# ADR-0005: Raw interaction events are stripped after 30 days; their ids are kept

Status: accepted
Date: decided in triage of issue 05 (raw event retention)
Related: ADR-0001 (derived interaction event ids)

## Context

`interaction_raw_events` grows without bound and stores a caller-supplied `raw_payload_json` of up to 4 KiB per row. Nothing reads it for ranking: `interaction_signals` is updated at ingest. But its `event_id` primary key is the Engine's idempotency record, and ADR-0001's derived ids only collapse replays while that record exists. Deleting rows would let a replayed old event, including the fixed anonymous `Like` id, count again.

## Decision

1. **Strip, don't delete.** Rows older than the retention window get `raw_payload_json`, `actor_id` and `source_instance` cleared. `event_id`, `event_type`, `video_uuid`, `instance_domain`, `published_at` and `ingested_at` stay, so a duplicate is caught for good.
2. **Window:** 30 days by `ingested_at`, as a named constant, overridable by `INTERACTION_RAW_RETENTION_DAYS`.
3. **Runs in the Engine,** not the optional weekly updater. At most once an hour, triggered from the event-ingest path, in bounded chunks each taking `db_lock` briefly. So every deployment prunes.

## Consequences

- The table still grows, by about 100 bytes per real event. After ADR-0001 that is real like-state changes, not replays.
- Personal data (`actor_id`) and caller-supplied payloads age out after 30 days.
- A true row cap would need a separate dedupe store. That was considered and not taken.
