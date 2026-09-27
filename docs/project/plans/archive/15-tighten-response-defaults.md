# Opt-in CORS by origin, fixed server-error bodies, and recommendations debug off by default

## Requirements

### What was asked for

Build issue `docs/project/issues/04-tighten-response-defaults.md` as triaged: Make CORS opt-in by origin, stop returning exception text on server errors, and turn recommendations debug off by default. The Agent Brief below, copied from the issue, is the confirmed requirement set; the build starts from this file.

### Purpose

Close the security-audit finding the issue records. This build is one of issues 01-06, delivered concurrently to use as little operator time and cause as few merge conflicts as possible.

### Decisions this rests on

`docs/project/adr/0004-cors-opt-in-by-origin.md`.

### Agent Brief

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

### Consistency constraints

- Match the surrounding code's style: stdlib HTTP handlers, `respond_json`, module-level named constants, and env vars read once at startup.
- Backwards compatibility is not required beyond what the brief states.
- Run `validate_tests.py` from the root of the tree this build runs in (a worktree for waves 1-2, main for wave 3). That tree's `.un` config carries it as `project_dir`.

### Batch context

Part of the security hardening batch (`.scratch/security-hardening-batch/notes.md`): issues 01-06 delivered in three waves of git worktrees. Wave 1 is plans 10, 11 and 12. Wave 2 is 13 and 14, branched from main after wave 1 merges. Wave 3 is 15, on the merged main. A wave 1 or 2 build runs in its own worktree created by `.scratch/security-hardening-batch/worktree-setup.sh`, merges to main when it closes, and is harvested on main, not in the worktree.

Wave 3: last, on main after plans 10-14 merge. It touches every 5xx/502 site, so it runs after the plans that change those sites. Plan 14 replaces the resolve calls, plan 11 adds to `internal_events.py`, and plans 11 and 12 edit `DEPLOYMENT.md` and `server_config.py`. It needs no worktree.

### Conflicts

The brief does not conflict with the tree. Every function and line it names was checked against the source on 2026-09-26 (`.scratch/security-hardening-batch/notes.md`, File overlap). Line numbers will drift once earlier waves merge, so re-locate by function name at Step 3.

## High-level plan

### Approach

**Client CORS.** `CLIENT_CORS_ORIGINS` is parsed once at startup into a set held on the server object. `respond_json`, `respond_bytes` and `respond_options` in `client/backend/lib/http_utils.py` read the request's `Origin` from the handler they are given. When the origin is in the set, they echo it with `Vary: Origin` and the existing allow-methods and allow-headers. Otherwise they send no `access-control-*` headers. Preflight returns 204 either way.

**Engine CORS.** `engine/server/api/http_utils.py` removes the CORS headers from `respond_json` and `respond_options`.

**Error bodies.** Every 5xx/502 site returns a fixed message naming the operation instead of exception text, and logs the exception with its traceback at error level. Any `code` field stays, and deliberate 4xx messages are unchanged. Plan 14 moves some sites, so Step 3 lists them again on the merged tree. The sites today are Client `server.py` 649-656, 718, 745, 843, 905, 961, 980 and 1002, and Engine `internal_events.py:71` and `similar.py:1020-1024`.

**Debug.** `RECOMMENDATIONS_DEBUG_ENABLED` in `server_config.py:370` derives from the env var `RECOMMENDATIONS_DEBUG` (`1`/`true`/`yes`, case-insensitive). The active-suite `engine` fixture (`tests/active/conftest.py:105`) adds `RECOMMENDATIONS_DEBUG=1` to its env.

**Docs.** `DEPLOYMENT.md:408` replaces the quoted constant with the env var and documents `CLIENT_CORS_ORIGINS`.

### Alternatives considered

- **A single configured origin instead of a list.** Rejected by ADR-0004: a dev setup may use more than one Vite origin, and a list costs nothing extra.
- **Keeping Engine CORS behind a flag.** Rejected by ADR-0004: the browser never reaches the Engine.
- **Building this in wave 1 with the others.** Rejected: it edits the same lines as plans 13 and 14 at the Client's 502 sites and would have to be redone after they merge.

### Risks and limitations

- Tests that assert on error strings containing exception text will change. The Step 0 baseline on the merged main shows them.
- Some 502 bodies embed `EngineApiError` text built from the Engine's error string. Meeting the "no Engine error string in the Client body" criterion therefore needs changes on both sides.
- The Vite dev setup stops working until `CLIENT_CORS_ORIGINS` is set, as documented. Say this in the hand-off.
- **Shared `whitelist.db`.** The worktree symlinks the main tree's `whitelist.db`, so this build's test Engines write interaction rows into the same file as other lanes, and as the live Engine if it runs. Every test run already does this; worktrees only make it concurrent.
- **Tracked test record.** `tests/last_test_validation.json` and `tests/last_test_output.txt` always conflict on merge. Take main's copy and re-run `validate_tests.py --compare` on the merged tree.
- **Engine rate limit.** Run Engine-backed test files in their own `validate_tests.py` invocations (memory `engine-rate-limit-single-lane-test-runs`).

### Tradeoffs accepted

Cross-origin dev needs an env var, and error bodies lose their diagnostic text, which moves to the logs.
