# 49-translate-whisper-worker

_Rendered by the `dev-flow` workflow from its run state. Every edit here is overwritten on the next step; the evidence each gate turned on is in `docs/project/plans/52-49-translate-whisper-worker.record.md`._

## Requirements

### Purpose

B1 (`docs/project/plans/archive/48-translate-instance-captions.md`, delivered) shows English subtitles only when the video's own instance already has an English caption track, which is rare. This build (plan 49, split from B2 of `docs/project/plans/18-english-subtitles.md`) adds a worker process that produces English cues for any non-English video up to 60 minutes long, using Whisper's `translate` task on the RTX 3070. It is subtitles only: no dubbed audio and no text-to-speech. The build ends at "a queued job becomes stored English cues". Nothing on the website changes. A job is queued from the command line. `docs/project/plans/50-translate-generation-in-page.md` adds the Engine/Client routes and the page, and it depends on this plan's enqueue function, heartbeat and per-chunk cue appends.

### Existing code this builds on (B1, as found in the tree)

- `engine/server/data/subtitles.py`:
  - `connect_subtitles_db(path)` opens the file with a 30 s busy timeout (`SUBTITLES_BUSY_TIMEOUT_SECONDS`), `check_same_thread=False`, `sqlite3.Row`, no deadline handler and the default journal mode.
  - `ensure_subtitles_schema(conn)` creates table `subtitles` with columns `video_id`, `instance_domain`, `target_language`, `state`, `source`, `fetched_at` (INTEGER ms), `track_text`, `cues_json`, and primary key `(video_id, instance_domain, target_language)`. `state` and `source` are plain TEXT with no CHECK.
  - `fetch_ready_subtitles` reads only `state='ready'` rows and returns a non-empty cue list or None.
  - `store_ready_subtitles` upserts the whole row as `ready`, replacing whatever state the key held.
  - Cues are one compact JSON array per row in `cues_json`, each cue `{start, end, text}`.
- `engine/server/api/handlers/internal_translate.py`:
  - `fetch_instance_track(host, video_key)` returns `(track_text, cues)` or None, within a 15 s budget, an 8 s per-fetch deadline, 2 MB per response and a 4 s socket timeout.
  - The module also holds `fetch_bounded`, `pick_english_track_path`, `parse_webvtt`, `same_host_https` and `SameHostRedirectHandler`, plus the constants `TARGET_LANGUAGE="en"` and `SOURCE_INSTANCE="instance"`.
  - The route resolves the video with `resolve_video_row` against the Engine's `whitelist.db`, keys the store by the row's canonical `video_id` and `instance_domain`, refuses denylisted hosts (`list_active_denied_hosts`), and fetches with `row["video_uuid"] or canonical_id`.
  - The worker may import these functions from there, or move the reusable ones into `engine/server/data/` first. That is a design choice; B1's behaviour must not change.
- `normalize_host` is in `engine/server/data/moderation.py:45`.
- The existing long-running worker to model the process on is `engine/server/db/jobs/updater-worker.py`.

### AC1: Queue

- Jobs are persistent rows in B1's `subtitles` table in `engine/server/db/subtitles.db`, so a restart loses no queued work.
- New states are `queued`, `running`, `failed` and `already_english`, alongside B1's `ready`. New source value: `whisper`.
- The rows gain whatever the job needs: timestamps (queued, started, finished), an error text, the detected language and an attempt count. These are added to the existing table without a rebuild, and old B1 rows must stay readable.
- Enqueue is idempotent on the key `(video_id, instance_domain, target_language='en')`. A key in any state (`queued`, `running`, `ready` from instance or whisper, `already_english`, `failed`) gets no new job, and enqueue never overwrites an existing row. Re-queuing a failed key is out of scope.
- The queue has a total cap on the number of `queued` jobs, 50 by default and configurable. Enqueue past the cap is refused with a distinguishable result.
- The worker runs one job at a time and claims the oldest `queued` row in one short transaction.
- A job left `running` by a crash goes back to `queued` once at the next worker start. If it is found `running` at start a second time, it is marked `failed` with an error text.
- This plan sets `journal_mode=WAL` on `subtitles.db`, because the Engine (B1's route, possibly two blue/green Engines) and the worker both write it. Transactions stay short. Concurrent writing by the Engine and the worker must be tested (risk R8, memory `engine-concurrent-start-locks-random-cache`).

### AC2: Command-line enqueue

A command-line entry point takes a video's `id` and `host` and puts it on the queue. It calls the same enqueue function plan 50's route will call. Before enqueuing, it resolves the video the way B1 does (see AC5, whitelist), so the stored key is the canonical `video_id` and `instance_domain`. It reports the outcome: queued, already present (with state), refused by the cap, or refused by a bound.

### AC3: Generation

1. When it claims a job, the worker first calls `fetch_instance_track` again. If the instance now has an English track, that track is stored as a `ready` row with source `instance` (`store_ready_subtitles`), and the job is done.
2. Otherwise the worker reads the video's JSON from the instance (`/api/v1/videos/{uuid or id}`), takes the duration from it, and picks the smallest https media file. It downloads that file in one sequential pass, piped into ffmpeg's stdin, and reads 16 kHz mono PCM from ffmpeg's stdout. Nothing is written to disk. ffmpeg must not read the remote URL directly, because it stalls on fragmented MP4 (R1).
3. It runs faster-whisper `translate` (model `medium`, compute type `int8_float16`) with voice-activity filtering (`vad_filter`), on audio chunks cut at silence, with a maximum chunk length of 30 s by default (configurable).
4. Cues are stored under the key with source `whisper`. Cue times are absolute: each chunk's times plus its offset in the video.
5. The language is detected on the first chunk. If it is English, the job ends `already_english` and stores no cues. This happens before any cues are appended.

### AC4: Cues while running

- The cues of each finished chunk are appended to the store while the job is `running`, so a reader can fetch what exists so far. Plan 50 reads them; plan 18 decided this as Q1 for B2.
- Storage is either a new cue table or a rewrite of the row's `cues_json` per chunk. That is a design choice, but B1's `fetch_ready_subtitles` must keep returning the complete cue list for a `ready` row with either source.
- A job ends in exactly one of `ready`, `already_english` or `failed`, and `failed` carries an error text.

### AC5: Bounds

The worker refuses, ending the job `failed` with an error text and doing no further remote work:

- **Duration:** a video longer than `SUBTITLE_MAX_DURATION` (seconds, configurable, default 60 minutes).
- **Whitelist:** a video that does not resolve in the Engine's `whitelist.db` `videos` table by `id` and `host`, or whose host is on the active denylist. This is the check B1 uses. It runs at enqueue (AC2) and again when the job is claimed. Hosts go through `normalize_host`.
- **Instance API calls:** the video JSON and captions calls go only to https on the video's own instance domain, and redirects may only stay on that domain, as in B1.
- **Media URL (operator decision):** the media URL must be https on the host named in the instance's JSON for that file. That host may differ from the instance domain, to cover object storage and CDNs. IP-literal hosts, explicit ports and userinfo are refused. A redirect may only stay on the media URL's own host.
- **Size:** a download larger than `SUBTITLE_MAX_BYTES` (configurable, default 1 GiB). This is checked against Content-Length when present, and enforced while streaming.

### AC6: Heartbeat

While it runs, idle or busy, the worker writes a heartbeat timestamp every 5 s into `subtitles.db`, in a small table, because the worker writes only into that store. Plan 50 judges "generation available" from the heartbeat's age.

### AC7: Memory

- With the desktop running, the worker process's peak VRAM stays at or under 3,072 MiB. This is measured with `nvidia-smi` during a real job, and the measurement is part of the build's evidence.
- A CUDA out-of-memory error marks the job `failed` with an error text. The job is not retried in a loop, and the worker keeps serving later jobs.
- The model loads lazily and is unloaded after 5 minutes idle.

### Environment and install (in scope, gate before any phase)

- faster-whisper (1.2.1, with CTranslate2 4.8.2 as in S0) is installed into `engine/.pixi` through its existing manual pip step (memory `engine-pixi-env-is-pip-filled`), never into the root `pixi.toml`, which un regenerates (memory `root-pixi-toml-regenerated-drops-pytest`). Worktrees symlink main's `engine/.pixi`.
- Before any phase:
  1. Do a pip dry run.
  2. If any pinned package would move (`transformers 4.57.6`, `huggingface-hub 0.36.0`, `tokenizers 0.22.2`, `numpy 2.4.1`, `torch 2.5.1+cu121`, `nvidia-cublas-cu12 12.1.3.1`, `nvidia-cudnn-cu12 9.1.0.70`), or a second set of CUDA libraries would come in, stop and put it to the operator.
  3. Otherwise install, then run a tiny `translate` on CUDA in that environment. This also checks CTranslate2 4.8.2 against cuDNN 9.1; S0 used 9.27.
  4. Then run the Engine's tests that use the query encoder.
- The Engine never imports faster-whisper, CTranslate2 or the CUDA wheels, so it keeps running on a machine without a GPU. The worker may preload the cuBLAS/cuDNN wheels with `ctypes`, as S0 did, rather than setting `LD_LIBRARY_PATH`.

### Consistency constraints

- The worker is a separate long-running process, like `engine/server/db/jobs/updater-worker.py`. The model never loads inside the Engine.
- The worker writes only into `subtitles.db`.
- The worker is pinned to the 3070 with `CUDA_VISIBLE_DEVICES`. The display stays on that card (plan 18, Q1(b)).
- Remote fetches reuse `normalize_host` and the https-only rule.
- B1's existing route behaviour and tests stay as they are.
- New code matches the style of the file it lands in.

### Close-out

- `DEPLOYMENT.md` gains the worker's service unit, the faster-whisper install step and the GPU pinning (`CUDA_VISIBLE_DEVICES`).
- `CONTEXT.md` gains the glossary term **Translate job**.

### Out of scope

- The Engine and Client routes, the "generation available" check in the page, and any frontend change (plan 50).
- Target languages other than English, and a per-profile language setting.
- Re-queuing failed jobs.
- Pruning stored translations.
- Bulk generation.
- Backfilling `videos.language`.
- Serving results back to instances.

### Limitations and tradeoffs accepted

- English only, and one job at a time.
- Stored translations are never pruned (about 48 KB per hour of video).
- Detection on the first chunk can mark a video with an English intro as `already_english` (R6).
- Long unbroken speech is still cut at the maximum chunk length (R2).
- Music or noise can produce invented or repeated lines; `vad_filter` reduces this (R5).
- A second service to run, in exchange for keeping the model out of the Engine.
- On-demand latency, in exchange for spending no GPU time on videos nobody watches.
- Because the media host is allowed to differ from the instance host, the instance chooses which https host the worker downloads from. The bounds on that are https only, no IP literals, no ports, no userinfo, no redirect off that host, and the size cap.

### Baseline suite state

The pre-build baseline suite passes (exit code 0, no variant). Test trees: active `tests/active`, working `tests/tmp`, archive `tests/archive`. The record is `tests/last_test_validation.json` and the output `tests/last_test_output.txt`.

## High-level plan

### Approach

Before writing this I read `data/subtitles.py`, `handlers/internal_translate.py`, `handlers/video.py` (`fetch_video_row` and `resolve_video_row`), `data/moderation.py`, `data/db.py`, `server_config.py`, `updater-worker.py`, `tests/active/test_internal_translate.py` and the plan 49 file. Nothing below conflicts with the settled requirements.

**Where the code lands (two places, one new file).** All store logic goes into the existing `engine/server/data/subtitles.py`, which uses only the stdlib. That covers the schema upgrade, WAL, enqueue, claim, crash recovery, per-chunk cue rewrite, job finish and heartbeat. The Engine already imports this module, and plan 50's route will call the same enqueue function from it. All GPU, media and process logic goes into one new script, `engine/server/db/jobs/translate-worker.py`. It is a sibling of `updater-worker.py` and follows its layout: the `script_dir`/`server_dir`/api-dir `sys.path` setup, `argparse` with `CompactHelpFormatter`, `setup_logging`, plain functions and a `main()`. It has two subcommands. `enqueue --id --host` is the command-line entry point for AC2. `run` is the long-running service. faster-whisper, CTranslate2 and the ctypes preload of the cuBLAS/cuDNN wheels are imported only inside the `run` path's model-load function. So `enqueue`, the Engine and every test that does not touch the model run on a machine without a GPU. The new limits go into `server_config.py` next to `DEFAULT_SUBTITLES_DB_PATH`, as plain constants that the worker's flags default to: `SUBTITLE_MAX_DURATION` = 3600, `SUBTITLE_MAX_BYTES` = 1 GiB, `SUBTITLE_QUEUE_CAP` = 50, and a maximum chunk length of 30 s. The Engine route in plan 50 reads the same cap.

**Reuse B1's fetch code by importing it, not by moving it.** The worker imports `fetch_instance_track`, `fetch_bounded`, `same_host_https`, `SameHostRedirectHandler`, `TARGET_LANGUAGE` and `SOURCE_INSTANCE` from `handlers.internal_translate`, and `fetch_video_row` from `handlers.video`. I checked that these modules pull in only stdlib modules and `server_config`/`http_utils`/`data.*`: no torch and no faiss. Moving them would break B1's tests. Those tests patch `internal_translate.build_opener` and `internal_translate.fetch_bounded` on that module object, and the requirement is that they stay as they are.

**AC1, queue.**
- *Schema upgrade.* `ensure_subtitles_schema` is extended. In one `BEGIN IMMEDIATE` transaction it creates the table if missing, reads `PRAGMA table_info`, and runs `ALTER TABLE ADD COLUMN` for each job column that is missing: `queued_at`, `started_at`, `finished_at` (INTEGER ms), `error` (TEXT), `detected_language` (TEXT) and `attempts` (INTEGER NOT NULL DEFAULT 0). It also adds an index on `(state, queued_at)` and the heartbeat table.
- *Old rows and concurrent openers.* Old B1 rows read with NULLs in the new columns, and B1's `SELECT` lists name their columns, so they are unaffected. Doing the check and the alter inside one immediate transaction is what stops two openers (two Engines, or an Engine and the worker) from racing into "duplicate column".
- *WAL.* `connect_subtitles_db` gains `PRAGMA journal_mode=WAL`. The mode persists in the file, so every later opener (Engine, CLI, worker) is a no-op after the first.
- *Enqueue.* Enqueue takes the canonical key and runs in one `BEGIN IMMEDIATE` transaction. If the key exists in any state, it returns "exists" with that state. If the count of `queued` rows is at or over the cap, it returns "cap". Otherwise it inserts with `ON CONFLICT DO NOTHING`, so it never overwrites anything. The new row is `state='queued'`, `source='whisper'`, `fetched_at`=`queued_at`=now (`fetched_at` is NOT NULL in B1's schema) and `attempts=0`. The result is a small distinguishable value: queued, exists(state) or cap.
- *Claim.* One short immediate transaction selects the oldest `queued` row (by `queued_at`, then rowid) and flips it to `running` with `started_at` set and `attempts`+1.
- *Crash recovery at start.* Any `running` row with `attempts` < 2 goes back to `queued`. A `running` row with `attempts` ≥ 2 has now been found running at start a second time, so it becomes `failed` with the error "worker stopped while running twice".
- *One worker at a time.* An `fcntl.flock` on a lock file next to the database enforces this. The kernel drops the lock when the process dies, so a crashed worker never leaves a stale lock (unlike the pid-file lock in `updater-worker.py`).

**AC2, CLI enqueue.**
- *Resolve.* It normalises the host with `normalize_host`. It opens `whitelist.db` read-only (`connect_readonly_db`) and calls `fetch_video_row(conn, id, host, error_threshold=VIDEO_ERROR_THRESHOLD)`, exactly as `resolve_video_row` does for B1. It then refuses a host in `list_active_denied_hosts`.
- *Duration.* It also refuses a row whose stored `duration` already exceeds `SUBTITLE_MAX_DURATION`. This is a cheap early bound; the worker re-checks against live JSON.
- *Enqueue and report.* Otherwise it enqueues under the row's canonical `video_id` and `instance_domain`. It prints one line (queued / already present: <state> / refused: queue cap / refused: <bound>) and exits with a distinct code for each outcome.

**AC3 and AC5, generation in order, each step stopping the job as `failed` with an error text and no further remote work.**
1. **Whitelist and denylist again**, read-only, the same function as at enqueue.
2. **`fetch_instance_track`** on the row's domain with `video_uuid` or the canonical id. If it finds an English track, the worker stores it with `store_ready_subtitles(..., SOURCE_INSTANCE, ...)`, stamps `finished_at`, and the job is done.
3. **Video JSON** at `/api/v1/videos/{uuid or id}`, through B1's `fetch_bounded`: https only, same-host redirects only, 2 MB, 8 s. If `duration` is missing or not numeric, the job fails because the bound cannot be checked. If it exceeds `SUBTITLE_MAX_DURATION`, the job fails.
4. **Pick the media file.** The candidates are `files[]` plus `streamingPlaylists[].files[]`, taking each file's `fileUrl`. A candidate is kept only if `fileUrl` passes the media URL check. That check normalises the host with `normalize_host` and then refuses: a scheme other than https, an IP-literal host (`ipaddress`), an explicit port, and userinfo. The worker takes the smallest kept file by declared `size`; files without a size sort last. If none is kept, the job fails.
5. **Download** through `build_opener(SameHostRedirectHandler(media_host))`, so a redirect may only stay on the media URL's own host. The socket timeout is generous; a stall fails the job. It refuses a `Content-Length` over `SUBTITLE_MAX_BYTES`, and it counts bytes while streaming and aborts past the cap. A feeder thread writes the response into the stdin of `ffmpeg -i pipe:0 -f s16le -ac 1 -ar 16000 pipe:1`. ffmpeg never sees the URL (R1). A reader thread drains ffmpeg's stdout into an in-memory PCM buffer, so the HTTP connection is drained at network speed and is not held back by the GPU. The buffer is at most about 115 MB at 60 minutes of 16 kHz int16. Nothing touches disk. The worker also counts decoded samples: audio past `SUBTITLE_MAX_DURATION` fails the job, so an instance whose JSON understates the duration is still bounded.
6. **Chunking at silence.** The main thread takes the buffered PCM in windows. It runs the Silero VAD that ships inside faster-whisper (`get_speech_timestamps`, no new dependency) and cuts each chunk at the last silence gap before the maximum chunk length. It hard-cuts at the maximum only when there is no gap (R2). Each chunk goes to `model.transcribe(chunk, task="translate", vad_filter=True)`. The language is left unset on the first chunk and then fixed to the detected value for the rest, so detection runs exactly once.
7. **Language.** If the first chunk's detected language is `en`, the job ends `already_english` with `detected_language` recorded and no cues ever written. Otherwise `detected_language` is stored and the job goes on.
8. **Cue times.** Each cue's start and end are the segment's time plus the chunk's offset in samples ÷ 16000, rounded to milliseconds like `parse_webvtt`.

**AC4, cues while running: a per-chunk rewrite of `cues_json`, not a cue table.** After each chunk, the worker writes the whole accumulated cue list into `cues_json` in one short UPDATE. The UPDATE is conditioned on the key, `state='running'` and the claim's `started_at`. At the end, the same conditional update sets `state='ready'`, `fetched_at` and `finished_at`. `fetch_ready_subtitles` is untouched and returns the full list for a ready row of either source. A job that produced no cues at all (VAD found no speech) ends `failed` with "no speech detected", not as an empty `ready`. B1's reader would treat an empty `ready` as a miss, and AC4 allows only the three end states. Every other exception ends the job `failed` with its text.

**AC6, heartbeat.** A daemon thread with its own `connect_subtitles_db` connection upserts a single-row table, `translate_worker_heartbeat` (`id`, `beat_at` ms, `pid`), every 5 s. It runs from worker start to exit, whether idle or busy. A failed beat (for example a lock) is logged and retried on the next tick.

**AC7, memory.**
- *Load and unload.* The model loads on the first claimed job: `WhisperModel("medium", device="cuda", compute_type="int8_float16")`, after the ctypes preload. The main loop polls the queue every couple of seconds and drops the model (del plus gc) once 5 minutes have passed since the last job ended.
- *Out-of-memory.* A CTranslate2 RuntimeError whose text contains "out of memory" marks the job `failed` with that text and unloads the model. The worker then goes on to the next job. A failed job is never re-queued, so there is no retry loop.
- *Evidence.* An `nvidia-smi --query-compute-apps=pid,used_memory` sampler runs during a real job on a long non-English video, and its peak for the worker's pid is recorded. The CUDA device is pinned in the unit with `CUDA_VISIBLE_DEVICES` set to the 3070's GPU UUID, not an index, so the pin does not depend on enumeration order.

**Environment gate (before any phase).** Steps 1 to 4 run as written in the requirements. Two more checks are added. First, the dry run is also read for packages that faster-whisper pulls in: `onnxruntime`, `av`, and their `sympy`/`protobuf`/`numpy` requirements against torch's pins. Second, the environment must have a system `ffmpeg` binary. The worker uses the ffmpeg CLI, not PyAV.

**Testability.** Transcription sits behind one function that takes a PCM chunk and returns segments plus a language. Tests swap in a stand-in for it, so the queue, bounds, pipe, chunk offsets, per-chunk rewrites, takeover and end states are tested without a GPU. Remote instances and media hosts are faked at `build_opener`, the same seam B1's tests use. ffmpeg itself is real and decodes a tiny generated clip. The R8 test runs two processes against one `subtitles.db` for several seconds. One acts as the Engine (`store_ready_subtitles` in a loop, plus `ensure_subtitles_schema` at start). The other acts as the worker (claim, per-chunk rewrites, heartbeat). Neither may raise "database is locked", and the final rows must be consistent. A second case runs two concurrent schema upgrades of a B1-shaped file. The real-GPU job with the `nvidia-smi` sampler is separate, manual evidence.

**Close-out.** `DEPLOYMENT.md` gains:
- the pip step into `engine/.pixi` with the pins to verify;
- pre-downloading the `medium` model into the Hugging Face cache, so the running worker only reads it;
- the system ffmpeg requirement;
- the systemd unit for `translate-worker.py run`, with `CUDA_VISIBLE_DEVICES=<3070 UUID>` and restart-on-failure;
- the `enqueue` command.

`CONTEXT.md` gains **Translate job**: a `subtitles` row keyed `(video_id, instance_domain, en)` that moves from `queued` through `running` to `ready`, `already_english` or `failed`, with source `whisper`, or `instance` when the instance gained a track meanwhile.

### Alternatives considered

- **A separate cue table instead of rewriting `cues_json`.** Rejected. `fetch_ready_subtitles` would have to read a second table for whisper rows, which changes B1's code, and plan 50 would need a join. Rewriting the blob per chunk costs about 120 rewrites of at most about 48 KB for a 60-minute video, a few MB of writes per job in total. That is a deliberate simplification: its ceiling is quadratic write volume, which only matters for much longer videos, and the upgrade path is a cue table read through `fetch_ready_subtitles`.
- **Moving `fetch_bounded` and its relatives into `engine/server/data/`.** Rejected because B1's tests patch `internal_translate.build_opener` and `internal_translate.fetch_bounded` on the handler module, so the move would require test changes. Importing from the handler module is a dependency in the opposite direction from usual, but it is stdlib-only and changes nothing in B1.
- **One `transcribe()` call over the whole audio, letting faster-whisper do its own VAD chunking.** Rejected. It needs the whole download before the first cue, which defeats AC4 and plan 50's early cues, and it does not expose a chunk to append per step. Its language detection would be equivalent.
- **Fixed 30 s windows, or ffmpeg's `silencedetect` for cut points.** Fixed windows split sentences (S0). `silencedetect` means parsing ffmpeg's stderr and tuning dB thresholds, while Silero VAD is already installed with faster-whisper.
- **Two scripts (a worker and a separate enqueue CLI).** Rejected for one script with two subcommands. faster-whisper is imported only on the `run` path, so the split gains nothing.
- **A pid-file lock as in `updater-worker.py`.** Rejected for `flock`: the lock dies with the process, which is exactly the crash case AC1's recovery is about.
- **Holding the model for the life of the process.** Rejected by AC7's 5-minute unload.
- **Running each model lifetime in a subprocess, so unloading also frees the CUDA context.** Not chosen now; it is the upgrade path named under the unload risk below.
- **Letting ffmpeg read the URL, or writing to a temp file.** Rejected by R1 and by the no-disk requirement.

### Gotchas, risks and limitations

- **B1's route can overwrite a running job.** `store_ready_subtitles` upserts unconditionally. If a viewer hits `/internal/translate` while a job is `running` and the instance has gained an English track, the row becomes `ready`/`instance`. The worker's conditional per-chunk and finish updates then match no row. The worker logs a takeover and stops that job without writing, and the key correctly ends `ready`. The job columns of that row (`started_at`, `attempts`) stay as leftovers, which is harmless.
- **`fetched_at` is NOT NULL** in B1's schema, so queued and running rows carry the queue time there until they finish.
- **WAL side effects.** WAL adds `-wal` and `-shm` sidecar files. A read-only opener needs the directory to be writable, which it is for every current opener, including B1's start test. Switching to WAL needs a brief exclusive lock, which the 30 s busy timeout covers on first open.
- **Non-faststart MP4.** If the smallest file is a non-faststart MP4 (`moov` atom at the end), it cannot be decoded from a pipe. PeerTube normally writes faststart web videos and fragmented HLS files, so this is expected to be rare. The job fails with ffmpeg's error, and choosing another file is not attempted.
- **No DNS-level SSRF check (R4).** The media host check is lexical: https only, no IP literal, no port, no userinfo. A hostname that resolves to a private or loopback address is not refused, because resolution happens inside urllib, as it does in B1. I name this as a limitation, not a bound. The upgrade path is resolving the host first and refusing private ranges, with the connection pinned to the resolved address.
- **Unload leaves the CUDA context.** Deleting the CTranslate2 model frees its weights and buffers, but the CUDA context and cuBLAS handles stay in the process, roughly a few hundred MiB, until the process exits. If the operator wants zero idle VRAM, the upgrade path is to run each model lifetime in a child process.
- **Memory headroom (R3).** S0 peaked at 2.1 GiB with the default beam size, well under 3,072 MiB. If the measured peak comes close, the lever is a smaller `beam_size`, at some quality cost.
- **Wall-clock gaps.** As in B1, DNS and a stalled TLS handshake are not bounded by the wall clock. A slow-trickling media server is bounded only by the socket timeout and the size cap, not by a whole-job deadline.
- **R5, R6 and R2** stay as accepted: invented lines on music, an English intro marking a video `already_english`, and hard cuts in long unbroken speech.
- **Unknown sizes.** Files with no declared size sort last, so a host that omits sizes gets an arbitrary one of its files. The byte cap still bounds the download.
- **R7.** faster-whisper also brings `onnxruntime` and `av` into the Engine's environment. The dry run decides whether this is safe; if any pin moves, the build stops and asks.

### Tradeoffs the operator is asked to accept

- **Blob rewrite per chunk** instead of a cue table: simpler, no change to B1's reader, quadratic but small write volume.
- **The worker imports from a handler module** instead of moving B1's fetch code, so B1's tests stay untouched.
- **No DNS-resolution check on media hosts:** the lexical bounds plus the size cap are the whole SSRF fence.
- **About 115 MB of PCM may sit in RAM** per job, at the 60-minute cap, so the download is never stalled by the GPU.
- **An idle worker keeps a CUDA context** after the model unloads.
- **A video with no detected speech ends `failed` ("no speech detected")**, not as an empty `ready`.
- **An early duration check at enqueue** uses the whitelist's stored duration, which may be stale. The authoritative check is at claim time, against live JSON and decoded samples.

## Impacts

<impacts>
<impact path="engine/server/data/subtitles.py" element="module docstring (lines 1-4)">
**What changes:** The docstring says "B1 writes only state 'ready' with source 'instance'" and "plan 49's per-chunk appends need a cue table or a blob rewrite". Both go stale. It should now say:
- the job states (`queued`, `running`, `failed`, `already_english`) and the `whisper` source exist;
- the per-chunk append is a whole-`cues_json` rewrite on a `running` row;
- the file is in WAL mode;
- the translate worker writes it, besides the blue/green Engines.

**Depends on it:** Nothing at runtime.

**Risk:** None.
</impact>
<impact path="engine/server/data/subtitles.py" element="SUBTITLES_BUSY_TIMEOUT_SECONDS and its comment (lines 12-13)">
**What changes:** The value (30 s) stays. The comment names only "several Engines" and "two blue/green Engines" as writers. It should add the worker (claim, per-chunk rewrites, a heartbeat every 5 s) and the CLI enqueue.

**Depends on it:** `connect_subtitles_db`, so every opener: the Engine, the worker's main and heartbeat connections, the CLI and the tests.

**Risk:** None for the code. The 30 s is what lets an Engine start wait out a worker write and the first WAL switch, so it must not be lowered.
</impact>
<impact path="engine/server/data/subtitles.py" element="connect_subtitles_db() (line 16)">
**What changes:** It gains `PRAGMA journal_mode=WAL` right after connect, outside any transaction. The repo pattern is `conn.execute("PRAGMA journal_mode=MEMORY").fetchall()` at `engine/server/data/random_cache.py:27`. The busy timeout, `check_same_thread=False` and `sqlite3.Row` stay.

**Callers:**
- `engine/server/api/server.py:371`, on every Engine start;
- `_subtitles_db` in `tests/active/test_internal_translate.py:484-490`;
- the new worker's main connection, its heartbeat-thread connection and the CLI `enqueue` path.

**Risk of regression:**
1. **Read-only openers after the last writer closed (uncertain; needs a standalone test first).** B1's `_stored()` (`tests/active/test_internal_translate.py:504-510`) opens `file:...?mode=ro` with plain `sqlite3.connect`. At lines 562/564 and 585/587 it does so after the only writer, a temporary `_server(...)` namespace, has been collected. A WAL database deletes its `-wal`/`-shm` on the last close. SQLite 3.22+ lets a read-only connection open such a file only if it can create `-shm`, which needs a writable directory. `tmp_path` is writable, so this should pass. It must still be proven under both pytest's Python 3.14.7 (`tests/last_test_validation.json:25`) and `ENGINE_PY` 3.12.
2. **First switch to WAL.** On an existing rollback-journal file the switch needs an exclusive lock. During a blue/green deploy, the old B1 instance holding a read or a write makes the new instance wait on the 30 s busy handler. An error at server.py:371 aborts the start before listening.
3. **Sidecars.** `subtitles.db-wal`/`-shm` appear. `.gitignore:13-14` already covers them. A file copy taken while services run must include them, or use `sqlite3 .backup`.
4. **Rollback to B1 code.** B1 never sets the journal mode and runs fine on a WAL file.
5. **Read-then-write transactions.** In WAL mode, a deferred transaction that reads and then writes gets `SQLITE_BUSY` at once when another writer committed after its read; the busy timeout does not help. Every new function that reads and then writes (enqueue, claim, recovery) must therefore use `BEGIN IMMEDIATE`. Single-statement writes, like B1's `store_ready_subtitles` INSERT, are unaffected.
</impact>
<impact path="engine/server/data/subtitles.py" element="ensure_subtitles_schema() (line 23)">
**What changes:** It moves from `with conn: CREATE TABLE IF NOT EXISTS` to one explicit `BEGIN IMMEDIATE` transaction. Inside it:
- create the table if missing;
- read `PRAGMA table_info(subtitles)`;
- `ALTER TABLE subtitles ADD COLUMN` for each missing column: `queued_at`, `started_at` and `finished_at` (INTEGER), `error` and `detected_language` (TEXT), and `attempts` (INTEGER NOT NULL DEFAULT 0; SQLite requires the default for a NOT NULL add);
- `CREATE INDEX IF NOT EXISTS` on `(state, queued_at)`;
- `CREATE TABLE IF NOT EXISTS translate_worker_heartbeat`;
- commit, or roll back on any error.

**Implementation constraints:**
- No `executescript`: it commits any open transaction first (`engine/server/data/trending.py:13`).
- Python's legacy transaction control (the default on both 3.12 and 3.14) never auto-begins for DDL or PRAGMA. The explicit BEGIN/COMMIT is what holds the check and the alters together.

**Callers:**
- `engine/server/api/server.py:372`;
- `tests/active/test_internal_translate.py:489`;
- the worker's `run` and the CLI `enqueue`.

**Dependents:**
- The session `engine` fixture (`tests/active/conftest.py:169-208`). It starts the Engine without overriding `DEFAULT_SUBTITLES_DB_PATH` (lines 183-185), so the first test run migrates the developer's real `engine/server/db/subtitles.db` (present in the tree) and switches it to WAL.
- The variant Engines in `tests/active/test_server_config.py` (264-265, 333) and `tests/active/test_random_cache.py` (299-300, 807), which use the same repo path. test_random_cache.py:784-811 starts several Engines at once on purpose.
- Plan 50, which reads the heartbeat table and the job columns.

**Risk of regression:**
- A duplicate-column race between concurrent openers. IMMEDIATE is the guard, and it needs its own test (two concurrent upgrades of one B1-shaped file).
- Every Engine start now takes a write lock, so it can wait behind a worker write, or fail on a lock error.
- B1's `store_ready_subtitles` INSERT names its columns, and `attempts` has a default, so B1 writes still satisfy NOT NULL.
- B1's start test asserts `"subtitles" in tables` (line 651), so the extra table does not affect it.

High, because it runs on every Engine start, including against the shared developer file.
</impact>
<impact path="engine/server/data/subtitles.py" element="fetch_ready_subtitles() (line 43, code unchanged)">
**What changes:** No code change.
- It filters on `state='ready'` and ignores `source`, so B1's route serves a whisper `ready` row as soon as the worker's finish update commits.
- A `queued`, `running`, `failed` or `already_english` row reads as a miss, so B1's route fetches the instance on every view of such a key.

**Depends on it:** `_cached_cues` (`engine/server/api/handlers/internal_translate.py:198`).

**Risk:**
- Low, provided the worker never writes an empty `ready`. The plan sends that case to `failed`.
- `json.loads` accepts `NaN`/`Infinity`, and `json.dumps` writes them by default. A non-finite cue time would load here, then fail the Client's `_is_seconds` (`client/backend/lib/engine_api_client.py:153-155`) and become a 502. The worker must write with `allow_nan=False` or validate its times.
</impact>
<impact path="engine/server/data/subtitles.py" element="store_ready_subtitles() (line 58): code unchanged, docstring stale, now part of the job state machine">
**What changes:** No code change. It is now called from two places:
1. the worker's AC3.1 path, with `SOURCE_INSTANCE`;
2. B1's `_store_cues` (internal_translate.py:209) on every ready-miss. A miss now includes keys in `queued`, `running`, `failed` and `already_english`.

**What the upsert does to job rows:**
- It sets only `state`, `source`, `fetched_at`, `track_text` and `cues_json`. `queued_at`, `started_at`, `finished_at`, `error`, `detected_language` and `attempts` keep their old values, so a `ready`/`instance` row can carry a stale `error` or `detected_language`. Plan 50 must read `state` first.
- A `queued` row it overwrites is never claimed, which is correct.
- A `running` row it overwrites makes every conditional worker update (key + `state='running'` + `started_at`) match zero rows. The worker must read `rowcount == 0` as a takeover.
- AC3.1's own call sets no `finished_at`, so a separate conditional UPDATE is needed. It must tolerate B1 having rewritten the row in between.

**Docstring (line 59):** "a concurrent miss on the same key writes the same row twice, harmlessly" no longer covers every case. Against a job row the upsert ends the job and leaves its job columns behind. The docstring should say so.

**Risk:** Medium. The state machine is correct only if every worker UPDATE is conditional and checks `rowcount`.
</impact>
<impact path="engine/server/data/subtitles.py" element="new store functions: enqueue, claim, start-up recovery, requeue-without-counting, per-chunk cues rewrite, finish (ready / already_english / failed), heartbeat upsert">
**What changes:** New stdlib-only functions in the file's style: plain functions taking `conn`, one-line docstrings, the time passed in (from `data.time.now_ms`) so tests can control it.

**Enqueue:**
- One `BEGIN IMMEDIATE` transaction: read the key's state, count `queued` rows against the cap, then `INSERT ... ON CONFLICT DO NOTHING`.
- The new row is `state='queued'`, `source='whisper'`, `fetched_at=queued_at=now` (`fetched_at` is NOT NULL) and `attempts=0`.
- It returns queued, exists(state) or cap.
- Plan 50 will call it on the Engine's shared `server.subtitles_db` under `subtitles_db_lock`, so it must roll back on any error and never leave a transaction open.

**Claim:** one IMMEDIATE transaction that picks the oldest `queued` row by `queued_at`, then rowid, sets `running`, `started_at` and `attempts+1`, and returns the key and `started_at`.

**Recovery:**
- A `running` row with `attempts` < 2 goes back to `queued`; one with `attempts` ≥ 2 goes to `failed` ("worker stopped while running twice").
- It must run only from `run` and only after the flock is held (see the worker start-up entry).

**Requeue without counting (recommended in step 4, pass 2):** a conditional UPDATE (key, `state='running'`, `started_at`) setting `state='queued'` and `attempts=attempts-1`. It is used on SIGTERM and on a whitelist-lock error at claim time, so ordinary stops and the updater's merge do not use up the single retry. Whether to adopt it is for step 4/5; without it, two ordinary restarts during one job fail the key permanently.

**Per-chunk rewrite:** UPDATE `cues_json` (and `detected_language`) WHERE key, `state='running'` and `started_at`, returning `rowcount`.

**Finish:**
- `ready`: sets `fetched_at` and `finished_at`;
- `already_english`: sets `detected_language`, no cues;
- `failed`: sets `error`;
- all three are conditional, like the per-chunk rewrite.

**Heartbeat:** upsert of the single row `(id, beat_at, pid)` in `translate_worker_heartbeat`.

**Depends on it:**
- the worker, the CLI and the new tests;
- plan 50, which takes these names and result shapes as a contract. Plan 50 also needs a "cues so far" reader for `running` rows (AC4 there, with an `after` position). None exists after this build, since `fetch_ready_subtitles` reads only `ready`.

**Risk:** New code, so no regression in existing behaviour. The names become a contract for plan 50.
</impact>
<impact path="engine/server/api/server.py" element="startup open of subtitles.db (lines 347, 371-372), attributes (297-298, 504), shutdown close (574-579)">
**What changes:** No code change. Every Engine start now:
- switches the file to WAL on first open;
- runs the IMMEDIATE migration;
- creates the heartbeat table and the index.

The comment at line 370 ("so a rejected start creates nothing") still holds.

**Depends on it:** Every Engine start: prod 7070/7071 blue/green, dev, the test-suite session Engine and the variant Engines.

**Risk:**
- A lock or migration error at 371-372 aborts the start before listening, and a blue/green deploy then rolls back at readiness.
- During a deploy, the new instance migrates a file the old B1 instance holds open. That is fine while the old instance has no transaction open.

Medium. Covered by the concurrent-upgrade test and B1's start test (`tests/active/test_internal_translate.py:623`).
</impact>
<impact path="engine/server/api/server_config.py" element="new constants next to DEFAULT_SUBTITLES_DB_PATH (line 420): SUBTITLE_MAX_DURATION=3600, SUBTITLE_MAX_BYTES=1 GiB, SUBTITLE_QUEUE_CAP=50, max chunk seconds=30">
**What changes:** Four plain constants, each with a one-line comment above, in the file's style. The comment on `DEFAULT_SUBTITLES_DB_PATH` (line 419, "Instance caption tracks served by /internal/translate") also goes stale: the file now holds translate jobs too.

**Depends on it:**
- the worker's argparse defaults;
- plan 50's route (the cap);
- every test group listing this file in `tests/config.json`, for example `test_internal_translate.py` (397-406) and `test_dislike_profile.py` (35), which all re-run.

**Risk:**
- Importing `server_config` resolves environment variables at import time and raises `SystemExit` on bad values (lines 364, 457-458, 499). The worker imports it directly and through `handlers.video:22`, so a bad Engine variable in a shared `.env.bridge` also stops the worker. The Triage rows at `DEPLOYMENT.md:237-238` should name the translate worker.
- If these constants ever become environment-configurable, they need the same exit-on-bad-value treatment.

Low.
</impact>
<impact path="engine/server/api/handlers/internal_translate.py" element="fetch_instance_track, fetch_bounded, same_host_https, SameHostRedirectHandler, TARGET_LANGUAGE, SOURCE_INSTANCE (imported by the worker; file must stay unchanged)">
**What changes:** No code change. The module becomes a dependency of a non-request process.

**Import chain, checked:**
- `data.moderation` → `data.similarity_cache`: stdlib only;
- `data.subtitles`, `data.time`;
- `handlers.video` → `data.db`, `data.time`, `data.popularity`, `data.peertube_labels`, `http_utils` (stdlib only), `server_config`;
- `handlers/__init__.py` is a docstring only.

No numpy, torch or faiss. The worker needs both `engine/server` and `engine/server/api` on `sys.path` at module top, before these imports.

**Behaviour the worker inherits:**
- `fetch_bounded` returns None on every failure with no reason, so the error text for a failed video-JSON fetch is necessarily generic.
- It needs a monotonic `budget_at`.
- The path must be pre-quoted (`quote(key, safe='')`, as at line 185).
- Its 2,000,000-byte cap and 8 s deadline now also bound the video JSON.
- It sends `accept: application/json, text/vtt`.
- It calls the module-global `build_opener` (line 79). The worker's media download should use its own module-level `build_opener` import, so tests fake `internal_translate.build_opener` (or `fetch_bounded`) and the worker's `build_opener` separately.
- `same_host_https` compares `urlsplit(url).hostname == host` exactly. `normalize_host` strips a trailing dot and `urlsplit` does not, so the host given to `SameHostRedirectHandler` for media must be the raw `urlsplit` hostname, or same-host redirects get refused.
- `SameHostRedirectHandler` logs refused redirects with the `[translate]` prefix, so worker logs mix that prefix in.

**Risk:** None for B1's code, as long as this file is not edited. Its test group re-runs on the `subtitles.py` and `server_config.py` changes.
</impact>
<impact path="engine/server/api/handlers/internal_translate.py" element="handle_internal_translate / _cached_cues / _store_cues (lines 198-257): behaviour change with no code change">
**What changes:** No code change, but what the route serves changes.
- A whisper `ready` row is served through `_cached_cues`, so the Translate overlay shows Whisper cues for any video the worker finished. Read literally, this contradicts the requirement "Nothing on the website changes"; the operator should know and the docs should say it.
- For a `queued`/`running` key, every view still runs `fetch_instance_track`. If the instance has gained an English track, `_store_cues` overwrites the job row (the takeover case).
- The module docstring (lines 3-5) says "Only ready is stored". That stays true of this route, not of the store.

**Risk:** Low. It is the intended reuse, but it is a visible change and must be documented.
</impact>
<impact path="engine/server/api/handlers/video.py" element="fetch_video_row() (line 25, imported by the worker); resolve_video_row() (line 264, behaviour mirrored)">
**What changes:** No code change. The worker calls `fetch_video_row(conn, id, host, error_threshold=VIDEO_ERROR_THRESHOLD)`, the value server.py passes.

**Behaviour the worker inherits:**
- It matches `video_id OR video_uuid` with `instance_domain = :host` exactly, so the host must go through `normalize_host` first, and a None host must be refused before the call (`:host IS NULL` would match any host).
- It selects `v.language`, so it needs a `whitelist.db` migrated by `migrate-whitelist.py`. Otherwise it raises `no such column`, which the worker must report as an error, not as "not found".
- `duration` is an INTEGER that may be NULL or stale. The early bound treats NULL as unknown and lets it pass.
- Importing the module pulls in `server_config`.

**Risk:** None for the existing callers (`/api/video`, `/api/video/refresh`, B1).
</impact>
<impact path="engine/server/data/moderation.py" element="normalize_host() (line 45), list_active_denied_hosts() (line 137), reused">
**What changes:** No code change.

**How the worker uses them:** `normalize_host` on the CLI host, on the row's `instance_domain` before the denylist check (as at internal_translate.py:245), and on media hosts. `list_active_denied_hosts` on the read-only whitelist connection; it tolerates a missing `instance_denylist` table.

**Behaviour to know:**
- `normalize_host` silently drops a port and userinfo, accepts IP literals (`[::1]` becomes `::1`), and adds `https://` to bare input. The refusals for IP literal, port and userinfo must therefore be separate checks on the raw `urlsplit` (`ipaddress.ip_address` on the hostname, `.port`, `.username`/`.password`), not inferred from `normalize_host`.
- It is part of the ANN id contract (comment at line 44) and must not be modified.

**Risk:** None, if used as is.
</impact>
<impact path="engine/server/data/moderation.py" element="purge_host_data() (line 194) and purge_similarity_for_host() (line 231); engine/server/db/jobs/instance-denylist-cli.py block --purge-now">
**What changes:** No code change. Neither purge touches `subtitles.db`, so blocking a host leaves its `queued` jobs and stored cues in place.

**Behaviour to know:** B1's route and the worker's claim-time re-check both consult the denylist before using a row, so nothing is served or generated for a denied host. A queued job for a host denied later ends `failed` at claim. Pruning stays out of scope.

**Risk:** Low. Worth one line in the docs.
</impact>
<impact path="engine/server/data/db.py" element="connect_readonly_db() (line 85), used by the worker and the CLI on whitelist.db">
**What changes:** No code change.

**Behaviour the worker inherits:**
- `mode=ro` with sqlite3's default 5 s busy timeout and no timeout parameter;
- the deadline progress handler, harmless outside `statement_deadline`;
- `OperationalError` on a missing file.

**Risk:**
- Writers of `whitelist.db`: the updater's merge (`engine/server/db/jobs/merge-staging-db.py:128`, `BEGIN IMMEDIATE`), `fetch-trending.py:113` and `/api/video` write-backs.
- Nothing in the tree sets WAL on `whitelist.db`; I could not read its header mode. In rollback mode, a claim-time re-check during a merge commit can hit "database is locked" after 5 s. Under "every other exception ends the job failed", that fails the key for good.
- Mitigation (recommended in step 4): `PRAGMA busy_timeout=30000` on the worker's connection (no change to `data/db.py`), and treat an `OperationalError` lock there as requeue-without-counting.
- Open per job or per CLI call, not for the process lifetime, so the worker never pins an inode that a migration or restore replaces.
</impact>
<impact path="engine/server/data/time.py" element="now_ms() (reused)">
**What changes:** No code change. It is the clock for `queued_at`, `started_at`, `finished_at`, `fetched_at` and `beat_at`.

**Behaviour to know:** The conditional updates key on `started_at` in ms. Two claims of one key in the same ms cannot happen with one worker under flock.

**Risk:** None.
</impact>
<impact path="engine/server/db/jobs/translate-worker.py" element="new script: module layout, imports, argparse with enqueue and run subcommands">
**What changes:** A new file.

**Templates:**
- The closer template for path setup and subcommands is `engine/server/db/jobs/instance-denylist-cli.py`, not `updater-worker.py`. It puts both `server_dir` and `api_dir` on `sys.path` at module top (lines 12-18), imports `server_config` at module level (line 20), and uses `add_subparsers(dest="command", required=True, title="commands")` (line 79) with `formatter_class` passed to each `add_parser`. `channel-moderation-cli.py:44` does the same.
- This corrects the previous inventory's claim that subparsers are new among the job scripts.
- From `updater-worker.py` it takes `setup_logging` (line 317, stdout plus FileHandler; a default log under `engine/server/db/` is covered by `.gitignore` `*.log`) and `CompactHelpFormatter` (`scripts/cli_format.py:8`).

**Import discipline:**
- numpy, faster-whisper, CTranslate2 and the ctypes preload of the `nvidia/cublas/lib` and `nvidia/cudnn/lib` wheels are imported only on the `run` model or VAD path.
- So `enqueue` and in-process tests can load the module under pytest's Python 3.14.7, which has no Engine packages.
- The hyphenated name means tests load it with `importlib.util.spec_from_file_location`, as `tests/active/test_host_normalisation.py:79` and `test_updater_worker.py:72` do.

**Risk:** New file, so no regression in existing behaviour.
</impact>
<impact path="engine/server/db/jobs/translate-worker.py" element="run start-up order: flock, then recovery, then heartbeat thread, then loop (new from step 4 pass 2)">
**What changes:** The plan names the flock and the recovery but not their order.
- Recovery must run only after `fcntl.flock(LOCK_EX | LOCK_NB)` succeeds on the lock file. The pattern is `acquire_deploy_lock` at `updater-worker.py:467-491`, opened `O_RDONLY | O_CREAT`.
- `enqueue` must never run recovery.
- Otherwise a second `run`, started by hand or by a stray unit, moves the live worker's `running` row to `queued`, or to `failed` when `attempts` ≥ 2. The live worker then reads `rowcount == 0` and logs a false takeover.
- A second `run` that fails to take the lock must exit non-zero without writing anything, the heartbeat included.

**Depends on it:** the AC1 recovery semantics, plan 50's heartbeat freshness (a refused second process must not beat), and the lock-file name (see the `.gitignore` entry).

**Risk:** Medium. A wrong order corrupts live job state silently. It needs a test: a second `run` against a held lock leaves the `running` row and the heartbeat untouched.
</impact>
<impact path="engine/server/db/jobs/translate-worker.py" element="media URL check and file picker over files[] and streamingPlaylists[].files[]">
**What changes:** New logic.
- Keep a `fileUrl` only when it is https, its hostname is not an IP literal, and it has no explicit port and no userinfo. Take the smallest by declared `size`; files without a size sort last.

**Gaps found:**
- **Audio (from my knowledge of the PeerTube API, not from the tree).** PeerTube 7 can split HLS into audio-only and video-only files, and VideoFile objects carry `hasAudio`/`hasVideo`. A small video-only file would be picked, ffmpeg would fail, and the key would be failed for good. Drop candidates whose `hasAudio` is explicitly false, and keep files that lack the field (older versions omit it). Add a split-stream fixture.
- **Media host vs R4 (open conflict raised in step 4).** The plan accepts any https host named in the JSON. R4 (plan 49 line 129) and plan 18's R2 (line 115) say "only the whitelisted host". The operator's AC5 decision in the requirements allows a different host. The plan text and both risk lists must be reconciled.
- **Redirects to a CDN (uncertain).** An instance that serves `fileUrl` on its own host and redirects to object storage would be refused by `SameHostRedirectHandler`, which ends the job `failed`.
- **Trailing dot.** The host given to the redirect handler must be the raw `urlsplit` hostname (see the internal_translate entry).

**Risk:** Medium, because a wrong pick fails a key permanently.
</impact>
<impact path="engine/server/db/jobs/translate-worker.py" element="download and ffmpeg pipe: build_opener(SameHostRedirectHandler(media_host)), byte cap, feeder and reader threads, PCM buffer">
**What changes:** New logic around `subprocess.Popen(["ffmpeg", "-i", "pipe:0", "-f", "s16le", "-ac", "1", "-ar", "16000", "pipe:1"])`.

**External binary:** ffmpeg is new; nothing in the repo uses it today. Check with `shutil.which` at `run` start and fail with a clear message. I could not check whether `/usr/bin/ffmpeg` exists on this machine, because the sandbox is confined to the project.

**Hazards:**
- Feeder and reader must close ffmpeg's stdin and drain stdout and stderr on every exit path (cap exceeded, socket stall, takeover, SIGTERM). Otherwise ffmpeg or a thread hangs.
- stderr must be drained or sent to DEVNULL/a bounded buffer, or ffmpeg blocks on a full pipe.
- Counting decoded samples against `SUBTITLE_MAX_DURATION` must abort the pipe, not merely mark the job.
- The socket timeout is the only stall bound; there is no whole-job deadline.
- A non-faststart MP4 fails in ffmpeg; this is accepted.

**Risk:** Medium. Leaks here hang the single worker, and the heartbeat thread keeps beating while it hangs, so plan 50 would see "available".
</impact>
<impact path="engine/server/db/jobs/translate-worker.py" element="VAD chunker, transcribe seam, cue assembly, lazy model load, idle unload, OOM handling">
**What changes:** New logic.

**Implementation notes:**
- `faster_whisper.vad.get_speech_timestamps` needs float32 numpy audio.
- `model.transcribe()` returns a lazy generator. OOM and other CUDA errors surface while iterating segments, so the try block must cover the iteration.
- Language detection on the first chunk only.

**Cues:**
- Whisper segment text usually starts with a space, so strip it, and drop empty texts as `parse_webvtt` does.
- Times are rounded to 3 decimals and must be finite (`allow_nan=False`).
- Cue order must hold across chunks for B1's sort assumption. The Client and the frontend re-sort anyway (`client/frontend/src/data/translate.ts:72`).

**Model lifecycle:**
- `WhisperModel("medium", device="cuda", compute_type="int8_float16")` after the ctypes preload.
- Unload with del plus gc after 5 minutes idle.
- An OOM `RuntimeError` fails the job and unloads the model.

**Risk:** New code. The empty-text and NaN rules protect B1's readers.
</impact>
<impact path="engine/server/db/jobs/translate-worker.py" element="stop path: SIGTERM handling and the systemd TimeoutStopSec window (new from step 4 pass 2)">
**What changes:** The plan has no stop handling. Without it, every `systemctl stop`/`restart`, deploy or reboot mid-job looks like a crash at the next start and uses up AC1's single retry.

**Recommended handling (step 4, recommendation 3):**
- A SIGTERM handler sets a stop flag that the feeder, the reader and the chunk loop check.
- One conditional requeue-without-counting runs, ffmpeg is closed, and the worker exits.
- Python runs signal handlers on the main thread only, between bytecodes. A main thread blocked inside one `transcribe` chunk responds only after that chunk, which is seconds on the GPU.
- The installer's unit shape uses `TimeoutStopSec=20` (`engine/install-engine-service.sh:133`). If the worker's unit copies it, the stop work must fit inside 20 s, or SIGKILL turns it back into a crash.

**Risk:** Medium. Undocumented, it makes ordinary operations fail keys permanently.
</impact>
<impact path="engine/server/db/jobs/translate-worker.py" element="enqueue subcommand: resolve, bounds, store call, output line and exit codes">
**What changes:** New logic.
- `normalize_host`, refusing None; a read-only whitelist connection; `fetch_video_row`; the denylist; the early duration bound.
- Then `connect_subtitles_db` plus `ensure_subtitles_schema` plus enqueue.
- One output line and a distinct exit code per outcome.

**Behaviour to know:**
- The CLI itself writes: it may switch the file to WAL and run the migration on a fresh file. Run as a different OS user than the Engine, it could create `subtitles.db` or its `-wal`/`-shm` owned by that user, which the Engine then cannot write. The docs should say to run it as the service user.
- It must not take the worker's flock and must not run recovery.

**Risk:** Low to medium. File ownership is an operational trap.
</impact>
<impact path="engine/server/db/jobs/instance-denylist-cli.py" element="pattern source only (sys.path setup lines 12-18, subparsers line 79)">
**What changes:** No code change. It is the in-repo precedent the new script should follow for `api_dir` on `sys.path` at module top and for subcommands. `channel-moderation-cli.py:44` is a second precedent.

**Risk:** None.
</impact>
<impact path="engine/server/db/jobs/updater-worker.py" element="pattern source (setup_logging line 317, acquire_deploy_lock lines 467-491); runtime coexistence">
**What changes:** No code change. The plan says updater-worker uses a pid-file lock. It uses both: `single_run_lock` (342-377) is a pid file, and `acquire_deploy_lock` (467-491) is an `fcntl.flock`, which is the one to copy.

**Runtime interaction:** The updater stops and starts only the Engine, so the worker keeps running through the weekly merge. The only exposure is the `whitelist.db` lock window (see the `connect_readonly_db` entry).

**Risk:** Low.
</impact>
<impact path="engine/server/scripts/cli_format.py" element="CompactHelpFormatter (line 8, reused)">
**What changes:** No code change. The top-level parser and each subparser should pass it explicitly; argparse subparsers do not inherit `formatter_class`.

**Risk:** None.
</impact>
<impact path="client/backend/lib/engine_api_client.py" element="fetch_translate() (line 158) and _is_seconds() (line 153), unchanged">
**What changes:** No code change. Through B1's route it now receives whisper `ready` cues.
- It requires every cue's `start`/`end` to be a finite number and `text` a string; one bad cue fails the whole answer.
- There is no response-size cap. A 60-minute translation is about 48 KB, well inside the 20 s timeout.

**Risk:** Low, provided the worker writes finite numbers and string text.
</impact>
<impact path="client/backend/server.py" element="/api/translate route (lines 113, 461, 1069-1077), unchanged">
**What changes:** No code change. It relays whisper `ready` cues to profile holders exactly as it relays instance cues. A queued or running video still answers `none` until plan 50.

**Risk:** None.
</impact>
<impact path="client/frontend/src/data/translate.ts" element="fetchTranslate() validator (lines 62-72), unchanged">
**What changes:** No code change. It accepts only `ready` with finite numbers and re-sorts by start, then end. Whisper cues reach it once a job finishes.

**Risk:** Low. It relies on the same finite-number rule.
</impact>
<impact path="client/frontend/src/pages/video-page/translate.ts" element="overlay cue list and binary search, unchanged">
**What changes:** No code change. A finished 60-minute whisper job is on the order of a thousand cues, against a typical instance track that is often shorter. The binary search by start handles that. Whisper segments can overlap slightly at chunk joins; the overlay shows one cue containing the position, as with instance tracks.

**Risk:** Low.
</impact>
<impact path="tests/active/test_internal_translate.py" element="B1's whole suite (must pass unchanged)">
**What changes:** Nothing may change in this file.

**What it exercises:**
- `connect_subtitles_db`/`ensure_subtitles_schema` through `_subtitles_db` (484-490);
- read-only reads through `_stored` (504-510);
- the read-only read after an Engine start (646);
- the Engine start at 623-661, with `DEFAULT_SUBTITLES_DB_PATH` overridden to a tmp file.

**What to watch:**
- `mode=ro` opens of a WAL file after the writer was collected (562/564, 585/587).
- The in-process tests run under Python 3.14.7.
- The `tables` set at 648 gains `translate_worker_heartbeat`, but the assertion is `"subtitles" in tables`.
- `_stored` names its columns, so the new columns are invisible to it.
- The test's own docstring (lines 1, 26) says it "stores only a `ready` track". That describes the route, so it stays true.

**Risk:** Medium. It is the regression oracle for every `subtitles.py` change, and read-only WAL is the main unknown.
</impact>
<impact path="tests/active/conftest.py" element="session engine fixture (line 169), ENGINE_PY (38), ENGINE_START_LOCK (108)">
**What changes:** No code change.
- The session Engine opens the repo's own `subtitles.db` (no override, lines 183-185), so the first test run after the build migrates the developer's real file and switches it to WAL.
- Starts are serialised under `ENGINE_START_LOCK` only up to healthy.
- New tests that need numpy or faster-whisper (VAD, the model smoke test) must run as subprocesses under `ENGINE_PY` (`engine/.pixi/envs/default/bin/python`), since pytest runs on 3.14.7.

**Risk:** Medium. A migration bug locks or damages the shared developer file and fails every Engine-backed test.
</impact>
<impact path="tests/active/test_server_config.py" element="variant Engine starts (lines 262-265 and 331-333)">
**What changes:** No code change. These Engines also open the repo `subtitles.db` and now run the WAL pragma and the IMMEDIATE migration, possibly alongside the session Engine and test_random_cache.py's Engines. (Correction: the second Popen is at line 333, not 331.)

**Risk:** Low to medium. They are additional concurrent openers of one file.
</impact>
<impact path="tests/active/test_random_cache.py" element="CACHE_VARIANT_RUNNER Engine starts (lines 297-300) and the deliberate concurrent starts (784-811)">
**What changes:** No code change.
- These Engines override only the random-cache path (line 289), so they open the repo `subtitles.db`. Lines 784-811 start several at once, which exercises the concurrent IMMEDIATE migration for real.
- Its `_names(...)` directory listings (236, 412-758) look only at `tmp_path / "db"`, where no subtitles files appear, so the new WAL sidecars do not affect them. The same holds for `tests/active/test_db.py:199/227`.

**Risk:** Low to medium.
</impact>
<impact path="tests/active/test_translate_worker.py" element="new test file (name to be fixed in step 4)">
**What changes:** New tests:
- a standalone read-only-WAL check, under the pytest Python and `ENGINE_PY`;
- the schema upgrade of a B1-shaped file, including two concurrent upgrades;
- WAL is set;
- enqueue: idempotent in every state, never overwrites, the cap result;
- claim order;
- recovery, including that it never runs without the flock;
- flock exclusivity (a second `run` exits and writes nothing);
- requeue on SIGTERM, if adopted;
- CLI lines and exit codes against a tmp `whitelist.db` built like `_whitelist` (`test_internal_translate.py:463`);
- media URL refusals: http, IPv4/IPv6 literals, port, userinfo, off-host redirect;
- the `hasAudio` filter;
- the byte cap, by Content-Length and by streaming;
- the duration bounds, from JSON and from decoded samples;
- real ffmpeg on a generated clip;
- chunk offsets and per-chunk rewrites;
- B1 takeover (`rowcount` 0);
- `already_english` and "no speech";
- OOM through the seam;
- the heartbeat cadence;
- the two-process R8 test.

**Doubles:**
- Define its own instance double, patched at `internal_translate.fetch_bounded` or `build_opener`, recording captions, track and video JSON in order.
- Define a media double at the worker's `build_opener`.
- Do not import or widen B1's `RecordingInstance`.

**Risk:**
- Timing flakiness in the R8 and heartbeat tests.
- Use `subprocess` with explicit scripts, not multiprocessing: Python 3.14's default start method on Linux is `forkserver`.
- ffmpeg must exist where the suite runs, so the test needs a clear fail-or-skip rule.
- Tests must never touch the repo's real `subtitles.db`.
</impact>
<impact path="tests/config.json" element="test_groups: new entry; existing test_internal_translate.py group (lines 397-406)">
**What changes:** A new group for the new test file, listing:
- `engine/server/db/jobs/translate-worker.py`
- `engine/server/data/subtitles.py`
- `engine/server/api/handlers/internal_translate.py`
- `engine/server/api/handlers/video.py`
- `engine/server/data/moderation.py`
- `engine/server/data/db.py`
- `engine/server/api/server_config.py`
- `engine/server/scripts/cli_format.py`

The existing B1 group already lists `subtitles.py` and `server_config.py`, so it re-runs.

**Risk:** If the group is missing, the runner never schedules the new tests.
</impact>
<impact path="tests/active/test_static_page_visit_logs.py" element="_runbook() (line 97) executes every ```bash fence under DEPLOYMENT.md's '### Follow an About visit' (line 252)">
**What changes:** No code change. It constrains the DEPLOYMENT.md edit:
- New worker sections and their ```bash fences must not land between `### Follow an About visit` and the next heading, or the test executes them.
- New fences must not precede the first ```nginx fence after the sites-available line (docstring, line 9).

**Risk:** Low, but a misplaced edit fails an unrelated test.
</impact>
<impact path=".gitignore" element="runtime-file ignore rules (lines 10-23)">
**What changes:** The worker's flock file is not covered: `*.db*` patterns cover only `-journal`, `-shm`, `-wal`, `.building` and `.bak*`. Add `engine/server/db/translate-worker.lock` next to line 21 (`engine/server/db/engine-deploy.lock`), with a comment in the same style. The WAL sidecars (13-14) and `*.log` (3) are already covered.

**Risk:** Low. Without the line, the file shows in `git status`, which `scripts/worktree-setup.sh:51-53` warns about.
</impact>
<impact path="engine/pixi.toml" element="Engine environment engine/.pixi (pip-filled; the manifest pins only python 3.12 and pip)">
**What changes:** No manifest change. faster-whisper 1.2.1 and ctranslate2 4.8.2 are pip-installed into `engine/.pixi/envs/default`. They bring onnxruntime (protobuf, flatbuffers, coloredlogs, and a sympy requirement against `requirements.txt:39`'s pin of 1.13.1), `av` (PyAV with bundled FFmpeg libraries) and possibly newer tokenizers or huggingface-hub.

**Depends on it:**
- the Engine's query encoder (sentence-transformers/transformers);
- `build-video-embeddings.py` (torch);
- every test run through `ENGINE_PY`;
- every worktree, since `scripts/worktree-setup.sh:34` symlinks main's `engine/.pixi`.

**Uncertain:**
- whether CTranslate2 4.8.2 runs on cuBLAS 12.1.3.1 and cuDNN 9.1.0.70;
- whether a later `pixi install` reconciles away pip-installed packages.

I could not list the env's site-packages; it is not visible to search.

**Risk:** High.
</impact>
<impact path="engine/server/requirements.txt" element="venv-route dependency list">
**What changes:** Possibly none. DEPLOYMENT.md sections 0 and 2 (lines 18-22, 92-106) say the units run `<project>/venv/bin/python3`, either a real venv from this file or a symlink to the pixi python. On a real-venv host the worker has no faster-whisper.

**Options (step 4 recommended the second):**
- add the packages here, which forces them onto GPU-less Engine hosts;
- document a separate pip step into whichever interpreter `venv/bin/python3` names.

**Risk:** Medium. A deploy-time `ModuleNotFoundError: faster_whisper` that a Triage row should name.
</impact>
<impact path="engine/install-engine-service.sh" element="engine_unit_text() unit shape (lines 119-137); also scripts/install-service.sh, scripts/uninstall-service.sh, engine/uninstall-engine-service.sh">
**What changes:** Nothing, per the plan. The worker's unit is hand-written from DEPLOYMENT.md, so the central installer and the uninstallers neither install nor remove it.

**The hand-written unit should mirror lines 125-133:**
- `Environment=PYTHONUNBUFFERED=1`;
- `EnvironmentFile=-<project>/.env.bridge` (needed only because `server_config` reads it);
- `Restart=on-failure`;
- a `TimeoutStopSec` that covers the stop path.

**And add:**
- `CUDA_VISIBLE_DEVICES=<3070 UUID>`;
- `HOME`/`HF_HOME` for the model cache;
- the same `User=` as the Engine, so file ownership of `subtitles.db` and its sidecars matches.

**Risk:** Low. It is an operational gap the docs must state.
</impact>
<impact path="scripts/worktree-setup.sh" element="worktree runtime links (lines 26-36)">
**What changes:** No code change.
- `whitelist.db` is a symlink to main's, so a worker or CLI run in a worktree reads main's catalogue.
- `subtitles.db` is neither linked nor copied, so a worktree's Engine or worker creates its own.
- `engine/.pixi` is shared, so the pip install changes every lane at once.

**Risk:** Low.
</impact>
<impact path="docs/project/plans/50-translate-generation-in-page.md" element="interfaces it consumes (lines 7, 27-30, 49)">
**What changes:** No edit required. Plan 50 depends on:
- the enqueue function and its result;
- the heartbeat table and its age;
- the job states;
- reading cues while `running`, with an `after` position.

This build fixes those names. The `running` reader does not exist after it.

**Risk:** A mismatch if the names drift. Record them in `engine/server/README.md`.
</impact>
<impact path="docs/project/plans/49-translate-whisper-worker.md" element="R4 (line 129) and close-out (line 114)">
**What changes:**
- R4 says "Only the whitelisted host". The plan, and the operator's AC5 media-URL decision recorded in the requirements, allow any https host passing the lexical checks.
- This is the open conflict step 4 raised. Once it is settled, R4 must be reworded to match, and the plan archived or marked delivered per `docs/project/issue-tracker.md`.

**Risk:** Low. A stale security statement.
</impact>
<impact path="docs/project/plans/18-english-subtitles.md" element="R2 (line 115) and the close-out term 'Subtitle job' (line 101)">
**What changes:**
- R2 makes the same "Only whitelisted hosts" promise as plan 49's R4, so it is part of the same conflict.
- Line 101 names the glossary term "Subtitle job"; the settled name is **Translate job**.
- Both should be annotated or updated when plan 49 closes.

**Risk:** Low.
</impact>
</impacts>

## Documentation to update

- [x] `DEPLOYMENT.md` - updated: I added the translate worker to `DEPLOYMENT.md`: its dependencies in section 0, the `subtitles.db` entry in section 1, the hand-written unit and its commands in section 2, eight Triage rows, and its outbound 443 in the firewall section. Every flag, output line, exit code, constant and stop-path timing in it was checked against `translate-worker.py`, `subtitles.py` and `server_config.py`, not taken from the change reports.
- [x] `CONTEXT.md` - updated: I added the glossary term **Translate job** to `CONTEXT.md` and amended **Translate state** and **Instance caption track** to match the store as the code has it.
- [x] `engine/server/README.md` - updated: I updated `engine/server/README.md` so that `subtitles.db` is described as a shared, WAL-mode store holding job rows, and added a section on the translate worker and its store contract.
- [x] `engine/server/db/jobs/docs/TRANSLATE_WORKER.md` - updated: I wrote the new `engine/server/db/jobs/docs/TRANSLATE_WORKER.md`. It explains how the translate worker behaves, and its layout follows `UPDATER_WORKER.md`.
- [x] `DATA_BUILD.md` - updated: The `subtitles.db` paragraph in `DATA_BUILD.md` now says the translate worker and its `enqueue` command write the file too, and that it runs in WAL mode.
- [x] `README.md` - updated: README.md Components: added the translate worker (`engine/server/db/jobs/translate-worker.py`) as its own component bullet.
- [x] `client/README.md` - updated: I updated the `/api/translate` bullet in `client/README.md` so it names both places the relayed `ready` cues can come from.
- [x] `docs/project/roadmap.md` - updated: I updated roadmap line 60 (F11-M2). Plan 49's Whisper translate worker is now listed under Delivered and plan 50 under Remaining, and the line is still PARTIAL.
- [x] `docs/project/plans/49-translate-whisper-worker.md` - updated: Reworded R4 to match the media-host rule that shipped, and added an "Outstanding" section listing the two parts not yet done. On your instruction, the plan stays open in `docs/project/plans/`.
- [x] `docs/project/plans/18-english-subtitles.md` - updated: Updated plan 18's R2 to match the media-host decision that was built, and changed the close-out glossary term to **Translate job**.
- [x] `docs/project/plans/50-translate-generation-in-page.md` - out of scope: Not on the checklist; I checked it because it consumes this build's interfaces. It describes intent (enqueue, heartbeat, per-chunk cues, a running reader), not current state, and none of its sentences has become false. The missing `running` reader is already its own work. The names it should consume are recorded in `engine/server/README.md` instead.

## Implementation plan

## Draft implementation: plan 49, the translate worker

I read these before drafting: `engine/server/data/subtitles.py` (all of it), `engine/server/api/handlers/internal_translate.py` (all of it), `handlers/video.py:1-80`, `data/db.py:80-95`, `server_config.py:405-434`, `instance-denylist-cli.py` (all of it), `updater-worker.py:1-60` and `310-494`, and `scripts/cli_format.py`. All code below follows the style of the file it lands in: one-line docstrings, plain functions taking `conn`, the time passed in, and `logging` with a bracketed prefix.

### What the build has to test (derived first)

| Area | What has to be shown |
|---|---|
| Store | A B1-shaped file upgrades in place and old rows read the same. Two concurrent upgrades both succeed. The file is in WAL mode. A `mode=ro` open after the last writer has closed works under pytest's 3.14 and under `ENGINE_PY` 3.12. |
| Queue | Enqueue is idempotent for each of the six states and never overwrites. The cap gives a distinct result. Claim takes the oldest first. Recovery requeues once and fails on the second find. Requeue-without-counting works. Every conditional update returns False after a B1 takeover. |
| Process | A second `run` against a held lock exits 6 and writes nothing, heartbeat included. The heartbeat beats on a 5 s cadence and stops when the main loop stalls. SIGTERM mid-job requeues without counting. |
| CLI | One line and one exit code for each outcome, against a tmp `whitelist.db`. Not found, denied host, stored-duration bound, cap, exists. |
| Bounds | Media URL: http, IPv4/IPv6 literals, numeric/hex/single-label hosts, port and userinfo are refused. An off-host redirect is refused. `hasAudio: false` is skipped. The smallest file wins. Byte cap by Content-Length and by streaming. Duration by JSON, unknown duration, and duration by decoded samples. |
| Pipeline | Real ffmpeg decodes a generated clip through stdin. Chunk offsets are correct. The cue rows are rewritten after each chunk. Chunks without speech are skipped. Outcomes covered: `already_english`, "no speech detected", OOM through the seam (fails the job, unloads, the next job runs), and the AC3.1 instance-track path. |
| Concurrency (R8) | A two-process Engine-plus-worker run against one file sees no "database is locked" and ends with consistent rows. |
| GPU (manual evidence) | The environment gate's tiny `translate`. One real job on a long non-English video with an `nvidia-smi` sampler, recording peak VRAM ≤ 3,072 MiB. |

### Module map

| File | Change |
|---|---|
| `engine/server/data/subtitles.py` | WAL in `connect_subtitles_db`. IMMEDIATE migration in `ensure_subtitles_schema`. Ten new store functions, all stdlib. Docstring and comment updates. |
| `engine/server/api/server_config.py` | Four constants. The comment on `DEFAULT_SUBTITLES_DB_PATH` is updated. |
| `engine/server/db/jobs/translate-worker.py` | New. `enqueue` and `run` subcommands. numpy, faster-whisper and the CUDA wheels are imported only inside `WhisperRunner`. |
| `tests/active/test_translate_worker.py` | New. Covers the table above. |
| `tests/config.json` | New group listing the eight files named in the inventory. |
| `.gitignore` | `engine/server/db/translate-worker.lock` next to line 21. |
| Docs | As settled in the documentation list. Nothing extra. |

B1's `internal_translate.py`, `video.py`, `moderation.py` and `db.py` are not edited.

---

### `engine/server/data/subtitles.py`

**Module docstring, replacing lines 1-4:**
```python
"""Translated caption tracks and translate jobs in engine/server/db/subtitles.db, one row per (video_id, instance_domain, target_language).

B1's route upserts state 'ready' with source 'instance'. Plan 49's translate worker adds the job states 'queued', 'running', 'failed' and 'already_english' and the source 'whisper', with job columns added in place by ensure_subtitles_schema; state and source stay plain TEXT. A running job's cues are a whole-cues_json rewrite after each chunk, so fetch_ready_subtitles reads a ready row of either source unchanged. The file is in WAL mode: both blue/green Engines, the translate worker (claim, per-chunk rewrites, a heartbeat every 5 s) and its enqueue CLI write it.
"""
```

**Imports:** add `from contextlib import contextmanager`.

**Constants:**
```python
# Longer than sqlite3's 5 s default: several Engines may migrate the file at once, the first opener switches it to WAL, and the blue/green Engines, the translate worker (claim, per-chunk rewrites, a heartbeat every 5 s) and its enqueue CLI all write it.
SUBTITLES_BUSY_TIMEOUT_SECONDS = 30.0
SOURCE_WHISPER = "whisper"
# A running row found at worker start after this many claims is failed instead of requeued: one retry after a crash (AC1).
MAX_CLAIMS = 2
RECOVERY_ERROR = "worker stopped while running twice"
# Plan 49's job columns, added in place to a B1 file; attempts needs its default because SQLite refuses a NOT NULL add without one.
JOB_COLUMNS = (("queued_at", "INTEGER"), ("started_at", "INTEGER"), ("finished_at", "INTEGER"), ("error", "TEXT"), ("detected_language", "TEXT"), ("attempts", "INTEGER NOT NULL DEFAULT 0"))
_KEY = "video_id = ? AND instance_domain = ? AND target_language = ?"
```

**Connection and transactions:**
```python
def connect_subtitles_db(path: Path) -> sqlite3.Connection:
    """Open or create the subtitles database in WAL mode; no deadline handler, so statement_deadline does not bound it."""
    conn = sqlite3.connect(path.as_posix(), check_same_thread=False, timeout=SUBTITLES_BUSY_TIMEOUT_SECONDS)
    conn.row_factory = sqlite3.Row
    # Persistent in the file, so a no-op for every opener after the first; the first switch waits out other openers on the busy timeout.
    conn.execute("PRAGMA journal_mode=WAL").fetchall()
    return conn


@contextmanager
def _immediate(conn: sqlite3.Connection):
    """One BEGIN IMMEDIATE transaction, rolled back on any error; in WAL a deferred read-then-write fails at once when another writer committed after its read, so every read-then-write here takes the write lock first."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
```
Python's legacy transaction control (the default on 3.12 and 3.14) never adds its own BEGIN once `in_transaction` is true, and never begins a transaction for DDL or PRAGMA. So the explicit BEGIN is the only transaction boundary. `executescript` is not used, because it commits first.

**Schema:**
```python
def ensure_subtitles_schema(conn: sqlite3.Connection) -> None:
    """Create the subtitles and heartbeat tables and add the job columns, in one IMMEDIATE transaction so concurrent openers never race into a duplicate column."""
    with _immediate(conn):
        conn.execute(<B1's CREATE TABLE IF NOT EXISTS subtitles, unchanged>)
        present = {row[1] for row in conn.execute("PRAGMA table_info(subtitles)")}
        for name, declaration in JOB_COLUMNS:
            if name not in present:
                conn.execute(f"ALTER TABLE subtitles ADD COLUMN {name} {declaration}")
        conn.execute("CREATE INDEX IF NOT EXISTS subtitles_state_queued_at ON subtitles (state, queued_at)")
        conn.execute("CREATE TABLE IF NOT EXISTS translate_worker_heartbeat (id INTEGER PRIMARY KEY CHECK (id = 1), beat_at INTEGER NOT NULL, pid INTEGER NOT NULL)")
```
`row[1]` (the column name) is used instead of `row["name"]`, so the function works under any row factory.

**B1 functions:**
- `fetch_ready_subtitles` is unchanged.
- `store_ready_subtitles` code is unchanged. Only its docstring changes, to: "Upsert a ready row. A concurrent miss on the same key writes the same row twice, harmlessly. Against a job row it ends the job: a running job's conditional updates then match nothing, and the job columns stay behind, so read state first."

**New functions** (plan 50 uses these names and return shapes):
```python
def _cues_text(cues: list[dict[str, Any]]) -> str:
    """Compact JSON for cues_json; allow_nan=False, so a non-finite time raises here instead of failing the Client's _is_seconds later."""
    return json.dumps(cues, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def enqueue_translate_job(conn, video_id, instance_domain, target_language, cap: int, queued_at: int) -> tuple[str, str | None]:
    """Queue a whisper job: ("queued", "queued"); ("exists", <state>) for a key in any state; ("cap", None) when cap jobs are already queued. Never overwrites a row."""
    with _immediate(conn):
        row = conn.execute(f"SELECT state FROM subtitles WHERE {_KEY}", (video_id, instance_domain, target_language)).fetchone()
        if row is not None:
            return "exists", row[0]
        (queued,) = conn.execute("SELECT COUNT(*) FROM subtitles WHERE state = 'queued'").fetchone()
        if queued >= cap:
            return "cap", None
        conn.execute(
            "INSERT INTO subtitles (video_id, instance_domain, target_language, state, source, fetched_at, queued_at, attempts) VALUES (?, ?, ?, 'queued', ?, ?, ?, 0) ON CONFLICT(video_id, instance_domain, target_language) DO NOTHING",
            (video_id, instance_domain, target_language, SOURCE_WHISPER, queued_at, queued_at),
        )
    return "queued", "queued"


def claim_translate_job(conn, target_language, started_at: int) -> sqlite3.Row | None:
    """Flip the oldest queued job to running, in one short transaction; its (video_id, instance_domain, started_at, attempts), or None."""
    with _immediate(conn):
        row = conn.execute("SELECT video_id, instance_domain FROM subtitles WHERE state = 'queued' AND target_language = ? ORDER BY queued_at, rowid LIMIT 1", (target_language,)).fetchone()
        if row is None:
            return None
        key = (row[0], row[1], target_language)
        conn.execute(f"UPDATE subtitles SET state = 'running', started_at = ?, attempts = attempts + 1 WHERE {_KEY}", (started_at, *key))
        return conn.execute(f"SELECT video_id, instance_domain, started_at, attempts FROM subtitles WHERE {_KEY}", key).fetchone()


def recover_translate_jobs(conn, finished_at: int) -> tuple[int, int]:
    """Run at worker start, and only under its flock: requeue a running row once, fail it when found running a second time; (requeued, failed)."""
    with _immediate(conn):
        failed = conn.execute("UPDATE subtitles SET state = 'failed', error = ?, finished_at = ? WHERE state = 'running' AND attempts >= ?", (RECOVERY_ERROR, finished_at, MAX_CLAIMS)).rowcount
        requeued = conn.execute("UPDATE subtitles SET state = 'queued' WHERE state = 'running'").rowcount
    return requeued, failed


def _update_claim(conn, video_id, instance_domain, target_language, started_at: int, assignments: str, values: tuple) -> bool:
    """One conditional UPDATE on this claim's running row; False when B1's route took the row over (rowcount 0)."""
    with conn:
        cursor = conn.execute(f"UPDATE subtitles SET {assignments} WHERE {_KEY} AND state = 'running' AND started_at = ?", (*values, video_id, instance_domain, target_language, started_at))
    return cursor.rowcount == 1


def requeue_translate_job(conn, video_id, instance_domain, target_language, started_at: int) -> bool:
    """Put a running job back without spending its claim (SIGTERM, a whitelist.db lock); queued_at is kept, so it stays at the head."""
    return _update_claim(conn, video_id, instance_domain, target_language, started_at, "state = 'queued', attempts = attempts - 1", ())


def store_running_cues(conn, video_id, instance_domain, target_language, started_at: int, cues, detected_language: str) -> bool:
    """Rewrite a running job's whole cues_json after a chunk (AC4)."""
    return _update_claim(conn, video_id, instance_domain, target_language, started_at, "cues_json = ?, detected_language = ?", (_cues_text(cues), detected_language))


def finish_translate_ready(conn, video_id, instance_domain, target_language, started_at: int, cues, finished_at: int) -> bool:
    """End a job ready with its full, start-sorted cue list; fetched_at is set so B1's reader sees a normal ready row."""
    return _update_claim(conn, video_id, instance_domain, target_language, started_at, "state = 'ready', cues_json = ?, fetched_at = ?, finished_at = ?", (_cues_text(cues), finished_at, finished_at))


def finish_translate_already_english(conn, video_id, instance_domain, target_language, started_at: int, detected_language: str, finished_at: int) -> bool:
    """End a job already_english; it never held cues."""
    return _update_claim(conn, video_id, instance_domain, target_language, started_at, "state = 'already_english', detected_language = ?, cues_json = NULL, finished_at = ?", (detected_language, finished_at))


def finish_translate_failed(conn, video_id, instance_domain, target_language, started_at: int, error: str, finished_at: int) -> bool:
    """End a job failed with its error text; partial cues stay in cues_json, unread because only ready rows are served."""
    return _update_claim(conn, video_id, instance_domain, target_language, started_at, "state = 'failed', error = ?, finished_at = ?", (error, finished_at))


def mark_translate_finished(conn, video_id, instance_domain, target_language, started_at: int, finished_at: int) -> bool:
    """Stamp finished_at after AC3.1's store_ready_subtitles; matches on started_at, which B1's upsert never touches, so a B1 rewrite in between is tolerated."""
    with conn:
        cursor = conn.execute(f"UPDATE subtitles SET finished_at = ? WHERE {_KEY} AND state = 'ready' AND started_at = ?", (finished_at, video_id, instance_domain, target_language, started_at))
    return cursor.rowcount == 1


def write_translate_heartbeat(conn, beat_at: int, pid: int) -> None:
    """Upsert the worker's single heartbeat row."""
    with conn:
        conn.execute("INSERT INTO translate_worker_heartbeat (id, beat_at, pid) VALUES (1, ?, ?) ON CONFLICT(id) DO UPDATE SET beat_at = excluded.beat_at, pid = excluded.pid", (beat_at, pid))
```
In the real file, the parameters carry B1's type annotations (`conn: sqlite3.Connection`, `video_id: str`, …). They are shortened above only for space.

Plan 50 will also need a reader for a `running` row's cues. It does not exist after this build; it is noted in `engine/server/README.md` as plan 50's to add.

---

### `engine/server/api/server_config.py`, after line 420

```python
# Instance caption tracks served by /internal/translate, and the translate worker's jobs and heartbeat; created empty at first start, so a worktree gets its own.
DEFAULT_SUBTITLES_DB_PATH = "engine/server/db/subtitles.db"
# Longest video, in seconds, the translate worker transcribes; checked against the stored row, the live video JSON and the decoded audio.
SUBTITLE_MAX_DURATION = 3600
# Largest media download, in bytes, the translate worker reads; checked against Content-Length and while streaming.
SUBTITLE_MAX_BYTES = 1024 ** 3
# Most queued translate jobs at once; the enqueue CLI and plan 50's route refuse past it.
SUBTITLE_QUEUE_CAP = 50
# Longest audio chunk, in seconds, handed to Whisper; cut at the last silence before it, hard-cut at it otherwise (R2).
SUBTITLE_MAX_CHUNK_SECONDS = 30
```

---

### `engine/server/db/jobs/translate-worker.py` (new)

**Header and imports.** The layout follows `instance-denylist-cli.py`.
```python
#!/usr/bin/env python3
"""Translate worker (plan 49): English cues for whitelisted videos with Whisper's translate task, one queued job at a time, into subtitles.db.

enqueue --id --host resolves the video against whitelist.db the way B1 does and queues it. run is the service: flock, crash recovery, a heartbeat every 5 s, then claim -> instance track, or video JSON -> one download piped into ffmpeg's stdin -> silence-cut PCM chunks -> faster-whisper. numpy, faster_whisper and the CUDA wheels are imported only inside WhisperRunner, so enqueue and the Engine never need them.
"""
from __future__ import annotations

import argparse, fcntl, gc, http.client, ipaddress, json, logging, math, os, re, shutil, signal, sqlite3, subprocess, sys, threading, time   # one import per line in the file
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit
from urllib.request import Request, build_opener

script_dir = Path(__file__).resolve().parent
server_dir = script_dir.parents[1]
# ... the server_dir / api_dir sys.path block from instance-denylist-cli.py:12-18, verbatim

from scripts.cli_format import CompactHelpFormatter
from server_config import DEFAULT_DB_PATH, DEFAULT_SUBTITLES_DB_PATH, SUBTITLE_MAX_BYTES, SUBTITLE_MAX_CHUNK_SECONDS, SUBTITLE_MAX_DURATION, SUBTITLE_QUEUE_CAP, VIDEO_ERROR_THRESHOLD
from data.db import connect_readonly_db
from data.moderation import list_active_denied_hosts, normalize_host
from data.subtitles import (claim_translate_job, connect_subtitles_db, enqueue_translate_job, ensure_subtitles_schema, finish_translate_already_english, finish_translate_failed, finish_translate_ready, mark_translate_finished, recover_translate_jobs, requeue_translate_job, store_ready_subtitles, store_running_cues, write_translate_heartbeat)
from data.time import now_ms
# The module, not its names: fetch_bounded and fetch_instance_track are called as attributes, so a test that fakes internal_translate.build_opener or .fetch_bounded reaches the worker's calls too.
from handlers import internal_translate
from handlers.internal_translate import FETCH_DEADLINE_SECONDS, SOURCE_INSTANCE, TARGET_LANGUAGE, SameHostRedirectHandler
from handlers.video import fetch_video_row
```

**Constants:**
```python
SAMPLE_RATE = 16_000
BYTES_PER_SAMPLE = 2
MODEL_NAME = "medium"
COMPUTE_TYPE = "int8_float16"
HEARTBEAT_SECONDS = 5.0
POLL_SECONDS = 2.0
IDLE_UNLOAD_SECONDS = 300.0
# Far longer than one chunk on the GPU; a main loop silent this long stops the heartbeat, so plan 50 reads a hung worker as unavailable.
STALL_SECONDS = 600.0
TRANSIENT_BACKOFF_SECONDS = 30.0
# The only stall bound on the download; joins on stop fit inside the unit's TimeoutStopSec=60.
MEDIA_SOCKET_TIMEOUT_SECONDS = 15.0
READ_CHUNK_BYTES = 65_536
# A silence cut closer than this to the chunk start is not taken.
MIN_CHUNK_SECONDS = 5.0
# Cut-point VAD: shorter silences than faster-whisper's 2 s default count as gaps, so fewer chunks are hard-cut.
VAD_MIN_SILENCE_MS = 500
VAD_SPEECH_PAD_MS = 200
ERROR_TEXT_MAX = 1000
STDERR_TAIL_BYTES = 4096
FFMPEG_ARGS = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", "pipe:0", "-vn", "-f", "s16le", "-ac", "1", "-ar", str(SAMPLE_RATE), "pipe:1"]
# A DNS name's last label is letters or punycode, never digits or hex, so 127.1, 2130706433 and 0x7f.0x1 (which inet_aton resolves) are refused with the IP literals.
_TLD = re.compile(r"[a-z]{2,63}|xn--[a-z0-9-]{1,59}")
EXIT_QUEUED = 0
EXIT_ERROR = 1
EXIT_EXISTS = 3
EXIT_CAP = 4
EXIT_REFUSED = 5
EXIT_LOCKED = 6
```
Exit code 2 is left to argparse.

**Job outcomes as exceptions.** Each one ends `run_job` in exactly one place.
```python
class JobFailed(Exception):
    """A bound refused the job or a step failed; the message is the stored error text."""
class JobStopped(Exception):
    """SIGTERM arrived mid-job; the job is requeued without spending its claim."""
class JobTakenOver(Exception):
    """A conditional update matched no row: B1's route replaced the running row."""
class WhitelistBusy(Exception):
    """whitelist.db was locked or unopenable at claim time; the job is requeued without spending its claim."""
```

**Whitelist resolution** (used by `enqueue` and at claim time):
```python
def resolve_video(whitelist_path: Path, video_id: str, host: str, max_duration: int) -> tuple[dict[str, Any] | None, str | None]:
    """The whitelisted row and None, or None and the refusal text: B1's check (fetch_video_row with VIDEO_ERROR_THRESHOLD, then the active denylist on the row's normalised domain) plus the stored-duration bound; NULL duration passes."""
    conn = connect_readonly_db(whitelist_path)
    try:
        # sqlite3's 5 s default is shorter than the updater merge's commit; this raises past 30 s, never reads as not-found.
        conn.execute("PRAGMA busy_timeout = 30000")
        row = fetch_video_row(conn, video_id, host, error_threshold=VIDEO_ERROR_THRESHOLD)
        denied = list_active_denied_hosts(conn) if row is not None else set()
    finally:
        conn.close()
    if row is None:
        return None, "not in whitelist"
    if normalize_host(row["instance_domain"]) in denied:
        return None, "host denied"
    duration = row["duration"]
    if isinstance(duration, int) and duration > max_duration:
        return None, f"duration {duration}s over {max_duration}s"
    return row, None


def is_transient_db_error(exc: sqlite3.Error) -> bool:
    """A lock or a missing file (mid-restore); "no such column" and the like are real errors."""
    text = str(exc).lower()
    return "locked" in text or "busy" in text or "unable to open" in text
```
The connection is opened for each call and closed afterwards. It is never held for the life of the process, so the worker never pins an inode that a migration or restore replaces.

**Enqueue subcommand:**
```python
def command_enqueue(args: argparse.Namespace) -> int:
    """Resolve and queue one video; one output line and one exit code per outcome."""
    video_id = args.id.strip()
    host = normalize_host(args.host)
    if host is None or not video_id:
        print("refused: invalid id or host")
        return EXIT_REFUSED
    try:
        row, refusal = resolve_video(args.whitelist_db, video_id, host, args.max_duration)
    except sqlite3.Error as exc:
        print(f"error: whitelist.db: {exc}")
        return EXIT_ERROR
    if refusal is not None:
        print(f"refused: {refusal}")
        return EXIT_REFUSED
    args.subtitles_db.parent.mkdir(parents=True, exist_ok=True)
    conn = connect_subtitles_db(args.subtitles_db)
    try:
        ensure_subtitles_schema(conn)
        outcome, state = enqueue_translate_job(conn, row["video_id"], row["instance_domain"], TARGET_LANGUAGE, args.cap, now_ms())
    except sqlite3.Error as exc:
        print(f"error: subtitles.db: {exc}")
        return EXIT_ERROR
    finally:
        conn.close()
    where = f"video_id={row['video_id']} host={row['instance_domain']}"
    if outcome == "queued":
        print(f"queued {where}")
        return EXIT_QUEUED
    if outcome == "exists":
        print(f"already present: {state} {where}")
        return EXIT_EXISTS
    print(f"refused: queue cap {args.cap}")
    return EXIT_CAP
```
`enqueue` never takes the flock and never runs recovery.

**Media URL check and file picker:**
```python
def media_host(url: str) -> str | None:
    """The raw urlsplit hostname of an acceptable media URL (https, a DNS name, no port, no userinfo), else None; raw, not normalize_host's, so SameHostRedirectHandler's exact compare holds."""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return None
    host = parts.hostname
    if parts.scheme != "https" or not host or port is not None or parts.username is not None or parts.password is not None:
        return None
    try:
        ipaddress.ip_address(host)
        return None
    except ValueError:
        pass
    if normalize_host(host) is None or not _TLD.fullmatch(host.rstrip(".").rsplit(".", 1)[-1]) or "." not in host.rstrip("."):
        return None
    return host


def pick_media_url(video: dict[str, Any]) -> str | None:
    """The smallest acceptable fileUrl over files[] and streamingPlaylists[].files[]; hasAudio false is skipped (PeerTube 7 split HLS), a missing hasAudio is kept, unknown sizes sort last."""
    files = list(video.get("files") or []) if isinstance(video.get("files"), list) else []
    for playlist in video.get("streamingPlaylists") or []:
        if isinstance(playlist, dict) and isinstance(playlist.get("files"), list):
            files += playlist["files"]
    best: tuple[float, str] | None = None
    for item in files:
        if not isinstance(item, dict) or item.get("hasAudio") is False:
            continue
        url = item.get("fileUrl")
        if not isinstance(url, str) or media_host(url) is None:
            continue
        size = item.get("size")
        rank = float(size) if isinstance(size, int) and not isinstance(size, bool) and size > 0 else math.inf
        if best is None or rank < best[0]:
            best = (rank, url)
    return best[1] if best is not None else None


def video_duration(video: dict[str, Any]) -> float | None:
    """The JSON's duration in seconds when it is a finite non-negative number, else None (the bound cannot be checked)."""
    value = video.get("duration")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        return None
    return float(value)
```

**Download and ffmpeg pipe.** This has no numpy, so tests run it under 3.14 with real ffmpeg.
```python
class AudioPipe:
    """One sequential download fed to ffmpeg's stdin, 16 kHz mono s16le read from its stdout into memory; ffmpeg never sees the URL (R1) and nothing touches disk."""

    def __init__(self, url: str, host: str, max_bytes: int, max_samples: int) -> None:
        """Bind the pipe to one media URL, its raw host and both caps."""
        # fields: url, host, max_bytes, max_samples, pcm = bytearray(), done = False, error: str | None = None,
        # cond = threading.Condition(), stop = threading.Event(), stderr_tail = bytearray(), proc = None, threads = []

    def start(self) -> None:
        """Start ffmpeg and the feeder, stdout reader and stderr drain threads (all daemon)."""
        self.proc = subprocess.Popen(FFMPEG_ARGS, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        # one Thread per target in (self._feed, self._read, self._drain_stderr), started and kept in self.threads

    def _fail(self, text: str) -> None:
        """Record the first error, wake the reader of the buffer and kill ffmpeg; every exit path that aborts goes through here."""
        with self.cond:
            if self.error is None:
                self.error = text
            self.cond.notify_all()
        self.stop.set()
        self._kill()

    def _feed(self) -> None:
        """Download through build_opener(SameHostRedirectHandler(host)) into ffmpeg's stdin, refusing Content-Length over max_bytes and aborting past it while streaming; stdin is closed on every path."""
        # with build_opener(SameHostRedirectHandler(self.host)).open(Request(self.url), timeout=MEDIA_SOCKET_TIMEOUT_SECONDS) as resp:
        #   status != 200 -> _fail(f"media HTTP {status}"); digit content-length > max_bytes -> _fail(f"media over {max_bytes} bytes")
        #   loop until stop: chunk = resp.read1(READ_CHUNK_BYTES); count; over cap -> _fail(...); proc.stdin.write(chunk)
        # except BrokenPipeError: pass  (ffmpeg exited; _read reports its status)
        # except (OSError, ValueError, http.client.HTTPException) as exc: _fail(f"media download failed: {exc}")
        # finally: proc.stdin.close(), OSError ignored

    def _read(self) -> None:
        """Drain stdout into pcm at network speed, aborting past max_samples (a JSON that understates the duration is still bounded); then reap ffmpeg and report a non-zero exit with its stderr tail."""
        # loop: data = proc.stdout.read1(READ_CHUNK_BYTES); EOF -> break; under cond: pcm += data, notify_all;
        #   len(pcm) // BYTES_PER_SAMPLE > max_samples -> _fail(f"audio longer than {max_samples // SAMPLE_RATE}s"), break
        # rc = proc.wait(); join the stderr thread (1 s)
        # rc != 0 and not stop.is_set() -> _fail(f"ffmpeg exit {rc}: {tail}")
        # under cond: done = True, notify_all

    def _drain_stderr(self) -> None:
        """Keep the last STDERR_TAIL_BYTES of ffmpeg's stderr so a full pipe never blocks it."""

    def wait_samples(self, end: int) -> int:
        """Block up to POLL_SECONDS for end samples, the pipe's end or an error; the samples buffered."""
        with self.cond:
            self.cond.wait_for(lambda: self.done or self.error is not None or len(self.pcm) >= end * BYTES_PER_SAMPLE, timeout=POLL_SECONDS)
            return len(self.pcm) // BYTES_PER_SAMPLE

    def slice(self, start: int, end: int) -> bytes:
        """A copy of samples [start, end)."""

    def _kill(self) -> None:
        """Kill ffmpeg if it still runs."""

    def close(self) -> None:
        """Stop the feeder, kill ffmpeg and join the threads; bounded by one socket timeout."""
```
This is the class in the draft that has state shared across threads, which is why it is a class. The buffer keeps all the PCM: at most 115 MB, at the 60-minute cap. This is the accepted tradeoff.

**Model and VAD seam.** This is the only place numpy, faster-whisper and the CUDA wheels are imported.
```python
def preload_cuda_libraries() -> None:
    """dlopen the pip CUDA wheels' libcublasLt.so.12, libcublas.so.12 and libcudnn.so.9 with RTLD_GLOBAL, as S0 did, instead of LD_LIBRARY_PATH; the environment gate's tiny translate proves the set."""
    # import ctypes, importlib.util; for package, names in (("nvidia.cublas", (...)), ("nvidia.cudnn", (...))):
    #   locations = importlib.util.find_spec(package).submodule_search_locations -> Path(...) / "lib" / name -> ctypes.CDLL(str(path), mode=ctypes.RTLD_GLOBAL)


def _float_audio(pcm: bytes):
    """s16le bytes as float32 in [-1, 1), the form faster_whisper takes."""
    import numpy as np
    return np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0


class WhisperRunner:
    """The faster-whisper model, loaded on the first transcribe and dropped by unload; tests pass any object with speech/transcribe/unload/model."""

    def __init__(self) -> None:
        """Start without a model."""
        self.model = None

    def speech(self, pcm: bytes) -> list[tuple[int, int]]:
        """Silero speech spans in samples (faster-whisper's own VAD, on CPU)."""
        from faster_whisper.vad import VadOptions, get_speech_timestamps
        spans = get_speech_timestamps(_float_audio(pcm), VadOptions(min_silence_duration_ms=VAD_MIN_SILENCE_MS, speech_pad_ms=VAD_SPEECH_PAD_MS))
        return [(span["start"], span["end"]) for span in spans]

    def transcribe(self, pcm: bytes, language: str | None) -> tuple[list[tuple[float, float, str]], str]:
        """Translate one chunk to English: its (start, end, text) segments in chunk seconds and the language (detected when language is None)."""
        if self.model is None:
            preload_cuda_libraries()
            from faster_whisper import WhisperModel
            self.model = WhisperModel(MODEL_NAME, device="cuda", compute_type=COMPUTE_TYPE)
            logging.info("[translate-worker] model loaded name=%s compute_type=%s", MODEL_NAME, COMPUTE_TYPE)
        segments, info = self.model.transcribe(_float_audio(pcm), task="translate", language=language, vad_filter=True)
        # transcribe is lazy: decoding, and any CUDA out-of-memory, happens while this list is built.
        return [(segment.start, segment.end, segment.text) for segment in segments], info.language

    def unload(self) -> None:
        """Drop the model and collect it; the CUDA context stays until exit (accepted)."""
        if self.model is not None:
            self.model = None
            gc.collect()
            logging.info("[translate-worker] model unloaded")


def is_cuda_oom(exc: BaseException) -> bool:
    """CTranslate2 raises CUDA out-of-memory as a RuntimeError naming it."""
    return isinstance(exc, RuntimeError) and "out of memory" in str(exc).lower()
```

**Chunking and cues** (no numpy):
```python
def cut_point(spans: list[tuple[int, int]], length: int, final: bool, min_cut: int) -> int:
    """Where a window is cut, in samples: its end when it is the last window, holds no speech, or ends in silence; else the middle of the last gap between two speech spans at or past min_cut; else its end (hard cut, R2)."""
    if final or not spans or spans[-1][1] < length:
        return length
    for (_, gap_start), (gap_end, _) in reversed(list(zip(spans, spans[1:]))):
        cut = (gap_start + gap_end) // 2
        if cut >= min_cut:
            return cut
    return length


def chunk_cues(segments: list[tuple[float, float, str]], offset: float) -> list[dict[str, Any]]:
    """Segments as absolute cues: stripped text, empty texts dropped, times plus the chunk offset rounded to ms, non-finite or reversed times dropped."""
    cues: list[dict[str, Any]] = []
    for start, end, text in segments:
        text = text.strip()
        begin = round(offset + start, 3)
        finish = round(offset + end, 3)
        if text and math.isfinite(begin) and math.isfinite(finish) and finish >= begin:
            cues.append({"start": begin, "end": finish, "text": text})
    return cues


def translate_audio(conn, job, pipe: AudioPipe, runner, max_chunk: int, stop: threading.Event, progress: dict[str, float]) -> str:
    """Transcribe pipe's PCM window by window, rewriting the running row's cues after each chunk that adds some; the end state written."""
    key = (job["video_id"], job["instance_domain"], TARGET_LANGUAGE)
    cues: list[dict[str, Any]] = []
    language: str | None = None
    pos = 0
    while True:
        available = pipe.wait_samples(pos + max_chunk)
        progress["at"] = time.monotonic()
        if stop.is_set():
            raise JobStopped()
        if pipe.error is not None:
            raise JobFailed(pipe.error)
        if available < pos + max_chunk and not pipe.done:
            continue
        if available <= pos:
            break
        window = pipe.slice(pos, min(available, pos + max_chunk))
        spans = runner.speech(window)
        cut = cut_point(spans, len(window) // BYTES_PER_SAMPLE, available < pos + max_chunk, int(MIN_CHUNK_SECONDS * SAMPLE_RATE))
        # A chunk with no speech is skipped: no GPU time, no invented lines (R5), and detection runs on the first chunk that has speech.
        if any(start < cut for start, _ in spans):
            segments, detected = runner.transcribe(window[: cut * BYTES_PER_SAMPLE], language)
            if language is None:
                language = detected
                if language == TARGET_LANGUAGE:
                    if not finish_translate_already_english(conn, *key, job["started_at"], language, now_ms()):
                        raise JobTakenOver()
                    return "already_english"
            new = chunk_cues(segments, pos / SAMPLE_RATE)
            if new:
                cues += new
                if not store_running_cues(conn, *key, job["started_at"], cues, language):
                    raise JobTakenOver()
        pos += cut
    if pipe.error is not None:
        raise JobFailed(pipe.error)
    if not cues:
        raise JobFailed("no speech detected")
    # Order holds by construction; the sort keeps B1's sorted-cues assumption even where segments overlap at a join.
    cues.sort(key=lambda cue: (cue["start"], cue["end"]))
    if not finish_translate_ready(conn, *key, job["started_at"], cues, now_ms()):
        raise JobTakenOver()
    return "ready"
```

**One job:**
```python
def run_job(conn, job, args: argparse.Namespace, runner, stop: threading.Event, progress: dict[str, float]) -> bool:
    """Run one claimed job to exactly one end state (or a requeue); True when it was requeued for a transient whitelist.db error, so the loop backs off."""
    key = (job["video_id"], job["instance_domain"], TARGET_LANGUAGE)
    started_at = job["started_at"]
    pipe: AudioPipe | None = None
    try:
        try:
            row, refusal = resolve_video(args.whitelist_db, job["video_id"], job["instance_domain"], args.max_duration)
        except sqlite3.Error as exc:
            if is_transient_db_error(exc):
                raise WhitelistBusy(str(exc)) from exc
            raise
        if refusal is not None:
            raise JobFailed(refusal)
        instance = row["instance_domain"]
        video_key = row["video_uuid"] or row["video_id"]
        fetched = internal_translate.fetch_instance_track(instance, video_key)
        if fetched is not None:
            store_ready_subtitles(conn, *key[:2], TARGET_LANGUAGE, SOURCE_INSTANCE, fetched[0], fetched[1], now_ms())
            mark_translate_finished(conn, *key, started_at, now_ms())
            logging.info("[translate-worker] instance track video_id=%s host=%s", *key[:2])
            return False
        raw = internal_translate.fetch_bounded(instance, f"/api/v1/videos/{quote(video_key, safe='')}", time.monotonic() + FETCH_DEADLINE_SECONDS)
        # fetch_bounded gives no reason on failure, so this text is generic by necessity.
        video = _json_object(raw) if raw is not None else None   # dict or None; ValueError/RecursionError/UnicodeDecodeError -> None
        if video is None:
            raise JobFailed("video JSON fetch failed")
        duration = video_duration(video)
        if duration is None:
            raise JobFailed("video duration unknown")
        if duration > args.max_duration:
            raise JobFailed(f"duration {duration:g}s over {args.max_duration}s")
        url = pick_media_url(video)
        if url is None:
            raise JobFailed("no usable https media file")
        pipe = AudioPipe(url, media_host(url), args.max_bytes, args.max_duration * SAMPLE_RATE)
        pipe.start()
        state = translate_audio(conn, job, pipe, runner, args.max_chunk_seconds * SAMPLE_RATE, stop, progress)
        logging.info("[translate-worker] job %s video_id=%s host=%s", state, *key[:2])
    except JobStopped:
        requeue_translate_job(conn, *key, started_at)
        logging.info("[translate-worker] stopped mid-job, requeued video_id=%s host=%s", *key[:2])
    except WhitelistBusy as exc:
        requeue_translate_job(conn, *key, started_at)
        logging.warning("[translate-worker] whitelist.db unavailable, requeued video_id=%s host=%s: %s", *key[:2], exc)
        return True
    except JobTakenOver:
        logging.info("[translate-worker] taken over by the instance track video_id=%s host=%s", *key[:2])
    except JobFailed as exc:
        _fail_job(conn, key, started_at, str(exc))
    except Exception as exc:
        if is_cuda_oom(exc):
            runner.unload()
        logging.exception("[translate-worker] job error video_id=%s host=%s", *key[:2])
        _fail_job(conn, key, started_at, f"{type(exc).__name__}: {exc}")
    finally:
        if pipe is not None:
            pipe.close()
    return False


def _fail_job(conn, key: tuple[str, str, str], started_at: int, error: str) -> None:
    """Write failed with a capped error text; a store error is logged and the row stays running, so the next start's recovery decides."""
```
The sqlite errors raised inside `requeue_translate_job` in the `JobStopped`/`WhitelistBusy` handlers are caught and logged the same way, so a stop never raises out of `run_job`.

**Heartbeat, loop and start-up:**
```python
def heartbeat_loop(db_path: Path, stop: threading.Event, progress: dict[str, float]) -> None:
    """Beat every HEARTBEAT_SECONDS on its own connection, idle or busy, unless the main loop has been silent for STALL_SECONDS; a failed beat is logged and retried next tick."""
    conn = connect_subtitles_db(db_path)
    try:
        while True:
            if time.monotonic() - progress["at"] <= STALL_SECONDS:
                try:
                    write_translate_heartbeat(conn, now_ms(), os.getpid())
                except sqlite3.Error as exc:
                    logging.warning("[translate-worker] heartbeat failed: %s", exc)
            if stop.wait(HEARTBEAT_SECONDS):
                break
    finally:
        conn.close()


def serve(conn, args, runner, stop, progress) -> None:
    """Claim and run jobs one at a time until stop; poll every POLL_SECONDS when idle and unload the model after IDLE_UNLOAD_SECONDS without a job."""
    idle_since = time.monotonic()
    while not stop.is_set():
        progress["at"] = time.monotonic()
        try:
            job = claim_translate_job(conn, TARGET_LANGUAGE, now_ms())
        except sqlite3.Error as exc:
            logging.warning("[translate-worker] claim failed: %s", exc)
            stop.wait(POLL_SECONDS)
            continue
        if job is None:
            if runner.model is not None and time.monotonic() - idle_since >= IDLE_UNLOAD_SECONDS:
                runner.unload()
            stop.wait(POLL_SECONDS)
            continue
        logging.info("[translate-worker] claimed video_id=%s host=%s attempts=%s", job["video_id"], job["instance_domain"], job["attempts"])
        backoff = run_job(conn, job, args, runner, stop, progress)
        idle_since = time.monotonic()
        if backoff:
            stop.wait(TRANSIENT_BACKOFF_SECONDS)


def command_run(args: argparse.Namespace) -> int:
    """The service, in this order: ffmpeg check, flock (a refused second run writes nothing), schema and recovery, heartbeat thread, loop."""
    setup_logging(args.log)
    if shutil.which("ffmpeg") is None:
        logging.error("[translate-worker] ffmpeg not found on PATH")
        return EXIT_ERROR
    args.lock.parent.mkdir(parents=True, exist_ok=True)
    lock_fd = os.open(args.lock.as_posix(), os.O_RDONLY | os.O_CREAT, 0o644)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(lock_fd)
        logging.error("[translate-worker] another worker holds %s", args.lock)
        return EXIT_LOCKED
    stop = threading.Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_: stop.set())
    progress = {"at": time.monotonic()}
    conn = connect_subtitles_db(args.subtitles_db)
    beat: threading.Thread | None = None
    try:
        ensure_subtitles_schema(conn)
        requeued, failed = recover_translate_jobs(conn, now_ms())
        logging.info("[translate-worker] started pid=%s recovered requeued=%s failed=%s", os.getpid(), requeued, failed)
        beat = threading.Thread(target=heartbeat_loop, args=(args.subtitles_db, stop, progress), daemon=True)
        beat.start()
        serve(conn, args, WhisperRunner(), stop, progress)
    finally:
        stop.set()
        if beat is not None:
            beat.join(HEARTBEAT_SECONDS)
        conn.close()
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)
    return EXIT_QUEUED
```
`setup_logging` is copied from `updater-worker.py:317`. On SIGTERM the main thread notices the stop between bytecodes. While it is inside one `transcribe` chunk it notices only once that chunk ends (seconds), then requeues, closes the pipe (at most one socket timeout, 15 s) and exits. The unit's `TimeoutStopSec=60` covers that.

**Arguments**, in the style of `instance-denylist-cli.py`, with `CompactHelpFormatter` passed to the parser and to each `add_parser`:
- Top level: `--subtitles-db` (default `repo_root / DEFAULT_SUBTITLES_DB_PATH`) and `--whitelist-db` (default `repo_root / DEFAULT_DB_PATH`), where `repo_root = script_dir.parents[3]`.
- `enqueue`: `--id` and `--host` (required), `--cap` (default `SUBTITLE_QUEUE_CAP`), `--max-duration` (default `SUBTITLE_MAX_DURATION`).
- `run`: `--lock` (default `engine/server/db/translate-worker.lock`), `--log` (default `engine/server/db/translate-worker.log`), `--max-duration`, `--max-bytes`, `--max-chunk-seconds`.
- The numeric flags use a `_positive_int` type, because `--max-chunk-seconds 0` would loop forever.
- `main()` dispatches with `sys.exit(command_enqueue(args) if args.command == "enqueue" else command_run(args))`.

---

### Seams the tests use

| Seam | Faked by |
|---|---|
| Instance (captions, track, video JSON) | `internal_translate.build_opener`, with a test-local recorder that records the call order. B1's `RecordingInstance` is not reused. |
| Media host | The worker module's `build_opener`. |
| Whisper and VAD | A stub runner with `model`, `speech(pcm)`, `transcribe(pcm, language)` and `unload()`. It can raise `RuntimeError("CUDA failed: out of memory")`. |
| ffmpeg | Real, fed a clip that `ffmpeg -f lavfi` generates in `tmp_path`. If ffmpeg is missing, the tests `pytest.fail` with a message, because the worker requires it. |
| Time | `now_ms` is passed into every store function. |
| Processes | The R8 test, the lock test and the SIGTERM test are `subprocess` runs of explicit scripts, never multiprocessing. Every test uses `tmp_path` databases and never the repo's `subtitles.db`. The two VAD/model checks run under `ENGINE_PY`. |

### Checks against the high-level plan and the requirements

Pass 1 found eight gaps, and the draft above closes them. Pass 2 found none, so it converged.

| Item | Status |
|---|---|
| AC1 | Persistent rows, the new states, `whisper`, columns added in place, idempotent enqueue that never overwrites, cap result, oldest-first claim in one IMMEDIATE transaction, recovery once then failed, WAL, R8 test: met. |
| AC2 | Same `enqueue_translate_job` as plan 50, B1's resolution, canonical key, four outcomes with distinct lines and exit codes: met. |
| AC3 | Instance track first, then JSON, duration, smallest https file, one pass through ffmpeg stdin, faster-whisper `translate` (`medium`/`int8_float16`, `vad_filter`) on silence-cut chunks capped at 30 s, absolute times, English on detection → `already_english` before any cue is written: met. One refinement: detection runs on the first chunk that has speech. |
| AC4 | Whole-`cues_json` rewrite per chunk. `fetch_ready_subtitles` is unchanged and reads either source. Exactly one end state, and `failed` carries its text: met. |
| AC5 | Duration (stored row, JSON and decoded samples), whitelist and denylist at enqueue and at claim, instance calls through B1's `fetch_bounded`, media URL lexical bounds per the operator's decision, size by Content-Length and by streaming: met. |
| AC6 | 5 s heartbeat from its own thread and connection, idle or busy: met. It also stops beating when the main loop stalls. |
| AC7 | Lazy load, 5-minute unload, OOM → `failed`, unload, keep serving: met in code. The 3,072 MiB peak is manual evidence from the `nvidia-smi` sampler. |
| Consistency | Separate process; it writes only `subtitles.db` (plus its lock file and log); `normalize_host` reused; B1's files and tests unedited; the Engine imports no GPU code: met. |

**Where the draft departs from the high-level plan, named as departures:**
1. **Detection on the first chunk with speech.** Chunks without speech are skipped instead of transcribed. This saves GPU time, cuts hallucination (R5), and keeps detection off silent intros.
2. **Requeue-without-counting is adopted.** It is used for SIGTERM and for a whitelist lock or a missing file at claim time, with a 30 s backoff, and it carries the step 4 recommendation. Without it, ordinary restarts would use up AC1's single retry.
3. **`hasAudio: false` files are skipped.** This avoids picking a video-only split-HLS file.
4. **The IP-literal rule is extended.** It also refuses a host whose last label is not letters or punycode, and a single-label host. This closes `127.1`, decimal and hex forms that `inet_aton` resolves but `ipaddress` rejects.
5. **Heartbeat stall guard.** The heartbeat stops after 600 s without main-loop progress, so plan 50 does not read a hung worker as available.
6. **The final `ready` write carries the full sorted cue list** rather than relying on the last per-chunk rewrite.
7. **`busy_timeout=30000` on the worker's read-only `whitelist.db` connection,** with a lock or open error treated as transient, not as "not found".
8. **Two smaller choices.** AC3.1 uses `store_ready_subtitles` (as the requirements name it) followed by a `started_at`-conditioned `mark_translate_finished`. The `run` unit uses `TimeoutStopSec=60`, not the installer's 20.

**Limitations as accepted, unchanged:**
- PCM is held in RAM (≤ 115 MB).
- There is no DNS-level SSRF check.
- An idle worker keeps its CUDA context.
- A non-faststart MP4 fails.
- The socket timeout is the only stall bound on the download.
- R2, R5 and R6.
- B1's overlay showing Whisper cues for finished jobs follows from AC4's "either source" rule and is documented. It is not prevented.
- The media host may differ from the instance host, per the operator's AC5 decision. The R4 wording in plans 49 and 18 is updated at close-out, as the settled documentation list says.


### Phases

#### Phase 1 - Subtitles store: in-place upgrade and concurrent writers [code]

**Files touched.** engine/server/data/subtitles.py (EDITED), tests/active/test_translate_worker.py (NEW), tests/config.json (EDITED)

**Checkpoint.** Seam: the store functions in engine/server/data/subtitles.py, called directly (rung 1) against a tmp_path subtitles.db opened with connect_subtitles_db + ensure_subtitles_schema, as test_internal_translate.py's store tests open it, plus two explicit subprocess scripts for the concurrent cases. C1 asserts four things. (a) A file built with B1's exact CREATE TABLE and holding B1 ready rows gains every JOB_COLUMNS column and the state/queued_at index. (b) PRAGMA journal_mode answers 'wal'. (c) fetch_ready_subtitles returns the same cues for the old rows before and after the upgrade. (d) Two subprocesses running ensure_subtitles_schema on one B1-shaped file at once both exit 0 with no 'duplicate column' error, and the column set is the same. A mode=ro open after the last writer closes still reads, under pytest's Python and under ENGINE_PY. C2 runs two subprocesses for several seconds against one file. The Engine script runs ensure_subtitles_schema and then store_ready_subtitles in a loop on its own keys. The worker script runs enqueue, claim, store_running_cues, finish_translate_ready and write_translate_heartbeat in a loop. The test asserts that neither stderr contains 'database is locked', that both exit 0, that every Engine key reads ready/instance, that every worker key reads ready/whisper with its full cue list, and that the heartbeat row exists.

**Intent.** engine/server/data/subtitles.py upgrades a B1 subtitles.db in place to a WAL file carrying the translate-job columns, the heartbeat table and the job store functions, and that file takes the Engine's and the worker's writes concurrently without lock errors.

- C1 - A B1-shaped subtitles.db is upgraded in place by ensure_subtitles_schema, even under concurrent upgraders: it gains the job columns in WAL mode, and its old rows read unchanged.
- C2 - An Engine process and a worker process writing one subtitles.db concurrently never raise "database is locked" and leave consistent rows.

**Outcome.** ### `engine/server/data/subtitles.py`
- Updated the module docstring and the `SUBTITLES_BUSY_TIMEOUT_SECONDS` comment. They now describe the job states, the `whisper` source, WAL mode, and the translate worker writing the file alongside the Engines. The 30 s value is unchanged.
- New constants: `SOURCE_WHISPER`; `JOB_COLUMNS`, which lists `queued_at`, `started_at`, `finished_at`, `error`, `detected_language` and `attempts INTEGER NOT NULL DEFAULT 0`; and `_KEY`, the where-clause for the row key.
- `connect_subtitles_db` now runs `PRAGMA journal_mode=WAL` straight after connecting. If two openers switch a rollback-journal file at the same moment, SQLite can fail one of them with "database is locked" immediately, without waiting on the busy timeout. A probe saw this in 1 of 120 racing opens, and the error was raised rather than the old mode being returned. So the switch retries every 10 ms on that error until the 30 s busy-timeout deadline. Any other error, or reaching the deadline, closes the connection and re-raises.
- New `_immediate(conn)` context manager: one `BEGIN IMMEDIATE` transaction that commits at the end and rolls back on any error.
- `ensure_subtitles_schema` now does all its work in one IMMEDIATE transaction: it creates B1's table (DDL unchanged), reads `PRAGMA table_info`, adds each missing job column with `ALTER TABLE ... ADD COLUMN`, and creates the index `subtitles_state_queued_at` on `(state, queued_at)` and the table `translate_worker_heartbeat (id INTEGER PRIMARY KEY CHECK (id = 1), beat_at INTEGER NOT NULL, pid INTEGER NOT NULL)`. Running the check and the alters in one transaction is what prevents the "duplicate column" race between two upgraders.
- `fetch_ready_subtitles` is unchanged. `store_ready_subtitles` has the same code; only its docstring changed, to say that it ends a job row and leaves the job columns behind.
- New store functions, as specified in the plan's code sketch:
  - `_cues_text`: compact JSON with `allow_nan=False`.
  - `enqueue_translate_job`: one IMMEDIATE transaction that returns `("exists", state)`, `("cap", None)` or `("queued", "queued")`. It uses a plain INSERT, because the existence check under the write lock makes it authoritative; a conflict would raise instead of falsely reporting "queued".
  - `claim_translate_job`: one IMMEDIATE transaction that takes the oldest queued row by `queued_at` then rowid, sets it to `running`, sets `started_at` and adds 1 to `attempts`. It returns a Row with the key, `started_at` and `attempts`.
  - `_update_claim`: one conditional UPDATE on key + `state='running'` + `started_at`, returning `rowcount == 1`.
  - `store_running_cues`, `finish_translate_ready` and `write_translate_heartbeat`: the single-row heartbeat is an upsert.
- Not added yet: the plan's other store functions (`recover_translate_jobs`, `requeue_translate_job`, `finish_translate_already_english`, `finish_translate_failed`, `mark_translate_finished`) and the `MAX_CLAIMS`/`RECOVERY_ERROR` constants. This checkpoint does not use them, so they belong to the phases that test them.

### `tests/active/test_translate_worker.py`, `tests/config.json`
Not touched in this step. They are where the checkpoint is promoted and its test group registered, which I take to be the workflow's promotion step, not production code.

**Beyond the files named.** tests/tmp/probe_wal_switch.py: a throwaway probe showing that a racing `PRAGMA journal_mode=WAL` raises "database is locked" (1 of 120 opens) instead of returning the old mode. It should be deleted; I have no delete tool.
tests/tmp/probe_subtitles_race.py: a throwaway probe that ran 96 concurrent-upgrade rounds and a 3 s two-writer run against the new code, all clean. It should be deleted; I have no delete tool.

#### Phase 2 - Queue and enqueue CLI [code]

**Files touched.** engine/server/api/server_config.py (EDITED), engine/server/db/jobs/translate-worker.py (NEW), tests/active/test_translate_worker.py (EDITED)

**Checkpoint.** Seam: the enqueue command run as a subprocess (rung 2, `python engine/server/db/jobs/translate-worker.py --whitelist-db <tmp> --subtitles-db <tmp> enqueue --id --host`, following test_updater_worker.py's subprocess precedent). It runs against a tmp whitelist.db with videos, channels and instance_denylist, built the way test_internal_translate.py's _whitelist builds it. Claim and recovery are tested at rung 1 on the store functions. C1 asserts each outcome's stdout line and exit code: queued (0, plus a queued/whisper row with attempts 0 under the canonical video_id and instance_domain, even when it was enqueued by uuid and a non-normalised host); already present: <state> (3) for each of queued, running, ready, failed, already_english and a B1 ready/instance row, where every column of the pre-existing row is byte-identical afterwards; refused: queue cap (4) with the row count unchanged; refused (5) for not in whitelist, host denied and a stored duration over --max-duration, with no row written. C2 asserts four things. Three jobs queued at different queued_at values are claimed oldest first, and each becomes running with started_at set and attempts+1. A running row with attempts 1 is requeued by recover_translate_jobs. The same row, claimed again (attempts 2) and recovered again, becomes failed with RECOVERY_ERROR and finished_at. The (requeued, failed) counts match.

**Intent.** A whitelisted video can be queued from translate-worker.py's enqueue command under its canonical key with one line and one exit code per outcome, and the queue hands jobs out oldest first, retrying a crashed job once before failing it.

- C1 - The enqueue command prints one line and exits with a distinct code for each outcome (queued, already present with its state and never overwritten, queue cap, refused with its reason).
- C2 - Claim hands out the oldest queued job, and start-up recovery requeues a running job once and fails it the second time it is found running.

**Outcome.** ### `engine/server/db/jobs/translate-worker.py` (new)
- A new script laid out like `instance-denylist-cli.py`. It puts `server_dir` and `api_dir` on `sys.path` at the top, takes `CompactHelpFormatter` from `scripts.cli_format`, and uses argparse subparsers (`dest="command", required=True`).
- **Arguments.** Top level: `--whitelist-db` (default `<repo>/engine/server/db/whitelist.db`) and `--subtitles-db` (default `<repo>/engine/server/db/subtitles.db`). There is one subcommand, `enqueue`, with `--id` and `--host` (both required), `--cap` (default `SUBTITLE_QUEUE_CAP`) and `--max-duration` (default `SUBTITLE_MAX_DURATION`). Both numeric flags use a `_positive_int` type.
- **`resolve_video(whitelist_path, video_id, host, max_duration)`** copies B1's check:
  - It opens `whitelist.db` with `connect_readonly_db` and sets `PRAGMA busy_timeout = 30000`.
  - It calls `fetch_video_row` with `VIDEO_ERROR_THRESHOLD`, then checks `list_active_denied_hosts` against `normalize_host` of the row's own domain.
  - It also refuses a stored integer `duration` over `max_duration`; a NULL duration passes.
  - It returns either `(row, None)` or `(None, "not in whitelist" | "host denied" | "duration Ns over Ms")`.
- **`command_enqueue`**:
  - It normalises the host. If the host is None or the id is empty, it refuses before the lookup, because `fetch_video_row` with a None host would match the id on any host.
  - It then resolves the video, opens the store with `connect_subtitles_db` plus `ensure_subtitles_schema`, and calls `enqueue_translate_job` under the row's canonical `video_id` and `instance_domain`, with `now_ms()`.
  - It prints one line per outcome and exits with that outcome's code:
    - `queued video_id=… host=…` exits 0;
    - `already present: <state> video_id=… host=…` exits 3;
    - `refused: queue cap N` exits 4;
    - `refused: <reason>` exits 5;
    - a sqlite error on either database prints one `error: <db>: …` line and exits 1. Exit 2 is left to argparse.
- It never takes a lock and never runs recovery. The `run` subcommand belongs to phases 3 and 4.

### `engine/server/api/server_config.py`
- Added four constants next to `DEFAULT_SUBTITLES_DB_PATH`, each with a one-line comment:
  - `SUBTITLE_MAX_DURATION = 3600`
  - `SUBTITLE_MAX_BYTES = 1024 ** 3`
  - `SUBTITLE_QUEUE_CAP = 50`
  - `SUBTITLE_MAX_CHUNK_SECONDS = 30`
- This phase only reads the duration and cap constants. The other two are here because this is the only phase whose file list includes `server_config.py`, and the plan's module map assigns all four to it.
- The comment on `DEFAULT_SUBTITLES_DB_PATH` now says the file also holds the translate worker's jobs and heartbeat.

### `engine/server/data/subtitles.py` (not in this phase's file list; see unanticipated)
- Added the constants `MAX_CLAIMS = 2` and `RECOVERY_ERROR = "worker stopped while running twice"`, with a comment on the one-retry rule.
- Added `recover_translate_jobs(conn, finished_at) -> (requeued, failed)`. It runs in one `_immediate` transaction:
  1. Running rows with `attempts >= MAX_CLAIMS` become `failed`, with `RECOVERY_ERROR` and `finished_at`.
  2. Every other running row goes back to `queued`, keeping its attempts, with no error and no `finished_at`.
- `claim_translate_job` was already present from phase 1 and is unchanged.

### `tests/active/test_translate_worker.py`
- Not touched. It is where the workflow promotes the checkpoint.

### Observed
- I ran a throwaway probe, `tests/tmp/probe_phase2_worker_cli.py`, through ValidateTests. It ran the command under ENGINE_PY on the checkpoint's own tmp whitelist fixture. Every outcome printed the line and exit code shown above. The uuid plus `PEER.Example.` request queued `v-1`/`peer.example`/whisper with attempts 0. One claim followed by recovery answered `(1, 0)`.
- I have no delete tool, so the probe file is still there. It should be deleted.

**Beyond the files named.** engine/server/data/subtitles.py: the checkpoint imports `recover_translate_jobs` from `data.subtitles`, and phase 1 left that function out ("belongs to the phase that tests it"), so I added it there together with `MAX_CLAIMS` and `RECOVERY_ERROR`.
tests/tmp/probe_phase2_worker_cli.py: a throwaway probe I wrote to watch the CLI's lines and exit codes and the recovery counts. It should be deleted; I have no delete tool.

#### Phase 3 - Job pipeline [code]

**Files touched.** engine/server/db/jobs/translate-worker.py (EDITED), tests/active/test_translate_worker.py (EDITED)

**Checkpoint.** Seam: run_job called in-process on a claimed job, with tmp whitelist.db and subtitles.db. The instance is faked at internal_translate.build_opener with a test-local recorder in the ScriptedInstance pattern from test_internal_translate.py, which records every URL in order. The media host is faked at the worker module's build_opener and serves bytes of a clip that `ffmpeg -f lavfi` generated in tmp_path. ffmpeg is real (the test calls pytest.fail if it is missing). Whisper and VAD are replaced by a stub runner exposing model, speech, transcribe and unload. C1 is parametrised over each bound, and each case asserts that the row is failed with that bound's error text and that the recorder saw no URL after the refusing step. The bounds are: whitelist/denylist at claim, JSON duration unknown, JSON duration over the cap, no acceptable media URL (http, IPv4/IPv6 literal, numeric/hex/single-label host, port, userinfo, hasAudio false), media Content-Length over max_bytes, media streamed past max_bytes, decoded samples past max_duration, and an off-host media redirect. A further rung 1 check covers pick_media_url: the smallest file is chosen, and files with unknown sizes sort last. C2 asserts the following. Using a stub with speech in chunks 1 and 3 and silence in chunk 2, the running row's cues_json read after each transcribe call grows by exactly that chunk's cues. Every cue time equals the segment time plus the chunk offset in samples/16000, rounded to ms. The silent chunk triggers no transcribe call. The row ends ready/whisper with the full sorted list and finished_at. Each of the remaining outcomes ends in its own single state: detected en gives already_english, with cues_json NULL and no store_running_cues ever written; no speech gives failed 'no speech detected'; an OOM RuntimeError gives failed with its text and unload called once; an instance English track gives ready/instance with finished_at stamped and no media fetch; a B1 takeover mid-job leaves the row ready/instance, untouched by the worker; a stop event mid-job requeues with attempts restored and queued_at kept.

**Intent.** run_job in translate-worker.py takes a claimed job through the bounded instance, media and ffmpeg pipeline into silence-cut Whisper chunks, refusing every AC5 bound and rewriting the running row's cues per chunk until exactly one end state.

- C1 - Every AC5 bound that a job breaks ends it failed with that bound's error text, and no further remote request is made.
- C2 - A transcribed job rewrites cues_json after each chunk with absolute cue times and ends in exactly one end state.

**Outcome.** ### `engine/server/db/jobs/translate-worker.py`
- The module docstring has a new paragraph on `run_job`'s pipeline. New imports: `http.client`, `json`, `logging`, `math`, `re`, `subprocess`, `threading`, `time`, `quote`/`urlsplit`, and `Request`/`build_opener` (a module-level name, so tests can fake the media host there). It also imports `FETCH_DEADLINE_SECONDS`, `READ_CHUNK_BYTES`, `SOURCE_INSTANCE`, `SameHostRedirectHandler`, `fetch_bounded` and `fetch_instance_track` from B1's `handlers.internal_translate`, which is not edited.
- New constants:
  - `SAMPLE_RATE`, `BYTES_PER_SAMPLE`.
  - `MIN_CHUNK_SAMPLES` (5 s): the shortest chunk a silence cut may leave.
  - `POLL_SECONDS`.
  - `MEDIA_SOCKET_TIMEOUT_SECONDS` (15 s).
  - `STDERR_TAIL_BYTES`.
  - `FFMPEG_ARGS`: `-i pipe:0 -vn -f s16le -ac 1 -ar 16000 pipe:1`.
  - `_TLD`: the last label must be letters or punycode.
- Three exceptions end a job, each in one place: `JobFailed` (its message is the stored error text), `JobStopped` and `JobTakenOver`.
- `media_host(url)` returns the raw `urlsplit` hostname, or None if the URL is not https, has a port or userinfo, fails `normalize_host`, or is not a DNS name. "Not a DNS name" means fewer than two labels or a last label that does not match `_TLD`. That one rule refuses IPv4 and IPv6 literals and the decimal, dotted-numeric and hex hosts, so `ipaddress` isn't needed.
- `pick_media_url(video)` looks at `files[]` plus `streamingPlaylists[].files[]`, guarding against non-list JSON. It skips `hasAudio: false` and unacceptable URLs, and takes the smallest declared `size`. A file without a size ranks as `math.inf`, so it sorts last but is still chosen when it is the only file.
- `video_duration(video)` returns a finite, non-negative, non-bool number, or None.
- `AudioPipe` downloads the media once, sequentially, into ffmpeg's stdin; nothing touches disk. It uses three daemon threads:
  - **Feeder:** opens the URL through `build_opener(SameHostRedirectHandler(host))`. A Content-Length over max_bytes is refused before any read. It counts bytes while streaming. An off-host redirect, HTTP error or timeout fails with `media download failed: …`. It closes stdin on every path.
  - **Reader:** fills an in-memory PCM buffer from stdout. Past `max_duration * 16000` samples it fails with `audio longer than Ns`. It reports a non-zero ffmpeg exit with the stderr tail.
  - **Stderr drain.**

  The first error wins, and recording it kills ffmpeg. `wait_samples` returns the sample count and the done flag as one snapshot taken under the lock. The error is always set before done, so the chunk loop can never miss it. `close()` kills ffmpeg, joins the threads and closes the pipes. A `rat-tail:` comment marks that all PCM is kept in RAM.
- `cut_point(spans, length, final)` decides where a window is cut:
  - at its end when it is the last window, has no speech, or ends in silence;
  - otherwise at the middle of its last gap between speech spans, if that point is at least `MIN_CHUNK_SAMPLES` in;
  - otherwise at its end (a hard cut).
- `chunk_cues(segments, offset)` turns segments into cues: text stripped, empty texts dropped, times plus the chunk offset rounded to ms, and non-finite or reversed times dropped.
- `is_cuda_oom(exc)`: a RuntimeError whose text contains "out of memory".
- `translate_audio(...)` takes the PCM one window of `max_chunk_seconds` at a time:
  - Each loop it updates `progress["at"]`, raises `JobStopped` if stop is set, and raises `JobFailed` on a pipe error.
  - It asks `runner.speech` about the window and calls `runner.transcribe` only when there is speech before the cut.
  - Detection happens on the first speech chunk. `en` ends the job `already_english` before any cue is written.
  - After each chunk that adds cues it rewrites `cues_json` with `store_running_cues`. A rowcount of 0 means B1 took the row over, and raises `JobTakenOver`.
  - No cues at all ends the job `failed` with `no speech detected`. Otherwise it sorts the cues and ends `ready`/whisper through `finish_translate_ready`.
- `generate(...)` runs AC3 in order, refusing at each bound before the next remote request:
  1. `resolve_video` again (the whitelist and denylist).
  2. `fetch_instance_track`. If there is an English track: `store_ready_subtitles` with `SOURCE_INSTANCE`, then `mark_translate_finished`.
  3. The video JSON through B1's `fetch_bounded`, which gives the same-domain redirect rule. Failures: `video JSON fetch failed`, `video duration unknown`, `duration Ns over Ms`.
  4. `pick_media_url`, failing with `no usable https media file`.
  5. `AudioPipe`, then `translate_audio`. The pipe is closed in `finally`.
- `run_job(conn, job, args, runner, stop, progress)` maps the outcome to exactly one row write:
  - `JobStopped` → `requeue_translate_job`.
  - `JobTakenOver` → no write.
  - `JobFailed` → `finish_translate_failed` with its text.
  - Any other exception → failed with `Type: text`. For a CUDA out-of-memory it calls `runner.unload()` once first.

  Each outcome is logged with a `[translate-worker]` prefix.
- Left for phase 4, which has the `run` command and the serve loop: `WhisperRunner` (the faster-whisper and VAD runner), and requeue-without-counting plus back-off for a locked `whitelist.db` at claim time. Until then, a sqlite error from `resolve_video` fails the job like any other error.

### `engine/server/data/subtitles.py`
These are the plan's remaining store functions, in the style of the existing ones:
- `requeue_translate_job`: a conditional update to `state='queued'`, `attempts-1`. `queued_at` is left as it was.
- `finish_translate_already_english`: sets the state, `detected_language` and `finished_at`. It does not touch `cues_json`, so no cue write ever happens.
- `finish_translate_failed`: sets the state, `error` and `finished_at`.

All three go through `_update_claim` (key + `state='running'` + `started_at`, returning `rowcount == 1`).
- `mark_translate_finished`: stamps `finished_at` on a `ready` row with the claim's `started_at`, after the worker's own `store_ready_subtitles`.

### Observed
- I ran a throwaway probe, `tests/tmp/probe_phase3_run_job.py`, through ValidateTests under Python 3.14.7 with real ffmpeg. It drove the checkpoint's own `Rig`, `StubRunner` and test bodies, one fresh tmp dir per scenario, without editing the checkpoint. All 32 scenarios passed: every bound, both followed redirects, transcribed, english, no speech, OOM, instance track, takeover, stop, and the four picks.
- I have no delete tool, so I emptied the probe file. It should be deleted.

**Beyond the files named.** engine/server/data/subtitles.py: run_job needs four store functions that phases 1 and 2 left for later. Following the plan's module map and the precedent from phase 2, I added `requeue_translate_job`, `finish_translate_already_english`, `finish_translate_failed` and `mark_translate_finished` there.
tests/tmp/probe_phase3_run_job.py: a throwaway probe I wrote and then emptied. It should be deleted; I have no delete tool.

#### Phase 4 - Worker service process [code]

**Files touched.** engine/server/db/jobs/translate-worker.py (EDITED), .gitignore (EDITED), tests/active/test_translate_worker.py (EDITED)

**Checkpoint.** Seam: the `run` command as a subprocess (rung 2) with tmp --subtitles-db, --whitelist-db, --lock and --log and an empty queue, so no job is claimed and no GPU code is imported. The precedent is test_updater_worker.py's subprocess runs. heartbeat_loop is also called in-process (rung 1) for the stall guard. C1: while the test process holds fcntl.flock on the lock file, `run` exits 6, its log names the held lock, and the tmp subtitles.db is not created (or, if pre-created B1-shaped, gains neither a job column nor a heartbeat row). C2: a `run` subprocess on an idle queue writes a translate_worker_heartbeat row whose pid is the subprocess pid, and over about 12 s beat_at advances at least twice, with consecutive beats about 5 s apart. After SIGTERM it exits 0 within the unit's 60 s and releases the lock, so a fresh LOCK_NB flock succeeds. In-process, heartbeat_loop with progress['at'] set more than STALL_SECONDS in the past writes no beat over one tick, and it writes a beat once progress['at'] is refreshed.

**Intent.** translate-worker.py's run command is a single long-lived service: one instance at a time under an flock, beating a heartbeat row every 5 s from its own thread while the main loop makes progress.

- C1 - A second run against a held lock exits 6 having written nothing, the heartbeat included.
- C2 - A running worker writes its heartbeat every 5 s while idle and stops beating when its main loop stalls.

**Outcome.** ### `engine/server/db/jobs/translate-worker.py`
- **Module docstring.** A new paragraph describes `run`'s start-up order and says that numpy, faster_whisper and the CUDA wheels are imported only inside `WhisperRunner`.
- **New imports:** `fcntl`, `gc`, `os`, `shutil` and `signal`; from `server_config`, `SUBTITLE_MAX_BYTES` and `SUBTITLE_MAX_CHUNK_SECONDS`; from `data.subtitles`, `claim_translate_job`, `recover_translate_jobs` and `write_translate_heartbeat`.
- **New constants:**
  - `EXIT_LOCKED = 6`
  - `MODEL_NAME = "medium"` and `COMPUTE_TYPE = "int8_float16"`
  - `HEARTBEAT_SECONDS = 5.0`
  - `IDLE_UNLOAD_SECONDS = 300.0`
  - `STALL_SECONDS = 600.0`, with a comment on why the heartbeat stops after that long
  - `VAD_MIN_SILENCE_MS = 500` and `VAD_SPEECH_PAD_MS = 200`
- **`preload_cuda_libraries()`** loads, with `ctypes.CDLL(..., RTLD_GLOBAL)`, `libcublasLt.so.12` and `libcublas.so.12` from `nvidia/cublas/lib`, then `libcudnn.so.9` from `nvidia/cudnn/lib`. The paths come from `importlib.util.find_spec`.
- **`_float_audio(pcm)`:** turns s16le audio into float32 numpy, importing numpy only at call time.
- **`WhisperRunner`** is the real runner that `run_job` gets in production:
  - `model` starts as None.
  - `speech()` returns faster-whisper's Silero `get_speech_timestamps` spans, in samples.
  - `transcribe()` loads the model on first use (preload, then `WhisperModel("medium", device="cuda", compute_type="int8_float16")`). It runs `task="translate"` with `vad_filter=True` and the given language, and builds the segment list inside the call, so a CUDA out-of-memory error is raised there.
  - `unload()` drops the model and runs `gc.collect()`.
- **`heartbeat_loop(db_path, stop, progress)`** uses its own `connect_subtitles_db` connection. It beats at once, then every `HEARTBEAT_SECONDS` via `stop.wait`, writing `write_translate_heartbeat(conn, now_ms(), os.getpid())`. It skips the write while `time.monotonic() - progress["at"] > STALL_SECONDS`, reading the module global at each check, so lowering it from outside takes effect. A sqlite error is logged and retried on the next tick.
- **`serve(conn, args, runner, stop, progress)`** loops until stop. Each pass it refreshes `progress["at"]` and claims a job.
  - Idle, or when the claim errors (logged), it sleeps `POLL_SECONDS`, and unloads the model after `IDLE_UNLOAD_SECONDS` with no job.
  - It sleeps with `time.sleep`, not `stop.wait`, so the SIGTERM handler, which runs on this thread, can never deadlock in `Event.set` against this thread's own wait.
  - When it claims a job it logs it and runs `run_job`.
- **`setup_logging(log_path)`:** stdout plus a FileHandler, the same as `updater-worker.py`.
- **`command_run(args)`** runs these steps in order:
  1. Set up logging.
  2. Check ffmpeg with `shutil.which` (exit 1 if missing).
  3. Open the lock with `os.open(O_RDONLY | O_CREAT, 0o644)` and take `flock(LOCK_EX | LOCK_NB)`. If the lock is held, it logs `another worker holds <lock>` and returns 6 before `subtitles.db` is opened, so nothing is written.
  4. Install SIGTERM/SIGINT handlers that set stop.
  5. Open the store, then run `ensure_subtitles_schema` and `recover_translate_jobs`, logging the counts.
  6. Start the heartbeat as a daemon thread and call `serve` with `WhisperRunner()`.
  7. On the way out: set stop, join the heartbeat (up to 5 s), close the connection, close the lock fd (which releases the flock), and return 0.
- **`parse_args`:** a new `run` subparser with `CompactHelpFormatter`:
  - `--lock` (default `<repo>/engine/server/db/translate-worker.lock`)
  - `--log` (default `<repo>/engine/server/db/translate-worker.log`)
  - `--max-duration`, `--max-bytes` and `--max-chunk-seconds`, which `generate` already reads; each uses `_positive_int` and defaults to the `server_config` constants.
- **`main`** now dispatches to `command_enqueue` or `command_run`.
- **Not done: requeue-without-counting plus back-off for a locked `whitelist.db` at claim time** (`WhitelistBusy`, which phase 3 deferred to here). Neither checkpoint tests it. As it stands, a whitelist lookup still locked after the 30 s busy timeout fails that key permanently, like any other error.

### `.gitignore`
- Added `engine/server/db/translate-worker.lock` next to `engine-deploy.lock`, with a comment in the same style. The log is already covered by `*.log`.

### `tests/active/test_translate_worker.py`
- Not touched. As in phases 1 to 3, it does not exist yet; it is where the workflow promotes the checkpoint.

### Observed
- I wrote a throwaway probe, `tests/tmp/probe_phase4_drive.py`, that imports the checkpoint and calls its four test bodies, with the lock-holding fixture rebuilt in the probe, without running or editing the checkpoint file. All five cases passed in 53.7 s: both held-lock variants, the idle beat with SIGTERM, the stall and resume, and the in-process guard.
- Under ENGINE_PY, `libcublasLt.so.12`, `libcublas.so.12` and `libcudnn.so.9` load with `RTLD_GLOBAL` from the wheel `lib` dirs, in that order.
- **Not observed:** faster-whisper and ctranslate2 are **not installed** in `engine/.pixi`. `importlib.metadata` found neither, and `import faster_whisper` raises ModuleNotFoundError. So `WhisperRunner`'s calls are written from faster-whisper 1.2.1's API as the plan gives it, and were not observed: `get_speech_timestamps(audio, VadOptions(min_silence_duration_ms, speech_pad_ms))` returning dicts with sample `start`/`end`, and `WhisperModel.transcribe(..., task, language, vad_filter)` returning `(segments, info.language)`. The checkpoint never imports them. The environment gate's install plus a real job (the planned AC7 evidence run) would confirm them. The gate recorded at Step 6 as done before Phase 1 does not appear to have installed faster-whisper.

**Beyond the files named.** tests/tmp/probe_phase4_drive.py: a throwaway probe that drove the checkpoint's test bodies against the new code; emptied, and should be deleted (I have no delete tool).
tests/tmp/probe_phase4_cuda_libs.py: a throwaway probe that showed the CUDA wheel library names and that they load with RTLD_GLOBAL; emptied, and should be deleted.
tests/tmp/probe_phase4_fw.py: a throwaway probe that found faster-whisper and ctranslate2 missing from engine/.pixi; emptied, and should be deleted.


