# Videos the updater adds have no tags

Status: bug, ready-for-agent
Origin: plan 54 (`docs/project/plans/54-53-tags-on-cards-and-tag.md`), Phase 2, where the Recent feed's first page carried no tagged row

## Problem

On 2026-10-06 the dev `whitelist.db` held 909,004 videos, 55,213 of them with `tags_json` NULL. The newest 2000+ videos all have NULL tags, so plan 54's tag chips and tag search show nothing for recent uploads, and the Recent feed's first pages show no chips.

`engine/server/db/jobs/updater-worker.py` crawls new videos into a staging DB with `videos-cli.js --new-videos`. The channel video listing carries no tags; only the crawler's per-video tags pass (`videos-cli.js --tags`) fetches them, and the updater never runs it. `merge-staging-db.py` copies every column the two DBs share, `tags_json` included, so the merge would carry tags if staging had them. Embeddings are built on staging before the merge, so new videos are also embedded without their tags.

Videos added this way are not in `engine/crawler/data/crawl.db`: there, the newest videos are absent, and `crawl.db` holds 37,014 NULL-tag rows of its own.

## Fix

1. The updater runs `videos-cli.js --tags --db <staging>` after the videos crawl and before the embeddings stage. Staging holds only the run's new videos, so the pass is bounded. A failure of this step is logged and the run continues: the videos merge untagged, and the backfill job below fills them later.
2. `engine/server/db/jobs/backfill-null-tags.py` fills `tags_json` for videos already in a whitelist DB whose `tags_json` is NULL, from each video's `/api/v1/videos/<uuid>` on its own instance (source-instance fetch rules). It skips active-denylisted hosts, writes through `videos` so the `videos_fts` triggers keep tag search current, and leaves `'[]'` rows alone (re-requesting those is why the dataset build's tags stage never converges). A failed fetch leaves the row NULL, so a later run retries it.

## State

Both parts applied 2026-10-06, without a build plan, at the operator's direction. Tests: `tests/active/test_updater_worker.py` (the tags child's argv and place, and a failing tags child not stopping the run) and `tests/active/test_backfill_null_tags.py`. Each was checked to fail against a broken version. Still to do: run the backfill against the dev `whitelist.db` (the command is in `DATA_BUILD.md`, "Filling NULL tags in whitelist.db"). Close the issue once that run has filled the backlog.

## Not fixed here

`run-dataset-build.sh --from sync` rebuilds `videos` from `crawl.db` (`sync-whitelist.py` `rebuild_content_tables` runs `DELETE FROM videos`), so it drops every video the updater added. That needs its own issue.
