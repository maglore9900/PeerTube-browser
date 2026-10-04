# 50-translate-generation-in-page

_Rendered by the `dev-flow` workflow from its run state. Every edit here is overwritten on the next step; the evidence each gate turned on is in `docs/project/plans/51-50-translate-generation-in-page.record.md`._

## Requirements

### Purpose

This plan connects plan 49's translate worker (delivered, `docs/project/plans/archive/49-translate-whisper-worker.md`) to plan 48's Translate toggle (B1, delivered, `docs/project/plans/archive/48-translate-instance-captions.md`). The aim is that Translate works from the video page for any non-English video: when Translate is on and a video has no English, the page asks the worker for a translation and shows its English lines as they arrive. This is the second half of B2 in `docs/project/plans/18-english-subtitles.md`, which holds the decisions (Q2 trigger: the toggle queues a job when no track exists; Q3: requests need a profile; Q6: local deployment, no per-address limit) and the S0 results.

### Baseline suite state

The pre-build suite exited 0 (baseline variant: false), with tree snapshot `b50b7a1326a13a229088dd4434487050dd33bd33`. Every phase must leave the suite green.

### What already exists (read from the tree)

- **Client state route:** `GET /api/translate?id=&host=` is handled by `_handle_translate_get` (`client/backend/server.py:1065`). It calls `_require_profile`, sanitises the query against `PROXY_ALLOWED_QUERY_PARAMS["/api/translate"] = {"id", "host"}` (line 113), requires exactly `{id, host}` with each value at most `BLOCK_REFERENCE_MAX_LENGTH` = 200 characters, calls `fetch_translate` (`client/backend/lib/engine_api_client.py`), and maps an `EngineApiError` to 502 through `_respond_engine_failure`. In `fetch_translate`, only an Engine 404 whose body `error` is exactly `Video not found` (`TRANSLATE_NOT_FOUND_ERROR`) maps to `{"state": "none"}`.
- **`_require_profile`** (`client/backend/server.py:541`) resolves `X-Profile-Key` and otherwise answers 401 `{"error": "Profile key required"}`.
- **Engine state route:** `handle_internal_translate` (`engine/server/api/handlers/internal_translate.py:220`) takes POST `{id, host}`. It answers 400 for a bad body, a missing id or host, or an invalid host. It resolves the video with `resolve_video_row`, answers 404 `Video not found` for an unknown video or one on the active denylist, and uses the resolved row's canonical `video_id` and `instance_domain` as the key. It reads `fetch_ready_subtitles` and, on a miss (which includes any job-state row today), fetches the instance's English caption track. It stores a found track with `store_ready_subtitles`, which replaces any job row and so ends that job, and answers `{"state": "ready", "cues": [...]}` or `{"state": "none"}`. Store access goes through `server.subtitles_db` under `server.subtitles_db_lock`.
- **Store contract** (`engine/server/data/subtitles.py`): `enqueue_translate_job(conn, video_id, instance_domain, target_language, cap, queued_at)` returns `("queued", "queued")`, `("exists", <state>)` for a key in any state (it never overwrites a row), or `("cap", None)` when `cap` jobs are already `queued`. `SUBTITLE_QUEUE_CAP = 50` is in `engine/server/api/server_config.py:426`. Job rows move `queued` → `running` and end in `ready` (source `whisper`, or `instance`), `already_english` (no cues) or `failed` (error text; partial cues are left in `cues_json`). While a job is `running`, the worker rewrites the whole `cues_json` after each chunk, and that list is append-only in chunk order (`cues += new`, `translate-worker.py:413`). It is not necessarily sorted, because segments can come out of order or overlap at a chunk join. It is sorted by `(start, end)` only when the job is finished `ready` (line 420). A job left running by a crash, or stopped, goes back to `queued` and later restarts from an empty cue list. The worker upserts `translate_worker_heartbeat(id=1, beat_at ms, pid)` every 5 s (`HEARTBEAT_SECONDS`) and stops beating after 600 s without progress (`STALL_SECONDS`), so the age of `beat_at` tells whether a worker is serving.
- **Frontend:** `fetchTranslate` (`client/frontend/src/data/translate.ts`) accepts only `ready` with cues or `none` and throws on anything else. `client/frontend/src/pages/video-page/translate.ts` holds one cue list, sorted by start and then end for its binary search, which each answer replaces. Its existing `setInterval` poll (`pollTimer`) is the `getCurrentPosition()` position fallback and is separate from the state polling this plan adds.

### AC1: Feature gate

- The Engine computes "generation available" from the age of `translate_worker_heartbeat.beat_at`. It is true only when the row exists and `now - beat_at` is within a freshness threshold. The threshold is a named constant, a small multiple of the worker's 5 s beat, with its value chosen in the plan.
- A missing row, a stale beat, a closed store or a store read error all count as not available.
- With generation not available, Translate behaves exactly as in plan 48: the page never sends a request and never polls the state.

### AC2: Request

- A new Client route, `POST /api/translate` with body `{id, host}`, starts with `_require_profile`. A request without a valid profile gets 401 and the Engine is not called. Each of `id` and `host` must be a non-empty string of at most `BLOCK_REFERENCE_MAX_LENGTH` (200) characters, or the route answers 400.
- The Client calls a new Engine route behind the bridge token, following the existing bridge pattern and its auth. That Engine route validates the body and resolves the video exactly as `handle_internal_translate` does (same 400s, same `resolve_video_row`, same denylist check, same 404 `Video not found`, same canonical key). It then calls plan 49's `enqueue_translate_job` with target language `en` and cap `SUBTITLE_QUEUE_CAP`.
- When generation is not available at request time, the route queues nothing and answers `{"state": "none", "available": false}`.
- `("queued", "queued")` answers `queued`. `("exists", <state>)` answers that existing state (enqueue is idempotent and never overwrites a row). `("cap", None)` answers the new state `busy` (operator decision). Every answer carries `available`.
- The Engine 404 `Video not found` maps to `none` at the Client, as on the state route. Every other Engine failure is a 502.
- The page sends the request only when Translate is on, the state route answered `none`, and `available` is true. Nothing is queued automatically without the toggle (plan 18 Q2).

### AC3: States

- The state route (`GET /api/translate` → `POST /internal/translate`) answers `state` as one of `none`, `queued`, `running`, `ready`, `already_english` or `failed`, plus a boolean `available` (AC1) on every answer. The request route can also answer `busy`, which is never stored (the queue was full).
- Order on the Engine state route: a stored `ready` row is served as today. A row in `queued` or `running` is answered from the store with no instance fetch (operator decision; the worker checks the instance itself when it claims the job). For no row, or a row in `failed` or `already_english`, B1's instance-track fetch runs first. A found track is stored and answered `ready` exactly as today. Otherwise the answer is `failed` or `already_english` for those rows and `none` when there is no row.
- `fetch_translate` (Client) and `fetchTranslate` (frontend) are widened to accept every state above, `available`, and the partial cues and `total` of AC4. They still reject malformed shapes.
- The page polls the state route with backoff while the state is `queued` or `running`. It stops polling on `ready`, `already_english`, `failed`, `none` or `busy`, when Translate is turned off (R1), and when the page changes video (R1). The backoff bounds are chosen in the plan.
- The page shows which state applies with a short label for each of: queued, running (translating), already English, failed, busy (queue full). `ready` shows the lines. `none` without availability looks exactly as in plan 48.
- `busy` is not polled. Turning Translate off and on again retries the request.
- R2: a job that fails after the page showed `running` reaches the page as `failed` on its next poll. The page never keeps showing `running` once the store says otherwise.

### AC4: Lines while running

- The state route accepts an optional `after` parameter: a non-negative integer cue count (operator decision), not a time. The Client allow-list `PROXY_ALLOWED_QUERY_PARAMS["/api/translate"]` gains `after`. `id` and `host` stay required, every value stays capped at 200 characters, and an `after` that is not a non-negative integer answers 400. The Client passes `after` through in the Engine body.
- For a `running` row, the answer carries the stored cues from index `after` on (all of them when `after` is absent), in stored order, plus `total`, the stored cue count. A `running` row whose `cues_json` is empty or not yet set answers no cues and `total` 0.
- The page sends `after` equal to the count of running cues it already holds. It merges new cues into its list so the list stays sorted by start, then end, for the existing binary search. When `total` is less than the count it holds (the job was requeued and restarted), it drops its list and refetches from 0. On `ready`, it replaces its list with the final sorted cues.
- The overlay shows running cues exactly as plan 48 shows `ready` cues. A playback position past the last stored cue shows nothing until the job reaches it.

### Consistency constraints

- The frontend talks only to the Client gateway. The Client reaches the Engine over the existing bridge pattern and its auth. The Engine never imports the worker or faster-whisper.
- The new Client route uses `_require_profile` (`client/backend/server.py:541`).
- Cue text is inserted with `textContent` only.
- New code matches the style of the file it lands in. One paragraph or statement per line, no softwrap.

### Out of scope

- The worker itself (plan 49).
- Target languages other than English.
- Pruning stored translations.
- Retrying a `failed` job from the page: enqueue never overwrites a row, so `failed` is final for that video.
- Server-sent events or a websocket (polling is the accepted tradeoff).

### Limitations accepted

- A seek past the translated part shows nothing until the job reaches it.
- One job at a time, so a second video waits behind the first.
- A `failed` video stays failed: there is no re-queue from the page.

### Documentation to update

- `engine/server/README.md`: the `/internal/translate` entry ("a key in a job state is a miss…", the answer shapes), the new request route, and the line "no reader serves `running` cues yet".
- `CONTEXT.md`: "Translate state" (which says a video whose job has not ended `ready` reads as `none`; it now names the job states, `busy` and `available`) and "Translate job" ("queued from the worker's command line" now includes the page).
- The Client README routes, if it lists `/api/translate`.

## High-level plan

### Approach

What I read: `internal_translate.py`, `data/subtitles.py`, the Engine POST dispatch in `similar.py`, the Client's `_handle_translate_get` and dispatch in `server.py`, `fetch_translate` in `engine_api_client.py`, both frontend `translate.ts` files, the worker's heartbeat constants and the Engine README. The video page has no in-page navigation (no pushState or popstate under `pages/video-page`). Going to another video loads a new page, which ends every timer. That satisfies R1's "page changes video" on its own, and the existing `requestTicket` covers turning Translate off.

The work goes into the files that already own Translate. There are no new modules on any tier.

**Store (`engine/server/data/subtitles.py`).** Two small readers, both in the file's existing style:
- One returns a key's `state` and raw `cues_json` in a single SELECT. It replaces the ready-only read in the handler, so one read decides the branch. `fetch_ready_subtitles` is removed if the handler and its tests are its only users; otherwise it stays.
- One returns `translate_worker_heartbeat.beat_at` or None.

**Engine (`internal_translate.py`).**
- The current body-validation, resolve, canonical-key and denylist block becomes one helper. It returns the resolved key or has already answered 400/404. The state route and the new request route both call it, which is what "resolves the video exactly as `handle_internal_translate` does" requires. Both routes share one source for it rather than a copy.
- A module constant `HEARTBEAT_FRESH_MS = 15_000` is three of the worker's 5 s beats. A helper `_generation_available` reads the heartbeat under `subtitles_db_lock` with the clock from `data.time.now_ms`, the clock the worker writes with. It answers false for a missing row, a closed store, a `sqlite3.Error`, or an age outside the threshold in either direction. A beat far in the future therefore counts as stale rather than fresh forever.
- **State route order (AC3).** Read the row and the heartbeat under one lock acquisition.
  - `ready` with a non-empty list: answer the cues as today.
  - `queued`: answer the state only.
  - `running`: answer cues `[after:]` in stored order plus `total`, the stored count. An empty, unset or non-list `cues_json` counts as zero cues.
  - Any other case (no row, `failed`, `already_english`, or a `ready` row whose cues don't load): run B1's instance fetch. A found track is stored and answered `ready` exactly as today. Otherwise answer the row's own state, or `none` when there is no row.
  - `available` is added to every 200 answer.
  - `after` is optional in the body. When present it must be a JSON int (not a bool) of 0 or more, or the route answers 400. An `after` past `total` gives an empty slice.
- **Request route.** A new `POST /internal/translate/enqueue`, dispatched next to `/internal/translate` in `similar.py`, so it sits behind the existing `/internal/` bridge-token check without new auth code. It runs the shared helper and then the availability check. If generation is unavailable it answers `{"state": "none", "available": false}` and queues nothing. Otherwise it calls `enqueue_translate_job(..., "en", SUBTITLE_QUEUE_CAP, now_ms())` and maps the result:
  - `queued` → `queued`
  - `exists` → the existing state
  - `cap` → `busy`
  - The answer is `available: true` in each case.
  - A `sqlite3.Error` or a closed store answers 503 with an error, which the Client turns into a 502.

**Client.**
- `PROXY_ALLOWED_QUERY_PARAMS["/api/translate"]` gains `after`. `_handle_translate_get` still requires `id` and `host` and still caps every value at 200 characters. It accepts `after` only as ASCII digits (a plain `isdigit` would let in Unicode digits) and passes it on as an int.
- `fetch_translate` gains an optional `after` and is widened to accept the six states plus a boolean `available`. Cues are required only for `ready` and `running`, and `total` (a non-bool int of 0 or more) only for `running`. It keeps copying only `start`/`end`/`text` and raises on any other shape. The 404 `Video not found` → `none` mapping now also returns `available: false`, so every answer carries the flag.
- A new `request_translate` posts to the enqueue route with the existing default timeout (no instance fetch happens on that path), maps the same 404, accepts the states including `busy`, and raises otherwise.
- The new `POST /api/translate` branch in `_serve_post` rate-limits like the GET branch. Its handler then starts with `_require_profile`, so a request without a profile gets 401 and never reaches the Engine. It reads the JSON body, requires `id` and `host` to be non-empty strings of at most 200 characters (else 400), and maps `EngineApiError` through `_respond_engine_failure`.

**Frontend.**
- `data/translate.ts` widens `TranslateState` to a union over the states, with `available` on each, `cues` on `ready`/`running` and `total` on `running`. `parseTranslateState` validates every one and still throws on anything else. `ready` cues stay sorted. `fetchTranslate` gains an optional `after`, and a new `requestTranslate` posts `{id, host}` with `profileHeaders()`.
- In `video-page/translate.ts`, `turnOn` reads the state:
  - `none` with `available` false: show the plan 48 message, exactly as today.
  - `none` with `available` true: call `requestTranslate` once, then handle its answer like a state answer.
  - `queued` or `running` with `available` true: start a state poll.
- The state poll is a `setTimeout` chain kept separate from the existing position `pollTimer`. It has its own handle and at most one request in flight, and it is guarded by `requestTicket`.
  - Backoff starts at 2 s, doubles while nothing changes, and is capped at 16 s. It resets to 2 s whenever the state changes or new cues arrive.
  - It stops on `ready`, `already_english`, `failed`, `none`, `busy`, an answer with `available` false, a 401, and `turnOff`.
  - A network error or 502 keeps the current label and retries at the next backoff step, so a blue/green switch doesn't stop it.
- **Running cues (AC4).** The page keeps a count of running cues received and sends it as `after`.
  - New cues are appended and the list re-sorted by start, then end, so `findCue` works unchanged. A full sort per poll is a deliberate simplification; at most a few thousand cues every few seconds is negligible. If it ever matters, a merge of the sorted new slice is the upgrade.
  - If `total` is below the held count, or the page sees `queued` after it held running cues, it drops the list and the next poll asks from 0.
  - `ready` replaces the list with the final cues.
  - The position poll that drives the overlay starts on `running` as it does on `ready`. Past the last stored cue the overlay shows nothing.
- **Labels.** Each one is set with `textContent`:
  - queued: "Waiting for translation…"
  - running: "Translating…" (shown alongside the lines)
  - already English: "This video is already in English."
  - failed: "Translation failed for this video."
  - busy: "The translation queue is full. Turn Translate off and on to try again."
- `failed` clears any running lines, so the page shows what a reload would show (the state route never serves a failed job's partial cues).
- `busy` is not polled. Off-then-on runs `turnOn` again, which retries the request.

**Requirement by requirement.**
- AC1: the heartbeat helper, plus the page gating both the request and the poll on `available`.
- AC2: the Client handler with its profile-first check, the shared resolve helper, and the enqueue mapping.
- AC3: the state-route order, the widened parsers on both tiers, the poll stop set and the labels. R2 holds because every poll re-renders from the store's answer.
- AC4: `after`/`total`, the slice, the merge and the reset.

**Docs.** The three files listed, plus two lines that would otherwise go wrong:
- `engine/server/db/jobs/docs/TRANSLATE_WORKER.md:148`: "B1 treats any non-ready key as a miss" is now false for `queued`/`running`.
- The handler's module docstring and the route list in `similar.py`'s docstring.

### Alternatives considered

- **Freshness threshold.** I rejected 10 s (two beats): one beat delayed by a busy SQLite write would flip Translate off. I rejected 60 s: a dead worker would keep accepting jobs for a minute. 15 s accepts one missed beat and reacts within one poll cycle.
- **Queueing from the state route on `none`.** This would save a round trip. I rejected it because a GET would gain a side effect, the "toggle queues" decision (plan 18 Q2) would become implicit, and every caller of the state route would start queueing.
- **Request route location.** A separate Engine module would mean duplicating, or exporting and importing, the resolve block. The same module keeps one helper and one denylist check.
- **Fixed-interval state polling.** I rejected a fixed `setInterval` because it hammers the Client for a job that may wait behind another for many minutes. Backoff with a reset on progress keeps running jobs responsive and queued ones cheap.
- **Re-sending all running cues every poll.** Simpler on the page, but the payload grows with every chunk on long videos. The operator also fixed the count cursor.
- **Keeping partial lines on `failed`.** Rejected because a reload would not show them, and the page should not disagree with itself across a reload.
- **Polling at the maximum backoff while unavailable.** This would notice a worker coming back, but it contradicts AC1's "never polls the state". Rejected.

### Gotchas and risks

- **Restart ambiguity in `after`.** A crash-restarted job can run past the held count between two polls. `total` then never drops below it, so the page appends cues from the second run onto the first. The `queued`-seen reset makes this unlikely: a restart passes through `queued` and needs a worker restart, a model load and re-transcription, all far longer than the 16 s poll cap. Even then the damage is temporary, because `ready` replaces the list. A real fix needs a run marker (e.g. `started_at`) in the answer, which the settled contract doesn't include.
- **Worker dies mid-job.** Once a poll answers `available` false, the page stops polling and keeps showing the stored state's label (queued or translating). That label is true while the worker is down. If the worker comes back it can go stale until the viewer toggles or reloads. This is the literal reading of AC1's "never polls when unavailable".
- **Engine lock and Client timeout.** `enqueue_translate_job` takes an IMMEDIATE transaction with a 30 s busy timeout while holding `subtitles_db_lock`. If the worker held the write lock that long, other translate requests on that Engine would wait, and the Client's 6 s timeout would answer 502. Worker writes are single short statements, so I accept this. The page shows the error and toggling retries.
- **Heartbeat clock.** It uses wall-clock ms on both sides. That is fine because `subtitles.db` is a local file shared on one host. An NTP step larger than 15 s flips availability for about one beat.
- **Queueing English videos.** Every video without an English track (including some that are spoken in English) is queued when a viewer has Translate on. Those end `already_english` at GPU cost. This follows from plan 18 Q2 and is accepted there.
- **Instance fetch on finished jobs.** `failed` and `already_english` rows still trigger the instance fetch on every view (up to 15 s), as B1 does for misses today. The state route's 20 s Client timeout already covers this.
- **Two tabs.** Two tabs on the same video both post. Enqueue is idempotent, so the second gets `exists`/`queued`.

### Tradeoffs the operator is accepting

- Lines appear on a polling delay of up to 16 s after a quiet spell, not instantly (no SSE).
- A seek past the translated part shows nothing until the job gets there.
- `failed` is final, and its partial lines are not shown.
- After a crash-restart the page may briefly show duplicated or mismatched running lines until `ready`.
- When the worker goes away mid-job, the label may go stale until the viewer toggles or reloads.
- `busy` asks the viewer to toggle to retry rather than retrying on its own.

## Impacts

<impacts>
<impact path="engine/server/data/subtitles.py" element="new key reader (state + raw cues_json, one SELECT); new heartbeat reader (translate_worker_heartbeat.beat_at or None); fetch_ready_subtitles (80-92) kept; docstrings at 3, 96, 150, 177">
**What changes.** Two pure readers are added in the file's style: `conn.execute(...).fetchone()`, the `_KEY` WHERE fragment (line 22), no transaction and no write.
- (a) The key reader returns `(state, cues_json)` or None for one `(video_id, instance_domain, target_language)`. It returns the text unparsed, so the handler decides the branch.
- (b) The heartbeat reader returns `beat_at` from `translate_worker_heartbeat WHERE id = 1`, or None. The table already exists, because `ensure_subtitles_schema` creates it at line 77 and the Engine runs that at start (`engine/server/api/server.py:372`). A fresh store therefore has the table and no row, which reads as unavailable.

**`fetch_ready_subtitles` must stay.** The plan's condition "removed if the handler and its tests are its only users" does not hold.
- After the build the handler stops calling it (`internal_translate.py:21`, `:203`).
- `tests/active/test_subtitles.py` still imports and calls it at :162, :164, :278, :304 and :312, and names it in the docstring at :7.
- It is also called inside a subprocess script string at :247, which a search for import lines misses.
- `engine/server/README.md:30` names it.

**Docstrings.**
- **Line 3.** "fetch_ready_subtitles reads a ready row of either source unchanged" stays true. It should now also say that the state route reads `running` cues through the new reader, and that the Engines also insert queued rows.
- **Line 96 (`store_ready_subtitles`).** "Against a job row it ends the job" stays true. The route still upserts over `failed`/`already_english` rows, and still over any row created during its up-to-15 s fetch (see the `internal_translate.py` entry).
- **Line 150 (`_update_claim`, "False when B1's route took the row over").** Stays true, but the takeover now happens only in a narrower window: a route fetch already in flight when the job was queued and claimed, or an old-code Engine during a blue/green switch. It does not become "old Engine only" (pass 2 corrected this).
- **Line 177 (`finish_translate_failed`, "unread because only ready rows are served").** Becomes inaccurate. Running rows are now served, and failed rows still are not.

**Depends on it.**
- `internal_translate.py`.
- The worker imports a fixed list of names at `translate-worker.py:46`. Adding functions does not affect that list.

**Regression risk: low.** These are pure reads.
- A connection never passed through `ensure_subtitles_schema` raises `no such table`, which is a `sqlite3.Error`. The handler must read it as unavailable or a miss, not raise.
- The `test_subtitles.py` group (`tests/config.json:413-415`) maps only this file. Touching the file also selects the `test_internal_translate.py` and `test_translate_worker.py` groups.
</impact>
<impact path="engine/server/api/handlers/internal_translate.py" element="module docstring (1-6); imports (20-24); new shared validate/resolve/canonical-key/denylist helper extracted from handle_internal_translate (222-247); HEARTBEAT_FRESH_MS and _generation_available; _cached_cues (198-206) replaced by one locked read of row+heartbeat; handle_internal_translate (220-257) reordered with after/total/available; new enqueue handler">
**What changes.**
- **Shared helper.** Lines 222-247 move into one helper used by both routes, in this order:
  - `read_json_body` raising `ValueError` → 400 `str(exc)`.
  - `id`/`host` stripped only when they are `str` → 400 `Missing id or host`.
  - `normalize_host` → 400 `Invalid host`.
  - `resolve_video_row(handler, server, {"id": [video_id], "host": [host]})` (`handlers/video.py:264`). It sends its own 404 `Video not found`, and a 400 `Missing video id` that is unreachable here.
  - The canonical `row["video_id"]` and `row["instance_domain"]`.
  - `list_active_denied_hosts` under `db_lock` → 404 `VIDEO_NOT_FOUND`.

  The helper must also hand back the parsed body (the state route reads `after` from it) and `row["video_uuid"]`, which line 250 passes to `fetch_instance_track`.
- **Freshness constant and check.** `HEARTBEAT_FRESH_MS = 15_000`, plus `_generation_available`, using `now_ms`, which is already imported at :22. An age outside `[0, 15000]` in either direction is false. So are a missing row, a `subtitles_db` of None and a `sqlite3.Error`.
- **Store read.** `_cached_cues` (its only use is :248) is replaced by one `subtitles_db_lock` hold that reads the row and the heartbeat together. `_store_cues` (:209-217) stays as it is.
- **State route order.**
  - `ready` with a non-empty list → the cues.
  - `queued` → the state only.
  - `running` → `cues[after:]` in stored order, plus `total`.
  - Anything else → the instance fetch (`fetch_instance_track`, unchanged and outside the lock), then the stored state or `none`.
  - Every 200 carries `available`.
  - `after` must be a JSON int, not a bool, and ≥ 0, or the answer is 400.
- **Enqueue handler.** It needs new imports: `enqueue_translate_job` from `data.subtitles`, and `SUBTITLE_QUEUE_CAP` from `server_config`. `handlers/video.py:22` already imports `server_config` the same way, and `translate-worker.py:43` imports it too, so this adds no new import-time dependency for the worker. The mapping is queued→`queued`, exists→`<state>`, cap→`busy`, all with `available: true`. An unavailable worker answers `{"state":"none","available":false}`. A closed store or a `sqlite3.Error` answers 503 with an error.
- **Docstring.** Lines 1-3 ("answers ... ready ... or none", "Only ready is stored; every failure is none") must change.

**What depends on it.**
- **Worker imports.** `engine/server/db/jobs/translate-worker.py:48` imports `FETCH_DEADLINE_SECONDS, READ_CHUNK_BYTES, SOURCE_INSTANCE, TARGET_LANGUAGE, SameHostRedirectHandler, fetch_bounded, fetch_instance_track`. All seven keep their names and signatures. The module must stay free of numpy and faster-whisper, and new module-level imports must not pull in anything the worker's environment lacks.
- **Test patch points.**
  - `tests/active/test_internal_translate.py:263-265` patches `module.build_opener`.
  - `:458-459` patches `module.fetch_bounded`.
  - `tests/active/test_translate_worker.py:488` patches `handlers.internal_translate.build_opener`.

  So `fetch_bounded` must keep resolving `build_opener` as a module global, and `fetch_instance_track` must keep calling the module-global `fetch_bounded`.
- **Test server stand-in.** It (`test_internal_translate.py:493-495`) has only `db, db_lock, video_error_threshold, subtitles_db, subtitles_db_lock, statement_timeout_seconds`. The new code must read nothing else from `server`.
- **Dispatch.** `similar.py:101` and `:458-459` dispatch here.
- **Client mirror.** `client/backend/lib/engine_api_client.py:19-20` mirrors `VIDEO_NOT_FOUND`.

**Regression risk: high.**
- **(1) Exact-answer constants.** `NONE`/`READY` (`test_internal_translate.py:144-145`) are compared with `==` in the handler tests (528-620). All of them fail once `available` is added. The test store has no heartbeat row, so the constants gain `"available": False`.
- **(2) Takeover narrows but does not end.** `queued`/`running` rows no longer trigger the fetch. However, for no row (or `failed`/`already_english`), the route decides on a read taken before a fetch of up to 15 s, then upserts unconditionally (`store_ready_subtitles`, `subtitles.py:97-106`). A job queued by another tab or the CLI, and claimed inside that window, is still overwritten `ready`/`instance`, and the worker hits `JobTakenOver`. The outcome is benign (the instance track wins), but the docs must describe this race rather than "never".
- **(3) Lock scope.** The instance fetch must stay outside `subtitles_db_lock`. `enqueue_translate_job` runs `BEGIN IMMEDIATE` with the 30 s busy timeout (`subtitles.py:15`, `:43-51`) while it holds that lock, so every other translate request on that Engine waits for it.
- **(4) Malformed running cues.** A `running` `cues_json` that does not load, or that loads as a non-list, must read as zero cues. One malformed element still makes the Client's per-cue check raise, so every poll becomes a 502. The worker writes with `allow_nan=False` (`subtitles.py:111`), so this needs a hand-damaged row.
- **(5) `ready` row whose cues don't load.** Under "otherwise answer the row's own state", such a row followed by an instance miss would answer `{"state":"ready"}` with no cues. Both parsers reject that, so it must map to `none`.
- **(6) `after` validation order.** Whether a bad `after` is refused before or after resolve (400 vs 404) is unspecified. A test should pin it.
- **(7) No duration check.** The enqueue route skips the CLI's stored-duration check (`translate-worker.py:113-115`, `SUBTITLE_MAX_DURATION`). Long videos take a queue slot and end `failed` `duration Ns over Ms` at the claim-time resolve. This is an operator decision.
- **(8) `exists` answers.** `exists` with `ready`/`running` answers a bare state with no cues or `total`. The downstream parsers must accept that on the request path, or the page must re-read the state.
- **(9) Takeover over finished rows.** An instance track found for a `failed`/`already_english` row overwrites it `ready`/`instance`, leaving the `error`/`detected_language`/`finished_at` job columns behind. This is the same as B1 today, so it is harmless.
</impact>
<impact path="engine/server/api/handlers/similar.py" element="_dispatch_post (441-474): new /internal/translate/enqueue branch; import line 101; module docstring route list line 13">
**What changes.**
- **New branch.** `if url.path == "/internal/translate/enqueue": <enqueue handler>(self, self.server); return`, placed beside :458-460 and after the `/internal/` bridge gate at :444, which covers it with no new auth code.
- **Import.** Line 101 gains the new handler.
- **Docstring.** Line 13 ("internal Client read of a video's English caption cues, from its own instance (cached)") is reworded to cover the job states and running cues, and a route line is added for the enqueue route.

**Depends on it.** Every Engine POST. Paths are matched exactly, so `/internal/translate` and `/internal/translate/enqueue` do not shadow each other.

**Regression risk: low.**
- The branch must stay after the gate.
- `test_internal_translate.py:623-654` drives a real Engine, with 404 with the token and 401 without (:653-654). The new route needs the same pair.
- `similar.py` is mapped in both the `test_internal_translate.py` group (`tests/config.json:405`) and the `test_server.py` group (:81).
</impact>
<impact path="engine/server/api/handlers/__init__.py" element="module docstring line 8">
**What changes.** The line "internal_translate: bridge read of a video's English caption cues ..." should also name the job states, the running cues and the enqueue route.

**Depends on it.** Nothing at runtime.

**Regression risk: none.**
</impact>
<impact path="engine/server/api/handlers/video.py" element="resolve_video_row (264-286), fetch_video_row (25, duration at 60)">
**What changes.** Nothing. The shared helper calls `resolve_video_row` exactly as today. Its row carries `duration` (`v.duration`, line 60), which a duration bound on the enqueue route would read if the operator wants one.

**Depends on it.** `/api/video`, `/api/video/refresh`, both translate routes, and the worker (`fetch_video_row`, `translate-worker.py:49`).

**Regression risk: none,** provided the file is not edited.
</impact>
<impact path="engine/server/api/server_config.py" element="SUBTITLE_QUEUE_CAP (426) and its comment (425); SUBTITLE_MAX_DURATION (422); DEFAULT_SUBTITLES_DB_PATH comment (419)">
**What changes.** Nothing in code.
- The new route reads `SUBTITLE_QUEUE_CAP`. The comment at :425 already says "the enqueue CLI and plan 50's route refuse past it".
- `SUBTITLE_MAX_DURATION` is relevant only if the duration bound is adopted.
- The comment at :419 ("Instance caption tracks served by /internal/translate, and the translate worker's jobs and heartbeat") could also mention the jobs the Engine queues. That edit is optional.

**Depends on it.** The worker CLI (`--cap` default) and the new route.

**Regression risk: low.** It is a shared value. `server_config.py` is mapped to many groups, so editing it selects many tests.
</impact>
<impact path="engine/server/api/server.py" element="subtitles_db / subtitles_db_lock lifecycle (297-298 init, 371-372 open+schema, 504 assign, 574-579 close under lock)">
**What changes.** Nothing. At shutdown `server.subtitles_db` becomes None under the lock. The state route must read that as unavailable plus a miss (as `_cached_cues` does now), and the enqueue route must answer 503.

**Depends on it.** Both translate handlers.

**Regression risk: low.** The risk is a handler that dereferences None.
</impact>
<impact path="engine/server/api/http_utils.py" element="read_json_body, respond_json (Engine side)">
**What changes.** Nothing. The shared helper keeps using these. The 503 from the enqueue route goes through `respond_json` like any other answer.

**Regression risk: none.**
</impact>
<impact path="engine/server/data/time.py" element="now_ms">
**What changes.** Nothing. It is the wall clock that both the worker's heartbeat (`translate-worker.py:502`) and `_generation_available` use. An NTP step larger than 15 s flips availability for about one beat.

**Depends on it.** The `test_internal_translate.py` group (`tests/config.json:397-406`) does not list this file; the worker group (:423) does.

**Regression risk: none.**
</impact>
<impact path="engine/server/db/jobs/translate-worker.py" element="HEARTBEAT_SECONDS (60), STALL_SECONDS comment (62-63), JobTakenOver docstring (91-92), run_job docstring (468) and takeover log (481-482), module docstring line 4, imports (43, 46, 48)">
**What changes.**
- **Code.** None. `HEARTBEAT_FRESH_MS` (15 s) is implicitly three × `HEARTBEAT_SECONDS` (5 s), with no shared constant. Raising the beat past about 7.5 s would make availability flap. A rat-tail comment on both constants is advisable.
- **Wording.**
  - :92 ("B1's route replaced the running row"), :468 and the log at :482 describe a takeover the route now performs only in the in-flight-fetch race (see the `internal_translate.py` entry) or from an old-code Engine. The guard must stay.
  - Line 4 ("resolves ... the way B1's /internal/translate does") stays true: the CLI's resolve still adds the duration check.

**Depends on it.**
- The Engine's availability check, through the heartbeat row.
- Its import of `handlers.internal_translate` at :48, which the handler refactor must not break.

**Regression risk: medium, and indirect.**
- A refactor that renames or moves any of the seven imported names breaks the worker at import. `test_translate_worker.py` is the guard; its group maps `internal_translate.py` (`tests/config.json:419`).
- Someone may remove the `JobTakenOver` guard as dead code. It is not dead.
</impact>
<impact path="client/backend/lib/engine_api_client.py" element="fetch_translate (158-177); new request_translate; _post_json (49-80); _is_seconds (153-155); TRANSLATE_TIMEOUT_SECONDS / TRANSLATE_NOT_FOUND_ERROR comments (17-20)">
**What changes.**
- **`fetch_translate`.**
  - It gains an optional `after`, put into the body only when given.
  - It accepts `none|queued|running|ready|already_english|failed` with a boolean `available`. It requires cues for `ready`/`running`, and a non-bool int `total` ≥ 0 for `running`. It copies only start/end/text through `_is_seconds`.
  - The 404 `Video not found` mapping returns `{"state":"none","available":False}`.
  - The docstring at :159 changes.
- **New `request_translate`.** It posts `{id, host}` to `/internal/translate/enqueue` through `_post_json` with its default `timeout=6` (:49). It maps the same 404, accepts the states plus `busy`, and raises `EngineApiError` otherwise. Its 503 becomes `EngineApiError`, which the server turns into a 502.

**Depends on it.** `client/backend/server.py` (import at :32-34, call at :1077, and the new POST handler).

**Regression risk: high.**
- **(1) Parametrized cases in `tests/active/test_server.py`.**
  - "engine none" `(200, {"state":"none"})` (:1551) becomes a 502 if `available` is required.
  - "unknown state" `(200, {"state":"queued"})` (:1554) is no longer unknown.
  - `TRANSLATE_NONE` (:1533) no longer equals the 404 mapping.
  - `TRANSLATE_READY` (:1536) is both the Engine reply and the expected answer at :1632, :1646, :1662-1663, and has no `available`.
  - The ready-cue test at :1689-1691 also uses replies without `available`.
- **(2) Exact Engine body.** :1664-1667 pins the body to exactly `{id, host}`, so `after` must be omitted when absent.
- **(3) Version skew.** `scripts/deploy-bluegreen.sh` swaps Engines only, and the Client unit restarts separately.
  - A strict new Client in front of an old Engine turns every translate read into a 502, because the old Engine sends no `available`.
  - An old Client in front of a new Engine turns `queued`/`running`/`failed`/`already_english` into 502s (it passes `none` and `ready` through).

  The choices are to default a missing `available` to false, or to require the Engine to be deployed first and say so in `DEPLOYMENT.md`.
- **(4) `exists` without cues.** If `request_translate` reuses the cue requirement, an `exists` → `ready`/`running` answer without cues becomes a 502.
- **(5) Old Engine without the route.** Its 404 `Not found` must stay a 502, not `none`. The existing comment at :19 already states this rule.
</impact>
<impact path="client/backend/server.py" element="PROXY_ALLOWED_QUERY_PARAMS['/api/translate'] (112-113); _handle_translate_get (1065-1081); _serve_get translate branch (461-466); _serve_post (469-539) new /api/translate branch; new POST handler; lib.engine_api_client import (32-34); RATE_LIMIT_* (65-66); _rate_limit_check (552-555)">
**What changes.**
- **Allow-list.** It becomes `{"id","host","after"}`. Only `_handle_translate_get` reads that key. The proxy paths look up `PROXY_ALLOWED_QUERY_PARAMS.get(path)` (:565, :609) for their own routes, and `/api/translate` is not in `PROXY_READ_GET_ROUTES`/`PROXY_READ_POST_ROUTES` (:91-94).
- **`_handle_translate_get`.**
  - The check `set(query) != {"id","host"}` (:1071) would reject `after`, so it becomes "id and host present".
  - `after` is accepted only when `isascii() and isdigit()` and is passed as an int.
  - `_sanitize_query` (:129-145) strips values and drops blank ones, so `after=` and `after=%20` read as absent.
  - The 200-character cap still covers every value.
  - The 400 text for a bad `after` is not yet decided.
- **New POST branch.** It goes before the final 404 at :539, in this order:
  - `_rate_limit_check(url.path)` → 429.
  - The handler: `_require_profile` (:541) → 401.
  - `read_json_body` → 400 on a `ValueError`. The body is `{}` when empty.
  - `id`/`host` must be `str`, non-empty after strip, and ≤ `BLOCK_REFERENCE_MAX_LENGTH` (:69), following the `_handle_block_add` pattern at :1130-1133.
  - `request_translate` → `_respond_engine_failure("translate", exc)` (:557).
- **Import.** It gains `request_translate`.

**Depends on it.**
- The browser. CORS (`client/backend/lib/http_utils.py:39-40`) already allows POST and `content-type, x-profile-key`.

**Regression risk: medium.**
- **(1) Shared rate-limit bucket.** The limiter key is `f"{ip}:{path}"` (:554), so GET polls and the POST share one `/api/translate` bucket at 90 per 60 s (:65-66). One tab polling at 2 s uses 30 per minute, so three tabs behind one address hit 429.
- **(2) Check order.** `test_server.py:1619-1667` pins 429 → 401 → 400 with no Engine call on refusal. The POST must keep the same order and must read the body only after `_require_profile`.
- **(3) Body types.** A JSON number for `id` must be a 400, not stripped.
- **(4) Existing cases.** "unknown param" `lang=fr` still answers 400 `Unknown query parameter: lang`, and a repeated `after` gets the "Multiple values" text.
- **(5) Log volume.** Every poll writes request.start/end on both tiers.
</impact>
<impact path="client/backend/lib/http_utils.py" element="_send_cors_headers / ALLOWED_REQUEST_HEADERS (12, 33-44); read_json_body (78-95)">
**What changes.** Nothing.
- CORS already allows `GET, POST, OPTIONS` with `content-type, x-profile-key`.
- `read_json_body` returns `{}` for an empty or blank body and raises `ValueError("Invalid JSON body")` for a non-object, so the new handler's `id`/`host` checks must cover `{}`.

**Regression risk: none.**
</impact>
<impact path="client/frontend/src/data/translate.ts" element="TranslateState type (11); fetchTranslate (45-59) incl. JSON.parse before response.ok (52-57); parseTranslateState (64-73); new requestTranslate; module docstring (1-5)">
**What changes.**
- **Type.** `TranslateState` becomes a union over the six states, each carrying `available`. `ready`/`running` carry `cues`, and `running` carries `total`. `busy` exists for request answers, either as a separate request type or inside the union.
- **`fetchTranslate`.** It sets `after` as a search param only when it is defined.
- **`parseTranslateState`.** It validates each state and `available` (`typeof === "boolean"`), and `total` with `Number.isInteger(total) && total >= 0`. It keeps sorting `ready` cues, and still throws "Translate response was malformed" on anything else.
- **New `requestTranslate`.** It POSTs `{id, host}` with `{"content-type": "application/json", ...profileHeaders()}`, as `reactions.ts:69-75` and `blocks.ts:59` do, and throws `ProfileKeyRejectedError` on 401.
- **Docstring.** "the gateway read of a video's English cues" gains the request.

**Depends on it.** `pages/video-page/translate.ts:9` is its only importer. The types are not imported elsewhere in `client/frontend/src`.

**Regression risk: high.**
- **(1) Test fixtures.** `READY`/`NONE` (`tests/active/test_frontend_translate.py:49-50`) have no `available`. A strict parser makes every existing page test show "malformed".
- **(2) Exact query.** `test_frontend_translate.py:307` asserts the query is exactly `{id, host}`.
- **(3) Errors the poll cannot tell apart.** `fetchTranslate` runs `JSON.parse` before checking `response.ok` (:52-53). A non-JSON 502 page from nginx therefore throws a `SyntaxError`, and every other non-401 failure throws a plain `Error` with no status. The poll's retry set (network error or 502) cannot be told apart from 400, 429 or a malformed answer. Either expose the status, or treat every error except `ProfileKeyRejectedError` as retryable.
- **(4) `exists` answers.** An `exists` → `ready`/`running` answer without cues throws if the request path shares the cue-requiring parser.
</impact>
<impact path="client/frontend/src/pages/video-page/translate.ts" element="module docstring (1-5); module state (21-29); turnOn (98-119); turnOff (121-130); startPolling/stopPolling (132-145); findCue (64-79); showAt/showText/setStatus (151-171); new state-poll setTimeout chain, running-cue merge, labels">
**What changes.**
- **`turnOn`.** It branches on `state` and `available`:
  - `none` with `available` false: `NO_TRANSLATION` (:16), unchanged.
  - `none` with `available` true: one `requestTranslate`, whose answer is handled like a state answer.
  - `queued`/`running` with `available` true: start the state poll.
  - `already_english`/`failed`/`busy`: set their labels.
  - `queued`/`running` with `available` false (pass 2): show the label, and for `running` show the cues and start the position poll, without a state poll.
- **New module state.** The state-poll handle, an in-flight flag, the backoff value (2 s → 16 s) and the held running count.
- **Running cues.**
  - They are appended and re-sorted with the `parseTranslateState` comparator, because the worker's running list is unsorted (`translate-worker.py:413` vs :420) and `findCue` binary-searches by start.
  - The list resets when `total` falls below the held count, or when `queued` follows held running cues.
  - `ready` replaces the list, and `failed` clears it.
- **Position poll.** `startPolling` (the 1 s position `setInterval`) also runs on `running`.
- **`turnOff`.** It must also clear the state-poll timer. Bumping `requestTicket` only drops in-flight answers, so a scheduled `setTimeout` still fires unless it is cleared or checks the ticket.
- **Labels.** Set via `setStatus` (`textContent`). "Loading translation…" (:102) stays.
- **Docstring.** It gains the request and polling behaviour.

**Depends on it.**
- `pages/video-page/index.ts:21` and `:288-289` (`setupTranslate`).
- The `playbackStatusUpdate` listener (:85-88), which reads the shared `cues`.
- `test_frontend_translate.py`, which bundles `index.ts`.

**Regression risk: high.**
- **(1) Stale chains.** A chain started by an earlier `turnOn` and not cleared keeps polling across off → on → off, which breaks R1.
- **(2) Re-entry.** `turnOn` while a poll request is in flight must not leave two chains running.
- **(3) 401.** `ProfileKeyRejectedError` must stop the poll, not retry it.
- **(4) Unclassified errors.** 429, proxy-HTML 502s and malformed answers are not classified (see the `data/translate.ts` entry).
- **(5) Test stub.** The existing fetch stub answers GET and POST alike, so a `none` + `available: true` fixture would trigger a POST whose answer is again `none`.
- **(6) bfcache.** A page restored from the back-forward cache resumes its timers. It is the same video, so this is acceptable.
</impact>
<impact path="client/frontend/src/pages/video-page/index.ts" element="setupTranslate import (21) and call (288-289)">
**What changes.** Nothing.
- It passes `{id: metadata.videoUuid || ..., host}`.
- The video page has no in-page navigation (no pushState or popstate under `pages/video-page`), so R1's "page changes video" is a full page load.

**Depends on it.** The `test_frontend_translate.py` bundle entry point (`test_frontend_translate.py:205`).

**Regression risk: none.**
</impact>
<impact path="client/frontend/src/data/profile.ts" element="ProfileKeyRejectedError (15), profileHeaders (31)">
**What changes.** Nothing; both are reused by `requestTranslate`.

**Regression risk: none.**
</impact>
<impact path="client/frontend/video-page.html" element="#translate-overlay (38), #translate-toggle / #translate-status (92-93)">
**What changes.** Probably nothing. The labels go into the existing `role="status"` span.
- `test_frontend_translate.py` reads the toggle label from this file, and `tests/config.json:411` maps it to that test.
- If the markup is edited, `dist/video-page.html` must be rebuilt, because pages carry no hash and `test_frontend_dist.py:25` compares them exactly.

**Regression risk: low.**
</impact>
<impact path="client/frontend/src/video.css" element=".translate-overlay, .block-status">
**What changes.** Probably nothing. The longest label, the `busy` one, may wrap beside the toggle. This is uncertain and cosmetic. The file is in the `test_frontend_dist.py` group (`tests/config.json:372`), so editing it selects the dist test.

**Regression risk: low.**
</impact>
<impact path="client/frontend/dist/assets/video-pSg73mMI.js" element="committed built video-page chunk">
**What changes.** Any edit to the two `translate.ts` files changes this chunk's content hash, so `dist/` is rebuilt and committed under a new name.
- `requestTranslate` stays in this chunk unless the import graph changes.
- Shared chunks (`reactions-T0agINKk.js`, `api-base-ouyYHZ10.js`) should not change. This is uncertain.

**Depends on it.** Production static serving, and `tests/active/test_frontend_dist.py:24`, which compares the asset names with a fresh `vite build`.

**Regression risk: medium.**
- The `test_frontend_dist.py` group (`tests/config.json:349-396`) lists neither `src/data/translate.ts` nor `src/pages/video-page/translate.ts`, so a selective run misses a stale `dist/`.
- The plan-48 record notes that `@peertube/embed-api`/`jschannel` resolution affected `vite build` in this checkout.
</impact>
<impact path="client/frontend/dist/video-page.html" element="script/link references to the hashed video chunk">
**What changes.** After the rebuild it must reference the new hash.

**Regression risk: medium.** `test_frontend_dist.py:25` compares it exactly.
</impact>
<impact path="tests/active/test_internal_translate.py" element="NONE/READY (144-145); handler tests (528-620); _server stand-in (493-495); _handle (498-500); startup test (623-654); docstring (1, 21-35)">
**What changes.**
- **Constants.** They gain `"available": False`. The store has the heartbeat table and no row, which reads as unavailable.
- **New cases:**
  - `queued`, `running` with and without `after`, and `total`.
  - `failed` and `already_english`, each with and without an instance track.
  - A fresh, a stale and a future heartbeat, written with `write_translate_heartbeat`.
  - A corrupt `ready` row, and a corrupt `running` `cues_json`.
  - `after` validation (bool, negative, string, and order versus 404).
  - The enqueue route: queued, exists, cap→busy, unavailable, closed store → 503, plus the same 400 and 404 answers.
  - `/internal/translate/enqueue` behind the gate in the startup test.
- **Handler entry point.** `_handle` calls `module.handle_internal_translate` directly, so the enqueue tests need a matching helper.
- **Docstring.** The exact answers it states (:1, :31, :33) change.

**Regression risk: high.** The suite goes red as soon as `available` is added.
</impact>
<impact path="tests/active/test_server.py" element="translate block (1529-1693): TRANSLATE_NONE/TRANSLATE_READY (1533, 1536), TRANSLATE_ENGINE_ANSWERS (1549-1558), _TranslateEngine (1561-1590), seen assertions (1633, 1647, 1664-1667, 1676, 1693); docstring (132-137)">
**What changes.**
- **Constants.** `TRANSLATE_NONE`/`TRANSLATE_READY` gain `available`.
- **"unknown state".** It becomes a truly unknown state, such as `"bogus"`.
- **"engine none".** Its expected outcome depends on the strictness decision for `available`.
- **The stub.** `_TranslateEngine` already records method, path, token, request id and body, but answers one `server.reply` on every path. It needs a reply chosen by path for the POST tests.
- **New tests:**
  - POST order 429 → 401 → 400 with no Engine call on refusal.
  - Body checks (non-str, blank, 201 characters, `{}`, invalid JSON).
  - The enqueue mapping, including `busy` and 503 → 502.
  - `after` passed as an int, `after=١` (a Unicode digit) refused, and `after` absent from the body when not given.
- **Docstring.** :132-137 changes.

**Regression risk: high.** The existing parametrized cases flip as soon as the validators widen.
</impact>
<impact path="tests/active/test_frontend_translate.py" element="READY/NONE (49-50); RUNNER fetch stub (140-149); _page timeout=60 (218); _translate_requests (232-233); count assertions (251, 271-272, 288, 305, 307, 310, 317, 332, 337, 343); wait steps (187, 372); docstring (1-17)">
**What changes.**
- **Fixtures.** They gain `available: false` to keep the plan 48 path.
- **The fetch stub.** It records only `{url, key}` (:144) and gives one fixed answer per path (:147). It must record `init.method` and `init.body`, and serve sequenced answers per method and path (queued → running with partial cues → ready).
- **`_translate_requests`.** It filters by path only, so it must tell GET from POST. The count assertions become "N GET, M POST".
- **Backoff tests.** They wait in real time (`{"wait": ms}`, :187), inside the 60 s subprocess timeout (:218). Walking 2→4→8→16 s takes about 30 s, so the cap test is long. Only that test should raise the limit.
- **Exit.** The runner ends with `process.exit(0)` (:196), so a pending poll timer cannot hang it.

**Regression risk: high.** Every existing case is at risk from the fixture shape and the stub.
</impact>
<impact path="tests/active/test_subtitles.py" element="fetch_ready_subtitles uses (7, 162-164, 247 subprocess string, 278, 304, 312)">
**What changes.** Nothing, as long as `fetch_ready_subtitles` stays. Tests for the new readers can be added here.

**Regression risk: medium.** That applies only if the function is removed, which would break this file, including the subprocess string at :247.
</impact>
<impact path="tests/active/test_translate_worker.py" element="test_a_b1_takeover_mid_job_leaves_the_ready_instance_row_untouched (927-944), docstring line 27, build_opener patch (488)">
**What changes.** The test still passes, because it calls `store_ready_subtitles` directly. It now models only the remaining race (an in-flight route fetch, or an old-code Engine), so its name and docstring line 27 could say so. The patch at :488 needs `build_opener` to stay a module global in `internal_translate.py`.

**Regression risk: low.**
</impact>
<impact path="tests/config.json" element="groups test_server.py (78-88), test_frontend_dist.py (349-396), test_internal_translate.py (397-406), test_frontend_translate.py (407-412), test_translate_worker.py (416-424)">
**What changes.** Optionally:
- add both `translate.ts` paths to the `test_frontend_dist.py` group, so selective runs catch a stale `dist/`;
- add `engine/server/data/time.py` and `engine/server/db/jobs/translate-worker.py` (the heartbeat coupling) to the `test_internal_translate.py` group;
- add `client/frontend/src/data/profile.ts` to the `test_frontend_translate.py` group.

**Regression risk: low.** This affects test selection only.
</impact>
<impact path="tests/check-frontend-client-gateway.sh" element="forbidden-route pattern (34)">
**What changes.** The pattern forbids `/internal/videos/resolve|/internal/videos/metadata|/internal/events/ingest`, but not `/internal/translate`. Adding `/internal/translate` would also cover `/internal/translate/enqueue` as a substring. This is optional hardening.

**Regression risk: none.** The frontend never names `/internal/`.
</impact>
<impact path="engine/server/README.md" element="/internal/translate bullet (15-21); store-contract section (24-31); intro (3)">
**What changes.**
- **Line 15.** The answer shapes become six states plus `available`, the optional `after`, and `total`.
- **Line 18.** "A key in a job state is a miss ... a `ready` store from the route replaces the job row" now holds only for `failed`/`already_english` (plus the in-flight race). "The route stores only `ready`" gains the enqueue route's queued rows. "A cache read error counts as a miss" must also cover the availability read.
- **New bullet** for `/internal/translate/enqueue`: body, the same 400/404 answers, the heartbeat gate, the mapping, and the 503.
- **Line 25.** The CLI is not the only queuer.
- **Line 30.** "Only `fetch_ready_subtitles` reads cues ... no reader serves `running` cues yet" is now false.
- **Line 31.** Name the 15 s freshness rule.
- **Line 3.** Still accurate.

**Regression risk: none.**
</impact>
<impact path="engine/server/db/jobs/docs/TRANSLATE_WORKER.md" element="lines 7, 10, 13, 33, 34, 37, 39, 49, 100-104, 146-148, 152">
**What changes.**
- **Line 148 (takeover section).** It is rewritten. The route no longer fetches for `queued`/`running`. A takeover now comes only from a route fetch already in flight when the job was queued, or from an old-code Engine. The guard stays.
- **Line 7.** "serves the `ready` rows it writes" now also covers `running` cues and the job states.
- **Lines 10 and 33.** `enqueue` is not the only inserter; the page route queues too.
- **Line 34.** `running` cues are now served.
- **Line 37.** "Partial cues ... never served" stays true for `failed`.
- **Line 39.** "A failed key is never queued again" stays true.
- **Lines 49 and 100-104.** The "at enqueue" checks (duration, cap, whitelist/denylist) describe the CLI. Say which checks the page route applies; duration is open.
- **Line 152.** Name the Engine's 15 s threshold.

**Regression risk: none.**
</impact>
<impact path="CONTEXT.md" element="'Translate state' (17), 'Translate job' (19)">
**What changes.**
- **Line 17.** "as does one whose translate job has not ended `ready`" is superseded by the states `queued`/`running` (partial cues)/`already_english`/`failed`, `busy` (request route only, never stored) and `available`.
- **Line 19.** "Jobs are queued from the worker's command line" now also covers the page, when Translate is on, the state is `none` and generation is available.
- Optionally, add a glossary term for "generation available".

**Regression risk: none.**
</impact>
<impact path="client/README.md" element="lines 25, 32, 34, 39, 45, 51">
**What changes.**
- **Line 32.** The GET bullet gains `after` (ASCII digits, else 400), the states, `available`, `total`, and 404 → `none` with `available:false`. A new POST bullet covers the check order, body rules, the 6 s call to `/internal/translate/enqueue`, the answers including `busy`, and 502 otherwise.
- **Line 39.** The bridge-call list gains enqueue.
- **Line 45.** "profile-gated read" now also covers a POST.
- **Line 51.** Add `/internal/translate/enqueue`.
- **Lines 25 and 34.** They already say "translate" and stay accurate.

**Regression risk: none.**
</impact>
<impact path="client/frontend/README.md" element="lines 8, 20-21">
**What changes.**
- **Line 21** describes only `ready`/`none`. It gains:
  - the request on `none` with `available`;
  - the 2→16 s state poll, its reset and its stop set;
  - `after`/`total` with the merge, re-sort and reset;
  - `ready` replacing the list;
  - the five labels;
  - `failed` clearing the lines;
  - `busy` needing off then on;
  - unavailable behaving exactly as in plan 48.
- **Line 8** can mention `POST /api/translate`.
- **Line 20** ("requests the cues exactly as a click does") stays accurate.

**Regression risk: none.**
</impact>
<impact path="README.md" element="lines 27, 53, 54">
**What changes.**
- **Line 27.** "jobs queued from its command line" now also covers the video page.
- **Line 54.** Add `/internal/translate/enqueue`.
- **Line 53.** "profile-gated `/api/translate`" is accurate. It can mention that the route now also queues generation.

**Regression risk: none.**
</impact>
<impact path="DEPLOYMENT.md" element="lines 98, 174, 230, 283, 293-295, 302, 346, 348, 579, 586, 751">
**What changes.**
- **Line 98.** The Engines also write queued job rows.
- **Line 230.** Jobs are also queued from the video page while the heartbeat is fresh. State the duration-check decision.
- **Line 283.** "resolves the video ... as `/internal/translate` does" plus `--max-duration`. Say whether the page route checks duration.
- **Lines 293-295.** Deleting a failed row now also lets a viewer with Translate on re-queue it from the page.
- **Line 302.** "under 10 s while the worker serves" can name the Engine's 15 s rule.
- **Lines 346 and 348.** A stale heartbeat now also turns page generation off.
- **Line 586.** Add `/internal/translate/enqueue`.
- **Line 751.** "on each cache miss" now means no row, or a `failed`/`already_english` row.
- **Line 579.** `/api/translate` already covers both methods.
- **Line 174.** The 20 s timeout still holds; the new POST uses 6 s.
- **Upgrade order.** Add the order if the Client parser stays strict (see the `engine_api_client.py` entry).

**Regression risk: none.**
</impact>
<impact path="DATA_BUILD.md" element="line 15">
**What changes.** `subtitles.db` is also written with queued job rows by the Engine's `/internal/translate/enqueue`, not only by the worker and its `enqueue` command.

**Regression risk: none.**
</impact>
<impact path="docs/project/roadmap.md" element="lines 24, 60">
**What changes.** At delivery, line 60's "Remaining: Whisper generation requested and shown from the video page (`docs/project/plans/50-...`)" moves to Delivered with the archive path. Line 24's DONE list may gain the item.

**Regression risk: none.**
</impact>
<impact path="docs/project/plans/18-english-subtitles.md" element="line 8">
**What changes.** "3. B2's page side, `docs/project/plans/50-translate-generation-in-page.md`" is marked delivered, with its archive path.

**Regression risk: none.**
</impact>
<impact path="docs/project/plans/50-translate-generation-in-page.md" element="the source plan">
**What changes.** It is archived at delivery under `docs/project/plans/archive/`, and the roadmap and plan 18 links follow it.

**Regression risk: none.**
</impact>
</impacts>

## Documentation to update

- [x] `engine/server/README.md` - updated: I rewrote the `/internal/translate` entry in `engine/server/README.md` to match the route as it works now, added an entry for `/internal/translate/enqueue`, and corrected the store-contract lines. Every claim was checked against `internal_translate.py`, `similar.py`, `data/subtitles.py` and `translate-worker.py`.
- [x] `CONTEXT.md` - updated: CONTEXT.md: "Translate state" now covers all six states, `busy` and `available`; added a "Generation available" entry; "Translate job" now says jobs can also be queued from the video page.
- [x] `client/README.md` - updated: I updated `client/README.md` for the new translate states, the `after` parameter and the new `POST /api/translate`. I checked each line against `client/backend/server.py` and `client/backend/lib/engine_api_client.py`.
- [x] `client/frontend/README.md` - updated: client/frontend/README.md: the Translate section now covers the generation request, the job states with their labels, and the backoff state poll.
- [x] `engine/server/db/jobs/docs/TRANSLATE_WORKER.md` - updated: TRANSLATE_WORKER.md now covers the Engine's page enqueue route, running cues being served, the narrower takeover case and the Engine's 15 s heartbeat freshness rule.
- [x] `README.md` - updated: README.md now covers translate jobs started from the video page and lists the Engine's enqueue route in the boundary contract.
- [x] `DEPLOYMENT.md` - updated: I updated DEPLOYMENT.md for page-requested translate jobs: the Engine's enqueue route, the 15 s heartbeat rule, the missing duration check on the page route, and the upgrade order.
- [x] `DATA_BUILD.md` - updated: DATA_BUILD.md: the paragraph about `subtitles.db` now lists the Engine's `/internal/translate/enqueue` among the writers, because it inserts queued translate jobs.
- [x] `docs/project/roadmap.md` - updated: The roadmap now lists plan 50, Translate generation from the video page, as delivered. It is a DONE line in Delivered, and the F11-M2 line's Remaining now names only the player.
- [x] `docs/project/plans/18-english-subtitles.md` - updated: Plan 18's build list now marks B2's page side as delivered and points it at the archived plan 50.
- [x] `engine/server/api/handlers/__init__.py` - updated: The `internal_translate` line in `engine/server/api/handlers/__init__.py` now also names the bridge request that queues a whisper job.
- [x] `engine/server/api/handlers/internal_translate.py` - out of scope: Phase 2 already rewrote the module docstring. It covers the six states, `after`/`total`, `available` against `HEARTBEAT_FRESH_MS`, the no-fetch `queued`/`running` rows, "this route stores only ready", and a full paragraph on `/internal/translate/enqueue` (the gate, the mapping, `busy`, the 503). It matches the diff.
- [x] `engine/server/api/handlers/similar.py` - out of scope: The build updated the route list: line 13 now describes the translate state, availability and stored or instance cues, and a new line names `/internal/translate/enqueue`. Both match the dispatch in the diff.
- [x] `engine/server/data/subtitles.py` - out of scope: The build updated the module docstring: running cues are read through `fetch_subtitle_state`, and both Engines and the worker write the file. It also changed `finish_translate_failed` to "a failed row's cues are never served". The `_update_claim` docstring at line 159 ("False when B1's route took the row over") and `store_ready_subtitles` ("Against a job row it ends the job") are still true, because the takeover still happens in the in-flight-fetch race. Neither claims how often it happens.
- [x] `engine/server/db/jobs/translate-worker.py` - out of scope: The build added the `rat-tail:` comment above `HEARTBEAT_SECONDS` naming `HEARTBEAT_FRESH_MS`. `JobTakenOver` ("B1's route replaced the running row", line 93), the `run_job` docstring (line 469) and the takeover log (line 483) describe an event that still happens: a route fetch already in flight when the job was queued, or an old Engine. None of them claims the route fetches for running rows, so they are still accurate. The module docstring's line 4 also stays true.
- [x] `client/frontend/src/pages/video-page/translate.ts` - out of scope: Phase 4 added a docstring paragraph. It covers the single generation request on `none` with `available`, and the separate state poll with backoff, `after` and merging. It also lists the stop conditions: any other state, no `available`, a 401, and turnOff. This matches the diff.
- [x] `client/frontend/src/data/translate.ts` - out of scope: Phase 4 rewrote the module docstring for the state read and the generation request. The `fetchTranslate` comment now describes `after`. `requestTranslate` has its own comment, and `TranslateRequestState` explains `busy`. This matches the diff.

## Implementation plan

## Draft implementation: plan 50, Translate generation requested and shown from the video page

I read these before drafting: `internal_translate.py` (whole file), `data/subtitles.py` (whole file), the `similar.py` import (101) and `_dispatch_post` (441-474), `engine_api_client.py` (whole file), `server.py` (imports at 32-36, the allow-list at 95-145, the GET/POST dispatch at 461-539, `_require_profile`/`_rate_limit_check`/`_respond_engine_failure` at 541-561, `_handle_translate_get` at 1065-1081, `_handle_block_add` at 1116-1133), both `translate.ts` files (whole), `reactions.ts:65-83` (the POST-with-profile pattern), and the `server_config` import lines across `engine/server`.

### What the build must test

- **Engine store.** The key reader returns `(state, cues_json)` or None. The heartbeat reader returns `beat_at` or None, including on a fresh schema with no row.
- **Engine state route.**
  - `available` is on every 200: no row, fresh, stale (`now - 15_001`), and future (`now + 1`).
  - `ready` → cues. `queued` → state only, with no instance fetch.
  - `running` with `after` absent, 0, mid, and past total. Empty, unset or corrupt `cues_json` → `[]` with total 0.
  - `failed`/`already_english` with and without an instance track.
  - A corrupt `ready` row with an instance miss → `none`.
  - `after` given as a bool, a negative number, a string, null or a float → 400.
  - An unknown video with a bad `after` → 404, which pins the order.
  - A closed store → `none` / `available: false`.
- **Engine enqueue route.**
  - Unavailable → `none`/false, and no row is written.
  - queued, exists (each state), cap → `busy`.
  - A `sqlite3.Error` from enqueue → 503.
  - The same 400 and 404 answers as the state route, including the denylist.
  - Behind the bridge gate: 401 without the token, 404 for an unknown video with it.
- **Client GET.**
  - `after` is passed through as an int and is absent from the Engine body when not given.
  - `after=١`, `after=-1` and `after=x` → 400. `after=` reads as absent.
  - The six states with `available` pass through.
  - A missing `available` → false. A non-bool `available`, a bad `total`, or an unknown state → 502.
  - 404 `Video not found` → `none`/false.
- **Client POST.**
  - 429 → 401 → 400 in that order, with no Engine call on any refusal.
  - Body checks: `{}`, a non-str value, a blank value, 201 characters, invalid JSON.
  - The mapping, including `busy`. Engine 503 → 502.
  - An old Engine's 404 `Not found` → 502.
- **Page.**
  - Unavailable `none` → the plan 48 message, with no POST and no poll.
  - `none`+available → exactly one POST.
  - queued → running (partial) → running (more, with `after` = held count) → ready.
  - A lower `total` → the next poll asks from 0.
  - `failed` clears the lines. `busy` → its label and no poll.
  - Off stops the chain, and so does a 401.
  - A 502 keeps the label and retries.
  - The labels are set via `textContent`.
- **Worker.** Its imports still load: the existing `test_translate_worker.py`.

### Module map (no new modules)

| File | Change |
|---|---|
| `engine/server/data/subtitles.py` | Adds `fetch_subtitle_state` and `fetch_translate_heartbeat`. `fetch_ready_subtitles` stays (`test_subtitles.py` still uses it). Docstrings at 3, 150 and 177. |
| `engine/server/api/handlers/internal_translate.py` | Adds `HEARTBEAT_FRESH_MS`, `_resolve_translate_key`, `_generation_available`, `_read_key`, `_stored_cues` and `handle_internal_translate_enqueue`. Reorders `handle_internal_translate`. `_cached_cues` is deleted. Module docstring. |
| `engine/server/api/handlers/similar.py` | Import and one dispatch branch. Docstring line 13 plus the new route line. |
| `engine/server/api/handlers/__init__.py` | Docstring line 8. |
| `engine/server/db/jobs/translate-worker.py` | Comments and docstrings only (92, 468, 482, rat-tail on `HEARTBEAT_SECONDS`). |
| `client/backend/lib/engine_api_client.py` | Adds `TRANSLATE_STATES` and `_checked_cues`/`_translate_available`. `fetch_translate` gains `after`. Adds `request_translate`. |
| `client/backend/server.py` | Allow-list, `_handle_translate_get`, the new POST branch, `_handle_translate_post`, and the import. |
| `client/frontend/src/data/translate.ts` | Union types, `fetchTranslate(after?)`, `parseTranslateState`, `requestTranslate`/`parseRequestState`. |
| `client/frontend/src/pages/video-page/translate.ts` | `turnOn` rewritten around `applyState`. Adds the state-poll `setTimeout` chain, the running merge and the labels. `turnOff` clears the chain. |
| `client/frontend/dist/**` | Rebuilt and committed (new video chunk hash, `video-page.html`). |
| Tests and docs | See the sections below. |

### Engine store: `engine/server/data/subtitles.py`

```python
def fetch_subtitle_state(conn: sqlite3.Connection, video_id: str, instance_domain: str, target_language: str) -> tuple[str, str | None] | None:
    """A key's state and raw cues_json in one read, or None for no row; the caller decides what the cues mean for that state."""
    row = conn.execute(f"SELECT state, cues_json FROM subtitles WHERE {_KEY}", (video_id, instance_domain, target_language)).fetchone()
    return (row[0], row[1]) if row is not None else None


def fetch_translate_heartbeat(conn: sqlite3.Connection) -> int | None:
    """The translate worker's last beat_at in ms, or None when no worker has beaten."""
    row = conn.execute("SELECT beat_at FROM translate_worker_heartbeat WHERE id = 1").fetchone()
    return row[0] if row is not None else None
```

Both readers are pure. A connection whose schema was never ensured raises `sqlite3.Error`, which the handler absorbs.

### Engine handler: `engine/server/api/handlers/internal_translate.py`

**Imports.**

```python
from data.subtitles import enqueue_translate_job, fetch_subtitle_state, fetch_translate_heartbeat, store_ready_subtitles
from server_config import SUBTITLE_QUEUE_CAP
```

`server_config` is already a top-level import of `handlers/video.py:22` and `translate-worker.py:43`, so the worker gains no new import-time dependency. `build_opener`, `fetch_bounded`, `fetch_instance_track` and the other four names imported by the worker are untouched, as are the test patch points.

**Constant.**

```python
# rat-tail: three of the translate worker's HEARTBEAT_SECONDS (5 s) beats, so one late beat is tolerated; raise it with the beat.
HEARTBEAT_FRESH_MS = 15_000
```

**Shared resolve.** These are lines 222-247 moved verbatim. Every 400/404 text and the check order are unchanged.

```python
def _resolve_translate_key(handler: Any, server: Any) -> tuple[dict[str, Any], str, str, str] | None:
    """Validate the {id, host} body and resolve its video as both translate routes must: (body, canonical video_id, instance_domain, the instance's video key); None once a 400 or 404 was answered."""
    ...  # read_json_body → 400 str(exc); id/host → 400 "Missing id or host"; normalize_host → 400 "Invalid host"; resolve_video_row (own 404); denylist under db_lock → 404 VIDEO_NOT_FOUND
    return body, row["video_id"], row["instance_domain"], row["video_uuid"] or row["video_id"]
```

**Availability and the key read.**

```python
def _generation_available(conn: sqlite3.Connection) -> bool:
    """Whether a translate worker beat within HEARTBEAT_FRESH_MS (AC1); no beat, a store error, or a beat dated ahead of now is not available, so a wrong clock cannot hold it fresh. The caller holds subtitles_db_lock."""
    try:
        beat_at = fetch_translate_heartbeat(conn)
    except sqlite3.Error as exc:
        logging.warning("[translate] heartbeat read failed: %s", exc)
        return False
    return beat_at is not None and 0 <= now_ms() - beat_at <= HEARTBEAT_FRESH_MS


def _read_key(server: Any, video_id: str, instance_domain: str) -> tuple[tuple[str, str | None] | None, bool]:
    """The key's (state, cues_json) and whether generation is available, under one lock hold; a closed store or a store error reads as no row and not available, so the instance answers instead."""
    try:
        with server.subtitles_db_lock:
            conn = server.subtitles_db
            if conn is None:
                return None, False
            return fetch_subtitle_state(conn, video_id, instance_domain, TARGET_LANGUAGE), _generation_available(conn)
    except sqlite3.Error as exc:
        logging.warning("[translate] cache read failed video_id=%s host=%s: %s", video_id, instance_domain, exc)
        return None, False


def _stored_cues(cues_json: str | None) -> list[Any] | None:
    """cues_json loaded as a list, or None when it is unset, does not load, or is not a list."""
    try:
        cues = json.loads(cues_json or "")
    except (ValueError, RecursionError):
        return None
    return cues if isinstance(cues, list) else None
```

**State route (AC3 order, AC4 slice).**

```python
def handle_internal_translate(handler: Any, server: Any) -> bool:
    """Answer a video's English translate state with whether generation is available; nothing is read from the store or the instance until the video resolves and its host is not denied."""
    resolved = _resolve_translate_key(handler, server)
    if resolved is None:
        return True
    body, canonical_id, instance, video_key = resolved
    after = body.get("after", 0)
    if isinstance(after, bool) or not isinstance(after, int) or after < 0:
        respond_json(handler, 400, {"error": "Invalid after"})
        return True
    row, available = _read_key(server, canonical_id, instance)
    state = row[0] if row is not None else None
    stored = _stored_cues(row[1]) if row is not None else None
    if state == "ready" and stored:
        respond_json(handler, 200, {"state": "ready", "cues": stored, "available": available})
        return True
    # A queued or running job is answered from the store with no instance fetch; the worker checks the instance itself when it claims the job.
    if state == "queued":
        respond_json(handler, 200, {"state": "queued", "available": available})
        return True
    if state == "running":
        cues = stored or []
        respond_json(handler, 200, {"state": "running", "cues": cues[after:], "total": len(cues), "available": available})
        return True
    fetched = fetch_instance_track(instance, video_key)
    if fetched is not None:
        track_text, cues = fetched
        _store_cues(server, canonical_id, instance, track_text, cues)
        respond_json(handler, 200, {"state": "ready", "cues": cues, "available": available})
        return True
    # A ready row whose cues do not load reads as none: both parsers refuse ready without cues.
    respond_json(handler, 200, {"state": state if state in ("failed", "already_english") else "none", "available": available})
    return True
```

How this code behaves at the edges:
- **`after` is checked after resolve,** so an unknown video with a bad `after` answers 404. A test pins this. The Client refuses a bad `after` before calling the Engine anyway.
- **The instance fetch stays outside `subtitles_db_lock`.** The `available` sent with a fetched answer is the value read before the fetch.
- **Malformed running cues.** A `running` element that is not a cue dict passes through, and the Client's per-cue check makes that poll a 502. That needs a hand-damaged row (the worker writes with `allow_nan=False`), so it is accepted rather than filtered.

**Enqueue route (AC2).**

```python
def handle_internal_translate_enqueue(handler: Any, server: Any) -> bool:
    """Queue a whisper job for a video when a translate worker is serving (AC2): queued, the existing state (a row is never overwritten), or busy when the queue is full; not available queues nothing."""
    resolved = _resolve_translate_key(handler, server)
    if resolved is None:
        return True
    _, canonical_id, instance, _ = resolved
    try:
        with server.subtitles_db_lock:
            conn = server.subtitles_db
            outcome = enqueue_translate_job(conn, canonical_id, instance, TARGET_LANGUAGE, SUBTITLE_QUEUE_CAP, now_ms()) if conn is not None and _generation_available(conn) else None
    except sqlite3.Error as exc:
        logging.warning("[translate] enqueue failed video_id=%s host=%s: %s", canonical_id, instance, exc)
        respond_json(handler, 503, {"error": "Translate store unavailable"})
        return True
    if outcome is None:
        respond_json(handler, 200, {"state": "none", "available": False})
        return True
    kind, state = outcome
    respond_json(handler, 200, {"state": "busy" if kind == "cap" else state, "available": True})
    return True
```

Decisions behind this route:
- **Closed store → not available, not 503.** I follow AC1 here ("a closed store … count[s] as not available") over the plan's "closed store answers 503". A heartbeat read error is likewise not available. Only a `sqlite3.Error` from `enqueue_translate_job` itself answers 503.
- **No duration check.** There is no `SUBTITLE_MAX_DURATION` check, because AC2 says to resolve "exactly as `handle_internal_translate` does". A long video takes a queue slot and ends `failed` at the worker's claim-time resolve. This is named in the docs. If the operator wants a duration check later, it is one comparison against `row["duration"]`, inside `_resolve_translate_key`'s caller.
- **Lock hold.** The heartbeat check and the enqueue happen in one lock hold, so availability cannot flip between them.

**Dispatch (`similar.py`).** The import line becomes `from handlers.internal_translate import handle_internal_translate, handle_internal_translate_enqueue`, and the new branch goes right after the `/internal/translate` branch, below the bridge gate at 444:

```python
        if url.path == "/internal/translate/enqueue":
            handle_internal_translate_enqueue(self, self.server)
            return
```

### Client gateway: `engine_api_client.py`

```python
TRANSLATE_STATES = frozenset(("none", "queued", "running", "ready", "already_english", "failed"))
# busy is the enqueue route's full-queue answer and is never stored.
TRANSLATE_REQUEST_STATES = TRANSLATE_STATES | {"busy"}


def _translate_available(body: dict[str, Any]) -> bool:
    """The answer's available flag; an Engine from before plan 50 sends none, read as False so it keeps plan 48's behaviour; any non-bool raises."""
    available = body.get("available", False)
    if not isinstance(available, bool):
        raise EngineApiError("Engine translate returned invalid payload")
    return available


def _checked_cues(cues: Any) -> list[dict[str, Any]]:
    """Copy start, end and text of each cue, so nothing else the Engine adds reaches the browser; any malformed cue raises."""
    ...  # body of today's loop at 171-176, raising on a non-list too


def fetch_translate(engine_base_url: str, video_id: str, host: str, after: int | None = None) -> dict[str, Any]:
    """Ask the Engine for a video's English translate state: one of TRANSLATE_STATES with available, cues for ready and running, total for running; after (a running cue count) is sent only when given. Anything else raises EngineApiError."""
    payload: dict[str, Any] = {"id": video_id, "host": host}
    if after is not None:
        payload["after"] = after
    status, body = _post_json(f"{engine_base_url.rstrip('/')}/internal/translate", payload, timeout=TRANSLATE_TIMEOUT_SECONDS)
    if status == 404 and body.get("error") == TRANSLATE_NOT_FOUND_ERROR:
        return {"state": "none", "available": False}
    if status != 200:
        raise EngineApiError(f"Engine translate failed (HTTP {status}): {body.get('error') or 'unknown error'}")
    state = body.get("state")
    if state not in TRANSLATE_STATES:
        raise EngineApiError("Engine translate returned invalid payload")
    answer: dict[str, Any] = {"state": state, "available": _translate_available(body)}
    if state in ("ready", "running"):
        answer["cues"] = _checked_cues(body.get("cues"))
    if state == "running":
        total = body.get("total")
        if not isinstance(total, int) or isinstance(total, bool) or total < 0:
            raise EngineApiError("Engine translate returned invalid payload")
        answer["total"] = total
    return answer


def request_translate(engine_base_url: str, video_id: str, host: str) -> dict[str, Any]:
    """Ask the Engine to queue a whisper job: {state, available} with state one of TRANSLATE_REQUEST_STATES and no cues (an existing ready or running job is read through fetch_translate); anything else raises EngineApiError."""
    status, body = _post_json(f"{engine_base_url.rstrip('/')}/internal/translate/enqueue", {"id": video_id, "host": host})
    if status == 404 and body.get("error") == TRANSLATE_NOT_FOUND_ERROR:
        return {"state": "none", "available": False}
    if status != 200:
        raise EngineApiError(f"Engine translate request failed (HTTP {status}): {body.get('error') or 'unknown error'}")
    state = body.get("state")
    if state not in TRANSLATE_REQUEST_STATES:
        raise EngineApiError("Engine translate request returned invalid payload")
    return {"state": state, "available": _translate_available(body)}
```

**Version skew.** I chose to read a missing `available` as false rather than refuse the answer.
- **New Client, old Engine:** answers keep plan 48 behaviour instead of becoming 502s.
- **Old Client, new Engine:** the old Client still turns job states into 502s, but those exist only once a new Client or the CLI queued a job. `DEPLOYMENT.md` therefore says: deploy the Engine, then the Client right after.

An old Engine's 404 `Not found` on the enqueue route stays a 502, as the comment at line 19 requires.

### Client server: `server.py`

- **Allow-list.** It becomes `"/api/translate": {"id", "host", "after"}`. The comment gains "after is read only on GET".
- **Import.** It adds `request_translate`.
- **`_handle_translate_get`:**

```python
        query, error = _sanitize_query(PROXY_ALLOWED_QUERY_PARAMS["/api/translate"], params)
        # A blank or whitespace value was dropped by _sanitize_query, so it fails as missing; after is optional.
        if error is None and ("id" not in query or "host" not in query or any(len(value) > BLOCK_REFERENCE_MAX_LENGTH for value in query.values())):
            error = "id and host must be non-empty strings"
        after = query.get("after")
        # isascii first: str.isdigit accepts other scripts' digits, which int() would also read.
        if error is None and after is not None and not (after.isascii() and after.isdigit()):
            error = "after must be a non-negative integer"
        ...
            payload = fetch_translate(self.server.engine_ingest_base, query["id"], query["host"], int(after) if after is not None else None)
```

- **POST branch.** It goes before the closing comment at 535:

```python
        if url.path == "/api/translate":
            if not self._rate_limit_check(url.path):
                respond_json(self, 429, {"error": "Rate limit exceeded"})
                return
            self._handle_translate_post()
            return
```

```python
    def _handle_translate_post(self) -> None:
        """Ask the Engine's /internal/translate/enqueue to queue a whisper job for one video, for the presented profile only; the body is read after the profile check."""
        if self._require_profile() is None:
            return
        try:
            body = read_json_body(self)
        except ValueError as exc:
            respond_json(self, 400, {"error": str(exc)})
            return
        video_id = body.get("id")
        host = body.get("host")
        for value in (video_id, host):
            if not isinstance(value, str) or not value.strip() or len(value) > BLOCK_REFERENCE_MAX_LENGTH:
                respond_json(self, 400, {"error": "id and host must be non-empty strings"})
                return
        try:
            payload = request_translate(self.server.engine_ingest_base, video_id.strip(), host.strip())
        except EngineApiError as exc:
            self._respond_engine_failure("translate", exc)
            return
        respond_json(self, 200, payload)
```

**Rate limiting.** GET polls and the POST share the `ip:/api/translate` bucket of 90 per 60 s. The fastest poll is one per 2 s, which is 30 per minute per tab. Three tabs behind one address can hit 429, and the page treats 429 as retryable (below). This is accepted and noted in `client/README.md`.

### Frontend data: `src/data/translate.ts`

```ts
export type TranslateCue = { start: number; end: number; text: string };
export type TranslateState =
  | { state: "none" | "queued" | "already_english" | "failed"; available: boolean }
  | { state: "ready"; available: boolean; cues: TranslateCue[] }
  | { state: "running"; available: boolean; cues: TranslateCue[]; total: number };
// The request route's answer: never cues; busy means the queue was full and nothing was stored.
export type TranslateRequestState = { state: TranslateState["state"] | "busy"; available: boolean };
```

- **`fetchTranslate`.** Its signature becomes `fetchTranslate(apiBase, id, host, after?: number)`. It calls `url.searchParams.set("after", String(after))` only when `after !== undefined`; the rest of the body is unchanged.
- **`parseTranslateState`.**
  - It throws "Translate response was malformed" unless `typeof body.available === "boolean"` and the state is one of the six.
  - For `ready`/`running` it maps cues with today's per-cue check. `ready` cues are sorted as today. `running` cues are kept in stored order, because the page counts them for `after` and sorts its merged list itself.
  - For `running` it requires `Number.isInteger(body.total) && body.total >= 0`.
- **`requestTranslate(apiBase, id, host): Promise<TranslateRequestState>`.**
  - It POSTs `JSON.stringify({ id, host })` with `{ "content-type": "application/json", ...profileHeaders() }` and `cache: "no-store"`.
  - A 401 throws `ProfileKeyRejectedError`, and other failures follow the same text/JSON/`!ok` handling as `fetchTranslate`.
  - `parseRequestState` checks the state against the seven names and checks that `available` is a boolean.

### Video page: `src/pages/video-page/translate.ts`

**New constants and state.**

```ts
const WAITING = "Waiting for translation…";
const TRANSLATING = "Translating…";
const STATE_LABELS: Record<string, string> = {
  none: NO_TRANSLATION,
  already_english: "This video is already in English.",
  failed: "Translation failed for this video.",
  busy: "The translation queue is full. Turn Translate off and on to try again."
};
// The state poll backs off while nothing changes and resets on any change, so a queued job waiting behind another stays cheap.
const STATE_POLL_FIRST_MS = 2000;
const STATE_POLL_MAX_MS = 16000;

let stateTimer: ReturnType<typeof setTimeout> | null = null;
let stateDelay = STATE_POLL_FIRST_MS;
let lastState = "";
// The running cues held, sent as after; 0 asks for all of them.
let runningHeld = 0;
```

**Flow.** The state poll is a chain: each tick schedules the next one only after its answer, so at most one request is in flight. A tick from an earlier ticket drops its answer and schedules nothing, which covers re-entry and off/on.

```ts
async function turnOn(apiBase: string, video: TranslateVideo) {
  on = true;
  setTranslate(true);
  renderToggle();
  setStatus("Loading translation…");
  resetStatePoll();
  const ticket = ++requestTicket;
  try {
    const state = await fetchTranslate(apiBase, video.id, video.host);
    if (ticket !== requestTicket) return;
    // Only a none from a serving worker asks for generation; none without it is plan 48's answer (AC1).
    if (state.state === "none" && state.available) {
      const requested = await requestTranslate(apiBase, video.id, video.host);
      if (ticket !== requestTicket) return;
      applyRequest(requested, apiBase, video, ticket);
      return;
    }
    applyState(state, apiBase, video, ticket);
  } catch (error) {
    if (ticket !== requestTicket) return;
    setStatus(error instanceof Error ? error.message : "Could not load the translation");
  }
}

function applyRequest(requested: TranslateRequestState, apiBase: string, video: TranslateVideo, ticket: number) {
  if (requested.state === "busy") {
    setStatus(STATE_LABELS.busy);
    return;
  }
  if (requested.state === "queued" || requested.state === "running" || requested.state === "ready") {
    // An existing running or ready job carries no cues here, so the state route is read at once.
    setStatus(requested.state === "queued" ? WAITING : "Loading translation…");
    scheduleStatePoll(apiBase, video, ticket, requested.state === "queued" ? STATE_POLL_FIRST_MS : 0);
    return;
  }
  applyState({ state: requested.state, available: requested.available }, apiBase, video, ticket);
}

function applyState(state: TranslateState, apiBase: string, video: TranslateVideo, ticket: number) {
  let changed = state.state !== lastState;
  lastState = state.state;
  if (state.state === "ready") {
    runningHeld = 0;
    cues = state.cues;
    setStatus("");
    startPolling();
    return;
  }
  if (state.state === "running") {
    if (state.total < runningHeld) {
      // The job was requeued and restarted: drop what is held and ask from 0.
      dropRunning();
      changed = true;
    } else if (state.cues.length) {
      cues = (runningHeld ? cues.concat(state.cues) : state.cues.slice()).sort((a, b) => a.start - b.start || a.end - b.end);
      runningHeld += state.cues.length;
      changed = true;
    }
    setStatus(TRANSLATING);
    startPolling();
  } else if (state.state === "queued") {
    if (runningHeld) dropRunning();
    setStatus(WAITING);
  } else {
    // none, already_english and failed end the poll; failed drops partial lines, as a reload would.
    runningHeld = 0;
    cues = [];
    stopPolling();
    showText("");
    setStatus(STATE_LABELS[state.state]);
    return;
  }
  if (!state.available) return;
  stateDelay = changed ? STATE_POLL_FIRST_MS : Math.min(stateDelay * 2, STATE_POLL_MAX_MS);
  scheduleStatePoll(apiBase, video, ticket, stateDelay);
}

function scheduleStatePoll(apiBase: string, video: TranslateVideo, ticket: number, delay: number) {
  clearStateTimer();
  stateTimer = setTimeout(() => {
    stateTimer = null;
    fetchTranslate(apiBase, video.id, video.host, runningHeld).then(
      (state) => { if (ticket === requestTicket) applyState(state, apiBase, video, ticket); },
      (error) => {
        if (ticket !== requestTicket) return;
        if (error instanceof ProfileKeyRejectedError) {
          setStatus(error.message);
          return;
        }
        // Network errors, 502s during a blue/green switch, 429 and a malformed answer keep the label and retry; fetchTranslate does not expose the status.
        stateDelay = Math.min(stateDelay * 2, STATE_POLL_MAX_MS);
        scheduleStatePoll(apiBase, video, ticket, stateDelay);
      }
    );
  }, delay);
}

function dropRunning() {
  runningHeld = 0;
  cues = [];
  showText("");
}

function clearStateTimer() {
  if (stateTimer !== null) clearTimeout(stateTimer);
  stateTimer = null;
}

function resetStatePoll() {
  clearStateTimer();
  stateDelay = STATE_POLL_FIRST_MS;
  lastState = "";
  runningHeld = 0;
  cues = [];
}
```

**`turnOff`.** It adds `resetStatePoll()` alongside the existing `requestTicket += 1` and `stopPolling()`. The ticket drops an answer already in flight, and the cleared timer stops a scheduled tick.

**Import.** It adds `ProfileKeyRejectedError` (from `../../data/profile`), `requestTranslate`, and the `TranslateState`/`TranslateRequestState` types.

**Behaviour this gives:**
- **Without `available`.** A `queued`/`running` answer with `available` false shows its label, and its cues for `running`, but starts no state poll (AC1 "never polls").
- **Sorting.** A sort of the whole list per running answer is a deliberate simplification, cheap at a few thousand cues every few seconds or more. The upgrade path is a merge of the sorted new slice.
- **Coverage.** `findCue`, `showAt` and `startPolling` are unchanged, so running cues show exactly as ready ones, and a position past the last stored cue shows nothing.
- **Leaving the page.** The video page has no in-page navigation, so a change of video is a full page load, which ends every timer (R1).

### Accepted limitations (from the plan, plus the ones this draft adds)

- A crash-restarted job that passes the held count between two polls without being seen `queued` appends cues from its second run onto the first. This lasts until `ready`, which replaces the list. A real fix needs a run marker in the answer.
- If the worker dies mid-job, the page stops polling once a poll answers `available` false, and keeps the last label until the viewer toggles or reloads.
- `busy` asks the viewer to toggle again. `failed` is final.
- The page retries every non-401 error at up to 16 s, including a persistent 400 or a malformed answer. That costs one request per 16 s per tab, and it is the price of not classifying errors.
- The enqueue route has no duration check (see above).
- An instance-fetch takeover of a job queued during an in-flight fetch is still possible (benign; the worker's `JobTakenOver` guard stays).

### Tests: what changes

- **`tests/active/test_subtitles.py`.** Cases for `fetch_subtitle_state` (no row, each state, raw text returned unparsed) and `fetch_translate_heartbeat` (no row, then a written beat).
- **`tests/active/test_internal_translate.py`.**
  - `NONE`/`READY` gain `"available": False`.
  - A `_enqueue` helper mirrors `_handle` for `module.handle_internal_translate_enqueue`.
  - Heartbeats are written with `write_translate_heartbeat(conn, now_ms() ± d, 1)`.
  - Every case listed under "What the build must test" for the Engine.
  - The startup test gains the `/internal/translate/enqueue` pair: 401 without the token, 404 with it.
  - The `_server` stand-in is unchanged, because the new code reads only `subtitles_db`/`subtitles_db_lock`/`db`/`db_lock`.
  - Docstring lines 1, 31 and 33.
- **`tests/active/test_server.py`.**
  - `TRANSLATE_NONE`/`TRANSLATE_READY` gain `available`.
  - "unknown state" becomes `"bogus"`.
  - "engine none" `(200, {"state": "none"})` now expects 200 `{"state": "none", "available": False}`.
  - `_TranslateEngine` gains a per-path reply dict.
  - New cases cover the GET `after` checks and the POST order, body checks and mapping.
  - Docstring lines 132-137.
- **`tests/active/test_frontend_translate.py`.**
  - `READY`/`NONE` gain `available: false`.
  - The fetch stub records `init.method` and `init.body` and serves a queue of answers per `METHOD path`, repeating the last one.
  - `_translate_requests` splits GET from POST.
  - New cases for the page behaviour listed above.
  - The backoff-cap case is the only one that raises the 60 s subprocess timeout.
- **`tests/config.json`.** Add both `translate.ts` paths to the `test_frontend_dist.py` group, so a stale `dist/` is caught on a selective run. Add `engine/server/data/time.py` and `engine/server/db/jobs/translate-worker.py` to the `test_internal_translate.py` group, for the heartbeat coupling.
- **`dist/`.** Rebuild with `vite build` and commit the new `video-*.js` and `video-page.html`.

### Documentation edits (the settled list, with the decisions above filled in)

- **`engine/server/README.md`.** The `/internal/translate` bullet covers the six states, `available`, `after` (a JSON int ≥ 0, else 400, checked after resolve) and `running` with `total`. Rows in `queued`/`running` are answered with no fetch, and `failed`/`already_english` still fetch. A new enqueue bullet covers the 15 s heartbeat gate, where a closed store or a read error means unavailable, plus queued/exists/busy, and 503 only on an enqueue store error. Lines 25, 30 and 31 are updated.
- **`CONTEXT.md`.** "Translate state" and "Translate job" as listed.
- **`client/README.md`.** The GET `after` rule and the states. A missing Engine `available` reads false. A new POST bullet covers the order 429 → 401 → 400, the shared bucket and the 6 s call. Lines 39, 45 and 51.
- **`client/frontend/README.md`.** Line 21: the request, the 2 → 16 s chain with its reset and stop set, the retry on every non-401 error, the merge and reset, the labels, `failed` clearing, `busy` needing off then on, and unavailable behaving as in plan 48. Line 8.
- **`TRANSLATE_WORKER.md`.** Line 148 is rewritten. Lines 7, 10, 33 and 34 change. Lines 49 and 100-104 say the page route checks the cap, the whitelist and the denylist through resolve, but not duration. Line 152 names the 15 s threshold.
- **`README.md`.** Lines 27, 53 and 54.
- **`DEPLOYMENT.md`.** Lines 98, 230, 283 (no duration check on the page route), 293-295, 302, 346, 348, 586 and 751. An upgrade note: Engine first, then the Client promptly. A new Client tolerates an old Engine, but an old Client turns job states into 502s.
- **`DATA_BUILD.md`.** Line 15.
- **Roadmap and plan 18.** The roadmap line 60 (and 24) and plan 18 line 8 at delivery, when plan 50 is archived.
- **Code docstrings.** The ones listed above in `internal_translate.py`, `similar.py`, `handlers/__init__.py`, `subtitles.py`, `translate-worker.py` and both `translate.ts` files.

### Check against the plan and requirements (pass 1 converged)

- **AC1.** The heartbeat helper with its age window `[0, 15000]`. A missing row, a closed store or an error reads as false. The page requests only on `none`+available and polls only while available.
- **AC2.**
  - The Client POST: profile first, then the body checks.
  - The Engine route reuses the moved resolve block verbatim, so its 400s, 404s and canonical key are the same as the state route's.
  - The mapping, with `available` on every answer.
  - 404 `Video not found` → `none` on the Client, and every other failure → 502.
- **AC3.**
  - The state-route order.
  - Both parsers widened and still strict.
  - The poll stop set: ready, already_english, failed, none, busy (never polled), off, 401, and leaving the page.
  - The five labels.
  - R2: every poll re-renders from the store's state, and `failed` clears the lines.
- **AC4.** `after` on all three tiers, with the 400 rules. The `running` slice and `total`, with empty or corrupt `cues_json` → `[]`/0. The page's merge and re-sort, the reset on a lower `total` or on `queued`, and `ready` replacing the list.
- **Consistency.** The frontend calls only `/api/translate`. The Engine never imports the worker. Labels and cue text use `textContent` only.
- **Where I depart from the plan's text, with reasons.**
  - Closed store → unavailable rather than 503 (AC1 wins).
  - A missing `available` → false at the Client (version skew).
  - `fetch_ready_subtitles` kept (it has test users).
  - `exists` → ready/running triggers an immediate state read instead of carrying cues.


### Phases

#### Phase 1 - Engine state route reports job state and availability [code]

**Files touched.** engine/server/data/subtitles.py (EDITED), engine/server/api/handlers/internal_translate.py (EDITED), engine/server/api/handlers/__init__.py (EDITED), engine/server/db/jobs/translate-worker.py (EDITED), tests/active/test_subtitles.py (EDITED), tests/active/test_internal_translate.py (EDITED), tests/config.json (EDITED)

**Checkpoint.** Seam: `handle_internal_translate` called directly (rung 1) through the existing `_handler_module` / `_server` / `_handle` harness in `tests/active/test_internal_translate.py`. That harness uses a real on-disk subtitles.db and a `RecordingInstance` instance stand-in. Heartbeats are written with `write_translate_heartbeat(conn, now_ms() ± d, 1)`. Assertions for C1: `available` is present on every 200 and is false for no heartbeat row, a stale beat (now-15_001), a future beat (now+1) and a closed store, and true for a fresh beat. This rules out a check with no age bound, a check without the future guard, and a flag dropped on some branches. Assertions for C2: a running row with `after` absent, 0, mid and past total answers `cues == stored[after:]` and `total == len(stored)`. Empty, unset or corrupt `cues_json` gives `[]` with total 0. The RecordingInstance logs no fetch for running. This rules out sending the whole list, a total counted from the slice, and a fetch done anyway. The same checkpoint also pins the AC3 order around these clauses: queued answers the state only with no fetch, ready answers cues, failed/already_english are answered with and without an instance track, a corrupt ready row with an instance miss answers none, `after` given as a bool/negative/string/null/float answers 400, and an unknown video with a bad `after` answers 404. `tests/active/test_subtitles.py` gains rung-1 cases for `fetch_subtitle_state` and `fetch_translate_heartbeat` (including no row on a fresh schema). The existing `test_translate_worker.py` stays green, which proves the worker's imports still load.

**Intent.** `/internal/translate` in `engine/server/api/handlers/internal_translate.py` answers a key's stored job state, reading it through the new `fetch_subtitle_state` and `fetch_translate_heartbeat` in `data/subtitles.py`, and it tells the caller whether a translate worker is currently serving.

- C1 - Every 200 answer of the state route carries `available`, which is true only when the translate worker's heartbeat is between 0 and 15 000 ms old.
- C2 - A running key is answered from the store with its cues from `after` onward and the stored `total`, without an instance fetch.

**Outcome.** ### `engine/server/data/subtitles.py`
- Added `fetch_subtitle_state(conn, video_id, instance_domain, target_language)`. It returns `(state, cues_json)` for the key with `cues_json` left unparsed, or None when the key has no row. It is one SELECT on the existing `_KEY` fragment.
- Added `fetch_translate_heartbeat(conn)`. It returns `beat_at` from `translate_worker_heartbeat WHERE id = 1`, or None when there is no beat yet. Both readers are pure: no transaction and no write.
- `fetch_ready_subtitles` is kept, because `test_subtitles.py` still uses it.
- Docstrings: the module docstring now says the state route reads a running row's cues so far through `fetch_subtitle_state`. `finish_translate_failed` now says partial cues are unread "because a failed row's cues are never served". The old wording, "only ready rows are served", is no longer true.

### `engine/server/api/handlers/internal_translate.py`
- Imports `fetch_subtitle_state` and `fetch_translate_heartbeat` in place of `fetch_ready_subtitles`.
- New `HEARTBEAT_FRESH_MS = 15_000`, with a `rat-tail:` comment: it is three of the worker's 5 s beats, and must be raised together with the beat.
- `_cached_cues` is replaced by three helpers:
  - `_generation_available(conn)`: true only for a beat aged 0 to 15 000 ms by the module's `now_ms`. No beat, a `sqlite3.Error` or a beat dated in the future gives false.
  - `_read_key(server, ...)`: reads the key's row and availability under one `subtitles_db_lock` hold. A closed store or a store error reads as no row and not available, so the instance still answers.
  - `_stored_cues(cues_json)`: the JSON loaded as a list, or None when it is unset, does not load, or is not a list.
- `handle_internal_translate`: validation, resolve and the denylist check are unchanged and in the same order.
  - After them it reads `after` from the body. It must be a JSON int, not a bool, and 0 or more, or the route answers 400 `Invalid after`. Because this check comes after resolve, an unknown video with a bad `after` still answers 404.
  - Order of answers:
    - a ready row with cues that load gives `ready` with the stored cues;
    - `queued` gives the state only;
    - `running` gives `cues[after:]` in stored order, plus `total` (the stored count). Unset, empty or damaged cues give `[]` and 0;
    - anything else goes to the instance fetch, unchanged and outside the lock. If the fetch finds a track, it is stored and the route answers `ready`. Otherwise it answers `failed` or `already_english` when that is the stored state, and `none` in every other case, including a ready row whose cues do not load.
  - Every 200 carries `available`.
- The extraction of a shared resolve helper is left for phase 2's enqueue route, which is its second user.
- The module docstring is rewritten for the six states, `after`/`total`, `available`, the no-fetch rows, and the narrower "this route stores only ready".

### `engine/server/api/handlers/__init__.py`
- The `internal_translate` line now describes the translate state, worker availability, and cues from a stored job or the instance.

### `engine/server/db/jobs/translate-worker.py`
- Comment only: a `rat-tail:` line above `HEARTBEAT_SECONDS` names its coupling to the Engine's `HEARTBEAT_FRESH_MS`, three beats with no shared constant. No code change, and the seven names the worker imports from the handler are untouched.

### `tests/active/test_internal_translate.py`
- The operator chose this when asked, and the approved plan says the same. The `NONE`/`READY` constants gain `"available": False`, with a one-line comment: the test store has the heartbeat table and no beat. The docstring line stating the exact none answer is updated to match.
- Without this, the gate, denylist, store-and-serve and none-path tests (4 tests, 8 cases) go red. The comparisons stay exact, and no assertion was loosened.

### `tests/active/test_subtitles.py`, `tests/config.json`
- Not touched. Nothing in them breaks: `fetch_ready_subtitles` is kept. The reader cases and the group-mapping additions belong with the checkpoint's promotion, as in plan 49's build.

### Not observed
- I ran nothing; the workflow's checkpoint run is the one that counts. The checkpoint's expected values were traced against this code by reading it. One example: `"null"` reaches `body.get("after", 0)` as None and is refused as not an int. Another: `"not a list"` loads as a dict, so `_stored_cues` gives None and the route answers `[]`/0.

#### Phase 2 - Engine enqueue route [code]

**Files touched.** engine/server/api/handlers/internal_translate.py (EDITED), engine/server/api/handlers/similar.py (EDITED), tests/active/test_internal_translate.py (EDITED)

**Checkpoint.** Seam: `handle_internal_translate_enqueue` called directly (rung 1) through a new `_enqueue` helper that mirrors the existing `_handle` in `tests/active/test_internal_translate.py`, against the same real subtitles.db. Assertions for C1: with no heartbeat, a stale heartbeat or a closed store, the answer is `{"state":"none","available":false}` and a SELECT on `subtitles` finds no row for the key. This rules out an enqueue that is not gated and a gate that answers correctly but still writes. Assertions for C2: with a fresh heartbeat, an empty key answers queued/true and leaves a queued row. A pre-existing row in each state answers that state and the row is unchanged. A queue at `SUBTITLE_QUEUE_CAP` answers busy/true. This rules out overwriting existing rows and leaking the raw `cap`. Also covered here: a monkeypatched `enqueue_translate_job` raising `sqlite3.Error` answers 503, and the 400/404/denylist answers are the same as the state route's. The bridge gate is checked through the existing real-Engine startup subprocess test in the same file, extended with `/internal/translate/enqueue`: 401 without the bridge token, 404 for an unknown video with it.

**Intent.** A bridge-gated `POST /internal/translate/enqueue`, dispatched in `similar.py` to `handle_internal_translate_enqueue`, queues a whisper job for a resolved video only while a translate worker is serving.

- C1 - When generation is unavailable, the enqueue route answers `none` with `available` false and writes no row.
- C2 - When generation is available, the enqueue route answers queued for a new key, the existing state for a stored key, and busy at the queue cap.

**Outcome.** ### `engine/server/api/handlers/internal_translate.py`
- Body validation, video resolve, the canonical key and the denylist check are moved unchanged out of `handle_internal_translate` into a new `_resolve_translate_key(handler, server)`. It returns `(body, canonical video_id, instance_domain, video key)`, or `None` once it has answered 400/404. Both routes call it, so the enqueue route gives exactly the same 400/404 answers as the state route. `handle_internal_translate` now unpacks that tuple and passes `video_key` (the old `row["video_uuid"] or canonical_id`) to `fetch_instance_track`. Its behaviour is otherwise unchanged.
- New `handle_internal_translate_enqueue(handler, server)`:
  - It resolves the key, then takes `subtitles_db_lock` once. Inside that hold it calls `enqueue_translate_job(conn, canonical_id, instance, "en", SUBTITLE_QUEUE_CAP, now_ms())`, but only when the store is open and `_generation_available(conn)` is true. Because it is one hold, availability cannot change between the beat read and the insert.
  - When generation is not available (a closed store included), it answers 200 `{"state": "none", "available": false}` and writes nothing.
  - Otherwise it maps the store's result: `queued` → `queued`, `exists` → the stored state, `cap` → `busy`, each with `available: true`.
  - A `sqlite3.Error` from the enqueue is logged and answers 503 `{"error": "Translate store unavailable"}`. The store's `_immediate` rolls back, so no row is left.
- New imports: `enqueue_translate_job` from `data.subtitles` and `SUBTITLE_QUEUE_CAP` from `server_config`. The worker already imports `server_config`, so it gains no new import-time dependency.
- The module docstring gains a paragraph describing the enqueue route.

### `engine/server/api/handlers/similar.py`
- The import line now also brings in `handle_internal_translate_enqueue`.
- `_dispatch_post` has a new exact-path branch for `/internal/translate/enqueue`, placed right after `/internal/translate`. It sits below the existing `/internal/` bridge-token check, so the gate needed no new auth code.
- The module docstring's route list gains the new route.

### `tests/active/test_internal_translate.py`
- No change was needed. The checkpoint brings its own `_enqueue` helper and imports only names this file already exports (`_post`, `VARIANT_RUNNER`, `_set_denied`, `DENIED_VIDEO`, and the rest).

#### Phase 3 - Client translate GET and POST [code]

**Files touched.** client/backend/lib/engine_api_client.py (EDITED), client/backend/server.py (EDITED), tests/active/test_server.py (EDITED)

**Checkpoint.** Seam: the real Client backend over HTTP via the existing `_keyed_client_backend` + `_TranslateEngine` stub + `_translate_get` harness in `tests/active/test_server.py`. The stub gains a per-path reply dict, and a `_translate_post` helper sits beside `_translate_get`. Assertions for C1: `after=3` reaches the Engine body as int 3. `after` absent and `after=` leave no `after` key. `after=١`, `-1` and `x` answer 400 with no Engine request recorded. Each of the six states with `available` passes through unchanged. A missing `available` reads false. A non-bool `available`, a bad `total` or the state `bogus` answer 502. A 404 `Video not found` answers none/false. Assertions for C2: these refusals are checked in order with an empty Engine log for each: rate-limited answers 429 before the profile check, no profile answers 401 before the body is read, and `{}`, a non-str value, a blank value, 201 characters and invalid JSON each answer 400. Enqueue answers queued/running/busy/none map through to the page. Engine 503 answers 502, and an old Engine's 404 `Not found` answers 502. The recorded request goes to `/internal/translate/enqueue` with the bridge token.

**Intent.** The Client's `/api/translate` in `server.py` and `engine_api_client.py` carries the Engine's job states to the page on GET and requests generation for a profile on POST.

- C1 - GET `/api/translate` forwards an ASCII-digit `after` to the Engine as an int and passes through the six states with `available`.
- C2 - POST `/api/translate` refuses 429, then 401, then 400 without calling the Engine, and otherwise returns the mapped enqueue answer.

**Outcome.** ### client/backend/lib/engine_api_client.py
- Added `TRANSLATE_STATES` (`none`, `queued`, `running`, `ready`, `already_english`, `failed`) and `TRANSLATE_REQUEST_STATES`, which is those six plus `busy`, the enqueue route's full-queue answer.
- Added `_translate_available`. A missing `available` reads as `False`, so an Engine from before plan 50 keeps plan 48's behaviour. Any value that is not a bool raises `EngineApiError`.
- Added `_checked_cues`. It is the old cue loop pulled out of `fetch_translate`: it raises on a non-list and copies only start, end and text, keeping the Engine's order.
- `fetch_translate` takes an optional `after` and puts it in the body only when given. It accepts the six states, each with `available`. `ready` and `running` require valid cues. `running` requires an int `total` of 0 or more, not a bool. 404 `Video not found` now maps to `{"state": "none", "available": False}`. Any other non-200 answer, an unknown state, or a malformed field raises.
- New `request_translate` posts `{id, host}` to `/internal/translate/enqueue` with the default 6 s timeout. It maps 404 `Video not found` the same way and accepts the six states or `busy` with `available`, without cues. Anything else raises, including 503 and an old Engine's 404 `Not found`.

### client/backend/server.py
- The import list gains `request_translate`.
- `PROXY_ALLOWED_QUERY_PARAMS["/api/translate"]` is now `{"id", "host", "after"}`, and the comment says `after` is read only on GET.
- `_handle_translate_get` requires `id` and `host` to be present instead of requiring exactly that key set. It accepts `after` only when the value is `isascii() and isdigit()`; otherwise it answers 400 `after must be a non-negative integer`. A valid `after` goes to `fetch_translate` as an int. A blank `after` was already dropped by `_sanitize_query`, so it is treated as absent.
- `_serve_post` has a new `/api/translate` branch: the rate limit check (429) runs first, then `_handle_translate_post`.
- New `_handle_translate_post` checks the profile first (401). It then reads the body with `read_json_body`, which answers 400 for invalid JSON or a non-object. `id` and `host` must each be a str that is non-empty after stripping and at most `BLOCK_REFERENCE_MAX_LENGTH` long, or the answer is 400. It then calls `request_translate` with the stripped values. An `EngineApiError` becomes 502 `Engine translate failed` through `_respond_engine_failure`.

### tests/active/test_server.py
- Retired three `TRANSLATE_ENGINE_ANSWERS` cases that conflict with C1:
  - "video not found" expected `{"state": "none"}`, which now lacks `available: false`.
  - "engine none" also expected `{"state": "none"}`, but a missing `available` now reads as false.
  - "unknown state" used `queued`, which is now a valid state.
- With them went the now unused `TRANSLATE_NONE`. The checkpoint covers all three behaviours in their new form (none/false, the missing-flag default, `bogus` → 502).
- The valid Engine replies now carry `available: False`, the shape plan 50's Engine sends when no worker is running. These are `TRANSLATE_READY`, used by the rate-limit, 401 and 400-ordering tests, and the reply and expected answer in the ready-cue test.
- None of these assertions changed what they check. Each still checks that a well-formed Engine answer passes through unchanged and that extra cue fields are stripped. Without the flag, every one of them would have failed, because the Client adds `available: false`.
- Docstring lines 132-137 were updated to match. `_keyed_client_backend`, `_serving` and `_translate_get`, which the checkpoint imports, are unchanged.

I changed no files this turn. The phase 3 code went in on the earlier run of this step (the "checkpoint outcome (run 1)" entry in the record), and that run ended 1 failed, 46 passed. The operator then edited the checkpoint and approved the edit. I re-read `engine_api_client.py`, `server.py`, the `test_server.py` helpers the checkpoint imports, `read_json_body`, `RateLimiter` and `resolve_request_id`, and traced every case in the edited checkpoint against the code already in the tree. Every case comes out as the checkpoint expects, so a smaller or different change would not help. `tests/last_test_output.txt` holds the most recent run of the checkpoint, which reads "collected 47 items … 47 passed". I did not run it myself; the workflow's run on hand-in is the one that counts. What the phase changed, file by file:

### client/backend/lib/engine_api_client.py
- Added `TRANSLATE_STATES` (`none`, `queued`, `running`, `ready`, `already_english`, `failed`) and `TRANSLATE_REQUEST_STATES`, which is those six plus `busy`, the enqueue route's answer when the queue is full.
- Added `_translate_available`. A missing `available` reads as `False`, so an Engine from before plan 50 keeps plan 48's behaviour. Any value that is not a bool raises `EngineApiError`, so `"true"`, `1` and `null` all become 502.
- Added `_checked_cues`. It is the old cue loop moved out of `fetch_translate`. It raises on a non-list and copies only start, end and text, in the Engine's order, so running cues are never re-sorted.
- `fetch_translate` takes an optional `after` and puts it in the body only when it is not None, so `after` 0 is still sent. It accepts the six states, each with `available`. `ready` and `running` need valid cues. `running` needs an int `total` of 0 or more that is not a bool. 404 `Video not found` maps to `{"state": "none", "available": False}`. Any other non-200 answer, an unknown state or a malformed field raises.
- New `request_translate` posts `{id, host}` to `/internal/translate/enqueue` with the default 6 s timeout. It maps 404 `Video not found` the same way, and accepts the six states or `busy` with `available` and no cues. Anything else raises, including 503 and an old Engine's 404 `Not found`.

### client/backend/server.py
- The import list gains `request_translate`.
- `PROXY_ALLOWED_QUERY_PARAMS["/api/translate"]` is now `{"id", "host", "after"}`. Its comment says `after` is read only on GET.
- `_handle_translate_get` now requires `id` and `host` to be present, where before it required exactly that set of keys.
  - It accepts `after` only when `after.isascii() and after.isdigit()`. Otherwise it answers 400 `after must be a non-negative integer` before any Engine call. That covers the Arabic-Indic digit, `-1`, `x`, `+1` and `1.5`.
  - A valid `after` goes to `fetch_translate` as an int.
  - A blank or whitespace `after` is already dropped by `parse_qs` and `_sanitize_query`, so it counts as absent.
- `_serve_post` has a new `/api/translate` branch. The rate-limit check (429) runs first, then `_handle_translate_post`.
- New `_handle_translate_post`:
  - It checks the profile first (401), before the body is read.
  - It then reads the body with `read_json_body`, which answers 400 `Invalid JSON body` for invalid JSON or a body that is not a JSON object.
  - `id` and `host` must each be a str that is non-empty after stripping and at most `BLOCK_REFERENCE_MAX_LENGTH` (200) long; otherwise the answer is 400.
  - It then calls `request_translate` with the stripped values. An `EngineApiError` becomes 502 `Engine translate failed` through `_respond_engine_failure`.

### tests/active/test_server.py
- Retired three `TRANSLATE_ENGINE_ANSWERS` cases that conflict with C1:
  - "video not found" expected `{"state": "none"}`, which no longer carries `available: false`.
  - "engine none" also expected `{"state": "none"}`, but a missing `available` now reads as false.
  - "unknown state" used `queued`, which is now a valid state.
- `TRANSLATE_NONE` was no longer used and went with them. The checkpoint covers all three behaviours in their new form: none with `available` false, the missing-flag default, and `bogus` → 502.
- The valid Engine replies now carry `available: False`, the shape plan 50's Engine sends when no worker is running. These are `TRANSLATE_READY` (used by the rate-limit, 401 and 400-ordering tests) and the reply and expected answer in the ready-cue test. Each assertion still checks the same thing as before.
- Docstring lines 132-137 were updated to match. `_keyed_client_backend`, `_serving` and `_translate_get`, which the checkpoint imports, are unchanged.

#### Phase 4 - Video page requests and follows generation [code]

**Files touched.** client/frontend/src/data/translate.ts (EDITED), client/frontend/src/pages/video-page/translate.ts (EDITED), client/frontend/dist/** (EDITED), tests/active/test_frontend_translate.py (EDITED), tests/config.json (EDITED)

**Checkpoint.** Seam: the bundled video page run in node through the existing esbuild + `runner.mjs` + `_page` harness in `tests/active/test_frontend_translate.py`. The fetch stub records `init.method` and `init.body` and serves a queue of answers per `METHOD path`, repeating the last one. `_translate_requests` splits GET from POST. Assertions for C1: none/true leads to exactly one POST with body `{id, host}` and the profile header. none/false leads to zero POSTs, no further GETs after the first, and the plan 48 status text. This rules out repeated requests, requesting while unavailable, and polling while unavailable. Assertions for C2: in a queued → running(2 cues) → running(+1, total 3) → ready run, each GET carries `after` equal to the held count (0, 2, 3), the overlay shows a running cue at its position, and ready replaces the list. A running answer with a lower `total` makes the next GET ask `after=0`. failed clears the overlay text and stops the GETs. busy shows its label and sends no GET. Turning Translate off stops the GETs, and so does a 401. A 502 keeps the label and a later GET is still made. The status labels are read from textContent snapshots. The rebuilt `dist/` is checked by the existing `test_frontend_dist.py`, now mapped to both translate.ts paths in tests/config.json.

**Intent.** With Translate on, the video page in `pages/video-page/translate.ts` (using `data/translate.ts`) requests generation once for a video a serving worker has no track for, and follows the job with a backoff state poll until it ends.

- C1 - The page sends exactly one generation request when the state is `none` with `available` true, and none when `available` is false.
- C2 - The state poll appends running cues by sending its held count as `after`, and stops on ready, failed, busy, none, off or 401 while retrying on a 502.

**Outcome.** I haven't run the checkpoint; the workflow's run at hand-in is the one that counts. Two probe results: esbuild bundles the edited page, and `tsc --noEmit` reports no errors in either translate module. tsc does report errors, but they are all in three other files: `pages/channels/index.ts`, `pages/video-page/index.ts` and `pages/videos/index.ts`. I also traced every checkpoint scenario through the code by hand.

### client/frontend/src/data/translate.ts
- **`TranslateState`** now covers the six states, each carrying `available`. `ready` and `running` carry `cues`, and `running` also carries `total`. A new `TranslateRequestState` type is `{state: one of those six or "busy", available}`, with no cues.
- **`fetchTranslate(apiBase, id, host, after?)`** adds `after` to the query only when one is given, so a plain read still sends exactly `id`/`host`.
- **New `requestTranslate(apiBase, id, host)`** sends a POST to `/api/translate` with body `JSON.stringify({id, host})` and headers `{"content-type": "application/json", ...profileHeaders()}`, the same pattern as `postProfile`. It accepts any of the seven state names plus `available`, and throws on anything else.
- **New `readTranslateResponse`.** Both calls now share the response handling `fetchTranslate` already had: a 401 throws `ProfileKeyRejectedError`, then the body is parsed, then a non-OK status throws the server's error text.
- **`parseTranslateState`** checks each state:
  - `ready` cues are sorted, as before.
  - `running` cues are left in stored order, because the page counts them for `after`. `running` also needs an integer `total` of 0 or more.
  - Anything else still throws "Translate response was malformed" (now the `MALFORMED` constant). The per-cue check moved into `parseCues` unchanged.
- **New exported `compareCues`** (by start, then end). The parser and the page share it.
- **One departure from the plan's text, in `parseAvailable`:** a missing `available` reads as `false`, and only a value that is present but not a boolean is malformed. The plan said `typeof === "boolean"`, which would also reject a missing flag. This matches the version-skew choice phase 3 made for the Client's `_translate_available`: a page served before the Client restarts falls back to plan 48's behaviour instead of showing "malformed" on every video. It also means plan 48's `READY`/`NONE` fixtures in `tests/active/test_frontend_translate.py`, which have no `available`, still exercise the plan 48 path unchanged.
- The module docstring now mentions the generation request.

### client/frontend/src/pages/video-page/translate.ts
- **`turnOn`** reads the state.
  - On `none` with `available` true, it calls `requestTranslate` once and hands the answer to `applyRequest`.
  - Everything else goes to `applyState`.
  - It now starts with `resetStatePoll()`, so a turn-on clears any earlier poll chain.
- **`applyRequest`:**
  - `busy` shows "The translation queue is full. Turn Translate off and on to try again." and is not polled.
  - An existing `ready` or `running` job comes back without its cues, so the state route is read at once (delay 0).
  - Any other answer goes through `applyState`.
- **`applyState`:**
  - `ready` replaces the cue list with the final cues, clears the label and starts the position poll.
  - `running` drops the held list when `total` is below the held count, so the next poll asks from 0. Otherwise it appends the new cues, re-sorts with `compareCues` (marked `rat-tail:`, with merging the sorted new slice as the upgrade), adds to `runningHeld`, shows "Translating…" and starts the position poll.
  - `queued` drops any running cues held and shows "Waiting for translation…".
  - `none`, `already_english` and `failed` empty the list, stop the position poll, clear the overlay and show their label (`ENDED_LABELS`). Plan 48's none message is unchanged.
  - A queued or running answer without `available` is shown but not polled. Otherwise the next poll waits 2 s after a change, and doubles up to 16 s while nothing changes.
- **`scheduleStatePoll`** is a `setTimeout` chain with its own handle (`stateTimer`), separate from the position `pollTimer`.
  - Each poll sends `runningHeld` as `after`, and only its answer schedules the next one.
  - An answer from an earlier `requestTicket` is dropped.
  - `ProfileKeyRejectedError` shows its message and ends the chain.
  - Any other error (a 502, a network error, a 429, a malformed answer) keeps the label and retries at the next backoff step.
- **`turnOff`** calls `resetStatePoll()` (clear the timer, reset the backoff, the last state, the held count and the cues) in place of `cues = []`.
- **New helpers:** `clearStateTimer`, `resetStatePoll`, `dropRunning`. New constants for the labels and the 2 s / 16 s bounds.
- The module docstring now covers the request and the state poll.

### client/frontend/dist/**
The operator ran `vite build` after the source edits; I have no build tool. I checked the output:
- The video chunk is now `assets/video-lFUUUMbq.js`, replacing `video-pSg73mMI.js`, and `dist/video-page.html` references it. The CSS name `video-KpoIp_n6.css` is unchanged.
- The chunk contains this phase's code, including the new labels, `requestTranslate` and the poll chain.
- `jschannel` is bundled inline, not left as a bare `import … from "jschannel"`, so plan 48's unresolved-dependency problem doesn't appear in this build.

### tests/config.json
Added `client/frontend/src/data/translate.ts` and `client/frontend/src/pages/video-page/translate.ts` to the `test_frontend_dist.py` group, so a selective run catches a stale `dist/` after either file changes.

### tests/active/test_frontend_translate.py
Not edited. Because a missing `available` reads as false, its fixtures keep driving the plan 48 paths: `ready` shows cues, `none` shows the message with no POST and no poll. Its counts of one `/api/translate` request still hold.

### tests/tmp/probe_phase4_compile.py
This was a throwaway compile probe (esbuild and tsc). I emptied it because I have no delete tool, so it can be deleted.


