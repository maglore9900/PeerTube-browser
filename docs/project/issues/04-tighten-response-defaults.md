# Tighten Client and Engine response defaults

Status: bug, ready-for-agent
Origin: task 84, SI4-M1 — hardening notes from security audit runs 1-2

## Problem

The Client backend sends `access-control-allow-origin: *` on write endpoints, both services return raw exception text to callers, and `RECOMMENDATIONS_DEBUG_ENABLED` defaults to `True`.

## Proposed solution

Correct the three defaults.

1. Replace the wildcard CORS value in `client/backend/lib/http_utils.py` with a configured allowed origin.
2. Log the exception and return a generic message in the Engine error path in `engine/server/api/handlers/similar.py` and the Client error path in `client/backend/server.py`.
3. Set `RECOMMENDATIONS_DEBUG_ENABLED = False` by default in `engine/server/api/server_config.py` (and update the value `DEPLOYMENT.md` quotes).

## Comments

**Triage.** All three defaults confirmed against the code, and the Engine has the same problems too:

- Both the Client backend and the Engine send `access-control-allow-origin: *` on every response and preflight. Production is same-origin through nginx and needs no CORS. Only the Vite dev server calls the Client API cross-origin. Since the profile key travels in a header rather than a cookie, the wildcard's real exposure is anonymous cross-site requests, not use of a visitor's profile.
- Raw exception text reaches callers on the Engine's 500 paths (recommendations handler, event ingest) and on the Client backend's 502 paths, which either return `detail: str(exc)` or embed the `EngineApiError` text, itself carrying the Engine's error string.
- `RECOMMENDATIONS_DEBUG_ENABLED = True` has no runtime switch, and the Client proxy passes `debug` through, so any visitor can read scoring internals. The active suite (`test_profiles.py`) relies on `debug=1`, so flipping the default needs a switch the fixture can set.

No existing implementation, no prior rejection. Decisions (recorded in `docs/project/adr/0004-cors-opt-in-by-origin.md`):

- Client backend CORS: no headers by default; `CLIENT_CORS_ORIGINS` lists exact origins to echo, with `Vary: Origin`.
- Engine CORS: removed entirely.
- Debug: off by default, on with the env var `RECOMMENDATIONS_DEBUG=1`; the active-suite Engine fixture sets it.
- Error bodies (triage call): 5xx and 502 bodies carry a fixed message; the exception goes to the log. 4xx messages the code writes deliberately for callers (`Invalid JSON body`, `Missing event_id`, …) stay as they are.

## Agent Brief

**Category:** bug
**Summary:** Make CORS opt-in by origin, stop returning exception text on server errors, and turn recommendations debug off by default

**Current behavior:**
- The Client backend's JSON, bytes and preflight responses all send `access-control-allow-origin: *`, and so do the Engine's.
- Server-error responses carry raw exception text. The Engine's recommendations/similar handler returns `{"error": str(exc)}` on 500, and on the `ValueError`s it maps to 500. The Engine's event-ingest handler returns `str(exc)` on 500. The Client backend's Engine-proxy failures return `{"error", "code", "detail": str(exc)}`. Its other Engine-call failures return `{"error": "Engine … failed: <exception text>"}` with status 502, and that text includes the Engine's own error message.
- `RECOMMENDATIONS_DEBUG_ENABLED` is a hard-coded `True` in the Engine's server config. `?debug=1` on `/recommendations` or `/videos/similar`, which the Client backend proxies, returns per-row scoring internals to anyone. `DEPLOYMENT.md` quotes the constant as the way to toggle it.

**Desired behavior:**
- **Client CORS.** Read `CLIENT_CORS_ORIGINS` from the environment at startup: comma-separated exact origins (scheme://host[:port]), whitespace tolerated, empty or unset meaning none. On every response and preflight:
  - If the request's `Origin` header exactly matches a listed origin, send `access-control-allow-origin: <that origin>`, `Vary: Origin`, and the existing allow-methods / allow-headers (and max-age on preflight).
  - Otherwise send no `access-control-*` headers. The preflight still answers 204.
  - Never send `*`.
- **Engine CORS.** The Engine sends no `access-control-*` headers on any response, including OPTIONS.
- **Error bodies.** Every 5xx and 502 response from either service carries a fixed, human-readable message that names the failing operation (e.g. `"Engine metadata failed"`, `"Internal server error"`) and no exception text, repr or traceback. Any existing machine-readable `code` field stays. The full exception, with traceback for unexpected ones, is logged at error level. 4xx messages the code raises deliberately for callers are unchanged.
- **Debug.** Recommendations debug is enabled only when the Engine's environment has `RECOMMENDATIONS_DEBUG=1` (accept `1`/`true`/`yes`, case-insensitive). Otherwise it is off, and `?debug=1` gets the existing 403 `Debug mode is disabled`. The active-suite Engine fixture sets `RECOMMENDATIONS_DEBUG=1`, so the profile tests keep reading `debug.profile`.
- **Docs.** `DEPLOYMENT.md` replaces the quoted `RECOMMENDATIONS_DEBUG_ENABLED = True` toggle with the env var, and documents `CLIENT_CORS_ORIGINS`: unset in production, set to the Vite origin for the cross-origin dev setup.

**Key interfaces:**
- Client backend `respond_json`, `respond_bytes`, `respond_options`: need the request's `Origin` and the configured origin set. Both are reachable from the handler they are given; the set is parsed once at startup and held on the server object.
- Engine `respond_json` / `respond_options` equivalents in its HTTP utils: drop the CORS headers.
- Engine server config `RECOMMENDATIONS_DEBUG_ENABLED`: derived from the env var instead of a literal.
- Client backend `EngineApiError` handlers and the Engine-proxy failure paths; Engine recommendations handler and event-ingest handler exception branches.

**Acceptance criteria:**
- [ ] With `CLIENT_CORS_ORIGINS` unset, a Client backend response to a request with `Origin: https://evil.example` carries no `access-control-allow-origin`.
- [ ] With `CLIENT_CORS_ORIGINS=http://127.0.0.1:5173`, a request with that `Origin` gets it echoed plus `Vary: Origin`, and the preflight carries allow-methods, allow-headers (`content-type, x-profile-key`) and max-age. A request with any other origin gets no allow-origin.
- [ ] No response from either service contains `access-control-allow-origin: *`.
- [ ] No Engine response, OPTIONS included, carries any `access-control-*` header.
- [ ] Forcing an Engine metadata failure makes the Client backend answer 502 with a body that doesn't contain the Engine's error string, and the Client log contains it.
- [ ] Forcing an unexpected exception in the Engine recommendations handler yields 500 with a fixed message, and the Engine log carries the traceback.
- [ ] A malformed JSON body still yields 400 `Invalid JSON body`.
- [ ] With `RECOMMENDATIONS_DEBUG` unset, `/recommendations?debug=1` returns 403; with `RECOMMENDATIONS_DEBUG=1`, it returns rows carrying `debug`.
- [ ] The active suite passes, including the profile tests that read `debug.profile`.
- [ ] `DEPLOYMENT.md` documents both env vars and no longer quotes the constant.

**Out of scope:**
- CSP and other security headers (delivered by the old security remediation).
- Adding cookies or credentials to CORS (`access-control-allow-credentials` stays absent).
- Changing which 4xx messages exist or their wording.
- Logging format or log retention.
- The frontend's debug page or `dev.mjs` beyond documenting the env var.
