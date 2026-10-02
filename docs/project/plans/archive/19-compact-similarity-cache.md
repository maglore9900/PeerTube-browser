# Compact similarity cache and duplicate whitelist indexes

## Requirements

### Asked for

The operator asked why `engine/server/db/similarity-cache.db` is 7.3 GB and `engine/server/db/whitelist.db` 3.3 GB, then chose three of four proposed reductions: O1 (compact similarity-cache schema), O2 (drop the per-domain purge indexes) and O4 (drop the duplicate `(video_id, instance_domain)` indexes in `whitelist.db`). O3 (float16 embeddings) was not chosen.

### Purpose

Cut the disk the Engine's databases take without changing what any caller of the similarity cache sees.

### Measured starting point (read-only, 2025-10-01)

- `similarity-cache.db`: 7,881,256,960 bytes, 1,924,135 pages of 4096, 0 free. 890,052 `similarity_sources` rows, 17,787,388 `similarity_items` rows; 888,168 sources hold exactly 20 items. `video_id` averages 36 chars (UUIDs in the sample), `instance_domain` about 18; 1,526 distinct similar hosts.
- Size by object: `sqlite_autoindex_similarity_items_1` 2,739.6 MB, `similarity_items` 2,460.8 MB, `similarity_source_rank_idx` 1,460.8 MB, `idx_similarity_items_similar_instance_domain` 535.7 MB, `idx_similarity_items_source_instance_domain` 527.3 MB, `similarity_sources` and its two indexes about 157 MB.
- `whitelist.db`: 3,518,222,336 bytes. `video_embeddings` 1,843.5 MB (897,889 × 384-dim float32 = 1,536 B each), `videos` 829.4 MB, `videos_fts_data` 274.7 MB. `idx_videos_id_instance` (67.0 MB) and `idx_video_embeddings_id_instance` (67.0 MB) index exactly `(video_id, instance_domain)`, the same columns in the same order as `sqlite_autoindex_videos_1` and `sqlite_autoindex_video_embeddings_1` (checked with `pragma_index_info`).

### Acceptance criteria

- **AC1 (O1a, revised at Step 3):** `similarity-cache.db` holds exactly two tables: `video_keys(key INTEGER PRIMARY KEY, video_id TEXT NOT NULL, instance_domain TEXT NOT NULL, UNIQUE(video_id, instance_domain))` and `similarity_sources(source_key INTEGER PRIMARY KEY, computed_at INTEGER NOT NULL, neighbours BLOB NOT NULL)`. `neighbours` packs each neighbour in rank order as a little-endian int32 `video_keys.key` followed by a float32 score (8 bytes per neighbour); rank is position + 1. `similarity_items` no longer exists. Keys are local to the cache file. The cache migrated from today's 20-per-source file and a 1000-per-source build are measured at close; the estimates are about 0.2 GB and about 7 GB.
- **AC2:** `fetch_cached_similarities` and `has_cached_similarities` keep their signatures, and `fetch_cached_similarities` returns the same dicts (`video_id`, `instance_domain`, `score`, `rank`) in rank order. Scores are stored as float32, the precision FAISS returns them in. The Engine's write on a home-layer miss (`store_similarity_cache`) and `precompute-similar-ann.py` write the new shape. All three precompute modes (full, `--incremental`, `--refresh-existing`) select sources through `video_keys`.
- **AC3 (O2):** `purge_similarity_for_host` and `collect_similarity_host_stats` work through `video_keys` and return the same count keys and values as today (`similarity_items` counts source-neighbour pairs removed, an entry whose source and neighbour are both on the host counted once). A purge removes the host's sources, removes the host's keys from every other source's `neighbours`, and deletes the host's `video_keys` rows. A host with no `video_keys` rows costs one indexed lookup; otherwise the purge scans `similarity_sources`. The per-domain indexes are no longer created.
- **AC4 (O4):** `ensure_video_indexes` stops creating `idx_videos_id_instance` and `idx_video_embeddings_id_instance` and drops them where they exist. `idx_videos_uuid_instance` stays.
- **AC5:** The updater's shadow copy, gate and swap work on the new shape; the gate's table check is `video_keys` and `similarity_sources`.
- **AC6 (Q1):** A one-time job `engine/server/db/jobs/migrate-similarity-cache.py` converts a legacy-shape cache into a new-shape file, keeping every source and item, Engine-written entries included. It does not touch FAISS.
- **AC7 (Q2):** The Engine at start, `precompute-similar-ann.py` and the updater refuse a legacy-shape cache with a message naming `migrate-similarity-cache.py`, in the style of `data/embedding_space.py`'s refusals.
- **AC8 (Q3):** `whitelist.db` is not vacuumed by any code. The documentation carries the optional one-off `VACUUM` (Engine stopped, about 3.5 GB temporary space) that returns the freed pages to the filesystem.

### Scope

In scope: AC1-AC8.

Out of scope: O3 (float16 embeddings), plan 17 (stable ANN ids, `docs/project/plans/17-stable-ann-ids.md`), `videos_fts`, backward compatibility with a legacy-shape cache (refused, not read).

Plan 17 is unaffected: its scope excludes rebuilding or re-keying the similarity cache, its AC7 keeps precompute's output keys on `(video_id, instance_domain)`, and the local keys never cross the cache module's boundary. Both builds edit `precompute-similar-ann.py`; the second to land rebases.

### Consistency constraints

- New code matches the style of the file it lands in.
- Job CLIs keep their current arguments; the new migration job follows `migrate-whitelist.py`'s CLI shape.
- Refusal messages say what is wrong and name the command that fixes it.
- Backward compatibility is not a requirement.

### Conflicts

- **Neighbour depth (found at Step 3, resolved by the operator).** The approved row design assumed today's 20 neighbours per source. The Engine reads `DEFAULT_SIMILAR_PER_LIKE = 1000` per source (`engine/server/api/server_config.py:380`) and the updater precomputes `--top-k 1000 --refresh-existing` (`engine/server/db/jobs/updater-worker.py:512-518`); today's file is a single early 20-per-source build (one `computed_at` across all 890,052 sources, no rank above 20). At 1000 the legacy shape is about 350 GB, rows about 20-25 GB, packed blobs about 7 GB. The updater cycle of 2026-10-01 started that refresh at 07:01; the GPU run exited 1 after 40 minutes, the CPU retry gave up in 10 s, and no gate or swap ran (`engine/server/db/updater-worker.log:31-34`). Disk exhaustion is suspected and not verified.
- **Measured depth** (`tests/tmp/probe_neighbour_depth.py`, 300 random seeds, live index, nprobe 16, top 1000, one row per author, floors 0.25 and 0.35 agree): a distinct-author pool of 48 is reached by 91% of seeds at a median 125 raw neighbours (p90 480); 192 by 71% at a median 472 (p90 844); 300 by 51% at a median 715 (p90 926). Cutting depth would push most up-next requests into the live ANN fallback, so 1000 stays.
- **Operator decision:** O1a, one packed blob per source, keeping 1000 neighbours. O1c (author dedup at precompute, about 2-3 GB) was explained and deferred: it ties the cache to `similarity_max_per_author` and loses same-author backfill when read-time filters (NSFW hidden, error threshold, deleted video) drop an author's first video.

### Housekeeping done outside the build

`tmp/fts/real.db` (3.36 GB, a Sep 25 copy of `whitelist.db`, referenced nowhere) was moved to `delete_me/real.db` at the operator's direction for the operator to delete. Its four small siblings in `tmp/fts/` were left in place.

### Test trees

- `active`: `tests/active`
- `working`: `tests/tmp`

Every test this build writes goes into `tests/tmp`; the harvest moves what lasts.

### Baseline suite state

Freshly run 2025-10-01 via `validate_tests.py` (bare): exit 0, GREEN. 42 groups, 41 answered by the banked record (`tests/last_test_validation.json`), 1 run (`test_search_fusion.py`, 10 passed, no `test_groups` map entry).

## High-level plan

Approved by the operator 2025-10-01 with rows; revised to packed blobs (O1a) at the operator's decision during Step 3 (see Requirements → Conflicts).

### Approach

- **One schema owner.** `engine/server/data/similarity_cache.py` holds the new schema, the neighbour codec (pack and unpack of `(key, score)` pairs), a shape check (`compact` / `legacy` / `empty`), and a refusal helper naming `migrate-similarity-cache.py`. `precompute-similar-ann.py` drops its own `ensure_schema` and `record_similarities` and imports the shared ones, as it already imports `data.embedding_space`. A write interns the source and its neighbours into `video_keys` (`INSERT OR IGNORE`, then select the keys), packs the neighbours, and upserts one `similarity_sources` row. A read selects one blob, unpacks the first `limit` neighbours, resolves their keys in one `video_keys` lookup, and returns the same dicts as today. (AC1, AC2)
- **Precompute selection.** The `--incremental` and `--refresh-existing` queries attach the output cache and join `similarity_sources` through `video_keys`. (AC2)
- **Host purge.** It resolves the host's keys from `video_keys`; with none it is done. Otherwise it deletes the host's sources, scans every other source's blob once, rewrites those that reference a host key, deletes the host's `video_keys` rows, and counts in the same pass. The per-domain indexes are no longer created. (AC3)
- **Whitelist indexes.** `ensure_video_indexes` replaces its two duplicate `CREATE`s with `DROP INDEX IF EXISTS`. (AC4)
- **Updater gate.** The table check adds `video_keys` and refuses a legacy shadow. The shadow copy and swap are whole-file and unchanged. (AC5)
- **Migration job.** `migrate-similarity-cache.py --in <legacy> --out <new>` builds `<new>.tmp`, walks the legacy items in `(source, rank)` order, packs each source's neighbours through the shared write path, checks source and neighbour counts against the input, and renames into place. It refuses to overwrite `--out` and never writes `--in`. (AC6)
- **Refusals.** Engine start (`server.py`, before `ensure_similarity_schema`), the precompute job on `--out`, the updater gate, and the host purge refuse a legacy shape with a message naming the migration job. The Engine's post-swap reopen treats a legacy file as a failed reopen and keeps its handle. (AC7)
- **Docs only.** The VACUUM step and the cutover order: stop the Engine, deploy, migrate, move the new file into place, start. (AC8)

### Alternatives considered

- **Text keys with a better table shape** (`WITHOUT ROWID`, PK `(source, rank)`, no rank index): about 2.5-3 GB at 20 per source, over 100 GB at 1000, because each row still carries about 108 bytes of text.
- **Integer-keyed rows** (`similarity_items(source_key, rank, similar_key, score) WITHOUT ROWID`, the first approved design): a plain SQL purge, but about 20-25 GB at 1000 per source.
- **O1c, author dedup at precompute:** about 2-3 GB, deferred by the operator; it ties the cache to `similarity_max_per_author` and loses same-author backfill under read-time filters.
- **Packed uuid16 + host-id blobs:** smaller still, but assumes UUID video ids; `video_keys` keeps any text id.
- **Keying on plan 17's `ann_id`:** 8-byte keys against 4, and a dependency on an unbuilt plan.
- **Rebuild instead of migrate:** rejected at Q1; it recomputes every entry and loses Engine-written ones.
- **Read a legacy cache as a miss:** rejected at Q2; every request falls through to live ANN compute and every write fails.

### Risks

- **R1: hard cutover.** The Engine refuses to start until the cache is migrated. The Engine is stopped during migration, so no miss writes are lost.
- **R2: orphan keys.** A refresh that rewrites a source's neighbours leaves unreferenced rows in `video_keys`. Bounded by distinct videos ever seen (about 1M rows, about 70 MB); the host purge removes that host's keys.
- **R3: precompute write throughput.** Interning adds an insert and a select per source write (up to 1001 keys); measured at close.
- **R4: purge cost.** A host that still has keys means a full pass over every blob (about 7 GB at 1000 per source). The updater reprunes every denied host on every shadow build; a host already purged has no `video_keys` rows and costs one lookup. Measured at close.
- **R5: fixture churn.** `tests/active/test_precompute_similar_ann.py`, `test_similar.py`, `test_similarity_candidates.py`, `test_updater_worker.py` and `engine/server/db/jobs/tests/test-moderation-integration.py` build legacy-shape caches by hand.
- **R6: disk.** The migrated file (about 0.2 GB) sits beside the 7.3 GB original until the operator removes it. The first updater refresh at 1000 per source then needs about 7 GB for the shadow on top of the active file and `.prev.db`; 58 GB is free.
- **R7: score precision.** Scores drop from SQLite REAL (float64) to float32. FAISS returns float32, so precomputed scores lose nothing; the live-miss path is checked at Step 3.

### Limitations

- Pages freed inside `whitelist.db` stay in the file until the operator runs `VACUUM`.
- `similarity-cache.prev.db` stays legacy until the first updater swap after migration replaces it.

### Tradeoffs accepted

- No backward compatibility: a legacy cache is refused.
- A one-time manual migration on deploy.
- Fixture churn across five test files.

## Impacts

### engine/server/data/similarity_cache.py — schema, codec, shape check, read and write

- **Path:** `engine/server/data/similarity_cache.py`
- **Changes:** `SIMILARITY_ITEM_COLUMNS` (11-18) goes. `ensure_similarity_schema` (21-48) creates `video_keys` and the blob-carrying `similarity_sources`. New: neighbour pack/unpack, `video_keys` interning, the shape check and the legacy refusal naming `migrate-similarity-cache.py`. `fetch_cached_similarities` (85-112) reads one blob, unpacks the first `limit`, resolves keys, and returns the same four-key dicts with `rank` = position + 1; it still swallows `sqlite3.Error` as `[]`. `has_cached_similarities` (115-129) checks `similarity_sources` by source key. `store_similarity_cache` (132-176) interns, packs, upserts one row and commits. The build-marker helpers (51-82) are untouched.
- **Depends on it:** `similarity_cache_manager.py`, `similarity_candidates.py`, `server.py:104,339`, `updater-worker.py` (marker helpers), `precompute-similar-ann.py` (after this build), the migration job, tests `test_similarity_candidates.py` and `test_updater_worker.py` (import `ensure_similarity_schema`).
- **Risk: high.** Every cache read and write goes through it. A wrong rank base, byte order or key resolution silently changes up-next and home pools.

### engine/server/data/similarity_cache_manager.py — cache policy

- **Path:** `engine/server/data/similarity_cache_manager.py`
- **Changes:** none. It calls `fetch_cached_similarities`, `has_cached_similarities` and `store_similarity_cache` by signature only (19-23, 51, 83, 96).
- **Depends on it:** `similarity_candidates.py`.
- **Risk: low**, provided AC2 holds. Its `score is None` miss rule (56) can no longer fire, since a packed score is never NULL; the legacy schema allowed NULL `score`.

### engine/server/data/similarity_candidates.py — `_refresh_similarity_handle` reopen probe

- **Path:** `engine/server/data/similarity_candidates.py`
- **Changes:** the probe at 283-284 reads `similarity_items`, which no longer exists. It becomes the shape check: a compact file passes; a legacy or invalid file fails the reopen and keeps the old handle (the existing failure path, 287-290).
- **Depends on it:** every cache read and write in the Engine after an updater swap.
- **Risk: medium.** Missing this makes every reopen fail after the first swap, so the Engine would serve a stale handle forever.

### engine/server/api/server.py — Engine start

- **Path:** `engine/server/api/server.py`
- **Changes:** 338-339 open the cache and call `ensure_similarity_schema`. The legacy refusal runs before schema creation, so a legacy file stops start-up with the message. A missing or empty file still gets the new schema.
- **Depends on it:** every Engine start, including the test fixture in `tests/active/conftest.py:106-148`, which starts the Engine against the repo's real `engine/server/db/similarity-cache.db`.
- **Risk: high.** See the Engine-backed tests entry and the coordination entry: once this lands, no Engine starts on the current legacy file.

### engine/server/data/moderation.py — host purge and stats

- **Path:** `engine/server/data/moderation.py`
- **Changes:** `purge_similarity_for_host` (228-280), `collect_similarity_host_stats` (283-323) and `ensure_similarity_purge_indexes` (326-356) are rewritten per AC3. `ensure_similarity_purge_indexes` keeps its name and its `bool` return (two callers use both) and creates nothing on the new shape, or goes, with its callers updated; Step 5 decides. Stats keys stay `similarity_items`, `similarity_sources`, `similarity_items_as_source`, `similarity_items_as_similar`, `similarity_items_total_mentions`. Legacy refusal applies. `purge_host_data` (the whitelist side) is untouched.
- **Depends on it:** `instance-denylist-cli.py:22-28,202,242,249,265`, `updater-worker.py:622,658` (`purge_hosts`, `purge_hosts_from_similarity`), `test-moderation-integration.py`, `test_updater_worker.py` (reprune).
- **Risk: high.** A miscounted or partial blob rewrite leaves a denied host's videos in pools; the counts feed CLI logs and the updater summary.

### engine/server/data/videos.py — `ensure_video_indexes`

- **Path:** `engine/server/data/videos.py`
- **Changes:** 23-24 and 30-31 change from `CREATE INDEX IF NOT EXISTS idx_videos_id_instance` / `idx_video_embeddings_id_instance` to `DROP INDEX IF EXISTS`. 21-22 (`idx_videos_uuid_instance`) stays.
- **Depends on it:** `server.py:336` (every Engine start). Lookups on `(video_id, instance_domain)` fall to the primary-key autoindexes, same columns, same order.
- **Risk: low.** The drop runs against the live `whitelist.db` on the first Engine start with this code; dropping two 67 MB indexes takes a write lock briefly.

### engine/server/db/jobs/precompute-similar-ann.py — job writer and selection

- **Path:** `engine/server/db/jobs/precompute-similar-ann.py`
- **Changes:** `SIMILARITY_ITEM_COLUMNS` (35-42), `ensure_schema` (140-167) and `record_similarities` (229-272) go, replaced by imports from `data.similarity_cache`. `--reset` (420-422) deletes from the new tables. The selection queries (456-471) join `out_cache.similarity_sources` through `out_cache.video_keys`. `--reset-only` and `--recreate-out-db` create the new schema through the shared helper. Legacy `--out` is refused before work starts. Commit cadence (every 500 sources, 543-544) stays; `store_similarity_cache` commits per call today, so the job needs a non-committing write or keeps its own batching (Step 5).
- **Depends on it:** `updater-worker.py:498-524` (`--refresh-existing`, `--top-k 1000`), `scripts/run-dataset-build.sh:251-258` (`--top-k 20 --recreate-out-db`), `tests/active/test_precompute_similar_ann.py`, `DATA_BUILD.md`.
- **Risk: high.** Its throughput at 1000 neighbours (R3) decides how long the updater's similarity stage runs.

### engine/server/db/jobs/updater-worker.py — similarity gate, purge, stage

- **Path:** `engine/server/db/jobs/updater-worker.py`
- **Changes:** `similarity_gate_reason` (732-761): the table check becomes `{video_keys, similarity_sources}`, and a legacy shadow fails the gate with a reason naming the migration job. `count_similarity_sources` (721-729) is unchanged (counts `similarity_sources`). `purge_hosts` (597-629) and `purge_hosts_from_similarity` (649-663) are unchanged in code and pick up AC3 through `purge_similarity_for_host`. `backup_similarity_db`, `swap_similarity_db`, `run_similarity_stage` (708-824) are unchanged.
- **Depends on it:** the nightly `peertube-updater.timer`, `engine/server/db/jobs/tests/test-orchestrator-smoke.py`, `tests/active/test_updater_worker.py`.
- **Risk: medium.** The timer runs repo code nightly against the real cache; see the coordination entry.

### engine/server/db/jobs/instance-denylist-cli.py — purge CLI

- **Path:** `engine/server/db/jobs/instance-denylist-cli.py`
- **Changes:** none, or only the `ensure_similarity_purge_indexes` call at 242-248 if Step 5 removes the function. It reads the same five stats keys (195-198, 253-261).
- **Depends on it:** operators running a manual host purge.
- **Risk: low.**

### engine/server/db/jobs/migrate-similarity-cache.py — NEW migration job

- **Path:** `engine/server/db/jobs/migrate-similarity-cache.py`
- **Changes:** new, per AC6. CLI shape follows `engine/server/db/jobs/migrate-whitelist.py`; it imports the shared write path from `data.similarity_cache` as the precompute job does.
- **Depends on it:** the one-time cutover on main, the test Engine's cache during this build (see coordination), `DEPLOYMENT.md`, `DATA_BUILD.md`.
- **Risk: medium.** It is the only path from the 7.3 GB file to a cache the new code accepts.

### scripts/run-dataset-build.sh — full dataset build

- **Path:** `scripts/run-dataset-build.sh`
- **Changes:** none. It runs precompute with `--recreate-out-db`, which creates the new shape. It builds at `--top-k 20` while the updater refreshes at 1000; that mismatch predates this build and is not changed here.
- **Risk: low.**

### scripts/worktree-setup.sh — shared cache symlink

- **Path:** `scripts/worktree-setup.sh`
- **Changes:** none in code. Line 27 symlinks `similarity-cache.db` from main into every worktree, so a worktree Engine and main's Engine share one file.
- **Risk: high for this build's sequencing**; see the coordination entry.

### tests/active — Engine-backed tests on the real cache (coordination)

- **Path:** `tests/active/conftest.py`
- **Changes:** none. The `engine` fixture (106-148) starts `engine/server/api/server.py` against the repo's real DB files. The nine groups using the `engine` or `engine_client` fixture or `ENGINE_SERVER` (`test_blocks.py`, `test_dislike_profile.py`, `test_frontend_blocks.py`, `test_frontend_reactions.py`, `test_frontend_upnext_pager.py`, `test_random_cache.py`, `test_server.py`, `test_server_config.py`, `test_similar.py`) depend on the real `similarity-cache.db` being in the shape the code accepts.
- **Risk: high.** From the phase that adds the Engine-start refusal onward, every Engine-backed test fails until the cache the test Engine opens is migrated. The operator's long-running Engine (:7070) and the nightly updater read the same file with whatever code they last loaded.

### tests/active/test_similar.py — `_cache_entry` reads the real cache

- **Path:** `tests/active/test_similar.py`
- **Changes:** `_cache_entry` (709-718) and the docstring at 46-52 read `similarity_sources` and `similarity_items` directly from the shared cache. They change to read the entry through the new shape (the shared read helper, read-only). The "1 to 47 rows" premise for the linux and cooking seeds holds after migration (20 rows each today), and fails after a 1000-per-source refresh, which is outside this build.
- **Risk: medium.**

### tests/active/test_similarity_candidates.py — marker and reopen tests

- **Path:** `tests/active/test_similarity_candidates.py`
- **Changes:** fixtures at 185, 200-201, 252-254, 286 insert and read legacy tables. They move to the shared write helper and the new tables. Literal scores like `0.5` are exact in float32; any non-dyadic literal reads back changed.
- **Risk: medium** (R5).

### tests/active/test_updater_worker.py — gate and reprune tests

- **Path:** `tests/active/test_updater_worker.py`
- **Changes:** fixtures at 191-193, 202, 237, 250, 348, 378-380, 391 insert, read and delete legacy rows. They move to the new shape. The reprune test (348-391) compares the purge's result to a hand-written SQL delete; that oracle becomes a blob-level expectation.
- **Risk: medium** (R5).

### tests/active/test_precompute_similar_ann.py — job tests

- **Path:** `tests/active/test_precompute_similar_ann.py`
- **Changes:** fixtures at 95-96, 106-107, 187, 208-210 move to the new shape (the table set asserted at 208 becomes `{video_keys, similarity_sources}`).
- **Risk: medium** (R5).

### engine/server/db/jobs/tests/test-moderation-integration.py — standalone job test

- **Path:** `engine/server/db/jobs/tests/test-moderation-integration.py`
- **Changes:** its own legacy `ensure_similarity_schema` (187-210), inserts (230-250), counts (451-452, 900-901) and the raw query at 1060 move to the new shape. Not part of the `validate_tests.py` suite; run by hand.
- **Risk: low** (R5).

### engine/server/db/jobs/tests/test-orchestrator-smoke.py — standalone smoke

- **Path:** `engine/server/db/jobs/tests/test-orchestrator-smoke.py`
- **Changes:** none expected; it starts with no cache and compares bytes on gate failure. Re-run at close.
- **Risk: low.**

### DATA_BUILD.md

- **Path:** `DATA_BUILD.md`
- **Changes:** 274-277 describe selection against `similarity_sources` and the 20-row trade-off; 317 counts `similarity_sources` (still valid). Gains the cache's shape in one line, the migration command, and the optional `whitelist.db` `VACUUM`.
- **Risk: low.**

### DEPLOYMENT.md

- **Path:** `DEPLOYMENT.md`
- **Changes:** gains the one-time cutover (stop Engines, deploy, migrate, move into place, start) and the refusal message in its troubleshooting table (211).
- **Risk: low.**

### engine/server/db/jobs/docs/UPDATER_WORKER.md

- **Path:** `engine/server/db/jobs/docs/UPDATER_WORKER.md`
- **Changes:** gate list line 89 names the two tables; line 99 (reopen "checks both cache tables") becomes the shape check.
- **Risk: low.**

### CONTEXT.md

- **Path:** `CONTEXT.md`
- **Changes:** possibly a **Similarity cache** entry defining `video_keys` keys as local to the cache file, so no reader mistakes them for ANN ids or rowids. Step 9 decides.
- **Risk: low.**

### docs/project/adr/0008-similarity-cache-handoff-through-files.md

- **Path:** `docs/project/adr/0008-similarity-cache-handoff-through-files.md`
- **Changes:** none expected; line 18's "schema check" stays true in kind.
- **Risk: low.**

### engine/server/db/jobs/docs/ORCHESTRATOR_SMOKE_TEST.md

- **Path:** `engine/server/db/jobs/docs/ORCHESTRATOR_SMOKE_TEST.md`
- **Changes:** line 17 ("schema-only active cache") stays true. Checked at Step 9.
- **Risk: low.**

### Highest risk

1. **Engine-backed tests and live processes on the real cache** (`tests/active/conftest.py`, `scripts/worktree-setup.sh`, `engine/server/api/server.py`). Once the start refusal lands, no Engine starts on the legacy file: not the suite's, not the operator's on restart, not the one the nightly updater restarts. Sequencing decides whether the build can run its own suite.
2. **The codec and read path** (`engine/server/data/similarity_cache.py`). Every pool goes through it, and a wrong rank base or key resolution is silent.
3. **The host purge** (`engine/server/data/moderation.py`). A partial blob rewrite leaves denied-host videos served, and it runs on every shadow build.

### Reassessment

#### Pass 1

**Entries checked against the files.** Every entry was opened at its path. One did not hold as first drafted: the Engine-backed test entry named `test_video.py` and "Client groups"; a search for the `engine`/`engine_client` fixtures and `ENGINE_SERVER` found nine groups, and `test_video.py` is not among them. The entry now lists the nine.

1. **Will it still work as intended?** Yes. Every reader of the cache goes through `fetch_cached_similarities` / `has_cached_similarities` (via `similarity_cache_manager.py`) or the shape check, every writer through `store_similarity_cache` or the precompute job, and every purge through `purge_similarity_for_host` / `collect_similarity_host_stats`. No other code reads the tables. FAISS returns float32 scores on both the precompute and live-miss paths (`ann.py:77`, `precompute-similar-ann.py:528`), so R7 loses no precision.
2. **Ramifications.** Once the Engine-start refusal lands, no Engine starts on the current legacy file: the suite's `engine` fixture, the operator's Engine on restart, and the Engine the nightly updater stops and restarts. The updater's precompute also refuses the legacy shadow, so the nightly cycle fails at the similarity stage until the cutover. `test_similar.py`'s "1 to 47 rows" premise holds only while entries stay at 20; the first 1000-per-source refresh breaks it (not this build's change, recorded for the operator).
3. **What else must happen.** The cache the test Engine opens must be migrated by the time the refusal lands, and the live processes must not meet new code with the legacy file.
4. **How original functionality changes.** Callers see none. Operators see a refusal on a legacy cache, a one-time migration, a purge that rewrites blobs, and two fewer indexes in `whitelist.db`.

**New impact (needs a decision): sequencing against shared state.** This session runs on main, which is also what the operator's Engine (:7070/:7072) and the nightly updater timer run from, and the suite's Engine opens main's real cache.

**Operator decision: A2, build on main with an early cutover.** Recorded as an impact:

### Sequencing on main — real cache cutover inside the build (coordination)

- **Path:** `engine/server/db/similarity-cache.db`
- **Changes:** the phase that lands the Engine-start refusal also lands the read/write path and the migration job, so no Engine runs new code against a legacy file. Before that phase's checkpoint runs an Engine, the real cache is migrated: the migration writes the new file, the 7.3 GB original moves to `delete_me/` with `mv -n` (a rename on the same filesystem, no extra space) as the rollback copy, and the new file moves into place.
- **Operator coordination:** pause `peertube-updater.timer` until the build closes; stop the long-running Engine for the migration and restart it on the new code afterwards. An old-code Engine still running at the swap keeps serving from its old handle (its reopen probe reads `similarity_items`, fails, and keeps the handle) but must not be restarted on old code, which would create legacy tables in the new file.
- **Depends on it:** the nine Engine-backed test groups, `test_similar.py`'s reads of the seed entries.
- **Risk: high**, carried by the phase order and the operator steps above.

#### Pass 2

Opened the files the new entry touches (`similarity_candidates.py:261-297` reopen behaviour, `server.py:337-340`, `scripts/worktree-setup.sh`). The old-code reopen behaviour is as stated. No new impact surfaced and no entry is unconfirmed; Steps 3-4 have converged. Operator approved A2.
### Documentation to update

- [x] `DATA_BUILD.md` — **updated.** Step 5's "This output is large — expect the cache to exceed the source database" was false of the delivered layout; replaced with the two-table layout, the 8-byte packed neighbour, the measured 0.34 GB at `--top-k 20` and the ~7 GB estimate at 1000, the legacy refusal and the `migrate-similarity-cache.py` command with its guarantees. New section "Reclaiming freed space in whitelist.db" for the dropped duplicate indexes and the optional `VACUUM`. Selection wording at 274-277 still true (a source is "in `similarity_sources`" by its row): no update there.
- [x] `DEPLOYMENT.md` — **updated.** The `reopen failed` row names an older-layout file as not valid and points at the conversion; a new row covers an Engine restart-looping on the legacy-layout message, with the fix. The one-time cutover lives in `DATA_BUILD.md` step 5, which the row points to.
- [x] `engine/server/db/jobs/docs/UPDATER_WORKER.md` — **updated.** Gate tables are `video_keys` and `similarity_sources`; the reopen check names what it reads and that an older-layout file fails it.
- [x] `CONTEXT.md` — **updated.** New **Video key** entry: local to one cache file, never leaves `data/similarity_cache.py`, distinct from the ANN id and the rowid.
- [x] `docs/project/adr/0008-similarity-cache-handoff-through-files.md` — **no update.** Its "schema check" is still a schema check, now over the new tables; the handoff through files is unchanged.
- [x] `engine/server/db/jobs/docs/ORCHESTRATOR_SMOKE_TEST.md` — **no update.** "schema-only active cache" is still what the first run swaps in; re-run at close: `smoke PASS`.
- [x] Found at 9.1 and checked, **no update:** `docs/project/adr/0006-derived-ann-ids.md:22` and `docs/project/issues/08-stable-ann-ids.md:52` say the cache is keyed by `(video_id, instance_domain)`, still true at the module boundary; `docs/project/adr/0007-nsfw-filter-default-at-request-edge.md` (read-time filtering unchanged); `engine/server/api/recommendations/docs/LAYER_PARAMS.md:70` (read/write policy unchanged). `docs/wiki/` does not exist. No ADR is contradicted.

## Implementation plan

### Facts the draft rests on (observed 2025-10-01)

- SQLite is 3.53.4 under both the system and the Engine pixi Python, so the bound-variable limit is 32,766 and row-value `IN` is available.
- The live legacy cache holds no NULL `score` and 8 sources with no items; the migration must keep those 8.
- FAISS returns float32 scores in both writers (`ann.py:77`, `precompute-similar-ann.py:528`).

### What needs testing

A compact round trip through the module API; migration fidelity against a legacy file; precompute's three selection modes writing compact entries; the host purge's removal and counts; the legacy refusal at Engine start and at reopen; the updater cycle on a legacy cache; the two dropped whitelist indexes.

### Module map

| File | Change |
|---|---|
| `engine/server/data/similarity_cache.py` | Schema, codec, shape check, refusal, interning, batch write, read. `SIMILARITY_ITEM_COLUMNS` removed. |
| `engine/server/data/similarity_candidates.py` | Reopen probe → shape check. |
| `engine/server/data/moderation.py` | Purge and stats over blobs; `ensure_similarity_purge_indexes` removed. |
| `engine/server/data/videos.py` | Two `CREATE INDEX` → `DROP INDEX IF EXISTS`. |
| `engine/server/db/jobs/precompute-similar-ann.py` | Local schema/writer removed; shared imports; selection joins; batch write per FAISS batch. |
| `engine/server/db/jobs/instance-denylist-cli.py` | The `ensure_similarity_purge_indexes` call and its skip log (242-248) removed. |
| `engine/server/db/jobs/updater-worker.py` | Gate table check → shape check. |
| `engine/server/db/jobs/migrate-similarity-cache.py` | NEW. |
| `engine/server/api/server.py` | No edit: the refusal lives in `ensure_similarity_schema`, which it already calls at 339. |

The rung for the refusal is "already in this codebase": every path that opens a cache for writing (Engine start, precompute, migration output) already calls `ensure_similarity_schema`, so one guard there covers them all; the purge and the gate read the shape directly.

### `engine/server/data/similarity_cache.py`

```python
NEIGHBOUR = struct.Struct("<if")  # video_keys.key int32, score float32; rank = position + 1
MIGRATE_JOB = "migrate-similarity-cache.py"

def similarity_cache_shape(conn) -> str:
    """'legacy' when similarity_items exists; 'compact' when video_keys and similarity_sources(neighbours) exist; 'empty' when none of the three tables exists; else 'invalid'."""

def legacy_cache_message(conn) -> str:
    # path from PRAGMA database_list (main)
    return f"{path} holds the legacy similarity cache layout. Convert it with {MIGRATE_JOB} --in {path} --out <new file>, then move the new file into place."

def ensure_similarity_schema(conn) -> None:
    """Create the compact cache tables if missing; raise RuntimeError on a legacy file."""
    if similarity_cache_shape(conn) == "legacy":
        raise RuntimeError(legacy_cache_message(conn))
    # CREATE TABLE IF NOT EXISTS video_keys (key INTEGER PRIMARY KEY, video_id TEXT NOT NULL,
    #   instance_domain TEXT NOT NULL, UNIQUE (video_id, instance_domain));
    # CREATE INDEX IF NOT EXISTS video_keys_instance_domain_idx ON video_keys (instance_domain);
    # CREATE TABLE IF NOT EXISTS similarity_sources (source_key INTEGER PRIMARY KEY,
    #   computed_at INTEGER NOT NULL, neighbours BLOB NOT NULL);

def pack_neighbours(pairs: list[tuple[int, float]]) -> bytes
def unpack_neighbours(blob: bytes, limit: int | None = None) -> list[tuple[int, float]]
    # NEIGHBOUR.iter_unpack over blob[: limit * NEIGHBOUR.size]

def intern_video_keys(conn, pairs: Iterable[tuple[str, str]]) -> dict[tuple[str, str], int]
    # executemany INSERT OR IGNORE; then SELECT key, video_id, instance_domain
    # WHERE (video_id, instance_domain) IN (VALUES ...) in chunks of 450 pairs (metadata.py precedent)

def write_similarities(conn, entries: list[tuple[dict, list[dict], int]]) -> None:
    """Upsert (source, items, computed_at) entries without committing; items are written in rank order."""
    # one intern call over every source and item pair in the batch
    # INSERT INTO similarity_sources (source_key, computed_at, neighbours) VALUES (?, ?, ?)
    #   ON CONFLICT(source_key) DO UPDATE SET computed_at = excluded.computed_at, neighbours = excluded.neighbours

def store_similarity_cache(conn, source, items, computed_at) -> None:
    write_similarities(conn, [(source, items, computed_at)]); conn.commit()

def fetch_cached_similarities(conn, source, limit) -> list[dict]:
    # SELECT s.neighbours FROM similarity_sources s JOIN video_keys k ON k.key = s.source_key
    #   WHERE k.video_id = ? AND k.instance_domain = ?
    # unpack first `limit`; one SELECT key, video_id, instance_domain FROM video_keys WHERE key IN (...)
    # -> [{"video_id", "instance_domain", "score", "rank": position + 1}]; sqlite3.Error -> [] as today

def has_cached_similarities(conn, source) -> bool:
    # SELECT 1 FROM similarity_sources s JOIN video_keys k ON k.key = s.source_key WHERE ... LIMIT 1
```

Invariants: a source row exists for every written source, including one with no items (an empty blob); ranks are 1..n by position, so writers sort items by `rank` before packing; every key in a blob exists in `video_keys` (the purge removes a key only after rewriting every blob holding it).

### `engine/server/data/similarity_candidates.py`

`_refresh_similarity_handle` (283-284): replace the two table reads with `if similarity_cache_shape(new) != "compact": raise sqlite3.DatabaseError(f"similarity cache shape {shape}")`, which feeds the existing close-and-log path. A legacy file now fails with `reason=similarity cache shape legacy`.

### `engine/server/data/moderation.py`

```python
def _host_similarity_pass(conn, host, *, apply: bool) -> dict[str, int]:
    keys = {key for (key,) in conn.execute("SELECT key FROM video_keys WHERE instance_domain = ?", (host,))}
    stats = zeros
    if not keys: return stats
    for source_key, blob in conn.execute("SELECT source_key, neighbours FROM similarity_sources").fetchall():
        pairs = unpack_neighbours(blob)
        hits = sum(1 for key, _ in pairs if key in keys)
        stats["similarity_items_as_similar"] += hits
        if source_key in keys:
            stats["similarity_sources"] += 1; stats["similarity_items_as_source"] += len(pairs); stats["similarity_items"] += len(pairs)
            if apply: DELETE FROM similarity_sources WHERE source_key = ?
        elif hits:
            stats["similarity_items"] += hits
            if apply: UPDATE similarity_sources SET neighbours = ? WHERE source_key = ?  (pairs without host keys)
    if apply: DELETE FROM video_keys WHERE instance_domain = ?
    stats["similarity_items_total_mentions"] = as_source + as_similar
    return stats
```

`collect_similarity_host_stats` = `_host_similarity_pass(apply=False)`. `purge_similarity_for_host` normalises the host, checks the shape (legacy → `RuntimeError(legacy_cache_message)`), and under `with conn:` runs the pass with `apply=not dry_run`; it returns `{similarity_items, similarity_sources}` from `precomputed_counts` when given (the CLI's current contract) and from the pass otherwise. `fetchall()` before the loop because the loop updates the table it reads. rat-tail: one full scan per host with keys; a reverse index (key → sources) if purges of live hosts become frequent.

### `engine/server/data/videos.py`

Lines 23-24 and 30-31 become `DROP INDEX IF EXISTS idx_videos_id_instance;` and `DROP INDEX IF EXISTS idx_video_embeddings_id_instance;`.

### `engine/server/db/jobs/precompute-similar-ann.py`

- Remove `SIMILARITY_ITEM_COLUMNS`, `ensure_schema`, `record_similarities`; import `ensure_similarity_schema`, `write_similarities` from `data.similarity_cache` (it already imports `data.embedding_space`).
- `--reset`: `DELETE FROM similarity_sources; DELETE FROM video_keys;`.
- Selection: `JOIN out_cache.similarity_sources s JOIN out_cache.video_keys k ON k.key = s.source_key` with `k.video_id = e.video_id AND k.instance_domain = e.instance_domain`; incremental keeps its `LEFT JOIN ... WHERE k.key IS NULL` form over the same join.
- Main loop: collect `(source, ranked items, computed_at)` per source in the FAISS batch, `write_similarities` once per batch and `commit()` after it, including on a soft stop. Progress logging stays at every 500.

### `engine/server/db/jobs/updater-worker.py`

`similarity_gate_reason` (745-751): read `similarity_cache_shape` of the shadow. `legacy` → reason `legacy similarity cache layout; convert it with migrate-similarity-cache.py`; anything but `compact` → the existing `missing tables: [...]` reason over `{video_keys, similarity_sources}`.

### `engine/server/db/jobs/migrate-similarity-cache.py` (NEW)

```
usage: migrate-similarity-cache.py [--in PATH] --out PATH
  --in   legacy cache (default engine/server/db/similarity-cache.db), opened read-only
  --out  new compact cache; refused when it exists
```

1. Refuse when `--out` exists, when `--in` is missing, or when `--in`'s shape is not `legacy`.
2. Build in `<out>.tmp` (a leftover is removed first) through `ensure_similarity_schema`.
3. Load `{(video_id, instance_domain): computed_at}` from the legacy `similarity_sources`.
4. Stream `similarity_items ORDER BY source_video_id, source_instance_domain, rank` (served by `similarity_source_rank_idx`), group by source, `write_similarities` in batches of 1,000 sources with a commit per batch; then write each source left in the map with no items.
5. Verify: source count equals the legacy count, and `SUM(LENGTH(neighbours)) / 8` equals the legacy item count. A mismatch deletes `<out>.tmp` and exits non-zero.
6. `os.replace(<out>.tmp, <out>)`; log the counts and both file sizes.

### Draft check against plan and requirements

Pass 1: AC1 (two tables, blob layout, rank by position) — `similarity_cache.py`; AC2 (signatures and dicts unchanged, three modes) — read/write and precompute; AC3 (purge via `video_keys`, same keys, no-key host is one lookup, domain indexes gone) — `moderation.py` + `video_keys_instance_domain_idx`; AC4 — `videos.py`; AC5 — gate; AC6 — migration job keeps the 8 empty sources; AC7 — `ensure_similarity_schema` guard (Engine start, precompute), purge shape check, gate, reopen; AC8 — docs at Step 9. One miss found and fixed in this pass: the first draft had no index on `video_keys.instance_domain`, which AC3's "one indexed lookup" needs. Converged on pass 1.

### Draft adjustments made at Step 6

- **Reopen probe:** no shape call. The two probe reads become `SELECT source_key, neighbours FROM similarity_sources LIMIT 1` and `SELECT key FROM video_keys LIMIT 1`; a legacy file fails them with `no such column` / `no such table` and takes the existing failure path. One line changed instead of a new branch.
- **Updater gate:** no legacy branch. A legacy shadow lacks `video_keys`, so the existing `missing tables: [...]` reason over `{video_keys, similarity_sources}` already fails it; and the precompute job refuses a legacy shadow before the gate is reached.
- **Purge:** no shape check of its own. AC7 names the Engine, precompute and the updater; on a legacy file the purge fails loudly with `no such table: video_keys`.

### Phases

#### Phase 1 — Compact store and migration

- **Kind:** code
- **Files:** `engine/server/data/similarity_cache.py` EDITED; `engine/server/data/similarity_candidates.py` EDITED (reopen probe); `engine/server/db/jobs/updater-worker.py` EDITED (gate table set); `engine/server/db/jobs/migrate-similarity-cache.py` NEW.
- **Intent:** A similarity cache written through `data/similarity_cache.py` holds its entries in `video_keys` and `similarity_sources` alone and reads every one back through `fetch_cached_similarities` as the caller wrote it, and `migrate-similarity-cache.py` turns a legacy-layout file into such a cache that serves each legacy source's stored neighbours.
- **Clauses:**
  - `C1` — Entries stored with `store_similarity_cache` for several sources are returned by `fetch_cached_similarities` with the stored `video_id`, `instance_domain` and `score`, in rank order, cut at `limit`, each `rank` numbering its position (1..n), from a file whose only tables are `video_keys` and `similarity_sources`. _(Reworded at Step 7.4 with operator approval, answering claim-audit Critical 1: the approved AC1 makes rank the position, so "the stored rank" contradicted it.)_
  - `C2` — For every source in a legacy-layout file, including one with no neighbours, `fetch_cached_similarities` on the file `migrate-similarity-cache.py` writes returns the neighbours the legacy `similarity_items` rows held for it, in rank order.
- **Checkpoint and seam:** `C1` in-process at the `data.similarity_cache` module API on a temp file (precedent: `tests/active/test_similarity_candidates.py` imports `data.similarity_cache` and builds temp caches). `C2` at the job's CLI as a subprocess under `conftest.ENGINE_PY` against a hand-built legacy temp file (precedent: `tests/active/test_precompute_similar_ann.py` `_run_job`), read back in-process through the module API. Supporting: the job refuses an existing `--out` without touching it. Excluded wrong implementations: the legacy schema kept, rank off by one, `limit` ignored, neighbours from another source, empty sources dropped.
- **Shared-state step after this phase lands:** with the operator's Engine stopped and `peertube-updater.timer` paused, run the job on the real cache, `mv -n` the original to `delete_me/`, and move the new file into place, before anything starts an Engine on this code.

- **Scaffolding before the checkpoint:** `engine/server/db/jobs/migrate-similarity-cache.py` landed as its CLI signature with `main` raising `NotImplementedError`, so the job's red is absent behaviour rather than a missing file.
- **Checkpoint:** `tests/tmp/test_19_compact_similarity_cache_phase1.py`.

##### Self-check (dispatch 1)

- `C1` — `test_19_compact_similarity_cache_phase1.py:70-72,77` fetch results equal the rank-ordered literal lists, cut at `limit` 2, replaced after a re-store; `:79` the file's tables equal `{video_keys, similarity_sources}` — expected: equal — under the legacy layout kept: `{similarity_sources, similarity_items}` (observed on the current code); under packing in list order without the rank sort: `s1@a` reads back `n2` first.
- `C2` — `:117-119` fetch on the migrated file equals the legacy items per source in rank order — expected: the three literal lists — under the scaffold, or a job that copies the legacy file: no conversion (exit 1 observed; a copy has no `video_keys`, so the compact read returns `[]`). `:124` the sources joined through `video_keys` — expected: four keys including `("s3", "a.example")` — under a job that writes only sources with items: three keys, `s3@a` missing.

1. **Whole claim.** C1: several sources (two, same `video_id` on two hosts), all four fields, rank order (items handed in out of order), `limit` cut, the two-table file — each asserted. C2: every legacy source including the empty one, its legacy neighbours, rank order (legacy rows inserted out of order) — asserted at 117-119 and 124-125. Name and docstrings claim only these plus the supporting refusal and untouched input, which are asserted at 127-131.
2. **Absence only.** `:125` (`s3@a` reads `[]`) is negative; its positive control is `:124` (the row exists) and `:117-119`. The refusal at `:130` pairs with `:131` (bytes kept) and with the successful first run.
3. **Echoed literal.** The inputs pass through interning, packing and unpacking (C1) and through the job (C2); deleting the rank sort, the `limit` slice or the job's empty-source pass turns a named assertion red. The C1 expected order differs from the input order.
4. **One value.** Several sources, two hosts sharing `video_id` `s1`, a shared neighbour key (`n2@b`), two limits and a re-store.
5. **The double.** None; real module, real job, temp files.
6. **It collects.** `--collect-only -q`: 2 tests, both node ids as written.
7. **Observed, not predicted.** The round-trip lists were observed passing on the current legacy code (the first test failed only at `:79`), so the fixture and the expected dicts are right; the job's output shape is the module's own read, already observed.
8. **Red, not green.** Run: exit 1, 2 failed.
9. **Red for the right reason.** Test 1 fails at `:79`: `Extra items in the left set: 'similarity_items'`, `right set: 'video_keys'` — the compact layout does not exist yet. Test 2 fails at `:115`: `NotImplementedError: migrate-similarity-cache.py` — the conversion does not exist yet. No control assertion failed.
10. **Observed expected output.** The C1 lists match what the run showed; the C2 expectations are the legacy rows' values, which the module reads back unchanged on the current code.

##### Checkpoint audit (round 1)

- `AUDIT: devsecops-test-shape-auditor — PASS. Predicted failure: test 1 at :79 (tables {similarity_sources, similarity_items}); test 2 at :115 on returncode (NotImplementedError).` Recommendations: (1) ranks all 1..n, canonical input — answered by the gapped-rank fixture below; (2) the s3@a row read is rung 3 without a downshift comment — comment added.
- `AUDIT: devsecops-test-claim-auditor — BLOCK.` Frozen ledger (26 rows), UNCARRIED: P1C1c (stored `rank` indistinguishable from position + 1), P1C1f (cut taken from the rank-ordered list not discriminated at `limit` 2).

##### Remediation (Step 7.4)

- **P1C1c — fixed (clause reworded with operator approval).** AC1 makes rank the position; the operator approved rewording P1C1 to "each `rank` numbering its position (1..n)". The test stores s1@a with gapped ranks 5, 2, 9 handed over in that order, and the re-store with rank 4; `:70` now expects ranks 1, 2, 3, which excludes echoing the stored rank (2/5/9) and keeping the handed-over order (n2 first).
- **P1C1f — fixed.** `:73` reads `limit=1` and expects n1; cutting in handed-over order before sorting answers n2.
- Claim recommendation 1 (bounds): partly taken — `:75` reads a never-stored source and expects `[]`, with the positive reads above it as control. `limit=0`, an empty item list through `store_similarity_cache` and a shrink-to-empty re-store are deferred: the empty case is carried by the migration's s3@a, and `limit=0` returns before the cache is read (`similarity_candidates.py:58`). Recommendation 2 (abnormal paths for a missing or non-legacy `--in`): deferred to Phase 3, whose refusal clauses cover a legacy-vs-compact mismatch. Recommendation 3 (name): taken — test 2 renamed `..._and_refuses_an_existing_output`.

##### Self-check (dispatch 2)

- `C1` — `:70` s1@a at limit 10 equals n1/n2/n3 ranked 1, 2, 3 — under echoing the stored rank: ranks 2, 5, 9 (observed on the current code: `'rank': 2 != 'rank': 1` at index 0); under list order: n2 first. `:73` limit 1 equals [n1] — under cut-before-sort: [n2]. `:72` limit 2, `:74` s1@b, `:78-79` re-store replaces s1@a and leaves s1@b. `:81` tables equal `{video_keys, similarity_sources}` — under the legacy layout: `{similarity_sources, similarity_items}`.
- `C2` — unchanged rows at `:121-123` and `:129`, line numbers shifted.

Questions 2-7 walked again on the amended test: the new negative (`:75`) has the positive reads at `:70-74` as control; no echoed literal (expected ranks differ from stored ranks); several values per observable; no double; `--collect-only` 2 tests; the new expectations follow AC1 and the observed legacy output. **Still red for its own reason:** exit 1, 2 failed — test 1 at `:70` on `'rank': 2 != 'rank': 1` (positions not renumbered yet), test 2 at `:119` on `NotImplementedError`. No control failed.

##### Checkpoint audit (round 2)

- `AUDIT: devsecops-test-shape-auditor — PASS. Predicted failure: test 1 at :70 (stored ranks 2/5/9 returned where 1/2/3 expected); test 2 at :119 on returncode (NotImplementedError).`
- `AUDIT: devsecops-test-claim-auditor — BLOCK: P1C1c (stored rank indistinguishable from position) and P1C1f (cut order not discriminated). Fixed: P1C1 reworded with operator approval to "each rank numbering its position (1..n)", gapped ranks 5/2/9 stored and 1/2/3 expected at :70, limit 1 at :73. Re-audit: PASS.` Every must_prove row CARRIED. Observations, non-blocking: the clause change is recorded above; `limit=0`, an empty store and a NULL legacy score are untried; a missing or malformed `--in` is untried. The re-audit rebuilt the non-ledger row ids from the current clauses because the frozen map was passed as its UNCARRIED rows only.

##### Changes

- `engine/server/data/similarity_cache.py`: `SIMILARITY_ITEM_COLUMNS` removed. `ensure_similarity_schema` creates `video_keys` (with `video_keys_instance_domain_idx`) and `similarity_sources(source_key, computed_at, neighbours)`. New: `NEIGHBOUR` (`<if`), `KEY_CHUNK` (450), `is_legacy_similarity_cache`, `pack_neighbours`, `unpack_neighbours`, `intern_video_keys`, `write_similarities` (batch upsert, no commit, items sorted by `rank`). `fetch_cached_similarities` reads one blob, unpacks the first `limit`, resolves keys in one `IN`, numbers `rank` by position. `has_cached_similarities` keeps the legacy meaning (true only when the entry has neighbours). `store_similarity_cache` calls `write_similarities` and commits.
- `engine/server/data/similarity_candidates.py`: the reopen probe reads `similarity_sources(source_key, neighbours)` and `video_keys`.
- `engine/server/db/jobs/updater-worker.py`: `similarity_gate_reason` checks for `{video_keys, similarity_sources}`.
- `engine/server/db/jobs/migrate-similarity-cache.py`: NEW. Refuses an existing `--out`, a missing `--in`, or a non-legacy `--in`; converts into `<out>.tmp` in batches of 1,000 sources; keeps item-less sources; rejects items without a source row; verifies source and neighbour counts; `os.replace` into place; deletes the temp file on any failure.
- No file outside the phase's list was touched.

##### Checkpoint outcome

`validate_tests.py tests/tmp/test_19_compact_similarity_cache_phase1.py`: 2 passed, exit 0.

##### Shared-state cutover

Pre-checks: no Engine or updater process running (`pgrep`); 58 GB free; the live legacy cache has 0 `similarity_items` rows without a `similarity_sources` row.

- Ran `migrate-similarity-cache.py --in engine/server/db/similarity-cache.db --out engine/server/db/similarity-cache.compact.db`: `migrated sources=890052 neighbours=17787388`, in 7,881,256,960 bytes, out 341,028,864 bytes, 2 min 51 s, 305 MB peak RSS.
- `mv -n` the original to `delete_me/similarity-cache.legacy.db` (the rollback copy), then the compact file to `engine/server/db/similarity-cache.db`.
- `tests/tmp/probe_19_cutover_compare.py`: 500 random legacy sources read through `fetch_cached_similarities` on the new file equal their legacy rows exactly (ids, hosts, scores, ranks): `checked=500 mismatched=0`.

#### Phase 2 — Precompute writes the compact cache

- **Kind:** code
- **Files:** `engine/server/db/jobs/precompute-similar-ann.py` EDITED.
- **Intent:** `precompute-similar-ann.py` builds and refreshes a compact cache through the shared writer: `--refresh-existing` recomputes exactly the cached sources still embedded and `--incremental` adds exactly the uncached ones, selecting both through `video_keys`.
- **Clauses:**
  - `C1` — After `--refresh-existing`, each cached source still in `video_embeddings` reads back through `fetch_cached_similarities` with the job's fresh top-k neighbours, and each cached source no longer in `video_embeddings` reads back unchanged.
  - `C2` — After `--incremental`, each embedding not cached before reads back with its fresh top-k neighbours, and each source cached before reads back unchanged.
- **Checkpoint and seam:** the job's CLI as a subprocess, `--cpu`, against the unit-vector source fixture of `tests/active/test_precompute_similar_ann.py` (copied into `working` and adjusted, per Step 7.1), read back through the module API. The unit vectors make the expected neighbour sets derivable by hand. Excluded wrong implementations: selection still joining a text-keyed `similarity_sources`, every source recomputed, no source recomputed, a stale entry overwritten.

- **Checkpoint:** `tests/tmp/test_19_compact_similarity_cache_phase2.py`. Expected neighbours observed with `tests/tmp/probe_19_p2_neighbours.py`: the current job's legacy output over the same fixture at `--top-k 2` gives v1→v2 .8, v8 .6; v2→v1 .8, v3 .6; v4→v5 .8, v3 .6; v5→v4 .8, v6 .6; v6→v7 .8, v8 .64; v8→v7 .8, v6 .64; v3→{v4, v2} tied at .6; v7→{v8, v6} tied at .8 — the hand-computed `TOP2` and `TIED_TOP2`, within 1e-6 (float32 0.64000004).

##### Self-check (dispatch 1)

- `C1` — `test_19_compact_similarity_cache_phase2.py:116-117` v1, v2, v4 read back their `TOP2` lists — under a refresh that selects nothing, or a job still writing the text-keyed layout: the sentinel, or `[]` through the compact read. `:118, :120` gone1 and `("v5", "")` read the sentinel — under a refresh of every source, or a join on `video_id` alone: `("v5", "")` refreshed.
- `C2` — `:133-134` v2, v4, v5, v6, v8 read back `TOP2`; `:136-137` v3, v7 read their tied neighbour sets ranked 1, 2 — under an incremental that selects nothing: `[]`. `:138-139` v1 and gone1 read the sentinel — under an incremental that recomputes cached sources (selection not excluding them): v1 reads `[v2, v8]`.

1. **Whole claim.** C1: each cached embedded source (v1, v2, v4) fresh; each cached non-embedded source (gone1, `("v5", "")`) unchanged. C2: each embedding not cached before (v2-v8; v9 is dropped by the job's length check and is not an indexable embedding) fresh; each cached source (v1, gone1) unchanged. Names and docstrings claim only these, plus v9 kept and an uncached source not gaining an entry under refresh (`:121-122`).
2. **Absence only.** `:122` (`v5` reads `[]`) is negative, controlled by the positive reads at `:116-117` in the same run.
3. **Echoed literal.** Fresh neighbours come from FAISS through the job; `TOP2` is worked from `VECTORS` by hand, not by the job's code. The sentinel is an input that must come back unchanged, and the positive reads prove the run wrote: deleting the selection join turns `:116` red.
4. **One value.** Six sources with distinct expected lists, two modes, two cache shapes of seed.
5. **The double.** None; real job, real FAISS index, real module.
6. **It collects.** 2 tests.
7. **Observed, not predicted.** `TOP2`/`TIED_TOP2` matched the observed output of the current job (probe above).
8. **Red, not green.** Exit 1, 2 failed.
9. **Red for the right reason.** Both tests fail at the job's exit status (`:114`, `:131`) with `sqlite3.OperationalError: no such column: s.video_id` raised from the job's selection query: the selection still joins a text-keyed `similarity_sources`, which is the phase's own missing behaviour. The exit-status assertion is the job's outcome under the phase, not a harness control: the fixture, index and seed all built (the index child exited 0, the seed ran in-process).
10. **Observed expected output.** As in 7.

##### Checkpoint audit

- `AUDIT: devsecops-test-shape-auditor — PASS. Predicted failure: both tests at the exit-status assertion (:114, :131), sqlite3.OperationalError: no such column: s.video_id from the selection query at precompute-similar-ann.py:456-471.`
- `AUDIT: devsecops-test-claim-auditor — PASS.` Ledger: 19 rows, all CARRIED. Recommendations: (1) v9 is cached and embedded yet asserted unchanged — justified: its embedding is malformed (3 floats under dim 4), the job's query batch drops it, so it has no fresh top-k; it is not an indexable embedding, which is how the self-check reads "still in `video_embeddings`". (2) tied v3/v7 scores unasserted — taken: `:138` asserts both scores (0.6, 0.8) within 1e-6; re-run still red on `no such column: s.video_id` before implementation. (3) empty or missing `--out`, (4) the `--refresh-existing` flag conflicts — deferred: both are covered by `tests/active/test_precompute_similar_ann.py` (`test_refresh_rejects_each_destructive_flag`, `test_refresh_over_missing_or_empty_cache_is_a_no_op`), whose fixtures move to the compact layout at Step 8.

##### Changes

- `engine/server/db/jobs/precompute-similar-ann.py`: `SIMILARITY_ITEM_COLUMNS`, `ensure_schema` and `record_similarities` removed; imports `ensure_similarity_schema` and `write_similarities` from `data.similarity_cache`. `--reset` deletes from `similarity_sources` and `video_keys`. The refresh selection joins `video_keys` then `similarity_sources` on `source_key`; the incremental selection left-joins both and keeps rows with no `similarity_sources` row (a neighbour-only key counts as uncached). The main loop collects each FAISS batch's entries and writes them with one `write_similarities` and one commit per batch; a soft stop or `KeyboardInterrupt` writes what is pending before the final commit. The 500-source progress log stays; its commit moved to the batch write.
- No file outside the phase's list was touched.

##### Checkpoint outcome

`validate_tests.py tests/tmp/test_19_compact_similarity_cache_phase2.py`: 2 passed, exit 0.

#### Phase 3 — Legacy caches are refused

- **Kind:** code
- **Files:** `engine/server/data/similarity_cache.py` EDITED (`ensure_similarity_schema` guard).
- **Intent:** Every path that opens a similarity cache to serve or write it — the Engine's start and the migration output through `ensure_similarity_schema`, and the precompute job — refuses a legacy-layout file with a message naming the file and `migrate-similarity-cache.py`, and leaves the file as it was.
- **Clauses:**
  - `C1` — `ensure_similarity_schema` on a legacy-layout file raises `RuntimeError` naming the file and `migrate-similarity-cache.py`, and the file's tables are unchanged.
  - `C2` — `precompute-similar-ann.py --refresh-existing` with a legacy-layout `--out` exits non-zero with stderr naming `migrate-similarity-cache.py`, and the `--out` bytes are unchanged.
- **Checkpoint and seam:** `C1` in-process at `data.similarity_cache` (positive control: an empty file gains the compact tables). `C2` at the job's CLI as a subprocess (positive control: the same run over a compact `--out` exits 0). The Engine's start is not entered: its cache path is fixed at `DEFAULT_SIMILARITY_DB_PATH` under the repo root, so a test Engine cannot open a legacy file without overwriting the shared cache. `server.py:339` calling `ensure_similarity_schema` is what `C1` stands for, recorded here as the conceded gap. Excluded wrong implementations: the guard checking only for missing tables, the guard creating `video_keys` into the legacy file before raising, a message without the job name.

- **Checkpoint:** `tests/tmp/test_19_compact_similarity_cache_phase3.py` (imports the phase 2 `source` fixture and `_run_job` for the job's positive control).

##### Self-check (dispatch 1)

- `C1` — `:66-70` `ensure_similarity_schema` on the legacy file raises `RuntimeError` whose text names `migrate-similarity-cache.py` and the file path; `:71` the file's `sqlite_master` (type, name) set equals its set before — under the current code (no guard): no raise, and `video_keys`, `video_keys_instance_domain_idx` created in the legacy file (observed `DID NOT RAISE`); under a guard that raises after `CREATE`: `:71` differs.
- `C2` — `:87` exit non-zero, `:88` stderr names `migrate-similarity-cache.py`, `:89` `--out` bytes unchanged — under the current code: exit 1 from `no such column: s.source_key` (so `:87` alone does not discriminate), stderr without the job name (observed), and `video_keys` created in the file (bytes differ).

1. **Whole claim.** C1: raises, `RuntimeError` type, names the file, names the job, tables unchanged — each asserted. C2: non-zero exit, stderr naming the job, bytes unchanged — each asserted; the exit status is carried together with the message, since a crash also exits non-zero.
2. **Absence only.** `:71` and `:89` are "unchanged" claims; their positive controls are the raise and message (`:66-70`, `:88`) and, for the job, the compact-`--out` run exiting 0 (`:80`), which proves the job reaches its work on a valid file.
3. **Echoed literal.** The job name and path must come from production's message; deleting the guard turns `:66` red.
4. **One value.** Two shapes per seam (empty/compact vs legacy), each with its own expected outcome.
5. **The double.** None.
6. **It collects.** 2 tests.
7. **Observed, not predicted.** The positive controls were observed passing on the current code (empty file gains the two compact tables; compact `--out` exits 0).
8. **Red, not green.** Exit 1, 2 failed.
9. **Red for the right reason.** Test 1 at `:66`: `Failed: DID NOT RAISE RuntimeError` — no guard yet. Test 2 at `:88`: stderr ends in `sqlite3.OperationalError: no such column: s.source_key`, no job name — no refusal yet. Controls at `:56` and `:80` passed.
10. **Observed expected output.** As in 7 and 9.

##### Checkpoint audit (round 1)

- `AUDIT: devsecops-test-shape-auditor — PASS. Predicted failure: test 1 at :66-67 DID NOT RAISE; test 2 passes :87 (OperationalError exit) and fails at :88 (stderr without the job name).`
- `AUDIT: devsecops-test-claim-auditor — BLOCK.` Frozen ledger: 23 rows; UNCARRIED P3C1e (tables' rows and definitions unchecked: `_schema` compared only (type, name)) and D2b (docstring "left as it was" on the `ensure` path, same cause).

##### Remediation (Step 7.4)

- **P3C1e, D2b — fixed.** `:72` now compares `legacy.read_bytes()` before and after the refused call, which excludes a row write or an `ALTER TABLE` before the raise as well as an added object. The docstring now says "keeps its bytes".
- Recommendation 2 (legacy edge inputs: empty legacy tables, a file holding only `similarity_items`) — deferred: `is_legacy_similarity_cache` keys on the `similarity_items` table alone, so row count does not enter the decision; recorded for the Step 8 review.

##### Self-check (dispatch 2)

- `C1` — `:66` raises, `:69-70` names the job and the path, `:72` bytes unchanged — under no guard: no raise (observed); under a guard after `CREATE`: bytes differ.
- `C2` — unchanged rows at `:88-90` (line numbers +1).

Questions 2-7 walked again: the new bytes check is an "unchanged" claim controlled by the raise at `:66` and the empty-file control at `:60`; no echoed literal; no double; collects 2. **Still red for its own reason:** test 1 at `:66` `DID NOT RAISE RuntimeError`; test 2 at `:89` stderr ends in `no such column: s.source_key` without the job name.

##### Checkpoint audit (round 2)

- `AUDIT: devsecops-test-shape-auditor — PASS. Predicted failure: test 1 at :66 DID NOT RAISE; test 2 at :89, stderr a sqlite error without migrate-similarity-cache.py.`
- `AUDIT: devsecops-test-claim-auditor — BLOCK: P3C1e/D2b, tables compared by (type, name) only. Fixed: :72 compares the file's bytes before and after. Re-audit: PASS.` All 23 rows CARRIED. Observation, non-blocking: legacy edge inputs (no rows; only `similarity_items`; legacy and compact tables together) untried, carried to the Step 8 review.

##### Changes

- `engine/server/data/similarity_cache.py`: `ensure_similarity_schema` checks `is_legacy_similarity_cache` first and raises `RuntimeError` naming the file (from `pragma_database_list`) and `migrate-similarity-cache.py --in <path> --out <new file>`, before any DDL. The Engine's start (`server.py:339`), the precompute job (`--out`, `--reset-only`) and the migration's output all reach it.
- No file outside the phase's list was touched.

##### Checkpoint outcome

`validate_tests.py tests/tmp/test_19_compact_similarity_cache_phase3.py`: 2 passed, exit 0. Phase 1's checkpoint re-run after the guard: 2 passed.

#### Phase 4 — Redundant indexes go

- **Kind:** code
- **Files:** `engine/server/data/moderation.py` EDITED; `engine/server/db/jobs/instance-denylist-cli.py` EDITED; `engine/server/data/videos.py` EDITED.
- **Intent:** The disk spent on redundant indexes is gone: the host purge removes a host from a compact cache without any per-domain similarity index, and `ensure_video_indexes` leaves `whitelist.db` without the two indexes that duplicate the `(video_id, instance_domain)` primary keys.
- **Clauses:**
  - `C1` — `purge_similarity_for_host` deletes the host's sources, removes the host's videos from every other source's neighbours while keeping the rest in rank order, and returns the counts the legacy purge returned for the same content.
  - `C2` — After `ensure_video_indexes`, a database that held `idx_videos_id_instance` and `idx_video_embeddings_id_instance` holds neither, and still holds `idx_videos_uuid_instance`.
- **Checkpoint and seam:** `C1` in-process at `data.moderation` on a compact temp cache built through the module API, read back through `fetch_cached_similarities`; the expected counts are the literals the legacy purge returns for the same hand-built content, worked out by hand in the test (a host appearing as source, as neighbour, and as both). Supporting: a host with no keys returns zeros and leaves every entry. `C2` in-process at `data.videos` on a temp DB carrying the old indexes, read through `sqlite_master` (precedent: `tests/active/test_db.py`). Excluded wrong implementations: only sources deleted, neighbour rewrite dropping non-host entries or reordering, overlap counted twice, indexes left, the uuid index dropped.

- **Checkpoint:** `tests/tmp/test_19_compact_similarity_cache_phase4.py`. Expected counts observed with `tests/tmp/probe_19_p4_legacy_counts.py` on the same content in the legacy layout under the current (legacy) purge: stats `{similarity_items: 4, similarity_sources: 2, as_source: 2, as_similar: 3, total_mentions: 5}`, purge `{similarity_items: 4, similarity_sources: 2}`, a keyless host `{0, 0}`, and the surviving rows s1→n1, n2 and s2→n1.

##### Self-check (dispatch 1)

- `C1` — `:59` purge returns `{similarity_items: 4, similarity_sources: 2}` — under counting the overlap twice (b1→x1): 5; under counting only sources' items: 2. `:60` s1 reads n1, n2 ranked 1, 2 — under deleting only sources: x1, n1, x2, n2; under a rewrite that drops non-host entries or reorders: different list. `:61` s2 unchanged — under a rewrite of every blob that loses entries: differs. `:62` sources are s1, s2 — under no source delete: b1, b2 still present.
- `C2` — `:105` index set equals `{idx_videos_uuid_instance}` for a DB carrying the duplicates and for a fresh one — under the current code: both duplicates present (observed); under dropping every `idx_` index: uuid index missing.

1. **Whole claim.** C1: host sources deleted (`:62`), host videos removed from other sources (`:60`), rest kept in rank order (`:60-61`), legacy counts (`:59`). C2: neither duplicate, uuid kept, on a DB that held them (`:105`, `old.db`). The fresh-DB pass and the stats/keyless checks are supporting.
2. **Absence only.** "Neither duplicate" is carried by exact set equality that also requires the uuid index present. The keyless-host zeros (`:72`) are paired with the reads at `:73-74` showing the content is still there.
3. **Echoed literal.** Counts are the legacy purge's observed output, not recomputed; the surviving lists come from the production purge through the production read.
4. **One value.** Two hosts purged (bad, keyless), sources as host, as neighbour and both; two DB shapes for C2.
5. **The double.** None.
6. **It collects.** 2 tests.
7. **Observed, not predicted.** Counts and survivors observed from the legacy purge (probe above); rank renumbering follows the approved P1C1.
8. **Red, not green.** Exit 1, 2 failed.
9. **Red for the right reason.** Test 1 at `:59`, inside `purge_similarity_for_host` → `collect_similarity_host_stats` (`moderation.py:318`): `sqlite3.OperationalError: no such column: instance_domain` — the purge does not know the compact layout. The first draft's keyless-host control ran first and failed the same way; it was moved after the clause assertions onto a second copy so the red lands on the clause. Test 2 at `:105`: `Extra items in the left set: 'idx_videos_id_instance', 'idx_video_embeddings_id_instance'`.
10. **Observed expected output.** As in 7.

##### Checkpoint audit (round 1)

- `AUDIT: devsecops-test-shape-auditor — PASS. Predicted failure: test 1 at :59 (OperationalError no such column: instance_domain inside the purge's stats pass); test 2 at :105 on old.db (both duplicates present).` Recommendation: the `video_keys` count read is rung 3 without a comment — comment added.
- `AUDIT: devsecops-test-claim-auditor — BLOCK.` Frozen ledger: 27 rows; UNCARRIED P4C1c ("from every other source's neighbours": only s1 held host neighbours) and D2 (docstring "without per-domain indexes" unasserted).

##### Remediation (Step 7.4)

- **P4C1c — fixed.** The fixture gains s3@a (host video last, after an a.example one) and s4@a (only a host video). `:65` s3 reads [n1] and `:66` s4 reads [] after the purge, so a purge rewriting only the first affected source fails. Counts re-observed with the probe on the new content (legacy purge): purge `{similarity_items: 6, similarity_sources: 2}`, stats as_source 2, as_similar 5, total 7; survivors s1→n1, n2; s2→n1; s3→n1; s4 kept with no items. `:63` and `:79` updated to those.
- **D2 — fixed.** `:72` asserts the file's non-auto indexes after the purge equal `{video_keys_instance_domain_idx}`.
- Recommendations taken: 2 (`:86-87` an empty host raises `ValueError`); 3 (last-position and all-host removal, via s3 and s4); 4 (`:82-83` b1 and s2 read back unchanged after the keyless purge).

##### Self-check (dispatch 2)

- `C1` — `:63` counts 6/2 — under the overlap counted twice: 7; under source items only: 2. `:64-67` s1 [n1, n2], s3 [n1], s4 [], s2 unchanged — under rewriting only the first affected source: s3 still holds x1. `:68` sources s1-s4 — under no source delete: b1, b2 present; under deleting a source left empty: s4 missing (legacy kept it).
- `C2` — unchanged at `:118`.

Questions 2-7 walked again: new negatives (`:66` s4 `[]`, `:70` no bad keys) sit beside positive reads in the same run; counts are the legacy purge's observed output; several sources and hosts; no double; collects 2. **Still red for its own reason:** test 1 at `:63` with `sqlite3.OperationalError: no such column: instance_domain` raised in the purge; test 2 at `:118`, `Extra items: idx_videos_id_instance, idx_video_embeddings_id_instance`.

##### Checkpoint audit (round 2)

- `AUDIT: devsecops-test-shape-auditor — PASS. Predicted failure: test 1 at :63 (OperationalError no such column: instance_domain from collect_similarity_host_stats); test 2 at :118 on old.db.` Recommendation: `_source_keys` compared `sqlite3.Row` objects (from `connect_similarity_db`) against tuples and sorted them, which raises on a correct implementation — fixed: rows are converted to tuples.
- `AUDIT: devsecops-test-claim-auditor — BLOCK: P4C1c (only one surviving source held host neighbours), D2 (no index assertion after the purge). Fixed: s3/s4 added with re-observed legacy counts 6/2 and 2/5/7; index set asserted at :72. Re-audit: PASS.` Observation taken: the module docstring now says "without adding per-domain indexes".

##### Changes

- `engine/server/data/moderation.py`: imports `pack_neighbours`, `unpack_neighbours`. New `_host_similarity_pass(conn, host, apply)`: resolves the host's keys from `video_keys` (none → zeros, no scan); otherwise one scan of `similarity_sources` that counts as the legacy purge did, deletes host sources, rewrites other sources' blobs without host keys, and deletes the host's `video_keys` rows. `purge_similarity_for_host` runs it under `with conn:` with `apply=not dry_run` and returns `precomputed_counts` when given, else the pass's two counts. `collect_similarity_host_stats` returns the pass with `apply=False`. `ensure_similarity_purge_indexes` removed.
- `engine/server/db/jobs/instance-denylist-cli.py`: the `ensure_similarity_purge_indexes` import, call and its `similarity-indexes-skip` log removed.
- `engine/server/data/videos.py`: `ensure_video_indexes` keeps `CREATE INDEX IF NOT EXISTS idx_videos_uuid_instance` and drops `idx_videos_id_instance` and `idx_video_embeddings_id_instance`; docstring updated.
- **Inventory gap:** `engine/server/db/jobs/ensure-video-indexes.py` (not in Step 3's inventory) runs `ensure_video_indexes` on a chosen DB, so it now also drops the two duplicates there. No code change; its description "Create video/embedding indexes used by seed lookups" stays true of the uuid index.

##### Checkpoint outcome

`validate_tests.py tests/tmp/test_19_compact_similarity_cache_phase4.py`: 2 passed, exit 0.

#### Coordination needed from the operator

- **No timer to pause.** `systemctl list-timers --all` lists no `peertube-updater.timer` and `systemctl list-unit-files 'peertube*'` lists no units (checked 2026-10-01 13:55). The 2026-10-01 updater run in `engine/server/db/updater-worker.log` used a temporary `systemctl` at `/tmp/tmp.UjihdvEEDa/systemctl`, so it was started by hand or by a script. The operator does not start the updater until the build closes.
- **After Phase 1 lands:** stop the long-running Engine, approve the real-cache migration and the `mv -n` of the 7.3 GB original to `delete_me/`, then restart the Engine on the new code.
- **Fixture churn (R5, accepted at Step 2):** the active tests that build legacy caches by hand (`test_precompute_similar_ann.py`, `test_similar.py` `_cache_entry`, `test_similarity_candidates.py`, `test_updater_worker.py`) and `engine/server/db/jobs/tests/test-moderation-integration.py` change their fixtures at Step 8 to build compact caches through the module API. Their assertions are not weakened.

#### Approval

Operator approved the four phases on 2026-10-01 ("proceed") and stopped the long-running Engine; it stays off until the cutover after Phase 1.

#### Rationale for the split

Four phases at two clauses each carry the eight observable facts. Phase 1 comes first because the shared-state cutover needs the migration job and the compact read/write path together. The precompute writer (Phase 2) lands before the refusal (Phase 3) because its refusal comes from calling the shared `ensure_similarity_schema`, which only happens once its local `ensure_schema` is gone. Phase 4 groups O2 and O4: both delete redundant indexes, and neither depends on the others' order.

## Inner unit tests

None. Every behaviour was expressible at its phase's checkpoint.

## Close

### Refactors

None made. The refactor pass looked for code the build left dead or duplicated: `SIMILARITY_ITEM_COLUMNS`, `ensure_schema`, `record_similarities` and `ensure_similarity_purge_indexes` are gone with no remaining caller; `moderation._table_exists` is still used by six callers. Left as is: `has_cached_similarities` and `fetch_cached_similarities` each carry the same two-table join, one line each, below the rule-of-three line. Nothing needed new behaviour.

### Fixture changes (R5, accepted at Step 2)

Assertions unchanged in strength; only how the tests build and read caches moved to the compact layout:
- `tests/active/test_similarity_candidates.py`: seeding through `store_similarity_cache`; `_committed` and `_sources` read through `video_keys` and `fetch_cached_similarities`; the marker scores moved from 0.9/0.8 to 0.875/0.75 (exact in float32, the stored precision); one docstring sentence reworded off the table names. 17 passed.
- `tests/active/test_updater_worker.py`: `_cache`, `_add_source`, `_delete_source`, `_rows` and the reprune seed use the module; the fake Engine-side purge of the active file calls `purge_similarity_for_host` instead of raw `DELETE`s on legacy tables. 54 passed.
- `tests/active/test_precompute_similar_ann.py`: `_seed_cache` and `_snapshot` use the module; the empty-cache test asserts `{video_keys, similarity_sources}` and an empty `video_keys` in place of an empty `similarity_items`. 11 passed.
- `tests/active/test_similar.py`: `_cache_entry` reads the seed's source row through `video_keys` and its neighbours through `fetch_cached_similarities`, read-only on the shared cache; the module docstring sentence follows.
- `engine/server/db/jobs/tests/test-moderation-integration.py` (standalone): its local legacy schema is replaced by the module's; the seed goes through `write_similarities`; the step-4 dangling check counts the purged hosts' `video_keys` rows plus blob keys with no `video_keys` row. Run: `Moderation integration test: PASS`.

### Clause accounting

- P1C1 — carried (Phase 1, round-2 claim audit, clause reworded with operator approval).
- P1C2 — carried (Phase 1).
- P2C1 — carried (Phase 2).
- P2C2 — carried (Phase 2).
- P3C1 — carried (Phase 3, round 2).
- P3C2 — carried (Phase 3).
- P4C1 — carried (Phase 4, round 2).
- P4C2 — carried (Phase 4).

### Suite

- First `validate_tests.py --compare` after the fixture changes: 125 passed, 2 failed, both new red `test_similar::test_a_listing_request_without_exactly_nsfw_1_gets_no_flagged_row_where_nsfw_1_gets_some[random=1-0]` and `[random=1-empty]`, at `test_similar.py:1236`, the test's own control: "random=1 with nsfw=1 served no flagged row in 12 draws".
- **Diagnosis, test first.** The control is probabilistic: 12 draws of 96 rows from the random cache, which the test's own comment puts at 0.6% flagged and "none about once in a thousand runs". `tests/tmp/probe_19_random_cache_nsfw.py` measured the served `random-cache.db` at 2,966 of 490,348 rows flagged (0.6049%), as the test assumes. The `random=1` path reads the random cache and `whitelist.db`; this build changed neither table's content (the dropped indexes duplicate primary keys the joins still use). Re-run: `test_similar.py` 92 passed, both cases included. Recorded as an intermittent control, not a regression; no checkpoint gap.
- Final `validate_tests.py --compare`: exit 0, every group green against the record, `nothing moved against the previous record`. Baseline was green, so the plain criterion holds.
- Standalone job tests: `engine/server/db/jobs/tests/test-moderation-integration.py` PASS; `engine/server/db/jobs/tests/test-orchestrator-smoke.py --cpu` `smoke PASS` (its forced gate-failure scenario logs the expected `Similarity gate failed: forced by --fail-similarity-gate`).

### Harvest (Step 10)

Run per `workflows/harvest.md`; record in `docs/project/plans/harvest-19-compact-similarity-cache-plan.md`. 7 tests moved into `tests/active` (4 new subject files, 2 into `test_precompute_similar_ann.py`), 1 REDUNDANT, none retired; each moved assertion felled by a recorded mutation and green after restore; `--audit-map` exit 0; `--compare` against the pre-harvest record shows exactly 7 appeared and nothing else. This build's working files are in `delete_me/`.

### Operator follow-ups

- `delete_me/` holds `similarity-cache.legacy.db` (7.9 GB, the pre-migration cache, the only rollback copy), `real.db` (3.4 GB), and this build's checkpoints, probes and mutation copies.
- The long-running Engine was stopped before the cutover and needs starting on the new code.
- The updater refreshes at `--top-k 1000`; the first such refresh takes the cache from 0.34 GB to an estimated ~7 GB (shadow plus active plus `.prev.db` during the swap). `scripts/run-dataset-build.sh` still builds at `--top-k 20`; that mismatch predates this build.
- Optional: `sqlite3 engine/server/db/whitelist.db "VACUUM;"` with the Engine stopped, after its first start on this code has dropped the two duplicate indexes (about 134 MB).
- `test_search_fusion.py` has no `test_groups` entry (pre-existing).
