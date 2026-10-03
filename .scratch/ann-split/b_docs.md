### Documentation to update

- [ ] `DATA_BUILD.md`
  - **Line 13:** "random rowid cache" becomes the random ANN-id cache.
  - **Cutover:** after plan A's migration, stop the Engine, run `build-ann-index.py`, start the Engine. A stored `random-cache.db` is rebuilt automatically.
  - **Line 232:** "The index uses `video_embeddings.rowid` as ids" becomes `video_embeddings.ann_id`; mention `id_source` and the AC4 refusal message.
  - **Line 290:** "random rowid pool" changes.
  - **Line 335:** `select count(*) from random_rowids` becomes `random_ann_ids`.
- [ ] `DEPLOYMENT.md`
  - **Line 42:** the cutover (stop, build index, start), and that the Engine refuses to start on an index whose sidecar `id_source` is not `video_embeddings.ann_id`.
  - **Triage table:** a row for that startup refusal, fixed by `build-ann-index.py`, and one for the `migrate-whitelist.py` message from `build-ann-index`.
  - **Line 421:** a first start rebuilds an old-shape random cache.
- [ ] `engine/server/db/jobs/docs/UPDATER_WORKER.md`
  - **Line 61:** the ANN rebuild writes `id_source: video_embeddings.ann_id`.
  - **Cutover:** the index rebuild before the first updater run on the new code.
- [ ] `engine/server/db/jobs/docs/ORCHESTRATOR_SMOKE_TEST.md`
  - **Validations list (around line 115):** the sidecar `id_source` assertion.
- [ ] `engine/server/api/recommendations/docs/LAYER_PARAMS.md`
  - **Line 130:** "has no `random_rowids` table" becomes `random_ann_ids`; an old-format file counts as having no table.
  - **Line 140:** "The cache holds only rowids (`random_rowids`)" becomes ANN ids (`random_ann_ids`), resolved by `ann_id`, with the hash-uniform sampling window.
- [ ] `engine/server/api/recommendations/docs/OVERVIEW.md`
  - **Line 15:** "drops rowids already seen" / "unseen rowid" becomes ANN ids.
  - **Line 69:** "Holds a prebuilt list of rowids" becomes ANN ids (`random_ann_ids`).
- [ ] `engine/server/README.md` - the Engine refuses to start until the index is rebuilt on `ann_id`, pointing at DATA_BUILD.
- [ ] `docs/project/issues/08-stable-ann-ids.md` - at close: `Status: enhancement, complete`, moved to `docs/project/issues/archive/`.

## Changes to the carried draft for plan B

- Sections 1-7 (`ann_ids.py`, the migration and the writers) are delivered by plan A and are not carried. Read `engine/server/data/ann_ids.py` in the tree for the names this plan imports.
- **Section 13, the smoke test:** only the `validate_outputs` `id_source` assertion; the mini-prod guards are plan A's.
- **Section 14, tests:** the AC5 cases in `test_ann_ids.py`, `test_stale_ann_index.py`, and the fixture churn except `test_video.py`'s inserts (plan A). The shared helper and the AC1-AC3 and migration tests are plan A's.

