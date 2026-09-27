# Resolve a batch of browser likes with one Engine call and cap requests at 50 likes

## Requirements

### What was asked for

Build issue `docs/project/issues/03-batch-like-resolution.md` as triaged: Resolve a batch of browser likes with one Engine call instead of one call per like, and cap a request at 50 like entries. The Agent Brief below, copied from the issue, is the confirmed requirement set; the build starts from this file.

### Purpose

Close the security-audit finding the issue records. This build is one of issues 01-06, delivered concurrently to use as little operator time and cause as few merge conflicts as possible.

### Decisions this rests on

`docs/project/adr/0003-metadata-endpoint-accepts-uuid-entries.md`.

### Agent Brief

**Category:** bug
**Summary:** Resolve a batch of browser likes with one Engine call instead of one call per like, and cap a request at 50 like entries

**Current behavior:**
When the Client backend receives browser likes as `(uuid, host)` pairs — on the likes page endpoint (`POST /api/user-profile/likes`, no profile required) and on likes import (`POST /api/profile/likes/import`) — it resolves each pair with its own sequential Engine `/internal/videos/resolve` call. Each call takes the Engine's global database lock. The likes page then makes one more batched `/internal/videos/metadata` call for the resolved `(video_id, instance_domain)` entries. One request may carry up to 200 likes (`MAX_CLIENT_LIKES`), so a single anonymous POST costs up to 201 Engine round trips and 201 lock acquisitions. The same 200 cap trims the `likes` list on the `/recommendations` proxy.

**Desired behavior:**
- **Engine.** `/internal/videos/metadata` accepts each entry either as `{video_id, instance_domain}` (today's form) or as `{video_uuid, instance_domain}`. An entry with both uses `video_id`. Malformed entries are skipped as today, and duplicates within each form are collapsed. Every entry in a request is answered under one `db_lock` hold, with SQL batched like the existing id lookup (chunked; no per-entry query). Rows come back in the order of their first matching entry. A video reached by both forms appears once. The error-count threshold filter applies to both forms. Existing id-keyed callers see no change.
- **Client backend.** The per-like resolve loop is gone. The likes page sends the deduplicated `(video_uuid, instance_domain)` entries in one metadata call and returns its rows. Likes import makes the same one call and records a like for each returned row, using the row's `video_id`, `video_uuid`, `instance_domain`, skipping disliked videos as today.
- **Cap.** `MAX_CLIENT_LIKES` is 50. It bounds like entries per request body on the likes page, the import, and the `/recommendations` proxy likes list. Entries past 50 are dropped, not rejected, and responses are otherwise unchanged.
- The likes page returns the same rows, in the same order, as before the change, for any request of 50 or fewer likes whose videos are all resolvable.

**Key interfaces:**
- Engine `/internal/videos/metadata` request body: `{"entries": [{"video_id"| "video_uuid": str, "instance_domain": str}, ...]}`; response shape unchanged (`{"ok", "count", "rows"}`).
- Engine entry parser (currently `_parse_entries`, shared with `/internal/dislikes/centroids`): the centroids endpoint must keep accepting only `video_id` entries. Either give metadata its own parser or make uuid acceptance opt-in.
- Engine metadata data function (currently `fetch_metadata_by_ids`): gains a uuid-keyed batch path, or a sibling function. `fetch_seed_embeddings_for_likes` shows an existing `(video_uuid, instance_domain) IN (...)` batch query to follow.
- Client `resolve_videos_by_uuid_host`: removed, or reimplemented as one metadata call; `fetch_metadata_for_entries` is the call to use.
- Client constant `MAX_CLIENT_LIKES`: 200 → 50.

**Acceptance criteria:**
- [ ] A likes-page request with N (≤ 50) likes causes exactly one Engine HTTP call, and one `db_lock` acquisition on the Engine.
- [ ] A likes-import request with N likes causes exactly one Engine HTTP call and records a like for each resolvable, non-disliked, non-errored video.
- [ ] A request with 60 like entries processes only the first 50 and returns 200.
- [ ] The likes page returns rows in submitted order, deduplicated, and a like whose video is unknown to the Engine is omitted without an error.
- [ ] `/internal/videos/metadata` with id-keyed entries returns the same rows as before; mixed id and uuid entries in one body both resolve.
- [ ] `/internal/dislikes/centroids` rejects or ignores uuid-keyed entries as it does today.
- [ ] The `/recommendations` proxy forwards at most 50 likes.
- [ ] Existing Client backend and Engine test suites pass.

**Out of scope:**
- The single-video `/internal/videos/resolve` endpoint and the user-action path that uses it.
- The profile's stored-likes limit (`MAX_LIKES = 100`) and the browser's local-likes limit.
- Rate limiting of these endpoints (issue 02).
- The `USE_LOCAL_LIKES_PROFILE` switch or any frontend change.

### Consistency constraints

- Match the surrounding code's style: stdlib HTTP handlers, `respond_json`, module-level named constants, and env vars read once at startup.
- Backwards compatibility is not required beyond what the brief states.
- Run `validate_tests.py` from the root of the tree this build runs in (a worktree for waves 1-2, main for wave 3). That tree's `.un` config carries it as `project_dir`.

### Batch context

Part of the security hardening batch (`.scratch/security-hardening-batch/notes.md`): issues 01-06 delivered in three waves of git worktrees. Wave 1 is plans 10, 11 and 12. Wave 2 is 13 and 14, branched from main after wave 1 merges. Wave 3 is 15, on the merged main. A wave 1 or 2 build runs in its own worktree created by `.scratch/security-hardening-batch/worktree-setup.sh`, merges to main when it closes, and is harvested on main, not in the worktree.

Wave 2, running alongside plan 13. It edits `client/backend/server.py` in four places: `MAX_CLIENT_LIKES` (`:49`), the `/recommendations` proxy trim (`:446`), likes import (`:837-843`) and the likes page (`:970-980`). Plan 15 runs afterwards and rewrites the 502 bodies this plan leaves in place.

### Conflicts

The brief does not conflict with the tree. Every function and line it names was checked against the source on 2026-09-26 (`.scratch/security-hardening-batch/notes.md`, File overlap). Line numbers will drift once earlier waves merge, so re-locate by function name at Step 3.

## High-level plan

### Approach

**Engine parser.** `/internal/videos/metadata` gets its own entry parser, which accepts `{video_id, instance_domain}` or `{video_uuid, instance_domain}`. An entry with both uses `video_id`. Malformed entries are skipped, and duplicates within each form are collapsed. `/internal/dislikes/centroids` keeps the existing `_parse_entries` (`handlers/internal_client_reads.py:20`), so it still accepts only ids.

**Engine data.** A uuid-keyed batch lookup is added beside `fetch_metadata_by_ids` (`engine/server/data/metadata.py:110`). It uses a chunked `(video_uuid, instance_domain) IN (...)` query, following `fetch_seed_embeddings_for_likes` (`data/embeddings.py:191`), and applies the same error-count filter. The handler answers both forms under one `db_lock` hold, returns each video once, and orders rows by their first matching entry.

**Client.** `resolve_videos_by_uuid_host` (`client/backend/lib/engine_api_client.py:136`) is removed. The likes page and likes import each make one `fetch_metadata_for_entries` call with the deduplicated uuid entries. Import records a like for each returned row and skips disliked videos, as it does today.

**Cap.** `MAX_CLIENT_LIKES` goes from 200 to 50, and each of its three uses still drops the extra entries silently.

### Alternatives considered

- **A new `/internal/videos/resolve-batch` endpoint** (the audit's suggested fix). Rejected by ADR-0003: the metadata endpoint already returns what the likes page needs, so one call replaces both the resolve loop and the separate metadata call.
- **An opt-in flag for uuid entries on the shared `_parse_entries`.** Viable, and the brief allows it. A separate parser is preferred so a wrong flag default can never widen what centroids accepts.
- **Parallelising the per-like resolve calls.** Rejected: it still takes the lock N times.

### Risks and limitations

- **Accepted consequence (ADR-0003).** Import no longer imports videos at or over the Engine's error-count threshold, because the metadata endpoint filters them and resolve did not.
- **Row order.** Metadata returns rows in first-entry order, so the likes page keeps the submitted order only if the handler preserves it across both lookup forms. The acceptance criteria require this explicitly.
- **Callers.** The `/recommendations` proxy trim at `:446` and `_parse_client_likes` both read `MAX_CLIENT_LIKES`. Grep for any other reader at Step 3.
- **Shared `whitelist.db`.** The worktree symlinks the main tree's `whitelist.db`, so this build's test Engines write interaction rows into the same file as other lanes, and as the live Engine if it runs. Every test run already does this; worktrees only make it concurrent.
- **Tracked test record.** `tests/last_test_validation.json` and `tests/last_test_output.txt` always conflict on merge. Take main's copy and re-run `validate_tests.py --compare` on the merged tree.
- **Engine rate limit.** Run Engine-backed test files in their own `validate_tests.py` invocations (memory `engine-rate-limit-single-lane-test-runs`).

### Tradeoffs accepted

A request's likes beyond the first 50 are dropped silently, not rejected.
