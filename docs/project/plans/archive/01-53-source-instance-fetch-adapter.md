# 53-source-instance-fetch-adapter

_Rendered by the `dev-flow` workflow from its run state. Every edit here is overwritten on the next step; the evidence each gate turned on is in `docs/project/plans/01-53-source-instance-fetch-adapter.record.md`._

## Requirements

### Purpose

PeerTube instances, and the media hosts their JSON names, are untrusted. Every request to them is a **source-instance fetch** (term defined in `CONTEXT.md`). The rule for such a fetch: https only, no explicit port, no userinfo, redirects followed only to https on the same host, a byte cap, a time bound, and a failure that says why. Today only `/internal/translate` implements the full rule. The translate worker copies part of it and imports the rest from a route handler, and `/api/video` and the trending job leave it out entirely: they use bare `urlopen`, with no cap and with redirects followed to any host or scheme. This build puts the rule in one adapter module and moves four callers onto it. Two things follow: unsafe fetches stop, and every failure carries a reason, so translate jobs record why a fetch failed and do not just fail generically.

### Baseline suite state

Pre-build baseline: the suite exits 0 (`code: 0`, `variant: false`). Test trees: active `tests/active`, working `tests/tmp`, archive `tests/archive`; record `tests/last_test_validation.json`, output `tests/last_test_output.txt`; plans in `docs/project/plans`. Project dir `/home/enduser/code/PeerTube-browser/.worktrees/53`.

### Current code (verified in the tree)

- `engine/server/api/handlers/internal_translate.py`: `same_host_https(url, host)` (:48), `SameHostRedirectHandler(host)` (:58, logs `[translate] refused redirect …` and returns None so urllib raises the 3xx as `HTTPError`), `fetch_bounded(host, path, budget_at) -> bytes | None` (:74). Constants `FETCH_MAX_BYTES = 2_000_000`, `FETCH_DEADLINE_SECONDS = 8.0`, `REQUEST_BUDGET_SECONDS = 15.0`, `SOCKET_TIMEOUT_SECONDS = 4.0`, `READ_CHUNK_BYTES = 65_536`. `fetch_bounded` sets deadline = min(now + 8 s, budget_at) and returns None if that has already passed. It sends header `accept: application/json, text/vtt`, opens with `build_opener(SameHostRedirectHandler(host)).open(request, timeout=min(SOCKET_TIMEOUT_SECONDS, remaining))`, returns None on non-200, on a Content-Length over the cap, on the deadline passing between chunks, or on the streamed size going over the cap, reads with `read1(READ_CHUNK_BYTES)`, and catches `(OSError, ValueError, http.client.HTTPException)`. `fetch_instance_track` (:187) uses it twice under one 15 s budget, for the caption list and then the en track.
- `engine/server/db/jobs/translate-worker.py`: puts `engine/server` and `engine/server/api` on `sys.path` (:34-40) and imports `FETCH_DEADLINE_SECONDS, READ_CHUNK_BYTES, SOURCE_INSTANCE, TARGET_LANGUAGE, SameHostRedirectHandler, fetch_bounded, fetch_instance_track` from `handlers.internal_translate` (:48), `fetch_video_row` from `handlers.video` (:49), and `server_config` (which lives in `engine/server/api`). It imports `build_opener, Request` from urllib (:32). `MEDIA_SOCKET_TIMEOUT_SECONDS = 15.0` (:76) and `_TLD` regex (:81). `media_host(url)` (:158) returns the raw `urlsplit` hostname when the URL is https, has no port or userinfo, passes `normalize_host`, has ≥2 labels and its last label matches `_TLD`, and returns None otherwise. `AudioPipe._feed` (:231) opens through `build_opener(SameHostRedirectHandler(self.host))` with `timeout=MEDIA_SOCKET_TIMEOUT_SECONDS`, then: non-200 → `media download failed: HTTP {status}`, Content-Length over max_bytes → `media over {max_bytes} bytes`, `read1(READ_CHUNK_BYTES)` loop until `stop` is set, streamed size over → `media over {max_bytes} bytes`, chunks written to ffmpeg stdin, `BrokenPipeError` ignored, `(OSError, ValueError, http.client.HTTPException)` → `media download failed: {exc}`, stdin closed in `finally`. The video-JSON fetch (:448) is `fetch_bounded(instance, f"/api/v1/videos/{quote(video_key, safe='')}", time.monotonic() + FETCH_DEADLINE_SECONDS)`. When it returns None, or the JSON does not decode to a dict, the job raises `JobFailed("video JSON fetch failed")` (:455).
- `engine/server/api/handlers/video.py:82` `fetch_instance_json(host, path) -> dict | None`: bare `urlopen(Request(url, headers={"accept": "application/json"}), timeout=8)`, `resp.read()`, catches `(HTTPError, URLError, TimeoutError)` and `ValueError`, logs `[video] …`, returns None on non-200, on a non-JSON body or on a non-object body.
- `engine/server/db/jobs/fetch-trending.py:73` `fetch_host_list(host, timeout_s, max_retries) -> list | None`: `Request(f"https://{host}{TRENDING_PATH}", headers={"User-Agent": "peertube-browser-trending/1.0"})`, bare `urlopen(request, timeout=timeout_s)`, `json.loads(response.read())`, `ValueError("body has no data list")` when `data` is not a list, catches `(OSError, ValueError)` and logs at DEBUG per attempt, makes `max_retries + 1` attempts with no backoff, and returns None after all fail. `TRENDING_PATH = "/api/v1/videos?sort=-trending&isLocal=true&count=100&nsfw=both"`. CLI default `--timeout-ms 5000`. The updater and the documented manual fill run `--timeout-ms 15000 --max-retries 3`. The job puts `engine/server` on `sys.path` at import, and `engine/server/api` in `main()` for `server_config`.
- Tests: `tests/active/test_translate_worker.py:507-508` patches `build_opener` on `handlers.internal_translate` (instance) and on the worker module (media). `test_internal_translate.py` has the `ScriptedInstance` host pattern (:238-269). `test_video.py` patches `urlopen` (and `fetch_instance_json`) on `handlers.video`, including in Engine-child subprocess cases. `test_fetch_trending.py` patches `urlopen` on the job module and records each attempt's URL and timeout.

### The adapter module

- One new module under the Engine server package (`engine/server/`, outside `api/handlers/`), importable both by the Engine (which already has `engine/server` on its import path, since it imports `data.*`) and by the jobs (which put `engine/server` on `sys.path`). No job may import it via a route handler. Stdlib only.
- It holds, as public names: the same-host https check (today's `same_host_https` semantics exactly), the media-URL check (today's `media_host` semantics exactly, including `normalize_host`, the ≥2-label rule, the `_TLD` last-label rule that refuses every IP literal and forms like `127.1`, `2130706433`, `0x7f.0x1`, and returning the raw `urlsplit` hostname, not the normalized one), `SameHostRedirectHandler`, the buffered fetch, the streamed fetch, and the bounds constants (2,000,000 bytes, 8 s deadline, 4 s socket timeout, 65,536-byte read chunk, 15 s media socket timeout). The redirect handler still refuses an off-host or non-https target by making urllib raise the 3xx.
- Network stubbing in tests needs exactly one patch point, in the adapter (for example the adapter's `build_opener` or one opener-factory name). Both forms open connections through that one point.

### Buffered form

- GET `https://<host><path>` with the same-host redirect policy, a byte cap, a per-fetch wall-clock deadline, an optional caller budget (a monotonic instant; the effective deadline is the earlier of the two), a socket timeout (capped by the time remaining, as today), and `read1` chunked reads with the deadline checked between chunks.
- Arguments: host and path, plus optional overrides: byte cap, deadline seconds, caller budget, socket timeout, and request headers. With no overrides it behaves exactly like today's `fetch_bounded`: the same bounds, the same `accept: application/json, text/vtt` header, the same success and failure cases.
- Result: the body bytes on success, or a short human-readable failure reason, never a bare `None`. Either a result type or a raised exception carrying the reason is acceptable. Choose one and use it consistently across every caller.
- Distinct reasons for each of: non-200 status (with the status), Content-Length over the cap, streamed body over the cap, deadline passed (including one already passed before the request), a refused redirect (off-host or off-https), and a network or TLS error (the exception text). The exception set caught stays `(OSError, ValueError, http.client.HTTPException)`.

### Streamed form

- Opens a media URL through the same-host redirect policy bound to the host `media_host` returned, and passes chunks to a consumer (for the worker, a write to ffmpeg's stdin).
- Keeps today's media behaviour exactly: socket timeout 15 s, the Content-Length precheck against the caller's byte cap, the streamed byte cap from the caller, `read1(65_536)` chunks, stopping when the caller's stop signal is set, **no wall-clock deadline**, the same exception set, and the failure texts `media download failed: HTTP {status}`, `media over {N} bytes`, `media download failed: {exc}`. A `BrokenPipeError` from the consumer (ffmpeg exited) is still not reported as a download failure, and the worker still closes ffmpeg's stdin on every path.

### Callers

- **Translate route** (`internal_translate.py`): uses the buffered form with the defaults, with the 15 s request budget passed as the caller budget across both fetches in `fetch_instance_track`. It holds no copy of the rule, constants or redirect handler, and does not call `urlopen` or `build_opener`. `fetch_instance_track`, `pick_english_track_path`, `parse_webvtt`, `SOURCE_INSTANCE`, `TARGET_LANGUAGE`, `REQUEST_BUDGET_SECONDS` and `HEARTBEAT_FRESH_MS` stay in the route (operator decision). `_track_path` uses the adapter's same-host check. Every response of `/internal/translate` and `/internal/translate/enqueue` (status codes and bodies) is unchanged in every case, including a denied host still answering 404 `{"error": "Video not found"}` before any fetch. A failed fetch is logged with its reason.
- **Translate worker**: uses the buffered form for the video JSON (defaults, one 8 s deadline) and the streamed form inside `AudioPipe` for media. It uses the adapter's `media_host` for `pick_media_url` and the `AudioPipe` host. It holds no `media_host`, `_TLD`, byte-cap loop, exception tuple, `build_opener` or `urlopen` of its own, and imports no fetch rule, fetch constant or redirect handler from a route handler. It keeps importing `fetch_instance_track`, `SOURCE_INSTANCE` and `TARGET_LANGUAGE` from `handlers.internal_translate` and `fetch_video_row` from `handlers.video` (operator decision). `api/` therefore stays on `sys.path`, for `server_config` and those imports, and is no longer needed for fetch code. A failed video-JSON fetch fails the job with text that includes the adapter's reason, as `video JSON fetch failed: <reason>` (e.g. `video JSON fetch failed: HTTP 404`). A body that does not decode to a JSON object still fails the job with a `video JSON fetch failed` text. The other job failure texts are unchanged.
- **`/api/video` `fetch_instance_json`**: uses the buffered form with the defaults (2 MB cap, 8 s deadline, 4 s socket timeout, same-host redirects). Its socket timeout drops from 8 s to 4 s; this is accepted. It keeps its `accept: application/json` header and its contract: a JSON object, or `None` on any failure (fetch failure, non-UTF-8, non-JSON, non-object), with the reason logged under `[video]`. A cross-host or non-https redirect, or a body over the cap, now fails the fetch, so `/api/video` and `/api/video/refresh` serve the stored row with 200, as they do for any failed fetch today, and the redirect target is never requested. Against an instance that answers normally, the merged metadata is the same as before.
- **Trending job** `fetch_host_list`: uses the buffered form, passing its own byte cap, `timeout_s` as **both** the socket timeout and the per-attempt wall-clock deadline (operator decision; this matches UPDATER_WORKER.md's "each attempt bounded by `--timeout-ms`" and its `(max_retries + 1) × timeout` cost), and `User-Agent: peertube-browser-trending/1.0`. It keeps the exact request URL, the retry loop (every failure retried, 4xx included, no backoff), the "body has no data list" check, per-attempt DEBUG logging with the reason, and the "`None` after all `max_retries + 1` attempts" contract. The cap is chosen by measuring a real trending page (`TRENDING_PATH` against at least one real, large PeerTube instance) and leaving clear headroom over it. The measured size and the chosen cap are recorded in a comment next to the constant. A cross-host redirect or a body over the cap fails that attempt, and a host that fails every attempt keeps its stored list. A normal trending page within the cap is stored as before.

### Out of scope

- `sync-whitelist.py`, `updater-worker.py`, `compare-join-hosts.py` (bare `urlopen`; untouched).
- A wall-clock deadline for media downloads. Changing the translate route's or the media download's cap or timeout values.
- The trending retry policy (no backoff, 4xx retried).
- Making `/api/video` DB-only.
- The rest of the translate worker split (issue 56) and the job handle (issue 54).
- Moving `fetch_instance_track` / `parse_webvtt` out of the route.
- Fixing incomplete certificate chains on media hosts.

### Acceptance criteria

1. One adapter module holds URL acceptance (both checks), the same-host redirect policy, the byte caps and bound constants, the deadlines and the failure reasons. The translate route, the translate worker, `handlers/video.py` and `fetch-trending.py` hold no copy of any of these, and none of them calls `urlopen` or `build_opener` directly.
2. The translate worker imports nothing fetch-rule-related from a route handler (no `fetch_bounded`, `SameHostRedirectHandler`, `FETCH_DEADLINE_SECONDS`, `READ_CHUNK_BYTES`). Its `api/` `sys.path` entry is no longer there for fetch code; it remains only for `server_config`, `handlers.video.fetch_video_row` and the route's `fetch_instance_track`/constants.
3. A buffered fetch fails with a distinct reason for each of: non-200 status, Content-Length over the cap, streamed body over the cap, deadline passed, a redirect off the host or off https, and a network or TLS error. With no overrides it behaves exactly like today's `fetch_bounded`.
4. A translate job whose video-JSON fetch fails is stored `failed` with error text that includes the adapter's reason.
5. `/internal/translate` and `/internal/translate/enqueue` responses (status codes and bodies) are unchanged in every case, including a denied host answering the same `Video not found` body.
6. Media download behaviour is unchanged: 15 s socket timeout, Content-Length precheck, streamed cap, no new deadline, same failure texts.
7. `/api/video`, when the instance answers the video-detail request with a redirect to another host, answers 200 with the stored row's metadata, and the redirect target is never requested. The same holds for a detail body over the cap.
8. `/api/video` against an instance that answers normally returns the same merged metadata as before.
9. The trending job fails a host's attempt when the instance redirects to another host or sends a body over the job's cap, and keeps that host's stored list. A normal trending page within the cap is stored as before. Each attempt is bounded by `timeout_s` as both socket timeout and deadline.
10. The existing translate route, translate worker, video and trending test cases pass. Their network stubbing patches the adapter in one place, and nothing patches `build_opener` in two module namespaces or `urlopen` on a caller module.
11. Docs: `engine/server/README.md`'s fetch-bounds section names the adapter as where the bounds live. `engine/server/db/jobs/docs/TRANSLATE_WORKER.md` names the adapter (replacing "B1's `fetch_bounded`") and documents `video JSON fetch failed: <reason>`. `engine/server/db/jobs/docs/UPDATER_WORKER.md`'s Trending Stage names the adapter, the job's cap and the per-attempt deadline. The `/api/video` notes say a refused redirect or an over-cap body falls back to the stored row. `CONTEXT.md`'s "Today only the translate route and the translate worker follow this rule" sentence is updated to reflect delivery.

## High-level plan

### Approach

Add one stdlib-only module, `engine/server/data/source_fetch.py`, named after the CONTEXT.md term. Both kinds of process can already import it. The Engine imports `data.*` today. Both jobs put `engine/server` on `sys.path` before their `data.*` imports. The module also needs `data.moderation.normalize_host` for the media check, and that sits in the same package. The module's public names are:

- **Bounds constants.** `FETCH_MAX_BYTES` 2_000_000, `FETCH_DEADLINE_SECONDS` 8.0, `SOCKET_TIMEOUT_SECONDS` 4.0, `READ_CHUNK_BYTES` 65_536, `MEDIA_SOCKET_TIMEOUT_SECONDS` 15.0, plus the private `_TLD` regex.
- **`same_host_https(url, host)`.** Moved from the route word for word.
- **`media_host(url)`.** Moved from the worker word for word. It still returns the raw `urlsplit` hostname.
- **`SameHostRedirectHandler(host)`.** Moved from the route. It still returns None so that urllib raises the 3xx as an `HTTPError`. It also stores the refused target on the instance (`self.refused`), so the caller can tell a refused redirect apart from an ordinary HTTP error. Its log line changes from `[translate] refused redirect` to a neutral `[source-fetch] refused redirect`, because the module now has four callers. No test asserts that text.
- **`SourceFetchFailed(Exception)`.** Its message is the short reason.
- **`fetch_bounded(host, path, *, max_bytes=…, deadline_seconds=…, budget_at=None, socket_timeout=…, headers=None) -> bytes`.** This is the buffered form.
- **`stream_media(url, host, max_bytes, consume, stop) -> None`.** This is the streamed form.

The module calls `build_opener` through its own module global in exactly one place, a small private `_open(request, host, timeout)`. Both forms open connections through it, so `source_fetch.build_opener` is the single patch point for tests.

**Failure signalling: an exception, used by every caller.** Both forms return their success value (bytes, or nothing) and raise `SourceFetchFailed(reason)` on any failure. An exception fits the callers that need the reason. The trending loop already catches a tuple and logs `exc`. The worker turns a failure into `JobFailed`. The two callers that want `None` (the route's `fetch_instance_track` and `/api/video`'s `fetch_instance_json`) each add one `try/except SourceFetchFailed`, log the reason and return None.

**Buffered form.**

- It reads `now = time.monotonic()` once. The deadline is `min(now + deadline_seconds, budget_at)` when `budget_at` is given, and `now + deadline_seconds` otherwise. `remaining` is computed from that same `now`. If `remaining <= 0` it raises `deadline passed` before any request.
- Using a single clock reading means a caller whose socket timeout equals its deadline (the trending job) gets exactly `timeout_s` as the socket timeout, not a value a few microseconds short. For the default 4 s / 8 s case nothing changes.
- It sends `headers` if given, and otherwise `accept: application/json, text/vtt`. It opens with socket timeout `min(socket_timeout, remaining)`.
- Every failure has its own reason:

| Case | Reason text |
|---|---|
| A 2xx other than 200 | `HTTP {status}` |
| An `HTTPError` raised while the handler holds a refused target | `redirect refused: {target}` |
| Any other `HTTPError` (urllib raises 4xx/5xx and does not return them) | `HTTP {code}` |
| Content-Length over the cap | `Content-Length {n} over {cap} bytes` |
| Deadline passed between `read1` chunks | `deadline passed` |
| Streamed size over the cap | `body over {cap} bytes` |
| Anything else in `(OSError, ValueError, http.client.HTTPException)` | the exception text |

- `HTTPError` is caught before the general tuple and is closed after reading its code.
- With no overrides, the bounds, header, success cases and failure cases match today's `fetch_bounded` exactly. Only the result changes: today's `None` becomes a raised reason.

**Streamed form.**

- It opens `Request(url)` through `_open` with `SameHostRedirectHandler(host)` and `MEDIA_SOCKET_TIMEOUT_SECONDS`. There is no wall-clock deadline.
- It raises `SourceFetchFailed` with today's exact texts:
  - `media download failed: HTTP {status}` for a non-200 status.
  - `media over {max_bytes} bytes` for the Content-Length precheck and for the streamed cap.
  - `media download failed: {exc}` for the same exception tuple. A refused redirect keeps today's text, `media download failed: HTTP Error 302: …`.
- The loop is `read1(READ_CHUNK_BYTES)` until `stop.is_set()` or EOF, and passes each chunk to `consume(chunk)`.
- `BrokenPipeError` is an `OSError`, so an `except BrokenPipeError: raise` clause sits before the tuple. That keeps a consumer's broken pipe from being reported as a download failure and passes it on to the worker unchanged.

### Callers, requirement by requirement

**Translate route.**

- Deletes its constants (except `REQUEST_BUDGET_SECONDS` and `HEARTBEAT_FRESH_MS`), `same_host_https`, `SameHostRedirectHandler`, `fetch_bounded` and its urllib imports.
- Imports `same_host_https`, `fetch_bounded` and `SourceFetchFailed` from `data.source_fetch`. `_track_path` uses the adapter's check.
- `fetch_instance_track` keeps one `budget_at` and passes it as `budget_at=` to both fetches. Each fetch sits in a `try`. On `SourceFetchFailed` it logs `[translate] instance fetch failed host=… path=…: <reason>` and returns None. From there the existing None paths take over, so every status code and body of both routes stays the same.
- The denied-host 404 happens in `_resolve_translate_key`, which runs before `fetch_instance_track`, so it is untouched.

**Translate worker.**

- Drops `http.client`, `re`, `urlsplit`, `Request`, `build_opener`, `_TLD`, `MEDIA_SOCKET_TIMEOUT_SECONDS` and `media_host`.
- Imports `media_host`, `fetch_bounded`, `stream_media` and `SourceFetchFailed` from `data.source_fetch`. It keeps `READ_CHUNK_BYTES` too, because `_read` drains ffmpeg's stdout with it; that is pipe plumbing, not a fetch rule.
- Its route import shrinks to `SOURCE_INSTANCE`, `TARGET_LANGUAGE` and `fetch_instance_track`. The `api/` path entry stays, for `server_config`, `handlers.video` and that import. Its comment says so.
- The video-JSON fetch calls `fetch_bounded(instance, path)` with the defaults (one 8 s deadline) and turns `SourceFetchFailed` into `JobFailed(f"video JSON fetch failed: {exc}")`, e.g. `video JSON fetch failed: HTTP 404`. A body that does not decode to a JSON object still raises `JobFailed("video JSON fetch failed")`. The stale comment saying the text is "generic by necessity" goes.
- `AudioPipe._feed` becomes:
  - try `stream_media(self.url, self.host, self.max_bytes, self.proc.stdin.write, self.stop)`;
  - except `BrokenPipeError`: pass;
  - except `SourceFetchFailed` as exc: `self._fail(str(exc))`;
  - finally close stdin.

  The texts, cap, timeout and stop behaviour are the same as today.

**`/api/video` `fetch_instance_json`.**

- Drops `urlopen`, `Request` and the urllib error imports.
- Calls `fetch_bounded(host, path, headers={"accept": "application/json"})` with the default bounds.
- On `SourceFetchFailed` it logs `[video] instance request failed host=… path=…: <reason>` and returns None.
- It then decodes UTF-8, loads the JSON and checks for an object, with today's `[video]` log lines.
- A refused redirect never opens its target: urllib raises before the second request. Over-cap bodies also fail.
- Every failure is the same None that `/api/video` and `/api/video/refresh` already answer with the stored row and 200. A normal answer yields identical bytes, and therefore identical merged metadata.

**Trending `fetch_host_list`.**

- Drops the urllib imports and adds `TRENDING_MAX_BYTES`. Its comment records the measured page size, the instance it was measured on and the date.
- Each attempt calls `fetch_bounded(host, TRENDING_PATH, max_bytes=TRENDING_MAX_BYTES, deadline_seconds=timeout_s, socket_timeout=timeout_s, headers={"User-Agent": "peertube-browser-trending/1.0"})`, then `json.loads` and the "body has no data list" check.
- The except tuple becomes `(SourceFetchFailed, ValueError)`. The per-attempt DEBUG line logs the reason. The URL, loop, missing backoff and None-after-all contract are unchanged.
- The cap is set during the build: fetch `TRENDING_PATH` from at least one large instance (several candidates, such as framatube.org or tilvids.com, the largest kept) and pick a round figure with clear headroom (≥4×) over it. My estimate is a few hundred KB, so 2–4 MB.

### Tests (AC10, one patch point)

- All network stubbing moves to `monkeypatch.setattr(source_fetch, "build_opener", …)`.
- **Route tests.**
  - The existing `ScriptedInstance` carries over unchanged.
  - The direct `fetch_bounded` / `SameHostRedirectHandler` cases move to an adapter test file and now assert reasons instead of `None`.
  - The handler cases that patched the route's `fetch_bounded` are rebuilt over `ScriptedInstance`, whose URL recording replaces the fetch recorder.
- **Worker rig.** The two scripted hosts sit behind one dispatcher `build_opener` that routes by request host to the instance or the media host. Each host keeps its own recording, so there are no longer patches in two namespaces.
- **`test_video`.** It drops `urlopen` patching, in-process and in the Engine-child subprocess, for a scripted opener on the adapter. The recorded socket timeout changes from 8 to 4 (accepted). New cases cover a cross-host redirect and an over-cap body falling back to the stored row with no request to the target.
- **`test_fetch_trending`.** It uses a scripted opener on the adapter that records URL, timeout and User-Agent. The single clock reading keeps the exact `0.25` timeout assertion valid. New cases cover a cross-host redirect, an over-cap body and a per-attempt deadline.

### Docs

These follow AC11 one for one:

- `engine/server/README.md`: the fetch-bounds section points to `data/source_fetch.py`.
- `TRANSLATE_WORKER.md`: names the adapter and documents `video JSON fetch failed: <reason>`.
- `UPDATER_WORKER.md` Trending Stage: names the adapter, the cap and the per-attempt deadline.
- The `/api/video` notes say a refused redirect or over-cap body falls back to the stored row.
- `CONTEXT.md`: its sentence becomes "every source-instance fetch goes through the adapter in `data/source_fetch.py`".
- The route's module docstring "Bounds (AC6)" paragraph points to the adapter.

### Alternatives considered

- **Return a result type instead of raising.** A `(body, reason)` pair or a small `Fetched` object would mean every caller checks a branch. The trending loop would need a synthetic raise to reuse its retry logging, and the worker would need an extra if. The exception lands naturally in three of the four callers and costs one `try` in the other. Rejected.
- **Put the module elsewhere.** A top-level `engine/server/source_fetch.py` would also import fine. It would start a second convention for shared Engine/job code next to `data/`, which already holds non-DB helpers (`data.time`, `data.moderation.normalize_host`). A new `net/` package would add an `__init__` for one module. Both rejected in favour of the existing package.
- **Patch `urlopen` instead of `build_opener`.** Same-host redirects need a custom handler, so `urlopen` cannot be the patch point. One shared `_open` over `build_opener` keeps the existing `ScriptedInstance` pattern working, with urllib's real redirect handling.
- **Have the redirect handler raise its own exception.** That would change the settled "urllib raises the 3xx" behaviour and the media failure text. Recording the refused target on the handler gives a distinct reason without changing either.
- **One generic fetch with a "streaming" flag.** It would mix a deadline-bounded, byte-collecting loop with an undeadlined, consumer-fed one, plus two sets of failure texts. Two small functions sharing `_open` and the constants are clearer.

### Risks, gotchas, limitations

- **Unmeasured trending cap.** Measuring needs network access during the build. If the build sandbox has none, the operator must run the measurement, or the build stops at that point; the cap cannot be guessed and recorded as measured. A cap set too low would silently empty trending for large hosts, so take the measurement from the largest catalogue host available.
- **4xx/5xx become `HTTP {code}`.** Today they surface as `HTTPError` text. For media, this is deliberately not done, so its texts stay identical.
- **Socket timeout capped by remaining time.** For the trending job, with socket timeout = deadline = `timeout_s`, a slow-but-steady body is now cut at `timeout_s` of wall clock. Before, it could run on indefinitely. This is the intended per-attempt bound from UPDATER_WORKER.md.
- **DNS and TLS stalls.** DNS resolution and a TLS handshake stalling across records are still not bounded by the wall clock. This is the existing accepted gap, now documented in one place.
- **The adapter imports `data.moderation`.** It needs it for `normalize_host`. That module must stay stdlib-only and free of side effects, which it is today.
- **Large test rewrite.** The rewrite is broad: four suites, one Engine-child subprocess path. The cases' assertions are kept; only the stubbing layer and the `None`→reason expectations of the low-level fetch cases change.
- **Pre-existing gaps left alone.** `fetch_instance_json` still catches only `ValueError` around `json.loads`. A pathologically nested body within 2 MB could raise `RecursionError`, as it could before.

### Tradeoffs the operator accepts

- `/api/video`'s socket timeout drops from 8 s to 4 s (already accepted).
- Shared redirect-refusal log lines move from the `[translate]` prefix to `[source-fetch]`.
- Instance-side failures in the route and `/api/video` logs now carry a reason instead of being silent or generic.
- The trending job's cap is a measured number that will need raising if instance pages grow. The comment records the measurement so the next person can re-measure.

## Impacts


<impacts>
<impact path="engine/server/data/source_fetch.py" element="new module: imports and bounds constants (FETCH_MAX_BYTES, FETCH_DEADLINE_SECONDS, SOCKET_TIMEOUT_SECONDS, READ_CHUNK_BYTES, MEDIA_SOCKET_TIMEOUT_SECONDS, _TLD)">
**What changes.** The file is new. Copy the constants exactly:
- From `internal_translate.py:31-36`: 2_000_000, 8.0, 4.0 and 65_536.
- From `translate-worker.py:76`: 15.0, with the comment "The only stall bound on the download; there is no whole-job deadline."
- From `translate-worker.py:80-81`: `_TLD = re.compile(r"[a-z]{2,63}|xn--[a-z0-9-]{1,59}")` and its comment.

Imports are stdlib only: `http.client`, `logging`, `re`, `time`, `urllib.parse.urlsplit`, `urllib.request.{HTTPRedirectHandler, Request, build_opener}` and `urllib.error.HTTPError`, plus `from data.moderation import normalize_host`.

**Import chain.** I checked it:
- `data/moderation.py` imports only stdlib and `data.similarity_cache`.
- `data/similarity_cache.py` imports only os, sqlite3, struct, pathlib and typing.
- `data/__init__.py` is a bare docstring.

So the module loads under the Engine, which puts `engine/server` on `sys.path` (`api/server.py:21-23`), under both jobs, which insert `server_dir` before their `data.*` imports, and under pytest.

**Dependents.** The four callers (the route, the worker, `handlers/video.py` and `fetch-trending.py`), the four existing suites and the new adapter test file.

**Regression risks.**
- **Clock.** The module must `import time` and call `time.monotonic()` at call time. `test_internal_translate.py:289` patches `time.monotonic` on the `time` module, and the deadline cases depend on that patch. A `from time import monotonic` would escape it.
- **Patch point.** `build_opener` must be looked up as a module global at call time inside `_open`. Otherwise `monkeypatch.setattr(source_fetch, "build_opener", …)` stubs nothing, and the tests make real network calls to `peer.example` and similar hosts.
- **Log level.** Logging stays at INFO. The worker tests count WARNING and ERROR records (`test_translate_worker.py:999-1019`), and Engine WARNING records reach every log mode.
</impact>
<impact path="engine/server/data/source_fetch.py" element="same_host_https(url, host)">
**What changes.** Moved word for word from `internal_translate.py:48-55`.

**Dependents.**
- `SameHostRedirectHandler.redirect_request`.
- The route's `_track_path` (`internal_translate.py:133`), which now imports it.
- The caption-pick PICK_REFUSED cases in `test_internal_translate.py:141-145` and `:342-346`, which reach it through `pick_english_track_path`.

**Risk.** Low for the move itself. One latent behaviour now reaches new callers. The check compares `parts.hostname`, which urlsplit lowercases, with `host` exactly. `fetch-trending.py:104-105` documents that `video_embeddings.instance_domain` can be stored mixed-case, and `/api/video` passes the row's `instance_domain` raw. For such a host, every same-host redirect is now refused, relative ones included, because urljoin keeps the original case. The translate route already behaved this way. It is new for `/api/video` and trending, which followed any redirect before. That is uncertain impact, depending on whether stored domains are normalised in prod. Flag it; do not change it, since the plan moves the function word for word.
</impact>
<impact path="engine/server/data/source_fetch.py" element="media_host(url)">
**What changes.** Moved word for word from `translate-worker.py:158-170`. It needs `normalize_host` and `_TLD`. Its docstring, "raw … so SameHostRedirectHandler's exact compare holds", stays true.

**Dependents.**
- The worker's `pick_media_url` (`translate-worker.py:186`), which calls the bare name.
- The worker's `generate` (`:464`).
- The REFUSED_FILES cases in `test_translate_worker.py:328-340`: http, the IPv4 and IPv6 literals, the decimal, dotted-numeric and hex hosts, the single-label host, the port and the userinfo.
- The PICKS cases (`:358-365`).

**Risk.** Low if the move is exact. The worker must import it under the same name.
</impact>
<impact path="engine/server/data/source_fetch.py" element="SameHostRedirectHandler(host), gaining self.refused and a [source-fetch] log prefix">
**What changes.** Moved from `internal_translate.py:58-71`. `__init__` sets `self.refused = None`, and `redirect_request` sets `self.refused = newurl` before returning None. The log line changes from `[translate] refused redirect host=%s target=%s` to `[source-fetch] refused redirect …`, still at INFO.

**Dependents.**
- Both forms, through `_open`.
- The direct handler cases in `test_internal_translate.py:349-363`, which move to the adapter test file.
- `logging_profiles._derive_event_name`: the event name for this line becomes `source_fetch.info` (it was `translate.info`), visible in verbose mode only. No `_EventRule` needle matches either name.

**Risk.** Medium, through an interface gap in the plan. `_open(request, host, timeout)` builds the handler inside itself, so `fetch_bounded` has no reference to read `handler.refused` from after the `HTTPError`. The build must choose one of these:
- `_open` takes the handler;
- `_open` returns the handler;
- `fetch_bounded` builds the handler and passes it in.

A fresh handler per fetch is required, so refused state never leaks between fetches or threads; the Engine's handler threads share the module. `stream_media` must ignore `refused` and keep the raw `HTTPError` text.
</impact>
<impact path="engine/server/data/source_fetch.py" element="SourceFetchFailed and _open(request, host, timeout)">
**What changes.** These are new.
- `SourceFetchFailed(Exception)` carries the reason as its message.
- `_open` is the single place that calls `build_opener(SameHostRedirectHandler(host)).open(request, timeout=…)`.

**Dependents.**
- Every caller's `except SourceFetchFailed`: the route's `fetch_instance_track`, the worker's `generate` and `AudioPipe._feed`, `video.fetch_instance_json`, and `fetch_host_list`.
- Every test stub that replaces `source_fetch.build_opener`.

**Risk.** Medium. See the `refused` gap in the entry above. Test openers receive the handler through `*handlers`, as `ScriptedInstance.build_opener` (`test_internal_translate.py:258-269`) and `ScriptedHost.build_opener` (`test_translate_worker.py:437-448`) do today. Under a real `OpenerDirector`, the timeout reaches the scripted `https_open` as `req.timeout`, which is how a test can record it.
</impact>
<impact path="engine/server/data/source_fetch.py" element="fetch_bounded(host, path, *, max_bytes, deadline_seconds, budget_at, socket_timeout, headers) -> bytes">
**What changes.** This is the new buffered form. It replaces `internal_translate.fetch_bounded(host, path, budget_at) -> bytes | None`, and the signature changes: `budget_at` becomes keyword-only and optional. It raises `SourceFetchFailed` with these reasons:
- `HTTP {status}` for a returned non-200 response;
- `redirect refused: {target}`;
- `HTTP {code}` for any other `HTTPError`;
- `Content-Length {n} over {cap} bytes`;
- `deadline passed`, both before the open and between chunks;
- `body over {cap} bytes`;
- the exception text for `(OSError, ValueError, http.client.HTTPException)`.

The default header is `accept: application/json, text/vtt`; a caller's `headers` replace it.

**Dependents.**
- The route: two calls with `budget_at=`.
- The worker's video-JSON fetch, with the defaults.
- `video.fetch_instance_json`, with `headers={"accept": "application/json"}`.
- `fetch-trending.fetch_host_list`, with max_bytes, deadline_seconds, socket_timeout and the User-Agent header.

**Regression risks.**
- **Catch order.** `HTTPError` is an `OSError` and must be caught first, or the redirect and status reasons collapse into exception text.
- **Closing `HTTPError`.** `test_fetch_trending.py:192-193` raises `HTTPError(url, code, msg, {}, None)` with `fp=None` from the open step. Closing it must not raise. Recent CPython substitutes a `BytesIO`; verify on the Engine and venv interpreters, or guard the close.
- **Floating point.** The plan claims one `now` reading makes the socket timeout exactly `timeout_s`. That is false in floating point. `(now + 0.25) - now` is not exactly 0.25 for an arbitrary `time.monotonic()` value; it is off by about one ulp of `now`, around 1e-12. `min(0.25, remaining)` can then be `0.24999999999…`, which makes the exact assertion `attempts == [(TRENDING_URL, 0.25)]` (`test_fetch_trending.py:186`, `:209`) flaky. The route tests are safe only because their Clock starts at 1000.0. The fix is to compute `remaining = deadline_seconds if budget_at is None else min(deadline_seconds, budget_at - now)` and then `deadline = now + remaining`.
- **No overrides.** With no overrides it must equal today's behaviour exactly; the cases at `test_internal_translate.py:366-430` pin it.
- **Status check.** Keep `resp.status != 200`: urllib returns non-error 2xx responses.
- **Header case.** urllib stores header names capitalized (`User-agent`, `Accept`), so test assertions on headers must use `get_header("User-agent")`.
</impact>
<impact path="engine/server/data/source_fetch.py" element="stream_media(url, host, max_bytes, consume, stop)">
**What changes.** This is the new streamed form, lifted from `AudioPipe._feed` (`translate-worker.py:231-262`) without the stdin handling. It opens `Request(url)` through `_open` with `MEDIA_SOCKET_TIMEOUT_SECONDS` and has no deadline. It raises:
- `media download failed: HTTP {status}`;
- `media over {max_bytes} bytes`, for both the precheck and the streamed count;
- `media download failed: {exc}` for the tuple, which keeps `HTTP Error 302: …` for a refused redirect.

It loops `read1(READ_CHUNK_BYTES)` while `not stop.is_set()`, checks the size before calling `consume(chunk)`, and re-raises `BrokenPipeError` before the tuple.

**Dependents.** `AudioPipe._feed`, and through it these test_translate_worker cases:
- the BOUNDS cases "media Content-Length over max_bytes" (`unread`: zero reads), "media streamed past max_bytes" and "media redirect off the media host" (target never requested; `_error_leads("media download failed")`);
- the same-host media redirect test (`:851`);
- the moov-at-end and faststart outcomes.

**Risk.** Medium.
- The texts must stay byte-identical (AC6, TRANSLATE_WORKER.md:138).
- The size check must come before `consume`, so an over-cap chunk is never written.
- The stop check stays at loop entry, so `AudioPipe.close()`'s join stays bounded by one socket timeout.
- A `ValueError` from writing to a closed stdin is still reported as `media download failed: …`, as today.
</impact>
<impact path="engine/server/data/moderation.py" element="normalize_host (no code change; new importer)">
**What changes.** Nothing. `data.source_fetch` becomes a new importer, for `media_host`.

**Risk.** Low. The module must stay importable without side effects: it is stdlib plus `data.similarity_cache` today. Any heavy import added here later would now load in every caller of the adapter, the Engine's `/api/video` path and the trending job included.
</impact>
<impact path="engine/server/api/handlers/internal_translate.py" element="module imports, constants and module docstring">
**What changes.**
- **Deleted:** `FETCH_MAX_BYTES`, `FETCH_DEADLINE_SECONDS`, `SOCKET_TIMEOUT_SECONDS` and `READ_CHUNK_BYTES` (`:31-36`), `import http.client` (`:12`), and `from urllib.request import HTTPRedirectHandler, Request, build_opener` (`:20`).
- **Must stay:** `from urllib.parse import quote, urlsplit` (`:19`). The plan says it "deletes … its urllib imports", which is too broad: `quote` is used in `fetch_instance_track` (`:190`) and `urlsplit` in `_track_path` (`:134`). `import re` stays for the WebVTT regexes and `import time` for `budget_at`.
- **Kept:** `REQUEST_BUDGET_SECONDS` and its comment, which still holds with the adapter's 4 s socket timeout, and `HEARTBEAT_FRESH_MS`.
- **Added:** `from data.source_fetch import SourceFetchFailed, fetch_bounded, same_host_https`.
- **Docstring:** the "Bounds (AC6)" paragraph (`:7`) points to `data/source_fetch.py` and keeps the 15 s per-request budget as the route's own.

**Dependents.**
- `handlers/similar.py:102`, which imports the two handlers at Engine load.
- The worker's route import (`translate-worker.py:48`).
- `test_internal_translate.py`'s `_translate` and `_handler_module`.

**Risk.** Medium. An import error here breaks Engine start, because `similar.py` imports the module. Dropping `urlsplit` by mistake fails only at runtime, on a `fileUrl` caption entry.
</impact>
<impact path="engine/server/api/handlers/internal_translate.py" element="same_host_https, SameHostRedirectHandler, fetch_bounded (deleted, :48-108)">
**What changes.** All three are deleted. Their INFO log lines go with them:
- `[translate] response over cap` (two places);
- `[translate] fetch deadline passed`;
- `[translate] instance fetch failed`.

The route re-adds the last one, carrying the reason, in `fetch_instance_track`.

**Dependents.**
- `test_internal_translate.py:282`, which patches `module.build_opener`.
- `test_internal_translate.py:476`, which patches `module.fetch_bounded`.
- `test_translate_worker.py:507`, which patches `handlers.internal_translate.build_opener`.
- `tests/tmp/probe_50_phase1_rows.py`, through `_handler_module`.

**Risk.** High churn. `monkeypatch.setattr` on a missing attribute raises `AttributeError` by default (`raising=True`), so leftover patches fail loudly rather than silently. That is good, but every one of them must be found and moved.
</impact>
<impact path="engine/server/api/handlers/internal_translate.py" element="fetch_instance_track(host, video_key)">
**What changes.** It keeps one `budget_at = time.monotonic() + REQUEST_BUDGET_SECONDS` and calls `fetch_bounded(host, path, budget_at=budget_at)` for the caption list and then the track. Each call sits in `try/except SourceFetchFailed`, which logs `[translate] instance fetch failed host=%s path=%s: %s` at INFO and returns None. The later None paths are unchanged: no en track, no usable path, UTF-8 decode and parse.

**Dependents.**
- `handle_internal_translate` (`:301`).
- The worker's `generate` (`translate-worker.py:443`), still imported from the route by operator decision.
- test_internal_translate's gate, store, job-state and NONE_PATHS cases (`:166-171`, `:596-604`).

**Risk.** Medium. AC5 requires identical statuses and bodies; every adapter failure must end as None. The second fetch must share the one request budget, not get a fresh 8 s.
</impact>
<impact path="engine/server/api/handlers/internal_translate.py" element="_track_path(item, host)">
**What changes.** It calls `same_host_https`, now imported from the adapter, and still uses `urlsplit` locally.

**Dependents.** `pick_english_track_path`, and the PICK_REFUSED and caption-pick tests.

**Risk.** Low.
</impact>
<impact path="engine/server/api/handlers/similar.py" element="import of handle_internal_translate / handle_internal_translate_enqueue and handle_video_* (:102-103), no code change">
**What changes.** Nothing. This is the Engine's load path for both changed handler modules, which now import `data.source_fetch` transitively.

**Risk.** Low, but any import-time error in the adapter, the route or `video.py` stops Engine start. `test_internal_translate.py`'s startup test, which runs `server.py` under `ENGINE_PY`, and test_video's Engine-child cases catch it.
</impact>
<impact path="engine/server/db/jobs/translate-worker.py" element="imports, sys.path block (:34-40) and module constants">
**What changes.**
- **Dropped:** `import http.client` (`:16`), `import re` (`:21`), `urlsplit` (`:31`, keep `quote`, which `:448` uses), `from urllib.request import Request, build_opener` (`:32`), `MEDIA_SOCKET_TIMEOUT_SECONDS` and its comment (`:75-76`), and `_TLD` and its comment (`:80-81`).
- **Route import (`:48`):** shrinks to `SOURCE_INSTANCE, TARGET_LANGUAGE, fetch_instance_track`.
- **Added:** `from data.source_fetch import READ_CHUNK_BYTES, SourceFetchFailed, fetch_bounded, media_host, stream_media`. `READ_CHUNK_BYTES` is still used by `_read` (`:267`).
- **`api/` path entry (`:38-40`):** stays, for `server_config`, `handlers.video.fetch_video_row` and `fetch_instance_track`. Its comment should say so.

**Dependents.**
- `test_translate_worker.py`'s `_worker()` (`:250-255`, in-process `spec_from_file_location`).
- The `-c` stall driver (`:208-216`).
- The `enqueue`/`run` subprocesses under `ENGINE_PY`.
- The systemd unit, which runs the script.

**Risk.** Medium. A leftover use of a removed name (`re`, `urlsplit`, `http.client`, `MEDIA_SOCKET_TIMEOUT_SECONDS`) fails only on the job path at runtime. Grep shows no other uses in the file.

**AC2 note.** `fetch_instance_track` is still a fetch-performing function imported from a route. The requirements accept this explicitly as an operator decision; issue 54/56 is where it moves.
</impact>
<impact path="engine/server/db/jobs/translate-worker.py" element="media_host (deleted, :158-170) and pick_media_url (:178-190)">
**What changes.** `media_host` is deleted and imported from the adapter. The body of `pick_media_url` is unchanged.

**Dependents.**
- `generate` (`:464`).
- The REFUSED_FILES and PICKS tests.

**Risk.** Low.
</impact>
<impact path="engine/server/db/jobs/translate-worker.py" element="AudioPipe._feed (:231-262)">
**What changes.** The body becomes:
- try `stream_media(self.url, self.host, self.max_bytes, self.proc.stdin.write, self.stop)`;
- except `BrokenPipeError`: pass, keeping the comment;
- except `SourceFetchFailed` as exc: `self._fail(str(exc))`;
- finally close stdin and swallow `OSError`.

The docstring and the comment that cites "B1's fetch_bounded" are updated.

**Dependents.**
- `_read`, `_fail` and `close`.
- The media BOUNDS cases and the outcome cases in test_translate_worker.
- TRANSLATE_WORKER.md Error Texts.

**Risk.** Medium.
- The texts must stay identical.
- `self.stop` must be the Event that `_fail` and `close` set.
- An exception outside both clauses still kills the feeder thread silently, as today.
</impact>
<impact path="engine/server/db/jobs/translate-worker.py" element="generate: video-JSON fetch (:448-455)">
**What changes.** It calls `raw = fetch_bounded(instance, f"/api/v1/videos/{quote(video_key, safe='')}")` with the defaults. The 8 s deadline equals today's `time.monotonic() + FETCH_DEADLINE_SECONDS` budget. `SourceFetchFailed` becomes `JobFailed(f"video JSON fetch failed: {exc}")`. A body that is not a JSON object, including one that raises `ValueError` or `RecursionError`, still gives `JobFailed("video JSON fetch failed")`. The "generic by necessity" comment (`:453`) goes.

**Dependents.**
- The BOUNDS case "video JSON redirect off the instance domain" (`test_translate_worker.py:349`). It checks the error with `_error_leads`, which accepts `text: detail`, so `video JSON fetch failed: redirect refused: https://cdn.example/api/v1/videos/u-1` passes.
- `PRESENT["failed"]` (`:125`), which is fixture data only.
- The `subtitles.error` column that operators read.

**Risk.** Low. The stored text gains a suffix. Nothing compares it exactly.
</impact>
<impact path="engine/server/api/handlers/video.py" element="imports (:13-15) and fetch_instance_json(host, path) (:82-101)">
**What changes.**
- **Imports:** drops `from urllib.error import HTTPError, URLError` and `from urllib.request import Request, urlopen`. Keeps `quote`. Adds `from data.source_fetch import SourceFetchFailed, fetch_bounded`.
- **Body:** `fetch_bounded(host, path, headers={"accept": "application/json"})`. On `SourceFetchFailed` it logs `[video] instance request failed host=%s path=%s: %s` and returns None. It then decodes UTF-8 and runs `json.loads` inside the existing `ValueError` handler (`UnicodeDecodeError` is a `ValueError`; the bad-utf8 case pins this), then the dict check. The `[video]` log lines stay.
- **Bounds:** the socket timeout goes from 8 s to 4 s (accepted). It gains an 8 s deadline per call, a 2 MB cap and same-host https redirects only.
- **Docstring:** should mention the adapter.

**Side effect.** Other `OSError`s and `http.client.HTTPException` (`IncompleteRead`, `RemoteDisconnected`) raised during `resp.read()` used to escape the old `(HTTPError, URLError, TimeoutError)` catch and fail the request. They now become None, and the stored row is answered with 200. That is a behaviour improvement and should be noted.

**Dependents.**
- `fetch_instance_video_dynamic` (`:210`, `:228`), and from there `handle_video_refresh_request` (`:455`) and `handle_video_request` (`:466`).
- The Client proxy budget (`client/backend/server.py:86`).
- The statement deadline note in DEPLOYMENT.md:753.

**Risk.** Medium.
- AC8: a normal answer must yield identical bytes.
- Mixed-case `instance_domain` values lose same-host redirects (see `same_host_https`).
- Worst case per call is about 8 s plus one 4 s socket timeout. Two calls can still exceed the Client's 20 s proxy budget, as before; no request budget is passed here.
</impact>
<impact path="engine/server/api/handlers/video.py" element="fetch_instance_video_dynamic / handle_video_refresh_request / handle_video_request (no code change)">
**What changes.** Nothing. They still receive None on any failure. A refused redirect or an over-cap body now becomes None, so the stored row is answered with 200 and nothing is written (AC7).

**Risk.** Low. The write-back guard (`dynamic is not None`, `:457`) is unchanged.
</impact>
<impact path="engine/server/db/jobs/fetch-trending.py" element="imports (:19), new TRENDING_MAX_BYTES, fetch_host_list (:73-88)">
**What changes.**
- **Imports:** drops `from urllib.request import Request, urlopen` and adds `from data.source_fetch import SourceFetchFailed, fetch_bounded` after the sys.path block (`:21-29`).
- **New constant:** `TRENDING_MAX_BYTES`, with a comment giving the measured size, the instance and the date.
- **Each attempt:** `json.loads(fetch_bounded(host, TRENDING_PATH, max_bytes=TRENDING_MAX_BYTES, deadline_seconds=timeout_s, socket_timeout=timeout_s, headers={"User-Agent": "peertube-browser-trending/1.0"}))`, then the "body has no data list" check.
- **Except tuple:** becomes `(SourceFetchFailed, ValueError)`, with its comment (`:85`) and the rat-tail comment (`:75`) updated. The DEBUG line carries the reason.

**Dependents.**
- `main()`'s `partial(fetch_host_list, timeout_s=args.timeout_ms / 1000, …)`.
- `updater-worker.py:1104` step 13 (systemd `--timeout-ms 15000 --max-retries 3`).
- `run`'s `_fetch_safely`.
- The ORCHESTRATOR_SMOKE_TEST run, which makes real fetches against mini-prod hosts.

**Risk.** High.
- **Cap.** The cap needs a real measurement. Set too low, it silently fails large hosts, and they lose their rows after two weekly runs.
- **Wall clock.** `--timeout-ms` now also bounds each attempt's wall clock, so a slow but steady page that used to succeed now fails.
- **2xx.** A 2xx other than 200 now fails.
- **Non-positive timeout.** A non-positive `--timeout-ms` now fails every attempt with `deadline passed` and no request.
- **Mixed case.** Hosts stored mixed-case lose same-host redirects.
- **Exception paths.** An `OSError` raised outside the adapter is no longer retried, but nothing else in the try raises one. `RecursionError` still goes to `_fetch_safely`, as before.
</impact>
<impact path="engine/server/db/jobs/updater-worker.py" element="trending stage invocation (:1104 and run_cmd), no code change">
**What changes.** Nothing. It still passes `--timeout-ms` and `--max-retries` through. Their meaning changes: the per-attempt value is now also a wall-clock deadline.

**Risk.** Low. `test_updater_worker.py` checks only the argv, not fetch behaviour.
</impact>
<impact path="tests/active/test_source_fetch.py" element="new adapter test file">
**What changes.** It is new. It takes the moved direct cases from `test_internal_translate.py:349-430` and asserts `SourceFetchFailed` reasons where they asserted None:
- the redirect handler, same-host and refused;
- following a redirect, absolute and relative;
- a refused redirect, with the target never opened and the reason `redirect refused: …`;
- Content-Length over the cap, with zero reads;
- streamed over the cap;
- the 2,000,000-byte body, declared and streamed;
- the per-fetch deadline and the request budget;
- a body finished inside the deadline;
- a spent budget that opens nothing.

New cases cover the `HTTP {status}` and `HTTP {code}` reasons, the network-error text, the overrides (max_bytes, deadline_seconds, socket_timeout, headers replacing `accept`), `media_host`, the texts and BrokenPipe pass-through of `stream_media`, and `refused` not leaking across fetches.

**Dependents.** It needs `Clock`, `Response` and `ScriptedInstance`: either imported from `test_internal_translate` or copied. It also needs a `tests/config.json` group.

**Risk.** Medium. The test ids move, so `tests/last_test_validation.json` changes.
</impact>
<impact path="tests/active/test_internal_translate.py" element="_translate patch (:278-283), direct fetch cases (:349-430), RecordingInstance/_handler_module/_instance/_route (:453-477, :625-636) and module docstring">
**What changes.**
- `_translate(instance)` patches `data.source_fetch.build_opener`.
- The direct cases move to `test_source_fetch.py`.
- `RecordingInstance` and `_handler_module` are rebuilt over `ScriptedInstance` (41 references in the file). `fetched` and `hosts()` become derived from `opened` URLs, and `hosts()` takes the urlsplit hostname.
- NONE_PATHS `None` entries (`:169-170`) become unserved routes, which answer 404, so `HTTP 404` gives None.
- Docstring lines 12-21 and 49 change.

**Dependents.**
- `tests/tmp/probe_50_phase1_rows.py`, which imports `RecordingInstance` and `_handler_module`.
- `tests/tmp/probe_50_phase2_enqueue.py` and `probe_50_phase2_observe.py`, which import `HandlerRequest`, `_subtitles_db` and `whitelist` (unchanged names).
- `test_translate_worker.py`'s docstring references to `ScriptedInstance` and `_whitelist`.

**Risk.** High churn.
- The handler cases now run the real adapter. Without the `time.monotonic` patch they use the real clock, which is harmless but nondeterministic.
- They fetch from both `peer.example` and `denied.example`. ScriptedInstance routes by full URL, so that works.
- The startup test, which runs `server.py` under `ENGINE_PY`, verifies the Engine still loads the new import chain.
</impact>
<impact path="tests/active/test_translate_worker.py" element="Rig (:488-526): ScriptedHost patches at :507-508, serve_media/redirect_video; module docstring (:10, :15)">
**What changes.** The two `monkeypatch.setattr` calls become one, on `data.source_fetch.build_opener`: a dispatcher that routes each `req.host` to `self.instance` (peer.example) or `self.media` (media.example). The old `setattr(self.worker, "build_opener", …)` would now raise `AttributeError`. The docstring changes at `:10`, and at `:15` for the new error suffix.

**Dependents.** Every job-pipeline test that asserts the instance and media `opened` lists, the BOUNDS table and `test_a_media_redirect_that_stays_on_the_media_host_is_followed`.

**Risk.** High.
- **`cdn.example`.** Both off-host targets are `cdn.example`: `OFF_DOMAIN_VIDEO_URL` (`:153`), served on the instance by `redirect_video`, and `OFF_HOST_TARGET` (`:152`), served on the media host by `serve_media`. A host-keyed dispatcher has no single owner for it. It must route `cdn.example` to whichever ScriptedHost served it, or record unknown hosts in an asserted list. Otherwise a regression that followed the redirect would show up as an unrouted error instead of a recorded URL, which weakens "target never requested".
- **Fresh opener.** The dispatcher must build a fresh real opener per call with the given handlers, so the real `SameHostRedirectHandler` runs.
</impact>
<impact path="tests/active/test_video.py" element="_FakeResponse/_serve (:312-344), timeout assertions (:422, :506), PERSIST_CHILD refusing stub (:243-248), refuse case (:696-703), docstring (:9, :11, :29, :32)">
**What changes.**
- **`_serve`:** it patches `video.urlopen`. It becomes a scripted `build_opener` on `data.source_fetch`. `_FakeResponse` has only `read` and `status`; through a real opener and the adapter it needs `headers`, `info()`, `read1`, `code`, `msg`, `geturl` and a context manager.
- **"status-404":** goes through urllib's error processor and becomes `HTTP 404`, still a failure.
- **"urlopen-urlerror":** becomes an exception raised from the open step.
- **Timeout assertions:** `(VIDEO_URL, 8)` becomes 4.
- **PERSIST_CHILD:** `patch.object(video, "urlopen", refusing)` must become a patch of `data.source_fetch.build_opener` inside the Engine child. The child imports `server` first, which puts `engine/server` on `sys.path`; `from data import source_fetch` then resolves the same module `handlers.video` uses.
- **ANSWER_CHILD and the in-process cases** that patch `video.fetch_instance_json` stay valid.
- **New cases:** a cross-host redirect, with the target never requested, and an over-cap body. Both must give the stored row with 200 and an unchanged DB.

**Risk.** Medium-high. The Engine-child path is easy to mis-patch. The recorded calls `[req.host, req.selector]` must stay `[[HOST, DETAIL_PATH]]`.
</impact>
<impact path="tests/active/test_fetch_trending.py" element="_Response (:158-162), _fake_urlopen (:165-177), FAILURES (:191-199), fetch_host_list tests (:180-225), docstring (:6, :10)">
**What changes.**
- **Stub:** `monkeypatch.setattr(job, "urlopen", …)` becomes a scripted opener on `data.source_fetch.build_opener` that records URL, timeout (`req.timeout`) and User-Agent (`req.get_header("User-agent")`) and pops one outcome per attempt.
- **`_Response(io.BytesIO)`:** has `read1` but no `headers`, `info()`, `code` or `msg`. Without `headers` the adapter raises `AttributeError`, which is outside the tuple.
- **FAILURES:** the `HTTPError`s with `fp=None`, `URLError` and `TimeoutError` are raised from the open step. The not-json, no-data and data-not-a-list cases stay as bodies.
- **Exact timeout:** `0.25` stays exact only with the remaining-time computation described under `fetch_bounded`.
- **New cases:** a cross-host redirect, an over-cap body and a per-attempt deadline. The deadline case needs a patched `time.monotonic`.

**Dependents.** The job is loaded by `spec_from_file_location`. Its `from data.source_fetch import …` binds the same `sys.modules` object the test patches, because `SERVER_DIR` is on `sys.path` (`:27-28`).

**Risk.** Medium.
</impact>
<impact path="tests/config.json" element="test_groups">
**What changes.**
- Add a `test_source_fetch.py` group: `engine/server/data/source_fetch.py` and `engine/server/data/moderation.py`.
- Add `engine/server/data/source_fetch.py` to the groups for `test_video.py` (`:174-181`), `test_fetch_trending.py` (`:73-77`), `test_internal_translate.py` (`:400-409`) and `test_translate_worker.py` (`:420-428`).

**Risk.** Low-medium. Without these entries, an adapter-only change does not reselect the dependent suites.
</impact>
<impact path="tests/last_test_validation.json" element="generated test record">
**What changes.** The test ids for the four suites change (the moved fetch cases, the renamed parameter ids such as `urlopen-urlerror`) and a new suite appears. The file is regenerated by the validation run, not edited by hand.

**Risk.** Low.
</impact>
<impact path="tests/tmp/probe_50_phase1_rows.py" element="imports RecordingInstance, _handler_module from test_internal_translate (:11, :28-30)">
**What changes.** It breaks on import if those names are removed or renamed.

**Risk.** Low. It is a scratch probe in the working tree. The build either keeps compatible names or retires the probe.
</impact>
<impact path="client/backend/server.py" element="comment at :86 (ENGINE_PROXY_ROUTE_TIMEOUT_SECONDS)">
**What changes.** The comment "up to two 8 s instance calls" now means two calls, each with an 8 s wall-clock deadline and a 4 s socket timeout. The value is out of scope.

**Risk.** Low, comment only.
</impact>
<impact path="engine/server/api/logging_profiles.py" element="_derive_event_name / _classify_event (no code change)">
**What changes.** Nothing in code.
- `[source-fetch] refused redirect` becomes the event `source_fetch.info` (the hyphen becomes an underscore), shown in verbose mode only.
- The new `[video] instance request failed host=… path=…` keeps the `video` scope, and `_extract_fields` now picks up `host` and `path`.

**Risk.** Low. No `_EventRule` needle matches these lines.
</impact>
<impact path="docs/project/issues/53-source-instance-fetch-adapter.md" element="issue status">
**What changes.** On delivery, `Status:` becomes `complete` and the file moves to `docs/project/issues/archive/` (`docs/project/triage-labels.md`). Issues 54, 55 and 57 cite `internal_translate.py` and `translate-worker.py` line numbers that this build shifts. Those citations go stale but are informational, and `docs/project/issues/plan.md` already expects 54 to build on the adapter.

**Risk.** None to code.
</impact>
</impacts>


## Documentation to update

- [ ] `engine/server/README.md` - - **Line 9 (`/api/video`):** "each with an 8 s socket timeout" becomes false. Replace it with the adapter's bounds and point to `data/source_fetch.py`: https only, redirects only to the same host over https, 2,000,000 bytes, an 8 s deadline and a 4 s socket timeout per call.
- **Line 11:** add that a refused redirect or an over-cap body counts as a failed detail call, so nothing is written and the stored row is answered.
- **Line 21 (`/internal/translate` Fetch bounds):** name `data/source_fetch.py` as where the bounds live, and keep the 15 s two-fetch budget as the route's own.
- [ ] `engine/server/db/jobs/docs/TRANSLATE_WORKER.md` - - **Line 91:** "through B1's `fetch_bounded`" becomes the adapter `data/source_fetch.py`, with its default bounds.
- **Line 107:** the Instance calls row names the adapter.
- **Line 118 and the Media File Choice bullets:** URL acceptance and the same-host redirect rule live in the adapter's `media_host` and `stream_media`.
- **Line 137:** `video JSON fetch failed` becomes `video JSON fetch failed: <reason>`, for example `HTTP 404` or `redirect refused: …`. The bare text remains only for a body that is not a JSON object.
- **Lines 96 and 138:** the texts and values are unchanged; optionally say they live in the adapter.
- [ ] `engine/server/db/jobs/docs/UPDATER_WORKER.md` - - **Trending Stage, line 94:** name the adapter and `TRENDING_MAX_BYTES`, with its measured basis. Say `--timeout-ms` is now both the socket timeout and the per-attempt wall-clock deadline. Replace "non-2xx" with non-200, and add that a redirect off the host or off https and a body over the cap each fail the attempt and are retried.
- **Line 110:** the per-attempt DEBUG line carries the adapter's reason.
- [ ] `CONTEXT.md` - - **Line 20, Source-instance fetch:** replace "Today only the translate route and the translate worker follow this rule. Issue 53 moves them…" with: every source-instance fetch goes through the adapter in `data/source_fetch.py` (the translate route, the translate worker, `/api/video` and the trending job). Keep that `/api/video` serves the stored row when the metadata fetch fails, a refused redirect or an over-cap body included.
- [ ] `engine/server/api/handlers/internal_translate.py` - - **Module docstring line 7, "Bounds (AC6)":** point to `data/source_fetch.py` for the per-fetch bounds, keep the route's 15 s request budget, and keep the accepted DNS and TLS gap.
- [ ] `engine/server/api/handlers/video.py` - - **`fetch_instance_json` docstring:** state the adapter bounds, and that a refused redirect or an over-cap body is None. The module docstring is optional.
- [ ] `DEPLOYMENT.md` - - **Line 751 (outbound 443):** a consistency edit. `/api/video` calls and the trending stage now follow the same https-only, same-host-redirect and capped rule as the translate fetches. Nothing there becomes false.
- [ ] `client/backend/server.py` - - **Comment line 86:** "up to two 8 s instance calls" becomes two calls, each with an 8 s deadline and a 4 s socket timeout.
- [ ] `tests/active/test_internal_translate.py` - - **Module docstring, lines 12-21 and 49:** the direct fetch section moves to `test_source_fetch.py`, and the handler harness becomes `ScriptedInstance` on `data.source_fetch.build_opener`.
- [ ] `tests/active/test_translate_worker.py` - - **Module docstring, lines 10 and 15:** one dispatcher on `data.source_fetch.build_opener` replaces the two namespaces, and the video-JSON redirect error becomes `video JSON fetch failed: redirect refused: …`.
- [ ] `tests/active/test_video.py` - - **Module docstring, lines 9, 11, 29 and 32:** the `urlopen` patching becomes the adapter's scripted opener. Add the redirect and over-cap cases, and note the 4 s socket timeout.
- [ ] `tests/active/test_fetch_trending.py` - - **Module docstring, lines 6 and 10:** "a `urlopen` patched on the module" becomes the adapter's scripted opener. Add the redirect, over-cap and deadline cases.
- [ ] `docs/project/issues/53-source-instance-fetch-adapter.md` - - On delivery, set `Status:` to `complete` and move the file to `docs/project/issues/archive/`.

## Implementation plan

## Draft implementation: source-instance fetch adapter (issue 53)

### Reading done before drafting

I read `internal_translate.py` (constants, `same_host_https`, `SameHostRedirectHandler`, `fetch_bounded`, `_track_path` and `fetch_instance_track`) and the worker's imports, `media_host`, `AudioPipe._feed` and `generate`. I also read `video.fetch_instance_json`, `fetch-trending.fetch_host_list` and the four suites' stubbing layers: `Clock`/`Response`/`ScriptedInstance` and `RecordingInstance` in test_internal_translate, `ScriptedHost` and `Rig` in test_translate_worker, `_FakeResponse`/`_serve` and `PERSIST_CHILD` in test_video, and `_Response`/`_fake_urlopen` in test_fetch_trending.

Facts from the tree that shaped the draft:
- The worker still uses `time` (heartbeat and stall loop) and `quote`. Nothing outside `media_host` and `_feed` uses `re`, `urlsplit`, `http.client`, `Request` or `build_opener`.
- `RecordingInstance()` is built with no arguments 13 times. Tests read its `.fetched`, `.serve(video, listing, track)` and `.hosts()`, and `tests/tmp/probe_50_phase1_rows.py` imports it. Those four names keep their shape.
- `tests/active` has no `__init__.py`, so pytest's prepend mode puts it on `sys.path`. A suite can import helpers from `test_internal_translate`; the probe already does.

### What the build has to test

| Behaviour | Where it is pinned |
|---|---|
| Both URL checks keep today's semantics; redirect handler follows same-host https and refuses the rest | test_source_fetch (moved cases), test_internal_translate PICK_REFUSED, test_translate_worker REFUSED_FILES/PICKS |
| Buffered form: each distinct reason; with no overrides, exactly today's bounds and header; overrides work; no `refused` leak between fetches; socket timeout = min(socket_timeout, remaining) | test_source_fetch |
| Streamed form: today's texts byte for byte; precheck reads nothing; size checked before `consume`; stop honoured; `BrokenPipeError` passed through unchanged; 15 s timeout | test_source_fetch, plus the worker BOUNDS and outcome cases |
| Route responses unchanged; budget shared across both fetches; failure logged with its reason | test_internal_translate gate, store, job-state and NONE_PATHS cases over the real adapter |
| Worker: `video JSON fetch failed: <reason>`; the bare text for a non-object body; media texts unchanged | test_translate_worker BOUNDS and pipeline |
| `/api/video`: cross-host redirect or over-cap body → stored row, 200, DB unchanged, target never requested; normal answer → same merge; timeout 4 | test_video, in-process and Engine-child |
| Trending: exact URL, `timeout_s` as socket timeout, User-Agent sent, retries, None after all attempts; redirect, over-cap and deadline each fail the attempt | test_fetch_trending |
| Engine still starts with the new import chain | test_internal_translate startup test, test_video Engine-child cases |

---

### 1. New: `engine/server/data/source_fetch.py`

```python
"""Source-instance fetch (CONTEXT.md): the one rule for every request to a PeerTube instance, or to a media host its JSON names, both untrusted.

https only, no explicit port, no userinfo, redirects followed only to https on the same host, a byte cap, a time bound, and a failure that says why (SourceFetchFailed). fetch_bounded buffers a JSON or WebVTT body under a wall-clock deadline; stream_media hands a media download to a consumer chunk by chunk under a socket timeout only. Both open through _open, so this module's build_opener is the one place tests stub the network. Not bounded by the wall clock: DNS resolution and a TLS handshake stalling across several records (stdlib has no DNS timeout); accepted gap.
"""
from __future__ import annotations

import http.client
import logging
import re
import threading
import time
from typing import Callable
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from data.moderation import normalize_host

FETCH_MAX_BYTES = 2_000_000
FETCH_DEADLINE_SECONDS = 8.0
SOCKET_TIMEOUT_SECONDS = 4.0
READ_CHUNK_BYTES = 65_536
# The only stall bound on the download; there is no whole-job deadline.
MEDIA_SOCKET_TIMEOUT_SECONDS = 15.0
# A DNS name's last label is letters or punycode, never digits or hex.
_TLD = re.compile(r"[a-z]{2,63}|xn--[a-z0-9-]{1,59}")
# OSError covers HTTPError, URLError, timeouts, resets and ssl errors; ValueError covers InvalidURL and IDNA UnicodeError; HTTPException covers IncompleteRead and RemoteDisconnected.
_FETCH_ERRORS = (OSError, ValueError, http.client.HTTPException)


class SourceFetchFailed(Exception):
    """A source-instance fetch failed; the message is the short reason."""


def same_host_https(url: str, host: str) -> bool:
    """Whether url is https on exactly host, with no explicit port and no userinfo (R5)."""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return False
    return parts.scheme == "https" and parts.hostname == host and port is None and parts.username is None and parts.password is None


def media_host(url: str) -> str | None:
    """The raw urlsplit hostname of an acceptable media URL (https, a DNS name, no port, no userinfo), else None; raw, not normalize_host's, so SameHostRedirectHandler's exact compare holds."""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return None
    host = parts.hostname or ""
    labels = host.rstrip(".").split(".")
    if parts.scheme != "https" or port is not None or parts.username is not None or parts.password is not None or normalize_host(host) is None:
        return None
    # Two labels or more ending in a real TLD refuses every IP literal, and also 127.1, 2130706433 and 0x7f.0x1, which inet_aton resolves but ipaddress rejects.
    return host if len(labels) >= 2 and _TLD.fullmatch(labels[-1]) else None


class SameHostRedirectHandler(HTTPRedirectHandler):
    """Follow a redirect only to https on the same host; any other target ends the fetch as an HTTPError, its URL kept in refused."""

    def __init__(self, host: str) -> None:
        """Bind the handler to the one host its fetch may reach; one handler per fetch, so refused never carries over."""
        super().__init__()
        self.host = host
        self.refused: str | None = None

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        """Refuse an off-host or non-https target; None makes urllib raise the 3xx as an HTTPError."""
        if not same_host_https(newurl, self.host):
            logging.info("[source-fetch] refused redirect host=%s target=%s", self.host, newurl)
            self.refused = newurl
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open(request: Request, handler: SameHostRedirectHandler, timeout: float):  # noqa: ANN202
    """Open request through handler's redirect policy: the one build_opener call, looked up at call time so a test's stub of this module's build_opener reaches both forms."""
    return build_opener(handler).open(request, timeout=timeout)


def fetch_bounded(host: str, path: str, *, max_bytes: int = FETCH_MAX_BYTES, deadline_seconds: float = FETCH_DEADLINE_SECONDS, budget_at: float | None = None, socket_timeout: float = SOCKET_TIMEOUT_SECONDS, headers: dict[str, str] | None = None) -> bytes:
    """GET https://<host><path> under the rule and return the body; SourceFetchFailed with the reason on a non-200, a refused redirect, a body over max_bytes, a passed deadline (deadline_seconds from now, or the caller's monotonic budget_at when earlier) or a fetch error. headers replace the default accept header."""
    now = time.monotonic()
    # remaining first and the deadline from it: (now + s) - now is not exactly s in floating point, and a caller passing socket_timeout == deadline_seconds must get exactly that timeout.
    remaining = deadline_seconds if budget_at is None else min(deadline_seconds, budget_at - now)
    if remaining <= 0:
        raise SourceFetchFailed("deadline passed")
    deadline = now + remaining
    request = Request(f"https://{host}{path}", headers=headers if headers is not None else {"accept": "application/json, text/vtt"})
    handler = SameHostRedirectHandler(host)
    chunks: list[bytes] = []
    size = 0
    try:
        with _open(request, handler, min(socket_timeout, remaining)) as resp:
            if resp.status != 200:
                raise SourceFetchFailed(f"HTTP {resp.status}")
            length = (resp.headers.get("content-length") or "").strip()
            if length.isdigit() and int(length) > max_bytes:
                raise SourceFetchFailed(f"Content-Length {length} over {max_bytes} bytes")
            while True:
                if time.monotonic() > deadline:
                    raise SourceFetchFailed("deadline passed")
                # read1 returns what has arrived, so a trickling server cannot hold one read open past the deadline for more than one socket timeout.
                chunk = resp.read1(READ_CHUNK_BYTES)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    raise SourceFetchFailed(f"body over {max_bytes} bytes")
                chunks.append(chunk)
    except HTTPError as exc:
        # urllib raises a 4xx/5xx, and a 3xx the handler refused, instead of returning it; caught before OSError so the reason stays distinct. fp may be None on an HTTPError built by hand.
        if exc.fp is not None:
            exc.close()
        raise SourceFetchFailed(f"redirect refused: {handler.refused}" if handler.refused is not None else f"HTTP {exc.code}") from exc
    except _FETCH_ERRORS as exc:
        raise SourceFetchFailed(str(exc) or type(exc).__name__) from exc
    return b"".join(chunks)


def stream_media(url: str, host: str, max_bytes: int, consume: Callable[[bytes], object], stop: threading.Event) -> None:
    """Download url through the same-host redirect policy bound to host (media_host's raw hostname), passing each chunk to consume until EOF or stop is set; SourceFetchFailed on a non-200, a Content-Length or streamed size over max_bytes (checked before consume), or a fetch error. No wall-clock deadline: MEDIA_SOCKET_TIMEOUT_SECONDS is the only stall bound. A BrokenPipeError from consume propagates unchanged."""
    try:
        with _open(Request(url), SameHostRedirectHandler(host), MEDIA_SOCKET_TIMEOUT_SECONDS) as resp:
            if resp.status != 200:
                raise SourceFetchFailed(f"media download failed: HTTP {resp.status}")
            length = (resp.headers.get("content-length") or "").strip()
            if length.isdigit() and int(length) > max_bytes:
                raise SourceFetchFailed(f"media over {max_bytes} bytes")
            size = 0
            while not stop.is_set():
                chunk = resp.read1(READ_CHUNK_BYTES)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    raise SourceFetchFailed(f"media over {max_bytes} bytes")
                consume(chunk)
    except BrokenPipeError:
        # The consumer's pipe closed, not the download; an OSError, so it must pass before the tuple below.
        raise
    except _FETCH_ERRORS as exc:
        # A refused redirect is an HTTPError here too and keeps its "HTTP Error 302: ..." text (TRANSLATE_WORKER.md Error Texts).
        raise SourceFetchFailed(f"media download failed: {exc}") from exc
```

**Invariants and decisions.**
- **Seam.** `_open(request, handler, timeout)` takes the handler. That closes the interface gap the impact inventory flagged. Each form builds a fresh handler per call, so `refused` is per fetch and never shared across Engine handler threads. `stream_media` never reads `refused`.
- **Clock.** The module calls `time.monotonic()` through the `time` module at call time, never `from time import monotonic`, so a test's `time.monotonic` patch reaches it.
- **Deadline arithmetic.** `remaining` is computed before `deadline`. I chose this over the plan's "one `now`" claim: the impact inventory showed that claim is false in floating point. Only this order keeps `min(0.25, 0.25) == 0.25` exact for trending. Under the route's budget, `deadline = now + (budget_at - now)`, which equals `budget_at` to within one ulp.
- **Reason texts.**
  - `HTTP {status}` (a 2xx other than 200) and `HTTP {code}` (a raised 4xx/5xx) deliberately read the same.
  - `redirect refused: <target>` is its own reason.
  - Exception text falls back to the class name when `str(exc)` is empty (e.g. a bare `TimeoutError()`), so a reason is never blank. This is a deliberate small addition. Media keeps raw `{exc}` to stay byte-identical.
- **Exception chaining.** Both forms raise with `from exc`, so the traceback keeps the cause when a caller logs it.
- **Logging.** The one log line stays at INFO, as `[source-fetch] refused redirect …`; it surfaces as event `source_fetch.info`, verbose mode only. Callers log the reasons.

### 2. `engine/server/api/handlers/internal_translate.py`

- **Imports.**
  - Delete `import http.client` and `from urllib.request import HTTPRedirectHandler, Request, build_opener`.
  - **Keep** `from urllib.parse import quote, urlsplit`: `quote` is used in `fetch_instance_track` and `urlsplit` in `_track_path`. Keep `re` and `time`.
  - Add `from data.source_fetch import SourceFetchFailed, fetch_bounded, same_host_https`.
- **Constants.** Delete `FETCH_MAX_BYTES`, `FETCH_DEADLINE_SECONDS`, `SOCKET_TIMEOUT_SECONDS` and `READ_CHUNK_BYTES`. Keep `REQUEST_BUDGET_SECONDS` with its comment; it still holds with the adapter's 4 s socket timeout. Keep `HEARTBEAT_FRESH_MS`.
- **Deleted functions.** `same_host_https`, `SameHostRedirectHandler`, `fetch_bounded` (old :48-108).
- **New private helper and `fetch_instance_track`.** Only the fetch lines change:

```python
def _fetch(host: str, path: str, budget_at: float) -> bytes | None:
    """One instance fetch under the request's budget; None, with the adapter's reason logged, on any failure."""
    try:
        return fetch_bounded(host, path, budget_at=budget_at)
    except SourceFetchFailed as exc:
        logging.info("[translate] instance fetch failed host=%s path=%s: %s", host, path, exc)
        return None


def fetch_instance_track(host: str, video_key: str) -> tuple[str, list[dict[str, Any]]] | None:
    """Read host's caption list for video_key, fetch its first en track and parse it; the track text and cues, or None."""
    budget_at = time.monotonic() + REQUEST_BUDGET_SECONDS
    listing = _fetch(host, f"/api/v1/videos/{quote(video_key, safe='')}/captions", budget_at)
    path = pick_english_track_path(listing, host) if listing is not None else None
    raw = _fetch(host, path, budget_at) if path is not None else None
    ...  # unchanged from here
```

  One wrapper instead of two inline `try` blocks keeps the original three lines and logs the right `path` for each fetch. Every adapter failure becomes the same `None` as before, so every status and body of both routes is unchanged (AC5). The denied-host 404 still answers in `_resolve_translate_key`, before any fetch.
- **`_track_path`.** Unchanged text; `same_host_https` now resolves to the import.
- **Docstring line 7.** Becomes: "Bounds (AC6): every instance fetch goes through the source-instance fetch in `data/source_fetch.py` (https only, to the resolved row's instance_domain only, no redirect off that host, 2 MB per response, an 8 s wall-clock deadline and 4 s per socket operation); this route adds a 15 s budget per request shared by its two fetches. Not bounded by the wall clock: DNS resolution and a TLS handshake stalling across several records; accepted gap."

### 3. `engine/server/db/jobs/translate-worker.py`

- **Drop:**
  - `import http.client` and `import re`;
  - `urlsplit` (keep `quote`);
  - `from urllib.request import Request, build_opener`;
  - `MEDIA_SOCKET_TIMEOUT_SECONDS` and its comment;
  - `_TLD` and its comment;
  - `def media_host`.
- **Imports, replacing :48:**
  - `from data.source_fetch import READ_CHUNK_BYTES, SourceFetchFailed, fetch_bounded, media_host, stream_media`
  - `from handlers.internal_translate import SOURCE_INSTANCE, TARGET_LANGUAGE, fetch_instance_track`
  - `READ_CHUNK_BYTES` stays because `_read` drains ffmpeg's stdout with it.
- **`sys.path` block.** Add a comment over the `api_dir` lines: `# api/ is for server_config, handlers.video.fetch_video_row and the route's fetch_instance_track and constants; fetch code comes from data.source_fetch.`
- **`AudioPipe._feed`:**

```python
    def _feed(self) -> None:
        """Stream the media download into ffmpeg's stdin through stream_media (same-host redirects, the Content-Length precheck and the streamed cap, its failure texts); stdin is closed on every path."""
        try:
            stream_media(self.url, self.host, self.max_bytes, self.proc.stdin.write, self.stop)
        except BrokenPipeError:
            # ffmpeg exited: killed after an error already recorded, or on its own, which _read reports with its exit code and stderr.
            pass
        except SourceFetchFailed as exc:
            self._fail(str(exc))
        finally:
            try:
                self.proc.stdin.close()
            except OSError:
                pass
```

  `self.stop` is the same Event that `_fail` and `close` set. The stop check stays at loop entry, so `close()`'s join is still bounded by one 15 s socket timeout. A `ValueError` from writing to a closed stdin still reads `media download failed: …`, as today.
- **`generate`, replacing :448-455:**

```python
    try:
        raw = fetch_bounded(instance, f"/api/v1/videos/{quote(video_key, safe='')}")
    except SourceFetchFailed as exc:
        raise JobFailed(f"video JSON fetch failed: {exc}") from exc
    try:
        video = json.loads(raw.decode("utf-8"))
    except (ValueError, RecursionError):
        video = None
    if not isinstance(video, dict):
        raise JobFailed("video JSON fetch failed")
```

  The defaults give one 8 s deadline, which equals today's `time.monotonic() + FETCH_DEADLINE_SECONDS`. The "generic by necessity" comment is removed. Example stored texts: `video JSON fetch failed: HTTP 404` and `video JSON fetch failed: redirect refused: https://cdn.example/api/v1/videos/u-1`.

### 4. `engine/server/api/handlers/video.py`

- **Imports.** Drop `from urllib.error import HTTPError, URLError` and `from urllib.request import Request, urlopen`. Keep `quote`. Add `from data.source_fetch import SourceFetchFailed, fetch_bounded`.

```python
def fetch_instance_json(host: str, path: str) -> dict[str, Any] | None:
    """Fetch a JSON object from a PeerTube instance API path through the source-instance fetch (data/source_fetch.py: https, redirects only to the same host over https, 2,000,000 bytes, an 8 s deadline, a 4 s socket timeout); None on a failed fetch (a refused redirect and an over-cap body included), a malformed body or a non-object body."""
    try:
        raw = fetch_bounded(host, path, headers={"accept": "application/json"})
    except SourceFetchFailed as exc:
        logging.info("[video] instance request failed host=%s path=%s: %s", host, path, exc)
        return None
    try:
        data = json.loads(raw.decode("utf-8"))
    except ValueError as exc:
        # UnicodeDecodeError and JSONDecodeError are both ValueError.
        logging.info("[video] instance response is not valid JSON: host=%s path=%s: %s", host, path, exc)
        return None
    if not isinstance(data, dict):
        logging.info("[video] instance response is not a JSON object: host=%s path=%s", host, path)
        return None
    return data
```

- **Side effect, an improvement to record.** `IncompleteRead`, `RemoteDisconnected` or another `OSError` during the body read used to escape and fail the request. They now become None, and the stored row is answered with 200.
- **Unchanged.** `fetch_instance_video_dynamic`, `handle_video_*` and the write-back guard. A normal answer gives the same bytes, so the merge is identical (AC8).

### 5. `engine/server/db/jobs/fetch-trending.py`

- **Imports.** Drop `from urllib.request import Request, urlopen`. Add `from data.source_fetch import SourceFetchFailed, fetch_bounded` after the `sys.path` block, next to the other `data.*` imports.
- **New constant, under `TRENDING_PATH`:**

```python
# Measured <N> bytes for TRENDING_PATH on <largest instance measured> (<YYYY-MM-DD>, identity encoding: urllib sends no Accept-Encoding); the cap leaves at least 4x headroom. Re-measure before raising it.
TRENDING_MAX_BYTES = <round figure ≥ 4 × N>
```

**This value is a build-time gate, not a guess.** Measure with `curl -s 'https://<host>/api/v1/videos?sort=-trending&isLocal=true&count=100&nsfw=both' | wc -c`, without `--compressed`, against several large catalogue hosts (e.g. framatube.org, tilvids.com, and the largest by `video_embeddings` count). Keep the largest. If the build environment has no network, the build stops and asks the operator for the figure.

```python
def fetch_host_list(host: str, timeout_s: float, max_retries: int) -> list[Any] | None:
    """Return a host's trending list (possibly empty), or None when all max_retries + 1 attempts failed."""
    # rat-tail: every failure is retried, 4xx included, with no backoff; a status-code check here if dead hosts stretch the stage.
    for attempt in range(max_retries + 1):
        try:
            # timeout_s bounds each attempt twice: per socket operation and on the wall clock (UPDATER_WORKER.md, Trending Stage).
            body = json.loads(fetch_bounded(host, TRENDING_PATH, max_bytes=TRENDING_MAX_BYTES, deadline_seconds=timeout_s, socket_timeout=timeout_s, headers={"User-Agent": "peertube-browser-trending/1.0"}))
            data = body.get("data") if isinstance(body, dict) else None
            if not isinstance(data, list):
                raise ValueError("body has no data list")
            return data
        # SourceFetchFailed carries the adapter's reason (status, refused redirect, cap, deadline, network); ValueError covers a non-JSON body and one with no data list.
        except (SourceFetchFailed, ValueError) as exc:
            logging.debug("trending fetch host=%s attempt=%d failed: %s", host, attempt + 1, exc)
    return None
```

The request URL is unchanged: `https://{host}{TRENDING_PATH}`. Passing `headers` replaces the default accept, so the request carries only the User-Agent, as today. The loop, the missing backoff and the None contract are unchanged.

### 6. Tests

All network stubbing goes through one patch point: `monkeypatch.setattr(source_fetch, "build_opener", …)` (or `patch.object` in the Engine child), with `from data import source_fetch`. Nothing patches `urlopen` on a caller, and nothing patches `build_opener` in two namespaces.

**`tests/active/test_source_fetch.py` (new).**
- **Helpers.** Imports `Clock`, `Response`, `ScriptedInstance`, `_body`, `HOST`, `TRACK_PATH`, `TRACK_URL`, `WITHIN_CAP`, `OVER_CAP` and `REFUSED_TARGETS` from `test_internal_translate`. It has its own `scripted_instance` fixture that patches `time.monotonic` and `source_fetch.build_opener`.
- **`ScriptedInstance.open` gains one line:** `self.timeouts.append(req.timeout)` (initialised in `__init__`).
- **Moved cases, asserting `pytest.raises(SourceFetchFailed, match=…)` where they asserted None:**
  - handler follows same-host 301/302/303/307/308;
  - handler refuses each REFUSED_TARGET and sets `.refused`;
  - follows a redirect, absolute and relative;
  - a refused redirect raises `redirect refused: <target>`, with `opened == [TRACK_URL]`;
  - declared over cap raises `Content-Length 2097153 over 2000000 bytes` with zero reads;
  - streamed over cap raises `body over 2000000 bytes`;
  - 2,000,000 bytes come back whole, declared and streamed;
  - per-fetch deadline and request budget each raise `deadline passed`;
  - seven 1 s chunks come back whole;
  - a spent budget raises `deadline passed` and opens nothing.
- **New buffered cases:**
  - a returned 204 raises `HTTP 204`;
  - an unserved path raises `HTTP 404`;
  - an exception raised from the open step raises its text;
  - with no overrides, the request carries `get_header("Accept") == "application/json, text/vtt"` and `timeouts == [4.0]`;
  - `budget_at=clock.now + 1.0` gives `timeouts == [1.0]`;
  - the overrides `max_bytes`, `deadline_seconds`, `socket_timeout` and `headers` each take effect, with headers replacing accept;
  - a refused-redirect fetch followed by an unserved path raises `HTTP 404`, not `redirect refused` (no leak).
- **`media_host`.** https host → raw hostname, including a mixed-case host returned lowercased by urlsplit; each refused form → None. The worker's REFUSED_FILES and PICKS cases remain the full table.
- **`stream_media`:**
  - non-200 raises `media download failed: HTTP 204`;
  - declared over cap raises `media over N bytes` with zero reads;
  - streamed over cap raises it with nothing consumed past the cap;
  - an off-host redirect raises text starting `media download failed: HTTP Error 302`, target never opened;
  - a set `stop` reads nothing more;
  - a consumer raising `BrokenPipeError` propagates as `BrokenPipeError`;
  - `timeouts == [15.0]`.

**`tests/active/test_internal_translate.py`.**
- `_translate(instance)` patches `data.source_fetch.build_opener`.
- The direct fetch and handler cases (:349-430) move out.
- `RecordingInstance` is rebuilt by composition over `ScriptedInstance`, keeping its public shape:

```python
class RecordingInstance:
    """The video instances behind the adapter's build_opener: each served (host, path) answers its bytes, an unserved one 404 (a failed fetch), and every URL opened is recorded in order."""

    def __init__(self) -> None:
        self.scripted = ScriptedInstance(Clock(), None)

    def serve(self, video: tuple[str, str, str], listing: bytes | None, track: bytes | None) -> None:
        _, uuid, host = video
        for path, body in ((f"/api/v1/videos/{uuid}/captions", listing), (TRACK_PATH, track)):
            if body is not None:
                self.scripted.serve(f"https://{host}{path}", chunks=[body])

    @property
    def fetched(self) -> list[tuple[str, str]]:
        return [(parts.hostname, parts.path + (f"?{parts.query}" if parts.query else "")) for parts in map(urlsplit, self.scripted.opened)]

    def hosts(self) -> list[str]:
        return [host for host, _ in self.fetched]


def _handler_module(instance: RecordingInstance, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """The handler module, imported inside each test so that a missing module fails each test on its own; the adapter's fetch reaches the recording instance."""
    monkeypatch.setattr(importlib.import_module("data.source_fetch"), "build_opener", instance.scripted.build_opener)
    return importlib.import_module("handlers.internal_translate")
```

  In NONE_PATHS, a `None` entry is an unserved route, which fails with 404. That is the same None path and the same fetch count as before. The docstring changes at lines 12-21 and 49.

**`tests/active/test_translate_worker.py`.**
- `Rig.__init__` replaces the two `setattr` calls (:507-508) with one: `monkeypatch.setattr(importlib.import_module("data.source_fetch"), "build_opener", _dispatching_opener(self.instance, self.media))`.

```python
def _dispatching_opener(instance: ScriptedHost, media: ScriptedHost):
    """One build_opener for both scripted hosts: a URL goes to the host that serves it, else by request host (peer.example to the instance, any other to the media host), so a followed cdn.example redirect shows in the opened list of the host that served it."""
    def build_opener(*handlers: object) -> urllib.request.OpenerDirector:
        def owner(req: Request) -> ScriptedHost:
            return next((host for host in (instance, media) if req.full_url in host.routes), instance if req.host == HOST else media)

        class DispatchHTTPS(HTTPSHandler):
            def https_open(self, req: Request) -> Response:
                return owner(req).open(req)

        class DispatchHTTP(HTTPHandler):
            def http_open(self, req: Request) -> Response:
                return owner(req).open(req)

        return urllib.request.build_opener(DispatchHTTPS(), DispatchHTTP(), *[handler for handler in handlers if not _socket_handler(handler)])
    return build_opener
```

  A fresh real opener is built per call around the adapter's real `SameHostRedirectHandler`. Both `cdn.example` targets are routed to the host that served them, so "target never requested" stays a recorded-URL assertion. `ScriptedHost.build_opener` is now unused and is deleted.
- The docstring changes at :10 (one dispatcher on `data.source_fetch.build_opener`) and :15 (`video JSON fetch failed: redirect refused: …`).
- The BOUNDS assertions are unchanged; `_error_leads` already accepts the suffix.

**`tests/active/test_video.py`.**

```python
class _FakeResponse(io.BytesIO):
    """One instance response as urllib's https open step hands it on: status, headers and a body read in chunks."""

    def __init__(self, body: bytes, status: int = 200, headers: dict[str, str] | None = None):
        super().__init__(body)
        self.code = self.status = status
        self.msg = "Scripted"
        self.headers = HTTPMessage()
        for name, value in (headers or {}).items():
            self.headers[name] = value

    def info(self) -> HTTPMessage:
        return self.headers
```

- **`_serve(monkeypatch, bodies)`** keeps its contract: the lookup key is the path on `PEER_HOST`, else the full URL, and it returns `(url, timeout)` per call. It now patches `source_fetch.build_opener` with a function that builds a real opener around a scripted `HTTPSHandler`. Its `https_open` records `(req.full_url, req.timeout)`, raises exceptions, returns a `_FakeResponse` as is, and wraps bytes or JSON in one.
- **Status cases.** `status-404` now goes through urllib's error processor and raises `HTTP 404`. It is still None.
- **Renamed id.** `urlopen-urlerror` becomes `open-urlerror`; the same rename applies at :701.
- **Timeouts.** `(VIDEO_URL, 8)` becomes `(VIDEO_URL, 4)` at :422 and :506.
- **PERSIST_CHILD.** After `import server`, it does `from data import source_fetch`. `refusing` becomes a `build_opener` stub whose https step records `[req.host, req.selector]` and raises `URLError("instance down")`. It is applied with `patch.object(source_fetch, "build_opener", refusing_opener)`. The recorded calls stay `[[HOST, DETAIL_PATH]]`.
- **New in-process cases:**
  - `VIDEO_PATH` answers 302 to `https://cdn.example/api/v1/videos/uuid-1`, and that URL is served SOURCE. Expect 200 with the stored title and the rest, `_snapshot` unchanged, and calls equal to `[(VIDEO_URL, 4)]`, so the target was never requested.
  - Over cap: a declared `Content-Length` of 2,000,001 and a streamed 2,000,001-byte body each give the same stored-row answer and an unchanged snapshot.
- **Docstring.** Changes at :9, :11, :29 and :32.

**`tests/active/test_fetch_trending.py`.**
- `_Response(io.BytesIO)` gains `code`, `msg`, `headers` (`HTTPMessage`, with optional entries) and `info()`.
- `_fake_urlopen` becomes `_scripted(outcomes)`. It returns `(build_opener, attempts)`. Its https step records `(req.full_url, req.timeout, req.get_header("User-agent"))` and pops one outcome per attempt: it raises an exception, returns a `_Response` as is, and wraps bytes. The tests patch `source_fetch.build_opener`.
- Assertions become `[(TRENDING_URL, 0.25, "peertube-browser-trending/1.0")] * n`. They stay exact because `remaining == deadline_seconds` when no budget is passed.
- FAILURES are unchanged as objects. The `HTTPError`s with `fp=None` raise `HTTP 500`/`HTTP 400` through the guarded close.
- **New cases, each with a control:**
  - **Redirect:** a 302 to `https://cdn.example/…` on every attempt gives None after 3 attempts, all at `TRENDING_URL` (target never requested). The control is a same-host 302 to `https://tube.example/moved`, which is served a list and returns it.
  - **Over cap:** a body of `TRENDING_MAX_BYTES + 1` gives None after 3 attempts; the control is a JSON list padded to exactly `TRENDING_MAX_BYTES`, which is returned.
  - **Deadline:** `time.monotonic` is patched to tick 1.0 per call, so `timeout_s=0.25` passes before the first read on every attempt and gives None after 3 attempts. The control is the same body with a frozen clock, which is returned.
- The docstring changes at :6 and :10.

**`tests/config.json`.**
- Add a group for `test_source_fetch.py`: `engine/server/data/source_fetch.py`, `engine/server/data/moderation.py`, `tests/active/test_internal_translate.py`. The last entry is there because of the imported helpers.
- Add `engine/server/data/source_fetch.py` to the groups of `test_video.py`, `test_fetch_trending.py`, `test_internal_translate.py` and `test_translate_worker.py`.

`tests/last_test_validation.json` is regenerated by the validation run, never hand-edited.

`tests/tmp/probe_50_phase1_rows.py` keeps working: `RecordingInstance()`, `.serve`, `.fetched`, `.hosts()` and `_handler_module(instance, monkeypatch)` keep their shapes.

### 7. Docs (the settled list, with the wording)

- **`engine/server/README.md`.**
  - :9 — `/api/video` calls go through `data/source_fetch.py`: https only, redirects only to the same host over https, 2,000,000 bytes, an 8 s deadline and a 4 s socket timeout per call.
  - :11 — a refused redirect or an over-cap body is a failed detail call: nothing is written and the stored row is answered.
  - :21 — the bounds live in `data/source_fetch.py`; the 15 s two-fetch budget is the route's own.
- **`TRANSLATE_WORKER.md`.**
  - :91 and :107 — "B1's `fetch_bounded`" becomes the adapter `data/source_fetch.py` with its default bounds.
  - :118 and the Media File Choice bullets — URL acceptance and the same-host rule live in the adapter's `media_host` and `stream_media`.
  - :137 — `video JSON fetch failed: <reason>` (e.g. `HTTP 404`, `redirect refused: …`); the bare text is only for a body that is not a JSON object.
  - :96 and :138 — the values and texts are unchanged and live in the adapter.
- **`UPDATER_WORKER.md`.**
  - Trending Stage :94 — the adapter; `TRENDING_MAX_BYTES` with its measured basis; `--timeout-ms` is both the socket timeout and the per-attempt wall-clock deadline; "non-2xx" becomes non-200; a redirect off the host or off https and a body over the cap each fail the attempt and are retried.
  - :110 — the DEBUG line carries the adapter's reason.
- **`CONTEXT.md` :20.** "Every source-instance fetch goes through the adapter in `data/source_fetch.py`: the translate route, the translate worker, `/api/video` and the trending job. `/api/video` serves the stored row when the metadata fetch fails, a refused redirect or an over-cap body included."
- **`video.py`** — `fetch_instance_json` docstring as drafted above.
- **`internal_translate.py`** — docstring line 7 as drafted above.
- **`DEPLOYMENT.md` :751** — outbound 443 from `/api/video` and the trending stage follows the same https-only, same-host-redirect, capped rule as the translate fetches.
- **`client/backend/server.py` :86** — comment: "up to two instance calls, each with an 8 s deadline and a 4 s socket timeout". The value is unchanged.
- **Issue 53** — on delivery, `Status:` becomes `complete` and the file moves to `docs/project/issues/archive/`.

### Check against plan and requirements (pass 1 converged)

- **AC1.** Holds. The URL checks, redirect policy, constants, deadlines and reasons exist only in `source_fetch.py`. A grep for `urlopen|build_opener` in the four callers finds nothing.
- **AC2.** Holds. The worker's route import is `SOURCE_INSTANCE, TARGET_LANGUAGE, fetch_instance_track` only.
- **AC3.** Holds. The reasons are `HTTP n`, `Content-Length n over cap bytes`, `body over cap bytes`, `deadline passed` (before and during the read), `redirect refused: url` and the exception text. With no overrides, the bounds, header, success cases and failure cases equal the old `fetch_bounded`.
- **AC4.** Holds: `video JSON fetch failed: <reason>`.
- **AC5.** Holds. `_fetch` turns every failure into the old None, and the denied-host 404 is untouched.
- **AC6.** Holds: same texts, 15 s timeout, precheck, streamed cap, no deadline, BrokenPipe passed through, stdin closed in `finally`.
- **AC7 and AC8.** Hold, with new test_video cases. A normal answer gives the same bytes and the same merge.
- **AC9.** Holds: cap, deadline and socket timeout of `timeout_s`, and new cases.
- **AC10.** Holds: one patch point, `source_fetch.build_opener`.
- **AC11.** Holds: section 7.

**Where this draft departs from the high-level plan's wording.** Each change comes from the settled inventory or is internal to the plan:
1. The deadline is `remaining`-first; the plan's single-`now` claim is wrong in floating point.
2. `_open` takes the handler, so `refused` is readable.
3. The route keeps `urlsplit` and `quote`; the plan said "deletes its urllib imports".
4. The route's two `try` blocks are one private `_fetch` wrapper.
5. Empty exception text falls back to the class name in the buffered form only.

**Accepted limitations, already in the plan.**
- Mixed-case stored `instance_domain` values lose same-host redirects on `/api/video` and trending. The function moves word for word; this is flagged, not changed.
- DNS and TLS stalls are still not bounded by the wall clock.
- Two `/api/video` calls can still exceed the Client's 20 s proxy budget.
- `TRENDING_MAX_BYTES` must be measured in the build, and the build stops for the operator without network access.
- `RecursionError` in `fetch_instance_json` is a pre-existing gap and is left alone.

### Phases

#### Phase 1 - Source-fetch adapter [code]

**Files touched.** engine/server/data/source_fetch.py (NEW), tests/active/test_source_fetch.py (NEW), tests/active/test_internal_translate.py (EDITED: ScriptedInstance.timeouts), tests/config.json (EDITED)

**Checkpoint.** Seam: the adapter's public functions, called directly (rung 1). The network is severed at the module's single patch point, `data.source_fetch.build_opener`, with the existing harness in tests/active/test_internal_translate.py: `Clock` patched into `time.monotonic`, plus `ScriptedInstance`/`Response` and the `_body`, HOST, TRACK_URL, WITHIN_CAP, OVER_CAP and REFUSED_TARGETS helpers. `ScriptedInstance` gains one field, `timeouts`, which records `req.timeout`. New file tests/active/test_source_fetch.py has its own `scripted_instance` fixture. C1 asserts `pytest.raises(SourceFetchFailed, match=…)` once per reason row, each with its exact text: `HTTP 204` for a returned 204; `HTTP 404` for an unserved path; `redirect refused: <target>` with `opened == [TRACK_URL]`; `Content-Length 2097153 over 2000000 bytes` with zero reads; `body over 2000000 bytes`; `deadline passed` for the per-fetch deadline, for the request budget, and for a spent budget with nothing opened; and the exception text for an error raised at open. Each case names the wrong implementation it excludes: a collapsed or blank reason, a reason that leaks across fetches (a refused redirect followed by a 404 must read `HTTP 404`), or a read past the cap. C1 also asserts that a call with no overrides sends Accept `application/json, text/vtt` with `timeouts == [4.0]`, that `budget_at=now+1.0` gives `timeouts == [1.0]`, and that each override (max_bytes, deadline_seconds, socket_timeout, headers replacing accept) takes effect, with 2,000,000 bytes and seven 1 s chunks coming back whole. C2 asserts `stream_media`'s texts byte for byte: `media download failed: HTTP 204`; `media over N bytes` from the precheck with zero reads; the same text from the streamed cap with nothing consumed past the cap; and an off-host redirect starting `media download failed: HTTP Error 302` with the target never opened. It also asserts that a set `stop` reads nothing more, that a consumer's BrokenPipeError propagates as BrokenPipeError, and that `timeouts == [15.0]`. The moved handler cases (follows same-host 301/302/303/307/308, refuses each REFUSED_TARGET and sets `.refused`) and the `media_host` cases (raw lowercased hostname, None for each refused form) sit in the same file.

**Intent.** `engine/server/data/source_fetch.py` exists as the one stdlib-only source-instance fetch: its `fetch_bounded` returns a body or raises `SourceFetchFailed` naming why, under today's default bounds, and its `stream_media` feeds a consumer chunk by chunk under today's media failure texts.

- C1 - `fetch_bounded` raises `SourceFetchFailed` carrying a distinct reason for each failure case, and with no overrides it applies today's bounds and accept header.
- C2 - `stream_media` raises today's media failure texts unchanged and passes a consumer's BrokenPipeError through as itself.

**Outcome.** ### engine/server/data/source_fetch.py (NEW)

This is the stdlib-only source-instance fetch adapter. It takes the plan's Step 6 draft as written, without the probe's `MUTATION` hooks. Its only in-repo import is `data.moderation.normalize_host`.

- **Constants:**
  - `FETCH_MAX_BYTES` 2_000_000, `FETCH_DEADLINE_SECONDS` 8.0, `SOCKET_TIMEOUT_SECONDS` 4.0 and `READ_CHUNK_BYTES` 65_536, copied from `internal_translate.py`.
  - `MEDIA_SOCKET_TIMEOUT_SECONDS` 15.0 and the private `_TLD` regex, copied from `translate-worker.py` with their comments.
  - `_FETCH_ERRORS = (OSError, ValueError, http.client.HTTPException)`, the exception set both forms catch.
- **`SourceFetchFailed(Exception)`:** its message is the short reason.
- **`same_host_https(url, host)` and `media_host(url)`:** moved word for word from the route and the worker. `media_host` still returns the raw `urlsplit` hostname.
- **`SameHostRedirectHandler(host)`:** moved from the route. It now records a refused target in `self.refused`. Its INFO log line now starts `[source-fetch] refused redirect …`. As before, it returns None, so urllib raises the 3xx as an `HTTPError`.
- **`_open(request, handler, timeout)`:** the one place that calls `build_opener`. It looks the name up as a module global at call time, so `source_fetch.build_opener` is the single patch point for both forms. It takes the handler as an argument, so each fetch builds its own: `refused` is read for that fetch only and is never shared across threads or fetches.
- **`fetch_bounded(host, path, *, max_bytes, deadline_seconds, budget_at=None, socket_timeout, headers=None) -> bytes`:**
  - The time left is worked out first (`deadline_seconds`, or `min(deadline_seconds, budget_at - now)` when a budget is given), and the deadline is `now` plus that. This keeps a socket timeout equal to `deadline_seconds` exact, as trending will pass in Phase 4.
  - It raises `deadline passed` before opening anything when no time is left.
  - It sends `accept: application/json, text/vtt` unless `headers` replaces it, and opens with socket timeout `min(socket_timeout, remaining)`.
  - Reasons raised:
    - `HTTP {status}` for a returned status other than 200.
    - `Content-Length {n} over {cap} bytes`, with no body read.
    - `deadline passed`, checked between `read1` chunks.
    - `body over {cap} bytes`.
    - `redirect refused: {target}` or `HTTP {code}` for an `HTTPError`. This is caught before the general set, and its `fp` is closed only when present.
    - Otherwise the exception's own text, or its class name when that text is empty.
- **`stream_media(url, host, max_bytes, consume, stop) -> None`:** the body of today's `AudioPipe._feed` without the stdin handling.
  - It uses a 15 s socket timeout and has no wall-clock deadline.
  - It checks `stop` at the top of each loop and checks the size before calling `consume`.
  - Failure texts are today's, unchanged: `media download failed: HTTP {status}`, `media over {max_bytes} bytes` (for both the declared length and the streamed body), and `media download failed: {exc}`. A refused redirect therefore still reads `HTTP Error 302: …`.
  - A `BrokenPipeError` is re-raised as itself before the general exception set is caught.

### Files listed for this phase but not changed

- **`tests/active/test_internal_translate.py` (`ScriptedInstance.timeouts`):** not needed. The checkpoint's own `SourceInstance` records `socket_timeouts` itself, and its comment says this is so it does not depend on that edit.
- **`tests/active/test_source_fetch.py` and the new `tests/config.json` group for it:** no active test file uses the adapter yet. I left both for the step that moves the checkpoint into `tests/active`, rather than writing a duplicate test or a config entry pointing at a file that does not exist. Adding `source_fetch.py` to the dependent suites' groups belongs with Phases 2–4, when those callers start importing it.

I did not run the checkpoint, as instructed. The module is the plan's draft, which the checkpoint's own probe (`probe_53_draft_source_fetch.py`) exercised.

#### Phase 2 - Translate route and worker on the adapter [code]

**Files touched.** engine/server/api/handlers/internal_translate.py (EDITED), engine/server/db/jobs/translate-worker.py (EDITED), tests/active/test_internal_translate.py (EDITED), tests/active/test_translate_worker.py (EDITED), tests/config.json (EDITED)

**Checkpoint.** Seam 1 is the route handler, entered through the existing harness: `_handler_module(instance, monkeypatch)` and `RecordingInstance`, which is rebuilt by composition over `ScriptedInstance` and keeps `.serve`, `.fetched` and `.hosts()`. Stubbing moves to `data.source_fetch.build_opener`. The existing gate, store, job-state, PICK_REFUSED and NONE_PATHS cases run unchanged over the real adapter (an unserved path is the old None). Each asserts the same status, body and fetch sequence as before, which shows the shared 15 s budget and the denied-host 404 before any fetch. One added assertion: a failed fetch logs `[translate] instance fetch failed host=… path=…: <reason>`. The direct fetch/handler cases leave this file; they are now in P1. Seam 2 is the worker's `generate`/`AudioPipe`, entered through the existing `Rig`. Its two `build_opener` patches become one `_dispatching_opener(instance, media)` on `data.source_fetch.build_opener`, and `ScriptedHost.build_opener` is deleted. The BOUNDS cases assert the stored error text, e.g. `video JSON fetch failed: HTTP 404` and `video JSON fetch failed: redirect refused: https://cdn.example/…`. A non-object body stores the bare `video JSON fetch failed`. REFUSED_FILES/PICKS and the media outcome cases keep their exact texts, and the cdn.example target is never recorded as opened. The startup test still starts the Engine with the new import chain.

**Intent.** The translate route and the translate worker fetch only through `data.source_fetch`. The route's own constants, URL check, redirect handler and `fetch_bounded` are deleted, and its answers are unchanged. The worker imports no fetch code from the route and stores a failed video-JSON fetch with the adapter's reason.

- C1 - Every translate-route status and body is unchanged with its instance fetches going through the adapter.
- C2 - The worker stores a failed video-JSON fetch as `video JSON fetch failed: <reason>`.

**Outcome.** ### engine/server/api/handlers/internal_translate.py
- **Deleted:** `FETCH_MAX_BYTES`, `FETCH_DEADLINE_SECONDS`, `SOCKET_TIMEOUT_SECONDS`, `READ_CHUNK_BYTES`, `same_host_https`, `SameHostRedirectHandler`, `fetch_bounded`, and the `http.client` and `urllib.request` imports. Its `[translate] response over cap` and `[translate] fetch deadline passed` log lines go with them.
- **Kept:** `urllib.parse.quote`/`urlsplit`, `REQUEST_BUDGET_SECONDS` with its comment, `HEARTBEAT_FRESH_MS`, `SOURCE_INSTANCE` and `TARGET_LANGUAGE`.
- **Added:** the import `from data.source_fetch import SourceFetchFailed, fetch_bounded, same_host_https`. `_track_path` keeps its text and now calls the adapter's `same_host_https`.
- **New private `_fetch(host, path, budget_at)`:** calls `fetch_bounded(host, path, budget_at=budget_at)`. On `SourceFetchFailed` it logs `[translate] instance fetch failed host=%s path=%s: <reason>` at INFO and returns None.
- **`fetch_instance_track`:** uses `_fetch` for both the caption list and the track, under one `budget_at = time.monotonic() + REQUEST_BUDGET_SECONDS`. Everything after the fetches is unchanged, so every status and body of both routes is unchanged. The denied-host 404 is still answered in `_resolve_translate_key`, before any fetch.
- **Module docstring:** the "Bounds (AC6)" paragraph now says the per-fetch bounds live in `data/source_fetch.py`, and keeps the route's own 15 s two-fetch budget and the accepted DNS/TLS gap.

### engine/server/db/jobs/translate-worker.py
- **Dropped:** `import http.client`, `import re`, `urlsplit` (`quote` kept), `from urllib.request import Request, build_opener`, `MEDIA_SOCKET_TIMEOUT_SECONDS`, `_TLD` and the worker's own `media_host`.
- **Imports:** added `from data.source_fetch import READ_CHUNK_BYTES, SourceFetchFailed, fetch_bounded, media_host, stream_media`. `READ_CHUNK_BYTES` is still used by `_read` to drain ffmpeg's stdout. The route import is down to `SOURCE_INSTANCE, TARGET_LANGUAGE, fetch_instance_track`.
- **`sys.path` block:** a new comment above the `api_dir` lines says what `api/` is still needed for (`server_config`, `handlers.video.fetch_video_row`, the route's `fetch_instance_track` and constants) and that fetch code now comes from `data.source_fetch`.
- **`AudioPipe._feed`:** now calls `stream_media(self.url, self.host, self.max_bytes, self.proc.stdin.write, self.stop)`.
  - `BrokenPipeError` is ignored, as before.
  - `SourceFetchFailed` becomes `self._fail(str(exc))`.
  - stdin is still closed in `finally`.
  - The media failure texts are the adapter's, which are byte-identical to the old ones.
- **`generate`:** the video-JSON fetch is `fetch_bounded(instance, path)` with the defaults (one 8 s deadline).
  - `SourceFetchFailed` becomes `JobFailed(f"video JSON fetch failed: {exc}")`.
  - A body that does not decode to a JSON object still raises the bare `JobFailed("video JSON fetch failed")`.
  - The stale "generic by necessity" comment is gone.

### tests/active/test_internal_translate.py
- **Retired:** the direct fetch cases that called the route's `SameHostRedirectHandler` and `fetch_bounded`, which no longer exist: the redirect handler, follow/refuse redirect, cap, deadline/budget and spent-budget cases. The `scripted_instance` fixture that only they used is retired too. Phase 1's checkpoint covers the same behaviour against `data.source_fetch`, with reasons. `_translate()` loses its unused `instance` parameter.
- **`RecordingInstance`:** rebuilt by composition over `ScriptedInstance`. `.serve(video, listing, track)` serves each non-None body, so None now means an unserved URL, which answers 404. `.fetched` is derived from the opened URLs as (hostname, path) and `.hosts()` is unchanged, so the existing handler cases keep their exact assertions.
- **`_handler_module`:** patches `data.source_fetch.build_opener` with the instance's opener.
- **Other edits:** added `from urllib.parse import urlsplit`, reworded the NONE_PATHS comment, and updated the module docstring for the fetch section and the handler harness.
- **Kept:** every name the phase 1 and phase 2 checkpoints import (`Clock`, `Response`, `ScriptedInstance`, `_socket_handler`, `_body`, `CHUNK`, `WITHIN_CAP`, `OVER_CAP`, `REFUSED_TARGETS`, …).

### tests/active/test_translate_worker.py
- **Removed:** `ScriptedHost.build_opener`.
- **New `_dispatching_opener(instance, media)`:** a single `build_opener` that routes each URL to the host serving it, and otherwise by request host (peer.example to the instance, anything else to the media host). It builds a real urllib opener around the adapter's handlers.
- **`Rig.__init__`:** its two patches (the route's and the worker's `build_opener`) become one, on `data.source_fetch.build_opener`.
- **Module docstring:** updated the stubbing description and the video-JSON redirect text, which is now `video JSON fetch failed: redirect refused: ...`. The BOUNDS assertions are unchanged; `_error_leads` already accepts the `: <reason>` suffix.

### tests/config.json
- Added `engine/server/data/source_fetch.py` to the `test_internal_translate.py` and `test_translate_worker.py` groups.

### tests/tmp/probe_53_phase2_impl.py (probe)
- This is an import probe. It showed that the route and the worker script load, that `route.fetch_bounded is source_fetch.fetch_bounded`, and that `worker.media_host is source_fetch.media_host`. I have no delete tool, so it is still on disk. Please delete it.

#### Phase 3 - /api/video on the adapter [code]

**Files touched.** engine/server/api/handlers/video.py (EDITED), tests/active/test_video.py (EDITED), tests/config.json (EDITED)

**Checkpoint.** Seam: the `/api/video` handlers, through test_video.py's existing harness. In process, `_serve(monkeypatch, bodies)` keeps its contract but now patches `data.source_fetch.build_opener` with a real opener around a scripted HTTPSHandler that records `(full_url, timeout)`. In the Engine child, PERSIST_CHILD switches to `patch.object(source_fetch, "build_opener", refusing_opener)`, and its recorded calls stay `[[HOST, DETAIL_PATH]]`. New cases cover three inputs: VIDEO_PATH answering 302 to `https://cdn.example/api/v1/videos/uuid-1` (that URL is served SOURCE), a declared Content-Length of 2,000,001, and a streamed 2,000,001-byte body. Each case asserts 200, the stored row's fields, an unchanged `_snapshot`, and calls equal to `[(VIDEO_URL, 4)]`. That last assertion is what shows the redirect target was never requested. The existing cases still assert the normal-answer merge, with the timeout now 4; `urlopen-urlerror` is renamed `open-urlerror`.

**Intent.** `video.fetch_instance_json` fetches through `data.source_fetch.fetch_bounded` instead of `urlopen`, so a redirect off the instance or an over-cap body becomes a failed detail call answered from the stored row.

- C1 - A cross-host redirect or an over-cap body on `/api/video` is answered with the stored row, DB unchanged, without requesting the redirect target.

**Outcome.** ### engine/server/api/handlers/video.py
- **Imports:** removed `from urllib.error import HTTPError, URLError` and `from urllib.request import Request, urlopen`, kept `quote`, and added `from data.source_fetch import SourceFetchFailed, fetch_bounded`.
- **`fetch_instance_json(host, path)`:** now calls `fetch_bounded(host, path, headers={"accept": "application/json"})` with the adapter's default limits: 2,000,000 bytes, an 8 s deadline, a 4 s socket timeout (it was 8 s), and redirects followed only to https on the same host.
  - On `SourceFetchFailed` it logs `[video] instance request failed host=%s path=%s: <reason>` at INFO and returns None. A cross-host redirect or an over-cap body therefore becomes a failed detail call, and `/api/video` answers from the stored row without writing anything. The redirect target is never requested.
  - The UTF-8 decode, the `json.loads` `ValueError` handler and the dict check are unchanged. A non-200 status now arrives as `HTTP <code>` from the adapter instead of a separate status check.
  - The docstring now states these limits.
- **Side effect:** `IncompleteRead`, `RemoteDisconnected` and other read errors used to escape and fail the request. The adapter now catches them, so the stored row is answered. The plan expected this.
- `fetch_instance_video_dynamic`, the `handle_video_*` functions and the write-back guard are unchanged.

### tests/active/test_video.py
This file's harness patched `video.urlopen`, which no longer exists. Without these edits every in-process write-guard case and the `urlopen-urlerror` Engine-child case would fail on an `AttributeError`.
- **Imports:** added `io`, `http.client.HTTPMessage`, `urllib.request.HTTPSHandler, build_opener` and `from data import source_fetch`.
- **`_FakeResponse`:** now an `io.BytesIO` subclass with `code`/`status`, `msg`, `headers` (an `HTTPMessage`) and `info()`, as written in the plan. It provides the `read1`, context-manager and close methods that urllib and the adapter use.
- **`_serve(monkeypatch, bodies)`:** keeps the same lookup and the same `(url, timeout)` return. It now patches `source_fetch.build_opener` with a real urllib opener that puts a scripted `HTTPSHandler` in front of the adapter's own handlers. `status-404` now goes through urllib's error processor, and its result is still None.
- **Timeouts:** `(VIDEO_URL, 8)` became `(VIDEO_URL, 4)` in `test_fetch_failure_leaves_db_untouched` and `test_object_body_counts_as_success`. The plan accepted this change.
- **Renamed id:** `urlopen-urlerror` became `open-urlerror` in both places it appears.
- **PERSIST_CHILD:** it now imports `from data import source_fetch`. `refusing` became a `Refusing` opener whose `open` records `[req.host, req.selector]` and raises `URLError("instance down")`, applied with `patch.object(source_fetch, "build_opener", lambda *handlers: Refusing())`. The recorded calls are still `[[HOST, DETAIL_PATH]]`.
- **Module docstring:** the lines describing the write-guard harness, the refused-refresh case and the stubbing paragraph now name the adapter's opener instead of `urlopen`.
- Every name the checkpoint imports from this file is unchanged.

### tests/config.json
- Added `engine/server/data/source_fetch.py` to the `test_video.py` group. Also added `engine/server/data/moderation.py`, which `source_fetch.py` imports, so `video.py` now depends on it too. The plan named only `source_fetch.py`.

Not run, as the step requires. I did not run `test_video.py` through `ValidateTests` either, because that would record a fingerprint for its group mid-build. Two things in its new harness are therefore unconfirmed: the 404 path (a `_FakeResponse` wrapped and closed by `HTTPError`) and the `Refusing` stub. The workflow's run of `test_video.py` will confirm them.

#### Phase 4 - Trending fetch on the adapter [code]

**Files touched.** engine/server/db/jobs/fetch-trending.py (EDITED), tests/active/test_fetch_trending.py (EDITED), tests/config.json (EDITED)

**Checkpoint.** Seam: `fetch_host_list(host, timeout_s, max_retries)`, called directly through test_fetch_trending.py's existing harness. `_fake_urlopen` becomes `_scripted(outcomes)` on `data.source_fetch.build_opener`; it records `(full_url, timeout, User-Agent)` and pops one outcome per attempt. The existing success, retry and FAILURES cases assert `[(TRENDING_URL, 0.25, "peertube-browser-trending/1.0")] * n` exactly. C1 has two new cases, each with a control. An off-host 302 to cdn.example on every attempt gives None after 3 attempts, all at TRENDING_URL; the control, a same-host 302 to tube.example/moved, returns the list. A body of TRENDING_MAX_BYTES + 1 gives None after 3 attempts; the control, padded to exactly TRENDING_MAX_BYTES, is returned. C2: with `time.monotonic` ticking 1.0 per call and timeout_s=0.25, every attempt fails on the deadline and the result is None after 3 attempts; the control, the same body with a frozen clock, is returned.

**Intent.** `fetch-trending.fetch_host_list` fetches each attempt through `data.source_fetch.fetch_bounded` under a measured `TRENDING_MAX_BYTES` with `timeout_s` as both socket timeout and per-attempt deadline. An attempt that breaks the adapter's rule fails and is retried, and `timeout_s` now bounds each attempt on the wall clock.

- C1 - An attempt answered with an off-host redirect or a body over `TRENDING_MAX_BYTES` fails and is retried, ending in None.
- C2 - An attempt whose wall-clock time passes `timeout_s` fails on the deadline and is retried.

**Outcome.** ### engine/server/db/jobs/fetch-trending.py
- **Imports:** dropped `from urllib.request import Request, urlopen`. Added `from data.source_fetch import SourceFetchFailed, fetch_bounded` after the `sys.path` block, with the other `data.*` imports.
- **New constant `TRENDING_MAX_BYTES = 2_500_000`,** placed under `TRENDING_PATH`. Its comment records the measured basis:
  - I measured on 2026-10-04 with a `tests/tmp` probe run through `ValidateTests`. It used urllib, which sends no Accept-Encoding, so it matches `curl | wc -c` without `--compressed`.
  - Hosts were framatube.org, tilvids.com and the top 15 hosts by `video_embeddings` count from the worktree's `whitelist.db`.
  - The largest page was **461,632 bytes, from peertube.dngr.us**. framatube.org was 454,433, video.hardlimit.com 437,965, indymotion.fr 433,901 and makertube.net 431,449. All the others were between 287k and 398k.
  - tilvids.com timed out after 30 s, so it is not in the figures.
  - Four times the largest is 1,846,528. I picked 2,500,000 (about 5.4×) instead of 2,000,000 because 2,000,000 is also the adapter's default cap. With the default value, the checkpoint's at-cap control could not tell whether `max_bytes` is actually passed.
- **`fetch_host_list`:** each attempt is now `json.loads(fetch_bounded(host, TRENDING_PATH, max_bytes=TRENDING_MAX_BYTES, deadline_seconds=timeout_s, socket_timeout=timeout_s, headers={"User-Agent": "peertube-browser-trending/1.0"}))`, followed by the unchanged "body has no data list" check. This is the plan's §5 code as written.
  - The except tuple is now `(SourceFetchFailed, ValueError)`, with its comment updated. The DEBUG line now carries the adapter's reason.
  - Unchanged: the request URL, the retry loop with no backoff, and the contract of returning None after `max_retries + 1` failed attempts.
  - Behaviour changes the plan accepted:
    - `--timeout-ms` now also limits each attempt's total time, not just each socket operation.
    - Any status other than 200, including other 2xx codes, now fails.
    - A redirect to another host or off https, or a body over the cap, fails the attempt and is retried.

### tests/active/test_fetch_trending.py
Its fetch cases patched `job.urlopen`, which no longer exists. Without this edit they would fail with an `AttributeError` from `monkeypatch.setattr`. This follows Phase 3's handling of `test_video.py`: the stubbing moved to the adapter's patch point, and the new redirect, cap and deadline cases stay in the checkpoint.
- **Imports:** added `http.client.HTTPMessage`, `urllib.request.HTTPSHandler, build_opener` and `from data import source_fetch`. Dropped `urllib.request.Request`.
- **New constant `USER_AGENT`.**
- **`_Response`:** now an `io.BytesIO` 200 with `code`/`status`, `msg`, `headers` (an `HTTPMessage`) and `info()`, which is what urllib's error processor and the adapter read.
- **`_fake_urlopen` is replaced by `_scripted(monkeypatch, outcomes)`.** It patches `source_fetch.build_opener` with a real opener around a scripted `HTTPSHandler`. That handler records `(full_url, timeout, User-Agent)` for each attempt, pops one outcome per attempt (raising it if it is an exception, otherwise serving it as a 200 body), and returns the record.
- **Assertions** in the four cases (success, `FAILURES`, no retries, retry succeeds) are now exactly `[(TRENDING_URL, 0.25, USER_AGENT)] * n`.
- The names the checkpoint imports (`FAILURES`, `TRENDING_URL`, `job`) are unchanged. The docstring's bullet 4 and its stubbing paragraph now name the adapter's opener.

### tests/config.json
- Added `engine/server/data/source_fetch.py` to the `test_fetch_trending.py` group. `moderation.py` was already in it.

Not run. I did not run `test_fetch_trending.py` or the checkpoint through `ValidateTests`, because that would record a group fingerprint partway through the build. So the rewritten harness has not been seen passing; the workflow's run will be the first.

The only `ValidateTests` runs were two probes in `tests/tmp`: the network measurement and a date check. Please delete both, since I have no delete tool: `tests/tmp/probe_53_phase4_measure.py` (it makes real network calls) and `tests/tmp/probe_53_phase4_date.py`.


