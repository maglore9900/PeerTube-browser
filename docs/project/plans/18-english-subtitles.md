# English subtitles

## Requirements

Status: draft. The operator asked for this write-up. The questions under **Open questions** are not answered yet, and a build starts once they are.

### Asked for

Optional English subtitles for videos that are not in English, generated with Whisper. Subtitles only: no dubbed audio and no text-to-speech. Baseline hardware is an 8 GB NVIDIA card, an RTX 3070, shared with everything else running on that machine.

### Purpose

A visitor can follow a video in a language they don't speak. The feature is optional. With no GPU worker configured, the site works exactly as it does today and shows no subtitle control.

### What the current code does (checked against the tree, read-only)

- **Playback is a cross-origin iframe.** The video page sets `#video-embed` to the source instance's `/videos/embed/<uuid>` (`client/frontend/src/pages/video-page/index.ts:212-219`). We can't add a `<track>` element to the instance's player.
- **CSP:** every page allows `frame-src https:` and `connect-src 'self' https:`. The nginx config in `DEPLOYMENT.md:313` carries `frame-src https:`.
- **Boundary:** the frontend talks only to the Client gateway (`tests/check-frontend-client-gateway.sh`), and the Client talks to the Engine over the authenticated bridge (`ENGINE_BRIDGE_TOKEN`, `client/backend/lib/engine_api_client.py`).
- **Language data:** the `videos` table (`engine/crawler/schema.sql:29`) stores no language. It does store `duration`. PeerTube's `/api/v1/videos/{id}` returns `language` and the file URLs. `/api/v1/videos/{id}/captions` lists any captions the instance already has.
- **Demand:** on the 890,052-row corpus, 58.8% of titles are ASCII-only and 3.7% carry Cyrillic. ASCII-only doesn't mean English, but most of the corpus is probably English, so generating subtitles on demand fits better than generating them in bulk.
- **GPU, measured 2026-09-27:** `lspci` shows an RTX 3070 (GA104, 8 GB) and an AMD Raphael, which is the Ryzen CPU's integrated GPU. `nvidia-smi` shows the desktop (gnome-shell, Xwayland, browser and apps) using 1,479 MiB on the 3070, which reports `Disp.A On`, so the 3070 is currently driving a display. About 6.7 GB is free. No Engine process was on the GPU.

### Acceptance criteria (draft)

- **AC1: Feature gate.** The Engine reports whether subtitles are available, meaning a worker is configured and alive. When they are not, the video page shows no subtitle control and makes no subtitle requests.
- **AC2: Existing captions first.** Before any GPU work, the Engine checks the instance's `/captions` list. If there is an English track, it fetches it, validates it and caches it as our own `.vtt`.
- **AC3: Generation.** Otherwise a job fetches the video's smallest media file from its instance, extracts the audio with ffmpeg and runs Whisper's `translate` task. The result is stored as `.vtt` keyed by `(video_id, instance_domain)`. When Whisper detects English, the job records "already English" and generates nothing.
- **AC4: One job at a time.** The worker runs one job at a time on the GPU from a persistent queue, so a restart doesn't lose queued work. A repeated request for a queued, running or finished video creates no new job.
- **AC5: Bounds.** A video longer than `SUBTITLE_MAX_DURATION` is refused. So is a request whose host is not in the whitelist, a media URL that is not https, or a download larger than `SUBTITLE_MAX_BYTES`. The queue has a total cap, and each client address has a request limit.
- **AC6: Serving.** The Client exposes subtitle status (none, queued, running, ready, already English, failed) and the `.vtt` file itself, both through the gateway. The frontend never fetches captions from an instance directly.
- **AC7: Display.** A layer over the player shows the current cue, kept in sync with the embed's playback position through the PeerTube embed API. Caption text is inserted as text, never as HTML.
- **AC8: Memory ceiling.** On the RTX 3070 baseline, with the desktop running, the worker's peak VRAM stays under an agreed limit, measured with `nvidia-smi` during a real job. The model defaults to the largest one that fits.

### Scope

In scope: AC1 to AC8. English is the only target language.

Out of scope:
- dubbing, TTS and voice cloning;
- target languages other than English, because Whisper's `translate` task only produces English;
- generating subtitles ahead of time for the whole corpus;
- adding a `language` column to the crawl;
- replacing the iframe with our own `<video>` element and hls.js;
- serving the subtitles back to the source instance.

### Consistency constraints

- The worker is a separate long-running process, like `updater-worker.py`, not part of the Engine's request process. The model never loads inside the Engine.
- Whisper's dependencies (faster-whisper, CTranslate2, and CUDA/cuDNN libraries) go in their own environment, not in `engine/.pixi`. That environment is filled by a manual pip step (memory `engine-pixi-env-is-pip-filled`), and the Engine must keep running on machines without a GPU.
- The routes follow the existing Client → Engine bridge pattern and its auth, and the new frontend calls go through the Client gateway.
- Remote fetches reuse the crawler's host normalisation and https-only rule.

### Open questions

- **Q1: Which GPU the worker uses.** The 3070 is currently driving the desktop (see above). Options: (a) move the display to the iGPU so the 3070 is headless, which frees about 1.5 GB and stops desktop use from taking VRAM mid-job; or (b) leave the display on the 3070 and budget for it. Either way the worker pins the card with `CUDA_VISIBLE_DEVICES`.
- **Q2: Trigger.** Options: (a) a "Generate English subtitles" button on the video page; or (b) queue automatically when a non-English video is opened. (b) spends GPU time on every non-English page view.
- **Q3: Who may trigger generation.** The Client is public. Options: any visitor, rate-limited per address (AC5); or only profiles; or only the operator, with visitors seeing subtitles that already exist.
- **Q4: Maximum duration.** This sets the worst-case job length and download size. Suggested: 60 minutes.
- **Q5: Fullscreen.** When the viewer fullscreens the embed's own player, our layer isn't visible. Options: (a) accept that, subtitles show only in the page view; or (b) add our own fullscreen button that fullscreens the container holding both the iframe and the layer.
- **Q6: Where production generates.** If the public deployment has no GPU, this machine runs the worker and pushes `.vtt` files and status to the server. That needs a push path and a way for the server to receive requests. If the deployment is this machine, none of that is needed.

## High-level plan

### Approach

The build runs in five phases, P0 to P4, and starts with a spike.

- **P0: Spike (throwaway, no gate).**
  - Measure faster-whisper `large-v3` at int8 against `medium` on the 3070: peak VRAM, speed relative to realtime, and quality on a few Cyrillic, German and Japanese videos from the corpus.
  - Confirm that the PeerTube embed API reports playback position through our sandboxed iframe on two or three real instances, and whether the embed URL needs `?api=1`.
  - Confirm that the instances' media files can be downloaded server-side.
  - The results fix the model default and settle AC7's approach.
- **P1: Storage and queue (AC4).** A `subtitles` table in its own SQLite DB records key, state, source (instance or Whisper), detected language, model, error and timestamps. A `.vtt` directory sits beside it. Queue operations are idempotent, and the queue survives restarts.
- **P2: Worker (AC2, AC3, AC5, AC8).** The worker process takes a job, checks for instance captions, and otherwise downloads the media within its caps, extracts the audio and runs Whisper `translate`. It then writes the `.vtt` and the job state. It loads the model once, and can unload it after an idle timeout, as the Engine does with its query encoder.
- **P3: Engine and Client routes (AC1, AC5, AC6).**
  - Engine: a status/request route and a `.vtt` read route, behind the bridge token. A heartbeat from the worker decides "available".
  - Client: gateway routes with per-address limits.
- **P4: Frontend (AC1, AC7).** On the video page: the control and its status states, polling while a job is queued or running, and a VTT parser that works in `textContent` only. The layer is positioned over `#video-embed` and synced through the embed API. The layer's CSS goes in `video.css`.

`DEPLOYMENT.md` gains the worker's service unit, its environment and the GPU pinning. `CONTEXT.md` gains **Subtitle job**. These are the close-out, not a phase.

### Alternatives considered

- **Chatterbox, or the full voice-translator pipeline:** that produces dubbed audio, which the operator ruled out.
- **Whisper transcription followed by a separate translation model (NLLB, or an LLM):** this would allow target languages other than English. It needs a second model in VRAM and doubles the error sources. `translate` does it in one pass for English.
- **`large-v3-turbo`:** it is faster, but OpenAI trained it without translation data, so its `translate` output is poor. Excluded unless P0 shows otherwise.
- **Our own `<video>` element with hls.js instead of the embed:** this gives native `<track>` subtitles and fullscreen, but replaces the player, depends on each instance's CORS policy for its media, and is roadmap F11-M2 work.
- **Running the model inside the Engine:** GPU memory and a CUDA dependency would enter the process that serves every request. That is rejected by the consistency constraints above.
- **Batch generation for every non-English video:** at about 1 to 2 minutes of GPU time per 20-minute video, and with no language column to select by, this costs far more than on-demand for a small share of the corpus.

### Risks

- **R1: Public GPU trigger.** Anyone can queue GPU work and remote downloads. AC5's caps and Q3 cover this, and the security audit should cover the new routes after the build.
- **R2: Server-side fetch of remote URLs.** Media URLs come from instance JSON, so this is an SSRF surface. Only whitelisted hosts, https only, no redirects off the host, and a size cap.
- **R3: Untrusted caption files.** Instance captions and Whisper output are both untrusted text. They are parsed and rendered as text, and a malformed file is rejected, not partly served.
- **R4: Embed API availability.** It depends on the instance's PeerTube version and embed settings, and P0 measures it. Where it's missing, the control is hidden for that video.
- **R5: VRAM contention.** If the desktop or another process takes VRAM mid-job, the job fails with out-of-memory. The worker marks it failed and doesn't retry in a loop. Q1 decides whether this can happen at all.
- **R6: CUDA libraries.** CTranslate2 needs particular cuBLAS/cuDNN versions. The driver reports CUDA 13.2. Compatibility with the pip wheels has not been checked, and P0 checks it.
- **R7: Whisper quality.** On music, noise or several speakers, Whisper can produce repeated or made-up lines. Voice-activity filtering (faster-whisper's `vad_filter`) reduces this. Failures are shown as they are.

### Limitations

- English is the only target language.
- The first viewer of a video waits for the job, about 1 to 2 minutes per 20 minutes of video on the baseline (an estimate, measured in P0).
- Subtitles aren't visible in the embed's own fullscreen unless Q5 is answered (b).

### Tradeoffs accepted

- A second service to run, the worker, in exchange for keeping the Engine free of GPU dependencies.
- On-demand latency in exchange for spending no GPU time on videos nobody watches.
