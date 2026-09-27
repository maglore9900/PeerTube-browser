# 33-metadata-id-threshold-precedence

_Rendered by the `dev-flow` workflow from its run state. Every edit here is overwritten on the next step; the evidence each gate turned on is in `docs/project/plans/01-33-metadata-id-threshold-precedence.record.md`._

## Requirements

### Purpose

Fix issue `docs/project/issues/33-metadata-id-threshold-precedence.md` (category bug). `fetch_metadata_by_ids` (`engine/server/data/metadata.py:110`) is meant to exclude every video whose `error_count` is at or over the Engine's error threshold (`VIDEO_ERROR_THRESHOLD`, default 3, `engine/server/api/server_config.py:387`, so the filter is on in every deployment). The threshold exists to keep videos the crawler repeatedly failed to reach out of what visitors see. Today, for any batch of more than one id entry, it excludes an errored video only when that video is the last pair of its 450-entry chunk. After this build, the id lookup filters every entry, exactly as the uuid lookup beside it already does. The issue listed the parenthesis fix as "not chosen". The operator has now chosen it, for every id caller, and accepts the consequences listed below.

### Current behaviour (verified in the worktree)

- `engine/server/data/metadata.py:119-129`: for each 450-entry chunk, `fetch_metadata_by_ids` builds `conditions = " OR ".join(["(v.video_id = ? AND v.instance_domain = ?)"] * len(batch))` and passes `conditions` to `_select_metadata` unparenthesised (line 128). Line 120 carries the comment `# Left unparenthesised on purpose: the threshold binds only to the last pair of each chunk (Open item A, option 1).`
- `_select_metadata` (`metadata.py:163-218`) renders `WHERE {conditions}` followed by `{error_clause}`. `{error_clause}` is `AND (v.error_count IS NULL OR v.error_count < ?)` and is added only when `error_threshold is not None and error_threshold > 0`. `AND` binds tighter than `OR`, so the clause attaches only to the chunk's final pair.
- `fetch_metadata_by_uuids` (`metadata.py:138-160`) passes `f"({conditions})"` (line 155), so its threshold applies to every pair.
- Callers of `fetch_metadata_by_ids`:
  - `engine/server/data/similarity_candidates.py:170-179` (`_build_rows`) resolves cached and ANN similar and up-next candidates, with and without `server.db_lock`.
  - `engine/server/api/handlers/internal_client_reads.py:157` answers id-form entries of `/internal/videos/metadata`. Its Client callers are:
    - `_handle_user_profile_likes_get` (`client/backend/server.py:1017-1032`) sends `fetch_recent_likes` rows (`video_id, video_uuid, instance_domain, updated_at`, up to `MAX_LIKES = 100`). They carry a non-empty `video_id`, so they are answered as id-form entries. The issue does not name this caller.
    - Block-add (`client/backend/server.py:969`) sends a single id entry. The filter already works for it, because its only pair is also the last.
  - The keyless likes page (`server.py:1034-1047`) and likes import (`server.py:910`) send uuid-form entries and are already filtered correctly.
- `tests/active/test_metadata.py`:
  - The module docstring has a "Known limitation, left unasserted on purpose" paragraph (line 8).
  - `test_both_lookups_return_every_healthy_video_across_the_450_entry_chunk_boundary` (lines 153-164) builds 460 bulk videos with `c455` errored (`error_count` 5), which sits in chunk 2 and is not its last pair.
  - On the id path that test asserts only that the healthy keys are a subset of the result (`<=`, line 160) and that c452's row is right (line 161), with a comment at line 159 explaining why c455 is not asserted. The uuid path asserts the exact healthy set (line 163).
- `engine/server/README.md:11` ends with: "Uuid entries leave out videos at or over the error-count threshold; for id entries the threshold applies only to the last pair of each 450-entry chunk."

### R1 — Engine: the id lookup filters every entry

- In `fetch_metadata_by_ids`, the chunk's OR of pairs is passed to `_select_metadata` wrapped in parentheses (`f"({conditions})"`), matching `fetch_metadata_by_uuids` line 155.
- The comment at `metadata.py:120` ("Left unparenthesised on purpose ... Open item A, option 1") is removed.
- Result: with `error_threshold > 0`, every id entry in every chunk whose video has `error_count >= error_threshold` is excluded, and videos with `error_count` NULL or below the threshold are returned as before. With `error_threshold` None or ≤ 0, the output is unchanged.
- Nothing else changes: the function signature `(conn, entries, error_threshold=None)`, the `if not entries: return {}` early return, 450-entry chunking via `_chunk`, parameter order (pairs first, threshold last and once per chunk), reading only `entry.get("video_id")` and `entry.get("instance_domain") or ""`, keying on `like_key(row)`, and the 29-key row dict.
- `_select_metadata`, `fetch_metadata_by_uuids`, `uuid_key`, `_chunk` and the rowid-keyed `fetch_metadata` are not edited.

### R2 — Callers: accepted consequences (no caller code changes)

- Similar and up-next (`similarity_candidates._build_rows`): errored candidates no longer come back, so those lists can be shorter than today (the operator accepts this; related to issue 09, similar pools being small).
- Keyed profile likes page (`GET` via `_handle_user_profile_likes_get`): a liked video at or over the threshold is no longer shown. The stored like in `users.db` is untouched; only the displayed row is omitted. This makes the keyed likes page agree with the keyless likes page and likes import, which already filter (ADR-0003).
- Block-add: unchanged (single entry, already filtered).
- `/internal/videos/metadata` response shape, ordering and dedup rules are unchanged; only which id-form rows pass the threshold changes.
- No caller (Engine or Client) is edited, and no caller gets a no-threshold path.

### R3 — Tests

- In `tests/active/test_metadata.py`, `test_both_lookups_return_every_healthy_video_across_the_450_entry_chunk_boundary` asserts the id path the way it asserts the uuid path. The id lookup returns exactly the healthy keys (`{f"c{i:03d}::bulk.example"}` for every `i != 455`), so c455 is absent, and `by_id["c452::bulk.example"] == _row(*_bulk(452))` still holds. The exact-set assertion replaces the subset (`<=`) assertion.
- The in-test comment at line 159 is removed.
- The module docstring's "Known limitation, left unasserted on purpose" paragraph (line 8) is removed. The last bullet (line 6) is reworded so it says both lookups drop the errored video in the second chunk.
- The test must fail against today's code (c455 comes back by id) and pass after R1.
- The rest of `test_metadata.py` stays as it is and must stay green.

### R4 — Docs

- `engine/server/README.md:11`: replace the final sentence with one stating that videos at or over the error-count threshold are left out for both entry forms.
- `docs/project/adr/0003-metadata-endpoint-accepts-uuid-entries.md`: no change needed. Its consequences speak only of the uuid path and import.
- At harvest: set issue 33's `Status:` to `bug, complete`, add a delivery comment, and move it to `docs/project/issues/archive/` (per `docs/project/triage-labels.md`).

### Acceptance criteria

- `fetch_metadata_by_ids` at threshold 3 over the 460-video bulk set returns exactly the 459 healthy videos. c455 is absent and c452's full row is present.
- At threshold None, an errored video requested by id is returned (unchanged behaviour). The existing tests exercise the None case only on the uuid path, so this case can be asserted in the chunk test or left to the unchanged `_select_metadata` rule.
- The comment at `metadata.py:120` and the known-limitation text in `test_metadata.py` and `engine/server/README.md` are gone.
- The full suite is green, including the live-Engine files that reach this function indirectly (`tests/active/test_similar.py`, `test_server.py`, `test_blocks.py`, `test_profiles.py`).

### Testing constraints

- Run `validate_tests.py` from `/home/enduser/code/PeerTube-browser/.worktrees/33` (this worktree's `project_dir`). The trees are: active `tests/active`, working `tests/tmp`, archive `tests/archive`, record `tests/last_test_validation.json`, output `tests/last_test_output.txt`.
- `tests/active/test_metadata.py` runs in-process: `data.metadata` imports no numpy, and it uses its own temp SQLite fixture.
- Run each Engine-backed test file in its own `validate_tests.py` invocation, because the Engine's per-IP rate limit is shared.
- Live-Engine tests read the shared `whitelist.db`. A similar or likes test whose expectations assumed an errored video could appear by id would now fail. None is known, but watch `test_similar.py` and `test_profiles.py`.

### Baseline suite state

The pre-build baseline run exited with code 0, variant false: the suite is green before the build starts.

### Consistency constraints

- The code change is a one-line edit in the style of `fetch_metadata_by_uuids`. No new function, flag, dependency or module.
- Match the file's style. Do not softwrap: one statement or comment per line, one paragraph per line in markdown.

### Out of scope

- A no-threshold or opt-out path for any caller, including the profile likes GET.
- Changing `VIDEO_ERROR_THRESHOLD` or the `error_threshold > 0` rule.
- `fetch_metadata` (rowid lookup) and the other row sources (`random_videos.py`, `search.py`).
- Measuring how often errored videos reached similar lists, and issue 09 (similar pool size).
- Archived plan/record files under `docs/project/plans/archive/`, which are historical and not edited.

## High-level plan

### Approach

The defect is one of operator precedence in the SQL that `fetch_metadata_by_ids` builds. `_select_metadata` renders `WHERE {conditions} {error_clause}`. The id path passes a bare `pair OR pair OR ... OR pair`, so the appended `AND (error_count IS NULL OR error_count < ?)` binds only to the final pair of each 450-entry chunk. The fix is to do what `fetch_metadata_by_uuids` already does at `metadata.py:155` and hand `_select_metadata` the chunk's OR of pairs wrapped in parentheses. The WHERE then reads `(any pair) AND (under threshold)`, and the threshold applies to every entry in every chunk. The comment at `metadata.py:120` that justified leaving it unparenthesised is deleted in the same edit. Nothing else in the function moves: not the signature, the early return, the chunking, the order of the parameters (pairs, then the threshold once per chunk, which parenthesising does not change), the entry fields read, the `like_key` keying, or the 29-key row. `_select_metadata`, the uuid lookup, `uuid_key`, `_chunk` and `fetch_metadata` are not touched.

How this meets each requirement. R1 is that one-line edit plus deleting the comment. When `error_threshold` is None or ≤ 0, `error_clause` is empty, so the only change to the WHERE is a redundant pair of parentheses and the result is identical. When the threshold is > 0, a video is dropped exactly when `error_count >= threshold`, and a NULL or lower count still passes. R2 needs no caller edits. `similarity_candidates._build_rows` and `/internal/videos/metadata` keep calling the function unchanged and simply receive fewer rows when some of the videos are errored. The endpoint's response shape, ordering and dedup are built from whatever the lookup returns, so they are unchanged. Block-add sends one entry, and a lone pair is also the last pair of its chunk, so its behaviour is identical. For R3, the chunk-boundary test in `tests/active/test_metadata.py` changes its id-path assertion from a subset check (`<=`) to an exact-set check. It asserts that the id lookup returns exactly the 459 healthy `c###::bulk.example` keys, with c455 absent, and it keeps the c452 full-row check. The explanatory comment at line 159 goes. The module docstring loses its "Known limitation" paragraph, and the last bullet is reworded to say both lookups return every healthy video and drop the errored one in the second chunk. To cover the None acceptance case explicitly, I would add one more assertion to that same test: the id lookup with the threshold set to None returns c455's row. It costs one line, runs on the same fixture, and pins down that the parentheses did not change the threshold-off case. The criteria allow leaving that case to `_select_metadata`, and they also allow asserting it here. I choose to assert it. The new exact-set assertion fails on today's code, because c455 is at position 5 of the 10-entry second chunk rather than its last, so it comes back by id. It passes after R1. For R4, the final sentence of `engine/server/README.md:11` becomes a single sentence saying that videos at or over the error-count threshold are left out for both entry forms. ADR-0003 stays as it is. At harvest, issue 33 gets `Status: bug, complete` and a delivery comment, and moves to `docs/project/issues/archive/`.

Verification order: first `test_metadata.py` in-process, which must be red before the edit and green after. Then each Engine-backed file in its own `validate_tests.py` invocation from the worktree: `test_similar.py`, `test_server.py`, `test_blocks.py`, `test_profiles.py`, and `test_internal_client_reads.py`, which drives the handler with a threshold. Then the full suite.

### Alternatives considered

- Parenthesise inside `_select_metadata` (render `WHERE ({conditions})`). This fixes both callers at the source and prevents the bug from coming back through a future caller. I rejected it because the requirements forbid editing `_select_metadata`, and because it would double-wrap the uuid path. The one-line edit in the uuid lookup's style is the settled choice. Moving the parentheses into `_select_metadata` later would be a harmless hardening if a third caller ever appears.
- Filter in Python after the query (drop rows whose `error_count` is at or over the threshold). I rejected it because the row dict does not carry `error_count` (it is not among the 29 keys), so this would widen the SELECT or need a second query. It also duplicates a rule that already lives in SQL.
- Keep today's behaviour and only document it, or give the likes GET a no-threshold path. This was the issue's option 1. The operator has explicitly moved away from it, and an opt-out path is out of scope.
- Rewrite the id match as `(video_id, instance_domain) IN (VALUES ...)` or as a join against a temp table. That changes the query shape for no gain over one pair of parentheses. Rejected as speculative.

### Risks and gotchas

- Behaviour visible to users changes in two places, as the operator accepted. Similar and up-next lists can shrink when errored candidates were previously slipping through. The keyed profile likes page stops showing liked videos that are at or over the threshold, although the stored likes in `users.db` are untouched. The likes page could therefore show fewer than the stored count, and a video comes back once its `error_count` drops below the threshold.
- Live-Engine tests read the shared `whitelist.db`. I checked `tests/active`: the tests that pick videos for blocks, dislikes, reactions and profiles select with `WHERE v.error_count = 0`, so their chosen videos are healthy and unaffected. `test_internal_client_reads.py` asserts that an errored `e1` comes back by id only with the threshold set to None, and parentheses do not change that. `test_similar.py` does not pin down errored candidates, but if it asserts a minimum list length, a smaller pool could affect it. That is the file to watch, as the constraints say.
- SQLite's parameter limit is unaffected: the chunk still binds 900 pair parameters plus one threshold, which is well under 999. The query plan is unaffected too, because the parentheses only restate the intended precedence.

### Tradeoffs the operator accepts

- There is no way to see an errored video by id through these callers, including a user's own likes. That is the consistency the operator chose, in line with ADR-0003's uuid path.
- The fix is local to the id lookup rather than hardening `_select_metadata`. A future caller that passes a bare OR could reintroduce the same bug. This is a deliberate simplification to keep the change to one line. The upgrade path is to parenthesise inside `_select_metadata` if another caller appears.

## Impacts

<impacts>
<impact path="engine/server/data/metadata.py" element="fetch_metadata_by_ids (lines 110-130): the one-line edit at :128 and the comment at :120">
**What changes.** Line 128 changes from `_select_metadata(conn, conditions, params, error_threshold)` to `_select_metadata(conn, f"({conditions})", params, error_threshold)`, the same form as `fetch_metadata_by_uuids` at :155. The comment at :120 (`# Left unparenthesised on purpose ... (Open item A, option 1).`) is deleted. Everything else stays as it was, and I confirmed each item in the file: the signature `(conn, entries, error_threshold=None)`, `if not entries: return {}` (:116-117), `_chunk(entries, 450)` (:119), the multi-line `" OR ".join(...)` (:121-123), and params built from `entry.get("video_id")` / `entry.get("instance_domain") or ""` (:124-127). Rows are still keyed by `like_key(row)` (:129).

**What depends on it.** Two direct callers: `similarity_candidates._build_rows` (:170, :175) and `handle_internal_videos_metadata` (`internal_client_reads.py:157`). The test file `tests/active/test_metadata.py` (:106, :150, :158) calls it directly.

**Regression risk: low for the code, medium for behaviour.**
- The parameter count and order do not change: 2 × batch pairs, then the threshold once, appended inside `_select_metadata`. Worst case is 900 + 1 = 901 parameters, under SQLite's 999.
- With `error_threshold` None or ≤ 0 the only change is a redundant pair of parentheses, so the result is identical.
- The one real risk is a typo in the f-string, for example `f"{conditions}"`, which would leave the bug in place silently. The exact-set assertion in test_metadata.py catches that.
- Style: `f"({conditions})"` inline, matching :155. The multi-line `join` is left as it is.
</impact>
<impact path="engine/server/data/metadata.py" element="_select_metadata (lines 163-218)">
**What changes.** Nothing. It renders `WHERE {conditions}` then `{error_clause}` (:212-213). The error clause `AND (v.error_count IS NULL OR v.error_count < ?)` is added only when `error_threshold is not None and error_threshold > 0` (:172-174). It works on a copy of params (:170) and returns `[dict(row) for row in rows]` (:218), the 29-key row.

**What depends on it.** Both id and uuid lookups. After this change both hand it a parenthesised fragment, so it never sees a bare OR again.

**Regression risk: none.** It must stay unedited, because wrapping here would double-wrap both callers; that is harmless, but the requirements forbid it. The hardening path (a third caller passing a bare OR) remains open, as the plan's accepted tradeoff says.
</impact>
<impact path="engine/server/data/metadata.py" element="fetch_metadata_by_uuids (138-160), uuid_key (133-135), _chunk (105-107), fetch_metadata (11-102)">
**What changes.** Nothing.
- `fetch_metadata_by_uuids` is the style reference at :155.
- `fetch_metadata` (the rowid lookup) builds its own `WHERE e.rowid IN (...) {error_clause}` (:65-66). A single `IN` term binds correctly, so the rowid path already filters every row. That matters for the similar-list analysis below.

**Regression risk: none** if the diff stays at :120 and :128.
</impact>
<impact path="engine/server/data/similarity_candidates.py" element="_build_rows (155-214) and get_similar_candidates (37-105)">
**What changes.** No code edit. `_build_rows` calls `fetch_metadata_by_ids` with `server.video_error_threshold`, with the lock (:174-179) and without it (:169-172). It then walks `entries` and skips any entry with no metadata row (:195-197). After the fix, every candidate at or over the threshold is skipped, not only the last pair of each chunk.

**Precision the plan lacks: where errored candidates actually come from.** ANN-computed entries are already filtered. `data/ann.py:45-49` resolves ANN rowids through the rowid `fetch_metadata` with the threshold, and builds its items only from rows that came back (:64-66). So a freshly computed pool holds no errored video. The fix newly drops only candidates read from the similarity cache (`_read_cache`, :108-122) whose video is now at or over the threshold. That covers:
- entries written by `engine/server/db/jobs/precompute-similar-ann.py`, which has no `error_count` / threshold filter (grep found none);
- entries cached before the video's `error_count` rose.

**Consequence: pages can come back short.** `read_cached_similarities` treats a cache as a hit only when `len(cached) == limit` under `require_full` (`similarity_cache_manager.py:61`). After a hit, `_build_rows` filters with no ANN refill. So a cached pool containing errored videos now yields fewer than `limit` rows, rather than a full page that includes errored ones.

**What depends on it.**
- Up-next / similar: `handlers/similar.py:774`.
- The home feed's like-seeded layers, through `deps.get_similar_candidates`, which `api/server.py:392` wires to this function: `recommendations/sources/cached_similar_from_likes.py:106` and `ann_similar_from_likes.py:74`.

**Regression risk: medium.** The behaviour change is accepted. The plan names similar and up-next but not the home feed layers, which see the same shrink. The size of the effect depends on how many errored videos sit in `similarity-cache.db`. Neither `similarity-cache.db` nor `whitelist.db` shows up under `engine/server/db/` in this worktree (Glob found only `random-cache.db`), so I could not tell whether the test Engine's cache is empty, starting fresh and filled by the filtered ANN path, or a symlink to main's precomputed cache. That is unconfirmed.
</impact>
<impact path="engine/server/data/ann.py" element="compute_similar_items (lines ~20-85)">
**What changes.** Nothing. It filters at compute time through `fetch_metadata(..., error_threshold=...)` (:45-49), and items come only from returned metadata (:64-66).

**Why it matters.** It explains why on-demand (ANN) similar pools are unaffected by the fix, and why the effect is confined to cached pools.

**Regression risk: none.**
</impact>
<impact path="engine/server/db/jobs/precompute-similar-ann.py" element="similarity cache precompute (whole job)">
**What changes.** Nothing.

**Why it matters.** This job fills `similarity-cache.db` (`UPDATER_WORKER.md:28,53`), and a grep for `error_count`/`error_threshold` in it finds nothing. So cached pools can hold errored videos, and after the fix `_build_rows` is their only filter. This is the path by which errored videos reached similar/up-next lists in production.

**Regression risk: none to the file.** It is the mechanism behind the accepted shrink. Filtering at precompute time would be the natural follow-up if short cached pages become a problem; that is out of scope, but related to issues 09, 24 and 25.
</impact>
<impact path="engine/server/api/handlers/similar.py" element="up-next/similar path, get_similar_candidates call at :774">
**What changes.** No edit. `similar_per_like` rows are requested (:772-774). Rows lost to the threshold are not refilled before `score_and_rank_list` and the `exclude` filter (:790-796). Up-next pages served from a cached pool with errored members come back shorter.

**Regression risk: low, accepted behaviour.** The live tests below that demand exact page sizes are where this would show.
</impact>
<impact path="engine/server/api/recommendations/sources/cached_similar_from_likes.py" element="get_similar_candidates call at :106 (home exploit-cache layer)">
**What changes.** No edit. Per-like candidates can be fewer, so the layer's pool is smaller. The layer shuffles and does not refill (:119-126).

**What depends on it.** The home feed mix. `LAYER_PARAMS.md:70` already notes that "if the source returns fewer candidates, `pool_size` will not expand the pool".

**Regression risk: low.** The plan does not mention it. It feeds `tests/active/test_similar.py::test_home_excluding_a_previous_page...` (PLAIN_FLOOR 45) and `test_home_and_random_return_more_than_the_default_page...`.
</impact>
<impact path="engine/server/api/recommendations/sources/ann_similar_from_likes.py" element="get_similar_candidates call at :74">
**What changes.** No edit. Same effect as the cached layer when the candidate call hits the cache. The layer is wired through `api/server.py:392`.

**Regression risk: low.**
</impact>
<impact path="engine/server/api/handlers/internal_client_reads.py" element="handle_internal_videos_metadata (130-172)">
**What changes.** No edit. Id-form entries go to `fetch_metadata_by_ids(server.db, id_entries, error_threshold=error_threshold)` (:157), where the threshold is `getattr(server, "video_error_threshold", None)` (:152). After the fix, errored videos are absent from `by_id`, so the ordered walk (:164-169) skips those entries.
- The response shape `{"ok", "count", "rows"}`, first-match order, and cross-form dedup (keyed on the returned row, :162-168) are unchanged.
- A video reached by both an id entry and a uuid entry was already dropped on the uuid side. It is now dropped on both sides, consistently.

**What depends on it.** Client callers through `fetch_metadata_for_entries`:
- `server.py:910`, likes import (uuid form);
- `server.py:969`, block-add (one id entry);
- `server.py:1028`, keyed likes GET (id form, up to `MAX_LIKES`);
- `server.py:1043`, keyless likes POST (uuid form).

**Regression risk: low.** Only which id rows pass changes.
</impact>
<impact path="client/backend/server.py" element="_handle_user_profile_likes_get (1017-1032)">
**What changes.** No edit.
- It sends `fetch_recent_likes` rows (they carry a non-empty `video_id`, so they are id form), up to `min(limit, MAX_LIKES)`. It answers `{"user_id", "likes": rows, "updatedAt"}`.
- After the fix, a liked video at or over the threshold is missing from `likes`. The stored like in `users.db` is untouched.
- The page can therefore list fewer rows than the profile holds, and a video reappears once its `error_count` drops below the threshold.

**What depends on it.** `client/frontend/src/data/user-profile.ts:43` (keyed branch) renders `likes` as returned. The built bundle is `client/frontend/dist/assets/user-profile-*.js`.

**Regression risk: low (accepted).** The issue does not name this caller; step 1 records it as an operator-accepted conflict. The live test `tests/active/test_server.py:190-192` asserts the returned set equals the 5 liked videos, which come from search. Search resolves through the rowid `fetch_metadata` with the threshold (`data/search.py:192-196`), so those videos are already under the threshold and the assertion holds.
</impact>
<impact path="client/backend/server.py" element="_handle_block_add (949-985)">
**What changes.** No edit. It resolves the uuid/host with `resolve_video_seed`, which has no error filter, then sends a single id entry to metadata (:969-972). A lone pair is its chunk's last pair, so it was already filtered. An errored video still answers 404 `Video not found in Engine` (:976-979), as before.

**Regression risk: none.** Note the issue cites this at `server.py:954`; it is now :969.
</impact>
<impact path="client/backend/server.py" element="_handle_likes_import (~893-922) and _handle_user_profile_likes_from_client (1034-1047)">
**What changes.** Nothing. Both send uuid-form entries from `_parse_client_likes`, which go through `fetch_metadata_by_uuids` and are already fully filtered.

**Regression risk: none.** Listed to confirm they are outside the change.
</impact>
<impact path="client/frontend/src/data/user-profile.ts" element="fetchUserProfileLikes keyed branch (~:43)">
**What changes.** Nothing. It renders `likes` from the keyed GET, which may now hold fewer rows. The frontend has no count it checks against.

**Regression risk: none.**
</impact>
<impact path="tests/active/test_metadata.py" element="module docstring (lines 1-11) and test_both_lookups_return_every_healthy_video_across_the_450_entry_chunk_boundary (153-164)">
**What changes.**
- **Docstring.** Line 6's last bullet is reworded, for example "both lookups return every healthy video and drop the errored video in the second chunk", plus the new None assertion if that goes into the docstring too. Line 8's "Known limitation, left unasserted on purpose" paragraph and its blank line are removed.
- **In the test:**
  - The comment at :159 is removed.
  - :160 goes from `{...healthy} <= set(by_id)` to an exact equality, in the uuid style at :163. Either `set(by_id) == {f"{_bulk(i)[0]}::{BULK}" for i in healthy}`, or a `{key: row["video_id"]}` dict equality like :163.
  - :161 (the c452 full row) stays.
  - New: an id lookup at `threshold=None` returns c455's row, e.g. `== _row(*_bulk(455))`.

**Design notes.**
- With None there is no error clause, so precedence cannot affect that assertion. It pins "threshold off is unchanged" rather than the fix.
- It is most meaningful run over the full 460 entries, or with c455 not last in its chunk, as :158 builds them. A single-entry call would prove less.
- `BULK_ERRORED = 455` sits at index 5 of the 10-entry second chunk (:47-48). So the exact-set assertion is red on today's code (c455 comes back by id) and green after the edit, which gives the required red-then-green.

**What depends on it.** The other tests in the file are unaffected:
- :104-110: b1 has NULL `error_count`, so it passes `IS NULL`.
- :148-150: no threshold.

It runs in-process: `data.metadata` imports no numpy.

**Regression risk: low.** Match the file's one-line style (no softwrap) and its `_bulk`/`BULK` helpers.
</impact>
<impact path="tests/active/test_internal_client_reads.py" element="test_an_errored_video_s_uuid_entry_is_omitted_only_under_the_threshold (187-191) and module docstring line 5">
**What changes.** No edit is required.
- The `by_id` control sends `[_id("e1"), _id("a1")]` at threshold None and expects `[E1, A1]`. With None there is no clause, so it stays green.
- No test in this file sends id-form entries with an errored video at THRESHOLD. So the handler-level id filter stays unpinned. The fix is still covered, one layer down, by test_metadata.py.

**Optional.** A case `[_id("e1"), _id("a1")]` at THRESHOLD expecting `_rows(A1)` would be red today, because e1 is not the last pair, and green after the fix. Neither the plan nor R3 asks for it.

It runs under `ENGINE_PY` in a child process, not the live Engine.

**Regression risk: none.**
</impact>
<impact path="tests/active/test_dislike_profile.py" element="_seed_and_pair (65-78) and test_an_upnext_page_carrying_a_dislike_centroid... (101-113)">
**What changes.** No edit expected. **The plan's watch list omits this file.** It requests an up-next page with `limit=16` for the seeds "cooking" and "linux" (`SEED_QUERIES`, :19), and asserts `len(plain["rows"]) == 16` (:72) and `len(body["rows"]) == 16` (:108). `test_similar.py:65` records those seeds' pools as measured "19 and 17 deep". If a cached pool for either seed holds errored videos, the cooking pool has only one spare, so filtering them could leave fewer than 16 rows. The test then fails at :72 or :108.

**Regression risk: medium, unconfirmed.** It depends on the contents of the test Engine's `similarity-cache.db`, which I could not inspect. If the cache starts empty and is filled by the filtered ANN path, nothing changes. Run it in its own `validate_tests.py` invocation and watch it.
</impact>
<impact path="tests/active/test_similar.py" element="test_upnext_excluding_the_previous_page... (167-189), home tests (110-157), UPNEXT_SEED_QUERIES/PLAIN_FLOOR (62-68)">
**What changes.** No edit expected. These tests assert exact or minimum sizes that a smaller pool could break:
- :171 `len(first["rows"]) == UPNEXT_PAGE` (8);
- :179 `len(ranked) == UPNEXT_PAGE * 2` (16) against pools measured 19 and 17 deep;
- :117 a default home page fills;
- :121 `> default` at twice the limit;
- :157 `len(page) >= PLAIN_FLOOR` (45).

The home tests draw on the like-seeded layers that use `get_similar_candidates`.

**Regression risk: medium, unconfirmed.** It depends on the same cache-content question as test_dislike_profile.py. The plan flags this file, which is correct. :179 has the same one-row margin for "cooking".
</impact>
<impact path="tests/active/test_blocks.py" element="_deep_seed (186-191), test_an_upnext_page_stays_full_after_blocks_remove_rows_from_it (194-208), RESOLVABLE (23-27)">
**What changes.** No edit expected.
- `RESOLVABLE` selects `WHERE v.error_count = 0`, so the block targets are healthy.
- `_deep_seed` searches for a seed whose pool holds at least PAGE + 3 (11) rows, then asserts full 8-row pages (:198, :207). A shrink moves which seed is chosen rather than failing, unless no search result qualifies (:191 `pytest.fail`).
- The `test_blocked_channel...` surface uses `keyless` rows from a live up-next page, which are unaffected in kind.

**Regression risk: low.**
</impact>
<impact path="tests/active/test_server.py" element="test_a_keyed_request_s_500_entry_exclude... (182-192ff) and stand-in-Engine tests (~456, ~648, ~672-716, ~1004)">
**What changes.** No edit expected.
- At :190-192, the keyed likes GET against the live Engine expects exactly the 5 liked search results. Search already filters errored videos (`data/search.py:195`), so they are healthy and the assertion holds after the fix.
- The home pages at :200-201 rely on the feed pool, but assert overlap and exclusion, not size.
- The stand-in `EngineStub` tests at :456 and :648 answer metadata themselves and never reach `fetch_metadata_by_ids`.

**Regression risk: low.**
</impact>
<impact path="tests/active/test_profiles.py" element="_embedded_videos (241-250) and keyed up-next tests (274-~300)">
**What changes.** No edit expected.
- `_embedded_videos` selects `WHERE v.error_count = 0`, so imported and liked videos are healthy.
- `_upnext_profile` (:276-279) asks for limit=16 but asserts only `body["rows"]` being non-empty and the debug profile.

**Regression risk: low.**
</impact>
<impact path="engine/server/api/server_config.py" element="VIDEO_ERROR_THRESHOLD = 3 (line 412)">
**What changes.** Nothing. It is out of scope. The issue and the plan cite `server_config.py:387`, but the constant is now at :412 (comment at :411: "Hide videos after this many recorded access errors (0 disables the filter)"). A delivery comment should cite :412.

**Regression risk: none.**
</impact>
<impact path="engine/server/README.md" element="line 11, /internal/videos/metadata bullet">
**What changes.** Replace the final sentence, "Uuid entries leave out videos at or over the error-count threshold; for id entries the threshold applies only to the last pair of each 450-entry chunk.", with one sentence saying that videos at or over the error-count threshold are left out for both entry forms. The rest of the bullet stays accurate. It must remain one line (no softwrap).

**Regression risk: none.**
</impact>
<impact path="client/README.md" element="line 21, GET /api/user-profile/likes bullet">
**What changes.** Optional. The bullet is bare today. Lines 15 and 22 already say that the uuid-form routes leave out videos at or over the error-count threshold. After the fix the keyed GET does too, and that is a visible behaviour change: the likes list can be shorter than the stored likes. A short clause here keeps the three likes routes consistent. The plan does not include this; it is flagged for the doc step to decide.

**Regression risk: none.**
</impact>
<impact path="docs/project/adr/0003-metadata-endpoint-accepts-uuid-entries.md" element="Consequences (17-22)">
**What changes.** None needed. I checked it: every consequence speaks of the uuid path, import, the tie-break, or the blob check, and none states the id-path precedence quirk. After the fix it stays true, and the id path now matches it in spirit.

**Regression risk: none.**
</impact>
<impact path="engine/server/api/recommendations/docs/PIPELINE_DIAGRAM.md" element="line 47, similarity candidates filters (error_threshold)">
**What changes.** Nothing. It already lists `error_threshold` as a similarity-candidate filter, which the fix makes fully true. `LAYER_PARAMS.md:65,105` likewise just lists `VIDEO_ERROR_THRESHOLD`.

**Regression risk: none.**
</impact>
<impact path="docs/project/issues/33-metadata-id-threshold-precedence.md" element="Status line (3), Comments (46), file location">
**What changes (at harvest).**
- `Status: bug, needs-triage` → `Status: bug, complete`.
- A delivery comment under `## Comments`: the id lookup now passes `f"({conditions})"`; the :120 comment is gone; the chunk test asserts the exact healthy set on the id path (c455 absent) plus c455 present at None; the README is updated.
- Move the file to `docs/project/issues/archive/`, per `docs/project/triage-labels.md:12`.

**Line references to correct in the comment.**
- `VIDEO_ERROR_THRESHOLD` is at `server_config.py:412`, not 387.
- Block-add's metadata call is at `client/backend/server.py:969`, not 954.
- The keyed likes GET (`server.py:1017-1032`) is an id caller the issue's Impact section missed.

**Regression risk: none.** Moving files needs a shell, so it happens at harvest.
</impact>
<impact path="docs/project/issues/09-similars-diversity.md" element="whole issue (related)">
**What changes.** Optional cross-reference. Issue 33 says a stricter filter "would shrink [similar pools] further". The fix does that, but only for cached pools holding errored videos (see the similarity_candidates entry). A one-line note under issue 09's comments would record it. Not required by the plan.

**Regression risk: none.**
</impact>
<impact path="docs/project/plans/01-33-metadata-id-threshold-precedence.md" element="plan and its .record.md">
**What changes.** These are rendered by the workflow; do not hand-edit them. At harvest they move to `docs/project/plans/archive/`, following the 16-14 precedent. The plan's cite of `server_config.py:387` is stale (:412).

**Regression risk: none.**
</impact>
<impact path="tests/last_test_validation.json" element="tracked test record (and tests/last_test_output.txt)">
**What changes.** Regenerated by the `validate_tests.py` runs. On merge, take main's copy and re-run `--compare`.

**Regression risk: merge process only.**
</impact>
</impacts>

## Documentation to update

- [x] `engine/server/README.md` - updated: `engine/server/README.md`: the `/internal/videos/metadata` bullet now says the error-count threshold applies to both entry forms.
- [x] `client/README.md` - updated: client/README.md: the `GET /api/user-profile/likes` bullet now says what the route returns and that it leaves out liked videos at or over the Engine's error-count threshold, while keeping the stored like.
- [x] `docs/project/issues/33-metadata-id-threshold-precedence.md` - updated: Issue 33 is marked `bug, complete` and has its delivery comment, but it has not been moved to `docs/project/issues/archive/`. I have no move or delete tool, so that step is left to harvest.
- [x] `docs/project/plans/01-33-metadata-id-threshold-precedence.md` - updated: I didn't edit this file: the workflow renders it, so it can't be hand-edited, and archiving it needs a shell that happens at harvest.
- [x] `docs/project/adr/0003-metadata-endpoint-accepts-uuid-entries.md` - out of scope: Every Consequence is about the uuid path, import, the lowest-`video_id` tie-break, the blob check or resolve. None of them states the id-path precedence quirk, so none is false now. The build makes the id path filter the way the uuid path already did, which matches the ADR's intent.
- [x] `docs/project/issues/09-similars-diversity.md` - out of scope: The impact inventory raised it as an optional cross-reference. The issue makes no claim about error-count filtering or about errored videos in similar pools; its only "threshold" is an overlap-ratio target on line 23. Nothing in it became false. The shrink of cached similar pools is recorded in issue 33's delivery comment instead.
- [x] `engine/server/api/recommendations/docs/PIPELINE_DIAGRAM.md` - out of scope: Line 47 lists `error_threshold` as a similarity-candidate filter. That claim is now fully true for cached candidates as well, so no change is needed.

## Implementation plan

## Draft implementation: issue 33, the id lookup filters every entry

### What must be tested

- **The id lookup honours the threshold for every entry in every chunk.** At threshold 3, over the 460 bulk videos, `fetch_metadata_by_ids` returns exactly the 459 healthy keys. c455 is absent: it sits at index 5 of the 10-entry second chunk, not last. c452's full 29-key row is present. This is red on today's code, because c455 comes back by id, and green after the edit.
- **Threshold off is unchanged.** At `error_threshold=None`, the same 460-entry id call returns c455's row. There is no error clause at None, so this assertion pins the unchanged behaviour. It does not test the fix itself.
- **Everything else in `test_metadata.py` stays green unchanged.** At :104-110, b1 has a NULL `error_count` and passes `IS NULL`. At :148-150 the call has no threshold.
- **Indirect callers stay green on the live Engine**, run one file per `validate_tests.py` invocation (see Verification).

### Module map (files touched)

| File | Change |
|---|---|
| `engine/server/data/metadata.py` | Line 128: parenthesise the conditions. Line 120: delete the comment. |
| `tests/active/test_metadata.py` | Docstring lines 6 and 8. The chunk test: lines 159-160, plus one new assertion. |
| `engine/server/README.md` | Line 11: the final sentence. |
| `docs/project/issues/33-…md` | At harvest: status, delivery comment, move to archive. |

No new function, flag, module or dependency. No caller is edited (`similarity_candidates.py`, `internal_client_reads.py`, `client/backend/server.py`).

### `engine/server/data/metadata.py`: `fetch_metadata_by_ids` after the edit

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
        conditions = " OR ".join(
            ["(v.video_id = ? AND v.instance_domain = ?)"] * len(batch)
        )
        params: list[Any] = []
        for entry in batch:
            params.append(entry.get("video_id"))
            params.append(entry.get("instance_domain") or "")
        for row in _select_metadata(conn, f"({conditions})", params, error_threshold):
            result[like_key(row)] = row
    return result
```

Diff: remove line 120 (`# Left unparenthesised on purpose: …`) and replace `conditions` with `f"({conditions})"` on the `_select_metadata` call, character-for-character the form at :155.

What stays true after the edit:
- The rendered WHERE is `WHERE ((pair) OR … OR (pair)) AND (v.error_count IS NULL OR v.error_count < ?)` when the threshold is > 0. When the threshold is None or ≤ 0 it is `WHERE ((pair) OR …)`, and only the redundant parentheses differ from today.
- Parameters are unchanged in count and order: 2 × len(batch) pairs, then the threshold once, appended by `_select_metadata`. The maximum is 901, under SQLite's 999.
- The signature, early return, chunking, the fields read, `like_key` keying and the 29-key row are unchanged.
- `_select_metadata`, `fetch_metadata_by_uuids`, `uuid_key`, `_chunk` and `fetch_metadata` are untouched.

### `tests/active/test_metadata.py`

**Docstring line 6** becomes:

`- The id lookup returns a1's full joined row and skips the unembedded n1. Across 460 videos, which cross the 450-entry chunk boundary at threshold 3, both lookups return every healthy video and drop the errored video in the second chunk; with no threshold the id lookup returns it.`

**Docstring line 8** ("Known limitation, left unasserted on purpose: …") is removed, together with the blank line that follows it. The docstring then runs bullet list → blank → "Everything runs in-process…".

**The chunk test** after the edit (the name is kept, since it is still accurate):

```python
def test_both_lookups_return_every_healthy_video_across_the_450_entry_chunk_boundary(conn):
    for i in range(BULK_SIZE):
        _add(conn, _bulk(i), error_count=5 if i == BULK_ERRORED else 0)
    conn.commit()
    healthy = [i for i in range(BULK_SIZE) if i != BULK_ERRORED]
    id_entries = [{"video_id": _bulk(i)[0], "instance_domain": BULK} for i in range(BULK_SIZE)]
    by_id = metadata.fetch_metadata_by_ids(conn, id_entries, error_threshold=THRESHOLD)
    assert {key: row["video_id"] for key, row in by_id.items()} == {f"{_bulk(i)[0]}::{BULK}": _bulk(i)[0] for i in healthy}
    assert by_id[f"c452::{BULK}"] == _row(*_bulk(452))
    assert metadata.fetch_metadata_by_ids(conn, id_entries, error_threshold=None)[f"c{BULK_ERRORED:03d}::{BULK}"] == _row(*_bulk(BULK_ERRORED))
    by_uuid = _by_uuids(conn, *[(_bulk(i)[1], BULK) for i in range(BULK_SIZE)])
    assert {key: row["video_id"] for key, row in by_uuid.items()} == {f"{_bulk(i)[1]}::{BULK}": _bulk(i)[0] for i in healthy}
    assert by_uuid[f"uc452::{BULK}"] == _row(*_bulk(452))
```

Decisions behind the test:
- **The entry list is hoisted into `id_entries`** so the threshold-3 call and the None call send the identical 460 entries. The None assertion runs with c455 in the middle of its chunk, which is the meaningful case.
- **The exact-set assertion uses the uuid path's dict form (:163)**, so the two paths read alike. It also checks that each key maps to its own video.
- **The :159 comment is deleted.**
- **Red-then-green:** on today's code, `by_id` contains `c455::bulk.example`, so the dict equality fails. After the edit it holds.

### `engine/server/README.md` line 11

The final sentence becomes `Videos at or over the error-count threshold are left out for both entry forms.` The rest of the bullet is unchanged, and it stays on one line.

### Optional items (not in the plan, left for the doc step)

- `client/README.md:21` could add a clause saying the keyed likes GET leaves out liked videos at or over the threshold while keeping the stored like. That would match :15 and :22.
- `test_internal_client_reads.py` could add a handler-level id case at THRESHOLD.

The draft does not include either. R3 does not ask for them, and the fix is pinned one layer down.

### Verification order

1. `validate_tests.py` from `/home/enduser/code/PeerTube-browser/.worktrees/33` on `tests/active/test_metadata.py`, in-process. First against the test edit alone, where it must be red with c455 present in `by_id`. Then with the `metadata.py` edit, where it must be green.
2. Each Engine-backed file in its own invocation, because of the shared per-IP rate limit:
   - `test_similar.py`
   - `test_dislike_profile.py`
   - `test_server.py`
   - `test_blocks.py`
   - `test_profiles.py`
   - `test_internal_client_reads.py`

   `test_dislike_profile.py` is added from the impact inventory; the plan's watch list omits it. It has exact 16-row up-next pages over the "cooking" pool (19 deep). `test_similar.py:179` has the same one-row margin.
3. The full suite.

If a live file fails on page size, the cause is a cached similarity pool (`similarity-cache.db`, filled by `precompute-similar-ann.py` with no error filter) that holds errored videos which `_build_rows` now drops. That is the accepted R2 shrink. It is not a defect in the edit, and it goes back for judgement rather than being patched around.

### Harvest

For issue 33:
- set `Status: bug, complete`;
- add a delivery comment covering:
  - the parenthesised id conditions;
  - the removed :120 comment;
  - the exact-set and None assertions;
  - the README line 11 change;
  - corrected line references: `server_config.py:412` and `client/backend/server.py:969`;
  - the keyed likes GET (`server.py:1017-1032`) as an affected caller the issue missed;
- move the file to `docs/project/issues/archive/`.

The plan and its `.record.md` move to `docs/project/plans/archive/`.

### Check against plan and requirements (pass 1, converged)

| Requirement | Status |
|---|---|
| R1 | Met: one-line parenthesis edit plus the comment deletion. Nothing else moves. |
| R2 | Met: no caller edits. |
| R3 | Met: exact-set assertion replaces `<=`, the :159 comment is gone, the docstring is reworded and the limitation paragraph removed, c452 is kept, red-then-green holds, and the None case is asserted as the plan chose. |
| R4 | Met: README line 11. ADR-0003 untouched. Issue harvest listed. |
| Acceptance criteria | All covered. |
| Consistency constraints | Met: inline `f"({conditions})"` as at :155, no softwrap. |
| Out of scope | Respected. |

**Deliberate simplification:** the fix stays local to the id lookup rather than hardening `_select_metadata`. Its limit is that a future caller passing a bare OR could bring the bug back. The upgrade path is to wrap `WHERE ({conditions})` inside `_select_metadata` when a third caller appears.

### Phases

#### Phase 1 - Id lookup filters every entry [code]

**Files touched.** engine/server/data/metadata.py (EDITED), tests/active/test_metadata.py (EDITED)

**Checkpoint.** Seam: the direct function boundary `metadata.fetch_metadata_by_ids(conn, entries, error_threshold)`, called in-process on the existing `conn` fixture in tests/active/test_metadata.py. That fixture is a temporary SQLite database with the Engine's videos, video_embeddings and channels tables, and nothing is stubbed. This harness is already the precedent for this function. The test is `test_both_lookups_return_every_healthy_video_across_the_450_entry_chunk_boundary`, and it keeps its name. It hoists the 460 bulk entries into `id_entries`. At error_threshold=THRESHOLD (3) it asserts exact dict equality `{key: row["video_id"] for key, row in by_id.items()} == {f"{_bulk(i)[0]}::{BULK}": _bulk(i)[0] for i in healthy}`, replacing the `<=` subset check in the uuid path's :163 form, so c455 (index 5 of the 10-entry second chunk, not its last) must be absent. It keeps the `by_id["c452::bulk.example"] == _row(*_bulk(452))` full-row check. It adds one assertion that the same `id_entries` at error_threshold=None return `_row(*_bulk(BULK_ERRORED))` under `c455::bulk.example`. It deletes the :159 comment, rewords docstring line 6 to "both lookups return every healthy video and drop the errored video in the second chunk; with no threshold the id lookup returns it", and removes the line 8 "Known limitation" paragraph with its trailing blank line. The test must be red on the test edit alone (c455 present in by_id) and green after the metadata.py edit. Every other test in the file stays green unchanged.

**Intent.** In engine/server/data/metadata.py, `fetch_metadata_by_ids` passes `_select_metadata` each chunk's OR of pairs wrapped in parentheses, in the same `f"({conditions})"` form `fetch_metadata_by_uuids` uses at :155, and the :120 comment is deleted. As a result the error threshold excludes an errored video wherever it sits in a 450-entry chunk, while with no threshold the lookup still returns that video.

- C1 - At threshold 3, the id lookup over the 460 bulk entries returns exactly the 459 healthy keys, and the errored c455 in the middle of the second chunk is absent.
- C2 - With no threshold, the same 460-entry id lookup still returns c455's full row.

**Outcome.** ### engine/server/data/metadata.py
`fetch_metadata_by_ids` now passes `_select_metadata` each chunk's OR of pairs in parentheses (`f"({conditions})"`), the same way `fetch_metadata_by_uuids` does. Before, the threshold's `AND` bound only to the last pair of the chunk. Now it applies to every pair, so an errored video is excluded wherever it sits in a 450-entry chunk. With no threshold there is no error clause, so the lookup still returns that video. I deleted the comment above the conditions that said "Left unparenthesised on purpose … (Open item A, option 1)".

### tests/active/test_metadata.py
The module docstring had a "Known limitation" paragraph saying the id lookup's threshold binds only to the last pair of each chunk. That is no longer true, so I removed it and reworded the chunk-boundary bullet: both lookups now return exactly the healthy videos and drop the errored one mid-way through the second chunk. In `test_both_lookups_return_every_healthy_video_across_the_450_entry_chunk_boundary` I took out the comment saying c455 is deliberately not asserted on the id path. I also changed the id-path assertion from a subset check (`healthy <= set(by_id)`) to an exact equality over key → video_id, the same form the checkpoint and the uuid-path assertion use. That makes the test stricter, not weaker: it now fails if c455 comes back by id. Nothing else in the file changed.


