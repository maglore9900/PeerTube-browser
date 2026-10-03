# Translate: instance captions and the video-page overlay

## Requirements

Split from `docs/project/plans/18-english-subtitles.md` (B1). That file holds the decisions, the S0 feasibility results and the reasoning behind them. This plan restates what B1 needs, so a build can start from this file alone.

### Asked for

A **Translate** toggle on the video page. When it's on, an English line is shown over the player, in time with the video. In this build the English comes only from a caption track the source instance already has. Generating English with Whisper comes later: the worker in `docs/project/plans/49-translate-whisper-worker.md`, and its connection to the page in `docs/project/plans/50-translate-generation-in-page.md`.

### Purpose

A visitor can follow a non-English video in English. B1 builds every part except the GPU: the toggle, serving through the Client and Engine, the overlay and its sync. B2 then only adds a second source of English.

### What the current code does (checked against the tree, 2026-10-03)

- **Embed:** the video page sets `#video-embed`'s `src` from `metadata.embedUrl`, or the `?embed=` fallback (`client/frontend/src/pages/video-page/index.ts:147`, `:280-287`). The URL is never given `?api=1`. The iframe carries `sandbox="allow-scripts allow-same-origin"` (`client/frontend/video-page.html:36`).
- **Embed API (S0):** with that same sandbox and `/videos/embed/<uuid>?api=1`, `@peertube/embed-api`'s `PeerTubePlayer` resolved `ready` within 1 s on `tube.rsi.cnr.it`. It reported play and pause, and streamed the position, and an overlay showed the right line during playback and after a seek. That instance is the only one tested. The package is not in `client/frontend/package.json`.
- **Profiles:** the frontend reads the key with `getProfileKey()` and builds headers with `profileHeaders()` (`client/frontend/src/data/profile.ts`). The Client answers 401 through `_require_profile` (`client/backend/server.py:514`).
- **Client → Engine:** reads are proxied through allow-lists (`PROXY_READ_GET_ROUTES`, `PROXY_ALLOWED_QUERY_PARAMS`, `client/backend/server.py:91-112`). Internal routes are handled in `engine/server/api/handlers/internal_client_reads.py`.
- **Instance fetches:** the Engine already fetches instance JSON with `fetch_instance_json` (`engine/server/api/handlers/video.py:82`, 8 s timeout). Host normalisation is `normalize_host` (`engine/server/data/moderation.py:45`).
- **Instance captions:** PeerTube's `/api/v1/videos/{id}/captions` lists tracks with `language.id` and a caption path or URL. The S0 probe read this list on `lone.earth`, where it held an `en` track.

### Acceptance criteria

- **AC1: When the toggle shows.** The Translate toggle shows only when the visitor has a profile and the embed's `ready` has resolved. Otherwise there is no toggle and no translate request is made. The label is **Translate**, never "CC" or "Captions".
- **AC2: Instance track.** When Translate is on, the Engine looks for a track in the instance's caption list whose language is English. If one exists, it fetches the track, validates it and caches it. The cache key is `(video_id, instance_domain, target_language)`, with `target_language` always `en`.
- **AC3: Serving.** A Client gateway route that requires a profile returns the translate state for a video (`ready` or `none`). When the state is `ready`, it also returns the cues: start, end and text. The frontend never fetches captions from an instance.
- **AC4: Display.** While Translate is on and the state is `ready`, a layer over `#video-embed` shows the cue for the current embed position. It updates during playback and after a seek. Cue text is inserted with `textContent`, never as HTML. When the state is `none`, the page says that no English translation is available for this video.
- **AC5: Persistence.** Translate stays on for later videos until the visitor turns it off. The setting is kept in the browser's `localStorage`.
- **AC6: Bounds.** A caption fetch goes only to the video's own instance, which must be a known whitelisted host. It is https only, follows no redirect off that host, and is capped in size. A track that doesn't parse as WebVTT is rejected as a whole, never served in part.

### Scope

In scope: AC1 to AC6.

Out of scope:
- Whisper generation, the job queue and the worker (B2);
- target languages other than English;
- fullscreen, because the overlay isn't visible when the embed's own player is fullscreen (accepted);
- pruning stored translations, a possible future feature (operator, 2026-10-03);
- replacing the iframe with our own player.

### Consistency constraints

- The frontend talks only to the Client gateway, and the Client reaches the Engine over the existing bridge pattern and its auth.
- Remote fetches reuse `normalize_host` and the https-only rule.
- The overlay's CSS goes in `video.css`.

### Open questions

- **Q1: Where "Translate on" is kept. Decided (operator, 2026-10-03):** in the browser's `localStorage`, like the NSFW filter. No Client schema change is needed, and the setting does not follow the profile key to another browser.
- **Q2: The embed library. Decided (operator, 2026-10-03):** `@peertube/embed-api` as an npm dependency in `client/frontend/package.json`, bundled by Vite.

## High-level plan

### Approach

- **Engine.** A new internal read route, behind the bridge token, takes `id` and `host`. It checks that the host is in the whitelist, then looks in the cache. On a miss, it reads the instance's caption list, picks an English track, fetches it within the AC6 bounds and parses it as WebVTT into cues. It then caches the original `.vtt` and returns `{state, cues}`. A `none` result is not cached, so B2's generation and a track added later can still change it. The parsing happens once, on the server, so the browser needs no VTT parser.
- **Storage.** A SQLite DB of its own, `engine/server/db/subtitles.db`, holds everything, with no `.vtt` files on disk:
  - one row per key, with state, source (`instance`) and fetched time;
  - the original track text;
  - the parsed cues.

  The repository's `.gitignore` already ignores `*.db` and its WAL files, so no new ignore rule or directory is needed. A 52-minute translation is about 48 KB of text, so keeping it in rows costs little. Plan 49 adds the job states and the `whisper` source to the same DB. A worktree gets its own empty `subtitles.db` unless one is linked, the same way `random-cache.db` is private (memory `worktree-random-cache-not-symlinked`).
- **Client.** One GET gateway route that calls `_require_profile` before proxying, plus its allow-list entries.
- **Frontend.**
  - The embed URL gets `?api=1`.
  - A `PeerTubePlayer` is created on `#video-embed`.
  - The toggle is shown once `ready` resolves and a profile exists.
  - On toggle-on, or when a page loads with Translate already on, the page requests the state.
  - When it's `ready`, the page subscribes to `playbackStatusUpdate` and shows the cue that contains the position.
  - The toggle state is kept in `localStorage` (Q1).

### Alternatives considered

- **Serve the raw `.vtt` and parse it in the browser.** Rejected: that is a second parser, in the browser, for untrusted text. The server already has to parse the file to validate it (R3).
- **The browser fetches the instance's captions directly.** Rejected by the constraint that the frontend never fetches captions from an instance, and it would skip validation.
- **Poll `getCurrentPosition()` instead of `playbackStatusUpdate`.** This is a fallback only. The event worked in S0.

### Risks

- **R1: Embed API on other instances.** Only `tube.rsi.cnr.it` was tested. An instance whose embed never resolves `ready` hides the toggle (AC1), so the feature degrades rather than breaks.
- **R2: Few English tracks.** Most non-English videos won't have one, so B1 alone mostly shows "no English translation available". B2 fills that gap.
- **R3: Untrusted caption text.** It is parsed on the server, rejected as a whole when malformed, and rendered with `textContent` only.
- **R4: Mislabelled tracks.** A track labelled English may not be English. It is shown as the instance labels it.
- **R5: SSRF.** The caption path comes from instance JSON. It must resolve to the video's own whitelisted host over https, with no redirect off that host.
- **R6: Unexplained refresh in S0.** The overlay once worked only after the page was reloaded. That was a scratch page, and the cause is unknown. The build should check the toggle on a page load where Translate is already on.

### Limitations

- English only.
- No overlay when the embed's own player is fullscreen.
- No toggle on instances whose embed API doesn't answer.

### Tradeoffs accepted

- Shipping B1 first means a working toggle that often has nothing to show until B2 lands. In exchange, the display path is proven without any GPU work.
