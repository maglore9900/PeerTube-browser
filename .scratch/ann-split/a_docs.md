### Documentation to update

- [ ] `DATA_BUILD.md`
  - **Line 155:** embeddings are copied with their `ann_id`, or `ann_id` is computed when the crawl DB lacks it.
  - **Line 159:** the exact check now includes `ann_id`.
  - **Lines 161-172:** "The migration is additive ... without touching rows ... second run does nothing" is no longer true for `video_embeddings`. Add the one-time step: stop the Engine, run `migrate-whitelist.py` (a table rebuild that keeps rowids and needs about 1.4 GB free plus the default full-file backup), start the Engine. No index rebuild is needed until plan B.
  - **Line 191:** the "schedule with the stable-ANN-ids cutover" note points at that step.
- [ ] `DEPLOYMENT.md`
  - **Triage table:** a row for the `migrate-whitelist.py` message from `sync-whitelist`, merge and `build-video-embeddings`.
  - **Deploy steps:** the one-time migration before the first dataset build or updater run on the new code.
- [ ] `engine/server/db/jobs/docs/UPDATER_WORKER.md`
  - **Prerequisite:** the one-time migration before the first updater run on the new code.
  - **`--resume-staging` (lines 48, 149, 186):** a pre-migration staging DB fails with the AC2 message and must be recreated by running without the flag.
  - **Merge:** it refuses an unmigrated prod or staging.
  - **Line 197:** `--inject-replace-embedding-for-test` keeps the row's `ann_id`.
- [ ] `engine/server/db/jobs/docs/ORCHESTRATOR_SMOKE_TEST.md`
  - **Source DB:** it must be migrated, since mini-prod copies its schema.
- [ ] `engine/server/README.md` - line 9 explains the `migrate-whitelist.py` requirement for `videos.language`; add that the writers now also need its `ann_id` step.
- [ ] `docs/project/issues/08-stable-ann-ids.md` - at close, a dated comment that plan A delivered. The issue stays open; plan B closes it.

## Changes to the carried draft for plan A

- **Section 3, the migration:** the copy carries `rowid` (AC-A4). Its column list starts `rowid, video_id, ...` and its select starts `rowid, video_id, ...`. The docstring adds that rowids are kept so a rowid index built before the migration stays valid.
- **Section 1, `ann_ids.py`:** `ANN_ID_SOURCE` lands here though nothing in plan A reads it; plan B's index build and gate import it. Drop it if this build's Step 5 prefers to add it in plan B.
- **Section 13, the smoke test:** only the mini-prod guard part. The `validate_outputs` `id_source` assertion is plan B's.
- **Section 14, tests:** only the shared helper, `test_ann_ids.py`'s AC1, AC2 and AC3 cases, the migration tests (plus the rowid check) and `test_video.py`'s inserts. The AC5 cases, `test_stale_ann_index.py` and the rest of the fixture churn are plan B's.

