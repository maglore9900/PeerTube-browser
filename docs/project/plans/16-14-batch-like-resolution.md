# 14-batch-like-resolution

_Rendered by the `dev-flow` workflow from its run state. Every edit here is overwritten on the next step; the evidence each gate turned on is in `docs/project/plans/16-14-batch-like-resolution.record.md`._

## Requirements

### Purpose

Build issue `docs/project/issues/03-batch-like-resolution.md` (category bug) as triaged. It closes the security-audit finding (run-1, `resolve_videos_by_uuid_host` loop): one anonymous `POST /api/user-profile/likes` currently costs up to 201 sequential Engine round trips and 201 acquisitions of the Engine's global `db_lock`. After this build, a batch of browser likes is resolved with one Engine call, and a request is capped at 50 like entries. The decision it rests on is `docs/project/adr/0003-metadata-endpoint-accepts-uuid-entries.md`: `/internal/videos/metadata` accepts `(video_uuid, instance_domain)` entries, and a separate resolve-batch endpoint was rejected. The build is part of the security hardening batch (`.scratch/security-hardening-batch/notes.md`), wave 2 alongside plan 13, and runs in the worktree `/home/enduser/code/PeerTube-browser/.worktrees/fix-14-batch-like-resolution`.

### Current behaviour (verified in the worktree)

- `client/backend/server.py:52`: `MAX_CLIENT_LIKES = 200`, next to `MAX_LIKES = 100` (profile stored-likes limit, out of scope) and `ENGINE_FEED_LIKES_MAX = 5`.
- `client/backend/server.py:1105` `_parse_client_likes(payload, max_items)`: takes `raw[:max_items]` and then skips malformed items (not a dict, or `uuid`/`host` not a non-empty string). It returns `[{"video_uuid", "instance_domain"}]` stripped, and does not deduplicate.
- `client/backend/server.py:493`, the `/recommendations` and `/videos/similar` POST proxy: `for entry in likes[:MAX_CLIENT_LIKES]:` sanitises to `{"uuid", "host"}`, skipping malformed entries.
- `client/backend/server.py:872-900`, `_handle_likes_import` (`POST /api/profile/likes/import`, behind `_require_profile`): calls `_parse_client_likes(body, MAX_CLIENT_LIKES)`, then `resolve_videos_by_uuid_host`. On `EngineApiError` it answers 502 `{"error": "Engine resolve failed: ..."}`. Otherwise, inside `with conn:`, it skips each video where `is_disliked(conn, profile_id, video_id, instance_domain)`, calls `record_like(conn, profile_id, "like", video, MAX_LIKES)` for the rest, and answers 200 `{"imported": n}`. `record_like` (`client/backend/lib/users_store.py:79`) reads `video_id`, `instance_domain` and `video_uuid` from the dict.
- `client/backend/server.py:1012-1029`, `_handle_user_profile_likes_from_client` (`POST /api/user-profile/likes`, no profile required): calls `_parse_client_likes`. An empty list gives 200 `{"likes": [], "updatedAt"}` with no Engine call. Otherwise it calls `resolve_videos_by_uuid_host`, then `fetch_metadata_for_entries(resolved)`. On `EngineApiError` it answers 502 `{"error": "Engine metadata failed: ..."}`. Otherwise it answers 200 `{"likes": rows, "updatedAt"}`.
- `client/backend/lib/engine_api_client.py:136` `resolve_videos_by_uuid_host`: deduplicates on `uuid::host` and makes one `resolve_video_seed` → `/internal/videos/resolve` call per like. It is imported in `server.py:32`. `fetch_metadata_for_entries` (`:92`) posts `{"entries": entries}` to `/internal/videos/metadata`, raises `EngineApiError` on a non-200 status or an invalid payload, and returns the dict rows.
- `engine/server/api/handlers/internal_client_reads.py:20` `_parse_entries`: returns None when `entries` is not a list, skips malformed items, and deduplicates on `video_id::instance_domain`. It is used by `handle_internal_videos_metadata` (`:95`) and `handle_internal_dislike_centroids` (`:129`). The metadata handler answers 400 `Missing entries`, and answers 200 with empty rows when there are no entries. Under one `with server.db_lock:` it calls `fetch_metadata_by_ids(..., error_threshold=getattr(server, "video_error_threshold", None))`, then emits rows in entry order via `_like_key`. The response is `{"ok": True, "count", "rows"}`.
- `engine/server/data/metadata.py:110` `fetch_metadata_by_ids`: chunks of 450 with an `OR` of `(v.video_id = ? AND v.instance_domain = ?)`. It inner-joins `video_embeddings` and left-joins `channels`, applies `AND (v.error_count IS NULL OR v.error_count < ?)` when the threshold is > 0, and returns a dict keyed by `like_key(row)` (`video_id::instance_domain`).
- `engine/server/data/embeddings.py:191` `fetch_seed_embeddings_for_likes`: the precedent for a `WHERE (v.video_uuid, v.instance_domain) IN ((?, ?), ...)` batch query. It is not chunked.
- The old resolve path (`fetch_seed_embedding` → `_fetch_seed_by_uuid`) matches `v.video_uuid = ? AND v.instance_domain = ?` exactly, with the same `video_embeddings` inner join and `LIMIT 1`, and no error-count filter. `_seed_from_row` also drops rows whose embedding blob is empty or does not match `embedding_dim`.
- The `videos` table key is `PRIMARY KEY (video_id, instance_domain)`. Nothing enforces uniqueness of `(video_uuid, instance_domain)`.

### R1 — Engine: metadata endpoint entry parsing

- `/internal/videos/metadata` gets its own entry parser. `_parse_entries` stays unchanged and is still used by `/internal/dislikes/centroids`, so centroids keeps accepting only `video_id` entries, and uuid-only entries there are skipped as malformed, as today.
- An entry is accepted as `{video_id, instance_domain}` or `{video_uuid, instance_domain}`, where each value is a non-empty string and is stripped. An entry carrying a valid `video_id` is treated as id-keyed, even if it also has `video_uuid`. An entry with neither valid key, or without a valid `instance_domain`, or that is not a dict, is skipped.
- Duplicates are collapsed within each form (id form on `video_id::instance_domain`, uuid form on `video_uuid::instance_domain`), keeping the first occurrence.
- A body without an `entries` list still gets 400 `{"error": "Missing entries"}`. When no entries are valid, the answer is still 200 `{"ok": True, "count": 0, "rows": []}` without taking the lock.

### R2 — Engine: uuid-keyed batch lookup

- A uuid-keyed batch data function goes beside `fetch_metadata_by_ids` in `engine/server/data/metadata.py` (a sibling function, or a path in the same function). It selects the same columns with the same joins (inner `video_embeddings`, left `channels`) and the same error-count threshold clause, and builds the same row dict, so a video's row is identical whichever form reached it.
- Its SQL is `WHERE (v.video_uuid, v.instance_domain) IN (...)`, following `fetch_seed_embeddings_for_likes`, chunked like the id lookup (at most 450 pairs per statement). There is no query per entry.
- The match is exact on `video_uuid` and `instance_domain`, as the old resolve was.
- A uuid entry yields at most one row. If several videos share one `(video_uuid, instance_domain)`, the one with the lowest `video_id` is chosen, so the choice is deterministic (operator-approved; resolve's `LIMIT 1` was arbitrary).
- No embedding-blob validity check is added (operator-approved difference from resolve; see conflicts).

### R3 — Engine: one lock hold, ordering, dedup across forms

- The handler answers every entry of a request, id and uuid forms together, under a single `with server.db_lock:` hold, one acquisition per request.
- Rows are emitted in the order of the first entry that matches each video. A video reached by both an id entry and a uuid entry (or by several entries) appears once, identified by `video_id::instance_domain`.
- The error-count threshold filter applies to both forms.
- The response shape is unchanged: `{"ok": True, "count": len(rows), "rows": rows}`. Existing id-keyed callers (the Client's `_handle_user_profile_likes_get`, `_handle_block_add`, and any other caller) see exactly the rows they saw before.

### R4 — Client: likes page makes one Engine call

- `_handle_user_profile_likes_from_client` sends the deduplicated `(video_uuid, instance_domain)` entries from `_parse_client_likes` in a single `fetch_metadata_for_entries` call and returns its rows as `likes`. There is no resolve call.
- Deduplication happens before the call, on `video_uuid::instance_domain`, keeping the first occurrence and submitted order. It may be done by the Client, the Engine parser, or both. The Engine's R1 dedup alone is sufficient.
- A like whose video is unknown to the Engine (or at or over the error threshold) is omitted without error.
- An empty parse still answers 200 `{"likes": [], "updatedAt"}` without an Engine call.
- The 502 path and body text are left as they are (plan 15 rewrites 502 bodies later).
- For any request of 50 or fewer likes whose videos all resolve, the response rows and their order are the same as before the change.

### R5 — Client: likes import makes one Engine call

- `_handle_likes_import` makes the same single `fetch_metadata_for_entries` call with the deduplicated uuid entries.
- For each returned row it skips the video if `is_disliked(conn, profile_id, row["video_id"], row["instance_domain"])`. Otherwise it calls `record_like(conn, profile_id, "like", {video_id, video_uuid, instance_domain from the row}, MAX_LIKES)`. It answers 200 `{"imported": n}`, as today.
- Accepted consequence (ADR-0003): a video at or over the Engine's error-count threshold is no longer imported.
- The existing 502 on `EngineApiError` stays. Its body text may stay "Engine resolve failed: ..." (plan 15 rewrites it).

### R6 — Client: remove the per-like resolve loop

`resolve_videos_by_uuid_host` is removed from `client/backend/lib/engine_api_client.py`, and its import is dropped from `client/backend/server.py`. `resolve_video_seed` and `/internal/videos/resolve` remain, for block-add and user actions.

### R7 — Cap at 50

- `MAX_CLIENT_LIKES = 50` in `client/backend/server.py`.
- It bounds like entries per request body on the likes page, the import (both via `_parse_client_likes`), and the `/recommendations` / `/videos/similar` proxy `likes` list (`likes[:MAX_CLIENT_LIKES]`).
- Entries past the 50th are dropped, not rejected. The cap applies to the raw list before malformed entries are skipped, as today. Responses are otherwise unchanged.
- Before editing, grep for any other reader of `MAX_CLIENT_LIKES`. Only the three sites above were found.

### Acceptance criteria

- A likes-page request with N ≤ 50 likes causes exactly one Engine HTTP call and one `db_lock` acquisition on the Engine.
- A likes-import request with N likes causes exactly one Engine HTTP call and records a like for each resolvable, non-disliked, non-errored video.
- A request with 60 like entries processes only the first 50 and returns 200 (likes page and import).
- The likes page returns rows in submitted order, deduplicated. A like whose video is unknown to the Engine is omitted without an error.
- `/internal/videos/metadata` with id-keyed entries returns the same rows as before. Mixed id and uuid entries in one body both resolve. A video reached by both forms appears once.
- `/internal/dislikes/centroids` treats uuid-keyed entries exactly as today (skipped as malformed).
- The `/recommendations` proxy forwards at most 50 likes.
- Existing Client backend and Engine test suites pass, including `tests/active/test_profiles.py::test_importing_browser_likes_marks_each_imported_video_liked_and_no_other` and `tests/active/test_server.py`.

### Testing constraints

- Run `validate_tests.py` from `/home/enduser/code/PeerTube-browser/.worktrees/fix-14-batch-like-resolution` (this worktree's `project_dir`). Trees: active `tests/active`, working `tests/tmp`, archive `tests/archive`, record `tests/last_test_validation.json`, output `tests/last_test_output.txt`.
- Run each Engine-backed test file in its own `validate_tests.py` invocation, because the Engine's per-IP rate limit is shared (memory `engine-rate-limit-single-lane-test-runs`).
- The Engine-call-count and lock-count criteria need a counting or capturing seam: a stand-in Engine or a wrapped lock or stub server. They cannot be read off the live Engine.
- The worktree's `whitelist.db` is a symlink to main's, so test Engines share it with other lanes. These endpoints only read from it, but the fixture Engine's startup still touches the file.
- Engine handler code imports numpy (and `handlers.similar` pulls in faiss), so any in-process Engine unit test must run under the Engine interpreter (`conftest.ENGINE_PY`) or through the live `engine` fixture.

### Baseline suite state

The pre-build baseline run exited with code 0, variant false: the suite is green before the build starts.

### Consistency constraints

- Match the surrounding style: stdlib HTTP handlers, `respond_json`, module-level named constants, env vars read once at startup, and a docstring on every function. No new dependency.
- Smallest thing that works: no new endpoint, no new module beyond tests, no abstraction with one implementation.
- Backwards compatibility is not required beyond what these requirements state.
- Do not softwrap.

### Out of scope

- The single-video `/internal/videos/resolve` endpoint and the user-action and block-add paths that use it.
- `MAX_LIKES = 100` (profile stored-likes limit) and the browser's local-likes limit.
- Rate limiting of these endpoints (issue 02).
- The `USE_LOCAL_LIKES_PROFILE` switch and any frontend change.
- 502 body wording (plan 15).

### Batch and merge context

- Wave 2, alongside plan 13. This plan edits `client/backend/server.py` at `MAX_CLIENT_LIKES` (now line 52), the proxy trim (now line 493), `_handle_likes_import` (now lines 872-900), `_handle_user_profile_likes_from_client` (now lines 1012-1029), and the import line 32. Keep the edits local. Line numbers drift, so re-locate by function name.
- The build merges to main when it closes. Harvest runs on main, not in the worktree.
- `tests/last_test_validation.json` and `tests/last_test_output.txt` always conflict on merge: take main's copy and re-run `validate_tests.py --compare` on the merged tree.

## High-level plan

### Approach

The fix sits on the Engine side of one existing endpoint. The Client side only loses code.

**Engine: data layer (R2).** In `engine/server/data/metadata.py`, `fetch_metadata_by_ids` already holds the 29-column SELECT, the inner `video_embeddings` join, the left `channels` join, the error-count clause and the row-dict construction. I move that body into one private helper in the same file. The helper takes a chunk's WHERE fragment and its parameters, and returns the built row dicts. `fetch_metadata_by_ids` keeps its signature and output (a dict keyed by `video_id::instance_domain`) and becomes a thin caller that supplies its existing `OR` fragment. A new sibling function, `fetch_metadata_by_uuids`, supplies `(v.video_uuid, v.instance_domain) IN ((?, ?), ...)`, the same row-value form `fetch_seed_embeddings_for_likes` already runs on this SQLite. It is chunked at 450 pairs, which is 900 bound values plus one threshold, under SQLite's 999 limit. The helper has two callers, so it is shared code, not a single-implementation abstraction. Because a video's row dict is built in exactly one place, it is identical whichever form reached it. The uuid function orders each chunk by `v.video_id` and keeps the first row per `video_uuid::instance_domain`. That gives at most one row per uuid entry, and the lowest `video_id` when several videos share a pair. Entries are deduplicated before chunking, so one pair never spans two chunks. The match is an exact equality on both columns, as `_fetch_seed_by_uuid` did, and no embedding-blob check is added (operator-approved). The rowid-keyed `fetch_metadata` at the top of the file is not touched, which keeps the diff local.

**Engine: parser and handler (R1, R3).** `internal_client_reads.py` gets a second parser beside `_parse_entries`, used only by `handle_internal_videos_metadata`. For each item it:
- skips anything that is not a dict, or has no valid stripped `instance_domain`;
- treats an item with a valid `video_id` as id-form, even if it also carries `video_uuid`;
- otherwise treats an item with a valid `video_uuid` as uuid-form, and skips it if it has neither.

It deduplicates within each form on its own key, keeping the first occurrence, and returns one ordered list of tagged entries. When `entries` is not a list it returns None, so the 400 `Missing entries` path is unchanged. `_parse_entries` and `/internal/dislikes/centroids` are not edited, so centroids keeps skipping uuid-only entries.

The handler flow:
1. An empty parse still answers 200 with no rows, before any lock.
2. It splits the ordered list into id entries and uuid entries.
3. Inside one `with server.db_lock:` it calls `fetch_metadata_by_ids` for the id entries and `fetch_metadata_by_uuids` for the uuid entries, skipping either call when its list is empty, with the same `video_error_threshold` for both.
4. After releasing the lock, it walks the ordered entries, looks up each entry's row in the dict for its form, and emits the row only if its `video_id::instance_domain` has not been emitted yet.

Rows therefore come out in first-matching-entry order, and a video reached by both forms, or by several entries, appears once. An id-only request runs exactly the query it ran before and emits the same rows in the same order, so `_handle_user_profile_likes_get`, `_handle_block_add` and the other id callers see no change. The response shape `{"ok", "count", "rows"}` is unchanged.

**Client (R4, R5, R6).**
- **Likes page:** `_handle_user_profile_likes_from_client` passes the `_parse_client_likes` output (already `{video_uuid, instance_domain}` dicts) straight to one `fetch_metadata_for_entries` call and returns its rows as `likes`. The empty-parse early 200 stays, and so do the 502 path and its text. Deduplication is left to the Engine parser. R4 says that is sufficient, and it avoids a second copy of the same loop in the Client.
- **Import:** `_handle_likes_import` makes the same single call. Its 502 text stays "Engine resolve failed". For each returned row it checks `is_disliked` on the row's `video_id` and `instance_domain`, and otherwise calls `record_like` with the row's `video_id`, `video_uuid` and `instance_domain`. An empty parse makes no Engine call, because `fetch_metadata_for_entries` already returns `[]` for an empty list.
- **Removal:** `resolve_videos_by_uuid_host` is deleted from `engine_api_client.py` and from the import on `server.py:32`. `resolve_video_seed` stays.

**Cap (R7).** `MAX_CLIENT_LIKES` becomes 50. A grep of the worktree, ignoring the stale `delete_me/*.bak-*` copies, confirms the only readers are the proxy trim and the two `_parse_client_likes` calls. All three keep slicing the raw list before skipping malformed items, so entries past the 50th are dropped silently.

**How each requirement is met.**
- **R1:** the new parser.
- **R2:** the sibling uuid function over the shared SELECT and row builder.
- **R3:** one lock hold around both lookups, then the ordered, deduplicating walk.
- **R4 and R5:** one metadata call each.
- **R6:** the deletion.
- **R7:** the constant.

**Same rows as before (R4).** For 50 or fewer likes that all resolve, old and new produce the same rows in the same order. The old flow deduplicated on `uuid::host` in submitted order, resolved each pair to a `video_id`, then asked metadata for those ids in that order, deduplicating on id. The new flow does the same steps inside one Engine call.

**Tests.** The Engine-side checks are:
- parser forms and dedup;
- id-only rows unchanged;
- mixed id and uuid entries;
- the same video via both forms appearing once;
- lowest `video_id` on a shared uuid pair;
- the error threshold on the uuid form;
- centroids ignoring uuid entries;
- exactly one lock acquisition.

These run in-process against a temp SQLite DB with a stand-in server whose `db_lock` counts its enters. Because the handler imports numpy, they run under `conftest.ENGINE_PY` as a subprocess, following the `test_db.py` pattern.

The Client-side checks are:
- one Engine HTTP call per likes-page or import request;
- a 60-entry body reaching the Engine as 50;
- the proxy forwarding at most 50;
- unknown videos omitted;
- disliked videos skipped on import.

These use a capturing stand-in Engine, a small stdlib HTTP server that records each request and returns canned rows. The existing `test_profiles.py` import test and `test_server.py` run against the live Engine fixture, each in its own `validate_tests.py` invocation.

### Alternatives considered

- **A new `/internal/videos/resolve-batch` endpoint.** Rejected by ADR-0003. The metadata endpoint already returns what both callers need, so one call replaces both the resolve loop and the separate metadata call.
- **An opt-in uuid flag on the shared `_parse_entries`.** Rejected. A separate parser means centroids cannot be widened by a wrong default or a forgotten argument, and R1 asks for a separate parser.
- **A uuid path inside `fetch_metadata_by_ids`, switched by a keyword.** Viable under R2. Rejected because the function name and its return key (`video_id::instance_domain`) would then lie for the uuid path, and the handler needs the uuid path keyed by `video_uuid::instance_domain`.
- **Copying the SELECT and row dict into the new function.** Rejected. That would make a third copy in the file (`fetch_metadata` already duplicates most of it), and any drift between the two metadata copies would break the "identical row whichever form" guarantee without any test failing.
- **Doing the lowest-`video_id` choice in SQL with a window function or a GROUP BY and MIN.** Rejected as more SQL for no gain. An `ORDER BY v.video_id` inside each chunk, then keeping the first row per key, is plain and deterministic.
- **Keeping `resolve_videos_by_uuid_host` as a one-call wrapper.** Rejected by R6, and a wrapper around a single call adds nothing.
- **Deduplicating in the Client too.** Rejected as a second copy of the Engine parser's loop. R4 states the Engine dedup alone is sufficient.
- **Parallel resolve calls.** Rejected. It still takes the lock N times, which is the finding.

### Risks and gotchas

- **Lowest `video_id` among eligible rows.** The error-count clause is applied in SQL before the pick, so the choice is the lowest `video_id` among videos that pass the threshold. If the lowest-id sibling is errored, a healthy sibling is returned. The old flow could return nothing there: resolve's arbitrary `LIMIT 1` might pick the errored one, and metadata then dropped it. I take this to be what "threshold applies to both forms" plus "lowest `video_id`" means together. It only matters for duplicated `(video_uuid, instance_domain)` pairs.
- **Lock hold length.** One hold now covers up to two queries instead of one. With the Client capping at 50, the uuid query is a single statement. A direct caller of the Engine could send a large body, but that is bounded by the Engine's body limit, and the chunking caps each statement's size.
- **Row-value `IN`.** It needs SQLite 3.15 or newer. The Engine already relies on it in `fetch_seed_embeddings_for_likes`, so this adds no new dependency.
- **Missing index.** No index on `(video_uuid, instance_domain)` is confirmed, so the uuid query may scan more than the id query. The old per-like resolve ran the same predicate 50 to 200 times, so one batched query is no worse. Adding an index is out of scope.
- **Moving the id path into the helper.** Moving `fetch_metadata_by_ids`'s body touches the query every existing metadata caller uses. A regression test comparing id-keyed output before and after on a fixture DB guards against that.
- **Shared test resources.** Test Engines share `whitelist.db` through the symlink. These endpoints only read it, but the fixture Engine's startup still touches the file.
- **Engine rate limit.** Engine-backed test files need separate `validate_tests.py` invocations.
- **Merge overlap.** Plan 13 edits `server.py` in wave 2, so the four edits stay local and are located by function name. `tests/last_test_validation.json` and `tests/last_test_output.txt` will conflict on merge: take main's copy and re-run `--compare`.

### Tradeoffs the operator accepts

- Likes past the 50th in a request are dropped silently, not rejected.
- Import no longer records videos at or over the Engine's error-count threshold (ADR-0003).
- Videos with an empty or mismatched embedding blob now appear on the likes page and are imported, where resolve used to drop them (already approved).
- When several videos share a uuid and host, the lowest-`video_id` eligible one is chosen.
- Deduplication of browser likes happens only on the Engine.

## Impacts


<impacts>
<impact path="engine/server/data/metadata.py" element="fetch_metadata_by_ids (lines 110-205): body moves into a new private helper">
**What changes.** The helper takes over:
- the 29-column SELECT (lines 133-162), which is `FROM video_embeddings e JOIN videos v ... LEFT JOIN channels c`;
- the optional `error_count` clause (lines 127-130), added only when `error_threshold > 0`, with its parameter appended after the pair parameters;
- the row-dict build (lines 174-204).

`fetch_metadata_by_ids` keeps its signature `(conn, entries, error_threshold=None) -> dict[str, dict]` and its `if not entries: return {}` early return. It still builds its 450-entry chunks through `_chunk` (line 105), its `OR` of `(v.video_id = ? AND v.instance_domain = ?)`, and its params from `entry.get("video_id")` and `entry.get("instance_domain") or ""`. Its result is still keyed on `like_key(row)` (`video_id::instance_domain`, `engine/server/api/recommendations/keys.py:8`).

**What depends on it.**
- `handle_internal_videos_metadata` (`engine/server/api/handlers/internal_client_reads.py:113`).
- `similarity_candidates._build_rows` (`engine/server/data/similarity_candidates.py:170` and `:175`), which feeds similar and up-next rows. The plan's caller list does not name it (see its own entry).

**Regression risk: medium.**
- The threshold parameter must stay last. It must be appended once per chunk, not once per call, or chunks after the first get the wrong parameter count.
- The row dict must keep exactly the same 29 keys. The uuid path keys on `video_uuid`/`instance_domain`, and `record_like` on import reads `video_id`/`video_uuid`/`instance_domain`.
- The id path keys the helper's output with `like_key`, which accepts dicts and `sqlite3.Row` (keys.py:10-15).
- If the helper takes an ORDER BY or sorts for the uuid caller, the id path's result is still a dict, so ordering cannot change what id callers see. The helper's signature must let the uuid caller order by `v.video_id`, or the uuid caller must sort in Python.
- Nothing in `tests/active` exercises this function directly today. It is covered only indirectly by the live-Engine tests (`test_server.py`, `test_blocks.py`, `test_similar.py`, `test_profiles.py`).
</impact>
<impact path="engine/server/data/metadata.py" element="new fetch_metadata_by_uuids (sibling function)">
**What changes.**
- A new public function, `(conn, entries, error_threshold=None)`, in the style of its sibling, with a docstring (every function in the file has one).
- It deduplicates `(video_uuid, instance_domain)` pairs, chunks them at 450 with `_chunk`, and runs `WHERE (v.video_uuid, v.instance_domain) IN ((?, ?), ...)` through the shared helper, ordered by `v.video_id`. The row-value form is the one already used at `engine/server/data/embeddings.py:228`.
- It keeps the first row per `video_uuid::instance_domain`, keyed from the row's own values, and returns that dict.

**What depends on it.** Only the new handler path.

**Regression risk: low for existing callers (new code), medium for correctness.**
- The match is a binary TEXT comparison, so it is exact and case-sensitive, like `_fetch_seed_by_uuid` (embeddings.py:134-139).
- The lowest `video_id` is chosen among rows that pass the error filter. This is the plan's stated interpretation.
- The inner join cannot fan out if `video_embeddings` is keyed on `(video_id, instance_domain)`. I did not re-open the schema DDL in this pass; the previous record cites `build-video-embeddings.py:73`.
- 450 pairs is 900 bound values plus 1 threshold, which stays under 999.
- An empty `entries` must return `{}` without a query, mirroring line 116.
- **The plan's "Missing index" risk is wrong.** `CREATE INDEX IF NOT EXISTS idx_videos_uuid_instance ON videos (video_uuid, instance_domain)` exists at `engine/server/data/videos.py:21-22` and is created on every Engine start (`engine/server/api/server.py:337`, `ensure_video_indexes(db)`). A temp-DB unit test will not have the index unless it calls `ensure_video_indexes`. That does not affect correctness.
</impact>
<impact path="engine/server/data/metadata.py" element="fetch_metadata (rowid-keyed, lines 11-102), _chunk (105-107), module imports (1-8)">
**What changes.** Nothing. `fetch_metadata` stays a separate copy of most of the SELECT and row dict, and `_chunk` is reused.

**What depends on it.** `fetch_metadata` is used by similar.py, ann.py, random_videos.py and search.py; the previous record lists these and I did not re-check them.

**Regression risk: none if the diff stays out of lines 11-102.**

**Test-design note.** The module imports only `sqlite3`, `typing` and `recommendations.keys`, and `recommendations/__init__.py` imports only `typing`. So `data.metadata` can be imported in the pytest interpreter in-process, the way `tests/active/test_internal_events.py:25-36` imports `data.*`. The data-layer tests (id output unchanged, uuid lookup, lowest `video_id`, threshold) do not need an `ENGINE_PY` subprocess. Only the handler does, because `internal_client_reads` imports numpy.
</impact>
<impact path="engine/server/data/similarity_candidates.py" element="_build_rows (lines 155-212), direct caller of fetch_metadata_by_ids">
**What changes.** No edit.

**Why it matters.** It calls `fetch_metadata_by_ids` both with and without `server.db_lock` (lines 169-179), looks rows up with `metadata.get(like_key(entry))` (line 195), and compares `like_key(meta)` with the source key (line 198). Its entries come from the ANN index or cache and can carry extra keys or a `None` instance_domain. The refactored function must go on reading only `entry.get("video_id")` and `entry.get("instance_domain") or ""`.

**Regression risk: medium, and the plan's caller list does not name it.** A drift in keying, row content or per-chunk parameters would silently empty or alter similar and up-next pages. It is covered only indirectly, by the live-Engine `tests/active/test_similar.py`.
</impact>
<impact path="engine/server/api/handlers/internal_client_reads.py" element="new metadata entry parser beside _parse_entries (line 20)">
**What changes.** A second parser, used only by `handle_internal_videos_metadata`. It mirrors `_parse_entries`:
- `isinstance(body, dict)` guard;
- returns None when `entries` is not a list;
- skips non-dict items and items without a non-empty stripped string `instance_domain`.

Beyond that:
- A valid `video_id` means id form, even when a uuid is also present. Otherwise a valid `video_uuid` means uuid form. Anything else is skipped.
- Duplicates are removed per form (id form on `_like_key`, uuid form on `video_uuid::instance_domain`), keeping the first.
- It returns one ordered, tagged list. It needs a docstring.

**What depends on it.** `handle_internal_videos_metadata` only.

**Regression risk: medium.**
- The id-form entries handed to `fetch_metadata_by_ids` must be the same stripped `{video_id, instance_domain}` dicts `_parse_entries` builds.
- **Behaviour change for id callers.** An item with an empty or whitespace `video_id` but a valid `video_uuid` was skipped before. Now it resolves through the uuid form.
  - `_handle_user_profile_likes_get` sends `fetch_recent_likes` rows, which carry `video_id`, `video_uuid`, `instance_domain` and `updated_at` (`client/backend/lib/users_store.py:126-141`).
  - `record_like` stores `str(video.get("video_id") or "")` (users_store.py:90), so a stored like with an empty id would now appear.
  - Every current writer passes a canonical non-empty id: server.py:775 checks it, and import uses Engine rows. No such rows are expected.
</impact>
<impact path="engine/server/api/handlers/internal_client_reads.py" element="handle_internal_videos_metadata (lines 95-126)">
**What changes.**
- The new parser replaces the `_parse_entries` call at line 103. The 400 `Missing entries` (104-106) and the empty 200 before any lock (108-110) stay.
- The entries split into an id list and a uuid list.
- One `with server.db_lock:` calls `fetch_metadata_by_ids` and/or `fetch_metadata_by_uuids`, skipping an empty list, both with `error_threshold=getattr(server, "video_error_threshold", None)`.
- After the lock is released, an ordered walk looks each entry up in its form's own dict and emits the row once, keyed on the row's `video_id::instance_domain`.
- The response `{"ok", "count", "rows"}` does not change.
- The docstring ("canonical (video_id, instance_domain) entries") must be updated.

**What depends on it.**
- The route, dispatched from `engine/server/api/handlers/similar.py:402-404` behind `_bridge_authorized` (line 394).
- Client callers through `fetch_metadata_for_entries`: `_handle_user_profile_likes_get` (server.py:1006), `_handle_block_add` (server.py:947), and after this change `_handle_user_profile_likes_from_client` and `_handle_likes_import`.

**Regression risk: medium-high.**
- Id-only bodies must give the same rows in the same order: today's loop (lines 119-123) emits in entry order.
- Cross-form dedup must key on the returned row, not the entry, or a video reached by both forms appears twice.
- The id dict and the uuid dict must stay separate, because both key formats are `x::y` strings and could collide.
- `db_lock` is a plain lock, so it must be taken once in the handler and never inside the data functions.
- **Statement deadline.** `do_POST` (`similar.py:355-363`) runs the whole request, lock wait and both queries included, under one `statement_deadline`. A breach gives 503 `Query time limit exceeded`, which the Client sees as `EngineApiError` and answers with 502. Before, each resolve had its own budget. With 50 or fewer pairs on an index this is negligible.
</impact>
<impact path="engine/server/api/handlers/internal_client_reads.py" element="_like_key (line 15), _parse_entries (20-48), handle_internal_dislike_centroids (129-158), handle_internal_video_resolve (51-92)">
**What changes.** Nothing (R1 and out of scope). Centroids keeps `_parse_entries`, so uuid-only entries there are skipped as malformed and do not count toward `DISLIKE_MAX_ENTRIES` (line 141). Resolve stays for `_handle_user_action` (server.py:758) and `_handle_block_add` (server.py:946).

**Regression risk: low.** The risk is an accidental edit while the sibling parser is added. The centroids-ignores-uuid test guards it, and `tests/active/test_dislike_profile.py` covers centroids.
</impact>
<impact path="engine/server/api/handlers/internal_client_reads.py" element="module imports (lines 4-12)">
**What changes.** Line 9 becomes `from data.metadata import fetch_metadata_by_ids, fetch_metadata_by_uuids`.

**What depends on it.** `handlers/similar.py` imports this module at load time, so the whole Engine does. The module imports numpy (line 6), so a handler test must run under `conftest.ENGINE_PY`.

**Regression risk: high impact, low probability.** A bad import name stops the Engine at startup, and every live-Engine test then fails in the `engine` fixture (`tests/active/conftest.py:101-137`).
</impact>
<impact path="engine/server/api/handlers/similar.py" element="do_POST (355-363), _dispatch_post (390-410), module docstring line 11">
**What changes.** No edit. The route and its bridge auth are unchanged. The docstring "internal Client metadata batch lookup" stays accurate.

**Why it matters.** This is where the single per-request statement deadline covers the new combined lookup (see the handler entry).

**Regression risk: low.**
</impact>
<impact path="engine/server/api/handlers/__init__.py" element="module docstring line 6">
**What changes.** Nothing required. "internal_client_reads: internal read endpoints used by Client service" stays true.

**Regression risk: none.**
</impact>
<impact path="engine/server/data/embeddings.py" element="fetch_seed_embeddings_for_likes (191+), fetch_seed_embedding / _fetch_seed_by_uuid / _seed_from_row (104-188)">
**What changes.** Nothing.
- `fetch_seed_embeddings_for_likes` is the precedent for the row-value `IN` (line 228). It is unchunked; the new function adds chunking.
- `_fetch_seed_by_uuid` stays for `/internal/videos/resolve`.

**Accepted differences from the old resolve path**, which the tests and the docs should state:
- `_seed_from_row` dropped rows with an empty or mismatched embedding blob (line 178). The metadata path has no such check.
- Resolve had no error filter and an arbitrary `LIMIT 1` (line 140). The new path is error-filtered and deterministic, choosing the lowest `video_id`.

**Regression risk: none to this file.**
</impact>
<impact path="engine/server/data/videos.py" element="ensure_video_indexes: idx_videos_uuid_instance (lines 21-22)">
**What changes.** Nothing.

**Why it matters.** It disproves the plan's "No index on (video_uuid, instance_domain) is confirmed" risk. The uuid batch query can use this index. The plan's risk note should be corrected.

**Regression risk: none.**
</impact>
<impact path="engine/server/api/http_utils.py" element="read_json_body 1,000,000-byte cap (lines 46-52)">
**What changes.** Nothing.

**Why it matters.** It is the only bound on how many entries a direct bridge caller can put in one metadata body. A large body means several 450-pair statements under one lock hold, which is the same exposure the id path already has.

**Regression risk: none.**
</impact>
<impact path="engine/server/api/recommendations/keys.py" element="like_key (line 8)">
**What changes.** Nothing.

**Why it matters.** It keys the refactored id path and will likely key the handler's cross-form dedup. Its output format matches `_like_key` in internal_client_reads.py:15.

**Regression risk: none.**
</impact>
<impact path="client/backend/lib/engine_api_client.py" element="resolve_videos_by_uuid_host (lines 136-166): deleted">
**What changes.** Removed (R6).

**What depends on it.** Outside `delete_me/` and `docs/`, three sites use it: the import at `client/backend/server.py:32`, the call at `:888` (`_handle_likes_import`), and the call at `:1024` (`_handle_user_profile_likes_from_client`). No test references it.

**Regression risk: low.** A missed site is an ImportError when `server.py` is imported, which `tests/active/conftest.py:39` surfaces across the whole suite. It is also named in the historical `docs/project/security-audit/run-1/REPORT.md:277` and `findings.json`, which must not be edited.
</impact>
<impact path="client/backend/lib/engine_api_client.py" element="fetch_metadata_for_entries (lines 92-109), resolve_video_seed (66-89), _post_json (32-63)">
**What changes.**
- No logic change. `fetch_metadata_for_entries` now also carries `{video_uuid, instance_domain}` entries. Its docstring ("canonical video identity entries") could mention the uuid form.
- It returns `[]` with no HTTP call for an empty list (line 97), which the import path relies on.
- It raises `EngineApiError` on a non-200 status or a bad payload.
- `_post_json` has a 6 s timeout (line 32), which now bounds the whole likes page and the whole import, not each resolve.
- `resolve_video_seed` stays.

**Regression risk: low.**
</impact>
<impact path="client/backend/server.py" element="engine_api_client import (lines 30-32)">
**What changes.** `resolve_videos_by_uuid_host` is dropped from the import. `fetch_metadata_for_entries` and `resolve_video_seed` stay.

**Regression risk: low.** It could conflict on merge with plan 13 in the same block, so locate the edit by name.
</impact>
<impact path="client/backend/server.py" element="MAX_CLIENT_LIKES = 200 → 50 (line 52)">
**What changes.** The value.

**Readers,** found by grep outside `delete_me/` and `docs/`:
- line 493, the proxy trim;
- line 886, `_handle_likes_import`;
- line 1019, `_handle_user_profile_likes_from_client`.

No test reads it.

**Context.** It sits beside `MAX_LIKES = 100` (line 51, out of scope) and `ENGINE_FEED_LIKES_MAX = 5` (line 55). It matches the browser's `MAX_LIKES = 50` (`client/frontend/src/data/local-likes.ts:25`) and ADR-0003.

**Regression risk: low.** No `tests/active` test posts more than 50 likes; the import test posts 3.
</impact>
<impact path="client/backend/server.py" element="/recommendations and /videos/similar POST proxy likes trim (lines 487-503)">
**What changes.** No code edit. `likes[:MAX_CLIENT_LIKES]` now cuts at 50 before malformed entries are skipped.

**Context.**
- A keyed request replaces the likes with at most 5 stored ones (lines 535-541).
- The Engine answers 400 above `DEFAULT_CLIENT_LIKES_MAX` = 5 on both POST routes (`engine/server/README.md:24`). So a keyless body of 6-50 likes still gets the Engine's 400 forwarded.
- The "proxy forwards at most 50" test therefore needs a capturing stand-in Engine, not the live one.

**Regression risk: low.**
</impact>
<impact path="client/backend/server.py" element="_parse_client_likes (lines 1105-1121)">
**What changes.** No edit. It cuts to `raw[:max_items]` before validation, returns stripped `{video_uuid, instance_domain}` dicts, and does not deduplicate. Its output keys are exactly the Engine parser's uuid form, and it now feeds `fetch_metadata_for_entries` directly.

It is distinct from the Engine's `handlers/similar.py:132` `_parse_client_likes`, which `tests/active/test_similar.py:259` patches.

**Regression risk: low.** If its key names changed, the Engine would skip every entry and return an empty page without any error.
</impact>
<impact path="client/backend/server.py" element="_handle_likes_import (lines 872-900)">
**What changes.**
- Line 888 becomes one `fetch_metadata_for_entries(self.server.engine_ingest_base, likes)` call. The 502 text `Engine resolve failed: ...` (line 890) stays; plan 15 rewrites it.
- The loop over the rows keeps `is_disliked(conn, profile_id, row["video_id"], row["instance_domain"])` and `record_like(conn, profile_id, "like", {video_id, video_uuid, instance_domain}, MAX_LIKES)` inside `with conn:`. `record_like` commits on its own (users_store.py:117), as it does today.
- The response stays `{"imported": n}`.
- The recording order is the Engine's first-match order, which equals submitted order. That keeps `updated_at` recency and the `MAX_LIKES` trim the same as today.

**Behaviour changes (accepted):**
- Videos at or over the error threshold are not imported.
- Videos with a bad embedding blob are now imported.
- On a uuid collision, the lowest `video_id` wins.

**Regression risk: medium.**
- It is covered by `tests/active/test_profiles.py:245` (live Engine). That test's dataset query already filters `error_count = 0` and joins embeddings (lines 225-230), so it should stay green.
- Frontend coupling: `importLocalLikes` clears all local likes after any 2xx (`client/frontend/src/data/reactions.ts:81`). Likes past the 50th, unknown ones and errored ones are therefore lost. The browser already caps at 50.
</impact>
<impact path="client/backend/server.py" element="_handle_user_profile_likes_from_client (lines 1012-1029)">
**What changes.**
- Lines 1024-1025 become one `fetch_metadata_for_entries` call.
- The empty-parse 200 (1020-1022), the 502 `Engine metadata failed: ...` (1027) and `{"likes": rows, "updatedAt"}` stay.
- The docstring is a placeholder ("Handle handle user profile likes from client.") and could now state the one-call behaviour.

**What depends on it.** The keyless likes page: `client/frontend/src/data/user-profile.ts:20-40` posts `{likes: [{uuid, host}]}` and renders `likes` in response order.

**Regression risk: medium.** Order and dedup now rest entirely on the Engine's ordered walk. No existing test covers this POST route (a grep of `tests/active` finds no POST to `/api/user-profile/likes`). The planned stand-in-Engine tests fill that gap.
</impact>
<impact path="client/backend/server.py" element="_handle_user_profile_likes_get (995-1010) and _handle_block_add (927-963): id-form callers">
**What changes.** No edit.
- The GET sends `fetch_recent_likes` rows, which carry both `video_id` and `video_uuid`. With a non-empty id they are id form, so the rows and their order are unchanged.
- Block-add sends a single `{video_id, instance_domain}`.

**Tests.** `tests/active/test_server.py:94`, `test_blocks.py`, and `test_profiles.py` through reads.

**Regression risk: low-medium.** See the parser entry for the empty-id-plus-uuid edge case.
</impact>
<impact path="client/backend/server.py" element="_handle_user_action / _store_reaction (lines 730-870)">
**What changes.** Nothing. It still uses `resolve_video_seed` (line 758). Listed to confirm that `resolve_video_seed` must not be removed together with the batch function.

**Regression risk: none.**
</impact>
<impact path="client/backend/lib/users_store.py" element="record_like (79-117), fetch_recent_likes (120-142)">
**What changes.** Nothing.
- `record_like` reads only `video_id`, `instance_domain` and `video_uuid`, so a full metadata row or a three-key dict built from it both work.
- `fetch_recent_likes` produces the id-form GET body.

**Regression risk: none.**
</impact>
<impact path="client/backend/lib/dislikes.py" element="is_disliked">
**What changes.** Nothing. It is now called with the metadata row's `video_id` and `instance_domain` rather than the resolved entry's. The values are the same.

**Regression risk: none.**
</impact>
<impact path="client/frontend/src/data/local-likes.ts" element="MAX_LIKES = 50 (line 25)">
**What changes.** Nothing; the frontend is out of scope. It is the bound ADR-0003 aligns to. The built bundle `client/frontend/dist/assets/key-rejected-*.js` carries `S=50`.

**Regression risk: none.**
</impact>
<impact path="client/frontend/src/data/reactions.ts" element="importLocalLikes (lines 65-83)">
**What changes.** Nothing. It posts every local like and clears local storage on success (line 81), so likes the server drops or cannot resolve are cleared too.

**Regression risk: low.**
</impact>
<impact path="client/frontend/src/data/user-profile.ts" element="fetchUserProfileLikes keyless branch (lines 20-40)">
**What changes.** Nothing. It depends on the response order matching the submitted order.

**Regression risk: low.**
</impact>
<impact path="tests/active/test_profiles.py" element="test_importing_browser_likes_marks_each_imported_video_liked_and_no_other (line 245) and _embedded_videos (225-232)">
**What changes.** No edit expected. It must stay green, running against the live Engine in its own `validate_tests.py` invocation.

**Regression risk: low.**
</impact>
<impact path="tests/active/test_server.py" element="test_a_keyed_request_s_500_entry_exclude... (line 86; GET likes at line 94)">
**What changes.** No edit. It exercises the id-form metadata path end to end, and it is the existing check that id callers are unchanged. It runs in its own invocation.

**Regression risk: low.**
</impact>
<impact path="tests/active/test_dislike_profile.py" element="/internal/dislikes/centroids tests">
**What changes.** No edit. It guards `_parse_entries` and centroids. The new centroids-ignores-uuid check can live here or in the new Engine test file.

**Regression risk: low.**
</impact>
<impact path="tests/active/test_blocks.py" element="block-add tests">
**What changes.** No edit. It exercises resolve plus a single-entry id-form metadata call against the live Engine.

**Regression risk: low.**
</impact>
<impact path="tests/active/conftest.py" element="ENGINE_PY (30), client_backend (69-89), _engine_client (156-176), engine fixture (101-137)">
**What changes.** Probably no edit.
- The `ClientBackendServer(..., engine_base, ...)` construction is the seam for pointing a Client at a capturing stand-in Engine.
- `ClientBackend` exposes only `base` and `db_path`, so the new Client tests must build their own server. Alternatively a fixture can be added, but a fixture here is shared by every file.

**Regression risk: low.**
</impact>
<impact path="tests/active/test_internal_events.py" element="in-process data imports (25-36) and ENGINE_PY -c child (42-60, 173)">
**What changes.** Nothing. It is the right precedent for the new tests:
- in-process `data.*` imports with `engine/server` and `engine/server/api` on `sys.path`, for the metadata data functions;
- an `ENGINE_PY -c` child with `cwd=API_DIR` for the numpy-importing handler, patching `read_json_body`/`respond_json` on the handler module and handing it a stand-in server.

**Correction to the plan.** The plan cites `test_db.py`, but `test_db.py:81` runs its child with `sys.executable`, not `ENGINE_PY`. `tests/active/test_similar.py:288-289` is the other `ENGINE_PY` child precedent.

**Regression risk: none.**
</impact>
<impact path="tests/active/test_db.py" element="cited by the plan as the test pattern">
**What changes.** Nothing. It is listed only because the plan names it as the pattern, and it is the wrong one: it uses `sys.executable` and imports only `data.db`.

**Regression risk: none.**
</impact>
<impact path="tests/tmp/ (new Engine and Client test files)">
**What changes.** New tests.

**Engine data layer, in-process:**
- id output unchanged;
- the uuid lookup;
- lowest `video_id`;
- the threshold on the uuid form.

**Engine handler, `ENGINE_PY` child:**
- parser forms and dedup;
- mixed forms;
- the same video once;
- one lock enter, using a counting `db_lock`;
- centroids ignores uuid.

**Client, stdlib stand-in Engine:**
- one call per request;
- 60 entries reach the Engine as 50;
- the proxy forwards at most 50;
- unknown videos are omitted;
- disliked videos are skipped on import.

**Risks.**
- The temp schema must include `videos` with every selected column plus `error_count` and `video_uuid`, `video_embeddings` with `embedding_dim` and `model_name`, and `channels` with `display_name` and `avatar_url`.
- `video_embeddings` should have its real `(video_id, instance_domain)` primary key.
- The stand-in Engine must answer `/internal/videos/metadata` and record the bodies.
</impact>
<impact path="tests/last_test_validation.json" element="tracked test record (and tests/last_test_output.txt)">
**What changes.** Regenerated by the runs. It conflicts on merge: take main's copy and re-run `--compare`.

**Regression risk: merge-process only.**
</impact>
<impact path="delete_me/ (server.py.bak-* and similar stale copies)">
**What changes.** Nothing. These files match greps for `resolve_videos_by_uuid_host` and `MAX_CLIENT_LIKES`, but they are not imported. Do not edit them and do not count them as readers.

**Regression risk: none.**
</impact>
</impacts>


## Documentation to update

- [x] `client/README.md` - updated: I added the 50-entry cap and the single Engine metadata call to the two browser-likes endpoints in `client/README.md`, and the cap to the feed-proxy `likes` note.
- [x] `engine/server/README.md` - updated: `engine/server/README.md`: the `/internal/videos/metadata` entry now describes both entry forms and how they are answered, and the `/internal/dislikes/centroids` entry says it takes id-form entries only.
- [x] `docs/project/adr/0003-metadata-endpoint-accepts-uuid-entries.md` - updated: I added two bullets to the ADR-0003 Consequences for the two approved differences from the old resolve path: the lowest-`video_id` tie-break, and no embedding-blob check.
- [x] `docs/project/issues/03-batch-like-resolution.md` - updated: Issue 03 is now `bug, complete` and has a delivery comment, but I couldn't move it to `issues/archive/` because I have no delete or move tool.
- [x] `docs/project/plans/14-batch-like-resolution.md` - updated: No edit: plan 14 needs no text correction, and archiving it is a harvest-time move on main.
- [x] `docs/project/plans/16-14-batch-like-resolution.md` - updated: I made the four listed corrections to the plan text of `docs/project/plans/16-14-batch-like-resolution.md` and checked each against the worktree code.

## Implementation plan

## Draft implementation: batch like resolution (plan 14, issue 03)

This draft converged on the first pass against the plan and R1 to R7. The pass-by-pass check is at the end. All paths are relative to the worktree `/home/enduser/code/PeerTube-browser/.worktrees/fix-14-batch-like-resolution`.

### Module map

| File | Change |
|---|---|
| `engine/server/data/metadata.py` | New private `_select_metadata` (the SELECT, the joins, the error clause, the row dict). `fetch_metadata_by_ids` becomes a thin caller of it. New `fetch_metadata_by_uuids` and private `_uuid_key`. `fetch_metadata` (lines 11-102) and `_chunk` are untouched. |
| `engine/server/api/handlers/internal_client_reads.py` | Import line 9 widened. New `_uuid_key` and `_parse_metadata_entries`. `handle_internal_videos_metadata` rewritten. `_parse_entries`, centroids and resolve are untouched. |
| `client/backend/lib/engine_api_client.py` | `resolve_videos_by_uuid_host` deleted. The `fetch_metadata_for_entries` docstring now names both entry forms. |
| `client/backend/server.py` | Import (lines 30-32), `MAX_CLIENT_LIKES = 50`, `_handle_likes_import`, `_handle_user_profile_likes_from_client`. The proxy trim at line 493 is unchanged in code. |
| `tests/tmp/test_metadata_uuid_entries.py` | New. Tests for the Engine data layer (in-process) and the handler (an `ENGINE_PY` child). |
| `tests/tmp/test_client_like_batching.py` | New. Client tests against a capturing stand-in Engine. |

No new dependency, endpoint or module outside the tests.

---

### 1. `engine/server/data/metadata.py`

**`_select_metadata(conn, where, params, error_threshold) -> list[dict[str, Any]]`**
- It is shared by exactly two callers, so it is not a single-implementation abstraction.
- **Invariant:** it builds a fresh parameter list per call, so the threshold is appended once per chunk and always last.
- **Invariant:** it builds the row dict in one place only, so a video's row is identical whichever form reached it.
- It never takes `db_lock`.

```python
def _select_metadata(
    conn: sqlite3.Connection,
    where: str,
    params: list[Any],
    error_threshold: int | None,
) -> list[dict[str, Any]]:
    """Run the metadata SELECT for one chunk's WHERE fragment and return the built row dicts."""
    query_params = list(params)
    error_clause = ""
    if error_threshold is not None and error_threshold > 0:
        error_clause = "AND (v.error_count IS NULL OR v.error_count < ?)"
        query_params.append(error_threshold)
    rows = conn.execute(
        f"""
        SELECT
          v.video_id,
          ... (lines 134-162 verbatim, 29 columns) ...
          e.model_name
        FROM video_embeddings e
        JOIN videos v
          ON v.video_id = e.video_id AND v.instance_domain = e.instance_domain
        LEFT JOIN channels c
          ON c.channel_id = v.channel_id AND c.instance_domain = v.instance_domain
        WHERE {where}
          {error_clause}
        """,
        query_params,
    ).fetchall()
    return [
        {
            "video_id": row["video_id"],
            ... (lines 175-203 verbatim, 29 keys) ...
            "model_name": row["model_name"],
        }
        for row in rows
    ]
```

The WHERE fragment is wrapped as `WHERE ({where})`, in parentheses, so that the `AND` error clause binds to the whole `OR` chain. In today's SQL, `WHERE a OR b AND (err)` binds `AND` tighter than `OR`. That means the existing id query applies the threshold only to the last pair of each chunk.

This is a live pre-existing bug on the id path, and it would change R3's "id callers see exactly the rows they saw before". **See "Open item A" below: the draft does not silently pick one side.**

**`fetch_metadata_by_ids`**

The signature, the early return, the 450-entry chunks, and the params from `entry.get("video_id")` / `entry.get("instance_domain") or ""` all stay the same.

```python
def fetch_metadata_by_ids(
    conn: sqlite3.Connection,
    entries: list[dict[str, Any]],
    error_threshold: int | None = None,
) -> dict[str, dict[str, Any]]:
    """Fetch video metadata for (video_id, instance_domain) pairs."""
    if not entries:
        return {}
    result: dict[str, dict[str, Any]] = {}
    for batch in _chunk(entries, 450):
        conditions = " OR ".join(["(v.video_id = ? AND v.instance_domain = ?)"] * len(batch))
        params: list[Any] = []
        for entry in batch:
            params.append(entry.get("video_id"))
            params.append(entry.get("instance_domain") or "")
        for row in _select_metadata(conn, conditions, params, error_threshold):
            result[like_key(row)] = row
    return result
```

`similarity_candidates._build_rows` keeps working unchanged. It reads the same keys and gets the same dicts, keyed by `like_key`.

**`fetch_metadata_by_uuids`**

```python
def _uuid_key(entry: dict[str, Any]) -> str:
    """Handle uuid key."""
    return f"{entry.get('video_uuid') or ''}::{entry.get('instance_domain') or ''}"


def fetch_metadata_by_uuids(
    conn: sqlite3.Connection,
    entries: list[dict[str, Any]],
    error_threshold: int | None = None,
) -> dict[str, dict[str, Any]]:
    """Fetch video metadata for (video_uuid, instance_domain) pairs, one row per pair.

    The match is exact on both columns. Where several videos share a pair, the one with the lowest
    video_id among those under the error threshold is kept.
    """
    pairs: dict[str, tuple[str, str]] = {}
    for entry in entries:
        pair = (str(entry.get("video_uuid") or ""), str(entry.get("instance_domain") or ""))
        pairs.setdefault(_uuid_key({"video_uuid": pair[0], "instance_domain": pair[1]}), pair)
    if not pairs:
        return {}
    result: dict[str, dict[str, Any]] = {}
    for batch in _chunk(list(pairs.values()), 450):
        placeholders = ", ".join(["(?, ?)"] * len(batch))
        params = [value for pair in batch for value in pair]
        for row in _select_metadata(conn, f"(v.video_uuid, v.instance_domain) IN ({placeholders})", params, error_threshold):
            key = _uuid_key(row)
            if key not in result or row["video_id"] < result[key]["video_id"]:
                result[key] = row
    return result
```

**Decision: pick the lowest id in Python rather than with `ORDER BY`.** The impact entry allows it ("or the uuid caller must sort in Python").
- The helper then needs no ordering parameter, and the id query is not given a useless sort.
- The pick does not depend on row order or on chunking.
- SQLite's BINARY collation compares UTF-8 bytes. Byte order equals code-point order, which is how Python orders `str`, so "lowest `video_id`" means the same in both.

**Other invariants:**
- 450 pairs is 900 values plus 1 threshold, under 999.
- `video_embeddings` has `PRIMARY KEY (video_id, instance_domain)` (`sync-whitelist.py:391`), so the inner join cannot fan out.
- The query can use `idx_videos_uuid_instance` (`data/videos.py:21`).

---

### 2. `engine/server/api/handlers/internal_client_reads.py`

Line 9:
```python
from data.metadata import fetch_metadata_by_ids, fetch_metadata_by_uuids
```

**New helpers beside `_like_key` and `_parse_entries`.** `_uuid_key` duplicates the private one in `metadata.py` on purpose. The file already mirrors `recommendations.keys.like_key` with its own `_like_key`, and the settled import line names only the two fetch functions. A drift between the two copies fails the mixed-forms test.

```python
def _uuid_key(entry: dict[str, Any]) -> str:
    """Handle uuid key."""
    return f"{entry.get('video_uuid') or ''}::{entry.get('instance_domain') or ''}"


def _stripped(value: Any) -> str | None:
    """Return a non-empty stripped string, or None."""
    return value.strip() or None if isinstance(value, str) else None


def _parse_metadata_entries(body: Any) -> list[tuple[str, dict[str, str]]] | None:
    """Return the distinct well-formed metadata entries of a body, tagged "id" or "uuid", in order.

    An item with a valid video_id is id-keyed even if it also carries video_uuid; duplicates are
    dropped per form, keeping the first.
    :returns: None when `entries` is not a list; malformed items are skipped.
    """
    raw_entries = body.get("entries") if isinstance(body, dict) else None
    if not isinstance(raw_entries, list):
        return None
    entries: list[tuple[str, dict[str, str]]] = []
    seen: set[tuple[str, str]] = set()
    for raw in raw_entries:
        if not isinstance(raw, dict):
            continue
        instance = _stripped(raw.get("instance_domain"))
        if instance is None:
            continue
        video_id = _stripped(raw.get("video_id"))
        video_uuid = _stripped(raw.get("video_uuid"))
        if video_id is not None:
            form, entry = "id", {"video_id": video_id, "instance_domain": instance}
            key = _like_key(entry)
        elif video_uuid is not None:
            form, entry = "uuid", {"video_uuid": video_uuid, "instance_domain": instance}
            key = _uuid_key(entry)
        else:
            continue
        if (form, key) in seen:
            continue
        seen.add((form, key))
        entries.append((form, entry))
    return entries
```

Two notes on the helpers:
- `_stripped` binds as `(value.strip() or None) if ... else None`. The parenthesised form is what gets written.
- Tagging the seen-set with the form keeps the id and uuid key spaces apart, since both are `x::y` strings.

**Handler**

```python
def handle_internal_videos_metadata(handler: Any, server: Any) -> bool:
    """Return metadata rows for (video_id, instance_domain) and (video_uuid, instance_domain) entries.

    Both forms are answered under one db_lock hold; each video appears once, at its first matching entry.
    """
    try:
        body = read_json_body(handler)
    except ValueError as exc:
        respond_json(handler, 400, {"error": str(exc)})
        return True

    entries = _parse_metadata_entries(body)
    if entries is None:
        respond_json(handler, 400, {"error": "Missing entries"})
        return True

    if not entries:
        respond_json(handler, 200, {"ok": True, "count": 0, "rows": []})
        return True

    id_entries = [entry for form, entry in entries if form == "id"]
    uuid_entries = [entry for form, entry in entries if form == "uuid"]
    error_threshold = getattr(server, "video_error_threshold", None)
    by_id: dict[str, dict[str, Any]] = {}
    by_uuid: dict[str, dict[str, Any]] = {}
    with server.db_lock:
        if id_entries:
            by_id = fetch_metadata_by_ids(server.db, id_entries, error_threshold=error_threshold)
        if uuid_entries:
            by_uuid = fetch_metadata_by_uuids(server.db, uuid_entries, error_threshold=error_threshold)

    rows: list[dict[str, Any]] = []
    emitted: set[str] = set()
    for form, entry in entries:
        row = by_id.get(_like_key(entry)) if form == "id" else by_uuid.get(_uuid_key(entry))
        if not isinstance(row, dict) or _like_key(row) in emitted:
            continue
        emitted.add(_like_key(row))
        rows.append(row)

    respond_json(handler, 200, {"ok": True, "count": len(rows), "rows": rows})
    return True
```

**Why id-only callers see no change.**
- An id-only request produces exactly the `_parse_entries` list, the same query, and the same entry-order walk.
- `emitted` cannot drop a row here, because the parser has already deduplicated on the same key.

**Deduplication across forms.** It keys on the returned row's `video_id::instance_domain`, never on the entry.

---

### 3. `client/backend/lib/engine_api_client.py`

- Delete lines 136-166 (`resolve_videos_by_uuid_host`). `resolve_video_seed` stays.
- New docstring for `fetch_metadata_for_entries`: `"""Fetch metadata rows from Engine for {video_id|video_uuid, instance_domain} entries, one row per video in first-entry order."""`
- No logic change. An empty list still returns `[]` with no HTTP call.

---

### 4. `client/backend/server.py`

**Import (lines 30-32):**
```python
from lib.engine_api_client import (EngineApiError, bridge_headers, compute_dislike_centroids,
                                   fetch_metadata_for_entries, resolve_video_seed)
```

**Cap (line 52):** `MAX_CLIENT_LIKES = 50`.
- The grep found three readers: the proxy trim (line 493) and the two `_parse_client_likes` calls.
- Matches in `delete_me/*.bak-*` are ignored.

**`_handle_likes_import`**: from the `likes = ...` line on.
- There is no pre-call empty check: `fetch_metadata_for_entries` returns `[]` for an empty list without calling the Engine, so the answer is `{"imported": 0}` as today.

```python
        likes = _parse_client_likes(body, MAX_CLIENT_LIKES)
        try:
            rows = fetch_metadata_for_entries(self.server.engine_ingest_base, likes)
        except EngineApiError as exc:
            respond_json(self, 502, {"error": f"Engine resolve failed: {exc}"})
            return
        conn = self.server.user_db
        imported = 0
        with conn:
            for row in rows:
                if is_disliked(conn, profile_id, row["video_id"], row["instance_domain"]):
                    continue
                video = {"video_id": row["video_id"], "video_uuid": row["video_uuid"], "instance_domain": row["instance_domain"]}
                record_like(conn, profile_id, "like", video, MAX_LIKES)
                imported += 1
        respond_json(self, 200, {"imported": imported})
```

**`_handle_user_profile_likes_from_client`**:

```python
    def _handle_user_profile_likes_from_client(self) -> None:
        """Answer a browser's local likes (uuid, host) with Engine metadata rows in one Engine call, deduplicated, in submitted order; unknown videos are omitted."""
        ...
        likes = _parse_client_likes(body, MAX_CLIENT_LIKES)
        if not likes:
            respond_json(self, 200, {"likes": [], "updatedAt": now_ms()})
            return
        try:
            rows = fetch_metadata_for_entries(self.server.engine_ingest_base, likes)
        except EngineApiError as exc:
            respond_json(self, 502, {"error": f"Engine metadata failed: {exc}"})
            return
        respond_json(self, 200, {"likes": rows, "updatedAt": now_ms()})
```

The proxy code is unchanged. `_parse_client_likes` is unchanged; its output keys are exactly the Engine's uuid form.

---

### 5. Tests

#### `tests/tmp/test_metadata_uuid_entries.py`

**Setup**
- `sys.path` gets `engine/server` and `engine/server/api`, as `test_internal_events.py:25-30` does. It then does `from data.metadata import fetch_metadata_by_ids, fetch_metadata_by_uuids` in-process: that module imports no numpy.
- The handler part runs in an `ENGINE_PY -c` child with `cwd=API_DIR`. The child inserts the same two paths itself.
- Correction to the plan: the pattern is `test_internal_events.py` / `test_similar.py`, not `test_db.py`.

**Temp schema** (`row_factory = sqlite3.Row`):
- `videos`: the 26 selected `v.*` columns, plus `error_count INTEGER`, with `PRIMARY KEY (video_id, instance_domain)`.
- `video_embeddings (video_id, instance_domain, embedding BLOB, embedding_dim, model_name, PRIMARY KEY (video_id, instance_domain))`.
- `channels (channel_id, instance_domain, display_name, avatar_url)`.
- It does not call `ensure_video_indexes`; the index does not affect correctness.

**Fixture videos**, all on host `h.example` unless noted:

| video_id | video_uuid | error_count | embedding | purpose |
|---|---|---|---|---|
| a1 | u-a | 0 | yes | plain match |
| b1 | u-b | NULL | yes | id and uuid paths reach the same video |
| s2 (inserted first) | u-s | 0 | yes | shared pair: rowid order is not id order |
| s1 | u-s | 0 → later 5 | yes | lowest id; errored sibling |
| e1 | u-e | 5 | yes | over threshold 3 |
| n1 | u-n | 0 | **no** | inner join drops it |
| a1 on `other.example` | u-a | 0 | yes | exact host match |

**Data-layer tests (in-process)**
1. `fetch_metadata_by_ids` returns exactly the 29-key dict, keyed `a1::h.example`, with the values from the DB. It skips `n1`, and with threshold 3 it skips `e1`. The empty list gives `{}`.
2. A 460-video set crosses the 450 chunk boundary on both functions with threshold 3. All 460 come back. The set includes one errored video in the second chunk, which must be absent; that catches a threshold parameter appended once per call.
3. `fetch_metadata_by_uuids`:
   - `u-a@h.example` gives `a1@h.example`, not the `other.example` one.
   - `U-A` and `u-a@H.EXAMPLE` give nothing.
   - `u-s` gives `s1`. After setting `s1.error_count = 5` with threshold 3, it gives `s2`.
   - `u-e` gives nothing at threshold 3, and `e1` at threshold None.
   - `u-n` gives nothing.
   - The empty list gives `{}` and runs no query: the conn is wrapped so `execute` counts calls.
4. The same video gives an identical dict through `by_ids[b1::h]` and `by_uuids[u-b::h]`.

**Handler tests (one `ENGINE_PY` child per test group)**
- The child patches `read_json_body` and `respond_json` on `handlers.internal_client_reads`.
- Its server is `SimpleNamespace(db=conn, db_lock=CountingLock(), video_error_threshold=3)`. `CountingLock` wraps `threading.Lock` and counts `__enter__`.
- It prints `[{status, payload, enters}]` for a list of bodies.

Cases:
- Parser forms: an id item with a whitespace uuid; a uuid-only item; an item with both keys (id wins, shown by an id that differs from the uuid's video); a non-dict item; a missing or blank `instance_domain`; neither key; duplicates in each form.
- `{"entries": "x"}` and `{}` give 400 `Missing entries`, with `enters == 0`.
- All-malformed entries give 200 `{"ok": True, "count": 0, "rows": []}`, with `enters == 0`.
- Id-only `[a1, b1, a1]` gives rows `[a1, b1]`, `count == 2` and `enters == 1`: the same as the old loop.
- Mixed `[uuid u-b, id a1, id b1, uuid u-a, uuid u-x]` gives `[b1, a1]`: first-match order, each video once, unknown omitted, `enters == 1`.
- Uuid `u-e` at threshold 3 is absent.
- Centroids: `fetch_embeddings_by_ids` is spied (wraps). A uuid-only body gives 200, the spy gets `[]`, and `centroids == []`. A mixed body passes only the id entries.

#### `tests/tmp/test_client_like_batching.py`

**Seam**
- A `ThreadingHTTPServer` stand-in Engine, written like `test_server.py:307`'s `EngineStub`. It records `(path, json body)` for every POST.
- For `/internal/videos/metadata` it answers from a canned `{uuid::host: row}` table in entry order, omitting unknown entries and duplicates, which mimics the Engine.
- For any other path it answers `{"rows": []}`.
- The Client is built by local `_serving` and `_client_backend` copies of `test_server.py:251-271`, with `RateLimiter(1000, 60)`.

**Tests**
1. Likes page: 3 likes plus a duplicate plus an unknown give exactly one recorded Engine request, to `/internal/videos/metadata`. Its `entries` equal the `{video_uuid, instance_domain}` list as submitted (the Client does not dedup). The response `likes` holds the known rows in submitted order, with the unknown omitted.
2. Likes page with 60 entries: 200, and the single request carries exactly the first 50.
3. Likes page with an empty or all-malformed body: 200, `likes == []`, and zero Engine requests.
4. Import: mint via `POST /api/profile`, then find `profile_id` via `resolve_profile(conn, key)` on a second connection to `users.db`. Write one dislike with `write_dislike(conn, profile_id, {...}, None)` and commit. Post 3 likes: the disliked video, a clean one, and an unknown one. This gives exactly one Engine request, `{"imported": 1}`, and `load_liked_keys(conn, profile_id) == {(clean_id, host)}`.
5. Import with 60 entries: 200, and the one request carries 50.
6. Proxy: a keyless `POST /recommendations` with 60 `{uuid, host}` likes. The recorded forwarded body has `likes` of length 50, equal to the first 50 sanitised.

`test_profiles.py` and `test_server.py` stay unedited. They run against the live Engine, each in its own `validate_tests.py` invocation.

---

### Open item A — needs a call before the build

**The problem.** The existing id SQL is `WHERE (a) OR (b) ... AND (v.error_count IS NULL OR v.error_count < ?)`. SQL gives `AND` higher precedence than `OR`, so today the threshold filters only the last pair of each chunk. Any other errored video requested by id is returned.

The settled requirements pull two ways:
- R3 says "id callers see exactly the rows they saw before".
- R2 says the uuid form uses "the same error-count threshold clause".

**Options:**
1. Keep today's id semantics exactly: the id caller passes an unparenthesised fragment. The uuid fragment is a single `IN` term, so its threshold applies to every row either way.
2. Parenthesise, and fix the id path as well. That changes what id callers see: errored videos would drop from the GET likes page, block-add and similar or up-next.

**The draft takes option 1 in code.** `_select_metadata` interpolates `WHERE {where}` without wrapping it, which matches R3 literally, and the uuid path is still fully filtered. I flag option 2 as a separate bug for the roadmap rather than fixing it silently here.

**The test consequence.** The "errored video in chunk 2" test in 5.1 item 2 applies to `fetch_metadata_by_uuids` only. For `fetch_metadata_by_ids`, the chunk-crossing test asserts all non-errored rows are present and pins current behaviour with no assertion on the errored one.

---

### Corrections to the settled plan text (for the doc step)
- **Missing index:** wrong. `idx_videos_uuid_instance` exists (`engine/server/data/videos.py:21-22`) and is created on every start.
- **Test pattern:** `test_internal_events.py` / `test_similar.py`, not `test_db.py`. The data-layer tests run in-process.
- **Id-path threshold precedence:** see Open item A. The plan's claim that the error clause is "applied in SQL before the pick" holds for the uuid path only.
- **Tests in `tests/tmp` import `conftest`:** they rely on `tests/active/conftest.py` for `ENGINE_PY`, `client_server`, `RateLimiter` and `ensure_user_schema`. I did not verify how `validate_tests.py` puts that on `sys.path` for the working tree. If it does not, the files are promoted to `tests/active` before running.

### Check against plan and requirements (pass 1, converged)
- **R1:**
  - `_parse_metadata_entries`: id wins when both keys are present.
  - It deduplicates per form.
  - It returns None, which gives 400.
  - An empty parse answers 200 before the lock.
  - `_parse_entries` and centroids are untouched.
- **R2:**
  - `fetch_metadata_by_uuids` has the same SELECT, joins, threshold and row dict via `_select_metadata`.
  - It uses a row-value `IN` in 450-pair chunks.
  - The match is exact.
  - It returns one row per pair, the lowest `video_id`.
  - There is no blob check.
- **R3:**
  - One `with server.db_lock:` covers both lookups.
  - Rows are emitted in first-match order and deduplicated on the row's `like_key`.
  - The threshold applies to both forms.
  - The response shape is unchanged.
  - Id-only requests are unchanged, including the precedence quirk (Open item A).
- **R4 and R5:** one `fetch_metadata_for_entries` call each. Deduplication is left to the Engine. The 502 texts are kept. Import records from the row fields and skips disliked videos.
- **R6:** the function is deleted and its import dropped. `resolve_video_seed` is kept.
- **R7:** the constant is 50. All three readers slice before validating.
- **Acceptance criteria:** each is covered by a test in section 5. The lock count is read through `CountingLock`, and the Engine call count through the stand-in Engine.


### Phases

#### Phase 1 - Engine uuid-keyed metadata lookup [code]

**Files touched.** engine/server/data/metadata.py (EDITED), tests/tmp/test_metadata_uuid_entries.py (NEW)

**Checkpoint.** Seam: the data-layer functions `fetch_metadata_by_ids` and `fetch_metadata_by_uuids` in `engine/server/data/metadata.py`, called in-process against a temp SQLite DB (`row_factory = sqlite3.Row`). The DB has `videos` (26 selected columns plus `error_count`, PK `(video_id, instance_domain)`), `video_embeddings` (PK `(video_id, instance_domain)`) and `channels`. Harness: the `sys.path` insertion of `engine/server` and `engine/server/api` from `tests/active/test_internal_events.py:25-30`. `data.metadata` imports no numpy, so no child process is needed. The file lives in `tests/tmp` and needs `tests/active` on `sys.path` before any `from conftest import ...`. Fixtures come from the draft's table: a1, b1, s2 inserted before s1, e1, n1 with no embedding, and a1 on other.example. Asserts, clause 1: `fetch_metadata_by_uuids(conn, [{video_uuid: "u-b", instance_domain: "h.example"}])["u-b::h.example"] == fetch_metadata_by_ids(conn, [{video_id: "b1", instance_domain: "h.example"}])["b1::h.example"]`, and the dict holds exactly the 29 keys. `u-a@h.example` gives the h.example a1, not the other.example one. `U-A` and `u-a@H.EXAMPLE` give nothing. `u-n` gives nothing. An empty list gives `{}` with zero `execute` calls, counted through a wrapped conn. Asserts, clause 2: `u-s` gives `s1`. After `s1.error_count = 5` with threshold 3 it gives `s2`. `u-e` is absent at threshold 3 and present at threshold None. Regression pins with no clause of their own: `fetch_metadata_by_ids` output for a1, n1 skipped, and a 460-video set crossing the 450 chunk boundary on both functions with threshold 3. Every non-errored video comes back. On the uuid path, an errored video in chunk 2 is absent. On the id path there is no assertion on that errored video, because Open item A option 1 keeps today's AND/OR precedence.

**Intent.** `engine/server/data/metadata.py` fetches metadata rows by exact `(video_uuid, instance_domain)` pair through `fetch_metadata_by_uuids`. It uses the same SELECT and row builder (`_select_metadata`) as `fetch_metadata_by_ids` and yields one row per pair: the lowest eligible `video_id`.

- C1 - `fetch_metadata_by_uuids` returns, for an exact `(video_uuid, instance_domain)` match, the same row dict that `fetch_metadata_by_ids` returns for that video.
- C2 - Where several videos share one `(video_uuid, instance_domain)`, the row kept is the one with the lowest `video_id` among those under the error threshold.

**Outcome.** ### `engine/server/data/metadata.py`

- **New `_select_metadata(conn, conditions, params, error_threshold)`:** holds the joined SELECT (`video_embeddings` JOIN `videos` LEFT JOIN `channels`) and the 29-key row builder that used to live inline in `fetch_metadata_by_ids`. It appends the `error_count IS NULL OR error_count < ?` clause when `error_threshold > 0`, the same rule as before. It works on a copy of `params` and returns a list of row dicts.
- **`fetch_metadata_by_ids`:** still splits the input into chunks of 450 and builds the same OR-of-pairs condition, but now gets its rows from `_select_metadata` and keys them with `like_key`, as before. Its conditions are passed without parentheses on purpose, so the threshold still applies only to the last pair of each chunk (Open item A, option 1). This behaviour is unchanged, and a one-line comment explains why.
- **New `fetch_metadata_by_uuids(conn, entries, error_threshold=None)`:**
  - Returns `{}` for an empty list without running any SQL.
  - Otherwise splits the input into chunks of 450, builds `(v.video_uuid = ? AND v.instance_domain = ?)` joined with OR, and passes it to `_select_metadata` wrapped in parentheses, so the threshold applies to every pair.
  - Keys rows as `"{video_uuid}::{instance_domain}"`. Where several videos share a pair, it keeps the row with the lowest `video_id` among those the threshold lets through (C2).
  - Matching is exact and case-sensitive, from SQLite's default BINARY `=`.
  - An unembedded video is dropped by the inner join, as in the id path.
- **Not changed:** `fetch_metadata` (the rowid lookup).

### `tests/tmp/test_metadata_uuid_entries.py`

Not created. The phase lists it as a new file, but the checkpoint already covers everything this phase does (see `inner_tests`).

#### Phase 2 - Engine metadata endpoint accepts both entry forms [code]

**Files touched.** engine/server/api/handlers/internal_client_reads.py (EDITED), tests/tmp/test_metadata_uuid_entries.py (EDITED)

**Checkpoint.** Seam: `handlers.internal_client_reads.handle_internal_videos_metadata(handler, server)`, entered in an `ENGINE_PY -c` child with `cwd=API_DIR`. The module imports numpy, so it cannot run in the pytest interpreter. Harness: the child pattern of `tests/active/test_internal_events.py:173` and `tests/active/test_similar.py:288-289`. The child patches `read_json_body` and `respond_json` on the handler module. It passes `SimpleNamespace(db=conn, db_lock=CountingLock(), video_error_threshold=3)`, where `CountingLock` wraps `threading.Lock` and counts `__enter__`, and prints `[{status, payload, enters}]` per body. It uses the same temp DB as phase 1. Asserts, clause 1: the mixed body `[uuid u-b, id a1, id b1, uuid u-a, uuid u-x]` gives `enters == 1`. Id-only `[a1, b1, a1]` gives `enters == 1`. Asserts, clause 2: the mixed body gives rows `[b1, a1]` with `count == 2`, each video once in first-match order and the unknown omitted. Id-only `[a1, b1, a1]` gives `[a1, b1]`. An item carrying both a valid `video_id` and a `video_uuid` of a different video resolves to the id's video. Per-form duplicates collapse. Uuid `u-e` is absent at threshold 3. Guards: `{"entries": "x"}` and `{}` give 400 `Missing entries` with `enters == 0`. An all-malformed body (non-dict, blank `instance_domain`, neither key) gives 200 `{"ok": True, "count": 0, "rows": []}` with `enters == 0`. On `/internal/dislikes/centroids`, with `fetch_embeddings_by_ids` spied: a uuid-only body passes `[]` and returns `centroids == []`, and a mixed body passes only the id entries.

**Intent.** `handle_internal_videos_metadata` in `engine/server/api/handlers/internal_client_reads.py` parses id-form and uuid-form entries with its own parser. It answers all of them in a single `db_lock` hold and emits each matched video once, at its first matching entry.

- C1 - A request body mixing id-form and uuid-form entries acquires `db_lock` exactly once.
- C2 - Each matched video appears once in `rows`, in the order of its first matching entry.

**Outcome.** ### `engine/server/api/handlers/internal_client_reads.py`
- Line 9 now imports `fetch_metadata_by_uuids` alongside `fetch_metadata_by_ids`.
- Three new helpers sit next to `_like_key` and `_parse_entries`, written as the plan sets them out:
  - `_uuid_key` builds the `video_uuid::instance_domain` key. It matches the key `fetch_metadata_by_uuids` builds its result dict with.
  - `_stripped` returns a stripped string, or None when the value is blank or not a string.
  - `_parse_metadata_entries` returns None when `entries` is not a list. It skips items that are not a dict or have no valid stripped `instance_domain`. An item with a valid `video_id` counts as the id form even when it also carries a `video_uuid`; otherwise a valid `video_uuid` makes it the uuid form, and an item with neither is skipped. It drops duplicates within each form, keeping the first, and returns one ordered list of `(form, entry)` pairs. The form is part of the duplicate key so id keys and uuid keys cannot collide.
- `handle_internal_videos_metadata`:
  - It now uses the new parser. The 400 `Missing entries` answer and the empty 200 answered before any lock are kept.
  - It splits the parsed entries into id entries and uuid entries. Inside one `with server.db_lock:` it calls `fetch_metadata_by_ids` and/or `fetch_metadata_by_uuids`, skipping a call when its list is empty, and both get the same `video_error_threshold`.
  - After the lock is released, it walks the entries in order and looks each one up in the dict for its own form. It emits a row only the first time it sees that row's `video_id::instance_domain`, so each video appears once, at its first matching entry.
  - The response shape is unchanged. The docstring is updated.
- `_like_key`, `_parse_entries`, `handle_internal_video_resolve` and `handle_internal_dislike_centroids` are not changed, so centroids still accepts only id-form entries.

### `tests/tmp/test_metadata_uuid_entries.py`
Not changed. The files list marks it EDITED, but the file does not exist in the worktree: the phase 1 checkpoint landed as `tests/tmp/test_14_batch_like_resolution_phase1.py`. The phase 2 checkpoint covers this phase on its own, so I did not create this file.

#### Phase 3 - Client resolves likes in one Engine call [code]

**Files touched.** client/backend/server.py (EDITED), client/backend/lib/engine_api_client.py (EDITED), tests/tmp/test_client_like_batching.py (NEW)

**Checkpoint.** Seam: the Client HTTP boundary. Requests go to `POST /api/user-profile/likes` and `POST /api/profile/likes/import` on a locally built `ClientBackendServer`, whose `engine_ingest_base` points at a capturing stand-in Engine. The stand-in is a stdlib `ThreadingHTTPServer` written like `EngineStub` at `tests/active/test_server.py:307`. It records `(path, json body)` for every POST. On `/internal/videos/metadata` it answers from a canned `{uuid::host: row}` table in entry order, omitting unknown entries and duplicates. Local `_serving` and `_client_backend` copies of `test_server.py:251-271` build the Client, with `RateLimiter(1000, 60)`. The file needs `tests/active` on `sys.path` before `from conftest import ...`. Asserts, clause 1: a likes-page body of 3 likes plus a duplicate plus an unknown records exactly one Engine request, to `/internal/videos/metadata`, with `entries` equal to the submitted `{video_uuid, instance_domain}` list. The response `likes` holds the known rows in submitted order. An import of 3 likes records exactly one Engine request, to the same path. An empty or all-malformed likes-page body gives 200 `likes == []` with zero Engine requests. Asserts, clause 2: mint via `POST /api/profile` and resolve `profile_id` with `resolve_profile` on a second connection. Write one dislike with `write_dislike` and commit. Import the disliked video, a clean one and an unknown one. The result is `{"imported": 1}` and `load_liked_keys(conn, profile_id) == {(clean_id, host)}`. The existing `tests/active/test_profiles.py` import test also has to pass against the live Engine, in its own `validate_tests.py` invocation. That shows phases 1-2 and 3 work together.

**Intent.** `_handle_user_profile_likes_from_client` and `_handle_likes_import` in `client/backend/server.py` each resolve a request's browser likes with a single `fetch_metadata_for_entries` call, and import records a like from each returned row. `resolve_videos_by_uuid_host` no longer exists.

- C1 - A likes-page or likes-import request causes exactly one Engine HTTP call, to `/internal/videos/metadata`.
- C2 - Likes import records a like for each returned row whose video the profile has not disliked.

**Outcome.** ### `client/backend/server.py`
- **Import:** `resolve_videos_by_uuid_host` is no longer imported from `lib.engine_api_client`. The import line is now `fetch_metadata_for_entries, resolve_video_seed)`.
- **`_handle_likes_import`:** the per-like resolve call is replaced by one `fetch_metadata_for_entries(self.server.engine_ingest_base, likes)` call. It is passed the `_parse_client_likes` output unchanged: `{video_uuid, instance_domain}` pairs, not deduplicated, because the Engine parser removes duplicates. For each returned row, the loop checks `is_disliked(conn, profile_id, row["video_id"], row["instance_domain"])` and otherwise calls `record_like(conn, profile_id, "like", row, MAX_LIKES)`. The row is passed as-is because `record_like` reads only `video_id`, `instance_domain` and `video_uuid`. The following are unchanged:
  - the 502 text `Engine resolve failed: ...` (plan 15 rewrites it);
  - the `with conn:` block;
  - the `{"imported": n}` response.
- **Empty import:** there is no Engine call when nothing parses, because `fetch_metadata_for_entries` returns `[]` for an empty list.
- **`_handle_user_profile_likes_from_client`:** the two calls (resolve, then metadata) are now one `fetch_metadata_for_entries(self.server.engine_ingest_base, likes)` call, and its rows come back as `likes`. The following are unchanged:
  - the early 200 when nothing parses;
  - the 502 text `Engine metadata failed: ...`;
  - the response shape.
- **Docstring:** the placeholder docstring ("Handle handle user profile likes from client.") now describes what the handler does: one Engine call, submitted order, unknown videos omitted.

### `client/backend/lib/engine_api_client.py`
- **`resolve_videos_by_uuid_host` is deleted.** It was the per-like `/internal/videos/resolve` loop. `resolve_video_seed` stays, because user actions and block-add still use it.
- **Docstring:** `fetch_metadata_for_entries` now says it takes `{video_id|video_uuid, instance_domain}` entries and returns one row per video in first-entry order. Its logic is unchanged.

### Not changed
- **Other references:** a grep of `client/` finds no remaining reference to `resolve_videos_by_uuid_host`. The stale copies in `delete_me/` still mention it; I left them alone because nothing imports them.
- **`tests/tmp/test_client_like_batching.py`:** the phase's files list names this new file, but I did not create it. The gating checkpoint is `tests/tmp/test_14_batch_like_resolution_phase3.py`, and it covers the whole phase, so no second test file was needed.
- **Checkpoint:** I did not run it. The workflow's run is the one that counts.

#### Phase 4 - Cap like entries at 50 [code]

**Files touched.** client/backend/server.py (EDITED), tests/tmp/test_client_like_batching.py (EDITED)

**Checkpoint.** Seam: the same Client HTTP boundary and capturing stand-in Engine as phase 3, in the same test file. Asserts, clause 1, on three request paths: a 60-entry likes-page body gives 200, and the single recorded `/internal/videos/metadata` request carries exactly the first 50 entries. A 60-entry import body gives 200, and its single request carries exactly the first 50. A keyless `POST /recommendations` with 60 `{uuid, host}` likes records a forwarded body whose `likes` is the first 50 sanitised entries. The three paths are listed by hand, not derived. They are the three `MAX_CLIENT_LIKES` readers that the grep in the plan found.

**Intent.** `MAX_CLIENT_LIKES` in `client/backend/server.py` is 50, so at most the first 50 like entries of one request body reach the Engine.

- C1 - A body carrying 60 like entries reaches the Engine as its first 50 entries.

**Outcome.** ### `client/backend/server.py`
- `MAX_CLIENT_LIKES` went from 200 to 50. I added a one-line comment above it: it caps like entries per request, it matches the browser's local-likes limit (ADR-0003), and entries past the cap are dropped, not rejected.
- The three places that read it are unchanged: the `/recommendations` and `/videos/similar` proxy trim (`likes[:MAX_CLIENT_LIKES]`), and the `_parse_client_likes(body, MAX_CLIENT_LIKES)` calls in `_handle_likes_import` and `_handle_user_profile_likes_from_client`. All three still cut the raw list before dropping malformed entries.
- A grep outside `docs/` and `delete_me/*.bak-*` found no other code that reads the constant.

### `tests/tmp/test_client_like_batching.py`
- Not touched, because it doesn't exist. The phase lists it as EDITED, but phase 3's checkpoint was written to `tests/tmp/test_14_batch_like_resolution_phase3.py`, and this phase's checkpoint `tests/tmp/test_14_batch_like_resolution_phase4.py` builds its own stand-in Engine. The constant change is all this checkpoint needs.

### Housekeeping for the operator
- The test author's probe files `tests/tmp/probe_14_phase4.py` and `tests/tmp/probe_phase4_cap.py` (the second is named in the record; I didn't check it is on disk) are still there and should be deleted. I have no tool that deletes files.
- This step's prompt came with its `{rat_tail_ladder}`, `{rat_tail_rules}` and `{rat_tail_keep_in_full}` placeholders unfilled.


