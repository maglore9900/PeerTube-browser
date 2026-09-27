# Strip old raw interaction events and cap likes on /videos/similar

Status: delivered. Adopted as the source plan of the dev_flow build `docs/project/plans/archive/16-11-raw-event-retention.md`, which holds the confirmed requirements and the record of what landed; where the two differ, plan 16 wins. The follow-ups that build left unbuilt are listed in the closing comment of `docs/project/issues/archive/05-raw-event-retention.md`. The Agent Brief's "Current behavior" below describes the tree before that build.

## Requirements

### What was asked for

Build issue `docs/project/issues/05-raw-event-retention.md` as triaged: Strip old raw interaction events while keeping their ids, and apply the likes cap to `/videos/similar`. The Agent Brief below, copied from the issue, is the confirmed requirement set; the build starts from this file.

### Purpose

Close the security-audit finding the issue records. This build is one of issues 01-06, delivered concurrently to use as little operator time and cause as few merge conflicts as possible.

### Decisions this rests on

`docs/project/adr/0005-raw-event-retention-keeps-ids.md`; `CONTEXT.md` **Interaction event**.

### Agent Brief

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

### Consistency constraints

- Match the surrounding code's style: stdlib HTTP handlers, `respond_json`, module-level named constants, and env vars read once at startup.
- Backwards compatibility is not required beyond what the brief states.
- Run `validate_tests.py` from the root of the tree this build runs in (a worktree for waves 1-2, main for wave 3). That tree's `.un` config carries it as `project_dir`.

### Batch context

Part of the security hardening batch (`.scratch/security-hardening-batch/notes.md`): issues 01-06 delivered in three waves of git worktrees. Wave 1 is plans 10, 11 and 12. Wave 2 is 13 and 14, branched from main after wave 1 merges. Wave 3 is 15, on the merged main. A wave 1 or 2 build runs in its own worktree created by `.scratch/security-hardening-batch/worktree-setup.sh`, merges to main when it closes, and is harvested on main, not in the worktree.

Wave 1. It shares `engine/server/api/handlers/similar.py` with plan 12, in different functions (lines ~193-233 here, ~283-303 there). It shares `internal_events.py` and `server_config.py` with plan 15, which runs after this plan merges.

### Conflicts

The brief does not conflict with the tree. Every function and line it names was checked against the source on 2026-09-26 (`.scratch/security-hardening-batch/notes.md`, File overlap). Line numbers will drift once earlier waves merge, so re-locate by function name at Step 3.

## High-level plan

### Approach

**Schema.** `ensure_interaction_event_schema()` gains `CREATE INDEX IF NOT EXISTS` on `interaction_raw_events(ingested_at)`.

**Strip.** A new function beside `ingest_interaction_event()` in `engine/server/data/interaction_events.py` takes a connection, a cutoff in ms and a chunk size. It works one chunk at a time over rows older than the cutoff that are not yet stripped, setting `raw_payload_json`, `actor_id` and `source_instance` to NULL and committing each chunk. It returns the total number of rows stripped.

**Trigger.** After a successful ingest, the Engine's event-ingest handler (`api/handlers/internal_events.py`) calls the strip if at least an hour has passed since the last run. A timestamp on the server object records the last run. Each chunk takes and releases `db_lock` on its own, so no single hold scans the table.

**Config.** A named 30-day constant goes in `api/server_config.py`. The env var `INTERACTION_RAW_RETENTION_DAYS` overrides it; it must be a positive integer, checked at startup, and a bad value stops the Engine with an error naming the variable.

**Likes cap.** `_recommendations_likes_payload_error()` in `handlers/similar.py` currently returns early for every path except `/recommendations`. It is widened to both routes in `SIMILAR_POST_ROUTES`, so `/videos/similar` returns the same 400 body and per-item errors.

Idempotency needs no change: stripped rows keep `event_id`, so `ON CONFLICT(event_id) DO NOTHING` still reports a duplicate.

### Alternatives considered

- **Pruning from the updater worker or a timer.** Rejected by ADR-0005: the timer is optional and weekly, and the ingest path is the only place certain to run when events arrive.
- **Deleting old rows.** Rejected by ADR-0005: `event_id` is the idempotency record, and deleting it lets replays count again.
- **A background thread on an interval.** Rejected: it adds a thread lifecycle to the server for a job the ingest path can rate-limit itself.

### Risks and limitations

- The first run on a large existing table strips every row past the window, in many chunks. Each chunk is short, but that first ingest request takes longer: the chunk size bounds each lock hold, not the whole request.
- Reading and writing the timestamp on the server object must be safe under the threaded server. Either check and set it under the lock, or accept that two threads may very rarely both run a strip, which is harmless because the strip is idempotent.
- Tests age rows by inserting them with a past `ingested_at` rather than waiting.
- **Shared `whitelist.db`.** The worktree symlinks the main tree's `whitelist.db`, so this build's test Engines write interaction rows into the same file as other lanes, and as the live Engine if it runs. Every test run already does this; worktrees only make it concurrent.
- **Tracked test record.** `tests/last_test_validation.json` and `tests/last_test_output.txt` always conflict on merge. Take main's copy and re-run `validate_tests.py --compare` on the merged tree.
- **Engine rate limit.** Run Engine-backed test files in their own `validate_tests.py` invocations (memory `engine-rate-limit-single-lane-test-runs`).

### Tradeoffs accepted

Once an hour, the retention work runs inside an ingest request rather than in a separate job.
