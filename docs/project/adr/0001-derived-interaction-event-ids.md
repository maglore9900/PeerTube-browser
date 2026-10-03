# ADR-0001: Interaction event ids are derived, and the ranking signal is capped

Status: accepted
Date: decided in triage of issue 01 (deterministic event ids)

## Context

The Client backend published every `Like` and `UndoLike` with a random `event_id`, so the Engine's `ON CONFLICT(event_id) DO NOTHING` idempotency never fired. Repeating a like, with or without a profile, added `+1.0` to `interaction_signals.signal_score` each time, and the popular ordering added that score to `popularity` uncapped.

A plain derivation from `(actor_id, video_uuid, instance_domain, event_type)` was proposed and rejected: it drops a genuine re-like after an un-like, and because every profile-less visitor publishes as actor `anonymous`, one anonymous like plus one anonymous un-like would zero that video's anonymous contribution forever.

## Decision

1. **A profile publishes only on a real state change.** A `like` on a video the profile already likes, or an `undo_like` on one it does not, publishes nothing.
2. **A profile's event id is derived from the actor, the video identity, the event type, and a like instance.** Replays of one like (or of its un-like) carry the same id; a like made after an un-like carries a new one.
3. **An anonymous event id is derived with a fixed instance.** Anonymous likes contribute at most `+1` per video, and anonymous un-likes at most `-1`. This is accepted: anonymous likes have no identity to tell a real repeat from a replay.
4. **The popular ordering caps the signal** with a named constant, `MIN(signal_score, C)`, initially `25.0`. The stored `signal_score` stays uncapped, so the cap can change without a data migration.

## Consequences

- The Engine's ingest path is unchanged; its existing idempotency now does the collapsing.
- Anonymous likes become a near-constant per video. Moving anonymous visitors to profiles is the way to make their likes count individually.
- Events already stored with random ids stay as they are; nothing is backfilled.
- The like instance is a generation in the Client's `users.db` table `like_generations`, which holds one row per profile and video, with a `published` flag. `CONTEXT.md` defines this as a **Published like**. The "real state change" in decision 1 means opening or closing a published like. It does not mean a change to the profile's likes list.
- A like publishes, and advances the generation, only when it opens a published like. An un-like, or a dislike replacing a like, publishes only when it closes one, and uses the generation its `Like` used. Rows survive un-like, reset and the `max_likes` trim. They are deleted with the profile.
- Imported likes never open a published like, so un-liking one publishes nothing. A re-like after a reset publishes nothing either. Neither reset nor import can therefore be looped to push a video's signal up or down.
- A like dropped by the `max_likes` trim stays published, so a later un-like still withdraws it.
- Likes made before `like_generations` existed have no published row. Un-liking one publishes no `UndoLike`, so its `+1` stays at the Engine.

## Amendment: decision 4 superseded (issue 37)

Decision 4 no longer holds. The popular ordering (the recommendation mix's popular layer and the Hot feed), the Popular feed and every returned row stop reading `interaction_signals`, so there is no signal left to cap and `POPULAR_SIGNAL_CAP` is gone. The signal came only from likes on this site, which already shape a profile's recommendations through similarity, so the global orders rank on the source instance's counts alone. Decisions 1-3 stand: events are still published with derived ids and aggregated into `interaction_signals`, and `docs/project/issues/archive/38-hot-trending-by-growth.md` decides whether anything reads it again.
