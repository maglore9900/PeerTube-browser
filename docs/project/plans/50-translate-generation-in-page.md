# Translate: generation from the video page

## Requirements

Split from `docs/project/plans/18-english-subtitles.md` (B2, second half), which holds the decisions and the S0 results. This plan builds on two others:
- B1, delivered, `docs/project/plans/archive/48-translate-instance-captions.md`: the toggle, the store, the state route and the overlay;
- the worker, delivered, `docs/project/plans/archive/49-translate-whisper-worker.md`: the queue, the enqueue function, the heartbeat and cues appended while a job runs.

### What B1 shipped that this plan extends

- **State routes:** `GET /api/translate?id=&host=` on the Client (`_handle_translate_get` in `client/backend/server.py`) calls `POST /internal/translate` with body `{id, host}` on the Engine (`handle_internal_translate` in `engine/server/api/handlers/internal_translate.py`).
- **Allow-list:** the Client entry is `PROXY_ALLOWED_QUERY_PARAMS["/api/translate"] = {"id", "host"}`; the `after` parameter joins it. Each value is capped at 200 characters (`BLOCK_REFERENCE_MAX_LENGTH`).
- **404 mapping:** only an Engine 404 whose body `error` is exactly `Video not found` (`TRANSLATE_NOT_FOUND_ERROR`) maps to `none`; every other Engine failure is a 502.
- **Validators to widen:** `fetch_translate` in `client/backend/lib/engine_api_client.py` and `fetchTranslate` in `client/frontend/src/data/translate.ts` accept only `ready` (with cues) or `none` and throw on anything else, so both must accept the job states, partial cues and generation availability.
- **Cue list:** `client/frontend/src/pages/video-page/translate.ts` keeps one sorted cue list that each answer replaces; appended cues must keep it sorted by start, then end, for its binary search. Its existing polling is the `getCurrentPosition()` position fallback, separate from the state polling this plan adds.

### Asked for

When Translate is on and a video has no English, the page asks the worker for a translation and shows its English lines as they arrive.

### Purpose

This connects plan 49's worker to plan 48's toggle, so that Translate works for any non-English video from the page.

### Acceptance criteria

- **AC1: Feature gate.** The Engine reports "generation available" only while plan 49's heartbeat is fresh. Without one, Translate behaves exactly as in plan 48.
- **AC2: Request.** With Translate on, a state of `none`, and generation available, the page asks for a job through a Client POST route that requires a profile. The route calls plan 49's enqueue function, which is idempotent and capped. A request without a valid profile gets 401.
- **AC3: States.** The state route returns `none`, `queued`, `running`, `ready`, `already_english` or `failed`, plus whether generation is available. The page polls with backoff while the state is `queued` or `running`, and says which state applies.
- **AC4: Lines while running.** While the state is `running`, the state route returns the cues stored so far, or only the cues after a given position. The overlay shows them exactly as plan 48 shows `ready` cues. A position past the last stored cue shows nothing until the job reaches it.

### Scope

In scope: AC1 to AC4. Out of scope:
- the worker itself (plan 49);
- target languages other than English;
- pruning stored translations (a possible future feature).

### Consistency constraints

- The frontend talks only to the Client gateway, and the Client reaches the Engine over the existing bridge pattern and its auth.
- The new Client route uses `_require_profile` (`client/backend/server.py:541`).
- Cue text is inserted with `textContent` only.

## High-level plan

### Approach

- **Engine.** A request route behind the bridge token calls plan 49's enqueue function. Plan 48's state route gains the job states, generation availability (from the heartbeat's age) and an `after` parameter so the page can fetch only the cues it doesn't have.
- **Client.** A POST gateway route with `_require_profile`, plus allow-list entries for the extra parameter on the state route.
- **Frontend.**
  - On toggle-on, if the state is `none` and generation is available, the page sends the request.
  - While the state is `queued` or `running`, it polls with backoff and appends the new cues to the overlay's list.
  - It stops polling on `ready`, `already_english` or `failed`, and when Translate is turned off or the page changes video.

### Alternatives considered

- **Server-sent events or a websocket instead of polling.** Rejected for now. Neither the Client nor the Engine has one, and polling a few times a minute for a single local viewer costs nothing.
- **Wait for `ready` before showing anything.** Rejected by the operator's decision to show lines while the job runs.

### Risks

- **R1: Polling after leaving.** Polling must stop when Translate is turned off or the page changes video.
- **R2: Stale state.** A job that fails after the page has shown `running` must reach the page as `failed`, not as `running` forever.

### Limitations

- A seek past the translated part shows nothing until the job reaches it.
- One job at a time, so a second video waits behind the first.

### Tradeoffs accepted

- Polling instead of a push channel, in exchange for no new transport in the Client or Engine.
