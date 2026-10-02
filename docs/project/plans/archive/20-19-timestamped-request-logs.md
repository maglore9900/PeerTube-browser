# 19-timestamped-request-logs

_Rendered by the `dev-flow` workflow from its run state. Every edit here is overwritten on the next step; the evidence each gate turned on is in `docs/project/plans/20-19-timestamped-request-logs.record.md`._

## Requirements

### Purpose

Issue 19 (task 41, [M7][F4]) is the first of the logging chain: 19 timestamped logs, then 20 request lifecycle logs with a shared `request_id`, then 21 static page visit logs. The goal is to make request timing analysis possible from the application's own log lines. Each record must carry an explicit, unambiguous, comparable timestamp, so the order of request-start, work and request-end within a request can be read from the app log alone. That must not depend on the journald envelope time or on how a given message happens to be formatted. Both long-running services must use the same timestamp and line format, so their logs can be compared side by side.

### Current state (found in the tree)

- Engine API server: `configure_engine_logging` in `engine/server/api/logging_profiles.py` installs `EngineJsonFormatter` on the root logger (one StreamHandler, INFO). It is called from `engine/server/api/server.py` line 323. Each record becomes one JSON line with keys `ts`, `level`, `event`, `message` (dropped for `service.lifecycle`), `modes`, plus `request_id`, `context` and `traceback` when present. `ts` is `datetime.now().astimezone().isoformat(timespec="milliseconds")`. That is local time with a numeric offset, and it is taken when the record is formatted, not when it was created.
- Engine request lines: `[access.start]` (`_log_access_start`) and `[access]` (`log_message`) in `engine/server/api/handlers/similar.py` are plain `logging.info` calls rendered by that formatter, with events `access.start` and `access`.
- Client backend: `client/backend/server.py` calls `logging.basicConfig(level=logging.INFO, format="%(message)s")` in `main()`. All its logs go through `_emit_client_log(level, event, message, context)`, which builds its own JSON string. The keys are `ts` (same local-time expression as the Engine), `level`, `service: "client-backend"`, `event`, `message` and optional `context`. Access lines come from `ClientBackendHandler.log_message` as event `client.access`. A record that does not go through `_emit_client_log` (for example a library logging to the root logger) is printed as its bare message with no timestamp.
- Consumers of the JSON: `engine/watch-engine-logs.sh` runs `journalctl -o cat | jq -R 'fromjson?'` and filters on `.modes`, `.level`, `.event` and `.message`. `client/watch-client-logs.sh` runs `jq -R 'fromjson? // {"raw": .}'`. The DEPLOYMENT.md runbooks send operators to the `traceback` key (Engine) and to `context.error` of the ERROR `engine.call` / `engine.bridge` records (Client).
- Existing tests: `engine/server/api/tests/test_logging_profiles.py` asserts `"ts" in payload`. `tests/active/test_logging_profiles.py`, `tests/active/test_internal_events.py` and `tests/active/test_similar.py` run `configure_engine_logging("verbose")` and parse the JSON lines (including `traceback` and `message`).

### Scope

In scope: the Engine API server process (everything logged through the root logger once `configure_engine_logging` has run) and the Client backend process (`client/backend/server.py`).

Out of scope:
- `request_id` propagation and request-end `duration_ms` (issue 20).
- nginx and static page visit logging (issue 21).
- The batch scripts in `engine/server/db/jobs/` and `updater-worker.py`, which keep their own plain `basicConfig` formats.
- Raw stderr output that does not pass through `logging`: socketserver's default `handle_error` traceback print and the `faulthandler` SIGUSR1 stack dump.

### R1 — Explicit UTC timestamp with milliseconds

- Every log record written by either service carries a timestamp in ISO-8601 extended format, in UTC, with millisecond precision and a `Z` zone marker, in exactly this shape: `YYYY-MM-DDTHH:MM:SS.mmmZ`, e.g. `2025-03-04T12:34:56.789Z`. No local time and no numeric offset (`+00:00` is not the accepted form; `Z` is).
- The timestamp is taken from the moment the log call was made (`logging.LogRecord.created`), not from when the formatter runs.
- In JSON output the timestamp stays under the existing key `ts`.

### R2 — One shared format across both services

- The Engine and the Client backend produce records to one contract: the same `ts` format (R1), the same `level` names (the stdlib level names `DEBUG`/`INFO`/`WARNING`/`ERROR`/`CRITICAL`), and the same leading key order `ts`, `level`, then the remaining keys.
- Request lifecycle lines (Engine `access.start` and `access`, Client `client.access`) and internal server lines (service start/stop/lifecycle, recommendations and similarity logs, `engine.call` and `engine.bridge` errors, any WARNING/ERROR) all go through this format. No record from either process reaches its output stream without the timestamp.
- The Client backend gets a real formatter on its root logger, the same way the Engine has one. A record logged in the Client by any path other than `_emit_client_log` (a bare `logging.*` call or a library's logger) is still emitted in the shared format with `ts`, `level` and an event. The Client's existing payload keys (`service: "client-backend"`, `event`, `message`, `context`) are preserved.
- How the code is shared between the two services (one shared helper or two matching implementations) is a design decision for later steps. The requirement is the identical output contract.

### R3 — Output format switch (JSON default, plain text opt-in)

- One environment variable, `LOG_FORMAT`, read by both services at logging setup, selects the output format: `json` (default) or `text`. Matching is case-insensitive and ignores surrounding whitespace.
- An unset, empty or unrecognised value selects `json`. It fails safe the same way `normalize_log_mode` falls back to `verbose`, and it must not stop the service from starting.
- JSON stays the default because `engine/watch-engine-logs.sh`, `client/watch-client-logs.sh` and the DEPLOYMENT.md runbooks depend on it. In JSON mode the existing keys and their meaning are unchanged: Engine `ts`, `level`, `event`, `message`, `modes`, `request_id`, `context`, `traceback`, including the per-event message rewriting already in `EngineJsonFormatter`; Client `ts`, `level`, `service`, `event`, `message`, `context`. Only the value format of `ts` changes (R1).
- The Engine's existing `focused`/`verbose` log mode concept (`modes` tagging) is separate from `LOG_FORMAT` and is not changed.
- Where the variable is documented (the service README/DEPLOYMENT notes alongside other env settings), add `LOG_FORMAT` with its two values and the default.

### R4 — Plain text line shape

- In `text` mode each record is one line: `<ts> <LEVEL> <event> <message>`. Then come the record's context entries as space-separated `key=value` tokens (where the record has a context dict, as the Client's do), then `request_id=<id>` when a request id is present. For the Engine, `message` is the same message text the JSON payload would carry.
- The `ts` in text mode is the identical string R1 defines, so text and JSON lines from the same moment carry the same timestamp.

### R5 — journald compatibility

- Exactly one physical line per record in both formats, because journald stores each stdout line as its own entry. In JSON mode this is already true (`json.dumps` escapes newlines). In text mode, any newline inside the message or the traceback is escaped (rendered as the two characters `\n`), so one record is never split across journal entries. In text mode the traceback is appended on that same line.
- No syslog priority prefixes (`<N>`) or other markers that journald would interpret. Output goes to the same stream as today (the Engine's StreamHandler default, stderr; the Client's `basicConfig` default, stderr), so the existing systemd units and `journalctl -u … -o cat` pipelines keep working unchanged.
- Nothing in the logs or the tooling relies on the journal envelope timestamp for ordering. The application `ts` is the timestamp of record.

### R6 — Ordering by application timestamp

- For a single request handled on one thread, the `ts` of its request-start line (Engine `access.start`), of any work log lines emitted while handling it, and of its request-end line (Engine `access`, Client `client.access`) are non-decreasing in that order. Because `ts` comes from `record.created` (R1), it reflects when each event happened, not when the line was formatted.
- Ordering is guaranteed per request, not globally across concurrently served requests (consistent with issue 20).

### Validation

- A sample record from each service, in each format, contains a full date and time with milliseconds and the `Z` timezone marker, matching `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$` for the `ts` value.
- An Engine request produces `access.start`, work and `access` records whose `ts` values are non-decreasing.
- `ts` equals the record's creation time rendered in UTC: a record created at a known `created` value renders that instant, not the formatting time.
- `LOG_FORMAT` unset, `json`, `JSON`, `bogus` and empty each select JSON; `text` (any case) selects the text line. Every record is a single line in both modes, including one with a traceback and one whose message contains a newline.
- The Client backend emits a record in the shared format both for `_emit_client_log` calls and for a bare `logging.info` call made after its logging setup.
- The existing JSON consumers keep working: Engine payload keys and per-event message rewriting unchanged, and the existing tests that parse the Engine JSON (`tests/active/test_logging_profiles.py`, `test_internal_events.py`, `test_similar.py`, `engine/server/api/tests/test_logging_profiles.py`) still pass.

### Baseline suite state

The pre-build baseline run exited with code 0 (`variant: false`): the active suite in `tests/active` is green before this build starts. Any red test after the build is attributable to the build. The project dir is `/home/enduser/code/PeerTube-browser/.worktrees/19`, the working test dir is `tests/tmp`, the archive is `tests/archive`, the plans live in `docs/project/plans`, the run record is `tests/last_test_validation.json` and the output is `tests/last_test_output.txt`.

## High-level plan

### Approach

The change is in the formatter layer of each service. No call site changes, except that the Client's `_emit_client_log` stops serialising JSON by hand. I read `engine/server/api/logging_profiles.py`, `client/backend/server.py` (lines 120-136 `_emit_client_log`, 258-273 `log_message`, 1175-1252 `main`), the Engine's call site at `engine/server/api/server.py:323`, and `tests/active/conftest.py:41`, which already imports the Client `server` module in-process.

**Timestamp (R1, R6).** Each service gets one small private helper that turns a `LogRecord` into the `ts` string. It renders `record.created` in UTC as `YYYY-MM-DDTHH:MM:SS`, appends `.` and the record's milliseconds as three digits, then appends a literal `Z`. All of this is stdlib. The value comes from `record.created`, which `logging` sets at the moment of the log call, not from `datetime.now()`. So ordering within one thread follows the order of the calls even if formatting happens later. That gives R6 for `access.start`, the work lines and `access` / `client.access`. Both the seconds and the milliseconds are taken from the same `created` value, so they cannot disagree. The `+00:00` form that `isoformat` would produce is avoided by building the string explicitly.

**Engine (R1-R5).** `EngineJsonFormatter.format` keeps all of its classification, request-id extraction, context building and per-event message rewriting exactly as it is. Only the `ts` value changes, and it now comes from the record. The work is split so the formatter first builds the payload dict as it does today, then renders it one of two ways:
- JSON: today's `json.dumps`, unchanged.
- Text: one line made of `ts`, `level`, `event` and the payload's `message`, separated by spaces. If the payload has a `context`, its entries follow as `key=value` tokens. Then comes `request_id=<id>` when present, then the traceback.

Because both renderings use the same payload, the text-mode message is by construction the message JSON would carry ("request started", "request finished", "[recommendations] incoming likes"). The formatter chooses its rendering when it is constructed. `configure_engine_logging` reads `LOG_FORMAT` from the environment when it runs and passes the normalised choice to the formatter. Its signature `configure_engine_logging(profile)` stays the same, so `server.py:323` and the four existing test modules need no change. A small `normalize_log_format` sits next to `normalize_log_mode` with the same fail-safe shape: strip, lowercase, `text` means text, anything else means `json`.

**Client (R2-R5).** The Client gets a real formatter on its root logger. `main()` replaces `logging.basicConfig(format="%(message)s")` with a `configure_client_logging()` call. That function clears the root handlers, sets INFO, adds a StreamHandler (stderr, as today), installs the Client formatter and reads `LOG_FORMAT` the same way the Engine does. `_emit_client_log` keeps its signature and its call sites. It no longer builds a JSON string. Instead it calls `logging.log(level, message, extra=...)` and passes `event` and `context` as record attributes. The formatter builds the payload in the order `ts`, `level`, `service: "client-backend"`, `event`, `message`, `context`, which is the same keys in the same order as today. A record without those attributes, such as a bare `logging.info` call or a library logger, gets `event` set to a fallback name (`client.log`, matching the Engine's `engine.log` fallback) and its `getMessage()` as `message`. If the record has `exc_info`, the formatter adds a `traceback` key the way the Engine does. That key is new to the Client, but it is additive, and without it an exception logged through the root logger would be silently lost. Text mode uses the same line shape as the Engine.

**Text rendering details (R4, R5).** Context values that are scalars are written with `str()`. Values that are lists or dicts, for example the Engine's incoming-likes context, are written as compact JSON so each one stays a single token. Once the line is assembled, every CR and LF in it (message, context values, traceback) is replaced by the two-character escapes `\r` / `\n`. Every record is therefore one physical line. Nothing is added in front of the line, so there are no `<N>` prefixes and no extra markers. For `service.lifecycle`, where JSON drops `message`, the text line leaves the message token out and goes straight from event to context.

**Docs (R3).** One `LOG_FORMAT` paragraph goes into DEPLOYMENT.md beside the other Engine/Client environment settings (around lines 105-114). It states the values `json` (default) and `text`, the fail-safe behaviour, and that the watch scripts and runbook `jq` recipes need `json`. It also says how to set the variable: through `.env.bridge` or an `Environment=` drop-in.

**Requirement map.**
- R1: the UTC helper built from `created`.
- R2: two formatters to one contract. Both have leading `ts`/`level`, use stdlib level names and use the same helper shape, and the Client now has a root formatter that catches bare records.
- R3: `LOG_FORMAT` normalisation in both setup functions; the JSON keys are unchanged.
- R4: the shared payload-to-text rendering.
- R5: newline escaping, unchanged streams and no prefixes.
- R6: `created`-based `ts`.

### Alternatives considered

- **One shared module for both services**, for example `common/log_format.py` at the repo root. Rejected. The Engine imports from `engine/server/api` (`from request_context import …`) and the Client from `client/backend` (`from lib.… import …`). Neither has the repo root on `sys.path`, so sharing would need a `sys.path` insert in both entry points, the install scripts and the tests, and it would join two independently deployed units at import time. The duplicated logic is about a dozen lines: the ts helper, the text renderer and the format normaliser. I chose two matching implementations and a cross-service test as the guard against drift. This is a deliberate simplification. Its ceiling is that the two copies can diverge if someone edits only one. The upgrade path is to extract a shared package once a third consumer appears, for example the issue-21 static visit logger if it is written in Python.
- **Keep `_emit_client_log` building JSON and add `basicConfig(format="%(asctime)s …")`.** Rejected. A record from `_emit_client_log` would then contain JSON inside a text prefix. That breaks `watch-client-logs.sh`'s `fromjson?` and does not meet "same format".
- **Set `logging.Formatter.converter = time.gmtime` and use `formatTime`.** Rejected. `formatTime` with `default_msec_format` gives `,mmm` and no `Z`, so it would need overriding anyway. A class-level `converter` change also leaks process-wide. An explicit helper is clearer.
- **Read `LOG_FORMAT` in `server_config.py` (Engine) at import.** Rejected. Reading it at logging setup is what R3 asks for. It also lets tests monkeypatch the environment and call `configure_engine_logging` without reloading a module.
- **Wrap the existing JSON formatter in a separate text formatter class.** Rejected as an extra class for one switch. A constructor flag on the existing formatter is smaller.

### Risks and gotchas

- **Validation timing.** `record.created` is fixed when the record is created. A test that builds a `LogRecord` with a chosen `created` (and the matching `msecs`, which is derived at construction) must set both to check "renders that instant". The plan derives milliseconds from `created` itself rather than trusting `msecs`, so setting `created` alone is enough.
- **Ambiguous text tokens.** In text mode, a context value or message containing spaces or `=` is not quoted, so `key=value` tokens are best-effort for human reading, not a parseable format. JSON remains the machine contract. This is a named limitation.
- **The Client `extra=` names** must not collide with reserved `LogRecord` attributes (`message`, `msg`, `args`, …). They will be namespaced, for example `client_event` and `client_context`.
- **Third-party library records in the Client** now appear as structured lines with event `client.log`. Before, they appeared as bare text. Any record with level below INFO is still filtered as today.
- **The existing Engine tests** read `ts` only for presence, so the format change does not break them. If the CI environment ever exported `LOG_FORMAT=text`, the JSON-parsing tests would fail. The new tests pin `LOG_FORMAT` explicitly, and the existing ones rely on the default.
- **The Client test seam.** `conftest.py` imports the Client `server` module in-process, so the formatter can be tested directly. A test that calls `configure_client_logging()` replaces the root handlers of the pytest process and must restore them, the same way the Engine tests already handle `configure_engine_logging`.
- **Out of scope, still untimestamped.** Raw stderr (socketserver `handle_error`, the faulthandler dump) still has no timestamp. The requirements say so explicitly.

### Tradeoffs for the operator

- There are two parallel implementations of one contract instead of a shared module. Drift is guarded by a test rather than by structure.
- Text mode is for humans. It escapes newlines and does not quote values, so tooling must keep using JSON.
- The Client gains an additive `traceback` key on records logged with `exc_info`. It is not part of the existing key list but is needed so no exception is dropped.
- `ts` changes from local time with an offset to UTC `Z`. Operators reading raw lines see UTC rather than local wall-clock time.

## Impacts


<impacts>
<impact path="engine/server/api/logging_profiles.py" element="imports (lines 5-12)">
**What changes.** `from datetime import datetime` (line 9) is used only for the `ts` at line 195. The new UTC helper needs `datetime.fromtimestamp(created, tz=timezone.utc)` or `time.gmtime`, so this import changes to `from datetime import datetime, timezone` (or to `time`). The text renderer and the env read need `import os`, which the module does not import today. `json` stays: it is used by `_normalize_incoming_likes_context`, the JSON render, and the compact rendering of list/dict context values in text mode.

**Depends on it.** Only this module.

**Risk: low.** If the `datetime` import is left unused after the change, linting may flag it. The module must keep importing only the stdlib and `request_context`: `tests/active/test_logging_profiles.py:36` relies on running it under pytest's own interpreter.
</impact>
<impact path="engine/server/api/logging_profiles.py" element="new `normalize_log_format()` next to `normalize_log_mode()` (line 73), plus a supported-formats constant">
**What changes.** A new public function that mirrors `normalize_log_mode`: `(value or "").strip().lower()`; it returns `"text"` when the value is `text` and `"json"` for anything else, including `None`, `""`, `"JSON"` and `"bogus"`. It would go beside `SUPPORTED_LOG_MODES` (line 15), possibly with a `SUPPORTED_LOG_FORMATS = ("json", "text")` tuple in the same style.

**Depends on it.** `configure_engine_logging` and the new tests. The Client gets its own copy because there is no shared module (plan, "Alternatives").

**Risk: low.** It must never raise, because R3 requires that a bad value does not stop startup. Note that `server_config._resolve_log_profile_env` (server_config.py:12-15) is a second, separate normaliser for `RECOMMENDATIONS_LOG_PROFILE`. It stays untouched, and the plan rightly does not put `LOG_FORMAT` there.
</impact>
<impact path="engine/server/api/logging_profiles.py" element="new private ts helper (UTC from `record.created`)">
**What changes.** A new `_format_ts(record)` (or similar). It renders `record.created` in UTC as `YYYY-MM-DDTHH:MM:SS.mmmZ`, taking the milliseconds from `created` itself and not from `record.msecs` (plan, "Validation timing").

**Depends on it.** The JSON and text renderings in `EngineJsonFormatter.format`.

**Risk: medium.** Watch the rounding edge: if the seconds and the milliseconds are computed separately, for example `int(created % 1 * 1000)` against a `fromtimestamp` that rounds microseconds, a value like x.9996 can disagree with its own seconds (`.1000`, or a seconds value one too high). Using `fromtimestamp(created, timezone.utc)` and then `microsecond // 1000` keeps both from one value. Expected regex: `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$`. It must be the same string in both renderings (R4 requirement line 53).
</impact>
<impact path="engine/server/api/logging_profiles.py" element="`EngineJsonFormatter` class: new constructor flag, `format()` (lines 184-226) split into payload build + render">
**What changes.** 
- `__init__` gets a format flag. It must default to JSON, because `EngineJsonFormatter()` is constructed with no arguments in `engine/server/api/tests/test_logging_profiles.py:34,141`.
- Line 195 `ts` becomes the record-based helper.
- Everything from line 189 to line 225 stays: classification, `_extract_request_id`, `_extract_fields`, the incoming-likes, access.start, access and service.lifecycle message rewriting, and `traceback`.
- The final `json.dumps(payload, ensure_ascii=True, separators=(",", ":"))` (line 226) stays the JSON branch, byte for byte.
- A new text branch renders: `ts level event [message] [context k=v…] [request_id=…] [traceback]`. `modes` is omitted. For `service.lifecycle` the message token is skipped because the payload has no `message`. CR and LF are escaped in the assembled line.

**Depends on it.** 
- `configure_engine_logging` (line 239).
- The unit tests (which build the formatter directly).
- `engine/watch-engine-logs.sh` (JSON keys `modes`, `level`, `event`, `message`).
- `engine/server/README.md:31` (names the class and its `traceback` key).
- Every Engine log record in production.

**Risk: medium-high.** 
- JSON mode must remain unchanged apart from the `ts` value. Key order today is `ts, level, event, message, modes`, then `request_id`, `context`, `traceback`. Any refactor that rebuilds the dict differently changes the order. Tests do not pin the order, but the R2 contract does.
- The class name says "Json" while it now also emits text. Renaming it would break the unit-test import (line 18) and README.md:31, so keep the name.
- In text mode, `request_id` should not be emitted twice when `context` already carries a `request_id` token taken from the message.
- The JSON branch's `ensure_ascii=True` escaping does not apply to text mode, so non-ASCII passes through raw. Probably fine, but worth stating.
- The traceback in text mode contains newlines and must go through the CR/LF escape. Context values from `_extract_fields` are single tokens already. The incoming-likes context holds a list of dicts, which must be rendered as compact JSON.
</impact>
<impact path="engine/server/api/logging_profiles.py" element="`configure_engine_logging(profile)` (lines 229-241)">
**What changes.** It reads `os.environ.get("LOG_FORMAT")` at call time, passes `normalize_log_format(...)` to the formatter (line 239), and keeps its signature and its return value (the normalised log *mode*, not the format). Root-handler clearing, INFO level and the StreamHandler (stderr) stay unchanged.

**Depends on it.** 
- `engine/server/api/server.py:323` (production).
- `tests/active/test_logging_profiles.py:23-24` (child).
- `tests/active/test_internal_events.py:256-257` (child).
- `tests/active/test_similar.py` (child scripts that call it).
- Indirectly every test that starts a real Engine and parses its log as JSON: `tests/active/conftest.py:110-122` `engine` fixture, `test_similar.py:669` `off_default_engine`, `test_random_cache.py:202-224` `_payloads`/`_has_started`, `test_server_config.py:227-249` `_payloads`.

**Risk: medium.** All of those child processes inherit `os.environ`: `subprocess.run` with no `env` argument, or `{**os.environ, …}`. If `LOG_FORMAT=text` is ever exported in the developer's shell or in CI, they all fail or time out. `_has_started` would never see `service.lifecycle`, and the JSON-only line assertions in test_similar, test_internal_events and test_logging_profiles would fail. The plan accepts this ("existing ones rely on the default"). A cheap hardening the plan could adopt is to pop `LOG_FORMAT` in `tests/active/conftest.py`, but that is not in the plan as written. Do not change the return value, because `server.py:483` logs it as `log_mode_hint`.
</impact>
<impact path="engine/server/api/logging_profiles.py" element="new text renderer / CR-LF escaping helper (private)">
**What changes.** A new private function that turns the payload dict into one line:
- Scalars go through `str()`.
- Lists and dicts go through `json.dumps(..., separators=(",", ":"))`.
- Each `\r` and `\n` becomes the two characters `\r` / `\n`, applied after assembly.
- No prefix is added.

**Depends on it.** The text branch of `EngineJsonFormatter.format`. Its behaviour must match the Client's copy exactly (R2 says "same line format"; a cross-service test guards against drift).

**Risk: medium.** Watch three things. Escaping must also cover a `\r\n` inside the message. A `None` context value, e.g. `user_id: None` in the incoming-likes context, renders as `None` under `str()` but `null` under JSON; pick one and make both services match. Spaces in values are not quoted, which is an accepted limitation.
</impact>
<impact path="engine/server/api/logging_profiles.py" element="`payload_visible_in_mode` (lines 81-90) and `_classify_event`/`_EVENT_RULES` (lines 31-70, 172-181)">
**What changes.** Nothing. These are listed so that the next step can confirm that the `modes` logic and `normalize_log_mode` are untouched (R3: `LOG_FORMAT` is separate from the focused/verbose modes).

**Depends on it.** `engine/watch-engine-logs.sh` (`.modes`) and the unit tests at lines 58-63 and 133-171.

**Risk: low**, unless the payload refactor accidentally drops `modes` from the JSON output.
</impact>
<impact path="engine/server/api/server.py" element="`configure_engine_logging(DEFAULT_RECOMMENDATIONS_LOG_PROFILE)` call (line 323), import (line 84), `log_mode_hint` line (483)">
**What changes.** Nothing in code. The call now also picks up `LOG_FORMAT` from the process environment, which systemd provides through `EnvironmentFile=-.env.bridge` / `Environment=`.

**Depends on it.** Production Engine startup.

**Risk: low.** About 20 lines run between process start and line 323 (arg parsing, signal setup, `faulthandler.register` at 306). Anything logged before line 323 goes through `logging.lastResort` without a timestamp, which is the same as today. A malformed `LOG_FORMAT` must not raise here. Optionally the format could be logged next to `log_mode_hint` (line 483), but the plan does not do this.
</impact>
<impact path="client/backend/server.py" element="imports (lines 5-23): `json`, `datetime`, `traceback`">
**What changes.** `from datetime import datetime` (line 23) is used only at line 128. If the new ts helper uses `datetime.fromtimestamp(..., timezone.utc)`, the import becomes `from datetime import datetime, timezone`; otherwise it becomes unused. `json` is still used widely (line 601 and others). `traceback` is still used at line 722. `os` and `logging` are already imported.

**Depends on it.** The whole module.

**Risk: low.**
</impact>
<impact path="client/backend/server.py" element="`_emit_client_log(level, event, message, context)` (lines 120-136)">
**What changes.** It no longer builds a JSON string. It calls `logging.log(level, message, extra={"client_event": event, "client_context": context})`, with names namespaced to avoid reserved `LogRecord` attributes (`message`, `msg`, `args`, `levelname`…; `logging` raises `KeyError` on a collision in `extra`). The signature stays the same and the docstring should be updated ("structured JSON log line").

**Depends on it.** 16 call sites in the same file, all unchanged:
- `log_message` (line 262).
- `_respond_engine_failure` (line 420).
- incoming likes (line 542).
- the proxy (lines 629, 642, 661, 674, 688, 711, 732).
- the bridge (lines 1075, 1079).
- `main` (lines 1220, 1238).

`tests/active/test_server.py` reads these records through `caplog` (see that entry).

**Risk: HIGH.**
- **(a)** `record.getMessage()` changes from the full JSON payload to only the bare `message`. Every in-process consumer that parsed or searched `getMessage()` for `event` or `context` breaks; see the test_server.py entry.
- **(b)** Message text is passed as `msg` with no `args`, so a `%` in the message is not interpolated. That is safe today, because all messages are literals or `f"Engine {operation} failed"`.
- **(c)** Records now reach any handler, including pytest's caplog, as plain messages. Before `configure_client_logging()` has run (in-process tests, conftest `client_backend`), no formatter is installed. That matches today: there is no `basicConfig` in tests, and lastResort prints only WARNING and above as a bare message.
- **(d)** `context` at line 722 carries a multi-line `traceback` string inside context. In JSON mode it stays a JSON string. In text mode it must be escaped (R5).
</impact>
<impact path="client/backend/server.py" element="new Client formatter class + ts helper + `normalize_log_format` copy + text renderer (new, near `_emit_client_log`)">
**What changes.** A new `logging.Formatter` subclass. It builds a payload in the order `ts`, `level`, `service: "client-backend"`, `event`, `message`, `context`, then the new additive `traceback` when `exc_info` is present. `event` comes from `record.client_event` or the fallback `client.log`; `message` is `record.getMessage()`; `context` comes from `record.client_context` when it is truthy, which keeps today's `if context:` behaviour at line 134. It renders JSON (`ensure_ascii=True, separators=(",", ":")` as at line 136) or text, and duplicates the Engine's ts helper, normaliser and text renderer.

**Depends on it.** `configure_client_logging`, `client/watch-client-logs.sh` (`fromjson?`), and the DEPLOYMENT.md/README runbooks that point at `context.error`.

**Risk: medium.**
- Level names: today the code uses `logging.getLevelName(level)`; the formatter uses `record.levelname`. These are equal for stdlib levels.
- An empty context must still be omitted, because `if context:` drops `{}`. A record with `client_context={}` must not emit `"context":{}`.
- The two copies can drift: the plan's named ceiling.
- The class must be importable without side effects at module import time. `tests/active/conftest.py:41` imports `server` in-process, so nothing may touch the root logger at import.
</impact>
<impact path="client/backend/server.py" element="new `configure_client_logging()`">
**What changes.** A new function, mirroring `configure_engine_logging`:
- `root.handlers.clear()`, `setLevel(INFO)`.
- A `StreamHandler()` (stderr, the same stream `basicConfig` used) with the Client formatter.
- It reads `LOG_FORMAT` at call time.

**Depends on it.** `main()` and the new tests. A test that calls it replaces the pytest process's root handlers, which removes pytest's own capture handlers wired into the root logger, so the test must save and restore them (plan, "Client test seam").

**Risk: medium.** A test that forgets to restore the handlers silently breaks `caplog`-based assertions in later tests in the same session (`test_server.py`, `test_similarity_candidates.py`, `test_random_cache.py:539`, `test_updater_worker.py:137`). Note that `basicConfig` was a no-op when handlers already existed. The explicit clear is a behaviour change if anything had installed handlers before `main()`; nothing does today.
</impact>
<impact path="client/backend/server.py" element="`main()` line 1184 `logging.basicConfig(level=logging.INFO, format=\"%(message)s\")`">
**What changes.** It is replaced by `configure_client_logging()`. Ordering stays: after `parse_trusted_proxies` (1179-1182) and `parse_cors_origins` (1183), and before the signal swap and the bind.

**Depends on it.** Client production startup, `scripts/run-services.sh:161-164`, `tests/run-arch-split-smoke.sh:544` (its client.log is only tailed on failure, not parsed), and the systemd unit from `client/install-client-service.sh:195-197`.

**Risk: low-medium.** The `SystemExit` for a bad `TRUSTED_PROXIES` (line 1182) happens before logging setup and goes to stderr bare; that is unchanged. The `service.start`/`service.stop` records (lines 1220, 1238) now go through the formatter. Their `context` contains an int `port` and an int `pid`, which stay JSON ints in JSON mode.
</impact>
<impact path="client/backend/server.py" element="`ClientBackendHandler.log_message` (lines 258-273)">
**What changes.** No code change. It is still the `client.access` request-end line, and its `ts` is now `record.created` (R6).

**Depends on it.** `BaseHTTPRequestHandler`, which calls it once the response has been sent.

**Risk: low.** `BaseHTTPRequestHandler.log_error` also routes to `log_message`, so error-path lines (for example a 400 from a malformed request line) are also emitted as `client.access` "request finished". That is pre-existing behaviour, noted here only because they now carry UTC timestamps as well.
</impact>
<impact path="tests/active/test_server.py" element="`_error_messages` / `_error_events` (lines 991-1005) and the four tests using them (lines 1008-1019, 1032-1043, 1046-1057, 1073-1082)">
**What changes.** These tests are not in the plan but **will break**. They read `record.getMessage()` from `caplog` and `json.loads` it to get `event` and `context`.
- After the change, `getMessage()` is only `"Engine metadata failed"` or `"engine bridge publish failed"`, so `_error_events` returns `[]`.
- Assertions that will fail: line 1019 (`event == "engine.call"`), lines 1077-1082 (`engine.bridge` and `context.error` containing "Connection refused").
- The sentinel lives only in `context.error` (server.py:420, 1075, 1079), not in the message. So `ENGINE_SENTINEL in caplog.text` (line 1017; caplog's own formatter prints `%(message)s`), the `ENGINE_SENTINEL in message` checks (lines 1018, 1043) and `DROPPED_TEXT in message` (line 1057) also fail.
- The module docstring (lines 94-106) describes "an ERROR record" carrying the sentinel.

**Depends on it.** The `client_server` import from conftest.

**Risk: HIGH, and certain unless addressed.** The fix belongs in this build: rewrite the helpers to read `record.client_event` / `record.client_context`, or to run each record through the new Client formatter (`json.loads(formatter.format(record))`). The second option also exercises the production formatter. The plan's statement "No call site changes" holds for production code, but this test module needs editing.
</impact>
<impact path="engine/server/api/tests/test_logging_profiles.py" element="`EngineJsonFormatter()` constructions (lines 34, 141) and `assertIn(\"ts\", payload)` (line 156)">
**What changes.** No edit is needed if the constructor's format flag defaults to JSON. A natural place for new Engine unit tests: `normalize_log_format` cases, `ts` regex and `created`-based value, text line shape, newline escaping, and the service.lifecycle text line with no message.

**Depends on it.** `logging_profiles` imports at lines 17-21 (adding `normalize_log_format` there if tested).

**Risk: low** if the default is kept. If the flag were made required, both constructions break.
</impact>
<impact path="tests/active/test_logging_profiles.py" element="child running `configure_engine_logging(\"verbose\")` and parsing every stderr line as JSON (lines 20-51)">
**What changes.** Nothing, as long as the default stays JSON. The child inherits the environment (`subprocess.run` with no `env`).

**Depends on it.** `configure_engine_logging` and the env default.

**Risk: low-medium.** It fails if `LOG_FORMAT=text` leaks into the test environment. This is also a candidate home for the new Engine format tests, with the env pinned for the child via `env={**os.environ, "LOG_FORMAT": ...}`: a traceback record escaped to one line in text mode, and a message containing `\n`.
</impact>
<impact path="tests/active/test_internal_events.py" element="`_FAILING_INGEST_CHILD` with `configure_engine_logging(\"verbose\")` (lines 253-308)">
**What changes.** Nothing. It parses every stderr line as JSON and reads `traceback`.

**Depends on it.** The JSON default and the unchanged `traceback` key.

**Risk: low** (environment leak only).
</impact>
<impact path="tests/active/test_similar.py" element="`_json_lines` (561-565), the failing-similar child, `_messages` reading the off-default Engine log (723-732), `off_default_engine` env (669)">
**What changes.** Nothing. These parse Engine JSON lines and the `message`/`traceback` keys. The lines with `{"case": n}` are printed by the child itself and parse as JSON.

**Depends on it.** JSON default, `message` unchanged for `[similar-server]…` records (no rewrite rule applies to them).

**Risk: low** (environment leak only).
</impact>
<impact path="tests/active/test_random_cache.py" element="`_payloads`/`_messages`/`_has_started` (lines 202-224), Engine env at 245 and 710">
**What changes.** Nothing. It reads the Engine log file as JSON and waits for `service.lifecycle` with `context.state == "start"`.

**Depends on it.** JSON default; the `service.lifecycle` payload shape (no `message`, `context` from fields).

**Risk: low-medium.** If `LOG_FORMAT=text` leaked into the environment, `_has_started` would never become true and the fixture would wait out its timeout rather than fail fast. The env at line 245 is built from `os.environ` minus one key.
</impact>
<impact path="tests/active/test_server_config.py" element="`_payloads` (lines 227-249), child env (line 49)">
**What changes.** Nothing. Same `service.lifecycle` start detection as test_random_cache.

**Depends on it.** JSON default.

**Risk: low** (environment leak only).
</impact>
<impact path="tests/active/conftest.py" element="`client_server` in-process import (line 41), `client_backend` fixture (71-91), session `engine` fixture env (110)">
**What changes.** Nothing is required. The import must stay free of side effects: the new Client formatter and configure function are defined at module level but not called. Optionally pop `LOG_FORMAT` from the Engine fixture env to harden it against leaks; that is not in the plan.

**Depends on it.** Every active test that uses `client_server`, `engine` or `client_backend`.

**Risk: low.**
</impact>
<impact path="tests/active/test_similarity_candidates.py" element="caplog `_messages`/`_reopen_warnings`/`_stale_skips` (lines 212-224, 294-397)">
**What changes.** Nothing. These read Engine `record.getMessage()`, which is unaffected because the Engine formatter does not alter records.

**Depends on it.** pytest's caplog handler on the root logger.

**Risk: low**, unless a new test calls `configure_engine_logging` or `configure_client_logging` in-process without restoring root handlers. That would strip pytest's capture handler for later tests in the session.
</impact>
<impact path="tests/active/test_log_format.py" element="new cross-service test module (name to be decided; does not exist yet)">
**What changes.** A new test module covering:
- `ts` regex and `created`-based value for both formatters.
- The `LOG_FORMAT` matrix: unset, `json`, `JSON`, `bogus`, empty → JSON; `text` in any case → text.
- One physical line with a traceback and with a `\n` message.
- No `<N>` prefix.
- The Client: a `_emit_client_log` record and a bare `logging.info` after `configure_client_logging()` both come out in the shared format with `event: client.log`.
- Engine `access.start` → work → `access` with non-decreasing `ts`.
- A drift guard: the same `created` produces the same `ts` string, and the same line shape, from both services.

Engine formatting can run in pytest's interpreter (`logging_profiles` is stdlib-only plus `request_context`, as test_logging_profiles.py:36 notes). The Client formatter is reachable via `client_server` from conftest. Note that both modules are named after their package directories: the Engine one needs `engine/server/api` on `sys.path`. The Engine's `server` module name collides with the Client's `server` already in `sys.modules`, so import `logging_profiles` directly, never the Engine's `server`.

**Depends on it.** Both formatters.

**Risk: medium.** Root-logger handler save/restore is mandatory. Constructing a `LogRecord` and then setting `created` relies on the plan deriving milliseconds from `created`, not `msecs`.
</impact>
<impact path="engine/watch-engine-logs.sh" element="`JQ_FILTER` with `fromjson?` (lines 127-148)">
**What changes.** No code change. In JSON mode the keys are unchanged, so it keeps working, and `ts` simply shows UTC. In text mode `fromjson?` yields nothing and `select(. != null)` drops every line, so the watcher shows **nothing**: a silent, empty view.

**Depends on it.** Operators; DEPLOYMENT.md:123.

**Risk: medium (operator-facing).** This is not a regression of the default, but the DEPLOYMENT.md paragraph must say plainly that the watcher needs `json`. Optionally the help text (`Notes:` lines 24-27) could say so; the plan does not touch the script.
</impact>
<impact path="client/watch-client-logs.sh" element="`jq -R 'fromjson? // {\"raw\": .}'` (lines 97-103), header comment (lines 4-5)">
**What changes.** No code change. In JSON mode the record keys are unchanged. Previously non-JSON lines, bare records, now arrive as structured JSON with `event: client.log` instead of `{"raw": …}`. In text mode every line becomes `{"raw": "<text line>"}`, which is degraded but works.

**Depends on it.** Operators.

**Risk: low.**
</impact>
<impact path="client/install-client-service.sh" element="generated unit `Environment=`/`EnvironmentFile=` (lines 195-197)">
**What changes.** Nothing. `LOG_FORMAT` reaches the Client through the existing `EnvironmentFile=-…/.env.bridge` or a drop-in.

**Depends on it.** `tests/active/test_install_client_service.py`, which compares the generated unit exactly.

**Risk: low**, but do not add an `Environment=LOG_FORMAT=` line here: the exact-match install tests would fail and the plan does not call for it.
</impact>
<impact path="engine/install-engine-service.sh" element="generated unit (lines 128-130)">
**What changes.** Nothing; the same reasoning as the Client unit. `tests/active/test_install_engine_service.py:58` pins the exact unit text.

**Depends on it.** Engine units.

**Risk: low**, provided it is left untouched.
</impact>
<impact path="scripts/run-services.sh" element="`load_bridge_secret` sources `.env.bridge` with `set -a` (lines 96-99); Engine/Client launches (144-164)">
**What changes.** Nothing. A `LOG_FORMAT` in `.env.bridge` is exported to both services here as well. That is consistent with DEPLOYMENT.md's "set it in `.env.bridge`" advice, but it turns text mode on for both services at once, and for prod and dev, which share the file.

**Depends on it.** Local runs; `logs` subcommand `tail -f` (line 244).

**Risk: low.** Worth a sentence in the doc paragraph: `.env.bridge` is shared by the prod and dev units, as DEPLOYMENT.md:528 already says for CORS.
</impact>
<impact path="engine/server/api/server_config.py" element="`_resolve_log_profile_env` / `DEFAULT_RECOMMENDATIONS_LOG_PROFILE` (lines 12-15, 516-518)">
**What changes.** Nothing. This is the import-time env read that the plan explicitly does not copy for `LOG_FORMAT`.

**Depends on it.** `server.py:80, 323`.

**Risk: none.** Listed so that nobody adds `LOG_FORMAT` here. `test_server_config.py` imports `server_config` in-process, and an import-time read there would be cached for the session.
</impact>
<impact path="client/backend/lib/http_utils.py" element="module (uses `datetime.now(timezone.utc)` at line 112 for the rate limiter)">
**What changes.** Nothing. This is not logging; the hit only came from searching for `datetime`.

**Depends on it.** `RateLimiter`.

**Risk: none.** Listed to record that no Client lib module logs (grep of `client/backend` for `logging.`/`logger` finds only `server.py`). So "third-party/library records" in the Client are in practice only stdlib ones, and `client.log` fallback lines should be rare.
</impact>
</impacts>


## Documentation to update

- [ ] `DEPLOYMENT.md` - Add one `LOG_FORMAT` paragraph after the `RANDOM_CACHE_REFRESH_INTERVAL_MINUTES` paragraph (line 114) in the service-environment block (lines 105-114), in the same one-paragraph style. Points to cover:
- Values: `json` (default) and `text`, case-insensitive, whitespace ignored. Unset, empty or unknown values select `json` and never stop startup.
- Both the Engine and the Client backend read it at logging setup.
- How to set it: through `.env.bridge` (shared by the prod and dev units and exported by `scripts/run-services.sh`) or an `Environment=` drop-in.
- `engine/watch-engine-logs.sh` shows nothing in text mode, and `client/watch-client-logs.sh` shows `{"raw":…}`.
- `ts` is UTC `YYYY-MM-DDTHH:MM:SS.mmmZ` taken at record creation.
- Text lines escape newlines, so a traceback is one line.

Also check Triage rows 203 (`context.error` of `engine.call`/`engine.bridge`) and 204 ("the JSON log record's `traceback` key"), and line 301. They stay correct in JSON mode, but each could get a short "(in `LOG_FORMAT=text`, the `error=` token / the escaped traceback at the end of the line)" note. Optional; the operator may prefer to say once in the new paragraph that the runbooks assume `json`.
- [ ] `engine/server/README.md` - Line 31 says `EngineJsonFormatter` adds a `traceback` key. That is still true in JSON mode. Optionally add that in `LOG_FORMAT=text` the traceback ends the line, newline-escaped. Otherwise no change, as long as the class keeps its name.
- [ ] `client/README.md` - Lines 31, 32 and 35 describe ERROR `engine.call` / `engine.bridge` records with `context.error`, and INFO `engine.proxy`. These stay accurate in JSON mode. Optionally add a pointer to DEPLOYMENT.md for `LOG_FORMAT` next to the `TRUSTED_PROXIES` env note (line 68), since that section lists the Client's env settings. Also uncertain: whether the README should mention that bare/library records now appear as `client.log` events and that exception records carry an additive `traceback` key.
- [ ] `docs/project/issues/19-timestamped-request-logs.md` - Per the tracker conventions: on delivery, set `Status: enhancement, complete` and move the file to `docs/project/issues/archive/`. Note that the delivered default is JSON, not the issue's "plain text default", by operator decision (recorded in the plan record). The `## Comments` section is the place to say so.
- [ ] `docs/project/issues/plan.md` - The triage note at lines 114-117 ("19 is mostly delivered … uses a local offset, not UTC … shrink it to 'UTC, plus an optional plain-text mode'") and the lane 4c row (line 91) become stale once 19 lands. Update or strike them when the issue is archived. This is bookkeeping, not product documentation.

## Implementation plan

## Draft implementation — issue 19, timestamped logs (UTC `ts`, `LOG_FORMAT` json|text, Client root formatter)

I read these files before drafting: `engine/server/api/logging_profiles.py` (whole file), `client/backend/server.py` (imports 1-23, `_emit_client_log` 120-136, `log_message` 258-273, `main` 1175-1252, the `"error"` context sites 420/722/1075/1079), `tests/active/test_server.py` (docstring 94-106, helpers and tests 991-1082, sentinel constants 937-942), `tests/active/conftest.py`, `tests/active/test_logging_profiles.py`, `engine/server/api/tests/test_logging_profiles.py`, `engine/server/api/handlers/similar.py:340-360` and `DEPLOYMENT.md:105-114`.

### What has to be tested

| # | Behaviour | Requirement | Where |
|---|---|---|---|
| T1 | `ts` matches `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$` in both services and both formats | R1, Validation 1 | new `tests/active/test_log_format.py` |
| T2 | A record whose `created` is set to `1741091696.789` renders `2025-03-04T12:34:56.789Z` (formatting time is ignored). The edge `1741091696.9999996` renders `2025-03-04T12:34:57.000Z`, with seconds and milliseconds consistent | R1, R6, Validation 3 | same |
| T3 | `LOG_FORMAT` unset, `json`, `JSON`, `bogus` or `""` gives JSON lines; `text`, `TEXT` or ` Text ` gives text lines. Engine runs in a child with a pinned env; Client runs in-process with monkeypatch | R3, Validation 4 | same |
| T4 | Every record is one physical line in both modes, including a `logging.exception` record and a message containing `\n`. In text mode the traceback is at the end of the line as `\n`-escaped text. No line starts with `<` | R5, Validation 4 | same |
| T5 | Text shape is `ts LEVEL event message k=v… [request_id=…] [traceback]`. An Engine `service.lifecycle` line has no message token. An Engine access line carries "request started" / "request finished" | R4 | same |
| T6 | After `configure_client_logging()` in the Client, a `_emit_client_log` record and a bare `logging.info` both come out in the shared format. The bare one has `event == "client.log"`. JSON key order is `ts, level, service, event, message[, context]` | R2, Validation 5 | same |
| T7 | Drift guard: `_format_ts` and `_render_text` give identical strings in the Engine (child) and the Client (in-process) for the same `created` and the same payload | R2 | same |
| T8 | Engine live request: in the session Engine's log, the slice from the `access.start` of a marked `POST /recommendations` to its `access` has non-decreasing `ts` and at least one `recommendations.*` work line | R6, Validation 2 | same |
| T9 | The existing JSON consumers stay green: the four Engine JSON-parsing modules are unchanged, and `test_server.py`'s Client ERROR-record tests are rewired to the new formatter | R3, Validation 6 | `tests/active/test_server.py` |

### Module map

| File | Change |
|---|---|
| `engine/server/api/logging_profiles.py` | imports; `SUPPORTED_LOG_FORMATS`; `normalize_log_format`; `_TEXT_ESCAPES`, `_format_ts`, `_text_value`, `_render_text`; `EngineJsonFormatter.__init__(log_format="json")`; `ts` comes from the record; text branch; `configure_engine_logging` reads `LOG_FORMAT` |
| `client/backend/server.py` | import `timezone`; copies of the four helpers and the constant; `ClientLogFormatter`; `configure_client_logging()`; `_emit_client_log` becomes a `logging.log(..., extra=…)` call; `main()` calls `configure_client_logging()` in place of `basicConfig` |
| `tests/active/test_server.py` | `_error_messages` renders each record through `ClientLogFormatter`; caplog's handler gets that formatter in the one test that reads `caplog.text`; the docstring wording is adjusted |
| `tests/active/test_log_format.py` | new module, T1-T8 |
| `DEPLOYMENT.md`, `engine/server/README.md`, `client/README.md`, issue 19, `docs/project/issues/plan.md` | the doc list (see the Docs section) |

No other production file changes. `engine/server/api/server.py`, both watch scripts, both install scripts, `scripts/run-services.sh` and `server_config.py` are untouched, as the impact inventory says.

### `engine/server/api/logging_profiles.py`

Imports (lines 5-12). `os` is added. `datetime` gains `timezone`. The module still imports only the stdlib and `request_context`.

```python
import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
```

The constant goes next to `SUPPORTED_LOG_MODES` (line 15):

```python
SUPPORTED_LOG_MODES = ("focused", "verbose")
SUPPORTED_LOG_FORMATS = ("json", "text")
```

And the escape table after `_LEADING_BLOCKS_RE` (line 19):

```python
# Text lines escape CR/LF so journald stores each record as one entry.
_TEXT_ESCAPES = str.maketrans({"\r": "\\r", "\n": "\\n"})
```

`normalize_log_format` goes directly after `normalize_log_mode`. It has the same fail-safe shape and never raises for `str | None`.

```python
def normalize_log_format(value: str | None) -> str:
    """Normalize ``LOG_FORMAT`` values and fail safely to ``json``."""
    raw = (value or "").strip().lower()
    if raw in SUPPORTED_LOG_FORMATS:
        return raw
    return "json"
```

The ts and text helpers go after `_classify_event`, before the class. Invariant for `_format_ts`: the seconds and the milliseconds come from one `datetime`, so they can never disagree. `fromtimestamp` rounds to the microsecond, and `// 1000` truncates to milliseconds. `record.msecs` is not used.

```python
def _format_ts(record: logging.LogRecord) -> str:
    """Render the record's creation time as UTC ``YYYY-MM-DDTHH:MM:SS.mmmZ``."""
    stamp = datetime.fromtimestamp(record.created, tz=timezone.utc)
    return f"{stamp.strftime('%Y-%m-%dT%H:%M:%S')}.{stamp.microsecond // 1000:03d}Z"


def _text_value(value: Any) -> str:
    """Render one context value as a single text token."""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _render_text(payload: dict[str, Any]) -> str:
    """Render a payload as one ``ts LEVEL event message k=v…`` line with CR/LF escaped."""
    parts = [payload["ts"], payload["level"], payload["event"]]
    if "message" in payload:
        parts.append(str(payload["message"]))
    context = payload.get("context") or {}
    parts.extend(f"{key}={_text_value(value)}" for key, value in context.items())
    request_id = payload.get("request_id")
    if request_id and "request_id" not in context:
        parts.append(f"request_id={request_id}")
    if "traceback" in payload:
        parts.append(payload["traceback"])
    return " ".join(parts).translate(_TEXT_ESCAPES)
```

Decisions in `_render_text`:
- **One rule for non-string values.** Every value that is not a string goes through compact JSON. A list or dict stays one token (the incoming-likes context), `None` is written `null` and a bool `true`. This answers the impact inventory's question about `None` rendering as `None` or `null`, the same way in both services.
- **`modes` and `service` are not text tokens.** R4 fixes the shape, and `modes` is only filter metadata for the JSON watcher.
- **`request_id` is written once.** It is skipped when the context already carries a `request_id` key.
- **Escaping runs last, over the whole assembled line,** so the message, the context values (including the Client's `context.traceback` at server.py:722) and the traceback are all covered, `\r\n` included.
- **Non-ASCII.** Text mode does not apply `ensure_ascii`, so non-ASCII characters pass through as they are. That is a stated limitation and harmless to journald.

`EngineJsonFormatter` (lines 184-226) keeps its name, which the unit-test import and README.md:31 depend on. The payload build is untouched except for line 195. The JSON return is the same expression as before.

```python
class EngineJsonFormatter(logging.Formatter):
    """Render engine log records as JSON objects with mode tags, or as text lines."""

    def __init__(self, log_format: str | None = "json") -> None:
        """Select the rendering: ``json`` (default) or ``text``; other values mean ``json``."""
        super().__init__()
        self.log_format = normalize_log_format(log_format)

    def format(self, record: logging.LogRecord) -> str:
        """Format a log record as one JSON or text line."""
        message = record.getMessage()
        event, modes = _classify_event(message, record.levelno)
        request_id = _extract_request_id(record, message)
        fields = _extract_fields(message)

        payload: dict[str, Any] = {
            "ts": _format_ts(record),
            "level": record.levelname,
            "event": event,
            "message": message,
            "modes": modes,
        }
        # … lines 201-225 unchanged (request_id, per-event rewriting, traceback) …
        if self.log_format == "text":
            return _render_text(payload)
        return json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
```

Invariants of the class:
- **JSON key order is unchanged:** `ts, level, event, message, modes`, then `request_id`, `context`, `traceback`.
- **`EngineJsonFormatter()` with no argument is JSON,** so `engine/server/api/tests/test_logging_profiles.py:34,141` needs no edit.
- **Text messages match JSON by construction.** Text mode renders the same payload after the rewriting, so its message is the JSON message.

`configure_engine_logging` (lines 229-241): one changed line plus the docstring. The signature and the return value (the log mode) stay the same, because `server.py:483` logs that value.

```python
def configure_engine_logging(profile: str) -> str:
    """Configure root logger with the ``LOG_FORMAT`` formatter and return normalized mode hint."""
    …
    handler.setFormatter(EngineJsonFormatter(os.environ.get("LOG_FORMAT")))
    …
```

`LOG_FORMAT` is read when this function is called, never at import. `server_config.py` is not touched.

### `client/backend/server.py`

Line 23 becomes `from datetime import datetime, timezone`. `datetime` is still used by the ts helper. `os`, `json`, `logging` and `traceback` are already imported.

Next to `_resolve_mode` / `_emit_client_log` (before line 120) go the constant, the escape table, `normalize_log_format`, `_format_ts`, `_text_value` and `_render_text`. Their bodies are byte-identical to the Engine's, and they are preceded by this marker:

```python
# rat-tail: LOG_FORMAT, _format_ts, _text_value and _render_text mirror engine/server/api/logging_profiles.py (no shared module: the two services import from different roots); tests/active/test_log_format.py checks both render alike.
SUPPORTED_LOG_FORMATS = ("json", "text")
_TEXT_ESCAPES = str.maketrans({"\r": "\\r", "\n": "\\n"})
CLIENT_LOG_SERVICE = "client-backend"
CLIENT_LOG_FALLBACK_EVENT = "client.log"
```

The formatter:

```python
class ClientLogFormatter(logging.Formatter):
    """Render Client records in the shared log format, JSON or text."""

    def __init__(self, log_format: str | None = "json") -> None:
        """Select the rendering: ``json`` (default) or ``text``; other values mean ``json``."""
        super().__init__()
        self.log_format = normalize_log_format(log_format)

    def format(self, record: logging.LogRecord) -> str:
        """Format one record; ``_emit_client_log`` records carry ``client_event``/``client_context``."""
        payload: dict[str, Any] = {
            "ts": _format_ts(record),
            "level": record.levelname,
            "service": CLIENT_LOG_SERVICE,
            "event": getattr(record, "client_event", None) or CLIENT_LOG_FALLBACK_EVENT,
            "message": record.getMessage(),
        }
        context = getattr(record, "client_context", None)
        if context:
            payload["context"] = context
        # Additive to the Client's keys: without it an exception logged through the root logger is lost.
        if record.exc_info:
            payload["traceback"] = self.formatException(record.exc_info)
        if self.log_format == "text":
            return _render_text(payload)
        return json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
```

Invariants of `ClientLogFormatter`:
- **Same keys, same order as today:** `ts, level, service, event, message[, context]`.
- **An empty or `None` context is omitted,** which is today's `if context:`.
- **`level`.** `record.levelname` equals `logging.getLevelName(level)` for stdlib levels.
- **JSON separators and `ensure_ascii` are as at line 136.**
- **No side effects at import.** Defining the class touches nothing, which conftest's in-process import (conftest.py:41) requires.

`_emit_client_log` keeps its signature and its 16 call sites:

```python
def _emit_client_log(
    level: int,
    event: str,
    message: str,
    context: dict[str, Any] | None = None,
) -> None:
    """Log one Client record; ``ClientLogFormatter`` renders it with its event and context."""
    logging.log(level, message, extra={"client_event": event, "client_context": context})
```

Notes on `_emit_client_log`:
- **`extra` names.** `client_event` and `client_context` are not reserved `LogRecord` attributes, so `logging` raises no `KeyError`.
- **No `%` interpolation.** No `args` are passed, so `getMessage()` returns `message` unchanged even if it contains `%`.
- **The implicit `basicConfig` is kept.** Module-level `logging.log` keeps today's implicit-`basicConfig`-when-no-handlers behaviour; nothing changes there.

`configure_client_logging` sits directly after the formatter and mirrors `configure_engine_logging`:

```python
def configure_client_logging() -> None:
    """Install ``ClientLogFormatter`` on the root logger, format from ``LOG_FORMAT``."""
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(logging.INFO)

    handler = logging.StreamHandler()
    handler.setLevel(logging.INFO)
    handler.setFormatter(ClientLogFormatter(os.environ.get("LOG_FORMAT")))
    root_logger.addHandler(handler)
```

The `StreamHandler()` default is stderr, the same stream `basicConfig` used, so the systemd units and `journalctl -o cat` pipelines are unchanged.

`main()` line 1184: `logging.basicConfig(level=logging.INFO, format="%(message)s")` becomes `configure_client_logging()`. It stays in the same position: after `parse_trusted_proxies` / `parse_cors_origins`, and before the signal swap and the bind. `log_message` (258-273) needs no code change.

### `tests/active/test_server.py`

These tests fail as the code stands, so they are fixed here.

Lines 991-992. The rest of `_error_events` is unchanged, because it now parses real JSON lines:

```python
_CLIENT_FORMATTER = client_server.ClientLogFormatter()


def _error_messages(caplog):
    """The ERROR records, each rendered as the Client's production JSON line."""
    return [_CLIENT_FORMATTER.format(record) for record in caplog.records if record.levelno >= logging.ERROR]
```

In `test_client_likes_502_is_fixed_text_and_engine_error_is_logged` (line 1008), add `caplog.handler.setFormatter(_CLIENT_FORMATTER)` right after `caplog.set_level(logging.ERROR)`. Then `caplog.text` at line 1017 is the production-rendered lines, and the sentinel in `context.error` is found again. Lines 1018, 1019, 1043, 1057 and 1077-1082 pass unchanged. `ENGINE_SENTINEL` and `DROPPED_TEXT` are plain ASCII with no quote or backslash, so `json.dumps` leaves them intact.

Docstring line 100: "the sentinel is in an ERROR record" becomes "the sentinel is in an ERROR record's `context.error`, as the Client's formatter renders it". Lines 102 and 105-106 already say `context.error` or are still true.

### `tests/active/test_log_format.py` (new)

The module docstring states the claims T1-T8 in the house style of the active tests. Seams:
- **Engine side: a child process.** It runs `[sys.executable, "-c", _ENGINE_CHILD, <args>]` with `cwd=API_DIR`, as `test_logging_profiles.py` does. The env is `{k: v for k, v in os.environ.items() if k != "LOG_FORMAT"}`, plus `LOG_FORMAT` when the case sets one. Using a child keeps the Engine's `server`/`logging_profiles` out of the pytest process, where `server` is already the Client module.
- **Client side: in-process,** through `client_server` from conftest.

The Engine child prints log records to stderr through `configure_engine_logging("verbose")`. In order: `[probe] plain`, `[probe] two\nlines`, `logging.exception("[probe] failed")` for a `ValueError("sentinel-log-format")`, `[access.start] ip=127.0.0.1 method=GET url=http://x/a`, `[service] lifecycle state=start component=engine run_id=r pid=1`. On stdout it prints JSON with three items:
- `ts`: `_format_ts` of a `LogRecord` whose `created` was set from argv.
- `fixed`: `EngineJsonFormatter(fmt).format` of that record.
- `text`: `_render_text(json.loads(argv payload))`.

The Client context manager is the only place that replaces root handlers. It saves and restores them inside the test body, which is the call phase. A fixture would capture the setup phase's pytest handlers and restore stale ones.

```python
@contextmanager
def _client_logging(monkeypatch, value):
    """Run configure_client_logging under LOG_FORMAT=value; yield the stream it writes to."""
    root = logging.getLogger()
    saved_handlers, saved_level = root.handlers[:], root.level
    if value is None:
        monkeypatch.delenv("LOG_FORMAT", raising=False)
    else:
        monkeypatch.setenv("LOG_FORMAT", value)
    try:
        client_server.configure_client_logging()
        stream = io.StringIO()
        root.handlers[0].setStream(stream)
        yield stream
    finally:
        root.handlers[:] = saved_handlers
        root.setLevel(saved_level)
```

Tests:
- `test_log_format_selects_json_or_text[engine|client × None, "json", "JSON", "bogus", "", "text", "TEXT", " Text "]` covers T1, T3, T4 and T6. JSON cases: every line passes `json.loads`, `ts` matches `TS_RE`, and the Client's keys come in order `["ts", "level", "service", "event", "message", …]`. Text cases: every line matches `^TS ` followed by the level. No line starts with `<`. The traceback/newline records are exactly one line each, and the text line contains `\\n` and ends with `ValueError: sentinel-log-format`. The Client emits `_emit_client_log(ERROR, "engine.call", "Engine metadata failed", {"error": "x\ny"})`, `logging.info("bare")` and a `logging.exception` record.
- `test_ts_is_record_creation_time_in_utc` covers T2: `created = 1741091696.789` gives `2025-03-04T12:34:56.789Z`, and `1741091696.9999996` gives `2025-03-04T12:34:57.000Z`. Both services are checked, and also a `created` an hour in the past, to show it is not the formatting time.
- `test_text_line_shape` covers T5. Engine: `… INFO access.start request started ip=127.0.0.1 method=GET url=http://x/a`, and the lifecycle line goes `… INFO service.lifecycle state=start …` with no message token. Client: `… INFO client.access request finished ip=… status=200 bytes=-`.
- `test_engine_and_client_render_alike` covers T7. One fixed `created` and one payload `{"ts": …, "level": "INFO", "event": "e", "message": "m\nn", "context": {"a": 1, "b": None, "c": [1, {"d": "x"}], "request_id": "r"}, "request_id": "r", "traceback": "T\nU"}` must give equal strings from the Engine child and from `client_server._render_text` / `_format_ts`.
- `test_engine_request_lines_are_ordered_by_ts(engine)` covers T8. It sends `POST /recommendations?limit=5&user_id=log-order-<uuid4 hex>` with `body={}`, then reads `engine.db_path` (the fixture's log path) as JSON lines. The slice runs from the `access.start` whose `context.url` contains the marker to the `access` that contains it. Inside the slice it keeps the `access.start`, the `access` and the `recommendations.*` records. It asserts at least one work record and non-decreasing `ts`. The session Engine runs with `--no-random-cache-refresh` and this pytest process sends one request at a time, so no other thread writes inside the slice. If the Engine refuses `user_id` on that route, the test-writing step should mark the URL through the `Host` header instead (`_get_full_url` builds it from `Host`).

### Docs (the settled list)

- **`DEPLOYMENT.md`, after line 114,** as one paragraph: "Both the Engine and the Client backend read an optional `LOG_FORMAT` when they set up logging: `json` (the default) or `text`, case-insensitive with surrounding whitespace ignored; an unset, empty or unknown value selects `json` and never stops startup. Set it in `.env.bridge`, which is shared by the prod and dev units and exported to both services by `scripts/run-services.sh`, or with an `Environment=` drop-in for one unit. Every record's `ts` is UTC `YYYY-MM-DDTHH:MM:SS.mmmZ`, taken when the record was created, and is the timestamp to order by, not the journal's. `text` writes `ts LEVEL event message key=value…` lines with newlines escaped as `\n`, so a traceback stays on its record's one line; it is for reading by eye. `engine/watch-engine-logs.sh` shows nothing in text mode, `client/watch-client-logs.sh` shows each line as `{"raw": …}`, and the Triage recipes that name JSON keys (`traceback`, `context.error`) assume `json`."
- **`engine/server/README.md:31`:** append "In `LOG_FORMAT=text` the traceback ends the record's line, newline-escaped (see DEPLOYMENT.md)."
- **`client/README.md`, near line 68:** "Logging: `LOG_FORMAT` (`json` default, `text`), see DEPLOYMENT.md. Records not logged through `_emit_client_log` appear as event `client.log`, and a record with an exception carries a `traceback` key."
- **`docs/project/issues/19-timestamped-request-logs.md`:** on delivery, set `Status: enhancement, complete`, move the file to `archive/`, and add a `## Comments` note that the default is JSON, not the issue's plain text, by operator decision.
- **`docs/project/issues/plan.md`:** strike or update the triage note at lines 114-117 and the lane 4c row (line 91).

### Check against the plan and requirements (pass 1, converged)

- **R1** is met by `_format_ts`, which uses `created` and one `datetime`, gives `Z` and three-digit milliseconds, and stays under the `ts` key.
- **R2** is met by the same helpers, stdlib `levelname`, leading `ts, level` in both payloads, and a Client root formatter that catches bare and library records. The Client keys are kept.
- **R3** is met by `normalize_log_format` (fail-safe), reading at setup time in both services, unchanged JSON keys and rewriting, untouched `modes`, and the DEPLOYMENT paragraph.
- **R4** is met by the shared `_render_text`, which renders the same payload so its message matches JSON, with `ts` identical to the JSON value.
- **R5** is met by the CR/LF escape over the whole line, the traceback on the same line, no prefix, and the same stderr stream.
- **R6** holds because `ts` comes from `created` (T8).
- **The plan.** The plan's "no call site changes" holds for production code. The `test_server.py` rewire is the only edit outside the plan, and the impact inventory requires it.
- **Named simplifications.** These are stated as limitations, not hidden:
  - Two copies of the helpers, guarded by T7.
  - Unquoted text tokens.
  - Raw non-ASCII in text mode.
  - The leak of an exported `LOG_FORMAT=text` into the Engine child tests. Not hardened, per the plan; popping it in conftest is the cheap upgrade if it ever bites.

### Phases

#### Phase 1 - Engine ts from record creation time [code]

**Files touched.** engine/server/api/logging_profiles.py (EDITED), tests/active/test_log_format.py (NEW)

**Checkpoint.** Seam for C1: the Engine child-process harness from tests/active/test_logging_profiles.py, i.e. `subprocess.run([sys.executable, "-c", _ENGINE_CHILD, …], cwd=API_DIR)` with `LOG_FORMAT` removed from the env. The child calls `configure_engine_logging("verbose")` and logs records to stderr. On stdout it prints the `_format_ts` and `EngineJsonFormatter().format` of a `LogRecord` whose `created` comes from argv. Assertions: every stderr line parses as JSON and its `ts` matches `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$`. created=1741091696.789 gives `2025-03-04T12:34:56.789Z` from both `_format_ts` and the formatted JSON's `ts`. created=1741091696.9999996 gives `2025-03-04T12:34:57.000Z`. A created one hour in the past renders that hour, not the formatting time. Seam for C2: the session `engine` fixture in conftest.py, whose log is read through `engine.db_path` as test_similar.py's `_messages` does. The test sends `POST /recommendations?limit=5&user_id=log-order-<uuid4 hex>` with `body={}`. If the route refuses `user_id`, the marker goes in through the `Host` header instead. The test parses the log's JSON lines, cuts the slice from the `access.start` whose `context.url` contains the marker to the `access` containing it, keeps the access.start, the access and the `recommendations.*` records, and asserts at least one work record and non-decreasing `ts`.

**Intent.** In engine/server/api/logging_profiles.py, EngineJsonFormatter takes every record's `ts` from `_format_ts(record)`, which renders `record.created` in UTC as `YYYY-MM-DDTHH:MM:SS.mmmZ`, so the Engine's `ts` follows the order of the log calls rather than the time of formatting.

- C1 - An Engine record's `ts` is its `record.created` rendered in UTC as `YYYY-MM-DDTHH:MM:SS.mmmZ`.
- C2 - Within one live Engine request, the `ts` values from its `access.start` to its `access` never decrease.

**Outcome.** ### `engine/server/api/logging_profiles.py`
- Added the module-level helper `_format_ts(record)`. It renders `record.created` in UTC as `YYYY-MM-DDTHH:MM:SS.mmmZ` using `datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(timespec="milliseconds")`, with the `+00:00` suffix replaced by `Z`.
- It deliberately does not read `record.msecs`, because `msecs` is not updated when `created` is set after the record is built.
- I observed the rounding in a probe rather than assuming it. `fromtimestamp` rounds to the microsecond before `isoformat` cuts to milliseconds: `1741091696.789` came out as `2025-03-04T12:34:56.789+00:00` and `1741091696.9999996` as `2025-03-04T12:34:57.000+00:00`.
- `EngineJsonFormatter.format` now sets `"ts": _format_ts(record)`. Before, it used `datetime.now().astimezone().isoformat(...)`, which gave local time at the moment of formatting. Now the stamp is the time the log call happened, which is what keeps it in order across one request.
- The import changed from `from datetime import datetime` to `from datetime import datetime, timezone`.

### `tests/active/test_log_format.py`
Not created. The phase lists it as NEW, but this step is production code only. It looks like the permanent home for the checkpoint once it is moved out of `tests/tmp/`, and nothing in this phase needs it to exist.

### `tests/tmp/probe_fromtimestamp.py`
This was my throwaway probe for the rounding check. I have no delete tool, so I emptied the file instead; it now collects no tests. It can be removed.

**Beyond the files named.** tests/tmp/probe_fromtimestamp.py: the throwaway probe for the rounding check. It is now an empty file because I couldn't delete it, and it can be removed.

#### Phase 2 - Engine LOG_FORMAT text rendering [code]

**Files touched.** engine/server/api/logging_profiles.py (EDITED), tests/active/test_log_format.py (EDITED)

**Checkpoint.** Seam: the same Engine child-process harness (cwd=API_DIR; env without `LOG_FORMAT`, plus `LOG_FORMAT` set when the case has a value), parametrized over None, "json", "JSON", "bogus", "", "text", "TEXT", " Text ". The child calls `configure_engine_logging("verbose")` and logs, in order: `[probe] plain`, `[probe] two\nlines`, a `logging.exception("[probe] failed")` for `ValueError("sentinel-log-format")`, `[access.start] ip=127.0.0.1 method=GET url=http://x/a`, and `[service] lifecycle state=start component=engine run_id=r pid=1`. C1: the JSON cases give stderr lines that all parse with `json.loads`; the text cases give lines matching `^<TS_RE> (INFO|ERROR) ` and none parse as a JSON object. C2, in text mode: stderr has exactly five lines. The multiline and exception records each sit on one line, contain a literal `\n` and, for the exception record, end with `ValueError: sentinel-log-format`. The access.start line is `<ts> INFO access.start request started ip=127.0.0.1 method=GET url=http://x/a`. The lifecycle line goes `<ts> INFO service.lifecycle state=start` with no message token. No line starts with `<`.

**Intent.** configure_engine_logging reads `LOG_FORMAT` when it runs and, for `text`, has EngineJsonFormatter render each record's payload through `_render_text` as one CR/LF-escaped `ts LEVEL event message k=v…` line, while every other value keeps today's JSON.

- C1 - An Engine `LOG_FORMAT` of text in any case or surrounding whitespace selects text lines, and an unset, empty, `json` or unknown value selects JSON lines.
- C2 - An Engine text record is one physical line shaped `ts LEVEL event [message] k=v… [request_id=…] [traceback]` with CR and LF written as `\r` and `\n`.

**Outcome.** ### `engine/server/api/logging_profiles.py`
- Imports: added `os`. The module still imports only the stdlib and `request_context`.
- Added `SUPPORTED_LOG_FORMATS = ("json", "text")` next to `SUPPORTED_LOG_MODES`. Added `_TEXT_ESCAPES`, a `str.maketrans` table that writes CR as `\r` and LF as `\n`, after `_LEADING_BLOCKS_RE`.
- New public `normalize_log_format(value)` directly after `normalize_log_mode`, with the same fail-safe shape: it strips and lowercases the value and returns it if it is in `SUPPORTED_LOG_FORMATS`. Anything else, including `None`, `""` and `bogus`, gives `"json"`. It never raises.
- New `_text_value(value)`: a string is returned as it is, and any other value becomes compact JSON (`ensure_ascii=False`, `default=str`), so a list or dict stays a single token and `None` is written as `null`.
- New `_render_text(payload)`: builds `ts LEVEL event`, then the message if the payload has one, then each context entry as `k=v`, then `request_id=…` (skipped if the context already has a `request_id` key), then the traceback. Everything is joined with single spaces, and CR/LF are escaped over the whole line at the end. `modes` is not written.
- `EngineJsonFormatter`: new `__init__(self, log_format="json")`, which stores `normalize_log_format(log_format)`. `format` builds the payload exactly as before. When the format is `text` it returns `_render_text(payload)`; otherwise it returns the same `json.dumps` expression as before, so JSON key order and values are unchanged. `EngineJsonFormatter()` with no argument still gives JSON, so the existing unit-test callers need no change. The class docstring now mentions text lines.
- `configure_engine_logging`: installs `EngineJsonFormatter(os.environ.get("LOG_FORMAT"))`, so the variable is read when the function is called, not at import. The signature and return value (the normalised log mode) are unchanged; only the docstring changed.

### `tests/active/test_log_format.py`
Not touched. The file does not exist in the tree, and this phase's checkpoint lives at `tests/tmp/test_19_timestamped_request_logs_phase2.py`. No production change needed it.

#### Phase 3 - Client root formatter, JSON [code]

**Files touched.** client/backend/server.py (EDITED), tests/active/test_server.py (EDITED), tests/active/test_log_format.py (EDITED)

**Checkpoint.** Seam: in-process through conftest's `client_server` import. A `_client_logging(monkeypatch, value)` context manager is used inside the test body. It saves the root handlers and level, sets or deletes `LOG_FORMAT`, calls `client_server.configure_client_logging()`, swaps `root.handlers[0]` to an `io.StringIO` stream, and restores everything in `finally`. With `LOG_FORMAT` unset, the test calls `client_server._emit_client_log(logging.ERROR, "engine.call", "Engine metadata failed", {"error": "x\ny"})`, then a `logging.exception` record, then `logging.info("bare")`. C1: the emitted line's keys are exactly `["ts", "level", "service", "event", "message", "context"]` in order, with `service == "client-backend"`, `event == "engine.call"`, `context == {"error": "x\ny"}` and `ts` matching TS_RE. The exception record carries a `traceback` key. C2: the bare record parses with keys `ts, level, service, event, message`, `event == "client.log"` and `message == "bare"`. The full suite also covers the rewired ERROR-record tests in tests/active/test_server.py (`_error_messages` renders through `ClientLogFormatter`, and caplog's handler gets that formatter in the `caplog.text` test), which must stay green.

**Intent.** In client/backend/server.py, configure_client_logging installs ClientLogFormatter on the root logger, which `main()` now calls in place of `basicConfig`, and `_emit_client_log` hands it event and context as `client_event`/`client_context` record attributes instead of building JSON by hand, so every Client record leaves through one formatter.

- C1 - An `_emit_client_log` record renders as a JSON line whose keys run `ts, level, service, event, message[, context]` with a UTC `ts`.
- C2 - A bare root-logger record renders in the same JSON shape with event `client.log`.

**Outcome.** ### `client/backend/server.py`
- The datetime import is now `from datetime import datetime, timezone`.
- New `_format_ts(record)`, a copy of the Engine's. It renders `record.created` in UTC as `YYYY-MM-DDTHH:MM:SS.mmmZ`. A `rat-tail:` comment says it mirrors `engine/server/api/logging_profiles.py` because the two services import from different roots, and that a drift guard is the upgrade (planned for phase 4).
- New `ClientLogFormatter(logging.Formatter)`. Its `format` builds the payload in the order `ts, level, service ("client-backend"), event, message`.
  - `event` is the record's `client_event`, or `client.log` when the record has none.
  - `message` is `record.getMessage()`.
  - `context` (the record's `client_context`) is added only when it is not empty, the same rule as the old `if context:`.
  - A record with `exc_info` also gets a `traceback` key, rendered by `formatException`.
  - Output is `json.dumps(..., ensure_ascii=True, separators=(",", ":"))`, the same call as before.
  - JSON only for now. `LOG_FORMAT` handling and text rendering are left to phase 4.
- New `configure_client_logging()`. It clears the root handlers, sets the level to INFO, and adds one INFO `StreamHandler()` (stderr, the same stream `basicConfig` used) carrying `ClientLogFormatter()`.
- `_emit_client_log` keeps its signature and all its call sites. Its body is now `logging.log(level, message, extra={"client_event": event, "client_context": context})` instead of building the JSON string by hand.
- `main()` calls `configure_client_logging()` in place of `logging.basicConfig(level=logging.INFO, format="%(message)s")`, in the same position.

### `tests/active/test_server.py`
The operator confirmed this rewire when asked. It changes only how the log is read, not what is asserted.
- New `_CLIENT_FORMATTER = client_server.ClientLogFormatter()`. `_error_messages` now renders each ERROR record through it, so `_error_events` parses the real production JSON lines and finds `event`/`context.error` again.
- `test_client_likes_502_is_fixed_text_and_engine_error_is_logged` takes `monkeypatch` and sets `caplog.handler.formatter` to `_CLIENT_FORMATTER` through `monkeypatch.setattr`, so `caplog.text` shows the production-rendered lines.
  - The plan used `caplog.handler.setFormatter` instead. A probe showed pytest 9.1.1 uses one caplog handler for the whole session, so `setFormatter` would carry into every later test. Monkeypatch restores it at teardown; a second probe test confirmed the default formatter is back.
- The module docstring line about the Engine sentinel now says it is in an ERROR record's `context.error`, as the Client's formatter renders it.

### `tests/active/test_log_format.py`
Not touched. The file does not exist, and this phase's checkpoint is `tests/tmp/test_19_timestamped_request_logs_phase3.py`.

**Beyond the files named.** tests/tmp/probe_caplog_formatter.py: my throwaway probe showing that caplog's handler, and so its formatter, lasts the whole session. I have no delete tool, so I emptied it; it collects no tests and can be removed. Separately, tests/tmp/test_probe_19_p3.py and tests/tmp/test_probe_19_p3_values.py were already there from an earlier step, and I did not touch them.

#### Phase 4 - Client text rendering and drift guard [code]

**Files touched.** client/backend/server.py (EDITED), tests/active/test_log_format.py (EDITED)

**Checkpoint.** Seam for C1: the in-process `_client_logging` context manager from phase 3, parametrized over the same eight `LOG_FORMAT` values as phase 2. JSON cases: every line parses. Text cases: every line matches `^<TS_RE> (INFO|ERROR) `, and the exception record and the `{"error": "x\ny"}` record are each one physical line containing a literal `\n`. A `client.access` record (`_emit_client_log(INFO, "client.access", "request finished", {"ip": …, "status": 200, "bytes": "-"})`) renders `<ts> INFO client.access request finished ip=… status=200 bytes=-`. No line starts with `<`. Seam for C2: the Engine child harness prints `_format_ts` for one fixed `created` and `_render_text` of a payload passed in argv: `{"ts": …, "level": "INFO", "event": "e", "message": "m\nn", "context": {"a": 1, "b": None, "c": [1, {"d": "x"}], "request_id": "r"}, "request_id": "r", "traceback": "T\nU"}`. The test asserts both strings equal `client_server._format_ts` and `client_server._render_text` on the same inputs in-process.

**Intent.** The Client's `normalize_log_format`, `_format_ts`, `_text_value` and `_render_text` are copies of the Engine's, so `LOG_FORMAT` selects the Client's rendering exactly as it does the Engine's, and both services write byte-identical `ts` and text for the same record.

- C1 - A Client `LOG_FORMAT` value selects text or JSON lines exactly as the same value does for the Engine.
- C2 - For the same `created` and payload, the Client's `_format_ts` and `_render_text` return the same strings as the Engine's.

**Outcome.** ### `client/backend/server.py`
- Added copies of the Engine's helpers from `engine/server/api/logging_profiles.py`, with bodies byte-identical to the Engine's. They sit before `ClientLogFormatter`, next to the existing `_format_ts`:
  - `SUPPORTED_LOG_FORMATS = ("json", "text")`.
  - `_TEXT_ESCAPES`, the table that escapes CR/LF.
  - `normalize_log_format(value)`: strips and lowercases the value. `json` or `text` is returned as is; anything else, including `None`, `""` and `bogus`, gives `"json"`. It never raises.
  - `_text_value(value)`: a string is returned as is, and any other value becomes compact JSON, so `None` is written as `null` and a list or dict stays one token.
  - `_render_text(payload)`: builds `ts LEVEL event [message] k=v… [request_id=…] [traceback]` and escapes CR/LF over the whole line.
- The phase-3 `rat-tail:` comment above `_format_ts` now covers all six mirrored names. It states the limit (editing only one copy lets the two drift), says a cross-service test compares them, and names the upgrade: a shared package once a third consumer appears.
- `ClientLogFormatter`:
  - New `__init__(self, log_format="json")` stores `normalize_log_format(log_format)`.
  - `format` builds the payload exactly as in phase 3. When the format is `text` it returns `_render_text(payload)`. `_render_text` does not write the `service` key, so the text line has the Engine's shape with no `service` token. Otherwise it returns the same `json.dumps` call as before, so JSON key order and values are unchanged.
  - `ClientLogFormatter()` with no argument is still JSON, so `_CLIENT_FORMATTER` in `tests/active/test_server.py` needs no change.
  - The class docstring now mentions text lines.
- `configure_client_logging` installs `ClientLogFormatter(os.environ.get("LOG_FORMAT"))`, so `LOG_FORMAT` is read when logging is set up, not at import. The docstring says so. Its call site in `main()` is unchanged.

### `tests/active/test_log_format.py`
Not touched. It does not exist in the tree, as in phases 1–3. This phase's drift guard is the checkpoint `tests/tmp/test_19_timestamped_request_logs_phase4.py`, and `tests/active/test_log_format.py` looks like its permanent home once it is moved out of `tests/tmp/`.


## Inner unit tests

None. Every phase's behaviour was expressible at its checkpoint.

## Close

- **Refactors:** the module docstring of `engine/server/api/logging_profiles.py` now mentions text lines. Left out, with reasons in the record's Step 8 refactor pass: moving `_proxy_engine_request`'s `context.traceback` to `exc_info` (that changes the JSON output), folding the access branches, renaming `EngineJsonFormatter`, and merging the six mirrored helpers. Nothing needed a fresh red.
- **Clause accounting:** P1C1, P1C2, P2C1, P2C2, P3C1, P3C2, P4C1 and P4C2 are each carried by their phase checkpoint's last audit (both auditors PASS).
- **`--compare`:** three attempts exited 1 on 15 to 17 reds. Every one is a control pinned to dataset contents that `57c8417 db rebuilt and updated` changed (the nsfw rows on the recent page, cache-entry sizes, whether a fallback runs, home-page overlap), plus one transient pager red. None asserts on logging, and build 19 has no code path to any of them, so no checkpoint gap was found and no durable test was retired. The operator chose "report only" three times and then directed the build to continue under `dev_flow.md` past Step 8. Re-pinning those controls against the rebuilt data is follow-up work outside this build.

## Documentation (Step 9)

- `DEPLOYMENT.md` - **update**: a `LOG_FORMAT` paragraph in section 2's service-environment block, after `RANDOM_CACHE_REFRESH_INTERVAL_MINUTES`. It gives the values, the fail-safe `json`, where to set the variable, the UTC `ts`, the text line shape with its escaping, and that both watchers and the Triage key recipes assume `json`.
- `DEPLOYMENT.md` Triage rows (`context.error`, `traceback`) and the section 3b symptom line - **no update**: they stay true under the `json` default, and the new paragraph says those recipes assume `json`.
- `engine/server/README.md` - **update**: the `traceback` note now adds that under `LOG_FORMAT=text` the traceback ends the record's line, newline-escaped.
- `client/README.md` - **update**: a `LOG_FORMAT` entry beside the other env settings. It says bare records appear as event `client.log` and that exception records carry a `traceback` key.
- `docs/project/issues/19-timestamped-request-logs.md` - **update**: set `Status: enhancement, complete`, added a delivery comment that records the JSON default as an operator decision, and moved the file to `docs/project/issues/archive/`.
- `docs/project/issues/plan.md` - **update**: the triage note now reads "19 is delivered" and points at this plan, and lane 4c reads "(19 delivered)".
- ADRs under `docs/project/adr/` - **no update**: none covers logging. `docs/wiki/` does not exist.

## Harvest (Step 10)

Run under `harvest.md`; the record is `docs/project/plans/harvest-19-timestamped-request-logs-plan.md`. All eight checkpoint tests are DURABLE. The four Engine tests went to `tests/active/test_logging_profiles.py` and the four Client tests to `tests/active/test_server.py`. Each was proved by a mutation that failed the assertion it was moved for. `test_groups` gained `handlers/similar.py` and `request_context.py` for `test_logging_profiles.py`, and `logging_profiles.py` for `test_server.py`. The checkpoints and 13 probes are in `delete_me/`. `--compare` shows 22 appeared ids and no departures. The one new red, the `[linux]` home-overlap control, is intermittent: three solo reruns passed.
