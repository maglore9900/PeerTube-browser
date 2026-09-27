# `videos.channel_name` holds another instance's channel name

Status: bug, complete

Origin: `docs/project/issues/plan.md`, "Proposed new issue 34", measured on `whitelist.db` during the session that wrote that plan (2026-09-27)

## Problem

Most rows in `videos` carry a `channel_name` that belongs to a different channel. The stored name is the name of the channel that has the same numeric `channel_id` on a different instance. The `channels` table, joined on `(channel_id, instance_domain)`, holds the correct names.

## Observed

- On `whitelist.db`, 851,810 of 890,052 videos have a `channel_name` that does not match their own `channel_url`.
- Example: tube.sasek.tv channel 13 is stored as "Tour de France des Familles", but its URL is `/video-channels/hochzeiten`.
- Not re-measured when this issue was filed. The figures come from the plan session.

## Impact

- **Search:** `videos_fts` indexes `videos.channel_name` (triggers at `engine/server/db/jobs/sync-whitelist.py:272-283`). A query for a channel's name therefore matches another channel's videos.
- **Cards:** none in practice. The `channel_name` fallback at `client/frontend/src/components/video-card.ts:142` builds a link only when `channel_url` is empty, which no row is. The visible label comes from `channel_display_name` via the `channels` join. See the triage below.

## Probable source (not traced)

- The crawler's video writer. `engine/crawler/src/videos-worker.ts:660-662` resolves `channelName` from the crawl job's `channel.displayName` first, then from the video's own `channel.displayName`. The row is written by the upsert in `engine/crawler/src/db.ts` (around `:770-779`).
- Nobody has confirmed which step pairs a `channel_id` with the wrong instance: the crawler writer, the crawl job's channel lookup, or `sync-whitelist.py` copying rows into `whitelist.db`.

## Repair (candidate, not chosen)

- Fix the writer so that new rows get their own channel's name.
- Correct existing rows from `channels` on `(channel_id, instance_domain)`, then rebuild `videos_fts`.
- That repair is a data migration against the shared `whitelist.db`. It runs on main after the merge, never from a worktree (see "Rules" in `plan.md`).

## Related

- `plan.md` puts this issue in tier P1 and wave 1, lane 1c.
- Issue 27 (`27-crawler-seed-instance-mode.md`) touches the same crawler code. `plan.md` puts it in lane 3d, after this issue.

## Comments

### Triage

**Established:**

- **Re-measured on `whitelist.db` (read-only).** Every video joins its own channel on `(channel_id, instance_domain)`. For 659,750 of 890,052 videos, `videos.channel_name` matches neither that channel's `display_name` nor its handle. 657,476 of those (over 99.6%) carry the `display_name` of the channel with the same `channel_id` on another instance. The issue's example checks out: tube.sasek.tv channel 13 holds "Tour de France des Familles", the name of `www.komitid.tv` channel 13. Its own name is "Hochzeiten / Familie Sasek". 49,200 `channel_id` values occur on more than one instance.
- **The crawl DB has the same fault.** In `engine/crawler/data/crawl.db`, 661,306 of 891,621 videos mismatch. `sync-whitelist.py` reloads `whitelist.db` from it, so a repair of `whitelist.db` alone would be undone by the next sync. The updater's merge rule for `videos` is `INSERT_ONLY`, so it never corrects existing prod rows.
- **Root cause: the crawler's video worker.** It builds its channel-metadata map keyed by `channel_id` alone across every host, and looks channels up by `channel_id` alone. When an id repeats across instances, the last host listed wins. The video row then takes that entry's `displayName` as `channel_name`. Only two values read that map entry: `displayName`, which comes first for `channel_name`, and `channelUrl`, which is used only when the video payload has no `channel.url`. The crawl slug comes from the per-host progress row before the map, so it was always right. The row's `channel_url` comes from the video's own `channel.url` first. This matches the data: `channel_url` is never empty.
- **Impact, corrected:**
  - **Search:** `videos_fts` indexes `channel_name`, so a channel-name query matches another channel's videos. This is real.
  - **Embeddings (not in the original issue):** `build-video-embeddings.py` appends `channel: <channel_name>` to each video's embedding text. About 74% of vectors carry another channel's name, which pulls unrelated videos together in similar, up-next and vector search.
  - **Cards: effectively none.** The `channel_name` fallback in `video-card.ts` only builds a link when `channel_url` is empty (0 rows). The Engine's `/api/video` prefers `channel_display_name`, and rewrites `channel_name` correctly for any video that is viewed.
- **Maintainer decision on scope:** fix the writer, repair both databases, and rebuild `videos_fts`. Re-embedding is a separate operator step (below). Removing `channel_name` from the embedding text is not part of this issue.

### Follow-up operator step (not the agent's)

After the repair has run on main, the embeddings still carry the wrong channel names until an operator runs `build-video-embeddings.py --force` on `whitelist.db`, then `build-ann-index.py` and `precompute-similar-ann.py`. Plan 17 (stable ANN ids, issue `08-stable-ann-ids.md`) also migrates `video_embeddings` and rebuilds the index. Schedule the re-embed with plan 17's cutover so the index is rebuilt once.

### Delivered

Delivered by the build plan `docs/project/plans/01-34-video-channel-name-wrong-instance.md`.

- **Writer.** `crawlVideos` in `engine/crawler/src/videos-worker.ts` keys its channel-metadata map with `channelMetaKey(host, channelId)`, which returns `host/channelId`. The map is built from `channels.instance_domain` lowercased, and `processInstance` looks it up with its already-lowercased `normalizedHost`. The same change is in the committed `engine/crawler/dist/videos-worker.js`.
- **Repair.** `engine/server/db/jobs/repair-video-channel-names.py --db PATH` corrects existing rows in `crawl.db` or `whitelist.db` and rebuilds `videos_fts` where it exists. Its behaviour and the run order are in `DATA_BUILD.md`, section "Repair video channel names (one-time migration)".
- **Tests.** The gating checkpoints are `tests/tmp/test_34_video_channel_name_wrong_instance_phase1.py` to `phase4.py`. Their durable home is `tests/active/test_channel_names.py`, which the harvest creates.

**Still owed on main:**
- The dist was edited by hand, without `npm run build`. Before or at merge, run `cd engine/crawler && npm run build` and confirm the dist diff. Production crawls run the dist, not the source.
- The operator runs the repair on `engine/crawler/data/crawl.db` and on every `whitelist.db` copy, prod included, then the re-embed, ANN rebuild and similarity precompute above. The steps are in `DATA_BUILD.md`.
- Nobody has run the active suite against the finished build yet, so that acceptance criterion stays open.


## Agent Brief

**Category:** bug
**Summary:** The crawler must store each video's own channel name, and existing rows in the crawl DB and the whitelist DB must be corrected, with the search index rebuilt to match.

**Current behavior:**
The video crawl builds a map of channel metadata (slug, display name, URL) keyed by `channel_id` only, from every channel on every crawled host, and looks each channel up by `channel_id` only. PeerTube channel ids are small per-instance integers, and 49,200 of them repeat across instances. So a video's row usually receives the display name of whichever same-id channel on another host was listed last, and that value is written to `videos.channel_name`. About 74% of video rows in both `crawl.db` and `whitelist.db` are wrong, while the `channels` table holds the correct `display_name` for every `(channel_id, instance_domain)`. `videos_fts` indexes the wrong names.

**Desired behavior:**
- **Writer.** The video crawl resolves channel metadata by `(instance_domain, channel_id)`, so a newly written or updated video row's `channel_name` is its own channel's display name, from the crawl's channel list or else from the video payload's own channel. A channel id shared across hosts never lends one host's name to another host's videos.
- **Repair.** An operator-runnable, idempotent repair sets every `videos.channel_name` to the `display_name` of the `channels` row with the same `(channel_id, instance_domain)`, wherever the two differ and that `display_name` is non-empty. It works on either database: the crawler's `crawl.db` and the Engine's `whitelist.db`. It reports how many rows it changed. A second run changes 0 rows.
- **Search index.** After the repair of `whitelist.db`, `videos_fts` reflects the corrected names: a search for a channel's own display name finds that channel's videos, and a search for another instance's same-id channel name no longer finds them through `channel_name`. Its row count still equals `videos`.
- **Runs on main.** The repair is a migration of shared databases. Documentation says to run it on main after merge, never from a worktree. Runbooks (`DATA_BUILD.md`, or wherever the dataset steps live) name the command, which databases to point it at, and the follow-up re-embed step in this issue's comments.

**Key interfaces:**
- The video crawl's channel-metadata map and its lookup. The key becomes host plus channel id.
- The video-row builder's channel-name resolution: its precedence (crawl channel list first, then the video payload's channel) stays as it is.
- A new repair command or job taking a database path, beside the existing dataset jobs, following their CLI style.
- `videos_fts` rebuild: reuse the existing FTS rebuild helper the sync job uses, rather than a new one.

**Acceptance criteria:**
- [x] A crawl fixture with two hosts that share a `channel_id` but have different channel names writes each host's videos with their own channel's name. The test fails on today's code.
- [x] On a fixture DB with mismatched `videos.channel_name` values, the repair sets each to its own channel's `display_name`. It leaves already-correct rows and rows whose channel has an empty `display_name` untouched, reports the changed count, and a second run changes 0 rows.
- [x] After the repair on a fixture `whitelist.db`, an FTS query for the correct channel name returns that channel's videos. A query for the other instance's name does not return them, and `videos_fts` has as many rows as `videos`.
- [x] The repair runs against both database shapes: `crawl.db`'s schema and `whitelist.db`'s schema.
- [ ] The existing active suite stays green, including the crawler host-normalisation tests.
- [x] The runbook states the order: merge, then the repair on `crawl.db` and `whitelist.db` from main, then the operator re-embed step.
- [x] The agent does not run the repair against the real `crawl.db` or `whitelist.db`.


**Out of scope:**
- Re-embedding, ANN rebuild and similarity precompute (the operator follow-up above).
- Changing what `build-video-embeddings.py` puts in the embedding text.
- The `channels` table (it holds the correct names), and the Engine's `/api/video` write-back.
- Issue 27 (crawler seed instance mode), which touches the same crawler module later.
