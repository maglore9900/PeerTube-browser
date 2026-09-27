# 15-tighten-response-defaults

_Rendered by the `dev-flow` workflow from its run state. Every edit here is overwritten on the next step; the evidence each gate turned on is in `docs/project/plans/16-15-tighten-response-defaults.record.md`._

## Requirements

### What is being built

Build issue `docs/project/issues/04-tighten-response-defaults.md` (Status: bug, ready-for-agent) as triaged. The build is plan 15, wave 3 of the security hardening batch (`.scratch/security-hardening-batch/notes.md`). It runs on main after plans 10-14 have merged, with no worktree. It does three things: CORS becomes opt-in by origin, server errors stop returning exception text, and recommendations debug is off by default. The decisions it rests on are in `docs/project/adr/0004-cors-opt-in-by-origin.md` (accepted). The operator approved these requirements, including the extra bridge_error site in R3.

### Purpose

Close security-audit finding SI4-M1 (audit runs 1-2, `docs/project/security-audit/run-1/REPORT.md` and `run-2/REPORT.md`), which covers three defaults:
- The wildcard CORS header lets any site make anonymous cross-site requests. The profile key travels in a header, not a cookie, so this is not a credentialed exposure.
- Raw exception text reaches callers, including the Engine's own error strings relayed through the Client.
- `?debug=1` gives any visitor the per-row scoring internals, because the Client proxy passes `debug` through.

Production is same-origin through nginx and needs no CORS. The browser never reaches the Engine, which binds loopback. Only the Vite dev server calls the Client API cross-origin.

### Baseline suite state

The pre-build baseline on the merged main is green: `validate_tests.py` exit code 0, no variant. The build must leave the active suite passing (`tests/active`).

### R1 — Client backend CORS (opt-in by exact origin)

- **Parsing.** Read `CLIENT_CORS_ORIGINS` from the environment once at startup, in the Client backend's `main()` in `client/backend/server.py`. Never read it per request, and never at import.
  - Format: comma-separated exact origins (`scheme://host[:port]`), whitespace around entries tolerated, empty entries dropped.
  - Empty or unset means no origins.
- **Storage.** Hold the parsed set on the server object (`ClientBackendServer`). Add it as a trailing constructor parameter with an empty default, so the existing six-argument constructions in `tests/active/conftest.py` (`client_backend` and `_engine_client` fixtures) keep working with no CORS.
- **Headers.** `respond_json`, `respond_bytes` and `respond_options` in `client/backend/lib/http_utils.py` read the request's `Origin` header and the configured set from the handler they are given (`handler.headers`, `handler.server`).
  - When `Origin` exactly matches a listed origin (string equality, no normalisation), send:
    - `access-control-allow-origin: <that origin>`
    - `Vary: Origin`
    - the existing `access-control-allow-methods: GET, POST, OPTIONS`
    - the existing `access-control-allow-headers: content-type, x-profile-key` (`ALLOWED_REQUEST_HEADERS`)
    - on preflight only, `access-control-max-age: 600`
  - Otherwise (no `Origin`, or an unlisted one), send no `access-control-*` header at all.
- **Invariants.**
  - The preflight (`respond_options`) always answers 204.
  - `*` is never sent.
  - `access-control-allow-credentials` is never sent.

### R2 — Engine CORS removed

`respond_json` and `respond_options` in `engine/server/api/http_utils.py` stop sending all `access-control-*` headers. The Engine sends none on any response, OPTIONS included. OPTIONS still answers 204.

### R3 — Fixed server-error bodies

Every 5xx and 502 response either service produces carries a fixed, human-readable message that names the failing operation. It contains no exception text, repr or traceback.
- An existing machine-readable `code` field stays.
- The full exception is logged at error level, with its traceback when the exception is unexpected:
  - Client: through its existing `_emit_client_log` / logging.
  - Engine: through `logging` (for example `logging.exception`).

Sites on the merged main. Line numbers are indicative; re-locate them by function.

**Client `client/backend/server.py`:**
- **`_proxy_engine_request`, generic `except Exception` branch** (currently 502 `{"error": "Engine read proxy failed", "code": "ENGINE_PROXY_FAILURE", "detail": str(exc)}`): drop `detail` and keep `error` and `code`. The existing error log already carries the error and the traceback.
- **`_proxy_engine_request`, transport-unavailable 502** (`code` `ENGINE_PROXY_UNAVAILABLE`, `detail: str(last_transport_error)`): drop `detail` and keep `error` and `code`. The existing warning log carries the error. Raise its level to error if needed to satisfy "logged at error level".
- **The `EngineApiError` handlers that answer 502 with `f"Engine … failed: {exc}"`:**
  - resolve (two sites, around 766 and 897)
  - centroids (around 795)
  - lookup (around 959)
  - metadata (two sites, around 1015 and 1030)

  Each returns its fixed message without the exception, e.g. `"Engine metadata failed"`, and logs the exception at error level. The `EngineApiError` text includes the Engine's own error string, so the fix is that the Client never puts it in the body.
- **The like/dislike action publish path.** The handler answers 502 with `bridge_error` taken from `_publish_to_engine_bridge`, which returns `str(exc)` for `URLError`/`TimeoutError` and for the generic exception. `bridge_error` becomes a fixed message such as `"engine bridge unavailable"`, and the exception is logged at error level. The existing fixed `engine bridge HTTP {code}` value may stay. The brief did not name this site; the operator approved including it.

**Engine:**
- **`engine/server/api/handlers/similar.py`, recommendations handler `except` branches:**
  - A `ValueError` whose text is in the bad-request set (`Invalid vector parameter`, `Vector dimension does not match embeddings`, `Vector norm is zero`) still answers 400 with that text.
  - Every other `ValueError` answers 500 with a fixed message (e.g. `"Internal server error"`) and is logged with its traceback.
  - The catch-all `except Exception` answers 500 with a fixed message. The existing `logging.exception("server error")` stays.
- **`engine/server/api/handlers/internal_events.py`, event-ingest catch-all `except Exception`:** 500 with a fixed message, and the exception logged with its traceback. The `ValueError` → 400 path is unchanged.

**Unchanged:**
- Every 4xx message the code writes deliberately for callers, e.g. `Invalid JSON body`, `Missing event_id`, `Missing entries`, and 400s that relay `ValueError` text from `read_json_body` or validation.
- 5xx/502/503 responses that already carry fixed text, e.g. `Engine read proxy returned an invalid page`, `Engine resolve returned incomplete identity`, `Engine read proxy HTTP {code}`, `Query time limit exceeded`, `Search is disabled`.
- The Client proxy's pass-through of an Engine error payload. Engine 5xx bodies become fixed at the source.

### R4 — Recommendations debug off by default

- In `engine/server/api/server_config.py`, `RECOMMENDATIONS_DEBUG_ENABLED` is derived from the env var `RECOMMENDATIONS_DEBUG`, not the literal `True`. It is true only for `1`, `true` or `yes` (case-insensitive, surrounding whitespace ignored); any other value, empty or unset means false.
- It is read once when the module is imported, matching the file's existing `_resolve_*_env` helpers and module-level constants. Its consumers in `engine/server/api/server.py` are unchanged.
- When it is off, `?debug=1` on `/recommendations` or `/videos/similar` gets the existing 403 `Debug mode is disabled`.
- The active-suite `engine` fixture in `tests/active/conftest.py` adds `RECOMMENDATIONS_DEBUG=1` to the Engine's env. The profile tests (`tests/active/test_profiles.py`, which reads `rows[0].debug.profile`) then keep working.

### R5 — Documentation

In `DEPLOYMENT.md`:
- **Section 7 "Verify".** The "Optional debug toggle" block quotes `RECOMMENDATIONS_DEBUG_ENABLED = True  # engine/server/api/server_config.py`. Replace it with the env var `RECOMMENDATIONS_DEBUG=1`: off by default, and set in the Engine's environment (e.g. `.env.bridge` or a systemd drop-in) to enable `?debug=1`.
- **`CLIENT_CORS_ORIGINS`.** Document it next to the dev-mode instructions in section 6 "Local alternative":
  - comma-separated exact origins;
  - leave unset in production (same-origin through nginx);
  - set it to the Vite origin (e.g. `http://127.0.0.1:5173`) on the Client backend for the cross-origin dev setup;
  - the Vite dev setup's cross-origin calls fail until it is set.
- The file must no longer quote the constant.

### Acceptance criteria

- [ ] With `CLIENT_CORS_ORIGINS` unset, a Client backend response to a request with `Origin: https://evil.example` carries no `access-control-allow-origin`.
- [ ] With `CLIENT_CORS_ORIGINS=http://127.0.0.1:5173`:
  - a request with that `Origin` gets it echoed, plus `Vary: Origin`;
  - the preflight carries allow-methods, allow-headers (`content-type, x-profile-key`) and max-age;
  - a request with any other origin gets no allow-origin.
- [ ] No response from either service contains `access-control-allow-origin: *`.
- [ ] No Engine response, OPTIONS included, carries any `access-control-*` header.
- [ ] Forcing an Engine metadata failure makes the Client backend answer 502 with a body that does not contain the Engine's error string, and the Client log contains it.
- [ ] Forcing an unexpected exception in the Engine recommendations handler yields 500 with a fixed message, and the Engine log carries the traceback.
- [ ] A malformed JSON body still yields 400 `Invalid JSON body`.
- [ ] With `RECOMMENDATIONS_DEBUG` unset, `/recommendations?debug=1` returns 403. With `RECOMMENDATIONS_DEBUG=1`, it returns rows carrying `debug`.
- [ ] The active suite passes, including the profile tests that read `debug.profile`.
- [ ] `DEPLOYMENT.md` documents both env vars and no longer quotes the constant.
- [ ] (From the approved extra site in R3) A failed bridge publish answers 502 with a `bridge_error` that contains no exception text, and the Client log contains the exception.

### Out of scope

- CSP and other security headers (delivered by the old security remediation).
- Adding cookies or credentials to CORS: `access-control-allow-credentials` stays absent.
- Changing which 4xx messages exist, or their wording.
- Logging format or log retention.
- The frontend's debug page, and `client/frontend/dev.mjs` beyond documenting the env var.
- Harvest-time edits (issue status → `complete`, moving the issue to `docs/project/issues/archive/`, `CONTEXT.md`). These happen on main at close.

### Consistency constraints

- Match the surrounding code's style:
  - stdlib `http.server` handlers and the existing `respond_json` helpers;
  - module-level named constants;
  - env vars read once at startup (Client: in `main()`; Engine: at `server_config` import, as its existing helpers do);
  - stdlib only, no new dependency.
- New code matches the file it lands in. Do not softwrap: one statement or comment per line.
- Backwards compatibility is not required beyond what the brief states. Tests that assert on error strings containing exception text change with the behaviour.

### Test running

- Run `.un/skills/devsecops/scripts/validate_tests.py` from the root of the main tree (`/home/enduser/code/PeerTube-browser`, the `.un` `project_dir`).
- Resolved trees: active `tests/active`, working `tests/tmp`, archive `tests/archive`, plans `docs/project/plans`, scratch `delete_me`. The record is `tests/last_test_validation.json` and the output is `tests/last_test_output.txt`.
- Run Engine-backed test files in their own `validate_tests.py` invocations, because of the Engine rate limit (memory `engine-rate-limit-single-lane-test-runs`).
- Test Engines write interaction rows to the shared `whitelist.db`, as every run already does.
- Engine handler code imports numpy and faiss. In-process tests of Engine handlers from the Client test interpreter must run in an `ENGINE_PY` child process (the precedent is in `tests/active/test_internal_events.py` / `test_similar.py`) or use the live `engine` fixture.

### Risks to carry forward

- **Hand-off note.** The Vite dev setup stops working cross-origin until `CLIENT_CORS_ORIGINS` is set, and `?debug=1` (the frontend debug page) stops working until the Engine runs with `RECOMMENDATIONS_DEBUG=1`. Say both in the hand-off.
- **Test stubs and the new header code.** `respond_json` / `respond_bytes` / `respond_options` will now read `handler.headers` and `handler.server`. Any caller or test stub that passes a handler without a server carrying the origin set, or without headers, must still work (use `getattr` defaults) or be updated.
- **Diagnostics move to the logs.** Error bodies lose their diagnostic text. That is the accepted tradeoff.

## High-level plan

### Approach

The build has four independent parts and one doc edit. It uses stdlib only and adds no new file outside the tests. I read each site on the merged main; line numbers below are from that read.

**R1 — Client CORS by exact origin.**
- **Parsing.** `client/backend/server.py` gains a module-level `parse_cors_origins` next to `parse_trusted_proxies`, in the same shape: split on commas, strip each entry, drop empties, return a frozenset. `main()` calls it once, beside the existing `TRUSTED_PROXIES` read and before the signal swap and the bind. It is never read at import or per request.
- **Storage.** `ClientBackendServer.__init__` gets a trailing `cors_origins` parameter after `trusted_proxies`, defaulting to an empty frozenset, stored as `self.cors_origins`. The constructor already takes seven parameters (trusted_proxies has a default), so the six-argument calls in `tests/active/conftest.py` (both fixtures) and `tests/active/test_server.py:328` keep working with no CORS. `main()` passes the parsed set as the new last argument.
- **Headers.** `client/backend/lib/http_utils.py` gets one private helper, called by `respond_json`, `respond_bytes` and `respond_options` between `send_response` and `end_headers`, in place of their three or four hard-coded `access-control-*` lines. It reads the request's `Origin` through `getattr(handler, "headers", None)` and the configured set through `getattr(getattr(handler, "server", None), "cors_origins", frozenset())`, so a stub with no server or no headers gets no CORS instead of crashing. It checks exact membership with no normalisation. On a match it sends the echoed allow-origin, `Vary: Origin`, the existing allow-methods and `ALLOWED_REQUEST_HEADERS`, and `access-control-max-age: 600` only when called from `respond_options`. Otherwise it sends nothing.
- **Invariants.** `respond_options` still always sends 204. Nothing ever sends `allow-credentials`.
- **Proxied responses.** The Client never copies upstream headers (it re-emits only content-type through `respond_bytes`), so the Engine's headers cannot leak through the proxy.

**R2 — Engine CORS removed.** In `engine/server/api/http_utils.py`, delete the four `access-control-*` lines from `respond_json` and the four from `respond_options`. `respond_options` stays, still used by `similar.py`, and answers a bare 204. The Engine has no other header site.

**R3 — Fixed server-error bodies.**
- **Client, `_proxy_engine_request` (around 685-730).**
  - The generic branch drops `detail` from its body. Its existing ERROR log already has the error and the traceback.
  - The transport-unavailable branch drops `detail` from its body, and its log goes from WARNING to ERROR so it meets "logged at error level". The log keeps `str(last_transport_error)`.
  - Both keep `error: "Engine read proxy failed"` and their `code`.
- **Client, the six `EngineApiError` handlers** (resolve 766 and 897, centroids 795, lookup 959, metadata 1015 and 1030): each calls one new private handler method, `_respond_engine_failure(operation, exc)`. It logs through `_emit_client_log` at ERROR, with the operation, the request path and `str(exc)` as context, and answers 502 `{"error": f"Engine {operation} failed"}`. No traceback is logged, because an `EngineApiError` is an anticipated failure and its text already carries the Engine's error.
- **Client, bridge publish.** `_publish_to_engine_bridge` is the only producer of `bridge_error`, so the fix goes there, not in the handler. The `URLError`/`TimeoutError` and generic branches log the exception at ERROR through `_emit_client_log`; the generic branch also logs `traceback.format_exc()` because it is unexpected. Both return the fixed `"engine bridge unavailable"`. The fixed `engine bridge HTTP {code}` string stays, and so does the activitypub not-implemented string.
- **Engine, `similar.py` (around 1008-1018).** A `ValueError` in the bad-request set still answers 400 with its own text. Any other `ValueError` gets `logging.exception` and 500 `"Internal server error"`. The catch-all keeps its `logging.exception("server error")` and answers the same fixed 500. The bad-request set becomes a module-level named constant instead of a local literal, to match the file's style.
- **Engine, `internal_events.py` (around 79-81).** The catch-all gets `logging.exception` and a fixed 500. The `ValueError` → 400 path is untouched.
- **Nothing else needs changing.** I grepped both services for 5xx sites built from `str(exc)` or an f-string with the exception, and these are all of them. `internal_client_reads.py` and `video.py` have only 4xx relays or fixed text. The Client proxy's pass-through of Engine error payloads stays; the Engine's 5xx bodies become fixed at the source.

**R4 — Debug off by default.**
- **The flag.** `engine/server/api/server_config.py` gains `_resolve_flag_env(name)` beside the other `_resolve_*_env` helpers. It is true only for `1`, `true` or `yes` after `.strip().lower()`, and false for anything else, empty or unset. `RECOMMENDATIONS_DEBUG_ENABLED = _resolve_flag_env("RECOMMENDATIONS_DEBUG")` replaces the literal `True`, with its comment updated.
- **Consumers.** `server.py:56/450` and the `similar.py:922` check are unchanged, and the existing 403 `Debug mode is disabled` covers both routes.
- **Test fixture.** The `engine` fixture's env in `tests/active/conftest.py` adds `"RECOMMENDATIONS_DEBUG": "1"`, so `test_profiles.py`'s `debug.profile` read keeps working.

**R5 — DEPLOYMENT.md.**
- **Section 7 (line 416-419).** The quoted constant is replaced by `RECOMMENDATIONS_DEBUG=1`: off by default, set in the Engine's environment through `.env.bridge` (the Engine unit's `EnvironmentFile`, `engine/install-engine-service.sh:182`) or a systemd drop-in, and it enables `?debug=1` for `/debug.html`.
- **Section 6 "Local alternative".** After the dev-mode block, one paragraph on `CLIENT_CORS_ORIGINS` in the style of the `TRUSTED_PROXIES` paragraph: comma-separated exact origins; unset in production (same-origin through nginx); set to the Vite origin, e.g. `http://127.0.0.1:5173`, on the Client backend for the cross-origin dev setup; cross-origin dev calls fail until it is set.

**How the acceptance criteria are covered.**
- **CORS on the Client.** A live Client on an ephemeral port, the same pattern as `client_backend`, built once with no origins and once with `http://127.0.0.1:5173`, is probed with GET and OPTIONS requests that carry each `Origin`.
- **CORS on the Engine.** A request to the live `engine` fixture, OPTIONS included, checks that no response carries any `access-control-*` header. This test runs in its own `validate_tests.py` invocation because of the Engine rate limit.
- **Engine metadata failure.** A stdlib stub Engine in the test answers the metadata call with a 500 carrying a distinctive string. The Client's 502 body must not contain it, and the captured log (caplog) must.
- **Engine recommendations exception.** In an `ENGINE_PY` child, following the `test_similar.py` precedent, a patched method raises a sentinel exception. The body must be the fixed 500 and the child's log must carry the traceback.
- **Bridge publish failure.** `_publish_to_engine_bridge` is called against a closed port and must return the fixed error while the log carries the exception. A stub Engine that resolves but refuses ingest covers the same thing through the handler.
- **Debug toggle.** The `RECOMMENDATIONS_DEBUG` values are tested in a child import the way `test_server_config.py` does. `debug=1` → 403 is tested in an `ENGINE_PY` child with the flag off. The live fixture, with the flag on, covers `debug` rows.
- **Malformed JSON.** Any Client route given a malformed body still answers 400 `Invalid JSON body`.

### Alternatives considered

- **Keeping the origin set in `http_utils`** (a module global set from `main()`) instead of on the server. Rejected: it is hidden process state, tests could not run two Clients with different sets in one interpreter, and the requirements put it on the server.
- **Passing origins as an explicit argument to `respond_*`.** Rejected: there are about 40 call sites to touch, and the handler already reaches its server.
- **Echoing the origin plus `Vary: Origin` on every response once any origin is configured.** Rejected: the requirement says no `access-control-*` header without a match, and exact-set echo is what ADR-0004 decides.
- **Sanitising `bridge_error` in `_handle_user_action` instead of in `_publish_to_engine_bridge`.** Rejected: the raw text would still exist in a return value whose only consumer puts it in a body, so the leak would stay one refactor away.
- **Inlining the log and respond pair at each of the six `EngineApiError` sites.** Rejected in favour of one private method: six copies of a ten-line `_emit_client_log` call would drift. It is a plain method, not an abstraction.
- **A generic 500 wrapper in the Engine's `do_GET`/`do_POST`.** Rejected as scope creep. Only the two named handlers leak, and a dispatcher-level catch would change behaviour on every route.
- **Refusing to start on a malformed `CLIENT_CORS_ORIGINS` entry, the way `TRUSTED_PROXIES` does.** Not done: the settled format only drops empty entries, and a non-origin string is harmless because it never equals a browser's `Origin`.

### Risks and gotchas

- **A literal `*` entry.** If the operator lists `*` and a non-browser client sends `Origin: *`, exact echo would send `access-control-allow-origin: *` and break the "never `*`" invariant. The parser therefore drops a `*` entry as well as empty ones. This is the one behaviour beyond the literal parsing text, and it only enforces a stated invariant.
- **`Origin: null`.** A listed `null` would be echoed to sandboxed frames. That is the operator's explicit choice, and DEPLOYMENT.md will say "exact origins" only.
- **Cache poisoning.** `Vary: Origin` is sent only on a match. With origins configured, a shared cache could store a no-CORS response and serve it to a listed origin. The only configured case is local dev, and nginx does not cache the API, so this is accepted.
- **Engine fixture env and in-process imports.** The fixture gets the variable in its env copy only, never in the pytest process's `os.environ`. `test_similar.py` imports `server_config` in-process and in `ENGINE_PY` children, so its debug default flips to false; I read that it patches `respond_json` and does not request debug, but the build must confirm it with a run.
- **Log-level change.** The transport-unavailable log goes from WARNING to ERROR, which changes log volume during an Engine outage. Nothing in the tree filters on that level.
- **Test stubs.** The only callers that could lack `server` or `headers` are test stubs. The `getattr` defaults cover them, and the Engine helpers read neither.
- **Engine-backed test runs.** New Engine-backed test files run in their own `validate_tests.py` invocations because of the Engine rate limit. They write to the shared `whitelist.db` only through the existing fixture paths.
- **Hand-off note.** The Vite cross-origin dev setup fails until `CLIENT_CORS_ORIGINS` is set on the Client backend. The frontend `/debug.html` (`?debug=1`) returns 403 until the Engine runs with `RECOMMENDATIONS_DEBUG=1`. `vite.config.ts` also proxies `/api` same-origin, so the default `npm run dev` path may be unaffected; only an explicit `--client-api-base` needs the variable.

### Tradeoffs the operator accepts

- **Diagnostics move to the logs.** Callers, including the frontend and anyone debugging with curl, now see "Engine metadata failed" instead of the cause, and must read the Client or Engine log.
- **Coarser 500s.** A non-bad-request `ValueError` in recommendations is now indistinguishable from any other 500 to the caller.
- **Opt-in dev settings.** Dev and debug workflows now need an environment variable each, and a production Engine has debug off unless someone opts in.
- **Deliberate simplifications.**
  - Exact string match with no origin normalisation, so `http://localhost:5173` and `http://127.0.0.1:5173` are distinct entries. The upgrade path, if ever needed, is to normalise both sides in the parser and the helper.
  - The origin list is fixed for the life of the process; changing it means a restart, like `TRUSTED_PROXIES`.

## Impacts


<impact path="client/backend/lib/http_utils.py" element="respond_json (33-42), respond_bytes (45-58), respond_options (61-68), plus a new private CORS header helper">
**What changes.**
- The hard-coded `access-control-*` lines are removed:
  - three in `respond_json` (38-40);
  - three in `respond_bytes` (54-56);
  - four in `respond_options` (64-67; line 67 is `max-age: 600`).
- One private helper is called in each writer after `send_response` and before `_finish_response` (20-30). `_finish_response` is what calls `end_headers`.
- The helper reads `Origin` through `getattr(handler, "headers", None)` and the set through `getattr(getattr(handler, "server", None), "cors_origins", frozenset())`.
- On an exact match it sends:
  - the echoed `access-control-allow-origin`;
  - `Vary: Origin`;
  - allow-methods `GET, POST, OPTIONS`;
  - `ALLOWED_REQUEST_HEADERS` (line 12, which stays);
  - `access-control-max-age: 600`, from `respond_options` only.
- `respond_options` still sends 204 with no body.
- Three docstrings become inaccurate and need rewording: "Send a JSON response with CORS headers" (34), "…with CORS headers" (51) and "Respond to CORS preflight requests" (62).

**What depends on it.**
- `client/backend/server.py:33-34` imports all three writers.
- Every response in server.py goes through them, about 40 `respond_json` sites, including every 429, 401, 400 and 404.
- `respond_bytes` is used for:
  - proxied Engine pages (604, 636);
  - the two 204s: profile delete (345) and block remove (981).
- `do_OPTIONS` (260-262) calls `respond_options`.
- `tests/active/conftest.py:40` imports `RateLimiter` from this module (unchanged).
- `tests/active/test_profiles.py:26,173` monkeypatches `http_utils.datetime`. The helper must not shadow or re-import `datetime`.

**Regression risk: medium.**
- The helper must run before `_finish_response`. A header sent after `end_headers` is silently dropped.
- `handler.headers` on a real handler is an `HTTPMessage`, which is case-insensitive. A dict-headers stub would miss `Origin` and send no CORS, which is harmless.
- Only a value equal to an operator-configured entry is echoed, so request-controlled text never reaches a header unmatched.
- No test in `tests/` asserts on `access-control-*` today (grep: no match), so every CORS test is new.
- `test_frontend_*.py` bundle with `VITE_CLIENT_API_BASE` and run under Node `fetch`, which does not enforce CORS. I believe undici sends no `Origin`, but I have not verified that. Either way, those tests should be unaffected.
</impact>
<impact path="client/backend/server.py" element="new module-level parse_cors_origins, beside parse_trusted_proxies (150-167)">
**What changes.** A new pure function:
- splits on commas and strips each entry;
- drops empty entries and, per the plan's Risks, a literal `*`;
- returns a `frozenset[str]`;
- never raises;
- unlike `parse_trusted_proxies`, has no default fallback, so empty means none.

**What depends on it.** Only `main()` and new tests.

**Regression risk: low.**
- It must not be called at module level. Line 167 (`DEFAULT_TRUSTED_PROXY_NETWORKS = parse_trusted_proxies(...)`) does that for its sibling. Line 50 (`DEFAULT_CLIENT_PUBLISH_MODE = os.environ.get(...)`) reads the env at import. Neither may be copied, because R1 says the value is never read at import.
- The `*`-drop goes beyond the requirement's literal parsing rules. It needs its own test.
- A `null` entry would be echoed to `Origin: null` senders. The plan accepts this.
</impact>
<impact path="client/backend/server.py" element="ClientBackendServer.__init__ (205-224)">
**What changes.** A trailing `cors_origins: frozenset[str] = frozenset()` goes after `trusted_proxies` (213), stored as `self.cors_origins`.

**What depends on it.** Positional constructions:
- `main()` (1183-1191), seven args today;
- `tests/active/conftest.py:74` (`client_backend`) and `:161` (`_engine_client`), six args each;
- `tests/active/test_server.py:328` (`_client_backend`, used by `rig` at 442 and by the limiter tests at 346 and 357), six args.

The new http_utils helper reads the attribute through `handler.server`.

**Regression risk: low.**
- The default keeps every six-argument caller at "no CORS".
- The parameter must be last. Inserting it before `trusted_proxies` would bind the parsed networks to the wrong name in `main()`.
- No existing fixture exposes the new argument, so CORS tests must build their own server with it.
</impact>
<impact path="client/backend/server.py" element="main() (1149-1191 and the service.start log after it)">
**What changes.**
- `parse_cors_origins(os.environ.get("CLIENT_CORS_ORIGINS", ""))` goes next to the `TRUSTED_PROXIES` read (1152-1156). That is before `logging.basicConfig` (1157), the signal swap (1174-1177), the DB open (1179-1182) and the bind (1183).
- The result is passed after `trusted_proxies` (1190).
- Optionally, the configured origins go into the `service.start` log context (1192 onward). That would help an operator confirm what is active.

**What depends on it.**
- `tests/active/test_server.py:211-249`. The `startup` fixture and the two `main()` tests monkeypatch `TRUSTED_PROXIES` and expect `SystemExit` before the signals swap. A non-raising CORS parse beside it cannot change that.
- The environment reaches `main()` through three routes:
  - `client/install-client-service.sh:196` (`EnvironmentFile=-${PROJECT_DIR}/.env.bridge`);
  - `scripts/run-services.sh:90-93` (`set -a; source .env.bridge`), which starts the Client at 153-156;
  - DEPLOYMENT.md §5's manual run (251-256).

**Regression risk: low.** The parser never raises, so startup cannot newly fail.
</impact>
<impact path="client/backend/server.py" element="_proxy_engine_request generic except Exception branch (685-706)">
**What changes.**
- The body drops `"detail": str(exc)` (704) and keeps `{"error": "Engine read proxy failed", "code": "ENGINE_PROXY_FAILURE"}`.
- The ERROR `_emit_client_log` (687-700) already carries `str(exc)` and `traceback.format_exc()`.

**What depends on it.**
- Frontend readers take only `.error` (`client/frontend/src/data/videos.ts:150`).
- A grep of `client/frontend/src` finds no reader of `detail` or `code`.

**Regression risk: low.** The branch is `# pragma: no cover`. It is also where an `http.client.RemoteDisconnected` lands, because that is not a `URLError`. That happens, for example, when an uncaught Engine exception closes the socket. After this change that case also gets a fixed body.
</impact>
<impact path="client/backend/server.py" element="_proxy_engine_request transport-unavailable tail (707-730)">
**What changes.**
- The body drops `detail` (727) and keeps `error` and `code: ENGINE_PROXY_UNAVAILABLE`.
- The log (708-720) goes from `logging.WARNING` to `logging.ERROR`. It keeps `str(last_transport_error)`.

**What depends on it.**
- `tests/active/test_server.py:181-186` asserts only `status == 502` against `CLOSED_ENGINE`.
- The retry loop (679-684) is unchanged.

**Regression risk: low.**
- Status and `code` are unchanged.
- One ERROR line per proxied request during an Engine outage.
- Nothing in the tree filters Client logs by level.
</impact>
<impact path="client/backend/server.py" element="_proxy_engine_request HTTPError branches (631-678) and ENGINE_PROXY_INVALID 502 (594-600); not named by the plan">
**What changes.** Nothing, according to the plan.

**Why it is listed.** R3 says every 5xx is logged at error level. Three sites fall short:
- **HTTPError with a payload (632-662).** It passes the Engine's status and body through verbatim with `respond_bytes`, logging only at INFO. Any Engine 5xx body therefore reaches the browser unchanged, so R3 depends entirely on the Engine sites below being fixed at the source. Unhandled Engine exceptions produce no body at all; they close the socket.
- **HTTPError without a payload (663-678).** It answers the upstream code, which can be a 5xx, with the fixed text `Engine read proxy HTTP {code}`, logged at WARNING.
- **`ENGINE_PROXY_INVALID` (598-600).** It answers a fixed 502 and logs nothing.

**Regression risk: none if left alone.** It is a completeness gap against a literal reading of R3, and whether to fix it is a scope decision. Raising these to ERROR would not change any response.
</impact>
<impact path="client/backend/server.py" element="six EngineApiError handlers: _handle_user_action resolve (765-767) and centroids (794-796), _handle_likes_import (896-898), _handle_block_add lookup (958-960), _handle_user_profile_likes_get metadata (1014-1016), _handle_user_profile_likes_from_client metadata (1029-1031); new private method _respond_engine_failure">
**What changes.** Each `respond_json(self, 502, {"error": f"Engine … failed: {exc}"})` becomes `self._respond_engine_failure(operation, exc)`. That method:
- logs at ERROR through `_emit_client_log` with the operation, `self.path` and `str(exc)`;
- answers 502 `{"error": f"Engine {operation} failed"}`.

The operation words today are resolve, centroids, resolve, lookup, metadata and metadata. `_handle_likes_import` (897) says "resolve", but it calls `fetch_metadata_for_entries` (895), so "metadata" would be accurate. The plan does not choose.

**What depends on it.** The frontend shows `payload.error` in six places. The visible text loses its `: Engine … (HTTP n): …` suffix.
- `blocks.ts:65`
- `profile.ts:96`
- `reactions.ts:43` and `:79`
- `user-profile.ts:83`
- `user-actions.ts:35`

Tests:
- `tests/active/test_dislikes.py:77` and `test_profiles.py:318` assert status only.
- The `rig` stub Engine (`test_server.py:403-445`) is the ready harness for the "forced metadata failure" criterion. Its `/internal/videos/metadata` branch (417-420) can return a 500 with a distinctive `error`.

Docs: DEPLOYMENT.md:227 quotes `Engine metadata failed (HTTP 401)` (see the docs checklist).

**Regression risk: low for behaviour, medium for logging completeness.**
- `engine_api_client._post_json` (60-63) also wraps unexpected exceptions into `EngineApiError`, for example a `JSONDecodeError` from a non-JSON 200 at line 45, or `RemoteDisconnected`. The plan logs no traceback, so those lose it, which falls short of R3's "traceback for unexpected ones".
- For caplog assertions, `_emit_client_log` serialises with `json.dumps(ensure_ascii=True)`, so a test's sentinel string should be plain ASCII with no quotes or backslashes.
- The root logger stays at WARNING in tests, because `basicConfig` runs only in `main()`, so ERROR records reach caplog.
</impact>
<impact path="client/backend/lib/engine_api_client.py" element="EngineApiError messages in _post_json (60-63), resolve_video_seed (83-88), fetch_metadata_for_entries (103-108), compute_dislike_centroids (124-130)">
**What changes.** Nothing. The messages embed the Engine's `error` field and HTTP status, or `str(URLError)`. After the build they reach only the Client log.

**What depends on it.** The six handlers above. The criterion "the Client log contains the Engine's error string" relies on this text staying intact.

**Regression risk: none if left unchanged.** It is listed so that nobody sanitises here as well, which would break the log half of the criterion.
</impact>
<impact path="client/backend/server.py" element="_publish_to_engine_bridge (1035-1054), _publish_event (1057-1067), and the bridge_error consumer in _handle_user_action (818-833)">
**What changes.**
- The `(URLError, TimeoutError)` branch (1051-1052) and the generic branch (1053-1054) log at ERROR through the module-level `_emit_client_log` (114). The generic branch adds `traceback.format_exc()`, and `traceback` is already imported at 15.
- Both return `{"ok": False, "error": "engine bridge unavailable"}`.
- These stay as they are:
  - `engine bridge HTTP {exc.code}` (1050), which still logs nothing;
  - the activitypub string (1064).

**What depends on it.**
- `_handle_user_action` puts `bridge_error` in the body (830) and chooses 200 or 502 from `ok` (823).
- Smoke checks require `bridge_error` to be empty on success, which is unaffected:
  - `tests/run-arch-split-smoke.sh:343-345` and `597-600`;
  - `tests/run-installers-smoke.sh:422-423`;
  - `README.md:136`.
- `tests/active/test_frontend_reactions.py:254` expects "Failed to send action" on the unpublished Client's 502. That text is `user-actions.ts:35`'s default, because the 502 body has no `error` key, so it is unaffected.

**Regression risk: low.**
- A stub that refuses `/internal/events/ingest` reaches the HTTPError branch, not the transport branch the plan changes. The transport branch needs a closed port or a direct call.
- The HTTPError branch leaves an Engine 5xx on ingest unlogged, as noted above.
</impact>
<impact path="engine/server/api/http_utils.py" element="respond_json (23-33) and respond_options (36-43)">
**What changes.**
- Three `access-control-*` lines are deleted from `respond_json` (28-30). The plan says four, but the tree has three.
- Four are deleted from `respond_options` (39-42), which then sends a bare 204.
- Two docstrings need rewording: "with CORS headers" (24) and "Respond to CORS preflight requests" (37).

**What depends on it.**
- `handlers/similar.py` (import at 64, `respond_options` at 333), `internal_client_reads.py`, `internal_events.py` and `video.py`.
- `tests/active/test_internal_client_reads.py:60-73` drives the real `respond_json` through a stub with dict headers, a no-op `send_header` and no `server`.
- `engine/server/api/tests/test_recommendations_likes_limit.py` patches `respond_json`. It is not in `tests/active`.
- The Client proxy re-emits only content-type (603, 634), so the Engine's headers never reached the browser anyway.

**Regression risk: low.**
- No test asserts Engine CORS headers.
- The Engine helpers must not gain an `Origin`/`server` read, or the stub test above would still pass while the helpers diverge from the Client's design.
</impact>
<impact path="engine/server/api/handlers/similar.py" element="SimilarHandler.do_OPTIONS (330-333)">
**What changes.** No code change. The docstring "Handle CORS preflight." becomes misleading and should be reworded.

**What depends on it.** Any OPTIONS request to the Engine, including the new no-CORS test. OPTIONS is neither rate-limited nor bridge-gated, and it calls `_log_access_start` first.

**Regression risk: none.**
</impact>
<impact path="engine/server/api/handlers/similar.py" element="_handle_similar except branches (1008-1020), plus a new module-level bad-request constant near SIMILAR_POST_ROUTES (85)">
**What changes.**
- The local `bad_request` set (1009-1013) becomes a module constant.
- A `ValueError` in the set still answers 400 with its text.
- Any other `ValueError` gets `logging.exception` and 500 `Internal server error`.
- The catch-all keeps `logging.exception("server error")` (1017) and answers the same fixed 500.
- `finally: clear_request_context()` stays.

**What depends on it.**
- `POST /recommendations` and `POST /videos/similar` (via `_handle_similar_request`), and `GET /videos/{id}/similar` (489-496).
- The Client passes these bodies through verbatim.

**Regression risk: medium.**
- **Statement-deadline timeouts.** A `sqlite3.OperationalError('interrupted')` raised inside `_handle_similar` is caught by the catch-all. It answers 500 instead of reaching the 503 `Query time limit exceeded` path (355-363, 423-431). That is pre-existing. After the change it becomes a fixed 500 with a traceback logged for a timeout.
- **Production logging.** `logging.exception` goes through `EngineJsonFormatter`, which drops `exc_info` (see the logging_profiles entry).
- **Test setup.** A test child must supply `self.server.default_limit` (902-908) and `refresh_similarity_cache` (919) before the `try`. A bare SimpleNamespace raises `AttributeError` outside the except branches. A cheap seam is `random=1` with `_handle_random` patched to raise a sentinel.
</impact>
<impact path="engine/server/api/handlers/internal_events.py" element="handle_internal_events_ingest catch-all (79-81)">
**What changes.**
- `respond_json(handler, 500, {"error": str(exc)})` becomes `logging.exception(...)` plus a fixed 500. `logging` is already imported at 4.
- R3 wants the message to name the operation, so `Event ingest failed` fits better than `Internal server error`. The plan does not choose.
- Unchanged: the `ValueError` → 400 paths (29-31, 76-78), the rollback-and-re-raise (73-75), and `_prune_raw_events_if_due`.

**What depends on it.**
- The Client's `_publish_to_engine_bridge`, which sees only `engine bridge HTTP 500`.
- `tests/active/test_internal_events.py` patches `respond_json` and asserts a single call (102-110), but only on 200 paths. No existing test reaches this branch.

**Regression risk: low.** An `OperationalError('interrupted')` also lands here instead of the outer 503. That is pre-existing; only the body changes.
</impact>
<impact path="engine/server/api/logging_profiles.py" element="EngineJsonFormatter.format (184-223) and configure_engine_logging (226-238); not in the plan">
**What changes.** Nothing, by the plan.

**Why it is listed.**
- `configure_engine_logging` (called at `engine/server/api/server.py:324`) clears the root handlers and installs `EngineJsonFormatter` as the only one.
- `format` builds its payload from `record.getMessage()` alone (189). It never reads `record.exc_info` or `exc_text`, and never calls `formatException`.
- So in the running Engine, `logging.exception("server error")` emits `{"level":"ERROR","message":"server error",…}` with no exception text and no traceback.
- Once the 500 bodies lose `str(exc)`, the cause of an Engine 500 is recorded nowhere. That contradicts R3 and the criterion "the Engine log carries the traceback".
- An `ENGINE_PY` child test that never calls `configure_engine_logging` falls back to `logging.lastResort`, which does print the traceback. It passes while production fails.

**Options.**
- (a) Put `traceback.format_exc()` in the message at the two sites. This leaves the format alone, but `_extract_fields` may lift stray `key=value` tokens from the traceback.
- (b) Add a `traceback` key in `format` when `exc_info` is set. This also fixes `internal_events.py:116`, but it is a log-format change, which the brief lists as out of scope.

**What depends on it.** `engine/server/api/tests/test_logging_profiles.py`, which is not collected by `tests/active`.

**Regression risk: high for meeting R3; low for code if (b) only adds a key.**
</impact>
<impact path="engine/server/api/server_config.py" element="new _resolve_flag_env helper beside _resolve_*_env (6-30), and RECOMMENDATIONS_DEBUG_ENABLED (384-385)">
**What changes.**
- The helper returns `os.environ.get(name, "").strip().lower() in {"1","true","yes"}` and never raises.
- Line 385 becomes `RECOMMENDATIONS_DEBUG_ENABLED = _resolve_flag_env("RECOMMENDATIONS_DEBUG")`.
- The comment at 384 should name the env var.

**What depends on it.**
- `engine/server/api/server.py:56` imports it, and `:450` passes it to `SimilarServer`, which stores it (231, 265).
- `similar.py:922,927` reads `getattr(self.server, "recommendations_debug_enabled", False)`.
- In-process imports:
  - `tests/active/test_similar.py:53-58` and `279-284` exec the module for `BATCH_SIZE` and `DEFAULT_CLIENT_LIKES_MAX`, which are unaffected;
  - `tests/active/test_internal_events.py:32` imports it, which is harmless.
- `server_config` imports only `os`, so the new flag tests can use `sys.executable` children as in `tests/active/test_server_config.py:22-27`. That file strips its variable from the child env.

**Regression risk: medium.**
- A shell that already exports `RECOMMENDATIONS_DEBUG` flips an "unset → False" test unless the child env strips it.
- Every Engine answers 403 on `debug=1` until opted in, which is intended.
- A stub-server 403 test proves the gate, not the env wiring. The `test_internal_events.py:42-60` pattern passes `None` for every `SimilarServer` argument, so it does not prove the wiring either. Only `main()` joins env to server.
</impact>
<impact path="engine/server/api/server.py" element="RECOMMENDATIONS_DEBUG_ENABLED import (56), SimilarServer recommendations_debug_enabled (231, 265), main() construction (450), configure_engine_logging call (324)">
**What changes.** Nothing in the code.

**What depends on it.** The value now comes from the Engine's environment when `server_config` is imported. It arrives through:
- `engine/install-engine-service.sh:182` (`EnvironmentFile=-${PROJECT_DIR}/.env.bridge`);
- a systemd drop-in;
- `scripts/run-services.sh:90-93`, which exports `.env.bridge` with `set -a` into the shell that starts the Engine (137-139).

**Regression risk: none in code.** Line 324 is where production installs the formatter that drops tracebacks.
</impact>
<impact path="engine/server/api/handlers/similar.py" element="debug gate in _handle_similar (921-928)">
**What changes.** Nothing in the code. With the default off, `debug=1` on `POST /recommendations`, `POST /videos/similar` or `GET /videos/{id}/similar` answers 403 `Debug mode is disabled`.

**What depends on it.**
- The Client proxy allows `debug` on both feed routes (`client/backend/server.py:86-87`) and passes the 403 through its HTTPError-with-payload branch.
- The feed page (`client/frontend/src/pages/videos/index.ts:74-78`, `src/data/videos.ts:84,105`) forwards `debug=1` and shows the 403's `error` (`videos.ts:150`) instead of rows.
- `tests/active/test_profiles.py:274-279` reads `rows[0].debug.profile`.

**Regression risk: medium for the suite** if the fixture change is missed (next entry).
</impact>
<impact path="tests/active/conftest.py" element="engine fixture env (105); client_backend (69-89) and _engine_client (156-176) constructions; ClientBackend.request (51-66)">
**What changes.**
- Line 105 adds `"RECOMMENDATIONS_DEBUG": "1"` to the child env dict only.
- It sits after `**os.environ`, so it overrides any shell value, and the pytest process's `os.environ` is untouched.
- Both `ClientBackendServer(...)` calls stay six-argument, which means no CORS.

**What depends on it.**
- The session-scoped `engine` fixture is shared by every Engine-backed file (`test_profiles`, `test_similar`, `test_server`, `test_blocks`, `test_dislikes`, `test_metadata`, `test_random_videos`, `test_frontend_*`). They all keep today's debug-on behaviour.
- `ClientBackend.request` returns only `(status, body)`, so CORS header tests need a raw `urllib` or `http.client` helper.

**Regression risk: low with the change, high without it.** A session Engine cannot also serve a debug-off case. That case needs a child process, because a second Engine runs into the rate limit.
</impact>
<impact path="tests/active/test_profiles.py" element="_upnext_profile (274-279) and its callers (282-300)">
**What changes.** Nothing.

**What depends on it.** The `engine` fixture's `RECOMMENDATIONS_DEBUG=1`.

**Regression risk: high if the fixture change is missed.** Each call fails `status == 200` at 278 with a 403.
</impact>
<impact path="tests/active/test_server.py" element="closed-Engine 502 test (181-189); _client_backend six-arg construction (322-331); startup/main() tests (211-249); rig stub Engine (403-445)">
**What changes.** Nothing needs changing:
- the 502 test checks status only;
- the six-argument construction keeps working;
- `main()` tests are unaffected by a non-raising CORS parse.

**What depends on it.** `rig` is the natural harness for the metadata-failure criterion: make `/internal/videos/metadata` answer 500 with a sentinel `error`, then assert on the 502 body and caplog.

**Regression risk: low.** The file is mapped to `client/backend/lib/http_utils.py`, `server.py`, `server_config.py` and `similar.py` in `.un/skills/devsecops/config.json:56-60`. Its live-Engine tests still need their own `validate_tests.py` invocation.
</impact>
<impact path="tests/active/test_similar.py" element="_LIKES_CHILD (232-276), _RATE_LIMIT_CHILD (191-212), in-process server_config exec (53-58, 279-284)">
**What changes.** Nothing.

**What depends on it.**
- `_LIKES_CHILD` uses `server=SimpleNamespace(use_client_likes=True)` and stubs `_handle_similar`, so the debug-default flip cannot reach it. That confirms the plan's reading.
- It is the precedent for the `ENGINE_PY` sentinel-exception test (`sys.path` setup, `patch.object(similar, "respond_json")`).

**Regression risk: low.** To prove anything about production, the new child must install `configure_engine_logging` and assert on that output.
</impact>
<impact path="tests/active/test_server_config.py" element="_run child-import helper (22-27) and module docstring (1-6)">
**What changes.** Nothing in the existing tests. The new flag tests can reuse `_run` with these cases:
- `1`, `true`, `yes`, `TRUE` and ` yes ` → True;
- unset, empty, `0`, `no` and `on` → False.

**What depends on it.** Nothing.

**Regression risk: low.** If the tests are added here, the docstring must widen beyond `INTERACTION_RAW_RETENTION_DAYS`. `config.json:104-106` already maps the file to `server_config.py`.
</impact>
<impact path="tests/active/test_internal_client_reads.py" element="stub Request (60-73) driving the real Engine http_utils">
**What changes.** Nothing.

**What depends on it.** The stub has a no-op `send_header`, dict headers and no `server`.

**Regression risk: none,** provided the Engine helpers stay free of any `Origin`/`server` read.
</impact>
<impact path="tests/active/test_internal_events.py" element="_post respond_json patch (102-110) and ENGINE_INGEST child (42-60)">
**What changes.** Nothing.

**What depends on it.** It is the precedent for a test that forces the ingest catch-all (for example a `db_lock` that raises a non-ValueError), with `respond_json` patched and a single call asserted.

**Regression risk: none.**
</impact>
<impact path="tests/active/test_frontend_reactions.py" element="unpublished 502 assertion (247-258) and card test (404-409)">
**What changes.** Nothing.

**What depends on it.** "Failed to send action" is `user-actions.ts:35`'s default for a 502 body with no `error` key. That body carries `bridge_error`, which keeps the unchanged activitypub text.

**Regression risk: none.**
</impact>
<impact path="tests/active/test_response_defaults.py" element="new test file(s) for the acceptance criteria; name proposed, the plan names none">
**What changes.** New tests:
- **Client CORS**, from servers built with an empty set and with `http://127.0.0.1:5173`, read through raw header requests:
  - with nothing configured, `Origin: https://evil.example` gets no allow-origin;
  - a listed origin is echoed with `Vary: Origin`;
  - the preflight carries methods, `content-type, x-profile-key` and `600`;
  - any other origin gets nothing;
  - no `*` is ever sent;
  - OPTIONS is always 204.
- `parse_cors_origins` values.
- Engine no-CORS on GET, POST and OPTIONS, in a separate file or invocation because of the Engine rate limit.
- Metadata failure through a `rig`-style stub.
- Bridge publish against a closed port.
- An `ENGINE_PY` sentinel-exception child.
- The debug flag values, and a 403 with the flag off.
- Malformed JSON → 400 `Invalid JSON body` (`client/backend/lib/http_utils.py:77-88`).

**What depends on it.**
- `conftest` fixtures and `ENGINE_PY`.
- A `config.json` test-group entry at harvest.

**Regression risk: medium for suite stability** if live-Engine and stub tests share one file.
</impact>
<impact path=".un/skills/devsecops/config.json" element="test_groups (14-120)">
**What changes.** Nothing required.
- Both `http_utils` files, `server_config.py`, `similar.py` and `internal_events.py` are already mapped.
- `logging_profiles.py` is not mapped.
- A new test file needs an entry at harvest.

**Regression risk: low.**
</impact>
<impact path="client/frontend/scripts/dev.mjs" element="finalClientApiBase default (84-87) exported as VITE_CLIENT_API_BASE (100-106); out of scope for code">
**What changes.** Nothing.

**Why it is listed.**
- `npm run dev` is `node ./scripts/dev.mjs` (`package.json:7`). It always exports `VITE_CLIENT_API_BASE`, defaulting to `http://127.0.0.1:7172`.
- `client/frontend/src/data/api-base.ts:19-21` prefers that value over `window.location.origin`.
- So the default dev page on :5173 is cross-origin and bypasses the Vite proxy (`vite.config.ts:27-43`).
- This contradicts the plan's hand-off note that "the default `npm run dev` path may be unaffected". Every default dev session loses API access until `CLIENT_CORS_ORIGINS` is set.

**Regression risk: high for the dev workflow and the accuracy of the hand-off; none in code.**
</impact>
<impact path="client/frontend/vite.config.ts" element="server.port 5173, no host, server.proxy (25-43)">
**What changes.** Nothing.

**Why it is listed.**
- No `host` is set, so the page is normally opened as `http://localhost:5173`. That is a different exact origin from the plan's example `http://127.0.0.1:5173`.
- A `--port 5175` run (DEPLOYMENT.md:407) needs its own entry.

**Regression risk: none in code.** It is an accuracy issue for the docs.
</impact>
<impact path="client/frontend/src/data/api-base.ts" element="resolveClientApiBase (18-33)">
**What changes.** Nothing.

**Why it is listed.** `VITE_CLIENT_API_BASE` wins over the page origin. That is what makes the dev setup cross-origin and dependent on `CLIENT_CORS_ORIGINS`.

**Regression risk: none in code.**
</impact>
<impact path="client/frontend/src/pages/videos/index.ts" element="debugMode from ?debug=1 (74-78) and the debug metrics render (452-470)">
**What changes.** Nothing; out of scope.

**Why it is listed.**
- It is the real debug view. No `debug.html` exists: the pages are `index`, `videos`, `search`, `video-page`, `channels` and `about`.
- The plan's R5 phrase "enables `?debug=1` for `/debug.html`", and DEPLOYMENT.md:414, point at a page that does not exist.
- With the flag off, this page shows `Debug mode is disabled` instead of rows.

**Regression risk: none in code.**
</impact>
<impact path="client/install-client-service.sh" element="unit template EnvironmentFile=-${PROJECT_DIR}/.env.bridge (196)">
**What changes.** Nothing.

**Why it is listed.**
- Prod and dev units installed from one tree share `<project>/.env.bridge`. DEPLOYMENT.md:102-103 says both contours coexist.
- If the docs say to put `CLIENT_CORS_ORIGINS` there, prod gets CORS too, which silently undoes "unset in production".
- A per-unit drop-in (`systemctl edit peertube-client-dev`) avoids that.

**Regression risk: medium.** The risk is documentation-driven.
</impact>
<impact path="engine/install-engine-service.sh" element="unit template EnvironmentFile (182)">
**What changes.** Nothing. The plan's R5 cites this line.

**Why it is listed.** Putting `RECOMMENDATIONS_DEBUG=1` in the shared `.env.bridge` turns debug on for the prod Engine as well.

**Regression risk: medium, documentation-driven.**
</impact>
<impact path="scripts/run-services.sh" element="load_bridge_secret (82-98), Engine start (137-139), Client start (153-156)">
**What changes.** Nothing.

**Why it is listed.** `set -a; source .env.bridge` exports every variable into the shell, and both `nohup` children inherit it. Either variable placed in that file reaches both services.

**Regression risk: none in code.**
</impact>
<impact path="docs/project/adr/0004-cors-opt-in-by-origin.md" element="Decisions 1-3 and Consequences">
**What changes.** Nothing. The build implements the ADR as written. Dropping a configured `*` enforces "`*` is never sent".

**Regression risk: none.**
</impact>
<impact path="docs/project/issues/04-tighten-response-defaults.md" element="issue status and acceptance criteria; also docs/project/plans/15-tighten-response-defaults.md">
**What changes.** Nothing during the build. At harvest:
- status becomes `bug, complete`;
- the criteria are ticked;
- the issue moves to `archive/`;
- plan 15 is marked delivered.

**Regression risk: none.**
</impact>
<impact path="delete_me/" element="stale backups (server.py.bak*, engine_api_client.py.bak*, mutation-logs) that match every grep for these symbols">
**What changes.** Nothing.

**Why it is listed.** They match `EngineApiError`, `parse_trusted_proxies`, `RECOMMENDATIONS_DEBUG_ENABLED` and similar symbols, but nothing imports them. Do not edit them or count them as sites.

**Regression risk: none.**
</impact>
<impact path="tests/last_test_validation.json" element="tracked test record, with tests/last_test_output.txt">
**What changes.** Every `validate_tests.py` run rewrites both files.

**Regression risk: low.** This build runs on main, so there is no merge conflict.
</impact>


## Documentation to update

- [x] `DEPLOYMENT.md` - updated: DEPLOYMENT.md: documented `RECOMMENDATIONS_DEBUG` and `CLIENT_CORS_ORIGINS`, removed the quoted constant, and updated the failure symptoms to the new fixed error bodies.
- [x] `client/README.md` - updated: `client/README.md` now documents `CLIENT_CORS_ORIGINS` and the fixed 502 bodies for a failed Engine call or bridge publish.
- [x] `client/frontend/README.md` - updated: I updated `client/frontend/README.md` to cover what the Vite dev page now needs: `CLIENT_CORS_ORIGINS` on the Client backend for cross-origin API calls, and `RECOMMENDATIONS_DEBUG=1` on the Engine for the debug view.
- [x] `engine/server/README.md` - updated: Added three items to "Notes" in `engine/server/README.md`: debug is opt-in through `RECOMMENDATIONS_DEBUG`, the Engine sends no CORS headers, and unexpected failures now answer a fixed 500 with the traceback going to the log.
- [x] `docs/project/adr/0004-cors-opt-in-by-origin.md` - out of scope: The build implements Decisions 1-3 as written:
- [x] `README.md` - out of scope: Its only relevant claim (line 136) is that `/api/user-action` must return an empty `bridge_error` on success. That is unchanged: only the failure values of `bridge_error` changed.
- [x] `engine/server/api/recommendations/docs/OVERVIEW.md` - out of scope: Engine/server/README points here for the likes-validation 400 bodies. Those 400 texts are deliberate caller messages, which this build left unchanged. The file makes no claim about 500 bodies, debug gating or CORS.

## Implementation plan

## Draft implementation: plan 15, tighten response defaults

Two passes. Pass 1 found one gap. `EngineJsonFormatter`, the only handler in the running Engine, drops `exc_info`, so `logging.exception` would record no traceback in production and R3 plus its acceptance criterion would fail. The operator chose option (b): the formatter adds a `traceback` key. Pass 2 found nothing unmet against the plan or R1-R5. The departures from the high-level plan are listed at the end, each with its reason.

Everything is stdlib, with no new dependency. The only new source file is a test file; the rest are edits.

### What the build must test

| Criterion | Where | Harness |
|---|---|---|
| Client CORS: unset → no allow-origin; listed origin echoed with `Vary: Origin`; preflight methods, headers and max-age; unlisted origin gets nothing; never `*`; OPTIONS always 204 | `test_response_defaults.py` | Two Clients built in the test, with `frozenset()` and with `frozenset({"http://127.0.0.1:5173"})`, read through raw `http.client` so headers are visible |
| `parse_cors_origins` values, including the dropped `*` | same | Pure function |
| Engine metadata failure → 502 without the Engine's string; Client log has it | same | Stub Engine answering `/internal/videos/metadata` with 500 `{"error": "engine-sentinel-metadata-9c1d"}`; `POST /api/user-profile/likes` with one `{uuid, host}`; caplog at ERROR |
| Bridge publish failure → fixed `bridge_error`; log has the exception | same | `_publish_to_engine_bridge(CLOSED_ENGINE, {...})` called directly; caplog |
| Malformed JSON → 400 `Invalid JSON body` | same | `POST /api/user-profile/likes` with raw body `{not json` |
| Recommendations unexpected exception → fixed 500; Engine log has the traceback | same | `ENGINE_PY` child running `configure_engine_logging`, with `_handle_random` patched to raise a sentinel; stderr parsed as JSON lines |
| Recommendations `ValueError`: a bad-request text → 400 with that text; any other text → fixed 500 | same | Same child, more cases |
| Ingest catch-all → fixed 500 with a traceback in the log | same | `ENGINE_PY` child; `db_lock` raises `RuntimeError(sentinel)` on enter |
| Debug flag values | same | `sys.executable` child importing `server_config` with a controlled env (`test_server_config.py` `_run` pattern) |
| `RECOMMENDATIONS_DEBUG` unset → `debug=1` answers 403 | same | `ENGINE_PY` child with the variable stripped; `recommendations_debug_enabled` comes from the imported `server_config` |
| No `access-control-*` header on any Engine response, OPTIONS included; `RECOMMENDATIONS_DEBUG=1` → rows carry `debug` | `test_engine_response_defaults.py` | Live `engine` fixture, run in its own `validate_tests.py` invocation |
| Suite green, including `test_profiles.py` `debug.profile` | whole suite | `engine` fixture env gets `RECOMMENDATIONS_DEBUG=1` |

### Module map

| File | Change |
|---|---|
| `client/backend/lib/http_utils.py` | Two constants and the private `_send_cors_headers`; three writers call it; three docstrings reworded |
| `client/backend/server.py` | `parse_cors_origins`; `ENGINE_BRIDGE_UNAVAILABLE_ERROR`; a trailing `cors_origins` constructor parameter; `main()` wiring and start log; two proxy 502 bodies and one log level; `_respond_engine_failure` plus six call sites; bridge publish logging and fixed errors |
| `engine/server/api/http_utils.py` | Seven `access-control-*` lines deleted; two docstrings reworded |
| `engine/server/api/handlers/similar.py` | `SIMILAR_BAD_REQUEST_ERRORS` and `SIMILAR_FAILED_MESSAGE` constants; `_handle_similar` except branches; `do_OPTIONS` docstring |
| `engine/server/api/handlers/internal_events.py` | Catch-all logs and answers a fixed 500 |
| `engine/server/api/logging_profiles.py` | `EngineJsonFormatter.format` adds `traceback` when `exc_info` is set (operator decision (b)) |
| `engine/server/api/server_config.py` | `_resolve_flag_env`; `RECOMMENDATIONS_DEBUG_ENABLED` derived from `RECOMMENDATIONS_DEBUG` |
| `tests/active/conftest.py` | `engine` fixture env adds `"RECOMMENDATIONS_DEBUG": "1"` |
| `tests/active/test_response_defaults.py` | New: all non-live tests |
| `tests/active/test_engine_response_defaults.py` | New: live-Engine tests, in their own invocation |
| `DEPLOYMENT.md`, `client/README.md`, `client/frontend/README.md`, `engine/server/README.md` | Per the settled docs checklist |

### Client: `client/backend/lib/http_utils.py`

```python
ALLOWED_REQUEST_HEADERS = "content-type, x-profile-key"
CORS_ALLOWED_METHODS = "GET, POST, OPTIONS"
# Seconds a browser may cache a preflight answer.
CORS_PREFLIGHT_MAX_AGE = "600"


def _send_cors_headers(handler: BaseHTTPRequestHandler, preflight: bool = False) -> None:
    """Send the CORS headers when the request's `Origin` is exactly one the server lists, and none otherwise.

    The origin set is read from `handler.server.cors_origins`, and a handler without a server, headers or that attribute sends none.
    """
    headers = getattr(handler, "headers", None)
    origin = headers.get("Origin") if headers is not None else None
    allowed = getattr(getattr(handler, "server", None), "cors_origins", frozenset())
    # `*` is refused here as well as in the parser, since a server can be built with any set.
    if not origin or origin == "*" or origin not in allowed:
        return
    handler.send_header("access-control-allow-origin", origin)
    handler.send_header("vary", "Origin")
    handler.send_header("access-control-allow-methods", CORS_ALLOWED_METHODS)
    handler.send_header("access-control-allow-headers", ALLOWED_REQUEST_HEADERS)
    if preflight:
        handler.send_header("access-control-max-age", CORS_PREFLIGHT_MAX_AGE)
```

The writers:
- **`respond_json`**, docstring "Send a JSON response, with CORS headers for a listed origin.": `send_response` → content-type → `_send_cors_headers(handler)` → content-length → `_finish_response`.
- **`respond_bytes`**, docstring "Send a non-JSON response payload, with CORS headers for a listed origin.": same order.
- **`respond_options`**, docstring "Answer an OPTIONS request 204, with the preflight CORS headers for a listed origin.": `send_response(204)` → `_send_cors_headers(handler, preflight=True)` → `_finish_response(handler)`.

Invariants:
- The helper runs before `_finish_response`, so no header is sent after `end_headers`.
- Only a value equal to an operator-configured entry is echoed.
- `allow-credentials` is never sent.
- The helper touches neither `datetime` nor the module's imports, so `test_profiles.py`'s monkeypatch of `http_utils.datetime` is unaffected.
- A dict-headers stub gets `.get("Origin")` → None → no CORS, which is harmless.

### Client: `client/backend/server.py`

**Parser**, placed directly after `parse_trusted_proxies` and before `DEFAULT_TRUSTED_PROXY_NETWORKS`. It is never called at module level.
```python
def parse_cors_origins(value: str) -> frozenset[str]:
    """Parse a `CLIENT_CORS_ORIGINS` value: comma-separated exact origins, each compared to a request's `Origin` as a plain string.

    Whitespace around entries and blank entries are dropped, and so is `*`, which would otherwise be echoed back to a request sending `Origin: *`.
    """
    entries = (entry.strip() for entry in value.split(","))
    return frozenset(entry for entry in entries if entry and entry != "*")
```

**Bridge constant**, placed beside the other module constants:
```python
# The `bridge_error` of a publish the Engine never answered; the cause goes to the Client log only.
ENGINE_BRIDGE_UNAVAILABLE_ERROR = "engine bridge unavailable"
```

**`ClientBackendServer.__init__`**: a trailing `cors_origins: frozenset[str] = frozenset(),` after `trusted_proxies`, and `self.cors_origins = cors_origins` after `self.trusted_proxies = trusted_proxies`. The existing six-argument constructions keep their default of no CORS.

**`main()`**: directly after the `TRUSTED_PROXIES` try/except, before `logging.basicConfig`:
```python
    cors_origins = parse_cors_origins(os.environ.get("CLIENT_CORS_ORIGINS", ""))
```
- `ClientBackendServer(...)` gains `cors_origins,` after `trusted_proxies,`.
- The `service.start` context gains `"cors_origins": sorted(cors_origins),`, so an operator can see which origins are active.

**`_proxy_engine_request`**:
- Generic branch: the body becomes `{"error": "Engine read proxy failed", "code": "ENGINE_PROXY_FAILURE"}`. Its log is unchanged: it is already at ERROR and carries `str(exc)` and the traceback.
- Transport-unavailable tail: `_emit_client_log(logging.ERROR, ...)` in place of `logging.WARNING`, with the same context. The body becomes `{"error": "Engine read proxy failed", "code": "ENGINE_PROXY_UNAVAILABLE"}`.

**New handler method**, placed after `_handle_user_profile_likes_from_client`:
```python
    def _respond_engine_failure(self, operation: str, exc: EngineApiError) -> None:
        """Log a failed Engine call with its cause at error level and answer 502 naming only the operation, so no Engine error text reaches the caller.

        Call it only inside the `except EngineApiError` block, where `traceback.format_exc()` still sees the exception.
        """
        context: dict[str, Any] = {"operation": operation, "path": self.path, "error": str(exc)}
        cause = exc.__cause__
        # A cause other than a transport failure is unexpected, e.g. a non-JSON 200 or a dropped connection, and its traceback is the only record of it.
        if cause is not None and not isinstance(cause, (URLError, TimeoutError)):
            context["traceback"] = traceback.format_exc()
        _emit_client_log(logging.ERROR, "engine.call", f"engine {operation} failed", context)
        respond_json(self, 502, {"error": f"Engine {operation} failed"})
```

Call sites. Each `respond_json(self, 502, {"error": f"Engine … failed: {exc}"})` becomes `self._respond_engine_failure("<op>", exc)` and keeps the `return` after it.

| Handler | Site | Operation |
|---|---|---|
| `_handle_user_action` | resolve | `"resolve"` |
| `_handle_user_action` | `_store_reaction` | `"centroids"` |
| `_handle_likes_import` | `fetch_metadata_for_entries` | `"metadata"` (was "resolve"; this is the call it makes) |
| `_handle_block_add` | resolve and metadata | `"lookup"` |
| `_handle_user_profile_likes_get` | metadata | `"metadata"` |
| `_handle_user_profile_likes_from_client` | metadata | `"metadata"` |

**`_publish_to_engine_bridge`**:
```python
    except HTTPError as exc:
        return {"ok": False, "error": f"engine bridge HTTP {exc.code}"}
    except (URLError, TimeoutError) as exc:
        _emit_client_log(logging.ERROR, "engine.bridge", "bridge publish unavailable", {"event_id": payload.get("event_id"), "error": str(exc)})
        return {"ok": False, "error": ENGINE_BRIDGE_UNAVAILABLE_ERROR}
    except Exception as exc:  # pragma: no cover
        _emit_client_log(logging.ERROR, "engine.bridge", "bridge publish exception", {"event_id": payload.get("event_id"), "error": str(exc), "traceback": traceback.format_exc()})
        return {"ok": False, "error": ENGINE_BRIDGE_UNAVAILABLE_ERROR}
```
- `_publish_event`'s activitypub string is unchanged.
- The consumer in `_handle_user_action` is unchanged; it now only ever receives fixed strings.
- `URLError`, `traceback` and `Any` are already imported in server.py.
- `engine_api_client.py` is not touched, so the `EngineApiError` text, which carries the Engine's error string, reaches the log intact.

### Engine: `engine/server/api/http_utils.py`

- **`respond_json`**: delete the three `access-control-*` lines. Docstring: "Send a JSON response; the Engine sends no CORS headers (ADR-0004)."
- **`respond_options`**: delete the four `access-control-*` lines, keeping `send_response(204)` and `end_headers()`. Docstring: "Answer an OPTIONS request 204 with no CORS headers (ADR-0004)."
- Neither helper gains any `Origin` or `server` read.

### Engine: `engine/server/api/handlers/similar.py`

**Constants**, after `SIMILAR_POST_ROUTES`:
```python
# ValueError texts from seed resolution that describe the caller's vector: answered 400 with the text; any other ValueError is a server fault.
SIMILAR_BAD_REQUEST_ERRORS = frozenset({
    "Invalid vector parameter",
    "Vector dimension does not match embeddings",
    "Vector norm is zero",
})
# The body of every 500 the similarity handler answers; the cause goes to the Engine log only.
SIMILAR_FAILED_MESSAGE = "Recommendations request failed"
```

**`_handle_similar` tail**:
```python
        except ValueError as exc:
            if str(exc) in SIMILAR_BAD_REQUEST_ERRORS:
                respond_json(self, 400, {"error": str(exc)})
            else:
                logging.exception("[similar-server][%s] request failed", request_id)
                respond_json(self, 500, {"error": SIMILAR_FAILED_MESSAGE})
        except Exception:  # pragma: no cover
            logging.exception("server error")
            respond_json(self, 500, {"error": SIMILAR_FAILED_MESSAGE})
        finally:
            clear_request_context()
```
- The `[similar-server][id]` prefix gives the formatter the `request_id`. The catch-all gets it from the request context, which is still set because `finally` runs afterwards.
- **`do_OPTIONS` docstring**: "Answer OPTIONS 204 with no CORS headers."

### Engine: `engine/server/api/handlers/internal_events.py`

```python
    except Exception:  # pragma: no cover
        logging.exception("[ingest] event ingest failed")
        respond_json(handler, 500, {"error": "Event ingest failed"})
        return True
```
The message is inline, like the file's other fixed messages (`"Missing events"`).

### Engine: `engine/server/api/logging_profiles.py` (operator decision (b))

In `EngineJsonFormatter.format`, directly before the `return json.dumps(...)`:
```python
        # Without this key logging.exception records only its message, and a 500's cause, which no longer reaches the caller, would be lost.
        if record.exc_info:
            payload["traceback"] = self.formatException(record.exc_info)
```
- The change is additive: no existing key changes, and records without `exc_info` render exactly as before.
- It also makes the existing `logging.exception("[ingest] raw-event retention strip failed")` carry its traceback.

### Engine: `engine/server/api/server_config.py`

```python
def _resolve_flag_env(name: str) -> bool:
    """Handle resolve flag env: true only for 1, true or yes in any case, false for any other value, blank or unset."""
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes"}
```
It is placed after `_resolve_positive_int_env`. Then:
```python
# Allow returning debug metadata in recommendation responses when debug=1 is passed; off unless RECOMMENDATIONS_DEBUG is 1, true or yes.
RECOMMENDATIONS_DEBUG_ENABLED = _resolve_flag_env("RECOMMENDATIONS_DEBUG")
```
It is read once at import. `server.py` and the gate in `similar.py` are unchanged.

### Tests: `tests/active/conftest.py`

```python
    env = {**os.environ, "ENGINE_INGEST_MODE": "bridge", "ENGINE_BRIDGE_TOKEN": BRIDGE_TOKEN, "RECOMMENDATIONS_DEBUG": "1"}
```
This goes in the child env only, not the pytest process. Both Client constructions stay six-argument.

### Tests: `tests/active/test_response_defaults.py` (no live Engine)

The module docstring lists each claim, as the neighbouring files do.

Helpers:
- **`_serving` / `_client`**: a `contextmanager` building `ClientBackendServer(("127.0.0.1", 0), ClientBackendHandler, conn, engine_base, "bridge", RateLimiter(1000, 60), DEFAULT_TRUSTED_PROXY_NETWORKS, cors_origins)` over a tmp `users.db`, served on a daemon thread.
- **`_raw(base, method, path, headers, body=b"")`**: an `http.client.HTTPConnection` request returning `(status, dict of lower-cased header name → value, body bytes)`. It uses `getheaders()` so a duplicated header would be visible.

Client CORS. `LISTED = "http://127.0.0.1:5173"`.
- **Unset set**: `GET /api/health` and `OPTIONS /api/user-profile` with `Origin: https://evil.example`, and with `Origin: http://127.0.0.1:5173`. No header starting `access-control-`. OPTIONS is 204.
- **Listed set, `GET /api/health` with `Origin: LISTED`**:
  - `access-control-allow-origin == LISTED`;
  - `vary == "Origin"`;
  - methods `GET, POST, OPTIONS`;
  - headers `content-type, x-profile-key`;
  - no `access-control-max-age`;
  - no `access-control-allow-credentials`.
- **Listed set, OPTIONS with `Origin: LISTED`**: 204, the same headers plus `access-control-max-age == "600"`.
- **Listed set, `Origin: http://localhost:5173`, `https://evil.example` and `*`, on GET and OPTIONS**: no `access-control-*`. OPTIONS is 204.
- **Error and bytes paths**:
  - `GET /api/user-profile` without a key (401 via `respond_json`) carries the echo.
  - `POST /api/profile` then `POST /api/profile/delete` (204 via `respond_bytes`) with `Origin: LISTED` carries the echo.
- **Across every response above**: no header value equals `*`.
- **Parser**:
  - `parse_cors_origins("")` → empty.
  - `" http://a:1 , ,http://b "` → `{"http://a:1", "http://b"}`.
  - `"*, http://a"` → `{"http://a"}`.
  - `",,"` → empty.

Error bodies:
- **Metadata failure.**
  - Setup: a stub `BaseHTTPRequestHandler` Engine answers `/internal/videos/metadata` with 500 `{"error": "engine-sentinel-metadata-9c1d"}`. With `caplog.at_level(logging.ERROR)`, `POST /api/user-profile/likes` sends `{"likes": [{"uuid": "u1", "host": "h.example"}]}`.
  - Assertions:
    - status 502;
    - body `== {"error": "Engine metadata failed"}`;
    - the sentinel does not appear in the raw body;
    - the sentinel appears in `caplog.text`;
    - some ERROR record's JSON has `event == "engine.call"`.
  - The sentinel is plain ASCII, so it survives `ensure_ascii` escaping.
- **Bridge publish.**
  - Direct: `client_server._publish_to_engine_bridge(CLOSED_ENGINE, {"event_id": "e1"})` → `{"ok": False, "error": "engine bridge unavailable"}`.
  - Log: an ERROR record whose JSON `event == "engine.bridge"` and whose `context.error` is non-empty and differs from the fixed text. This is the log half; the exact errno text varies by platform.
- **Malformed JSON.** A `_raw` `POST /api/user-profile/likes` with body `b"{not json"` and content-type JSON → 400, `{"error": "Invalid JSON body"}`.

Engine children. Each asserts `ENGINE_PY.exists()`, runs with `cwd=SERVER_DIR / "api"`, and uses a child env of `os.environ` with `RECOMMENDATIONS_DEBUG` removed.
- **`_SIMILAR_CHILD`**:
  - Setup: `sys.path[:0] = [server, server/api]`; `from logging_profiles import configure_engine_logging`; `configure_engine_logging("verbose")`; `from handlers import similar`; `import server_config`.
  - `Handler` stub: `server = SimpleNamespace(default_limit=20, refresh_similarity_cache=False, recommendations_debug_enabled=server_config.RECOMMENDATIONS_DEBUG_ENABLED)`.
  - Cases, each with `respond_json` patched:
    1. `_handle_random` patched to raise `RuntimeError("sentinel-boom-4e2b")`, params `{"random": ["1"]}`;
    2. `_handle_random` raising `ValueError("sentinel-value-8a1c")`;
    3. `_handle_random` raising `ValueError("Vector norm is zero")`;
    4. params `{"debug": ["1"]}` with nothing patched beyond `respond_json`.
  - The child prints the respond calls and `server_config.RECOMMENDATIONS_DEBUG_ENABLED` as JSON on stdout.
  - Assertions:
    - (1) and (2) → `[500, {"error": "Recommendations request failed"}]`;
    - (3) → `[400, {"error": "Vector norm is zero"}]`;
    - (4) → `[403, {"error": "Debug mode is disabled"}]`;
    - the flag is `False`;
    - stderr, parsed line by line as JSON, has an ERROR line whose `traceback` contains `Traceback` and `sentinel-boom-4e2b`, and one containing `sentinel-value-8a1c`.
  - This runs the production formatter, not `lastResort`.
- **`_INGEST_CHILD`**:
  - Setup: `configure_engine_logging("verbose")`; `from handlers import internal_events`; `read_json_body` patched to return `{"events": [{"event_id": "x"}]}`; `respond_json` patched; `server = SimpleNamespace(db=None, db_lock=RaisingLock())`, where `RaisingLock.__enter__` raises `RuntimeError("sentinel-ingest-5d7e")`.
  - Assertions: a single call `[500, {"error": "Event ingest failed"}]`, and the stderr JSON `traceback` contains the sentinel.
- **Flag values**:
  - `sys.executable` children import `server_config` from `engine/server/api`, reusing `test_server_config.py`'s `_run` shape but with `RECOMMENDATIONS_DEBUG` set or stripped.
  - `1`, `true`, `yes`, `TRUE`, ` yes ` → True.
  - Unset, `""`, `0`, `no`, `on` → False.

### Tests: `tests/active/test_engine_response_defaults.py` (live `engine`, own invocation)

- **No Engine CORS.** Raw `http.client` requests to the fixture's port with `Origin: http://127.0.0.1:5173`:
  - `GET /api/health`;
  - `OPTIONS /recommendations` → 204;
  - `POST /recommendations` with `{}` (limit 1).
  - None carries a header starting `access-control-`.
- **Debug on.** `POST /recommendations?debug=1&limit=3` → 200, and every row has a `debug` key. The fixture sets `RECOMMENDATIONS_DEBUG=1`, so this proves env → `server_config` → `main()` → gate end to end.

### Docs

These follow the settled checklist:
- **DEPLOYMENT.md §7**: `RECOMMENDATIONS_DEBUG=1`, off by default, `1`/`true`/`yes` in any case, 403 `Debug mode is disabled` otherwise. Point at `/videos.html?debug=1`, not `/debug.html`. Prefer a per-unit drop-in over the shared `.env.bridge`.
- **DEPLOYMENT.md §6**: a `CLIENT_CORS_ORIGINS` paragraph:
  - exact origins; whitespace, blank entries and `*` are ignored;
  - unset in production;
  - `npm run dev` always targets `http://127.0.0.1:7172`, so default dev is cross-origin and needs this;
  - `localhost` and `127.0.0.1` are distinct entries, and `--port 5175` needs its own;
  - a change needs a restart.
- **DEPLOYMENT.md §3b**: the `Engine metadata failed` symptom (the HTTP status is now only in `journalctl`).
- **Triage rows**, optional.
- **The three READMEs**, as listed in the checklist.
- No file quotes the `RECOMMENDATIONS_DEBUG_ENABLED = True` constant any more.

### Departures from the high-level plan

1. **Engine formatter gains a `traceback` key.** This is operator decision (b). Without it, R3's "Engine log carries the traceback" is false in production.
2. **`_respond_engine_failure` logs a traceback when the `EngineApiError` wraps a non-transport cause.** The plan said no traceback. `_post_json` wraps unexpected exceptions (a non-JSON 200, `RemoteDisconnected`) into `EngineApiError`, and R3 wants a traceback for unexpected ones. Transport failures and HTTP-status failures stay traceback-free.
3. **The likes-import operation word is `metadata`, not `resolve`**, because that is the call it makes.
4. **The recommendations 500 message is `Recommendations request failed`, not `Internal server error`.** R3 requires the message to name the operation. The ingest message is `Event ingest failed` for the same reason.
5. **`_send_cors_headers` also refuses `Origin: *`**, as well as the parser dropping it. The constructor accepts any set, so the invariant is enforced where the header is sent.

### Deliberate simplifications and known limits

- **Exact-string origin match with no normalisation.** Ceiling: `localhost` and `127.0.0.1` need separate entries. Upgrade path: normalise both sides in the parser and the helper.
- **Origin set fixed for the process's life.** A change needs a restart, as with `TRUSTED_PROXIES`.
- **`Vary: Origin` only on a match.** With origins configured, a shared cache could serve a no-CORS response to a listed origin. This is accepted, since only local dev configures origins and nginx does not cache the API.
- **Not changed, by the plan's scope:**
  - The proxy HTTPError-without-payload branch still logs an upstream 5xx at WARNING.
  - `ENGINE_PROXY_INVALID` still logs nothing.
  - The bridge `engine bridge HTTP {code}` path still logs nothing.
  - All three bodies are already fixed text, and the Engine side logs its own 5xx with a traceback now. Raising these log levels is a follow-up if a strict reading of R3's logging clause is wanted.
- **Debug 403 without the variable is proven through an `ENGINE_PY` child**, which uses the imported `server_config` flag in a stub server. `main()`'s env-to-server wiring is proven only by the flag-on live test.
- **Pre-existing timeout behaviour.** An `OperationalError('interrupted')` inside `_handle_similar` or ingest still lands in the catch-all as a 500. It now has a fixed body and a logged traceback.

### Hand-off notes

- The Vite dev setup, including plain `npm run dev`, which always sets `VITE_CLIENT_API_BASE=http://127.0.0.1:7172`, gets no API access until `CLIENT_CORS_ORIGINS` lists the page's exact origin.
- `/videos.html?debug=1` shows `Debug mode is disabled` until the Engine runs with `RECOMMENDATIONS_DEBUG=1`.
- Neither variable should go in the shared `.env.bridge` on a host that also runs prod units; use a per-unit drop-in.
- Run `test_engine_response_defaults.py` in its own `validate_tests.py` invocation, because of the Engine rate limit.
- At harvest, add both new test files to `.un/skills/devsecops/config.json` and map `logging_profiles.py`.

### Phases

#### Phase 1 - Client CORS by exact origin [code]

**Files touched.** client/backend/lib/http_utils.py (EDITED), client/backend/server.py (EDITED), tests/active/test_response_defaults.py (NEW)

**Checkpoint.** Seam 1 is `parse_cors_origins` as a pure function: "" → empty; " http://a:1 , ,http://b " → {"http://a:1", "http://b"}; "*, http://a" → {"http://a"}; ",," → empty. Seam 2 is the HTTP boundary of a live Client. The test builds two `ClientBackendServer`s on ephemeral ports over a tmp users.db, the same construction as the `client_backend` fixture in tests/active/conftest.py plus the trailing `cors_origins` argument: one with frozenset() and one with frozenset({"http://127.0.0.1:5173"}). Both are read through raw `http.client` so every header is visible. Assertions: (a) With the empty set, GET /api/health and OPTIONS /api/user-profile carry no header starting `access-control-`, whatever the Origin, and OPTIONS is 204. (b) With the listed set, Origin http://127.0.0.1:5173 on a GET gets allow-origin echoed, `vary: Origin`, methods "GET, POST, OPTIONS", headers "content-type, x-profile-key", no max-age and no allow-credentials. (c) The same Origin on OPTIONS gets 204, the same headers, and max-age "600". (d) Origins http://localhost:5173, https://evil.example and `*` get no access-control-* header on GET or OPTIONS, and OPTIONS is still 204. (e) The 401 from GET /api/user-profile (respond_json) and the 204 from POST /api/profile/delete (respond_bytes) carry the echo. (f) No header value in any of these responses equals `*`.

**Intent.** The Client backend sends CORS headers only to a request whose Origin exactly matches the set that `parse_cors_origins` builds from CLIENT_CORS_ORIGINS in `main()` and that `ClientBackendServer` holds as `cors_origins`.

- C1 - `parse_cors_origins` turns a CLIENT_CORS_ORIGINS value into a frozenset of exact origins, dropping surrounding whitespace, blank entries and `*`.
- C2 - `respond_json`, `respond_bytes` and `respond_options` send access-control-* headers only when the request's Origin is in `server.cors_origins`: they echo that Origin with `Vary: Origin`, and they add max-age 600 only on the 204 preflight.

**Outcome.** ### `client/backend/lib/http_utils.py`
- New private `_send_cors_headers(handler, preflight=False)`. It reads the request's `Origin` from the handler. If that Origin is exactly in `handler.server.cors_origins`, it sends: `access-control-allow-origin` set to that Origin, the existing allow-methods (`GET, POST, OPTIONS`) and allow-headers (`content-type, x-profile-key`), `access-control-max-age: 600` only when `preflight` is true, and `vary: Origin`. For any other Origin, or none, it sends no `access-control-*` header and no `Vary`.
- `respond_json` and `respond_bytes` no longer hard-code `access-control-allow-origin: *` and the allow-* headers. They call `_send_cors_headers(handler)` instead.
- `respond_options` still answers 204 but now calls `_send_cors_headers(handler, preflight=True)`, so max-age goes out only alongside an echoed Origin. Nothing in this module sends `*` any more.

### `client/backend/server.py`
- New `parse_cors_origins(value) -> frozenset[str]`, placed next to `parse_trusted_proxies`. It splits on commas, trims whitespace, and drops blank entries and `*`. Matching is exact: no case folding and no trailing-slash normalisation. A value listing nothing gives the empty set, so no origin is allowed.
- `ClientBackendServer.__init__` takes a new trailing argument, `cors_origins: frozenset[str] = frozenset()`, after `trusted_proxies`, and stores it as `self.cors_origins`. The existing six-argument construction (as in conftest's `client_backend`) holds the empty set.
- `main()` parses `CLIENT_CORS_ORIGINS` from the environment right after `TRUSTED_PROXIES`, before the signal swap and the DB/bind, and passes the result to `ClientBackendServer`.
- For the hand-off: once this lands, the Vite dev setup gets no CORS headers until the Client backend is started with `CLIENT_CORS_ORIGINS` set to the Vite origin (e.g. `http://127.0.0.1:5173`). This is by design under ADR-0004, and `DEPLOYMENT.md` documents it in a later phase.

### `tests/active/test_response_defaults.py`
Not created here. The phase list names it as NEW, but this step asks only for the production code behind the checkpoint `tests/tmp/test_15_tighten_response_defaults_phase1.py`. The durable test is expected to be promoted from that checkpoint by the workflow.

#### Phase 2 - Engine CORS off, debug opt-in [code]

**Files touched.** engine/server/api/http_utils.py (EDITED), engine/server/api/server_config.py (EDITED), engine/server/api/handlers/similar.py (EDITED), tests/active/conftest.py (EDITED), tests/active/test_engine_response_defaults.py (NEW), tests/active/test_response_defaults.py (EDITED)

**Checkpoint.** Seam 1 is `server_config` imported in a `sys.executable` child with a controlled environment, following the `_run` pattern in tests/active/test_server_config.py. RECOMMENDATIONS_DEBUG set to 1, true, yes, TRUE or " yes " gives RECOMMENDATIONS_DEBUG_ENABLED True. Unset, "", 0, no or on gives False. Seam 2 is an ENGINE_PY child with RECOMMENDATIONS_DEBUG removed from its env, following tests/active/test_similar.py. It calls `_handle_similar` with params {"debug": ["1"]} on a stub server whose recommendations_debug_enabled comes from the imported server_config, and asserts respond_json receives [403, {"error": "Debug mode is disabled"}]. Seam 3 is the live `engine` fixture in tests/active/conftest.py, whose env now includes RECOMMENDATIONS_DEBUG=1. The test lives in tests/active/test_engine_response_defaults.py and runs in its own validate_tests.py invocation. Raw http.client requests with Origin http://127.0.0.1:5173 to GET /api/health, OPTIONS /recommendations (which answers 204) and POST /recommendations carry no header starting `access-control-`. POST /recommendations?debug=1&limit=3 answers 200, and every row has a `debug` key. The existing test_profiles.py debug.profile read stays green.

**Intent.** The Engine sends no CORS header on any response, and it returns recommendation debug metadata only when its environment sets RECOMMENDATIONS_DEBUG to 1, true or yes.

- C1 - No Engine response, OPTIONS included, carries a header starting `access-control-`.
- C2 - RECOMMENDATIONS_DEBUG_ENABLED is true only when RECOMMENDATIONS_DEBUG, stripped and lower-cased, is 1, true or yes; otherwise a debug=1 recommendations request answers 403.

**Outcome.** ### `engine/server/api/http_utils.py`
- `respond_json` no longer sends any `access-control-*` header. The three lines are gone: allow-origin `*`, allow-methods and allow-headers. It still sends content-type and content-length. New docstring: "Send a JSON response; the Engine sends no CORS headers (ADR-0004)."
- `respond_options` now answers a bare 204 (`send_response(204)` then `end_headers()`). Its four `access-control-*` lines are gone, max-age included. New docstring: "Answer an OPTIONS request 204 with no CORS headers (ADR-0004)."
- Neither helper reads `Origin` or `server`. The Engine has no other place that writes headers.

### `engine/server/api/server_config.py`
- New `_resolve_flag_env(name) -> bool`, next to the other `_resolve_*_env` helpers. It returns true only when the variable, stripped and lower-cased, is `1`, `true` or `yes`. Any other value, blank or unset, gives false. It never raises.
- `RECOMMENDATIONS_DEBUG_ENABLED = _resolve_flag_env("RECOMMENDATIONS_DEBUG")` replaces the literal `True`. The comment above it now names the variable. The flag is read once, when the module is imported. `server.py`, which passes it into `SimilarServer`, is unchanged.

### `engine/server/api/handlers/similar.py`
- The `do_OPTIONS` docstring changes from "Handle CORS preflight." to "Answer OPTIONS 204 with no CORS headers." No behaviour changes: the existing 403 check in `_handle_similar` (`Debug mode is disabled`) now takes its value from the env-derived flag.

### `tests/active/conftest.py`
- The `engine` fixture adds `"RECOMMENDATIONS_DEBUG": "1"` to the env it gives the Engine process, after `**os.environ`, so a value exported in the shell cannot override it. The pytest process's own `os.environ` is untouched. Without this, every Engine-backed test that reads `debug.profile` (`test_profiles.py`) would get a 403 now that debug is off by default.

### `tests/active/test_engine_response_defaults.py`, `tests/active/test_response_defaults.py`
- Not created or edited in this step, same as in phase 1. This step asks only for the production code behind `tests/tmp/test_15_tighten_response_defaults_phase2.py`. I'm assuming the workflow promotes the durable tests from the checkpoint.

### Hand-off
- Any Engine started without `RECOMMENDATIONS_DEBUG=1` now answers `?debug=1` on `/recommendations` and `/videos/similar` with 403 `Debug mode is disabled`, so `/videos.html?debug=1` shows that error until the variable is set.

#### Phase 3 - Client fixed failure bodies [code]

**Files touched.** client/backend/server.py (EDITED), tests/active/test_response_defaults.py (EDITED)

**Checkpoint.** Seam 1 is the Client's HTTP boundary with a stub Engine. A stdlib BaseHTTPRequestHandler stub answers /internal/videos/metadata with 500 {"error": "engine-sentinel-metadata-9c1d"}. A Client is built over that stub as in phase 1's harness. With caplog at ERROR, POST /api/user-profile/likes sends {"likes": [{"uuid": "u1", "host": "h.example"}]}. It must answer 502 with body exactly {"error": "Engine metadata failed"}, and the sentinel must be absent from the raw body. The sentinel must appear in caplog.text, and some ERROR record's JSON must have event "engine.call". Seam 2 is `_publish_to_engine_bridge` called directly against a closed port. It returns {"ok": False, "error": "engine bridge unavailable"}, and an ERROR record with event "engine.bridge" carries a non-empty context.error that differs from the fixed text. Regression guard: POST /api/user-profile/likes with the raw body `{not json` still answers 400 {"error": "Invalid JSON body"}.

**Intent.** A failed Engine call or bridge publish now answers the Client's caller with fixed text that names the operation, and the failure's cause is recorded only in the Client log at ERROR.

- C1 - The 502 bodies for Engine-call failures and the `bridge_error` from a failed bridge publish carry only fixed text naming the operation, never the Engine's or the exception's text.
- C2 - The Client log records the failure's cause (the Engine's error text or the transport exception) at ERROR level.

**Outcome.** ### client/backend/server.py
- New handler method `_respond_engine_failure(operation, exc)`. It logs one ERROR record with event `engine.call` and message `Engine <operation> failed`, carrying the request path and `str(exc)` as `context.error`, so the Engine's error text reaches the Client log (C2). It then answers 502 with exactly `{"error": "Engine <operation> failed"}` (C1).
- All six Engine-call 502 sites now go through that method instead of putting `{exc}` in the body:
  - `_handle_user_action` resolve → `resolve`
  - `_handle_user_action` centroids → `centroids`
  - `_handle_block_add` → `lookup`
  - `_handle_user_profile_likes_get` → `metadata`
  - `_handle_user_profile_likes_from_client` → `metadata`
  - `_handle_likes_import` → `metadata`. This one used to say "Engine resolve failed", but the call it makes is the metadata call.
- `_publish_to_engine_bridge`:
  - **HTTPError:** still returns the fixed `engine bridge HTTP <code>`. It now also logs an ERROR `engine.bridge` record with the status and the Engine's response body as `context.error`.
  - **Any other failure:** the `URLError`/`TimeoutError` branch and the `# pragma: no cover` `Exception` branch are now one `except Exception` branch. It logs an ERROR `engine.bridge` record with `str(exc)` as `context.error` and returns exactly `{"ok": False, "error": "engine bridge unavailable"}`. The merge is needed because urlopen wraps a refused connection in `URLError` but lets a dropped connection through unwrapped as `http.client.RemoteDisconnected`. The red run showed this: `bridge_error` was `Remote end closed connection without response`, so the old catch-all branch was the one being hit.

### tests/active/test_response_defaults.py
Not touched. The phase lists it as EDITED, but the file does not exist in the repo, and this phase's checkpoint is `tests/tmp/test_15_tighten_response_defaults_phase3.py`. Presumably the file gets created when the tmp checkpoints are promoted later. That step is out of scope here, so I didn't create it.

#### Phase 4 - Engine fixed 500s with logged traceback [code]

**Files touched.** engine/server/api/handlers/similar.py (EDITED), engine/server/api/handlers/internal_events.py (EDITED), engine/server/api/logging_profiles.py (EDITED), tests/active/test_response_defaults.py (EDITED)

**Checkpoint.** The seam is ENGINE_PY children that run the production `configure_engine_logging("verbose")` from logging_profiles, following the ENGINE_PY child pattern in tests/active/test_similar.py, with stderr parsed as JSON lines. Similar child, with respond_json patched: `_handle_random` raising RuntimeError("sentinel-boom-4e2b") answers [500, {"error": "Recommendations request failed"}]. Raising ValueError("sentinel-value-8a1c") gives the same 500. Raising ValueError("Vector norm is zero") answers [400, {"error": "Vector norm is zero"}]. Stderr has an ERROR line whose `traceback` contains "Traceback" and sentinel-boom-4e2b, and another whose traceback contains sentinel-value-8a1c. Ingest child: read_json_body is patched to return one event, and db_lock raises RuntimeError("sentinel-ingest-5d7e") on enter. The result is a single [500, {"error": "Event ingest failed"}] call, and the stderr JSON `traceback` contains the sentinel.

**Intent.** The Engine's recommendations and ingest handlers answer an unexpected failure with a fixed 500 naming the operation, and `EngineJsonFormatter` writes that failure's traceback to the Engine log.

- C1 - `_handle_similar` and the ingest handler answer any failure outside the bad-request set with a fixed 500 body naming the operation, while a ValueError whose text is in SIMILAR_BAD_REQUEST_ERRORS still answers 400 with that text.
- C2 - A `logging.exception` record rendered by EngineJsonFormatter carries a `traceback` key holding the exception's traceback.

**Outcome.** ### `engine/server/api/logging_profiles.py`
`EngineJsonFormatter.format` now adds a `traceback` key, holding `self.formatException(record.exc_info)`, when a record carries `exc_info`. It goes in just before the JSON is serialised. Other keys are unchanged, and a record without `exc_info` renders exactly as before, with no key. This is operator decision (b). It also gives the existing `logging.exception("[ingest] raw-event retention strip failed")` its traceback.

### `engine/server/api/handlers/similar.py`
- Two new module constants after `SIMILAR_POST_ROUTES`:
  - `SIMILAR_BAD_REQUEST_ERRORS`, a frozenset of the three seed-resolution texts that were a local set literal inside `_handle_similar`.
  - `SIMILAR_FAILED_MESSAGE = "Recommendations request failed"`.
- The `except` branches in `_handle_similar`:
  - A `ValueError` whose text is exactly in `SIMILAR_BAD_REQUEST_ERRORS` still answers 400 with that text.
  - Any other `ValueError` now calls `logging.exception("[similar-server][%s] request failed", request_id)` and answers 500 `{"error": SIMILAR_FAILED_MESSAGE}`. Before, it answered 500 with the exception text and logged nothing.
  - The catch-all keeps `logging.exception("server error")` and now answers the same fixed 500 instead of `str(exc)`.
  - `finally: clear_request_context()` is unchanged.

### `engine/server/api/handlers/internal_events.py`
The ingest catch-all used to answer `respond_json(handler, 500, {"error": str(exc)})`. It now calls `logging.exception("[ingest] event ingest failed")` and answers 500 `{"error": "Event ingest failed"}`. The `ValueError` → 400 paths and the rollback-and-re-raise are unchanged.

### `tests/active/test_response_defaults.py`
Not touched. The files list names it as EDITED, but it does not exist in the tree. This phase's checkpoint is `tests/tmp/test_15_tighten_response_defaults_phase4.py`, which I did not edit either.


