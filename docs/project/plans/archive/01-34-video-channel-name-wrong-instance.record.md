# Build record - 34-video-channel-name-wrong-instance

Written by the `dev-flow` workflow. The plan it accompanies is `docs/project/plans/01-34-video-channel-name-wrong-instance.md`.

**Nothing but the workflow writes this file.** It carries the evidence each gate turned on: the baseline, both auditor verdicts verbatim, every self-check table, every red and its reason, every checkpoint outcome, and every amendment the operator approved to a settled section of the plan.

## Run state

<!-- dev-flow:state
```json
{
  "version": 1,
  "request": "# `videos.channel_name` holds another instance's channel name\n\nStatus: bug, ready-for-agent\nOrigin: `docs/project/issues/plan.md`, \"Proposed new issue 34\", measured on `whitelist.db` during the session that wrote that plan (2026-09-27)\n\n## Problem\n\nMost rows in `videos` carry a `channel_name` that belongs to a different channel. The stored name is the name of the channel that has the same numeric `channel_id` on a different instance. The `channels` table, joined on `(channel_id, instance_domain)`, holds the correct names.\n\n## Observed\n\n- On `whitelist.db`, 851,810 of 890,052 videos have a `channel_name` that does not match their own `channel_url`.\n- Example: tube.sasek.tv channel 13 is stored as \"Tour de France des Familles\", but its URL is `/video-channels/hochzeiten`.\n- Not re-measured when this issue was filed. The figures come from the plan session.\n\n## Impact\n\n- **Search:** `videos_fts` indexes `videos.channel_name` (triggers at `engine/server/db/jobs/sync-whitelist.py:272-283`). A query for a channel's name therefore matches another channel's videos.\n- **Cards:** the `channel_name` fallback at `client/frontend/src/components/video-card.ts:142` builds wrong channel links. The visible label is correct, because cards show `channel_display_name` from the `channels` join.\n\n## Probable source (not traced)\n\n- The crawler's video writer. `engine/crawler/src/videos-worker.ts:660-662` resolves `channelName` from the crawl job's `channel.displayName` first, then from the video's own `channel.displayName`. The row is written by the upsert in `engine/crawler/src/db.ts` (around `:770-779`).\n- Nobody has confirmed which step pairs a `channel_id` with the wrong instance: the crawler writer, the crawl job's channel lookup, or `sync-whitelist.py` copying rows into `whitelist.db`.\n\n## Repair (candidate, not chosen)\n\n- Fix the writer so that new rows get their own channel's name.\n- Correct existing rows from `channels` on `(channel_id, instance_domain)`, then rebuild `videos_fts`.\n- That repair is a data migration against the shared `whitelist.db`. It runs on main after the merge, never from a worktree (see \"Rules\" in `plan.md`).\n\n## Related\n\n- `plan.md` puts this issue in tier P1 and wave 1, lane 1c.\n- Issue 27 (`27-crawler-seed-instance-mode.md`) touches the same crawler code. `plan.md` puts it in lane 3d, after this issue.\n\n## Comments\n\n### Triage\n\n**Established:**\n\n- **Re-measured on `whitelist.db` (read-only).** Every video joins its own channel on `(channel_id, instance_domain)`. For 659,750 of 890,052 videos, `videos.channel_name` matches neither that channel's `display_name` nor its handle. 657,476 of those (over 99.6%) carry the `display_name` of the channel with the same `channel_id` on another instance. The issue's example checks out: tube.sasek.tv channel 13 holds \"Tour de France des Familles\", the name of `www.komitid.tv` channel 13. Its own name is \"Hochzeiten / Familie Sasek\". 49,200 `channel_id` values occur on more than one instance.\n- **The crawl DB has the same fault.** In `engine/crawler/data/crawl.db`, 661,306 of 891,621 videos mismatch. `sync-whitelist.py` reloads `whitelist.db` from it, so a repair of `whitelist.db` alone would be undone by the next sync. The updater's merge rule for `videos` is `INSERT_ONLY`, so it never corrects existing prod rows.\n- **Root cause: the crawler's video worker.** It builds its channel-metadata map keyed by `channel_id` alone across every host, and looks channels up by `channel_id` alone. When an id repeats across instances, the last host listed wins. The video row then takes that entry's `displayName` as `channel_name`. The row's `channel_url` (taken from the video's own `channel.url`) and the crawl slug come out right. This matches the data: `channel_url` is never empty.\n- **Impact, corrected:**\n  - **Search:** `videos_fts` indexes `channel_name`, so a channel-name query matches another channel's videos. This is real.\n  - **Embeddings (not in the original issue):** `build-video-embeddings.py` appends `channel: <channel_name>` to each video's embedding text. About 74% of vectors carry another channel's name, which pulls unrelated videos together in similar, up-next and vector search.\n  - **Cards: effectively none.** The `channel_name` fallback in `video-card.ts` only builds a link when `channel_url` is empty (0 rows). The Engine's `/api/video` prefers `channel_display_name`, and rewrites `channel_name` correctly for any video that is viewed.\n- **Maintainer decision on scope:** fix the writer, repair both databases, and rebuild `videos_fts`. Re-embedding is a separate operator step (below). Removing `channel_name` from the embedding text is not part of this issue.\n\n### Follow-up operator step (not the agent's)\n\nAfter the repair has run on main, the embeddings still carry the wrong channel names until an operator runs `build-video-embeddings.py --force` on `whitelist.db`, then `build-ann-index.py` and `precompute-similar-ann.py`. Plan 17 (`docs/project/plans/17-stable-ann-ids.md`) also migrates `video_embeddings` and rebuilds the index. Schedule the re-embed with plan 17's cutover so the index is rebuilt once.\n\n## Agent Brief\n\n**Category:** bug\n**Summary:** The crawler must store each video's own channel name, and existing rows in the crawl DB and the whitelist DB must be corrected, with the search index rebuilt to match.\n\n**Current behavior:**\nThe video crawl builds a map of channel metadata (slug, display name, URL) keyed by `channel_id` only, from every channel on every crawled host, and looks each channel up by `channel_id` only. PeerTube channel ids are small per-instance integers, and 49,200 of them repeat across instances. So a video's row usually receives the display name of whichever same-id channel on another host was listed last, and that value is written to `videos.channel_name`. About 74% of video rows in both `crawl.db` and `whitelist.db` are wrong, while the `channels` table holds the correct `display_name` for every `(channel_id, instance_domain)`. `videos_fts` indexes the wrong names.\n\n**Desired behavior:**\n- **Writer.** The video crawl resolves channel metadata by `(instance_domain, channel_id)`, so a newly written or updated video row's `channel_name` is its own channel's display name, from the crawl's channel list or else from the video payload's own channel. A channel id shared across hosts never lends one host's name to another host's videos.\n- **Repair.** An operator-runnable, idempotent repair sets every `videos.channel_name` to the `display_name` of the `channels` row with the same `(channel_id, instance_domain)`, wherever the two differ and that `display_name` is non-empty. It works on either database: the crawler's `crawl.db` and the Engine's `whitelist.db`. It reports how many rows it changed. A second run changes 0 rows.\n- **Search index.** After the repair of `whitelist.db`, `videos_fts` reflects the corrected names: a search for a channel's own display name finds that channel's videos, and a search for another instance's same-id channel name no longer finds them through `channel_name`. Its row count still equals `videos`.\n- **Runs on main.** The repair is a migration of shared databases. Documentation says to run it on main after merge, never from a worktree. Runbooks (`DATA_BUILD.md`, or wherever the dataset steps live) name the command, which databases to point it at, and the follow-up re-embed step in this issue's comments.\n\n**Key interfaces:**\n- The video crawl's channel-metadata map and its lookup. The key becomes host plus channel id.\n- The video-row builder's channel-name resolution: its precedence (crawl channel list first, then the video payload's channel) stays as it is.\n- A new repair command or job taking a database path, beside the existing dataset jobs, following their CLI style.\n- `videos_fts` rebuild: reuse the existing FTS rebuild helper the sync job uses, rather than a new one.\n\n**Acceptance criteria:**\n- [ ] A crawl fixture with two hosts that share a `channel_id` but have different channel names writes each host's videos with their own channel's name. The test fails on today's code.\n- [ ] On a fixture DB with mismatched `videos.channel_name` values, the repair sets each to its own channel's `display_name`. It leaves already-correct rows and rows whose channel has an empty `display_name` untouched, reports the changed count, and a second run changes 0 rows.\n- [ ] After the repair on a fixture `whitelist.db`, an FTS query for the correct channel name returns that channel's videos. A query for the other instance's name does not return them, and `videos_fts` has as many rows as `videos`.\n- [ ] The repair runs against both database shapes: `crawl.db`'s schema and `whitelist.db`'s schema.\n- [ ] The existing active suite stays green, including the crawler host-normalisation tests.\n- [ ] The runbook states the order: merge, then the repair on `crawl.db` and `whitelist.db` from main, then the operator re-embed step.\n- [ ] The agent does not run the repair against the real `crawl.db` or `whitelist.db`.\n\n**Out of scope:**\n- Re-embedding, ANN rebuild and similarity precompute (the operator follow-up above).\n- Changing what `build-video-embeddings.py` puts in the embedding text.\n- The `channels` table (it holds the correct names), and the Engine's `/api/video` write-back.\n- Issue 27 (crawler seed instance mode), which touches the same crawler module later.",
  "request_source": "read from docs/project/issues/34-video-channel-name-wrong-instance.md",
  "slug": "34-video-channel-name-wrong-instance",
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
    "9": "done"
  },
  "phases": [
    {
      "n": "1",
      "kind": "code",
      "name": "Crawler keys channel metadata by host and id",
      "checkpoint": "`test_crawl_writes_each_hosts_own_channel_name(tmp_path)` in the new `tests/active/test_channel_names.py`. Seam: the compiled `crawlVideos` exported by `engine/crawler/dist/videos-worker.js`. The test runs it under `node --input-type=module -e` with `cwd=engine/crawler` against two stdlib `ThreadingHTTPServer`s on `127.0.0.1` ephemeral ports and a temp `crawl.db` built from `engine/crawler/schema.sql`. Both channels rows share `channel_id` \"7\" and have different display names and URLs. The test asserts exact equality of `{(instance_domain, video_id): (channel_name, channel_url)}` read from `videos`. Harness precedent: `test_host_normalisation.py::test_crawler_dist_returns_pinned_values`. The test copies its `_git` / `_dist_is_stale` gates and `BUILD_HINT`. A missing node or git, a missing or stale dist, or a nonzero node exit fails the test and never skips it. On today's code the test fails deterministically, because the id-only map keeps one entry for \"7\".",
      "intent": "`crawlVideos` in `engine/crawler/src/videos-worker.ts` (and its committed `dist/videos-worker.js`) looks up channel metadata by lowercased host plus channel id. As a result, each host's crawled videos carry that host's own channel metadata, even when a channel id repeats across instances.",
      "clauses": [
        {
          "id": "C1",
          "text": "Each host's crawled videos have `channel_name` equal to the `display_name` of the channel on that same host."
        },
        {
          "id": "C2",
          "text": "Each host's crawled videos have `channel_url` equal to the `channel_url` of the channel on that same host."
        }
      ],
      "files": [
        "engine/crawler/src/videos-worker.ts (EDITED)",
        "engine/crawler/dist/videos-worker.js (EDITED)",
        "tests/active/test_channel_names.py (NEW)"
      ],
      "done": true,
      "outcome": "### `engine/crawler/src/videos-worker.ts`\n- `crawlVideos` now keys the `channelMeta` map by `channelMetaKey(channel.instance_domain.toLowerCase(), channel.channel_id)` instead of by `channel.channel_id` alone. Before, when two instances had the same channel id, the later row overwrote the earlier one and both hosts got the same `channel_name`/`channel_url`.\n- `processInstance` looks up metadata with `channelMetaKey(normalizedHost, item.channelId)`. `normalizedHost` is already lowercased, so both sides of the lookup use the same host form.\n- New helper `channelMetaKey(host, channelId)` returns `` `${host}/${channelId}` ``. A host cannot contain `/`, so two different host/id pairs can never produce the same key. It has a one-line JSDoc comment explaining why ids need the host, matching the file's other function comments.\n\n### `engine/crawler/dist/videos-worker.js`\n- Edited by hand to match the source change in the style tsc produces here (same two call sites, plus `channelMetaKey` with its JSDoc and no type annotations). I have no shell, so I could not run `npm run build`. The dist was saved after the source, so its mtime is newer and the checkpoint's staleness check, which compares mtimes on a dirty tree, will pass. There is no source map to update.\n\n### `tests/active/test_channel_names.py`\n- Not created. It is the checkpoint's permanent location, and this turn was limited to production code. The gating checkpoint stays at `tests/tmp/test_34_video_channel_name_wrong_instance_phase1.py`, unchanged."
    },
    {
      "n": "2",
      "kind": "code",
      "name": "Repair function corrects channel names",
      "checkpoint": "`test_repair_sets_each_video_to_its_own_channel_name(jobs, seeded_db)`. Seam: the in-process function `repair_channel_names(conn)` in `repair-video-channel-names.py`. The job is loaded with the `_load_job` importlib loader copied from `test_host_normalisation.py`. The fixture `seeded_db` is parametrised over the `crawl` shape (`schema.sql`) and the `whitelist` shape (`ensure_content_schema` from the loaded `sync-whitelist.py`). `_seed` loads the v1\u2013v7 / channels 7, 8, 9 table from the draft. Asserts: the returned count is 3; the `video_id -> channel_name` dict equals the expected column; `channels` equals its pre-repair snapshot; a second call returns 0 and leaves the dict unchanged; `has_videos_fts` is True exactly for the whitelist parameter. Every DB is under `tmp_path`.",
      "intent": "The new job `engine/server/db/jobs/repair-video-channel-names.py` exposes `repair_channel_names`. It sets each video's `channel_name` to the non-empty `display_name` of its own `(channel_id, instance_domain)` channel and returns how many rows it changed.",
      "clauses": [
        {
          "id": "C1",
          "text": "After a repair, videos with a foreign or NULL `channel_name` carry their own channel's `display_name`. Already-correct rows, rows whose channel has an empty, NULL or absent display name, and the `channels` table are unchanged."
        },
        {
          "id": "C2",
          "text": "The repair returns the number of rows it changed, and a second run returns 0."
        }
      ],
      "files": [
        "engine/server/db/jobs/repair-video-channel-names.py (NEW)",
        "tests/active/test_channel_names.py (EDITED)"
      ],
      "done": true,
      "outcome": "### `engine/server/db/jobs/repair-video-channel-names.py` (NEW)\nA new job module with two functions, stdlib `sqlite3` only:\n- `repair_channel_names(conn) -> int` runs one `UPDATE videos` statement inside `with conn:`, so it commits. It sets `channel_name` to the `display_name` of the channel matching the video's own `(channel_id, instance_domain)`. A row is only touched when that channel exists, its `display_name` is not NULL or empty, and the stored name differs from it (`IS NOT`, so NULL stored names get repaired too). It returns `cursor.rowcount`, the number of rows it changed, which makes a second run return 0. `channels` is only read, never written. On the whitelist shape, the existing `videos_fts_au` trigger re-indexes each changed row.\n- `has_videos_fts(conn) -> bool` checks `sqlite_master` for the `videos_fts` table. It is True on the whitelist shape and False on the crawl shape.\n\nThere is no CLI entry point yet. The checkpoint only exercises the functions, and this phase's intent only calls for exposing `repair_channel_names`.\n\nI did not touch `tests/active/test_channel_names.py`, which the phase lists as EDITED. It does not exist in the worktree yet, and nothing in this phase's checkpoint needs it. I read that entry as the promotion target for the checkpoint, which the workflow handles.\n\nI checked the behaviour with a throwaway probe (`tests/tmp/probe_repair_rowcount.py`), using the same seed shape as the checkpoint on both a crawl-schema and a whitelist-schema database:\n- **Both shapes:** the first call returned 3 and the second returned 0. After reopening the database, v1 and v7 read `A` and v2 read `B`, while v3\u2013v6 kept their stored names.\n- **Whitelist shape:** `has_videos_fts` was True, and `rowcount` was still 3 even with the FTS triggers firing. An FTS5 `integrity-check` passed after the update, and `channel_name:A` matched rowids 1 and 7.\n\nI have no tool that deletes files, so the probe file is still in `tests/tmp/` and should be removed. It is not part of the phase."
    },
    {
      "n": "3",
      "kind": "code",
      "name": "\"`. Asserts: `Alphachan` gives {v1, v7} and `Betachan` gives {v2, v3}, so v1's stale foreign name is gone; `COUNT(*)` on `videos_fts` equals `COUNT(*)` on `videos` (7).</checkpoint>\n<name>Repair rebuilds the search index",
      "checkpoint": "`test_repaired_fts_finds_own_name_not_foreign_name(jobs, tmp_path)`. Seam: the `videos_fts` table of a whitelist-shape temp DB. The DB is created with `ensure_content_schema`, seeded with stale names (so the index holds them), and then repaired through `repair_channel_names`. The test queries `SELECT v.video_id FROM videos_fts JOIN videos v ON v.rowid = videos_fts.rowid WHERE videos_fts MATCH ?` with `channel_name : \"<name>\"`. Asserts: `Alphachan` gives {v1, v7} and `Betachan` gives {v2, v3}, so v1's stale foreign name is gone; `COUNT(*)` on `videos_fts` equals `COUNT(*)` on `videos` (7).",
      "intent": "On a database that has `videos_fts`, the repair runs between `sync-whitelist.py`'s trigger drop and recreate and then rebuilds the index, so full-text search reflects the corrected channel names in full.",
      "clauses": [
        {
          "id": "C1",
          "text": "After the repair, a `channel_name` MATCH for a channel's own name returns that channel's videos, and a MATCH for the other instance's same-id name does not return them."
        },
        {
          "id": "C2",
          "text": "After the repair, `videos_fts` holds as many rows as `videos`."
        }
      ],
      "files": [
        "engine/server/db/jobs/repair-video-channel-names.py (EDITED)",
        "tests/active/test_channel_names.py (EDITED)"
      ],
      "done": true,
      "outcome": "I ran none of the gating tests myself. Everything I checked came from a throwaway probe, described below.\n\n### `engine/server/db/jobs/repair-video-channel-names.py`\n- **New `_load_sync_whitelist()`.** Loads `sync-whitelist.py` with `importlib.util.spec_from_file_location`, because its hyphenated name rules out a normal import. This lets the job reuse the file's `videos_fts` helpers instead of copying FTS SQL. It runs only on the FTS path, so crawl.db never loads that file.\n- **`repair_channel_names(conn)` without `videos_fts` (crawl shape).** Unchanged: one UPDATE inside `with conn:`, returning the number of rows changed.\n- **`repair_channel_names(conn)` with `videos_fts` (whitelist shape).** Follows the same order as `rebuild_content_tables`:\n  1. `drop_videos_fts_triggers`\n  2. the UPDATE, with `rowcount` read straight away\n  3. `create_videos_fts_triggers`\n  4. `rebuild_videos_fts`\n  5. compare the rebuilt count with `COUNT(*)` on `videos`, and raise `RuntimeError` in `sync-whitelist.py`'s wording if they differ\n  6. `conn.commit()`\n- **Rebuild on every run.** The rebuild and count check run even when nothing changed. So re-running the job fixes an index left stale by an interrupted run, and it also fixes drift that the per-row trigger `'delete'` cannot mend.\n- **`rat-tail:` comment.** Records that the helpers use `executescript`, which commits. The update is therefore already committed before the rebuild, and a failed rebuild is recovered by running the job again, not by rollback. Upgrade path: have the helpers run their SQL through `conn.execute` instead.\n- **Docstrings.** The module and function docstrings now describe the rebuild.\n\n**Probe results.** The probe (`tests/tmp/probe_34_phase3_impl.py`) built a smaller version of the checkpoint's drifted index on a whitelist-shaped database: v1 corrected and v8 inserted while the triggers were dropped.\n- The second run returned 0.\n- After reopening, `channel_name : \"Alphachan\"` matched `['v1', 'v7']` and `\"Betachan\"` matched `['v2']`.\n- `videos_fts_docsize` held 4 rows for 4 videos, and the FTS5 integrity-check passed.\n- On a crawl-shaped database, `has_videos_fts` was False.\n\nI have no delete tool, so I emptied the probe file instead of removing it. It is part of no phase and should be deleted.\n\n### `tests/active/test_channel_names.py`\nNot touched. As in Phase 2, I read the listing as the checkpoint's promotion target, which the workflow handles."
    },
    {
      "n": "4",
      "kind": "code",
      "name": "Repair CLI",
      "checkpoint": "`test_cli_requires_db_and_logs_changed_count(tmp_path)`. Seam: the script's command line, run through `subprocess.run([sys.executable, str(REPAIR_JOB), ...])`. Asserts: a bare invocation exits with return code 2. Against an inline-seeded crawl-shape DB under `tmp_path`, the run exits 0, and `re.search(r\"channel names repaired rows=(\\d+)\", proc.stderr)` gives 3. A second run gives 0.",
      "intent": "`repair-video-channel-names.py` runs as a command that refuses to start without an explicit `--db` and logs the number of rows it changed.",
      "clauses": [
        {
          "id": "C1",
          "text": "Invoking the job without `--db` exits with an argparse usage error (return code 2)."
        },
        {
          "id": "C2",
          "text": "Invoking the job with `--db` logs `channel names repaired rows=N` with the changed count."
        }
      ],
      "files": [
        "engine/server/db/jobs/repair-video-channel-names.py (EDITED)",
        "tests/active/test_channel_names.py (EDITED)"
      ],
      "done": true,
      "outcome": "### `engine/server/db/jobs/repair-video-channel-names.py`\n- Added a command line that follows `recompute-popularity.py` and `sync-whitelist.py`. It appends `engine/server` to `sys.path` and imports `CompactHelpFormatter` from `scripts.cli_format`.\n- Added `main()`, called under an `if __name__ == \"__main__\"` guard. It uses argparse with `CompactHelpFormatter` and a single `--db PATH` argument that is required and has no default. The neighbouring jobs default to the shared `whitelist.db`, and a migration run with no arguments must never hit that by accident.\n- Logging is set up with `logging.basicConfig(level=logging.INFO, format=\"%(levelname)s %(message)s\")`.\n- A `--db` path that is not an existing file is rejected with `parser.error(\"database not found: ...\")`, which exits 2. Without this check, `sqlite3.connect` would quietly create an empty file and then fail on the missing tables.\n- After the path check, `main()` opens the connection, calls the existing `repair_channel_names(conn)`, closes the connection in `finally`, and logs `channel names repaired rows=%d`.\n- `repair_channel_names`, the SQL and the FTS handling are unchanged.\n\n### `tests/active/test_channel_names.py`\n- Not touched. It does not exist in the worktree yet, and this phase's checkpoint lives in `tests/tmp/`. I take the EDITED entry to mean the checkpoint gets promoted there, which the workflow handles. Phase 3 read it the same way.",
      "beyond": "tests/tmp/probe_34_phase4_impl.py - a throwaway probe. It checked that the edited module still loads in-process through `importlib` (phases 2 and 3 load it that way) now that it changes `sys.path` and imports `scripts.cli_format`. It also checked the four CLI cases. A bare run exits 2 with `the following arguments are required: --db`. A missing `--db` path exits 2 with `database not found` and creates no file. The seeded crawl DB logs `INFO channel names repaired rows=3`, and a second run logs `rows=0`. I have no delete tool, so please remove it. `tests/tmp/probe_34_phase4_cli.py`, left over from authoring the checkpoint, is still there too and can go with it."
    }
  ],
  "digests": {
    "tests/tmp/test_34_video_channel_name_wrong_instance_phase1.py": "7d958f8a0cdd15e77c451cb9780a1869f05f0674d09f9346860eba854bd7d7fb",
    "tests/tmp/test_34_video_channel_name_wrong_instance_phase2.py": "8d2b3fd2194f2b958181d4332d41c06420cc384d765590c77cb28cbce519f0b7",
    "tests/tmp/test_34_video_channel_name_wrong_instance_phase3.py": "1c98b78951736f21bdbb54009b1e415d373af6b5eed6c2c415bf5cec5c1b87b9",
    "tests/tmp/test_34_video_channel_name_wrong_instance_phase4.py": "8220983f2aede2a9f9010347cd2ec7bfce65c5b36cc6e77bfed4aafa4f9c49ec"
  },
  "paths": {
    "active": "tests/active",
    "working": "tests/tmp",
    "plans": "docs/project/plans",
    "delete_me": "delete_me",
    "archive": "tests/archive",
    "project_dir": "/home/enduser/code/PeerTube-browser/.worktrees/34",
    "record": "tests/last_test_validation.json",
    "output": "tests/last_test_output.txt"
  },
  "baseline": {
    "code": 0,
    "variant": false
  },
  "sessions": [
    "20260927T095149-9cfa-dev-flow"
  ],
  "plan": "docs/project/plans/01-34-video-channel-name-wrong-instance.md",
  "record": "docs/project/plans/01-34-video-channel-name-wrong-instance.record.md",
  "replies": {
    "step_1_gather_requirements": "<requirements>\n### Purpose\n\nEvery row in `videos` must carry its own channel's display name in `channel_name`. Today about 74% of rows in both `engine/crawler/data/crawl.db` and `whitelist.db` hold the display name of the channel with the same numeric `channel_id` on another instance. PeerTube channel ids are small per-instance integers, and 49,200 of them repeat across instances. Because of the wrong names, a channel-name search (`videos_fts` indexes `channel_name`) matches another channel's videos, and about 74% of video embeddings carry a foreign channel name (`build-video-embeddings.py` appends `channel: <channel_name>`). The `channels` table holds the correct `display_name` for every `(channel_id, instance_domain)`. Card links are effectively unaffected, because `channel_url` is never empty.\n\n### Root cause (established by triage, confirmed in the tree)\n\nIn `engine/crawler/src/videos-worker.ts`, `crawlVideos` builds `channelMeta` as `Map<string, ChannelMeta>` keyed by `channel.channel_id` alone (lines ~163-172). It is built from `store.listChannelsWithVideos(1, hosts)`, which returns channels from every crawled host. `processInstance` looks it up with `channelMeta.get(item.channelId)` (line ~289), again without the host. When an id repeats across hosts, the last listed host wins. That entry's `displayName` then becomes the video row's `channel_name` (resolution around lines 660-662, row written by the upsert in `engine/crawler/src/db.ts`). `sync-whitelist.py` copies `crawl.db` into `whitelist.db`, so both databases carry the fault. The updater's `videos` merge is `INSERT_ONLY`, so it never corrects existing prod rows.\n\n### Requirement 1: Writer fix\n\n- The video crawl's channel-metadata map is keyed on host plus channel id, and every lookup uses both.\n- The host part of the key must be in the same form on both sides. The map is built from `channels.instance_domain`. The lookup happens in `processInstance`, which uses `host.toLowerCase()` (`normalizedHost`), while the work item carries `instanceDomain`. The key must match for every channel whose metadata exists, so a normalisation mismatch must not silently drop metadata.\n- The channel-name precedence stays as it is: first the crawl channel list's `displayName` (now the correct host's), then the video payload's own `channel.displayName` / `display_name`.\n- The crawl slug (`channelSlug`) and `channelUrl` taken from the meta are resolved by the same host-aware key.\n- Nothing else in the crawler changes. Issue 27 (seed instance mode) is out of scope.\n\n### Requirement 2: Repair job\n\n- A new operator-runnable Python job in `engine/server/db/jobs/`, following the existing jobs' CLI style (argparse, a `--db <path>` argument, the same docstring and logging conventions as its neighbours, e.g. `sync-whitelist.py`, `recompute-popularity.py`).\n- For every `videos` row, it sets `channel_name` to the `display_name` of the `channels` row with the same `(channel_id, instance_domain)`. It does so only where that `display_name` is non-NULL and non-empty and differs from the current `channel_name`. Rows that are already correct, and rows whose channel has an empty or NULL `display_name` (or no channel row), are left untouched.\n- It reports the number of rows changed. It is idempotent: a second run changes 0 rows and reports 0.\n- It works on both database shapes: the crawler's `crawl.db` schema, which has no `videos_fts` (the crawler source defines no FTS table or triggers), and the Engine's `whitelist.db` schema.\n- It does not touch the `channels` table.\n\n### Requirement 3: Search index\n\n- When the target database has `videos_fts` (the `whitelist.db` shape), the repair leaves the index reflecting the corrected names. It reuses the existing helpers in `engine/server/db/jobs/sync-whitelist.py` (`drop_videos_fts_triggers`, `create_videos_fts_triggers`, `rebuild_videos_fts`) rather than writing new FTS code. Those helpers follow the file's bulk pattern: drop the triggers, run the bulk update, recreate the triggers, rebuild. `sync-whitelist.py` has a hyphenated filename, so it cannot be imported by the normal module syntax; reuse it the way other code in the repo already loads hyphenated job modules, or by an equivalent means.\n- After the rebuild, the `videos_fts` row count must equal the `videos` row count. The job fails loudly if they differ, matching the check `sync-whitelist.py` already makes.\n- Result: an FTS search for a channel's own display name finds that channel's videos. A search for another instance's same-id channel name no longer finds them through `channel_name`.\n- When `videos_fts` is absent (`crawl.db`), the job skips the FTS steps without error.\n\n### Requirement 4: Tests (in `tests/active`)\n\n- A crawl fixture with two hosts that share a `channel_id` but have different channel display names. It asserts that each host's videos are written with their own channel's name. This test must fail on today's code. Crawler tests in this repo run the compiled crawler under node (see `tests/active/test_host_normalisation.py`, which runs `engine/crawler/dist/*.js`, and fails rather than skips when node or the dist is missing or stale). The new test follows that convention.\n- A repair test on a fixture DB with mismatched `channel_name` values. It checks that each mismatched row is set to its own channel's `display_name`, that already-correct rows and rows whose channel has an empty `display_name` are untouched, and that the reported changed count is correct. A second run must change 0 rows.\n- The repair test runs on both schemas: a `crawl.db`-shaped fixture (no FTS) and a `whitelist.db`-shaped fixture (with `videos_fts` and its triggers, created via `sync-whitelist.py`'s `ensure_content_schema` or equivalent).\n- An FTS test on the `whitelist.db` fixture, after the repair: a query for the correct channel name returns that channel's videos, a query for the other instance's name does not return them, and `videos_fts` has as many rows as `videos`.\n- All fixtures are temporary. No test touches the real `crawl.db` or `whitelist.db`.\n\n### Requirement 5: Runbook\n\n- `DATA_BUILD.md` (which already documents the `crawl.db` and `sync-whitelist.py` steps) gains a section naming the repair command and the order to follow:\n  1. Merge to main.\n  2. From main, never from a worktree, run the repair against `engine/crawler/data/crawl.db`, then against `whitelist.db`. That means every copy of `whitelist.db`, including the prod/server database, because the updater's `INSERT_ONLY` merge will never correct existing prod rows.\n  3. The operator follow-up: `build-video-embeddings.py --force` on `whitelist.db`, then `build-ann-index.py`, then `precompute-similar-ann.py`, scheduled with plan 17's (`docs/project/plans/17-stable-ann-ids.md`) cutover so the index is rebuilt only once.\n- The runbook states that the repair is a migration of shared databases and runs on main after merge only.\n\n### Constraints\n\n- The agent must not run the repair against the real `crawl.db` or `whitelist.db`.\n- The existing active suite (`tests/active`) stays green, including `test_host_normalisation.py`. Pre-build baseline: the suite exits with code 0.\n- Smallest change that works: stdlib only for the Python job, no new dependencies, no new abstractions.\n\n### Out of scope\n\n- Re-embedding, the ANN rebuild and the similarity precompute (operator follow-up only).\n- Changing the embedding text in `build-video-embeddings.py`.\n- The `channels` table, and the Engine's `/api/video` write-back.\n- Issue 27 (crawler seed instance mode).\n- `client/frontend/src/components/video-card.ts`: no change.\n\n### Acceptance criteria\n\n- [ ] A two-host shared-`channel_id` crawl fixture writes each host's videos with their own channel's name. The test fails on today's code.\n- [ ] The repair corrects mismatched rows, leaves correct rows and empty-`display_name` rows untouched, reports the changed count, and a second run changes 0.\n- [ ] After the repair on a `whitelist.db` fixture, an FTS query for the correct name returns the channel's videos, a query for the other instance's name does not, and the `videos_fts` count equals the `videos` count.\n- [ ] The repair runs on both the `crawl.db` and `whitelist.db` schemas.\n- [ ] The active suite stays green, including the host-normalisation tests.\n- [ ] `DATA_BUILD.md` states: merge, then the repair from main on `crawl.db` and on every `whitelist.db` (prod included), then the operator re-embed step.\n- [ ] The repair is never run against the real databases by the agent.\n</requirements>\n\n<conflicts>\nThe brief says the repair must \"rebuild videos_fts\", but whitelist.db already has an AFTER UPDATE trigger (sync-whitelist.py:279-284) that keeps videos_fts in step with any UPDATE of channel_name. A plain UPDATE would therefore already leave the index correct. The rebuild is kept anyway: it follows the file's drop-triggers/bulk-update/rebuild pattern, and a single bulk rebuild is cheaper than ~660k per-row trigger writes. This is noted so the design doesn't treat the rebuild as the thing that makes the index correct.\nThe brief says to \"reuse the existing FTS rebuild helper the sync job uses\", but that helper lives in engine/server/db/jobs/sync-whitelist.py, whose hyphenated name cannot be imported normally. Reusing it needs an importlib-style load, or moving the helpers into an importable module. The design has to pick one.\nThe brief says to repair \"both databases\" (crawl.db and whitelist.db), but the updater merges videos INSERT_ONLY into prod, so a separate prod whitelist.db copy would keep the wrong names. The operator resolved this: the runbook tells the operator to run the repair on every whitelist.db copy, prod included.\nChannel-meta key normalisation: channelMeta is built from channels.instance_domain as stored, while processInstance looks up with host.toLowerCase(). If stored domains are not already lowercase, a host-aware key built naively would miss every lookup and fall back to the payload name. The design must make both sides use the same form.\n</conflicts>",
    "step_2_develop_solution": "<initial_solution>\n### Approach\n\nFour changes, each tied to a requirement: a keying fix in one function of the crawler, one new Python job, one new test module, and one new runbook section. I read the files each change touches: `videos-worker.ts` (map build, `processInstance`, `processChannel`, `toVideoRow`), `db.ts` (`listChannelsWithVideos`, `prepareVideoProgress`, `listVideoWorkItems`, `listInstances`, the upsert), `http.ts`, `host-filters.ts`, `sync-whitelist.py` (FTS helpers, `ensure_content_schema`, `rebuild_content_tables` and its count check), `recompute-popularity.py`, `test_host_normalisation.py` and `DATA_BUILD.md`.\n\n**Requirement 1 (writer fix).** In `crawlVideos`, the `channelMeta` map gets a composite string key built from the host and the channel id, for example `host/channel_id`. A `/` cannot appear in a normalised host, and a host can carry a `:port`, so the separator cannot collide with a real value. The value type stays `ChannelMeta` and no new type is added. The host part is lowercased on both sides:\n- When the map is built, from `channel.instance_domain`.\n- At the lookup in `processInstance`, which already holds `normalizedHost = host.toLowerCase()`, together with `item.channelId`.\n\nThis follows the host through the code. `processInstance`'s `host` is the grouping key `item.instanceDomain`. That value comes from `video_crawl_progress.instance_domain`, which `prepareVideoProgress` copied verbatim from `channels.instance_domain`. So both sides start from the same column, and applying the same lowercasing to both means a mixed-case stored domain still matches. No metadata can be dropped by a normalisation mismatch.\n\n`processChannel` and `toVideoRow` are unchanged. They already take `meta.channelSlug`, `meta.displayName` and `meta.channelUrl` from the single `meta` handed to them, so all three now come from the correct host's entry. The precedence (crawl list `displayName` first, then the payload's `channel.displayName` / `display_name`) is untouched. Nothing else in the crawler changes. Because `engine/crawler/dist/` is committed, the build is re-run and the regenerated `dist/videos-worker.js` is committed with the source; only that dist file should differ.\n\n**Requirement 2 (repair job).** A new file, `engine/server/db/jobs/repair-video-channel-names.py`, laid out like its neighbours:\n- Shebang, a one-paragraph module docstring, and the same `script_dir` / `sys.path` preamble.\n- argparse with `CompactHelpFormatter` and `--db PATH`.\n- `logging.basicConfig` at INFO and a `main()` behind `if __name__ == \"__main__\"`.\n\nThe repair is one set-based UPDATE on `videos`. It sets `channel_name` from a correlated subquery on `channels` matched by `(channel_id, instance_domain)`, which is the `channels` primary key, so each lookup is indexed. The WHERE clause requires three things of the channel row:\n- it exists;\n- its `display_name` is non-NULL and not `''`;\n- its `display_name` IS NOT the current `channel_name`. `IS NOT` rather than `!=`, so a row whose `channel_name` is NULL is also corrected.\n\nThe changed count is the UPDATE cursor's `rowcount`, logged in the neighbours' `key=value` style. Rows that are already correct, rows with an empty or NULL display name, and rows with no channel row never match, so a second run changes 0 rows and reports 0. `channels` is only read.\n\n`--db` is **required**, with no default. Neighbours such as `recompute-popularity.py` default to the crawl DB path, but this job is a migration that is run deliberately against several named databases, and a default would let a bare invocation silently hit one of them.\n\n**Requirement 3 (search index).** The job checks `sqlite_master` for a `videos_fts` table.\n- If it is present, the job follows `rebuild_content_tables`' order: `drop_videos_fts_triggers`, the UPDATE, `create_videos_fts_triggers`, then `rebuild_videos_fts`. It then compares the returned count with `COUNT(*)` on `videos` and raises `RuntimeError` with the same wording `sync-whitelist.py` uses if they differ.\n- If it is absent (the `crawl.db` shape), only the UPDATE and commit run, and no FTS helper is called.\n\nThe helpers are reached by loading `sync-whitelist.py` with `importlib.util.spec_from_file_location` from the job's own directory. This is the loader `test_host_normalisation.py` and `test_similar.py` already use. Loading only runs that module's imports and its `sys.path` setup, because its `main()` is guarded.\n\nWhen FTS is present, the rebuild and count check run on **every** invocation, even when 0 rows changed. See the first risk below for why.\n\n**Requirement 4 (tests).** One new module, `tests/active/test_channel_names.py`.\n\n- **Crawl test.** Follows `test_host_normalisation.py`'s convention: it fails, rather than skips, when node is missing, the dist is missing, or `dist/videos-worker.js` is older than `src/videos-worker.ts`, using the same git-or-mtime staleness rule and the same build hint.\n  - It starts two stdlib `ThreadingHTTPServer`s on 127.0.0.1 with ephemeral ports, so the two hosts are `127.0.0.1:P1` and `127.0.0.1:P2` and no DNS is involved. Each serves `/api/v1/video-channels/<slug>/videos` with its own videos, and the payloads carry no `channel.displayName`.\n  - It creates a temp `crawl.db` from `engine/crawler/schema.sql`. It inserts both hosts into `instances`, and one `channels` row per host with the same `channel_id`, different `display_name`s, and `videos_count >= 1`.\n  - It runs the compiled `crawlVideos` under node with `concurrency 1`, `maxRetries 0`, a short timeout, and resume, tags and comments off. With `maxRetries 0` the https attempt against the plain-HTTP server fails once and `fetchPage` falls back to http.\n  - It asserts that each host's `videos.channel_name` equals its own channel's `display_name`, and also checks `channel_url`.\n  - On today's code, one of the two hosts always gets the other's name, whichever order the rows come back in, so the test fails deterministically.\n- **Repair tests.** Parametrised over two temp fixtures: a `crawl.db` shape (`schema.sql`) and a `whitelist.db` shape (`ensure_content_schema` from the loaded `sync-whitelist.py`, which creates `videos_fts` and its triggers). Each fixture seeds:\n  - mismatched rows (a foreign same-id name);\n  - an already-correct row;\n  - a row whose channel has an empty `display_name`;\n  - a row whose channel has a NULL `display_name`.\n\n  The test runs the job's repair function and asserts the exact changed count, each row's resulting name, and that a second run returns 0. The job is loaded by the same importlib loader. A single subprocess run of the CLI against a temp DB also checks the logged count.\n- **FTS test.** On the whitelist fixture after repair: a MATCH on `channel_name` for the correct name returns that channel's videos, a MATCH for the other instance's same-id name does not return them, and `COUNT(*)` on `videos_fts` equals the count on `videos`.\n- Every DB is under `tmp_path`, and no test references a real DB path.\n\n**Requirement 5 (runbook).** A new `DATA_BUILD.md` section after step 2, titled as a one-off repair of `channel_name`. It explains in one line why the repair is needed, states that it is a migration of shared databases that runs on main after merge only (never from a worktree), and lists the order:\n1. Merge.\n2. Run `repair-video-channel-names.py --db engine/crawler/data/crawl.db`.\n3. Run it again with `--db` on every copy of `whitelist.db`, the prod/server database included, because the updater's `INSERT_ONLY` merge never corrects existing rows.\n4. Operator follow-up, timed with plan 17's cutover so the index is rebuilt once: `build-video-embeddings.py --force` on `whitelist.db`, then `build-ann-index.py`, then `precompute-similar-ann.py`.\n\nThe agent never runs the job against the real databases. It is exercised only inside the tests' temp fixtures.\n\n### Alternatives considered\n\n- **Nested `Map<host, Map<channelId, ChannelMeta>>` instead of a composite string key.** Rejected: more code at both the build and the lookup, for a collision risk the `/` separator already rules out.\n- **Keying on the raw `instance_domain` on both sides (`item.instanceDomain` at lookup) instead of lowercasing both.** Also correct, since both come from the same column. Rejected: `processInstance` already works in `normalizedHost` and the video rows are written under it, so lowercasing both sides keeps one host form throughout.\n- **Updating with the triggers left in place, letting `videos_fts_au` fix the index row by row.** This would be transactional and need no rebuild. Rejected: the requirement asks for the helpers' bulk pattern. It is also fragile, because the per-row `'delete'` reuses the stored old values and would corrupt an index that had already drifted, whereas `rebuild` recovers from drift.\n- **A Python row loop with `executemany`, as in `recompute-popularity.py`.** Rejected: one set-based UPDATE is shorter, gives the changed count directly, and is faster on millions of rows.\n- **`UPDATE \u2026 FROM`.** Rejected: it needs SQLite 3.33 or later, and a correlated subquery works on any SQLite the servers run.\n- **Copying the FTS SQL into the new job.** Rejected: the requirement asks for reuse, and a second copy of the trigger SQL would drift from the first.\n- **A shared helper module for loading hyphenated jobs.** Rejected: a new abstraction for three lines that the repo already inlines.\n\n### Risks, gotchas and limitations\n\n- **The repair is not a single transaction on the FTS path.** The reused helpers call `executescript`, which COMMITs any open transaction first. So the UPDATE commits when the triggers are recreated, before the rebuild. A crash in between leaves corrected names with a stale index, and a later count mismatch raises after the data is already committed. Mitigation: the rebuild and count check run on every invocation when FTS is present, so re-running the job restores the index even though it reports 0 changed rows.\n- **Cost and locking on prod.** The rebuild re-indexes all of `videos_fts` each run. On the prod `whitelist.db` this is a long write that blocks other writers, such as the updater merge. The runbook will tell operators to run it outside an updater cycle.\n- **Exact `instance_domain` join.** The repair matches `videos.instance_domain` to `channels.instance_domain` exactly, the same join `sync-whitelist.py` uses. The crawler writes video rows under the lowercased host, while `channels` keeps the stored spelling. A channel stored in mixed case would therefore not be repaired. Hosts are already lowercased by `normalizeHostToken` when they enter the crawl, so this should not occur, but the repair does not guard against it.\n- **What counts as \"empty\".** \"Empty `display_name`\" means `''`. Whitespace-only names are not specially handled; the channel crawler's `toBoundedString` trims names and turns blanks into NULL, so none are expected.\n- **Committed dist.** If `dist/videos-worker.js` is not rebuilt and committed with the source change, the new crawl test fails on staleness by design.\n- **Crawl test environment.** The test needs node, `engine/crawler/node_modules` (better-sqlite3) and a built dist, and fails with the build hint when any is missing, as `test_host_normalisation.py` does. It binds to loopback ephemeral ports only.\n- **Load-time imports.** Loading `sync-whitelist.py` executes its module-level imports (`scripts.cli_format`, `server_config`, `data.moderation`). The repair job therefore depends on the Engine's server tree being present, which is true everywhere these jobs already run.\n\n### Tradeoffs the operator is asked to accept\n\n- `--db` is required, unlike the neighbours' defaulted `--db`: a small inconsistency in CLI style, in exchange for never repairing a database by accident.\n- Every run with FTS present pays a full FTS rebuild, even when nothing changed. The cost is time, and the benefit is that a crashed run is fixed by simply running it again.\n- The FTS path is not atomic, because the settled helpers commit internally. Recovery is to re-run, not rollback.\n- Until the operator's re-embed, ANN rebuild and precompute are done, embeddings keep carrying the old foreign channel names. Search text is correct straight after the repair; semantic similarity is only corrected at the plan-17 cutover.\n</initial_solution>\n\n<conflicts>\nnone\n</conflicts>",
    "step_3_identify_impacts": "<impacts>\n\n<impacts>\n<impact path=\"engine/crawler/src/videos-worker.ts\" element=\"crawlVideos(): the channelMeta map build (lines 163-172)\">\n**What changes.** The map key changes from `channel.channel_id` to a composite string: `channel.instance_domain.toLowerCase()`, then `/`, then `channel.channel_id`. The value (`ChannelMeta`: `channelSlug`, `displayName`, `channelUrl`) and the type `Map<string, ChannelMeta>` do not change.\n\n**What depends on it.**\n- `channels` comes from `store.listChannelsWithVideos(1, hosts)` (db.ts:1265-1278), optionally sliced by `maxChannels`. That query returns rows from every crawled host and filters `channel_name IS NOT NULL`, which is why ids collide across hosts.\n- The map is passed unchanged through `workerLoop` (line 191) into `processInstance`.\n- The same `channels` array feeds `store.prepareVideoProgress(channels, ...)` (line 175), so every work item has a matching map entry under the raw `instance_domain`.\n\n**Regression risk: low.**\n- Two `channels` rows could differ only by the case of `instance_domain` while sharing a `channel_id`. Their lowercased keys would collide and the last one listed would win. That is the old bug in a much narrower form. Hosts are normalised to lowercase by `normalizeHostToken` on entry, so such rows are not expected. I did not check the real DB for them.\n- The key string must be built the same way here and at the lookup. A mismatch, for example lowercasing only one side or using a different separator, silently gives `meta === undefined`. The name then falls back to the payload's `channel.displayName`, which the new test's payloads deliberately omit, so the test would catch this.\n</impact>\n<impact path=\"engine/crawler/src/videos-worker.ts\" element=\"processInstance() lookup `channelMeta.get(item.channelId)` (line 289)\">\n**What changes.** The lookup becomes `channelMeta.get(`${normalizedHost}/${item.channelId}`)`, where `normalizedHost = host.toLowerCase()` (line 285) is already in scope.\n\n**What depends on it.**\n- `host` is the key of `grouped`, which `groupByInstance` (lines 707-715) builds from `item.instanceDomain`. That value comes from `video_crawl_progress.instance_domain` (`listVideoWorkItems`, db.ts:1399-1424), which `prepareVideoProgress` (db.ts:1328-1346) copied verbatim from `channels.instance_domain`. Both sides of the key therefore start from the same column, as the plan says.\n- `meta` is handed to `processChannel` (line 290).\n\n**Regression risk: low.** This is the one line that fixes the bug. `workerLoop` and the `channelMeta` parameter types in `workerLoop` (line 260) and `processInstance` (line 280) keep their signatures.\n</impact>\n<impact path=\"engine/crawler/src/videos-worker.ts\" element=\"processChannel() (lines 425-468): slug and meta use\">\n**What changes.** Nothing in the code. What `meta` holds changes.\n\n**Correction to the plan.** The plan says the slug \"now comes from the correct host's entry\". In fact `channelSlug = item.channelName ?? meta?.channelSlug` (line 433): the slug is taken first from the per-host progress row. `prepareVideoProgress` writes that row's `channel_name`, and `listChannelsWithVideos` only returns channels where it is non-NULL. The slug was therefore already correct, and `meta.channelSlug` is a dead fallback in practice. The fix really changes only `displayName` and `channelUrl`, both passed on at lines 450-451.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"engine/crawler/src/videos-worker.ts\" element=\"toVideoRow() channel name and URL resolution (lines 660-664)\">\n**What changes.** Nothing in the code.\n- `channelName = toBoundedString(channel.displayName) ?? toBoundedString(channelRef?.displayName ?? channelRef?.display_name)`. The precedence is unchanged, as required, and the first term now comes from the correct host.\n- `channelUrl = toHttpUrlOrNull(channelRef?.url) ?? toHttpUrlOrNull(channel.channelUrl)`. The payload's own `channel.url` comes FIRST here, so `meta.channelUrl` is only a fallback.\n\n**What depends on it.**\n- `upsertVideos` (db.ts:1453) writes the row.\n- The ON CONFLICT clause (db.ts:1169-1195) overwrites `channel_name` and `channel_url` on every re-crawl, so after the fix a fresh crawl of `crawl.db` corrects rows by itself.\n\n**Regression risk: low.**\n- **The test's `channel_url` check.** It only exercises the fix if the fixture payload has no `channel.url`. Otherwise the payload URL wins whatever key is used.\n- **The URL value.** The fixture's `channels.channel_url` must be an absolute http(s) URL, or `toHttpUrlOrNull` returns NULL.\n- **Trimming.** `toBoundedString` trims the name and caps it at 200 characters, so the fixture's display names should be short and untrimmed, or the test's equality check fails.\n</impact>\n<impact path=\"engine/crawler/src/videos-worker.ts\" element=\"fetchPage() https\u2192http fallback (lines 581-619) and buildChannelVideosUrl() (624-636), used by the new crawl test\">\n**What changes.** Nothing.\n\n**How the test reaches its fake servers.**\n- `crawlChannelVideos` starts with `protocol = \"https:\"`. Against a plain-HTTP `ThreadingHTTPServer`, Node's fetch fails the TLS handshake, typically with EPROTO or `ERR_SSL_WRONG_VERSION_NUMBER`. Those codes are not in `isNoNetworkError`'s list, so no curl fallback runs.\n- With `maxRetries: 0`, `fetchJsonWithRetry` throws after the first attempt (`attempt > maxRetries`). The catch then retries over `http:` with `maxRetries: Math.max(1, 0) = 1`, so the http leg gets one retry with a 1000 ms backoff on error.\n- The protocol is kept for later pages.\n- The URL path is `/api/v1/video-channels/<encodeURIComponent(slug)>/videos?start=0&count=50&sort=-publishedAt`. The fake server must match the path and ignore the query.\n- Pagination stops when `nextStart >= page.total`, or when `data.length < 50` if `total` is absent. The fixture should send `total` equal to its video count.\n\n**Regression risk: none to production.** For the test there is one flake path. If the https attempt ever fails with ECONNREFUSED or ETIMEDOUT, `fetchJsonWithRetry` calls `fetchViaCurl` (http.ts:73-78), then throws `NoNetworkError`. `processChannel` then records an error, and no rows are written. Binding to 127.0.0.1 and keeping the server alive for the whole run avoids this.\n</impact>\n<impact path=\"engine/crawler/dist/videos-worker.js\" element=\"compiled crawlVideos channelMeta build (lines 40-47) and processInstance lookup (line 126)\">\n**What changes.** It is regenerated by `npm run build` (`node node_modules/typescript/bin/tsc -p tsconfig.json`) and committed together with the source. The dist is tracked: the root `.gitignore` ignores only `node_modules`, `*.db` and `.un/`.\n\n**What depends on it.**\n- Production runs the dist, not the source. The updater runs `crawler_dist / \"videos-cli.js\"` (updater-worker.py:805, 954), and `npm run crawl:videos` and `scripts/run-dataset-build.sh` go through `dist/videos-cli.js`. So without the rebuild, the fix never reaches staging or prod crawls.\n- The new crawl test imports this file.\n\n**Regression risk: medium, for the build process.**\n- `tsc` recompiles all of `src/` into `dist/`. The plan says \"only that dist file should differ\", and that holds only if the other committed dist files are already in step with their sources. I compared only the `videos-worker` lines at issue, which currently match the source.\n- `tsconfig` emits no source maps or declarations, so no extra files appear.\n- The staleness rule compares the git commit times of `src/videos-worker.ts` and this file. If both are committed together, the times are equal and the dist is not stale.\n</impact>\n<impact path=\"engine/crawler/src/db.ts\" element=\"VideoStore: listInstances (1241), listChannelsWithVideos (1265-1278), prepareVideoProgress/pruneVideoProgress (1328-1394), listVideoWorkItems (1399-1424), upsertStmt (1138-1196), constructor/applyBaseSchema (1131-1137, reads ../schema.sql at line 24)\">\n**What changes.** Nothing.\n\n**What depends on it.** The key-normalisation reasoning and the crawl test fixture.\n- **Instance match.** `listInstances` returns `instances.host` as stored. `listChannelsWithVideos` matches `instance_domain IN (hosts)` exactly, so the fixture's `instances.host` must equal `channels.instance_domain` byte for byte (`127.0.0.1:P1`).\n- **Required channel fields.** Each channel needs `videos_count >= 1` and a non-NULL `channel_name` (the slug).\n- **Constructor side effects.** The constructor sets `journal_mode = WAL`, so `-wal` and `-shm` files appear beside the temp DB. It also runs `applyBaseSchema` and migrations, so a DB created from `schema.sql` is already compatible.\n- **Module-level read.** `db.js` reads `../schema.sql` relative to itself at import (line 24), which resolves to `engine/crawler/schema.sql`.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"engine/crawler/src/videos-cli.ts\" element=\"crawlVideos option mapping (lines 87-107)\">\n**What changes.** Nothing.\n\n**What depends on it.** It is the reference for the full `VideoCrawlOptions` object the new test must build when it imports `crawlVideos` directly. The object has 18 keys:\n- `dbPath`\n- `excludeHostsFile: null`\n- `existingDbPath: null`\n- `concurrency`\n- `timeoutMs`\n- `maxRetries`\n- `newOnly: false`\n- `stopAfterFullPages: 0`\n- `sort: \"-publishedAt\"`\n- `maxInstances: 0`\n- `maxChannels: 0`\n- `maxVideosPages: 0`\n- `tagsOnly: false`\n- `updateTags: false`\n- `commentsOnly: false`\n- `hostDelayMs: 0`\n- `resume: false`\n- `errorsOnly: false`\n\nThe alternative is to run `dist/videos-cli.js --db ... --max-retries 0 --timeout N --concurrency 1`, which needs `commander` from `node_modules`.\n\n**Regression risk: none.** A missing option key is `undefined` in JS, so `sort: undefined` would still fall back to `-publishedAt` inside `buildChannelVideosUrl`.\n</impact>\n<impact path=\"engine/crawler/src/http.ts\" element=\"fetchJsonWithRetry() (55-133), isNoNetworkError() (37-53), fetchViaCurl() (138-161)\">\n**What changes.** Nothing.\n\n**What depends on it.** The crawl test's single https failure and its fall back to http. See the fetchPage entry.\n- `setDefaultResultOrder(\"ipv4first\")` runs at import. It is harmless for 127.0.0.1.\n- Node's fetch does not use `HTTP(S)_PROXY` by default, so a proxy environment should not reroute loopback requests.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"engine/crawler/src/host-filters.ts\" element=\"toBoundedString (48-56), toHttpUrlOrNull (68-78), normalizeHostToken (83-100)\">\n**What changes.** Nothing.\n\n**What depends on it.**\n- The name and URL sanitising in `toVideoRow`.\n- The plan's claim that hosts are lowercased when they enter the crawl. `normalizeHostToken` lowercases, and branch 4 keeps `:port`. That is why a `/` separator cannot collide with a stored host.\n\n**Regression risk: none.** `test_host_normalisation.py` pins this file's dist copy, and nothing here changes.\n</impact>\n<impact path=\"engine/crawler/schema.sql\" element=\"instances / channels / videos / video_crawl_progress tables\">\n**What changes.** Nothing.\n\n**What depends on it.**\n- The crawl.db-shape fixtures in the new test are created from it.\n- `sync-whitelist.py` parses its `instances`, `channels` and `videos` blocks at import (sync-whitelist.py:36, 92-96), and the repair job loads that module. So the repair job now depends on this file existing, even when run against `whitelist.db`.\n- `channels` has `PRIMARY KEY (channel_id, instance_domain)` (line 26), which makes the repair's correlated subquery an index lookup.\n- `videos.channel_id` is nullable (line 34). Rows with a NULL `channel_id` never match the repair.\n\n**Regression risk: low.** If the file moves, the repair job fails at load.\n</impact>\n<impact path=\"engine/server/db/jobs/repair-video-channel-names.py\" element=\"new job (whole module)\">\n**What changes.** A new file.\n\n**Layout, following its neighbours:**\n- Shebang, then a docstring.\n- The `script_dir` / `sys.path` preamble. `sync-whitelist.py:16-22` inserts both `engine/server` and `engine/server/api`. `recompute-popularity.py:10-11` appends `engine/server` and adds `api` lazily.\n- argparse with `CompactHelpFormatter` (`engine/server/scripts/cli_format.py`, which exists).\n- `logging.basicConfig(level=logging.INFO, ...)`. Note the neighbours' formats differ: `\"%(levelname)s: %(message)s\"` in sync-whitelist and `\"%(levelname)s %(message)s\"` in recompute-popularity.\n- A guarded `main()`.\n- `--db` is required, with `metavar=\"PATH\"`.\n\n**The repair.** One `UPDATE videos SET channel_name = (SELECT c.display_name FROM channels c WHERE c.channel_id = videos.channel_id AND c.instance_domain = videos.instance_domain) WHERE EXISTS (SELECT 1 FROM channels c WHERE <same join> AND c.display_name IS NOT NULL AND c.display_name <> '' AND c.display_name IS NOT videos.channel_name)`. The changed count is `cursor.rowcount`.\n\n**The FTS branch.**\n- It is taken when `sqlite_master` has a table named `videos_fts`, the same probe as `search.fts_available`.\n- It calls `drop_videos_fts_triggers`, then the UPDATE, `create_videos_fts_triggers`, `rebuild_videos_fts` and the count check.\n- The check raises `RuntimeError` with sync-whitelist's wording (lines 518-521).\n\n**Correction to the plan.** The plan says neighbours \"such as `recompute-popularity.py` default to the crawl DB path\". They do not. `server_config.DEFAULT_DB_PATH` is `\"engine/server/db/whitelist.db\"` (server_config.py:363), and recompute-popularity defaults to that path. So does sync-whitelist's `DEFAULT_SOURCE_DB_PATH`. A default here would silently hit the shared `whitelist.db`, which is an even stronger reason for `--db` to be required.\n\n**The loader is new in production code.** No file under `engine/` uses `importlib` today (grep: no matches). The `spec_from_file_location` precedent is in tests only (`test_host_normalisation.py:78-82`, `test_similar.py:72, 298`). This job is the first production module to load a sibling hyphenated job, which is acceptable but worth knowing.\n\n**Load-time dependencies of sync-whitelist.py.**\n- `scripts.cli_format`\n- `server_config`, whose only import is `os`\n- `data.moderation`, stdlib only\n- the parse of `engine/crawler/schema.sql`\n\nAll are stdlib-only, so the job stays stdlib-only.\n\n**Transactions.** `executescript` in the helpers COMMITs any pending implicit transaction.\n- **Order.** Triggers dropped (commit), then the UPDATE, which opens an implicit transaction. `create_videos_fts_triggers` commits the UPDATE and the new triggers. `rebuild_videos_fts` runs inside a new implicit transaction that the job must `commit()` explicitly, or it is rolled back on close.\n- **crawl.db path.** Also needs an explicit `commit()`.\n- **When `rowcount` must be read.** Before any `executescript`.\n\n**What depends on it.** The operator runbook and the new tests.\n\n**Regression risk: medium, operationally.** It rewrites shared databases. See the entries for `sync-whitelist.py`, the prod `whitelist.db` writers and `search.py`.\n</impact>\n<impact path=\"engine/server/db/jobs/sync-whitelist.py\" element=\"FTS helpers create_videos_fts_triggers (294-296), drop_videos_fts_triggers (299-306), rebuild_videos_fts (309-320), VIDEOS_FTS_TRIGGERS_SQL (270-285), ensure_content_schema (323-417), and the count check in rebuild_content_tables (511-521)\">\n**What changes.** Nothing. The repair job and the new test reuse these helpers.\n\n**What depends on it.**\n- The new job and the whitelist-shape test fixture. `ensure_content_schema` creates `channels`, `videos`, `video_embeddings`, `videos_fts` (fts5, `content='videos'`) and the triggers.\n- Note the fixture shape. The whitelist `channels` table has no NOT NULL besides the keys. The whitelist `videos` table has `popularity REAL NOT NULL DEFAULT 0` and `last_checked_at INTEGER NOT NULL`, so the fixture inserts must supply `last_checked_at`.\n- `rebuild_videos_fts` issues the `'rebuild'` command and returns `COUNT(*)` from `videos_fts`. On an external-content table that count reflects the content table, so the equality check is a weak guard. It matches sync-whitelist's own check, as required.\n\n**Regression risk: low.**\n- The helpers use `executescript`, whose commit behaviour is described in the job's entry.\n- If a later edit makes any helper non-idempotent, or makes `ensure_content_schema` do more, the repair job and test inherit that change silently. This is a coupling the build accepts in exchange for reuse.\n</impact>\n<impact path=\"engine/server/db/jobs/sync-whitelist.py\" element=\"module top level: sys.path mutation (16-22), imports (24-26), DEFAULT_SOURCE_DB_PATH (31), SCHEMA_SQL_PATH and *_COLUMNS parsed at import (36, 92-96), __main__ guard (676)\">\n**What changes.** Nothing.\n\n**What depends on it.**\n- Loading this module from the repair job runs this top-level code.\n- It leaves `engine/server` and `engine/server/api` on `sys.path`.\n- `main()` is guarded, so no sync runs.\n- `SCHEMA_SQL_PATH` is `script_dir.parents[3] / \"engine/crawler/schema.sql\"`, which resolves correctly from the jobs directory.\n\n**Regression risk: low.** It fails loudly at load if `schema.sql` or the server tree is missing.\n- **Module name.** The job should load it under an identifier-like name distinct from the test's `sync_whitelist_job`. Two module objects are harmless; the module defines no dataclass, so no `sys.modules` registration is needed.\n- **`conftest.py` interaction.** It imports `client/backend/server.py` as `server` first. The `engine/server/api/server.py` on `sys.path` does not shadow it, because the module is already cached. This is the same situation as the existing tests.\n</impact>\n<impact path=\"engine/server/db/jobs/recompute-popularity.py\" element=\"style reference: preamble, argparse, logging, --db default\">\n**What changes.** Nothing.\n\n**What depends on it.** It is the style reference for the new job.\n- The log line style is `\"popularity updated rows=%d\"` (line 121). The new job's key=value line should match, for example `channel names repaired rows=%d`. The CLI subprocess test can then parse the count.\n- Its `--db` default is `whitelist.db` (see the correction in the job entry).\n\n**Regression risk: none.**\n</impact>\n<impact path=\"engine/server/db/whitelist.db (prod/server copy) and its concurrent writers: engine/server/api/handlers/video.py (UPDATE videos ... channel_name, lines 305-343) and engine/server/db/jobs/merge-staging-db.py (INSERT OR IGNORE, lines 162-190)\">\n**What changes.** Nothing in the code. The repair will be run by the operator against live `whitelist.db` copies.\n\n**What depends on it.**\n- **The Engine's `/api/video` write-back.** It rewrites `videos.channel_name` and `channels.display_name` from the live instance, under `server.db_lock`, inside a try. It is the only other writer of `channel_name`.\n- **The updater merge.** It inserts `videos` INSERT_ONLY and fires `videos_fts_ai`.\n\n**Regression risk: medium, operational.**\n- **Missed triggers.** While the triggers are dropped, rows written by the Engine or the merge skip the per-row FTS maintenance. The following `rebuild` covers them, so the end state is correct.\n- **Lock contention.** The full rebuild holds the write lock for a long time on the ~890k-row prod DB. The Engine's write-back will hit `database is locked` (caught by its try), and a concurrent updater merge may fail. The runbook must say to run the repair outside an updater cycle, and ideally with the Engine idle or stopped.\n- **`channels` is INSERT_ONLY too** (merge_rules.json:9-12). Prod `channels.display_name` is therefore the first-inserted value, possibly refreshed by `/api/video`. It is still the correct host's name, so the repair source is sound.\n- **Migrated but not re-synced DBs.** `whitelist_migrations.migrate_videos_schema` (lines 260-265) drops `videos_fts`, and only the next `ensure_content_schema` recreates it. On such a copy the repair takes the no-FTS branch, and search is already disabled by `fts_available`.\n</impact>\n<impact path=\"engine/server/db/jobs/merge_rules.json\" element=\"videos / channels strategy INSERT_ONLY (lines 8-17)\">\n**What changes.** Nothing.\n\n**What depends on it.** It is why the repair must run on every `whitelist.db` copy: a merge never overwrites existing prod rows, so fixing staging or `crawl.db` does not propagate to prod. `test-orchestrator-smoke.py:793-809` asserts this invariant.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"engine/server/data/search.py\" element=\"fts_available() (121-131), lexical_candidates() (134-164)\">\n**What changes.** Nothing.\n\n**What depends on it.** It reads `videos_fts MATCH ?` joined to `videos` by rowid. After the repair, lexical search on `channel_name` returns the correct channel's videos. This is the user-visible outcome that the new FTS test checks directly with MATCH, bypassing this module.\n\n**Regression risk: low.** During the repair window (triggers dropped, rebuild in progress), searches may see a stale index or wait on the lock.\n</impact>\n<impact path=\"engine/server/db/jobs/build-video-embeddings.py\" element=\"embedding text builder (lines 40-54, query 189-205)\">\n**What changes.** Nothing. Changing it is out of scope.\n\n**What depends on it.** It appends `channel: <channel_name>`. Existing vectors keep the foreign names until the operator runs `--force`, then `build-ann-index.py` and `precompute-similar-ann.py`.\n\n**Regression risk: none from the code.** It is listed because the runbook's follow-up step depends on it.\n</impact>\n<impact path=\"engine/server/db/jobs/updater-worker.py\" element=\"crawler invocation of dist/videos-cli.js (lines 805, 954) and staging merge (1055)\">\n**What changes.** Nothing.\n\n**What depends on it.** Once the rebuilt dist is merged, updater crawls write correct names into staging. The merge then inserts only new rows into prod, which is why existing prod rows still need the repair.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"scripts/run-dataset-build.sh\" element=\"full pipeline: crawl \u2192 sync-whitelist (228) \u2192 embeddings (236) \u2192 ANN (244) \u2192 precompute (253)\">\n**What changes.** Nothing. The repair is a one-off migration and is not added to the pipeline.\n\n**What depends on it.** A full rebuild after the fix, re-crawl plus sync, produces correct names without the repair job.\n\n**Regression risk: none.** I list it because an operator might ask whether the job belongs here. It does not: a fresh crawl with the fixed writer gets names right, and the ON CONFLICT upsert overwrites `channel_name`.\n</impact>\n<impact path=\"tests/active/test_channel_names.py\" element=\"new test module: crawl test, parametrised repair tests, FTS test, CLI subprocess test\">\n**What changes.** A new file.\n- **Header.** It imports `ROOT` from `conftest` and adds `engine/server` to `sys.path`, as `test_host_normalisation.py:19-23` does.\n- **Loader.** It loads `repair-video-channel-names.py` (and `sync-whitelist.py` for `ensure_content_schema`) with an inline `_load_job`, a copy of `test_host_normalisation.py:78-82`.\n\n**Crawl test.**\n- **Gates.** It copies the node / dist-missing / git / staleness gates of `test_host_normalisation.py:48-70`: `_git`, `_dist_is_stale`, `BUILD_HINT = \"cd engine/crawler && npm install && npm run build\"`. SRC and DIST point at `videos-worker.ts` / `.js`.\n- **What else the gates must cover.** Unlike `host-filters.js`, `dist/videos-worker.js` imports `better-sqlite3` (and `./db.js`, which reads `schema.sql`). The node process therefore also needs `engine/crawler/node_modules`. The test should fail with the build hint when node cannot import it, for example by asserting returncode 0 with stderr in the message.\n- **Node script.** `node --input-type=module -e` with `await import(<dist uri>)`, then `crawlVideos({...})`, with `cwd=engine/crawler` so bare-specifier resolution finds `node_modules`. Resolution goes from the dist file's location, so cwd matters less, but setting it is safe.\n- **Servers.** Two `ThreadingHTTPServer`s on `(\"127.0.0.1\", 0)`, each in a daemon thread and shut down in `finally`.\n- **Assertions.** Per host, `channel_name` equals its own `display_name`. `channel_url` equals its own channel's URL, which requires the payload to have no `channel.url`.\n\n**Repair tests.**\n- **Parametrisation.** Over a crawl-shape fixture (`schema.sql` via `executescript`) and a whitelist-shape fixture (`ensure_content_schema`).\n- **Seeded rows.** Mismatched, already-correct, empty and NULL `display_name`. The plan should also seed a video with no `channels` row, which the requirements name.\n- **Assertions.** The exact count, each row's value, and 0 on the second run.\n\n**CLI test.** One subprocess run with `sys.executable`, parsing the `rows=N` log line.\n\n**FTS test.** MATCH on the correct name versus the foreign name, and `COUNT(videos_fts) == COUNT(videos)`.\n- **MATCH syntax.** It must use a column filter (`channel_name : \"...\"`, quoted as a phrase). A bare MATCH on the old name could also hit the title or description if the fixture text contains it. Fixture names should be distinctive single-token strings.\n- **Why the foreign name disappears.** The foreign-name query no longer returning the videos depends on the rebuild re-tokenising. In an external-content table, stale tokens would otherwise remain.\n\n**What depends on it.** `validate_tests.py` discovers `tests/active/test_*.py` automatically. It has no mapping in the local `.un/skills/devsecops/config.json`, which is gitignored and outside this read, so until harvest it runs on every invocation.\n\n**Regression risk: medium, for suite stability.**\n- The node, `node_modules` and dist gates can go red on machines without the crawler installed. `test_host_normalisation.py` needs node but not `node_modules`, so this is a new, stricter requirement.\n- I could not verify that `engine/crawler/node_modules` exists in this worktree. The read was refused as outside the project, which suggests a symlink to another checkout.\n- The crawl needs an https failure, then an http success, per channel. With the default 5000 ms timeout a TLS failure is immediate, so the runtime stays small.\n- Every DB must be under `tmp_path`. It must never request the `engine` or `dataset` fixtures, which open the shared `whitelist.db`.\n</impact>\n<impact path=\"tests/active/test_host_normalisation.py\" element=\"gate helpers _git/_dist_is_stale (48-61), test_crawler_dist_returns_pinned_values (64-75), _load_job (78-82)\">\n**What changes.** Nothing. The new test copies these patterns inline, as the plan chooses.\n\n**What depends on it.** It must stay green. It checks `host-filters.ts` / `.js`, and the rebuild regenerates `dist/host-filters.js` too.\n- If the regenerated `host-filters.js` differs from the committed one, it gets a new commit time. That is harmless, since the dist is then newer than the source.\n- If the rebuild is committed with `host-filters.ts` unchanged, nothing changes for this test.\n\n**Regression risk: low.** The staleness rule is by commit time, so rebuilding and committing only `videos-worker.js` cannot make it stale.\n</impact>\n<impact path=\"tests/active/conftest.py\" element=\"module-level Client backend import (37-43), ROOT (31), WHITELIST_DB (34)\">\n**What changes.** Nothing.\n\n**What depends on it.** The new test imports `ROOT`. `WHITELIST_DB` is the shared dataset and must not be used.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"tests/last_test_validation.json\" element=\"tracked suite record (also tests/last_test_output.txt)\">\n**What changes.** Both files are rewritten by the post-build `validate_tests.py` run.\n\n**What depends on it.** The comparison against the green baseline.\n\n**Regression risk: none functionally.** They conflict on merge. Take main's copy and re-run the comparison.\n</impact>\n<impact path=\"client/frontend/src/components/video-card.ts\" element=\"channel_name fallback (line ~142)\">\n**What changes.** Nothing. It is explicitly out of scope.\n\n**What depends on it.** It reads `videos.channel_name` only when `channel_url` is empty, which applies to 0 rows per triage.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"client/frontend/src/pages/video-page/index.ts\" element=\"local `channelMeta` / fetchChannelMetadata (599-630)\">\n**What changes.** Nothing.\n\n**Why it is listed.** It is an unrelated same-named identifier that a `channelMeta` grep hits. It is recorded only so no one edits it by mistake.\n\n**Regression risk: none.**\n</impact>\n</impacts>\n\n</impacts>\n\n<docs_checklist>\n<doc path=\"DATA_BUILD.md\">\nAdd a new section after \"## 2) Filter to JoinPeerTube whitelist\" (which ends at line 158, before \"## 3) Build embeddings\") covering the one-off repair of `videos.channel_name`:\n- A one-line reason for the repair.\n- It is a migration of shared databases: run it on main after merge only, never from a worktree.\n- Run it outside an updater cycle, with the Engine idle, because the FTS rebuild holds the write lock.\n- The order:\n  1. Merge.\n  2. `python3 engine/server/db/jobs/repair-video-channel-names.py --db engine/crawler/data/crawl.db`.\n  3. The same command with `--db` on every `whitelist.db`, including prod, because merges are `INSERT_ONLY`.\n  4. The operator follow-up, using the flags this file already documents: `build-video-embeddings.py --db-path engine/server/db/whitelist.db --force`, then `build-ann-index.py` with `--db-path`, `--index-path`, `--meta-path`, and `--gpu` or `--cpu`, then `precompute-similar-ann.py` with `--db`, `--index`, `--out`, `--reset`, and `--gpu` or `--cpu`.\n\nTwo cautions:\n- The plan-17 reference in the requirements names `docs/project/plans/17-stable-ann-ids.md`, but that file does not exist in this tree. `docs/project/plans/` holds only `01-34-*`, and the related issue is `docs/project/issues/08-stable-ann-ids.md`. The runbook should cite something that exists, or name \"plan 17\" without a path.\n- The file already points at `engine/server/db/jobs/UPDATER_WORKER.md` (line 30), but the doc lives in `engine/server/db/jobs/docs/`. This is a pre-existing broken reference, worth fixing only if that line is touched.\n</doc><doc path=\"docs/project/issues/34-video-channel-name-wrong-instance.md\">\nAt harvest:\n- Tick the acceptance criteria.\n- Set `Status: bug, complete`.\n- Move the file to `docs/project/issues/archive/`, per `docs/project/triage-labels.md`.\n- Record that the repair and the re-embed are still owed by the operator on main.\n- Record the correction that the crawl slug was already host-correct: only `displayName` and the `channelUrl` fallback were wrong.\n</doc><doc path=\"engine/server/db/jobs/docs/UPDATER_WORKER.md\">\nOptional. A one-line note that `videos` and `channels` merge `INSERT_ONLY`, so data corrections to existing prod rows, such as `repair-video-channel-names.py`, must be run against the prod `whitelist.db` directly, and not while an updater cycle holds the DB. No behaviour documented there changes, so leave the file untouched if the DATA_BUILD section says this already.\n</doc>\n</docs_checklist>\n\n<highest_risk>\nengine/server/db/jobs/repair-video-channel-names.py: it rewrites shared, live databases, including prod `whitelist.db`, while the Engine's `/api/video` write-back and the updater merge also write to them. Because the reused helpers call `executescript`, the UPDATE is committed before the rebuild, and the rebuild needs its own explicit `commit()` or it is lost on close. It is also the first production code under `engine/` to load a sibling job through importlib, so it now depends at load on `engine/crawler/schema.sql` and the server tree.\ntests/active/test_channel_names.py (the crawl test): it must fail rather than skip, yet it depends on more than the existing host test does: node, a fresh `dist/videos-worker.js`, AND `engine/crawler/node_modules/better-sqlite3`. I could not confirm `node_modules` exists: the read was refused as outside the project, which suggests a symlink. The test also relies on the https attempt failing with a TLS error rather than a no-network code (which would divert to curl), and it proves the `channel_url` part only if the fake payload has no `channel.url`.\nengine/crawler/dist/videos-worker.js: production runs this file, not the source (the updater runs `dist/videos-cli.js`), so the fix does nothing until it is rebuilt and committed. `tsc` recompiles all of `src/`, so any other dist file already out of step with its source will change too. That contradicts the plan's \"only that dist file should differ\" and needs checking in the diff.\n</highest_risk>",
    "step_4_reassess": "<summary>\nI opened the files behind every material inventory entry: `videos-worker.ts` (the map build at 163-172, the lookup at 285-291, `processChannel`, `crawlChannelVideos`, `fetchPage`/`buildChannelVideosUrl`, `toVideoRow`, `groupByInstance`), `db.ts` (`listChannelsWithVideos`, `prepareVideoProgress`), `http.ts`, `schema.sql`, `sync-whitelist.py` (preamble, schema parse, FTS helpers, `ensure_content_schema`, `rebuild_content_tables`, `main`), `recompute-popularity.py`, `server_config.py:363`, `merge_rules.json`, `handlers/video.py:302-343` and `test_host_normalisation.py`. Every entry I checked matches the file. The inventory's two corrections to the plan are right. The slug comes from `item.channelName` first (line 433). The neighbours' `--db` default is `engine/server/db/whitelist.db`, not the crawl DB. Neither correction changes the design. The first actually makes the case for a required `--db` stronger. I found nothing the inventory is missing.\n<question id=\"1\">\nYes. The bug is only the key at line 165 and the lookup at line 289. `prepareVideoProgress` inserts `channel.instance_domain` verbatim (db.ts:1342), and `groupByInstance` groups on that value (videos-worker.ts:710). So a composite key built as `lower(instance_domain) + \"/\" + channel_id` on both sides always resolves to the right host's entry. `processChannel` (450-451) and `toVideoRow` (660-664) already read everything from that single `meta`. For the repair, `channels` has `PRIMARY KEY (channel_id, instance_domain)` in both shapes (schema.sql:26, sync-whitelist.py:348), so the correlated-subquery UPDATE is well defined and indexed. `rebuild_videos_fts` issues `'rebuild'` and returns the count (309-320). The helpers exist with the names and behaviour the plan assumes.\n</question>\n<question id=\"2\">\n- **Every re-crawl self-corrects.** Once the rebuilt dist ships, every re-crawl of `crawl.db` fixes `channel_name`/`channel_url` on its own through the ON CONFLICT upsert, and updater crawls write correct names into staging.\n- **Existing rows need the one-off job.** Existing rows in each `whitelist.db` are fixed only by the job, because `merge_rules.json` makes `videos` and `channels` INSERT_ONLY.\n- **Operational load on the FTS path.** The job drops the triggers and runs a full `rebuild` of `videos_fts` on every run. That write holds the lock for a long time on prod. During it, `handlers/video.py`'s write-back (under `server.db_lock`, inside a try) can hit `database is locked`, and a concurrent updater merge can fail.\n- **No longer atomic.** `executescript` commits: the UPDATE is committed by `create_videos_fts_triggers` before the rebuild runs.\n- **Code shape.** The job becomes the first production module to load a sibling job through `importlib`, so its load now depends on `engine/crawler/schema.sql`, which `sync-whitelist.py` parses at import (lines 36, 92-96).\n- **Test suite.** It gains a stricter environment requirement: node + `node_modules` (better-sqlite3) + a fresh dist.\n</question>\n<question id=\"3\">\n- **Commit the rebuilt dist.** `dist/videos-worker.js` must be rebuilt and committed with the source. Production runs the dist through `updater-worker.py` and `run-dataset-build.sh`, and without it the fix never runs.\n- **Run the repair on every copy.** The job must run against `crawl.db` and every `whitelist.db` copy, prod included, outside an updater cycle and ideally with the Engine idle.\n- **Commit explicitly after the rebuild.** On the FTS path the job must call `conn.commit()` explicitly after `rebuild_videos_fts`. Under the default legacy isolation, the `INSERT ... 'rebuild'` opens an implicit transaction, which would otherwise be rolled back on close.\n- **Read the count early.** `rowcount` must be read before any `executescript`.\n- **Re-embed.** The operator must run the re-embed, ANN build and precompute to fix semantic similarity.\n- **Other tests unaffected.** `test_host_normalisation.py` stays green: staleness is by commit time, and rebuilding only makes dist newer.\n</question>\n<question id=\"4\">\n- **Crawler.** Only which channel entry a video row's display name and fallback URL come from changes, now the same host's instead of whichever same-id row was listed last. The name precedence (crawl list first, payload second) and the URL precedence (payload `channel.url` first) are unchanged. So is the slug, which already came from the per-host progress row.\n- **Stored data.** After the repair, existing `videos.channel_name` values change to the owning channel's `display_name`. Rows with an empty or NULL `display_name` or no channel row keep their current value.\n- **Search.** Lexical search on `channel_name` returns the correct channel's videos.\n- **Unchanged.** Nothing else in the crawler, the Engine API, the frontend or the pipeline changes.\n</question>\n</summary>\n\n<new_impacts>\nnone\n</new_impacts>\n\n<unconfirmed>\n- **engine/crawler/src/videos-worker.ts, fetchPage() entry: the TLS failure.** The entry says the https attempt against a plain-HTTP server fails at once with EPROTO / ERR_SSL_WRONG_VERSION_NUMBER. That is runtime behaviour the tree cannot confirm. What the code shows is this. `isNoNetworkError` (http.ts:37-53) lists only ENETUNREACH, EHOSTUNREACH, ENOTFOUND, EAI_AGAIN, ECONNREFUSED, ETIMEDOUT and ETIMEOUT, so a TLS error goes neither to curl nor to `NoNetworkError`. An abort by the per-attempt `AbortController` (http.ts:61-62) also goes the http way. So the fallback happens whether the handshake fails fast or hangs until `timeoutMs`; only the runtime differs. It is fast if `BaseHTTPRequestHandler` finds a newline byte in the ClientHello and answers 400. The supported_groups extension id 0x000a makes that likely but not certain.\n- **tests/active/test_channel_names.py entry: `node_modules`.** Whether `engine/crawler/node_modules` exists in this worktree is still unconfirmed, as the entry itself says.\n- **Every other entry** I checked held up against its file.\n</unconfirmed>\n\n<new_conflicts>\nnone\n</new_conflicts>\n\n<recommendations>\n1. **Seed a video with no `channels` row in both repair fixtures.** The inventory already flags this. The plan's list of seeded rows leaves it out, but the requirements name the case. Cost: one extra insert per fixture and one assertion.\n2. **Pass an explicit `timeoutMs` of about 2000-3000 ms in the crawl test,** not something very short. The same `timeoutMs` bounds the http leg, which is the one that must succeed. If the https handshake hangs rather than fails, each channel costs at most one timeout. Cost: up to a few seconds of test time in the worst case, and nothing in production.\n3. **Write the explicit `conn.commit()` after `rebuild_videos_fts`, and read `rowcount` before the first `executescript`, into the implementation phase as named steps.** Both are easy to miss, and missing either one silently loses the rebuild or misreports the count. Cost: none beyond two lines.\n4. **Use sync-whitelist's `\"%(levelname)s: %(message)s\"` log format** and a `rows=%d` suffix, e.g. `channel names repaired rows=%d`, so the CLI test can parse the count reliably. Cost: none. It is a choice between two existing neighbour styles.\n5. **In the runbook step, say to run the job outside an updater cycle and with the Engine idle or stopped for the prod `whitelist.db`.** Cost: a short maintenance window on prod for the length of one full FTS rebuild.\n</recommendations>",
    "step_5_draft_implementation": "<draft>\n## Draft implementation: issue 34, `videos.channel_name` taken from another instance's channel\n\nThe draft was checked against the plan and the requirements in one pass and they converged, so no operator decision was needed. Before drafting I read `videos-worker.ts` (lines 150-300 and 420-700), `dist/videos-worker.js` (lines 1-130), `db.ts` (lines 1236-1425), `http.ts` (lines 30-165), `schema.sql`, `sync-whitelist.py` (lines 1-60, 265-424 and 495-530), `recompute-popularity.py`, `test_host_normalisation.py` and `DATA_BUILD.md` (lines 125-250).\n\n### What changes\n\n| Path | Change | Requirement |\n|---|---|---|\n| `engine/crawler/src/videos-worker.ts` | Two lines change: the map key where it is built, and the key at the lookup | R1 |\n| `engine/crawler/dist/videos-worker.js` | Regenerated with `npm run build` and committed with the source | R1 |\n| `engine/server/db/jobs/repair-video-channel-names.py` | New job | R2, R3 |\n| `tests/active/test_channel_names.py` | New test module | R4 |\n| `DATA_BUILD.md` | New section `## 2b)` placed between steps 2 and 3 | R5 |\n\n### Two corrections to the plan (they change nothing in scope)\n\n- **The slug was already correct.** `processChannel` reads the slug as `item.channelName ?? meta?.channelSlug` (videos-worker.ts:433), and `item.channelName` comes from the progress row for that host. The fix therefore changes only `displayName`, and `channelUrl`, which is the fallback after the payload's own `channel.url`.\n- **The neighbouring jobs default to `whitelist.db`, not `crawl.db`.** `server_config.DEFAULT_DB_PATH` is `engine/server/db/whitelist.db`. That makes a required `--db` even more important.\n\n---\n\n### 1. Writer fix: `engine/crawler/src/videos-worker.ts`\n\nAt the map build (lines 163-172), only the key expression changes:\n\n```ts\n  const channelMeta = new Map<string, ChannelMeta>(\n    channels.map((channel) => [\n      `${channel.instance_domain.toLowerCase()}/${channel.channel_id}`,\n      {\n        channelSlug: channel.channel_name,\n        displayName: channel.display_name,\n        channelUrl: channel.channel_url\n      }\n    ])\n  );\n```\n\nAt the lookup in `processInstance` (line 289), only the key changes:\n\n```ts\n    const meta = channelMeta.get(`${normalizedHost}/${item.channelId}`);\n```\n\n**Why the two keys always match.** The key is `lower(instance_domain) + \"/\" + channel_id`, and both sides build it from the same column:\n\n- The map side builds it from `channels.instance_domain`.\n- The lookup side uses `normalizedHost = host.toLowerCase()`. Here `host` comes from `groupByInstance(item.instanceDomain)`. That value is `video_crawl_progress.instance_domain`, which `prepareVideoProgress` copied verbatim from `channels.instance_domain`.\n\nA normalised host cannot contain `/` (a `:port` is allowed), so the separator cannot make two different pairs produce the same key.\n\n**What stays the same:**\n- The value type `ChannelMeta` and the `Map<string, ChannelMeta>` signatures in `workerLoop` (line 260) and `processInstance` (line 280).\n- `processChannel` and `toVideoRow`.\n- The name precedence in `toVideoRow` (lines 660-662): the crawl list's `displayName` first, then the payload's `channel.displayName` / `display_name`.\n\n**Dist.** Run `cd engine/crawler && npm run build`. The expected diff in `dist/videos-worker.js` is line 41 (`channel.channel_id,` becomes the same template literal) and line 126 (the `.get(...)` key). Any other file that `tsc` rewrites under `dist/` was already out of step with its source. That drift is reported at commit time, not folded silently into this change.\n\n---\n\n### 2 and 3. Repair job: `engine/server/db/jobs/repair-video-channel-names.py`\n\n```python\n#!/usr/bin/env python3\n\"\"\"Repair videos.channel_name from the channel row on the video's own instance.\n\nThe video crawler once looked up channel metadata by channel_id alone, so where PeerTube's per-instance channel ids repeat across instances a video took the display name of another instance's channel. This one-off migration sets each video's channel_name to the display_name of the channels row with the same (channel_id, instance_domain), and rebuilds videos_fts when the database has one.\n\"\"\"\nimport argparse\nimport importlib.util\nimport logging\nimport sqlite3\nimport sys\nfrom pathlib import Path\n\nscript_dir = Path(__file__).resolve().parent\nserver_dir = script_dir.parents[1]\nif str(server_dir) not in sys.path:\n    sys.path.insert(0, str(server_dir))\n\nfrom scripts.cli_format import CompactHelpFormatter\n\nREPAIR_SQL = \"\"\"\nUPDATE videos\nSET channel_name = (\n  SELECT c.display_name FROM channels c\n  WHERE c.channel_id = videos.channel_id AND c.instance_domain = videos.instance_domain\n)\nWHERE EXISTS (\n  SELECT 1 FROM channels c\n  WHERE c.channel_id = videos.channel_id\n    AND c.instance_domain = videos.instance_domain\n    AND c.display_name IS NOT NULL\n    AND c.display_name <> ''\n    AND c.display_name IS NOT videos.channel_name\n);\n\"\"\"\n\n\ndef _load_sync_whitelist():\n    \"\"\"Load sync-whitelist.py, whose hyphenated name rules out a normal import, for its videos_fts helpers.\"\"\"\n    spec = importlib.util.spec_from_file_location(\"sync_whitelist_for_repair\", script_dir / \"sync-whitelist.py\")\n    module = importlib.util.module_from_spec(spec)\n    spec.loader.exec_module(module)\n    return module\n\n\ndef has_videos_fts(conn: sqlite3.Connection) -> bool:\n    \"\"\"Whether the database carries the videos_fts index (the whitelist.db shape; crawl.db has none).\"\"\"\n    row = conn.execute(\"SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'videos_fts'\").fetchone()\n    return row is not None\n\n\ndef repair_channel_names(conn: sqlite3.Connection) -> int:\n    \"\"\"Set each video's channel_name to its own channel's display_name and return the number of rows changed.\n\n    Rows that already match, and rows whose channel has a NULL or empty display_name or no channels row, are left alone, so a second run returns 0. channels is only read. When videos_fts exists, the update runs between sync-whitelist.py's trigger drop and recreate, and the index is rebuilt and its count checked on every run, even when nothing changed. The helpers use executescript, which commits, so the update is already committed before the rebuild: a failed rebuild is recovered by running the job again, not by rollback.\n\n    :param conn: Connection to a crawl.db or whitelist.db.\n    :returns: Number of videos rows whose channel_name changed.\n    \"\"\"\n    if not has_videos_fts(conn):\n        changed = conn.execute(REPAIR_SQL).rowcount\n        conn.commit()\n        return changed\n    sync = _load_sync_whitelist()\n    sync.drop_videos_fts_triggers(conn)\n    changed = conn.execute(REPAIR_SQL).rowcount\n    sync.create_videos_fts_triggers(conn)\n    fts_count = sync.rebuild_videos_fts(conn)\n    videos_count = conn.execute(\"SELECT COUNT(*) FROM videos\").fetchone()[0]\n    if fts_count != videos_count:\n        raise RuntimeError(\n            f\"videos_fts holds {fts_count} rows but videos holds {videos_count}; \"\n            \"the full-text index did not rebuild cleanly.\"\n        )\n    conn.commit()\n    return changed\n\n\ndef main() -> None:\n    \"\"\"Handle main.\"\"\"\n    parser = argparse.ArgumentParser(\n        description=\"Repair videos.channel_name from the channel on each video's own instance.\",\n        formatter_class=CompactHelpFormatter,\n    )\n    parser.add_argument(\n        \"--db\",\n        required=True,\n        metavar=\"PATH\",\n        help=\"Path to the crawl.db or whitelist.db to repair (required; there is no default).\",\n    )\n    args = parser.parse_args()\n\n    logging.basicConfig(level=logging.INFO, format=\"%(levelname)s %(message)s\")\n\n    db_path = Path(args.db)\n    if not db_path.is_file():\n        parser.error(f\"database not found: {db_path}\")\n    conn = sqlite3.connect(str(db_path))\n    try:\n        changed = repair_channel_names(conn)\n    finally:\n        conn.close()\n    logging.info(\"channel names repaired rows=%d\", changed)\n\n\nif __name__ == \"__main__\":\n    main()\n```\n\n**What the job guarantees.**\n- **Changed count.** `rowcount` is read immediately after the UPDATE. The UPDATE runs in Python's implicit transaction, and no `executescript` has run yet at that point.\n- **NULL names.** The WHERE uses `IS NOT`, so a row whose `channel_name` is NULL is corrected too.\n- **Rows that can never match:** a NULL `videos.channel_id`, a channel with no row in `channels`, or a channel whose `display_name` is NULL or `''`.\n- **Index lookup.** The correlated subqueries join on the `channels` primary key `(channel_id, instance_domain)`, so each lookup uses the index.\n- **Idempotence.** After one run, every row that could match has `channel_name == display_name`, so a second UPDATE matches 0 rows.\n\n**Design decisions.**\n- **Why `is_file()` is checked.** `sqlite3.connect` would silently create an empty file for a mistyped path and then fail with \"no such table\". Checking first also keeps stray DBs from being created in the tree.\n- **Why the loader is called lazily.** It is only called on the FTS path, so the `crawl.db` path does not load `sync-whitelist.py` at all, and so does not need its load-time parse of `schema.sql`. The whitelist path loads it once per call, which is cheap.\n- **Log format.** `\"%(levelname)s %(message)s\"` and `rows=%d` follow `recompute-popularity.py`, so the CLI test can parse the count.\n\n**Deliberate simplification: no transaction across the FTS path.** The settled helpers commit internally, so the job cannot be atomic. The ceiling is that a crash between the trigger recreate and the rebuild leaves correct names with a stale index. Recovery is a re-run: it reports `rows=0`, but it rebuilds and checks the count. If one transaction is ever required, the upgrade path is to run `VIDEOS_FTS_DROP_TRIGGERS_SQL` and `VIDEOS_FTS_TRIGGERS_SQL` through `conn.execute` statement by statement instead of `executescript`. That is a change to `sync-whitelist.py`, which is outside this build.\n\n---\n\n### 4. Tests: `tests/active/test_channel_names.py`\n\n**Module constants and imports:**\n\n```python\n\"\"\"Each video carries its own instance's channel name (issue 34).\n\n- The compiled `crawlVideos` in `engine/crawler/dist/videos-worker.js`, run under node against two loopback hosts sharing a channel_id, writes each host's videos with that host's channel display name and URL; a missing node, git, node_modules or dist, or a stale dist, fails the test rather than skipping it.\n- `repair-video-channel-names.py` corrects mismatched and NULL names on both the crawl.db and whitelist.db shapes, leaves correct rows and rows whose channel has an empty, NULL or absent display name untouched, reports the changed count, and changes 0 rows on a second run.\n- On the whitelist.db shape the repaired videos_fts finds a channel's videos by its own name, not by the other instance's same-id name, and holds as many rows as videos.\n- The CLI requires --db and logs the changed count.\n\"\"\"\nfrom __future__ import annotations\n\nimport importlib.util\nimport json\nimport os\nimport re\nimport shutil\nimport sqlite3\nimport subprocess\nimport sys\nimport threading\nfrom http.server import BaseHTTPRequestHandler, ThreadingHTTPServer\nfrom urllib.parse import unquote, urlsplit\n\nimport pytest\nfrom conftest import ROOT\n\nSERVER_DIR = ROOT / \"engine\" / \"server\"\nif str(SERVER_DIR) not in sys.path:\n    sys.path.insert(0, str(SERVER_DIR))\n\nCRAWLER_DIR = ROOT / \"engine\" / \"crawler\"\nSRC = CRAWLER_DIR / \"src\" / \"videos-worker.ts\"\nDIST = CRAWLER_DIR / \"dist\" / \"videos-worker.js\"\nCRAWL_SCHEMA = CRAWLER_DIR / \"schema.sql\"\nBUILD_HINT = \"cd engine/crawler && npm install && npm run build\"\nJOBS_DIR = SERVER_DIR / \"db\" / \"jobs\"\nREPAIR_JOB = JOBS_DIR / \"repair-video-channel-names.py\"\n```\n\n**Helpers copied inline.** `_git`, `_dist_is_stale` and `_load_job` are copied verbatim from `test_host_normalisation.py`. They read the module-level `SRC`, `DIST` and `JOBS_DIR`, so they check the videos-worker pair.\n\n**Module fixture:**\n\n```python\n@pytest.fixture(scope=\"module\")\ndef jobs():\n    return _load_job(\"sync_whitelist_channel_names\", \"sync-whitelist.py\"), _load_job(\"repair_video_channel_names\", \"repair-video-channel-names.py\")\n```\n\n#### Crawl test\n\n**Node script.** Run with `node --input-type=module -e`, with `cwd=CRAWLER_DIR`:\n\n```js\nconst { crawlVideos } = await import(process.env.VIDEOS_WORKER_URL);\nawait crawlVideos(JSON.parse(process.env.CRAWL_OPTIONS));\n```\n\n**Fake server:**\n\n```python\nclass _ChannelVideosHandler(BaseHTTPRequestHandler):\n    timeout = 1  # the crawler tries https first; a TLS ClientHello with no newline would otherwise hold readline until the crawler's own timeout\n\n    def do_GET(self):\n        path = urlsplit(self.path).path\n        prefix, suffix = \"/api/v1/video-channels/\", \"/videos\"\n        slug = unquote(path[len(prefix):-len(suffix)]) if path.startswith(prefix) and path.endswith(suffix) else None\n        videos = self.server.videos_by_slug.get(slug)\n        if videos is None:\n            self.send_error(404)\n            return\n        body = json.dumps({\"total\": len(videos), \"data\": videos}).encode(\"utf-8\")\n        self.send_response(200)\n        self.send_header(\"Content-Type\", \"application/json\")\n        self.send_header(\"Content-Length\", str(len(body)))\n        self.end_headers()\n        self.wfile.write(body)\n\n    def log_message(self, format, *args):\n        pass\n```\n\n**Crawl options.** The 18 keys from `videos-cli.ts:87-107`:\n\n```python\ndef _crawl_options(db_path) -> dict:\n    return {\"dbPath\": str(db_path), \"excludeHostsFile\": None, \"existingDbPath\": None, \"concurrency\": 1, \"timeoutMs\": 3000, \"maxRetries\": 0, \"newOnly\": False, \"stopAfterFullPages\": 0, \"sort\": \"-publishedAt\", \"maxInstances\": 0, \"maxChannels\": 0, \"maxVideosPages\": 0, \"tagsOnly\": False, \"updateTags\": False, \"commentsOnly\": False, \"hostDelayMs\": 0, \"resume\": False, \"errorsOnly\": False}\n```\n\n**`test_crawl_writes_each_hosts_own_channel_name(tmp_path)` runs in this order:**\n1. **Gates, the same as `test_crawler_dist_returns_pinned_values`:** node is on PATH, `DIST.is_file()`, git is on PATH, and `not _dist_is_stale(git)`. Each gate's message carries `BUILD_HINT`. A missing `node_modules` (better-sqlite3) shows up as a nonzero node exit, and that assertion also carries `BUILD_HINT`.\n2. **Servers.** Two `ThreadingHTTPServer((\"127.0.0.1\", 0), _ChannelVideosHandler)`, each run with `serve_forever` in a daemon thread. `host_a = f\"127.0.0.1:{server_a.server_port}\"`, and `host_b` likewise.\n   - `server_a.videos_by_slug = {\"alpha_chan\": [{\"uuid\": \"a1\", \"id\": 1, \"name\": \"Alpha one\"}, {\"uuid\": \"a2\", \"id\": 2, \"name\": \"Alpha two\"}]}`\n   - `server_b.videos_by_slug = {\"beta_chan\": [{\"uuid\": \"b1\", \"id\": 1, \"name\": \"Beta one\"}]}`\n   - The payloads carry no `channel` key, so neither the payload name nor the payload URL can mask the lookup.\n   - Both servers are shut down and closed in `finally`.\n3. **DB.** `tmp_path / \"crawl.db\"` is created with `executescript(CRAWL_SCHEMA.read_text())`. It gets both hosts in `instances`, and these rows in `channels` (named columns):\n   - `(\"7\", \"alpha_chan\", \"Alphachan\", f\"http://{host_a}/c/alpha_chan\", host_a, 2)`\n   - `(\"7\", \"beta_chan\", \"Betachan\", f\"http://{host_b}/c/beta_chan\", host_b, 1)`\n4. **Run.** `subprocess.run([node, \"--input-type=module\", \"-e\", NODE_SCRIPT], cwd=CRAWLER_DIR, capture_output=True, text=True, encoding=\"utf-8\", timeout=120, env={**os.environ, \"VIDEOS_WORKER_URL\": DIST.as_uri(), \"CRAWL_OPTIONS\": json.dumps(_crawl_options(db))})`. The run must exit 0; on failure the message includes stderr and `BUILD_HINT`.\n5. **Assert** that `{(instance_domain, video_id): (channel_name, channel_url)}` read from `videos` equals exactly:\n   - `(host_a, \"a1\")` and `(host_a, \"a2\")` \u2192 `(\"Alphachan\", f\"http://{host_a}/c/alpha_chan\")`\n   - `(host_b, \"b1\")` \u2192 `(\"Betachan\", f\"http://{host_b}/c/beta_chan\")`\n\n   On failure the message includes node's stdout. Exact equality also catches a crawl that wrote nothing.\n\n**Why it fails on today's code.** Whichever order `listChannelsWithVideos` returns the rows in, the id-only map keeps one entry for id `7`, so one host's rows get the other host's name and URL.\n\n**How the fake servers are reached.** The crawler tries https first against the plain-HTTP server. That attempt fails with a TLS error or ECONNRESET, or with an abort when the handler's 1 s read timeout closes the socket. None of these codes is in `isNoNetworkError`, so curl never runs. With `maxRetries 0` the https attempt throws, and `fetchPage` falls back to http. `ThreadingHTTPServer` answers each connection on its own thread, so the stuck https connection does not block the http one.\n\n#### Repair tests\n\n**Seed data.** `_seed(conn)` inserts with named columns, so it works on both schemas. Videos carry `last_checked_at = 1`, a distinct title such as `\"clip v1\"`, and description `\"plain text\"`.\n\n| channels `(channel_id, instance_domain, display_name)` |\n|---|\n| `(\"7\", \"a.example\", \"Alphachan\")` |\n| `(\"7\", \"b.example\", \"Betachan\")` |\n| `(\"8\", \"a.example\", \"\")` |\n| `(\"9\", \"a.example\", None)` |\n\n| video | instance, channel | stored `channel_name` | expected after repair |\n|---|---|---|---|\n| v1 | a.example, 7 | `\"Betachan\"` | `\"Alphachan\"` |\n| v2 | b.example, 7 | `\"Alphachan\"` | `\"Betachan\"` |\n| v3 | b.example, 7 | `\"Betachan\"` | unchanged |\n| v4 | a.example, 8 | `\"Stalename\"` | unchanged (empty `display_name`) |\n| v5 | a.example, 9 | `\"Stalename\"` | unchanged (NULL `display_name`) |\n| v6 | a.example, 404 | `\"Orphanname\"` | unchanged (no channel row) |\n| v7 | a.example, 7 | `None` | `\"Alphachan\"` |\n\n`EXPECTED_CHANGED = 3`.\n\n**Fixture.** `seeded_db` is `@pytest.fixture(params=[\"crawl\", \"whitelist\"])` and uses `jobs` and `tmp_path`:\n- `\"crawl\"` runs `executescript(CRAWL_SCHEMA.read_text())`.\n- `\"whitelist\"` runs `sync.ensure_content_schema(conn)`, which creates `videos_fts` and its triggers, so the index is seeded with the stale names.\n- It then calls `_seed`, commits, closes, and returns the path. The FTS table is present or absent according to the parameter.\n\n**Tests:**\n- **`test_repair_sets_each_video_to_its_own_channel_name(jobs, seeded_db)`**\n  - Calls `repair.repair_channel_names(conn)` and asserts it returns `3`.\n  - Asserts `dict(SELECT video_id, channel_name FROM videos)` equals the expected column.\n  - Asserts the `channels` rows are unchanged, compared with a snapshot taken before the repair.\n  - Asserts a second call returns `0` and leaves the dict the same.\n  - Asserts `has_videos_fts(conn)` is `True` exactly for the `whitelist` parameter.\n- **`test_repaired_fts_finds_own_name_not_foreign_name(jobs, tmp_path)`** (whitelist shape only)\n  - `_matches(conn, name)` runs `SELECT v.video_id FROM videos_fts JOIN videos v ON v.rowid = videos_fts.rowid WHERE videos_fts MATCH ?` with `f'channel_name : \"{name}\"'`.\n  - After the repair, `Alphachan` gives `{\"v1\", \"v7\"}` and `Betachan` gives `{\"v2\", \"v3\"}`. That excludes v1, which carried `Betachan` in the stale index before the repair.\n  - `COUNT(*)` on `videos_fts` equals `COUNT(*)` on `videos`, which is 7.\n- **`test_cli_requires_db_and_logs_changed_count(tmp_path)`**\n  - Running `[sys.executable, str(REPAIR_JOB)]` exits with return code `2` (argparse, `--db` required).\n  - A crawl-shape seeded DB is built inline, and `[sys.executable, str(REPAIR_JOB), \"--db\", str(db)]` exits `0`.\n  - `re.search(r\"channel names repaired rows=(\\d+)\", proc.stderr)` gives `3`. A second run gives `0`.\n\n**Isolation.** Every DB lives under `tmp_path`. No test requests the `engine` or `dataset` fixtures or refers to `WHITELIST_DB`.\n\n---\n\n### 5. Runbook: `DATA_BUILD.md`\n\nInsert after line 158, before `## 3) Build embeddings`:\n\n````markdown\n## 2b) Repair `videos.channel_name` (one-off migration)\nUntil issue 34 was fixed, the video crawler looked up channel metadata by `channel_id` alone, so about 74% of videos carry the display name of the same-id channel on another instance; search and embeddings inherit the wrong name.\n\nThis is a migration of shared databases: run it on main after the fix is merged, never from a worktree. Run it outside an updater cycle and with the Engine idle, because on a `whitelist.db` it rebuilds `videos_fts` and holds the write lock for the duration.\n\n1. Merge the fix to main.\n2. Repair the crawl database:\n   ```bash\n   python3 engine/server/db/jobs/repair-video-channel-names.py --db engine/crawler/data/crawl.db\n   ```\n3. Repair every copy of `whitelist.db`, the prod/server database included. The updater merges `videos` `INSERT_ONLY`, so it never corrects existing rows:\n   ```bash\n   python3 engine/server/db/jobs/repair-video-channel-names.py --db engine/server/db/whitelist.db\n   ```\n4. Operator follow-up, scheduled with plan 17's (stable ANN ids) cutover so the index is rebuilt only once: re-embed, rebuild the ANN index, then the similarity cache.\n   ```bash\n   python3 engine/server/db/jobs/build-video-embeddings.py \\\n     --db-path engine/server/db/whitelist.db --force\n   python3 engine/server/db/jobs/build-ann-index.py \\\n     --db-path engine/server/db/whitelist.db \\\n     --index-path engine/server/db/whitelist-video-embeddings.faiss \\\n     --meta-path engine/server/db/whitelist-video-embeddings.faiss.json \\\n     --normalize --gpu\n   python3 engine/server/db/jobs/precompute-similar-ann.py \\\n     --db engine/server/db/whitelist.db \\\n     --index engine/server/db/whitelist-video-embeddings.faiss \\\n     --out engine/server/db/similarity-cache.db \\\n     --reset --gpu\n   ```\n   Use `--cpu` in place of `--gpu` where there is no CUDA.\n\nNotes:\n- `--db` is required; the job has no default database.\n- The job logs `channel names repaired rows=N`. A second run reports `rows=0`, and on a `whitelist.db` it still rebuilds and checks the full-text index, so re-running is the recovery if a run is interrupted.\n- Search reflects the corrected names as soon as step 3 finishes; similar-video results only do so after step 4.\n- A fresh crawl with the fixed crawler writes correct names by itself, so the job is not part of `run-dataset-build.sh`.\n````\n\n**Plan 17 reference.** The runbook names \"plan 17 (stable ANN ids)\" without a path, because `docs/project/plans/17-stable-ann-ids.md` does not exist in this tree. Line 30's broken `UPDATER_WORKER.md` pointer is not touched. `UPDATER_WORKER.md` is left alone because the `INSERT_ONLY` note is in this section.\n\n---\n\n### Checked against the plan and the requirements\n\n| Requirement | How the draft meets it |\n|---|---|\n| R1 | The key is host plus id at both the build and the lookup, from the same column and lowercased on both sides. Precedence is unchanged, the rest of the crawler is unchanged, and the dist is rebuilt. |\n| R2 | One set-based UPDATE with a `(channel_id, instance_domain)` join, guarded for non-NULL, non-empty and `IS NOT`. `channels` is only read. The count comes from `rowcount`, and a second run returns 0. The CLI has argparse, `CompactHelpFormatter`, a required `--db PATH`, INFO logging and a guarded `main()`. |\n| R3 | The `videos_fts` probe, then the reused drop / update / create / rebuild helpers loaded by `spec_from_file_location`. The count check copies `sync-whitelist.py`'s `RuntimeError`, and the FTS steps are skipped on `crawl.db`. |\n| R4 | A two-host crawl test with the node gates, which fails on today's code. Repair tests on both schemas cover mismatched, correct, empty, NULL, absent and NULL-current rows, plus the second run. There is an FTS test with column-filtered MATCH and the count check, a CLI test, and only `tmp_path` DBs. |\n| R5 | The section after step 2 has the merge / crawl.db / every whitelist.db / re-embed order, \"main after merge only, never from a worktree\", and the timing note. |\n\n**Constraints.** The job uses only the stdlib and adds no dependency or abstraction. The agent never runs it against a real database. The existing suite is untouched: `test_host_normalisation.py` checks `host-filters`, whose source does not change.\n\n**Risks the operator carries** (from the plan, unchanged):\n- The FTS path is not atomic.\n- Every whitelist run pays a full rebuild.\n- The repair joins `instance_domain` exactly as stored, so a channel whose `instance_domain` is stored in mixed case would not be repaired.\n- The new test needs `engine/crawler/node_modules`, a stricter requirement than `test_host_normalisation.py`.\n- Embeddings keep the foreign names until step 4.\n</draft>",
    "step_6_develop_phase_breakdown": "<phases>\n<phase n=\"1\" kind=\"code\">\n<checkpoint>`test_crawl_writes_each_hosts_own_channel_name(tmp_path)` in the new `tests/active/test_channel_names.py`. Seam: the compiled `crawlVideos` exported by `engine/crawler/dist/videos-worker.js`. The test runs it under `node --input-type=module -e` with `cwd=engine/crawler` against two stdlib `ThreadingHTTPServer`s on `127.0.0.1` ephemeral ports and a temp `crawl.db` built from `engine/crawler/schema.sql`. Both channels rows share `channel_id` \"7\" and have different display names and URLs. The test asserts exact equality of `{(instance_domain, video_id): (channel_name, channel_url)}` read from `videos`. Harness precedent: `test_host_normalisation.py::test_crawler_dist_returns_pinned_values`. The test copies its `_git` / `_dist_is_stale` gates and `BUILD_HINT`. A missing node or git, a missing or stale dist, or a nonzero node exit fails the test and never skips it. On today's code the test fails deterministically, because the id-only map keeps one entry for \"7\".</checkpoint>\n<name>Crawler keys channel metadata by host and id</name>\n<intent>`crawlVideos` in `engine/crawler/src/videos-worker.ts` (and its committed `dist/videos-worker.js`) looks up channel metadata by lowercased host plus channel id. As a result, each host's crawled videos carry that host's own channel metadata, even when a channel id repeats across instances.</intent>\n<clause_1>Each host's crawled videos have `channel_name` equal to the `display_name` of the channel on that same host.</clause_1>\n<clause_2>Each host's crawled videos have `channel_url` equal to the `channel_url` of the channel on that same host.</clause_2>\n<files>engine/crawler/src/videos-worker.ts (EDITED), engine/crawler/dist/videos-worker.js (EDITED), tests/active/test_channel_names.py (NEW)</files>\n</phase>\n<phase n=\"2\" kind=\"code\">\n<checkpoint>`test_repair_sets_each_video_to_its_own_channel_name(jobs, seeded_db)`. Seam: the in-process function `repair_channel_names(conn)` in `repair-video-channel-names.py`. The job is loaded with the `_load_job` importlib loader copied from `test_host_normalisation.py`. The fixture `seeded_db` is parametrised over the `crawl` shape (`schema.sql`) and the `whitelist` shape (`ensure_content_schema` from the loaded `sync-whitelist.py`). `_seed` loads the v1\u2013v7 / channels 7, 8, 9 table from the draft. Asserts: the returned count is 3; the `video_id -> channel_name` dict equals the expected column; `channels` equals its pre-repair snapshot; a second call returns 0 and leaves the dict unchanged; `has_videos_fts` is True exactly for the whitelist parameter. Every DB is under `tmp_path`.</checkpoint>\n<name>Repair function corrects channel names</name>\n<intent>The new job `engine/server/db/jobs/repair-video-channel-names.py` exposes `repair_channel_names`. It sets each video's `channel_name` to the non-empty `display_name` of its own `(channel_id, instance_domain)` channel and returns how many rows it changed.</intent>\n<clause_1>After a repair, videos with a foreign or NULL `channel_name` carry their own channel's `display_name`. Already-correct rows, rows whose channel has an empty, NULL or absent display name, and the `channels` table are unchanged.</clause_1>\n<clause_2>The repair returns the number of rows it changed, and a second run returns 0.</clause_2>\n<files>engine/server/db/jobs/repair-video-channel-names.py (NEW), tests/active/test_channel_names.py (EDITED)</files>\n</phase>\n<phase n=\"3\" kind=\"code\">\n<checkpoint>`test_repaired_fts_finds_own_name_not_foreign_name(jobs, tmp_path)`. Seam: the `videos_fts` table of a whitelist-shape temp DB. The DB is created with `ensure_content_schema`, seeded with stale names (so the index holds them), and then repaired through `repair_channel_names`. The test queries `SELECT v.video_id FROM videos_fts JOIN videos v ON v.rowid = videos_fts.rowid WHERE videos_fts MATCH ?` with `channel_name : \"<name>\"`. Asserts: `Alphachan` gives {v1, v7} and `Betachan` gives {v2, v3}, so v1's stale foreign name is gone; `COUNT(*)` on `videos_fts` equals `COUNT(*)` on `videos` (7).</checkpoint>\n<name>Repair rebuilds the search index</name>\n<intent>On a database that has `videos_fts`, the repair runs between `sync-whitelist.py`'s trigger drop and recreate and then rebuilds the index, so full-text search reflects the corrected channel names in full.</intent>\n<clause_1>After the repair, a `channel_name` MATCH for a channel's own name returns that channel's videos, and a MATCH for the other instance's same-id name does not return them.</clause_1>\n<clause_2>After the repair, `videos_fts` holds as many rows as `videos`.</clause_2>\n<files>engine/server/db/jobs/repair-video-channel-names.py (EDITED), tests/active/test_channel_names.py (EDITED)</files>\n</phase>\n<phase n=\"4\" kind=\"code\">\n<checkpoint>`test_cli_requires_db_and_logs_changed_count(tmp_path)`. Seam: the script's command line, run through `subprocess.run([sys.executable, str(REPAIR_JOB), ...])`. Asserts: a bare invocation exits with return code 2. Against an inline-seeded crawl-shape DB under `tmp_path`, the run exits 0, and `re.search(r\"channel names repaired rows=(\\d+)\", proc.stderr)` gives 3. A second run gives 0.</checkpoint>\n<name>Repair CLI</name>\n<intent>`repair-video-channel-names.py` runs as a command that refuses to start without an explicit `--db` and logs the number of rows it changed.</intent>\n<clause_1>Invoking the job without `--db` exits with an argparse usage error (return code 2).</clause_1>\n<clause_2>Invoking the job with `--db` logs `channel names repaired rows=N` with the changed count.</clause_2>\n<files>engine/server/db/jobs/repair-video-channel-names.py (EDITED), tests/active/test_channel_names.py (EDITED)</files>\n</phase>\n</phases>\n\n<needs_coordination>\nPhase 1: the crawl checkpoint needs `node` on PATH and `engine/crawler/node_modules` (better-sqlite3), which `npm install` may need network access to fetch. It also needs the dist rebuilt with `cd engine/crawler && npm run build` and committed with the source, or the staleness gate fails. No credentials are needed and no live endpoints are used: the test binds only to loopback ephemeral ports. No phase touches the real crawl.db or whitelist.db. Running the job against those databases is the operator's post-merge step in the runbook.\n</needs_coordination>\n\n<rationale>\nThe seams follow the draft's own boundaries. The writer fix is verified through the compiled crawler, and the repair job through three separate boundaries: the in-process function, the FTS table, and the CLI. The job's intent covers four observable facts: row correction, count/idempotence, index consistency and CLI behaviour. With at most two clauses per phase, that makes three job phases. Phase 2's whitelist-shape parameter passes without special FTS handling, because the triggers keep the index in step row by row. Phase 3 then adds the drop/update/recreate/rebuild path and proves it with the stale-index MATCH and the count check, so each phase is independently green. The crawler fix is its own phase because it shares no code with the job and needs a different harness (node plus a committed dist). DATA_BUILD.md section 2b is documentation, so it gets no phase and is written in Step 9. There is no prose phase. Four phases is the maximum, so no split into further plans is needed. The operator approved this breakdown.\n</rationale>",
    "author:tests/tmp/test_34_video_channel_name_wrong_instance_phase1.py": "<assertions>\ntests/tmp/test_34_video_channel_name_wrong_instance_phase1.py:112 - exact equality of {(instance_domain, video_id): channel_name} read from `videos` after the compiled `crawlVideos` ran against two local instances whose channel rows share channel_id \"7\": host A's a-1 and a-2 carry \"Alpha Display\", host B's b-1 carries \"Beta Display\". Because the dict is exact, it also rules out any video carrying the other host's name, any missing row and any extra row. Today's code fails it: host A's videos come back as \"Beta Display\". - C1\ntests/tmp/test_34_video_channel_name_wrong_instance_phase1.py:113 - exact equality of {(instance_domain, video_id): channel_url} from the same rows: host A's videos carry http://<host A>/video-channels/alpha and host B's video carries http://<host B>/video-channels/beta. The served video JSON has no `channel` object, so the URL can only come from the channels row the lookup picks. Today's code gives host A beta's URL (seen in the probe). - C2\n</assertions>\n\n<probes>\nCommand: ValidateTests [\"tests/tmp/probe_channel_names.py\", \"-s\"]. The probe was the same harness as the test (two ThreadingHTTPServers on 127.0.0.1, crawl.db built from schema.sql, channels (\"7\",\"alpha\",url_a,\"Alpha Display\",host_a,2) and (\"7\",\"beta\",url_b,\"Beta Display\",host_b,1), node --input-type=module -e with cwd=engine/crawler importing dist/videos-worker.js), with prints added. What it printed:\n- node and git were both on PATH. dist/videos-worker.js exists, and `git status --porcelain` on src and dist was empty, so the stale gate compares commit times.\n- node exited 0 in 0.07s with empty stderr. With maxRetries 0, the https-first attempt against the plain-http servers failed at once and never reached do_GET. The only hits were one http GET per server: /api/v1/video-channels/alpha/videos?start=0&count=50&sort=-publishedAt and /api/v1/video-channels/beta/videos?...\n- videos rows: (hostA,'a-1','7','Beta Display','http://hostB/video-channels/beta'), (hostA,'a-2','7','Beta Display','http://hostB/video-channels/beta'), (hostB,'b-1','7','Beta Display','http://hostB/video-channels/beta'). This is the value under the wrong implementation: the id-only map keeps the last \"7\" row.\n- video_crawl_progress ended 'done' for both hosts. listChannelsWithVideos returned the rows in insertion order (A, then B).\nThen ValidateTests [\"tests/tmp/test_34_video_channel_name_wrong_instance_phase1.py\"] failed at line 112 (C1), with {(hostA,'a-1'): 'Beta Display'} != 'Alpha Display' and the same for a-2. All gates passed and node exit was 0.\nEither row order leaves one host wrong under the id-only map, so the red does not depend on order. I have no tool that deletes files, so the probe file tests/tmp/probe_channel_names.py is still on disk and needs removing.\n</probes>\n\n<unassertable>\nnone\n</unassertable>",
    "self_check:tests/tmp/test_34_video_channel_name_wrong_instance_phase1.py": "<rows>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_34_video_channel_name_wrong_instance_phase1.py:112 \u2014 `names`, keyed by (instance_domain, video_id) over every stored video row, equals exactly {(host_a,\"a-1\"):\"Alpha Display\", (host_a,\"a-2\"):\"Alpha Display\", (host_b,\"b-1\"):\"Beta Display\"}</assertion>\n<expected>Once the phase is built, alpha's two videos carry \"Alpha Display\" and beta's one video carries \"Beta Display\", with no other rows. The current code reached this assertion with rc 0 and all three videos stored (crawl log \"new=2\", \"new=1\", \"new_total=3\"), so the row set and keys are observed. The per-host values are the fixture's own display_name for each host.</expected>\n<wrong_implementation>The current code keys `channelMeta` by `channel_id` alone (videos-worker.ts:163-172), so the two \"7\" rows collide and one host's meta overwrites the other's. Observed in the gating run: `{(host_a,'a-1'): 'Beta Display', (host_a,'a-2'): 'Beta Display'}`, so alpha's videos got beta's name. Observed in the probe run: b-1 read 'Alpha Display'. Which host wins changes between runs, and the assertion goes red either way. Other wrong fixes it excludes: using the slug `channel_name` (\"alpha\"/\"beta\" instead of the display names), or storing null.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_34_video_channel_name_wrong_instance_phase1.py:113 \u2014 `urls`, keyed by (instance_domain, video_id), equals exactly {(host_a,\"a-1\"):url_a, (host_a,\"a-2\"):url_a, (host_b,\"b-1\"):url_b}, where url_a/url_b are each host's own channels.channel_url</assertion>\n<expected>Once the phase is built, a-1 and a-2 carry `http://<host_a>/video-channels/alpha` and b-1 carries `http://<host_b>/video-channels/beta`. The stand-in videos carry no `channel`, so `channelRef?.url` is absent and the value can only come from the channels row. The probe run confirmed that with every other fallback absent, the stored URL comes from that meta.</expected>\n<wrong_implementation>With the same channel_id-only `channelMeta` key, the colliding meta supplies the other host's URL. Observed in the probe run (same fixture as the checkpoint): `('127.0.0.1:40483', 'b-1', 'Alpha Display', 'http://127.0.0.1:41925/video-channels/alpha')`, so beta's video got alpha's URL. The name could be fixed while the URL still comes from shared meta, and C2 catches that partial fix.</wrong_implementation>\n</row>\n</rows>\n\n<answers>\n1. Whole claim \u2014 no gap. Docstring bullet 1 / C1 is carried by line 112, and bullet 2 / C2 by line 113. Both compare whole dicts over every stored row, so \"no video carries the other host's name/URL\" is enforced: any foreign value or extra row breaks equality. Bullet 3 (missing node/git, missing or stale dist, nonzero node exit fail instead of skipping) is carried by the plain asserts at lines 73, 74, 76, 77 and 103. There is no pytest.skip anywhere.\n2. Absence only \u2014 no. The \"not the other host's value\" half is not an absence assertion. It sits inside an exact-equality check that also requires the three expected rows to be present with specific values. Line 103 (rc 0) plus the required keys prove the crawl path ran.\n3. Echoed literal \u2014 no. The test only seeds channels rows and reads back what `crawlVideos` wrote into `videos`, and it does no mapping of its own. Deleting `displayName: channel.display_name` (videos-worker.ts:168) turns line 112 red (null names). Deleting `channelUrl: channel.channel_url` (line 169) turns line 113 red. The fix itself is to line 165's channel_id-only key.\n4. One value \u2014 no. There are two hosts and three videos, with distinct display names and URLs. The display names (\"Alpha Display\") differ from the slugs (\"alpha\"), so a slug-for-display-name mixup also fails. The expected values come from the fixture's channels rows, not from a sibling output.\n5. The double \u2014 no project module is doubled. The two HTTP servers stand in for external PeerTube instances, which is a severed network layer. The real compiled `dist/videos-worker.js`, `db.ts` store and `schema.sql` all run.\n6. It collects \u2014 yes. The gating run printed \"collected 1 item\", and one test was written. The imports are stdlib only. `crawlVideos` and every options key match `VideoCrawlOptions` in videos-worker.ts:26-45. The channels/instances columns were accepted by the real schema, since the run got past the inserts and the crawl stored rows. The pre-supplied `--collect-only -q` summary printed \"no tests\" with exit 0. The real run shows the item collects, so I read that as the summary format under collect-only, not a collection defect.\n7. Observed, not predicted \u2014 yes, all observed. The stand-in's response shape was seen working (\"channel done \u2026/alpha new=2 total=2\", \"\u2026/beta new=1 total=1\"). The C1 wrong reading came from the gating run. The C2 reading was not reached there because line 112 failed first, so I ran a probe (tests/tmp/test_probe_34_urls.py, same fixture, printing every row). It showed rc=0 and b-1 stored with 'Alpha Display' and alpha's URL, so C2 is also red against the current code. No rewrite was needed. One thing the probe revealed: which host wins the collision varies between runs (Beta in the gating run, Alpha in the probe). The exact-dict assertions are red under either winner. I have no delete tool, so I emptied both probe files (tests/tmp/test_probe_34_urls.py and tests/tmp/probe_34_urls.py, the second an earlier misnamed copy that was never collected). They collect nothing now but should be deleted.\n8. Red, not green \u2014 yes, it is red. ValidateTests: \"tests/tmp/test_34_video_channel_name_wrong_instance_phase1.py  1 failed\", \"[exit status 1]\".\n9. Red for the right reason \u2014 yes. Every control passed: node found, dist present and not stale, git present, and line 103 `proc.returncode == 0` passed, with the crawl log showing \"[videos] finished new_total=3\". The failure is the C1 judging assertion: \"tests/tmp/test_34_video_channel_name_wrong_instance_phase1.py:112: AssertionError\" with \"{('127.0.0.1:40317', 'a-1'): 'Beta Display'} != {('127.0.0.1:40317', 'a-1'): 'Alpha Display'}\" and the same for 'a-2'. That is the channel_id collision in `channelMeta`, which is exactly the bug the phase fixes.\n10. Observed expected output \u2014 yes. The C1 row quotes the run's own diff. For the C2 row, the probe printed `('127.0.0.1:40483', 'b-1', 'Alpha Display', 'http://127.0.0.1:41925/video-channels/alpha')`, so the current reading is the other host's URL. The fixed-implementation values in both rows are the fixture's per-host channels values. The run confirmed the set of stored keys (a-1, a-2 under host_a, b-1 under host_b) that those values attach to. Nothing the run showed contradicted a row, so the test was not rewritten.\n</answers>\n\n<exemptions>\nnone\n</exemptions>",
    "step_7_implement:1": "<changes>\n### `engine/crawler/src/videos-worker.ts`\n- `crawlVideos` now keys the `channelMeta` map by `channelMetaKey(channel.instance_domain.toLowerCase(), channel.channel_id)` instead of by `channel.channel_id` alone. Before, when two instances had the same channel id, the later row overwrote the earlier one and both hosts got the same `channel_name`/`channel_url`.\n- `processInstance` looks up metadata with `channelMetaKey(normalizedHost, item.channelId)`. `normalizedHost` is already lowercased, so both sides of the lookup use the same host form.\n- New helper `channelMetaKey(host, channelId)` returns `` `${host}/${channelId}` ``. A host cannot contain `/`, so two different host/id pairs can never produce the same key. It has a one-line JSDoc comment explaining why ids need the host, matching the file's other function comments.\n\n### `engine/crawler/dist/videos-worker.js`\n- Edited by hand to match the source change in the style tsc produces here (same two call sites, plus `channelMetaKey` with its JSDoc and no type annotations). I have no shell, so I could not run `npm run build`. The dist was saved after the source, so its mtime is newer and the checkpoint's staleness check, which compares mtimes on a dirty tree, will pass. There is no source map to update.\n\n### `tests/active/test_channel_names.py`\n- Not created. It is the checkpoint's permanent location, and this turn was limited to production code. The gating checkpoint stays at `tests/tmp/test_34_video_channel_name_wrong_instance_phase1.py`, unchanged.\n</changes>\n\n<inner_tests>\nnone\n</inner_tests>\n\n<unanticipated>\nnone\n</unanticipated>\n\n<awaiting_operator>\nnone\n</awaiting_operator>",
    "author:tests/tmp/test_34_video_channel_name_wrong_instance_phase2.py": "<assertions>\ntests/tmp/test_34_video_channel_name_wrong_instance_phase2.py:73 - control, before the repair: the seeded `video_id -> channel_name` dict equals STORED, so a failure later cannot come from a seed that never landed (setup control, no clause)\ntests/tmp/test_34_video_channel_name_wrong_instance_phase2.py:78 - the first `repair_channel_names(conn)` returns exactly 3 on both shapes. Observed wrong values: `!=` instead of `IS NOT` gives 2, no empty-name guard gives 4, joining on channel_id alone gives 4, no WHERE clause gives 7 (C2)\ntests/tmp/test_34_video_channel_name_wrong_instance_phase2.py:83 - read on a fresh connection, the dict equals REPAIRED: v1, v2 and v7 (foreign or NULL names) carry their own channel's display name, and v3 (already correct), v4 (empty display_name), v5 (NULL display_name) and v6 (no channel row) keep their stored names. Reopening means a repair that never commits reads back as STORED, which was observed (C1)\ntests/tmp/test_34_video_channel_name_wrong_instance_phase2.py:84 - `SELECT * FROM channels ORDER BY channel_id, instance_domain` equals the snapshot taken before the repair (C1)\ntests/tmp/test_34_video_channel_name_wrong_instance_phase2.py:85 - `has_videos_fts(conn)` is True exactly when the parameter is `whitelist`, after the repair. This is the agreed shape control, confirming the run covered the named schema (no clause)\ntests/tmp/test_34_video_channel_name_wrong_instance_phase2.py:86 - a second `repair_channel_names(conn)` returns 0. Observed wrong value: joining on channel_id alone gives 4 again, and no WHERE clause gives 7 (C2)\ntests/tmp/test_34_video_channel_name_wrong_instance_phase2.py:92 - after the second call, a fresh connection still reads the dict as REPAIRED (C2)\n</assertions>\n\n<probes>\nCommand: ValidateTests [\"tests/tmp/test_probe_34_phase2.py\", \"-s\"]. The probe loaded sync-whitelist.py with the _load_job loader, built both shapes (crawl via executescript(schema.sql), whitelist via ensure_content_schema), seeded the draft's channels 7/8/9 and videos v1-v7 with named columns, and applied the draft UPDATE plus wrong variants. It printed the following. The repair job does not exist yet. On the crawl shape, sqlite_master has no videos_fts objects. On the whitelist shape it has the videos_fts table, its shadow tables and the triggers videos_fts_ai/ad/au. On both shapes the seeded dict reads {'v1': 'Betachan', 'v2': 'Alphachan', 'v3': 'Betachan', 'v4': 'Stalename', 'v5': 'Stalename', 'v6': 'Orphanname', 'v7': None}, and inserting into the whitelist shape's videos with its triggers in place succeeded. Draft SQL on both shapes: count 3, after {'v1': 'Alphachan', 'v2': 'Betachan', 'v3': 'Betachan', 'v4': 'Stalename', 'v5': 'Stalename', 'v6': 'Orphanname', 'v7': 'Alphachan'}, second run 0. `!=` in place of `IS NOT`: count 2, v7 stays None. No `<> ''` guard: count 4, v4 becomes ''. No `IS NOT NULL` guard: identical to the draft, because `NULL <> ''` is already false. Join on channel_id alone: count 4, v2 and v3 become 'Alphachan', second run 4. No WHERE clause: count 7, v4 becomes '', v5 and v6 become None, second run 7. Draft SQL run with no commit and the connection closed: after reopening, the dict reads as the seeded values. Command: ValidateTests [\"tests/tmp/test_34_video_channel_name_wrong_instance_phase2.py\"]. Both parameters error in the `jobs` fixture with FileNotFoundError for engine/server/db/jobs/repair-video-channel-names.py, the expected red before phase 2 is implemented. The probe file tests/tmp/test_probe_34_phase2.py has been emptied, because no tool here can delete it. It should be removed.\n</probes>\n\n<unassertable>\nnone\n</unassertable>",
    "self_check:tests/tmp/test_34_video_channel_name_wrong_instance_phase2.py": "<rows>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_34_video_channel_name_wrong_instance_phase2.py:85 \u2014 on a fresh connection after the first repair, `dict(SELECT video_id, channel_name FROM videos) == REPAIRED`: v1 \u2192 Alphachan, v2 \u2192 Betachan, v7 (was NULL) \u2192 Alphachan, and v3 Betachan, v4 Stalename, v5 Stalename, v6 Orphanname unchanged. Run on both the crawl and whitelist shapes.</assertion>\n<expected>{'v1': 'Alphachan', 'v2': 'Betachan', 'v3': 'Betachan', 'v4': 'Stalename', 'v5': 'Stalename', 'v6': 'Orphanname', 'v7': 'Alphachan'} on both shapes. The probe observed exactly this dict after running the draft's REPAIR_SQL on each shape.</expected>\n<wrong_implementation>Each wrong variant below was observed in the probe on both shapes. `!=` instead of `IS NOT` leaves v7 None. Dropping the empty-name guard writes '' into v4. An unguarded update also writes None into v5. Joining on channel_id alone gives v2 and v3 'Alphachan'. A repair that never commits reads back as the seeded names when the database is reopened. Each of these makes the dict differ from REPAIRED.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_34_video_channel_name_wrong_instance_phase2.py:86 \u2014 after the repair, `SELECT * FROM channels ORDER BY channel_id, instance_domain` on a fresh connection equals the snapshot taken at line 74, before the repair. It is armed by line 85, which shows that the repair ran and wrote.</assertion>\n<expected>The pre-repair rows unchanged. The probe observed four rows, for example on the crawl shape ('7',None,None,'Alphachan','a.example',\u2026), ('7',None,None,'Betachan','b.example',\u2026), ('8',None,None,'','a.example',\u2026), ('9',None,None,None,'a.example',\u2026), and the whitelist shape has its own column order.</expected>\n<wrong_implementation>A repair that also \"syncs\" channels, for example writing display_name into channels.channel_name, filling the empty or NULL display_name for channels 8 and 9, or pruning channel rows with no videos. The snapshot then differs in at least one row. This case was not run in the probe; the assertion is a direct before/after comparison of the whole table.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_34_video_channel_name_wrong_instance_phase2.py:80 \u2014 the first `repair.repair_channel_names(conn)` returns exactly 3.</assertion>\n<expected>3 on both shapes, taken from the UPDATE's rowcount in the probe. On the whitelist shape, trigger writes to videos_fts are not counted.</expected>\n<wrong_implementation>Counts observed in the probe: `!=` returns 2; no empty-name guard returns 4; channel_id-only join returns 4; unguarded returns 6. A function that returns the number of candidate rows (7) or a fixed value also fails.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_34_video_channel_name_wrong_instance_phase2.py:88 \u2014 a second `repair_channel_names(conn)` on a fresh connection returns 0. Line 94 then reopens the database and checks that the names still equal REPAIRED.</assertion>\n<expected>0 on the second call and the REPAIRED dict afterwards. The probe observed a second rowcount of 0 for the draft SQL on both shapes.</expected>\n<wrong_implementation>Second-run counts observed in the probe: channel_id-only join returns 4 again, because v2 and v3 flip back and forth; unguarded returns 6; no commit returns 3, because the first run was lost. A version that re-writes every matching row without the `IS NOT channel_name` guard returns non-zero every run. Line 94 catches a second run that changes names.</wrong_implementation>\n</row>\n</rows>\n\n<answers>\n1. Whole claim: yes, it covers every clause. C1: line 85 checks the foreign rows (v1, v2), the NULL row (v7), the already-correct row (v3), the empty display name (v4), the NULL display name (v5) and the absent channel (v6); line 86 checks `channels`. C2: line 80 checks the count 3, and lines 88 and 94 check that the second call returns 0 and leaves the names alone. The docstring's fourth bullet (`has_videos_fts`) is line 87, a supporting assertion. No gap.\n2. Absence only: no. The \"unchanged\" checks sit inside the full-dict equality at line 85, which also requires v1, v2 and v7 to change, so the positive control is in the same assertion. The channels snapshot (line 86) is armed by line 85, and the second-run 0 (line 88) by the first-run 3 (line 80). The seed control at line 73 proves the stored names landed before the repair runs.\n3. Echoed literal: no. REPAIRED and 3 are literals and the test performs no UPDATE of its own. Deleting the UPDATE in `repair_channel_names` (or its `commit()`) turns lines 80 and 85 red. Dropping the `IS NOT videos.channel_name` term turns line 88 red. Dropping the `<> ''` term turns lines 80 and 85 red (4 rows, v4 = '').\n4. One value: no. The name is read across seven rows covering six distinct cases, and the count on two runs. Everything runs on two schema shapes, with channel 7 on two instances so that each instance's rows start with the other's name.\n5. The double: no. No doubles. The real `sync-whitelist.py` `ensure_content_schema`, the real `schema.sql` and real SQLite files under tmp_path are used.\n6. It collects: yes. The run collected 2 items (crawl and whitelist). `sync_whitelist_channel_names` loads, and the seed and control ran on both shapes. The only unresolved name is the phase's own module.\n7. Observed: yes, from a run. The probe `tests/tmp/probe_34_phase2_seed.py` ran the plan's REPAIR_SQL and six wrong variants on both shapes. It printed the seeded dict (equal to STORED), the channels rows, the draft's rowcount 3 and post-repair dict (equal to REPAIRED), the second rowcount 0, and videos_fts present only on the whitelist shape. It also printed the wrong variants' readings quoted in the rows (2/4/4/6 and 3-after-no-commit). The one row not probed is the channels-mutating implementation in the second C1 row, and it says so.\nREWRITE made: the first run of the checkpoint as handed to me errored at setup (\"ERROR at setup of test_repair_sets_each_video_to_its_own_channel_name[crawl]\", FileNotFoundError at line 36 in the `jobs` fixture). So the seed control at line 74 never ran and nothing about the fixture was measured. I replaced `jobs` with a `sync_job` fixture that loads only sync-whitelist.py. The repair module is now loaded in the test body after the seed control (line 76), and the test takes only `seeded_db`.\n8. Red, not green: yes, it is red. ValidateTests exit status 1, \"2 failed\".\n9. Right reason: yes. Both params fail at line 76, `repair = _load_job(\"repair_video_channel_names\", \"repair-video-channel-names.py\")`, with \"FileNotFoundError: [Errno 2] No such file or directory: '.../engine/server/db/jobs/repair-video-channel-names.py'\". That file is this phase's NEW deliverable. The seed control at line 73 (`_names(conn) == STORED`) passed on both shapes before the failure, so this is not a control failure.\n10. Observed expected output: each row's expected value is the value the probe run printed for the plan's SQL (rowcount 3, the REPAIRED dict, second rowcount 0, the channels rows). The checkpoint run itself stops at line 76 before any judging assertion, as it must before the phase exists. Nothing the run showed contradicts a row.\nNote: I have no delete tool, so `tests/tmp/probe_34_phase2_seed.py` (always fails by design, `assert False, \"probe\"`) is still on disk and should be removed. It is outside tests/active, so suite discovery does not reach it.\n</answers>\n\n<exemptions>\nnone\n</exemptions>",
    "step_7_implement:2": "<changes>\n### `engine/server/db/jobs/repair-video-channel-names.py` (NEW)\nA new job module with two functions, stdlib `sqlite3` only:\n- `repair_channel_names(conn) -> int` runs one `UPDATE videos` statement inside `with conn:`, so it commits. It sets `channel_name` to the `display_name` of the channel matching the video's own `(channel_id, instance_domain)`. A row is only touched when that channel exists, its `display_name` is not NULL or empty, and the stored name differs from it (`IS NOT`, so NULL stored names get repaired too). It returns `cursor.rowcount`, the number of rows it changed, which makes a second run return 0. `channels` is only read, never written. On the whitelist shape, the existing `videos_fts_au` trigger re-indexes each changed row.\n- `has_videos_fts(conn) -> bool` checks `sqlite_master` for the `videos_fts` table. It is True on the whitelist shape and False on the crawl shape.\n\nThere is no CLI entry point yet. The checkpoint only exercises the functions, and this phase's intent only calls for exposing `repair_channel_names`.\n\nI did not touch `tests/active/test_channel_names.py`, which the phase lists as EDITED. It does not exist in the worktree yet, and nothing in this phase's checkpoint needs it. I read that entry as the promotion target for the checkpoint, which the workflow handles.\n\nI checked the behaviour with a throwaway probe (`tests/tmp/probe_repair_rowcount.py`), using the same seed shape as the checkpoint on both a crawl-schema and a whitelist-schema database:\n- **Both shapes:** the first call returned 3 and the second returned 0. After reopening the database, v1 and v7 read `A` and v2 read `B`, while v3\u2013v6 kept their stored names.\n- **Whitelist shape:** `has_videos_fts` was True, and `rowcount` was still 3 even with the FTS triggers firing. An FTS5 `integrity-check` passed after the update, and `channel_name:A` matched rowids 1 and 7.\n\nI have no tool that deletes files, so the probe file is still in `tests/tmp/` and should be removed. It is not part of the phase.\n</changes>\n\n<inner_tests>\nnone\n</inner_tests>\n\n<unanticipated>\nnone\n</unanticipated>\n\n<awaiting_operator>\nnone\n</awaiting_operator>",
    "author:tests/tmp/test_34_video_channel_name_wrong_instance_phase3.py": "<assertions>\ntests/tmp/test_34_video_channel_name_wrong_instance_phase3.py:65 - after the repair, read through a fresh connection, a `channel_name : \"Alphachan\"` MATCH (joined to videos by rowid) returns exactly {v1, v7}. This includes v1, whose stale index entry still said Betachan, and excludes v2 and v3, the other instance's same-id channel. Phase 2's code gives {v7} (observed), and a repair that never commits would give {v2}. - C1\ntests/tmp/test_34_video_channel_name_wrong_instance_phase3.py:66 - `channel_name : \"Betachan\"` returns exactly {v2, v3}, so v1's foreign name is gone from the index. Phase 2's code gives {v1, v2, v3} (observed). - C1\ntests/tmp/test_34_video_channel_name_wrong_instance_phase3.py:68 - COUNT(*) on `videos_fts_docsize`, the index's own per-row table, equals COUNT(*) on `videos`, and both are 7. This is a deviation the operator approved, replacing the vacuous COUNT(*) on `videos_fts`. It is 0 on an index that was never built (observed). - C2\ntests/tmp/test_34_video_channel_name_wrong_instance_phase3.py:70 - the FTS5 `integrity-check` command passes, meaning the index agrees with `videos`. On Phase 2's code it raises `fts5: checksum mismatch for table \"videos_fts\"` (observed), and on an index that was never built it raises `database disk image is malformed`. - C2\ntests/tmp/test_34_video_channel_name_wrong_instance_phase3.py:57 - a setup check, not a clause: before the repair the drifted index gives Alphachan={v2} and Betachan={v1, v3}, which shows the index still holds v1's stale name when the repair starts.\nCurrent run against Phase 2's code: the setup check passes, and the test fails at line 65 with `{'v7'} == {'v1', 'v7'}`.\n</assertions>\n\n<probes>\ntests/tmp/test_probe_34_phase3.py, run with ValidateTests [\"tests/tmp/test_probe_34_phase3.py\"] three times. Same v1-v7 / channels 7, 8, 9 seed as phase 2, on ensure_content_schema. It compares the current (Phase 2) repair_channel_names with a simulated Phase 3 (drop_videos_fts_triggers, then the same UPDATE, then create_videos_fts_triggers, rebuild_videos_fts, commit).\nAgreed fixture (seed with triggers live): before the repair, Alphachan=['v2'] and Betachan=['v1','v3']. After the repair, both Phase 2 and the simulated Phase 3 give Alphachan=['v1','v7'] and Betachan=['v2','v3'], counts 7 7, integrity ok. So the agreed checkpoint could not fail on Phase 2's code.\nIndex never built (seeded with triggers dropped): COUNT(*) FROM videos_fts=7, videos=7, docsize 0, integrity 'database disk image is malformed'. Phase 2's repair raised 'database disk image is malformed'. The simulated Phase 3 gave ['v1','v7'] / ['v2','v3'], docsize 7, integrity ok. So COUNT(*) on the external-content videos_fts is vacuous.\nDrifted fixture (normal seed, then v1 set to Alphachan with the triggers dropped, then the triggers recreated): before the repair, Alphachan=['v2'], Betachan=['v1','v3'], integrity 'fts5: checksum mismatch for table \"videos_fts\"', docsize 7. Phase 2: changed 2, then Alphachan=['v7'], Betachan=['v1','v2','v3'], still a checksum mismatch, docsize 7. Simulated Phase 3: Alphachan=['v1','v7'], Betachan=['v2','v3'], integrity ok, docsize 7.\nOperator decision (AskUser): use the drifted fixture and measure C2 with docsize and integrity-check.\nThe checkpoint itself, run with ValidateTests [\"tests/tmp/test_34_video_channel_name_wrong_instance_phase3.py\"], fails at line 65: `assert {'v7'} == {'v1', 'v7'}`.\nI have no delete tool, so the probe file tests/tmp/test_probe_34_phase3.py is still there and should be removed. It ends in `assert False`.\n</probes>\n\n<unassertable>\nnone. The agreed seam is changed in two ways the operator approved. (1) Before the repair, the fixture sets v1 to Alphachan with the triggers dropped, so the index is stale. On the fixture as agreed, the Phase 2 code already passes. (2) C2 is measured on `videos_fts_docsize` and with integrity-check, because COUNT(*) on `videos_fts` reads the content table and gives 7 even when the index is empty. The docsize count alone does not tell Phase 2 apart on the drifted fixture (it is 7 there too). The integrity-check is what does.\n</unassertable>",
    "self_check:tests/tmp/test_34_video_channel_name_wrong_instance_phase3.py": "<rows>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_34_video_channel_name_wrong_instance_phase3.py:77 \u2014 after repair_channel_names, read through a fresh connection, `channel_name : \"Alphachan\"` MATCH joined to videos returns exactly {\"v1\", \"v7\"}</assertion>\n<expected>{\"v1\", \"v7\"}. I observed this in the probe run with repair + rebuild_videos_fts + commit: \"REBUILT after ['v1', 'v7'] ...\".</expected>\n<wrong_implementation>The current repair, which relies only on the per-row videos_fts_au trigger and never rebuilds, can't re-index v1. v1 was corrected in videos while the triggers were dropped, so the UPDATE's `IS NOT` guard skips it and the index keeps its foreign \"Betachan\". The run showed this reads {'v7'}. A rebuild that never commits reads the same through the reopened connection.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_34_video_channel_name_wrong_instance_phase3.py:78 \u2014 the same MATCH for the other instance's same-id name, \"Betachan\", returns exactly {\"v2\", \"v3\"}, so a.example's v1 is not found under b.example's name</assertion>\n<expected>{\"v2\", \"v3\"}. I observed this in the probe: \"REBUILT after ... ['v2', 'v3']\".</expected>\n<wrong_implementation>Under the trigger-only repair the index still carries v1 under \"Betachan\", and the probe read ['v1', 'v2', 'v3']. A repair that copied names across instances by channel_id alone would also put the wrong name back on v1 or v2 and break one of the two sets.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_34_video_channel_name_wrong_instance_phase3.py:79 \u2014 (COUNT(*) FROM videos_fts_docsize, COUNT(*) FROM videos) == (8, 8) after the repair</assertion>\n<expected>(8, 8). I observed this in the probe after repair + rebuild: \"REBUILT after ... 8 8\".</expected>\n<wrong_implementation>A repair that only fires row triggers never indexes v8. v8 was inserted while the triggers were dropped, and its channel's display name is empty, so the UPDATE skips it. The probe read \"CURRENT after ... 7 8\", which is (7, 8).</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_34_video_channel_name_wrong_instance_phase3.py:81 \u2014 the FTS5 `integrity-check` with rank 1 (which checks the index against the videos content table) runs without raising</assertion>\n<expected>No exception. I observed this in the probe: \"REBUILT integrity ok\".</expected>\n<wrong_implementation>Under the trigger-only repair the index disagrees with videos (v1's stale name, v8 missing), and the probe showed \"CURRENT integrity raised DatabaseError database disk image is malformed\".</wrong_implementation>\n</row>\n</rows>\n\n<answers>\n1. Whole claim \u2014 yes, before the rewrite. C1 was carried at lines 65/66. But C2's docsize == videos == 7 was already true under the current code: the drift scenario only renamed a row, so both counts stayed at 7 and the C2 assertion excluded no implementation. Rewrite: the drift now also inserts v8 (channel 8, whose display name is empty, so the repair's UPDATE never touches it) while the triggers are dropped. The index is then one row short, and C2 now expects (8, 8) against a starting (7, 8). The docstring was updated to say so. The integrity-check line (81) carries the docstring's \"integrity-check passes\". After the rewrite, the answer is no.\n2. Absence only \u2014 no. The \"not found under the other instance's name\" half of C1 comes from exact set equality, not from a bare absence check. Both sets have to be exactly right, and two controls before the repair (lines 69 and 70) prove the index started out stale: Alphachan \u2192 {v2}, Betachan \u2192 {v1, v3}, docsize/videos \u2192 (7, 8).\n3. Echoed literal \u2014 no. The test never runs the repair's UPDATE or a rebuild itself. Lines 77\u201381 go red if the phase's rebuild/commit in repair_channel_names is deleted, i.e. the current code, which the run confirms. Deleting the correlated `c.instance_domain = videos.instance_domain` predicate in REPAIR_CHANNEL_NAMES_SQL would put a foreign name back and break line 77 or 78.\n4. One value \u2014 no. The MATCH is read for two names across four channel-7 videos on two instances, plus orphan, empty-name and NULL-name channels. The index count comes from videos_fts_docsize (the shadow table) and is compared against videos, which is a different source, and the two start out unequal (7 vs 8).\n5. The double \u2014 no. There are no doubles. The real sync-whitelist.py schema/trigger helpers and the real repair module run against a real SQLite file.\n6. It collects \u2014 yes, it does. The workflow's collect-only summary printed \"no tests\", but the real run printed \"collected 1 item\". All names bind: ensure_content_schema, drop_videos_fts_triggers, create_videos_fts_triggers and repair_channel_names exist in the job files.\n7. Observed, not predicted \u2014 the original C2 expectation (7) was never observed failing and turned out to be vacuous. Every expected value now comes from the probe tests/tmp/probe_34_fts_rowcount.py, which ran the scenario both ways. With the current code it printed \"CURRENT after ['v7'] ['v1', 'v2', 'v3'] ['v4', 'v5'] 7 8\" and \"CURRENT integrity raised DatabaseError database disk image is malformed\". With the repair followed by rebuild_videos_fts and commit it printed \"REBUILT after ['v1', 'v7'] ['v2', 'v3'] ['v4', 'v5', 'v8'] 8 8\" and \"REBUILT integrity ok\". I have no delete tool, so I emptied the probe to a single comment line (it collects nothing); it should be deleted.\n8. Red, not green \u2014 yes, red. ValidateTests printed \"1 failed \u2026 recorded: tests/last_test_validation.json (exit 1)\", exit status 1.\n9. Red for the right reason \u2014 yes. Both controls passed: lines 69 (stale names) and 70 ((7, 8) counts) ran before the failure. The failure is at the first judging assertion, \"tests/tmp/test_34_video_channel_name_wrong_instance_phase3.py:77: AssertionError \u2026 assert {'v7'} == {'v1', 'v7'} \u2026 Extra items in the right set: 'v1'\". The trigger-only repair can't re-index v1, which drifted behind the index's back, and that is exactly the missing rebuild the phase adds.\n10. Observed expected output \u2014 yes. Line 77's {'v7'} under the current code matches both the run and the probe. The expected values {v1, v7}, {v2, v3}, (8, 8) and a clean integrity check are what the probe showed after repair + rebuild + commit. Lines 78\u201381 were not reached in the checkpoint run itself; their current-code readings ({v1, v2, v3}, (7, 8), DatabaseError) come from the probe.\n</answers>\n\n<exemptions>\nnone\n</exemptions>",
    "step_7_implement:3": "<changes>\nI ran none of the gating tests myself. Everything I checked came from a throwaway probe, described below.\n\n### `engine/server/db/jobs/repair-video-channel-names.py`\n- **New `_load_sync_whitelist()`.** Loads `sync-whitelist.py` with `importlib.util.spec_from_file_location`, because its hyphenated name rules out a normal import. This lets the job reuse the file's `videos_fts` helpers instead of copying FTS SQL. It runs only on the FTS path, so crawl.db never loads that file.\n- **`repair_channel_names(conn)` without `videos_fts` (crawl shape).** Unchanged: one UPDATE inside `with conn:`, returning the number of rows changed.\n- **`repair_channel_names(conn)` with `videos_fts` (whitelist shape).** Follows the same order as `rebuild_content_tables`:\n  1. `drop_videos_fts_triggers`\n  2. the UPDATE, with `rowcount` read straight away\n  3. `create_videos_fts_triggers`\n  4. `rebuild_videos_fts`\n  5. compare the rebuilt count with `COUNT(*)` on `videos`, and raise `RuntimeError` in `sync-whitelist.py`'s wording if they differ\n  6. `conn.commit()`\n- **Rebuild on every run.** The rebuild and count check run even when nothing changed. So re-running the job fixes an index left stale by an interrupted run, and it also fixes drift that the per-row trigger `'delete'` cannot mend.\n- **`rat-tail:` comment.** Records that the helpers use `executescript`, which commits. The update is therefore already committed before the rebuild, and a failed rebuild is recovered by running the job again, not by rollback. Upgrade path: have the helpers run their SQL through `conn.execute` instead.\n- **Docstrings.** The module and function docstrings now describe the rebuild.\n\n**Probe results.** The probe (`tests/tmp/probe_34_phase3_impl.py`) built a smaller version of the checkpoint's drifted index on a whitelist-shaped database: v1 corrected and v8 inserted while the triggers were dropped.\n- The second run returned 0.\n- After reopening, `channel_name : \"Alphachan\"` matched `['v1', 'v7']` and `\"Betachan\"` matched `['v2']`.\n- `videos_fts_docsize` held 4 rows for 4 videos, and the FTS5 integrity-check passed.\n- On a crawl-shaped database, `has_videos_fts` was False.\n\nI have no delete tool, so I emptied the probe file instead of removing it. It is part of no phase and should be deleted.\n\n### `tests/active/test_channel_names.py`\nNot touched. As in Phase 2, I read the listing as the checkpoint's promotion target, which the workflow handles.\n</changes>\n\n<inner_tests>\nnone\n</inner_tests>\n\n<unanticipated>\nnone\n</unanticipated>\n\n<awaiting_operator>\nnone\n</awaiting_operator>",
    "author:tests/tmp/test_34_video_channel_name_wrong_instance_phase4.py": "<assertions>\ntests/tmp/test_34_video_channel_name_wrong_instance_phase4.py:41 - running the script with no arguments exits with return code 2 (C1)\ntests/tmp/test_34_video_channel_name_wrong_instance_phase4.py:42 - that run's stderr contains argparse's \"the following arguments are required: --db\", so the code 2 comes from `--db` being required and not from some other failure (C1)\ntests/tmp/test_34_video_channel_name_wrong_instance_phase4.py:43 - that run logs no `channel names repaired rows=N` line, so nothing was repaired against a default DB (C1)\ntests/tmp/test_34_video_channel_name_wrong_instance_phase4.py:54 - control, not a clause: the inline crawl-schema seed reads back as the stored names before the job runs\ntests/tmp/test_34_video_channel_name_wrong_instance_phase4.py:57 - the first `--db` run against the seeded crawl-shape DB exits 0 (C2)\ntests/tmp/test_34_video_channel_name_wrong_instance_phase4.py:58 - `re.findall(r\"channel names repaired rows=(\\d+)\", stderr)` is exactly [\"3\"]: one log line, carrying the changed count (C2)\ntests/tmp/test_34_video_channel_name_wrong_instance_phase4.py:60 - the DB then reads v1, v2 and v7 as their own channel's name, with v3 to v6 unchanged, so the 3 that was logged really is the number of rows changed (C2)\ntests/tmp/test_34_video_channel_name_wrong_instance_phase4.py:63 - the second `--db` run exits 0 (C2)\ntests/tmp/test_34_video_channel_name_wrong_instance_phase4.py:64 - the second run's log is exactly [\"0\"], which rules out a hard-coded or cumulative count (C2)\ntests/tmp/test_34_video_channel_name_wrong_instance_phase4.py:65 - the second run leaves the repaired names as they were (C2)\nRed run observed: against the current script, which has no CLI, the test fails at line 41 because the bare invocation exits 0 and not 2.\n</assertions>\n\n<probes>\nProbe file: tests/tmp/probe_34_phase4_cli.py. Command: ValidateTests [\"tests/tmp/probe_34_phase4_cli.py\", \"-s\"]. Output:\nBARE current 0 '' '' - with the current script (no main), a bare invocation exits 0 and prints nothing. This is the wrong-implementation value for C1.\nWITHDB current 0 '' '' - a `--db` run exits 0 with empty stderr, so the log regex finds nothing. This is the wrong-implementation value for C2.\nARGPARSE required 2 'usage: -c [-h] --db DB\\n-c: error: the following arguments are required: --db\\n' - argparse's exit code and message when `--db` is required and missing.\nLOGGING '' 'INFO channel names repaired rows=3\\n' - `logging.basicConfig` in the style of the sibling jobs writes to stderr, not stdout.\ninproc first 3 second 0 - `repair_channel_names` on the same inline crawl-shape seed changes 3 rows, then 0.\nnames [('v1','Alphachan'),('v2','Betachan'),('v3','Betachan'),('v4','Stalename'),('v5','Stalename'),('v6','Orphanname'),('v7','Alphachan')] - the names after repair.\nThe probe file tests/tmp/probe_34_phase4_cli.py is still on disk: none of my tools can delete a file. It needs removing.\n</probes>\n\n<unassertable>\nnone\n</unassertable>",
    "self_check:tests/tmp/test_34_video_channel_name_wrong_instance_phase4.py": "<rows>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_34_video_channel_name_wrong_instance_phase4.py:41 \u2014 the bare invocation `[sys.executable, REPAIR_JOB]` has returncode == 2; lines 42 and 43 back it: stderr contains argparse's \"the following arguments are required: --db\", and no `channel names repaired rows=N` line is logged</assertion>\n<expected>returncode 2, and stderr reads `usage: ... --db PATH\\n...: error: the following arguments are required: --db\\n`. Observed by probe: a parser built with CompactHelpFormatter and `--db required=True, metavar=\"PATH\"` exits 2 with exactly that message. No repair line is logged.</expected>\n<wrong_implementation>The script as it stands, with no CLI entry point: exit 0 and empty stdout and stderr (observed, and this is today's red at :41). A `--db` that has a default, as its neighbours do: exit 0 and a repair of the default database logged, so :41 and :43 fail. An exit 2 caused by anything other than the missing `--db` (for example a crash from a bad import) fails :42.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_34_video_channel_name_wrong_instance_phase4.py:58 and :64 \u2014 `re.findall(r\"channel names repaired rows=(\\d+)\", stderr)` is exactly [\"3\"] on the first `--db` run and exactly [\"0\"] on the second. :60 ties the 3 to the rows that actually changed (v1, v2 and v7). :57 and :63 require exit 0.</assertion>\n<expected>First run: [\"3\"] and the names become {v1: Alphachan, v2: Betachan, v3: Betachan, v4: Stalename, v5: Stalename, v6: Orphanname, v7: Alphachan}. Second run: [\"0\"] with the names unchanged. Observed by probe on this exact inline seed: `repair_channel_names` returned 3, then 0, and left those names. A `logging.basicConfig(level=INFO, format=\"%(levelname)s %(message)s\")` line was observed on stderr as `INFO channel names repaired rows=3`.</expected>\n<wrong_implementation>A `--db` run that repairs but logs nothing, or prints to stdout: [] at :58. The script today exits 0 with empty stderr (observed). A hard-coded or cumulative count: [\"3\"] at :64. Logging the matched or total rows instead of the changed ones: [\"4\"] (with v3) or [\"7\"] at :58. A CLI that logs 3 but never calls the repair or never commits: the names at :60 stay as STORED.</wrong_implementation>\n</row>\n</rows>\n\n<answers>\nI made no rewrites. Every answer from 1 to 10 is \"no defect\", and each is backed by the runs below.\n\n1. **Whole claim \u2014 yes, every clause and docstring line is tested.**\n   - C1: :41 checks the exit code is 2, :42 checks the argparse required-`--db` message, and :43 checks that no repair line is logged.\n   - C2: :57 and :58 check exit 0 and exactly [\"3\"]. :60 checks the database now reads the REPAIRED names. :63 to :65 check the second run gives exit 0, exactly [\"0\"], and unchanged names.\n   - Every line of the docstring has a matching assertion.\n\n2. **Absence only \u2014 no.** The only negative assertion is :43 (no rows= line on the bare run). The assertions just before it arm it: :41 (exit 2) and :42 (the argparse message) prove the argument-parsing path actually ran. On the positive side, :58 proves the same regex does match once the job has a database.\n\n3. **Echoed literal \u2014 no.** REPAIRED, \"3\" and \"0\" are written-out literals, not computed the way the job computes them. The job does the transformation in a subprocess, and the test only reads the result back. Deleting `logging.info(\"channel names repaired rows=%d\", changed)` from main turns :58 red. Deleting `parser.add_argument(\"--db\", required=True, ...)` turns :41 red.\n\n4. **One value \u2014 no.** The count is read at two inputs (3 on a dirty database, 0 on an already-repaired one). The names are read across seven rows covering foreign, correct, NULL-stored, empty-display, NULL-display and orphan-channel cases. The log count is checked against the database state, which is a separate source.\n\n5. **The double \u2014 no.** There are no doubles. The real script runs through `sys.executable` against a real SQLite file built from the real `engine/crawler/schema.sql`.\n\n6. **It collects \u2014 yes.** The imports are all stdlib (re, sqlite3, subprocess, sys, pathlib). REPAIR_JOB and CRAWL_SCHEMA exist (Glob and Read confirmed). The columns used in the INSERTs all exist in schema.sql: channels.channel_id, instance_domain, display_name; videos.video_id, instance_domain, channel_id, channel_name, title, description, last_checked_at. The real run printed \"collected 1 item\", which matches the one test written. The `--collect-only` summary I was handed says \"no tests\", but the actual run collected and executed the test.\n\n7. **Observed, not predicted \u2014 yes, the expected values come from runs.** I re-ran `ValidateTests [\"tests/tmp/probe_34_phase4_cli.py\", \"-s\"]` this turn, and it printed:\n   - `BARE current 0 '' ''`\n   - `WITHDB current 0 '' ''`\n   - `ARGPARSE required 2 '...error: the following arguments are required: --db\\n'`\n   - `LOGGING '' 'INFO channel names repaired rows=3\\n'` (the log goes to stderr, not stdout)\n   - `inproc first 3 second 0`\n   - `names [('v1','Alphachan'),('v2','Betachan'),('v3','Betachan'),('v4','Stalename'),('v5','Stalename'),('v6','Orphanname'),('v7','Alphachan')]`\n\n   That probe uses the test's exact seed, including the `?1` binding. I also ran a new probe, `ValidateTests [\"tests/tmp/test_probe_34_phase4_selfcheck.py\", \"-s\"]`, which checks the planned formatter and metavar. It printed `COMPACT 2 '' 'usage: -c [-h] --db PATH\\n-c: error: the following arguments are required: --db\\n'`, so CompactHelpFormatter does not change the substring asserted at :42.\n\n   Both probe files are still in `tests/tmp/`, along with the earlier ones: `probe_34_phase4_cli.py`, `probe_34_phase3_impl.py`, `probe_34_fts_rowcount.py`, `test_probe_34_phase3.py`, `probe_repair_rowcount.py`, `probe_34_phase2_seed.py`, `test_probe_34_phase2.py`, `probe_34_urls.py`, `test_probe_34_urls.py` and `probe_channel_names.py`. None of my tools can delete files, so they need removing.\n\n8. **Red, not green \u2014 yes, it is red.** `ValidateTests [\"tests/tmp/test_34_video_channel_name_wrong_instance_phase4.py\"]` gave `[exit status 1]`: \"1 failed\" / \"FAILED tests/tmp/test_34_video_channel_name_wrong_instance_phase4.py::test_cli_requires_db_and_logs_changed_count\".\n\n9. **Red for the right reason \u2014 yes.** The failure is the C1 clause assertion at line 41, not a control assertion: `assert bare.returncode == 2` failed with `assert 0 == 2 ... CompletedProcess(args=[.../python3, .../engine/server/db/jobs/repair-video-channel-names.py], returncode=0, stdout='', stderr='')`. The script exists and ran, so the path and interpreter are fine. It exits 0 because it has no argparse entry point yet, which is exactly what this phase builds. The run stops at :41, so the C2 assertions were not reached in this run. Their wrong-implementation value was observed separately: `WITHDB current 0 '' ''` means :57 passes and :58 would fail with [] != [\"3\"]. The seed they depend on was observed to land and repair as expected (see answer 7).\n\n10. **Observed expected output \u2014 the rows match the runs.**\n   - C1: expected is exit 2 with the required-`--db` message. The formatter probe showed exactly that, and today's red shows 0 / empty, which is what the row gives as the current wrong value.\n   - C2: expected is [\"3\"] then [\"0\"] with the REPAIRED names. The in-process probe on the same seed showed 3, 0 and those exact names, and the logging probe showed the line on stderr in the regex's shape.\n\n   No run contradicted a row.\n</answers>\n\n<exemptions>\nnone\n</exemptions>",
    "step_7_implement:4": "<changes>\n### `engine/server/db/jobs/repair-video-channel-names.py`\n- Added a command line that follows `recompute-popularity.py` and `sync-whitelist.py`. It appends `engine/server` to `sys.path` and imports `CompactHelpFormatter` from `scripts.cli_format`.\n- Added `main()`, called under an `if __name__ == \"__main__\"` guard. It uses argparse with `CompactHelpFormatter` and a single `--db PATH` argument that is required and has no default. The neighbouring jobs default to the shared `whitelist.db`, and a migration run with no arguments must never hit that by accident.\n- Logging is set up with `logging.basicConfig(level=logging.INFO, format=\"%(levelname)s %(message)s\")`.\n- A `--db` path that is not an existing file is rejected with `parser.error(\"database not found: ...\")`, which exits 2. Without this check, `sqlite3.connect` would quietly create an empty file and then fail on the missing tables.\n- After the path check, `main()` opens the connection, calls the existing `repair_channel_names(conn)`, closes the connection in `finally`, and logs `channel names repaired rows=%d`.\n- `repair_channel_names`, the SQL and the FTS handling are unchanged.\n\n### `tests/active/test_channel_names.py`\n- Not touched. It does not exist in the worktree yet, and this phase's checkpoint lives in `tests/tmp/`. I take the EDITED entry to mean the checkpoint gets promoted there, which the workflow handles. Phase 3 read it the same way.\n</changes>\n\n<inner_tests>\nnone\n</inner_tests>\n\n<unanticipated>\ntests/tmp/probe_34_phase4_impl.py - a throwaway probe. It checked that the edited module still loads in-process through `importlib` (phases 2 and 3 load it that way) now that it changes `sys.path` and imports `scripts.cli_format`. It also checked the four CLI cases. A bare run exits 2 with `the following arguments are required: --db`. A missing `--db` path exits 2 with `database not found` and creates no file. The seeded crawl DB logs `INFO channel names repaired rows=3`, and a second run logs `rows=0`. I have no delete tool, so please remove it. `tests/tmp/probe_34_phase4_cli.py`, left over from authoring the checkpoint, is still there too and can go with it.\n</unanticipated>\n\n<awaiting_operator>\nnone\n</awaiting_operator>",
    "step_8_i1_refactor": "<refactors>\nnone\n</refactors>\n\n<left_out>\nengine/crawler/src/videos-worker.ts and dist/videos-worker.js: the four copies of the per-host error-classification catch block in processTagInstance/processCommentsInstance, the three identical groupByInstance* functions, the three identical *WorkerLoop functions and the unused TAGS_CONCURRENCY constant were all there before this build and are outside the lines it changed. Folding them together would grow the build past what was approved, so they belong in their own issue.\nengine/crawler/dist/videos-worker.js: I made no source edit, because every edit to src has to be mirrored in the dist by hand. I have no shell to run `npm run build`, so I could not confirm that tsc output would match. I checked by grep that src and dist call channelMetaKey at the same two sites and define the same helper.\nengine/server/db/jobs/repair-video-channel-names.py: `int(changed)` wraps a `rowcount` that is already an int. Removing the wrapper would be cosmetic, and no probe run backs it, so I left the file exactly as it passed Phases 2\u20134.\ntests/tmp: the leftover probe files (probe_34_phase2_seed.py, probe_34_phase3_impl.py, probe_34_phase4_impl.py, probe_34_phase4_cli.py, probe_34_fts_rowcount.py, probe_34_urls.py, test_probe_34_phase2.py, test_probe_34_phase3.py, test_probe_34_phase4_selfcheck.py, test_probe_34_urls.py) are not part of any phase and need deleting. I have no delete tool. The four test_probe_* files will be collected if tests/tmp is ever run as a directory.\ntests/active/test_channel_names.py: it still does not exist. The gating checkpoints are only in tests/tmp/test_34_video_channel_name_wrong_instance_phase1\u20134.py, and moving them to the permanent location is the workflow's job, not this pass's.\nStep prompt: the \"What the pass is measured against\" section arrived as a literal `{rat_tail_rules}` placeholder, so I checked the pass against the role's rat-tail rule instead. The one simplification this build added (the executescript commit in repair_channel_names) already carries a rat-tail comment naming its limit and upgrade path.\n</left_out>\n\n<needs_fresh_red>\nnone\n</needs_fresh_red>\n\n<observation>\nThis build's code is already minimal and matches the style of the files it landed in, so I made no refactors: the channelMetaKey change is the same in src and dist (checked by grep) and the repair job needs no restructuring.\n</observation>",
    "step_9_triage": "<docs>\n<doc path=\"DATA_BUILD.md\" update=\"yes\">\nThe file documents no way to correct `videos.channel_name` in existing databases, and `engine/server/db/jobs/repair-video-channel-names.py` now exists for that. Add a section between \"## 2) Filter to JoinPeerTube whitelist\" (ends line 158) and \"## 3) Build embeddings\", written as current state, with no \"previously\" and no bug history beyond a one-line reason. The reason: rows written before the crawler keyed channel metadata by host plus id hold the display name of a same-id channel on another instance.\n\nThe section should say:\n- The repair is a migration of shared databases. Run it on main after merge only, never from a worktree.\n- Run it outside an updater cycle, with the Engine idle or stopped. On `whitelist.db` it drops the FTS triggers, updates, recreates them and rebuilds `videos_fts`, and the rebuild holds the write lock.\n- The order:\n  1. Merge.\n  2. `python3 engine/server/db/jobs/repair-video-channel-names.py --db engine/crawler/data/crawl.db`.\n  3. The same command with `--db` on every `whitelist.db` copy, prod included, because `merge_rules.json` merges `videos` INSERT_ONLY and the updater never corrects existing prod rows.\n  4. Operator follow-up: `build-video-embeddings.py --db-path engine/server/db/whitelist.db --force`, then `build-ann-index.py` and `precompute-similar-ann.py` with the flags this file already documents in sections 4 and 5. Schedule it with the stable-ANN-ids cutover so the index is rebuilt once. Cite `docs/project/issues/08-stable-ann-ids.md` or \"plan 17\" without a path, because `docs/project/plans/17-stable-ann-ids.md` does not exist.\n\nDescribe what landed:\n- `--db PATH` is required and has no default.\n- A path that does not exist is rejected with exit 2 (\"database not found\").\n- It logs `channel names repaired rows=N`. It is idempotent: a second run logs `rows=0`.\n- It only changes rows whose own `(channel_id, instance_domain)` channel has a non-empty `display_name` that differs from the stored name, and it never writes `channels`.\n- On a DB with `videos_fts` it rebuilds the index on every run and fails with a RuntimeError if the `videos_fts` count differs from `videos`. A failed rebuild is recovered by re-running the job, because the update is already committed.\n- On `crawl.db` (no FTS) it skips the index steps.\n- It loads `sync-whitelist.py`, which parses `engine/crawler/schema.sql`, on the FTS path.\n\nLine 30 points at `engine/server/db/jobs/UPDATER_WORKER.md`, but the file is at `engine/server/db/jobs/docs/UPDATER_WORKER.md`. This broken reference was already there; fix it only if this edit touches that line.\n</doc>\n<doc path=\"docs/project/issues/34-video-channel-name-wrong-instance.md\" update=\"yes\">\nThe build delivered the issue, so its record is now wrong:\n- `Status: bug, ready-for-agent` (line 3) becomes `Status: bug, complete`.\n- Tick the acceptance criteria (lines 77-83).\n- Move the file to `docs/project/issues/archive/` per `docs/project/triage-labels.md`.\n\nRecord these points:\n- Still owed by the operator on main: `repair-video-channel-names.py` on `crawl.db` and on every `whitelist.db` copy, prod included, then the re-embed, ANN rebuild and similarity precompute.\n- The writer fix landed in both `videos-worker.ts` and the committed `dist/videos-worker.js`. The dist was edited by hand without `npm run build`, so a real `npm run build` should be run and the dist diff confirmed before or at merge.\n\nLine 45 already says the crawl slug and `channel_url` came out right. Make the correction precise: the slug comes from the per-host progress row, so only `displayName` and the `channelUrl` fallback were affected.\n\nLine 54 cites `docs/project/plans/17-stable-ann-ids.md`, which does not exist. Point it at `docs/project/issues/08-stable-ann-ids.md`, or name \"plan 17\" without a path.\n\nLine 19 (\"Cards: ... builds wrong channel links\") is contradicted by the line-49 finding (effectively no card impact). Reconcile it so the archived record does not claim a card fault.\n</doc>\n<doc path=\"engine/server/db/jobs/docs/UPDATER_WORKER.md\" update=\"no\">\nIt never mentions `channel_name`, the repair, or `INSERT_ONLY` by name. Its claims (line 71: prod gets merged changes according to `merge_rules.json`; line 88: the worker stops the Engine around the merge) are still true, because the build changed no updater, merge or rule behaviour. The operational guidance (INSERT_ONLY means every prod `whitelist.db` must be repaired directly, and no repair during an updater cycle) goes in the new DATA_BUILD.md section, so the optional note would duplicate it.\n</doc>\n<doc path=\"docs/project/issues/plan.md\" update=\"no\">\nIt is a sequencing plan. Its lines on issue 34 (line 62: the repair runs on main after the merge; line 150: migrations run on main after merge) are still accurate descriptions of the intended order. It says nothing about the writer or the repair that the build made false. Issue status is tracked in the issue file.\n</doc>\n<doc path=\"CONTEXT.md\" update=\"no\">\nThe glossary's only channel-related term is **Block** (`instance_domain` + `channel_id`), which the build does not touch. It defines no term for `channel_name`, the crawler's channel metadata, or data repairs, and the build introduces no new domain concept that needs a glossary entry.\n</doc>\n</docs>\n\n<adr_conflicts>\nnone\n</adr_conflicts>",
    "step_9_i2_update:DATA_BUILD.md": "<changes>\nAdded a \"Repair video channel names (one-time migration)\" subsection to `DATA_BUILD.md` at the end of step 2. It gives the repair command, the order to run it in, and how it behaves.\n\n- **Placement.** It sits under \"## 2) Filter to JoinPeerTube whitelist\" as a `###` subsection, just before \"## 3) Build embeddings\". The later sections keep their numbers, so \"step 3/4/5\" still points to the right place.\n- **Reason.** One line: channel ids are only unique per instance, so rows written before the crawl keyed metadata by host plus id can hold the name of a channel with the same id on another instance.\n- **When it may run.** It is a migration of shared databases: on main after merge only, never from a worktree. It must run outside an updater cycle with the Engine idle or stopped, because on `whitelist.db` it drops the FTS triggers, runs the update, recreates the triggers and rebuilds `videos_fts`, and the rebuild holds the write lock.\n- **Order.**\n  1. Merge.\n  2. Run the repair on `engine/crawler/data/crawl.db`.\n  3. Run it on every copy of `whitelist.db`, prod included. `merge_rules.json` merges `videos` as `INSERT_ONLY`; I checked that in the file.\n  4. Operator follow-up: `build-video-embeddings.py --db-path engine/server/db/whitelist.db --force`, then `build-ann-index.py` and `precompute-similar-ann.py`. For their flags it points to steps 4 and 5 rather than repeating them. This is scheduled with the stable-ANN-ids cutover and cites `docs/project/issues/08-stable-ann-ids.md`, which exists; the plans path does not.\n- **Behaviour.** Each point was checked against `repair-video-channel-names.py`:\n  - `--db PATH` is required and has no default.\n  - A path that is not an existing file exits 2 with `database not found`.\n  - It only changes a row whose own channel exists with a non-empty `display_name` that differs from the stored name. It never writes `channels`.\n  - It logs `channel names repaired rows=N`, and a second run logs `rows=0`.\n  - On a database with `videos_fts` it rebuilds the index on every run and raises `RuntimeError` if the counts don't match. The update is already committed at that point, so the fix for a failed rebuild is to run it again.\n  - On `crawl.db` it skips the index steps.\n  - On the FTS path it loads `sync-whitelist.py`, which parses `engine/crawler/schema.sql` when it loads, so it has to run from a full checkout.\n- I did not change line 30, the broken `UPDATER_WORKER.md` reference; the real file is at `engine/server/db/jobs/docs/UPDATER_WORKER.md`. The instruction was to fix it only if this edit touched that line, and it didn't.\n</changes>\n\n<not_on_checklist>\nnone\n</not_on_checklist>",
    "step_9_i2_update:docs/project/issues/34-video-channel-name-wrong-instance.md": "<changes>\nIssue 34 is marked complete with a Delivered record, its wrong claims are corrected, and six of its seven criteria are ticked. **It is still in `docs/project/issues/`: please run `git mv docs/project/issues/34-video-channel-name-wrong-instance.md docs/project/issues/archive/`**, because I have no tool that can move or delete files.\n\n- **Status:** `Status: bug, complete`.\n- **Cards line under Impact:** it said the cards build wrong channel links. It now says there is no card fault in practice: the `channel_name` fallback builds a link only when `channel_url` is empty, and no row has an empty `channel_url`. This matches the triage finding.\n- **Root-cause bullet in Triage:** made precise against `videos-worker.ts`. The crawl slug comes from `item.channelName`, the per-host progress row, before the map (line 440). `channel_url` comes from the payload's `channel.url` first, so `meta.channelUrl` is only a fallback (line 671). So only `displayName` and the `channelUrl` fallback were affected.\n- **Plan 17 link:** the path to `docs/project/plans/17-stable-ann-ids.md`, which does not exist, is replaced by \"Plan 17 (stable ANN ids, issue `08-stable-ann-ids.md`)\".\n- **New \"Delivered\" comment**, in the same form as archived issue 06:\n  - The writer fix: `channelMetaKey(host, channelId)`, checked in both src (lines 165, 289, 299) and dist (lines 41, 126, 134).\n  - The repair job, pointing at the `DATA_BUILD.md` section \"Repair video channel names (one-time migration)\" for behaviour and run order rather than repeating them.\n  - Where the gating tests are now (`tests/tmp/...phase1\u20134.py`), and that the harvest will move them to `tests/active/test_channel_names.py`.\n- **\"Still owed on main\" list** in that comment:\n  - Run a real `npm run build` and confirm the dist diff. The dist was edited by hand, and production runs the dist.\n  - The operator runs the repair on `crawl.db` and on every `whitelist.db` copy, prod included, then the re-embed, ANN rebuild and similarity precompute.\n  - The active suite has not been run against the finished build.\n- **Acceptance criteria:** six ticked. \"The existing active suite stays green\" is left unticked on purpose. Neither the phase reports nor the plan record show a suite run after the build, and I only tick what has evidence. It can be ticked once `validate_tests.py` passes.\n</changes>\n\n<not_on_checklist>\nnone\n</not_on_checklist>"
  },
  "requirements": "### Purpose\n\nEvery row in `videos` must carry its own channel's display name in `channel_name`. Today about 74% of rows in both `engine/crawler/data/crawl.db` and `whitelist.db` hold the display name of the channel with the same numeric `channel_id` on another instance. PeerTube channel ids are small per-instance integers, and 49,200 of them repeat across instances. Because of the wrong names, a channel-name search (`videos_fts` indexes `channel_name`) matches another channel's videos, and about 74% of video embeddings carry a foreign channel name (`build-video-embeddings.py` appends `channel: <channel_name>`). The `channels` table holds the correct `display_name` for every `(channel_id, instance_domain)`. Card links are effectively unaffected, because `channel_url` is never empty.\n\n### Root cause (established by triage, confirmed in the tree)\n\nIn `engine/crawler/src/videos-worker.ts`, `crawlVideos` builds `channelMeta` as `Map<string, ChannelMeta>` keyed by `channel.channel_id` alone (lines ~163-172). It is built from `store.listChannelsWithVideos(1, hosts)`, which returns channels from every crawled host. `processInstance` looks it up with `channelMeta.get(item.channelId)` (line ~289), again without the host. When an id repeats across hosts, the last listed host wins. That entry's `displayName` then becomes the video row's `channel_name` (resolution around lines 660-662, row written by the upsert in `engine/crawler/src/db.ts`). `sync-whitelist.py` copies `crawl.db` into `whitelist.db`, so both databases carry the fault. The updater's `videos` merge is `INSERT_ONLY`, so it never corrects existing prod rows.\n\n### Requirement 1: Writer fix\n\n- The video crawl's channel-metadata map is keyed on host plus channel id, and every lookup uses both.\n- The host part of the key must be in the same form on both sides. The map is built from `channels.instance_domain`. The lookup happens in `processInstance`, which uses `host.toLowerCase()` (`normalizedHost`), while the work item carries `instanceDomain`. The key must match for every channel whose metadata exists, so a normalisation mismatch must not silently drop metadata.\n- The channel-name precedence stays as it is: first the crawl channel list's `displayName` (now the correct host's), then the video payload's own `channel.displayName` / `display_name`.\n- The crawl slug (`channelSlug`) and `channelUrl` taken from the meta are resolved by the same host-aware key.\n- Nothing else in the crawler changes. Issue 27 (seed instance mode) is out of scope.\n\n### Requirement 2: Repair job\n\n- A new operator-runnable Python job in `engine/server/db/jobs/`, following the existing jobs' CLI style (argparse, a `--db <path>` argument, the same docstring and logging conventions as its neighbours, e.g. `sync-whitelist.py`, `recompute-popularity.py`).\n- For every `videos` row, it sets `channel_name` to the `display_name` of the `channels` row with the same `(channel_id, instance_domain)`. It does so only where that `display_name` is non-NULL and non-empty and differs from the current `channel_name`. Rows that are already correct, and rows whose channel has an empty or NULL `display_name` (or no channel row), are left untouched.\n- It reports the number of rows changed. It is idempotent: a second run changes 0 rows and reports 0.\n- It works on both database shapes: the crawler's `crawl.db` schema, which has no `videos_fts` (the crawler source defines no FTS table or triggers), and the Engine's `whitelist.db` schema.\n- It does not touch the `channels` table.\n\n### Requirement 3: Search index\n\n- When the target database has `videos_fts` (the `whitelist.db` shape), the repair leaves the index reflecting the corrected names. It reuses the existing helpers in `engine/server/db/jobs/sync-whitelist.py` (`drop_videos_fts_triggers`, `create_videos_fts_triggers`, `rebuild_videos_fts`) rather than writing new FTS code. Those helpers follow the file's bulk pattern: drop the triggers, run the bulk update, recreate the triggers, rebuild. `sync-whitelist.py` has a hyphenated filename, so it cannot be imported by the normal module syntax; reuse it the way other code in the repo already loads hyphenated job modules, or by an equivalent means.\n- After the rebuild, the `videos_fts` row count must equal the `videos` row count. The job fails loudly if they differ, matching the check `sync-whitelist.py` already makes.\n- Result: an FTS search for a channel's own display name finds that channel's videos. A search for another instance's same-id channel name no longer finds them through `channel_name`.\n- When `videos_fts` is absent (`crawl.db`), the job skips the FTS steps without error.\n\n### Requirement 4: Tests (in `tests/active`)\n\n- A crawl fixture with two hosts that share a `channel_id` but have different channel display names. It asserts that each host's videos are written with their own channel's name. This test must fail on today's code. Crawler tests in this repo run the compiled crawler under node (see `tests/active/test_host_normalisation.py`, which runs `engine/crawler/dist/*.js`, and fails rather than skips when node or the dist is missing or stale). The new test follows that convention.\n- A repair test on a fixture DB with mismatched `channel_name` values. It checks that each mismatched row is set to its own channel's `display_name`, that already-correct rows and rows whose channel has an empty `display_name` are untouched, and that the reported changed count is correct. A second run must change 0 rows.\n- The repair test runs on both schemas: a `crawl.db`-shaped fixture (no FTS) and a `whitelist.db`-shaped fixture (with `videos_fts` and its triggers, created via `sync-whitelist.py`'s `ensure_content_schema` or equivalent).\n- An FTS test on the `whitelist.db` fixture, after the repair: a query for the correct channel name returns that channel's videos, a query for the other instance's name does not return them, and `videos_fts` has as many rows as `videos`.\n- All fixtures are temporary. No test touches the real `crawl.db` or `whitelist.db`.\n\n### Requirement 5: Runbook\n\n- `DATA_BUILD.md` (which already documents the `crawl.db` and `sync-whitelist.py` steps) gains a section naming the repair command and the order to follow:\n  1. Merge to main.\n  2. From main, never from a worktree, run the repair against `engine/crawler/data/crawl.db`, then against `whitelist.db`. That means every copy of `whitelist.db`, including the prod/server database, because the updater's `INSERT_ONLY` merge will never correct existing prod rows.\n  3. The operator follow-up: `build-video-embeddings.py --force` on `whitelist.db`, then `build-ann-index.py`, then `precompute-similar-ann.py`, scheduled with plan 17's (`docs/project/plans/17-stable-ann-ids.md`) cutover so the index is rebuilt only once.\n- The runbook states that the repair is a migration of shared databases and runs on main after merge only.\n\n### Constraints\n\n- The agent must not run the repair against the real `crawl.db` or `whitelist.db`.\n- The existing active suite (`tests/active`) stays green, including `test_host_normalisation.py`. Pre-build baseline: the suite exits with code 0.\n- Smallest change that works: stdlib only for the Python job, no new dependencies, no new abstractions.\n\n### Out of scope\n\n- Re-embedding, the ANN rebuild and the similarity precompute (operator follow-up only).\n- Changing the embedding text in `build-video-embeddings.py`.\n- The `channels` table, and the Engine's `/api/video` write-back.\n- Issue 27 (crawler seed instance mode).\n- `client/frontend/src/components/video-card.ts`: no change.\n\n### Acceptance criteria\n\n- [ ] A two-host shared-`channel_id` crawl fixture writes each host's videos with their own channel's name. The test fails on today's code.\n- [ ] The repair corrects mismatched rows, leaves correct rows and empty-`display_name` rows untouched, reports the changed count, and a second run changes 0.\n- [ ] After the repair on a `whitelist.db` fixture, an FTS query for the correct name returns the channel's videos, a query for the other instance's name does not, and the `videos_fts` count equals the `videos` count.\n- [ ] The repair runs on both the `crawl.db` and `whitelist.db` schemas.\n- [ ] The active suite stays green, including the host-normalisation tests.\n- [ ] `DATA_BUILD.md` states: merge, then the repair from main on `crawl.db` and on every `whitelist.db` (prod included), then the operator re-embed step.\n- [ ] The repair is never run against the real databases by the agent.",
  "approved": [
    "1",
    "2",
    "3",
    "5",
    "6",
    "9"
  ],
  "initial_solution": "### Approach\n\nFour changes, each tied to a requirement: a keying fix in one function of the crawler, one new Python job, one new test module, and one new runbook section. I read the files each change touches: `videos-worker.ts` (map build, `processInstance`, `processChannel`, `toVideoRow`), `db.ts` (`listChannelsWithVideos`, `prepareVideoProgress`, `listVideoWorkItems`, `listInstances`, the upsert), `http.ts`, `host-filters.ts`, `sync-whitelist.py` (FTS helpers, `ensure_content_schema`, `rebuild_content_tables` and its count check), `recompute-popularity.py`, `test_host_normalisation.py` and `DATA_BUILD.md`.\n\n**Requirement 1 (writer fix).** In `crawlVideos`, the `channelMeta` map gets a composite string key built from the host and the channel id, for example `host/channel_id`. A `/` cannot appear in a normalised host, and a host can carry a `:port`, so the separator cannot collide with a real value. The value type stays `ChannelMeta` and no new type is added. The host part is lowercased on both sides:\n- When the map is built, from `channel.instance_domain`.\n- At the lookup in `processInstance`, which already holds `normalizedHost = host.toLowerCase()`, together with `item.channelId`.\n\nThis follows the host through the code. `processInstance`'s `host` is the grouping key `item.instanceDomain`. That value comes from `video_crawl_progress.instance_domain`, which `prepareVideoProgress` copied verbatim from `channels.instance_domain`. So both sides start from the same column, and applying the same lowercasing to both means a mixed-case stored domain still matches. No metadata can be dropped by a normalisation mismatch.\n\n`processChannel` and `toVideoRow` are unchanged. They already take `meta.channelSlug`, `meta.displayName` and `meta.channelUrl` from the single `meta` handed to them, so all three now come from the correct host's entry. The precedence (crawl list `displayName` first, then the payload's `channel.displayName` / `display_name`) is untouched. Nothing else in the crawler changes. Because `engine/crawler/dist/` is committed, the build is re-run and the regenerated `dist/videos-worker.js` is committed with the source; only that dist file should differ.\n\n**Requirement 2 (repair job).** A new file, `engine/server/db/jobs/repair-video-channel-names.py`, laid out like its neighbours:\n- Shebang, a one-paragraph module docstring, and the same `script_dir` / `sys.path` preamble.\n- argparse with `CompactHelpFormatter` and `--db PATH`.\n- `logging.basicConfig` at INFO and a `main()` behind `if __name__ == \"__main__\"`.\n\nThe repair is one set-based UPDATE on `videos`. It sets `channel_name` from a correlated subquery on `channels` matched by `(channel_id, instance_domain)`, which is the `channels` primary key, so each lookup is indexed. The WHERE clause requires three things of the channel row:\n- it exists;\n- its `display_name` is non-NULL and not `''`;\n- its `display_name` IS NOT the current `channel_name`. `IS NOT` rather than `!=`, so a row whose `channel_name` is NULL is also corrected.\n\nThe changed count is the UPDATE cursor's `rowcount`, logged in the neighbours' `key=value` style. Rows that are already correct, rows with an empty or NULL display name, and rows with no channel row never match, so a second run changes 0 rows and reports 0. `channels` is only read.\n\n`--db` is **required**, with no default. Neighbours such as `recompute-popularity.py` default to the crawl DB path, but this job is a migration that is run deliberately against several named databases, and a default would let a bare invocation silently hit one of them.\n\n**Requirement 3 (search index).** The job checks `sqlite_master` for a `videos_fts` table.\n- If it is present, the job follows `rebuild_content_tables`' order: `drop_videos_fts_triggers`, the UPDATE, `create_videos_fts_triggers`, then `rebuild_videos_fts`. It then compares the returned count with `COUNT(*)` on `videos` and raises `RuntimeError` with the same wording `sync-whitelist.py` uses if they differ.\n- If it is absent (the `crawl.db` shape), only the UPDATE and commit run, and no FTS helper is called.\n\nThe helpers are reached by loading `sync-whitelist.py` with `importlib.util.spec_from_file_location` from the job's own directory. This is the loader `test_host_normalisation.py` and `test_similar.py` already use. Loading only runs that module's imports and its `sys.path` setup, because its `main()` is guarded.\n\nWhen FTS is present, the rebuild and count check run on **every** invocation, even when 0 rows changed. See the first risk below for why.\n\n**Requirement 4 (tests).** One new module, `tests/active/test_channel_names.py`.\n\n- **Crawl test.** Follows `test_host_normalisation.py`'s convention: it fails, rather than skips, when node is missing, the dist is missing, or `dist/videos-worker.js` is older than `src/videos-worker.ts`, using the same git-or-mtime staleness rule and the same build hint.\n  - It starts two stdlib `ThreadingHTTPServer`s on 127.0.0.1 with ephemeral ports, so the two hosts are `127.0.0.1:P1` and `127.0.0.1:P2` and no DNS is involved. Each serves `/api/v1/video-channels/<slug>/videos` with its own videos, and the payloads carry no `channel.displayName`.\n  - It creates a temp `crawl.db` from `engine/crawler/schema.sql`. It inserts both hosts into `instances`, and one `channels` row per host with the same `channel_id`, different `display_name`s, and `videos_count >= 1`.\n  - It runs the compiled `crawlVideos` under node with `concurrency 1`, `maxRetries 0`, a short timeout, and resume, tags and comments off. With `maxRetries 0` the https attempt against the plain-HTTP server fails once and `fetchPage` falls back to http.\n  - It asserts that each host's `videos.channel_name` equals its own channel's `display_name`, and also checks `channel_url`.\n  - On today's code, one of the two hosts always gets the other's name, whichever order the rows come back in, so the test fails deterministically.\n- **Repair tests.** Parametrised over two temp fixtures: a `crawl.db` shape (`schema.sql`) and a `whitelist.db` shape (`ensure_content_schema` from the loaded `sync-whitelist.py`, which creates `videos_fts` and its triggers). Each fixture seeds:\n  - mismatched rows (a foreign same-id name);\n  - an already-correct row;\n  - a row whose channel has an empty `display_name`;\n  - a row whose channel has a NULL `display_name`.\n\n  The test runs the job's repair function and asserts the exact changed count, each row's resulting name, and that a second run returns 0. The job is loaded by the same importlib loader. A single subprocess run of the CLI against a temp DB also checks the logged count.\n- **FTS test.** On the whitelist fixture after repair: a MATCH on `channel_name` for the correct name returns that channel's videos, a MATCH for the other instance's same-id name does not return them, and `COUNT(*)` on `videos_fts` equals the count on `videos`.\n- Every DB is under `tmp_path`, and no test references a real DB path.\n\n**Requirement 5 (runbook).** A new `DATA_BUILD.md` section after step 2, titled as a one-off repair of `channel_name`. It explains in one line why the repair is needed, states that it is a migration of shared databases that runs on main after merge only (never from a worktree), and lists the order:\n1. Merge.\n2. Run `repair-video-channel-names.py --db engine/crawler/data/crawl.db`.\n3. Run it again with `--db` on every copy of `whitelist.db`, the prod/server database included, because the updater's `INSERT_ONLY` merge never corrects existing rows.\n4. Operator follow-up, timed with plan 17's cutover so the index is rebuilt once: `build-video-embeddings.py --force` on `whitelist.db`, then `build-ann-index.py`, then `precompute-similar-ann.py`.\n\nThe agent never runs the job against the real databases. It is exercised only inside the tests' temp fixtures.\n\n### Alternatives considered\n\n- **Nested `Map<host, Map<channelId, ChannelMeta>>` instead of a composite string key.** Rejected: more code at both the build and the lookup, for a collision risk the `/` separator already rules out.\n- **Keying on the raw `instance_domain` on both sides (`item.instanceDomain` at lookup) instead of lowercasing both.** Also correct, since both come from the same column. Rejected: `processInstance` already works in `normalizedHost` and the video rows are written under it, so lowercasing both sides keeps one host form throughout.\n- **Updating with the triggers left in place, letting `videos_fts_au` fix the index row by row.** This would be transactional and need no rebuild. Rejected: the requirement asks for the helpers' bulk pattern. It is also fragile, because the per-row `'delete'` reuses the stored old values and would corrupt an index that had already drifted, whereas `rebuild` recovers from drift.\n- **A Python row loop with `executemany`, as in `recompute-popularity.py`.** Rejected: one set-based UPDATE is shorter, gives the changed count directly, and is faster on millions of rows.\n- **`UPDATE \u2026 FROM`.** Rejected: it needs SQLite 3.33 or later, and a correlated subquery works on any SQLite the servers run.\n- **Copying the FTS SQL into the new job.** Rejected: the requirement asks for reuse, and a second copy of the trigger SQL would drift from the first.\n- **A shared helper module for loading hyphenated jobs.** Rejected: a new abstraction for three lines that the repo already inlines.\n\n### Risks, gotchas and limitations\n\n- **The repair is not a single transaction on the FTS path.** The reused helpers call `executescript`, which COMMITs any open transaction first. So the UPDATE commits when the triggers are recreated, before the rebuild. A crash in between leaves corrected names with a stale index, and a later count mismatch raises after the data is already committed. Mitigation: the rebuild and count check run on every invocation when FTS is present, so re-running the job restores the index even though it reports 0 changed rows.\n- **Cost and locking on prod.** The rebuild re-indexes all of `videos_fts` each run. On the prod `whitelist.db` this is a long write that blocks other writers, such as the updater merge. The runbook will tell operators to run it outside an updater cycle.\n- **Exact `instance_domain` join.** The repair matches `videos.instance_domain` to `channels.instance_domain` exactly, the same join `sync-whitelist.py` uses. The crawler writes video rows under the lowercased host, while `channels` keeps the stored spelling. A channel stored in mixed case would therefore not be repaired. Hosts are already lowercased by `normalizeHostToken` when they enter the crawl, so this should not occur, but the repair does not guard against it.\n- **What counts as \"empty\".** \"Empty `display_name`\" means `''`. Whitespace-only names are not specially handled; the channel crawler's `toBoundedString` trims names and turns blanks into NULL, so none are expected.\n- **Committed dist.** If `dist/videos-worker.js` is not rebuilt and committed with the source change, the new crawl test fails on staleness by design.\n- **Crawl test environment.** The test needs node, `engine/crawler/node_modules` (better-sqlite3) and a built dist, and fails with the build hint when any is missing, as `test_host_normalisation.py` does. It binds to loopback ephemeral ports only.\n- **Load-time imports.** Loading `sync-whitelist.py` executes its module-level imports (`scripts.cli_format`, `server_config`, `data.moderation`). The repair job therefore depends on the Engine's server tree being present, which is true everywhere these jobs already run.\n\n### Tradeoffs the operator is asked to accept\n\n- `--db` is required, unlike the neighbours' defaulted `--db`: a small inconsistency in CLI style, in exchange for never repairing a database by accident.\n- Every run with FTS present pays a full FTS rebuild, even when nothing changed. The cost is time, and the benefit is that a crashed run is fixed by simply running it again.\n- The FTS path is not atomic, because the settled helpers commit internally. Recovery is to re-run, not rollback.\n- Until the operator's re-embed, ANN rebuild and precompute are done, embeddings keep carrying the old foreign channel names. Search text is correct straight after the repair; semantic similarity is only corrected at the plan-17 cutover.",
  "conflicts": "none",
  "impacts": "\n<impacts>\n<impact path=\"engine/crawler/src/videos-worker.ts\" element=\"crawlVideos(): the channelMeta map build (lines 163-172)\">\n**What changes.** The map key changes from `channel.channel_id` to a composite string: `channel.instance_domain.toLowerCase()`, then `/`, then `channel.channel_id`. The value (`ChannelMeta`: `channelSlug`, `displayName`, `channelUrl`) and the type `Map<string, ChannelMeta>` do not change.\n\n**What depends on it.**\n- `channels` comes from `store.listChannelsWithVideos(1, hosts)` (db.ts:1265-1278), optionally sliced by `maxChannels`. That query returns rows from every crawled host and filters `channel_name IS NOT NULL`, which is why ids collide across hosts.\n- The map is passed unchanged through `workerLoop` (line 191) into `processInstance`.\n- The same `channels` array feeds `store.prepareVideoProgress(channels, ...)` (line 175), so every work item has a matching map entry under the raw `instance_domain`.\n\n**Regression risk: low.**\n- Two `channels` rows could differ only by the case of `instance_domain` while sharing a `channel_id`. Their lowercased keys would collide and the last one listed would win. That is the old bug in a much narrower form. Hosts are normalised to lowercase by `normalizeHostToken` on entry, so such rows are not expected. I did not check the real DB for them.\n- The key string must be built the same way here and at the lookup. A mismatch, for example lowercasing only one side or using a different separator, silently gives `meta === undefined`. The name then falls back to the payload's `channel.displayName`, which the new test's payloads deliberately omit, so the test would catch this.\n</impact>\n<impact path=\"engine/crawler/src/videos-worker.ts\" element=\"processInstance() lookup `channelMeta.get(item.channelId)` (line 289)\">\n**What changes.** The lookup becomes `channelMeta.get(`${normalizedHost}/${item.channelId}`)`, where `normalizedHost = host.toLowerCase()` (line 285) is already in scope.\n\n**What depends on it.**\n- `host` is the key of `grouped`, which `groupByInstance` (lines 707-715) builds from `item.instanceDomain`. That value comes from `video_crawl_progress.instance_domain` (`listVideoWorkItems`, db.ts:1399-1424), which `prepareVideoProgress` (db.ts:1328-1346) copied verbatim from `channels.instance_domain`. Both sides of the key therefore start from the same column, as the plan says.\n- `meta` is handed to `processChannel` (line 290).\n\n**Regression risk: low.** This is the one line that fixes the bug. `workerLoop` and the `channelMeta` parameter types in `workerLoop` (line 260) and `processInstance` (line 280) keep their signatures.\n</impact>\n<impact path=\"engine/crawler/src/videos-worker.ts\" element=\"processChannel() (lines 425-468): slug and meta use\">\n**What changes.** Nothing in the code. What `meta` holds changes.\n\n**Correction to the plan.** The plan says the slug \"now comes from the correct host's entry\". In fact `channelSlug = item.channelName ?? meta?.channelSlug` (line 433): the slug is taken first from the per-host progress row. `prepareVideoProgress` writes that row's `channel_name`, and `listChannelsWithVideos` only returns channels where it is non-NULL. The slug was therefore already correct, and `meta.channelSlug` is a dead fallback in practice. The fix really changes only `displayName` and `channelUrl`, both passed on at lines 450-451.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"engine/crawler/src/videos-worker.ts\" element=\"toVideoRow() channel name and URL resolution (lines 660-664)\">\n**What changes.** Nothing in the code.\n- `channelName = toBoundedString(channel.displayName) ?? toBoundedString(channelRef?.displayName ?? channelRef?.display_name)`. The precedence is unchanged, as required, and the first term now comes from the correct host.\n- `channelUrl = toHttpUrlOrNull(channelRef?.url) ?? toHttpUrlOrNull(channel.channelUrl)`. The payload's own `channel.url` comes FIRST here, so `meta.channelUrl` is only a fallback.\n\n**What depends on it.**\n- `upsertVideos` (db.ts:1453) writes the row.\n- The ON CONFLICT clause (db.ts:1169-1195) overwrites `channel_name` and `channel_url` on every re-crawl, so after the fix a fresh crawl of `crawl.db` corrects rows by itself.\n\n**Regression risk: low.**\n- **The test's `channel_url` check.** It only exercises the fix if the fixture payload has no `channel.url`. Otherwise the payload URL wins whatever key is used.\n- **The URL value.** The fixture's `channels.channel_url` must be an absolute http(s) URL, or `toHttpUrlOrNull` returns NULL.\n- **Trimming.** `toBoundedString` trims the name and caps it at 200 characters, so the fixture's display names should be short and untrimmed, or the test's equality check fails.\n</impact>\n<impact path=\"engine/crawler/src/videos-worker.ts\" element=\"fetchPage() https\u2192http fallback (lines 581-619) and buildChannelVideosUrl() (624-636), used by the new crawl test\">\n**What changes.** Nothing.\n\n**How the test reaches its fake servers.**\n- `crawlChannelVideos` starts with `protocol = \"https:\"`. Against a plain-HTTP `ThreadingHTTPServer`, Node's fetch fails the TLS handshake, typically with EPROTO or `ERR_SSL_WRONG_VERSION_NUMBER`. Those codes are not in `isNoNetworkError`'s list, so no curl fallback runs.\n- With `maxRetries: 0`, `fetchJsonWithRetry` throws after the first attempt (`attempt > maxRetries`). The catch then retries over `http:` with `maxRetries: Math.max(1, 0) = 1`, so the http leg gets one retry with a 1000 ms backoff on error.\n- The protocol is kept for later pages.\n- The URL path is `/api/v1/video-channels/<encodeURIComponent(slug)>/videos?start=0&count=50&sort=-publishedAt`. The fake server must match the path and ignore the query.\n- Pagination stops when `nextStart >= page.total`, or when `data.length < 50` if `total` is absent. The fixture should send `total` equal to its video count.\n\n**Regression risk: none to production.** For the test there is one flake path. If the https attempt ever fails with ECONNREFUSED or ETIMEDOUT, `fetchJsonWithRetry` calls `fetchViaCurl` (http.ts:73-78), then throws `NoNetworkError`. `processChannel` then records an error, and no rows are written. Binding to 127.0.0.1 and keeping the server alive for the whole run avoids this.\n</impact>\n<impact path=\"engine/crawler/dist/videos-worker.js\" element=\"compiled crawlVideos channelMeta build (lines 40-47) and processInstance lookup (line 126)\">\n**What changes.** It is regenerated by `npm run build` (`node node_modules/typescript/bin/tsc -p tsconfig.json`) and committed together with the source. The dist is tracked: the root `.gitignore` ignores only `node_modules`, `*.db` and `.un/`.\n\n**What depends on it.**\n- Production runs the dist, not the source. The updater runs `crawler_dist / \"videos-cli.js\"` (updater-worker.py:805, 954), and `npm run crawl:videos` and `scripts/run-dataset-build.sh` go through `dist/videos-cli.js`. So without the rebuild, the fix never reaches staging or prod crawls.\n- The new crawl test imports this file.\n\n**Regression risk: medium, for the build process.**\n- `tsc` recompiles all of `src/` into `dist/`. The plan says \"only that dist file should differ\", and that holds only if the other committed dist files are already in step with their sources. I compared only the `videos-worker` lines at issue, which currently match the source.\n- `tsconfig` emits no source maps or declarations, so no extra files appear.\n- The staleness rule compares the git commit times of `src/videos-worker.ts` and this file. If both are committed together, the times are equal and the dist is not stale.\n</impact>\n<impact path=\"engine/crawler/src/db.ts\" element=\"VideoStore: listInstances (1241), listChannelsWithVideos (1265-1278), prepareVideoProgress/pruneVideoProgress (1328-1394), listVideoWorkItems (1399-1424), upsertStmt (1138-1196), constructor/applyBaseSchema (1131-1137, reads ../schema.sql at line 24)\">\n**What changes.** Nothing.\n\n**What depends on it.** The key-normalisation reasoning and the crawl test fixture.\n- **Instance match.** `listInstances` returns `instances.host` as stored. `listChannelsWithVideos` matches `instance_domain IN (hosts)` exactly, so the fixture's `instances.host` must equal `channels.instance_domain` byte for byte (`127.0.0.1:P1`).\n- **Required channel fields.** Each channel needs `videos_count >= 1` and a non-NULL `channel_name` (the slug).\n- **Constructor side effects.** The constructor sets `journal_mode = WAL`, so `-wal` and `-shm` files appear beside the temp DB. It also runs `applyBaseSchema` and migrations, so a DB created from `schema.sql` is already compatible.\n- **Module-level read.** `db.js` reads `../schema.sql` relative to itself at import (line 24), which resolves to `engine/crawler/schema.sql`.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"engine/crawler/src/videos-cli.ts\" element=\"crawlVideos option mapping (lines 87-107)\">\n**What changes.** Nothing.\n\n**What depends on it.** It is the reference for the full `VideoCrawlOptions` object the new test must build when it imports `crawlVideos` directly. The object has 18 keys:\n- `dbPath`\n- `excludeHostsFile: null`\n- `existingDbPath: null`\n- `concurrency`\n- `timeoutMs`\n- `maxRetries`\n- `newOnly: false`\n- `stopAfterFullPages: 0`\n- `sort: \"-publishedAt\"`\n- `maxInstances: 0`\n- `maxChannels: 0`\n- `maxVideosPages: 0`\n- `tagsOnly: false`\n- `updateTags: false`\n- `commentsOnly: false`\n- `hostDelayMs: 0`\n- `resume: false`\n- `errorsOnly: false`\n\nThe alternative is to run `dist/videos-cli.js --db ... --max-retries 0 --timeout N --concurrency 1`, which needs `commander` from `node_modules`.\n\n**Regression risk: none.** A missing option key is `undefined` in JS, so `sort: undefined` would still fall back to `-publishedAt` inside `buildChannelVideosUrl`.\n</impact>\n<impact path=\"engine/crawler/src/http.ts\" element=\"fetchJsonWithRetry() (55-133), isNoNetworkError() (37-53), fetchViaCurl() (138-161)\">\n**What changes.** Nothing.\n\n**What depends on it.** The crawl test's single https failure and its fall back to http. See the fetchPage entry.\n- `setDefaultResultOrder(\"ipv4first\")` runs at import. It is harmless for 127.0.0.1.\n- Node's fetch does not use `HTTP(S)_PROXY` by default, so a proxy environment should not reroute loopback requests.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"engine/crawler/src/host-filters.ts\" element=\"toBoundedString (48-56), toHttpUrlOrNull (68-78), normalizeHostToken (83-100)\">\n**What changes.** Nothing.\n\n**What depends on it.**\n- The name and URL sanitising in `toVideoRow`.\n- The plan's claim that hosts are lowercased when they enter the crawl. `normalizeHostToken` lowercases, and branch 4 keeps `:port`. That is why a `/` separator cannot collide with a stored host.\n\n**Regression risk: none.** `test_host_normalisation.py` pins this file's dist copy, and nothing here changes.\n</impact>\n<impact path=\"engine/crawler/schema.sql\" element=\"instances / channels / videos / video_crawl_progress tables\">\n**What changes.** Nothing.\n\n**What depends on it.**\n- The crawl.db-shape fixtures in the new test are created from it.\n- `sync-whitelist.py` parses its `instances`, `channels` and `videos` blocks at import (sync-whitelist.py:36, 92-96), and the repair job loads that module. So the repair job now depends on this file existing, even when run against `whitelist.db`.\n- `channels` has `PRIMARY KEY (channel_id, instance_domain)` (line 26), which makes the repair's correlated subquery an index lookup.\n- `videos.channel_id` is nullable (line 34). Rows with a NULL `channel_id` never match the repair.\n\n**Regression risk: low.** If the file moves, the repair job fails at load.\n</impact>\n<impact path=\"engine/server/db/jobs/repair-video-channel-names.py\" element=\"new job (whole module)\">\n**What changes.** A new file.\n\n**Layout, following its neighbours:**\n- Shebang, then a docstring.\n- The `script_dir` / `sys.path` preamble. `sync-whitelist.py:16-22` inserts both `engine/server` and `engine/server/api`. `recompute-popularity.py:10-11` appends `engine/server` and adds `api` lazily.\n- argparse with `CompactHelpFormatter` (`engine/server/scripts/cli_format.py`, which exists).\n- `logging.basicConfig(level=logging.INFO, ...)`. Note the neighbours' formats differ: `\"%(levelname)s: %(message)s\"` in sync-whitelist and `\"%(levelname)s %(message)s\"` in recompute-popularity.\n- A guarded `main()`.\n- `--db` is required, with `metavar=\"PATH\"`.\n\n**The repair.** One `UPDATE videos SET channel_name = (SELECT c.display_name FROM channels c WHERE c.channel_id = videos.channel_id AND c.instance_domain = videos.instance_domain) WHERE EXISTS (SELECT 1 FROM channels c WHERE <same join> AND c.display_name IS NOT NULL AND c.display_name <> '' AND c.display_name IS NOT videos.channel_name)`. The changed count is `cursor.rowcount`.\n\n**The FTS branch.**\n- It is taken when `sqlite_master` has a table named `videos_fts`, the same probe as `search.fts_available`.\n- It calls `drop_videos_fts_triggers`, then the UPDATE, `create_videos_fts_triggers`, `rebuild_videos_fts` and the count check.\n- The check raises `RuntimeError` with sync-whitelist's wording (lines 518-521).\n\n**Correction to the plan.** The plan says neighbours \"such as `recompute-popularity.py` default to the crawl DB path\". They do not. `server_config.DEFAULT_DB_PATH` is `\"engine/server/db/whitelist.db\"` (server_config.py:363), and recompute-popularity defaults to that path. So does sync-whitelist's `DEFAULT_SOURCE_DB_PATH`. A default here would silently hit the shared `whitelist.db`, which is an even stronger reason for `--db` to be required.\n\n**The loader is new in production code.** No file under `engine/` uses `importlib` today (grep: no matches). The `spec_from_file_location` precedent is in tests only (`test_host_normalisation.py:78-82`, `test_similar.py:72, 298`). This job is the first production module to load a sibling hyphenated job, which is acceptable but worth knowing.\n\n**Load-time dependencies of sync-whitelist.py.**\n- `scripts.cli_format`\n- `server_config`, whose only import is `os`\n- `data.moderation`, stdlib only\n- the parse of `engine/crawler/schema.sql`\n\nAll are stdlib-only, so the job stays stdlib-only.\n\n**Transactions.** `executescript` in the helpers COMMITs any pending implicit transaction.\n- **Order.** Triggers dropped (commit), then the UPDATE, which opens an implicit transaction. `create_videos_fts_triggers` commits the UPDATE and the new triggers. `rebuild_videos_fts` runs inside a new implicit transaction that the job must `commit()` explicitly, or it is rolled back on close.\n- **crawl.db path.** Also needs an explicit `commit()`.\n- **When `rowcount` must be read.** Before any `executescript`.\n\n**What depends on it.** The operator runbook and the new tests.\n\n**Regression risk: medium, operationally.** It rewrites shared databases. See the entries for `sync-whitelist.py`, the prod `whitelist.db` writers and `search.py`.\n</impact>\n<impact path=\"engine/server/db/jobs/sync-whitelist.py\" element=\"FTS helpers create_videos_fts_triggers (294-296), drop_videos_fts_triggers (299-306), rebuild_videos_fts (309-320), VIDEOS_FTS_TRIGGERS_SQL (270-285), ensure_content_schema (323-417), and the count check in rebuild_content_tables (511-521)\">\n**What changes.** Nothing. The repair job and the new test reuse these helpers.\n\n**What depends on it.**\n- The new job and the whitelist-shape test fixture. `ensure_content_schema` creates `channels`, `videos`, `video_embeddings`, `videos_fts` (fts5, `content='videos'`) and the triggers.\n- Note the fixture shape. The whitelist `channels` table has no NOT NULL besides the keys. The whitelist `videos` table has `popularity REAL NOT NULL DEFAULT 0` and `last_checked_at INTEGER NOT NULL`, so the fixture inserts must supply `last_checked_at`.\n- `rebuild_videos_fts` issues the `'rebuild'` command and returns `COUNT(*)` from `videos_fts`. On an external-content table that count reflects the content table, so the equality check is a weak guard. It matches sync-whitelist's own check, as required.\n\n**Regression risk: low.**\n- The helpers use `executescript`, whose commit behaviour is described in the job's entry.\n- If a later edit makes any helper non-idempotent, or makes `ensure_content_schema` do more, the repair job and test inherit that change silently. This is a coupling the build accepts in exchange for reuse.\n</impact>\n<impact path=\"engine/server/db/jobs/sync-whitelist.py\" element=\"module top level: sys.path mutation (16-22), imports (24-26), DEFAULT_SOURCE_DB_PATH (31), SCHEMA_SQL_PATH and *_COLUMNS parsed at import (36, 92-96), __main__ guard (676)\">\n**What changes.** Nothing.\n\n**What depends on it.**\n- Loading this module from the repair job runs this top-level code.\n- It leaves `engine/server` and `engine/server/api` on `sys.path`.\n- `main()` is guarded, so no sync runs.\n- `SCHEMA_SQL_PATH` is `script_dir.parents[3] / \"engine/crawler/schema.sql\"`, which resolves correctly from the jobs directory.\n\n**Regression risk: low.** It fails loudly at load if `schema.sql` or the server tree is missing.\n- **Module name.** The job should load it under an identifier-like name distinct from the test's `sync_whitelist_job`. Two module objects are harmless; the module defines no dataclass, so no `sys.modules` registration is needed.\n- **`conftest.py` interaction.** It imports `client/backend/server.py` as `server` first. The `engine/server/api/server.py` on `sys.path` does not shadow it, because the module is already cached. This is the same situation as the existing tests.\n</impact>\n<impact path=\"engine/server/db/jobs/recompute-popularity.py\" element=\"style reference: preamble, argparse, logging, --db default\">\n**What changes.** Nothing.\n\n**What depends on it.** It is the style reference for the new job.\n- The log line style is `\"popularity updated rows=%d\"` (line 121). The new job's key=value line should match, for example `channel names repaired rows=%d`. The CLI subprocess test can then parse the count.\n- Its `--db` default is `whitelist.db` (see the correction in the job entry).\n\n**Regression risk: none.**\n</impact>\n<impact path=\"engine/server/db/whitelist.db (prod/server copy) and its concurrent writers: engine/server/api/handlers/video.py (UPDATE videos ... channel_name, lines 305-343) and engine/server/db/jobs/merge-staging-db.py (INSERT OR IGNORE, lines 162-190)\">\n**What changes.** Nothing in the code. The repair will be run by the operator against live `whitelist.db` copies.\n\n**What depends on it.**\n- **The Engine's `/api/video` write-back.** It rewrites `videos.channel_name` and `channels.display_name` from the live instance, under `server.db_lock`, inside a try. It is the only other writer of `channel_name`.\n- **The updater merge.** It inserts `videos` INSERT_ONLY and fires `videos_fts_ai`.\n\n**Regression risk: medium, operational.**\n- **Missed triggers.** While the triggers are dropped, rows written by the Engine or the merge skip the per-row FTS maintenance. The following `rebuild` covers them, so the end state is correct.\n- **Lock contention.** The full rebuild holds the write lock for a long time on the ~890k-row prod DB. The Engine's write-back will hit `database is locked` (caught by its try), and a concurrent updater merge may fail. The runbook must say to run the repair outside an updater cycle, and ideally with the Engine idle or stopped.\n- **`channels` is INSERT_ONLY too** (merge_rules.json:9-12). Prod `channels.display_name` is therefore the first-inserted value, possibly refreshed by `/api/video`. It is still the correct host's name, so the repair source is sound.\n- **Migrated but not re-synced DBs.** `whitelist_migrations.migrate_videos_schema` (lines 260-265) drops `videos_fts`, and only the next `ensure_content_schema` recreates it. On such a copy the repair takes the no-FTS branch, and search is already disabled by `fts_available`.\n</impact>\n<impact path=\"engine/server/db/jobs/merge_rules.json\" element=\"videos / channels strategy INSERT_ONLY (lines 8-17)\">\n**What changes.** Nothing.\n\n**What depends on it.** It is why the repair must run on every `whitelist.db` copy: a merge never overwrites existing prod rows, so fixing staging or `crawl.db` does not propagate to prod. `test-orchestrator-smoke.py:793-809` asserts this invariant.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"engine/server/data/search.py\" element=\"fts_available() (121-131), lexical_candidates() (134-164)\">\n**What changes.** Nothing.\n\n**What depends on it.** It reads `videos_fts MATCH ?` joined to `videos` by rowid. After the repair, lexical search on `channel_name` returns the correct channel's videos. This is the user-visible outcome that the new FTS test checks directly with MATCH, bypassing this module.\n\n**Regression risk: low.** During the repair window (triggers dropped, rebuild in progress), searches may see a stale index or wait on the lock.\n</impact>\n<impact path=\"engine/server/db/jobs/build-video-embeddings.py\" element=\"embedding text builder (lines 40-54, query 189-205)\">\n**What changes.** Nothing. Changing it is out of scope.\n\n**What depends on it.** It appends `channel: <channel_name>`. Existing vectors keep the foreign names until the operator runs `--force`, then `build-ann-index.py` and `precompute-similar-ann.py`.\n\n**Regression risk: none from the code.** It is listed because the runbook's follow-up step depends on it.\n</impact>\n<impact path=\"engine/server/db/jobs/updater-worker.py\" element=\"crawler invocation of dist/videos-cli.js (lines 805, 954) and staging merge (1055)\">\n**What changes.** Nothing.\n\n**What depends on it.** Once the rebuilt dist is merged, updater crawls write correct names into staging. The merge then inserts only new rows into prod, which is why existing prod rows still need the repair.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"scripts/run-dataset-build.sh\" element=\"full pipeline: crawl \u2192 sync-whitelist (228) \u2192 embeddings (236) \u2192 ANN (244) \u2192 precompute (253)\">\n**What changes.** Nothing. The repair is a one-off migration and is not added to the pipeline.\n\n**What depends on it.** A full rebuild after the fix, re-crawl plus sync, produces correct names without the repair job.\n\n**Regression risk: none.** I list it because an operator might ask whether the job belongs here. It does not: a fresh crawl with the fixed writer gets names right, and the ON CONFLICT upsert overwrites `channel_name`.\n</impact>\n<impact path=\"tests/active/test_channel_names.py\" element=\"new test module: crawl test, parametrised repair tests, FTS test, CLI subprocess test\">\n**What changes.** A new file.\n- **Header.** It imports `ROOT` from `conftest` and adds `engine/server` to `sys.path`, as `test_host_normalisation.py:19-23` does.\n- **Loader.** It loads `repair-video-channel-names.py` (and `sync-whitelist.py` for `ensure_content_schema`) with an inline `_load_job`, a copy of `test_host_normalisation.py:78-82`.\n\n**Crawl test.**\n- **Gates.** It copies the node / dist-missing / git / staleness gates of `test_host_normalisation.py:48-70`: `_git`, `_dist_is_stale`, `BUILD_HINT = \"cd engine/crawler && npm install && npm run build\"`. SRC and DIST point at `videos-worker.ts` / `.js`.\n- **What else the gates must cover.** Unlike `host-filters.js`, `dist/videos-worker.js` imports `better-sqlite3` (and `./db.js`, which reads `schema.sql`). The node process therefore also needs `engine/crawler/node_modules`. The test should fail with the build hint when node cannot import it, for example by asserting returncode 0 with stderr in the message.\n- **Node script.** `node --input-type=module -e` with `await import(<dist uri>)`, then `crawlVideos({...})`, with `cwd=engine/crawler` so bare-specifier resolution finds `node_modules`. Resolution goes from the dist file's location, so cwd matters less, but setting it is safe.\n- **Servers.** Two `ThreadingHTTPServer`s on `(\"127.0.0.1\", 0)`, each in a daemon thread and shut down in `finally`.\n- **Assertions.** Per host, `channel_name` equals its own `display_name`. `channel_url` equals its own channel's URL, which requires the payload to have no `channel.url`.\n\n**Repair tests.**\n- **Parametrisation.** Over a crawl-shape fixture (`schema.sql` via `executescript`) and a whitelist-shape fixture (`ensure_content_schema`).\n- **Seeded rows.** Mismatched, already-correct, empty and NULL `display_name`. The plan should also seed a video with no `channels` row, which the requirements name.\n- **Assertions.** The exact count, each row's value, and 0 on the second run.\n\n**CLI test.** One subprocess run with `sys.executable`, parsing the `rows=N` log line.\n\n**FTS test.** MATCH on the correct name versus the foreign name, and `COUNT(videos_fts) == COUNT(videos)`.\n- **MATCH syntax.** It must use a column filter (`channel_name : \"...\"`, quoted as a phrase). A bare MATCH on the old name could also hit the title or description if the fixture text contains it. Fixture names should be distinctive single-token strings.\n- **Why the foreign name disappears.** The foreign-name query no longer returning the videos depends on the rebuild re-tokenising. In an external-content table, stale tokens would otherwise remain.\n\n**What depends on it.** `validate_tests.py` discovers `tests/active/test_*.py` automatically. It has no mapping in the local `.un/skills/devsecops/config.json`, which is gitignored and outside this read, so until harvest it runs on every invocation.\n\n**Regression risk: medium, for suite stability.**\n- The node, `node_modules` and dist gates can go red on machines without the crawler installed. `test_host_normalisation.py` needs node but not `node_modules`, so this is a new, stricter requirement.\n- I could not verify that `engine/crawler/node_modules` exists in this worktree. The read was refused as outside the project, which suggests a symlink to another checkout.\n- The crawl needs an https failure, then an http success, per channel. With the default 5000 ms timeout a TLS failure is immediate, so the runtime stays small.\n- Every DB must be under `tmp_path`. It must never request the `engine` or `dataset` fixtures, which open the shared `whitelist.db`.\n</impact>\n<impact path=\"tests/active/test_host_normalisation.py\" element=\"gate helpers _git/_dist_is_stale (48-61), test_crawler_dist_returns_pinned_values (64-75), _load_job (78-82)\">\n**What changes.** Nothing. The new test copies these patterns inline, as the plan chooses.\n\n**What depends on it.** It must stay green. It checks `host-filters.ts` / `.js`, and the rebuild regenerates `dist/host-filters.js` too.\n- If the regenerated `host-filters.js` differs from the committed one, it gets a new commit time. That is harmless, since the dist is then newer than the source.\n- If the rebuild is committed with `host-filters.ts` unchanged, nothing changes for this test.\n\n**Regression risk: low.** The staleness rule is by commit time, so rebuilding and committing only `videos-worker.js` cannot make it stale.\n</impact>\n<impact path=\"tests/active/conftest.py\" element=\"module-level Client backend import (37-43), ROOT (31), WHITELIST_DB (34)\">\n**What changes.** Nothing.\n\n**What depends on it.** The new test imports `ROOT`. `WHITELIST_DB` is the shared dataset and must not be used.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"tests/last_test_validation.json\" element=\"tracked suite record (also tests/last_test_output.txt)\">\n**What changes.** Both files are rewritten by the post-build `validate_tests.py` run.\n\n**What depends on it.** The comparison against the green baseline.\n\n**Regression risk: none functionally.** They conflict on merge. Take main's copy and re-run the comparison.\n</impact>\n<impact path=\"client/frontend/src/components/video-card.ts\" element=\"channel_name fallback (line ~142)\">\n**What changes.** Nothing. It is explicitly out of scope.\n\n**What depends on it.** It reads `videos.channel_name` only when `channel_url` is empty, which applies to 0 rows per triage.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"client/frontend/src/pages/video-page/index.ts\" element=\"local `channelMeta` / fetchChannelMetadata (599-630)\">\n**What changes.** Nothing.\n\n**Why it is listed.** It is an unrelated same-named identifier that a `channelMeta` grep hits. It is recorded only so no one edits it by mistake.\n\n**Regression risk: none.**\n</impact>\n</impacts>\n",
  "docs_checklist": "- [x] `DATA_BUILD.md` - updated: Added a \"Repair video channel names (one-time migration)\" subsection to `DATA_BUILD.md` at the end of step 2. It gives the repair command, the order to run it in, and how it behaves.\n- [x] `docs/project/issues/34-video-channel-name-wrong-instance.md` - updated: Issue 34 is marked complete with a Delivered record, its wrong claims are corrected, and six of its seven criteria are ticked. **It is still in `docs/project/issues/`: please run `git mv docs/project/issues/34-video-channel-name-wrong-instance.md docs/project/issues/archive/`**, because I have no tool that can move or delete files.\n- [x] `engine/server/db/jobs/docs/UPDATER_WORKER.md` - out of scope: It never mentions `channel_name`, the repair, or `INSERT_ONLY` by name. Its claims (line 71: prod gets merged changes according to `merge_rules.json`; line 88: the worker stops the Engine around the merge) are still true, because the build changed no updater, merge or rule behaviour. The operational guidance (INSERT_ONLY means every prod `whitelist.db` must be repaired directly, and no repair during an updater cycle) goes in the new DATA_BUILD.md section, so the optional note would duplicate it.\n- [x] `docs/project/issues/plan.md` - out of scope: It is a sequencing plan. Its lines on issue 34 (line 62: the repair runs on main after the merge; line 150: migrations run on main after merge) are still accurate descriptions of the intended order. It says nothing about the writer or the repair that the build made false. Issue status is tracked in the issue file.\n- [x] `CONTEXT.md` - out of scope: The glossary's only channel-related term is **Block** (`instance_domain` + `channel_id`), which the build does not touch. It defines no term for `channel_name`, the crawler's channel metadata, or data repairs, and the build introduces no new domain concept that needs a glossary entry.",
  "docs": [
    {
      "path": "DATA_BUILD.md",
      "note": "Add a new section after \"## 2) Filter to JoinPeerTube whitelist\" (which ends at line 158, before \"## 3) Build embeddings\") covering the one-off repair of `videos.channel_name`:\n- A one-line reason for the repair.\n- It is a migration of shared databases: run it on main after merge only, never from a worktree.\n- Run it outside an updater cycle, with the Engine idle, because the FTS rebuild holds the write lock.\n- The order:\n  1. Merge.\n  2. `python3 engine/server/db/jobs/repair-video-channel-names.py --db engine/crawler/data/crawl.db`.\n  3. The same command with `--db` on every `whitelist.db`, including prod, because merges are `INSERT_ONLY`.\n  4. The operator follow-up, using the flags this file already documents: `build-video-embeddings.py --db-path engine/server/db/whitelist.db --force`, then `build-ann-index.py` with `--db-path`, `--index-path`, `--meta-path`, and `--gpu` or `--cpu`, then `precompute-similar-ann.py` with `--db`, `--index`, `--out`, `--reset`, and `--gpu` or `--cpu`.\n\nTwo cautions:\n- The plan-17 reference in the requirements names `docs/project/plans/17-stable-ann-ids.md`, but that file does not exist in this tree. `docs/project/plans/` holds only `01-34-*`, and the related issue is `docs/project/issues/08-stable-ann-ids.md`. The runbook should cite something that exists, or name \"plan 17\" without a path.\n- The file already points at `engine/server/db/jobs/UPDATER_WORKER.md` (line 30), but the doc lives in `engine/server/db/jobs/docs/`. This is a pre-existing broken reference, worth fixing only if that line is touched."
    },
    {
      "path": "docs/project/issues/34-video-channel-name-wrong-instance.md",
      "note": "At harvest:\n- Tick the acceptance criteria.\n- Set `Status: bug, complete`.\n- Move the file to `docs/project/issues/archive/`, per `docs/project/triage-labels.md`.\n- Record that the repair and the re-embed are still owed by the operator on main.\n- Record the correction that the crawl slug was already host-correct: only `displayName` and the `channelUrl` fallback were wrong."
    },
    {
      "path": "engine/server/db/jobs/docs/UPDATER_WORKER.md",
      "note": "Optional. A one-line note that `videos` and `channels` merge `INSERT_ONLY`, so data corrections to existing prod rows, such as `repair-video-channel-names.py`, must be run against the prod `whitelist.db` directly, and not while an updater cycle holds the DB. No behaviour documented there changes, so leave the file untouched if the DATA_BUILD section says this already."
    }
  ],
  "reassessments": 1,
  "draft": "## Draft implementation: issue 34, `videos.channel_name` taken from another instance's channel\n\nThe draft was checked against the plan and the requirements in one pass and they converged, so no operator decision was needed. Before drafting I read `videos-worker.ts` (lines 150-300 and 420-700), `dist/videos-worker.js` (lines 1-130), `db.ts` (lines 1236-1425), `http.ts` (lines 30-165), `schema.sql`, `sync-whitelist.py` (lines 1-60, 265-424 and 495-530), `recompute-popularity.py`, `test_host_normalisation.py` and `DATA_BUILD.md` (lines 125-250).\n\n### What changes\n\n| Path | Change | Requirement |\n|---|---|---|\n| `engine/crawler/src/videos-worker.ts` | Two lines change: the map key where it is built, and the key at the lookup | R1 |\n| `engine/crawler/dist/videos-worker.js` | Regenerated with `npm run build` and committed with the source | R1 |\n| `engine/server/db/jobs/repair-video-channel-names.py` | New job | R2, R3 |\n| `tests/active/test_channel_names.py` | New test module | R4 |\n| `DATA_BUILD.md` | New section `## 2b)` placed between steps 2 and 3 | R5 |\n\n### Two corrections to the plan (they change nothing in scope)\n\n- **The slug was already correct.** `processChannel` reads the slug as `item.channelName ?? meta?.channelSlug` (videos-worker.ts:433), and `item.channelName` comes from the progress row for that host. The fix therefore changes only `displayName`, and `channelUrl`, which is the fallback after the payload's own `channel.url`.\n- **The neighbouring jobs default to `whitelist.db`, not `crawl.db`.** `server_config.DEFAULT_DB_PATH` is `engine/server/db/whitelist.db`. That makes a required `--db` even more important.\n\n---\n\n### 1. Writer fix: `engine/crawler/src/videos-worker.ts`\n\nAt the map build (lines 163-172), only the key expression changes:\n\n```ts\n  const channelMeta = new Map<string, ChannelMeta>(\n    channels.map((channel) => [\n      `${channel.instance_domain.toLowerCase()}/${channel.channel_id}`,\n      {\n        channelSlug: channel.channel_name,\n        displayName: channel.display_name,\n        channelUrl: channel.channel_url\n      }\n    ])\n  );\n```\n\nAt the lookup in `processInstance` (line 289), only the key changes:\n\n```ts\n    const meta = channelMeta.get(`${normalizedHost}/${item.channelId}`);\n```\n\n**Why the two keys always match.** The key is `lower(instance_domain) + \"/\" + channel_id`, and both sides build it from the same column:\n\n- The map side builds it from `channels.instance_domain`.\n- The lookup side uses `normalizedHost = host.toLowerCase()`. Here `host` comes from `groupByInstance(item.instanceDomain)`. That value is `video_crawl_progress.instance_domain`, which `prepareVideoProgress` copied verbatim from `channels.instance_domain`.\n\nA normalised host cannot contain `/` (a `:port` is allowed), so the separator cannot make two different pairs produce the same key.\n\n**What stays the same:**\n- The value type `ChannelMeta` and the `Map<string, ChannelMeta>` signatures in `workerLoop` (line 260) and `processInstance` (line 280).\n- `processChannel` and `toVideoRow`.\n- The name precedence in `toVideoRow` (lines 660-662): the crawl list's `displayName` first, then the payload's `channel.displayName` / `display_name`.\n\n**Dist.** Run `cd engine/crawler && npm run build`. The expected diff in `dist/videos-worker.js` is line 41 (`channel.channel_id,` becomes the same template literal) and line 126 (the `.get(...)` key). Any other file that `tsc` rewrites under `dist/` was already out of step with its source. That drift is reported at commit time, not folded silently into this change.\n\n---\n\n### 2 and 3. Repair job: `engine/server/db/jobs/repair-video-channel-names.py`\n\n```python\n#!/usr/bin/env python3\n\"\"\"Repair videos.channel_name from the channel row on the video's own instance.\n\nThe video crawler once looked up channel metadata by channel_id alone, so where PeerTube's per-instance channel ids repeat across instances a video took the display name of another instance's channel. This one-off migration sets each video's channel_name to the display_name of the channels row with the same (channel_id, instance_domain), and rebuilds videos_fts when the database has one.\n\"\"\"\nimport argparse\nimport importlib.util\nimport logging\nimport sqlite3\nimport sys\nfrom pathlib import Path\n\nscript_dir = Path(__file__).resolve().parent\nserver_dir = script_dir.parents[1]\nif str(server_dir) not in sys.path:\n    sys.path.insert(0, str(server_dir))\n\nfrom scripts.cli_format import CompactHelpFormatter\n\nREPAIR_SQL = \"\"\"\nUPDATE videos\nSET channel_name = (\n  SELECT c.display_name FROM channels c\n  WHERE c.channel_id = videos.channel_id AND c.instance_domain = videos.instance_domain\n)\nWHERE EXISTS (\n  SELECT 1 FROM channels c\n  WHERE c.channel_id = videos.channel_id\n    AND c.instance_domain = videos.instance_domain\n    AND c.display_name IS NOT NULL\n    AND c.display_name <> ''\n    AND c.display_name IS NOT videos.channel_name\n);\n\"\"\"\n\n\ndef _load_sync_whitelist():\n    \"\"\"Load sync-whitelist.py, whose hyphenated name rules out a normal import, for its videos_fts helpers.\"\"\"\n    spec = importlib.util.spec_from_file_location(\"sync_whitelist_for_repair\", script_dir / \"sync-whitelist.py\")\n    module = importlib.util.module_from_spec(spec)\n    spec.loader.exec_module(module)\n    return module\n\n\ndef has_videos_fts(conn: sqlite3.Connection) -> bool:\n    \"\"\"Whether the database carries the videos_fts index (the whitelist.db shape; crawl.db has none).\"\"\"\n    row = conn.execute(\"SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'videos_fts'\").fetchone()\n    return row is not None\n\n\ndef repair_channel_names(conn: sqlite3.Connection) -> int:\n    \"\"\"Set each video's channel_name to its own channel's display_name and return the number of rows changed.\n\n    Rows that already match, and rows whose channel has a NULL or empty display_name or no channels row, are left alone, so a second run returns 0. channels is only read. When videos_fts exists, the update runs between sync-whitelist.py's trigger drop and recreate, and the index is rebuilt and its count checked on every run, even when nothing changed. The helpers use executescript, which commits, so the update is already committed before the rebuild: a failed rebuild is recovered by running the job again, not by rollback.\n\n    :param conn: Connection to a crawl.db or whitelist.db.\n    :returns: Number of videos rows whose channel_name changed.\n    \"\"\"\n    if not has_videos_fts(conn):\n        changed = conn.execute(REPAIR_SQL).rowcount\n        conn.commit()\n        return changed\n    sync = _load_sync_whitelist()\n    sync.drop_videos_fts_triggers(conn)\n    changed = conn.execute(REPAIR_SQL).rowcount\n    sync.create_videos_fts_triggers(conn)\n    fts_count = sync.rebuild_videos_fts(conn)\n    videos_count = conn.execute(\"SELECT COUNT(*) FROM videos\").fetchone()[0]\n    if fts_count != videos_count:\n        raise RuntimeError(\n            f\"videos_fts holds {fts_count} rows but videos holds {videos_count}; \"\n            \"the full-text index did not rebuild cleanly.\"\n        )\n    conn.commit()\n    return changed\n\n\ndef main() -> None:\n    \"\"\"Handle main.\"\"\"\n    parser = argparse.ArgumentParser(\n        description=\"Repair videos.channel_name from the channel on each video's own instance.\",\n        formatter_class=CompactHelpFormatter,\n    )\n    parser.add_argument(\n        \"--db\",\n        required=True,\n        metavar=\"PATH\",\n        help=\"Path to the crawl.db or whitelist.db to repair (required; there is no default).\",\n    )\n    args = parser.parse_args()\n\n    logging.basicConfig(level=logging.INFO, format=\"%(levelname)s %(message)s\")\n\n    db_path = Path(args.db)\n    if not db_path.is_file():\n        parser.error(f\"database not found: {db_path}\")\n    conn = sqlite3.connect(str(db_path))\n    try:\n        changed = repair_channel_names(conn)\n    finally:\n        conn.close()\n    logging.info(\"channel names repaired rows=%d\", changed)\n\n\nif __name__ == \"__main__\":\n    main()\n```\n\n**What the job guarantees.**\n- **Changed count.** `rowcount` is read immediately after the UPDATE. The UPDATE runs in Python's implicit transaction, and no `executescript` has run yet at that point.\n- **NULL names.** The WHERE uses `IS NOT`, so a row whose `channel_name` is NULL is corrected too.\n- **Rows that can never match:** a NULL `videos.channel_id`, a channel with no row in `channels`, or a channel whose `display_name` is NULL or `''`.\n- **Index lookup.** The correlated subqueries join on the `channels` primary key `(channel_id, instance_domain)`, so each lookup uses the index.\n- **Idempotence.** After one run, every row that could match has `channel_name == display_name`, so a second UPDATE matches 0 rows.\n\n**Design decisions.**\n- **Why `is_file()` is checked.** `sqlite3.connect` would silently create an empty file for a mistyped path and then fail with \"no such table\". Checking first also keeps stray DBs from being created in the tree.\n- **Why the loader is called lazily.** It is only called on the FTS path, so the `crawl.db` path does not load `sync-whitelist.py` at all, and so does not need its load-time parse of `schema.sql`. The whitelist path loads it once per call, which is cheap.\n- **Log format.** `\"%(levelname)s %(message)s\"` and `rows=%d` follow `recompute-popularity.py`, so the CLI test can parse the count.\n\n**Deliberate simplification: no transaction across the FTS path.** The settled helpers commit internally, so the job cannot be atomic. The ceiling is that a crash between the trigger recreate and the rebuild leaves correct names with a stale index. Recovery is a re-run: it reports `rows=0`, but it rebuilds and checks the count. If one transaction is ever required, the upgrade path is to run `VIDEOS_FTS_DROP_TRIGGERS_SQL` and `VIDEOS_FTS_TRIGGERS_SQL` through `conn.execute` statement by statement instead of `executescript`. That is a change to `sync-whitelist.py`, which is outside this build.\n\n---\n\n### 4. Tests: `tests/active/test_channel_names.py`\n\n**Module constants and imports:**\n\n```python\n\"\"\"Each video carries its own instance's channel name (issue 34).\n\n- The compiled `crawlVideos` in `engine/crawler/dist/videos-worker.js`, run under node against two loopback hosts sharing a channel_id, writes each host's videos with that host's channel display name and URL; a missing node, git, node_modules or dist, or a stale dist, fails the test rather than skipping it.\n- `repair-video-channel-names.py` corrects mismatched and NULL names on both the crawl.db and whitelist.db shapes, leaves correct rows and rows whose channel has an empty, NULL or absent display name untouched, reports the changed count, and changes 0 rows on a second run.\n- On the whitelist.db shape the repaired videos_fts finds a channel's videos by its own name, not by the other instance's same-id name, and holds as many rows as videos.\n- The CLI requires --db and logs the changed count.\n\"\"\"\nfrom __future__ import annotations\n\nimport importlib.util\nimport json\nimport os\nimport re\nimport shutil\nimport sqlite3\nimport subprocess\nimport sys\nimport threading\nfrom http.server import BaseHTTPRequestHandler, ThreadingHTTPServer\nfrom urllib.parse import unquote, urlsplit\n\nimport pytest\nfrom conftest import ROOT\n\nSERVER_DIR = ROOT / \"engine\" / \"server\"\nif str(SERVER_DIR) not in sys.path:\n    sys.path.insert(0, str(SERVER_DIR))\n\nCRAWLER_DIR = ROOT / \"engine\" / \"crawler\"\nSRC = CRAWLER_DIR / \"src\" / \"videos-worker.ts\"\nDIST = CRAWLER_DIR / \"dist\" / \"videos-worker.js\"\nCRAWL_SCHEMA = CRAWLER_DIR / \"schema.sql\"\nBUILD_HINT = \"cd engine/crawler && npm install && npm run build\"\nJOBS_DIR = SERVER_DIR / \"db\" / \"jobs\"\nREPAIR_JOB = JOBS_DIR / \"repair-video-channel-names.py\"\n```\n\n**Helpers copied inline.** `_git`, `_dist_is_stale` and `_load_job` are copied verbatim from `test_host_normalisation.py`. They read the module-level `SRC`, `DIST` and `JOBS_DIR`, so they check the videos-worker pair.\n\n**Module fixture:**\n\n```python\n@pytest.fixture(scope=\"module\")\ndef jobs():\n    return _load_job(\"sync_whitelist_channel_names\", \"sync-whitelist.py\"), _load_job(\"repair_video_channel_names\", \"repair-video-channel-names.py\")\n```\n\n#### Crawl test\n\n**Node script.** Run with `node --input-type=module -e`, with `cwd=CRAWLER_DIR`:\n\n```js\nconst { crawlVideos } = await import(process.env.VIDEOS_WORKER_URL);\nawait crawlVideos(JSON.parse(process.env.CRAWL_OPTIONS));\n```\n\n**Fake server:**\n\n```python\nclass _ChannelVideosHandler(BaseHTTPRequestHandler):\n    timeout = 1  # the crawler tries https first; a TLS ClientHello with no newline would otherwise hold readline until the crawler's own timeout\n\n    def do_GET(self):\n        path = urlsplit(self.path).path\n        prefix, suffix = \"/api/v1/video-channels/\", \"/videos\"\n        slug = unquote(path[len(prefix):-len(suffix)]) if path.startswith(prefix) and path.endswith(suffix) else None\n        videos = self.server.videos_by_slug.get(slug)\n        if videos is None:\n            self.send_error(404)\n            return\n        body = json.dumps({\"total\": len(videos), \"data\": videos}).encode(\"utf-8\")\n        self.send_response(200)\n        self.send_header(\"Content-Type\", \"application/json\")\n        self.send_header(\"Content-Length\", str(len(body)))\n        self.end_headers()\n        self.wfile.write(body)\n\n    def log_message(self, format, *args):\n        pass\n```\n\n**Crawl options.** The 18 keys from `videos-cli.ts:87-107`:\n\n```python\ndef _crawl_options(db_path) -> dict:\n    return {\"dbPath\": str(db_path), \"excludeHostsFile\": None, \"existingDbPath\": None, \"concurrency\": 1, \"timeoutMs\": 3000, \"maxRetries\": 0, \"newOnly\": False, \"stopAfterFullPages\": 0, \"sort\": \"-publishedAt\", \"maxInstances\": 0, \"maxChannels\": 0, \"maxVideosPages\": 0, \"tagsOnly\": False, \"updateTags\": False, \"commentsOnly\": False, \"hostDelayMs\": 0, \"resume\": False, \"errorsOnly\": False}\n```\n\n**`test_crawl_writes_each_hosts_own_channel_name(tmp_path)` runs in this order:**\n1. **Gates, the same as `test_crawler_dist_returns_pinned_values`:** node is on PATH, `DIST.is_file()`, git is on PATH, and `not _dist_is_stale(git)`. Each gate's message carries `BUILD_HINT`. A missing `node_modules` (better-sqlite3) shows up as a nonzero node exit, and that assertion also carries `BUILD_HINT`.\n2. **Servers.** Two `ThreadingHTTPServer((\"127.0.0.1\", 0), _ChannelVideosHandler)`, each run with `serve_forever` in a daemon thread. `host_a = f\"127.0.0.1:{server_a.server_port}\"`, and `host_b` likewise.\n   - `server_a.videos_by_slug = {\"alpha_chan\": [{\"uuid\": \"a1\", \"id\": 1, \"name\": \"Alpha one\"}, {\"uuid\": \"a2\", \"id\": 2, \"name\": \"Alpha two\"}]}`\n   - `server_b.videos_by_slug = {\"beta_chan\": [{\"uuid\": \"b1\", \"id\": 1, \"name\": \"Beta one\"}]}`\n   - The payloads carry no `channel` key, so neither the payload name nor the payload URL can mask the lookup.\n   - Both servers are shut down and closed in `finally`.\n3. **DB.** `tmp_path / \"crawl.db\"` is created with `executescript(CRAWL_SCHEMA.read_text())`. It gets both hosts in `instances`, and these rows in `channels` (named columns):\n   - `(\"7\", \"alpha_chan\", \"Alphachan\", f\"http://{host_a}/c/alpha_chan\", host_a, 2)`\n   - `(\"7\", \"beta_chan\", \"Betachan\", f\"http://{host_b}/c/beta_chan\", host_b, 1)`\n4. **Run.** `subprocess.run([node, \"--input-type=module\", \"-e\", NODE_SCRIPT], cwd=CRAWLER_DIR, capture_output=True, text=True, encoding=\"utf-8\", timeout=120, env={**os.environ, \"VIDEOS_WORKER_URL\": DIST.as_uri(), \"CRAWL_OPTIONS\": json.dumps(_crawl_options(db))})`. The run must exit 0; on failure the message includes stderr and `BUILD_HINT`.\n5. **Assert** that `{(instance_domain, video_id): (channel_name, channel_url)}` read from `videos` equals exactly:\n   - `(host_a, \"a1\")` and `(host_a, \"a2\")` \u2192 `(\"Alphachan\", f\"http://{host_a}/c/alpha_chan\")`\n   - `(host_b, \"b1\")` \u2192 `(\"Betachan\", f\"http://{host_b}/c/beta_chan\")`\n\n   On failure the message includes node's stdout. Exact equality also catches a crawl that wrote nothing.\n\n**Why it fails on today's code.** Whichever order `listChannelsWithVideos` returns the rows in, the id-only map keeps one entry for id `7`, so one host's rows get the other host's name and URL.\n\n**How the fake servers are reached.** The crawler tries https first against the plain-HTTP server. That attempt fails with a TLS error or ECONNRESET, or with an abort when the handler's 1 s read timeout closes the socket. None of these codes is in `isNoNetworkError`, so curl never runs. With `maxRetries 0` the https attempt throws, and `fetchPage` falls back to http. `ThreadingHTTPServer` answers each connection on its own thread, so the stuck https connection does not block the http one.\n\n#### Repair tests\n\n**Seed data.** `_seed(conn)` inserts with named columns, so it works on both schemas. Videos carry `last_checked_at = 1`, a distinct title such as `\"clip v1\"`, and description `\"plain text\"`.\n\n| channels `(channel_id, instance_domain, display_name)` |\n|---|\n| `(\"7\", \"a.example\", \"Alphachan\")` |\n| `(\"7\", \"b.example\", \"Betachan\")` |\n| `(\"8\", \"a.example\", \"\")` |\n| `(\"9\", \"a.example\", None)` |\n\n| video | instance, channel | stored `channel_name` | expected after repair |\n|---|---|---|---|\n| v1 | a.example, 7 | `\"Betachan\"` | `\"Alphachan\"` |\n| v2 | b.example, 7 | `\"Alphachan\"` | `\"Betachan\"` |\n| v3 | b.example, 7 | `\"Betachan\"` | unchanged |\n| v4 | a.example, 8 | `\"Stalename\"` | unchanged (empty `display_name`) |\n| v5 | a.example, 9 | `\"Stalename\"` | unchanged (NULL `display_name`) |\n| v6 | a.example, 404 | `\"Orphanname\"` | unchanged (no channel row) |\n| v7 | a.example, 7 | `None` | `\"Alphachan\"` |\n\n`EXPECTED_CHANGED = 3`.\n\n**Fixture.** `seeded_db` is `@pytest.fixture(params=[\"crawl\", \"whitelist\"])` and uses `jobs` and `tmp_path`:\n- `\"crawl\"` runs `executescript(CRAWL_SCHEMA.read_text())`.\n- `\"whitelist\"` runs `sync.ensure_content_schema(conn)`, which creates `videos_fts` and its triggers, so the index is seeded with the stale names.\n- It then calls `_seed`, commits, closes, and returns the path. The FTS table is present or absent according to the parameter.\n\n**Tests:**\n- **`test_repair_sets_each_video_to_its_own_channel_name(jobs, seeded_db)`**\n  - Calls `repair.repair_channel_names(conn)` and asserts it returns `3`.\n  - Asserts `dict(SELECT video_id, channel_name FROM videos)` equals the expected column.\n  - Asserts the `channels` rows are unchanged, compared with a snapshot taken before the repair.\n  - Asserts a second call returns `0` and leaves the dict the same.\n  - Asserts `has_videos_fts(conn)` is `True` exactly for the `whitelist` parameter.\n- **`test_repaired_fts_finds_own_name_not_foreign_name(jobs, tmp_path)`** (whitelist shape only)\n  - `_matches(conn, name)` runs `SELECT v.video_id FROM videos_fts JOIN videos v ON v.rowid = videos_fts.rowid WHERE videos_fts MATCH ?` with `f'channel_name : \"{name}\"'`.\n  - After the repair, `Alphachan` gives `{\"v1\", \"v7\"}` and `Betachan` gives `{\"v2\", \"v3\"}`. That excludes v1, which carried `Betachan` in the stale index before the repair.\n  - `COUNT(*)` on `videos_fts` equals `COUNT(*)` on `videos`, which is 7.\n- **`test_cli_requires_db_and_logs_changed_count(tmp_path)`**\n  - Running `[sys.executable, str(REPAIR_JOB)]` exits with return code `2` (argparse, `--db` required).\n  - A crawl-shape seeded DB is built inline, and `[sys.executable, str(REPAIR_JOB), \"--db\", str(db)]` exits `0`.\n  - `re.search(r\"channel names repaired rows=(\\d+)\", proc.stderr)` gives `3`. A second run gives `0`.\n\n**Isolation.** Every DB lives under `tmp_path`. No test requests the `engine` or `dataset` fixtures or refers to `WHITELIST_DB`.\n\n---\n\n### 5. Runbook: `DATA_BUILD.md`\n\nInsert after line 158, before `## 3) Build embeddings`:\n\n````markdown\n## 2b) Repair `videos.channel_name` (one-off migration)\nUntil issue 34 was fixed, the video crawler looked up channel metadata by `channel_id` alone, so about 74% of videos carry the display name of the same-id channel on another instance; search and embeddings inherit the wrong name.\n\nThis is a migration of shared databases: run it on main after the fix is merged, never from a worktree. Run it outside an updater cycle and with the Engine idle, because on a `whitelist.db` it rebuilds `videos_fts` and holds the write lock for the duration.\n\n1. Merge the fix to main.\n2. Repair the crawl database:\n   ```bash\n   python3 engine/server/db/jobs/repair-video-channel-names.py --db engine/crawler/data/crawl.db\n   ```\n3. Repair every copy of `whitelist.db`, the prod/server database included. The updater merges `videos` `INSERT_ONLY`, so it never corrects existing rows:\n   ```bash\n   python3 engine/server/db/jobs/repair-video-channel-names.py --db engine/server/db/whitelist.db\n   ```\n4. Operator follow-up, scheduled with plan 17's (stable ANN ids) cutover so the index is rebuilt only once: re-embed, rebuild the ANN index, then the similarity cache.\n   ```bash\n   python3 engine/server/db/jobs/build-video-embeddings.py \\\n     --db-path engine/server/db/whitelist.db --force\n   python3 engine/server/db/jobs/build-ann-index.py \\\n     --db-path engine/server/db/whitelist.db \\\n     --index-path engine/server/db/whitelist-video-embeddings.faiss \\\n     --meta-path engine/server/db/whitelist-video-embeddings.faiss.json \\\n     --normalize --gpu\n   python3 engine/server/db/jobs/precompute-similar-ann.py \\\n     --db engine/server/db/whitelist.db \\\n     --index engine/server/db/whitelist-video-embeddings.faiss \\\n     --out engine/server/db/similarity-cache.db \\\n     --reset --gpu\n   ```\n   Use `--cpu` in place of `--gpu` where there is no CUDA.\n\nNotes:\n- `--db` is required; the job has no default database.\n- The job logs `channel names repaired rows=N`. A second run reports `rows=0`, and on a `whitelist.db` it still rebuilds and checks the full-text index, so re-running is the recovery if a run is interrupted.\n- Search reflects the corrected names as soon as step 3 finishes; similar-video results only do so after step 4.\n- A fresh crawl with the fixed crawler writes correct names by itself, so the job is not part of `run-dataset-build.sh`.\n````\n\n**Plan 17 reference.** The runbook names \"plan 17 (stable ANN ids)\" without a path, because `docs/project/plans/17-stable-ann-ids.md` does not exist in this tree. Line 30's broken `UPDATER_WORKER.md` pointer is not touched. `UPDATER_WORKER.md` is left alone because the `INSERT_ONLY` note is in this section.\n\n---\n\n### Checked against the plan and the requirements\n\n| Requirement | How the draft meets it |\n|---|---|\n| R1 | The key is host plus id at both the build and the lookup, from the same column and lowercased on both sides. Precedence is unchanged, the rest of the crawler is unchanged, and the dist is rebuilt. |\n| R2 | One set-based UPDATE with a `(channel_id, instance_domain)` join, guarded for non-NULL, non-empty and `IS NOT`. `channels` is only read. The count comes from `rowcount`, and a second run returns 0. The CLI has argparse, `CompactHelpFormatter`, a required `--db PATH`, INFO logging and a guarded `main()`. |\n| R3 | The `videos_fts` probe, then the reused drop / update / create / rebuild helpers loaded by `spec_from_file_location`. The count check copies `sync-whitelist.py`'s `RuntimeError`, and the FTS steps are skipped on `crawl.db`. |\n| R4 | A two-host crawl test with the node gates, which fails on today's code. Repair tests on both schemas cover mismatched, correct, empty, NULL, absent and NULL-current rows, plus the second run. There is an FTS test with column-filtered MATCH and the count check, a CLI test, and only `tmp_path` DBs. |\n| R5 | The section after step 2 has the merge / crawl.db / every whitelist.db / re-embed order, \"main after merge only, never from a worktree\", and the timing note. |\n\n**Constraints.** The job uses only the stdlib and adds no dependency or abstraction. The agent never runs it against a real database. The existing suite is untouched: `test_host_normalisation.py` checks `host-filters`, whose source does not change.\n\n**Risks the operator carries** (from the plan, unchanged):\n- The FTS path is not atomic.\n- Every whitelist run pays a full rebuild.\n- The repair joins `instance_domain` exactly as stored, so a channel whose `instance_domain` is stored in mixed case would not be repaired.\n- The new test needs `engine/crawler/node_modules`, a stricter requirement than `test_host_normalisation.py`.\n- Embeddings keep the foreign names until step 4.",
  "coordination": "Phase 1: the crawl checkpoint needs `node` on PATH and `engine/crawler/node_modules` (better-sqlite3), which `npm install` may need network access to fetch. It also needs the dist rebuilt with `cd engine/crawler && npm run build` and committed with the source, or the staleness gate fails. No credentials are needed and no live endpoints are used: the test binds only to loopback ephemeral ports. No phase touches the real crawl.db or whitelist.db. Running the job against those databases is the operator's post-merge step in the runbook.",
  "tests": {
    "tests/tmp/test_34_video_channel_name_wrong_instance_phase1.py": {
      "rows": [
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_34_video_channel_name_wrong_instance_phase1.py:112 \u2014 `names`, keyed by (instance_domain, video_id) over every stored video row, equals exactly {(host_a,\"a-1\"):\"Alpha Display\", (host_a,\"a-2\"):\"Alpha Display\", (host_b,\"b-1\"):\"Beta Display\"}",
          "expected": "Once the phase is built, alpha's two videos carry \"Alpha Display\" and beta's one video carries \"Beta Display\", with no other rows. The current code reached this assertion with rc 0 and all three videos stored (crawl log \"new=2\", \"new=1\", \"new_total=3\"), so the row set and keys are observed. The per-host values are the fixture's own display_name for each host.",
          "wrong_implementation": "The current code keys `channelMeta` by `channel_id` alone (videos-worker.ts:163-172), so the two \"7\" rows collide and one host's meta overwrites the other's. Observed in the gating run: `{(host_a,'a-1'): 'Beta Display', (host_a,'a-2'): 'Beta Display'}`, so alpha's videos got beta's name. Observed in the probe run: b-1 read 'Alpha Display'. Which host wins changes between runs, and the assertion goes red either way. Other wrong fixes it excludes: using the slug `channel_name` (\"alpha\"/\"beta\" instead of the display names), or storing null."
        },
        {
          "clause": "C2",
          "assertion": "tests/tmp/test_34_video_channel_name_wrong_instance_phase1.py:113 \u2014 `urls`, keyed by (instance_domain, video_id), equals exactly {(host_a,\"a-1\"):url_a, (host_a,\"a-2\"):url_a, (host_b,\"b-1\"):url_b}, where url_a/url_b are each host's own channels.channel_url",
          "expected": "Once the phase is built, a-1 and a-2 carry `http://<host_a>/video-channels/alpha` and b-1 carries `http://<host_b>/video-channels/beta`. The stand-in videos carry no `channel`, so `channelRef?.url` is absent and the value can only come from the channels row. The probe run confirmed that with every other fallback absent, the stored URL comes from that meta.",
          "wrong_implementation": "With the same channel_id-only `channelMeta` key, the colliding meta supplies the other host's URL. Observed in the probe run (same fixture as the checkpoint): `('127.0.0.1:40483', 'b-1', 'Alpha Display', 'http://127.0.0.1:41925/video-channels/alpha')`, so beta's video got alpha's URL. The name could be fixed while the URL still comes from shared meta, and C2 catches that partial fix."
        }
      ],
      "clauses": [
        {
          "id": "C1",
          "text": "Each host's crawled videos have `channel_name` equal to the `display_name` of the channel on that same host."
        },
        {
          "id": "C2",
          "text": "Each host's crawled videos have `channel_url` equal to the `channel_url` of the channel on that same host."
        }
      ],
      "surface": "checkpoint",
      "results": {
        "command": "validate_tests.py tests/tmp/test_34_video_channel_name_wrong_instance_phase1.py",
        "code": 1,
        "output": "  tests/tmp/test_34_video_channel_name_wrong_instance_phase1.py  1 failed                               0.0s\n  -------------------------------------------------------------\n  total                                                          1 failed                               0.7s wall, 1 lane\n\nrecorded: tests/last_test_validation.json (exit 1)\nwrote tests/last_test_output.txt"
      }
    },
    "tests/tmp/test_34_video_channel_name_wrong_instance_phase2.py": {
      "rows": [
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_34_video_channel_name_wrong_instance_phase2.py:85 \u2014 on a fresh connection after the first repair, `dict(SELECT video_id, channel_name FROM videos) == REPAIRED`: v1 \u2192 Alphachan, v2 \u2192 Betachan, v7 (was NULL) \u2192 Alphachan, and v3 Betachan, v4 Stalename, v5 Stalename, v6 Orphanname unchanged. Run on both the crawl and whitelist shapes.",
          "expected": "{'v1': 'Alphachan', 'v2': 'Betachan', 'v3': 'Betachan', 'v4': 'Stalename', 'v5': 'Stalename', 'v6': 'Orphanname', 'v7': 'Alphachan'} on both shapes. The probe observed exactly this dict after running the draft's REPAIR_SQL on each shape.",
          "wrong_implementation": "Each wrong variant below was observed in the probe on both shapes. `!=` instead of `IS NOT` leaves v7 None. Dropping the empty-name guard writes '' into v4. An unguarded update also writes None into v5. Joining on channel_id alone gives v2 and v3 'Alphachan'. A repair that never commits reads back as the seeded names when the database is reopened. Each of these makes the dict differ from REPAIRED."
        },
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_34_video_channel_name_wrong_instance_phase2.py:86 \u2014 after the repair, `SELECT * FROM channels ORDER BY channel_id, instance_domain` on a fresh connection equals the snapshot taken at line 74, before the repair. It is armed by line 85, which shows that the repair ran and wrote.",
          "expected": "The pre-repair rows unchanged. The probe observed four rows, for example on the crawl shape ('7',None,None,'Alphachan','a.example',\u2026), ('7',None,None,'Betachan','b.example',\u2026), ('8',None,None,'','a.example',\u2026), ('9',None,None,None,'a.example',\u2026), and the whitelist shape has its own column order.",
          "wrong_implementation": "A repair that also \"syncs\" channels, for example writing display_name into channels.channel_name, filling the empty or NULL display_name for channels 8 and 9, or pruning channel rows with no videos. The snapshot then differs in at least one row. This case was not run in the probe; the assertion is a direct before/after comparison of the whole table."
        },
        {
          "clause": "C2",
          "assertion": "tests/tmp/test_34_video_channel_name_wrong_instance_phase2.py:80 \u2014 the first `repair.repair_channel_names(conn)` returns exactly 3.",
          "expected": "3 on both shapes, taken from the UPDATE's rowcount in the probe. On the whitelist shape, trigger writes to videos_fts are not counted.",
          "wrong_implementation": "Counts observed in the probe: `!=` returns 2; no empty-name guard returns 4; channel_id-only join returns 4; unguarded returns 6. A function that returns the number of candidate rows (7) or a fixed value also fails."
        },
        {
          "clause": "C2",
          "assertion": "tests/tmp/test_34_video_channel_name_wrong_instance_phase2.py:88 \u2014 a second `repair_channel_names(conn)` on a fresh connection returns 0. Line 94 then reopens the database and checks that the names still equal REPAIRED.",
          "expected": "0 on the second call and the REPAIRED dict afterwards. The probe observed a second rowcount of 0 for the draft SQL on both shapes.",
          "wrong_implementation": "Second-run counts observed in the probe: channel_id-only join returns 4 again, because v2 and v3 flip back and forth; unguarded returns 6; no commit returns 3, because the first run was lost. A version that re-writes every matching row without the `IS NOT channel_name` guard returns non-zero every run. Line 94 catches a second run that changes names."
        }
      ],
      "clauses": [
        {
          "id": "C1",
          "text": "After a repair, videos with a foreign or NULL `channel_name` carry their own channel's `display_name`. Already-correct rows, rows whose channel has an empty, NULL or absent display name, and the `channels` table are unchanged."
        },
        {
          "id": "C2",
          "text": "The repair returns the number of rows it changed, and a second run returns 0."
        }
      ],
      "surface": "checkpoint",
      "results": {
        "command": "validate_tests.py tests/tmp/test_34_video_channel_name_wrong_instance_phase2.py",
        "code": 1,
        "output": "  tests/tmp/test_34_video_channel_name_wrong_instance_phase2.py  2 failed                               0.0s\n  -------------------------------------------------------------\n  total                                                          2 failed                               0.2s wall, 1 lane\n\nrecorded: tests/last_test_validation.json (exit 1)\nwrote tests/last_test_output.txt"
      }
    },
    "tests/tmp/test_34_video_channel_name_wrong_instance_phase3.py": {
      "rows": [
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_34_video_channel_name_wrong_instance_phase3.py:77 \u2014 after repair_channel_names, read through a fresh connection, `channel_name : \"Alphachan\"` MATCH joined to videos returns exactly {\"v1\", \"v7\"}",
          "expected": "{\"v1\", \"v7\"}. I observed this in the probe run with repair + rebuild_videos_fts + commit: \"REBUILT after ['v1', 'v7'] ...\".",
          "wrong_implementation": "The current repair, which relies only on the per-row videos_fts_au trigger and never rebuilds, can't re-index v1. v1 was corrected in videos while the triggers were dropped, so the UPDATE's `IS NOT` guard skips it and the index keeps its foreign \"Betachan\". The run showed this reads {'v7'}. A rebuild that never commits reads the same through the reopened connection."
        },
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_34_video_channel_name_wrong_instance_phase3.py:78 \u2014 the same MATCH for the other instance's same-id name, \"Betachan\", returns exactly {\"v2\", \"v3\"}, so a.example's v1 is not found under b.example's name",
          "expected": "{\"v2\", \"v3\"}. I observed this in the probe: \"REBUILT after ... ['v2', 'v3']\".",
          "wrong_implementation": "Under the trigger-only repair the index still carries v1 under \"Betachan\", and the probe read ['v1', 'v2', 'v3']. A repair that copied names across instances by channel_id alone would also put the wrong name back on v1 or v2 and break one of the two sets."
        },
        {
          "clause": "C2",
          "assertion": "tests/tmp/test_34_video_channel_name_wrong_instance_phase3.py:79 \u2014 (COUNT(*) FROM videos_fts_docsize, COUNT(*) FROM videos) == (8, 8) after the repair",
          "expected": "(8, 8). I observed this in the probe after repair + rebuild: \"REBUILT after ... 8 8\".",
          "wrong_implementation": "A repair that only fires row triggers never indexes v8. v8 was inserted while the triggers were dropped, and its channel's display name is empty, so the UPDATE skips it. The probe read \"CURRENT after ... 7 8\", which is (7, 8)."
        },
        {
          "clause": "C2",
          "assertion": "tests/tmp/test_34_video_channel_name_wrong_instance_phase3.py:81 \u2014 the FTS5 `integrity-check` with rank 1 (which checks the index against the videos content table) runs without raising",
          "expected": "No exception. I observed this in the probe: \"REBUILT integrity ok\".",
          "wrong_implementation": "Under the trigger-only repair the index disagrees with videos (v1's stale name, v8 missing), and the probe showed \"CURRENT integrity raised DatabaseError database disk image is malformed\"."
        }
      ],
      "clauses": [
        {
          "id": "C1",
          "text": "After the repair, a `channel_name` MATCH for a channel's own name returns that channel's videos, and a MATCH for the other instance's same-id name does not return them."
        },
        {
          "id": "C2",
          "text": "After the repair, `videos_fts` holds as many rows as `videos`."
        }
      ],
      "surface": "checkpoint",
      "results": {
        "command": "validate_tests.py tests/tmp/test_34_video_channel_name_wrong_instance_phase3.py",
        "code": 1,
        "output": "  tests/tmp/test_34_video_channel_name_wrong_instance_phase3.py  1 failed                               0.0s\n  -------------------------------------------------------------\n  total                                                          1 failed                               0.2s wall, 1 lane\n\nrecorded: tests/last_test_validation.json (exit 1)\nwrote tests/last_test_output.txt"
      }
    },
    "tests/tmp/test_34_video_channel_name_wrong_instance_phase4.py": {
      "rows": [
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_34_video_channel_name_wrong_instance_phase4.py:41 \u2014 the bare invocation `[sys.executable, REPAIR_JOB]` has returncode == 2; lines 42 and 43 back it: stderr contains argparse's \"the following arguments are required: --db\", and no `channel names repaired rows=N` line is logged",
          "expected": "returncode 2, and stderr reads `usage: ... --db PATH\\n...: error: the following arguments are required: --db\\n`. Observed by probe: a parser built with CompactHelpFormatter and `--db required=True, metavar=\"PATH\"` exits 2 with exactly that message. No repair line is logged.",
          "wrong_implementation": "The script as it stands, with no CLI entry point: exit 0 and empty stdout and stderr (observed, and this is today's red at :41). A `--db` that has a default, as its neighbours do: exit 0 and a repair of the default database logged, so :41 and :43 fail. An exit 2 caused by anything other than the missing `--db` (for example a crash from a bad import) fails :42."
        },
        {
          "clause": "C2",
          "assertion": "tests/tmp/test_34_video_channel_name_wrong_instance_phase4.py:58 and :64 \u2014 `re.findall(r\"channel names repaired rows=(\\d+)\", stderr)` is exactly [\"3\"] on the first `--db` run and exactly [\"0\"] on the second. :60 ties the 3 to the rows that actually changed (v1, v2 and v7). :57 and :63 require exit 0.",
          "expected": "First run: [\"3\"] and the names become {v1: Alphachan, v2: Betachan, v3: Betachan, v4: Stalename, v5: Stalename, v6: Orphanname, v7: Alphachan}. Second run: [\"0\"] with the names unchanged. Observed by probe on this exact inline seed: `repair_channel_names` returned 3, then 0, and left those names. A `logging.basicConfig(level=INFO, format=\"%(levelname)s %(message)s\")` line was observed on stderr as `INFO channel names repaired rows=3`.",
          "wrong_implementation": "A `--db` run that repairs but logs nothing, or prints to stdout: [] at :58. The script today exits 0 with empty stderr (observed). A hard-coded or cumulative count: [\"3\"] at :64. Logging the matched or total rows instead of the changed ones: [\"4\"] (with v3) or [\"7\"] at :58. A CLI that logs 3 but never calls the repair or never commits: the names at :60 stay as STORED."
        }
      ],
      "clauses": [
        {
          "id": "C1",
          "text": "Invoking the job without `--db` exits with an argparse usage error (return code 2)."
        },
        {
          "id": "C2",
          "text": "Invoking the job with `--db` logs `channel names repaired rows=N` with the changed count."
        }
      ],
      "surface": "checkpoint",
      "results": {
        "command": "validate_tests.py tests/tmp/test_34_video_channel_name_wrong_instance_phase4.py",
        "code": 1,
        "output": "  tests/tmp/test_34_video_channel_name_wrong_instance_phase4.py  1 failed                               0.0s\n  -------------------------------------------------------------\n  total                                                          1 failed                               0.2s wall, 1 lane\n\nrecorded: tests/last_test_validation.json (exit 1)\nwrote tests/last_test_output.txt"
      }
    }
  },
  "audits": {
    "tests/tmp/test_34_video_channel_name_wrong_instance_phase1.py": [
      {
        "shape": "```\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\nFails at line 112 on the `names ==` assertion. The current `crawlVideos` keys\n`channelMeta` by `channel.channel_id` alone (engine/crawler/src/videos-worker.ts:163-171),\nand both channel rows share channel_id \"7\". One host's metadata therefore overwrites the\nother's, and one host's videos get the other host's display_name (\"Alpha Display\" where\n\"Beta Display\" belongs, or the reverse). Line 113 would fail the same way on `channel_url`\nif line 112 did not stop the test first.\n\nNOT ASSESSED\n1. `code_under_test` lists tests/active/test_channel_names.py (NEW), which does not\n   exist. It was not read, and it has no bearing on this test's assertions.\n2. engine/crawler/dist/videos-worker.js was not read. The stub question and the predicted\n   failure come from src/videos-worker.ts (lines 136-202 and 641-699) and assume the\n   compiled output matches it. The test guards that assumption at line 77.\n3. `fixtures_path` was not supplied. The test builds all its fixtures inline (lines 48-68,\n   79-94), so there was nothing to resolve. engine/crawler/schema.sql was not read.\n```",
        "claim": "CLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (14 clauses: 2 must_prove, 10 docstring, 2 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1 | must_prove | each host's videos have `channel_name` = that host's channel `display_name` | :112 | Looking up channel metadata by `channel_id` alone, which puts one host's display name on both hosts' videos. Both rows share id \"7\" (:91) and have different display names | CARRIED |\n| C2 | must_prove | each host's videos have `channel_url` = that host's channel `channel_url` | :113 | The same `channel_id`-only lookup, which gives both hosts' videos one URL. `url_a` and `url_b` differ (:84-85), and the stand-in videos have no `channel` object (:49, :79-80), so the stored URL has to come from the channels row | CARRIED |\n| D1 | docstring | \"compiled `crawlVideos`, run under node against two local PeerTube stand-ins whose channels share channel_id \\\"7\\\"\" | :103, :112 | A node run that fails or never runs `crawlVideos`. :112 also needs rows keyed under both hosts, so it fails if only one stand-in was crawled | CARRIED |\n| D2 | docstring | \"every video stored for a host has `channel_name` equal to the `display_name` of that host's own channel row\" | :112 | Wrong or null names, and videos missing from the result (the whole dict must be equal) | CARRIED |\n| D3 | docstring | \"no video carries the other host's name\" | :112 | Cross-host name leakage: any `Beta Display` on an alpha key fails the equality | CARRIED |\n| D4 | docstring | \"every video stored for a host has `channel_url` equal to the `channel_url` of that host's own channel row\" | :113 | Wrong or null URLs, and missing videos | CARRIED |\n| D5 | docstring | \"no video carries the other host's URL\" | :113 | Cross-host URL leakage | CARRIED |\n| D6 | docstring | \"a missing node ... fails the test rather than skipping it\" | :73 | A skip or early return when node is absent | CARRIED |\n| D7 | docstring | \"a missing ... git ... fails the test\" | :76 | A skip when git is absent | CARRIED |\n| D8 | docstring | \"a missing ... dist ... fails the test\" | :74 | Running against a dist that does not exist | CARRIED |\n| D9 | docstring | \"a ... stale dist ... fails the test\" | :77 | A green run against a dist compiled before the source edit | CARRIED |\n| D10 | docstring | \"a nonzero node exit fails the test\" | :103 | Reading an empty or partial DB after node crashed | CARRIED |\n| N1 | name | \"crawl writes ... channel name\" | :112 | A crawl that stores no name, or a null name | CARRIED |\n| N2 | name | \"each host's own\" | :112 | Names attributed across hosts; the test has two hosts and one shared channel id | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. name-as-sentence (rules/testing.md) \u2014 tests/tmp/test_34_video_channel_name_wrong_instance_phase1.py:71\n   The name `test_crawl_writes_each_hosts_own_channel_name` says what should happen but not when: the shared-`channel_id` condition is missing. It also names only the channel name, although the test asserts the channel URL too (C2, :113). A failure at :113 is reported under a name that does not mention URLs.\n2. bounds (rules/testing.md) \u2014 tests/tmp/test_34_video_channel_name_wrong_instance_phase1.py:91\n   Only populated channel rows run. `toVideoRow` (videos-worker.ts:660-664) has fallbacks that no test reaches:\n   - a channels row with a null `display_name`, which falls back to the video's own `channel.displayName`;\n   - a null `channel_url`.\n3. normal-and-abnormal-paths (rules/testing.md) \u2014 tests/tmp/test_34_video_channel_name_wrong_instance_phase1.py:79-80\n   The stand-in videos never carry a `channel` object. In `toVideoRow` the URL prefers the video's `channel.url` over the channels row (videos-worker.ts:664), while the name prefers the channels row (videos-worker.ts:661-662). Nothing tests that precedence, so C2 is proven only on the path where the video has no channel URL of its own.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `code_under_test` lists tests/active/test_channel_names.py, but no file exists at that path. Nothing from it was assessed.\n2. engine/crawler/dist/videos-worker.js was not read. The claims were judged against src/videos-worker.ts (the `crawlVideos` entry point, `processInstance` and `toVideoRow`).\n3. `fixtures_path` was not supplied. The test uses only pytest's built-in `tmp_path` fixture, so there was no conftest to resolve.",
        "body": "### devsecops-test-shape-auditor\n\n```\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\nFails at line 112 on the `names ==` assertion. The current `crawlVideos` keys\n`channelMeta` by `channel.channel_id` alone (engine/crawler/src/videos-worker.ts:163-171),\nand both channel rows share channel_id \"7\". One host's metadata therefore overwrites the\nother's, and one host's videos get the other host's display_name (\"Alpha Display\" where\n\"Beta Display\" belongs, or the reverse). Line 113 would fail the same way on `channel_url`\nif line 112 did not stop the test first.\n\nNOT ASSESSED\n1. `code_under_test` lists tests/active/test_channel_names.py (NEW), which does not\n   exist. It was not read, and it has no bearing on this test's assertions.\n2. engine/crawler/dist/videos-worker.js was not read. The stub question and the predicted\n   failure come from src/videos-worker.ts (lines 136-202 and 641-699) and assume the\n   compiled output matches it. The test guards that assumption at line 77.\n3. `fixtures_path` was not supplied. The test builds all its fixtures inline (lines 48-68,\n   79-94), so there was nothing to resolve. engine/crawler/schema.sql was not read.\n```\n\n### devsecops-test-claim-auditor\n\nCLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (14 clauses: 2 must_prove, 10 docstring, 2 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1 | must_prove | each host's videos have `channel_name` = that host's channel `display_name` | :112 | Looking up channel metadata by `channel_id` alone, which puts one host's display name on both hosts' videos. Both rows share id \"7\" (:91) and have different display names | CARRIED |\n| C2 | must_prove | each host's videos have `channel_url` = that host's channel `channel_url` | :113 | The same `channel_id`-only lookup, which gives both hosts' videos one URL. `url_a` and `url_b` differ (:84-85), and the stand-in videos have no `channel` object (:49, :79-80), so the stored URL has to come from the channels row | CARRIED |\n| D1 | docstring | \"compiled `crawlVideos`, run under node against two local PeerTube stand-ins whose channels share channel_id \\\"7\\\"\" | :103, :112 | A node run that fails or never runs `crawlVideos`. :112 also needs rows keyed under both hosts, so it fails if only one stand-in was crawled | CARRIED |\n| D2 | docstring | \"every video stored for a host has `channel_name` equal to the `display_name` of that host's own channel row\" | :112 | Wrong or null names, and videos missing from the result (the whole dict must be equal) | CARRIED |\n| D3 | docstring | \"no video carries the other host's name\" | :112 | Cross-host name leakage: any `Beta Display` on an alpha key fails the equality | CARRIED |\n| D4 | docstring | \"every video stored for a host has `channel_url` equal to the `channel_url` of that host's own channel row\" | :113 | Wrong or null URLs, and missing videos | CARRIED |\n| D5 | docstring | \"no video carries the other host's URL\" | :113 | Cross-host URL leakage | CARRIED |\n| D6 | docstring | \"a missing node ... fails the test rather than skipping it\" | :73 | A skip or early return when node is absent | CARRIED |\n| D7 | docstring | \"a missing ... git ... fails the test\" | :76 | A skip when git is absent | CARRIED |\n| D8 | docstring | \"a missing ... dist ... fails the test\" | :74 | Running against a dist that does not exist | CARRIED |\n| D9 | docstring | \"a ... stale dist ... fails the test\" | :77 | A green run against a dist compiled before the source edit | CARRIED |\n| D10 | docstring | \"a nonzero node exit fails the test\" | :103 | Reading an empty or partial DB after node crashed | CARRIED |\n| N1 | name | \"crawl writes ... channel name\" | :112 | A crawl that stores no name, or a null name | CARRIED |\n| N2 | name | \"each host's own\" | :112 | Names attributed across hosts; the test has two hosts and one shared channel id | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. name-as-sentence (rules/testing.md) \u2014 tests/tmp/test_34_video_channel_name_wrong_instance_phase1.py:71\n   The name `test_crawl_writes_each_hosts_own_channel_name` says what should happen but not when: the shared-`channel_id` condition is missing. It also names only the channel name, although the test asserts the channel URL too (C2, :113). A failure at :113 is reported under a name that does not mention URLs.\n2. bounds (rules/testing.md) \u2014 tests/tmp/test_34_video_channel_name_wrong_instance_phase1.py:91\n   Only populated channel rows run. `toVideoRow` (videos-worker.ts:660-664) has fallbacks that no test reaches:\n   - a channels row with a null `display_name`, which falls back to the video's own `channel.displayName`;\n   - a null `channel_url`.\n3. normal-and-abnormal-paths (rules/testing.md) \u2014 tests/tmp/test_34_video_channel_name_wrong_instance_phase1.py:79-80\n   The stand-in videos never carry a `channel` object. In `toVideoRow` the URL prefers the video's `channel.url` over the channels row (videos-worker.ts:664), while the name prefers the channels row (videos-worker.ts:661-662). Nothing tests that precedence, so C2 is proven only on the path where the video has no channel URL of its own.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `code_under_test` lists tests/active/test_channel_names.py, but no file exists at that path. Nothing from it was assessed.\n2. engine/crawler/dist/videos-worker.js was not read. The claims were judged against src/videos-worker.ts (the `crawlVideos` entry point, `processInstance` and `toVideoRow`).\n3. `fixtures_path` was not supplied. The test uses only pytest's built-in `tmp_path` fixture, so there was no conftest to resolve.",
        "map": [
          {
            "id": "C1",
            "source": "must_prove",
            "clause": "each host's videos have `channel_name` = that host's channel `display_name`",
            "assertion": ":112",
            "excludes": "Looking up channel metadata by `channel_id` alone, which puts one host's display name on both hosts' videos. Both rows share id \"7\" (:91) and have different display names",
            "status": "CARRIED"
          },
          {
            "id": "C2",
            "source": "must_prove",
            "clause": "each host's videos have `channel_url` = that host's channel `channel_url`",
            "assertion": ":113",
            "excludes": "The same `channel_id`-only lookup, which gives both hosts' videos one URL. `url_a` and `url_b` differ (:84-85), and the stand-in videos have no `channel` object (:49, :79-80), so the stored URL has to come from the channels row",
            "status": "CARRIED"
          },
          {
            "id": "D1",
            "source": "docstring",
            "clause": "\"compiled `crawlVideos`, run under node against two local PeerTube stand-ins whose channels share channel_id \\\"7\\\"\"",
            "assertion": ":103, :112",
            "excludes": "A node run that fails or never runs `crawlVideos`. :112 also needs rows keyed under both hosts, so it fails if only one stand-in was crawled",
            "status": "CARRIED"
          },
          {
            "id": "D2",
            "source": "docstring",
            "clause": "\"every video stored for a host has `channel_name` equal to the `display_name` of that host's own channel row\"",
            "assertion": ":112",
            "excludes": "Wrong or null names, and videos missing from the result (the whole dict must be equal)",
            "status": "CARRIED"
          },
          {
            "id": "D3",
            "source": "docstring",
            "clause": "\"no video carries the other host's name\"",
            "assertion": ":112",
            "excludes": "Cross-host name leakage: any `Beta Display` on an alpha key fails the equality",
            "status": "CARRIED"
          },
          {
            "id": "D4",
            "source": "docstring",
            "clause": "\"every video stored for a host has `channel_url` equal to the `channel_url` of that host's own channel row\"",
            "assertion": ":113",
            "excludes": "Wrong or null URLs, and missing videos",
            "status": "CARRIED"
          },
          {
            "id": "D5",
            "source": "docstring",
            "clause": "\"no video carries the other host's URL\"",
            "assertion": ":113",
            "excludes": "Cross-host URL leakage",
            "status": "CARRIED"
          },
          {
            "id": "D6",
            "source": "docstring",
            "clause": "\"a missing node ... fails the test rather than skipping it\"",
            "assertion": ":73",
            "excludes": "A skip or early return when node is absent",
            "status": "CARRIED"
          },
          {
            "id": "D7",
            "source": "docstring",
            "clause": "\"a missing ... git ... fails the test\"",
            "assertion": ":76",
            "excludes": "A skip when git is absent",
            "status": "CARRIED"
          },
          {
            "id": "D8",
            "source": "docstring",
            "clause": "\"a missing ... dist ... fails the test\"",
            "assertion": ":74",
            "excludes": "Running against a dist that does not exist",
            "status": "CARRIED"
          },
          {
            "id": "D9",
            "source": "docstring",
            "clause": "\"a ... stale dist ... fails the test\"",
            "assertion": ":77",
            "excludes": "A green run against a dist compiled before the source edit",
            "status": "CARRIED"
          },
          {
            "id": "D10",
            "source": "docstring",
            "clause": "\"a nonzero node exit fails the test\"",
            "assertion": ":103",
            "excludes": "Reading an empty or partial DB after node crashed",
            "status": "CARRIED"
          },
          {
            "id": "N1",
            "source": "name",
            "clause": "\"crawl writes ... channel name\"",
            "assertion": ":112",
            "excludes": "A crawl that stores no name, or a null name",
            "status": "CARRIED"
          },
          {
            "id": "N2",
            "source": "name",
            "clause": "\"each host's own\"",
            "assertion": ":112",
            "excludes": "Names attributed across hosts; the test has two hosts and one shared channel id",
            "status": "CARRIED"
          }
        ],
        "map_problem": ""
      }
    ],
    "tests/tmp/test_34_video_channel_name_wrong_instance_phase2.py": [
      {
        "shape": "```\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\nBoth parametrisations (\"crawl\" and \"whitelist\") pass the seed control at line 73, then fail\nat line 76. There `_load_job(\"repair_video_channel_names\", \"repair-video-channel-names.py\")`\ncalls `spec.loader.exec_module` on engine/server/db/jobs/repair-video-channel-names.py.\nThat file does not exist yet, so it raises FileNotFoundError before `repair_channel_names`\nis reached.\n\nNOT ASSESSED\n1. `code_under_test` listed tests/active/test_channel_names.py (EDITED). That path does not\n   resolve in this worktree, so the edit was not read.\n2. `code_under_test` listed engine/server/db/jobs/repair-video-channel-names.py (NEW). It\n   does not exist yet, so `repair_channel_names` and `has_videos_fts` were not read. The stub\n   question was answered from the assertion form and the seed data alone:\n   - A stub returning 3 without writing fails at line 85, because REPAIRED differs from STORED\n     on v1, v2 and v7.\n   - A stub returning 0, or the old behaviour left in place, fails at line 80.\n   - A repair that joins on channel_id without instance_domain fails at line 85: channel 7\n     has a different name on each instance, so v1 and v2 would end up with the same name.\n   - A repair that writes empty or NULL display names fails at line 85 on v4 and v5.\n   - A repair that never commits fails at line 85, because the test reopens the connection.\n   - A second run that still reports changes fails at line 88.\n   The expected values are literals (lines 20-24), not worked out the way the code works\n   them out. The observable is read across seven rows and two database shapes, so no\n   anti_pattern entry in rules/shape.md applies. The test sits at ladder rung 1 (it calls the\n   function directly) with rung-3 row checks, which suits a function that edits a database.\n   There is no downshift.\n```",
        "claim": "CLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (19 clauses: 9 must_prove, 8 docstring, 2 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | videos with a foreign `channel_name` carry their own channel's `display_name` | :85 | matching on `channel_id` alone: channel 7 is on both instances, so v1 and v2 cannot both come out right | CARRIED |\n| C1b | must_prove | videos with a NULL `channel_name` are repaired the same way | :85 | a repair that only compares `channel_name != display_name`, which skips NULL (v7 would stay None) | CARRIED |\n| C1c | must_prove | already-correct rows are unchanged | :85, :80 | a repair that rewrites v3; the count of 3 at :80 also excludes a same-value rewrite being counted | CARRIED |\n| C1d | must_prove | rows whose channel has an empty display name are unchanged | :85 | writing `''` over v4's stored name | CARRIED |\n| C1e | must_prove | rows whose channel has a NULL display name are unchanged | :85 | writing NULL over v5's stored name | CARRIED |\n| C1f | must_prove | rows whose channel's display name is absent (no channel row) are unchanged | :85 | a correlated-subquery UPDATE with no match that NULLs v6 | CARRIED |\n| C1g | must_prove | the `channels` table is unchanged | :86 | any write to `channels`: the whole-row `SELECT *` snapshot catches it on either side | CARRIED |\n| C2a | must_prove | the repair returns the number of rows it changed | :80 | returning the table size (7), the matched-row count (4 with v3), or None | CARRIED |\n| C2b | must_prove | a second run returns 0 | :88 | an UPDATE without an \"is it already correct\" guard, which returns \u22653 again | CARRIED |\n| D1 | docstring | \"run in-process on a crawl.db-shaped and a whitelist.db-shaped temp database\" | :73 (params :44) | a shape that silently seeded nothing; the seed check runs on both params | CARRIED |\n| D2 | docstring | \"seeded with foreign, NULL, correct and unrepairable channel names\" | :73 | a seed that did not land as `STORED` describes | CARRIED |\n| D3 | docstring | \"It returns 3\" | :80 | any other count | CARRIED |\n| D4 | docstring | \"a fresh connection then reads v1, v2 and v7 \u2026 as their own channel's display name\" | :85 (reopen :83) | a repair that never commits | CARRIED |\n| D5 | docstring | \"v3, v4, v5, v6 \u2026 keep their stored names\" | :85 | writing to any of the four | CARRIED |\n| D6 | docstring | \"`channels` reads back identical to its pre-repair snapshot\" | :86 | any write to `channels` | CARRIED |\n| D7 | docstring | \"A second call returns 0 and leaves every name as the first call set it\" | :88, :94 | a second call that counts again, or rewrites and commits a name | CARRIED |\n| D8 | docstring | \"`has_videos_fts` is True on the whitelist shape and False on the crawl shape\" | :87 | a constant return; both params run | CARRIED |\n| N1 | name | \"sets each video to its own channel name\" (its own instance's channel) | :85 | a join on `channel_id` without `instance_domain` (v1 and v2) | CARRIED |\n| N2 | name | \"each video\" | :85 | nothing. The same line asserts that v4, v5 and v6 are NOT set, so \"each\" overclaims (see Recommendation 1) | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. name-as-sentence (rules/testing.md) \u2014 tests/tmp/test_34_video_channel_name_wrong_instance_phase2.py:69\n   `def test_repair_sets_each_video_to_its_own_channel_name(seeded_db):` says \"each video\", but the test expects v4, v5 and v6 to keep their stale names (`REPAIRED` at :24). The name also has no \"when\" clause, and it says nothing about the returned count or the idempotent second run, which are half of what the test asserts. A name like \"repair sets foreign or NULL names to the own-instance display name, leaves unrepairable rows, and is idempotent\" would let a failure read correctly without opening the file.\n2. bounds (rules/testing.md) \u2014 tests/tmp/test_34_video_channel_name_wrong_instance_phase2.py:22\n   The seed has no video with a NULL `channel_id`, which both schemas allow (`channel_id TEXT`, no NOT NULL). There is also no run on an empty `videos` table, where the repair should return 0. The NULL-name and empty or NULL display-name edges are covered.\n3. No rule covers this \u2014 tests/tmp/test_34_video_channel_name_wrong_instance_phase2.py:87\n   The test checks `has_videos_fts` on each shape but never reads `videos_fts` after the repair on the whitelist shape. The `videos_fts_au` trigger (sync-whitelist.py:279) or a rebuild is what would keep the full-text index in step with the repaired names. No clause in `must_prove` or the docstring claims this, so it is not a whole-claim defect. It is recorded because the test asserts the probe but not what the probe is for.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `code_under_test` path engine/server/db/jobs/repair-video-channel-names.py does not exist (marked NEW). I could not confirm the symbols `repair_channel_names` and `has_videos_fts`, or which inputs the job accepts. Bounds were judged from the two schemas: engine/crawler/schema.sql and engine/server/db/jobs/sync-whitelist.py:323-417.\n2. `code_under_test` path tests/active/test_channel_names.py (marked EDITED) does not exist, and no `test_channel_names*.py` exists anywhere under tests/. Its edits could not be read.",
        "body": "### devsecops-test-shape-auditor\n\n```\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\nBoth parametrisations (\"crawl\" and \"whitelist\") pass the seed control at line 73, then fail\nat line 76. There `_load_job(\"repair_video_channel_names\", \"repair-video-channel-names.py\")`\ncalls `spec.loader.exec_module` on engine/server/db/jobs/repair-video-channel-names.py.\nThat file does not exist yet, so it raises FileNotFoundError before `repair_channel_names`\nis reached.\n\nNOT ASSESSED\n1. `code_under_test` listed tests/active/test_channel_names.py (EDITED). That path does not\n   resolve in this worktree, so the edit was not read.\n2. `code_under_test` listed engine/server/db/jobs/repair-video-channel-names.py (NEW). It\n   does not exist yet, so `repair_channel_names` and `has_videos_fts` were not read. The stub\n   question was answered from the assertion form and the seed data alone:\n   - A stub returning 3 without writing fails at line 85, because REPAIRED differs from STORED\n     on v1, v2 and v7.\n   - A stub returning 0, or the old behaviour left in place, fails at line 80.\n   - A repair that joins on channel_id without instance_domain fails at line 85: channel 7\n     has a different name on each instance, so v1 and v2 would end up with the same name.\n   - A repair that writes empty or NULL display names fails at line 85 on v4 and v5.\n   - A repair that never commits fails at line 85, because the test reopens the connection.\n   - A second run that still reports changes fails at line 88.\n   The expected values are literals (lines 20-24), not worked out the way the code works\n   them out. The observable is read across seven rows and two database shapes, so no\n   anti_pattern entry in rules/shape.md applies. The test sits at ladder rung 1 (it calls the\n   function directly) with rung-3 row checks, which suits a function that edits a database.\n   There is no downshift.\n```\n\n### devsecops-test-claim-auditor\n\nCLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (19 clauses: 9 must_prove, 8 docstring, 2 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | videos with a foreign `channel_name` carry their own channel's `display_name` | :85 | matching on `channel_id` alone: channel 7 is on both instances, so v1 and v2 cannot both come out right | CARRIED |\n| C1b | must_prove | videos with a NULL `channel_name` are repaired the same way | :85 | a repair that only compares `channel_name != display_name`, which skips NULL (v7 would stay None) | CARRIED |\n| C1c | must_prove | already-correct rows are unchanged | :85, :80 | a repair that rewrites v3; the count of 3 at :80 also excludes a same-value rewrite being counted | CARRIED |\n| C1d | must_prove | rows whose channel has an empty display name are unchanged | :85 | writing `''` over v4's stored name | CARRIED |\n| C1e | must_prove | rows whose channel has a NULL display name are unchanged | :85 | writing NULL over v5's stored name | CARRIED |\n| C1f | must_prove | rows whose channel's display name is absent (no channel row) are unchanged | :85 | a correlated-subquery UPDATE with no match that NULLs v6 | CARRIED |\n| C1g | must_prove | the `channels` table is unchanged | :86 | any write to `channels`: the whole-row `SELECT *` snapshot catches it on either side | CARRIED |\n| C2a | must_prove | the repair returns the number of rows it changed | :80 | returning the table size (7), the matched-row count (4 with v3), or None | CARRIED |\n| C2b | must_prove | a second run returns 0 | :88 | an UPDATE without an \"is it already correct\" guard, which returns \u22653 again | CARRIED |\n| D1 | docstring | \"run in-process on a crawl.db-shaped and a whitelist.db-shaped temp database\" | :73 (params :44) | a shape that silently seeded nothing; the seed check runs on both params | CARRIED |\n| D2 | docstring | \"seeded with foreign, NULL, correct and unrepairable channel names\" | :73 | a seed that did not land as `STORED` describes | CARRIED |\n| D3 | docstring | \"It returns 3\" | :80 | any other count | CARRIED |\n| D4 | docstring | \"a fresh connection then reads v1, v2 and v7 \u2026 as their own channel's display name\" | :85 (reopen :83) | a repair that never commits | CARRIED |\n| D5 | docstring | \"v3, v4, v5, v6 \u2026 keep their stored names\" | :85 | writing to any of the four | CARRIED |\n| D6 | docstring | \"`channels` reads back identical to its pre-repair snapshot\" | :86 | any write to `channels` | CARRIED |\n| D7 | docstring | \"A second call returns 0 and leaves every name as the first call set it\" | :88, :94 | a second call that counts again, or rewrites and commits a name | CARRIED |\n| D8 | docstring | \"`has_videos_fts` is True on the whitelist shape and False on the crawl shape\" | :87 | a constant return; both params run | CARRIED |\n| N1 | name | \"sets each video to its own channel name\" (its own instance's channel) | :85 | a join on `channel_id` without `instance_domain` (v1 and v2) | CARRIED |\n| N2 | name | \"each video\" | :85 | nothing. The same line asserts that v4, v5 and v6 are NOT set, so \"each\" overclaims (see Recommendation 1) | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. name-as-sentence (rules/testing.md) \u2014 tests/tmp/test_34_video_channel_name_wrong_instance_phase2.py:69\n   `def test_repair_sets_each_video_to_its_own_channel_name(seeded_db):` says \"each video\", but the test expects v4, v5 and v6 to keep their stale names (`REPAIRED` at :24). The name also has no \"when\" clause, and it says nothing about the returned count or the idempotent second run, which are half of what the test asserts. A name like \"repair sets foreign or NULL names to the own-instance display name, leaves unrepairable rows, and is idempotent\" would let a failure read correctly without opening the file.\n2. bounds (rules/testing.md) \u2014 tests/tmp/test_34_video_channel_name_wrong_instance_phase2.py:22\n   The seed has no video with a NULL `channel_id`, which both schemas allow (`channel_id TEXT`, no NOT NULL). There is also no run on an empty `videos` table, where the repair should return 0. The NULL-name and empty or NULL display-name edges are covered.\n3. No rule covers this \u2014 tests/tmp/test_34_video_channel_name_wrong_instance_phase2.py:87\n   The test checks `has_videos_fts` on each shape but never reads `videos_fts` after the repair on the whitelist shape. The `videos_fts_au` trigger (sync-whitelist.py:279) or a rebuild is what would keep the full-text index in step with the repaired names. No clause in `must_prove` or the docstring claims this, so it is not a whole-claim defect. It is recorded because the test asserts the probe but not what the probe is for.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `code_under_test` path engine/server/db/jobs/repair-video-channel-names.py does not exist (marked NEW). I could not confirm the symbols `repair_channel_names` and `has_videos_fts`, or which inputs the job accepts. Bounds were judged from the two schemas: engine/crawler/schema.sql and engine/server/db/jobs/sync-whitelist.py:323-417.\n2. `code_under_test` path tests/active/test_channel_names.py (marked EDITED) does not exist, and no `test_channel_names*.py` exists anywhere under tests/. Its edits could not be read.",
        "map": [
          {
            "id": "C1a",
            "source": "must_prove",
            "clause": "videos with a foreign `channel_name` carry their own channel's `display_name`",
            "assertion": ":85",
            "excludes": "matching on `channel_id` alone: channel 7 is on both instances, so v1 and v2 cannot both come out right",
            "status": "CARRIED"
          },
          {
            "id": "C1b",
            "source": "must_prove",
            "clause": "videos with a NULL `channel_name` are repaired the same way",
            "assertion": ":85",
            "excludes": "a repair that only compares `channel_name != display_name`, which skips NULL (v7 would stay None)",
            "status": "CARRIED"
          },
          {
            "id": "C1c",
            "source": "must_prove",
            "clause": "already-correct rows are unchanged",
            "assertion": ":85, :80",
            "excludes": "a repair that rewrites v3; the count of 3 at :80 also excludes a same-value rewrite being counted",
            "status": "CARRIED"
          },
          {
            "id": "C1d",
            "source": "must_prove",
            "clause": "rows whose channel has an empty display name are unchanged",
            "assertion": ":85",
            "excludes": "writing `''` over v4's stored name",
            "status": "CARRIED"
          },
          {
            "id": "C1e",
            "source": "must_prove",
            "clause": "rows whose channel has a NULL display name are unchanged",
            "assertion": ":85",
            "excludes": "writing NULL over v5's stored name",
            "status": "CARRIED"
          },
          {
            "id": "C1f",
            "source": "must_prove",
            "clause": "rows whose channel's display name is absent (no channel row) are unchanged",
            "assertion": ":85",
            "excludes": "a correlated-subquery UPDATE with no match that NULLs v6",
            "status": "CARRIED"
          },
          {
            "id": "C1g",
            "source": "must_prove",
            "clause": "the `channels` table is unchanged",
            "assertion": ":86",
            "excludes": "any write to `channels`: the whole-row `SELECT *` snapshot catches it on either side",
            "status": "CARRIED"
          },
          {
            "id": "C2a",
            "source": "must_prove",
            "clause": "the repair returns the number of rows it changed",
            "assertion": ":80",
            "excludes": "returning the table size (7), the matched-row count (4 with v3), or None",
            "status": "CARRIED"
          },
          {
            "id": "C2b",
            "source": "must_prove",
            "clause": "a second run returns 0",
            "assertion": ":88",
            "excludes": "an UPDATE without an \"is it already correct\" guard, which returns \u22653 again",
            "status": "CARRIED"
          },
          {
            "id": "D1",
            "source": "docstring",
            "clause": "\"run in-process on a crawl.db-shaped and a whitelist.db-shaped temp database\"",
            "assertion": ":73 (params :44)",
            "excludes": "a shape that silently seeded nothing; the seed check runs on both params",
            "status": "CARRIED"
          },
          {
            "id": "D2",
            "source": "docstring",
            "clause": "\"seeded with foreign, NULL, correct and unrepairable channel names\"",
            "assertion": ":73",
            "excludes": "a seed that did not land as `STORED` describes",
            "status": "CARRIED"
          },
          {
            "id": "D3",
            "source": "docstring",
            "clause": "\"It returns 3\"",
            "assertion": ":80",
            "excludes": "any other count",
            "status": "CARRIED"
          },
          {
            "id": "D4",
            "source": "docstring",
            "clause": "\"a fresh connection then reads v1, v2 and v7 \u2026 as their own channel's display name\"",
            "assertion": ":85 (reopen :83)",
            "excludes": "a repair that never commits",
            "status": "CARRIED"
          },
          {
            "id": "D5",
            "source": "docstring",
            "clause": "\"v3, v4, v5, v6 \u2026 keep their stored names\"",
            "assertion": ":85",
            "excludes": "writing to any of the four",
            "status": "CARRIED"
          },
          {
            "id": "D6",
            "source": "docstring",
            "clause": "\"`channels` reads back identical to its pre-repair snapshot\"",
            "assertion": ":86",
            "excludes": "any write to `channels`",
            "status": "CARRIED"
          },
          {
            "id": "D7",
            "source": "docstring",
            "clause": "\"A second call returns 0 and leaves every name as the first call set it\"",
            "assertion": ":88, :94",
            "excludes": "a second call that counts again, or rewrites and commits a name",
            "status": "CARRIED"
          },
          {
            "id": "D8",
            "source": "docstring",
            "clause": "\"`has_videos_fts` is True on the whitelist shape and False on the crawl shape\"",
            "assertion": ":87",
            "excludes": "a constant return; both params run",
            "status": "CARRIED"
          },
          {
            "id": "N1",
            "source": "name",
            "clause": "\"sets each video to its own channel name\" (its own instance's channel)",
            "assertion": ":85",
            "excludes": "a join on `channel_id` without `instance_domain` (v1 and v2)",
            "status": "CARRIED"
          },
          {
            "id": "N2",
            "source": "name",
            "clause": "\"each video\"",
            "assertion": ":85",
            "excludes": "nothing. The same line asserts that v4, v5 and v6 are NOT set, so \"each\" overclaims (see Recommendation 1)",
            "status": "CARRIED"
          }
        ],
        "map_problem": ""
      }
    ],
    "tests/tmp/test_34_video_channel_name_wrong_instance_phase3.py": [
      {
        "shape": "SHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\nThe test should fail at line 77, `assert _matches(conn, \"Alphachan\") == {\"v1\", \"v7\"}`, because the result will be `{\"v7\"}`. `repair_channel_names` currently runs only `REPAIR_CHANNEL_NAMES_SQL`, with no rebuild. That UPDATE skips v1, since v1's `channel_name` already equals `'Alphachan'`, so the index keeps v1 under \"Betachan\". Meanwhile the `videos_fts_au` trigger moves v2 out of \"Alphachan\".\n\nNOT ASSESSED\n1. `code_under_test` listed `tests/active/test_channel_names.py`, which does not exist at that path. It was not read, and nothing in the verdict relies on it.\n2. The anti-pattern pass found no match in `shape.md`:\n   - The test reads no `.md` file (`doc-lint-grep`, `section-scoped-substring-grep`, `whole-file-source-name-grep`).\n   - No code constant is compared to an inline literal (`hardcoded-spec-mirror`).\n   - The expected sets at lines 77\u201379 are written out, not recomputed (`tautological-assertion`).\n   - Every post-repair assertion is positive (`absence-only-assertion`).\n   - The repair job and the FTS index sit between the seeded names and the video-id sets that are read back (`echoed-literal`).\n   - Two names are checked against an uneven seed (v1 and v7 under Alphachan; v2 and v3 under Betachan), and the count comes from `videos_fts_docsize`, which is stored apart from `videos` (`single-value-pin`).\n3. Ladder pass: the test runs at rung 1, calling `repair.repair_channel_names(conn)` directly at line 70. It asserts at rung 3, on rows read back from the database through a fresh connection at lines 75\u201381. That is the highest rung this database-state invariant supports. There is no downshift, so no comment is needed.\n4. Stub question: the test would fail against each of these wrong implementations:\n   - A no-op: line 77 gets `{\"v2\"}`.\n   - The current trigger-only UPDATE: line 77 gets `{\"v7\"}`.\n   - A rebuild that never commits: the reopen at line 75 reads back the stale index.\n   - A version that re-indexes only the changed rows: line 79 gets `(7, 8)`, because v8 is never indexed.\n\n   Lines 68\u201369 check that the seeded drift is really there before the repair runs, so the post-repair assertions cannot pass just because the setup never made the index go stale.",
        "claim": "CLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (13 clauses: 3 must_prove, 7 docstring, 3 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | own-name MATCH returns that channel's videos | :77, :78 | a repair that corrects `videos` but leaves the index holding v1's stale \"Betachan\" (v1 would be missing from Alphachan); a repair that skips NULL-named v7 | CARRIED |\n| C1b | must_prove | other instance's same-id name does not return them | :77, :78 | set equality means a stale index that still returns v1 for \"Betachan\", or v2 for \"Alphachan\", fails; a join on `channel_id` alone would put v2/v3 under Alphachan | CARRIED |\n| C2 | must_prove | `videos_fts` holds as many rows as `videos` | :79, :81 | a repair that relies on the per-row trigger alone, so v8 (empty display name, never updated) is never indexed: docsize 7 \u2260 8, and the integrity-check raises | CARRIED |\n| D1 | docstring | \"`videos_fts` has drifted \u2026 still holds v1's foreign name and has no row for v8\" | :68, :69 | a fixture whose index was never stale, which would let a no-op repair pass | CARRIED |\n| D2 | docstring | \"read through a fresh connection\" | :75 (reads at :77\u2013:81) | a repair whose rebuild never commits and so reads back as the stale index | CARRIED |\n| D3 | docstring | \"Alphachan\" returns exactly v1 and v7 | :77 | a missed v1/v7, or an extra row from the other instance | CARRIED |\n| D4 | docstring | \"Betachan\" returns exactly v2 and v3 | :78 | v1's stale entry lingering, or v2 left out | CARRIED |\n| D5 | docstring | \"neither name finds the other instance's same-id channel's videos\" | :77, :78 | same-id foreign matches, ruled out by the exact-set comparison | CARRIED |\n| D6 | docstring | `videos_fts_docsize` holds as many rows as `videos` (8) | :79 | an index missing v8 (7, 8) | CARRIED |\n| D7 | docstring | \"the FTS5 integrity-check passes\" | :81 | an index that disagrees with the `videos` content (raises DatabaseError) | CARRIED |\n| N1 | name | \"repaired fts\" (state after the repair) | :70 then :77\u2013:81 | assertions are taken after `repair_channel_names` runs, with the before-state pinned at :68\u2013:69 | CARRIED |\n| N2 | name | \"finds own name\" | :77, :78 | own-name MATCH missing the channel's videos | CARRIED |\n| N3 | name | \"not foreign name\" | :77, :78 | foreign same-id name still matching, ruled out by exact-set equality | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. bounds (rules/testing.md) \u2014 tests/tmp/test_34_video_channel_name_wrong_instance_phase3.py:17\u201319\n   The seed includes these edge rows:\n   - v4/v8: channel 8 with an empty `display_name`\n   - v5: channel 9 with a NULL `display_name`\n   - v6: orphan channel 404\n\n   Their only effect on the result is through the row count at :79. Nothing checks that they keep their stored name, which is the behaviour `repair_channel_names`'s docstring promises (\"Rows whose channel is missing or has no display name keep their stored name\"). A MATCH on \"Stalename\" and on \"Orphanname\" would cover these edges.\n2. normal-and-abnormal-paths (rules/testing.md) \u2014 tests/tmp/test_34_video_channel_name_wrong_instance_phase3.py:54\n   Only the success path is tested. No test covers how the repair behaves where it is expected to fail or do nothing, for example a crawl-shaped database without `videos_fts` (`has_videos_fts`) or an index that cannot be rebuilt. This is outside `must_prove`, so it does not block.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `code_under_test` listed tests/active/test_channel_names.py (EDITED), but the path does not exist and Glob found no `test_channel_names.py` under tests/. I could not check whether the suite covers the abnormal-path and bounds cases above somewhere else.",
        "body": "### devsecops-test-shape-auditor\n\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\nThe test should fail at line 77, `assert _matches(conn, \"Alphachan\") == {\"v1\", \"v7\"}`, because the result will be `{\"v7\"}`. `repair_channel_names` currently runs only `REPAIR_CHANNEL_NAMES_SQL`, with no rebuild. That UPDATE skips v1, since v1's `channel_name` already equals `'Alphachan'`, so the index keeps v1 under \"Betachan\". Meanwhile the `videos_fts_au` trigger moves v2 out of \"Alphachan\".\n\nNOT ASSESSED\n1. `code_under_test` listed `tests/active/test_channel_names.py`, which does not exist at that path. It was not read, and nothing in the verdict relies on it.\n2. The anti-pattern pass found no match in `shape.md`:\n   - The test reads no `.md` file (`doc-lint-grep`, `section-scoped-substring-grep`, `whole-file-source-name-grep`).\n   - No code constant is compared to an inline literal (`hardcoded-spec-mirror`).\n   - The expected sets at lines 77\u201379 are written out, not recomputed (`tautological-assertion`).\n   - Every post-repair assertion is positive (`absence-only-assertion`).\n   - The repair job and the FTS index sit between the seeded names and the video-id sets that are read back (`echoed-literal`).\n   - Two names are checked against an uneven seed (v1 and v7 under Alphachan; v2 and v3 under Betachan), and the count comes from `videos_fts_docsize`, which is stored apart from `videos` (`single-value-pin`).\n3. Ladder pass: the test runs at rung 1, calling `repair.repair_channel_names(conn)` directly at line 70. It asserts at rung 3, on rows read back from the database through a fresh connection at lines 75\u201381. That is the highest rung this database-state invariant supports. There is no downshift, so no comment is needed.\n4. Stub question: the test would fail against each of these wrong implementations:\n   - A no-op: line 77 gets `{\"v2\"}`.\n   - The current trigger-only UPDATE: line 77 gets `{\"v7\"}`.\n   - A rebuild that never commits: the reopen at line 75 reads back the stale index.\n   - A version that re-indexes only the changed rows: line 79 gets `(7, 8)`, because v8 is never indexed.\n\n   Lines 68\u201369 check that the seeded drift is really there before the repair runs, so the post-repair assertions cannot pass just because the setup never made the index go stale.\n\n### devsecops-test-claim-auditor\n\nCLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (13 clauses: 3 must_prove, 7 docstring, 3 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | own-name MATCH returns that channel's videos | :77, :78 | a repair that corrects `videos` but leaves the index holding v1's stale \"Betachan\" (v1 would be missing from Alphachan); a repair that skips NULL-named v7 | CARRIED |\n| C1b | must_prove | other instance's same-id name does not return them | :77, :78 | set equality means a stale index that still returns v1 for \"Betachan\", or v2 for \"Alphachan\", fails; a join on `channel_id` alone would put v2/v3 under Alphachan | CARRIED |\n| C2 | must_prove | `videos_fts` holds as many rows as `videos` | :79, :81 | a repair that relies on the per-row trigger alone, so v8 (empty display name, never updated) is never indexed: docsize 7 \u2260 8, and the integrity-check raises | CARRIED |\n| D1 | docstring | \"`videos_fts` has drifted \u2026 still holds v1's foreign name and has no row for v8\" | :68, :69 | a fixture whose index was never stale, which would let a no-op repair pass | CARRIED |\n| D2 | docstring | \"read through a fresh connection\" | :75 (reads at :77\u2013:81) | a repair whose rebuild never commits and so reads back as the stale index | CARRIED |\n| D3 | docstring | \"Alphachan\" returns exactly v1 and v7 | :77 | a missed v1/v7, or an extra row from the other instance | CARRIED |\n| D4 | docstring | \"Betachan\" returns exactly v2 and v3 | :78 | v1's stale entry lingering, or v2 left out | CARRIED |\n| D5 | docstring | \"neither name finds the other instance's same-id channel's videos\" | :77, :78 | same-id foreign matches, ruled out by the exact-set comparison | CARRIED |\n| D6 | docstring | `videos_fts_docsize` holds as many rows as `videos` (8) | :79 | an index missing v8 (7, 8) | CARRIED |\n| D7 | docstring | \"the FTS5 integrity-check passes\" | :81 | an index that disagrees with the `videos` content (raises DatabaseError) | CARRIED |\n| N1 | name | \"repaired fts\" (state after the repair) | :70 then :77\u2013:81 | assertions are taken after `repair_channel_names` runs, with the before-state pinned at :68\u2013:69 | CARRIED |\n| N2 | name | \"finds own name\" | :77, :78 | own-name MATCH missing the channel's videos | CARRIED |\n| N3 | name | \"not foreign name\" | :77, :78 | foreign same-id name still matching, ruled out by exact-set equality | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. bounds (rules/testing.md) \u2014 tests/tmp/test_34_video_channel_name_wrong_instance_phase3.py:17\u201319\n   The seed includes these edge rows:\n   - v4/v8: channel 8 with an empty `display_name`\n   - v5: channel 9 with a NULL `display_name`\n   - v6: orphan channel 404\n\n   Their only effect on the result is through the row count at :79. Nothing checks that they keep their stored name, which is the behaviour `repair_channel_names`'s docstring promises (\"Rows whose channel is missing or has no display name keep their stored name\"). A MATCH on \"Stalename\" and on \"Orphanname\" would cover these edges.\n2. normal-and-abnormal-paths (rules/testing.md) \u2014 tests/tmp/test_34_video_channel_name_wrong_instance_phase3.py:54\n   Only the success path is tested. No test covers how the repair behaves where it is expected to fail or do nothing, for example a crawl-shaped database without `videos_fts` (`has_videos_fts`) or an index that cannot be rebuilt. This is outside `must_prove`, so it does not block.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `code_under_test` listed tests/active/test_channel_names.py (EDITED), but the path does not exist and Glob found no `test_channel_names.py` under tests/. I could not check whether the suite covers the abnormal-path and bounds cases above somewhere else.",
        "map": [
          {
            "id": "C1a",
            "source": "must_prove",
            "clause": "own-name MATCH returns that channel's videos",
            "assertion": ":77, :78",
            "excludes": "a repair that corrects `videos` but leaves the index holding v1's stale \"Betachan\" (v1 would be missing from Alphachan); a repair that skips NULL-named v7",
            "status": "CARRIED"
          },
          {
            "id": "C1b",
            "source": "must_prove",
            "clause": "other instance's same-id name does not return them",
            "assertion": ":77, :78",
            "excludes": "set equality means a stale index that still returns v1 for \"Betachan\", or v2 for \"Alphachan\", fails; a join on `channel_id` alone would put v2/v3 under Alphachan",
            "status": "CARRIED"
          },
          {
            "id": "C2",
            "source": "must_prove",
            "clause": "`videos_fts` holds as many rows as `videos`",
            "assertion": ":79, :81",
            "excludes": "a repair that relies on the per-row trigger alone, so v8 (empty display name, never updated) is never indexed: docsize 7 \u2260 8, and the integrity-check raises",
            "status": "CARRIED"
          },
          {
            "id": "D1",
            "source": "docstring",
            "clause": "\"`videos_fts` has drifted \u2026 still holds v1's foreign name and has no row for v8\"",
            "assertion": ":68, :69",
            "excludes": "a fixture whose index was never stale, which would let a no-op repair pass",
            "status": "CARRIED"
          },
          {
            "id": "D2",
            "source": "docstring",
            "clause": "\"read through a fresh connection\"",
            "assertion": ":75 (reads at :77\u2013:81)",
            "excludes": "a repair whose rebuild never commits and so reads back as the stale index",
            "status": "CARRIED"
          },
          {
            "id": "D3",
            "source": "docstring",
            "clause": "\"Alphachan\" returns exactly v1 and v7",
            "assertion": ":77",
            "excludes": "a missed v1/v7, or an extra row from the other instance",
            "status": "CARRIED"
          },
          {
            "id": "D4",
            "source": "docstring",
            "clause": "\"Betachan\" returns exactly v2 and v3",
            "assertion": ":78",
            "excludes": "v1's stale entry lingering, or v2 left out",
            "status": "CARRIED"
          },
          {
            "id": "D5",
            "source": "docstring",
            "clause": "\"neither name finds the other instance's same-id channel's videos\"",
            "assertion": ":77, :78",
            "excludes": "same-id foreign matches, ruled out by the exact-set comparison",
            "status": "CARRIED"
          },
          {
            "id": "D6",
            "source": "docstring",
            "clause": "`videos_fts_docsize` holds as many rows as `videos` (8)",
            "assertion": ":79",
            "excludes": "an index missing v8 (7, 8)",
            "status": "CARRIED"
          },
          {
            "id": "D7",
            "source": "docstring",
            "clause": "\"the FTS5 integrity-check passes\"",
            "assertion": ":81",
            "excludes": "an index that disagrees with the `videos` content (raises DatabaseError)",
            "status": "CARRIED"
          },
          {
            "id": "N1",
            "source": "name",
            "clause": "\"repaired fts\" (state after the repair)",
            "assertion": ":70 then :77\u2013:81",
            "excludes": "assertions are taken after `repair_channel_names` runs, with the before-state pinned at :68\u2013:69",
            "status": "CARRIED"
          },
          {
            "id": "N2",
            "source": "name",
            "clause": "\"finds own name\"",
            "assertion": ":77, :78",
            "excludes": "own-name MATCH missing the channel's videos",
            "status": "CARRIED"
          },
          {
            "id": "N3",
            "source": "name",
            "clause": "\"not foreign name\"",
            "assertion": ":77, :78",
            "excludes": "foreign same-id name still matching, ruled out by exact-set equality",
            "status": "CARRIED"
          }
        ],
        "map_problem": ""
      }
    ],
    "tests/tmp/test_34_video_channel_name_wrong_instance_phase4.py": [
      {
        "shape": "```\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\nFails at line 41 on `assert bare.returncode == 2`. The job has no argparse\nparser and no `__main__` entry point: it only defines `REPAIR_CHANNEL_NAMES_SQL`,\n`_load_sync_whitelist`, `has_videos_fts` and `repair_channel_names`. Running it\nwith no arguments imports those definitions and exits 0, so the assertion sees\n0 where it expects 2.\n\nNOT ASSESSED\n1. `code_under_test` listed tests/active/test_channel_names.py, which does not\n   resolve (FileNotFoundError), so it was not read. The verdict rests on\n   test_path and engine/server/db/jobs/repair-video-channel-names.py only.\n2. engine/crawler/schema.sql (read at test_path:48) exists but was not read.\n   Whether its `channels` and `videos` columns match the INSERTs at\n   test_path:49-50 was not checked.\n```",
        "claim": "```\nCLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (16 clauses: 4 must_prove, 10 docstring, 2 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | without `--db` exits with return code 2 | :41 | a job that runs with a default path, or exits 0/1 | CARRIED |\n| C1b | must_prove | the exit is an argparse usage error | :42 | a hand-rolled exit 2, or a usage error about some other argument | CARRIED |\n| C2a | must_prove | with `--db` logs `channel names repaired rows=N` | :58, :64 | no log line, a reworded line, or one written only to stdout | CARRIED |\n| C2b | must_prove | N is the changed count | :58, :60, :64 | logging the total videos (7), the rows the WHERE matched including skipped ones, or a constant (the second run must log 0 while the first logs 3) | CARRIED |\n| D1 | docstring | \"run as a command, through `sys.executable`, against a crawl.db-shaped temp database seeded with foreign, NULL, correct and unrepairable channel names\" | :36, :48-50, :54 | a seed that did not land as written, which would make every later check meaningless | CARRIED |\n| D2 | docstring | \"Run with no arguments it exits 2\" | :41 | any other exit code | CARRIED |\n| D3 | docstring | \"argparse's usage error naming `--db` as required\" | :42 | an error that does not name `--db`, or does not call it required | CARRIED |\n| D4 | docstring | \"and logs no repair\" | :43 | a job that repairs something before it rejects the arguments | CARRIED |\n| D5 | docstring | \"Run with `--db` it exits 0\" | :57 | a non-zero exit on success | CARRIED |\n| D6 | docstring | \"logs `channel names repaired rows=3` exactly once\" | :58 | a wrong count, or the line logged twice (findall == [\"3\"]) | CARRIED |\n| D7 | docstring | \"v1, v2 and v7 read as their own channel's display name\" | :60 | a name copied from the same id on another instance, or a NULL left in place | CARRIED |\n| D8 | docstring | \"v3 to v6 keep their stored names\" | :60 | overwriting with '' or NULL, or touching the orphan row | CARRIED |\n| D9 | docstring | \"Run again it exits 0\" | :63 | a failure on the second run | CARRIED |\n| D10 | docstring | \"logs `channel names repaired rows=0`\" | :64 | counting matched rows instead of changed ones, or a fixed count | CARRIED |\n| N1 | name | \"cli requires db\" | :41, :42 | a CLI that accepts a missing `--db` | CARRIED |\n| N2 | name | \"logs changed count\" | :58, :60, :64 | a logged count that is not the number of rows changed | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. bounds (rules/testing.md) \u2014 tests/tmp/test_34_video_channel_name_wrong_instance_phase4.py:56\n   `--db` is only tested with a valid seeded database. These `--db` edges are never\n   tried: the flag given with no value, a path that does not exist (sqlite3.connect\n   would quietly create an empty file there), and a file that is not a database.\n2. normal-and-abnormal-paths (rules/testing.md) \u2014 tests/tmp/test_34_video_channel_name_wrong_instance_phase4.py:39\n   The failure path is tested only for a missing argument. Nothing covers how the job\n   fails when `--db` names a database the repair cannot run against, such as one with\n   no `videos` table.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `code_under_test` listed tests/active/test_channel_names.py, which does not resolve\n   in this worktree. Anything it adds was not read.\n2. engine/server/db/jobs/repair-video-channel-names.py as read has no argument parsing\n   and no logging. So whether `--db` is required, and where the `rows=N` line is\n   written, came from `must_prove` and the test, not from the code.\n```",
        "body": "### devsecops-test-shape-auditor\n\n```\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\nFails at line 41 on `assert bare.returncode == 2`. The job has no argparse\nparser and no `__main__` entry point: it only defines `REPAIR_CHANNEL_NAMES_SQL`,\n`_load_sync_whitelist`, `has_videos_fts` and `repair_channel_names`. Running it\nwith no arguments imports those definitions and exits 0, so the assertion sees\n0 where it expects 2.\n\nNOT ASSESSED\n1. `code_under_test` listed tests/active/test_channel_names.py, which does not\n   resolve (FileNotFoundError), so it was not read. The verdict rests on\n   test_path and engine/server/db/jobs/repair-video-channel-names.py only.\n2. engine/crawler/schema.sql (read at test_path:48) exists but was not read.\n   Whether its `channels` and `videos` columns match the INSERTs at\n   test_path:49-50 was not checked.\n```\n\n### devsecops-test-claim-auditor\n\n```\nCLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (16 clauses: 4 must_prove, 10 docstring, 2 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | without `--db` exits with return code 2 | :41 | a job that runs with a default path, or exits 0/1 | CARRIED |\n| C1b | must_prove | the exit is an argparse usage error | :42 | a hand-rolled exit 2, or a usage error about some other argument | CARRIED |\n| C2a | must_prove | with `--db` logs `channel names repaired rows=N` | :58, :64 | no log line, a reworded line, or one written only to stdout | CARRIED |\n| C2b | must_prove | N is the changed count | :58, :60, :64 | logging the total videos (7), the rows the WHERE matched including skipped ones, or a constant (the second run must log 0 while the first logs 3) | CARRIED |\n| D1 | docstring | \"run as a command, through `sys.executable`, against a crawl.db-shaped temp database seeded with foreign, NULL, correct and unrepairable channel names\" | :36, :48-50, :54 | a seed that did not land as written, which would make every later check meaningless | CARRIED |\n| D2 | docstring | \"Run with no arguments it exits 2\" | :41 | any other exit code | CARRIED |\n| D3 | docstring | \"argparse's usage error naming `--db` as required\" | :42 | an error that does not name `--db`, or does not call it required | CARRIED |\n| D4 | docstring | \"and logs no repair\" | :43 | a job that repairs something before it rejects the arguments | CARRIED |\n| D5 | docstring | \"Run with `--db` it exits 0\" | :57 | a non-zero exit on success | CARRIED |\n| D6 | docstring | \"logs `channel names repaired rows=3` exactly once\" | :58 | a wrong count, or the line logged twice (findall == [\"3\"]) | CARRIED |\n| D7 | docstring | \"v1, v2 and v7 read as their own channel's display name\" | :60 | a name copied from the same id on another instance, or a NULL left in place | CARRIED |\n| D8 | docstring | \"v3 to v6 keep their stored names\" | :60 | overwriting with '' or NULL, or touching the orphan row | CARRIED |\n| D9 | docstring | \"Run again it exits 0\" | :63 | a failure on the second run | CARRIED |\n| D10 | docstring | \"logs `channel names repaired rows=0`\" | :64 | counting matched rows instead of changed ones, or a fixed count | CARRIED |\n| N1 | name | \"cli requires db\" | :41, :42 | a CLI that accepts a missing `--db` | CARRIED |\n| N2 | name | \"logs changed count\" | :58, :60, :64 | a logged count that is not the number of rows changed | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. bounds (rules/testing.md) \u2014 tests/tmp/test_34_video_channel_name_wrong_instance_phase4.py:56\n   `--db` is only tested with a valid seeded database. These `--db` edges are never\n   tried: the flag given with no value, a path that does not exist (sqlite3.connect\n   would quietly create an empty file there), and a file that is not a database.\n2. normal-and-abnormal-paths (rules/testing.md) \u2014 tests/tmp/test_34_video_channel_name_wrong_instance_phase4.py:39\n   The failure path is tested only for a missing argument. Nothing covers how the job\n   fails when `--db` names a database the repair cannot run against, such as one with\n   no `videos` table.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `code_under_test` listed tests/active/test_channel_names.py, which does not resolve\n   in this worktree. Anything it adds was not read.\n2. engine/server/db/jobs/repair-video-channel-names.py as read has no argument parsing\n   and no logging. So whether `--db` is required, and where the `rows=N` line is\n   written, came from `must_prove` and the test, not from the code.\n```",
        "map": [
          {
            "id": "C1a",
            "source": "must_prove",
            "clause": "without `--db` exits with return code 2",
            "assertion": ":41",
            "excludes": "a job that runs with a default path, or exits 0/1",
            "status": "CARRIED"
          },
          {
            "id": "C1b",
            "source": "must_prove",
            "clause": "the exit is an argparse usage error",
            "assertion": ":42",
            "excludes": "a hand-rolled exit 2, or a usage error about some other argument",
            "status": "CARRIED"
          },
          {
            "id": "C2a",
            "source": "must_prove",
            "clause": "with `--db` logs `channel names repaired rows=N`",
            "assertion": ":58, :64",
            "excludes": "no log line, a reworded line, or one written only to stdout",
            "status": "CARRIED"
          },
          {
            "id": "C2b",
            "source": "must_prove",
            "clause": "N is the changed count",
            "assertion": ":58, :60, :64",
            "excludes": "logging the total videos (7), the rows the WHERE matched including skipped ones, or a constant (the second run must log 0 while the first logs 3)",
            "status": "CARRIED"
          },
          {
            "id": "D1",
            "source": "docstring",
            "clause": "\"run as a command, through `sys.executable`, against a crawl.db-shaped temp database seeded with foreign, NULL, correct and unrepairable channel names\"",
            "assertion": ":36, :48-50, :54",
            "excludes": "a seed that did not land as written, which would make every later check meaningless",
            "status": "CARRIED"
          },
          {
            "id": "D2",
            "source": "docstring",
            "clause": "\"Run with no arguments it exits 2\"",
            "assertion": ":41",
            "excludes": "any other exit code",
            "status": "CARRIED"
          },
          {
            "id": "D3",
            "source": "docstring",
            "clause": "\"argparse's usage error naming `--db` as required\"",
            "assertion": ":42",
            "excludes": "an error that does not name `--db`, or does not call it required",
            "status": "CARRIED"
          },
          {
            "id": "D4",
            "source": "docstring",
            "clause": "\"and logs no repair\"",
            "assertion": ":43",
            "excludes": "a job that repairs something before it rejects the arguments",
            "status": "CARRIED"
          },
          {
            "id": "D5",
            "source": "docstring",
            "clause": "\"Run with `--db` it exits 0\"",
            "assertion": ":57",
            "excludes": "a non-zero exit on success",
            "status": "CARRIED"
          },
          {
            "id": "D6",
            "source": "docstring",
            "clause": "\"logs `channel names repaired rows=3` exactly once\"",
            "assertion": ":58",
            "excludes": "a wrong count, or the line logged twice (findall == [\"3\"])",
            "status": "CARRIED"
          },
          {
            "id": "D7",
            "source": "docstring",
            "clause": "\"v1, v2 and v7 read as their own channel's display name\"",
            "assertion": ":60",
            "excludes": "a name copied from the same id on another instance, or a NULL left in place",
            "status": "CARRIED"
          },
          {
            "id": "D8",
            "source": "docstring",
            "clause": "\"v3 to v6 keep their stored names\"",
            "assertion": ":60",
            "excludes": "overwriting with '' or NULL, or touching the orphan row",
            "status": "CARRIED"
          },
          {
            "id": "D9",
            "source": "docstring",
            "clause": "\"Run again it exits 0\"",
            "assertion": ":63",
            "excludes": "a failure on the second run",
            "status": "CARRIED"
          },
          {
            "id": "D10",
            "source": "docstring",
            "clause": "\"logs `channel names repaired rows=0`\"",
            "assertion": ":64",
            "excludes": "counting matched rows instead of changed ones, or a fixed count",
            "status": "CARRIED"
          },
          {
            "id": "N1",
            "source": "name",
            "clause": "\"cli requires db\"",
            "assertion": ":41, :42",
            "excludes": "a CLI that accepts a missing `--db`",
            "status": "CARRIED"
          },
          {
            "id": "N2",
            "source": "name",
            "clause": "\"logs changed count\"",
            "assertion": ":58, :60, :64",
            "excludes": "a logged count that is not the number of rows changed",
            "status": "CARRIED"
          }
        ],
        "map_problem": ""
      }
    ]
  },
  "refactors": "<refactors>\nnone\n</refactors>\n\n<left_out>\nengine/crawler/src/videos-worker.ts and dist/videos-worker.js: the four copies of the per-host error-classification catch block in processTagInstance/processCommentsInstance, the three identical groupByInstance* functions, the three identical *WorkerLoop functions and the unused TAGS_CONCURRENCY constant were all there before this build and are outside the lines it changed. Folding them together would grow the build past what was approved, so they belong in their own issue.\nengine/crawler/dist/videos-worker.js: I made no source edit, because every edit to src has to be mirrored in the dist by hand. I have no shell to run `npm run build`, so I could not confirm that tsc output would match. I checked by grep that src and dist call channelMetaKey at the same two sites and define the same helper.\nengine/server/db/jobs/repair-video-channel-names.py: `int(changed)` wraps a `rowcount` that is already an int. Removing the wrapper would be cosmetic, and no probe run backs it, so I left the file exactly as it passed Phases 2\u20134.\ntests/tmp: the leftover probe files (probe_34_phase2_seed.py, probe_34_phase3_impl.py, probe_34_phase4_impl.py, probe_34_phase4_cli.py, probe_34_fts_rowcount.py, probe_34_urls.py, test_probe_34_phase2.py, test_probe_34_phase3.py, test_probe_34_phase4_selfcheck.py, test_probe_34_urls.py) are not part of any phase and need deleting. I have no delete tool. The four test_probe_* files will be collected if tests/tmp is ever run as a directory.\ntests/active/test_channel_names.py: it still does not exist. The gating checkpoints are only in tests/tmp/test_34_video_channel_name_wrong_instance_phase1\u20134.py, and moving them to the permanent location is the workflow's job, not this pass's.\nStep prompt: the \"What the pass is measured against\" section arrived as a literal `{rat_tail_rules}` placeholder, so I checked the pass against the role's rat-tail rule instead. The one simplification this build added (the executescript commit in repair_channel_names) already carries a rat-tail comment naming its limit and upgrade path.\n</left_out>\n\n<needs_fresh_red>\nnone\n</needs_fresh_red>\n\n<observation>\nThis build's code is already minimal and matches the style of the files it landed in, so I made no refactors: the channelMetaKey change is the same in src and dist (checked by grep) and the repair job needs no restructuring.\n</observation>"
}
```
dev-flow:state -->

## 2026-09-27 - Step 0 - baseline

Resolved paths: {
  "active": "tests/active",
  "working": "tests/tmp",
  "plans": "docs/project/plans",
  "delete_me": "delete_me",
  "archive": "tests/archive",
  "project_dir": "/home/enduser/code/PeerTube-browser/.worktrees/34",
  "record": "tests/last_test_validation.json",
  "output": "tests/last_test_output.txt"
}

Pre-build suite exited 0. Baseline variant: False.

```
selected 1 of 20 test groups (19 unchanged):
  test_search_fusion.py — no map entry
  test_search_fusion.py  10 passed                              1.9s
  ---------------------
  total                  10 passed                              2.1s wall, 1 lane

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

## 2026-09-27 - Step 1 - Gather requirements

Approved by the operator.

### requirements

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

### conflicts

The brief says the repair must "rebuild videos_fts", but whitelist.db already has an AFTER UPDATE trigger (sync-whitelist.py:279-284) that keeps videos_fts in step with any UPDATE of channel_name. A plain UPDATE would therefore already leave the index correct. The rebuild is kept anyway: it follows the file's drop-triggers/bulk-update/rebuild pattern, and a single bulk rebuild is cheaper than ~660k per-row trigger writes. This is noted so the design doesn't treat the rebuild as the thing that makes the index correct.
The brief says to "reuse the existing FTS rebuild helper the sync job uses", but that helper lives in engine/server/db/jobs/sync-whitelist.py, whose hyphenated name cannot be imported normally. Reusing it needs an importlib-style load, or moving the helpers into an importable module. The design has to pick one.
The brief says to repair "both databases" (crawl.db and whitelist.db), but the updater merges videos INSERT_ONLY into prod, so a separate prod whitelist.db copy would keep the wrong names. The operator resolved this: the runbook tells the operator to run the repair on every whitelist.db copy, prod included.
Channel-meta key normalisation: channelMeta is built from channels.instance_domain as stored, while processInstance looks up with host.toLowerCase(). If stored domains are not already lowercase, a host-aware key built naively would miss every lookup and fall back to the payload name. The design must make both sides use the same form.

## 2026-09-27 - Step 2 - Develop a solution

Approved by the operator.

### initial_solution

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

### conflicts

none

## 2026-09-27 - Step 3 - Identify every file, function and doc affected

Recorded ungated, at the operator direction.

### impacts


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


### docs_checklist

<doc path="DATA_BUILD.md">
Add a new section after "## 2) Filter to JoinPeerTube whitelist" (which ends at line 158, before "## 3) Build embeddings") covering the one-off repair of `videos.channel_name`:
- A one-line reason for the repair.
- It is a migration of shared databases: run it on main after merge only, never from a worktree.
- Run it outside an updater cycle, with the Engine idle, because the FTS rebuild holds the write lock.
- The order:
  1. Merge.
  2. `python3 engine/server/db/jobs/repair-video-channel-names.py --db engine/crawler/data/crawl.db`.
  3. The same command with `--db` on every `whitelist.db`, including prod, because merges are `INSERT_ONLY`.
  4. The operator follow-up, using the flags this file already documents: `build-video-embeddings.py --db-path engine/server/db/whitelist.db --force`, then `build-ann-index.py` with `--db-path`, `--index-path`, `--meta-path`, and `--gpu` or `--cpu`, then `precompute-similar-ann.py` with `--db`, `--index`, `--out`, `--reset`, and `--gpu` or `--cpu`.

Two cautions:
- The plan-17 reference in the requirements names `docs/project/plans/17-stable-ann-ids.md`, but that file does not exist in this tree. `docs/project/plans/` holds only `01-34-*`, and the related issue is `docs/project/issues/08-stable-ann-ids.md`. The runbook should cite something that exists, or name "plan 17" without a path.
- The file already points at `engine/server/db/jobs/UPDATER_WORKER.md` (line 30), but the doc lives in `engine/server/db/jobs/docs/`. This is a pre-existing broken reference, worth fixing only if that line is touched.
</doc><doc path="docs/project/issues/34-video-channel-name-wrong-instance.md">
At harvest:
- Tick the acceptance criteria.
- Set `Status: bug, complete`.
- Move the file to `docs/project/issues/archive/`, per `docs/project/triage-labels.md`.
- Record that the repair and the re-embed are still owed by the operator on main.
- Record the correction that the crawl slug was already host-correct: only `displayName` and the `channelUrl` fallback were wrong.
</doc><doc path="engine/server/db/jobs/docs/UPDATER_WORKER.md">
Optional. A one-line note that `videos` and `channels` merge `INSERT_ONLY`, so data corrections to existing prod rows, such as `repair-video-channel-names.py`, must be run against the prod `whitelist.db` directly, and not while an updater cycle holds the DB. No behaviour documented there changes, so leave the file untouched if the DATA_BUILD section says this already.
</doc>

### highest_risk

engine/server/db/jobs/repair-video-channel-names.py: it rewrites shared, live databases, including prod `whitelist.db`, while the Engine's `/api/video` write-back and the updater merge also write to them. Because the reused helpers call `executescript`, the UPDATE is committed before the rebuild, and the rebuild needs its own explicit `commit()` or it is lost on close. It is also the first production code under `engine/` to load a sibling job through importlib, so it now depends at load on `engine/crawler/schema.sql` and the server tree.
tests/active/test_channel_names.py (the crawl test): it must fail rather than skip, yet it depends on more than the existing host test does: node, a fresh `dist/videos-worker.js`, AND `engine/crawler/node_modules/better-sqlite3`. I could not confirm `node_modules` exists: the read was refused as outside the project, which suggests a symlink. The test also relies on the https attempt failing with a TLS error rather than a no-network code (which would divert to curl), and it proves the `channel_url` part only if the fake payload has no `channel.url`.
engine/crawler/dist/videos-worker.js: production runs this file, not the source (the updater runs `dist/videos-cli.js`), so the fix does nothing until it is rebuilt and committed. `tsc` recompiles all of `src/`, so any other dist file already out of step with its source will change too. That contradicts the plan's "only that dist file should differ" and needs checking in the diff.

## 2026-09-27 - Step 4 - Reassess the implementation plan (pass 1)

Pass 1. New impacts: none.

I opened the files behind every material inventory entry: `videos-worker.ts` (the map build at 163-172, the lookup at 285-291, `processChannel`, `crawlChannelVideos`, `fetchPage`/`buildChannelVideosUrl`, `toVideoRow`, `groupByInstance`), `db.ts` (`listChannelsWithVideos`, `prepareVideoProgress`), `http.ts`, `schema.sql`, `sync-whitelist.py` (preamble, schema parse, FTS helpers, `ensure_content_schema`, `rebuild_content_tables`, `main`), `recompute-popularity.py`, `server_config.py:363`, `merge_rules.json`, `handlers/video.py:302-343` and `test_host_normalisation.py`. Every entry I checked matches the file. The inventory's two corrections to the plan are right. The slug comes from `item.channelName` first (line 433). The neighbours' `--db` default is `engine/server/db/whitelist.db`, not the crawl DB. Neither correction changes the design. The first actually makes the case for a required `--db` stronger. I found nothing the inventory is missing.
<question id="1">
Yes. The bug is only the key at line 165 and the lookup at line 289. `prepareVideoProgress` inserts `channel.instance_domain` verbatim (db.ts:1342), and `groupByInstance` groups on that value (videos-worker.ts:710). So a composite key built as `lower(instance_domain) + "/" + channel_id` on both sides always resolves to the right host's entry. `processChannel` (450-451) and `toVideoRow` (660-664) already read everything from that single `meta`. For the repair, `channels` has `PRIMARY KEY (channel_id, instance_domain)` in both shapes (schema.sql:26, sync-whitelist.py:348), so the correlated-subquery UPDATE is well defined and indexed. `rebuild_videos_fts` issues `'rebuild'` and returns the count (309-320). The helpers exist with the names and behaviour the plan assumes.
</question>
<question id="2">
- **Every re-crawl self-corrects.** Once the rebuilt dist ships, every re-crawl of `crawl.db` fixes `channel_name`/`channel_url` on its own through the ON CONFLICT upsert, and updater crawls write correct names into staging.
- **Existing rows need the one-off job.** Existing rows in each `whitelist.db` are fixed only by the job, because `merge_rules.json` makes `videos` and `channels` INSERT_ONLY.
- **Operational load on the FTS path.** The job drops the triggers and runs a full `rebuild` of `videos_fts` on every run. That write holds the lock for a long time on prod. During it, `handlers/video.py`'s write-back (under `server.db_lock`, inside a try) can hit `database is locked`, and a concurrent updater merge can fail.
- **No longer atomic.** `executescript` commits: the UPDATE is committed by `create_videos_fts_triggers` before the rebuild runs.
- **Code shape.** The job becomes the first production module to load a sibling job through `importlib`, so its load now depends on `engine/crawler/schema.sql`, which `sync-whitelist.py` parses at import (lines 36, 92-96).
- **Test suite.** It gains a stricter environment requirement: node + `node_modules` (better-sqlite3) + a fresh dist.
</question>
<question id="3">
- **Commit the rebuilt dist.** `dist/videos-worker.js` must be rebuilt and committed with the source. Production runs the dist through `updater-worker.py` and `run-dataset-build.sh`, and without it the fix never runs.
- **Run the repair on every copy.** The job must run against `crawl.db` and every `whitelist.db` copy, prod included, outside an updater cycle and ideally with the Engine idle.
- **Commit explicitly after the rebuild.** On the FTS path the job must call `conn.commit()` explicitly after `rebuild_videos_fts`. Under the default legacy isolation, the `INSERT ... 'rebuild'` opens an implicit transaction, which would otherwise be rolled back on close.
- **Read the count early.** `rowcount` must be read before any `executescript`.
- **Re-embed.** The operator must run the re-embed, ANN build and precompute to fix semantic similarity.
- **Other tests unaffected.** `test_host_normalisation.py` stays green: staleness is by commit time, and rebuilding only makes dist newer.
</question>
<question id="4">
- **Crawler.** Only which channel entry a video row's display name and fallback URL come from changes, now the same host's instead of whichever same-id row was listed last. The name precedence (crawl list first, payload second) and the URL precedence (payload `channel.url` first) are unchanged. So is the slug, which already came from the per-host progress row.
- **Stored data.** After the repair, existing `videos.channel_name` values change to the owning channel's `display_name`. Rows with an empty or NULL `display_name` or no channel row keep their current value.
- **Search.** Lexical search on `channel_name` returns the correct channel's videos.
- **Unchanged.** Nothing else in the crawler, the Engine API, the frontend or the pipeline changes.
</question>

New impacts:
none

Inventory entries that did not hold up:
- **engine/crawler/src/videos-worker.ts, fetchPage() entry: the TLS failure.** The entry says the https attempt against a plain-HTTP server fails at once with EPROTO / ERR_SSL_WRONG_VERSION_NUMBER. That is runtime behaviour the tree cannot confirm. What the code shows is this. `isNoNetworkError` (http.ts:37-53) lists only ENETUNREACH, EHOSTUNREACH, ENOTFOUND, EAI_AGAIN, ECONNREFUSED, ETIMEDOUT and ETIMEOUT, so a TLS error goes neither to curl nor to `NoNetworkError`. An abort by the per-attempt `AbortController` (http.ts:61-62) also goes the http way. So the fallback happens whether the handshake fails fast or hangs until `timeoutMs`; only the runtime differs. It is fast if `BaseHTTPRequestHandler` finds a newline byte in the ClientHello and answers 400. The supported_groups extension id 0x000a makes that likely but not certain.
- **tests/active/test_channel_names.py entry: `node_modules`.** Whether `engine/crawler/node_modules` exists in this worktree is still unconfirmed, as the entry itself says.
- **Every other entry** I checked held up against its file.

Conflicts: none

Recommendations: 1. **Seed a video with no `channels` row in both repair fixtures.** The inventory already flags this. The plan's list of seeded rows leaves it out, but the requirements name the case. Cost: one extra insert per fixture and one assertion.
2. **Pass an explicit `timeoutMs` of about 2000-3000 ms in the crawl test,** not something very short. The same `timeoutMs` bounds the http leg, which is the one that must succeed. If the https handshake hangs rather than fails, each channel costs at most one timeout. Cost: up to a few seconds of test time in the worst case, and nothing in production.
3. **Write the explicit `conn.commit()` after `rebuild_videos_fts`, and read `rowcount` before the first `executescript`, into the implementation phase as named steps.** Both are easy to miss, and missing either one silently loses the rebuild or misreports the count. Cost: none beyond two lines.
4. **Use sync-whitelist's `"%(levelname)s: %(message)s"` log format** and a `rows=%d` suffix, e.g. `channel names repaired rows=%d`, so the CLI test can parse the count reliably. Cost: none. It is a choice between two existing neighbour styles.
5. **In the runbook step, say to run the job outside an updater cycle and with the Engine idle or stopped for the prod `whitelist.db`.** Cost: a short maintenance window on prod for the length of one full FTS rebuild.

## 2026-09-27 - Step 5 - Draft the initial implementation

Recorded ungated, at the operator direction.

### draft

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

## 2026-09-27 - Step 6 - Design the phase breakdown

Approved by the operator.

#### Phase 1 - Crawler keys channel metadata by host and id [code]

**Files touched.** engine/crawler/src/videos-worker.ts (EDITED), engine/crawler/dist/videos-worker.js (EDITED), tests/active/test_channel_names.py (NEW)

**Checkpoint.** `test_crawl_writes_each_hosts_own_channel_name(tmp_path)` in the new `tests/active/test_channel_names.py`. Seam: the compiled `crawlVideos` exported by `engine/crawler/dist/videos-worker.js`. The test runs it under `node --input-type=module -e` with `cwd=engine/crawler` against two stdlib `ThreadingHTTPServer`s on `127.0.0.1` ephemeral ports and a temp `crawl.db` built from `engine/crawler/schema.sql`. Both channels rows share `channel_id` "7" and have different display names and URLs. The test asserts exact equality of `{(instance_domain, video_id): (channel_name, channel_url)}` read from `videos`. Harness precedent: `test_host_normalisation.py::test_crawler_dist_returns_pinned_values`. The test copies its `_git` / `_dist_is_stale` gates and `BUILD_HINT`. A missing node or git, a missing or stale dist, or a nonzero node exit fails the test and never skips it. On today's code the test fails deterministically, because the id-only map keeps one entry for "7".

**Intent.** `crawlVideos` in `engine/crawler/src/videos-worker.ts` (and its committed `dist/videos-worker.js`) looks up channel metadata by lowercased host plus channel id. As a result, each host's crawled videos carry that host's own channel metadata, even when a channel id repeats across instances.

- C1 - Each host's crawled videos have `channel_name` equal to the `display_name` of the channel on that same host.
- C2 - Each host's crawled videos have `channel_url` equal to the `channel_url` of the channel on that same host.

**Outcome.** _pending_

#### Phase 2 - Repair function corrects channel names [code]

**Files touched.** engine/server/db/jobs/repair-video-channel-names.py (NEW), tests/active/test_channel_names.py (EDITED)

**Checkpoint.** `test_repair_sets_each_video_to_its_own_channel_name(jobs, seeded_db)`. Seam: the in-process function `repair_channel_names(conn)` in `repair-video-channel-names.py`. The job is loaded with the `_load_job` importlib loader copied from `test_host_normalisation.py`. The fixture `seeded_db` is parametrised over the `crawl` shape (`schema.sql`) and the `whitelist` shape (`ensure_content_schema` from the loaded `sync-whitelist.py`). `_seed` loads the v1–v7 / channels 7, 8, 9 table from the draft. Asserts: the returned count is 3; the `video_id -> channel_name` dict equals the expected column; `channels` equals its pre-repair snapshot; a second call returns 0 and leaves the dict unchanged; `has_videos_fts` is True exactly for the whitelist parameter. Every DB is under `tmp_path`.

**Intent.** The new job `engine/server/db/jobs/repair-video-channel-names.py` exposes `repair_channel_names`. It sets each video's `channel_name` to the non-empty `display_name` of its own `(channel_id, instance_domain)` channel and returns how many rows it changed.

- C1 - After a repair, videos with a foreign or NULL `channel_name` carry their own channel's `display_name`. Already-correct rows, rows whose channel has an empty, NULL or absent display name, and the `channels` table are unchanged.
- C2 - The repair returns the number of rows it changed, and a second run returns 0.

**Outcome.** _pending_

#### Phase 3 - "`. Asserts: `Alphachan` gives {v1, v7} and `Betachan` gives {v2, v3}, so v1's stale foreign name is gone; `COUNT(*)` on `videos_fts` equals `COUNT(*)` on `videos` (7).</checkpoint>
<name>Repair rebuilds the search index [code]

**Files touched.** engine/server/db/jobs/repair-video-channel-names.py (EDITED), tests/active/test_channel_names.py (EDITED)

**Checkpoint.** `test_repaired_fts_finds_own_name_not_foreign_name(jobs, tmp_path)`. Seam: the `videos_fts` table of a whitelist-shape temp DB. The DB is created with `ensure_content_schema`, seeded with stale names (so the index holds them), and then repaired through `repair_channel_names`. The test queries `SELECT v.video_id FROM videos_fts JOIN videos v ON v.rowid = videos_fts.rowid WHERE videos_fts MATCH ?` with `channel_name : "<name>"`. Asserts: `Alphachan` gives {v1, v7} and `Betachan` gives {v2, v3}, so v1's stale foreign name is gone; `COUNT(*)` on `videos_fts` equals `COUNT(*)` on `videos` (7).

**Intent.** On a database that has `videos_fts`, the repair runs between `sync-whitelist.py`'s trigger drop and recreate and then rebuilds the index, so full-text search reflects the corrected channel names in full.

- C1 - After the repair, a `channel_name` MATCH for a channel's own name returns that channel's videos, and a MATCH for the other instance's same-id name does not return them.
- C2 - After the repair, `videos_fts` holds as many rows as `videos`.

**Outcome.** _pending_

#### Phase 4 - Repair CLI [code]

**Files touched.** engine/server/db/jobs/repair-video-channel-names.py (EDITED), tests/active/test_channel_names.py (EDITED)

**Checkpoint.** `test_cli_requires_db_and_logs_changed_count(tmp_path)`. Seam: the script's command line, run through `subprocess.run([sys.executable, str(REPAIR_JOB), ...])`. Asserts: a bare invocation exits with return code 2. Against an inline-seeded crawl-shape DB under `tmp_path`, the run exits 0, and `re.search(r"channel names repaired rows=(\d+)", proc.stderr)` gives 3. A second run gives 0.

**Intent.** `repair-video-channel-names.py` runs as a command that refuses to start without an explicit `--db` and logs the number of rows it changed.

- C1 - Invoking the job without `--db` exits with an argparse usage error (return code 2).
- C2 - Invoking the job with `--db` logs `channel names repaired rows=N` with the changed count.

**Outcome.** _pending_


Needs coordination: Phase 1: the crawl checkpoint needs `node` on PATH and `engine/crawler/node_modules` (better-sqlite3), which `npm install` may need network access to fetch. It also needs the dist rebuilt with `cd engine/crawler && npm run build` and committed with the source, or the staleness gate fails. No credentials are needed and no live endpoints are used: the test binds only to loopback ephemeral ports. No phase touches the real crawl.db or whitelist.db. Running the job against those databases is the operator's post-merge step in the runbook.

Rationale: The seams follow the draft's own boundaries. The writer fix is verified through the compiled crawler, and the repair job through three separate boundaries: the in-process function, the FTS table, and the CLI. The job's intent covers four observable facts: row correction, count/idempotence, index consistency and CLI behaviour. With at most two clauses per phase, that makes three job phases. Phase 2's whitelist-shape parameter passes without special FTS handling, because the triggers keep the index in step row by row. Phase 3 then adds the drop/update/recreate/rebuild path and proves it with the stale-index MATCH and the count check, so each phase is independently green. The crawler fix is its own phase because it shares no code with the job and needs a different harness (node plus a committed dist). DATA_BUILD.md section 2b is documentation, so it gets no phase and is written in Step 9. There is no prose phase. Four phases is the maximum, so no split into further plans is needed. The operator approved this breakdown.

## 2026-09-27 - Step 7 - Phase 1 (Crawler keys channel metadata by host and id) - must_prove

Quoted from the phase Intent, written at Step 6 before the checkpoint was drafted.

Intent:
`crawlVideos` in `engine/crawler/src/videos-worker.ts` (and its committed `dist/videos-worker.js`) looks up channel metadata by lowercased host plus channel id. As a result, each host's crawled videos carry that host's own channel metadata, even when a channel id repeats across instances.

- C1 - Each host's crawled videos have `channel_name` equal to the `display_name` of the channel on that same host.
- C2 - Each host's crawled videos have `channel_url` equal to the `channel_url` of the channel on that same host.

must_prove:
- C1 - Each host's crawled videos have `channel_name` equal to the `display_name` of the channel on that same host.
- C2 - Each host's crawled videos have `channel_url` equal to the `channel_url` of the channel on that same host.

## 2026-09-27 - Step 7 - Phase 1 (Crawler keys channel metadata by host and id) - self-check (audit round 1, send-back 0)

`tests/tmp/test_34_video_channel_name_wrong_instance_phase1.py`, surface `checkpoint`. Collection exit 0.

- C1 - tests/tmp/test_34_video_channel_name_wrong_instance_phase1.py:112 — `names`, keyed by (instance_domain, video_id) over every stored video row, equals exactly {(host_a,"a-1"):"Alpha Display", (host_a,"a-2"):"Alpha Display", (host_b,"b-1"):"Beta Display"} - expected: Once the phase is built, alpha's two videos carry "Alpha Display" and beta's one video carries "Beta Display", with no other rows. The current code reached this assertion with rc 0 and all three videos stored (crawl log "new=2", "new=1", "new_total=3"), so the row set and keys are observed. The per-host values are the fixture's own display_name for each host. - excludes: The current code keys `channelMeta` by `channel_id` alone (videos-worker.ts:163-172), so the two "7" rows collide and one host's meta overwrites the other's. Observed in the gating run: `{(host_a,'a-1'): 'Beta Display', (host_a,'a-2'): 'Beta Display'}`, so alpha's videos got beta's name. Observed in the probe run: b-1 read 'Alpha Display'. Which host wins changes between runs, and the assertion goes red either way. Other wrong fixes it excludes: using the slug `channel_name` ("alpha"/"beta" instead of the display names), or storing null.
- C2 - tests/tmp/test_34_video_channel_name_wrong_instance_phase1.py:113 — `urls`, keyed by (instance_domain, video_id), equals exactly {(host_a,"a-1"):url_a, (host_a,"a-2"):url_a, (host_b,"b-1"):url_b}, where url_a/url_b are each host's own channels.channel_url - expected: Once the phase is built, a-1 and a-2 carry `http://<host_a>/video-channels/alpha` and b-1 carries `http://<host_b>/video-channels/beta`. The stand-in videos carry no `channel`, so `channelRef?.url` is absent and the value can only come from the channels row. The probe run confirmed that with every other fallback absent, the stored URL comes from that meta. - excludes: With the same channel_id-only `channelMeta` key, the colliding meta supplies the other host's URL. Observed in the probe run (same fixture as the checkpoint): `('127.0.0.1:40483', 'b-1', 'Alpha Display', 'http://127.0.0.1:41925/video-channels/alpha')`, so beta's video got alpha's URL. The name could be fixed while the URL still comes from shared meta, and C2 catches that partial fix.

<assertions>
tests/tmp/test_34_video_channel_name_wrong_instance_phase1.py:112 - exact equality of {(instance_domain, video_id): channel_name} read from `videos` after the compiled `crawlVideos` ran against two local instances whose channel rows share channel_id "7": host A's a-1 and a-2 carry "Alpha Display", host B's b-1 carries "Beta Display". Because the dict is exact, it also rules out any video carrying the other host's name, any missing row and any extra row. Today's code fails it: host A's videos come back as "Beta Display". - C1
tests/tmp/test_34_video_channel_name_wrong_instance_phase1.py:113 - exact equality of {(instance_domain, video_id): channel_url} from the same rows: host A's videos carry http://<host A>/video-channels/alpha and host B's video carries http://<host B>/video-channels/beta. The served video JSON has no `channel` object, so the URL can only come from the channels row the lookup picks. Today's code gives host A beta's URL (seen in the probe). - C2
</assertions>

<probes>
Command: ValidateTests ["tests/tmp/probe_channel_names.py", "-s"]. The probe was the same harness as the test (two ThreadingHTTPServers on 127.0.0.1, crawl.db built from schema.sql, channels ("7","alpha",url_a,"Alpha Display",host_a,2) and ("7","beta",url_b,"Beta Display",host_b,1), node --input-type=module -e with cwd=engine/crawler importing dist/videos-worker.js), with prints added. What it printed:
- node and git were both on PATH. dist/videos-worker.js exists, and `git status --porcelain` on src and dist was empty, so the stale gate compares commit times.
- node exited 0 in 0.07s with empty stderr. With maxRetries 0, the https-first attempt against the plain-http servers failed at once and never reached do_GET. The only hits were one http GET per server: /api/v1/video-channels/alpha/videos?start=0&count=50&sort=-publishedAt and /api/v1/video-channels/beta/videos?...
- videos rows: (hostA,'a-1','7','Beta Display','http://hostB/video-channels/beta'), (hostA,'a-2','7','Beta Display','http://hostB/video-channels/beta'), (hostB,'b-1','7','Beta Display','http://hostB/video-channels/beta'). This is the value under the wrong implementation: the id-only map keeps the last "7" row.
- video_crawl_progress ended 'done' for both hosts. listChannelsWithVideos returned the rows in insertion order (A, then B).
Then ValidateTests ["tests/tmp/test_34_video_channel_name_wrong_instance_phase1.py"] failed at line 112 (C1), with {(hostA,'a-1'): 'Beta Display'} != 'Alpha Display' and the same for a-2. All gates passed and node exit was 0.
Either row order leaves one host wrong under the id-only map, so the red does not depend on order. I have no tool that deletes files, so the probe file tests/tmp/probe_channel_names.py is still on disk and needs removing.
</probes>

<unassertable>
none
</unassertable>

### `tests/tmp/test_34_video_channel_name_wrong_instance_phase1.py` - 6113 characters, inlined in full

```
"""The crawler's compiled `crawlVideos`, run under node against two local PeerTube stand-ins whose channels share channel_id "7".

- Every video stored for a host has `channel_name` equal to the `display_name` of that host's own channel row, and no video carries the other host's name.
- Every video stored for a host has `channel_url` equal to the `channel_url` of that host's own channel row, and no video carries the other host's URL.
- A missing node or git, a missing or stale dist, or a nonzero node exit fails the test rather than skipping it.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CRAWLER_DIR = ROOT / "engine" / "crawler"
SCHEMA = CRAWLER_DIR / "schema.sql"
SRC = CRAWLER_DIR / "src" / "videos-worker.ts"
DIST = CRAWLER_DIR / "dist" / "videos-worker.js"
BUILD_HINT = "cd engine/crawler && npm install && npm run build"

NODE_SCRIPT = """
import { readFileSync } from "node:fs";
const { crawlVideos } = await import(process.env.VIDEOS_WORKER_URL);
await crawlVideos(JSON.parse(readFileSync(0, "utf8")));
"""


def _git(git: str, *args: str) -> str:
    proc = subprocess.run([git, *args], cwd=ROOT, capture_output=True, text=True)
    assert proc.returncode == 0, f"git {' '.join(args)} failed: {proc.stderr}"
    return proc.stdout.strip()


def _dist_is_stale(git: str) -> bool:
    """Whether DIST predates SRC: by commit time when both are committed and clean, since a checkout sets mtimes arbitrarily; otherwise by time on disk."""
    dirty = _git(git, "status", "--porcelain", "--", str(SRC), str(DIST))
    src_committed = _git(git, "log", "-1", "--format=%ct", "--", str(SRC))
    dist_committed = _git(git, "log", "-1", "--format=%ct", "--", str(DIST))
    if dirty or not src_committed or not dist_committed:
        return SRC.stat().st_mtime > DIST.stat().st_mtime
    return int(src_committed) > int(dist_committed)


def _instance(slug: str, videos: list[dict]) -> ThreadingHTTPServer:
    """A PeerTube stand-in serving one channel's videos page; the videos carry no `channel`, so the stored name and URL can only come from the channels row."""
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.split("?", 1)[0] != f"/api/v1/video-channels/{slug}/videos":
                self.send_response(404)
                self.end_headers()
                return
            body = json.dumps({"total": len(videos), "data": videos}).encode("utf-8")
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def test_crawl_writes_each_hosts_own_channel_name(tmp_path):
    node = shutil.which("node")
    assert node is not None, f"node is not on PATH; install Node.js, then {BUILD_HINT}"
    assert DIST.is_file(), f"{DIST} is missing; {BUILD_HINT}"
    git = shutil.which("git")
    assert git is not None, f"git is not on PATH, so whether {DIST} predates {SRC} cannot be told"
    assert not _dist_is_stale(git), f"{DIST} predates {SRC}; {BUILD_HINT}"

    alpha = _instance("alpha", [{"uuid": "a-1", "name": "A one"}, {"uuid": "a-2", "name": "A two"}])
    beta = _instance("beta", [{"uuid": "b-1", "name": "B one"}])
    try:
        host_a = f"127.0.0.1:{alpha.server_address[1]}"
        host_b = f"127.0.0.1:{beta.server_address[1]}"
        url_a = f"http://{host_a}/video-channels/alpha"
        url_b = f"http://{host_b}/video-channels/beta"
        db_path = tmp_path / "crawl.db"
        conn = sqlite3.connect(db_path)
        try:
            conn.executescript(SCHEMA.read_text(encoding="utf-8"))
            conn.executemany("INSERT INTO instances (host) VALUES (?)", [(host_a,), (host_b,)])
            conn.executemany("INSERT INTO channels (channel_id, channel_name, channel_url, display_name, instance_domain, videos_count) VALUES (?, ?, ?, ?, ?, ?)", [("7", "alpha", url_a, "Alpha Display", host_a, 2), ("7", "beta", url_b, "Beta Display", host_b, 1)])
            conn.commit()
        finally:
            conn.close()
        # maxRetries 0 keeps the crawler's https-first attempt against these plain-http servers to one fast failure before its http fallback.
        options = {"dbPath": str(db_path), "excludeHostsFile": None, "existingDbPath": None, "concurrency": 2, "timeoutMs": 5000, "maxRetries": 0, "resume": False, "errorsOnly": False, "newOnly": False, "stopAfterFullPages": 0, "sort": "-publishedAt", "maxInstances": 0, "maxChannels": 0, "maxVideosPages": 0, "tagsOnly": False, "updateTags": False, "commentsOnly": False, "hostDelayMs": 0}
        proc = subprocess.run([node, "--input-type=module", "-e", NODE_SCRIPT], cwd=CRAWLER_DIR, input=json.dumps(options), capture_output=True, text=True, encoding="utf-8", timeout=120, env={**os.environ, "VIDEOS_WORKER_URL": DIST.as_uri()})
    finally:
        alpha.shutdown()
        alpha.server_close()
        beta.shutdown()
        beta.server_close()
    assert proc.returncode == 0, f"node could not run {DIST}: {proc.stderr}; {BUILD_HINT}"

    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute("SELECT instance_domain, video_id, channel_name, channel_url FROM videos").fetchall()
    finally:
        conn.close()
    names = {(host, video_id): name for host, video_id, name, _ in rows}
    urls = {(host, video_id): url for host, video_id, _, url in rows}
    assert names == {(host_a, "a-1"): "Alpha Display", (host_a, "a-2"): "Alpha Display", (host_b, "b-1"): "Beta Display"}, f"crawl log: {proc.stdout}"  # C1
    assert urls == {(host_a, "a-1"): url_a, (host_a, "a-2"): url_a, (host_b, "b-1"): url_b}, f"crawl log: {proc.stdout}"  # C2

```


Gate: satisfied

## 2026-09-27 - Step 7 - Phase 1 (Crawler keys channel metadata by host and id) - red (audit round 1)

`tests/tmp/test_34_video_channel_name_wrong_instance_phase1.py` exited 1.

```
  tests/tmp/test_34_video_channel_name_wrong_instance_phase1.py  1 failed                               0.0s
  -------------------------------------------------------------
  total                                                          1 failed                               0.7s wall, 1 lane

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

## 2026-09-27 - Step 7 - Phase 1 (Crawler keys channel metadata by host and id) - audit (round 1)

- AUDIT: devsecops-test-shape-auditor - PASS
- AUDIT: devsecops-test-claim-auditor - PASS
- OUTSTANDING: nothing

### devsecops-test-shape-auditor

```
SHAPE AUDIT — VERDICT: PASS

CRITICAL
none

RECOMMENDATIONS
none

PREDICTED FAILURE
Fails at line 112 on the `names ==` assertion. The current `crawlVideos` keys
`channelMeta` by `channel.channel_id` alone (engine/crawler/src/videos-worker.ts:163-171),
and both channel rows share channel_id "7". One host's metadata therefore overwrites the
other's, and one host's videos get the other host's display_name ("Alpha Display" where
"Beta Display" belongs, or the reverse). Line 113 would fail the same way on `channel_url`
if line 112 did not stop the test first.

NOT ASSESSED
1. `code_under_test` lists tests/active/test_channel_names.py (NEW), which does not
   exist. It was not read, and it has no bearing on this test's assertions.
2. engine/crawler/dist/videos-worker.js was not read. The stub question and the predicted
   failure come from src/videos-worker.ts (lines 136-202 and 641-699) and assume the
   compiled output matches it. The test guards that assumption at line 77.
3. `fixtures_path` was not supplied. The test builds all its fixtures inline (lines 48-68,
   79-94), so there was nothing to resolve. engine/crawler/schema.sql was not read.
```

### devsecops-test-claim-auditor

CLAIM AUDIT — VERDICT: PASS

CLAUSE MAP  (14 clauses: 2 must_prove, 10 docstring, 2 name)
| id | source | clause | assertion | excludes | status |
|---|---|---|---|---|---|
| C1 | must_prove | each host's videos have `channel_name` = that host's channel `display_name` | :112 | Looking up channel metadata by `channel_id` alone, which puts one host's display name on both hosts' videos. Both rows share id "7" (:91) and have different display names | CARRIED |
| C2 | must_prove | each host's videos have `channel_url` = that host's channel `channel_url` | :113 | The same `channel_id`-only lookup, which gives both hosts' videos one URL. `url_a` and `url_b` differ (:84-85), and the stand-in videos have no `channel` object (:49, :79-80), so the stored URL has to come from the channels row | CARRIED |
| D1 | docstring | "compiled `crawlVideos`, run under node against two local PeerTube stand-ins whose channels share channel_id \"7\"" | :103, :112 | A node run that fails or never runs `crawlVideos`. :112 also needs rows keyed under both hosts, so it fails if only one stand-in was crawled | CARRIED |
| D2 | docstring | "every video stored for a host has `channel_name` equal to the `display_name` of that host's own channel row" | :112 | Wrong or null names, and videos missing from the result (the whole dict must be equal) | CARRIED |
| D3 | docstring | "no video carries the other host's name" | :112 | Cross-host name leakage: any `Beta Display` on an alpha key fails the equality | CARRIED |
| D4 | docstring | "every video stored for a host has `channel_url` equal to the `channel_url` of that host's own channel row" | :113 | Wrong or null URLs, and missing videos | CARRIED |
| D5 | docstring | "no video carries the other host's URL" | :113 | Cross-host URL leakage | CARRIED |
| D6 | docstring | "a missing node ... fails the test rather than skipping it" | :73 | A skip or early return when node is absent | CARRIED |
| D7 | docstring | "a missing ... git ... fails the test" | :76 | A skip when git is absent | CARRIED |
| D8 | docstring | "a missing ... dist ... fails the test" | :74 | Running against a dist that does not exist | CARRIED |
| D9 | docstring | "a ... stale dist ... fails the test" | :77 | A green run against a dist compiled before the source edit | CARRIED |
| D10 | docstring | "a nonzero node exit fails the test" | :103 | Reading an empty or partial DB after node crashed | CARRIED |
| N1 | name | "crawl writes ... channel name" | :112 | A crawl that stores no name, or a null name | CARRIED |
| N2 | name | "each host's own" | :112 | Names attributed across hosts; the test has two hosts and one shared channel id | CARRIED |

CRITICAL
none

RECOMMENDATIONS
1. name-as-sentence (rules/testing.md) — tests/tmp/test_34_video_channel_name_wrong_instance_phase1.py:71
   The name `test_crawl_writes_each_hosts_own_channel_name` says what should happen but not when: the shared-`channel_id` condition is missing. It also names only the channel name, although the test asserts the channel URL too (C2, :113). A failure at :113 is reported under a name that does not mention URLs.
2. bounds (rules/testing.md) — tests/tmp/test_34_video_channel_name_wrong_instance_phase1.py:91
   Only populated channel rows run. `toVideoRow` (videos-worker.ts:660-664) has fallbacks that no test reaches:
   - a channels row with a null `display_name`, which falls back to the video's own `channel.displayName`;
   - a null `channel_url`.
3. normal-and-abnormal-paths (rules/testing.md) — tests/tmp/test_34_video_channel_name_wrong_instance_phase1.py:79-80
   The stand-in videos never carry a `channel` object. In `toVideoRow` the URL prefers the video's `channel.url` over the channels row (videos-worker.ts:664), while the name prefers the channels row (videos-worker.ts:661-662). Nothing tests that precedence, so C2 is proven only on the path where the video has no channel URL of its own.

OBSERVATIONS
none

NOT ASSESSED
1. `code_under_test` lists tests/active/test_channel_names.py, but no file exists at that path. Nothing from it was assessed.
2. engine/crawler/dist/videos-worker.js was not read. The claims were judged against src/videos-worker.ts (the `crawlVideos` entry point, `processInstance` and `toVideoRow`).
3. `fixtures_path` was not supplied. The test uses only pytest's built-in `tmp_path` fixture, so there was no conftest to resolve.

## 2026-09-27 - Step 7 - Phase 1 (Crawler keys channel metadata by host and id) - checkpoint outcome (run 1)

`tests/tmp/test_34_video_channel_name_wrong_instance_phase1.py` exited 0 after the phase landed.

<changes>
### `engine/crawler/src/videos-worker.ts`
- `crawlVideos` now keys the `channelMeta` map by `channelMetaKey(channel.instance_domain.toLowerCase(), channel.channel_id)` instead of by `channel.channel_id` alone. Before, when two instances had the same channel id, the later row overwrote the earlier one and both hosts got the same `channel_name`/`channel_url`.
- `processInstance` looks up metadata with `channelMetaKey(normalizedHost, item.channelId)`. `normalizedHost` is already lowercased, so both sides of the lookup use the same host form.
- New helper `channelMetaKey(host, channelId)` returns `` `${host}/${channelId}` ``. A host cannot contain `/`, so two different host/id pairs can never produce the same key. It has a one-line JSDoc comment explaining why ids need the host, matching the file's other function comments.

### `engine/crawler/dist/videos-worker.js`
- Edited by hand to match the source change in the style tsc produces here (same two call sites, plus `channelMetaKey` with its JSDoc and no type annotations). I have no shell, so I could not run `npm run build`. The dist was saved after the source, so its mtime is newer and the checkpoint's staleness check, which compares mtimes on a dirty tree, will pass. There is no source map to update.

### `tests/active/test_channel_names.py`
- Not created. It is the checkpoint's permanent location, and this turn was limited to production code. The gating checkpoint stays at `tests/tmp/test_34_video_channel_name_wrong_instance_phase1.py`, unchanged.
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
  tests/tmp/test_34_video_channel_name_wrong_instance_phase1.py  1 passed                               0.0s
  -------------------------------------------------------------
  total                                                          1 passed                               1.2s wall, 1 lane

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

## 2026-09-27 - Step 7 - Phase 2 (Repair function corrects channel names) - must_prove

Quoted from the phase Intent, written at Step 6 before the checkpoint was drafted.

Intent:
The new job `engine/server/db/jobs/repair-video-channel-names.py` exposes `repair_channel_names`. It sets each video's `channel_name` to the non-empty `display_name` of its own `(channel_id, instance_domain)` channel and returns how many rows it changed.

- C1 - After a repair, videos with a foreign or NULL `channel_name` carry their own channel's `display_name`. Already-correct rows, rows whose channel has an empty, NULL or absent display name, and the `channels` table are unchanged.
- C2 - The repair returns the number of rows it changed, and a second run returns 0.

must_prove:
- C1 - After a repair, videos with a foreign or NULL `channel_name` carry their own channel's `display_name`. Already-correct rows, rows whose channel has an empty, NULL or absent display name, and the `channels` table are unchanged.
- C2 - The repair returns the number of rows it changed, and a second run returns 0.

## 2026-09-27 - Step 7 - Phase 2 (Repair function corrects channel names) - self-check (audit round 1, send-back 0)

`tests/tmp/test_34_video_channel_name_wrong_instance_phase2.py`, surface `checkpoint`. Collection exit 0.

- C1 - tests/tmp/test_34_video_channel_name_wrong_instance_phase2.py:85 — on a fresh connection after the first repair, `dict(SELECT video_id, channel_name FROM videos) == REPAIRED`: v1 → Alphachan, v2 → Betachan, v7 (was NULL) → Alphachan, and v3 Betachan, v4 Stalename, v5 Stalename, v6 Orphanname unchanged. Run on both the crawl and whitelist shapes. - expected: {'v1': 'Alphachan', 'v2': 'Betachan', 'v3': 'Betachan', 'v4': 'Stalename', 'v5': 'Stalename', 'v6': 'Orphanname', 'v7': 'Alphachan'} on both shapes. The probe observed exactly this dict after running the draft's REPAIR_SQL on each shape. - excludes: Each wrong variant below was observed in the probe on both shapes. `!=` instead of `IS NOT` leaves v7 None. Dropping the empty-name guard writes '' into v4. An unguarded update also writes None into v5. Joining on channel_id alone gives v2 and v3 'Alphachan'. A repair that never commits reads back as the seeded names when the database is reopened. Each of these makes the dict differ from REPAIRED.
- C1 - tests/tmp/test_34_video_channel_name_wrong_instance_phase2.py:86 — after the repair, `SELECT * FROM channels ORDER BY channel_id, instance_domain` on a fresh connection equals the snapshot taken at line 74, before the repair. It is armed by line 85, which shows that the repair ran and wrote. - expected: The pre-repair rows unchanged. The probe observed four rows, for example on the crawl shape ('7',None,None,'Alphachan','a.example',…), ('7',None,None,'Betachan','b.example',…), ('8',None,None,'','a.example',…), ('9',None,None,None,'a.example',…), and the whitelist shape has its own column order. - excludes: A repair that also "syncs" channels, for example writing display_name into channels.channel_name, filling the empty or NULL display_name for channels 8 and 9, or pruning channel rows with no videos. The snapshot then differs in at least one row. This case was not run in the probe; the assertion is a direct before/after comparison of the whole table.
- C2 - tests/tmp/test_34_video_channel_name_wrong_instance_phase2.py:80 — the first `repair.repair_channel_names(conn)` returns exactly 3. - expected: 3 on both shapes, taken from the UPDATE's rowcount in the probe. On the whitelist shape, trigger writes to videos_fts are not counted. - excludes: Counts observed in the probe: `!=` returns 2; no empty-name guard returns 4; channel_id-only join returns 4; unguarded returns 6. A function that returns the number of candidate rows (7) or a fixed value also fails.
- C2 - tests/tmp/test_34_video_channel_name_wrong_instance_phase2.py:88 — a second `repair_channel_names(conn)` on a fresh connection returns 0. Line 94 then reopens the database and checks that the names still equal REPAIRED. - expected: 0 on the second call and the REPAIRED dict afterwards. The probe observed a second rowcount of 0 for the draft SQL on both shapes. - excludes: Second-run counts observed in the probe: channel_id-only join returns 4 again, because v2 and v3 flip back and forth; unguarded returns 6; no commit returns 3, because the first run was lost. A version that re-writes every matching row without the `IS NOT channel_name` guard returns non-zero every run. Line 94 catches a second run that changes names.

<assertions>
tests/tmp/test_34_video_channel_name_wrong_instance_phase2.py:73 - control, before the repair: the seeded `video_id -> channel_name` dict equals STORED, so a failure later cannot come from a seed that never landed (setup control, no clause)
tests/tmp/test_34_video_channel_name_wrong_instance_phase2.py:78 - the first `repair_channel_names(conn)` returns exactly 3 on both shapes. Observed wrong values: `!=` instead of `IS NOT` gives 2, no empty-name guard gives 4, joining on channel_id alone gives 4, no WHERE clause gives 7 (C2)
tests/tmp/test_34_video_channel_name_wrong_instance_phase2.py:83 - read on a fresh connection, the dict equals REPAIRED: v1, v2 and v7 (foreign or NULL names) carry their own channel's display name, and v3 (already correct), v4 (empty display_name), v5 (NULL display_name) and v6 (no channel row) keep their stored names. Reopening means a repair that never commits reads back as STORED, which was observed (C1)
tests/tmp/test_34_video_channel_name_wrong_instance_phase2.py:84 - `SELECT * FROM channels ORDER BY channel_id, instance_domain` equals the snapshot taken before the repair (C1)
tests/tmp/test_34_video_channel_name_wrong_instance_phase2.py:85 - `has_videos_fts(conn)` is True exactly when the parameter is `whitelist`, after the repair. This is the agreed shape control, confirming the run covered the named schema (no clause)
tests/tmp/test_34_video_channel_name_wrong_instance_phase2.py:86 - a second `repair_channel_names(conn)` returns 0. Observed wrong value: joining on channel_id alone gives 4 again, and no WHERE clause gives 7 (C2)
tests/tmp/test_34_video_channel_name_wrong_instance_phase2.py:92 - after the second call, a fresh connection still reads the dict as REPAIRED (C2)
</assertions>

<probes>
Command: ValidateTests ["tests/tmp/test_probe_34_phase2.py", "-s"]. The probe loaded sync-whitelist.py with the _load_job loader, built both shapes (crawl via executescript(schema.sql), whitelist via ensure_content_schema), seeded the draft's channels 7/8/9 and videos v1-v7 with named columns, and applied the draft UPDATE plus wrong variants. It printed the following. The repair job does not exist yet. On the crawl shape, sqlite_master has no videos_fts objects. On the whitelist shape it has the videos_fts table, its shadow tables and the triggers videos_fts_ai/ad/au. On both shapes the seeded dict reads {'v1': 'Betachan', 'v2': 'Alphachan', 'v3': 'Betachan', 'v4': 'Stalename', 'v5': 'Stalename', 'v6': 'Orphanname', 'v7': None}, and inserting into the whitelist shape's videos with its triggers in place succeeded. Draft SQL on both shapes: count 3, after {'v1': 'Alphachan', 'v2': 'Betachan', 'v3': 'Betachan', 'v4': 'Stalename', 'v5': 'Stalename', 'v6': 'Orphanname', 'v7': 'Alphachan'}, second run 0. `!=` in place of `IS NOT`: count 2, v7 stays None. No `<> ''` guard: count 4, v4 becomes ''. No `IS NOT NULL` guard: identical to the draft, because `NULL <> ''` is already false. Join on channel_id alone: count 4, v2 and v3 become 'Alphachan', second run 4. No WHERE clause: count 7, v4 becomes '', v5 and v6 become None, second run 7. Draft SQL run with no commit and the connection closed: after reopening, the dict reads as the seeded values. Command: ValidateTests ["tests/tmp/test_34_video_channel_name_wrong_instance_phase2.py"]. Both parameters error in the `jobs` fixture with FileNotFoundError for engine/server/db/jobs/repair-video-channel-names.py, the expected red before phase 2 is implemented. The probe file tests/tmp/test_probe_34_phase2.py has been emptied, because no tool here can delete it. It should be removed.
</probes>

<unassertable>
none
</unassertable>

### `tests/tmp/test_34_video_channel_name_wrong_instance_phase2.py` - 4321 characters, inlined in full

```
"""`repair_channel_names` from `repair-video-channel-names.py`, run in-process on a crawl.db-shaped and a whitelist.db-shaped temp database seeded with foreign, NULL, correct and unrepairable channel names.

- It returns 3, and a fresh connection then reads v1, v2 and v7 (foreign or NULL names) as their own channel's display name, while v3 (already correct), v4 (empty display name), v5 (NULL display name) and v6 (no channel row) keep their stored names.
- `channels` reads back identical to its pre-repair snapshot.
- A second call returns 0 and leaves every name as the first call set it.
- `has_videos_fts` is True on the whitelist shape and False on the crawl shape.
"""
from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
JOBS_DIR = ROOT / "engine" / "server" / "db" / "jobs"
CRAWL_SCHEMA = ROOT / "engine" / "crawler" / "schema.sql"

CHANNELS = [("7", "a.example", "Alphachan"), ("7", "b.example", "Betachan"), ("8", "a.example", ""), ("9", "a.example", None)]
# (video_id, instance_domain, channel_id, stored channel_name); channel 7 exists on both instances, so each instance's rows start with the other instance's name.
VIDEOS = [("v1", "a.example", "7", "Betachan"), ("v2", "b.example", "7", "Alphachan"), ("v3", "b.example", "7", "Betachan"), ("v4", "a.example", "8", "Stalename"), ("v5", "a.example", "9", "Stalename"), ("v6", "a.example", "404", "Orphanname"), ("v7", "a.example", "7", None)]
STORED = {"v1": "Betachan", "v2": "Alphachan", "v3": "Betachan", "v4": "Stalename", "v5": "Stalename", "v6": "Orphanname", "v7": None}
REPAIRED = {"v1": "Alphachan", "v2": "Betachan", "v3": "Betachan", "v4": "Stalename", "v5": "Stalename", "v6": "Orphanname", "v7": "Alphachan"}


def _load_job(module_name: str, filename: str):
    spec = importlib.util.spec_from_file_location(module_name, JOBS_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def jobs():
    return _load_job("sync_whitelist_channel_names", "sync-whitelist.py"), _load_job("repair_video_channel_names", "repair-video-channel-names.py")


def _seed(conn: sqlite3.Connection) -> None:
    conn.executemany("INSERT INTO channels (channel_id, instance_domain, display_name) VALUES (?, ?, ?)", CHANNELS)
    conn.executemany("INSERT INTO videos (video_id, instance_domain, channel_id, channel_name, title, description, last_checked_at) VALUES (?, ?, ?, ?, 'clip ' || ?1, 'plain text', 1)", VIDEOS)


@pytest.fixture(params=["crawl", "whitelist"])
def seeded_db(request, jobs, tmp_path):
    sync, _ = jobs
    db_path = tmp_path / f"{request.param}.db"
    conn = sqlite3.connect(db_path)
    try:
        if request.param == "crawl":
            conn.executescript(CRAWL_SCHEMA.read_text(encoding="utf-8"))
        else:
            sync.ensure_content_schema(conn)
        _seed(conn)
        conn.commit()
    finally:
        conn.close()
    return db_path, request.param


def _names(conn: sqlite3.Connection) -> dict:
    return dict(conn.execute("SELECT video_id, channel_name FROM videos").fetchall())


def _channels(conn: sqlite3.Connection) -> list:
    return conn.execute("SELECT * FROM channels ORDER BY channel_id, instance_domain").fetchall()


def test_repair_sets_each_video_to_its_own_channel_name(jobs, seeded_db):
    _, repair = jobs
    db_path, shape = seeded_db
    conn = sqlite3.connect(db_path)
    try:
        assert _names(conn) == STORED, "the seed did not land as written"
        channels_before = _channels(conn)
        changed = repair.repair_channel_names(conn)
    finally:
        conn.close()
    assert changed == 3  # C2

    # Reopened, so a repair that never commits reads back as the stored names.
    conn = sqlite3.connect(db_path)
    try:
        assert _names(conn) == REPAIRED  # C1
        assert _channels(conn) == channels_before  # C1
        assert repair.has_videos_fts(conn) is (shape == "whitelist"), f"the {shape} shape was not told apart by videos_fts"
        assert repair.repair_channel_names(conn) == 0  # C2
    finally:
        conn.close()

    conn = sqlite3.connect(db_path)
    try:
        assert _names(conn) == REPAIRED  # C2
    finally:
        conn.close()

```


Gate: satisfied

## 2026-09-27 - Step 7 - Phase 2 (Repair function corrects channel names) - red (audit round 1)

`tests/tmp/test_34_video_channel_name_wrong_instance_phase2.py` exited 1.

```
  tests/tmp/test_34_video_channel_name_wrong_instance_phase2.py  2 failed                               0.0s
  -------------------------------------------------------------
  total                                                          2 failed                               0.2s wall, 1 lane

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

## 2026-09-27 - Step 7 - Phase 2 (Repair function corrects channel names) - audit (round 1)

- AUDIT: devsecops-test-shape-auditor - PASS
- AUDIT: devsecops-test-claim-auditor - PASS
- OUTSTANDING: nothing

### devsecops-test-shape-auditor

```
SHAPE AUDIT — VERDICT: PASS

CRITICAL
none

RECOMMENDATIONS
none

PREDICTED FAILURE
Both parametrisations ("crawl" and "whitelist") pass the seed control at line 73, then fail
at line 76. There `_load_job("repair_video_channel_names", "repair-video-channel-names.py")`
calls `spec.loader.exec_module` on engine/server/db/jobs/repair-video-channel-names.py.
That file does not exist yet, so it raises FileNotFoundError before `repair_channel_names`
is reached.

NOT ASSESSED
1. `code_under_test` listed tests/active/test_channel_names.py (EDITED). That path does not
   resolve in this worktree, so the edit was not read.
2. `code_under_test` listed engine/server/db/jobs/repair-video-channel-names.py (NEW). It
   does not exist yet, so `repair_channel_names` and `has_videos_fts` were not read. The stub
   question was answered from the assertion form and the seed data alone:
   - A stub returning 3 without writing fails at line 85, because REPAIRED differs from STORED
     on v1, v2 and v7.
   - A stub returning 0, or the old behaviour left in place, fails at line 80.
   - A repair that joins on channel_id without instance_domain fails at line 85: channel 7
     has a different name on each instance, so v1 and v2 would end up with the same name.
   - A repair that writes empty or NULL display names fails at line 85 on v4 and v5.
   - A repair that never commits fails at line 85, because the test reopens the connection.
   - A second run that still reports changes fails at line 88.
   The expected values are literals (lines 20-24), not worked out the way the code works
   them out. The observable is read across seven rows and two database shapes, so no
   anti_pattern entry in rules/shape.md applies. The test sits at ladder rung 1 (it calls the
   function directly) with rung-3 row checks, which suits a function that edits a database.
   There is no downshift.
```

### devsecops-test-claim-auditor

CLAIM AUDIT — VERDICT: PASS

CLAUSE MAP  (19 clauses: 9 must_prove, 8 docstring, 2 name)
| id | source | clause | assertion | excludes | status |
|---|---|---|---|---|---|
| C1a | must_prove | videos with a foreign `channel_name` carry their own channel's `display_name` | :85 | matching on `channel_id` alone: channel 7 is on both instances, so v1 and v2 cannot both come out right | CARRIED |
| C1b | must_prove | videos with a NULL `channel_name` are repaired the same way | :85 | a repair that only compares `channel_name != display_name`, which skips NULL (v7 would stay None) | CARRIED |
| C1c | must_prove | already-correct rows are unchanged | :85, :80 | a repair that rewrites v3; the count of 3 at :80 also excludes a same-value rewrite being counted | CARRIED |
| C1d | must_prove | rows whose channel has an empty display name are unchanged | :85 | writing `''` over v4's stored name | CARRIED |
| C1e | must_prove | rows whose channel has a NULL display name are unchanged | :85 | writing NULL over v5's stored name | CARRIED |
| C1f | must_prove | rows whose channel's display name is absent (no channel row) are unchanged | :85 | a correlated-subquery UPDATE with no match that NULLs v6 | CARRIED |
| C1g | must_prove | the `channels` table is unchanged | :86 | any write to `channels`: the whole-row `SELECT *` snapshot catches it on either side | CARRIED |
| C2a | must_prove | the repair returns the number of rows it changed | :80 | returning the table size (7), the matched-row count (4 with v3), or None | CARRIED |
| C2b | must_prove | a second run returns 0 | :88 | an UPDATE without an "is it already correct" guard, which returns ≥3 again | CARRIED |
| D1 | docstring | "run in-process on a crawl.db-shaped and a whitelist.db-shaped temp database" | :73 (params :44) | a shape that silently seeded nothing; the seed check runs on both params | CARRIED |
| D2 | docstring | "seeded with foreign, NULL, correct and unrepairable channel names" | :73 | a seed that did not land as `STORED` describes | CARRIED |
| D3 | docstring | "It returns 3" | :80 | any other count | CARRIED |
| D4 | docstring | "a fresh connection then reads v1, v2 and v7 … as their own channel's display name" | :85 (reopen :83) | a repair that never commits | CARRIED |
| D5 | docstring | "v3, v4, v5, v6 … keep their stored names" | :85 | writing to any of the four | CARRIED |
| D6 | docstring | "`channels` reads back identical to its pre-repair snapshot" | :86 | any write to `channels` | CARRIED |
| D7 | docstring | "A second call returns 0 and leaves every name as the first call set it" | :88, :94 | a second call that counts again, or rewrites and commits a name | CARRIED |
| D8 | docstring | "`has_videos_fts` is True on the whitelist shape and False on the crawl shape" | :87 | a constant return; both params run | CARRIED |
| N1 | name | "sets each video to its own channel name" (its own instance's channel) | :85 | a join on `channel_id` without `instance_domain` (v1 and v2) | CARRIED |
| N2 | name | "each video" | :85 | nothing. The same line asserts that v4, v5 and v6 are NOT set, so "each" overclaims (see Recommendation 1) | CARRIED |

CRITICAL
none

RECOMMENDATIONS
1. name-as-sentence (rules/testing.md) — tests/tmp/test_34_video_channel_name_wrong_instance_phase2.py:69
   `def test_repair_sets_each_video_to_its_own_channel_name(seeded_db):` says "each video", but the test expects v4, v5 and v6 to keep their stale names (`REPAIRED` at :24). The name also has no "when" clause, and it says nothing about the returned count or the idempotent second run, which are half of what the test asserts. A name like "repair sets foreign or NULL names to the own-instance display name, leaves unrepairable rows, and is idempotent" would let a failure read correctly without opening the file.
2. bounds (rules/testing.md) — tests/tmp/test_34_video_channel_name_wrong_instance_phase2.py:22
   The seed has no video with a NULL `channel_id`, which both schemas allow (`channel_id TEXT`, no NOT NULL). There is also no run on an empty `videos` table, where the repair should return 0. The NULL-name and empty or NULL display-name edges are covered.
3. No rule covers this — tests/tmp/test_34_video_channel_name_wrong_instance_phase2.py:87
   The test checks `has_videos_fts` on each shape but never reads `videos_fts` after the repair on the whitelist shape. The `videos_fts_au` trigger (sync-whitelist.py:279) or a rebuild is what would keep the full-text index in step with the repaired names. No clause in `must_prove` or the docstring claims this, so it is not a whole-claim defect. It is recorded because the test asserts the probe but not what the probe is for.

OBSERVATIONS
none

NOT ASSESSED
1. `code_under_test` path engine/server/db/jobs/repair-video-channel-names.py does not exist (marked NEW). I could not confirm the symbols `repair_channel_names` and `has_videos_fts`, or which inputs the job accepts. Bounds were judged from the two schemas: engine/crawler/schema.sql and engine/server/db/jobs/sync-whitelist.py:323-417.
2. `code_under_test` path tests/active/test_channel_names.py (marked EDITED) does not exist, and no `test_channel_names*.py` exists anywhere under tests/. Its edits could not be read.

## 2026-09-27 - Step 7 - Phase 2 (Repair function corrects channel names) - checkpoint outcome (run 1)

`tests/tmp/test_34_video_channel_name_wrong_instance_phase2.py` exited 0 after the phase landed.

<changes>
### `engine/server/db/jobs/repair-video-channel-names.py` (NEW)
A new job module with two functions, stdlib `sqlite3` only:
- `repair_channel_names(conn) -> int` runs one `UPDATE videos` statement inside `with conn:`, so it commits. It sets `channel_name` to the `display_name` of the channel matching the video's own `(channel_id, instance_domain)`. A row is only touched when that channel exists, its `display_name` is not NULL or empty, and the stored name differs from it (`IS NOT`, so NULL stored names get repaired too). It returns `cursor.rowcount`, the number of rows it changed, which makes a second run return 0. `channels` is only read, never written. On the whitelist shape, the existing `videos_fts_au` trigger re-indexes each changed row.
- `has_videos_fts(conn) -> bool` checks `sqlite_master` for the `videos_fts` table. It is True on the whitelist shape and False on the crawl shape.

There is no CLI entry point yet. The checkpoint only exercises the functions, and this phase's intent only calls for exposing `repair_channel_names`.

I did not touch `tests/active/test_channel_names.py`, which the phase lists as EDITED. It does not exist in the worktree yet, and nothing in this phase's checkpoint needs it. I read that entry as the promotion target for the checkpoint, which the workflow handles.

I checked the behaviour with a throwaway probe (`tests/tmp/probe_repair_rowcount.py`), using the same seed shape as the checkpoint on both a crawl-schema and a whitelist-schema database:
- **Both shapes:** the first call returned 3 and the second returned 0. After reopening the database, v1 and v7 read `A` and v2 read `B`, while v3–v6 kept their stored names.
- **Whitelist shape:** `has_videos_fts` was True, and `rowcount` was still 3 even with the FTS triggers firing. An FTS5 `integrity-check` passed after the update, and `channel_name:A` matched rowids 1 and 7.

I have no tool that deletes files, so the probe file is still in `tests/tmp/` and should be removed. It is not part of the phase.
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
  tests/tmp/test_34_video_channel_name_wrong_instance_phase2.py  2 passed                               0.0s
  -------------------------------------------------------------
  total                                                          2 passed                               0.2s wall, 1 lane

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

## 2026-09-27 - Step 7 - Phase 3 ("`. Asserts: `Alphachan` gives {v1, v7} and `Betachan` gives {v2, v3}, so v1's stale foreign name is gone; `COUNT(*)` on `videos_fts` equals `COUNT(*)` on `videos` (7).</checkpoint>
<name>Repair rebuilds the search index) - must_prove

Quoted from the phase Intent, written at Step 6 before the checkpoint was drafted.

Intent:
On a database that has `videos_fts`, the repair runs between `sync-whitelist.py`'s trigger drop and recreate and then rebuilds the index, so full-text search reflects the corrected channel names in full.

- C1 - After the repair, a `channel_name` MATCH for a channel's own name returns that channel's videos, and a MATCH for the other instance's same-id name does not return them.
- C2 - After the repair, `videos_fts` holds as many rows as `videos`.

must_prove:
- C1 - After the repair, a `channel_name` MATCH for a channel's own name returns that channel's videos, and a MATCH for the other instance's same-id name does not return them.
- C2 - After the repair, `videos_fts` holds as many rows as `videos`.

## 2026-09-27 - Step 7 - Phase 3 ("`. Asserts: `Alphachan` gives {v1, v7} and `Betachan` gives {v2, v3}, so v1's stale foreign name is gone; `COUNT(*)` on `videos_fts` equals `COUNT(*)` on `videos` (7).</checkpoint>
<name>Repair rebuilds the search index) - self-check (audit round 1, send-back 0)

`tests/tmp/test_34_video_channel_name_wrong_instance_phase3.py`, surface `checkpoint`. Collection exit 0.

- C1 - tests/tmp/test_34_video_channel_name_wrong_instance_phase3.py:77 — after repair_channel_names, read through a fresh connection, `channel_name : "Alphachan"` MATCH joined to videos returns exactly {"v1", "v7"} - expected: {"v1", "v7"}. I observed this in the probe run with repair + rebuild_videos_fts + commit: "REBUILT after ['v1', 'v7'] ...". - excludes: The current repair, which relies only on the per-row videos_fts_au trigger and never rebuilds, can't re-index v1. v1 was corrected in videos while the triggers were dropped, so the UPDATE's `IS NOT` guard skips it and the index keeps its foreign "Betachan". The run showed this reads {'v7'}. A rebuild that never commits reads the same through the reopened connection.
- C1 - tests/tmp/test_34_video_channel_name_wrong_instance_phase3.py:78 — the same MATCH for the other instance's same-id name, "Betachan", returns exactly {"v2", "v3"}, so a.example's v1 is not found under b.example's name - expected: {"v2", "v3"}. I observed this in the probe: "REBUILT after ... ['v2', 'v3']". - excludes: Under the trigger-only repair the index still carries v1 under "Betachan", and the probe read ['v1', 'v2', 'v3']. A repair that copied names across instances by channel_id alone would also put the wrong name back on v1 or v2 and break one of the two sets.
- C2 - tests/tmp/test_34_video_channel_name_wrong_instance_phase3.py:79 — (COUNT(*) FROM videos_fts_docsize, COUNT(*) FROM videos) == (8, 8) after the repair - expected: (8, 8). I observed this in the probe after repair + rebuild: "REBUILT after ... 8 8". - excludes: A repair that only fires row triggers never indexes v8. v8 was inserted while the triggers were dropped, and its channel's display name is empty, so the UPDATE skips it. The probe read "CURRENT after ... 7 8", which is (7, 8).
- C2 - tests/tmp/test_34_video_channel_name_wrong_instance_phase3.py:81 — the FTS5 `integrity-check` with rank 1 (which checks the index against the videos content table) runs without raising - expected: No exception. I observed this in the probe: "REBUILT integrity ok". - excludes: Under the trigger-only repair the index disagrees with videos (v1's stale name, v8 missing), and the probe showed "CURRENT integrity raised DatabaseError database disk image is malformed".

<assertions>
tests/tmp/test_34_video_channel_name_wrong_instance_phase3.py:65 - after the repair, read through a fresh connection, a `channel_name : "Alphachan"` MATCH (joined to videos by rowid) returns exactly {v1, v7}. This includes v1, whose stale index entry still said Betachan, and excludes v2 and v3, the other instance's same-id channel. Phase 2's code gives {v7} (observed), and a repair that never commits would give {v2}. - C1
tests/tmp/test_34_video_channel_name_wrong_instance_phase3.py:66 - `channel_name : "Betachan"` returns exactly {v2, v3}, so v1's foreign name is gone from the index. Phase 2's code gives {v1, v2, v3} (observed). - C1
tests/tmp/test_34_video_channel_name_wrong_instance_phase3.py:68 - COUNT(*) on `videos_fts_docsize`, the index's own per-row table, equals COUNT(*) on `videos`, and both are 7. This is a deviation the operator approved, replacing the vacuous COUNT(*) on `videos_fts`. It is 0 on an index that was never built (observed). - C2
tests/tmp/test_34_video_channel_name_wrong_instance_phase3.py:70 - the FTS5 `integrity-check` command passes, meaning the index agrees with `videos`. On Phase 2's code it raises `fts5: checksum mismatch for table "videos_fts"` (observed), and on an index that was never built it raises `database disk image is malformed`. - C2
tests/tmp/test_34_video_channel_name_wrong_instance_phase3.py:57 - a setup check, not a clause: before the repair the drifted index gives Alphachan={v2} and Betachan={v1, v3}, which shows the index still holds v1's stale name when the repair starts.
Current run against Phase 2's code: the setup check passes, and the test fails at line 65 with `{'v7'} == {'v1', 'v7'}`.
</assertions>

<probes>
tests/tmp/test_probe_34_phase3.py, run with ValidateTests ["tests/tmp/test_probe_34_phase3.py"] three times. Same v1-v7 / channels 7, 8, 9 seed as phase 2, on ensure_content_schema. It compares the current (Phase 2) repair_channel_names with a simulated Phase 3 (drop_videos_fts_triggers, then the same UPDATE, then create_videos_fts_triggers, rebuild_videos_fts, commit).
Agreed fixture (seed with triggers live): before the repair, Alphachan=['v2'] and Betachan=['v1','v3']. After the repair, both Phase 2 and the simulated Phase 3 give Alphachan=['v1','v7'] and Betachan=['v2','v3'], counts 7 7, integrity ok. So the agreed checkpoint could not fail on Phase 2's code.
Index never built (seeded with triggers dropped): COUNT(*) FROM videos_fts=7, videos=7, docsize 0, integrity 'database disk image is malformed'. Phase 2's repair raised 'database disk image is malformed'. The simulated Phase 3 gave ['v1','v7'] / ['v2','v3'], docsize 7, integrity ok. So COUNT(*) on the external-content videos_fts is vacuous.
Drifted fixture (normal seed, then v1 set to Alphachan with the triggers dropped, then the triggers recreated): before the repair, Alphachan=['v2'], Betachan=['v1','v3'], integrity 'fts5: checksum mismatch for table "videos_fts"', docsize 7. Phase 2: changed 2, then Alphachan=['v7'], Betachan=['v1','v2','v3'], still a checksum mismatch, docsize 7. Simulated Phase 3: Alphachan=['v1','v7'], Betachan=['v2','v3'], integrity ok, docsize 7.
Operator decision (AskUser): use the drifted fixture and measure C2 with docsize and integrity-check.
The checkpoint itself, run with ValidateTests ["tests/tmp/test_34_video_channel_name_wrong_instance_phase3.py"], fails at line 65: `assert {'v7'} == {'v1', 'v7'}`.
I have no delete tool, so the probe file tests/tmp/test_probe_34_phase3.py is still there and should be removed. It ends in `assert False`.
</probes>

<unassertable>
none. The agreed seam is changed in two ways the operator approved. (1) Before the repair, the fixture sets v1 to Alphachan with the triggers dropped, so the index is stale. On the fixture as agreed, the Phase 2 code already passes. (2) C2 is measured on `videos_fts_docsize` and with integrity-check, because COUNT(*) on `videos_fts` reads the content table and gives 7 even when the index is empty. The docsize count alone does not tell Phase 2 apart on the drifted fixture (it is 7 there too). The integrity-check is what does.
</unassertable>

### `tests/tmp/test_34_video_channel_name_wrong_instance_phase3.py` - 4067 characters, inlined in full

```
"""`repair_channel_names` from `repair-video-channel-names.py`, run in-process on a whitelist.db-shaped temp database whose `videos_fts` has drifted: seeded with foreign and NULL channel names, then v1 corrected while the triggers were dropped, so the index still holds v1's foreign name.

- After the repair, and read through a fresh connection, a `channel_name` MATCH on "Alphachan" returns exactly v1 and v7, and one on "Betachan" returns exactly v2 and v3, so neither name finds the other instance's same-id channel's videos.
- `videos_fts_docsize` holds as many rows as `videos` (7), and the FTS5 integrity-check passes.
"""
from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
JOBS_DIR = ROOT / "engine" / "server" / "db" / "jobs"

CHANNELS = [("7", "a.example", "Alphachan"), ("7", "b.example", "Betachan"), ("8", "a.example", ""), ("9", "a.example", None)]
# (video_id, instance_domain, channel_id, stored channel_name); channel 7 exists on both instances, so each instance's rows start with the other instance's name.
VIDEOS = [("v1", "a.example", "7", "Betachan"), ("v2", "b.example", "7", "Alphachan"), ("v3", "b.example", "7", "Betachan"), ("v4", "a.example", "8", "Stalename"), ("v5", "a.example", "9", "Stalename"), ("v6", "a.example", "404", "Orphanname"), ("v7", "a.example", "7", None)]
MATCH_SQL = "SELECT v.video_id FROM videos_fts JOIN videos v ON v.rowid = videos_fts.rowid WHERE videos_fts MATCH ?"


def _load_job(module_name: str, filename: str):
    spec = importlib.util.spec_from_file_location(module_name, JOBS_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def jobs():
    return _load_job("sync_whitelist_channel_names", "sync-whitelist.py"), _load_job("repair_video_channel_names", "repair-video-channel-names.py")


def _seed(conn: sqlite3.Connection) -> None:
    conn.executemany("INSERT INTO channels (channel_id, instance_domain, display_name) VALUES (?, ?, ?)", CHANNELS)
    conn.executemany("INSERT INTO videos (video_id, instance_domain, channel_id, channel_name, title, description, last_checked_at) VALUES (?, ?, ?, ?, 'clip ' || ?1, 'plain text', 1)", VIDEOS)


def _matches(conn: sqlite3.Connection, name: str) -> set:
    return {row[0] for row in conn.execute(MATCH_SQL, (f'channel_name : "{name}"',))}


def test_repaired_fts_finds_own_name_not_foreign_name(jobs, tmp_path):
    sync, repair = jobs
    db_path = tmp_path / "whitelist.db"
    conn = sqlite3.connect(db_path)
    try:
        sync.ensure_content_schema(conn)
        _seed(conn)
        conn.commit()
        # v1 corrected behind the index's back, as a repair that stopped before its rebuild leaves it; per-row triggers alone cannot mend this.
        sync.drop_videos_fts_triggers(conn)
        conn.execute("UPDATE videos SET channel_name = 'Alphachan' WHERE video_id = 'v1'")
        conn.commit()
        sync.create_videos_fts_triggers(conn)
        assert _matches(conn, "Alphachan") == {"v2"} and _matches(conn, "Betachan") == {"v1", "v3"}, "the index did not start out holding the stale names"
        repair.repair_channel_names(conn)
    finally:
        conn.close()

    # Reopened, so a rebuild that never commits reads back as the stale index.
    conn = sqlite3.connect(db_path)
    try:
        assert _matches(conn, "Alphachan") == {"v1", "v7"}  # C1
        assert _matches(conn, "Betachan") == {"v2", "v3"}  # C1
        # COUNT(*) on the external-content videos_fts reads the videos table, so the index's own row count is taken from its docsize shadow table.
        assert conn.execute("SELECT COUNT(*) FROM videos_fts_docsize").fetchone()[0] == conn.execute("SELECT COUNT(*) FROM videos").fetchone()[0] == 7  # C2
        # Raises DatabaseError when the index disagrees with videos.
        conn.execute("INSERT INTO videos_fts (videos_fts, rank) VALUES ('integrity-check', 1)")  # C2
    finally:
        conn.close()

```


Gate: satisfied

## 2026-09-27 - Step 7 - Phase 3 ("`. Asserts: `Alphachan` gives {v1, v7} and `Betachan` gives {v2, v3}, so v1's stale foreign name is gone; `COUNT(*)` on `videos_fts` equals `COUNT(*)` on `videos` (7).</checkpoint>
<name>Repair rebuilds the search index) - red (audit round 1)

`tests/tmp/test_34_video_channel_name_wrong_instance_phase3.py` exited 1.

```
  tests/tmp/test_34_video_channel_name_wrong_instance_phase3.py  1 failed                               0.0s
  -------------------------------------------------------------
  total                                                          1 failed                               0.2s wall, 1 lane

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

## 2026-09-27 - Step 7 - Phase 3 ("`. Asserts: `Alphachan` gives {v1, v7} and `Betachan` gives {v2, v3}, so v1's stale foreign name is gone; `COUNT(*)` on `videos_fts` equals `COUNT(*)` on `videos` (7).</checkpoint>
<name>Repair rebuilds the search index) - audit (round 1)

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
The test should fail at line 77, `assert _matches(conn, "Alphachan") == {"v1", "v7"}`, because the result will be `{"v7"}`. `repair_channel_names` currently runs only `REPAIR_CHANNEL_NAMES_SQL`, with no rebuild. That UPDATE skips v1, since v1's `channel_name` already equals `'Alphachan'`, so the index keeps v1 under "Betachan". Meanwhile the `videos_fts_au` trigger moves v2 out of "Alphachan".

NOT ASSESSED
1. `code_under_test` listed `tests/active/test_channel_names.py`, which does not exist at that path. It was not read, and nothing in the verdict relies on it.
2. The anti-pattern pass found no match in `shape.md`:
   - The test reads no `.md` file (`doc-lint-grep`, `section-scoped-substring-grep`, `whole-file-source-name-grep`).
   - No code constant is compared to an inline literal (`hardcoded-spec-mirror`).
   - The expected sets at lines 77–79 are written out, not recomputed (`tautological-assertion`).
   - Every post-repair assertion is positive (`absence-only-assertion`).
   - The repair job and the FTS index sit between the seeded names and the video-id sets that are read back (`echoed-literal`).
   - Two names are checked against an uneven seed (v1 and v7 under Alphachan; v2 and v3 under Betachan), and the count comes from `videos_fts_docsize`, which is stored apart from `videos` (`single-value-pin`).
3. Ladder pass: the test runs at rung 1, calling `repair.repair_channel_names(conn)` directly at line 70. It asserts at rung 3, on rows read back from the database through a fresh connection at lines 75–81. That is the highest rung this database-state invariant supports. There is no downshift, so no comment is needed.
4. Stub question: the test would fail against each of these wrong implementations:
   - A no-op: line 77 gets `{"v2"}`.
   - The current trigger-only UPDATE: line 77 gets `{"v7"}`.
   - A rebuild that never commits: the reopen at line 75 reads back the stale index.
   - A version that re-indexes only the changed rows: line 79 gets `(7, 8)`, because v8 is never indexed.

   Lines 68–69 check that the seeded drift is really there before the repair runs, so the post-repair assertions cannot pass just because the setup never made the index go stale.

### devsecops-test-claim-auditor

CLAIM AUDIT — VERDICT: PASS

CLAUSE MAP  (13 clauses: 3 must_prove, 7 docstring, 3 name)
| id | source | clause | assertion | excludes | status |
|---|---|---|---|---|---|
| C1a | must_prove | own-name MATCH returns that channel's videos | :77, :78 | a repair that corrects `videos` but leaves the index holding v1's stale "Betachan" (v1 would be missing from Alphachan); a repair that skips NULL-named v7 | CARRIED |
| C1b | must_prove | other instance's same-id name does not return them | :77, :78 | set equality means a stale index that still returns v1 for "Betachan", or v2 for "Alphachan", fails; a join on `channel_id` alone would put v2/v3 under Alphachan | CARRIED |
| C2 | must_prove | `videos_fts` holds as many rows as `videos` | :79, :81 | a repair that relies on the per-row trigger alone, so v8 (empty display name, never updated) is never indexed: docsize 7 ≠ 8, and the integrity-check raises | CARRIED |
| D1 | docstring | "`videos_fts` has drifted … still holds v1's foreign name and has no row for v8" | :68, :69 | a fixture whose index was never stale, which would let a no-op repair pass | CARRIED |
| D2 | docstring | "read through a fresh connection" | :75 (reads at :77–:81) | a repair whose rebuild never commits and so reads back as the stale index | CARRIED |
| D3 | docstring | "Alphachan" returns exactly v1 and v7 | :77 | a missed v1/v7, or an extra row from the other instance | CARRIED |
| D4 | docstring | "Betachan" returns exactly v2 and v3 | :78 | v1's stale entry lingering, or v2 left out | CARRIED |
| D5 | docstring | "neither name finds the other instance's same-id channel's videos" | :77, :78 | same-id foreign matches, ruled out by the exact-set comparison | CARRIED |
| D6 | docstring | `videos_fts_docsize` holds as many rows as `videos` (8) | :79 | an index missing v8 (7, 8) | CARRIED |
| D7 | docstring | "the FTS5 integrity-check passes" | :81 | an index that disagrees with the `videos` content (raises DatabaseError) | CARRIED |
| N1 | name | "repaired fts" (state after the repair) | :70 then :77–:81 | assertions are taken after `repair_channel_names` runs, with the before-state pinned at :68–:69 | CARRIED |
| N2 | name | "finds own name" | :77, :78 | own-name MATCH missing the channel's videos | CARRIED |
| N3 | name | "not foreign name" | :77, :78 | foreign same-id name still matching, ruled out by exact-set equality | CARRIED |

CRITICAL
none

RECOMMENDATIONS
1. bounds (rules/testing.md) — tests/tmp/test_34_video_channel_name_wrong_instance_phase3.py:17–19
   The seed includes these edge rows:
   - v4/v8: channel 8 with an empty `display_name`
   - v5: channel 9 with a NULL `display_name`
   - v6: orphan channel 404

   Their only effect on the result is through the row count at :79. Nothing checks that they keep their stored name, which is the behaviour `repair_channel_names`'s docstring promises ("Rows whose channel is missing or has no display name keep their stored name"). A MATCH on "Stalename" and on "Orphanname" would cover these edges.
2. normal-and-abnormal-paths (rules/testing.md) — tests/tmp/test_34_video_channel_name_wrong_instance_phase3.py:54
   Only the success path is tested. No test covers how the repair behaves where it is expected to fail or do nothing, for example a crawl-shaped database without `videos_fts` (`has_videos_fts`) or an index that cannot be rebuilt. This is outside `must_prove`, so it does not block.

OBSERVATIONS
none

NOT ASSESSED
1. `code_under_test` listed tests/active/test_channel_names.py (EDITED), but the path does not exist and Glob found no `test_channel_names.py` under tests/. I could not check whether the suite covers the abnormal-path and bounds cases above somewhere else.

## 2026-09-27 - Step 7 - Phase 3 ("`. Asserts: `Alphachan` gives {v1, v7} and `Betachan` gives {v2, v3}, so v1's stale foreign name is gone; `COUNT(*)` on `videos_fts` equals `COUNT(*)` on `videos` (7).</checkpoint>
<name>Repair rebuilds the search index) - checkpoint outcome (run 1)

`tests/tmp/test_34_video_channel_name_wrong_instance_phase3.py` exited 0 after the phase landed.

<changes>
I ran none of the gating tests myself. Everything I checked came from a throwaway probe, described below.

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
  tests/tmp/test_34_video_channel_name_wrong_instance_phase3.py  1 passed                               0.0s
  -------------------------------------------------------------
  total                                                          1 passed                               0.2s wall, 1 lane

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

## 2026-09-27 - Step 7 - Phase 4 (Repair CLI) - must_prove

Quoted from the phase Intent, written at Step 6 before the checkpoint was drafted.

Intent:
`repair-video-channel-names.py` runs as a command that refuses to start without an explicit `--db` and logs the number of rows it changed.

- C1 - Invoking the job without `--db` exits with an argparse usage error (return code 2).
- C2 - Invoking the job with `--db` logs `channel names repaired rows=N` with the changed count.

must_prove:
- C1 - Invoking the job without `--db` exits with an argparse usage error (return code 2).
- C2 - Invoking the job with `--db` logs `channel names repaired rows=N` with the changed count.

## 2026-09-27 - Step 7 - Phase 4 (Repair CLI) - self-check (audit round 1, send-back 0)

`tests/tmp/test_34_video_channel_name_wrong_instance_phase4.py`, surface `checkpoint`. Collection exit 0.

- C1 - tests/tmp/test_34_video_channel_name_wrong_instance_phase4.py:41 — the bare invocation `[sys.executable, REPAIR_JOB]` has returncode == 2; lines 42 and 43 back it: stderr contains argparse's "the following arguments are required: --db", and no `channel names repaired rows=N` line is logged - expected: returncode 2, and stderr reads `usage: ... --db PATH\n...: error: the following arguments are required: --db\n`. Observed by probe: a parser built with CompactHelpFormatter and `--db required=True, metavar="PATH"` exits 2 with exactly that message. No repair line is logged. - excludes: The script as it stands, with no CLI entry point: exit 0 and empty stdout and stderr (observed, and this is today's red at :41). A `--db` that has a default, as its neighbours do: exit 0 and a repair of the default database logged, so :41 and :43 fail. An exit 2 caused by anything other than the missing `--db` (for example a crash from a bad import) fails :42.
- C2 - tests/tmp/test_34_video_channel_name_wrong_instance_phase4.py:58 and :64 — `re.findall(r"channel names repaired rows=(\d+)", stderr)` is exactly ["3"] on the first `--db` run and exactly ["0"] on the second. :60 ties the 3 to the rows that actually changed (v1, v2 and v7). :57 and :63 require exit 0. - expected: First run: ["3"] and the names become {v1: Alphachan, v2: Betachan, v3: Betachan, v4: Stalename, v5: Stalename, v6: Orphanname, v7: Alphachan}. Second run: ["0"] with the names unchanged. Observed by probe on this exact inline seed: `repair_channel_names` returned 3, then 0, and left those names. A `logging.basicConfig(level=INFO, format="%(levelname)s %(message)s")` line was observed on stderr as `INFO channel names repaired rows=3`. - excludes: A `--db` run that repairs but logs nothing, or prints to stdout: [] at :58. The script today exits 0 with empty stderr (observed). A hard-coded or cumulative count: ["3"] at :64. Logging the matched or total rows instead of the changed ones: ["4"] (with v3) or ["7"] at :58. A CLI that logs 3 but never calls the repair or never commits: the names at :60 stay as STORED.

<assertions>
tests/tmp/test_34_video_channel_name_wrong_instance_phase4.py:41 - running the script with no arguments exits with return code 2 (C1)
tests/tmp/test_34_video_channel_name_wrong_instance_phase4.py:42 - that run's stderr contains argparse's "the following arguments are required: --db", so the code 2 comes from `--db` being required and not from some other failure (C1)
tests/tmp/test_34_video_channel_name_wrong_instance_phase4.py:43 - that run logs no `channel names repaired rows=N` line, so nothing was repaired against a default DB (C1)
tests/tmp/test_34_video_channel_name_wrong_instance_phase4.py:54 - control, not a clause: the inline crawl-schema seed reads back as the stored names before the job runs
tests/tmp/test_34_video_channel_name_wrong_instance_phase4.py:57 - the first `--db` run against the seeded crawl-shape DB exits 0 (C2)
tests/tmp/test_34_video_channel_name_wrong_instance_phase4.py:58 - `re.findall(r"channel names repaired rows=(\d+)", stderr)` is exactly ["3"]: one log line, carrying the changed count (C2)
tests/tmp/test_34_video_channel_name_wrong_instance_phase4.py:60 - the DB then reads v1, v2 and v7 as their own channel's name, with v3 to v6 unchanged, so the 3 that was logged really is the number of rows changed (C2)
tests/tmp/test_34_video_channel_name_wrong_instance_phase4.py:63 - the second `--db` run exits 0 (C2)
tests/tmp/test_34_video_channel_name_wrong_instance_phase4.py:64 - the second run's log is exactly ["0"], which rules out a hard-coded or cumulative count (C2)
tests/tmp/test_34_video_channel_name_wrong_instance_phase4.py:65 - the second run leaves the repaired names as they were (C2)
Red run observed: against the current script, which has no CLI, the test fails at line 41 because the bare invocation exits 0 and not 2.
</assertions>

<probes>
Probe file: tests/tmp/probe_34_phase4_cli.py. Command: ValidateTests ["tests/tmp/probe_34_phase4_cli.py", "-s"]. Output:
BARE current 0 '' '' - with the current script (no main), a bare invocation exits 0 and prints nothing. This is the wrong-implementation value for C1.
WITHDB current 0 '' '' - a `--db` run exits 0 with empty stderr, so the log regex finds nothing. This is the wrong-implementation value for C2.
ARGPARSE required 2 'usage: -c [-h] --db DB\n-c: error: the following arguments are required: --db\n' - argparse's exit code and message when `--db` is required and missing.
LOGGING '' 'INFO channel names repaired rows=3\n' - `logging.basicConfig` in the style of the sibling jobs writes to stderr, not stdout.
inproc first 3 second 0 - `repair_channel_names` on the same inline crawl-shape seed changes 3 rows, then 0.
names [('v1','Alphachan'),('v2','Betachan'),('v3','Betachan'),('v4','Stalename'),('v5','Stalename'),('v6','Orphanname'),('v7','Alphachan')] - the names after repair.
The probe file tests/tmp/probe_34_phase4_cli.py is still on disk: none of my tools can delete a file. It needs removing.
</probes>

<unassertable>
none
</unassertable>

### `tests/tmp/test_34_video_channel_name_wrong_instance_phase4.py` - 3747 characters, inlined in full

```
"""`repair-video-channel-names.py` run as a command, through `sys.executable`, against a crawl.db-shaped temp database seeded with foreign, NULL, correct and unrepairable channel names.

- Run with no arguments it exits 2 with argparse's usage error naming `--db` as required, and logs no repair.
- Run with `--db` it exits 0 and logs `channel names repaired rows=3` exactly once, and the database then reads v1, v2 and v7 as their own channel's display name while v3 to v6 keep their stored names.
- Run again it exits 0 and logs `channel names repaired rows=0`.
"""
from __future__ import annotations

import re
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPAIR_JOB = ROOT / "engine" / "server" / "db" / "jobs" / "repair-video-channel-names.py"
CRAWL_SCHEMA = ROOT / "engine" / "crawler" / "schema.sql"

CHANNELS = [("7", "a.example", "Alphachan"), ("7", "b.example", "Betachan"), ("8", "a.example", ""), ("9", "a.example", None)]
# (video_id, instance_domain, channel_id, stored channel_name); channel 7 exists on both instances, so each instance's rows start with the other instance's name.
VIDEOS = [("v1", "a.example", "7", "Betachan"), ("v2", "b.example", "7", "Alphachan"), ("v3", "b.example", "7", "Betachan"), ("v4", "a.example", "8", "Stalename"), ("v5", "a.example", "9", "Stalename"), ("v6", "a.example", "404", "Orphanname"), ("v7", "a.example", "7", None)]
STORED = {"v1": "Betachan", "v2": "Alphachan", "v3": "Betachan", "v4": "Stalename", "v5": "Stalename", "v6": "Orphanname", "v7": None}
REPAIRED = {"v1": "Alphachan", "v2": "Betachan", "v3": "Betachan", "v4": "Stalename", "v5": "Stalename", "v6": "Orphanname", "v7": "Alphachan"}
REPAIRED_LOG = r"channel names repaired rows=(\d+)"


def _names(db_path: Path) -> dict:
    conn = sqlite3.connect(db_path)
    try:
        return dict(conn.execute("SELECT video_id, channel_name FROM videos").fetchall())
    finally:
        conn.close()


def _run(tmp_path: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(REPAIR_JOB), *args], cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", timeout=60)


def test_cli_requires_db_and_logs_changed_count(tmp_path):
    bare = _run(tmp_path)
    assert bare.returncode == 2, f"stdout: {bare.stdout} stderr: {bare.stderr}"  # C1
    assert "the following arguments are required: --db" in bare.stderr  # C1
    assert re.findall(REPAIRED_LOG, bare.stderr) == []  # C1

    db_path = tmp_path / "crawl.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(CRAWL_SCHEMA.read_text(encoding="utf-8"))
        conn.executemany("INSERT INTO channels (channel_id, instance_domain, display_name) VALUES (?, ?, ?)", CHANNELS)
        conn.executemany("INSERT INTO videos (video_id, instance_domain, channel_id, channel_name, title, description, last_checked_at) VALUES (?, ?, ?, ?, 'clip ' || ?1, 'plain text', 1)", VIDEOS)
        conn.commit()
    finally:
        conn.close()
    assert _names(db_path) == STORED, "the seed did not land as written"

    first = _run(tmp_path, "--db", str(db_path))
    assert first.returncode == 0, f"stdout: {first.stdout} stderr: {first.stderr}"  # C2
    assert re.findall(REPAIRED_LOG, first.stderr) == ["3"], f"stderr: {first.stderr}"  # C2
    # The logged count is only the changed count if exactly those three rows changed.
    assert _names(db_path) == REPAIRED  # C2

    second = _run(tmp_path, "--db", str(db_path))
    assert second.returncode == 0, f"stdout: {second.stdout} stderr: {second.stderr}"  # C2
    assert re.findall(REPAIRED_LOG, second.stderr) == ["0"], f"stderr: {second.stderr}"  # C2
    assert _names(db_path) == REPAIRED  # C2

```


Gate: satisfied

## 2026-09-27 - Step 7 - Phase 4 (Repair CLI) - red (audit round 1)

`tests/tmp/test_34_video_channel_name_wrong_instance_phase4.py` exited 1.

```
  tests/tmp/test_34_video_channel_name_wrong_instance_phase4.py  1 failed                               0.0s
  -------------------------------------------------------------
  total                                                          1 failed                               0.2s wall, 1 lane

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

## 2026-09-27 - Step 7 - Phase 4 (Repair CLI) - audit (round 1)

- AUDIT: devsecops-test-shape-auditor - PASS
- AUDIT: devsecops-test-claim-auditor - PASS
- OUTSTANDING: nothing

### devsecops-test-shape-auditor

```
SHAPE AUDIT — VERDICT: PASS

CRITICAL
none

RECOMMENDATIONS
none

PREDICTED FAILURE
Fails at line 41 on `assert bare.returncode == 2`. The job has no argparse
parser and no `__main__` entry point: it only defines `REPAIR_CHANNEL_NAMES_SQL`,
`_load_sync_whitelist`, `has_videos_fts` and `repair_channel_names`. Running it
with no arguments imports those definitions and exits 0, so the assertion sees
0 where it expects 2.

NOT ASSESSED
1. `code_under_test` listed tests/active/test_channel_names.py, which does not
   resolve (FileNotFoundError), so it was not read. The verdict rests on
   test_path and engine/server/db/jobs/repair-video-channel-names.py only.
2. engine/crawler/schema.sql (read at test_path:48) exists but was not read.
   Whether its `channels` and `videos` columns match the INSERTs at
   test_path:49-50 was not checked.
```

### devsecops-test-claim-auditor

```
CLAIM AUDIT — VERDICT: PASS

CLAUSE MAP  (16 clauses: 4 must_prove, 10 docstring, 2 name)
| id | source | clause | assertion | excludes | status |
|---|---|---|---|---|---|
| C1a | must_prove | without `--db` exits with return code 2 | :41 | a job that runs with a default path, or exits 0/1 | CARRIED |
| C1b | must_prove | the exit is an argparse usage error | :42 | a hand-rolled exit 2, or a usage error about some other argument | CARRIED |
| C2a | must_prove | with `--db` logs `channel names repaired rows=N` | :58, :64 | no log line, a reworded line, or one written only to stdout | CARRIED |
| C2b | must_prove | N is the changed count | :58, :60, :64 | logging the total videos (7), the rows the WHERE matched including skipped ones, or a constant (the second run must log 0 while the first logs 3) | CARRIED |
| D1 | docstring | "run as a command, through `sys.executable`, against a crawl.db-shaped temp database seeded with foreign, NULL, correct and unrepairable channel names" | :36, :48-50, :54 | a seed that did not land as written, which would make every later check meaningless | CARRIED |
| D2 | docstring | "Run with no arguments it exits 2" | :41 | any other exit code | CARRIED |
| D3 | docstring | "argparse's usage error naming `--db` as required" | :42 | an error that does not name `--db`, or does not call it required | CARRIED |
| D4 | docstring | "and logs no repair" | :43 | a job that repairs something before it rejects the arguments | CARRIED |
| D5 | docstring | "Run with `--db` it exits 0" | :57 | a non-zero exit on success | CARRIED |
| D6 | docstring | "logs `channel names repaired rows=3` exactly once" | :58 | a wrong count, or the line logged twice (findall == ["3"]) | CARRIED |
| D7 | docstring | "v1, v2 and v7 read as their own channel's display name" | :60 | a name copied from the same id on another instance, or a NULL left in place | CARRIED |
| D8 | docstring | "v3 to v6 keep their stored names" | :60 | overwriting with '' or NULL, or touching the orphan row | CARRIED |
| D9 | docstring | "Run again it exits 0" | :63 | a failure on the second run | CARRIED |
| D10 | docstring | "logs `channel names repaired rows=0`" | :64 | counting matched rows instead of changed ones, or a fixed count | CARRIED |
| N1 | name | "cli requires db" | :41, :42 | a CLI that accepts a missing `--db` | CARRIED |
| N2 | name | "logs changed count" | :58, :60, :64 | a logged count that is not the number of rows changed | CARRIED |

CRITICAL
none

RECOMMENDATIONS
1. bounds (rules/testing.md) — tests/tmp/test_34_video_channel_name_wrong_instance_phase4.py:56
   `--db` is only tested with a valid seeded database. These `--db` edges are never
   tried: the flag given with no value, a path that does not exist (sqlite3.connect
   would quietly create an empty file there), and a file that is not a database.
2. normal-and-abnormal-paths (rules/testing.md) — tests/tmp/test_34_video_channel_name_wrong_instance_phase4.py:39
   The failure path is tested only for a missing argument. Nothing covers how the job
   fails when `--db` names a database the repair cannot run against, such as one with
   no `videos` table.

OBSERVATIONS
none

NOT ASSESSED
1. `code_under_test` listed tests/active/test_channel_names.py, which does not resolve
   in this worktree. Anything it adds was not read.
2. engine/server/db/jobs/repair-video-channel-names.py as read has no argument parsing
   and no logging. So whether `--db` is required, and where the `rows=N` line is
   written, came from `must_prove` and the test, not from the code.
```

## 2026-09-27 - Step 7 - Phase 4 (Repair CLI) - checkpoint outcome (run 1)

`tests/tmp/test_34_video_channel_name_wrong_instance_phase4.py` exited 0 after the phase landed.

<changes>
### `engine/server/db/jobs/repair-video-channel-names.py`
- Added a command line that follows `recompute-popularity.py` and `sync-whitelist.py`. It appends `engine/server` to `sys.path` and imports `CompactHelpFormatter` from `scripts.cli_format`.
- Added `main()`, called under an `if __name__ == "__main__"` guard. It uses argparse with `CompactHelpFormatter` and a single `--db PATH` argument that is required and has no default. The neighbouring jobs default to the shared `whitelist.db`, and a migration run with no arguments must never hit that by accident.
- Logging is set up with `logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")`.
- A `--db` path that is not an existing file is rejected with `parser.error("database not found: ...")`, which exits 2. Without this check, `sqlite3.connect` would quietly create an empty file and then fail on the missing tables.
- After the path check, `main()` opens the connection, calls the existing `repair_channel_names(conn)`, closes the connection in `finally`, and logs `channel names repaired rows=%d`.
- `repair_channel_names`, the SQL and the FTS handling are unchanged.

### `tests/active/test_channel_names.py`
- Not touched. It does not exist in the worktree yet, and this phase's checkpoint lives in `tests/tmp/`. I take the EDITED entry to mean the checkpoint gets promoted there, which the workflow handles. Phase 3 read it the same way.
</changes>

<inner_tests>
none
</inner_tests>

<unanticipated>
tests/tmp/probe_34_phase4_impl.py - a throwaway probe. It checked that the edited module still loads in-process through `importlib` (phases 2 and 3 load it that way) now that it changes `sys.path` and imports `scripts.cli_format`. It also checked the four CLI cases. A bare run exits 2 with `the following arguments are required: --db`. A missing `--db` path exits 2 with `database not found` and creates no file. The seeded crawl DB logs `INFO channel names repaired rows=3`, and a second run logs `rows=0`. I have no delete tool, so please remove it. `tests/tmp/probe_34_phase4_cli.py`, left over from authoring the checkpoint, is still there too and can go with it.
</unanticipated>

<awaiting_operator>
none
</awaiting_operator>

```
  tests/tmp/test_34_video_channel_name_wrong_instance_phase4.py  1 passed                               0.0s
  -------------------------------------------------------------
  total                                                          1 passed                               0.3s wall, 1 lane

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

## 2026-09-27 - Step 8 - clause accounting

- P1C1 - carried - rests on: the last audit of `tests/tmp/test_34_video_channel_name_wrong_instance_phase1.py`
- P1C2 - carried - rests on: the last audit of `tests/tmp/test_34_video_channel_name_wrong_instance_phase1.py`
- P2C1 - carried - rests on: the last audit of `tests/tmp/test_34_video_channel_name_wrong_instance_phase2.py`
- P2C2 - carried - rests on: the last audit of `tests/tmp/test_34_video_channel_name_wrong_instance_phase2.py`
- P3C1 - carried - rests on: the last audit of `tests/tmp/test_34_video_channel_name_wrong_instance_phase3.py`
- P3C2 - carried - rests on: the last audit of `tests/tmp/test_34_video_channel_name_wrong_instance_phase3.py`
- P4C1 - carried - rests on: the last audit of `tests/tmp/test_34_video_channel_name_wrong_instance_phase4.py`
- P4C2 - carried - rests on: the last audit of `tests/tmp/test_34_video_channel_name_wrong_instance_phase4.py`

## 2026-09-27 - Step 8 - refactor pass

<refactors>
none
</refactors>

<left_out>
engine/crawler/src/videos-worker.ts and dist/videos-worker.js: the four copies of the per-host error-classification catch block in processTagInstance/processCommentsInstance, the three identical groupByInstance* functions, the three identical *WorkerLoop functions and the unused TAGS_CONCURRENCY constant were all there before this build and are outside the lines it changed. Folding them together would grow the build past what was approved, so they belong in their own issue.
engine/crawler/dist/videos-worker.js: I made no source edit, because every edit to src has to be mirrored in the dist by hand. I have no shell to run `npm run build`, so I could not confirm that tsc output would match. I checked by grep that src and dist call channelMetaKey at the same two sites and define the same helper.
engine/server/db/jobs/repair-video-channel-names.py: `int(changed)` wraps a `rowcount` that is already an int. Removing the wrapper would be cosmetic, and no probe run backs it, so I left the file exactly as it passed Phases 2–4.
tests/tmp: the leftover probe files (probe_34_phase2_seed.py, probe_34_phase3_impl.py, probe_34_phase4_impl.py, probe_34_phase4_cli.py, probe_34_fts_rowcount.py, probe_34_urls.py, test_probe_34_phase2.py, test_probe_34_phase3.py, test_probe_34_phase4_selfcheck.py, test_probe_34_urls.py) are not part of any phase and need deleting. I have no delete tool. The four test_probe_* files will be collected if tests/tmp is ever run as a directory.
tests/active/test_channel_names.py: it still does not exist. The gating checkpoints are only in tests/tmp/test_34_video_channel_name_wrong_instance_phase1–4.py, and moving them to the permanent location is the workflow's job, not this pass's.
Step prompt: the "What the pass is measured against" section arrived as a literal `{rat_tail_rules}` placeholder, so I checked the pass against the role's rat-tail rule instead. The one simplification this build added (the executescript commit in repair_channel_names) already carries a rat-tail comment naming its limit and upgrade path.
</left_out>

<needs_fresh_red>
none
</needs_fresh_red>

<observation>
This build's code is already minimal and matches the style of the files it landed in, so I made no refactors: the channelMetaKey change is the same in src and dist (checked by grep) and the repair job needs no restructuring.
</observation>

## 2026-09-27 - Step 8 - suite comparison (attempt 1)

`--compare` exited 0.

```
selected 1 of 20 test groups (19 unchanged):
  test_search_fusion.py — no map entry
  test_search_fusion.py  10 passed                              1.8s
  ---------------------
  total                  10 passed                              2.0s wall, 1 lane

nothing moved against the previous record

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

## 2026-09-27 - Step 9 - document triage

- [ ] `DATA_BUILD.md` - The file documents no way to correct `videos.channel_name` in existing databases, and `engine/server/db/jobs/repair-video-channel-names.py` now exists for that. Add a section between "## 2) Filter to JoinPeerTube whitelist" (ends line 158) and "## 3) Build embeddings", written as current state, with no "previously" and no bug history beyond a one-line reason. The reason: rows written before the crawler keyed channel metadata by host plus id hold the display name of a same-id channel on another instance.

The section should say:
- The repair is a migration of shared databases. Run it on main after merge only, never from a worktree.
- Run it outside an updater cycle, with the Engine idle or stopped. On `whitelist.db` it drops the FTS triggers, updates, recreates them and rebuilds `videos_fts`, and the rebuild holds the write lock.
- The order:
  1. Merge.
  2. `python3 engine/server/db/jobs/repair-video-channel-names.py --db engine/crawler/data/crawl.db`.
  3. The same command with `--db` on every `whitelist.db` copy, prod included, because `merge_rules.json` merges `videos` INSERT_ONLY and the updater never corrects existing prod rows.
  4. Operator follow-up: `build-video-embeddings.py --db-path engine/server/db/whitelist.db --force`, then `build-ann-index.py` and `precompute-similar-ann.py` with the flags this file already documents in sections 4 and 5. Schedule it with the stable-ANN-ids cutover so the index is rebuilt once. Cite `docs/project/issues/08-stable-ann-ids.md` or "plan 17" without a path, because `docs/project/plans/17-stable-ann-ids.md` does not exist.

Describe what landed:
- `--db PATH` is required and has no default.
- A path that does not exist is rejected with exit 2 ("database not found").
- It logs `channel names repaired rows=N`. It is idempotent: a second run logs `rows=0`.
- It only changes rows whose own `(channel_id, instance_domain)` channel has a non-empty `display_name` that differs from the stored name, and it never writes `channels`.
- On a DB with `videos_fts` it rebuilds the index on every run and fails with a RuntimeError if the `videos_fts` count differs from `videos`. A failed rebuild is recovered by re-running the job, because the update is already committed.
- On `crawl.db` (no FTS) it skips the index steps.
- It loads `sync-whitelist.py`, which parses `engine/crawler/schema.sql`, on the FTS path.

Line 30 points at `engine/server/db/jobs/UPDATER_WORKER.md`, but the file is at `engine/server/db/jobs/docs/UPDATER_WORKER.md`. This broken reference was already there; fix it only if this edit touches that line.
- [ ] `docs/project/issues/34-video-channel-name-wrong-instance.md` - The build delivered the issue, so its record is now wrong:
- `Status: bug, ready-for-agent` (line 3) becomes `Status: bug, complete`.
- Tick the acceptance criteria (lines 77-83).
- Move the file to `docs/project/issues/archive/` per `docs/project/triage-labels.md`.

Record these points:
- Still owed by the operator on main: `repair-video-channel-names.py` on `crawl.db` and on every `whitelist.db` copy, prod included, then the re-embed, ANN rebuild and similarity precompute.
- The writer fix landed in both `videos-worker.ts` and the committed `dist/videos-worker.js`. The dist was edited by hand without `npm run build`, so a real `npm run build` should be run and the dist diff confirmed before or at merge.

Line 45 already says the crawl slug and `channel_url` came out right. Make the correction precise: the slug comes from the per-host progress row, so only `displayName` and the `channelUrl` fallback were affected.

Line 54 cites `docs/project/plans/17-stable-ann-ids.md`, which does not exist. Point it at `docs/project/issues/08-stable-ann-ids.md`, or name "plan 17" without a path.

Line 19 ("Cards: ... builds wrong channel links") is contradicted by the line-49 finding (effectively no card impact). Reconcile it so the archived record does not claim a card fault.

Out of scope:
- [ ] `engine/server/db/jobs/docs/UPDATER_WORKER.md` - It never mentions `channel_name`, the repair, or `INSERT_ONLY` by name. Its claims (line 71: prod gets merged changes according to `merge_rules.json`; line 88: the worker stops the Engine around the merge) are still true, because the build changed no updater, merge or rule behaviour. The operational guidance (INSERT_ONLY means every prod `whitelist.db` must be repaired directly, and no repair during an updater cycle) goes in the new DATA_BUILD.md section, so the optional note would duplicate it.
- [ ] `docs/project/issues/plan.md` - It is a sequencing plan. Its lines on issue 34 (line 62: the repair runs on main after the merge; line 150: migrations run on main after merge) are still accurate descriptions of the intended order. It says nothing about the writer or the repair that the build made false. Issue status is tracked in the issue file.
- [ ] `CONTEXT.md` - The glossary's only channel-related term is **Block** (`instance_domain` + `channel_id`), which the build does not touch. It defines no term for `channel_name`, the crawler's channel metadata, or data repairs, and the build introduces no new domain concept that needs a glossary entry.

ADR conflicts: none

## 2026-09-27 - Step 9 - Update documentation

- [x] `DATA_BUILD.md` - updated: Added a "Repair video channel names (one-time migration)" subsection to `DATA_BUILD.md` at the end of step 2. It gives the repair command, the order to run it in, and how it behaves.
- [x] `docs/project/issues/34-video-channel-name-wrong-instance.md` - updated: Issue 34 is marked complete with a Delivered record, its wrong claims are corrected, and six of its seven criteria are ticked. **It is still in `docs/project/issues/`: please run `git mv docs/project/issues/34-video-channel-name-wrong-instance.md docs/project/issues/archive/`**, because I have no tool that can move or delete files.
- [x] `engine/server/db/jobs/docs/UPDATER_WORKER.md` - out of scope: It never mentions `channel_name`, the repair, or `INSERT_ONLY` by name. Its claims (line 71: prod gets merged changes according to `merge_rules.json`; line 88: the worker stops the Engine around the merge) are still true, because the build changed no updater, merge or rule behaviour. The operational guidance (INSERT_ONLY means every prod `whitelist.db` must be repaired directly, and no repair during an updater cycle) goes in the new DATA_BUILD.md section, so the optional note would duplicate it.
- [x] `docs/project/issues/plan.md` - out of scope: It is a sequencing plan. Its lines on issue 34 (line 62: the repair runs on main after the merge; line 150: migrations run on main after merge) are still accurate descriptions of the intended order. It says nothing about the writer or the repair that the build made false. Issue status is tracked in the issue file.
- [x] `CONTEXT.md` - out of scope: The glossary's only channel-related term is **Block** (`instance_domain` + `channel_id`), which the build does not touch. It defines no term for `channel_name`, the crawler's channel metadata, or data repairs, and the build introduces no new domain concept that needs a glossary entry.

**Updated but not named by the Step 3 inventory.** none

**Other files that had to be touched.** none

**ADR conflicts.** none

### `DATA_BUILD.md`

<changes>
Added a "Repair video channel names (one-time migration)" subsection to `DATA_BUILD.md` at the end of step 2. It gives the repair command, the order to run it in, and how it behaves.

- **Placement.** It sits under "## 2) Filter to JoinPeerTube whitelist" as a `###` subsection, just before "## 3) Build embeddings". The later sections keep their numbers, so "step 3/4/5" still points to the right place.
- **Reason.** One line: channel ids are only unique per instance, so rows written before the crawl keyed metadata by host plus id can hold the name of a channel with the same id on another instance.
- **When it may run.** It is a migration of shared databases: on main after merge only, never from a worktree. It must run outside an updater cycle with the Engine idle or stopped, because on `whitelist.db` it drops the FTS triggers, runs the update, recreates the triggers and rebuilds `videos_fts`, and the rebuild holds the write lock.
- **Order.**
  1. Merge.
  2. Run the repair on `engine/crawler/data/crawl.db`.
  3. Run it on every copy of `whitelist.db`, prod included. `merge_rules.json` merges `videos` as `INSERT_ONLY`; I checked that in the file.
  4. Operator follow-up: `build-video-embeddings.py --db-path engine/server/db/whitelist.db --force`, then `build-ann-index.py` and `precompute-similar-ann.py`. For their flags it points to steps 4 and 5 rather than repeating them. This is scheduled with the stable-ANN-ids cutover and cites `docs/project/issues/08-stable-ann-ids.md`, which exists; the plans path does not.
- **Behaviour.** Each point was checked against `repair-video-channel-names.py`:
  - `--db PATH` is required and has no default.
  - A path that is not an existing file exits 2 with `database not found`.
  - It only changes a row whose own channel exists with a non-empty `display_name` that differs from the stored name. It never writes `channels`.
  - It logs `channel names repaired rows=N`, and a second run logs `rows=0`.
  - On a database with `videos_fts` it rebuilds the index on every run and raises `RuntimeError` if the counts don't match. The update is already committed at that point, so the fix for a failed rebuild is to run it again.
  - On `crawl.db` it skips the index steps.
  - On the FTS path it loads `sync-whitelist.py`, which parses `engine/crawler/schema.sql` when it loads, so it has to run from a full checkout.
- I did not change line 30, the broken `UPDATER_WORKER.md` reference; the real file is at `engine/server/db/jobs/docs/UPDATER_WORKER.md`. The instruction was to fix it only if this edit touched that line, and it didn't.
</changes>

<not_on_checklist>
none
</not_on_checklist>

### `docs/project/issues/34-video-channel-name-wrong-instance.md`

<changes>
Issue 34 is marked complete with a Delivered record, its wrong claims are corrected, and six of its seven criteria are ticked. **It is still in `docs/project/issues/`: please run `git mv docs/project/issues/34-video-channel-name-wrong-instance.md docs/project/issues/archive/`**, because I have no tool that can move or delete files.

- **Status:** `Status: bug, complete`.
- **Cards line under Impact:** it said the cards build wrong channel links. It now says there is no card fault in practice: the `channel_name` fallback builds a link only when `channel_url` is empty, and no row has an empty `channel_url`. This matches the triage finding.
- **Root-cause bullet in Triage:** made precise against `videos-worker.ts`. The crawl slug comes from `item.channelName`, the per-host progress row, before the map (line 440). `channel_url` comes from the payload's `channel.url` first, so `meta.channelUrl` is only a fallback (line 671). So only `displayName` and the `channelUrl` fallback were affected.
- **Plan 17 link:** the path to `docs/project/plans/17-stable-ann-ids.md`, which does not exist, is replaced by "Plan 17 (stable ANN ids, issue `08-stable-ann-ids.md`)".
- **New "Delivered" comment**, in the same form as archived issue 06:
  - The writer fix: `channelMetaKey(host, channelId)`, checked in both src (lines 165, 289, 299) and dist (lines 41, 126, 134).
  - The repair job, pointing at the `DATA_BUILD.md` section "Repair video channel names (one-time migration)" for behaviour and run order rather than repeating them.
  - Where the gating tests are now (`tests/tmp/...phase1–4.py`), and that the harvest will move them to `tests/active/test_channel_names.py`.
- **"Still owed on main" list** in that comment:
  - Run a real `npm run build` and confirm the dist diff. The dist was edited by hand, and production runs the dist.
  - The operator runs the repair on `crawl.db` and on every `whitelist.db` copy, prod included, then the re-embed, ANN rebuild and similarity precompute.
  - The active suite has not been run against the finished build.
- **Acceptance criteria:** six ticked. "The existing active suite stays green" is left unticked on purpose. Neither the phase reports nor the plan record show a suite run after the build, and I only tick what has evidence. It can be ticked once `validate_tests.py` passes.
</changes>

<not_on_checklist>
none
</not_on_checklist>

