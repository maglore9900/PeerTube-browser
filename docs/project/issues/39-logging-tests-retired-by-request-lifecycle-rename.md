# Replace the logging tests retired when request lines became request.start / request.end

Status: enhancement, needs-triage
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
