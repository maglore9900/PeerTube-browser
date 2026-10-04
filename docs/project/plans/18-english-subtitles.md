# English subtitles

## Requirements

Status: split (2026-10-03). Every question under **Open questions** is answered, and S0 found the feature worth building. There are three builds, in this order:
1. B1, delivered: `docs/project/plans/archive/48-translate-instance-captions.md`.
2. B2's worker, delivered: `docs/project/plans/archive/49-translate-whisper-worker.md`.
3. B2's page side, delivered: `docs/project/plans/archive/50-translate-generation-in-page.md`.

B2 was split in two because it needed more than four phases. This file stays as the record of the decisions and the S0 results.

### Asked for

Optional English subtitles for videos that are not in English, generated with Whisper. Subtitles only: no dubbed audio and no text-to-speech. Baseline hardware is an 8 GB NVIDIA card, an RTX 3070, shared with everything else running on that machine.

### Purpose

A visitor can follow a video in a language they don't speak. The feature is optional. With no GPU worker configured, the site works exactly as it does today and shows no subtitle control.

### What the current code does (checked against the tree, read-only)

- **Playback is a cross-origin iframe.** The video page sets `#video-embed` to the source instance's `/videos/embed/<uuid>` (`client/frontend/src/pages/video-page/index.ts:212-219`). We can't add a `<track>` element to the instance's player.
- **CSP:** every page allows `frame-src https:` and `connect-src 'self' https:`. The nginx config in `DEPLOYMENT.md:313` carries `frame-src https:`.
- **Boundary:** the frontend talks only to the Client gateway (`tests/check-frontend-client-gateway.sh`), and the Client talks to the Engine over the authenticated bridge (`ENGINE_BRIDGE_TOKEN`, `client/backend/lib/engine_api_client.py`).
- **Language data:** the `videos` table (`engine/crawler/schema.sql:29`) stores `duration` and `language`, the PeerTube language code (for example `en`). The crawler fills `language` for the videos it crawls, and `/api/video` fills it in `whitelist.db` when a video page is viewed, until the next sync reloads that table from `crawl.db`. Rows crawled before the column existed stay empty until a full re-crawl or a backfill, so coverage is sparse. PeerTube's `/api/v1/videos/{id}` returns `language` and the file URLs. `/api/v1/videos/{id}/captions` lists any captions the instance already has.
- **Demand:** on the 890,052-row corpus, 58.8% of titles are ASCII-only and 3.7% carry Cyrillic. ASCII-only doesn't mean English, but most of the corpus is probably English, so generating subtitles on demand fits better than generating them in bulk.
- **GPU, measured 2026-09-27:** `lspci` shows an RTX 3070 (GA104, 8 GB) and an AMD Raphael, which is the Ryzen CPU's integrated GPU. `nvidia-smi` shows the desktop (gnome-shell, Xwayland, browser and apps) using 1,479 MiB on the 3070, which reports `Disp.A On`, so the 3070 is currently driving a display. About 6.7 GB is free. No Engine process was on the GPU.

### Acceptance criteria (draft)

- **AC1: Feature gate.** The Engine reports whether subtitles are available, meaning a worker is configured and alive. When they are not, or the visitor has no profile, the video page shows no subtitle control and makes no subtitle requests.
- **AC2: Existing captions first.** Before any GPU work, the Engine checks the instance's `/captions` list. If there is an English track, it fetches it, validates it and caches it as our own `.vtt`.
- **AC3: Generation.** Otherwise a job fetches the video's smallest media file from its instance, extracts the audio with ffmpeg and runs Whisper's `translate` task. The result is stored as `.vtt` keyed by `(video_id, instance_domain, target_language)`. `target_language` is always `en` for now, and is in the key so a later target-language setting needs no migration. When Whisper detects English, the job records "already English" and generates nothing.
- **AC4: One job at a time.** The worker runs one job at a time on the GPU from a persistent queue, so a restart doesn't lose queued work. A repeated request for a queued, running or finished video creates no new job.
- **AC5: Bounds.** A video longer than `SUBTITLE_MAX_DURATION` is refused. So is a request whose host is not in the whitelist, a media URL that is not https, or a download larger than `SUBTITLE_MAX_BYTES`. The queue has a total cap. A request without a valid profile is refused (Q3).
- **AC6: Serving.** The Client exposes subtitle status (none, queued, running, ready, already English, failed) and the `.vtt` file itself, both through the gateway. The frontend never fetches captions from an instance directly.
- **AC7: Display.** A layer over the player shows the current cue, kept in sync with the embed's playback position through the PeerTube embed API. Caption text is inserted as text, never as HTML.
- **AC8: Memory ceiling.** On the RTX 3070 baseline, with the desktop running, the worker's peak VRAM stays under an agreed limit, measured with `nvidia-smi` during a real job. The model defaults to the largest one that fits.

### Scope

In scope: AC1 to AC8. English is the only target language.

Out of scope:
- dubbing, TTS and voice cloning;
- target languages other than English, because Whisper's `translate` task only produces English. A per-profile target-language setting is a possible future enhancement once this works (operator, 2026-10-03). It would need Whisper transcription followed by a separate translation model (see Alternatives);
- generating subtitles ahead of time for the whole corpus;
- backfilling `videos.language` for rows crawled before the column existed;
- replacing the iframe with our own `<video>` element and hls.js;
- serving the subtitles back to the source instance.

### Consistency constraints

- The worker is a separate long-running process, like `updater-worker.py`, not part of the Engine's request process. The model never loads inside the Engine.
- Whisper's dependencies go into `engine/.pixi`, by the operator's decision (2026-10-03, plan 49 Q4). This replaces the earlier rule of a separate environment. The environment already holds CUDA torch with cuBLAS 12 and cuDNN 9, and it is filled by a manual pip step (memory `engine-pixi-env-is-pip-filled`). The Engine never imports Whisper, so it keeps running on machines without a GPU.
- The routes follow the existing Client → Engine bridge pattern and its auth, and the new frontend calls go through the Client gateway.
- Remote fetches reuse the crawler's host normalisation and https-only rule.

### Open questions

- **Q1: Which GPU the worker uses. Decided (operator, 2026-10-03): (b).** The displays are physically plugged into the 3070, so the display stays on it and the worker budgets for desktop use. R5 (VRAM contention) therefore applies, and S0 measures it. The 3070 is currently driving the desktop (see above). Options: (a) move the display to the iGPU so the 3070 is headless, which frees about 1.5 GB and stops desktop use from taking VRAM mid-job; or (b) leave the display on the 3070 and budget for it. Either way the worker pins the card with `CUDA_VISIBLE_DEVICES`.
- **Q2: Trigger. Decided (operator, 2026-10-03):** a per-video toggle on the video page, labelled **Translate**, never "CC" or "Captions", so it can't be confused with the captions PeerTube's own player offers. It works like a closed-caption button. Turning it on shows the subtitles if they exist and queues a job if they don't. Turning it off hides them. Nothing is queued automatically.
- **Q3: Who may trigger generation. Decided (operator, 2026-10-03):** only a visitor with a profile (`X-Profile-Key`, CONTEXT.md **Profile**). Without a profile, the toggle is not shown.
- **Q7: Toggle persistence. Decided (operator, 2026-10-03):** Translate stays on for later videos until it is turned off, like a player's CC setting. Where the setting is kept, on the profile or in the browser's `localStorage`, is left to B1.
- **Q4: Maximum duration. Decided (operator, 2026-10-03): 60 minutes** to start with, revisited if it proves a problem. This sets the worst-case job length and download size. Suggested: 60 minutes.
- **Q5: Fullscreen. Decided (operator, 2026-10-03): (a), accepted as a limitation.** Translations show only while the video plays in the page. When the viewer fullscreens the embed's own player, our layer isn't visible. Options: (a) accept that, subtitles show only in the page view; or (b) add our own fullscreen button that fullscreens the container holding both the iframe and the layer.
- **Q6: Where production generates. Decided (operator, 2026-10-03):** PeerTube Browser runs locally, reachable at most on the local LAN. The worker runs on the same machine as the Engine, so there is no push path. Abuse by visitors is a minor concern, so the per-address request limit in AC5 is dropped. The duration, size and queue caps and the remote-fetch rules stay, because they protect against bad instance data and runaway GPU use, not against visitors.

## High-level plan

### Approach

**Split (operator, 2026-10-03).** The work is a spike followed by two builds, each with its own plan file. If production has no GPU, a third plan would be needed for a push path, but the deployment is local (Q6), so there is none.
- **S0:** a feasibility prototype. It is throwaway work under `.scratch/18-subtitles/` and is not a build. It is a terminal tool: given the URL of a video being watched, it streams the video's audio from its instance, runs Whisper `translate`, and prints the English lines with timestamps as they are produced. It reports the detected language, how fast it runs compared with the video's length, and the peak VRAM while the desktop is in normal use. Nothing is shown in the video. If the output isn't worth having, nothing is built (operator, 2026-10-03). The embed API check moves to B1.
- **B1: Translate with instance captions.** The toggle, the display layer, the embed sync, and serving an instance's existing English track through the Client and Engine (AC2, AC6, AC7, and AC1 limited to instance tracks). No GPU work.
- **B2: Whisper generation.** The queue, the worker, its environment, the availability heartbeat and the bounds (AC3, AC4, AC5, AC8, and AC1 in full). The toggle also queues a job when no track exists.

**S0 results so far (2026-10-03, faster-whisper 1.2.1, CTranslate2 4.8.2, `medium` int8_float16 on the 3070, desktop running).** The prototypes are `.scratch/18-subtitles/translate_probe.py` (download first) and `translate_stream.py` (sequential download piped into ffmpeg, translated in 30 s chunks).
- **CUDA (R6):** the pip cuBLAS 12 and cuDNN 9 wheels run with driver 595.91. They are preloaded with `ctypes`, with no `LD_LIBRARY_PATH`.
- **French, 8:10, video.antopie.org:** translated in 21.2 s (23x realtime). Peak 3,869 MiB total, 2,124 MiB for the process, desktop baseline 1,737 MiB. The English is readable, with some errors on proper nouns and acronyms.
- **French, 0:58, tube-cycle-2.apps.education.fr, streamed:** the first English line came 2.1 s after the download started. Downloading 5.2 MB took 2.1 s, and the whole job took 2.7 s wall time (1.8 s on the GPU). Peak 3,053 MiB total, 1,292 MiB for the process. Language detected as `fr` with p=1.00.
- **Italian, 52:28, tube.rsi.cnr.it:** with download-first, ffmpeg stalled (R8). Streamed, the translation reads well. Downloading 146.2 MB took 92.0 s (about 1.6 MB/s). The whole job took 92.7 s wall time, 89.7 s of it on the GPU, so translation kept pace with the download and finished about 34x faster than realtime. Peak 3,683 MiB total, 1,868 MiB for the process, desktop baseline 1,753 MiB. A video near the 60-minute cap takes about 1.5 minutes.
- **Embed API (R4), tube.rsi.cnr.it:** an iframe with the same `sandbox="allow-scripts allow-same-origin"` as `video-page.html`, loading `/videos/embed/<uuid>?api=1`, worked with `@peertube/embed-api`'s `PeerTubePlayer`. `ready` resolved within 1 s, play and pause arrived as `playbackStatusChange`, and `playbackStatusUpdate` streamed the position. The page used `.scratch/18-subtitles/embed_check.html`. With the 52-minute Whisper output overlaid as plain text, the line matching the position showed during playback and after a seek: at 12:05 it showed the `[0:12:00 -> 0:12:06]` cue. Other instances are still unchecked, and R4 still applies to them (hide the toggle when `ready` doesn't resolve).
- **Verdict (operator, 2026-10-03):** worth building. The model default is `medium`, since its quality is good enough, so the `large-v3` comparison was not run. AC8's memory limit is set from the `medium` figures above.
- **No speech, 2:48, lone.earth:** no lines, and the detected language was `en` at p=0.51. The instance has an English caption for this video, so AC2 would have served that instead.

The phases below, P0 to P4, describe the whole feature. B1 takes the display and serving parts of P1, P3 and P4, and B2 takes the rest.

- **P0: Spike (throwaway, no gate).**
  - Measure faster-whisper `large-v3` at int8 against `medium` on the 3070: peak VRAM, speed relative to realtime, and quality on a few Cyrillic, German and Japanese videos from the corpus.
  - Confirm that the PeerTube embed API reports playback position through our sandboxed iframe on two or three real instances, and whether the embed URL needs `?api=1`.
  - Confirm that the instances' media files can be downloaded server-side.
  - The results fix the model default and settle AC7's approach.
- **P1: Storage and queue (AC4).** A `subtitles` table in its own SQLite DB records key, state, source (instance or Whisper), detected language, model, error and timestamps. A `.vtt` directory sits beside it. Queue operations are idempotent, and the queue survives restarts. As shipped by B1, there is no `.vtt` directory: `engine/server/data/subtitles.py` keeps the original track text and the parsed cues (`track_text`, `cues_json`) in the `subtitles` row in `engine/server/db/subtitles.db`.
- **P2: Worker (AC2, AC3, AC5, AC8).** The worker process takes a job, checks for instance captions, and otherwise downloads the media within its caps, extracts the audio and runs Whisper `translate`. It then writes the `.vtt` and the job state. It loads the model once, and can unload it after an idle timeout, as the Engine does with its query encoder.
- **P3: Engine and Client routes (AC1, AC5, AC6).**
  - Engine: a status/request route and a `.vtt` read route, behind the bridge token. A heartbeat from the worker decides "available".
  - Client: gateway routes that require a profile.
- **P4: Frontend (AC1, AC7).** On the video page: the control and its status states, polling while a job is queued or running, and a VTT parser that works in `textContent` only. The layer is positioned over `#video-embed` and synced through the embed API. The layer's CSS goes in `video.css`.

`DEPLOYMENT.md` gains the worker's service unit, its environment and the GPU pinning. `CONTEXT.md` gains **Translate job** and **Translate** (our toggle and its subtitles, as distinct from an instance's own PeerTube captions). These are the close-out, not a phase.

### Alternatives considered

- **Chatterbox, or the full voice-translator pipeline:** that produces dubbed audio, which the operator ruled out.
- **Whisper transcription followed by a separate translation model (NLLB, or an LLM):** this would allow target languages other than English. It needs a second model in VRAM and doubles the error sources. `translate` does it in one pass for English.
- **`large-v3-turbo`:** it is faster, but OpenAI trained it without translation data, so its `translate` output is poor. Excluded unless P0 shows otherwise.
- **Our own `<video>` element with hls.js instead of the embed:** this gives native `<track>` subtitles and fullscreen, but replaces the player, depends on each instance's CORS policy for its media, and is roadmap F11-M2 work.
- **Running the model inside the Engine:** GPU memory and a CUDA dependency would enter the process that serves every request. That is rejected by the consistency constraints above.
- **Batch generation for every non-English video:** at about 1 to 2 minutes of GPU time per 20-minute video, and with `videos.language` empty for most existing rows, this costs far more than on-demand for a small share of the corpus.

### Risks

- **R1: GPU trigger.** Any profile on the LAN can queue GPU work and remote downloads. The deployment is local (Q6), and requests need a profile (Q3), so AC5's caps are the only other guard. The security audit should still cover the new routes after the build.
- **R2: Server-side fetch of remote URLs.** Media URLs come from instance JSON, so this is an SSRF surface. Instance API calls (video JSON, captions) go only to the video's whitelisted instance domain. The media URL's host is the one the instance JSON names, which may be object storage or a CDN (operator, plan 49 AC5): https only, a DNS name with no IP literal, port or userinfo, no redirect off that host, and a size cap.
- **R3: Untrusted caption files.** Instance captions and Whisper output are both untrusted text. They are parsed and rendered as text, and a malformed file is rejected, not partly served.
- **R4: Embed API availability.** It depends on the instance's PeerTube version and embed settings, and P0 measures it. Where it's missing, the control is hidden for that video.
- **R5: VRAM contention.** If the desktop or another process takes VRAM mid-job, the job fails with out-of-memory. The worker marks it failed and doesn't retry in a loop. Q1 decides whether this can happen at all.
- **R6: CUDA libraries.** CTranslate2 needs particular cuBLAS/cuDNN versions. The driver reports CUDA 13.2. Compatibility with the pip wheels has not been checked, and P0 checks it.
- **R8: Reading remote media (found in S0, 2026-10-03).** If ffmpeg reads an instance's fragmented MP4 straight from its URL, it jumps around the file, opening a new HTTPS connection for each jump, and stalls. On `tube.rsi.cnr.it` (146 MB, 240p) it had not finished after more than 7 minutes, while a direct read of the same file ran at about 5 MB/s. The worker must download in one sequential pass, piped into ffmpeg's stdin. It should translate in chunks as the audio arrives, so the first lines are ready before the download finishes. The chunks must overlap rather than be cut hard: with 30 s hard cuts, a sentence is split at the boundary (seen at 12:00 on the Italian video).
- **R7: Whisper quality.** On music, noise or several speakers, Whisper can produce repeated or made-up lines. Voice-activity filtering (faster-whisper's `vad_filter`) reduces this. Failures are shown as they are.

### Limitations

- English is the only target language.
- The first viewer of a video waits for the job, about 1 to 2 minutes per 20 minutes of video on the baseline (an estimate, measured in P0).
- Translations aren't visible when the embed's own player is in fullscreen (Q5, accepted).

### Tradeoffs accepted

- A second service to run, the worker, in exchange for keeping the Engine free of GPU dependencies.
- On-demand latency in exchange for spending no GPU time on videos nobody watches.
