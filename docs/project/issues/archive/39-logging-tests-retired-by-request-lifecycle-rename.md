# Replace the logging tests retired when request lines became request.start / request.end

Status: enhancement, complete
Origin: build 20-request-lifecycle-logs (plan `docs/project/plans/21-20-request-lifecycle-logs.md`), step 8 triage

## Problem

Build 20 replaced the Engine's `[access.start]` / `[access]` lines with `[request.start]` / `[request.end]` logged through a `structured_context` extra, and removed the old `_EVENT_RULES` entries (R4/R5, R9). R9 required every test asserting on `access.start` / `access` to be moved to the new events, including the issue-19 durable non-decreasing-ts test. Plan §Tests drafted those rewrites, but phases 1 and 2 listed the files and left them unedited. At step 8 the conflicting tests went red and were retired to `tests/archive/request_lifecycle_rename/`, not repointed.

Coverage now missing:

- **tests/active/test_logging_profiles.py** (archived as `test_logging_profiles.py`):
  - `ts` is `record.created` in UTC with milliseconds, under a pinned off-UTC zone, plus the `_format_ts` edge values (1741091696.789, 1741091696.9999996, one hour back).
  - The issue-19 property: in the session Engine log, ts never decreases from a marked request's start through its `recommendations.*` work to its end. This is the one R9 names explicitly.
  - `LOG_FORMAT` unset/`json`/`JSON`/`bogus`/empty gives the exact JSON payloads, and `text`/`TEXT`/` Text `/tab-text-newline gives one escaped text line per record.
- **engine/server/api/tests/test_logging_profiles.py** (archived as `engine_api_test_logging_profiles.py`): request-start tagged focused+verbose, the end message not duplicating context, and the smoke-stream event/mode set.

## Proposed solution

Write the plan §Tests rewrites (plan lines 1096-1109):

- In the probes (`_TS_CHILD`, `_LOG_FORMAT_CHILD`), log `[request.start] request started` with `extra={"structured_context": {"ip", "method", "url", "user_agent": "Mozilla/5.0 (X11; Linux)"}}`. `JSON_PAYLOADS[3]` becomes `request.start` with that context, and the text line becomes `INFO request.start request started ip=127.0.0.1 method=GET url=http://x/a user_agent=Mozilla/5.0 (X11; Linux) request_id=rid-a`.
- `test_engine_request_ts_never_decreases_from_request_start_to_request_end` finds the `request.start` whose `context.url` carries the marker, takes its `request_id`, and ends at the `request.end` with that id. It keeps the same-id `request.*` and `recommendations.*` records and keeps the ts assertions. A step-8 probe (`tests/tmp/test_probe_20_step8.py`, now emptied) saw this hold: one start, ten `recommendations.*` records and one end under a single 32-hex id, ts non-decreasing inside the request window.
- Engine unit tests: `[request.start]` with a spaced user agent (context equals the dict), `[request.end]` with `{"status": 200, "duration_ms": 3}` and no url/bytes, and the smoke stream ending in a `[request.end]` record expecting `request.end`. Add `set_request_id(None)` to tearDown (plan R8).

The ts and LOG_FORMAT tests guard issue 19's delivered behaviour, which no other active test covers, so they come first.

## Related

- `docs/project/issues/20-request-lifecycle-logs.md`, the build that retired them.
- `docs/project/issues/35-upnext-tests-retired-by-random-draw.md`, the same retire-then-replace pattern.

## Comments

Triage (2026-10-03): `enhancement, ready`. Not already covered: the active logging-profiles module holds only the traceback test, and the Client/Engine drift test in `test_server.py` checks the Engine's `_format_ts` for the two fixed values only, not the off-UTC end-to-end ts, the hour-back case, the Engine `LOG_FORMAT` payloads or the issue-19 request-order property. No prior rejection (`docs/project/rejected/` does not exist). Claim checked against the code: the Engine's request wrapper logs `[request.start] request started` and `[request.end] request finished` with a `structured_context` extra, and `EngineJsonFormatter` renders them as the proposed payload and text line describe. Decided with the maintainer: the three Engine unit-test rewrites go back into the Engine's own unittest module, where the originals lived, and not into the active suite.

## Agent Brief

**Category:** enhancement
**Summary:** Restore the Engine logging tests that build 20 retired, rewritten for the `request.start` / `request.end` events

**Current behavior:**
The Engine logs each HTTP request as a `[request.start] request started` record carrying `structured_context` `{ip, method, url, user_agent}` and a `[request.end] request finished` record carrying `{status, duration_ms}`, both under the request's 32-hex request_id. `EngineJsonFormatter` maps them to events `request.start` / `request.end`, tagged `focused` and `verbose`, with the fixed messages above and the structured context kept whole (a user agent with spaces stays one value). No test asserts any of this. The earlier tests pinned the removed `access.start` / `access` events and were retired, unedited, to the request-lifecycle-rename folder under the test archive, where they are skipped and readable as the reference for the rewrite.

**Desired behavior:**
The retired tests are back, asserting the same properties against the new events.

Active suite (the active `test_logging_profiles.py`, next to the existing traceback test, using its subprocess-child pattern with cwd at the Engine API directory):
- **ts test:** a child with `LOG_FORMAT` unset and `TZ` pinned off UTC logs `[probe] plain`, a `[request.start] request started` record with `structured_context` `{ip: 127.0.0.1, method: GET, url: http://x/a, user_agent: "Mozilla/5.0 (X11; Linux)"}`, and an error record. Every line's `ts` matches `YYYY-MM-DDTHH:MM:SS.mmmZ` and reads back within a minute of the child's clock; the messages are `[probe] plain`, `request started`, `[probe] failed without exception`. `_format_ts` and the formatter's `ts` give `2025-03-04T12:34:56.789Z` for created 1741091696.789, `2025-03-04T12:34:57.000Z` for 1741091696.9999996, and read back an hour-old `created` within 1 ms.
- **Request-order test (issue 19's property):** send the session Engine `POST /recommendations?limit=5&user_id=log-order-<hex>`. In its log, find the one `request.start` whose `context.url` carries the marker, take its `request_id`, and end at the `request.end` with that id. Of the records between, keep the same-id `request.*` and `recommendations.*` records: the first is `request.start`, the last `request.end`, at least one `recommendations.*` lies between, and every `ts` matches the format, falls within the request's wall-clock window (±1 s), and never decreases.
- **LOG_FORMAT JSON** (unset, `json`, `JSON`, `bogus`, empty) and **LOG_FORMAT text** (`text`, `TEXT`, ` Text `, tab-text-newline): the five-record child's fourth record becomes the `[request.start]` record above with request_id `rid-a`. Its JSON payload is `{"level": "INFO", "event": "request.start", "message": "request started", "modes": ["focused", "verbose"], "request_id": "rid-a", "context": {"ip": "127.0.0.1", "method": "GET", "url": "http://x/a", "user_agent": "Mozilla/5.0 (X11; Linux)"}}` in that key order. Its text line is `INFO request.start request started ip=127.0.0.1 method=GET url=http://x/a user_agent=Mozilla/5.0 (X11; Linux) request_id=rid-a`. The other four records' expectations are unchanged from the archived module.

Engine unittest module (the Engine API's own `tests/test_logging_profiles.py`, as `EngineJsonFormatterTests` methods):
- A `[request.start] request started` record with a `structured_context` holding a spaced user agent gets event `request.start`, message `request started`, both modes, and `context` equal to that dict.
- A `[request.end] request finished` record with `{"status": 200, "duration_ms": 3}` gets event `request.end`, message `request finished`, and `context` exactly that dict: no url, no bytes.
- The smoke stream test ends with a `[request.end]` record (with that structured context) and expects the event set to contain `request.end`; every record carries `ts`, request_id `abc123`, and is visible in focused and verbose.
- `tearDown` also calls `set_request_id(None)`, so no id leaks between tests.

**Key interfaces:**
- `EngineJsonFormatter.format()`, `_format_ts()`, `configure_engine_logging()`, `payload_visible_in_mode()` in the Engine's logging-profiles module
- `set_request_id()` / `clear_request_context()` in the Engine's request-context module
- `logging.info(..., extra={"structured_context": {...}})`, the record shape the Engine request wrapper emits
- The session `engine` fixture (`engine.request`, `engine.db_path` as the log path) in the active suite's conftest

**Acceptance criteria:**
- [ ] The active logging-profiles module runs the ts test, the request-order test and both LOG_FORMAT parametrised tests, and all pass via `validate_tests.py` on that file.
- [ ] No test in the active suite or the Engine unittest module asserts on an `access.start` or `access` event.
- [ ] The request-order test pairs start and end by `request_id`, not by url (`request.end` carries no url).
- [ ] The Engine unittest module passes under `python -m unittest` run from the Engine API directory, including the three new tests.
- [ ] Each restored assertion fails when its property is broken; for example, the request.start JSON test goes red if `_REQUEST_MESSAGES` stops mapping `request.start`, and the request-order test goes red if the marked start or end is missing.
- [ ] The active module's docstring no longer says these tests are retired; it describes what the module now proves.
- [ ] The test map in `tests/config.json` still maps `test_logging_profiles.py` to the Engine's logging-profiles module and request handler.

**Out of scope:**
- Any change to Engine logging code, event rules, messages or the request wrapper.
- Moving the Engine unittest module into the active suite (decided at triage: it stays where it was).
- The Client's logging tests in `test_server.py` and the static-page-visit runbook tests.
- Deleting or editing the archived modules; they remain as the historical record.
