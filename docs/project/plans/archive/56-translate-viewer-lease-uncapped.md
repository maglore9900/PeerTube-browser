# Translate jobs held by a viewer lease, with no duration or size cap

## Requirements

### What was asked for
Remove the translate worker's duration cap and media-size cap, since the media is streamed and never stored. Handle what the caps were standing in for: a viewer who gives up on a long translation (closes the video, or turns Translate off) must not leave the worker busy with it, and there must be a way to cancel a translation.

### Purpose
Any whitelisted video can be translated whatever its length. The single GPU worker spends time only on videos someone is still waiting for.

### Background (checked 2026-10-09)
- A debug session on 2026-10-09 found translation "not working" was the caps. Since the last success on 10-06, 7 jobs failed with `duration Ns over 3600s`, including both of the operator's attempts that day (7754 s and 5284 s). The rest failed on the video itself: no speech (music), HTTP 403, an incomplete cert chain, one transient CUDA OOM. A 295 s French interview queued as a control ended `ready`.
- Checked in `engine/server/db/jobs/translate-worker.py`:
  - `AudioPipe` streams the download into ffmpeg's stdin and never writes it to disk (`_feed`, `stream_media`).
  - `_read` appends every decoded sample to `self.pcm` (line 225), and nothing is ever dropped. The rat-tail at line 182 says so. The duration cap (`max_samples`, line 227) is the only bound on that buffer, which grows by about 115 MB per hour of audio.
  - `_read` drains ffmpeg as fast as the network allows. Today's control decoded at roughly 100× real time while Whisper ran at roughly 20×, so trimming alone would still buffer most of a long video ahead of the translation.
  - `translate_audio` wakes at least every `POLL_SECONDS` (2 s) and checks `stop` there (line 346). That is the natural point to check a lease.
- Checked in `engine/server/data/subtitles.py`:
  - `enqueue_translate_job` never overwrites a row in any state, so a `failed` video is never retried.
  - Every `TranslateJob` write is a conditional update on `state='running'` and the claim's `started_at`.
- Checked in `engine/server/api/handlers/internal_translate.py`: the state route answers a `queued` or `running` row from the store with no fetch, under `subtitles_db_lock`. Every poll from a waiting page passes through it.
- Checked in `client/frontend/src/pages/video-page/translate.ts`:
  - While a job is `queued` or `running` and generation is available, the page polls the state route every 2–16 s (doubling while nothing changes).
  - `turnOff` sends nothing to the server.
  - A `none` answer on the poll path ends polling (`applyState`). Only `turnOn` requests generation.
- Checked in `server_config.py`, `source_fetch.py` and the worker CLI:
  - `SUBTITLE_MAX_DURATION` (3600) is checked at CLI enqueue, at claim against the stored row, against the live JSON, and on the decoded samples.
  - `SUBTITLE_MAX_BYTES` (1 GiB) is checked against Content-Length and while streaming in `stream_media`.
  - A JSON without a duration fails `video duration unknown`, which exists only to feed the cap.

### Acceptance criteria
- **AC1 No duration cap.** `SUBTITLE_MAX_DURATION`, the CLI's `--max-duration`, every duration check (stored row, JSON, decoded samples) and the `video duration unknown` failure are gone. A video of any length is translated.
- **AC2 No media-size cap.** `SUBTITLE_MAX_BYTES`, `run --max-bytes` and `stream_media`'s size checks are gone. `fetch_bounded`'s 2 MB cap on instance API responses stays, because it is a different bound. The worker still picks the smallest acceptable media file.
- **AC3 Constant memory.** The worker's decoded-audio buffer holds at most a fixed lookahead past the current translation position plus the current window, whatever the video's length. Samples already translated are dropped. The reader stops pulling from ffmpeg once the lookahead is full, so the download slows to the translation's pace instead of buffering ahead.
- **AC4 Viewer lease.** A job queued from the page carries a lease. Every state read of a `queued` or `running` row through the Engine's state route renews it. A running job whose lease has expired is abandoned within one chunk-loop wake. A queued job whose lease has expired is never started.
- **AC5 Cancel.** Turning Translate off on the page sends a cancel for that video. A cancel shortens the lease to a short grace period rather than ending the job outright, so a job another viewer is still polling survives. With no other viewer, the job stops within the grace period plus one chunk.
- **AC6 Abandoned jobs can be requested again.** An abandoned job leaves no row, so the state reads `none` and a later Translate request queues it afresh. Its partial cues are discarded. A page still on Translate that polls and reads `none` while generation is available requests generation again, as `turnOn` does. That covers a backgrounded tab whose throttled timers let the lease lapse.
- **AC7 Jobs from the command line run to the end.** A job queued by `translate-worker.py enqueue` has no lease and is never abandoned.

### Scope
- **In:**
  - the worker (`AudioPipe`, `translate_audio`, `generate`, `resolve_video`, CLI flags);
  - `data/subtitles.py` (lease column, claim, abandon, cancel);
  - `data/source_fetch.py` (`stream_media` size cap);
  - `server_config.py`;
  - the Engine translate routes, plus a cancel route;
  - the Client gateway (a cancel route);
  - the page (cancel on Translate off, re-request on `none` while on);
  - the translate contract fixture;
  - docs (`TRANSLATE_WORKER.md`, `engine/server/README.md`, `client/README.md`, `CONTEXT.md`, `DEPLOYMENT.md` where it names the caps).
- **Out:**
  - resuming an abandoned job from its partial cues;
  - per-viewer accounting of who holds a lease;
  - a progress or ETA display;
  - showing a failed job's reason on the page (a separate improvement found in the same debug session);
  - a cancel sent when the tab closes. The lease covers that case. A `keepalive` fetch on `pagehide` is a possible later addition.

### Consistency constraints
- Every new store write follows the existing pattern: one `BEGIN IMMEDIATE` or conditional update, and every write to a running job goes through `TranslateJob` (the claim rule, issue 54).
- The new route follows the existing bridge-gated `/internal/translate*` shape, with the same validation and resolve (`_resolve_translate_key`), so a cancel for an unknown or denied video answers 404 like the others.
- The Client cancel route checks the profile first, as `_handle_translate_get` and `_handle_translate_post` do.
- All three layers stay held to `tests/active/fixtures/translate_contract.json`.
- The schema change is an in-place `ALTER TABLE` in `ensure_subtitles_schema`, like plan 49's job columns.

### Conflicts
- **AC6 vs the rule that a key is never re-queued.** That rule applies to `failed`. An abandoned job is not failed, and deleting its row is what makes it requestable again. Resolved by the operator choosing "abandoned jobs can be requested again" (2026-10-09).
- **AC1 vs the 7 rows already failed on the cap.** Under the never-retry rule those rows would stay failed forever. Resolved by the operator on 2026-10-09: they were deleted that day, before the build, by `.scratch/translate-debug/clear_cap_failures.py` (failed rows whose `error` starts with `duration ` or `audio longer than`). The build carries no cleanup.

### Amendments to the confirmed requirements

### Source issue
None. This came from the 2026-10-09 debug session.

## High-level plan

### Approach
**Lease column.** `subtitles` gains a `wanted_at` column (ms). The Engine's enqueue route sets it to now when it queues a job. The CLI leaves it NULL, meaning unleased (AC7). Existing rows migrate with NULL, so nothing in flight changes meaning. The lease length is a `server_config` constant, `TRANSLATE_LEASE_MS`, proposed at 180 s.

**Renewal (AC4).** When the state route reads a `queued` or `running` row, it renews `wanted_at` in the same `subtitles_db_lock` hold, with one conditional update that only touches leased rows (`wanted_at IS NOT NULL`). A renewal that fails is logged and the answer is unchanged. This mirrors the cache-write failure path, so a locked store never turns a poll into an error.

**Worker side (AC4).**
- `claim_translate_job` first deletes `queued` rows whose lease has expired, then claims the oldest remaining one, all in its existing IMMEDIATE transaction.
- `translate_audio` already wakes at least every 2 s. It reads the job's lease through a new `TranslateJob` method at each wake. If the lease has expired, it raises a new `JobAbandoned`, and `run_job` ends the job through another new `TranslateJob` method, a conditional delete on the claim (AC6).
- The read can run every wake or be throttled to every few seconds. It is a single-row primary-key read either way.

**Cancel (AC5).** A new bridge-gated `POST /internal/translate/cancel {id, host}` resolves the key as the other routes do. With one conditional update it sets a leased row's `wanted_at` back so that it expires `TRANSLATE_CANCEL_GRACE_MS` from now (proposed 20 s, above the page's 16 s maximum poll interval). It answers the key's state afterwards.
- A poll from another viewer inside the grace period renews the lease, so that viewer keeps the job.
- With no other viewer, the worker drops the job at its next wake after the grace period.
- The Client adds `DELETE /api/translate?id&host` (profile-checked) to proxy it, and `turnOff` fires it without waiting for the answer.

**Page re-request (AC6).** `applyState`, on a poll-path `none` with `available` while Translate is on, calls `requestTranslate` instead of ending, which is the same step `turnOn` takes.

**Constant memory (AC3).**
- `AudioPipe` keeps `base`, the absolute sample index of `pcm[0]`. `wait_samples` and `slice` take absolute indices as now.
- A new `release(upto)` drops samples before `upto`. `translate_audio` calls it after each window with the new `pos`.
- `_read` waits on the existing condition while the buffered samples past the release point exceed `LOOKAHEAD_SECONDS` (proposed 600 s, about 19 MB). It stops reading ffmpeg's stdout, ffmpeg blocks on its full stdout pipe and stops reading stdin, and the feeder's `write` blocks, so the socket is read at the translation's pace.
- `close` and `_fail` already set `stop` and kill ffmpeg. The wait must also wake on `stop`, so a stopped or failed pipe never leaves `_read` parked.

**Caps removed (AC1, AC2).** The duration checks and `video duration unknown` are deleted, along with `max_samples`. `stream_media` loses `max_bytes` and both checks, and the `media over N bytes` error text goes. The CLI's `--max-duration` and `run`'s `--max-bytes` flags go. `pick_media_url` is unchanged.

### Alternatives considered
- **Explicit cancel only, no lease.** This doesn't cover a closed tab, a crash or a lost network connection, which are the common ways a viewer leaves. Rejected.
- **A `cancelled` state instead of deleting the row.** This would let the page say "translation stopped". But it is a new state through the contract fixture, the Client's `TRANSLATE_STATES` and the page, and enqueue would then need a rule to re-queue it. Deleting reuses `none`, which every layer already handles. Rejected for size.
- **Resume from partial cues.** Keeping the cues and the position would save repeated work when a viewer comes back. Re-downloading from an offset needs Range requests, and HLS fragment seeking is worse. Out of scope, as the operator drew it.
- **Raising the caps instead of removing them.** This keeps the failure mode the operator hit, only at a different length. With constant memory and the lease, neither cap protects anything. Rejected.
- **A cancel that ends the job outright.** One viewer's Translate off would stop another viewer's job. Rejected in favour of shortening the lease.
- **Trimming the buffer without backpressure.** This doesn't bound memory, because decode outruns translation by roughly 5×. Rejected.

### Risks and gotchas
- **R1 Background-tab throttling.** Browsers throttle timers in hidden tabs. Chrome's intensive throttling limits chained timers to once a minute after 5 minutes hidden. A 60 s lease would expire for a viewer who switched tabs to wait, which is why 180 s is proposed. AC6's re-request covers the case where it lapses anyway, at the cost of restarting the job from zero.
- **R2 Remote send timeouts under backpressure.** While the lookahead is full the socket is read only as Whisper frees space. Reads stay frequent because each 30 s window takes about 1.5 s on the 3070, but a single stalled Whisper call (a hang) could leave the socket unread. A server with a short send timeout (nginx default 60 s) would then reset the connection and the job fails `media download failed`. The existing 600 s stall detector already marks such a worker unavailable.
- **R3 Unleased CLI jobs have no bound.** A CLI-queued live stream or endless file would run until stopped. This is accepted because the operator issues CLI jobs.
- **R4 A write on every poll.** Each poll on a queued or running job now writes `subtitles.db`. That is one short update every 2–16 s per waiting viewer, in WAL mode. Both blue/green Engines may write. The busy timeout is already 30 s, and a failed renewal is logged rather than surfaced.
- **R5 Blue/green.** An older Engine without the renewal serves polls during a switch. That is harmless while the switch drain (30 s) stays well under the lease (180 s). An older worker would ignore `wanted_at` and run jobs to the end, which is the current behaviour.
- **R6 A long job blocks the queue.** One job runs at a time. A 3-hour video holds the GPU for about 10 minutes while other viewers' jobs wait queued. Their leases keep renewing while they poll, so they wait rather than expire.

### Tradeoffs to accept
- An abandoned job loses its work. Coming back means starting again from zero.
- A cancel takes effect after a grace period of about 20 s, not instantly.
- A viewer who leaves a tab hidden long enough for the lease to lapse restarts the job when the tab polls again.
- A video's length is no longer refused up front. A very long one is simply slow, and only while someone waits.

### Documentation to update
- `engine/server/db/jobs/docs/TRANSLATE_WORKER.md`: Bounds, Media File Choice, Job Pipeline, Error Texts, the in-memory PCM statement, CLI flags, and a new lease and cancel section.
- `engine/server/README.md`: the column, the store functions, the cancel route.
- `client/README.md`: the gateway cancel route.
- `CONTEXT.md`: Translate job (lease, abandonment, the CLI exception), Translate state (`none` after abandonment). A term for the lease, proposed **Viewer lease**.
- `DEPLOYMENT.md`, where it names the caps or the `--max-*` flags.
