# Build record - 14-batch-like-resolution

Written by the `dev-flow` workflow. The plan it accompanies is `docs/project/plans/16-14-batch-like-resolution.md`.

**Nothing but the workflow writes this file.** It carries the evidence each gate turned on: the baseline, both auditor verdicts verbatim, every self-check table, every red and its reason, every checkpoint outcome, and every amendment the operator approved to a settled section of the plan.

## Run state

<!-- dev-flow:state
```json
{
  "version": 1,
  "request": "# Resolve a batch of browser likes with one Engine call and cap requests at 50 likes\n\n## Requirements\n\n### What was asked for\n\nBuild issue `docs/project/issues/03-batch-like-resolution.md` as triaged: Resolve a batch of browser likes with one Engine call instead of one call per like, and cap a request at 50 like entries. The Agent Brief below, copied from the issue, is the confirmed requirement set; the build starts from this file.\n\n### Purpose\n\nClose the security-audit finding the issue records. This build is one of issues 01-06, delivered concurrently to use as little operator time and cause as few merge conflicts as possible.\n\n### Decisions this rests on\n\n`docs/project/adr/0003-metadata-endpoint-accepts-uuid-entries.md`.\n\n### Agent Brief\n\n**Category:** bug\n**Summary:** Resolve a batch of browser likes with one Engine call instead of one call per like, and cap a request at 50 like entries\n\n**Current behavior:**\nWhen the Client backend receives browser likes as `(uuid, host)` pairs \u2014 on the likes page endpoint (`POST /api/user-profile/likes`, no profile required) and on likes import (`POST /api/profile/likes/import`) \u2014 it resolves each pair with its own sequential Engine `/internal/videos/resolve` call. Each call takes the Engine's global database lock. The likes page then makes one more batched `/internal/videos/metadata` call for the resolved `(video_id, instance_domain)` entries. One request may carry up to 200 likes (`MAX_CLIENT_LIKES`), so a single anonymous POST costs up to 201 Engine round trips and 201 lock acquisitions. The same 200 cap trims the `likes` list on the `/recommendations` proxy.\n\n**Desired behavior:**\n- **Engine.** `/internal/videos/metadata` accepts each entry either as `{video_id, instance_domain}` (today's form) or as `{video_uuid, instance_domain}`. An entry with both uses `video_id`. Malformed entries are skipped as today, and duplicates within each form are collapsed. Every entry in a request is answered under one `db_lock` hold, with SQL batched like the existing id lookup (chunked; no per-entry query). Rows come back in the order of their first matching entry. A video reached by both forms appears once. The error-count threshold filter applies to both forms. Existing id-keyed callers see no change.\n- **Client backend.** The per-like resolve loop is gone. The likes page sends the deduplicated `(video_uuid, instance_domain)` entries in one metadata call and returns its rows. Likes import makes the same one call and records a like for each returned row, using the row's `video_id`, `video_uuid`, `instance_domain`, skipping disliked videos as today.\n- **Cap.** `MAX_CLIENT_LIKES` is 50. It bounds like entries per request body on the likes page, the import, and the `/recommendations` proxy likes list. Entries past 50 are dropped, not rejected, and responses are otherwise unchanged.\n- The likes page returns the same rows, in the same order, as before the change, for any request of 50 or fewer likes whose videos are all resolvable.\n\n**Key interfaces:**\n- Engine `/internal/videos/metadata` request body: `{\"entries\": [{\"video_id\"| \"video_uuid\": str, \"instance_domain\": str}, ...]}`; response shape unchanged (`{\"ok\", \"count\", \"rows\"}`).\n- Engine entry parser (currently `_parse_entries`, shared with `/internal/dislikes/centroids`): the centroids endpoint must keep accepting only `video_id` entries. Either give metadata its own parser or make uuid acceptance opt-in.\n- Engine metadata data function (currently `fetch_metadata_by_ids`): gains a uuid-keyed batch path, or a sibling function. `fetch_seed_embeddings_for_likes` shows an existing `(video_uuid, instance_domain) IN (...)` batch query to follow.\n- Client `resolve_videos_by_uuid_host`: removed, or reimplemented as one metadata call; `fetch_metadata_for_entries` is the call to use.\n- Client constant `MAX_CLIENT_LIKES`: 200 \u2192 50.\n\n**Acceptance criteria:**\n- [ ] A likes-page request with N (\u2264 50) likes causes exactly one Engine HTTP call, and one `db_lock` acquisition on the Engine.\n- [ ] A likes-import request with N likes causes exactly one Engine HTTP call and records a like for each resolvable, non-disliked, non-errored video.\n- [ ] A request with 60 like entries processes only the first 50 and returns 200.\n- [ ] The likes page returns rows in submitted order, deduplicated, and a like whose video is unknown to the Engine is omitted without an error.\n- [ ] `/internal/videos/metadata` with id-keyed entries returns the same rows as before; mixed id and uuid entries in one body both resolve.\n- [ ] `/internal/dislikes/centroids` rejects or ignores uuid-keyed entries as it does today.\n- [ ] The `/recommendations` proxy forwards at most 50 likes.\n- [ ] Existing Client backend and Engine test suites pass.\n\n**Out of scope:**\n- The single-video `/internal/videos/resolve` endpoint and the user-action path that uses it.\n- The profile's stored-likes limit (`MAX_LIKES = 100`) and the browser's local-likes limit.\n- Rate limiting of these endpoints (issue 02).\n- The `USE_LOCAL_LIKES_PROFILE` switch or any frontend change.\n\n### Consistency constraints\n\n- Match the surrounding code's style: stdlib HTTP handlers, `respond_json`, module-level named constants, and env vars read once at startup.\n- Backwards compatibility is not required beyond what the brief states.\n- Run `validate_tests.py` from the root of the tree this build runs in (a worktree for waves 1-2, main for wave 3). That tree's `.un` config carries it as `project_dir`.\n\n### Batch context\n\nPart of the security hardening batch (`.scratch/security-hardening-batch/notes.md`): issues 01-06 delivered in three waves of git worktrees. Wave 1 is plans 10, 11 and 12. Wave 2 is 13 and 14, branched from main after wave 1 merges. Wave 3 is 15, on the merged main. A wave 1 or 2 build runs in its own worktree created by `.scratch/security-hardening-batch/worktree-setup.sh`, merges to main when it closes, and is harvested on main, not in the worktree.\n\nWave 2, running alongside plan 13. It edits `client/backend/server.py` in four places: `MAX_CLIENT_LIKES` (`:49`), the `/recommendations` proxy trim (`:446`), likes import (`:837-843`) and the likes page (`:970-980`). Plan 15 runs afterwards and rewrites the 502 bodies this plan leaves in place.\n\n### Conflicts\n\nThe brief does not conflict with the tree. Every function and line it names was checked against the source on 2026-09-26 (`.scratch/security-hardening-batch/notes.md`, File overlap). Line numbers will drift once earlier waves merge, so re-locate by function name at Step 3.\n\n## High-level plan\n\n### Approach\n\n**Engine parser.** `/internal/videos/metadata` gets its own entry parser, which accepts `{video_id, instance_domain}` or `{video_uuid, instance_domain}`. An entry with both uses `video_id`. Malformed entries are skipped, and duplicates within each form are collapsed. `/internal/dislikes/centroids` keeps the existing `_parse_entries` (`handlers/internal_client_reads.py:20`), so it still accepts only ids.\n\n**Engine data.** A uuid-keyed batch lookup is added beside `fetch_metadata_by_ids` (`engine/server/data/metadata.py:110`). It uses a chunked `(video_uuid, instance_domain) IN (...)` query, following `fetch_seed_embeddings_for_likes` (`data/embeddings.py:191`), and applies the same error-count filter. The handler answers both forms under one `db_lock` hold, returns each video once, and orders rows by their first matching entry.\n\n**Client.** `resolve_videos_by_uuid_host` (`client/backend/lib/engine_api_client.py:136`) is removed. The likes page and likes import each make one `fetch_metadata_for_entries` call with the deduplicated uuid entries. Import records a like for each returned row and skips disliked videos, as it does today.\n\n**Cap.** `MAX_CLIENT_LIKES` goes from 200 to 50, and each of its three uses still drops the extra entries silently.\n\n### Alternatives considered\n\n- **A new `/internal/videos/resolve-batch` endpoint** (the audit's suggested fix). Rejected by ADR-0003: the metadata endpoint already returns what the likes page needs, so one call replaces both the resolve loop and the separate metadata call.\n- **An opt-in flag for uuid entries on the shared `_parse_entries`.** Viable, and the brief allows it. A separate parser is preferred so a wrong flag default can never widen what centroids accepts.\n- **Parallelising the per-like resolve calls.** Rejected: it still takes the lock N times.\n\n### Risks and limitations\n\n- **Accepted consequence (ADR-0003).** Import no longer imports videos at or over the Engine's error-count threshold, because the metadata endpoint filters them and resolve did not.\n- **Row order.** Metadata returns rows in first-entry order, so the likes page keeps the submitted order only if the handler preserves it across both lookup forms. The acceptance criteria require this explicitly.\n- **Callers.** The `/recommendations` proxy trim at `:446` and `_parse_client_likes` both read `MAX_CLIENT_LIKES`. Grep for any other reader at Step 3.\n- **Shared `whitelist.db`.** The worktree symlinks the main tree's `whitelist.db`, so this build's test Engines write interaction rows into the same file as other lanes, and as the live Engine if it runs. Every test run already does this; worktrees only make it concurrent.\n- **Tracked test record.** `tests/last_test_validation.json` and `tests/last_test_output.txt` always conflict on merge. Take main's copy and re-run `validate_tests.py --compare` on the merged tree.\n- **Engine rate limit.** Run Engine-backed test files in their own `validate_tests.py` invocations (memory `engine-rate-limit-single-lane-test-runs`).\n\n### Tradeoffs accepted\n\nA request's likes beyond the first 50 are dropped silently, not rejected.",
  "request_source": "read from docs/project/plans/14-batch-like-resolution.md",
  "slug": "14-batch-like-resolution",
  "steps": {
    "0": "done",
    "1": "done",
    "2": "done",
    "3": "done",
    "4": "done",
    "5": "done",
    "6": "done",
    "7": "done",
    "8": "done",
    "9": "done"
  },
  "phases": [
    {
      "n": "1",
      "kind": "code",
      "name": "Engine uuid-keyed metadata lookup",
      "checkpoint": "Seam: the data-layer functions `fetch_metadata_by_ids` and `fetch_metadata_by_uuids` in `engine/server/data/metadata.py`, called in-process against a temp SQLite DB (`row_factory = sqlite3.Row`). The DB has `videos` (26 selected columns plus `error_count`, PK `(video_id, instance_domain)`), `video_embeddings` (PK `(video_id, instance_domain)`) and `channels`. Harness: the `sys.path` insertion of `engine/server` and `engine/server/api` from `tests/active/test_internal_events.py:25-30`. `data.metadata` imports no numpy, so no child process is needed. The file lives in `tests/tmp` and needs `tests/active` on `sys.path` before any `from conftest import ...`. Fixtures come from the draft's table: a1, b1, s2 inserted before s1, e1, n1 with no embedding, and a1 on other.example. Asserts, clause 1: `fetch_metadata_by_uuids(conn, [{video_uuid: \"u-b\", instance_domain: \"h.example\"}])[\"u-b::h.example\"] == fetch_metadata_by_ids(conn, [{video_id: \"b1\", instance_domain: \"h.example\"}])[\"b1::h.example\"]`, and the dict holds exactly the 29 keys. `u-a@h.example` gives the h.example a1, not the other.example one. `U-A` and `u-a@H.EXAMPLE` give nothing. `u-n` gives nothing. An empty list gives `{}` with zero `execute` calls, counted through a wrapped conn. Asserts, clause 2: `u-s` gives `s1`. After `s1.error_count = 5` with threshold 3 it gives `s2`. `u-e` is absent at threshold 3 and present at threshold None. Regression pins with no clause of their own: `fetch_metadata_by_ids` output for a1, n1 skipped, and a 460-video set crossing the 450 chunk boundary on both functions with threshold 3. Every non-errored video comes back. On the uuid path, an errored video in chunk 2 is absent. On the id path there is no assertion on that errored video, because Open item A option 1 keeps today's AND/OR precedence.",
      "intent": "`engine/server/data/metadata.py` fetches metadata rows by exact `(video_uuid, instance_domain)` pair through `fetch_metadata_by_uuids`. It uses the same SELECT and row builder (`_select_metadata`) as `fetch_metadata_by_ids` and yields one row per pair: the lowest eligible `video_id`.",
      "clauses": [
        {
          "id": "C1",
          "text": "`fetch_metadata_by_uuids` returns, for an exact `(video_uuid, instance_domain)` match, the same row dict that `fetch_metadata_by_ids` returns for that video."
        },
        {
          "id": "C2",
          "text": "Where several videos share one `(video_uuid, instance_domain)`, the row kept is the one with the lowest `video_id` among those under the error threshold."
        }
      ],
      "files": [
        "engine/server/data/metadata.py (EDITED)",
        "tests/tmp/test_metadata_uuid_entries.py (NEW)"
      ],
      "done": true,
      "outcome": "### `engine/server/data/metadata.py`\n\n- **New `_select_metadata(conn, conditions, params, error_threshold)`:** holds the joined SELECT (`video_embeddings` JOIN `videos` LEFT JOIN `channels`) and the 29-key row builder that used to live inline in `fetch_metadata_by_ids`. It appends the `error_count IS NULL OR error_count < ?` clause when `error_threshold > 0`, the same rule as before. It works on a copy of `params` and returns a list of row dicts.\n- **`fetch_metadata_by_ids`:** still splits the input into chunks of 450 and builds the same OR-of-pairs condition, but now gets its rows from `_select_metadata` and keys them with `like_key`, as before. Its conditions are passed without parentheses on purpose, so the threshold still applies only to the last pair of each chunk (Open item A, option 1). This behaviour is unchanged, and a one-line comment explains why.\n- **New `fetch_metadata_by_uuids(conn, entries, error_threshold=None)`:**\n  - Returns `{}` for an empty list without running any SQL.\n  - Otherwise splits the input into chunks of 450, builds `(v.video_uuid = ? AND v.instance_domain = ?)` joined with OR, and passes it to `_select_metadata` wrapped in parentheses, so the threshold applies to every pair.\n  - Keys rows as `\"{video_uuid}::{instance_domain}\"`. Where several videos share a pair, it keeps the row with the lowest `video_id` among those the threshold lets through (C2).\n  - Matching is exact and case-sensitive, from SQLite's default BINARY `=`.\n  - An unembedded video is dropped by the inner join, as in the id path.\n- **Not changed:** `fetch_metadata` (the rowid lookup).\n\n### `tests/tmp/test_metadata_uuid_entries.py`\n\nNot created. The phase lists it as a new file, but the checkpoint already covers everything this phase does (see `inner_tests`)."
    },
    {
      "n": "2",
      "kind": "code",
      "name": "Engine metadata endpoint accepts both entry forms",
      "checkpoint": "Seam: `handlers.internal_client_reads.handle_internal_videos_metadata(handler, server)`, entered in an `ENGINE_PY -c` child with `cwd=API_DIR`. The module imports numpy, so it cannot run in the pytest interpreter. Harness: the child pattern of `tests/active/test_internal_events.py:173` and `tests/active/test_similar.py:288-289`. The child patches `read_json_body` and `respond_json` on the handler module. It passes `SimpleNamespace(db=conn, db_lock=CountingLock(), video_error_threshold=3)`, where `CountingLock` wraps `threading.Lock` and counts `__enter__`, and prints `[{status, payload, enters}]` per body. It uses the same temp DB as phase 1. Asserts, clause 1: the mixed body `[uuid u-b, id a1, id b1, uuid u-a, uuid u-x]` gives `enters == 1`. Id-only `[a1, b1, a1]` gives `enters == 1`. Asserts, clause 2: the mixed body gives rows `[b1, a1]` with `count == 2`, each video once in first-match order and the unknown omitted. Id-only `[a1, b1, a1]` gives `[a1, b1]`. An item carrying both a valid `video_id` and a `video_uuid` of a different video resolves to the id's video. Per-form duplicates collapse. Uuid `u-e` is absent at threshold 3. Guards: `{\"entries\": \"x\"}` and `{}` give 400 `Missing entries` with `enters == 0`. An all-malformed body (non-dict, blank `instance_domain`, neither key) gives 200 `{\"ok\": True, \"count\": 0, \"rows\": []}` with `enters == 0`. On `/internal/dislikes/centroids`, with `fetch_embeddings_by_ids` spied: a uuid-only body passes `[]` and returns `centroids == []`, and a mixed body passes only the id entries.",
      "intent": "`handle_internal_videos_metadata` in `engine/server/api/handlers/internal_client_reads.py` parses id-form and uuid-form entries with its own parser. It answers all of them in a single `db_lock` hold and emits each matched video once, at its first matching entry.",
      "clauses": [
        {
          "id": "C1",
          "text": "A request body mixing id-form and uuid-form entries acquires `db_lock` exactly once."
        },
        {
          "id": "C2",
          "text": "Each matched video appears once in `rows`, in the order of its first matching entry."
        }
      ],
      "files": [
        "engine/server/api/handlers/internal_client_reads.py (EDITED)",
        "tests/tmp/test_metadata_uuid_entries.py (EDITED)"
      ],
      "done": true,
      "outcome": "### `engine/server/api/handlers/internal_client_reads.py`\n- Line 9 now imports `fetch_metadata_by_uuids` alongside `fetch_metadata_by_ids`.\n- Three new helpers sit next to `_like_key` and `_parse_entries`, written as the plan sets them out:\n  - `_uuid_key` builds the `video_uuid::instance_domain` key. It matches the key `fetch_metadata_by_uuids` builds its result dict with.\n  - `_stripped` returns a stripped string, or None when the value is blank or not a string.\n  - `_parse_metadata_entries` returns None when `entries` is not a list. It skips items that are not a dict or have no valid stripped `instance_domain`. An item with a valid `video_id` counts as the id form even when it also carries a `video_uuid`; otherwise a valid `video_uuid` makes it the uuid form, and an item with neither is skipped. It drops duplicates within each form, keeping the first, and returns one ordered list of `(form, entry)` pairs. The form is part of the duplicate key so id keys and uuid keys cannot collide.\n- `handle_internal_videos_metadata`:\n  - It now uses the new parser. The 400 `Missing entries` answer and the empty 200 answered before any lock are kept.\n  - It splits the parsed entries into id entries and uuid entries. Inside one `with server.db_lock:` it calls `fetch_metadata_by_ids` and/or `fetch_metadata_by_uuids`, skipping a call when its list is empty, and both get the same `video_error_threshold`.\n  - After the lock is released, it walks the entries in order and looks each one up in the dict for its own form. It emits a row only the first time it sees that row's `video_id::instance_domain`, so each video appears once, at its first matching entry.\n  - The response shape is unchanged. The docstring is updated.\n- `_like_key`, `_parse_entries`, `handle_internal_video_resolve` and `handle_internal_dislike_centroids` are not changed, so centroids still accepts only id-form entries.\n\n### `tests/tmp/test_metadata_uuid_entries.py`\nNot changed. The files list marks it EDITED, but the file does not exist in the worktree: the phase 1 checkpoint landed as `tests/tmp/test_14_batch_like_resolution_phase1.py`. The phase 2 checkpoint covers this phase on its own, so I did not create this file."
    },
    {
      "n": "3",
      "kind": "code",
      "name": "Client resolves likes in one Engine call",
      "checkpoint": "Seam: the Client HTTP boundary. Requests go to `POST /api/user-profile/likes` and `POST /api/profile/likes/import` on a locally built `ClientBackendServer`, whose `engine_ingest_base` points at a capturing stand-in Engine. The stand-in is a stdlib `ThreadingHTTPServer` written like `EngineStub` at `tests/active/test_server.py:307`. It records `(path, json body)` for every POST. On `/internal/videos/metadata` it answers from a canned `{uuid::host: row}` table in entry order, omitting unknown entries and duplicates. Local `_serving` and `_client_backend` copies of `test_server.py:251-271` build the Client, with `RateLimiter(1000, 60)`. The file needs `tests/active` on `sys.path` before `from conftest import ...`. Asserts, clause 1: a likes-page body of 3 likes plus a duplicate plus an unknown records exactly one Engine request, to `/internal/videos/metadata`, with `entries` equal to the submitted `{video_uuid, instance_domain}` list. The response `likes` holds the known rows in submitted order. An import of 3 likes records exactly one Engine request, to the same path. An empty or all-malformed likes-page body gives 200 `likes == []` with zero Engine requests. Asserts, clause 2: mint via `POST /api/profile` and resolve `profile_id` with `resolve_profile` on a second connection. Write one dislike with `write_dislike` and commit. Import the disliked video, a clean one and an unknown one. The result is `{\"imported\": 1}` and `load_liked_keys(conn, profile_id) == {(clean_id, host)}`. The existing `tests/active/test_profiles.py` import test also has to pass against the live Engine, in its own `validate_tests.py` invocation. That shows phases 1-2 and 3 work together.",
      "intent": "`_handle_user_profile_likes_from_client` and `_handle_likes_import` in `client/backend/server.py` each resolve a request's browser likes with a single `fetch_metadata_for_entries` call, and import records a like from each returned row. `resolve_videos_by_uuid_host` no longer exists.",
      "clauses": [
        {
          "id": "C1",
          "text": "A likes-page or likes-import request causes exactly one Engine HTTP call, to `/internal/videos/metadata`."
        },
        {
          "id": "C2",
          "text": "Likes import records a like for each returned row whose video the profile has not disliked."
        }
      ],
      "files": [
        "client/backend/server.py (EDITED)",
        "client/backend/lib/engine_api_client.py (EDITED)",
        "tests/tmp/test_client_like_batching.py (NEW)"
      ],
      "done": true,
      "outcome": "### `client/backend/server.py`\n- **Import:** `resolve_videos_by_uuid_host` is no longer imported from `lib.engine_api_client`. The import line is now `fetch_metadata_for_entries, resolve_video_seed)`.\n- **`_handle_likes_import`:** the per-like resolve call is replaced by one `fetch_metadata_for_entries(self.server.engine_ingest_base, likes)` call. It is passed the `_parse_client_likes` output unchanged: `{video_uuid, instance_domain}` pairs, not deduplicated, because the Engine parser removes duplicates. For each returned row, the loop checks `is_disliked(conn, profile_id, row[\"video_id\"], row[\"instance_domain\"])` and otherwise calls `record_like(conn, profile_id, \"like\", row, MAX_LIKES)`. The row is passed as-is because `record_like` reads only `video_id`, `instance_domain` and `video_uuid`. The following are unchanged:\n  - the 502 text `Engine resolve failed: ...` (plan 15 rewrites it);\n  - the `with conn:` block;\n  - the `{\"imported\": n}` response.\n- **Empty import:** there is no Engine call when nothing parses, because `fetch_metadata_for_entries` returns `[]` for an empty list.\n- **`_handle_user_profile_likes_from_client`:** the two calls (resolve, then metadata) are now one `fetch_metadata_for_entries(self.server.engine_ingest_base, likes)` call, and its rows come back as `likes`. The following are unchanged:\n  - the early 200 when nothing parses;\n  - the 502 text `Engine metadata failed: ...`;\n  - the response shape.\n- **Docstring:** the placeholder docstring (\"Handle handle user profile likes from client.\") now describes what the handler does: one Engine call, submitted order, unknown videos omitted.\n\n### `client/backend/lib/engine_api_client.py`\n- **`resolve_videos_by_uuid_host` is deleted.** It was the per-like `/internal/videos/resolve` loop. `resolve_video_seed` stays, because user actions and block-add still use it.\n- **Docstring:** `fetch_metadata_for_entries` now says it takes `{video_id|video_uuid, instance_domain}` entries and returns one row per video in first-entry order. Its logic is unchanged.\n\n### Not changed\n- **Other references:** a grep of `client/` finds no remaining reference to `resolve_videos_by_uuid_host`. The stale copies in `delete_me/` still mention it; I left them alone because nothing imports them.\n- **`tests/tmp/test_client_like_batching.py`:** the phase's files list names this new file, but I did not create it. The gating checkpoint is `tests/tmp/test_14_batch_like_resolution_phase3.py`, and it covers the whole phase, so no second test file was needed.\n- **Checkpoint:** I did not run it. The workflow's run is the one that counts."
    },
    {
      "n": "4",
      "kind": "code",
      "name": "Cap like entries at 50",
      "checkpoint": "Seam: the same Client HTTP boundary and capturing stand-in Engine as phase 3, in the same test file. Asserts, clause 1, on three request paths: a 60-entry likes-page body gives 200, and the single recorded `/internal/videos/metadata` request carries exactly the first 50 entries. A 60-entry import body gives 200, and its single request carries exactly the first 50. A keyless `POST /recommendations` with 60 `{uuid, host}` likes records a forwarded body whose `likes` is the first 50 sanitised entries. The three paths are listed by hand, not derived. They are the three `MAX_CLIENT_LIKES` readers that the grep in the plan found.",
      "intent": "`MAX_CLIENT_LIKES` in `client/backend/server.py` is 50, so at most the first 50 like entries of one request body reach the Engine.",
      "clauses": [
        {
          "id": "C1",
          "text": "A body carrying 60 like entries reaches the Engine as its first 50 entries."
        }
      ],
      "files": [
        "client/backend/server.py (EDITED)",
        "tests/tmp/test_client_like_batching.py (EDITED)"
      ],
      "done": true,
      "outcome": "### `client/backend/server.py`\n- `MAX_CLIENT_LIKES` went from 200 to 50. I added a one-line comment above it: it caps like entries per request, it matches the browser's local-likes limit (ADR-0003), and entries past the cap are dropped, not rejected.\n- The three places that read it are unchanged: the `/recommendations` and `/videos/similar` proxy trim (`likes[:MAX_CLIENT_LIKES]`), and the `_parse_client_likes(body, MAX_CLIENT_LIKES)` calls in `_handle_likes_import` and `_handle_user_profile_likes_from_client`. All three still cut the raw list before dropping malformed entries.\n- A grep outside `docs/` and `delete_me/*.bak-*` found no other code that reads the constant.\n\n### `tests/tmp/test_client_like_batching.py`\n- Not touched, because it doesn't exist. The phase lists it as EDITED, but phase 3's checkpoint was written to `tests/tmp/test_14_batch_like_resolution_phase3.py`, and this phase's checkpoint `tests/tmp/test_14_batch_like_resolution_phase4.py` builds its own stand-in Engine. The constant change is all this checkpoint needs.\n\n### Housekeeping for the operator\n- The test author's probe files `tests/tmp/probe_14_phase4.py` and `tests/tmp/probe_phase4_cap.py` (the second is named in the record; I didn't check it is on disk) are still there and should be deleted. I have no tool that deletes files.\n- This step's prompt came with its `{rat_tail_ladder}`, `{rat_tail_rules}` and `{rat_tail_keep_in_full}` placeholders unfilled."
    }
  ],
  "digests": {
    "tests/tmp/test_14_batch_like_resolution_phase1.py": "a3064b0cc08f6597a9884a2e820c056ded42b2cb6d69879b5ef245f1f20e762a",
    "tests/tmp/test_14_batch_like_resolution_phase2.py": "fee881233fa157c0dcd09386e63e745e6a9c69e68baba6db87cc03dd00632571",
    "tests/tmp/test_14_batch_like_resolution_phase3.py": "707ffdbcfeec8d6588ba76ce7be3f1f567f704a73043e05df6f3b684918a3657",
    "tests/tmp/test_14_batch_like_resolution_phase4.py": "b9c443709eccf6ffe884cc33336b0fd1403933aa9e6290323ba8fb7a95e331a3"
  },
  "paths": {
    "active": "tests/active",
    "working": "tests/tmp",
    "plans": "docs/project/plans",
    "delete_me": "delete_me",
    "archive": "tests/archive",
    "project_dir": "/home/enduser/code/PeerTube-browser/.worktrees/fix-14-batch-like-resolution",
    "record": "tests/last_test_validation.json",
    "output": "tests/last_test_output.txt"
  },
  "baseline": {
    "code": 0,
    "variant": false
  },
  "sessions": [
    "20260927T025844-8f82-dev-flow",
    "20260927T030206-3459-dev-flow"
  ],
  "plan": "docs/project/plans/16-14-batch-like-resolution.md",
  "record": "docs/project/plans/16-14-batch-like-resolution.record.md",
  "replies": {
    "step_1_gather_requirements": "<requirements>\n### Purpose\n\nBuild issue `docs/project/issues/03-batch-like-resolution.md` (category bug) as triaged. It closes the security-audit finding (run-1, `resolve_videos_by_uuid_host` loop): one anonymous `POST /api/user-profile/likes` currently costs up to 201 sequential Engine round trips and 201 acquisitions of the Engine's global `db_lock`. After this build, a batch of browser likes is resolved with one Engine call, and a request is capped at 50 like entries. The decision it rests on is `docs/project/adr/0003-metadata-endpoint-accepts-uuid-entries.md`: `/internal/videos/metadata` accepts `(video_uuid, instance_domain)` entries, and a separate resolve-batch endpoint was rejected. The build is part of the security hardening batch (`.scratch/security-hardening-batch/notes.md`), wave 2 alongside plan 13, and runs in the worktree `/home/enduser/code/PeerTube-browser/.worktrees/fix-14-batch-like-resolution`.\n\n### Current behaviour (verified in the worktree)\n\n- `client/backend/server.py:52`: `MAX_CLIENT_LIKES = 200`, next to `MAX_LIKES = 100` (profile stored-likes limit, out of scope) and `ENGINE_FEED_LIKES_MAX = 5`.\n- `client/backend/server.py:1105` `_parse_client_likes(payload, max_items)`: takes `raw[:max_items]` and then skips malformed items (not a dict, or `uuid`/`host` not a non-empty string). It returns `[{\"video_uuid\", \"instance_domain\"}]` stripped, and does not deduplicate.\n- `client/backend/server.py:493`, the `/recommendations` and `/videos/similar` POST proxy: `for entry in likes[:MAX_CLIENT_LIKES]:` sanitises to `{\"uuid\", \"host\"}`, skipping malformed entries.\n- `client/backend/server.py:872-900`, `_handle_likes_import` (`POST /api/profile/likes/import`, behind `_require_profile`): calls `_parse_client_likes(body, MAX_CLIENT_LIKES)`, then `resolve_videos_by_uuid_host`. On `EngineApiError` it answers 502 `{\"error\": \"Engine resolve failed: ...\"}`. Otherwise, inside `with conn:`, it skips each video where `is_disliked(conn, profile_id, video_id, instance_domain)`, calls `record_like(conn, profile_id, \"like\", video, MAX_LIKES)` for the rest, and answers 200 `{\"imported\": n}`. `record_like` (`client/backend/lib/users_store.py:79`) reads `video_id`, `instance_domain` and `video_uuid` from the dict.\n- `client/backend/server.py:1012-1029`, `_handle_user_profile_likes_from_client` (`POST /api/user-profile/likes`, no profile required): calls `_parse_client_likes`. An empty list gives 200 `{\"likes\": [], \"updatedAt\"}` with no Engine call. Otherwise it calls `resolve_videos_by_uuid_host`, then `fetch_metadata_for_entries(resolved)`. On `EngineApiError` it answers 502 `{\"error\": \"Engine metadata failed: ...\"}`. Otherwise it answers 200 `{\"likes\": rows, \"updatedAt\"}`.\n- `client/backend/lib/engine_api_client.py:136` `resolve_videos_by_uuid_host`: deduplicates on `uuid::host` and makes one `resolve_video_seed` \u2192 `/internal/videos/resolve` call per like. It is imported in `server.py:32`. `fetch_metadata_for_entries` (`:92`) posts `{\"entries\": entries}` to `/internal/videos/metadata`, raises `EngineApiError` on a non-200 status or an invalid payload, and returns the dict rows.\n- `engine/server/api/handlers/internal_client_reads.py:20` `_parse_entries`: returns None when `entries` is not a list, skips malformed items, and deduplicates on `video_id::instance_domain`. It is used by `handle_internal_videos_metadata` (`:95`) and `handle_internal_dislike_centroids` (`:129`). The metadata handler answers 400 `Missing entries`, and answers 200 with empty rows when there are no entries. Under one `with server.db_lock:` it calls `fetch_metadata_by_ids(..., error_threshold=getattr(server, \"video_error_threshold\", None))`, then emits rows in entry order via `_like_key`. The response is `{\"ok\": True, \"count\", \"rows\"}`.\n- `engine/server/data/metadata.py:110` `fetch_metadata_by_ids`: chunks of 450 with an `OR` of `(v.video_id = ? AND v.instance_domain = ?)`. It inner-joins `video_embeddings` and left-joins `channels`, applies `AND (v.error_count IS NULL OR v.error_count < ?)` when the threshold is > 0, and returns a dict keyed by `like_key(row)` (`video_id::instance_domain`).\n- `engine/server/data/embeddings.py:191` `fetch_seed_embeddings_for_likes`: the precedent for a `WHERE (v.video_uuid, v.instance_domain) IN ((?, ?), ...)` batch query. It is not chunked.\n- The old resolve path (`fetch_seed_embedding` \u2192 `_fetch_seed_by_uuid`) matches `v.video_uuid = ? AND v.instance_domain = ?` exactly, with the same `video_embeddings` inner join and `LIMIT 1`, and no error-count filter. `_seed_from_row` also drops rows whose embedding blob is empty or does not match `embedding_dim`.\n- The `videos` table key is `PRIMARY KEY (video_id, instance_domain)`. Nothing enforces uniqueness of `(video_uuid, instance_domain)`.\n\n### R1 \u2014 Engine: metadata endpoint entry parsing\n\n- `/internal/videos/metadata` gets its own entry parser. `_parse_entries` stays unchanged and is still used by `/internal/dislikes/centroids`, so centroids keeps accepting only `video_id` entries, and uuid-only entries there are skipped as malformed, as today.\n- An entry is accepted as `{video_id, instance_domain}` or `{video_uuid, instance_domain}`, where each value is a non-empty string and is stripped. An entry carrying a valid `video_id` is treated as id-keyed, even if it also has `video_uuid`. An entry with neither valid key, or without a valid `instance_domain`, or that is not a dict, is skipped.\n- Duplicates are collapsed within each form (id form on `video_id::instance_domain`, uuid form on `video_uuid::instance_domain`), keeping the first occurrence.\n- A body without an `entries` list still gets 400 `{\"error\": \"Missing entries\"}`. When no entries are valid, the answer is still 200 `{\"ok\": True, \"count\": 0, \"rows\": []}` without taking the lock.\n\n### R2 \u2014 Engine: uuid-keyed batch lookup\n\n- A uuid-keyed batch data function goes beside `fetch_metadata_by_ids` in `engine/server/data/metadata.py` (a sibling function, or a path in the same function). It selects the same columns with the same joins (inner `video_embeddings`, left `channels`) and the same error-count threshold clause, and builds the same row dict, so a video's row is identical whichever form reached it.\n- Its SQL is `WHERE (v.video_uuid, v.instance_domain) IN (...)`, following `fetch_seed_embeddings_for_likes`, chunked like the id lookup (at most 450 pairs per statement). There is no query per entry.\n- The match is exact on `video_uuid` and `instance_domain`, as the old resolve was.\n- A uuid entry yields at most one row. If several videos share one `(video_uuid, instance_domain)`, the one with the lowest `video_id` is chosen, so the choice is deterministic (operator-approved; resolve's `LIMIT 1` was arbitrary).\n- No embedding-blob validity check is added (operator-approved difference from resolve; see conflicts).\n\n### R3 \u2014 Engine: one lock hold, ordering, dedup across forms\n\n- The handler answers every entry of a request, id and uuid forms together, under a single `with server.db_lock:` hold, one acquisition per request.\n- Rows are emitted in the order of the first entry that matches each video. A video reached by both an id entry and a uuid entry (or by several entries) appears once, identified by `video_id::instance_domain`.\n- The error-count threshold filter applies to both forms.\n- The response shape is unchanged: `{\"ok\": True, \"count\": len(rows), \"rows\": rows}`. Existing id-keyed callers (the Client's `_handle_user_profile_likes_get`, `_handle_block_add`, and any other caller) see exactly the rows they saw before.\n\n### R4 \u2014 Client: likes page makes one Engine call\n\n- `_handle_user_profile_likes_from_client` sends the deduplicated `(video_uuid, instance_domain)` entries from `_parse_client_likes` in a single `fetch_metadata_for_entries` call and returns its rows as `likes`. There is no resolve call.\n- Deduplication happens before the call, on `video_uuid::instance_domain`, keeping the first occurrence and submitted order. It may be done by the Client, the Engine parser, or both. The Engine's R1 dedup alone is sufficient.\n- A like whose video is unknown to the Engine (or at or over the error threshold) is omitted without error.\n- An empty parse still answers 200 `{\"likes\": [], \"updatedAt\"}` without an Engine call.\n- The 502 path and body text are left as they are (plan 15 rewrites 502 bodies later).\n- For any request of 50 or fewer likes whose videos all resolve, the response rows and their order are the same as before the change.\n\n### R5 \u2014 Client: likes import makes one Engine call\n\n- `_handle_likes_import` makes the same single `fetch_metadata_for_entries` call with the deduplicated uuid entries.\n- For each returned row it skips the video if `is_disliked(conn, profile_id, row[\"video_id\"], row[\"instance_domain\"])`. Otherwise it calls `record_like(conn, profile_id, \"like\", {video_id, video_uuid, instance_domain from the row}, MAX_LIKES)`. It answers 200 `{\"imported\": n}`, as today.\n- Accepted consequence (ADR-0003): a video at or over the Engine's error-count threshold is no longer imported.\n- The existing 502 on `EngineApiError` stays. Its body text may stay \"Engine resolve failed: ...\" (plan 15 rewrites it).\n\n### R6 \u2014 Client: remove the per-like resolve loop\n\n`resolve_videos_by_uuid_host` is removed from `client/backend/lib/engine_api_client.py`, and its import is dropped from `client/backend/server.py`. `resolve_video_seed` and `/internal/videos/resolve` remain, for block-add and user actions.\n\n### R7 \u2014 Cap at 50\n\n- `MAX_CLIENT_LIKES = 50` in `client/backend/server.py`.\n- It bounds like entries per request body on the likes page, the import (both via `_parse_client_likes`), and the `/recommendations` / `/videos/similar` proxy `likes` list (`likes[:MAX_CLIENT_LIKES]`).\n- Entries past the 50th are dropped, not rejected. The cap applies to the raw list before malformed entries are skipped, as today. Responses are otherwise unchanged.\n- Before editing, grep for any other reader of `MAX_CLIENT_LIKES`. Only the three sites above were found.\n\n### Acceptance criteria\n\n- A likes-page request with N \u2264 50 likes causes exactly one Engine HTTP call and one `db_lock` acquisition on the Engine.\n- A likes-import request with N likes causes exactly one Engine HTTP call and records a like for each resolvable, non-disliked, non-errored video.\n- A request with 60 like entries processes only the first 50 and returns 200 (likes page and import).\n- The likes page returns rows in submitted order, deduplicated. A like whose video is unknown to the Engine is omitted without an error.\n- `/internal/videos/metadata` with id-keyed entries returns the same rows as before. Mixed id and uuid entries in one body both resolve. A video reached by both forms appears once.\n- `/internal/dislikes/centroids` treats uuid-keyed entries exactly as today (skipped as malformed).\n- The `/recommendations` proxy forwards at most 50 likes.\n- Existing Client backend and Engine test suites pass, including `tests/active/test_profiles.py::test_importing_browser_likes_marks_each_imported_video_liked_and_no_other` and `tests/active/test_server.py`.\n\n### Testing constraints\n\n- Run `validate_tests.py` from `/home/enduser/code/PeerTube-browser/.worktrees/fix-14-batch-like-resolution` (this worktree's `project_dir`). Trees: active `tests/active`, working `tests/tmp`, archive `tests/archive`, record `tests/last_test_validation.json`, output `tests/last_test_output.txt`.\n- Run each Engine-backed test file in its own `validate_tests.py` invocation, because the Engine's per-IP rate limit is shared (memory `engine-rate-limit-single-lane-test-runs`).\n- The Engine-call-count and lock-count criteria need a counting or capturing seam: a stand-in Engine or a wrapped lock or stub server. They cannot be read off the live Engine.\n- The worktree's `whitelist.db` is a symlink to main's, so test Engines share it with other lanes. These endpoints only read from it, but the fixture Engine's startup still touches the file.\n- Engine handler code imports numpy (and `handlers.similar` pulls in faiss), so any in-process Engine unit test must run under the Engine interpreter (`conftest.ENGINE_PY`) or through the live `engine` fixture.\n\n### Baseline suite state\n\nThe pre-build baseline run exited with code 0, variant false: the suite is green before the build starts.\n\n### Consistency constraints\n\n- Match the surrounding style: stdlib HTTP handlers, `respond_json`, module-level named constants, env vars read once at startup, and a docstring on every function. No new dependency.\n- Smallest thing that works: no new endpoint, no new module beyond tests, no abstraction with one implementation.\n- Backwards compatibility is not required beyond what these requirements state.\n- Do not softwrap.\n\n### Out of scope\n\n- The single-video `/internal/videos/resolve` endpoint and the user-action and block-add paths that use it.\n- `MAX_LIKES = 100` (profile stored-likes limit) and the browser's local-likes limit.\n- Rate limiting of these endpoints (issue 02).\n- The `USE_LOCAL_LIKES_PROFILE` switch and any frontend change.\n- 502 body wording (plan 15).\n\n### Batch and merge context\n\n- Wave 2, alongside plan 13. This plan edits `client/backend/server.py` at `MAX_CLIENT_LIKES` (now line 52), the proxy trim (now line 493), `_handle_likes_import` (now lines 872-900), `_handle_user_profile_likes_from_client` (now lines 1012-1029), and the import line 32. Keep the edits local. Line numbers drift, so re-locate by function name.\n- The build merges to main when it closes. Harvest runs on main, not in the worktree.\n- `tests/last_test_validation.json` and `tests/last_test_output.txt` always conflict on merge: take main's copy and re-run `validate_tests.py --compare` on the merged tree.\n</requirements>\n\n<conflicts>\nBrief \"the likes page returns the same rows, in the same order, as before\" vs the tree: the old resolve path (`engine/server/data/embeddings.py` `_seed_from_row`) dropped videos whose embedding blob was empty or did not match `embedding_dim`, while `fetch_metadata_by_ids` has no such check, so such a video now appears on the likes page and is imported. Operator approved accepting this difference.\nBrief \"rows come back in the order of their first matching entry\" / \"a video reached by both forms appears once\" vs the tree: `videos` is keyed on `(video_id, instance_domain)` only, and `(video_uuid, instance_domain)` is not unique, so one uuid entry could match several videos, where resolve took an arbitrary `LIMIT 1`. Resolved with the operator: a uuid entry yields at most one row, the lowest `video_id`.\nPlan \"Batch context\" line numbers (`:49`, `:446`, `:837-843`, `:970-980`) vs the tree: after wave 1 merged they are `server.py:52`, `:493`, `:872-900` and `:1012-1029`. The functions are unchanged. Only the locations moved.\n</conflicts>",
    "step_2_develop_solution": "<initial_solution>\n### Approach\n\nThe fix sits on the Engine side of one existing endpoint. The Client side only loses code.\n\n**Engine: data layer (R2).** In `engine/server/data/metadata.py`, `fetch_metadata_by_ids` already holds the 29-column SELECT, the inner `video_embeddings` join, the left `channels` join, the error-count clause and the row-dict construction. I move that body into one private helper in the same file. The helper takes a chunk's WHERE fragment and its parameters, and returns the built row dicts. `fetch_metadata_by_ids` keeps its signature and output (a dict keyed by `video_id::instance_domain`) and becomes a thin caller that supplies its existing `OR` fragment. A new sibling function, `fetch_metadata_by_uuids`, supplies `(v.video_uuid, v.instance_domain) IN ((?, ?), ...)`, the same row-value form `fetch_seed_embeddings_for_likes` already runs on this SQLite. It is chunked at 450 pairs, which is 900 bound values plus one threshold, under SQLite's 999 limit. The helper has two callers, so it is shared code, not a single-implementation abstraction. Because a video's row dict is built in exactly one place, it is identical whichever form reached it. The uuid function orders each chunk by `v.video_id` and keeps the first row per `video_uuid::instance_domain`. That gives at most one row per uuid entry, and the lowest `video_id` when several videos share a pair. Entries are deduplicated before chunking, so one pair never spans two chunks. The match is an exact equality on both columns, as `_fetch_seed_by_uuid` did, and no embedding-blob check is added (operator-approved). The rowid-keyed `fetch_metadata` at the top of the file is not touched, which keeps the diff local.\n\n**Engine: parser and handler (R1, R3).** `internal_client_reads.py` gets a second parser beside `_parse_entries`, used only by `handle_internal_videos_metadata`. For each item it:\n- skips anything that is not a dict, or has no valid stripped `instance_domain`;\n- treats an item with a valid `video_id` as id-form, even if it also carries `video_uuid`;\n- otherwise treats an item with a valid `video_uuid` as uuid-form, and skips it if it has neither.\n\nIt deduplicates within each form on its own key, keeping the first occurrence, and returns one ordered list of tagged entries. When `entries` is not a list it returns None, so the 400 `Missing entries` path is unchanged. `_parse_entries` and `/internal/dislikes/centroids` are not edited, so centroids keeps skipping uuid-only entries.\n\nThe handler flow:\n1. An empty parse still answers 200 with no rows, before any lock.\n2. It splits the ordered list into id entries and uuid entries.\n3. Inside one `with server.db_lock:` it calls `fetch_metadata_by_ids` for the id entries and `fetch_metadata_by_uuids` for the uuid entries, skipping either call when its list is empty, with the same `video_error_threshold` for both.\n4. After releasing the lock, it walks the ordered entries, looks up each entry's row in the dict for its form, and emits the row only if its `video_id::instance_domain` has not been emitted yet.\n\nRows therefore come out in first-matching-entry order, and a video reached by both forms, or by several entries, appears once. An id-only request runs exactly the query it ran before and emits the same rows in the same order, so `_handle_user_profile_likes_get`, `_handle_block_add` and the other id callers see no change. The response shape `{\"ok\", \"count\", \"rows\"}` is unchanged.\n\n**Client (R4, R5, R6).**\n- **Likes page:** `_handle_user_profile_likes_from_client` passes the `_parse_client_likes` output (already `{video_uuid, instance_domain}` dicts) straight to one `fetch_metadata_for_entries` call and returns its rows as `likes`. The empty-parse early 200 stays, and so do the 502 path and its text. Deduplication is left to the Engine parser. R4 says that is sufficient, and it avoids a second copy of the same loop in the Client.\n- **Import:** `_handle_likes_import` makes the same single call. Its 502 text stays \"Engine resolve failed\". For each returned row it checks `is_disliked` on the row's `video_id` and `instance_domain`, and otherwise calls `record_like` with the row's `video_id`, `video_uuid` and `instance_domain`. An empty parse makes no Engine call, because `fetch_metadata_for_entries` already returns `[]` for an empty list.\n- **Removal:** `resolve_videos_by_uuid_host` is deleted from `engine_api_client.py` and from the import on `server.py:32`. `resolve_video_seed` stays.\n\n**Cap (R7).** `MAX_CLIENT_LIKES` becomes 50. A grep of the worktree, ignoring the stale `delete_me/*.bak-*` copies, confirms the only readers are the proxy trim and the two `_parse_client_likes` calls. All three keep slicing the raw list before skipping malformed items, so entries past the 50th are dropped silently.\n\n**How each requirement is met.**\n- **R1:** the new parser.\n- **R2:** the sibling uuid function over the shared SELECT and row builder.\n- **R3:** one lock hold around both lookups, then the ordered, deduplicating walk.\n- **R4 and R5:** one metadata call each.\n- **R6:** the deletion.\n- **R7:** the constant.\n\n**Same rows as before (R4).** For 50 or fewer likes that all resolve, old and new produce the same rows in the same order. The old flow deduplicated on `uuid::host` in submitted order, resolved each pair to a `video_id`, then asked metadata for those ids in that order, deduplicating on id. The new flow does the same steps inside one Engine call.\n\n**Tests.** The Engine-side checks are:\n- parser forms and dedup;\n- id-only rows unchanged;\n- mixed id and uuid entries;\n- the same video via both forms appearing once;\n- lowest `video_id` on a shared uuid pair;\n- the error threshold on the uuid form;\n- centroids ignoring uuid entries;\n- exactly one lock acquisition.\n\nThese run in-process against a temp SQLite DB with a stand-in server whose `db_lock` counts its enters. Because the handler imports numpy, they run under `conftest.ENGINE_PY` as a subprocess, following the `test_db.py` pattern.\n\nThe Client-side checks are:\n- one Engine HTTP call per likes-page or import request;\n- a 60-entry body reaching the Engine as 50;\n- the proxy forwarding at most 50;\n- unknown videos omitted;\n- disliked videos skipped on import.\n\nThese use a capturing stand-in Engine, a small stdlib HTTP server that records each request and returns canned rows. The existing `test_profiles.py` import test and `test_server.py` run against the live Engine fixture, each in its own `validate_tests.py` invocation.\n\n### Alternatives considered\n\n- **A new `/internal/videos/resolve-batch` endpoint.** Rejected by ADR-0003. The metadata endpoint already returns what both callers need, so one call replaces both the resolve loop and the separate metadata call.\n- **An opt-in uuid flag on the shared `_parse_entries`.** Rejected. A separate parser means centroids cannot be widened by a wrong default or a forgotten argument, and R1 asks for a separate parser.\n- **A uuid path inside `fetch_metadata_by_ids`, switched by a keyword.** Viable under R2. Rejected because the function name and its return key (`video_id::instance_domain`) would then lie for the uuid path, and the handler needs the uuid path keyed by `video_uuid::instance_domain`.\n- **Copying the SELECT and row dict into the new function.** Rejected. That would make a third copy in the file (`fetch_metadata` already duplicates most of it), and any drift between the two metadata copies would break the \"identical row whichever form\" guarantee without any test failing.\n- **Doing the lowest-`video_id` choice in SQL with a window function or a GROUP BY and MIN.** Rejected as more SQL for no gain. An `ORDER BY v.video_id` inside each chunk, then keeping the first row per key, is plain and deterministic.\n- **Keeping `resolve_videos_by_uuid_host` as a one-call wrapper.** Rejected by R6, and a wrapper around a single call adds nothing.\n- **Deduplicating in the Client too.** Rejected as a second copy of the Engine parser's loop. R4 states the Engine dedup alone is sufficient.\n- **Parallel resolve calls.** Rejected. It still takes the lock N times, which is the finding.\n\n### Risks and gotchas\n\n- **Lowest `video_id` among eligible rows.** The error-count clause is applied in SQL before the pick, so the choice is the lowest `video_id` among videos that pass the threshold. If the lowest-id sibling is errored, a healthy sibling is returned. The old flow could return nothing there: resolve's arbitrary `LIMIT 1` might pick the errored one, and metadata then dropped it. I take this to be what \"threshold applies to both forms\" plus \"lowest `video_id`\" means together. It only matters for duplicated `(video_uuid, instance_domain)` pairs.\n- **Lock hold length.** One hold now covers up to two queries instead of one. With the Client capping at 50, the uuid query is a single statement. A direct caller of the Engine could send a large body, but that is bounded by the Engine's body limit, and the chunking caps each statement's size.\n- **Row-value `IN`.** It needs SQLite 3.15 or newer. The Engine already relies on it in `fetch_seed_embeddings_for_likes`, so this adds no new dependency.\n- **Missing index.** No index on `(video_uuid, instance_domain)` is confirmed, so the uuid query may scan more than the id query. The old per-like resolve ran the same predicate 50 to 200 times, so one batched query is no worse. Adding an index is out of scope.\n- **Moving the id path into the helper.** Moving `fetch_metadata_by_ids`'s body touches the query every existing metadata caller uses. A regression test comparing id-keyed output before and after on a fixture DB guards against that.\n- **Shared test resources.** Test Engines share `whitelist.db` through the symlink. These endpoints only read it, but the fixture Engine's startup still touches the file.\n- **Engine rate limit.** Engine-backed test files need separate `validate_tests.py` invocations.\n- **Merge overlap.** Plan 13 edits `server.py` in wave 2, so the four edits stay local and are located by function name. `tests/last_test_validation.json` and `tests/last_test_output.txt` will conflict on merge: take main's copy and re-run `--compare`.\n\n### Tradeoffs the operator accepts\n\n- Likes past the 50th in a request are dropped silently, not rejected.\n- Import no longer records videos at or over the Engine's error-count threshold (ADR-0003).\n- Videos with an empty or mismatched embedding blob now appear on the likes page and are imported, where resolve used to drop them (already approved).\n- When several videos share a uuid and host, the lowest-`video_id` eligible one is chosen.\n- Deduplication of browser likes happens only on the Engine.\n</initial_solution>\n\n<conflicts>\nnone\n</conflicts>",
    "step_3_identify_impacts": "<impacts>\n\n<impacts>\n<impact path=\"engine/server/data/metadata.py\" element=\"fetch_metadata_by_ids (lines 110-205): body moves into a new private helper\">\n**What changes.** The helper takes over:\n- the 29-column SELECT (lines 133-162), which is `FROM video_embeddings e JOIN videos v ... LEFT JOIN channels c`;\n- the optional `error_count` clause (lines 127-130), added only when `error_threshold > 0`, with its parameter appended after the pair parameters;\n- the row-dict build (lines 174-204).\n\n`fetch_metadata_by_ids` keeps its signature `(conn, entries, error_threshold=None) -> dict[str, dict]` and its `if not entries: return {}` early return. It still builds its 450-entry chunks through `_chunk` (line 105), its `OR` of `(v.video_id = ? AND v.instance_domain = ?)`, and its params from `entry.get(\"video_id\")` and `entry.get(\"instance_domain\") or \"\"`. Its result is still keyed on `like_key(row)` (`video_id::instance_domain`, `engine/server/api/recommendations/keys.py:8`).\n\n**What depends on it.**\n- `handle_internal_videos_metadata` (`engine/server/api/handlers/internal_client_reads.py:113`).\n- `similarity_candidates._build_rows` (`engine/server/data/similarity_candidates.py:170` and `:175`), which feeds similar and up-next rows. The plan's caller list does not name it (see its own entry).\n\n**Regression risk: medium.**\n- The threshold parameter must stay last. It must be appended once per chunk, not once per call, or chunks after the first get the wrong parameter count.\n- The row dict must keep exactly the same 29 keys. The uuid path keys on `video_uuid`/`instance_domain`, and `record_like` on import reads `video_id`/`video_uuid`/`instance_domain`.\n- The id path keys the helper's output with `like_key`, which accepts dicts and `sqlite3.Row` (keys.py:10-15).\n- If the helper takes an ORDER BY or sorts for the uuid caller, the id path's result is still a dict, so ordering cannot change what id callers see. The helper's signature must let the uuid caller order by `v.video_id`, or the uuid caller must sort in Python.\n- Nothing in `tests/active` exercises this function directly today. It is covered only indirectly by the live-Engine tests (`test_server.py`, `test_blocks.py`, `test_similar.py`, `test_profiles.py`).\n</impact>\n<impact path=\"engine/server/data/metadata.py\" element=\"new fetch_metadata_by_uuids (sibling function)\">\n**What changes.**\n- A new public function, `(conn, entries, error_threshold=None)`, in the style of its sibling, with a docstring (every function in the file has one).\n- It deduplicates `(video_uuid, instance_domain)` pairs, chunks them at 450 with `_chunk`, and runs `WHERE (v.video_uuid, v.instance_domain) IN ((?, ?), ...)` through the shared helper, ordered by `v.video_id`. The row-value form is the one already used at `engine/server/data/embeddings.py:228`.\n- It keeps the first row per `video_uuid::instance_domain`, keyed from the row's own values, and returns that dict.\n\n**What depends on it.** Only the new handler path.\n\n**Regression risk: low for existing callers (new code), medium for correctness.**\n- The match is a binary TEXT comparison, so it is exact and case-sensitive, like `_fetch_seed_by_uuid` (embeddings.py:134-139).\n- The lowest `video_id` is chosen among rows that pass the error filter. This is the plan's stated interpretation.\n- The inner join cannot fan out if `video_embeddings` is keyed on `(video_id, instance_domain)`. I did not re-open the schema DDL in this pass; the previous record cites `build-video-embeddings.py:73`.\n- 450 pairs is 900 bound values plus 1 threshold, which stays under 999.\n- An empty `entries` must return `{}` without a query, mirroring line 116.\n- **The plan's \"Missing index\" risk is wrong.** `CREATE INDEX IF NOT EXISTS idx_videos_uuid_instance ON videos (video_uuid, instance_domain)` exists at `engine/server/data/videos.py:21-22` and is created on every Engine start (`engine/server/api/server.py:337`, `ensure_video_indexes(db)`). A temp-DB unit test will not have the index unless it calls `ensure_video_indexes`. That does not affect correctness.\n</impact>\n<impact path=\"engine/server/data/metadata.py\" element=\"fetch_metadata (rowid-keyed, lines 11-102), _chunk (105-107), module imports (1-8)\">\n**What changes.** Nothing. `fetch_metadata` stays a separate copy of most of the SELECT and row dict, and `_chunk` is reused.\n\n**What depends on it.** `fetch_metadata` is used by similar.py, ann.py, random_videos.py and search.py; the previous record lists these and I did not re-check them.\n\n**Regression risk: none if the diff stays out of lines 11-102.**\n\n**Test-design note.** The module imports only `sqlite3`, `typing` and `recommendations.keys`, and `recommendations/__init__.py` imports only `typing`. So `data.metadata` can be imported in the pytest interpreter in-process, the way `tests/active/test_internal_events.py:25-36` imports `data.*`. The data-layer tests (id output unchanged, uuid lookup, lowest `video_id`, threshold) do not need an `ENGINE_PY` subprocess. Only the handler does, because `internal_client_reads` imports numpy.\n</impact>\n<impact path=\"engine/server/data/similarity_candidates.py\" element=\"_build_rows (lines 155-212), direct caller of fetch_metadata_by_ids\">\n**What changes.** No edit.\n\n**Why it matters.** It calls `fetch_metadata_by_ids` both with and without `server.db_lock` (lines 169-179), looks rows up with `metadata.get(like_key(entry))` (line 195), and compares `like_key(meta)` with the source key (line 198). Its entries come from the ANN index or cache and can carry extra keys or a `None` instance_domain. The refactored function must go on reading only `entry.get(\"video_id\")` and `entry.get(\"instance_domain\") or \"\"`.\n\n**Regression risk: medium, and the plan's caller list does not name it.** A drift in keying, row content or per-chunk parameters would silently empty or alter similar and up-next pages. It is covered only indirectly, by the live-Engine `tests/active/test_similar.py`.\n</impact>\n<impact path=\"engine/server/api/handlers/internal_client_reads.py\" element=\"new metadata entry parser beside _parse_entries (line 20)\">\n**What changes.** A second parser, used only by `handle_internal_videos_metadata`. It mirrors `_parse_entries`:\n- `isinstance(body, dict)` guard;\n- returns None when `entries` is not a list;\n- skips non-dict items and items without a non-empty stripped string `instance_domain`.\n\nBeyond that:\n- A valid `video_id` means id form, even when a uuid is also present. Otherwise a valid `video_uuid` means uuid form. Anything else is skipped.\n- Duplicates are removed per form (id form on `_like_key`, uuid form on `video_uuid::instance_domain`), keeping the first.\n- It returns one ordered, tagged list. It needs a docstring.\n\n**What depends on it.** `handle_internal_videos_metadata` only.\n\n**Regression risk: medium.**\n- The id-form entries handed to `fetch_metadata_by_ids` must be the same stripped `{video_id, instance_domain}` dicts `_parse_entries` builds.\n- **Behaviour change for id callers.** An item with an empty or whitespace `video_id` but a valid `video_uuid` was skipped before. Now it resolves through the uuid form.\n  - `_handle_user_profile_likes_get` sends `fetch_recent_likes` rows, which carry `video_id`, `video_uuid`, `instance_domain` and `updated_at` (`client/backend/lib/users_store.py:126-141`).\n  - `record_like` stores `str(video.get(\"video_id\") or \"\")` (users_store.py:90), so a stored like with an empty id would now appear.\n  - Every current writer passes a canonical non-empty id: server.py:775 checks it, and import uses Engine rows. No such rows are expected.\n</impact>\n<impact path=\"engine/server/api/handlers/internal_client_reads.py\" element=\"handle_internal_videos_metadata (lines 95-126)\">\n**What changes.**\n- The new parser replaces the `_parse_entries` call at line 103. The 400 `Missing entries` (104-106) and the empty 200 before any lock (108-110) stay.\n- The entries split into an id list and a uuid list.\n- One `with server.db_lock:` calls `fetch_metadata_by_ids` and/or `fetch_metadata_by_uuids`, skipping an empty list, both with `error_threshold=getattr(server, \"video_error_threshold\", None)`.\n- After the lock is released, an ordered walk looks each entry up in its form's own dict and emits the row once, keyed on the row's `video_id::instance_domain`.\n- The response `{\"ok\", \"count\", \"rows\"}` does not change.\n- The docstring (\"canonical (video_id, instance_domain) entries\") must be updated.\n\n**What depends on it.**\n- The route, dispatched from `engine/server/api/handlers/similar.py:402-404` behind `_bridge_authorized` (line 394).\n- Client callers through `fetch_metadata_for_entries`: `_handle_user_profile_likes_get` (server.py:1006), `_handle_block_add` (server.py:947), and after this change `_handle_user_profile_likes_from_client` and `_handle_likes_import`.\n\n**Regression risk: medium-high.**\n- Id-only bodies must give the same rows in the same order: today's loop (lines 119-123) emits in entry order.\n- Cross-form dedup must key on the returned row, not the entry, or a video reached by both forms appears twice.\n- The id dict and the uuid dict must stay separate, because both key formats are `x::y` strings and could collide.\n- `db_lock` is a plain lock, so it must be taken once in the handler and never inside the data functions.\n- **Statement deadline.** `do_POST` (`similar.py:355-363`) runs the whole request, lock wait and both queries included, under one `statement_deadline`. A breach gives 503 `Query time limit exceeded`, which the Client sees as `EngineApiError` and answers with 502. Before, each resolve had its own budget. With 50 or fewer pairs on an index this is negligible.\n</impact>\n<impact path=\"engine/server/api/handlers/internal_client_reads.py\" element=\"_like_key (line 15), _parse_entries (20-48), handle_internal_dislike_centroids (129-158), handle_internal_video_resolve (51-92)\">\n**What changes.** Nothing (R1 and out of scope). Centroids keeps `_parse_entries`, so uuid-only entries there are skipped as malformed and do not count toward `DISLIKE_MAX_ENTRIES` (line 141). Resolve stays for `_handle_user_action` (server.py:758) and `_handle_block_add` (server.py:946).\n\n**Regression risk: low.** The risk is an accidental edit while the sibling parser is added. The centroids-ignores-uuid test guards it, and `tests/active/test_dislike_profile.py` covers centroids.\n</impact>\n<impact path=\"engine/server/api/handlers/internal_client_reads.py\" element=\"module imports (lines 4-12)\">\n**What changes.** Line 9 becomes `from data.metadata import fetch_metadata_by_ids, fetch_metadata_by_uuids`.\n\n**What depends on it.** `handlers/similar.py` imports this module at load time, so the whole Engine does. The module imports numpy (line 6), so a handler test must run under `conftest.ENGINE_PY`.\n\n**Regression risk: high impact, low probability.** A bad import name stops the Engine at startup, and every live-Engine test then fails in the `engine` fixture (`tests/active/conftest.py:101-137`).\n</impact>\n<impact path=\"engine/server/api/handlers/similar.py\" element=\"do_POST (355-363), _dispatch_post (390-410), module docstring line 11\">\n**What changes.** No edit. The route and its bridge auth are unchanged. The docstring \"internal Client metadata batch lookup\" stays accurate.\n\n**Why it matters.** This is where the single per-request statement deadline covers the new combined lookup (see the handler entry).\n\n**Regression risk: low.**\n</impact>\n<impact path=\"engine/server/api/handlers/__init__.py\" element=\"module docstring line 6\">\n**What changes.** Nothing required. \"internal_client_reads: internal read endpoints used by Client service\" stays true.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"engine/server/data/embeddings.py\" element=\"fetch_seed_embeddings_for_likes (191+), fetch_seed_embedding / _fetch_seed_by_uuid / _seed_from_row (104-188)\">\n**What changes.** Nothing.\n- `fetch_seed_embeddings_for_likes` is the precedent for the row-value `IN` (line 228). It is unchunked; the new function adds chunking.\n- `_fetch_seed_by_uuid` stays for `/internal/videos/resolve`.\n\n**Accepted differences from the old resolve path**, which the tests and the docs should state:\n- `_seed_from_row` dropped rows with an empty or mismatched embedding blob (line 178). The metadata path has no such check.\n- Resolve had no error filter and an arbitrary `LIMIT 1` (line 140). The new path is error-filtered and deterministic, choosing the lowest `video_id`.\n\n**Regression risk: none to this file.**\n</impact>\n<impact path=\"engine/server/data/videos.py\" element=\"ensure_video_indexes: idx_videos_uuid_instance (lines 21-22)\">\n**What changes.** Nothing.\n\n**Why it matters.** It disproves the plan's \"No index on (video_uuid, instance_domain) is confirmed\" risk. The uuid batch query can use this index. The plan's risk note should be corrected.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"engine/server/api/http_utils.py\" element=\"read_json_body 1,000,000-byte cap (lines 46-52)\">\n**What changes.** Nothing.\n\n**Why it matters.** It is the only bound on how many entries a direct bridge caller can put in one metadata body. A large body means several 450-pair statements under one lock hold, which is the same exposure the id path already has.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"engine/server/api/recommendations/keys.py\" element=\"like_key (line 8)\">\n**What changes.** Nothing.\n\n**Why it matters.** It keys the refactored id path and will likely key the handler's cross-form dedup. Its output format matches `_like_key` in internal_client_reads.py:15.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"client/backend/lib/engine_api_client.py\" element=\"resolve_videos_by_uuid_host (lines 136-166): deleted\">\n**What changes.** Removed (R6).\n\n**What depends on it.** Outside `delete_me/` and `docs/`, three sites use it: the import at `client/backend/server.py:32`, the call at `:888` (`_handle_likes_import`), and the call at `:1024` (`_handle_user_profile_likes_from_client`). No test references it.\n\n**Regression risk: low.** A missed site is an ImportError when `server.py` is imported, which `tests/active/conftest.py:39` surfaces across the whole suite. It is also named in the historical `docs/project/security-audit/run-1/REPORT.md:277` and `findings.json`, which must not be edited.\n</impact>\n<impact path=\"client/backend/lib/engine_api_client.py\" element=\"fetch_metadata_for_entries (lines 92-109), resolve_video_seed (66-89), _post_json (32-63)\">\n**What changes.**\n- No logic change. `fetch_metadata_for_entries` now also carries `{video_uuid, instance_domain}` entries. Its docstring (\"canonical video identity entries\") could mention the uuid form.\n- It returns `[]` with no HTTP call for an empty list (line 97), which the import path relies on.\n- It raises `EngineApiError` on a non-200 status or a bad payload.\n- `_post_json` has a 6 s timeout (line 32), which now bounds the whole likes page and the whole import, not each resolve.\n- `resolve_video_seed` stays.\n\n**Regression risk: low.**\n</impact>\n<impact path=\"client/backend/server.py\" element=\"engine_api_client import (lines 30-32)\">\n**What changes.** `resolve_videos_by_uuid_host` is dropped from the import. `fetch_metadata_for_entries` and `resolve_video_seed` stay.\n\n**Regression risk: low.** It could conflict on merge with plan 13 in the same block, so locate the edit by name.\n</impact>\n<impact path=\"client/backend/server.py\" element=\"MAX_CLIENT_LIKES = 200 \u2192 50 (line 52)\">\n**What changes.** The value.\n\n**Readers,** found by grep outside `delete_me/` and `docs/`:\n- line 493, the proxy trim;\n- line 886, `_handle_likes_import`;\n- line 1019, `_handle_user_profile_likes_from_client`.\n\nNo test reads it.\n\n**Context.** It sits beside `MAX_LIKES = 100` (line 51, out of scope) and `ENGINE_FEED_LIKES_MAX = 5` (line 55). It matches the browser's `MAX_LIKES = 50` (`client/frontend/src/data/local-likes.ts:25`) and ADR-0003.\n\n**Regression risk: low.** No `tests/active` test posts more than 50 likes; the import test posts 3.\n</impact>\n<impact path=\"client/backend/server.py\" element=\"/recommendations and /videos/similar POST proxy likes trim (lines 487-503)\">\n**What changes.** No code edit. `likes[:MAX_CLIENT_LIKES]` now cuts at 50 before malformed entries are skipped.\n\n**Context.**\n- A keyed request replaces the likes with at most 5 stored ones (lines 535-541).\n- The Engine answers 400 above `DEFAULT_CLIENT_LIKES_MAX` = 5 on both POST routes (`engine/server/README.md:24`). So a keyless body of 6-50 likes still gets the Engine's 400 forwarded.\n- The \"proxy forwards at most 50\" test therefore needs a capturing stand-in Engine, not the live one.\n\n**Regression risk: low.**\n</impact>\n<impact path=\"client/backend/server.py\" element=\"_parse_client_likes (lines 1105-1121)\">\n**What changes.** No edit. It cuts to `raw[:max_items]` before validation, returns stripped `{video_uuid, instance_domain}` dicts, and does not deduplicate. Its output keys are exactly the Engine parser's uuid form, and it now feeds `fetch_metadata_for_entries` directly.\n\nIt is distinct from the Engine's `handlers/similar.py:132` `_parse_client_likes`, which `tests/active/test_similar.py:259` patches.\n\n**Regression risk: low.** If its key names changed, the Engine would skip every entry and return an empty page without any error.\n</impact>\n<impact path=\"client/backend/server.py\" element=\"_handle_likes_import (lines 872-900)\">\n**What changes.**\n- Line 888 becomes one `fetch_metadata_for_entries(self.server.engine_ingest_base, likes)` call. The 502 text `Engine resolve failed: ...` (line 890) stays; plan 15 rewrites it.\n- The loop over the rows keeps `is_disliked(conn, profile_id, row[\"video_id\"], row[\"instance_domain\"])` and `record_like(conn, profile_id, \"like\", {video_id, video_uuid, instance_domain}, MAX_LIKES)` inside `with conn:`. `record_like` commits on its own (users_store.py:117), as it does today.\n- The response stays `{\"imported\": n}`.\n- The recording order is the Engine's first-match order, which equals submitted order. That keeps `updated_at` recency and the `MAX_LIKES` trim the same as today.\n\n**Behaviour changes (accepted):**\n- Videos at or over the error threshold are not imported.\n- Videos with a bad embedding blob are now imported.\n- On a uuid collision, the lowest `video_id` wins.\n\n**Regression risk: medium.**\n- It is covered by `tests/active/test_profiles.py:245` (live Engine). That test's dataset query already filters `error_count = 0` and joins embeddings (lines 225-230), so it should stay green.\n- Frontend coupling: `importLocalLikes` clears all local likes after any 2xx (`client/frontend/src/data/reactions.ts:81`). Likes past the 50th, unknown ones and errored ones are therefore lost. The browser already caps at 50.\n</impact>\n<impact path=\"client/backend/server.py\" element=\"_handle_user_profile_likes_from_client (lines 1012-1029)\">\n**What changes.**\n- Lines 1024-1025 become one `fetch_metadata_for_entries` call.\n- The empty-parse 200 (1020-1022), the 502 `Engine metadata failed: ...` (1027) and `{\"likes\": rows, \"updatedAt\"}` stay.\n- The docstring is a placeholder (\"Handle handle user profile likes from client.\") and could now state the one-call behaviour.\n\n**What depends on it.** The keyless likes page: `client/frontend/src/data/user-profile.ts:20-40` posts `{likes: [{uuid, host}]}` and renders `likes` in response order.\n\n**Regression risk: medium.** Order and dedup now rest entirely on the Engine's ordered walk. No existing test covers this POST route (a grep of `tests/active` finds no POST to `/api/user-profile/likes`). The planned stand-in-Engine tests fill that gap.\n</impact>\n<impact path=\"client/backend/server.py\" element=\"_handle_user_profile_likes_get (995-1010) and _handle_block_add (927-963): id-form callers\">\n**What changes.** No edit.\n- The GET sends `fetch_recent_likes` rows, which carry both `video_id` and `video_uuid`. With a non-empty id they are id form, so the rows and their order are unchanged.\n- Block-add sends a single `{video_id, instance_domain}`.\n\n**Tests.** `tests/active/test_server.py:94`, `test_blocks.py`, and `test_profiles.py` through reads.\n\n**Regression risk: low-medium.** See the parser entry for the empty-id-plus-uuid edge case.\n</impact>\n<impact path=\"client/backend/server.py\" element=\"_handle_user_action / _store_reaction (lines 730-870)\">\n**What changes.** Nothing. It still uses `resolve_video_seed` (line 758). Listed to confirm that `resolve_video_seed` must not be removed together with the batch function.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"client/backend/lib/users_store.py\" element=\"record_like (79-117), fetch_recent_likes (120-142)\">\n**What changes.** Nothing.\n- `record_like` reads only `video_id`, `instance_domain` and `video_uuid`, so a full metadata row or a three-key dict built from it both work.\n- `fetch_recent_likes` produces the id-form GET body.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"client/backend/lib/dislikes.py\" element=\"is_disliked\">\n**What changes.** Nothing. It is now called with the metadata row's `video_id` and `instance_domain` rather than the resolved entry's. The values are the same.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"client/frontend/src/data/local-likes.ts\" element=\"MAX_LIKES = 50 (line 25)\">\n**What changes.** Nothing; the frontend is out of scope. It is the bound ADR-0003 aligns to. The built bundle `client/frontend/dist/assets/key-rejected-*.js` carries `S=50`.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"client/frontend/src/data/reactions.ts\" element=\"importLocalLikes (lines 65-83)\">\n**What changes.** Nothing. It posts every local like and clears local storage on success (line 81), so likes the server drops or cannot resolve are cleared too.\n\n**Regression risk: low.**\n</impact>\n<impact path=\"client/frontend/src/data/user-profile.ts\" element=\"fetchUserProfileLikes keyless branch (lines 20-40)\">\n**What changes.** Nothing. It depends on the response order matching the submitted order.\n\n**Regression risk: low.**\n</impact>\n<impact path=\"tests/active/test_profiles.py\" element=\"test_importing_browser_likes_marks_each_imported_video_liked_and_no_other (line 245) and _embedded_videos (225-232)\">\n**What changes.** No edit expected. It must stay green, running against the live Engine in its own `validate_tests.py` invocation.\n\n**Regression risk: low.**\n</impact>\n<impact path=\"tests/active/test_server.py\" element=\"test_a_keyed_request_s_500_entry_exclude... (line 86; GET likes at line 94)\">\n**What changes.** No edit. It exercises the id-form metadata path end to end, and it is the existing check that id callers are unchanged. It runs in its own invocation.\n\n**Regression risk: low.**\n</impact>\n<impact path=\"tests/active/test_dislike_profile.py\" element=\"/internal/dislikes/centroids tests\">\n**What changes.** No edit. It guards `_parse_entries` and centroids. The new centroids-ignores-uuid check can live here or in the new Engine test file.\n\n**Regression risk: low.**\n</impact>\n<impact path=\"tests/active/test_blocks.py\" element=\"block-add tests\">\n**What changes.** No edit. It exercises resolve plus a single-entry id-form metadata call against the live Engine.\n\n**Regression risk: low.**\n</impact>\n<impact path=\"tests/active/conftest.py\" element=\"ENGINE_PY (30), client_backend (69-89), _engine_client (156-176), engine fixture (101-137)\">\n**What changes.** Probably no edit.\n- The `ClientBackendServer(..., engine_base, ...)` construction is the seam for pointing a Client at a capturing stand-in Engine.\n- `ClientBackend` exposes only `base` and `db_path`, so the new Client tests must build their own server. Alternatively a fixture can be added, but a fixture here is shared by every file.\n\n**Regression risk: low.**\n</impact>\n<impact path=\"tests/active/test_internal_events.py\" element=\"in-process data imports (25-36) and ENGINE_PY -c child (42-60, 173)\">\n**What changes.** Nothing. It is the right precedent for the new tests:\n- in-process `data.*` imports with `engine/server` and `engine/server/api` on `sys.path`, for the metadata data functions;\n- an `ENGINE_PY -c` child with `cwd=API_DIR` for the numpy-importing handler, patching `read_json_body`/`respond_json` on the handler module and handing it a stand-in server.\n\n**Correction to the plan.** The plan cites `test_db.py`, but `test_db.py:81` runs its child with `sys.executable`, not `ENGINE_PY`. `tests/active/test_similar.py:288-289` is the other `ENGINE_PY` child precedent.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"tests/active/test_db.py\" element=\"cited by the plan as the test pattern\">\n**What changes.** Nothing. It is listed only because the plan names it as the pattern, and it is the wrong one: it uses `sys.executable` and imports only `data.db`.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"tests/tmp/ (new Engine and Client test files)\">\n**What changes.** New tests.\n\n**Engine data layer, in-process:**\n- id output unchanged;\n- the uuid lookup;\n- lowest `video_id`;\n- the threshold on the uuid form.\n\n**Engine handler, `ENGINE_PY` child:**\n- parser forms and dedup;\n- mixed forms;\n- the same video once;\n- one lock enter, using a counting `db_lock`;\n- centroids ignores uuid.\n\n**Client, stdlib stand-in Engine:**\n- one call per request;\n- 60 entries reach the Engine as 50;\n- the proxy forwards at most 50;\n- unknown videos are omitted;\n- disliked videos are skipped on import.\n\n**Risks.**\n- The temp schema must include `videos` with every selected column plus `error_count` and `video_uuid`, `video_embeddings` with `embedding_dim` and `model_name`, and `channels` with `display_name` and `avatar_url`.\n- `video_embeddings` should have its real `(video_id, instance_domain)` primary key.\n- The stand-in Engine must answer `/internal/videos/metadata` and record the bodies.\n</impact>\n<impact path=\"tests/last_test_validation.json\" element=\"tracked test record (and tests/last_test_output.txt)\">\n**What changes.** Regenerated by the runs. It conflicts on merge: take main's copy and re-run `--compare`.\n\n**Regression risk: merge-process only.**\n</impact>\n<impact path=\"delete_me/ (server.py.bak-* and similar stale copies)\">\n**What changes.** Nothing. These files match greps for `resolve_videos_by_uuid_host` and `MAX_CLIENT_LIKES`, but they are not imported. Do not edit them and do not count them as readers.\n\n**Regression risk: none.**\n</impact>\n</impacts>\n\n</impacts>\n\n<docs_checklist>\n<doc path=\"client/README.md\">\n- **Line 15** (`POST /api/profile/likes/import`): add that at most 50 likes per body are read and the rest are dropped. A video the Engine does not know, or holds at or over its error threshold, is not imported (ADR-0003).\n- **Line 22** (`POST /api/user-profile/likes`): add that it resolves up to 50 browser likes in one Engine metadata call, in submitted order, deduplicated, and that unknown videos are omitted.\n- **Lines 30 and 37-39** stay accurate: `/internal/videos/resolve` is still used by user actions and block-add.\n</doc><doc path=\"engine/server/README.md\">\nLine 11 (`/internal/videos/metadata`): entries may be `{video_id, instance_domain}` or `{video_uuid, instance_domain}`, mixed. An entry with both uses `video_id`. All entries are answered under one lock hold, one row per video, in first-matching-entry order. Where several videos share a uuid and host, the lowest `video_id` wins. Line 10 (resolve) is unchanged.\n</doc><doc path=\"docs/project/adr/0003-metadata-endpoint-accepts-uuid-entries.md\">\nThe decision is unchanged. Optionally add two consequences under Consequences: the lowest-`video_id` rule for a shared `(video_uuid, instance_domain)`, and that videos with an empty or mismatched embedding blob now appear on the likes page and are imported.\n</doc><doc path=\"docs/project/issues/03-batch-like-resolution.md\">\nAt harvest on main: set `Status: bug, complete`, add a delivery comment, and move the file to `docs/project/issues/archive/` (per `docs/project/triage-labels.md`).\n</doc><doc path=\"docs/project/plans/14-batch-like-resolution.md\">\nAt harvest on main, archive it together with `16-14-batch-like-resolution.md` and its record, in `docs/project/plans/archive/`. Correct the plan text in `16-14-batch-like-resolution.md` in two places:\n- **Missing index:** `idx_videos_uuid_instance` exists (`engine/server/data/videos.py:21`).\n- **Test pattern:** the handler tests follow `test_internal_events.py`/`test_similar.py` (`ENGINE_PY` child), not `test_db.py`, and the data-layer tests can run in-process.\n</doc>\n</docs_checklist>\n\n<highest_risk>\nengine/server/data/metadata.py fetch_metadata_by_ids refactor into the shared helper: every existing consumer goes through it, including similarity_candidates._build_rows (similar and up-next pages), which the plan's caller list omits. A drift in per-chunk parameters, threshold placement, row-dict keys or like_key keying silently empties or alters rows, and no in-process test covers this function today.\nengine/server/api/handlers/internal_client_reads.py handle_internal_videos_metadata plus the new parser: id-only bodies must give identical rows and order; cross-form dedup must key on the returned row's video_id::instance_domain with the id and uuid dicts kept separate; db_lock must be taken exactly once; and a bad import on line 9 stops the whole Engine at startup (loaded by handlers/similar.py).\nclient/backend/server.py _handle_likes_import: it now relies on Engine metadata rows for record_like and is_disliked and inherits the error-threshold filter, while importLocalLikes clears every local like on any 2xx (client/frontend/src/data/reactions.ts:81). So a like the server drops (past the 50th, unknown or errored) is lost for good with no retry.\n</highest_risk>",
    "step_4_reassess": "<summary>\nI checked the inventory against the files it names, and every entry I opened held up. The plan still works. The main points:\n- **Engine data layer.** `metadata.py:110-205` is as described: `if not entries: return {}`, 450-entry `_chunk` batches, the `OR` fragment, and the threshold clause added only when `error_threshold > 0`. That clause is appended once per chunk, after the pair parameters. The 29-column SELECT and row dict are keyed on `like_key(row)`.\n- **The two callers.** `similarity_candidates.py:170,175` call `fetch_metadata_by_ids` with and without the lock, and look rows up with `like_key(entry)` at 195 and 198.\n- **Handler.** `internal_client_reads.py` has `_parse_entries` at 20-48 and the metadata handler at 95-126, where one lock hold is followed by an entry-order walk on `_like_key`. Centroids uses `_parse_entries` at 137.\n- **Schema.** `video_embeddings` has `PRIMARY KEY (video_id, instance_domain)` (`build-video-embeddings.py:73`), so the inner join cannot fan out. `idx_videos_uuid_instance` exists (`videos.py:21-22`) and is created at `server.py:337`.\n- **Row-value precedent.** It is at `embeddings.py:228`, unchunked. Resolve's `LIMIT 1` is at 140 and the blob check at 178.\n- **Statement deadline.** `similar.py:355-363` wraps `_dispatch_post` in one `_statement_deadline`. The route is at 402-404, behind `_bridge_authorized` at 394.\n- **Client side.** The resolve loop is at `engine_api_client.py:136-166`. `fetch_metadata_for_entries` returns `[]` for an empty list (97), and `_post_json` has a 6 s timeout. In `server.py`:\n  - the import is at 30-32 and `MAX_CLIENT_LIKES = 200` at 52;\n  - the proxy trim at 493 cuts before it validates;\n  - `_handle_likes_import` is at 872-900, block-add at 927-963, the likes GET at 995-1010 and the likes POST at 1012-1029;\n  - `_parse_client_likes` is at 1105-1121: it cuts, then validates, and does not deduplicate.\n- **Other call sites.** `record_like` and `fetch_recent_likes` match. Outside `delete_me/` and `docs/`, the three `MAX_CLIENT_LIKES` readers and the three `resolve_videos_by_uuid_host` sites are the only ones.\n- **Tests.** The citations match: `test_db.py:81` (uses `sys.executable`), `test_internal_events.py:173` and `test_similar.py:289` (`ENGINE_PY` children), the `ClientBackend(base, db_path)` fixture at `conftest.py:46-89`, and `test_profiles.py:223-253`.\n\nThe last step-4 pass added the per-request statement deadline as a new impact. The inventory now carries it in the handler and `similar.py` entries. I found nothing else missing.\n<question id=\"1\">\nYes.\n- **Id-only bodies.** They run the same SQL with the same parameters in the same order and emit rows in entry order. `_build_rows`, the likes GET and block-add therefore see identical results.\n- **Uuid entries.** They go through an exact match on both columns. The pick is deterministic, and `video_embeddings` has one row per video, so no join fans out. Two distinct uuid pairs cannot land on the same video, because a video has exactly one `video_uuid`. Duplicates can only come from the same video reached by both forms, and the post-lock walk keyed on the row's `video_id::instance_domain` removes those.\n- **Likes page.** The old flow deduplicated on `uuid::host` in submitted order, resolved each pair, then ran metadata by id in that order. The new flow gives the same rows in the same order. The only differences are the ones the operator already accepted: no embedding-blob check, the error filter applied before the lowest-`video_id` pick, and import filtered by error count.\n- **Test harness.** `_proxy_engine_request` (server.py:565), the metadata calls and resolve all use the single `engine_ingest_base`. So one capturing stand-in Engine sees both the proxy request and the metadata call, and the planned Client tests are feasible as designed.\n</question>\n<question id=\"2\">\nAll of these are already in the inventory:\n- **Load.** A likes-page or import request makes one Engine round trip and takes `db_lock` once, running one or two indexed statements. Before, it made up to 51 round trips, or 201 at the old cap.\n- **Timeouts.** One statement deadline and one 6 s Client timeout now cover the whole batch, where before each resolve had its own.\n- **Similar and up-next.** These pages now run through the refactored helper, so a drift in parameters or row keys would change them silently.\n- **Browser storage.** `importLocalLikes` clears browser storage after any 2xx (`reactions.ts:81`). Likes that are dropped, unknown or errored are therefore lost for good.\n- **Proxy.** Keyless bodies of 6-50 likes still get the Engine's 400 forwarded.\n</question>\n<question id=\"3\">\nNo code beyond the plan is needed. The conditions in the inventory are what keep things working:\n- **Helper.** It takes the connection only, never the lock, because `db_lock` is non-reentrant. It reads only `entry.get(\"video_id\")` and `entry.get(\"instance_domain\") or \"\"`. It appends the threshold once per chunk, as the last parameter. It lets the uuid caller order by `v.video_id`.\n- **Handler.** It keeps the id dict and the uuid dict separate, and deduplicates on the returned row's key.\n- **Import.** `_handle_likes_import` keeps `is_disliked` and `record_like` inside `with conn:`.\n- **Imports.** Line 9 of `internal_client_reads.py` must import the new name correctly, or the Engine fails at startup.\n- **Test fixtures.** The temp schema carries the real `video_embeddings` primary key. Client tests build their own `ClientBackendServer` pointed at the stand-in, as `conftest.py:161-168` does. The import test must first mint a profile, which needs no Engine call.\n</question>\n<question id=\"4\">\n**Unchanged:** the id-keyed contract (same rows, order and response shape), `/internal/dislikes/centroids`, `/internal/videos/resolve`, and user actions and block-add.\n\n**Exception:** an entry with an empty `video_id` but a valid `video_uuid` used to be skipped and now resolves through the uuid form. No current writer produces such an entry.\n\n**Changed:**\n- `/internal/videos/metadata` also accepts `{video_uuid, instance_domain}` entries.\n- Import skips videos at or over the error threshold.\n- The likes page and import both include videos with a bad embedding blob.\n- On a shared uuid and host, the lowest eligible `video_id` wins.\n- Each request body is cut at 50 likes instead of 200, on the likes page, the import and the proxy.\n- Browser likes are deduplicated only on the Engine.\n- `resolve_videos_by_uuid_host` is gone.\n- An Engine timeout now fails the whole likes page or import with a 502.\n</question>\n</summary>\n\n<new_impacts>\nnone\n</new_impacts>\n\n<unconfirmed>\nnone\n</unconfirmed>\n\n<new_conflicts>\nnone\n</new_conflicts>\n\n<recommendations>\n1. Proceed with the plan as it stands. The inventory has converged: no new impacts, and no conflicts with the requirements or the plan. Cost: none.\n2. Record two corrections in the plan's risks. First, the \"Missing index\" risk is wrong: `idx_videos_uuid_instance` (`engine/server/data/videos.py:21-22`) serves the uuid query and is created at every Engine start. Second, the Engine handler tests should follow the `ENGINE_PY` child pattern in `test_internal_events.py:173` and `test_similar.py:289`, not `test_db.py`, and the `data.metadata` tests can run in-process. Cost: plan wording only, with no change to behaviour or scope. Both corrections are already in the inventory and the docs checklist; this is a reminder that the plan text still carries the old wording.\n3. Optional: when the stand-in Engine is built, give it a mode that answers 503, and add two cases showing the likes page and the import each answer 502 with nothing imported. This covers the single-deadline ramification before plan 15 rewrites those 502 bodies. Cost: one extra response mode and about two test cases in a harness the plan already builds. Skip it if plan 15 will add its own 502 tests.\n</recommendations>",
    "step_5_draft_implementation": "<draft>\n## Draft implementation: batch like resolution (plan 14, issue 03)\n\nThis draft converged on the first pass against the plan and R1 to R7. The pass-by-pass check is at the end. All paths are relative to the worktree `/home/enduser/code/PeerTube-browser/.worktrees/fix-14-batch-like-resolution`.\n\n### Module map\n\n| File | Change |\n|---|---|\n| `engine/server/data/metadata.py` | New private `_select_metadata` (the SELECT, the joins, the error clause, the row dict). `fetch_metadata_by_ids` becomes a thin caller of it. New `fetch_metadata_by_uuids` and private `_uuid_key`. `fetch_metadata` (lines 11-102) and `_chunk` are untouched. |\n| `engine/server/api/handlers/internal_client_reads.py` | Import line 9 widened. New `_uuid_key` and `_parse_metadata_entries`. `handle_internal_videos_metadata` rewritten. `_parse_entries`, centroids and resolve are untouched. |\n| `client/backend/lib/engine_api_client.py` | `resolve_videos_by_uuid_host` deleted. The `fetch_metadata_for_entries` docstring now names both entry forms. |\n| `client/backend/server.py` | Import (lines 30-32), `MAX_CLIENT_LIKES = 50`, `_handle_likes_import`, `_handle_user_profile_likes_from_client`. The proxy trim at line 493 is unchanged in code. |\n| `tests/tmp/test_metadata_uuid_entries.py` | New. Tests for the Engine data layer (in-process) and the handler (an `ENGINE_PY` child). |\n| `tests/tmp/test_client_like_batching.py` | New. Client tests against a capturing stand-in Engine. |\n\nNo new dependency, endpoint or module outside the tests.\n\n---\n\n### 1. `engine/server/data/metadata.py`\n\n**`_select_metadata(conn, where, params, error_threshold) -> list[dict[str, Any]]`**\n- It is shared by exactly two callers, so it is not a single-implementation abstraction.\n- **Invariant:** it builds a fresh parameter list per call, so the threshold is appended once per chunk and always last.\n- **Invariant:** it builds the row dict in one place only, so a video's row is identical whichever form reached it.\n- It never takes `db_lock`.\n\n```python\ndef _select_metadata(\n    conn: sqlite3.Connection,\n    where: str,\n    params: list[Any],\n    error_threshold: int | None,\n) -> list[dict[str, Any]]:\n    \"\"\"Run the metadata SELECT for one chunk's WHERE fragment and return the built row dicts.\"\"\"\n    query_params = list(params)\n    error_clause = \"\"\n    if error_threshold is not None and error_threshold > 0:\n        error_clause = \"AND (v.error_count IS NULL OR v.error_count < ?)\"\n        query_params.append(error_threshold)\n    rows = conn.execute(\n        f\"\"\"\n        SELECT\n          v.video_id,\n          ... (lines 134-162 verbatim, 29 columns) ...\n          e.model_name\n        FROM video_embeddings e\n        JOIN videos v\n          ON v.video_id = e.video_id AND v.instance_domain = e.instance_domain\n        LEFT JOIN channels c\n          ON c.channel_id = v.channel_id AND c.instance_domain = v.instance_domain\n        WHERE {where}\n          {error_clause}\n        \"\"\",\n        query_params,\n    ).fetchall()\n    return [\n        {\n            \"video_id\": row[\"video_id\"],\n            ... (lines 175-203 verbatim, 29 keys) ...\n            \"model_name\": row[\"model_name\"],\n        }\n        for row in rows\n    ]\n```\n\nThe WHERE fragment is wrapped as `WHERE ({where})`, in parentheses, so that the `AND` error clause binds to the whole `OR` chain. In today's SQL, `WHERE a OR b AND (err)` binds `AND` tighter than `OR`. That means the existing id query applies the threshold only to the last pair of each chunk.\n\nThis is a live pre-existing bug on the id path, and it would change R3's \"id callers see exactly the rows they saw before\". **See \"Open item A\" below: the draft does not silently pick one side.**\n\n**`fetch_metadata_by_ids`**\n\nThe signature, the early return, the 450-entry chunks, and the params from `entry.get(\"video_id\")` / `entry.get(\"instance_domain\") or \"\"` all stay the same.\n\n```python\ndef fetch_metadata_by_ids(\n    conn: sqlite3.Connection,\n    entries: list[dict[str, Any]],\n    error_threshold: int | None = None,\n) -> dict[str, dict[str, Any]]:\n    \"\"\"Fetch video metadata for (video_id, instance_domain) pairs.\"\"\"\n    if not entries:\n        return {}\n    result: dict[str, dict[str, Any]] = {}\n    for batch in _chunk(entries, 450):\n        conditions = \" OR \".join([\"(v.video_id = ? AND v.instance_domain = ?)\"] * len(batch))\n        params: list[Any] = []\n        for entry in batch:\n            params.append(entry.get(\"video_id\"))\n            params.append(entry.get(\"instance_domain\") or \"\")\n        for row in _select_metadata(conn, conditions, params, error_threshold):\n            result[like_key(row)] = row\n    return result\n```\n\n`similarity_candidates._build_rows` keeps working unchanged. It reads the same keys and gets the same dicts, keyed by `like_key`.\n\n**`fetch_metadata_by_uuids`**\n\n```python\ndef _uuid_key(entry: dict[str, Any]) -> str:\n    \"\"\"Handle uuid key.\"\"\"\n    return f\"{entry.get('video_uuid') or ''}::{entry.get('instance_domain') or ''}\"\n\n\ndef fetch_metadata_by_uuids(\n    conn: sqlite3.Connection,\n    entries: list[dict[str, Any]],\n    error_threshold: int | None = None,\n) -> dict[str, dict[str, Any]]:\n    \"\"\"Fetch video metadata for (video_uuid, instance_domain) pairs, one row per pair.\n\n    The match is exact on both columns. Where several videos share a pair, the one with the lowest\n    video_id among those under the error threshold is kept.\n    \"\"\"\n    pairs: dict[str, tuple[str, str]] = {}\n    for entry in entries:\n        pair = (str(entry.get(\"video_uuid\") or \"\"), str(entry.get(\"instance_domain\") or \"\"))\n        pairs.setdefault(_uuid_key({\"video_uuid\": pair[0], \"instance_domain\": pair[1]}), pair)\n    if not pairs:\n        return {}\n    result: dict[str, dict[str, Any]] = {}\n    for batch in _chunk(list(pairs.values()), 450):\n        placeholders = \", \".join([\"(?, ?)\"] * len(batch))\n        params = [value for pair in batch for value in pair]\n        for row in _select_metadata(conn, f\"(v.video_uuid, v.instance_domain) IN ({placeholders})\", params, error_threshold):\n            key = _uuid_key(row)\n            if key not in result or row[\"video_id\"] < result[key][\"video_id\"]:\n                result[key] = row\n    return result\n```\n\n**Decision: pick the lowest id in Python rather than with `ORDER BY`.** The impact entry allows it (\"or the uuid caller must sort in Python\").\n- The helper then needs no ordering parameter, and the id query is not given a useless sort.\n- The pick does not depend on row order or on chunking.\n- SQLite's BINARY collation compares UTF-8 bytes. Byte order equals code-point order, which is how Python orders `str`, so \"lowest `video_id`\" means the same in both.\n\n**Other invariants:**\n- 450 pairs is 900 values plus 1 threshold, under 999.\n- `video_embeddings` has `PRIMARY KEY (video_id, instance_domain)` (`sync-whitelist.py:391`), so the inner join cannot fan out.\n- The query can use `idx_videos_uuid_instance` (`data/videos.py:21`).\n\n---\n\n### 2. `engine/server/api/handlers/internal_client_reads.py`\n\nLine 9:\n```python\nfrom data.metadata import fetch_metadata_by_ids, fetch_metadata_by_uuids\n```\n\n**New helpers beside `_like_key` and `_parse_entries`.** `_uuid_key` duplicates the private one in `metadata.py` on purpose. The file already mirrors `recommendations.keys.like_key` with its own `_like_key`, and the settled import line names only the two fetch functions. A drift between the two copies fails the mixed-forms test.\n\n```python\ndef _uuid_key(entry: dict[str, Any]) -> str:\n    \"\"\"Handle uuid key.\"\"\"\n    return f\"{entry.get('video_uuid') or ''}::{entry.get('instance_domain') or ''}\"\n\n\ndef _stripped(value: Any) -> str | None:\n    \"\"\"Return a non-empty stripped string, or None.\"\"\"\n    return value.strip() or None if isinstance(value, str) else None\n\n\ndef _parse_metadata_entries(body: Any) -> list[tuple[str, dict[str, str]]] | None:\n    \"\"\"Return the distinct well-formed metadata entries of a body, tagged \"id\" or \"uuid\", in order.\n\n    An item with a valid video_id is id-keyed even if it also carries video_uuid; duplicates are\n    dropped per form, keeping the first.\n    :returns: None when `entries` is not a list; malformed items are skipped.\n    \"\"\"\n    raw_entries = body.get(\"entries\") if isinstance(body, dict) else None\n    if not isinstance(raw_entries, list):\n        return None\n    entries: list[tuple[str, dict[str, str]]] = []\n    seen: set[tuple[str, str]] = set()\n    for raw in raw_entries:\n        if not isinstance(raw, dict):\n            continue\n        instance = _stripped(raw.get(\"instance_domain\"))\n        if instance is None:\n            continue\n        video_id = _stripped(raw.get(\"video_id\"))\n        video_uuid = _stripped(raw.get(\"video_uuid\"))\n        if video_id is not None:\n            form, entry = \"id\", {\"video_id\": video_id, \"instance_domain\": instance}\n            key = _like_key(entry)\n        elif video_uuid is not None:\n            form, entry = \"uuid\", {\"video_uuid\": video_uuid, \"instance_domain\": instance}\n            key = _uuid_key(entry)\n        else:\n            continue\n        if (form, key) in seen:\n            continue\n        seen.add((form, key))\n        entries.append((form, entry))\n    return entries\n```\n\nTwo notes on the helpers:\n- `_stripped` binds as `(value.strip() or None) if ... else None`. The parenthesised form is what gets written.\n- Tagging the seen-set with the form keeps the id and uuid key spaces apart, since both are `x::y` strings.\n\n**Handler**\n\n```python\ndef handle_internal_videos_metadata(handler: Any, server: Any) -> bool:\n    \"\"\"Return metadata rows for (video_id, instance_domain) and (video_uuid, instance_domain) entries.\n\n    Both forms are answered under one db_lock hold; each video appears once, at its first matching entry.\n    \"\"\"\n    try:\n        body = read_json_body(handler)\n    except ValueError as exc:\n        respond_json(handler, 400, {\"error\": str(exc)})\n        return True\n\n    entries = _parse_metadata_entries(body)\n    if entries is None:\n        respond_json(handler, 400, {\"error\": \"Missing entries\"})\n        return True\n\n    if not entries:\n        respond_json(handler, 200, {\"ok\": True, \"count\": 0, \"rows\": []})\n        return True\n\n    id_entries = [entry for form, entry in entries if form == \"id\"]\n    uuid_entries = [entry for form, entry in entries if form == \"uuid\"]\n    error_threshold = getattr(server, \"video_error_threshold\", None)\n    by_id: dict[str, dict[str, Any]] = {}\n    by_uuid: dict[str, dict[str, Any]] = {}\n    with server.db_lock:\n        if id_entries:\n            by_id = fetch_metadata_by_ids(server.db, id_entries, error_threshold=error_threshold)\n        if uuid_entries:\n            by_uuid = fetch_metadata_by_uuids(server.db, uuid_entries, error_threshold=error_threshold)\n\n    rows: list[dict[str, Any]] = []\n    emitted: set[str] = set()\n    for form, entry in entries:\n        row = by_id.get(_like_key(entry)) if form == \"id\" else by_uuid.get(_uuid_key(entry))\n        if not isinstance(row, dict) or _like_key(row) in emitted:\n            continue\n        emitted.add(_like_key(row))\n        rows.append(row)\n\n    respond_json(handler, 200, {\"ok\": True, \"count\": len(rows), \"rows\": rows})\n    return True\n```\n\n**Why id-only callers see no change.**\n- An id-only request produces exactly the `_parse_entries` list, the same query, and the same entry-order walk.\n- `emitted` cannot drop a row here, because the parser has already deduplicated on the same key.\n\n**Deduplication across forms.** It keys on the returned row's `video_id::instance_domain`, never on the entry.\n\n---\n\n### 3. `client/backend/lib/engine_api_client.py`\n\n- Delete lines 136-166 (`resolve_videos_by_uuid_host`). `resolve_video_seed` stays.\n- New docstring for `fetch_metadata_for_entries`: `\"\"\"Fetch metadata rows from Engine for {video_id|video_uuid, instance_domain} entries, one row per video in first-entry order.\"\"\"`\n- No logic change. An empty list still returns `[]` with no HTTP call.\n\n---\n\n### 4. `client/backend/server.py`\n\n**Import (lines 30-32):**\n```python\nfrom lib.engine_api_client import (EngineApiError, bridge_headers, compute_dislike_centroids,\n                                   fetch_metadata_for_entries, resolve_video_seed)\n```\n\n**Cap (line 52):** `MAX_CLIENT_LIKES = 50`.\n- The grep found three readers: the proxy trim (line 493) and the two `_parse_client_likes` calls.\n- Matches in `delete_me/*.bak-*` are ignored.\n\n**`_handle_likes_import`**: from the `likes = ...` line on.\n- There is no pre-call empty check: `fetch_metadata_for_entries` returns `[]` for an empty list without calling the Engine, so the answer is `{\"imported\": 0}` as today.\n\n```python\n        likes = _parse_client_likes(body, MAX_CLIENT_LIKES)\n        try:\n            rows = fetch_metadata_for_entries(self.server.engine_ingest_base, likes)\n        except EngineApiError as exc:\n            respond_json(self, 502, {\"error\": f\"Engine resolve failed: {exc}\"})\n            return\n        conn = self.server.user_db\n        imported = 0\n        with conn:\n            for row in rows:\n                if is_disliked(conn, profile_id, row[\"video_id\"], row[\"instance_domain\"]):\n                    continue\n                video = {\"video_id\": row[\"video_id\"], \"video_uuid\": row[\"video_uuid\"], \"instance_domain\": row[\"instance_domain\"]}\n                record_like(conn, profile_id, \"like\", video, MAX_LIKES)\n                imported += 1\n        respond_json(self, 200, {\"imported\": imported})\n```\n\n**`_handle_user_profile_likes_from_client`**:\n\n```python\n    def _handle_user_profile_likes_from_client(self) -> None:\n        \"\"\"Answer a browser's local likes (uuid, host) with Engine metadata rows in one Engine call, deduplicated, in submitted order; unknown videos are omitted.\"\"\"\n        ...\n        likes = _parse_client_likes(body, MAX_CLIENT_LIKES)\n        if not likes:\n            respond_json(self, 200, {\"likes\": [], \"updatedAt\": now_ms()})\n            return\n        try:\n            rows = fetch_metadata_for_entries(self.server.engine_ingest_base, likes)\n        except EngineApiError as exc:\n            respond_json(self, 502, {\"error\": f\"Engine metadata failed: {exc}\"})\n            return\n        respond_json(self, 200, {\"likes\": rows, \"updatedAt\": now_ms()})\n```\n\nThe proxy code is unchanged. `_parse_client_likes` is unchanged; its output keys are exactly the Engine's uuid form.\n\n---\n\n### 5. Tests\n\n#### `tests/tmp/test_metadata_uuid_entries.py`\n\n**Setup**\n- `sys.path` gets `engine/server` and `engine/server/api`, as `test_internal_events.py:25-30` does. It then does `from data.metadata import fetch_metadata_by_ids, fetch_metadata_by_uuids` in-process: that module imports no numpy.\n- The handler part runs in an `ENGINE_PY -c` child with `cwd=API_DIR`. The child inserts the same two paths itself.\n- Correction to the plan: the pattern is `test_internal_events.py` / `test_similar.py`, not `test_db.py`.\n\n**Temp schema** (`row_factory = sqlite3.Row`):\n- `videos`: the 26 selected `v.*` columns, plus `error_count INTEGER`, with `PRIMARY KEY (video_id, instance_domain)`.\n- `video_embeddings (video_id, instance_domain, embedding BLOB, embedding_dim, model_name, PRIMARY KEY (video_id, instance_domain))`.\n- `channels (channel_id, instance_domain, display_name, avatar_url)`.\n- It does not call `ensure_video_indexes`; the index does not affect correctness.\n\n**Fixture videos**, all on host `h.example` unless noted:\n\n| video_id | video_uuid | error_count | embedding | purpose |\n|---|---|---|---|---|\n| a1 | u-a | 0 | yes | plain match |\n| b1 | u-b | NULL | yes | id and uuid paths reach the same video |\n| s2 (inserted first) | u-s | 0 | yes | shared pair: rowid order is not id order |\n| s1 | u-s | 0 \u2192 later 5 | yes | lowest id; errored sibling |\n| e1 | u-e | 5 | yes | over threshold 3 |\n| n1 | u-n | 0 | **no** | inner join drops it |\n| a1 on `other.example` | u-a | 0 | yes | exact host match |\n\n**Data-layer tests (in-process)**\n1. `fetch_metadata_by_ids` returns exactly the 29-key dict, keyed `a1::h.example`, with the values from the DB. It skips `n1`, and with threshold 3 it skips `e1`. The empty list gives `{}`.\n2. A 460-video set crosses the 450 chunk boundary on both functions with threshold 3. All 460 come back. The set includes one errored video in the second chunk, which must be absent; that catches a threshold parameter appended once per call.\n3. `fetch_metadata_by_uuids`:\n   - `u-a@h.example` gives `a1@h.example`, not the `other.example` one.\n   - `U-A` and `u-a@H.EXAMPLE` give nothing.\n   - `u-s` gives `s1`. After setting `s1.error_count = 5` with threshold 3, it gives `s2`.\n   - `u-e` gives nothing at threshold 3, and `e1` at threshold None.\n   - `u-n` gives nothing.\n   - The empty list gives `{}` and runs no query: the conn is wrapped so `execute` counts calls.\n4. The same video gives an identical dict through `by_ids[b1::h]` and `by_uuids[u-b::h]`.\n\n**Handler tests (one `ENGINE_PY` child per test group)**\n- The child patches `read_json_body` and `respond_json` on `handlers.internal_client_reads`.\n- Its server is `SimpleNamespace(db=conn, db_lock=CountingLock(), video_error_threshold=3)`. `CountingLock` wraps `threading.Lock` and counts `__enter__`.\n- It prints `[{status, payload, enters}]` for a list of bodies.\n\nCases:\n- Parser forms: an id item with a whitespace uuid; a uuid-only item; an item with both keys (id wins, shown by an id that differs from the uuid's video); a non-dict item; a missing or blank `instance_domain`; neither key; duplicates in each form.\n- `{\"entries\": \"x\"}` and `{}` give 400 `Missing entries`, with `enters == 0`.\n- All-malformed entries give 200 `{\"ok\": True, \"count\": 0, \"rows\": []}`, with `enters == 0`.\n- Id-only `[a1, b1, a1]` gives rows `[a1, b1]`, `count == 2` and `enters == 1`: the same as the old loop.\n- Mixed `[uuid u-b, id a1, id b1, uuid u-a, uuid u-x]` gives `[b1, a1]`: first-match order, each video once, unknown omitted, `enters == 1`.\n- Uuid `u-e` at threshold 3 is absent.\n- Centroids: `fetch_embeddings_by_ids` is spied (wraps). A uuid-only body gives 200, the spy gets `[]`, and `centroids == []`. A mixed body passes only the id entries.\n\n#### `tests/tmp/test_client_like_batching.py`\n\n**Seam**\n- A `ThreadingHTTPServer` stand-in Engine, written like `test_server.py:307`'s `EngineStub`. It records `(path, json body)` for every POST.\n- For `/internal/videos/metadata` it answers from a canned `{uuid::host: row}` table in entry order, omitting unknown entries and duplicates, which mimics the Engine.\n- For any other path it answers `{\"rows\": []}`.\n- The Client is built by local `_serving` and `_client_backend` copies of `test_server.py:251-271`, with `RateLimiter(1000, 60)`.\n\n**Tests**\n1. Likes page: 3 likes plus a duplicate plus an unknown give exactly one recorded Engine request, to `/internal/videos/metadata`. Its `entries` equal the `{video_uuid, instance_domain}` list as submitted (the Client does not dedup). The response `likes` holds the known rows in submitted order, with the unknown omitted.\n2. Likes page with 60 entries: 200, and the single request carries exactly the first 50.\n3. Likes page with an empty or all-malformed body: 200, `likes == []`, and zero Engine requests.\n4. Import: mint via `POST /api/profile`, then find `profile_id` via `resolve_profile(conn, key)` on a second connection to `users.db`. Write one dislike with `write_dislike(conn, profile_id, {...}, None)` and commit. Post 3 likes: the disliked video, a clean one, and an unknown one. This gives exactly one Engine request, `{\"imported\": 1}`, and `load_liked_keys(conn, profile_id) == {(clean_id, host)}`.\n5. Import with 60 entries: 200, and the one request carries 50.\n6. Proxy: a keyless `POST /recommendations` with 60 `{uuid, host}` likes. The recorded forwarded body has `likes` of length 50, equal to the first 50 sanitised.\n\n`test_profiles.py` and `test_server.py` stay unedited. They run against the live Engine, each in its own `validate_tests.py` invocation.\n\n---\n\n### Open item A \u2014 needs a call before the build\n\n**The problem.** The existing id SQL is `WHERE (a) OR (b) ... AND (v.error_count IS NULL OR v.error_count < ?)`. SQL gives `AND` higher precedence than `OR`, so today the threshold filters only the last pair of each chunk. Any other errored video requested by id is returned.\n\nThe settled requirements pull two ways:\n- R3 says \"id callers see exactly the rows they saw before\".\n- R2 says the uuid form uses \"the same error-count threshold clause\".\n\n**Options:**\n1. Keep today's id semantics exactly: the id caller passes an unparenthesised fragment. The uuid fragment is a single `IN` term, so its threshold applies to every row either way.\n2. Parenthesise, and fix the id path as well. That changes what id callers see: errored videos would drop from the GET likes page, block-add and similar or up-next.\n\n**The draft takes option 1 in code.** `_select_metadata` interpolates `WHERE {where}` without wrapping it, which matches R3 literally, and the uuid path is still fully filtered. I flag option 2 as a separate bug for the roadmap rather than fixing it silently here.\n\n**The test consequence.** The \"errored video in chunk 2\" test in 5.1 item 2 applies to `fetch_metadata_by_uuids` only. For `fetch_metadata_by_ids`, the chunk-crossing test asserts all non-errored rows are present and pins current behaviour with no assertion on the errored one.\n\n---\n\n### Corrections to the settled plan text (for the doc step)\n- **Missing index:** wrong. `idx_videos_uuid_instance` exists (`engine/server/data/videos.py:21-22`) and is created on every start.\n- **Test pattern:** `test_internal_events.py` / `test_similar.py`, not `test_db.py`. The data-layer tests run in-process.\n- **Id-path threshold precedence:** see Open item A. The plan's claim that the error clause is \"applied in SQL before the pick\" holds for the uuid path only.\n- **Tests in `tests/tmp` import `conftest`:** they rely on `tests/active/conftest.py` for `ENGINE_PY`, `client_server`, `RateLimiter` and `ensure_user_schema`. I did not verify how `validate_tests.py` puts that on `sys.path` for the working tree. If it does not, the files are promoted to `tests/active` before running.\n\n### Check against plan and requirements (pass 1, converged)\n- **R1:**\n  - `_parse_metadata_entries`: id wins when both keys are present.\n  - It deduplicates per form.\n  - It returns None, which gives 400.\n  - An empty parse answers 200 before the lock.\n  - `_parse_entries` and centroids are untouched.\n- **R2:**\n  - `fetch_metadata_by_uuids` has the same SELECT, joins, threshold and row dict via `_select_metadata`.\n  - It uses a row-value `IN` in 450-pair chunks.\n  - The match is exact.\n  - It returns one row per pair, the lowest `video_id`.\n  - There is no blob check.\n- **R3:**\n  - One `with server.db_lock:` covers both lookups.\n  - Rows are emitted in first-match order and deduplicated on the row's `like_key`.\n  - The threshold applies to both forms.\n  - The response shape is unchanged.\n  - Id-only requests are unchanged, including the precedence quirk (Open item A).\n- **R4 and R5:** one `fetch_metadata_for_entries` call each. Deduplication is left to the Engine. The 502 texts are kept. Import records from the row fields and skips disliked videos.\n- **R6:** the function is deleted and its import dropped. `resolve_video_seed` is kept.\n- **R7:** the constant is 50. All three readers slice before validating.\n- **Acceptance criteria:** each is covered by a test in section 5. The lock count is read through `CountingLock`, and the Engine call count through the stand-in Engine.\n\n</draft>",
    "step_6_develop_phase_breakdown": "<phases>\n<phase n=\"1\" kind=\"code\">\n<checkpoint>Seam: the data-layer functions `fetch_metadata_by_ids` and `fetch_metadata_by_uuids` in `engine/server/data/metadata.py`, called in-process against a temp SQLite DB (`row_factory = sqlite3.Row`). The DB has `videos` (26 selected columns plus `error_count`, PK `(video_id, instance_domain)`), `video_embeddings` (PK `(video_id, instance_domain)`) and `channels`. Harness: the `sys.path` insertion of `engine/server` and `engine/server/api` from `tests/active/test_internal_events.py:25-30`. `data.metadata` imports no numpy, so no child process is needed. The file lives in `tests/tmp` and needs `tests/active` on `sys.path` before any `from conftest import ...`. Fixtures come from the draft's table: a1, b1, s2 inserted before s1, e1, n1 with no embedding, and a1 on other.example. Asserts, clause 1: `fetch_metadata_by_uuids(conn, [{video_uuid: \"u-b\", instance_domain: \"h.example\"}])[\"u-b::h.example\"] == fetch_metadata_by_ids(conn, [{video_id: \"b1\", instance_domain: \"h.example\"}])[\"b1::h.example\"]`, and the dict holds exactly the 29 keys. `u-a@h.example` gives the h.example a1, not the other.example one. `U-A` and `u-a@H.EXAMPLE` give nothing. `u-n` gives nothing. An empty list gives `{}` with zero `execute` calls, counted through a wrapped conn. Asserts, clause 2: `u-s` gives `s1`. After `s1.error_count = 5` with threshold 3 it gives `s2`. `u-e` is absent at threshold 3 and present at threshold None. Regression pins with no clause of their own: `fetch_metadata_by_ids` output for a1, n1 skipped, and a 460-video set crossing the 450 chunk boundary on both functions with threshold 3. Every non-errored video comes back. On the uuid path, an errored video in chunk 2 is absent. On the id path there is no assertion on that errored video, because Open item A option 1 keeps today's AND/OR precedence.</checkpoint>\n<name>Engine uuid-keyed metadata lookup</name>\n<intent>`engine/server/data/metadata.py` fetches metadata rows by exact `(video_uuid, instance_domain)` pair through `fetch_metadata_by_uuids`. It uses the same SELECT and row builder (`_select_metadata`) as `fetch_metadata_by_ids` and yields one row per pair: the lowest eligible `video_id`.</intent>\n<clause_1>`fetch_metadata_by_uuids` returns, for an exact `(video_uuid, instance_domain)` match, the same row dict that `fetch_metadata_by_ids` returns for that video.</clause_1>\n<clause_2>Where several videos share one `(video_uuid, instance_domain)`, the row kept is the one with the lowest `video_id` among those under the error threshold.</clause_2>\n<files>engine/server/data/metadata.py (EDITED), tests/tmp/test_metadata_uuid_entries.py (NEW)</files>\n</phase>\n<phase n=\"2\" kind=\"code\">\n<checkpoint>Seam: `handlers.internal_client_reads.handle_internal_videos_metadata(handler, server)`, entered in an `ENGINE_PY -c` child with `cwd=API_DIR`. The module imports numpy, so it cannot run in the pytest interpreter. Harness: the child pattern of `tests/active/test_internal_events.py:173` and `tests/active/test_similar.py:288-289`. The child patches `read_json_body` and `respond_json` on the handler module. It passes `SimpleNamespace(db=conn, db_lock=CountingLock(), video_error_threshold=3)`, where `CountingLock` wraps `threading.Lock` and counts `__enter__`, and prints `[{status, payload, enters}]` per body. It uses the same temp DB as phase 1. Asserts, clause 1: the mixed body `[uuid u-b, id a1, id b1, uuid u-a, uuid u-x]` gives `enters == 1`. Id-only `[a1, b1, a1]` gives `enters == 1`. Asserts, clause 2: the mixed body gives rows `[b1, a1]` with `count == 2`, each video once in first-match order and the unknown omitted. Id-only `[a1, b1, a1]` gives `[a1, b1]`. An item carrying both a valid `video_id` and a `video_uuid` of a different video resolves to the id's video. Per-form duplicates collapse. Uuid `u-e` is absent at threshold 3. Guards: `{\"entries\": \"x\"}` and `{}` give 400 `Missing entries` with `enters == 0`. An all-malformed body (non-dict, blank `instance_domain`, neither key) gives 200 `{\"ok\": True, \"count\": 0, \"rows\": []}` with `enters == 0`. On `/internal/dislikes/centroids`, with `fetch_embeddings_by_ids` spied: a uuid-only body passes `[]` and returns `centroids == []`, and a mixed body passes only the id entries.</checkpoint>\n<name>Engine metadata endpoint accepts both entry forms</name>\n<intent>`handle_internal_videos_metadata` in `engine/server/api/handlers/internal_client_reads.py` parses id-form and uuid-form entries with its own parser. It answers all of them in a single `db_lock` hold and emits each matched video once, at its first matching entry.</intent>\n<clause_1>A request body mixing id-form and uuid-form entries acquires `db_lock` exactly once.</clause_1>\n<clause_2>Each matched video appears once in `rows`, in the order of its first matching entry.</clause_2>\n<files>engine/server/api/handlers/internal_client_reads.py (EDITED), tests/tmp/test_metadata_uuid_entries.py (EDITED)</files>\n</phase>\n<phase n=\"3\" kind=\"code\">\n<checkpoint>Seam: the Client HTTP boundary. Requests go to `POST /api/user-profile/likes` and `POST /api/profile/likes/import` on a locally built `ClientBackendServer`, whose `engine_ingest_base` points at a capturing stand-in Engine. The stand-in is a stdlib `ThreadingHTTPServer` written like `EngineStub` at `tests/active/test_server.py:307`. It records `(path, json body)` for every POST. On `/internal/videos/metadata` it answers from a canned `{uuid::host: row}` table in entry order, omitting unknown entries and duplicates. Local `_serving` and `_client_backend` copies of `test_server.py:251-271` build the Client, with `RateLimiter(1000, 60)`. The file needs `tests/active` on `sys.path` before `from conftest import ...`. Asserts, clause 1: a likes-page body of 3 likes plus a duplicate plus an unknown records exactly one Engine request, to `/internal/videos/metadata`, with `entries` equal to the submitted `{video_uuid, instance_domain}` list. The response `likes` holds the known rows in submitted order. An import of 3 likes records exactly one Engine request, to the same path. An empty or all-malformed likes-page body gives 200 `likes == []` with zero Engine requests. Asserts, clause 2: mint via `POST /api/profile` and resolve `profile_id` with `resolve_profile` on a second connection. Write one dislike with `write_dislike` and commit. Import the disliked video, a clean one and an unknown one. The result is `{\"imported\": 1}` and `load_liked_keys(conn, profile_id) == {(clean_id, host)}`. The existing `tests/active/test_profiles.py` import test also has to pass against the live Engine, in its own `validate_tests.py` invocation. That shows phases 1-2 and 3 work together.</checkpoint>\n<name>Client resolves likes in one Engine call</name>\n<intent>`_handle_user_profile_likes_from_client` and `_handle_likes_import` in `client/backend/server.py` each resolve a request's browser likes with a single `fetch_metadata_for_entries` call, and import records a like from each returned row. `resolve_videos_by_uuid_host` no longer exists.</intent>\n<clause_1>A likes-page or likes-import request causes exactly one Engine HTTP call, to `/internal/videos/metadata`.</clause_1>\n<clause_2>Likes import records a like for each returned row whose video the profile has not disliked.</clause_2>\n<files>client/backend/server.py (EDITED), client/backend/lib/engine_api_client.py (EDITED), tests/tmp/test_client_like_batching.py (NEW)</files>\n</phase>\n<phase n=\"4\" kind=\"code\">\n<checkpoint>Seam: the same Client HTTP boundary and capturing stand-in Engine as phase 3, in the same test file. Asserts, clause 1, on three request paths: a 60-entry likes-page body gives 200, and the single recorded `/internal/videos/metadata` request carries exactly the first 50 entries. A 60-entry import body gives 200, and its single request carries exactly the first 50. A keyless `POST /recommendations` with 60 `{uuid, host}` likes records a forwarded body whose `likes` is the first 50 sanitised entries. The three paths are listed by hand, not derived. They are the three `MAX_CLIENT_LIKES` readers that the grep in the plan found.</checkpoint>\n<name>Cap like entries at 50</name>\n<intent>`MAX_CLIENT_LIKES` in `client/backend/server.py` is 50, so at most the first 50 like entries of one request body reach the Engine.</intent>\n<clause_1>A body carrying 60 like entries reaches the Engine as its first 50 entries.</clause_1>\n<files>client/backend/server.py (EDITED), tests/tmp/test_client_like_batching.py (EDITED)</files>\n</phase>\n</phases>\n\n<needs_coordination>\nnone\n</needs_coordination>\n\n<rationale>\nThe build falls into four phases. Each has its own test boundary and depends only on the phases before it. The operator approved the breakdown as presented.\n\nPhase 1 is the data layer. `fetch_metadata_by_uuids` over the shared `_select_metadata` can be tested in-process with no Engine interpreter, because `data.metadata` imports no numpy. That makes it the cheapest place to prove the two hardest guarantees: the same row dict whichever form is used, and the lowest eligible `video_id`. It also pins the refactored id path that `similarity_candidates._build_rows` depends on.\n\nPhase 2 is the handler. It needs the `ENGINE_PY` child and the counting-lock stand-in server, and it builds on phase 1's functions. Parser rules (id wins, per-form dedup, 400 and empty-200 paths) and the centroids-unchanged guard are cases inside clause 2's test or guards on the checkpoint, not extra clauses. That keeps the phase at two clauses.\n\nPhases 3 and 4 are on the Client side. Both run against a capturing stand-in Engine, because a live Engine cannot count HTTP calls and answers 400 above 5 likes on the proxy. The cap is split out from the one-call rewrite. The rewrite already carries two facts: the single call, and import recording non-disliked rows. The cap is a separate observable across three readers, so folding it in would have needed a third clause.\n\nThe R6 deletion of `resolve_videos_by_uuid_host` sits in phase 3's files. Its proof is that the module still imports, and the single-call assertion shows no resolve call remains.\n\nOpen item A (AND/OR precedence in the id-path threshold) goes with option 1, as the draft proposed and the operator accepted. Id-caller semantics stay unchanged, and the phase 1 checkpoint makes no assertion on errored id rows. The precedence bug goes to the roadmap for Step 9.\n\nBoth new test files live in `tests/tmp`, where pytest does not put `tests/active` on the path. They must insert `tests/active` on `sys.path` before `from conftest import ...`. They build their own servers, so they need no conftest fixtures.\n\nThe build closes when all five clauses pass and the full suite is green. Engine-backed files (`test_profiles.py`, `test_server.py`, `test_similar.py`, `test_blocks.py`) each run in their own `validate_tests.py` invocation because of the Engine's shared rate limit.\n\nThe step template's `{principles}`, `{shape_ladder-ladder}` and `{tdd_seams}` placeholders arrived unfilled. Each seam above was therefore anchored to an existing harness in the tree: `test_internal_events.py`, `test_similar.py`, and `test_server.py`'s EngineStub.\n</rationale>",
    "author:tests/tmp/test_14_batch_like_resolution_phase1.py": "<exemptions>\nnone\n</exemptions>\n\n<items>\n<item id=\"D15\">\n<disposition>fixed</disposition>\n<what>I narrowed the docstring and added a control assertion. The old sentence said the siblings \"come out of the SELECT as s2, s1, s3 (observed)\". That describes the production query, which has not been written yet, so no test here can assert its order. The sentence now reads: \"The fixture stores the three `u-s` siblings as s2, s1, s3, and a scan of `videos` yields them in that order, so the lowest id is neither the first row nor the last. The lookup keeps s1.\" That sentence is now carried by a new first line in the shared-pair test, :130: `[row[\"video_id\"] for row in conn.execute(\"SELECT video_id FROM videos WHERE video_uuid = 'u-s'\")] == [\"s2\", \"s1\", \"s3\"]`. It excludes a fixture that has drifted, for example one reordered or given an index, where s1 is scanned first. In that case a first-row-wins pick would pass :131, :133 and :137. The assertion arms C2a's first-row-wins exclusion instead of leaving it on an unchecked premise. I ran the file and saw this control pass: the shared-pair test now fails at :131 on the missing function, not at :130. I also changed the fixture comment at :90 so it no longer claims \"(observed)\", and it now points at this assertion.</what>\n</item>\n</items>\n\n<findings_addressed>\nClaim audit REC 1 (D15 order stated but never asserted): taken. I narrowed the docstring to the fixture's scan order and asserted that order at :130, as a control before the C2 assertions. The run shows it passing. Both auditors report no CRITICAL findings. I left REC 2 (threshold 0 or negative) and REC 3 (malformed entries) alone. Neither is a must_prove clause of this phase, and pinning either would fix a contract the operator has not approved.\n</findings_addressed>\n\n<rows>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_14_batch_like_resolution_phase1.py:105-108: the result for `u-b@h.example` has the single key `u-b::h.example`. Its row has exactly the 29 ROW_KEYS, equals `fetch_metadata_by_ids(b1@h.example)[\"b1::h.example\"]`, and equals the fixture-stored `_row(*B1)`. Lines :112-116 add exact-match checks: the h.example a1 and not the other.example a1; both hosts, each under its own key; `U-A` gives `{}`; `H.EXAMPLE` gives `{}`; the unembedded `u-n` gives `{}`. Lines :125-126 check that an empty list gives `{}` and runs zero statements, with a control at :122-123.</assertion>\n<expected>`{\"u-b::h.example\": <b1's 29-key row with Chan B/ava-b, embedding_dim 3, model_name m>}`, identical to the id path's row. The uuid and host mismatch cases give `{}`.</expected>\n<wrong_implementation>A uuid path that builds its own trimmed row, or drops the channels join, fails :106-108 (for example `channel_display_name` None, or keys missing). Matching on the uuid alone returns or overwrites with the other.example a1, which fails :112-113. COLLATE NOCASE or lower() gives a row at :114 or :115 where `{}` is expected. `error_count < ?` without `IS NULL` gives `{}` at :105.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_14_batch_like_resolution_phase1.py:131, :133, :135, :137, :138 check `u-s@h.example`, the shared pair. It keeps s1; with s1.error_count 3 it keeps s2; with 2, s1; with 5, s2; with 5 and no threshold, s1. The control at :130 shows that the scan order is s2, s1, s3. Lines :142-143 check that `u-e` is dropped at threshold 3 and returned at None.</assertion>\n<expected>Respectively `{\"u-s::h.example\": _row(*S1)}`, `_row(*S2)`, `_row(*S1)`, `_row(*S2)` and `_row(*S1)`. Then `{}` for u-e at threshold 3, and `{\"u-e::h.example\": _row(*E1)}` at None.</expected>\n<wrong_implementation>Last-row-wins gives s3 at :131. First-row-wins gives s2 at :131 while the order :130 pins holds. Pick-then-filter gives `{}` at :137. A `<=` threshold keeps s1 at :133. An off-by-one that drops error_count 2 gives s2 at :135. Applying the filter when the threshold is None gives s2 at :138, and `{}` for u-e at :143. Omitting the error clause keeps s1 at :133 and :137, and returns u-e at :142.</wrong_implementation>\n</row>\n</rows>\n\n<answers>\n1. No. Every negative has a positive control. :114-116 sit beside :112-113, which return rows through the same call. :126 is armed by :122-123. :142 is paired with :143. If the code under test were deleted, every uuid test would fail.\n2. No. The expected rows come from `_row`, built from the fixture's stored values, not from a production transform. :108 turns red if the joins are dropped in the uuid SELECT, and :107 turns red if its row construction differs from the id path's. The new :130 reads the fixture table, not production output. It is a control on the fixture's premise and carries no clause. It does not mirror the production query's logic: it is a plain scan with no join, no threshold and no pick.\n3. No. The threshold is read at the values 2, 3 and 5 and at None. Matching is read across uuid case, host case, a second host and an unembedded video. Each expected row is a separately stored video with distinct values.\n4. No. There are no doubles. `data.metadata` is imported for real and runs on a real SQLite file.\n5. Yes, it collects. The run collected 7 tests: 6 failed and 1 passed, the same as before. The new line uses only `conn.execute`, and `row[\"video_id\"]` works on the fixture's `sqlite3.Row` factory.\n6. Yes. The scan order s2, s1, s3 is observed. :130 passed in this run, because the shared-pair test's failure moved to :131. The earlier probe had observed the same order under the draft query. The uuid return contract is still a prediction, as stated in the previous reply.\n7. Yes. All 6 failures are `AttributeError: module 'data.metadata' has no attribute 'fetch_metadata_by_uuids'`. They are raised at :77 and reached from :103, :112, :122, :131, :142 and :160. The id pin passes.\nNo question was answered yes as a failing, so nothing needed rewriting beyond the D15 fix. The probe files `tests/tmp/probe_phase1_metadata.py` and `tests/tmp/probe_phase1_against_impls.py` are still on disk because I have no delete tool, and they should be removed.\n</answers>",
    "self_check:tests/tmp/test_14_batch_like_resolution_phase1.py": "<rows>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_14_batch_like_resolution_phase1.py:105-108 \u2014 `fetch_metadata_by_uuids` for `u-b@h.example` at threshold 3 has exactly the key `u-b::h.example`. Its row has exactly the 29 `ROW_KEYS`, equals `fetch_metadata_by_ids(...)[\"b1::h.example\"]`, and equals `_row(*B1)`: the stored values plus `channel_display_name` \"Chan B\", `channel_avatar_url` \"ava-b\", `embedding_dim` 3 and `model_name` \"m\".</assertion>\n<expected>`{\"u-b::h.example\": _row(*B1)}`. The probe showed `fetch_metadata_by_ids` returns exactly `_row(*B1)` for b1 at threshold 3 even though b1's `error_count` is NULL, so the id side of line 107 is observed.</expected>\n<wrong_implementation>A uuid query that leaves out the `channels` LEFT JOIN or builds a trimmed row gives a different key set or `channel_display_name` None (red at 106/108). One that keys the row by `like_key` gives `b1::h.example` (red at 105). One that drops a NULL `error_count` under a threshold (`error_count < ?` without `IS NULL`) gives `{}`.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_14_batch_like_resolution_phase1.py:112-116 \u2014 `u-a@h.example` gives only the h.example a1 row. Asking for both hosts gives both a1 rows under their own keys. `U-A@h.example`, `u-a@H.EXAMPLE` and the unembedded `u-n@h.example` each give `{}`.</assertion>\n<expected>112: `{\"u-a::h.example\": _row(*A1)}`. 113: that plus `\"u-a::other.example\": _row(*A1_OTHER)` (the probe observed the id lookup returning exactly `_row(*A1_OTHER)` for the other.example a1). 114, 115, 116: `{}`.</expected>\n<wrong_implementation>Matching on uuid alone returns or overwrites with the other.example a1 (red at 112/113). `COLLATE NOCASE` or `lower()` matching returns a1 for `U-A` or `H.EXAMPLE` (red at 114/115). A LEFT JOIN on `video_embeddings` returns n1 with `embedding_dim` None (red at 116). Line 112 is the positive control: a function that always returns `{}` is red there before it reaches the absences.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_14_batch_like_resolution_phase1.py:125-126 \u2014 an empty entry list returns `{}`, and the connection's trace callback records no statement. Lines 122-123 are the control: the same trace records at least one statement for a lookup that finds a row.</assertion>\n<expected>`{}`, and `statements == []`. The probe observed the trace recording 1 statement for an id lookup and 0 for an empty one.</expected>\n<wrong_implementation>A version with no `if not entries: return {}` guard that still runs a query (for example a WHERE with an empty IN, or a setup statement before the loop) records a statement, so it goes red at 126.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_14_batch_like_resolution_phase1.py:130-137 \u2014 for the shared pair `u-s@h.example` (the probe showed the SELECT yields s2, s1, s3), the result as s1's `error_count` changes at threshold 3: 0 gives s1, 3 gives s2, 2 gives s1, 5 gives s2, and 5 with threshold None gives s1.</assertion>\n<expected>130 `_row(*S1)`, 132 `_row(*S2)`, 134 `_row(*S1)`, 136 `_row(*S2)`, 137 `_row(*S1)`, each under `u-s::h.example`. The probe showed that with s1 at 3 the eligible rows are s2 and s3, and that the id lookup returns exactly `_row(*S1/S2/S3)` for each sibling.</expected>\n<wrong_implementation>Keeping the first row in SELECT order gives s2 at 130. Keeping the last row (plain dict overwrite) gives s3. Choosing the lowest id before filtering on errors gives `{}` at 132/136. Using `<=` for the threshold keeps s1 at 132. Applying the threshold even when it is None gives s2 at 137.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_14_batch_like_resolution_phase1.py:141-142 \u2014 `u-e` (error_count 5) gives `{}` at threshold 3 and `{\"u-e::h.example\": _row(*E1)}` with threshold None.</assertion>\n<expected>141 `{}`. 142 `{\"u-e::h.example\": _row(*E1)}`. The probe observed the id lookup giving `{}` for e1 at threshold 3 and exactly `_row(*E1)` with None.</expected>\n<wrong_implementation>A uuid query without the error clause returns e1 at 141. One that always applies the clause gives `{}` at 142. Line 142 is also the positive control for the absence at 141.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_14_batch_like_resolution_phase1.py:160-161 \u2014 across 460 bulk videos at threshold 3, which cross the 450-pair chunk boundary, the uuid lookup maps every healthy `uc###::bulk.example` to its `c###`, leaves out `uc455` (error_count 5, in chunk 2 and not its last pair), and returns uc452's full row.</assertion>\n<expected>A dict with exactly the 459 healthy keys, each mapped to its own `c###`, plus `_row(*_bulk(452))` for `uc452`. The id path returned exactly `_row(*_bulk(452))` for c452 in this run: line 158 passed before 159 raised.</expected>\n<wrong_implementation>Copying the id path's `OR` chain for uuids binds the threshold only to each chunk's last pair, so `uc455` comes back (red at 160). Querying only the first chunk loses uc450\u2013uc459. Deduplicating in a way that lets a pair span two chunks produces mismatched rows.</wrong_implementation>\n</row>\n</rows>\n\n<answers>\n1. No. Every clause and bullet in the docstring has an assertion. C1 is covered by the id-equality row for b1 with its channels and embeddings join and the NULL error_count (105-108), exact matching on uuid and host, case-sensitivity and the unembedded n1 (112-116), and the empty list with no statement (125-126). C2 is covered by the s1/s2 threshold walk (130-137), u-e dropped only while a threshold is set (141-142), and the chunk-boundary errored video on the uuid path (160). The id-path pins (147, 157-158) carry no clause, as the plan says, and c455 is deliberately left unasserted on the id path (Open item A, option 1).\n2. No. Every absence has a positive control that runs the same path first. 114-116 follow 112, which returns a row for the same fixture. 126 follows the trace control at 122-123, and the probe saw the trace record 1 statement. 141 is paired with 142. At 160, uc455's absence sits inside an exact-dict equality that also demands the other 459 rows.\n3. No. The expected rows come from `_row`/`_video`, which build the values the fixture stored and do not run production's SELECT or its row builder. Line 107 compares the two production functions, but 108 pins the result independently. Deleting `c.display_name AS channel_display_name` or the row builder's `\"channel_display_name\"` entry makes 106/108 red. Deleting the error clause makes 132, 141 and 160 red.\n4. No. C1 is read over b1 (with a channel row and NULL error_count), a1 on two hosts, and three non-matching inputs. C2 is read at s1 error_count 0, 3, 2 and 5 with threshold 3, at 5 with None, on u-e at 3 and at None, and across 460 videos. The siblings come out of the SELECT as s2, s1, s3, so first-row and last-row picks both disagree with lowest-id.\n5. No. There is no double. It runs a real in-process SQLite file DB and the real `data.metadata`. The empty-list statement count uses sqlite3's own `set_trace_callback`, not a wrapper around a module this project owns.\n6. No. The run printed \"collected 7 items\", which matches the 7 test functions. The only error is the expected `AttributeError: module 'data.metadata' has no attribute 'fetch_metadata_by_uuids'`, raised from `_by_uuids` at line 77. `fetch_metadata_by_ids`, `_chunk`/`like_key` through the module import, `sqlite3.Row` and `set_trace_callback` all resolved. The collect-only summary shows \"no tests\" only in its lane table; the real run's \"collected 7 items\" is the count.\n7. No. I re-observed the premises in a probe (`tests/tmp/probe_14_phase1.py`, run with -s), which printed: `u-s order: ['s2', 's1', 's3']`; `b1 == _row: True ['b1::h.example']` at threshold 3; `e1 none == _row: True`; `e1 at 3: {}`; `a1 other == _row: True`; `s rows == _row: True True True`; `trace count after id lookup: 1`; `trace count after empty id lookup: 0`; `u-s eligible with s1 at 3: ['s2', 's3']`; and a row-value `IN ((?, ?), (?, ?))` returning both a1 rows. The run also showed test 6 passing (a1's `_row` equals the id output) and line 158 passing (`_row(*_bulk(452))`). The uuid function's own output cannot be observed until the phase is built; each of its expected values is the id lookup's observed row for the same video. No rewrite was needed. I emptied the probe file because I have no delete tool, so `tests/tmp/probe_14_phase1.py` remains as a 0-byte file and should be removed.\n8. Yes, it is red. `ValidateTests tests/tmp/test_14_batch_like_resolution_phase1.py` gave exit status 1: \"6 failed, 1 passed\" (`FFFFF.F`). The one pass is `test_the_id_lookup_returns_the_joined_row_and_skips_an_unembedded_video`, a regression pin on existing behaviour that carries no clause. Every clause-bearing test fails.\n9. Red for the right reason. All six failures are `E AttributeError: module 'data.metadata' has no attribute 'fetch_metadata_by_uuids'. Did you mean: 'fetch_metadata_by_ids'?` at `tests/tmp/test_14_batch_like_resolution_phase1.py:77` (`_by_uuids`), reached from lines 103, 112, 122, 130, 141 and 159. The function this phase adds does not exist yet. No control assertion failed. In the chunk test, the id-path assertions at 157 and 158 passed before line 159 raised, so the harness, the fixture and the 460-row bulk insert all work. The control at 122 raised the same AttributeError inside its call to the missing function; it did not fail its own check. Its premise (the trace records a lookup) was observed in the probe with 1 statement.\n10. Each `expected` column is either the id lookup's row observed for the same video (b1, a1, a1@other, s1, s2, s3, e1 at None, c452), or a premise observed in the probe (SELECT order s2, s1, s3; eligible s2 and s3 with s1 at 3; e1 absent at 3; trace counts 1 and 0). Nothing the run printed contradicts a row. The uuid function's own output is not yet observable because it raises AttributeError.\n</answers>\n\n<exemptions>\nnone\n</exemptions>",
    "step_7_implement:1": "<changes>\n### `engine/server/data/metadata.py`\n\n- **New `_select_metadata(conn, conditions, params, error_threshold)`:** holds the joined SELECT (`video_embeddings` JOIN `videos` LEFT JOIN `channels`) and the 29-key row builder that used to live inline in `fetch_metadata_by_ids`. It appends the `error_count IS NULL OR error_count < ?` clause when `error_threshold > 0`, the same rule as before. It works on a copy of `params` and returns a list of row dicts.\n- **`fetch_metadata_by_ids`:** still splits the input into chunks of 450 and builds the same OR-of-pairs condition, but now gets its rows from `_select_metadata` and keys them with `like_key`, as before. Its conditions are passed without parentheses on purpose, so the threshold still applies only to the last pair of each chunk (Open item A, option 1). This behaviour is unchanged, and a one-line comment explains why.\n- **New `fetch_metadata_by_uuids(conn, entries, error_threshold=None)`:**\n  - Returns `{}` for an empty list without running any SQL.\n  - Otherwise splits the input into chunks of 450, builds `(v.video_uuid = ? AND v.instance_domain = ?)` joined with OR, and passes it to `_select_metadata` wrapped in parentheses, so the threshold applies to every pair.\n  - Keys rows as `\"{video_uuid}::{instance_domain}\"`. Where several videos share a pair, it keeps the row with the lowest `video_id` among those the threshold lets through (C2).\n  - Matching is exact and case-sensitive, from SQLite's default BINARY `=`.\n  - An unembedded video is dropped by the inner join, as in the id path.\n- **Not changed:** `fetch_metadata` (the rowid lookup).\n\n### `tests/tmp/test_metadata_uuid_entries.py`\n\nNot created. The phase lists it as a new file, but the checkpoint already covers everything this phase does (see `inner_tests`).\n</changes>\n\n<inner_tests>\nnone. The checkpoint covers C1 (exact pair match, 29-key row equal to the id lookup's, case sensitivity, unembedded video, empty input running no SQL) and C2 (lowest `video_id` among siblings stored out of order, threshold on and off, the chunk boundary). So the listed `tests/tmp/test_metadata_uuid_entries.py` was not needed and was not created.\n</inner_tests>\n\n<unanticipated>\nnone\n</unanticipated>\n\n<awaiting_operator>\nnone\n</awaiting_operator>",
    "author:tests/tmp/test_14_batch_like_resolution_phase2.py": "<exemptions>\nnone\n</exemptions>\n\n<findings_addressed>\nNo CRITICAL from either auditor. Claim audit RECOMMENDATION 1 (N4, entry order is also table order at :167): taken. The id-only body is now [b1, a1, b1] \u2192 [b1, a1], so table order no longer passes. Claim audit RECOMMENDATION 2 (a body over 450 entries; an explicit empty list): not taken. The auditor says no rule requires it at this surface, and the ledger does not list it. Shape audit RECOMMENDATION 1 (test 2 and the malformed-body test are regression controls, not gates): no change. I confirmed by running it that test 2 is still a pin the unchanged handler meets. The comment at :167 now says what it excludes, and C1/C2 are still gated at :157-162.\n</findings_addressed>\n\n<items>\n<item id=\"N4\">\n<disposition>fixed</disposition>\n<what>Test 2's body is now `[id b1, id a1, id b1]` and :167 asserts `report[\"responses\"] == _rows(B1, A1)`. Entry order b1, a1 is the reverse of the fixture's insertion, rowid and alphabetical order, which are all a1, b1. So an implementation that returns rows in table or SQL order reads [a1, b1] and fails. One that repeats b1 reads [b1, a1, b1] and also fails. The module docstring's matching sentence (D7) now says \"`[b1, a1, b1]` gives `[b1, a1]`\", so it describes what the test asserts. D7 is still carried by :167 and :168. I checked this with a probe that ran the real `_handle` over this body against the unchanged handler. It printed rows ['b1', 'a1'], enters 1, statements_locked [True], count 2. Then I ran the edited test through a re-exporting probe and it passed. So this test is still a regression pin that the current handler meets, as the shape auditor described. It is not the red gate. The gate is still :157-162.</what>\n</item>\n</items>\n\n<rows>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_14_batch_like_resolution_phase2.py:157 \u2014 (enters, row video_ids) for the mixed body [uuid u-b, id a1, id b1, uuid u-a, uuid u-x]; :160 \u2014 set(statements_locked) == {True}; :162 \u2014 (enters, set(statements_locked)) for the id-first mixed body</assertion>\n<expected>(1, [\"b1\", \"a1\"]) at :157; {True} at :160; (1, {True}) at :162</expected>\n<wrong_implementation>Separate lookups per form, each under its own `with db_lock` (or `acquire()`, which the counter also sees), read enters 2, so :157 gets (2, [\"b1\", \"a1\"]) and :162 gets (2, {True}). One acquisition that wraps only the id lookup runs the uuid SELECT with the lock free, so :160 gets {False, True}. The unchanged id-only handler reads (1, [\"a1\", \"b1\"]) at :157.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_14_batch_like_resolution_phase2.py:158 \u2014 mixed body [uuid u-b, id a1, id b1, uuid u-a, uuid u-x] responses; :159 \u2014 id-first mixed body [id a1, uuid u-x, uuid u-b, id b1] responses; :185 \u2014 [uuid u-a, uuid u-a, id b1, id b1, uuid u-b, id a1] responses</assertion>\n<expected>_rows(B1, A1) at :158 (count 2, full rows, u-x omitted); _rows(A1, B1) at :159; _rows(A1, B1) at :185</expected>\n<wrong_implementation>Emitting all id rows first, or in table order, gives [a1, b1] at :158. Emitting all uuid rows first gives [b1, a1] at :159. Appending each form's matches without deduplicating gives [b1, a1, b1, a1] or similar, count 4, at :158 and repeated rows at :185. A placeholder row for u-x makes the count 3 at :158.</wrong_implementation>\n</row>\n</rows>\n\n<answers>\n1. No. The only absence checks are u-x omitted (:158), e1 omitted under the threshold (:192) and enters 0 (:198-200). Each has a positive control on the same run or fixture: b1 and a1 are present at :158, e1 comes back with no threshold at :190-191, and enters 1 for the valid bodies at :157 and :168. Take the handler away and every responses assertion fails.\n2. No. Expected rows are built by `_row` from the fixture's input values, not by running production's SELECT or join. Deleting the reordering loop in handle_internal_videos_metadata, which walks the entries and emits each key once, turns :158 and :167 red. :167 now uses a non-table order, so table order no longer passes it.\n3. No. Order is checked on three bodies whose first-match orders differ: [b1, a1] at :158, [a1, b1] at :159, and id-only [b1, a1] at :167. The lock count is checked on four bodies, and the threshold is checked both set and unset.\n4. No. The only doubles are the request stand-in (stdlib BaseHTTPRequestHandler) and the CountingLock (threading.Lock). fetch_embeddings_by_ids, which this project owns, is spied with wraps=, not replaced.\n5. Yes, it collects. I ran the edited test 2 through the re-exporting probe tests/tmp/probe_14_n4.py and it passed. Seven tests, same imports; only test 2's body, its expected value and one docstring sentence changed.\n6. Yes, observed. Before I wrote the expectation, a probe ran the real `_handle` on [b1, a1, b1] against the unchanged handler and printed rows ['b1', 'a1'], enters 1, statements_locked [True], count 2.\n7. Yes. The edit only touches test 2, which is a pin that passes now (observed). The red tests are unchanged: :157, :180, :185 and :191 still fail because the uuid form has not been built. Housekeeping: I have no delete tool, so tests/tmp/probe_14_n4.py has been emptied but still needs removing, along with the earlier probes (probe_14_phase2.py, probe_14_phase1.py, probe_phase1_metadata.py, probe_phase1_against_impls.py).\n</answers>",
    "self_check:tests/tmp/test_14_batch_like_resolution_phase2.py": "<rows>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_14_batch_like_resolution_phase2.py:157 \u2014 for the mixed body `[uuid u-b, id a1, id b1, uuid u-a, uuid u-x]`, the pair (lock acquisitions, row video_ids) == (1, [\"b1\", \"a1\"])</assertion>\n<expected>(1, [\"b1\", \"a1\"]): one `db_lock` acquisition, and that one hold served both the uuid entry (b1) and the id entry (a1).</expected>\n<wrong_implementation>A separate lookup, and a separate lock hold, for each form reads (2, [\"b1\", \"a1\"]). The current id-only handler never resolves the uuid entry. The run showed it reading (1, ['a1', 'b1']), so that version of \"exactly once\" fails too, because the uuid entry was never served inside the hold.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_14_batch_like_resolution_phase2.py:162 \u2014 for the second mixed body `[id a1, uuid u-x, uuid u-b, id b1]`, (acquisitions, set of per-statement \"lock held\" flags) == (1, {True})</assertion>\n<expected>(1, {True}): one acquisition, and every SQL statement ran while it was held. It is reached only after line 159 shows u-b was resolved in that same call.</expected>\n<wrong_implementation>A lock per form reads (2, {True}). A uuid lookup run after the lock is released reads (1, {True, False}).</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_14_batch_like_resolution_phase2.py:158 \u2014 the mixed body `[uuid u-b, id a1, id b1, uuid u-a, uuid u-x]` responds exactly `[[200, {ok, count 2, rows [b1, a1]}]]`, with complete rows</assertion>\n<expected>[[200, {\"ok\": True, \"count\": 2, \"rows\": [b1 row, a1 row]}]]: b1 at its uuid entry, a1 at its id entry, u-x omitted.</expected>\n<wrong_implementation>The current id-only handler gives rows [a1, b1] (observed in the first run). No dedupe across forms gives [b1, a1, b1, a1] with count 4. Id rows emitted before uuid rows gives [a1, b1].</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_14_batch_like_resolution_phase2.py:159 \u2014 `[id a1, uuid u-x, uuid u-b, id b1]` responds with rows exactly [a1, b1]</assertion>\n<expected>[[200, {\"ok\": True, \"count\": 2, \"rows\": [a1 row, b1 row]}]]</expected>\n<wrong_implementation>Emitting every uuid-matched row before the id rows gives [b1, a1]. No dedupe across forms gives [a1, b1, b1].</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_14_batch_like_resolution_phase2.py:178 \u2014 an item with video_id a1 and video_uuid u-b gives rows exactly [a1]</assertion>\n<expected>[[200, {\"ok\": True, \"count\": 1, \"rows\": [a1 row]}]]</expected>\n<wrong_implementation>An item that feeds both lookups gives [a1, b1] with count 2. An item where the uuid takes precedence gives [b1].</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_14_batch_like_resolution_phase2.py:179 \u2014 `{\"video_id\": \" a1 \", \"video_uuid\": \"   \", \"instance_domain\": \" h.example \"}` gives rows exactly [a1]</assertion>\n<expected>[[200, {\"ok\": True, \"count\": 1, \"rows\": [a1 row]}]]</expected>\n<wrong_implementation>Values used without stripping give no match, rows []. Treating a whitespace uuid as present gives a uuid lookup on \"   \" instead of the id match, also rows [].</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_14_batch_like_resolution_phase2.py:180 \u2014 `{\"video_id\": \"   \", \"video_uuid\": \" u-b \"}` gives rows exactly [b1]</assertion>\n<expected>[[200, {\"ok\": True, \"count\": 1, \"rows\": [b1 row]}]]. The b1 row shape was seen in this run's id-form output (Chan B / ava-b, integers 20..26, embedding_dim 3, model 'm').</expected>\n<wrong_implementation>Dropping an item with a blank id instead of falling back to its uuid gives [[200, {'ok': True, 'count': 0, 'rows': []}]], as observed today.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_14_batch_like_resolution_phase2.py:185 \u2014 `[uuid u-a, uuid u-a, id b1, id b1, uuid u-b, id a1]` gives rows exactly [a1, b1]</assertion>\n<expected>[[200, {\"ok\": True, \"count\": 2, \"rows\": [a1 row, b1 row]}]]</expected>\n<wrong_implementation>The current id-only handler gives [b1, a1] (observed). Dedupe within each form but not across forms gives [a1, b1, b1, a1] with count 4. Id rows first gives [b1, a1].</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_14_batch_like_resolution_phase2.py:191 \u2014 `[uuid u-e, uuid u-a]` with no threshold gives rows exactly [e1, a1]</assertion>\n<expected>[[200, {\"ok\": True, \"count\": 2, \"rows\": [e1 row (channel_display_name/avatar None), a1 row]}]]. The same value passed the control at line 190 through the id form.</expected>\n<wrong_implementation>Ignoring uuid-form entries gives rows [] (observed today). Applying a default threshold when none is set drops e1 and gives [a1].</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_14_batch_like_resolution_phase2.py:192 \u2014 the same body at threshold 3 gives rows exactly [a1]</assertion>\n<expected>[[200, {\"ok\": True, \"count\": 1, \"rows\": [a1 row]}]]</expected>\n<wrong_implementation>Applying the error threshold only to the id lookup and not the uuid lookup gives [e1, a1]. Ignoring uuid entries gives [].</wrong_implementation>\n</row>\n</rows>\n\n<answers>\n1. Whole claim: no gap. Each docstring bullet has assertions: mixed bodies at 157-162, id-only at 167-168, id-over-uuid/stripping/blank-id at 178-180, repeats at 185, the error threshold at 190-192, bodies with no valid entries and the lock at 198-200, centroids at 205-208. I changed the docstring's harness sentence to match the new request stand-in (see 5).\n2. Absence only: no, after one rewrite. At 192, \"e1 omitted at threshold 3\" had a control at the old line 174 that itself needed uuid resolution, so it failed before measuring anything (see 9). The new control at 190 reads e1 by id with no threshold; it passed in the rerun, so the omission at 192 is armed. The `enters == 0` checks at 198-200 are paired with their responses, and the lock counter is shown working by the green id-only test (enters 1). The uuid-only `[[]]` at 205 is paired with the mixed case `[[a1]]` at 207.\n3. Echoed literal: no. Expected rows are built from fixture inputs by `_row`, which does not repeat production's join or ordering. Deleting the per-entry ordering loop (`for entry in entries: row = metadata.get(...)`, internal_client_reads.py:120-123) or the single `with server.db_lock:` at :112 turns 157-159 and 185 red.\n4. One value: no. Order is checked on two mixed bodies with opposite form order (158 gives [b1, a1], 159 gives [a1, b1]). The threshold is read at 3 and at None. Centroids are read at a uuid-only and a mixed body.\n5. The double: yes, rewritten. The old child patched `read_json_body` and `respond_json`, which are project-owned `http_utils`. The child now passes a `Request` stand-in for the stdlib `BaseHTTPRequestHandler` (headers, rfile, send_response/send_header/end_headers, wfile), so the real body reader and responder run. The only stand-ins left are for the stdlib request object and the lock; the embedding lookup is `wraps=` spied and runs for real.\n6. It collects: yes. The provided `--collect-only` summary printed \"no tests\", which didn't match. The ValidateTests run printed \"collected 7 items\", matching the 7 test functions. All names bind and the harness ran every case (the returncode control at 151 passed in every test). I did not look into why the collect-only summary printed \"no tests\"; I'm treating the real run as the evidence.\n7. Observed, not predicted: yes. The row shapes (column set, integers n*10+i, channel None for e1, embedding_dim 3, model 'm') were seen in run output: b1/a1 by id in the diffs, and e1 by passing the control at 190. The centroid [0.707107, 0.707107, 0.0] passes in the run. The probe tests/tmp/probe_14_phase2.py is still on disk: I have no delete tool, so it needs removing by hand.\n8. Red, not green: yes. ValidateTests exit status 1, \"4 failed, 3 passed\". The 3 green tests (id-only, no-valid-entry bodies, centroids) are behaviour that should stay the same, and they now pass through the real http_utils; every uuid-form claim is red.\n9. Red for the right reason: yes after the rewrite. In the first run, test_an_errored_video_s_uuid_entry_... failed its CONTROL at line 174 (`unset[\"responses\"] == _rows(E1, A1)` got `[[200, {'ok': True, 'count': 0, 'rows': []}]]`), a test defect that I rewrote as described in 2. Rerun failures: line 157 `assert (1, ['a1', 'b1']) == (1, ['b1', 'a1'])`, the uuid entry was not served; line 180 got `[[200, {'ok': True, 'count': 0, 'rows': []}]]`, blank id not falling back to uuid; line 185 got rows [b1, a1] vs [a1, b1]; line 191 got `[[200, {'ok': True, 'count': 0, 'rows': []}]]`, after control 190 passed. Every failure is a phase assertion, and the harness control at 151 passed each time.\n10. Observed expected output: yes. Each row's expected value is the value the run printed on the expected side, with row shapes confirmed by passing id-form reads (control 190, lines 178-179 passing before 180). The wrong-implementation readings marked \"observed\" are what the run printed on the actual side: (1, ['a1', 'b1']) at 157, rows [] at 180 and 191, [b1, a1] at 185. The others (lock per form, no cross-form dedupe) are what those implementations would produce, not runs.\n</answers>\n\n<exemptions>\nnone\n</exemptions>",
    "step_7_implement:2": "<changes>\n### `engine/server/api/handlers/internal_client_reads.py`\n- Line 9 now imports `fetch_metadata_by_uuids` alongside `fetch_metadata_by_ids`.\n- Three new helpers sit next to `_like_key` and `_parse_entries`, written as the plan sets them out:\n  - `_uuid_key` builds the `video_uuid::instance_domain` key. It matches the key `fetch_metadata_by_uuids` builds its result dict with.\n  - `_stripped` returns a stripped string, or None when the value is blank or not a string.\n  - `_parse_metadata_entries` returns None when `entries` is not a list. It skips items that are not a dict or have no valid stripped `instance_domain`. An item with a valid `video_id` counts as the id form even when it also carries a `video_uuid`; otherwise a valid `video_uuid` makes it the uuid form, and an item with neither is skipped. It drops duplicates within each form, keeping the first, and returns one ordered list of `(form, entry)` pairs. The form is part of the duplicate key so id keys and uuid keys cannot collide.\n- `handle_internal_videos_metadata`:\n  - It now uses the new parser. The 400 `Missing entries` answer and the empty 200 answered before any lock are kept.\n  - It splits the parsed entries into id entries and uuid entries. Inside one `with server.db_lock:` it calls `fetch_metadata_by_ids` and/or `fetch_metadata_by_uuids`, skipping a call when its list is empty, and both get the same `video_error_threshold`.\n  - After the lock is released, it walks the entries in order and looks each one up in the dict for its own form. It emits a row only the first time it sees that row's `video_id::instance_domain`, so each video appears once, at its first matching entry.\n  - The response shape is unchanged. The docstring is updated.\n- `_like_key`, `_parse_entries`, `handle_internal_video_resolve` and `handle_internal_dislike_centroids` are not changed, so centroids still accepts only id-form entries.\n\n### `tests/tmp/test_metadata_uuid_entries.py`\nNot changed. The files list marks it EDITED, but the file does not exist in the worktree: the phase 1 checkpoint landed as `tests/tmp/test_14_batch_like_resolution_phase1.py`. The phase 2 checkpoint covers this phase on its own, so I did not create this file.\n</changes>\n\n<inner_tests>\nnone\n</inner_tests>\n\n<unanticipated>\nnone\n</unanticipated>\n\n<awaiting_operator>\nnone\n</awaiting_operator>",
    "author:tests/tmp/test_14_batch_like_resolution_phase3.py": "<exemptions>\nnone\n</exemptions>\n\n<items>\n<item id=\"D11b\">\n<disposition>justified</disposition>\n<what>I narrowed the prose to match what the test checks. The real Engine's metadata route matches a row on the entry's uuid and host, so the row and the submitted like always share `video_uuid`/`instance_domain`. A stand-in that returned a row differing from its entry would no longer answer \"as the Engine does\", which is what the docstring at :7 claims. The docstring bullet at :5 now reads: \"stored with the `video_id` of their Engine rows and with a non-null `video_uuid` and `instance_domain` (which the row and the submitted like share, so which one they are taken from is not told apart)\". The comment on :143 was narrowed the same way: \"each like carries its video_uuid and host, not nulls; row and entry share them, so their source is not told apart\". :143 still carries what the sentence now claims: a null or dropped `video_uuid`/`instance_domain` fails it. The part about where the values come from (D11a, `video_id`) stays carried by :142/:143, because each fixture's `video_id` differs from its uuid. No assertion changed. The line count is unchanged, so every line reference still holds.</what>\n</item>\n</items>\n\n<findings_addressed>\nNo CRITICAL from either auditor. Claim-audit recommendation 1 (D11b whole-claim): taken in its \"narrow the docstring\" form. The docstring at :5 and the comment at :143 now claim only a non-null `video_uuid`/`instance_domain`, not that they come from the row. Recommendations 2\u20134 (empty or max-size import, a failing Engine path or a missing profile key, recording non-POST/GET methods): not taken. They are outside the ledger and do not block.\n</findings_addressed>\n\n<rows>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_14_batch_like_resolution_phase3.py:109, :117, :121, :140. The stand-in's full request record equals exactly one `(/internal/videos/metadata, {\"entries\": [submitted pairs in order]})` for the likes page (:109), the well-formed page after the empty ones (:121) and the import (:140). It is `[]` after the empty and malformed pages (:117).</assertion>\n<expected>:109 `[(METADATA, {\"entries\": [u-c, u-a, u-c, u-x, u-b pairs]})]`. :117 `[]`. :121 `[(METADATA, {\"entries\": [u-a pair]})]`. :140 `[(METADATA, {\"entries\": [u-a, u-b, u-x, u-c pairs]})]`.</expected>\n<wrong_implementation>The current per-like `resolve_videos_by_uuid_host` loop. Its record starts with `('/internal/videos/resolve', {'host': 'h.example', 'uuid': ...})`, observed on this run at :109, :121 and :140. Deduping or filtering entries before the call, or making a second call, also breaks the equality.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_14_batch_like_resolution_phase3.py:141, :142, :143. The import answers `(200, {\"imported\": 2})`. `load_liked_keys` is `{(\"id-a\", HOST), (\"id-c\", HOST)}`. The stored like rows are `{(\"id-a\", \"u-a\", HOST), (\"id-c\", \"u-c\", HOST)}`.</assertion>\n<expected>`(200, {\"imported\": 2})`; `{(\"id-a\", HOST), (\"id-c\", HOST)}`; `{(\"id-a\", \"u-a\", HOST), (\"id-c\", \"u-c\", HOST)}`.</expected>\n<wrong_implementation>Ignoring the dislike, or checking it against the uuid, imports 3 (observed, FAIL at :141). Skipping the first or last returned row imports 1 (observed, FAIL at :141). Recording a like from the unknown submitted `u-x`, or keying the like on the uuid, puts `u-x`/`u-a` into the liked set at :142. Dropping the uuid gives a null at :143 (observed).</wrong_implementation>\n</row>\n</rows>\n\n<answers>\n1. No. The only absence assertion is :117 (`received == []`). The control at :120/:121 arms it: a well-formed like sent next to the same stand-in is recorded.\n2. No. The expected values are literal fixtures (A/B/C, pair lists). The test never does production's uuid\u2192metadata transformation. The stand-in answers the Engine's side, and deleting the Client's metadata batch call turns :109/:121/:140 red, as seen on this run with the current resolve loop.\n3. No. The page is checked with five entries (a repeat and an unknown among them) and again with one. The import is checked with four entries (clean, disliked, unknown, clean). The order is checked against a table order that differs from it.\n4. No. The only double is the Engine, a separate service reached over HTTP, so this is the severed layer. The Client backend, `write_dislike`, `resolve_profile` and `load_liked_keys` are all real.\n5. Yes, it collects: this run collected 3 tests, all imports resolved, and all 3 ran to their assertions.\n6. Yes, the values were observed. The resolve-first request shape and the 502 come from probe 1. The pass/fail pattern for correct and wrong implementations comes from probe 3. This run showed the failures at :109, :121 and :140.\n7. Yes, it is still red for its own reason. On this run all 3 tests fail on `/internal/videos/resolve != /internal/videos/metadata` at :109, :121 and :140, not on a typo or setup. This remediation edited only the docstring and one comment. No rewrite was needed.\n</answers>",
    "self_check:tests/tmp/test_14_batch_like_resolution_phase3.py": "<rows>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_14_batch_like_resolution_phase3.py:109 \u2014 after one likes-page POST of [u-c, u-a, u-c (repeat), u-x (unknown), u-b], the stand-in Engine's full record of every request (POST and GET, any path) equals exactly one entry: (`/internal/videos/metadata`, {\"entries\": [the five submitted {video_uuid, instance_domain} pairs, in order]})</assertion>\n<expected>[(\"/internal/videos/metadata\", {\"entries\": [u-c, u-a, u-c, u-x, u-b pairs]})], one element. Observed: the probe run, which emulates the one-call Client, printed `PAGE correct: PASS`.</expected>\n<wrong_implementation>The current per-like resolve loop. Observed in this turn's run: `At index 0 diff: ('/internal/videos/resolve', {'host': 'h.example', 'uuid': 'u-c'}) != ('/internal/videos/metadata', ...)`. A fix that keeps a resolve call before the metadata call, or sends two metadata calls, also gives a record longer than one and fails the same equality.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_14_batch_like_resolution_phase3.py:117 \u2014 after the likes-page bodies `{}`, `{\"likes\": []}` and a list of only malformed likes, the Engine record is `[]`. It is armed by the control at :120 (`assert received`): a well-formed like sent next on the same Engine is recorded.</assertion>\n<expected>[] at :117, then a non-empty record at :120. Observed: in this turn's run both :117 and the :120 control passed, and the test first failed at :121.</expected>\n<wrong_implementation>A Client that calls the Engine even with nothing to resolve, for example one that drops the empty-parse early return and posts `{\"entries\": []}` to metadata. The record then holds a request, not `[]`. A stand-in that recorded nothing would pass :117 vacuously, which is the case the :120 control excludes.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_14_batch_like_resolution_phase3.py:121 \u2014 the single well-formed like sent after the empty bodies leaves exactly `[(\"/internal/videos/metadata\", {\"entries\": [u-a pair]})]` in the record</assertion>\n<expected>[(\"/internal/videos/metadata\", {\"entries\": [{\"video_uuid\": \"u-a\", \"instance_domain\": \"h.example\"}]})]. Observed: the probe printed `EMPTY correct: PASS` for the emulated one-call Client.</expected>\n<wrong_implementation>The current resolve loop. Observed in this turn's run, failing at :121: `At index 0 diff: ('/internal/videos/resolve', {'host': 'h.example', 'uuid': 'u-a'}) != ('/internal/videos/metadata', ...)`. This is the one-like input, so a Client that resolves one like at a time and batches only larger bodies still fails.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_14_batch_like_resolution_phase3.py:140 \u2014 an import of [u-a, u-b (disliked), u-x (unknown), u-c] leaves exactly one Engine request, to `/internal/videos/metadata`, carrying the four submitted pairs in order</assertion>\n<expected>[(\"/internal/videos/metadata\", {\"entries\": [u-a, u-b, u-x, u-c pairs]})]. Observed: the probe printed `IMPORT correct: PASS` for the emulated import, which makes one `fetch_metadata_for_entries` call.</expected>\n<wrong_implementation>An import still on `resolve_videos_by_uuid_host`, even after the likes page is fixed. Observed in this turn's run: `At index 0 diff: ('/internal/videos/resolve', {'host': 'h.example', 'uuid': 'u-a'}) != ('/internal/videos/metadata', ...)`. An import that resolves first and then asks metadata gives two or more records.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_14_batch_like_resolution_phase3.py:141 \u2014 the import answers `(200, {\"imported\": 2})`. The Engine returns rows A, B, C, B is disliked and sits between the two clean rows, and u-x has no row.</assertion>\n<expected>(200, {\"imported\": 2}). Observed: the probe printed `IMPORT correct: PASS` for the emulated import.</expected>\n<wrong_implementation>Probe run this turn, each reported as `FAIL at line 141`: an import that ignores dislikes (reads 3); one that keys the like on the entry's uuid instead of the row's video_id, so `is_disliked` misses id-b (reads 3); one that skips the first returned row (reads 1); one that skips the last returned row (reads 1).</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_14_batch_like_resolution_phase3.py:142 \u2014 `load_liked_keys(conn, profile_id) == {(\"id-a\", HOST), (\"id-c\", HOST)}`: the returned rows' video_ids, which differ from their uuids, and not the disliked id-b</assertion>\n<expected>{(\"id-a\", \"h.example\"), (\"id-c\", \"h.example\")}. Observed: the emulated import passed this line (`IMPORT correct: PASS`).</expected>\n<wrong_implementation>An import that records B despite the dislike, which adds (\"id-b\", HOST). One that stores the browser entry's uuid as the video_id, which gives {(\"u-a\", HOST), (\"u-c\", HOST)}. In the probe each of these mutants was caught first at :141, so this line is the stored-state view of the same exclusion.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_14_batch_like_resolution_phase3.py:143 \u2014 the profile's `likes` table holds exactly {(\"id-a\", \"u-a\", HOST), (\"id-c\", \"u-c\", HOST)}, so each like carries its Engine row's video_id, video_uuid and instance_domain</assertion>\n<expected>{(\"id-a\", \"u-a\", \"h.example\"), (\"id-c\", \"u-c\", \"h.example\")}. Observed: the emulated import passed this line.</expected>\n<wrong_implementation>An import that builds the recorded video without the row's `video_uuid`. The probe's \"drops uuid\" mutant printed `FAIL at line 143`, because the stored like had an empty uuid while :141 and :142 still passed.</wrong_implementation>\n</row>\n</rows>\n\n<answers>\n1. Whole claim: yes, every clause is carried. The docstring's first bullet (one metadata call, the five pairs in order, 200 with known rows in submitted order) is :109 and :110. The second bullet (empty, `[]` and all-malformed bodies answered 200 with `likes == []` and no Engine call, then a well-formed like reaching it) is :117, :119, :120 and :121. The third bullet (import: one call carrying four pairs, `{\"imported\": 2}`, liking exactly the two clean videos with their rows' video_id, video_uuid and instance_domain) is :140, :141, :142 and :143. C1 is carried on the likes page (:109, :121) and on import (:140). C2 is carried at :141 to :143.\n2. Absence only: one yes, now fixed. :117 (`received == []`) was armed only by the old :120, which combined the control and the C1 claim in one equality. On the current code that line was red, so the red could be read as a failed control. I split it into a separate control at :120 (`assert received, \"control: ...\"`) and the C1 equality at :121. In this turn's run the control passed and the test first failed at :121. No other assertion is a bare negative: :109, :140 and :141 to :143 are exact equalities.\n3. Echoed literal: no. Every expected value is a literal (A/B/C rows, the `_entry` pairs, `{\"imported\": 2}`, the id sets). Nothing reads back from the production path. The Client's `_parse_client_likes` uuid/host \u2192 video_uuid/instance_domain mapping is the wire contract, written out as literals. Production lines whose deletion turns a line red: the single `fetch_metadata_for_entries` call in `_handle_user_profile_likes_from_client` and `_handle_likes_import` (:109, :121, :140); the `is_disliked(...)` skip in `_handle_likes_import` (:141, :142); the `video_uuid` field of the dict passed to `record_like` (:143). The probe showed each of these mutants red.\n4. One value: no. The call count is read at three inputs: a five-like body with a repeat and an unknown (:109), a one-like body (:121) and a four-like import (:140). Zero calls are read at three different empty or malformed bodies (:117). C2 is read over a clean/disliked/unknown/clean mix whose disliked row sits between the clean ones, so skip-first and skip-last are told apart (observed). Each video_id differs from its uuid, so keying on the entry is told apart from keying on the row.\n5. The double: no double stands in for Client code. The stand-in replaces the Engine process across its HTTP boundary. That is the severed layer this checkpoint's seam names, and the operator approved it in the plan (\"a live Engine cannot count HTTP calls\"). The real Engine's metadata behaviour is gated at its own seam in phases 1 and 2, and the live-Engine test `tests/active/test_profiles.py` import test covers the joined path in its own invocation. The Client (`ClientBackendServer`, `connect_db`, `ensure_user_schema`, `resolve_profile`, `write_dislike`, `load_liked_keys`) is all real code over a real `users.db`.\n6. It collects: yes. The `--collect-only -q` summary line read \"no tests\", which is the runner's summary for that mode. Both of this turn's real runs printed `collected 3 items`, and all 3 tests ran past setup. The import test executed `client_server.connect_db`, `resolve_profile`, `write_dislike(conn, profile_id, B, None)`, `load_liked_keys` and the `likes` SELECT before failing at :140, so every import, name and helper signature binds. The count is 3, matching the three tests written.\n7. Observed, not predicted: yes, every expectation comes from a run. This turn I re-ran `tests/tmp/probe_14_phase3.py -s`. It emulates the one-call Client by monkeypatching `resolve_videos_by_uuid_host` in `client_server` and printed `PAGE correct: PASS`, `EMPTY correct: PASS`, `IMPORT correct: PASS`, `IMPORT ignores dislikes: FAIL at line 141`, `IMPORT keys on entry uuid: FAIL at line 141`, `IMPORT skips first row: FAIL at line 141`, `IMPORT skips last row: FAIL at line 141`, `IMPORT drops uuid: FAIL at line 143`. That run shows the Client accepting the stand-in's `{\"ok\",\"count\",\"rows\"}` reply, and the C1 and C2 expectations holding under a correct implementation and failing under the wrong ones. The current code's resolve-first behaviour is observed in the checkpoint run itself. Caveat: the \"correct\" implementation is an emulation through a monkeypatch, not the phase's code. The phase's build run confirms it.\n8. Red, not green: yes. After the rewrite, `ValidateTests tests/tmp/test_14_batch_like_resolution_phase3.py` printed `3 failed` with `[exit status 1]`.\n9. Red for the right reason: yes, and no control failed. The three failures are `test_14_batch_like_resolution_phase3.py:109: AssertionError`, `:121: AssertionError` and `:140: AssertionError`, all C1 assertions. Each reads `At index 0 diff: ('/internal/videos/resolve', {'host': 'h.example', 'uuid': ...}) != ('/internal/videos/metadata', {'entries': [...]})`. The Client still calls the per-like resolve route, which is the phase's unbuilt behaviour. The controls passed: :117, :119 and the new :120 control, and at :126/:130 the mint returned 201 and `resolve_profile` matched. C2 (:141 to :143) is not reached in this red because :140 fails first in the same test. Its discrimination is shown by the probe run in answer 7.\n10. Observed expected output: yes. Every row's `expected` is what a run showed: the probe's PASS for the emulated correct Client, and the checkpoint run's resolve-first record for the current code. No run contradicted a row. The one change a run forced was the :120 control/:121 claim split; the probe then reported the C2 lines at their new numbers, 141 and 143, which the rows use. Housekeeping: `tests/tmp/probe_14_phase3.py` and the earlier `probe_14_*` and `probe_phase1_*` files are still on disk and need deleting. I have no delete tool. The checkpoint was run last, so `tests/last_test_validation.json` records its exit 1.\n</answers>\n\n<exemptions>\nnone\n</exemptions>",
    "step_7_implement:3": "<changes>\n### `client/backend/server.py`\n- **Import:** `resolve_videos_by_uuid_host` is no longer imported from `lib.engine_api_client`. The import line is now `fetch_metadata_for_entries, resolve_video_seed)`.\n- **`_handle_likes_import`:** the per-like resolve call is replaced by one `fetch_metadata_for_entries(self.server.engine_ingest_base, likes)` call. It is passed the `_parse_client_likes` output unchanged: `{video_uuid, instance_domain}` pairs, not deduplicated, because the Engine parser removes duplicates. For each returned row, the loop checks `is_disliked(conn, profile_id, row[\"video_id\"], row[\"instance_domain\"])` and otherwise calls `record_like(conn, profile_id, \"like\", row, MAX_LIKES)`. The row is passed as-is because `record_like` reads only `video_id`, `instance_domain` and `video_uuid`. The following are unchanged:\n  - the 502 text `Engine resolve failed: ...` (plan 15 rewrites it);\n  - the `with conn:` block;\n  - the `{\"imported\": n}` response.\n- **Empty import:** there is no Engine call when nothing parses, because `fetch_metadata_for_entries` returns `[]` for an empty list.\n- **`_handle_user_profile_likes_from_client`:** the two calls (resolve, then metadata) are now one `fetch_metadata_for_entries(self.server.engine_ingest_base, likes)` call, and its rows come back as `likes`. The following are unchanged:\n  - the early 200 when nothing parses;\n  - the 502 text `Engine metadata failed: ...`;\n  - the response shape.\n- **Docstring:** the placeholder docstring (\"Handle handle user profile likes from client.\") now describes what the handler does: one Engine call, submitted order, unknown videos omitted.\n\n### `client/backend/lib/engine_api_client.py`\n- **`resolve_videos_by_uuid_host` is deleted.** It was the per-like `/internal/videos/resolve` loop. `resolve_video_seed` stays, because user actions and block-add still use it.\n- **Docstring:** `fetch_metadata_for_entries` now says it takes `{video_id|video_uuid, instance_domain}` entries and returns one row per video in first-entry order. Its logic is unchanged.\n\n### Not changed\n- **Other references:** a grep of `client/` finds no remaining reference to `resolve_videos_by_uuid_host`. The stale copies in `delete_me/` still mention it; I left them alone because nothing imports them.\n- **`tests/tmp/test_client_like_batching.py`:** the phase's files list names this new file, but I did not create it. The gating checkpoint is `tests/tmp/test_14_batch_like_resolution_phase3.py`, and it covers the whole phase, so no second test file was needed.\n- **Checkpoint:** I did not run it. The workflow's run is the one that counts.\n</changes>\n\n<inner_tests>\nnone\n</inner_tests>\n\n<unanticipated>\nnone\n</unanticipated>\n\n<awaiting_operator>\nnone\n</awaiting_operator>",
    "author:tests/tmp/test_14_batch_like_resolution_phase4.py": "<assertions>\ntests/tmp/test_14_batch_like_resolution_phase4.py:109 \u2014 a 60-like likes-page body reaches the Engine as exactly one request, `/internal/videos/metadata`, whose `entries` are the `{video_uuid, instance_domain}` pairs u-00..u-49 in order (C1)\ntests/tmp/test_14_batch_like_resolution_phase4.py:110 \u2014 that likes-page request is answered 200 with the rows of exactly id-00..id-49, in submitted order (C1)\ntests/tmp/test_14_batch_like_resolution_phase4.py:123 \u2014 a 60-like import reaches the Engine as exactly one `/internal/videos/metadata` request whose `entries` are u-00..u-49 in order (C1)\ntests/tmp/test_14_batch_like_resolution_phase4.py:124 \u2014 the import answers exactly (200, {\"imported\": 50}) (C1)\ntests/tmp/test_14_batch_like_resolution_phase4.py:125 \u2014 the profile's liked keys afterwards are exactly (id-00..id-49, h.example) (C1)\ntests/tmp/test_14_batch_like_resolution_phase4.py:131 \u2014 a keyless 60-like `POST /recommendations` is answered 200 (C1)\ntests/tmp/test_14_batch_like_resolution_phase4.py:133 \u2014 that request makes exactly one forwarded request, to path `/recommendations`, whose `likes` are the `{uuid, host}` pairs u-00..u-49 in order (C1)\n</assertions>\n\n<probes>\nCommand: ValidateTests [\"tests/tmp/probe_14_phase4.py\", \"-s\"]. The probe loads the checkpoint module and runs its three tests with `server.MAX_CLIENT_LIKES` monkeypatched to 200, 50, 49 and 51. It also runs the likes-page and import tests against a variant of `_parse_client_likes` that keeps the last 50 entries. Output: the current `MAX_CLIENT_LIKES` is 200. With cap=200, the tests fail at lines 109, 123 and 133. With cap=50, all three pass. With cap=49 and cap=51, they fail at lines 109, 123 and 133. The last-50 variant fails at lines 109 and 123. So every wrong version fails on the first C1 assertion it reaches, which is the request the Engine received. An earlier run of the same probe printed the recorded requests for the keyless recommendations path: `[('/recommendations?limit=48', ['likes'], 60)]` at cap 200 and `[('/recommendations?limit=48', ['likes'], 50)]` at cap 50. That showed the Client adds `?limit=48` to the forwarded path and forwards a body whose only key is `likes`. This is why line 133 compares only the URL path. It also showed that minting a profile makes no call to the Engine, because at cap 50 the import test's recorded requests contain only the one metadata request. The probe file `tests/tmp/probe_14_phase4.py` is still on disk because I have no tool that deletes files; it should be removed.\n</probes>\n\n<unassertable>\nnone\n</unassertable>",
    "self_check:tests/tmp/test_14_batch_like_resolution_phase4.py": "<rows>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_14_batch_like_resolution_phase4.py:109 \u2014 a 60-like `POST /api/user-profile/likes` body leaves the stand-in Engine with exactly one recorded request, `(\"/internal/videos/metadata\", {\"entries\": [{video_uuid: u-00..u-49, instance_domain: h.example}]})`, in submitted order</assertion>\n<expected>`received == [(\"/internal/videos/metadata\", {\"entries\": <the 50 pairs u-00..u-49>})]`. The probe checked this: with `client_server.MAX_CLIENT_LIKES` monkeypatched to 50, this test passes.</expected>\n<wrong_implementation>The current cap of 200 (`client/backend/server.py:51`). The probe observed one metadata request with 60 entries, u-00 through u-59. A cap of 49 or 51 also fails at :109 (observed). So does a `_parse_client_likes` that keeps the last 50 entries instead of the first 50 (observed). A second Engine call, such as a leftover per-like resolve, would also make the list comparison unequal.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_14_batch_like_resolution_phase4.py:110 \u2014 that likes-page request is answered `(200, [id-00..id-49])`, the rows of exactly the first 50 videos, in order</assertion>\n<expected>`(200, [\"id-00\", \u2026, \"id-49\"])` (passes at an emulated cap of 50)</expected>\n<wrong_implementation>Cap 200: status 200 and 60 rows, id-00 through id-59 (observed). A cap that dropped entries with a 4xx instead of trimming them silently would also fail on the status.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_14_batch_like_resolution_phase4.py:123 \u2014 a 60-like `POST /api/profile/likes/import` records exactly one Engine request, `(\"/internal/videos/metadata\", {\"entries\": [u-00..u-49 pairs]})`</assertion>\n<expected>`received == [(\"/internal/videos/metadata\", {\"entries\": <the 50 pairs u-00..u-49>})]`. Minting the profile makes no Engine call; this passes at an emulated cap of 50.</expected>\n<wrong_implementation>Cap 200: one metadata request with 60 entries, u-00 through u-59 (observed). A cap of 49 or 51, or keeping the last 50, also fails at :123 (observed).</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_14_batch_like_resolution_phase4.py:124 and :125 \u2014 the import answers `(200, {\"imported\": 50})` and the profile's liked keys are exactly `{(id-00..id-49, h.example)}`</assertion>\n<expected>`(200, {\"imported\": 50})` and exactly 50 liked keys, id-00 through id-49 (passes at an emulated cap of 50)</expected>\n<wrong_implementation>Cap 200: `{\"imported\": 60}` and 60 liked keys, id-00 through id-59 (observed). The Client capping the request while the import still records a like for every submitted entry would also fail here.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_14_batch_like_resolution_phase4.py:131 and :133 \u2014 a keyless 60-like `POST /recommendations` gets 200, and the only forwarded request goes to path `/recommendations` with `likes` equal to the `{uuid, host}` pairs u-00..u-49</assertion>\n<expected>Status 200, and `[(\"/recommendations\", [<the 50 pairs u-00..u-49>])]`. The query string `?limit=48` is dropped by `urlparse(...).path` (observed). This passes at an emulated cap of 50.</expected>\n<wrong_implementation>Cap 200: one forwarded request, `/recommendations?limit=48`, with 60 likes, u-00 through u-59 (observed). The same happens if only the two `_parse_client_likes` readers are capped and the proxy trim `likes[:MAX_CLIENT_LIKES]` at `server.py:492` is missed. A cap of 49 or 51 also fails at :133 (observed).</wrong_implementation>\n</row>\n</rows>\n\n<answers>\n1. Whole claim: no gap. C1 says a 60-like body reaches the Engine as its first 50 entries. The test checks this on all three `MAX_CLIENT_LIKES` readers the plan lists: the likes page (:109), the import (:123) and the proxy (:133). Each is an equality over the full recorded request list, so the count, the order and which 50 entries were kept are all checked. Every clause in the docstring is asserted: the 200 and the 50 rows (:110), `{\"imported\": 50}` (:124), the profile liking exactly those 50 (:125), and the keyless 200 (:131).\n2. Absence only: no. There are no negative assertions. Dropping the last 10 is checked positively, by exact equality with the first 50.\n3. Echoed literal: no. The expected values are literals built from `range(50)`. The test never slices the submitted list, which is production's transformation. The line that decides the outcome is `MAX_CLIENT_LIKES` at `client/backend/server.py:51`. Setting it back to 200 turns :109, :123 and :133 red (observed). Deleting the `[:MAX_CLIENT_LIKES]` slice at :492 turns :133 red.\n4. One value: no. The input is 60 because that is the clause, and the output reads the cap exactly: a cap of 49 or 51 fails (observed). No value is compared against a sibling from the same source; every expected value is a literal.\n5. The double: no, not for any in-process module the project owns. The Engine stand-in replaces a separate process across the HTTP boundary. That is the seam the plan approved: the live Engine cannot record requests, and it answers 400 above 5 likes on the proxy. The Client (`ClientBackendServer`), `users.db`, `resolve_profile` and `load_liked_keys` are all real. The C1 assertions at :109, :123 and :133 read what the Client sent, not anything the stand-in computed.\n6. It collects: yes. The `--collect-only` summary line says \"no tests\", but the real run printed \"collected 3 items\", and all three tests reached their assertions. So every import resolves (`conftest`, `lib.profiles`, `lib.users_store`), every name binds, and `ClientBackendServer(...)`, `ClientBackend(base, db_path)`, `.request` and `.db_path` all ran. I wrote 3 tests and 3 were collected.\n7. Observed, not predicted: yes on one point, now rewritten. The comment at :108 said \"Observed\" about counts for caps of 49 and 51 and about the entries kept by a last-50 variant, but no run had printed those. I re-ran `tests/tmp/probe_14_phase4.py` with `-s`. At the current cap of 200 all three tests fail at 109, 123 and 133. At an emulated cap of 50 all three PASS. At 49 and at 51 they fail at 109, 123 and 133. The last-50 variant fails at 109 and 123. I also printed `len(_parse_client_likes(body, 0)) == 60`, which confirms that variant's emulation is valid. The comment now states only what was printed. `tests/tmp/probe_phase4_cap.py` printed today's values: likes page gets 1 request with 60 entries (u-00 to u-59), then 200 with 60 rows (id-00 to id-59). Import gets 1 request with 60 entries, then `{'imported': 60}` and 60 liked. Recs: 200, one request to `/recommendations?limit=48` with 60 likes. Every `expected` value in the rows comes from these runs.\n8. Red, not green: red. `ValidateTests [\"tests/tmp/test_14_batch_like_resolution_phase4.py\"]` gave exit status 1: \"collected 3 items\", \"3 failed in 1.56s\".\n9. Red for the right reason: yes. Each test fails on its first C1 assertion, and none fails on a control. `:109: AssertionError`: the recorded request is `('/internal/videos/metadata', {'entries': [{'video_uuid': 'u-00', ...` and holds 60 entries, not 50 (probe). `:123: AssertionError`: the same request, with 60 entries. `:133: AssertionError`: `('/recommendations', [{'uuid': 'u-00', 'host': 'h.example'}, ...` with 60 likes. The harness worked: the Client answered 200, the stand-in recorded exactly one request per test, and minting the profile (status 201, :116) passed. The failures come from `MAX_CLIENT_LIKES = 200`, which the phase changes to 50.\n10. Observed expected output: yes. Each row's `expected` value is what the probe saw at an emulated cap of 50, where all three tests passed. Each `wrong_implementation` value is what the runs printed at cap 200, 49, 51 or last-50. Housekeeping: I have no delete tool, so `tests/tmp/probe_phase4_cap.py` and `tests/tmp/probe_14_phase4.py` are still on disk and should be removed.\n</answers>\n\n<exemptions>\nnone\n</exemptions>",
    "step_7_implement:4": "<changes>\n### `client/backend/server.py`\n- `MAX_CLIENT_LIKES` went from 200 to 50. I added a one-line comment above it: it caps like entries per request, it matches the browser's local-likes limit (ADR-0003), and entries past the cap are dropped, not rejected.\n- The three places that read it are unchanged: the `/recommendations` and `/videos/similar` proxy trim (`likes[:MAX_CLIENT_LIKES]`), and the `_parse_client_likes(body, MAX_CLIENT_LIKES)` calls in `_handle_likes_import` and `_handle_user_profile_likes_from_client`. All three still cut the raw list before dropping malformed entries.\n- A grep outside `docs/` and `delete_me/*.bak-*` found no other code that reads the constant.\n\n### `tests/tmp/test_client_like_batching.py`\n- Not touched, because it doesn't exist. The phase lists it as EDITED, but phase 3's checkpoint was written to `tests/tmp/test_14_batch_like_resolution_phase3.py`, and this phase's checkpoint `tests/tmp/test_14_batch_like_resolution_phase4.py` builds its own stand-in Engine. The constant change is all this checkpoint needs.\n\n### Housekeeping for the operator\n- The test author's probe files `tests/tmp/probe_14_phase4.py` and `tests/tmp/probe_phase4_cap.py` (the second is named in the record; I didn't check it is on disk) are still there and should be deleted. I have no tool that deletes files.\n- This step's prompt came with its `{rat_tail_ladder}`, `{rat_tail_rules}` and `{rat_tail_keep_in_full}` placeholders unfilled.\n</changes>\n\n<inner_tests>\nnone\n</inner_tests>\n\n<unanticipated>\nnone\n</unanticipated>\n\n<awaiting_operator>\nnone\n</awaiting_operator>",
    "step_8_i1_refactor": "<refactors>\nengine/server/data/metadata.py \u2014 `_select_metadata` returns `[dict(row) for row in rows]` in place of the 29-entry hand-written row builder. A probe run showed that a `sqlite3.Row` is keyed by its SELECT names (`v.video_id` \u2192 `video_id`, `c.display_name AS channel_display_name` \u2192 `channel_display_name`) and that `dict(row)` keeps SELECT order, which was the builder's key order. So the rows have the same keys, values and order as before.\nengine/server/data/metadata.py \u2014 new public `uuid_key(entry)` builds the `video_uuid::instance_domain` key, and `fetch_metadata_by_uuids` uses it in place of its inline f-string (same output for a dict row).\nengine/server/api/handlers/internal_client_reads.py \u2014 removed the private `_uuid_key` copy. The handler imports `uuid_key` from `data.metadata`, so the key it looks rows up by and the key the data layer stores them under come from one function and cannot drift apart.\nengine/server/api/handlers/internal_client_reads.py \u2014 `_parse_entries` (the centroids parser) now uses the `_stripped` helper phase 2 added, in place of its own isinstance/strip checks, and `_stripped` moved above it. It still accepts, skips, strips, dedups and orders items exactly as before.\nclient/backend/server.py \u2014 dropped the early empty-likes 200 in `_handle_user_profile_likes_from_client`. `fetch_metadata_for_entries` already returns `[]` without an HTTP call for an empty list, so the response is still 200 `{\"likes\": [], \"updatedAt\": ...}` with zero Engine requests. This also matches `_handle_likes_import`, which already relied on that short-circuit.\n</refactors>\n\n<left_out>\nDeduping `fetch_metadata` (the rowid lookup) onto the shared SELECT/row builder: this build never changed it (phase 1 \"Not changed\"), and grep finds no test under tests/ that calls it. Changing it without any gating coverage is a risk I would not take without a run; it needs its own change with a test.\nReplacing the handler's `_like_key` with `recommendations.keys.like_key`: the output is the same for dicts, but the duplication predates this build and is not part of the new functionality.\nMerging `_parse_client_likes` with the `/recommendations` proxy likes sanitiser in client/backend/server.py: they emit different key shapes (`video_uuid/instance_domain` vs `uuid/host`), and the duplication predates this build.\nFactoring the shared chunk-and-OR loop of `fetch_metadata_by_ids`/`fetch_metadata_by_uuids` into one helper: the two differ on purpose in parenthesisation (Open item A, option 1) and in how they key rows. A helper would need flags for both and would not be simpler.\nNot confirmed by a run: I did not run the checkpoints (the workflow's run is the one that counts). The `dict(row)` swap rests on the probe; the other changes are identity-preserving rewrites. The phase 1 test (exact 29 keys, full-row equality) and the phase 2/3 checkpoints are what will confirm them.\nHousekeeping I cannot do (no delete tool): my probe `tests/tmp/probe_refactor_row_keys.py` (fails on purpose with `assert False`) should be deleted, along with the earlier probes `tests/tmp/probe_14_phase1.py`, `probe_14_phase2.py`, `probe_14_phase3.py`, `probe_14_phase4.py`, `probe_14_n4.py`, `probe_phase1_against_impls.py`, `probe_phase1_metadata.py` and `probe_phase4_cap.py`. This step's `{rat_tail_rules}` placeholder was not filled in, so I measured the pass against the role's general rules; none of the refactors adds or changes a `rat-tail:` comment.\n</left_out>\n\n<needs_fresh_red>\nnone\n</needs_fresh_red>\n\n<observation>\nA probe showed that sqlite3.Row is keyed by SELECT names and that dict(row) keeps SELECT order, so the new metadata path now has one SELECT, one row builder and one uuid key shared by the data layer and the handler, with no behaviour change on any path a checkpoint gates.\n</observation>",
    "step_9_triage": "<docs>\n<doc path=\"client/README.md\" update=\"yes\">\nLine 15 (`POST /api/profile/likes/import`) is incomplete: it does not say that only the first 50 entries of `likes` are read and the rest are dropped, not rejected. It also does not say that the likes are resolved in one Engine metadata call, so a video the Engine does not know, or holds at or over its error-count threshold, is not imported (ADR-0003). Add both to the existing sentence, which keeps \"a video the profile dislikes is skipped. Answers `{imported}`\". Line 22 (`POST /api/user-profile/likes` \u2014 \"resolves a browser-supplied like list; needs no profile.\") needs to say how: it reads at most the first 50 `{uuid, host}` entries and resolves them in one Engine metadata call. It answers `likes` in submitted order, with duplicates removed, and leaves out any video the Engine does not know or holds at or over its error threshold. An empty or fully malformed list answers `{likes: []}`. Nowhere is the 50-entry cap on the `/recommendations`/`/videos/similar` `likes` list stated. The nearest place is line 26, next to the keyed-likes sentence: say that a keyless body's `likes` are cut to their first 50 before being forwarded. Lines 30 and 37-39 stay accurate, because `/internal/videos/resolve` is still used by user actions and block-add.\n</doc>\n<doc path=\"engine/server/README.md\" update=\"yes\">\nLine 11 (\"`/internal/videos/metadata` internal metadata batch lookup for Client likes/profile.\") is now incomplete. It should say:\n- entries are `{video_id, instance_domain}` or `{video_uuid, instance_domain}`, and both forms can be mixed in one body;\n- an entry with a non-empty `video_id` is treated as the id form;\n- the uuid match is exact;\n- all entries are answered under a single `db_lock` hold, one row per video, in the order of the first entry that matches it;\n- when several videos share a `(video_uuid, instance_domain)`, the lowest `video_id` wins;\n- videos at or over the error-count threshold, and unembedded videos, are left out for both forms.\n\nAlso add to line 12 (`/internal/dislikes/centroids`) that it takes only `video_id` entries. Line 10 (resolve) is unchanged and still accurate.\n</doc>\n<doc path=\"docs/project/adr/0003-metadata-endpoint-accepts-uuid-entries.md\" update=\"yes\">\nThe Decision matches what was built: both entry forms, one lock hold, the likes page and import on one call, the resolve loop removed, and `MAX_CLIENT_LIKES = 50` on all three sites, with extra entries dropped. The existing error-threshold consequence is also right. Consequences is missing two differences from the old resolve path that the build delivered and the operator approved. Add them as bullets, stated as current behaviour:\n1. When several videos share one `(video_uuid, instance_domain)`, the one with the lowest `video_id` among those that pass the error filter is used (`fetch_metadata_by_uuids`).\n2. There is no check on the embedding blob, so a video whose embedding blob is empty or does not match `embedding_dim` is still shown on the likes page and still imported.\n</doc>\n<doc path=\"docs/project/issues/03-batch-like-resolution.md\" update=\"yes\">\nIssue 03 is delivered. At harvest on main:\n- set the `Status:` line to `bug, complete`;\n- add a delivery comment covering what was delivered: one `/internal/videos/metadata` call per likes-page or import request under one `db_lock` hold, `resolve_videos_by_uuid_host` removed, and `MAX_CLIENT_LIKES` 200 \u2192 50;\n- move the file to `docs/project/issues/archive/`, per `docs/project/triage-labels.md`.\n</doc>\n<doc path=\"docs/project/plans/14-batch-like-resolution.md\" update=\"yes\">\nAt harvest on main, archive it together with `16-14-batch-like-resolution.md` and `16-14-batch-like-resolution.record.md` in `docs/project/plans/archive/`. Its text needs no correction beyond what the 16-14 entry below lists.\n</doc>\n<doc path=\"docs/project/plans/16-14-batch-like-resolution.md\" update=\"yes\">\nThe Step 5 checklist lists this under plan 14, but its corrections belong here. Before it is archived, fix these in the plan text:\n1. **The \"Missing index\" risk is wrong.** `idx_videos_uuid_instance ON videos (video_uuid, instance_domain)` exists (`engine/server/data/videos.py:21-22`) and is created on every Engine start.\n2. **The test pattern cites `test_db.py`.** The handler tests follow the `ENGINE_PY` child used by `test_internal_events.py`/`test_similar.py`, and the data-layer tests run in-process.\n3. **The files lists name test files that were never created.** These are `tests/tmp/test_metadata_uuid_entries.py` and `tests/tmp/test_client_like_batching.py`. The checkpoints landed as `tests/tmp/test_14_batch_like_resolution_phase{1..4}.py`.\n4. **Phase 1's description is out of date after the refactor.** It describes a hand-written row builder. `_select_metadata` returns `dict(row)`, and the handler imports the shared public `uuid_key` from `data.metadata`.\n</doc>\n</docs>\n\n<adr_conflicts>\nnone\n</adr_conflicts>",
    "step_9_i2_update:client/README.md": "<changes>\nI added the 50-entry cap and the single Engine metadata call to the two browser-likes endpoints in `client/README.md`, and the cap to the feed-proxy `likes` note.\n\n- **Line 15 (`POST /api/profile/likes/import`):** says that only the first 50 `likes` entries are read and the rest are dropped, not rejected. The likes are resolved in one `/internal/videos/metadata` call, so a video the Engine does not know, or holds at or over its error-count threshold, is not imported (ADR-0003). The disliked-video skip and the `{imported}` answer stay as they were.\n- **Line 22 (`POST /api/user-profile/likes`):**\n  - States the body shape `{likes: [{uuid, host}]}` and that at most the first 50 entries are resolved, in one metadata call.\n  - It answers `{likes, updatedAt}`, in submitted order with duplicates removed. Unknown videos and videos at or over the error threshold are left out.\n  - An empty or fully malformed list answers `{likes: []}` without calling the Engine.\n  - It points to `engine/server/README.md` for how the Engine matches entries, and does not restate that.\n- **Line 26 (keyed-likes sentence):** a keyless `/recommendations` or `/videos/similar` body has its `likes` cut to the first 50 entries before they are forwarded. Entries past the 50th are dropped, not rejected.\n\nI checked all of this against the worktree code:\n- `MAX_CLIENT_LIKES = 50` in `server.py:52`.\n- The proxy trim at `server.py:493`.\n- `_handle_likes_import` at `:872`.\n- `_handle_user_profile_likes_from_client` at `:1012`.\n- `_parse_client_likes`, which cuts the raw list before skipping malformed entries.\n- `fetch_metadata_for_entries`, which returns `[]` for an empty list without making an HTTP call.\n\nLines 30 and 37\u201339 are unchanged, since `/internal/videos/resolve` is still used by user actions and block-add.\n</changes>\n\n<not_on_checklist>\nnone\n</not_on_checklist>",
    "step_9_i2_update:engine/server/README.md": "<changes>\n`engine/server/README.md`: the `/internal/videos/metadata` entry now describes both entry forms and how they are answered, and the `/internal/dislikes/centroids` entry says it takes id-form entries only.\n\n- **`/internal/videos/metadata`:**\n  - Entries can be `{video_id, instance_domain}` or `{video_uuid, instance_domain}`, and one body can mix both.\n  - An entry with a non-empty `video_id` is treated as the id form.\n  - The uuid match is exact and case-sensitive. When several videos share a `(video_uuid, instance_domain)`, the lowest `video_id` wins.\n  - All entries are answered under one `db_lock` hold. There is one row per video, in the order of the first entry that matches it.\n  - Unembedded videos are never returned.\n  - I checked all of this against `internal_client_reads.py` and `data/metadata.py`.\n- **Error threshold (differs from the checklist):** the checklist says videos at or over the error-count threshold are left out for both forms. The code does that fully only for uuid entries. In `fetch_metadata_by_ids` the conditions are deliberately left without parentheses (commented as Open item A, option 1), so for id entries the threshold applies only to the last pair of each 450-entry chunk. The README states that current behaviour and does not repeat the \"both forms\" claim. You may want this recorded as a known issue or fixed separately. The same point may affect the wording of the ADR-0003 consequence, which is written in another turn.\n- **`/internal/dislikes/centroids`:** adds \"It takes only `{video_id, instance_domain}` entries.\" I also rejoined its hard-wrapped lines into one line.\n- The resolve line is unchanged.\n</changes>\n\n<not_on_checklist>\nnone\n</not_on_checklist>",
    "step_9_i2_update:docs/project/adr/0003-metadata-endpoint-accepts-uuid-entries.md": "<changes>\nI added two bullets to the ADR-0003 Consequences for the two approved differences from the old resolve path: the lowest-`video_id` tie-break, and no embedding-blob check.\n\n- **Tie-break:** when several videos share one `(video_uuid, instance_domain)`, a uuid entry gets the video with the lowest `video_id` among those that pass the error-count filter (`fetch_metadata_by_uuids`). I checked this in `engine/server/data/metadata.py:138-160`: the threshold is applied in SQL and the lowest `video_id` is kept per `uuid_key`.\n- **No blob check:** a video whose embedding blob is empty or doesn't match its `embedding_dim` still shows on the likes page and is still imported. I checked `_select_metadata`: it only inner-joins `video_embeddings` and never looks at the blob.\n- **Resolve bullet:** it now reads \"user actions and block-add\". The code confirms both still call `resolve_video_seed`, in `_handle_user_action` and `_handle_block_add` in `client/backend/server.py`.\n\nI left the Context and Decision sections and the existing error-threshold bullet as they were; they match what was built.\n</changes>\n\n<not_on_checklist>\nnone\n</not_on_checklist>",
    "step_9_i2_update:docs/project/issues/03-batch-like-resolution.md": "<changes>\nIssue 03 is now `bug, complete` and has a delivery comment, but I couldn't move it to `issues/archive/` because I have no delete or move tool.\n\n- **Status line:** changed from `bug, ready-for-agent` to `bug, complete`.\n- **Delivery comment:** added under Comments, after the triage decisions. It follows the `**Delivered** by \u2026` format in `archive/05-raw-event-retention.md` and points at the archived locations of `16-14-batch-like-resolution.md` and `14-batch-like-resolution.md`. It covers:\n  - `/internal/videos/metadata` parses its entries with `_parse_metadata_entries`, which accepts both entry forms in one body. It answers them under one `db_lock` hold through `fetch_metadata_by_ids` and `fetch_metadata_by_uuids`, and returns each video once, at its first matching entry.\n  - `/internal/dislikes/centroids` still uses `_parse_entries`, so it takes only `video_id` entries.\n  - The likes page and likes import each make one `fetch_metadata_for_entries` call. Import records a like from each returned row the profile has not disliked.\n  - `resolve_videos_by_uuid_host` is removed. `resolve_video_seed` and `/internal/videos/resolve` stay for user actions and block-add.\n  - `MAX_CLIENT_LIKES` is 50 at all three places that use it.\n  - For the two ways this differs from the old resolve (lowest `video_id` wins; no embedding-blob check), it points to ADR-0003's Consequences rather than repeating them.\n- **Checked against the worktree code:** the constant and where it is used, the removed function, the new parser, the uuid fetch and the shared `uuid_key`, and the single lock hold in the handler.\n- **Not changed:** the Problem, Proposed solution, Agent Brief and acceptance-criteria checkboxes. They stay as the issue's original record, as in the other archived issues.\n- **Still to do at harvest (needs a shell):** move this file to `docs/project/issues/archive/03-batch-like-resolution.md` with `git mv`. The comment's plan links assume both plans are archived in the same harvest.\n</changes>\n\n<not_on_checklist>\nnone\n</not_on_checklist>",
    "step_9_i2_update:docs/project/plans/14-batch-like-resolution.md": "<changes>\nNo edit: plan 14 needs no text correction, and archiving it is a harvest-time move on main.\n\n- **Text left as is.** The checklist entry says this plan needs no correction beyond what the 16-14 entry lists. The 16-14 corrections (the \"Missing index\" risk, the test pattern, the test files that were never created, the Phase 1 row-builder description) all concern `docs/project/plans/16-14-batch-like-resolution.md`. None of them is in this file. This file holds the requirements and the high-level plan the build started from. Its Approach, Alternatives, Risks and Tradeoffs agree with what was delivered:\n  - its own parser for metadata, with centroids left on `_parse_entries`;\n  - a chunked uuid-keyed lookup beside `fetch_metadata_by_ids`;\n  - one `db_lock` hold;\n  - `resolve_videos_by_uuid_host` removed;\n  - `MAX_CLIENT_LIKES` 200 \u2192 50, with extra entries dropped.\n- **Line numbers.** The line numbers in Batch context (`:49`, `:446`, `:837-843`, `:970-980`) describe the tree when the plan was written. The plan already says they drift and that functions should be found by name.\n- **Archiving not done here.** Moving this file to `docs/project/plans/archive/` together with `16-14-batch-like-resolution.md` and `16-14-batch-like-resolution.record.md` happens at harvest on main, not in this worktree. I have no move tool, so it stays as a harvest action.\n</changes>\n\n<not_on_checklist>\nnone\n</not_on_checklist>",
    "step_9_i2_update:docs/project/plans/16-14-batch-like-resolution.md": "<changes>\nI made the four listed corrections to the plan text of `docs/project/plans/16-14-batch-like-resolution.md` and checked each against the worktree code.\n\n**The file may be overwritten.** Its header says it is \"rendered by the `dev-flow` workflow from its run state. Every edit here is overwritten on the next step\". If the harvest or archive step renders it again, these edits will be lost unless the same corrections also go into the run state or `16-14-batch-like-resolution.record.md`.\n\n1. **Missing index (High-level plan, Risks).** I replaced the \"Missing index\" bullet with an \"Index\" bullet. It says that `idx_videos_uuid_instance ON videos (video_uuid, instance_domain)` is defined at `engine/server/data/videos.py:21-22`. `ensure_video_indexes` creates it on every Engine start (`engine/server/api/server.py:337`). A temp-DB test that does not call `ensure_video_indexes` runs without the index, which does not affect correctness.\n2. **Test pattern (High-level plan, Tests).** I dropped the `test_db.py` citation, since it runs its child with `sys.executable`. The paragraph now says the data-layer checks run in-process because `data.metadata` imports no numpy. The handler checks run in a `conftest.ENGINE_PY -c` child, following `test_internal_events.py` and `test_similar.py`.\n3. **Test files that were never created.** Everywhere the plan named `tests/tmp/test_metadata_uuid_entries.py` or `tests/tmp/test_client_like_batching.py`, it now names the checkpoints that actually exist, `tests/tmp/test_14_batch_like_resolution_phase{1..4}.py`. I found all four on disk. The changed places are:\n   - the module map (now four rows, one per checkpoint);\n   - the two Section 5 test headings;\n   - each phase's \"Files touched\" line;\n   - each phase's \"Outcome\" subsection, where the \"not created / doesn't exist\" notes are gone;\n   - the phase 4 checkpoint seam, which no longer says it shares phase 3's test file: it builds its own stand-in Engine.\n4. **The refactor.** These places now match the code as it stands:\n   - **Phase 1 Outcome:** `_select_metadata` returns `[dict(row) for row in rows]`, which gives the same 29 keys in SELECT order. It no longer mentions a hand-written row builder. `fetch_metadata_by_uuids` keys its rows with the public `uuid_key`.\n   - **Phase 2 Outcome:** line 9 imports `fetch_metadata_by_ids, fetch_metadata_by_uuids, uuid_key`. There are now two new helpers, not three, because the private `_uuid_key` is gone. `_parse_entries` does its string checks through `_stripped` and behaves as before.\n   - **Module map:** its metadata.py and handler rows say the same.\n\n**Stale but not on the list, so left alone:**\n- The High-level plan and Draft \u00a71 describe the uuid SQL as a row-value `(v.video_uuid, v.instance_domain) IN (...)` with deduplication before chunking. The built code uses a parenthesised OR of `(v.video_uuid = ? AND v.instance_domain = ?)` and relies on the handler parser to deduplicate. The Phase 1 Outcome already describes this correctly.\n- The Phase 3 Outcome says the \"early 200 when nothing parses\" in `_handle_user_profile_likes_from_client` is unchanged. The Step 8 refactor removed that early return: the empty case now goes through `fetch_metadata_for_entries`'s own short-circuit, and the response is the same.\n</changes>\n\n<not_on_checklist>\nnone\n</not_on_checklist>"
  },
  "requirements": "### Purpose\n\nBuild issue `docs/project/issues/03-batch-like-resolution.md` (category bug) as triaged. It closes the security-audit finding (run-1, `resolve_videos_by_uuid_host` loop): one anonymous `POST /api/user-profile/likes` currently costs up to 201 sequential Engine round trips and 201 acquisitions of the Engine's global `db_lock`. After this build, a batch of browser likes is resolved with one Engine call, and a request is capped at 50 like entries. The decision it rests on is `docs/project/adr/0003-metadata-endpoint-accepts-uuid-entries.md`: `/internal/videos/metadata` accepts `(video_uuid, instance_domain)` entries, and a separate resolve-batch endpoint was rejected. The build is part of the security hardening batch (`.scratch/security-hardening-batch/notes.md`), wave 2 alongside plan 13, and runs in the worktree `/home/enduser/code/PeerTube-browser/.worktrees/fix-14-batch-like-resolution`.\n\n### Current behaviour (verified in the worktree)\n\n- `client/backend/server.py:52`: `MAX_CLIENT_LIKES = 200`, next to `MAX_LIKES = 100` (profile stored-likes limit, out of scope) and `ENGINE_FEED_LIKES_MAX = 5`.\n- `client/backend/server.py:1105` `_parse_client_likes(payload, max_items)`: takes `raw[:max_items]` and then skips malformed items (not a dict, or `uuid`/`host` not a non-empty string). It returns `[{\"video_uuid\", \"instance_domain\"}]` stripped, and does not deduplicate.\n- `client/backend/server.py:493`, the `/recommendations` and `/videos/similar` POST proxy: `for entry in likes[:MAX_CLIENT_LIKES]:` sanitises to `{\"uuid\", \"host\"}`, skipping malformed entries.\n- `client/backend/server.py:872-900`, `_handle_likes_import` (`POST /api/profile/likes/import`, behind `_require_profile`): calls `_parse_client_likes(body, MAX_CLIENT_LIKES)`, then `resolve_videos_by_uuid_host`. On `EngineApiError` it answers 502 `{\"error\": \"Engine resolve failed: ...\"}`. Otherwise, inside `with conn:`, it skips each video where `is_disliked(conn, profile_id, video_id, instance_domain)`, calls `record_like(conn, profile_id, \"like\", video, MAX_LIKES)` for the rest, and answers 200 `{\"imported\": n}`. `record_like` (`client/backend/lib/users_store.py:79`) reads `video_id`, `instance_domain` and `video_uuid` from the dict.\n- `client/backend/server.py:1012-1029`, `_handle_user_profile_likes_from_client` (`POST /api/user-profile/likes`, no profile required): calls `_parse_client_likes`. An empty list gives 200 `{\"likes\": [], \"updatedAt\"}` with no Engine call. Otherwise it calls `resolve_videos_by_uuid_host`, then `fetch_metadata_for_entries(resolved)`. On `EngineApiError` it answers 502 `{\"error\": \"Engine metadata failed: ...\"}`. Otherwise it answers 200 `{\"likes\": rows, \"updatedAt\"}`.\n- `client/backend/lib/engine_api_client.py:136` `resolve_videos_by_uuid_host`: deduplicates on `uuid::host` and makes one `resolve_video_seed` \u2192 `/internal/videos/resolve` call per like. It is imported in `server.py:32`. `fetch_metadata_for_entries` (`:92`) posts `{\"entries\": entries}` to `/internal/videos/metadata`, raises `EngineApiError` on a non-200 status or an invalid payload, and returns the dict rows.\n- `engine/server/api/handlers/internal_client_reads.py:20` `_parse_entries`: returns None when `entries` is not a list, skips malformed items, and deduplicates on `video_id::instance_domain`. It is used by `handle_internal_videos_metadata` (`:95`) and `handle_internal_dislike_centroids` (`:129`). The metadata handler answers 400 `Missing entries`, and answers 200 with empty rows when there are no entries. Under one `with server.db_lock:` it calls `fetch_metadata_by_ids(..., error_threshold=getattr(server, \"video_error_threshold\", None))`, then emits rows in entry order via `_like_key`. The response is `{\"ok\": True, \"count\", \"rows\"}`.\n- `engine/server/data/metadata.py:110` `fetch_metadata_by_ids`: chunks of 450 with an `OR` of `(v.video_id = ? AND v.instance_domain = ?)`. It inner-joins `video_embeddings` and left-joins `channels`, applies `AND (v.error_count IS NULL OR v.error_count < ?)` when the threshold is > 0, and returns a dict keyed by `like_key(row)` (`video_id::instance_domain`).\n- `engine/server/data/embeddings.py:191` `fetch_seed_embeddings_for_likes`: the precedent for a `WHERE (v.video_uuid, v.instance_domain) IN ((?, ?), ...)` batch query. It is not chunked.\n- The old resolve path (`fetch_seed_embedding` \u2192 `_fetch_seed_by_uuid`) matches `v.video_uuid = ? AND v.instance_domain = ?` exactly, with the same `video_embeddings` inner join and `LIMIT 1`, and no error-count filter. `_seed_from_row` also drops rows whose embedding blob is empty or does not match `embedding_dim`.\n- The `videos` table key is `PRIMARY KEY (video_id, instance_domain)`. Nothing enforces uniqueness of `(video_uuid, instance_domain)`.\n\n### R1 \u2014 Engine: metadata endpoint entry parsing\n\n- `/internal/videos/metadata` gets its own entry parser. `_parse_entries` stays unchanged and is still used by `/internal/dislikes/centroids`, so centroids keeps accepting only `video_id` entries, and uuid-only entries there are skipped as malformed, as today.\n- An entry is accepted as `{video_id, instance_domain}` or `{video_uuid, instance_domain}`, where each value is a non-empty string and is stripped. An entry carrying a valid `video_id` is treated as id-keyed, even if it also has `video_uuid`. An entry with neither valid key, or without a valid `instance_domain`, or that is not a dict, is skipped.\n- Duplicates are collapsed within each form (id form on `video_id::instance_domain`, uuid form on `video_uuid::instance_domain`), keeping the first occurrence.\n- A body without an `entries` list still gets 400 `{\"error\": \"Missing entries\"}`. When no entries are valid, the answer is still 200 `{\"ok\": True, \"count\": 0, \"rows\": []}` without taking the lock.\n\n### R2 \u2014 Engine: uuid-keyed batch lookup\n\n- A uuid-keyed batch data function goes beside `fetch_metadata_by_ids` in `engine/server/data/metadata.py` (a sibling function, or a path in the same function). It selects the same columns with the same joins (inner `video_embeddings`, left `channels`) and the same error-count threshold clause, and builds the same row dict, so a video's row is identical whichever form reached it.\n- Its SQL is `WHERE (v.video_uuid, v.instance_domain) IN (...)`, following `fetch_seed_embeddings_for_likes`, chunked like the id lookup (at most 450 pairs per statement). There is no query per entry.\n- The match is exact on `video_uuid` and `instance_domain`, as the old resolve was.\n- A uuid entry yields at most one row. If several videos share one `(video_uuid, instance_domain)`, the one with the lowest `video_id` is chosen, so the choice is deterministic (operator-approved; resolve's `LIMIT 1` was arbitrary).\n- No embedding-blob validity check is added (operator-approved difference from resolve; see conflicts).\n\n### R3 \u2014 Engine: one lock hold, ordering, dedup across forms\n\n- The handler answers every entry of a request, id and uuid forms together, under a single `with server.db_lock:` hold, one acquisition per request.\n- Rows are emitted in the order of the first entry that matches each video. A video reached by both an id entry and a uuid entry (or by several entries) appears once, identified by `video_id::instance_domain`.\n- The error-count threshold filter applies to both forms.\n- The response shape is unchanged: `{\"ok\": True, \"count\": len(rows), \"rows\": rows}`. Existing id-keyed callers (the Client's `_handle_user_profile_likes_get`, `_handle_block_add`, and any other caller) see exactly the rows they saw before.\n\n### R4 \u2014 Client: likes page makes one Engine call\n\n- `_handle_user_profile_likes_from_client` sends the deduplicated `(video_uuid, instance_domain)` entries from `_parse_client_likes` in a single `fetch_metadata_for_entries` call and returns its rows as `likes`. There is no resolve call.\n- Deduplication happens before the call, on `video_uuid::instance_domain`, keeping the first occurrence and submitted order. It may be done by the Client, the Engine parser, or both. The Engine's R1 dedup alone is sufficient.\n- A like whose video is unknown to the Engine (or at or over the error threshold) is omitted without error.\n- An empty parse still answers 200 `{\"likes\": [], \"updatedAt\"}` without an Engine call.\n- The 502 path and body text are left as they are (plan 15 rewrites 502 bodies later).\n- For any request of 50 or fewer likes whose videos all resolve, the response rows and their order are the same as before the change.\n\n### R5 \u2014 Client: likes import makes one Engine call\n\n- `_handle_likes_import` makes the same single `fetch_metadata_for_entries` call with the deduplicated uuid entries.\n- For each returned row it skips the video if `is_disliked(conn, profile_id, row[\"video_id\"], row[\"instance_domain\"])`. Otherwise it calls `record_like(conn, profile_id, \"like\", {video_id, video_uuid, instance_domain from the row}, MAX_LIKES)`. It answers 200 `{\"imported\": n}`, as today.\n- Accepted consequence (ADR-0003): a video at or over the Engine's error-count threshold is no longer imported.\n- The existing 502 on `EngineApiError` stays. Its body text may stay \"Engine resolve failed: ...\" (plan 15 rewrites it).\n\n### R6 \u2014 Client: remove the per-like resolve loop\n\n`resolve_videos_by_uuid_host` is removed from `client/backend/lib/engine_api_client.py`, and its import is dropped from `client/backend/server.py`. `resolve_video_seed` and `/internal/videos/resolve` remain, for block-add and user actions.\n\n### R7 \u2014 Cap at 50\n\n- `MAX_CLIENT_LIKES = 50` in `client/backend/server.py`.\n- It bounds like entries per request body on the likes page, the import (both via `_parse_client_likes`), and the `/recommendations` / `/videos/similar` proxy `likes` list (`likes[:MAX_CLIENT_LIKES]`).\n- Entries past the 50th are dropped, not rejected. The cap applies to the raw list before malformed entries are skipped, as today. Responses are otherwise unchanged.\n- Before editing, grep for any other reader of `MAX_CLIENT_LIKES`. Only the three sites above were found.\n\n### Acceptance criteria\n\n- A likes-page request with N \u2264 50 likes causes exactly one Engine HTTP call and one `db_lock` acquisition on the Engine.\n- A likes-import request with N likes causes exactly one Engine HTTP call and records a like for each resolvable, non-disliked, non-errored video.\n- A request with 60 like entries processes only the first 50 and returns 200 (likes page and import).\n- The likes page returns rows in submitted order, deduplicated. A like whose video is unknown to the Engine is omitted without an error.\n- `/internal/videos/metadata` with id-keyed entries returns the same rows as before. Mixed id and uuid entries in one body both resolve. A video reached by both forms appears once.\n- `/internal/dislikes/centroids` treats uuid-keyed entries exactly as today (skipped as malformed).\n- The `/recommendations` proxy forwards at most 50 likes.\n- Existing Client backend and Engine test suites pass, including `tests/active/test_profiles.py::test_importing_browser_likes_marks_each_imported_video_liked_and_no_other` and `tests/active/test_server.py`.\n\n### Testing constraints\n\n- Run `validate_tests.py` from `/home/enduser/code/PeerTube-browser/.worktrees/fix-14-batch-like-resolution` (this worktree's `project_dir`). Trees: active `tests/active`, working `tests/tmp`, archive `tests/archive`, record `tests/last_test_validation.json`, output `tests/last_test_output.txt`.\n- Run each Engine-backed test file in its own `validate_tests.py` invocation, because the Engine's per-IP rate limit is shared (memory `engine-rate-limit-single-lane-test-runs`).\n- The Engine-call-count and lock-count criteria need a counting or capturing seam: a stand-in Engine or a wrapped lock or stub server. They cannot be read off the live Engine.\n- The worktree's `whitelist.db` is a symlink to main's, so test Engines share it with other lanes. These endpoints only read from it, but the fixture Engine's startup still touches the file.\n- Engine handler code imports numpy (and `handlers.similar` pulls in faiss), so any in-process Engine unit test must run under the Engine interpreter (`conftest.ENGINE_PY`) or through the live `engine` fixture.\n\n### Baseline suite state\n\nThe pre-build baseline run exited with code 0, variant false: the suite is green before the build starts.\n\n### Consistency constraints\n\n- Match the surrounding style: stdlib HTTP handlers, `respond_json`, module-level named constants, env vars read once at startup, and a docstring on every function. No new dependency.\n- Smallest thing that works: no new endpoint, no new module beyond tests, no abstraction with one implementation.\n- Backwards compatibility is not required beyond what these requirements state.\n- Do not softwrap.\n\n### Out of scope\n\n- The single-video `/internal/videos/resolve` endpoint and the user-action and block-add paths that use it.\n- `MAX_LIKES = 100` (profile stored-likes limit) and the browser's local-likes limit.\n- Rate limiting of these endpoints (issue 02).\n- The `USE_LOCAL_LIKES_PROFILE` switch and any frontend change.\n- 502 body wording (plan 15).\n\n### Batch and merge context\n\n- Wave 2, alongside plan 13. This plan edits `client/backend/server.py` at `MAX_CLIENT_LIKES` (now line 52), the proxy trim (now line 493), `_handle_likes_import` (now lines 872-900), `_handle_user_profile_likes_from_client` (now lines 1012-1029), and the import line 32. Keep the edits local. Line numbers drift, so re-locate by function name.\n- The build merges to main when it closes. Harvest runs on main, not in the worktree.\n- `tests/last_test_validation.json` and `tests/last_test_output.txt` always conflict on merge: take main's copy and re-run `validate_tests.py --compare` on the merged tree.",
  "approved": [
    "1",
    "2",
    "3",
    "3",
    "5",
    "6",
    "9"
  ],
  "initial_solution": "### Approach\n\nThe fix sits on the Engine side of one existing endpoint. The Client side only loses code.\n\n**Engine: data layer (R2).** In `engine/server/data/metadata.py`, `fetch_metadata_by_ids` already holds the 29-column SELECT, the inner `video_embeddings` join, the left `channels` join, the error-count clause and the row-dict construction. I move that body into one private helper in the same file. The helper takes a chunk's WHERE fragment and its parameters, and returns the built row dicts. `fetch_metadata_by_ids` keeps its signature and output (a dict keyed by `video_id::instance_domain`) and becomes a thin caller that supplies its existing `OR` fragment. A new sibling function, `fetch_metadata_by_uuids`, supplies `(v.video_uuid, v.instance_domain) IN ((?, ?), ...)`, the same row-value form `fetch_seed_embeddings_for_likes` already runs on this SQLite. It is chunked at 450 pairs, which is 900 bound values plus one threshold, under SQLite's 999 limit. The helper has two callers, so it is shared code, not a single-implementation abstraction. Because a video's row dict is built in exactly one place, it is identical whichever form reached it. The uuid function orders each chunk by `v.video_id` and keeps the first row per `video_uuid::instance_domain`. That gives at most one row per uuid entry, and the lowest `video_id` when several videos share a pair. Entries are deduplicated before chunking, so one pair never spans two chunks. The match is an exact equality on both columns, as `_fetch_seed_by_uuid` did, and no embedding-blob check is added (operator-approved). The rowid-keyed `fetch_metadata` at the top of the file is not touched, which keeps the diff local.\n\n**Engine: parser and handler (R1, R3).** `internal_client_reads.py` gets a second parser beside `_parse_entries`, used only by `handle_internal_videos_metadata`. For each item it:\n- skips anything that is not a dict, or has no valid stripped `instance_domain`;\n- treats an item with a valid `video_id` as id-form, even if it also carries `video_uuid`;\n- otherwise treats an item with a valid `video_uuid` as uuid-form, and skips it if it has neither.\n\nIt deduplicates within each form on its own key, keeping the first occurrence, and returns one ordered list of tagged entries. When `entries` is not a list it returns None, so the 400 `Missing entries` path is unchanged. `_parse_entries` and `/internal/dislikes/centroids` are not edited, so centroids keeps skipping uuid-only entries.\n\nThe handler flow:\n1. An empty parse still answers 200 with no rows, before any lock.\n2. It splits the ordered list into id entries and uuid entries.\n3. Inside one `with server.db_lock:` it calls `fetch_metadata_by_ids` for the id entries and `fetch_metadata_by_uuids` for the uuid entries, skipping either call when its list is empty, with the same `video_error_threshold` for both.\n4. After releasing the lock, it walks the ordered entries, looks up each entry's row in the dict for its form, and emits the row only if its `video_id::instance_domain` has not been emitted yet.\n\nRows therefore come out in first-matching-entry order, and a video reached by both forms, or by several entries, appears once. An id-only request runs exactly the query it ran before and emits the same rows in the same order, so `_handle_user_profile_likes_get`, `_handle_block_add` and the other id callers see no change. The response shape `{\"ok\", \"count\", \"rows\"}` is unchanged.\n\n**Client (R4, R5, R6).**\n- **Likes page:** `_handle_user_profile_likes_from_client` passes the `_parse_client_likes` output (already `{video_uuid, instance_domain}` dicts) straight to one `fetch_metadata_for_entries` call and returns its rows as `likes`. The empty-parse early 200 stays, and so do the 502 path and its text. Deduplication is left to the Engine parser. R4 says that is sufficient, and it avoids a second copy of the same loop in the Client.\n- **Import:** `_handle_likes_import` makes the same single call. Its 502 text stays \"Engine resolve failed\". For each returned row it checks `is_disliked` on the row's `video_id` and `instance_domain`, and otherwise calls `record_like` with the row's `video_id`, `video_uuid` and `instance_domain`. An empty parse makes no Engine call, because `fetch_metadata_for_entries` already returns `[]` for an empty list.\n- **Removal:** `resolve_videos_by_uuid_host` is deleted from `engine_api_client.py` and from the import on `server.py:32`. `resolve_video_seed` stays.\n\n**Cap (R7).** `MAX_CLIENT_LIKES` becomes 50. A grep of the worktree, ignoring the stale `delete_me/*.bak-*` copies, confirms the only readers are the proxy trim and the two `_parse_client_likes` calls. All three keep slicing the raw list before skipping malformed items, so entries past the 50th are dropped silently.\n\n**How each requirement is met.**\n- **R1:** the new parser.\n- **R2:** the sibling uuid function over the shared SELECT and row builder.\n- **R3:** one lock hold around both lookups, then the ordered, deduplicating walk.\n- **R4 and R5:** one metadata call each.\n- **R6:** the deletion.\n- **R7:** the constant.\n\n**Same rows as before (R4).** For 50 or fewer likes that all resolve, old and new produce the same rows in the same order. The old flow deduplicated on `uuid::host` in submitted order, resolved each pair to a `video_id`, then asked metadata for those ids in that order, deduplicating on id. The new flow does the same steps inside one Engine call.\n\n**Tests.** The Engine-side checks are:\n- parser forms and dedup;\n- id-only rows unchanged;\n- mixed id and uuid entries;\n- the same video via both forms appearing once;\n- lowest `video_id` on a shared uuid pair;\n- the error threshold on the uuid form;\n- centroids ignoring uuid entries;\n- exactly one lock acquisition.\n\nThese run in-process against a temp SQLite DB with a stand-in server whose `db_lock` counts its enters. Because the handler imports numpy, they run under `conftest.ENGINE_PY` as a subprocess, following the `test_db.py` pattern.\n\nThe Client-side checks are:\n- one Engine HTTP call per likes-page or import request;\n- a 60-entry body reaching the Engine as 50;\n- the proxy forwarding at most 50;\n- unknown videos omitted;\n- disliked videos skipped on import.\n\nThese use a capturing stand-in Engine, a small stdlib HTTP server that records each request and returns canned rows. The existing `test_profiles.py` import test and `test_server.py` run against the live Engine fixture, each in its own `validate_tests.py` invocation.\n\n### Alternatives considered\n\n- **A new `/internal/videos/resolve-batch` endpoint.** Rejected by ADR-0003. The metadata endpoint already returns what both callers need, so one call replaces both the resolve loop and the separate metadata call.\n- **An opt-in uuid flag on the shared `_parse_entries`.** Rejected. A separate parser means centroids cannot be widened by a wrong default or a forgotten argument, and R1 asks for a separate parser.\n- **A uuid path inside `fetch_metadata_by_ids`, switched by a keyword.** Viable under R2. Rejected because the function name and its return key (`video_id::instance_domain`) would then lie for the uuid path, and the handler needs the uuid path keyed by `video_uuid::instance_domain`.\n- **Copying the SELECT and row dict into the new function.** Rejected. That would make a third copy in the file (`fetch_metadata` already duplicates most of it), and any drift between the two metadata copies would break the \"identical row whichever form\" guarantee without any test failing.\n- **Doing the lowest-`video_id` choice in SQL with a window function or a GROUP BY and MIN.** Rejected as more SQL for no gain. An `ORDER BY v.video_id` inside each chunk, then keeping the first row per key, is plain and deterministic.\n- **Keeping `resolve_videos_by_uuid_host` as a one-call wrapper.** Rejected by R6, and a wrapper around a single call adds nothing.\n- **Deduplicating in the Client too.** Rejected as a second copy of the Engine parser's loop. R4 states the Engine dedup alone is sufficient.\n- **Parallel resolve calls.** Rejected. It still takes the lock N times, which is the finding.\n\n### Risks and gotchas\n\n- **Lowest `video_id` among eligible rows.** The error-count clause is applied in SQL before the pick, so the choice is the lowest `video_id` among videos that pass the threshold. If the lowest-id sibling is errored, a healthy sibling is returned. The old flow could return nothing there: resolve's arbitrary `LIMIT 1` might pick the errored one, and metadata then dropped it. I take this to be what \"threshold applies to both forms\" plus \"lowest `video_id`\" means together. It only matters for duplicated `(video_uuid, instance_domain)` pairs.\n- **Lock hold length.** One hold now covers up to two queries instead of one. With the Client capping at 50, the uuid query is a single statement. A direct caller of the Engine could send a large body, but that is bounded by the Engine's body limit, and the chunking caps each statement's size.\n- **Row-value `IN`.** It needs SQLite 3.15 or newer. The Engine already relies on it in `fetch_seed_embeddings_for_likes`, so this adds no new dependency.\n- **Missing index.** No index on `(video_uuid, instance_domain)` is confirmed, so the uuid query may scan more than the id query. The old per-like resolve ran the same predicate 50 to 200 times, so one batched query is no worse. Adding an index is out of scope.\n- **Moving the id path into the helper.** Moving `fetch_metadata_by_ids`'s body touches the query every existing metadata caller uses. A regression test comparing id-keyed output before and after on a fixture DB guards against that.\n- **Shared test resources.** Test Engines share `whitelist.db` through the symlink. These endpoints only read it, but the fixture Engine's startup still touches the file.\n- **Engine rate limit.** Engine-backed test files need separate `validate_tests.py` invocations.\n- **Merge overlap.** Plan 13 edits `server.py` in wave 2, so the four edits stay local and are located by function name. `tests/last_test_validation.json` and `tests/last_test_output.txt` will conflict on merge: take main's copy and re-run `--compare`.\n\n### Tradeoffs the operator accepts\n\n- Likes past the 50th in a request are dropped silently, not rejected.\n- Import no longer records videos at or over the Engine's error-count threshold (ADR-0003).\n- Videos with an empty or mismatched embedding blob now appear on the likes page and are imported, where resolve used to drop them (already approved).\n- When several videos share a uuid and host, the lowest-`video_id` eligible one is chosen.\n- Deduplication of browser likes happens only on the Engine.",
  "conflicts": "none",
  "impacts": "\n<impacts>\n<impact path=\"engine/server/data/metadata.py\" element=\"fetch_metadata_by_ids (lines 110-205): body moves into a new private helper\">\n**What changes.** The helper takes over:\n- the 29-column SELECT (lines 133-162), which is `FROM video_embeddings e JOIN videos v ... LEFT JOIN channels c`;\n- the optional `error_count` clause (lines 127-130), added only when `error_threshold > 0`, with its parameter appended after the pair parameters;\n- the row-dict build (lines 174-204).\n\n`fetch_metadata_by_ids` keeps its signature `(conn, entries, error_threshold=None) -> dict[str, dict]` and its `if not entries: return {}` early return. It still builds its 450-entry chunks through `_chunk` (line 105), its `OR` of `(v.video_id = ? AND v.instance_domain = ?)`, and its params from `entry.get(\"video_id\")` and `entry.get(\"instance_domain\") or \"\"`. Its result is still keyed on `like_key(row)` (`video_id::instance_domain`, `engine/server/api/recommendations/keys.py:8`).\n\n**What depends on it.**\n- `handle_internal_videos_metadata` (`engine/server/api/handlers/internal_client_reads.py:113`).\n- `similarity_candidates._build_rows` (`engine/server/data/similarity_candidates.py:170` and `:175`), which feeds similar and up-next rows. The plan's caller list does not name it (see its own entry).\n\n**Regression risk: medium.**\n- The threshold parameter must stay last. It must be appended once per chunk, not once per call, or chunks after the first get the wrong parameter count.\n- The row dict must keep exactly the same 29 keys. The uuid path keys on `video_uuid`/`instance_domain`, and `record_like` on import reads `video_id`/`video_uuid`/`instance_domain`.\n- The id path keys the helper's output with `like_key`, which accepts dicts and `sqlite3.Row` (keys.py:10-15).\n- If the helper takes an ORDER BY or sorts for the uuid caller, the id path's result is still a dict, so ordering cannot change what id callers see. The helper's signature must let the uuid caller order by `v.video_id`, or the uuid caller must sort in Python.\n- Nothing in `tests/active` exercises this function directly today. It is covered only indirectly by the live-Engine tests (`test_server.py`, `test_blocks.py`, `test_similar.py`, `test_profiles.py`).\n</impact>\n<impact path=\"engine/server/data/metadata.py\" element=\"new fetch_metadata_by_uuids (sibling function)\">\n**What changes.**\n- A new public function, `(conn, entries, error_threshold=None)`, in the style of its sibling, with a docstring (every function in the file has one).\n- It deduplicates `(video_uuid, instance_domain)` pairs, chunks them at 450 with `_chunk`, and runs `WHERE (v.video_uuid, v.instance_domain) IN ((?, ?), ...)` through the shared helper, ordered by `v.video_id`. The row-value form is the one already used at `engine/server/data/embeddings.py:228`.\n- It keeps the first row per `video_uuid::instance_domain`, keyed from the row's own values, and returns that dict.\n\n**What depends on it.** Only the new handler path.\n\n**Regression risk: low for existing callers (new code), medium for correctness.**\n- The match is a binary TEXT comparison, so it is exact and case-sensitive, like `_fetch_seed_by_uuid` (embeddings.py:134-139).\n- The lowest `video_id` is chosen among rows that pass the error filter. This is the plan's stated interpretation.\n- The inner join cannot fan out if `video_embeddings` is keyed on `(video_id, instance_domain)`. I did not re-open the schema DDL in this pass; the previous record cites `build-video-embeddings.py:73`.\n- 450 pairs is 900 bound values plus 1 threshold, which stays under 999.\n- An empty `entries` must return `{}` without a query, mirroring line 116.\n- **The plan's \"Missing index\" risk is wrong.** `CREATE INDEX IF NOT EXISTS idx_videos_uuid_instance ON videos (video_uuid, instance_domain)` exists at `engine/server/data/videos.py:21-22` and is created on every Engine start (`engine/server/api/server.py:337`, `ensure_video_indexes(db)`). A temp-DB unit test will not have the index unless it calls `ensure_video_indexes`. That does not affect correctness.\n</impact>\n<impact path=\"engine/server/data/metadata.py\" element=\"fetch_metadata (rowid-keyed, lines 11-102), _chunk (105-107), module imports (1-8)\">\n**What changes.** Nothing. `fetch_metadata` stays a separate copy of most of the SELECT and row dict, and `_chunk` is reused.\n\n**What depends on it.** `fetch_metadata` is used by similar.py, ann.py, random_videos.py and search.py; the previous record lists these and I did not re-check them.\n\n**Regression risk: none if the diff stays out of lines 11-102.**\n\n**Test-design note.** The module imports only `sqlite3`, `typing` and `recommendations.keys`, and `recommendations/__init__.py` imports only `typing`. So `data.metadata` can be imported in the pytest interpreter in-process, the way `tests/active/test_internal_events.py:25-36` imports `data.*`. The data-layer tests (id output unchanged, uuid lookup, lowest `video_id`, threshold) do not need an `ENGINE_PY` subprocess. Only the handler does, because `internal_client_reads` imports numpy.\n</impact>\n<impact path=\"engine/server/data/similarity_candidates.py\" element=\"_build_rows (lines 155-212), direct caller of fetch_metadata_by_ids\">\n**What changes.** No edit.\n\n**Why it matters.** It calls `fetch_metadata_by_ids` both with and without `server.db_lock` (lines 169-179), looks rows up with `metadata.get(like_key(entry))` (line 195), and compares `like_key(meta)` with the source key (line 198). Its entries come from the ANN index or cache and can carry extra keys or a `None` instance_domain. The refactored function must go on reading only `entry.get(\"video_id\")` and `entry.get(\"instance_domain\") or \"\"`.\n\n**Regression risk: medium, and the plan's caller list does not name it.** A drift in keying, row content or per-chunk parameters would silently empty or alter similar and up-next pages. It is covered only indirectly, by the live-Engine `tests/active/test_similar.py`.\n</impact>\n<impact path=\"engine/server/api/handlers/internal_client_reads.py\" element=\"new metadata entry parser beside _parse_entries (line 20)\">\n**What changes.** A second parser, used only by `handle_internal_videos_metadata`. It mirrors `_parse_entries`:\n- `isinstance(body, dict)` guard;\n- returns None when `entries` is not a list;\n- skips non-dict items and items without a non-empty stripped string `instance_domain`.\n\nBeyond that:\n- A valid `video_id` means id form, even when a uuid is also present. Otherwise a valid `video_uuid` means uuid form. Anything else is skipped.\n- Duplicates are removed per form (id form on `_like_key`, uuid form on `video_uuid::instance_domain`), keeping the first.\n- It returns one ordered, tagged list. It needs a docstring.\n\n**What depends on it.** `handle_internal_videos_metadata` only.\n\n**Regression risk: medium.**\n- The id-form entries handed to `fetch_metadata_by_ids` must be the same stripped `{video_id, instance_domain}` dicts `_parse_entries` builds.\n- **Behaviour change for id callers.** An item with an empty or whitespace `video_id` but a valid `video_uuid` was skipped before. Now it resolves through the uuid form.\n  - `_handle_user_profile_likes_get` sends `fetch_recent_likes` rows, which carry `video_id`, `video_uuid`, `instance_domain` and `updated_at` (`client/backend/lib/users_store.py:126-141`).\n  - `record_like` stores `str(video.get(\"video_id\") or \"\")` (users_store.py:90), so a stored like with an empty id would now appear.\n  - Every current writer passes a canonical non-empty id: server.py:775 checks it, and import uses Engine rows. No such rows are expected.\n</impact>\n<impact path=\"engine/server/api/handlers/internal_client_reads.py\" element=\"handle_internal_videos_metadata (lines 95-126)\">\n**What changes.**\n- The new parser replaces the `_parse_entries` call at line 103. The 400 `Missing entries` (104-106) and the empty 200 before any lock (108-110) stay.\n- The entries split into an id list and a uuid list.\n- One `with server.db_lock:` calls `fetch_metadata_by_ids` and/or `fetch_metadata_by_uuids`, skipping an empty list, both with `error_threshold=getattr(server, \"video_error_threshold\", None)`.\n- After the lock is released, an ordered walk looks each entry up in its form's own dict and emits the row once, keyed on the row's `video_id::instance_domain`.\n- The response `{\"ok\", \"count\", \"rows\"}` does not change.\n- The docstring (\"canonical (video_id, instance_domain) entries\") must be updated.\n\n**What depends on it.**\n- The route, dispatched from `engine/server/api/handlers/similar.py:402-404` behind `_bridge_authorized` (line 394).\n- Client callers through `fetch_metadata_for_entries`: `_handle_user_profile_likes_get` (server.py:1006), `_handle_block_add` (server.py:947), and after this change `_handle_user_profile_likes_from_client` and `_handle_likes_import`.\n\n**Regression risk: medium-high.**\n- Id-only bodies must give the same rows in the same order: today's loop (lines 119-123) emits in entry order.\n- Cross-form dedup must key on the returned row, not the entry, or a video reached by both forms appears twice.\n- The id dict and the uuid dict must stay separate, because both key formats are `x::y` strings and could collide.\n- `db_lock` is a plain lock, so it must be taken once in the handler and never inside the data functions.\n- **Statement deadline.** `do_POST` (`similar.py:355-363`) runs the whole request, lock wait and both queries included, under one `statement_deadline`. A breach gives 503 `Query time limit exceeded`, which the Client sees as `EngineApiError` and answers with 502. Before, each resolve had its own budget. With 50 or fewer pairs on an index this is negligible.\n</impact>\n<impact path=\"engine/server/api/handlers/internal_client_reads.py\" element=\"_like_key (line 15), _parse_entries (20-48), handle_internal_dislike_centroids (129-158), handle_internal_video_resolve (51-92)\">\n**What changes.** Nothing (R1 and out of scope). Centroids keeps `_parse_entries`, so uuid-only entries there are skipped as malformed and do not count toward `DISLIKE_MAX_ENTRIES` (line 141). Resolve stays for `_handle_user_action` (server.py:758) and `_handle_block_add` (server.py:946).\n\n**Regression risk: low.** The risk is an accidental edit while the sibling parser is added. The centroids-ignores-uuid test guards it, and `tests/active/test_dislike_profile.py` covers centroids.\n</impact>\n<impact path=\"engine/server/api/handlers/internal_client_reads.py\" element=\"module imports (lines 4-12)\">\n**What changes.** Line 9 becomes `from data.metadata import fetch_metadata_by_ids, fetch_metadata_by_uuids`.\n\n**What depends on it.** `handlers/similar.py` imports this module at load time, so the whole Engine does. The module imports numpy (line 6), so a handler test must run under `conftest.ENGINE_PY`.\n\n**Regression risk: high impact, low probability.** A bad import name stops the Engine at startup, and every live-Engine test then fails in the `engine` fixture (`tests/active/conftest.py:101-137`).\n</impact>\n<impact path=\"engine/server/api/handlers/similar.py\" element=\"do_POST (355-363), _dispatch_post (390-410), module docstring line 11\">\n**What changes.** No edit. The route and its bridge auth are unchanged. The docstring \"internal Client metadata batch lookup\" stays accurate.\n\n**Why it matters.** This is where the single per-request statement deadline covers the new combined lookup (see the handler entry).\n\n**Regression risk: low.**\n</impact>\n<impact path=\"engine/server/api/handlers/__init__.py\" element=\"module docstring line 6\">\n**What changes.** Nothing required. \"internal_client_reads: internal read endpoints used by Client service\" stays true.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"engine/server/data/embeddings.py\" element=\"fetch_seed_embeddings_for_likes (191+), fetch_seed_embedding / _fetch_seed_by_uuid / _seed_from_row (104-188)\">\n**What changes.** Nothing.\n- `fetch_seed_embeddings_for_likes` is the precedent for the row-value `IN` (line 228). It is unchunked; the new function adds chunking.\n- `_fetch_seed_by_uuid` stays for `/internal/videos/resolve`.\n\n**Accepted differences from the old resolve path**, which the tests and the docs should state:\n- `_seed_from_row` dropped rows with an empty or mismatched embedding blob (line 178). The metadata path has no such check.\n- Resolve had no error filter and an arbitrary `LIMIT 1` (line 140). The new path is error-filtered and deterministic, choosing the lowest `video_id`.\n\n**Regression risk: none to this file.**\n</impact>\n<impact path=\"engine/server/data/videos.py\" element=\"ensure_video_indexes: idx_videos_uuid_instance (lines 21-22)\">\n**What changes.** Nothing.\n\n**Why it matters.** It disproves the plan's \"No index on (video_uuid, instance_domain) is confirmed\" risk. The uuid batch query can use this index. The plan's risk note should be corrected.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"engine/server/api/http_utils.py\" element=\"read_json_body 1,000,000-byte cap (lines 46-52)\">\n**What changes.** Nothing.\n\n**Why it matters.** It is the only bound on how many entries a direct bridge caller can put in one metadata body. A large body means several 450-pair statements under one lock hold, which is the same exposure the id path already has.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"engine/server/api/recommendations/keys.py\" element=\"like_key (line 8)\">\n**What changes.** Nothing.\n\n**Why it matters.** It keys the refactored id path and will likely key the handler's cross-form dedup. Its output format matches `_like_key` in internal_client_reads.py:15.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"client/backend/lib/engine_api_client.py\" element=\"resolve_videos_by_uuid_host (lines 136-166): deleted\">\n**What changes.** Removed (R6).\n\n**What depends on it.** Outside `delete_me/` and `docs/`, three sites use it: the import at `client/backend/server.py:32`, the call at `:888` (`_handle_likes_import`), and the call at `:1024` (`_handle_user_profile_likes_from_client`). No test references it.\n\n**Regression risk: low.** A missed site is an ImportError when `server.py` is imported, which `tests/active/conftest.py:39` surfaces across the whole suite. It is also named in the historical `docs/project/security-audit/run-1/REPORT.md:277` and `findings.json`, which must not be edited.\n</impact>\n<impact path=\"client/backend/lib/engine_api_client.py\" element=\"fetch_metadata_for_entries (lines 92-109), resolve_video_seed (66-89), _post_json (32-63)\">\n**What changes.**\n- No logic change. `fetch_metadata_for_entries` now also carries `{video_uuid, instance_domain}` entries. Its docstring (\"canonical video identity entries\") could mention the uuid form.\n- It returns `[]` with no HTTP call for an empty list (line 97), which the import path relies on.\n- It raises `EngineApiError` on a non-200 status or a bad payload.\n- `_post_json` has a 6 s timeout (line 32), which now bounds the whole likes page and the whole import, not each resolve.\n- `resolve_video_seed` stays.\n\n**Regression risk: low.**\n</impact>\n<impact path=\"client/backend/server.py\" element=\"engine_api_client import (lines 30-32)\">\n**What changes.** `resolve_videos_by_uuid_host` is dropped from the import. `fetch_metadata_for_entries` and `resolve_video_seed` stay.\n\n**Regression risk: low.** It could conflict on merge with plan 13 in the same block, so locate the edit by name.\n</impact>\n<impact path=\"client/backend/server.py\" element=\"MAX_CLIENT_LIKES = 200 \u2192 50 (line 52)\">\n**What changes.** The value.\n\n**Readers,** found by grep outside `delete_me/` and `docs/`:\n- line 493, the proxy trim;\n- line 886, `_handle_likes_import`;\n- line 1019, `_handle_user_profile_likes_from_client`.\n\nNo test reads it.\n\n**Context.** It sits beside `MAX_LIKES = 100` (line 51, out of scope) and `ENGINE_FEED_LIKES_MAX = 5` (line 55). It matches the browser's `MAX_LIKES = 50` (`client/frontend/src/data/local-likes.ts:25`) and ADR-0003.\n\n**Regression risk: low.** No `tests/active` test posts more than 50 likes; the import test posts 3.\n</impact>\n<impact path=\"client/backend/server.py\" element=\"/recommendations and /videos/similar POST proxy likes trim (lines 487-503)\">\n**What changes.** No code edit. `likes[:MAX_CLIENT_LIKES]` now cuts at 50 before malformed entries are skipped.\n\n**Context.**\n- A keyed request replaces the likes with at most 5 stored ones (lines 535-541).\n- The Engine answers 400 above `DEFAULT_CLIENT_LIKES_MAX` = 5 on both POST routes (`engine/server/README.md:24`). So a keyless body of 6-50 likes still gets the Engine's 400 forwarded.\n- The \"proxy forwards at most 50\" test therefore needs a capturing stand-in Engine, not the live one.\n\n**Regression risk: low.**\n</impact>\n<impact path=\"client/backend/server.py\" element=\"_parse_client_likes (lines 1105-1121)\">\n**What changes.** No edit. It cuts to `raw[:max_items]` before validation, returns stripped `{video_uuid, instance_domain}` dicts, and does not deduplicate. Its output keys are exactly the Engine parser's uuid form, and it now feeds `fetch_metadata_for_entries` directly.\n\nIt is distinct from the Engine's `handlers/similar.py:132` `_parse_client_likes`, which `tests/active/test_similar.py:259` patches.\n\n**Regression risk: low.** If its key names changed, the Engine would skip every entry and return an empty page without any error.\n</impact>\n<impact path=\"client/backend/server.py\" element=\"_handle_likes_import (lines 872-900)\">\n**What changes.**\n- Line 888 becomes one `fetch_metadata_for_entries(self.server.engine_ingest_base, likes)` call. The 502 text `Engine resolve failed: ...` (line 890) stays; plan 15 rewrites it.\n- The loop over the rows keeps `is_disliked(conn, profile_id, row[\"video_id\"], row[\"instance_domain\"])` and `record_like(conn, profile_id, \"like\", {video_id, video_uuid, instance_domain}, MAX_LIKES)` inside `with conn:`. `record_like` commits on its own (users_store.py:117), as it does today.\n- The response stays `{\"imported\": n}`.\n- The recording order is the Engine's first-match order, which equals submitted order. That keeps `updated_at` recency and the `MAX_LIKES` trim the same as today.\n\n**Behaviour changes (accepted):**\n- Videos at or over the error threshold are not imported.\n- Videos with a bad embedding blob are now imported.\n- On a uuid collision, the lowest `video_id` wins.\n\n**Regression risk: medium.**\n- It is covered by `tests/active/test_profiles.py:245` (live Engine). That test's dataset query already filters `error_count = 0` and joins embeddings (lines 225-230), so it should stay green.\n- Frontend coupling: `importLocalLikes` clears all local likes after any 2xx (`client/frontend/src/data/reactions.ts:81`). Likes past the 50th, unknown ones and errored ones are therefore lost. The browser already caps at 50.\n</impact>\n<impact path=\"client/backend/server.py\" element=\"_handle_user_profile_likes_from_client (lines 1012-1029)\">\n**What changes.**\n- Lines 1024-1025 become one `fetch_metadata_for_entries` call.\n- The empty-parse 200 (1020-1022), the 502 `Engine metadata failed: ...` (1027) and `{\"likes\": rows, \"updatedAt\"}` stay.\n- The docstring is a placeholder (\"Handle handle user profile likes from client.\") and could now state the one-call behaviour.\n\n**What depends on it.** The keyless likes page: `client/frontend/src/data/user-profile.ts:20-40` posts `{likes: [{uuid, host}]}` and renders `likes` in response order.\n\n**Regression risk: medium.** Order and dedup now rest entirely on the Engine's ordered walk. No existing test covers this POST route (a grep of `tests/active` finds no POST to `/api/user-profile/likes`). The planned stand-in-Engine tests fill that gap.\n</impact>\n<impact path=\"client/backend/server.py\" element=\"_handle_user_profile_likes_get (995-1010) and _handle_block_add (927-963): id-form callers\">\n**What changes.** No edit.\n- The GET sends `fetch_recent_likes` rows, which carry both `video_id` and `video_uuid`. With a non-empty id they are id form, so the rows and their order are unchanged.\n- Block-add sends a single `{video_id, instance_domain}`.\n\n**Tests.** `tests/active/test_server.py:94`, `test_blocks.py`, and `test_profiles.py` through reads.\n\n**Regression risk: low-medium.** See the parser entry for the empty-id-plus-uuid edge case.\n</impact>\n<impact path=\"client/backend/server.py\" element=\"_handle_user_action / _store_reaction (lines 730-870)\">\n**What changes.** Nothing. It still uses `resolve_video_seed` (line 758). Listed to confirm that `resolve_video_seed` must not be removed together with the batch function.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"client/backend/lib/users_store.py\" element=\"record_like (79-117), fetch_recent_likes (120-142)\">\n**What changes.** Nothing.\n- `record_like` reads only `video_id`, `instance_domain` and `video_uuid`, so a full metadata row or a three-key dict built from it both work.\n- `fetch_recent_likes` produces the id-form GET body.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"client/backend/lib/dislikes.py\" element=\"is_disliked\">\n**What changes.** Nothing. It is now called with the metadata row's `video_id` and `instance_domain` rather than the resolved entry's. The values are the same.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"client/frontend/src/data/local-likes.ts\" element=\"MAX_LIKES = 50 (line 25)\">\n**What changes.** Nothing; the frontend is out of scope. It is the bound ADR-0003 aligns to. The built bundle `client/frontend/dist/assets/key-rejected-*.js` carries `S=50`.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"client/frontend/src/data/reactions.ts\" element=\"importLocalLikes (lines 65-83)\">\n**What changes.** Nothing. It posts every local like and clears local storage on success (line 81), so likes the server drops or cannot resolve are cleared too.\n\n**Regression risk: low.**\n</impact>\n<impact path=\"client/frontend/src/data/user-profile.ts\" element=\"fetchUserProfileLikes keyless branch (lines 20-40)\">\n**What changes.** Nothing. It depends on the response order matching the submitted order.\n\n**Regression risk: low.**\n</impact>\n<impact path=\"tests/active/test_profiles.py\" element=\"test_importing_browser_likes_marks_each_imported_video_liked_and_no_other (line 245) and _embedded_videos (225-232)\">\n**What changes.** No edit expected. It must stay green, running against the live Engine in its own `validate_tests.py` invocation.\n\n**Regression risk: low.**\n</impact>\n<impact path=\"tests/active/test_server.py\" element=\"test_a_keyed_request_s_500_entry_exclude... (line 86; GET likes at line 94)\">\n**What changes.** No edit. It exercises the id-form metadata path end to end, and it is the existing check that id callers are unchanged. It runs in its own invocation.\n\n**Regression risk: low.**\n</impact>\n<impact path=\"tests/active/test_dislike_profile.py\" element=\"/internal/dislikes/centroids tests\">\n**What changes.** No edit. It guards `_parse_entries` and centroids. The new centroids-ignores-uuid check can live here or in the new Engine test file.\n\n**Regression risk: low.**\n</impact>\n<impact path=\"tests/active/test_blocks.py\" element=\"block-add tests\">\n**What changes.** No edit. It exercises resolve plus a single-entry id-form metadata call against the live Engine.\n\n**Regression risk: low.**\n</impact>\n<impact path=\"tests/active/conftest.py\" element=\"ENGINE_PY (30), client_backend (69-89), _engine_client (156-176), engine fixture (101-137)\">\n**What changes.** Probably no edit.\n- The `ClientBackendServer(..., engine_base, ...)` construction is the seam for pointing a Client at a capturing stand-in Engine.\n- `ClientBackend` exposes only `base` and `db_path`, so the new Client tests must build their own server. Alternatively a fixture can be added, but a fixture here is shared by every file.\n\n**Regression risk: low.**\n</impact>\n<impact path=\"tests/active/test_internal_events.py\" element=\"in-process data imports (25-36) and ENGINE_PY -c child (42-60, 173)\">\n**What changes.** Nothing. It is the right precedent for the new tests:\n- in-process `data.*` imports with `engine/server` and `engine/server/api` on `sys.path`, for the metadata data functions;\n- an `ENGINE_PY -c` child with `cwd=API_DIR` for the numpy-importing handler, patching `read_json_body`/`respond_json` on the handler module and handing it a stand-in server.\n\n**Correction to the plan.** The plan cites `test_db.py`, but `test_db.py:81` runs its child with `sys.executable`, not `ENGINE_PY`. `tests/active/test_similar.py:288-289` is the other `ENGINE_PY` child precedent.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"tests/active/test_db.py\" element=\"cited by the plan as the test pattern\">\n**What changes.** Nothing. It is listed only because the plan names it as the pattern, and it is the wrong one: it uses `sys.executable` and imports only `data.db`.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"tests/tmp/ (new Engine and Client test files)\">\n**What changes.** New tests.\n\n**Engine data layer, in-process:**\n- id output unchanged;\n- the uuid lookup;\n- lowest `video_id`;\n- the threshold on the uuid form.\n\n**Engine handler, `ENGINE_PY` child:**\n- parser forms and dedup;\n- mixed forms;\n- the same video once;\n- one lock enter, using a counting `db_lock`;\n- centroids ignores uuid.\n\n**Client, stdlib stand-in Engine:**\n- one call per request;\n- 60 entries reach the Engine as 50;\n- the proxy forwards at most 50;\n- unknown videos are omitted;\n- disliked videos are skipped on import.\n\n**Risks.**\n- The temp schema must include `videos` with every selected column plus `error_count` and `video_uuid`, `video_embeddings` with `embedding_dim` and `model_name`, and `channels` with `display_name` and `avatar_url`.\n- `video_embeddings` should have its real `(video_id, instance_domain)` primary key.\n- The stand-in Engine must answer `/internal/videos/metadata` and record the bodies.\n</impact>\n<impact path=\"tests/last_test_validation.json\" element=\"tracked test record (and tests/last_test_output.txt)\">\n**What changes.** Regenerated by the runs. It conflicts on merge: take main's copy and re-run `--compare`.\n\n**Regression risk: merge-process only.**\n</impact>\n<impact path=\"delete_me/ (server.py.bak-* and similar stale copies)\">\n**What changes.** Nothing. These files match greps for `resolve_videos_by_uuid_host` and `MAX_CLIENT_LIKES`, but they are not imported. Do not edit them and do not count them as readers.\n\n**Regression risk: none.**\n</impact>\n</impacts>\n",
  "docs_checklist": "- [x] `client/README.md` - updated: I added the 50-entry cap and the single Engine metadata call to the two browser-likes endpoints in `client/README.md`, and the cap to the feed-proxy `likes` note.\n- [x] `engine/server/README.md` - updated: `engine/server/README.md`: the `/internal/videos/metadata` entry now describes both entry forms and how they are answered, and the `/internal/dislikes/centroids` entry says it takes id-form entries only.\n- [x] `docs/project/adr/0003-metadata-endpoint-accepts-uuid-entries.md` - updated: I added two bullets to the ADR-0003 Consequences for the two approved differences from the old resolve path: the lowest-`video_id` tie-break, and no embedding-blob check.\n- [x] `docs/project/issues/03-batch-like-resolution.md` - updated: Issue 03 is now `bug, complete` and has a delivery comment, but I couldn't move it to `issues/archive/` because I have no delete or move tool.\n- [x] `docs/project/plans/14-batch-like-resolution.md` - updated: No edit: plan 14 needs no text correction, and archiving it is a harvest-time move on main.\n- [x] `docs/project/plans/16-14-batch-like-resolution.md` - updated: I made the four listed corrections to the plan text of `docs/project/plans/16-14-batch-like-resolution.md` and checked each against the worktree code.",
  "docs": [
    {
      "path": "client/README.md",
      "note": "- **Line 15** (`POST /api/profile/likes/import`): add that at most 50 likes per body are read and the rest are dropped. A video the Engine does not know, or holds at or over its error threshold, is not imported (ADR-0003).\n- **Line 22** (`POST /api/user-profile/likes`): add that it resolves up to 50 browser likes in one Engine metadata call, in submitted order, deduplicated, and that unknown videos are omitted.\n- **Lines 30 and 37-39** stay accurate: `/internal/videos/resolve` is still used by user actions and block-add."
    },
    {
      "path": "engine/server/README.md",
      "note": "Line 11 (`/internal/videos/metadata`): entries may be `{video_id, instance_domain}` or `{video_uuid, instance_domain}`, mixed. An entry with both uses `video_id`. All entries are answered under one lock hold, one row per video, in first-matching-entry order. Where several videos share a uuid and host, the lowest `video_id` wins. Line 10 (resolve) is unchanged."
    },
    {
      "path": "docs/project/adr/0003-metadata-endpoint-accepts-uuid-entries.md",
      "note": "The decision is unchanged. Optionally add two consequences under Consequences: the lowest-`video_id` rule for a shared `(video_uuid, instance_domain)`, and that videos with an empty or mismatched embedding blob now appear on the likes page and are imported."
    },
    {
      "path": "docs/project/issues/03-batch-like-resolution.md",
      "note": "At harvest on main: set `Status: bug, complete`, add a delivery comment, and move the file to `docs/project/issues/archive/` (per `docs/project/triage-labels.md`)."
    },
    {
      "path": "docs/project/plans/14-batch-like-resolution.md",
      "note": "At harvest on main, archive it together with `16-14-batch-like-resolution.md` and its record, in `docs/project/plans/archive/`. Correct the plan text in `16-14-batch-like-resolution.md` in two places:\n- **Missing index:** `idx_videos_uuid_instance` exists (`engine/server/data/videos.py:21`).\n- **Test pattern:** the handler tests follow `test_internal_events.py`/`test_similar.py` (`ENGINE_PY` child), not `test_db.py`, and the data-layer tests can run in-process."
    }
  ],
  "reassessments": 2,
  "draft": "## Draft implementation: batch like resolution (plan 14, issue 03)\n\nThis draft converged on the first pass against the plan and R1 to R7. The pass-by-pass check is at the end. All paths are relative to the worktree `/home/enduser/code/PeerTube-browser/.worktrees/fix-14-batch-like-resolution`.\n\n### Module map\n\n| File | Change |\n|---|---|\n| `engine/server/data/metadata.py` | New private `_select_metadata` (the SELECT, the joins, the error clause, the row dict). `fetch_metadata_by_ids` becomes a thin caller of it. New `fetch_metadata_by_uuids` and private `_uuid_key`. `fetch_metadata` (lines 11-102) and `_chunk` are untouched. |\n| `engine/server/api/handlers/internal_client_reads.py` | Import line 9 widened. New `_uuid_key` and `_parse_metadata_entries`. `handle_internal_videos_metadata` rewritten. `_parse_entries`, centroids and resolve are untouched. |\n| `client/backend/lib/engine_api_client.py` | `resolve_videos_by_uuid_host` deleted. The `fetch_metadata_for_entries` docstring now names both entry forms. |\n| `client/backend/server.py` | Import (lines 30-32), `MAX_CLIENT_LIKES = 50`, `_handle_likes_import`, `_handle_user_profile_likes_from_client`. The proxy trim at line 493 is unchanged in code. |\n| `tests/tmp/test_metadata_uuid_entries.py` | New. Tests for the Engine data layer (in-process) and the handler (an `ENGINE_PY` child). |\n| `tests/tmp/test_client_like_batching.py` | New. Client tests against a capturing stand-in Engine. |\n\nNo new dependency, endpoint or module outside the tests.\n\n---\n\n### 1. `engine/server/data/metadata.py`\n\n**`_select_metadata(conn, where, params, error_threshold) -> list[dict[str, Any]]`**\n- It is shared by exactly two callers, so it is not a single-implementation abstraction.\n- **Invariant:** it builds a fresh parameter list per call, so the threshold is appended once per chunk and always last.\n- **Invariant:** it builds the row dict in one place only, so a video's row is identical whichever form reached it.\n- It never takes `db_lock`.\n\n```python\ndef _select_metadata(\n    conn: sqlite3.Connection,\n    where: str,\n    params: list[Any],\n    error_threshold: int | None,\n) -> list[dict[str, Any]]:\n    \"\"\"Run the metadata SELECT for one chunk's WHERE fragment and return the built row dicts.\"\"\"\n    query_params = list(params)\n    error_clause = \"\"\n    if error_threshold is not None and error_threshold > 0:\n        error_clause = \"AND (v.error_count IS NULL OR v.error_count < ?)\"\n        query_params.append(error_threshold)\n    rows = conn.execute(\n        f\"\"\"\n        SELECT\n          v.video_id,\n          ... (lines 134-162 verbatim, 29 columns) ...\n          e.model_name\n        FROM video_embeddings e\n        JOIN videos v\n          ON v.video_id = e.video_id AND v.instance_domain = e.instance_domain\n        LEFT JOIN channels c\n          ON c.channel_id = v.channel_id AND c.instance_domain = v.instance_domain\n        WHERE {where}\n          {error_clause}\n        \"\"\",\n        query_params,\n    ).fetchall()\n    return [\n        {\n            \"video_id\": row[\"video_id\"],\n            ... (lines 175-203 verbatim, 29 keys) ...\n            \"model_name\": row[\"model_name\"],\n        }\n        for row in rows\n    ]\n```\n\nThe WHERE fragment is wrapped as `WHERE ({where})`, in parentheses, so that the `AND` error clause binds to the whole `OR` chain. In today's SQL, `WHERE a OR b AND (err)` binds `AND` tighter than `OR`. That means the existing id query applies the threshold only to the last pair of each chunk.\n\nThis is a live pre-existing bug on the id path, and it would change R3's \"id callers see exactly the rows they saw before\". **See \"Open item A\" below: the draft does not silently pick one side.**\n\n**`fetch_metadata_by_ids`**\n\nThe signature, the early return, the 450-entry chunks, and the params from `entry.get(\"video_id\")` / `entry.get(\"instance_domain\") or \"\"` all stay the same.\n\n```python\ndef fetch_metadata_by_ids(\n    conn: sqlite3.Connection,\n    entries: list[dict[str, Any]],\n    error_threshold: int | None = None,\n) -> dict[str, dict[str, Any]]:\n    \"\"\"Fetch video metadata for (video_id, instance_domain) pairs.\"\"\"\n    if not entries:\n        return {}\n    result: dict[str, dict[str, Any]] = {}\n    for batch in _chunk(entries, 450):\n        conditions = \" OR \".join([\"(v.video_id = ? AND v.instance_domain = ?)\"] * len(batch))\n        params: list[Any] = []\n        for entry in batch:\n            params.append(entry.get(\"video_id\"))\n            params.append(entry.get(\"instance_domain\") or \"\")\n        for row in _select_metadata(conn, conditions, params, error_threshold):\n            result[like_key(row)] = row\n    return result\n```\n\n`similarity_candidates._build_rows` keeps working unchanged. It reads the same keys and gets the same dicts, keyed by `like_key`.\n\n**`fetch_metadata_by_uuids`**\n\n```python\ndef _uuid_key(entry: dict[str, Any]) -> str:\n    \"\"\"Handle uuid key.\"\"\"\n    return f\"{entry.get('video_uuid') or ''}::{entry.get('instance_domain') or ''}\"\n\n\ndef fetch_metadata_by_uuids(\n    conn: sqlite3.Connection,\n    entries: list[dict[str, Any]],\n    error_threshold: int | None = None,\n) -> dict[str, dict[str, Any]]:\n    \"\"\"Fetch video metadata for (video_uuid, instance_domain) pairs, one row per pair.\n\n    The match is exact on both columns. Where several videos share a pair, the one with the lowest\n    video_id among those under the error threshold is kept.\n    \"\"\"\n    pairs: dict[str, tuple[str, str]] = {}\n    for entry in entries:\n        pair = (str(entry.get(\"video_uuid\") or \"\"), str(entry.get(\"instance_domain\") or \"\"))\n        pairs.setdefault(_uuid_key({\"video_uuid\": pair[0], \"instance_domain\": pair[1]}), pair)\n    if not pairs:\n        return {}\n    result: dict[str, dict[str, Any]] = {}\n    for batch in _chunk(list(pairs.values()), 450):\n        placeholders = \", \".join([\"(?, ?)\"] * len(batch))\n        params = [value for pair in batch for value in pair]\n        for row in _select_metadata(conn, f\"(v.video_uuid, v.instance_domain) IN ({placeholders})\", params, error_threshold):\n            key = _uuid_key(row)\n            if key not in result or row[\"video_id\"] < result[key][\"video_id\"]:\n                result[key] = row\n    return result\n```\n\n**Decision: pick the lowest id in Python rather than with `ORDER BY`.** The impact entry allows it (\"or the uuid caller must sort in Python\").\n- The helper then needs no ordering parameter, and the id query is not given a useless sort.\n- The pick does not depend on row order or on chunking.\n- SQLite's BINARY collation compares UTF-8 bytes. Byte order equals code-point order, which is how Python orders `str`, so \"lowest `video_id`\" means the same in both.\n\n**Other invariants:**\n- 450 pairs is 900 values plus 1 threshold, under 999.\n- `video_embeddings` has `PRIMARY KEY (video_id, instance_domain)` (`sync-whitelist.py:391`), so the inner join cannot fan out.\n- The query can use `idx_videos_uuid_instance` (`data/videos.py:21`).\n\n---\n\n### 2. `engine/server/api/handlers/internal_client_reads.py`\n\nLine 9:\n```python\nfrom data.metadata import fetch_metadata_by_ids, fetch_metadata_by_uuids\n```\n\n**New helpers beside `_like_key` and `_parse_entries`.** `_uuid_key` duplicates the private one in `metadata.py` on purpose. The file already mirrors `recommendations.keys.like_key` with its own `_like_key`, and the settled import line names only the two fetch functions. A drift between the two copies fails the mixed-forms test.\n\n```python\ndef _uuid_key(entry: dict[str, Any]) -> str:\n    \"\"\"Handle uuid key.\"\"\"\n    return f\"{entry.get('video_uuid') or ''}::{entry.get('instance_domain') or ''}\"\n\n\ndef _stripped(value: Any) -> str | None:\n    \"\"\"Return a non-empty stripped string, or None.\"\"\"\n    return value.strip() or None if isinstance(value, str) else None\n\n\ndef _parse_metadata_entries(body: Any) -> list[tuple[str, dict[str, str]]] | None:\n    \"\"\"Return the distinct well-formed metadata entries of a body, tagged \"id\" or \"uuid\", in order.\n\n    An item with a valid video_id is id-keyed even if it also carries video_uuid; duplicates are\n    dropped per form, keeping the first.\n    :returns: None when `entries` is not a list; malformed items are skipped.\n    \"\"\"\n    raw_entries = body.get(\"entries\") if isinstance(body, dict) else None\n    if not isinstance(raw_entries, list):\n        return None\n    entries: list[tuple[str, dict[str, str]]] = []\n    seen: set[tuple[str, str]] = set()\n    for raw in raw_entries:\n        if not isinstance(raw, dict):\n            continue\n        instance = _stripped(raw.get(\"instance_domain\"))\n        if instance is None:\n            continue\n        video_id = _stripped(raw.get(\"video_id\"))\n        video_uuid = _stripped(raw.get(\"video_uuid\"))\n        if video_id is not None:\n            form, entry = \"id\", {\"video_id\": video_id, \"instance_domain\": instance}\n            key = _like_key(entry)\n        elif video_uuid is not None:\n            form, entry = \"uuid\", {\"video_uuid\": video_uuid, \"instance_domain\": instance}\n            key = _uuid_key(entry)\n        else:\n            continue\n        if (form, key) in seen:\n            continue\n        seen.add((form, key))\n        entries.append((form, entry))\n    return entries\n```\n\nTwo notes on the helpers:\n- `_stripped` binds as `(value.strip() or None) if ... else None`. The parenthesised form is what gets written.\n- Tagging the seen-set with the form keeps the id and uuid key spaces apart, since both are `x::y` strings.\n\n**Handler**\n\n```python\ndef handle_internal_videos_metadata(handler: Any, server: Any) -> bool:\n    \"\"\"Return metadata rows for (video_id, instance_domain) and (video_uuid, instance_domain) entries.\n\n    Both forms are answered under one db_lock hold; each video appears once, at its first matching entry.\n    \"\"\"\n    try:\n        body = read_json_body(handler)\n    except ValueError as exc:\n        respond_json(handler, 400, {\"error\": str(exc)})\n        return True\n\n    entries = _parse_metadata_entries(body)\n    if entries is None:\n        respond_json(handler, 400, {\"error\": \"Missing entries\"})\n        return True\n\n    if not entries:\n        respond_json(handler, 200, {\"ok\": True, \"count\": 0, \"rows\": []})\n        return True\n\n    id_entries = [entry for form, entry in entries if form == \"id\"]\n    uuid_entries = [entry for form, entry in entries if form == \"uuid\"]\n    error_threshold = getattr(server, \"video_error_threshold\", None)\n    by_id: dict[str, dict[str, Any]] = {}\n    by_uuid: dict[str, dict[str, Any]] = {}\n    with server.db_lock:\n        if id_entries:\n            by_id = fetch_metadata_by_ids(server.db, id_entries, error_threshold=error_threshold)\n        if uuid_entries:\n            by_uuid = fetch_metadata_by_uuids(server.db, uuid_entries, error_threshold=error_threshold)\n\n    rows: list[dict[str, Any]] = []\n    emitted: set[str] = set()\n    for form, entry in entries:\n        row = by_id.get(_like_key(entry)) if form == \"id\" else by_uuid.get(_uuid_key(entry))\n        if not isinstance(row, dict) or _like_key(row) in emitted:\n            continue\n        emitted.add(_like_key(row))\n        rows.append(row)\n\n    respond_json(handler, 200, {\"ok\": True, \"count\": len(rows), \"rows\": rows})\n    return True\n```\n\n**Why id-only callers see no change.**\n- An id-only request produces exactly the `_parse_entries` list, the same query, and the same entry-order walk.\n- `emitted` cannot drop a row here, because the parser has already deduplicated on the same key.\n\n**Deduplication across forms.** It keys on the returned row's `video_id::instance_domain`, never on the entry.\n\n---\n\n### 3. `client/backend/lib/engine_api_client.py`\n\n- Delete lines 136-166 (`resolve_videos_by_uuid_host`). `resolve_video_seed` stays.\n- New docstring for `fetch_metadata_for_entries`: `\"\"\"Fetch metadata rows from Engine for {video_id|video_uuid, instance_domain} entries, one row per video in first-entry order.\"\"\"`\n- No logic change. An empty list still returns `[]` with no HTTP call.\n\n---\n\n### 4. `client/backend/server.py`\n\n**Import (lines 30-32):**\n```python\nfrom lib.engine_api_client import (EngineApiError, bridge_headers, compute_dislike_centroids,\n                                   fetch_metadata_for_entries, resolve_video_seed)\n```\n\n**Cap (line 52):** `MAX_CLIENT_LIKES = 50`.\n- The grep found three readers: the proxy trim (line 493) and the two `_parse_client_likes` calls.\n- Matches in `delete_me/*.bak-*` are ignored.\n\n**`_handle_likes_import`**: from the `likes = ...` line on.\n- There is no pre-call empty check: `fetch_metadata_for_entries` returns `[]` for an empty list without calling the Engine, so the answer is `{\"imported\": 0}` as today.\n\n```python\n        likes = _parse_client_likes(body, MAX_CLIENT_LIKES)\n        try:\n            rows = fetch_metadata_for_entries(self.server.engine_ingest_base, likes)\n        except EngineApiError as exc:\n            respond_json(self, 502, {\"error\": f\"Engine resolve failed: {exc}\"})\n            return\n        conn = self.server.user_db\n        imported = 0\n        with conn:\n            for row in rows:\n                if is_disliked(conn, profile_id, row[\"video_id\"], row[\"instance_domain\"]):\n                    continue\n                video = {\"video_id\": row[\"video_id\"], \"video_uuid\": row[\"video_uuid\"], \"instance_domain\": row[\"instance_domain\"]}\n                record_like(conn, profile_id, \"like\", video, MAX_LIKES)\n                imported += 1\n        respond_json(self, 200, {\"imported\": imported})\n```\n\n**`_handle_user_profile_likes_from_client`**:\n\n```python\n    def _handle_user_profile_likes_from_client(self) -> None:\n        \"\"\"Answer a browser's local likes (uuid, host) with Engine metadata rows in one Engine call, deduplicated, in submitted order; unknown videos are omitted.\"\"\"\n        ...\n        likes = _parse_client_likes(body, MAX_CLIENT_LIKES)\n        if not likes:\n            respond_json(self, 200, {\"likes\": [], \"updatedAt\": now_ms()})\n            return\n        try:\n            rows = fetch_metadata_for_entries(self.server.engine_ingest_base, likes)\n        except EngineApiError as exc:\n            respond_json(self, 502, {\"error\": f\"Engine metadata failed: {exc}\"})\n            return\n        respond_json(self, 200, {\"likes\": rows, \"updatedAt\": now_ms()})\n```\n\nThe proxy code is unchanged. `_parse_client_likes` is unchanged; its output keys are exactly the Engine's uuid form.\n\n---\n\n### 5. Tests\n\n#### `tests/tmp/test_metadata_uuid_entries.py`\n\n**Setup**\n- `sys.path` gets `engine/server` and `engine/server/api`, as `test_internal_events.py:25-30` does. It then does `from data.metadata import fetch_metadata_by_ids, fetch_metadata_by_uuids` in-process: that module imports no numpy.\n- The handler part runs in an `ENGINE_PY -c` child with `cwd=API_DIR`. The child inserts the same two paths itself.\n- Correction to the plan: the pattern is `test_internal_events.py` / `test_similar.py`, not `test_db.py`.\n\n**Temp schema** (`row_factory = sqlite3.Row`):\n- `videos`: the 26 selected `v.*` columns, plus `error_count INTEGER`, with `PRIMARY KEY (video_id, instance_domain)`.\n- `video_embeddings (video_id, instance_domain, embedding BLOB, embedding_dim, model_name, PRIMARY KEY (video_id, instance_domain))`.\n- `channels (channel_id, instance_domain, display_name, avatar_url)`.\n- It does not call `ensure_video_indexes`; the index does not affect correctness.\n\n**Fixture videos**, all on host `h.example` unless noted:\n\n| video_id | video_uuid | error_count | embedding | purpose |\n|---|---|---|---|---|\n| a1 | u-a | 0 | yes | plain match |\n| b1 | u-b | NULL | yes | id and uuid paths reach the same video |\n| s2 (inserted first) | u-s | 0 | yes | shared pair: rowid order is not id order |\n| s1 | u-s | 0 \u2192 later 5 | yes | lowest id; errored sibling |\n| e1 | u-e | 5 | yes | over threshold 3 |\n| n1 | u-n | 0 | **no** | inner join drops it |\n| a1 on `other.example` | u-a | 0 | yes | exact host match |\n\n**Data-layer tests (in-process)**\n1. `fetch_metadata_by_ids` returns exactly the 29-key dict, keyed `a1::h.example`, with the values from the DB. It skips `n1`, and with threshold 3 it skips `e1`. The empty list gives `{}`.\n2. A 460-video set crosses the 450 chunk boundary on both functions with threshold 3. All 460 come back. The set includes one errored video in the second chunk, which must be absent; that catches a threshold parameter appended once per call.\n3. `fetch_metadata_by_uuids`:\n   - `u-a@h.example` gives `a1@h.example`, not the `other.example` one.\n   - `U-A` and `u-a@H.EXAMPLE` give nothing.\n   - `u-s` gives `s1`. After setting `s1.error_count = 5` with threshold 3, it gives `s2`.\n   - `u-e` gives nothing at threshold 3, and `e1` at threshold None.\n   - `u-n` gives nothing.\n   - The empty list gives `{}` and runs no query: the conn is wrapped so `execute` counts calls.\n4. The same video gives an identical dict through `by_ids[b1::h]` and `by_uuids[u-b::h]`.\n\n**Handler tests (one `ENGINE_PY` child per test group)**\n- The child patches `read_json_body` and `respond_json` on `handlers.internal_client_reads`.\n- Its server is `SimpleNamespace(db=conn, db_lock=CountingLock(), video_error_threshold=3)`. `CountingLock` wraps `threading.Lock` and counts `__enter__`.\n- It prints `[{status, payload, enters}]` for a list of bodies.\n\nCases:\n- Parser forms: an id item with a whitespace uuid; a uuid-only item; an item with both keys (id wins, shown by an id that differs from the uuid's video); a non-dict item; a missing or blank `instance_domain`; neither key; duplicates in each form.\n- `{\"entries\": \"x\"}` and `{}` give 400 `Missing entries`, with `enters == 0`.\n- All-malformed entries give 200 `{\"ok\": True, \"count\": 0, \"rows\": []}`, with `enters == 0`.\n- Id-only `[a1, b1, a1]` gives rows `[a1, b1]`, `count == 2` and `enters == 1`: the same as the old loop.\n- Mixed `[uuid u-b, id a1, id b1, uuid u-a, uuid u-x]` gives `[b1, a1]`: first-match order, each video once, unknown omitted, `enters == 1`.\n- Uuid `u-e` at threshold 3 is absent.\n- Centroids: `fetch_embeddings_by_ids` is spied (wraps). A uuid-only body gives 200, the spy gets `[]`, and `centroids == []`. A mixed body passes only the id entries.\n\n#### `tests/tmp/test_client_like_batching.py`\n\n**Seam**\n- A `ThreadingHTTPServer` stand-in Engine, written like `test_server.py:307`'s `EngineStub`. It records `(path, json body)` for every POST.\n- For `/internal/videos/metadata` it answers from a canned `{uuid::host: row}` table in entry order, omitting unknown entries and duplicates, which mimics the Engine.\n- For any other path it answers `{\"rows\": []}`.\n- The Client is built by local `_serving` and `_client_backend` copies of `test_server.py:251-271`, with `RateLimiter(1000, 60)`.\n\n**Tests**\n1. Likes page: 3 likes plus a duplicate plus an unknown give exactly one recorded Engine request, to `/internal/videos/metadata`. Its `entries` equal the `{video_uuid, instance_domain}` list as submitted (the Client does not dedup). The response `likes` holds the known rows in submitted order, with the unknown omitted.\n2. Likes page with 60 entries: 200, and the single request carries exactly the first 50.\n3. Likes page with an empty or all-malformed body: 200, `likes == []`, and zero Engine requests.\n4. Import: mint via `POST /api/profile`, then find `profile_id` via `resolve_profile(conn, key)` on a second connection to `users.db`. Write one dislike with `write_dislike(conn, profile_id, {...}, None)` and commit. Post 3 likes: the disliked video, a clean one, and an unknown one. This gives exactly one Engine request, `{\"imported\": 1}`, and `load_liked_keys(conn, profile_id) == {(clean_id, host)}`.\n5. Import with 60 entries: 200, and the one request carries 50.\n6. Proxy: a keyless `POST /recommendations` with 60 `{uuid, host}` likes. The recorded forwarded body has `likes` of length 50, equal to the first 50 sanitised.\n\n`test_profiles.py` and `test_server.py` stay unedited. They run against the live Engine, each in its own `validate_tests.py` invocation.\n\n---\n\n### Open item A \u2014 needs a call before the build\n\n**The problem.** The existing id SQL is `WHERE (a) OR (b) ... AND (v.error_count IS NULL OR v.error_count < ?)`. SQL gives `AND` higher precedence than `OR`, so today the threshold filters only the last pair of each chunk. Any other errored video requested by id is returned.\n\nThe settled requirements pull two ways:\n- R3 says \"id callers see exactly the rows they saw before\".\n- R2 says the uuid form uses \"the same error-count threshold clause\".\n\n**Options:**\n1. Keep today's id semantics exactly: the id caller passes an unparenthesised fragment. The uuid fragment is a single `IN` term, so its threshold applies to every row either way.\n2. Parenthesise, and fix the id path as well. That changes what id callers see: errored videos would drop from the GET likes page, block-add and similar or up-next.\n\n**The draft takes option 1 in code.** `_select_metadata` interpolates `WHERE {where}` without wrapping it, which matches R3 literally, and the uuid path is still fully filtered. I flag option 2 as a separate bug for the roadmap rather than fixing it silently here.\n\n**The test consequence.** The \"errored video in chunk 2\" test in 5.1 item 2 applies to `fetch_metadata_by_uuids` only. For `fetch_metadata_by_ids`, the chunk-crossing test asserts all non-errored rows are present and pins current behaviour with no assertion on the errored one.\n\n---\n\n### Corrections to the settled plan text (for the doc step)\n- **Missing index:** wrong. `idx_videos_uuid_instance` exists (`engine/server/data/videos.py:21-22`) and is created on every start.\n- **Test pattern:** `test_internal_events.py` / `test_similar.py`, not `test_db.py`. The data-layer tests run in-process.\n- **Id-path threshold precedence:** see Open item A. The plan's claim that the error clause is \"applied in SQL before the pick\" holds for the uuid path only.\n- **Tests in `tests/tmp` import `conftest`:** they rely on `tests/active/conftest.py` for `ENGINE_PY`, `client_server`, `RateLimiter` and `ensure_user_schema`. I did not verify how `validate_tests.py` puts that on `sys.path` for the working tree. If it does not, the files are promoted to `tests/active` before running.\n\n### Check against plan and requirements (pass 1, converged)\n- **R1:**\n  - `_parse_metadata_entries`: id wins when both keys are present.\n  - It deduplicates per form.\n  - It returns None, which gives 400.\n  - An empty parse answers 200 before the lock.\n  - `_parse_entries` and centroids are untouched.\n- **R2:**\n  - `fetch_metadata_by_uuids` has the same SELECT, joins, threshold and row dict via `_select_metadata`.\n  - It uses a row-value `IN` in 450-pair chunks.\n  - The match is exact.\n  - It returns one row per pair, the lowest `video_id`.\n  - There is no blob check.\n- **R3:**\n  - One `with server.db_lock:` covers both lookups.\n  - Rows are emitted in first-match order and deduplicated on the row's `like_key`.\n  - The threshold applies to both forms.\n  - The response shape is unchanged.\n  - Id-only requests are unchanged, including the precedence quirk (Open item A).\n- **R4 and R5:** one `fetch_metadata_for_entries` call each. Deduplication is left to the Engine. The 502 texts are kept. Import records from the row fields and skips disliked videos.\n- **R6:** the function is deleted and its import dropped. `resolve_video_seed` is kept.\n- **R7:** the constant is 50. All three readers slice before validating.\n- **Acceptance criteria:** each is covered by a test in section 5. The lock count is read through `CountingLock`, and the Engine call count through the stand-in Engine.\n",
  "coordination": "none",
  "tests": {
    "tests/tmp/test_14_batch_like_resolution_phase1.py": {
      "rows": [
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_14_batch_like_resolution_phase1.py:105-108: the result for `u-b@h.example` has the single key `u-b::h.example`. Its row has exactly the 29 ROW_KEYS, equals `fetch_metadata_by_ids(b1@h.example)[\"b1::h.example\"]`, and equals the fixture-stored `_row(*B1)`. Lines :112-116 add exact-match checks: the h.example a1 and not the other.example a1; both hosts, each under its own key; `U-A` gives `{}`; `H.EXAMPLE` gives `{}`; the unembedded `u-n` gives `{}`. Lines :125-126 check that an empty list gives `{}` and runs zero statements, with a control at :122-123.",
          "expected": "`{\"u-b::h.example\": <b1's 29-key row with Chan B/ava-b, embedding_dim 3, model_name m>}`, identical to the id path's row. The uuid and host mismatch cases give `{}`.",
          "wrong_implementation": "A uuid path that builds its own trimmed row, or drops the channels join, fails :106-108 (for example `channel_display_name` None, or keys missing). Matching on the uuid alone returns or overwrites with the other.example a1, which fails :112-113. COLLATE NOCASE or lower() gives a row at :114 or :115 where `{}` is expected. `error_count < ?` without `IS NULL` gives `{}` at :105."
        },
        {
          "clause": "C2",
          "assertion": "tests/tmp/test_14_batch_like_resolution_phase1.py:131, :133, :135, :137, :138 check `u-s@h.example`, the shared pair. It keeps s1; with s1.error_count 3 it keeps s2; with 2, s1; with 5, s2; with 5 and no threshold, s1. The control at :130 shows that the scan order is s2, s1, s3. Lines :142-143 check that `u-e` is dropped at threshold 3 and returned at None.",
          "expected": "Respectively `{\"u-s::h.example\": _row(*S1)}`, `_row(*S2)`, `_row(*S1)`, `_row(*S2)` and `_row(*S1)`. Then `{}` for u-e at threshold 3, and `{\"u-e::h.example\": _row(*E1)}` at None.",
          "wrong_implementation": "Last-row-wins gives s3 at :131. First-row-wins gives s2 at :131 while the order :130 pins holds. Pick-then-filter gives `{}` at :137. A `<=` threshold keeps s1 at :133. An off-by-one that drops error_count 2 gives s2 at :135. Applying the filter when the threshold is None gives s2 at :138, and `{}` for u-e at :143. Omitting the error clause keeps s1 at :133 and :137, and returns u-e at :142."
        }
      ],
      "clauses": [
        {
          "id": "C1",
          "text": "`fetch_metadata_by_uuids` returns, for an exact `(video_uuid, instance_domain)` match, the same row dict that `fetch_metadata_by_ids` returns for that video."
        },
        {
          "id": "C2",
          "text": "Where several videos share one `(video_uuid, instance_domain)`, the row kept is the one with the lowest `video_id` among those under the error threshold."
        }
      ],
      "surface": "checkpoint",
      "results": {
        "command": "validate_tests.py tests/tmp/test_14_batch_like_resolution_phase1.py",
        "code": 1,
        "output": "  tests/tmp/test_14_batch_like_resolution_phase1.py  6 failed, 1 passed                     0.0s\n  -------------------------------------------------\n  total                                              6 failed, 1 passed                     0.2s wall, 1 lane\n\nrecorded: tests/last_test_validation.json (exit 1)\nwrote tests/last_test_output.txt"
      }
    },
    "tests/tmp/test_14_batch_like_resolution_phase2.py": {
      "rows": [
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_14_batch_like_resolution_phase2.py:157 \u2014 (enters, row video_ids) for the mixed body [uuid u-b, id a1, id b1, uuid u-a, uuid u-x]; :160 \u2014 set(statements_locked) == {True}; :162 \u2014 (enters, set(statements_locked)) for the id-first mixed body",
          "expected": "(1, [\"b1\", \"a1\"]) at :157; {True} at :160; (1, {True}) at :162",
          "wrong_implementation": "Separate lookups per form, each under its own `with db_lock` (or `acquire()`, which the counter also sees), read enters 2, so :157 gets (2, [\"b1\", \"a1\"]) and :162 gets (2, {True}). One acquisition that wraps only the id lookup runs the uuid SELECT with the lock free, so :160 gets {False, True}. The unchanged id-only handler reads (1, [\"a1\", \"b1\"]) at :157."
        },
        {
          "clause": "C2",
          "assertion": "tests/tmp/test_14_batch_like_resolution_phase2.py:158 \u2014 mixed body [uuid u-b, id a1, id b1, uuid u-a, uuid u-x] responses; :159 \u2014 id-first mixed body [id a1, uuid u-x, uuid u-b, id b1] responses; :185 \u2014 [uuid u-a, uuid u-a, id b1, id b1, uuid u-b, id a1] responses",
          "expected": "_rows(B1, A1) at :158 (count 2, full rows, u-x omitted); _rows(A1, B1) at :159; _rows(A1, B1) at :185",
          "wrong_implementation": "Emitting all id rows first, or in table order, gives [a1, b1] at :158. Emitting all uuid rows first gives [b1, a1] at :159. Appending each form's matches without deduplicating gives [b1, a1, b1, a1] or similar, count 4, at :158 and repeated rows at :185. A placeholder row for u-x makes the count 3 at :158."
        }
      ],
      "clauses": [
        {
          "id": "C1",
          "text": "A request body mixing id-form and uuid-form entries acquires `db_lock` exactly once."
        },
        {
          "id": "C2",
          "text": "Each matched video appears once in `rows`, in the order of its first matching entry."
        }
      ],
      "surface": "checkpoint",
      "results": {
        "command": "validate_tests.py tests/tmp/test_14_batch_like_resolution_phase2.py",
        "code": 1,
        "output": "  tests/tmp/test_14_batch_like_resolution_phase2.py  4 failed, 3 passed                     0.0s\n  -------------------------------------------------\n  total                                              4 failed, 3 passed                     1.0s wall, 1 lane\n\nrecorded: tests/last_test_validation.json (exit 1)\nwrote tests/last_test_output.txt"
      }
    },
    "tests/tmp/test_14_batch_like_resolution_phase3.py": {
      "rows": [
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_14_batch_like_resolution_phase3.py:109, :117, :121, :140. The stand-in's full request record equals exactly one `(/internal/videos/metadata, {\"entries\": [submitted pairs in order]})` for the likes page (:109), the well-formed page after the empty ones (:121) and the import (:140). It is `[]` after the empty and malformed pages (:117).",
          "expected": ":109 `[(METADATA, {\"entries\": [u-c, u-a, u-c, u-x, u-b pairs]})]`. :117 `[]`. :121 `[(METADATA, {\"entries\": [u-a pair]})]`. :140 `[(METADATA, {\"entries\": [u-a, u-b, u-x, u-c pairs]})]`.",
          "wrong_implementation": "The current per-like `resolve_videos_by_uuid_host` loop. Its record starts with `('/internal/videos/resolve', {'host': 'h.example', 'uuid': ...})`, observed on this run at :109, :121 and :140. Deduping or filtering entries before the call, or making a second call, also breaks the equality."
        },
        {
          "clause": "C2",
          "assertion": "tests/tmp/test_14_batch_like_resolution_phase3.py:141, :142, :143. The import answers `(200, {\"imported\": 2})`. `load_liked_keys` is `{(\"id-a\", HOST), (\"id-c\", HOST)}`. The stored like rows are `{(\"id-a\", \"u-a\", HOST), (\"id-c\", \"u-c\", HOST)}`.",
          "expected": "`(200, {\"imported\": 2})`; `{(\"id-a\", HOST), (\"id-c\", HOST)}`; `{(\"id-a\", \"u-a\", HOST), (\"id-c\", \"u-c\", HOST)}`.",
          "wrong_implementation": "Ignoring the dislike, or checking it against the uuid, imports 3 (observed, FAIL at :141). Skipping the first or last returned row imports 1 (observed, FAIL at :141). Recording a like from the unknown submitted `u-x`, or keying the like on the uuid, puts `u-x`/`u-a` into the liked set at :142. Dropping the uuid gives a null at :143 (observed)."
        }
      ],
      "clauses": [
        {
          "id": "C1",
          "text": "A likes-page or likes-import request causes exactly one Engine HTTP call, to `/internal/videos/metadata`."
        },
        {
          "id": "C2",
          "text": "Likes import records a like for each returned row whose video the profile has not disliked."
        }
      ],
      "surface": "checkpoint",
      "results": {
        "command": "validate_tests.py tests/tmp/test_14_batch_like_resolution_phase3.py",
        "code": 1,
        "output": "  tests/tmp/test_14_batch_like_resolution_phase3.py  3 failed                               0.0s\n  -------------------------------------------------\n  total                                              3 failed                               2.2s wall, 1 lane\n\nrecorded: tests/last_test_validation.json (exit 1)\nwrote tests/last_test_output.txt"
      }
    },
    "tests/tmp/test_14_batch_like_resolution_phase4.py": {
      "rows": [
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_14_batch_like_resolution_phase4.py:109 \u2014 a 60-like `POST /api/user-profile/likes` body leaves the stand-in Engine with exactly one recorded request, `(\"/internal/videos/metadata\", {\"entries\": [{video_uuid: u-00..u-49, instance_domain: h.example}]})`, in submitted order",
          "expected": "`received == [(\"/internal/videos/metadata\", {\"entries\": <the 50 pairs u-00..u-49>})]`. The probe checked this: with `client_server.MAX_CLIENT_LIKES` monkeypatched to 50, this test passes.",
          "wrong_implementation": "The current cap of 200 (`client/backend/server.py:51`). The probe observed one metadata request with 60 entries, u-00 through u-59. A cap of 49 or 51 also fails at :109 (observed). So does a `_parse_client_likes` that keeps the last 50 entries instead of the first 50 (observed). A second Engine call, such as a leftover per-like resolve, would also make the list comparison unequal."
        },
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_14_batch_like_resolution_phase4.py:110 \u2014 that likes-page request is answered `(200, [id-00..id-49])`, the rows of exactly the first 50 videos, in order",
          "expected": "`(200, [\"id-00\", \u2026, \"id-49\"])` (passes at an emulated cap of 50)",
          "wrong_implementation": "Cap 200: status 200 and 60 rows, id-00 through id-59 (observed). A cap that dropped entries with a 4xx instead of trimming them silently would also fail on the status."
        },
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_14_batch_like_resolution_phase4.py:123 \u2014 a 60-like `POST /api/profile/likes/import` records exactly one Engine request, `(\"/internal/videos/metadata\", {\"entries\": [u-00..u-49 pairs]})`",
          "expected": "`received == [(\"/internal/videos/metadata\", {\"entries\": <the 50 pairs u-00..u-49>})]`. Minting the profile makes no Engine call; this passes at an emulated cap of 50.",
          "wrong_implementation": "Cap 200: one metadata request with 60 entries, u-00 through u-59 (observed). A cap of 49 or 51, or keeping the last 50, also fails at :123 (observed)."
        },
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_14_batch_like_resolution_phase4.py:124 and :125 \u2014 the import answers `(200, {\"imported\": 50})` and the profile's liked keys are exactly `{(id-00..id-49, h.example)}`",
          "expected": "`(200, {\"imported\": 50})` and exactly 50 liked keys, id-00 through id-49 (passes at an emulated cap of 50)",
          "wrong_implementation": "Cap 200: `{\"imported\": 60}` and 60 liked keys, id-00 through id-59 (observed). The Client capping the request while the import still records a like for every submitted entry would also fail here."
        },
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_14_batch_like_resolution_phase4.py:131 and :133 \u2014 a keyless 60-like `POST /recommendations` gets 200, and the only forwarded request goes to path `/recommendations` with `likes` equal to the `{uuid, host}` pairs u-00..u-49",
          "expected": "Status 200, and `[(\"/recommendations\", [<the 50 pairs u-00..u-49>])]`. The query string `?limit=48` is dropped by `urlparse(...).path` (observed). This passes at an emulated cap of 50.",
          "wrong_implementation": "Cap 200: one forwarded request, `/recommendations?limit=48`, with 60 likes, u-00 through u-59 (observed). The same happens if only the two `_parse_client_likes` readers are capped and the proxy trim `likes[:MAX_CLIENT_LIKES]` at `server.py:492` is missed. A cap of 49 or 51 also fails at :133 (observed)."
        }
      ],
      "clauses": [
        {
          "id": "C1",
          "text": "A body carrying 60 like entries reaches the Engine as its first 50 entries."
        }
      ],
      "surface": "checkpoint",
      "results": {
        "command": "validate_tests.py tests/tmp/test_14_batch_like_resolution_phase4.py",
        "code": 1,
        "output": "  tests/tmp/test_14_batch_like_resolution_phase4.py  3 failed                               0.0s\n  -------------------------------------------------\n  total                                              3 failed                               2.2s wall, 1 lane\n\nrecorded: tests/last_test_validation.json (exit 1)\nwrote tests/last_test_output.txt"
      }
    }
  },
  "audits": {
    "tests/tmp/test_14_batch_like_resolution_phase1.py": [
      {
        "shape": "```\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\nEvery test that goes through `_by_uuids` fails at tests/tmp/test_14_batch_like_resolution_phase1.py:77 with\n`AttributeError: module 'data.metadata' has no attribute 'fetch_metadata_by_uuids'`. The first to fail is\ntest_a_uuid_pair_gets_the_row_the_id_lookup_gives_its_video, at line 103. The bulk test gets past its id-path\nassertions at lines 157-158 and then fails at line 159. test_the_id_lookup_returns_the_joined_row_and_skips_an_unembedded_video\nnever calls the uuid lookup and should pass: it only pins the id path.\n\nNOT ASSESSED\n1. `code_under_test` listed tests/tmp/test_metadata_uuid_entries.py (NEW), which does not resolve. It was\n   not read.\n2. `code_under_test` listed engine/server/data/metadata.py as EDITED, but it does not define\n   `fetch_metadata_by_uuids`. Grep over engine/ also found nothing. The stub question was answered from the\n   assertion form alone, not against an implementation.\n```",
        "claim": "CLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (38 clauses: 5 must_prove, 26 docstring, 7 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | \"the same row dict that `fetch_metadata_by_ids` returns for that video\" | :107 | a uuid path that builds its own row: a trimmed dict, dropped joins, or renamed or re-typed values | CARRIED |\n| C1b | must_prove | exact match on `video_uuid` | :114 | case-insensitive uuid matching (`COLLATE NOCASE`, `lower()`) | CARRIED |\n| C1c | must_prove | exact match on `instance_domain` | :112, :113, :115 | matching on the uuid alone, where other.example's a1 is returned or overwrites; case-insensitive host matching | CARRIED |\n| C2a | must_prove | several videos share a pair, and the lowest `video_id` is kept | :130 | a last-row-wins dict overwrite gives s3. First-row-wins gives s2, but only because the rows come back in the order s2, s1, s3, and nothing asserts that order (see D15) | CARRIED |\n| C2b | must_prove | \"among those under the error threshold\" | :132, :136, :134 | pick-then-filter gives `{}` at :136; `<=` against the threshold keeps s1 at :132; applying no filter keeps s1 at :132/:136 | CARRIED |\n| D1 | docstring | \"answers an exact pair with the row `fetch_metadata_by_ids` gives that video\" | :107 | a uuid row that differs from the id row | CARRIED |\n| D2 | docstring | \"a pair shared by several videos with the lowest `video_id` under the error threshold\" | :130, :132, :136 | the same as C2a and C2b | CARRIED |\n| D3 | docstring | \"keyed `u-b::h.example`\" | :105 | keying by `like_key` (`b1::h.example`), or returning more than one key | CARRIED |\n| D4 | docstring | \"the 29-key row\" | :106 | a row with keys missing or extra | CARRIED |\n| D5 | docstring | \"its `channels` and `video_embeddings` columns joined in\" | :108 | leaving out the channels LEFT JOIN, so `channel_display_name` is None; dropping `embedding_dim`/`model_name` | CARRIED |\n| D6 | docstring | \"the same one the fixture stored\" | :108 | both lookups being wrong in the same way, which :107 alone would pass | CARRIED |\n| D7 | docstring | \"b1's NULL `error_count` does not exclude it\" | :105 (threshold 3 by default at :76) | `error_count < ?` without `IS NULL`, which gives `{}` | CARRIED |\n| D8 | docstring | \"`u-a@h.example` gives the h.example a1 and not the other.example a1\" | :112 | a match on the uuid alone | CARRIED |\n| D9 | docstring | \"Asking for both gives each under its own key\" | :113 | keying by uuid only, so one host overwrites the other | CARRIED |\n| D10 | docstring | \"`U-A@h.example` ... give `{}`\" | :114 | a case-insensitive uuid match | CARRIED |\n| D11 | docstring | \"`u-a@H.EXAMPLE` ... give `{}`\" | :115 | a case-insensitive host match | CARRIED |\n| D12 | docstring | \"`u-n@h.example` (no embedding) give[s] `{}`\" | :116 | a LEFT JOIN on `video_embeddings` | CARRIED |\n| D13 | docstring | \"An empty list gives `{}`\" | :125 | returning something other than an empty dict on empty input | CARRIED |\n| D14 | docstring | \"and runs no SQL statement on the connection\" | :126, control at :122-123 | having no early return, so a query or setup statement still runs | CARRIED |\n| D15 | docstring | \"the three `u-s` siblings come out of the SELECT as s2, s1, s3 (observed)\" | none | nothing: the order is stated but never asserted, although the first-row-wins exclusion in C2a depends on it | UNCARRIED |\n| D16 | docstring | \"the lookup keeps s1\" | :130 | first-row-wins or last-row-wins | CARRIED |\n| D17 | docstring | \"at 3 or 5 under threshold 3 it keeps s2\" | :132, :136 | `<=` against the threshold; pick-then-filter | CARRIED |\n| D18 | docstring | \"at 2 it keeps s1\" | :134 | an off-by-one threshold that excludes `error_count == threshold-1` | CARRIED |\n| D19 | docstring | \"with no threshold it keeps s1 at 5\" | :137 | applying a filter when the threshold is None | CARRIED |\n| D20 | docstring | \"`u-e` (error_count 5) is dropped at threshold 3\" | :141 | a uuid query without the error clause | CARRIED |\n| D21 | docstring | \"and returned with no threshold\" | :142 | always applying the error clause | CARRIED |\n| D22 | docstring | \"a1's full row with the unembedded n1 skipped\" (id path) | :147 | an id-path refactor that changes the row or LEFT JOINs embeddings | CARRIED |\n| D23 | docstring | \"both lookups return every healthy video\" across 460 / the 450 chunk | :157, :160 | querying only the first chunk; a wrong parameter count per chunk | CARRIED |\n| D24 | docstring | \"The uuid lookup also drops the errored video in chunk 2\" | :160 | copying the id path's OR-chain, which applies the threshold only to each chunk's last pair | CARRIED |\n| D25 | docstring | \"The id lookup is not asserted on that video\" | :157 | a statement about the test's own scope; :157 is a subset check, which matches it | CARRIED |\n| D26 | docstring | \"in-process against a temporary SQLite database with the Engine's three joined tables. Nothing is stubbed\" | :81-99 (fixture) | a statement about the harness, true as the fixture is built; no stub or patch appears in the file | CARRIED |\n| N1 | name | \"a uuid pair gets the row the id lookup gives its video\" | :107 | same as C1a | CARRIED |\n| N2 | name | \"a uuid pair matches only its exact uuid and host\" | :112-115 | uuid-only or case-insensitive matching | CARRIED |\n| N3 | name | \"an empty uuid list gives nothing and runs no statement\" | :125, :126 | a non-empty result; a statement run on empty input | CARRIED |\n| N4 | name | \"a shared uuid pair keeps the lowest video_id under the threshold\" | :130-136 | same as C2a and C2b | CARRIED |\n| N5 | name | \"an errored video's uuid pair is dropped only while a threshold is set\" | :141, :142 | no error clause; an error clause applied unconditionally | CARRIED |\n| N6 | name | \"the id lookup returns the joined row and skips an unembedded video\" | :147 | a changed id row; a LEFT JOIN on embeddings | CARRIED |\n| N7 | name | \"both lookups return every healthy video across the 450-entry chunk boundary\" | :157, :160 | a first-chunk-only query on either path | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. whole-claim (rules/testing.md) \u2014 tests/tmp/test_14_batch_like_resolution_phase1.py:5\n   D15 is UNCARRIED. The docstring says the `u-s` siblings \"come out of the SELECT as s2, s1, s3 (observed)\", but no assertion checks that order. The order matters: `:130` rules out a first-row-wins pick only while the scan returns s2 first. If the order were s1, s2, s3, first-row-wins would pass :130, :132 and :136. Either assert the order the rows come back in, or narrow the sentence.\n2. bounds (rules/testing.md) \u2014 tests/tmp/test_14_batch_like_resolution_phase1.py:76\n   The only thresholds tested are 3 and None. The existing code in `metadata.py:128` treats `error_threshold > 0` as \"set\", but `error_threshold=0` is never tested, and neither is a negative threshold. N5 (\"only while a threshold is set\") does not say which side 0 falls on.\n3. normal-and-abnormal-paths (rules/testing.md) \u2014 tests/tmp/test_14_batch_like_resolution_phase1.py:77\n   Every entry `_by_uuids` builds is well formed. No test covers an entry with a missing `video_uuid` key, a None or empty `instance_domain`, or the same pair repeated in one request. That leaves the malformed-input failure mode of the uuid lookup untested.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `code_under_test` lists `engine/server/data/metadata.py` (EDITED), but the file as read does not define `fetch_metadata_by_uuids`. The call at :77 therefore targets a function that is not written yet. Its return contract (a dict keyed `video_uuid::instance_domain`, and the `error_threshold` keyword) was judged from the test alone, not against an implementation.\n2. `code_under_test` lists `tests/tmp/test_metadata_uuid_entries.py` (NEW), which does not exist, so it was not read.\n3. No `fixtures_path` was supplied and no `conftest.py` exists under `tests/tmp`. The test defines its only fixture, `conn`, at :80-99, so nothing is missing for independence.\n4. The Grep for the `fetch_metadata_by_uuids` definition also matched `docs/project/plans/16-14-batch-like-resolution.record.md`, which is the build's working record. This verdict rests on `testing.md`, the test file and `metadata.py`, and cites no reasoning from that record.",
        "body": "### devsecops-test-shape-auditor\n\n```\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\nEvery test that goes through `_by_uuids` fails at tests/tmp/test_14_batch_like_resolution_phase1.py:77 with\n`AttributeError: module 'data.metadata' has no attribute 'fetch_metadata_by_uuids'`. The first to fail is\ntest_a_uuid_pair_gets_the_row_the_id_lookup_gives_its_video, at line 103. The bulk test gets past its id-path\nassertions at lines 157-158 and then fails at line 159. test_the_id_lookup_returns_the_joined_row_and_skips_an_unembedded_video\nnever calls the uuid lookup and should pass: it only pins the id path.\n\nNOT ASSESSED\n1. `code_under_test` listed tests/tmp/test_metadata_uuid_entries.py (NEW), which does not resolve. It was\n   not read.\n2. `code_under_test` listed engine/server/data/metadata.py as EDITED, but it does not define\n   `fetch_metadata_by_uuids`. Grep over engine/ also found nothing. The stub question was answered from the\n   assertion form alone, not against an implementation.\n```\n\n### devsecops-test-claim-auditor\n\nCLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (38 clauses: 5 must_prove, 26 docstring, 7 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | \"the same row dict that `fetch_metadata_by_ids` returns for that video\" | :107 | a uuid path that builds its own row: a trimmed dict, dropped joins, or renamed or re-typed values | CARRIED |\n| C1b | must_prove | exact match on `video_uuid` | :114 | case-insensitive uuid matching (`COLLATE NOCASE`, `lower()`) | CARRIED |\n| C1c | must_prove | exact match on `instance_domain` | :112, :113, :115 | matching on the uuid alone, where other.example's a1 is returned or overwrites; case-insensitive host matching | CARRIED |\n| C2a | must_prove | several videos share a pair, and the lowest `video_id` is kept | :130 | a last-row-wins dict overwrite gives s3. First-row-wins gives s2, but only because the rows come back in the order s2, s1, s3, and nothing asserts that order (see D15) | CARRIED |\n| C2b | must_prove | \"among those under the error threshold\" | :132, :136, :134 | pick-then-filter gives `{}` at :136; `<=` against the threshold keeps s1 at :132; applying no filter keeps s1 at :132/:136 | CARRIED |\n| D1 | docstring | \"answers an exact pair with the row `fetch_metadata_by_ids` gives that video\" | :107 | a uuid row that differs from the id row | CARRIED |\n| D2 | docstring | \"a pair shared by several videos with the lowest `video_id` under the error threshold\" | :130, :132, :136 | the same as C2a and C2b | CARRIED |\n| D3 | docstring | \"keyed `u-b::h.example`\" | :105 | keying by `like_key` (`b1::h.example`), or returning more than one key | CARRIED |\n| D4 | docstring | \"the 29-key row\" | :106 | a row with keys missing or extra | CARRIED |\n| D5 | docstring | \"its `channels` and `video_embeddings` columns joined in\" | :108 | leaving out the channels LEFT JOIN, so `channel_display_name` is None; dropping `embedding_dim`/`model_name` | CARRIED |\n| D6 | docstring | \"the same one the fixture stored\" | :108 | both lookups being wrong in the same way, which :107 alone would pass | CARRIED |\n| D7 | docstring | \"b1's NULL `error_count` does not exclude it\" | :105 (threshold 3 by default at :76) | `error_count < ?` without `IS NULL`, which gives `{}` | CARRIED |\n| D8 | docstring | \"`u-a@h.example` gives the h.example a1 and not the other.example a1\" | :112 | a match on the uuid alone | CARRIED |\n| D9 | docstring | \"Asking for both gives each under its own key\" | :113 | keying by uuid only, so one host overwrites the other | CARRIED |\n| D10 | docstring | \"`U-A@h.example` ... give `{}`\" | :114 | a case-insensitive uuid match | CARRIED |\n| D11 | docstring | \"`u-a@H.EXAMPLE` ... give `{}`\" | :115 | a case-insensitive host match | CARRIED |\n| D12 | docstring | \"`u-n@h.example` (no embedding) give[s] `{}`\" | :116 | a LEFT JOIN on `video_embeddings` | CARRIED |\n| D13 | docstring | \"An empty list gives `{}`\" | :125 | returning something other than an empty dict on empty input | CARRIED |\n| D14 | docstring | \"and runs no SQL statement on the connection\" | :126, control at :122-123 | having no early return, so a query or setup statement still runs | CARRIED |\n| D15 | docstring | \"the three `u-s` siblings come out of the SELECT as s2, s1, s3 (observed)\" | none | nothing: the order is stated but never asserted, although the first-row-wins exclusion in C2a depends on it | UNCARRIED |\n| D16 | docstring | \"the lookup keeps s1\" | :130 | first-row-wins or last-row-wins | CARRIED |\n| D17 | docstring | \"at 3 or 5 under threshold 3 it keeps s2\" | :132, :136 | `<=` against the threshold; pick-then-filter | CARRIED |\n| D18 | docstring | \"at 2 it keeps s1\" | :134 | an off-by-one threshold that excludes `error_count == threshold-1` | CARRIED |\n| D19 | docstring | \"with no threshold it keeps s1 at 5\" | :137 | applying a filter when the threshold is None | CARRIED |\n| D20 | docstring | \"`u-e` (error_count 5) is dropped at threshold 3\" | :141 | a uuid query without the error clause | CARRIED |\n| D21 | docstring | \"and returned with no threshold\" | :142 | always applying the error clause | CARRIED |\n| D22 | docstring | \"a1's full row with the unembedded n1 skipped\" (id path) | :147 | an id-path refactor that changes the row or LEFT JOINs embeddings | CARRIED |\n| D23 | docstring | \"both lookups return every healthy video\" across 460 / the 450 chunk | :157, :160 | querying only the first chunk; a wrong parameter count per chunk | CARRIED |\n| D24 | docstring | \"The uuid lookup also drops the errored video in chunk 2\" | :160 | copying the id path's OR-chain, which applies the threshold only to each chunk's last pair | CARRIED |\n| D25 | docstring | \"The id lookup is not asserted on that video\" | :157 | a statement about the test's own scope; :157 is a subset check, which matches it | CARRIED |\n| D26 | docstring | \"in-process against a temporary SQLite database with the Engine's three joined tables. Nothing is stubbed\" | :81-99 (fixture) | a statement about the harness, true as the fixture is built; no stub or patch appears in the file | CARRIED |\n| N1 | name | \"a uuid pair gets the row the id lookup gives its video\" | :107 | same as C1a | CARRIED |\n| N2 | name | \"a uuid pair matches only its exact uuid and host\" | :112-115 | uuid-only or case-insensitive matching | CARRIED |\n| N3 | name | \"an empty uuid list gives nothing and runs no statement\" | :125, :126 | a non-empty result; a statement run on empty input | CARRIED |\n| N4 | name | \"a shared uuid pair keeps the lowest video_id under the threshold\" | :130-136 | same as C2a and C2b | CARRIED |\n| N5 | name | \"an errored video's uuid pair is dropped only while a threshold is set\" | :141, :142 | no error clause; an error clause applied unconditionally | CARRIED |\n| N6 | name | \"the id lookup returns the joined row and skips an unembedded video\" | :147 | a changed id row; a LEFT JOIN on embeddings | CARRIED |\n| N7 | name | \"both lookups return every healthy video across the 450-entry chunk boundary\" | :157, :160 | a first-chunk-only query on either path | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. whole-claim (rules/testing.md) \u2014 tests/tmp/test_14_batch_like_resolution_phase1.py:5\n   D15 is UNCARRIED. The docstring says the `u-s` siblings \"come out of the SELECT as s2, s1, s3 (observed)\", but no assertion checks that order. The order matters: `:130` rules out a first-row-wins pick only while the scan returns s2 first. If the order were s1, s2, s3, first-row-wins would pass :130, :132 and :136. Either assert the order the rows come back in, or narrow the sentence.\n2. bounds (rules/testing.md) \u2014 tests/tmp/test_14_batch_like_resolution_phase1.py:76\n   The only thresholds tested are 3 and None. The existing code in `metadata.py:128` treats `error_threshold > 0` as \"set\", but `error_threshold=0` is never tested, and neither is a negative threshold. N5 (\"only while a threshold is set\") does not say which side 0 falls on.\n3. normal-and-abnormal-paths (rules/testing.md) \u2014 tests/tmp/test_14_batch_like_resolution_phase1.py:77\n   Every entry `_by_uuids` builds is well formed. No test covers an entry with a missing `video_uuid` key, a None or empty `instance_domain`, or the same pair repeated in one request. That leaves the malformed-input failure mode of the uuid lookup untested.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `code_under_test` lists `engine/server/data/metadata.py` (EDITED), but the file as read does not define `fetch_metadata_by_uuids`. The call at :77 therefore targets a function that is not written yet. Its return contract (a dict keyed `video_uuid::instance_domain`, and the `error_threshold` keyword) was judged from the test alone, not against an implementation.\n2. `code_under_test` lists `tests/tmp/test_metadata_uuid_entries.py` (NEW), which does not exist, so it was not read.\n3. No `fixtures_path` was supplied and no `conftest.py` exists under `tests/tmp`. The test defines its only fixture, `conn`, at :80-99, so nothing is missing for independence.\n4. The Grep for the `fetch_metadata_by_uuids` definition also matched `docs/project/plans/16-14-batch-like-resolution.record.md`, which is the build's working record. This verdict rests on `testing.md`, the test file and `metadata.py`, and cites no reasoning from that record.",
        "map": [
          {
            "id": "C1a",
            "source": "must_prove",
            "clause": "\"the same row dict that `fetch_metadata_by_ids` returns for that video\"",
            "assertion": ":107",
            "excludes": "a uuid path that builds its own row: a trimmed dict, dropped joins, or renamed or re-typed values",
            "status": "CARRIED"
          },
          {
            "id": "C1b",
            "source": "must_prove",
            "clause": "exact match on `video_uuid`",
            "assertion": ":114",
            "excludes": "case-insensitive uuid matching (`COLLATE NOCASE`, `lower()`)",
            "status": "CARRIED"
          },
          {
            "id": "C1c",
            "source": "must_prove",
            "clause": "exact match on `instance_domain`",
            "assertion": ":112, :113, :115",
            "excludes": "matching on the uuid alone, where other.example's a1 is returned or overwrites; case-insensitive host matching",
            "status": "CARRIED"
          },
          {
            "id": "C2a",
            "source": "must_prove",
            "clause": "several videos share a pair, and the lowest `video_id` is kept",
            "assertion": ":130",
            "excludes": "a last-row-wins dict overwrite gives s3. First-row-wins gives s2, but only because the rows come back in the order s2, s1, s3, and nothing asserts that order (see D15)",
            "status": "CARRIED"
          },
          {
            "id": "C2b",
            "source": "must_prove",
            "clause": "\"among those under the error threshold\"",
            "assertion": ":132, :136, :134",
            "excludes": "pick-then-filter gives `{}` at :136; `<=` against the threshold keeps s1 at :132; applying no filter keeps s1 at :132/:136",
            "status": "CARRIED"
          },
          {
            "id": "D1",
            "source": "docstring",
            "clause": "\"answers an exact pair with the row `fetch_metadata_by_ids` gives that video\"",
            "assertion": ":107",
            "excludes": "a uuid row that differs from the id row",
            "status": "CARRIED"
          },
          {
            "id": "D2",
            "source": "docstring",
            "clause": "\"a pair shared by several videos with the lowest `video_id` under the error threshold\"",
            "assertion": ":130, :132, :136",
            "excludes": "the same as C2a and C2b",
            "status": "CARRIED"
          },
          {
            "id": "D3",
            "source": "docstring",
            "clause": "\"keyed `u-b::h.example`\"",
            "assertion": ":105",
            "excludes": "keying by `like_key` (`b1::h.example`), or returning more than one key",
            "status": "CARRIED"
          },
          {
            "id": "D4",
            "source": "docstring",
            "clause": "\"the 29-key row\"",
            "assertion": ":106",
            "excludes": "a row with keys missing or extra",
            "status": "CARRIED"
          },
          {
            "id": "D5",
            "source": "docstring",
            "clause": "\"its `channels` and `video_embeddings` columns joined in\"",
            "assertion": ":108",
            "excludes": "leaving out the channels LEFT JOIN, so `channel_display_name` is None; dropping `embedding_dim`/`model_name`",
            "status": "CARRIED"
          },
          {
            "id": "D6",
            "source": "docstring",
            "clause": "\"the same one the fixture stored\"",
            "assertion": ":108",
            "excludes": "both lookups being wrong in the same way, which :107 alone would pass",
            "status": "CARRIED"
          },
          {
            "id": "D7",
            "source": "docstring",
            "clause": "\"b1's NULL `error_count` does not exclude it\"",
            "assertion": ":105 (threshold 3 by default at :76)",
            "excludes": "`error_count < ?` without `IS NULL`, which gives `{}`",
            "status": "CARRIED"
          },
          {
            "id": "D8",
            "source": "docstring",
            "clause": "\"`u-a@h.example` gives the h.example a1 and not the other.example a1\"",
            "assertion": ":112",
            "excludes": "a match on the uuid alone",
            "status": "CARRIED"
          },
          {
            "id": "D9",
            "source": "docstring",
            "clause": "\"Asking for both gives each under its own key\"",
            "assertion": ":113",
            "excludes": "keying by uuid only, so one host overwrites the other",
            "status": "CARRIED"
          },
          {
            "id": "D10",
            "source": "docstring",
            "clause": "\"`U-A@h.example` ... give `{}`\"",
            "assertion": ":114",
            "excludes": "a case-insensitive uuid match",
            "status": "CARRIED"
          },
          {
            "id": "D11",
            "source": "docstring",
            "clause": "\"`u-a@H.EXAMPLE` ... give `{}`\"",
            "assertion": ":115",
            "excludes": "a case-insensitive host match",
            "status": "CARRIED"
          },
          {
            "id": "D12",
            "source": "docstring",
            "clause": "\"`u-n@h.example` (no embedding) give[s] `{}`\"",
            "assertion": ":116",
            "excludes": "a LEFT JOIN on `video_embeddings`",
            "status": "CARRIED"
          },
          {
            "id": "D13",
            "source": "docstring",
            "clause": "\"An empty list gives `{}`\"",
            "assertion": ":125",
            "excludes": "returning something other than an empty dict on empty input",
            "status": "CARRIED"
          },
          {
            "id": "D14",
            "source": "docstring",
            "clause": "\"and runs no SQL statement on the connection\"",
            "assertion": ":126, control at :122-123",
            "excludes": "having no early return, so a query or setup statement still runs",
            "status": "CARRIED"
          },
          {
            "id": "D15",
            "source": "docstring",
            "clause": "\"the three `u-s` siblings come out of the SELECT as s2, s1, s3 (observed)\"",
            "assertion": "none",
            "excludes": "nothing: the order is stated but never asserted, although the first-row-wins exclusion in C2a depends on it",
            "status": "UNCARRIED"
          },
          {
            "id": "D16",
            "source": "docstring",
            "clause": "\"the lookup keeps s1\"",
            "assertion": ":130",
            "excludes": "first-row-wins or last-row-wins",
            "status": "CARRIED"
          },
          {
            "id": "D17",
            "source": "docstring",
            "clause": "\"at 3 or 5 under threshold 3 it keeps s2\"",
            "assertion": ":132, :136",
            "excludes": "`<=` against the threshold; pick-then-filter",
            "status": "CARRIED"
          },
          {
            "id": "D18",
            "source": "docstring",
            "clause": "\"at 2 it keeps s1\"",
            "assertion": ":134",
            "excludes": "an off-by-one threshold that excludes `error_count == threshold-1`",
            "status": "CARRIED"
          },
          {
            "id": "D19",
            "source": "docstring",
            "clause": "\"with no threshold it keeps s1 at 5\"",
            "assertion": ":137",
            "excludes": "applying a filter when the threshold is None",
            "status": "CARRIED"
          },
          {
            "id": "D20",
            "source": "docstring",
            "clause": "\"`u-e` (error_count 5) is dropped at threshold 3\"",
            "assertion": ":141",
            "excludes": "a uuid query without the error clause",
            "status": "CARRIED"
          },
          {
            "id": "D21",
            "source": "docstring",
            "clause": "\"and returned with no threshold\"",
            "assertion": ":142",
            "excludes": "always applying the error clause",
            "status": "CARRIED"
          },
          {
            "id": "D22",
            "source": "docstring",
            "clause": "\"a1's full row with the unembedded n1 skipped\" (id path)",
            "assertion": ":147",
            "excludes": "an id-path refactor that changes the row or LEFT JOINs embeddings",
            "status": "CARRIED"
          },
          {
            "id": "D23",
            "source": "docstring",
            "clause": "\"both lookups return every healthy video\" across 460 / the 450 chunk",
            "assertion": ":157, :160",
            "excludes": "querying only the first chunk; a wrong parameter count per chunk",
            "status": "CARRIED"
          },
          {
            "id": "D24",
            "source": "docstring",
            "clause": "\"The uuid lookup also drops the errored video in chunk 2\"",
            "assertion": ":160",
            "excludes": "copying the id path's OR-chain, which applies the threshold only to each chunk's last pair",
            "status": "CARRIED"
          },
          {
            "id": "D25",
            "source": "docstring",
            "clause": "\"The id lookup is not asserted on that video\"",
            "assertion": ":157",
            "excludes": "a statement about the test's own scope; :157 is a subset check, which matches it",
            "status": "CARRIED"
          },
          {
            "id": "D26",
            "source": "docstring",
            "clause": "\"in-process against a temporary SQLite database with the Engine's three joined tables. Nothing is stubbed\"",
            "assertion": ":81-99 (fixture)",
            "excludes": "a statement about the harness, true as the fixture is built; no stub or patch appears in the file",
            "status": "CARRIED"
          },
          {
            "id": "N1",
            "source": "name",
            "clause": "\"a uuid pair gets the row the id lookup gives its video\"",
            "assertion": ":107",
            "excludes": "same as C1a",
            "status": "CARRIED"
          },
          {
            "id": "N2",
            "source": "name",
            "clause": "\"a uuid pair matches only its exact uuid and host\"",
            "assertion": ":112-115",
            "excludes": "uuid-only or case-insensitive matching",
            "status": "CARRIED"
          },
          {
            "id": "N3",
            "source": "name",
            "clause": "\"an empty uuid list gives nothing and runs no statement\"",
            "assertion": ":125, :126",
            "excludes": "a non-empty result; a statement run on empty input",
            "status": "CARRIED"
          },
          {
            "id": "N4",
            "source": "name",
            "clause": "\"a shared uuid pair keeps the lowest video_id under the threshold\"",
            "assertion": ":130-136",
            "excludes": "same as C2a and C2b",
            "status": "CARRIED"
          },
          {
            "id": "N5",
            "source": "name",
            "clause": "\"an errored video's uuid pair is dropped only while a threshold is set\"",
            "assertion": ":141, :142",
            "excludes": "no error clause; an error clause applied unconditionally",
            "status": "CARRIED"
          },
          {
            "id": "N6",
            "source": "name",
            "clause": "\"the id lookup returns the joined row and skips an unembedded video\"",
            "assertion": ":147",
            "excludes": "a changed id row; a LEFT JOIN on embeddings",
            "status": "CARRIED"
          },
          {
            "id": "N7",
            "source": "name",
            "clause": "\"both lookups return every healthy video across the 450-entry chunk boundary\"",
            "assertion": ":157, :160",
            "excludes": "a first-chunk-only query on either path",
            "status": "CARRIED"
          }
        ],
        "map_problem": ""
      },
      {
        "shape": "```\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\nSix tests fail. Each one reaches `_by_uuids` (line 77), the only caller of\n`metadata.fetch_metadata_by_uuids(...)`, and fails there with\n`AttributeError: module 'data.metadata' has no attribute 'fetch_metadata_by_uuids'`.\nWhere each test first reaches it:\n- test_a_uuid_pair_gets_the_row_the_id_lookup_gives_its_video: line 103\n- test_a_uuid_pair_matches_only_its_exact_uuid_and_host: line 112\n- test_an_empty_uuid_list_gives_nothing_and_runs_no_statement: line 122\n- test_a_shared_uuid_pair_keeps_the_lowest_video_id_under_the_threshold: line 131\n- test_an_errored_video_s_uuid_pair_is_dropped_only_while_a_threshold_is_set: line 142\n- test_both_lookups_return_every_healthy_video_across_the_450_entry_chunk_boundary:\n  line 160, after its id-lookup assertions at lines 158\u2013159 pass\ntest_the_id_lookup_returns_the_joined_row_and_skips_an_unembedded_video (line 146)\npasses, because it touches only the existing `fetch_metadata_by_ids`.\n\nNOT ASSESSED\n1. `code_under_test` listed tests/tmp/test_metadata_uuid_entries.py. That path does not\n   resolve, so its contents were not reviewed.\n2. `fetch_metadata_by_uuids` is not defined anywhere under engine/, so the stub\n   question was answered from the test's assertions alone. The answer: each assertion\n   compares against a literal built from the fixture (`_row(*...)` or exact key sets).\n   The fixture stores the siblings as s2, s1, s3 (line 130) and changes s1's\n   error_count to 3, 2 and 5 (lines 132\u2013138). A stub or hard-coded return fails, and so\n   do these wrong versions:\n   - keeping the first row (s2 at line 131) or the last row (s3 at line 131)\n   - ignoring the threshold (line 133)\n   - using `<=` against the threshold (line 133)\n   - picking the lowest id before applying the threshold filter (line 133 would give {})\n   - keying rows by video_id (line 105)\n   - matching case-insensitively (lines 114\u2013115)\n   - returning the id lookup's output unchanged (lines 105 and 112)\n   Anti-pattern pass: nothing found. Every negative assertion (lines 114\u2013116, 125\u2013126,\n   142) has a positive control in the same test (lines 112\u2013113, 122\u2013123, 143).\n   Ladder pass: the test sits at rung 1, direct invocation of the functions, which is\n   the highest rung this invariant supports.\n```",
        "claim": "CLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (38 clauses: 5 must_prove, 26 docstring, 7 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | \"the same row dict that `fetch_metadata_by_ids` returns for that video\" | :107 | a uuid path that builds its own row: a trimmed dict, dropped joins, or renamed or re-typed values | CARRIED |\n| C1b | must_prove | exact match on `video_uuid` | :114 | case-insensitive uuid matching (`COLLATE NOCASE`, `lower()`) | CARRIED |\n| C1c | must_prove | exact match on `instance_domain` | :112, :113, :115 | a match on the uuid alone, where other.example's a1 is returned or overwrites the other; case-insensitive host matching | CARRIED |\n| C2a | must_prove | several videos share a pair, and the lowest `video_id` is kept | :131, with the order pinned at :130 | last-row-wins gives s3. First-row-wins gives s2 while the scan order s2, s1, s3 holds, and :130 now asserts that order | CARRIED |\n| C2b | must_prove | \"among those under the error threshold\" | :133, :135, :137 | pick-then-filter gives `{}` at :137; `<=` against the threshold keeps s1 at :133; applying no filter keeps s1 at :133 and :137 | CARRIED |\n| D1 | docstring | \"answers an exact pair with the row `fetch_metadata_by_ids` gives that video\" | :107 | a uuid row that differs from the id row | CARRIED |\n| D2 | docstring | \"a pair shared by several videos with the lowest `video_id` under the error threshold\" | :131, :133, :137 | the same as C2a and C2b | CARRIED |\n| D3 | docstring | \"keyed `u-b::h.example`\" | :105 | keying by `like_key` (`b1::h.example`), or returning more than one key | CARRIED |\n| D4 | docstring | \"the 29-key row\" | :106 | a row with keys missing or extra | CARRIED |\n| D5 | docstring | \"its `channels` and `video_embeddings` columns joined in\" | :108 | leaving out the channels LEFT JOIN, so `channel_display_name` is None; dropping `embedding_dim` or `model_name` | CARRIED |\n| D6 | docstring | \"the same one the fixture stored\" | :108 | both lookups being wrong in the same way, which :107 alone would pass | CARRIED |\n| D7 | docstring | \"b1's NULL `error_count` does not exclude it\" | :105 (threshold 3 by default at :76) | `error_count < ?` without `IS NULL`, which gives `{}` | CARRIED |\n| D8 | docstring | \"`u-a@h.example` gives the h.example a1 and not the other.example a1\" | :112 | a match on the uuid alone | CARRIED |\n| D9 | docstring | \"Asking for both gives each under its own key\" | :113 | keying by uuid only, so one host overwrites the other | CARRIED |\n| D10 | docstring | \"`U-A@h.example` ... give `{}`\" | :114 | a case-insensitive uuid match | CARRIED |\n| D11 | docstring | \"`u-a@H.EXAMPLE` ... give `{}`\" | :115 | a case-insensitive host match | CARRIED |\n| D12 | docstring | \"`u-n@h.example` (no embedding) give[s] `{}`\" | :116 | a LEFT JOIN on `video_embeddings` | CARRIED |\n| D13 | docstring | \"An empty list gives `{}`\" | :125 | returning something other than an empty dict on empty input | CARRIED |\n| D14 | docstring | \"and runs no SQL statement on the connection\" | :126, control at :122-123 | no early return, so a query or setup statement still runs | CARRIED |\n| D15 | docstring | narrowed to \"The fixture stores the three `u-s` siblings as s2, s1, s3, and a scan of `videos` yields them in that order\" | :130 | a fixture that has drifted (reordered, or scanned in id order), where first-row-wins would pass :131 | CARRIED |\n| D16 | docstring | \"The lookup keeps s1\" | :131 | first-row-wins or last-row-wins | CARRIED |\n| D17 | docstring | \"at 3 or 5 under threshold 3 it keeps s2\" | :133, :137 | `<=` against the threshold; pick-then-filter | CARRIED |\n| D18 | docstring | \"at 2 it keeps s1\" | :135 | an off-by-one threshold that excludes `error_count == threshold-1` | CARRIED |\n| D19 | docstring | \"with no threshold it keeps s1 at 5\" | :138 | applying a filter when the threshold is None | CARRIED |\n| D20 | docstring | \"`u-e` (error_count 5) is dropped at threshold 3\" | :142 | a uuid query with no error clause | CARRIED |\n| D21 | docstring | \"and returned with no threshold\" | :143 | always applying the error clause | CARRIED |\n| D22 | docstring | \"a1's full row with the unembedded n1 skipped\" (id path) | :148 | an id-path refactor that changes the row or LEFT JOINs embeddings | CARRIED |\n| D23 | docstring | \"both lookups return every healthy video\" across 460 videos and the 450-entry chunk | :158, :161 | querying only the first chunk; a wrong parameter count per chunk | CARRIED |\n| D24 | docstring | \"The uuid lookup also drops the errored video in chunk 2\" | :161 | copying the id path's OR-chain, which applies the threshold only to each chunk's last pair | CARRIED |\n| D25 | docstring | \"The id lookup is not asserted on that video\" | :158 | a statement about the test's own scope; :158 is a subset check, which matches it | CARRIED |\n| D26 | docstring | \"in-process against a temporary SQLite database with the Engine's three joined tables. Nothing is stubbed\" | :80-99 (fixture) | a statement about the harness, true as the fixture is built; no stub or patch appears in the file | CARRIED |\n| N1 | name | \"a uuid pair gets the row the id lookup gives its video\" | :107 | same as C1a | CARRIED |\n| N2 | name | \"a uuid pair matches only its exact uuid and host\" | :112-115 | uuid-only or case-insensitive matching | CARRIED |\n| N3 | name | \"an empty uuid list gives nothing and runs no statement\" | :125, :126 | a non-empty result; a statement run on empty input | CARRIED |\n| N4 | name | \"a shared uuid pair keeps the lowest video_id under the threshold\" | :131-138 | same as C2a and C2b | CARRIED |\n| N5 | name | \"an errored video's uuid pair is dropped only while a threshold is set\" | :142, :143 | no error clause; an error clause applied unconditionally | CARRIED |\n| N6 | name | \"the id lookup returns the joined row and skips an unembedded video\" | :148 | a changed id row; a LEFT JOIN on embeddings | CARRIED |\n| N7 | name | \"both lookups return every healthy video across the 450-entry chunk boundary\" | :158, :161 | a first-chunk-only query on either path | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nOBSERVATIONS\n1. whole-claim (rules/testing.md) \u2014 tests/tmp/test_14_batch_like_resolution_phase1.py:5, :130\n   D15 was resolved two ways. The prose was narrowed, from \"come out of the SELECT as s2, s1, s3 (observed)\" to \"a scan of `videos` yields them in that order\". An assertion was also added at :130:\n   `assert [row[\"video_id\"] for row in conn.execute(\"SELECT video_id FROM videos WHERE video_uuid = 'u-s'\")] == [\"s2\", \"s1\", \"s3\"], ...`\n   The narrowed sentence is carried. The old claim was about the order the production SELECT returns rows in, and nothing asserts that now. :130 reads a plain scan of `videos`, not the `video_embeddings JOIN videos` query the lookup runs. So C2a's exclusion of first-row-wins at :131 still depends on the join visiting the rows in the order the plain scan does. The docstring no longer claims more than :130 shows, so this does not block.\n2. bounds (rules/testing.md) \u2014 tests/tmp/test_14_batch_like_resolution_phase1.py:76\n   Carried over from round 1, and no ledger row names it. Only thresholds 3 and None are exercised. `error_threshold=0` and negative values are never tested, although `metadata.py:128` treats only `> 0` as a set threshold.\n3. normal-and-abnormal-paths (rules/testing.md) \u2014 tests/tmp/test_14_batch_like_resolution_phase1.py:77\n   Carried over from round 1, and no ledger row names it. Every entry `_by_uuids` builds is well formed. No test covers an entry missing `video_uuid`, a None or empty `instance_domain`, or the same pair repeated in one request.\n\nNOT ASSESSED\n1. `code_under_test` lists `engine/server/data/metadata.py` (EDITED), but the file as read does not define `fetch_metadata_by_uuids`. Its return contract (a dict keyed `video_uuid::instance_domain`, and the `error_threshold` keyword) was judged from the test alone.\n2. `code_under_test` lists `tests/tmp/test_metadata_uuid_entries.py` (NEW), which does not exist, so it was not read.\n3. No `fixtures_path` was supplied, and no `conftest.py` exists under `tests/tmp`. The test defines its only fixture, `conn`, at :80-99.\n4. The Grep for `fetch_metadata_by_uuids` also matched the build's working record, `docs/project/plans/16-14-batch-like-resolution.record.md`. This verdict rests only on `testing.md`, the test file and `metadata.py`, and uses nothing from that record.",
        "body": "### devsecops-test-shape-auditor\n\n```\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\nSix tests fail. Each one reaches `_by_uuids` (line 77), the only caller of\n`metadata.fetch_metadata_by_uuids(...)`, and fails there with\n`AttributeError: module 'data.metadata' has no attribute 'fetch_metadata_by_uuids'`.\nWhere each test first reaches it:\n- test_a_uuid_pair_gets_the_row_the_id_lookup_gives_its_video: line 103\n- test_a_uuid_pair_matches_only_its_exact_uuid_and_host: line 112\n- test_an_empty_uuid_list_gives_nothing_and_runs_no_statement: line 122\n- test_a_shared_uuid_pair_keeps_the_lowest_video_id_under_the_threshold: line 131\n- test_an_errored_video_s_uuid_pair_is_dropped_only_while_a_threshold_is_set: line 142\n- test_both_lookups_return_every_healthy_video_across_the_450_entry_chunk_boundary:\n  line 160, after its id-lookup assertions at lines 158\u2013159 pass\ntest_the_id_lookup_returns_the_joined_row_and_skips_an_unembedded_video (line 146)\npasses, because it touches only the existing `fetch_metadata_by_ids`.\n\nNOT ASSESSED\n1. `code_under_test` listed tests/tmp/test_metadata_uuid_entries.py. That path does not\n   resolve, so its contents were not reviewed.\n2. `fetch_metadata_by_uuids` is not defined anywhere under engine/, so the stub\n   question was answered from the test's assertions alone. The answer: each assertion\n   compares against a literal built from the fixture (`_row(*...)` or exact key sets).\n   The fixture stores the siblings as s2, s1, s3 (line 130) and changes s1's\n   error_count to 3, 2 and 5 (lines 132\u2013138). A stub or hard-coded return fails, and so\n   do these wrong versions:\n   - keeping the first row (s2 at line 131) or the last row (s3 at line 131)\n   - ignoring the threshold (line 133)\n   - using `<=` against the threshold (line 133)\n   - picking the lowest id before applying the threshold filter (line 133 would give {})\n   - keying rows by video_id (line 105)\n   - matching case-insensitively (lines 114\u2013115)\n   - returning the id lookup's output unchanged (lines 105 and 112)\n   Anti-pattern pass: nothing found. Every negative assertion (lines 114\u2013116, 125\u2013126,\n   142) has a positive control in the same test (lines 112\u2013113, 122\u2013123, 143).\n   Ladder pass: the test sits at rung 1, direct invocation of the functions, which is\n   the highest rung this invariant supports.\n```\n\n### devsecops-test-claim-auditor\n\nCLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (38 clauses: 5 must_prove, 26 docstring, 7 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | \"the same row dict that `fetch_metadata_by_ids` returns for that video\" | :107 | a uuid path that builds its own row: a trimmed dict, dropped joins, or renamed or re-typed values | CARRIED |\n| C1b | must_prove | exact match on `video_uuid` | :114 | case-insensitive uuid matching (`COLLATE NOCASE`, `lower()`) | CARRIED |\n| C1c | must_prove | exact match on `instance_domain` | :112, :113, :115 | a match on the uuid alone, where other.example's a1 is returned or overwrites the other; case-insensitive host matching | CARRIED |\n| C2a | must_prove | several videos share a pair, and the lowest `video_id` is kept | :131, with the order pinned at :130 | last-row-wins gives s3. First-row-wins gives s2 while the scan order s2, s1, s3 holds, and :130 now asserts that order | CARRIED |\n| C2b | must_prove | \"among those under the error threshold\" | :133, :135, :137 | pick-then-filter gives `{}` at :137; `<=` against the threshold keeps s1 at :133; applying no filter keeps s1 at :133 and :137 | CARRIED |\n| D1 | docstring | \"answers an exact pair with the row `fetch_metadata_by_ids` gives that video\" | :107 | a uuid row that differs from the id row | CARRIED |\n| D2 | docstring | \"a pair shared by several videos with the lowest `video_id` under the error threshold\" | :131, :133, :137 | the same as C2a and C2b | CARRIED |\n| D3 | docstring | \"keyed `u-b::h.example`\" | :105 | keying by `like_key` (`b1::h.example`), or returning more than one key | CARRIED |\n| D4 | docstring | \"the 29-key row\" | :106 | a row with keys missing or extra | CARRIED |\n| D5 | docstring | \"its `channels` and `video_embeddings` columns joined in\" | :108 | leaving out the channels LEFT JOIN, so `channel_display_name` is None; dropping `embedding_dim` or `model_name` | CARRIED |\n| D6 | docstring | \"the same one the fixture stored\" | :108 | both lookups being wrong in the same way, which :107 alone would pass | CARRIED |\n| D7 | docstring | \"b1's NULL `error_count` does not exclude it\" | :105 (threshold 3 by default at :76) | `error_count < ?` without `IS NULL`, which gives `{}` | CARRIED |\n| D8 | docstring | \"`u-a@h.example` gives the h.example a1 and not the other.example a1\" | :112 | a match on the uuid alone | CARRIED |\n| D9 | docstring | \"Asking for both gives each under its own key\" | :113 | keying by uuid only, so one host overwrites the other | CARRIED |\n| D10 | docstring | \"`U-A@h.example` ... give `{}`\" | :114 | a case-insensitive uuid match | CARRIED |\n| D11 | docstring | \"`u-a@H.EXAMPLE` ... give `{}`\" | :115 | a case-insensitive host match | CARRIED |\n| D12 | docstring | \"`u-n@h.example` (no embedding) give[s] `{}`\" | :116 | a LEFT JOIN on `video_embeddings` | CARRIED |\n| D13 | docstring | \"An empty list gives `{}`\" | :125 | returning something other than an empty dict on empty input | CARRIED |\n| D14 | docstring | \"and runs no SQL statement on the connection\" | :126, control at :122-123 | no early return, so a query or setup statement still runs | CARRIED |\n| D15 | docstring | narrowed to \"The fixture stores the three `u-s` siblings as s2, s1, s3, and a scan of `videos` yields them in that order\" | :130 | a fixture that has drifted (reordered, or scanned in id order), where first-row-wins would pass :131 | CARRIED |\n| D16 | docstring | \"The lookup keeps s1\" | :131 | first-row-wins or last-row-wins | CARRIED |\n| D17 | docstring | \"at 3 or 5 under threshold 3 it keeps s2\" | :133, :137 | `<=` against the threshold; pick-then-filter | CARRIED |\n| D18 | docstring | \"at 2 it keeps s1\" | :135 | an off-by-one threshold that excludes `error_count == threshold-1` | CARRIED |\n| D19 | docstring | \"with no threshold it keeps s1 at 5\" | :138 | applying a filter when the threshold is None | CARRIED |\n| D20 | docstring | \"`u-e` (error_count 5) is dropped at threshold 3\" | :142 | a uuid query with no error clause | CARRIED |\n| D21 | docstring | \"and returned with no threshold\" | :143 | always applying the error clause | CARRIED |\n| D22 | docstring | \"a1's full row with the unembedded n1 skipped\" (id path) | :148 | an id-path refactor that changes the row or LEFT JOINs embeddings | CARRIED |\n| D23 | docstring | \"both lookups return every healthy video\" across 460 videos and the 450-entry chunk | :158, :161 | querying only the first chunk; a wrong parameter count per chunk | CARRIED |\n| D24 | docstring | \"The uuid lookup also drops the errored video in chunk 2\" | :161 | copying the id path's OR-chain, which applies the threshold only to each chunk's last pair | CARRIED |\n| D25 | docstring | \"The id lookup is not asserted on that video\" | :158 | a statement about the test's own scope; :158 is a subset check, which matches it | CARRIED |\n| D26 | docstring | \"in-process against a temporary SQLite database with the Engine's three joined tables. Nothing is stubbed\" | :80-99 (fixture) | a statement about the harness, true as the fixture is built; no stub or patch appears in the file | CARRIED |\n| N1 | name | \"a uuid pair gets the row the id lookup gives its video\" | :107 | same as C1a | CARRIED |\n| N2 | name | \"a uuid pair matches only its exact uuid and host\" | :112-115 | uuid-only or case-insensitive matching | CARRIED |\n| N3 | name | \"an empty uuid list gives nothing and runs no statement\" | :125, :126 | a non-empty result; a statement run on empty input | CARRIED |\n| N4 | name | \"a shared uuid pair keeps the lowest video_id under the threshold\" | :131-138 | same as C2a and C2b | CARRIED |\n| N5 | name | \"an errored video's uuid pair is dropped only while a threshold is set\" | :142, :143 | no error clause; an error clause applied unconditionally | CARRIED |\n| N6 | name | \"the id lookup returns the joined row and skips an unembedded video\" | :148 | a changed id row; a LEFT JOIN on embeddings | CARRIED |\n| N7 | name | \"both lookups return every healthy video across the 450-entry chunk boundary\" | :158, :161 | a first-chunk-only query on either path | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nOBSERVATIONS\n1. whole-claim (rules/testing.md) \u2014 tests/tmp/test_14_batch_like_resolution_phase1.py:5, :130\n   D15 was resolved two ways. The prose was narrowed, from \"come out of the SELECT as s2, s1, s3 (observed)\" to \"a scan of `videos` yields them in that order\". An assertion was also added at :130:\n   `assert [row[\"video_id\"] for row in conn.execute(\"SELECT video_id FROM videos WHERE video_uuid = 'u-s'\")] == [\"s2\", \"s1\", \"s3\"], ...`\n   The narrowed sentence is carried. The old claim was about the order the production SELECT returns rows in, and nothing asserts that now. :130 reads a plain scan of `videos`, not the `video_embeddings JOIN videos` query the lookup runs. So C2a's exclusion of first-row-wins at :131 still depends on the join visiting the rows in the order the plain scan does. The docstring no longer claims more than :130 shows, so this does not block.\n2. bounds (rules/testing.md) \u2014 tests/tmp/test_14_batch_like_resolution_phase1.py:76\n   Carried over from round 1, and no ledger row names it. Only thresholds 3 and None are exercised. `error_threshold=0` and negative values are never tested, although `metadata.py:128` treats only `> 0` as a set threshold.\n3. normal-and-abnormal-paths (rules/testing.md) \u2014 tests/tmp/test_14_batch_like_resolution_phase1.py:77\n   Carried over from round 1, and no ledger row names it. Every entry `_by_uuids` builds is well formed. No test covers an entry missing `video_uuid`, a None or empty `instance_domain`, or the same pair repeated in one request.\n\nNOT ASSESSED\n1. `code_under_test` lists `engine/server/data/metadata.py` (EDITED), but the file as read does not define `fetch_metadata_by_uuids`. Its return contract (a dict keyed `video_uuid::instance_domain`, and the `error_threshold` keyword) was judged from the test alone.\n2. `code_under_test` lists `tests/tmp/test_metadata_uuid_entries.py` (NEW), which does not exist, so it was not read.\n3. No `fixtures_path` was supplied, and no `conftest.py` exists under `tests/tmp`. The test defines its only fixture, `conn`, at :80-99.\n4. The Grep for `fetch_metadata_by_uuids` also matched the build's working record, `docs/project/plans/16-14-batch-like-resolution.record.md`. This verdict rests only on `testing.md`, the test file and `metadata.py`, and uses nothing from that record.",
        "map": [
          {
            "id": "C1a",
            "source": "must_prove",
            "clause": "\"the same row dict that `fetch_metadata_by_ids` returns for that video\"",
            "assertion": ":107",
            "excludes": "a uuid path that builds its own row: a trimmed dict, dropped joins, or renamed or re-typed values",
            "status": "CARRIED"
          },
          {
            "id": "C1b",
            "source": "must_prove",
            "clause": "exact match on `video_uuid`",
            "assertion": ":114",
            "excludes": "case-insensitive uuid matching (`COLLATE NOCASE`, `lower()`)",
            "status": "CARRIED"
          },
          {
            "id": "C1c",
            "source": "must_prove",
            "clause": "exact match on `instance_domain`",
            "assertion": ":112, :113, :115",
            "excludes": "a match on the uuid alone, where other.example's a1 is returned or overwrites the other; case-insensitive host matching",
            "status": "CARRIED"
          },
          {
            "id": "C2a",
            "source": "must_prove",
            "clause": "several videos share a pair, and the lowest `video_id` is kept",
            "assertion": ":131, with the order pinned at :130",
            "excludes": "last-row-wins gives s3. First-row-wins gives s2 while the scan order s2, s1, s3 holds, and :130 now asserts that order",
            "status": "CARRIED"
          },
          {
            "id": "C2b",
            "source": "must_prove",
            "clause": "\"among those under the error threshold\"",
            "assertion": ":133, :135, :137",
            "excludes": "pick-then-filter gives `{}` at :137; `<=` against the threshold keeps s1 at :133; applying no filter keeps s1 at :133 and :137",
            "status": "CARRIED"
          },
          {
            "id": "D1",
            "source": "docstring",
            "clause": "\"answers an exact pair with the row `fetch_metadata_by_ids` gives that video\"",
            "assertion": ":107",
            "excludes": "a uuid row that differs from the id row",
            "status": "CARRIED"
          },
          {
            "id": "D2",
            "source": "docstring",
            "clause": "\"a pair shared by several videos with the lowest `video_id` under the error threshold\"",
            "assertion": ":131, :133, :137",
            "excludes": "the same as C2a and C2b",
            "status": "CARRIED"
          },
          {
            "id": "D3",
            "source": "docstring",
            "clause": "\"keyed `u-b::h.example`\"",
            "assertion": ":105",
            "excludes": "keying by `like_key` (`b1::h.example`), or returning more than one key",
            "status": "CARRIED"
          },
          {
            "id": "D4",
            "source": "docstring",
            "clause": "\"the 29-key row\"",
            "assertion": ":106",
            "excludes": "a row with keys missing or extra",
            "status": "CARRIED"
          },
          {
            "id": "D5",
            "source": "docstring",
            "clause": "\"its `channels` and `video_embeddings` columns joined in\"",
            "assertion": ":108",
            "excludes": "leaving out the channels LEFT JOIN, so `channel_display_name` is None; dropping `embedding_dim` or `model_name`",
            "status": "CARRIED"
          },
          {
            "id": "D6",
            "source": "docstring",
            "clause": "\"the same one the fixture stored\"",
            "assertion": ":108",
            "excludes": "both lookups being wrong in the same way, which :107 alone would pass",
            "status": "CARRIED"
          },
          {
            "id": "D7",
            "source": "docstring",
            "clause": "\"b1's NULL `error_count` does not exclude it\"",
            "assertion": ":105 (threshold 3 by default at :76)",
            "excludes": "`error_count < ?` without `IS NULL`, which gives `{}`",
            "status": "CARRIED"
          },
          {
            "id": "D8",
            "source": "docstring",
            "clause": "\"`u-a@h.example` gives the h.example a1 and not the other.example a1\"",
            "assertion": ":112",
            "excludes": "a match on the uuid alone",
            "status": "CARRIED"
          },
          {
            "id": "D9",
            "source": "docstring",
            "clause": "\"Asking for both gives each under its own key\"",
            "assertion": ":113",
            "excludes": "keying by uuid only, so one host overwrites the other",
            "status": "CARRIED"
          },
          {
            "id": "D10",
            "source": "docstring",
            "clause": "\"`U-A@h.example` ... give `{}`\"",
            "assertion": ":114",
            "excludes": "a case-insensitive uuid match",
            "status": "CARRIED"
          },
          {
            "id": "D11",
            "source": "docstring",
            "clause": "\"`u-a@H.EXAMPLE` ... give `{}`\"",
            "assertion": ":115",
            "excludes": "a case-insensitive host match",
            "status": "CARRIED"
          },
          {
            "id": "D12",
            "source": "docstring",
            "clause": "\"`u-n@h.example` (no embedding) give[s] `{}`\"",
            "assertion": ":116",
            "excludes": "a LEFT JOIN on `video_embeddings`",
            "status": "CARRIED"
          },
          {
            "id": "D13",
            "source": "docstring",
            "clause": "\"An empty list gives `{}`\"",
            "assertion": ":125",
            "excludes": "returning something other than an empty dict on empty input",
            "status": "CARRIED"
          },
          {
            "id": "D14",
            "source": "docstring",
            "clause": "\"and runs no SQL statement on the connection\"",
            "assertion": ":126, control at :122-123",
            "excludes": "no early return, so a query or setup statement still runs",
            "status": "CARRIED"
          },
          {
            "id": "D15",
            "source": "docstring",
            "clause": "narrowed to \"The fixture stores the three `u-s` siblings as s2, s1, s3, and a scan of `videos` yields them in that order\"",
            "assertion": ":130",
            "excludes": "a fixture that has drifted (reordered, or scanned in id order), where first-row-wins would pass :131",
            "status": "CARRIED"
          },
          {
            "id": "D16",
            "source": "docstring",
            "clause": "\"The lookup keeps s1\"",
            "assertion": ":131",
            "excludes": "first-row-wins or last-row-wins",
            "status": "CARRIED"
          },
          {
            "id": "D17",
            "source": "docstring",
            "clause": "\"at 3 or 5 under threshold 3 it keeps s2\"",
            "assertion": ":133, :137",
            "excludes": "`<=` against the threshold; pick-then-filter",
            "status": "CARRIED"
          },
          {
            "id": "D18",
            "source": "docstring",
            "clause": "\"at 2 it keeps s1\"",
            "assertion": ":135",
            "excludes": "an off-by-one threshold that excludes `error_count == threshold-1`",
            "status": "CARRIED"
          },
          {
            "id": "D19",
            "source": "docstring",
            "clause": "\"with no threshold it keeps s1 at 5\"",
            "assertion": ":138",
            "excludes": "applying a filter when the threshold is None",
            "status": "CARRIED"
          },
          {
            "id": "D20",
            "source": "docstring",
            "clause": "\"`u-e` (error_count 5) is dropped at threshold 3\"",
            "assertion": ":142",
            "excludes": "a uuid query with no error clause",
            "status": "CARRIED"
          },
          {
            "id": "D21",
            "source": "docstring",
            "clause": "\"and returned with no threshold\"",
            "assertion": ":143",
            "excludes": "always applying the error clause",
            "status": "CARRIED"
          },
          {
            "id": "D22",
            "source": "docstring",
            "clause": "\"a1's full row with the unembedded n1 skipped\" (id path)",
            "assertion": ":148",
            "excludes": "an id-path refactor that changes the row or LEFT JOINs embeddings",
            "status": "CARRIED"
          },
          {
            "id": "D23",
            "source": "docstring",
            "clause": "\"both lookups return every healthy video\" across 460 videos and the 450-entry chunk",
            "assertion": ":158, :161",
            "excludes": "querying only the first chunk; a wrong parameter count per chunk",
            "status": "CARRIED"
          },
          {
            "id": "D24",
            "source": "docstring",
            "clause": "\"The uuid lookup also drops the errored video in chunk 2\"",
            "assertion": ":161",
            "excludes": "copying the id path's OR-chain, which applies the threshold only to each chunk's last pair",
            "status": "CARRIED"
          },
          {
            "id": "D25",
            "source": "docstring",
            "clause": "\"The id lookup is not asserted on that video\"",
            "assertion": ":158",
            "excludes": "a statement about the test's own scope; :158 is a subset check, which matches it",
            "status": "CARRIED"
          },
          {
            "id": "D26",
            "source": "docstring",
            "clause": "\"in-process against a temporary SQLite database with the Engine's three joined tables. Nothing is stubbed\"",
            "assertion": ":80-99 (fixture)",
            "excludes": "a statement about the harness, true as the fixture is built; no stub or patch appears in the file",
            "status": "CARRIED"
          },
          {
            "id": "N1",
            "source": "name",
            "clause": "\"a uuid pair gets the row the id lookup gives its video\"",
            "assertion": ":107",
            "excludes": "same as C1a",
            "status": "CARRIED"
          },
          {
            "id": "N2",
            "source": "name",
            "clause": "\"a uuid pair matches only its exact uuid and host\"",
            "assertion": ":112-115",
            "excludes": "uuid-only or case-insensitive matching",
            "status": "CARRIED"
          },
          {
            "id": "N3",
            "source": "name",
            "clause": "\"an empty uuid list gives nothing and runs no statement\"",
            "assertion": ":125, :126",
            "excludes": "a non-empty result; a statement run on empty input",
            "status": "CARRIED"
          },
          {
            "id": "N4",
            "source": "name",
            "clause": "\"a shared uuid pair keeps the lowest video_id under the threshold\"",
            "assertion": ":131-138",
            "excludes": "same as C2a and C2b",
            "status": "CARRIED"
          },
          {
            "id": "N5",
            "source": "name",
            "clause": "\"an errored video's uuid pair is dropped only while a threshold is set\"",
            "assertion": ":142, :143",
            "excludes": "no error clause; an error clause applied unconditionally",
            "status": "CARRIED"
          },
          {
            "id": "N6",
            "source": "name",
            "clause": "\"the id lookup returns the joined row and skips an unembedded video\"",
            "assertion": ":148",
            "excludes": "a changed id row; a LEFT JOIN on embeddings",
            "status": "CARRIED"
          },
          {
            "id": "N7",
            "source": "name",
            "clause": "\"both lookups return every healthy video across the 450-entry chunk boundary\"",
            "assertion": ":158, :161",
            "excludes": "a first-chunk-only query on either path",
            "status": "CARRIED"
          }
        ],
        "map_problem": ""
      }
    ],
    "tests/tmp/test_14_batch_like_resolution_phase2.py": [
      {
        "shape": "```\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. No rule in shape.md covers this \u2014 tests/tmp/test_14_batch_like_resolution_phase2.py:167-168\n   assert report[\"responses\"] == _rows(A1, B1)  # C2\n   assert report[\"enters\"] == 1  # C1\n   These lines carry the C2 and C1 tags, but they hold against the current handler.\n   It parses only id-form entries, deduplicates them, and takes the lock once for\n   them. So this test is a regression control, not the gate for either clause. Both\n   clauses are gated at lines 157-162. The same is true of\n   test_a_body_with_no_entries_list_or_no_valid_entry_is_answered_without_the_lock\n   (lines 198-200), which is not tagged.\n\nPREDICTED FAILURE\nFails at line 157 on the tuple assertion. The current `_parse_entries` drops every\nuuid-form entry, so the first mixed body resolves only ids a1 and b1, in entry order.\nThe observed value is (1, [\"a1\", \"b1\"]); the expected value is (1, [\"b1\", \"a1\"]).\n\nNOT ASSESSED\n1. `code_under_test` listed tests/tmp/test_metadata_uuid_entries.py, which does not\n   resolve (there is no such file under tests/tmp/). The audit covered\n   engine/server/api/handlers/internal_client_reads.py and\n   engine/server/data/metadata.py, found by Grep.\n2. `fixtures_path` was not supplied. The only external symbol, ENGINE_PY, is defined at\n   tests/active/conftest.py:30. The rest of that conftest was not read, and the test\n   uses no fixture from it.\n```",
        "claim": "CLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (32 clauses: 3 must_prove, 19 docstring, 10 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1 | must_prove | a mixed id/uuid body acquires `db_lock` exactly once | :157, :162 | one lookup per form under separate holds (enters 2), or no lock at all (enters 0); the counter sees both `with` and `acquire()` (:53-61) | CARRIED |\n| C2a | must_prove | each matched video appears once in `rows` | :158, :185 | b1 repeated by its uuid entry and its id entry; an unmatched `u-x` coming back as a placeholder row; `count` disagreeing with the rows | CARRIED |\n| C2b | must_prove | in the order of its first matching entry | :158, :159 | all uuid rows before the id rows (:159 gives [b1, a1]); all id rows first, or SQL/table order (:158 gives [a1, b1]) | CARRIED |\n| D1 | docstring | \"answers a body of id-form and uuid-form entries under one `db_lock` hold\" | :157, :160, :162 | two holds; any statement run outside the hold | CARRIED |\n| D2 | docstring | \"each matched video once, at its first matching entry\" | :158, :159 | a duplicate row; order by form or by table | CARRIED |\n| D3 | docstring | \"`/internal/dislike/centroids` still looks up only id-form entries\" | :205, :207 | uuid entries passed to the embedding lookup | CARRIED |\n| D4 | docstring | \"`[uuid u-b, id a1, id b1, uuid u-a, uuid u-x]` gives exactly `[b1, a1]` with `count == 2`\" | :158 | any other rows, order or count (`_rows` sets count) | CARRIED |\n| D5 | docstring | \"`[id a1, uuid u-x, uuid u-b, id b1]` gives `[a1, b1]`\" | :159 | uuid rows placed first | CARRIED |\n| D6 | docstring | \"each with one lock acquisition and every SQL statement run while that lock is held\" | :157, :160, :162 | a second acquisition; a statement run with the lock free; no statement at all (`== {True}` needs at least one) | CARRIED |\n| D7 | docstring | \"id-only body `[a1, b1, a1]` gives `[a1, b1]` with one acquisition\" | :167, :168 | a1 repeated; more than one acquisition | CARRIED |\n| D8 | docstring | \"valid `video_id` and another video's `video_uuid` gives the id's video\" | :178 | the uuid winning, or both videos coming back | CARRIED |\n| D9 | docstring | \"values are stripped\" | :179, :180 | the padded id, the padded domain (:179) or the padded uuid (:180) matching nothing | CARRIED |\n| D10 | docstring | \"a blank `video_id` beside a valid `video_uuid` gives the uuid's video\" | :180 | a whitespace id counted as present and dropping the entry | CARRIED |\n| D11 | docstring | \"Repeats within a form ... give one row\" | :185, :167 | u-a twice or b1 twice appearing twice | CARRIED |\n| D12 | docstring | \"a video reached by both forms gives one row\" | :185, :158 | a1 via u-a and a1 appearing twice | CARRIED |\n| D13 | docstring | \"uuid entry of a video at `error_count` 5 is omitted at threshold 3\" | :192 | the uuid path ignoring the threshold (u-e is not the last pair, so a threshold that binds only to the last pair also fails) | CARRIED |\n| D14 | docstring | \"returned in its first-match place with no threshold\" | :191, :190 | e1 dropped, or placed after a1 | CARRIED |\n| D15 | docstring | \"`{\"entries\": \"x\"}` gives 400 `Missing entries` without taking the lock\" | :198 | 200/other error; lock taken | CARRIED |\n| D16 | docstring | \"`{}` gives 400 `Missing entries` without taking the lock\" | :199 | same | CARRIED |\n| D17 | docstring | \"a body of only malformed items gives 200 with no rows, without taking the lock\" | :200 | a malformed item accepted (e.g. a uuid with no domain); the lock taken for an empty lookup | CARRIED |\n| D18 | docstring | \"uuid-only body hands the embedding lookup `[]` and gives no centroids\" | :205, :206 | the uuid entry passed through; the lookup skipped (`[]` \u2260 `[[]]`); a centroid for a1 | CARRIED |\n| D19 | docstring | \"mixed body hands it only the id entry and gives that video's unit vector\" | :207, :208 | u-b passed to the lookup; a second centroid from b1's vector | CARRIED |\n| D20 | docstring | \"embedding lookup is spied on, not replaced, and the lock counts every acquisition\" | :53-61, :90 | a hidden `acquire()` not being counted; a stubbed lookup hiding real results (`wraps=`) | CARRIED |\n| N1 | name | test 1: \"a mixed body takes the lock once\" | :157, :162 | two holds | CARRIED |\n| N2 | name | test 1: \"gives each video once in first match order\" | :158, :159 | duplicates; order by form | CARRIED |\n| N3 | name | test 2: \"an id-only body takes the lock once\" | :168 | more than one acquisition | CARRIED |\n| N4 | name | test 2: \"gives its rows in entry order\" | :167 | only a reversed order: entry order a1, b1 is also insertion, rowid and alphabetical order, so a result in table order passes | UNCARRIED |\n| N5 | name | test 3: \"a valid video_id wins over a video_uuid\" | :178 | the uuid winning | CARRIED |\n| N6 | name | test 3: \"a blank one falls back to it\" | :180 | a blank id dropping the entry | CARRIED |\n| N7 | name | test 4: \"repeats within and across forms give one row per video\" | :185 | a repeated row | CARRIED |\n| N8 | name | test 5: \"errored video's uuid entry is omitted only under the threshold\" | :192, :191 | the threshold ignored; the video omitted even with no threshold | CARRIED |\n| N9 | name | test 6: \"no entries list or no valid entry is answered without the lock\" | :198-200 | the lock taken on a rejected or empty body | CARRIED |\n| N10 | name | test 7: \"centroids looks up only the id entries\" | :205, :207 | uuid entries passed to the lookup | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. whole-claim / name-as-sentence (rules/testing.md) \u2014 tests/tmp/test_14_batch_like_resolution_phase2.py:167\n   `assert report[\"responses\"] == _rows(A1, B1)  # C2`\n   N4 is UNCARRIED. The name says \"in entry order\", but a1, b1 is also the fixture's insertion, rowid and alphabetical order. A result in table order passes this assertion. An id-only body in a non-table order, such as `[b1, a1, b1]` \u2192 `[b1, a1]`, would carry it. C2b is still carried for mixed bodies at :158, so this does not block.\n2. bounds (rules/testing.md) \u2014 tests/tmp/test_14_batch_like_resolution_phase2.py:156\n   The lock-once claim (C1) is only exercised with bodies of 4\u20135 entries. `fetch_metadata_by_ids` / `fetch_metadata_by_uuids` split entries into chunks of 450. Nothing tests a mixed body over one chunk, where several SQL statements must share one hold. An explicit empty list `{\"entries\": []}` is also untested (:195-200 test the all-malformed body, not the empty one). No rule makes either one required at this surface.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `code_under_test` lists tests/tmp/test_metadata_uuid_entries.py, and that file does not exist. Nothing from it was assessed.\n2. I did not read `fetch_embeddings_by_ids` (engine/server/data/embeddings.py). D18 and D19 were judged from the spy at :90 and the assertions at :205-208.\n3. `fixtures_path` was not supplied. I checked `ENGINE_PY` in tests/active/conftest.py:30 with a grep, and `db_path` is defined in the test itself (:132). I did not read the rest of that conftest.",
        "body": "### devsecops-test-shape-auditor\n\n```\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. No rule in shape.md covers this \u2014 tests/tmp/test_14_batch_like_resolution_phase2.py:167-168\n   assert report[\"responses\"] == _rows(A1, B1)  # C2\n   assert report[\"enters\"] == 1  # C1\n   These lines carry the C2 and C1 tags, but they hold against the current handler.\n   It parses only id-form entries, deduplicates them, and takes the lock once for\n   them. So this test is a regression control, not the gate for either clause. Both\n   clauses are gated at lines 157-162. The same is true of\n   test_a_body_with_no_entries_list_or_no_valid_entry_is_answered_without_the_lock\n   (lines 198-200), which is not tagged.\n\nPREDICTED FAILURE\nFails at line 157 on the tuple assertion. The current `_parse_entries` drops every\nuuid-form entry, so the first mixed body resolves only ids a1 and b1, in entry order.\nThe observed value is (1, [\"a1\", \"b1\"]); the expected value is (1, [\"b1\", \"a1\"]).\n\nNOT ASSESSED\n1. `code_under_test` listed tests/tmp/test_metadata_uuid_entries.py, which does not\n   resolve (there is no such file under tests/tmp/). The audit covered\n   engine/server/api/handlers/internal_client_reads.py and\n   engine/server/data/metadata.py, found by Grep.\n2. `fixtures_path` was not supplied. The only external symbol, ENGINE_PY, is defined at\n   tests/active/conftest.py:30. The rest of that conftest was not read, and the test\n   uses no fixture from it.\n```\n\n### devsecops-test-claim-auditor\n\nCLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (32 clauses: 3 must_prove, 19 docstring, 10 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1 | must_prove | a mixed id/uuid body acquires `db_lock` exactly once | :157, :162 | one lookup per form under separate holds (enters 2), or no lock at all (enters 0); the counter sees both `with` and `acquire()` (:53-61) | CARRIED |\n| C2a | must_prove | each matched video appears once in `rows` | :158, :185 | b1 repeated by its uuid entry and its id entry; an unmatched `u-x` coming back as a placeholder row; `count` disagreeing with the rows | CARRIED |\n| C2b | must_prove | in the order of its first matching entry | :158, :159 | all uuid rows before the id rows (:159 gives [b1, a1]); all id rows first, or SQL/table order (:158 gives [a1, b1]) | CARRIED |\n| D1 | docstring | \"answers a body of id-form and uuid-form entries under one `db_lock` hold\" | :157, :160, :162 | two holds; any statement run outside the hold | CARRIED |\n| D2 | docstring | \"each matched video once, at its first matching entry\" | :158, :159 | a duplicate row; order by form or by table | CARRIED |\n| D3 | docstring | \"`/internal/dislike/centroids` still looks up only id-form entries\" | :205, :207 | uuid entries passed to the embedding lookup | CARRIED |\n| D4 | docstring | \"`[uuid u-b, id a1, id b1, uuid u-a, uuid u-x]` gives exactly `[b1, a1]` with `count == 2`\" | :158 | any other rows, order or count (`_rows` sets count) | CARRIED |\n| D5 | docstring | \"`[id a1, uuid u-x, uuid u-b, id b1]` gives `[a1, b1]`\" | :159 | uuid rows placed first | CARRIED |\n| D6 | docstring | \"each with one lock acquisition and every SQL statement run while that lock is held\" | :157, :160, :162 | a second acquisition; a statement run with the lock free; no statement at all (`== {True}` needs at least one) | CARRIED |\n| D7 | docstring | \"id-only body `[a1, b1, a1]` gives `[a1, b1]` with one acquisition\" | :167, :168 | a1 repeated; more than one acquisition | CARRIED |\n| D8 | docstring | \"valid `video_id` and another video's `video_uuid` gives the id's video\" | :178 | the uuid winning, or both videos coming back | CARRIED |\n| D9 | docstring | \"values are stripped\" | :179, :180 | the padded id, the padded domain (:179) or the padded uuid (:180) matching nothing | CARRIED |\n| D10 | docstring | \"a blank `video_id` beside a valid `video_uuid` gives the uuid's video\" | :180 | a whitespace id counted as present and dropping the entry | CARRIED |\n| D11 | docstring | \"Repeats within a form ... give one row\" | :185, :167 | u-a twice or b1 twice appearing twice | CARRIED |\n| D12 | docstring | \"a video reached by both forms gives one row\" | :185, :158 | a1 via u-a and a1 appearing twice | CARRIED |\n| D13 | docstring | \"uuid entry of a video at `error_count` 5 is omitted at threshold 3\" | :192 | the uuid path ignoring the threshold (u-e is not the last pair, so a threshold that binds only to the last pair also fails) | CARRIED |\n| D14 | docstring | \"returned in its first-match place with no threshold\" | :191, :190 | e1 dropped, or placed after a1 | CARRIED |\n| D15 | docstring | \"`{\"entries\": \"x\"}` gives 400 `Missing entries` without taking the lock\" | :198 | 200/other error; lock taken | CARRIED |\n| D16 | docstring | \"`{}` gives 400 `Missing entries` without taking the lock\" | :199 | same | CARRIED |\n| D17 | docstring | \"a body of only malformed items gives 200 with no rows, without taking the lock\" | :200 | a malformed item accepted (e.g. a uuid with no domain); the lock taken for an empty lookup | CARRIED |\n| D18 | docstring | \"uuid-only body hands the embedding lookup `[]` and gives no centroids\" | :205, :206 | the uuid entry passed through; the lookup skipped (`[]` \u2260 `[[]]`); a centroid for a1 | CARRIED |\n| D19 | docstring | \"mixed body hands it only the id entry and gives that video's unit vector\" | :207, :208 | u-b passed to the lookup; a second centroid from b1's vector | CARRIED |\n| D20 | docstring | \"embedding lookup is spied on, not replaced, and the lock counts every acquisition\" | :53-61, :90 | a hidden `acquire()` not being counted; a stubbed lookup hiding real results (`wraps=`) | CARRIED |\n| N1 | name | test 1: \"a mixed body takes the lock once\" | :157, :162 | two holds | CARRIED |\n| N2 | name | test 1: \"gives each video once in first match order\" | :158, :159 | duplicates; order by form | CARRIED |\n| N3 | name | test 2: \"an id-only body takes the lock once\" | :168 | more than one acquisition | CARRIED |\n| N4 | name | test 2: \"gives its rows in entry order\" | :167 | only a reversed order: entry order a1, b1 is also insertion, rowid and alphabetical order, so a result in table order passes | UNCARRIED |\n| N5 | name | test 3: \"a valid video_id wins over a video_uuid\" | :178 | the uuid winning | CARRIED |\n| N6 | name | test 3: \"a blank one falls back to it\" | :180 | a blank id dropping the entry | CARRIED |\n| N7 | name | test 4: \"repeats within and across forms give one row per video\" | :185 | a repeated row | CARRIED |\n| N8 | name | test 5: \"errored video's uuid entry is omitted only under the threshold\" | :192, :191 | the threshold ignored; the video omitted even with no threshold | CARRIED |\n| N9 | name | test 6: \"no entries list or no valid entry is answered without the lock\" | :198-200 | the lock taken on a rejected or empty body | CARRIED |\n| N10 | name | test 7: \"centroids looks up only the id entries\" | :205, :207 | uuid entries passed to the lookup | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. whole-claim / name-as-sentence (rules/testing.md) \u2014 tests/tmp/test_14_batch_like_resolution_phase2.py:167\n   `assert report[\"responses\"] == _rows(A1, B1)  # C2`\n   N4 is UNCARRIED. The name says \"in entry order\", but a1, b1 is also the fixture's insertion, rowid and alphabetical order. A result in table order passes this assertion. An id-only body in a non-table order, such as `[b1, a1, b1]` \u2192 `[b1, a1]`, would carry it. C2b is still carried for mixed bodies at :158, so this does not block.\n2. bounds (rules/testing.md) \u2014 tests/tmp/test_14_batch_like_resolution_phase2.py:156\n   The lock-once claim (C1) is only exercised with bodies of 4\u20135 entries. `fetch_metadata_by_ids` / `fetch_metadata_by_uuids` split entries into chunks of 450. Nothing tests a mixed body over one chunk, where several SQL statements must share one hold. An explicit empty list `{\"entries\": []}` is also untested (:195-200 test the all-malformed body, not the empty one). No rule makes either one required at this surface.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `code_under_test` lists tests/tmp/test_metadata_uuid_entries.py, and that file does not exist. Nothing from it was assessed.\n2. I did not read `fetch_embeddings_by_ids` (engine/server/data/embeddings.py). D18 and D19 were judged from the spy at :90 and the assertions at :205-208.\n3. `fixtures_path` was not supplied. I checked `ENGINE_PY` in tests/active/conftest.py:30 with a grep, and `db_path` is defined in the test itself (:132). I did not read the rest of that conftest.",
        "map": [
          {
            "id": "C1",
            "source": "must_prove",
            "clause": "a mixed id/uuid body acquires `db_lock` exactly once",
            "assertion": ":157, :162",
            "excludes": "one lookup per form under separate holds (enters 2), or no lock at all (enters 0); the counter sees both `with` and `acquire()` (:53-61)",
            "status": "CARRIED"
          },
          {
            "id": "C2a",
            "source": "must_prove",
            "clause": "each matched video appears once in `rows`",
            "assertion": ":158, :185",
            "excludes": "b1 repeated by its uuid entry and its id entry; an unmatched `u-x` coming back as a placeholder row; `count` disagreeing with the rows",
            "status": "CARRIED"
          },
          {
            "id": "C2b",
            "source": "must_prove",
            "clause": "in the order of its first matching entry",
            "assertion": ":158, :159",
            "excludes": "all uuid rows before the id rows (:159 gives [b1, a1]); all id rows first, or SQL/table order (:158 gives [a1, b1])",
            "status": "CARRIED"
          },
          {
            "id": "D1",
            "source": "docstring",
            "clause": "\"answers a body of id-form and uuid-form entries under one `db_lock` hold\"",
            "assertion": ":157, :160, :162",
            "excludes": "two holds; any statement run outside the hold",
            "status": "CARRIED"
          },
          {
            "id": "D2",
            "source": "docstring",
            "clause": "\"each matched video once, at its first matching entry\"",
            "assertion": ":158, :159",
            "excludes": "a duplicate row; order by form or by table",
            "status": "CARRIED"
          },
          {
            "id": "D3",
            "source": "docstring",
            "clause": "\"`/internal/dislike/centroids` still looks up only id-form entries\"",
            "assertion": ":205, :207",
            "excludes": "uuid entries passed to the embedding lookup",
            "status": "CARRIED"
          },
          {
            "id": "D4",
            "source": "docstring",
            "clause": "\"`[uuid u-b, id a1, id b1, uuid u-a, uuid u-x]` gives exactly `[b1, a1]` with `count == 2`\"",
            "assertion": ":158",
            "excludes": "any other rows, order or count (`_rows` sets count)",
            "status": "CARRIED"
          },
          {
            "id": "D5",
            "source": "docstring",
            "clause": "\"`[id a1, uuid u-x, uuid u-b, id b1]` gives `[a1, b1]`\"",
            "assertion": ":159",
            "excludes": "uuid rows placed first",
            "status": "CARRIED"
          },
          {
            "id": "D6",
            "source": "docstring",
            "clause": "\"each with one lock acquisition and every SQL statement run while that lock is held\"",
            "assertion": ":157, :160, :162",
            "excludes": "a second acquisition; a statement run with the lock free; no statement at all (`== {True}` needs at least one)",
            "status": "CARRIED"
          },
          {
            "id": "D7",
            "source": "docstring",
            "clause": "\"id-only body `[a1, b1, a1]` gives `[a1, b1]` with one acquisition\"",
            "assertion": ":167, :168",
            "excludes": "a1 repeated; more than one acquisition",
            "status": "CARRIED"
          },
          {
            "id": "D8",
            "source": "docstring",
            "clause": "\"valid `video_id` and another video's `video_uuid` gives the id's video\"",
            "assertion": ":178",
            "excludes": "the uuid winning, or both videos coming back",
            "status": "CARRIED"
          },
          {
            "id": "D9",
            "source": "docstring",
            "clause": "\"values are stripped\"",
            "assertion": ":179, :180",
            "excludes": "the padded id, the padded domain (:179) or the padded uuid (:180) matching nothing",
            "status": "CARRIED"
          },
          {
            "id": "D10",
            "source": "docstring",
            "clause": "\"a blank `video_id` beside a valid `video_uuid` gives the uuid's video\"",
            "assertion": ":180",
            "excludes": "a whitespace id counted as present and dropping the entry",
            "status": "CARRIED"
          },
          {
            "id": "D11",
            "source": "docstring",
            "clause": "\"Repeats within a form ... give one row\"",
            "assertion": ":185, :167",
            "excludes": "u-a twice or b1 twice appearing twice",
            "status": "CARRIED"
          },
          {
            "id": "D12",
            "source": "docstring",
            "clause": "\"a video reached by both forms gives one row\"",
            "assertion": ":185, :158",
            "excludes": "a1 via u-a and a1 appearing twice",
            "status": "CARRIED"
          },
          {
            "id": "D13",
            "source": "docstring",
            "clause": "\"uuid entry of a video at `error_count` 5 is omitted at threshold 3\"",
            "assertion": ":192",
            "excludes": "the uuid path ignoring the threshold (u-e is not the last pair, so a threshold that binds only to the last pair also fails)",
            "status": "CARRIED"
          },
          {
            "id": "D14",
            "source": "docstring",
            "clause": "\"returned in its first-match place with no threshold\"",
            "assertion": ":191, :190",
            "excludes": "e1 dropped, or placed after a1",
            "status": "CARRIED"
          },
          {
            "id": "D15",
            "source": "docstring",
            "clause": "\"`{\"entries\": \"x\"}` gives 400 `Missing entries` without taking the lock\"",
            "assertion": ":198",
            "excludes": "200/other error; lock taken",
            "status": "CARRIED"
          },
          {
            "id": "D16",
            "source": "docstring",
            "clause": "\"`{}` gives 400 `Missing entries` without taking the lock\"",
            "assertion": ":199",
            "excludes": "same",
            "status": "CARRIED"
          },
          {
            "id": "D17",
            "source": "docstring",
            "clause": "\"a body of only malformed items gives 200 with no rows, without taking the lock\"",
            "assertion": ":200",
            "excludes": "a malformed item accepted (e.g. a uuid with no domain); the lock taken for an empty lookup",
            "status": "CARRIED"
          },
          {
            "id": "D18",
            "source": "docstring",
            "clause": "\"uuid-only body hands the embedding lookup `[]` and gives no centroids\"",
            "assertion": ":205, :206",
            "excludes": "the uuid entry passed through; the lookup skipped (`[]` \u2260 `[[]]`); a centroid for a1",
            "status": "CARRIED"
          },
          {
            "id": "D19",
            "source": "docstring",
            "clause": "\"mixed body hands it only the id entry and gives that video's unit vector\"",
            "assertion": ":207, :208",
            "excludes": "u-b passed to the lookup; a second centroid from b1's vector",
            "status": "CARRIED"
          },
          {
            "id": "D20",
            "source": "docstring",
            "clause": "\"embedding lookup is spied on, not replaced, and the lock counts every acquisition\"",
            "assertion": ":53-61, :90",
            "excludes": "a hidden `acquire()` not being counted; a stubbed lookup hiding real results (`wraps=`)",
            "status": "CARRIED"
          },
          {
            "id": "N1",
            "source": "name",
            "clause": "test 1: \"a mixed body takes the lock once\"",
            "assertion": ":157, :162",
            "excludes": "two holds",
            "status": "CARRIED"
          },
          {
            "id": "N2",
            "source": "name",
            "clause": "test 1: \"gives each video once in first match order\"",
            "assertion": ":158, :159",
            "excludes": "duplicates; order by form",
            "status": "CARRIED"
          },
          {
            "id": "N3",
            "source": "name",
            "clause": "test 2: \"an id-only body takes the lock once\"",
            "assertion": ":168",
            "excludes": "more than one acquisition",
            "status": "CARRIED"
          },
          {
            "id": "N4",
            "source": "name",
            "clause": "test 2: \"gives its rows in entry order\"",
            "assertion": ":167",
            "excludes": "only a reversed order: entry order a1, b1 is also insertion, rowid and alphabetical order, so a result in table order passes",
            "status": "UNCARRIED"
          },
          {
            "id": "N5",
            "source": "name",
            "clause": "test 3: \"a valid video_id wins over a video_uuid\"",
            "assertion": ":178",
            "excludes": "the uuid winning",
            "status": "CARRIED"
          },
          {
            "id": "N6",
            "source": "name",
            "clause": "test 3: \"a blank one falls back to it\"",
            "assertion": ":180",
            "excludes": "a blank id dropping the entry",
            "status": "CARRIED"
          },
          {
            "id": "N7",
            "source": "name",
            "clause": "test 4: \"repeats within and across forms give one row per video\"",
            "assertion": ":185",
            "excludes": "a repeated row",
            "status": "CARRIED"
          },
          {
            "id": "N8",
            "source": "name",
            "clause": "test 5: \"errored video's uuid entry is omitted only under the threshold\"",
            "assertion": ":192, :191",
            "excludes": "the threshold ignored; the video omitted even with no threshold",
            "status": "CARRIED"
          },
          {
            "id": "N9",
            "source": "name",
            "clause": "test 6: \"no entries list or no valid entry is answered without the lock\"",
            "assertion": ":198-200",
            "excludes": "the lock taken on a rejected or empty body",
            "status": "CARRIED"
          },
          {
            "id": "N10",
            "source": "name",
            "clause": "test 7: \"centroids looks up only the id entries\"",
            "assertion": ":205, :207",
            "excludes": "uuid entries passed to the lookup",
            "status": "CARRIED"
          }
        ],
        "map_problem": ""
      },
      {
        "shape": "SHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\ntest_a_mixed_body_takes_the_lock_once_and_gives_each_video_once_in_first_match_order should fail at tests/tmp/test_14_batch_like_resolution_phase2.py:157. The tuple assertion should get `(1, [\"a1\", \"b1\"])` where it expects `(1, [\"b1\", \"a1\"])`. This is because `_parse_entries` (internal_client_reads.py:35) skips every entry that has no `video_id`, so the `u-b` entry never resolves and the rows follow the id-form entries only.\n\nOther tests in the file, against the code as it stands:\n- :185 should fail with `[b1, a1]` returned where `_rows(A1, B1)` is expected.\n- :180 should fail with `NO_ROWS` returned where `_rows(B1)` is expected.\n- :191 should fail with `NO_ROWS` returned where `_rows(E1, A1)` is expected.\n- :167\u2013168, :198\u2013200 and :205\u2013208 should stay green. They check behaviour that already holds and are meant to keep holding.\n\nNOT ASSESSED\n1. `code_under_test` listed tests/tmp/test_metadata_uuid_entries.py, which does not exist. Nothing the test depends on was checked against it.\n2. No `fixtures_path` was supplied. `ENGINE_PY` was traced by Grep to tests/active/conftest.py:30 and nothing more in that conftest was read. The test defines its only fixture, `db_path`, itself at :132.\n3. `code_under_test` marks engine/server/api/handlers/internal_client_reads.py as EDITED, but the file as read has no uuid-form handling in `handle_internal_videos_metadata` (:95\u2013126). The predicted failure is based on the file as read.",
        "claim": "CLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (33 clauses: 3 must_prove, 20 docstring, 10 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1 | must_prove | a mixed id/uuid body acquires `db_lock` exactly once | :157, :162 | one lookup per form under its own hold (enters 2), or no lock at all (enters 0). The counter sees both `with` and `acquire()` (:53-61). Both mixed orderings are checked | CARRIED |\n| C2a | must_prove | each matched video appears once in `rows` | :158, :185 | b1 repeated by its uuid entry and its id entry; the unmatched `u-x` coming back as a placeholder row; `count` disagreeing with the rows | CARRIED |\n| C2b | must_prove | in the order of its first matching entry | :158, :159 | all uuid rows before the id rows (:159 needs [a1, b1]); all id rows first, or SQL/table order (:158 needs [b1, a1]) | CARRIED |\n| D1 | docstring | \"answers a body of id-form and uuid-form entries under one `db_lock` hold\" | :157, :160, :162 | two holds; any statement run outside the hold | CARRIED |\n| D2 | docstring | \"each matched video once, at its first matching entry\" | :158, :159 | a duplicate row; rows ordered by form or by table | CARRIED |\n| D3 | docstring | \"`/internal/dislikes/centroids` still looks up only id-form entries\" | :205, :207 | uuid entries passed to the embedding lookup | CARRIED |\n| D4 | docstring | \"`[uuid u-b, id a1, id b1, uuid u-a, uuid u-x]` gives exactly `[b1, a1]` with `count == 2`\" | :158 | any other rows, order or count (`_rows` sets count, :129) | CARRIED |\n| D5 | docstring | \"`[id a1, uuid u-x, uuid u-b, id b1]` gives `[a1, b1]`\" | :159 | uuid rows placed first | CARRIED |\n| D6 | docstring | \"each with one lock acquisition and every SQL statement run while that lock is held\" | :157, :160, :162 | a second acquisition; a statement run with the lock free; no statement at all (`== {True}` needs at least one) | CARRIED |\n| D7 | docstring | \"id-only body `[b1, a1, b1]` gives `[b1, a1]` with one acquisition\" | :167, :168 | b1 repeated; rows in table/rowid/alphabetical order (would give [a1, b1]); more than one acquisition | CARRIED |\n| D8 | docstring | \"valid `video_id` and another video's `video_uuid` gives the id's video\" | :178 | the uuid winning, or both videos coming back | CARRIED |\n| D9 | docstring | \"values are stripped\" | :179, :180 | the padded id or padded domain (:179), or the padded uuid (:180), matching nothing | CARRIED |\n| D10 | docstring | \"a blank `video_id` beside a valid `video_uuid` gives the uuid's video\" | :180 | a whitespace id counted as present and dropping the entry | CARRIED |\n| D11 | docstring | \"Repeats within a form ... give one row\" | :185, :167 | u-a twice or b1 twice appearing twice | CARRIED |\n| D12 | docstring | \"a video reached by both forms gives one row\" | :185, :158 | a1 reached by u-a and by id appearing twice | CARRIED |\n| D13 | docstring | \"uuid entry of a video at `error_count` 5 is omitted at threshold 3\" | :192 | the uuid path ignoring the threshold (u-e is not the last pair) | CARRIED |\n| D14 | docstring | \"returned in its first-match place with no threshold\" | :191, :190 | e1 dropped, or placed after a1 | CARRIED |\n| D15 | docstring | \"`{\"entries\": \"x\"}` gives 400 `Missing entries` without taking the lock\" | :198 | a 200 or a different error; the lock taken | CARRIED |\n| D16 | docstring | \"`{}` gives 400 `Missing entries` without taking the lock\" | :199 | same as D15 | CARRIED |\n| D17 | docstring | \"a body of only malformed items gives 200 with no rows, without taking the lock\" | :200 | a malformed item accepted (for example a uuid with no domain, or an int domain); the lock taken for an empty lookup | CARRIED |\n| D18 | docstring | \"uuid-only body hands the embedding lookup `[]` and gives no centroids\" | :205, :206 | the uuid entry passed through; the lookup skipped (`[]` \u2260 `[[]]`); a centroid for a1 | CARRIED |\n| D19 | docstring | \"mixed body hands it only the id entry and gives that video's unit vector\" | :207, :208 | u-b passed to the lookup; a second centroid from b1's vector | CARRIED |\n| D20 | docstring | \"embedding lookup is spied on, not replaced, and the lock counts every acquisition\" | :53-61, :90 | a hidden `acquire()` going uncounted; a stubbed lookup hiding real results (`wraps=`) | CARRIED |\n| N1 | name | test 1: \"a mixed body takes the lock once\" | :157, :162 | two holds | CARRIED |\n| N2 | name | test 1: \"gives each video once in first match order\" | :158, :159 | duplicates; rows ordered by form | CARRIED |\n| N3 | name | test 2: \"an id-only body takes the lock once\" | :168 | more than one acquisition | CARRIED |\n| N4 | name | test 2: \"gives its rows in entry order\" | :167 | table order. The body is now `[b1, a1, b1]` against a fixture inserted a1, b1, e1, so insertion, rowid and alphabetical order all give [a1, b1] and fail | CARRIED |\n| N5 | name | test 3: \"a valid video_id wins over a video_uuid\" | :178 | the uuid winning | CARRIED |\n| N6 | name | test 3: \"a blank one falls back to it\" | :180 | a blank id dropping the entry | CARRIED |\n| N7 | name | test 4: \"repeats within and across forms give one row per video\" | :185 | a repeated row | CARRIED |\n| N8 | name | test 5: \"errored video's uuid entry is omitted only under the threshold\" | :192, :191 | the threshold ignored; the video omitted even with no threshold | CARRIED |\n| N9 | name | test 6: \"no entries list or no valid entry is answered without the lock\" | :198-200 | the lock taken on a rejected or empty body | CARRIED |\n| N10 | name | test 7: \"centroids looks up only the id entries\" | :205, :207 | uuid entries passed to the lookup | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nOBSERVATIONS\n1. whole-claim (rules/testing.md) \u2014 tests/tmp/test_14_batch_like_resolution_phase2.py:3, :166\n   N4 is now carried because the assertion changed, not because the prose was narrowed. The id-only body is now `[_id(\"b1\"), _id(\"a1\"), _id(\"b1\")]` (:166), and :167 expects `_rows(B1, A1)`, which a result in table order fails. The docstring's D7 sentence was rewritten to match (`[b1, a1, b1]` gives `[b1, a1]`, where round one had `[a1, b1, a1]` gives `[a1, b1]`). The clause is the same, restated for the new input, and it is carried.\n2. tests/tmp/test_14_batch_like_resolution_phase2.py:1\n   The D3 route is now spelled `/internal/dislikes/centroids`, where the ledger has `/internal/dislike/centroids`. The test calls the handler function directly (:80), so the route string is prose only. Neither spelling is checked against a route table here.\n\nNOT ASSESSED\n1. `code_under_test` lists tests/tmp/test_metadata_uuid_entries.py, which does not resolve (FileNotFoundError). No clause here depends on it.\n2. `data.metadata.fetch_metadata_by_ids` and `data.embeddings.fetch_embeddings_by_ids` are not in `code_under_test` and were not read. The threshold and ordering exclusions were judged from the test's fixture data (:140-142) and its expected rows, not from the lookup code.\n3. `conftest.ENGINE_PY` (tests/active/conftest.py, imported at :26) was not read. The test uses it only as the path to the Engine's interpreter, not as a fixture that sets up state.",
        "body": "### devsecops-test-shape-auditor\n\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\ntest_a_mixed_body_takes_the_lock_once_and_gives_each_video_once_in_first_match_order should fail at tests/tmp/test_14_batch_like_resolution_phase2.py:157. The tuple assertion should get `(1, [\"a1\", \"b1\"])` where it expects `(1, [\"b1\", \"a1\"])`. This is because `_parse_entries` (internal_client_reads.py:35) skips every entry that has no `video_id`, so the `u-b` entry never resolves and the rows follow the id-form entries only.\n\nOther tests in the file, against the code as it stands:\n- :185 should fail with `[b1, a1]` returned where `_rows(A1, B1)` is expected.\n- :180 should fail with `NO_ROWS` returned where `_rows(B1)` is expected.\n- :191 should fail with `NO_ROWS` returned where `_rows(E1, A1)` is expected.\n- :167\u2013168, :198\u2013200 and :205\u2013208 should stay green. They check behaviour that already holds and are meant to keep holding.\n\nNOT ASSESSED\n1. `code_under_test` listed tests/tmp/test_metadata_uuid_entries.py, which does not exist. Nothing the test depends on was checked against it.\n2. No `fixtures_path` was supplied. `ENGINE_PY` was traced by Grep to tests/active/conftest.py:30 and nothing more in that conftest was read. The test defines its only fixture, `db_path`, itself at :132.\n3. `code_under_test` marks engine/server/api/handlers/internal_client_reads.py as EDITED, but the file as read has no uuid-form handling in `handle_internal_videos_metadata` (:95\u2013126). The predicted failure is based on the file as read.\n\n### devsecops-test-claim-auditor\n\nCLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (33 clauses: 3 must_prove, 20 docstring, 10 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1 | must_prove | a mixed id/uuid body acquires `db_lock` exactly once | :157, :162 | one lookup per form under its own hold (enters 2), or no lock at all (enters 0). The counter sees both `with` and `acquire()` (:53-61). Both mixed orderings are checked | CARRIED |\n| C2a | must_prove | each matched video appears once in `rows` | :158, :185 | b1 repeated by its uuid entry and its id entry; the unmatched `u-x` coming back as a placeholder row; `count` disagreeing with the rows | CARRIED |\n| C2b | must_prove | in the order of its first matching entry | :158, :159 | all uuid rows before the id rows (:159 needs [a1, b1]); all id rows first, or SQL/table order (:158 needs [b1, a1]) | CARRIED |\n| D1 | docstring | \"answers a body of id-form and uuid-form entries under one `db_lock` hold\" | :157, :160, :162 | two holds; any statement run outside the hold | CARRIED |\n| D2 | docstring | \"each matched video once, at its first matching entry\" | :158, :159 | a duplicate row; rows ordered by form or by table | CARRIED |\n| D3 | docstring | \"`/internal/dislikes/centroids` still looks up only id-form entries\" | :205, :207 | uuid entries passed to the embedding lookup | CARRIED |\n| D4 | docstring | \"`[uuid u-b, id a1, id b1, uuid u-a, uuid u-x]` gives exactly `[b1, a1]` with `count == 2`\" | :158 | any other rows, order or count (`_rows` sets count, :129) | CARRIED |\n| D5 | docstring | \"`[id a1, uuid u-x, uuid u-b, id b1]` gives `[a1, b1]`\" | :159 | uuid rows placed first | CARRIED |\n| D6 | docstring | \"each with one lock acquisition and every SQL statement run while that lock is held\" | :157, :160, :162 | a second acquisition; a statement run with the lock free; no statement at all (`== {True}` needs at least one) | CARRIED |\n| D7 | docstring | \"id-only body `[b1, a1, b1]` gives `[b1, a1]` with one acquisition\" | :167, :168 | b1 repeated; rows in table/rowid/alphabetical order (would give [a1, b1]); more than one acquisition | CARRIED |\n| D8 | docstring | \"valid `video_id` and another video's `video_uuid` gives the id's video\" | :178 | the uuid winning, or both videos coming back | CARRIED |\n| D9 | docstring | \"values are stripped\" | :179, :180 | the padded id or padded domain (:179), or the padded uuid (:180), matching nothing | CARRIED |\n| D10 | docstring | \"a blank `video_id` beside a valid `video_uuid` gives the uuid's video\" | :180 | a whitespace id counted as present and dropping the entry | CARRIED |\n| D11 | docstring | \"Repeats within a form ... give one row\" | :185, :167 | u-a twice or b1 twice appearing twice | CARRIED |\n| D12 | docstring | \"a video reached by both forms gives one row\" | :185, :158 | a1 reached by u-a and by id appearing twice | CARRIED |\n| D13 | docstring | \"uuid entry of a video at `error_count` 5 is omitted at threshold 3\" | :192 | the uuid path ignoring the threshold (u-e is not the last pair) | CARRIED |\n| D14 | docstring | \"returned in its first-match place with no threshold\" | :191, :190 | e1 dropped, or placed after a1 | CARRIED |\n| D15 | docstring | \"`{\"entries\": \"x\"}` gives 400 `Missing entries` without taking the lock\" | :198 | a 200 or a different error; the lock taken | CARRIED |\n| D16 | docstring | \"`{}` gives 400 `Missing entries` without taking the lock\" | :199 | same as D15 | CARRIED |\n| D17 | docstring | \"a body of only malformed items gives 200 with no rows, without taking the lock\" | :200 | a malformed item accepted (for example a uuid with no domain, or an int domain); the lock taken for an empty lookup | CARRIED |\n| D18 | docstring | \"uuid-only body hands the embedding lookup `[]` and gives no centroids\" | :205, :206 | the uuid entry passed through; the lookup skipped (`[]` \u2260 `[[]]`); a centroid for a1 | CARRIED |\n| D19 | docstring | \"mixed body hands it only the id entry and gives that video's unit vector\" | :207, :208 | u-b passed to the lookup; a second centroid from b1's vector | CARRIED |\n| D20 | docstring | \"embedding lookup is spied on, not replaced, and the lock counts every acquisition\" | :53-61, :90 | a hidden `acquire()` going uncounted; a stubbed lookup hiding real results (`wraps=`) | CARRIED |\n| N1 | name | test 1: \"a mixed body takes the lock once\" | :157, :162 | two holds | CARRIED |\n| N2 | name | test 1: \"gives each video once in first match order\" | :158, :159 | duplicates; rows ordered by form | CARRIED |\n| N3 | name | test 2: \"an id-only body takes the lock once\" | :168 | more than one acquisition | CARRIED |\n| N4 | name | test 2: \"gives its rows in entry order\" | :167 | table order. The body is now `[b1, a1, b1]` against a fixture inserted a1, b1, e1, so insertion, rowid and alphabetical order all give [a1, b1] and fail | CARRIED |\n| N5 | name | test 3: \"a valid video_id wins over a video_uuid\" | :178 | the uuid winning | CARRIED |\n| N6 | name | test 3: \"a blank one falls back to it\" | :180 | a blank id dropping the entry | CARRIED |\n| N7 | name | test 4: \"repeats within and across forms give one row per video\" | :185 | a repeated row | CARRIED |\n| N8 | name | test 5: \"errored video's uuid entry is omitted only under the threshold\" | :192, :191 | the threshold ignored; the video omitted even with no threshold | CARRIED |\n| N9 | name | test 6: \"no entries list or no valid entry is answered without the lock\" | :198-200 | the lock taken on a rejected or empty body | CARRIED |\n| N10 | name | test 7: \"centroids looks up only the id entries\" | :205, :207 | uuid entries passed to the lookup | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nOBSERVATIONS\n1. whole-claim (rules/testing.md) \u2014 tests/tmp/test_14_batch_like_resolution_phase2.py:3, :166\n   N4 is now carried because the assertion changed, not because the prose was narrowed. The id-only body is now `[_id(\"b1\"), _id(\"a1\"), _id(\"b1\")]` (:166), and :167 expects `_rows(B1, A1)`, which a result in table order fails. The docstring's D7 sentence was rewritten to match (`[b1, a1, b1]` gives `[b1, a1]`, where round one had `[a1, b1, a1]` gives `[a1, b1]`). The clause is the same, restated for the new input, and it is carried.\n2. tests/tmp/test_14_batch_like_resolution_phase2.py:1\n   The D3 route is now spelled `/internal/dislikes/centroids`, where the ledger has `/internal/dislike/centroids`. The test calls the handler function directly (:80), so the route string is prose only. Neither spelling is checked against a route table here.\n\nNOT ASSESSED\n1. `code_under_test` lists tests/tmp/test_metadata_uuid_entries.py, which does not resolve (FileNotFoundError). No clause here depends on it.\n2. `data.metadata.fetch_metadata_by_ids` and `data.embeddings.fetch_embeddings_by_ids` are not in `code_under_test` and were not read. The threshold and ordering exclusions were judged from the test's fixture data (:140-142) and its expected rows, not from the lookup code.\n3. `conftest.ENGINE_PY` (tests/active/conftest.py, imported at :26) was not read. The test uses it only as the path to the Engine's interpreter, not as a fixture that sets up state.",
        "map": [
          {
            "id": "C1",
            "source": "must_prove",
            "clause": "a mixed id/uuid body acquires `db_lock` exactly once",
            "assertion": ":157, :162",
            "excludes": "one lookup per form under its own hold (enters 2), or no lock at all (enters 0). The counter sees both `with` and `acquire()` (:53-61). Both mixed orderings are checked",
            "status": "CARRIED"
          },
          {
            "id": "C2a",
            "source": "must_prove",
            "clause": "each matched video appears once in `rows`",
            "assertion": ":158, :185",
            "excludes": "b1 repeated by its uuid entry and its id entry; the unmatched `u-x` coming back as a placeholder row; `count` disagreeing with the rows",
            "status": "CARRIED"
          },
          {
            "id": "C2b",
            "source": "must_prove",
            "clause": "in the order of its first matching entry",
            "assertion": ":158, :159",
            "excludes": "all uuid rows before the id rows (:159 needs [a1, b1]); all id rows first, or SQL/table order (:158 needs [b1, a1])",
            "status": "CARRIED"
          },
          {
            "id": "D1",
            "source": "docstring",
            "clause": "\"answers a body of id-form and uuid-form entries under one `db_lock` hold\"",
            "assertion": ":157, :160, :162",
            "excludes": "two holds; any statement run outside the hold",
            "status": "CARRIED"
          },
          {
            "id": "D2",
            "source": "docstring",
            "clause": "\"each matched video once, at its first matching entry\"",
            "assertion": ":158, :159",
            "excludes": "a duplicate row; rows ordered by form or by table",
            "status": "CARRIED"
          },
          {
            "id": "D3",
            "source": "docstring",
            "clause": "\"`/internal/dislikes/centroids` still looks up only id-form entries\"",
            "assertion": ":205, :207",
            "excludes": "uuid entries passed to the embedding lookup",
            "status": "CARRIED"
          },
          {
            "id": "D4",
            "source": "docstring",
            "clause": "\"`[uuid u-b, id a1, id b1, uuid u-a, uuid u-x]` gives exactly `[b1, a1]` with `count == 2`\"",
            "assertion": ":158",
            "excludes": "any other rows, order or count (`_rows` sets count, :129)",
            "status": "CARRIED"
          },
          {
            "id": "D5",
            "source": "docstring",
            "clause": "\"`[id a1, uuid u-x, uuid u-b, id b1]` gives `[a1, b1]`\"",
            "assertion": ":159",
            "excludes": "uuid rows placed first",
            "status": "CARRIED"
          },
          {
            "id": "D6",
            "source": "docstring",
            "clause": "\"each with one lock acquisition and every SQL statement run while that lock is held\"",
            "assertion": ":157, :160, :162",
            "excludes": "a second acquisition; a statement run with the lock free; no statement at all (`== {True}` needs at least one)",
            "status": "CARRIED"
          },
          {
            "id": "D7",
            "source": "docstring",
            "clause": "\"id-only body `[b1, a1, b1]` gives `[b1, a1]` with one acquisition\"",
            "assertion": ":167, :168",
            "excludes": "b1 repeated; rows in table/rowid/alphabetical order (would give [a1, b1]); more than one acquisition",
            "status": "CARRIED"
          },
          {
            "id": "D8",
            "source": "docstring",
            "clause": "\"valid `video_id` and another video's `video_uuid` gives the id's video\"",
            "assertion": ":178",
            "excludes": "the uuid winning, or both videos coming back",
            "status": "CARRIED"
          },
          {
            "id": "D9",
            "source": "docstring",
            "clause": "\"values are stripped\"",
            "assertion": ":179, :180",
            "excludes": "the padded id or padded domain (:179), or the padded uuid (:180), matching nothing",
            "status": "CARRIED"
          },
          {
            "id": "D10",
            "source": "docstring",
            "clause": "\"a blank `video_id` beside a valid `video_uuid` gives the uuid's video\"",
            "assertion": ":180",
            "excludes": "a whitespace id counted as present and dropping the entry",
            "status": "CARRIED"
          },
          {
            "id": "D11",
            "source": "docstring",
            "clause": "\"Repeats within a form ... give one row\"",
            "assertion": ":185, :167",
            "excludes": "u-a twice or b1 twice appearing twice",
            "status": "CARRIED"
          },
          {
            "id": "D12",
            "source": "docstring",
            "clause": "\"a video reached by both forms gives one row\"",
            "assertion": ":185, :158",
            "excludes": "a1 reached by u-a and by id appearing twice",
            "status": "CARRIED"
          },
          {
            "id": "D13",
            "source": "docstring",
            "clause": "\"uuid entry of a video at `error_count` 5 is omitted at threshold 3\"",
            "assertion": ":192",
            "excludes": "the uuid path ignoring the threshold (u-e is not the last pair)",
            "status": "CARRIED"
          },
          {
            "id": "D14",
            "source": "docstring",
            "clause": "\"returned in its first-match place with no threshold\"",
            "assertion": ":191, :190",
            "excludes": "e1 dropped, or placed after a1",
            "status": "CARRIED"
          },
          {
            "id": "D15",
            "source": "docstring",
            "clause": "\"`{\"entries\": \"x\"}` gives 400 `Missing entries` without taking the lock\"",
            "assertion": ":198",
            "excludes": "a 200 or a different error; the lock taken",
            "status": "CARRIED"
          },
          {
            "id": "D16",
            "source": "docstring",
            "clause": "\"`{}` gives 400 `Missing entries` without taking the lock\"",
            "assertion": ":199",
            "excludes": "same as D15",
            "status": "CARRIED"
          },
          {
            "id": "D17",
            "source": "docstring",
            "clause": "\"a body of only malformed items gives 200 with no rows, without taking the lock\"",
            "assertion": ":200",
            "excludes": "a malformed item accepted (for example a uuid with no domain, or an int domain); the lock taken for an empty lookup",
            "status": "CARRIED"
          },
          {
            "id": "D18",
            "source": "docstring",
            "clause": "\"uuid-only body hands the embedding lookup `[]` and gives no centroids\"",
            "assertion": ":205, :206",
            "excludes": "the uuid entry passed through; the lookup skipped (`[]` \u2260 `[[]]`); a centroid for a1",
            "status": "CARRIED"
          },
          {
            "id": "D19",
            "source": "docstring",
            "clause": "\"mixed body hands it only the id entry and gives that video's unit vector\"",
            "assertion": ":207, :208",
            "excludes": "u-b passed to the lookup; a second centroid from b1's vector",
            "status": "CARRIED"
          },
          {
            "id": "D20",
            "source": "docstring",
            "clause": "\"embedding lookup is spied on, not replaced, and the lock counts every acquisition\"",
            "assertion": ":53-61, :90",
            "excludes": "a hidden `acquire()` going uncounted; a stubbed lookup hiding real results (`wraps=`)",
            "status": "CARRIED"
          },
          {
            "id": "N1",
            "source": "name",
            "clause": "test 1: \"a mixed body takes the lock once\"",
            "assertion": ":157, :162",
            "excludes": "two holds",
            "status": "CARRIED"
          },
          {
            "id": "N2",
            "source": "name",
            "clause": "test 1: \"gives each video once in first match order\"",
            "assertion": ":158, :159",
            "excludes": "duplicates; rows ordered by form",
            "status": "CARRIED"
          },
          {
            "id": "N3",
            "source": "name",
            "clause": "test 2: \"an id-only body takes the lock once\"",
            "assertion": ":168",
            "excludes": "more than one acquisition",
            "status": "CARRIED"
          },
          {
            "id": "N4",
            "source": "name",
            "clause": "test 2: \"gives its rows in entry order\"",
            "assertion": ":167",
            "excludes": "table order. The body is now `[b1, a1, b1]` against a fixture inserted a1, b1, e1, so insertion, rowid and alphabetical order all give [a1, b1] and fail",
            "status": "CARRIED"
          },
          {
            "id": "N5",
            "source": "name",
            "clause": "test 3: \"a valid video_id wins over a video_uuid\"",
            "assertion": ":178",
            "excludes": "the uuid winning",
            "status": "CARRIED"
          },
          {
            "id": "N6",
            "source": "name",
            "clause": "test 3: \"a blank one falls back to it\"",
            "assertion": ":180",
            "excludes": "a blank id dropping the entry",
            "status": "CARRIED"
          },
          {
            "id": "N7",
            "source": "name",
            "clause": "test 4: \"repeats within and across forms give one row per video\"",
            "assertion": ":185",
            "excludes": "a repeated row",
            "status": "CARRIED"
          },
          {
            "id": "N8",
            "source": "name",
            "clause": "test 5: \"errored video's uuid entry is omitted only under the threshold\"",
            "assertion": ":192, :191",
            "excludes": "the threshold ignored; the video omitted even with no threshold",
            "status": "CARRIED"
          },
          {
            "id": "N9",
            "source": "name",
            "clause": "test 6: \"no entries list or no valid entry is answered without the lock\"",
            "assertion": ":198-200",
            "excludes": "the lock taken on a rejected or empty body",
            "status": "CARRIED"
          },
          {
            "id": "N10",
            "source": "name",
            "clause": "test 7: \"centroids looks up only the id entries\"",
            "assertion": ":205, :207",
            "excludes": "uuid entries passed to the lookup",
            "status": "CARRIED"
          }
        ],
        "map_problem": ""
      }
    ],
    "tests/tmp/test_14_batch_like_resolution_phase3.py": [
      {
        "shape": "```\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\nFails at tests/tmp/test_14_batch_like_resolution_phase3.py:109. The assertion `received == [(METADATA, {\"entries\": [...]})]`\nfinds `[(\"/internal/videos/resolve\", {\"host\": \"h.example\", \"uuid\": \"u-c\"})]` instead.\n`resolve_videos_by_uuid_host` still calls `/internal/videos/resolve` once per like, the stand-in's\nreply has no `video`, and the Client answers 502 before any metadata call. The same wrong\nrequest list fails line 121 of the empty-body test and line 140 of the import test.\n\nNOT ASSESSED\n1. `code_under_test` listed tests/tmp/test_client_like_batching.py (NEW), which does not resolve.\n   It was not read, and the verdict does not depend on it.\n2. `fixtures_path` was not supplied. The test imports `ClientBackend`, `RateLimiter`, `client_server`\n   and `ensure_user_schema` from tests/active/conftest.py (line 22), which was read. It builds its own\n   Engine stand-in and Client server and uses no conftest fixture.\n```",
        "claim": "CLAIM AUDIT \u2014 VERDICT: PASS\n\n```\nCLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (22 clauses: 4 must_prove, 12 docstring, 6 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | a likes-page request causes exactly one Engine HTTP call | :109 | a per-like resolve loop, or any second call before or after the batch. The whole record is compared by equality, not by membership | CARRIED |\n| C1b | must_prove | the likes-page call is to `/internal/videos/metadata` | :109 | the batch sent to any other route, e.g. `/internal/videos/resolve` | CARRIED |\n| C1c | must_prove | a likes-import request causes exactly one Engine HTTP call | :140 | resolving each like on its own before the import writes, or a metadata call followed by a per-row resolve | CARRIED |\n| C1d | must_prove | the likes-import call is to `/internal/videos/metadata` | :140 | the import still going through `resolve_videos_by_uuid_host`'s route | CARRIED |\n| D1 | docstring | \"resolves a request's browser likes with one Engine call, to `/internal/videos/metadata`\" | :109, :140 | same as C1a\u2013C1d | CARRIED |\n| D2 | docstring | \"an import records a like from each returned row whose video the profile has not disliked\" | :141, :142 | skipping the first or last row (imports 1), ignoring the dislike (imports 3) | CARRIED |\n| D3 | docstring | page: \"one `/internal/videos/metadata` request whose `entries` are the five submitted pairs, in order\" | :109 | deduping or dropping the unknown entry before sending, reordering, sending the browser's `{uuid, host}` keys unrenamed | CARRIED |\n| D4 | docstring | page: \"answered 200 with the three known rows in submitted order\" | :110 | returning rows in table order `[A, B, C]`, or a non-200 status | CARRIED |\n| D5 | docstring | \"an empty body, an empty `likes` list, and a list of only malformed likes are each answered 200 with `likes == []`\" | :119 | a 400 or 502 on any of the three, or a malformed entry passed through as a row | CARRIED |\n| D6 | docstring | those three \"reach the Engine not at all\" | :117 | a metadata call with empty `entries`, or a call for a partly-valid entry | CARRIED |\n| D7 | docstring | \"a well-formed like sent next does reach it\" | :120, :121 | a deaf stand-in making :117 vacuous | CARRIED |\n| D8 | docstring | import: \"one `/internal/videos/metadata` request carrying the four pairs\" | :140 | filtering out the disliked or unknown entry before the call, or extra calls | CARRIED |\n| D9 | docstring | import: \"answers `{\"imported\": 2}`\" | :141 | counting submitted likes or all returned rows, or a wrong status | CARRIED |\n| D10 | docstring | \"leaves the profile liking exactly the two clean videos\" | :142 | a like for id-b or u-x, or a like keyed on the uuid (`u-a`) instead of the row's `video_id` | CARRIED |\n| D11a | docstring | stored with \"the `video_id` ... of their Engine rows\" | :143 | storing the browser's uuid as the `video_id`. Each fixture's `video_id` differs from its uuid | CARRIED |\n| D11b | docstring | stored with \"`video_uuid` and `instance_domain` of their Engine rows\" | :143 | a null or dropped `video_uuid`/`instance_domain`, but not taking them from the browser entry instead of the row: fixtures A and C have the same uuid and host in the row and in the entry | UNCARRIED |\n| N1 | name | test 1: \"a likes page is one metadata call\" | :109 | same as C1a/C1b | CARRIED |\n| N2 | name | test 1: \"answered with the known rows in submitted order\" | :110 | table-order or unfiltered-duplicate answer | CARRIED |\n| N3 | name | test 2: \"with no well-formed like is answered empty\" | :119 | a non-200 or non-empty answer | CARRIED |\n| N4 | name | test 2: \"without the engine\" | :117 | any Engine call on an empty or malformed page | CARRIED |\n| N5 | name | test 3: \"an import is one metadata call\" | :140 | same as C1c/C1d | CARRIED |\n| N6 | name | test 3: \"likes each returned video the profile has not disliked\" | :142, :143 | liking the disliked id-b, skipping a clean row, liking the unreturned u-x | CARRIED |\n| C2a | must_prove | import records a like for each returned row | :141, :142, :143 | skipping the first or last returned row. Disliked B sits between clean A and C, so a skip yields 1 | CARRIED |\n| C2b | must_prove | ...only where the profile has not disliked the video | :141, :142 | ignoring the dislike, or checking it against the uuid instead of the row's `video_id` (both import 3 including id-b) | CARRIED |\n| C2c | must_prove | ...and only for returned rows | :142, :143 | recording a like from the submitted entry for unknown `u-x` | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. whole-claim (rules/testing.md) \u2014 tests/tmp/test_14_batch_like_resolution_phase3.py:143\n   assert stored == {(\"id-a\", \"u-a\", HOST), (\"id-c\", \"u-c\", HOST)}  # C2: each like carries its row's video_uuid\n   D11b says the stored `video_uuid` and `instance_domain` come from the Engine rows. The rows'\n   values are the same as the submitted entry's, so an import that stores the browser's uuid and\n   host passes. Either give one row a `video_uuid`/`instance_domain` that differs from its entry\n   (the stand-in matches on the entry key, so the returned row can differ), or narrow the docstring\n   sentence at :5 to `video_id`. Docstring-only clause, so this does not block.\n2. bounds (rules/testing.md) \u2014 tests/tmp/test_14_batch_like_resolution_phase3.py:124\n   C1 covers any likes-import request, but only a populated import runs. Nothing tests an empty\n   import (`{}`, `likes: []`, or only malformed likes): whether it reaches the Engine and what it\n   answers. Test 2 covers this for the page route only. The `MAX_CLIENT_LIKES` cut-off is also\n   untested on both routes: a request at or over max should still be one call with at most max\n   entries.\n3. normal-and-abnormal-paths (rules/testing.md) \u2014 tests/tmp/test_14_batch_like_resolution_phase3.py:83\n   The stand-in always answers the metadata route 200. The expected failure (the metadata call\n   fails and the page answers 502, or the import answers 502 and records nothing) is not tested on\n   either route. A missing or invalid `X-Profile-Key` on import is not tested either.\n4. whole-claim (rules/testing.md) \u2014 tests/tmp/test_14_batch_like_resolution_phase3.py:74\n   The equality checks at :109, :121 and :140 carry \"exactly one Engine HTTP call\" only for POST\n   and GET. The stand-in records only those two methods, so a stray request by any other method\n   would not reach `received`. No rule directly covers this. Noted because C1 says \"exactly\".\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `code_under_test` lists tests/tmp/test_client_like_batching.py (NEW), which does not resolve.\n   It was not read.\n2. `fixtures_path` was not supplied. The test uses no pytest fixture except `tmp_path`, and its\n   helpers are imported from tests/active/conftest.py (`ClientBackend`, `client_server`,\n   `RateLimiter`, `ensure_user_schema`). I read that file to judge independence.\n```",
        "body": "### devsecops-test-shape-auditor\n\n```\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\nFails at tests/tmp/test_14_batch_like_resolution_phase3.py:109. The assertion `received == [(METADATA, {\"entries\": [...]})]`\nfinds `[(\"/internal/videos/resolve\", {\"host\": \"h.example\", \"uuid\": \"u-c\"})]` instead.\n`resolve_videos_by_uuid_host` still calls `/internal/videos/resolve` once per like, the stand-in's\nreply has no `video`, and the Client answers 502 before any metadata call. The same wrong\nrequest list fails line 121 of the empty-body test and line 140 of the import test.\n\nNOT ASSESSED\n1. `code_under_test` listed tests/tmp/test_client_like_batching.py (NEW), which does not resolve.\n   It was not read, and the verdict does not depend on it.\n2. `fixtures_path` was not supplied. The test imports `ClientBackend`, `RateLimiter`, `client_server`\n   and `ensure_user_schema` from tests/active/conftest.py (line 22), which was read. It builds its own\n   Engine stand-in and Client server and uses no conftest fixture.\n```\n\n### devsecops-test-claim-auditor\n\nCLAIM AUDIT \u2014 VERDICT: PASS\n\n```\nCLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (22 clauses: 4 must_prove, 12 docstring, 6 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | a likes-page request causes exactly one Engine HTTP call | :109 | a per-like resolve loop, or any second call before or after the batch. The whole record is compared by equality, not by membership | CARRIED |\n| C1b | must_prove | the likes-page call is to `/internal/videos/metadata` | :109 | the batch sent to any other route, e.g. `/internal/videos/resolve` | CARRIED |\n| C1c | must_prove | a likes-import request causes exactly one Engine HTTP call | :140 | resolving each like on its own before the import writes, or a metadata call followed by a per-row resolve | CARRIED |\n| C1d | must_prove | the likes-import call is to `/internal/videos/metadata` | :140 | the import still going through `resolve_videos_by_uuid_host`'s route | CARRIED |\n| D1 | docstring | \"resolves a request's browser likes with one Engine call, to `/internal/videos/metadata`\" | :109, :140 | same as C1a\u2013C1d | CARRIED |\n| D2 | docstring | \"an import records a like from each returned row whose video the profile has not disliked\" | :141, :142 | skipping the first or last row (imports 1), ignoring the dislike (imports 3) | CARRIED |\n| D3 | docstring | page: \"one `/internal/videos/metadata` request whose `entries` are the five submitted pairs, in order\" | :109 | deduping or dropping the unknown entry before sending, reordering, sending the browser's `{uuid, host}` keys unrenamed | CARRIED |\n| D4 | docstring | page: \"answered 200 with the three known rows in submitted order\" | :110 | returning rows in table order `[A, B, C]`, or a non-200 status | CARRIED |\n| D5 | docstring | \"an empty body, an empty `likes` list, and a list of only malformed likes are each answered 200 with `likes == []`\" | :119 | a 400 or 502 on any of the three, or a malformed entry passed through as a row | CARRIED |\n| D6 | docstring | those three \"reach the Engine not at all\" | :117 | a metadata call with empty `entries`, or a call for a partly-valid entry | CARRIED |\n| D7 | docstring | \"a well-formed like sent next does reach it\" | :120, :121 | a deaf stand-in making :117 vacuous | CARRIED |\n| D8 | docstring | import: \"one `/internal/videos/metadata` request carrying the four pairs\" | :140 | filtering out the disliked or unknown entry before the call, or extra calls | CARRIED |\n| D9 | docstring | import: \"answers `{\"imported\": 2}`\" | :141 | counting submitted likes or all returned rows, or a wrong status | CARRIED |\n| D10 | docstring | \"leaves the profile liking exactly the two clean videos\" | :142 | a like for id-b or u-x, or a like keyed on the uuid (`u-a`) instead of the row's `video_id` | CARRIED |\n| D11a | docstring | stored with \"the `video_id` ... of their Engine rows\" | :143 | storing the browser's uuid as the `video_id`. Each fixture's `video_id` differs from its uuid | CARRIED |\n| D11b | docstring | stored with \"`video_uuid` and `instance_domain` of their Engine rows\" | :143 | a null or dropped `video_uuid`/`instance_domain`, but not taking them from the browser entry instead of the row: fixtures A and C have the same uuid and host in the row and in the entry | UNCARRIED |\n| N1 | name | test 1: \"a likes page is one metadata call\" | :109 | same as C1a/C1b | CARRIED |\n| N2 | name | test 1: \"answered with the known rows in submitted order\" | :110 | table-order or unfiltered-duplicate answer | CARRIED |\n| N3 | name | test 2: \"with no well-formed like is answered empty\" | :119 | a non-200 or non-empty answer | CARRIED |\n| N4 | name | test 2: \"without the engine\" | :117 | any Engine call on an empty or malformed page | CARRIED |\n| N5 | name | test 3: \"an import is one metadata call\" | :140 | same as C1c/C1d | CARRIED |\n| N6 | name | test 3: \"likes each returned video the profile has not disliked\" | :142, :143 | liking the disliked id-b, skipping a clean row, liking the unreturned u-x | CARRIED |\n| C2a | must_prove | import records a like for each returned row | :141, :142, :143 | skipping the first or last returned row. Disliked B sits between clean A and C, so a skip yields 1 | CARRIED |\n| C2b | must_prove | ...only where the profile has not disliked the video | :141, :142 | ignoring the dislike, or checking it against the uuid instead of the row's `video_id` (both import 3 including id-b) | CARRIED |\n| C2c | must_prove | ...and only for returned rows | :142, :143 | recording a like from the submitted entry for unknown `u-x` | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. whole-claim (rules/testing.md) \u2014 tests/tmp/test_14_batch_like_resolution_phase3.py:143\n   assert stored == {(\"id-a\", \"u-a\", HOST), (\"id-c\", \"u-c\", HOST)}  # C2: each like carries its row's video_uuid\n   D11b says the stored `video_uuid` and `instance_domain` come from the Engine rows. The rows'\n   values are the same as the submitted entry's, so an import that stores the browser's uuid and\n   host passes. Either give one row a `video_uuid`/`instance_domain` that differs from its entry\n   (the stand-in matches on the entry key, so the returned row can differ), or narrow the docstring\n   sentence at :5 to `video_id`. Docstring-only clause, so this does not block.\n2. bounds (rules/testing.md) \u2014 tests/tmp/test_14_batch_like_resolution_phase3.py:124\n   C1 covers any likes-import request, but only a populated import runs. Nothing tests an empty\n   import (`{}`, `likes: []`, or only malformed likes): whether it reaches the Engine and what it\n   answers. Test 2 covers this for the page route only. The `MAX_CLIENT_LIKES` cut-off is also\n   untested on both routes: a request at or over max should still be one call with at most max\n   entries.\n3. normal-and-abnormal-paths (rules/testing.md) \u2014 tests/tmp/test_14_batch_like_resolution_phase3.py:83\n   The stand-in always answers the metadata route 200. The expected failure (the metadata call\n   fails and the page answers 502, or the import answers 502 and records nothing) is not tested on\n   either route. A missing or invalid `X-Profile-Key` on import is not tested either.\n4. whole-claim (rules/testing.md) \u2014 tests/tmp/test_14_batch_like_resolution_phase3.py:74\n   The equality checks at :109, :121 and :140 carry \"exactly one Engine HTTP call\" only for POST\n   and GET. The stand-in records only those two methods, so a stray request by any other method\n   would not reach `received`. No rule directly covers this. Noted because C1 says \"exactly\".\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `code_under_test` lists tests/tmp/test_client_like_batching.py (NEW), which does not resolve.\n   It was not read.\n2. `fixtures_path` was not supplied. The test uses no pytest fixture except `tmp_path`, and its\n   helpers are imported from tests/active/conftest.py (`ClientBackend`, `client_server`,\n   `RateLimiter`, `ensure_user_schema`). I read that file to judge independence.\n```",
        "map": [
          {
            "id": "C1a",
            "source": "must_prove",
            "clause": "a likes-page request causes exactly one Engine HTTP call",
            "assertion": ":109",
            "excludes": "a per-like resolve loop, or any second call before or after the batch. The whole record is compared by equality, not by membership",
            "status": "CARRIED"
          },
          {
            "id": "C1b",
            "source": "must_prove",
            "clause": "the likes-page call is to `/internal/videos/metadata`",
            "assertion": ":109",
            "excludes": "the batch sent to any other route, e.g. `/internal/videos/resolve`",
            "status": "CARRIED"
          },
          {
            "id": "C1c",
            "source": "must_prove",
            "clause": "a likes-import request causes exactly one Engine HTTP call",
            "assertion": ":140",
            "excludes": "resolving each like on its own before the import writes, or a metadata call followed by a per-row resolve",
            "status": "CARRIED"
          },
          {
            "id": "C1d",
            "source": "must_prove",
            "clause": "the likes-import call is to `/internal/videos/metadata`",
            "assertion": ":140",
            "excludes": "the import still going through `resolve_videos_by_uuid_host`'s route",
            "status": "CARRIED"
          },
          {
            "id": "D1",
            "source": "docstring",
            "clause": "\"resolves a request's browser likes with one Engine call, to `/internal/videos/metadata`\"",
            "assertion": ":109, :140",
            "excludes": "same as C1a\u2013C1d",
            "status": "CARRIED"
          },
          {
            "id": "D2",
            "source": "docstring",
            "clause": "\"an import records a like from each returned row whose video the profile has not disliked\"",
            "assertion": ":141, :142",
            "excludes": "skipping the first or last row (imports 1), ignoring the dislike (imports 3)",
            "status": "CARRIED"
          },
          {
            "id": "D3",
            "source": "docstring",
            "clause": "page: \"one `/internal/videos/metadata` request whose `entries` are the five submitted pairs, in order\"",
            "assertion": ":109",
            "excludes": "deduping or dropping the unknown entry before sending, reordering, sending the browser's `{uuid, host}` keys unrenamed",
            "status": "CARRIED"
          },
          {
            "id": "D4",
            "source": "docstring",
            "clause": "page: \"answered 200 with the three known rows in submitted order\"",
            "assertion": ":110",
            "excludes": "returning rows in table order `[A, B, C]`, or a non-200 status",
            "status": "CARRIED"
          },
          {
            "id": "D5",
            "source": "docstring",
            "clause": "\"an empty body, an empty `likes` list, and a list of only malformed likes are each answered 200 with `likes == []`\"",
            "assertion": ":119",
            "excludes": "a 400 or 502 on any of the three, or a malformed entry passed through as a row",
            "status": "CARRIED"
          },
          {
            "id": "D6",
            "source": "docstring",
            "clause": "those three \"reach the Engine not at all\"",
            "assertion": ":117",
            "excludes": "a metadata call with empty `entries`, or a call for a partly-valid entry",
            "status": "CARRIED"
          },
          {
            "id": "D7",
            "source": "docstring",
            "clause": "\"a well-formed like sent next does reach it\"",
            "assertion": ":120, :121",
            "excludes": "a deaf stand-in making :117 vacuous",
            "status": "CARRIED"
          },
          {
            "id": "D8",
            "source": "docstring",
            "clause": "import: \"one `/internal/videos/metadata` request carrying the four pairs\"",
            "assertion": ":140",
            "excludes": "filtering out the disliked or unknown entry before the call, or extra calls",
            "status": "CARRIED"
          },
          {
            "id": "D9",
            "source": "docstring",
            "clause": "import: \"answers `{\"imported\": 2}`\"",
            "assertion": ":141",
            "excludes": "counting submitted likes or all returned rows, or a wrong status",
            "status": "CARRIED"
          },
          {
            "id": "D10",
            "source": "docstring",
            "clause": "\"leaves the profile liking exactly the two clean videos\"",
            "assertion": ":142",
            "excludes": "a like for id-b or u-x, or a like keyed on the uuid (`u-a`) instead of the row's `video_id`",
            "status": "CARRIED"
          },
          {
            "id": "D11a",
            "source": "docstring",
            "clause": "stored with \"the `video_id` ... of their Engine rows\"",
            "assertion": ":143",
            "excludes": "storing the browser's uuid as the `video_id`. Each fixture's `video_id` differs from its uuid",
            "status": "CARRIED"
          },
          {
            "id": "D11b",
            "source": "docstring",
            "clause": "stored with \"`video_uuid` and `instance_domain` of their Engine rows\"",
            "assertion": ":143",
            "excludes": "a null or dropped `video_uuid`/`instance_domain`, but not taking them from the browser entry instead of the row: fixtures A and C have the same uuid and host in the row and in the entry",
            "status": "UNCARRIED"
          },
          {
            "id": "N1",
            "source": "name",
            "clause": "test 1: \"a likes page is one metadata call\"",
            "assertion": ":109",
            "excludes": "same as C1a/C1b",
            "status": "CARRIED"
          },
          {
            "id": "N2",
            "source": "name",
            "clause": "test 1: \"answered with the known rows in submitted order\"",
            "assertion": ":110",
            "excludes": "table-order or unfiltered-duplicate answer",
            "status": "CARRIED"
          },
          {
            "id": "N3",
            "source": "name",
            "clause": "test 2: \"with no well-formed like is answered empty\"",
            "assertion": ":119",
            "excludes": "a non-200 or non-empty answer",
            "status": "CARRIED"
          },
          {
            "id": "N4",
            "source": "name",
            "clause": "test 2: \"without the engine\"",
            "assertion": ":117",
            "excludes": "any Engine call on an empty or malformed page",
            "status": "CARRIED"
          },
          {
            "id": "N5",
            "source": "name",
            "clause": "test 3: \"an import is one metadata call\"",
            "assertion": ":140",
            "excludes": "same as C1c/C1d",
            "status": "CARRIED"
          },
          {
            "id": "N6",
            "source": "name",
            "clause": "test 3: \"likes each returned video the profile has not disliked\"",
            "assertion": ":142, :143",
            "excludes": "liking the disliked id-b, skipping a clean row, liking the unreturned u-x",
            "status": "CARRIED"
          },
          {
            "id": "C2a",
            "source": "must_prove",
            "clause": "import records a like for each returned row",
            "assertion": ":141, :142, :143",
            "excludes": "skipping the first or last returned row. Disliked B sits between clean A and C, so a skip yields 1",
            "status": "CARRIED"
          },
          {
            "id": "C2b",
            "source": "must_prove",
            "clause": "...only where the profile has not disliked the video",
            "assertion": ":141, :142",
            "excludes": "ignoring the dislike, or checking it against the uuid instead of the row's `video_id` (both import 3 including id-b)",
            "status": "CARRIED"
          },
          {
            "id": "C2c",
            "source": "must_prove",
            "clause": "...and only for returned rows",
            "assertion": ":142, :143",
            "excludes": "recording a like from the submitted entry for unknown `u-x`",
            "status": "CARRIED"
          }
        ],
        "map_problem": ""
      },
      {
        "shape": "```\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\ntest_a_likes_page_is_one_metadata_call_answered_with_the_known_rows_in_submitted_order fails at\nline 109: `received` holds a single `(\"/internal/videos/resolve\", {\"host\": \"h.example\", \"uuid\": \"u-c\"})`\nrequest instead of the one `/internal/videos/metadata` request. This is because `resolve_videos_by_uuid_host`\nstill calls the Engine once per like, and this stand-in answers that call with no `video` field, so the\nClient stops with a 502.\ntest_a_likes_page_with_no_well_formed_like_is_answered_empty_without_the_engine passes lines 117,\n119 and 120, then fails at line 121 on the same `/internal/videos/resolve` request.\ntest_an_import_is_one_metadata_call_and_likes_each_returned_video_the_profile_has_not_disliked\nfails at line 140 on `received == [(METADATA, ...)]`, because the only request recorded is to\n`/internal/videos/resolve`.\n\nNOT ASSESSED\n1. `code_under_test` lists tests/tmp/test_client_like_batching.py (NEW), and that path does not\n   resolve (Glob: no matches). I did not read it. Nothing in test_path imports it.\n2. No `fixtures_path` was supplied. The test does not use pytest fixtures. It imports\n   `ClientBackend`, `RateLimiter`, `client_server` and `ensure_user_schema` from\n   tests/active/conftest.py (lines 39\u201366), and I read that file. `write_dislike`,\n   `resolve_profile` and `load_liked_keys` resolve to client/backend/lib/{dislikes,profiles,users_store}.py.\n   I confirmed each definition exists but did not read their bodies.\n```",
        "claim": "CLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (25 clauses: 7 must_prove, 12 docstring, 6 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | a likes-page request causes exactly one Engine HTTP call | :109 | a resolve loop that runs once per like, or a second call before or after the batch. The whole record is compared by equality, not by membership | CARRIED |\n| C1b | must_prove | the likes-page call is to `/internal/videos/metadata` | :109 | the batch going to another route, e.g. `/internal/videos/resolve` | CARRIED |\n| C1c | must_prove | a likes-import request causes exactly one Engine HTTP call | :140 | resolving each like separately before the import writes, or a metadata call followed by a resolve for each row | CARRIED |\n| C1d | must_prove | the likes-import call is to `/internal/videos/metadata` | :140 | the import still using the route that `resolve_videos_by_uuid_host` calls | CARRIED |\n| D1 | docstring | \"resolves a request's browser likes with one Engine call, to `/internal/videos/metadata`\" | :109, :140 | same as C1a\u2013C1d | CARRIED |\n| D2 | docstring | \"an import records a like from each returned row whose video the profile has not disliked\" | :141, :142 | skipping the first or last row (imports 1), or ignoring the dislike (imports 3) | CARRIED |\n| D3 | docstring | page: \"one `/internal/videos/metadata` request whose `entries` are the five submitted pairs, in order\" | :109 | removing duplicates or dropping the unknown entry before sending, reordering, or sending the browser's `{uuid, host}` keys without renaming them | CARRIED |\n| D4 | docstring | page: \"answered 200 with the three known rows in submitted order\" | :110 | returning rows in table order `[A, B, C]`, or a non-200 status | CARRIED |\n| D5 | docstring | \"an empty body, an empty `likes` list, and a list of only malformed likes are each answered 200 with `likes == []`\" | :119 | a 400 or 502 on any of the three, or a malformed entry passed through as a row | CARRIED |\n| D6 | docstring | those three \"reach the Engine not at all\" | :117 | a metadata call with empty `entries`, or a call for an entry that is only partly valid | CARRIED |\n| D7 | docstring | \"a well-formed like sent next does reach it\" | :120, :121 | a stand-in Engine that records nothing, which would make :117 pass vacuously | CARRIED |\n| D8 | docstring | import: \"one `/internal/videos/metadata` request carrying the four pairs\" | :140 | filtering out the disliked or unknown entry before the call, or extra calls | CARRIED |\n| D9 | docstring | import: \"answers `{\"imported\": 2}`\" | :141 | counting the submitted likes or all returned rows, or a wrong status | CARRIED |\n| D10 | docstring | \"leaves the profile liking exactly the two clean videos\" | :142 | a like for id-b or u-x, or a like keyed on the uuid (`u-a`) instead of the row's `video_id` | CARRIED |\n| D11a | docstring | stored with \"the `video_id` of their Engine rows\" | :143 | storing the browser's uuid as the `video_id`. Each fixture's `video_id` differs from its uuid (:30\u2013:32) | CARRIED |\n| D11b | docstring | narrowed to: stored \"with a non-null `video_uuid` and `instance_domain` (which the row and the submitted like share, so which one they are taken from is not told apart)\" | :143 | a null or dropped `video_uuid`/`instance_domain`. The narrowed sentence no longer claims the row is the source | CARRIED |\n| N1 | name | test 1: \"a likes page is one metadata call\" | :109 | same as C1a/C1b | CARRIED |\n| N2 | name | test 1: \"answered with the known rows in submitted order\" | :110 | an answer in table order, or one that keeps the duplicate | CARRIED |\n| N3 | name | test 2: \"with no well-formed like is answered empty\" | :119 | a non-200 or non-empty answer | CARRIED |\n| N4 | name | test 2: \"without the engine\" | :117 | any Engine call on an empty or malformed page | CARRIED |\n| N5 | name | test 3: \"an import is one metadata call\" | :140 | same as C1c/C1d | CARRIED |\n| N6 | name | test 3: \"likes each returned video the profile has not disliked\" | :142, :143 | liking the disliked id-b, skipping a clean row, or liking the unreturned u-x | CARRIED |\n| C2a | must_prove | import records a like for each returned row | :141, :142, :143 | skipping the first or last returned row. Disliked B sits between clean A and C, so a skip yields 1 | CARRIED |\n| C2b | must_prove | ...only where the profile has not disliked the video | :141, :142 | ignoring the dislike, or checking it against the uuid instead of the row's `video_id` (both import 3, including id-b) | CARRIED |\n| C2c | must_prove | ...and only for returned rows | :142, :143 | recording a like from the submitted entry for the unknown `u-x` | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nOBSERVATIONS\n1. whole-claim (rules/testing.md): tests/tmp/test_14_batch_like_resolution_phase3.py:5\n   Ledger row D11b changed from UNCARRIED to CARRIED because the author narrowed the docstring, not because they added an assertion. The old sentence said `video_uuid` and `instance_domain` are taken \"of their Engine rows\". The new sentence claims only that they are non-null, and says outright that the source is not told apart. :143 carries the narrowed claim. Nothing yet excludes an implementation that stores the browser entry's uuid and host instead of the row's, because fixtures A and C have the same uuid and host in the row and in the entry.\n2. bounds (rules/testing.md): tests/tmp/test_14_batch_like_resolution_phase3.py:124\n   The import route has no test for its input edges: an empty body, an empty `likes` list, or only malformed likes. So nothing shows whether an import with nothing to resolve still calls the Engine. Test 2 (:113) covers these edges for the likes page only.\n3. normal-and-abnormal-paths (rules/testing.md): tests/tmp/test_14_batch_like_resolution_phase3.py:83\n   The stand-in Engine always answers 200 with `ok: True`. Neither route's failure mode is exercised. That means no test covers an Engine error answered as 502, and no test shows that an import against a failing Engine records no likes.\n4. surfaces (rules/testing.md): tests/tmp/test_14_batch_like_resolution_phase3.py:107\n   Here \"likes-page request\" is read as `POST /api/user-profile/likes`. The server also serves `GET /api/user-profile/likes` (server.py:995), which also calls `/internal/videos/metadata`, and this test does not exercise it. The ledger fixed this reading on the first audit. I record it here in case C1 was meant to cover both.\n\nNOT ASSESSED\n1. `code_under_test` lists tests/tmp/test_client_like_batching.py (NEW). That path does not exist in the worktree, so I could not read it.\n2. `fixtures_path` was not supplied. I read `ClientBackend`, `RateLimiter`, `client_server` and `ensure_user_schema` from tests/active/conftest.py, which the test imports directly at :22. I read `write_dislike`, `resolve_profile` and `load_liked_keys` from client/backend/lib. I did not read the full `ClientBackend.request` body or `connect_db`'s row factory.",
        "body": "### devsecops-test-shape-auditor\n\n```\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\ntest_a_likes_page_is_one_metadata_call_answered_with_the_known_rows_in_submitted_order fails at\nline 109: `received` holds a single `(\"/internal/videos/resolve\", {\"host\": \"h.example\", \"uuid\": \"u-c\"})`\nrequest instead of the one `/internal/videos/metadata` request. This is because `resolve_videos_by_uuid_host`\nstill calls the Engine once per like, and this stand-in answers that call with no `video` field, so the\nClient stops with a 502.\ntest_a_likes_page_with_no_well_formed_like_is_answered_empty_without_the_engine passes lines 117,\n119 and 120, then fails at line 121 on the same `/internal/videos/resolve` request.\ntest_an_import_is_one_metadata_call_and_likes_each_returned_video_the_profile_has_not_disliked\nfails at line 140 on `received == [(METADATA, ...)]`, because the only request recorded is to\n`/internal/videos/resolve`.\n\nNOT ASSESSED\n1. `code_under_test` lists tests/tmp/test_client_like_batching.py (NEW), and that path does not\n   resolve (Glob: no matches). I did not read it. Nothing in test_path imports it.\n2. No `fixtures_path` was supplied. The test does not use pytest fixtures. It imports\n   `ClientBackend`, `RateLimiter`, `client_server` and `ensure_user_schema` from\n   tests/active/conftest.py (lines 39\u201366), and I read that file. `write_dislike`,\n   `resolve_profile` and `load_liked_keys` resolve to client/backend/lib/{dislikes,profiles,users_store}.py.\n   I confirmed each definition exists but did not read their bodies.\n```\n\n### devsecops-test-claim-auditor\n\nCLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (25 clauses: 7 must_prove, 12 docstring, 6 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | a likes-page request causes exactly one Engine HTTP call | :109 | a resolve loop that runs once per like, or a second call before or after the batch. The whole record is compared by equality, not by membership | CARRIED |\n| C1b | must_prove | the likes-page call is to `/internal/videos/metadata` | :109 | the batch going to another route, e.g. `/internal/videos/resolve` | CARRIED |\n| C1c | must_prove | a likes-import request causes exactly one Engine HTTP call | :140 | resolving each like separately before the import writes, or a metadata call followed by a resolve for each row | CARRIED |\n| C1d | must_prove | the likes-import call is to `/internal/videos/metadata` | :140 | the import still using the route that `resolve_videos_by_uuid_host` calls | CARRIED |\n| D1 | docstring | \"resolves a request's browser likes with one Engine call, to `/internal/videos/metadata`\" | :109, :140 | same as C1a\u2013C1d | CARRIED |\n| D2 | docstring | \"an import records a like from each returned row whose video the profile has not disliked\" | :141, :142 | skipping the first or last row (imports 1), or ignoring the dislike (imports 3) | CARRIED |\n| D3 | docstring | page: \"one `/internal/videos/metadata` request whose `entries` are the five submitted pairs, in order\" | :109 | removing duplicates or dropping the unknown entry before sending, reordering, or sending the browser's `{uuid, host}` keys without renaming them | CARRIED |\n| D4 | docstring | page: \"answered 200 with the three known rows in submitted order\" | :110 | returning rows in table order `[A, B, C]`, or a non-200 status | CARRIED |\n| D5 | docstring | \"an empty body, an empty `likes` list, and a list of only malformed likes are each answered 200 with `likes == []`\" | :119 | a 400 or 502 on any of the three, or a malformed entry passed through as a row | CARRIED |\n| D6 | docstring | those three \"reach the Engine not at all\" | :117 | a metadata call with empty `entries`, or a call for an entry that is only partly valid | CARRIED |\n| D7 | docstring | \"a well-formed like sent next does reach it\" | :120, :121 | a stand-in Engine that records nothing, which would make :117 pass vacuously | CARRIED |\n| D8 | docstring | import: \"one `/internal/videos/metadata` request carrying the four pairs\" | :140 | filtering out the disliked or unknown entry before the call, or extra calls | CARRIED |\n| D9 | docstring | import: \"answers `{\"imported\": 2}`\" | :141 | counting the submitted likes or all returned rows, or a wrong status | CARRIED |\n| D10 | docstring | \"leaves the profile liking exactly the two clean videos\" | :142 | a like for id-b or u-x, or a like keyed on the uuid (`u-a`) instead of the row's `video_id` | CARRIED |\n| D11a | docstring | stored with \"the `video_id` of their Engine rows\" | :143 | storing the browser's uuid as the `video_id`. Each fixture's `video_id` differs from its uuid (:30\u2013:32) | CARRIED |\n| D11b | docstring | narrowed to: stored \"with a non-null `video_uuid` and `instance_domain` (which the row and the submitted like share, so which one they are taken from is not told apart)\" | :143 | a null or dropped `video_uuid`/`instance_domain`. The narrowed sentence no longer claims the row is the source | CARRIED |\n| N1 | name | test 1: \"a likes page is one metadata call\" | :109 | same as C1a/C1b | CARRIED |\n| N2 | name | test 1: \"answered with the known rows in submitted order\" | :110 | an answer in table order, or one that keeps the duplicate | CARRIED |\n| N3 | name | test 2: \"with no well-formed like is answered empty\" | :119 | a non-200 or non-empty answer | CARRIED |\n| N4 | name | test 2: \"without the engine\" | :117 | any Engine call on an empty or malformed page | CARRIED |\n| N5 | name | test 3: \"an import is one metadata call\" | :140 | same as C1c/C1d | CARRIED |\n| N6 | name | test 3: \"likes each returned video the profile has not disliked\" | :142, :143 | liking the disliked id-b, skipping a clean row, or liking the unreturned u-x | CARRIED |\n| C2a | must_prove | import records a like for each returned row | :141, :142, :143 | skipping the first or last returned row. Disliked B sits between clean A and C, so a skip yields 1 | CARRIED |\n| C2b | must_prove | ...only where the profile has not disliked the video | :141, :142 | ignoring the dislike, or checking it against the uuid instead of the row's `video_id` (both import 3, including id-b) | CARRIED |\n| C2c | must_prove | ...and only for returned rows | :142, :143 | recording a like from the submitted entry for the unknown `u-x` | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nOBSERVATIONS\n1. whole-claim (rules/testing.md): tests/tmp/test_14_batch_like_resolution_phase3.py:5\n   Ledger row D11b changed from UNCARRIED to CARRIED because the author narrowed the docstring, not because they added an assertion. The old sentence said `video_uuid` and `instance_domain` are taken \"of their Engine rows\". The new sentence claims only that they are non-null, and says outright that the source is not told apart. :143 carries the narrowed claim. Nothing yet excludes an implementation that stores the browser entry's uuid and host instead of the row's, because fixtures A and C have the same uuid and host in the row and in the entry.\n2. bounds (rules/testing.md): tests/tmp/test_14_batch_like_resolution_phase3.py:124\n   The import route has no test for its input edges: an empty body, an empty `likes` list, or only malformed likes. So nothing shows whether an import with nothing to resolve still calls the Engine. Test 2 (:113) covers these edges for the likes page only.\n3. normal-and-abnormal-paths (rules/testing.md): tests/tmp/test_14_batch_like_resolution_phase3.py:83\n   The stand-in Engine always answers 200 with `ok: True`. Neither route's failure mode is exercised. That means no test covers an Engine error answered as 502, and no test shows that an import against a failing Engine records no likes.\n4. surfaces (rules/testing.md): tests/tmp/test_14_batch_like_resolution_phase3.py:107\n   Here \"likes-page request\" is read as `POST /api/user-profile/likes`. The server also serves `GET /api/user-profile/likes` (server.py:995), which also calls `/internal/videos/metadata`, and this test does not exercise it. The ledger fixed this reading on the first audit. I record it here in case C1 was meant to cover both.\n\nNOT ASSESSED\n1. `code_under_test` lists tests/tmp/test_client_like_batching.py (NEW). That path does not exist in the worktree, so I could not read it.\n2. `fixtures_path` was not supplied. I read `ClientBackend`, `RateLimiter`, `client_server` and `ensure_user_schema` from tests/active/conftest.py, which the test imports directly at :22. I read `write_dislike`, `resolve_profile` and `load_liked_keys` from client/backend/lib. I did not read the full `ClientBackend.request` body or `connect_db`'s row factory.",
        "map": [
          {
            "id": "C1a",
            "source": "must_prove",
            "clause": "a likes-page request causes exactly one Engine HTTP call",
            "assertion": ":109",
            "excludes": "a resolve loop that runs once per like, or a second call before or after the batch. The whole record is compared by equality, not by membership",
            "status": "CARRIED"
          },
          {
            "id": "C1b",
            "source": "must_prove",
            "clause": "the likes-page call is to `/internal/videos/metadata`",
            "assertion": ":109",
            "excludes": "the batch going to another route, e.g. `/internal/videos/resolve`",
            "status": "CARRIED"
          },
          {
            "id": "C1c",
            "source": "must_prove",
            "clause": "a likes-import request causes exactly one Engine HTTP call",
            "assertion": ":140",
            "excludes": "resolving each like separately before the import writes, or a metadata call followed by a resolve for each row",
            "status": "CARRIED"
          },
          {
            "id": "C1d",
            "source": "must_prove",
            "clause": "the likes-import call is to `/internal/videos/metadata`",
            "assertion": ":140",
            "excludes": "the import still using the route that `resolve_videos_by_uuid_host` calls",
            "status": "CARRIED"
          },
          {
            "id": "D1",
            "source": "docstring",
            "clause": "\"resolves a request's browser likes with one Engine call, to `/internal/videos/metadata`\"",
            "assertion": ":109, :140",
            "excludes": "same as C1a\u2013C1d",
            "status": "CARRIED"
          },
          {
            "id": "D2",
            "source": "docstring",
            "clause": "\"an import records a like from each returned row whose video the profile has not disliked\"",
            "assertion": ":141, :142",
            "excludes": "skipping the first or last row (imports 1), or ignoring the dislike (imports 3)",
            "status": "CARRIED"
          },
          {
            "id": "D3",
            "source": "docstring",
            "clause": "page: \"one `/internal/videos/metadata` request whose `entries` are the five submitted pairs, in order\"",
            "assertion": ":109",
            "excludes": "removing duplicates or dropping the unknown entry before sending, reordering, or sending the browser's `{uuid, host}` keys without renaming them",
            "status": "CARRIED"
          },
          {
            "id": "D4",
            "source": "docstring",
            "clause": "page: \"answered 200 with the three known rows in submitted order\"",
            "assertion": ":110",
            "excludes": "returning rows in table order `[A, B, C]`, or a non-200 status",
            "status": "CARRIED"
          },
          {
            "id": "D5",
            "source": "docstring",
            "clause": "\"an empty body, an empty `likes` list, and a list of only malformed likes are each answered 200 with `likes == []`\"",
            "assertion": ":119",
            "excludes": "a 400 or 502 on any of the three, or a malformed entry passed through as a row",
            "status": "CARRIED"
          },
          {
            "id": "D6",
            "source": "docstring",
            "clause": "those three \"reach the Engine not at all\"",
            "assertion": ":117",
            "excludes": "a metadata call with empty `entries`, or a call for an entry that is only partly valid",
            "status": "CARRIED"
          },
          {
            "id": "D7",
            "source": "docstring",
            "clause": "\"a well-formed like sent next does reach it\"",
            "assertion": ":120, :121",
            "excludes": "a stand-in Engine that records nothing, which would make :117 pass vacuously",
            "status": "CARRIED"
          },
          {
            "id": "D8",
            "source": "docstring",
            "clause": "import: \"one `/internal/videos/metadata` request carrying the four pairs\"",
            "assertion": ":140",
            "excludes": "filtering out the disliked or unknown entry before the call, or extra calls",
            "status": "CARRIED"
          },
          {
            "id": "D9",
            "source": "docstring",
            "clause": "import: \"answers `{\"imported\": 2}`\"",
            "assertion": ":141",
            "excludes": "counting the submitted likes or all returned rows, or a wrong status",
            "status": "CARRIED"
          },
          {
            "id": "D10",
            "source": "docstring",
            "clause": "\"leaves the profile liking exactly the two clean videos\"",
            "assertion": ":142",
            "excludes": "a like for id-b or u-x, or a like keyed on the uuid (`u-a`) instead of the row's `video_id`",
            "status": "CARRIED"
          },
          {
            "id": "D11a",
            "source": "docstring",
            "clause": "stored with \"the `video_id` of their Engine rows\"",
            "assertion": ":143",
            "excludes": "storing the browser's uuid as the `video_id`. Each fixture's `video_id` differs from its uuid (:30\u2013:32)",
            "status": "CARRIED"
          },
          {
            "id": "D11b",
            "source": "docstring",
            "clause": "narrowed to: stored \"with a non-null `video_uuid` and `instance_domain` (which the row and the submitted like share, so which one they are taken from is not told apart)\"",
            "assertion": ":143",
            "excludes": "a null or dropped `video_uuid`/`instance_domain`. The narrowed sentence no longer claims the row is the source",
            "status": "CARRIED"
          },
          {
            "id": "N1",
            "source": "name",
            "clause": "test 1: \"a likes page is one metadata call\"",
            "assertion": ":109",
            "excludes": "same as C1a/C1b",
            "status": "CARRIED"
          },
          {
            "id": "N2",
            "source": "name",
            "clause": "test 1: \"answered with the known rows in submitted order\"",
            "assertion": ":110",
            "excludes": "an answer in table order, or one that keeps the duplicate",
            "status": "CARRIED"
          },
          {
            "id": "N3",
            "source": "name",
            "clause": "test 2: \"with no well-formed like is answered empty\"",
            "assertion": ":119",
            "excludes": "a non-200 or non-empty answer",
            "status": "CARRIED"
          },
          {
            "id": "N4",
            "source": "name",
            "clause": "test 2: \"without the engine\"",
            "assertion": ":117",
            "excludes": "any Engine call on an empty or malformed page",
            "status": "CARRIED"
          },
          {
            "id": "N5",
            "source": "name",
            "clause": "test 3: \"an import is one metadata call\"",
            "assertion": ":140",
            "excludes": "same as C1c/C1d",
            "status": "CARRIED"
          },
          {
            "id": "N6",
            "source": "name",
            "clause": "test 3: \"likes each returned video the profile has not disliked\"",
            "assertion": ":142, :143",
            "excludes": "liking the disliked id-b, skipping a clean row, or liking the unreturned u-x",
            "status": "CARRIED"
          },
          {
            "id": "C2a",
            "source": "must_prove",
            "clause": "import records a like for each returned row",
            "assertion": ":141, :142, :143",
            "excludes": "skipping the first or last returned row. Disliked B sits between clean A and C, so a skip yields 1",
            "status": "CARRIED"
          },
          {
            "id": "C2b",
            "source": "must_prove",
            "clause": "...only where the profile has not disliked the video",
            "assertion": ":141, :142",
            "excludes": "ignoring the dislike, or checking it against the uuid instead of the row's `video_id` (both import 3, including id-b)",
            "status": "CARRIED"
          },
          {
            "id": "C2c",
            "source": "must_prove",
            "clause": "...and only for returned rows",
            "assertion": ":142, :143",
            "excludes": "recording a like from the submitted entry for the unknown `u-x`",
            "status": "CARRIED"
          }
        ],
        "map_problem": ""
      }
    ],
    "tests/tmp/test_14_batch_like_resolution_phase4.py": [
      {
        "shape": "SHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\nFails at tests/tmp/test_14_batch_like_resolution_phase4.py:109 on `assert received == [(METADATA, {\"entries\": [... for i in range(50)]})]`. `MAX_CLIENT_LIKES = 200` (client/backend/server.py:51) lets all 60 entries through, so the recorded request carries 60 entries instead of 50. The same mismatch fails line 123 in the import test. In the recommendations test, line 131 passes and line 133 fails because the forwarded `likes` list holds 60 pairs.\n\nNOT ASSESSED\n1. `code_under_test` listed tests/tmp/test_client_like_batching.py, which does not exist. Nothing from it was read.\n2. `fixtures_path` was not supplied. The test builds its own Engine stand-in and Client backend at lines 44-102. The imports it depends on were resolved by reading and grep: `ClientBackend`, `client_server`, `RateLimiter` and `ensure_user_schema` in tests/active/conftest.py, `resolve_profile` in client/backend/lib/profiles.py, `load_liked_keys` in client/backend/lib/users_store.py, and the `ClientBackendServer.__init__` signature at client/backend/server.py:203. The bodies of `resolve_profile`, `load_liked_keys` and `_parse_client_likes` were not read.",
        "claim": "CLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (14 clauses: 3 must_prove, 6 docstring, 5 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | a 60-like body reaches the Engine capped at 50 entries | :109, :123, :133 | the current cap of 200 (all 60 forwarded), a cap of 49 or 51, and a cap on one route only among the three exercised. Each is an exact equality on the whole recorded request list | CARRIED |\n| C1b | must_prove | the entries forwarded are the *first* 50 | :109, :123, :133 | keeping the last 50, an arbitrary 50, or reordered entries. The expected list is `u-00`..`u-49` in order | CARRIED |\n| C1c | must_prove | \"reaches the Engine\", in one request, carrying those entries and nothing else | :109, :123, :133 | a split into several Engine calls, an extra Engine call, or entries reshaped on the way. `received == [ ... ]` holds exactly one element | CARRIED |\n| D1 | docstring | \"at most the first 50 \u2026 on each of the three paths that read `MAX_CLIENT_LIKES`\" | :109, :123, :133 | a cap that misses any of the three readers at server.py:492, :885, :1018 | CARRIED |\n| D2 | docstring | likes page: \"one `/internal/videos/metadata` request whose `entries` are the first 50\" | :109 | the uncapped or last-50 forward, or a second request | CARRIED |\n| D3 | docstring | likes page: \"answered 200 with those 50 videos' rows\" | :110 | a non-200 status, missing or extra rows, rows out of order. Compares the exact `video_id` list `id-00`..`id-49` | CARRIED |\n| D4 | docstring | import: one metadata request of the first 50 and \"answers `{\"imported\": 50}`\" | :123, :124 | the uncapped forward, or a count other than 50 (for example 60 under the 200 cap) | CARRIED |\n| D5 | docstring | import: \"leaves the profile liking exactly those 50 videos\" | :125 | storing all 60, storing a different 50, or storing extras. Set equality read back through `load_liked_keys` | CARRIED |\n| D6 | docstring | keyless `POST /recommendations` \"answered 200 and forwards one request whose `likes` are the first 50 `{uuid, host}` pairs\" | :131, :133 | a non-200 status, the uncapped forward, the last 50, a second forwarded request, or likes reshaped away from `{uuid, host}` | CARRIED |\n| N1 | name | \"a 60-like likes page reaches the engine as its first 50\" | :109 | same as D2 | CARRIED |\n| N2 | name | \"and is answered with their rows\" | :110 | same as D3 | CARRIED |\n| N3 | name | \"a 60-like import reaches the engine as its first 50\" | :123 | same as D4 (Engine half) | CARRIED |\n| N4 | name | \"and likes exactly those\" | :125 | same as D5 | CARRIED |\n| N5 | name | \"a keyless 60-like recommendations request forwards its first 50 likes\" | :133 | same as D6 (forward half) | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. whole-claim (rules/testing.md) \u2014 tests/tmp/test_14_batch_like_resolution_phase4.py:1\n   The docstring says the three paths are \"the `MAX_CLIENT_LIKES` readers the plan's grep found\". The grep is right that there are three reads (server.py:492, :885, :1018). But the read at :492 is the proxy sanitiser, and two routes go through it: `/recommendations` and `/videos/similar` (`PROXY_ALLOWED_BODY_KEYS`, server.py:101-102). C1 is a claim about any body carrying 60 likes. Only `/recommendations` is exercised, so a cap applied only when `path == \"/recommendations\"` would pass. This is a Recommendation because the three exercised paths do carry C1 as stated. One fix is a `/videos/similar` case. The other is to narrow the docstring to name the routes rather than the readers.\n2. bounds (rules/testing.md) \u2014 tests/tmp/test_14_batch_like_resolution_phase4.py:41\n   Only the 60-entry input runs. Nothing tests the edges of the cap: exactly 50, one past it (51), or empty. Nothing tests malformed entries either. The docstring says outright that \"every like is well formed\", so it is never shown whether the cap takes the first 50 entries of the raw body or the first 50 entries that survive sanitising. Both readers slice before they sanitise (server.py:492, :1109), and that behaviour is untested.\n3. normal-and-abnormal-paths (rules/testing.md) \u2014 tests/tmp/test_14_batch_like_resolution_phase4.py:105\n   Every test takes the success path. No test sends an over-cap body down a failure path, for example an Engine error on the capped metadata call (the 502 branches at server.py:888, :1024) or a non-list `likes` (the 400 at server.py:489).\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `code_under_test` lists tests/tmp/test_client_like_batching.py, and that file does not exist. It was not read. None of the verdict depends on it.\n2. `fixtures_path` was not supplied. I read the conftest the test imports (tests/active/conftest.py: `ClientBackend`, `RateLimiter`, `client_server`, `ensure_user_schema`). I confirmed that `resolve_profile` and `load_liked_keys` resolve to client/backend/lib/profiles.py:42 and client/backend/lib/users_store.py:145. I did not read their bodies.",
        "body": "### devsecops-test-shape-auditor\n\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\nFails at tests/tmp/test_14_batch_like_resolution_phase4.py:109 on `assert received == [(METADATA, {\"entries\": [... for i in range(50)]})]`. `MAX_CLIENT_LIKES = 200` (client/backend/server.py:51) lets all 60 entries through, so the recorded request carries 60 entries instead of 50. The same mismatch fails line 123 in the import test. In the recommendations test, line 131 passes and line 133 fails because the forwarded `likes` list holds 60 pairs.\n\nNOT ASSESSED\n1. `code_under_test` listed tests/tmp/test_client_like_batching.py, which does not exist. Nothing from it was read.\n2. `fixtures_path` was not supplied. The test builds its own Engine stand-in and Client backend at lines 44-102. The imports it depends on were resolved by reading and grep: `ClientBackend`, `client_server`, `RateLimiter` and `ensure_user_schema` in tests/active/conftest.py, `resolve_profile` in client/backend/lib/profiles.py, `load_liked_keys` in client/backend/lib/users_store.py, and the `ClientBackendServer.__init__` signature at client/backend/server.py:203. The bodies of `resolve_profile`, `load_liked_keys` and `_parse_client_likes` were not read.\n\n### devsecops-test-claim-auditor\n\nCLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (14 clauses: 3 must_prove, 6 docstring, 5 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | a 60-like body reaches the Engine capped at 50 entries | :109, :123, :133 | the current cap of 200 (all 60 forwarded), a cap of 49 or 51, and a cap on one route only among the three exercised. Each is an exact equality on the whole recorded request list | CARRIED |\n| C1b | must_prove | the entries forwarded are the *first* 50 | :109, :123, :133 | keeping the last 50, an arbitrary 50, or reordered entries. The expected list is `u-00`..`u-49` in order | CARRIED |\n| C1c | must_prove | \"reaches the Engine\", in one request, carrying those entries and nothing else | :109, :123, :133 | a split into several Engine calls, an extra Engine call, or entries reshaped on the way. `received == [ ... ]` holds exactly one element | CARRIED |\n| D1 | docstring | \"at most the first 50 \u2026 on each of the three paths that read `MAX_CLIENT_LIKES`\" | :109, :123, :133 | a cap that misses any of the three readers at server.py:492, :885, :1018 | CARRIED |\n| D2 | docstring | likes page: \"one `/internal/videos/metadata` request whose `entries` are the first 50\" | :109 | the uncapped or last-50 forward, or a second request | CARRIED |\n| D3 | docstring | likes page: \"answered 200 with those 50 videos' rows\" | :110 | a non-200 status, missing or extra rows, rows out of order. Compares the exact `video_id` list `id-00`..`id-49` | CARRIED |\n| D4 | docstring | import: one metadata request of the first 50 and \"answers `{\"imported\": 50}`\" | :123, :124 | the uncapped forward, or a count other than 50 (for example 60 under the 200 cap) | CARRIED |\n| D5 | docstring | import: \"leaves the profile liking exactly those 50 videos\" | :125 | storing all 60, storing a different 50, or storing extras. Set equality read back through `load_liked_keys` | CARRIED |\n| D6 | docstring | keyless `POST /recommendations` \"answered 200 and forwards one request whose `likes` are the first 50 `{uuid, host}` pairs\" | :131, :133 | a non-200 status, the uncapped forward, the last 50, a second forwarded request, or likes reshaped away from `{uuid, host}` | CARRIED |\n| N1 | name | \"a 60-like likes page reaches the engine as its first 50\" | :109 | same as D2 | CARRIED |\n| N2 | name | \"and is answered with their rows\" | :110 | same as D3 | CARRIED |\n| N3 | name | \"a 60-like import reaches the engine as its first 50\" | :123 | same as D4 (Engine half) | CARRIED |\n| N4 | name | \"and likes exactly those\" | :125 | same as D5 | CARRIED |\n| N5 | name | \"a keyless 60-like recommendations request forwards its first 50 likes\" | :133 | same as D6 (forward half) | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. whole-claim (rules/testing.md) \u2014 tests/tmp/test_14_batch_like_resolution_phase4.py:1\n   The docstring says the three paths are \"the `MAX_CLIENT_LIKES` readers the plan's grep found\". The grep is right that there are three reads (server.py:492, :885, :1018). But the read at :492 is the proxy sanitiser, and two routes go through it: `/recommendations` and `/videos/similar` (`PROXY_ALLOWED_BODY_KEYS`, server.py:101-102). C1 is a claim about any body carrying 60 likes. Only `/recommendations` is exercised, so a cap applied only when `path == \"/recommendations\"` would pass. This is a Recommendation because the three exercised paths do carry C1 as stated. One fix is a `/videos/similar` case. The other is to narrow the docstring to name the routes rather than the readers.\n2. bounds (rules/testing.md) \u2014 tests/tmp/test_14_batch_like_resolution_phase4.py:41\n   Only the 60-entry input runs. Nothing tests the edges of the cap: exactly 50, one past it (51), or empty. Nothing tests malformed entries either. The docstring says outright that \"every like is well formed\", so it is never shown whether the cap takes the first 50 entries of the raw body or the first 50 entries that survive sanitising. Both readers slice before they sanitise (server.py:492, :1109), and that behaviour is untested.\n3. normal-and-abnormal-paths (rules/testing.md) \u2014 tests/tmp/test_14_batch_like_resolution_phase4.py:105\n   Every test takes the success path. No test sends an over-cap body down a failure path, for example an Engine error on the capped metadata call (the 502 branches at server.py:888, :1024) or a non-list `likes` (the 400 at server.py:489).\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `code_under_test` lists tests/tmp/test_client_like_batching.py, and that file does not exist. It was not read. None of the verdict depends on it.\n2. `fixtures_path` was not supplied. I read the conftest the test imports (tests/active/conftest.py: `ClientBackend`, `RateLimiter`, `client_server`, `ensure_user_schema`). I confirmed that `resolve_profile` and `load_liked_keys` resolve to client/backend/lib/profiles.py:42 and client/backend/lib/users_store.py:145. I did not read their bodies.",
        "map": [
          {
            "id": "C1a",
            "source": "must_prove",
            "clause": "a 60-like body reaches the Engine capped at 50 entries",
            "assertion": ":109, :123, :133",
            "excludes": "the current cap of 200 (all 60 forwarded), a cap of 49 or 51, and a cap on one route only among the three exercised. Each is an exact equality on the whole recorded request list",
            "status": "CARRIED"
          },
          {
            "id": "C1b",
            "source": "must_prove",
            "clause": "the entries forwarded are the *first* 50",
            "assertion": ":109, :123, :133",
            "excludes": "keeping the last 50, an arbitrary 50, or reordered entries. The expected list is `u-00`..`u-49` in order",
            "status": "CARRIED"
          },
          {
            "id": "C1c",
            "source": "must_prove",
            "clause": "\"reaches the Engine\", in one request, carrying those entries and nothing else",
            "assertion": ":109, :123, :133",
            "excludes": "a split into several Engine calls, an extra Engine call, or entries reshaped on the way. `received == [ ... ]` holds exactly one element",
            "status": "CARRIED"
          },
          {
            "id": "D1",
            "source": "docstring",
            "clause": "\"at most the first 50 \u2026 on each of the three paths that read `MAX_CLIENT_LIKES`\"",
            "assertion": ":109, :123, :133",
            "excludes": "a cap that misses any of the three readers at server.py:492, :885, :1018",
            "status": "CARRIED"
          },
          {
            "id": "D2",
            "source": "docstring",
            "clause": "likes page: \"one `/internal/videos/metadata` request whose `entries` are the first 50\"",
            "assertion": ":109",
            "excludes": "the uncapped or last-50 forward, or a second request",
            "status": "CARRIED"
          },
          {
            "id": "D3",
            "source": "docstring",
            "clause": "likes page: \"answered 200 with those 50 videos' rows\"",
            "assertion": ":110",
            "excludes": "a non-200 status, missing or extra rows, rows out of order. Compares the exact `video_id` list `id-00`..`id-49`",
            "status": "CARRIED"
          },
          {
            "id": "D4",
            "source": "docstring",
            "clause": "import: one metadata request of the first 50 and \"answers `{\"imported\": 50}`\"",
            "assertion": ":123, :124",
            "excludes": "the uncapped forward, or a count other than 50 (for example 60 under the 200 cap)",
            "status": "CARRIED"
          },
          {
            "id": "D5",
            "source": "docstring",
            "clause": "import: \"leaves the profile liking exactly those 50 videos\"",
            "assertion": ":125",
            "excludes": "storing all 60, storing a different 50, or storing extras. Set equality read back through `load_liked_keys`",
            "status": "CARRIED"
          },
          {
            "id": "D6",
            "source": "docstring",
            "clause": "keyless `POST /recommendations` \"answered 200 and forwards one request whose `likes` are the first 50 `{uuid, host}` pairs\"",
            "assertion": ":131, :133",
            "excludes": "a non-200 status, the uncapped forward, the last 50, a second forwarded request, or likes reshaped away from `{uuid, host}`",
            "status": "CARRIED"
          },
          {
            "id": "N1",
            "source": "name",
            "clause": "\"a 60-like likes page reaches the engine as its first 50\"",
            "assertion": ":109",
            "excludes": "same as D2",
            "status": "CARRIED"
          },
          {
            "id": "N2",
            "source": "name",
            "clause": "\"and is answered with their rows\"",
            "assertion": ":110",
            "excludes": "same as D3",
            "status": "CARRIED"
          },
          {
            "id": "N3",
            "source": "name",
            "clause": "\"a 60-like import reaches the engine as its first 50\"",
            "assertion": ":123",
            "excludes": "same as D4 (Engine half)",
            "status": "CARRIED"
          },
          {
            "id": "N4",
            "source": "name",
            "clause": "\"and likes exactly those\"",
            "assertion": ":125",
            "excludes": "same as D5",
            "status": "CARRIED"
          },
          {
            "id": "N5",
            "source": "name",
            "clause": "\"a keyless 60-like recommendations request forwards its first 50 likes\"",
            "assertion": ":133",
            "excludes": "same as D6 (forward half)",
            "status": "CARRIED"
          }
        ],
        "map_problem": ""
      }
    ]
  },
  "refactors": "<refactors>\nengine/server/data/metadata.py \u2014 `_select_metadata` returns `[dict(row) for row in rows]` in place of the 29-entry hand-written row builder. A probe run showed that a `sqlite3.Row` is keyed by its SELECT names (`v.video_id` \u2192 `video_id`, `c.display_name AS channel_display_name` \u2192 `channel_display_name`) and that `dict(row)` keeps SELECT order, which was the builder's key order. So the rows have the same keys, values and order as before.\nengine/server/data/metadata.py \u2014 new public `uuid_key(entry)` builds the `video_uuid::instance_domain` key, and `fetch_metadata_by_uuids` uses it in place of its inline f-string (same output for a dict row).\nengine/server/api/handlers/internal_client_reads.py \u2014 removed the private `_uuid_key` copy. The handler imports `uuid_key` from `data.metadata`, so the key it looks rows up by and the key the data layer stores them under come from one function and cannot drift apart.\nengine/server/api/handlers/internal_client_reads.py \u2014 `_parse_entries` (the centroids parser) now uses the `_stripped` helper phase 2 added, in place of its own isinstance/strip checks, and `_stripped` moved above it. It still accepts, skips, strips, dedups and orders items exactly as before.\nclient/backend/server.py \u2014 dropped the early empty-likes 200 in `_handle_user_profile_likes_from_client`. `fetch_metadata_for_entries` already returns `[]` without an HTTP call for an empty list, so the response is still 200 `{\"likes\": [], \"updatedAt\": ...}` with zero Engine requests. This also matches `_handle_likes_import`, which already relied on that short-circuit.\n</refactors>\n\n<left_out>\nDeduping `fetch_metadata` (the rowid lookup) onto the shared SELECT/row builder: this build never changed it (phase 1 \"Not changed\"), and grep finds no test under tests/ that calls it. Changing it without any gating coverage is a risk I would not take without a run; it needs its own change with a test.\nReplacing the handler's `_like_key` with `recommendations.keys.like_key`: the output is the same for dicts, but the duplication predates this build and is not part of the new functionality.\nMerging `_parse_client_likes` with the `/recommendations` proxy likes sanitiser in client/backend/server.py: they emit different key shapes (`video_uuid/instance_domain` vs `uuid/host`), and the duplication predates this build.\nFactoring the shared chunk-and-OR loop of `fetch_metadata_by_ids`/`fetch_metadata_by_uuids` into one helper: the two differ on purpose in parenthesisation (Open item A, option 1) and in how they key rows. A helper would need flags for both and would not be simpler.\nNot confirmed by a run: I did not run the checkpoints (the workflow's run is the one that counts). The `dict(row)` swap rests on the probe; the other changes are identity-preserving rewrites. The phase 1 test (exact 29 keys, full-row equality) and the phase 2/3 checkpoints are what will confirm them.\nHousekeeping I cannot do (no delete tool): my probe `tests/tmp/probe_refactor_row_keys.py` (fails on purpose with `assert False`) should be deleted, along with the earlier probes `tests/tmp/probe_14_phase1.py`, `probe_14_phase2.py`, `probe_14_phase3.py`, `probe_14_phase4.py`, `probe_14_n4.py`, `probe_phase1_against_impls.py`, `probe_phase1_metadata.py` and `probe_phase4_cap.py`. This step's `{rat_tail_rules}` placeholder was not filled in, so I measured the pass against the role's general rules; none of the refactors adds or changes a `rat-tail:` comment.\n</left_out>\n\n<needs_fresh_red>\nnone\n</needs_fresh_red>\n\n<observation>\nA probe showed that sqlite3.Row is keyed by SELECT names and that dict(row) keeps SELECT order, so the new metadata path now has one SELECT, one row builder and one uuid key shared by the data layer and the handler, with no behaviour change on any path a checkpoint gates.\n</observation>"
}
```
dev-flow:state -->

## Entries from earlier runs of this build

## 2026-09-27 - Step 0 - baseline

Resolved paths: {
  "active": "tests/active",
  "working": "tests/tmp",
  "plans": "docs/project/plans",
  "delete_me": "delete_me",
  "archive": "tests/archive",
  "project_dir": "/home/enduser/code/PeerTube-browser/.worktrees/fix-14-batch-like-resolution",
  "record": "tests/last_test_validation.json",
  "output": "tests/last_test_output.txt"
}

Pre-build suite exited 0. Baseline variant: False.

```
unchanged since 2026-09-27T02:58:33-04:00 — every fingerprint still holds
  146 passed (46.5s)
```

## 2026-09-27 - Step 1 - Gather requirements

Approved by the operator.

### requirements

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

### conflicts

Brief "the likes page returns the same rows, in the same order, as before" vs the tree: the old resolve path (`engine/server/data/embeddings.py` `_seed_from_row`) dropped videos whose embedding blob was empty or did not match `embedding_dim`, while `fetch_metadata_by_ids` has no such check, so such a video now appears on the likes page and is imported. Operator approved accepting this difference.
Brief "rows come back in the order of their first matching entry" / "a video reached by both forms appears once" vs the tree: `videos` is keyed on `(video_id, instance_domain)` only, and `(video_uuid, instance_domain)` is not unique, so one uuid entry could match several videos, where resolve took an arbitrary `LIMIT 1`. Resolved with the operator: a uuid entry yields at most one row, the lowest `video_id`.
Plan "Batch context" line numbers (`:49`, `:446`, `:837-843`, `:970-980`) vs the tree: after wave 1 merged they are `server.py:52`, `:493`, `:872-900` and `:1012-1029`. The functions are unchanged. Only the locations moved.

## 2026-09-27 - Step 2 - Develop a solution

Approved by the operator.

### initial_solution

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

### conflicts

none

## 2026-09-27 - Step 3 - Identify every file, function and doc affected

Recorded ungated, at the operator direction.

### impacts


<impacts>
<impact path="engine/server/data/metadata.py" element="fetch_metadata_by_ids (lines 110-205): body moved into a new private helper">
**What changes.** The 29-column SELECT (lines 133-170), the inner `video_embeddings` join, the left `channels` join, the `error_count` clause (lines 127-130) and the row-dict build (lines 174-204) move into one private helper. `fetch_metadata_by_ids` keeps its signature `(conn, entries, error_threshold=None) -> dict[str, dict]`. It keeps building its `OR` fragment `(v.video_id = ? AND v.instance_domain = ?)` per 450-entry chunk through `_chunk`, and it still keys the result on `like_key(row)` (`video_id::instance_domain`, `engine/server/api/recommendations/keys.py:8`).

**What depends on it.**
- `handle_internal_videos_metadata` (`engine/server/api/handlers/internal_client_reads.py:113`).
- `similarity_candidates._build_rows` (`engine/server/data/similarity_candidates.py:170,175`), which is the hot path for similar and up-next rows. Plan 07's archive notes it is also a row source for the random cache.

**Regression risk: medium.**
- Parameter order must stay pairs first, then the threshold last, matching the placement of `{error_clause}` after the WHERE fragment. The threshold is only appended when `error_threshold > 0`.
- The row-dict keys must stay exactly the same 29 keys. Missing `video_uuid` or `instance_domain` would break the uuid path's keying and `record_like` on import.
- If the helper returns a list of dicts instead of `sqlite3.Row`, the id path must key on `like_key(dict)`. `like_key` handles both dicts and Rows.
- If an ORDER BY is added to the shared SQL for the uuid path, it must not change which rows the id path returns. It cannot, because the id result is a dict keyed by video, but the helper's signature has to let the uuid caller add its ORDER BY (or sort in Python).
- The plan's before/after regression test on a fixture DB is the guard. Nothing in `tests/active` covers the id path in-process today. Only the live-Engine tests (`test_server.py`, `test_blocks.py`, `test_similar.py`) exercise it indirectly.
</impact>
<impact path="engine/server/data/metadata.py" element="new fetch_metadata_by_uuids (sibling function)">
**What changes.**
- New public function beside `fetch_metadata_by_ids`, with the same argument style `(conn, entries, error_threshold=None)`.
- It deduplicates `(video_uuid, instance_domain)` pairs before chunking, then chunks at 450 with the existing `_chunk` (line 105).
- WHERE is `(v.video_uuid, v.instance_domain) IN ((?, ?), ...)`, the row-value form already used at `engine/server/data/embeddings.py:228`, with `ORDER BY v.video_id` in each chunk.
- It keeps the first row per `video_uuid::instance_domain` and returns a dict under that key.
- It needs a docstring (every function in the file has one).

**What depends on it.** Only the new metadata handler path.

**Regression risk: low for existing callers (new code), medium for correctness.**
- The key must be built from the row's `video_uuid` and `instance_domain`. SQL `=` / `IN` on TEXT is a binary comparison, so the row values equal the stripped entry values exactly. Case differences do not match, which is the same as the old `_fetch_seed_by_uuid`.
- The lowest-`video_id` choice is made after the error filter, as the plan states.
- Performance: the plan's "Missing index" risk is **wrong**. `idx_videos_uuid_instance ON videos (video_uuid, instance_domain)` exists (`engine/server/data/videos.py:21-22`) and is created at Engine startup (`engine/server/api/server.py:337` `ensure_video_indexes(db)`). A temp-DB unit test will not have it unless it calls `ensure_video_indexes`. That is irrelevant to correctness.
- 450 pairs is 900 bound values plus 1 for the threshold, which is under the 999 limit of old SQLite builds.
</impact>
<impact path="engine/server/data/metadata.py" element="fetch_metadata (rowid-keyed, lines 11-102) and _chunk (lines 105-107)">
**What changes.** Nothing. The plan leaves `fetch_metadata` untouched, so it remains a second copy of the SELECT and row dict. `_chunk` is reused by the new function.

**What depends on them.**
- `fetch_metadata` is used by `engine/server/api/handlers/similar.py:34`, `engine/server/data/ann.py:18`, `engine/server/data/random_videos.py:8` and `engine/server/data/search.py:20`.
- Note: `_chunk` is duplicated in `engine/server/data/embeddings.py:307`. Import the one in `metadata.py`, not that one.

**Regression risk: none if untouched.** The Step 4 check is that the diff does not reach lines 11-102.
</impact>
<impact path="engine/server/data/similarity_candidates.py" element="_build_rows (lines 155-199), a direct caller of fetch_metadata_by_ids">
**What changes.** No edit.

**Why it matters.** It depends on the refactored `fetch_metadata_by_ids` returning the same dict keyed by `like_key`. It looks rows up with `metadata.get(like_key(entry))` (line 195) and compares `like_key(meta)` to the source key (line 198). It calls with and without `server.db_lock` (lines 169-179). Its entries come from ANN/cache and may carry extra keys. `fetch_metadata_by_ids` reads only `video_id` and `instance_domain` (`entry.get(...)`), and that must stay true.

**Regression risk: medium, and it was not named in the plan's caller list.** Any change to key format, row-dict content or the chunk boundary in the helper silently empties or alters similar and up-next pages. It is covered only indirectly by the live-Engine `tests/active/test_similar.py` and by feed tests.
</impact>
<impact path="engine/server/api/handlers/internal_client_reads.py" element="new metadata entry parser (beside _parse_entries, line 20)">
**What changes.** A second parser, used only by `handle_internal_videos_metadata`.
- It returns None when `body.get("entries")` is not a list. Note `_parse_entries` also guards `isinstance(body, dict)`, and the new parser must too.
- It skips non-dicts and items without a non-empty stripped string `instance_domain`.
- A valid `video_id` means id-form, even when `video_uuid` is present. Otherwise a valid `video_uuid` means uuid-form. Otherwise the item is skipped.
- It deduplicates per form on its own key, keeping the first occurrence, and returns one ordered list of tagged entries.

It should reuse `_like_key` (line 15) for the id key, and needs a matching uuid key plus a docstring.

**What depends on it.** `handle_internal_videos_metadata` only.

**Regression risk: medium.**
- The id-form entries handed to `fetch_metadata_by_ids` must be the same stripped `{video_id, instance_domain}` dicts `_parse_entries` produced. If the tag is stored inside the dict it must not break `entry.get("video_id")`. It would not, but keep the id list clean.
- Behaviour change for id callers, low probability: an entry whose `video_id` is empty or whitespace but which carries a valid `video_uuid` was skipped before and now resolves via uuid. `GET /api/user-profile/likes` sends `fetch_recent_likes` rows (`video_id`, `video_uuid`, `instance_domain`, `updated_at`). `record_like` stores `str(video.get("video_id") or "")`, so a stored like with an empty `video_id` would now appear. All current writers pass a canonical non-empty `video_id` (`server.py:775` check; import uses Engine rows), so no such rows are expected.
</impact>
<impact path="engine/server/api/handlers/internal_client_reads.py" element="handle_internal_videos_metadata (lines 95-126)">
**What changes.**
- The new parser replaces the `_parse_entries` call at line 103. The 400 `Missing entries` (line 105) and the empty 200 before any lock (lines 108-110) stay.
- The entries split into id and uuid lists.
- One `with server.db_lock:` hold calls `fetch_metadata_by_ids` and/or `fetch_metadata_by_uuids`, skipping empty lists, both with `error_threshold=getattr(server, "video_error_threshold", None)`.
- After the lock, an ordered walk emits each row once, keyed on `video_id::instance_domain` (the row's `like_key`).
- The response `{"ok", "count", "rows"}` is unchanged. The docstring ("canonical (video_id, instance_domain) entries") needs updating.

**What depends on it.**
- The route `/internal/videos/metadata` (`engine/server/api/handlers/similar.py:402-403`).
- Client callers `_handle_user_profile_likes_get`, `_handle_block_add`, `_handle_user_profile_likes_from_client` and `_handle_likes_import`, all via `fetch_metadata_for_entries`.

**Regression risk: medium-high.**
- For id-only bodies, order and dedup must be identical: the old loop emitted in entry order and deduplicated through `_parse_entries`.
- The cross-form dedup must key on the returned row's `video_id::instance_domain`, not the entry's. Otherwise the same video reached by both forms appears twice.
- The lock must be held once. `server.db_lock` is a plain lock, so do not nest `with` blocks in the helpers. The data functions take `conn` only, as today.
</impact>
<impact path="engine/server/api/handlers/internal_client_reads.py" element="_parse_entries (line 20) and handle_internal_dislike_centroids (lines 129-158)">
**What changes.** Nothing (R1). Centroids keeps `_parse_entries`, so uuid-only entries are skipped as malformed and count toward nothing against `DISLIKE_MAX_ENTRIES`.

**What depends on them.** Client `compute_dislike_centroids` (`client/backend/lib/engine_api_client.py:112`) and `_store_reaction` (`server.py:859`). Covered by `tests/active/test_dislike_profile.py`.

**Regression risk: low.** The only risk is an accidental edit to `_parse_entries` or `_like_key` while adding the sibling parser. The new centroids-ignores-uuid test guards this.
</impact>
<impact path="engine/server/api/handlers/internal_client_reads.py" element="module imports (lines 6-12)">
**What changes.** Line 9 becomes `from data.metadata import fetch_metadata_by_ids, fetch_metadata_by_uuids`.

**What depends on it.** The module is imported at module level by `engine/server/api/handlers/similar.py:77-81`, which the Engine server imports at startup. It also imports numpy (line 6) and `recommendations.dislike_profile`, so any in-process test of it needs the Engine interpreter and both `engine/server` and `engine/server/api` on `sys.path`. `data.metadata` imports `recommendations.keys`.

**Regression risk: high impact, low probability.** A misspelled import name takes down the whole Engine at startup, not just this endpoint. Every live-Engine test would fail at the `engine` fixture (`tests/active/conftest.py:102`).
</impact>
<impact path="engine/server/api/handlers/similar.py" element="_dispatch_post routing (lines 390-407) and handler imports (lines 77-81)">
**What changes.** No edit. The route stays `/internal/videos/metadata`, behind `_bridge_authorized` (line 394). The module docstring line 11 ("internal Client metadata batch lookup") stays accurate.

**Why it matters.** It is the only dispatcher of the endpoint and imports the edited module at load time. See the import-risk entry above.

**Regression risk: low.**
</impact>
<impact path="engine/server/data/embeddings.py" element="fetch_seed_embeddings_for_likes (line 191), fetch_seed_embedding / _fetch_seed_by_uuid / _seed_from_row (lines 104-188)">
**What changes.** Nothing.
- `fetch_seed_embeddings_for_likes` is the precedent for the row-value IN (line 228). It is unchunked; the new function adds chunking.
- `_fetch_seed_by_uuid` (the old resolve path, used by `/internal/videos/resolve`) stays for `_handle_user_action` and `_handle_block_add`.

**Behaviour differences this build accepts versus the old resolve** (operator-approved, must stay visible in tests and docs):
- `_seed_from_row` dropped rows with an empty or mismatched embedding blob (line 178). The metadata path does not.
- Resolve had no error-count filter and an arbitrary `LIMIT 1` (line 140). The new path is error-filtered and picks the lowest `video_id`.

**Regression risk: none to this file.**
</impact>
<impact path="engine/server/data/videos.py" element="ensure_video_indexes: idx_videos_uuid_instance (lines 21-22)">
**What changes.** Nothing.

**Why it matters.** It contradicts the plan's risk "No index on `(video_uuid, instance_domain)` is confirmed". The index exists and is created on every Engine start (`engine/server/api/server.py:337`), so the uuid batch query is an index lookup, as the id query is (`idx_videos_id_instance`). The plan's risk note should be corrected. No action is needed in code.

**Regression risk: none.**
</impact>
<impact path="engine/server/api/http_utils.py" element="read_json_body (lines 46-63)">
**What changes.** Nothing.

**Why it matters.** The 1,000,000-byte body cap (line 52) is the only bound on the entry count a direct bridge caller can send to `/internal/videos/metadata`, as the plan's lock-hold risk says. With 450-pair chunking, one lock hold may cover several statements for a large body, which is the same exposure the id path already has.

**Regression risk: none.**
</impact>
<impact path="engine/server/api/recommendations/keys.py" element="like_key (line 8)">
**What changes.** Nothing.

**Why it matters.** It is used by the refactored id path, and likely by the handler's cross-form dedup of emitted rows. It accepts dicts and `sqlite3.Row`, and returns `"{video_id or ''}::{instance_domain or ''}"`, the same format as `_like_key` in `internal_client_reads.py:15`.

**Regression risk: none.**
</impact>
<impact path="client/backend/lib/engine_api_client.py" element="resolve_videos_by_uuid_host (lines 136-166): deleted">
**What changes.** The function is removed (R6).

**What depends on it.** Only `client/backend/server.py:32` (import), `:888` (import handler) and `:1024` (likes page). A worktree grep outside `delete_me/` found no other readers. The `delete_me/*.bak-*` copies reference it but are stale and not imported. `docs/project/security-audit/run-1/REPORT.md:277` and `findings.json` name it historically.

**Regression risk: low.** A missed call site is an import-time `ImportError` in `server.py`, which `tests/active/conftest.py:39` (`import server as client_server`) would surface immediately across the whole Client suite.
</impact>
<impact path="client/backend/lib/engine_api_client.py" element="fetch_metadata_for_entries (lines 92-109) and resolve_video_seed (lines 66-89)">
**What changes.**
- `fetch_metadata_for_entries`: no logic change. It now also carries `{video_uuid, instance_domain}` entries. Its docstring ("canonical video identity entries") could mention the uuid form. It returns `[]` without an HTTP call for an empty list (line 97), which the import path relies on. It raises `EngineApiError` on a non-200 status or an invalid payload.
- `resolve_video_seed` stays, for `_handle_user_action` (`server.py:758`) and `_handle_block_add` (`server.py:946`).

**Regression risk: low.**
</impact>
<impact path="client/backend/server.py" element="engine_api_client import (lines 30-32)">
**What changes.** `resolve_videos_by_uuid_host` is dropped from the import. `fetch_metadata_for_entries` and `resolve_video_seed` remain.

**What depends on it.** Module load of the Client backend.

**Regression risk: low.** Merge overlap with plan 13 in wave 2 on the same import block is possible, so locate the change by name.
</impact>
<impact path="client/backend/server.py" element="MAX_CLIENT_LIKES = 200 → 50 (line 52)">
**What changes.** The constant value.

**Readers** (grep outside `delete_me/`):
- line 493 (proxy trim);
- line 886 (`_handle_likes_import`);
- line 1019 (`_handle_user_profile_likes_from_client`).

No other reader. It sits next to `MAX_LIKES = 100` (line 51, out of scope). It matches the browser's `MAX_LIKES = 50` in `client/frontend/src/data/local-likes.ts:25` and ADR-0003.

**Regression risk: low.** Tests that post more than 50 likes and expect all of them would now see 50. None found in `tests/active`: the `test_profiles.py` import posts 3.
</impact>
<impact path="client/backend/server.py" element="/recommendations and /videos/similar POST proxy likes trim (lines 487-503)">
**What changes.** No code edit. `likes[:MAX_CLIENT_LIKES]` now slices at 50 before skipping malformed items.

**Context.** The Engine itself answers 400 `Too many likes in request body` above `DEFAULT_CLIENT_LIKES_MAX` = 5 (`engine/server/api/recommendations/docs/OVERVIEW.md:22`). So in practice a keyless request with more than 5 likes is already refused downstream. A keyed request has its likes replaced by the profile's five (`client/README.md:26`). The "proxy forwards at most 50" test therefore needs a capturing stand-in Engine, not the live one.

**Regression risk: low.**
</impact>
<impact path="client/backend/server.py" element="_parse_client_likes (lines 1105-1121)">
**What changes.** No edit. It slices `raw[:max_items]` before validation, returns stripped `{video_uuid, instance_domain}` dicts, and does not deduplicate. It now feeds `fetch_metadata_for_entries` directly, and its output keys match the new Engine parser's uuid form exactly.

**Note.** It is distinct from the Engine's `similar._parse_client_likes`, which `tests/active/test_similar.py:259` patches.

**Regression risk: low.** If its output key names ever change, the Engine skips every entry silently and returns an empty likes page.
</impact>
<impact path="client/backend/server.py" element="_handle_likes_import (lines 872-900)">
**What changes.**
- The `resolve_videos_by_uuid_host` call (line 888) becomes one `fetch_metadata_for_entries(self.server.engine_ingest_base, likes)` call. The 502 text stays `Engine resolve failed: ...` (line 890); plan 15 rewrites it later.
- The loop iterates the returned rows. It checks `is_disliked(conn, profile_id, row["video_id"], row["instance_domain"])` and otherwise calls `record_like` with the row's `video_id`, `video_uuid` and `instance_domain` (passing the full row also works, since `record_like` reads only those three keys; the plan says build the three-key dict).
- The response stays `{"imported": n}`.

**Behaviour changes** (accepted):
- Videos at or over the error threshold are no longer imported.
- Videos with a bad embedding blob now are imported.
- The lowest `video_id` is chosen on uuid collisions.

An empty parse makes no Engine call.

**Regression risk: medium.** It is covered by `tests/active/test_profiles.py::test_importing_browser_likes_marks_each_imported_video_liked_and_no_other` (live Engine; its dataset query already filters `error_count = 0` and joins embeddings, so it stays green). Frontend coupling: `importLocalLikes` clears **all** local likes after a 200 (`client/frontend/src/data/reactions.ts:81`), so any entry past the 50th, or any unresolvable one, is dropped for good. The browser caps local likes at 50, so this only affects stale storage.
</impact>
<impact path="client/backend/server.py" element="_handle_user_profile_likes_from_client (lines 1012-1029)">
**What changes.**
- The resolve and metadata calls (lines 1024-1025) become one `fetch_metadata_for_entries(self.server.engine_ingest_base, likes)` call.
- The empty-parse 200 (lines 1020-1022), the 502 `Engine metadata failed: ...` (line 1027) and the response `{"likes": rows, "updatedAt"}` stay.
- Deduplication is left to the Engine.

**What depends on it.** Keyless `POST /api/user-profile/likes` from `client/frontend/src/data/user-profile.ts:23`.

**Regression risk: medium.** Row order and dedup now depend entirely on the Engine handler's ordered walk. There was no existing test for this route's POST form; the plan's stand-in-Engine tests fill that gap.
</impact>
<impact path="client/backend/server.py" element="_handle_user_profile_likes_get (lines 995-1010) and _handle_block_add (lines 927-963): id-form callers of the metadata endpoint">
**What changes.** No edit.
- `_handle_user_profile_likes_get` sends the rows from `fetch_recent_likes`: `video_id`, `video_uuid`, `instance_domain`, `updated_at`. With a non-empty `video_id` these are id-form under the new parser, so the rows and their order are unchanged.
- `_handle_block_add` sends a single `{video_id, instance_domain}`.

**What depends on them.** `tests/active/test_server.py:94` (GET likes against the live Engine), `tests/active/test_blocks.py`, and `tests/active/test_profiles.py` (via `_liked`/`_read`).

**Regression risk: low-medium.** See the parser entry for the empty-`video_id`-with-uuid edge case.
</impact>
<impact path="client/backend/server.py" element="_handle_user_action / _store_reaction (lines 742-870)">
**What changes.** Nothing. It keeps using `resolve_video_seed` → `/internal/videos/resolve` (line 758). This is out of scope.

**Regression risk: none.** Listed only to confirm `resolve_video_seed` must not be removed along with `resolve_videos_by_uuid_host`.
</impact>
<impact path="client/backend/lib/users_store.py" element="record_like (lines 79-117) and fetch_recent_likes (lines 120-)">
**What changes.** Nothing.
- `record_like` reads only `video_id`, `instance_domain` and `video_uuid` from its dict, so an Engine metadata row, or a three-key dict built from it, works.
- `fetch_recent_likes` output is the id-form body of the GET likes path.

**Regression risk: none.**
</impact>
<impact path="client/backend/lib/dislikes.py" element="is_disliked (line 33)">
**What changes.** Nothing. It is called on import with the row's `video_id` and `instance_domain` instead of the resolved entry's; the values are the same.

**Regression risk: none.**
</impact>
<impact path="client/frontend/src/data/local-likes.ts" element="MAX_LIKES = 50 (line 25)">
**What changes.** Nothing (frontend is out of scope). It is the browser-side bound ADR-0003 aligns `MAX_CLIENT_LIKES` to. The built bundle `client/frontend/dist/assets/key-rejected-*.js` carries `S=50`.

**Regression risk: none.**
</impact>
<impact path="client/frontend/src/data/reactions.ts" element="importLocalLikes (lines 65-83)">
**What changes.** Nothing. It posts all local likes to `/api/profile/likes/import` and clears local storage on any 2xx. With the server cap at 50 and Engine-side filtering, likes the server drops are cleared too. That is acceptable given the 50-item browser cap, but it is an interaction to note.

**Regression risk: low.**
</impact>
<impact path="client/frontend/src/data/user-profile.ts" element="keyless likes-page fetch (line 23)">
**What changes.** Nothing. It posts `{likes: [{uuid, host}]}` to `POST /api/user-profile/likes` and renders `likes` in response order, so it depends on the Engine walk preserving submitted order.

**Regression risk: low.**
</impact>
<impact path="tests/active/test_profiles.py" element="test_importing_browser_likes_marks_each_imported_video_liked_and_no_other (line 245)">
**What changes.** No edit is expected. It must stay green. It posts 3 embedded, `error_count = 0` videos to import against the live Engine, then checks `/api/profile/reaction` by uuid and host.

**Regression risk: low.** It must run in its own `validate_tests.py` invocation (Engine rate limit).
</impact>
<impact path="tests/active/test_server.py" element="test_a_keyed_request_s_500_entry_exclude_reaches_the_engine_and_none_of_it_is_returned (line 86ff, GET /api/user-profile/likes at line 94)">
**What changes.** No edit. It exercises the id-form metadata path end to end through `_handle_user_profile_likes_get` against the live Engine. It is the existing regression check that id callers are unchanged. It must run in its own invocation.

**Regression risk: low.**
</impact>
<impact path="tests/active/test_dislike_profile.py" element="/internal/dislikes/centroids tests (line 46)">
**What changes.** No edit. It guards that `_parse_entries` and centroids are unchanged. The plan adds a centroids-ignores-uuid check, which could live here or in the new Engine test file.

**Regression risk: low.**
</impact>
<impact path="tests/active/test_blocks.py" element="block-add tests (resolve + id-form metadata)">
**What changes.** No edit. It exercises `resolve_video_seed` plus single-entry id-form `fetch_metadata_for_entries` against the live Engine.

**Regression risk: low.**
</impact>
<impact path="tests/active/conftest.py" element="ENGINE_PY, engine / unpublished_client / client_backend fixtures, CLOSED_ENGINE">
**What changes.** Probably no edit. New tests reuse:
- `ENGINE_PY` (line 30);
- `client_server` and `ClientBackendServer` construction (lines 74-81), which takes the Engine base URL as an argument, the seam for a capturing stand-in Engine;
- `RateLimiter` and `ensure_user_schema`.

The session-scoped `engine` fixture touches the symlinked `whitelist.db` and `random-cache.db`.

**Regression risk: low.** If a stand-in-Engine fixture is added here rather than in the new test file, it affects every test module's collection.
</impact>
<impact path="tests/active/test_db.py" element="cited as the pattern for the new Engine tests">
**What changes.** Nothing.

**Correction to the plan.** `test_db.py` runs its child with `sys.executable` (line 81) and imports only `data.db` in-process. It is **not** an `ENGINE_PY` subprocess precedent.

The actual `ENGINE_PY -c <child>` pattern, passing `SERVER_DIR` and `SERVER_DIR/api` for `sys.path` and using `cwd=SERVER_DIR/"api"`, is:
- `tests/active/test_similar.py:287-291` (`_handle_likes`, `_LIKES_CHILD` with a hand-written `Handler` stub and a `SimpleNamespace` server);
- `tests/active/test_internal_events.py:173`.

The new handler tests need that pattern, because `internal_client_reads` imports numpy, and `data.metadata` imports `recommendations.keys` from `engine/server/api`.

**Regression risk: none** (test-design accuracy).
</impact>
<impact path="tests/active/test_similar.py" element="_LIKES_CHILD / _handle_likes (lines 230-291): nearest precedent for new Engine-handler unit tests">
**What changes.** No edit. It patches the Engine's `similar._parse_client_likes`, not the Client's. It shows how to drive a handler function with a stub handler and server under `ENGINE_PY`, patching `read_json_body` and `respond_json`. The new metadata-handler tests can patch those same names on `handlers.internal_client_reads` and give the stub server a counting `db_lock`, `db` (temp SQLite) and `video_error_threshold`.

**Regression risk: none.**
</impact>
<impact path="tests/ (new Engine and Client test files, location TBD in tests/tmp then tests/active)">
**What changes.** New tests are added.
- **Engine, in-process under `ENGINE_PY`:**
  - parser forms and dedup;
  - id-only unchanged;
  - mixed forms;
  - same video once;
  - lowest `video_id`;
  - threshold on uuid;
  - centroids ignores uuid;
  - one lock enter.
- **Client, stand-in stdlib HTTP Engine:**
  - one call per request;
  - 60 → 50;
  - proxy ≤ 50;
  - unknown omitted;
  - disliked skipped.

**Risks.**
- The temp DB schema must include `videos` (with `error_count`, `video_uuid` and every selected column), `video_embeddings` (`embedding_dim`, `model_name`) and `channels` (`display_name`, `avatar_url`), or the SELECT fails.
- The stand-in Engine must answer the bridge path and honour `bridge_headers`.
- The Client's `_post_json` has a 6 s timeout.
</impact>
<impact path="tests/last_test_validation.json" element="tracked test record (and tests/last_test_output.txt)">
**What changes.** It is regenerated by `validate_tests.py` runs in this worktree. It will conflict on merge: take main's copy and re-run `--compare` on the merged tree.

**Regression risk: merge-process only.**
</impact>
<impact path="delete_me/server.py.bak-M1 (and the other delete_me/*.bak-* and delete_me/similar.py.bak* copies)">
**What changes.** Nothing. These are stale copies that match greps for `resolve_videos_by_uuid_host` and `MAX_CLIENT_LIKES`. They are not imported and must not be edited, nor counted as readers.

**Regression risk: none.** Listed so Step 4 does not treat them as missed call sites.
</impact>
</impacts>


### docs_checklist


<doc path="client/README.md">
Line 15 (`POST /api/profile/likes/import`): state that at most 50 likes per body are read, that extras are dropped, and that a video the Engine does not know, or holds at or over its error threshold, is not imported (ADR-0003). Line 22 (`POST /api/user-profile/likes`): state that it resolves up to 50 browser likes in one Engine metadata call, and that unknown videos are omitted. Line 30 ("video resolve/metadata") stays accurate. Line 37 (`/internal/videos/resolve`) stays: it is still consumed by user actions and block-add.
</doc>
<doc path="engine/server/README.md">
Line 11 (`/internal/videos/metadata`): mention that entries may be `{video_id, instance_domain}` or `{video_uuid, instance_domain}` (an entry with both uses `video_id`), answered under one lock hold, one row per video in first-matching-entry order. Line 10 (resolve) is unchanged.
</doc>
<doc path="docs/project/adr/0003-metadata-endpoint-accepts-uuid-entries.md">
Already describes the decision; no change needed unless the build wants to record the lowest-`video_id` rule for shared `(video_uuid, instance_domain)` pairs and the dropped embedding-blob check as further consequences. Optional.
</doc>
<doc path="docs/project/issues/03-batch-like-resolution.md">
At harvest (on main, not in the worktree): set `Status:` to `bug, complete` and move it to `docs/project/issues/archive/`, per `docs/project/triage-labels.md`.
</doc>
<doc path="docs/project/plans/14-batch-like-resolution.md">
At harvest on main: archive with the build record, as earlier plans were (`docs/project/plans/archive/`). The "Risks" note that no index on `(video_uuid, instance_domain)` is confirmed is wrong: `idx_videos_uuid_instance` exists (`engine/server/data/videos.py:21`). Correct it in `16-14-batch-like-resolution.md` if the plan text is carried forward.
</doc>


### highest_risk


engine/server/data/metadata.py `fetch_metadata_by_ids` refactor into a shared helper: every existing metadata consumer goes through it, including `similarity_candidates._build_rows` (similar and up-next pages), which the plan's caller list omits. Any drift in param order, threshold placement, row-dict keys or `like_key` keying silently empties or alters rows, and no in-process test covers it today.
engine/server/api/handlers/internal_client_reads.py `handle_internal_videos_metadata` plus the new parser: id-only bodies must give byte-identical rows and order. Cross-form dedup must key on the returned row's `video_id::instance_domain`. There must be exactly one `db_lock` hold. The module is imported at Engine startup via `handlers/similar.py:77`, so an import mistake takes the whole Engine down.
client/backend/server.py `_handle_likes_import`: it now depends on Engine row content for `record_like`/`is_disliked`, and inherits error-threshold filtering. The frontend's `importLocalLikes` clears every local like on 200 (`client/frontend/src/data/reactions.ts:81`), so any like the server drops (past the 50th, unknown, errored) is lost for good, with no retry.

## 2026-09-27 - Step 4 - Reassess the implementation plan (pass 1)

Pass 1. New impacts: YES.

I opened the files behind the inventory's highest-risk entries and checked them. `metadata.py` is as described: the 29-column SELECT and row dict at 133-204, 450-entry chunks, and the threshold appended last. So is the handler and parser in `internal_client_reads.py`, including the `isinstance(body, dict)` guard. The two `fetch_metadata_by_ids` callers in `similarity_candidates.py:170,175` match, and so does the row-value `IN` precedent at `embeddings.py:228`. `idx_videos_uuid_instance` exists (`videos.py:21-22`) and is created at `server.py:337`. The Client side matches too: the resolve loop, `_handle_likes_import`, `_handle_user_profile_likes_from_client`, `_parse_client_likes`, the proxy trim at `server.py:493`, and `record_like`/`fetch_recent_likes`. `test_db.py:81` uses `sys.executable`. Outside `delete_me/`, the three `MAX_CLIENT_LIKES` readers and three `resolve_videos_by_uuid_host` sites are the only ones. Every entry I checked held up. I also checked `video_embeddings`: its key is `PRIMARY KEY (video_id, instance_domain)` (`build-video-embeddings.py:73`), so the inner join cannot fan out. That means each video is exactly one row, and the uuid path's "first row per key after ORDER BY video_id" really is "lowest `video_id`". I found one interaction the inventory does not carry: the Engine's per-request statement deadline, which now covers the whole batch.
<question id="1">
Yes. For id-only bodies, the refactored `fetch_metadata_by_ids` runs the same SQL with the same parameters in the same order. It is keyed on `like_key(row)`, whose format is the same as the handler's `_like_key`, so `_build_rows` and the id callers see identical dicts. For the likes page, the old flow was: dedup on `uuid::host`, then one exact `video_uuid = ? AND instance_domain = ?` resolve per pair (the Client always passed the host, `engine_api_client.py:152`), then metadata by id with the error filter. The new flow reaches the same rows in the same order. A `(video_id, instance_domain)` has exactly one `video_uuid`, so two distinct uuid pairs can never collapse onto one video. Duplicates only arise across forms, and the ordered walk keyed on the row's `like_key` removes them. On a correct build of the plan, the only differences are the ones the operator already accepted:
- the embedding-blob check is dropped;
- the error filter is applied before the lowest-`video_id` pick;
- import is error-filtered.
</question>
<question id="2">
- **Engine locking and lookups.** One likes-page or import request now costs one Engine round trip, one `db_lock` hold and one or two statements, instead of up to 51 round trips and holds. The uuid query is an index lookup, not a scan.
- **Statement deadline (new).** The Engine's statement deadline is now per batch, not per like. `SimilarHandler.do_POST` (`similar.py:355-363`) runs the whole metadata request, including the `db_lock` wait, under one `statement_deadline`. That is 5 s by default, fixed at request start. Before, each like's resolve had its own 5 s budget. A breach answers 503 `Query time limit exceeded`. `fetch_metadata_for_entries` turns that into `EngineApiError`, which the Client answers as 502. With ≤ 50 pairs on an index this is negligible. It is the same exposure the id path and block-add already have.
- **Rate limiting.** No per-IP Engine limiter applies: the `/internal/*` routes are not rate-limited.
- **Client latency.** The Client's `_post_json` 6 s timeout now bounds the whole likes page, rather than each of up to 200 sequential calls.
- **Similar and up-next.** These pages go through the refactored helper. A drift in the helper would alter them silently, which the inventory already flags.
</question>
<question id="3">
Nothing beyond the plan and the inventory is needed in code.
- **Helper contract.** The helper must take `conn` only, never the lock, because `db_lock` is non-reentrant. It must keep reading only `video_id`/`instance_domain` from entries. It must let the uuid caller add `ORDER BY v.video_id`, or sort in Python.
- **Import.** `_handle_likes_import` must keep calling `record_like` inside `with conn:`. `record_like` commits itself (`users_store.py:117`), which is unchanged behaviour.
- **Temp DB for tests.** The Engine unit tests' temp DB must create:
  - `video_embeddings` with its `(video_id, instance_domain)` primary key;
  - `videos` with every selected column plus `error_count`;
  - `channels`.
- **Test pattern.** The Engine test pattern is `test_similar.py`'s `ENGINE_PY` child, not `test_db.py`, as the inventory already corrects.
- **Plan wording.** The plan's "Missing index" risk is wrong and should be corrected, as the inventory already says.
</question>
<question id="4">
The id-keyed endpoint contract is unchanged: same rows, same order, same response shape. The one exception is an entry with an empty `video_id` plus a valid `video_uuid`, which now resolves instead of being skipped. No current writer produces one. The other changes:
- `/internal/videos/metadata` now also accepts `{video_uuid, instance_domain}` entries.
- `/internal/dislikes/centroids` is untouched.
- Import no longer records videos at or over the error threshold.
- Import and the likes page now include videos with an empty or mismatched embedding blob.
- On a shared uuid+host, both pick the lowest eligible `video_id` rather than an arbitrary row.
- Like entries past the 50th are dropped on the likes page, the import and the `/recommendations`/`/videos/similar` proxy (was 200).
- Browser-like dedup happens only on the Engine.
- `resolve_videos_by_uuid_host` no longer exists.
- An Engine statement timeout on a batch now fails the whole likes page or import with 502. Before, it failed only if some single resolve hit its own 5 s budget.
</question>

New impacts:
engine/server/api/handlers/similar.py SimilarHandler.do_POST (lines 355-363) and `_statement_deadline` (335-343): `/internal/videos/metadata` runs, lock wait included, under one per-request `statement_deadline` (DEFAULT_STATEMENT_TIMEOUT_SECONDS, from request start). Resolving a browser-like batch in one call replaces up to 50 separate 5 s budgets (one per resolve) with a single budget for both lookups. On a breach the Engine answers 503 `Query time limit exceeded`, which `fetch_metadata_for_entries` raises as `EngineApiError`, so the whole likes page answers 502 `Engine metadata failed` and the whole import answers 502 `Engine resolve failed` (nothing imported). No code change is needed: at ≤ 50 pairs the query is an index lookup (`idx_videos_uuid_instance`), and the id path already carries the same exposure. Tests on a temp DB will not show it. Regression risk: low.

Inventory entries that did not hold up:
none

Conflicts: none

Recommendations: 1. Accept the new statement-deadline impact as a recorded ramification, with no code change. Cost: one line in the plan's risks. The alternative is a Client test that has the stand-in Engine answer 503 and asserts the likes page and the import both answer 502 with nothing imported. It costs one more stand-in response mode and about 2 test cases, in a harness the plan already builds. I recommend the test only if the operator wants the 502 path of the two rewritten handlers covered before plan 15 rewrites their bodies. Otherwise skip it.
2. Replace the plan's "Missing index" risk with "`idx_videos_uuid_instance` (`engine/server/data/videos.py:21`) serves the uuid query". Also change the Engine-test pattern reference from `test_db.py` to `test_similar.py` `_LIKES_CHILD` under `conftest.ENGINE_PY`. Cost: plan text only, no behaviour change. Both corrections are already in the inventory, so this is a reminder that the plan text still carries them.
3. In the Engine unit tests' temp schema, give `video_embeddings` its real `PRIMARY KEY (video_id, instance_domain)`. The lowest-`video_id` test's premise, that one row per video comes back and the first after `ORDER BY v.video_id` wins, depends on that key, and a key-less fixture would let a join fan-out slip through unnoticed. Cost: one line of fixture DDL.

## 2026-09-27 - Step 3 - Identify every file, function and doc affected

Recorded ungated, at the operator direction.

### impacts


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


### docs_checklist

<doc path="client/README.md">
- **Line 15** (`POST /api/profile/likes/import`): add that at most 50 likes per body are read and the rest are dropped. A video the Engine does not know, or holds at or over its error threshold, is not imported (ADR-0003).
- **Line 22** (`POST /api/user-profile/likes`): add that it resolves up to 50 browser likes in one Engine metadata call, in submitted order, deduplicated, and that unknown videos are omitted.
- **Lines 30 and 37-39** stay accurate: `/internal/videos/resolve` is still used by user actions and block-add.
</doc><doc path="engine/server/README.md">
Line 11 (`/internal/videos/metadata`): entries may be `{video_id, instance_domain}` or `{video_uuid, instance_domain}`, mixed. An entry with both uses `video_id`. All entries are answered under one lock hold, one row per video, in first-matching-entry order. Where several videos share a uuid and host, the lowest `video_id` wins. Line 10 (resolve) is unchanged.
</doc><doc path="docs/project/adr/0003-metadata-endpoint-accepts-uuid-entries.md">
The decision is unchanged. Optionally add two consequences under Consequences: the lowest-`video_id` rule for a shared `(video_uuid, instance_domain)`, and that videos with an empty or mismatched embedding blob now appear on the likes page and are imported.
</doc><doc path="docs/project/issues/03-batch-like-resolution.md">
At harvest on main: set `Status: bug, complete`, add a delivery comment, and move the file to `docs/project/issues/archive/` (per `docs/project/triage-labels.md`).
</doc><doc path="docs/project/plans/14-batch-like-resolution.md">
At harvest on main, archive it together with `16-14-batch-like-resolution.md` and its record, in `docs/project/plans/archive/`. Correct the plan text in `16-14-batch-like-resolution.md` in two places:
- **Missing index:** `idx_videos_uuid_instance` exists (`engine/server/data/videos.py:21`).
- **Test pattern:** the handler tests follow `test_internal_events.py`/`test_similar.py` (`ENGINE_PY` child), not `test_db.py`, and the data-layer tests can run in-process.
</doc>

### highest_risk

engine/server/data/metadata.py fetch_metadata_by_ids refactor into the shared helper: every existing consumer goes through it, including similarity_candidates._build_rows (similar and up-next pages), which the plan's caller list omits. A drift in per-chunk parameters, threshold placement, row-dict keys or like_key keying silently empties or alters rows, and no in-process test covers this function today.
engine/server/api/handlers/internal_client_reads.py handle_internal_videos_metadata plus the new parser: id-only bodies must give identical rows and order; cross-form dedup must key on the returned row's video_id::instance_domain with the id and uuid dicts kept separate; db_lock must be taken exactly once; and a bad import on line 9 stops the whole Engine at startup (loaded by handlers/similar.py).
client/backend/server.py _handle_likes_import: it now relies on Engine metadata rows for record_like and is_disliked and inherits the error-threshold filter, while importLocalLikes clears every local like on any 2xx (client/frontend/src/data/reactions.ts:81). So a like the server drops (past the 50th, unknown or errored) is lost for good with no retry.

## 2026-09-27 - Step 4 - Reassess the implementation plan (pass 2)

Pass 2. New impacts: none.

I checked the inventory against the files it names, and every entry I opened held up. The plan still works. The main points:
- **Engine data layer.** `metadata.py:110-205` is as described: `if not entries: return {}`, 450-entry `_chunk` batches, the `OR` fragment, and the threshold clause added only when `error_threshold > 0`. That clause is appended once per chunk, after the pair parameters. The 29-column SELECT and row dict are keyed on `like_key(row)`.
- **The two callers.** `similarity_candidates.py:170,175` call `fetch_metadata_by_ids` with and without the lock, and look rows up with `like_key(entry)` at 195 and 198.
- **Handler.** `internal_client_reads.py` has `_parse_entries` at 20-48 and the metadata handler at 95-126, where one lock hold is followed by an entry-order walk on `_like_key`. Centroids uses `_parse_entries` at 137.
- **Schema.** `video_embeddings` has `PRIMARY KEY (video_id, instance_domain)` (`build-video-embeddings.py:73`), so the inner join cannot fan out. `idx_videos_uuid_instance` exists (`videos.py:21-22`) and is created at `server.py:337`.
- **Row-value precedent.** It is at `embeddings.py:228`, unchunked. Resolve's `LIMIT 1` is at 140 and the blob check at 178.
- **Statement deadline.** `similar.py:355-363` wraps `_dispatch_post` in one `_statement_deadline`. The route is at 402-404, behind `_bridge_authorized` at 394.
- **Client side.** The resolve loop is at `engine_api_client.py:136-166`. `fetch_metadata_for_entries` returns `[]` for an empty list (97), and `_post_json` has a 6 s timeout. In `server.py`:
  - the import is at 30-32 and `MAX_CLIENT_LIKES = 200` at 52;
  - the proxy trim at 493 cuts before it validates;
  - `_handle_likes_import` is at 872-900, block-add at 927-963, the likes GET at 995-1010 and the likes POST at 1012-1029;
  - `_parse_client_likes` is at 1105-1121: it cuts, then validates, and does not deduplicate.
- **Other call sites.** `record_like` and `fetch_recent_likes` match. Outside `delete_me/` and `docs/`, the three `MAX_CLIENT_LIKES` readers and the three `resolve_videos_by_uuid_host` sites are the only ones.
- **Tests.** The citations match: `test_db.py:81` (uses `sys.executable`), `test_internal_events.py:173` and `test_similar.py:289` (`ENGINE_PY` children), the `ClientBackend(base, db_path)` fixture at `conftest.py:46-89`, and `test_profiles.py:223-253`.

The last step-4 pass added the per-request statement deadline as a new impact. The inventory now carries it in the handler and `similar.py` entries. I found nothing else missing.
<question id="1">
Yes.
- **Id-only bodies.** They run the same SQL with the same parameters in the same order and emit rows in entry order. `_build_rows`, the likes GET and block-add therefore see identical results.
- **Uuid entries.** They go through an exact match on both columns. The pick is deterministic, and `video_embeddings` has one row per video, so no join fans out. Two distinct uuid pairs cannot land on the same video, because a video has exactly one `video_uuid`. Duplicates can only come from the same video reached by both forms, and the post-lock walk keyed on the row's `video_id::instance_domain` removes those.
- **Likes page.** The old flow deduplicated on `uuid::host` in submitted order, resolved each pair, then ran metadata by id in that order. The new flow gives the same rows in the same order. The only differences are the ones the operator already accepted: no embedding-blob check, the error filter applied before the lowest-`video_id` pick, and import filtered by error count.
- **Test harness.** `_proxy_engine_request` (server.py:565), the metadata calls and resolve all use the single `engine_ingest_base`. So one capturing stand-in Engine sees both the proxy request and the metadata call, and the planned Client tests are feasible as designed.
</question>
<question id="2">
All of these are already in the inventory:
- **Load.** A likes-page or import request makes one Engine round trip and takes `db_lock` once, running one or two indexed statements. Before, it made up to 51 round trips, or 201 at the old cap.
- **Timeouts.** One statement deadline and one 6 s Client timeout now cover the whole batch, where before each resolve had its own.
- **Similar and up-next.** These pages now run through the refactored helper, so a drift in parameters or row keys would change them silently.
- **Browser storage.** `importLocalLikes` clears browser storage after any 2xx (`reactions.ts:81`). Likes that are dropped, unknown or errored are therefore lost for good.
- **Proxy.** Keyless bodies of 6-50 likes still get the Engine's 400 forwarded.
</question>
<question id="3">
No code beyond the plan is needed. The conditions in the inventory are what keep things working:
- **Helper.** It takes the connection only, never the lock, because `db_lock` is non-reentrant. It reads only `entry.get("video_id")` and `entry.get("instance_domain") or ""`. It appends the threshold once per chunk, as the last parameter. It lets the uuid caller order by `v.video_id`.
- **Handler.** It keeps the id dict and the uuid dict separate, and deduplicates on the returned row's key.
- **Import.** `_handle_likes_import` keeps `is_disliked` and `record_like` inside `with conn:`.
- **Imports.** Line 9 of `internal_client_reads.py` must import the new name correctly, or the Engine fails at startup.
- **Test fixtures.** The temp schema carries the real `video_embeddings` primary key. Client tests build their own `ClientBackendServer` pointed at the stand-in, as `conftest.py:161-168` does. The import test must first mint a profile, which needs no Engine call.
</question>
<question id="4">
**Unchanged:** the id-keyed contract (same rows, order and response shape), `/internal/dislikes/centroids`, `/internal/videos/resolve`, and user actions and block-add.

**Exception:** an entry with an empty `video_id` but a valid `video_uuid` used to be skipped and now resolves through the uuid form. No current writer produces such an entry.

**Changed:**
- `/internal/videos/metadata` also accepts `{video_uuid, instance_domain}` entries.
- Import skips videos at or over the error threshold.
- The likes page and import both include videos with a bad embedding blob.
- On a shared uuid and host, the lowest eligible `video_id` wins.
- Each request body is cut at 50 likes instead of 200, on the likes page, the import and the proxy.
- Browser likes are deduplicated only on the Engine.
- `resolve_videos_by_uuid_host` is gone.
- An Engine timeout now fails the whole likes page or import with a 502.
</question>

New impacts:
none

Inventory entries that did not hold up:
none

Conflicts: none

Recommendations: 1. Proceed with the plan as it stands. The inventory has converged: no new impacts, and no conflicts with the requirements or the plan. Cost: none.
2. Record two corrections in the plan's risks. First, the "Missing index" risk is wrong: `idx_videos_uuid_instance` (`engine/server/data/videos.py:21-22`) serves the uuid query and is created at every Engine start. Second, the Engine handler tests should follow the `ENGINE_PY` child pattern in `test_internal_events.py:173` and `test_similar.py:289`, not `test_db.py`, and the `data.metadata` tests can run in-process. Cost: plan wording only, with no change to behaviour or scope. Both corrections are already in the inventory and the docs checklist; this is a reminder that the plan text still carries the old wording.
3. Optional: when the stand-in Engine is built, give it a mode that answers 503, and add two cases showing the likes page and the import each answer 502 with nothing imported. This covers the single-deadline ramification before plan 15 rewrites those 502 bodies. Cost: one extra response mode and about two test cases in a harness the plan already builds. Skip it if plan 15 will add its own 502 tests.

## 2026-09-27 - Step 5 - Draft the initial implementation

Recorded ungated, at the operator direction.

### draft

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

## 2026-09-27 - Step 6 - Design the phase breakdown

Approved by the operator.

#### Phase 1 - Engine uuid-keyed metadata lookup [code]

**Files touched.** engine/server/data/metadata.py (EDITED), tests/tmp/test_metadata_uuid_entries.py (NEW)

**Checkpoint.** Seam: the data-layer functions `fetch_metadata_by_ids` and `fetch_metadata_by_uuids` in `engine/server/data/metadata.py`, called in-process against a temp SQLite DB (`row_factory = sqlite3.Row`). The DB has `videos` (26 selected columns plus `error_count`, PK `(video_id, instance_domain)`), `video_embeddings` (PK `(video_id, instance_domain)`) and `channels`. Harness: the `sys.path` insertion of `engine/server` and `engine/server/api` from `tests/active/test_internal_events.py:25-30`. `data.metadata` imports no numpy, so no child process is needed. The file lives in `tests/tmp` and needs `tests/active` on `sys.path` before any `from conftest import ...`. Fixtures come from the draft's table: a1, b1, s2 inserted before s1, e1, n1 with no embedding, and a1 on other.example. Asserts, clause 1: `fetch_metadata_by_uuids(conn, [{video_uuid: "u-b", instance_domain: "h.example"}])["u-b::h.example"] == fetch_metadata_by_ids(conn, [{video_id: "b1", instance_domain: "h.example"}])["b1::h.example"]`, and the dict holds exactly the 29 keys. `u-a@h.example` gives the h.example a1, not the other.example one. `U-A` and `u-a@H.EXAMPLE` give nothing. `u-n` gives nothing. An empty list gives `{}` with zero `execute` calls, counted through a wrapped conn. Asserts, clause 2: `u-s` gives `s1`. After `s1.error_count = 5` with threshold 3 it gives `s2`. `u-e` is absent at threshold 3 and present at threshold None. Regression pins with no clause of their own: `fetch_metadata_by_ids` output for a1, n1 skipped, and a 460-video set crossing the 450 chunk boundary on both functions with threshold 3. Every non-errored video comes back. On the uuid path, an errored video in chunk 2 is absent. On the id path there is no assertion on that errored video, because Open item A option 1 keeps today's AND/OR precedence.

**Intent.** `engine/server/data/metadata.py` fetches metadata rows by exact `(video_uuid, instance_domain)` pair through `fetch_metadata_by_uuids`. It uses the same SELECT and row builder (`_select_metadata`) as `fetch_metadata_by_ids` and yields one row per pair: the lowest eligible `video_id`.

- C1 - `fetch_metadata_by_uuids` returns, for an exact `(video_uuid, instance_domain)` match, the same row dict that `fetch_metadata_by_ids` returns for that video.
- C2 - Where several videos share one `(video_uuid, instance_domain)`, the row kept is the one with the lowest `video_id` among those under the error threshold.

**Outcome.** _pending_

#### Phase 2 - Engine metadata endpoint accepts both entry forms [code]

**Files touched.** engine/server/api/handlers/internal_client_reads.py (EDITED), tests/tmp/test_metadata_uuid_entries.py (EDITED)

**Checkpoint.** Seam: `handlers.internal_client_reads.handle_internal_videos_metadata(handler, server)`, entered in an `ENGINE_PY -c` child with `cwd=API_DIR`. The module imports numpy, so it cannot run in the pytest interpreter. Harness: the child pattern of `tests/active/test_internal_events.py:173` and `tests/active/test_similar.py:288-289`. The child patches `read_json_body` and `respond_json` on the handler module. It passes `SimpleNamespace(db=conn, db_lock=CountingLock(), video_error_threshold=3)`, where `CountingLock` wraps `threading.Lock` and counts `__enter__`, and prints `[{status, payload, enters}]` per body. It uses the same temp DB as phase 1. Asserts, clause 1: the mixed body `[uuid u-b, id a1, id b1, uuid u-a, uuid u-x]` gives `enters == 1`. Id-only `[a1, b1, a1]` gives `enters == 1`. Asserts, clause 2: the mixed body gives rows `[b1, a1]` with `count == 2`, each video once in first-match order and the unknown omitted. Id-only `[a1, b1, a1]` gives `[a1, b1]`. An item carrying both a valid `video_id` and a `video_uuid` of a different video resolves to the id's video. Per-form duplicates collapse. Uuid `u-e` is absent at threshold 3. Guards: `{"entries": "x"}` and `{}` give 400 `Missing entries` with `enters == 0`. An all-malformed body (non-dict, blank `instance_domain`, neither key) gives 200 `{"ok": True, "count": 0, "rows": []}` with `enters == 0`. On `/internal/dislikes/centroids`, with `fetch_embeddings_by_ids` spied: a uuid-only body passes `[]` and returns `centroids == []`, and a mixed body passes only the id entries.

**Intent.** `handle_internal_videos_metadata` in `engine/server/api/handlers/internal_client_reads.py` parses id-form and uuid-form entries with its own parser. It answers all of them in a single `db_lock` hold and emits each matched video once, at its first matching entry.

- C1 - A request body mixing id-form and uuid-form entries acquires `db_lock` exactly once.
- C2 - Each matched video appears once in `rows`, in the order of its first matching entry.

**Outcome.** _pending_

#### Phase 3 - Client resolves likes in one Engine call [code]

**Files touched.** client/backend/server.py (EDITED), client/backend/lib/engine_api_client.py (EDITED), tests/tmp/test_client_like_batching.py (NEW)

**Checkpoint.** Seam: the Client HTTP boundary. Requests go to `POST /api/user-profile/likes` and `POST /api/profile/likes/import` on a locally built `ClientBackendServer`, whose `engine_ingest_base` points at a capturing stand-in Engine. The stand-in is a stdlib `ThreadingHTTPServer` written like `EngineStub` at `tests/active/test_server.py:307`. It records `(path, json body)` for every POST. On `/internal/videos/metadata` it answers from a canned `{uuid::host: row}` table in entry order, omitting unknown entries and duplicates. Local `_serving` and `_client_backend` copies of `test_server.py:251-271` build the Client, with `RateLimiter(1000, 60)`. The file needs `tests/active` on `sys.path` before `from conftest import ...`. Asserts, clause 1: a likes-page body of 3 likes plus a duplicate plus an unknown records exactly one Engine request, to `/internal/videos/metadata`, with `entries` equal to the submitted `{video_uuid, instance_domain}` list. The response `likes` holds the known rows in submitted order. An import of 3 likes records exactly one Engine request, to the same path. An empty or all-malformed likes-page body gives 200 `likes == []` with zero Engine requests. Asserts, clause 2: mint via `POST /api/profile` and resolve `profile_id` with `resolve_profile` on a second connection. Write one dislike with `write_dislike` and commit. Import the disliked video, a clean one and an unknown one. The result is `{"imported": 1}` and `load_liked_keys(conn, profile_id) == {(clean_id, host)}`. The existing `tests/active/test_profiles.py` import test also has to pass against the live Engine, in its own `validate_tests.py` invocation. That shows phases 1-2 and 3 work together.

**Intent.** `_handle_user_profile_likes_from_client` and `_handle_likes_import` in `client/backend/server.py` each resolve a request's browser likes with a single `fetch_metadata_for_entries` call, and import records a like from each returned row. `resolve_videos_by_uuid_host` no longer exists.

- C1 - A likes-page or likes-import request causes exactly one Engine HTTP call, to `/internal/videos/metadata`.
- C2 - Likes import records a like for each returned row whose video the profile has not disliked.

**Outcome.** _pending_

#### Phase 4 - Cap like entries at 50 [code]

**Files touched.** client/backend/server.py (EDITED), tests/tmp/test_client_like_batching.py (EDITED)

**Checkpoint.** Seam: the same Client HTTP boundary and capturing stand-in Engine as phase 3, in the same test file. Asserts, clause 1, on three request paths: a 60-entry likes-page body gives 200, and the single recorded `/internal/videos/metadata` request carries exactly the first 50 entries. A 60-entry import body gives 200, and its single request carries exactly the first 50. A keyless `POST /recommendations` with 60 `{uuid, host}` likes records a forwarded body whose `likes` is the first 50 sanitised entries. The three paths are listed by hand, not derived. They are the three `MAX_CLIENT_LIKES` readers that the grep in the plan found.

**Intent.** `MAX_CLIENT_LIKES` in `client/backend/server.py` is 50, so at most the first 50 like entries of one request body reach the Engine.

- C1 - A body carrying 60 like entries reaches the Engine as its first 50 entries.

**Outcome.** _pending_


Needs coordination: none

Rationale: The build falls into four phases. Each has its own test boundary and depends only on the phases before it. The operator approved the breakdown as presented.

Phase 1 is the data layer. `fetch_metadata_by_uuids` over the shared `_select_metadata` can be tested in-process with no Engine interpreter, because `data.metadata` imports no numpy. That makes it the cheapest place to prove the two hardest guarantees: the same row dict whichever form is used, and the lowest eligible `video_id`. It also pins the refactored id path that `similarity_candidates._build_rows` depends on.

Phase 2 is the handler. It needs the `ENGINE_PY` child and the counting-lock stand-in server, and it builds on phase 1's functions. Parser rules (id wins, per-form dedup, 400 and empty-200 paths) and the centroids-unchanged guard are cases inside clause 2's test or guards on the checkpoint, not extra clauses. That keeps the phase at two clauses.

Phases 3 and 4 are on the Client side. Both run against a capturing stand-in Engine, because a live Engine cannot count HTTP calls and answers 400 above 5 likes on the proxy. The cap is split out from the one-call rewrite. The rewrite already carries two facts: the single call, and import recording non-disliked rows. The cap is a separate observable across three readers, so folding it in would have needed a third clause.

The R6 deletion of `resolve_videos_by_uuid_host` sits in phase 3's files. Its proof is that the module still imports, and the single-call assertion shows no resolve call remains.

Open item A (AND/OR precedence in the id-path threshold) goes with option 1, as the draft proposed and the operator accepted. Id-caller semantics stay unchanged, and the phase 1 checkpoint makes no assertion on errored id rows. The precedence bug goes to the roadmap for Step 9.

Both new test files live in `tests/tmp`, where pytest does not put `tests/active` on the path. They must insert `tests/active` on `sys.path` before `from conftest import ...`. They build their own servers, so they need no conftest fixtures.

The build closes when all five clauses pass and the full suite is green. Engine-backed files (`test_profiles.py`, `test_server.py`, `test_similar.py`, `test_blocks.py`) each run in their own `validate_tests.py` invocation because of the Engine's shared rate limit.

The step template's `{principles}`, `{shape_ladder-ladder}` and `{tdd_seams}` placeholders arrived unfilled. Each seam above was therefore anchored to an existing harness in the tree: `test_internal_events.py`, `test_similar.py`, and `test_server.py`'s EngineStub.

## 2026-09-27 - Step 7 - Phase 1 (Engine uuid-keyed metadata lookup) - must_prove

Quoted from the phase Intent, written at Step 6 before the checkpoint was drafted.

Intent:
`engine/server/data/metadata.py` fetches metadata rows by exact `(video_uuid, instance_domain)` pair through `fetch_metadata_by_uuids`. It uses the same SELECT and row builder (`_select_metadata`) as `fetch_metadata_by_ids` and yields one row per pair: the lowest eligible `video_id`.

- C1 - `fetch_metadata_by_uuids` returns, for an exact `(video_uuid, instance_domain)` match, the same row dict that `fetch_metadata_by_ids` returns for that video.
- C2 - Where several videos share one `(video_uuid, instance_domain)`, the row kept is the one with the lowest `video_id` among those under the error threshold.

must_prove:
- C1 - `fetch_metadata_by_uuids` returns, for an exact `(video_uuid, instance_domain)` match, the same row dict that `fetch_metadata_by_ids` returns for that video.
- C2 - Where several videos share one `(video_uuid, instance_domain)`, the row kept is the one with the lowest `video_id` among those under the error threshold.

## 2026-09-27 - Step 7 - Phase 1 (Engine uuid-keyed metadata lookup) - self-check (audit round 1, send-back 0)

`tests/tmp/test_14_batch_like_resolution_phase1.py`, surface `checkpoint`. Collection exit 0.

- C1 - tests/tmp/test_14_batch_like_resolution_phase1.py:105-108 — `fetch_metadata_by_uuids` for `u-b@h.example` at threshold 3 has exactly the key `u-b::h.example`. Its row has exactly the 29 `ROW_KEYS`, equals `fetch_metadata_by_ids(...)["b1::h.example"]`, and equals `_row(*B1)`: the stored values plus `channel_display_name` "Chan B", `channel_avatar_url` "ava-b", `embedding_dim` 3 and `model_name` "m". - expected: `{"u-b::h.example": _row(*B1)}`. The probe showed `fetch_metadata_by_ids` returns exactly `_row(*B1)` for b1 at threshold 3 even though b1's `error_count` is NULL, so the id side of line 107 is observed. - excludes: A uuid query that leaves out the `channels` LEFT JOIN or builds a trimmed row gives a different key set or `channel_display_name` None (red at 106/108). One that keys the row by `like_key` gives `b1::h.example` (red at 105). One that drops a NULL `error_count` under a threshold (`error_count < ?` without `IS NULL`) gives `{}`.
- C1 - tests/tmp/test_14_batch_like_resolution_phase1.py:112-116 — `u-a@h.example` gives only the h.example a1 row. Asking for both hosts gives both a1 rows under their own keys. `U-A@h.example`, `u-a@H.EXAMPLE` and the unembedded `u-n@h.example` each give `{}`. - expected: 112: `{"u-a::h.example": _row(*A1)}`. 113: that plus `"u-a::other.example": _row(*A1_OTHER)` (the probe observed the id lookup returning exactly `_row(*A1_OTHER)` for the other.example a1). 114, 115, 116: `{}`. - excludes: Matching on uuid alone returns or overwrites with the other.example a1 (red at 112/113). `COLLATE NOCASE` or `lower()` matching returns a1 for `U-A` or `H.EXAMPLE` (red at 114/115). A LEFT JOIN on `video_embeddings` returns n1 with `embedding_dim` None (red at 116). Line 112 is the positive control: a function that always returns `{}` is red there before it reaches the absences.
- C1 - tests/tmp/test_14_batch_like_resolution_phase1.py:125-126 — an empty entry list returns `{}`, and the connection's trace callback records no statement. Lines 122-123 are the control: the same trace records at least one statement for a lookup that finds a row. - expected: `{}`, and `statements == []`. The probe observed the trace recording 1 statement for an id lookup and 0 for an empty one. - excludes: A version with no `if not entries: return {}` guard that still runs a query (for example a WHERE with an empty IN, or a setup statement before the loop) records a statement, so it goes red at 126.
- C2 - tests/tmp/test_14_batch_like_resolution_phase1.py:130-137 — for the shared pair `u-s@h.example` (the probe showed the SELECT yields s2, s1, s3), the result as s1's `error_count` changes at threshold 3: 0 gives s1, 3 gives s2, 2 gives s1, 5 gives s2, and 5 with threshold None gives s1. - expected: 130 `_row(*S1)`, 132 `_row(*S2)`, 134 `_row(*S1)`, 136 `_row(*S2)`, 137 `_row(*S1)`, each under `u-s::h.example`. The probe showed that with s1 at 3 the eligible rows are s2 and s3, and that the id lookup returns exactly `_row(*S1/S2/S3)` for each sibling. - excludes: Keeping the first row in SELECT order gives s2 at 130. Keeping the last row (plain dict overwrite) gives s3. Choosing the lowest id before filtering on errors gives `{}` at 132/136. Using `<=` for the threshold keeps s1 at 132. Applying the threshold even when it is None gives s2 at 137.
- C2 - tests/tmp/test_14_batch_like_resolution_phase1.py:141-142 — `u-e` (error_count 5) gives `{}` at threshold 3 and `{"u-e::h.example": _row(*E1)}` with threshold None. - expected: 141 `{}`. 142 `{"u-e::h.example": _row(*E1)}`. The probe observed the id lookup giving `{}` for e1 at threshold 3 and exactly `_row(*E1)` with None. - excludes: A uuid query without the error clause returns e1 at 141. One that always applies the clause gives `{}` at 142. Line 142 is also the positive control for the absence at 141.
- C2 - tests/tmp/test_14_batch_like_resolution_phase1.py:160-161 — across 460 bulk videos at threshold 3, which cross the 450-pair chunk boundary, the uuid lookup maps every healthy `uc###::bulk.example` to its `c###`, leaves out `uc455` (error_count 5, in chunk 2 and not its last pair), and returns uc452's full row. - expected: A dict with exactly the 459 healthy keys, each mapped to its own `c###`, plus `_row(*_bulk(452))` for `uc452`. The id path returned exactly `_row(*_bulk(452))` for c452 in this run: line 158 passed before 159 raised. - excludes: Copying the id path's `OR` chain for uuids binds the threshold only to each chunk's last pair, so `uc455` comes back (red at 160). Querying only the first chunk loses uc450–uc459. Deduplicating in a way that lets a pair span two chunks produces mismatched rows.

<assertions>
tests/tmp/test_14_batch_like_resolution_phase1.py:105 - `fetch_metadata_by_uuids([u-b@h.example], threshold 3)` returns exactly one key, `u-b::h.example` - C1
tests/tmp/test_14_batch_like_resolution_phase1.py:106 - that row holds exactly the 29 literal `ROW_KEYS` - C1
tests/tmp/test_14_batch_like_resolution_phase1.py:107 - the uuid row equals `fetch_metadata_by_ids([b1@h.example], threshold 3)["b1::h.example"]`; b1's NULL `error_count` must not exclude it - C1
tests/tmp/test_14_batch_like_resolution_phase1.py:108 - the uuid row equals the values the fixture stored for b1, with the channels join (`Chan B`/`ava-b`) and embeddings join (3, `m`), so both paths being wrong the same way still fails - C1
tests/tmp/test_14_batch_like_resolution_phase1.py:112 - `u-a@h.example` gives only `{"u-a::h.example": <h.example a1 row>}`, not the other.example a1 - C1
tests/tmp/test_14_batch_like_resolution_phase1.py:113 - asking for `u-a@h.example` and `u-a@other.example` together gives each host's own a1 row under its own key - C1
tests/tmp/test_14_batch_like_resolution_phase1.py:114 - `U-A@h.example` gives `{}` (uuid match is case-sensitive) - C1
tests/tmp/test_14_batch_like_resolution_phase1.py:115 - `u-a@H.EXAMPLE` gives `{}` (host match is case-sensitive) - C1
tests/tmp/test_14_batch_like_resolution_phase1.py:116 - `u-n@h.example` (video with no embedding) gives `{}` - C1
tests/tmp/test_14_batch_like_resolution_phase1.py:122 - control: a lookup that finds a row returns something, so the trace below is watching a real lookup - control, no clause
tests/tmp/test_14_batch_like_resolution_phase1.py:123 - control: the connection's `set_trace_callback` recorded at least one statement for that lookup - control, no clause
tests/tmp/test_14_batch_like_resolution_phase1.py:125 - an empty entry list gives `{}` - C1
tests/tmp/test_14_batch_like_resolution_phase1.py:126 - the empty list ran zero SQL statements on the connection - C1
tests/tmp/test_14_batch_like_resolution_phase1.py:130 - u-s siblings come out of the SELECT as s2, s1, s3 (observed); the lookup keeps s1's full row, which neither first-row-wins nor last-row-wins gives - C2
tests/tmp/test_14_batch_like_resolution_phase1.py:132 - with s1.error_count = 3 (equal to threshold 3) it keeps s2 - C2
tests/tmp/test_14_batch_like_resolution_phase1.py:134 - with s1.error_count = 2 (just under threshold 3) it keeps s1 - C2
tests/tmp/test_14_batch_like_resolution_phase1.py:136 - with s1.error_count = 5 and threshold 3 it keeps s2 (lowest among eligible rows, not pick-then-filter, which gives `{}`) - C2
tests/tmp/test_14_batch_like_resolution_phase1.py:137 - with s1.error_count = 5 and threshold None it keeps s1 - C2
tests/tmp/test_14_batch_like_resolution_phase1.py:141 - `u-e` (error_count 5) is absent at threshold 3 - C2
tests/tmp/test_14_batch_like_resolution_phase1.py:142 - `u-e` gives e1's full row at threshold None - C2
tests/tmp/test_14_batch_like_resolution_phase1.py:147 - regression pin: `fetch_metadata_by_ids([a1@h, n1@h])` equals `{"a1::h.example": <a1 full joined row>}`, with unembedded n1 skipped - regression pin, no clause
tests/tmp/test_14_batch_like_resolution_phase1.py:157 - regression pin: across 460 bulk videos at threshold 3, the id lookup returns every one of the 459 healthy videos. The errored c455 (chunk 2, not its last pair) is deliberately not asserted, per Open item A option 1 - regression pin, no clause
tests/tmp/test_14_batch_like_resolution_phase1.py:158 - regression pin: the id lookup's chunk-2 row c452 equals its full fixture row - regression pin, no clause
tests/tmp/test_14_batch_like_resolution_phase1.py:160 - regression pin: the uuid lookup over the same 460 pairs maps exactly the 459 healthy `uc###::bulk.example` keys to their video_ids, so errored c455 in chunk 2 is absent - regression pin, no clause
tests/tmp/test_14_batch_like_resolution_phase1.py:161 - regression pin: the uuid lookup's chunk-2 row for uc452 equals its full fixture row - regression pin, no clause
</assertions>

<probes>
1. `tests/tmp/probe_phase1_metadata.py`, run with ValidateTests `["tests/tmp/probe_phase1_metadata.py", "-s"]` and read from `tests/last_test_output.txt`:
- The interpreter is `.pixi/envs/default/bin/python3` (Python 3.14.7) with SQLite 3.53.4. `data.metadata` imports in-process from tests/tmp, and today it has no `fetch_metadata_by_uuids` (False).
- The draft SELECT with `(v.video_uuid, v.instance_domain) IN ((?, ?))` on videos stored s2, s1, s3 returned the rows in order `['s2', 's1', 's3']`, both with and without the error clause. The query plan scans `v` first (`SCAN v`), then searches `e` through its autoindex.
- Row-value IN with `('U-A', 'h.example')` gave `[]`, and with `('u-a', 'H.EXAMPLE')` gave `[]`.
- `set_trace_callback` recorded 1 statement for one `fetch_metadata_by_ids` call, and `fetch_metadata_by_ids(conn, [])` gave `{}` with 0 statements.
- `fetch_metadata_by_ids([a1@h, n1@h])` gave only `a1::h.example`, as a 29-key dict holding exactly the fixture's values: channel `Chan A`/`ava`, `embedding_dim` 3, `model_name` `m`.
- With 460 bulk videos, c455 errored, threshold 3, the id lookup returned 460 rows and included c455. That confirms Open item A: the threshold binds only to the last pair of each chunk. A 450-pair row-value IN with the threshold parameter ran and returned 450 rows.

2. `tests/tmp/probe_phase1_against_impls.py`, run with ValidateTests `["tests/tmp/probe_phase1_against_impls.py", "-s"]`. It imports this test file's functions and monkeypatches `metadata.fetch_metadata_by_uuids`:
- A draft-shaped implementation (row-value IN, 450 chunks, lowest video_id picked in Python, keys `uuid::host`) passed all 7 tests.
- Wrong variants each failed the intended test: first-row-wins and last-row-wins failed `test_a_shared_uuid_pair_keeps_the_lowest_video_id_under_the_threshold`, and so did pick-then-filter. COLLATE NOCASE failed `test_a_uuid_pair_matches_only_its_exact_uuid_and_host`.

3. The real file, run with ValidateTests `["tests/tmp/test_14_batch_like_resolution_phase1.py"]`: 6 failed, 1 passed. Every failure is `AttributeError: module 'data.metadata' has no attribute 'fetch_metadata_by_uuids'`. The chunk test fails at line 138, after its id-path assertions at 157-158 have run and passed. The id pin at 147 passes.

Both probe files are still on disk because I have no delete tool: `tests/tmp/probe_phase1_metadata.py` and `tests/tmp/probe_phase1_against_impls.py`. Their names do not match pytest's default `test_*.py` pattern, so a suite run does not collect them, but they should be deleted.
</probes>

<unassertable>
none. Every clause is carried. Four places where the test differs from the Step 6 checkpoint wording, for the auditor:
(1) The empty-list "zero `execute` calls" is counted with the connection's `sqlite3` `set_trace_callback`, not a proxy wrapping `conn.execute`. A `sqlite3.Connection`'s `execute` cannot be patched on the instance. A trace sees every statement whatever API the code uses. It is paired with a control showing that the trace sees a real lookup.
(2) A third u-s sibling, s3, is stored after s1. With s2 alone, a last-row-wins pick would pass, because the observed row order is s2, s1, s3.
(3) The checkpoint says `videos` has 26 selected columns. The SELECT at metadata.py:133-162 reads 25 `v.*` columns (plus 2 from channels and 2 from embeddings, which makes the 29 keys), so the temp schema has those 25 plus `error_count`.
(4) The file computes ROOT from `Path(__file__).parents[2]` and does not import `conftest`, so it needs no `tests/active` on `sys.path`.
One expectation is still a prediction: that `fetch_metadata_by_uuids(conn, entries, error_threshold=...)` returns a dict keyed `video_uuid::instance_domain`. It comes from the Step 6 checkpoint's own expression and the draft; the function does not exist yet, so I could not observe it. The draft-shaped reference in probe 2 confirms only that the test is consistent with that contract.
</unassertable>

### `tests/tmp/test_14_batch_like_resolution_phase1.py` - 9817 characters, inlined in full

```
"""`fetch_metadata_by_uuids` answers an exact `(video_uuid, instance_domain)` pair with the row `fetch_metadata_by_ids` gives that video, and a pair shared by several videos with the lowest `video_id` under the error threshold.

- `u-b@h.example` at threshold 3 gives, keyed `u-b::h.example`, the 29-key row `fetch_metadata_by_ids` gives for `b1@h.example`, with its `channels` and `video_embeddings` columns joined in. That row is the same one the fixture stored, and `b1`'s NULL `error_count` does not exclude it.
- `u-a@h.example` gives the `h.example` a1 and not the `other.example` a1. Asking for both gives each under its own key. `U-A@h.example`, `u-a@H.EXAMPLE`, and `u-n@h.example` (no embedding) give `{}`. An empty list gives `{}` and runs no SQL statement on the connection.
- The three `u-s` siblings come out of the SELECT as s2, s1, s3 (observed), and the lookup keeps s1. With s1's `error_count` at 3 or 5 under threshold 3 it keeps s2, at 2 it keeps s1, and with no threshold it keeps s1 at 5. `u-e` (error_count 5) is dropped at threshold 3 and returned with no threshold.
- Pins on the id path this phase refactors: a1's full row with the unembedded n1 skipped. Across 460 videos, which cross the 450-entry chunk boundary at threshold 3, both lookups return every healthy video. The uuid lookup also drops the errored video in chunk 2. The id lookup is not asserted on that video, because its threshold binds only to the last pair of each chunk (Open item A, option 1).

Everything runs in-process against a temporary SQLite database with the Engine's three joined tables. Nothing is stubbed.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SERVER_DIR = ROOT / "engine" / "server"
API_DIR = SERVER_DIR / "api"
# `data.metadata` imports `recommendations.keys`, which lives under `api`, as the Engine's server.py runs it.
for path in (SERVER_DIR, API_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from data import metadata  # noqa: E402

HOST = "h.example"
OTHER = "other.example"
BULK = "bulk.example"
THRESHOLD = 3
VIDEO_TEXT = ("video_id", "video_uuid", "instance_domain", "channel_id", "channel_name", "channel_url", "account_name", "account_url", "title", "description", "tags_json", "category", "published_at", "video_url", "thumbnail_url", "embed_path", "preview_path", "last_checked_at")
VIDEO_INT = ("video_numeric_id", "duration", "views", "likes", "dislikes", "comments_count", "nsfw")
ROW_KEYS = ("video_id", "video_uuid", "video_numeric_id", "instance_domain", "channel_id", "channel_name", "channel_url", "channel_display_name", "channel_avatar_url", "account_name", "account_url", "title", "description", "tags_json", "category", "published_at", "video_url", "duration", "thumbnail_url", "embed_path", "views", "likes", "dislikes", "comments_count", "nsfw", "preview_path", "last_checked_at", "embedding_dim", "model_name")
# (video_id, video_uuid, instance_domain, n, channel display_name/avatar_url); n makes every integer column distinct per video.
A1 = ("a1", "u-a", HOST, 1, ("Chan A", "ava-a"))
B1 = ("b1", "u-b", HOST, 2, ("Chan B", "ava-b"))
S2 = ("s2", "u-s", HOST, 3, (None, None))
S1 = ("s1", "u-s", HOST, 4, (None, None))
S3 = ("s3", "u-s", HOST, 5, (None, None))
E1 = ("e1", "u-e", HOST, 6, (None, None))
N1 = ("n1", "u-n", HOST, 7, (None, None))
A1_OTHER = ("a1", "u-a", OTHER, 8, (None, None))
BULK_SIZE = 460
# In the second 450-entry chunk and not its last pair.
BULK_ERRORED = 455


def _video(video_id: str, uuid: str, host: str, n: int) -> dict:
    """The `videos` values the fixture stores for one video: each text column names its video, each integer is distinct."""
    values = {column: f"{column}:{video_id}@{host}" for column in VIDEO_TEXT}
    values.update({column: n * 10 + i for i, column in enumerate(VIDEO_INT)})
    values.update(video_id=video_id, video_uuid=uuid, instance_domain=host)
    return values


def _row(video_id: str, uuid: str, host: str, n: int, channel: tuple) -> dict:
    """The metadata row a fixture video should come back as."""
    return {**_video(video_id, uuid, host, n), "channel_display_name": channel[0], "channel_avatar_url": channel[1], "embedding_dim": 3, "model_name": "m"}


def _add(conn: sqlite3.Connection, video: tuple, error_count: int | None = 0, embedded: bool = True) -> None:
    video_id, uuid, host, n, channel = video
    values = {**_video(video_id, uuid, host, n), "error_count": error_count}
    conn.execute(f"INSERT INTO videos ({', '.join(values)}) VALUES ({', '.join('?' * len(values))})", list(values.values()))
    if embedded:
        conn.execute("INSERT INTO video_embeddings VALUES (?, ?, x'00', 3, 'm')", (video_id, host))
    if channel[0] is not None:
        conn.execute("INSERT INTO channels VALUES (?, ?, ?, ?)", (values["channel_id"], host, *channel))


def _bulk(i: int) -> tuple:
    return (f"c{i:03d}", f"uc{i:03d}", BULK, 100 + i, (None, None))


def _by_uuids(conn: sqlite3.Connection, *pairs: tuple[str, str], threshold: int | None = THRESHOLD) -> dict:
    return metadata.fetch_metadata_by_uuids(conn, [{"video_uuid": uuid, "instance_domain": host} for uuid, host in pairs], error_threshold=threshold)


@pytest.fixture
def conn(tmp_path):
    db = sqlite3.connect(tmp_path / "metadata.db")
    db.row_factory = sqlite3.Row
    columns = ", ".join([f"{column} TEXT" for column in VIDEO_TEXT] + [f"{column} INTEGER" for column in VIDEO_INT] + ["error_count INTEGER"])
    db.execute(f"CREATE TABLE videos ({columns}, PRIMARY KEY (video_id, instance_domain))")
    db.execute("CREATE TABLE video_embeddings (video_id TEXT, instance_domain TEXT, embedding BLOB, embedding_dim INTEGER, model_name TEXT, PRIMARY KEY (video_id, instance_domain))")
    db.execute("CREATE TABLE channels (channel_id TEXT, instance_domain TEXT, display_name TEXT, avatar_url TEXT)")
    _add(db, A1)
    _add(db, B1, error_count=None)
    # Stored s2, s1, s3, so the SELECT yields them in that order (observed): the lowest id is neither the first row nor the last.
    _add(db, S2)
    _add(db, S1)
    _add(db, S3)
    _add(db, E1, error_count=5)
    _add(db, N1, embedded=False)
    _add(db, A1_OTHER)
    db.commit()
    yield db
    db.close()


def test_a_uuid_pair_gets_the_row_the_id_lookup_gives_its_video(conn):
    by_uuid = _by_uuids(conn, ("u-b", HOST))
    by_id = metadata.fetch_metadata_by_ids(conn, [{"video_id": "b1", "instance_domain": HOST}], error_threshold=THRESHOLD)
    assert set(by_uuid) == {"u-b::h.example"}  # C1
    assert set(by_uuid["u-b::h.example"]) == set(ROW_KEYS)  # C1
    assert by_uuid["u-b::h.example"] == by_id["b1::h.example"]  # C1
    assert by_uuid["u-b::h.example"] == _row(*B1)  # C1


def test_a_uuid_pair_matches_only_its_exact_uuid_and_host(conn):
    assert _by_uuids(conn, ("u-a", HOST)) == {"u-a::h.example": _row(*A1)}  # C1
    assert _by_uuids(conn, ("u-a", HOST), ("u-a", OTHER)) == {"u-a::h.example": _row(*A1), "u-a::other.example": _row(*A1_OTHER)}  # C1
    assert _by_uuids(conn, ("U-A", HOST)) == {}  # C1
    assert _by_uuids(conn, ("u-a", "H.EXAMPLE")) == {}  # C1
    assert _by_uuids(conn, ("u-n", HOST)) == {}  # C1


def test_an_empty_uuid_list_gives_nothing_and_runs_no_statement(conn):
    statements: list[str] = []
    conn.set_trace_callback(statements.append)
    assert _by_uuids(conn, ("u-a", HOST)) != {}
    assert statements, "the trace saw no statement for a lookup that found a row"
    statements.clear()
    assert _by_uuids(conn) == {}  # C1
    assert statements == []  # C1


def test_a_shared_uuid_pair_keeps_the_lowest_video_id_under_the_threshold(conn):
    assert _by_uuids(conn, ("u-s", HOST)) == {"u-s::h.example": _row(*S1)}  # C2
    conn.execute("UPDATE videos SET error_count = 3 WHERE video_id = 's1'")
    assert _by_uuids(conn, ("u-s", HOST)) == {"u-s::h.example": _row(*S2)}  # C2
    conn.execute("UPDATE videos SET error_count = 2 WHERE video_id = 's1'")
    assert _by_uuids(conn, ("u-s", HOST)) == {"u-s::h.example": _row(*S1)}  # C2
    conn.execute("UPDATE videos SET error_count = 5 WHERE video_id = 's1'")
    assert _by_uuids(conn, ("u-s", HOST)) == {"u-s::h.example": _row(*S2)}  # C2
    assert _by_uuids(conn, ("u-s", HOST), threshold=None) == {"u-s::h.example": _row(*S1)}  # C2


def test_an_errored_video_s_uuid_pair_is_dropped_only_while_a_threshold_is_set(conn):
    assert _by_uuids(conn, ("u-e", HOST)) == {}  # C2
    assert _by_uuids(conn, ("u-e", HOST), threshold=None) == {"u-e::h.example": _row(*E1)}  # C2


def test_the_id_lookup_returns_the_joined_row_and_skips_an_unembedded_video(conn):
    entries = [{"video_id": "a1", "instance_domain": HOST}, {"video_id": "n1", "instance_domain": HOST}]
    assert metadata.fetch_metadata_by_ids(conn, entries) == {"a1::h.example": _row(*A1)}


def test_both_lookups_return_every_healthy_video_across_the_450_entry_chunk_boundary(conn):
    for i in range(BULK_SIZE):
        _add(conn, _bulk(i), error_count=5 if i == BULK_ERRORED else 0)
    conn.commit()
    healthy = [i for i in range(BULK_SIZE) if i != BULK_ERRORED]
    by_id = metadata.fetch_metadata_by_ids(conn, [{"video_id": _bulk(i)[0], "instance_domain": BULK} for i in range(BULK_SIZE)], error_threshold=THRESHOLD)
    # Open item A, option 1: the id query's threshold binds to the last pair of each chunk only, so c455 is left unasserted here.
    assert {f"{_bulk(i)[0]}::{BULK}" for i in healthy} <= set(by_id)
    assert by_id[f"c452::{BULK}"] == _row(*_bulk(452))
    by_uuid = _by_uuids(conn, *[(_bulk(i)[1], BULK) for i in range(BULK_SIZE)])
    assert {key: row["video_id"] for key, row in by_uuid.items()} == {f"{_bulk(i)[1]}::{BULK}": _bulk(i)[0] for i in healthy}
    assert by_uuid[f"uc452::{BULK}"] == _row(*_bulk(452))

```


Gate: satisfied

## 2026-09-27 - Step 7 - Phase 1 (Engine uuid-keyed metadata lookup) - red (audit round 1)

`tests/tmp/test_14_batch_like_resolution_phase1.py` exited 1.

```
  tests/tmp/test_14_batch_like_resolution_phase1.py  6 failed, 1 passed                     0.0s
  -------------------------------------------------
  total                                              6 failed, 1 passed                     0.2s wall, 1 lane

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

## 2026-09-27 - Step 7 - Phase 1 (Engine uuid-keyed metadata lookup) - audit (round 1)

- AUDIT: devsecops-test-shape-auditor - PASS
- AUDIT: devsecops-test-claim-auditor - PASS
- OUTSTANDING: 1 UNCARRIED clause(s) - D15

### devsecops-test-shape-auditor

```
SHAPE AUDIT — VERDICT: PASS

CRITICAL
none

RECOMMENDATIONS
none

PREDICTED FAILURE
Every test that goes through `_by_uuids` fails at tests/tmp/test_14_batch_like_resolution_phase1.py:77 with
`AttributeError: module 'data.metadata' has no attribute 'fetch_metadata_by_uuids'`. The first to fail is
test_a_uuid_pair_gets_the_row_the_id_lookup_gives_its_video, at line 103. The bulk test gets past its id-path
assertions at lines 157-158 and then fails at line 159. test_the_id_lookup_returns_the_joined_row_and_skips_an_unembedded_video
never calls the uuid lookup and should pass: it only pins the id path.

NOT ASSESSED
1. `code_under_test` listed tests/tmp/test_metadata_uuid_entries.py (NEW), which does not resolve. It was
   not read.
2. `code_under_test` listed engine/server/data/metadata.py as EDITED, but it does not define
   `fetch_metadata_by_uuids`. Grep over engine/ also found nothing. The stub question was answered from the
   assertion form alone, not against an implementation.
```

### devsecops-test-claim-auditor

CLAIM AUDIT — VERDICT: PASS

CLAUSE MAP  (38 clauses: 5 must_prove, 26 docstring, 7 name)
| id | source | clause | assertion | excludes | status |
|---|---|---|---|---|---|
| C1a | must_prove | "the same row dict that `fetch_metadata_by_ids` returns for that video" | :107 | a uuid path that builds its own row: a trimmed dict, dropped joins, or renamed or re-typed values | CARRIED |
| C1b | must_prove | exact match on `video_uuid` | :114 | case-insensitive uuid matching (`COLLATE NOCASE`, `lower()`) | CARRIED |
| C1c | must_prove | exact match on `instance_domain` | :112, :113, :115 | matching on the uuid alone, where other.example's a1 is returned or overwrites; case-insensitive host matching | CARRIED |
| C2a | must_prove | several videos share a pair, and the lowest `video_id` is kept | :130 | a last-row-wins dict overwrite gives s3. First-row-wins gives s2, but only because the rows come back in the order s2, s1, s3, and nothing asserts that order (see D15) | CARRIED |
| C2b | must_prove | "among those under the error threshold" | :132, :136, :134 | pick-then-filter gives `{}` at :136; `<=` against the threshold keeps s1 at :132; applying no filter keeps s1 at :132/:136 | CARRIED |
| D1 | docstring | "answers an exact pair with the row `fetch_metadata_by_ids` gives that video" | :107 | a uuid row that differs from the id row | CARRIED |
| D2 | docstring | "a pair shared by several videos with the lowest `video_id` under the error threshold" | :130, :132, :136 | the same as C2a and C2b | CARRIED |
| D3 | docstring | "keyed `u-b::h.example`" | :105 | keying by `like_key` (`b1::h.example`), or returning more than one key | CARRIED |
| D4 | docstring | "the 29-key row" | :106 | a row with keys missing or extra | CARRIED |
| D5 | docstring | "its `channels` and `video_embeddings` columns joined in" | :108 | leaving out the channels LEFT JOIN, so `channel_display_name` is None; dropping `embedding_dim`/`model_name` | CARRIED |
| D6 | docstring | "the same one the fixture stored" | :108 | both lookups being wrong in the same way, which :107 alone would pass | CARRIED |
| D7 | docstring | "b1's NULL `error_count` does not exclude it" | :105 (threshold 3 by default at :76) | `error_count < ?` without `IS NULL`, which gives `{}` | CARRIED |
| D8 | docstring | "`u-a@h.example` gives the h.example a1 and not the other.example a1" | :112 | a match on the uuid alone | CARRIED |
| D9 | docstring | "Asking for both gives each under its own key" | :113 | keying by uuid only, so one host overwrites the other | CARRIED |
| D10 | docstring | "`U-A@h.example` ... give `{}`" | :114 | a case-insensitive uuid match | CARRIED |
| D11 | docstring | "`u-a@H.EXAMPLE` ... give `{}`" | :115 | a case-insensitive host match | CARRIED |
| D12 | docstring | "`u-n@h.example` (no embedding) give[s] `{}`" | :116 | a LEFT JOIN on `video_embeddings` | CARRIED |
| D13 | docstring | "An empty list gives `{}`" | :125 | returning something other than an empty dict on empty input | CARRIED |
| D14 | docstring | "and runs no SQL statement on the connection" | :126, control at :122-123 | having no early return, so a query or setup statement still runs | CARRIED |
| D15 | docstring | "the three `u-s` siblings come out of the SELECT as s2, s1, s3 (observed)" | none | nothing: the order is stated but never asserted, although the first-row-wins exclusion in C2a depends on it | UNCARRIED |
| D16 | docstring | "the lookup keeps s1" | :130 | first-row-wins or last-row-wins | CARRIED |
| D17 | docstring | "at 3 or 5 under threshold 3 it keeps s2" | :132, :136 | `<=` against the threshold; pick-then-filter | CARRIED |
| D18 | docstring | "at 2 it keeps s1" | :134 | an off-by-one threshold that excludes `error_count == threshold-1` | CARRIED |
| D19 | docstring | "with no threshold it keeps s1 at 5" | :137 | applying a filter when the threshold is None | CARRIED |
| D20 | docstring | "`u-e` (error_count 5) is dropped at threshold 3" | :141 | a uuid query without the error clause | CARRIED |
| D21 | docstring | "and returned with no threshold" | :142 | always applying the error clause | CARRIED |
| D22 | docstring | "a1's full row with the unembedded n1 skipped" (id path) | :147 | an id-path refactor that changes the row or LEFT JOINs embeddings | CARRIED |
| D23 | docstring | "both lookups return every healthy video" across 460 / the 450 chunk | :157, :160 | querying only the first chunk; a wrong parameter count per chunk | CARRIED |
| D24 | docstring | "The uuid lookup also drops the errored video in chunk 2" | :160 | copying the id path's OR-chain, which applies the threshold only to each chunk's last pair | CARRIED |
| D25 | docstring | "The id lookup is not asserted on that video" | :157 | a statement about the test's own scope; :157 is a subset check, which matches it | CARRIED |
| D26 | docstring | "in-process against a temporary SQLite database with the Engine's three joined tables. Nothing is stubbed" | :81-99 (fixture) | a statement about the harness, true as the fixture is built; no stub or patch appears in the file | CARRIED |
| N1 | name | "a uuid pair gets the row the id lookup gives its video" | :107 | same as C1a | CARRIED |
| N2 | name | "a uuid pair matches only its exact uuid and host" | :112-115 | uuid-only or case-insensitive matching | CARRIED |
| N3 | name | "an empty uuid list gives nothing and runs no statement" | :125, :126 | a non-empty result; a statement run on empty input | CARRIED |
| N4 | name | "a shared uuid pair keeps the lowest video_id under the threshold" | :130-136 | same as C2a and C2b | CARRIED |
| N5 | name | "an errored video's uuid pair is dropped only while a threshold is set" | :141, :142 | no error clause; an error clause applied unconditionally | CARRIED |
| N6 | name | "the id lookup returns the joined row and skips an unembedded video" | :147 | a changed id row; a LEFT JOIN on embeddings | CARRIED |
| N7 | name | "both lookups return every healthy video across the 450-entry chunk boundary" | :157, :160 | a first-chunk-only query on either path | CARRIED |

CRITICAL
none

RECOMMENDATIONS
1. whole-claim (rules/testing.md) — tests/tmp/test_14_batch_like_resolution_phase1.py:5
   D15 is UNCARRIED. The docstring says the `u-s` siblings "come out of the SELECT as s2, s1, s3 (observed)", but no assertion checks that order. The order matters: `:130` rules out a first-row-wins pick only while the scan returns s2 first. If the order were s1, s2, s3, first-row-wins would pass :130, :132 and :136. Either assert the order the rows come back in, or narrow the sentence.
2. bounds (rules/testing.md) — tests/tmp/test_14_batch_like_resolution_phase1.py:76
   The only thresholds tested are 3 and None. The existing code in `metadata.py:128` treats `error_threshold > 0` as "set", but `error_threshold=0` is never tested, and neither is a negative threshold. N5 ("only while a threshold is set") does not say which side 0 falls on.
3. normal-and-abnormal-paths (rules/testing.md) — tests/tmp/test_14_batch_like_resolution_phase1.py:77
   Every entry `_by_uuids` builds is well formed. No test covers an entry with a missing `video_uuid` key, a None or empty `instance_domain`, or the same pair repeated in one request. That leaves the malformed-input failure mode of the uuid lookup untested.

OBSERVATIONS
none

NOT ASSESSED
1. `code_under_test` lists `engine/server/data/metadata.py` (EDITED), but the file as read does not define `fetch_metadata_by_uuids`. The call at :77 therefore targets a function that is not written yet. Its return contract (a dict keyed `video_uuid::instance_domain`, and the `error_threshold` keyword) was judged from the test alone, not against an implementation.
2. `code_under_test` lists `tests/tmp/test_metadata_uuid_entries.py` (NEW), which does not exist, so it was not read.
3. No `fixtures_path` was supplied and no `conftest.py` exists under `tests/tmp`. The test defines its only fixture, `conn`, at :80-99, so nothing is missing for independence.
4. The Grep for the `fetch_metadata_by_uuids` definition also matched `docs/project/plans/16-14-batch-like-resolution.record.md`, which is the build's working record. This verdict rests on `testing.md`, the test file and `metadata.py`, and cites no reasoning from that record.

## 2026-09-27 - Step 7 - Phase 1 (Engine uuid-keyed metadata lookup) - self-check (audit round 2, send-back 0)

`tests/tmp/test_14_batch_like_resolution_phase1.py`, surface `checkpoint`. Collection exit 0.

- C1 - tests/tmp/test_14_batch_like_resolution_phase1.py:105-108: the result for `u-b@h.example` has the single key `u-b::h.example`. Its row has exactly the 29 ROW_KEYS, equals `fetch_metadata_by_ids(b1@h.example)["b1::h.example"]`, and equals the fixture-stored `_row(*B1)`. Lines :112-116 add exact-match checks: the h.example a1 and not the other.example a1; both hosts, each under its own key; `U-A` gives `{}`; `H.EXAMPLE` gives `{}`; the unembedded `u-n` gives `{}`. Lines :125-126 check that an empty list gives `{}` and runs zero statements, with a control at :122-123. - expected: `{"u-b::h.example": <b1's 29-key row with Chan B/ava-b, embedding_dim 3, model_name m>}`, identical to the id path's row. The uuid and host mismatch cases give `{}`. - excludes: A uuid path that builds its own trimmed row, or drops the channels join, fails :106-108 (for example `channel_display_name` None, or keys missing). Matching on the uuid alone returns or overwrites with the other.example a1, which fails :112-113. COLLATE NOCASE or lower() gives a row at :114 or :115 where `{}` is expected. `error_count < ?` without `IS NULL` gives `{}` at :105.
- C2 - tests/tmp/test_14_batch_like_resolution_phase1.py:131, :133, :135, :137, :138 check `u-s@h.example`, the shared pair. It keeps s1; with s1.error_count 3 it keeps s2; with 2, s1; with 5, s2; with 5 and no threshold, s1. The control at :130 shows that the scan order is s2, s1, s3. Lines :142-143 check that `u-e` is dropped at threshold 3 and returned at None. - expected: Respectively `{"u-s::h.example": _row(*S1)}`, `_row(*S2)`, `_row(*S1)`, `_row(*S2)` and `_row(*S1)`. Then `{}` for u-e at threshold 3, and `{"u-e::h.example": _row(*E1)}` at None. - excludes: Last-row-wins gives s3 at :131. First-row-wins gives s2 at :131 while the order :130 pins holds. Pick-then-filter gives `{}` at :137. A `<=` threshold keeps s1 at :133. An off-by-one that drops error_count 2 gives s2 at :135. Applying the filter when the threshold is None gives s2 at :138, and `{}` for u-e at :143. Omitting the error clause keeps s1 at :133 and :137, and returns u-e at :142.

<exemptions>
none
</exemptions>

<items>
<item id="D15">
<disposition>fixed</disposition>
<what>I narrowed the docstring and added a control assertion. The old sentence said the siblings "come out of the SELECT as s2, s1, s3 (observed)". That describes the production query, which has not been written yet, so no test here can assert its order. The sentence now reads: "The fixture stores the three `u-s` siblings as s2, s1, s3, and a scan of `videos` yields them in that order, so the lowest id is neither the first row nor the last. The lookup keeps s1." That sentence is now carried by a new first line in the shared-pair test, :130: `[row["video_id"] for row in conn.execute("SELECT video_id FROM videos WHERE video_uuid = 'u-s'")] == ["s2", "s1", "s3"]`. It excludes a fixture that has drifted, for example one reordered or given an index, where s1 is scanned first. In that case a first-row-wins pick would pass :131, :133 and :137. The assertion arms C2a's first-row-wins exclusion instead of leaving it on an unchecked premise. I ran the file and saw this control pass: the shared-pair test now fails at :131 on the missing function, not at :130. I also changed the fixture comment at :90 so it no longer claims "(observed)", and it now points at this assertion.</what>
</item>
</items>

<findings_addressed>
Claim audit REC 1 (D15 order stated but never asserted): taken. I narrowed the docstring to the fixture's scan order and asserted that order at :130, as a control before the C2 assertions. The run shows it passing. Both auditors report no CRITICAL findings. I left REC 2 (threshold 0 or negative) and REC 3 (malformed entries) alone. Neither is a must_prove clause of this phase, and pinning either would fix a contract the operator has not approved.
</findings_addressed>

<rows>
<row clause="C1">
<assertion>tests/tmp/test_14_batch_like_resolution_phase1.py:105-108: the result for `u-b@h.example` has the single key `u-b::h.example`. Its row has exactly the 29 ROW_KEYS, equals `fetch_metadata_by_ids(b1@h.example)["b1::h.example"]`, and equals the fixture-stored `_row(*B1)`. Lines :112-116 add exact-match checks: the h.example a1 and not the other.example a1; both hosts, each under its own key; `U-A` gives `{}`; `H.EXAMPLE` gives `{}`; the unembedded `u-n` gives `{}`. Lines :125-126 check that an empty list gives `{}` and runs zero statements, with a control at :122-123.</assertion>
<expected>`{"u-b::h.example": <b1's 29-key row with Chan B/ava-b, embedding_dim 3, model_name m>}`, identical to the id path's row. The uuid and host mismatch cases give `{}`.</expected>
<wrong_implementation>A uuid path that builds its own trimmed row, or drops the channels join, fails :106-108 (for example `channel_display_name` None, or keys missing). Matching on the uuid alone returns or overwrites with the other.example a1, which fails :112-113. COLLATE NOCASE or lower() gives a row at :114 or :115 where `{}` is expected. `error_count < ?` without `IS NULL` gives `{}` at :105.</wrong_implementation>
</row>
<row clause="C2">
<assertion>tests/tmp/test_14_batch_like_resolution_phase1.py:131, :133, :135, :137, :138 check `u-s@h.example`, the shared pair. It keeps s1; with s1.error_count 3 it keeps s2; with 2, s1; with 5, s2; with 5 and no threshold, s1. The control at :130 shows that the scan order is s2, s1, s3. Lines :142-143 check that `u-e` is dropped at threshold 3 and returned at None.</assertion>
<expected>Respectively `{"u-s::h.example": _row(*S1)}`, `_row(*S2)`, `_row(*S1)`, `_row(*S2)` and `_row(*S1)`. Then `{}` for u-e at threshold 3, and `{"u-e::h.example": _row(*E1)}` at None.</expected>
<wrong_implementation>Last-row-wins gives s3 at :131. First-row-wins gives s2 at :131 while the order :130 pins holds. Pick-then-filter gives `{}` at :137. A `<=` threshold keeps s1 at :133. An off-by-one that drops error_count 2 gives s2 at :135. Applying the filter when the threshold is None gives s2 at :138, and `{}` for u-e at :143. Omitting the error clause keeps s1 at :133 and :137, and returns u-e at :142.</wrong_implementation>
</row>
</rows>

<answers>
1. No. Every negative has a positive control. :114-116 sit beside :112-113, which return rows through the same call. :126 is armed by :122-123. :142 is paired with :143. If the code under test were deleted, every uuid test would fail.
2. No. The expected rows come from `_row`, built from the fixture's stored values, not from a production transform. :108 turns red if the joins are dropped in the uuid SELECT, and :107 turns red if its row construction differs from the id path's. The new :130 reads the fixture table, not production output. It is a control on the fixture's premise and carries no clause. It does not mirror the production query's logic: it is a plain scan with no join, no threshold and no pick.
3. No. The threshold is read at the values 2, 3 and 5 and at None. Matching is read across uuid case, host case, a second host and an unembedded video. Each expected row is a separately stored video with distinct values.
4. No. There are no doubles. `data.metadata` is imported for real and runs on a real SQLite file.
5. Yes, it collects. The run collected 7 tests: 6 failed and 1 passed, the same as before. The new line uses only `conn.execute`, and `row["video_id"]` works on the fixture's `sqlite3.Row` factory.
6. Yes. The scan order s2, s1, s3 is observed. :130 passed in this run, because the shared-pair test's failure moved to :131. The earlier probe had observed the same order under the draft query. The uuid return contract is still a prediction, as stated in the previous reply.
7. Yes. All 6 failures are `AttributeError: module 'data.metadata' has no attribute 'fetch_metadata_by_uuids'`. They are raised at :77 and reached from :103, :112, :122, :131, :142 and :160. The id pin passes.
No question was answered yes as a failing, so nothing needed rewriting beyond the D15 fix. The probe files `tests/tmp/probe_phase1_metadata.py` and `tests/tmp/probe_phase1_against_impls.py` are still on disk because I have no delete tool, and they should be removed.
</answers>

Gate: satisfied

## 2026-09-27 - Step 7 - Phase 1 (Engine uuid-keyed metadata lookup) - red (audit round 2)

`tests/tmp/test_14_batch_like_resolution_phase1.py` exited 1.

```
  tests/tmp/test_14_batch_like_resolution_phase1.py  6 failed, 1 passed                     0.0s
  -------------------------------------------------
  total                                              6 failed, 1 passed                     0.2s wall, 1 lane

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

## 2026-09-27 - Step 7 - Phase 1 (Engine uuid-keyed metadata lookup) - audit (round 2)

- AUDIT: devsecops-test-shape-auditor - PASS
- AUDIT: devsecops-test-claim-auditor - PASS
- OUTSTANDING: nothing

### devsecops-test-shape-auditor

```
SHAPE AUDIT — VERDICT: PASS

CRITICAL
none

RECOMMENDATIONS
none

PREDICTED FAILURE
Six tests fail. Each one reaches `_by_uuids` (line 77), the only caller of
`metadata.fetch_metadata_by_uuids(...)`, and fails there with
`AttributeError: module 'data.metadata' has no attribute 'fetch_metadata_by_uuids'`.
Where each test first reaches it:
- test_a_uuid_pair_gets_the_row_the_id_lookup_gives_its_video: line 103
- test_a_uuid_pair_matches_only_its_exact_uuid_and_host: line 112
- test_an_empty_uuid_list_gives_nothing_and_runs_no_statement: line 122
- test_a_shared_uuid_pair_keeps_the_lowest_video_id_under_the_threshold: line 131
- test_an_errored_video_s_uuid_pair_is_dropped_only_while_a_threshold_is_set: line 142
- test_both_lookups_return_every_healthy_video_across_the_450_entry_chunk_boundary:
  line 160, after its id-lookup assertions at lines 158–159 pass
test_the_id_lookup_returns_the_joined_row_and_skips_an_unembedded_video (line 146)
passes, because it touches only the existing `fetch_metadata_by_ids`.

NOT ASSESSED
1. `code_under_test` listed tests/tmp/test_metadata_uuid_entries.py. That path does not
   resolve, so its contents were not reviewed.
2. `fetch_metadata_by_uuids` is not defined anywhere under engine/, so the stub
   question was answered from the test's assertions alone. The answer: each assertion
   compares against a literal built from the fixture (`_row(*...)` or exact key sets).
   The fixture stores the siblings as s2, s1, s3 (line 130) and changes s1's
   error_count to 3, 2 and 5 (lines 132–138). A stub or hard-coded return fails, and so
   do these wrong versions:
   - keeping the first row (s2 at line 131) or the last row (s3 at line 131)
   - ignoring the threshold (line 133)
   - using `<=` against the threshold (line 133)
   - picking the lowest id before applying the threshold filter (line 133 would give {})
   - keying rows by video_id (line 105)
   - matching case-insensitively (lines 114–115)
   - returning the id lookup's output unchanged (lines 105 and 112)
   Anti-pattern pass: nothing found. Every negative assertion (lines 114–116, 125–126,
   142) has a positive control in the same test (lines 112–113, 122–123, 143).
   Ladder pass: the test sits at rung 1, direct invocation of the functions, which is
   the highest rung this invariant supports.
```

### devsecops-test-claim-auditor

CLAIM AUDIT — VERDICT: PASS

CLAUSE MAP  (38 clauses: 5 must_prove, 26 docstring, 7 name)
| id | source | clause | assertion | excludes | status |
|---|---|---|---|---|---|
| C1a | must_prove | "the same row dict that `fetch_metadata_by_ids` returns for that video" | :107 | a uuid path that builds its own row: a trimmed dict, dropped joins, or renamed or re-typed values | CARRIED |
| C1b | must_prove | exact match on `video_uuid` | :114 | case-insensitive uuid matching (`COLLATE NOCASE`, `lower()`) | CARRIED |
| C1c | must_prove | exact match on `instance_domain` | :112, :113, :115 | a match on the uuid alone, where other.example's a1 is returned or overwrites the other; case-insensitive host matching | CARRIED |
| C2a | must_prove | several videos share a pair, and the lowest `video_id` is kept | :131, with the order pinned at :130 | last-row-wins gives s3. First-row-wins gives s2 while the scan order s2, s1, s3 holds, and :130 now asserts that order | CARRIED |
| C2b | must_prove | "among those under the error threshold" | :133, :135, :137 | pick-then-filter gives `{}` at :137; `<=` against the threshold keeps s1 at :133; applying no filter keeps s1 at :133 and :137 | CARRIED |
| D1 | docstring | "answers an exact pair with the row `fetch_metadata_by_ids` gives that video" | :107 | a uuid row that differs from the id row | CARRIED |
| D2 | docstring | "a pair shared by several videos with the lowest `video_id` under the error threshold" | :131, :133, :137 | the same as C2a and C2b | CARRIED |
| D3 | docstring | "keyed `u-b::h.example`" | :105 | keying by `like_key` (`b1::h.example`), or returning more than one key | CARRIED |
| D4 | docstring | "the 29-key row" | :106 | a row with keys missing or extra | CARRIED |
| D5 | docstring | "its `channels` and `video_embeddings` columns joined in" | :108 | leaving out the channels LEFT JOIN, so `channel_display_name` is None; dropping `embedding_dim` or `model_name` | CARRIED |
| D6 | docstring | "the same one the fixture stored" | :108 | both lookups being wrong in the same way, which :107 alone would pass | CARRIED |
| D7 | docstring | "b1's NULL `error_count` does not exclude it" | :105 (threshold 3 by default at :76) | `error_count < ?` without `IS NULL`, which gives `{}` | CARRIED |
| D8 | docstring | "`u-a@h.example` gives the h.example a1 and not the other.example a1" | :112 | a match on the uuid alone | CARRIED |
| D9 | docstring | "Asking for both gives each under its own key" | :113 | keying by uuid only, so one host overwrites the other | CARRIED |
| D10 | docstring | "`U-A@h.example` ... give `{}`" | :114 | a case-insensitive uuid match | CARRIED |
| D11 | docstring | "`u-a@H.EXAMPLE` ... give `{}`" | :115 | a case-insensitive host match | CARRIED |
| D12 | docstring | "`u-n@h.example` (no embedding) give[s] `{}`" | :116 | a LEFT JOIN on `video_embeddings` | CARRIED |
| D13 | docstring | "An empty list gives `{}`" | :125 | returning something other than an empty dict on empty input | CARRIED |
| D14 | docstring | "and runs no SQL statement on the connection" | :126, control at :122-123 | no early return, so a query or setup statement still runs | CARRIED |
| D15 | docstring | narrowed to "The fixture stores the three `u-s` siblings as s2, s1, s3, and a scan of `videos` yields them in that order" | :130 | a fixture that has drifted (reordered, or scanned in id order), where first-row-wins would pass :131 | CARRIED |
| D16 | docstring | "The lookup keeps s1" | :131 | first-row-wins or last-row-wins | CARRIED |
| D17 | docstring | "at 3 or 5 under threshold 3 it keeps s2" | :133, :137 | `<=` against the threshold; pick-then-filter | CARRIED |
| D18 | docstring | "at 2 it keeps s1" | :135 | an off-by-one threshold that excludes `error_count == threshold-1` | CARRIED |
| D19 | docstring | "with no threshold it keeps s1 at 5" | :138 | applying a filter when the threshold is None | CARRIED |
| D20 | docstring | "`u-e` (error_count 5) is dropped at threshold 3" | :142 | a uuid query with no error clause | CARRIED |
| D21 | docstring | "and returned with no threshold" | :143 | always applying the error clause | CARRIED |
| D22 | docstring | "a1's full row with the unembedded n1 skipped" (id path) | :148 | an id-path refactor that changes the row or LEFT JOINs embeddings | CARRIED |
| D23 | docstring | "both lookups return every healthy video" across 460 videos and the 450-entry chunk | :158, :161 | querying only the first chunk; a wrong parameter count per chunk | CARRIED |
| D24 | docstring | "The uuid lookup also drops the errored video in chunk 2" | :161 | copying the id path's OR-chain, which applies the threshold only to each chunk's last pair | CARRIED |
| D25 | docstring | "The id lookup is not asserted on that video" | :158 | a statement about the test's own scope; :158 is a subset check, which matches it | CARRIED |
| D26 | docstring | "in-process against a temporary SQLite database with the Engine's three joined tables. Nothing is stubbed" | :80-99 (fixture) | a statement about the harness, true as the fixture is built; no stub or patch appears in the file | CARRIED |
| N1 | name | "a uuid pair gets the row the id lookup gives its video" | :107 | same as C1a | CARRIED |
| N2 | name | "a uuid pair matches only its exact uuid and host" | :112-115 | uuid-only or case-insensitive matching | CARRIED |
| N3 | name | "an empty uuid list gives nothing and runs no statement" | :125, :126 | a non-empty result; a statement run on empty input | CARRIED |
| N4 | name | "a shared uuid pair keeps the lowest video_id under the threshold" | :131-138 | same as C2a and C2b | CARRIED |
| N5 | name | "an errored video's uuid pair is dropped only while a threshold is set" | :142, :143 | no error clause; an error clause applied unconditionally | CARRIED |
| N6 | name | "the id lookup returns the joined row and skips an unembedded video" | :148 | a changed id row; a LEFT JOIN on embeddings | CARRIED |
| N7 | name | "both lookups return every healthy video across the 450-entry chunk boundary" | :158, :161 | a first-chunk-only query on either path | CARRIED |

CRITICAL
none

RECOMMENDATIONS
none

OBSERVATIONS
1. whole-claim (rules/testing.md) — tests/tmp/test_14_batch_like_resolution_phase1.py:5, :130
   D15 was resolved two ways. The prose was narrowed, from "come out of the SELECT as s2, s1, s3 (observed)" to "a scan of `videos` yields them in that order". An assertion was also added at :130:
   `assert [row["video_id"] for row in conn.execute("SELECT video_id FROM videos WHERE video_uuid = 'u-s'")] == ["s2", "s1", "s3"], ...`
   The narrowed sentence is carried. The old claim was about the order the production SELECT returns rows in, and nothing asserts that now. :130 reads a plain scan of `videos`, not the `video_embeddings JOIN videos` query the lookup runs. So C2a's exclusion of first-row-wins at :131 still depends on the join visiting the rows in the order the plain scan does. The docstring no longer claims more than :130 shows, so this does not block.
2. bounds (rules/testing.md) — tests/tmp/test_14_batch_like_resolution_phase1.py:76
   Carried over from round 1, and no ledger row names it. Only thresholds 3 and None are exercised. `error_threshold=0` and negative values are never tested, although `metadata.py:128` treats only `> 0` as a set threshold.
3. normal-and-abnormal-paths (rules/testing.md) — tests/tmp/test_14_batch_like_resolution_phase1.py:77
   Carried over from round 1, and no ledger row names it. Every entry `_by_uuids` builds is well formed. No test covers an entry missing `video_uuid`, a None or empty `instance_domain`, or the same pair repeated in one request.

NOT ASSESSED
1. `code_under_test` lists `engine/server/data/metadata.py` (EDITED), but the file as read does not define `fetch_metadata_by_uuids`. Its return contract (a dict keyed `video_uuid::instance_domain`, and the `error_threshold` keyword) was judged from the test alone.
2. `code_under_test` lists `tests/tmp/test_metadata_uuid_entries.py` (NEW), which does not exist, so it was not read.
3. No `fixtures_path` was supplied, and no `conftest.py` exists under `tests/tmp`. The test defines its only fixture, `conn`, at :80-99.
4. The Grep for `fetch_metadata_by_uuids` also matched the build's working record, `docs/project/plans/16-14-batch-like-resolution.record.md`. This verdict rests only on `testing.md`, the test file and `metadata.py`, and uses nothing from that record.

## 2026-09-27 - Step 7 - Phase 1 (Engine uuid-keyed metadata lookup) - checkpoint outcome (run 1)

`tests/tmp/test_14_batch_like_resolution_phase1.py` exited 0 after the phase landed.

<changes>
### `engine/server/data/metadata.py`

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
</changes>

<inner_tests>
none. The checkpoint covers C1 (exact pair match, 29-key row equal to the id lookup's, case sensitivity, unembedded video, empty input running no SQL) and C2 (lowest `video_id` among siblings stored out of order, threshold on and off, the chunk boundary). So the listed `tests/tmp/test_metadata_uuid_entries.py` was not needed and was not created.
</inner_tests>

<unanticipated>
none
</unanticipated>

<awaiting_operator>
none
</awaiting_operator>

```
  tests/tmp/test_14_batch_like_resolution_phase1.py  7 passed                               0.0s
  -------------------------------------------------
  total                                              7 passed                               0.2s wall, 1 lane

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

## 2026-09-27 - Step 7 - Phase 2 (Engine metadata endpoint accepts both entry forms) - must_prove

Quoted from the phase Intent, written at Step 6 before the checkpoint was drafted.

Intent:
`handle_internal_videos_metadata` in `engine/server/api/handlers/internal_client_reads.py` parses id-form and uuid-form entries with its own parser. It answers all of them in a single `db_lock` hold and emits each matched video once, at its first matching entry.

- C1 - A request body mixing id-form and uuid-form entries acquires `db_lock` exactly once.
- C2 - Each matched video appears once in `rows`, in the order of its first matching entry.

must_prove:
- C1 - A request body mixing id-form and uuid-form entries acquires `db_lock` exactly once.
- C2 - Each matched video appears once in `rows`, in the order of its first matching entry.

## 2026-09-27 - Step 7 - Phase 2 (Engine metadata endpoint accepts both entry forms) - self-check (audit round 1, send-back 0)

`tests/tmp/test_14_batch_like_resolution_phase2.py`, surface `checkpoint`. Collection exit 0.

- C1 - tests/tmp/test_14_batch_like_resolution_phase2.py:157 — for the mixed body `[uuid u-b, id a1, id b1, uuid u-a, uuid u-x]`, the pair (lock acquisitions, row video_ids) == (1, ["b1", "a1"]) - expected: (1, ["b1", "a1"]): one `db_lock` acquisition, and that one hold served both the uuid entry (b1) and the id entry (a1). - excludes: A separate lookup, and a separate lock hold, for each form reads (2, ["b1", "a1"]). The current id-only handler never resolves the uuid entry. The run showed it reading (1, ['a1', 'b1']), so that version of "exactly once" fails too, because the uuid entry was never served inside the hold.
- C1 - tests/tmp/test_14_batch_like_resolution_phase2.py:162 — for the second mixed body `[id a1, uuid u-x, uuid u-b, id b1]`, (acquisitions, set of per-statement "lock held" flags) == (1, {True}) - expected: (1, {True}): one acquisition, and every SQL statement ran while it was held. It is reached only after line 159 shows u-b was resolved in that same call. - excludes: A lock per form reads (2, {True}). A uuid lookup run after the lock is released reads (1, {True, False}).
- C2 - tests/tmp/test_14_batch_like_resolution_phase2.py:158 — the mixed body `[uuid u-b, id a1, id b1, uuid u-a, uuid u-x]` responds exactly `[[200, {ok, count 2, rows [b1, a1]}]]`, with complete rows - expected: [[200, {"ok": True, "count": 2, "rows": [b1 row, a1 row]}]]: b1 at its uuid entry, a1 at its id entry, u-x omitted. - excludes: The current id-only handler gives rows [a1, b1] (observed in the first run). No dedupe across forms gives [b1, a1, b1, a1] with count 4. Id rows emitted before uuid rows gives [a1, b1].
- C2 - tests/tmp/test_14_batch_like_resolution_phase2.py:159 — `[id a1, uuid u-x, uuid u-b, id b1]` responds with rows exactly [a1, b1] - expected: [[200, {"ok": True, "count": 2, "rows": [a1 row, b1 row]}]] - excludes: Emitting every uuid-matched row before the id rows gives [b1, a1]. No dedupe across forms gives [a1, b1, b1].
- C2 - tests/tmp/test_14_batch_like_resolution_phase2.py:178 — an item with video_id a1 and video_uuid u-b gives rows exactly [a1] - expected: [[200, {"ok": True, "count": 1, "rows": [a1 row]}]] - excludes: An item that feeds both lookups gives [a1, b1] with count 2. An item where the uuid takes precedence gives [b1].
- C2 - tests/tmp/test_14_batch_like_resolution_phase2.py:179 — `{"video_id": " a1 ", "video_uuid": "   ", "instance_domain": " h.example "}` gives rows exactly [a1] - expected: [[200, {"ok": True, "count": 1, "rows": [a1 row]}]] - excludes: Values used without stripping give no match, rows []. Treating a whitespace uuid as present gives a uuid lookup on "   " instead of the id match, also rows [].
- C2 - tests/tmp/test_14_batch_like_resolution_phase2.py:180 — `{"video_id": "   ", "video_uuid": " u-b "}` gives rows exactly [b1] - expected: [[200, {"ok": True, "count": 1, "rows": [b1 row]}]]. The b1 row shape was seen in this run's id-form output (Chan B / ava-b, integers 20..26, embedding_dim 3, model 'm'). - excludes: Dropping an item with a blank id instead of falling back to its uuid gives [[200, {'ok': True, 'count': 0, 'rows': []}]], as observed today.
- C2 - tests/tmp/test_14_batch_like_resolution_phase2.py:185 — `[uuid u-a, uuid u-a, id b1, id b1, uuid u-b, id a1]` gives rows exactly [a1, b1] - expected: [[200, {"ok": True, "count": 2, "rows": [a1 row, b1 row]}]] - excludes: The current id-only handler gives [b1, a1] (observed). Dedupe within each form but not across forms gives [a1, b1, b1, a1] with count 4. Id rows first gives [b1, a1].
- C2 - tests/tmp/test_14_batch_like_resolution_phase2.py:191 — `[uuid u-e, uuid u-a]` with no threshold gives rows exactly [e1, a1] - expected: [[200, {"ok": True, "count": 2, "rows": [e1 row (channel_display_name/avatar None), a1 row]}]]. The same value passed the control at line 190 through the id form. - excludes: Ignoring uuid-form entries gives rows [] (observed today). Applying a default threshold when none is set drops e1 and gives [a1].
- C2 - tests/tmp/test_14_batch_like_resolution_phase2.py:192 — the same body at threshold 3 gives rows exactly [a1] - expected: [[200, {"ok": True, "count": 1, "rows": [a1 row]}]] - excludes: Applying the error threshold only to the id lookup and not the uuid lookup gives [e1, a1]. Ignoring uuid entries gives [].

<assertions>
tests/tmp/test_14_batch_like_resolution_phase2.py:141 - the mixed body [uuid u-b, id a1, id b1, uuid u-a, uuid u-x] answers exactly [[200, {"ok": True, "count": 2, "rows": [b1 row, a1 row]}]]: full 29-key rows built independently from the fixture values, each video once at its first matching entry, u-x omitted. The unchanged handler gives [a1, b1] - C2
tests/tmp/test_14_batch_like_resolution_phase2.py:142 - the id-first mixed body [id a1, uuid u-x, uuid u-b, id b1] answers [a1, b1]. This catches an implementation that emits every uuid-form row before the id-form rows, which passes the body at :141 - C2
tests/tmp/test_14_batch_like_resolution_phase2.py:143 - the mixed body acquires db_lock exactly once. The lock counts `with` and `.acquire()` alike, so one hold per form (2) or per entry (5) fails - C1
tests/tmp/test_14_batch_like_resolution_phase2.py:144 - every SQL statement the mixed body runs is traced while the lock is held, and at least one statement runs. This catches one acquisition wrapping only one of the two lookups - C1
tests/tmp/test_14_batch_like_resolution_phase2.py:145 - the lock is released after the mixed body - C1
tests/tmp/test_14_batch_like_resolution_phase2.py:146 - the id-first mixed body also gives enters == 1, with every statement run under the lock - C1
tests/tmp/test_14_batch_like_resolution_phase2.py:151 - id-only [a1, b1, a1] answers [a1, b1], count 2 (pin: the unchanged handler already gives this) - C2
tests/tmp/test_14_batch_like_resolution_phase2.py:152 - id-only [a1, b1, a1] takes the lock once - C1
tests/tmp/test_14_batch_like_resolution_phase2.py:162 - an item with video_id a1 and video_uuid u-b answers [a1] only, not b1 and not both - C2
tests/tmp/test_14_batch_like_resolution_phase2.py:163 - padded " a1 " / " h.example " with a whitespace uuid answers [a1], so values are stripped - C2
tests/tmp/test_14_batch_like_resolution_phase2.py:164 - a blank video_id beside video_uuid " u-b " answers [b1]: a blank id is not valid, so the uuid decides (R1). The unchanged handler gives [] - C2
tests/tmp/test_14_batch_like_resolution_phase2.py:169 - [uuid u-a, uuid u-a, id b1, id b1, uuid u-b, id a1] answers exactly [a1, b1]: repeats within a form and a video reached by both forms each give one row. The unchanged handler gives [b1, a1] - C2
tests/tmp/test_14_batch_like_resolution_phase2.py:174 - control: [uuid u-e, uuid u-a] with no threshold answers [e1, a1], so u-e does resolve - control for C2
tests/tmp/test_14_batch_like_resolution_phase2.py:175 - the same body at threshold 3 answers [a1]: e1 (error_count 5) is not a match - C2
tests/tmp/test_14_batch_like_resolution_phase2.py:181 - {"entries": "x"} answers [[400, {"error": "Missing entries"}]] with 0 lock acquisitions - guard (R1)
tests/tmp/test_14_batch_like_resolution_phase2.py:182 - {} answers the same 400 with 0 acquisitions - guard (R1)
tests/tmp/test_14_batch_like_resolution_phase2.py:183 - an all-malformed body (non-dict, blank instance_domain, neither key, uuid without instance_domain, non-string instance_domain) answers [[200, {"ok": True, "count": 0, "rows": []}]] with 0 acquisitions - guard (R1)
tests/tmp/test_14_batch_like_resolution_phase2.py:188 - centroids with a uuid-only body hands the spied fetch_embeddings_by_ids exactly [] - guard (R1, centroids unchanged)
tests/tmp/test_14_batch_like_resolution_phase2.py:189 - that body answers [[200, {"ok": True, "space": None, "centroids": []}]] - guard
tests/tmp/test_14_batch_like_resolution_phase2.py:190 - centroids with the mixed body [uuid u-b, id a1] hands the lookup only [{video_id: a1, instance_domain: h.example}] - guard
tests/tmp/test_14_batch_like_resolution_phase2.py:191 - that body answers the single centroid [[0.707107, 0.707107, 0.0]], a1's (1, 1, 0) at unit length. Including b1's (2, 1, 0) would add a second centroid - guard
Against the unchanged handler, 4 tests fail for the intended reasons (the tests at :141, :164, :169 and :174) and 3 pass (the id-only pin, the guards, centroids).
</assertions>

<probes>
Probe tests/tmp/probe_14_phase2.py, run with ValidateTests ["tests/tmp/probe_14_phase2.py", "-s"], output read from tests/last_test_output.txt. It ran the same ENGINE_PY -c child (cwd=API_DIR, CountingLock, trace callback, spied fetch_embeddings_by_ids) against the unchanged handler, on a temp DB holding a1, b1 and e1 (error_count 5) with 3-float32 blobs (n, 1, 0). It printed:
- `from conftest import ENGINE_PY` works from tests/tmp once tests/active is on sys.path. ENGINE_PY exists. The child exited 0 with empty stderr.
- metadata mixed [u-b, a1, b1, u-a, u-x]: responses [[200, {ok: true, count: 2, rows: [a1 (29 keys), b1 (29 keys)]}]], enters 1, held_after false, statements_locked [true]. So the Engine interpreter's sqlite3 fires the trace callback once per SELECT while the lock is held, and the unchanged handler gives the wrong order, [a1, b1].
- metadata id-only [a1, b1, a1]: rows [a1, b1], enters 1, statements_locked [true].
- metadata {"entries": "x"} and {}: [[400, {"error": "Missing entries"}]], enters 0, no statements.
- metadata all-malformed: [[200, {ok: true, count: 0, rows: []}]], enters 0.
- centroids uuid-only [u-a]: [[200, {ok: true, space: null, centroids: []}]], enters 1, statements_locked [] (no SQL for an empty list), embedding_entries [[]].
- centroids mixed [u-b, id a1]: [[200, {ok: true, space: null, centroids: [[0.707107, 0.707107, 0.0]]}]], embedding_entries [[{video_id: a1, instance_domain: h.example}]].
Also: phase 1's one-byte blob x'00' cannot be used here, because the centroids handler decodes blobs with np.frombuffer(float32), which cannot read a single byte (reasoned, not run). That is why this fixture stores real 3-float vectors. The full-row expected values were confirmed by the real checkpoint's first run: the id-only, both-keys and padded cases matched _row(...) exactly against the unchanged handler.
</probes>

<unassertable>
none. Housekeeping: I have no delete tool, so the throwaway tests/tmp/probe_14_phase2.py is still on disk and needs removing, as do the phase 1 probes already there (tests/tmp/probe_14_phase1.py, probe_phase1_metadata.py, probe_phase1_against_impls.py). One deliberate departure from the phase 1 fixture: embeddings are real 3-float32 vectors instead of x'00', because the centroids guard decodes them. The metadata rows do not include the blob, so they are unaffected.
</unassertable>

### `tests/tmp/test_14_batch_like_resolution_phase2.py` - 11834 characters, inlined in full

```
"""`/internal/videos/metadata` answers a body of id-form and uuid-form entries under one `db_lock` hold, with each matched video once, at its first matching entry; `/internal/dislikes/centroids` still looks up only id-form entries.

- The mixed body `[uuid u-b, id a1, id b1, uuid u-a, uuid u-x]` gives exactly `[b1, a1]` with `count == 2`, and `[id a1, uuid u-x, uuid u-b, id b1]` gives `[a1, b1]`, each with one lock acquisition and every SQL statement run while that lock is held. The id-only body `[a1, b1, a1]` gives `[a1, b1]` with one acquisition.
- An item with a valid `video_id` and the `video_uuid` of another video gives the id's video; values are stripped; a blank `video_id` beside a valid `video_uuid` gives the uuid's video. Repeats within a form, and a video reached by both forms, give one row.
- The uuid entry of a video at `error_count` 5 is omitted at threshold 3, and returned in its first-match place with no threshold.
- `{"entries": "x"}` and `{}` give 400 `Missing entries`, and a body of only malformed items gives 200 with no rows, all three without taking the lock.
- On centroids, a uuid-only body hands the embedding lookup `[]` and gives no centroids; a mixed body hands it only the id entry and gives that video's unit vector.

The handlers import numpy, so they run under the Engine's interpreter in a child process, on a temporary database with the Engine's three joined tables, with only the HTTP body reader and responder patched; the embedding lookup is spied on, not replaced, and the lock counts every acquisition.
"""
from __future__ import annotations

import json
import sqlite3
import struct
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "tests" / "active") not in sys.path:
    sys.path.insert(0, str(ROOT / "tests" / "active"))

from conftest import ENGINE_PY  # noqa: E402

SERVER_DIR = ROOT / "engine" / "server"
API_DIR = SERVER_DIR / "api"
HOST = "h.example"
THRESHOLD = 3
VIDEO_TEXT = ("video_id", "video_uuid", "instance_domain", "channel_id", "channel_name", "channel_url", "account_name", "account_url", "title", "description", "tags_json", "category", "published_at", "video_url", "thumbnail_url", "embed_path", "preview_path", "last_checked_at")
VIDEO_INT = ("video_numeric_id", "duration", "views", "likes", "dislikes", "comments_count", "nsfw")
# (video_id, video_uuid, instance_domain, n, channel display_name/avatar_url), as in the phase 1 fixture.
A1 = ("a1", "u-a", HOST, 1, ("Chan A", "ava-a"))
B1 = ("b1", "u-b", HOST, 2, ("Chan B", "ava-b"))
E1 = ("e1", "u-e", HOST, 6, (None, None))
MISSING_ENTRIES = [[400, {"error": "Missing entries"}]]
NO_ROWS = [[200, {"ok": True, "count": 0, "rows": []}]]
# Runs each (route, body, threshold) case through the real handler and reports its responses, the lock's acquisitions, whether each SQL statement ran under the lock, and what the embedding lookup was handed.
CHILD = r'''
import json, sqlite3, sys, threading
from types import SimpleNamespace
from unittest.mock import patch
sys.path[:0] = [sys.argv[1], sys.argv[2]]
from handlers import internal_client_reads as reads

class CountingLock:
    """A db_lock that counts every acquisition, through `with` or `acquire`."""
    def __init__(self):
        self._lock = threading.Lock()
        self.enters = 0
    def acquire(self, *args, **kwargs):
        self.enters += 1
        return self._lock.acquire(*args, **kwargs)
    def release(self):
        self._lock.release()
    def locked(self):
        return self._lock.locked()
    def __enter__(self):
        return self.acquire()
    def __exit__(self, *exc_info):
        self.release()

HANDLERS = {"metadata": reads.handle_internal_videos_metadata, "centroids": reads.handle_internal_dislike_centroids}
conn = sqlite3.connect(sys.argv[3])
conn.row_factory = sqlite3.Row
reports = []
for route, body, threshold in json.loads(sys.argv[4]):
    lock = CountingLock()
    statements = []
    conn.set_trace_callback(lambda sql: statements.append(lock.locked()))
    server = SimpleNamespace(db=conn, db_lock=lock, video_error_threshold=threshold)
    with patch.object(reads, "read_json_body", return_value=body), patch.object(reads, "respond_json") as respond, patch.object(reads, "fetch_embeddings_by_ids", wraps=reads.fetch_embeddings_by_ids) as embeddings:
        HANDLERS[route](object(), server)
    reports.append({"responses": [list(c.args[1:]) for c in respond.call_args_list], "enters": lock.enters, "held_after": lock.locked(), "statements_locked": statements, "embedding_entries": [c.args[1] for c in embeddings.call_args_list]})
print(json.dumps(reports))
'''


def _video(video_id: str, uuid: str, host: str, n: int) -> dict:
    """The `videos` values the fixture stores for one video: each text column names its video, each integer is distinct."""
    values = {column: f"{column}:{video_id}@{host}" for column in VIDEO_TEXT}
    values.update({column: n * 10 + i for i, column in enumerate(VIDEO_INT)})
    values.update(video_id=video_id, video_uuid=uuid, instance_domain=host)
    return values


def _row(video_id: str, uuid: str, host: str, n: int, channel: tuple) -> dict:
    """The metadata row a fixture video should come back as."""
    return {**_video(video_id, uuid, host, n), "channel_display_name": channel[0], "channel_avatar_url": channel[1], "embedding_dim": 3, "model_name": "m"}


def _add(conn: sqlite3.Connection, video: tuple, error_count: int | None = 0) -> None:
    video_id, uuid, host, n, channel = video
    values = {**_video(video_id, uuid, host, n), "error_count": error_count}
    conn.execute(f"INSERT INTO videos ({', '.join(values)}) VALUES ({', '.join('?' * len(values))})", list(values.values()))
    # A real 3-float32 vector (n, 1, 0), not phase 1's one-byte blob: the centroids handler decodes it.
    conn.execute("INSERT INTO video_embeddings VALUES (?, ?, ?, 3, 'm')", (video_id, host, struct.pack("<3f", float(n), 1.0, 0.0)))
    if channel[0] is not None:
        conn.execute("INSERT INTO channels VALUES (?, ?, ?, ?)", (values["channel_id"], host, *channel))


def _id(video_id: str) -> dict:
    return {"video_id": video_id, "instance_domain": HOST}


def _uuid(video_uuid: str) -> dict:
    return {"video_uuid": video_uuid, "instance_domain": HOST}


def _rows(*videos: tuple) -> list:
    return [[200, {"ok": True, "count": len(videos), "rows": [_row(*video) for video in videos]}]]


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "metadata.db"
    db = sqlite3.connect(path)
    columns = ", ".join([f"{column} TEXT" for column in VIDEO_TEXT] + [f"{column} INTEGER" for column in VIDEO_INT] + ["error_count INTEGER"])
    db.execute(f"CREATE TABLE videos ({columns}, PRIMARY KEY (video_id, instance_domain))")
    db.execute("CREATE TABLE video_embeddings (video_id TEXT, instance_domain TEXT, embedding BLOB, embedding_dim INTEGER, model_name TEXT, PRIMARY KEY (video_id, instance_domain))")
    db.execute("CREATE TABLE channels (channel_id TEXT, instance_domain TEXT, display_name TEXT, avatar_url TEXT)")
    _add(db, A1)
    _add(db, B1, error_count=None)
    _add(db, E1, error_count=5)
    db.commit()
    db.close()
    return path


def _handle(db_path: Path, *cases: tuple[str, dict, int | None]) -> list[dict]:
    assert ENGINE_PY.exists(), f"Engine interpreter missing at {ENGINE_PY}; run `pixi install` in engine/"
    run = subprocess.run([str(ENGINE_PY), "-c", CHILD, str(SERVER_DIR), str(API_DIR), str(db_path), json.dumps(cases)], cwd=API_DIR, capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stderr[-2000:]  # control: the Engine's interpreter imported the handlers and ran every case
    return json.loads(run.stdout)


def test_a_mixed_body_takes_the_lock_once_and_gives_each_video_once_in_first_match_order(db_path):
    report, id_first = _handle(db_path, ("metadata", {"entries": [_uuid("u-b"), _id("a1"), _id("b1"), _uuid("u-a"), _uuid("u-x")]}, THRESHOLD), ("metadata", {"entries": [_id("a1"), _uuid("u-x"), _uuid("u-b"), _id("b1")]}, THRESHOLD))
    assert report["responses"] == _rows(B1, A1)  # C2: b1 at its uuid entry, a1 at its id entry, neither repeated by its other-form entry, u-x omitted; the id-only lookup gives [a1, b1]
    assert id_first["responses"] == _rows(A1, B1)  # C2: emitting every uuid row before the id rows gives [b1, a1] here
    assert report["enters"] == 1  # C1: one acquisition for both forms, not one per form or per entry
    assert set(report["statements_locked"]) == {True}  # C1: at least one statement, and every one ran inside that hold
    assert report["held_after"] is False
    assert (id_first["enters"], set(id_first["statements_locked"])) == (1, {True})  # C1


def test_an_id_only_body_takes_the_lock_once_and_gives_its_rows_in_entry_order(db_path):
    (report,) = _handle(db_path, ("metadata", {"entries": [_id("a1"), _id("b1"), _id("a1")]}, THRESHOLD))
    assert report["responses"] == _rows(A1, B1)  # C2
    assert report["enters"] == 1  # C1


def test_a_valid_video_id_wins_over_a_video_uuid_and_a_blank_one_falls_back_to_it(db_path):
    both, padded, blank_id = _handle(
        db_path,
        ("metadata", {"entries": [{"video_id": "a1", "video_uuid": "u-b", "instance_domain": HOST}]}, THRESHOLD),
        ("metadata", {"entries": [{"video_id": " a1 ", "video_uuid": "   ", "instance_domain": f" {HOST} "}]}, THRESHOLD),
        ("metadata", {"entries": [{"video_id": "   ", "video_uuid": " u-b ", "instance_domain": HOST}]}, THRESHOLD),
    )
    assert both["responses"] == _rows(A1)  # C2: the id's video, not u-b's and not both
    assert padded["responses"] == _rows(A1)  # C2: values are stripped
    assert blank_id["responses"] == _rows(B1)  # C2: a blank id is no id, so the uuid decides


def test_repeats_within_and_across_forms_give_one_row_per_video(db_path):
    (report,) = _handle(db_path, ("metadata", {"entries": [_uuid("u-a"), _uuid("u-a"), _id("b1"), _id("b1"), _uuid("u-b"), _id("a1")]}, THRESHOLD))
    assert report["responses"] == _rows(A1, B1)  # C2


def test_an_errored_video_s_uuid_entry_is_omitted_only_under_the_threshold(db_path):
    under, unset = _handle(db_path, ("metadata", {"entries": [_uuid("u-e"), _uuid("u-a")]}, THRESHOLD), ("metadata", {"entries": [_uuid("u-e"), _uuid("u-a")]}, None))
    assert unset["responses"] == _rows(E1, A1)  # control: u-e resolves when no threshold is set
    assert under["responses"] == _rows(A1)  # C2: e1 (error_count 5) is not a match at threshold 3


def test_a_body_with_no_entries_list_or_no_valid_entry_is_answered_without_the_lock(db_path):
    malformed = ["x", {"video_id": "a1", "instance_domain": "  "}, {"instance_domain": HOST}, {"video_uuid": "u-a"}, {"video_id": "a1", "instance_domain": 7}]
    not_a_list, no_entries, all_malformed = _handle(db_path, ("metadata", {"entries": "x"}, THRESHOLD), ("metadata", {}, THRESHOLD), ("metadata", {"entries": malformed}, THRESHOLD))
    assert (not_a_list["responses"], not_a_list["enters"]) == (MISSING_ENTRIES, 0)
    assert (no_entries["responses"], no_entries["enters"]) == (MISSING_ENTRIES, 0)
    assert (all_malformed["responses"], all_malformed["enters"]) == (NO_ROWS, 0)


def test_centroids_looks_up_only_the_id_entries(db_path):
    uuid_only, mixed = _handle(db_path, ("centroids", {"entries": [_uuid("u-a")]}, THRESHOLD), ("centroids", {"entries": [_uuid("u-b"), _id("a1")]}, THRESHOLD))
    assert uuid_only["embedding_entries"] == [[]]
    assert uuid_only["responses"] == [[200, {"ok": True, "space": None, "centroids": []}]]
    assert mixed["embedding_entries"] == [[_id("a1")]]
    assert mixed["responses"] == [[200, {"ok": True, "space": None, "centroids": [[0.707107, 0.707107, 0.0]]}]]  # a1's (1, 1, 0) at unit length alone (observed); b1's (2, 1, 0) would add a second centroid

```


Gate: satisfied

## 2026-09-27 - Step 7 - Phase 2 (Engine metadata endpoint accepts both entry forms) - red (audit round 1)

`tests/tmp/test_14_batch_like_resolution_phase2.py` exited 1.

```
  tests/tmp/test_14_batch_like_resolution_phase2.py  4 failed, 3 passed                     0.0s
  -------------------------------------------------
  total                                              4 failed, 3 passed                     0.9s wall, 1 lane

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

## 2026-09-27 - Step 7 - Phase 2 (Engine metadata endpoint accepts both entry forms) - audit (round 1)

- AUDIT: devsecops-test-shape-auditor - PASS
- AUDIT: devsecops-test-claim-auditor - PASS
- OUTSTANDING: 1 UNCARRIED clause(s) - N4

### devsecops-test-shape-auditor

```
SHAPE AUDIT — VERDICT: PASS

CRITICAL
none

RECOMMENDATIONS
1. No rule in shape.md covers this — tests/tmp/test_14_batch_like_resolution_phase2.py:167-168
   assert report["responses"] == _rows(A1, B1)  # C2
   assert report["enters"] == 1  # C1
   These lines carry the C2 and C1 tags, but they hold against the current handler.
   It parses only id-form entries, deduplicates them, and takes the lock once for
   them. So this test is a regression control, not the gate for either clause. Both
   clauses are gated at lines 157-162. The same is true of
   test_a_body_with_no_entries_list_or_no_valid_entry_is_answered_without_the_lock
   (lines 198-200), which is not tagged.

PREDICTED FAILURE
Fails at line 157 on the tuple assertion. The current `_parse_entries` drops every
uuid-form entry, so the first mixed body resolves only ids a1 and b1, in entry order.
The observed value is (1, ["a1", "b1"]); the expected value is (1, ["b1", "a1"]).

NOT ASSESSED
1. `code_under_test` listed tests/tmp/test_metadata_uuid_entries.py, which does not
   resolve (there is no such file under tests/tmp/). The audit covered
   engine/server/api/handlers/internal_client_reads.py and
   engine/server/data/metadata.py, found by Grep.
2. `fixtures_path` was not supplied. The only external symbol, ENGINE_PY, is defined at
   tests/active/conftest.py:30. The rest of that conftest was not read, and the test
   uses no fixture from it.
```

### devsecops-test-claim-auditor

CLAIM AUDIT — VERDICT: PASS

CLAUSE MAP  (32 clauses: 3 must_prove, 19 docstring, 10 name)
| id | source | clause | assertion | excludes | status |
|---|---|---|---|---|---|
| C1 | must_prove | a mixed id/uuid body acquires `db_lock` exactly once | :157, :162 | one lookup per form under separate holds (enters 2), or no lock at all (enters 0); the counter sees both `with` and `acquire()` (:53-61) | CARRIED |
| C2a | must_prove | each matched video appears once in `rows` | :158, :185 | b1 repeated by its uuid entry and its id entry; an unmatched `u-x` coming back as a placeholder row; `count` disagreeing with the rows | CARRIED |
| C2b | must_prove | in the order of its first matching entry | :158, :159 | all uuid rows before the id rows (:159 gives [b1, a1]); all id rows first, or SQL/table order (:158 gives [a1, b1]) | CARRIED |
| D1 | docstring | "answers a body of id-form and uuid-form entries under one `db_lock` hold" | :157, :160, :162 | two holds; any statement run outside the hold | CARRIED |
| D2 | docstring | "each matched video once, at its first matching entry" | :158, :159 | a duplicate row; order by form or by table | CARRIED |
| D3 | docstring | "`/internal/dislike/centroids` still looks up only id-form entries" | :205, :207 | uuid entries passed to the embedding lookup | CARRIED |
| D4 | docstring | "`[uuid u-b, id a1, id b1, uuid u-a, uuid u-x]` gives exactly `[b1, a1]` with `count == 2`" | :158 | any other rows, order or count (`_rows` sets count) | CARRIED |
| D5 | docstring | "`[id a1, uuid u-x, uuid u-b, id b1]` gives `[a1, b1]`" | :159 | uuid rows placed first | CARRIED |
| D6 | docstring | "each with one lock acquisition and every SQL statement run while that lock is held" | :157, :160, :162 | a second acquisition; a statement run with the lock free; no statement at all (`== {True}` needs at least one) | CARRIED |
| D7 | docstring | "id-only body `[a1, b1, a1]` gives `[a1, b1]` with one acquisition" | :167, :168 | a1 repeated; more than one acquisition | CARRIED |
| D8 | docstring | "valid `video_id` and another video's `video_uuid` gives the id's video" | :178 | the uuid winning, or both videos coming back | CARRIED |
| D9 | docstring | "values are stripped" | :179, :180 | the padded id, the padded domain (:179) or the padded uuid (:180) matching nothing | CARRIED |
| D10 | docstring | "a blank `video_id` beside a valid `video_uuid` gives the uuid's video" | :180 | a whitespace id counted as present and dropping the entry | CARRIED |
| D11 | docstring | "Repeats within a form ... give one row" | :185, :167 | u-a twice or b1 twice appearing twice | CARRIED |
| D12 | docstring | "a video reached by both forms gives one row" | :185, :158 | a1 via u-a and a1 appearing twice | CARRIED |
| D13 | docstring | "uuid entry of a video at `error_count` 5 is omitted at threshold 3" | :192 | the uuid path ignoring the threshold (u-e is not the last pair, so a threshold that binds only to the last pair also fails) | CARRIED |
| D14 | docstring | "returned in its first-match place with no threshold" | :191, :190 | e1 dropped, or placed after a1 | CARRIED |
| D15 | docstring | "`{"entries": "x"}` gives 400 `Missing entries` without taking the lock" | :198 | 200/other error; lock taken | CARRIED |
| D16 | docstring | "`{}` gives 400 `Missing entries` without taking the lock" | :199 | same | CARRIED |
| D17 | docstring | "a body of only malformed items gives 200 with no rows, without taking the lock" | :200 | a malformed item accepted (e.g. a uuid with no domain); the lock taken for an empty lookup | CARRIED |
| D18 | docstring | "uuid-only body hands the embedding lookup `[]` and gives no centroids" | :205, :206 | the uuid entry passed through; the lookup skipped (`[]` ≠ `[[]]`); a centroid for a1 | CARRIED |
| D19 | docstring | "mixed body hands it only the id entry and gives that video's unit vector" | :207, :208 | u-b passed to the lookup; a second centroid from b1's vector | CARRIED |
| D20 | docstring | "embedding lookup is spied on, not replaced, and the lock counts every acquisition" | :53-61, :90 | a hidden `acquire()` not being counted; a stubbed lookup hiding real results (`wraps=`) | CARRIED |
| N1 | name | test 1: "a mixed body takes the lock once" | :157, :162 | two holds | CARRIED |
| N2 | name | test 1: "gives each video once in first match order" | :158, :159 | duplicates; order by form | CARRIED |
| N3 | name | test 2: "an id-only body takes the lock once" | :168 | more than one acquisition | CARRIED |
| N4 | name | test 2: "gives its rows in entry order" | :167 | only a reversed order: entry order a1, b1 is also insertion, rowid and alphabetical order, so a result in table order passes | UNCARRIED |
| N5 | name | test 3: "a valid video_id wins over a video_uuid" | :178 | the uuid winning | CARRIED |
| N6 | name | test 3: "a blank one falls back to it" | :180 | a blank id dropping the entry | CARRIED |
| N7 | name | test 4: "repeats within and across forms give one row per video" | :185 | a repeated row | CARRIED |
| N8 | name | test 5: "errored video's uuid entry is omitted only under the threshold" | :192, :191 | the threshold ignored; the video omitted even with no threshold | CARRIED |
| N9 | name | test 6: "no entries list or no valid entry is answered without the lock" | :198-200 | the lock taken on a rejected or empty body | CARRIED |
| N10 | name | test 7: "centroids looks up only the id entries" | :205, :207 | uuid entries passed to the lookup | CARRIED |

CRITICAL
none

RECOMMENDATIONS
1. whole-claim / name-as-sentence (rules/testing.md) — tests/tmp/test_14_batch_like_resolution_phase2.py:167
   `assert report["responses"] == _rows(A1, B1)  # C2`
   N4 is UNCARRIED. The name says "in entry order", but a1, b1 is also the fixture's insertion, rowid and alphabetical order. A result in table order passes this assertion. An id-only body in a non-table order, such as `[b1, a1, b1]` → `[b1, a1]`, would carry it. C2b is still carried for mixed bodies at :158, so this does not block.
2. bounds (rules/testing.md) — tests/tmp/test_14_batch_like_resolution_phase2.py:156
   The lock-once claim (C1) is only exercised with bodies of 4–5 entries. `fetch_metadata_by_ids` / `fetch_metadata_by_uuids` split entries into chunks of 450. Nothing tests a mixed body over one chunk, where several SQL statements must share one hold. An explicit empty list `{"entries": []}` is also untested (:195-200 test the all-malformed body, not the empty one). No rule makes either one required at this surface.

OBSERVATIONS
none

NOT ASSESSED
1. `code_under_test` lists tests/tmp/test_metadata_uuid_entries.py, and that file does not exist. Nothing from it was assessed.
2. I did not read `fetch_embeddings_by_ids` (engine/server/data/embeddings.py). D18 and D19 were judged from the spy at :90 and the assertions at :205-208.
3. `fixtures_path` was not supplied. I checked `ENGINE_PY` in tests/active/conftest.py:30 with a grep, and `db_path` is defined in the test itself (:132). I did not read the rest of that conftest.

## 2026-09-27 - Step 7 - Phase 2 (Engine metadata endpoint accepts both entry forms) - self-check (audit round 2, send-back 0)

`tests/tmp/test_14_batch_like_resolution_phase2.py`, surface `checkpoint`. Collection exit 0.

- C1 - tests/tmp/test_14_batch_like_resolution_phase2.py:157 — (enters, row video_ids) for the mixed body [uuid u-b, id a1, id b1, uuid u-a, uuid u-x]; :160 — set(statements_locked) == {True}; :162 — (enters, set(statements_locked)) for the id-first mixed body - expected: (1, ["b1", "a1"]) at :157; {True} at :160; (1, {True}) at :162 - excludes: Separate lookups per form, each under its own `with db_lock` (or `acquire()`, which the counter also sees), read enters 2, so :157 gets (2, ["b1", "a1"]) and :162 gets (2, {True}). One acquisition that wraps only the id lookup runs the uuid SELECT with the lock free, so :160 gets {False, True}. The unchanged id-only handler reads (1, ["a1", "b1"]) at :157.
- C2 - tests/tmp/test_14_batch_like_resolution_phase2.py:158 — mixed body [uuid u-b, id a1, id b1, uuid u-a, uuid u-x] responses; :159 — id-first mixed body [id a1, uuid u-x, uuid u-b, id b1] responses; :185 — [uuid u-a, uuid u-a, id b1, id b1, uuid u-b, id a1] responses - expected: _rows(B1, A1) at :158 (count 2, full rows, u-x omitted); _rows(A1, B1) at :159; _rows(A1, B1) at :185 - excludes: Emitting all id rows first, or in table order, gives [a1, b1] at :158. Emitting all uuid rows first gives [b1, a1] at :159. Appending each form's matches without deduplicating gives [b1, a1, b1, a1] or similar, count 4, at :158 and repeated rows at :185. A placeholder row for u-x makes the count 3 at :158.

<exemptions>
none
</exemptions>

<findings_addressed>
No CRITICAL from either auditor. Claim audit RECOMMENDATION 1 (N4, entry order is also table order at :167): taken. The id-only body is now [b1, a1, b1] → [b1, a1], so table order no longer passes. Claim audit RECOMMENDATION 2 (a body over 450 entries; an explicit empty list): not taken. The auditor says no rule requires it at this surface, and the ledger does not list it. Shape audit RECOMMENDATION 1 (test 2 and the malformed-body test are regression controls, not gates): no change. I confirmed by running it that test 2 is still a pin the unchanged handler meets. The comment at :167 now says what it excludes, and C1/C2 are still gated at :157-162.
</findings_addressed>

<items>
<item id="N4">
<disposition>fixed</disposition>
<what>Test 2's body is now `[id b1, id a1, id b1]` and :167 asserts `report["responses"] == _rows(B1, A1)`. Entry order b1, a1 is the reverse of the fixture's insertion, rowid and alphabetical order, which are all a1, b1. So an implementation that returns rows in table or SQL order reads [a1, b1] and fails. One that repeats b1 reads [b1, a1, b1] and also fails. The module docstring's matching sentence (D7) now says "`[b1, a1, b1]` gives `[b1, a1]`", so it describes what the test asserts. D7 is still carried by :167 and :168. I checked this with a probe that ran the real `_handle` over this body against the unchanged handler. It printed rows ['b1', 'a1'], enters 1, statements_locked [True], count 2. Then I ran the edited test through a re-exporting probe and it passed. So this test is still a regression pin that the current handler meets, as the shape auditor described. It is not the red gate. The gate is still :157-162.</what>
</item>
</items>

<rows>
<row clause="C1">
<assertion>tests/tmp/test_14_batch_like_resolution_phase2.py:157 — (enters, row video_ids) for the mixed body [uuid u-b, id a1, id b1, uuid u-a, uuid u-x]; :160 — set(statements_locked) == {True}; :162 — (enters, set(statements_locked)) for the id-first mixed body</assertion>
<expected>(1, ["b1", "a1"]) at :157; {True} at :160; (1, {True}) at :162</expected>
<wrong_implementation>Separate lookups per form, each under its own `with db_lock` (or `acquire()`, which the counter also sees), read enters 2, so :157 gets (2, ["b1", "a1"]) and :162 gets (2, {True}). One acquisition that wraps only the id lookup runs the uuid SELECT with the lock free, so :160 gets {False, True}. The unchanged id-only handler reads (1, ["a1", "b1"]) at :157.</wrong_implementation>
</row>
<row clause="C2">
<assertion>tests/tmp/test_14_batch_like_resolution_phase2.py:158 — mixed body [uuid u-b, id a1, id b1, uuid u-a, uuid u-x] responses; :159 — id-first mixed body [id a1, uuid u-x, uuid u-b, id b1] responses; :185 — [uuid u-a, uuid u-a, id b1, id b1, uuid u-b, id a1] responses</assertion>
<expected>_rows(B1, A1) at :158 (count 2, full rows, u-x omitted); _rows(A1, B1) at :159; _rows(A1, B1) at :185</expected>
<wrong_implementation>Emitting all id rows first, or in table order, gives [a1, b1] at :158. Emitting all uuid rows first gives [b1, a1] at :159. Appending each form's matches without deduplicating gives [b1, a1, b1, a1] or similar, count 4, at :158 and repeated rows at :185. A placeholder row for u-x makes the count 3 at :158.</wrong_implementation>
</row>
</rows>

<answers>
1. No. The only absence checks are u-x omitted (:158), e1 omitted under the threshold (:192) and enters 0 (:198-200). Each has a positive control on the same run or fixture: b1 and a1 are present at :158, e1 comes back with no threshold at :190-191, and enters 1 for the valid bodies at :157 and :168. Take the handler away and every responses assertion fails.
2. No. Expected rows are built by `_row` from the fixture's input values, not by running production's SELECT or join. Deleting the reordering loop in handle_internal_videos_metadata, which walks the entries and emits each key once, turns :158 and :167 red. :167 now uses a non-table order, so table order no longer passes it.
3. No. Order is checked on three bodies whose first-match orders differ: [b1, a1] at :158, [a1, b1] at :159, and id-only [b1, a1] at :167. The lock count is checked on four bodies, and the threshold is checked both set and unset.
4. No. The only doubles are the request stand-in (stdlib BaseHTTPRequestHandler) and the CountingLock (threading.Lock). fetch_embeddings_by_ids, which this project owns, is spied with wraps=, not replaced.
5. Yes, it collects. I ran the edited test 2 through the re-exporting probe tests/tmp/probe_14_n4.py and it passed. Seven tests, same imports; only test 2's body, its expected value and one docstring sentence changed.
6. Yes, observed. Before I wrote the expectation, a probe ran the real `_handle` on [b1, a1, b1] against the unchanged handler and printed rows ['b1', 'a1'], enters 1, statements_locked [True], count 2.
7. Yes. The edit only touches test 2, which is a pin that passes now (observed). The red tests are unchanged: :157, :180, :185 and :191 still fail because the uuid form has not been built. Housekeeping: I have no delete tool, so tests/tmp/probe_14_n4.py has been emptied but still needs removing, along with the earlier probes (probe_14_phase2.py, probe_14_phase1.py, probe_phase1_metadata.py, probe_phase1_against_impls.py).
</answers>

Gate: satisfied

## 2026-09-27 - Step 7 - Phase 2 (Engine metadata endpoint accepts both entry forms) - red (audit round 2)

`tests/tmp/test_14_batch_like_resolution_phase2.py` exited 1.

```
  tests/tmp/test_14_batch_like_resolution_phase2.py  4 failed, 3 passed                     0.0s
  -------------------------------------------------
  total                                              4 failed, 3 passed                     1.0s wall, 1 lane

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

## 2026-09-27 - Step 7 - Phase 2 (Engine metadata endpoint accepts both entry forms) - audit (round 2)

- AUDIT: devsecops-test-shape-auditor - PASS
- AUDIT: devsecops-test-claim-auditor - PASS
- OUTSTANDING: nothing

### devsecops-test-shape-auditor

SHAPE AUDIT — VERDICT: PASS

CRITICAL
none

RECOMMENDATIONS
none

PREDICTED FAILURE
test_a_mixed_body_takes_the_lock_once_and_gives_each_video_once_in_first_match_order should fail at tests/tmp/test_14_batch_like_resolution_phase2.py:157. The tuple assertion should get `(1, ["a1", "b1"])` where it expects `(1, ["b1", "a1"])`. This is because `_parse_entries` (internal_client_reads.py:35) skips every entry that has no `video_id`, so the `u-b` entry never resolves and the rows follow the id-form entries only.

Other tests in the file, against the code as it stands:
- :185 should fail with `[b1, a1]` returned where `_rows(A1, B1)` is expected.
- :180 should fail with `NO_ROWS` returned where `_rows(B1)` is expected.
- :191 should fail with `NO_ROWS` returned where `_rows(E1, A1)` is expected.
- :167–168, :198–200 and :205–208 should stay green. They check behaviour that already holds and are meant to keep holding.

NOT ASSESSED
1. `code_under_test` listed tests/tmp/test_metadata_uuid_entries.py, which does not exist. Nothing the test depends on was checked against it.
2. No `fixtures_path` was supplied. `ENGINE_PY` was traced by Grep to tests/active/conftest.py:30 and nothing more in that conftest was read. The test defines its only fixture, `db_path`, itself at :132.
3. `code_under_test` marks engine/server/api/handlers/internal_client_reads.py as EDITED, but the file as read has no uuid-form handling in `handle_internal_videos_metadata` (:95–126). The predicted failure is based on the file as read.

### devsecops-test-claim-auditor

CLAIM AUDIT — VERDICT: PASS

CLAUSE MAP  (33 clauses: 3 must_prove, 20 docstring, 10 name)
| id | source | clause | assertion | excludes | status |
|---|---|---|---|---|---|
| C1 | must_prove | a mixed id/uuid body acquires `db_lock` exactly once | :157, :162 | one lookup per form under its own hold (enters 2), or no lock at all (enters 0). The counter sees both `with` and `acquire()` (:53-61). Both mixed orderings are checked | CARRIED |
| C2a | must_prove | each matched video appears once in `rows` | :158, :185 | b1 repeated by its uuid entry and its id entry; the unmatched `u-x` coming back as a placeholder row; `count` disagreeing with the rows | CARRIED |
| C2b | must_prove | in the order of its first matching entry | :158, :159 | all uuid rows before the id rows (:159 needs [a1, b1]); all id rows first, or SQL/table order (:158 needs [b1, a1]) | CARRIED |
| D1 | docstring | "answers a body of id-form and uuid-form entries under one `db_lock` hold" | :157, :160, :162 | two holds; any statement run outside the hold | CARRIED |
| D2 | docstring | "each matched video once, at its first matching entry" | :158, :159 | a duplicate row; rows ordered by form or by table | CARRIED |
| D3 | docstring | "`/internal/dislikes/centroids` still looks up only id-form entries" | :205, :207 | uuid entries passed to the embedding lookup | CARRIED |
| D4 | docstring | "`[uuid u-b, id a1, id b1, uuid u-a, uuid u-x]` gives exactly `[b1, a1]` with `count == 2`" | :158 | any other rows, order or count (`_rows` sets count, :129) | CARRIED |
| D5 | docstring | "`[id a1, uuid u-x, uuid u-b, id b1]` gives `[a1, b1]`" | :159 | uuid rows placed first | CARRIED |
| D6 | docstring | "each with one lock acquisition and every SQL statement run while that lock is held" | :157, :160, :162 | a second acquisition; a statement run with the lock free; no statement at all (`== {True}` needs at least one) | CARRIED |
| D7 | docstring | "id-only body `[b1, a1, b1]` gives `[b1, a1]` with one acquisition" | :167, :168 | b1 repeated; rows in table/rowid/alphabetical order (would give [a1, b1]); more than one acquisition | CARRIED |
| D8 | docstring | "valid `video_id` and another video's `video_uuid` gives the id's video" | :178 | the uuid winning, or both videos coming back | CARRIED |
| D9 | docstring | "values are stripped" | :179, :180 | the padded id or padded domain (:179), or the padded uuid (:180), matching nothing | CARRIED |
| D10 | docstring | "a blank `video_id` beside a valid `video_uuid` gives the uuid's video" | :180 | a whitespace id counted as present and dropping the entry | CARRIED |
| D11 | docstring | "Repeats within a form ... give one row" | :185, :167 | u-a twice or b1 twice appearing twice | CARRIED |
| D12 | docstring | "a video reached by both forms gives one row" | :185, :158 | a1 reached by u-a and by id appearing twice | CARRIED |
| D13 | docstring | "uuid entry of a video at `error_count` 5 is omitted at threshold 3" | :192 | the uuid path ignoring the threshold (u-e is not the last pair) | CARRIED |
| D14 | docstring | "returned in its first-match place with no threshold" | :191, :190 | e1 dropped, or placed after a1 | CARRIED |
| D15 | docstring | "`{"entries": "x"}` gives 400 `Missing entries` without taking the lock" | :198 | a 200 or a different error; the lock taken | CARRIED |
| D16 | docstring | "`{}` gives 400 `Missing entries` without taking the lock" | :199 | same as D15 | CARRIED |
| D17 | docstring | "a body of only malformed items gives 200 with no rows, without taking the lock" | :200 | a malformed item accepted (for example a uuid with no domain, or an int domain); the lock taken for an empty lookup | CARRIED |
| D18 | docstring | "uuid-only body hands the embedding lookup `[]` and gives no centroids" | :205, :206 | the uuid entry passed through; the lookup skipped (`[]` ≠ `[[]]`); a centroid for a1 | CARRIED |
| D19 | docstring | "mixed body hands it only the id entry and gives that video's unit vector" | :207, :208 | u-b passed to the lookup; a second centroid from b1's vector | CARRIED |
| D20 | docstring | "embedding lookup is spied on, not replaced, and the lock counts every acquisition" | :53-61, :90 | a hidden `acquire()` going uncounted; a stubbed lookup hiding real results (`wraps=`) | CARRIED |
| N1 | name | test 1: "a mixed body takes the lock once" | :157, :162 | two holds | CARRIED |
| N2 | name | test 1: "gives each video once in first match order" | :158, :159 | duplicates; rows ordered by form | CARRIED |
| N3 | name | test 2: "an id-only body takes the lock once" | :168 | more than one acquisition | CARRIED |
| N4 | name | test 2: "gives its rows in entry order" | :167 | table order. The body is now `[b1, a1, b1]` against a fixture inserted a1, b1, e1, so insertion, rowid and alphabetical order all give [a1, b1] and fail | CARRIED |
| N5 | name | test 3: "a valid video_id wins over a video_uuid" | :178 | the uuid winning | CARRIED |
| N6 | name | test 3: "a blank one falls back to it" | :180 | a blank id dropping the entry | CARRIED |
| N7 | name | test 4: "repeats within and across forms give one row per video" | :185 | a repeated row | CARRIED |
| N8 | name | test 5: "errored video's uuid entry is omitted only under the threshold" | :192, :191 | the threshold ignored; the video omitted even with no threshold | CARRIED |
| N9 | name | test 6: "no entries list or no valid entry is answered without the lock" | :198-200 | the lock taken on a rejected or empty body | CARRIED |
| N10 | name | test 7: "centroids looks up only the id entries" | :205, :207 | uuid entries passed to the lookup | CARRIED |

CRITICAL
none

RECOMMENDATIONS
none

OBSERVATIONS
1. whole-claim (rules/testing.md) — tests/tmp/test_14_batch_like_resolution_phase2.py:3, :166
   N4 is now carried because the assertion changed, not because the prose was narrowed. The id-only body is now `[_id("b1"), _id("a1"), _id("b1")]` (:166), and :167 expects `_rows(B1, A1)`, which a result in table order fails. The docstring's D7 sentence was rewritten to match (`[b1, a1, b1]` gives `[b1, a1]`, where round one had `[a1, b1, a1]` gives `[a1, b1]`). The clause is the same, restated for the new input, and it is carried.
2. tests/tmp/test_14_batch_like_resolution_phase2.py:1
   The D3 route is now spelled `/internal/dislikes/centroids`, where the ledger has `/internal/dislike/centroids`. The test calls the handler function directly (:80), so the route string is prose only. Neither spelling is checked against a route table here.

NOT ASSESSED
1. `code_under_test` lists tests/tmp/test_metadata_uuid_entries.py, which does not resolve (FileNotFoundError). No clause here depends on it.
2. `data.metadata.fetch_metadata_by_ids` and `data.embeddings.fetch_embeddings_by_ids` are not in `code_under_test` and were not read. The threshold and ordering exclusions were judged from the test's fixture data (:140-142) and its expected rows, not from the lookup code.
3. `conftest.ENGINE_PY` (tests/active/conftest.py, imported at :26) was not read. The test uses it only as the path to the Engine's interpreter, not as a fixture that sets up state.

## 2026-09-27 - Step 7 - Phase 2 (Engine metadata endpoint accepts both entry forms) - checkpoint outcome (run 1)

`tests/tmp/test_14_batch_like_resolution_phase2.py` exited 0 after the phase landed.

<changes>
### `engine/server/api/handlers/internal_client_reads.py`
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
</changes>

<inner_tests>
none
</inner_tests>

<unanticipated>
none
</unanticipated>

<awaiting_operator>
none
</awaiting_operator>

```
  tests/tmp/test_14_batch_like_resolution_phase2.py  7 passed                               0.0s
  -------------------------------------------------
  total                                              7 passed                               0.9s wall, 1 lane

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

## 2026-09-27 - Step 7 - Phase 3 (Client resolves likes in one Engine call) - must_prove

Quoted from the phase Intent, written at Step 6 before the checkpoint was drafted.

Intent:
`_handle_user_profile_likes_from_client` and `_handle_likes_import` in `client/backend/server.py` each resolve a request's browser likes with a single `fetch_metadata_for_entries` call, and import records a like from each returned row. `resolve_videos_by_uuid_host` no longer exists.

- C1 - A likes-page or likes-import request causes exactly one Engine HTTP call, to `/internal/videos/metadata`.
- C2 - Likes import records a like for each returned row whose video the profile has not disliked.

must_prove:
- C1 - A likes-page or likes-import request causes exactly one Engine HTTP call, to `/internal/videos/metadata`.
- C2 - Likes import records a like for each returned row whose video the profile has not disliked.

## 2026-09-27 - Step 7 - Phase 3 (Client resolves likes in one Engine call) - self-check (audit round 1, send-back 0)

`tests/tmp/test_14_batch_like_resolution_phase3.py`, surface `checkpoint`. Collection exit 0.

- C1 - tests/tmp/test_14_batch_like_resolution_phase3.py:109 — after one likes-page POST of [u-c, u-a, u-c (repeat), u-x (unknown), u-b], the stand-in Engine's full record of every request (POST and GET, any path) equals exactly one entry: (`/internal/videos/metadata`, {"entries": [the five submitted {video_uuid, instance_domain} pairs, in order]}) - expected: [("/internal/videos/metadata", {"entries": [u-c, u-a, u-c, u-x, u-b pairs]})], one element. Observed: the probe run, which emulates the one-call Client, printed `PAGE correct: PASS`. - excludes: The current per-like resolve loop. Observed in this turn's run: `At index 0 diff: ('/internal/videos/resolve', {'host': 'h.example', 'uuid': 'u-c'}) != ('/internal/videos/metadata', ...)`. A fix that keeps a resolve call before the metadata call, or sends two metadata calls, also gives a record longer than one and fails the same equality.
- C1 - tests/tmp/test_14_batch_like_resolution_phase3.py:117 — after the likes-page bodies `{}`, `{"likes": []}` and a list of only malformed likes, the Engine record is `[]`. It is armed by the control at :120 (`assert received`): a well-formed like sent next on the same Engine is recorded. - expected: [] at :117, then a non-empty record at :120. Observed: in this turn's run both :117 and the :120 control passed, and the test first failed at :121. - excludes: A Client that calls the Engine even with nothing to resolve, for example one that drops the empty-parse early return and posts `{"entries": []}` to metadata. The record then holds a request, not `[]`. A stand-in that recorded nothing would pass :117 vacuously, which is the case the :120 control excludes.
- C1 - tests/tmp/test_14_batch_like_resolution_phase3.py:121 — the single well-formed like sent after the empty bodies leaves exactly `[("/internal/videos/metadata", {"entries": [u-a pair]})]` in the record - expected: [("/internal/videos/metadata", {"entries": [{"video_uuid": "u-a", "instance_domain": "h.example"}]})]. Observed: the probe printed `EMPTY correct: PASS` for the emulated one-call Client. - excludes: The current resolve loop. Observed in this turn's run, failing at :121: `At index 0 diff: ('/internal/videos/resolve', {'host': 'h.example', 'uuid': 'u-a'}) != ('/internal/videos/metadata', ...)`. This is the one-like input, so a Client that resolves one like at a time and batches only larger bodies still fails.
- C1 - tests/tmp/test_14_batch_like_resolution_phase3.py:140 — an import of [u-a, u-b (disliked), u-x (unknown), u-c] leaves exactly one Engine request, to `/internal/videos/metadata`, carrying the four submitted pairs in order - expected: [("/internal/videos/metadata", {"entries": [u-a, u-b, u-x, u-c pairs]})]. Observed: the probe printed `IMPORT correct: PASS` for the emulated import, which makes one `fetch_metadata_for_entries` call. - excludes: An import still on `resolve_videos_by_uuid_host`, even after the likes page is fixed. Observed in this turn's run: `At index 0 diff: ('/internal/videos/resolve', {'host': 'h.example', 'uuid': 'u-a'}) != ('/internal/videos/metadata', ...)`. An import that resolves first and then asks metadata gives two or more records.
- C2 - tests/tmp/test_14_batch_like_resolution_phase3.py:141 — the import answers `(200, {"imported": 2})`. The Engine returns rows A, B, C, B is disliked and sits between the two clean rows, and u-x has no row. - expected: (200, {"imported": 2}). Observed: the probe printed `IMPORT correct: PASS` for the emulated import. - excludes: Probe run this turn, each reported as `FAIL at line 141`: an import that ignores dislikes (reads 3); one that keys the like on the entry's uuid instead of the row's video_id, so `is_disliked` misses id-b (reads 3); one that skips the first returned row (reads 1); one that skips the last returned row (reads 1).
- C2 - tests/tmp/test_14_batch_like_resolution_phase3.py:142 — `load_liked_keys(conn, profile_id) == {("id-a", HOST), ("id-c", HOST)}`: the returned rows' video_ids, which differ from their uuids, and not the disliked id-b - expected: {("id-a", "h.example"), ("id-c", "h.example")}. Observed: the emulated import passed this line (`IMPORT correct: PASS`). - excludes: An import that records B despite the dislike, which adds ("id-b", HOST). One that stores the browser entry's uuid as the video_id, which gives {("u-a", HOST), ("u-c", HOST)}. In the probe each of these mutants was caught first at :141, so this line is the stored-state view of the same exclusion.
- C2 - tests/tmp/test_14_batch_like_resolution_phase3.py:143 — the profile's `likes` table holds exactly {("id-a", "u-a", HOST), ("id-c", "u-c", HOST)}, so each like carries its Engine row's video_id, video_uuid and instance_domain - expected: {("id-a", "u-a", "h.example"), ("id-c", "u-c", "h.example")}. Observed: the emulated import passed this line. - excludes: An import that builds the recorded video without the row's `video_uuid`. The probe's "drops uuid" mutant printed `FAIL at line 143`, because the stored like had an empty uuid while :141 and :142 still passed.

<assertions>
tests/tmp/test_14_batch_like_resolution_phase3.py:109 - a likes-page body [u-c, u-a, u-c (repeat), u-x (unknown), u-b] leaves the stand-in Engine with exactly one recorded request, `(/internal/videos/metadata, {"entries": [...the five submitted {video_uuid, instance_domain} pairs, in order]})`. The stand-in records every POST and GET, so a resolve call or any second call fails this line. - C1
tests/tmp/test_14_batch_like_resolution_phase3.py:110 - that request is answered 200 with `likes == [C, A, B]`: the known rows in submitted order (not the table's [A, B, C]), with the repeat and u-x omitted. - C1
tests/tmp/test_14_batch_like_resolution_phase3.py:117 - after `{}`, `{"likes": []}` and a list of only malformed likes (non-dict, no host, no uuid, blank uuid, non-string host), the Engine has recorded nothing. - C1
tests/tmp/test_14_batch_like_resolution_phase3.py:119 - each of those three bodies is answered `(200, [])`. - C1
tests/tmp/test_14_batch_like_resolution_phase3.py:120 - a well-formed like sent next is recorded as the single request `(/internal/videos/metadata, {"entries": [u-a pair]})`. This is also the control that the stand-in records what reaches it. - C1
tests/tmp/test_14_batch_like_resolution_phase3.py:126 - control: minting via `POST /api/profile` answers 201. - setup
tests/tmp/test_14_batch_like_resolution_phase3.py:130 - control: `resolve_profile` on a second connection returns the minted `profile_id`. - setup
tests/tmp/test_14_batch_like_resolution_phase3.py:139 - importing [u-a, u-b (disliked via `write_dislike`, committed), u-x (unknown), u-c] leaves exactly one recorded Engine request, to `/internal/videos/metadata`, whose `entries` are the four submitted pairs in order. - C1
tests/tmp/test_14_batch_like_resolution_phase3.py:140 - the import answers `(200, {"imported": 2})`. - C2
tests/tmp/test_14_batch_like_resolution_phase3.py:141 - `load_liked_keys(conn, profile_id) == {("id-a", HOST), ("id-c", HOST)}`: the rows' video_ids (which differ from the uuids), and not the disliked id-b. - C2
tests/tmp/test_14_batch_like_resolution_phase3.py:142 - the profile's `likes` rows hold exactly `{("id-a", "u-a", HOST), ("id-c", "u-c", HOST)}`, so each like carries its row's video_uuid. - C2
Deviation from the agreed wording: the import posts two clean likes instead of one, so it expects `{"imported": 2}` and two liked keys, not `{"imported": 1}` and `{(clean_id, host)}`. With a single clean row, an implementation that skips the first or last returned row passed. With the disliked row between two clean ones, both off-by-one versions fail (observed). The request still counts as "an import of 3+ likes → one Engine request".
</assertions>

<probes>
1. `ValidateTests tests/tmp/probe_14_phase3.py -s`: a stand-in Engine plus a real ClientBackendServer on the current, unchanged code. Output (tests/last_test_output.txt):
PAGE (502, {'error': 'Engine metadata failed: Engine resolve returned invalid payload'})
PAGE_RECEIVED [('/internal/videos/resolve', {'host': 'h.example', 'uuid': 'u-a'})]
EMPTY (200, {'likes': [], 'updatedAt': ...}) []
MINT 201 ['key', 'profile_id']
RESOLVED True
IMPORT (502, {'error': 'Engine resolve failed: Engine resolve returned invalid payload'})
IMPORT_RECEIVED [('/internal/videos/resolve', {'host': 'h.example', 'uuid': 'u-a'})]
LIKED set()
So on the current code both routes call `/internal/videos/resolve` first, and the empty body makes no Engine call. It also showed that `from conftest import ...` works from tests/tmp once tests/active is on sys.path.
2. `ValidateTests tests/tmp/test_14_batch_like_resolution_phase3.py`: all 3 tests fail on the current code. Lines 109, 120 and 139 each fail with `At index 0 diff: ('/internal/videos/resolve', {'host': 'h.example', 'uuid': ...}) != ('/internal/videos/metadata', ...)`. Lines 117 and 119 pass, and so do the setup controls at 126 and 130.
3. `ValidateTests tests/tmp/probe_14_phase3.py -s` (rewritten): runs the checkpoint's three tests with `server.resolve_videos_by_uuid_host` monkeypatched to emulate a correct implementation (identity for the likes page, `fetch_metadata_for_entries` for import) and several wrong ones. Output:
PAGE correct: PASS
EMPTY correct: PASS
IMPORT correct: PASS
IMPORT ignores dislikes: FAIL at line 140
IMPORT keys on entry uuid: FAIL at line 140
IMPORT skips first row: FAIL at line 140
IMPORT skips last row: FAIL at line 140
IMPORT drops uuid: FAIL at line 142
Note: `tests/tmp/probe_14_phase3.py` is still on disk. I have no delete tool, so it needs removing, along with the earlier `probe_14_*` files from phases 1 and 2.
</probes>

<unassertable>
This file does not carry the checkpoint's cross-phase item: `tests/active/test_importing_browser_likes_marks_each_imported_video_liked_and_no_other` in `test_profiles.py` passing against the live Engine. The agreement puts it in its own `validate_tests.py` invocation, and running it would bank a mid-build fingerprint for tests/active, so I did not run it. The workflow has to run it as a separate gate after this phase. Every clause assigned to this file (C1, C2) is asserted.
</unassertable>

### `tests/tmp/test_14_batch_like_resolution_phase3.py` - 8231 characters, inlined in full

```
"""The Client resolves a request's browser likes with one Engine call, to `/internal/videos/metadata`, and an import records a like from each returned row whose video the profile has not disliked.

- A likes-page body of three likes, a repeat and an unknown one reaches the Engine as one `/internal/videos/metadata` request whose `entries` are the five submitted `{video_uuid, instance_domain}` pairs, in order, and is answered 200 with the three known rows in submitted order.
- An empty body, an empty `likes` list, and a list of only malformed likes are each answered 200 with `likes == []` and reach the Engine not at all; a well-formed like sent next does reach it.
- Importing two clean likes, one the profile dislikes and an unknown one reaches the Engine as one `/internal/videos/metadata` request carrying the four pairs, answers `{"imported": 2}`, and leaves the profile liking exactly the two clean videos, stored with the `video_id`, `video_uuid` and `instance_domain` of their Engine rows.

The Engine is a stdlib stand-in that records every request it gets and answers the metadata route as the Engine does: one row per known uuid entry, in entry order, each video once. The Client is a real `ClientBackendServer` over a `users.db` under `tmp_path`.
"""
from __future__ import annotations

import json
import sys
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "tests" / "active") not in sys.path:
    sys.path.insert(0, str(ROOT / "tests" / "active"))

from conftest import ClientBackend, RateLimiter, client_server, ensure_user_schema  # noqa: E402
from lib.dislikes import write_dislike  # noqa: E402
from lib.profiles import resolve_profile  # noqa: E402
from lib.users_store import load_liked_keys  # noqa: E402

HOST = "h.example"
METADATA = "/internal/videos/metadata"
# Engine rows; each video_id differs from its uuid, so a like stored from the browser's entry rather than the row is told apart.
A = {"video_id": "id-a", "video_uuid": "u-a", "instance_domain": HOST, "title": "A"}
B = {"video_id": "id-b", "video_uuid": "u-b", "instance_domain": HOST, "title": "B"}
C = {"video_id": "id-c", "video_uuid": "u-c", "instance_domain": HOST, "title": "C"}


def _like(uuid: str) -> dict:
    return {"uuid": uuid, "host": HOST}


def _entry(uuid: str) -> dict:
    return {"video_uuid": uuid, "instance_domain": HOST}


@contextmanager
def _serving(srv):
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}"
    finally:
        srv.shutdown()
        srv.server_close()


@contextmanager
def _client_backend(tmp_path, engine_base):
    """A Client backend on 127.0.0.1:0, as conftest's `client_backend` is built but with its Engine chosen here."""
    db_path = tmp_path / "users.db"
    conn = client_server.connect_db(db_path)
    ensure_user_schema(conn)
    try:
        with _serving(client_server.ClientBackendServer(("127.0.0.1", 0), client_server.ClientBackendHandler, conn, engine_base, "bridge", RateLimiter(1000, 60))) as base:
            yield ClientBackend(base, db_path)
    finally:
        conn.close()


@contextmanager
def _engine(videos):
    """A stand-in Engine that records `(path, json body)` for every request and answers the metadata route from `videos` by uuid and host, in entry order, each video once; any other route gets no rows."""
    table = {f"{v['video_uuid']}::{v['instance_domain']}": v for v in videos}
    received = []

    class EngineStub(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            body = json.loads(self.rfile.read(int(self.headers.get("content-length") or 0)) or b"null")
            received.append((self.path, body))
            rows = []
            if self.path == METADATA:
                for entry in body["entries"]:
                    row = table.get(f"{entry.get('video_uuid')}::{entry.get('instance_domain')}")
                    if row is not None and row not in rows:
                        rows.append(row)
            self._answer({"ok": True, "count": len(rows), "rows": rows})

        def do_GET(self):  # noqa: N802
            received.append((self.path, None))
            self._answer({"rows": []})

        def _answer(self, payload):
            data = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format, *args):
            pass

    with _serving(ThreadingHTTPServer(("127.0.0.1", 0), EngineStub)) as base:
        yield base, received


def test_a_likes_page_is_one_metadata_call_answered_with_the_known_rows_in_submitted_order(tmp_path):
    likes = [_like("u-c"), _like("u-a"), _like("u-c"), _like("u-x"), _like("u-b")]
    with _engine([A, B, C]) as (engine_base, received), _client_backend(tmp_path, engine_base) as client:
        status, body = client.request("POST", "/api/user-profile/likes", body={"likes": likes})
    # The per-like resolve loop records a `/internal/videos/resolve` request first (observed: it then answers 502 here).
    assert received == [(METADATA, {"entries": [_entry("u-c"), _entry("u-a"), _entry("u-c"), _entry("u-x"), _entry("u-b")]})]  # C1
    assert (status, body["likes"]) == (200, [C, A, B])  # C1: submitted order, not the table's [A, B, C]; the repeat and u-x omitted


def test_a_likes_page_with_no_well_formed_like_is_answered_empty_without_the_engine(tmp_path):
    malformed = ["x", {"uuid": "u-a"}, {"host": HOST}, {"uuid": "   ", "host": HOST}, {"uuid": "u-a", "host": 7}]
    with _engine([A]) as (engine_base, received), _client_backend(tmp_path, engine_base) as client:
        replies = [client.request("POST", "/api/user-profile/likes", body=body) for body in ({}, {"likes": []}, {"likes": malformed})]
        assert received == []  # C1
        client.request("POST", "/api/user-profile/likes", body={"likes": [_like("u-a")]})
    assert [(status, body["likes"]) for status, body in replies] == [(200, [])] * 3  # C1
    assert received == [(METADATA, {"entries": [_entry("u-a")]})]  # C1, and the control that this Engine records what reaches it


def test_an_import_is_one_metadata_call_and_likes_each_returned_video_the_profile_has_not_disliked(tmp_path):
    with _engine([A, B, C]) as (engine_base, received), _client_backend(tmp_path, engine_base) as client:
        status, minted = client.request("POST", "/api/profile")
        assert status == 201, minted
        conn = client_server.connect_db(client.db_path)
        try:
            profile_id = resolve_profile(conn, minted["key"])
            assert profile_id == minted["profile_id"]  # control: the second connection sees the minted profile
            with conn:
                write_dislike(conn, profile_id, B, None)
            # The disliked video sits between the clean ones, so skipping the first or the last returned row imports one, not two.
            status, body = client.request("POST", "/api/profile/likes/import", headers={"X-Profile-Key": minted["key"]}, body={"likes": [_like("u-a"), _like("u-b"), _like("u-x"), _like("u-c")]})
            liked = load_liked_keys(conn, profile_id)
            stored = {(row["video_id"], row["video_uuid"], row["instance_domain"]) for row in conn.execute("SELECT video_id, video_uuid, instance_domain FROM likes WHERE user_id = ?", (profile_id,))}
        finally:
            conn.close()
    assert received == [(METADATA, {"entries": [_entry("u-a"), _entry("u-b"), _entry("u-x"), _entry("u-c")]})]  # C1
    assert (status, body) == (200, {"imported": 2})  # C2: observed 3 when the dislike is ignored or a like is keyed on the uuid, 1 when the first or last row is skipped
    assert liked == {("id-a", HOST), ("id-c", HOST)}  # C2: the rows' video_ids, and not id-b, which the profile dislikes
    assert stored == {("id-a", "u-a", HOST), ("id-c", "u-c", HOST)}  # C2: each like carries its row's video_uuid

```


Gate: satisfied

## 2026-09-27 - Step 7 - Phase 3 (Client resolves likes in one Engine call) - red (audit round 1)

`tests/tmp/test_14_batch_like_resolution_phase3.py` exited 1.

```
  tests/tmp/test_14_batch_like_resolution_phase3.py  3 failed                               0.0s
  -------------------------------------------------
  total                                              3 failed                               2.2s wall, 1 lane

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

## 2026-09-27 - Step 7 - Phase 3 (Client resolves likes in one Engine call) - audit (round 1)

- AUDIT: devsecops-test-shape-auditor - PASS
- AUDIT: devsecops-test-claim-auditor - PASS
- OUTSTANDING: 1 UNCARRIED clause(s) - D11b

### devsecops-test-shape-auditor

```
SHAPE AUDIT — VERDICT: PASS

CRITICAL
none

RECOMMENDATIONS
none

PREDICTED FAILURE
Fails at tests/tmp/test_14_batch_like_resolution_phase3.py:109. The assertion `received == [(METADATA, {"entries": [...]})]`
finds `[("/internal/videos/resolve", {"host": "h.example", "uuid": "u-c"})]` instead.
`resolve_videos_by_uuid_host` still calls `/internal/videos/resolve` once per like, the stand-in's
reply has no `video`, and the Client answers 502 before any metadata call. The same wrong
request list fails line 121 of the empty-body test and line 140 of the import test.

NOT ASSESSED
1. `code_under_test` listed tests/tmp/test_client_like_batching.py (NEW), which does not resolve.
   It was not read, and the verdict does not depend on it.
2. `fixtures_path` was not supplied. The test imports `ClientBackend`, `RateLimiter`, `client_server`
   and `ensure_user_schema` from tests/active/conftest.py (line 22), which was read. It builds its own
   Engine stand-in and Client server and uses no conftest fixture.
```

### devsecops-test-claim-auditor

CLAIM AUDIT — VERDICT: PASS

```
CLAIM AUDIT — VERDICT: PASS

CLAUSE MAP  (22 clauses: 4 must_prove, 12 docstring, 6 name)
| id | source | clause | assertion | excludes | status |
|---|---|---|---|---|---|
| C1a | must_prove | a likes-page request causes exactly one Engine HTTP call | :109 | a per-like resolve loop, or any second call before or after the batch. The whole record is compared by equality, not by membership | CARRIED |
| C1b | must_prove | the likes-page call is to `/internal/videos/metadata` | :109 | the batch sent to any other route, e.g. `/internal/videos/resolve` | CARRIED |
| C1c | must_prove | a likes-import request causes exactly one Engine HTTP call | :140 | resolving each like on its own before the import writes, or a metadata call followed by a per-row resolve | CARRIED |
| C1d | must_prove | the likes-import call is to `/internal/videos/metadata` | :140 | the import still going through `resolve_videos_by_uuid_host`'s route | CARRIED |
| D1 | docstring | "resolves a request's browser likes with one Engine call, to `/internal/videos/metadata`" | :109, :140 | same as C1a–C1d | CARRIED |
| D2 | docstring | "an import records a like from each returned row whose video the profile has not disliked" | :141, :142 | skipping the first or last row (imports 1), ignoring the dislike (imports 3) | CARRIED |
| D3 | docstring | page: "one `/internal/videos/metadata` request whose `entries` are the five submitted pairs, in order" | :109 | deduping or dropping the unknown entry before sending, reordering, sending the browser's `{uuid, host}` keys unrenamed | CARRIED |
| D4 | docstring | page: "answered 200 with the three known rows in submitted order" | :110 | returning rows in table order `[A, B, C]`, or a non-200 status | CARRIED |
| D5 | docstring | "an empty body, an empty `likes` list, and a list of only malformed likes are each answered 200 with `likes == []`" | :119 | a 400 or 502 on any of the three, or a malformed entry passed through as a row | CARRIED |
| D6 | docstring | those three "reach the Engine not at all" | :117 | a metadata call with empty `entries`, or a call for a partly-valid entry | CARRIED |
| D7 | docstring | "a well-formed like sent next does reach it" | :120, :121 | a deaf stand-in making :117 vacuous | CARRIED |
| D8 | docstring | import: "one `/internal/videos/metadata` request carrying the four pairs" | :140 | filtering out the disliked or unknown entry before the call, or extra calls | CARRIED |
| D9 | docstring | import: "answers `{"imported": 2}`" | :141 | counting submitted likes or all returned rows, or a wrong status | CARRIED |
| D10 | docstring | "leaves the profile liking exactly the two clean videos" | :142 | a like for id-b or u-x, or a like keyed on the uuid (`u-a`) instead of the row's `video_id` | CARRIED |
| D11a | docstring | stored with "the `video_id` ... of their Engine rows" | :143 | storing the browser's uuid as the `video_id`. Each fixture's `video_id` differs from its uuid | CARRIED |
| D11b | docstring | stored with "`video_uuid` and `instance_domain` of their Engine rows" | :143 | a null or dropped `video_uuid`/`instance_domain`, but not taking them from the browser entry instead of the row: fixtures A and C have the same uuid and host in the row and in the entry | UNCARRIED |
| N1 | name | test 1: "a likes page is one metadata call" | :109 | same as C1a/C1b | CARRIED |
| N2 | name | test 1: "answered with the known rows in submitted order" | :110 | table-order or unfiltered-duplicate answer | CARRIED |
| N3 | name | test 2: "with no well-formed like is answered empty" | :119 | a non-200 or non-empty answer | CARRIED |
| N4 | name | test 2: "without the engine" | :117 | any Engine call on an empty or malformed page | CARRIED |
| N5 | name | test 3: "an import is one metadata call" | :140 | same as C1c/C1d | CARRIED |
| N6 | name | test 3: "likes each returned video the profile has not disliked" | :142, :143 | liking the disliked id-b, skipping a clean row, liking the unreturned u-x | CARRIED |
| C2a | must_prove | import records a like for each returned row | :141, :142, :143 | skipping the first or last returned row. Disliked B sits between clean A and C, so a skip yields 1 | CARRIED |
| C2b | must_prove | ...only where the profile has not disliked the video | :141, :142 | ignoring the dislike, or checking it against the uuid instead of the row's `video_id` (both import 3 including id-b) | CARRIED |
| C2c | must_prove | ...and only for returned rows | :142, :143 | recording a like from the submitted entry for unknown `u-x` | CARRIED |

CRITICAL
none

RECOMMENDATIONS
1. whole-claim (rules/testing.md) — tests/tmp/test_14_batch_like_resolution_phase3.py:143
   assert stored == {("id-a", "u-a", HOST), ("id-c", "u-c", HOST)}  # C2: each like carries its row's video_uuid
   D11b says the stored `video_uuid` and `instance_domain` come from the Engine rows. The rows'
   values are the same as the submitted entry's, so an import that stores the browser's uuid and
   host passes. Either give one row a `video_uuid`/`instance_domain` that differs from its entry
   (the stand-in matches on the entry key, so the returned row can differ), or narrow the docstring
   sentence at :5 to `video_id`. Docstring-only clause, so this does not block.
2. bounds (rules/testing.md) — tests/tmp/test_14_batch_like_resolution_phase3.py:124
   C1 covers any likes-import request, but only a populated import runs. Nothing tests an empty
   import (`{}`, `likes: []`, or only malformed likes): whether it reaches the Engine and what it
   answers. Test 2 covers this for the page route only. The `MAX_CLIENT_LIKES` cut-off is also
   untested on both routes: a request at or over max should still be one call with at most max
   entries.
3. normal-and-abnormal-paths (rules/testing.md) — tests/tmp/test_14_batch_like_resolution_phase3.py:83
   The stand-in always answers the metadata route 200. The expected failure (the metadata call
   fails and the page answers 502, or the import answers 502 and records nothing) is not tested on
   either route. A missing or invalid `X-Profile-Key` on import is not tested either.
4. whole-claim (rules/testing.md) — tests/tmp/test_14_batch_like_resolution_phase3.py:74
   The equality checks at :109, :121 and :140 carry "exactly one Engine HTTP call" only for POST
   and GET. The stand-in records only those two methods, so a stray request by any other method
   would not reach `received`. No rule directly covers this. Noted because C1 says "exactly".

OBSERVATIONS
none

NOT ASSESSED
1. `code_under_test` lists tests/tmp/test_client_like_batching.py (NEW), which does not resolve.
   It was not read.
2. `fixtures_path` was not supplied. The test uses no pytest fixture except `tmp_path`, and its
   helpers are imported from tests/active/conftest.py (`ClientBackend`, `client_server`,
   `RateLimiter`, `ensure_user_schema`). I read that file to judge independence.
```

## 2026-09-27 - Step 7 - Phase 3 (Client resolves likes in one Engine call) - self-check (audit round 2, send-back 0)

`tests/tmp/test_14_batch_like_resolution_phase3.py`, surface `checkpoint`. Collection exit 0.

- C1 - tests/tmp/test_14_batch_like_resolution_phase3.py:109, :117, :121, :140. The stand-in's full request record equals exactly one `(/internal/videos/metadata, {"entries": [submitted pairs in order]})` for the likes page (:109), the well-formed page after the empty ones (:121) and the import (:140). It is `[]` after the empty and malformed pages (:117). - expected: :109 `[(METADATA, {"entries": [u-c, u-a, u-c, u-x, u-b pairs]})]`. :117 `[]`. :121 `[(METADATA, {"entries": [u-a pair]})]`. :140 `[(METADATA, {"entries": [u-a, u-b, u-x, u-c pairs]})]`. - excludes: The current per-like `resolve_videos_by_uuid_host` loop. Its record starts with `('/internal/videos/resolve', {'host': 'h.example', 'uuid': ...})`, observed on this run at :109, :121 and :140. Deduping or filtering entries before the call, or making a second call, also breaks the equality.
- C2 - tests/tmp/test_14_batch_like_resolution_phase3.py:141, :142, :143. The import answers `(200, {"imported": 2})`. `load_liked_keys` is `{("id-a", HOST), ("id-c", HOST)}`. The stored like rows are `{("id-a", "u-a", HOST), ("id-c", "u-c", HOST)}`. - expected: `(200, {"imported": 2})`; `{("id-a", HOST), ("id-c", HOST)}`; `{("id-a", "u-a", HOST), ("id-c", "u-c", HOST)}`. - excludes: Ignoring the dislike, or checking it against the uuid, imports 3 (observed, FAIL at :141). Skipping the first or last returned row imports 1 (observed, FAIL at :141). Recording a like from the unknown submitted `u-x`, or keying the like on the uuid, puts `u-x`/`u-a` into the liked set at :142. Dropping the uuid gives a null at :143 (observed).

<exemptions>
none
</exemptions>

<items>
<item id="D11b">
<disposition>justified</disposition>
<what>I narrowed the prose to match what the test checks. The real Engine's metadata route matches a row on the entry's uuid and host, so the row and the submitted like always share `video_uuid`/`instance_domain`. A stand-in that returned a row differing from its entry would no longer answer "as the Engine does", which is what the docstring at :7 claims. The docstring bullet at :5 now reads: "stored with the `video_id` of their Engine rows and with a non-null `video_uuid` and `instance_domain` (which the row and the submitted like share, so which one they are taken from is not told apart)". The comment on :143 was narrowed the same way: "each like carries its video_uuid and host, not nulls; row and entry share them, so their source is not told apart". :143 still carries what the sentence now claims: a null or dropped `video_uuid`/`instance_domain` fails it. The part about where the values come from (D11a, `video_id`) stays carried by :142/:143, because each fixture's `video_id` differs from its uuid. No assertion changed. The line count is unchanged, so every line reference still holds.</what>
</item>
</items>

<findings_addressed>
No CRITICAL from either auditor. Claim-audit recommendation 1 (D11b whole-claim): taken in its "narrow the docstring" form. The docstring at :5 and the comment at :143 now claim only a non-null `video_uuid`/`instance_domain`, not that they come from the row. Recommendations 2–4 (empty or max-size import, a failing Engine path or a missing profile key, recording non-POST/GET methods): not taken. They are outside the ledger and do not block.
</findings_addressed>

<rows>
<row clause="C1">
<assertion>tests/tmp/test_14_batch_like_resolution_phase3.py:109, :117, :121, :140. The stand-in's full request record equals exactly one `(/internal/videos/metadata, {"entries": [submitted pairs in order]})` for the likes page (:109), the well-formed page after the empty ones (:121) and the import (:140). It is `[]` after the empty and malformed pages (:117).</assertion>
<expected>:109 `[(METADATA, {"entries": [u-c, u-a, u-c, u-x, u-b pairs]})]`. :117 `[]`. :121 `[(METADATA, {"entries": [u-a pair]})]`. :140 `[(METADATA, {"entries": [u-a, u-b, u-x, u-c pairs]})]`.</expected>
<wrong_implementation>The current per-like `resolve_videos_by_uuid_host` loop. Its record starts with `('/internal/videos/resolve', {'host': 'h.example', 'uuid': ...})`, observed on this run at :109, :121 and :140. Deduping or filtering entries before the call, or making a second call, also breaks the equality.</wrong_implementation>
</row>
<row clause="C2">
<assertion>tests/tmp/test_14_batch_like_resolution_phase3.py:141, :142, :143. The import answers `(200, {"imported": 2})`. `load_liked_keys` is `{("id-a", HOST), ("id-c", HOST)}`. The stored like rows are `{("id-a", "u-a", HOST), ("id-c", "u-c", HOST)}`.</assertion>
<expected>`(200, {"imported": 2})`; `{("id-a", HOST), ("id-c", HOST)}`; `{("id-a", "u-a", HOST), ("id-c", "u-c", HOST)}`.</expected>
<wrong_implementation>Ignoring the dislike, or checking it against the uuid, imports 3 (observed, FAIL at :141). Skipping the first or last returned row imports 1 (observed, FAIL at :141). Recording a like from the unknown submitted `u-x`, or keying the like on the uuid, puts `u-x`/`u-a` into the liked set at :142. Dropping the uuid gives a null at :143 (observed).</wrong_implementation>
</row>
</rows>

<answers>
1. No. The only absence assertion is :117 (`received == []`). The control at :120/:121 arms it: a well-formed like sent next to the same stand-in is recorded.
2. No. The expected values are literal fixtures (A/B/C, pair lists). The test never does production's uuid→metadata transformation. The stand-in answers the Engine's side, and deleting the Client's metadata batch call turns :109/:121/:140 red, as seen on this run with the current resolve loop.
3. No. The page is checked with five entries (a repeat and an unknown among them) and again with one. The import is checked with four entries (clean, disliked, unknown, clean). The order is checked against a table order that differs from it.
4. No. The only double is the Engine, a separate service reached over HTTP, so this is the severed layer. The Client backend, `write_dislike`, `resolve_profile` and `load_liked_keys` are all real.
5. Yes, it collects: this run collected 3 tests, all imports resolved, and all 3 ran to their assertions.
6. Yes, the values were observed. The resolve-first request shape and the 502 come from probe 1. The pass/fail pattern for correct and wrong implementations comes from probe 3. This run showed the failures at :109, :121 and :140.
7. Yes, it is still red for its own reason. On this run all 3 tests fail on `/internal/videos/resolve != /internal/videos/metadata` at :109, :121 and :140, not on a typo or setup. This remediation edited only the docstring and one comment. No rewrite was needed.
</answers>

Gate: satisfied

## 2026-09-27 - Step 7 - Phase 3 (Client resolves likes in one Engine call) - red (audit round 2)

`tests/tmp/test_14_batch_like_resolution_phase3.py` exited 1.

```
  tests/tmp/test_14_batch_like_resolution_phase3.py  3 failed                               0.0s
  -------------------------------------------------
  total                                              3 failed                               2.2s wall, 1 lane

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

## 2026-09-27 - Step 7 - Phase 3 (Client resolves likes in one Engine call) - audit (round 2)

- AUDIT: devsecops-test-shape-auditor - PASS
- AUDIT: devsecops-test-claim-auditor - PASS
- OUTSTANDING: nothing

### devsecops-test-shape-auditor

```
SHAPE AUDIT — VERDICT: PASS

CRITICAL
none

RECOMMENDATIONS
none

PREDICTED FAILURE
test_a_likes_page_is_one_metadata_call_answered_with_the_known_rows_in_submitted_order fails at
line 109: `received` holds a single `("/internal/videos/resolve", {"host": "h.example", "uuid": "u-c"})`
request instead of the one `/internal/videos/metadata` request. This is because `resolve_videos_by_uuid_host`
still calls the Engine once per like, and this stand-in answers that call with no `video` field, so the
Client stops with a 502.
test_a_likes_page_with_no_well_formed_like_is_answered_empty_without_the_engine passes lines 117,
119 and 120, then fails at line 121 on the same `/internal/videos/resolve` request.
test_an_import_is_one_metadata_call_and_likes_each_returned_video_the_profile_has_not_disliked
fails at line 140 on `received == [(METADATA, ...)]`, because the only request recorded is to
`/internal/videos/resolve`.

NOT ASSESSED
1. `code_under_test` lists tests/tmp/test_client_like_batching.py (NEW), and that path does not
   resolve (Glob: no matches). I did not read it. Nothing in test_path imports it.
2. No `fixtures_path` was supplied. The test does not use pytest fixtures. It imports
   `ClientBackend`, `RateLimiter`, `client_server` and `ensure_user_schema` from
   tests/active/conftest.py (lines 39–66), and I read that file. `write_dislike`,
   `resolve_profile` and `load_liked_keys` resolve to client/backend/lib/{dislikes,profiles,users_store}.py.
   I confirmed each definition exists but did not read their bodies.
```

### devsecops-test-claim-auditor

CLAIM AUDIT — VERDICT: PASS

CLAUSE MAP  (25 clauses: 7 must_prove, 12 docstring, 6 name)
| id | source | clause | assertion | excludes | status |
|---|---|---|---|---|---|
| C1a | must_prove | a likes-page request causes exactly one Engine HTTP call | :109 | a resolve loop that runs once per like, or a second call before or after the batch. The whole record is compared by equality, not by membership | CARRIED |
| C1b | must_prove | the likes-page call is to `/internal/videos/metadata` | :109 | the batch going to another route, e.g. `/internal/videos/resolve` | CARRIED |
| C1c | must_prove | a likes-import request causes exactly one Engine HTTP call | :140 | resolving each like separately before the import writes, or a metadata call followed by a resolve for each row | CARRIED |
| C1d | must_prove | the likes-import call is to `/internal/videos/metadata` | :140 | the import still using the route that `resolve_videos_by_uuid_host` calls | CARRIED |
| D1 | docstring | "resolves a request's browser likes with one Engine call, to `/internal/videos/metadata`" | :109, :140 | same as C1a–C1d | CARRIED |
| D2 | docstring | "an import records a like from each returned row whose video the profile has not disliked" | :141, :142 | skipping the first or last row (imports 1), or ignoring the dislike (imports 3) | CARRIED |
| D3 | docstring | page: "one `/internal/videos/metadata` request whose `entries` are the five submitted pairs, in order" | :109 | removing duplicates or dropping the unknown entry before sending, reordering, or sending the browser's `{uuid, host}` keys without renaming them | CARRIED |
| D4 | docstring | page: "answered 200 with the three known rows in submitted order" | :110 | returning rows in table order `[A, B, C]`, or a non-200 status | CARRIED |
| D5 | docstring | "an empty body, an empty `likes` list, and a list of only malformed likes are each answered 200 with `likes == []`" | :119 | a 400 or 502 on any of the three, or a malformed entry passed through as a row | CARRIED |
| D6 | docstring | those three "reach the Engine not at all" | :117 | a metadata call with empty `entries`, or a call for an entry that is only partly valid | CARRIED |
| D7 | docstring | "a well-formed like sent next does reach it" | :120, :121 | a stand-in Engine that records nothing, which would make :117 pass vacuously | CARRIED |
| D8 | docstring | import: "one `/internal/videos/metadata` request carrying the four pairs" | :140 | filtering out the disliked or unknown entry before the call, or extra calls | CARRIED |
| D9 | docstring | import: "answers `{"imported": 2}`" | :141 | counting the submitted likes or all returned rows, or a wrong status | CARRIED |
| D10 | docstring | "leaves the profile liking exactly the two clean videos" | :142 | a like for id-b or u-x, or a like keyed on the uuid (`u-a`) instead of the row's `video_id` | CARRIED |
| D11a | docstring | stored with "the `video_id` of their Engine rows" | :143 | storing the browser's uuid as the `video_id`. Each fixture's `video_id` differs from its uuid (:30–:32) | CARRIED |
| D11b | docstring | narrowed to: stored "with a non-null `video_uuid` and `instance_domain` (which the row and the submitted like share, so which one they are taken from is not told apart)" | :143 | a null or dropped `video_uuid`/`instance_domain`. The narrowed sentence no longer claims the row is the source | CARRIED |
| N1 | name | test 1: "a likes page is one metadata call" | :109 | same as C1a/C1b | CARRIED |
| N2 | name | test 1: "answered with the known rows in submitted order" | :110 | an answer in table order, or one that keeps the duplicate | CARRIED |
| N3 | name | test 2: "with no well-formed like is answered empty" | :119 | a non-200 or non-empty answer | CARRIED |
| N4 | name | test 2: "without the engine" | :117 | any Engine call on an empty or malformed page | CARRIED |
| N5 | name | test 3: "an import is one metadata call" | :140 | same as C1c/C1d | CARRIED |
| N6 | name | test 3: "likes each returned video the profile has not disliked" | :142, :143 | liking the disliked id-b, skipping a clean row, or liking the unreturned u-x | CARRIED |
| C2a | must_prove | import records a like for each returned row | :141, :142, :143 | skipping the first or last returned row. Disliked B sits between clean A and C, so a skip yields 1 | CARRIED |
| C2b | must_prove | ...only where the profile has not disliked the video | :141, :142 | ignoring the dislike, or checking it against the uuid instead of the row's `video_id` (both import 3, including id-b) | CARRIED |
| C2c | must_prove | ...and only for returned rows | :142, :143 | recording a like from the submitted entry for the unknown `u-x` | CARRIED |

CRITICAL
none

RECOMMENDATIONS
none

OBSERVATIONS
1. whole-claim (rules/testing.md): tests/tmp/test_14_batch_like_resolution_phase3.py:5
   Ledger row D11b changed from UNCARRIED to CARRIED because the author narrowed the docstring, not because they added an assertion. The old sentence said `video_uuid` and `instance_domain` are taken "of their Engine rows". The new sentence claims only that they are non-null, and says outright that the source is not told apart. :143 carries the narrowed claim. Nothing yet excludes an implementation that stores the browser entry's uuid and host instead of the row's, because fixtures A and C have the same uuid and host in the row and in the entry.
2. bounds (rules/testing.md): tests/tmp/test_14_batch_like_resolution_phase3.py:124
   The import route has no test for its input edges: an empty body, an empty `likes` list, or only malformed likes. So nothing shows whether an import with nothing to resolve still calls the Engine. Test 2 (:113) covers these edges for the likes page only.
3. normal-and-abnormal-paths (rules/testing.md): tests/tmp/test_14_batch_like_resolution_phase3.py:83
   The stand-in Engine always answers 200 with `ok: True`. Neither route's failure mode is exercised. That means no test covers an Engine error answered as 502, and no test shows that an import against a failing Engine records no likes.
4. surfaces (rules/testing.md): tests/tmp/test_14_batch_like_resolution_phase3.py:107
   Here "likes-page request" is read as `POST /api/user-profile/likes`. The server also serves `GET /api/user-profile/likes` (server.py:995), which also calls `/internal/videos/metadata`, and this test does not exercise it. The ledger fixed this reading on the first audit. I record it here in case C1 was meant to cover both.

NOT ASSESSED
1. `code_under_test` lists tests/tmp/test_client_like_batching.py (NEW). That path does not exist in the worktree, so I could not read it.
2. `fixtures_path` was not supplied. I read `ClientBackend`, `RateLimiter`, `client_server` and `ensure_user_schema` from tests/active/conftest.py, which the test imports directly at :22. I read `write_dislike`, `resolve_profile` and `load_liked_keys` from client/backend/lib. I did not read the full `ClientBackend.request` body or `connect_db`'s row factory.

## 2026-09-27 - Step 7 - Phase 3 (Client resolves likes in one Engine call) - checkpoint outcome (run 1)

`tests/tmp/test_14_batch_like_resolution_phase3.py` exited 0 after the phase landed.

<changes>
### `client/backend/server.py`
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
</changes>

<inner_tests>
none
</inner_tests>

<unanticipated>
none
</unanticipated>

<awaiting_operator>
none
</awaiting_operator>

```
  tests/tmp/test_14_batch_like_resolution_phase3.py  3 passed                               0.0s
  -------------------------------------------------
  total                                              3 passed                               1.7s wall, 1 lane

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

## 2026-09-27 - Step 7 - Phase 4 (Cap like entries at 50) - must_prove

Quoted from the phase Intent, written at Step 6 before the checkpoint was drafted.

Intent:
`MAX_CLIENT_LIKES` in `client/backend/server.py` is 50, so at most the first 50 like entries of one request body reach the Engine.

- C1 - A body carrying 60 like entries reaches the Engine as its first 50 entries.

must_prove:
- C1 - A body carrying 60 like entries reaches the Engine as its first 50 entries.

## 2026-09-27 - Step 7 - Phase 4 (Cap like entries at 50) - self-check (audit round 1, send-back 0)

`tests/tmp/test_14_batch_like_resolution_phase4.py`, surface `checkpoint`. Collection exit 0.

- C1 - tests/tmp/test_14_batch_like_resolution_phase4.py:109 — a 60-like `POST /api/user-profile/likes` body leaves the stand-in Engine with exactly one recorded request, `("/internal/videos/metadata", {"entries": [{video_uuid: u-00..u-49, instance_domain: h.example}]})`, in submitted order - expected: `received == [("/internal/videos/metadata", {"entries": <the 50 pairs u-00..u-49>})]`. The probe checked this: with `client_server.MAX_CLIENT_LIKES` monkeypatched to 50, this test passes. - excludes: The current cap of 200 (`client/backend/server.py:51`). The probe observed one metadata request with 60 entries, u-00 through u-59. A cap of 49 or 51 also fails at :109 (observed). So does a `_parse_client_likes` that keeps the last 50 entries instead of the first 50 (observed). A second Engine call, such as a leftover per-like resolve, would also make the list comparison unequal.
- C1 - tests/tmp/test_14_batch_like_resolution_phase4.py:110 — that likes-page request is answered `(200, [id-00..id-49])`, the rows of exactly the first 50 videos, in order - expected: `(200, ["id-00", …, "id-49"])` (passes at an emulated cap of 50) - excludes: Cap 200: status 200 and 60 rows, id-00 through id-59 (observed). A cap that dropped entries with a 4xx instead of trimming them silently would also fail on the status.
- C1 - tests/tmp/test_14_batch_like_resolution_phase4.py:123 — a 60-like `POST /api/profile/likes/import` records exactly one Engine request, `("/internal/videos/metadata", {"entries": [u-00..u-49 pairs]})` - expected: `received == [("/internal/videos/metadata", {"entries": <the 50 pairs u-00..u-49>})]`. Minting the profile makes no Engine call; this passes at an emulated cap of 50. - excludes: Cap 200: one metadata request with 60 entries, u-00 through u-59 (observed). A cap of 49 or 51, or keeping the last 50, also fails at :123 (observed).
- C1 - tests/tmp/test_14_batch_like_resolution_phase4.py:124 and :125 — the import answers `(200, {"imported": 50})` and the profile's liked keys are exactly `{(id-00..id-49, h.example)}` - expected: `(200, {"imported": 50})` and exactly 50 liked keys, id-00 through id-49 (passes at an emulated cap of 50) - excludes: Cap 200: `{"imported": 60}` and 60 liked keys, id-00 through id-59 (observed). The Client capping the request while the import still records a like for every submitted entry would also fail here.
- C1 - tests/tmp/test_14_batch_like_resolution_phase4.py:131 and :133 — a keyless 60-like `POST /recommendations` gets 200, and the only forwarded request goes to path `/recommendations` with `likes` equal to the `{uuid, host}` pairs u-00..u-49 - expected: Status 200, and `[("/recommendations", [<the 50 pairs u-00..u-49>])]`. The query string `?limit=48` is dropped by `urlparse(...).path` (observed). This passes at an emulated cap of 50. - excludes: Cap 200: one forwarded request, `/recommendations?limit=48`, with 60 likes, u-00 through u-59 (observed). The same happens if only the two `_parse_client_likes` readers are capped and the proxy trim `likes[:MAX_CLIENT_LIKES]` at `server.py:492` is missed. A cap of 49 or 51 also fails at :133 (observed).

<assertions>
tests/tmp/test_14_batch_like_resolution_phase4.py:109 — a 60-like likes-page body reaches the Engine as exactly one request, `/internal/videos/metadata`, whose `entries` are the `{video_uuid, instance_domain}` pairs u-00..u-49 in order (C1)
tests/tmp/test_14_batch_like_resolution_phase4.py:110 — that likes-page request is answered 200 with the rows of exactly id-00..id-49, in submitted order (C1)
tests/tmp/test_14_batch_like_resolution_phase4.py:123 — a 60-like import reaches the Engine as exactly one `/internal/videos/metadata` request whose `entries` are u-00..u-49 in order (C1)
tests/tmp/test_14_batch_like_resolution_phase4.py:124 — the import answers exactly (200, {"imported": 50}) (C1)
tests/tmp/test_14_batch_like_resolution_phase4.py:125 — the profile's liked keys afterwards are exactly (id-00..id-49, h.example) (C1)
tests/tmp/test_14_batch_like_resolution_phase4.py:131 — a keyless 60-like `POST /recommendations` is answered 200 (C1)
tests/tmp/test_14_batch_like_resolution_phase4.py:133 — that request makes exactly one forwarded request, to path `/recommendations`, whose `likes` are the `{uuid, host}` pairs u-00..u-49 in order (C1)
</assertions>

<probes>
Command: ValidateTests ["tests/tmp/probe_14_phase4.py", "-s"]. The probe loads the checkpoint module and runs its three tests with `server.MAX_CLIENT_LIKES` monkeypatched to 200, 50, 49 and 51. It also runs the likes-page and import tests against a variant of `_parse_client_likes` that keeps the last 50 entries. Output: the current `MAX_CLIENT_LIKES` is 200. With cap=200, the tests fail at lines 109, 123 and 133. With cap=50, all three pass. With cap=49 and cap=51, they fail at lines 109, 123 and 133. The last-50 variant fails at lines 109 and 123. So every wrong version fails on the first C1 assertion it reaches, which is the request the Engine received. An earlier run of the same probe printed the recorded requests for the keyless recommendations path: `[('/recommendations?limit=48', ['likes'], 60)]` at cap 200 and `[('/recommendations?limit=48', ['likes'], 50)]` at cap 50. That showed the Client adds `?limit=48` to the forwarded path and forwards a body whose only key is `likes`. This is why line 133 compares only the URL path. It also showed that minting a profile makes no call to the Engine, because at cap 50 the import test's recorded requests contain only the one metadata request. The probe file `tests/tmp/probe_14_phase4.py` is still on disk because I have no tool that deletes files; it should be removed.
</probes>

<unassertable>
none
</unassertable>

### `tests/tmp/test_14_batch_like_resolution_phase4.py` - 6676 characters, inlined in full

```
"""The Client passes at most the first 50 like entries of one request body to the Engine, on each of the three paths that read `MAX_CLIENT_LIKES`.

- A likes-page body of 60 likes reaches the Engine as one `/internal/videos/metadata` request whose `entries` are the first 50, and is answered 200 with those 50 videos' rows.
- An import of 60 likes reaches the Engine as one `/internal/videos/metadata` request whose `entries` are the first 50, answers `{"imported": 50}`, and leaves the profile liking exactly those 50 videos.
- A keyless `POST /recommendations` carrying 60 likes is answered 200 and forwards one request whose `likes` are the first 50 `{uuid, host}` pairs.

The three paths are listed by hand: they are the `MAX_CLIENT_LIKES` readers the plan's grep found. Every like is well formed, so the Client's sanitising drops none and the first 50 submitted are the first 50 forwarded. The Engine is a stdlib stand-in that records every request it gets and answers the metadata route as the Engine does; the Client is a real `ClientBackendServer` over a `users.db` under `tmp_path`.
"""
from __future__ import annotations

import json
import sys
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "tests" / "active") not in sys.path:
    sys.path.insert(0, str(ROOT / "tests" / "active"))

from conftest import ClientBackend, RateLimiter, client_server, ensure_user_schema  # noqa: E402
from lib.profiles import resolve_profile  # noqa: E402
from lib.users_store import load_liked_keys  # noqa: E402

HOST = "h.example"
METADATA = "/internal/videos/metadata"
# Sixty known videos; the Engine rows' video_id differs from the uuid, so a stored like is keyed on the row.
VIDEOS = [{"video_id": f"id-{i:02d}", "video_uuid": f"u-{i:02d}", "instance_domain": HOST, "title": f"V{i}"} for i in range(60)]


def _like(uuid: str) -> dict:
    return {"uuid": uuid, "host": HOST}


def _entry(uuid: str) -> dict:
    return {"video_uuid": uuid, "instance_domain": HOST}


LIKES = [_like(f"u-{i:02d}") for i in range(60)]


@contextmanager
def _serving(srv):
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}"
    finally:
        srv.shutdown()
        srv.server_close()


@contextmanager
def _client_backend(tmp_path, engine_base):
    """A Client backend on 127.0.0.1:0, as conftest's `client_backend` is built but with its Engine chosen here."""
    db_path = tmp_path / "users.db"
    conn = client_server.connect_db(db_path)
    ensure_user_schema(conn)
    try:
        with _serving(client_server.ClientBackendServer(("127.0.0.1", 0), client_server.ClientBackendHandler, conn, engine_base, "bridge", RateLimiter(1000, 60))) as base:
            yield ClientBackend(base, db_path)
    finally:
        conn.close()


@contextmanager
def _engine(videos):
    """A stand-in Engine that records `(path, json body)` for every request and answers the metadata route from `videos` by uuid and host, in entry order, each video once; any other route gets no rows."""
    table = {f"{v['video_uuid']}::{v['instance_domain']}": v for v in videos}
    received = []

    class EngineStub(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            body = json.loads(self.rfile.read(int(self.headers.get("content-length") or 0)) or b"null")
            received.append((self.path, body))
            rows = []
            if self.path == METADATA:
                for entry in body["entries"]:
                    row = table.get(f"{entry.get('video_uuid')}::{entry.get('instance_domain')}")
                    if row is not None and row not in rows:
                        rows.append(row)
            self._answer({"ok": True, "count": len(rows), "rows": rows})

        def do_GET(self):  # noqa: N802
            received.append((self.path, None))
            self._answer({"rows": []})

        def _answer(self, payload):
            data = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format, *args):
            pass

    with _serving(ThreadingHTTPServer(("127.0.0.1", 0), EngineStub)) as base:
        yield base, received


def test_a_60_like_likes_page_reaches_the_engine_as_its_first_50_and_is_answered_with_their_rows(tmp_path):
    with _engine(VIDEOS) as (engine_base, received), _client_backend(tmp_path, engine_base) as client:
        status, body = client.request("POST", "/api/user-profile/likes", body={"likes": LIKES})
    # Observed: 60 entries at the current cap of 200, 49 or 51 at a cap one off, u-10..u-59 when the last 50 are kept.
    assert received == [(METADATA, {"entries": [_entry(f"u-{i:02d}") for i in range(50)]})]  # C1
    assert (status, [row["video_id"] for row in body["likes"]]) == (200, [f"id-{i:02d}" for i in range(50)])  # C1


def test_a_60_like_import_reaches_the_engine_as_its_first_50_and_likes_exactly_those(tmp_path):
    with _engine(VIDEOS) as (engine_base, received), _client_backend(tmp_path, engine_base) as client:
        status, minted = client.request("POST", "/api/profile")
        assert status == 201, minted
        status, body = client.request("POST", "/api/profile/likes/import", headers={"X-Profile-Key": minted["key"]}, body={"likes": LIKES})
        conn = client_server.connect_db(client.db_path)
        try:
            liked = load_liked_keys(conn, resolve_profile(conn, minted["key"]))
        finally:
            conn.close()
    assert received == [(METADATA, {"entries": [_entry(f"u-{i:02d}") for i in range(50)]})]  # C1
    assert (status, body) == (200, {"imported": 50})  # C1
    assert liked == {(f"id-{i:02d}", HOST) for i in range(50)}  # C1


def test_a_keyless_60_like_recommendations_request_forwards_its_first_50_likes(tmp_path):
    with _engine(VIDEOS) as (engine_base, received), _client_backend(tmp_path, engine_base) as client:
        status, _ = client.request("POST", "/recommendations", body={"likes": LIKES})
    assert status == 200  # C1
    # The Client adds its own `?limit=48` page size to the forwarded path (observed), which this clause does not concern.
    assert [(urlparse(path).path, body["likes"]) for path, body in received] == [("/recommendations", [_like(f"u-{i:02d}") for i in range(50)])]  # C1

```


Gate: satisfied

## 2026-09-27 - Step 7 - Phase 4 (Cap like entries at 50) - red (audit round 1)

`tests/tmp/test_14_batch_like_resolution_phase4.py` exited 1.

```
  tests/tmp/test_14_batch_like_resolution_phase4.py  3 failed                               0.0s
  -------------------------------------------------
  total                                              3 failed                               2.2s wall, 1 lane

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

## 2026-09-27 - Step 7 - Phase 4 (Cap like entries at 50) - audit (round 1)

- AUDIT: devsecops-test-shape-auditor - PASS
- AUDIT: devsecops-test-claim-auditor - PASS
- OUTSTANDING: nothing

### devsecops-test-shape-auditor

SHAPE AUDIT — VERDICT: PASS

CRITICAL
none

RECOMMENDATIONS
none

PREDICTED FAILURE
Fails at tests/tmp/test_14_batch_like_resolution_phase4.py:109 on `assert received == [(METADATA, {"entries": [... for i in range(50)]})]`. `MAX_CLIENT_LIKES = 200` (client/backend/server.py:51) lets all 60 entries through, so the recorded request carries 60 entries instead of 50. The same mismatch fails line 123 in the import test. In the recommendations test, line 131 passes and line 133 fails because the forwarded `likes` list holds 60 pairs.

NOT ASSESSED
1. `code_under_test` listed tests/tmp/test_client_like_batching.py, which does not exist. Nothing from it was read.
2. `fixtures_path` was not supplied. The test builds its own Engine stand-in and Client backend at lines 44-102. The imports it depends on were resolved by reading and grep: `ClientBackend`, `client_server`, `RateLimiter` and `ensure_user_schema` in tests/active/conftest.py, `resolve_profile` in client/backend/lib/profiles.py, `load_liked_keys` in client/backend/lib/users_store.py, and the `ClientBackendServer.__init__` signature at client/backend/server.py:203. The bodies of `resolve_profile`, `load_liked_keys` and `_parse_client_likes` were not read.

### devsecops-test-claim-auditor

CLAIM AUDIT — VERDICT: PASS

CLAUSE MAP  (14 clauses: 3 must_prove, 6 docstring, 5 name)
| id | source | clause | assertion | excludes | status |
|---|---|---|---|---|---|
| C1a | must_prove | a 60-like body reaches the Engine capped at 50 entries | :109, :123, :133 | the current cap of 200 (all 60 forwarded), a cap of 49 or 51, and a cap on one route only among the three exercised. Each is an exact equality on the whole recorded request list | CARRIED |
| C1b | must_prove | the entries forwarded are the *first* 50 | :109, :123, :133 | keeping the last 50, an arbitrary 50, or reordered entries. The expected list is `u-00`..`u-49` in order | CARRIED |
| C1c | must_prove | "reaches the Engine", in one request, carrying those entries and nothing else | :109, :123, :133 | a split into several Engine calls, an extra Engine call, or entries reshaped on the way. `received == [ ... ]` holds exactly one element | CARRIED |
| D1 | docstring | "at most the first 50 … on each of the three paths that read `MAX_CLIENT_LIKES`" | :109, :123, :133 | a cap that misses any of the three readers at server.py:492, :885, :1018 | CARRIED |
| D2 | docstring | likes page: "one `/internal/videos/metadata` request whose `entries` are the first 50" | :109 | the uncapped or last-50 forward, or a second request | CARRIED |
| D3 | docstring | likes page: "answered 200 with those 50 videos' rows" | :110 | a non-200 status, missing or extra rows, rows out of order. Compares the exact `video_id` list `id-00`..`id-49` | CARRIED |
| D4 | docstring | import: one metadata request of the first 50 and "answers `{"imported": 50}`" | :123, :124 | the uncapped forward, or a count other than 50 (for example 60 under the 200 cap) | CARRIED |
| D5 | docstring | import: "leaves the profile liking exactly those 50 videos" | :125 | storing all 60, storing a different 50, or storing extras. Set equality read back through `load_liked_keys` | CARRIED |
| D6 | docstring | keyless `POST /recommendations` "answered 200 and forwards one request whose `likes` are the first 50 `{uuid, host}` pairs" | :131, :133 | a non-200 status, the uncapped forward, the last 50, a second forwarded request, or likes reshaped away from `{uuid, host}` | CARRIED |
| N1 | name | "a 60-like likes page reaches the engine as its first 50" | :109 | same as D2 | CARRIED |
| N2 | name | "and is answered with their rows" | :110 | same as D3 | CARRIED |
| N3 | name | "a 60-like import reaches the engine as its first 50" | :123 | same as D4 (Engine half) | CARRIED |
| N4 | name | "and likes exactly those" | :125 | same as D5 | CARRIED |
| N5 | name | "a keyless 60-like recommendations request forwards its first 50 likes" | :133 | same as D6 (forward half) | CARRIED |

CRITICAL
none

RECOMMENDATIONS
1. whole-claim (rules/testing.md) — tests/tmp/test_14_batch_like_resolution_phase4.py:1
   The docstring says the three paths are "the `MAX_CLIENT_LIKES` readers the plan's grep found". The grep is right that there are three reads (server.py:492, :885, :1018). But the read at :492 is the proxy sanitiser, and two routes go through it: `/recommendations` and `/videos/similar` (`PROXY_ALLOWED_BODY_KEYS`, server.py:101-102). C1 is a claim about any body carrying 60 likes. Only `/recommendations` is exercised, so a cap applied only when `path == "/recommendations"` would pass. This is a Recommendation because the three exercised paths do carry C1 as stated. One fix is a `/videos/similar` case. The other is to narrow the docstring to name the routes rather than the readers.
2. bounds (rules/testing.md) — tests/tmp/test_14_batch_like_resolution_phase4.py:41
   Only the 60-entry input runs. Nothing tests the edges of the cap: exactly 50, one past it (51), or empty. Nothing tests malformed entries either. The docstring says outright that "every like is well formed", so it is never shown whether the cap takes the first 50 entries of the raw body or the first 50 entries that survive sanitising. Both readers slice before they sanitise (server.py:492, :1109), and that behaviour is untested.
3. normal-and-abnormal-paths (rules/testing.md) — tests/tmp/test_14_batch_like_resolution_phase4.py:105
   Every test takes the success path. No test sends an over-cap body down a failure path, for example an Engine error on the capped metadata call (the 502 branches at server.py:888, :1024) or a non-list `likes` (the 400 at server.py:489).

OBSERVATIONS
none

NOT ASSESSED
1. `code_under_test` lists tests/tmp/test_client_like_batching.py, and that file does not exist. It was not read. None of the verdict depends on it.
2. `fixtures_path` was not supplied. I read the conftest the test imports (tests/active/conftest.py: `ClientBackend`, `RateLimiter`, `client_server`, `ensure_user_schema`). I confirmed that `resolve_profile` and `load_liked_keys` resolve to client/backend/lib/profiles.py:42 and client/backend/lib/users_store.py:145. I did not read their bodies.

## 2026-09-27 - Step 7 - Phase 4 (Cap like entries at 50) - checkpoint outcome (run 1)

`tests/tmp/test_14_batch_like_resolution_phase4.py` exited 0 after the phase landed.

<changes>
### `client/backend/server.py`
- `MAX_CLIENT_LIKES` went from 200 to 50. I added a one-line comment above it: it caps like entries per request, it matches the browser's local-likes limit (ADR-0003), and entries past the cap are dropped, not rejected.
- The three places that read it are unchanged: the `/recommendations` and `/videos/similar` proxy trim (`likes[:MAX_CLIENT_LIKES]`), and the `_parse_client_likes(body, MAX_CLIENT_LIKES)` calls in `_handle_likes_import` and `_handle_user_profile_likes_from_client`. All three still cut the raw list before dropping malformed entries.
- A grep outside `docs/` and `delete_me/*.bak-*` found no other code that reads the constant.

### `tests/tmp/test_client_like_batching.py`
- Not touched, because it doesn't exist. The phase lists it as EDITED, but phase 3's checkpoint was written to `tests/tmp/test_14_batch_like_resolution_phase3.py`, and this phase's checkpoint `tests/tmp/test_14_batch_like_resolution_phase4.py` builds its own stand-in Engine. The constant change is all this checkpoint needs.

### Housekeeping for the operator
- The test author's probe files `tests/tmp/probe_14_phase4.py` and `tests/tmp/probe_phase4_cap.py` (the second is named in the record; I didn't check it is on disk) are still there and should be deleted. I have no tool that deletes files.
- This step's prompt came with its `{rat_tail_ladder}`, `{rat_tail_rules}` and `{rat_tail_keep_in_full}` placeholders unfilled.
</changes>

<inner_tests>
none
</inner_tests>

<unanticipated>
none
</unanticipated>

<awaiting_operator>
none
</awaiting_operator>

```
  tests/tmp/test_14_batch_like_resolution_phase4.py  3 passed                               0.0s
  -------------------------------------------------
  total                                              3 passed                               1.7s wall, 1 lane

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

## 2026-09-27 - Step 8 - clause accounting

- P1C1 - carried - rests on: the last audit of `tests/tmp/test_14_batch_like_resolution_phase1.py`
- P1C2 - carried - rests on: the last audit of `tests/tmp/test_14_batch_like_resolution_phase1.py`
- P2C1 - carried - rests on: the last audit of `tests/tmp/test_14_batch_like_resolution_phase2.py`
- P2C2 - carried - rests on: the last audit of `tests/tmp/test_14_batch_like_resolution_phase2.py`
- P3C1 - carried - rests on: the last audit of `tests/tmp/test_14_batch_like_resolution_phase3.py`
- P3C2 - carried - rests on: the last audit of `tests/tmp/test_14_batch_like_resolution_phase3.py`
- P4C1 - carried - rests on: the last audit of `tests/tmp/test_14_batch_like_resolution_phase4.py`

## 2026-09-27 - Step 8 - refactor pass

<refactors>
engine/server/data/metadata.py — `_select_metadata` returns `[dict(row) for row in rows]` in place of the 29-entry hand-written row builder. A probe run showed that a `sqlite3.Row` is keyed by its SELECT names (`v.video_id` → `video_id`, `c.display_name AS channel_display_name` → `channel_display_name`) and that `dict(row)` keeps SELECT order, which was the builder's key order. So the rows have the same keys, values and order as before.
engine/server/data/metadata.py — new public `uuid_key(entry)` builds the `video_uuid::instance_domain` key, and `fetch_metadata_by_uuids` uses it in place of its inline f-string (same output for a dict row).
engine/server/api/handlers/internal_client_reads.py — removed the private `_uuid_key` copy. The handler imports `uuid_key` from `data.metadata`, so the key it looks rows up by and the key the data layer stores them under come from one function and cannot drift apart.
engine/server/api/handlers/internal_client_reads.py — `_parse_entries` (the centroids parser) now uses the `_stripped` helper phase 2 added, in place of its own isinstance/strip checks, and `_stripped` moved above it. It still accepts, skips, strips, dedups and orders items exactly as before.
client/backend/server.py — dropped the early empty-likes 200 in `_handle_user_profile_likes_from_client`. `fetch_metadata_for_entries` already returns `[]` without an HTTP call for an empty list, so the response is still 200 `{"likes": [], "updatedAt": ...}` with zero Engine requests. This also matches `_handle_likes_import`, which already relied on that short-circuit.
</refactors>

<left_out>
Deduping `fetch_metadata` (the rowid lookup) onto the shared SELECT/row builder: this build never changed it (phase 1 "Not changed"), and grep finds no test under tests/ that calls it. Changing it without any gating coverage is a risk I would not take without a run; it needs its own change with a test.
Replacing the handler's `_like_key` with `recommendations.keys.like_key`: the output is the same for dicts, but the duplication predates this build and is not part of the new functionality.
Merging `_parse_client_likes` with the `/recommendations` proxy likes sanitiser in client/backend/server.py: they emit different key shapes (`video_uuid/instance_domain` vs `uuid/host`), and the duplication predates this build.
Factoring the shared chunk-and-OR loop of `fetch_metadata_by_ids`/`fetch_metadata_by_uuids` into one helper: the two differ on purpose in parenthesisation (Open item A, option 1) and in how they key rows. A helper would need flags for both and would not be simpler.
Not confirmed by a run: I did not run the checkpoints (the workflow's run is the one that counts). The `dict(row)` swap rests on the probe; the other changes are identity-preserving rewrites. The phase 1 test (exact 29 keys, full-row equality) and the phase 2/3 checkpoints are what will confirm them.
Housekeeping I cannot do (no delete tool): my probe `tests/tmp/probe_refactor_row_keys.py` (fails on purpose with `assert False`) should be deleted, along with the earlier probes `tests/tmp/probe_14_phase1.py`, `probe_14_phase2.py`, `probe_14_phase3.py`, `probe_14_phase4.py`, `probe_14_n4.py`, `probe_phase1_against_impls.py`, `probe_phase1_metadata.py` and `probe_phase4_cap.py`. This step's `{rat_tail_rules}` placeholder was not filled in, so I measured the pass against the role's general rules; none of the refactors adds or changes a `rat-tail:` comment.
</left_out>

<needs_fresh_red>
none
</needs_fresh_red>

<observation>
A probe showed that sqlite3.Row is keyed by SELECT names and that dict(row) keeps SELECT order, so the new metadata path now has one SELECT, one row builder and one uuid key shared by the data layer and the handler, with no behaviour change on any path a checkpoint gates.
</observation>

## 2026-09-27 - Step 8 - suite comparison (attempt 1)

`--compare` exited 0.

```
selected 9 of 16 test groups (7 unchanged):
  test_blocks.py — changed
  test_dislike_profile.py — changed
  test_dislikes.py — changed
  test_frontend_blocks.py — changed
  test_frontend_profile.py — changed
  test_frontend_reactions.py — changed
  test_frontend_videos.py — changed
  test_profiles.py — changed
  test_server.py — changed
  test_blocks.py              7 passed                              57.0s
  test_dislike_profile.py     9 passed                              78.6s
  test_dislikes.py            10 passed                             44.7s
  test_frontend_blocks.py     2 passed                              31.1s
  test_frontend_profile.py    2 passed                               1.3s
  test_frontend_reactions.py  7 passed                              32.2s
  test_frontend_videos.py     1 passed                              25.1s
  test_profiles.py            11 passed                             21.7s
  test_server.py              33 passed                             26.5s
  --------------------------
  total                       82 passed                             78.8s wall, 9 lanes

nothing moved against the previous record

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

## 2026-09-27 - Step 9 - document triage

- [ ] `client/README.md` - Line 15 (`POST /api/profile/likes/import`) is incomplete: it does not say that only the first 50 entries of `likes` are read and the rest are dropped, not rejected. It also does not say that the likes are resolved in one Engine metadata call, so a video the Engine does not know, or holds at or over its error-count threshold, is not imported (ADR-0003). Add both to the existing sentence, which keeps "a video the profile dislikes is skipped. Answers `{imported}`". Line 22 (`POST /api/user-profile/likes` — "resolves a browser-supplied like list; needs no profile.") needs to say how: it reads at most the first 50 `{uuid, host}` entries and resolves them in one Engine metadata call. It answers `likes` in submitted order, with duplicates removed, and leaves out any video the Engine does not know or holds at or over its error threshold. An empty or fully malformed list answers `{likes: []}`. Nowhere is the 50-entry cap on the `/recommendations`/`/videos/similar` `likes` list stated. The nearest place is line 26, next to the keyed-likes sentence: say that a keyless body's `likes` are cut to their first 50 before being forwarded. Lines 30 and 37-39 stay accurate, because `/internal/videos/resolve` is still used by user actions and block-add.
- [ ] `engine/server/README.md` - Line 11 ("`/internal/videos/metadata` internal metadata batch lookup for Client likes/profile.") is now incomplete. It should say:
- entries are `{video_id, instance_domain}` or `{video_uuid, instance_domain}`, and both forms can be mixed in one body;
- an entry with a non-empty `video_id` is treated as the id form;
- the uuid match is exact;
- all entries are answered under a single `db_lock` hold, one row per video, in the order of the first entry that matches it;
- when several videos share a `(video_uuid, instance_domain)`, the lowest `video_id` wins;
- videos at or over the error-count threshold, and unembedded videos, are left out for both forms.

Also add to line 12 (`/internal/dislikes/centroids`) that it takes only `video_id` entries. Line 10 (resolve) is unchanged and still accurate.
- [ ] `docs/project/adr/0003-metadata-endpoint-accepts-uuid-entries.md` - The Decision matches what was built: both entry forms, one lock hold, the likes page and import on one call, the resolve loop removed, and `MAX_CLIENT_LIKES = 50` on all three sites, with extra entries dropped. The existing error-threshold consequence is also right. Consequences is missing two differences from the old resolve path that the build delivered and the operator approved. Add them as bullets, stated as current behaviour:
1. When several videos share one `(video_uuid, instance_domain)`, the one with the lowest `video_id` among those that pass the error filter is used (`fetch_metadata_by_uuids`).
2. There is no check on the embedding blob, so a video whose embedding blob is empty or does not match `embedding_dim` is still shown on the likes page and still imported.
- [ ] `docs/project/issues/03-batch-like-resolution.md` - Issue 03 is delivered. At harvest on main:
- set the `Status:` line to `bug, complete`;
- add a delivery comment covering what was delivered: one `/internal/videos/metadata` call per likes-page or import request under one `db_lock` hold, `resolve_videos_by_uuid_host` removed, and `MAX_CLIENT_LIKES` 200 → 50;
- move the file to `docs/project/issues/archive/`, per `docs/project/triage-labels.md`.
- [ ] `docs/project/plans/14-batch-like-resolution.md` - At harvest on main, archive it together with `16-14-batch-like-resolution.md` and `16-14-batch-like-resolution.record.md` in `docs/project/plans/archive/`. Its text needs no correction beyond what the 16-14 entry below lists.
- [ ] `docs/project/plans/16-14-batch-like-resolution.md` - The Step 5 checklist lists this under plan 14, but its corrections belong here. Before it is archived, fix these in the plan text:
1. **The "Missing index" risk is wrong.** `idx_videos_uuid_instance ON videos (video_uuid, instance_domain)` exists (`engine/server/data/videos.py:21-22`) and is created on every Engine start.
2. **The test pattern cites `test_db.py`.** The handler tests follow the `ENGINE_PY` child used by `test_internal_events.py`/`test_similar.py`, and the data-layer tests run in-process.
3. **The files lists name test files that were never created.** These are `tests/tmp/test_metadata_uuid_entries.py` and `tests/tmp/test_client_like_batching.py`. The checkpoints landed as `tests/tmp/test_14_batch_like_resolution_phase{1..4}.py`.
4. **Phase 1's description is out of date after the refactor.** It describes a hand-written row builder. `_select_metadata` returns `dict(row)`, and the handler imports the shared public `uuid_key` from `data.metadata`.

Out of scope:
_none - this build changes no documented behaviour._

ADR conflicts: none

## 2026-09-27 - Step 9 - Update documentation

- [x] `client/README.md` - updated: I added the 50-entry cap and the single Engine metadata call to the two browser-likes endpoints in `client/README.md`, and the cap to the feed-proxy `likes` note.
- [x] `engine/server/README.md` - updated: `engine/server/README.md`: the `/internal/videos/metadata` entry now describes both entry forms and how they are answered, and the `/internal/dislikes/centroids` entry says it takes id-form entries only.
- [x] `docs/project/adr/0003-metadata-endpoint-accepts-uuid-entries.md` - updated: I added two bullets to the ADR-0003 Consequences for the two approved differences from the old resolve path: the lowest-`video_id` tie-break, and no embedding-blob check.
- [x] `docs/project/issues/03-batch-like-resolution.md` - updated: Issue 03 is now `bug, complete` and has a delivery comment, but I couldn't move it to `issues/archive/` because I have no delete or move tool.
- [x] `docs/project/plans/14-batch-like-resolution.md` - updated: No edit: plan 14 needs no text correction, and archiving it is a harvest-time move on main.
- [x] `docs/project/plans/16-14-batch-like-resolution.md` - updated: I made the four listed corrections to the plan text of `docs/project/plans/16-14-batch-like-resolution.md` and checked each against the worktree code.

**Updated but not named by the Step 3 inventory.** docs/project/plans/16-14-batch-like-resolution.md

**Other files that had to be touched.** none

**ADR conflicts.** none

### `client/README.md`

<changes>
I added the 50-entry cap and the single Engine metadata call to the two browser-likes endpoints in `client/README.md`, and the cap to the feed-proxy `likes` note.

- **Line 15 (`POST /api/profile/likes/import`):** says that only the first 50 `likes` entries are read and the rest are dropped, not rejected. The likes are resolved in one `/internal/videos/metadata` call, so a video the Engine does not know, or holds at or over its error-count threshold, is not imported (ADR-0003). The disliked-video skip and the `{imported}` answer stay as they were.
- **Line 22 (`POST /api/user-profile/likes`):**
  - States the body shape `{likes: [{uuid, host}]}` and that at most the first 50 entries are resolved, in one metadata call.
  - It answers `{likes, updatedAt}`, in submitted order with duplicates removed. Unknown videos and videos at or over the error threshold are left out.
  - An empty or fully malformed list answers `{likes: []}` without calling the Engine.
  - It points to `engine/server/README.md` for how the Engine matches entries, and does not restate that.
- **Line 26 (keyed-likes sentence):** a keyless `/recommendations` or `/videos/similar` body has its `likes` cut to the first 50 entries before they are forwarded. Entries past the 50th are dropped, not rejected.

I checked all of this against the worktree code:
- `MAX_CLIENT_LIKES = 50` in `server.py:52`.
- The proxy trim at `server.py:493`.
- `_handle_likes_import` at `:872`.
- `_handle_user_profile_likes_from_client` at `:1012`.
- `_parse_client_likes`, which cuts the raw list before skipping malformed entries.
- `fetch_metadata_for_entries`, which returns `[]` for an empty list without making an HTTP call.

Lines 30 and 37–39 are unchanged, since `/internal/videos/resolve` is still used by user actions and block-add.
</changes>

<not_on_checklist>
none
</not_on_checklist>

### `engine/server/README.md`

<changes>
`engine/server/README.md`: the `/internal/videos/metadata` entry now describes both entry forms and how they are answered, and the `/internal/dislikes/centroids` entry says it takes id-form entries only.

- **`/internal/videos/metadata`:**
  - Entries can be `{video_id, instance_domain}` or `{video_uuid, instance_domain}`, and one body can mix both.
  - An entry with a non-empty `video_id` is treated as the id form.
  - The uuid match is exact and case-sensitive. When several videos share a `(video_uuid, instance_domain)`, the lowest `video_id` wins.
  - All entries are answered under one `db_lock` hold. There is one row per video, in the order of the first entry that matches it.
  - Unembedded videos are never returned.
  - I checked all of this against `internal_client_reads.py` and `data/metadata.py`.
- **Error threshold (differs from the checklist):** the checklist says videos at or over the error-count threshold are left out for both forms. The code does that fully only for uuid entries. In `fetch_metadata_by_ids` the conditions are deliberately left without parentheses (commented as Open item A, option 1), so for id entries the threshold applies only to the last pair of each 450-entry chunk. The README states that current behaviour and does not repeat the "both forms" claim. You may want this recorded as a known issue or fixed separately. The same point may affect the wording of the ADR-0003 consequence, which is written in another turn.
- **`/internal/dislikes/centroids`:** adds "It takes only `{video_id, instance_domain}` entries." I also rejoined its hard-wrapped lines into one line.
- The resolve line is unchanged.
</changes>

<not_on_checklist>
none
</not_on_checklist>

### `docs/project/adr/0003-metadata-endpoint-accepts-uuid-entries.md`

<changes>
I added two bullets to the ADR-0003 Consequences for the two approved differences from the old resolve path: the lowest-`video_id` tie-break, and no embedding-blob check.

- **Tie-break:** when several videos share one `(video_uuid, instance_domain)`, a uuid entry gets the video with the lowest `video_id` among those that pass the error-count filter (`fetch_metadata_by_uuids`). I checked this in `engine/server/data/metadata.py:138-160`: the threshold is applied in SQL and the lowest `video_id` is kept per `uuid_key`.
- **No blob check:** a video whose embedding blob is empty or doesn't match its `embedding_dim` still shows on the likes page and is still imported. I checked `_select_metadata`: it only inner-joins `video_embeddings` and never looks at the blob.
- **Resolve bullet:** it now reads "user actions and block-add". The code confirms both still call `resolve_video_seed`, in `_handle_user_action` and `_handle_block_add` in `client/backend/server.py`.

I left the Context and Decision sections and the existing error-threshold bullet as they were; they match what was built.
</changes>

<not_on_checklist>
none
</not_on_checklist>

### `docs/project/issues/03-batch-like-resolution.md`

<changes>
Issue 03 is now `bug, complete` and has a delivery comment, but I couldn't move it to `issues/archive/` because I have no delete or move tool.

- **Status line:** changed from `bug, ready-for-agent` to `bug, complete`.
- **Delivery comment:** added under Comments, after the triage decisions. It follows the `**Delivered** by …` format in `archive/05-raw-event-retention.md` and points at the archived locations of `16-14-batch-like-resolution.md` and `14-batch-like-resolution.md`. It covers:
  - `/internal/videos/metadata` parses its entries with `_parse_metadata_entries`, which accepts both entry forms in one body. It answers them under one `db_lock` hold through `fetch_metadata_by_ids` and `fetch_metadata_by_uuids`, and returns each video once, at its first matching entry.
  - `/internal/dislikes/centroids` still uses `_parse_entries`, so it takes only `video_id` entries.
  - The likes page and likes import each make one `fetch_metadata_for_entries` call. Import records a like from each returned row the profile has not disliked.
  - `resolve_videos_by_uuid_host` is removed. `resolve_video_seed` and `/internal/videos/resolve` stay for user actions and block-add.
  - `MAX_CLIENT_LIKES` is 50 at all three places that use it.
  - For the two ways this differs from the old resolve (lowest `video_id` wins; no embedding-blob check), it points to ADR-0003's Consequences rather than repeating them.
- **Checked against the worktree code:** the constant and where it is used, the removed function, the new parser, the uuid fetch and the shared `uuid_key`, and the single lock hold in the handler.
- **Not changed:** the Problem, Proposed solution, Agent Brief and acceptance-criteria checkboxes. They stay as the issue's original record, as in the other archived issues.
- **Still to do at harvest (needs a shell):** move this file to `docs/project/issues/archive/03-batch-like-resolution.md` with `git mv`. The comment's plan links assume both plans are archived in the same harvest.
</changes>

<not_on_checklist>
none
</not_on_checklist>

### `docs/project/plans/14-batch-like-resolution.md`

<changes>
No edit: plan 14 needs no text correction, and archiving it is a harvest-time move on main.

- **Text left as is.** The checklist entry says this plan needs no correction beyond what the 16-14 entry lists. The 16-14 corrections (the "Missing index" risk, the test pattern, the test files that were never created, the Phase 1 row-builder description) all concern `docs/project/plans/16-14-batch-like-resolution.md`. None of them is in this file. This file holds the requirements and the high-level plan the build started from. Its Approach, Alternatives, Risks and Tradeoffs agree with what was delivered:
  - its own parser for metadata, with centroids left on `_parse_entries`;
  - a chunked uuid-keyed lookup beside `fetch_metadata_by_ids`;
  - one `db_lock` hold;
  - `resolve_videos_by_uuid_host` removed;
  - `MAX_CLIENT_LIKES` 200 → 50, with extra entries dropped.
- **Line numbers.** The line numbers in Batch context (`:49`, `:446`, `:837-843`, `:970-980`) describe the tree when the plan was written. The plan already says they drift and that functions should be found by name.
- **Archiving not done here.** Moving this file to `docs/project/plans/archive/` together with `16-14-batch-like-resolution.md` and `16-14-batch-like-resolution.record.md` happens at harvest on main, not in this worktree. I have no move tool, so it stays as a harvest action.
</changes>

<not_on_checklist>
none
</not_on_checklist>

### `docs/project/plans/16-14-batch-like-resolution.md`

<changes>
I made the four listed corrections to the plan text of `docs/project/plans/16-14-batch-like-resolution.md` and checked each against the worktree code.

**The file may be overwritten.** Its header says it is "rendered by the `dev-flow` workflow from its run state. Every edit here is overwritten on the next step". If the harvest or archive step renders it again, these edits will be lost unless the same corrections also go into the run state or `16-14-batch-like-resolution.record.md`.

1. **Missing index (High-level plan, Risks).** I replaced the "Missing index" bullet with an "Index" bullet. It says that `idx_videos_uuid_instance ON videos (video_uuid, instance_domain)` is defined at `engine/server/data/videos.py:21-22`. `ensure_video_indexes` creates it on every Engine start (`engine/server/api/server.py:337`). A temp-DB test that does not call `ensure_video_indexes` runs without the index, which does not affect correctness.
2. **Test pattern (High-level plan, Tests).** I dropped the `test_db.py` citation, since it runs its child with `sys.executable`. The paragraph now says the data-layer checks run in-process because `data.metadata` imports no numpy. The handler checks run in a `conftest.ENGINE_PY -c` child, following `test_internal_events.py` and `test_similar.py`.
3. **Test files that were never created.** Everywhere the plan named `tests/tmp/test_metadata_uuid_entries.py` or `tests/tmp/test_client_like_batching.py`, it now names the checkpoints that actually exist, `tests/tmp/test_14_batch_like_resolution_phase{1..4}.py`. I found all four on disk. The changed places are:
   - the module map (now four rows, one per checkpoint);
   - the two Section 5 test headings;
   - each phase's "Files touched" line;
   - each phase's "Outcome" subsection, where the "not created / doesn't exist" notes are gone;
   - the phase 4 checkpoint seam, which no longer says it shares phase 3's test file: it builds its own stand-in Engine.
4. **The refactor.** These places now match the code as it stands:
   - **Phase 1 Outcome:** `_select_metadata` returns `[dict(row) for row in rows]`, which gives the same 29 keys in SELECT order. It no longer mentions a hand-written row builder. `fetch_metadata_by_uuids` keys its rows with the public `uuid_key`.
   - **Phase 2 Outcome:** line 9 imports `fetch_metadata_by_ids, fetch_metadata_by_uuids, uuid_key`. There are now two new helpers, not three, because the private `_uuid_key` is gone. `_parse_entries` does its string checks through `_stripped` and behaves as before.
   - **Module map:** its metadata.py and handler rows say the same.

**Stale but not on the list, so left alone:**
- The High-level plan and Draft §1 describe the uuid SQL as a row-value `(v.video_uuid, v.instance_domain) IN (...)` with deduplication before chunking. The built code uses a parenthesised OR of `(v.video_uuid = ? AND v.instance_domain = ?)` and relies on the handler parser to deduplicate. The Phase 1 Outcome already describes this correctly.
- The Phase 3 Outcome says the "early 200 when nothing parses" in `_handle_user_profile_likes_from_client` is unchanged. The Step 8 refactor removed that early return: the empty case now goes through `fetch_metadata_for_entries`'s own short-circuit, and the response is the same.
</changes>

<not_on_checklist>
none
</not_on_checklist>

