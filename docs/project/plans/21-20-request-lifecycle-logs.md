# 20-request-lifecycle-logs

_Rendered by the `dev-flow` workflow from its run state. Every edit here is overwritten on the next step; the evidence each gate turned on is in `docs/project/plans/21-20-request-lifecycle-logs.record.md`._

## Requirements

### Purpose

Issue 20 (task 38, [M7][F4]) is the second link of the logging chain: 19 timestamped logs (delivered), then 20 request lifecycle logs with a shared `request_id`, then 21 static page visit logs. Requests are served by threaded HTTP servers, so their log lines interleave. Today one request's lines cannot be picked out and read in order, and an app line cannot be matched to the nginx access line for the same request. After this build an operator can take one `request_id` and find:

- the nginx access line for the request (the client and network view: bytes, upstream, and so on);
- the Client backend's lines for it;
- the Engine's lines for it.

In each service those lines read `request.start` -> work logs -> `request.end`.

### Topology (from DEPLOYMENT.md)

Browser -> public nginx (`:80`, site config in DEPLOYMENT.md lines 394-432) -> Client backend (`client/backend/server.py`, `127.0.0.1:7072`) -> in prod, the loopback nginx listener `127.0.0.1:7079` (written by `engine/install-engine-service.sh`, blue/green upstream from issue 26) -> Engine (`engine/server/api`, `7070`/`7071`). In dev there is no nginx: the Client calls the Engine directly. "The app log" means both long-running services, the Client backend and the Engine.

### Current state (found in the tree)

- Engine `engine/server/api/request_context.py` already has the thread-local `set_request_id`, `fetch_request_id` and `clear_request_context`. `EngineJsonFormatter` (`engine/server/api/logging_profiles.py`) puts `request_id` on a record from three places, in this order: record extra, a `[scope][id]` message prefix, or the context. The text renderer appends `request_id=…`.
- Engine `SimilarHandler` (`engine/server/api/handlers/similar.py`):
  - `_log_access_start` logs `[access.start] ip= method= url=` at the top of `_dispatch_get` and `_dispatch_post`, and in `do_OPTIONS`.
  - `log_message` logs `[access] ip= method= url= status= bytes=`. `BaseHTTPRequestHandler.send_response` calls it, so the line is written when the status line is sent, not when the request finishes.
  - A request id exists only inside `_handle_similar`. It is a 6-hex id from `_make_request_id()` (numpy randint), and it is set into the context after the `[similar-server][id] start` line. Its `finally: clear_request_context()` clears it.
  - Every other route, and the access lines themselves, carry no `request_id`.
  - `do_GET` and `do_POST` wrap dispatch in `_statement_deadline()` and answer an interrupted query with `_respond_interrupted` (503).
- Client backend `client/backend/server.py`:
  - `ClientLogFormatter` emits `ts, level, service, event, message[, context][, traceback]`, with no `request_id` key. Its `_render_text` already appends `request_id=` when the payload has one.
  - `log_message` emits `client.access` ("request finished", with ip/method/url/status/bytes) at `send_response` time. There is no start line.
  - `_proxy_engine_request` sends `accept` and `x-client-ip` only.
  - `client/backend/lib/engine_api_client.py` and `_publish_to_engine_bridge` build their own headers (`bridge_headers()`).
  - The Client cannot import Engine modules (`tests/check-client-engine-boundary.sh`).
- Public nginx config in DEPLOYMENT.md sets no `X-Request-ID` and defines no log format with `$request_id`.
- DEPLOYMENT.md:472 says `X-Request-ID` reaches the Engine "as the Client sent them". The Client sends none, so that statement is currently false.
- Consumers of the current event names:
  - `_EVENT_RULES` in `logging_profiles.py` (`[access.start]` -> `access.start`, `[access]` -> `access`);
  - `engine/watch-engine-logs.sh` (lines 135-138);
  - `client/watch-client-logs.sh`;
  - `engine/server/api/tests/test_logging_profiles.py`;
  - `tests/active/test_logging_profiles.py` (including the issue-19 durable test `test_engine_request_ts_never_decreases_from_access_start_to_access`);
  - the access-line assertions in `tests/active/test_server.py`.

### Operator decisions

- **Id source: nginx always mints, the apps validate.** Public nginx overwrites any browser-supplied `X-Request-ID` with its own `$request_id`. Neither app trusts the header blindly: each accepts it only if it matches a strict pattern, and otherwise generates its own.
- **Event names: replace.** In both services the old start and access events are replaced by `request.start` and `request.end`, so each service logs exactly one start and one end per request. The send_response-time `access` / `client.access` line goes away. Every consumer of the old names is updated.

### Requirements

R1 - nginx.
- Every proxied `location` in the public site config in DEPLOYMENT.md (`/api/`, `/recommendations`, `/videos/similar`, `/client/`) sets `proxy_set_header X-Request-ID $request_id;`. This overwrites whatever the browser sent.
- The public site's access log uses a `log_format` that includes `$request_id`, so the nginx line carries the same id as the app lines.
- The internal `127.0.0.1:7079` listener (`engine/install-engine-service.sh`, issue 26 blue/green) must pass the Client's `X-Request-ID` through to the Engine unchanged. This is expected to need no change, and it must be verified against the script. Nothing in the blue/green scripts may overwrite or drop the header.

R2 - Id rule, the same in both services.
- An incoming `X-Request-ID` is accepted only if it fully matches `^[A-Za-z0-9._-]{1,64}$` (nginx's `$request_id` is 32 hex characters).
- If the header is missing, empty, or does not match, the service generates `uuid.uuid4().hex`. That is stdlib, and it has the same 32-hex shape as nginx's.
- An invalid value is never logged as the id.
- The rule is duplicated in Client and Engine because the two cannot share a module. If it is duplicated, it is a named deliberate duplication, like the existing `rat-tail` note at `client/backend/server.py:120`.

R3 - Scope of the id.
- In both the Client and the Engine, the request id is set at the very start of every request entry point: `do_GET`, `do_POST` and `do_OPTIONS`. It is set before any business logic, rate-limit check, bridge-auth check, body read or statement deadline.
- It is cleared when the request ends, on every exit path.
- A keep-alive connection serves several requests on one thread, so one request's id must never leak into the next request's records.

R4 - `request.start`.
- It is the first record each service logs for a request. Event name `request.start`, message "request started".
- It carries `request_id`, `ip` (each service's existing client-address rule: the Engine's `_get_client_ip`, the Client's `resolve_client_address`), `method`, `url` (the full URL as `_get_full_url` builds it today) and `user_agent`.
- `user_agent` appears only when the request has a non-empty `User-Agent` header.
- In JSON output every value must survive intact, including values that contain spaces, such as a user agent. The Engine formatter's whitespace-split `key=value` message parsing must not truncate them.
- Text output keeps the single-line CR/LF escaping that issue 19 delivered.

R5 - `request.end`.
- Each service logs exactly one per request, as the last record of the request. Event name `request.end`, message "request finished".
- It carries `request_id`, `status` (the status code actually sent) and `duration_ms` (integer milliseconds on a monotonic clock, measured from `request.start`).
- It carries no `bytes`: byte counts are nginx's job.
- It is emitted on every exit path:
  - normal responses;
  - 4xx, including 400/401/403/404 and 429;
  - the Engine's 503 statement-timeout path;
  - Client proxy failures (502/504);
  - an unhandled exception, in which case `status` is what was sent, or a placeholder such as `-` if nothing was sent.
- It replaces the Engine `[access]` line and the Client `client.access` line, which `log_message` emits at `send_response` time. `log_message` must no longer produce a second end line.

R6 - Propagation within a service.
- Every log record emitted on a request's thread between start and end carries that request's `request_id`. This covers handler, recommendations, similarity, moderation, search and proxy logs.
- Engine: through the existing context and formatter.
- Client: `ClientLogFormatter` gains a top-level `request_id` key, taken from a Client-side thread-local context. The key is additive to the Client's key order, like `traceback`.
- Records not tied to a request carry no `request_id`. These are startup, lifecycle and background-thread records.

R7 - Propagation Client -> Engine. Every HTTP call the Client makes to the Engine while serving a request sends `X-Request-ID: <the request's id>`. That covers:
- the read proxy (`_proxy_engine_request`), including its retry attempts;
- `engine_api_client` calls (metadata, resolve, dislike centroids and the like);
- the bridge publish (`_publish_to_engine_bridge`).

So the Engine's `request.start` … `request.end` for that call carry the same id as the Client's.

R8 - Remove the ad-hoc id.
- Delete `_make_request_id` in `engine/server/api/handlers/similar.py`.
- `_handle_similar` and everything it calls use the shared id from the context (`fetch_request_id()`) instead of minting and setting their own.
- The `[similar-server][<id>] …` log lines keep their format, with the shared id in the bracket.
- `_handle_similar`'s own clearing of the context must not end the id before `request.end` is logged.

R9 - Consumers of the old names. Update every consumer to the new events:
- `_EVENT_RULES` (the new start and end events stay tagged for both `focused` and `verbose`);
- `engine/watch-engine-logs.sh`;
- `client/watch-client-logs.sh`;
- the existing unit and active tests that assert on `access.start`, `access` or `client.access`, including the issue-19 durable non-decreasing-ts test, which must keep checking the same property over `request.start` -> work -> `request.end`.

R10 - Docs and runbook.
- DEPLOYMENT.md gains a runbook, placed in the Triage area or next to the logging paragraph at line 116. It shows how to take one `request_id` and find the matching line in the public nginx access log and the matching records in the Client and Engine journald units, using concrete commands (grep/journalctl/jq). It explains what each log is for: nginx gives the network view and bytes, the app gives internal processing and duration.
- DEPLOYMENT.md:472 is corrected so that it is true: the Client now sends `X-Request-ID`.

R11 - Ordering.
- Start -> work -> end order is guaranteed within one request in each service, read by `ts` and the `request_id`. No global ordering across requests is promised.

### Constraints

- stdlib only (`uuid`, `threading`, `re`, `time`). No new dependency.
- New code follows the style of the file it lands in.
- No change to response bodies.
- Echoing `X-Request-ID` back on responses is not required.
- `LOG_FORMAT=json|text` behaviour from issue 19 is preserved.

### Validation

1. Smoke through the Client backend (as the session `engine` and Client fixtures run it), with `X-Request-ID` set to a known valid value as nginx would set it. Do this for one similar route (POST `/videos/similar` or `/recommendations`; see Conflicts), for `/api/video` and for `/api/health`. For each, the Client log shows `request.start` … `request.end` carrying that id. For the proxied routes, the Engine log also shows `request.start` … work … `request.end` with the same id. In each service the start record comes first and the end record last for that id.
2. A request without `X-Request-ID` gets a generated 32-hex id, used consistently in both services.
3. A request with a malformed `X-Request-ID` (too long, containing spaces or CR/LF, or other disallowed characters) gets a generated id, and the bad value appears in no log record as `request_id`.
4. No request-path record lacks `request_id`. This includes error paths: 404, 429, 400, and the Engine 503 statement timeout. Each service logs exactly one `request.end` per request, with `status` and `duration_ms` and no `bytes`.
5. Two consecutive requests on one keep-alive connection get distinct ids, and neither request's records carry the other's id.
6. The DEPLOYMENT.md runbook exists and its nginx config sets and logs `$request_id`.

### Out of scope

- Static page visit logs (issue 21).
- About click tracking (issue 18).
- Changing the 7079 listener's own access-log format.
- Byte counts in app logs.
- Global cross-request ordering.

### Baseline suite state

Pre-build suite exited 0 (baseline variant: false).

## High-level plan

### Approach

Each service gets one request lifecycle wrapper. `do_GET`, `do_POST` and `do_OPTIONS` call it. It is the only place that resolves the id, logs `request.start` and `request.end`, and clears the request's state. The nginx changes, the Client→Engine propagation and the consumer updates hang off that one seam. The design adds one new file, `client/backend/lib/request_context.py`, and no new dependency.

**R1 – nginx (DEPLOYMENT.md public site block).**
- Each of the four proxied locations (`/api/`, `/recommendations`, `/videos/similar`, `/client/`) gains `proxy_set_header X-Request-ID $request_id;`. This overwrites anything the browser sent.
- A `log_format` that includes `$request_id` is declared at the top of the site file, outside `server {}`. This is legal there because `sites-enabled/*` is included inside `http {}`. The format is the combined fields plus `request_id=$request_id`, `upstream=$upstream_addr` and `rt=$request_time`.
- The `server` block gains an `access_log /var/log/nginx/peertube-browser.access.log <format>;` line. The static `location /` is logged with the id too, which issue 21 can use later.
- 7079 listener, checked against `engine_listener_text()` in `engine/install-engine-service.sh`:
  - its only header directive is `proxy_set_header Host $http_host`;
  - nginx forwards every client request header by default (`proxy_pass_request_headers on`);
  - `X-Request-ID` has no underscore, so `underscores_in_headers` does not apply;
  - a grep of every `*.sh` finds no other `proxy_set_header` or header-dropping directive.

  So the Client's header reaches the Engine unchanged and the script needs no change. The listener's own `$request_id` is a different value, but nothing uses it, and its log format stays out of scope.

**R2 – id rule.**
- Engine: `engine/server/api/request_context.py` gains the pattern constant and a resolver. The resolver returns the raw header value when it `re.fullmatch`es `[A-Za-z0-9._-]{1,64}`, and `uuid.uuid4().hex` otherwise, including when the header is missing or empty.
- `fullmatch` is chosen on purpose over `match` with `^…$`: `$` also matches before a trailing newline, so `"abc\n"` would pass.
- The rejected value is never logged, as the id or in any other field. Logging it would reopen log injection.
- Client: the new `client/backend/lib/request_context.py` carries an identical copy (a `threading.local` with set/fetch/clear plus the resolver).
- The copy gets a `rat-tail` note naming the Engine original, in the same style as `server.py:120`. A cross-service test feeds the same accept/reject samples to both resolvers and checks the two pattern strings are equal, so drift fails a test.

**R3 – scope.**
- The wrapper's first act is to resolve the id from `X-Request-ID` and set it in the thread-local context. That happens before the client-IP lookup, rate limits, bridge auth, body reads and the Engine's `_statement_deadline()`.
- The wrapper also resets a per-request "status sent" slot on the handler instance. Under keep-alive, one handler instance serves every request on the connection, so the slot must not carry over.
- In a `finally`, after `request.end`, the wrapper clears the id and all request-scoped state: the Engine's `clear_request_context()` plus `set_request_id(None)`, and the Client's clear.
- Validation 5 is tested as the operator chose: a test-only handler subclass with `protocol_version = "HTTP/1.1"` sends two requests over one `http.client` connection. Production stays on HTTP/1.0, where every connection closes after one response.

**R4 / R5 – start and end records.**
- `request.start` carries `ip` (Engine `_get_client_ip`, Client `_get_client_ip` → `resolve_client_address`), `method`, `url` (`_get_full_url`), and `user_agent` only when the header is non-empty.
- `request.end` carries `status` and `duration_ms`. `duration_ms` is an integer from `perf_counter`, which both files already use, measured from just before the start record.
- How the status is captured:
  - Each handler overrides `log_request(code, size)`, which `send_response` calls, so that it records the status as an int and logs nothing. That removes the send_response-time `[access]` / `client.access` line.
  - `log_message` then receives only `log_error` calls: http.server's own parse errors and timeouts. The app code never calls `send_error`.
  - Those calls become a single WARNING record, `[http] …` in the Engine and `client.http` in the Client, so they stay visible and are never a second end line.
  - If no status was sent, `status` is `"-"`.
- The `finally` covers every exit path: normal responses, 4xx, the Engine's 503 (which `_respond_interrupted` sends inside the wrapped body), Client 502/504 relays, and unhandled exceptions. Exceptions still propagate to socketserver as today.
- Client: both records go through `_emit_client_log` with a context dict, so values with spaces survive in JSON.
- Engine: the formatter's whitespace-split `key=value` parsing would truncate a user agent. `EngineJsonFormatter` therefore gains one optional structured-context record extra. When it is present, the formatter uses it verbatim as `context` instead of parsing the message.
  - The Engine logs `[request.start] request started` and `[request.end] request finished` with that extra.
  - The two access rules in `_EVENT_RULES` become `[request.start]` → `request.start` and `[request.end]` → `request.end`, both for `focused` and `verbose`.
  - The formatter's two access branches become request branches that set the message to "request started" / "request finished", as they do today.
- Text mode is still rendered by the shared `_render_text`, whose whole-line translate keeps the CR/LF escaping.

**R6 – propagation within a service.**
- Engine: the existing context and `_extract_request_id` already stamp every record on the thread. Moderation, search and recommendations records gain the id because it is now set for every route.
- The `[scope][id]` prefix rule still takes precedence, and the bracket now holds the same shared id.
- Client: `ClientLogFormatter.format` reads the Client context at format time and adds a top-level `request_id` after `context` and before `traceback`, so existing keys keep their positions. The mirrored `_render_text` already appends it, so the rat-tail copies are not edited.
- Both formatters read thread-locals at format time. That is correct because `StreamHandler` formats on the emitting thread.
- Startup, lifecycle and background-thread records (for example the random-cache refresh) run on threads that never set an id, so they carry none.

**R7 – Client→Engine propagation.**
- `bridge_headers()` adds `X-Request-ID` whenever the Client context holds an id. That one change covers `engine_api_client._post_json` (resolve, metadata, centroids) and `_publish_to_engine_bridge`, since both already build their headers there.
- `_proxy_engine_request` adds the header to its dict next to `x-client-ip`. Its `Request` is built once and reused across retries, so every attempt sends the same id.

**R8 – remove the ad-hoc id.**
- `_make_request_id` is deleted. numpy stays imported because `_draw_page` uses it.
- `_handle_similar` drops `set_request_id(...)` and takes `request_id = fetch_request_id()`. Its fallback `"-"` matters only for unit tests that call it with no context.
- The `[similar-server][…]` lines keep their format.
- The early-clearing problem: `_handle_similar` and `_handle_similar_request` both call `clear_request_context()` in `finally`, which today also deletes the id. The fix moves ownership of the id to the wrapper: `clear_request_context()` stops clearing `request_id` (its docstring is updated), and only the wrapper sets and clears the id. The inner calls keep their names, so the `patch.object(similar, "clear_request_context")` tests still hold.
- Engine unit tests that used `clear_request_context()` as a teardown to reset the id also call `set_request_id(None)`.

**R9 – consumers.**
- `_EVENT_RULES` and the formatter branches change as described under R4/R5.
- `engine/watch-engine-logs.sh`: the `access` / `access.start` jq branches become `request.end` / `request.start`.
- `client/watch-client-logs.sh` was read and names no event (it is `fromjson? // {"raw": .}`), so it needs no change.
- Tests:
  - the `[access.start]` probes in both `test_logging_profiles.py` files become `request.start` records with a structured context that includes a user agent with spaces;
  - the `client.access` payloads and text line in `tests/active/test_server.py` become `request.end`;
  - the issue-19 durable test now finds the `request.start` whose `context.url` carries the marker, takes its `request_id`, and finds the `request.end` with that id. `request.end` no longer has a url. The non-decreasing-`ts` property over start → `recommendations.*` → end is unchanged.
- Validation 1 uses POST `/recommendations` for the similar route, the route the durable test already drives against the session Engine. The Engine side is read from the session Engine's log file. The Client side is read through a `ClientLogFormatter` handler that the test attaches to the in-process Client.
- The Engine 503 path is covered by a handler-level test that forces an interrupted `sqlite3.OperationalError` from dispatch.

**R10 – docs.**
- The DEPLOYMENT.md site block gains the `log_format`, `access_log` and four `proxy_set_header` lines.
- A "Follow one request" runbook goes into Triage, cross-linked from the line-116 logging paragraph. It shows:
  - `grep 'request_id=<id>'` on the nginx access log;
  - `journalctl -u peertube-client.service -o cat | jq -cR --arg id <id> 'fromjson? | select(.request_id == $id)'`;
  - the same against `'peertube-engine@*'`;
  - a plain `grep request_id=<id>` alternative for text mode.
- The runbook explains what each log is for: nginx gives bytes, upstream and the network view; the app logs give internal processing and `duration_ms`.
- It also warns about two cases: a Client request can show several Engine start/end pairs under one id (one per proxy retry or internal bridge call), and a malformed header means a different id from nginx's.
- Line 472 is reworded to say the Client sends `X-Request-ID` and the listener passes it through.

**R11 – ordering.** One request's records are written on one thread, in program order: start first, end in the `finally`. `ts` and `request_id` are enough to read them in order, and the docs promise nothing across requests.

### Alternatives considered

- **Pass the id explicitly** through `engine_api_client` functions and the proxy, instead of a Client thread-local. Rejected: every call site and signature would change. R6 needs a thread-local for the formatter anyway, and `bridge_headers()` is already the single choke point.
- **Engine: quote or JSON-encode values in the message** so the whitespace parser survives spaces. Rejected: it changes parsing for every existing record. A structured-context extra is opt-in and touches only the two new records.
- **Keep `clear_request_context()` semantics and carry the id on `self`, passed as a record extra.** Rejected: any record logged between the inner clear and `request.end` would lose the id.
- **Capture the status by overriding `send_response`** instead of `log_request`. The two are equivalent. `log_request` was chosen because overriding it is also what stops the old access line.
- **A shared Client/Engine package for the id rule.** Rejected: the boundary check forbids it, and two copies do not justify a package. The rat-tail note plus a cross-check test is the existing convention, and a shared package remains the upgrade path.
- **Suffix the id per proxy retry** (`<id>.1`). Rejected: an exact-id grep would no longer find every attempt.
- **Switching the servers to HTTP/1.1** to get real keep-alive was rejected by the operator in favour of a test-only subclass.

### Gotchas, risks, limitations

- Requests that http.server rejects before dispatch get no `request.start` or `request.end` in either app. Examples are a malformed request line, a 414 URI too long, or a 501 for a method with no `do_*`. Only the nginx line (and now a `[http]` / `client.http` warning) records them. This is a deliberate limit of hooking `do_*`, as R3 specifies.
- The Engine's `user_agent` is that of its immediate caller. In prod and dev this is the Client's `Python-urllib/…`, because the Client does not forward the browser's UA. The browser UA appears in the Client's `request.start`.
- On an unhandled exception, `request.end` is the last logging record. socketserver's `handle_error` then prints a raw, non-JSON traceback to stderr, as it does today.
- In dev, and for any direct caller of `:7072`, the caller chooses the id within the pattern. Ids are for correlation only: they are not unique and not authenticated. A caller can reuse an id to blur the logs, but cannot inject characters.
- `ts` is wall-clock while `duration_ms` is monotonic. A backwards NTP step can still reorder `ts` inside one request, which is the same exposure issue 19 accepted.
- Log volume: the Engine's line count per request is unchanged (two old lines replaced by two new ones). The Client gains one line per request. Health polls (deploy checks, fixtures) also produce pairs.
- Formatters read thread-locals at format time. Moving to a `QueueHandler` or any off-thread formatting later would silently drop ids. This is called out in a code comment.
- The rejected header value is never logged, so the reason an id was regenerated cannot be seen in the logs.

### Tradeoffs the operator is asked to accept

- The send_response-time access lines disappear, and with them the app-side `bytes`. Byte counts come only from nginx.
- `clear_request_context()` changes meaning: it clears feed state but no longer the id. The wrapper now owns the id. It also clears feed state on every request path, which closes the gap where routes such as search never cleared it.
- Keep-alive non-leak is shown with an HTTP/1.1 test subclass, not against the shipped HTTP/1.0 servers.
- One new Client file, `lib/request_context.py`, deliberately duplicates the Engine's id rule (rat-tail, with a cross-check test).

## Impacts

<impacts>
<impact path="engine/server/api/request_context.py" element="new id pattern constant and resolver (R2)">
**Change.** Add a module-level pattern constant `[A-Za-z0-9._-]{1,64}` and a resolver. The resolver uses `re.fullmatch` and returns the raw header value, or `uuid.uuid4().hex` when the value is missing, empty or does not match. Today the module imports only `threading` and `typing`, so this adds `re` and `uuid`.

**Dependents.** The Engine wrapper in `handlers/similar.py` calls the resolver. The cross-service test reads the pattern string and runs the samples through it. `logging_profiles.py` imports `request_context` at module level (`from request_context import fetch_request_id`). `tests/active/test_logging_profiles.py:124` and `tests/active/test_server.py:1296` depend on "logging_profiles imports only the stdlib and request_context, so pytest's own interpreter can run it".

**Risk.**
- Any non-stdlib import added here breaks those two subprocess tests, which run under the system python with `cwd=API_DIR`.
- If someone uses `re.match` with `^…$` instead of `fullmatch`, `"abc\n"` is accepted.
- The resolver must never pass the rejected value to a log call.
</impact>
<impact path="engine/server/api/request_context.py" element="clear_request_context() and set_request_id()/fetch_request_id()">
**Change.** `clear_request_context()` (lines 63-76) stops deleting `request_id`: lines 75-76 are removed and the docstring loses "and request id". `set_request_id(None)` stays the only way to clear the id (lines 51-52), and the wrapper owns it. `fetch_request_id` is unchanged.

**Dependents.**
- `handlers/similar.py`: `_handle_similar_request` (line 671) and `_handle_similar` (line 1136) call it in `finally`.
- `engine/server/api/tests/test_logging_profiles.py:30` uses it as the tearDown that resets the id.
- `logging_profiles._extract_request_id` falls back to `fetch_request_id()` (line 117).

**Risk.** After this change, an id leaks from one test to the next unless tearDowns also call `set_request_id(None)`. In production, the wrapper is now the only place the id is cleared. A wrapper path that skips its `finally` would leave a stale id on a reused thread. ThreadingHTTPServer uses one thread per connection, so the exposure is the keep-alive case only.
</impact>
<impact path="engine/server/api/handlers/similar.py" element="SimilarHandler.do_GET / do_POST / do_OPTIONS and the new lifecycle wrapper">
**Change.** All three call the new wrapper. In order, the wrapper:
1. resolves the id from `X-Request-ID` and calls `set_request_id`;
2. resets the per-instance status slot;
3. takes `perf_counter`;
4. logs `[request.start]` with the structured-context extra: ip from `_get_client_ip`, method, url from `_get_full_url`, and `user_agent` only when non-empty;
5. runs the body;
6. in `finally`, logs `[request.end]` with `status` (int, or `"-"`) and `duration_ms`, then calls `clear_request_context()` and `set_request_id(None)`.

`do_GET` and `do_POST` keep their `_statement_deadline()` / `is_interrupted_error` / `_respond_interrupted` blocks (lines 387-395 and 455-463) inside the wrapped body. Today those blocks are the whole method body. `do_OPTIONS` (line 362) currently calls `_log_access_start()` and then `respond_options`.

**Dependents.**
- `server.py:120` registers `SimilarHandler` with `SimilarServer`.
- `tests/active/test_video.py:165-230` runs a real `SimilarServer` with `SimilarHandler` in a child.
- The session `engine` fixture (`tests/active/conftest.py:106`) drives every route through it.
- `scripts/deploy-bluegreen.sh` health polls and the Client proxy hit every route.

**Risk.**
- The id must be set before `_rate_limit_check`, `_bridge_authorized`, `read_json_body` and `_statement_deadline()`, as R3 requires. Otherwise the 429/401/503 records have no id.
- The `finally` must not swallow exceptions: socketserver `handle_error` still has to see them.
- `_respond_interrupted` (line 377) logs `[statement.timeout]` WARNING inside the wrapped body, so it now carries the id.
- Order inside `finally` matters: `request.end` before the clear, or `request.end` loses its id.
</impact>
<impact path="engine/server/api/handlers/similar.py" element="SimilarHandler._log_access_start() and its three call sites">
**Change.** Removed: `_log_access_start` (lines 340-347) and its calls in `do_OPTIONS` (line 364), `_dispatch_post` (line 424) and `_dispatch_get` (line 467). The wrapper's `request.start` replaces them.

**Dependents.** None outside the file; a grep of tests shows no direct call.

**Risk.** Leaving one call in place gives two start records per request: an old `[access.start]` with no rule (it falls to `access.start.info`, verbose) plus the new one.
</impact>
<impact path="engine/server/api/handlers/similar.py" element="SimilarHandler.log_message() and new log_request() override">
**Change.**
- A new `log_request(code, size)` stores `int(code)` in the per-instance status slot and logs nothing. http.server's `send_response` calls it, and `respond_json`, `respond_options` and `send_error` all go through `send_response`.
- `log_message` (lines 349-360), which today emits `[access] ip= method= url= status= bytes=`, becomes a single WARNING `[http] …` record. It then only receives `log_error` calls: http.server parse errors, 414, 501 for an unknown method, and timeouts.

**Dependents.** `_EVENT_RULES` and the formatter branches in `logging_profiles.py`, and the `access` branch of `engine/watch-engine-logs.sh`.

**Risk.**
- `log_error` can fire before `self.headers` exists, for example a bad request line or a 414 where `requestline` and `command` are `''`. Today's `log_message` calls `_get_client_ip()`, which reads `self.headers.get`. The new `[http]` line must not read headers, or it raises `AttributeError` inside `send_error`.
- The `[http]` text may carry the raw request line (`format % args`), which is attacker-controlled. JSON escapes it and text mode escapes CR/LF, so it is no worse than today.
- At WARNING, `_classify_event` derives event `http.info` from the `[http]` scope (`_derive_event_name`). The `.info` suffix is misleading on a warning, so decide whether to add a rule.
</impact>
<impact path="engine/server/api/handlers/similar.py" element="_handle_similar() id handling, _make_request_id(), numpy import">
**Change.**
- `_make_request_id()` (lines 1239-1241) is deleted.
- In `_handle_similar` (lines 1036-1046), `request_id = _make_request_id()` becomes `request_id = fetch_request_id() or "-"`, and `set_request_id(request_id)` at line 1046 is dropped.
- The `finally: clear_request_context()` at line 1136 stays. It no longer drops the id.
- `import numpy as np` (line 31) stays: `_draw_page` (line 1197) and `_parse_dislike_centroids` (lines 216-222) use it.
- The `set_request_id` import (line 89) stays only if the wrapper lives in this module.

**Dependents.** The `request_id` string is passed to `_handle_random`, `_handle_ordered_feed`, `_handle_home`, `_handle_seed_with_embedding`, `_respond_rows`, `_handle_vector_search`, `_log_upnext_pool`, `get_upnext_candidates` and `apply_serving_moderation_filters`. `logging_profiles._REQUEST_PREFIX_RE` extracts it from `[similar-server][id]`.

Test doubles call `_handle_similar` directly with no context, so the id is `"-"`:
- `tests/active/test_similar.py` `_DEBUG_CHILD` at line 451;
- `tests/active/test_similar.py` `_FAILING_SIMILAR_CHILD` at line 563, which asserts `"] start limit=20"` in a message (line 588) and still passes.

**Risk.**
- Ids grow from 6 hex characters to 32 (uuid4 hex) or a caller-chosen 1-64 characters. `tests/active/test_similar.py` `POOL_LINE` / `START_LINE` (lines 656-657) use `(\w+)`, which matches uuid4 hex but not caller ids containing `.` or `-`. Only a test that sends `X-Request-ID` would break.
- `test_upnext_with_and_without_likes…` (line 983) needs distinct ids per request. Engine-direct requests get a fresh uuid4 each time, but requests relayed through one Client request would share an id.
</impact>
<impact path="engine/server/api/handlers/similar.py" element="_handle_similar_request() finally clear_request_context()">
**Change.** No code change. The `finally: clear_request_context()` at line 671 keeps its name, but now clears only feed state, so the id survives until `request.end`.

**Dependents.** Both patch `similar.clear_request_context` and assert call counts:
- `engine/server/api/tests/test_recommendations_likes_limit.py` (lines 57, 89, 107: `assert_not_called` / `assert_called_once`);
- `tests/active/test_similar.py` `_LIKES_CHILD` (line 326, `"clear": clear.call_count` expected 0 or 1).

**Risk.** If the wrapper's own clear runs through the module-global name `clear_request_context` while those tests call `_handle_similar_request` directly, nothing changes: they never enter the wrapper. Moving the inner clear into the wrapper would break the expected counts of 1. The plan keeps it.
</impact>
<impact path="engine/server/api/handlers/similar.py" element="_handle_search() moderation request_id">
**Change.** No code change. Line 587 passes `request_id=fetch_request_id()`. Today that is `None` on search (nothing set an id), so `apply_serving_moderation_filters` never logged. From now on it returns the wrapper's id.

**Dependents.** `engine/server/data/serving_moderation.py`.

**Risk.** A behaviour change: GET `/api/v1/search/videos` now logs `[similar-server][<id>] moderation filtered_by_denylist=…` whenever moderation filtered rows. That is new INFO volume with a `similar-server` scope on a search request, which may confuse triage. No test counts these lines (grep).
</impact>
<impact path="engine/server/api/handlers/similar.py" element="_dispatch_get/_dispatch_post routes via internal handlers (handlers/internal_events.py, internal_client_reads.py, video.py)">
**Change.** No code change in those modules. Every record they emit on a request thread now carries the top-level `request_id`, from context through `_extract_request_id`. That covers bridge ingest, resolve/metadata/centroids, video and refresh, health and channels.

**Dependents.** The runbook greps.

**Risk.** Low. Records stamped after the wrapper's clear (none expected) would lack the id. `/api/video/refresh` opens its own statement deadline inside the request body (`test_video.py:684`), which stays inside the wrapper.
</impact>
<impact path="engine/server/data/serving_moderation.py" element="apply_serving_moderation_filters(request_id=…)">
**Change.** None. It now receives the shared id, longer than before, and is called from search with an id (see `_handle_search`).

**Dependents.** `similarity_candidates._upnext_rows` (line 209), `similar.py` lines 587, 699 and 776, and `engine/server/db/jobs/tests/test-moderation-integration.py:948`, which passes `"moderation-test"` explicitly and is unaffected.

**Risk.** Low. The log format is unchanged.
</impact>
<impact path="engine/server/data/similarity_candidates.py" element="get_upnext_candidates(…, request_id) / _upnext_rows">
**Change.** None. The `request_id` argument is now the shared id. The `[similar-server] ann_*` and `candidates=` records in `data/ann.py` and line 469 carry no prefix id, but gain the top-level `request_id` from context.

**Dependents.** The `tests/active/test_similar.py` `_pools_with_fallbacks` docstring (line 834) says "the ann_fallback lines carry no id". The test reads only `message`, so it still passes, but the docstring goes stale.

**Risk.** Low.
</impact>
<impact path="engine/server/api/logging_profiles.py" element="_EVENT_RULES access entries (lines 36-37)">
**Change.** `_EventRule("[access.start]", "access.start", …)` becomes `("[request.start]", "request.start", ("focused","verbose"))`, and `_EventRule("[access]", "access", …)` becomes `("[request.end]", "request.end", …)`.

**Dependents.** `_classify_event`, `engine/watch-engine-logs.sh`, both `test_logging_profiles.py` files and the session-Engine durable test.

**Risk.** Rule order matters: the first needle found wins. `[request.start]` and `[request.end]` must not appear inside other messages. A grep finds no other `[request.` text in the engine.
</impact>
<impact path="engine/server/api/logging_profiles.py" element="EngineJsonFormatter.format() access branches and new structured-context extra">
**Change.**
- The `elif event == "access.start"` / `elif event == "access"` branches (lines 257-264) become `request.start` / `request.end`. They keep "request started" / "request finished" as the message.
- A new optional record extra (a structured context dict) is used verbatim as `context` instead of `_extract_fields(message)`, so a `user_agent` with spaces survives. `_extract_fields` (lines 120-136) splits on whitespace.
- The `request_id` key position is unchanged (after `modes`, before `context`).
- `_render_text` (lines 210-223) is unchanged and still escapes CR/LF over the whole line. Its context values go through `_text_value`.
- Add the "thread-local read at format time; a QueueHandler would drop ids" comment.

**Dependents.** `configure_engine_logging`; `server.py:323`; the tests that assert exact payload key order (`tests/active/test_logging_profiles.py` `JSON_PAYLOADS`, lines 89-95); the Client mirror check `test_client_format_ts_and_render_text_return_the_engines_strings`, which compares only `_format_ts` and `_render_text` and so is unaffected as long as `_render_text` is untouched.

**Risk.**
- The extra's attribute name must not collide with LogRecord attributes or the existing `request_id` extra.
- The JSON payload must keep key order `ts, level, event, message, modes, request_id, context, traceback`.
- In text mode an unquoted `user_agent=Mozilla/5.0 (X11; …)` is ambiguous to read by eye, which is the accepted limitation of text mode.
</impact>
<impact path="engine/server/api/logging_profiles.py" element="_extract_request_id() and _REQUEST_PREFIX_RE">
**Change.** None. The `[scope][id]` prefix still wins over context. With the shared id, both give the same value.

**Dependents.** Every Engine record.

**Risk.** `_REQUEST_PREFIX_RE` `[^\]]+` accepts every id the pattern allows, since `]` is excluded from the pattern. Low risk.
</impact>
<impact path="engine/server/api/server.py" element="startup/lifecycle logs, random-cache worker thread, request_context imports">
**Change.** None.
- `server.py:122-127` imports four feed-state fetchers, which are unchanged.
- The startup `[similar-server]` lines (lines 353 and 475-492) and `[service] lifecycle` (lines 477 and 519) run on the main thread.
- `run_random_cache_worker` runs on a `threading.Thread` (line 496).
None of these sets an id, so none carries one.

**Dependents.** None.

**Risk.** Low. If any code path ever calls `set_request_id` on the main thread before `serve_forever`, startup records would carry it.
</impact>
<impact path="engine/server/api/http_utils.py" element="respond_json / respond_options">
**Change.** None. Both call `handler.send_response`, which feeds the new `log_request` status capture.

**Dependents.** Every Engine route.

**Risk.** Low. A route that wrote a response without `send_response` would show `status="-"`; none exists (a grep finds no `send_error` or raw writes).
</impact>
<impact path="client/backend/lib/request_context.py" element="new module (threading.local set/fetch/clear plus resolver)">
**Change.** New file. It holds:
- a `threading.local`;
- `set`/`fetch`/`clear` for the id;
- a copy of the Engine's pattern constant and resolver;
- a `rat-tail` comment naming `engine/server/api/request_context.py`, in the style of `server.py:120`.

It must be importable as `lib.request_context`. The lib modules use relative imports (`from .time_utils import now_ms`), so `engine_api_client.py` should use `from .request_context import …`, and `server.py` should use `from lib.request_context import …`.

**Dependents.** `server.py`, `lib/engine_api_client.py`, the cross-service test, and the in-process Client used by tests (`tests/active/conftest.py:37-43` adds `client/backend` to `sys.path`).

**Risk.** `tests/check-client-engine-boundary.sh` fails on `from engine.` / `import engine.` / `from engine ` text anywhere in `client/backend/*.py`, comments included (the regex `(^|\s)from\s+engine(\.|\s)`), and on any `engine/server/db/` text. The rat-tail must not say e.g. "copied from engine server…". Naming the path `engine/server/api/request_context.py` is safe.
</impact>
<impact path="client/backend/server.py" element="ClientBackendHandler.do_GET / do_POST / do_OPTIONS and the new lifecycle wrapper">
**Change.** All three (lines 350-474) route through a wrapper. In order, the wrapper:
1. resolves the id and sets it in the Client context;
2. resets the status slot;
3. emits `request.start` through `_emit_client_log(INFO, "request.start", "request started", {ip, method, url[, user_agent]})`, with ip from `_get_client_ip()` → `resolve_client_address`;
4. runs the body;
5. in `finally`, emits `request.end` with `{status, duration_ms}` and clears the context.

The id must be set before `_rate_limit_check`, `mint_rate_limiter`, `_require_profile` and `read_json_body`.

**Dependents.**
- Every Client route.
- The `client_backend` / `engine_client` / `unpublished_client` fixtures (`tests/active/conftest.py`).
- Many live-HTTP tests in `tests/active/test_server.py`. These assert on responses, not log lines, so they are unaffected.

**Risk.**
- Exceptions must still propagate.
- `_get_client_ip` reads `self.server.trusted_proxies` and `self.headers`, which are fine inside `do_*`.
- The Client now logs one more line per request.
</impact>
<impact path="client/backend/server.py" element="ClientBackendHandler.log_message() and new log_request() override">
**Change.**
- `log_message` (lines 333-348) currently emits `client.access` "request finished" with ip, method, url, status (str) and bytes (str). It becomes a WARNING `_emit_client_log(…, "client.http", …)`, only for `log_error` calls.
- A new `log_request` records an int status and logs nothing.

**Dependents.** The `tests/active/test_server.py` client-log tests (via `_log_records` and `CLIENT_LOG_JSON_PAYLOADS`), and `client/watch-client-logs.sh` (no event names, so unaffected).

**Risk.** As in the Engine, `log_error` before headers are parsed means `self.headers` and possibly `self.server`-derived data are unavailable. Today's `log_message` already calls `_get_client_ip()`, which reads `self.headers`. The new `client.http` must not read headers, or it raises inside `send_error`.
</impact>
<impact path="client/backend/server.py" element="ClientLogFormatter.format()">
**Change.** Read the Client context at format time and, when an id is set, add a top-level `request_id` after `context` and before `traceback` (lines 174-189). Add the thread-local/QueueHandler comment. The mirrored `_render_text` (lines 148-161) already appends `request_id=` when the key is present, so the rat-tail copies `_format_ts`, `_text_value`, `_render_text` and `normalize_log_format` stay byte-identical.

**Dependents.**
- `configure_client_logging`.
- `tests/active/test_server.py` asserts exact key lists: `LOG_EMIT_KEYS` / `LOG_BARE_KEYS` (lines 1119-1120) and `CLIENT_LOG_JSON_PAYLOADS` (lines 1124-1129). Those tests log from the pytest main thread, where no id is set, so no key is added. That assumption must hold.
- `test_client_format_ts_and_render_text_return_the_engines_strings` (line 1295).

**Risk.**
- If the Client context is ever set on pytest's main thread (for example a test calling the wrapper directly without clearing), later key-order tests gain `request_id` and fail.
- The JSON key order changes only when an id exists.
- Records from `_publish_to_engine_bridge` and `engine.proxy` / `engine.call` gain the id, which is the intent.
</impact>
<impact path="client/backend/server.py" element="_proxy_engine_request() headers dict (line 674)">
**Change.** Add `x-request-id` next to `x-client-ip`, taken from the Client context. The `Request` is built once (lines 681-686) and reused across the retry loop (line 688), so every attempt sends the same id.

**Dependents.**
- Every proxied GET/POST read, through `_handle_engine_read_proxy_get` and `_handle_engine_read_proxy_post`.
- Stub Engines in `tests/active/test_server.py` (e.g. lines 440-449, which record `x-client-ip`) read individual headers. None compares the whole header set (grep).

**Risk.**
- If the context is empty (direct unit calls with no wrapper), the header must be omitted, not sent as `"None"` or empty.
- The header name must match the Engine's `X-Request-ID`. Header lookup in http.server is case-insensitive.
</impact>
<impact path="client/backend/lib/engine_api_client.py" element="bridge_headers()">
**Change.** Add `X-Request-ID` when the Client context holds an id, via a relative import of the new module.

**Dependents.** Every bridge call:
- `_post_json` (line 39), used by `resolve_video_seed`, `fetch_metadata_for_entries` and `compute_dislike_centroids`;
- `client/backend/server.py:1141` `_publish_to_engine_bridge`.

**Risk.**
- The docstring says "every bridge call site must go through here". Keep the token logic unchanged.
- In tests that call `_publish_to_engine_bridge` directly on the main thread (`tests/active/test_server.py` around lines 1090-1104), no id is set, so no header is sent. That is correct.
- Adding an import here creates a lib-internal dependency. With a relative import, no cycle results.
</impact>
<impact path="client/backend/server.py" element="_publish_to_engine_bridge(), main() lifecycle records">
**Change.** No code change.
- `_publish_to_engine_bridge` inherits the header through `bridge_headers()`.
- `service.start` / `service.stop` (lines 1295 and 1313) run on the main thread and carry no id.

**Dependents.** None.

**Risk.** Low.
</impact>
<impact path="client/backend/lib/http_utils.py" element="respond_json / respond_bytes / respond_options and ALLOWED_REQUEST_HEADERS">
**Change.** None. These call `send_response`, which feeds `log_request`. `ALLOWED_REQUEST_HEADERS` (`content-type, x-profile-key`) does not list `x-request-id`.

**Dependents.** The CORS dev setup.

**Risk.** Low. The browser never sends `X-Request-ID` (nginx sets it). In the cross-origin Vite dev setup the browser sends none either, so the Client generates one. No change is needed, but a future frontend that sets the header cross-origin would be blocked by the preflight.
</impact>
<impact path="engine/watch-engine-logs.sh" element="JQ_FILTER access branches (lines 135-138)">
**Change.** `.event == "access"` becomes `"request.end"`, and `"access.start"` becomes `"request.start"`. The `sub("^\\[access…\\]")` message strips become `[request.end]` / `[request.start]`. They are effectively no-ops, because the formatter already rewrites the message to "request started" / "request finished".

**Dependents.** Operators. DEPLOYMENT.md line 125 references the script.

**Risk.** Low. If not updated, records still show, unstripped.
</impact>
<impact path="client/watch-client-logs.sh" element="jq filter">
**Change.** None: `fromjson? // {"raw": .}` names no event. Read in full and confirmed.

**Dependents.** None.

**Risk.** None.
</impact>
<impact path="engine/install-engine-service.sh" element="engine_listener_text() (lines 249-272)">
**Change.** None. The only header directive is `proxy_set_header Host $http_host` (line 266). There is no `proxy_pass_request_headers off` and no `underscores_in_headers`, and a grep of every `*.sh` finds no other `proxy_set_header`. `X-Request-ID` therefore passes through to the Engine unchanged.

**Dependents.** The prod listener on 7079.

**Risk.** None for this build. The listener's own access log (line 259) keeps the default format without the id, which is out of scope.
</impact>
<impact path="DEPLOYMENT.md" element="nginx public site block (lines 394-432)">
**Change.**
- Add a `log_format` with `request_id=$request_id upstream=$upstream_addr rt=$request_time` above `server {`.
- Add `access_log /var/log/nginx/peertube-browser.access.log <fmt>;` inside `server`.
- Add `proxy_set_header X-Request-ID $request_id;` in each of `/api/`, `/recommendations`, `/videos/similar` and `/client/`.

**Dependents.** Operators copying the block, and `certbot --nginx` (lines 501-503), which edits the server block.

**Risk.**
- `log_format` must be outside `server{}` (legal because `sites-enabled/*` is included in `http{}`), and its name must be unique across `http{}`: a duplicate name fails `nginx -t`.
- `proxy_set_header` in a location disables inheritance from server level, so it must be repeated in all four locations.
</impact>
<impact path="DEPLOYMENT.md" element="LOG_FORMAT paragraph (line 116), Triage (lines 195-229), Engine listener text (line 472), up-next log lines (line 333), X-Forwarded-For paragraph (line 436)">
**Change.**
- **Line 116:** cross-link the new "Follow one request" runbook.
- **Triage:** add the runbook, with:
  - the nginx grep;
  - `journalctl -u peertube-client.service -o cat | jq -cR --arg id … 'fromjson? | select(.request_id == $id)'`;
  - the same for `'peertube-engine@*'`;
  - the text-mode grep;
  - what each log is for;
  - the caveats: several Engine pairs per id (retry, bridge calls), and a different id when the header was malformed.
- **Line 472:** already says `X-Request-ID` reaches the Engine "as the Client sent them". Reword it to say the Client sends it and the listener passes it through.
- **Line 333:** `[similar-server][<id>] upnext_pool`. The `<id>` is now the shared request id; worth a note.
- **Line 436:** "keys its rate limiters and access log" now means the `request.start` `ip`. Optional wording.

**Dependents.** Operators.

**Risk.** Doc-only. The jq recipe must match the real key (top-level `request_id` in both services).
</impact>
<impact path="tests/active/test_logging_profiles.py" element="_TS_CHILD, _LOG_FORMAT_CHILD, JSON_PAYLOADS, text assertion, _request_records, durable ts test, module docstring">
**Change.**
- **Probes:** the `[access.start]` probes at lines 59 and 83 become `request.start` records logged with the structured-context extra, including a `user_agent` with spaces.
- **`JSON_PAYLOADS[3]`** (line 93) becomes event `request.start` with the structured context.
- **Line 152** expects message "request started"; that is unchanged.
- **Text assertion (line 243):** becomes `INFO request.start request started ip=… method=… url=… user_agent=… request_id=rid-a`.
- **`_request_records` / `test_engine_request_ts_never_decreases_from_access_start_to_access`** (lines 169-205): find the `request.start` whose `context.url` holds the marker, take its `request_id`, and find the `request.end` with the same `request_id` (`request.end` has no url). Then filter the records between them to `request.*` and `recommendations.*`.
- **Docstring** (lines 5-7): update.
- **New tests:** Validation 1 (shared id across the Client and session Engine logs) and the Engine 503 handler test may land here or in `test_server.py`.

**Dependents.** `tests/last_test_validation.json` ids.

**Risk.**
- The session Engine log is shared by every test in the session. Matching `request.end` by id is safe only if the id is unique, which a fresh uuid4 is, since `engine.request` sends no `X-Request-ID`.
- `_epoch` ordering is unchanged.
</impact>
<impact path="engine/server/api/tests/test_logging_profiles.py" element="tearDown, test_access_start_is_tagged…, test_access_message_does_not_duplicate_context, test_smoke_stream…">
**Change.**
- **tearDown (line 30):** add `set_request_id(None)` after `clear_request_context()`.
- **`test_access_start_is_tagged…` and `test_access_message_does_not_duplicate_context`** (lines 65-86): rewrite for `[request.start]` / `[request.end]` with the structured extra. The `request.end` context is `status` and `duration_ms`; there is no url and no bytes, so drop the `context["url"]` assertion.
- **Smoke stream** (line 150): `[access] …` becomes a `[request.end]` record, and the expected event set (lines 161-171) changes `"access"` to `"request.end"`.
- **New tests:** add the R2 resolver unit cases here, or in the cross-service test.

**Dependents.** Run with the Engine interpreter or unittest.

**Risk.** Without the tearDown change, `test_request_id_is_taken_from_request_context` (`set_request_id("7f33a0")`) leaks its id into later tests' payloads. No current test asserts absence, so the leak is silent rather than a failure.
</impact>
<impact path="engine/server/api/tests/test_recommendations_likes_limit.py" element="patch.object(similar, 'clear_request_context') call-count assertions">
**Change.** None needed. `_handle_similar_request` keeps its inner `clear_request_context()` call, and these tests call it directly on a `_DummySimilarHandler`, outside any wrapper.

**Dependents.** None.

**Risk.** It breaks only if the implementation moves or removes the inner clear, or renames the module-level name.
</impact>
<impact path="tests/active/test_server.py" element="CLIENT_LOG_JSON_PAYLOADS, _log_records, text-mode access assertion, module docstring (lines 110-115)">
**Change.**
- **`CLIENT_LOG_JSON_PAYLOADS[3]`** (line 1128): `client.access` / "request finished" with `{"ip","status","bytes"}` becomes `request.end` / "request finished" with `{"status": 200, "duration_ms": …}`, or a `request.start` with a spaced `user_agent` per R9.
- **`_log_records`** (line 1199): same change.
- **Text assertion** (line 1292): `INFO client.access request finished ip=127.0.0.1 status=200 bytes=-` gets the new shape.
- **Docstring** (lines 113-114): update.
- **Rename:** the variable `access` in `test_client_log_format_text_writes…` (line 1286) needs a matching rename.

**Dependents.** `tests/last_test_validation.json`.

**Risk.** These tests run on the pytest main thread with no Client id, so no top-level `request_id` appears. Keep it that way, or the exact key/order assertions fail.
</impact>
<impact path="tests/active/test_server.py" element="new tests: Client-side wrapper, keep-alive non-leak (Validation 5), Client→Engine propagation, cross-service resolver check">
**Change.**
- **Keep-alive test:** a test-only `ClientBackendHandler` / `SimilarHandler` subclass with `protocol_version = "HTTP/1.1"`, sending two requests over one `http.client.HTTPConnection`. It asserts:
  - a distinct id per request;
  - no stale status;
  - the context is cleared.
- **Propagation tests**, with stub Engines (pattern as at lines 440-449) recording `X-Request-ID`:
  - the proxy (including a retry, where both attempts carry the same id);
  - `bridge_headers` / `_post_json`;
  - `_publish_to_engine_bridge`.
- **Cross-service test:** compare the two pattern strings and the accept/reject samples (`"abc\n"`, a 65-character id, an empty value, spaces, unicode).
- **Validation 1 (Client side):** attach a `ClientLogFormatter` handler to the root logger.

**Dependents.** The conftest fixtures.

**Risk.**
- Pytest's root logger is not at INFO by default. `_emit_client_log` calls `logging.log(INFO)`, which root drops unless the test sets the level, as `_client_logging` does at lines 1158-1175, and then restores handlers and level.
- Importing the Engine's `request_context` into the pytest process by putting `engine/server/api` on `sys.path` risks shadowing: conftest already imported the Client's `server` as `server`, and the Engine API dir also has `server.py` and `http_utils.py`. Use a subprocess child (the existing pattern) or `importlib.util.spec_from_file_location`.
- For an Engine `SimilarHandler` subclass under HTTP/1.1, `respond_options` sends a 204 with no content-length, which is valid.
</impact>
<impact path="tests/active/test_similar.py" element="START_LINE/POOL_LINE regexes, _pools_with_fallbacks docstring, _DEBUG_CHILD/_FAILING_SIMILAR_CHILD doubles, _LIKES_CHILD">
**Change.**
- No required code change.
- **Doubles:** the `_handle_similar` doubles (lines 428-456 and 538-565) now log `[similar-server][-] start…`, because `fetch_request_id()` is `None`. They still pass on `"] start limit=20"`.
- **`_LIKES_CHILD`** (line 326) keeps clear count 0 or 1.
- **Regexes:** `START_LINE` / `POOL_LINE` `(\w+)` match uuid4 hex.
- **Docstring:** line 834 ("ann_fallback lines carry no id") is now stale. They carry a top-level `request_id`, though not in the message.

**Dependents.** None.

**Risk.** Low. It would break only if those requests were routed through a Client or given an `X-Request-ID` with `.` or `-`.
</impact>
<impact path="tests/active/conftest.py" element="engine fixture log file, ClientBackend.request, _engine_client">
**Change.** Probably none. `ClientBackend.request` already accepts `headers`, so a test can send `X-Request-ID`. The session Engine log (`engine.db_path`, which is the log path) is what the durable and Validation 1 tests read.

**Dependents.** All active tests.

**Risk.** Low. If Validation 1 needs the Client's log, attach a handler in the test rather than changing the fixture.
</impact>
<impact path="tests/check-client-engine-boundary.sh" element="import/DB-coupling grep over client/backend/*.py">
**Change.** None. It scans the new `client/backend/lib/request_context.py`.

**Dependents.** `tests/run-arch-split-smoke.sh` (line 422).

**Risk.** It fails if the rat-tail comment or any code in the new file contains `from engine ` / `from engine.` / `import engine` / `engine/server/db/` text.
</impact>
<impact path="tests/last_test_validation.json" element="recorded test ids">
**Change.** This is a generated artifact. Renamed tests (e.g. `test_engine_request_ts_never_decreases_from_access_start_to_access`, line 1194) leave stale ids until it is regenerated.

**Dependents.** The dev-flow validation step.

**Risk.** Low. Regenerate it; do not hand-edit.
</impact>
<impact path="delete_me/test_19_timestamped_request_logs_phase4.py" element="scratch tests and backups in delete_me/ (also phase1-3, test_probe_19_p4.py, *.bak-trl-*)">
**Change.** None planned. These scratch files assert `access.start` / `client.access` and will fail if collected. No pytest config limits `testpaths`, so `pytest` from the repo root would collect `delete_me/test_*.py`.

**Dependents.** None in the product.

**Risk.** Low to medium: a confusing red run if someone runs bare `pytest`. Leave them, or confirm they are excluded. Uncertain whether the dev flow runs only `tests/active`.
</impact>
<impact path="docs/project/issues/20-request-lifecycle-logs.md" element="Status line and Comments">
**Change.** The dev flow updates the status (it is currently `enhancement, needs-triage`), and the issue moves to `archive/` on completion per `docs/project/triage-labels.md`.

**Dependents.** `docs/project/issues/plan.md`, and issue 21, which builds on the nginx id.

**Risk.** Doc-only.
</impact>
<impact path="client/README.md" element="LOG_FORMAT (line 72), TRUSTED_PROXIES access-log wording (line 68), proxy retry (line 30)">
**Change.**
- **Line 72:** document the `request.start` / `request.end` / `client.http` events, the top-level `request_id`, and the `X-Request-ID` the backend forwards to the Engine (proxy and bridge).
- **Line 68:** "access log" now means `request.start`'s `ip`.
- **Line 30:** a retried read produces two Engine start/end pairs under one id.

**Dependents.** Readers.

**Risk.** Doc-only.
</impact>
<impact path="engine/server/README.md" element="Notes (around line 31)">
**Change.** Optional: note that every request logs `request.start` / `request.end` with a `request_id` taken from a valid `X-Request-ID` (`[A-Za-z0-9._-]{1,64}`), or generated. I am unsure whether the README's scope covers logging. It already discusses log records at line 31.

**Dependents.** Readers.

**Risk.** Doc-only.
</impact>
<impact path="docs/project/adr/0009-engine-blue-green-through-nginx-upstream-snippet.md" element="decision 1 (headers passed through unchanged)">
**Change.** None. It already states the listener passes request headers through unchanged, which the plan relies on. ADR-0002 (`docs/project/adr/0002-trusted-proxy-client-address.md`) mentions the "access log" and stays accurate.

**Dependents.** None.

**Risk.** None.
</impact>
<impact path="CONTEXT.md" element="glossary">
**Change.** Optional new term **Request id**: the correlation id nginx sets, the Client and Engine reuse when valid and generate otherwise, and every record of one request carries. It is not unique and not authenticated. I am unsure whether the glossary owner wants operational terms. Existing entries include deploy-level terms (Active instance, Upstream snippet), so it fits.

**Dependents.** None.

**Risk.** Doc-only.
</impact>
</impacts>

## Documentation to update

- [x] `DEPLOYMENT.md` - updated: I updated DEPLOYMENT.md: the nginx site block now sets and logs `X-Request-ID`, the Triage section has a new "Follow one request" runbook, and the four sentences that still described the old logging are fixed.
- [x] `client/README.md` - updated: I updated `client/README.md` to cover the request lifecycle records, the request id rule, and how the id is forwarded on Engine calls. I checked each statement against `client/backend/server.py`, `client/backend/lib/engine_api_client.py` and `client/backend/lib/request_context.py`.
- [x] `engine/server/README.md` - updated: I added one Notes point to `engine/server/README.md` on the Engine's per-request log records and the request id.
- [x] `docs/project/issues/20-request-lifecycle-logs.md` - updated: Issue 20 is marked complete and its file is at `docs/project/issues/archive/20-request-lifecycle-logs.md`, with a delivery comment added. The old file is still in place because I can't delete files.
- [x] `CONTEXT.md` - updated: I added a **Request id** term to the `CONTEXT.md` glossary.
- [x] `docs/project/issues/plan.md` - updated: `docs/project/issues/plan.md` now lists issue 20 as delivered in three places: the triage recommendation, the P5 tier and wave lane 4c.
- [x] `docs/project/adr/0009-engine-blue-green-through-nginx-upstream-snippet.md` - out of scope: Decision 1 says the 7079 listener passes request headers through unchanged. The build relies on that and does not change it: `engine_listener_text()` sets only `Host`. It is still accurate.
- [x] `docs/project/adr/0002-trusted-proxy-client-address.md` - out of scope: It records the decision that every use of the client address, the access log included, goes through one rule. The Client's `request.start` `ip` still comes from `resolve_client_address`, so the decision holds. Its "access log" wording describes the state at the time of the decision, and an ADR is not rewritten for a later log rename.

## Implementation plan

## Draft: issue 20, request lifecycle logs with a shared `request_id`

Read before drafting: `engine/server/api/request_context.py`, `handlers/similar.py` (handler head, dispatch, search, `_handle_similar` id lines, `_make_request_id`), `logging_profiles.py`, `http_utils.py` (both services), `client/backend/server.py` (formatter, handler, proxy), `lib/engine_api_client.py`, `engine/watch-engine-logs.sh`, `tests/check-client-engine-boundary.sh`, DEPLOYMENT.md site block / 116 / 472 / Triage, both `test_logging_profiles.py` probes, the client log tests in `tests/active/test_server.py`, the `SimilarServer` child pattern in `tests/active/test_video.py`, and the conftest fixtures. The template's ladder line came through as an unfilled `{rat_tail_ladder}` placeholder. This draft therefore uses the repo's existing rat-tail convention (`server.py:120`): name the mirror, name the cross-check test, and name the upgrade path.

### What has to be tested (derived before drafting)

| # | Behaviour | Where it is proven |
|---|---|---|
| T1 | Resolver: accepts `[A-Za-z0-9._-]{1,64}` exactly. Rejects None, `""`, `" "`, `"abc\n"`, `"a b"`, 65 chars, `"é"`, `"a/b"`, `"[x]"`, `"abc\r\nX: y"`, and returns 32-hex for them. Engine and Client pattern strings are equal. | cross-service test, `tests/active/test_server.py` |
| T2 | Engine wrapper: one `request.start` first and one `request.end` last per request. The id comes from a valid header and is generated otherwise. A bad header value appears in no record. 404 / 429 / 400 / 503 each end with `status` and `duration_ms` and no `bytes`. Every record between start and end carries the id. | Engine child server test, `tests/active/test_logging_profiles.py` |
| T3 | Engine keep-alive: two requests on one HTTP/1.1 connection get distinct ids, neither leaks, and the status is not stale. | same child, HTTP/1.1 subclass |
| T4 | Client wrapper: as T2 for `/api/health`, 404, 429 and 400 (bad JSON on `/api/user-action`). | `tests/active/test_server.py` |
| T5 | Client keep-alive | `tests/active/test_server.py`, HTTP/1.1 subclass |
| T6 | Client→Engine: proxy (including a retry, both attempts carry the same id), `_post_json` through `bridge_headers`, and `_publish_to_engine_bridge` all send `X-Request-ID` = the Client's id. Each omits the header when no id is set. | stub-Engine tests, `tests/active/test_server.py` |
| T7 | Validation 1 / 2 end-to-end: Client + session Engine, with the same id in both services' start…end, for POST `/recommendations` and `/api/video`, plus `/api/health` (Client only). The same with no header gives one generated 32-hex id in both. | `tests/active/test_server.py` with `engine_client` |
| T8 | Formatter: the structured-context extra keeps a spaced `user_agent` whole in JSON. Text keeps CR/LF escaping. Key order is unchanged. | both `test_logging_profiles.py` |
| T9 | Issue-19 durable property over `request.start` → `recommendations.*` → `request.end` | rewritten durable test |
| T10 | Docs: the nginx block sets and logs `$request_id`, and the runbook exists. | review (Validation 6) |

### Module map

| File | Change |
|---|---|
| `engine/server/api/request_context.py` | Adds `REQUEST_ID_HEADER`, `REQUEST_ID_PATTERN` and `resolve_request_id`. `clear_request_context` no longer clears the id. |
| `engine/server/api/handlers/similar.py` | Adds the `_run_request` wrapper, `_serve_get` / `_serve_post` / `_serve_options`, `log_request`, and the `[http]` `log_message`. Removes `_log_access_start` (and its 3 calls) and `_make_request_id`. `_handle_similar` reads the shared id. |
| `engine/server/api/logging_profiles.py` | Adds the `structured_context` extra and renames the two rules and branches to `request.*`. |
| `engine/watch-engine-logs.sh` | Renames the two jq branches. |
| `client/backend/lib/request_context.py` | **new**: thread-local id plus the resolver copy (rat-tail). |
| `client/backend/server.py` | Adds the wrapper, `log_request`, the `client.http` `log_message`, the formatter `request_id`, and the proxy header. |
| `client/backend/lib/engine_api_client.py` | `bridge_headers()` adds `X-Request-ID`. |
| tests | see the Tests section |
| `DEPLOYMENT.md`, `client/README.md`, `engine/server/README.md`, `CONTEXT.md`, issue 20 | see the Docs section |

No new dependency. Stdlib only: `re`, `uuid`, `threading`, `time`.

### `engine/server/api/request_context.py`

```python
"""Provide request context runtime helpers."""

import re
import threading
import uuid
from typing import Any

_REQUEST_CONTEXT = threading.local()

REQUEST_ID_HEADER = "X-Request-ID"
# Ids are for log correlation only: neither unique nor authenticated. nginx's $request_id (32 hex) fits, and no character here can break a log line or the `[scope][id]` prefix.
REQUEST_ID_PATTERN = r"[A-Za-z0-9._-]{1,64}"
_REQUEST_ID_RE = re.compile(REQUEST_ID_PATTERN)
```

```python
def resolve_request_id(header_value: str | None) -> str:
    """Return `header_value` when it fully matches REQUEST_ID_PATTERN, else a fresh uuid4 hex; a rejected value is never logged."""
    # fullmatch, not match with ^…$: `$` also matches before a trailing newline, so "abc\n" would pass.
    if header_value and _REQUEST_ID_RE.fullmatch(header_value):
        return header_value
    return uuid.uuid4().hex
```

Changes to `clear_request_context`:
- The docstring becomes "Clear request-scoped likes, centroids, excluded keys and the NSFW flag; the request id belongs to the handler's request wrapper, which clears it with `set_request_id(None)`."
- Lines 75-76 are deleted.

`set_request_id` and `fetch_request_id` are unchanged. The imports stay stdlib-only, so the two subprocess tests that run `logging_profiles` under pytest's interpreter still pass.

Invariant: header values reach `resolve_request_id` unstripped. A value with surrounding spaces is rejected, not trimmed. That matches R2 ("fully matches").

### `engine/server/api/handlers/similar.py`

Imports:
- `from typing import Any, Callable`.
- The `request_context` import list gains `REQUEST_ID_HEADER` and `resolve_request_id`.
- `set_request_id` and `clear_request_context` stay (the wrapper uses them).
- `import numpy as np` stays (`_draw_page`, `_parse_dislike_centroids`).

On `SimilarHandler`:

```python
    # Status sent for the current request, read by request.end; reset per request because keep-alive reuses one handler instance per connection.
    _response_status: int | None = None
```

```python
    def _run_request(self, serve: Callable[[], None]) -> None:
        """Run one request between its request.start and request.end records; the only place its id is set and cleared."""
        # First act, so rate-limit, bridge-auth, body-read and statement-deadline records all carry the id.
        set_request_id(resolve_request_id(self.headers.get(REQUEST_ID_HEADER)))
        self._response_status = None
        started = perf_counter()
        try:
            context = {"ip": self._get_client_ip(), "method": self.command or "-", "url": self._get_full_url()}
            user_agent = self.headers.get("User-Agent", "").strip()
            if user_agent:
                context["user_agent"] = user_agent
            logging.info("[request.start] request started", extra={"structured_context": context})
            serve()
        finally:
            status = self._response_status if self._response_status is not None else "-"
            duration_ms = int((perf_counter() - started) * 1000)
            # Logged before the clear, or request.end loses its id; exceptions still propagate to socketserver's handle_error.
            logging.info("[request.end] request finished", extra={"structured_context": {"status": status, "duration_ms": duration_ms}})
            clear_request_context()
            set_request_id(None)
```

Wrapper decisions:
- The start record is built inside the `try`. If building it ever raised, the id would still be cleared and `request.end` still logged, so there is still exactly one end and no leak.
- The id is set before the `try` because `set_request_id` and `headers.get` cannot raise.

The three entry points become thin. Each existing body moves verbatim into a `_serve_*` method:

```python
    def do_OPTIONS(self) -> None:  # noqa: N802
        """Answer OPTIONS 204 with no CORS headers."""
        self._run_request(lambda: respond_options(self))

    def do_POST(self) -> None:  # noqa: N802
        """Handle similarity and internal bridge ingest endpoints under the time budget."""
        self._run_request(self._serve_post)

    def _serve_post(self) -> None:
        """Dispatch a POST under the time budget, answering 503 when its database work is interrupted."""
        try:
            with self._statement_deadline():
                self._dispatch_post()
        except sqlite3.OperationalError as exc:
            if not is_interrupted_error(exc):
                raise
            self._respond_interrupted()
```

`do_GET` / `_serve_get` mirror this with `_dispatch_get`. Separately, `self._log_access_start()` is deleted from the first line of `_dispatch_post` and `_dispatch_get`, and the `_log_access_start` method is deleted.

Status capture and the old access line:

```python
    def log_request(self, code: Any = "-", size: Any = "-") -> None:
        """Record the status send_response sent, for request.end; the wrapper owns the request's records, so nothing is logged here."""
        self._response_status = int(code)

    def log_message(self, format: str, *args: Any) -> None:
        """Log http.server's own errors (bad request line, 414, unsupported method, timeout) as one [http] warning; only log_error reaches here now."""
        # May run before the request line or headers were parsed, so it reads only the socket peer, never self.headers.
        peer = self.client_address[0] if self.client_address else "unknown"
        logging.warning("[http] %s", format % args, extra={"structured_context": {"peer": peer}})
```

Notes on these two:
- `code` is always an int or an `HTTPStatus` from `send_response`, so `int(code)` is safe.
- At WARNING, `_classify_event` derives `http.info`. This is the same convention as every other Engine warning (`statement.timeout.info`, `bridge.auth.info`), so no rule is added. That is a deliberate consistency choice; renaming every warning's suffix is out of scope.
- The structured extra stops `_extract_fields` from turning attacker-controlled request-line tokens such as `/?a=b` into context keys.

`_handle_similar` (around lines 1036-1046):
- `request_id = _make_request_id()` becomes `request_id = fetch_request_id() or "-"`, with a one-line comment: "The wrapper's id; `-` only for unit doubles that call this with no context."
- The `set_request_id(request_id)` line after the start log is deleted.
- `finally: clear_request_context()` stays. It now clears feed state only.

`_handle_similar_request`'s `finally: clear_request_context()` is unchanged, so the `patch.object(similar, "clear_request_context")` call counts still hold.

`_make_request_id` (lines 1239-1241) is deleted.

`_handle_search` is unchanged. It now passes the wrapper's id to moderation (a new INFO line when rows are filtered, noted in the docs).

Seams, all through `send_response`:
- `respond_json` and `respond_options` in `http_utils.py` feed `log_request`.
- `_respond_interrupted` runs inside `serve()`, so its `[statement.timeout]` warning and the 503 both land inside start…end.
- `_bridge_authorized` 401/503, `_rate_limit_check` 429, and `read_json_body` 400 likewise.

### `engine/server/api/logging_profiles.py`

The rules change:

```python
    _EventRule("[request.start]", "request.start", ("focused", "verbose")),
    _EventRule("[request.end]", "request.end", ("focused", "verbose")),
```

These replace the `access.start` / `access` rules. They stay first in the list. A grep finds no other `[request.` text in the engine.

In `EngineJsonFormatter.format`:

```python
        message = record.getMessage()
        event, modes = _classify_event(message, record.levelno)
        # request_id falls back to the thread-local context, read at format time: correct because StreamHandler formats on the emitting thread; a QueueHandler or any off-thread formatting would drop ids.
        request_id = _extract_request_id(record, message)
        structured = getattr(record, "structured_context", None)
        # A record that brings its own context keeps values with spaces (a user agent) whole; its message is not split into key=value tokens.
        fields = dict(structured) if isinstance(structured, dict) else _extract_fields(message)
```

The branches `access.start` / `access` become `request.start` → message "request started", and `request.end` → message "request finished". Each sets `payload["context"] = fields` when non-empty.

Unchanged:
- key order `ts, level, event, message, modes, request_id, context, traceback`;
- `_render_text`;
- `_extract_request_id`;
- `_REQUEST_PREFIX_RE`.

The extra name `structured_context` collides with neither a `LogRecord` attribute nor the `request_id` extra.

### `engine/watch-engine-logs.sh`

Lines 135-138 become:

```
  | if .event == "request.end" then
      .message |= sub("^\\[request\\.end\\]\\s*"; "")
    elif .event == "request.start" then
      .message |= sub("^\\[request\\.start\\]\\s*"; "")
```

### `client/backend/lib/request_context.py` (new)

```python
"""Hold the id of the request a Client thread is serving, and the rule that accepts an incoming X-Request-ID."""
from __future__ import annotations

import re
import threading
import uuid

_REQUEST_CONTEXT = threading.local()

# rat-tail: REQUEST_ID_HEADER, REQUEST_ID_PATTERN and resolve_request_id mirror engine/server/api/request_context.py (no shared module: the boundary check keeps Client and Engine code apart), so editing only one copy lets them drift; a cross-service test compares both, and a shared package is the upgrade once a third consumer appears.
REQUEST_ID_HEADER = "X-Request-ID"
# Ids are for log correlation only: neither unique nor authenticated. nginx's $request_id (32 hex) fits, and no character here can break a log line.
REQUEST_ID_PATTERN = r"[A-Za-z0-9._-]{1,64}"
_REQUEST_ID_RE = re.compile(REQUEST_ID_PATTERN)


def resolve_request_id(header_value: str | None) -> str:
    """Return `header_value` when it fully matches REQUEST_ID_PATTERN, else a fresh uuid4 hex; a rejected value is never logged."""
    # fullmatch, not match with ^…$: `$` also matches before a trailing newline, so "abc\n" would pass.
    if header_value and _REQUEST_ID_RE.fullmatch(header_value):
        return header_value
    return uuid.uuid4().hex


def set_request_id(request_id: str) -> None:
    """Store the id of the request this thread is serving."""
    _REQUEST_CONTEXT.request_id = request_id


def fetch_request_id() -> str | None:
    """Return the id of the request this thread is serving, or None outside a request."""
    return getattr(_REQUEST_CONTEXT, "request_id", None)


def clear_request_id() -> None:
    """Forget this thread's request id; the handler's request wrapper calls it when the request ends."""
    if hasattr(_REQUEST_CONTEXT, "request_id"):
        delattr(_REQUEST_CONTEXT, "request_id")
```

Boundary check: the file contains no `from engine`, `import engine` or `engine/server/db/` text. The rat-tail names `engine/server/api/request_context.py`, which the regexes allow.

### `client/backend/lib/engine_api_client.py`

- Import: `from .request_context import REQUEST_ID_HEADER, fetch_request_id`. The relative import is the lib convention, and it creates no cycle.
- In `bridge_headers()`, after the token block:

```python
    request_id = fetch_request_id()
    # Carries the serving request's id so the Engine's records for this call share it; omitted outside a request.
    if request_id:
        headers[REQUEST_ID_HEADER] = request_id
```

- The docstring's `:returns:` becomes "Content type, the bridge token when one is configured, and the request id when the call is made while serving a request."
- This covers `_post_json` (resolve, metadata, centroids) and `_publish_to_engine_bridge`.

### `client/backend/server.py`

The import is `from lib.request_context import REQUEST_ID_HEADER, clear_request_id, fetch_request_id, resolve_request_id, set_request_id`, placed alphabetically in the `lib.` block between `lib.profiles` and `lib.time_utils`.

`ClientLogFormatter.format`: after the `context` block and before `traceback`:

```python
        # Additive like traceback, read from this thread's request context at format time: correct because StreamHandler formats on the emitting thread; a QueueHandler would drop the id.
        request_id = fetch_request_id()
        if request_id:
            payload["request_id"] = request_id
```

The rat-tail copies `_format_ts`, `_text_value`, `_render_text` and `normalize_log_format` are untouched. `_render_text` already appends `request_id=`.

`ClientBackendHandler`:

```python
    # Status sent for the current request, read by request.end; reset per request because keep-alive reuses one handler instance per connection.
    _response_status: int | None = None

    def _run_request(self, serve: Callable[[], None]) -> None:
        """Run one request between its request.start and request.end records; the only place its id is set and cleared."""
        # First act, so rate-limit, profile-auth, body-read and proxy records all carry the id.
        set_request_id(resolve_request_id(self.headers.get(REQUEST_ID_HEADER)))
        self._response_status = None
        started = time.perf_counter()
        try:
            context = {"ip": self._get_client_ip(), "method": self.command or "-", "url": self._get_full_url()}
            user_agent = self.headers.get("User-Agent", "").strip()
            if user_agent:
                context["user_agent"] = user_agent
            _emit_client_log(logging.INFO, "request.start", "request started", context)
            serve()
        finally:
            status = self._response_status if self._response_status is not None else "-"
            duration_ms = int((time.perf_counter() - started) * 1000)
            # Logged before the clear, or request.end loses its id; exceptions still propagate to socketserver's handle_error.
            _emit_client_log(logging.INFO, "request.end", "request finished", {"status": status, "duration_ms": duration_ms})
            clear_request_id()

    def log_request(self, code: Any = "-", size: Any = "-") -> None:
        """Record the status send_response sent, for request.end; the wrapper owns the request's records, so nothing is logged here."""
        self._response_status = int(code)

    def log_message(self, format: str, *args: Any) -> None:
        """Log http.server's own errors (bad request line, 414, unsupported method, timeout) as one client.http warning; only log_error reaches here now."""
        # May run before the request line or headers were parsed, so it reads only the socket peer, never self.headers.
        peer = self.client_address[0] if self.client_address else "unknown"
        _emit_client_log(logging.WARNING, "client.http", format % args, {"peer": peer})
```

`Callable` comes from `typing`: `from typing import Any, Callable`.

`do_OPTIONS`, `do_GET` and `do_POST` become `self._run_request(lambda: respond_options(self))` / `self._run_request(self._serve_get)` / `self._run_request(self._serve_post)`. The current bodies (lines 354-408 and 410-474) move verbatim into `_serve_get` / `_serve_post`, docstrings "Route a GET request to its endpoint handler." / "Route a POST request to its endpoint handler.", with the `/client/events/publish` comment kept.

`_proxy_engine_request`, after the `headers = {...}` line (674):

```python
        request_id = fetch_request_id()
        # Built into the one Request every retry reuses, so each attempt carries the same id; omitted outside a request.
        if request_id:
            headers["x-request-id"] = request_id
```

The lowercase key matches the dict's style. urllib normalises it, and http.server lookup is case-insensitive.

`main()` lifecycle records and `_publish_to_engine_bridge` have no code change. The main thread never sets an id, so lifecycle records carry none.

### Tests

**`engine/server/api/tests/test_logging_profiles.py`**
- tearDown: `clear_request_context(); set_request_id(None)`.
- `test_access_start_is_tagged…` becomes `test_request_start_is_tagged_focused_and_verbose_and_keeps_a_spaced_user_agent`: log `[request.start] request started` with `structured_context={"ip","method","url","user_agent": "Mozilla/5.0 (X11; Linux x86_64)"}`; assert event, modes, and that context equals the dict.
- `test_access_message_does_not_duplicate_context` becomes the `request.end` version: context `{"status": 200, "duration_ms": 3}`, message "request finished", and no `url` / `bytes`.
- Smoke stream: `[access] …` becomes a `[request.end]` record with the extra, and the expected set's `"access"` becomes `"request.end"`.

**`tests/active/test_logging_profiles.py`**
- `_TS_CHILD` line 59 becomes `logging.info("[request.start] request started", extra={"structured_context": {"ip": "127.0.0.1", "method": "GET", "url": "http://x/a"}})`. The expected messages are unchanged.
- `_LOG_FORMAT_CHILD` line 83 becomes the same, plus `"user_agent": "Mozilla/5.0 (X11; Linux)"` and `extra request_id="rid-a"`.
- `JSON_PAYLOADS[3]` becomes `{"level":"INFO","event":"request.start","message":"request started","modes":["focused","verbose"],"request_id":"rid-a","context":{"ip":"127.0.0.1","method":"GET","url":"http://x/a","user_agent":"Mozilla/5.0 (X11; Linux)"}}`.
- The text assertion becomes `"INFO request.start request started ip=127.0.0.1 method=GET url=http://x/a user_agent=Mozilla/5.0 (X11; Linux) request_id=rid-a"`, and `access_start` is renamed `request_start`.
- `_request_records(log_path, marker)` returns the index of the one `request.start` whose `context.url` holds the marker, plus the index of the `request.end` whose `request_id` equals that start's.
- The durable test is renamed `test_engine_request_ts_never_decreases_from_request_start_to_request_end`. Its kept records are those between the two indexes with the same `request_id` whose event is `request.*` or `recommendations.*`. Its assertions are `events[0] == "request.start"` and `events[-1] == "request.end"`, plus the unchanged ts properties. `engine.request` sends no header, so the uuid4 id is unique in the shared session log.
- The module docstring is updated.
- New `_LIFECYCLE_CHILD`, run with the same child runner as `tests/active/test_video.py`'s `SimilarServer` children:
  - It starts a `SimilarServer` with `args` defaults on a temp DB and an `EngineJsonFormatter` handler on a `StringIO`.
  - It defines `KeepAliveHandler(SimilarHandler)` with `protocol_version = "HTTP/1.1"`.
  - It sends:
    - GET `/api/health` with a valid `X-Request-ID: probe.id-1`;
    - GET `/api/health` with no header;
    - GET `/api/health` with each of `"bad id"`, 65×`a` and `"a/b"`;
    - GET `/nope` (404);
    - GET `/api/channels` with `srv.rate_limiter` set to a stub whose `allow` returns False (429);
    - POST `/recommendations` with body `b"{"` (400);
    - GET `/api/health` through a handler subclass whose `_dispatch_get` raises `sqlite3.OperationalError("interrupted")` (503);
    - two GETs on one `http.client.HTTPConnection` to `KeepAliveHandler`.
  - It prints the records.
  - The parent asserts, per request id:
    - the first record is `request.start` and the last is `request.end`;
    - `request.end` context is exactly `{status, duration_ms}` with an int `duration_ms` and the expected status;
    - every record in the window has `request_id`;
    - the valid id is used verbatim;
    - the others are 32-hex;
    - no record's text contains `bad id`, the 65-char value, or `a/b` as `request_id`;
    - 503 has a `statement.timeout.info` WARNING inside the window;
    - the keep-alive pair has distinct ids, with no record of one carrying the other's id;
    - after the last request no record has an id (the context is cleared).

**`tests/active/test_server.py`**
- `CLIENT_LOG_JSON_PAYLOADS[3]` becomes `{"level":"INFO","service":"client-backend","event":"request.start","message":"request started","context":{"ip":"127.0.0.1","method":"GET","url":"http://x/a","user_agent":"Mozilla/5.0 (X11; Linux)"}}`.
- The `_log_records` 4th call is changed to match.
- The text assertion becomes `"INFO request.start request started ip=127.0.0.1 method=GET url=http://x/a user_agent=Mozilla/5.0 (X11; Linux)"`, and `access` is renamed `request_start`.
- The docstring (lines 113-114) is updated.
- All of these run on the pytest main thread, where no Client id is set, so `LOG_EMIT_KEYS` / `LOG_BARE_KEYS` hold. Every new test that sets the Client context clears it in `finally`.
- New `test_request_id_rule_is_the_same_in_client_and_engine`:
  - It loads the Engine module with `importlib.util.spec_from_file_location("engine_request_context", LOG_API_DIR / "request_context.py")`. No `sys.path` change, so there is no shadowing of `server` / `http_utils`.
  - It asserts equal `REQUEST_ID_PATTERN` and `REQUEST_ID_HEADER`, and the same accept/reject verdict from both resolvers on the T1 samples. A rejected value yields a 32-hex value that is not the input.
- New Client lifecycle tests, using the `client_backend` fixture plus `_client_logging(monkeypatch, None)`. `request.end` is logged after the response is written, so each test polls the stream until the `request.end` for the id appears (bounded wait). They cover:
  - `/api/health` with a valid id, with no id, and with malformed ids (`"bad id"`, 65 chars, `"a/b"`; CR/LF cannot go through `http.client`, so T1 covers it);
  - 404;
  - 429, by monkeypatching `ClientBackendHandler._rate_limit_check` to return False;
  - 400, from `/api/user-action` with an invalid JSON body.
  - The assertions match the Engine child's.
- New Client keep-alive test: a `ClientBackendServer` on port 0 with `KeepAliveClientHandler(ClientBackendHandler)` and `protocol_version = "HTTP/1.1"`, sending two GET `/api/health` on one connection.
- New propagation tests with stub Engines that record `X-Request-ID` (the pattern at lines 440-449):
  - proxied GET `/api/video` with a stub that drops the first connection, so both attempts carry the id;
  - `fetch_metadata_for_entries` called inside a thread that set the Client id;
  - `_publish_to_engine_bridge` likewise;
  - each of the three called with no id set sends no header.
- New Validation 1/2 test with `engine_client` (in-process Client → session Engine), `_client_logging` capturing the Client records, and the session Engine log file for the Engine side:
  - POST `/recommendations?limit=5` with `X-Request-ID: v1.<uuid hex>`;
  - GET `/api/video?id=…&host=…` with a dataset identity;
  - GET `/api/health`;
  - assert start…end order in the Client for all three, and in the Engine for the first two, with the same id;
  - repeat POST `/recommendations` with no header and assert one 32-hex id that appears in both services.

**`tests/active/test_similar.py`**: no code change. The stale docstring at line 834 becomes "the ann_fallback lines carry no id in the message; the top-level `request_id` comes from the context".

**`engine/server/api/tests/test_recommendations_likes_limit.py`**: unchanged.

**`tests/last_test_validation.json`**: regenerated, not hand-edited.

**`delete_me/`** scratch tests: left alone and not collected by the dev flow's `tests/active` run.

### Docs

**DEPLOYMENT.md site block.** Above `server {`:

```nginx
log_format peertube_browser_rid '$remote_addr - $remote_user [$time_local] "$request" '
                                '$status $body_bytes_sent "$http_referer" "$http_user_agent" '
                                'request_id=$request_id upstream=$upstream_addr rt=$request_time';
```

- In `server`: `access_log /var/log/nginx/peertube-browser.access.log peertube_browser_rid;`.
- In each of `/api/`, `/recommendations`, `/videos/similar` and `/client/`: `proxy_set_header X-Request-ID $request_id;`.
- A sentence after the block: the `log_format` sits outside `server` because the site file is included inside `http`. Its name must be unique in `http`. `proxy_set_header` in a location disables inheritance, so the line is in all four. nginx overwrites any id the browser sent.

**DEPLOYMENT.md line 116** gains: "To follow one request across nginx, the Client backend and the Engine, see *Follow one request* under Triage."

**DEPLOYMENT.md Triage** gains a `#### Follow one request` subsection after the table:

```bash
sudo grep "request_id=$id" /var/log/nginx/peertube-browser.access.log
journalctl -u peertube-client.service -o cat | jq -cR --arg id "$id" 'fromjson? | select(.request_id == $id)'
journalctl -u 'peertube-engine@*' -o cat | jq -cR --arg id "$id" 'fromjson? | select(.request_id == $id)'
# LOG_FORMAT=text
journalctl -u peertube-client.service -u 'peertube-engine@*' -o cat | grep "request_id=$id"
```

The runbook prose covers:
- Where to get `$id`: the nginx line or a `request.start` record.
- Each service reads `request.start` → work → `request.end`, ordered by `ts`.
- What each log is for: nginx gives bytes, upstream, `rt` and status as the network saw them; the apps give internal processing and `duration_ms`.
- Caveat: one Client request can show several Engine start/end pairs under the same id (proxy retry, bridge calls such as resolve or metadata).
- Caveat: a malformed `X-Request-ID` from a direct caller is replaced, so that service's id differs from the caller's.
- Requests http.server rejects before routing have only the nginx line and an `http.info` / `client.http` warning.

**DEPLOYMENT.md line 472** becomes: "Request headers pass through unchanged: `X-Client-IP`, `X-Bridge-Token`, and the `X-Request-ID` the Client sends with every Engine call reach the Engine as the Client sent them."

**DEPLOYMENT.md lines 333 and 436:** line 333's `<id>` is "the request's shared `request_id`". Line 436's "access log" becomes "`request.start` record".

**`client/README.md`:**
- Line 72 documents the `request.start` / `request.end` / `client.http` events, the top-level `request_id`, and the forwarding of `X-Request-ID` on proxied reads and bridge calls.
- Line 30 notes that a retried read shows two Engine pairs under one id.
- Line 68's "access log" becomes "`request.start` `ip`".

**`engine/server/README.md` Notes:** one sentence on `request.start` / `request.end` and the id rule.

**`CONTEXT.md`:** adds **Request id**: the correlation id nginx sets per request, which the Client and Engine reuse when it matches `[A-Za-z0-9._-]{1,64}` and generate otherwise, and which every record of that request carries. It is not unique and not authenticated.

**Issue 20:** the dev flow sets the status line and archives the issue.

### Check against plan and requirements

**Pass 1** found two gaps, both fixed above:
- (a) With the start record built outside the `try`, a raise there would leak the id under keep-alive, so the start record moved inside the `try`.
- (b) Reading `request.end` right after the HTTP response races its `finally`, so the Client and Engine tests poll.

**Pass 2** found no gaps:

| Req | Met by |
|---|---|
| R1 | Site block: four `proxy_set_header` lines, `log_format`, `access_log`. The 7079 listener is unchanged (verified in plan / impact). |
| R2 | `resolve_request_id` with `fullmatch` in both files; rat-tail; cross-check test. The rejected value is never passed to a log call. |
| R3 | Wrapper's first statement; `finally` clears; status reset per request; keep-alive tests on both services. |
| R4 | `request.start` fields; `structured_context` in the Engine, the context dict in the Client; text escaping unchanged. |
| R5 | `log_request` capture; `finally` end with `status` / `duration_ms`; `"-"` when nothing was sent; the old access lines are gone; `log_message` produces only warnings. |
| R6 | Engine context plus formatter; Client formatter `request_id`; main and worker threads never set one. |
| R7 | `bridge_headers` (`_post_json`, publish) and the proxy dict (one `Request`, so retries share the id). |
| R8 | `_make_request_id` deleted; `fetch_request_id()`; the `[similar-server][id]` format kept; the inner clear no longer drops the id. |
| R9 | Rules, branches, watcher, all listed tests. `watch-client-logs.sh` names no event. |
| R10 | Runbook, line 116 link, line 472 fix. |
| R11 | Single thread, program order; the durable test checks `ts` over start → work → end for one id. |

Constraints are met:
- stdlib only;
- each file's style followed (docstring-per-function, one-line comments, `# noqa: N802` kept);
- no response body change;
- no echo header;
- `LOG_FORMAT` behaviour preserved.

### Named simplifications and limits

- The id rule is duplicated in two files (rat-tail plus cross-check test). The upgrade path is a shared package once a third consumer appears.
- The Engine `[http]` warning is classed `http.info`, following the existing warning-suffix convention.
- CR/LF rejection is proven at resolver level only, because `http.client` refuses to send such headers.
- Keep-alive is proven on HTTP/1.1 test subclasses. Production stays on HTTP/1.0.
- Formatters read thread-locals at format time. A future `QueueHandler` would drop ids; both formatters carry a comment saying so.


### Phases

#### Phase 1 - Shared groundwork: structured context and id rule [code]

**Files touched.** engine/server/api/logging_profiles.py (EDITED), engine/server/api/request_context.py (EDITED), client/backend/lib/request_context.py (NEW), engine/server/api/tests/test_logging_profiles.py (EDITED), tests/active/test_logging_profiles.py (EDITED), tests/active/test_server.py (EDITED)

**Checkpoint.** Two checks. First, through the formatter: engine/server/api/tests/test_logging_profiles.py logs a `[request.start] request started` record with `structured_context={"ip","method","url","user_agent": "Mozilla/5.0 (X11; Linux x86_64)"}` through logging → EngineJsonFormatter. It asserts that `context` equals the dict and that a record without the extra still goes through `_extract_fields`. tests/active/test_logging_profiles.py's `_LOG_FORMAT_CHILD` subprocess (harness at line 72) emits the same record with `request_id="rid-a"` and asserts the JSON payload, then the text line, with the spaced user agent kept whole, key order `ts, level, event, message, modes, request_id, context, traceback` unchanged, and CR/LF escaping unchanged. Second, the id rule: the new `test_request_id_rule_is_the_same_in_client_and_engine` in tests/active/test_server.py loads engine/server/api/request_context.py with `importlib.util.spec_from_file_location` (no sys.path change). It asserts equal `REQUEST_ID_PATTERN` and `REQUEST_ID_HEADER`, and the same verdict from both `resolve_request_id`s on the T1 samples. Accepted values come back verbatim. None, "", " ", "abc\n", "a b", 65×"a", "é", "a/b", "[x]" and "abc\r\nX: y" each yield a 32-hex value that is not the input.

**Intent.** EngineJsonFormatter in engine/server/api/logging_profiles.py uses a record's `structured_context` extra as its context in place of splitting the message, and the Engine's request_context.py and the new client/backend/lib/request_context.py resolve an X-Request-ID by the same fullmatch rule.

- C1 - A record carrying a `structured_context` dict gets that dict verbatim as its `context`, so a user_agent containing spaces stays whole.
- C2 - The Engine's and the Client's `resolve_request_id` give the same verdict on every sample: the header value verbatim when it fully matches the shared pattern, otherwise a fresh 32-hex id.

**Outcome.** The checkpoint has not run yet; it runs when this is handed in. I did not run any tests during this step.

### `engine/server/api/logging_profiles.py`
- `EngineJsonFormatter.format` now looks for a `structured_context` extra on the log record.
- If that extra is a dict, a shallow copy of it becomes the record's context, in place of `_extract_fields(message)`. So a value with spaces, like a user agent, stays whole, an int stays an int, and the key order is kept. The message's own `key=value` tokens are not added.
- A record without the extra still has its message split into `key=value` fields, as before.
- Unchanged: the event branches (they still set `payload["context"] = fields` when it is not empty), the payload key order, `_render_text` and its CR/LF escaping, and `_extract_request_id`.

### `engine/server/api/request_context.py`
- Added `REQUEST_ID_HEADER = "X-Request-ID"`.
- Added `REQUEST_ID_PATTERN = r"[A-Za-z0-9._-]{1,64}"`. It is a plain string so the Engine's and the Client's copies compare equal; a compiled `_REQUEST_ID_RE` is built from it.
- Added `resolve_request_id(header_value)`. It returns the value unchanged when it fully matches the pattern (`fullmatch`, so `"abc\n"` is rejected), and otherwise a new `uuid.uuid4().hex`.
- New imports are `re` and `uuid`, both stdlib, so the subprocess tests that import `logging_profiles` under pytest's interpreter still work.
- I left the `clear_request_context` change for Phase 2, which also lists this file.

### `client/backend/lib/request_context.py` (new)
- The Client's copy of `REQUEST_ID_HEADER`, `REQUEST_ID_PATTERN`, `_REQUEST_ID_RE` and `resolve_request_id`, identical to the Engine's.
- It carries a `rat-tail:` comment: the code is copied, not shared, because the client/engine boundary check keeps the two codebases apart. A cross-service test compares the two copies, and a shared package is the fix once a third consumer appears.
- The comment mentions `engine/server/api/request_context.py`, but the boundary regexes don't match that text: there is no `from engine`/`import engine` and no `engine/server/db/`.
- The thread-local set/fetch/clear helpers from the plan are not added here. Only the Client phase uses them, and this checkpoint does not test them.

### Test files in this phase's list
- `engine/server/api/tests/test_logging_profiles.py`, `tests/active/test_logging_profiles.py` and `tests/active/test_server.py` are not edited. The gating checkpoint is `tests/tmp/test_20_request_lifecycle_logs_phase1.py`, and this step asks for production code only.
- The plan's checks for this phase, which put this coverage into those three permanent test files, are therefore not written yet.

#### Phase 2 - Engine request lifecycle [code]

**Files touched.** engine/server/api/handlers/similar.py (EDITED), engine/server/api/logging_profiles.py (EDITED), engine/server/api/request_context.py (EDITED), engine/watch-engine-logs.sh (EDITED), engine/server/api/tests/test_logging_profiles.py (EDITED), tests/active/test_logging_profiles.py (EDITED), tests/active/test_similar.py (EDITED)

**Checkpoint.** Seam: a real SimilarServer over a socket, run as a subprocess child in the existing pattern (`server.SimilarServer(("127.0.0.1", 0), SimilarHandler, **{**args, "db": conn, ...})`, tests/active/test_video.py:170/230), with an EngineJsonFormatter handler on a StringIO. The child is the new `_LIFECYCLE_CHILD` in tests/active/test_logging_profiles.py. It sends: GET /api/health with `X-Request-ID: probe.id-1`; the same with no header; the same with "bad id", 65×a and "a/b"; GET /nope (404); GET /api/channels with a refusing rate-limiter stub (429); POST /recommendations with body `{` (400); GET through a subclass whose `_dispatch_get` raises `sqlite3.OperationalError("interrupted")` (503); and two GETs on one http.client connection to a `protocol_version = "HTTP/1.1"` subclass. The parent asserts, per id: the first record is request.start (ip/method/url) and the last is request.end, whose context is exactly {status, duration_ms}, with an int duration and the expected status. Every record in the window has the id. The valid id is used verbatim and the others are 32-hex. No rejected value appears in any record. The 503 window holds a statement.timeout.info WARNING. The keep-alive ids are distinct and never cross. No record after the last request carries an id. The issue-19 durable test is rewritten against the session Engine log: it pairs request.start (url carries the marker) with request.end by request_id and keeps the ts properties.

**Intent.** Every request engine/server/api/handlers/similar.py's SimilarHandler serves runs inside `_run_request`, which logs one request.start and one request.end, and every record between them carries that request's resolved id.

- C1 - Each served request logs request.start first and request.end last, and request.end carries exactly status and duration_ms on every exit path (200, 404, 429, 400, 503).
- C2 - Every record between a request's start and end carries that request's id and no other, including across a keep-alive connection, and no id remains set once the request ends.

**Outcome.** ### `engine/server/api/handlers/similar.py`
- New `SimilarHandler._run_request(serve)`, the one place a request's id is set and cleared. Its first step is `set_request_id(resolve_request_id(self.headers.get(REQUEST_ID_HEADER)))`, which runs before any rate-limit, bridge-auth, body-read or statement-deadline code. It then resets the per-instance `_response_status`, starts a `perf_counter()` timer and logs `[request.start] request started` with `extra={"structured_context": {ip, method, url[, user_agent]}}`. `user_agent` is included only when the header is non-empty. Then it runs `serve()`.
- In `_run_request`'s `finally`, it logs `[request.end] request finished` with `{status, duration_ms}`, then calls `clear_request_context()` and `set_request_id(None)`. `status` is the int that was sent, or `"-"` if nothing was sent; `duration_ms` is an int measured from just before the start record. Exceptions still propagate.
- `do_GET`, `do_POST` and `do_OPTIONS` now go through `_run_request`. The old `do_GET` / `do_POST` bodies (statement deadline, plus the `is_interrupted_error` → `_respond_interrupted` 503) moved unchanged into the new `_serve_get` / `_serve_post`. The 503 path and its `[statement.timeout]` warning therefore happen between start and end.
- New `log_request(code, size)`: it stores `int(code)` in `_response_status` and logs nothing. This removes the old line that was logged when the response was sent.
- `log_message` now logs one WARNING `[http] <format % args>` with a `peer` structured context. Only http.server's own `log_error` calls reach it. It never reads `self.headers`, because those calls can come before the headers are parsed.
- Removed `_log_access_start` and its three calls (`do_OPTIONS`, `_dispatch_get`, `_dispatch_post`), and removed `_make_request_id`.
- `_handle_similar` now uses `request_id = fetch_request_id() or "-"` and no longer calls `set_request_id`. The `[similar-server][<id>]` lines keep their format and now hold the shared id. Its `finally: clear_request_context()` stays, and so does the one in `_handle_similar_request`.
- Imports: `Callable` from `typing`; `REQUEST_ID_HEADER` and `resolve_request_id` from `request_context`. numpy stays (`_draw_page`, `_parse_dislike_centroids`).

### `engine/server/api/request_context.py`
- `clear_request_context()` no longer deletes `request_id`; the docstring now says the request wrapper owns the id and clears it with `set_request_id(None)`. This is what lets `_handle_similar`'s inner clear leave the id in place for `request.end`.

### `engine/server/api/logging_profiles.py`
- In `_EVENT_RULES`, `[access.start]` → `access.start` became `[request.start]` → `request.start`, and `[access]` → `access` became `[request.end]` → `request.end`. Both stay tagged `focused` and `verbose`.
- The two formatter branches now match `request.start` / `request.end`, and still set the message to "request started" / "request finished".
- Added a comment: the request id is read from the thread-local at format time, so a QueueHandler would drop it.

### `engine/watch-engine-logs.sh`
- The jq branches for `access` / `access.start` now match `request.end` / `request.start`, with the matching `sub` strips.

### Test files on this phase's list (not edited)
- I left `engine/server/api/tests/test_logging_profiles.py`, `tests/active/test_logging_profiles.py` and `tests/active/test_similar.py` as they are. They are durable tests that have already gated, so they are not mine to edit, and this step asked for production code only.
- Several of them now conflict with R9 and are expected to go red against this code:
  - `engine/server/api/tests/test_logging_profiles.py`: `test_access_start_is_tagged…`, `test_access_message_does_not_duplicate_context`, and the smoke-stream test's expected event `"access"`.
  - `tests/active/test_logging_profiles.py`: `JSON_PAYLOADS[3]` and the text-line assertion, which both still expect `access.start`, and the issue-19 durable `test_engine_request_ts_never_decreases_from_access_start_to_access`, which looks for `access.start` / `access` in the session Engine log.
- The workflow needs to retire or replace them, as the plan's R9 and Tests section describe. They should not be quietly repointed.
- `tests/active/test_similar.py` needs no change: its doubles now log `[similar-server][-] start…`, which still matches `"] start limit=20"`.

I did not run the checkpoint or any probe.

#### Phase 3 - Client request lifecycle [code]

**Files touched.** client/backend/server.py (EDITED), tests/active/test_server.py (EDITED)

**Checkpoint.** Seam: the in-process Client over a socket, using the `client_backend` fixture (tests/active/conftest.py:72) with `_client_logging(monkeypatch, None)` (tests/active/test_server.py:1159) capturing ClientLogFormatter output. Each test polls the stream, with a bounded wait, for the request.end carrying its id, because the end record is written after the response. It covers /api/health with a valid id, no id, and "bad id"/65 chars/"a/b"; 404; 429 via a monkeypatched `ClientBackendHandler._rate_limit_check` returning False; and 400 from /api/user-action with invalid JSON. The assertions match Phase 2's: start first, then end with exactly {status, duration_ms}; a top-level `request_id` on every record in the window; valid ids verbatim and the others 32-hex; no rejected value logged. A keep-alive test runs a `ClientBackendServer` on port 0 with an HTTP/1.1 `KeepAliveClientHandler` and sends two GET /api/health on one connection, asserting distinct, non-crossing ids. The existing CLIENT_LOG_JSON_PAYLOADS and text tests are updated to the request.start shape and still hold on the pytest main thread, where no id is set.

**Intent.** Every request client/backend/server.py's ClientBackendHandler serves runs inside `_run_request`, which logs one request.start and one request.end, and ClientLogFormatter stamps every record between them with that request's id as a top-level request_id.

- C1 - Each served Client request logs request.start first and request.end last, and request.end carries exactly status and duration_ms on every exit path (200, 404, 429, 400).
- C2 - Every Client record between a request's start and end has a top-level request_id equal to that request's id and no other, including across a keep-alive connection.

**Outcome.** ### client/backend/server.py
- New module-level `REQUEST_ID_HEADER`, `REQUEST_ID_PATTERN` (`[A-Za-z0-9._-]{1,64}`) and `resolve_request_id(header_value)`. It returns the header verbatim when the whole value matches the pattern, and otherwise a fresh `uuid4().hex`, so a rejected value is never logged. These mirror `engine/server/api/request_context.py` and carry a `rat-tail:` comment, because the two services import from different roots and cannot share one module.
- New module-level `_REQUEST_CONTEXT = threading.local()`, which holds the id of the request the current handler thread is serving.
- `ClientLogFormatter.format` adds a top-level `request_id` (after `message`, before `context`) whenever the emitting thread has one set. Records logged outside a request (service start/stop, the test-only records) keep their old key order.
- `ClientBackendHandler._run_request(serve)` (new) wraps every request:
  - It sets the id first, then logs `request.start` "request started" with context `{ip, method, url}`, plus `user_agent` when the header is non-empty.
  - It then runs `serve()`. In a `finally` it logs `request.end` "request finished" with exactly `{status, duration_ms}`: `status` is the int `send_response` sent (`"-"` if none was sent) and `duration_ms` is truncated `perf_counter` ms. Only after that does it delete the thread-local id, so request.end keeps its id and later records on a keep-alive thread do not inherit it.
- `log_request` (new override) only records the status for request.end. The old `log_message` that wrote `client.access` with string `status`/`bytes` is gone.
- `log_message` now handles only what `log_error` sends (bad request line, unsupported method, timeout). It logs one WARNING `client.http` record with context `{peer}` and reads only the socket peer, because the headers may not be parsed yet. This mirrors the Engine's handler.
- `do_OPTIONS`, `do_GET` and `do_POST` now call `_run_request`. The old routing bodies of `do_GET` and `do_POST` moved unchanged into `_serve_get` and `_serve_post`.
- Imports added: `re`, `threading`, and `Callable` from `typing`.

### tests/active/test_server.py
Not changed. Its only `client.access` records are written directly with `_emit_client_log` to exercise the formatter and the text rendering. They never come from the handler, so removing the handler's access line leaves them valid. The checkpoint imports `_client_logging` from this file as it already stands.

#### Phase 4 - Client to Engine propagation [code]

**Files touched.** client/backend/lib/engine_api_client.py (EDITED), client/backend/server.py (EDITED), tests/active/test_server.py (EDITED)

**Checkpoint.** Two seams. For the header on the wire: stub Engines that record the received `X-Request-ID`, in the existing stub pattern at tests/active/test_server.py:440-449. The proxied GET /api/video goes to a stub that drops the first connection, so both attempts are recorded. `fetch_metadata_for_entries` and `_publish_to_engine_bridge` are each called inside a thread that set the Client id. Each of the three is also called with no id set, and the stub must record no header. End to end: the `engine_client` fixture (tests/active/conftest.py:148, the in-process Client → session Engine) with `_client_logging` capturing Client records and the session Engine's log file read for the Engine side. It sends POST /recommendations?limit=5 with `X-Request-ID: v1.<uuid hex>`, GET /api/video with a dataset identity, and GET /api/health. It asserts start…end order under the same id in the Client for all three and in the Engine for the first two. It then repeats POST /recommendations with no header and asserts a single 32-hex id appearing in both services.

**Intent.** Every Engine call the Client makes while serving a request carries that request's id in X-Request-ID, so one request's id appears in both the Client's and the Engine's start…end windows.

- C1 - The proxied read on every retry attempt, `_post_json` and `_publish_to_engine_bridge` each send X-Request-ID equal to the Client's current id, and send no such header when no id is set.
- C2 - For POST /recommendations and GET /api/video, the Client's and the Engine's start…end windows share one id: the supplied one when valid, else a single generated 32-hex id.

**Outcome.** ### `client/backend/lib/engine_api_client.py`
- The Client's request-id thread-local now lives here as `REQUEST_CONTEXT = threading.local()`. Phase 3 had put it in `server.py` as `_REQUEST_CONTEXT`. It had to move because `_post_json` has to read it, and `lib` cannot import `server`. It is still set and cleared only by `ClientBackendHandler._run_request`.
- New `request_id_headers()`: returns `{"X-Request-ID": <current id>}` while a request is being served, and `{}` when no id is set. It never sends an empty or `None` value.
- `bridge_headers()` now adds `request_id_headers()` to its headers, and its docstring says so. Because `_post_json` (resolve, metadata, centroids) and `_publish_to_engine_bridge` both build their headers here, they now send the id.
- New imports: `threading`, and `REQUEST_ID_HEADER` from `.request_context` (the lib's existing copy, using the lib's relative-import style).

### `client/backend/server.py`
- Removed the local `_REQUEST_CONTEXT = threading.local()` and its comment. `server.py` now imports `REQUEST_CONTEXT` and `request_id_headers` from `lib.engine_api_client`.
- `ClientLogFormatter.format`, plus the set and `del` in `_run_request`, now use `REQUEST_CONTEXT`. Nothing else about them changed.
- In `_proxy_engine_request`, the upstream headers now include `**request_id_headers()`. The proxy builds one `Request` and reuses it on every retry, so each attempt carries the same id.
- Removed `import threading`, which nothing used once the thread-local moved.

### `tests/active/test_server.py`
- Not edited. The checkpoint imports `_serving` and `_client_logging` from it as they are.

### Verification
- A probe, `tests/tmp/probe_p4_import.py`, confirmed three things: the server and the lib share the same thread-local object; `bridge_headers()` gives `{'content-type': 'application/json'}` with no id set; and with id `abc` set it gives `{'content-type': 'application/json', 'X-Request-ID': 'abc'}`.
- I did not run the checkpoint itself.

**Beyond the files named.** tests/tmp/probe_p4_import.py — a probe I added to check that the relative import works and that the server and lib share one thread-local. I have no delete tool, so it is still there. It should be deleted; it holds no expectation the checkpoint needs.


