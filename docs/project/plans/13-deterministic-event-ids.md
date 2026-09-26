# Derive interaction event ids and cap the signal in the popular ordering

## Requirements

### What was asked for

Build issue `docs/project/issues/01-deterministic-event-ids.md` as triaged: Derive interaction event ids so replays collapse at ingest, and cap the interaction signal's effect on the popular ordering. The Agent Brief below, copied from the issue, is the confirmed requirement set; the build starts from this file.

### Purpose

Close the security-audit finding the issue records. This build is one of issues 01-06, delivered concurrently to use as little operator time and cause as few merge conflicts as possible.

### Decisions this rests on

`docs/project/adr/0001-derived-interaction-event-ids.md`; `CONTEXT.md` **Interaction event**, **Interaction signal**.

### Agent Brief

**Category:** bug
**Summary:** Derive interaction event ids so replays collapse at ingest, and cap the interaction signal's effect on the popular ordering

**Current behavior:**
When a visitor posts a `like` or `undo_like` user action, the Client backend publishes an interaction event with a freshly generated random `event_id` (`client-<uuid4>`). It publishes on every request, even when the profile already likes the video (or, for `undo_like`, does not). A request without `X-Profile-Key` is published as actor `anonymous`. The Engine ingests idempotently on `event_id`, but because every id is new, each repeated `Like` adds `+1.0` to the video's `interaction_signals.signal_score`. The Engine's popular pool orders by `popularity + signal_score` with no bound, so repeated posts can push any video to the top. A dislike that replaces a like publishes an `UndoLike` the same way.

**Desired behavior:**
- **Profile, publish on change only.** A `like` publishes a `Like` only when the profile did not already like the video. An `undo_like` publishes an `UndoLike` only when a like was actually removed. A dislike that replaces a like still publishes an `UndoLike` (it already does so only when a like was removed). A no-change request still returns 200 and publishes nothing.
- **Profile, derived id.** The `event_id` is a deterministic function of actor, `video_uuid`, `instance_domain`, `event_type`, and a *like instance*. The instance must be the same for every publish of one like and of the un-like that ends it, and different for a like made after that un-like. There is no per-video like counter today: the `likes` row is deleted on un-like, so the agent must choose where the instance comes from, and it must survive the un-like. Any scheme meeting this contract is acceptable.
- **Anonymous, derived id.** Actor `anonymous` uses a fixed instance, so every anonymous `Like` on a video carries one id and every anonymous `UndoLike` on it carries another.
- The id must not embed raw user input unhashed; a hash (e.g. SHA-256 hex, with a prefix such as `client-`) over the joined fields is expected. It must stay a non-empty string that the Engine's `normalize_event_payload` accepts.
- **Ranking cap.** The Engine's popular-pool ordering uses `popularity + MIN(COALESCE(signal_score, 0), C)`, where `C` is a named module-level constant set to `25.0`. `interaction_signals.signal_score` itself is still stored uncapped.

**Key interfaces:**
- The Client backend's user-action handler (currently `_handle_user_action`) and the event payload it builds for `_publish_event`: the `event_id` field and the decision whether to publish.
- `record_like()` in the client users store currently returns `None`. It needs to report whether the like was new (or the handler must check the like state first), so the handler can gate publishing.
- `remove_like()` already returns whether a like was removed; the `undo_like` path should use it.
- The Engine's popular-pool query (the one ordering by `v.popularity + COALESCE(sig.signal_score, 0)`) and a new constant beside it.
- `ingest_interaction_event()` / `normalize_event_payload()` in the Engine: **unchanged**. The existing `ON CONFLICT(event_id) DO NOTHING` does the collapsing.

**Acceptance criteria:**
- [ ] Posting `like` twice for one video with one profile publishes exactly one `Like`; the video's `likes_count` and `signal_score` rise by 1 and 1.0.
- [ ] A profile's like → undo_like → like sequence publishes Like, UndoLike, Like, and the two `Like` events carry different `event_id`s. The video ends with `signal_score` 1.0.
- [ ] Re-sending an identical already-published event to the Engine (a bridge retry) is reported as `duplicate: true` and changes no counts.
- [ ] Two anonymous `like` posts for one video produce the same `event_id`, and the Engine counts the second as a duplicate.
- [ ] `undo_like` for a video the profile does not like publishes nothing and returns 200.
- [ ] A dislike replacing a like publishes one `UndoLike`, with the id the matching profile un-like would have used; a dislike on an unliked video publishes nothing.
- [ ] In the popular ordering, a video with `signal_score` 1000 and `popularity` 0 ranks below a video with `popularity` 30 and no signal (the cap bounds the signal at 25.0).
- [ ] The existing interaction-event and security-bundle test suites still pass.

**Out of scope:**
- Backfilling or rewriting events already stored with random ids.
- Changing Engine ingest, `_event_deltas` weights, or the stored `signal_score`.
- The secondary likes tiebreaker in the popular ordering (`likes + likes_count`, net of undos since plan 08); it only breaks ties and is left uncapped.
- `Comment` events (the Client does not publish them today).
- Rate limiting, or requiring a profile for likes.
- The likes-import path, which publishes nothing.

### Consistency constraints

- Match the surrounding code's style: stdlib HTTP handlers, `respond_json`, module-level named constants, and env vars read once at startup.
- Backwards compatibility is not required beyond what the brief states.
- Run `validate_tests.py` from the root of the tree this build runs in (a worktree for waves 1-2, main for wave 3). That tree's `.un` config carries it as `project_dir`.

### Batch context

Part of the security hardening batch (`.scratch/security-hardening-batch/notes.md`): issues 01-06 delivered in three waves of git worktrees. Wave 1 is plans 10, 11 and 12. Wave 2 is 13 and 14, branched from main after wave 1 merges. Wave 3 is 15, on the merged main. A wave 1 or 2 build runs in its own worktree created by `.scratch/security-hardening-batch/worktree-setup.sh`, merges to main when it closes, and is harvested on main, not in the worktree.

Wave 2, branched from main after plans 10-12 merge, and running alongside plan 14. Both plans edit `client/backend/server.py`, in different handlers. Both also edit `client/backend/lib/users_store.py`: this plan changes what `record_like` returns, and plan 14's import calls `record_like` and ignores the return value.

### Conflicts

The brief does not conflict with the tree. Every function and line it names was checked against the source on 2026-09-26 (`.scratch/security-hardening-batch/notes.md`, File overlap). Line numbers will drift once earlier waves merge, so re-locate by function name at Step 3.

## High-level plan

### Approach

**Like instance.** The brief leaves its source to the build. The approved design is a new Client table `like_generations(user_id, video_id, instance_domain, generation)`. `ensure_user_schema` creates it with `CREATE TABLE IF NOT EXISTS`, and an un-like never deletes from it.
- A `like` that inserts a new `likes` row increments the generation. `record_like` reports whether the like was new and returns the generation.
- An `undo_like`, or a dislike that replaces a like, reads the video's current generation and removes the like with `remove_like`. It publishes only when a like was removed.
- Anonymous actors use a fixed generation `0`.

**Id.** The user-action handler sets `event_id` to `client-` followed by the SHA-256 hex of the joined `(actor, video_uuid, instance_domain, event_type, generation)`, replacing `client-<uuid4>`. Actor is the profile id, or `anonymous`.

**Publish on change only.** In `_handle_user_action` (`server.py:684`), `publish` is true only for a new like or when a like was removed. A request that changes nothing still returns 200.

**Ranking cap.** `engine/server/data/random_videos.py:247` orders by `v.popularity + MIN(COALESCE(sig.signal_score, 0), C)`, where `C` is a module-level constant set to `25.0`. Ingest, `_event_deltas` and the stored score are unchanged.

### Alternatives considered

- **A column on `likes`.** Rejected: an un-like deletes the row, so the instance would not survive to tell the next like apart.
- **The like's timestamp as the instance.** Rejected: it does not follow from stored state, so retrying a request after a partial failure could produce a second id.
- **The key without an instance** (the issue's step 1). Rejected at triage (ADR-0001): it drops genuine re-likes and lets any visitor permanently zero a video's anonymous contribution.

### Risks and limitations

- **Trimmed likes.** When the `max_likes` trim in `record_like` drops a like, the Engine keeps its `+1`. A later un-like finds nothing to remove and publishes nothing. This gap exists today, and the plan does not close it.
- `like_generations` gains one row for each (profile, video) pair ever liked. It stays small. If a profile-deletion path exists, it should also remove that profile's rows; the build checks at Step 3.
- Likes import (plan 14's path) also calls `record_like`. The new return value must not break that caller; import publishes nothing.
- **Shared `whitelist.db`.** The worktree symlinks the main tree's `whitelist.db`, so this build's test Engines write interaction rows into the same file as other lanes, and as the live Engine if it runs. Every test run already does this; worktrees only make it concurrent.
- **Tracked test record.** `tests/last_test_validation.json` and `tests/last_test_output.txt` always conflict on merge. Take main's copy and re-run `validate_tests.py --compare` on the merged tree.
- **Engine rate limit.** Run Engine-backed test files in their own `validate_tests.py` invocations (memory `engine-rate-limit-single-lane-test-runs`).

### Tradeoffs accepted

Anonymous likes add at most +1 per video, permanently. Events stored before this change keep their random ids and are not backfilled.
