# 13-deterministic-event-ids

_Rendered by the `dev-flow` workflow from its run state. Every edit here is overwritten on the next step; the evidence each gate turned on is in `docs/project/plans/16-13-deterministic-event-ids.record.md`._

## Requirements

### Goal and purpose

Build issue `docs/project/issues/01-deterministic-event-ids.md` as triaged. It closes the security-audit finding that repeated `like` posts can push any video to the top of the Engine's popular ordering. Two changes do this. (1) The Client backend derives each interaction event's `event_id` deterministically, so the Engine's existing `ON CONFLICT(event_id) DO NOTHING` collapses replays at ingest. (2) The Engine caps how much the interaction signal can add in the popular ordering. Decisions: `docs/project/adr/0001-derived-interaction-event-ids.md` and `CONTEXT.md` **Interaction event** and **Interaction signal**. This build is plan 13, in wave 2 of the security hardening batch (issues 01-06, `.scratch/security-hardening-batch/notes.md`). It runs in the worktree `/home/enduser/code/PeerTube-browser/.worktrees/fix-13-deterministic-event-ids`, branched from main after plans 10-12 merged, and alongside plan 14.

### Current behavior (verified in the tree)

- `client/backend/server.py` `_handle_user_action` (currently around line 731) builds the event with `"event_id": f"client-{uuid4()}"` (around line 802). It sets `publish = action in ("like", "undo_like")`, so every like and undo_like is published even when nothing changed. `actor_id` is `profile_id or "anonymous"`. A dislike publishes an `UndoLike` only when `_store_reaction` reports that a like was removed.
- `_store_reaction(profile_id, action, video)` returns whether a dislike removed a like. It calls `record_like` in two places: the plain-like branch, and the "like replacing a dislike" branch. It calls `remove_like` in the undo_like branch and in the dislike branch.
- `client/backend/lib/users_store.py`: `record_like(conn, user_id, action, video, max_likes) -> None` upserts into `likes` (`ON CONFLICT ... DO UPDATE`), trims to `max_likes`, and commits. `remove_like(conn, user_id, video_id, instance_domain) -> bool` deletes the row and reports whether one was removed. The `likes` row is deleted on un-like, so there is no persistent per-video like instance.
- `_handle_likes_import` calls `record_like` and publishes nothing.
- `client/backend/lib/profiles.py` `delete_profile` deletes every row keyed to a profile (blocks, dislikes, dislike_profiles, likes, users, profiles) in one transaction.
- `engine/server/data/random_videos.py` `fetch_popular_videos` orders its inner subquery by `(v.popularity + COALESCE(sig.signal_score, 0)) DESC` (around line 247), then by `(v.likes + COALESCE(sig.likes_count, 0)) DESC`, then views, published_at and video_id.

### Requirements: like instance (generation)

- Add a new Client table, `like_generations(user_id, video_id, instance_domain, generation)`, keyed on `(user_id, video_id, instance_domain)`. Create it in `ensure_user_schema` with `CREATE TABLE IF NOT EXISTS`, in the same executescript style as the other tables.
- An un-like never deletes from `like_generations`, so the generation survives the un-like.
- When `record_like` inserts a new `likes` row, it increments that video's generation for the user, starting from 1 on the first like. Re-liking a video that is already liked leaves the generation unchanged.
- `record_like` reports whether the like was new and returns the current generation (for example, a `(new, generation)` pair). The exact return shape is the build's choice. The likes-import caller ignores the return value and must keep working unchanged.
- An `undo_like`, or a dislike that replaces a like, reads the video's current generation for the profile and removes the like with `remove_like`. It publishes only when `remove_like` reports that a like was removed. The generation it uses is the one the matching Like used.
- Anonymous actors (no resolvable `X-Profile-Key`) use the fixed generation `0`.
- `delete_profile` in `client/backend/lib/profiles.py` also deletes that profile's `like_generations` rows, in the same transaction.

### Requirements: derived event id

- The event id is `client-` followed by the SHA-256 hex digest of the joined fields `(actor, video_uuid, instance_domain, event_type, generation)`. Actor is the profile id, or `anonymous`. `event_type` is `Like` or `UndoLike`. The joining must be unambiguous (e.g. a separator that cannot confuse field boundaries). This replaces `client-<uuid4>`, and the `uuid4` import goes if nothing else uses it.
- Every publish of one like, and of the un-like that ends it, uses the same generation. A like made after that un-like uses a different one.
- The id never embeds raw user input unhashed. It is a non-empty string that the Engine's `normalize_event_payload` accepts.
- The payload's other fields (`event_type`, `actor_id`, `object`, `published_at`, `source_instance`, `raw_payload`) are unchanged.

### Requirements: publish on change only

- With a profile, a `like` publishes a `Like` only when the like is new. This covers the plain-like branch and a like that replaces a dislike.
- With a profile, an `undo_like` publishes an `UndoLike` only when a like was actually removed.
- A `dislike` that replaces a like publishes one `UndoLike`, with the id the matching profile `undo_like` would have used. A dislike on a video that is not liked publishes nothing. `undo_dislike` publishes nothing.
- A request that changes nothing still returns 200 `{"ok": True, "updatedAt": ...}` and publishes nothing.
- Anonymous `like` and `undo_like` always publish, with generation 0. Every anonymous `Like` on a video therefore carries one id, and every anonymous `UndoLike` carries another. Anonymous likes add at most +1 per video and anonymous un-likes subtract at most -1 (ADR-0001 §3, accepted).
- Error handling is unchanged: 400/404/502 paths, `DislikeLimitReached`, `EngineApiError`, and the centroids-before-write ordering.

### Requirements: ranking cap

- In `engine/server/data/random_videos.py`, add a module-level named constant (e.g. `POPULAR_SIGNAL_CAP = 25.0`). The popular-pool ordering becomes `(v.popularity + MIN(COALESCE(sig.signal_score, 0), <constant>)) DESC`, with the constant passed as a query parameter or interpolated from the constant, never a bare literal.
- `interaction_signals.signal_score` stays uncapped in storage. The `interaction_signal_score` column the query returns stays the raw value.
- The secondary likes tiebreaker is unchanged.

### Unchanged (must not be modified)

The Engine's `ingest_interaction_event()`, `normalize_event_payload()`, the `_event_deltas` weights, and the stored `signal_score`.

### Acceptance criteria

- Posting `like` twice for one video with one profile publishes exactly one `Like`. The video's `likes_count` rises by 1 and its `signal_score` by 1.0.
- A profile's like → undo_like → like sequence publishes Like, UndoLike, Like. The two `Like` events carry different `event_id`s, and the video ends with `signal_score` 1.0.
- Re-sending an identical, already-published event to the Engine (a bridge retry) is reported as `duplicate: true` and changes no counts.
- Two anonymous `like` posts for one video produce the same `event_id`, and the Engine counts the second as a duplicate.
- `undo_like` for a video the profile does not like publishes nothing and returns 200.
- A dislike replacing a like publishes one `UndoLike`, with the id the matching profile un-like would have used. A dislike on an unliked video publishes nothing.
- In the popular ordering, a video with `signal_score` 1000 and `popularity` 0 ranks below a video with `popularity` 30 and no signal.
- `delete_profile` removes the profile's `like_generations` rows.
- The existing interaction-event tests (`tests/active/test_interaction_events.py`, `tests/active/test_internal_events.py`, `tests/active/test_random_videos.py`) and the security-bundle / frontend suites in `tests/active` still pass.

### Out of scope

- Backfilling or rewriting events already stored with random ids.
- Changing Engine ingest, `_event_deltas`, or the stored `signal_score`.
- The secondary likes tiebreaker.
- `Comment` events.
- Rate limiting, or requiring a profile for likes.
- Making the likes-import path publish.
- Closing the `max_likes` trim gap. When the trim drops a like, the Engine keeps its +1, a later un-like publishes nothing, and a re-like gets a new generation. This gap exists today and is accepted.

### Consistency constraints

- Match the surrounding style: stdlib HTTP handlers, `respond_json`, module-level named constants, env vars read once at startup, stdlib only (`hashlib`). Keep the fewest files, and add no new abstractions with a single implementation.
- Backwards compatibility is not required beyond the above.
- Line numbers drift, so re-locate code by function name.
- Plan 14 edits other handlers in `server.py` and calls `record_like` from import, ignoring its return value. Keep the diff to `_handle_user_action`, `_store_reaction`, `record_like`, `ensure_user_schema`, `delete_profile` and `fetch_popular_videos` to limit merge conflicts.

### Test and run constraints

- Test trees: active `tests/active`, working `tests/tmp`, archive `tests/archive`, delete_me `delete_me`, plans `docs/project/plans`. Record: `tests/last_test_validation.json`. Output: `tests/last_test_output.txt`.
- Run `validate_tests.py` from the worktree root (`project_dir` = `/home/enduser/code/PeerTube-browser/.worktrees/fix-13-deterministic-event-ids`).
- Run Engine-backed test files in their own `validate_tests.py` invocations because of the Engine rate limit.
- The worktree symlinks main's `whitelist.db`, so test Engines share it with other lanes. Tests must use unique video/actor identities, or isolated DBs, so concurrent lanes do not collide.
- On merge, `tests/last_test_validation.json` and `tests/last_test_output.txt` will conflict. Take main's copy and re-run `validate_tests.py --compare` on the merged tree.

### Baseline suite state

Pre-build baseline: exit code 0, variant false (the suite passes before any change).

## High-level plan

### Approach

Two changes, one in each service. Both stay inside the six functions the requirements name, plus a small unavoidable edit to the import lines of `server.py`.

**1. Client: generation table and `record_like` (`client/backend/lib/users_store.py`).** `ensure_user_schema` gets one more `CREATE TABLE IF NOT EXISTS like_generations` in the existing executescript, placed before the `local-user` cleanup. It has `user_id`, `video_id`, `instance_domain` and an integer `generation`, with `(user_id, video_id, instance_domain)` as the primary key. `record_like` stops using `ON CONFLICT ... DO UPDATE` to find out whether a like is new. It first inserts the `likes` row with `ON CONFLICT DO NOTHING` and reads the cursor's rowcount: 1 means new, 0 means the video was already liked. When the row already exists it runs the old refresh of `video_uuid` and `updated_at` as a plain UPDATE, so recency ordering and the trim behave exactly as today. When the like is new it upserts `like_generations`: insert generation 1, or on conflict set generation to generation + 1. It then reads the current generation back and returns `(new, generation)`. The trim and the trailing commit are unchanged. The trim never drops the row just inserted, because that row is the newest. The likes-import caller already ignores the result, so it keeps working without edits. An imported new like still advances that video's generation, which the plan accepts (see Risks). Nothing ever deletes from `like_generations` except `delete_profile`, so a generation survives an un-like. This covers "increments on a new like, from 1", "unchanged on a re-like", and "the generation survives an un-like".

The un-like side needs to read a generation, and `server.py` holds no SQL. So `users_store.py` gains one small reader function. It returns the stored generation for `(user, video_id, instance_domain)`, or 0 when there is no row. `server.py` imports it next to `record_like` and `remove_like`. `remove_like` itself is not changed.

**2. Client: `_store_reaction` (`client/backend/server.py`).** Today it returns "did a dislike remove a like". It will return a `(changed, generation)` pair covering every branch:
- Plain like: the result of `record_like`.
- `undo_like`: read the generation, then `remove_like`, both inside the same `with conn` block. Returns `(removed, generation)`.
- Dislike: in its existing write transaction, read the generation before `remove_like` and `write_dislike`. Returns `(removed, generation)`. The centroids are still computed before any write, so the error ordering is unchanged.
- `undo_dislike`: returns `(False, 0)`.
- Like replacing a dislike: `delete_dislike` then `record_like`. Returns `record_like`'s pair. Likes and dislikes exclude each other, so this is always new.

The generation an un-like reads is the value the matching Like got when it was recorded. Only a later new like changes it. So a Like and the un-like that ends it share a generation, and the next Like gets a different one. The docstring's `:returns:` is updated.

**3. Client: `_handle_user_action`.**
- With a profile: `publish` becomes `changed`. A replayed like, an un-like of an unliked video, a dislike of an unliked video and every `undo_dislike` publish nothing. They fall through to the existing 200 `{"ok": True, "updatedAt": ...}` response.
- Without a profile: `publish` stays `action in ("like", "undo_like")` with generation 0. Dislike actions already require a profile, so anonymous input can only be a like or an undo_like.
- `event_type` keeps the existing rule (`Like` for `like`, otherwise `UndoLike`), so a dislike that removed a like produces an `UndoLike`. Its generation is the one the profile's `undo_like` would have read, so the id is identical.
- The id is `client-` plus the SHA-256 hex digest of `(actor, canonical_uuid, canonical_host, event_type, generation)`. The fields are serialised with `json.dumps` of a list, which is already imported. JSON quoting and escaping make field boundaries unambiguous whatever the field values contain.
- The id is 71 characters of hex and contains no raw input. `normalize_event_payload` only requires a non-empty string, and `event_id` is a TEXT primary key with no length limit, so it is accepted.
- `hashlib` is added to the stdlib imports. `uuid4` stays imported because `run_id` near the bottom of `server.py` still uses it, so the requirement to drop the import only if unused leaves it in place.
- The other payload fields, the 400/404/502 paths, `DislikeLimitReached`, `EngineApiError` and the bridge response are untouched.

**4. `delete_profile` (`client/backend/lib/profiles.py`).** One more `DELETE FROM like_generations WHERE user_id = ?` inside the existing `with conn` transaction.

**5. Engine: ranking cap (`engine/server/data/random_videos.py`).** A module-level `POPULAR_SIGNAL_CAP = 25.0`. The first ORDER BY term in `fetch_popular_videos`'s inner subquery becomes `popularity + MIN(COALESCE(signal_score, 0), ?)`, with the constant bound as a query parameter. The params list now holds, in order: the optional error threshold, the cap, the inner limit, the outer limit. Getting this order right is the one fiddly part. `COALESCE` sits inside `MIN`, so SQLite's two-argument scalar `MIN` never sees NULL. The outer `interaction_signal_score` column, the stored `signal_score` and the likes tiebreaker are unchanged. A signal of 1000 now counts as 25, which ranks below popularity 30.

**How the acceptance criteria follow:**
- Double like: the second post finds the row, `new` is false, nothing is published.
- like → undo → like: the ids use generations g, g, g+1, so the two Likes differ, the counts net +1 −1 +1, and `signal_score` ends at 1.0.
- Bridge retry: the same id hits the Engine's existing `ON CONFLICT DO NOTHING` and is reported as a duplicate.
- Anonymous: generation 0 gives one id per video, so the second post is a duplicate.
- The un-like, dislike, ranking and `delete_profile` criteria follow directly from sections 2 to 5.

**Tests:** new Client cases publish under fresh profiles, so their actor identities are unique per run. The anonymous criterion ("the second is a duplicate") holds on every run even against the shared `whitelist.db`. The ranking case uses an isolated in-memory Engine database, as `test_random_videos.py` already does.

### Alternatives considered

- **How to detect a new like.** Rejected: a SELECT for an existing row before the upsert. It adds a query and leaves a window where two concurrent requests both see "absent" and both publish. The conditional insert's rowcount is atomic at the statement level, so only one request ever sees "new".
- **Where the un-like's generation comes from.** Rejected: widening `remove_like` to return the generation. That changes a shared helper's signature for one caller. Rejected: inline SQL in `_store_reaction`, because `server.py` has no SQL anywhere. The small reader in `users_store.py` costs one extra name on an existing import line.
- **Hash input encoding.** Rejected: joining with a control-character separator such as `\x1f` or `\n`. It is only unambiguous if we can prove no field contains that character, and `video_uuid` and `instance_domain` come back from the Engine. JSON encoding needs no such proof.
- **Keying the id on the `likes` row's rowid or timestamp.** Rejected: the row is deleted on un-like, so rowids and timestamps are not stable, and timestamps can repeat.
- **Cap by interpolation versus a bound parameter.** Both are allowed. The parameter was chosen so the value never sits inside the SQL text. The cost is reordering the params list.
- **Capping at ingest.** Out of scope and rejected by ADR-0001: the stored score must stay raw so the cap can change without a migration.

### Risks and gotchas

- **Likes that predate `like_generations`** have no row, so an un-like reads generation 0. The resulting `UndoLike` still has a unique, profile-scoped id. It cannot collide with the anonymous generation-0 ids because the actor differs. The next new like starts that video at generation 1, so the sequence stays correct.
- **Imported likes** advance the generation without publishing. A later un-like then publishes an `UndoLike` for a Like id the Engine never saw. The count effect (−1) is what today's code already does, and import publishing is out of scope.
- **The `max_likes` trim gap** remains as accepted: the Engine keeps its +1, a later un-like publishes nothing, and a re-like gets a new generation.
- **Merge risk with plan 14:** besides the named functions, `server.py` gets two import-line edits (`hashlib`, and the new reader on the `users_store` import). If they conflict, resolve by union. `record_like`'s return value is additive, so plan 14's import caller, which ignores it, is unaffected.
- **Test runs publish into the shared `whitelist.db`.** Any anonymous Like or UndoLike a test sends for a real video permanently takes that video's single anonymous Like and UndoLike ids. New tests must therefore publish as fresh profiles or use an isolated Engine DB. The existing frontend-reactions tests assert browser-store state, not Engine counts, so they are unaffected.
- **Concurrency on the one shared SQLite connection** is unchanged. The existing rat-tail about unserialised read, compute and write for dislikes still applies.

### Tradeoffs the operator accepts

- **Anonymous likes collapse to at most +1 per video, and un-likes to at most −1.** Once an anonymous Like and UndoLike have both been stored for a video, anonymous visitors contribute nothing further to it, ever. This is ADR-0001 §3 as accepted.
- **The cap of 25.0 is a deliberate simplification.** One named constant bounds the signal's effect on ordering. It does nothing to stop the likes tiebreaker, which is uncapped and out of scope, from being inflated among videos that tie on the first term. To raise or lower the cap, edit the constant. If it ever needs to be configurable, the upgrade path is an env var read once at startup.
- **Events already stored with random ids stay as they are.** No backfill.

## Impacts

<impact path="client/backend/lib/users_store.py" element="ensure_user_schema() (lines 10-63): new like_generations table">
**What changes.** The existing `executescript` gets one more `CREATE TABLE IF NOT EXISTS like_generations (user_id TEXT NOT NULL, video_id TEXT NOT NULL, instance_domain TEXT NOT NULL, generation INTEGER NOT NULL, PRIMARY KEY (user_id, video_id, instance_domain))`. It goes after `dislike_profiles` (lines 53-58) and before the `local-user` cleanup comment and DELETEs (lines 59-61), as the plan says. The docstring at line 11 ("Create the users, likes, profile, block and dislike tables if missing.") should also name the like generations table. No `local-user` DELETE is needed for the new table, because no such rows can exist in a table that is new.

**What depends on it.**
- `client/backend/server.py:1179` (`main`) runs it once at startup on `users.db`, so the live DB gets the table on the first restart. No migration step is needed.
- `tests/active/conftest.py:73` (`client_backend`) and `:160` (`_engine_client`) call it.
- `tests/active/test_server.py:266` (`_client_backend`) calls it.
- `delete_me/test_12_*.py` and `delete_me/test_probe_phase3_http.py` call it. These are scratch copies and are not collected.
- Every later `record_like` and `delete_profile` now needs the table.

**Regression risk: low.** `CREATE TABLE IF NOT EXISTS` is idempotent. A DB on which this function never ran would now fail in `record_like` and `delete_profile` with "no such table: like_generations". I found no such path: every connection above runs the schema first, and the `_seed_like` helpers write to fixture DBs that already have it. Do not confuse this with `engine/server/data/users.py:11`, the Engine's separate `ensure_user_schema`, which is untouched.
</impact>
<impact path="client/backend/lib/users_store.py" element="record_like() (lines 79-117): new-like detection, generation upsert, returns (new, generation)">
**What changes.**
- The one `INSERT ... ON CONFLICT ... DO UPDATE` (lines 94-102) becomes `INSERT ... ON CONFLICT(user_id, video_id, instance_domain) DO NOTHING`. The code reads `cursor.rowcount`: 1 means a new like, 0 means the row already existed.
- On 0, a plain `UPDATE likes SET video_uuid = ?, updated_at = ? WHERE user_id = ? AND video_id = ? AND instance_domain = ?` keeps today's recency refresh.
- On 1, it runs `INSERT INTO like_generations ... VALUES (?, ?, ?, 1) ON CONFLICT(...) DO UPDATE SET generation = like_generations.generation + 1`.
- It then reads the generation back.
- The return annotation changes from `-> None` to `-> tuple[bool, int]`, and the docstring (line 86) gains `:returns:`.
- The `max_likes` trim (103-116) and `conn.commit()` (117) are unchanged.
- `connect_db` (`server.py:144`) uses the default isolation level, so the conflicting INSERT reports rowcount 0. The UPSERT syntax is already in use in this file.

**What depends on it.** Five callers:
- `server.py:846`, plain like in `_store_reaction`. It now consumes the result.
- `server.py:869`, a like replacing a dislike. It now consumes the result.
- `server.py:898`, `_handle_likes_import`. It ignores the result. Plan 14 also edits this handler.
- `tests/active/test_profiles.py:44` (`_seed_like`), which ignores it.
- `tests/active/test_frontend_profile.py:109` (`_seed_like`), which ignores it.

**Transaction behaviour.**
- `get_or_create_user` (line 76) commits by itself when it inserts a user.
- The final commit inside `record_like` commits the caller's enclosing `with conn:` early. That ordering already exists and is documented in `docs/project/plans/archive/03-like-dislike.md:430`: `delete_dislike` runs first, so this commit covers both.
- The generation upsert and read-back happen before that commit, so they are atomic with the likes INSERT.

**Regression risk: medium.**
1. The plan says "the trim never drops the row just inserted". That holds for a single like. It does not strictly hold in a bulk import: up to `MAX_CLIENT_LIKES = 200` (`server.py:52`) records can go in against `MAX_LIKES = 100` (`server.py:51`), in one `with conn:`, and many share one `now_ms()`. A tie at the boundary can therefore trim a row whose generation was just advanced. That is harmless, since the next new like takes generation+1, but the plan's claim holds only for single likes.
2. `clear_likes` (the reset) leaves `like_generations` in place, so a re-like after a reset is new and publishes a fresh `Like`. See the reset entry: this is a repeatable +1 loop.
3. The read-back must work whether or not the connection has a `row_factory`: the test helpers set `sqlite3.Row`, raw connections do not. Use `row[0]`.
4. "New" must come from the INSERT's own rowcount, not from a SELECT beforehand, or two concurrent likes could both publish.
</impact>
<impact path="client/backend/lib/users_store.py" element="new generation reader function (next to remove_like, line 159)">
**What changes.** A new function returns the stored `generation` for `(user_id, video_id, instance_domain)`, or 0 when there is no row. To match the file's style:
- positional `conn, user_id, video_id, instance_domain`, so it can be called as `reader(conn, profile_id, *key)` the way `remove_like` is;
- a docstring with `:returns:`;
- no commit ("inside the caller's transaction", like `remove_like`).

**What depends on it.** `_store_reaction`'s undo_like and dislike branches, through a new name on the `lib.users_store` import (`server.py:37-39`). New tests may call it directly.

**Regression risk: low.** It should be read before `remove_like`. The value is the same either way, because `remove_like` never touches `like_generations`, but reading first keeps the intent clear. Returning 0 for a missing row gives the same generation anonymous actors use. That is safe only because the hashed actor differs: the profile id versus `"anonymous"`.
</impact>
<impact path="client/backend/lib/users_store.py" element="remove_like() (159-168), clear_likes() (153-156), video_reaction(), fetch_recent_likes(), load_liked_keys(), get_or_create_user(): unchanged">
**What changes.** Nothing. The plan keeps `remove_like`'s signature. `remove_like` still does not commit, and its callers hold `with conn:`.

**What depends on it.**
- `remove_like` is called at `server.py:848` (undo_like) and `:861` (dislike).
- `clear_likes` is called at `server.py:988` (reset). It deletes only `likes` and so deliberately leaves `like_generations`. That is required for "the generation survives", but it opens the reset loop described below.

**Regression risk: none in code.** Listed so the reset interaction is on record.
</impact>
<impact path="client/backend/server.py" element="stdlib import block (lines 5-22): add hashlib; keep uuid4">
**What changes.** `import hashlib` goes in alphabetical order between `argparse` (line 5) and `ipaddress` (line 6). Plan 12 has since added `ipaddress` at line 6, so the block reads argparse, ipaddress, json, ...

`from uuid import uuid4` (line 21) must stay: `run_id = str(uuid4())` at line 1155 still uses it. The requirement is "drop uuid4 if unused", and it is still used.

**What depends on it.** The event-id derivation in `_handle_user_action`.

**Regression risk: nil.** This is a merge point with plan 14 if plan 14 touches the import block; resolve by union.
</impact>
<impact path="client/backend/server.py" element="lib.users_store import (lines 37-39): add the generation reader">
**What changes.** The reader's name is added to the parenthesised import, which is alphabetised today: `clear_likes, ensure_user_schema, fetch_recent_likes, get_or_create_user, load_liked_keys, record_like, remove_like, video_reaction`.

**What depends on it.** `tests/active/conftest.py:39` (`import server as client_server`) and `test_server.py:47`. A misspelt name raises ImportError, which breaks all of `tests/active`.

**Regression risk: low.** A mistake fails loudly at import. This is a merge point with plan 14.
</impact>
<impact path="client/backend/server.py" element="ClientBackendHandler._store_reaction() (lines 831-870): returns (changed, generation)">
**What changes.** The return type changes from `bool` to a pair, and `:returns:` (line 837, "Whether a dislike removed a like.") is rewritten. Branch by branch:
- **Plain like** (line 846): the value of `record_like` must be captured inside the `with conn:` (lines 844-848) and returned. Today the function returns `False` at line 849, after the `with` block.
- **undo_like** (line 848): read the generation, then `removed = remove_like(...)`, both inside the same `with`. Return `(removed, generation)`.
- **dislike** (lines 855-863): the `DislikeLimitReached` check (856-857) and `compute_dislike_centroids` (859) stay before any write. Inside the `with` at line 860, read the generation, then `remove_like` and `write_dislike`. Return `(like_removed, generation)`.
- **The shared tail** (lines 864-870) serves both `undo_dislike` and a like replacing a dislike. It must return `record_like`'s pair when `action == "like"` and `(False, 0)` for `undo_dislike`. Today it returns `False` for both, so this branch is the easy one to get wrong.

**Exclusivity.** The plan says a like replacing a dislike is always new. That holds only because every path removes the other reaction; nothing in `lib/dislikes.py` enforces it at the DB level. If a `likes` row did co-exist, this branch would return `new=False` and publish nothing, which is still correct. `dislikes.py`'s `write_dislike` and `delete_dislike` do not commit, so the transaction is unchanged.

**What depends on it.** Only `_handle_user_action` (line 787). The rat-tail comment at lines 853-854 stays true.

**Regression risk: medium.** This is where "a Like and its un-like share a generation" either holds or fails. On the one shared `check_same_thread=False` connection of a `ThreadingHTTPServer`, two concurrent undo_likes can both read g, but only one `remove_like` sees rowcount 1, so only one publishes. A concurrent like and undo is the same class of race as the existing rat-tail.
</impact>
<impact path="client/backend/server.py" element="ClientBackendHandler._handle_user_action() (lines 731-829): publish gating and derived event_id">
**What changes.**
- Line 784, `publish = action in ("like", "undo_like")`, stays as the anonymous default, with generation 0.
- In the profile branch (785-795), `like_removed = self._store_reaction(...)` becomes `changed, generation = ...`, and line 795 `publish = publish or like_removed` becomes `publish = changed`. The comment at line 794 needs rewording.
- Line 802, `"event_id": f"client-{uuid4()}"`, becomes `"client-" + hashlib.sha256(json.dumps([actor, canonical_uuid, canonical_host, event_type, generation]).encode("utf-8")).hexdigest()`.
- `actor` is the same expression as line 804, `profile_id or "anonymous"`, and should be computed once and used in both places.
- `event_type` (line 800) must be computed before the id.
- The docstring "Handle handle user action." (line 732) could state the publish rule.
- The comment at lines 753-754 stays true.

**Behaviour changes callers can see.**
- With a key, a repeat `like`, an `undo_like` of an unliked video, a dislike of an unliked video, and every `undo_dislike` answer 200 `{ok, updatedAt}` and publish nothing.
- On `unpublished_client` (activitypub mode), a repeat keyed like or undo_like used to answer 502 and now answers 200.
- Keyless likes and un-likes still always publish, so they still answer 502 on an unpublished Client. `test_frontend_reactions.py:249-258` relies on that.

**Hashing details.**
- The `json.dumps` defaults (`ensure_ascii=True`, `", "` separators) are part of the id and must never change.
- `generation` must be an `int`, never a `bool` or `str`.
- `canonical_uuid` can be `""` (line 774). The Engine then rejects the event with "Missing object.video_uuid" (`interaction_events.py:208-209`), which is unchanged behaviour.
- The id is 71 characters and is accepted by `normalize_event_payload` (lines 194-198: a non-empty string after `_clean_text`, no length cap) and by `event_id TEXT PRIMARY KEY` (line 24).
- `raw_payload: body` (line 812) is still sent raw. That is out of scope.

**What depends on it.**
- `sendUserAction` in `client/frontend/src/data/user-actions.ts:33` checks only `response.ok`.
- The Engine answers a duplicate with 200 `ok: true` (`internal_events.py:84-93`), and `_publish_to_engine_bridge` maps that to `ok=True`. So a replayed anonymous like answers 200 `bridge_ok: true`.
- The smokes: see their entries.

**Regression risk: medium-high.** Any of these silently reopens the finding or breaks the contract:
- publishing when `changed` is False;
- hashing `None` as the actor instead of `"anonymous"`;
- using a different generation for an undo than for its Like;
- letting the serialisation drift.

No existing test exposes event ids.
</impact>
<impact path="client/backend/server.py" element="_handle_user_profile_reset() (lines 976-993) with clear_likes(): repeatable +1 loop (Step 4 finding, not in the plan's Risks)">
**What changes.** Nothing in the plan's code. But its interaction with the new gating matters. Reset deletes every `likes` row, keeps `like_generations`, and publishes nothing. One profile can therefore repeat like → `POST /api/user-profile/reset` → like. Each like is "new", takes generation+1, gets a fresh id, and adds +1 to `likes_count` and `signal_score`. The only limit is the general per-route `RateLimiter` (lines 352-357).

**What depends on it.** `test_profiles.py`'s `PROFILE_ROUTES` (line 31) uses the route, and the frontend reset flow.

**Regression risk: not a regression.** Today every like adds +1. But the plan's "Risks" does not record this as an unbounded one-profile loop. The 25.0 cap limits the effect on ordering, but not the shown likes count or the likes tiebreaker (`random_videos.py:45,248`).

**Uncertain: operator decision.** Accept it in "Tradeoffs", or change the gating (for example the "open" flag on `like_generations` proposed in the prior Step 4 record). I list it so it is not missed.
</impact>
<impact path="client/backend/server.py" element="_handle_likes_import() (lines 872-900): record_like caller, and the repeatable −1 loop">
**What changes.** Nothing in code. `record_like` at line 898 now returns a pair, which is ignored, and `imported += 1` is unchanged. The whole loop runs inside one `with conn:` while `record_like` commits on each iteration, as today.

**What depends on it.**
- Plan 14 edits this handler.
- `tests/active/test_profiles.py:245-253` and `tests/active/test_frontend_reactions.py:350-374` exercise it, on `unpublished_client`.

**Risk: low for code, but a behaviour to record.**
- Each imported new like advances the generation without publishing. The plan accepts this.
- It is also repeatable. Import video X → `undo_like` X finds the row, publishes an `UndoLike` with a fresh generation, and takes −1 off X → import again → undo again. Each pass removes another 1 from any video other people liked, down to the Engine's `MAX(0, …)` floor (`interaction_events.py:124-127`).
- This gets around the plan's own rule that "an un-like of an unliked video publishes nothing".
- Today's code allows the same, so it is not a regression, but the plan records only the single-shot case.
- See also the tie-trim note in the `record_like` entry.
</impact>
<impact path="client/backend/server.py" element="_publish_to_engine_bridge() / _publish_event() (lines 1032-1064): unchanged">
**What changes.** Nothing.

**What depends on it.** It limits how tests can observe duplicates. It returns `{"ok", "response"}`, and the handler exposes only `ok`, `bridge_ok` and `bridge_error`. So "the second is a duplicate" cannot be read from the Client response. Tests must either read the Engine's `interaction_raw_events`/`interaction_signals`, post to `/internal/events/ingest` directly, or capture payloads with a stub Engine.

**Regression risk: none.**
</impact>
<impact path="client/backend/lib/profiles.py" element="delete_profile() (lines 69-80)">
**What changes.** One more `conn.execute("DELETE FROM like_generations WHERE user_id = ?", (profile_id,))` inside the `with conn:`. It belongs next to the `likes` delete at line 78, since both key on `user_id`. The docstring ("every row keyed to it") stays true.

**What depends on it.**
- `server.py:340-345` (`POST /api/profile/delete`).
- `tests/active/test_profiles.py:197-217`.
- The profile-delete steps in `tests/run-installers-smoke.sh:449,683` and `tests/run-arch-split-smoke.sh:617`.

**Regression risk: low.** It only fails on a DB where the table was never created, and no such path exists. Because the delete runs in one transaction, a failure would roll back the whole profile delete.
</impact>
<impact path="engine/server/data/random_videos.py" element="new module-level POPULAR_SIGNAL_CAP = 25.0">
**What changes.** A named constant goes after the imports (after line 9), with a `#` comment above it. The module has no constants today; the house style can be seen in `interaction_events.py:13-14`.

**What depends on it.** `fetch_popular_videos` and the new ranking test, which may import it.

**Regression risk: nil.**
</impact>
<impact path="engine/server/data/random_videos.py" element="fetch_popular_videos() (lines 195-303): capped ORDER BY term and params order">
**What changes.**
- Line 247, `(v.popularity + COALESCE(sig.signal_score, 0)) DESC`, becomes `(v.popularity + MIN(COALESCE(sig.signal_score, 0), ?)) DESC`.
- Line 200 becomes `[POPULAR_SIGNAL_CAP, limit, limit]`, and line 203 becomes `[error_threshold, POPULAR_SIGNAL_CAP, limit, limit]`. That matches the placeholder order: the WHERE `?` from `{error_clause}` (245, inner subquery), then the cap (247), then the inner `LIMIT ?` (252), then the outer `LIMIT ?` (262).
- Line 234 (`interaction_signal_score`, raw) and the tiebreaker at line 248 are unchanged.
- The docstring "by likes/views" (198) could mention the capped signal.

**What depends on it.**
- `engine/server/api/server.py:90,398` wires it in.
- `engine/server/api/recommendations/builder.py:109-113` wraps it with `error_threshold=settings.video_error_threshold`. That value is `VIDEO_ERROR_THRESHOLD = 3` (`server_config.py:387`), so production always takes the 4-parameter branch.
- `candidates/popular_videos.py:52` consumes the pool.
- `tests/active/test_random_videos.py:85` calls it without a threshold, which is the 3-parameter branch.

**Regression risk: medium.**
- A wrong params order raises nothing, because every placeholder takes a number. It silently turns the cap into a LIMIT or a threshold.
- The tested branch is not the production branch, so the new test must cover both.
- Two-argument `MIN` is SQLite's scalar function, which returns NULL if any argument is NULL. `COALESCE` inside it prevents that.
- On the live dataset, videos with a signal above 25 drop in the popular pool. That is intended.
</impact>
<impact path="engine/server/data/random_videos.py" element="fetch_random_rows() (line 45 likes), fetch_recent_videos(), cache readers: unchanged">
**What changes.** Nothing. `(v.likes + COALESCE(sig.likes_count, 0)) AS likes` is the displayed likes figure, not the ranking signal.

**Regression risk: none.** Listed so the cap is not applied to the wrong query.
</impact>
<impact path="engine/server/data/interaction_events.py" element="ingest_interaction_event() / normalize_event_payload() / _event_deltas() / prune_interaction_raw_events(): unchanged, relied upon">
**What changes.** Nothing; the requirements forbid changes here.

**What depends on it.**
- The collapsing relies on `ON CONFLICT(event_id) DO NOTHING` (line 85) and on the duplicate result (lines 100-109).
- The deltas are Like +1.0, UndoLike −1.0 (lines 255, 262), floored by `MAX(0, …)` (124-127).
- The prune (150-189) strips payload, actor and source but keeps the row, and with it the `event_id`, so derived ids keep collapsing replays after retention.

**Regression risk: none from this build.**
</impact>
<impact path="engine/server/api/handlers/internal_events.py" element="handle_internal_events_ingest() duplicate accounting (lines 56-94): unchanged">
**What changes.** Nothing.

**What depends on it.** The "bridge retry is reported as duplicate" and "second anonymous like is a duplicate" criteria. They can be observed through `results[i].duplicate` and `duplicates`. The route is served only in `ENGINE_INGEST_MODE=bridge`, which the conftest `engine` fixture sets (line 105).

**Regression risk: none.**
</impact>
<impact path="engine/server/data/users.py" element="Engine-side ensure_user_schema() (line 11) / record_like() (line 47): NOT touched">
**What changes.** Nothing. It has the same function names as the Client module, so a `def record_like` grep finds both. The one to edit is `client/backend/lib/users_store.py:79`.

**Regression risk: none, provided the right file is edited.**
</impact>
<impact path="client/backend/lib/engine_api_client.py" element="resolve_video_seed() (lines 66-89): unchanged; shape needed by a stub Engine">
**What changes.** Nothing.

**What depends on it.** Any new isolated test that uses a stub Engine must answer `POST /internal/videos/resolve` with 200 `{"video": {"video_id", "instance_domain", "video_uuid", "video_url"}}`. A 404 becomes "not found"; any other status or a non-dict raises `EngineApiError`. The stub must also accept `POST /internal/events/ingest` and record the `event_id`. I verified this shape in the source; the prior record had it as unverified.

**Regression risk: none.**
</impact>
<impact path="client/frontend/src/data/user-actions.ts" element="sendUserAction() (lines 18-38): unchanged">
**What changes.** Nothing. It treats any 2xx as success, so the new 200 `{ok, updatedAt}` answer to a keyed no-change action is accepted.

**Side effect.** A keyed repeat like on a Client that cannot publish no longer throws "Failed to send action". That is correct.

**Regression risk: none.**
</impact>
<impact path="tests/active/test_random_videos.py" element="existing popular tests (108-122), helpers _two_video_db/_set_views/_event (34-77); home for the ranking-cap test">
**What changes.** The existing tests stay green: they use signal 1.0, which is under the cap, and assert the raw `interaction_signal_score == 1.0` (line 119). The new criterion fits here:
- Use `_two_video_db`, then `UPDATE videos SET popularity` to 0 and 30.
- Set the signal to 1000 with a direct `INSERT INTO interaction_signals`, rather than 1000 ingests.
- Run with and without `error_threshold`. `_set_views` sets `error_count = 0`, so a threshold of 1 keeps both rows.

**Correction to the plan.** The plan says the file uses "an isolated in-memory Engine database". It actually uses a file DB under `tmp_path`, built by `ATTACH` of `whitelist.db` read-only (lines 36-52). It is still isolated from the live DB's writes, but it needs `whitelist.db` to exist.

**What depends on it.** `.un/skills/devsecops/config.json:87-88` maps it to `random_videos.py`.

**Regression risk: low.**
</impact>
<impact path="tests/active/test_profiles.py" element="_seed_like (41-46), _rows_for (59-67), test_deleting_a_profile_removes_its_rows_and_keeps_anothers (197-217)">
**What changes.**
- `_seed_like` now also writes a `like_generations` row and ignores the return value.
- This is the natural home for the "`delete_profile` removes the profile's `like_generations` rows" criterion: add a `like_generations` count to `_rows_for`.
- The four equality asserts (lines 205, 209, 215, 216) must then change together to include `"like_generations": 1` (or 0).
- The comment at line 201 ("all three tables") becomes "four".

**What depends on it.** `config.json:18-21` maps it to `server.py`, `profiles.py` and `users_store.py`.

**Regression risk: low.** A partial update of those dicts fails the test.
</impact>
<impact path="tests/active/test_profiles.py" element="test_a_keyed_upnext_request_is_seeded_... (264-282) and test_a_keyed_search_marks_... (291-313)">
**What changes.** Nothing.
- The first like by a fresh profile is new, so line 300 still expects 502 on `unpublished_client`.
- A dislike of an unliked video still answers 200.
- Line 277 does not assert status.

**Regression risk: none.** Line 300 guards against a like wrongly treated as not new, which would answer 200.
</impact>
<impact path="tests/active/test_frontend_profile.py" element="_seed_like (106-111)">
**What changes.** Nothing required. It calls `record_like` on a fixture DB that already has the table, and ignores the result.

**Regression risk: low.**
</impact>
<impact path="tests/active/test_frontend_reactions.py" element="keyless tests (202-258), keyed sequence (264-308), keyed-vs-keyless store test (311-340), card test (396-409)">
**What changes.** Nothing in the file. Behaviour against the shared live `whitelist.db` does change.

**Keyless tests.** They publish anonymous Like/UndoLike on the first rows of `_videos(dataset, n)`, which are the same every run.
- After this build each such video has exactly one anonymous Like id and one anonymous UndoLike id.
- The first run nets +1−1. Every later run gets duplicates, which still answer 200 `ok`, and the assertions check only `"ok"` and browser-store state.
- The finally-block undos at lines 213-214 and 239-240 become duplicates, so they have no effect after the first run.

**Keyed sequence (264-303).** Each step is a real change, or answers 200 without publishing:
- like: g1, published;
- dislike: removes the like, publishes UndoLike at g1;
- undo_dislike: 200, nothing published;
- out-of-band dislike on the now unliked video: 200;
- like replacing that dislike: g2, published;
- undo_like: UndoLike at g2.

So `all("ok" in a ...)` (line 303) holds.

**Card test (406).** It still expects a 502 for a fresh profile's first like on `unpublished_client`.

**Regression risk: low for the assertions, medium for shared data.**
- A test asserting that "the first anonymous like counts +1" would fail on every run after the first.
- A run that dies between an anonymous Like and its UndoLike leaves +1 on that video for good, because every later anonymous Like is a duplicate. This is accepted under ADR-0001 §3.
</impact>
<impact path="tests/active/test_dislikes.py" element="test_a_video_s_reaction_follows_... (68-87), _profile_disliking (118-123)">
**What changes.** Nothing.
- The dislike of a liked video still publishes, and line 77 accepts `in (200, 502)`.
- `undo_dislike` answers 200 (line 82).
- A dislike of an unliked video answers 200 (line 84, and `_profile_disliking` at line 122).
- Lines 74, 79 and 86 do not assert status.

**Regression risk: none.**
</impact>
<impact path="tests/active/test_server.py" element="keyed likes loop (86-102) and _client_backend / EngineStub harness (262-326)">
**What changes.** Nothing.
- Each like in the loop is on a distinct row, the set removes duplicates, and status is not asserted.
- The dislikes answer 200 (line 102).
- The `_client_backend(tmp_path, engine_base, rate_limiter)` helper plus the `EngineStub` pattern (307-320) is the ready-made isolated harness for the new Client acceptance tests. Extend the stub with `do_POST` for resolve and ingest.

**Regression risk: none.**
</impact>
<impact path="tests/active (new test file(s) for this build)" element="new Client acceptance tests: publish-on-change, derived ids, dislike UndoLike id, anonymous duplicate, delete_profile">
**What changes.** New tests. There are two ways to observe events:
- (a) `engine_client`, reading the live `interaction_raw_events` by a fresh profile id through the `dataset` connection;
- (b) the stub Engine from `test_server.py`, which records posted `event_id`s. This avoids the shared DB and the Engine rate limit.

**Constraints.**
- Profile tests must mint fresh profiles.
- An anonymous test may assert only "same id" or "second is a duplicate", never "first counts".
- Tests that publish real Likes under (a) must withdraw them in a `finally`, as the existing tests do.

**What depends on it.**
- `validate_tests.py` collects `tests/active/test_*.py` (and `tests/tmp`).
- Engine-backed files run in their own invocation.
- New files are unmapped in `.un/skills/devsecops/config.json` until harvest.

**Regression risk: medium for suite stability** under (a); low under (b).
</impact>
<impact path="tests/run-arch-split-smoke.sh" element="client_user_action like + validate_user_action_response (330-346, 584-602), profile delete (617)">
**What changes.** Nothing. The like by the freshly minted profile is new, so it publishes and `ok`, `bridge_ok` and an empty `bridge_error` hold.

If minting fails, the like is anonymous. After the first run it is then a duplicate, which still returns `bridge_ok: true`.

**Regression risk: low.**
</impact>
<impact path="tests/run-installers-smoke.sh" element="like flow (649-686), verify_engine_event_recorded (~459-496), cleanup_engine_test_events (~498-585), delete_client_test_profile (~444-457)">
**What changes.** Nothing.
- The fresh profile's first like is new and publishes.
- The raw row exists under `actor_id = profile_id`.
- The cleanup deletes raw rows by actor and recomputes, which frees that derived id. That is harmless, because the profile is deleted and cannot replay.
- The profile delete now also removes `like_generations`.

**Regression risk: low.**
</impact>
<impact path="engine/server/db/jobs/tests/test-interaction-events.py" element="ingest contract script">
**What changes.** Nothing. The acceptance criteria require it to keep passing. It is not collected by `validate_tests.py`, so it must be run explicitly. It does not reference Client event ids or `fetch_popular_videos` (grep).

**Regression risk: none.**
</impact>
<impact path="engine/server/db/jobs/tests/test-security-bundle.py" element="security bundle checks">
**What changes.** Nothing. A grep found no reference to popular ordering, `signal_score`, Client ids or user-action. It must be run explicitly.

**Regression risk: none expected.**
</impact>
<impact path=".un/skills/devsecops/config.json" element="test_groups (test_profiles 18-21, groups at 37-40/45-46/56-85 naming server.py/users_store.py/profiles.py, test_random_videos 87-88)">
**What changes.** Nothing in this worktree. The existing mappings already re-run the affected groups when any of the four source files changes. A new test file needs an entry at harvest.

**Regression risk: low.**
</impact>
<impact path="tests/last_test_validation.json" element="tracked suite record">
**What changes.** The post-build run rewrites it. It conflicts on merge: take main's copy and re-run `validate_tests.py --compare`.

**Regression risk: none functionally.**
</impact>
<impact path="tests/last_test_output.txt" element="tracked captured output">
**What changes.** Rewritten by the post-build run. Resolve its merge conflict the same way as `last_test_validation.json`.

**Regression risk: none.**
</impact>
<impact path="delete_me/server.py.bak*" element="stale copies of server.py matched by grep">
**What changes.** Nothing. They are backups under `delete_me/` that match every symbol grep here (`record_like`, `_store_reaction`, `uuid4`). They must not be edited in place of `client/backend/server.py`.

**Regression risk: none.**
</impact>

## Documentation to update

- [x] `client/README.md` - updated: `client/README.md`: `POST /api/user-action` now says when each action publishes and how event ids are built. The likes import and profile delete entries now cover like generations.
- [x] `DEPLOYMENT.md` - updated: DEPLOYMENT.md: added the 25.0 popular signal cap (section 1) and the publish-on-change rule, the `like_generations` table and derived event ids (section 5).
- [x] `engine/server/api/recommendations/docs/OVERVIEW.md` - updated: OVERVIEW.md: the popular pool's order now reads `popularity` plus the interaction signal capped at `POPULAR_SIGNAL_CAP` (25.0), not "top by likes/views".
- [x] `engine/server/api/recommendations/docs/PIPELINE_DIAGRAM.md` - updated: Changed the popular-layer node label (line 29) from `top likes/views` to `popularity + capped signal`.
- [x] `engine/server/api/recommendations/docs/LAYER_PARAMS.md` - updated: Fixed the popular layer's **Source:** line (line 137). It now describes the actual pool order: `popularity` plus the capped interaction signal, then likes, then views.
- [x] `CONTEXT.md` - updated: Added the glossary term **Published like** to `CONTEXT.md`, which defines what counts as a real like/un-like change.
- [x] `docs/project/adr/0001-derived-interaction-event-ids.md` - updated: Added the like-generation scheme to ADR-0001's Consequences and said what "real state change" in decision 1 means. The decisions themselves are unchanged.
- [x] `docs/project/issues/01-deterministic-event-ids.md` - updated: Issue 01 is marked `bug, complete` with all 8 acceptance criteria ticked, and a copy is in `docs/project/issues/archive/`. The original file still needs deleting, because I can't delete files.
- [x] `docs/project/plans/13-deterministic-event-ids.md` - updated: Plan 13 is now marked delivered and points to `16-13-deterministic-event-ids.md`. Its risks describe the code as built, and a new Delivery section records what the build settled. The file has not been moved to `archive/` yet.
- [x] `docs/project/roadmap.md` - updated: Roadmap: security issue `01` is now listed as Delivered, removed from the open issues and the implementation order, and has its two remaining follow-ups added as optional M1 lines.
- [x] `docs/project/adr/0005-raw-event-retention-keeps-ids.md` - out of scope: Its claims (strip, don't delete; kept ids catch replays including the fixed anonymous `Like` id) are exactly what the build relies on, and nothing in it is made false.
- [x] `README.md` - out of scope: Lines 37-40 say only that interaction events update `interaction_signals`, which ranking uses. That is still true, and the file makes no claim about event ids or the popular ordering.

## Implementation plan

## Draft implementation: plan 13, derived event ids, publish on change, popular-signal cap

**Operator decision taken at this step.** The inventory left two loops for the operator: reset → re-like (+1 each pass) and import → undo_like (−1 each pass). The operator chose to close both with a published flag. So this draft departs from the settled plan and inventory in the places listed under "Deviations from the settled plan and inventory" at the end. Everything else follows the plan as approved.

### What has to be tested

| # | Behaviour | Where |
|---|---|---|
| T1 | Two profile `like` posts publish one `Like`. `likes_count` +1 and `signal_score` +1.0 | new `tests/active/test_event_ids.py` (stub Engine) |
| T2 | Profile like → undo_like → like publishes Like(g1), UndoLike(g1), Like(g2). The two Like ids differ and `signal_score` ends at 1.0 | same |
| T3 | Re-sending a published payload is `duplicate: true` and changes no counts | same |
| T4 | Two anonymous likes produce the same id, and the second is a duplicate | same |
| T5 | undo_like on an unliked video answers 200 and publishes nothing | same |
| T6 | A dislike that replaces a like publishes one UndoLike with the id the undo_like would have used. A dislike on an unliked video publishes nothing | same |
| T7 | Reset loop closed: like → reset → like publishes one Like. A later undo_like publishes the UndoLike for that same Like, and `signal_score` ends at 0 | same |
| T8 | Import loop closed: import X → undo_like X publishes nothing | same |
| T9 | Popular ordering: signal 1000 with popularity 0 ranks below popularity 30 with no signal, on both parameter branches | `tests/active/test_random_videos.py` |
| T10 | `delete_profile` removes the profile's `like_generations` rows and keeps another profile's | `tests/active/test_profiles.py` (existing delete test, extended) |
| T11 | Existing suites stay green | `validate_tests.py` |

### Module map

| File | Change |
|---|---|
| `client/backend/lib/users_store.py` | table in `ensure_user_schema`; `record_like` gains `publish=False` and returns `(opened, generation)`; new `like_generation` (reader) and `close_like` (writer) |
| `client/backend/lib/profiles.py` | `delete_profile` deletes `like_generations` |
| `client/backend/server.py` | `import hashlib`; `close_like` added to the `users_store` import; `_store_reaction` returns `(publish, generation)`; `_handle_user_action` gates on it and derives the id |
| `engine/server/data/random_videos.py` | `POPULAR_SIGNAL_CAP`; capped ORDER BY term; params reordered |
| `tests/active/test_event_ids.py` | new: T1–T8 |
| `tests/active/test_random_videos.py` | new T9 test |
| `tests/active/test_profiles.py` | `_seed_like` passes `publish=True`; `_rows_for` counts `like_generations`; the four delete asserts are updated |

### The like-generation state machine

This is the core invariant. Each `(profile, video)` row in `like_generations` holds `generation` and `published`.

| Event | Precondition | Effect | Publishes |
|---|---|---|---|
| keyed like (`record_like(publish=True)`) inserts a new `likes` row | no row | insert `(g=1, published=1)` | `Like` at g=1 |
| same | `published=0` | `g+=1`, `published=1` | `Like` at the new g |
| same | `published=1` (after a reset or trim, the Engine still holds this profile's Like) | nothing | nothing |
| keyed like, `likes` row already exists | any | refresh `video_uuid` / `updated_at` only | nothing |
| import (`record_like`, default `publish=False`) | any | `likes` row only; `like_generations` untouched | nothing |
| undo_like, or a dislike (`close_like`) | `published=1` | `published=0`, g unchanged | `UndoLike` at g |
| same | no row, or `published=0` | nothing | nothing |
| reset (`clear_likes`) | any | untouched | nothing |
| `delete_profile` | any | rows deleted | nothing |

**Invariant.** g changes only on the 0→1 transition, so while `published=1` it is constant. Every Like(g) is matched by at most one UndoLike(g), and the next Like gets g+1. Per profile and video, the Engine sees each id at most once, so the profile's net contribution is always 0 or +1. Both loops are closed by construction: reset leaves `published=1`, so the re-like publishes nothing, and import never opens a like, so its undo publishes nothing.

**Atomicity.** Opening and closing are single statements whose rowcount decides whether to publish. That is an `UPSERT ... DO UPDATE ... WHERE published = 0` for opening and an `UPDATE ... WHERE published = 1` for closing. Two concurrent requests can never both publish the same transition, and no request relies on a SELECT-then-write.

### `client/backend/lib/users_store.py`

`ensure_user_schema`: the docstring becomes "Create the users, likes, like generation, profile, block and dislike tables if missing." Insert this after `dislike_profiles` and before the `local-user` comment:

```sql
        CREATE TABLE IF NOT EXISTS like_generations (
          user_id TEXT NOT NULL,
          video_id TEXT NOT NULL,
          instance_domain TEXT NOT NULL,
          generation INTEGER NOT NULL,
          published INTEGER NOT NULL DEFAULT 0,
          PRIMARY KEY (user_id, video_id, instance_domain)
        );
```

`record_like`:

```python
def record_like(
    conn: sqlite3.Connection,
    user_id: str,
    action: str,
    video: dict[str, Any],
    max_likes: int,
    publish: bool = False,
) -> tuple[bool, int]:
    """Record a like with recency tracking.

    :param publish: The caller publishes a `Like` when this opens one. The likes import passes nothing, so an imported like never opens one.
    :returns: Whether this like opened the video's published like, and the video's like generation (0 when none was ever opened).
    """
    if action != "like":
        raise ValueError("Unsupported action")
    get_or_create_user(conn, user_id)
    video_id = str(video.get("video_id") or "")
    instance_domain = str(video.get("instance_domain") or "")
    video_uuid = video.get("video_uuid")
    now = now_ms()
    inserted = conn.execute(
        """
        INSERT INTO likes (user_id, video_id, instance_domain, video_uuid, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(user_id, video_id, instance_domain) DO NOTHING
        """,
        (user_id, video_id, instance_domain, video_uuid, now),
    ).rowcount > 0
    if not inserted:
        conn.execute(
            "UPDATE likes SET video_uuid = ?, updated_at = ? WHERE user_id = ? AND video_id = ? AND instance_domain = ?",
            (video_uuid, now, user_id, video_id, instance_domain),
        )
    opened = False
    if inserted and publish:
        # A like still published (the Engine holds it through a reset or trim) is not opened again.
        opened = conn.execute(
            """
            INSERT INTO like_generations (user_id, video_id, instance_domain, generation, published)
            VALUES (?, ?, ?, 1, 1)
            ON CONFLICT(user_id, video_id, instance_domain)
            DO UPDATE SET generation = like_generations.generation + 1, published = 1
            WHERE like_generations.published = 0
            """,
            (user_id, video_id, instance_domain),
        ).rowcount > 0
    generation = like_generation(conn, user_id, video_id, instance_domain)
    if max_likes > 0:
        ...  # trim unchanged
    conn.commit()
    return opened, generation
```

- When the DO UPDATE's WHERE is false, SQLite treats the conflict as DO NOTHING, so `changes()` is 0 and `rowcount` is 0.
- The `inserted` flag is taken from the INSERT's own cursor before any other statement runs.

New functions, placed after `remove_like`:

```python
def like_generation(conn: sqlite3.Connection, user_id: str, video_id: str, instance_domain: str) -> int:
    """Return the profile's like generation for one video.

    :returns: The generation, or 0 when no like of it was ever published.
    """
    row = conn.execute(
        "SELECT generation FROM like_generations WHERE user_id = ? AND video_id = ? AND instance_domain = ?",
        (user_id, video_id, instance_domain),
    ).fetchone()
    return int(row[0]) if row else 0


def close_like(conn: sqlite3.Connection, user_id: str, video_id: str, instance_domain: str) -> tuple[bool, int]:
    """Close the profile's published like of one video, inside the caller's transaction.

    :returns: Whether a published like was closed, so an `UndoLike` is due, and the generation that like was published under.
    """
    closed = conn.execute(
        "UPDATE like_generations SET published = 0 WHERE user_id = ? AND video_id = ? AND instance_domain = ? AND published = 1",
        (user_id, video_id, instance_domain),
    ).rowcount > 0
    return closed, like_generation(conn, user_id, video_id, instance_domain)
```

- `row[0]` works with or without `row_factory`.
- `remove_like` and `clear_likes` are unchanged.

### `client/backend/lib/profiles.py`

In `delete_profile`, add `conn.execute("DELETE FROM like_generations WHERE user_id = ?", (profile_id,))` after the `likes` delete, inside the same `with conn:`.

### `client/backend/server.py`

Imports:
- `import hashlib` goes between `argparse` and `ipaddress`.
- `from uuid import uuid4` stays, because `run_id` still uses it.
- `users_store` import: `(clear_likes, close_like, ensure_user_schema, fetch_recent_likes, get_or_create_user, load_liked_keys, record_like, remove_like, video_reaction)`. `like_generation` is not imported, since the server does not need it.

`_store_reaction` (annotation `-> tuple[bool, int]`):

```python
        """...
        :returns: Whether to publish, a `Like` for a like and an `UndoLike` otherwise, and the like generation the event is published under.
        ...
        """
        conn = self.server.user_db
        key = (video["video_id"], video["instance_domain"])
        if action == "undo_like" or (action == "like" and not is_disliked(conn, profile_id, *key)):
            with conn:
                if action == "like":
                    result = record_like(conn, profile_id, "like", video, MAX_LIKES, publish=True)
                else:
                    remove_like(conn, profile_id, *key)
                    result = close_like(conn, profile_id, *key)
            return result
        entries = ...  # unchanged
        if action == "dislike":
            ...  # limit check and centroids unchanged, before any write
            with conn:
                remove_like(conn, profile_id, *key)
                withdrawn = close_like(conn, profile_id, *key)
                write_dislike(conn, profile_id, video, centroids)
            return withdrawn
        # undo_dislike, or a like replacing a dislike.
        centroids = ...  # unchanged
        result = (False, 0)
        with conn:
            delete_dislike(conn, profile_id, *key, centroids)
            if action == "like":
                result = record_like(conn, profile_id, "like", video, MAX_LIKES, publish=True)
        return result
```

- The un-like decision comes from the flag, not from `remove_like`'s result. `remove_like` still removes the row, so reaction state is unchanged.
- An un-like after a reset therefore still withdraws the Like the Engine holds. An un-like of an imported like, or of one that predates the table, withdraws nothing.

`_handle_user_action` (docstring: "Apply one like/dislike action and publish the `Like`/`UndoLike` it causes, if any."):

```python
        publish = action in ("like", "undo_like")
        generation = 0  # the fixed generation of anonymous likes
        if profile_id is not None:
            try:
                publish, generation = self._store_reaction(profile_id, action, video)
            except DislikeLimitReached:
                ...  # unchanged
            except EngineApiError as exc:
                ...  # unchanged
            # A profile publishes only a like it opens or closes. A dislike publishes only to withdraw a like it replaced.
        if not publish:
            respond_json(self, 200, {"ok": True, "updatedAt": now_ms()})
            return

        event_type = "Like" if action == "like" else "UndoLike"
        actor = profile_id or "anonymous"
        # The JSON list keeps field boundaries unambiguous. Its encoding is part of every id, so it must never change.
        identity = json.dumps([actor, canonical_uuid, canonical_host, event_type, generation])
        event_payload = {
            "event_id": "client-" + hashlib.sha256(identity.encode("utf-8")).hexdigest(),
            "event_type": event_type,
            "actor_id": actor,
            ...  # object, published_at, source_instance, raw_payload unchanged
        }
```

`generation` is always an `int`: it comes from `int(row[0])`, the literal `1`, or `0`.

### `engine/server/data/random_videos.py`

After the imports:

```python
# The most of a video's interaction signal the popular ordering adds; the stored signal_score stays raw.
POPULAR_SIGNAL_CAP = 25.0
```

In `fetch_popular_videos`:
- docstring: "Return the most popular videos: popularity plus the capped interaction signal, then likes and views."
- `params: list[Any] = [POPULAR_SIGNAL_CAP, limit, limit]`
- the threshold branch sets `params = [error_threshold, POPULAR_SIGNAL_CAP, limit, limit]`
- the first ORDER BY term becomes `(v.popularity + MIN(COALESCE(sig.signal_score, 0), ?)) DESC,`

The placeholder order is: `{error_clause}` `?`, the cap `?`, the inner `LIMIT ?`, then the outer `LIMIT ?`. The `interaction_signal_score` column and the likes tiebreaker are untouched.

### Tests

**`tests/active/test_event_ids.py`** (new). It needs no live Engine or shared `whitelist.db` and is not rate-limited.

Module docstring: the T1–T8 bullets. Setup:
- Add `engine/server` and `engine/server/api` to `sys.path`, as `test_random_videos.py` does.
- Import `ensure_interaction_event_schema` and `ingest_interaction_event`.
- From conftest, import `RateLimiter`, `client_server` and `ensure_user_schema`.

Harness:
- `_serving(srv)`: copied from `test_server.py`, about 8 lines.
- A fixture `rig(tmp_path)` that yields `(client, engine_db, events)`:
  - `engine_db` is `sqlite3.connect(tmp_path / "engine.db", check_same_thread=False)` with `row_factory = sqlite3.Row`, after `ensure_interaction_event_schema`.
  - `events` is the list of `(payload, result)` pairs.
  - An `EngineStub(BaseHTTPRequestHandler).do_POST` routes three paths:
    - `/internal/videos/resolve`: answers `{"video": {"video_id": "vid-" + uuid, "instance_domain": host, "video_uuid": uuid, "video_url": f"https://{host}/w/{uuid}"}}`.
    - `/internal/dislikes/centroids`: answers `{"space": "test", "centroids": []}`, which `compute_dislike_centroids` turns into None.
    - `/internal/events/ingest`: runs `ingest_interaction_event(engine_db, payload)` under a lock, appends `(payload, result)`, and answers `{"ok": True, "duplicates": int(result["duplicate"]), "results": [result]}`. This is the real ingest, not a mock.
  - The Client is a `ClientBackendServer` on `tmp_path/"users.db"` in `"bridge"` mode with `RateLimiter(1000, 60)`, wrapped in conftest's `ClientBackend`.
- Helpers:
  - `_video()` returns a fresh `{"uuid": uuid4().hex, "host": "ids.example"}`.
  - `_act(client, headers, action, video)` posts `/api/user-action` and returns the status.
  - `_signal(engine_db, video)` returns `(likes_count, signal_score)`, or `(0, 0.0)`.
  - `_published(events)` returns `[(p["event_type"], p["event_id"]) for p, r in events]`.

Cases:
- **T1.** Mint, then like twice. Both answer 200. One event, a `Like`. `_signal == (1, 1.0)`.
- **T2.** Like, undo_like, like. The types are `[Like, UndoLike, Like]`. `ids[0] == ids[1]` is false, because the types differ. `ids[0] != ids[2]`. `ids[0]` equals the expected sha256 of `[profile_id, uuid, host, "Like", 1]`, which pins the encoding, and `ids[2]` uses generation 2. The final signal score is 1.0.
- **T3.** Take the first T1 payload and call `ingest_interaction_event(engine_db, payload)` again. `duplicate is True` and `_signal` is unchanged.
- **T4.** Anonymous like twice. Both ids are equal, the second result has `duplicate is True`, and `_signal == (1, 1.0)`.
- **T5.** Mint, then undo_like on a fresh video. Status 200 and no events.
- **T6.** Mint, like, dislike. There are exactly two events, and the second is an `UndoLike` whose id equals sha256 of `[pid, uuid, host, "UndoLike", 1]`, the id an undo_like at g1 would have used. Then, on a second fresh video, a dislike answers 200 and adds no event.
- **T7.** Mint, like, `POST /api/user-profile/reset` with the key, like again. Only one `Like` has been published. Then undo_like gives exactly one `UndoLike` at g1, and `_signal == (0, 0.0)`.
- **T8.** Mint, `POST /api/profile/likes/import` with the key and `{"likes": [{"video_uuid": uuid, "instance_domain": host}]}`, then undo_like. There are no events.
  - This depends on the stub's `resolve_videos_by_uuid_host` path. I have not read its endpoint yet (`engine_api_client.py:136-166`); the builder reads it and adds the matching stub route.
  - If that route turns out to cost more than about 15 lines, fall back to seeding with `record_like(conn, pid, "like", video, 100)` without `publish` on the users.db. That is exactly the call the import makes.

**`tests/active/test_random_videos.py`** gets `test_the_popular_order_caps_the_interaction_signal(tmp_path)`:
- `_two_video_db`, then `UPDATE videos SET popularity = 0` on `first` and `30` on `second`.
- `INSERT INTO interaction_signals (video_uuid, instance_domain, likes_count, signal_score, updated_at) VALUES (?, ?, 0, 1000.0, 0)` for `first`, then commit.
- For `threshold in (None, 1)`, `fetch_popular_videos(conn, 10, error_threshold=threshold)` returns `[second, first]` by `video_id`, and `first`'s `interaction_signal_score == 1000.0`, which shows the stored value is still raw.
- `_set_views` sets `error_count = 0`, so threshold 1 keeps both rows.
- Add a docstring bullet.
- A wrong params order either makes the cap act as the error threshold, which drops rows, or turns the limits into the cap. Both break one of the two branches.

**`tests/active/test_profiles.py`**:
- `_seed_like` passes `publish=True` to `record_like`.
- `_rows_for` adds `"like_generations": conn.execute("SELECT COUNT(*) FROM like_generations WHERE user_id = ?", (profile_id,)).fetchone()[0]`.
- The asserts at 205, 209 and 216 gain `"like_generations": 1`, and the one at 215 gains `"like_generations": 0`.
- The comment at 201 becomes "record_like also creates the `users` row and opens a like generation, so all four tables hold rows for both."
- `test_frontend_profile.py`'s `_seed_like` stays as it is (`publish` defaults to False).

### Existing tests, walked through with the flag

- `test_frontend_reactions` keyed sequence:
  - like: opens g1 and publishes.
  - dislike: closes g1, publishes UndoLike(g1).
  - undo_dislike: publishes nothing.
  - out-of-band dislike: nothing to close, 200.
  - like replacing the dislike: opens g2 and publishes.
  - undo_like: UndoLike(g2).
  - The same shape as the settled walk-through, so `all("ok" in a)` holds.
- The card test and `test_profiles.py:300`: a fresh profile's first like opens and publishes, so still 502 on `unpublished_client`.
- `test_dislikes` 74-87:
  - line 77 closes the like opened at line 74, which publishes, so 200 or 502;
  - line 82: 200;
  - line 84: nothing to close, 200.
- Keyless tests: unchanged from the inventory's account.
- Smokes: a fresh profile's first like opens and publishes, and the raw row is keyed by the profile.

### Acceptance criteria → evidence

| Criterion | Holds because | Test |
|---|---|---|
| Double like, one Like, +1 / +1.0 | second INSERT rowcount 0, nothing is opened | T1 |
| like→undo→like, distinct Like ids, 1.0 | g1 opened, closed, then g2 opened | T2 |
| Bridge retry is a duplicate | same id, `ON CONFLICT(event_id) DO NOTHING` | T3 |
| Anonymous duplicate | generation 0 and actor `anonymous` give a fixed id | T4 |
| undo_like of an unliked video: 200, nothing | nothing to close | T5 |
| Dislike UndoLike id = the undo_like id; unliked dislike publishes nothing | both go through `close_like` | T6 |
| Signal 1000 / pop 0 below pop 30 | `MIN(1000, 25) = 25 < 30` | T9 |
| `delete_profile` removes generations | new DELETE | T10 |
| Existing suites | walk-through above | T11 |

### Deviations from the settled plan and inventory

All of these follow from the operator's "close both with a published flag". None is silent.

1. **Schema.** `like_generations` gains `published INTEGER NOT NULL DEFAULT 0`. The inventory's DDL lists only four columns.
2. **When generation increments.** Only when a like is opened, that is, a new `likes` row from a publishing caller while `published=0`. The requirement says "on every new likes row". A re-like after a reset or trim, and every imported like, now leaves it unchanged. The contract still holds: a Like and its un-like share a generation, and the next Like differs.
3. **Un-like gating.** Publishing depends on `close_like`, not on `remove_like`'s result. `remove_like` is still called and still removes the row.
4. **`record_like` signature.** It gains the keyword `publish: bool = False`. `_handle_likes_import` (plan 14's handler) and the tests' `_seed_like` helpers keep working unedited. `record_like` returns `(opened, generation)` rather than `(new, generation)`.
5. **Reader.** The inventory's reader exists as `like_generation(conn, user_id, video_id, instance_domain) -> int`, with the positional shape and `:returns:`. The server imports the new writer `close_like` instead of the reader, so the users_store import line gains `close_like`.
6. **`test_profiles._seed_like`** passes `publish=True`. The inventory assumed `record_like` would always write a generation row.
7. **Plan Risks, "imported likes advance the generation, a later un-like publishes UndoLike (−1)".** This no longer happens: an imported like never publishes either event.

### Risks

- **Likes that predate `like_generations`.** They have no row, so their un-like publishes nothing. The Engine keeps the +1 from the old random-id Like. The un-like side is bounded at 0, where the settled plan would have published a gen-0 UndoLike.
- **Publish failure after the flag opens or closes** (bridge down, or `unpublished_client`). The Client's state moves while the Engine misses the event, and nothing retries it. Worst case, a later close publishes an UndoLike the Engine never saw a Like for. That is −1 once per generation, floored at 0. The settled plan had the same gap.
- **Trim gap.** It is narrower as a side effect: a re-like after a trim publishes nothing and a later un-like withdraws. It stays open when the profile never re-likes.
- **Anonymous import.** A like the browser published anonymously and then imported is never withdrawn by the profile. This falls under ADR-0001 §3's anonymous +1.
- **Concurrency.** Opening and closing are single conditional statements, so two concurrent requests cannot publish one transition twice. The existing dislike rat-tail is unchanged.
- **Merge with plan 14.** The import-line edits (`hashlib`, `close_like`) resolve by union. Its import caller is untouched.

### Documentation changes from the settled checklist

- `client/README.md` line 19: "an un-like publishes only when it withdraws a like the profile published, and a reset or import publishes nothing and never re-publishes".
- `CONTEXT.md` **Like generation**: add "and whether its like is published".
- ADR-0001 Consequences: add the published flag, the closed loops, the legacy-like note and the import note.
- `docs/project/roadmap.md`: drop the "close the reset/import loops" follow-up. Keep the import-publishing item, the likes-tiebreaker item, and a narrowed trim-gap item.

### Convergence

Pass 1 checked the draft against the plan and requirements, with the operator decision applied. Every requirement is met or listed above as an approved deviation. Pass 2 found `_seed_like` needing `publish=True` and the dislike branch's `close_like` placement, and added both. No further change was needed.

### Phases

#### Phase 1 - Popular signal cap [code]

**Files touched.** engine/server/data/random_videos.py (EDITED), tests/active/test_random_videos.py (EDITED)

**Checkpoint.** T9, `test_the_popular_order_caps_the_interaction_signal(tmp_path)` in tests/active/test_random_videos.py. The seam is a direct call to `fetch_popular_videos(conn, 10, error_threshold=threshold)` on the isolated tmp engine.db built by the existing `_two_video_db` harness, so the file's own tests are the precedent. Setup: `first` gets popularity 0, `second` gets popularity 30, and an `interaction_signals` row gives `first` a signal_score of 1000.0 with likes_count 0. The test runs for threshold in (None, 1), an explicit set covering both params branches. It asserts that the result order by `video_id` is [second, first]. As a control it asserts that `first`'s `interaction_signal_score == 1000.0`, so the stored score is shown to be raw. `_set_views` sets error_count = 0, so threshold 1 keeps both rows. A wrong params order therefore breaks at least one branch.

**Intent.** `fetch_popular_videos` in engine/server/data/random_videos.py orders videos by popularity plus the interaction signal capped at the module constant `POPULAR_SIGNAL_CAP`.

- C1 - A video with signal 1000 and popularity 0 ranks below a video with popularity 30 and no signal, with and without an error threshold.

**Outcome.** ### `engine/server/data/random_videos.py`
- Added the module constant `POPULAR_SIGNAL_CAP = 25.0`. It has a one-line comment saying why it exists: a burst of interaction events should not be able to outrank crawled popularity.
- `fetch_popular_videos` now ranks by `v.popularity + MIN(COALESCE(sig.signal_score, 0), ?)` instead of `v.popularity + COALESCE(sig.signal_score, 0)`. The cap is a bound parameter. It sits in `params` after the optional error threshold and before the two `limit`s, which matches where each `?` appears in the SQL. This is true with and without an error threshold.
- The tie-breakers after the popularity term are unchanged (likes plus signal likes, views, published_at, video_id).
- The returned `interaction_signal_score` column is unchanged and still reports the raw, uncapped signal.

### `tests/active/test_random_videos.py`
Not changed. It only uses a signal of 1.0, well under the cap, so the cap doesn't affect it. It has no expectation that conflicts with this change, so this phase had no reason to edit it.

#### Phase 2 - Publish on change, derived ids [code]

**Files touched.** client/backend/lib/users_store.py (EDITED), client/backend/server.py (EDITED), tests/active/test_event_ids.py (NEW)

**Checkpoint.** T1–T8 in tests/active/test_event_ids.py (NEW). The seam is HTTP POST to /api/user-action, /api/user-profile/reset and /api/profile/likes/import on a real `ClientBackendServer` in "bridge" mode over a tmp users.db, with `RateLimiter(1000, 60)`. It follows the `_serving` / `_client_backend` harness in test_server.py and is wrapped in conftest's `ClientBackend`. The Engine is a `BaseHTTPRequestHandler` stub with three routes. `/internal/videos/resolve` echoes a video. `/internal/dislikes/centroids` answers with empty centroids. `/internal/events/ingest` runs the real `ingest_interaction_event` on a tmp engine.db under a lock and records (payload, result). Assertions are made at the Engine boundary: the published (event_type, event_id) list and `interaction_signals` (likes_count, signal_score).
Clause 1: T1 (double like gives one Like, (1, 1.0)). T5 (undo_like of an unliked video answers 200 with no event). T6b (dislike of an unliked video adds no event). T7 (like, reset, like publishes one Like, and the later undo_like gives one UndoLike, ending at (0, 0.0)). T8 (import then undo_like gives no events). For T8, the builder reads engine_api_client.py:136-166 and adds the resolve-by-uuid stub route. If that route costs more than about 15 lines, the test seeds with `record_like` without `publish`.
Clause 2: T2 (like → undo_like → like gives [Like, UndoLike, Like]; ids[0] equals sha256 of json.dumps([pid, uuid, host, "Like", 1]); ids[2] uses generation 2 and differs from ids[0]; the signal ends at 1.0). T3 (re-ingesting T1's payload returns duplicate True and leaves the counts unchanged). T4 (two anonymous likes carry equal ids, the second is a duplicate, and the signal is (1, 1.0)). T6a (a dislike replacing a like publishes an UndoLike whose id is sha256 of [pid, uuid, host, "UndoLike", 1]).

**Intent.** A profile's POST /api/user-action publishes a Like or UndoLike only when it opens or closes that profile's published like of the video, tracked in the new `like_generations` table by `record_like(publish=True)` and `close_like` in users_store.py, and every event `_handle_user_action` publishes carries an id derived from actor, video, event type and like generation.

- C1 - An action that neither opens nor closes the profile's published like of the video publishes no event.
- C2 - A published event's id is `client-` plus the SHA-256 of the JSON list of actor, canonical uuid, canonical host, event type and like generation.

**Outcome.** ### `client/backend/lib/users_store.py`
- `ensure_user_schema` now also creates `like_generations(user_id, video_id, instance_domain, generation INTEGER NOT NULL, published INTEGER NOT NULL DEFAULT 0)`, keyed on `(user_id, video_id, instance_domain)`, with `CREATE TABLE IF NOT EXISTS`. It sits before the `local-user` cleanup, and the docstring names the new table.
- `record_like` takes a new keyword `publish: bool = False` and returns `(opened, generation)`.
  - The `likes` INSERT is now `ON CONFLICT DO NOTHING`, and its own rowcount decides whether the like is new. An existing row gets a plain UPDATE of `video_uuid`/`updated_at`, so recency and the trim work as before.
  - A new like with `publish=True` runs a conditional upsert on `like_generations`. It inserts `(g=1, published=1)`, or sets `g+1, published=1` only when `published = 0`. The rowcount is `opened`.
  - A re-like after a reset or trim, while the like is still published, therefore opens nothing. An imported like (`publish` left False) never touches `like_generations`.
  - The trim and the commit are unchanged. The import caller ignores the return value.
- New `like_generation(conn, user_id, video_id, instance_domain) -> int` returns the stored generation, or 0 when there is no row. It uses `row[0]`, so it works with or without a `row_factory`.
- New `close_like(conn, user_id, video_id, instance_domain) -> tuple[bool, int]` runs `UPDATE ... SET published = 0 ... AND published = 1`. It returns whether a published like was closed, plus that like's generation. It does not commit: it runs inside the caller's transaction, like `remove_like`.

### `client/backend/server.py`
- Added `import hashlib`. `close_like` joins the `lib.users_store` import. `uuid4` stays because `run_id` still uses it.
- `_store_reaction` now returns `(publish, generation)`:
  - plain like, and like replacing a dislike: `record_like(..., publish=True)`;
  - undo_like: `remove_like` then `close_like`, in the same `with conn`;
  - dislike: `remove_like`, `close_like` and `write_dislike` in the existing write transaction, still after the limit check and the centroids request;
  - undo_dislike: `(False, 0)`.
  - The `:returns:` docstring is rewritten.
- `_handle_user_action`:
  - Anonymous requests keep `publish = action in ("like", "undo_like")` at generation 0. A profile's request publishes only what `_store_reaction` reports. A no-change request falls through to the existing 200 `{ok, updatedAt}`.
  - `actor = profile_id or "anonymous"` is computed once and used for both the id and `actor_id`.
  - `event_id` is `"client-" + sha256(json.dumps([actor, canonical_uuid, canonical_host, event_type, generation]))`. It hashes the Engine-resolved uuid and host, not the spelling sent.
  - The docstring now states the publish rule. Other payload fields and the error paths are unchanged.

### `tests/active/test_event_ids.py`
Not created. The gating checkpoint `tests/tmp/test_13_deterministic_event_ids_phase2.py` covers T1–T8. I left moving it into `tests/active` to the workflow rather than make a copy.

**Beyond the files named.** tests/tmp/probe_like_generations.py: a throwaway probe I wrote to check SQLite's behaviour. When the `DO UPDATE ... WHERE` condition is false, the upsert reports rowcount 0. The probe ran the new users_store functions through open, repeat, close, re-open, reset and import. It passed, and every step returned the `(opened/closed, generation)` it should. I have no delete tool, so it is still there; please delete it. Running it also rewrote `tests/last_test_validation.json` and `tests/last_test_output.txt` with that one probe's result.

#### Phase 3 - Delete removes generations [code]

**Files touched.** client/backend/lib/profiles.py (EDITED), tests/active/test_profiles.py (EDITED)

**Checkpoint.** T10: extend the existing `test_deleting_a_profile_removes_its_rows_and_keeps_anothers` in tests/active/test_profiles.py. The seam is HTTP POST /api/profile/delete on conftest's `client_backend`, with row counts read straight from users.db through `_rows_for`, following the precedent in this test. `_seed_like` passes `publish=True`. `_rows_for` adds a `like_generations` count. The asserts at 205, 209 and 216 expect `"like_generations": 1`, and the one at 215 expects `"like_generations": 0`. The comment at 201 is updated to say all four tables hold rows.

**Intent.** `delete_profile` in client/backend/lib/profiles.py removes the deleted profile's `like_generations` rows inside its existing transaction.

- C1 - After one profile is deleted, it has no `like_generations` rows and another profile keeps its rows.

**Outcome.** ### client/backend/lib/profiles.py
`delete_profile` now also runs `DELETE FROM like_generations WHERE user_id = ?` inside its existing `with conn:` transaction, right after the `likes` delete. It deletes by `user_id`, not by the likes it just removed, so closed generations (rows left behind after an undone like) go too. The table has no foreign keys, so the order of the deletes doesn't matter.

### tests/active/test_profiles.py
Not changed. The phase lists it as EDITED, but it is a durable test that has already gated, so this step can't touch it. Its `test_deleting_a_profile_removes_its_rows_and_keeps_anothers` still holds, because it only counts `profiles`, `users` and `likes`. Moving the checkpoint's `like_generations` assertions into this file is left to the promotion step.


