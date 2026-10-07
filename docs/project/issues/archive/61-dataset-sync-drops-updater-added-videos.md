# A dataset rebuild from sync drops every video the updater added

Status: bug, ready-for-agent
Origin: issue 60 (`docs/project/issues/60-updater-added-videos-have-no-tags.md`), found while tracing the missing tags

## Problem

`scripts/run-dataset-build.sh --from sync` (and any full run, which passes through the sync stage) runs `engine/server/db/jobs/sync-whitelist.py --db engine/crawler/data/crawl.db --output-db engine/server/db/whitelist.db`. Its `rebuild_content_tables` runs `DELETE FROM video_embeddings`, `DELETE FROM videos` and `DELETE FROM channels` (`sync-whitelist.py:464-466`), then reloads them from `crawl.db`.

The updater worker never writes `crawl.db`. It crawls new videos into its own staging DB and merges them straight into `whitelist.db` (`updater-worker.py`, `merge-staging-db.py`). So every video and channel the updater has added since the last full crawl exists only in `whitelist.db`, and the next sync deletes it.

Measured 2026-10-06 (read-only, dev DBs): 18,843 `whitelist.db` videos are absent from `crawl.db`, all with embeddings, published up to the newest video in the catalogue. A sync would remove them, and the following embeddings, ANN index and similarity stages would rebuild without them. The Recent feed would lose its newest pages until the updater crawls them again. The updater skips videos already in prod by `--existing-db`, but after the sync they are no longer in prod, so they would come back. That costs a full re-crawl of each host's new videos, and the re-crawled videos get new `ann_id`s and lose any trending ranks or similarity rows in the meantime.

The existing operator guidance to resume a stalled build with `--from sync` (memory `dataset-build-tags-stage-never-converges`) walks straight into this.

## Options

- **O1. Sync stops deleting what crawl.db does not hold.** `rebuild_content_tables` upserts from `crawl.db` and deletes only rows of hosts leaving the whitelist (and denylisted ones), so updater-added rows survive. This changes the "wholesale reload" design and its trigger-dropping fast path, and leaves deleted-upstream videos to the existing moderation and error paths.
- **O2. The updater also writes crawl.db.** After a successful merge, the run copies its staged `videos` and `channels` rows into `crawl.db`, so the crawl DB stays the full source. This adds a second write target to the updater and a lock to coordinate with a crawl running against `crawl.db`.
- **O3. The build carries updater-only rows across the sync.** Before the sync stage, `run-dataset-build.sh` copies the rows `whitelist.db` holds and `crawl.db` lacks into `crawl.db`. This narrows the fix to the build script, but any other caller of `sync-whitelist.py` still loses the rows.

O2 keeps `crawl.db` as the one source of truth, which is what the sync design assumes. It is the likely recommendation, pending triage.

## Triage (2026-10-06)

The `videos.language` column was checked before choosing a fix.

- The dev `crawl.db` predates the column. `sync-whitelist.py` refuses a crawl DB without it (`ensure_schema_compatibility`'s superset check, which runs before the delete), so a bare `--from sync` against today's dev DBs fails rather than deletes. A full build first runs the crawler's enrichment stage. That opens `crawl.db` and adds the column (`migrateVideosLanguage`, `engine/crawler/src/db.ts`), and the sync then proceeds and deletes.
- 7,866 `whitelist.db` videos carry a language, and 7,834 of them are updater-only rows. The copy keeps their language, so the column is no reason to choose against O2.
- The other 32 are in `crawl.db` too, with no language there. A sync blanks their language whatever this issue does. That is a small, separate loss and is not fixed here.

O2 was chosen by the operator.

## Fix (applied 2026-10-06, without a build plan)

- `engine/server/db/jobs/copy-to-crawl-db.py` inserts into a crawl DB the instances, channels and videos a whitelist DB holds and the crawl DB lacks. It works on the columns both share and never changes a row the crawl DB holds. It first adds `videos.language` when the crawl DB predates it. Running it again copies nothing.
- `updater-worker.py` runs it from prod into `--crawl-db` (default `<crawler-dir>/data/crawl.db`) after the Engine is started again and before trending. A failure is logged and the run goes on; copying from prod, not staging, means the next run catches up. A host with no crawl DB skips it.
- Tests: `tests/active/test_copy_to_crawl_db.py`, plus two cases in `tests/active/test_updater_worker.py`. The updater cases were checked to fail against a broken version.
- Trial on a copy of the dev `crawl.db`, reading the live `whitelist.db`. It copied 27 instances, 24,125 channels and 18,843 videos in 8 s. After it, no `whitelist.db` video is missing from the copy, and no copied video lacks its channel. A second run copied nothing. One earlier attempt failed once on the attach with `database disk image is malformed` and then succeeded unchanged; the cause was not found.
- Not verified: a sync run end to end against the copied crawl DB. It needs a 5 GB `whitelist.db` copy.

The one-off copy reached the dev `crawl.db` in two runs. The first, at 14:14, copied the 18,843 videos before the issue-60 backfill finished. The job then gained the NULL-tags fill, and a second run filled 33,734 `tags_json` values (`instances=0 channels=0 videos=0 tags_filled=33734`). Closed 2026-10-06.
