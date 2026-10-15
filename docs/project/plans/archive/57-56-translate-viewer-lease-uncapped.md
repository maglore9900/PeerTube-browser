# 56-translate-viewer-lease-uncapped

_Rendered by the `dev-flow` workflow from its run state. Every edit here is overwritten on the next step; the evidence each gate turned on is in `docs/project/plans/57-56-translate-viewer-lease-uncapped.record.md`._

## Requirements

### Purpose
Any whitelisted video can be translated, whatever its length. The single GPU translate worker spends time only on videos that a viewer is still waiting for. The duration cap and the media-size cap go, because the media is streamed and never stored. What the caps were standing in for is handled directly:
- bounded memory;
- a viewer lease, so a viewer who gives up (closes the video or the tab, or turns Translate off) does not leave the worker busy;
- an explicit cancel.

### Background (operator's debug session, 2026-10-09, re-checked in the tree)
- Translation was "not working" because of the caps. Since the last success on 10-06, 7 jobs failed with `duration Ns over 3600s`, including both of the operator's attempts that day (7754 s and 5284 s). The other failures came from the videos themselves: music with no speech, an HTTP 403, an incomplete cert chain, and one transient CUDA OOM. A 295 s control video ended `ready`.
- The 7 cap-failed rows were deleted on 2026-10-09 by `.scratch/translate-debug/clear_cap_failures.py`. The build carries no cleanup.
- In `engine/server/db/jobs/translate-worker.py`:
  - `AudioPipe` streams the download into ffmpeg's stdin through `stream_media` and never writes it to disk.
  - `_read` (line ~218) appends every decoded sample to `self.pcm` and never drops any (rat-tail at line 182). The only bound on that buffer is `max_samples` (line 227, `audio longer than Ns`), and it grows by about 115 MB per hour of audio.
  - `_read` drains ffmpeg as fast as the network allows. That is about 100× real time, against Whisper's about 20×.
  - `translate_audio` (line 338) wakes at least every `POLL_SECONDS` (2 s) through `wait_samples` and checks `stop` there (line 346).
  - `generate` (line 384) contains `resolve_video(..., args.max_duration)`, `video_duration`, `video duration unknown`, `duration Ns over Ms`, and `AudioPipe(url, host, args.max_bytes, args.max_duration * SAMPLE_RATE)`.
  - `resolve_video` (line 92) checks the stored duration.
  - `parse_args`: `enqueue --max-duration`, `run --max-duration`, `run --max-bytes`.
  - `run_job` maps the exceptions `JobStopped` (requeue), `WhitelistBusy` (requeue), `JobTakenOver` (no write) and `JobFailed` (`end_failed`).
- In `engine/server/data/subtitles.py`:
  - `ensure_subtitles_schema` adds columns in place from `JOB_COLUMNS`.
  - `enqueue_translate_job` never overwrites a row, so a `failed` key is never retried.
  - `claim_translate_job` takes the oldest queued row in one `BEGIN IMMEDIATE` (`_immediate`).
  - `TranslateJob` methods are conditional updates on `state='running' AND started_at=?` (`_update_claim`).
  - `_recover_translate_jobs` requeues running rows at worker start, and fails those at `MAX_CLAIMS`.
- In `engine/server/data/source_fetch.py`: `stream_media(url, host, max_bytes, consume, stop)` checks Content-Length and the streamed size against `max_bytes` (`media over N bytes`). `fetch_bounded` has its own 2 MB `FETCH_MAX_BYTES`.
- In `engine/server/api/server_config.py`: `SUBTITLE_MAX_DURATION = 3600` (line 422), `SUBTITLE_MAX_BYTES = 1024 ** 3` (line 424), `SUBTITLE_QUEUE_CAP = 50`, `SUBTITLE_MAX_CHUNK_SECONDS = 30`, `HEARTBEAT_FRESH_MS`.
- In `engine/server/api/handlers/internal_translate.py`:
  - `handle_internal_translate` answers a `queued` or `running` row from the store with no fetch. It reads the row through `_read_key` under `subtitles_db_lock`.
  - `handle_internal_translate_enqueue` queues under one lock hold with the heartbeat gate.
  - `_resolve_translate_key` validates `{id, host}` and answers 400 or 404 `{"error": "Video not found"}`.
  - The routes are registered in `engine/server/api/router.py` (lines 144-145, docstring lines 18-19) behind the bridge gate.
- In `client/backend/server.py`:
  - There is no `do_DELETE`, so http.server answers 501 for that method.
  - Removals are POSTs to sub-paths (`/api/profile/blocks/remove`, `/api/profile/follows/remove`).
  - `_handle_translate_get` and `_handle_translate_post` call `_require_profile()` first.
  - Each path has its own `_rate_limit_check(url.path)` bucket.
  - The gateway client is `client/backend/lib/engine_api_client.py` (`fetch_translate`, `request_translate`).
- In `client/frontend/src/pages/video-page/translate.ts`:
  - `turnOff` sends nothing to the server.
  - `applyState` ends polling on `none`.
  - Only `turnOn` calls `requestTranslate`.
  - The state poll runs every 2–16 s (`STATE_POLL_FIRST_MS`, `STATE_POLL_MAX_MS`), and only while `available`.
  - The data layer is `client/frontend/src/data/translate.ts`.
- Baseline: the active suite passed before the build (code 0).

### Acceptance criteria
- **AC1 No duration cap.** The following are all removed:
  - `SUBTITLE_MAX_DURATION`;
  - the `--max-duration` flag on both `enqueue` and `run`;
  - the stored-row duration check in `resolve_video`, which also loses its `max_duration` parameter;
  - the JSON duration check and `video_duration`;
  - the decoded-samples check (`max_samples`, `audio longer than Ns`);
  - the failure `video duration unknown`.

  A video of any length, including one whose JSON has no duration, is translated.
- **AC2 No media-size cap.** `SUBTITLE_MAX_BYTES`, `run --max-bytes`, `stream_media`'s `max_bytes` parameter, both of its size checks, and the `media over N bytes` text are removed. `fetch_bounded`'s 2 MB cap on instance API responses stays. `pick_media_url` is unchanged, so the worker still picks the smallest acceptable media file.
- **AC3 Constant memory.**
  - The decoded-audio buffer holds at most `LOOKAHEAD_SECONDS` (a worker constant, proposed 600 s, about 19 MB) past the current translation position, plus the current window (`--max-chunk-seconds`), whatever the video's length.
  - Samples already translated are dropped.
  - Once that limit is reached, the reader stops pulling from ffmpeg, so ffmpeg and the feeder block and the download runs at the translation's pace.
  - The limit always includes the window, so a large `--max-chunk-seconds` can never deadlock the reader against `wait_samples`.
- **AC4 Viewer lease.**
  - A job queued by the Engine's enqueue route carries a lease. Every state read of a `queued` or `running` row through the Engine's state route renews it.
  - A running job whose lease has expired is abandoned within one chunk-loop wake (2 s), or at the first wake after a longer step such as model load or a Whisper call.
  - A queued job whose lease has expired is never started.
- **AC5 Cancel.**
  - Turning Translate off on the page sends a cancel for that video.
  - A cancel shortens the lease to a grace period. It does not end the job outright, so a job that another viewer is still polling survives.
  - With no other viewer, the job stops within the grace period plus one chunk.
- **AC6 Abandoned jobs can be requested again.**
  - An abandoned job leaves no row and its partial cues are discarded, so the state reads `none` and a later Translate request queues it afresh.
  - A page still on Translate that reads `none` with `available` on the poll path requests generation again, as `turnOn` does. This covers a backgrounded tab whose throttled timers let the lease lapse.
- **AC7 Command-line jobs run to the end.** A job queued by `translate-worker.py enqueue` has no lease and is never abandoned, renewed or shortened.

### Design (settled with the operator)
- **Lease column.**
  - `subtitles` gains `wanted_at INTEGER` (ms, nullable). It is added in place by `ensure_subtitles_schema` through `JOB_COLUMNS`, as plan 49's columns were.
  - NULL means unleased, which covers CLI jobs and every row that existed before migration.
  - The Engine's enqueue route sets `wanted_at` to the enqueue time on insert. `enqueue_translate_job` gains a way to take that value, and the CLI passes none.
  - New `server_config` constants: `TRANSLATE_LEASE_MS` (proposed 180 000) and `TRANSLATE_CANCEL_GRACE_MS` (proposed 20 000, above the page's 16 s maximum poll interval).
  - A lease has expired when `wanted_at <= now - TRANSLATE_LEASE_MS`. The Engine and the worker both use `now_ms()` on the same host.
- **Renewal.**
  - When the state route reads a `queued` or `running` row, it sets `wanted_at = now` in the same `subtitles_db_lock` hold. This is one conditional UPDATE matching that key, `state IN ('queued','running')` and `wanted_at IS NOT NULL`.
  - A failed renewal (`sqlite3.Error`) is logged and leaves the answer unchanged, mirroring the cache-write failure path.
- **Claim.** `claim_translate_job` first deletes `queued` rows with `wanted_at IS NOT NULL` whose lease has expired, then claims the oldest remaining row. Both happen in its existing IMMEDIATE transaction.
- **Abandon.**
  - At each wake in `translate_audio` (or throttled to every few seconds), the worker reads the job's `wanted_at` through a new `TranslateJob` method, a single-row primary-key read.
  - If the lease has expired, it raises a new `JobAbandoned`. `run_job` then ends the job through a second new `TranslateJob` method: one conditional DELETE matching the key, `state='running'`, the claim's `started_at`, `wanted_at IS NOT NULL` and the lease still expired.
  - A renewal that lands between the read and the delete therefore wins, and the job continues. A row the instance-track store replaced is left alone.
  - It logs one info line.
- **Stop and recovery.**
  - A SIGTERM mid-job requeues as now (`JobStopped`), and `wanted_at` is kept.
  - At worker start, `_recover_translate_jobs` requeues running rows as now. A leased row whose lease expired while the worker was down is dropped at the next claim.
- **Cancel route (Engine).**
  - New bridge-gated `POST /internal/translate/cancel {id, host}`, registered in `router.py` beside the other two routes and documented in its docstring.
  - It validates and resolves through `_resolve_translate_key`, so an unknown or denied video answers 404 `Video not found` and a bad body answers 400.
  - Under one `subtitles_db_lock` hold, it runs one conditional UPDATE: `wanted_at = MIN(wanted_at, now - TRANSLATE_LEASE_MS + TRANSLATE_CANCEL_GRACE_MS)`. The update matches only that key with `state IN ('queued','running')` and `wanted_at IS NOT NULL`. It never lengthens a lease, and it never touches CLI, ready, failed or already_english rows.
  - It then answers `{state, available}`, the same shape as enqueue. `state` is the key's stored state after the update, or `none` for no row, and `available` is the heartbeat gate.
  - A store error answers 503 `Translate store unavailable`, as enqueue does. A closed store answers `{"state":"none","available":false}`.
  - A viewer polling within the grace period renews the lease and keeps the job.
- **Cancel route (Client).**
  - Operator decision: `POST /api/translate/cancel {id, host}`, not `DELETE`. This follows the Client's `/remove` convention and needs no new HTTP method.
  - It is profile-checked first (`_require_profile`), and the body is read after the check.
  - It validates exactly as `_handle_translate_post` does and is rate-limited in its own path bucket.
  - It calls a new `engine_api_client` function that posts to `/internal/translate/cancel` with the bridge token, then answers the normalised `{state, available}`. Engine failures go through `_respond_engine_failure`.
  - The data layer `client/frontend/src/data/translate.ts` gains a cancel call.
- **Page.**
  - `turnOff` always fires the cancel for the video and does not wait for the answer. A cancel for a key with no job does nothing.
  - `applyState`, on a poll-path `none` with `available` while Translate is on, calls `requestTranslate` and `applyRequest` under the current ticket, as `turnOn` does, instead of ending the poll.
  - A `none` without `available`, and the other ended states, end the poll as now.
- **Constant memory.**
  - `AudioPipe` keeps `base`, the absolute sample index of `pcm[0]`. `wait_samples` and `slice` keep taking absolute indices.
  - A new `release(upto)` drops the samples before `upto`. `translate_audio` calls it after each window with the new `pos`.
  - `_read` waits on the existing condition while the samples buffered past the release point exceed `LOOKAHEAD_SECONDS` plus the window. The wait also wakes on `stop` and on an error, so `close` and `_fail` never leave `_read` parked.
  - `AudioPipe` loses `max_bytes` and `max_samples`, and its rat-tail comment is replaced.
  - `_feed` calls `stream_media` without a size cap.
- **Caps removed.** Everything named in AC1 and AC2 goes, together with the `server_config` imports in the worker.

### Consistency constraints
- Every new store write is one `BEGIN IMMEDIATE` transaction or one conditional statement. Every write to a running job goes through a `TranslateJob` method that is conditional on the claim (issue 54's claim rule).
- The Engine cancel route follows the bridge-gated `/internal/translate*` shape, with the same validation and `_resolve_translate_key`.
- The Client cancel route checks the profile first, as `_handle_translate_get` and `_handle_translate_post` do.
- All three layers (Engine, Client gateway, page data layer) stay held to `tests/active/fixtures/translate_contract.json`, which gains `cancel` route cases.
- The schema change is an in-place `ALTER TABLE` in `ensure_subtitles_schema`.
- New code matches the style of its file: one-line docstrings, annotated parameters, no softwrap.

### Scope
- **In:**
  - the worker: `AudioPipe`, `translate_audio`, `generate`, `run_job`, `resolve_video`, `command_enqueue`, `parse_args`, a new `JobAbandoned`;
  - `engine/server/data/subtitles.py`: the lease column, enqueue with a lease, claim-time drop, the lease read and abandon methods on `TranslateJob`, renewal, cancel;
  - `engine/server/data/source_fetch.py`: `stream_media` loses its size cap;
  - `engine/server/api/server_config.py`;
  - the Engine translate routes, plus the cancel route and its router entry;
  - the Client gateway: the cancel route and the `engine_api_client` function;
  - the page data layer and `translate.ts`: cancel on Translate off, re-request on `none` while on;
  - the translate contract fixture;
  - the tests for all of these;
  - docs: `engine/server/db/jobs/docs/TRANSLATE_WORKER.md`, `engine/server/README.md`, `client/README.md`, `CONTEXT.md`, `DEPLOYMENT.md`.
- **Out:**
  - resuming an abandoned job from its partial cues;
  - per-viewer accounting of who holds a lease;
  - a progress or ETA display;
  - showing a failed job's reason on the page;
  - a cancel sent when the tab closes (the lease covers that case; a `keepalive` fetch on `pagehide` is a possible later addition);
  - any cleanup of the cap-failed rows (already done by the operator).

### Documentation to update
- **`TRANSLATE_WORKER.md`:**
  - Bounds; Media File Choice; Job Pipeline;
  - Error Texts: remove `duration Ns over Ms`, `audio longer than Ns`, `video duration unknown` and `media over N bytes`;
  - the in-memory PCM statement, which becomes a bounded lookahead with backpressure;
  - the CLI flags;
  - a new section on the viewer lease, cancel and abandonment, including the CLI exception.
- **`engine/server/README.md`:** the `wanted_at` column, the new store functions, renewal on the state route, and the cancel route. The tunables list drops the two caps and adds the lease and grace constants.
- **`client/README.md`:** the `POST /api/translate/cancel` gateway route.
- **`CONTEXT.md`:**
  - Translate job: the lease, abandonment, the CLI exception;
  - Translate state: `none` after abandonment;
  - a new term, **Viewer lease**.
- **`DEPLOYMENT.md`:**
  - line 236: drop the sentence about the page route skipping the duration check, and mention the lease;
  - lines 279-280: drop the `--max-duration` and `--max-bytes` rows from the `run` flags table;
  - line 290: drop `--max-duration` from the `enqueue` paragraph;
  - add `/internal/translate/cancel` to the boundary contract list.

### Risks, tradeoffs and named simplifications
- **R1 Background-tab throttling.** Chrome limits chained timers in a tab hidden for more than 5 minutes to about once a minute. That is why the lease is 180 s. If it lapses anyway, the AC6 re-request restarts the job from zero.
- **R2 Remote send timeouts under backpressure.** While the lookahead is full, the socket is read only as Whisper frees space. A hung Whisper call can let a server's send timeout (nginx's default is 60 s) reset the connection, and the job then fails `media download failed`. The existing 600 s stall detector already marks a hung worker unavailable.
- **R3 Unleased CLI jobs have no bound.** A CLI-queued endless stream runs until stopped. This is accepted, because the operator issues CLI jobs.
- **R4 A write on every poll.** Each poll on a queued or running job is one short UPDATE every 2–16 s per waiting viewer, in WAL mode, with a 30 s busy timeout. A failed renewal is logged and not surfaced.
- **R5 Blue/green.** An older Engine without renewal serves polls only during the 30 s switch drain, which is well under the 180 s lease. An older worker ignores `wanted_at` and runs jobs to the end, which is today's behaviour.
- **R6 A long job blocks the queue.** One job runs at a time, so a 3-hour video holds the GPU for about 10 minutes. Queued viewers' polls keep renewing their leases while they wait.
- **Turn-off race (named gap).** A cancel sent while the enqueue is still in flight can reach the Engine before the row exists. That job then lives one full lease (180 s) with nobody polling, and is dropped at claim or at the next wake.
- **Running-cue rewrite (named simplification).** `write_running_cues` still rewrites the whole cue list after each chunk, which is O(cues) per write. For a multi-hour video that is a few hundred KB per write. Ceiling: very long videos make each write larger. Upgrade path: append-only cue storage.
- **Tradeoffs accepted:**
  - An abandoned job loses its work.
  - A cancel takes effect after about 20 s.
  - A lapsed hidden tab restarts the job.
  - A very long video is not refused up front. It is simply slow, and only while someone waits.

### Conflicts already resolved by the operator
- **AC6 against "a key is never re-queued".** That rule applies to `failed` rows. An abandoned job is deleted, not failed, so it reads `none` and can be requested again. Operator decision, 2026-10-09.
- **AC1 against the 7 rows that failed on the cap.** The operator deleted them on 2026-10-09, before the build, and the build carries no cleanup.
- **The plan's `DELETE /api/translate?id&host`.** The Client has no `do_DELETE`, and its removals are POSTs to sub-paths. The operator chose `POST /api/translate/cancel {id, host}` on 2026-10-09.

## High-level plan

### Approach

The SQLite row carries a lease, the worker checks it, and the page renews it by polling. `subtitles.db` is already the only channel between the Engine, the worker and the page's poll, so the lease lives there. No new process, thread, table or dependency is added. Memory stays constant through backpressure inside the existing `AudioPipe`, and its three threads are unchanged. I read every file named in the requirements, and the plan below follows what is in the tree.

**AC1 and AC2: the caps go.**
- `resolve_video` loses its `max_duration` parameter and the stored-duration branch. It becomes a thin wrapper around `resolve_translatable_video` that keeps the `missing host` to `not in whitelist` mapping.
- `command_enqueue` and `generate` call it without the bound.
- In `generate`, the `video_duration` call, the `video duration unknown` failure and the JSON duration comparison go, and `video_duration` itself is deleted. `math` stays, because `pick_media_url` and `chunk_cues` still use it.
- `AudioPipe` is built from the URL and host only.
- `parse_args` drops `enqueue --max-duration`, `run --max-duration` and `run --max-bytes`.
- The worker's import line drops `SUBTITLE_MAX_BYTES` and `SUBTITLE_MAX_DURATION` and gains `TRANSLATE_LEASE_MS`.
- `server_config` drops both caps and adds `TRANSLATE_LEASE_MS = 180_000` and `TRANSLATE_CANCEL_GRACE_MS = 20_000`.
- `stream_media` loses `max_bytes`, the Content-Length check and the streamed-size check. Its docstring is updated. `fetch_bounded` and `FETCH_MAX_BYTES` are not touched, and neither is `pick_media_url`.

**AC3: constant memory.**
- `AudioPipe` gains `base`, the absolute sample index of `pcm[0]`. `wait_samples` returns `base + len(pcm)//2` (absolute samples), and `slice` subtracts `base`, so `translate_audio` keeps working in absolute positions.
- A new `release(upto)` runs under the condition. It deletes the bytes before `upto` from the front of `pcm`, advances `base` and calls `notify_all`. `translate_audio` calls it right after `pos += cut`.
- `AudioPipe` takes the window length (`max_chunk` samples) and computes `limit = LOOKAHEAD_SECONDS * SAMPLE_RATE + max_chunk`. `LOOKAHEAD_SECONDS = 600` is a new worker constant.
- Before each read, `_read` waits on the condition until the room (`limit` minus the samples buffered) is positive, or until `stop` is set or an error is recorded. It then calls `read1(min(READ_CHUNK_BYTES, room in bytes))`.
  - Clamping the read size means the buffer never exceeds the limit, not even by one read chunk. The AC3 bound is therefore exact, not approximate.
  - The limit always includes the window, so `wait_samples(pos + max_chunk)` can always be satisfied whatever `--max-chunk-seconds` is.
- While `_read` is parked, ffmpeg blocks on its stdout pipe, `_feed` blocks in `stdin.write`, and the socket is read only as Whisper frees space.
- `close` and `_fail` set `stop` and then `notify_all` under the condition, so a parked `_read` always wakes.
  - `close` already kills ffmpeg, and that unblocks `_feed` with a `BrokenPipeError`.
  - When `_read` leaves the loop on `stop`, it still reaps ffmpeg and sets `done`.
- The rat-tail comment is replaced with a one-line statement of the bound.
- At the defaults the buffer holds at most about 19.2 MB plus 0.96 MB, whatever the video's length.

**AC4: viewer lease.**
- `JOB_COLUMNS` gains `("wanted_at", "INTEGER")`, so the existing in-place `ALTER` loop adds it. Rows from before the migration read NULL, which means unleased.
- `enqueue_translate_job` gains a keyword `wanted_at: int | None = None`, written on insert. The Engine's enqueue route passes `now_ms()`; `command_enqueue` passes nothing (AC7).
- **Expiry and the store functions:**
  - The `subtitles.py` functions take a cutoff in ms (`expired_at = now - TRANSLATE_LEASE_MS`), computed by the caller. `subtitles.py` therefore stays free of `server_config`, as it is today.
  - Every lease predicate is `wanted_at IS NOT NULL AND wanted_at <= ?`.
- **Renewal:**
  - A new `renew_translate_lease(conn, key…, now)` is one conditional UPDATE: `SET wanted_at = now` WHERE the key, `state IN ('queued','running')` and `wanted_at IS NOT NULL`.
  - `_read_key` calls it in the same lock hold, only when the row it just read is `queued` or `running`, so ready rows cost no write.
  - It has its own `try`/`except sqlite3.Error` that logs a warning and leaves the read answer unchanged, as `_store_cues` does.
- **Claim:** `claim_translate_job` first runs one DELETE of `state='queued'` rows whose lease has expired, inside its existing `_immediate` block, and then selects the oldest remaining row. `serve` passes the cutoff. A queued job whose lease has expired is therefore never started, including a row recovery requeued after the lease ran out while the worker was down.
- **Abandon:**
  - `TranslateJob` gains `read_lease()`, a primary-key read of `wanted_at`.
  - It also gains `abandon(expired_at)`, one conditional DELETE on the key, `state='running'`, `started_at = self.started_at` and the lease predicate. It returns whether a row went. It is a sibling of `_update_claim` and does not go through it, because it deletes rather than updates. It is still conditional on the claim, so issue 54's rule holds.
  - `translate_audio` checks right after its `stop` check, at every wake. That is at most every 2 s while waiting, or once per chunk while busy, so the first wake after a model load or a long Whisper call catches it. If `read_lease()` returns a lease that has expired, it raises `JobAbandoned`.
  - Throttling the check is unnecessary: one primary-key read per chunk is cheaper than the per-chunk cue rewrite.
  - `run_job` catches `JobAbandoned` and calls `job.abandon(now_ms() - TRANSLATE_LEASE_MS)`.
    - True logs one info line, `abandoned, no viewer`.
    - False means a renewal landed in between or the instance-track store replaced the row. A renewal means the viewer is back, so that branch keeps the claim and requeues the job. I prefer that to failing it: the job's partial work is lost either way, and the requeued row sits at the head of the queue.
- **Instance-track rows:** `store_ready_subtitles` leaves the job columns behind, so a ready instance row may keep a stale `wanted_at`. That is harmless: every lease statement also requires `state IN ('queued','running')`, or `running` together with the claim's `started_at`.

**AC5: cancel.**
- **Engine:**
  - New `handle_internal_translate_cancel` runs `_resolve_translate_key`, which answers 400 or 404 exactly as the other two routes do.
  - In one `_subtitles_store` hold, it calls a new store function `cancel_translate_lease(conn, key…, capped_at)`. That is one conditional UPDATE `SET wanted_at = MIN(wanted_at, ?)`, with `capped_at = now - TRANSLATE_LEASE_MS + TRANSLATE_CANCEL_GRACE_MS`, over the same key, state and NOT NULL predicate as renewal. It then calls `fetch_subtitle_state` and `_generation_available`.
  - It answers `{state or "none", available}`.
  - `sqlite3.Error` answers 503 `Translate store unavailable`. A closed store answers `{"state":"none","available":false}`.
  - It is registered in `router.py` beside the other two routes, with a docstring line `[bridge gate]`, and documented in the module docstring.
- **Client:**
  - `do_POST` gains an `/api/translate/cancel` branch with `_rate_limit_check(url.path)`. The limiter keys by IP and path, so the new path gets its own bucket automatically.
  - The new `_handle_translate_cancel` mirrors `_handle_translate_post` line for line: profile first, then the body, the same validation, `_respond_engine_failure("translate", …)`.
  - `engine_api_client.cancel_translate` mirrors `request_translate`: the same 404 `Video not found` mapping to `{none, false}`, state checked against `TRANSLATE_STATES` (cancel never answers `busy`), and `_translate_available`.
- **Page data layer:** `cancelTranslate(apiBase, id, host)` mirrors `requestTranslate`, POSTing and parsing `{state, available}`, so the contract fixture can replay it.

**AC5: the page.**
- `turnOff` fires `cancelTranslate` without awaiting it, with a `.catch` so a failure is never an unhandled rejection. A cancel for a key with no job is a no-op on the Engine.
- One refinement: the page tracks the promise of its one in-flight state poll or enqueue, and `turnOff` sends the cancel after that promise settles. `turnOff` itself still returns at once and never waits for the cancel's answer.
  - Without this, a poll already in flight could reach the Engine after the cancel and renew the lease to the full 180 s.
  - With it, the named turn-off race also narrows: an enqueue in flight at click time has reached the Engine before the cancel is sent.

**AC6: abandoned jobs can be requested again.**
- An abandoned job leaves no row, so the state route answers `none` and a new enqueue inserts a fresh lease.
- In `applyState`, a `none` with `available` while `on` no longer ends the poll. It drops held running cues (`dropRunning`), sets the waiting label, and calls `requestTranslate` and then `applyRequest` under the current ticket. A rejection is handled as `turnOn` handles it.
- A ready row whose cues fail to load reads `none` on the state route but `ready` on enqueue. Today `applyRequest` would then poll at delay 0, and that would loop tightly. So a re-request made from the poll path schedules `applyRequest`'s follow-up poll with the doubling `stateDelay` instead of 0. Such a broken row costs one pair of requests per 16 s, not a spin.
- A `none` without `available`, `failed` and `already_english` end the poll as now.
- The module doc comment is updated.

**AC7: command-line jobs.**
- The CLI inserts NULL, and every lease statement requires `wanted_at IS NOT NULL`. CLI jobs are never renewed, shortened, dropped at claim or abandoned.
- `requeue` (`JobStopped`, `WhitelistBusy`) and `_recover_translate_jobs` do not touch `wanted_at`, so a lease survives a requeue unchanged.

**Contract fixture and tests.**
- **Fixture:** `translate_contract.json` gains `cancel` route cases. They cover every stored state with and without `available`, the 404 `Video not found` mapping to `{none, false}`, the missing-route 404 rejected, `busy` rejected, an unknown state rejected, and `available` as a string rejected. The description text names the third route. The three replaying tests (`test_engine_api_client.py`, `test_frontend_translate.py`, `test_internal_translate.py`) learn the route.
- **Worker tests:**
  - A no-duration JSON and a long stored duration both translate.
  - `AudioPipe`'s logical length never exceeds `limit` against a fake ffmpeg producing more than the limit, and `_read` parks and resumes on `release`. A `--max-chunk-seconds` above `LOOKAHEAD` does not deadlock, and `close` wakes a parked reader.
  - An expired lease abandons the job, deletes the row and logs one line.
  - A renewal between the read and the delete keeps the job.
  - A CLI job is never abandoned.
- **Store tests:**
  - The claim drops expired leased queued rows but keeps unleased and fresh ones.
  - Renewal and cancel touch only leased queued and running rows, and cancel never lengthens a lease.
  - Migration adds `wanted_at` in place.
- **Route tests:** the Engine route covers 400, 404, 503, closed store, and renewal on read. The Client route covers 401 before the body, 400, 429 and 502.
- **Frontend tests:** cancel on `turnOff`, cancel ordered after an in-flight poll, and re-request on poll-path `none` with `available`.

**Docs.** `TRANSLATE_WORKER.md`, `engine/server/README.md`, `client/README.md`, `CONTEXT.md` (a new **Viewer lease** term) and `DEPLOYMENT.md` are updated as listed in the requirements.

### Alternatives considered

- **A separate lease table or per-viewer rows.** Rejected: per-viewer accounting is out of scope. A single column with renewal piggybacked on the existing poll needs no new request, and its write is gated to `queued` and `running` rows.
- **The Engine signalling the worker directly (signal or socket).** Rejected: the Engine and the worker share only `subtitles.db`. The worker already wakes every 2 s, so a database read is enough.
- **Spooling PCM to a temp file to bound memory.** Rejected: the purpose is that media is never stored, and backpressure needs no disk.
- **A deque of chunks instead of a `bytearray` with `base`.** Rejected: `slice` would have to join across chunks. Trimming the front of one buffer keeps `slice` a single contiguous copy.
- **Pulling ffmpeg output from the main thread on demand, with no reader thread.** Rejected: it would lose the 2 s wake that the stop and lease checks need, and it reintroduces pipe-deadlock risk with stderr.
- **Throttling the lease read to every N seconds.** Rejected: one primary-key read per chunk is cheaper than the per-chunk cue rewrite, and a throttle would only add state.
- **Abandon with a plain DELETE after the read.** Rejected for the settled conditional DELETE, so a renewal that races the check wins.
- **On a lost abandon race, fail the job or leave it running.** I chose to requeue: a viewer came back, and requeuing keeps the claim count honest.
- **Cancelling in-flight requests with `AbortController` on turnOff.** Rejected: aborting the browser fetch does not stop a request the gateway has already forwarded. Ordering the cancel after the in-flight request settles is what actually removes the race.
- **Guarding the AC6 re-request on the previous state being `queued` or `running`.** Rejected: it narrows AC6's wording. Using the backoff delay keeps AC6 literal and still prevents a spin.
- **`DELETE /api/translate`.** The operator chose `POST /api/translate/cancel` (decision of 2026-10-09).

### Gotchas, risks and limitations

- **Expired queued rows count against `SUBTITLE_QUEUE_CAP` until the next claim.** While one long job runs, cancelled or lapsed queued rows can hold cap slots, so a new viewer may see `busy`. With a cap of 50 this is unlikely. Upgrade path: the same expired-row DELETE in `enqueue_translate_job`.
- **Enqueue does not renew an existing row.** A viewer whose enqueue answers `exists` for a lapsed queued row renews it only at the first poll, 2 s later. If the worker drops the row in that window, the poll reads `none` and AC6 re-requests it. This heals itself, at the cost of one extra round trip.
- **Bytearray allocation.** Front deletion of a `bytearray` trims the logical length at once, but CPython may keep up to about twice that allocated until it compacts. The test asserts the logical length (the AC3 bound), not the RSS.
- **Shutdown under backpressure.** `close` must notify the condition after setting `stop`, and `_read` must still reap ffmpeg after an early exit. Otherwise shutdown hangs on a parked reader. The tests pin both.
- **Remote send timeouts (R2).** These are made more likely by backpressure, and a hung Whisper call can turn into `media download failed`. Accepted as R2.
- **One viewer's cancel affects co-viewers.** It shortens the lease for everyone. A co-viewer in a hidden tab polling once a minute (R1) then loses the job after 20 s, and their AC6 re-request restarts it from zero.
- **A CLI enqueue of a key that already has a leased viewer job answers `already present`.** The job stays leased and can still be abandoned. Converting a viewer job to a CLI job is not provided.
- **Lease arithmetic uses `now_ms()` on one host for the Engine and the worker.** A clock step backwards lengthens leases, and a step forwards can abandon a job early. AC6 re-requests in that case.
- **An instance-track takeover leaves stale `wanted_at` on a ready row.** It is inert, because every lease statement is state-gated.

### Tradeoffs the operator is asked to accept

- An abandoned job loses all its work, and a re-request starts from zero.
- A cancel takes effect after about 20 s plus one chunk, not at once.
- A hidden tab whose timers lapse past 180 s restarts its job.
- One viewer's cancel can cost a slow-polling co-viewer a restart.
- A very long video is never refused. It holds the single GPU for its whole run while someone waits, and an unleased CLI job holds it until it ends.
- Every poll on a queued or running job is one short write.
- The whole-list running-cue rewrite stays O(cues) per chunk. This is the named simplification: its ceiling is very long videos, and its upgrade path is append-only cue storage.
- **Two refinements of the settled design that I am choosing and naming:**
  - The cancel is ordered after the page's in-flight request. This narrows the named turn-off race; it does not widen anything.
  - A poll-path re-request follows up with the backoff delay, not 0.
- **A deliberate choice to confirm:** when the abandon DELETE loses to a renewal, the job is requeued, not continued. I am asking the operator to accept this, because the design text says the job continues.

## Impacts

Note on this pass (step 3, pass 3): step 4 pass 2 reopened this step for one missed impact (DEPLOYMENT.md:98) and one inaccurate risk (bytearray front deletion). I re-opened every production file and the cited test anchors against the tree, and all prior entries still hold at their line numbers. This pass also adds what pass 2 did not carry: engine/server/README.md lines 24, 31 and 41; TRANSLATE_WORKER.md lines 33, 85 and 100; the `test_engine_api_client.py` docstring's "routes are exactly state and enqueue"; the `test_subtitles.py` "five nullable job columns" claim; the gateway error prefix (`request_translate` raises `Engine translate request failed`, not `Engine translate failed`); `read_lease` seeing a stale `wanted_at` on a taken-over row; DEPLOYMENT.md line 270's stop-path wording; the generated `tests/last_test_validation.json`; and step 4's claim-drop observability and worker-restart notes.

Discrepancies with the plan text that still stand: Client POST routing is in `_serve_post` (server.py:486), not `do_POST`; `turnOff()` takes no arguments; `QUEUED_ROW` pins every column; and `CONTEXT.md` and `source_fetch.py` both call the media fetch byte-capped.

<impact path="engine/server/db/jobs/translate-worker.py" element="module docstring (lines 2-9) and the api/ sys.path comment (line 35)">
**What changes:**
- Line 6 says `run_job` takes a claim "until exactly one end state". It must add that each chunk-loop wake reads the lease, and that an expired lease abandons the job by deleting its row.
- Line 35 says api/ is on the path "for server_config (the bounds and HEARTBEAT_SECONDS)". After the build the worker imports the chunk and queue bounds, `HEARTBEAT_SECONDS`, `TRANSLATE_LEASE_MS` and the paths, so the comment should name those.

**Depends on it:** nothing at runtime.

**Risk:** wording drift only.
</impact>
<impact path="engine/server/db/jobs/translate-worker.py" element="server_config import line (line 41)">
**What changes:** drop `SUBTITLE_MAX_BYTES` and `SUBTITLE_MAX_DURATION` and add `TRANSLATE_LEASE_MS`. It stays one alphabetical line.

**Depends on it:** `tests/active/test_server_config.py` (lines 383-444) parses this file's AST and requires `HEARTBEAT_SECONDS` to be imported from `server_config` and never bound locally. That still holds while `HEARTBEAT_SECONDS` stays on this line.

**Risk:** an `ImportError` if this line and `server_config` are edited out of step. It fails loudly at collection for every worker test.
</impact>
<impact path="engine/server/db/jobs/translate-worker.py" element="resolve_video() (lines 92-106)">
**What changes:**
- The signature becomes `(whitelist_path, video_id, host)`.
- Lines 103-105 go: the stored-duration branch and its `duration Ns over Ms` text.
- It keeps `PRAGMA busy_timeout = 30000` and the `missing host` → `not in whitelist` mapping.
- The docstring loses "then the stored-duration bound; NULL duration passes".

**Depends on it:**
- `command_enqueue` (line 118) and `generate` (line 387).
- The hand-rolled double `_recording` in `tests/active/test_translate_worker.py` (lines 659-670) is `recorded(whitelist_path, video_id, host, max_duration)` and forwards `max_duration`. A three-argument call raises `TypeError`, which `generate` does not catch as `OperationalError`, so the whitelist back-off tests would fail for the wrong reason.

**Risk:** medium, from the test double. Both production callers are in this file.
</impact>
<impact path="engine/server/db/jobs/translate-worker.py" element="command_enqueue() (lines 109-142)">
**What changes:**
- Line 118 calls `resolve_video` without the bound.
- Line 128 keeps calling `enqueue_translate_job` with no `wanted_at`, so CLI rows carry NULL (AC7).
- The `refused: duration Ns over Ms` outcome disappears.

**Depends on it:** in `test_translate_worker.py`:
- `REFUSALS["stored duration over --max-duration"]` (line 142) passes `--max-duration 600`. With the flag gone, argparse exits 2.
- The matching `CONTROL_KEYS` entry (line 147), the `ENQUEUE_VIDEOS` rows for `lu-1`/`mu-1`, and docstring line 8 exist only for that case.

**Risk:** low in code. The case must be rewritten (for example, a 601 s stored duration now queues) or deleted.
</impact>
<impact path="engine/server/db/jobs/translate-worker.py" element="video_duration() (lines 165-170) deleted, and its use in generate (lines 412-416)">
**What changes:** the function, its call, `video duration unknown` and the JSON over-cap check are deleted.

**Depends on it:** only `generate`. `math` stays imported, because `pick_media_url` (line 161) uses `math.inf` and `chunk_cues` (line 333) uses `math.isfinite`.

**Risk:** low.
</impact>
<impact path="engine/server/db/jobs/translate-worker.py" element="new LOOKAHEAD_SECONDS constant and new JobAbandoned exception (beside lines 56-89)">
**What changes:**
- `LOOKAHEAD_SECONDS = 600` with a one-line comment.
- `class JobAbandoned(Exception)` beside `JobStopped` and `JobTakenOver`, with a one-line docstring.
- `JobFailed`'s docstring ("A bound refused the job…") still holds: the whitelist and URL bounds remain.

**Depends on it:** `AudioPipe`, `translate_audio` and `run_job`.

**Risk:** none on its own.
</impact>
<impact path="engine/server/db/jobs/translate-worker.py" element="AudioPipe class docstring and __init__ (lines 173-192)">
**What changes:**
- The signature becomes `(url, host, max_chunk)`. `self.max_bytes` and `self.max_samples` go.
- New fields: `self.base = 0` and `self.limit = LOOKAHEAD_SECONDS * SAMPLE_RATE + max_chunk` (in samples).
- The line-182 rat-tail ("about 115 MB at the 60-minute cap") becomes a one-line statement of the bound.
- The class docstring's "the download runs at network speed whatever the GPU does" becomes false, because the download slows to the translation's pace once the lookahead is full.
- The threads start inside `__init__` (lines 190-192), so `base` and `limit` must be set before `thread.start()`.

**Depends on it:** `generate` (line 420) is the only constructor call. No test constructs `AudioPipe` today.

**Risk:** medium. A field assigned after the threads start is an intermittent `AttributeError` in `_read`.
</impact>
<impact path="engine/server/db/jobs/translate-worker.py" element="AudioPipe._feed() (lines 203-216)">
**What changes:**
- Line 206 drops `self.max_bytes` from the `stream_media` call.
- The docstring's "the Content-Length precheck and the streamed cap" becomes false. Reword it to: same-host redirects, the socket timeout, and a write that blocks while ffmpeg's stdin is full.

**Depends on it:** `stream_media`'s new signature.

**Risk:** a call left with the positional `max_bytes` puts the int in `consume`. The resulting `TypeError` is neither `SourceFetchFailed` nor `BrokenPipeError`, and `_FETCH_ERRORS` in source_fetch.py does not include it. The feeder thread dies silently, the `finally` closes stdin, and ffmpeg sees EOF, so the job ends with partial or no audio and no error text.
</impact>
<impact path="engine/server/db/jobs/translate-worker.py" element="AudioPipe._read() (lines 218-237): backpressure wait, clamped read1, max_samples abort removed">
**What changes:**
- Lines 227-229 (`audio longer than Ns`) go, with the docstring clause about `max_samples`.
- Before each read, wait on `self.cond` until `limit - len(pcm)//2 > 0`, or `stop` is set, or `error` is set. Then call `read1(min(READ_CHUNK_BYTES, room*BYTES_PER_SAMPLE))`.
- On a stop or error exit, the loop must still reach `proc.wait()`, `threads[2].join()` and `done = True` with `notify_all`.

**Depends on it:** `wait_samples`, `close`, `_fail`, and `_feed`, which now blocks in `stdin.write` while `_read` is parked.

**Risks:**
- (1) `read1` can return an odd byte count, so the AC3 assertion must count samples.
- (2) The condition must not be held across `read1`. Holding it would block `wait_samples` and `slice`, and so the main thread.
- (3) `_fail` sets `error` under the lock but `stop` only after releasing it (lines 196-200). The wait predicate must therefore include `error is not None`, or `_fail` must set `stop` first.
- (4) `threads[2].join()` returns only at ffmpeg's stderr EOF, so ffmpeg must be killed on every early exit.
- (5) A parked reader leaves ffmpeg blocked on stdout and the feeder blocked in `stdin.write`, so the socket goes unread. R2 applies: the remote send timeout, during a model load or a long Whisper call.
</impact>
<impact path="engine/server/db/jobs/translate-worker.py" element="AudioPipe._fail() (lines 194-201) and AudioPipe.close() (lines 255-262)">
**What changes:**
- `close` sets `stop`, then `notify_all` under `self.cond`, before `proc.kill()` and the joins.
- `_fail` sets `stop` before or inside its `with self.cond:` block.
- `close`'s docstring ("the feeder's join is bounded by one socket timeout") still holds as an upper bound. A feeder blocked in `stdin.write` is released by the ffmpeg kill (`BrokenPipeError`), not by the socket.

**Depends on it:**
- `generate`'s `finally: pipe.close()` (line 424) on every exit, now including `JobAbandoned`.
- DEPLOYMENT.md line 270's `TimeoutStopSec=120` reasoning.

**Risk:** high. A parked `_read` that is never woken hangs `thread.join()` on stop, abandon or failure until systemd's SIGKILL. That leaves the row `running`, and a second occurrence fails it `worker stopped while running twice`.
</impact>
<impact path="engine/server/db/jobs/translate-worker.py" element="AudioPipe.wait_samples() (244-248), AudioPipe.slice() (250-253), new AudioPipe.release(upto)">
**What changes:**
- `wait_samples` compares and returns absolute samples: `base + len(pcm)//BYTES_PER_SAMPLE`.
- `slice` subtracts `base` from both bounds.
- `release(upto)` runs under the condition: `del pcm[:(upto-base)*2]`, `base = upto`, then `notify_all`.
- The docstrings say "absolute".

**Depends on it:** `translate_audio`, the only caller (lines 344 and 355). `final`, `available <= pos` and `pos / SAMPLE_RATE` stay absolute.

**Risk:**
- `slice` with `start < base` reads the wrong bytes silently through a negative index. It should assert `start >= base`, and `release` must never pass `pos`.
- Corrected from the earlier pass: in CPython ≥3.4, `del buf[:n]` on a bytearray advances an internal start offset in O(1) and copies nothing. The live bytes are copied later, when the reader thread's `+=` reallocates. Peak memory can briefly reach about twice the bounded buffer during that copy, and the cost falls on the reader thread, not the main thread. AC3's logical-length assertion is unaffected.
</impact>
<impact path="engine/server/db/jobs/translate-worker.py" element="translate_audio() (lines 338-381): lease check per wake, release after each window">
**What changes:**
- After the `stop` check (line 346), read `job.read_lease()`. If it is not None and `<= now_ms() - TRANSLATE_LEASE_MS`, raise `JobAbandoned`.
- After `pos += cut` (line 372), call `pipe.release(pos)`.

**Depends on it:**
- `generate`.
- Every Rig pipeline test. `Rig.claim` (test_translate_worker.py:543) enqueues positionally with no `wanted_at`, so those rows are never abandoned.
- `progress["at"]` is still refreshed every wake (line 345).

**Risks:**
- (1) A `sqlite3.OperationalError` from `read_lease` (a lock held past 30 s) falls into `run_job`'s generic `except Exception` and fails a viewer's job. Guard it and treat a failure as "not expired".
- (2) Tests must monkeypatch `worker.now_ms`, the module-level import at line 46. Today no worker test does; they use real wall-clock `_now_ms()` (line 264).
- (3) The check sits before `pipe.error`, so an expired lease on a failed pipe abandons the job rather than failing it.
- (4) New: a primary-key `read_lease` on a row that the instance-track store has turned `ready` still reads the stale `wanted_at` that `store_ready_subtitles` leaves behind. If that value has expired, the worker raises `JobAbandoned` instead of reaching the next claim-conditional write. `abandon` and `requeue` then both return False, so `run_job`'s False/False path must log `taken over by the instance track`. Gating `read_lease` on `state='running' AND started_at=?` avoids the detour.
</impact>
<impact path="engine/server/db/jobs/translate-worker.py" element="generate() (lines 384-424)">
**What changes:**
- Line 387 calls `resolve_video` without `args.max_duration`.
- Lines 412-416 are deleted.
- Line 420 becomes `AudioPipe(url, media_host(url), args.max_chunk_seconds * SAMPLE_RATE)`.
- The docstring's "each bound raising JobFailed" still holds.

**Depends on it:** `run_job`, and in `test_translate_worker.py`:
- the `Namespace(... max_duration=..., max_bytes=...)` objects at lines 553, 684 and 984 (extra attributes are harmless);
- `BOUNDS` (lines 352-359): JSON duration unknown, JSON duration over the cap, Content-Length over max_bytes, streamed past max_bytes, decoded audio past max_duration;
- `rig.run(..., max_bytes=..., max_duration=...)` at line 910;
- the fetch-reasons case "video JSON served, duration over the cap" (line 946);
- docstring lines 15, 16 and 22.

**Risk:** certain test churn; low production risk.
</impact>
<impact path="engine/server/db/jobs/translate-worker.py" element="run_job() (lines 427-452) and its docstring">
**What changes:**
- A new `except JobAbandoned:` branch before `except Exception` (line 446). It calls `job.abandon(now_ms() - TRANSLATE_LEASE_MS)`:
  - True logs info `[translate-worker] abandoned, no viewer video_id=%s host=%s`.
  - False calls `requeue()`. If that is also False, it logs `taken over by the instance track`.
  - It returns False.
- The docstring's "Take one claimed job to exactly one end state, or back to queued" becomes false: an abandoned job ends with its row deleted.

**Depends on it:** `serve`, the TRANSLATE_WORKER.md Logs section, and the DEPLOYMENT.md triage rows.

**Risk:**
- The requeue lowers `attempts` and keeps `queued_at`, so the job is reclaimed at once and restarts from zero.
- A `sqlite3.Error` from `abandon` is uncaught here, and `serve` does not wrap `run_job` (lines 487-488), so the service loop would die. The branch needs its own try.
- Requeue versus literal continuation is still the operator's choice, and it decides where `abandon` is called.
</impact>
<impact path="engine/server/db/jobs/translate-worker.py" element="serve() (lines 471-494): claim with the lease cutoff">
**What changes:** line 477 computes `now = now_ms()` and calls `claim_translate_job(conn, TARGET_LANGUAGE, now, expired_at=now - TRANSLATE_LEASE_MS)`. Per step 4's recommendation 2, it may log `[translate-worker] dropped N queued jobs with no viewer` when the claim reports a non-zero drop count.

**Depends on it:**
- `claim_translate_job`'s new keyword.
- The serve back-off and stall tests (lines 782 and 1195-1260), whose rows are unleased.

**Risk:**
- Low if the cutoff is a keyword with a default.
- The drop is otherwise silent, so the planned DEPLOYMENT.md triage row has no symptom to point to.
</impact>
<impact path="engine/server/db/jobs/translate-worker.py" element="parse_args() (lines 550-569)">
**What changes:** delete `enqueue --max-duration` (561), `run --max-duration` (565) and `run --max-bytes` (566). `_positive_int` stays, for `--cap`, `--max-chunk-seconds` and `--stall-seconds`.

**Depends on it:**
- The `REFUSED_STALL_SECONDS` comment in `test_translate_worker.py` (line 215) cites `run --max-duration`.
- `scripts/run-services.sh` line 185 runs `run` with no flags (verified), so it is unaffected.
- A hand-customised systemd `ExecStart` that passes either flag exits 2 and restart-loops (DEPLOYMENT.md lines 254-256, `RestartPreventExitStatus=6` only).
- `scripts/deploy-bluegreen.sh` never restarts the worker. The new code takes effect only after a manual `systemctl restart peertube-translate-worker`.

**Risk:** an operator-side regression on upgrade, which a DEPLOYMENT.md upgrade note must cover.
</impact>
<impact path="engine/server/db/jobs/translate-worker.py" element="heartbeat_loop() (lines 455-468): unchanged, but its stop behaviour now loses viewers' jobs">
**What changes:** none in code. The loop exits on `stop` (line 465), so after any stop, restart or crash longer than 15 s the Engine answers `available: false`.

**Depends on it:** the page's `applyState` (translate.ts:199-200) stops polling a queued or running job when `available` is false. With no renewals, the job is dropped at the next claim or abandoned 180 s later.

**Risk:** this is the runtime trigger of the open recommendation 1. The heartbeat itself needs no change.
</impact>
<impact path="engine/server/data/subtitles.py" element="module docstring (line 3) and SUBTITLES_BUSY_TIMEOUT_SECONDS comment (line 15)">
**What changes:**
- Line 3's "a TranslateJob whose six methods (...) each match only while the row is running" gains `read_lease` (a read) and `abandon` (a conditional DELETE). It should also name the `wanted_at` lease column, `renew_translate_lease`, `cancel_translate_lease` and the claim's expired-row DELETE.
- Line 15's writer list ("the blue/green Engines and the translate worker (claim, per-chunk rewrites, a heartbeat)") gains the Engine's renewal on queued/running state reads, the cancel, and the worker's claim DELETE and abandon DELETE.

**Depends on it:** nothing at runtime.

**Risk:** doc drift.
</impact>
<impact path="engine/server/data/subtitles.py" element="JOB_COLUMNS (line 23) and ensure_subtitles_schema() (lines 56-79)">
**What changes:** append `("wanted_at", "INTEGER")`. The loop at lines 74-77 adds it in place under IMMEDIATE. No index is needed, because the claim DELETE filters `state='queued'`, which `subtitles_state_queued_at` covers.

**Depends on it:**
- Every opener: Engine start, `open_translate_worker_store` and CLI `enqueue`.
- `tests/active/test_subtitles.py`: `JOB_COLUMN_NAMES` (line 73) feeds `ALL_COLUMNS`, which the upgrade tests and `UPGRADE_SCRIPT` compare exactly. The docstring's "fourteen columns" (lines 10 and 26) and "five nullable job columns" (line 7) become fifteen and six.
- `QUEUED_ROW` in `test_internal_translate.py` (line 664, a 14-tuple compared against `SELECT *`).

**Risk:** low at runtime (a metadata-only ALTER). An older blue/green Engine ignores the column and inserts NULL, so its jobs behave like CLI jobs.
</impact>
<impact path="engine/server/data/subtitles.py" element="enqueue_translate_job() (lines 156-169)">
**What changes:** a keyword-only `wanted_at: int | None = None`, added to the INSERT's columns and values (line 166). The docstring notes the lease, and that `exists` neither renews nor overwrites.

**Depends on it:**
- The Engine's enqueue route passes `wanted_at=now_ms()`. The CLI passes nothing.
- The positional six-argument calls in all three test files stay valid.
- `QUEUED_ROW` needs `NOW` as its 15th element.

**Risk:** certain churn on `QUEUED_ROW`.
</impact>
<impact path="engine/server/data/subtitles.py" element="TranslateJob (lines 172-205): class docstring, new read_lease() and abandon()">
**What changes:**
- `read_lease()` reads `wanted_at` by key; a missing row reads None.
- `abandon(expired_at)` runs, under `with self.conn:`, `DELETE ... WHERE {_KEY} AND state='running' AND started_at=? AND wanted_at IS NOT NULL AND wanted_at <= ?` and returns `rowcount == 1`.
- The class docstring's "Every method is one conditional UPDATE" must be reworded.

**Depends on it:**
- `translate_audio` and `run_job`.
- `test_subtitles.py`'s takeover test enumerates the six methods; `abandon` should join the set that returns False after a takeover.

**Risk:** low. Issue 54's rule holds because `abandon` is conditional on the claim. See the `translate_audio` entry for `read_lease` and stale leases.
</impact>
<impact path="engine/server/data/subtitles.py" element="claim_translate_job() (lines 208-217)">
**What changes:** a keyword `expired_at: int | None = None`. When it is given, the same `_immediate` block first runs `DELETE FROM subtitles WHERE state='queued' AND target_language=? AND wanted_at IS NOT NULL AND wanted_at <= ?`. The docstring gains the drop. Making the drop observable (step 4's recommendation 2) can use a keyword-only out-value, so the return shape and its ten-odd callers stay unchanged; the module has no logger today.

**Depends on it:** positional callers:
- `serve`;
- `test_internal_translate.py:694`;
- `test_translate_worker.py:544, 983`;
- `test_subtitles.py:150, 355, 390, 605, 617, 647`, including the subprocess scripts.

**Risk:** medium.
- A sign or unit error, or a missing NOT NULL or state gate, silently deletes viewers' queued jobs, or CLI or ready rows, at every 2 s idle poll.
- A required positional parameter breaks every caller listed above.
</impact>
<impact path="engine/server/data/subtitles.py" element="new renew_translate_lease(conn, video_id, instance_domain, target_language, now)">
**What changes:** a new function. Under `with conn:`, it runs `UPDATE subtitles SET wanted_at=? WHERE {_KEY} AND state IN ('queued','running') AND wanted_at IS NOT NULL`.

**Depends on it:** `internal_translate._read_key`, and the engine README's store list.

**Risk:** it runs on every queued/running poll under `subtitles_db_lock`. With the 30 s busy timeout it can outlast the Client's 20 s `TRANSLATE_TIMEOUT_SECONDS`, which surfaces as a 502 that the page retries with backoff.
</impact>
<impact path="engine/server/data/subtitles.py" element="new cancel_translate_lease(conn, key..., capped_at)">
**What changes:** a new function, `UPDATE ... SET wanted_at = MIN(wanted_at, ?)`, with renewal's key, state and NOT NULL predicate.

**Depends on it:** the new Engine cancel handler.

**Risk:** low. A store test must pin that it never lengthens a lease and never touches CLI, ready, failed or already_english rows.
</impact>
<impact path="engine/server/data/subtitles.py" element="_recover_translate_jobs() (220-225), TranslateJob.requeue() (199-201), store_ready_subtitles() (132-143): unchanged">
**What changes:** none.
- `requeue` and recovery keep `wanted_at`.
- `store_ready_subtitles`' `DO UPDATE SET` leaves a stale `wanted_at` on a ready row. Every lease write ignores it because each is state-gated; `read_lease` is the exception, see `translate_audio`.

**Depends on it:**
- The claim DELETE drops a recovered row whose lease expired while the worker was down.
- Recovery still fails a row found running twice, even with an expired lease. That row then answers `failed`, not `none`, so AC6 does not re-request it. This is the existing rule and is accepted.

**Risk:** none if left untouched.
</impact>
<impact path="engine/server/data/source_fetch.py" element="stream_media() (lines 122-145)">
**What changes:**
- The signature becomes `(url, host, consume, stop)`.
- Lines 128-131 and 136-138 are deleted, along with `media over N bytes` and the docstring clause.
- `fetch_bounded`, `FETCH_MAX_BYTES` and `MEDIA_SOCKET_TIMEOUT_SECONDS` are untouched. The latter's comment ("the only stall bound on the download") still holds, but the timeout cannot fire while `consume` is blocked; that is R2.

**Depends on it:**
- `AudioPipe._feed` (worker line 206), the only production caller.
- `tests/active/test_source_fetch.py`: every `stream_media(MEDIA_URL, HOST, MEDIA_SIZE, …)` call (lines 322-445); the three cap tests (349, 359, 371); the `MEDIA_SIZE` comment (line 31); docstring line 5.

**Risk:** certain test churn. A leftover positional int lands in `consume` and raises an uncaught `TypeError`.
</impact>
<impact path="engine/server/data/source_fetch.py" element="module docstring (lines 1-4)">
**What changes:** "a byte cap" is listed as part of the one rule. Reword: `fetch_bounded` caps the body, and `stream_media` is bounded by its socket timeout, `stop` and the consumer's backpressure.

**Depends on it:** CONTEXT.md's "Source-instance fetch" term.

**Risk:** doc drift.
</impact>
<impact path="engine/server/api/server_config.py" element="SUBTITLE_MAX_DURATION / SUBTITLE_MAX_BYTES (lines 421-424) removed; TRANSLATE_LEASE_MS and TRANSLATE_CANCEL_GRACE_MS added">
**What changes:**
- Delete both caps and their comments.
- Add `TRANSLATE_LEASE_MS = 180_000` and `TRANSLATE_CANCEL_GRACE_MS = 20_000`, each with a one-line comment. The grace must stay above the page's 16 s `STATE_POLL_MAX_MS`.

**Depends on it:**
- The worker's import line and `internal_translate`'s import (line 27).
- Outside docs/project, delete_me, tests/tmp and tests/archive, the caps appear only here, in the worker, in engine/server/README.md:35, in TRANSLATE_WORKER.md and in DEPLOYMENT.md (grepped).

**Risk:** low.
</impact>
<impact path="engine/server/api/handlers/internal_translate.py" element="module docstring (lines 1-8) and imports (lines 22-27)">
**What changes:**
- The docstring gains a cancel-route paragraph. It also needs renewal on a queued/running state read and the lease on enqueue.
- Line 3's "This route stores only ready" becomes false, because the state route now also renews `wanted_at`.
- Line 23 imports `cancel_translate_lease` and `renew_translate_lease`.
- Line 27 imports `TRANSLATE_LEASE_MS` and `TRANSLATE_CANCEL_GRACE_MS`.

**Depends on it:** `router.py`; `test_server_config.py` (the handler's `HEARTBEAT_FRESH_MS` identity check, unaffected).

**Risk:** low.
</impact>
<impact path="engine/server/api/handlers/internal_translate.py" element="_read_key() (lines 171-180)">
**What changes:**
- When the row read is `queued` or `running`, call `renew_translate_lease(conn, …, now_ms())` in the same lock hold, inside its own `try/except sqlite3.Error` that logs a warning and keeps the answer.
- Use the module-level `now_ms`, which `_route` pins (`test_internal_translate.py:679`).
- The docstring currently describes a pure read and must mention the renewal.

**Depends on it:** `handle_internal_translate` (line 240). `BRANCHES` (lines 968-979) and the running-cue tests seed unleased rows, so their answers and rows are unchanged.

**Risk:** medium.
- A renewal error caught only by the outer `except` turns into `(None, False)`. That ends the page's poll, which under the lease loses the job.
- Renewing ready, failed or missing rows would add a write to the instance-fetch path.
</impact>
<impact path="engine/server/api/handlers/internal_translate.py" element="handle_internal_translate_enqueue() (lines 265-284)">
**What changes:** line 274 passes `wanted_at=now_ms()`, and the docstring notes the lease.

**Depends on it:** `QUEUED_ROW` and its comparisons (lines 1123, 1159, 1174). The test at 1127 ("row unchanged") still holds, because enqueue never renews.

**Risk:** certain churn on `QUEUED_ROW`.
</impact>
<impact path="engine/server/api/handlers/internal_translate.py" element="new handle_internal_translate_cancel()">
**What changes:** a new handler.
- It calls `_resolve_translate_key` (400/404).
- In one `_subtitles_store` hold it runs `cancel_translate_lease(..., now_ms() - TRANSLATE_LEASE_MS + TRANSLATE_CANCEL_GRACE_MS)`, then `fetch_subtitle_state` and `_generation_available`.
- It answers `{state or "none", available}` with no cues.
- A `sqlite3.Error` is logged and answers 503 `Translate store unavailable`.
- A closed store answers `{none, false}`.

**Depends on it:** `router.POST_ROUTES`, the Client's `cancel_translate`, and the contract fixture's cancel cases.

**Risk:** a ready row whose cues do not load answers `ready` here but `none` on the state route. That is harmless for a fire-and-forget call. The downstream parsers must accept `ready`/`running` without cues, so they mirror the request parsers.
</impact>
<impact path="engine/server/api/handlers/internal_translate.py" element="_resolve_translate_key() docstring (line 205) and resolve_translatable_video() docstring (line 143)">
**What changes:** "both translate routes" and "both /internal/translate routes" become all three.

**Depends on it:** nothing.

**Risk:** doc drift.
</impact>
<impact path="engine/server/api/router.py" element="module docstring (lines 18-19), import (line 43), POST_ROUTES (lines 144-145)">
**What changes:**
- Add a docstring line `- POST /internal/translate/cancel: … [bridge gate]`.
- Import `handle_internal_translate_cancel`.
- Add the `"/internal/translate/cancel"` entry.

**Depends on it:**
- The `/internal/` bridge gate covers the new path.
- `test_router.py` stubs named paths only.
- `test_internal_translate.py`'s startup test (lines 1285-1286 pattern) should POST the new route with and without the token.

**Risk:** low.
</impact>
<impact path="engine/server/api/handlers/__init__.py" element="package docstring (line 8)">
**What changes:** the internal_translate line gains the cancel bridge request.

**Depends on it:** nothing.

**Risk:** doc drift.
</impact>
<impact path="client/backend/server.py" element="engine_api_client import (lines 32-35)">
**What changes:** add `cancel_translate`, in the existing alphabetical order.

**Depends on it:** every Client test imports this module.

**Risk:** a typo fails the whole Client suite loudly.
</impact>
<impact path="client/backend/server.py" element="ClientBackendHandler._serve_post (translate branch lines 561-566); the plan says do_POST">
**What changes:**
- Routing is in `_serve_post`; `do_POST` (line 412) only wraps it.
- Add an exact-path `/api/translate/cancel` branch before the 404 at line 571: `_rate_limit_check(url.path)` answering 429, then `_handle_translate_cancel()`.
- The limiter keys `"{ip}:{path}"` (line 586), so the route gets its own bucket.

**Depends on it:**
- `PROXY_READ_POST_ROUTES` (checked first at line 489) does not contain the path.
- `PROXY_ALLOWED_QUERY_PARAMS` (lines 116-117) needs no entry, because cancel reads a body.

**Risk:** low.
</impact>
<impact path="client/backend/server.py" element="new _handle_translate_cancel() beside _handle_translate_post (lines 1131-1151)">
**What changes:** a line-for-line mirror of `_handle_translate_post`:
- `_require_profile()` first, so 401 comes before the body is read;
- `read_json_body`, answering 400;
- the same id/host validation against `BLOCK_REFERENCE_MAX_LENGTH`;
- `cancel_translate` with the stripped values;
- `_respond_engine_failure("translate", exc)`, answering 502 `Engine translate failed`.

**Depends on it:** `test_server.py` and `client/README.md`.

**Risk:** low. The 502 text is shared with the other translate routes, so only the log's `context.error` and `path` tell a cancel failure apart.
</impact>
<impact path="client/backend/lib/engine_api_client.py" element="new cancel_translate() beside request_translate (lines 222-232); constants (lines 17-23)">
**What changes:** a new function.
- It POSTs `{id, host}` to `/internal/translate/cancel` with `_post_json`'s default 6 s timeout.
- A 404 `Video not found` maps to `{none, false}`.
- Any other non-200 raises `EngineApiError`. The text must begin `Engine translate` (for example `Engine translate cancel failed (HTTP N): …`), because `test_engine_api_client.py:81` matches `^Engine translate`. `request_translate` itself uses `Engine translate request failed`.
- The state must be in `TRANSLATE_STATES` (`busy` is rejected), and `available` goes through `_translate_available`. It never returns cues.
- The comment at line 22 may note that cancel uses `TRANSLATE_STATES`.

**Depends on it:** in `test_engine_api_client.py`:
- the import (line 21);
- `ROUTES` (line 26);
- the replay dispatch (line 88);
- `set(ROUTES)` (line 96);
- the per-route loop (line 98), which gains `("cancel", TRANSLATE_STATES)`.

**Risk:** low.
</impact>
<impact path="client/frontend/src/data/translate.ts" element="new cancelTranslate(); module doc comment (lines 1-5)">
**What changes:**
- An exported `cancelTranslate(apiBase, id, host)` mirrors `requestTranslate` (lines 72-82): a POST to `/api/translate/cancel`, then `readTranslateResponse`.
- The state must be one of the six stored states. Add a constant beside `REQUEST_STATES` (line 20) that excludes `busy`.
- `available` goes through `parseAvailable`.
- It returns `{state, available}`, typed with a new or reused type, since `TranslateRequestState` includes `busy`.
- The module comment names the cancel request.

**Depends on it:** the page module, and the contract replay in `test_frontend_translate.py` (`CONTRACT_RUNNER` line 743 import, line 750 dispatch, and the `_result` method/path control at 818-819).

**Risk:** certain test churn.
</impact>
<impact path="client/frontend/src/pages/video-page/translate.ts" element="applyState() lines 199-200: the poll ends on queued/running without available">
**What changes:** today `if (!state.available) return;` stops polling a queued or running job while the heartbeat is stale. Under the lease, a stopped poll means no renewal, so the job is lost (dropped at claim, or abandoned 180 s later). The page then sits on "Waiting…" or "Translating…" with no poll left to re-request. Triggers:
- any heartbeat gap over 15 s (a worker restart, crash or stop);
- a `_read_key` store error or closed store, which reads as `none` with `available: false`.

Recommendation 1 (still open with the operator) is to keep polling `queued`/`running` at `STATE_POLL_MAX_MS` while `available` is false, rewording the line-199 comment. This reverses plan 50's "never polled" rule for those two states.

**Depends on it:**
- A new frontend scenario (queued without available, then queued, then running), if the recommendation is taken.
- The docs that state the never-polled rule: CONTEXT.md:18, client/frontend/README.md:29-30, DEPLOYMENT.md:236.

**Risk:** high at runtime if left as is. If the recommendation is declined, DEPLOYMENT.md triage must say that a worker restart over 15 s drops waiting viewers' jobs.
</impact>
<impact path="client/frontend/src/pages/video-page/translate.ts" element="applyState() else branch (lines 190-197) and applyRequest() (lines 151-162): AC6 re-request on a poll-path none">
**What changes:**
- In the else branch, `none` with `available` while the ticket is current no longer ends the poll. It calls `dropRunning()` and `setStatus(WAITING)`, then `requestTranslate` and `applyRequest` under the current ticket.
- A rejection is handled as in `turnOn` (line 136).
- `applyRequest` gains a delay parameter: 0 from `turnOn`, and the doubled `stateDelay` from the poll path.
- The branch returns before line 201, so it must double `stateDelay` itself. Otherwise a ready row whose cues do not load costs a request pair every 2 s.
- `turnOn`'s first answer (lines 127-131) never reaches this branch, because `turnOn` handles `none` with `available` itself. `applyRequest` → `applyState` with an enqueue `none` always carries `available: false`, so it does not recurse.

**Depends on it:** `GENERATION_SCENARIOS` in `test_frontend_translate.py` (lines 563-578):
- `"available"` (gets `[none]`, posts `[queued]`) now re-POSTs repeatedly, because each `none`→`queued` flip is a change that resets the delay. That breaks `len(POST) == 1` at line 648. It needs gets `[none, queued]`.
- `"stop-none"` (gets `[queued, none]`, `available` defaulting to true at line 560) now sends an unconfigured POST that gets 500. The test at line 705 still passes on `gets == 2`, but no longer for its stated reason. It should use `available=False`, with a separate AC6 scenario added.
- The ENDED_LABELS comment at line 191 is updated.

**Risk:** high for the suite. At runtime, a ready row whose cues do not load now shows "Waiting for translation…" indefinitely instead of "No English translation…".
</impact>
<impact path="client/frontend/src/pages/video-page/translate.ts" element="turnOff() (lines 140-149) and the click listener in onReady (lines 107-110)">
**What changes:**
- `turnOff()` takes no arguments, and `apiBase`/`video` are not in its scope. The listener's `if (on) turnOff();` must pass them, or the module must hold them.
- After the synchronous resets, it chains `cancelTranslate(apiBase, video.id, video.host)` after the tracked in-flight promise, with a `.catch`, and never awaits.

**Depends on it:**
- The first runner's stub (line 169) answers only `/api/translate` specially, and every other path gets `{}` 200. `cancelTranslate` then throws `MALFORMED`, so the `.catch` must swallow it or `rejections` fills.
- `_translate_requests` (line 255) and the click test filter the exact path `/api/translate`, so the cancel is hidden. They should assert one cancel.
- The generation runner's stub (lines 485-505) also answers the cancel with a generic `{}` 200. Give it its own answers key (500 when unconfigured), widen `_asked` (line 625), `count` (line 505) and `_translate_by_method` (line 616) where needed, and have `stop-off` assert exactly one cancel after the last GET.

**Risk:**
- One cancel per off-click; it does nothing on the Engine when there is no job.
- An off-then-on click can land the old cancel after the new enqueue, shortening the fresh lease to 20 s. The next poll heals it.
</impact>
<impact path="client/frontend/src/pages/video-page/translate.ts" element="new in-flight promise tracking in turnOn() (lines 116-138), scheduleStatePoll() (line 210) and the AC6 re-request">
**What changes:** a module variable holds the promise of the one in-flight `fetchTranslate`/`requestTranslate`. It is set at every request site, including the AC6 re-request and any unavailable poll, and `turnOff` chains its cancel after it.

**Depends on it:** the new scenario "cancel ordered after an in-flight poll", which needs a per-answer delay option in `GENERATION_RUNNER`'s fetch stub.

**Risk:** low, but a request site that does not register reopens the race: a poll still in flight after the cancel renews the lease to 180 s. A pending timer is cleared by `resetStatePoll` and needs no ordering.
</impact>
<impact path="client/frontend/src/pages/video-page/translate.ts" element="module doc comment (lines 1-7)">
**What changes:** line 6 says "it ends on any other state, an answer without `available`, a 401, or turnOff". It must say:
- `none` with `available` re-requests, with backoff;
- turnOff sends a cancel after the in-flight request;
- queued/running without `available` keeps polling, if recommendation 1 is taken.

**Depends on it:** nothing.

**Risk:** doc drift.
</impact>
<impact path="client/frontend/src/pages/video-page/index.ts" element="setupTranslate call">
**What changes:** none expected. `setupTranslate(iframe, apiBase, video)` already supplies what `onReady` passes on.

**Depends on it:** the generation-runner bundle (esbuild of index.ts).

**Risk:** none unless `setupTranslate`'s signature changes.
</impact>
<impact path="client/frontend/dist/assets/video-Cbu0t9sB.js" element="committed built bundle">
**What changes:** not regenerated by this build; `scripts/sync.sh` builds before a deploy.

**Depends on it:** deploys.

**Risk:** an unbuilt `dist/` serves the old page: no cancel, no AC6, and the poll still stops on `available:false`. The lease still lets closed tabs lapse.
</impact>
<impact path="tests/active/fixtures/translate_contract.json" element="description (line 2) and cases">
**What changes:**
- The description names a third route, cancel (`POST /internal/translate/cancel`), answering `{state, available}` with no cues.
- New cases:
  - the six stored states with and without `available`;
  - exactly one 404 `Video not found` → `{none, false}` (the coverage test requires exactly one per route);
  - a route-missing 404 → rejected;
  - `busy` → rejected;
  - an unknown state → rejected;
  - `available` as a string → rejected.

**Depends on it:** all three replayers hard-code two routes:
- `test_engine_api_client.py`: `ROUTES` and the loop;
- `test_frontend_translate.py`: `CONTRACT_RUNNER`, `_result`, `len(asked)`;
- `test_internal_translate.py`: `ENGINE_DRIVERS` (809), `ROUTE_STATES` (827), `HANDLERS` (828), and the exact-set check at line 880.

`tests/config.json` already maps the fixture to all three.

**Risk:** high for the suite. The fixture and all three replayers must land together.
</impact>
<impact path="tests/active/test_internal_translate.py" element="QUEUED_ROW (664), ENGINE_DRIVERS (809), ROUTE_STATES (827), HANDLERS (828), startup test (~1285), docstring">
**What changes:**
- `QUEUED_ROW` gains `NOW` (the enqueue route's lease).
- Cancel drivers for the six states are added to `ENGINE_DRIVERS` and `ROUTE_STATES`, and `HANDLERS` gains `"cancel": "handle_internal_translate_cancel"`.
- New tests:
  - a state read renews leased queued/running rows, and leaves unleased or ready rows alone;
  - a renewal failure keeps the answer;
  - cancel: 400, 404, 503, closed store, `MIN` never lengthening, and the answered state.
- The startup test covers the cancel route with and without the token.
- The docstring's counts are updated.

**Depends on it:** `test_source_fetch.py` imports this module.

**Risk:** certain churn. `_route` pins `now_ms`.
</impact>
<impact path="tests/active/test_subtitles.py" element="JOB_COLUMN_NAMES (73), docstring (lines 7, 10, 26), claim and takeover tests">
**What changes:**
- `wanted_at` is added, giving 15 columns; the docstring's "five nullable job columns" becomes six and "fourteen columns" becomes fifteen.
- New tests:
  - the claim DELETE drops expired rows and keeps fresh and NULL ones, and drops nothing without a cutoff;
  - renew and cancel touch only leased queued/running rows, and cancel never lengthens;
  - `abandon` matches only the claim with an expired lease, and returns False after a takeover;
  - `read_lease` returns None for a CLI row.

**Depends on it:** `UPGRADE_SCRIPT` compares column sets.

**Risk:** certain churn.
</impact>
<impact path="tests/active/test_translate_worker.py" element="_recording (659-670), Rig.claim/Rig.run (540-556), _serving Namespace (684), fetch reasons (946, 984), BOUNDS (352-359), REFUSALS/CONTROL_KEYS (142-147), REFUSED_STALL_SECONDS comment (215), docstring (8, 15, 16, 22)">
**What changes:**
- `_recording` becomes `recorded(whitelist_path, video_id, host)`. It still records every call and forwards all three arguments, and its expected call sequences are unchanged.
- The cap cases are removed or inverted: a JSON with no duration translates; a long stored or JSON duration translates; the enqueue duration refusal becomes a queued case.
- `Rig.claim` needs a way to enqueue a leased row.
- New tests:
  - `AudioPipe`'s bound against a fake ffmpeg, by monkeypatching `worker.FFMPEG_ARGS`, which is read at call time;
  - park and resume on `release`;
  - a chunk longer than the lookahead does not deadlock;
  - `close` wakes a parked reader;
  - an expired lease abandons the job, leaves `rig.row() == {}` and logs one line, with `worker.now_ms` monkeypatched;
  - a renewal racing the delete keeps the job;
  - a CLI job is never abandoned.

**Depends on it:** ffmpeg on PATH (skips at lines 477 and 712).

**Risk:** certain churn. The `cues_writes` trigger (line 514) fires only on `UPDATE OF cues_json`, so `read_lease`, the claim DELETE and `abandon` do not disturb it.
</impact>
<impact path="tests/active/test_source_fetch.py" element="stream_media tests (316-445), MEDIA_SIZE comment (31), docstring line 5">
**What changes:**
- Every call drops `MEDIA_SIZE`.
- The three cap tests (349, 359, 371) are deleted, or replaced by a test that a huge declared Content-Length streams whole.
- The docstring loses `media over` and "a declared length equal to `max_bytes`".

**Depends on it:** nothing else.

**Risk:** a leftover positional int lands in `consume`.
</impact>
<impact path="tests/active/test_engine_api_client.py" element="docstring (lines 5, 8), import (21), ROUTES (26), replay (73-88), coverage (91-104)">
**What changes:**
- `ROUTES` gains `cancel`, the replay dispatches `cancel_translate`, the import gains it, and the loop adds `("cancel", TRANSLATE_STATES)`.
- Docstring line 8's "the routes are exactly state and enqueue" and "each route has exactly one 404" are updated for three routes. Line 5 names the cancel path.

**Depends on it:** the fixture.

**Risk:** certain churn.
</impact>
<impact path="tests/active/test_frontend_translate.py" element="first runner stub (169), _translate_requests (255), GENERATION_RUNNER stub (485-505) and count (505), GENERATION_SCENARIOS (563-578), _generation_env (581-586), _asked (623-625), stop test (704-713), CONTRACT_RUNNER (728-760), _result (814-819), docstring">
**What changes:**
- The contract replay learns cancel.
- `_generation_env` gains a `POST /api/translate/cancel` answers key. The stub looks it up (500 when unconfigured) instead of answering `{}` 200, and gains a per-answer delay.
- `_asked` includes the cancel path.
- Scenario fixes: `"available"` gets `[none, queued]`; `"stop-none"` uses `available=False`.
- New scenarios:
  - an AC6 re-request on a poll-path `none`;
  - the backoff on a repeated ready re-request;
  - cancel on turnOff, with `{id, host}` and the key;
  - cancel ordered after an in-flight poll;
  - queued without `available` keeps polling, if recommendation 1 is taken.
- The click test asserts the cancel.
- The docstring (lines 18, 29, 32) is updated.

**Depends on it:** node and esbuild.

**Risk:** high churn. The scenarios use real timers, about 20 s each, and run in parallel.
</impact>
<impact path="tests/active/test_server.py" element="translate gateway section (lines ~1552-1960)">
**What changes:** new `POST /api/translate/cancel` tests:
- 429 first, then 401 before the body, then the 400s;
- one call to `/internal/translate/cancel` with the bridge token and request id, and none to the other routes;
- the `Video not found` mapping;
- a 503, and an old Engine's 404, each → 502.

They can reuse `_routed_translate_engine` (line 1826) beside `TRANSLATE_ENQUEUE_ROUTE` (line 1726). Docstring line 145's pattern is extended.

**Depends on it:** `tests/config.json` already maps `server.py` and `engine_api_client.py`.

**Risk:** low.
</impact>
<impact path="tests/config.json" element="test_groups mappings (lines 425-466)">
**What changes:** `test_internal_translate.py` gains `engine/server/api/router.py`, because its startup test exercises the new registration. Optionally `test_translate_worker.py` gains `engine/server/data/source_fetch.py` (already present) and nothing else.

**Depends on it:** change-to-test selection.

**Risk:** low. An unmapped router change would not select the startup test.
</impact>
<impact path="tests/last_test_validation.json" element="generated record of the last validation run">
**What changes:** none by hand. It lists test ids this build deletes or renames, for example `...bounds_text...[JSON duration unknown]` (line 5313) and `...[stored duration over --max-duration]` (line 5461). The next validation run rewrites it.

**Depends on it:** only `scripts/git_unset.sh` references it (grepped); no test reads it.

**Risk:** none. It is flagged so stale ids in it are not read as regressions.
</impact>
<impact path="tests/tmp/probe_53_draft_translate_worker.py" element="tests/tmp and tests/archive probes on the old resolve_video/stream_media/AudioPipe signatures">
**What changes:** none planned. `probe_53_*`, `probe_45_*`, `probe_56_backoff.py` and `tests/archive/translate_worker/test_translate_worker.py` will not run against the new signatures.

**Depends on it:** nothing in the active suite.

**Risk:** none. Their failure is not a regression.
</impact>
<impact path="docs/project/plans/56-translate-viewer-lease-uncapped.md" element="the settled design document">
**What changes:** none. It still says `DELETE /api/translate`, which the operator replaced with `POST /api/translate/cancel` on 2026-10-09.

**Depends on it:** nothing at runtime.

**Risk:** a reader may take the DELETE route as current. Archive the plan with the build.
</impact>
<impact path="engine/server/db/jobs/docs/TRANSLATE_WORKER.md" element="Job Lifecycle (33, 39), Enqueue (47, 49, 58, 60), Run flags (78), Serve Loop (85), Job Pipeline (95, 97, 100), Bounds (106-107), Error Texts (140-143), Stop (150), Takeover (155), Logs (165-)">
**What changes:**
- Lifecycle:
  - Line 33 adds `wanted_at` to the queued row's columns.
  - Line 39's "Every job ends in exactly one of…" gains the abandoned path.
- Enqueue: the caps and flags go from lines 47, 49 and 58. Line 60 says the page route stamps a lease, and that CLI jobs carry none.
- Run flags: line 78 keeps only `--max-chunk-seconds`.
- Serve loop: line 85's "runs it to its end" becomes "until it ends or is abandoned", and it notes the claim's drop of expired queued rows.
- Job pipeline:
  - Line 95 deletes "Check its duration".
  - Line 97 states the lookahead bound and the backpressure.
  - Line 100 notes that the socket is not read while the lookahead is full (R2).
- Bounds (lines 106-107): the two cap rows go; Lookahead and Viewer lease rows are added.
- Error Texts (lines 140-143): four texts go.
- Stop (line 150): stop also wakes a parked reader.
- Takeover (line 155): the six methods gain `read_lease` and `abandon`.
- Logs: add `abandoned, no viewer`.
- New section: Viewer Lease and Cancel.

**Depends on it:** operators.

**Risk:** doc drift.
</impact>
<impact path="engine/server/README.md" element="lines 3, 20, 24, 28-31, 35, 39, 41, 52">
**What changes:**
- Line 3 lists the cancel route among the subtitles.db writers.
- Line 24 (Cache):
  - add `wanted_at` to the job columns;
  - change "The route stores only ready" to "stores only ready, and renews a leased queued/running row's `wanted_at`".
- Line 28: enqueue stamps `wanted_at`.
- Line 31's **Duration** bullet ("the worker checks the duration when it claims the job") is deleted. This pass found it; earlier passes missed it.
- A new cancel route bullet.
- Line 35 drops the two caps and adds the lease and grace constants.
- Line 39's six methods gain `read_lease` and `abandon`.
- Line 41's end states gain the abandoned row deletion. This pass found it.
- Add `renew_translate_lease`, `cancel_translate_lease` and the claim drop.
- Line 52's migration note names `wanted_at`.

**Depends on it:** readers.

**Risk:** doc drift.
</impact>
<impact path="client/README.md" element="lines 28, 37-38, 40, 45, 51, 58-59">
**What changes:**
- Line 28's 401 list names the cancel.
- A new `POST /api/translate/cancel` bullet after line 38.
- Line 40's failure text applies to it.
- Line 45's bridge-call list gains the translate cancel.
- Lines 51 and 58-59: the route lists gain both cancel paths.

**Depends on it:** readers.

**Risk:** doc drift.
</impact>
<impact path="client/frontend/README.md" element="lines 8, 29, 30, 31">
**What changes:**
- Line 8: the gateway routes gain `POST /api/translate/cancel`.
- Line 29: a poll-path `none` with `available` re-requests with backoff.
- Line 30: turning off also sends one cancel after any request in flight.
- Line 31: a `none` while on, with a serving worker, shows "Waiting…" and re-requests.
- Lines 29-30 change further if recommendation 1 is taken.

**Depends on it:** readers.

**Risk:** doc drift.
</impact>
<impact path="CONTEXT.md" element="terms Translate state (17), Generation available (18), Source-instance fetch (20), Translate job (21), Claim (22); new Viewer lease">
**What changes:**
- A new **Viewer lease** term.
- Translate job (line 21): "ends in exactly one of" gains abandonment, which deletes the row and allows a new request. It also gains the CLI exception and the removal of the duration cap.
- Translate state: `none` also follows an abandoned job.
- Claim: it can end in a conditional abandon.
- Source-instance fetch: "caps the bytes it reads" no longer holds for media.
- Generation available (line 18) changes if recommendation 1 is taken.

**Depends on it:** the glossary that the other docs use.

**Risk:** doc drift.
</impact>
<impact path="DEPLOYMENT.md" element="lines 98, 236, 254-257 and an upgrade note, 270, 279-280, 290, 297, 353-360 triage, 586, 593">
**What changes:**
- **Line 98** (step 4 pass 2's new impact):
  - "Nothing prunes it" becomes false, because the worker now deletes abandoned and lapsed page jobs; tracks and finished jobs are still never pruned.
  - The writer sentence gains lease renewal on queued/running state reads and `/internal/translate/cancel`, with their failure modes: a renewal failure is a logged warning and leaves the answer unchanged; a cancel store error is a 503, reaching the page as a 502 that it swallows.
- Line 236 drops the `--max-duration` sentence, adds the lease and cancel, and changes "runs no state poll" if recommendation 1 is taken.
- An upgrade note:
  - remove `--max-duration`/`--max-bytes` from any customised `ExecStart` first, or the unit exits 2 and restart-loops;
  - then run `sudo systemctl restart peertube-translate-worker` after the pull, because `deploy-bluegreen.sh` never restarts the worker;
  - the Client and the frontend build ship together for cancel.
- Line 270: the stop also wakes a reader parked on a full lookahead; a feeder blocked writing is released by the ffmpeg kill.
- Lines 279-280: delete both flag rows.
- Line 290: delete the `--max-duration` clause.
- Line 297: drop `duration Ns over Ms`.
- Triage:
  - `abandoned, no viewer`;
  - row 355 "Jobs stay queued": expired page jobs are dropped at claim (with the drop log line, if recommendation 2 is taken);
  - if recommendation 1 is declined: a worker restart over 15 s drops waiting viewers' jobs.
- Lines 586 and 593: the route lists gain cancel.

**Depends on it:** operators.

**Risk:** an operator unaware of the removed flags restart-loops the worker.
</impact>
<impact path="README.md" element="lines 53-54">
**What changes:** the gateway row and the internal-contract row gain the cancel routes.

**Depends on it:** readers.

**Risk:** doc drift.
</impact>
<impact path="DATA_BUILD.md" element="line 15">
**What changes:** the Engine also writes `subtitles.db` on queued/running state reads (renewal) and from `/internal/translate/cancel`. The worker also deletes lapsed and abandoned page jobs.

**Depends on it:** readers.

**Risk:** doc drift.
</impact>
<impact path="docs/project/roadmap.md" element="line 62 F11-M2 PARTIAL; DONE bullets 24-25">
**What changes:** the Delivered list gains the viewer lease, cancel and the cap removal, with the plan link. An optional DONE bullet goes beside lines 24-25.

**Depends on it:** project tracking.

**Risk:** none.
</impact>

## Documentation to update

- [x] `engine/server/db/jobs/docs/TRANSLATE_WORKER.md` - updated: I updated `TRANSLATE_WORKER.md`: the duration and media-size caps are removed, and the doc now covers the bounded lookahead with backpressure and the viewer lease, cancel and abandonment, including the command-line exception.
- [x] `engine/server/README.md` - updated: engine/server/README.md now describes the viewer lease (`wanted_at`), lease renewal on state reads, the `/internal/translate/cancel` route and the new store functions. The two removed caps are no longer mentioned.
- [x] `client/README.md` - updated: I documented the `POST /api/translate/cancel` gateway route in `client/README.md` and added it, plus the Engine's `/internal/translate/cancel`, to the 401 list, the bridge-call list and the boundary lists.
- [x] `client/frontend/README.md` - updated: I updated `client/frontend/README.md` so the video page covers both new Translate behaviours: it sends a cancel when Translate is turned off, and it requests the translation again when a poll reads `none` while generation is available. Every sentence was checked against `src/pages/video-page/translate.ts` and `src/data/translate.ts`.
- [x] `CONTEXT.md` - updated: I added a **Viewer lease** term to CONTEXT.md and updated Translate state, Translate job, Claim and Source-instance fetch to match.
- [x] `DEPLOYMENT.md` - updated: I updated DEPLOYMENT.md: the duration and media-size caps are gone from it, and it now covers the viewer lease, cancel, abandonment and the worker upgrade steps.
- [x] `README.md` - updated: Added the translate cancel route to both rows of the boundary contract table.
- [x] `DATA_BUILD.md` - updated: Updated the `subtitles.db` paragraph in DATA_BUILD.md (line 15) so its list of writers includes the viewer-lease writes.
- [x] `docs/project/roadmap.md` - updated: The roadmap now lists the viewer-lease translate work as delivered: a new DONE bullet, and an entry in F11-M2's PARTIAL Delivered list.

## Implementation plan

## Draft implementation: plan 56, translate viewer lease and uncapped length

### What I read and what the operator decided

I read every production file the inventory names: the worker, `subtitles.py`, `source_fetch.stream_media`, `internal_translate.py`, the router and `server_config` translate lines, `server.py` (import, `_serve_post`, `_handle_translate_post`), `engine_api_client.py`, both `translate.ts` files and the contract fixture. The draft below is written against those lines.

I asked the operator two questions during this step:
1. **Recommendation 1: taken.** Without `available`, the page keeps polling a `queued` or `running` job at `STATE_POLL_MAX_MS`. Those polls keep renewing the lease while the worker restarts. This reverses plan 50's "never polled" rule for those two states only.
2. **Lost abandon race: continue.** This is the settled design, and it replaces the plan text's requeue. `translate_audio` calls `job.abandon(expired_at)` itself at the wake where it saw an expired lease.
   - True means the row is gone, and it raises `JobAbandoned`. `run_job` only logs.
   - False means a renewal won. The chunk loop carries on with all its cues kept, and nothing is requeued.
   - `read_lease` is gated on the claim, so a row that the instance track took over reads None. The next claim-conditional write then raises `JobTakenOver`, as it does today.
   - This moves the `abandon` call from `run_job` into `translate_audio`. It is the only way to get literal continuation, because once an exception has unwound the loop the window state is gone.

**Recommendation 2 (log a line when the claim drops expired rows): declined.** Most queued-row drops are the cancel and lapse cases the operator expects. Ceiling: a dropped queued job leaves no journal line, so DEPLOYMENT.md triage row 355 points at the lease rule, not at a log. Upgrade path: a `rowcount` return from a split-out `drop_lapsed_translate_jobs`, logged in `serve`.

### Functionality the tests must cover

- **Worker, AC1 and AC2:** a JSON with no `duration`, a long JSON duration and a long stored duration all translate. `enqueue` with a 601 s stored duration queues. `--max-duration` and `--max-bytes` are gone, so argparse exits 2.
- **Worker, AC3:**
  - the logical buffer never exceeds `limit` samples;
  - the reader parks, and `release` resumes it;
  - a chunk longer than the lookahead does not deadlock;
  - `close` wakes a parked reader, and so does `_fail`;
  - a normal EOF still ends with `done`.
- **Worker, AC4 and AC7:**
  - an expired lease deletes the row, logs `abandoned, no viewer` once, and `rig.row() == {}`;
  - a renewal between the read and the delete keeps translating, and the job ends `ready` with all its cues;
  - an unleased (CLI) row is never abandoned, even with `now_ms` far ahead;
  - a store error from `read_lease` is a warning and the job continues.
- **Store:**
  - the claim drops expired leased queued rows and keeps unleased, fresh, running and ready rows;
  - `expired_at=None` drops nothing;
  - renew and cancel touch only leased queued and running rows;
  - cancel never lengthens a lease;
  - `abandon` matches only the claim with an expired lease and is False after a takeover;
  - `read_lease` is None for a CLI row and after a takeover;
  - the migration adds `wanted_at` in place (15 columns).
- **Engine:**
  - the state read renews a leased queued or running row and leaves ready, unleased and missing rows unwritten;
  - a renewal error keeps the answer;
  - the enqueue route stamps `wanted_at`;
  - cancel answers 400, 404, 503, a closed store as `{none,false}`, and the state after the update;
  - the router registers cancel behind the bridge token.
- **Client:**
  - cancel answers 429, then 401 before the body, then 400;
  - it makes one bridge call to `/internal/translate/cancel`;
  - `Video not found` maps to `{none,false}`;
  - a 503 or an old Engine's 404 answers 502.
- **Page:**
  - `turnOff` sends exactly one cancel, ordered after an in-flight poll;
  - a poll-path `none` with `available` re-requests;
  - a ready row whose cues do not load backs off and does not spin;
  - queued without `available` keeps polling.
- **Contract:** the `cancel` route cases replay through all three layers.

---

### 1. `engine/server/api/server_config.py`

Lines 421-424 (both caps and their comments) are deleted. In their place:

```python
# A page-queued translate job that no state read renewed for this long is dropped before it starts or abandoned mid-run (the viewer lease); above Chrome's one-minute timer clamp for hidden tabs.
TRANSLATE_LEASE_MS = 180_000
# A cancel caps the lease this far ahead; above the page's 16 s STATE_POLL_MAX_MS, so a co-viewer still polling renews it first.
TRANSLATE_CANCEL_GRACE_MS = 20_000
```

### 2. `engine/server/data/source_fetch.py`

- The module docstring's "a byte cap" is reworded: `fetch_bounded` caps the body, and `stream_media` is bounded by its socket timeout, `stop` and the consumer's backpressure.
- `stream_media` becomes:

```python
def stream_media(url: str, host: str, consume: Callable[[bytes], object], stop: threading.Event) -> None:
    """Download url through the same-host redirect policy bound to host (media_host's raw hostname), passing each chunk to consume until EOF or stop is set; SourceFetchFailed on a non-200 or a fetch error. No size cap and no wall-clock deadline: MEDIA_SOCKET_TIMEOUT_SECONDS is the only stall bound, and consume may block (the worker's backpressure). A BrokenPipeError from consume propagates unchanged."""
    try:
        with _open(Request(url), SameHostRedirectHandler(host), MEDIA_SOCKET_TIMEOUT_SECONDS) as resp:
            if resp.status != 200:
                raise SourceFetchFailed(f"media download failed: HTTP {resp.status}")
            while not stop.is_set():
                chunk = resp.read1(READ_CHUNK_BYTES)
                if not chunk:
                    break
                consume(chunk)
    except BrokenPipeError:
        raise
    except _FETCH_ERRORS as exc:
        raise SourceFetchFailed(f"media download failed: {exc}") from exc
```

`fetch_bounded`, `FETCH_MAX_BYTES` and `MEDIA_SOCKET_TIMEOUT_SECONDS` are untouched.

### 3. `engine/server/data/subtitles.py`

```python
JOB_COLUMNS = (... , ("attempts", "INTEGER NOT NULL DEFAULT 0"), ("wanted_at", "INTEGER"))
# A viewer lease: a page-queued job still queued or running; NULL wanted_at (command-line jobs, rows from before the column) is never leased.
_LEASED = "state IN ('queued', 'running') AND wanted_at IS NOT NULL"
```

- **Migration:** the existing loop adds the column. There is no new index, because the claim's DELETE filters `state='queued'`, which `subtitles_state_queued_at` covers.
- **`enqueue_translate_job(conn, video_id, instance_domain, target_language, cap, queued_at, *, wanted_at: int | None = None)`.**
  - The INSERT gains `wanted_at` among its columns and values.
  - Docstring: "wanted_at is the viewer lease (the Engine route's enqueue time; None from the CLI). `exists` neither renews nor overwrites."
- **`renew_translate_lease(conn, video_id, instance_domain, target_language, now: int) -> None`.**
  - Docstring: "Renew a leased queued or running row's viewer lease to now; any other row is untouched."
  - Body: `with conn: conn.execute(f"UPDATE subtitles SET wanted_at = ? WHERE {_KEY} AND {_LEASED}", (now, video_id, instance_domain, target_language))`
- **`cancel_translate_lease(conn, video_id, instance_domain, target_language, capped_at: int) -> None`.**
  - Docstring: "Shorten a leased queued or running row's lease to at most capped_at, never lengthening it."
  - Body: `SET wanted_at = MIN(wanted_at, ?)` with the same WHERE as renewal.
- **`TranslateJob`.** The class docstring becomes: "Every write is one conditional statement (an UPDATE, or abandon's DELETE) that matches only while the row is running with this started_at…". New methods:

```python
    def read_lease(self) -> int | None:
        """The running row's viewer lease (wanted_at); None for an unleased command-line job or once the claim is lost."""
        row = self.conn.execute(f"SELECT wanted_at FROM subtitles WHERE {_KEY} AND state = 'running' AND started_at = ?", (self.video_id, self.instance_domain, self.target_language, self.started_at)).fetchone()
        return row[0] if row is not None else None

    def abandon(self, expired_at: int) -> bool:
        """Delete the running row, partial cues with it, while its lease is still at or before expired_at (AC4); False when a renewal landed first or the claim was lost."""
        with self.conn:
            cursor = self.conn.execute(f"DELETE FROM subtitles WHERE {_KEY} AND state = 'running' AND started_at = ? AND wanted_at IS NOT NULL AND wanted_at <= ?", (self.video_id, self.instance_domain, self.target_language, self.started_at, expired_at))
        return cursor.rowcount == 1
```

- **`claim_translate_job(conn, target_language, started_at, *, expired_at: int | None = None)`.**
  - Inside the existing `_immediate` block, before the SELECT: `if expired_at is not None: conn.execute("DELETE FROM subtitles WHERE state = 'queued' AND target_language = ? AND wanted_at IS NOT NULL AND wanted_at <= ?", (target_language, expired_at))`.
  - Docstring: "…first dropping queued page jobs whose lease lapsed at expired_at."
  - Every positional caller stays valid.
- **Unchanged:** `_recover_translate_jobs`, `requeue` and `store_ready_subtitles`. They keep `wanted_at`. A stale `wanted_at` on a ready instance row is inert, because every lease statement is gated on `state` or on the claim.
- **Docs in the file:** the module docstring (line 3) and the busy-timeout comment (line 15) name the lease column, renew, cancel, the claim drop, `read_lease` and `abandon`, and the Engine and worker writes they add.

### 4. `engine/server/db/jobs/translate-worker.py`

- **Imports and comments:**
  - Line 41: `from server_config import DEFAULT_DB_PATH, DEFAULT_SUBTITLES_DB_PATH, HEARTBEAT_SECONDS, SUBTITLE_MAX_CHUNK_SECONDS, SUBTITLE_QUEUE_CAP, TRANSLATE_LEASE_MS, VIDEO_ERROR_THRESHOLD`.
  - The line-35 comment names: the chunk and queue bounds, `HEARTBEAT_SECONDS`, `TRANSLATE_LEASE_MS` and the paths.
  - Docstring line 6 adds: "each chunk-loop wake reads the job's viewer lease, and a lapsed one is abandoned by deleting the row."
- **New constant and exception:**

```python
# Decoded audio held past the translation position; the reader stops pulling from ffmpeg beyond it plus one window, so the buffer is about 19 MB whatever the video's length (AC3).
LOOKAHEAD_SECONDS = 600

class JobAbandoned(Exception):
    """The viewer lease lapsed and TranslateJob.abandon deleted the row; nothing more is written."""
```

- **`resolve_video(whitelist_path, video_id, host)`.**
  - Lines 103-105 are deleted, so it returns `row, None`.
  - Docstring: "…resolve_translatable_video with VIDEO_ERROR_THRESHOLD (a missing host reads as not in whitelist)."
- **`command_enqueue`:** calls `resolve_video(args.whitelist_db, video_id, host)`. The `enqueue_translate_job` call is unchanged and passes no `wanted_at` (AC7).
- **`video_duration`:** deleted. `math` stays, because `pick_media_url` and `chunk_cues` use it.
- **`AudioPipe`.** Class docstring: "…each on its own thread; the reader holds at most LOOKAHEAD_SECONDS plus one window past the translation position and stops pulling beyond it, so ffmpeg and the download wait for the GPU; nothing touches disk."

```python
    def __init__(self, url: str, host: str, max_chunk: int) -> None:
        """Start ffmpeg and the feeder, stdout reader and stderr drain threads for one media URL, its raw host and the window length in samples."""
        self.url = url
        self.host = host
        # Bounded: at most limit samples are buffered, released as each window is translated (AC3).
        self.limit = LOOKAHEAD_SECONDS * SAMPLE_RATE + max_chunk
        # The absolute sample index of pcm[0].
        self.base = 0
        self.pcm = bytearray()
        ... (unchanged; threads start last)

    def _feed(self) -> None:
        """Stream the media download into ffmpeg's stdin through stream_media (same-host redirects, the socket timeout, its failure texts); a write blocks while ffmpeg's stdin is full; stdin is closed on every path."""
            stream_media(self.url, self.host, self.proc.stdin.write, self.stop)

    def _read(self) -> None:
        """Drain stdout into pcm, never past limit samples: while full it waits for release, stop or an error, so ffmpeg and the feeder block; then reap ffmpeg and report a non-zero exit with its stderr tail."""
        while True:
            with self.cond:
                self.cond.wait_for(lambda: self.stop.is_set() or self.error is not None or len(self.pcm) < self.limit * BYTES_PER_SAMPLE)
                room = self.limit * BYTES_PER_SAMPLE - len(self.pcm)
            if self.stop.is_set() or self.error is not None:
                break
            # Clamped to the room in bytes, so the buffer never exceeds limit, not even by one read.
            data = self.proc.stdout.read1(min(READ_CHUNK_BYTES, room))
            if not data:
                break
            with self.cond:
                self.pcm += data
                self.cond.notify_all()
        code = self.proc.wait()
        ... (unchanged)
```

- **Why `_read` cannot hang:**
  - The condition is never held across `read1`.
  - Only `release` shrinks `pcm`, so the room computed under the lock can only grow before the append.
  - On an early break, `proc.wait()` returns because both `close` and `_fail` kill ffmpeg. `threads[2].join()` then sees stderr EOF.
  - `_fail` is unchanged: it sets `error` under the lock and notifies, and the predicate includes `error`.

```python
    def wait_samples(self, end: int) -> tuple[int, bool]:
        """Block up to POLL_SECONDS for absolute sample end, an error or the end of the audio; the absolute samples buffered and whether the audio has ended."""
        with self.cond:
            self.cond.wait_for(lambda: self.done or self.error is not None or self.base + len(self.pcm) // BYTES_PER_SAMPLE >= end, timeout=POLL_SECONDS)
            return self.base + len(self.pcm) // BYTES_PER_SAMPLE, self.done

    def slice(self, start: int, end: int) -> bytes:
        """A copy of absolute samples [start, end); start is never before a released sample."""
        with self.cond:
            assert start >= self.base
            return bytes(self.pcm[(start - self.base) * BYTES_PER_SAMPLE:(end - self.base) * BYTES_PER_SAMPLE])

    def release(self, upto: int) -> None:
        """Drop the samples before absolute index upto, already translated, and wake a reader waiting for room."""
        with self.cond:
            del self.pcm[:(upto - self.base) * BYTES_PER_SAMPLE]
            self.base = upto
            self.cond.notify_all()

    def close(self) -> None:
        """Stop the feeder, wake a reader waiting for room, kill ffmpeg if it still runs and join the threads; a feeder blocked writing ends at the kill, else within one socket timeout."""
        self.stop.set()
        with self.cond:
            self.cond.notify_all()
        self.proc.kill()
        ... (unchanged)
```

- **Liveness at the tail.** `limit >= max_chunk`, and the buffer starts at `pos` after each `release(pos)`. So `wait_samples(pos + max_chunk)` either fills or sees `done`, whatever `--max-chunk-seconds` is.
- **Lease check:**

```python
def lease_lapsed(job: TranslateJob) -> bool:
    """Whether job's viewer lease lapsed and abandon deleted its row; an unleased job, a lost claim, a renewal that won the race or a store error reads as not lapsed, and the job continues."""
    expired_at = now_ms() - TRANSLATE_LEASE_MS
    try:
        lease = job.read_lease()
        return lease is not None and lease <= expired_at and job.abandon(expired_at)
    except sqlite3.Error as exc:
        logging.warning("[translate-worker] lease check failed video_id=%s host=%s: %s", job.video_id, job.instance_domain, exc)
        return False
```

- **`translate_audio`:**
  - Right after `if stop.is_set(): raise JobStopped()`, add `if lease_lapsed(job): raise JobAbandoned()`.
  - Right after `pos += cut`, add `pipe.release(pos)`.
  - The check runs at every wake: every 2 s while waiting, and once per chunk while busy. The first wake after a model load or a long Whisper call catches a lapse. No throttle is needed, because one primary-key read per chunk is cheaper than the cue rewrite.
- **`generate`:**
  - It calls `resolve_video(args.whitelist_db, job.video_id, job.instance_domain)`.
  - Lines 412-416 are deleted.
  - It builds `pipe = AudioPipe(url, media_host(url), args.max_chunk_seconds * SAMPLE_RATE)`, so `translate_audio` keeps receiving the same `max_chunk`.
- **`run_job`:**
  - A new branch, `except JobAbandoned: logging.info("[translate-worker] abandoned, no viewer video_id=%s host=%s", *where)`, sits after `JobTakenOver` and before `JobFailed`/`Exception`. It returns False.
  - Docstring: "Take one claimed job to exactly one end state, or back to queued…, or abandon it (row deleted) when its viewer lease lapsed…"
- **`serve`:** `now = now_ms()`, then `job = claim_translate_job(conn, TARGET_LANGUAGE, now, expired_at=now - TRANSLATE_LEASE_MS)`.
- **`parse_args`:** the three flag lines (561, 565, 566) are deleted. `_positive_int` stays.

### 5. `engine/server/api/handlers/internal_translate.py`

- **Imports:**
  - Line 23 adds `cancel_translate_lease` and `renew_translate_lease`.
  - Line 27 becomes `from server_config import HEARTBEAT_FRESH_MS, SUBTITLE_QUEUE_CAP, TRANSLATE_CANCEL_GRACE_MS, TRANSLATE_LEASE_MS`.
- **`_read_key`:**

```python
            stored = fetch_subtitle_state(conn, video_id, instance_domain, TARGET_LANGUAGE)
            if stored is not None and stored[0] in ("queued", "running"):
                # Same lock hold: a viewer still reading a queued or running job renews its lease (AC4); a failed renewal is logged and the answer stands.
                try:
                    renew_translate_lease(conn, video_id, instance_domain, TARGET_LANGUAGE, now_ms())
                except sqlite3.Error as exc:
                    logging.warning("[translate] lease renewal failed video_id=%s host=%s: %s", video_id, instance_domain, exc)
            return stored, _generation_available(conn)
```

  - Docstring: "…and renews a leased queued or running row's lease in the same hold…".
- **`handle_internal_translate_enqueue`:** passes `wanted_at=now_ms()`. Its docstring notes the lease. It still never renews an existing row.
- **New handler:**

```python
def handle_internal_translate_cancel(handler: Any, server: Any) -> bool:
    """Shorten a video's viewer lease to TRANSLATE_CANCEL_GRACE_MS (leased queued or running rows only, never lengthened) and answer the key's state after it with available, no cues; a closed store answers none, not available."""
    resolved = _resolve_translate_key(handler, server)
    if resolved is None:
        return True
    _, canonical_id, instance, _ = resolved
    try:
        with _subtitles_store(server) as conn:
            if conn is None:
                stored, available = None, False
            else:
                cancel_translate_lease(conn, canonical_id, instance, TARGET_LANGUAGE, now_ms() - TRANSLATE_LEASE_MS + TRANSLATE_CANCEL_GRACE_MS)
                stored, available = fetch_subtitle_state(conn, canonical_id, instance, TARGET_LANGUAGE), _generation_available(conn)
    except sqlite3.Error as exc:
        logging.warning("[translate] cancel failed video_id=%s host=%s: %s", canonical_id, instance, exc)
        respond_json(handler, 503, {"error": "Translate store unavailable"})
        return True
    respond_json(handler, 200, {"state": stored[0] if stored is not None else "none", "available": available})
    return True
```

- **Docs in the file:**
  - The module docstring gains a cancel paragraph and renewal on the state route.
  - "This route stores only ready" becomes "stores only ready, and renews a leased queued or running row's wanted_at".
  - The enqueue paragraph names the lease.
  - The `_resolve_translate_key` and `resolve_translatable_video` docstrings say "all three" routes.
- **`router.py`:**
  - The import adds `handle_internal_translate_cancel`.
  - `POST_ROUTES` adds `"/internal/translate/cancel": handle_internal_translate_cancel,`.
  - The docstring gains `- POST /internal/translate/cancel: internal Client request to shorten a video's translate viewer lease to the cancel grace. [bridge gate]`.
  - `handlers/__init__.py` line 8 names the cancel.

### 6. Client gateway

- **`engine_api_client.py`:** a mirror of `request_translate`. I chose a mirror over a shared helper, because the two differ in path, state set and error label, and a helper would cost about as many lines.

```python
def cancel_translate(engine_base_url: str, video_id: str, host: str) -> dict[str, Any]:
    """Ask the Engine to shorten a video's translate viewer lease to its cancel grace: {state, available} with state one of TRANSLATE_STATES and no cues; anything else raises EngineApiError."""
    status, body = _post_json(f"{engine_base_url.rstrip('/')}/internal/translate/cancel", {"id": video_id, "host": host})
    if status == 404 and body.get("error") == TRANSLATE_NOT_FOUND_ERROR:
        return {"state": "none", "available": False}
    if status != 200:
        raise EngineApiError(f"Engine translate cancel failed (HTTP {status}): {body.get('error') or 'unknown error'}")
    state = body.get("state")
    if state not in TRANSLATE_STATES:
        raise EngineApiError("Engine translate cancel returned invalid payload")
    return {"state": state, "available": _translate_available(body)}
```

  The line-22 comment becomes: "busy is the enqueue route's full-queue answer and is never stored; cancel answers TRANSLATE_STATES."
- **`server.py`** (rung 2: reuse the existing handler rather than copy it):
  - The import adds `cancel_translate`, in alphabetical order.
  - `_handle_translate_post` becomes `_handle_translate_post(self, engine_call: Callable[[str, str, str], dict[str, Any]])`. Its body is unchanged except that it calls `engine_call(self.server.engine_ingest_base, video_id.strip(), host.strip())`.
  - Its docstring: "Ask the Engine to queue a whisper job (request_translate) or shorten a video's viewer lease (cancel_translate) for one video, for the presented profile only; the body is read after the profile check."
  - `_serve_post`'s `/api/translate` branch calls `self._handle_translate_post(request_translate)`. The new branch goes before the 404:

```python
        if url.path == "/api/translate/cancel":
            if not self._rate_limit_check(url.path):
                respond_json(self, 429, {"error": "Rate limit exceeded"})
                return
            self._handle_translate_post(cancel_translate)
            return
```

  - The module globals are looked up at each request, so a test that monkeypatches `server.request_translate` still takes effect.
  - The rate limiter keys by `ip:path`, so the new path gets its own bucket.
  - Failures go through `_respond_engine_failure("translate", …)`, which answers 502 `Engine translate failed`.

### 7. Page data layer: `client/frontend/src/data/translate.ts`

```ts
// The cancel route's answer: a stored state or none, never busy, and no cues.
export type TranslateCancelState = { state: TranslateState["state"]; available: boolean };
const CANCEL_STATES = ["none", "queued", "running", "ready", "already_english", "failed"];

export async function requestTranslate(apiBase, id, host): Promise<TranslateRequestState> {
  return (await postTranslate(apiBase, "/api/translate", REQUEST_STATES)) as TranslateRequestState;
}

/**
 * Ask the Client gateway to shorten this video's viewer lease to the cancel grace; a 401 throws ProfileKeyRejectedError, a malformed body throws.
 */
export async function cancelTranslate(apiBase: string, id: string, host: string): Promise<TranslateCancelState> {
  return (await postTranslate(apiBase, "/api/translate/cancel", CANCEL_STATES, id, host)) as TranslateCancelState;
}

async function postTranslate(apiBase: string, path: string, states: string[], id: string, host: string): Promise<{ state: string; available: boolean }> {
  // the current requestTranslate body with path and states as parameters
}
```

`requestTranslate` passes `id` and `host` through. The module comment names the cancel request.

### 8. Page: `client/frontend/src/pages/video-page/translate.ts`

```ts
// The one in-flight state read or generation request; turnOff sends its cancel after it settles, so a poll already sent cannot renew the lease after the cancel.
let inFlight: Promise<unknown> = Promise.resolve();

function track<T>(request: Promise<T>): Promise<T> {
  inFlight = request.catch(() => undefined);
  return request;
}
```

- **Request sites that register:** `turnOn`'s `fetchTranslate` and `requestTranslate` (`await track(...)`), `scheduleStatePoll`'s `fetchTranslate`, and the new re-request.
- **Click listener:** `if (on) turnOff(apiBase, video);`.
- **`turnOff(apiBase, video)`:** the existing resets, then `inFlight.then(() => cancelTranslate(apiBase, video.id, video.host)).catch(() => undefined);`. It is never awaited, and a failure or `MALFORMED` is swallowed.
- **`applyRequest(requested, apiBase, video, ticket, delay = 0)`:** the ready/running branch schedules at `delay`.
- **`applyState` else branch, before the ended states:**

```ts
  } else if (state.state === "none" && state.available) {
    // Abandoned (no viewer polled within the lease) or never stored while Translate is on: ask again, as turnOn does; the follow-up poll backs off, so a ready row whose cues do not load cannot spin.
    dropRunning();
    setStatus(WAITING);
    stateDelay = changed ? STATE_POLL_FIRST_MS : Math.min(stateDelay * 2, STATE_POLL_MAX_MS);
    requestAgain(apiBase, video, ticket, stateDelay);
    return;
  } else {
```

- **`requestAgain(apiBase, video, ticket, delay)`:** `track(requestTranslate(...)).then(r => { if (ticket === requestTicket) applyRequest(r, apiBase, video, ticket, delay); }, error => { if (ticket === requestTicket) setStatus(error instanceof Error ? error.message : "Could not load the translation"); })`.
- **Why this cannot recurse:** a `none` with `available` reaches `applyState` only from the poll path. `turnOn` handles its own, and enqueue answers `none` only without `available`.
- **The spin guard works:** a broken ready row answers `ready` to the request, and `applyRequest`'s ready path does not touch `lastState`. The next poll's `none` is therefore unchanged, and the delay doubles to 16 s.
- **Lines 199-202 (recommendation 1):**

```ts
  // A queued or running job is polled even without a serving worker, at the slowest rate, so its viewer lease keeps renewing across a worker restart.
  stateDelay = !state.available ? STATE_POLL_MAX_MS : changed ? STATE_POLL_FIRST_MS : Math.min(stateDelay * 2, STATE_POLL_MAX_MS);
  scheduleStatePoll(apiBase, video, ticket, stateDelay);
```

- **Module comment line 6:** `none` without `available`, `failed` and `already_english` end the poll. A poll-path `none` with `available` re-requests with backoff. A queued or running job is polled with or without `available`. `turnOff` sends one cancel after any request in flight.

### 9. Contract fixture

- The description names the third route: cancel (`POST /internal/translate/cancel`), answering `{state, available}` with no cues.
- New cases:
  - `cancel <state>` and `cancel <state> without available` for none, queued, running, ready, already_english and failed (no cues);
  - `cancel video not found` 404 → `{none,false}`;
  - `cancel route missing 404` → rejected;
  - `cancel busy` → rejected;
  - `cancel unknown state` → rejected;
  - `cancel available a string` → rejected.
- The replayers learn the route:
  - `test_engine_api_client.py`: `ROUTES`, dispatch to `cancel_translate`, the loop `("cancel", TRANSLATE_STATES)`, and the docstring;
  - `test_frontend_translate.py` `CONTRACT_RUNNER`: import and dispatch `cancelTranslate`, and `_result`'s path is `/api/translate/cancel`;
  - `test_internal_translate.py`: cancel drivers in `ENGINE_DRIVERS` and `ROUTE_STATES`, `HANDLERS["cancel"] = "handle_internal_translate_cancel"`, and the exact-set check.

### 10. Test churn, per the inventory

- **`test_translate_worker.py`:**
  - `_recording` takes three arguments.
  - The `BOUNDS` cap cases are deleted, and a "no duration translates" case is added.
  - The fetch-reasons duration case is deleted.
  - `REFUSALS`/`CONTROL_KEYS` for the stored duration become a queued case.
  - The line-215 comment and the docstring are updated.
  - `Rig.claim(..., wanted_at=None)` forwards the lease.
  - The new `AudioPipe` tests monkeypatch `worker.stream_media` to a no-op, `worker.FFMPEG_ARGS` to a Python script writing N zero bytes, and `worker.LOOKAHEAD_SECONDS = 1`.
  - The lease tests monkeypatch `worker.now_ms`.
- **`test_subtitles.py`:** `JOB_COLUMN_NAMES` gains `wanted_at` (15 columns, six nullable job columns), and the store tests listed above are added.
- **`test_internal_translate.py`:** `QUEUED_ROW` gains `NOW`, plus the renewal, cancel and startup tests. `tests/config.json` maps `engine/server/api/router.py` to this test file.
- **`test_source_fetch.py`:** `MEDIA_SIZE` is dropped from every call, and the three cap tests are replaced by "a huge declared Content-Length streams whole".
- **`test_server.py`:** the cancel gateway tests, through `_routed_translate_engine`.
- **`test_frontend_translate.py`:**
  - the generation stub answers `POST /api/translate/cancel` from its own key (500 when unconfigured) and gains a per-answer delay;
  - `_asked` includes the cancel path;
  - `"available"` gets `[none, queued]`, and `"stop-none"` uses `available=False`;
  - new scenarios: AC6 re-request, ready-row backoff, cancel on `turnOff`, cancel ordered after an in-flight poll, queued without `available` keeps polling;
  - the first runner's click test asserts one cancel.

### 11. Docs

These are applied exactly as the settled documentation list gives them: `TRANSLATE_WORKER.md`, `engine/server/README.md`, `client/README.md`, `client/frontend/README.md`, `CONTEXT.md`, `DEPLOYMENT.md`, `README.md`, `DATA_BUILD.md` and `roadmap.md`. The two decisions resolve its conditional items as follows:
- Recommendation 1 is taken. CONTEXT.md:18, frontend README 29-30 and DEPLOYMENT.md:236 say that a queued or running job is still polled at 16 s without `available`. The triage row "a worker restart drops waiting viewers' jobs" is therefore not added.
- On the abandon race, `TRANSLATE_WORKER.md`'s Viewer Lease section says "a renewal racing the delete wins and the job continues with its cues".
- Recommendation 2 is declined, so no claim-drop log line appears in the Logs or triage sections.

### Check against the plan and requirements (pass 1; it converged)

- **AC1:** both `--max-duration` flags, `SUBTITLE_MAX_DURATION`, the stored check, `video_duration`, `video duration unknown`, the JSON check and `max_samples` are gone. A JSON with no duration reaches `pick_media_url`. ✓
- **AC2:** `SUBTITLE_MAX_BYTES`, `--max-bytes`, `max_bytes` and both checks are gone, and so is `media over N bytes`. `fetch_bounded` and `pick_media_url` are untouched. ✓
- **AC3:** the bound is exact (`limit` samples, read clamped in bytes), released samples are dropped, the reader parks and backpressure reaches ffmpeg and the socket, and `limit` includes the window. ✓
- **AC4:**
  - the enqueue route stamps the lease, and the state route renews only leased queued and running rows in the same lock hold, with an error logged;
  - every wake checks the lease;
  - the claim drops expired queued rows inside its IMMEDIATE block;
  - the abandon DELETE is conditional on the claim and on expiry.
  
  ✓ (operator-confirmed relocation of the `abandon` call so that a lost race continues)
- **AC5:** the page cancels on off, the cancel uses `MIN` with the state and NOT NULL gates (never lengthening), and the job stops within the grace plus one chunk. ✓
- **AC6:** no row is left, so a later enqueue inserts afresh, and a poll-path `none` with `available` re-requests. ✓
- **AC7:** the CLI writes NULL, and every lease statement requires NOT NULL. ✓
- **Consistency:** every new write is one conditional statement or inside `_immediate`, and worker writes to a running row go through claim-conditional `TranslateJob` methods. The Engine route reuses `_resolve_translate_key`, the Client checks the profile first, and the fixture covers all three layers. ✓

### Named simplifications, refinements and remaining limits

- **Refinements of the settled design:**
  - The cancel is ordered after the in-flight request.
  - A poll-path re-request follows up with the backoff delay.
  - `read_lease` is gated on the claim (not a bare primary-key read), so a takeover reads None and never detours through abandon.
- **The off-then-on race:** an old cancel can land after a new enqueue. It shortens a fresh lease to 20 s, and the next poll renews it.
- **Unchanged from the plan:**
  - expired queued rows hold queue-cap slots until the next claim;
  - enqueue does not renew;
  - the bytearray front deletion can briefly double the copy at reallocation (the logical bound holds);
  - R2 send timeouts;
  - one viewer's cancel affects co-viewers;
  - the running-cue rewrite is O(cues), with append-only storage as its upgrade path;
  - an abandoned job loses its work.
- **Operational:** `dist/` is not rebuilt here, and the worker needs a manual restart after removing any customised `--max-duration`/`--max-bytes` from `ExecStart`. The DEPLOYMENT.md upgrade note covers both.


### Phases

#### Phase 1 - Uncapped length, bounded buffer [code]

**Files touched.** engine/server/db/jobs/translate-worker.py (EDITED), engine/server/data/source_fetch.py (EDITED), engine/server/api/server_config.py (EDITED), tests/active/test_translate_worker.py (EDITED), tests/active/test_source_fetch.py (EDITED)

**Checkpoint.** Seam: the worker's `run_job` and `AudioPipe`, entered in-process through the existing `Rig` harness in tests/active/test_translate_worker.py. That harness uses ScriptedHost instance and media hosts behind the patched `data.source_fetch.build_opener`, a StubRunner, and a tmp subtitles.db and whitelist.db.

C1: two runs with `Rig.run` (the Namespace no longer carries max_duration or max_bytes). In the first, the video JSON has no `duration`; in the second it has one far above the old 600 s cap. Each must end with `rig.row()["state"] == "ready"` and the clip's cues. That rules out a worker that still fails on `video duration unknown` or on a long duration. A third run, with a long stored duration in whitelist.db, also ends ready, which rules out a surviving stored-duration branch.

C2: build `AudioPipe(url, host, max_chunk)` with three monkeypatches: `worker.stream_media` becomes a no-op, `worker.FFMPEG_ARGS` becomes a Python script that writes more zero bytes than `limit * BYTES_PER_SAMPLE`, and `worker.LOOKAHEAD_SECONDS` is set to 1. Assert all of the following:
- The logical buffer, sampled as `len(pipe.pcm)` under `pipe.cond` until the reader has stalled, never exceeds `pipe.limit * BYTES_PER_SAMPLE`. This rules out an unclamped read that overshoots by one chunk.
- With no release, `pipe.done` stays False and the buffer stays at the limit. This proves the reader parked rather than finishing.
- After `pipe.release(n)`, the absolute count `wait_samples` reports grows past its value before the release. This proves the reader resumed.
- Driving release until the end leaves `done` True. This proves a normal EOF still completes.

**Intent.** The translate worker (engine/server/db/jobs/translate-worker.py, with stream_media in engine/server/data/source_fetch.py) translates a video of any duration or size, and its AudioPipe holds no more than `limit` samples of decoded audio while it does.

- C1 - A video whose JSON has no duration, or a duration above the old cap, translates to ready.
- C2 - AudioPipe's buffer never exceeds limit samples, and its reader parks until release frees room.

**Outcome.** ### engine/server/db/jobs/translate-worker.py
- The `server_config` import no longer takes `SUBTITLE_MAX_BYTES` or `SUBTITLE_MAX_DURATION`.
- New constant `LOOKAHEAD_SECONDS = 600`: how much decoded audio the reader holds past the translation position.
- `resolve_video(whitelist_path, video_id, host)` no longer takes `max_duration` and no longer checks the stored duration. It still maps `missing host` to `not in whitelist`. `command_enqueue` and `generate` call it with three arguments.
- `video_duration` is deleted. In `generate`, the `video duration unknown` failure and the JSON duration check are gone, so a video with any duration, or none, goes on to `pick_media_url`. `generate` builds `AudioPipe(url, media_host(url), max_chunk)` and passes the same `max_chunk` to `translate_audio`.
- `AudioPipe(url, host, max_chunk)`:
  - `max_bytes` and `max_samples` are gone. Two new fields, `limit = LOOKAHEAD_SECONDS * SAMPLE_RATE + max_chunk` and `base` (the absolute sample index of `pcm[0]`), are set before the threads start. The old "all PCM in RAM" rat-tail comment is replaced.
  - `_read` waits on `cond` until there is room, `stop` is set or an error is recorded. Each read is `read1(min(READ_CHUNK_BYTES, room))`, so the buffer never goes past `limit` samples. On stop or an error it breaks out and still reaps ffmpeg and sets `done`. The `audio longer than Ns` abort is gone.
  - `wait_samples` waits for and returns absolute sample counts (`base + len(pcm)//2`).
  - `slice` takes absolute indices and asserts `start >= base`.
  - New `release(upto)` drops the samples before `upto`, moves `base` forward and wakes the reader.
  - `close` wakes a parked reader under `cond` before killing ffmpeg.
  - `_feed` calls `stream_media(url, host, consume, stop)`.
- `translate_audio` calls `pipe.release(pos)` right after `pos += cut`.
- `parse_args` no longer has `enqueue --max-duration`, `run --max-duration` or `run --max-bytes`.

### engine/server/data/source_fetch.py
- `stream_media(url, host, consume, stop)` no longer takes `max_bytes`. The Content-Length check, the streamed-size check and the `media over N bytes` text are gone, and its docstring says the download is uncapped.
- The module docstring now says the byte cap applies to `fetch_bounded` only. `fetch_bounded` and `FETCH_MAX_BYTES` are untouched.

### engine/server/api/server_config.py
- `SUBTITLE_MAX_DURATION` and `SUBTITLE_MAX_BYTES` are removed, with their comments.

### tests/active/test_translate_worker.py
Three kinds of change: tests that conflict with AC1/AC2 are retired, call sites follow the new signatures, and the docstring is brought in line.

**Retired:**
- From `BOUNDS`: `JSON duration unknown`, `JSON duration over the cap`, `media Content-Length over max_bytes`, `media streamed past max_bytes` and `decoded audio past max_duration`.
- From `FETCH_REASONS`: `video JSON served, duration over the cap`.
- From the enqueue `REFUSALS` and `CONTROL_KEYS`: `stored duration over --max-duration`, along with the `l-1` and `m-1` rows that only it used.

**Follow-on edits:**
- The bounds test no longer computes `max_bytes`, overrides `max_duration` or checks `unread`.
- The unused `"streamed"` branch of `Rig.serve_media` is removed.
- `_recording`'s stand-in takes and forwards three arguments.
- The `Rig.run`, `_serving` and fetch-reasons `Namespace`s carry only `whitelist_db` and `max_chunk_seconds`.
- The mov test no longer overrides `max_bytes`.
- `MAX_DURATION` is renamed `JSON_DURATION` (only `_video` uses it).
- The `REFUSED_STALL_SECONDS` comment now says the flag it was probed on is removed.
- The module docstring no longer describes the cap cases.
- The names the checkpoint imports (`rig`, `clip`, `StubRunner`, `ScriptedHost`, `_dispatching_opener`, `_worker`, `MEDIA_URL`, `MEDIA_HOST`, `VIDEO_URL`) are unchanged.

### tests/active/test_source_fetch.py
- Every `stream_media` call drops the positional `MEDIA_SIZE`. `MEDIA_SIZE` stays as the body size.
- The three cap tests are retired: `..._refuses_a_declared_length_over_max_bytes_without_reading`, `..._refuses_a_body_streamed_past_max_bytes_consuming_nothing_past_it` and `..._names_its_own_max_bytes`.
- The docstring and the `MEDIA_SIZE` comment no longer mention `max_bytes` or `media over`.

### tests/tmp/probe_56_phase1_audiopipe.py (throwaway probe, still on disk)
- This probe imports the edited worker and runs `AudioPipe` with a no-op download, a fake ffmpeg writing 100000 zero bytes, `LOOKAHEAD_SECONDS` 1 and a 1000-sample window.
- Observed: the reader parked at exactly 34000 bytes (limit 17000 samples) with `done` False. Releasing to the end gave 50000 samples, `done` True, no error, and `close` returned.
- I have no delete tool, so it needs removing by hand.

**Beyond the files named.** tests/tmp/probe_56_phase1_audiopipe.py - a throwaway observation probe I wrote and could not delete (I have no delete tool); please remove it.

#### Phase 2 - Lease drop at claim and abandon in the worker [code]

**Files touched.** engine/server/data/subtitles.py (EDITED), engine/server/db/jobs/translate-worker.py (EDITED), tests/active/test_subtitles.py (EDITED), tests/active/test_translate_worker.py (EDITED)

**Checkpoint.** Seam: the store functions in engine/server/data/subtitles.py against a tmp subtitles.db, and the worker's `run_job` through the existing `Rig`. `Rig.claim` gains `wanted_at=None` and forwards it to `enqueue_translate_job`, and `worker.now_ms` is monkeypatched.

C1: enqueue four rows: queued with an expired lease, queued unleased (`wanted_at` None), queued with a fresh lease, and ready with an expired `wanted_at`. Call `claim_translate_job(conn, "en", t, expired_at=cutoff)` and assert:
- The expired queued row is gone. This rules out a claim that never drops.
- The unleased, fresh and ready rows are still present and unchanged. This rules out a drop that ignores NOT NULL, the cutoff or the state gate.
- The claimed job is the oldest surviving queued row.

C2, positive half: claim a leased row with the lease already expired against the patched `now_ms`, then run `Rig.run`. Assert that `rig.row() == {}`, that exactly one log record contains `abandoned, no viewer`, and that run_job returned False.

C2, negative half: claim an unleased row with `now_ms` far ahead. The run ends ready with its cues. This rules out an abandon that ignores `wanted_at IS NOT NULL`.

**Intent.** A page-queued job whose viewer lease has lapsed no longer survives in subtitles.db. It is deleted at claim while queued, or abandoned at a chunk-loop wake while running. A command-line job with a NULL lease is never dropped either way.

- C1 - The claim deletes queued rows whose lease has expired and keeps unleased, fresh-leased and non-queued rows.
- C2 - A running job whose lease has lapsed has its row deleted and logs one abandoned line, while an unleased job runs to ready.

**Outcome.** ### engine/server/data/subtitles.py
- `JOB_COLUMNS` gains `("wanted_at", "INTEGER")`. The existing in-place `ALTER` loop in `ensure_subtitles_schema` adds it, and rows from before the migration read NULL, which means unleased.
- `enqueue_translate_job(..., queued_at, *, wanted_at: int | None = None)` writes `wanted_at` on insert. Every positional caller, including the CLI, still inserts NULL.
- `claim_translate_job(conn, target_language, started_at, *, expired_at: int | None = None)`: when `expired_at` is given, the existing `_immediate` block first runs `DELETE ... WHERE state = 'queued' AND target_language = ? AND wanted_at IS NOT NULL AND wanted_at <= ?`, then claims the oldest remaining row as before. Running, ready, unleased and fresh rows are never touched. With no cutoff, behaviour is unchanged.
- Two new `TranslateJob` methods:
  - `read_lease()` reads `wanted_at` only while the row is still `running` with this claim's `started_at`. It returns None for a CLI job or once the claim is lost, so a row the instance track took over never shows its stale lease.
  - `abandon(expired_at)` is one conditional DELETE on the key, `state = 'running'`, the claim's `started_at`, `wanted_at IS NOT NULL` and `wanted_at <= expired_at`, under `with self.conn:`. It returns `rowcount == 1`. It is a sibling of `_update_claim` and does not go through it, because it deletes rather than updates.
- The module docstring, the `JOB_COLUMNS` comment and the `TranslateJob` docstring now mention the lease column, the claim's drop and the two new methods.

### engine/server/db/jobs/translate-worker.py
- The `server_config` import gains `TRANSLATE_LEASE_MS`. The api/ path comment and the module docstring mention the lease.
- New `JobAbandoned` exception.
- New `lease_lapsed(job)`: it takes `expired_at = now_ms() - TRANSLATE_LEASE_MS`, and returns True only when `read_lease()` gives a non-NULL lease at or before that cutoff and `abandon(expired_at)` deleted the row.
  - A `sqlite3.Error` is logged as a warning and counts as not lapsed, so a locked store never fails a viewer's job.
  - A renewal that wins the race against the delete also counts as not lapsed, and the job carries on with its cues. This is the operator's "continue" decision.
- `translate_audio` checks `lease_lapsed(job)` at every wake, right after the `stop` check, and raises `JobAbandoned`. That puts the check after the whitelist, instance-track and video-JSON fetches and the media open, and before any chunk is transcribed.
- `run_job` gets a new `except JobAbandoned` branch that logs `[translate-worker] abandoned, no viewer video_id=%s host=%s` once and returns False. Its docstring names the abandon path.
- `serve` claims with `expired_at=now - TRANSLATE_LEASE_MS`, using one `now_ms()` for both the claim time and the cutoff.

### engine/server/api/server_config.py
- Adds `TRANSLATE_LEASE_MS = 180_000` beside the other translate constants, with a one-line comment. The approved plan has this constant, but Phase 1 did not land it, and the worker needs it here.

### tests/active/test_subtitles.py
- These edits follow from the new column, which is a confirmed requirement (the plan's "JOB_COLUMN_NAMES gains wanted_at"):
  - `JOB_COLUMN_NAMES` gains `wanted_at`, so `ALL_COLUMNS` has fifteen columns.
  - The upgrade test's NULL check on the old rows also covers `wanted_at`.
  - The `end_ready_from_instance` full-row dict gains `"wanted_at": None`.
  - The docstring counts are updated ("six nullable job columns", "fifteen columns") and the column list names `wanted_at`.
- No assertion was loosened. Each one still checks the exact schema and row, now with the extra column.

### tests/active/test_translate_worker.py
- Not changed. The checkpoint claims through the store's own `claim_translate_job`, so `Rig.claim` needed no `wanted_at`. Existing Rig and serve tests queue unleased rows, which are never dropped or abandoned.

### tests/active/test_internal_translate.py
- `QUEUED_ROW`, compared against `SELECT *`, gains a trailing `None` for the new `wanted_at` column. In this phase the Engine's enqueue route does not stamp a lease yet; Phase 3 makes that element `NOW`.

**Beyond the files named.** engine/server/api/server_config.py: added `TRANSLATE_LEASE_MS = 180_000`. The worker's lease cutoff needs it, the approved design puts it in server_config, and no phase lists server_config except Phase 1, which did not add it.
tests/active/test_internal_translate.py: `QUEUED_ROW` is a 14-tuple compared against `SELECT *`. Adding the `wanted_at` column in this phase makes it 15 columns, so I appended `None` (the route does not stamp a lease until Phase 3). Without this, five enqueue-route tests (lines 1095, 1110, 1123, 1159, 1174) go red on the schema change alone.

#### Phase 3 - Renewal on read and the cancel route [code]

**Files touched.** engine/server/api/handlers/internal_translate.py (EDITED), engine/server/api/handlers/__init__.py (EDITED), engine/server/api/router.py (EDITED), client/engine_api_client.py (EDITED), client/server.py (EDITED), client/frontend/src/data/translate.ts (EDITED), tests/fixtures/translate_contract.json (EDITED), tests/active/test_internal_translate.py (EDITED), tests/active/test_server.py (EDITED), tests/active/test_engine_api_client.py (EDITED), tests/config.json (EDITED)

**Checkpoint.** Seam: the Engine handlers, entered through the existing driver harness in tests/active/test_internal_translate.py (ENGINE_DRIVERS and HANDLERS against a tmp subtitles.db). The Client gateway is entered through `_routed_translate_engine` in tests/active/test_server.py. The translate_contract.json fixture is replayed through all three layers (test_engine_api_client.py, the CONTRACT_RUNNER in test_frontend_translate.py, and test_internal_translate.py).

C1: seed five rows: leased queued, leased running, leased ready, unleased queued, and none. Drive the state route for each with `now_ms` patched, and assert:
- `wanted_at` equals now for the two leased queued and running rows.
- It is byte-identical for the ready and unleased rows, and no row appears for the missing key.
- The answer for each row equals the answer the route gave before the change, so the read result is unaffected.

C2, through the gateway: `POST /api/translate/cancel` with a valid profile makes exactly one bridge call to `/internal/translate/cancel` with `{id, host}` and answers its `{state, available}`.

C2, at the Engine handler:
- A leased queued row with a fresh lease ends with `wanted_at == now - TRANSLATE_LEASE_MS + TRANSLATE_CANCEL_GRACE_MS`, so the lease is shortened.
- A row whose lease is already earlier than that keeps its value, so the cancel never lengthens it.
- The answer is the state after the update, with `available`.

C2, in the contract: the cancel cases replay through all three layers, and the exact-set check holds.

**Intent.** A viewer's state read now renews a leased queued or running job's lease. A new cancel route, from the page's data layer through the Client gateway to the Engine, caps that lease at the cancel grace period and answers the state after the update.

- C1 - A state read of a leased queued or running row sets its lease to now, and leaves every other row unwritten.
- C2 - A cancel through the Client gateway shortens the row's lease to the grace cap without ever lengthening it, and answers state and available.

**Outcome.** Paths below are the real ones. The phase list's `client/engine_api_client.py`, `client/server.py` and `tests/fixtures/translate_contract.json` are `client/backend/lib/engine_api_client.py`, `client/backend/server.py` and `tests/active/fixtures/translate_contract.json`.

### engine/server/api/handlers/internal_translate.py
- **Renewal on read:** `_read_key` now renews the lease when the row it read is `queued` or `running`. It calls `renew_translate_lease(conn, key…, now_ms())` inside the same `subtitles_db_lock` hold as the read. The renewal has its own `try/except sqlite3.Error`, which logs `[translate] lease renewal failed video_id=… host=…` and returns the answer unchanged. A renewal error therefore never reads as "no row" and never ends the page's poll. Ready, failed, already_english and missing rows cost no write.
- **Enqueue stamps the lease:** `handle_internal_translate_enqueue` passes `wanted_at=now` with the same `now_ms()` used for `queued_at`. Phase 2 left this to Phase 3. Without it, no page job would carry a lease, and renewal and cancel would never match a row.
- **New `handle_internal_translate_cancel`:**
  - It calls `_resolve_translate_key`, so a bad body answers 400 and an unknown or denied video answers 404, exactly as the other two routes do.
  - In one `_subtitles_store` hold it calls `cancel_translate_lease(..., now_ms() - TRANSLATE_LEASE_MS + TRANSLATE_CANCEL_GRACE_MS)`, then `fetch_subtitle_state` and `_generation_available`.
  - It answers `{state, available}` with no cues, using `none` for no row.
  - A closed store answers `{none, false}`. A `sqlite3.Error` is logged and answers 503 `Translate store unavailable`.
- **Imports:** `cancel_translate_lease`, `renew_translate_lease`, `TRANSLATE_CANCEL_GRACE_MS` and `TRANSLATE_LEASE_MS`.
- **Docstrings:**
  - The module docstring describes renewal, the lease taken at enqueue, and a new cancel-route paragraph. "Stores only ready" now reads "stores only ready and renews leases".
  - `resolve_translatable_video` and `_resolve_translate_key` now say all three routes.
  - The enqueue docstring names the lease.

### engine/server/api/router.py
- Imports `handle_internal_translate_cancel`.
- Adds `POST_ROUTES["/internal/translate/cancel"]`. The existing `/internal/` gate covers it.
- Adds a `[bridge gate]` line for the route to the module docstring.

### engine/server/api/handlers/__init__.py
- The `internal_translate` line now names the cancel bridge request.

### engine/server/api/server_config.py (not in this phase's list)
- Adds `TRANSLATE_CANCEL_GRACE_MS = 20_000` with a one-line comment: it must stay above the page's 16 s `STATE_POLL_MAX_MS`.

### engine/server/data/subtitles.py (not in this phase's list)
- New `_LEASED` predicate: `state IN ('queued','running') AND wanted_at IS NOT NULL`.
- New `renew_translate_lease(conn, key…, now)`: one conditional UPDATE under `with conn:` that sets `wanted_at = now`.
- New `cancel_translate_lease(conn, key…, capped_at)`: the same predicate, with `wanted_at = MIN(wanted_at, ?)`, so it never lengthens a lease.
- The module docstring names both functions and says CLI rows are never renewed or shortened.

### client/backend/lib/engine_api_client.py
- New `cancel_translate(engine_base_url, video_id, host)`, a mirror of `request_translate`:
  - one POST of `{id, host}` to `/internal/translate/cancel`, with the default 6 s timeout and the bridge headers;
  - a 404 `Video not found` maps to `{none, false}`;
  - any other non-200 raises `Engine translate cancel failed (HTTP N): …`;
  - the state must be in `TRANSLATE_STATES`, so `busy` raises `Engine translate cancel returned invalid payload`;
  - `available` goes through `_translate_available`.
- The `TRANSLATE_REQUEST_STATES` comment notes that the cancel route answers `TRANSLATE_STATES`.

### client/backend/server.py
- `_handle_translate_post` now takes the Engine call as a parameter, `engine_call: Callable[[str, str, str], dict[str, Any]]`. The profile check, the body read after it, the validation and `_respond_engine_failure("translate", …)` are shared as they were.
- `/api/translate` passes `request_translate`.
- A new `/api/translate/cancel` branch in `_serve_post`, placed before the 404, runs `_rate_limit_check(url.path)` (its own bucket, 429), then `_handle_translate_post(cancel_translate)`.
- The import adds `cancel_translate`.

### client/frontend/src/data/translate.ts
- New exported `cancelTranslate(apiBase, id, host)`, which POSTs `{id, host}` to `/api/translate/cancel`.
- `requestTranslate` and `cancelTranslate` now share a private `postTranslate(apiBase, path, id, host, states)`. It holds the old `requestTranslate` body with the path and the accepted state list as parameters.
- New `CANCEL_STATES` (the six stored states). `REQUEST_STATES` is now `[...CANCEL_STATES, "busy"]`, so `busy` on cancel throws `Translate response was malformed`.
- New type `TranslateCancelState`, and the module comment names the cancel.

### tests/active/fixtures/translate_contract.json
- Adds 17 `cancel` cases:
  - the six stored states, each with and without `available`;
  - one `cancel video not found` 404 → `{none, false}`;
  - rejected: `cancel route missing 404`, `cancel busy`, `cancel unknown state`, `cancel available a string`.
- No cancel case carries cues.
- The description names the third route and the three gateway functions.

### tests/active/test_engine_api_client.py
- `ROUTES` gains `cancel`, and the import gains `cancel_translate`.
- The replay dispatches through a small `_gateway_call(case, engine_base)`.
- The coverage loop adds `("cancel", TRANSLATE_STATES)`.
- The module and test docstrings now cover three routes.

### tests/active/test_internal_translate.py
- `QUEUED_ROW`'s last element (`wanted_at`) is now `NOW`, the lease the enqueue route takes.
- New `_cancel_driver(row)` with six `("cancel", state)` entries in `ENGINE_DRIVERS`.
- `ROUTE_STATES` adds the six cancel pairs, making 19.
- `HANDLERS["cancel"] = "handle_internal_translate_cancel"`.
- The startup test also POSTs `/internal/translate/cancel` with the token (expects 404 `Video not found`) and without it (expects 401).
- The docstrings are updated, including the pair count, the enqueue row's lease, the cancel drivers and `_record_handlers`.

### tests/active/test_frontend_translate.py (not in this phase's list)
- `CONTRACT_RUNNER` imports `cancelTranslate` and sends cancel cases through it.
- `_result`'s request control expects path `/api/translate/cancel` for a cancel case.
- The docstrings are updated to match.

### tests/config.json
- `test_internal_translate.py` now also maps to `engine/server/api/router.py`.

### tests/active/test_server.py
- Not changed. The checkpoint covers the gateway cancel route (one bridge call, the answer mapping, 401 with no call) through the helpers already in this file.

**Beyond the files named.** engine/server/api/server_config.py - added `TRANSLATE_CANCEL_GRACE_MS = 20_000`. The cancel cap needs it, the approved design puts it in server_config, and no phase lists server_config for it.
engine/server/data/subtitles.py - added `renew_translate_lease` and `cancel_translate_lease` (and the `_LEASED` predicate) as the design names them. Phase 2 did not add them, and every store write lives in this module.
tests/active/test_frontend_translate.py - the new `cancel` fixture cases would otherwise replay through `requestTranslate`, and `cancel busy` would come back as a value instead of a throw. That is the fixture-and-three-replayers-land-together risk the impact list names. I changed only `CONTRACT_RUNNER`'s dispatch and import, `_result`'s expected path, and their docstrings. Phase 4's scenarios are untouched.

#### Phase 4 - Page cancel and re-request [code]

**Files touched.** client/frontend/src/pages/video-page/translate.ts (EDITED), tests/active/test_frontend_translate.py (EDITED)

**Checkpoint.** Seam: the video page in the real browser harness, the generation_pages scenarios in tests/active/test_frontend_translate.py. The page's fetches go to a stub gateway. The stub answers `POST /api/translate/cancel` from its own key (500 when unconfigured) and gains a per-answer delay, and `_asked` includes the cancel path.

C1: a scenario that clicks off while a state poll is held in flight by the delay. Assert:
- Exactly one request was sent to `/api/translate/cancel`. This rules out no cancel, or one cancel per click handler.
- Its body is `{id, host}`, with the profile key.
- Its index in `page["requests"]` is after the completion of the delayed GET. This rules out a cancel sent while the poll was still in flight.
- `rejections` is empty.

C2: a scenario where the poll answers queued and then `none` with `available` true. Assert:
- A second `POST /api/translate` is sent after that `none`, with `{id, host}`. This rules out a poll that ends on none.
- The status shown is the waiting label.
- In a twin scenario where the `none` comes with `available` false, no second POST is sent. This control shows that the `available` flag gates the re-request.

**Intent.** On the video page (client/frontend/src/pages/video-page/translate.ts), turning Translate off sends one cancel after any request already in flight. A poll that reads none while generation is available asks for the translation again.

- C1 - Turning Translate off sends exactly one cancel, and only after the in-flight state poll has settled.
- C2 - A poll answer of none with available sends a new generation request.

**Outcome.** ### `client/frontend/src/pages/video-page/translate.ts`
- **C1: cancel on turnOff.** Each translate request the page sends is now wrapped in a new `tracked()` helper. That covers turnOn's state read, every state poll and every generation request. `tracked()` extends a module-level `requestsSettled` promise, built with `Promise.allSettled(...).then(() => undefined)` so earlier answers don't pile up inside it. `turnOff` now takes `(apiBase, video)` and sends `cancelTranslate` (which already existed in `data/translate.ts`) once `requestsSettled` resolves. So with nothing in flight the cancel goes out on the next microtask, and with a poll in flight it waits for that poll's answer. A failed cancel is caught. The comment explains why there is nothing to show: the lease runs out on its own and the page is already off. The click handler passes `apiBase` and `video` through.
- **C2: re-request from the poll.** turnOn's existing "none + available → `requestTranslate` → `applyRequest`" branch moved into a new `applyFetched()`, which turnOn and the state poll now share. The poll changed from `.then(ok, err)` to `.then(applyFetched).catch(err)`, so a failed re-request takes the same path as a failed poll: a 401 shows its message, and anything else retries with backoff. `applyFetched` sets `lastState = "none"` before the request, so the `queued` answer for the new job counts as a change and the poll restarts at 2 s instead of carrying on the old job's doubled delay.
- Updated the module doc comment to cover both behaviours.

### `tests/active/test_frontend_translate.py`
- Retired the `stop-none` case. Its `none` answer used the default `available: true`, and it asserted that this answer ends the poll, which C2 now contradicts. With C2 that `none` sends a generation request (answered 500 in that runner) and the poll retries. I removed the `stop-none` scenario, dropped `"none"` from the parametrization, renamed the test to `test_a_401_or_turning_translate_off_ends_the_poll`, and updated the docstring line. A `none` *without* `available` still ends the poll; the existing `unavailable` scenario and the checkpoint's `re-request-unavailable` twin both cover it.
- Nothing else in the file conflicts. Both runners answer `/api/translate/cancel` with a fallback 200 `{}`, which `cancelTranslate` rejects as malformed and the page catches. The assertions there filter on the exact `/api/translate` path.


