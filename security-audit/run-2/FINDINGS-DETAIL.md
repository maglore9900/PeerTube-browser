# Findings detail — run-2

Data flows for every MEDIUM+ finding. Line numbers were re-read against the working
tree at the time of writing.

---

## F9 — Engine rate limiter collapses to one global bucket

### Flow

1. Browser → `POST /recommendations` (or `GET /api/video`, `GET /api/channels`) on the
   Client backend. `client/backend/server.py:221-226` / `:182-186` route it after the
   Client-side limiter check (`:253-257`, keyed on the TCP peer — run-1 F6).
2. `_proxy_engine_request` (`client/backend/server.py:349-375`) builds the upstream
   request:
   ```python
   headers = {"accept": "application/json"}
   ...
   headers["content-type"] = "application/json"
   request = Request(upstream, data=request_data, method=method, headers=headers)
   ```
   No `X-Forwarded-For`, no `X-Real-IP`, no other identity header.
3. Engine `SimilarHandler._get_client_ip` (`engine/server/api/handlers/similar.py:215-227`)
   reads `X-Forwarded-For`, then `X-Real-IP`, then falls back to
   `self.client_address[0]` — which is `127.0.0.1`, the Client backend.
4. `_rate_limit_check` (`:355-362`) builds `key = f"{ip}:{path}"` and calls
   `RateLimiter.allow`. Applied to all `/api/*` GETs (`:296-298`) and to both POST
   similar routes (`:367-369`).
5. `RateLimiter` (`engine/server/api/http_utils.py:66-91`) permits
   `DEFAULT_RATE_LIMIT_MAX_REQUESTS = 60` per `DEFAULT_RATE_LIMIT_WINDOW_SECONDS = 60`
   (`engine/server/api/server_config.py:349-350`).
6. On rejection the Engine answers 429; `_proxy_engine_request` relays the upstream
   body and status back to the browser (`client/backend/server.py:411-442`).

### Requests

```
# exhaust the shared bucket
for i in $(seq 1 60); do
  curl -s -o /dev/null -X POST https://<site>/recommendations \
    -H 'content-type: application/json' -d '{"likes":[]}'
done

# from any other network, immediately after
curl -i -X POST https://<site>/recommendations -H 'content-type: application/json' -d '{}'
# HTTP/1.1 429  {"error": "Rate limit exceeded"}
```

### What the attacker gets

Denial of the feed, the video page and the channels page for every visitor, for the
rest of each 60-second window, at a cost of 60 cheap requests per minute. No
authentication, no preconditions.

### Baseline comparison

Gateways that terminate client connections and then call an internal service either
propagate the client address in a header the internal service trusts *because* it is
loopback-bound, or they keep rate limiting entirely at the edge. Doing neither — a
per-IP limiter on a service that only ever sees one IP — is a limiter that can only
misfire.

---

## F10 — Unbounded LIKE pattern under the global `db_lock`

### Flow

1. Browser → `GET /api/channels?q=<pattern>` on the Client backend.
   `client/backend/server.py:182-186` routes it; `_handle_engine_read_proxy_get`
   (`:259-275`) checks each parameter against
   `PROXY_ALLOWED_QUERY_PARAMS["/api/channels"]` (`:52-62`), which contains `q`,
   `instance`, `sort`, `dir`, `limit`, `offset`, `minFollowers`, `minVideos`,
   `maxVideos`. `q` passes with only `.strip()` applied — no length or content check.
2. `_proxy_engine_request` re-encodes it onto the Engine URL (`:357-360`).
3. Engine `do_GET` (`engine/server/api/handlers/similar.py:309-328`) takes
   `self.server.db_lock` at `:316` and calls `fetch_channels(..., query=params["q"][0], ...)`.
4. `fetch_channels` (`engine/server/data/channels.py:64-75`) builds
   `like = f"%{term}%"` and appends
   `LOWER(COALESCE(display_name, channel_name, channel_id,'')) LIKE ? OR LOWER(COALESCE(instance_domain,'')) LIKE ?`.
   The statement runs twice: `COUNT(*)` at `:92`, page rows at `:121`.
5. The hostile row reaches `channels.display_name` through the crawler:
   `crawlInstanceChannels` → `displayName: toNullableString(channel.displayName ?? channel.display_name)`
   (`engine/crawler/src/channels-worker.ts:324`), `toNullableString` doing only a
   non-empty-string type check (`:516`), persisted by the prepared upsert in
   `ChannelStore` (`engine/crawler/src/db.ts:767-785`, executed at `:1012-1029`).

### Requests

```
# after the hostile channel has been crawled
GET /api/channels?q=%25a%25a%25a%25a%25a%25zq HTTP/1.1
Host: <site>
```

(`%25` is a literal `%`; the term becomes `%a%a%a%a%a%zq`, and `fetch_channels` wraps it
again to `%%a%a%a%a%a%zq%`.)

Hostile channel payload served from the attacker's instance at
`/api/v1/video-channels`:

```json
{"total":1,"data":[{"id":1,"name":"evil","displayName":"aaaaaaaa…(200 chars)…aaaa",
 "url":"https://evil.example/c/evil","host":"evil.example","followersCount":1}]}
```

### Measurements

Executed locally with `python3 security-audit/run-2/harness/like_backtracking*.py`
(Python 3.14.7, in-memory SQLite, same WHERE clause, 20 000 rows):

```
like_backtracking.py           (40-char names, 3-letter alphabet)
  wildcards=1  0.053 s
  wildcards=4  2.399 s
  wildcards=8 38.021 s

like_backtracking_realistic.py (word-like names)
  %e%e…%zq, 16 wildcards        0.037 s      <- no blow-up on ordinary data
  (%_)*zq, 10 groups            0.009 s      <- SQLite collapses consecutive wildcards

like_backtracking_planted.py   (realistic names + one 200×'a' display_name)
  wildcards=3   0.378 s
  wildcards=4  14.231 s
  wildcards=5  > 400 s (timeout)
```

The realistic run is included deliberately: it shows the attack is *not* effective
against ordinary data, and that the stored hostile value is the enabling condition.

### What the attacker gets

One request pins an Engine worker thread inside SQLite while holding `db_lock`. Every
other Engine entry point — `/recommendations` (`:705`), `/videos/similar`,
`/api/video` (`handlers/video.py:215`), `/api/channels`, `/internal/videos/resolve`
(`internal_client_reads.py:36`), `/internal/events/ingest` (`internal_events.py:32`) —
blocks on that mutex. The Client backend then times out after 10 s and returns 502 to
every visitor. There is no statement timeout, no `progress_handler`, and no way to
cancel the query short of restarting the service.

### Baseline comparison

Search endpoints backed by SQL normally either escape LIKE metacharacters with an
`ESCAPE` clause, use FTS, or cap the term length. PeerTube's own search goes through
a query builder with bounded parameters and a database that can be told to abort a
statement. Here the pattern is caller-controlled, the term is unbounded, and the query
runs under the one mutex the whole service shares.

---

## F11 — Batch event ingest: rate-limit amplification and ingest stall

### Flow

1. Browser → `POST /client/events/publish`. `client/backend/server.py:245-250` routes
   it after the 90/minute per-peer limiter.
2. `_handle_client_publish_event` (`:652-668`) parses the body as a dict, sets
   `event_id`/`published_at` **only at the top level**, and calls `_publish_event`.
3. `_publish_to_engine_bridge` (`:671-690`) `json.dumps` the body unchanged to
   `{engine}/internal/events/ingest`.
4. Engine `do_POST` (`engine/server/api/handlers/similar.py:277-289`) dispatches to the
   ingest handler. Note there is **no** `_rate_limit_check` on `/internal/*` routes.
5. `handle_internal_events_ingest` (`engine/server/api/handlers/internal_events.py:19-39`):
   ```python
   if isinstance(body.get("events"), list):
       events = [item for item in body["events"] if isinstance(item, dict)]
   ...
   with server.db_lock:
       for event in events:
           result = ingest_interaction_event(server.db, event)
   ```
   The top-level `event_id` the Client backend minted is ignored in this branch; each
   element carries its own.
6. `ingest_interaction_event` (`engine/server/data/interaction_events.py:48-126`)
   inserts into `interaction_raw_events` (including `raw_payload_json`), upserts
   `interaction_signals` with `+1.0` per `Like`, and calls `conn.commit()` — per event,
   on a connection opened with library defaults (`engine/server/data/db.py:9-13`:
   rollback journal, `synchronous=FULL`).
7. `fetch_popular_videos` (`engine/server/data/random_videos.py:247`) orders the global
   popular pool by `(v.popularity + COALESCE(sig.signal_score, 0)) DESC`.

### Requests

```
POST /client/events/publish HTTP/1.1
Host: <site>
Content-Type: application/json

{"events":[
  {"event_id":"a00001","event_type":"Like","object":{"video_uuid":"<target-uuid>","instance_domain":"<target-host>"}},
  {"event_id":"a00002","event_type":"Like","object":{"video_uuid":"<target-uuid>","instance_domain":"<target-host>"}},
  ... ~11000 entries, unique event_id each ...
]}
```

Body size limit is 1 000 000 bytes in both services
(`client/backend/lib/http_utils.py:86`, `engine/server/api/http_utils.py:52`); the
minimal event above is ~88 bytes, hence ~11 000 per request. Distinct `event_id`s are
required, otherwise `ON CONFLICT(event_id) DO NOTHING` suppresses the signal update
(the commit still happens, so the stall remains either way).

### What the attacker gets

- **Ranking:** `+11 000` to one video's `signal_score` per request, against typical
  `popularity` values of two or three digits. One request puts any indexed video at the
  top of the popular pool, which supplies 10 % of the `home` mix
  (`server_config.py:58-59`) and 20 % of the `guest_home` mix that visitors without
  likes actually receive (`:144-145`).
- **Availability:** ~11 000 fsync-ing commits inside one `db_lock` acquisition; every
  other Engine endpoint blocks behind it, and the Client backend's 10-second proxy
  timeout turns that into 502s for all visitors.
- **Storage:** one permanent row per event in `interaction_raw_events`, carrying the
  attacker-controlled `raw_payload` object, with no retention policy. At the permitted
  90 requests/minute that is ~1 000 000 rows per minute from a single IP.

### Baseline comparison

Bridge/ingest endpoints in comparable systems authenticate the publisher, cap batch
size, and commit once per batch. Here the endpoint is anonymous, the batch is bounded
only by the HTTP body limit, and the commit granularity is per element under a global
lock — the worst of the three.
