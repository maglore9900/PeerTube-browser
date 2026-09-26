# Retention for raw interaction events and bounded like expansion

Status: bug, ready-for-agent
Origin: task 85, SI4-M1 — hardening notes from security audit runs 1-2

## Problem

`interaction_raw_events` has no retention policy, and `_resolve_client_likes` builds one `OR` term per submitted like with no cap on the similar endpoint.

## Proposed solution

Prune old rows and cap the expansion.

1. Add a retention window and a pruning step for `interaction_raw_events` in the existing maintenance/updater path.
2. Cap the number of likes expanded in `_resolve_client_likes` (`engine/server/api/handlers/similar.py`) at the same limit the recommendations path uses.

## Comments

**Triage.** Both halves confirmed against the code.

- `interaction_raw_events` is never pruned. It is not read for ranking (`interaction_signals` is updated at ingest), but its `event_id` primary key is the ingest idempotency record that issue 01 / ADR-0001 depend on. So deleting rows would let replays of old events count again.
- `/recommendations` rejects more than `DEFAULT_CLIENT_LIKES_MAX` (5) likes. `/videos/similar` skips that check, so `_resolve_client_likes` builds one `OR` term per like, bounded only by the 64 KiB body limit, under `db_lock`. Every current caller (frontend `getRandomLikes`, the Client's profile sample) sends at most 5.
- The only scheduled maintenance is the optional weekly updater timer.

No existing implementation, no prior rejection. Decisions (recorded in `docs/project/adr/0005-raw-event-retention-keeps-ids.md` and `CONTEXT.md`):

- Retention strips `raw_payload_json`, `actor_id` and `source_instance` from rows older than the window, and keeps the ids.
- The window is 30 days by `ingested_at`, overridable by `INTERACTION_RAW_RETENTION_DAYS`. It runs in the Engine, at most hourly, from the ingest path, in bounded chunks.
- `/videos/similar` gets the same 400-above-5 rule as `/recommendations`.

## Agent Brief

**Category:** bug
**Summary:** Strip old raw interaction events while keeping their ids, and apply the likes cap to `/videos/similar`

**Current behavior:**
- Every ingested interaction event stays in `interaction_raw_events` for good, with its actor id and a caller-supplied `raw_payload_json` of up to 4 KiB. Nothing prunes it, and the only scheduled job (the weekly updater timer) is optional and never touches it.
- `POST /recommendations` rejects a likes list longer than `DEFAULT_CLIENT_LIKES_MAX` (5) with `400 {"error": "Too many likes in request body", "max_allowed", "received"}`. `POST /videos/similar` skips that check (the helper returns early for any other path). Its likes are resolved by one query with one `OR` term per distinct like, under the global DB lock, bounded only by the 64 KiB body limit.

**Desired behavior:**
- **Retention.** Events older than the retention window, by `ingested_at`, keep `event_id`, `event_type`, `video_uuid`, `instance_domain`, `published_at` and `ingested_at`. Their `raw_payload_json`, `actor_id` and `source_instance` become NULL.
  - The window defaults to 30 days, as a named constant, overridable by the env var `INTERACTION_RAW_RETENTION_DAYS` (a positive integer; anything else fails Engine startup with an error naming the variable).
  - The Engine runs the strip at most once per hour, triggered from the event-ingest request path. It runs in chunks of a bounded number of rows, each chunk its own short `db_lock` hold and commit, so no single hold scans the whole table.
  - The strip only touches rows not yet stripped.
  - The schema gains an index that makes the `ingested_at` cutoff cheap, created idempotently alongside the existing interaction-event schema.
- **Idempotency is unchanged.** Ingesting an event whose id belongs to a stripped row is still reported as a duplicate and changes no counts.
- **Likes cap.** `POST /videos/similar` applies the same validation and limit as `/recommendations`: the same 400 body above `DEFAULT_CLIENT_LIKES_MAX`, and the same per-item format errors. At or under the limit, behaviour is unchanged.

**Key interfaces:**
- `ensure_interaction_event_schema()`: add the `ingested_at` index.
- A new pruning function beside `ingest_interaction_event()`, taking a connection, a cutoff in ms and a chunk size, and returning the number of rows stripped. The Engine's event-ingest handler calls it, rate-limited to once per hour via a timestamp held on the server object.
- Engine server config: the retention constant and its env override.
- `_recommendations_likes_payload_error()` in the similar handler: applies to both routes in `SIMILAR_POST_ROUTES`, not only `/recommendations`.

**Acceptance criteria:**
- [ ] A row ingested 31 days ago has NULL `raw_payload_json`, `actor_id` and `source_instance` after a prune run, and keeps its `event_id`, `event_type`, `video_uuid`, `instance_domain`, `published_at` and `ingested_at`. A row ingested 29 days ago is untouched.
- [ ] Re-ingesting the stripped row's `event_id` returns `duplicate: true` and leaves `interaction_signals` unchanged.
- [ ] Two ingest requests within an hour trigger at most one prune run; the first after the hour triggers another.
- [ ] With more stale rows than one chunk, one run strips all of them across several commits.
- [ ] `INTERACTION_RAW_RETENTION_DAYS=7` strips an 8-day-old row. `INTERACTION_RAW_RETENTION_DAYS=abc` stops Engine startup with an error naming the variable.
- [ ] `POST /videos/similar` with 6 likes returns the same 400 body `/recommendations` returns, and with 5 likes proceeds as today.
- [ ] Existing interaction-event, security-bundle and likes-limit tests pass.

**Out of scope:**
- Deleting rows or capping the table's row count (ADR-0005 keeps ids for good).
- `interaction_signals` and its aggregation.
- The Client proxy's `MAX_CLIENT_LIKES` (issue 03).
- The updater worker and its timer.
- Backfill beyond what the first prune run strips.
