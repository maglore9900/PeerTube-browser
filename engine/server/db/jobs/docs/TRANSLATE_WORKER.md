# Translate Worker

This document describes how `engine/server/db/jobs/translate-worker.py` works.

## Purpose

`translate-worker.py` produces English cues for non-English whitelisted videos with Whisper's `translate` task, one queued job at a time, into `engine/server/db/subtitles.db`. It is a separate long-running process so the model never loads inside the Engine: numpy, faster-whisper and the CUDA wheels are imported only inside `WhisperRunner`, so `enqueue` and the Engine run without them. The Engine's `/internal/translate` serves what it writes: the job state, a `running` job's cues so far, the final `ready` cues, and `available` from the heartbeat.

It has two subcommands:
- `enqueue` queues one video from the command line;
- `run` is the service that serves the queue.

The Engine's `/internal/translate/enqueue` also queues jobs, when a viewer turns Translate on (see [Enqueue](#enqueue)). For the `subtitles.db` columns, the `translate_worker_heartbeat` table, the store functions and the Engine's translate routes, see `engine/server/README.md`. For the service unit, the faster-whisper install, `ffmpeg`, GPU pinning and the firewall, see `DEPLOYMENT.md`.

## Inputs and Outputs

Inputs:
- Whitelist DB: `engine/server/db/whitelist.db` (`--whitelist-db`, read only)
- The video's own instance: the captions (B1's `fetch_instance_track`) and `/api/v1/videos/{uuid or id}`
- One media file from the https host the instance's JSON names
- System `ffmpeg` on `PATH`
- Whisper `medium`, `int8_float16`, on the CUDA device the process sees

Outputs, all in `subtitles.db` (`--subtitles-db`), the only file the worker writes besides its lock and log:
- job rows in `subtitles`, keyed `(video_id, instance_domain, 'en')`
- the single heartbeat row
- the lock file `engine/server/db/translate-worker.lock` (`--lock`) and the log `engine/server/db/translate-worker.log` (`--log`)

## Job Lifecycle

| State | Meaning |
|---|---|
| `queued` | Waiting; `enqueue` or the Engine's enqueue route inserted it with source `whisper`, `queued_at` and `attempts` 0. A row from the Engine's route also carries `wanted_at`, its viewer lease; a row from `enqueue` carries NULL. |
| `running` | Claimed; `started_at` set and `attempts` raised by 1. `cues_json` holds the cues so far, rewritten whole after each chunk, and the Engine serves them while the job runs. |
| `ready` | Done, with the full start-sorted cue list. Source `whisper`, or `instance` when the instance had an English track at claim time. |
| `already_english` | The first speech chunk was detected as English; no cues are stored. |
| `failed` | Ended with an error text in `error` (see [Error Texts](#error-texts)). Partial cues stay in `cues_json` and are never served. |

Every job ends in exactly one of `ready`, `already_english` or `failed`, or is abandoned: a leased job whose lease lapsed is deleted, at claim while `queued` or at a chunk-loop wake while `running` (see [Viewer Lease and Cancel](#viewer-lease-and-cancel)). An abandoned job leaves no row and its partial cues go with it, so its state reads `none` and it can be queued again. A failed key is never queued again.

## Enqueue

```bash
./venv/bin/python3 engine/server/db/jobs/translate-worker.py enqueue --id <id-or-uuid> --host <host>
```

`--whitelist-db` and `--subtitles-db` go before the subcommand. `--cap` (default `SUBTITLE_QUEUE_CAP`, 50) is the most `queued` jobs at once. Run it as the service user, so the files it creates stay writable by the worker.

The host goes through `normalize_host`. The video is resolved by `resolve_translatable_video` (`api/handlers/internal_translate.py`), as the Engine's routes resolve it: `fetch_video_row` with `VIDEO_ERROR_THRESHOLD`, then the active denylist on the row's normalised domain. The job is queued under the row's canonical `video_id` and `instance_domain`, with a NULL `wanted_at`, in one IMMEDIATE transaction that never overwrites an existing row. A job queued here has no viewer lease and runs to its end.

| Line | Exit |
|---|---|
| `queued video_id=… host=…` | 0 |
| `error: whitelist.db: …` or `error: subtitles.db: …` | 1 |
| argparse usage error | 2 |
| `already present: <state> video_id=… host=…` (a key in any state) | 3 |
| `refused: queue cap N` | 4 |
| `refused: invalid id or host`, `refused: not in whitelist`, `refused: host denied` | 5 |

The Engine's enqueue route inserts the same row through the same store call, with the same cap and the same whitelist and denylist resolve, and stamps `wanted_at` with its enqueue time. It queues only while the heartbeat is fresh (see [Heartbeat](#heartbeat)).

## Run: Start-up Order

```bash
./venv/bin/python3 engine/server/db/jobs/translate-worker.py run
```

1. Set up logging to stdout and the `--log` file.
2. Check `ffmpeg` with `shutil.which`; missing, it logs `ffmpeg not found on PATH` and exits 1.
3. Take `flock(LOCK_EX | LOCK_NB)` on `--lock`. When another worker holds it, it logs `another worker holds <lock>` and exits 6 before `subtitles.db` is opened, so nothing is written. The kernel drops the lock when the process dies, so a crash leaves no stale lock.
4. Install SIGTERM/SIGINT handlers that set stop.
5. `open_translate_worker_store` re-asserts the flock on the held descriptor, then creates the directory, opens `subtitles.db` in WAL, migrates it and runs crash recovery (see [Stop, Crash and Recovery](#stop-crash-and-recovery)); the counts are logged.
6. Start the heartbeat thread.
7. Serve the queue until stop.
8. On the way out: set stop, join the heartbeat for up to 5 s, close the connection and the lock, log `stopped`, exit 0.

`run` flags, each a positive integer:
- `--max-chunk-seconds`, defaulting to `SUBTITLE_MAX_CHUNK_SECONDS` (see [Bounds](#bounds));
- `--stall-seconds`, defaulting to the worker's `STALL_SECONDS` (600 s): the longest main-loop silence before the heartbeat stops (see [Heartbeat](#heartbeat)).

The poll, back-off and idle-unload times in [Serve Loop](#serve-loop) are `serve`'s defaults, not flags.

## Serve Loop

Each pass claims the oldest `queued` row (by `queued_at`, then rowid) in one short IMMEDIATE transaction and runs it until it ends or is abandoned. The claim takes `expired_at = now - TRANSLATE_LEASE_MS` and, in the same transaction, first deletes the `queued` rows whose `wanted_at` is at or before it; the drop writes no log line. With no job, or when the claim raises a sqlite error (logged, retried), it sleeps 2 s. After 300 s without a job (`IDLE_UNLOAD_SECONDS`) it unloads the model; the next job loads it again.

After a `whitelist.db` requeue (see [Job Pipeline](#job-pipeline) step 1) it waits 30 s (`TRANSIENT_BACKOFF_SECONDS`) before the next claim, slept in 2 s slices. The requeued job is still at the head of the queue, so it is reclaimed every cycle, with later jobs waiting behind it, until `whitelist.db` is usable; then it runs like any other job. A cycle takes about 60 s under a held lock (the 30 s busy wait plus the back-off) and about 30 s with a missing file.

## Job Pipeline

For a claimed job, in order, each bound ending the job `failed` before the next remote request (step 1 requeues it instead when `whitelist.db` is unavailable):

1. Resolve the video against `whitelist.db` again, exactly as `enqueue` does. When the lookup raises an `OperationalError` whose text contains `locked`, `busy` or `unable to open` (the updater merge holding the file past the 30 s busy timeout, or a restore that has removed it), the job goes back to `queued` with `attempts` lowered by 1 and its `queued_at` kept, writing no `error` or `finished_at` and making no remote request, and the serve loop backs off. Every other database error fails the job as `<ExceptionType>: <text>`.
2. Fetch the instance's English caption track with B1's `fetch_instance_track`. If there is one, store it `ready` with source `instance` while the claim holds (`end_ready_from_instance`) and the job is done; if the Engine's store took the row over first, nothing is written and the job is taken over (see [Takeover](#takeover-by-the-instance-track)).
3. Fetch the video JSON through B1's `fetch_bounded`: https to the video's own instance domain only, redirects only on that domain, B1's size and time limits. The video's duration is not checked: a video of any length, or with no duration, goes on.
4. Pick the media file (see [Media File Choice](#media-file-choice)).
5. Download it once, sequentially, into ffmpeg's stdin (`-i pipe:0 -vn -f s16le -ac 1 -ar 16000 pipe:1`), reading 16 kHz mono PCM from its stdout into RAM. ffmpeg never reads the URL itself, because it stalls seeking a remote fragmented MP4. Nothing touches disk, and the download has no size cap. `AudioPipe` buffers at most `LOOKAHEAD_SECONDS` (600 s) past the translation position plus one window (`--max-chunk-seconds`), about 20 MB whatever the video's length; `translate_audio` releases the samples behind its position after each window. When the buffer is full, the reader stops pulling from ffmpeg, so ffmpeg and the download wait and the download runs at the translation's pace. Meanwhile the socket is not read, so a media host's send timeout (nginx's default is 60 s) during a long Whisper call can end the job `media download failed`.
6. Cut and translate the audio window by window (see [Chunking and Translation](#chunking-and-translation)).

There is no whole-job deadline; the media download is bounded by a 15 s socket timeout per read.

## Bounds

| Bound | Constant / flag | Where it is enforced |
|---|---|---|
| Lookahead | `LOOKAHEAD_SECONDS` = 600 s (worker constant) | Decoded audio buffered past the translation position, plus one window; a full buffer pauses ffmpeg and the download. |
| Viewer lease | `TRANSLATE_LEASE_MS` = 180 s, `TRANSLATE_CANCEL_GRACE_MS` = 20 s (`server_config`) | Page jobs only; see [Viewer Lease and Cancel](#viewer-lease-and-cancel). |
| Queue length | `SUBTITLE_QUEUE_CAP` = 50 (`server_config`), `enqueue --cap` | `queued` rows only, at `enqueue` and on the Engine's enqueue route. |
| Chunk length | `SUBTITLE_MAX_CHUNK_SECONDS` = 30 s (`server_config`), `--max-chunk-seconds` | The window size handed to Whisper. |
| Whitelist and denylist | — | At enqueue and at claim. |
| Instance calls | — | https to the video's own instance domain; redirects stay on it. |
| Media URL | — | See [Media File Choice](#media-file-choice). |

## Media File Choice

`pick_media_url` looks at `files[]` and `streamingPlaylists[].files[]` of the video JSON:
- a file with `hasAudio: false` is skipped (a missing `hasAudio` is kept);
- its `fileUrl` must be https on a DNS name: no port, no userinfo, at least two labels, and a last label of letters or punycode, which refuses every IP literal including forms like `127.1`, `2130706433` and `0x7f.0x1`;
- a file in `streamingPlaylists[].files[]` wins over any in `files[]`, which is used only when no HLS file qualifies. HLS files are fragmented MP4, which ffmpeg decodes from the download pipe; a web-video MP4 may keep its index (moov atom) at the end, and ffmpeg reading that from a pipe decodes nothing;
- within that group the smallest declared `size` wins; files without a size rank last but are still chosen when nothing else qualifies.

The host may differ from the instance domain (object storage, a CDN): the instance chooses it. A redirect may only stay on that exact host. No acceptable file fails the job `no usable https media file`.

## Chunking and Translation

Each window holds at most `--max-chunk-seconds` of audio. faster-whisper's Silero VAD (on CPU, 500 ms minimum silence, 200 ms speech padding) finds the speech spans, and the window is cut:
- at its end when it is the last window, has no speech, or ends in silence;
- otherwise at the middle of its last gap between speech spans, when that point is at least 5 s in;
- otherwise at its end, a hard cut through speech.

A chunk with speech before the cut is translated with `task="translate"` and `vad_filter=True`; a chunk without speech is skipped, using no GPU time. Cue times are the segment times plus the chunk's offset, rounded to ms; empty texts and non-finite or reversed times are dropped. After each chunk that adds cues, the running row's whole `cues_json` is rewritten, so each write grows with the cue count.

The language is detected on the first chunk with speech. English ends the job `already_english` before any cue is written; any other language is passed to every later chunk. A job whose media ffmpeg decodes to no audio at all, while still exiting 0, fails `no audio decoded`; one that decodes audio but produces no cue fails `no speech detected`. Otherwise the cues are sorted by start and the job ends `ready` with source `whisper`.

The model loads on the first translated chunk: the cuBLAS and cuDNN wheels are preloaded with `ctypes` (`RTLD_GLOBAL`), then `WhisperModel("medium", device="cuda", compute_type="int8_float16")`. A CUDA out-of-memory error unloads the model and fails only that job with its `RuntimeError: …` text; the next job loads the model afresh.

## Viewer Lease and Cancel

A job queued from the page holds a viewer lease in `wanted_at` (ms); the worker spends time on it only while a viewer is still waiting. The lease has lapsed when `wanted_at <= now - TRANSLATE_LEASE_MS` (180 s); the Engine and the worker read `now_ms()` on the same host.

- **Renewal.** Every Engine state read of a leased `queued` or `running` row sets `wanted_at` to now. For the routes, see `engine/server/README.md`.
- **Cancel.** The Engine's cancel route caps `wanted_at` so the lease lapses `TRANSLATE_CANCEL_GRACE_MS` (20 s) later, and never lengthens it. A viewer still polling within the grace renews the lease and keeps the job.
- **Queued.** The claim deletes a lapsed `queued` row before choosing the next job (see [Serve Loop](#serve-loop)), so it never starts.
- **Running.** At every chunk-loop wake, right after the stop check, `lease_lapsed` reads the lease with `read_lease`, which reads only while the claim holds. On a lapse it runs `abandon`, one conditional DELETE on the claim, `wanted_at IS NOT NULL` and the lease still lapsed, and the job raises `JobAbandoned` and logs `abandoned, no viewer`. The first wake comes after the media open, before any chunk is transcribed; a long step such as the model load or a Whisper call delays the check to the next wake.
- **Races.** A renewal that lands between the read and the delete wins: the delete matches no row and the job continues with its cues. A `sqlite3.Error` on the read or the delete is logged as `lease check failed` (warning) and counts as not lapsed; the next wake checks again.
- **Command-line jobs.** A NULL `wanted_at` is never renewed, shortened, dropped or abandoned, so an `enqueue` job runs to its end.
- **Stop and recovery.** A SIGTERM requeue keeps `wanted_at`, and so does crash recovery's requeue; a lease that lapsed while the worker was down is dropped at the next claim.

## Error Texts

A `failed` row's `error` is one of:
- `not in whitelist`, `host denied` (the resolve at claim)
- `video JSON fetch failed`, `no usable https media file`
- `media download failed: …` (HTTP status, an off-host redirect, a timeout or reset), `ffmpeg exit N: <stderr tail>`
- `no audio decoded`, `no speech detected`
- `worker stopped while running twice` (recovery)
- `<ExceptionType>: <text>` for anything else, including CUDA out-of-memory and a `whitelist.db` error other than a lock or a missing file (for example `no such table`)

## Stop, Crash and Recovery

- **SIGTERM/SIGINT.** Stop is checked each time the chunk loop wakes, so the current chunk finishes first. The job then goes back to `queued` without spending its claim (`attempts` lowered by 1) and keeps its `queued_at`, so it stays at the head of the queue. Shutdown then closes the media pipe: `close` wakes a reader parked on a full lookahead, and killing ffmpeg releases a feeder blocked writing; otherwise the download thread ends within one 15 s socket timeout. The heartbeat join takes up to 5 s. During the back-off after a `whitelist.db` requeue, stop ends `serve` within one 2 s slice with no further claim; during sqlite's 30 s busy wait inside the claim-time lookup, it takes effect only when that wait ends.
- **Crash.** A row left `running` is handled at the next `run` start, under the lock: recovery is private to the store and runs only through `open_translate_worker_store`, after its flock re-assert. With `attempts` below `MAX_CLAIMS` (2) it goes back to `queued`; at 2 or more it becomes `failed` with `worker stopped while running twice`. A crashed job is therefore retried once.

## Takeover by the Instance Track

The Engine's `/internal/translate` answers a `queued` or `running` row from the store, but fetches the instance for no row or a `failed`/`already_english` row, and stores a found English track as `ready`/`instance` over whatever row is there when the fetch returns. That can overwrite a `running` job when the job was queued and claimed while such a fetch was in flight, or during a blue/green switch when an older Engine still treats every non-`ready` key as a miss. `claim_translate_job` returns a `TranslateJob` handle holding the connection it claimed on, and every worker write to a running job goes through one of its methods: the updates `write_running_cues`, `end_ready`, `end_already_english`, `end_failed`, `requeue` and `end_ready_from_instance`, the lease read `read_lease`, and `abandon`, a conditional DELETE. Each matches only the key with `state='running'` and the claim's `started_at`, and the writes return whether the claim still held; once the Engine's store has written, they match zero rows and return False, the worker logs `taken over by the instance track` and writes nothing more for that job. `read_lease` returns None on such a row, so a replaced row is never abandoned.

## Heartbeat

A separate thread on its own connection upserts `translate_worker_heartbeat` (`id=1`, `beat_at` in ms, `pid`) at start and then every 5 s (`HEARTBEAT_SECONDS` in `api/server_config.py`), idle or busy. The main loop records progress on every serve pass, every back-off slice and every chunk-loop wake (at most 2 s apart), so the beat continues through a `whitelist.db` outage. When it has recorded none for 600 s (`--stall-seconds`, default `STALL_SECONDS`), for example a single Whisper call or fetch that hangs, the beat is skipped until progress resumes, so a hung worker reads as unavailable. A failed beat is logged and retried on the next tick. The row is left in place on exit, so its age is what tells a stopped worker apart: the Engine counts generation available only for a beat at most 15 s old (`HEARTBEAT_FRESH_MS`, derived beside it as three `HEARTBEAT_SECONDS` beats, so changing the interval moves the window with it), and otherwise neither queues a job from the page nor reports `available`.

## Known Gaps

- `WhisperRunner`'s faster-whisper calls have not yet run against an installed faster-whisper, and the peak-VRAM measurement on the 3070 (target ≤ 3,072 MiB) is outstanding.

## Logs

Lines go to stdout (the journal under systemd) and the `--log` file, all prefixed `[translate-worker]`:
- `started pid=… recovered requeued=N failed=N` / `stopped`
- `claimed video_id=… host=… attempts=N`
- `job ready video_id=… host=…`, `job already_english …`, `job ready from the instance track …`
- `job failed video_id=… host=…: <error>`; `job error video_id=… host=…` with a traceback for an unexpected exception
- `stopped mid-job, requeued video_id=… host=…`
- `abandoned, no viewer video_id=… host=…`
- `whitelist.db unavailable, requeued video_id=… host=…: <error>` (warning level)
- `lease check failed video_id=… host=…: <error>` (warning level)
- `taken over by the instance track video_id=… host=…`
- `model loaded name=medium compute_type=int8_float16` / `model unloaded`
- `claim failed: …`, `heartbeat failed: …`
- `another worker holds <lock>`, `ffmpeg not found on PATH`
