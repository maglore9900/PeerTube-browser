# Open issues: priorities and parallel waves

Written 2026-09-27, after plans 14 and 15 were delivered. It covers every open issue in this
directory (08-33) and one new issue this plan proposes (34). The format follows the
security-hardening batch (`.scratch/security-hardening-batch/notes.md`): waves run one after
another, and the lanes inside a wave run in parallel worktrees.

## Before wave 1 (on main, no worktrees)

1. **Triage.** Every open issue is `needs-triage`. A build needs a `ready-for-agent` brief, so
   triage the issues of the next wave before it starts, not all 25 up front. Triage decisions
   this plan already recommends are in "Triage recommendations" below.
2. **File issue 34** (below): wrong `videos.channel_name` on most of the dataset.
3. **Housekeeping.** Issue 15 exists twice. `issues/15-remove-single-like.md` is `complete` but
   was never moved, and `issues/archive/15-remove-single-like.md` is an older `needs-triage`
   copy. Keep the complete one in `archive/` and delete the other.
4. **Write the wave's plan files on main before any worktree branches**, so plan numbers cannot
   collide. The next plan number is 17.

## Proposed new issue 34: `videos.channel_name` is another instance's channel name

Measured this session on `whitelist.db`: 851,810 of 890,052 videos have a `channel_name` that
does not match their own `channel_url`. The stored name belongs to the channel with the same
numeric `channel_id` on a different instance. For example, tube.sasek.tv channel 13 is stored
as "Tour de France des Familles", but its URL is `/video-channels/hochzeiten`. The `channels`
table joined on `(channel_id, instance_domain)` holds the correct names.

- **Search:** `videos_fts` indexes `videos.channel_name`, so a channel-name query matches the
  wrong channel's videos.
- **Cards:** the `channel_name` fallback in `video-card.ts:142` builds wrong channel links.
  Cards show `channel_display_name` from the `channels` join, so the visible label is correct.
- **Probable source:** the crawler's video writer (`engine/crawler/src/videos-worker.ts`, where
  `channelName` is resolved, and the `db.ts` upsert). This is not yet traced.
- **Repair:** fix the writer, then correct existing rows from `channels` and rebuild
  `videos_fts`. That is a data migration against the shared `whitelist.db`, so it runs on main
  after the merge, never from a worktree (see "Rules").

## Priorities

| Tier | Issues | Why this tier |
|---|---|---|
| P3: feed | 16, 17 | 16 is small. 17 is a user-facing mode switch that needs 16 first. |
| P4: runtime reliability | 22+23, 25, 24, 26 | Restarts and updater runs currently cause downtime. 26 is the goal, and the others are its prerequisites. |
| P5: observability | 19, 20, 21, 18 | 19 and part of 20 are already delivered (see triage). None of these block other work. |
| P6: structural | 08 | Stable ANN ids. No visible symptom today, but it touches nearly every Engine data file and job, so it runs in a wave of its own. |
| P7: crawler | 27 | A standalone feature in `engine/crawler`. |
| P8: docs | 29, 30, 28 | 29 and 30 go last, because earlier work would rewrite them. 28 should not be built (see triage). |

## Waves

Each lane is one issue, one plan file and one worktree. The files listed are those the lane is
expected to touch; each plan's impact inventory confirms them.

### Wave 1: bugs and a quick win (4 lanes)

| Lane | Issue | Main files | Notes |
|---|---|---|---|
| 1a | 32 concurrent start lock | `engine/server/data/random_cache.py`, `engine/server/api/server.py`, the `ENGINE_START_LOCK` comment in `tests/active/conftest.py`, new tests in `tests/active/test_random_cache.py` | Delivered. |
| 1b | 33 metadata threshold | `engine/server/data/metadata.py`, `tests/active/test_metadata.py` | Similar and up-next lists get shorter. 09 measures pool sizes after this change. |
| 1c | 34 channel_name | `engine/crawler/src/videos-worker.ts`, `db.ts`, a repair job | The repair runs on main after the merge. |
| 1d | 14 collapsible description | `client/frontend/src/pages/video-page/index.ts`, `video.css`, `video-page.html` | Delivered. |

No two lanes share a file.

### Wave 2: similars, video metadata, popular, random cache (4 lanes)

| Lane | Issue | Main files | Depends on |
|---|---|---|---|
| 2a | 09 similars diversity | `api/handlers/similar.py`, `data/similarity_candidates.py`, `data/ann.py`, `api/server.py`, `recommendations/related_personalization.py`, `server_config.py` | 33. Delivered. The durable up-next tests that assumed a repeatable page were retired to `tests/archive/upnext_random_draw/`, not rewritten; issue 35 tracks their replacement. |
| 2b | 10 metadata completeness | `api/handlers/video.py`, video page metadata block | 14 (same page) |
| 2c | 16 popular weighted random | `api/recommendations/candidates/popular_videos.py`, `server_config.py` | none. Delivered. |
| 2d | 22+23 random cache refresh, one build | `data/random_cache.py`, `api/server.py` startup, `server_config.py` | 32 (same file; delivered). 32 left two things this lane reworks: the `reuse_non_empty` keyword on `populate_random_cache`, which the Engine start passes as `True`, and the 3600 s busy wait (`RANDOM_CACHE_BUSY_TIMEOUT_SECONDS`) in `connect_random_cache_db`. |

Three lanes add constants to `server_config.py`, in separate sections. Expect small merge
conflicts there and nowhere else.

### Wave 3: video page load, feed modes, precompute, crawler (4 lanes)

| Lane | Issue | Main files | Depends on |
|---|---|---|---|
| 3a | 11 fast similars response | video page load flow, `api/handlers/video.py` | 09, 10 |
| 3b | 17 feed modes | `api/handlers/similar.py`, `data/random_videos.py`, `client/frontend/src/data/feed-params.ts`, `client/frontend/src/data/videos.ts`, `pages/videos/index.ts`, `index.html`, `videos.html`, `videos.css` | 16. Delivered. The gateway allowlist already carried `mode`, and the recommendations builder is untouched. |
| 3c | 25 precompute existing sources | `db/jobs/precompute-similar-ann.py`, `db/jobs/updater-worker.py` | none |
| 3d | 27 crawler seed-instance mode | `engine/crawler/src/*` | 34 (same code) |

### Wave 4: similars on scroll, shadow swap, logging (3 lanes)

| Lane | Issue | Main files | Depends on |
|---|---|---|---|
| 4a | 12 similars on scroll | video page similar section, the `?id=` mode of `pages/videos/index.ts`, similar route limit | 11, 17 (both touch these files) |
| 4b | 24 similarity shadow swap | `updater-worker.py`, `precompute-similar-ann.py`, `data/similarity_cache_manager.py` | 25, 23 |
| 4c | 20 request lifecycle logs (with what is left of 19) | `api/request_context.py`, `api/logging_profiles.py`, the Client's logging in `client/backend/server.py` | Runs after the handler-heavy lanes, because it touches every handler lightly. |

### Wave 5: stable ANN ids, plus lanes that touch no Engine data (3 lanes)

| Lane | Issue | Main files | Depends on |
|---|---|---|---|
| 5a | 08 stable ANN ids | `data/{ann,embeddings,metadata,search}.py`, `handlers/similar.py`, all index and precompute jobs | 09, 24, 25 (all touch these files). `data/ann.py` also holds `search_similar_above` (09's up-next fallback, a rowid reader) and the Engine's nprobe helpers (`_extract_ivf`, `get_nprobe`, `apply_nprobe`, `set_nprobe`); 08 migrates them with the rest of the file. |
| 5b | 13 comments | video page, below the description | 11, 12 (same page). Delivered. |
| 5c | 21 + 18 static-page logs and About click tracking | nginx docs, the About template, one Client endpoint | 20 |

The `ann_id` backfill is a migration of the shared `whitelist.db`. It runs on main after the
merge, then the ANN index is rebuilt.

### Wave 6: deploy and docs (2 lanes, then 30 alone)

| Lane | Issue | Depends on |
|---|---|---|
| 6a | 26 zero-downtime deploy | 23, 24, 20 |
| 6b | 29 recommendations overview doc | 09, 16, 17 |
| after | 30 docstrings | everything else |

## Triage recommendations

- **19 is mostly delivered.** Both services already log `"ts"` as ISO-8601 with milliseconds
  (`engine/server/api/logging_profiles.py:195`, `client/backend/server.py:122`). The one
  difference is that it uses a local offset, not UTC. Close 19, or shrink it to "UTC, plus an
  optional plain-text mode", and fold that into 20.
- **20 is partly delivered.** The Engine already has a per-request `request_id` and
  `access.start` / `access` events (`api/request_context.py`). The Client has neither, and
  nothing reads or forwards `X-Request-ID`. Rescope 20 to those gaps.
- **22 and 23 describe one mechanism**: rebuild into a temporary file, then swap. Build them as one
  plan. 32 may become moot after that, but it is a small fix that unblocks parallel testing now,
  so do it first anyway.
- **13's stated dependency was unnecessary (resolved).** The issue waits for a "comments enrichment" dataset stage. That stage exists (`npm run crawl:videos:comments` in `engine/crawler`), but it stores only `videos.comments_count`, not comment content. The video page reads comment threads from the source instance at view time instead, so 13 did not need it. See `docs/project/plans/archive/19-13-video-comments.md`.
- **24/25 ordering:** do 25 first, as its overlap notes say, so the precompute stage is
  rewritten once.
- **08 vs 09:** issue 09 says it should follow 08. This plan reverses that. 09 only changes how
  candidates are sampled, not their ids, and 08 conflicts with nearly everything, so it runs
  late and alone.
- **28 (Tailwind): wontfix**, or move it to the roadmap under F5-M2 to F7-M2 as the issue
  itself suggests. It is an evaluation with no defect behind it.
- **17** must extend the delivered feed parameter panel (`plans/archive/04-feed-parameter-panel.md`),
  not add a second parameter mechanism.

## Rules carried over from the last batch

- **Branching:** worktrees go under `.worktrees/`, created with `scripts/worktree-setup.sh
  <branch>`, run from the main checkout. That script refuses to run while main
  tracks the `.pixi` or `node_modules` symlinks. Last time a committed symlink deleted main's
  real `node_modules`.
- **Harvest:** harvest runs on main after each merge, one at a time, never in a worktree.
- **Shared data:** `whitelist.db` and `similarity-cache.db` are symlinked, so every worktree and
  main share them. A build's tests must write only temporary copies. Real data migrations (34's
  repair, 08's backfill, a 24/25 cutover) run on main after the merge.
- **Merge conflicts:** `tests/last_test_validation.json` and `tests/last_test_output.txt` conflict
  on every merge. Take main's copy, then re-run `--compare` on the merged tree.
- **Lane count:** last time ran 3 lanes. This plan uses up to 4, and each lane starts its own
  Engine for tests. The machine has 12 cores and about 20G of free RAM, but one Engine's memory
  was not measured. Run wave 1 and watch memory before settling on 4. If memory is tight, run 1d
  (frontend only) after the others.
