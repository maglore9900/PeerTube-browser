# Deterministic event ids and bounded ranking influence

Status: bug, ready-for-agent
Origin: task 80, SI3-M1 — security audit run 1, finding F5

## Problem

`_handle_client_publish_event` fills in a fresh `event_id` when one is absent, defeating the ingest idempotency key, and each `Like` adds `+1.0` to `interaction_signals.signal_score`, which orders the popular pool.

## Proposed solution

Collapse replays and cap the ranking contribution.

1. Derive `event_id` deterministically from `(actor_id, video_uuid, instance_domain, event_type)` instead of generating a random id when absent (today: `client/backend/server.py` builds `f"client-{uuid4()}"`).
2. Confirm the existing idempotency path in `engine/server/data/interaction_events.py` now collapses repeated posts.
3. Cap the `signal_score` contribution used in the popular ordering at `engine/server/data/random_videos.py:247` so accumulated signal cannot dominate `popularity`.

## Related

- The un-like paths of `docs/project/plans/03-like-dislike.md` shipped without this fix, by operator decision at that build's Step 1 (Q5). `undo_like`, and a dislike that replaces a like, publish `UndoLike` with a random `event_id` today, so a deterministic scheme here must cover `UndoLike` as well as `Like`. A dislike itself publishes nothing.

## Comments

**Triage.** Claim confirmed against the code, with two corrections to the problem statement. The publishing handler is `_handle_user_action`, not `_handle_client_publish_event`. It does not fill in an id "when absent": it assigns a random `client-<uuid4>` to every `Like` and `UndoLike`, whatever the request carries. Repeating `like` on one video, with or without a profile, publishes a new event each time, and each adds `+1.0` to `signal_score`. The Engine's `ON CONFLICT(event_id) DO NOTHING` works but never sees a repeated id. No existing implementation, no prior rejection.

Step 1's key as proposed, `(actor_id, video_uuid, instance_domain, event_type)`, was rejected in the question round: it drops a genuine re-like after an un-like, and lets any anonymous visitor zero a video's anonymous contribution for good. Decisions (recorded in `docs/project/adr/0001-derived-interaction-event-ids.md` and `CONTEXT.md`):

- A re-like after an un-like counts again. A profile publishes only on a real like-state change, and its event id includes a like instance, so replays collapse and genuine re-likes do not.
- Anonymous events use a fixed instance, so they contribute at most `+1` per video.
- The popular ordering caps the signal with a fixed named constant, initially `25.0`. The stored score stays uncapped.

## Agent Brief

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
