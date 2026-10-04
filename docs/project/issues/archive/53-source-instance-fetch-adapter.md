# One source-instance fetch adapter

Status: enhancement, ready-for-agent
Origin: architecture review `.scratch/architecture-review-20261004-0901.md`, candidate "one source-instance fetch adapter" (Strong, top recommendation)

## Problem

The rule for fetching from a PeerTube instance, or from the media host its JSON names, is implemented properly once, copied once, and left out in several other places. The rule is: https only, redirects kept on that host, bytes capped, time bounded, and a failure that says why.

- `engine/server/api/handlers/internal_translate.py:48-104` (`same_host_https`, `SameHostRedirectHandler`, `fetch_bounded`) holds the full rule. `fetch_bounded` returns `None` and gives no reason.
- `engine/server/db/jobs/translate-worker.py` has its own copy. `media_host` (`:158-170`) adds a TLD rule the route doesn't have, `AudioPipe._feed` (`:230-256`) repeats the byte cap and the exception tuple, and there is no wall-clock deadline for media. The worker gets the shared half by putting `api/` on `sys.path` and importing from a route handler (`:36-48`). Because `fetch_bounded` gives no reason, the worker can only write a generic `video JSON fetch failed` (`:453`).
- `engine/server/api/handlers/video.py:82-101` (`fetch_instance_json`, called on every `/api/video`) and `engine/server/db/jobs/fetch-trending.py:73-88` use bare `urlopen` with `resp.read()`. Neither caps the body, and urllib's default redirect handler follows a redirect to any host or scheme. Those hosts are untrusted. This was observed in the code, not tested. `sync-whitelist.py:230`, `updater-worker.py:535` and `compare-join-hosts.py:59` also call bare `urlopen`; they were not read beyond that line.
- Tests have to monkeypatch `build_opener` in two module namespaces (`tests/active/test_translate_worker.py:507-508`). The scripted host in `test_internal_translate.py:238-269` was rewritten for the worker tests.

Both production failures on 2026-10-04 surfaced in this code: an incomplete certificate chain on an object-storage host, and a moov-at-end MP4 that decoded to nothing.

## Proposed solution

Move the instance-fetch rules out of the route into one adapter module under `engine/server/` that both the Engine and the jobs import. It owns URL acceptance, the same-host redirect policy, the byte cap, deadlines and a failure reason. It comes in two forms: buffered (JSON, caption tracks) and streamed (media into ffmpeg). The translate route and the worker move onto it first.

Moving `video.py` and `fetch-trending.py` onto it is where most of the gain is. It also changes their behaviour (they gain a cap and stop following cross-host redirects), so it needs its own decision during triage. The interface is not decided yet.

## Related

- `docs/project/issues/archive/45-translate-worker-whitelist-locked-at-claim.md`, `engine/server/db/jobs/docs/TRANSLATE_WORKER.md`.
- Issue 56 (worker split): its media-acquisition part would join this adapter.

## Comments

**Triage (2026-10-04).** The code claims above were checked against the tree, and all of them hold. No shared fetch module exists yet, and there are no prior rejections. The maintainer decided:

- **Scope:** the translate route, the translate worker, `/api/video`'s `fetch_instance_json` and the trending job's `fetch_host_list`. An earlier round left the last two out because of their behaviour change. It was reopened once the code showed that a failed fetch on `/api/video` already falls back to the stored row and still answers 200, so the change only stops unsafe fetches. `sync-whitelist`, `updater-worker` and `compare-join-hosts` stay out.
- **No new media deadline:** the streamed form keeps today's limits (socket timeout and byte cap). A wall-clock deadline for media downloads is a separate decision.
- **Trending's cap is the caller's:** the 2 MB cap was sized for one video's JSON. Nobody has measured how large a 100-video trending page is, so the trending job passes its own cap.
- The term "source-instance fetch" is now in `CONTEXT.md`.

## Agent Brief

**Category:** enhancement
**Summary:** Move the source-instance fetch rule out of the translate route into one shared adapter module that gives a reason for every failure. Move the translate route, the translate worker, the `/api/video` instance metadata fetch and the trending job onto it.

**Current behavior:**
The rule for fetching from a video's source instance is: https only, no explicit port, no userinfo, redirects only to https on the same host, a byte cap, a time bound, and a failure that says why. Its full implementation sits inside the `/internal/translate` route handler as `same_host_https`, `SameHostRedirectHandler` and `fetch_bounded`, with the constants `FETCH_MAX_BYTES`, `FETCH_DEADLINE_SECONDS`, `SOCKET_TIMEOUT_SECONDS` and `READ_CHUNK_BYTES`. `fetch_bounded` returns `bytes | None` and gives no reason for a failure.

The translate worker imports these from the route handler by adding the API directory to `sys.path`. It has a second copy of the rule for media:
- `media_host` checks a media URL and also requires a DNS name ending in a real TLD.
- `AudioPipe._feed` repeats the Content-Length precheck, the streamed byte cap and the exception tuple `(OSError, ValueError, http.client.HTTPException)`.

When the video-JSON fetch fails, the worker can only fail the job with the generic text `video JSON fetch failed`. Tests stub the network by monkeypatching `build_opener` in both the route module's namespace and the worker module's namespace.

Two more callers fetch from untrusted instance hosts without the rule:
- `fetch_instance_json`, used by `/api/video` and `/api/video/refresh` for the video detail and the channel detail. It calls bare `urlopen` with an 8 s socket timeout and `resp.read()`: no byte cap, no wall-clock bound, and urllib's default redirect handler, which follows a redirect to any host or scheme. When it returns `None`, the route merges nothing over the stored row and still answers 200.
- `fetch_host_list` in the trending job. It does the same with a configurable socket timeout, a `User-Agent: peertube-browser-trending/1.0` header and up to `max_retries` retries on any failure.

**Desired behavior:**
One adapter module under the Engine server package owns the rule. Both the Engine and the jobs import it directly, and no job imports from a route handler to get it. It has two forms:

- **Buffered** (JSON, caption tracks, trending lists): GET `https://<host><path>` with the same-host redirect policy, a byte cap, a per-fetch wall-clock deadline (also capped by an optional caller budget), a socket timeout and `read1` chunked reads. On success it returns the body. On failure it returns a short human-readable reason, for example a non-200 status, over the byte cap, deadline passed, a refused redirect, or the network or TLS error text. It never returns a bare `None`. The defaults are today's translate-route bounds (2 MB, 8 s deadline, 4 s socket timeout). A caller can pass its own cap, timeouts and request headers.
- **Streamed** (media into ffmpeg): opens a media URL through the same-host redirect policy and passes chunks to a consumer. It keeps today's media limits exactly: the media socket timeout, the Content-Length precheck and the streamed byte cap given by the caller. It adds no wall-clock deadline. Its failure texts keep today's wording (`media download failed: …`, `media over N bytes`).

URL acceptance moves into the adapter unchanged:
- An instance host is checked with today's `same_host_https` semantics.
- A media URL is checked with today's `media_host` semantics, which include the TLD and IP-literal refusal and return the raw `urlsplit` hostname.

The callers:
- **Translate route:** uses the buffered form with the defaults. Its responses are unchanged.
- **Translate worker:** uses both forms. A job whose video-JSON fetch fails is failed with the adapter's reason, for example `video JSON fetch failed: HTTP 404`, in place of the generic text.
- **`fetch_instance_json`:** uses the buffered form with the defaults. It keeps its contract: a JSON object, or `None` on any failure, with the reason logged. A cross-host or non-https redirect, or a body over the cap, now fails the fetch. `/api/video` then serves the stored row, as it does for any failed fetch today.
- **Trending job:** uses the buffered form, passing its own byte cap, its configured timeout as the socket timeout and its `User-Agent`. It keeps its retry loop, its "body has no data list" check and its "`None` after all attempts" contract. Measure a real trending page before choosing the cap, and leave clear headroom over it. A cross-host redirect now fails that host's attempt, and a failing host keeps its stored list as it does today.

**Key interfaces:**
- The buffered fetch returns body bytes or a failure reason. A result type or a raised exception carrying the reason are both acceptable. Choose one and use it consistently.
- The buffered fetch takes host and path, plus optional overrides: byte cap, deadline, caller budget, socket timeout and headers. With no overrides it behaves exactly like today's `fetch_bounded`.
- The same-host redirect handler and the two URL-acceptance checks become public names of the adapter module.
- Network stubbing in tests should need a patch in one place, the adapter, and not one per caller.

**Acceptance criteria:**
- [ ] One adapter module holds URL acceptance, the same-host redirect policy, the byte caps, the deadlines and the failure reasons. The translate route, the translate worker, the `/api/video` handler and the trending job hold no copy of any of these, and none of them calls `urlopen` or `build_opener` directly.
- [ ] The translate worker no longer adds the API handlers directory to `sys.path` to get fetch code, and imports nothing fetch-related from a route handler.
- [ ] A buffered fetch fails with a distinct reason for each of: non-200 status, Content-Length over the cap, streamed body over the cap, deadline passed, a redirect off the host or off https, and a network or TLS error.
- [ ] A translate job whose video-JSON fetch fails is stored `failed` with error text that includes the adapter's reason.
- [ ] The `/internal/translate` route's responses (status codes and bodies) are unchanged in every case, including a denied host still answering the same `Video not found` body.
- [ ] Media download behaviour is unchanged: same limits, no new deadline, same failure texts.
- [ ] `/api/video`, where the instance answers a video-detail request with a redirect to another host, answers 200 with the stored row's metadata, and the redirect target is never requested. The same holds for a detail body over the cap.
- [ ] `/api/video` against an instance that answers normally returns the same merged metadata as before.
- [ ] The trending job fails a host's attempt when the instance redirects to another host or sends a body over the job's cap, and keeps that host's stored list. A normal trending page within the cap is stored as before.
- [ ] The existing translate route, translate worker, video and trending tests pass. Network stubbing in them patches the adapter once and no longer patches `build_opener` in two module namespaces.
- [ ] The Engine server README section on the fetch bounds, the translate worker doc and any trending job doc name the adapter as where the bounds live, and the `/api/video` notes say that a refused redirect or an over-cap body falls back to the stored row.

**Out of scope:**
- `sync-whitelist`, `updater-worker` and `compare-join-hosts`, which also call bare `urlopen`.
- Adding a wall-clock deadline to media downloads, or changing the translate route's or the media download's cap and timeout values.
- Changing the trending job's retry policy (no backoff, 4xx retried).
- Making `/api/video` DB-only (the planned follow-up noted in its handler).
- The rest of the translate worker split (issue 56) and the job handle (issue 54).
- Fixing incomplete certificate chains on media hosts.
