# 63-catalog-update-weekly-increments

_Rendered by the `dev-flow` workflow from its run state. Every edit here is overwritten on the next step; the evidence each gate turned on is in `docs/project/plans/01-63-catalog-update-weekly-increments.record.md`._

## Requirements

### Purpose

A catalog update (`scripts/run-catalog-update.sh`, and the prod `peertube-updater.timer`, both running `engine/server/db/jobs/updater-worker.py`) crawls every instance in one run. That takes 4.5-9 hours, mostly in the channels stage (about 2h10m) and the videos stage (1.5-6h). This build cuts the hosts into 7 fixed groups and crawls one group per run, with runs scheduled daily. Each host is still refreshed about once a week, the cadence it has today, but one run does roughly a seventh of the crawl work. The operator chose daily runs of a seventh, not weekly runs of a fraction; the issue's "a cron job runs the command once a week" is superseded.

### Baseline suite state

Pre-build baseline: the suite exits 0 (`code: 0`, `variant: false`). Test trees: active `tests/active`, working `tests/tmp`, archive `tests/archive`, delete_me `delete_me`. Record `tests/last_test_validation.json`, output `tests/last_test_output.txt`, config `tests/config.json`. Plans in `docs/project/plans`. Project dir `/home/enduser/code/PeerTube-browser`.

### Current code (verified in the tree)

- `updater-worker.py` `main()`, in order: `cleanup_similarity_leftovers`; `load_denied_hosts`; optional `--sync-join-whitelist` reconcile; `init_staging_db` plus `seed_staging_from_prod` (copies every prod `instances.host` and every prod `channels` row into staging), or reuse with `--resume-staging`; `purge_hosts_from_staging(denied)`; the instances stage (`instances-cli.js --resume --whitelist-url ...`); `prune_staging_local_non_ok_instances` when `--skip-local-dead`; channels, videos (`--new-videos --existing-db prod`), tags (failure tolerated) and channel video counts; embeddings (GPU with CPU retry); `count_staging_deltas`; Engine stop (systemctl or shim, with the blue/green deploy lock when `--engine-upstream-snippet` is given); `merge-staging-db.py`; post-merge denylist `purge_hosts`; `recompute-popularity.py --incremental`; `build-ann-index.py`; Engine start in `finally`; `copy-to-crawl-db.py` (failure tolerated); `fetch-trending.py` (failure held until similarity has run); `run_similarity_stage` (shadow build, gate, swap). The whole run is under `single_run_lock` (`/tmp/peertube-browser-staging-sync.lock`); a second run while one is live raises `RuntimeError` and exits non-zero.
- Every crawl stage takes its hosts from the staging `instances` table: `channels-worker.ts` (`store.listInstances()`), `videos-worker.ts` (`store.listInstances()`, then `listChannelsWithVideos(1, hosts)`), `channels-videos-count-worker.ts` (`store.listInstances()`). Each also filters by `--exclude-hosts-file`. The tags pass works on staging's new videos. So removing hosts from staging `instances` before the channels stage keeps every later crawl stage off them, the same way `prune_staging_local_non_ok_instances` already works.
- The merge risk from the issue is resolved. `merge_rules.json` makes `instances`, `channels` and `videos` INSERT_ONLY and `video_embeddings` INSERT_OR_REPLACE, and `merge-staging-db.py` only runs INSERT OR IGNORE / INSERT OR REPLACE / UPSERT. It never deletes. A host absent from staging keeps all its prod rows.
- Schedules: `engine/install-updater-service.sh` and `scripts/install-service.sh` default `UPDATER_TIMER_ONCALENDAR="Fri *-*-* 20:00:00"` and `UPDATER_FLAGS="--gpu --skip-local-dead --concurrency 5 --timeout-ms 15000 --max-retries 3"`. `tests/active/test_install_updater_service.py` pins the installer's dry-run output, flags and OnCalendar included. `scripts/run-catalog-update.sh` hard-codes the same flags and runs detached by default.
- `scripts/run-services.sh` (`stop_one`, status) and the systemctl shim in `run-catalog-update.sh` find the Engine with `pgrep -f engine/server/api/server.py`. The shim's `stop` records "Engine was running" from that match, and `start` restarts services only if it was.
- `run-catalog-update.sh` needs `node` (and `npm` unless `--skip-build`) on PATH and exits FAILED otherwise. It resolves python itself from the pixi env or venv.

### Requirements

1. **Opt-in flag.** `updater-worker.py` gains `--increments N` (integer; 0 or absent means off). Off: the run crawls every host exactly as today, unchanged. On: the run crawls only one group of hosts, as below. N must be at least 1 (N = 1 behaves like a full crawl but still uses the pointer).
2. **Group assignment.** A host's group is `int(sha1(host).hexdigest(), 16) % N`, over the host string exactly as stored in `instances.host` (already lowercased and normalised by `normalize_host_token` / `normalizeHostToken`, UTF-8 encoded). It is stable across runs and needs no stored map. A new JoinPeerTube host falls into its group automatically and is first crawled and merged on its group's day. Deliberate simplification: groups balance host counts, not crawl cost, so a group holding a few very large instances runs longer. Upgrade path, not built now: a sticky size-balanced host-to-group map, persisted.
3. **Persisted pointer.** A small JSON state file records the last completed group, the N it was computed under, and when. Its default path is next to the prod DB (for example `engine/server/db/updater-increment.json`), and a flag (for example `--increment-state`) overrides it. A run crawls group `(last + 1) % N`. A missing file means group 0. If the stored N differs from the current `--increments`, the run starts at group 0 and logs that it did. An unreadable or corrupt file fails the run before any crawl, with a clear message; it is not silently reset.
4. **When the pointer advances.** The pointer is written (atomically: temp file plus `os.replace`) only after this run's merge into prod has committed. Any failure before or during the merge leaves it unchanged, and the next run retries the same group. That covers a crawl CLI exiting non-zero, embeddings failing on both GPU and CPU, an injected `--fail-before-merge`, a merge error, or the run refused by `single_run_lock`. A failure after the merge commits (denylist prune, popularity, ANN, copy-to-crawl.db, trending, similarity) does not hold the pointer back: the group's data is in prod, and the next daily run rebuilds those derived steps anyway. Hosts that error individually inside a crawl the CLI completes are recorded by the crawler as today and are not retried. They wait for their group's next turn.
5. **Where the filter applies.** With `--increments`, once the instances stage and the `--skip-local-dead` prune have run (and after the staging denylist prune), every staging `instances` row whose host is not in the selected group is deleted. This happens before the channels stage, so channels, videos, tags, channel video counts and embeddings touch only the group's hosts, and only the group's rows reach the merge. Seeded `channels` rows of other hosts can stay in staging: no crawl stage visits them, and the INSERT_ONLY merge leaves prod unchanged for them. The filter applies the same way to a reused staging DB (`--resume-staging`).
6. **Every run keeps the global steps.** The merge, post-merge denylist prune, `recompute-popularity.py --incremental`, the full ANN rebuild, copy-to-crawl.db, `fetch-trending.py` (all hosts, as today) and the similarity shadow build, gate and swap run on every incremental run, now daily. Accepted consequence: the Engine stop window (about 1.5 minutes on 2026-10-02) and the ~30-40 minute similarity build happen once a day instead of once a week.
7. **Logging.** Each incremental run logs to the worker log: N, the selected group, the pointer value read, the group's host count and the staging channel count for those hosts after the filter, and the pointer value written (or that it was not advanced, and why).
8. **Refused combination.** `--increments` together with `--sync-join-whitelist` is rejected at startup with a clear error. That mode has its own host selection.
9. **Wiring.**
   - `scripts/run-catalog-update.sh` passes `--increments 7` to the worker by default, and its help text says so. `-- <extra flags>` still passes extra flags through.
   - The default `UPDATER_FLAGS` in `engine/install-updater-service.sh` and `scripts/install-service.sh` gain `--increments 7`.
   - The default `UPDATER_TIMER_ONCALENDAR` in both becomes daily (one fixed time a day, for example `*-*-* 20:00:00`). Both stay overridable as today.
   - `tests/active/test_install_updater_service.py` is updated to the new defaults.
10. **Cron for the non-systemd path.** The docs give the exact crontab line that runs `scripts/run-catalog-update.sh` once a day. The repo does not install it; the operator does. The line sets PATH so `node` and `npm` resolve under cron's minimal environment. The line, and the command line cron spawns from it, must not contain the string `engine/server/api/server.py`, so the `pgrep -f` checks in the shim and in `run-services.sh` match only the Engine. The script's default detached mode and timestamped `catalog-update-*.log` are kept. A run still going when the next day's run starts makes the new run exit on the lock without advancing the pointer.
11. **Documentation.** Update `DATA_BUILD.md` (weekly timer and "Trending up to a week old" wording), `DEPLOYMENT.md` (timer table), `engine/server/db/jobs/docs/UPDATER_WORKER.md` (the flag, group rule, pointer file and advance rule, the filter point, the daily schedule, the crontab line), and the weekly-cadence paragraph of `docs/project/adr/0010-trending-from-source-instances.md`. `CONTEXT.md` gets a glossary entry for the term "increment" (a fixed hash group of hosts crawled in one run) if the build introduces it as a domain term.

### Out of scope

- Skipping the 227 instances with no videos in `whitelist.db`. The operator chose to keep them.
- Size-balanced or re-balanced group assignment (see requirement 2's upgrade path).
- Changing merge strategies. One side observation, not to be fixed here: `channels` is INSERT_ONLY, so the channel video counts the counts stage refreshes on seeded channels that already exist in prod do not reach prod.
- Moving the updater's bare `urlopen` onto the source-fetch adapter.

## High-level plan

### Approach

All the behaviour goes into `engine/server/db/jobs/updater-worker.py`, as a few small module-level helpers in the same style as `prune_staging_local_non_ok_instances` and `purge_hosts_from_staging`. The rest is defaults, one test, and docs. No new module, no new dependency: `hashlib`, `json`, `os` and `tempfile` from the stdlib are enough.

**Flags (req 1, 8).** `parse_args` gains `--increments` (int, default 0) and `--increment-state` (path, default unset). In `main()`, the state path defaults to `prod_db.parent / "updater-increment.json"`, so it sits next to whatever `--prod-db` names. That gives `engine/server/db/updater-increment.json` in production and keeps tests from touching the real file. Startup validation goes next to the existing `--dry-run` check, before the lock: a negative N is rejected, and N ≥ 1 together with `--sync-join-whitelist` is rejected with a clear error. With N = 0 nothing below runs and the code path is byte-for-byte today's.

**Group function (req 2).** One helper returns `int(hashlib.sha1(host.encode("utf-8")).hexdigest(), 16) % n`. It is computed in Python because SQLite has no sha1. The input is the host string exactly as stored in `instances.host`, with no re-normalisation, so the stored value is the only source of truth.

**Pointer read (req 3).** It is read inside `single_run_lock`, as the first thing after the lock is taken and before cleanup, seeding or any crawl, so two runs can never interleave a read and a write. A missing file selects group 0. A file that parses but whose stored N differs from `--increments` selects group 0 and logs that the N changed. Otherwise the run takes `(last + 1) % N`. These cases raise `RuntimeError` naming the file and telling the operator to fix or delete it:
- the file cannot be read or is not valid JSON;
- it lacks `last_group` / `increments`;
- `increments` is not an int ≥ 1;
- `last_group` is not an int in `[0, increments)`.

Nothing is reset silently. The file holds `last_group`, `increments` and `completed_at` (UTC ISO timestamp).

**Filter point (req 5).** A new helper sits after `run_cmd(instances_cmd)` and after the `--skip-local-dead` prune, before `channels_cmd`. The staging denylist prune already runs earlier, before the instances stage. The helper:
1. reads every `host` from staging `instances`;
2. keeps those whose group equals the selected one;
3. deletes the rest in one transaction, by `executemany` on the host key;
4. counts staging `channels` rows for the kept hosts;
5. returns the kept-host and channel counts.

This is the same mechanism as the local-health prune, so every later crawl stage (each reads `store.listInstances()`) only sees the group. It runs whether staging was freshly seeded or reused with `--resume-staging`. On reuse the staging DB normally comes from a failed run of the same group, because the pointer did not advance, but the filter is re-applied regardless. Seeded `channels` rows of other hosts stay in staging and are harmless, as the requirement states.

**Pointer advance (req 4).** The write goes immediately after the `merge-staging-db.py` `run_cmd` returns. That script commits its whole merge in one `BEGIN IMMEDIATE` … `commit` transaction and rolls back on error, so exit 0 means committed. The write comes before the post-merge denylist prune and is atomic: a temp file in the same directory, flushed and fsynced, then `os.replace`. Every failure before that line raises before the write and leaves the file alone:
- a non-zero crawl CLI exit;
- embeddings failing on both GPU and CPU (`run_with_cpu_fallback` raises);
- `--fail-before-merge`;
- a merge error;
- refusal by the lock, which happens before the pointer is even read.

Failures after it (prune, popularity, ANN, copy, trending, similarity) cannot reach back to undo it. If the write itself fails with an `OSError`, the error is logged as "pointer not advanced" and the global steps still run, so the ANN index matches prod. The run then exits non-zero at the end, the same way `trending_error` is held. The next run safely re-crawls the same group, because the INSERT_ONLY merge is idempotent.

**Global steps (req 6).** These are unchanged and still run every time. Only their frequency changes, through the schedule.

**Logging (req 7).** Each incremental run logs to the worker log:
- one line at read time: N, the stored pointer (or "missing" / "N changed from X, restarting at 0"), and the selected group;
- one line after the filter: group, hosts kept, hosts removed, staging channels for the group;
- one line at the end: "pointer written last_group=g", or "pointer not advanced: <reason>" logged from the existing exception path. A failure before the merge logs that reason before re-raising. This is a small `try/except` that logs and re-raises around the pre-merge section, guarded on N ≥ 1, rather than restructuring `main()`.

**Wiring (req 9).**
- `scripts/run-catalog-update.sh`: `--increments 7` is added to the hard-coded worker flags, before `EXTRA_ARGS`. Argparse keeps the last occurrence, so `-- --increments 0` still forces a full crawl. The help header says both. Its `sed -n '2,23p'` range moves if the header grows.
- Both installers: `UPDATER_FLAGS` gains `--increments 7` and `UPDATER_TIMER_ONCALENDAR` defaults to `*-*-* 20:00:00`. Both env/flag overrides are unchanged.
- `tests/active/test_install_updater_service.py`: the pinned ExecStart and OnCalendar expectations get the new defaults. Its `parse_args` round-trip then also proves the worker accepts the flag.

**Cron (req 10).** `UPDATER_WORKER.md` documents one line of the form `0 20 * * * PATH=<dir of node>:/usr/local/bin:/usr/bin:/bin /usr/bin/bash /home/enduser/code/PeerTube-browser/scripts/run-catalog-update.sh >/dev/null 2>&1`. The doc tells the operator to substitute `dirname "$(command -v node)"`, which matters for nvm installs. The line names only the script path, so neither it nor the `/bin/sh -c` cron spawns contains `engine/server/api/server.py`. It avoids `%`, which cron treats specially. The script's own detached mode still writes `catalog-update-<timestamp>.log`. The redirect only stops cron mailing the two "started" lines. Overlap: the second run hits `single_run_lock` and exits non-zero before reading the pointer. Under systemd, a timer does not start a oneshot service that is still running.

**Docs (req 11).**
- `DATA_BUILD.md`: weekly becomes daily-by-seventh, and trending becomes "up to a day old".
- `DEPLOYMENT.md`: timer table updated.
- `UPDATER_WORKER.md`: flag, group rule, pointer file and advance rule, filter point, schedule, cron line, how to force a full crawl, and the simplification with its upgrade path.
- ADR 0010: the cadence paragraph changes to daily.
- `CONTEXT.md`: an "increment" glossary entry, because the build introduces the term in a flag name, a state file and the docs.

### Alternatives considered

- **Pass the group to the crawlers as a host list** (an include file, or the complement written into `--exclude-hosts-file`). Rejected: it needs TypeScript changes in three or four CLIs, or overloads the denylist file's meaning, and the out-of-group rows would still sit in staging and reach the merge. Deleting from staging uses a mechanism the worker already relies on.
- **Filter at seed time** (seed only group hosts). Rejected: `instances-cli --whitelist-url` re-inserts every JoinPeerTube host afterwards, so a post-instances filter is needed anyway, and filtering twice is redundant.
- **Derive the group from the date** (day-of-year % 7), with no state file. Rejected: a failed run would silently skip its group for a week. The settled pointer-plus-retry rule requires state.
- **A stored host-to-group map.** Rejected for now as the named upgrade path; a hash needs no storage and handles new hosts automatically.
- **Advance the pointer at the end of the run.** Rejected by req 4: a post-merge failure would make the next run re-crawl a group whose data is already in prod.

### Risks and gotchas

- **The instances stage stays global.** Every run still fetches the JoinPeerTube list and probes every instance before filtering. That stage was not the bulk (channels and videos were), but it is not divided by 7.
- **`--max-instances` / `--max-channels` caps** now apply to the group subset, not the whole set. Same values, different meaning; worth a doc line.
- **Imbalance.** A group holding several very large instances runs longer than a seventh. This is the deliberate simplification of req 2.
- **Host normalisation drift.** If a host's stored string ever changed (e.g. a normalisation fix), it would move group. Harmless: at worst one host is crawled a few days early or late once.
- **Changing N** restarts at group 0, so groups near the end of the old cycle wait up to a full cycle. This is logged.
- **New JoinPeerTube hosts** reach prod only on their group's day, up to a week later than today's weekly-but-full run in the worst case. Accepted by req 2.
- **Write failure after merge.** If the pointer write fails after a committed merge, the run is marked failed but the global steps still run. The group repeats next day, at the cost of one redundant crawl.
- **Deleting the state file by hand** restarts at group 0. That is harmless, and documented as the recovery for a corrupt file.

### Tradeoffs the operator accepts

- The Engine stop window (~1.5 min) and the 30–40 min similarity build happen daily instead of weekly (req 6).
- Daily runs mean daily GPU use and daily embeddings/ANN rebuilds of the whole prod index. The full ANN rebuild does not shrink with the crawl.
- Per-host freshness stays about weekly, but varies per host: each host's day is fixed by its hash, not chosen.
- Hosts that error inside a completed crawl wait a full cycle (req 4).
- The non-systemd path depends on an operator-installed crontab line that the repo does not manage.

## Impacts

<impacts>
<impact path="engine/server/db/jobs/updater-worker.py" element="module imports (lines 6-22)">
**What changes.** Add `import hashlib`. `json` (line 8), `os` (line 10) and `tempfile` (line 17) are already imported, so the plan's "stdlib only" holds with one new import. The pointer's `completed_at` (a UTC ISO timestamp) can come from the existing `time` module (`time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())`). Using `datetime` instead adds a second import. Either works; keep it stdlib.

**What depends on it.** `tests/active/test_updater_worker.py`, `tests/active/test_host_normalisation.py:87` and `tests/active/test_install_updater_service.py:93` all exec the module in the pytest interpreter. A stdlib-only import keeps that working.

**Regression risk.** Very low.
</impact>
<impact path="engine/server/db/jobs/updater-worker.py" element="parse_args(): new --increments and --increment-state arguments (argparse block, lines 114-316)">
**What changes.** Two new arguments, in the file's multi-line `parser.add_argument(` style with a `help=`:
- `--increments`: `type=int`, `default=0`.
- `--increment-state`: path string, `default=None`.

Place them next to `--resume-staging` or `--skip-local-dead` (lines 126-133, 257-264). The `--max-instances` and `--max-channels` help texts (lines 217-228) could note that with `--increments` the cap applies to the group's hosts. The `description=` (lines 115-119) could mention the per-run host group.

**What depends on it.**
- `main()`.
- `run-catalog-update.sh` and both installers, which will pass `--increments 7`.
- `test_install_updater_service.py:176`, which round-trips the installer's real ExecStart argv through `worker.parse_args()`. Until the flag exists, argparse exits with SystemExit 2 there.
- `test_updater_worker.py:515-525` (`test_parse_args_takes_snippet_and_deploy_lock`) calls `parse_args` too. Additive flags leave it unaffected.

**Regression risk.** Low. Argparse keeps the last occurrence of a repeated option. That is what makes `run-catalog-update.sh -- --increments 0` and an operator `UPDATER_FLAGS` override work, so the option must not use `action="append"` or a custom action.
</impact>
<impact path="engine/server/db/jobs/updater-worker.py" element="new helper: host → group (sha1 of host % N)">
**What changes.** A new module-level function returning `int(hashlib.sha1(host.encode("utf-8")).hexdigest(), 16) % n`, with a one-line docstring like its neighbours. Its input is the `instances.host` value exactly as stored, never passed through `normalize_host_token` again.

**What depends on it.** The staging filter helper, and the new tests, which should pin at least one host's group with a literal computed outside the helper. That follows the repo convention in `test_updater_worker.py:893-894` for `INJECT_ANN_ID`.

**Regression risk.** Low in code.
- **Duplicate spellings.** Staging can hold two spellings of one host: the instances stage inserts the crawler's `normalizeHostToken` spelling, while seeding copies prod's stored string. UPDATER_WORKER.md:159 records that prod can hold unnormalised spellings. Those two rows hash to different groups, so the host is crawled on two days. This is harmless (INSERT_ONLY merge), and it is the "host normalisation drift" the plan accepts.
- **N must never be 0 here.** `% 0` raises ZeroDivisionError. Only call the helper when N ≥ 1.
</impact>
<impact path="engine/server/db/jobs/updater-worker.py" element="new helper: read pointer state file → selected group">
**What changes.** A new function reads the JSON state file and returns the selected group, plus what to log.

**Outcomes:**
- **Missing file:** group 0.
- **Stored `increments` differs from N:** group 0, and log "N changed from X, restarting at 0".
- **Otherwise:** `(last_group + 1) % N`.

**Raises `RuntimeError`**, naming the path and telling the operator to fix or delete the file, when:
- the file is unreadable (`OSError`) or is not valid JSON (`json.JSONDecodeError`, `UnicodeDecodeError`);
- the top-level value is not an object;
- a key is missing;
- `increments` is not an int ≥ 1;
- `last_group` is not an int in `[0, increments)`.

**Pitfall: bools are ints.** `isinstance(True, int)` is true, so `{"last_group": false, "increments": true}` passes a naive check. Exclude `bool` explicitly.

**What depends on it.** `main()`, which calls it inside the lock, and the new tests (missing, valid, N changed, each corrupt case).

**Regression risk.** Low. The plan's rule is that nothing is reset silently. A broad `except Exception` that falls back to group 0 would break it.
</impact>
<impact path="engine/server/db/jobs/updater-worker.py" element="new helper: filter staging instances to the selected group (modelled on prune_staging_local_non_ok_instances, lines 972-1021)">
**What changes.** A new function (staging_db, group, n) does the following:
1. Opens `sqlite3.connect(staging_db.as_posix())` with no prod attach.
2. Selects every `host` from `instances`.
3. Keeps the hosts whose group equals the selected one.
4. Deletes the rest with `executemany("DELETE FROM instances WHERE host = ?", ...)` in one transaction and commits.
5. Counts `channels` rows whose `instance_domain` is among the kept hosts.
6. Logs one line (group, kept, removed, channels) and returns the counts as a dict, in the style of `prune_staging_local_non_ok_instances`, closing the connection in `finally`.

**Facts checked:**
- `engine/crawler/schema.sql` has no foreign keys, so deleting `instances` rows cascades to nothing.
- Staging `instances.host` is the primary key.
- Every later crawl stage reads its hosts from the staging `instances` table:
  - `channels-worker.ts:75` uses `store.listInstances()`, and `prepareChannelProgress`/`pruneChannelProgress` (db.ts:956-991) drop progress rows for hosts not in the list, even with `--resume`.
  - `videos-worker.ts:158-164` uses `listInstances()`, then `listChannelsWithVideos(1, hosts)`, and `pruneVideoProgress` (db.ts:1369+) applies the same pruning.
  - `channels-videos-count-worker.ts:45` uses `listInstances()`.
  - The tags pass (`listVideosForTags`, db.ts:1301) reads staging `videos`, which only the group's crawl fills.

**Channel counting.** Count channels without a giant `IN (...)`: SQLite's default host-parameter limit is 32766 on modern builds (999 on old ones), and staging holds about 1,764+ hosts. A temp table, or a Python-side count over `SELECT instance_domain, COUNT(*) FROM channels GROUP BY instance_domain`, avoids the limit.

**What depends on it.** `main()` and the new tests.

**Regression risk.** Medium.
- **Placement.** Called before the instances stage, it is undone, because `instances-cli --whitelist-url` re-inserts every JoinPeerTube host.
- **Delete scope.** It must delete only from `instances`. Deleting seeded `channels` or `videos` rows is unneeded, and touching prod is wrong.
</impact>
<impact path="engine/server/db/jobs/updater-worker.py" element="new helper: atomic pointer write (temp file in same dir, flush, fsync, os.replace)">
**What changes.** A new function writes `{"last_group": g, "increments": N, "completed_at": <UTC ISO>}`:
1. `tempfile.NamedTemporaryFile(mode="w", dir=state.parent, prefix=<stable prefix such as "updater-increment.">, suffix=".tmp", delete=False)`.
2. `json.dump`, `flush()`, `os.fsync(fileno)`, close.
3. `os.replace(tmp, state)`.

On failure it unlinks the temp file. Optionally, fsync the directory after the replace.

**What depends on it.** `main()`, right after the merge, and the new tests (written content, no temp file left, an OSError path).

**Regression risk.** Low.
- **Leftover temp files.** A crash between create and replace leaves a `.tmp` next to `whitelist.db`. A stable prefix lets `.gitignore` and the docs name it.
- **Missing directory.** When `--increment-state` names a directory that does not exist, the failure only appears after a full crawl and merge. Validating the parent directory at startup, before the lock, avoids wasting a crawl. This is not in the plan; I recommend it.
</impact>
<impact path="engine/server/db/jobs/updater-worker.py" element="main(): path resolution and startup validation (lines 1089-1119)">
**What changes.**
- **State path.** Resolve it next to the other paths (1089-1095): `Path(args.increment_state).resolve()` if given, else `prod_db.parent / "updater-increment.json"`.
- **Validation.** Next to the `--dry-run` check (1118-1119), before the lock: reject `args.increments < 0`, and reject `args.increments >= 1` together with `args.sync_join_whitelist`, with a clear `RuntimeError` (or `parser.error`; the existing check raises `RuntimeError` after logging is set up, so match that).

**Default path follows symlinks.** `prod_db` is already `.resolve()`d (line 1089). In a worktree, `scripts/worktree-setup.sh:27-28` symlinks `whitelist.db` to main's, so the default state file resolves to main's `engine/server/db/updater-increment.json`. The pointer is then shared with the live dataset it describes, which is consistent, but a worktree run advances main's pointer. Worth one doc line.

**What depends on it.** Every later use of N and of the state path.

**Regression risk.** Low. With N = 0 nothing below may run. Every new call site must be guarded on `args.increments >= 1`, so the existing `main()` runs in `test_updater_worker.py` (`_run_main`, `_run_trending_main`, `_run_crawl_main`, none of which pass `--increments`) stay byte-for-byte unchanged and write no state file.
</impact>
<impact path="engine/server/db/jobs/updater-worker.py" element="main(): pointer read inside single_run_lock (line 1123-1124)">
**What changes.** When N ≥ 1, the first statement inside `with single_run_lock(lock_file):`, before `cleanup_similarity_leftovers` (line 1124), reads the pointer, selects the group and logs N, the stored value or "missing" or "N changed", and the selected group.

**What depends on it.** The filter call site and the pointer write, which need the selected group in a local.

**Regression risk.** Low.
- **Lock refusal.** `single_run_lock` raises `RuntimeError` before the body runs (lines 371-373), so a refused run never reads the pointer. The cron/timer overlap case therefore needs no new code.
- **Corrupt file.** A corrupt file now fails the run before the similarity leftover cleanup. That is acceptable, since the next run cleans up.
</impact>
<impact path="engine/server/db/jobs/updater-worker.py" element="main(): filter call site inside `if run_crawl_stages:` (between line 1226 and line 1228)">
**What changes.** When N ≥ 1, call the filter helper after `run_cmd(instances_cmd)` (1223) and after the optional `prune_staging_local_non_ok_instances` (1225-1226), immediately before `channels_cmd` is built (1228). It applies whether staging was freshly seeded (1177-1182) or reused under `--resume-staging` (1175-1176).

**`--resume-staging` caveat.** The plan says a reused staging DB "normally comes from a failed run of the same group". That is not guaranteed: a run after a successful run, or after N changed, can reuse staging holding another group's already-crawled `videos` and `video_embeddings`. Those rows re-merge as an INSERT_ONLY no-op, and INSERT_OR_REPLACE rewrites identical embeddings, so the effect is harmless but extra work. Worth one doc line.

**What depends on it.** All later crawl stages, `count_staging_deltas` (1345), the merge, and the embeddings stage, which then embeds only the group's new videos.

**Regression risk.** Medium if misplaced; see the helper entry. `run_crawl_stages` is always true when N ≥ 1, because sync-join is refused.
</impact>
<impact path="engine/server/db/jobs/updater-worker.py" element="main(): pointer advance after merge-staging-db run_cmd, inside the service try (lines 1383-1397), held OSError and end-of-run raise (lines 1480-1518)">
**What changes.**
- **The write.** When N ≥ 1, call the write helper directly after the `merge-staging-db.py` `run_cmd` (1383-1395) returns and before the denylist safety prune (1397). Wrap it in `try/except OSError`, which logs "pointer not advanced: <error>" and stores the exception in a held variable. On success, log "pointer written last_group=g".
- **The held error.** After `run_similarity_stage` (1510-1516), the run raises it the same way `trending_error` is raised (1517-1518). Decide and document which raises first when both are set, or raise one message naming both. Either way "worker completed" must not be logged.
- **Merge commit guarantee.** `merge-staging-db.py` commits inside one `BEGIN IMMEDIATE` … `commit` and rolls back on any exception (lines 128-209). `run_cmd` uses `check=True` (line 390), so returning means exit 0, which means committed.

**Timing.** The write happens inside the Engine-stopped window, which it lengthens by one fsync.

**What depends on it.** The retry semantics of req 4, and the existing tests:
- `test_main_runs_trending_then_similarity_stage_after_service_start` (`test_updater_worker.py:336-370`) requires exactly one `Try` whose `finalbody` contains `systemctl_cmd(action="start")`. It also requires the one trending `run_cmd` and the one `run_similarity_stage` call to sit after that `try`'s `end_lineno`. A new try/except around only the pointer write, nested in the service try's body, keeps all of this.
- `test_main_stops_and_starts_the_snippet_unit_under_the_lock` (`test_updater_worker.py:644-679`) requires no `engine_unit` store after the stop.
- `test_main_run_stops_and_starts_the_snippet_unit_holding_the_lock` (729-740) requires the first and last child to be the sudo stop and start. That still holds because those runs are sync-join (N = 0).

**Regression risk.** High. Writing before the merge returns, or catching broader than `OSError` and swallowing a merge failure, breaks req 4. Placing the write after the denylist prune, popularity or ANN lets a post-merge failure hold the pointer back. That violates req 4 and re-crawls a group whose data is already in prod.
</impact>
<impact path="engine/server/db/jobs/updater-worker.py" element="main(): 'pointer not advanced: <reason>' logging for failures before the write (outer try at line 1122)">
**What changes.** The plan wants the pre-merge failure reason logged before re-raising.

**Placement.** The merge failure itself happens inside the service try, so a try/except around only the crawl section misses it. The least intrusive shape is a `pointer_written` (or `selected_group`) local plus an `except Exception as exc:` on the existing outer `try` (line 1122, today `try/finally`). That except logs `pointer not advanced: %s` when N ≥ 1 and the pointer was not written, then bare-`raise`s.

**What it does not cover.**
- That except also sees the lock refusal, where the pointer was never read. Logging "not advanced" there is true but differently worded; guard it on "pointer was read".
- SIGTERM or SIGKILL from systemd (`TimeoutStartSec=24h`) bypass `except Exception`, so no line is logged then.

**AST scans that must keep passing.** The except must not put a `systemctl_cmd(action="start")` in any `finalbody`, and it must not move the trending `run_cmd` or `run_similarity_stage` inside the service try (`test_updater_worker.py:341-347, 362`). Restructuring `main()` more widely risks these scans.

**What depends on it.** Req 7 logging, and the new tests (for example `--fail-before-merge` with `--increments`, read through `caplog`).

**Regression risk.** Medium. A non-re-raising except would turn failures into success.
</impact>
<impact path="engine/server/db/jobs/updater-worker.py" element="existing helpers used as style references or unchanged dependencies: prune_staging_local_non_ok_instances (972-1021), purge_hosts_from_staging (638-652), seed_staging_from_prod (875-915), count_staging_deltas (918-969), single_run_lock (346-382), run_cmd (385-392), run_with_cpu_fallback (414-432)">
**What changes.** Nothing.
- `seed_staging_from_prod` still copies every prod host and channel. The plan rejects filtering at seed time.
- `count_staging_deltas` reports only the group's new rows, because the seeded other-host channels already exist in prod.
- `run_with_cpu_fallback` raises `CalledProcessError` when the CPU retry fails too. That raise is what makes "embeddings failing on both" a pre-write failure.

**What depends on it.** The new code reads these as the pattern to copy.

**Regression risk.** None, if left untouched.
</impact>
<impact path="engine/server/db/jobs/merge-staging-db.py" element="main() transaction (lines 118-214)">
**What changes.** Nothing.

**Why it matters.** The pointer-advance rule depends on one `BEGIN IMMEDIATE` … `conn.commit()` with rollback in `except` (128-209), and on the strategies being only INSERT OR IGNORE, INSERT OR REPLACE or UPSERT, never DELETE (166-194). So a host absent from the group's staging keeps all its prod rows, which resolves issue 63's open risk. A failure in `DETACH` in its `finally` (211) after the commit would exit non-zero after a committed merge: the pointer is not advanced and the group is re-crawled. That is harmless.

**What depends on it.** The `updater-worker.py` advance logic, and `test_merge_staging_db.py`.

**Regression risk.** None from this build.
</impact>
<impact path="engine/server/db/jobs/merge_rules.json" element="table strategies">
**What changes.** Nothing.

**Why it matters.** `instances`, `channels` and `videos` are INSERT_ONLY and `video_embeddings` is INSERT_OR_REPLACE. That makes a re-crawl of the same group after a failed pointer write idempotent.

**Regression risk.** None. Changing it is out of scope.
</impact>
<impact path="engine/crawler/src/channels-worker.ts" element="crawlChannels() host list (lines 72-101)">
**What changes.** Nothing.

**Why it matters.** It reads `store.listInstances()` and applies `--max-instances` slicing after the exclude filter. With increments, the cap applies to the group's subset, the risk the plan names.

**What depends on it.** Correctness of the staging filter. No TypeScript change, so no rebuild of `dist/` is needed.

**Regression risk.** None.
</impact>
<impact path="engine/crawler/src/videos-worker.ts" element="host and channel selection (lines 155-181)">
**What changes.** Nothing.

**Why it matters.** It reads `listInstances()`, then `listChannelsWithVideos(1, hosts)`, so seeded channels of out-of-group hosts are never crawled. `prepareVideoProgress` prunes progress rows the same way. The tags pass (`listVideosForTags`, 241) reads staging `videos` only.

**Regression risk.** None.
</impact>
<impact path="engine/crawler/src/channels-videos-count-worker.ts" element="host list (line 45)">
**What changes.** Nothing.

**Why it matters.** It reads `filterHosts(store.listInstances(), ...)`, so channel video counts are refreshed only for the group's hosts.

**Regression risk.** None.
</impact>
<impact path="engine/crawler/src/db.ts" element="listInstances (1259-1264), listChannelsWithVideos (1283-1296), prepareChannelProgress/pruneChannelProgress (956-991), prepareVideoProgress/pruneVideoProgress (1346-1395)">
**What changes.** Nothing.

**Why it matters.** I verified that each reads the staging `instances` table or prunes progress to the passed hosts, even with `--resume`. This is what the filter-by-deletion approach relies on.

**Regression risk.** None.
</impact>
<impact path="engine/server/db/jobs/fetch-trending.py" element="AGE_OUT_MS comment (line 36)">
**What changes.** The comment reads "The updater runs weekly: a host failing one run keeps its list, a host failing two loses it (operator decision, issue 38)". With a daily timer it becomes false: at 10 days, a host survives about nine consecutive failed daily runs.

At minimum, rewrite the comment. Whether to keep 10 days is an operator decision the plan does not take. Keeping 10 days means a trending list can now be up to 10 days stale in the worst case. Shortening the window (for example to 2 days, to keep "two failed runs") changes behaviour and breaks `tests/active/test_fetch_trending.py`, whose docstring and test (lines 1-5, 140) pin exactly 10 days.

**What depends on it.** The ADR-0010 Note, UPDATER_WORKER.md:98 and CONTEXT.md:29, which all state the weekly semantics.

**Regression risk.** Low in code (comment only). This conflicts with ADR-0010's recorded operator decision and should be surfaced, not silently overridden.
</impact>
<impact path="scripts/run-catalog-update.sh" element="worker invocation (lines 122-126) and help header (lines 2-23, sed range at line 45)">
**What changes.**
- **Invocation.** Add `--increments 7` to the hard-coded flags on line 125, before `"${EXTRA_ARGS[@]+...}"` (126), so `-- --increments 0` (argparse keeps the last occurrence) forces a full crawl.
- **Help header.** Say that it passes `--increments 7` and how to force a full crawl. If the header grows past line 23, move the `sed -n '2,23p'` range on line 45 with it, or `--help` cuts the text or prints `set -uo pipefail`.
- **Header claim.** Line 5 says the script runs the worker "with the flags install-service.sh gives the timer". That stays true only if both installers change too.

**Cron constraint (req 10).** The script's own command lines (`bash .../run-catalog-update.sh --foreground ...` and `python .../engine/server/db/jobs/updater-worker.py ...`) do not contain `engine/server/api/server.py`, so the shim's `pgrep -f "${ENGINE_PATTERN}"` (line 103) and the post-run check (line 130) still match only the Engine.

**What depends on it.** The operator's crontab line, documented in UPDATER_WORKER.md. No test exercises this script (grep of `tests/` finds none).

**Regression risk.** Low. The flag must come before `EXTRA_ARGS`. Placing it after them makes a full crawl impossible to request.
</impact>
<impact path="engine/install-updater-service.sh" element="UPDATER_TIMER_ONCALENDAR and UPDATER_FLAGS defaults (lines 32-33), usage text (54-55), ExecStart assembly (336), timer unit (361-375)">
**What changes.**
- Line 32 default becomes `*-*-* 20:00:00`.
- Line 33 default gains `--increments 7`, giving `--gpu --skip-local-dead --concurrency 5 --timeout-ms 15000 --max-retries 3 --increments 7`, or wherever the implementer places it.
- The usage lines could state the daily default.
- Both overrides stay unchanged: the env var, `--updater-oncalendar` and `--updater-flags` (lines 174-178).
- `updater_exec` (336) appends `${UPDATER_FLAGS}` after the fixed flags, so the default reaches the ExecStart.

**What depends on it.**
- The prod and dev dry-run previews pinned by `tests/active/test_install_updater_service.py`.
- `resolve_default_engine_service_name` in the worker (it runs this script with `--print-default-engine-service-name`, which is unaffected).
- Existing installed units are not regenerated until the operator re-runs the installer, so the change takes effect only on reinstall.

**Regression risk.** High in operations. An operator who installs with a custom `UPDATER_FLAGS` or `--updater-flags` that lacks `--increments` now gets a daily timer running a full 4.5-9 h crawl every day, because the worker's own default is 0. Document that a custom flag set must carry `--increments 7`. Consider an installer warning when the timer is daily and the flags lack `--increments`; this is not in the plan.
</impact>
<impact path="scripts/install-service.sh" element="UPDATER_TIMER_ONCALENDAR and UPDATER_FLAGS defaults (lines 41-42), forwarded at install_updater_for_contour (lines 222-233)">
**What changes.** The same two defaults change as in the updater installer.

**Why both must change.** The central installer always passes `--updater-oncalendar "${UPDATER_TIMER_ONCALENDAR}"` and `--updater-flags "${UPDATER_FLAGS}"` (231-232), which replace the sub-installer's defaults. If only `engine/install-updater-service.sh` changes, every central prod install (the documented path, README.md:71-78, DEPLOYMENT.md:459-460) keeps Fri-weekly with no increments.

**What depends on it.** The `central-argv` parametrisation of `test_updater_installer_prod_dry_run_passes_snippet_and_allows_only_instance_stop_start` (`test_install_updater_service.py:158-163`), which runs the echoed sub-installer argv verbatim.

**Regression risk.** Medium. The two defaults can drift apart, and today no test asserts `--increments` or OnCalendar on the central path.
</impact>
<impact path="tests/active/test_install_updater_service.py" element="dev ExecStart pin (line 191), prod parse_args round-trip (lines 172-177), module and test docstrings (lines 1-6, 151, 181)">
**What changes.**
- **Dev ExecStart pin.** Line 191 pins the dev ExecStart exactly, ending `... --max-retries 3'`. It must gain `--increments 7` in the position the default puts it.
- **No OnCalendar assertion exists today.** The plan says "pinned ExecStart and OnCalendar expectations", but nothing in this file reads the `----- updater timer preview -----` section. The `_previews` helper (103-114) already parses it under the key `timer`. Add an `OnCalendar=*-*-* 20:00:00` assertion for prod, in both the `defaults` and `central-argv` paths, and for dev.
- **Increments on the central path.** Add `_values(argv, "--increments") == ["7"]` in the prod test, in both paths. That is what catches one installer changing without the other.
- **Round-trip.** `worker.parse_args()` (176) now receives `--increments 7`. It passes only after the worker gains the flag, so extend its tuple to `args.increments == 7`.
- **Docstrings.** Line 1 and the dev docstring ("today's `ExecStart` exactly", lines 4, 181) need rewording to the new default.

**What depends on it.** The durable suite. The test map lists it against the two installers and the worker.

**Regression risk.** Low. The risk is a missed assertion, which would let the installers drift.
</impact>
<impact path="tests/active/test_updater_worker.py" element="existing main() runs and AST scans (lines 109-120, 336-370, 623-751, 755-1026), and home for the new incremental tests">
**What changes.**
- **Existing tests.** They pass no `--increments`, so they must keep passing unchanged. They are the N = 0 "byte-for-byte today" check.
- **AST constraints.** Exactly one service `Try` with the start in its `finalbody`; trending and similarity after its `end_lineno`; `engine_unit` not rebound after the stop; the release in that `try`'s `finalbody`. See the main() entries.
- **New tests.** They fit beside `_run_crawl_main` (937-977), which runs the full crawl path (not sync-join) to `--fail-before-merge` with only `subprocess.run` faked. It can seed staging `instances` and `channels` through the fake instances child, then assert:
  - after the run, staging `instances` holds only the group;
  - the state file is untouched after a pre-merge failure;
  - the log lines are emitted.
- **Advance test.** A success-path run with `--increments` is needed, but `_run_trending_main` uses sync-join, which is now refused. A new full-crawl harness with `--skip-systemctl`, faking the merge child as exit 0, is required to observe the write after the merge and a held error after a forced `OSError` (for example a `--increment-state` in an unwritable or missing directory).
- **Docstring.** The module docstring (1-32) lists every proven clause, the repo convention, so the new clauses go there.

**What depends on it.** The durable suite.

**Regression risk.** Medium. A main() restructure that breaks the AST scans fails here first, which is the intended guard.
</impact>
<impact path="tests/active/test_host_normalisation.py" element="_load_job of updater-worker.py (line 87), fetch_join_hosts check (111-115)">
**What changes.** Nothing.

**Why it matters.** It execs the module, so a new import must be stdlib-only. `hashlib` is.

**Regression risk.** None.
</impact>
<impact path="tests/active/test_fetch_trending.py" element="10-day age-out tests (docstring lines 1-5, test at 140)">
**What changes.** Nothing, unless the operator decides to change `AGE_OUT_MS` for the daily cadence (see the `fetch-trending.py` entry). In that case these pins move.

**Regression risk.** None as planned.
</impact>
<impact path="tests/config.json" element="test map entries (test_updater_worker.py at line 304, test_install_updater_service.py at line 348)">
**What changes.** Only if the new incremental tests go into a new test file. That file then needs a map entry listing `engine/server/db/jobs/updater-worker.py` (and, if the test reads it, `engine/crawler/schema.sql`). Tests added to `test_updater_worker.py` need no change.

**Regression risk.** Low. A missing entry means the durable-suite map does not route updater changes to the new test.
</impact>
<impact path="engine/server/db/jobs/tests/test-orchestrator-smoke.py" element="run_orchestrator worker argv (lines 415-473)">
**What changes.** Nothing. It passes no `--increments`, so the worker runs as today (N = 0). It is not in `tests/config.json`, so it is not part of the durable suite. An optional incremental scenario could be added later through its `extra_flags`.

**Regression risk.** None.
</impact>
<impact path=".gitignore" element="local data files section (lines 10-25)">
**What changes.** The plan misses this. The new state file `engine/server/db/updater-increment.json` is not covered by any pattern: `*.db*`, `*.faiss.json` and the explicit lock files do not match it, and `*.json` is not ignored. Every dev checkout, and the prod checkout that runs from the repo directory, would then show it as untracked, and it could be committed by accident. The same goes for a leftover temp file from the atomic write. Add an entry, with a comment like the existing lock-file entries (lines 20-23), for `engine/server/db/updater-increment.json`, plus the temp-file pattern the write helper uses (for example `engine/server/db/updater-increment.*.tmp`).

**Regression risk.** Low, but a committed pointer file would reset or skew other checkouts' groups.
</impact>
<impact path="scripts/uninstall-service.sh" element="--purge-updater-state / week_state_file (lines 155-199)">
**What changes.** The plan does not mention it, and I recommend no code change, only awareness. `--purge-updater-state` removes a legacy `/var/lib/peertube-browser/updater-last-success-week.txt`, which no current code writes (grep finds it only here, in `tests/run-installers-smoke.sh` and `peertube-browser-service-review.md`). It does not remove the new `engine/server/db/updater-increment.json`.

An operator reading "purge updater state" may expect the pointer to go. Either document that the pointer survives uninstall (harmless: a reinstall resumes the cycle), or extend the purge to it. Extending it would change `tests/run-installers-smoke.sh`'s expectations, so it is not recommended in this build.

**Regression risk.** None if unchanged.
</impact>
<impact path="scripts/run-services.sh" element="stop_one / status pgrep patterns (lines 216-267)">
**What changes.** Nothing.

**Why it matters.** It matches the Engine with `pgrep -f "engine/server/api/server.py"` (231, 245-260). Req 10's crontab line must not contain that string, and the planned line, which names only `scripts/run-catalog-update.sh`, does not.

**Regression risk.** None. A crontab line that ran the worker directly with a path argument containing the Engine path would make `stop` kill the wrong process, which the doc should warn against.
</impact>
<impact path="scripts/worktree-setup.sh" element="whitelist.db symlink (lines 27-28)">
**What changes.** Nothing.

**Why it matters.** The worker `.resolve()`s `--prod-db`, so in a worktree the default state path lands in main's `engine/server/db/`. A catalog update run from a worktree reads and advances main's pointer. That is consistent, since the dataset is the same, but surprising. Worth a line in UPDATER_WORKER.md.

**Regression risk.** Low. Tests always pass a tmp `--prod-db`, so they never touch it.
</impact>
<impact path="engine/server/db/updater-increment.json" element="new runtime artifact (pointer state file)">
**What changes.** A new file, created by the first successful incremental run. Its content is `{"last_group": int, "increments": int, "completed_at": "YYYY-MM-DDTHH:MM:SSZ"}`. Deleting it by hand restarts at group 0, the documented recovery for a corrupt file.

**What depends on it.** Every incremental run reads it under the lock. The file is owned by the user the run executes as: systemd's `SERVICE_USER`, or the cron user. If both paths are ever used with different users, the write fails with an `OSError` after the merge, and the run then re-crawls the same group daily until the owner is fixed.

**Regression risk.** Low. The ownership mismatch is worth a Triage row.
</impact>
<impact path="engine/server/db/jobs/docs/UPDATER_WORKER.md" element="Purpose/Inputs-Outputs (5-36), Execution Order (42-89), Trending Stage write bullet (98), Important Flags (209-238), Manual Run (240-246), Systemd Run (248-272), Logs (274-297)">
**What changes.**
- **Execution Order.** Steps are cross-referenced by number only inside this file (steps 2, 6, 7, 8, 9, 11, 12, 13, 15, 15.4); no other doc cites them. Add the new steps as sub-steps (for example 1a pointer read, 5a group filter, 8a pointer write) so the numbering does not shift.
- **Other sections.** See the docs checklist.

**Regression risk.** Documentation only.
</impact>
<impact path="DATA_BUILD.md" element="Automatic background updater (line 28)">
**What changes.** The line "Timer runs weekly (`OnCalendar=Fri *-*-* 20:00:00` by default), so Trending is up to a week old" becomes daily (`*-*-* 20:00:00`) with `--increments 7`: each run crawls one seventh of the hosts, so each host is refreshed about weekly, and Trending is up to a day old.

**Regression risk.** Documentation only.
</impact>
<impact path="DEPLOYMENT.md" element="units table (131), The updater timer (214, 228), outbound-443 paragraph (760), Triage table (~330-351)">
**What changes.**
- Line 131: `OnCalendar=*-*-* 20:00:00`.
- Line 214: "Weekly, it crawls" becomes "Daily, it crawls one seventh of the hosts (`--increments 7`)".
- Line 228: `UPDATER_FLAGS` defaults are already stale (missing `--timeout-ms 15000 --max-retries 3`); give the full new default including `--increments 7`, and say a custom value must keep it.
- Line 760: "the updater timer re-crawls weekly" becomes "daily, one seventh of the hosts per run".
- Optional Triage rows: the corrupt or unreadable pointer `RuntimeError` (fix or delete the file), and "pointer not advanced" after a merge (permissions on `engine/server/db/`).

**Regression risk.** Documentation only.
</impact>
<impact path="docs/project/adr/0010-trending-from-source-instances.md" element="Note (2026-10-03) paragraph (line 50)">
**What changes.** The note says the timer is weekly, so Trending is up to a week old, and that a failing host "survives one failed weekly run and is dropped after two". With daily runs, decision 1's "once a day" holds again, and Trending is at most a day old. That matches Consequences line 43.

The age-out sentence becomes "survives about nine consecutive failed daily runs", unless `AGE_OUT_MS` changes. That is a change to the operator decision recorded via issue 38, so surface it rather than silently rewriting. Add a dated note (for example "Note (issue 63): daily cadence") rather than editing the old one, matching ADR practice.

**Regression risk.** Documentation only, but it is an ADR conflict to flag.
</impact>
<impact path="CONTEXT.md" element="Trending entry (line 29), new Increment entry">
**What changes.**
- **Trending entry.** It says "by the updater's weekly trending stage; a host that fails a run keeps its list until it is more than 10 days old". Update "weekly" to "daily". The 10-day clause stays accurate as long as `AGE_OUT_MS` is unchanged.
- **New entry.** Add an **Increment** entry: "a fixed group of catalogue hosts, chosen by `sha1(host) % N`, that one catalog update run crawls; N is `--increments` (7 by default in the timer and `run-catalog-update.sh`); the next group comes from a pointer file advanced only after the run's merge commits". It must be distinct from the unrelated `--incremental` flags of `recompute-popularity.py` and `precompute-similar-ann.py`, a real confusion risk worth one clause.

**Regression risk.** Documentation only.
</impact>
<impact path="docs/project/adr/0005-raw-event-retention-keeps-ids.md" element="decision 3 (line 15) 'not the optional weekly updater'">
**What changes.** Nothing recommended. It is a historical rationale, and the decision (pruning in the Engine) is unaffected by a daily updater. Listed so the next step does not take it for an omission.

**Regression risk.** None.
</impact>
<impact path="docs/project/issues/43-updater-trending-launch-failure-skips-similarity.md" element="likelihood paragraph (line 14) 'the weekly similarity rebuild is lost'">
**What changes.** Optional: "weekly" becomes "daily", which lowers the cost of that open bug. The new held pointer-write error follows the same held-error pattern as `trending_error`, so it does not change issue 43's analysis.

**Regression risk.** None.
</impact>
<impact path="docs/project/issues/63-catalog-update-weekly-increments.md" element="Status line, delivery">
**What changes.** On delivery, set the Status to `complete`, record what was delivered (daily runs, 7 groups, pointer file, cron line), and move the issue to `docs/project/issues/archive/` per the tracker rules.

**Regression risk.** None.
</impact>
<impact path="docs/project/issues/issue-tracker.md" element="row 63 (line 11)">
**What changes.** Remove the row when issue 63 moves to `archive/`.

**Regression risk.** None.
</impact>
<impact path="docs/project/roadmap.md" element="DONE list (around line 37)">
**What changes.**
- Add a DONE entry for issue 63, like the other delivered issues, pointing at UPDATER_WORKER.md and the plan.
- Line 37's "fetched by the updater's weekly trending stage" is history in a DONE entry; update it to "daily" or leave it, as the operator prefers.

**Regression risk.** None.
</impact>
</impacts>

<impact path="scripts/run-services.sh" element="start_services / stop_services as called by the catalog-update shim (lines 143-198, 227-232; header line 8)">
**What changes.** No code change is planned. What changes is how often this runs and who is watching. On the cron path, the `systemctl` shim that `run-catalog-update.sh` writes (lines 98-115) turns the worker's Engine `stop` into `bash run-services.sh stop`, and its `start` into `bash run-services.sh start`. The `start` only happens when the Engine was running at stop time (STATE_FILE, line 103/107). I checked what that does here:
- **The stop affects all three services.** `stop_services` (227-232) stops the translate worker first, with SIGTERM and up to `WORKER_STOP_TIMEOUT=120` s (line 43). The comment at 41-42 says an in-flight job is requeued; a SIGKILL after 120 s leaves it `running` and costs a claim. It then stops the Client and the Engine. So every cron run also stops the Client and the translate worker for the merge, popularity and ANN window, not only the Engine.
- **The start can fail with no one watching.** `start_services` (143-198) needs `.env.bridge`, through `load_bridge_secret`, which `exit 1`s when the file is missing (95-111). It needs `curl` for `health_status` (124). It needs the Engine healthy within `HEALTH_TIMEOUT=300` s, and the translate worker alive 3 s after launch (it exits at once without ffmpeg, line 187-194). Any of these failing leaves the Client or the translate worker down after an unattended daily run. `run-catalog-update.sh:130-133` only re-checks the Engine, and only by `pgrep`, so a Client or translate-worker failure shows only in the detached log.
- **The relaunch runs in cron's environment.** Line 8 asks the operator to set `CUDA_VISIBLE_DEVICES` to pin the translate worker. The worker relaunched at line 185 inherits cron's minimal environment, so the pin is lost unless the crontab line sets it. Setting it in the crontab line has a side effect: it is also inherited by `updater-worker.py` and its embeddings, ANN and similarity children, so the updater's `--gpu` work is pinned to the same card.
- **GPU overlap.** Embeddings run before the Engine stop, and the similarity build runs after the start. The translate worker is running during both, so they compete with it for VRAM. A GPU failure there is retried on CPU by `run_with_cpu_fallback` (updater-worker.py:414-432) and logged, but the run does not fail. Today this happens weekly; with the plan it happens daily.

**What depends on it.** The cron line documented in UPDATER_WORKER.md (req 10), the translate worker's job queue, and the Client's availability. The systemd path is unaffected: there the worker calls real `systemctl` on the Engine units only.

**Regression risk.** Medium in operations, none in code. Nothing in the build changes this file. The risk is an undocumented daily restart of three services from a bare environment. Document in the cron section that each run restarts the Client and the translate worker (an in-flight translation is requeued). The crontab line must carry the environment the services need, such as `CUDA_VISIBLE_DEVICES=<uuid>`, accepting that it also pins the updater. Point to `catalog-update-*.log` for restart failures.
</impact>

<impact path="scripts/run-catalog-update.sh" element="">
.log (lines 20-21, 51-56)">
**What changes.** No code change is planned. Each detached run writes a new `${REPO_DIR}/catalog-update-$(date +%Y%m%d-%H%M%S).log` (line 52) in the repo root. With a daily cron that is about 365 files a year, and nothing prunes them. `.gitignore` line 3 (`*.log`) keeps them out of git. The cron line's `>/dev/null 2>&1` only discards the two "started" lines (54-55); the whole run, including `run-services.sh` restart failures, goes to this file.

**What depends on it.** It is the operator's only record of a cron run's shim and service-restart output; the worker's own lines also go to `updater-worker.log`.

**Regression risk.** Low: disk use and clutter in the repo root. Add a doc line in UPDATER_WORKER.md (cron section and Logs) telling the operator to prune these files periodically, for example `find <repo> -maxdepth 1 -name 'catalog-update-*.log' -mtime +30 -delete`, as a separate crontab line (it contains no `%`). Pruning in the script is an upgrade path and is not recommended in this build.
</impact>

<impact path="engine/server/db/jobs/updater-worker.py" element="setup_logging (lines 322-330) and default --logs path (line 111)">
**What changes.** Nothing in code. `setup_logging` attaches a plain `logging.FileHandler(log_path, "a")` (325) to `engine/server/db/updater-worker.log` (default at line 111). This happens on both the systemd and cron paths, in addition to the journal or stdout. With daily runs the file grows about seven times as fast as today, and nothing rotates it. The `*.log` pattern keeps it out of git. The three new log lines (pointer read, group filter, pointer written / not advanced) add to it.

**What depends on it.** Operators reading the worker log (UPDATER_WORKER.md Logs, 274-278). Three test files exec this module (`test_updater_worker.py`, `test_host_normalisation.py:87`, `test_install_updater_service.py:93`), and `test_updater_worker.py` reads log output from `main()` runs.

**Regression risk.** Low. Switching to `RotatingFileHandler` is out of scope, and it would touch logging that those tests exercise. Add a doc line in the Logs section saying the file is append-only and unrotated, and how to truncate or rotate it (for example a logrotate `copytruncate` rule, or truncating it between runs).
</impact>

## Documentation to update

- [x] `engine/server/db/jobs/docs/UPDATER_WORKER.md` - updated: I updated `UPDATER_WORKER.md` to cover `--increments N` / `--increment-state` and the daily `--increments 7` schedule, and added a section on running it from cron. I checked each claim against `updater-worker.py`, `run-catalog-update.sh`, `run-services.sh`, `install-updater-service.sh`, `uninstall-service.sh`, `worktree-setup.sh`, `fetch-trending.py` and `.gitignore`.
- [x] `DATA_BUILD.md` - updated: I updated the `DATA_BUILD.md` updater bullet: the timer now runs daily with `--increments 7`, each host is refreshed about weekly, and Trending is up to a day old.
- [x] `DEPLOYMENT.md` - updated: I updated DEPLOYMENT.md: the updater timer is now daily with `--increments 7` (each run crawls a seventh of the hosts), the `UPDATER_FLAGS` default is correct, and there are two new Triage rows for pointer-file failures.
- [x] `docs/project/adr/0010-trending-from-source-instances.md` - updated: Added a dated Note (2026-10-15, issue 63) to ADR-0010 about the daily cadence. The 2026-10-03 Note is unchanged.
- [x] `CONTEXT.md` - updated: CONTEXT.md: the Trending entry now says the trending stage runs daily, and there is a new glossary entry for **Increment**.
- [x] `docs/project/issues/63-catalog-update-weekly-increments.md` - updated: I closed issue 63 in place: its status is `enhancement, complete`, and a dated comment under `## Comments` records what was delivered, pointing to the plan and its record.
- [x] `docs/project/issues/issue-tracker.md` - updated: Removed row 63 ("Run the catalog update in weekly increments") from the open-issues table, because the issue is delivered and is being archived.
- [x] `docs/project/roadmap.md` - updated: I added a DONE entry for issue 63 to the roadmap and changed the issue 38 entry's "weekly trending stage" to "daily".
- [x] `docs/project/issues/43-updater-trending-launch-failure-skips-similarity.md` - updated: Issue 43 now calls the similarity rebuild "daily" instead of "weekly", since the updater timer runs every day.
- [x] `docs/project/adr/0005-raw-event-retention-keeps-ids.md` - out of scope: Decision 3's "not the optional weekly updater" is the historical rationale for pruning in the Engine. The decision does not depend on the updater's cadence, and the updater remains optional, so the decision is unaffected.
- [x] `docs/project/adr/0009-engine-blue-green-through-nginx-upstream-snippet.md` - out of scope: It says only that the updater stops and starts the Engine "on its own schedule", under the deploy lock. It states no cadence, and this build leaves the lock and the stop/start window unchanged.
- [x] `peertube-browser-service-review.md` - out of scope: This is a point-in-time external review of the repo as it stood then (F4 quotes `OnCalendar=Fri *-*-* 20:00:00`). It is a dated assessment, not a maintained description of current behaviour, so it is not rewritten.
- [x] `README.md` - out of scope: It mentions only `--purge-updater-state` / `--keep-updater-state` in the uninstall examples. It makes no claim about what the purge removes and says nothing about cadence or flags, so nothing in it became false. That the pointer survives the purge is documented in UPDATER_WORKER.md and DEPLOYMENT.md.

## Implementation plan

## Draft: incremental catalog update (issue 63)

### What has to be tested (drives the shape below)

- **Group function.** It is stable and equals `sha1(host) % N` on the stored string. Pin it with literals computed outside the helper.
- **Pointer read.** Missing file → group 0. Valid file → `(last + 1) % N`, including the wrap. Stored N differs → group 0 with a note. Every corrupt shape → `RuntimeError` naming the path. Bools are refused.
- **Pointer write.** The content is exact, no temp file is left behind, an existing file is overwritten, and a failure leaves the old file alone.
- **Staging filter.** Only the group's `instances` rows remain, `channels` is untouched, and the counts it returns are right.
- **`main` with `--increments`.**
  - The filter runs after the instances child and before the channels child.
  - A pre-merge failure leaves the pointer byte-identical and logs `pointer not advanced`.
  - A lock refusal leaves the pointer byte-identical.
  - A successful run writes the pointer after the merge child and before the popularity child.
  - A write `OSError` still runs ANN, trending and similarity, then fails the run.
  - A corrupt file, a negative N, `--sync-join-whitelist`, or a missing state directory fail before any child runs.
- **`main` without `--increments`.** The existing tests cover it, unchanged. One existing run also asserts that no state file appears.
- **Installers.** Both default to `--increments 7` and `OnCalendar=*-*-* 20:00:00`, and the worker's `parse_args` reads `increments == 7`.

### Module map

| File | Change |
|---|---|
| `engine/server/db/jobs/updater-worker.py` | `import hashlib`; 2 args; 4 helpers; 6 small call sites in `main()` |
| `engine/server/db/jobs/fetch-trending.py` | line 36 comment only |
| `scripts/run-catalog-update.sh` | `--increments 7` in the worker call; help paragraph; `sed` range |
| `engine/install-updater-service.sh`, `scripts/install-service.sh` | two default strings each |
| `.gitignore` | pointer file and its temp pattern |
| `tests/active/test_updater_worker.py` | new tests and one new harness; docstring clauses |
| `tests/active/test_install_updater_service.py` | new pins |
| Docs | per the settled checklist (summarised at the end) |

No new module, no new dependency, no new test file, so `tests/config.json` is unchanged. No TypeScript change, so no `dist/` rebuild is needed.

### `updater-worker.py`

**Import.** `import hashlib` goes between `fcntl` and `json`, alphabetically. `completed_at` uses the existing `time` module, so `datetime` is not imported.

**Constant**, next to `DEPLOY_LOCK_POLL_SECONDS`:
```python
INCREMENT_STATE_NAME = "updater-increment.json"
```

**`parse_args`.** The new arguments go right after `--resume-staging`, in the file's style. They use no `append` or custom action, so argparse keeps the last occurrence and `-- --increments 0` / an `UPDATER_FLAGS` override win.
```python
    parser.add_argument(
        "--increments",
        type=int,
        default=0,
        help=(
            "Split hosts into N fixed groups (sha1(host) %% N) and crawl only the next group "
            "after the one in --increment-state. 0 crawls every host. Refused with --sync-join-whitelist."
        ),
    )
    parser.add_argument(
        "--increment-state",
        default=None,
        help=f"Pointer file for --increments (default: {INCREMENT_STATE_NAME} next to --prod-db).",
    )
```
The `%%` is needed because argparse %-formats help strings. The `--max-instances` and `--max-channels` help texts each gain the sentence "With --increments the cap applies to the run's host group." The `description=` gains nothing. The per-group behaviour is documented in the flag help and in UPDATER_WORKER.md, which keeps the help diff small.

**Helpers.** They sit right after `prune_staging_local_non_ok_instances`, in this order.

```python
def host_increment_group(host: str, increments: int) -> int:
    """Return the fixed group of `host`, exactly as stored in instances.host, among `increments` groups."""
    return int(hashlib.sha1(host.encode("utf-8")).hexdigest(), 16) % increments
```
Invariant: `increments >= 1`. Every caller is guarded on N ≥ 1, so `% 0` cannot occur. The host is never re-normalised.

```python
def read_increment_pointer(state_path: Path, increments: int) -> tuple[int, str]:
    """Return the group this run crawls and what the pointer file held; refuse a file that cannot be trusted."""
    if not state_path.exists():
        return 0, "missing"
    fix = f"fix or delete {state_path} (deleting it restarts at group 0)"
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"increment pointer {state_path} is unreadable: {exc}; {fix}") from exc
    if not isinstance(state, dict):
        raise RuntimeError(f"increment pointer {state_path} is not a JSON object; {fix}")
    stored = state.get("increments")
    last = state.get("last_group")
    # type() rather than isinstance(): a JSON true/false would otherwise pass as 1/0.
    if type(stored) is not int or stored < 1:
        raise RuntimeError(f"increment pointer {state_path} has increments={stored!r}, not an integer >= 1; {fix}")
    if type(last) is not int or not 0 <= last < stored:
        raise RuntimeError(f"increment pointer {state_path} has last_group={last!r}, not an integer in [0, {stored}); {fix}")
    if stored != increments:
        return 0, f"N changed from {stored}, restarting at 0"
    return (last + 1) % increments, f"last_group={last}"
```
How each case is handled:
- **Missing key.** `.get` returns `None`, which fails the type check, and the message shows `None`.
- **Path is a directory.** `read_text` raises `IsADirectoryError`, an `OSError`, so it is refused.
- **No silent fallback.** There is no broad `except`, so nothing falls back to group 0 silently.

```python
def write_increment_pointer(state_path: Path, group: int, increments: int) -> None:
    """Record `group` as the last completed one: temp file in the same dir, fsync, os.replace."""
    payload = {
        "last_group": group,
        "increments": increments,
        "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    tmp = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=state_path.parent,
        prefix=f"{state_path.stem}.",
        suffix=".tmp",
        delete=False,
    )
    try:
        with tmp:
            json.dump(payload, tmp)
            tmp.write("\n")
            tmp.flush()
            os.fsync(tmp.fileno())
        os.replace(tmp.name, state_path)
    except BaseException:
        Path(tmp.name).unlink(missing_ok=True)
        raise
```
- **Temp file name.** With the default path the temp file is `updater-increment.<random>.tmp`, which is what `.gitignore` names.
- **Deliberate simplification: no directory fsync after `os.replace`.**
  - Ceiling: a power loss right after the replace can bring back the previous pointer, which costs one redundant re-crawl of a group. The INSERT_ONLY merge makes that harmless.
  - Upgrade path: `os.open(parent, O_RDONLY)` + `os.fsync` + `os.close` after the replace.

```python
def filter_staging_to_increment(staging_db: Path, group: int, increments: int) -> dict[str, int]:
    """Delete every staging instance outside `group`, so the crawl stages after it visit only that group's hosts."""
    conn = sqlite3.connect(staging_db.as_posix())
    try:
        hosts = [row[0] for row in conn.execute("SELECT host FROM instances WHERE host IS NOT NULL")]
        removed = [host for host in hosts if host_increment_group(host, increments) != group]
        conn.executemany("DELETE FROM instances WHERE host = ?", [(host,) for host in removed])
        conn.commit()
        kept = set(hosts) - set(removed)
        # Counted in Python: an IN (...) over ~1.8k hosts can pass SQLite's host-parameter limit on old builds.
        channels = sum(
            int(count)
            for domain, count in conn.execute("SELECT instance_domain, COUNT(*) FROM channels GROUP BY instance_domain")
            if domain in kept
        )
        logging.info(
            "increment filter group=%d hosts_kept=%d hosts_removed=%d staging_channels=%d",
            group,
            len(kept),
            len(removed),
            channels,
        )
        return {"kept": len(kept), "removed": len(removed), "channels": channels}
    finally:
        conn.close()
```
- **One transaction.** Python's sqlite3 opens an implicit transaction on the first DELETE, and `commit()` closes it.
- **What it touches.** It writes only to staging `instances`. Seeded `channels` and `videos` rows of other hosts stay put, and prod is never attached.
- **Empty group.** If the group is empty (tiny dev datasets), the crawl CLIs get an empty host list and the run merges nothing new. That is still correct, and the pointer still advances.
- **NULL hosts.** `instances.host` is `TEXT PRIMARY KEY`, which permits NULL in SQLite. No writer stores one, so a NULL row is left alone rather than hashed.

**`main()`.** These changes are additive. Every new statement is guarded on `args.increments >= 1`, so the N = 0 path executes exactly today's statements.

1. **Path resolution**, after `lock_file = ...`:
```python
    increment_state = (
        Path(args.increment_state).resolve()
        if args.increment_state
        else prod_db.parent / INCREMENT_STATE_NAME
    )
```
2. **Startup validation**, directly after the existing `--dry-run` check and before the lock:
```python
    if args.increments < 0:
        raise RuntimeError("--increments must be 0 (crawl every host) or a positive group count.")
    if args.increments >= 1 and args.sync_join_whitelist:
        raise RuntimeError("--increments cannot be combined with --sync-join-whitelist, which selects its own hosts.")
    if args.increments >= 1 and not increment_state.parent.is_dir():
        raise RuntimeError(f"--increment-state directory does not exist: {increment_state.parent}")
```
   The third check is the impact inventory's recommendation. It costs one line and catches a mistyped `--increment-state` before a 1–2 h crawl, not after the merge. The plan does not name it, but it adds no behaviour beyond refusing a run that would certainly fail to write its pointer.
3. **Locals**, beside `temp_files`: `selected_group: int | None = None`, `pointer_settled = False` and `pointer_error: OSError | None = None`.
4. **Outer `try`.** The existing `try: … finally:` at line 1122 gains an `except` before its `finally`:
```python
    except Exception as exc:
        if selected_group is not None and not pointer_settled:
            logging.error("pointer not advanced: %s", exc)
        raise
```
   - **Why here, not around the crawl section.** The plan said "a small try/except around the pre-merge section". The settled impact entry places it here instead, because a merge failure happens inside the service `try`, which a crawl-only wrapper misses.
   - **Lock refusal and corrupt file.** `selected_group is None` there, so no misleading line is logged. The `RuntimeError` is the message.
   - **Post-merge failures.** `pointer_settled` is already True there, so nothing is logged.
   - **Never swallowed.** The handler always re-raises with a bare `raise`.
   - **AST scans unaffected.** This `Try` has no `systemctl_cmd` in its `finalbody`, and trending and similarity stay outside the service `try`.
5. **Pointer read.** This is the first statement inside `with single_run_lock(lock_file):`, before `cleanup_similarity_leftovers`:
```python
            if args.increments >= 1:
                selected_group, pointer_read = read_increment_pointer(increment_state, args.increments)
                logging.info(
                    "increment read n=%d pointer=%s group=%d state=%s",
                    args.increments,
                    pointer_read,
                    selected_group,
                    increment_state,
                )
```
6. **Filter.** It goes inside `if run_crawl_stages:`, after the optional `prune_staging_local_non_ok_instances` and before `channels_cmd`. It applies the same way to fresh and `--resume-staging` staging.
```python
                if args.increments >= 1:
                    filter_staging_to_increment(staging_db, selected_group, args.increments)
```
7. **Pointer write.** It goes inside the service `try`, directly after the `merge-staging-db.py` `run_cmd` returns and before `if denied_hosts:` (the safety prune). `run_cmd` uses `check=True`, and merge-staging-db commits in one `BEGIN IMMEDIATE`…`commit`, so reaching this line means the merge committed.
```python
                if args.increments >= 1:
                    try:
                        write_increment_pointer(increment_state, selected_group, args.increments)
                        logging.info("pointer written last_group=%d state=%s", selected_group, increment_state)
                    except OSError as exc:
                        # The group's rows are in prod; the global steps still run so the ANN index matches it, and the run fails at the end.
                        logging.error("pointer not advanced: write failed: %s", exc)
                        pointer_error = exc
                    pointer_settled = True
```
   This nested `Try` has no `finalbody`, so the "exactly one `Try` whose `finally` starts the service" scan still holds.
8. **Held error.** It is raised at the end, after the existing `trending_error` raise:
```python
            if trending_error is not None:
                raise RuntimeError("trending stage failed") from trending_error
            if pointer_error is not None:
                raise RuntimeError(f"increment pointer not advanced: {pointer_error}") from pointer_error
```
   - **Order.** Trending raises first, so the existing exact `RuntimeError("trending stage failed")` pin holds. When both are set, the pointer failure is already in the log from step 7.
   - **No duplicate log line.** `pointer_settled` is True, so the outer `except` does not log it a second time.
   - **No "worker completed".** Either raise skips that line.
   - **Similarity failure.** If `run_similarity_stage` itself raises, that exception wins. The pointer failure is still logged.

**Req 4 trace:**

| Failure | Pointer |
|---|---|
| Lock refused | Read never reached |
| Corrupt file | Raises at read |
| Crawl CLI non-zero (`run_cmd` raises) | Unchanged; logged |
| Embeddings fail on GPU and CPU (`run_with_cpu_fallback` raises) | Unchanged; logged |
| `--fail-before-merge` | Unchanged; logged |
| Systemctl stop or deploy lock failure | Unchanged; logged |
| Merge non-zero | Unchanged; logged |
| Post-merge prune, popularity, ANN, `--fail-during-ann-build`, `--fail-after-merge-before-similarity`, copy, trending, similarity | Already written |

### `fetch-trending.py`, comment only

Line 36 becomes: `# The updater runs daily (issue 63): a host keeps its list through about nine consecutive failed runs and loses it once the list is over 10 days old (10-day window: operator decision, issue 38).` `AGE_OUT_MS` is unchanged. See "For the operator" below.

### `scripts/run-catalog-update.sh`

- **Invocation.** Line 125 becomes `  "${ACCEL}" --skip-local-dead --concurrency 5 --timeout-ms 15000 --max-retries 3 --increments 7 \`. It stays before `EXTRA_ARGS`, so `-- --increments 0` wins.
- **Help paragraph.** These lines are inserted after line 9:
```
#
# It passes --increments 7: each run crawls one of 7 fixed host groups, the one after the
# group recorded in engine/server/db/updater-increment.json, so a daily run (cron, see
# engine/server/db/jobs/docs/UPDATER_WORKER.md) refreshes every host about once a week.
# `-- --increments 0` crawls every host in one run.
```
- **`sed` range.** The header grows by 5 lines, so line 45's `sed -n '2,23p'` becomes `sed -n '2,28p'`. The implementer checks that `--help` ends at "...this script starts it again." and does not print `set -uo pipefail`.

### Installers

- `engine/install-updater-service.sh`:
  - line 32: `UPDATER_TIMER_ONCALENDAR="${UPDATER_TIMER_ONCALENDAR:-*-*-* 20:00:00}"`
  - line 33: `UPDATER_FLAGS="${UPDATER_FLAGS:---gpu --skip-local-dead --concurrency 5 --timeout-ms 15000 --max-retries 3 --increments 7}"`
  - usage line 54: `Systemd OnCalendar expression (default: daily 20:00)`
- `scripts/install-service.sh` lines 41–42: identical strings, so the two installers cannot drift. Usage line 91: `(default: daily 20:00)`.
- The installer warning when the flags lack `--increments` is not built. It is not in the plan, and the docs carry the warning. A plain-text check of the flags is the upgrade path.

### `.gitignore`

In the local data files section, beside the lock-file entries:
```
# Catalog update increment pointer (issue 63) and its atomic-write temp file
engine/server/db/updater-increment.json
engine/server/db/updater-increment.*.tmp
```

### Tests

**`tests/active/test_install_updater_service.py`:**
- **Prod test.** After the `--engine-upstream-snippet` assertion, add:
  - `assert _values(argv, "--increments") == ["7"], report` (this catches central/sub-installer drift);
  - `assert "OnCalendar=*-*-* 20:00:00" in previews.get("timer", []), report`.

  The round-trip tuple gains `args.increments`, expected `7`.
- **Dev test.** The pinned ExecStart ends `... --max-retries 3 --increments 7'`, and it adds the same OnCalendar assertion.
- **Docstrings.** The module docstring gains a clause: "both carry `--increments 7` and a daily `OnCalendar=*-*-* 20:00:00`". "today's `ExecStart`" becomes "the default `ExecStart`".

**`tests/active/test_updater_worker.py`** (new section after the tags tests):
- `HOSTS = ["a.example", "b.example", …]`, about 8 hosts. The pinned groups for N = 7 are literals, obtained once with `python3 -c 'import hashlib;print(int(hashlib.sha1(b"a.example").hexdigest(),16)%7)'`. That follows the `INJECT_ANN_ID` convention. Pick hosts so the chosen group holds ≥1 host and at least one host lies outside it.
- `test_host_increment_group_matches_pinned_sha1` checks the literals, and that N = 1 always gives 0.
- `test_read_increment_pointer_*`:
  - missing → `(0, "missing")`;
  - `{last 2, n 7}` → 3;
  - `{last 6, n 7}` → 0;
  - `{last 3, n 5}` with N = 7 → `(0, "N changed from 5, restarting at 0")`.

  Corrupt cases are parametrised: not JSON; non-UTF-8 bytes; `[]`; a missing key; `{"last_group": false, "increments": true}`; `increments: 0`; `last_group: 7` with n 7; `last_group: -1`; `last_group: "1"`; and a directory at the path. Each raises `RuntimeError` whose message contains the path.
- `test_write_increment_pointer_*`:
  - the content round-trips through `read_increment_pointer` and `completed_at` matches `^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$`;
  - the directory holds only the state file afterwards;
  - an existing file is replaced;
  - a missing parent dir raises `OSError` and no file appears;
  - `os.replace` monkeypatched to raise means the old file is byte-identical and no `.tmp` is left.
- `test_filter_staging_to_increment_*`: staging is built from `engine/crawler/schema.sql`, with `HOSTS` in `instances` and channels on several hosts. Afterwards `instances` equals the group's hosts, the `channels` rows are unchanged, and the returned dict equals the counts computed in the test.
- **`_run_crawl_main` changes.** It gains `extra: list[str] = ()` and `state: Path | None`. The fake instances child (`instances-cli.js` in cmd) inserts `HOSTS` into staging `instances`. The fake channels child records `SELECT host FROM instances` from staging into `run["hosts_at_channels"]`. With no `--increments`, today's tests pass through unchanged.
  - **New test, filter before channels.** `--increments 7` against a pre-written pointer: `hosts_at_channels` equals the selected group's hosts, the pointer file is byte-identical, and caplog has `pointer not advanced: Injected failure: before merge stage`.
- **New harness `_run_increment_main`.**
  - It is `_run_crawl_main` without `--fail-before-merge`, with `--skip-systemctl`, `--increments 7` and `--increment-state <tmp>`, and `run_similarity_stage` replaced by a recorder.
  - The fake child records whether the state file exists, and its content, at the merge child and at the `recompute-popularity.py` child.
  - It takes `fail_merge` and `fail_write` (monkeypatches `updater.write_increment_pointer` to raise `OSError("disk full")`).
- **Tests on that harness:**

  | Case | Expected |
  |---|---|
  | Success | Absent at merge, `last_group == g` at popularity; "pointer written last_group=g"; "worker completed" |
  | Merge child fails | Pointer unchanged; error is the merge `CalledProcessError`; "pointer not advanced" logged |
  | Write fails | ANN, trending and one similarity call still run; error is `RuntimeError` containing "increment pointer not advanced"; no "worker completed"; exactly one "pointer not advanced" line |

- **Refusals, each before any child.** Each asserts no child ran and the state file is byte-identical where one was written:
  - `--increments 7 --sync-join-whitelist`;
  - `--increments -1`;
  - `--increment-state <tmp>/missing/p.json`;
  - a corrupt pointer.
- **Lock refusal.** Hold `--lock-file` with `fcntl.flock` from the test (the same pattern as the deploy-lock test). Run `--increments 7`: `RuntimeError`, no child, pointer byte-identical.
- **N = 0.** In one existing crawl test, add `assert not (tmp_path / "updater-increment.json").exists()`.
- **Module docstring.** Gains one paragraph listing these clauses, per the file's convention.

### Docs (settled checklist; the content the draft commits to)

- **UPDATER_WORKER.md.** Purpose and Outputs (pointer file and temp name). Sub-steps 1a (read), 5a (filter) and 8a (write), so numbering is unchanged. Group rule and its simplification/upgrade path. Caps apply to the group, the instances stage stays global, and the refusal with sync-join. Trending (98). Resume Staging. Important Flags. Manual Run (`--increments 7`; `--increments 0` / `run-catalog-update.sh -- --increments 0` for a full crawl). Systemd Run: daily, `*-*-* 20:00:00`, a custom `UPDATER_FLAGS` must keep `--increments 7`, and installed units change only on reinstall. Logs: three lines, `updater-worker.log` unrotated (logrotate `copytruncate`), and the `catalog-update-*.log` pruning line.
- **New "Cron (no systemd)" section.**
  - The line: `0 20 * * * PATH=<dir of node>:/usr/local/bin:/usr/bin:/bin /usr/bin/bash /home/enduser/code/PeerTube-browser/scripts/run-catalog-update.sh >/dev/null 2>&1`, with `<dir of node>` = `dirname "$(command -v node)"`.
  - Optionally add `CUDA_VISIBLE_DEVICES=<uuid>` before `/usr/bin/bash`; it also pins the updater's GPU stages.
  - The line has no `%` and does not contain `engine/server/api/server.py`.
  - Operational notes: an overlapping run exits on the lock; the repo does not install the line; a worktree shares main's pointer; each run's stop/start restarts the Client and translate worker too, from cron's environment (`.env.bridge`, `curl` and `ffmpeg` are required); GPU sharing with CPU fallback.
  - The pruning line: `find <repo> -maxdepth 1 -name 'catalog-update-*.log' -mtime +30 -delete`.
- **Other docs.**
  - `DATA_BUILD.md:28`: daily with `--increments 7`, each host about weekly, Trending up to a day old.
  - `DEPLOYMENT.md`: lines 131, 214, 228 (the full default flags) and 760, plus two Triage rows (corrupt pointer → fix or delete it; "pointer not advanced" after the merge → write permission on `engine/server/db/`).
  - ADR 0010: a new dated "Note (issue 63)".
  - `CONTEXT.md`: the Trending entry says daily, and an **Increment** entry is added, distinct from `--incremental`.
  - Issue 63: complete and archived. The tracker row is removed and a roadmap DONE entry added.

### Check against plan and requirements (pass 1, converged)

| Req | Where it is met |
|---|---|
| 1 | Flag, N=0 guard everywhere, N=1 → group 0 with pointer |
| 2 | `host_increment_group` |
| 3 | `read_increment_pointer`, default path next to prod, `--increment-state`, N-changed reset, corrupt raise |
| 4 | Write site plus trace table |
| 5 | Filter site after the instances stage and local-dead prune, after the staging denylist prune, before channels, on fresh and reused staging |
| 6 | Unchanged |
| 7 | Read, filter and written/not-advanced lines |
| 8 | Startup refusal |
| 9 | Script, installers, test |
| 10 | Cron section |
| 11 | Docs |

Deviations from the plan, both taken from the settled impacts:
- The "not advanced" logging lives on the outer `try`, not on a pre-merge wrapper.
- A startup check on the state directory is added.

### For the operator (flagged, not changed)

At a daily cadence, `AGE_OUT_MS = 10 days` in `fetch-trending.py` stops meaning "a host survives one failed run, is dropped after two" (issue 38's decision, ADR 0010). It now means about nine failed daily runs. The draft keeps 10 days and rewrites the comment and docs to say so. Restoring "two failed runs" would mean `AGE_OUT_MS ≈ 2 days`, which moves the pins in `tests/active/test_fetch_trending.py`. That is the operator's call, and the ADR 0010 note records it either way.

### Phases

#### Phase 1 - Crawl one group [code]

**Files touched.** engine/server/db/jobs/updater-worker.py (EDITED)

**Checkpoint.** Seam: `updater-worker.py` `main()` entered in-process through `sys.argv`, with only `subprocess.run` faked. It follows the existing `_run_crawl_main` harness in `tests/active/test_updater_worker.py`: real `schema.sql` staging and prod, fake crawler `dist/`, `--fail-before-merge`. The harness gains `extra` and `state` arguments. Its fake `instances-cli.js` child inserts a fixed HOSTS list (about 8 hosts) into staging `instances`. Its fake `channels-cli.js` child records `SELECT host FROM instances` from staging. C1: with `--increments 7 --increment-state <tmp>` and a pre-written pointer `{last_group: g-1, increments: 7}`, the hosts seen at the channels child equal exactly the HOSTS whose group is g. The groups come from literals computed outside the helper (`python3 -c 'import hashlib;...'`, the INJECT_ANN_ID convention), and the hosts are chosen so that group g has at least one host and at least one host is outside it. This excludes three wrong implementations: a filter placed after channels, a filter selecting `last_group` instead of `last_group+1`, and a hash on a re-normalised host. C2 is parametrised over four refusals: a corrupt pointer file, `--increments -1`, `--increments 7 --sync-join-whitelist`, and `--increment-state <tmp>/missing/p.json`. For each it asserts that `main` raises `RuntimeError`, that no child ran (calls list empty), and that the pointer file is byte-identical where one was written. That excludes validation placed after the lock or after the instances stage.

**Intent.** With `--increments N` ≥ 1, `updater-worker.py` `main()` reads the pointer under the lock and deletes every staging `instances` row outside the selected group before the channels crawl, and it refuses at startup any run whose pointer or increment flags cannot be trusted.

- C1 - The channels crawl child sees exactly the staging hosts whose sha1(host) % N equals (stored last_group + 1) % N.
- C2 - A corrupt pointer, a negative N, `--sync-join-whitelist`, or a missing state directory stops the run before any child runs, and the pointer file is left byte-identical.

**Outcome.** ### engine/server/db/jobs/updater-worker.py

Phase 1 of the plan's `updater-worker.py` section. All of it is additive, and every new statement in `main()` is guarded on `args.increments >= 1`. A run without `--increments` executes the same statements as before and reads no pointer file.

- **Imports and constant.** Added `import hashlib` (stdlib) and `INCREMENT_STATE_NAME = "updater-increment.json"` next to the deploy-lock constants.
- **New flags in `parse_args`.**
  - `--increments` takes an int and defaults to 0, which means a full crawl.
  - `--increment-state` is a path and defaults to unset.
  - Both are plain options, so if a flag is given twice argparse keeps the last one. That is what lets a later `-- --increments 0` force a full crawl.
  - The `--max-instances` and `--max-channels` help texts now say that with `--increments` the cap applies to the run's host group.
- **New helpers**, placed after `prune_staging_local_non_ok_instances`:
  - `host_increment_group(host, increments)` returns `sha1(host as stored, UTF-8) % increments`. The host is not normalised again first.
  - `read_increment_pointer(state_path, increments)` returns `(group, what was read)`:
    - a missing file gives group 0;
    - a file whose stored N differs from `--increments` gives group 0 and the note "N changed from X, restarting at 0";
    - otherwise the group is `(last_group + 1) % N`.
  - `read_increment_pointer` raises `RuntimeError`, naming the file and saying to fix or delete it, when the file is unreadable, is not JSON, is not an object, or has a missing or out-of-range `increments` or `last_group`. JSON booleans are refused because the check uses `type() is int`.
  - `filter_staging_to_increment(staging_db, group, increments)` deletes every staging `instances` row outside the group in one transaction. It counts the group's staging channels in Python, which avoids a large `IN (...)`. It logs group, hosts kept, hosts removed and channels, and returns those counts.
- **Changes in `main()`:**
  - **State path.** `increment_state` is `--increment-state` resolved, or `prod_db.parent / updater-increment.json` when the flag is not given.
  - **Startup refusals.** Three checks sit right after the existing `--dry-run` check, before the lock and before any child. Each raises `RuntimeError`:
    - a negative `--increments`;
    - `--increments` together with `--sync-join-whitelist`;
    - a state-file directory that does not exist.
  - **Pointer read.** It is the first statement inside `single_run_lock`, before `cleanup_similarity_leftovers`. It logs N, what the pointer held, the selected group and the state path.
  - **Filter call.** `filter_staging_to_increment` runs after the instances child and the optional `--skip-local-dead` prune, and before the channels command is built. It applies the same way to fresh and `--resume-staging` staging.
  - **New local.** `selected_group: int | None = None` is declared beside `temp_files`.
- **Left for later phases.** The pointer write (phase 2) and the "pointer not advanced" handling (phase 3) are not in this phase.

#### Phase 2 - Advance on commit [code]

**Files touched.** engine/server/db/jobs/updater-worker.py (EDITED), .gitignore (EDITED)

**Checkpoint.** Seam: `main()` in-process with `subprocess.run` faked, through a new `_run_increment_main` harness built on the `_run_trending_main` pattern (real crawl and merge path, `--skip-systemctl`, `--increments 7 --increment-state <tmp>`, `run_similarity_stage` replaced by a recorder). The fake child snapshots whether the state file exists, and its content, at the `merge-staging-db.py` child and at the `recompute-popularity.py` child. C1: on a successful run the pointer is absent (or still holds the prior content) at the merge child, and holds `last_group == g, increments == 7` at the popularity child. This excludes a write before the merge and a write at the end of the run. C2 is parametrised over three ways the run can stop before the merge commits: `--fail-before-merge`, the merge child exiting non-zero, and the `--lock-file` already held via `fcntl.flock` from the test (the deploy-lock test's holder pattern). For each it asserts that the run raised and that the pre-written pointer is byte-identical. This excludes advancing on a failed merge and reading or writing the pointer outside the lock.

**Intent.** The increment pointer file records the run's group exactly when the `merge-staging-db.py` child has returned success, written atomically between the merge and the post-merge steps.

- C1 - A successful run writes last_group equal to the crawled group after the merge child and before the popularity child.
- C2 - A run that stops before the merge commits leaves the pointer file byte-identical.

**Outcome.** ### `engine/server/db/jobs/updater-worker.py`
- Added `write_increment_pointer(state_path, group, increments)` after `read_increment_pointer`. It writes `{"last_group": group, "increments": increments, "completed_at": "<UTC ISO-8601 Z>"}\n`, the same shape `read_increment_pointer` reads back. The write is atomic: `tempfile.mkstemp` in the pointer's own directory (named `<pointer name>.<random>.tmp`), write, `fsync`, then `os.replace` over the pointer. If anything fails, the temp file is removed and the error re-raised. A crash therefore leaves either the old pointer or the new one, never a half-written file. It logs `increment written last_group=… n=… state=…`.
- In `main()`, with `--increments >= 1`, `write_increment_pointer(increment_state, selected_group, args.increments)` is called right after the `merge-staging-db.py` `run_cmd` returns, before the denylist safety prune and the `recompute-popularity.py` child (C1). A run that stops earlier never reaches it, so the pointer stays byte-identical (C2). That covers `--fail-before-merge`, a merge child exiting non-zero (`run_cmd` raises `CalledProcessError`), and a held run lock. A failure in a later step leaves the pointer advanced, so a group that is already merged is not crawled again.

### `.gitignore`
- Added `engine/server/db/updater-increment.json*`. This ignores the default pointer file (`updater-increment.json` next to the default prod DB in `engine/server/db/`) and any temp file a crashed write leaves behind. Neither is matched by the existing `*.db*` patterns.

#### Phase 3 - Report a pointer that did not advance [code]

**Files touched.** engine/server/db/jobs/updater-worker.py (EDITED)

**Checkpoint.** Seam: the same `_run_increment_main` harness, plus caplog. C1 is parametrised over a `--fail-before-merge` stop and a merge child that fails. Each run logs exactly one `pointer not advanced` record, and that record carries the failure's reason. This excludes a missing log, a duplicate from both the inner and the outer handler, and a log line on a lock refusal: a lock-held control asserts zero such records. C2: with `updater.write_increment_pointer` monkeypatched to raise `OSError("disk full")`, the ANN build child, the trending child and one similarity-stage call all occur. The run's error is a `RuntimeError` containing `increment pointer not advanced`, no `worker completed` record exists, and exactly one `pointer not advanced` record exists. This excludes three wrong implementations: letting the OSError propagate immediately, which would skip the global steps; swallowing it, which would give a green run; and logging it twice.

**Intent.** `updater-worker.py` `main()` reports every increment run whose pointer did not advance, and holds a pointer write failure until the global post-merge steps have run.

- C1 - A run that fails after the pointer read and before the merge commits logs exactly one `pointer not advanced` line.
- C2 - A failed pointer write fails the run, with `increment pointer not advanced`, only after the ANN, trending and similarity steps have run.

**Outcome.** ### `engine/server/db/jobs/updater-worker.py`

`main()` now logs `increment pointer not advanced` for every `--increments` run that read the pointer and did not advance it, and holds a failed pointer write until the global post-merge steps have run.

- **New `pointer_pending` flag.** It is set to True right after `read_increment_pointer` succeeds. It goes back to False once `write_increment_pointer` has returned or has logged its own failure.
- **New `except BaseException` clause** on the outer `try` around `single_run_lock` (it re-raises). When `pointer_pending` is still True, it logs `increment pointer not advanced group=<g> state=<path>: <exc>`. This covers C1:
  - a run stopped by `--fail-before-merge` or by the merge child failing gets exactly one line carrying that error's text;
  - a run refused at the lock never read the pointer, so it logs nothing;
  - a completed run already cleared the flag, so it logs nothing.
- **Pointer write failure (C2).** The `write_increment_pointer` call after the merge is now wrapped in `except OSError`. On failure it logs one `increment pointer not advanced ... ; running post-merge steps before failing the run` line, keeps the error in `pointer_error` and lets the run continue: denylist prune, popularity, ANN build, Engine start, crawl.db copy, trending and the similarity stage.
- **End of the run.** After `run_similarity_stage`, a held `pointer_error` raises `RuntimeError("increment pointer not advanced: <error>")`, chained from the original error. So the run fails and never logs `worker completed`. The flag is already False by then, so the outer handler does not log a second line.
- **When both fail.** This check comes before the existing trending-error raise. If the pointer write and trending both fail, the pointer error is what gets raised; the trending failure is still logged as before.

#### Phase 4 - Launchers default to daily increments [code]

**Files touched.** engine/install-updater-service.sh (EDITED), scripts/install-service.sh (EDITED), scripts/run-catalog-update.sh (EDITED), engine/server/db/jobs/fetch-trending.py (EDITED)

**Checkpoint.** C1 seam: the installer as a subprocess under `--dry-run`, through the existing `tests/active/test_install_updater_service.py` harness (fake `--project-dir`, stub systemctl, nginx and logger on PATH, the worker's `parse_args` loaded in-process). Prod, directly and via the central installer: `_values(argv, "--increments") == ["7"]`, the timer preview contains `OnCalendar=*-*-* 20:00:00`, and `worker.parse_args()` on that ExecStart gives `increments == 7`. Dev: the pinned ExecStart ends `--max-retries 3 --increments 7` and the same OnCalendar line is present. This excludes the two installers drifting apart, a flag the worker cannot parse, and the weekly schedule left in place. C2 seam: `scripts/run-catalog-update.sh` as a subprocess, which is a new rung-2 test with no existing harness. The script resolves the repo from its own location, so the test copies it into a temp tree's `scripts/`. That tree gets a stub `venv/bin/python3` that writes its argv to a file and exits 0, a stub `node` on PATH, and an `engine/crawler/dist/` directory. The test runs `--foreground --skip-build -- --increments 0` and asserts that the recorded argv holds `--increments 7` before `--increments 0`, and that the worker's `parse_args` on that argv reads `increments == 0`. A second run without `--` asserts that `--increments 7` alone is present. This excludes a missing flag and a flag placed after EXTRA_ARGS, which would make the full-crawl override impossible.

**Intent.** Every shipped launcher runs the updater worker as one increment of seven per day: both installers' default unit and `scripts/run-catalog-update.sh`.

- C1 - The default updater unit from both `engine/install-updater-service.sh` and `scripts/install-service.sh` runs the worker with `--increments 7` on `OnCalendar=*-*-* 20:00:00`.
- C2 - `scripts/run-catalog-update.sh` passes `--increments 7` to the worker ahead of the operator's `--` flags, so `-- --increments 0` overrides it.

**Outcome.** ### `engine/install-updater-service.sh`
- The default `UPDATER_TIMER_ONCALENDAR` is now `*-*-* 20:00:00` (daily at 20:00). It was `Fri *-*-* 20:00:00`.
- The default `UPDATER_FLAGS` is now `--gpu --skip-local-dead --concurrency 5 --timeout-ms 15000 --max-retries 3 --increments 7`. `updater_exec` already appends `${UPDATER_FLAGS}` after the fixed flags, so both the prod and the dev `ExecStart` end `--max-retries 3 --increments 7`.
- The env var, `--updater-oncalendar` and `--updater-flags` overrides work as before.
- Usage text: `--updater-oncalendar` says `(default: daily 20:00)`. `--updater-flags` says the default carries `--increments 7`, and that a daily timer without it crawls every host each day.

### `scripts/install-service.sh`
- The same two default strings as the updater installer, so the two cannot drift. This matters because the central installer always forwards `--updater-oncalendar` and `--updater-flags` to the sub-installer, and those replace its defaults.
- The same two usage-text additions.

### `scripts/run-catalog-update.sh`
- **Worker call:** `--increments 7` goes after `--max-retries 3` and before `"${EXTRA_ARGS[@]...}"`. Argparse keeps the last occurrence, so `-- --increments 0` still forces a full crawl.
- **Help header:** a new paragraph after line 9 says the script passes `--increments 7` (one of 7 fixed host groups per run, the pointer in `engine/server/db/updater-increment.json`, each host refreshed about weekly on a daily run). It also says `-- --increments 0` crawls every host.
- **`sed` range:** the `--help` range moves from `2,23p` to `2,28p`, so help still ends at "...this script starts it again." I checked the new line numbers by reading the file, but did not run `--help`.

### `engine/server/db/jobs/fetch-trending.py`
- Comment only, on `AGE_OUT_MS`: the updater now runs daily (issue 63), so a host keeps its list through about nine consecutive failed runs. It loses the list once it is over 10 days old; the 10-day window is the operator decision from issue 38.
- `AGE_OUT_MS` itself is unchanged. The plan's "For the operator" note still stands: keeping 10 days changes issue 38's "survives one failed run, dropped after two" meaning, and that is the operator's call.

### `tests/active/test_install_updater_service.py` → `tests/archive/01-63-catalog-update-weekly-increments/`
- **Retired:** `test_updater_installer_dev_dry_run_keeps_single_name_rule`. It was cut whole and unchanged into `tests/archive/01-63-catalog-update-weekly-increments/test_install_updater_service.py`, as an excerpt with a provenance docstring, following the earlier archive folders.
- **Why it could not be repointed:** its last assertion pins the exact pre-build dev `ExecStart` string ending `--max-retries 3'`, which is the default C1 replaces. No fixture or harness constant feeds that string, and `Tree.run` is shared with the phase-4 checkpoint, which needs the real default.
- **README:** a new `README.md` in that folder records what the test asserted, why no repoint could save it, and what covers it now. The checkpoint's dev test covers the argv. The dev single-name sudoers rule and the "no snippet" claim have no active test until the harvest restores this test with `--increments 7'` pinned.
- **Rest of the file:** the prod test and all helpers stay active, unchanged, and the prod test keeps passing with the new defaults. The file is not emptied, so its `test_groups` entry is unaffected.
- **Not updated:** the module docstring's line 4 still describes the dev test. I left it for the harvest.

**Beyond the files named.** tests/active/test_install_updater_service.py — I cut out the dev test (`test_updater_installer_dev_dry_run_keeps_single_name_rule`), because its exact `ExecStart` pin encodes the pre-build `UPDATER_FLAGS` default that C1 replaces. The plan's impact inventory names this file, but phase 4's files list does not.
tests/archive/01-63-catalog-update-weekly-increments/test_install_updater_service.py — new file: the cut test, kept unchanged.
tests/archive/01-63-catalog-update-weekly-increments/README.md — new file: the retirement entry.


