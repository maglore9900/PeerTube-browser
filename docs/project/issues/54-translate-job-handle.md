# A translate job handle in the subtitles store

Status: enhancement, ready-for-agent
Origin: architecture review `.scratch/architecture-review-20261004-0901.md`, candidate "translate job handle in the subtitles store" (Strong)

## Problem

A translate job's lifecycle runs through four modules, and the store's interface hands its invariants to the callers:

- After the claim, the worker builds `(video_id, instance_domain, TARGET_LANGUAGE, started_at)` by hand (`engine/server/db/jobs/translate-worker.py:473`). It then passes `*claim` to every finish and requeue call, eight call sites in all, so that `_update_claim` (`engine/server/data/subtitles.py:158-162`) can compare-and-set on `started_at`. The finish and requeue functions (`subtitles.py:165-187`) are one-line wrappers.
- `store_ready_subtitles` documents "against a job row it ends the job … so read state first" (`subtitles.py:105`). The route follows that rule. The worker instead does an unconditional upsert followed by a conditional `mark_translate_finished` (`translate-worker.py:445-446`).
- `recover_translate_jobs` is safe only under the worker's flock (`subtitles.py:151`), and only `command_run`'s ordering guarantees that.
- Every opener must call `ensure_subtitles_schema` after `connect_subtitles_db` and create the directory first (`engine/server/api/server.py:371-372`, `translate-worker.py:136-140, 567-571`).
- The route repeats the `subtitles_db_lock` / `None` check three times (`internal_translate.py:215-219, 237-240, 320-322`).
- `JobTakenOver` (`translate-worker.py:92-93, 485-486`) refers to a route taking over a running row. The current route never fetches over a running row (`internal_translate.py:297-300`). The review found no current writer that triggers it, but did not check an older blue/green Engine.
- Tests fake `server` as a `SimpleNamespace` with three lock and connection attributes (`tests/active/test_internal_translate.py:510-512`).

## Proposed solution

Make the claim return a job handle that carries its own key and `started_at` and exposes the end states: ready with cues, already English, failed with text, requeue, and running cues. The compare-and-set happens inside the handle. Opening the store also migrates it. "Instance track found while running" becomes one store operation. Settle whether `JobTakenOver` still has a writer. The interface is not decided yet.

## Related

- `CONTEXT.md`: Translate job, Translate state.
- Issue 57 (resolve translatable video) is small and fits inside this.
- Issue 56 (worker split): its job-pipeline part depends on this.

## Comments

**Triage (2026-10-04).** The code claims above were checked against the tree, and all of them hold except one. `JobTakenOver` does have a current writer. The state route reads the key, and when there is no row it fetches the instance track, which can take up to its 15 s budget. It then stores `ready` with an unconditional upsert. If an enqueue and a claim land in that window, the upsert ends the running job. Older blue/green Engines were not checked. No job handle exists yet, and there are no prior rejections. The maintainer decided:

- **Issue 57 is folded in:** the shared "resolve a translatable video" function is part of this brief. Issue 57 should be closed as covered by 54; it was not edited in this run.
- **The instance track wins a takeover race:** behaviour is unchanged. `JobTakenOver` stays, documented with its real writer.
- The term "claim" (and "taken over") is now in `CONTEXT.md`.

## Agent Brief

**Category:** enhancement
**Summary:** Make a translate job's claim a handle that owns its key, its `started_at` compare-and-set and its end states. Make opening the subtitles store also migrate it. Resolve a translatable video in one function shared by the route and the worker. Behaviour stays the same throughout.

**Current behavior:**
The subtitles store hands its invariants to the callers:
- **The claim.** `claim_translate_job` returns a bare row. The translate worker rebuilds `(video_id, instance_domain, target_language, started_at)` from it by hand and passes it unpacked to `store_running_cues`, `finish_translate_ready`, `finish_translate_already_english`, `finish_translate_failed` and `requeue_translate_job`. Each of these is a one-line wrapper over one private conditional update, which matches only while the row is `running` with that `started_at`. Each returns `False` when the row was taken over.
- **The instance track found at claim.** The worker calls `store_ready_subtitles`, an unconditional upsert, and then `mark_translate_finished`, a conditional stamp. `store_ready_subtitles`' own contract says to read state first, and the worker's call does not.
- **Recovery.** `recover_translate_jobs` is safe only while the worker holds its flock. Only the order of steps in the worker's `run` command guarantees that.
- **Opening the store.** Every opener (the Engine at start, the worker's enqueue CLI and its `run` service) must create the parent directory, call `connect_subtitles_db` and then `ensure_subtitles_schema`.
- **The route's store access.** The translate routes repeat the same "hold `subtitles_db_lock`, take `subtitles_db`, treat `None` as closed" block three times: the state read, the instance-track store and the enqueue.
- **Resolving a video, done twice.** The route resolves a video from `{id, host}` with `resolve_video_row`, then the active-denylist check under `db_lock`, writing the 400 or 404 response itself. The worker's `resolve_video` does the same lookup with `fetch_video_row` and `VIDEO_ERROR_THRESHOLD`, the same denylist check, a stored-duration bound and an inline `busy_timeout`. The worker also guards a pitfall: a `None` host matches the id on any host. The two can drift apart.
- **Tests.** Tests fake the Engine server as a `SimpleNamespace` with `db`, `db_lock`, `subtitles_db`, `subtitles_db_lock` and the threshold.

**Desired behavior:**
- **Job handle.** Claiming returns a job handle, or nothing when no job is queued. The handle carries the job's key, its `started_at` and its `attempts`, and exposes the claim's operations:
  - write the running cues so far (with the detected language);
  - end ready with the full cue list;
  - end `already_english` with the detected language;
  - end `failed` with the error text;
  - requeue without spending the claim;
  - end ready from an instance caption track.

  Each operation does the compare-and-set on `started_at` internally and reports whether the claim still held. The last operation is a single store operation that writes the track and stamps `finished_at` only while the claim holds. The current upsert-then-stamp is replaced, and the end state is the same as today's. No caller assembles or unpacks a claim tuple.
- **Takeover.** Unchanged: the Engine's instance-track store still replaces a running row, and a later handle operation then reports the claim lost. The worker's `JobTakenOver` path stays. Its docstring and the worker doc must name the real writer: the state route's instance-track store racing an enqueue and a claim.
- **Opening the store.** One open function creates the parent directory, connects in WAL mode and migrates the schema. The Engine and every worker entry point use it. The heartbeat thread's connection may use it too.
- **Recovery** is reachable only together with the worker's flock. For example, a store opener for the worker service runs recovery and can only be called while the flock is held, or recovery takes proof of the lock. A caller cannot run recovery without the lock by mistake.
- **The route's store access** goes through one helper that holds the lock and treats a closed store the same way the three current sites do: no row and not available for reads, a logged no-op for the track store, and `available: false` with nothing queued for enqueue.
- **Resolve a translatable video (from issue 57).** One function takes a whitelist connection, a video id, a normalised host and an error threshold. It returns the whitelisted row, or a refusal: not in whitelist, or host denied, checked on the row's normalised domain against the active denylist. It refuses a missing host instead of matching the id on any host. The route maps the refusal to its current 404 `Video not found`. The worker maps it to its current refusal texts and keeps its own stored-duration bound and `busy_timeout`. The route's 400 validation of the `{id, host}` body stays in the route.

**Key interfaces:**
- The claim's return type becomes a job handle: a small class or dataclass in the subtitles store module, holding the store connection or taking it per call.
- Handle operations return whether the claim held, or raise one exception the worker maps to its takeover path. Choose one.
- One store-open function replaces the `connect_subtitles_db` plus `ensure_subtitles_schema` pair at every caller.
- One resolve function, shared by the `/internal/translate` routes and the translate worker, returns a row or a refusal and never writes an HTTP response.

**Acceptance criteria:**
- [ ] No caller outside the store module builds, unpacks or passes a `(video_id, instance_domain, target_language, started_at)` tuple. The five per-claim functions and `mark_translate_finished` are no longer part of the store's public interface.
- [ ] Every handle operation is a no-op that reports the claim lost when the row is no longer `running` with the claim's `started_at`. A test proves this for each operation.
- [ ] Ending ready from an instance track while the claim holds leaves exactly today's row: state `ready`, source `instance`, the track and cues, `finished_at` set. When the claim was lost, it changes nothing.
- [ ] A state-route instance-track store over a running row still wins. The worker then logs the takeover and writes nothing further for that job.
- [ ] Opening the store on a fresh path creates the directory and the full schema. Opening a B1-era file adds the job columns. The Engine and the worker's enqueue and run entry points call nothing else to open the store.
- [ ] Recovery cannot be called from the worker without the flock held. A test or the type of the call shows this.
- [ ] The three route sites use one store-access helper, and route responses for a closed store are unchanged.
- [ ] One resolve function serves both the routes and the worker. A missing host is refused, a denied host is refused on the row's normalised domain, and the routes' 400 and 404 responses and the worker's refusal texts are unchanged.
- [ ] The existing translate route, translate worker and subtitles store tests pass, rewritten only where they used the removed functions or the claim tuple.
- [ ] The translate worker doc and the Engine server README's store-contract section describe the handle, the takeover writer and the single store opener.

**Out of scope:**
- Making the state route's instance-track store conditional, i.e. a running job winning the race.
- Removing `JobTakenOver`.
- The source-instance fetch adapter (issue 53) and the rest of the worker split (issue 56): timing parameters and moving the pipeline out of the script.
- Changing the job states, `MAX_CLAIMS`, recovery's requeue-once rule, the queue cap or the heartbeat.
- Any schema change beyond what the store opener already migrates.

