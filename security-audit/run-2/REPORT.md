# Security audit — PeerTube Browser (run-2)

Scope: entire repository except `.un/` and `src/un/`. Second run; run-1 lives in
`security-audit/run-1`. Source-first review, with three findings supported by a local
SQLite harness that was built and executed (`security-audit/run-2/harness/`).

## Executive summary

No application code has changed since run-1, so all eight of its findings still stand —
the unescaped `href` on the channels page, the `?embed=` iframe sink, the `?api=`
override and the anonymous write endpoints are all still present as described. This run
deliberately looked elsewhere, and the new findings are all in one class run-1 did not
reach: **shared-resource exhaustion behind the Client→Engine gateway**. The Engine is a
single-process `http.server` where every request path takes one global `db_lock` around
an unbounded SQLite connection, and the gateway in front of it hands the Engine no
client identity at all. The consequence is that one anonymous visitor can (F9) exhaust
a rate-limit bucket that is shared by the whole deployment, (F10) hold that global lock
for minutes with a single `GET /api/channels?q=...`, or (F11) push ~11 000 ranking
events past a 90-per-minute limiter in one POST and stall the Engine while they commit.

F9 is not even an attack in the normal case: it fires under ordinary traffic. F10 is
the most serious — a single unauthenticated request, once a hostile instance has been
crawled, blocks every Engine endpoint for as long as the attacker chooses.

One correction to run-1: its F6 claimed the Engine's limiter is *bypassable* because it
trusts `X-Forwarded-For`. In the deployment `DEPLOYMENT.md` describes, the Engine never
sees that header (`_proxy_engine_request` does not forward it), so the real behaviour is
the opposite and worse — see F9.

Coverage caveat: two runs still do not exhaust this codebase. The recommendation mixer,
the FAISS/embedding jobs, and the crawler's resume/progress state machine remain the
least-examined areas.

## Baseline

Compared against other federated-content aggregators and PeerTube's own client. Beyond
run-1's point about escaping, the relevant comparison for this run is operational:
comparable services bound the cost of a single request against a shared database —
statement timeouts, a query-cancel hook, per-request CPU budgets, or simply not holding
a global mutex across a full table scan. This project has a single embedded SQLite
handle guarded by one mutex, with no timeout and no cancellation, directly reachable
from an anonymous browser request. That is what turns ordinary inefficiencies into
outages here.

## Findings

Numbering continues from run-1 (F1–F8) to avoid collisions.

| ID | Severity | Title |
|---|---|---|
| F9 | MEDIUM | Engine rate limiter degenerates into one global 60-requests/minute bucket, because the gateway forwards no client identity |
| F10 | HIGH | Unbounded `LIKE` pattern on `/api/channels?q=` burns CPU under the global `db_lock`; one hostile crawled channel name makes it effectively infinite |
| F11 | MEDIUM | `/client/events/publish` forwards `{"events":[...]}` batches, multiplying the rate limit by ~11 000 and stalling the Engine during ingest |

---

### F9 — MEDIUM — The Engine's per-IP rate limiter is a per-deployment rate limiter

**Locations:** `client/backend/server.py:363` and `:370-375` (proxy request headers);
`engine/server/api/handlers/similar.py:215-227` (`_get_client_ip`), `:296-298`, `:355-362`,
`:367-369`; `engine/server/api/server_config.py:349-350` (60 requests / 60 seconds).

The browser only ever talks to the Client backend, which proxies to the Engine with
`headers = {"accept": ..., "content-type": ...}` — no `X-Forwarded-For`, no `X-Real-IP`.
The Engine's `_get_client_ip` therefore falls through to `self.client_address[0]`, which
is `127.0.0.1` for every request from every visitor. The limiter key is `f"{ip}:{path}"`,
so the whole deployment shares one bucket per route, sized at 60 requests per minute.

**Attack:** send 60 `POST /recommendations` in a few seconds through the public gateway.
Every other visitor receives `{"error": "Rate limit exceeded"}` with HTTP 429 — proxied
back verbatim by the Client backend — for the remainder of the window. Repeat once a
minute to keep the feed down indefinitely. The same applies independently to
`/api/video` and `/api/channels`.

**Impact:** trivial, sustained denial of the feed and the video page for all users. It
also degrades without an attacker: a handful of simultaneous visitors, each loading a
feed and a few video pages, exceeds 60/minute on their own.

**Fix:** forward the resolved client address from the gateway (e.g. an
`X-Client-IP` header set by the Client backend, trusted by the Engine only because the
Engine is loopback-bound) and key the Engine limiter on that; or accept that the Engine
is an internal service and move rate limiting entirely to the Client backend, keyed on
the forwarded address of a trusted proxy (run-1 F6).

---

### F10 — HIGH — `?q=` LIKE patterns run unbounded under the global `db_lock`

**Locations:** `engine/server/data/channels.py:64-75` (pattern construction), `:92`, `:121`;
`engine/server/api/handlers/similar.py:309-328` (handler, `db_lock` at `:316`);
`client/backend/server.py:52-62` (`q` and `instance` are gateway-allowlisted), `:259-275`;
`engine/crawler/src/channels-worker.ts:324` and `:516` (display name stored with no
length or content validation).

`fetch_channels` wraps the caller's search term in `%…%` and runs it as a `LIKE` against
`display_name`, `channel_name`, `channel_id` and `instance_domain` — twice (once for
`COUNT(*)`, once for the page). The term is never length-limited or sanitised, so the
caller controls the pattern, including how many `%` wildcards it contains. SQLite's
`LIKE` backtracks across wildcard positions, so cost grows combinatorially with the
number of wildcards and with the number of occurrences of the chosen literal character
in each row. The whole thing runs while `db_lock` is held, and every other Engine
endpoint takes that same lock.

**Measured** (`harness/like_backtracking.py`, `harness/like_backtracking_planted.py`,
Python 3.14.7, in-memory SQLite, 20 000 rows):

| Data | Pattern | Time |
|---|---|---|
| Realistic channel names | `%e%e%…%zq`, 16 wildcards | 0.04 s |
| 40-char names over a 3-letter alphabet | `%a%a%…%zz`, 4 wildcards | 2.4 s |
| same | 8 wildcards | 38 s |
| Realistic names **+ one row whose `display_name` is 200 × `a`** | `%a%a%a%a%zq` (4 wildcards) | 14.2 s |
| same | 5 wildcards | > 400 s (timed out) |

The last two rows are the finding: a *single* stored row with a long repetitive name
makes one anonymous request cost unbounded CPU, and the attacker sets the exponent by
adding wildcards to `q`.

**Attack:** operate a PeerTube-API-compatible instance listed on
`instances.joinpeertube.org` (open self-registration; the same foothold run-1's F1
uses), serve one channel whose `displayName` is 200 identical characters, wait for the
crawl, then send
`GET /api/channels?q=%25a%25a%25a%25a%25a%25zq` to the public gateway. The Engine thread
enters `fetch_channels` holding `db_lock` and does not come back; every concurrent
`/recommendations`, `/api/video` and `/api/channels` request blocks behind the lock. The
limiter permits 60 such requests per minute, so all worker threads can be pinned.

Without a planted row the attack is weak (0.03–0.04 s on realistic data) — the stored
hostile value is what makes it decisive. Note the crawler applies no length cap:
`toNullableString` accepts any non-empty string.

**Impact:** complete, sustained loss of availability for every Engine-backed page, from
one unauthenticated GET. No timeout, no `progress_handler`, no statement cancellation,
and no per-request thread isolation exists to cut it short.

**Fix (all three, they are independent):**

1. Escape LIKE metacharacters in the search term and cap its length:
   ```python
   term = query.strip().lower()[:64].replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
   where.append("... LIKE ? ESCAPE '\\'")
   ```
2. Install a cancellation budget on the Engine connection, e.g.
   `conn.set_progress_handler(lambda: time.monotonic() > deadline, 10000)`, so no single
   statement can run for minutes.
3. Bound crawled text at ingest: reject or truncate `displayName`/`name` beyond a sane
   limit in `channels-worker.ts` and `videos-worker.ts`.

---

### F11 — MEDIUM — Batch events multiply the ingest rate limit by ~11 000 and stall the Engine

**Locations:** `client/backend/server.py:245-250`, `:652-668`, `:671-690`;
`engine/server/api/handlers/similar.py:277-289` (no rate limit on `/internal/*`);
`engine/server/api/handlers/internal_events.py:19-39`;
`engine/server/data/interaction_events.py:52-120`;
`engine/server/data/random_videos.py:247` (ranking sink).

Run-1's F5 established that `/client/events/publish` is an unauthenticated passthrough
to the Engine bridge and that each `Like` adds `+1.0` to the video's ranking score. What
run-1 missed is the shape of the payload: the Engine accepts a **list**
(`if isinstance(body.get("events"), list)`), and the Client backend forwards the body
unchanged. One 1 MB request (`http_utils.read_json_body` caps there) carries roughly
11 000 events of the minimal form
`{"event_id":"a1","event_type":"Like","object":{"video_uuid":"u","instance_domain":"h"}}`.

Consequences, all from one request:

- The 90-requests-per-minute limiter on `/client/events/publish` becomes ~1 000 000
  events per minute from a single IP. Run-1's "a few thousand posts to dominate the
  popular pool" becomes a fraction of one request.
- `handle_internal_events_ingest` holds `server.db_lock` across the entire loop, and
  `ingest_interaction_event` calls `conn.commit()` per event on a connection with
  SQLite's default `synchronous=FULL` rollback journal. 11 000 fsync-ing commits under
  the global lock stall every other Engine endpoint for the duration.
- Each event inserts a permanent row into `interaction_raw_events`, including the
  attacker-controlled `raw_payload` blob, with no retention policy.

**Attack:**

```
POST /client/events/publish
Content-Type: application/json

{"events":[{"event_id":"a1","event_type":"Like","object":{"video_uuid":"<uuid>","instance_domain":"<host>"}},
           {"event_id":"a2", ...}, ... ~11000 entries ...]}
```

**Impact:** an anonymous caller sets what every visitor sees in the popular slots at
negligible cost, grows the Engine database without bound, and makes the Engine
unresponsive while each batch commits.

**Fix:** authenticate the Client→Engine bridge (shared secret or Unix socket) and drop
the browser-facing passthrough; cap `events` length server-side; wrap the whole batch in
one transaction instead of committing per event, and release `db_lock` between chunks;
derive `event_id` deterministically from `(actor, video, type)` so replays collapse; cap
or size-limit `raw_payload`.

---

## Hardening notes (not findings)

- **Run-1's notes all still apply** — no CSP anywhere, `access-control-allow-origin: *`,
  `RECOMMENDATIONS_DEBUG_ENABLED = True` by default, no retention on
  `interaction_raw_events`, exception text returned to callers.
- `RateLimiter.requests` (`engine/server/api/http_utils.py:73-90`,
  `client/backend/lib/http_utils.py:108-126`) never evicts empty buckets. Not reachable
  for growth in the documented deployment (the Engine sees one key per path, and
  `/videos/{id}/similar` is not gateway-exposed), but it is a memory leak waiting for
  the moment either service is exposed directly.
- `sync-whitelist.py` and `updater-worker.fetch_join_hosts` only `strip().lower()` host
  strings from the JoinPeerTube index before storing them in `instances`, while the
  crawler path (`host-filters.normalizeHostToken`) parses them as URLs. A host entry
  containing `/`, `?`, `#` or `@` would therefore reach `buildUrl` in
  `channels-worker.ts:401` verbatim and redirect a crawl request. Normalise on the
  Python side too.
- `crawler.ts:340` (`parseHost`) returns `ref.host` without `normalizeHostToken`, unlike
  every sibling branch. Only reachable with `--graph`/`--expand-beyond-whitelist`, which
  the updater does not pass.
- The video page will fetch metadata from **any** host given in `?host=`
  (`video-page/index.ts:396-436`): when `/api/video` 404s, the browser falls back to
  `https://<attacker>/api/v1/videos/...` and renders the response, which feeds the
  unvalidated `href`/`src` sinks of run-1's F2/F3 without needing crawler access.
- `_handle_user_profile_reset` (`client/backend/server.py:606`) calls `read_json_body`
  outside a `try`, so a malformed body raises through `do_POST` and the connection is
  dropped with no response, unlike every sibling handler.
- Neither service drains an over-long or unread request body before continuing, so a
  declared-but-unread body desynchronises a keep-alive connection. Harmless today (the
  attacker only desynchronises their own connection) but it is the precondition for
  request smuggling if a connection-reusing proxy is ever put in front.
- `quote()` in `handlers/video.py:164`, `:176`, `:262`, `:269` leaves `/` unescaped.
  Currently unreachable with a traversal payload because every value is either a DB
  column matched by the preceding query or a field from the instance's own response, but
  a length/charset check on `channel_slug` would close the class.
- The updater's sudoers rule (`install-updater-service.sh:376`) is correctly narrow
  (`systemctl stop|start <exact unit>`), and unit names are validated against
  `^[a-zA-Z0-9_.@-]+$` before they reach it. No injection was found there.

## What this codebase does well

- Everything run-1 credited is still true: parameterised SQL throughout, a whitelisted
  `ORDER BY`, no `shell=True`, no `eval`/`pickle`, size-capped bodies, loopback binds,
  a non-root systemd user, and per-route allowlists for gateway query parameters and
  body keys.
- The installers are unusually disciplined for shell: `set -euo pipefail`, argument
  arrays rather than string commands, `printf '%q'` for dry-run echo, `visudo -cf`
  validation before installing a sudoers file, and strict validation of every value
  that reaches a unit file.
- The moderation layer consistently normalises hosts through one helper
  (`data/moderation.normalize_host`) before comparing or deleting, and every purge
  statement is parameterised even where the table name is interpolated from a fixed
  internal list.
- The Engine refuses `debug=1` outright when debug is disabled rather than silently
  ignoring it, and the recommendation path reads likes only from the current request
  context — there is no cross-visitor profile read on the Engine side.
