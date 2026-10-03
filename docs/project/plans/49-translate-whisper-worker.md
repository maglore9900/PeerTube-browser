# Translate: Whisper generation worker

## Requirements

Split from `docs/project/plans/18-english-subtitles.md`, which holds the decisions, the S0 feasibility results and the reasoning behind them. It was B2 there. B2 was split again (operator, 2026-10-03) because it needed more than four phases:
- this plan, the worker;
- `docs/project/plans/50-translate-generation-in-page.md`, the routes and the page.

This plan builds on B1, `docs/project/plans/archive/48-translate-instance-captions.md` (delivered), because the worker writes into B1's store.

### B1's store and fetch code

- **Table:** `subtitles` in `engine/server/db/subtitles.db`, columns `video_id`, `instance_domain`, `target_language`, `state`, `source`, `fetched_at`, `track_text`, `cues_json`, primary key `(video_id, instance_domain, target_language)`. `state` and `source` are plain TEXT with no CHECK, so job states and the `whisper` source fit without a rebuild. B1 writes only `ready` rows with source `instance`.
- **Cues:** one compact JSON array per row in `cues_json`, not a cue table.
- **Connection:** `connect_subtitles_db` sets a 30 s busy timeout and no deadline handler. B1 leaves the journal mode at its default.
- **Store code:** `connect_subtitles_db`, `ensure_subtitles_schema`, `fetch_ready_subtitles` and `store_ready_subtitles` in `engine/server/data/subtitles.py`. `fetch_ready_subtitles` reads only `state='ready'` rows; `store_ready_subtitles` upserts the whole row, replacing whatever state the key held.
- **Fetch and parse code:** `fetch_instance_track`, `fetch_bounded`, `pick_english_track_path` and `parse_webvtt` in `engine/server/api/handlers/internal_translate.py`, a request-handler module. The worker imports them from there, or moves them into `engine/server/data/` first.

### Asked for

A worker process that takes queued translate jobs and produces English cues for a video with Whisper's `translate` task on the RTX 3070. It is subtitles only: no dubbed audio and no text-to-speech. This build ends at "a queued job becomes stored English cues". Nothing on the website changes. A job is queued from the command line, and plan 50 adds the route that queues one from the page.

### Purpose

B1 shows English only when the source instance already has an English track, which is rare. This worker produces English for any non-English video up to 60 minutes long, and plan 50 connects it to the page.

### What S0 measured (2026-10-03, `.scratch/18-subtitles/`)

- faster-whisper 1.2.1 and CTranslate2 4.8.2 run on the 3070 with driver 595.91. The cuBLAS 12 and cuDNN 9 pip wheels were preloaded with `ctypes`, with no `LD_LIBRARY_PATH`. S0 used a uv venv on Python 3.12.
- `medium` at `int8_float16` is the agreed default. The operator judged its quality good enough (verdict, 2026-10-03).
- The process peaked at 1.3 to 2.1 GiB. The card's total peaked at 3.9 GiB of 8 GiB, with the desktop at about 1.7 GiB. The model loaded in 1.9 s once cached.
- On a 52:28 Italian video (146 MB at 240p, about 1.6 MB/s), the whole job took 92.7 s with the GPU busy for 89.7 s, so translation kept pace with the download. On a short French video, the first line came 2.1 s after the download started.
- If ffmpeg reads a fragmented MP4 straight from its URL, it stalls (R1). A sequential download piped into ffmpeg's stdin works. Nothing is written to disk: the media passes through memory only.
- With 30 s hard chunks, a sentence was split at a chunk boundary.
- A 52-minute translation is about 48 KB of text.

### Acceptance criteria

- **AC1: Queue.** Jobs live in a persistent queue in B1's `subtitles.db`, so a restart loses no queued work.
  - Enqueuing is idempotent on the key `(video_id, instance_domain, target_language='en')`: a key that is queued, running or finished gets no new job.
  - The queue has a total cap.
  - The worker runs one job at a time.
  - A job left `running` by a crash is retried once at the next start, then marked `failed`.
- **AC2: Command-line enqueue.** A command-line entry point puts a video on the queue by `id` and `host`, using the same enqueue function plan 50's route will call.
- **AC3: Generation.**
  1. The worker checks for an instance English track again (`fetch_instance_track`); if there is one, it is stored as a `ready` row with source `instance` (`store_ready_subtitles`).
  2. Otherwise it downloads the video's smallest https media file in one sequential pass and pipes it into ffmpeg.
  3. It runs Whisper `translate` with voice-activity filtering, on chunks cut at silence, with a maximum chunk length.
  4. The cues are stored under the key with source `whisper`.
  5. If Whisper detects English, the job records `already_english` and stores no cues.
- **AC4: Cues while running.** The cues of each finished chunk are appended to the store while the job is `running`, so a reader can fetch what exists so far (plan 18, Q1 for B2). The job ends `ready`, `already_english` or `failed`, with an error text for `failed`.
- **AC5: Bounds.** The worker refuses:
  - a video longer than `SUBTITLE_MAX_DURATION`, default 60 minutes;
  - a host not in the whitelist;
  - a media URL that is not https, or that redirects off its host;
  - a download larger than `SUBTITLE_MAX_BYTES`.
- **AC6: Heartbeat.** While it runs, the worker writes a heartbeat every few seconds, so plan 50 can tell whether generation is available.
- **AC7: Memory.** With the desktop running, the worker process's peak VRAM stays at or under 3,072 MiB, measured with `nvidia-smi` during a real job. A CUDA out-of-memory error marks the job `failed` and is not retried in a loop. The model is unloaded after 5 minutes idle.

### Scope

In scope: AC1 to AC7, plus the install of faster-whisper into `engine/.pixi`.

Out of scope:
- the Engine and Client routes, the "generation available" check in the page, and any frontend change (plan 50);
- target languages other than English, and a per-profile language setting (a possible future enhancement);
- pruning stored translations (a possible future feature, see Limitations);
- bulk generation;
- backfilling `videos.language`;
- serving results back to instances.

### Consistency constraints

- The worker is a separate long-running process, like `updater-worker.py`. The model never loads inside the Engine.
- Whisper's dependencies go into `engine/.pixi`, through its existing manual pip step (memory `engine-pixi-env-is-pip-filled`), never into the root `pixi.toml`, which un regenerates (memory `root-pixi-toml-regenerated-drops-pytest`). The Engine never imports them, so it keeps running on a machine without a GPU.
- The worker writes only into B1's store: `subtitles.db` (plan 48, Storage).
- The worker is pinned to the 3070 with `CUDA_VISIBLE_DEVICES`. The display stays on that card (plan 18, Q1).
- Remote fetches reuse `normalize_host` (`engine/server/data/moderation.py:45`) and the https-only rule.

### Decisions (operator, 2026-10-03)

- **Cues while running:** yes (AC4).
- **Memory limit:** 3,072 MiB for the worker process (AC7).
- **Idle unload:** after 5 minutes (AC7).
- **Environment:** `engine/.pixi`. Worktrees already symlink main's copy. Checked 2026-10-03 (`pip list` in `engine/.pixi`):
  - Python is 3.12.
  - The environment already carries `torch 2.5.1+cu121`, with `nvidia-cublas-cu12 12.1.3.1` and `nvidia-cudnn-cu12 9.1.0.70`.
  - It pins `transformers 4.57.6`, `huggingface-hub 0.36.0`, `tokenizers 0.22.2` and `numpy 2.4.1`.

  Not yet checked:
  - that installing faster-whisper keeps those pins, because S0's fresh environment resolved to `huggingface-hub 1.33` and `tokenizers 0.23.2`;
  - that CTranslate2 4.8.2 runs on cuDNN 9.1, because S0 used 9.27.

  The build checks both first, with a dry run of the install (R7).

## High-level plan

### Approach

- **Install check, before any phase.**
  1. Do a pip dry run of faster-whisper into `engine/.pixi`.
  2. If no pinned package moves, install it and run a tiny `translate` on CUDA in that environment.
  3. Run the Engine's tests that use the query encoder.

  If a pin would move, stop and put it to the operator.
- **Queue (AC1, AC2).** B1's `subtitles` table gains the job states (`queued`, `running`, `failed`, `already_english`) and their timestamps. Per-chunk appends (AC4) need either a new cue table or a rewrite of the row's `cues_json` blob per chunk. The enqueue function inserts a row idempotently and checks the cap. The worker claims the oldest `queued` row in one transaction. This plan sets `journal_mode=WAL` on `subtitles.db`, because B1's Engine route and the worker both write. A small CLI calls the enqueue function.
- **Media pipeline (AC3, AC5).** Resolve the video on its instance and apply the bounds. Pick the smallest https file. Stream it with a sequential download into ffmpeg's stdin, with no file on disk. Read 16 kHz mono PCM from ffmpeg's stdout.
- **Transcription (AC3, AC4, AC7).**
  - Buffer the audio until voice activity shows a silence, or the maximum chunk length is reached.
  - Translate that chunk, then append its cues with the chunk's time offset.
  - Detect the language on the first chunk, and stop as `already_english` if it is English.
  - Catch CUDA out-of-memory and record it as `failed`.
- **Worker process (AC1, AC6, AC7).** It loops: heartbeat, claim, run, and unload the model after 5 minutes idle. At start it resets a stale `running` job to `queued` once, and to `failed` the second time.
- **Close-out.** `DEPLOYMENT.md` gains the worker's service unit, the install step and the GPU pinning. `CONTEXT.md` gains **Translate job**.

### Alternatives considered

- **A separate environment for Whisper.** Rejected by the operator. `engine/.pixi` already holds CUDA torch and the CUDA libraries.
- **Download to a temporary file, then translate.** Rejected: ffmpeg stalls on fragmented MP4 over HTTP (R1), the first line comes later, and it leaves files to clean up.
- **Fixed 30 s chunks with overlap and de-duplication.** This works, but de-duplicating overlapping text is fragile. Cutting at silence avoids it.
- **`large-v3`.** Not needed at the quality the operator accepted, and it uses more VRAM.
- **The model inside the Engine.** Rejected by the constraints.

### Risks

- **R1: Remote media reads.** ffmpeg on a remote fragmented MP4 jumps around the file and stalls: more than 7 minutes, against about 30 s for a direct sequential read. The sequential pipe is required.
- **R2: Chunk boundaries.** Cutting at silence fixes most splits. Long unbroken speech still hits the maximum chunk length.
- **R3: VRAM contention.** The desktop shares the 3070. There was 4 GiB of headroom at peak, and out-of-memory errors are handled as in AC7.
- **R4: SSRF.** Media URLs come from instance JSON. Only the whitelisted host, https only, no redirect off the host, and a size cap.
- **R5: Whisper quality.** Music or noise can produce made-up or repeated lines. `vad_filter` reduces this.
- **R6: Language detection.** Detection on the first chunk can mark a video with an English intro as `already_english`.
- **R7: Shared environment.** Installing faster-whisper into `engine/.pixi` could move packages the Engine's query encoder needs, or add a second set of CUDA libraries. The install check covers this.
- **R8: Two writers on one SQLite file.** The Engine and the worker both write. WAL and short transactions help, but the "database is locked" history (memory `engine-concurrent-start-locks-random-cache`) says to test it.

### Limitations

- English only. One job at a time.
- Stored translations are never pruned. At about 48 KB per hour of video, growth is small. Pruning is a possible future feature (operator, 2026-10-03).

### Tradeoffs accepted

- A second service to run, in exchange for keeping the model out of the Engine's request process.
- On-demand latency in exchange for spending no GPU time on videos nobody watches.
