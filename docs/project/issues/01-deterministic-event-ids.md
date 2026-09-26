# Deterministic event ids and bounded ranking influence

Status: bug, needs-triage
Origin: task 80, SI3-M1 — security audit run 1, finding F5

## Problem

`_handle_client_publish_event` fills in a fresh `event_id` when one is absent, defeating the ingest idempotency key, and each `Like` adds `+1.0` to `interaction_signals.signal_score`, which orders the popular pool.

## Proposed solution

Collapse replays and cap the ranking contribution.

1. Derive `event_id` deterministically from `(actor_id, video_uuid, instance_domain, event_type)` instead of generating a random id when absent (today: `client/backend/server.py` builds `f"client-{uuid4()}"`).
2. Confirm the existing idempotency path in `engine/server/data/interaction_events.py` now collapses repeated posts.
3. Cap the `signal_score` contribution used in the popular ordering at `engine/server/data/random_videos.py:247` so accumulated signal cannot dominate `popularity`.

## Related

- Must land before the un-like path of the like/dislike plan (`docs/project/plans/03-like-dislike.md`, I2), which emits `UndoLike` and has to match the deterministic key.

## Comments
