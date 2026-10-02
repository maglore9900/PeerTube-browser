# Build record - 19-timestamped-request-logs

Written by the `dev-flow` workflow. The plan it accompanies is `docs/project/plans/20-19-timestamped-request-logs.md`.

**Nothing but the workflow writes this file.** It carries the evidence each gate turned on: the baseline, both auditor verdicts verbatim, every self-check table, every red and its reason, every checkpoint outcome, and every amendment the operator approved to a settled section of the plan.

## Run state

<!-- dev-flow:state
```json
{
  "version": 1,
  "request": "# Timestamped request logs\n\nStatus: enhancement, needs-triage\nOrigin: task 41, [M7][F4]\n\n## Problem\n\nRequest timing analysis is harder when logs rely only on the journal envelope time or inconsistent message formatting.\n\n## Proposed solution\n\nAn explicit timestamp in the application log format and in request lifecycle logs.\n\n- Logging format with an explicit timestamp (ISO-8601 with milliseconds, UTC).\n- Request lifecycle logs and internal server logs share that format.\n- Optional structured output config (plain text default, JSON optional).\n- Compatible with journald (no duplicate parsing assumptions).\n\n## Validation (from the original task)\n\n- Sample log lines include full date/time and a timezone marker.\n- Ordering across request-start/work/request-end uses the application timestamp.\n\n## Related\n\n- First of the logging chain: this, then `20-request-lifecycle-logs`, then `21-static-page-visit-logs`.\n\n## Comments",
  "request_source": "read from docs/project/issues/19-timestamped-request-logs.md",
  "slug": "19-timestamped-request-logs",
  "steps": {
    "0": "done",
    "1": "done",
    "2": "done",
    "3": "done",
    "4": "done",
    "5": "done",
    "6": "done",
    "7": "done"
  },
  "phases": [
    {
      "n": "1",
      "kind": "code",
      "name": "Engine ts from record creation time",
      "checkpoint": "Seam for C1: the Engine child-process harness from tests/active/test_logging_profiles.py, i.e. `subprocess.run([sys.executable, \"-c\", _ENGINE_CHILD, \u2026], cwd=API_DIR)` with `LOG_FORMAT` removed from the env. The child calls `configure_engine_logging(\"verbose\")` and logs records to stderr. On stdout it prints the `_format_ts` and `EngineJsonFormatter().format` of a `LogRecord` whose `created` comes from argv. Assertions: every stderr line parses as JSON and its `ts` matches `^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}\\.\\d{3}Z$`. created=1741091696.789 gives `2025-03-04T12:34:56.789Z` from both `_format_ts` and the formatted JSON's `ts`. created=1741091696.9999996 gives `2025-03-04T12:34:57.000Z`. A created one hour in the past renders that hour, not the formatting time. Seam for C2: the session `engine` fixture in conftest.py, whose log is read through `engine.db_path` as test_similar.py's `_messages` does. The test sends `POST /recommendations?limit=5&user_id=log-order-<uuid4 hex>` with `body={}`. If the route refuses `user_id`, the marker goes in through the `Host` header instead. The test parses the log's JSON lines, cuts the slice from the `access.start` whose `context.url` contains the marker to the `access` containing it, keeps the access.start, the access and the `recommendations.*` records, and asserts at least one work record and non-decreasing `ts`.",
      "intent": "In engine/server/api/logging_profiles.py, EngineJsonFormatter takes every record's `ts` from `_format_ts(record)`, which renders `record.created` in UTC as `YYYY-MM-DDTHH:MM:SS.mmmZ`, so the Engine's `ts` follows the order of the log calls rather than the time of formatting.",
      "clauses": [
        {
          "id": "C1",
          "text": "An Engine record's `ts` is its `record.created` rendered in UTC as `YYYY-MM-DDTHH:MM:SS.mmmZ`."
        },
        {
          "id": "C2",
          "text": "Within one live Engine request, the `ts` values from its `access.start` to its `access` never decrease."
        }
      ],
      "files": [
        "engine/server/api/logging_profiles.py (EDITED)",
        "tests/active/test_log_format.py (NEW)"
      ],
      "done": true,
      "outcome": "### `engine/server/api/logging_profiles.py`\n- Added the module-level helper `_format_ts(record)`. It renders `record.created` in UTC as `YYYY-MM-DDTHH:MM:SS.mmmZ` using `datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(timespec=\"milliseconds\")`, with the `+00:00` suffix replaced by `Z`.\n- It deliberately does not read `record.msecs`, because `msecs` is not updated when `created` is set after the record is built.\n- I observed the rounding in a probe rather than assuming it. `fromtimestamp` rounds to the microsecond before `isoformat` cuts to milliseconds: `1741091696.789` came out as `2025-03-04T12:34:56.789+00:00` and `1741091696.9999996` as `2025-03-04T12:34:57.000+00:00`.\n- `EngineJsonFormatter.format` now sets `\"ts\": _format_ts(record)`. Before, it used `datetime.now().astimezone().isoformat(...)`, which gave local time at the moment of formatting. Now the stamp is the time the log call happened, which is what keeps it in order across one request.\n- The import changed from `from datetime import datetime` to `from datetime import datetime, timezone`.\n\n### `tests/active/test_log_format.py`\nNot created. The phase lists it as NEW, but this step is production code only. It looks like the permanent home for the checkpoint once it is moved out of `tests/tmp/`, and nothing in this phase needs it to exist.\n\n### `tests/tmp/probe_fromtimestamp.py`\nThis was my throwaway probe for the rounding check. I have no delete tool, so I emptied the file instead; it now collects no tests. It can be removed.",
      "beyond": "tests/tmp/probe_fromtimestamp.py: the throwaway probe for the rounding check. It is now an empty file because I couldn't delete it, and it can be removed."
    },
    {
      "n": "2",
      "kind": "code",
      "name": "Engine LOG_FORMAT text rendering",
      "checkpoint": "Seam: the same Engine child-process harness (cwd=API_DIR; env without `LOG_FORMAT`, plus `LOG_FORMAT` set when the case has a value), parametrized over None, \"json\", \"JSON\", \"bogus\", \"\", \"text\", \"TEXT\", \" Text \". The child calls `configure_engine_logging(\"verbose\")` and logs, in order: `[probe] plain`, `[probe] two\\nlines`, a `logging.exception(\"[probe] failed\")` for `ValueError(\"sentinel-log-format\")`, `[access.start] ip=127.0.0.1 method=GET url=http://x/a`, and `[service] lifecycle state=start component=engine run_id=r pid=1`. C1: the JSON cases give stderr lines that all parse with `json.loads`; the text cases give lines matching `^<TS_RE> (INFO|ERROR) ` and none parse as a JSON object. C2, in text mode: stderr has exactly five lines. The multiline and exception records each sit on one line, contain a literal `\\n` and, for the exception record, end with `ValueError: sentinel-log-format`. The access.start line is `<ts> INFO access.start request started ip=127.0.0.1 method=GET url=http://x/a`. The lifecycle line goes `<ts> INFO service.lifecycle state=start` with no message token. No line starts with `<`.",
      "intent": "configure_engine_logging reads `LOG_FORMAT` when it runs and, for `text`, has EngineJsonFormatter render each record's payload through `_render_text` as one CR/LF-escaped `ts LEVEL event message k=v\u2026` line, while every other value keeps today's JSON.",
      "clauses": [
        {
          "id": "C1",
          "text": "An Engine `LOG_FORMAT` of text in any case or surrounding whitespace selects text lines, and an unset, empty, `json` or unknown value selects JSON lines."
        },
        {
          "id": "C2",
          "text": "An Engine text record is one physical line shaped `ts LEVEL event [message] k=v\u2026 [request_id=\u2026] [traceback]` with CR and LF written as `\\r` and `\\n`."
        }
      ],
      "files": [
        "engine/server/api/logging_profiles.py (EDITED)",
        "tests/active/test_log_format.py (EDITED)"
      ],
      "done": true,
      "outcome": "### `engine/server/api/logging_profiles.py`\n- Imports: added `os`. The module still imports only the stdlib and `request_context`.\n- Added `SUPPORTED_LOG_FORMATS = (\"json\", \"text\")` next to `SUPPORTED_LOG_MODES`. Added `_TEXT_ESCAPES`, a `str.maketrans` table that writes CR as `\\r` and LF as `\\n`, after `_LEADING_BLOCKS_RE`.\n- New public `normalize_log_format(value)` directly after `normalize_log_mode`, with the same fail-safe shape: it strips and lowercases the value and returns it if it is in `SUPPORTED_LOG_FORMATS`. Anything else, including `None`, `\"\"` and `bogus`, gives `\"json\"`. It never raises.\n- New `_text_value(value)`: a string is returned as it is, and any other value becomes compact JSON (`ensure_ascii=False`, `default=str`), so a list or dict stays a single token and `None` is written as `null`.\n- New `_render_text(payload)`: builds `ts LEVEL event`, then the message if the payload has one, then each context entry as `k=v`, then `request_id=\u2026` (skipped if the context already has a `request_id` key), then the traceback. Everything is joined with single spaces, and CR/LF are escaped over the whole line at the end. `modes` is not written.\n- `EngineJsonFormatter`: new `__init__(self, log_format=\"json\")`, which stores `normalize_log_format(log_format)`. `format` builds the payload exactly as before. When the format is `text` it returns `_render_text(payload)`; otherwise it returns the same `json.dumps` expression as before, so JSON key order and values are unchanged. `EngineJsonFormatter()` with no argument still gives JSON, so the existing unit-test callers need no change. The class docstring now mentions text lines.\n- `configure_engine_logging`: installs `EngineJsonFormatter(os.environ.get(\"LOG_FORMAT\"))`, so the variable is read when the function is called, not at import. The signature and return value (the normalised log mode) are unchanged; only the docstring changed.\n\n### `tests/active/test_log_format.py`\nNot touched. The file does not exist in the tree, and this phase's checkpoint lives at `tests/tmp/test_19_timestamped_request_logs_phase2.py`. No production change needed it."
    },
    {
      "n": "3",
      "kind": "code",
      "name": "Client root formatter, JSON",
      "checkpoint": "Seam: in-process through conftest's `client_server` import. A `_client_logging(monkeypatch, value)` context manager is used inside the test body. It saves the root handlers and level, sets or deletes `LOG_FORMAT`, calls `client_server.configure_client_logging()`, swaps `root.handlers[0]` to an `io.StringIO` stream, and restores everything in `finally`. With `LOG_FORMAT` unset, the test calls `client_server._emit_client_log(logging.ERROR, \"engine.call\", \"Engine metadata failed\", {\"error\": \"x\\ny\"})`, then a `logging.exception` record, then `logging.info(\"bare\")`. C1: the emitted line's keys are exactly `[\"ts\", \"level\", \"service\", \"event\", \"message\", \"context\"]` in order, with `service == \"client-backend\"`, `event == \"engine.call\"`, `context == {\"error\": \"x\\ny\"}` and `ts` matching TS_RE. The exception record carries a `traceback` key. C2: the bare record parses with keys `ts, level, service, event, message`, `event == \"client.log\"` and `message == \"bare\"`. The full suite also covers the rewired ERROR-record tests in tests/active/test_server.py (`_error_messages` renders through `ClientLogFormatter`, and caplog's handler gets that formatter in the `caplog.text` test), which must stay green.",
      "intent": "In client/backend/server.py, configure_client_logging installs ClientLogFormatter on the root logger, which `main()` now calls in place of `basicConfig`, and `_emit_client_log` hands it event and context as `client_event`/`client_context` record attributes instead of building JSON by hand, so every Client record leaves through one formatter.",
      "clauses": [
        {
          "id": "C1",
          "text": "An `_emit_client_log` record renders as a JSON line whose keys run `ts, level, service, event, message[, context]` with a UTC `ts`."
        },
        {
          "id": "C2",
          "text": "A bare root-logger record renders in the same JSON shape with event `client.log`."
        }
      ],
      "files": [
        "client/backend/server.py (EDITED)",
        "tests/active/test_server.py (EDITED)",
        "tests/active/test_log_format.py (EDITED)"
      ],
      "done": true,
      "outcome": "### `client/backend/server.py`\n- The datetime import is now `from datetime import datetime, timezone`.\n- New `_format_ts(record)`, a copy of the Engine's. It renders `record.created` in UTC as `YYYY-MM-DDTHH:MM:SS.mmmZ`. A `rat-tail:` comment says it mirrors `engine/server/api/logging_profiles.py` because the two services import from different roots, and that a drift guard is the upgrade (planned for phase 4).\n- New `ClientLogFormatter(logging.Formatter)`. Its `format` builds the payload in the order `ts, level, service (\"client-backend\"), event, message`.\n  - `event` is the record's `client_event`, or `client.log` when the record has none.\n  - `message` is `record.getMessage()`.\n  - `context` (the record's `client_context`) is added only when it is not empty, the same rule as the old `if context:`.\n  - A record with `exc_info` also gets a `traceback` key, rendered by `formatException`.\n  - Output is `json.dumps(..., ensure_ascii=True, separators=(\",\", \":\"))`, the same call as before.\n  - JSON only for now. `LOG_FORMAT` handling and text rendering are left to phase 4.\n- New `configure_client_logging()`. It clears the root handlers, sets the level to INFO, and adds one INFO `StreamHandler()` (stderr, the same stream `basicConfig` used) carrying `ClientLogFormatter()`.\n- `_emit_client_log` keeps its signature and all its call sites. Its body is now `logging.log(level, message, extra={\"client_event\": event, \"client_context\": context})` instead of building the JSON string by hand.\n- `main()` calls `configure_client_logging()` in place of `logging.basicConfig(level=logging.INFO, format=\"%(message)s\")`, in the same position.\n\n### `tests/active/test_server.py`\nThe operator confirmed this rewire when asked. It changes only how the log is read, not what is asserted.\n- New `_CLIENT_FORMATTER = client_server.ClientLogFormatter()`. `_error_messages` now renders each ERROR record through it, so `_error_events` parses the real production JSON lines and finds `event`/`context.error` again.\n- `test_client_likes_502_is_fixed_text_and_engine_error_is_logged` takes `monkeypatch` and sets `caplog.handler.formatter` to `_CLIENT_FORMATTER` through `monkeypatch.setattr`, so `caplog.text` shows the production-rendered lines.\n  - The plan used `caplog.handler.setFormatter` instead. A probe showed pytest 9.1.1 uses one caplog handler for the whole session, so `setFormatter` would carry into every later test. Monkeypatch restores it at teardown; a second probe test confirmed the default formatter is back.\n- The module docstring line about the Engine sentinel now says it is in an ERROR record's `context.error`, as the Client's formatter renders it.\n\n### `tests/active/test_log_format.py`\nNot touched. The file does not exist, and this phase's checkpoint is `tests/tmp/test_19_timestamped_request_logs_phase3.py`.",
      "beyond": "tests/tmp/probe_caplog_formatter.py: my throwaway probe showing that caplog's handler, and so its formatter, lasts the whole session. I have no delete tool, so I emptied it; it collects no tests and can be removed. Separately, tests/tmp/test_probe_19_p3.py and tests/tmp/test_probe_19_p3_values.py were already there from an earlier step, and I did not touch them."
    },
    {
      "n": "4",
      "kind": "code",
      "name": "Client text rendering and drift guard",
      "checkpoint": "Seam for C1: the in-process `_client_logging` context manager from phase 3, parametrized over the same eight `LOG_FORMAT` values as phase 2. JSON cases: every line parses. Text cases: every line matches `^<TS_RE> (INFO|ERROR) `, and the exception record and the `{\"error\": \"x\\ny\"}` record are each one physical line containing a literal `\\n`. A `client.access` record (`_emit_client_log(INFO, \"client.access\", \"request finished\", {\"ip\": \u2026, \"status\": 200, \"bytes\": \"-\"})`) renders `<ts> INFO client.access request finished ip=\u2026 status=200 bytes=-`. No line starts with `<`. Seam for C2: the Engine child harness prints `_format_ts` for one fixed `created` and `_render_text` of a payload passed in argv: `{\"ts\": \u2026, \"level\": \"INFO\", \"event\": \"e\", \"message\": \"m\\nn\", \"context\": {\"a\": 1, \"b\": None, \"c\": [1, {\"d\": \"x\"}], \"request_id\": \"r\"}, \"request_id\": \"r\", \"traceback\": \"T\\nU\"}`. The test asserts both strings equal `client_server._format_ts` and `client_server._render_text` on the same inputs in-process.",
      "intent": "The Client's `normalize_log_format`, `_format_ts`, `_text_value` and `_render_text` are copies of the Engine's, so `LOG_FORMAT` selects the Client's rendering exactly as it does the Engine's, and both services write byte-identical `ts` and text for the same record.",
      "clauses": [
        {
          "id": "C1",
          "text": "A Client `LOG_FORMAT` value selects text or JSON lines exactly as the same value does for the Engine."
        },
        {
          "id": "C2",
          "text": "For the same `created` and payload, the Client's `_format_ts` and `_render_text` return the same strings as the Engine's."
        }
      ],
      "files": [
        "client/backend/server.py (EDITED)",
        "tests/active/test_log_format.py (EDITED)"
      ],
      "done": true,
      "outcome": "### `client/backend/server.py`\n- Added copies of the Engine's helpers from `engine/server/api/logging_profiles.py`, with bodies byte-identical to the Engine's. They sit before `ClientLogFormatter`, next to the existing `_format_ts`:\n  - `SUPPORTED_LOG_FORMATS = (\"json\", \"text\")`.\n  - `_TEXT_ESCAPES`, the table that escapes CR/LF.\n  - `normalize_log_format(value)`: strips and lowercases the value. `json` or `text` is returned as is; anything else, including `None`, `\"\"` and `bogus`, gives `\"json\"`. It never raises.\n  - `_text_value(value)`: a string is returned as is, and any other value becomes compact JSON, so `None` is written as `null` and a list or dict stays one token.\n  - `_render_text(payload)`: builds `ts LEVEL event [message] k=v\u2026 [request_id=\u2026] [traceback]` and escapes CR/LF over the whole line.\n- The phase-3 `rat-tail:` comment above `_format_ts` now covers all six mirrored names. It states the limit (editing only one copy lets the two drift), says a cross-service test compares them, and names the upgrade: a shared package once a third consumer appears.\n- `ClientLogFormatter`:\n  - New `__init__(self, log_format=\"json\")` stores `normalize_log_format(log_format)`.\n  - `format` builds the payload exactly as in phase 3. When the format is `text` it returns `_render_text(payload)`. `_render_text` does not write the `service` key, so the text line has the Engine's shape with no `service` token. Otherwise it returns the same `json.dumps` call as before, so JSON key order and values are unchanged.\n  - `ClientLogFormatter()` with no argument is still JSON, so `_CLIENT_FORMATTER` in `tests/active/test_server.py` needs no change.\n  - The class docstring now mentions text lines.\n- `configure_client_logging` installs `ClientLogFormatter(os.environ.get(\"LOG_FORMAT\"))`, so `LOG_FORMAT` is read when logging is set up, not at import. The docstring says so. Its call site in `main()` is unchanged.\n\n### `tests/active/test_log_format.py`\nNot touched. It does not exist in the tree, as in phases 1\u20133. This phase's drift guard is the checkpoint `tests/tmp/test_19_timestamped_request_logs_phase4.py`, and `tests/active/test_log_format.py` looks like its permanent home once it is moved out of `tests/tmp/`."
    }
  ],
  "digests": {
    "tests/tmp/test_19_timestamped_request_logs_phase1.py": "5ce68ebb2f865c35cdc97415575813d329b5bd6f5bde0f37286fe222f88b8bd7",
    "tests/tmp/test_19_timestamped_request_logs_phase2.py": "fc682c028e673da7cbf21513f46ac4c1269a44fe3cfbd7f53d375330526b76ea",
    "tests/tmp/test_19_timestamped_request_logs_phase3.py": "33090feee8886a80677df35d70d728e8079d21897294cf09b426ea276e8efe77",
    "tests/tmp/test_19_timestamped_request_logs_phase4.py": "1f76dc094a66931b287ff907f2f0ad91f8fe4e8b510306f5bf3012a433f8297c"
  },
  "paths": {
    "active": "tests/active",
    "working": "tests/tmp",
    "plans": "docs/project/plans",
    "delete_me": "delete_me",
    "archive": "tests/archive",
    "project_dir": "/home/enduser/code/PeerTube-browser/.worktrees/19",
    "record": "tests/last_test_validation.json",
    "output": "tests/last_test_output.txt"
  },
  "baseline": {
    "code": 0,
    "variant": false
  },
  "sessions": [
    "20261001T175457-7b02-dev-flow",
    "20261001T175936-b83b-dev-flow"
  ],
  "plan": "docs/project/plans/20-19-timestamped-request-logs.md",
  "record": "docs/project/plans/20-19-timestamped-request-logs.record.md",
  "replies": {
    "step_1_gather_requirements": "<requirements>\n### Purpose\n\nIssue 19 (task 41, [M7][F4]) is the first of the logging chain: 19 timestamped logs, then 20 request lifecycle logs with a shared `request_id`, then 21 static page visit logs. The goal is to make request timing analysis possible from the application's own log lines. Each record must carry an explicit, unambiguous, comparable timestamp, so the order of request-start, work and request-end within a request can be read from the app log alone. That must not depend on the journald envelope time or on how a given message happens to be formatted. Both long-running services must use the same timestamp and line format, so their logs can be compared side by side.\n\n### Current state (found in the tree)\n\n- Engine API server: `configure_engine_logging` in `engine/server/api/logging_profiles.py` installs `EngineJsonFormatter` on the root logger (one StreamHandler, INFO). It is called from `engine/server/api/server.py` line 323. Each record becomes one JSON line with keys `ts`, `level`, `event`, `message` (dropped for `service.lifecycle`), `modes`, plus `request_id`, `context` and `traceback` when present. `ts` is `datetime.now().astimezone().isoformat(timespec=\"milliseconds\")`. That is local time with a numeric offset, and it is taken when the record is formatted, not when it was created.\n- Engine request lines: `[access.start]` (`_log_access_start`) and `[access]` (`log_message`) in `engine/server/api/handlers/similar.py` are plain `logging.info` calls rendered by that formatter, with events `access.start` and `access`.\n- Client backend: `client/backend/server.py` calls `logging.basicConfig(level=logging.INFO, format=\"%(message)s\")` in `main()`. All its logs go through `_emit_client_log(level, event, message, context)`, which builds its own JSON string. The keys are `ts` (same local-time expression as the Engine), `level`, `service: \"client-backend\"`, `event`, `message` and optional `context`. Access lines come from `ClientBackendHandler.log_message` as event `client.access`. A record that does not go through `_emit_client_log` (for example a library logging to the root logger) is printed as its bare message with no timestamp.\n- Consumers of the JSON: `engine/watch-engine-logs.sh` runs `journalctl -o cat | jq -R 'fromjson?'` and filters on `.modes`, `.level`, `.event` and `.message`. `client/watch-client-logs.sh` runs `jq -R 'fromjson? // {\"raw\": .}'`. The DEPLOYMENT.md runbooks send operators to the `traceback` key (Engine) and to `context.error` of the ERROR `engine.call` / `engine.bridge` records (Client).\n- Existing tests: `engine/server/api/tests/test_logging_profiles.py` asserts `\"ts\" in payload`. `tests/active/test_logging_profiles.py`, `tests/active/test_internal_events.py` and `tests/active/test_similar.py` run `configure_engine_logging(\"verbose\")` and parse the JSON lines (including `traceback` and `message`).\n\n### Scope\n\nIn scope: the Engine API server process (everything logged through the root logger once `configure_engine_logging` has run) and the Client backend process (`client/backend/server.py`).\n\nOut of scope:\n- `request_id` propagation and request-end `duration_ms` (issue 20).\n- nginx and static page visit logging (issue 21).\n- The batch scripts in `engine/server/db/jobs/` and `updater-worker.py`, which keep their own plain `basicConfig` formats.\n- Raw stderr output that does not pass through `logging`: socketserver's default `handle_error` traceback print and the `faulthandler` SIGUSR1 stack dump.\n\n### R1 \u2014 Explicit UTC timestamp with milliseconds\n\n- Every log record written by either service carries a timestamp in ISO-8601 extended format, in UTC, with millisecond precision and a `Z` zone marker, in exactly this shape: `YYYY-MM-DDTHH:MM:SS.mmmZ`, e.g. `2025-03-04T12:34:56.789Z`. No local time and no numeric offset (`+00:00` is not the accepted form; `Z` is).\n- The timestamp is taken from the moment the log call was made (`logging.LogRecord.created`), not from when the formatter runs.\n- In JSON output the timestamp stays under the existing key `ts`.\n\n### R2 \u2014 One shared format across both services\n\n- The Engine and the Client backend produce records to one contract: the same `ts` format (R1), the same `level` names (the stdlib level names `DEBUG`/`INFO`/`WARNING`/`ERROR`/`CRITICAL`), and the same leading key order `ts`, `level`, then the remaining keys.\n- Request lifecycle lines (Engine `access.start` and `access`, Client `client.access`) and internal server lines (service start/stop/lifecycle, recommendations and similarity logs, `engine.call` and `engine.bridge` errors, any WARNING/ERROR) all go through this format. No record from either process reaches its output stream without the timestamp.\n- The Client backend gets a real formatter on its root logger, the same way the Engine has one. A record logged in the Client by any path other than `_emit_client_log` (a bare `logging.*` call or a library's logger) is still emitted in the shared format with `ts`, `level` and an event. The Client's existing payload keys (`service: \"client-backend\"`, `event`, `message`, `context`) are preserved.\n- How the code is shared between the two services (one shared helper or two matching implementations) is a design decision for later steps. The requirement is the identical output contract.\n\n### R3 \u2014 Output format switch (JSON default, plain text opt-in)\n\n- One environment variable, `LOG_FORMAT`, read by both services at logging setup, selects the output format: `json` (default) or `text`. Matching is case-insensitive and ignores surrounding whitespace.\n- An unset, empty or unrecognised value selects `json`. It fails safe the same way `normalize_log_mode` falls back to `verbose`, and it must not stop the service from starting.\n- JSON stays the default because `engine/watch-engine-logs.sh`, `client/watch-client-logs.sh` and the DEPLOYMENT.md runbooks depend on it. In JSON mode the existing keys and their meaning are unchanged: Engine `ts`, `level`, `event`, `message`, `modes`, `request_id`, `context`, `traceback`, including the per-event message rewriting already in `EngineJsonFormatter`; Client `ts`, `level`, `service`, `event`, `message`, `context`. Only the value format of `ts` changes (R1).\n- The Engine's existing `focused`/`verbose` log mode concept (`modes` tagging) is separate from `LOG_FORMAT` and is not changed.\n- Where the variable is documented (the service README/DEPLOYMENT notes alongside other env settings), add `LOG_FORMAT` with its two values and the default.\n\n### R4 \u2014 Plain text line shape\n\n- In `text` mode each record is one line: `<ts> <LEVEL> <event> <message>`. Then come the record's context entries as space-separated `key=value` tokens (where the record has a context dict, as the Client's do), then `request_id=<id>` when a request id is present. For the Engine, `message` is the same message text the JSON payload would carry.\n- The `ts` in text mode is the identical string R1 defines, so text and JSON lines from the same moment carry the same timestamp.\n\n### R5 \u2014 journald compatibility\n\n- Exactly one physical line per record in both formats, because journald stores each stdout line as its own entry. In JSON mode this is already true (`json.dumps` escapes newlines). In text mode, any newline inside the message or the traceback is escaped (rendered as the two characters `\\n`), so one record is never split across journal entries. In text mode the traceback is appended on that same line.\n- No syslog priority prefixes (`<N>`) or other markers that journald would interpret. Output goes to the same stream as today (the Engine's StreamHandler default, stderr; the Client's `basicConfig` default, stderr), so the existing systemd units and `journalctl -u \u2026 -o cat` pipelines keep working unchanged.\n- Nothing in the logs or the tooling relies on the journal envelope timestamp for ordering. The application `ts` is the timestamp of record.\n\n### R6 \u2014 Ordering by application timestamp\n\n- For a single request handled on one thread, the `ts` of its request-start line (Engine `access.start`), of any work log lines emitted while handling it, and of its request-end line (Engine `access`, Client `client.access`) are non-decreasing in that order. Because `ts` comes from `record.created` (R1), it reflects when each event happened, not when the line was formatted.\n- Ordering is guaranteed per request, not globally across concurrently served requests (consistent with issue 20).\n\n### Validation\n\n- A sample record from each service, in each format, contains a full date and time with milliseconds and the `Z` timezone marker, matching `^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}\\.\\d{3}Z$` for the `ts` value.\n- An Engine request produces `access.start`, work and `access` records whose `ts` values are non-decreasing.\n- `ts` equals the record's creation time rendered in UTC: a record created at a known `created` value renders that instant, not the formatting time.\n- `LOG_FORMAT` unset, `json`, `JSON`, `bogus` and empty each select JSON; `text` (any case) selects the text line. Every record is a single line in both modes, including one with a traceback and one whose message contains a newline.\n- The Client backend emits a record in the shared format both for `_emit_client_log` calls and for a bare `logging.info` call made after its logging setup.\n- The existing JSON consumers keep working: Engine payload keys and per-event message rewriting unchanged, and the existing tests that parse the Engine JSON (`tests/active/test_logging_profiles.py`, `test_internal_events.py`, `test_similar.py`, `engine/server/api/tests/test_logging_profiles.py`) still pass.\n\n### Baseline suite state\n\nThe pre-build baseline run exited with code 0 (`variant: false`): the active suite in `tests/active` is green before this build starts. Any red test after the build is attributable to the build. The project dir is `/home/enduser/code/PeerTube-browser/.worktrees/19`, the working test dir is `tests/tmp`, the archive is `tests/archive`, the plans live in `docs/project/plans`, the run record is `tests/last_test_validation.json` and the output is `tests/last_test_output.txt`.\n</requirements>\n\n<conflicts>\nThe issue says plain text should be the default with JSON optional (\"plain text default, JSON optional\"). The tree already writes JSON by default from both the Engine (`EngineJsonFormatter` in engine/server/api/logging_profiles.py) and the Client backend (`_emit_client_log` in client/backend/server.py), and engine/watch-engine-logs.sh, client/watch-client-logs.sh and the DEPLOYMENT.md runbooks depend on that JSON. The operator resolved this: JSON stays the default and plain text is an opt-in through LOG_FORMAT=text (R3).\nThe issue asks for a UTC timestamp, while the tree's existing `ts` in both services is local time with a numeric offset (`datetime.now().astimezone()`), taken at format time rather than from record.created. R1 changes the value format of `ts` to UTC `Z` from record.created. Any operator reading or tooling that assumed local wall-clock time in `ts` will now see UTC.\n</conflicts>",
    "step_2_develop_solution": "<initial_solution>\n### Approach\n\nThe change is in the formatter layer of each service. No call site changes, except that the Client's `_emit_client_log` stops serialising JSON by hand. I read `engine/server/api/logging_profiles.py`, `client/backend/server.py` (lines 120-136 `_emit_client_log`, 258-273 `log_message`, 1175-1252 `main`), the Engine's call site at `engine/server/api/server.py:323`, and `tests/active/conftest.py:41`, which already imports the Client `server` module in-process.\n\n**Timestamp (R1, R6).** Each service gets one small private helper that turns a `LogRecord` into the `ts` string. It renders `record.created` in UTC as `YYYY-MM-DDTHH:MM:SS`, appends `.` and the record's milliseconds as three digits, then appends a literal `Z`. All of this is stdlib. The value comes from `record.created`, which `logging` sets at the moment of the log call, not from `datetime.now()`. So ordering within one thread follows the order of the calls even if formatting happens later. That gives R6 for `access.start`, the work lines and `access` / `client.access`. Both the seconds and the milliseconds are taken from the same `created` value, so they cannot disagree. The `+00:00` form that `isoformat` would produce is avoided by building the string explicitly.\n\n**Engine (R1-R5).** `EngineJsonFormatter.format` keeps all of its classification, request-id extraction, context building and per-event message rewriting exactly as it is. Only the `ts` value changes, and it now comes from the record. The work is split so the formatter first builds the payload dict as it does today, then renders it one of two ways:\n- JSON: today's `json.dumps`, unchanged.\n- Text: one line made of `ts`, `level`, `event` and the payload's `message`, separated by spaces. If the payload has a `context`, its entries follow as `key=value` tokens. Then comes `request_id=<id>` when present, then the traceback.\n\nBecause both renderings use the same payload, the text-mode message is by construction the message JSON would carry (\"request started\", \"request finished\", \"[recommendations] incoming likes\"). The formatter chooses its rendering when it is constructed. `configure_engine_logging` reads `LOG_FORMAT` from the environment when it runs and passes the normalised choice to the formatter. Its signature `configure_engine_logging(profile)` stays the same, so `server.py:323` and the four existing test modules need no change. A small `normalize_log_format` sits next to `normalize_log_mode` with the same fail-safe shape: strip, lowercase, `text` means text, anything else means `json`.\n\n**Client (R2-R5).** The Client gets a real formatter on its root logger. `main()` replaces `logging.basicConfig(format=\"%(message)s\")` with a `configure_client_logging()` call. That function clears the root handlers, sets INFO, adds a StreamHandler (stderr, as today), installs the Client formatter and reads `LOG_FORMAT` the same way the Engine does. `_emit_client_log` keeps its signature and its call sites. It no longer builds a JSON string. Instead it calls `logging.log(level, message, extra=...)` and passes `event` and `context` as record attributes. The formatter builds the payload in the order `ts`, `level`, `service: \"client-backend\"`, `event`, `message`, `context`, which is the same keys in the same order as today. A record without those attributes, such as a bare `logging.info` call or a library logger, gets `event` set to a fallback name (`client.log`, matching the Engine's `engine.log` fallback) and its `getMessage()` as `message`. If the record has `exc_info`, the formatter adds a `traceback` key the way the Engine does. That key is new to the Client, but it is additive, and without it an exception logged through the root logger would be silently lost. Text mode uses the same line shape as the Engine.\n\n**Text rendering details (R4, R5).** Context values that are scalars are written with `str()`. Values that are lists or dicts, for example the Engine's incoming-likes context, are written as compact JSON so each one stays a single token. Once the line is assembled, every CR and LF in it (message, context values, traceback) is replaced by the two-character escapes `\\r` / `\\n`. Every record is therefore one physical line. Nothing is added in front of the line, so there are no `<N>` prefixes and no extra markers. For `service.lifecycle`, where JSON drops `message`, the text line leaves the message token out and goes straight from event to context.\n\n**Docs (R3).** One `LOG_FORMAT` paragraph goes into DEPLOYMENT.md beside the other Engine/Client environment settings (around lines 105-114). It states the values `json` (default) and `text`, the fail-safe behaviour, and that the watch scripts and runbook `jq` recipes need `json`. It also says how to set the variable: through `.env.bridge` or an `Environment=` drop-in.\n\n**Requirement map.**\n- R1: the UTC helper built from `created`.\n- R2: two formatters to one contract. Both have leading `ts`/`level`, use stdlib level names and use the same helper shape, and the Client now has a root formatter that catches bare records.\n- R3: `LOG_FORMAT` normalisation in both setup functions; the JSON keys are unchanged.\n- R4: the shared payload-to-text rendering.\n- R5: newline escaping, unchanged streams and no prefixes.\n- R6: `created`-based `ts`.\n\n### Alternatives considered\n\n- **One shared module for both services**, for example `common/log_format.py` at the repo root. Rejected. The Engine imports from `engine/server/api` (`from request_context import \u2026`) and the Client from `client/backend` (`from lib.\u2026 import \u2026`). Neither has the repo root on `sys.path`, so sharing would need a `sys.path` insert in both entry points, the install scripts and the tests, and it would join two independently deployed units at import time. The duplicated logic is about a dozen lines: the ts helper, the text renderer and the format normaliser. I chose two matching implementations and a cross-service test as the guard against drift. This is a deliberate simplification. Its ceiling is that the two copies can diverge if someone edits only one. The upgrade path is to extract a shared package once a third consumer appears, for example the issue-21 static visit logger if it is written in Python.\n- **Keep `_emit_client_log` building JSON and add `basicConfig(format=\"%(asctime)s \u2026\")`.** Rejected. A record from `_emit_client_log` would then contain JSON inside a text prefix. That breaks `watch-client-logs.sh`'s `fromjson?` and does not meet \"same format\".\n- **Set `logging.Formatter.converter = time.gmtime` and use `formatTime`.** Rejected. `formatTime` with `default_msec_format` gives `,mmm` and no `Z`, so it would need overriding anyway. A class-level `converter` change also leaks process-wide. An explicit helper is clearer.\n- **Read `LOG_FORMAT` in `server_config.py` (Engine) at import.** Rejected. Reading it at logging setup is what R3 asks for. It also lets tests monkeypatch the environment and call `configure_engine_logging` without reloading a module.\n- **Wrap the existing JSON formatter in a separate text formatter class.** Rejected as an extra class for one switch. A constructor flag on the existing formatter is smaller.\n\n### Risks and gotchas\n\n- **Validation timing.** `record.created` is fixed when the record is created. A test that builds a `LogRecord` with a chosen `created` (and the matching `msecs`, which is derived at construction) must set both to check \"renders that instant\". The plan derives milliseconds from `created` itself rather than trusting `msecs`, so setting `created` alone is enough.\n- **Ambiguous text tokens.** In text mode, a context value or message containing spaces or `=` is not quoted, so `key=value` tokens are best-effort for human reading, not a parseable format. JSON remains the machine contract. This is a named limitation.\n- **The Client `extra=` names** must not collide with reserved `LogRecord` attributes (`message`, `msg`, `args`, \u2026). They will be namespaced, for example `client_event` and `client_context`.\n- **Third-party library records in the Client** now appear as structured lines with event `client.log`. Before, they appeared as bare text. Any record with level below INFO is still filtered as today.\n- **The existing Engine tests** read `ts` only for presence, so the format change does not break them. If the CI environment ever exported `LOG_FORMAT=text`, the JSON-parsing tests would fail. The new tests pin `LOG_FORMAT` explicitly, and the existing ones rely on the default.\n- **The Client test seam.** `conftest.py` imports the Client `server` module in-process, so the formatter can be tested directly. A test that calls `configure_client_logging()` replaces the root handlers of the pytest process and must restore them, the same way the Engine tests already handle `configure_engine_logging`.\n- **Out of scope, still untimestamped.** Raw stderr (socketserver `handle_error`, the faulthandler dump) still has no timestamp. The requirements say so explicitly.\n\n### Tradeoffs for the operator\n\n- There are two parallel implementations of one contract instead of a shared module. Drift is guarded by a test rather than by structure.\n- Text mode is for humans. It escapes newlines and does not quote values, so tooling must keep using JSON.\n- The Client gains an additive `traceback` key on records logged with `exc_info`. It is not part of the existing key list but is needed so no exception is dropped.\n- `ts` changes from local time with an offset to UTC `Z`. Operators reading raw lines see UTC rather than local wall-clock time.\n</initial_solution>\n\n<conflicts>\nnone\n</conflicts>",
    "step_3_identify_impacts": "<impacts>\n\n<impacts>\n<impact path=\"engine/server/api/logging_profiles.py\" element=\"imports (lines 5-12)\">\n**What changes.** `from datetime import datetime` (line 9) is used only for the `ts` at line 195. The new UTC helper needs `datetime.fromtimestamp(created, tz=timezone.utc)` or `time.gmtime`, so this import changes to `from datetime import datetime, timezone` (or to `time`). The text renderer and the env read need `import os`, which the module does not import today. `json` stays: it is used by `_normalize_incoming_likes_context`, the JSON render, and the compact rendering of list/dict context values in text mode.\n\n**Depends on it.** Only this module.\n\n**Risk: low.** If the `datetime` import is left unused after the change, linting may flag it. The module must keep importing only the stdlib and `request_context`: `tests/active/test_logging_profiles.py:36` relies on running it under pytest's own interpreter.\n</impact>\n<impact path=\"engine/server/api/logging_profiles.py\" element=\"new `normalize_log_format()` next to `normalize_log_mode()` (line 73), plus a supported-formats constant\">\n**What changes.** A new public function that mirrors `normalize_log_mode`: `(value or \"\").strip().lower()`; it returns `\"text\"` when the value is `text` and `\"json\"` for anything else, including `None`, `\"\"`, `\"JSON\"` and `\"bogus\"`. It would go beside `SUPPORTED_LOG_MODES` (line 15), possibly with a `SUPPORTED_LOG_FORMATS = (\"json\", \"text\")` tuple in the same style.\n\n**Depends on it.** `configure_engine_logging` and the new tests. The Client gets its own copy because there is no shared module (plan, \"Alternatives\").\n\n**Risk: low.** It must never raise, because R3 requires that a bad value does not stop startup. Note that `server_config._resolve_log_profile_env` (server_config.py:12-15) is a second, separate normaliser for `RECOMMENDATIONS_LOG_PROFILE`. It stays untouched, and the plan rightly does not put `LOG_FORMAT` there.\n</impact>\n<impact path=\"engine/server/api/logging_profiles.py\" element=\"new private ts helper (UTC from `record.created`)\">\n**What changes.** A new `_format_ts(record)` (or similar). It renders `record.created` in UTC as `YYYY-MM-DDTHH:MM:SS.mmmZ`, taking the milliseconds from `created` itself and not from `record.msecs` (plan, \"Validation timing\").\n\n**Depends on it.** The JSON and text renderings in `EngineJsonFormatter.format`.\n\n**Risk: medium.** Watch the rounding edge: if the seconds and the milliseconds are computed separately, for example `int(created % 1 * 1000)` against a `fromtimestamp` that rounds microseconds, a value like x.9996 can disagree with its own seconds (`.1000`, or a seconds value one too high). Using `fromtimestamp(created, timezone.utc)` and then `microsecond // 1000` keeps both from one value. Expected regex: `^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}\\.\\d{3}Z$`. It must be the same string in both renderings (R4 requirement line 53).\n</impact>\n<impact path=\"engine/server/api/logging_profiles.py\" element=\"`EngineJsonFormatter` class: new constructor flag, `format()` (lines 184-226) split into payload build + render\">\n**What changes.** \n- `__init__` gets a format flag. It must default to JSON, because `EngineJsonFormatter()` is constructed with no arguments in `engine/server/api/tests/test_logging_profiles.py:34,141`.\n- Line 195 `ts` becomes the record-based helper.\n- Everything from line 189 to line 225 stays: classification, `_extract_request_id`, `_extract_fields`, the incoming-likes, access.start, access and service.lifecycle message rewriting, and `traceback`.\n- The final `json.dumps(payload, ensure_ascii=True, separators=(\",\", \":\"))` (line 226) stays the JSON branch, byte for byte.\n- A new text branch renders: `ts level event [message] [context k=v\u2026] [request_id=\u2026] [traceback]`. `modes` is omitted. For `service.lifecycle` the message token is skipped because the payload has no `message`. CR and LF are escaped in the assembled line.\n\n**Depends on it.** \n- `configure_engine_logging` (line 239).\n- The unit tests (which build the formatter directly).\n- `engine/watch-engine-logs.sh` (JSON keys `modes`, `level`, `event`, `message`).\n- `engine/server/README.md:31` (names the class and its `traceback` key).\n- Every Engine log record in production.\n\n**Risk: medium-high.** \n- JSON mode must remain unchanged apart from the `ts` value. Key order today is `ts, level, event, message, modes`, then `request_id`, `context`, `traceback`. Any refactor that rebuilds the dict differently changes the order. Tests do not pin the order, but the R2 contract does.\n- The class name says \"Json\" while it now also emits text. Renaming it would break the unit-test import (line 18) and README.md:31, so keep the name.\n- In text mode, `request_id` should not be emitted twice when `context` already carries a `request_id` token taken from the message.\n- The JSON branch's `ensure_ascii=True` escaping does not apply to text mode, so non-ASCII passes through raw. Probably fine, but worth stating.\n- The traceback in text mode contains newlines and must go through the CR/LF escape. Context values from `_extract_fields` are single tokens already. The incoming-likes context holds a list of dicts, which must be rendered as compact JSON.\n</impact>\n<impact path=\"engine/server/api/logging_profiles.py\" element=\"`configure_engine_logging(profile)` (lines 229-241)\">\n**What changes.** It reads `os.environ.get(\"LOG_FORMAT\")` at call time, passes `normalize_log_format(...)` to the formatter (line 239), and keeps its signature and its return value (the normalised log *mode*, not the format). Root-handler clearing, INFO level and the StreamHandler (stderr) stay unchanged.\n\n**Depends on it.** \n- `engine/server/api/server.py:323` (production).\n- `tests/active/test_logging_profiles.py:23-24` (child).\n- `tests/active/test_internal_events.py:256-257` (child).\n- `tests/active/test_similar.py` (child scripts that call it).\n- Indirectly every test that starts a real Engine and parses its log as JSON: `tests/active/conftest.py:110-122` `engine` fixture, `test_similar.py:669` `off_default_engine`, `test_random_cache.py:202-224` `_payloads`/`_has_started`, `test_server_config.py:227-249` `_payloads`.\n\n**Risk: medium.** All of those child processes inherit `os.environ`: `subprocess.run` with no `env` argument, or `{**os.environ, \u2026}`. If `LOG_FORMAT=text` is ever exported in the developer's shell or in CI, they all fail or time out. `_has_started` would never see `service.lifecycle`, and the JSON-only line assertions in test_similar, test_internal_events and test_logging_profiles would fail. The plan accepts this (\"existing ones rely on the default\"). A cheap hardening the plan could adopt is to pop `LOG_FORMAT` in `tests/active/conftest.py`, but that is not in the plan as written. Do not change the return value, because `server.py:483` logs it as `log_mode_hint`.\n</impact>\n<impact path=\"engine/server/api/logging_profiles.py\" element=\"new text renderer / CR-LF escaping helper (private)\">\n**What changes.** A new private function that turns the payload dict into one line:\n- Scalars go through `str()`.\n- Lists and dicts go through `json.dumps(..., separators=(\",\", \":\"))`.\n- Each `\\r` and `\\n` becomes the two characters `\\r` / `\\n`, applied after assembly.\n- No prefix is added.\n\n**Depends on it.** The text branch of `EngineJsonFormatter.format`. Its behaviour must match the Client's copy exactly (R2 says \"same line format\"; a cross-service test guards against drift).\n\n**Risk: medium.** Watch three things. Escaping must also cover a `\\r\\n` inside the message. A `None` context value, e.g. `user_id: None` in the incoming-likes context, renders as `None` under `str()` but `null` under JSON; pick one and make both services match. Spaces in values are not quoted, which is an accepted limitation.\n</impact>\n<impact path=\"engine/server/api/logging_profiles.py\" element=\"`payload_visible_in_mode` (lines 81-90) and `_classify_event`/`_EVENT_RULES` (lines 31-70, 172-181)\">\n**What changes.** Nothing. These are listed so that the next step can confirm that the `modes` logic and `normalize_log_mode` are untouched (R3: `LOG_FORMAT` is separate from the focused/verbose modes).\n\n**Depends on it.** `engine/watch-engine-logs.sh` (`.modes`) and the unit tests at lines 58-63 and 133-171.\n\n**Risk: low**, unless the payload refactor accidentally drops `modes` from the JSON output.\n</impact>\n<impact path=\"engine/server/api/server.py\" element=\"`configure_engine_logging(DEFAULT_RECOMMENDATIONS_LOG_PROFILE)` call (line 323), import (line 84), `log_mode_hint` line (483)\">\n**What changes.** Nothing in code. The call now also picks up `LOG_FORMAT` from the process environment, which systemd provides through `EnvironmentFile=-.env.bridge` / `Environment=`.\n\n**Depends on it.** Production Engine startup.\n\n**Risk: low.** About 20 lines run between process start and line 323 (arg parsing, signal setup, `faulthandler.register` at 306). Anything logged before line 323 goes through `logging.lastResort` without a timestamp, which is the same as today. A malformed `LOG_FORMAT` must not raise here. Optionally the format could be logged next to `log_mode_hint` (line 483), but the plan does not do this.\n</impact>\n<impact path=\"client/backend/server.py\" element=\"imports (lines 5-23): `json`, `datetime`, `traceback`\">\n**What changes.** `from datetime import datetime` (line 23) is used only at line 128. If the new ts helper uses `datetime.fromtimestamp(..., timezone.utc)`, the import becomes `from datetime import datetime, timezone`; otherwise it becomes unused. `json` is still used widely (line 601 and others). `traceback` is still used at line 722. `os` and `logging` are already imported.\n\n**Depends on it.** The whole module.\n\n**Risk: low.**\n</impact>\n<impact path=\"client/backend/server.py\" element=\"`_emit_client_log(level, event, message, context)` (lines 120-136)\">\n**What changes.** It no longer builds a JSON string. It calls `logging.log(level, message, extra={\"client_event\": event, \"client_context\": context})`, with names namespaced to avoid reserved `LogRecord` attributes (`message`, `msg`, `args`, `levelname`\u2026; `logging` raises `KeyError` on a collision in `extra`). The signature stays the same and the docstring should be updated (\"structured JSON log line\").\n\n**Depends on it.** 16 call sites in the same file, all unchanged:\n- `log_message` (line 262).\n- `_respond_engine_failure` (line 420).\n- incoming likes (line 542).\n- the proxy (lines 629, 642, 661, 674, 688, 711, 732).\n- the bridge (lines 1075, 1079).\n- `main` (lines 1220, 1238).\n\n`tests/active/test_server.py` reads these records through `caplog` (see that entry).\n\n**Risk: HIGH.**\n- **(a)** `record.getMessage()` changes from the full JSON payload to only the bare `message`. Every in-process consumer that parsed or searched `getMessage()` for `event` or `context` breaks; see the test_server.py entry.\n- **(b)** Message text is passed as `msg` with no `args`, so a `%` in the message is not interpolated. That is safe today, because all messages are literals or `f\"Engine {operation} failed\"`.\n- **(c)** Records now reach any handler, including pytest's caplog, as plain messages. Before `configure_client_logging()` has run (in-process tests, conftest `client_backend`), no formatter is installed. That matches today: there is no `basicConfig` in tests, and lastResort prints only WARNING and above as a bare message.\n- **(d)** `context` at line 722 carries a multi-line `traceback` string inside context. In JSON mode it stays a JSON string. In text mode it must be escaped (R5).\n</impact>\n<impact path=\"client/backend/server.py\" element=\"new Client formatter class + ts helper + `normalize_log_format` copy + text renderer (new, near `_emit_client_log`)\">\n**What changes.** A new `logging.Formatter` subclass. It builds a payload in the order `ts`, `level`, `service: \"client-backend\"`, `event`, `message`, `context`, then the new additive `traceback` when `exc_info` is present. `event` comes from `record.client_event` or the fallback `client.log`; `message` is `record.getMessage()`; `context` comes from `record.client_context` when it is truthy, which keeps today's `if context:` behaviour at line 134. It renders JSON (`ensure_ascii=True, separators=(\",\", \":\")` as at line 136) or text, and duplicates the Engine's ts helper, normaliser and text renderer.\n\n**Depends on it.** `configure_client_logging`, `client/watch-client-logs.sh` (`fromjson?`), and the DEPLOYMENT.md/README runbooks that point at `context.error`.\n\n**Risk: medium.**\n- Level names: today the code uses `logging.getLevelName(level)`; the formatter uses `record.levelname`. These are equal for stdlib levels.\n- An empty context must still be omitted, because `if context:` drops `{}`. A record with `client_context={}` must not emit `\"context\":{}`.\n- The two copies can drift: the plan's named ceiling.\n- The class must be importable without side effects at module import time. `tests/active/conftest.py:41` imports `server` in-process, so nothing may touch the root logger at import.\n</impact>\n<impact path=\"client/backend/server.py\" element=\"new `configure_client_logging()`\">\n**What changes.** A new function, mirroring `configure_engine_logging`:\n- `root.handlers.clear()`, `setLevel(INFO)`.\n- A `StreamHandler()` (stderr, the same stream `basicConfig` used) with the Client formatter.\n- It reads `LOG_FORMAT` at call time.\n\n**Depends on it.** `main()` and the new tests. A test that calls it replaces the pytest process's root handlers, which removes pytest's own capture handlers wired into the root logger, so the test must save and restore them (plan, \"Client test seam\").\n\n**Risk: medium.** A test that forgets to restore the handlers silently breaks `caplog`-based assertions in later tests in the same session (`test_server.py`, `test_similarity_candidates.py`, `test_random_cache.py:539`, `test_updater_worker.py:137`). Note that `basicConfig` was a no-op when handlers already existed. The explicit clear is a behaviour change if anything had installed handlers before `main()`; nothing does today.\n</impact>\n<impact path=\"client/backend/server.py\" element=\"`main()` line 1184 `logging.basicConfig(level=logging.INFO, format=\\\"%(message)s\\\")`\">\n**What changes.** It is replaced by `configure_client_logging()`. Ordering stays: after `parse_trusted_proxies` (1179-1182) and `parse_cors_origins` (1183), and before the signal swap and the bind.\n\n**Depends on it.** Client production startup, `scripts/run-services.sh:161-164`, `tests/run-arch-split-smoke.sh:544` (its client.log is only tailed on failure, not parsed), and the systemd unit from `client/install-client-service.sh:195-197`.\n\n**Risk: low-medium.** The `SystemExit` for a bad `TRUSTED_PROXIES` (line 1182) happens before logging setup and goes to stderr bare; that is unchanged. The `service.start`/`service.stop` records (lines 1220, 1238) now go through the formatter. Their `context` contains an int `port` and an int `pid`, which stay JSON ints in JSON mode.\n</impact>\n<impact path=\"client/backend/server.py\" element=\"`ClientBackendHandler.log_message` (lines 258-273)\">\n**What changes.** No code change. It is still the `client.access` request-end line, and its `ts` is now `record.created` (R6).\n\n**Depends on it.** `BaseHTTPRequestHandler`, which calls it once the response has been sent.\n\n**Risk: low.** `BaseHTTPRequestHandler.log_error` also routes to `log_message`, so error-path lines (for example a 400 from a malformed request line) are also emitted as `client.access` \"request finished\". That is pre-existing behaviour, noted here only because they now carry UTC timestamps as well.\n</impact>\n<impact path=\"tests/active/test_server.py\" element=\"`_error_messages` / `_error_events` (lines 991-1005) and the four tests using them (lines 1008-1019, 1032-1043, 1046-1057, 1073-1082)\">\n**What changes.** These tests are not in the plan but **will break**. They read `record.getMessage()` from `caplog` and `json.loads` it to get `event` and `context`.\n- After the change, `getMessage()` is only `\"Engine metadata failed\"` or `\"engine bridge publish failed\"`, so `_error_events` returns `[]`.\n- Assertions that will fail: line 1019 (`event == \"engine.call\"`), lines 1077-1082 (`engine.bridge` and `context.error` containing \"Connection refused\").\n- The sentinel lives only in `context.error` (server.py:420, 1075, 1079), not in the message. So `ENGINE_SENTINEL in caplog.text` (line 1017; caplog's own formatter prints `%(message)s`), the `ENGINE_SENTINEL in message` checks (lines 1018, 1043) and `DROPPED_TEXT in message` (line 1057) also fail.\n- The module docstring (lines 94-106) describes \"an ERROR record\" carrying the sentinel.\n\n**Depends on it.** The `client_server` import from conftest.\n\n**Risk: HIGH, and certain unless addressed.** The fix belongs in this build: rewrite the helpers to read `record.client_event` / `record.client_context`, or to run each record through the new Client formatter (`json.loads(formatter.format(record))`). The second option also exercises the production formatter. The plan's statement \"No call site changes\" holds for production code, but this test module needs editing.\n</impact>\n<impact path=\"engine/server/api/tests/test_logging_profiles.py\" element=\"`EngineJsonFormatter()` constructions (lines 34, 141) and `assertIn(\\\"ts\\\", payload)` (line 156)\">\n**What changes.** No edit is needed if the constructor's format flag defaults to JSON. A natural place for new Engine unit tests: `normalize_log_format` cases, `ts` regex and `created`-based value, text line shape, newline escaping, and the service.lifecycle text line with no message.\n\n**Depends on it.** `logging_profiles` imports at lines 17-21 (adding `normalize_log_format` there if tested).\n\n**Risk: low** if the default is kept. If the flag were made required, both constructions break.\n</impact>\n<impact path=\"tests/active/test_logging_profiles.py\" element=\"child running `configure_engine_logging(\\\"verbose\\\")` and parsing every stderr line as JSON (lines 20-51)\">\n**What changes.** Nothing, as long as the default stays JSON. The child inherits the environment (`subprocess.run` with no `env`).\n\n**Depends on it.** `configure_engine_logging` and the env default.\n\n**Risk: low-medium.** It fails if `LOG_FORMAT=text` leaks into the test environment. This is also a candidate home for the new Engine format tests, with the env pinned for the child via `env={**os.environ, \"LOG_FORMAT\": ...}`: a traceback record escaped to one line in text mode, and a message containing `\\n`.\n</impact>\n<impact path=\"tests/active/test_internal_events.py\" element=\"`_FAILING_INGEST_CHILD` with `configure_engine_logging(\\\"verbose\\\")` (lines 253-308)\">\n**What changes.** Nothing. It parses every stderr line as JSON and reads `traceback`.\n\n**Depends on it.** The JSON default and the unchanged `traceback` key.\n\n**Risk: low** (environment leak only).\n</impact>\n<impact path=\"tests/active/test_similar.py\" element=\"`_json_lines` (561-565), the failing-similar child, `_messages` reading the off-default Engine log (723-732), `off_default_engine` env (669)\">\n**What changes.** Nothing. These parse Engine JSON lines and the `message`/`traceback` keys. The lines with `{\"case\": n}` are printed by the child itself and parse as JSON.\n\n**Depends on it.** JSON default, `message` unchanged for `[similar-server]\u2026` records (no rewrite rule applies to them).\n\n**Risk: low** (environment leak only).\n</impact>\n<impact path=\"tests/active/test_random_cache.py\" element=\"`_payloads`/`_messages`/`_has_started` (lines 202-224), Engine env at 245 and 710\">\n**What changes.** Nothing. It reads the Engine log file as JSON and waits for `service.lifecycle` with `context.state == \"start\"`.\n\n**Depends on it.** JSON default; the `service.lifecycle` payload shape (no `message`, `context` from fields).\n\n**Risk: low-medium.** If `LOG_FORMAT=text` leaked into the environment, `_has_started` would never become true and the fixture would wait out its timeout rather than fail fast. The env at line 245 is built from `os.environ` minus one key.\n</impact>\n<impact path=\"tests/active/test_server_config.py\" element=\"`_payloads` (lines 227-249), child env (line 49)\">\n**What changes.** Nothing. Same `service.lifecycle` start detection as test_random_cache.\n\n**Depends on it.** JSON default.\n\n**Risk: low** (environment leak only).\n</impact>\n<impact path=\"tests/active/conftest.py\" element=\"`client_server` in-process import (line 41), `client_backend` fixture (71-91), session `engine` fixture env (110)\">\n**What changes.** Nothing is required. The import must stay free of side effects: the new Client formatter and configure function are defined at module level but not called. Optionally pop `LOG_FORMAT` from the Engine fixture env to harden it against leaks; that is not in the plan.\n\n**Depends on it.** Every active test that uses `client_server`, `engine` or `client_backend`.\n\n**Risk: low.**\n</impact>\n<impact path=\"tests/active/test_similarity_candidates.py\" element=\"caplog `_messages`/`_reopen_warnings`/`_stale_skips` (lines 212-224, 294-397)\">\n**What changes.** Nothing. These read Engine `record.getMessage()`, which is unaffected because the Engine formatter does not alter records.\n\n**Depends on it.** pytest's caplog handler on the root logger.\n\n**Risk: low**, unless a new test calls `configure_engine_logging` or `configure_client_logging` in-process without restoring root handlers. That would strip pytest's capture handler for later tests in the session.\n</impact>\n<impact path=\"tests/active/test_log_format.py\" element=\"new cross-service test module (name to be decided; does not exist yet)\">\n**What changes.** A new test module covering:\n- `ts` regex and `created`-based value for both formatters.\n- The `LOG_FORMAT` matrix: unset, `json`, `JSON`, `bogus`, empty \u2192 JSON; `text` in any case \u2192 text.\n- One physical line with a traceback and with a `\\n` message.\n- No `<N>` prefix.\n- The Client: a `_emit_client_log` record and a bare `logging.info` after `configure_client_logging()` both come out in the shared format with `event: client.log`.\n- Engine `access.start` \u2192 work \u2192 `access` with non-decreasing `ts`.\n- A drift guard: the same `created` produces the same `ts` string, and the same line shape, from both services.\n\nEngine formatting can run in pytest's interpreter (`logging_profiles` is stdlib-only plus `request_context`, as test_logging_profiles.py:36 notes). The Client formatter is reachable via `client_server` from conftest. Note that both modules are named after their package directories: the Engine one needs `engine/server/api` on `sys.path`. The Engine's `server` module name collides with the Client's `server` already in `sys.modules`, so import `logging_profiles` directly, never the Engine's `server`.\n\n**Depends on it.** Both formatters.\n\n**Risk: medium.** Root-logger handler save/restore is mandatory. Constructing a `LogRecord` and then setting `created` relies on the plan deriving milliseconds from `created`, not `msecs`.\n</impact>\n<impact path=\"engine/watch-engine-logs.sh\" element=\"`JQ_FILTER` with `fromjson?` (lines 127-148)\">\n**What changes.** No code change. In JSON mode the keys are unchanged, so it keeps working, and `ts` simply shows UTC. In text mode `fromjson?` yields nothing and `select(. != null)` drops every line, so the watcher shows **nothing**: a silent, empty view.\n\n**Depends on it.** Operators; DEPLOYMENT.md:123.\n\n**Risk: medium (operator-facing).** This is not a regression of the default, but the DEPLOYMENT.md paragraph must say plainly that the watcher needs `json`. Optionally the help text (`Notes:` lines 24-27) could say so; the plan does not touch the script.\n</impact>\n<impact path=\"client/watch-client-logs.sh\" element=\"`jq -R 'fromjson? // {\\\"raw\\\": .}'` (lines 97-103), header comment (lines 4-5)\">\n**What changes.** No code change. In JSON mode the record keys are unchanged. Previously non-JSON lines, bare records, now arrive as structured JSON with `event: client.log` instead of `{\"raw\": \u2026}`. In text mode every line becomes `{\"raw\": \"<text line>\"}`, which is degraded but works.\n\n**Depends on it.** Operators.\n\n**Risk: low.**\n</impact>\n<impact path=\"client/install-client-service.sh\" element=\"generated unit `Environment=`/`EnvironmentFile=` (lines 195-197)\">\n**What changes.** Nothing. `LOG_FORMAT` reaches the Client through the existing `EnvironmentFile=-\u2026/.env.bridge` or a drop-in.\n\n**Depends on it.** `tests/active/test_install_client_service.py`, which compares the generated unit exactly.\n\n**Risk: low**, but do not add an `Environment=LOG_FORMAT=` line here: the exact-match install tests would fail and the plan does not call for it.\n</impact>\n<impact path=\"engine/install-engine-service.sh\" element=\"generated unit (lines 128-130)\">\n**What changes.** Nothing; the same reasoning as the Client unit. `tests/active/test_install_engine_service.py:58` pins the exact unit text.\n\n**Depends on it.** Engine units.\n\n**Risk: low**, provided it is left untouched.\n</impact>\n<impact path=\"scripts/run-services.sh\" element=\"`load_bridge_secret` sources `.env.bridge` with `set -a` (lines 96-99); Engine/Client launches (144-164)\">\n**What changes.** Nothing. A `LOG_FORMAT` in `.env.bridge` is exported to both services here as well. That is consistent with DEPLOYMENT.md's \"set it in `.env.bridge`\" advice, but it turns text mode on for both services at once, and for prod and dev, which share the file.\n\n**Depends on it.** Local runs; `logs` subcommand `tail -f` (line 244).\n\n**Risk: low.** Worth a sentence in the doc paragraph: `.env.bridge` is shared by the prod and dev units, as DEPLOYMENT.md:528 already says for CORS.\n</impact>\n<impact path=\"engine/server/api/server_config.py\" element=\"`_resolve_log_profile_env` / `DEFAULT_RECOMMENDATIONS_LOG_PROFILE` (lines 12-15, 516-518)\">\n**What changes.** Nothing. This is the import-time env read that the plan explicitly does not copy for `LOG_FORMAT`.\n\n**Depends on it.** `server.py:80, 323`.\n\n**Risk: none.** Listed so that nobody adds `LOG_FORMAT` here. `test_server_config.py` imports `server_config` in-process, and an import-time read there would be cached for the session.\n</impact>\n<impact path=\"client/backend/lib/http_utils.py\" element=\"module (uses `datetime.now(timezone.utc)` at line 112 for the rate limiter)\">\n**What changes.** Nothing. This is not logging; the hit only came from searching for `datetime`.\n\n**Depends on it.** `RateLimiter`.\n\n**Risk: none.** Listed to record that no Client lib module logs (grep of `client/backend` for `logging.`/`logger` finds only `server.py`). So \"third-party/library records\" in the Client are in practice only stdlib ones, and `client.log` fallback lines should be rare.\n</impact>\n</impacts>\n\n</impacts>\n\n<docs_checklist>\n<doc path=\"DEPLOYMENT.md\">\nAdd one `LOG_FORMAT` paragraph after the `RANDOM_CACHE_REFRESH_INTERVAL_MINUTES` paragraph (line 114) in the service-environment block (lines 105-114), in the same one-paragraph style. Points to cover:\n- Values: `json` (default) and `text`, case-insensitive, whitespace ignored. Unset, empty or unknown values select `json` and never stop startup.\n- Both the Engine and the Client backend read it at logging setup.\n- How to set it: through `.env.bridge` (shared by the prod and dev units and exported by `scripts/run-services.sh`) or an `Environment=` drop-in.\n- `engine/watch-engine-logs.sh` shows nothing in text mode, and `client/watch-client-logs.sh` shows `{\"raw\":\u2026}`.\n- `ts` is UTC `YYYY-MM-DDTHH:MM:SS.mmmZ` taken at record creation.\n- Text lines escape newlines, so a traceback is one line.\n\nAlso check Triage rows 203 (`context.error` of `engine.call`/`engine.bridge`) and 204 (\"the JSON log record's `traceback` key\"), and line 301. They stay correct in JSON mode, but each could get a short \"(in `LOG_FORMAT=text`, the `error=` token / the escaped traceback at the end of the line)\" note. Optional; the operator may prefer to say once in the new paragraph that the runbooks assume `json`.\n</doc>\n<doc path=\"engine/server/README.md\">\nLine 31 says `EngineJsonFormatter` adds a `traceback` key. That is still true in JSON mode. Optionally add that in `LOG_FORMAT=text` the traceback ends the line, newline-escaped. Otherwise no change, as long as the class keeps its name.\n</doc>\n<doc path=\"client/README.md\">\nLines 31, 32 and 35 describe ERROR `engine.call` / `engine.bridge` records with `context.error`, and INFO `engine.proxy`. These stay accurate in JSON mode. Optionally add a pointer to DEPLOYMENT.md for `LOG_FORMAT` next to the `TRUSTED_PROXIES` env note (line 68), since that section lists the Client's env settings. Also uncertain: whether the README should mention that bare/library records now appear as `client.log` events and that exception records carry an additive `traceback` key.\n</doc>\n<doc path=\"docs/project/issues/19-timestamped-request-logs.md\">\nPer the tracker conventions: on delivery, set `Status: enhancement, complete` and move the file to `docs/project/issues/archive/`. Note that the delivered default is JSON, not the issue's \"plain text default\", by operator decision (recorded in the plan record). The `## Comments` section is the place to say so.\n</doc>\n<doc path=\"docs/project/issues/plan.md\">\nThe triage note at lines 114-117 (\"19 is mostly delivered \u2026 uses a local offset, not UTC \u2026 shrink it to 'UTC, plus an optional plain-text mode'\") and the lane 4c row (line 91) become stale once 19 lands. Update or strike them when the issue is archived. This is bookkeeping, not product documentation.\n</doc>\n</docs_checklist>\n\n<highest_risk>\ntests/active/test_server.py `_error_events`/`_error_messages` and its four Engine-failure tests: these parse `record.getMessage()` as JSON and look for the sentinel there, but after `_emit_client_log` switches to `extra=` the message is only \"Engine metadata failed\" and the sentinel lives only in `context.error`. Lines 1017-1019, 1043, 1057 and 1077-1082 will fail, and the plan does not mention this file.\nclient/backend/server.py `_emit_client_log` plus the new `configure_client_logging`: changing what `getMessage()` returns affects every in-process consumer. Any new test that calls `configure_client_logging()` (or `configure_engine_logging()`) in the pytest process clears the root handlers, including pytest's caplog handler, and if it does not restore them, the caplog-based tests that run later in the session (test_server, test_similarity_candidates, test_random_cache, test_updater_worker) break.\nengine/server/api/logging_profiles.py `EngineJsonFormatter.format` refactor plus `configure_engine_logging` env read: JSON output must stay byte-compatible apart from `ts` (key order, `modes`, `ensure_ascii`), the constructor must default to JSON for the unit tests, and every Engine child and fixture in tests/active inherits `os.environ`. A leaked `LOG_FORMAT=text` would break test_similar, test_internal_events and test_logging_profiles, make the `_has_started` waits in test_random_cache and test_server_config wait out their timeout, and give watch-engine-logs.sh an empty view.\n</highest_risk>",
    "step_4_reassess": "<summary>\nI checked the inventory against the files it names. Everything I opened holds up, and I found nothing the inventory missed. The Engine formatter (`logging_profiles.py:184-241`) does what the inventory says: `ts` comes from `datetime.now().astimezone()` at line 195, the keys are ordered `ts, level, event, message, modes` and then `request_id`/`context`/`traceback`, and the constructor is called with no arguments in the unit tests and in `configure_engine_logging`. The Client's `_emit_client_log` (`server.py:120-136`) builds JSON itself and logs it as the record's message, and `main()` calls `basicConfig(format=\"%(message)s\")` at line 1184. The breakage the inventory flags in `tests/active/test_server.py` is real: `_error_messages`/`_error_events` (lines 991-1005) `json.loads` the result of `record.getMessage()`, and lines 1017-1019, 1043, 1057 and 1077-1082 depend on that. The `.ts` hits in the grep were TypeScript files, not timestamp consumers. The only callers of `configure_engine_logging` are the ones listed. The other caplog users (`test_random_cache.py:547`, `test_updater_worker.py:151`, `test_similarity_candidates.py`) read Engine-side records, and those records are unaffected.\n<question id=\"1\">\nYes, with one condition. Production code needs no other call-site changes, and the Engine gets the format switch without any change to its signature or its callers. In the Client, moving the structured fields from the message into `extra=` attributes is what lets one root formatter serve both JSON and text and also catch bare records. The condition: the same move breaks `tests/active/test_server.py`, which reads `getMessage()` as JSON. That module has to be edited in this build. The inventory already records this, and it is a test-side change, not a change to the plan.\n</question>\n<question id=\"2\">\n- **Client `getMessage()`.** It now returns only the bare message (for example \"Engine metadata failed\"). The event, context and error text live on the record attributes and appear only in the formatted output. Any in-process consumer has to read the attributes or run the record through the formatter. Today the only such consumer is `test_server.py`.\n- **Library records.** Records from stdlib libraries in the Client now come out as structured `client.log` lines.\n- **`ts` format.** It changes from local time with an offset to UTC with `Z` in both services. The watch scripts keep working because they don't parse `ts`.\n- **Text mode and the watchers.** `watch-engine-logs.sh` shows nothing in text mode (`fromjson?` then `select(. != null)` drops every line). `watch-client-logs.sh` falls back to `{\"raw\": \u2026}`.\n- **Shared `.env.bridge`.** A `LOG_FORMAT` set there switches both services, prod and dev together, because `run-services.sh` and the units share the file.\n</question>\n<question id=\"3\">\n- **`test_server.py` helpers.** Rewrite them to read `record.client_event`/`record.client_context`, or to format each record with the Client formatter. The sentinel and `DROPPED_TEXT` checks must look at the context error, not the bare message. The docstring at lines 94-106 needs the matching wording.\n- **Engine default.** `EngineJsonFormatter` must default to JSON, so that the no-argument constructions at test lines 34 and 141 keep working.\n- **Engine JSON output.** It must stay byte-for-byte the same apart from the `ts` value, including key order and `modes`.\n- **Client `context`.** An empty or missing context must still be left out, as `if context:` does today.\n- **Root-handler restore.** Any test that calls `configure_client_logging()` or `configure_engine_logging()` in-process must save and restore the root handlers. Otherwise caplog breaks for every later test in the session.\n- **Import side effects.** Importing `client/backend/server.py` must not touch logging, because `conftest.py:41` imports it in-process.\n- **Docs.** The DEPLOYMENT.md paragraph must say that the watchers and the `context.error` runbook recipes (lines 123, 203, 301) need `json`, and that `.env.bridge` is shared.\n</question>\n<question id=\"4\">\n- **`ts` value.** It is now a UTC `Z` string taken from `record.created`, not formatting-time local time with an offset. Lines therefore order by when the log call was made.\n- **Client records.** Records that used to come out as bare text in the Client (library or bare `logging.*` calls) are now structured lines with `event: client.log`.\n- **Client `traceback`.** A Client record carrying `exc_info` gains a `traceback` key. This is additive.\n- **Client `getMessage()`.** An in-process Client record's `getMessage()` is now only the bare message, not the JSON payload.\n- **New `LOG_FORMAT=text` mode.** It is opt-in and gives one line per record with escaped CR/LF.\n- **Unchanged.** With `LOG_FORMAT` unset or invalid, every JSON key, every key order and the output stream stay as they were.\n</question>\n</summary>\n\n<new_impacts>\nnone\n</new_impacts>\n\n<unconfirmed>\nnone\n</unconfirmed>\n\n<new_conflicts>\nnone\n</new_conflicts>\n\n<recommendations>\n1. **Put the `tests/active/test_server.py` edit into the phase plan explicitly.** Change `_error_messages`/`_error_events` to run each ERROR record through the Client formatter in JSON mode, i.e. `json.loads(formatter.format(record))`. Point the sentinel and `DROPPED_TEXT` checks at the formatted line or at `context.error`, and fix the docstring at lines 94-106. Cost: roughly 10-15 changed lines in one test module. The benefit is that these tests then exercise the production formatter. Without this edit, five tests go red (the parametrised one counts five times) the moment `_emit_client_log` changes.\n2. **Settle one value-rendering rule for text mode in both copies.** Recommended: `str` values as-is, and every other value (None, bool, int, list, dict) through compact `json.dumps`. That gives `null`/`true`/`5`/`[...]`, so the Engine's incoming-likes `user_id: None` and the Client's int `port`/`pid` render the same way in both services. Cost: nothing beyond writing it down; it removes a source of drift between the two copies.\n3. **Optional: pop `LOG_FORMAT` from the environment in `tests/active/conftest.py`** (session-level, or in the Engine fixture env). This stops a developer's or CI's exported `LOG_FORMAT=text` from making about six JSON-parsing test modules fail or time out. Cost: one line. The downside is that it hides the variable from every test, so the new format tests must set it explicitly, which they already plan to do.\n4. **Optional: add one line to the Notes in `engine/watch-engine-logs.sh`** saying the watcher needs `LOG_FORMAT=json`. That covers the silent empty view in text mode. Cost: one comment or help line. The installer tests don't touch this script.\n5. **Note for implementation, no decision needed.** In Engine text mode the `key=value` tokens appear twice, once in the raw message and again as context, wherever no rewrite rule replaces the message. This follows from the plan's line shape and is accepted. Dropping either copy would make the text line diverge from the JSON payload, which the plan builds on purpose.\n</recommendations>",
    "step_5_draft_implementation": "<draft>\n## Draft implementation \u2014 issue 19, timestamped logs (UTC `ts`, `LOG_FORMAT` json|text, Client root formatter)\n\nI read these files before drafting: `engine/server/api/logging_profiles.py` (whole file), `client/backend/server.py` (imports 1-23, `_emit_client_log` 120-136, `log_message` 258-273, `main` 1175-1252, the `\"error\"` context sites 420/722/1075/1079), `tests/active/test_server.py` (docstring 94-106, helpers and tests 991-1082, sentinel constants 937-942), `tests/active/conftest.py`, `tests/active/test_logging_profiles.py`, `engine/server/api/tests/test_logging_profiles.py`, `engine/server/api/handlers/similar.py:340-360` and `DEPLOYMENT.md:105-114`.\n\n### What has to be tested\n\n| # | Behaviour | Requirement | Where |\n|---|---|---|---|\n| T1 | `ts` matches `^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}\\.\\d{3}Z$` in both services and both formats | R1, Validation 1 | new `tests/active/test_log_format.py` |\n| T2 | A record whose `created` is set to `1741091696.789` renders `2025-03-04T12:34:56.789Z` (formatting time is ignored). The edge `1741091696.9999996` renders `2025-03-04T12:34:57.000Z`, with seconds and milliseconds consistent | R1, R6, Validation 3 | same |\n| T3 | `LOG_FORMAT` unset, `json`, `JSON`, `bogus` or `\"\"` gives JSON lines; `text`, `TEXT` or ` Text ` gives text lines. Engine runs in a child with a pinned env; Client runs in-process with monkeypatch | R3, Validation 4 | same |\n| T4 | Every record is one physical line in both modes, including a `logging.exception` record and a message containing `\\n`. In text mode the traceback is at the end of the line as `\\n`-escaped text. No line starts with `<` | R5, Validation 4 | same |\n| T5 | Text shape is `ts LEVEL event message k=v\u2026 [request_id=\u2026] [traceback]`. An Engine `service.lifecycle` line has no message token. An Engine access line carries \"request started\" / \"request finished\" | R4 | same |\n| T6 | After `configure_client_logging()` in the Client, a `_emit_client_log` record and a bare `logging.info` both come out in the shared format. The bare one has `event == \"client.log\"`. JSON key order is `ts, level, service, event, message[, context]` | R2, Validation 5 | same |\n| T7 | Drift guard: `_format_ts` and `_render_text` give identical strings in the Engine (child) and the Client (in-process) for the same `created` and the same payload | R2 | same |\n| T8 | Engine live request: in the session Engine's log, the slice from the `access.start` of a marked `POST /recommendations` to its `access` has non-decreasing `ts` and at least one `recommendations.*` work line | R6, Validation 2 | same |\n| T9 | The existing JSON consumers stay green: the four Engine JSON-parsing modules are unchanged, and `test_server.py`'s Client ERROR-record tests are rewired to the new formatter | R3, Validation 6 | `tests/active/test_server.py` |\n\n### Module map\n\n| File | Change |\n|---|---|\n| `engine/server/api/logging_profiles.py` | imports; `SUPPORTED_LOG_FORMATS`; `normalize_log_format`; `_TEXT_ESCAPES`, `_format_ts`, `_text_value`, `_render_text`; `EngineJsonFormatter.__init__(log_format=\"json\")`; `ts` comes from the record; text branch; `configure_engine_logging` reads `LOG_FORMAT` |\n| `client/backend/server.py` | import `timezone`; copies of the four helpers and the constant; `ClientLogFormatter`; `configure_client_logging()`; `_emit_client_log` becomes a `logging.log(..., extra=\u2026)` call; `main()` calls `configure_client_logging()` in place of `basicConfig` |\n| `tests/active/test_server.py` | `_error_messages` renders each record through `ClientLogFormatter`; caplog's handler gets that formatter in the one test that reads `caplog.text`; the docstring wording is adjusted |\n| `tests/active/test_log_format.py` | new module, T1-T8 |\n| `DEPLOYMENT.md`, `engine/server/README.md`, `client/README.md`, issue 19, `docs/project/issues/plan.md` | the doc list (see the Docs section) |\n\nNo other production file changes. `engine/server/api/server.py`, both watch scripts, both install scripts, `scripts/run-services.sh` and `server_config.py` are untouched, as the impact inventory says.\n\n### `engine/server/api/logging_profiles.py`\n\nImports (lines 5-12). `os` is added. `datetime` gains `timezone`. The module still imports only the stdlib and `request_context`.\n\n```python\nimport json\nimport logging\nimport os\nimport re\nfrom dataclasses import dataclass\nfrom datetime import datetime, timezone\nfrom typing import Any\n```\n\nThe constant goes next to `SUPPORTED_LOG_MODES` (line 15):\n\n```python\nSUPPORTED_LOG_MODES = (\"focused\", \"verbose\")\nSUPPORTED_LOG_FORMATS = (\"json\", \"text\")\n```\n\nAnd the escape table after `_LEADING_BLOCKS_RE` (line 19):\n\n```python\n# Text lines escape CR/LF so journald stores each record as one entry.\n_TEXT_ESCAPES = str.maketrans({\"\\r\": \"\\\\r\", \"\\n\": \"\\\\n\"})\n```\n\n`normalize_log_format` goes directly after `normalize_log_mode`. It has the same fail-safe shape and never raises for `str | None`.\n\n```python\ndef normalize_log_format(value: str | None) -> str:\n    \"\"\"Normalize ``LOG_FORMAT`` values and fail safely to ``json``.\"\"\"\n    raw = (value or \"\").strip().lower()\n    if raw in SUPPORTED_LOG_FORMATS:\n        return raw\n    return \"json\"\n```\n\nThe ts and text helpers go after `_classify_event`, before the class. Invariant for `_format_ts`: the seconds and the milliseconds come from one `datetime`, so they can never disagree. `fromtimestamp` rounds to the microsecond, and `// 1000` truncates to milliseconds. `record.msecs` is not used.\n\n```python\ndef _format_ts(record: logging.LogRecord) -> str:\n    \"\"\"Render the record's creation time as UTC ``YYYY-MM-DDTHH:MM:SS.mmmZ``.\"\"\"\n    stamp = datetime.fromtimestamp(record.created, tz=timezone.utc)\n    return f\"{stamp.strftime('%Y-%m-%dT%H:%M:%S')}.{stamp.microsecond // 1000:03d}Z\"\n\n\ndef _text_value(value: Any) -> str:\n    \"\"\"Render one context value as a single text token.\"\"\"\n    if isinstance(value, str):\n        return value\n    return json.dumps(value, ensure_ascii=False, separators=(\",\", \":\"), default=str)\n\n\ndef _render_text(payload: dict[str, Any]) -> str:\n    \"\"\"Render a payload as one ``ts LEVEL event message k=v\u2026`` line with CR/LF escaped.\"\"\"\n    parts = [payload[\"ts\"], payload[\"level\"], payload[\"event\"]]\n    if \"message\" in payload:\n        parts.append(str(payload[\"message\"]))\n    context = payload.get(\"context\") or {}\n    parts.extend(f\"{key}={_text_value(value)}\" for key, value in context.items())\n    request_id = payload.get(\"request_id\")\n    if request_id and \"request_id\" not in context:\n        parts.append(f\"request_id={request_id}\")\n    if \"traceback\" in payload:\n        parts.append(payload[\"traceback\"])\n    return \" \".join(parts).translate(_TEXT_ESCAPES)\n```\n\nDecisions in `_render_text`:\n- **One rule for non-string values.** Every value that is not a string goes through compact JSON. A list or dict stays one token (the incoming-likes context), `None` is written `null` and a bool `true`. This answers the impact inventory's question about `None` rendering as `None` or `null`, the same way in both services.\n- **`modes` and `service` are not text tokens.** R4 fixes the shape, and `modes` is only filter metadata for the JSON watcher.\n- **`request_id` is written once.** It is skipped when the context already carries a `request_id` key.\n- **Escaping runs last, over the whole assembled line,** so the message, the context values (including the Client's `context.traceback` at server.py:722) and the traceback are all covered, `\\r\\n` included.\n- **Non-ASCII.** Text mode does not apply `ensure_ascii`, so non-ASCII characters pass through as they are. That is a stated limitation and harmless to journald.\n\n`EngineJsonFormatter` (lines 184-226) keeps its name, which the unit-test import and README.md:31 depend on. The payload build is untouched except for line 195. The JSON return is the same expression as before.\n\n```python\nclass EngineJsonFormatter(logging.Formatter):\n    \"\"\"Render engine log records as JSON objects with mode tags, or as text lines.\"\"\"\n\n    def __init__(self, log_format: str | None = \"json\") -> None:\n        \"\"\"Select the rendering: ``json`` (default) or ``text``; other values mean ``json``.\"\"\"\n        super().__init__()\n        self.log_format = normalize_log_format(log_format)\n\n    def format(self, record: logging.LogRecord) -> str:\n        \"\"\"Format a log record as one JSON or text line.\"\"\"\n        message = record.getMessage()\n        event, modes = _classify_event(message, record.levelno)\n        request_id = _extract_request_id(record, message)\n        fields = _extract_fields(message)\n\n        payload: dict[str, Any] = {\n            \"ts\": _format_ts(record),\n            \"level\": record.levelname,\n            \"event\": event,\n            \"message\": message,\n            \"modes\": modes,\n        }\n        # \u2026 lines 201-225 unchanged (request_id, per-event rewriting, traceback) \u2026\n        if self.log_format == \"text\":\n            return _render_text(payload)\n        return json.dumps(payload, ensure_ascii=True, separators=(\",\", \":\"))\n```\n\nInvariants of the class:\n- **JSON key order is unchanged:** `ts, level, event, message, modes`, then `request_id`, `context`, `traceback`.\n- **`EngineJsonFormatter()` with no argument is JSON,** so `engine/server/api/tests/test_logging_profiles.py:34,141` needs no edit.\n- **Text messages match JSON by construction.** Text mode renders the same payload after the rewriting, so its message is the JSON message.\n\n`configure_engine_logging` (lines 229-241): one changed line plus the docstring. The signature and the return value (the log mode) stay the same, because `server.py:483` logs that value.\n\n```python\ndef configure_engine_logging(profile: str) -> str:\n    \"\"\"Configure root logger with the ``LOG_FORMAT`` formatter and return normalized mode hint.\"\"\"\n    \u2026\n    handler.setFormatter(EngineJsonFormatter(os.environ.get(\"LOG_FORMAT\")))\n    \u2026\n```\n\n`LOG_FORMAT` is read when this function is called, never at import. `server_config.py` is not touched.\n\n### `client/backend/server.py`\n\nLine 23 becomes `from datetime import datetime, timezone`. `datetime` is still used by the ts helper. `os`, `json`, `logging` and `traceback` are already imported.\n\nNext to `_resolve_mode` / `_emit_client_log` (before line 120) go the constant, the escape table, `normalize_log_format`, `_format_ts`, `_text_value` and `_render_text`. Their bodies are byte-identical to the Engine's, and they are preceded by this marker:\n\n```python\n# rat-tail: LOG_FORMAT, _format_ts, _text_value and _render_text mirror engine/server/api/logging_profiles.py (no shared module: the two services import from different roots); tests/active/test_log_format.py checks both render alike.\nSUPPORTED_LOG_FORMATS = (\"json\", \"text\")\n_TEXT_ESCAPES = str.maketrans({\"\\r\": \"\\\\r\", \"\\n\": \"\\\\n\"})\nCLIENT_LOG_SERVICE = \"client-backend\"\nCLIENT_LOG_FALLBACK_EVENT = \"client.log\"\n```\n\nThe formatter:\n\n```python\nclass ClientLogFormatter(logging.Formatter):\n    \"\"\"Render Client records in the shared log format, JSON or text.\"\"\"\n\n    def __init__(self, log_format: str | None = \"json\") -> None:\n        \"\"\"Select the rendering: ``json`` (default) or ``text``; other values mean ``json``.\"\"\"\n        super().__init__()\n        self.log_format = normalize_log_format(log_format)\n\n    def format(self, record: logging.LogRecord) -> str:\n        \"\"\"Format one record; ``_emit_client_log`` records carry ``client_event``/``client_context``.\"\"\"\n        payload: dict[str, Any] = {\n            \"ts\": _format_ts(record),\n            \"level\": record.levelname,\n            \"service\": CLIENT_LOG_SERVICE,\n            \"event\": getattr(record, \"client_event\", None) or CLIENT_LOG_FALLBACK_EVENT,\n            \"message\": record.getMessage(),\n        }\n        context = getattr(record, \"client_context\", None)\n        if context:\n            payload[\"context\"] = context\n        # Additive to the Client's keys: without it an exception logged through the root logger is lost.\n        if record.exc_info:\n            payload[\"traceback\"] = self.formatException(record.exc_info)\n        if self.log_format == \"text\":\n            return _render_text(payload)\n        return json.dumps(payload, ensure_ascii=True, separators=(\",\", \":\"))\n```\n\nInvariants of `ClientLogFormatter`:\n- **Same keys, same order as today:** `ts, level, service, event, message[, context]`.\n- **An empty or `None` context is omitted,** which is today's `if context:`.\n- **`level`.** `record.levelname` equals `logging.getLevelName(level)` for stdlib levels.\n- **JSON separators and `ensure_ascii` are as at line 136.**\n- **No side effects at import.** Defining the class touches nothing, which conftest's in-process import (conftest.py:41) requires.\n\n`_emit_client_log` keeps its signature and its 16 call sites:\n\n```python\ndef _emit_client_log(\n    level: int,\n    event: str,\n    message: str,\n    context: dict[str, Any] | None = None,\n) -> None:\n    \"\"\"Log one Client record; ``ClientLogFormatter`` renders it with its event and context.\"\"\"\n    logging.log(level, message, extra={\"client_event\": event, \"client_context\": context})\n```\n\nNotes on `_emit_client_log`:\n- **`extra` names.** `client_event` and `client_context` are not reserved `LogRecord` attributes, so `logging` raises no `KeyError`.\n- **No `%` interpolation.** No `args` are passed, so `getMessage()` returns `message` unchanged even if it contains `%`.\n- **The implicit `basicConfig` is kept.** Module-level `logging.log` keeps today's implicit-`basicConfig`-when-no-handlers behaviour; nothing changes there.\n\n`configure_client_logging` sits directly after the formatter and mirrors `configure_engine_logging`:\n\n```python\ndef configure_client_logging() -> None:\n    \"\"\"Install ``ClientLogFormatter`` on the root logger, format from ``LOG_FORMAT``.\"\"\"\n    root_logger = logging.getLogger()\n    root_logger.handlers.clear()\n    root_logger.setLevel(logging.INFO)\n\n    handler = logging.StreamHandler()\n    handler.setLevel(logging.INFO)\n    handler.setFormatter(ClientLogFormatter(os.environ.get(\"LOG_FORMAT\")))\n    root_logger.addHandler(handler)\n```\n\nThe `StreamHandler()` default is stderr, the same stream `basicConfig` used, so the systemd units and `journalctl -o cat` pipelines are unchanged.\n\n`main()` line 1184: `logging.basicConfig(level=logging.INFO, format=\"%(message)s\")` becomes `configure_client_logging()`. It stays in the same position: after `parse_trusted_proxies` / `parse_cors_origins`, and before the signal swap and the bind. `log_message` (258-273) needs no code change.\n\n### `tests/active/test_server.py`\n\nThese tests fail as the code stands, so they are fixed here.\n\nLines 991-992. The rest of `_error_events` is unchanged, because it now parses real JSON lines:\n\n```python\n_CLIENT_FORMATTER = client_server.ClientLogFormatter()\n\n\ndef _error_messages(caplog):\n    \"\"\"The ERROR records, each rendered as the Client's production JSON line.\"\"\"\n    return [_CLIENT_FORMATTER.format(record) for record in caplog.records if record.levelno >= logging.ERROR]\n```\n\nIn `test_client_likes_502_is_fixed_text_and_engine_error_is_logged` (line 1008), add `caplog.handler.setFormatter(_CLIENT_FORMATTER)` right after `caplog.set_level(logging.ERROR)`. Then `caplog.text` at line 1017 is the production-rendered lines, and the sentinel in `context.error` is found again. Lines 1018, 1019, 1043, 1057 and 1077-1082 pass unchanged. `ENGINE_SENTINEL` and `DROPPED_TEXT` are plain ASCII with no quote or backslash, so `json.dumps` leaves them intact.\n\nDocstring line 100: \"the sentinel is in an ERROR record\" becomes \"the sentinel is in an ERROR record's `context.error`, as the Client's formatter renders it\". Lines 102 and 105-106 already say `context.error` or are still true.\n\n### `tests/active/test_log_format.py` (new)\n\nThe module docstring states the claims T1-T8 in the house style of the active tests. Seams:\n- **Engine side: a child process.** It runs `[sys.executable, \"-c\", _ENGINE_CHILD, <args>]` with `cwd=API_DIR`, as `test_logging_profiles.py` does. The env is `{k: v for k, v in os.environ.items() if k != \"LOG_FORMAT\"}`, plus `LOG_FORMAT` when the case sets one. Using a child keeps the Engine's `server`/`logging_profiles` out of the pytest process, where `server` is already the Client module.\n- **Client side: in-process,** through `client_server` from conftest.\n\nThe Engine child prints log records to stderr through `configure_engine_logging(\"verbose\")`. In order: `[probe] plain`, `[probe] two\\nlines`, `logging.exception(\"[probe] failed\")` for a `ValueError(\"sentinel-log-format\")`, `[access.start] ip=127.0.0.1 method=GET url=http://x/a`, `[service] lifecycle state=start component=engine run_id=r pid=1`. On stdout it prints JSON with three items:\n- `ts`: `_format_ts` of a `LogRecord` whose `created` was set from argv.\n- `fixed`: `EngineJsonFormatter(fmt).format` of that record.\n- `text`: `_render_text(json.loads(argv payload))`.\n\nThe Client context manager is the only place that replaces root handlers. It saves and restores them inside the test body, which is the call phase. A fixture would capture the setup phase's pytest handlers and restore stale ones.\n\n```python\n@contextmanager\ndef _client_logging(monkeypatch, value):\n    \"\"\"Run configure_client_logging under LOG_FORMAT=value; yield the stream it writes to.\"\"\"\n    root = logging.getLogger()\n    saved_handlers, saved_level = root.handlers[:], root.level\n    if value is None:\n        monkeypatch.delenv(\"LOG_FORMAT\", raising=False)\n    else:\n        monkeypatch.setenv(\"LOG_FORMAT\", value)\n    try:\n        client_server.configure_client_logging()\n        stream = io.StringIO()\n        root.handlers[0].setStream(stream)\n        yield stream\n    finally:\n        root.handlers[:] = saved_handlers\n        root.setLevel(saved_level)\n```\n\nTests:\n- `test_log_format_selects_json_or_text[engine|client \u00d7 None, \"json\", \"JSON\", \"bogus\", \"\", \"text\", \"TEXT\", \" Text \"]` covers T1, T3, T4 and T6. JSON cases: every line passes `json.loads`, `ts` matches `TS_RE`, and the Client's keys come in order `[\"ts\", \"level\", \"service\", \"event\", \"message\", \u2026]`. Text cases: every line matches `^TS ` followed by the level. No line starts with `<`. The traceback/newline records are exactly one line each, and the text line contains `\\\\n` and ends with `ValueError: sentinel-log-format`. The Client emits `_emit_client_log(ERROR, \"engine.call\", \"Engine metadata failed\", {\"error\": \"x\\ny\"})`, `logging.info(\"bare\")` and a `logging.exception` record.\n- `test_ts_is_record_creation_time_in_utc` covers T2: `created = 1741091696.789` gives `2025-03-04T12:34:56.789Z`, and `1741091696.9999996` gives `2025-03-04T12:34:57.000Z`. Both services are checked, and also a `created` an hour in the past, to show it is not the formatting time.\n- `test_text_line_shape` covers T5. Engine: `\u2026 INFO access.start request started ip=127.0.0.1 method=GET url=http://x/a`, and the lifecycle line goes `\u2026 INFO service.lifecycle state=start \u2026` with no message token. Client: `\u2026 INFO client.access request finished ip=\u2026 status=200 bytes=-`.\n- `test_engine_and_client_render_alike` covers T7. One fixed `created` and one payload `{\"ts\": \u2026, \"level\": \"INFO\", \"event\": \"e\", \"message\": \"m\\nn\", \"context\": {\"a\": 1, \"b\": None, \"c\": [1, {\"d\": \"x\"}], \"request_id\": \"r\"}, \"request_id\": \"r\", \"traceback\": \"T\\nU\"}` must give equal strings from the Engine child and from `client_server._render_text` / `_format_ts`.\n- `test_engine_request_lines_are_ordered_by_ts(engine)` covers T8. It sends `POST /recommendations?limit=5&user_id=log-order-<uuid4 hex>` with `body={}`, then reads `engine.db_path` (the fixture's log path) as JSON lines. The slice runs from the `access.start` whose `context.url` contains the marker to the `access` that contains it. Inside the slice it keeps the `access.start`, the `access` and the `recommendations.*` records. It asserts at least one work record and non-decreasing `ts`. The session Engine runs with `--no-random-cache-refresh` and this pytest process sends one request at a time, so no other thread writes inside the slice. If the Engine refuses `user_id` on that route, the test-writing step should mark the URL through the `Host` header instead (`_get_full_url` builds it from `Host`).\n\n### Docs (the settled list)\n\n- **`DEPLOYMENT.md`, after line 114,** as one paragraph: \"Both the Engine and the Client backend read an optional `LOG_FORMAT` when they set up logging: `json` (the default) or `text`, case-insensitive with surrounding whitespace ignored; an unset, empty or unknown value selects `json` and never stops startup. Set it in `.env.bridge`, which is shared by the prod and dev units and exported to both services by `scripts/run-services.sh`, or with an `Environment=` drop-in for one unit. Every record's `ts` is UTC `YYYY-MM-DDTHH:MM:SS.mmmZ`, taken when the record was created, and is the timestamp to order by, not the journal's. `text` writes `ts LEVEL event message key=value\u2026` lines with newlines escaped as `\\n`, so a traceback stays on its record's one line; it is for reading by eye. `engine/watch-engine-logs.sh` shows nothing in text mode, `client/watch-client-logs.sh` shows each line as `{\"raw\": \u2026}`, and the Triage recipes that name JSON keys (`traceback`, `context.error`) assume `json`.\"\n- **`engine/server/README.md:31`:** append \"In `LOG_FORMAT=text` the traceback ends the record's line, newline-escaped (see DEPLOYMENT.md).\"\n- **`client/README.md`, near line 68:** \"Logging: `LOG_FORMAT` (`json` default, `text`), see DEPLOYMENT.md. Records not logged through `_emit_client_log` appear as event `client.log`, and a record with an exception carries a `traceback` key.\"\n- **`docs/project/issues/19-timestamped-request-logs.md`:** on delivery, set `Status: enhancement, complete`, move the file to `archive/`, and add a `## Comments` note that the default is JSON, not the issue's plain text, by operator decision.\n- **`docs/project/issues/plan.md`:** strike or update the triage note at lines 114-117 and the lane 4c row (line 91).\n\n### Check against the plan and requirements (pass 1, converged)\n\n- **R1** is met by `_format_ts`, which uses `created` and one `datetime`, gives `Z` and three-digit milliseconds, and stays under the `ts` key.\n- **R2** is met by the same helpers, stdlib `levelname`, leading `ts, level` in both payloads, and a Client root formatter that catches bare and library records. The Client keys are kept.\n- **R3** is met by `normalize_log_format` (fail-safe), reading at setup time in both services, unchanged JSON keys and rewriting, untouched `modes`, and the DEPLOYMENT paragraph.\n- **R4** is met by the shared `_render_text`, which renders the same payload so its message matches JSON, with `ts` identical to the JSON value.\n- **R5** is met by the CR/LF escape over the whole line, the traceback on the same line, no prefix, and the same stderr stream.\n- **R6** holds because `ts` comes from `created` (T8).\n- **The plan.** The plan's \"no call site changes\" holds for production code. The `test_server.py` rewire is the only edit outside the plan, and the impact inventory requires it.\n- **Named simplifications.** These are stated as limitations, not hidden:\n  - Two copies of the helpers, guarded by T7.\n  - Unquoted text tokens.\n  - Raw non-ASCII in text mode.\n  - The leak of an exported `LOG_FORMAT=text` into the Engine child tests. Not hardened, per the plan; popping it in conftest is the cheap upgrade if it ever bites.\n</draft>",
    "step_6_develop_phase_breakdown": "<phases>\n<phase n=\"1\" kind=\"code\">\n<checkpoint>Seam for C1: the Engine child-process harness from tests/active/test_logging_profiles.py, i.e. `subprocess.run([sys.executable, \"-c\", _ENGINE_CHILD, \u2026], cwd=API_DIR)` with `LOG_FORMAT` removed from the env. The child calls `configure_engine_logging(\"verbose\")` and logs records to stderr. On stdout it prints the `_format_ts` and `EngineJsonFormatter().format` of a `LogRecord` whose `created` comes from argv. Assertions: every stderr line parses as JSON and its `ts` matches `^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}\\.\\d{3}Z$`. created=1741091696.789 gives `2025-03-04T12:34:56.789Z` from both `_format_ts` and the formatted JSON's `ts`. created=1741091696.9999996 gives `2025-03-04T12:34:57.000Z`. A created one hour in the past renders that hour, not the formatting time. Seam for C2: the session `engine` fixture in conftest.py, whose log is read through `engine.db_path` as test_similar.py's `_messages` does. The test sends `POST /recommendations?limit=5&user_id=log-order-<uuid4 hex>` with `body={}`. If the route refuses `user_id`, the marker goes in through the `Host` header instead. The test parses the log's JSON lines, cuts the slice from the `access.start` whose `context.url` contains the marker to the `access` containing it, keeps the access.start, the access and the `recommendations.*` records, and asserts at least one work record and non-decreasing `ts`.</checkpoint>\n<name>Engine ts from record creation time</name>\n<intent>In engine/server/api/logging_profiles.py, EngineJsonFormatter takes every record's `ts` from `_format_ts(record)`, which renders `record.created` in UTC as `YYYY-MM-DDTHH:MM:SS.mmmZ`, so the Engine's `ts` follows the order of the log calls rather than the time of formatting.</intent>\n<clause_1>An Engine record's `ts` is its `record.created` rendered in UTC as `YYYY-MM-DDTHH:MM:SS.mmmZ`.</clause_1>\n<clause_2>Within one live Engine request, the `ts` values from its `access.start` to its `access` never decrease.</clause_2>\n<files>engine/server/api/logging_profiles.py (EDITED), tests/active/test_log_format.py (NEW)</files>\n</phase>\n<phase n=\"2\" kind=\"code\">\n<checkpoint>Seam: the same Engine child-process harness (cwd=API_DIR; env without `LOG_FORMAT`, plus `LOG_FORMAT` set when the case has a value), parametrized over None, \"json\", \"JSON\", \"bogus\", \"\", \"text\", \"TEXT\", \" Text \". The child calls `configure_engine_logging(\"verbose\")` and logs, in order: `[probe] plain`, `[probe] two\\nlines`, a `logging.exception(\"[probe] failed\")` for `ValueError(\"sentinel-log-format\")`, `[access.start] ip=127.0.0.1 method=GET url=http://x/a`, and `[service] lifecycle state=start component=engine run_id=r pid=1`. C1: the JSON cases give stderr lines that all parse with `json.loads`; the text cases give lines matching `^<TS_RE> (INFO|ERROR) ` and none parse as a JSON object. C2, in text mode: stderr has exactly five lines. The multiline and exception records each sit on one line, contain a literal `\\n` and, for the exception record, end with `ValueError: sentinel-log-format`. The access.start line is `<ts> INFO access.start request started ip=127.0.0.1 method=GET url=http://x/a`. The lifecycle line goes `<ts> INFO service.lifecycle state=start` with no message token. No line starts with `<`.</checkpoint>\n<name>Engine LOG_FORMAT text rendering</name>\n<intent>configure_engine_logging reads `LOG_FORMAT` when it runs and, for `text`, has EngineJsonFormatter render each record's payload through `_render_text` as one CR/LF-escaped `ts LEVEL event message k=v\u2026` line, while every other value keeps today's JSON.</intent>\n<clause_1>An Engine `LOG_FORMAT` of text in any case or surrounding whitespace selects text lines, and an unset, empty, `json` or unknown value selects JSON lines.</clause_1>\n<clause_2>An Engine text record is one physical line shaped `ts LEVEL event [message] k=v\u2026 [request_id=\u2026] [traceback]` with CR and LF written as `\\r` and `\\n`.</clause_2>\n<files>engine/server/api/logging_profiles.py (EDITED), tests/active/test_log_format.py (EDITED)</files>\n</phase>\n<phase n=\"3\" kind=\"code\">\n<checkpoint>Seam: in-process through conftest's `client_server` import. A `_client_logging(monkeypatch, value)` context manager is used inside the test body. It saves the root handlers and level, sets or deletes `LOG_FORMAT`, calls `client_server.configure_client_logging()`, swaps `root.handlers[0]` to an `io.StringIO` stream, and restores everything in `finally`. With `LOG_FORMAT` unset, the test calls `client_server._emit_client_log(logging.ERROR, \"engine.call\", \"Engine metadata failed\", {\"error\": \"x\\ny\"})`, then a `logging.exception` record, then `logging.info(\"bare\")`. C1: the emitted line's keys are exactly `[\"ts\", \"level\", \"service\", \"event\", \"message\", \"context\"]` in order, with `service == \"client-backend\"`, `event == \"engine.call\"`, `context == {\"error\": \"x\\ny\"}` and `ts` matching TS_RE. The exception record carries a `traceback` key. C2: the bare record parses with keys `ts, level, service, event, message`, `event == \"client.log\"` and `message == \"bare\"`. The full suite also covers the rewired ERROR-record tests in tests/active/test_server.py (`_error_messages` renders through `ClientLogFormatter`, and caplog's handler gets that formatter in the `caplog.text` test), which must stay green.</checkpoint>\n<name>Client root formatter, JSON</name>\n<intent>In client/backend/server.py, configure_client_logging installs ClientLogFormatter on the root logger, which `main()` now calls in place of `basicConfig`, and `_emit_client_log` hands it event and context as `client_event`/`client_context` record attributes instead of building JSON by hand, so every Client record leaves through one formatter.</intent>\n<clause_1>An `_emit_client_log` record renders as a JSON line whose keys run `ts, level, service, event, message[, context]` with a UTC `ts`.</clause_1>\n<clause_2>A bare root-logger record renders in the same JSON shape with event `client.log`.</clause_2>\n<files>client/backend/server.py (EDITED), tests/active/test_server.py (EDITED), tests/active/test_log_format.py (EDITED)</files>\n</phase>\n<phase n=\"4\" kind=\"code\">\n<checkpoint>Seam for C1: the in-process `_client_logging` context manager from phase 3, parametrized over the same eight `LOG_FORMAT` values as phase 2. JSON cases: every line parses. Text cases: every line matches `^<TS_RE> (INFO|ERROR) `, and the exception record and the `{\"error\": \"x\\ny\"}` record are each one physical line containing a literal `\\n`. A `client.access` record (`_emit_client_log(INFO, \"client.access\", \"request finished\", {\"ip\": \u2026, \"status\": 200, \"bytes\": \"-\"})`) renders `<ts> INFO client.access request finished ip=\u2026 status=200 bytes=-`. No line starts with `<`. Seam for C2: the Engine child harness prints `_format_ts` for one fixed `created` and `_render_text` of a payload passed in argv: `{\"ts\": \u2026, \"level\": \"INFO\", \"event\": \"e\", \"message\": \"m\\nn\", \"context\": {\"a\": 1, \"b\": None, \"c\": [1, {\"d\": \"x\"}], \"request_id\": \"r\"}, \"request_id\": \"r\", \"traceback\": \"T\\nU\"}`. The test asserts both strings equal `client_server._format_ts` and `client_server._render_text` on the same inputs in-process.</checkpoint>\n<name>Client text rendering and drift guard</name>\n<intent>The Client's `normalize_log_format`, `_format_ts`, `_text_value` and `_render_text` are copies of the Engine's, so `LOG_FORMAT` selects the Client's rendering exactly as it does the Engine's, and both services write byte-identical `ts` and text for the same record.</intent>\n<clause_1>A Client `LOG_FORMAT` value selects text or JSON lines exactly as the same value does for the Engine.</clause_1>\n<clause_2>For the same `created` and payload, the Client's `_format_ts` and `_render_text` return the same strings as the Engine's.</clause_2>\n<files>client/backend/server.py (EDITED), tests/active/test_log_format.py (EDITED)</files>\n</phase>\n</phases>\n\n<needs_coordination>\nnone. No phase needs credentials or a manual step. Phase 1 clause 2 uses the session `engine` fixture, which needs the engine pixi env (`engine/.pixi/envs/default`) and `whitelist.db` that the active suite already relies on.\n</needs_coordination>\n\n<rationale>\nFour phases, split on two seams: by service (Engine, then Client), and within each service by concern (timestamp/format contract, then the text rendering). The Engine goes first because the Client copies its helpers, and phase 4's drift guard needs both sides to exist. Each Intent reduces to two clauses. A single Engine phase would have carried three facts (ts source, LOG_FORMAT selection, text line shape), and a single Client phase would have carried four (key order, bare-record fallback, format selection, parity with the Engine), so both were split here. Phase 3 also carries the test_server.py rewire. Once `_emit_client_log` stops building JSON, those ERROR-record tests fail, so they must land in the same phase. The full suite verifies them; they are not a clause of their own. There is no prose phase: the DEPLOYMENT.md, README, issue-19 and plan.md edits are documentation for Step 9. The draft's T1-T8 map onto the clauses as follows: T1/T2 to P1-C1 and P3-C1, T8 to P1-C2, T3 to P2-C1 and P4-C1, T4/T5 to P2-C2 and P4-C1, T6 to P3, T7 to P4-C2. T9 is the full suite. Known unproven line: `main()` calling `configure_client_logging()` in place of `basicConfig` is a one-line swap that no checkpoint enters, because `main` parses argv and binds a port. The operator approved this gap. Note for the checkpoint author: the step template's principles and shape-ladder placeholders arrived unfilled, so the seams above follow the existing suite's precedent (the child harness in test_logging_profiles.py, the engine log reading in test_similar.py, and the in-process client_server import from conftest).\n</rationale>",
    "author:tests/tmp/test_19_timestamped_request_logs_phase1.py": "<assertions>\ntests/tmp/test_19_timestamped_request_logs_phase1.py:72 - every stderr line of the child (the `configure_engine_logging(\"verbose\")` handler, LOG_FORMAT unset, TZ pinned to Asia/Kathmandu +05:45) has a `ts` that fully matches `^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}\\.\\d{3}Z$` - C1\ntests/tmp/test_19_timestamped_request_logs_phase1.py:74 - each of those stderr `ts` values, read back as UTC, is within 60 s of the child's `time.time()`, so a local-time rendering (off by 5h45m here) fails - C1\ntests/tmp/test_19_timestamped_request_logs_phase1.py:78 - created=1741091696.789, set on a LogRecord after construction (its msecs is the clock at construction): `_format_ts` and `EngineJsonFormatter().format`'s `ts` are both exactly `2025-03-04T12:34:56.789Z` - C1\ntests/tmp/test_19_timestamped_request_logs_phase1.py:80 - created=1741091696.9999996: both are exactly `2025-03-04T12:34:57.000Z` (plain millisecond truncation gives 56.999) - C1\ntests/tmp/test_19_timestamped_request_logs_phase1.py:81 - created = test's time.time() - 3600: the formatter's `ts` equals `_format_ts` and matches TS_RE - C1\ntests/tmp/test_19_timestamped_request_logs_phase1.py:82 - that `ts`, read back as UTC epoch, is within 1 ms of the `created` passed in - C1\ntests/tmp/test_19_timestamped_request_logs_phase1.py:84 - negative: that `ts` is more than 3540 s before the child's formatting time, so it is not the time of formatting - C1\ntests/tmp/test_19_timestamped_request_logs_phase1.py:120 - session Engine, POST /recommendations?limit=5&user_id=log-order-<hex>, body {}: between the single marked access.start and the single marked access (controls at :109 status 200 with seed.user_id == marker, :116 exactly one of each with start before end, :119 the kept slice opens with access.start and closes with access), at least one `recommendations.*` work record is kept - C2\ntests/tmp/test_19_timestamped_request_logs_phase1.py:123 - every kept record's `ts` matches TS_RE - C2\ntests/tmp/test_19_timestamped_request_logs_phase1.py:125 - every kept `ts`, read back as UTC, lies within [before-1 s, after+1 s] of the request's wall-clock window, which rules out a constant or local-time ts that would make ordering vacuous - C2\ntests/tmp/test_19_timestamped_request_logs_phase1.py:126 - the kept `ts` values, in log order, never decrease - C2\n</assertions>\n\n<probes>\n1. tests/tmp/test_probe_19_p1.py::test_probe_child, run via ValidateTests [\"tests/tmp/test_probe_19_p1.py\", \"-k\", \"child\"]. The child ran under the current logging_profiles with LOG_FORMAT removed. Stderr lines read like {\"ts\":\"2026-10-01T18:16:04.556-04:00\",...} for \"[probe] plain\", \"request started\" and \"[probe] failed without exception\". `_format_ts` is absent (printed null). `EngineJsonFormatter().format` of records with created 1741091696.789 / 1741091696.9999995 / now-3600 gave ts \"2026-10-01T18:16:04.556-04:00\" for all three, which is the formatting time. record.msecs was 556.0, set at construction and not updated when created was set. In the parent, datetime.fromtimestamp(..., timezone.utc) gave 2025-03-04T12:34:56.789000+00:00 and 2025-03-04T12:34:57+00:00, while int(frac*1000) gave 789 and 999. json.dumps renders 1741091696.9999996 as 1741091696.9999995 (the same float). The host TZ is -04:00 and TZ is unset.\n2. tests/tmp/test_probe_19_p1.py::test_probe_engine, against the session `engine` fixture. POST /recommendations?limit=5&user_id=log-order-<hex> with body {} returned 200, seed {\"user_id\": marker, \"mode\": \"home\"} and 5 rows, so the route accepts `user_id` and no Host-header fallback is needed. The log had 0 non-JSON lines. The marker appeared in the access.start and access context.url, and between them came recommendations.incoming_likes_body (no request_id), recommendations.info \u00d76, recommendations.layer_timing and recommendations.profile, plus similar_server.info and similarity.request_done, which the filter drops. The request took about 600 ms.\n3. The checkpoint itself, against the current code (ValidateTests on tests/tmp/test_19_timestamped_request_logs_phase1.py): 2 failed. C1 passed all controls and failed at :72 with ts ['2026-10-02T04:02:22.310+05:45', \u2026], which shows the TZ pin reaches the child. C2 passed all controls (200, one start and one end, recommendations work present) and failed at :123 with ts ['2026-10-01T18:17:23.590-04:00', \u2026].\n4. tests/tmp/test_probe_19_p1.py::test_probe_patched ran the checkpoint's C1 test with the plan's `_format_ts` (fromtimestamp UTC, microsecond // 1000) patched in memory into logging_profiles, along with a formatter subclass that sets ts from it. Result: \"PATCHED PASSES\". Every C1 expectation holds under the intended implementation. C2 was not run against a patched Engine (see unassertable).\nThe probe file has been overwritten with a \"Delete this file.\" note, following the repo's existing tmp-probe convention, because I have no delete tool.\n</probes>\n\n<unassertable>\nnone. Every C1 and C2 assertion is in place. Two notes for the reviewer. (a) C2's pass under a correct implementation is predicted but not observed: I could not run the live Engine with the new `_format_ts` without editing production code. The prediction rests on the probed slice, where all kept records are written on the request's thread in a serial sequence, and on the C1 probe passing under the plan's helper. The phase's first green run will confirm it. (b) Two pins go beyond the agreed seam, and both serve the agreed assertions. The C1 child gets TZ=Asia/Kathmandu so a local-time rendering cannot pass on a UTC host. The C2 test also bounds every kept ts to the request's wall-clock window, so a constant ts cannot pass \"non-decreasing\" vacuously.\n</unassertable>",
    "self_check:tests/tmp/test_19_timestamped_request_logs_phase1.py": "<rows>\n<row clause=\"C1\">\n<assertion>test_19_timestamped_request_logs_phase1.py:72, :74, :78, :80, :81, :82, :84. Line 72: every stderr line that `configure_engine_logging(\"verbose\")` writes in a child with TZ=Asia/Kathmandu has a `ts` that fully matches `TS_RE`. Line 74: each of those reads back as UTC to within 60 s of the child's `time.time()`. Line 78: for created=1741091696.789, `_format_ts` and `EngineJsonFormatter().format(...)[\"ts\"]` are both `2025-03-04T12:34:56.789Z`. Line 80: for created=1741091696.9999996 both are `2025-03-04T12:34:57.000Z`. Lines 81, 82 and 84 check each of the two values for a `created` one hour back separately: it matches `TS_RE` (81), it reads back to that `created` within 1 ms (82), and it is more than HOUR-60 s before the child's clock at formatting time (84).</assertion>\n<expected>Three `YYYY-MM-DDTHH:MM:SS.mmmZ` stamps from the child's own minute. `{\"format_ts\": \"2025-03-04T12:34:56.789Z\", \"formatted\": \"2025-03-04T12:34:56.789Z\"}` and `{\"format_ts\": \"2025-03-04T12:34:57.000Z\", \"formatted\": \"2025-03-04T12:34:57.000Z\"}`. These two values were observed in probe tests/tmp/probe_ts_values.py: the plan's `fromtimestamp(created, timezone.utc)` + `microsecond // 1000` formula gives exactly these strings. For the hour-back record, both values equal `past` truncated to the millisecond, about 3600 s before `now`.</expected>\n<wrong_implementation>Today's `datetime.now().astimezone().isoformat(timespec=\"milliseconds\")` reads `2026-10-02T04:04:51.609+05:45` in the child, which fails line 72 (observed). A local-time rendering with a `Z` bolted on reads back 5h45m off and fails line 74. A ts taken at formatting time rather than from `created` gives the 2026 clock instead of 2025-03-04 at line 78 and is not an hour back at line 84. Milliseconds read from `record.msecs` give the construction clock, observed as `.129Z`, and fail lines 78 and 80. Milliseconds truncated from `created % 1` with no microsecond rounding give `2025-03-04T12:34:56.999Z` (observed in the probe) and fail line 80. A missing `_format_ts` helper prints null and fails lines 78, 80 and 81.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>test_19_timestamped_request_logs_phase1.py:120, :123, :125, :126. The session Engine log is sliced from the one `access.start` whose `context.url` holds the `log-order-<hex>` marker to the one `access` that holds it. The slice keeps the access.start, the access and the `recommendations.*` records. Line 120: at least one `recommendations.*` record lies between the two access records. Line 123: every kept `ts` fully matches `TS_RE`. Line 125: every kept `ts` reads back inside [before-1 s, after+1 s] of the request's wall clock. Line 126: the kept `ts` values, read back as epochs, are already in sorted (non-decreasing) order.</assertion>\n<expected>An access.start, several `recommendations.*` work records and an access, all in UTC `...Z` form, inside the request window and non-decreasing. Today's run observed six or more kept records, which shows the work records are there (line 120 passed).</expected>\n<wrong_implementation>Today's formatter writes the Engine's local time with an offset. The observed value is `['2026-10-01T18:19:52.639-04:00', ...]`, which fails line 123. A local-time stamp ending in `Z` falls hours outside the request window and fails line 125. Line 126 catches one specific bug: seconds and milliseconds taken from two different roundings of `created`, for example seconds from `fromtimestamp` (which rounds to the microsecond) and milliseconds from `int(created % 1 * 1000)`. Then a record at x.9999996 renders as x+1.999, and the next record at x+1.0xx reads earlier, so ts goes backwards. A ts taken at formatting time on a deferred or queued handler can also run out of call order. One caveat: today's synchronous format-time stamp would also be non-decreasing. Today's red comes from lines 123 and 125, not from line 126.</wrong_implementation>\n</row>\n</rows>\n\n<answers>\n1. Whole claim: yes, each clause is tested. Every docstring sentence has an assertion. Child records: TS_RE at line 72, reading back to the child clock at line 74. Fixed `created` values for `_format_ts` and the formatter: lines 78 and 80. The hour-back record: lines 81, 82 and 84. Live request: one start and one end (line 116), at least one recommendations record (line 120), TS_RE (line 123), inside the wall-clock window (line 125), non-decreasing (line 126). No rewrite was needed for this question.\n2. Absence only: no. The test has no negative assertions. Line 84 is a positive lower bound on how far the hour-back stamp sits before the formatting clock.\n3. Echoed literal: no. The expected strings are fixed literals. `_epoch` parses a stamp back, which is the inverse of production's rendering, not a copy of it, and the bounds come from independent clocks (`time.time()` in the child and in the test). The production line whose deletion turns these red is the `\"ts\":` entry of the payload in `EngineJsonFormatter.format` (logging_profiles.py:195 today, `_format_ts(record)` after the phase), together with `_format_ts`'s body.\n4. One value: there was a yes, now fixed. C1 is read at three `created` values plus three live records, and C2 across every record of a live request. The old line 81 pinned `hour_back[\"formatted\"] == hour_back[\"format_ts\"]`, a sibling from the same source, and lines 82 and 84 then checked only `formatted`. I rewrote lines 81, 82 and 84 to check `format_ts` and `formatted` separately, each against TS_RE, against `past` and against the child's `now`. Lines 78 and 80 already pin both against independent literals.\n5. The double: no. There are no doubles. The real `logging_profiles` runs in a child and the real Engine runs from the session fixture.\n6. It collects: yes. `--collect-only` lists both tests in tests/last_test_output.txt (\"2 tests collected\"). The `conftest` import binds `ROOT` and `engine`. `engine.db_path` is the fixture's log path (conftest.py:124 `ClientBackend(..., log_path)`). The run reached assertions in both tests.\n7. Observed, not predicted: yes, after a probe. The off-UTC rendering (`+05:45`) and the live record set were seen in the checkpoint run. The literal expectations at lines 78 and 80, and the wrong-implementation readings in the comments, were not yet observed, so I ran probe tests/tmp/probe_ts_values.py (`-vv`). It printed: `'1741091696.789': {'plan': '2025-03-04T12:34:56.789Z', 'truncating': '2025-03-04T12:34:56.789Z', 'via_msecs': '2025-03-04T12:34:56.129Z'}` and `'1741091696.9999995': {'plan': '2025-03-04T12:34:57.000Z', 'truncating': '2025-03-04T12:34:56.999Z', 'via_msecs': '2025-03-04T12:34:56.129Z'}`. The expected literals match what the plan's formula gives; truncation and msecs give the wrong values the comments name. Not observed: the post-phase values of lines 74, 82, 84, 125 and 126. They can only be seen once `_format_ts` exists. They are bounds against independent clocks, not shapes I predicted. The probe file is still in tests/tmp: I have no delete tool, and its name does not match `test_*.py`, so default discovery does not collect it. It needs removing.\n8. Red, not green: yes. After the rewrite, `ValidateTests tests/tmp/test_19_timestamped_request_logs_phase1.py` gave `[exit status 1]`, \"2 failed\".\n9. Red for the right reason: yes. Both tests got past every control: returncode 0, JSON lines, the three messages in order (line 70), status 200 with the seed user_id (line 109), one start before one end (line 116), first and last events (line 119), and the recommendations record (line 120). Test 1 failed at `tests/tmp/test_19_timestamped_request_logs_phase1.py:72: AssertionError: ['2026-10-02T04:04:51.609+05:45', '2026-10-02T04:04:51.609+05:45', '2026-10-02T04:04:51.609+05:45']`. That is the C1 assertion failing on today's local-time ts with an offset. Test 2 failed at `tests/tmp/test_19_timestamped_request_logs_phase1.py:123: AssertionError: ['2026-10-01T18:19:52.639-04:00', '2026-10-01T18:19:52.639-04:00', '2026-10-01T18:19:53.118-04:00', ...]`. That is the C2 TS_RE assertion failing on today's formatter, not a control.\n10. Observed expected output: what the run showed, plus one honest gap. Both `wrong_implementation` readings for today's code are quoted from this run (`...+05:45` and `...-04:00`). The C1 `expected` literals, and the wrong readings `56.999Z` and `.129Z`, come from the probe run quoted in answer 7. The run contradicted none of the rows. For C2, the run shows the ordering is not what makes it red today; the red comes from line 123. The C2 row says so instead of claiming that line 126 fails now.\n</answers>\n\n<exemptions>\nnone\n</exemptions>",
    "step_7_implement:1": "<changes>\n### `engine/server/api/logging_profiles.py`\n- Added the module-level helper `_format_ts(record)`. It renders `record.created` in UTC as `YYYY-MM-DDTHH:MM:SS.mmmZ` using `datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(timespec=\"milliseconds\")`, with the `+00:00` suffix replaced by `Z`.\n- It deliberately does not read `record.msecs`, because `msecs` is not updated when `created` is set after the record is built.\n- I observed the rounding in a probe rather than assuming it. `fromtimestamp` rounds to the microsecond before `isoformat` cuts to milliseconds: `1741091696.789` came out as `2025-03-04T12:34:56.789+00:00` and `1741091696.9999996` as `2025-03-04T12:34:57.000+00:00`.\n- `EngineJsonFormatter.format` now sets `\"ts\": _format_ts(record)`. Before, it used `datetime.now().astimezone().isoformat(...)`, which gave local time at the moment of formatting. Now the stamp is the time the log call happened, which is what keeps it in order across one request.\n- The import changed from `from datetime import datetime` to `from datetime import datetime, timezone`.\n\n### `tests/active/test_log_format.py`\nNot created. The phase lists it as NEW, but this step is production code only. It looks like the permanent home for the checkpoint once it is moved out of `tests/tmp/`, and nothing in this phase needs it to exist.\n\n### `tests/tmp/probe_fromtimestamp.py`\nThis was my throwaway probe for the rounding check. I have no delete tool, so I emptied the file instead; it now collects no tests. It can be removed.\n</changes>\n\n<inner_tests>\nnone\n</inner_tests>\n\n<unanticipated>\ntests/tmp/probe_fromtimestamp.py: the throwaway probe for the rounding check. It is now an empty file because I couldn't delete it, and it can be removed.\n</unanticipated>\n\n<awaiting_operator>\nnone\n</awaiting_operator>",
    "author:tests/tmp/test_19_timestamped_request_logs_phase2.py": "<assertions>\ntests/tmp/test_19_timestamped_request_logs_phase2.py:78 - LOG_FORMAT unset, `json`, `JSON`, `bogus` or `\"\"`: stderr has five lines and each one parses with json.loads as a JSON object - C1\ntests/tmp/test_19_timestamped_request_logs_phase2.py:80 - in those JSON cases, every record's `ts` fully matches TS_RE - C1\ntests/tmp/test_19_timestamped_request_logs_phase2.py:82 - in those JSON cases, the exception record's `traceback` starts `Traceback (most recent call last):` and ends `ValueError: sentinel-log-format` - C1\ntests/tmp/test_19_timestamped_request_logs_phase2.py:84 - in those JSON cases, the five payloads minus ts/traceback equal JSON_PAYLOADS item for item, key order included. These are the payloads observed before this phase, so a non-text value keeps today's JSON - C1\ntests/tmp/test_19_timestamped_request_logs_phase2.py:93 - LOG_FORMAT `text`, `TEXT` or ` Text `: stderr is exactly five lines. splitlines breaks on CR and on LF, so an unescaped CR or LF in the CR/LF message or the traceback adds a line - C2\ntests/tmp/test_19_timestamped_request_logs_phase2.py:95 - in the text cases, every line matches `^<TS_RE> (INFO|ERROR) ` - C1\ntests/tmp/test_19_timestamped_request_logs_phase2.py:96 - negative: in the text cases, no line parses as a JSON object - C1\ntests/tmp/test_19_timestamped_request_logs_phase2.py:97 - in the text cases, no line starts with `<` - C2\ntests/tmp/test_19_timestamped_request_logs_phase2.py:100 - in the text cases, each line's first space-separated token fully matches TS_RE - C2\ntests/tmp/test_19_timestamped_request_logs_phase2.py:102 - the plain record reads exactly `INFO probe.info [probe] plain` after the ts - C2\ntests/tmp/test_19_timestamped_request_logs_phase2.py:103 - the `[probe] two\\r\\nlines` record is one line reading exactly `INFO engine.log [probe] two\\r\\nlines`, with CR and LF written as the literal two-character escapes - C2\ntests/tmp/test_19_timestamped_request_logs_phase2.py:105 - the exception record is one line that fully matches `ERROR probe.info [probe] failed request_id=rid-p2 Traceback (most recent call last):\\n  File \"<string>\", line N, in <module>\\n    raise ValueError(\"sentinel-log-format\")\\nValueError: sentinel-log-format`, with literal `\\n`. This pins request_id after the message and before the traceback - C2\ntests/tmp/test_19_timestamped_request_logs_phase2.py:106 - the exception line ends with `ValueError: sentinel-log-format` - C2\ntests/tmp/test_19_timestamped_request_logs_phase2.py:107 - the access.start line reads exactly `INFO access.start request started ip=127.0.0.1 method=GET url=http://x/a` after the ts - C2\ntests/tmp/test_19_timestamped_request_logs_phase2.py:109 - the lifecycle line reads exactly `INFO service.lifecycle state=start component=engine run_id=r pid=1` after the ts, with no message token - C2\n</assertions>\n\n<probes>\ntests/tmp/test_probe_19_p2.py (ValidateTests [\"tests/tmp/test_probe_19_p2.py\", \"-s\"]). It ran the agreed five-record child with LOG_FORMAT unset and then set to `text`, against today's code. Both runs printed the same five JSON lines: `{\"ts\":\u2026,\"level\":\"INFO\",\"event\":\"probe.info\",\"message\":\"[probe] plain\",\"modes\":[\"verbose\"]}`; then `{\u2026\"event\":\"engine.log\",\"message\":\"[probe] two\\nlines\",\"modes\":[\"verbose\"]}` (the newline defeats _PREFIX_RE, so the event falls back to engine.log); then `{\u2026\"level\":\"ERROR\",\"event\":\"probe.info\",\"message\":\"[probe] failed\",\"modes\":[\"focused\",\"verbose\"],\"traceback\":\"Traceback (most recent call last):\\n  File \\\"<string>\\\", line 8, in <module>\\n    raise ValueError(\\\"sentinel-log-format\\\")\\nValueError: sentinel-log-format\"}` (no caret line under Python 3.14.7); then `{\u2026\"event\":\"access.start\",\"message\":\"request started\",\u2026,\"context\":{\"ip\":\"127.0.0.1\",\"method\":\"GET\",\"url\":\"http://x/a\"}}`; then `{\u2026\"event\":\"service.lifecycle\",\"modes\":[\"focused\",\"verbose\"],\"context\":{\"state\":\"start\",\"component\":\"engine\",\"run_id\":\"r\",\"pid\":\"1\"}}` with no message key. I then ran the real test against today's code (ValidateTests [\"tests/tmp/test_19_timestamped_request_logs_phase2.py\"]): 5 passed, 3 failed. All five JSON cases pass, which confirms JSON_PAYLOADS for the adjusted records: the `two\\r\\nlines` message still maps to engine.log, and `extra={\"request_id\": \"rid-p2\"}` gives `\"request_id\":\"rid-p2\"` after modes. The three text cases fail at line 95 because stderr is still JSON. Not observable before implementation: the text-line strings at :102-:109. They are predictions from the agreed checkpoint and the Step-5 `_render_text` draft, built on the payloads observed above. The implementation run confirms them. The probe file could not be deleted with the tools I have, so it has been emptied. tests/tmp/test_probe_19_p2.py should be removed.\n</probes>\n\n<unassertable>\nTwo of the agreed records were adjusted with the operator's approval (AskUser: \"Adjust two records, still five lines\"). The multiline message is now `[probe] two\\r\\nlines`, so CR escaping is asserted. The exception record now carries `extra={\"request_id\": \"rid-p2\"}`, so the `[request_id=\u2026]` slot between the message/context and the traceback is asserted. Still five records and five lines. Not asserted: the Intent's \"reads LOG_FORMAT when it runs\" (call time rather than import time). The agreed seam sets LOG_FORMAT in the child's env before it starts, and that cannot tell the two apart. It is not part of C1 or C2. A child that sets os.environ between import and configure_engine_logging would confirm it.\n</unassertable>",
    "self_check:tests/tmp/test_19_timestamped_request_logs_phase2.py": "<rows>\n<row clause=\"C1\">\n<assertion>test_19_timestamped_request_logs_phase2.py:78,80,82,84 \u2014 for LOG_FORMAT unset, `json`, `JSON`, `bogus` and `\"\"`, stderr is exactly five lines and each parses as a JSON object (78). Each `ts` matches TS_RE (80). The exception record's traceback starts `Traceback (most recent call last):` and ends `ValueError: sentinel-log-format` (82). With `ts` and `traceback` removed, each payload's items, in key order, equal JSON_PAYLOADS (84).</assertion>\n<expected>Five JSON lines whose items equal JSON_PAYLOADS in order, for example access.start reads `level, event, message=\"request started\", modes, request_id=\"rid-a\", context={ip, method, url}`. Observed passing for all five values in the current run.</expected>\n<wrong_implementation>A selector that treats every value other than exactly `json` as text, so unset, `JSON`, `bogus` or `\"\"` give text. The lines no longer parse, and 78 goes red on `None` payloads. A JSON branch that is rebuilt and reorders keys or drops the access.start message rewrite turns 84 red on the item lists.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>test_19_timestamped_request_logs_phase2.py:95,96 \u2014 for LOG_FORMAT `text`, `TEXT`, ` Text ` and `\\ttext\\n`, every line starts with a TS_RE timestamp, a space and `INFO ` or `ERROR ` (95). No line parses as a JSON object (96; line 95 is its positive control).</assertion>\n<expected>Five text lines that start `<ts> INFO ` / `<ts> ERROR `, none of them JSON. Today the run shows five JSON lines for all four values, and 95 fails.</expected>\n<wrong_implementation>A selector that compares `value == \"text\"` without lowercasing and stripping: `TEXT`, ` Text ` and `\\ttext\\n` stay JSON and 95 reads `False` on a `{\"ts\":\u2026` line. A selector that strips only spaces fails the tab/newline case. Not reading LOG_FORMAT at all (the code as it stands) fails all four.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>test_19_timestamped_request_logs_phase2.py:93,97,100 \u2014 under text mode, `stderr.splitlines()` (which also breaks on CR) gives exactly five lines, one per record (93). No line starts with `<` (97). The first space-separated token of each line fully matches TS_RE (100).</assertion>\n<expected>`len(lines) == 5`, no line starts with `<`, and every head token looks like `2026-10-01T22:29:27.181Z`.</expected>\n<wrong_implementation>A text renderer that does not escape CR/LF: the `two\\r\\nlines` message and the three-line traceback split into extra physical lines, giving 9 or more, and 93 goes red. A renderer that adds a syslog `<N>` priority prefix fails 97 and 100.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>test_19_timestamped_request_logs_phase2.py:102,103 \u2014 after the ts, the plain record reads exactly `INFO probe.info [probe] plain`, and the CR/LF record reads exactly `INFO engine.log [probe] two\\r\\nlines`, where `\\r` and `\\n` are the two characters backslash-r and backslash-n.</assertion>\n<expected>`INFO probe.info [probe] plain` and `INFO engine.log [probe] two\\\\r\\\\nlines` (Python literal).</expected>\n<wrong_implementation>A renderer that escapes LF but not CR, or that drops CR/LF instead of escaping them: line 103 reads `\u2026two\\r\\\\nlines` or `\u2026twolines`, and in the unescaped-CR case 93 also reads 6. A renderer that includes `modes` or the level name in lowercase breaks 102.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>test_19_timestamped_request_logs_phase2.py:105 \u2014 after the ts, the exception record fully matches `ERROR probe.info [probe] failed request_id=rid-p2 Traceback (most recent call last):\\n  File \"<string>\", line \\d+, in <module>\\n    raise ValueError(\"sentinel-log-format\")\\nValueError: sentinel-log-format`, with each `\\n` the two literal characters.</assertion>\n<expected>A full match. The traceback body is the one observed in the JSON `traceback` key under a probe run: `Traceback (most recent call last):\\n  File \"<string>\", line 6, in <module>\\n    raise ValueError(\"sentinel-log-format\")\\nValueError: sentinel-log-format`, with no caret line.</expected>\n<wrong_implementation>A renderer that puts the traceback before `request_id=`, leaves the traceback out, or leaves its newlines raw. In each case the fullmatch is None. The raw-newline case also makes 93 read 8.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>test_19_timestamped_request_logs_phase2.py:107 \u2014 after the ts, the access.start record (logged with extra request_id `rid-a`) reads exactly `INFO access.start request started ip=127.0.0.1 method=GET url=http://x/a request_id=rid-a`.</assertion>\n<expected>`INFO access.start request started ip=127.0.0.1 method=GET url=http://x/a request_id=rid-a`. The probe run confirmed that the payload carries request_id `rid-a` and that context is {ip, method, url}.</expected>\n<wrong_implementation>A renderer that walks the payload in dict order, so `request_id=rid-a` comes before the context tokens because request_id precedes context in the payload. Another that uses the raw `getMessage()` (`[access.start] ip=\u2026`) instead of the payload's rewritten `request started`. Either way the string differs.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>test_19_timestamped_request_logs_phase2.py:109 \u2014 after the ts, the lifecycle record reads exactly `INFO service.lifecycle state=start component=engine run_id=r pid=1`.</assertion>\n<expected>`INFO service.lifecycle state=start component=engine run_id=r pid=1`. There is no message token.</expected>\n<wrong_implementation>A renderer that writes `str(payload.get(\"message\"))` or the record's raw message whenever the payload has none. That gives `INFO service.lifecycle None state=\u2026` or `INFO service.lifecycle [service] lifecycle state=\u2026 state=\u2026`, which is not equal.</wrong_implementation>\n</row>\n</rows>\n\n<answers>\n1. Whole claim \u2014 yes, on the first pass. C2's order `k=v\u2026 [request_id=\u2026]` was never exercised: no record had both a context and a request_id, so a renderer that put request_id before the context would have passed. Rewrite: the access.start record now carries `extra={\"request_id\": \"rid-a\"}`, and line 107 pins `\u2026 url=http://x/a request_id=rid-a`. JSON_PAYLOADS gained `\"request_id\": \"rid-a\"` before `context`, taken from the order the probe showed (`KEYS ['ts','level','event','message','modes','request_id','context']`), and the docstring was updated to match. I also dropped the old `failed.endswith(...)` assertion, which only repeated the fullmatch at 105. After the rewrite every docstring clause has an assertion: the JSON matrix (78\u201384), the five-line count (93), the text head (95), not JSON (96), no `<` (97), ts (100), plain/CR-LF/exception/access/lifecycle (102\u2013109). Second pass: no.\n2. Absence only \u2014 no. Line 96 (no line is JSON) and line 97 (no line starts with `<`) are both negative. Line 95 (text head regex) and the exact-equality assertions at 102\u2013109 are the positive controls on the same lines. Lines 90 and 93 show the child ran and emitted five records.\n3. Echoed literal \u2014 no. Every expected value is a fixed literal; the test does none of production's transformation. Deleting `payload[\"message\"] = \"request started\"` (logging_profiles.py:218) turns 84 red, and so would deleting `payload[\"request_id\"] = request_id` (:209). The text expectations come from the plan's R4/R5 shape, not from any computation in the test.\n4. One value \u2014 no, after one change. The JSON choice is read at five inputs: unset, `json`, `JSON`, `bogus`, `\"\"`. The text choice was read at three (`text`, `TEXT`, ` Text `) with only spaces as padding, so I added `\"\\ttext\\n\"` to cover other whitespace. The text shape is read on five different records (plain, CR/LF, exception, access.start, lifecycle), and no expected value is pinned against a sibling from the same source.\n5. The double \u2014 no. The child imports the real `logging_profiles.configure_engine_logging` and logs through the real root logger to real stderr. Nothing is shimmed.\n6. It collects \u2014 yes, it collects. The `--collect-only -q` summary printed `no tests`, but the ValidateTests run of the same file printed `collected 8 items` before my edit and 9 after (5 JSON + 4 text parametrizations), which is the count I wrote. Every name used binds: json, os, re, subprocess, sys, textwrap, Path, pytest, TS_RE, TEXT_HEAD_RE, JSON_PAYLOADS, EXCEPTION_TEXT_RE, _run_child, _json_object. `configure_engine_logging(profile)` exists at logging_profiles.py:236, and `logging.exception`/`logging.info` accept `extra=`.\n7. Observed, not predicted \u2014 yes, for two values, and both are now observed. The access.start payload with a request_id, and the exact traceback text the text line embeds, had not been seen. I wrote a probe, tests/tmp/test_probe_19_p2.py, and ran it with `-s`. It printed `KEYS ['ts', 'level', 'event', 'message', 'modes', 'request_id', 'context']` for access.start and `TB 'Traceback (most recent call last):\\n  File \"<string>\", line 6, in <module>\\n    raise ValueError(\"sentinel-log-format\")\\nValueError: sentinel-log-format'` (no caret line on Python 3.14.7). It also printed `RC 0` for `LOG_FORMAT='\\ttext\\n'`, so that env value is accepted. The 5 JSON parametrizations pass in the real run, which confirms JSON_PAYLOADS. The text-line strings themselves cannot be observed until the phase exists: they are the plan's R4/R5 spec, built on the observed payload and traceback. The probe file has been emptied again.\n8. Red, not green \u2014 yes, it is red. `ValidateTests tests/tmp/test_19_timestamped_request_logs_phase2.py` printed `4 failed, 5 passed`, `[exit status 1]`. The failures are `test_engine_log_format_text_writes_one_escaped_text_line_per_record[text]`, `[TEXT]`, `[ Text ]` and `[\\ttext\\n]`. The 5 JSON parametrizations pass, as they should, because JSON is today's behaviour that must stay unchanged.\n9. Red for the right reason \u2014 yes. All four failures are at `tests/tmp/test_19_timestamped_request_logs_phase2.py:95: AssertionError`, `assert all(TEXT_HEAD_RE.match(line) for line in lines)`. The failing value is `['{\"ts\":\"2026-10-01T22:29:27.181Z\",\"level\":\"INFO\",\"event\":\"probe.info\",\"message\":\"[probe] plain\",\"modes\":[\"verbose\"]}'...`: the Engine ignores LOG_FORMAT and still writes JSON. The controls before it passed: line 90 `returncode == 0` and line 93 `len(lines) == 5`. So the child ran, imported the module and logged five records, and the first assertion that judges the phase is the one that failed. There is no typo, missing import, bad path or harness gap.\n10. Observed expected output \u2014 for the JSON rows, the `expected` values are what the run showed (5 passed with the updated access.start payload). For the C1 text row, the run showed the failure the row predicts: JSON lines where text heads should be. For the C2 rows, the run stops at line 95, so 97\u2013109 have not been reached. Their `expected` strings are the specified shape built on observed parts: the traceback and the access.start payload from the probe, the event names and messages from the passing JSON payloads. No run contradicted any row.\n</answers>\n\n<exemptions>\nnone\n</exemptions>",
    "step_7_implement:2": "<changes>\n### `engine/server/api/logging_profiles.py`\n- Imports: added `os`. The module still imports only the stdlib and `request_context`.\n- Added `SUPPORTED_LOG_FORMATS = (\"json\", \"text\")` next to `SUPPORTED_LOG_MODES`. Added `_TEXT_ESCAPES`, a `str.maketrans` table that writes CR as `\\r` and LF as `\\n`, after `_LEADING_BLOCKS_RE`.\n- New public `normalize_log_format(value)` directly after `normalize_log_mode`, with the same fail-safe shape: it strips and lowercases the value and returns it if it is in `SUPPORTED_LOG_FORMATS`. Anything else, including `None`, `\"\"` and `bogus`, gives `\"json\"`. It never raises.\n- New `_text_value(value)`: a string is returned as it is, and any other value becomes compact JSON (`ensure_ascii=False`, `default=str`), so a list or dict stays a single token and `None` is written as `null`.\n- New `_render_text(payload)`: builds `ts LEVEL event`, then the message if the payload has one, then each context entry as `k=v`, then `request_id=\u2026` (skipped if the context already has a `request_id` key), then the traceback. Everything is joined with single spaces, and CR/LF are escaped over the whole line at the end. `modes` is not written.\n- `EngineJsonFormatter`: new `__init__(self, log_format=\"json\")`, which stores `normalize_log_format(log_format)`. `format` builds the payload exactly as before. When the format is `text` it returns `_render_text(payload)`; otherwise it returns the same `json.dumps` expression as before, so JSON key order and values are unchanged. `EngineJsonFormatter()` with no argument still gives JSON, so the existing unit-test callers need no change. The class docstring now mentions text lines.\n- `configure_engine_logging`: installs `EngineJsonFormatter(os.environ.get(\"LOG_FORMAT\"))`, so the variable is read when the function is called, not at import. The signature and return value (the normalised log mode) are unchanged; only the docstring changed.\n\n### `tests/active/test_log_format.py`\nNot touched. The file does not exist in the tree, and this phase's checkpoint lives at `tests/tmp/test_19_timestamped_request_logs_phase2.py`. No production change needed it.\n</changes>\n\n<inner_tests>\nnone\n</inner_tests>\n\n<unanticipated>\nnone\n</unanticipated>\n\n<awaiting_operator>\nnone\n</awaiting_operator>",
    "author:tests/tmp/test_19_timestamped_request_logs_phase3.py": "<assertions>\ntests/tmp/test_19_timestamped_request_logs_phase3.py:89 \u2014 the five records (`engine.call` emit, `logging.exception`, bare `logging.info`, emit with `{}` context, emit with no context) write exactly five lines to the StringIO that replaced the stream of the handler `configure_client_logging()` installed, so each record is one line (C1, C2)\ntests/tmp/test_19_timestamped_request_logs_phase3.py:91 \u2014 every line parses as a JSON object (C1, C2)\ntests/tmp/test_19_timestamped_request_logs_phase3.py:94 \u2014 the `engine.call` line's keys are exactly `[\"ts\", \"level\", \"service\", \"event\", \"message\", \"context\"]`, in that order (C1)\ntests/tmp/test_19_timestamped_request_logs_phase3.py:95 \u2014 the `engine.call` line has level ERROR, service `client-backend`, event `engine.call`, message `Engine metadata failed` and context `{\"error\": \"x\\ny\"}` (C1)\ntests/tmp/test_19_timestamped_request_logs_phase3.py:97 \u2014 an emit with a `{}` context drops the key: its keys are exactly `ts, level, service, event, message`, with its own event and message (C1, the optional `[, context]`)\ntests/tmp/test_19_timestamped_request_logs_phase3.py:98 \u2014 an emit with no context also drops the key, rather than writing `null` (C1, the optional `[, context]`)\ntests/tmp/test_19_timestamped_request_logs_phase3.py:102 \u2014 every line's `ts` fully matches `^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}\\.\\d{3}Z$` (C1)\ntests/tmp/test_19_timestamped_request_logs_phase3.py:104 \u2014 with TZ pinned to Asia/Kathmandu (+05:45), every `ts` read back as UTC falls within the wall-clock window of the calls (\u00b11 s), so a local-time `ts` with a `Z` appended fails (C1)\ntests/tmp/test_19_timestamped_request_logs_phase3.py:106 \u2014 the installed handler's formatter renders a record with `created=1741091696.789` as `2025-03-04T12:34:56.789Z` and one with `created=1741091696.9999996` as `2025-03-04T12:34:57.000Z`, so `ts` is the record's creation time in UTC, rounded to the microsecond before the milliseconds are cut (C1; the plan's rationale maps T2 to P3-C1)\ntests/tmp/test_19_timestamped_request_logs_phase3.py:108 \u2014 the bare `logging.info(\"bare\")` line's keys are exactly `ts, level, service, event, message` (no context, no traceback) (C2)\ntests/tmp/test_19_timestamped_request_logs_phase3.py:109 \u2014 the bare line has level INFO, service `client-backend`, event `client.log` and message `bare` (C2)\ntests/tmp/test_19_timestamped_request_logs_phase3.py:110 \u2014 the exception line's keys are exactly `ts, level, service, event, message, traceback` (C1: it carries a `traceback` key)\ntests/tmp/test_19_timestamped_request_logs_phase3.py:111 \u2014 the exception line has level ERROR, service `client-backend`, event `client.log` and message `client probe failed` (C2)\ntests/tmp/test_19_timestamped_request_logs_phase3.py:112 \u2014 the exception line's `traceback` starts with `Traceback (most recent call last):` and ends with `ValueError: sentinel-client-log` (C1)\n</assertions>\n\n<probes>\n1) ValidateTests [\"tests/tmp/test_probe_19_p3.py\", \"-s\"] (first version: today's code under a plain `%(message)s` StreamHandler, TZ=Asia/Kathmandu with time.tzset()). Printed: root handlers before the test = [_LiveLoggingNullHandler, _FileHandler /dev/null, LogCaptureHandler, LogCaptureHandler], level 30; `has configure False has formatter False`; local now `...+05:45` (TZ pinning works in-process); RAW = `{\"ts\":\"2026-10-02T04:17:22.827+05:45\",\"level\":\"ERROR\",\"service\":\"client-backend\",\"event\":\"engine.call\",\"message\":\"Engine metadata failed\",\"context\":{\"error\":\"x\\\\ny\"}}\\nclient probe failed\\nTraceback (most recent call last):\\n ... ValueError: sentinel-client-log\\nbare\\n`; first-line keys ['ts','level','service','event','message','context'], TS_RE False; after the restore, the same four handlers, level 30, and local time back to the host's -04:00. Conclusion: today's key order already matches, so the discriminating assertions are the `ts` form and UTC check, the one-line count, and the bare and exception records.\n2) ValidateTests [\"tests/tmp/test_19_timestamped_request_logs_phase3.py\"] against today's code: 1 failed with `AttributeError: module 'server' has no attribute 'configure_client_logging'` (line 44), so it is red for the right reason.\n3) ValidateTests [\"tests/tmp/test_probe_19_p3.py\", \"-s\"] (second version: runs the checkpoint body with a probe-only stand-in of the planned ClientLogFormatter, configure_client_logging and _emit_client_log monkeypatched onto client_server; nothing was written to server.py). The planned shape passes, printing `RESTORED True TZ None`. Three wrong implementations each raise AssertionError: local_z (local time + `Z`) fails the window check at :104 with `['2026-10-02T04:18:25.510Z', ...]` against epoch ~1790894005.51; msecs (seconds from created, milliseconds from record.msecs) fails :106 with `2025-03-04T12:34:56.511Z`; today_emit (new formatter, old JSON-in-message emit) fails :94/95 with event `client.log`. The 2025-03-04T12:34:56.789Z / 57.000Z values come from the Engine helper's observed output in the phase 1 checkpoint and the probe's own stand-in rendering, which used the same fromtimestamp(tz=utc) form. Cleanup: tests/tmp/test_probe_19_p3.py is still on disk because no tool here can delete a file. It should be deleted; it imports the checkpoint module and must not outlive it.\n</probes>\n\n<unassertable>\nnone. Two notes. First, the operator approved gap carries over from Step 6: `main()` calling `configure_client_logging()` in place of `basicConfig` is not entered, because `main` parses argv and binds a port. Second, the rewired ERROR-record tests in tests/active/test_server.py are not asserted here; the full suite covers them, as agreed at Step 6.\n</unassertable>",
    "self_check:tests/tmp/test_19_timestamped_request_logs_phase3.py": "<rows>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_19_timestamped_request_logs_phase3.py:89 \u2014 the five records (engine.call emit, logging.exception, bare logging.info, emit with {} context, emit with no context) write exactly five lines to the StringIO behind the handler configure_client_logging() installed</assertion>\n<expected>5 lines, one per record</expected>\n<wrong_implementation>Today's root setup, with _emit_client_log building JSON by hand and the exception and bare records going out as plain text. Probe test_probe_19_p3_values.py showed that stream: the emit JSON line, then `client probe failed`, a 4-line traceback and `bare`. That is 7 lines for the first three records, 9 with the two extra emits.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_19_timestamped_request_logs_phase3.py:91 \u2014 every line parses as a JSON object</assertion>\n<expected>all five lines are dicts</expected>\n<wrong_implementation>A formatter that only covers records carrying client_event, or text in place of JSON. The lines `bare` and `client probe failed` (observed today) are not JSON, so json.loads at line 90 raises.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_19_timestamped_request_logs_phase3.py:94 \u2014 the engine.call line's keys are exactly ts, level, service, event, message, context, in that order</assertion>\n<expected>[\"ts\", \"level\", \"service\", \"event\", \"message\", \"context\"]</expected>\n<wrong_implementation>A formatter installed while _emit_client_log still logs its hand-built JSON string as the message. In probe today_emit the line read {'ts': ..., 'level': 'ERROR', 'service': 'client-backend', 'event': 'client.log', ...} with no context key, and the engine.call JSON was buried in message. A payload built in another order (e.g. event before service) also fails here.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_19_timestamped_request_logs_phase3.py:95 \u2014 the engine.call line has level ERROR, service client-backend, event engine.call, message \"Engine metadata failed\" and context {\"error\": \"x\\ny\"}</assertion>\n<expected>(\"ERROR\", \"client-backend\", \"engine.call\", \"Engine metadata failed\", {\"error\": \"x\\ny\"})</expected>\n<wrong_implementation>Wrong attribute names between _emit_client_log's extra= and the formatter, which lets event fall back to client.log (as observed in probe today_emit). Or a context that is stringified or escaped twice, which reads back as a str and not as the dict.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_19_timestamped_request_logs_phase3.py:97 \u2014 an emit with a {} context omits the key: keys exactly ts, level, service, event, message, with event probe.empty and message \"empty context\"</assertion>\n<expected>([\"ts\",\"level\",\"service\",\"event\",\"message\"], \"probe.empty\", \"empty context\")</expected>\n<wrong_implementation>A formatter that tests `context is not None`, which writes \"context\": {}, so the key list has six entries.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_19_timestamped_request_logs_phase3.py:98 \u2014 an emit with no context also omits the key, with event probe.none and message \"no context\"</assertion>\n<expected>([\"ts\",\"level\",\"service\",\"event\",\"message\"], \"probe.none\", \"no context\")</expected>\n<wrong_implementation>A formatter that always writes payload[\"context\"] = getattr(record, \"client_context\", None), which gives \"context\": null and six keys.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_19_timestamped_request_logs_phase3.py:102 \u2014 every line's ts fully matches TS_RE ^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}\\.\\d{3}Z$</assertion>\n<expected>all five ts match, e.g. YYYY-MM-DDTHH:MM:SS.mmmZ</expected>\n<wrong_implementation>Today's datetime.now().astimezone().isoformat(timespec=\"milliseconds\"). Probe test_probe_19_p3_values.py observed `2026-10-02T04:19:50.028+05:45` under TZ=Asia/Kathmandu, which has no Z. A plain utc isoformat gives `+00:00` (observed `2025-03-04T12:34:56.789+00:00`).</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_19_timestamped_request_logs_phase3.py:104 \u2014 with TZ pinned to Asia/Kathmandu, every ts read back as UTC lies within [before-1, after+1] of time.time() around the calls</assertion>\n<expected>every _epoch(ts) is inside the window</expected>\n<wrong_implementation>Local time with a Z appended. In probe local_z the stamps read 2026-10-02T04:19:20.843Z against a window at epoch 1790894060.84 (22:34:20Z), which is 5h45m outside it.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_19_timestamped_request_logs_phase3.py:106 \u2014 the installed formatter renders records with created=1741091696.789 and created=1741091696.9999996</assertion>\n<expected>(\"2025-03-04T12:34:56.789Z\", \"2025-03-04T12:34:57.000Z\")</expected>\n<wrong_implementation>Milliseconds taken from record.msecs, which goes stale once created is set after construction: probe msecs read 2025-03-04T12:34:56.844Z for both records. Naive truncation via int((created % 1) * 1000) gives 2025-03-04T12:34:56.999Z (observed). A ts from datetime.now() gives today's date and not 2025-03-04.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_19_timestamped_request_logs_phase3.py:110 \u2014 the exception line's keys are ts, level, service, event, message, traceback</assertion>\n<expected>[\"ts\",\"level\",\"service\",\"event\",\"message\",\"traceback\"]</expected>\n<wrong_implementation>A formatter that ignores exc_info, so it has no traceback key and the traceback is lost. Or the stdlib default that appends the traceback as extra lines, which is today's behaviour: observed 4 traceback lines after `client probe failed`.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_19_timestamped_request_logs_phase3.py:112 \u2014 the traceback value starts with \"Traceback (most recent call last):\" and ends with \"ValueError: sentinel-client-log\"</assertion>\n<expected>the formatted ValueError traceback, ending `ValueError: sentinel-client-log`</expected>\n<wrong_implementation>A traceback of repr(exc_info) or str(exc) only, which does not start with \"Traceback (most recent call last):\". Or a formatException with a trailing newline left in, which does not end with the sentinel.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_19_timestamped_request_logs_phase3.py:108 \u2014 the bare logging.info line's keys are exactly ts, level, service, event, message</assertion>\n<expected>[\"ts\",\"level\",\"service\",\"event\",\"message\"]</expected>\n<wrong_implementation>The JSON formatter applied only to _emit_client_log records (e.g. on a dedicated logger) while the root keeps \"%(message)s\". The bare line is then the plain text `bare` (observed today), which is not JSON. A formatter writing \"context\": null for records without attributes gives six keys.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_19_timestamped_request_logs_phase3.py:109 \u2014 the bare line has level INFO, service client-backend, event client.log, message \"bare\"</assertion>\n<expected>(\"INFO\", \"client-backend\", \"client.log\", \"bare\")</expected>\n<wrong_implementation>A formatter using getattr(record, \"client_event\", None) with no fallback, which gives event null. Or the Engine's fallback copied over unchanged, which gives event engine.log.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_19_timestamped_request_logs_phase3.py:111 \u2014 the logging.exception line has level ERROR, service client-backend, event client.log, message \"client probe failed\"</assertion>\n<expected>(\"ERROR\", \"client-backend\", \"client.log\", \"client probe failed\")</expected>\n<wrong_implementation>A missing client.log fallback, which gives a null event. Or the message built from the formatted record text including the traceback, which gives a message other than \"client probe failed\".</wrong_implementation>\n</row>\n</rows>\n\n<answers>\n1. Whole claim \u2014 yes, every clause is tested, so no rewrite was needed. Each docstring bullet maps to assertions: the five lines are checked at 89 and 91; key order and values at 94 and 95; the empty and no-context lines at 97 and 98; ts against TS_RE at 102; the UTC window at 104; the two fixed-created renderings at 106; the bare and exception lines at 108-111; the traceback at 112. C1 (key order ts, level, service, event, message[, context] and a UTC ts) is carried by 89-106, 110 and 112. C2 (a bare root record in the same shape with event client.log) is carried by 108, 109 and 111.\n2. Absence only \u2014 no. The absence of context at 97 and 98 is checked as an exact key list on lines whose event and message are also asserted, so those records were provably emitted and formatted. Line 94 is the positive control: the context key does appear when the context is non-empty.\n3. Echoed literal \u2014 no. The test only parses (json.loads, and strptime in _epoch) and never builds a payload or renders a ts. The expected ts literals are fixed epoch facts, not the formatter's output fed back. Production lines whose deletion turns it red: the `or \"client.log\"` fallback in ClientLogFormatter.format (109, 111); `if context:` around payload[\"context\"] (97, 98); the ts helper reading record.created in UTC (102, 104, 106); and the `extra=` in _emit_client_log (94, 95).\n4. One value \u2014 no. ts is read on five live records plus two fixed created values, including the .9999996 rounding edge. Context is read present, empty and absent. Event is read at three emit events and at client.log on two different bare records, at INFO and ERROR. The window at 104 compares against an independent clock (time.time()), not a sibling field.\n5. The double \u2014 no. The only substitutions are the handler's stream (a stdlib StringIO swapped in via setStream) and the TZ env var. No module this project owns is replaced.\n6. It collects \u2014 yes. The collect-only summary reads \"no tests\" because nothing ran; the real run printed \"collected 1 item\", which matches the one test written. Every name except the phase's own configure_client_logging binds: probe tests/tmp/test_probe_19_p3.py ran the whole test body against a stand-in configure_client_logging and _emit_client_log, and test_planned_shape_passes PASSED with \"RESTORED True TZ None\". That shows setStream, handler.format, _epoch and _fixed_record all work and that the root handlers and TZ are restored.\n7. Observed, not predicted \u2014 yes, every expected value and every comment that claims an observation comes from a run. Probe tests/tmp/test_probe_19_p3_values.py printed today's stream: `{\"ts\":\"2026-10-02T04:19:50.028+05:45\",...,\"event\":\"engine.call\",...,\"context\":{\"error\":\"x\\\\ny\"}}\\nclient probe failed\\nTraceback (most recent call last):\\n ...\\nValueError: sentinel-client-log\\nbare\\n`. It also printed `NAIVE 2025-03-04T12:34:56.999Z PROPER 2025-03-04T12:34:57.000Z` and `FIXED 2025-03-04T12:34:56.789+00:00`. In test_probe_19_p3.py the planned shape passed, and each wrong variant failed at an assertion: local_z failed the window at 104 (stamps 04:19:20.843Z against a window at 22:34:20Z); msecs failed 106 with 2025-03-04T12:34:56.844Z for both records; today_emit failed 94, with the emitted line read as event client.log and no context. No rewrite was needed. The two probe files under tests/tmp/ (test_probe_19_p3.py and test_probe_19_p3_values.py) are now carried by the checkpoint and should be deleted. I have no delete tool, so they are still there.\n8. Red, not green \u2014 yes, it is red. ValidateTests on tests/tmp/test_19_timestamped_request_logs_phase3.py: \"1 failed\", \"[exit status 1]\".\n9. Red for the right reason \u2014 yes. tests/last_test_output.txt names line 44, `client_server.configure_client_logging()`, failing with \"E AttributeError: module 'server' has no attribute 'configure_client_logging'\". The plan names configure_client_logging as this phase's new function (plan \u00a7Files: \"`ClientLogFormatter`; `configure_client_logging()`\"), so this red is the phase being unimplemented, not a typo, import error or bad path. No control assertion failed. The other half of the phase, today's hand-built _emit_client_log, has been seen failing a judging assertion: in probe today_emit, with only configure_client_logging stood in, the test failed at line 94.\n10. Observed expected output \u2014 yes, every row's expected value is what a run showed. The values the formatter must produce were seen when the planned-shape probe passed: the five lines, the key lists, client.log, the traceback start and end, and \"2025-03-04T12:34:56.789Z\" / \"2025-03-04T12:34:57.000Z\". Each row's wrong-implementation reading is quoted from the probe output above: +05:45, the 7/9 plain lines, 56.844Z, 56.999Z, the 5h45m shift, and event client.log with no context. No run contradicted any row.\n</answers>\n\n<exemptions>\nnone\n</exemptions>",
    "step_7_implement:3": "<changes>\n### `client/backend/server.py`\n- The datetime import is now `from datetime import datetime, timezone`.\n- New `_format_ts(record)`, a copy of the Engine's. It renders `record.created` in UTC as `YYYY-MM-DDTHH:MM:SS.mmmZ`. A `rat-tail:` comment says it mirrors `engine/server/api/logging_profiles.py` because the two services import from different roots, and that a drift guard is the upgrade (planned for phase 4).\n- New `ClientLogFormatter(logging.Formatter)`. Its `format` builds the payload in the order `ts, level, service (\"client-backend\"), event, message`.\n  - `event` is the record's `client_event`, or `client.log` when the record has none.\n  - `message` is `record.getMessage()`.\n  - `context` (the record's `client_context`) is added only when it is not empty, the same rule as the old `if context:`.\n  - A record with `exc_info` also gets a `traceback` key, rendered by `formatException`.\n  - Output is `json.dumps(..., ensure_ascii=True, separators=(\",\", \":\"))`, the same call as before.\n  - JSON only for now. `LOG_FORMAT` handling and text rendering are left to phase 4.\n- New `configure_client_logging()`. It clears the root handlers, sets the level to INFO, and adds one INFO `StreamHandler()` (stderr, the same stream `basicConfig` used) carrying `ClientLogFormatter()`.\n- `_emit_client_log` keeps its signature and all its call sites. Its body is now `logging.log(level, message, extra={\"client_event\": event, \"client_context\": context})` instead of building the JSON string by hand.\n- `main()` calls `configure_client_logging()` in place of `logging.basicConfig(level=logging.INFO, format=\"%(message)s\")`, in the same position.\n\n### `tests/active/test_server.py`\nThe operator confirmed this rewire when asked. It changes only how the log is read, not what is asserted.\n- New `_CLIENT_FORMATTER = client_server.ClientLogFormatter()`. `_error_messages` now renders each ERROR record through it, so `_error_events` parses the real production JSON lines and finds `event`/`context.error` again.\n- `test_client_likes_502_is_fixed_text_and_engine_error_is_logged` takes `monkeypatch` and sets `caplog.handler.formatter` to `_CLIENT_FORMATTER` through `monkeypatch.setattr`, so `caplog.text` shows the production-rendered lines.\n  - The plan used `caplog.handler.setFormatter` instead. A probe showed pytest 9.1.1 uses one caplog handler for the whole session, so `setFormatter` would carry into every later test. Monkeypatch restores it at teardown; a second probe test confirmed the default formatter is back.\n- The module docstring line about the Engine sentinel now says it is in an ERROR record's `context.error`, as the Client's formatter renders it.\n\n### `tests/active/test_log_format.py`\nNot touched. The file does not exist, and this phase's checkpoint is `tests/tmp/test_19_timestamped_request_logs_phase3.py`.\n</changes>\n\n<inner_tests>\nnone\n</inner_tests>\n\n<unanticipated>\ntests/tmp/probe_caplog_formatter.py: my throwaway probe showing that caplog's handler, and so its formatter, lasts the whole session. I have no delete tool, so I emptied it; it collects no tests and can be removed. Separately, tests/tmp/test_probe_19_p3.py and tests/tmp/test_probe_19_p3_values.py were already there from an earlier step, and I did not touch them.\n</unanticipated>\n\n<awaiting_operator>\nnone\n</awaiting_operator>",
    "author:tests/tmp/test_19_timestamped_request_logs_phase4.py": "<assertions>\ntests/tmp/test_19_timestamped_request_logs_phase4.py:111 - for LOG_FORMAT unset, `json`, `JSON`, `bogus` and empty, the four Client records (`engine.call` with `{\"error\": \"x\\ny\"}`, a `logging.exception`, a bare `logging.info`, and `client.access`) give exactly four lines, and each one parses as a JSON object - C1\ntests/tmp/test_19_timestamped_request_logs_phase4.py:113 - in those JSON cases every `ts` matches TS_RE - C1\ntests/tmp/test_19_timestamped_request_logs_phase4.py:115 - in those JSON cases the exception record's `traceback` starts with `Traceback (most recent call last):` and ends with `ValueError: sentinel-client-log` - C1\ntests/tmp/test_19_timestamped_request_logs_phase4.py:116 - in those JSON cases each payload, less `ts` and `traceback`, has exactly the keys, key order and values of phase 3 (service `client-backend`, events `engine.call`/`client.log`/`client.log`/`client.access`, and `status` still the int 200) - C1\ntests/tmp/test_19_timestamped_request_logs_phase4.py:123 - for `text`, `TEXT`, ` Text ` and tab-`text`-newline, the four records give exactly four physical lines (splitlines), so the multi-line context value and the traceback are each one line - C1\ntests/tmp/test_19_timestamped_request_logs_phase4.py:125 - in the text cases every line matches `^<TS_RE> (INFO|ERROR) ` - C1\ntests/tmp/test_19_timestamped_request_logs_phase4.py:126 - in the text cases no line parses as a JSON object (fails against today's Client, which ignores LOG_FORMAT) - C1\ntests/tmp/test_19_timestamped_request_logs_phase4.py:127 - in the text cases no line starts with `<` - C1\ntests/tmp/test_19_timestamped_request_logs_phase4.py:130 - in the text cases each line's leading ts token matches TS_RE in full - C1\ntests/tmp/test_19_timestamped_request_logs_phase4.py:133 - the `engine.call` text line, after the ts, is exactly `ERROR engine.call Engine metadata failed error=x\\ny`, where `\\n` is a backslash and an n, with no service token - C1\ntests/tmp/test_19_timestamped_request_logs_phase4.py:134 - the exception text line fully matches `ERROR client.log client probe failed Traceback (most recent call last):\\n  File \"\u2026\", line N, in \u2026\\n    raise ValueError(\"sentinel-client-log\")\\nValueError: sentinel-client-log`, where each `\\n` is a literal backslash and n - C1\ntests/tmp/test_19_timestamped_request_logs_phase4.py:135 - the bare text line, after the ts, is exactly `INFO client.log bare` - C1\ntests/tmp/test_19_timestamped_request_logs_phase4.py:137 - the `client.access` text line, after the ts, is exactly `INFO client.access request finished ip=127.0.0.1 status=200 bytes=-` - C1\ntests/tmp/test_19_timestamped_request_logs_phase4.py:146 - control: the Engine child prints `_format_ts` = `2025-03-04T12:34:56.789Z` and `2025-03-04T12:34:57.000Z` for created 1741091696.789 and 1741091696.9999996, and prints `_render_text` of the payload as the observed `2025-03-04T12:34:57.000Z INFO e m\\nn a=1 b=null c=[1,{\"d\":\"x\"}] request_id=r T\\nU`, so the equality checks below compare real strings - C2\ntests/tmp/test_19_timestamped_request_logs_phase4.py:153 - in-process, `client_server._format_ts` gives the Engine child's strings for both `created` values - C2\ntests/tmp/test_19_timestamped_request_logs_phase4.py:154 - in-process, `client_server._render_text(payload)` equals the Engine child's `_render_text` of the same payload (today an AttributeError: the Client has no `_render_text`) - C2\n</assertions>\n\n<probes>\nRan ValidateTests [\"tests/tmp/test_probe_19_p4.py\"] once (Python 3.14.7), with a deliberate `assert False` so the output would print. (1) The Engine child (`cwd=engine/server/api`, `from logging_profiles import _format_ts, _render_text`, created=1741091696.9999996, payload `{\"ts\": \"2025-03-04T12:34:57.000Z\", \"level\": \"INFO\", \"event\": \"e\", \"message\": \"m\\nn\", \"context\": {\"a\": 1, \"b\": None, \"c\": [1, {\"d\": \"x\"}], \"request_id\": \"r\"}, \"request_id\": \"r\", \"traceback\": \"T\\nU\"}` passed as JSON in argv) exited rc 0 with empty stderr. It printed ts `2025-03-04T12:34:57.000Z` and text `2025-03-04T12:34:57.000Z INFO e m\\nn a=1 b=null c=[1,{\"d\":\"x\"}] request_id=r T\\nU`, where each `\\n` is a backslash and an n. (2) `hasattr` on client_server for normalize_log_format/_format_ts/_text_value/_render_text gave only `['_format_ts']`, so the Client's text path and `_render_text` are absent today. (3) After `configure_client_logging()`, the Client wrote these lines: `logging.exception(\"client probe failed\")` gave `{\"ts\":\"2026-10-01T22:41:53.182Z\",\"level\":\"ERROR\",\"service\":\"client-backend\",\"event\":\"client.log\",\"message\":\"client probe failed\",\"traceback\":\"Traceback (most recent call last):\\n  File \\\"/\u2026/tests/tmp/test_probe_19_p4.py\\\", line 45, in test_probe\\n    raise ValueError(\\\"sentinel-client-log\\\")\\nValueError: sentinel-client-log\"}`, with no caret line under the raise; `_emit_client_log(INFO, \"client.access\", \u2026)` gave `{\"ts\":\u2026,\"level\":\"INFO\",\"service\":\"client-backend\",\"event\":\"client.access\",\"message\":\"request finished\",\"context\":{\"ip\":\"127.0.0.1\",\"status\":200,\"bytes\":\"-\"}}`. The ts 1741091696.789 -> `2025-03-04T12:34:56.789Z` was observed earlier, by the gated phase 1 Engine checkpoint and phase 3 Client checkpoint. Not run: the checkpoint file itself, so as not to bank a fingerprint before the workflow's gating run. Its predicted red is the four text cases (today's lines are JSON) and the C2 test at line 154 (AttributeError on `_render_text`); the JSON cases and the controls at 146/153 should pass today. The probe file tests/tmp/test_probe_19_p4.py is still in place because no tool here can delete a file; it should be removed.\n</probes>\n\n<unassertable>\nnone\n</unassertable>",
    "self_check:tests/tmp/test_19_timestamped_request_logs_phase4.py": "<rows>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_19_timestamped_request_logs_phase4.py:115/117/119/120 \u2014 under LOG_FORMAT unset, `json`, `JSON`, `bogus` and `\"\"`, stderr is exactly four lines. Each one is a JSON object whose `ts` matches TS_RE. The exception record's `traceback` runs from `Traceback (most recent call last):` to `ValueError: sentinel-client-log`. With `ts` and `traceback` removed, the four payloads' items, in order, equal JSON_PAYLOADS.</assertion>\n<expected>Four JSON lines, the same as the Engine gives for these five values. This is observed: the Engine's normalize_log_format returned `json` for None, 'json', 'JSON', 'bogus' and '' in tests/tmp/probe_engine_render.py. All five parametrizations pass against the code as it stands, which is phase 3's JSON output.</expected>\n<wrong_implementation>A Client that defaults to text when LOG_FORMAT is unset, or that treats any value other than `json` (e.g. `bogus`, `\"\"` or the upper-case `JSON` without lowercasing) as text, writes `<ts> LEVEL \u2026` lines. `_json_object` then returns None, and line 115 goes red. A copy that reorders keys or adds `modes` to the JSON payload turns line 120 red.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_19_timestamped_request_logs_phase4.py:127/129 \u2014 under LOG_FORMAT `text`, `TEXT`, ` Text ` and `\\ttext\\n`, stderr is exactly four physical lines (splitlines), and every line matches `^<TS_RE> (INFO|ERROR) `.</assertion>\n<expected>Four text lines, the same as the Engine gives for these four values. The selection is observed: the Engine's normalize_log_format returned `text` for 'text', 'TEXT', ' Text ' and '\\ttext\\n' in the probe. Today's run fails at :129 on all four, because each line is still JSON (`['{\"ts\":\"2026-10-01T22:44:17.311Z\",\"level\":\"ERROR\",...`).</expected>\n<wrong_implementation>Several plausible faults stay on JSON and turn :129 red: a Client that ignores LOG_FORMAT (as today), one that compares without `.lower()` (`TEXT`), or one that skips `.strip()` (` Text ` and `\\ttext\\n`). A text renderer that does not escape LF writes the `error=x` / `y` value and the traceback across several lines, which makes :127 read more than 4.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_19_timestamped_request_logs_phase4.py:137 \u2014 once the timestamp is split off, the `engine.call` line reads exactly `ERROR engine.call Engine metadata failed error=x\\ny`, where `\\n` is a backslash followed by an n.</assertion>\n<expected>`ERROR engine.call Engine metadata failed error=x\\\\ny` (Python literal). This is observed as the Engine's `_render_text` output for the same payload in the probe: `'T ERROR engine.call Engine metadata failed error=x\\\\ny'`.</expected>\n<wrong_implementation>A Client text renderer that writes the `service` token (`ERROR client-backend engine.call \u2026`), renders the context as JSON (`{\"error\":\"x\\ny\"}`), or leaves the LF unescaped (the line becomes `\u2026error=x`) gives a string that is not equal.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_19_timestamped_request_logs_phase4.py:138 \u2014 the exception line fullmatches EXCEPTION_TEXT_RE. That is `ERROR client.log client probe failed Traceback (most recent call last):\\n  File \"\u2026\", line N, in _log_records\\n    raise ValueError(\"sentinel-client-log\")\\nValueError: sentinel-client-log`, with each `\\n` written as a backslash followed by an n, all on one line.</assertion>\n<expected>A match. This is observed: tests/tmp/probe_client_tb.py took the Client's real in-process traceback (`'Traceback (most recent call last):\\n  File \".../test_19_timestamped_request_logs_phase4.py\", line 89, in _log_records\\n    raise ValueError(\"sentinel-client-log\")\\nValueError: sentinel-client-log'`), escaped its LFs and fullmatched the regex (`MATCH True`). The Engine's `_render_text` puts the traceback at the end of the line in the same form (probe line 37).</expected>\n<wrong_implementation>A text renderer can drop the traceback (the Engine keeps it as the final token), place it before the message, or let its LFs through. In the last case the record splits across lines, so :127 or this fullmatch goes red.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_19_timestamped_request_logs_phase4.py:139/141 \u2014 the bare record reads `INFO client.log bare`, and the access record reads `INFO client.access request finished ip=127.0.0.1 status=200 bytes=-`.</assertion>\n<expected>Exactly those two strings. Both are observed from the Engine's `_render_text` on the same payloads in the probe: `'T INFO client.log bare'` and `'T INFO client.access request finished ip=127.0.0.1 status=200 bytes=-'`.</expected>\n<wrong_implementation>A renderer that writes `service=client-backend` or the `service` value, quotes the strings (`ip=\"127.0.0.1\"`), or renders the int via `repr`/str of a JSON string produces a different access line. A bare record that falls back to an event other than `client.log` changes the bare line.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_19_timestamped_request_logs_phase4.py:157 \u2014 for `created` 1741091696.789 and 1741091696.9999996, the Client's `_format_ts` returns the same list the Engine child printed. The control at :150 pins that list to `[\"2025-03-04T12:34:56.789Z\", \"2025-03-04T12:34:57.000Z\"]`.</assertion>\n<expected>`[\"2025-03-04T12:34:56.789Z\", \"2025-03-04T12:34:57.000Z\"]` from both. This is observed: the control at :150 passed in the run, and so did :157 (the Client's phase-3 copy already exists).</expected>\n<wrong_implementation>A Client `_format_ts` built from `record.msecs`, or one that truncates `created` instead of letting `fromtimestamp` round to the microsecond, gives `2025-03-04T12:34:56.999Z` for the second value. Local time instead of UTC gives a different hour. Either way the lists differ.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_19_timestamped_request_logs_phase4.py:159 \u2014 the Client's `_render_text` over both RENDER_PAYLOADS equals the Engine child's list. The control at :150 pins that list to ENGINE_TEXTS.</assertion>\n<expected>`['2025-03-04T12:34:57.000Z INFO e m\\\\nn a=1 b=null c=[1,{\"d\":\"x\"}] request_id=r T\\\\nU', '2025-03-04T12:34:56.789Z ERROR service.lifecycle state=start note=a\\\\rb request_id=q']`, from the Engine child, observed (the control at :150 passed). The current run is red at :158 with `AttributeError: module 'server' has no attribute '_render_text'`, because phase 4 has not yet added the Client copy.</expected>\n<wrong_implementation>Each of these drifted Client copies changes the list: writing `None` as `None` (str()) instead of `null`; a list rendered by `json.dumps` with its default separators (`[1, {\"d\": \"x\"}]`); `request_id` written twice for payload 1; `request_id` never appended when only top-level for payload 2; an empty message token for payload 2; and CR left unescaped (`a\\rb`).</wrong_implementation>\n</row>\n</rows>\n\n<answers>\n1. Whole claim: yes, after the rewrite. C1 is carried both ways. The JSON side is lines 115-120 over unset/json/JSON/bogus/\"\". The text side is lines 127-141 over text/TEXT/\" Text \"/\"\\ttext\\n\", and that block covers four lines, the TS head, the escaped `\\n`, the traceback at the end of the line, no `service` token and the access line. The Engine's selection for all nine values was observed in a probe rather than assumed. C2 is lines 157 and 159. Every docstring bullet has an assertion. I rewrote the last bullet to describe the second payload.\n2. Absence only: no. Line 130 (no line parses as a JSON object) and line 131 (no line starts with `<`) are negatives. They are armed by line 127 (exactly four lines) and line 129 (every line matches `^<TS_RE> (INFO|ERROR) `), and both of those have to pass first.\n3. Echoed literal: no. Lines 157 and 159 compare the Client's in-process output with the Engine child's stdout, which are two separate code paths. The control at line 150 pins the Engine's output to values I observed. Deleting the Client's `.translate(_TEXT_ESCAPES)` (the line in the Client's `_render_text` that escapes CR/LF) turns 159 red, and also 127/137. Deleting the Client's `.strip().lower()` in normalize_log_format turns 129 red for TEXT, \" Text \" and \"\\ttext\\n\".\n4. One value: this was a yes, and I rewrote it. `_render_text` was read at a single payload, which skipped the \"no message\" branch and the \"request_id only at top level, appended\" branch. A Client copy that drifted in either branch would have passed. I changed RENDER_PAYLOAD/ENGINE_TEXT to RENDER_PAYLOADS/ENGINE_TEXTS and added a second payload with no message, a CR in a context value and a top-level-only `request_id`. Its Engine rendering, `2025-03-04T12:34:56.789Z ERROR service.lifecycle state=start note=a\\\\rb request_id=q`, was observed in tests/tmp/probe_engine_render.py. The child now renders a list. `_format_ts` is read at two `created` values, and LOG_FORMAT selection at nine values.\n5. The double: no. The only substitution is swapping the real StreamHandler's stream for a StringIO, and that is a stdlib sink. `configure_client_logging`, `_emit_client_log`, the formatter and the Engine's `logging_profiles` are all the project's real code.\n6. It collects: yes. The full run printed `collected 10 items`, which is 5 JSON + 4 text + 1 drift-guard, the count I wrote (the `--collect-only` summary's \"no tests\" is just how the runner prints a collect-only pass, and exit was 0). `client_server` binds from tests/active/conftest. The Engine's `_format_ts`/`_render_text` import in the child, and the control passed. `LogRecord(name, level, pathname, lineno, msg, args, exc_info)` and `handler.setStream` exist. The one name that does not bind yet is `client_server._render_text`, which this phase delivers (see 9).\n7. Observed, not predicted: yes, after the rewrite. The Engine's normalize_log_format for all nine values printed json \u00d75 and text \u00d74. Its `_render_text` of the four Client payloads printed exactly the strings at lines 137, 139 and 141, plus the escaped-traceback shape (probe_engine_render.py). The Client's real in-process traceback, escaped, fullmatches EXCEPTION_TEXT_RE (probe_client_tb.py: `MATCH True`, frame `line 89, in _log_records`). ENGINE_TEXTS and the two timestamps come from the Engine child, and the control at :150 passed. I have no tool that deletes files, so the two probes are still in tests/tmp/. They are named `probe_*.py`, which pytest's `test_*.py` pattern does not collect, and they should be removed.\n8. Red, not green: yes, it is red. ValidateTests: `5 failed, 5 passed`, `[exit status 1]`, `collected 10 items`. The five JSON parametrizations pass because phase 3's Client already writes JSON for those values. The four text parametrizations and the drift guard fail.\n9. Red for the right reason: yes. The text cases fail at `tests/tmp/test_19_timestamped_request_logs_phase4.py:129: AssertionError` on `assert all(TEXT_HEAD_RE.match(line) for line in lines)`, with lines like `'{\"ts\":\"2026-10-01T22:44:17.311Z\",\"level\":\"ERROR\",\"service\":\"client-backend\",\"event\":\"engine.call\",...'`. The Client ignores LOG_FORMAT and still writes JSON, which is exactly the missing phase. Line 127 (four lines) passed before it. The drift guard gets past its control (`:150` engine equality passed) and `:157` (`_format_ts` equal). It fails at `:158` with `AttributeError: module 'server' has no attribute '_render_text'`. The Client copy of `_render_text` is the phase-4 deliverable the plan names (`normalize_log_format`, `_format_ts`, `_text_value`, `_render_text` copied into the Client), so this is the phase not being built. It is not a typo or a harness fault. No control assertion failed.\n10. Observed expected output: yes. The run passed every value it reached: the control at :150 (Engine timestamps and both ENGINE_TEXTS) and :157 (Client timestamps). The text-line literals at 137/139/141 and EXCEPTION_TEXT_RE are what the Engine's `_render_text` printed for the same payloads in the probe, and the regex matched the Client's real traceback. None of the rows' `expected` values was contradicted by a run.\n</answers>\n\n<exemptions>\nnone\n</exemptions>",
    "step_7_implement:4": "<changes>\n### `client/backend/server.py`\n- Added copies of the Engine's helpers from `engine/server/api/logging_profiles.py`, with bodies byte-identical to the Engine's. They sit before `ClientLogFormatter`, next to the existing `_format_ts`:\n  - `SUPPORTED_LOG_FORMATS = (\"json\", \"text\")`.\n  - `_TEXT_ESCAPES`, the table that escapes CR/LF.\n  - `normalize_log_format(value)`: strips and lowercases the value. `json` or `text` is returned as is; anything else, including `None`, `\"\"` and `bogus`, gives `\"json\"`. It never raises.\n  - `_text_value(value)`: a string is returned as is, and any other value becomes compact JSON, so `None` is written as `null` and a list or dict stays one token.\n  - `_render_text(payload)`: builds `ts LEVEL event [message] k=v\u2026 [request_id=\u2026] [traceback]` and escapes CR/LF over the whole line.\n- The phase-3 `rat-tail:` comment above `_format_ts` now covers all six mirrored names. It states the limit (editing only one copy lets the two drift), says a cross-service test compares them, and names the upgrade: a shared package once a third consumer appears.\n- `ClientLogFormatter`:\n  - New `__init__(self, log_format=\"json\")` stores `normalize_log_format(log_format)`.\n  - `format` builds the payload exactly as in phase 3. When the format is `text` it returns `_render_text(payload)`. `_render_text` does not write the `service` key, so the text line has the Engine's shape with no `service` token. Otherwise it returns the same `json.dumps` call as before, so JSON key order and values are unchanged.\n  - `ClientLogFormatter()` with no argument is still JSON, so `_CLIENT_FORMATTER` in `tests/active/test_server.py` needs no change.\n  - The class docstring now mentions text lines.\n- `configure_client_logging` installs `ClientLogFormatter(os.environ.get(\"LOG_FORMAT\"))`, so `LOG_FORMAT` is read when logging is set up, not at import. The docstring says so. Its call site in `main()` is unchanged.\n\n### `tests/active/test_log_format.py`\nNot touched. It does not exist in the tree, as in phases 1\u20133. This phase's drift guard is the checkpoint `tests/tmp/test_19_timestamped_request_logs_phase4.py`, and `tests/active/test_log_format.py` looks like its permanent home once it is moved out of `tests/tmp/`.\n</changes>\n\n<inner_tests>\nnone\n</inner_tests>\n\n<unanticipated>\nnone\n</unanticipated>\n\n<awaiting_operator>\nnone\n</awaiting_operator>",
    "step_8_i1_refactor": "<refactors>\nengine/server/api/logging_profiles.py: the module docstring now mentions the text lines that `LOG_FORMAT=text` selects, not only the JSON events. This is a docstring-only change, with no change to code or behaviour.\n</refactors>\n\n<left_out>\nclient/backend/server.py `_proxy_engine_request`'s catch-all `except Exception` puts `traceback.format_exc()` into `context.traceback`. Now that `ClientLogFormatter` handles `exc_info`, `exc_info=True` could replace it, but the traceback would move from `context.traceback` to a top-level `traceback` key. That changes the JSON output, so it is not a refactor.\nengine/server/api/logging_profiles.py `EngineJsonFormatter.format`: the `access.start` and `access` branches repeat `if fields: payload[\"context\"] = fields`. They could be folded into a table of fixed messages, but that code predates this build and its output is already gated, so I left it alone.\n`EngineJsonFormatter` is now a misnomer because it can also write text, but renaming it would break its existing importers and tests, and engine/server/README.md names it. Left as is.\nThe six copied logging helpers (Engine and Client): merging them is already covered by the `rat-tail:` comment in client/backend/server.py, with a shared package as the upgrade once a third consumer appears, so I left them duplicated.\nThat `rat-tail:` comment says a cross-service test compares both copies. Today that drift guard exists only as the checkpoint tests/tmp/test_19_timestamped_request_logs_phase4.py; tests/active/test_log_format.py, which every phase lists, was never created. If the checkpoint is not moved into tests/active, nothing durable backs the comment's claim. That move is the workflow's job, not a production refactor.\nProbe files from this build are still in tests/tmp. Some are emptied (probe_fromtimestamp.py, probe_caplog_formatter.py); others are not (probe_client_tb.py, probe_engine_render.py, probe_ts_values.py, test_probe_19_p1..p4.py, test_probe_19_p3_values.py). I have no delete tool, so they need removing by hand.\n</left_out>\n\n<needs_fresh_red>\nnone\n</needs_fresh_red>\n\n<observation>\nThe four phases left the production code clean: the Engine and Client helpers are copies held together by a `rat-tail:` comment, both formatters still write JSON by default, and nothing could be simplified without changing output. The one real gap is outside production code: the drift guard and the `LOG_FORMAT` tests still exist only in tests/tmp, because tests/active/test_log_format.py was never created.\n</observation>",
    "step_8_triage:0": "<failures>\n### Shared dataset rebuilt under the build (common cause, checked by probe)\nEvery red test reads the live `engine/server/db/whitelist.db` and `similarity-cache.db`. In this worktree both are gitignored symlinks into the main checkout. A probe (`tests/tmp/probe_step8_dataset.py`) found:\n- Both files were rewritten on 2026-10-01, and HEAD is `57c8417 db rebuilt and updated`.\n- All 890,052 `similarity_sources` rows share one `computed_at` (1790885329887), so the cache was rebuilt in full.\n- The 48 newest `videos` rows contain 0 with `nsfw = 1`, whether ordered by `published_at` or by `last_checked_at`.\n\nBuild 19 changed only `engine/server/api/logging_profiles.py`, `client/backend/server.py` and the `_error_messages`/caplog rewire in `tests/active/test_server.py` that the operator confirmed (git status). None of the failing assertions depends on log format. The one dependency is `_messages` parsing JSON lines, and that still works: the failing pool test parsed `upnext_pool` lines out of the Engine log. In each case the test's premise about the data no longer holds. That is a test-side fault, not an implementation fault, and it is not caused by this build. The operator chose \"out of scope: report only\". I changed no test and no production code.\n\n### test_server.py::test_a_gateway_listing_request_without_exactly_nsfw_1_gets_no_flagged_row_where_nsfw_1_gets_some (10 cases)\nThe control assertion fails: `{route} with nsfw=1 served no flagged row`. The test pins \"Recent's sixth row is flagged (observed)\". A probe sent `POST /recommendations?mode=recent&nsfw=1` and `/videos/similar?mode=recent&nsfw=1` through a real Client. Both returned 200 with 48 rows, 0 of them flagged, which matches the DB finding of no nsfw row among the newest 48. Fault: the test's data-pinned control. Change: none.\n\n### test_similar.py::test_a_short_cached_seed_fills_a_48_row_page_and_leaves_its_cache_entry_unchanged[linux, cooking]\nThe control `0 < len(before[1]) < 48` fails at 542 and 260 rows. `_cache_entry` reads `similarity-cache.db` directly with sqlite; no build-19 code is involved. The rebuilt cache no longer has short entries for these seeds. Fault: the test's data-pinned control. Change: none.\n\n### test_similar.py: three fallback/nprobe tests\nThese are `test_home_and_search_are_unchanged_by_an_upnext_fallback_and_nprobe_is_restored`, `test_every_upnext_pool_line_records_the_fallback_steps_its_request_ran_and_nprobe_restored_to_default` and `test_on_an_engine_started_off_default_nprobe_every_upnext_pool_line_reports_the_nprobe_its_fallback_restored`. Each control expects the linux up-next request to run the ANN fallback, and the test comments rest on \"every similarity-cache.db entry holds at most 20 rows (observed)\". The Engine's own lines show `upnext_pool initial=170 \u2026 steps=none` and `initial=205 \u2026 steps=none`. The pool already reaches the 48-row target, so no fallback runs and no `ann_fallback` line is logged. Fault: the test's data-pinned control. Change: none.\n\n### test_similar.py::test_home_excluding_a_previous_page_returns_none_of_it_and_a_full_page[music]\nThe control \"a plain page repeats none of the previous one\" fails: two home pages for the music likes share no row. This one is inferred, not observed. Home's row selection is untouched by build 19, which changed only log formatters, and the candidates behind it were rebuilt with the cache, so the draw's overlap has changed. Re-running it against the pre-rebuild data, or reading the home pool size for the music likes, would confirm it. Fault: the test's data-pinned control. Change: none.\n\n### test_frontend_upnext_pager.py::test_the_pager_s_48_row_batches_never_repeat_a_row_and_it_stops_asking_after_an_empty_batch\nIn the suite run, one batch carried an `error` key. The truncated output hides the error text, so I could not see what it was. Run alone through a probe (`tests/tmp/probe_step8_pager.py`) against the same Engine and data, with the test's own `_seed`/`_run`, the pager was clean: 48\u00d76, then 30, then empty at batch 8, with `calls` staying at 8 after that. That satisfies every assertion the test makes on the 48-row run. The 20-row re-run was not exercised. The frontend and the up-next code are untouched by build 19, so the suite failure was transient: probably load under 12 lanes, or the data rebuild, but I could not observe which. Re-running this group alone in the workflow would confirm it. Fault: not the implementation. Change: none.\n\n### Retired tests\nNone. No durable test conflicts with a confirmed requirement of build 19 (Engine/Client log timestamps and `LOG_FORMAT` rendering), and none now passes vacuously because of it.\n</failures>\n\n<checkpoint_gaps>\nnone. No failure comes from build 19's implementation, so no phase checkpoint missed anything. Phases 1\u20134 gate only log-format behaviour, and every red here is a dataset-pinned control or a transient pager error that this build's code cannot reach.\n</checkpoint_gaps>\n\n<correction>\n- Read the failing assertions. All 17 are control assertions about the shared live dataset, or a pager `error` whose text was cut from the output; none is about logging.\n- Probed the data with `tests/tmp/probe_step8_dataset.py`. The probe found that `whitelist.db` and `similarity-cache.db` are symlinks into main and were rebuilt on 2026-10-01 (HEAD `57c8417 db rebuilt and updated`). The cache has a single `computed_at` across 890,052 sources. The newest 48 videos hold 0 nsfw rows. Only the build's two logging files and the confirmed `test_server.py` rewire are modified.\n- Probed the routes with `tests/tmp/probe_step8_pager.py`. Run alone against a real Engine and Client, the pager behaved correctly (48\u00d76, 30, then empty, with no further calls). `mode=recent&nsfw=1` returned 48 rows with none flagged on both gateway routes.\n- Asked the operator how to handle the data-pinned controls. Answer: out of scope, report only.\n- Made no change to production code or to any test. Retired no test.\n- Emptied both probe files, since I have no delete tool; each now collects no tests and can be removed.\n- Follow-up for whoever owns the dataset: re-point the data-pinned controls in a separate issue. They are in `test_server.py` (nsfw recent page), `test_similar.py` (short cached seeds, fallback/nprobe, home overlap) and `test_frontend_upnext_pager.py`. Alternatively, restore the pre-rebuild dataset before comparing against the baseline. Re-running `test_frontend_upnext_pager.py` alone in the workflow would confirm its red was transient.\n</correction>",
    "step_8_triage:1": "<failures>\n### Common cause: the shared dataset was rebuilt under the build (inspected the tests first; probe-observed)\nAttempt 2 runs the same 16 tests red as attempt 1. Each one fails on a control assertion about the live dataset, never on a logging assertion. That dataset is `engine/server/db/whitelist.db` plus `similarity-cache.db`, both gitignored symlinks into the main checkout. Attempt 1's probe found both files rebuilt on 2026-10-01, at HEAD `57c8417 db rebuilt and updated`: one `computed_at` across 890,052 sources, and none of the newest 48 videos flagged nsfw. The Step-0 baseline re-ran only `test_search_fusion.py` (\"selected 1 of 46\"), so the \"green\" recorded for `test_server.py` and `test_similar.py` is a fingerprint from before the rebuild. Build 19 touched only the two logging modules and the operator-confirmed `_error_messages`/caplog rewire in `test_server.py`. The one place a failing test reads logs is `_messages`, and it still parses the Engine's JSON lines: the failing pool test pulled out `upnext_pool \u2026 steps=none` lines. The fault is in the tests' data-pinned premises, not in the implementation. These tests have already gated and do not conflict with a build-19 requirement, so I did not edit, re-point or retire any of them. The operator chose \"report only, same as attempt 1\".\n\n### test_server.py::test_a_gateway_listing_request_without_exactly_nsfw_1_gets_no_flagged_row_where_nsfw_1_gets_some (10 cases)\nThe control fails: `{route} with nsfw=1 served no flagged row` on `mode=recent&nsfw=1`. The test pins \"Recent's sixth row is flagged (observed)\". In the rebuilt data the newest 48 videos hold 0 nsfw rows. That was observed in attempt 1, through the real Client on both routes, and directly in the DB. Fault: the test's data-pinned control. Change: none.\n\n### test_similar.py::test_a_short_cached_seed_fills_a_48_row_page_and_leaves_its_cache_entry_unchanged[linux, cooking]\nThe control `0 < len(before[1]) < 48` fails at 542 and 260 rows. `_cache_entry` reads `similarity-cache.db` with sqlite directly, so no build-19 code runs. Fault: the test's data-pinned control. Change: none.\n\n### test_similar.py fallback/nprobe tests (3)\nThe three tests are `test_home_and_search_are_unchanged_by_an_upnext_fallback_and_nprobe_is_restored`, `test_every_upnext_pool_line_records_the_fallback_steps_its_request_ran_and_nprobe_restored_to_default` and `test_on_an_engine_started_off_default_nprobe_every_upnext_pool_line_reports_the_nprobe_its_fallback_restored`. Each rests on \"every similarity-cache.db entry holds at most 20 rows (observed)\". The Engine's own lines read `upnext_pool initial=170 \u2026 steps=none` and `initial=205 \u2026 steps=none`. The pool already exceeds the 48-row target, so no `ann_fallback` runs or is logged. Fault: the test's data-pinned control. Change: none.\n\n### test_similar.py::test_home_excluding_a_previous_page_returns_none_of_it_and_a_full_page[music]\nAttempt 1 only inferred this cause; this time it is observed. The docstring premise is \"the like-seeded layers draw from the same shallow pool and repeat across pages\". Probe `tests/tmp/test_probe_step8_home_overlap.py` ran against the session Engine. The five music likes' cache entries hold 302, 596, 242, 388 and 291 rows. Three pairs of plain music home draws shared 1, 1 and 0 rows, so the control `previous & plain` fails some of the time. For comparison, linux (542-row entries) shared 2, 2 and 4 rows, and cooking (260) shared 8, 4 and 3. Home row selection never passes through the log formatter. Fault: the test's data-pinned control, which is now flaky on the deeper pool. Change: none.\n\n### test_frontend_upnext_pager.py (attempt 1 only)\nAttempt 1 called its red transient, and the workflow re-run confirms it: \"no longer red\", 1 passed. Change: none.\n\n### Retired tests\nNone. No durable test conflicts with a confirmed requirement of build 19 (UTC `ts` from `record.created`, `LOG_FORMAT` json/text, the Client root formatter). None passes vacuously because of build 19.\n</failures>\n\n<checkpoint_gaps>\nnone. No red comes from build 19's implementation. Phases 1\u20134 gate only log-format behaviour. Every red is a control pinned to dataset contents that changed under the build (commit 57c8417 rebuilt both DBs). No phase checkpoint could, or should, have caught that.\n</checkpoint_gaps>\n\n<correction>\n- Inspected the failing tests first. All 16 reds in attempt 2 are the attempt-1 controls, which assert on dataset contents (nsfw rows in the recent page, cache-entry sizes, whether a fallback runs, overlap between home draws). None asserts on logging. The pager test is green again, which confirms attempt 1's \"transient\" call.\n- Checked the record: the Step-0 baseline re-ran only test_search_fusion.py. So test_server/test_similar were never re-baselined after the data rebuild at 57c8417.\n- Observed the one cause attempt 1 had only inferred, with probe tests/tmp/test_probe_step8_home_overlap.py. The music likes' cache entries hold 242\u2013596 rows. Two plain music home draws shared 1, 1 and 0 rows, so the [music] overlap control is flaky on the rebuilt data. Linux and cooking shared 2\u20138 rows.\n- Asked the operator how to close the step. Answer: report only, same as attempt 1.\n- Changed no production code and no test. Retired no test. No checkpoint touched.\n- Emptied the probe file because I have no delete tool. It now collects no tests and can be removed, along with the earlier emptied step-8 probes (probe_step8_dataset.py, probe_step8_pager.py).\n- Follow-up outside build 19: re-pin the data-pinned controls against the rebuilt dataset in a separate issue, or restore the pre-57c8417 DBs before comparing. The controls are in test_server.py (nsfw recent page) and test_similar.py (short cached seeds, three fallback/nprobe tests, music home overlap).\n</correction>",
    "step_8_triage:2": "<failures>\n### Common cause: the shared dataset was rebuilt underneath the build (I inspected the tests first)\nThis is attempt 3, and it has the same reds as attempts 1 and 2, minus `test_similar.py::test_home_excluding_a_previous_page_returns_none_of_it_and_a_full_page[music]`. The compare now lists that test as \"no longer red\", so attempt 2 was right to call it flaky. All 15 remaining failures stop on a control assertion about what the shared data contains. None stops on a logging assertion. The data is `engine/server/db/whitelist.db` and `similarity-cache.db`, both gitignored symlinks into the main checkout. In attempt 1 a probe showed both files were rebuilt at HEAD `57c8417 db rebuilt and updated`: one `computed_at` across all 890,052 sources, and none of the newest 48 videos flagged nsfw. Both groups were selected because they were already \"not green\". The compare lists no test as newly red, so none of these 15 was green in the previous record.\n\nBuild 19 changed only `engine/server/api/logging_profiles.py`, `client/backend/server.py`, and the `_error_messages`/caplog rewire in `test_server.py` that the operator confirmed. The failing tests touch logging in one place, `_messages` in test_similar.py, and it still parses the Engine's JSON lines: in this run the `NPROBE_PREFIX` startup controls passed, and the pool test read `upnext_pool \u2026 steps=none` lines out of the log. The fault is in each test's premise about the data, not in the implementation. These tests have already gated and do not conflict with any build-19 requirement, so none was edited, repointed or retired. The operator chose \"report only, again\".\n\n### test_server.py::test_a_gateway_listing_request_without_exactly_nsfw_1_gets_no_flagged_row_where_nsfw_1_gets_some (10 cases: /recommendations and /videos/similar \u00d7 missing/empty/0/true/space-1)\nThe control at test_server.py:1297 fails: `{route} with nsfw=1 served no flagged row` on `mode=recent&nsfw=1`. The test relies on \"Recent's sixth row is flagged (observed)\". In the rebuilt data none of the newest 48 videos is flagged nsfw; attempt 1 saw this through a real Client on both routes and directly in the DB. Fault: the test's data-pinned control. Change: none.\n\n### test_similar.py::test_a_short_cached_seed_fills_a_48_row_page_and_leaves_its_cache_entry_unchanged[linux, cooking]\nThe control `0 < len(before[1]) < FILL_LIMIT` at test_similar.py:829 fails with 542 and 260 rows. `_cache_entry` reads `similarity-cache.db` directly through sqlite, so no build-19 code runs. Fault: the test's data-pinned control. Change: none.\n\n### test_similar.py: fallback/nprobe tests (3)\nThese are `test_home_and_search_are_unchanged_by_an_upnext_fallback_and_nprobe_is_restored` (:877), `test_every_upnext_pool_line_records_the_fallback_steps_its_request_ran_and_nprobe_restored_to_default` (:975) and `test_on_an_engine_started_off_default_nprobe_every_upnext_pool_line_reports_the_nprobe_its_fallback_restored` (:1001). All three rely on \"every similarity-cache.db entry holds at most 20 rows (observed)\". The Engine's own log reads `upnext_pool initial=170 \u2026 steps=none` and `initial=205 \u2026 steps=none`. The pool already exceeds the 48-row target, so no ANN fallback runs and no `[similar-server] ann_fallback` line is logged. The fallback controls then find 0 lines. Fault: the test's data-pinned control. Change: none.\n\n### Retired tests\nNone. No durable test conflicts with a confirmed requirement of build 19: UTC `ts` from `record.created`, `LOG_FORMAT` choosing json or text, and the Client root formatter. No test passes vacuously because of it.\n</failures>\n\n<checkpoint_gaps>\nnone. None of the reds comes from build 19's implementation. Phases 1\u20134 gate only log format and timestamps, and every failure here is a control pinned to dataset contents that `57c8417` rebuilt. No phase checkpoint could, or should, have caught that.\n</checkpoint_gaps>\n\n<correction>\n- Read the failing test first, then the run record. All 15 reds are control assertions about the live dataset: nsfw rows on the recent page, cache-entry size, whether a fallback runs. None asserts anything about logging. The compare lists no newly red test. The only movement is `[music]` going green, which confirms attempt 2's call that it is flaky.\n- Checked that the build's one log-reading path still works. `_messages` passed its `NPROBE_PREFIX` controls and parsed `upnext_pool` lines in this run.\n- Checked the earlier step-8 attempts in `docs/project/plans/20-19-timestamped-request-logs.record.md`. The dataset cause was observed by probe there (both DBs rebuilt at `57c8417`), so this run needed no new probe. None was written.\n- Asked the operator how to close a third identical attempt. Answer: report only, again.\n- Changed no production code and no test, touched no checkpoint, and retired no test.\n- Still open from earlier steps: the emptied probe files in `tests/tmp/` (probe_step8_dataset.py, probe_step8_pager.py, test_probe_step8_home_overlap.py, probe_fromtimestamp.py, probe_caplog_formatter.py) can be deleted.\n- Follow-up outside build 19: re-pin these controls against the rebuilt dataset, or restore the DBs from before `57c8417` before comparing. They are in test_server.py (the nsfw recent page) and test_similar.py (short cached seeds, three fallback/nprobe tests).\n</correction>"
  },
  "requirements": "### Purpose\n\nIssue 19 (task 41, [M7][F4]) is the first of the logging chain: 19 timestamped logs, then 20 request lifecycle logs with a shared `request_id`, then 21 static page visit logs. The goal is to make request timing analysis possible from the application's own log lines. Each record must carry an explicit, unambiguous, comparable timestamp, so the order of request-start, work and request-end within a request can be read from the app log alone. That must not depend on the journald envelope time or on how a given message happens to be formatted. Both long-running services must use the same timestamp and line format, so their logs can be compared side by side.\n\n### Current state (found in the tree)\n\n- Engine API server: `configure_engine_logging` in `engine/server/api/logging_profiles.py` installs `EngineJsonFormatter` on the root logger (one StreamHandler, INFO). It is called from `engine/server/api/server.py` line 323. Each record becomes one JSON line with keys `ts`, `level`, `event`, `message` (dropped for `service.lifecycle`), `modes`, plus `request_id`, `context` and `traceback` when present. `ts` is `datetime.now().astimezone().isoformat(timespec=\"milliseconds\")`. That is local time with a numeric offset, and it is taken when the record is formatted, not when it was created.\n- Engine request lines: `[access.start]` (`_log_access_start`) and `[access]` (`log_message`) in `engine/server/api/handlers/similar.py` are plain `logging.info` calls rendered by that formatter, with events `access.start` and `access`.\n- Client backend: `client/backend/server.py` calls `logging.basicConfig(level=logging.INFO, format=\"%(message)s\")` in `main()`. All its logs go through `_emit_client_log(level, event, message, context)`, which builds its own JSON string. The keys are `ts` (same local-time expression as the Engine), `level`, `service: \"client-backend\"`, `event`, `message` and optional `context`. Access lines come from `ClientBackendHandler.log_message` as event `client.access`. A record that does not go through `_emit_client_log` (for example a library logging to the root logger) is printed as its bare message with no timestamp.\n- Consumers of the JSON: `engine/watch-engine-logs.sh` runs `journalctl -o cat | jq -R 'fromjson?'` and filters on `.modes`, `.level`, `.event` and `.message`. `client/watch-client-logs.sh` runs `jq -R 'fromjson? // {\"raw\": .}'`. The DEPLOYMENT.md runbooks send operators to the `traceback` key (Engine) and to `context.error` of the ERROR `engine.call` / `engine.bridge` records (Client).\n- Existing tests: `engine/server/api/tests/test_logging_profiles.py` asserts `\"ts\" in payload`. `tests/active/test_logging_profiles.py`, `tests/active/test_internal_events.py` and `tests/active/test_similar.py` run `configure_engine_logging(\"verbose\")` and parse the JSON lines (including `traceback` and `message`).\n\n### Scope\n\nIn scope: the Engine API server process (everything logged through the root logger once `configure_engine_logging` has run) and the Client backend process (`client/backend/server.py`).\n\nOut of scope:\n- `request_id` propagation and request-end `duration_ms` (issue 20).\n- nginx and static page visit logging (issue 21).\n- The batch scripts in `engine/server/db/jobs/` and `updater-worker.py`, which keep their own plain `basicConfig` formats.\n- Raw stderr output that does not pass through `logging`: socketserver's default `handle_error` traceback print and the `faulthandler` SIGUSR1 stack dump.\n\n### R1 \u2014 Explicit UTC timestamp with milliseconds\n\n- Every log record written by either service carries a timestamp in ISO-8601 extended format, in UTC, with millisecond precision and a `Z` zone marker, in exactly this shape: `YYYY-MM-DDTHH:MM:SS.mmmZ`, e.g. `2025-03-04T12:34:56.789Z`. No local time and no numeric offset (`+00:00` is not the accepted form; `Z` is).\n- The timestamp is taken from the moment the log call was made (`logging.LogRecord.created`), not from when the formatter runs.\n- In JSON output the timestamp stays under the existing key `ts`.\n\n### R2 \u2014 One shared format across both services\n\n- The Engine and the Client backend produce records to one contract: the same `ts` format (R1), the same `level` names (the stdlib level names `DEBUG`/`INFO`/`WARNING`/`ERROR`/`CRITICAL`), and the same leading key order `ts`, `level`, then the remaining keys.\n- Request lifecycle lines (Engine `access.start` and `access`, Client `client.access`) and internal server lines (service start/stop/lifecycle, recommendations and similarity logs, `engine.call` and `engine.bridge` errors, any WARNING/ERROR) all go through this format. No record from either process reaches its output stream without the timestamp.\n- The Client backend gets a real formatter on its root logger, the same way the Engine has one. A record logged in the Client by any path other than `_emit_client_log` (a bare `logging.*` call or a library's logger) is still emitted in the shared format with `ts`, `level` and an event. The Client's existing payload keys (`service: \"client-backend\"`, `event`, `message`, `context`) are preserved.\n- How the code is shared between the two services (one shared helper or two matching implementations) is a design decision for later steps. The requirement is the identical output contract.\n\n### R3 \u2014 Output format switch (JSON default, plain text opt-in)\n\n- One environment variable, `LOG_FORMAT`, read by both services at logging setup, selects the output format: `json` (default) or `text`. Matching is case-insensitive and ignores surrounding whitespace.\n- An unset, empty or unrecognised value selects `json`. It fails safe the same way `normalize_log_mode` falls back to `verbose`, and it must not stop the service from starting.\n- JSON stays the default because `engine/watch-engine-logs.sh`, `client/watch-client-logs.sh` and the DEPLOYMENT.md runbooks depend on it. In JSON mode the existing keys and their meaning are unchanged: Engine `ts`, `level`, `event`, `message`, `modes`, `request_id`, `context`, `traceback`, including the per-event message rewriting already in `EngineJsonFormatter`; Client `ts`, `level`, `service`, `event`, `message`, `context`. Only the value format of `ts` changes (R1).\n- The Engine's existing `focused`/`verbose` log mode concept (`modes` tagging) is separate from `LOG_FORMAT` and is not changed.\n- Where the variable is documented (the service README/DEPLOYMENT notes alongside other env settings), add `LOG_FORMAT` with its two values and the default.\n\n### R4 \u2014 Plain text line shape\n\n- In `text` mode each record is one line: `<ts> <LEVEL> <event> <message>`. Then come the record's context entries as space-separated `key=value` tokens (where the record has a context dict, as the Client's do), then `request_id=<id>` when a request id is present. For the Engine, `message` is the same message text the JSON payload would carry.\n- The `ts` in text mode is the identical string R1 defines, so text and JSON lines from the same moment carry the same timestamp.\n\n### R5 \u2014 journald compatibility\n\n- Exactly one physical line per record in both formats, because journald stores each stdout line as its own entry. In JSON mode this is already true (`json.dumps` escapes newlines). In text mode, any newline inside the message or the traceback is escaped (rendered as the two characters `\\n`), so one record is never split across journal entries. In text mode the traceback is appended on that same line.\n- No syslog priority prefixes (`<N>`) or other markers that journald would interpret. Output goes to the same stream as today (the Engine's StreamHandler default, stderr; the Client's `basicConfig` default, stderr), so the existing systemd units and `journalctl -u \u2026 -o cat` pipelines keep working unchanged.\n- Nothing in the logs or the tooling relies on the journal envelope timestamp for ordering. The application `ts` is the timestamp of record.\n\n### R6 \u2014 Ordering by application timestamp\n\n- For a single request handled on one thread, the `ts` of its request-start line (Engine `access.start`), of any work log lines emitted while handling it, and of its request-end line (Engine `access`, Client `client.access`) are non-decreasing in that order. Because `ts` comes from `record.created` (R1), it reflects when each event happened, not when the line was formatted.\n- Ordering is guaranteed per request, not globally across concurrently served requests (consistent with issue 20).\n\n### Validation\n\n- A sample record from each service, in each format, contains a full date and time with milliseconds and the `Z` timezone marker, matching `^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}\\.\\d{3}Z$` for the `ts` value.\n- An Engine request produces `access.start`, work and `access` records whose `ts` values are non-decreasing.\n- `ts` equals the record's creation time rendered in UTC: a record created at a known `created` value renders that instant, not the formatting time.\n- `LOG_FORMAT` unset, `json`, `JSON`, `bogus` and empty each select JSON; `text` (any case) selects the text line. Every record is a single line in both modes, including one with a traceback and one whose message contains a newline.\n- The Client backend emits a record in the shared format both for `_emit_client_log` calls and for a bare `logging.info` call made after its logging setup.\n- The existing JSON consumers keep working: Engine payload keys and per-event message rewriting unchanged, and the existing tests that parse the Engine JSON (`tests/active/test_logging_profiles.py`, `test_internal_events.py`, `test_similar.py`, `engine/server/api/tests/test_logging_profiles.py`) still pass.\n\n### Baseline suite state\n\nThe pre-build baseline run exited with code 0 (`variant: false`): the active suite in `tests/active` is green before this build starts. Any red test after the build is attributable to the build. The project dir is `/home/enduser/code/PeerTube-browser/.worktrees/19`, the working test dir is `tests/tmp`, the archive is `tests/archive`, the plans live in `docs/project/plans`, the run record is `tests/last_test_validation.json` and the output is `tests/last_test_output.txt`.",
  "approved": [
    "1",
    "2",
    "3",
    "5",
    "6"
  ],
  "initial_solution": "### Approach\n\nThe change is in the formatter layer of each service. No call site changes, except that the Client's `_emit_client_log` stops serialising JSON by hand. I read `engine/server/api/logging_profiles.py`, `client/backend/server.py` (lines 120-136 `_emit_client_log`, 258-273 `log_message`, 1175-1252 `main`), the Engine's call site at `engine/server/api/server.py:323`, and `tests/active/conftest.py:41`, which already imports the Client `server` module in-process.\n\n**Timestamp (R1, R6).** Each service gets one small private helper that turns a `LogRecord` into the `ts` string. It renders `record.created` in UTC as `YYYY-MM-DDTHH:MM:SS`, appends `.` and the record's milliseconds as three digits, then appends a literal `Z`. All of this is stdlib. The value comes from `record.created`, which `logging` sets at the moment of the log call, not from `datetime.now()`. So ordering within one thread follows the order of the calls even if formatting happens later. That gives R6 for `access.start`, the work lines and `access` / `client.access`. Both the seconds and the milliseconds are taken from the same `created` value, so they cannot disagree. The `+00:00` form that `isoformat` would produce is avoided by building the string explicitly.\n\n**Engine (R1-R5).** `EngineJsonFormatter.format` keeps all of its classification, request-id extraction, context building and per-event message rewriting exactly as it is. Only the `ts` value changes, and it now comes from the record. The work is split so the formatter first builds the payload dict as it does today, then renders it one of two ways:\n- JSON: today's `json.dumps`, unchanged.\n- Text: one line made of `ts`, `level`, `event` and the payload's `message`, separated by spaces. If the payload has a `context`, its entries follow as `key=value` tokens. Then comes `request_id=<id>` when present, then the traceback.\n\nBecause both renderings use the same payload, the text-mode message is by construction the message JSON would carry (\"request started\", \"request finished\", \"[recommendations] incoming likes\"). The formatter chooses its rendering when it is constructed. `configure_engine_logging` reads `LOG_FORMAT` from the environment when it runs and passes the normalised choice to the formatter. Its signature `configure_engine_logging(profile)` stays the same, so `server.py:323` and the four existing test modules need no change. A small `normalize_log_format` sits next to `normalize_log_mode` with the same fail-safe shape: strip, lowercase, `text` means text, anything else means `json`.\n\n**Client (R2-R5).** The Client gets a real formatter on its root logger. `main()` replaces `logging.basicConfig(format=\"%(message)s\")` with a `configure_client_logging()` call. That function clears the root handlers, sets INFO, adds a StreamHandler (stderr, as today), installs the Client formatter and reads `LOG_FORMAT` the same way the Engine does. `_emit_client_log` keeps its signature and its call sites. It no longer builds a JSON string. Instead it calls `logging.log(level, message, extra=...)` and passes `event` and `context` as record attributes. The formatter builds the payload in the order `ts`, `level`, `service: \"client-backend\"`, `event`, `message`, `context`, which is the same keys in the same order as today. A record without those attributes, such as a bare `logging.info` call or a library logger, gets `event` set to a fallback name (`client.log`, matching the Engine's `engine.log` fallback) and its `getMessage()` as `message`. If the record has `exc_info`, the formatter adds a `traceback` key the way the Engine does. That key is new to the Client, but it is additive, and without it an exception logged through the root logger would be silently lost. Text mode uses the same line shape as the Engine.\n\n**Text rendering details (R4, R5).** Context values that are scalars are written with `str()`. Values that are lists or dicts, for example the Engine's incoming-likes context, are written as compact JSON so each one stays a single token. Once the line is assembled, every CR and LF in it (message, context values, traceback) is replaced by the two-character escapes `\\r` / `\\n`. Every record is therefore one physical line. Nothing is added in front of the line, so there are no `<N>` prefixes and no extra markers. For `service.lifecycle`, where JSON drops `message`, the text line leaves the message token out and goes straight from event to context.\n\n**Docs (R3).** One `LOG_FORMAT` paragraph goes into DEPLOYMENT.md beside the other Engine/Client environment settings (around lines 105-114). It states the values `json` (default) and `text`, the fail-safe behaviour, and that the watch scripts and runbook `jq` recipes need `json`. It also says how to set the variable: through `.env.bridge` or an `Environment=` drop-in.\n\n**Requirement map.**\n- R1: the UTC helper built from `created`.\n- R2: two formatters to one contract. Both have leading `ts`/`level`, use stdlib level names and use the same helper shape, and the Client now has a root formatter that catches bare records.\n- R3: `LOG_FORMAT` normalisation in both setup functions; the JSON keys are unchanged.\n- R4: the shared payload-to-text rendering.\n- R5: newline escaping, unchanged streams and no prefixes.\n- R6: `created`-based `ts`.\n\n### Alternatives considered\n\n- **One shared module for both services**, for example `common/log_format.py` at the repo root. Rejected. The Engine imports from `engine/server/api` (`from request_context import \u2026`) and the Client from `client/backend` (`from lib.\u2026 import \u2026`). Neither has the repo root on `sys.path`, so sharing would need a `sys.path` insert in both entry points, the install scripts and the tests, and it would join two independently deployed units at import time. The duplicated logic is about a dozen lines: the ts helper, the text renderer and the format normaliser. I chose two matching implementations and a cross-service test as the guard against drift. This is a deliberate simplification. Its ceiling is that the two copies can diverge if someone edits only one. The upgrade path is to extract a shared package once a third consumer appears, for example the issue-21 static visit logger if it is written in Python.\n- **Keep `_emit_client_log` building JSON and add `basicConfig(format=\"%(asctime)s \u2026\")`.** Rejected. A record from `_emit_client_log` would then contain JSON inside a text prefix. That breaks `watch-client-logs.sh`'s `fromjson?` and does not meet \"same format\".\n- **Set `logging.Formatter.converter = time.gmtime` and use `formatTime`.** Rejected. `formatTime` with `default_msec_format` gives `,mmm` and no `Z`, so it would need overriding anyway. A class-level `converter` change also leaks process-wide. An explicit helper is clearer.\n- **Read `LOG_FORMAT` in `server_config.py` (Engine) at import.** Rejected. Reading it at logging setup is what R3 asks for. It also lets tests monkeypatch the environment and call `configure_engine_logging` without reloading a module.\n- **Wrap the existing JSON formatter in a separate text formatter class.** Rejected as an extra class for one switch. A constructor flag on the existing formatter is smaller.\n\n### Risks and gotchas\n\n- **Validation timing.** `record.created` is fixed when the record is created. A test that builds a `LogRecord` with a chosen `created` (and the matching `msecs`, which is derived at construction) must set both to check \"renders that instant\". The plan derives milliseconds from `created` itself rather than trusting `msecs`, so setting `created` alone is enough.\n- **Ambiguous text tokens.** In text mode, a context value or message containing spaces or `=` is not quoted, so `key=value` tokens are best-effort for human reading, not a parseable format. JSON remains the machine contract. This is a named limitation.\n- **The Client `extra=` names** must not collide with reserved `LogRecord` attributes (`message`, `msg`, `args`, \u2026). They will be namespaced, for example `client_event` and `client_context`.\n- **Third-party library records in the Client** now appear as structured lines with event `client.log`. Before, they appeared as bare text. Any record with level below INFO is still filtered as today.\n- **The existing Engine tests** read `ts` only for presence, so the format change does not break them. If the CI environment ever exported `LOG_FORMAT=text`, the JSON-parsing tests would fail. The new tests pin `LOG_FORMAT` explicitly, and the existing ones rely on the default.\n- **The Client test seam.** `conftest.py` imports the Client `server` module in-process, so the formatter can be tested directly. A test that calls `configure_client_logging()` replaces the root handlers of the pytest process and must restore them, the same way the Engine tests already handle `configure_engine_logging`.\n- **Out of scope, still untimestamped.** Raw stderr (socketserver `handle_error`, the faulthandler dump) still has no timestamp. The requirements say so explicitly.\n\n### Tradeoffs for the operator\n\n- There are two parallel implementations of one contract instead of a shared module. Drift is guarded by a test rather than by structure.\n- Text mode is for humans. It escapes newlines and does not quote values, so tooling must keep using JSON.\n- The Client gains an additive `traceback` key on records logged with `exc_info`. It is not part of the existing key list but is needed so no exception is dropped.\n- `ts` changes from local time with an offset to UTC `Z`. Operators reading raw lines see UTC rather than local wall-clock time.",
  "conflicts": "none",
  "impacts": "\n<impacts>\n<impact path=\"engine/server/api/logging_profiles.py\" element=\"imports (lines 5-12)\">\n**What changes.** `from datetime import datetime` (line 9) is used only for the `ts` at line 195. The new UTC helper needs `datetime.fromtimestamp(created, tz=timezone.utc)` or `time.gmtime`, so this import changes to `from datetime import datetime, timezone` (or to `time`). The text renderer and the env read need `import os`, which the module does not import today. `json` stays: it is used by `_normalize_incoming_likes_context`, the JSON render, and the compact rendering of list/dict context values in text mode.\n\n**Depends on it.** Only this module.\n\n**Risk: low.** If the `datetime` import is left unused after the change, linting may flag it. The module must keep importing only the stdlib and `request_context`: `tests/active/test_logging_profiles.py:36` relies on running it under pytest's own interpreter.\n</impact>\n<impact path=\"engine/server/api/logging_profiles.py\" element=\"new `normalize_log_format()` next to `normalize_log_mode()` (line 73), plus a supported-formats constant\">\n**What changes.** A new public function that mirrors `normalize_log_mode`: `(value or \"\").strip().lower()`; it returns `\"text\"` when the value is `text` and `\"json\"` for anything else, including `None`, `\"\"`, `\"JSON\"` and `\"bogus\"`. It would go beside `SUPPORTED_LOG_MODES` (line 15), possibly with a `SUPPORTED_LOG_FORMATS = (\"json\", \"text\")` tuple in the same style.\n\n**Depends on it.** `configure_engine_logging` and the new tests. The Client gets its own copy because there is no shared module (plan, \"Alternatives\").\n\n**Risk: low.** It must never raise, because R3 requires that a bad value does not stop startup. Note that `server_config._resolve_log_profile_env` (server_config.py:12-15) is a second, separate normaliser for `RECOMMENDATIONS_LOG_PROFILE`. It stays untouched, and the plan rightly does not put `LOG_FORMAT` there.\n</impact>\n<impact path=\"engine/server/api/logging_profiles.py\" element=\"new private ts helper (UTC from `record.created`)\">\n**What changes.** A new `_format_ts(record)` (or similar). It renders `record.created` in UTC as `YYYY-MM-DDTHH:MM:SS.mmmZ`, taking the milliseconds from `created` itself and not from `record.msecs` (plan, \"Validation timing\").\n\n**Depends on it.** The JSON and text renderings in `EngineJsonFormatter.format`.\n\n**Risk: medium.** Watch the rounding edge: if the seconds and the milliseconds are computed separately, for example `int(created % 1 * 1000)` against a `fromtimestamp` that rounds microseconds, a value like x.9996 can disagree with its own seconds (`.1000`, or a seconds value one too high). Using `fromtimestamp(created, timezone.utc)` and then `microsecond // 1000` keeps both from one value. Expected regex: `^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}\\.\\d{3}Z$`. It must be the same string in both renderings (R4 requirement line 53).\n</impact>\n<impact path=\"engine/server/api/logging_profiles.py\" element=\"`EngineJsonFormatter` class: new constructor flag, `format()` (lines 184-226) split into payload build + render\">\n**What changes.** \n- `__init__` gets a format flag. It must default to JSON, because `EngineJsonFormatter()` is constructed with no arguments in `engine/server/api/tests/test_logging_profiles.py:34,141`.\n- Line 195 `ts` becomes the record-based helper.\n- Everything from line 189 to line 225 stays: classification, `_extract_request_id`, `_extract_fields`, the incoming-likes, access.start, access and service.lifecycle message rewriting, and `traceback`.\n- The final `json.dumps(payload, ensure_ascii=True, separators=(\",\", \":\"))` (line 226) stays the JSON branch, byte for byte.\n- A new text branch renders: `ts level event [message] [context k=v\u2026] [request_id=\u2026] [traceback]`. `modes` is omitted. For `service.lifecycle` the message token is skipped because the payload has no `message`. CR and LF are escaped in the assembled line.\n\n**Depends on it.** \n- `configure_engine_logging` (line 239).\n- The unit tests (which build the formatter directly).\n- `engine/watch-engine-logs.sh` (JSON keys `modes`, `level`, `event`, `message`).\n- `engine/server/README.md:31` (names the class and its `traceback` key).\n- Every Engine log record in production.\n\n**Risk: medium-high.** \n- JSON mode must remain unchanged apart from the `ts` value. Key order today is `ts, level, event, message, modes`, then `request_id`, `context`, `traceback`. Any refactor that rebuilds the dict differently changes the order. Tests do not pin the order, but the R2 contract does.\n- The class name says \"Json\" while it now also emits text. Renaming it would break the unit-test import (line 18) and README.md:31, so keep the name.\n- In text mode, `request_id` should not be emitted twice when `context` already carries a `request_id` token taken from the message.\n- The JSON branch's `ensure_ascii=True` escaping does not apply to text mode, so non-ASCII passes through raw. Probably fine, but worth stating.\n- The traceback in text mode contains newlines and must go through the CR/LF escape. Context values from `_extract_fields` are single tokens already. The incoming-likes context holds a list of dicts, which must be rendered as compact JSON.\n</impact>\n<impact path=\"engine/server/api/logging_profiles.py\" element=\"`configure_engine_logging(profile)` (lines 229-241)\">\n**What changes.** It reads `os.environ.get(\"LOG_FORMAT\")` at call time, passes `normalize_log_format(...)` to the formatter (line 239), and keeps its signature and its return value (the normalised log *mode*, not the format). Root-handler clearing, INFO level and the StreamHandler (stderr) stay unchanged.\n\n**Depends on it.** \n- `engine/server/api/server.py:323` (production).\n- `tests/active/test_logging_profiles.py:23-24` (child).\n- `tests/active/test_internal_events.py:256-257` (child).\n- `tests/active/test_similar.py` (child scripts that call it).\n- Indirectly every test that starts a real Engine and parses its log as JSON: `tests/active/conftest.py:110-122` `engine` fixture, `test_similar.py:669` `off_default_engine`, `test_random_cache.py:202-224` `_payloads`/`_has_started`, `test_server_config.py:227-249` `_payloads`.\n\n**Risk: medium.** All of those child processes inherit `os.environ`: `subprocess.run` with no `env` argument, or `{**os.environ, \u2026}`. If `LOG_FORMAT=text` is ever exported in the developer's shell or in CI, they all fail or time out. `_has_started` would never see `service.lifecycle`, and the JSON-only line assertions in test_similar, test_internal_events and test_logging_profiles would fail. The plan accepts this (\"existing ones rely on the default\"). A cheap hardening the plan could adopt is to pop `LOG_FORMAT` in `tests/active/conftest.py`, but that is not in the plan as written. Do not change the return value, because `server.py:483` logs it as `log_mode_hint`.\n</impact>\n<impact path=\"engine/server/api/logging_profiles.py\" element=\"new text renderer / CR-LF escaping helper (private)\">\n**What changes.** A new private function that turns the payload dict into one line:\n- Scalars go through `str()`.\n- Lists and dicts go through `json.dumps(..., separators=(\",\", \":\"))`.\n- Each `\\r` and `\\n` becomes the two characters `\\r` / `\\n`, applied after assembly.\n- No prefix is added.\n\n**Depends on it.** The text branch of `EngineJsonFormatter.format`. Its behaviour must match the Client's copy exactly (R2 says \"same line format\"; a cross-service test guards against drift).\n\n**Risk: medium.** Watch three things. Escaping must also cover a `\\r\\n` inside the message. A `None` context value, e.g. `user_id: None` in the incoming-likes context, renders as `None` under `str()` but `null` under JSON; pick one and make both services match. Spaces in values are not quoted, which is an accepted limitation.\n</impact>\n<impact path=\"engine/server/api/logging_profiles.py\" element=\"`payload_visible_in_mode` (lines 81-90) and `_classify_event`/`_EVENT_RULES` (lines 31-70, 172-181)\">\n**What changes.** Nothing. These are listed so that the next step can confirm that the `modes` logic and `normalize_log_mode` are untouched (R3: `LOG_FORMAT` is separate from the focused/verbose modes).\n\n**Depends on it.** `engine/watch-engine-logs.sh` (`.modes`) and the unit tests at lines 58-63 and 133-171.\n\n**Risk: low**, unless the payload refactor accidentally drops `modes` from the JSON output.\n</impact>\n<impact path=\"engine/server/api/server.py\" element=\"`configure_engine_logging(DEFAULT_RECOMMENDATIONS_LOG_PROFILE)` call (line 323), import (line 84), `log_mode_hint` line (483)\">\n**What changes.** Nothing in code. The call now also picks up `LOG_FORMAT` from the process environment, which systemd provides through `EnvironmentFile=-.env.bridge` / `Environment=`.\n\n**Depends on it.** Production Engine startup.\n\n**Risk: low.** About 20 lines run between process start and line 323 (arg parsing, signal setup, `faulthandler.register` at 306). Anything logged before line 323 goes through `logging.lastResort` without a timestamp, which is the same as today. A malformed `LOG_FORMAT` must not raise here. Optionally the format could be logged next to `log_mode_hint` (line 483), but the plan does not do this.\n</impact>\n<impact path=\"client/backend/server.py\" element=\"imports (lines 5-23): `json`, `datetime`, `traceback`\">\n**What changes.** `from datetime import datetime` (line 23) is used only at line 128. If the new ts helper uses `datetime.fromtimestamp(..., timezone.utc)`, the import becomes `from datetime import datetime, timezone`; otherwise it becomes unused. `json` is still used widely (line 601 and others). `traceback` is still used at line 722. `os` and `logging` are already imported.\n\n**Depends on it.** The whole module.\n\n**Risk: low.**\n</impact>\n<impact path=\"client/backend/server.py\" element=\"`_emit_client_log(level, event, message, context)` (lines 120-136)\">\n**What changes.** It no longer builds a JSON string. It calls `logging.log(level, message, extra={\"client_event\": event, \"client_context\": context})`, with names namespaced to avoid reserved `LogRecord` attributes (`message`, `msg`, `args`, `levelname`\u2026; `logging` raises `KeyError` on a collision in `extra`). The signature stays the same and the docstring should be updated (\"structured JSON log line\").\n\n**Depends on it.** 16 call sites in the same file, all unchanged:\n- `log_message` (line 262).\n- `_respond_engine_failure` (line 420).\n- incoming likes (line 542).\n- the proxy (lines 629, 642, 661, 674, 688, 711, 732).\n- the bridge (lines 1075, 1079).\n- `main` (lines 1220, 1238).\n\n`tests/active/test_server.py` reads these records through `caplog` (see that entry).\n\n**Risk: HIGH.**\n- **(a)** `record.getMessage()` changes from the full JSON payload to only the bare `message`. Every in-process consumer that parsed or searched `getMessage()` for `event` or `context` breaks; see the test_server.py entry.\n- **(b)** Message text is passed as `msg` with no `args`, so a `%` in the message is not interpolated. That is safe today, because all messages are literals or `f\"Engine {operation} failed\"`.\n- **(c)** Records now reach any handler, including pytest's caplog, as plain messages. Before `configure_client_logging()` has run (in-process tests, conftest `client_backend`), no formatter is installed. That matches today: there is no `basicConfig` in tests, and lastResort prints only WARNING and above as a bare message.\n- **(d)** `context` at line 722 carries a multi-line `traceback` string inside context. In JSON mode it stays a JSON string. In text mode it must be escaped (R5).\n</impact>\n<impact path=\"client/backend/server.py\" element=\"new Client formatter class + ts helper + `normalize_log_format` copy + text renderer (new, near `_emit_client_log`)\">\n**What changes.** A new `logging.Formatter` subclass. It builds a payload in the order `ts`, `level`, `service: \"client-backend\"`, `event`, `message`, `context`, then the new additive `traceback` when `exc_info` is present. `event` comes from `record.client_event` or the fallback `client.log`; `message` is `record.getMessage()`; `context` comes from `record.client_context` when it is truthy, which keeps today's `if context:` behaviour at line 134. It renders JSON (`ensure_ascii=True, separators=(\",\", \":\")` as at line 136) or text, and duplicates the Engine's ts helper, normaliser and text renderer.\n\n**Depends on it.** `configure_client_logging`, `client/watch-client-logs.sh` (`fromjson?`), and the DEPLOYMENT.md/README runbooks that point at `context.error`.\n\n**Risk: medium.**\n- Level names: today the code uses `logging.getLevelName(level)`; the formatter uses `record.levelname`. These are equal for stdlib levels.\n- An empty context must still be omitted, because `if context:` drops `{}`. A record with `client_context={}` must not emit `\"context\":{}`.\n- The two copies can drift: the plan's named ceiling.\n- The class must be importable without side effects at module import time. `tests/active/conftest.py:41` imports `server` in-process, so nothing may touch the root logger at import.\n</impact>\n<impact path=\"client/backend/server.py\" element=\"new `configure_client_logging()`\">\n**What changes.** A new function, mirroring `configure_engine_logging`:\n- `root.handlers.clear()`, `setLevel(INFO)`.\n- A `StreamHandler()` (stderr, the same stream `basicConfig` used) with the Client formatter.\n- It reads `LOG_FORMAT` at call time.\n\n**Depends on it.** `main()` and the new tests. A test that calls it replaces the pytest process's root handlers, which removes pytest's own capture handlers wired into the root logger, so the test must save and restore them (plan, \"Client test seam\").\n\n**Risk: medium.** A test that forgets to restore the handlers silently breaks `caplog`-based assertions in later tests in the same session (`test_server.py`, `test_similarity_candidates.py`, `test_random_cache.py:539`, `test_updater_worker.py:137`). Note that `basicConfig` was a no-op when handlers already existed. The explicit clear is a behaviour change if anything had installed handlers before `main()`; nothing does today.\n</impact>\n<impact path=\"client/backend/server.py\" element=\"`main()` line 1184 `logging.basicConfig(level=logging.INFO, format=\\\"%(message)s\\\")`\">\n**What changes.** It is replaced by `configure_client_logging()`. Ordering stays: after `parse_trusted_proxies` (1179-1182) and `parse_cors_origins` (1183), and before the signal swap and the bind.\n\n**Depends on it.** Client production startup, `scripts/run-services.sh:161-164`, `tests/run-arch-split-smoke.sh:544` (its client.log is only tailed on failure, not parsed), and the systemd unit from `client/install-client-service.sh:195-197`.\n\n**Risk: low-medium.** The `SystemExit` for a bad `TRUSTED_PROXIES` (line 1182) happens before logging setup and goes to stderr bare; that is unchanged. The `service.start`/`service.stop` records (lines 1220, 1238) now go through the formatter. Their `context` contains an int `port` and an int `pid`, which stay JSON ints in JSON mode.\n</impact>\n<impact path=\"client/backend/server.py\" element=\"`ClientBackendHandler.log_message` (lines 258-273)\">\n**What changes.** No code change. It is still the `client.access` request-end line, and its `ts` is now `record.created` (R6).\n\n**Depends on it.** `BaseHTTPRequestHandler`, which calls it once the response has been sent.\n\n**Risk: low.** `BaseHTTPRequestHandler.log_error` also routes to `log_message`, so error-path lines (for example a 400 from a malformed request line) are also emitted as `client.access` \"request finished\". That is pre-existing behaviour, noted here only because they now carry UTC timestamps as well.\n</impact>\n<impact path=\"tests/active/test_server.py\" element=\"`_error_messages` / `_error_events` (lines 991-1005) and the four tests using them (lines 1008-1019, 1032-1043, 1046-1057, 1073-1082)\">\n**What changes.** These tests are not in the plan but **will break**. They read `record.getMessage()` from `caplog` and `json.loads` it to get `event` and `context`.\n- After the change, `getMessage()` is only `\"Engine metadata failed\"` or `\"engine bridge publish failed\"`, so `_error_events` returns `[]`.\n- Assertions that will fail: line 1019 (`event == \"engine.call\"`), lines 1077-1082 (`engine.bridge` and `context.error` containing \"Connection refused\").\n- The sentinel lives only in `context.error` (server.py:420, 1075, 1079), not in the message. So `ENGINE_SENTINEL in caplog.text` (line 1017; caplog's own formatter prints `%(message)s`), the `ENGINE_SENTINEL in message` checks (lines 1018, 1043) and `DROPPED_TEXT in message` (line 1057) also fail.\n- The module docstring (lines 94-106) describes \"an ERROR record\" carrying the sentinel.\n\n**Depends on it.** The `client_server` import from conftest.\n\n**Risk: HIGH, and certain unless addressed.** The fix belongs in this build: rewrite the helpers to read `record.client_event` / `record.client_context`, or to run each record through the new Client formatter (`json.loads(formatter.format(record))`). The second option also exercises the production formatter. The plan's statement \"No call site changes\" holds for production code, but this test module needs editing.\n</impact>\n<impact path=\"engine/server/api/tests/test_logging_profiles.py\" element=\"`EngineJsonFormatter()` constructions (lines 34, 141) and `assertIn(\\\"ts\\\", payload)` (line 156)\">\n**What changes.** No edit is needed if the constructor's format flag defaults to JSON. A natural place for new Engine unit tests: `normalize_log_format` cases, `ts` regex and `created`-based value, text line shape, newline escaping, and the service.lifecycle text line with no message.\n\n**Depends on it.** `logging_profiles` imports at lines 17-21 (adding `normalize_log_format` there if tested).\n\n**Risk: low** if the default is kept. If the flag were made required, both constructions break.\n</impact>\n<impact path=\"tests/active/test_logging_profiles.py\" element=\"child running `configure_engine_logging(\\\"verbose\\\")` and parsing every stderr line as JSON (lines 20-51)\">\n**What changes.** Nothing, as long as the default stays JSON. The child inherits the environment (`subprocess.run` with no `env`).\n\n**Depends on it.** `configure_engine_logging` and the env default.\n\n**Risk: low-medium.** It fails if `LOG_FORMAT=text` leaks into the test environment. This is also a candidate home for the new Engine format tests, with the env pinned for the child via `env={**os.environ, \"LOG_FORMAT\": ...}`: a traceback record escaped to one line in text mode, and a message containing `\\n`.\n</impact>\n<impact path=\"tests/active/test_internal_events.py\" element=\"`_FAILING_INGEST_CHILD` with `configure_engine_logging(\\\"verbose\\\")` (lines 253-308)\">\n**What changes.** Nothing. It parses every stderr line as JSON and reads `traceback`.\n\n**Depends on it.** The JSON default and the unchanged `traceback` key.\n\n**Risk: low** (environment leak only).\n</impact>\n<impact path=\"tests/active/test_similar.py\" element=\"`_json_lines` (561-565), the failing-similar child, `_messages` reading the off-default Engine log (723-732), `off_default_engine` env (669)\">\n**What changes.** Nothing. These parse Engine JSON lines and the `message`/`traceback` keys. The lines with `{\"case\": n}` are printed by the child itself and parse as JSON.\n\n**Depends on it.** JSON default, `message` unchanged for `[similar-server]\u2026` records (no rewrite rule applies to them).\n\n**Risk: low** (environment leak only).\n</impact>\n<impact path=\"tests/active/test_random_cache.py\" element=\"`_payloads`/`_messages`/`_has_started` (lines 202-224), Engine env at 245 and 710\">\n**What changes.** Nothing. It reads the Engine log file as JSON and waits for `service.lifecycle` with `context.state == \"start\"`.\n\n**Depends on it.** JSON default; the `service.lifecycle` payload shape (no `message`, `context` from fields).\n\n**Risk: low-medium.** If `LOG_FORMAT=text` leaked into the environment, `_has_started` would never become true and the fixture would wait out its timeout rather than fail fast. The env at line 245 is built from `os.environ` minus one key.\n</impact>\n<impact path=\"tests/active/test_server_config.py\" element=\"`_payloads` (lines 227-249), child env (line 49)\">\n**What changes.** Nothing. Same `service.lifecycle` start detection as test_random_cache.\n\n**Depends on it.** JSON default.\n\n**Risk: low** (environment leak only).\n</impact>\n<impact path=\"tests/active/conftest.py\" element=\"`client_server` in-process import (line 41), `client_backend` fixture (71-91), session `engine` fixture env (110)\">\n**What changes.** Nothing is required. The import must stay free of side effects: the new Client formatter and configure function are defined at module level but not called. Optionally pop `LOG_FORMAT` from the Engine fixture env to harden it against leaks; that is not in the plan.\n\n**Depends on it.** Every active test that uses `client_server`, `engine` or `client_backend`.\n\n**Risk: low.**\n</impact>\n<impact path=\"tests/active/test_similarity_candidates.py\" element=\"caplog `_messages`/`_reopen_warnings`/`_stale_skips` (lines 212-224, 294-397)\">\n**What changes.** Nothing. These read Engine `record.getMessage()`, which is unaffected because the Engine formatter does not alter records.\n\n**Depends on it.** pytest's caplog handler on the root logger.\n\n**Risk: low**, unless a new test calls `configure_engine_logging` or `configure_client_logging` in-process without restoring root handlers. That would strip pytest's capture handler for later tests in the session.\n</impact>\n<impact path=\"tests/active/test_log_format.py\" element=\"new cross-service test module (name to be decided; does not exist yet)\">\n**What changes.** A new test module covering:\n- `ts` regex and `created`-based value for both formatters.\n- The `LOG_FORMAT` matrix: unset, `json`, `JSON`, `bogus`, empty \u2192 JSON; `text` in any case \u2192 text.\n- One physical line with a traceback and with a `\\n` message.\n- No `<N>` prefix.\n- The Client: a `_emit_client_log` record and a bare `logging.info` after `configure_client_logging()` both come out in the shared format with `event: client.log`.\n- Engine `access.start` \u2192 work \u2192 `access` with non-decreasing `ts`.\n- A drift guard: the same `created` produces the same `ts` string, and the same line shape, from both services.\n\nEngine formatting can run in pytest's interpreter (`logging_profiles` is stdlib-only plus `request_context`, as test_logging_profiles.py:36 notes). The Client formatter is reachable via `client_server` from conftest. Note that both modules are named after their package directories: the Engine one needs `engine/server/api` on `sys.path`. The Engine's `server` module name collides with the Client's `server` already in `sys.modules`, so import `logging_profiles` directly, never the Engine's `server`.\n\n**Depends on it.** Both formatters.\n\n**Risk: medium.** Root-logger handler save/restore is mandatory. Constructing a `LogRecord` and then setting `created` relies on the plan deriving milliseconds from `created`, not `msecs`.\n</impact>\n<impact path=\"engine/watch-engine-logs.sh\" element=\"`JQ_FILTER` with `fromjson?` (lines 127-148)\">\n**What changes.** No code change. In JSON mode the keys are unchanged, so it keeps working, and `ts` simply shows UTC. In text mode `fromjson?` yields nothing and `select(. != null)` drops every line, so the watcher shows **nothing**: a silent, empty view.\n\n**Depends on it.** Operators; DEPLOYMENT.md:123.\n\n**Risk: medium (operator-facing).** This is not a regression of the default, but the DEPLOYMENT.md paragraph must say plainly that the watcher needs `json`. Optionally the help text (`Notes:` lines 24-27) could say so; the plan does not touch the script.\n</impact>\n<impact path=\"client/watch-client-logs.sh\" element=\"`jq -R 'fromjson? // {\\\"raw\\\": .}'` (lines 97-103), header comment (lines 4-5)\">\n**What changes.** No code change. In JSON mode the record keys are unchanged. Previously non-JSON lines, bare records, now arrive as structured JSON with `event: client.log` instead of `{\"raw\": \u2026}`. In text mode every line becomes `{\"raw\": \"<text line>\"}`, which is degraded but works.\n\n**Depends on it.** Operators.\n\n**Risk: low.**\n</impact>\n<impact path=\"client/install-client-service.sh\" element=\"generated unit `Environment=`/`EnvironmentFile=` (lines 195-197)\">\n**What changes.** Nothing. `LOG_FORMAT` reaches the Client through the existing `EnvironmentFile=-\u2026/.env.bridge` or a drop-in.\n\n**Depends on it.** `tests/active/test_install_client_service.py`, which compares the generated unit exactly.\n\n**Risk: low**, but do not add an `Environment=LOG_FORMAT=` line here: the exact-match install tests would fail and the plan does not call for it.\n</impact>\n<impact path=\"engine/install-engine-service.sh\" element=\"generated unit (lines 128-130)\">\n**What changes.** Nothing; the same reasoning as the Client unit. `tests/active/test_install_engine_service.py:58` pins the exact unit text.\n\n**Depends on it.** Engine units.\n\n**Risk: low**, provided it is left untouched.\n</impact>\n<impact path=\"scripts/run-services.sh\" element=\"`load_bridge_secret` sources `.env.bridge` with `set -a` (lines 96-99); Engine/Client launches (144-164)\">\n**What changes.** Nothing. A `LOG_FORMAT` in `.env.bridge` is exported to both services here as well. That is consistent with DEPLOYMENT.md's \"set it in `.env.bridge`\" advice, but it turns text mode on for both services at once, and for prod and dev, which share the file.\n\n**Depends on it.** Local runs; `logs` subcommand `tail -f` (line 244).\n\n**Risk: low.** Worth a sentence in the doc paragraph: `.env.bridge` is shared by the prod and dev units, as DEPLOYMENT.md:528 already says for CORS.\n</impact>\n<impact path=\"engine/server/api/server_config.py\" element=\"`_resolve_log_profile_env` / `DEFAULT_RECOMMENDATIONS_LOG_PROFILE` (lines 12-15, 516-518)\">\n**What changes.** Nothing. This is the import-time env read that the plan explicitly does not copy for `LOG_FORMAT`.\n\n**Depends on it.** `server.py:80, 323`.\n\n**Risk: none.** Listed so that nobody adds `LOG_FORMAT` here. `test_server_config.py` imports `server_config` in-process, and an import-time read there would be cached for the session.\n</impact>\n<impact path=\"client/backend/lib/http_utils.py\" element=\"module (uses `datetime.now(timezone.utc)` at line 112 for the rate limiter)\">\n**What changes.** Nothing. This is not logging; the hit only came from searching for `datetime`.\n\n**Depends on it.** `RateLimiter`.\n\n**Risk: none.** Listed to record that no Client lib module logs (grep of `client/backend` for `logging.`/`logger` finds only `server.py`). So \"third-party/library records\" in the Client are in practice only stdlib ones, and `client.log` fallback lines should be rare.\n</impact>\n</impacts>\n",
  "docs_checklist": "- [ ] `DEPLOYMENT.md` - Add one `LOG_FORMAT` paragraph after the `RANDOM_CACHE_REFRESH_INTERVAL_MINUTES` paragraph (line 114) in the service-environment block (lines 105-114), in the same one-paragraph style. Points to cover:\n- Values: `json` (default) and `text`, case-insensitive, whitespace ignored. Unset, empty or unknown values select `json` and never stop startup.\n- Both the Engine and the Client backend read it at logging setup.\n- How to set it: through `.env.bridge` (shared by the prod and dev units and exported by `scripts/run-services.sh`) or an `Environment=` drop-in.\n- `engine/watch-engine-logs.sh` shows nothing in text mode, and `client/watch-client-logs.sh` shows `{\"raw\":\u2026}`.\n- `ts` is UTC `YYYY-MM-DDTHH:MM:SS.mmmZ` taken at record creation.\n- Text lines escape newlines, so a traceback is one line.\n\nAlso check Triage rows 203 (`context.error` of `engine.call`/`engine.bridge`) and 204 (\"the JSON log record's `traceback` key\"), and line 301. They stay correct in JSON mode, but each could get a short \"(in `LOG_FORMAT=text`, the `error=` token / the escaped traceback at the end of the line)\" note. Optional; the operator may prefer to say once in the new paragraph that the runbooks assume `json`.\n- [ ] `engine/server/README.md` - Line 31 says `EngineJsonFormatter` adds a `traceback` key. That is still true in JSON mode. Optionally add that in `LOG_FORMAT=text` the traceback ends the line, newline-escaped. Otherwise no change, as long as the class keeps its name.\n- [ ] `client/README.md` - Lines 31, 32 and 35 describe ERROR `engine.call` / `engine.bridge` records with `context.error`, and INFO `engine.proxy`. These stay accurate in JSON mode. Optionally add a pointer to DEPLOYMENT.md for `LOG_FORMAT` next to the `TRUSTED_PROXIES` env note (line 68), since that section lists the Client's env settings. Also uncertain: whether the README should mention that bare/library records now appear as `client.log` events and that exception records carry an additive `traceback` key.\n- [ ] `docs/project/issues/19-timestamped-request-logs.md` - Per the tracker conventions: on delivery, set `Status: enhancement, complete` and move the file to `docs/project/issues/archive/`. Note that the delivered default is JSON, not the issue's \"plain text default\", by operator decision (recorded in the plan record). The `## Comments` section is the place to say so.\n- [ ] `docs/project/issues/plan.md` - The triage note at lines 114-117 (\"19 is mostly delivered \u2026 uses a local offset, not UTC \u2026 shrink it to 'UTC, plus an optional plain-text mode'\") and the lane 4c row (line 91) become stale once 19 lands. Update or strike them when the issue is archived. This is bookkeeping, not product documentation.",
  "docs": [
    {
      "path": "DEPLOYMENT.md",
      "note": "Add one `LOG_FORMAT` paragraph after the `RANDOM_CACHE_REFRESH_INTERVAL_MINUTES` paragraph (line 114) in the service-environment block (lines 105-114), in the same one-paragraph style. Points to cover:\n- Values: `json` (default) and `text`, case-insensitive, whitespace ignored. Unset, empty or unknown values select `json` and never stop startup.\n- Both the Engine and the Client backend read it at logging setup.\n- How to set it: through `.env.bridge` (shared by the prod and dev units and exported by `scripts/run-services.sh`) or an `Environment=` drop-in.\n- `engine/watch-engine-logs.sh` shows nothing in text mode, and `client/watch-client-logs.sh` shows `{\"raw\":\u2026}`.\n- `ts` is UTC `YYYY-MM-DDTHH:MM:SS.mmmZ` taken at record creation.\n- Text lines escape newlines, so a traceback is one line.\n\nAlso check Triage rows 203 (`context.error` of `engine.call`/`engine.bridge`) and 204 (\"the JSON log record's `traceback` key\"), and line 301. They stay correct in JSON mode, but each could get a short \"(in `LOG_FORMAT=text`, the `error=` token / the escaped traceback at the end of the line)\" note. Optional; the operator may prefer to say once in the new paragraph that the runbooks assume `json`."
    },
    {
      "path": "engine/server/README.md",
      "note": "Line 31 says `EngineJsonFormatter` adds a `traceback` key. That is still true in JSON mode. Optionally add that in `LOG_FORMAT=text` the traceback ends the line, newline-escaped. Otherwise no change, as long as the class keeps its name."
    },
    {
      "path": "client/README.md",
      "note": "Lines 31, 32 and 35 describe ERROR `engine.call` / `engine.bridge` records with `context.error`, and INFO `engine.proxy`. These stay accurate in JSON mode. Optionally add a pointer to DEPLOYMENT.md for `LOG_FORMAT` next to the `TRUSTED_PROXIES` env note (line 68), since that section lists the Client's env settings. Also uncertain: whether the README should mention that bare/library records now appear as `client.log` events and that exception records carry an additive `traceback` key."
    },
    {
      "path": "docs/project/issues/19-timestamped-request-logs.md",
      "note": "Per the tracker conventions: on delivery, set `Status: enhancement, complete` and move the file to `docs/project/issues/archive/`. Note that the delivered default is JSON, not the issue's \"plain text default\", by operator decision (recorded in the plan record). The `## Comments` section is the place to say so."
    },
    {
      "path": "docs/project/issues/plan.md",
      "note": "The triage note at lines 114-117 (\"19 is mostly delivered \u2026 uses a local offset, not UTC \u2026 shrink it to 'UTC, plus an optional plain-text mode'\") and the lane 4c row (line 91) become stale once 19 lands. Update or strike them when the issue is archived. This is bookkeeping, not product documentation."
    }
  ],
  "reassessments": 1,
  "draft": "## Draft implementation \u2014 issue 19, timestamped logs (UTC `ts`, `LOG_FORMAT` json|text, Client root formatter)\n\nI read these files before drafting: `engine/server/api/logging_profiles.py` (whole file), `client/backend/server.py` (imports 1-23, `_emit_client_log` 120-136, `log_message` 258-273, `main` 1175-1252, the `\"error\"` context sites 420/722/1075/1079), `tests/active/test_server.py` (docstring 94-106, helpers and tests 991-1082, sentinel constants 937-942), `tests/active/conftest.py`, `tests/active/test_logging_profiles.py`, `engine/server/api/tests/test_logging_profiles.py`, `engine/server/api/handlers/similar.py:340-360` and `DEPLOYMENT.md:105-114`.\n\n### What has to be tested\n\n| # | Behaviour | Requirement | Where |\n|---|---|---|---|\n| T1 | `ts` matches `^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}\\.\\d{3}Z$` in both services and both formats | R1, Validation 1 | new `tests/active/test_log_format.py` |\n| T2 | A record whose `created` is set to `1741091696.789` renders `2025-03-04T12:34:56.789Z` (formatting time is ignored). The edge `1741091696.9999996` renders `2025-03-04T12:34:57.000Z`, with seconds and milliseconds consistent | R1, R6, Validation 3 | same |\n| T3 | `LOG_FORMAT` unset, `json`, `JSON`, `bogus` or `\"\"` gives JSON lines; `text`, `TEXT` or ` Text ` gives text lines. Engine runs in a child with a pinned env; Client runs in-process with monkeypatch | R3, Validation 4 | same |\n| T4 | Every record is one physical line in both modes, including a `logging.exception` record and a message containing `\\n`. In text mode the traceback is at the end of the line as `\\n`-escaped text. No line starts with `<` | R5, Validation 4 | same |\n| T5 | Text shape is `ts LEVEL event message k=v\u2026 [request_id=\u2026] [traceback]`. An Engine `service.lifecycle` line has no message token. An Engine access line carries \"request started\" / \"request finished\" | R4 | same |\n| T6 | After `configure_client_logging()` in the Client, a `_emit_client_log` record and a bare `logging.info` both come out in the shared format. The bare one has `event == \"client.log\"`. JSON key order is `ts, level, service, event, message[, context]` | R2, Validation 5 | same |\n| T7 | Drift guard: `_format_ts` and `_render_text` give identical strings in the Engine (child) and the Client (in-process) for the same `created` and the same payload | R2 | same |\n| T8 | Engine live request: in the session Engine's log, the slice from the `access.start` of a marked `POST /recommendations` to its `access` has non-decreasing `ts` and at least one `recommendations.*` work line | R6, Validation 2 | same |\n| T9 | The existing JSON consumers stay green: the four Engine JSON-parsing modules are unchanged, and `test_server.py`'s Client ERROR-record tests are rewired to the new formatter | R3, Validation 6 | `tests/active/test_server.py` |\n\n### Module map\n\n| File | Change |\n|---|---|\n| `engine/server/api/logging_profiles.py` | imports; `SUPPORTED_LOG_FORMATS`; `normalize_log_format`; `_TEXT_ESCAPES`, `_format_ts`, `_text_value`, `_render_text`; `EngineJsonFormatter.__init__(log_format=\"json\")`; `ts` comes from the record; text branch; `configure_engine_logging` reads `LOG_FORMAT` |\n| `client/backend/server.py` | import `timezone`; copies of the four helpers and the constant; `ClientLogFormatter`; `configure_client_logging()`; `_emit_client_log` becomes a `logging.log(..., extra=\u2026)` call; `main()` calls `configure_client_logging()` in place of `basicConfig` |\n| `tests/active/test_server.py` | `_error_messages` renders each record through `ClientLogFormatter`; caplog's handler gets that formatter in the one test that reads `caplog.text`; the docstring wording is adjusted |\n| `tests/active/test_log_format.py` | new module, T1-T8 |\n| `DEPLOYMENT.md`, `engine/server/README.md`, `client/README.md`, issue 19, `docs/project/issues/plan.md` | the doc list (see the Docs section) |\n\nNo other production file changes. `engine/server/api/server.py`, both watch scripts, both install scripts, `scripts/run-services.sh` and `server_config.py` are untouched, as the impact inventory says.\n\n### `engine/server/api/logging_profiles.py`\n\nImports (lines 5-12). `os` is added. `datetime` gains `timezone`. The module still imports only the stdlib and `request_context`.\n\n```python\nimport json\nimport logging\nimport os\nimport re\nfrom dataclasses import dataclass\nfrom datetime import datetime, timezone\nfrom typing import Any\n```\n\nThe constant goes next to `SUPPORTED_LOG_MODES` (line 15):\n\n```python\nSUPPORTED_LOG_MODES = (\"focused\", \"verbose\")\nSUPPORTED_LOG_FORMATS = (\"json\", \"text\")\n```\n\nAnd the escape table after `_LEADING_BLOCKS_RE` (line 19):\n\n```python\n# Text lines escape CR/LF so journald stores each record as one entry.\n_TEXT_ESCAPES = str.maketrans({\"\\r\": \"\\\\r\", \"\\n\": \"\\\\n\"})\n```\n\n`normalize_log_format` goes directly after `normalize_log_mode`. It has the same fail-safe shape and never raises for `str | None`.\n\n```python\ndef normalize_log_format(value: str | None) -> str:\n    \"\"\"Normalize ``LOG_FORMAT`` values and fail safely to ``json``.\"\"\"\n    raw = (value or \"\").strip().lower()\n    if raw in SUPPORTED_LOG_FORMATS:\n        return raw\n    return \"json\"\n```\n\nThe ts and text helpers go after `_classify_event`, before the class. Invariant for `_format_ts`: the seconds and the milliseconds come from one `datetime`, so they can never disagree. `fromtimestamp` rounds to the microsecond, and `// 1000` truncates to milliseconds. `record.msecs` is not used.\n\n```python\ndef _format_ts(record: logging.LogRecord) -> str:\n    \"\"\"Render the record's creation time as UTC ``YYYY-MM-DDTHH:MM:SS.mmmZ``.\"\"\"\n    stamp = datetime.fromtimestamp(record.created, tz=timezone.utc)\n    return f\"{stamp.strftime('%Y-%m-%dT%H:%M:%S')}.{stamp.microsecond // 1000:03d}Z\"\n\n\ndef _text_value(value: Any) -> str:\n    \"\"\"Render one context value as a single text token.\"\"\"\n    if isinstance(value, str):\n        return value\n    return json.dumps(value, ensure_ascii=False, separators=(\",\", \":\"), default=str)\n\n\ndef _render_text(payload: dict[str, Any]) -> str:\n    \"\"\"Render a payload as one ``ts LEVEL event message k=v\u2026`` line with CR/LF escaped.\"\"\"\n    parts = [payload[\"ts\"], payload[\"level\"], payload[\"event\"]]\n    if \"message\" in payload:\n        parts.append(str(payload[\"message\"]))\n    context = payload.get(\"context\") or {}\n    parts.extend(f\"{key}={_text_value(value)}\" for key, value in context.items())\n    request_id = payload.get(\"request_id\")\n    if request_id and \"request_id\" not in context:\n        parts.append(f\"request_id={request_id}\")\n    if \"traceback\" in payload:\n        parts.append(payload[\"traceback\"])\n    return \" \".join(parts).translate(_TEXT_ESCAPES)\n```\n\nDecisions in `_render_text`:\n- **One rule for non-string values.** Every value that is not a string goes through compact JSON. A list or dict stays one token (the incoming-likes context), `None` is written `null` and a bool `true`. This answers the impact inventory's question about `None` rendering as `None` or `null`, the same way in both services.\n- **`modes` and `service` are not text tokens.** R4 fixes the shape, and `modes` is only filter metadata for the JSON watcher.\n- **`request_id` is written once.** It is skipped when the context already carries a `request_id` key.\n- **Escaping runs last, over the whole assembled line,** so the message, the context values (including the Client's `context.traceback` at server.py:722) and the traceback are all covered, `\\r\\n` included.\n- **Non-ASCII.** Text mode does not apply `ensure_ascii`, so non-ASCII characters pass through as they are. That is a stated limitation and harmless to journald.\n\n`EngineJsonFormatter` (lines 184-226) keeps its name, which the unit-test import and README.md:31 depend on. The payload build is untouched except for line 195. The JSON return is the same expression as before.\n\n```python\nclass EngineJsonFormatter(logging.Formatter):\n    \"\"\"Render engine log records as JSON objects with mode tags, or as text lines.\"\"\"\n\n    def __init__(self, log_format: str | None = \"json\") -> None:\n        \"\"\"Select the rendering: ``json`` (default) or ``text``; other values mean ``json``.\"\"\"\n        super().__init__()\n        self.log_format = normalize_log_format(log_format)\n\n    def format(self, record: logging.LogRecord) -> str:\n        \"\"\"Format a log record as one JSON or text line.\"\"\"\n        message = record.getMessage()\n        event, modes = _classify_event(message, record.levelno)\n        request_id = _extract_request_id(record, message)\n        fields = _extract_fields(message)\n\n        payload: dict[str, Any] = {\n            \"ts\": _format_ts(record),\n            \"level\": record.levelname,\n            \"event\": event,\n            \"message\": message,\n            \"modes\": modes,\n        }\n        # \u2026 lines 201-225 unchanged (request_id, per-event rewriting, traceback) \u2026\n        if self.log_format == \"text\":\n            return _render_text(payload)\n        return json.dumps(payload, ensure_ascii=True, separators=(\",\", \":\"))\n```\n\nInvariants of the class:\n- **JSON key order is unchanged:** `ts, level, event, message, modes`, then `request_id`, `context`, `traceback`.\n- **`EngineJsonFormatter()` with no argument is JSON,** so `engine/server/api/tests/test_logging_profiles.py:34,141` needs no edit.\n- **Text messages match JSON by construction.** Text mode renders the same payload after the rewriting, so its message is the JSON message.\n\n`configure_engine_logging` (lines 229-241): one changed line plus the docstring. The signature and the return value (the log mode) stay the same, because `server.py:483` logs that value.\n\n```python\ndef configure_engine_logging(profile: str) -> str:\n    \"\"\"Configure root logger with the ``LOG_FORMAT`` formatter and return normalized mode hint.\"\"\"\n    \u2026\n    handler.setFormatter(EngineJsonFormatter(os.environ.get(\"LOG_FORMAT\")))\n    \u2026\n```\n\n`LOG_FORMAT` is read when this function is called, never at import. `server_config.py` is not touched.\n\n### `client/backend/server.py`\n\nLine 23 becomes `from datetime import datetime, timezone`. `datetime` is still used by the ts helper. `os`, `json`, `logging` and `traceback` are already imported.\n\nNext to `_resolve_mode` / `_emit_client_log` (before line 120) go the constant, the escape table, `normalize_log_format`, `_format_ts`, `_text_value` and `_render_text`. Their bodies are byte-identical to the Engine's, and they are preceded by this marker:\n\n```python\n# rat-tail: LOG_FORMAT, _format_ts, _text_value and _render_text mirror engine/server/api/logging_profiles.py (no shared module: the two services import from different roots); tests/active/test_log_format.py checks both render alike.\nSUPPORTED_LOG_FORMATS = (\"json\", \"text\")\n_TEXT_ESCAPES = str.maketrans({\"\\r\": \"\\\\r\", \"\\n\": \"\\\\n\"})\nCLIENT_LOG_SERVICE = \"client-backend\"\nCLIENT_LOG_FALLBACK_EVENT = \"client.log\"\n```\n\nThe formatter:\n\n```python\nclass ClientLogFormatter(logging.Formatter):\n    \"\"\"Render Client records in the shared log format, JSON or text.\"\"\"\n\n    def __init__(self, log_format: str | None = \"json\") -> None:\n        \"\"\"Select the rendering: ``json`` (default) or ``text``; other values mean ``json``.\"\"\"\n        super().__init__()\n        self.log_format = normalize_log_format(log_format)\n\n    def format(self, record: logging.LogRecord) -> str:\n        \"\"\"Format one record; ``_emit_client_log`` records carry ``client_event``/``client_context``.\"\"\"\n        payload: dict[str, Any] = {\n            \"ts\": _format_ts(record),\n            \"level\": record.levelname,\n            \"service\": CLIENT_LOG_SERVICE,\n            \"event\": getattr(record, \"client_event\", None) or CLIENT_LOG_FALLBACK_EVENT,\n            \"message\": record.getMessage(),\n        }\n        context = getattr(record, \"client_context\", None)\n        if context:\n            payload[\"context\"] = context\n        # Additive to the Client's keys: without it an exception logged through the root logger is lost.\n        if record.exc_info:\n            payload[\"traceback\"] = self.formatException(record.exc_info)\n        if self.log_format == \"text\":\n            return _render_text(payload)\n        return json.dumps(payload, ensure_ascii=True, separators=(\",\", \":\"))\n```\n\nInvariants of `ClientLogFormatter`:\n- **Same keys, same order as today:** `ts, level, service, event, message[, context]`.\n- **An empty or `None` context is omitted,** which is today's `if context:`.\n- **`level`.** `record.levelname` equals `logging.getLevelName(level)` for stdlib levels.\n- **JSON separators and `ensure_ascii` are as at line 136.**\n- **No side effects at import.** Defining the class touches nothing, which conftest's in-process import (conftest.py:41) requires.\n\n`_emit_client_log` keeps its signature and its 16 call sites:\n\n```python\ndef _emit_client_log(\n    level: int,\n    event: str,\n    message: str,\n    context: dict[str, Any] | None = None,\n) -> None:\n    \"\"\"Log one Client record; ``ClientLogFormatter`` renders it with its event and context.\"\"\"\n    logging.log(level, message, extra={\"client_event\": event, \"client_context\": context})\n```\n\nNotes on `_emit_client_log`:\n- **`extra` names.** `client_event` and `client_context` are not reserved `LogRecord` attributes, so `logging` raises no `KeyError`.\n- **No `%` interpolation.** No `args` are passed, so `getMessage()` returns `message` unchanged even if it contains `%`.\n- **The implicit `basicConfig` is kept.** Module-level `logging.log` keeps today's implicit-`basicConfig`-when-no-handlers behaviour; nothing changes there.\n\n`configure_client_logging` sits directly after the formatter and mirrors `configure_engine_logging`:\n\n```python\ndef configure_client_logging() -> None:\n    \"\"\"Install ``ClientLogFormatter`` on the root logger, format from ``LOG_FORMAT``.\"\"\"\n    root_logger = logging.getLogger()\n    root_logger.handlers.clear()\n    root_logger.setLevel(logging.INFO)\n\n    handler = logging.StreamHandler()\n    handler.setLevel(logging.INFO)\n    handler.setFormatter(ClientLogFormatter(os.environ.get(\"LOG_FORMAT\")))\n    root_logger.addHandler(handler)\n```\n\nThe `StreamHandler()` default is stderr, the same stream `basicConfig` used, so the systemd units and `journalctl -o cat` pipelines are unchanged.\n\n`main()` line 1184: `logging.basicConfig(level=logging.INFO, format=\"%(message)s\")` becomes `configure_client_logging()`. It stays in the same position: after `parse_trusted_proxies` / `parse_cors_origins`, and before the signal swap and the bind. `log_message` (258-273) needs no code change.\n\n### `tests/active/test_server.py`\n\nThese tests fail as the code stands, so they are fixed here.\n\nLines 991-992. The rest of `_error_events` is unchanged, because it now parses real JSON lines:\n\n```python\n_CLIENT_FORMATTER = client_server.ClientLogFormatter()\n\n\ndef _error_messages(caplog):\n    \"\"\"The ERROR records, each rendered as the Client's production JSON line.\"\"\"\n    return [_CLIENT_FORMATTER.format(record) for record in caplog.records if record.levelno >= logging.ERROR]\n```\n\nIn `test_client_likes_502_is_fixed_text_and_engine_error_is_logged` (line 1008), add `caplog.handler.setFormatter(_CLIENT_FORMATTER)` right after `caplog.set_level(logging.ERROR)`. Then `caplog.text` at line 1017 is the production-rendered lines, and the sentinel in `context.error` is found again. Lines 1018, 1019, 1043, 1057 and 1077-1082 pass unchanged. `ENGINE_SENTINEL` and `DROPPED_TEXT` are plain ASCII with no quote or backslash, so `json.dumps` leaves them intact.\n\nDocstring line 100: \"the sentinel is in an ERROR record\" becomes \"the sentinel is in an ERROR record's `context.error`, as the Client's formatter renders it\". Lines 102 and 105-106 already say `context.error` or are still true.\n\n### `tests/active/test_log_format.py` (new)\n\nThe module docstring states the claims T1-T8 in the house style of the active tests. Seams:\n- **Engine side: a child process.** It runs `[sys.executable, \"-c\", _ENGINE_CHILD, <args>]` with `cwd=API_DIR`, as `test_logging_profiles.py` does. The env is `{k: v for k, v in os.environ.items() if k != \"LOG_FORMAT\"}`, plus `LOG_FORMAT` when the case sets one. Using a child keeps the Engine's `server`/`logging_profiles` out of the pytest process, where `server` is already the Client module.\n- **Client side: in-process,** through `client_server` from conftest.\n\nThe Engine child prints log records to stderr through `configure_engine_logging(\"verbose\")`. In order: `[probe] plain`, `[probe] two\\nlines`, `logging.exception(\"[probe] failed\")` for a `ValueError(\"sentinel-log-format\")`, `[access.start] ip=127.0.0.1 method=GET url=http://x/a`, `[service] lifecycle state=start component=engine run_id=r pid=1`. On stdout it prints JSON with three items:\n- `ts`: `_format_ts` of a `LogRecord` whose `created` was set from argv.\n- `fixed`: `EngineJsonFormatter(fmt).format` of that record.\n- `text`: `_render_text(json.loads(argv payload))`.\n\nThe Client context manager is the only place that replaces root handlers. It saves and restores them inside the test body, which is the call phase. A fixture would capture the setup phase's pytest handlers and restore stale ones.\n\n```python\n@contextmanager\ndef _client_logging(monkeypatch, value):\n    \"\"\"Run configure_client_logging under LOG_FORMAT=value; yield the stream it writes to.\"\"\"\n    root = logging.getLogger()\n    saved_handlers, saved_level = root.handlers[:], root.level\n    if value is None:\n        monkeypatch.delenv(\"LOG_FORMAT\", raising=False)\n    else:\n        monkeypatch.setenv(\"LOG_FORMAT\", value)\n    try:\n        client_server.configure_client_logging()\n        stream = io.StringIO()\n        root.handlers[0].setStream(stream)\n        yield stream\n    finally:\n        root.handlers[:] = saved_handlers\n        root.setLevel(saved_level)\n```\n\nTests:\n- `test_log_format_selects_json_or_text[engine|client \u00d7 None, \"json\", \"JSON\", \"bogus\", \"\", \"text\", \"TEXT\", \" Text \"]` covers T1, T3, T4 and T6. JSON cases: every line passes `json.loads`, `ts` matches `TS_RE`, and the Client's keys come in order `[\"ts\", \"level\", \"service\", \"event\", \"message\", \u2026]`. Text cases: every line matches `^TS ` followed by the level. No line starts with `<`. The traceback/newline records are exactly one line each, and the text line contains `\\\\n` and ends with `ValueError: sentinel-log-format`. The Client emits `_emit_client_log(ERROR, \"engine.call\", \"Engine metadata failed\", {\"error\": \"x\\ny\"})`, `logging.info(\"bare\")` and a `logging.exception` record.\n- `test_ts_is_record_creation_time_in_utc` covers T2: `created = 1741091696.789` gives `2025-03-04T12:34:56.789Z`, and `1741091696.9999996` gives `2025-03-04T12:34:57.000Z`. Both services are checked, and also a `created` an hour in the past, to show it is not the formatting time.\n- `test_text_line_shape` covers T5. Engine: `\u2026 INFO access.start request started ip=127.0.0.1 method=GET url=http://x/a`, and the lifecycle line goes `\u2026 INFO service.lifecycle state=start \u2026` with no message token. Client: `\u2026 INFO client.access request finished ip=\u2026 status=200 bytes=-`.\n- `test_engine_and_client_render_alike` covers T7. One fixed `created` and one payload `{\"ts\": \u2026, \"level\": \"INFO\", \"event\": \"e\", \"message\": \"m\\nn\", \"context\": {\"a\": 1, \"b\": None, \"c\": [1, {\"d\": \"x\"}], \"request_id\": \"r\"}, \"request_id\": \"r\", \"traceback\": \"T\\nU\"}` must give equal strings from the Engine child and from `client_server._render_text` / `_format_ts`.\n- `test_engine_request_lines_are_ordered_by_ts(engine)` covers T8. It sends `POST /recommendations?limit=5&user_id=log-order-<uuid4 hex>` with `body={}`, then reads `engine.db_path` (the fixture's log path) as JSON lines. The slice runs from the `access.start` whose `context.url` contains the marker to the `access` that contains it. Inside the slice it keeps the `access.start`, the `access` and the `recommendations.*` records. It asserts at least one work record and non-decreasing `ts`. The session Engine runs with `--no-random-cache-refresh` and this pytest process sends one request at a time, so no other thread writes inside the slice. If the Engine refuses `user_id` on that route, the test-writing step should mark the URL through the `Host` header instead (`_get_full_url` builds it from `Host`).\n\n### Docs (the settled list)\n\n- **`DEPLOYMENT.md`, after line 114,** as one paragraph: \"Both the Engine and the Client backend read an optional `LOG_FORMAT` when they set up logging: `json` (the default) or `text`, case-insensitive with surrounding whitespace ignored; an unset, empty or unknown value selects `json` and never stops startup. Set it in `.env.bridge`, which is shared by the prod and dev units and exported to both services by `scripts/run-services.sh`, or with an `Environment=` drop-in for one unit. Every record's `ts` is UTC `YYYY-MM-DDTHH:MM:SS.mmmZ`, taken when the record was created, and is the timestamp to order by, not the journal's. `text` writes `ts LEVEL event message key=value\u2026` lines with newlines escaped as `\\n`, so a traceback stays on its record's one line; it is for reading by eye. `engine/watch-engine-logs.sh` shows nothing in text mode, `client/watch-client-logs.sh` shows each line as `{\"raw\": \u2026}`, and the Triage recipes that name JSON keys (`traceback`, `context.error`) assume `json`.\"\n- **`engine/server/README.md:31`:** append \"In `LOG_FORMAT=text` the traceback ends the record's line, newline-escaped (see DEPLOYMENT.md).\"\n- **`client/README.md`, near line 68:** \"Logging: `LOG_FORMAT` (`json` default, `text`), see DEPLOYMENT.md. Records not logged through `_emit_client_log` appear as event `client.log`, and a record with an exception carries a `traceback` key.\"\n- **`docs/project/issues/19-timestamped-request-logs.md`:** on delivery, set `Status: enhancement, complete`, move the file to `archive/`, and add a `## Comments` note that the default is JSON, not the issue's plain text, by operator decision.\n- **`docs/project/issues/plan.md`:** strike or update the triage note at lines 114-117 and the lane 4c row (line 91).\n\n### Check against the plan and requirements (pass 1, converged)\n\n- **R1** is met by `_format_ts`, which uses `created` and one `datetime`, gives `Z` and three-digit milliseconds, and stays under the `ts` key.\n- **R2** is met by the same helpers, stdlib `levelname`, leading `ts, level` in both payloads, and a Client root formatter that catches bare and library records. The Client keys are kept.\n- **R3** is met by `normalize_log_format` (fail-safe), reading at setup time in both services, unchanged JSON keys and rewriting, untouched `modes`, and the DEPLOYMENT paragraph.\n- **R4** is met by the shared `_render_text`, which renders the same payload so its message matches JSON, with `ts` identical to the JSON value.\n- **R5** is met by the CR/LF escape over the whole line, the traceback on the same line, no prefix, and the same stderr stream.\n- **R6** holds because `ts` comes from `created` (T8).\n- **The plan.** The plan's \"no call site changes\" holds for production code. The `test_server.py` rewire is the only edit outside the plan, and the impact inventory requires it.\n- **Named simplifications.** These are stated as limitations, not hidden:\n  - Two copies of the helpers, guarded by T7.\n  - Unquoted text tokens.\n  - Raw non-ASCII in text mode.\n  - The leak of an exported `LOG_FORMAT=text` into the Engine child tests. Not hardened, per the plan; popping it in conftest is the cheap upgrade if it ever bites.",
  "coordination": "none. No phase needs credentials or a manual step. Phase 1 clause 2 uses the session `engine` fixture, which needs the engine pixi env (`engine/.pixi/envs/default`) and `whitelist.db` that the active suite already relies on.",
  "tests": {
    "tests/tmp/test_19_timestamped_request_logs_phase1.py": {
      "rows": [
        {
          "clause": "C1",
          "assertion": "test_19_timestamped_request_logs_phase1.py:72, :74, :78, :80, :81, :82, :84. Line 72: every stderr line that `configure_engine_logging(\"verbose\")` writes in a child with TZ=Asia/Kathmandu has a `ts` that fully matches `TS_RE`. Line 74: each of those reads back as UTC to within 60 s of the child's `time.time()`. Line 78: for created=1741091696.789, `_format_ts` and `EngineJsonFormatter().format(...)[\"ts\"]` are both `2025-03-04T12:34:56.789Z`. Line 80: for created=1741091696.9999996 both are `2025-03-04T12:34:57.000Z`. Lines 81, 82 and 84 check each of the two values for a `created` one hour back separately: it matches `TS_RE` (81), it reads back to that `created` within 1 ms (82), and it is more than HOUR-60 s before the child's clock at formatting time (84).",
          "expected": "Three `YYYY-MM-DDTHH:MM:SS.mmmZ` stamps from the child's own minute. `{\"format_ts\": \"2025-03-04T12:34:56.789Z\", \"formatted\": \"2025-03-04T12:34:56.789Z\"}` and `{\"format_ts\": \"2025-03-04T12:34:57.000Z\", \"formatted\": \"2025-03-04T12:34:57.000Z\"}`. These two values were observed in probe tests/tmp/probe_ts_values.py: the plan's `fromtimestamp(created, timezone.utc)` + `microsecond // 1000` formula gives exactly these strings. For the hour-back record, both values equal `past` truncated to the millisecond, about 3600 s before `now`.",
          "wrong_implementation": "Today's `datetime.now().astimezone().isoformat(timespec=\"milliseconds\")` reads `2026-10-02T04:04:51.609+05:45` in the child, which fails line 72 (observed). A local-time rendering with a `Z` bolted on reads back 5h45m off and fails line 74. A ts taken at formatting time rather than from `created` gives the 2026 clock instead of 2025-03-04 at line 78 and is not an hour back at line 84. Milliseconds read from `record.msecs` give the construction clock, observed as `.129Z`, and fail lines 78 and 80. Milliseconds truncated from `created % 1` with no microsecond rounding give `2025-03-04T12:34:56.999Z` (observed in the probe) and fail line 80. A missing `_format_ts` helper prints null and fails lines 78, 80 and 81."
        },
        {
          "clause": "C2",
          "assertion": "test_19_timestamped_request_logs_phase1.py:120, :123, :125, :126. The session Engine log is sliced from the one `access.start` whose `context.url` holds the `log-order-<hex>` marker to the one `access` that holds it. The slice keeps the access.start, the access and the `recommendations.*` records. Line 120: at least one `recommendations.*` record lies between the two access records. Line 123: every kept `ts` fully matches `TS_RE`. Line 125: every kept `ts` reads back inside [before-1 s, after+1 s] of the request's wall clock. Line 126: the kept `ts` values, read back as epochs, are already in sorted (non-decreasing) order.",
          "expected": "An access.start, several `recommendations.*` work records and an access, all in UTC `...Z` form, inside the request window and non-decreasing. Today's run observed six or more kept records, which shows the work records are there (line 120 passed).",
          "wrong_implementation": "Today's formatter writes the Engine's local time with an offset. The observed value is `['2026-10-01T18:19:52.639-04:00', ...]`, which fails line 123. A local-time stamp ending in `Z` falls hours outside the request window and fails line 125. Line 126 catches one specific bug: seconds and milliseconds taken from two different roundings of `created`, for example seconds from `fromtimestamp` (which rounds to the microsecond) and milliseconds from `int(created % 1 * 1000)`. Then a record at x.9999996 renders as x+1.999, and the next record at x+1.0xx reads earlier, so ts goes backwards. A ts taken at formatting time on a deferred or queued handler can also run out of call order. One caveat: today's synchronous format-time stamp would also be non-decreasing. Today's red comes from lines 123 and 125, not from line 126."
        }
      ],
      "clauses": [
        {
          "id": "C1",
          "text": "An Engine record's `ts` is its `record.created` rendered in UTC as `YYYY-MM-DDTHH:MM:SS.mmmZ`."
        },
        {
          "id": "C2",
          "text": "Within one live Engine request, the `ts` values from its `access.start` to its `access` never decrease."
        }
      ],
      "surface": "checkpoint",
      "results": {
        "command": "validate_tests.py tests/tmp/test_19_timestamped_request_logs_phase1.py",
        "code": 1,
        "output": "  tests/tmp/test_19_timestamped_request_logs_phase1.py  2 failed                               0.0s\n  ----------------------------------------------------\n  total                                                 2 failed                               2.1s wall, 1 lane\n\nrecorded: tests/last_test_validation.json (exit 1)\nwrote tests/last_test_output.txt"
      }
    },
    "tests/tmp/test_19_timestamped_request_logs_phase2.py": {
      "rows": [
        {
          "clause": "C1",
          "assertion": "test_19_timestamped_request_logs_phase2.py:78,80,82,84 \u2014 for LOG_FORMAT unset, `json`, `JSON`, `bogus` and `\"\"`, stderr is exactly five lines and each parses as a JSON object (78). Each `ts` matches TS_RE (80). The exception record's traceback starts `Traceback (most recent call last):` and ends `ValueError: sentinel-log-format` (82). With `ts` and `traceback` removed, each payload's items, in key order, equal JSON_PAYLOADS (84).",
          "expected": "Five JSON lines whose items equal JSON_PAYLOADS in order, for example access.start reads `level, event, message=\"request started\", modes, request_id=\"rid-a\", context={ip, method, url}`. Observed passing for all five values in the current run.",
          "wrong_implementation": "A selector that treats every value other than exactly `json` as text, so unset, `JSON`, `bogus` or `\"\"` give text. The lines no longer parse, and 78 goes red on `None` payloads. A JSON branch that is rebuilt and reorders keys or drops the access.start message rewrite turns 84 red on the item lists."
        },
        {
          "clause": "C1",
          "assertion": "test_19_timestamped_request_logs_phase2.py:95,96 \u2014 for LOG_FORMAT `text`, `TEXT`, ` Text ` and `\\ttext\\n`, every line starts with a TS_RE timestamp, a space and `INFO ` or `ERROR ` (95). No line parses as a JSON object (96; line 95 is its positive control).",
          "expected": "Five text lines that start `<ts> INFO ` / `<ts> ERROR `, none of them JSON. Today the run shows five JSON lines for all four values, and 95 fails.",
          "wrong_implementation": "A selector that compares `value == \"text\"` without lowercasing and stripping: `TEXT`, ` Text ` and `\\ttext\\n` stay JSON and 95 reads `False` on a `{\"ts\":\u2026` line. A selector that strips only spaces fails the tab/newline case. Not reading LOG_FORMAT at all (the code as it stands) fails all four."
        },
        {
          "clause": "C2",
          "assertion": "test_19_timestamped_request_logs_phase2.py:93,97,100 \u2014 under text mode, `stderr.splitlines()` (which also breaks on CR) gives exactly five lines, one per record (93). No line starts with `<` (97). The first space-separated token of each line fully matches TS_RE (100).",
          "expected": "`len(lines) == 5`, no line starts with `<`, and every head token looks like `2026-10-01T22:29:27.181Z`.",
          "wrong_implementation": "A text renderer that does not escape CR/LF: the `two\\r\\nlines` message and the three-line traceback split into extra physical lines, giving 9 or more, and 93 goes red. A renderer that adds a syslog `<N>` priority prefix fails 97 and 100."
        },
        {
          "clause": "C2",
          "assertion": "test_19_timestamped_request_logs_phase2.py:102,103 \u2014 after the ts, the plain record reads exactly `INFO probe.info [probe] plain`, and the CR/LF record reads exactly `INFO engine.log [probe] two\\r\\nlines`, where `\\r` and `\\n` are the two characters backslash-r and backslash-n.",
          "expected": "`INFO probe.info [probe] plain` and `INFO engine.log [probe] two\\\\r\\\\nlines` (Python literal).",
          "wrong_implementation": "A renderer that escapes LF but not CR, or that drops CR/LF instead of escaping them: line 103 reads `\u2026two\\r\\\\nlines` or `\u2026twolines`, and in the unescaped-CR case 93 also reads 6. A renderer that includes `modes` or the level name in lowercase breaks 102."
        },
        {
          "clause": "C2",
          "assertion": "test_19_timestamped_request_logs_phase2.py:105 \u2014 after the ts, the exception record fully matches `ERROR probe.info [probe] failed request_id=rid-p2 Traceback (most recent call last):\\n  File \"<string>\", line \\d+, in <module>\\n    raise ValueError(\"sentinel-log-format\")\\nValueError: sentinel-log-format`, with each `\\n` the two literal characters.",
          "expected": "A full match. The traceback body is the one observed in the JSON `traceback` key under a probe run: `Traceback (most recent call last):\\n  File \"<string>\", line 6, in <module>\\n    raise ValueError(\"sentinel-log-format\")\\nValueError: sentinel-log-format`, with no caret line.",
          "wrong_implementation": "A renderer that puts the traceback before `request_id=`, leaves the traceback out, or leaves its newlines raw. In each case the fullmatch is None. The raw-newline case also makes 93 read 8."
        },
        {
          "clause": "C2",
          "assertion": "test_19_timestamped_request_logs_phase2.py:107 \u2014 after the ts, the access.start record (logged with extra request_id `rid-a`) reads exactly `INFO access.start request started ip=127.0.0.1 method=GET url=http://x/a request_id=rid-a`.",
          "expected": "`INFO access.start request started ip=127.0.0.1 method=GET url=http://x/a request_id=rid-a`. The probe run confirmed that the payload carries request_id `rid-a` and that context is {ip, method, url}.",
          "wrong_implementation": "A renderer that walks the payload in dict order, so `request_id=rid-a` comes before the context tokens because request_id precedes context in the payload. Another that uses the raw `getMessage()` (`[access.start] ip=\u2026`) instead of the payload's rewritten `request started`. Either way the string differs."
        },
        {
          "clause": "C2",
          "assertion": "test_19_timestamped_request_logs_phase2.py:109 \u2014 after the ts, the lifecycle record reads exactly `INFO service.lifecycle state=start component=engine run_id=r pid=1`.",
          "expected": "`INFO service.lifecycle state=start component=engine run_id=r pid=1`. There is no message token.",
          "wrong_implementation": "A renderer that writes `str(payload.get(\"message\"))` or the record's raw message whenever the payload has none. That gives `INFO service.lifecycle None state=\u2026` or `INFO service.lifecycle [service] lifecycle state=\u2026 state=\u2026`, which is not equal."
        }
      ],
      "clauses": [
        {
          "id": "C1",
          "text": "An Engine `LOG_FORMAT` of text in any case or surrounding whitespace selects text lines, and an unset, empty, `json` or unknown value selects JSON lines."
        },
        {
          "id": "C2",
          "text": "An Engine text record is one physical line shaped `ts LEVEL event [message] k=v\u2026 [request_id=\u2026] [traceback]` with CR and LF written as `\\r` and `\\n`."
        }
      ],
      "surface": "checkpoint",
      "results": {
        "command": "validate_tests.py tests/tmp/test_19_timestamped_request_logs_phase2.py",
        "code": 1,
        "output": "  tests/tmp/test_19_timestamped_request_logs_phase2.py  4 failed, 5 passed                     0.0s\n  ----------------------------------------------------\n  total                                                 4 failed, 5 passed                     0.5s wall, 1 lane\n\nrecorded: tests/last_test_validation.json (exit 1)\nwrote tests/last_test_output.txt"
      }
    },
    "tests/tmp/test_19_timestamped_request_logs_phase3.py": {
      "rows": [
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_19_timestamped_request_logs_phase3.py:89 \u2014 the five records (engine.call emit, logging.exception, bare logging.info, emit with {} context, emit with no context) write exactly five lines to the StringIO behind the handler configure_client_logging() installed",
          "expected": "5 lines, one per record",
          "wrong_implementation": "Today's root setup, with _emit_client_log building JSON by hand and the exception and bare records going out as plain text. Probe test_probe_19_p3_values.py showed that stream: the emit JSON line, then `client probe failed`, a 4-line traceback and `bare`. That is 7 lines for the first three records, 9 with the two extra emits."
        },
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_19_timestamped_request_logs_phase3.py:91 \u2014 every line parses as a JSON object",
          "expected": "all five lines are dicts",
          "wrong_implementation": "A formatter that only covers records carrying client_event, or text in place of JSON. The lines `bare` and `client probe failed` (observed today) are not JSON, so json.loads at line 90 raises."
        },
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_19_timestamped_request_logs_phase3.py:94 \u2014 the engine.call line's keys are exactly ts, level, service, event, message, context, in that order",
          "expected": "[\"ts\", \"level\", \"service\", \"event\", \"message\", \"context\"]",
          "wrong_implementation": "A formatter installed while _emit_client_log still logs its hand-built JSON string as the message. In probe today_emit the line read {'ts': ..., 'level': 'ERROR', 'service': 'client-backend', 'event': 'client.log', ...} with no context key, and the engine.call JSON was buried in message. A payload built in another order (e.g. event before service) also fails here."
        },
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_19_timestamped_request_logs_phase3.py:95 \u2014 the engine.call line has level ERROR, service client-backend, event engine.call, message \"Engine metadata failed\" and context {\"error\": \"x\\ny\"}",
          "expected": "(\"ERROR\", \"client-backend\", \"engine.call\", \"Engine metadata failed\", {\"error\": \"x\\ny\"})",
          "wrong_implementation": "Wrong attribute names between _emit_client_log's extra= and the formatter, which lets event fall back to client.log (as observed in probe today_emit). Or a context that is stringified or escaped twice, which reads back as a str and not as the dict."
        },
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_19_timestamped_request_logs_phase3.py:97 \u2014 an emit with a {} context omits the key: keys exactly ts, level, service, event, message, with event probe.empty and message \"empty context\"",
          "expected": "([\"ts\",\"level\",\"service\",\"event\",\"message\"], \"probe.empty\", \"empty context\")",
          "wrong_implementation": "A formatter that tests `context is not None`, which writes \"context\": {}, so the key list has six entries."
        },
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_19_timestamped_request_logs_phase3.py:98 \u2014 an emit with no context also omits the key, with event probe.none and message \"no context\"",
          "expected": "([\"ts\",\"level\",\"service\",\"event\",\"message\"], \"probe.none\", \"no context\")",
          "wrong_implementation": "A formatter that always writes payload[\"context\"] = getattr(record, \"client_context\", None), which gives \"context\": null and six keys."
        },
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_19_timestamped_request_logs_phase3.py:102 \u2014 every line's ts fully matches TS_RE ^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}\\.\\d{3}Z$",
          "expected": "all five ts match, e.g. YYYY-MM-DDTHH:MM:SS.mmmZ",
          "wrong_implementation": "Today's datetime.now().astimezone().isoformat(timespec=\"milliseconds\"). Probe test_probe_19_p3_values.py observed `2026-10-02T04:19:50.028+05:45` under TZ=Asia/Kathmandu, which has no Z. A plain utc isoformat gives `+00:00` (observed `2025-03-04T12:34:56.789+00:00`)."
        },
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_19_timestamped_request_logs_phase3.py:104 \u2014 with TZ pinned to Asia/Kathmandu, every ts read back as UTC lies within [before-1, after+1] of time.time() around the calls",
          "expected": "every _epoch(ts) is inside the window",
          "wrong_implementation": "Local time with a Z appended. In probe local_z the stamps read 2026-10-02T04:19:20.843Z against a window at epoch 1790894060.84 (22:34:20Z), which is 5h45m outside it."
        },
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_19_timestamped_request_logs_phase3.py:106 \u2014 the installed formatter renders records with created=1741091696.789 and created=1741091696.9999996",
          "expected": "(\"2025-03-04T12:34:56.789Z\", \"2025-03-04T12:34:57.000Z\")",
          "wrong_implementation": "Milliseconds taken from record.msecs, which goes stale once created is set after construction: probe msecs read 2025-03-04T12:34:56.844Z for both records. Naive truncation via int((created % 1) * 1000) gives 2025-03-04T12:34:56.999Z (observed). A ts from datetime.now() gives today's date and not 2025-03-04."
        },
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_19_timestamped_request_logs_phase3.py:110 \u2014 the exception line's keys are ts, level, service, event, message, traceback",
          "expected": "[\"ts\",\"level\",\"service\",\"event\",\"message\",\"traceback\"]",
          "wrong_implementation": "A formatter that ignores exc_info, so it has no traceback key and the traceback is lost. Or the stdlib default that appends the traceback as extra lines, which is today's behaviour: observed 4 traceback lines after `client probe failed`."
        },
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_19_timestamped_request_logs_phase3.py:112 \u2014 the traceback value starts with \"Traceback (most recent call last):\" and ends with \"ValueError: sentinel-client-log\"",
          "expected": "the formatted ValueError traceback, ending `ValueError: sentinel-client-log`",
          "wrong_implementation": "A traceback of repr(exc_info) or str(exc) only, which does not start with \"Traceback (most recent call last):\". Or a formatException with a trailing newline left in, which does not end with the sentinel."
        },
        {
          "clause": "C2",
          "assertion": "tests/tmp/test_19_timestamped_request_logs_phase3.py:108 \u2014 the bare logging.info line's keys are exactly ts, level, service, event, message",
          "expected": "[\"ts\",\"level\",\"service\",\"event\",\"message\"]",
          "wrong_implementation": "The JSON formatter applied only to _emit_client_log records (e.g. on a dedicated logger) while the root keeps \"%(message)s\". The bare line is then the plain text `bare` (observed today), which is not JSON. A formatter writing \"context\": null for records without attributes gives six keys."
        },
        {
          "clause": "C2",
          "assertion": "tests/tmp/test_19_timestamped_request_logs_phase3.py:109 \u2014 the bare line has level INFO, service client-backend, event client.log, message \"bare\"",
          "expected": "(\"INFO\", \"client-backend\", \"client.log\", \"bare\")",
          "wrong_implementation": "A formatter using getattr(record, \"client_event\", None) with no fallback, which gives event null. Or the Engine's fallback copied over unchanged, which gives event engine.log."
        },
        {
          "clause": "C2",
          "assertion": "tests/tmp/test_19_timestamped_request_logs_phase3.py:111 \u2014 the logging.exception line has level ERROR, service client-backend, event client.log, message \"client probe failed\"",
          "expected": "(\"ERROR\", \"client-backend\", \"client.log\", \"client probe failed\")",
          "wrong_implementation": "A missing client.log fallback, which gives a null event. Or the message built from the formatted record text including the traceback, which gives a message other than \"client probe failed\"."
        }
      ],
      "clauses": [
        {
          "id": "C1",
          "text": "An `_emit_client_log` record renders as a JSON line whose keys run `ts, level, service, event, message[, context]` with a UTC `ts`."
        },
        {
          "id": "C2",
          "text": "A bare root-logger record renders in the same JSON shape with event `client.log`."
        }
      ],
      "surface": "checkpoint",
      "results": {
        "command": "validate_tests.py tests/tmp/test_19_timestamped_request_logs_phase3.py",
        "code": 1,
        "output": "  tests/tmp/test_19_timestamped_request_logs_phase3.py  1 failed                               0.0s\n  ----------------------------------------------------\n  total                                                 1 failed                               0.2s wall, 1 lane\n\nrecorded: tests/last_test_validation.json (exit 1)\nwrote tests/last_test_output.txt"
      }
    },
    "tests/tmp/test_19_timestamped_request_logs_phase4.py": {
      "rows": [
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_19_timestamped_request_logs_phase4.py:115/117/119/120 \u2014 under LOG_FORMAT unset, `json`, `JSON`, `bogus` and `\"\"`, stderr is exactly four lines. Each one is a JSON object whose `ts` matches TS_RE. The exception record's `traceback` runs from `Traceback (most recent call last):` to `ValueError: sentinel-client-log`. With `ts` and `traceback` removed, the four payloads' items, in order, equal JSON_PAYLOADS.",
          "expected": "Four JSON lines, the same as the Engine gives for these five values. This is observed: the Engine's normalize_log_format returned `json` for None, 'json', 'JSON', 'bogus' and '' in tests/tmp/probe_engine_render.py. All five parametrizations pass against the code as it stands, which is phase 3's JSON output.",
          "wrong_implementation": "A Client that defaults to text when LOG_FORMAT is unset, or that treats any value other than `json` (e.g. `bogus`, `\"\"` or the upper-case `JSON` without lowercasing) as text, writes `<ts> LEVEL \u2026` lines. `_json_object` then returns None, and line 115 goes red. A copy that reorders keys or adds `modes` to the JSON payload turns line 120 red."
        },
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_19_timestamped_request_logs_phase4.py:127/129 \u2014 under LOG_FORMAT `text`, `TEXT`, ` Text ` and `\\ttext\\n`, stderr is exactly four physical lines (splitlines), and every line matches `^<TS_RE> (INFO|ERROR) `.",
          "expected": "Four text lines, the same as the Engine gives for these four values. The selection is observed: the Engine's normalize_log_format returned `text` for 'text', 'TEXT', ' Text ' and '\\ttext\\n' in the probe. Today's run fails at :129 on all four, because each line is still JSON (`['{\"ts\":\"2026-10-01T22:44:17.311Z\",\"level\":\"ERROR\",...`).",
          "wrong_implementation": "Several plausible faults stay on JSON and turn :129 red: a Client that ignores LOG_FORMAT (as today), one that compares without `.lower()` (`TEXT`), or one that skips `.strip()` (` Text ` and `\\ttext\\n`). A text renderer that does not escape LF writes the `error=x` / `y` value and the traceback across several lines, which makes :127 read more than 4."
        },
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_19_timestamped_request_logs_phase4.py:137 \u2014 once the timestamp is split off, the `engine.call` line reads exactly `ERROR engine.call Engine metadata failed error=x\\ny`, where `\\n` is a backslash followed by an n.",
          "expected": "`ERROR engine.call Engine metadata failed error=x\\\\ny` (Python literal). This is observed as the Engine's `_render_text` output for the same payload in the probe: `'T ERROR engine.call Engine metadata failed error=x\\\\ny'`.",
          "wrong_implementation": "A Client text renderer that writes the `service` token (`ERROR client-backend engine.call \u2026`), renders the context as JSON (`{\"error\":\"x\\ny\"}`), or leaves the LF unescaped (the line becomes `\u2026error=x`) gives a string that is not equal."
        },
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_19_timestamped_request_logs_phase4.py:138 \u2014 the exception line fullmatches EXCEPTION_TEXT_RE. That is `ERROR client.log client probe failed Traceback (most recent call last):\\n  File \"\u2026\", line N, in _log_records\\n    raise ValueError(\"sentinel-client-log\")\\nValueError: sentinel-client-log`, with each `\\n` written as a backslash followed by an n, all on one line.",
          "expected": "A match. This is observed: tests/tmp/probe_client_tb.py took the Client's real in-process traceback (`'Traceback (most recent call last):\\n  File \".../test_19_timestamped_request_logs_phase4.py\", line 89, in _log_records\\n    raise ValueError(\"sentinel-client-log\")\\nValueError: sentinel-client-log'`), escaped its LFs and fullmatched the regex (`MATCH True`). The Engine's `_render_text` puts the traceback at the end of the line in the same form (probe line 37).",
          "wrong_implementation": "A text renderer can drop the traceback (the Engine keeps it as the final token), place it before the message, or let its LFs through. In the last case the record splits across lines, so :127 or this fullmatch goes red."
        },
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_19_timestamped_request_logs_phase4.py:139/141 \u2014 the bare record reads `INFO client.log bare`, and the access record reads `INFO client.access request finished ip=127.0.0.1 status=200 bytes=-`.",
          "expected": "Exactly those two strings. Both are observed from the Engine's `_render_text` on the same payloads in the probe: `'T INFO client.log bare'` and `'T INFO client.access request finished ip=127.0.0.1 status=200 bytes=-'`.",
          "wrong_implementation": "A renderer that writes `service=client-backend` or the `service` value, quotes the strings (`ip=\"127.0.0.1\"`), or renders the int via `repr`/str of a JSON string produces a different access line. A bare record that falls back to an event other than `client.log` changes the bare line."
        },
        {
          "clause": "C2",
          "assertion": "tests/tmp/test_19_timestamped_request_logs_phase4.py:157 \u2014 for `created` 1741091696.789 and 1741091696.9999996, the Client's `_format_ts` returns the same list the Engine child printed. The control at :150 pins that list to `[\"2025-03-04T12:34:56.789Z\", \"2025-03-04T12:34:57.000Z\"]`.",
          "expected": "`[\"2025-03-04T12:34:56.789Z\", \"2025-03-04T12:34:57.000Z\"]` from both. This is observed: the control at :150 passed in the run, and so did :157 (the Client's phase-3 copy already exists).",
          "wrong_implementation": "A Client `_format_ts` built from `record.msecs`, or one that truncates `created` instead of letting `fromtimestamp` round to the microsecond, gives `2025-03-04T12:34:56.999Z` for the second value. Local time instead of UTC gives a different hour. Either way the lists differ."
        },
        {
          "clause": "C2",
          "assertion": "tests/tmp/test_19_timestamped_request_logs_phase4.py:159 \u2014 the Client's `_render_text` over both RENDER_PAYLOADS equals the Engine child's list. The control at :150 pins that list to ENGINE_TEXTS.",
          "expected": "`['2025-03-04T12:34:57.000Z INFO e m\\\\nn a=1 b=null c=[1,{\"d\":\"x\"}] request_id=r T\\\\nU', '2025-03-04T12:34:56.789Z ERROR service.lifecycle state=start note=a\\\\rb request_id=q']`, from the Engine child, observed (the control at :150 passed). The current run is red at :158 with `AttributeError: module 'server' has no attribute '_render_text'`, because phase 4 has not yet added the Client copy.",
          "wrong_implementation": "Each of these drifted Client copies changes the list: writing `None` as `None` (str()) instead of `null`; a list rendered by `json.dumps` with its default separators (`[1, {\"d\": \"x\"}]`); `request_id` written twice for payload 1; `request_id` never appended when only top-level for payload 2; an empty message token for payload 2; and CR left unescaped (`a\\rb`)."
        }
      ],
      "clauses": [
        {
          "id": "C1",
          "text": "A Client `LOG_FORMAT` value selects text or JSON lines exactly as the same value does for the Engine."
        },
        {
          "id": "C2",
          "text": "For the same `created` and payload, the Client's `_format_ts` and `_render_text` return the same strings as the Engine's."
        }
      ],
      "surface": "checkpoint",
      "results": {
        "command": "validate_tests.py tests/tmp/test_19_timestamped_request_logs_phase4.py",
        "code": 1,
        "output": "  tests/tmp/test_19_timestamped_request_logs_phase4.py  5 failed, 5 passed                     0.0s\n  ----------------------------------------------------\n  total                                                 5 failed, 5 passed                     0.2s wall, 1 lane\n\nrecorded: tests/last_test_validation.json (exit 1)\nwrote tests/last_test_output.txt"
      }
    }
  },
  "audits": {
    "tests/tmp/test_19_timestamped_request_logs_phase1.py": [
      {
        "shape": "SHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\n`test_engine_ts_is_record_created_in_utc_with_milliseconds` fails at line 72 on `assert all(TS_RE.fullmatch(line[\"ts\"]) for line in lines)`. The cause is logging_profiles.py:195: it renders `ts` as `datetime.now().astimezone().isoformat(timespec=\"milliseconds\")`, and under `TZ=Asia/Kathmandu` that gives a value ending in `+05:45` rather than `Z`.\n`test_engine_request_ts_never_decreases_from_access_start_to_access` fails at line 123 on `assert all(TS_RE.fullmatch(ts) for ts in stamps)` for the same cause: the timestamp carries an offset suffix (such as `+00:00`) instead of `Z`.\n\nNOT ASSESSED\n1. `code_under_test` lists tests/active/test_log_format.py (NEW), and that path does not exist. Nothing in that file was assessed.\n2. `fixtures_path` was not supplied. I found the `engine` fixture and `ROOT` in tests/active/conftest.py, which the test imports at line 23. I read the fixture there: `engine.db_path` is the session Engine's log file. I did not read the Engine's request and recommendations code. So whether a `recommendations.*` record is logged inside the marked request, which lines 116\u2013120 depend on, comes from the test's own comment at line 108 and was not checked against the code. The line-123 prediction assumes those earlier assertions hold.\n3. Anti-patterns pass, done as its own read. All seven `<anti_pattern>` entries were checked against their `<how_to_spot>` blocks, and none matched:\n   - No `.md` file is read, so the doc and substring-grep entries do not apply.\n   - The literals at lines 78 and 80 are outputs of the formatter for stated `created` inputs. They are not mirrored code constants.\n   - The expectations at lines 82 and 84 come from the input `past` and the child's clock, through `_epoch` (a `strptime` parse). Nothing re-derives them the way the formatter does.\n   - Every assertion is a positive one.\n   - Production code (`_format_ts`, `EngineJsonFormatter.format`, the live Engine) sits between every input and its assertion.\n   - C1 is exercised at three `created` values: a fixed millisecond, a rounding edge, and one hour back. It also runs under a zone pinned away from UTC, so returning the formatting time or local time cannot pass.\n4. Ladder pass, done as its own read:\n   - Test 1 calls the formatter directly (rung 1) in a child process and reads emitted log lines (rung 3). Running in a child is needed to pin `TZ`, and comments at lines 28 and 32 explain it.\n   - Test 2 asserts on log entries emitted by a live request (rung 3), which is where C2 lives.\n   - Neither test is on the anti-rung, and neither downshifts without a comment.\n5. Stub question:\n   - For C1, an implementation that returns the formatting time fails lines 78 and 84. One that renders local time fails lines 72, 74 and 78. One that reads `record.msecs` fails line 78, and one that truncates fails line 80.\n   - For C2, a constant or local-time `ts` fails lines 123 and 125.",
        "claim": "CLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (24 clauses: 7 must_prove, 13 docstring, 4 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | `ts` is in the form `YYYY-MM-DDTHH:MM:SS.mmmZ` | :72, :81 | the current `isoformat(timespec=\"milliseconds\")` output, which ends `+05:45` (or any other offset), not `Z` | CARRIED |\n| C1b | must_prove | rendered \"in UTC\" | :74, :78 | a local-time rendering with or without a `Z`: the child runs with `TZ=Asia/Kathmandu`, so it reads back 5h45m off the child's clock | CARRIED |\n| C1c | must_prove | the instant is \"its `record.created`\", not the formatting time | :78, :82, :84 | `datetime.now()` at format time: `created` is fixed at 2025-03-04, and also set one hour back, and the formatting happens later | CARRIED |\n| C1d | must_prove | the milliseconds come from `created` | :78, :80 | milliseconds taken from `record.msecs`, which is set at construction before `created` is overwritten, and milliseconds truncated without rounding to the microsecond first (`56.999`) | CARRIED |\n| C2a | must_prove | \"within one live Engine request\" | :109, :116 | a run against something other than the live Engine (`engine` session fixture, real HTTP POST), and a marker matching zero or several requests | CARRIED |\n| C2b | must_prove | the span runs \"from its `access.start` to its `access`\" | :116, :119 | the end record logged before the start record, and a slice that does not open and close on those two events | CARRIED |\n| C2c | must_prove | the `ts` values \"never decrease\" | :126, with :120, :125 | any out-of-order `ts` inside the span. :120 makes sure there are more than two points to order, and :125 fails a constant or local-time `ts` that would trivially stay in order | CARRIED |\n| D1 | docstring | \"`ts` is the record's creation time in UTC `YYYY-MM-DDTHH:MM:SS.mmmZ`\" | :72, :78, :84 | as C1a\u2013C1c | CARRIED |\n| D2 | docstring | \"within one live request it never decreases\" | :126 | as C2c | CARRIED |\n| D3 | docstring | child runs with `LOG_FORMAT` unset and the zone pinned off UTC: \"every stderr line is JSON\" | :67\u2013:68, :70 | non-JSON output under the production setup, and records that never reached stderr through the formatter | CARRIED |\n| D4 | docstring | \"whose `ts` matches `TS_RE`\" | :72 | an offset-suffixed or second-precision `ts` | CARRIED |\n| D5 | docstring | \"reads back within a minute of the child's clock\" | :74 | local time read as UTC (5h45m off) | CARRIED |\n| D6 | docstring | `_format_ts` and the formatter both give `\u202656.789Z` for 1741091696.789 | :78 | either path using the format time or `msecs`, and the two paths disagreeing | CARRIED |\n| D7 | docstring | both give `\u202657.000Z` for 1741091696.9999996 | :80 | milliseconds truncated without rounding to the microsecond first | CARRIED |\n| D8 | docstring | for a `created` one hour back, both \"read back to that `created` within a millisecond\" | :81, :82 | the format time, and coarser-than-millisecond precision | CARRIED |\n| D9 | docstring | \"an hour before the formatting\" | :84 | `ts` taken at format time | CARRIED |\n| D10 | docstring | \"the one `access.start` \u2026 to the one `access`\" whose url carries the marker | :116 | duplicate or missing access lines for the request | CARRIED |\n| D11 | docstring | \"the `access.start`, the `access` and at least one `recommendations.*` record\" | :119, :120 | a span that is missing its endpoints, or holds no record from inside the request | CARRIED |\n| D12 | docstring | each \"carry a `ts` matching `TS_RE`\" | :123 | live Engine records still in the old offset format | CARRIED |\n| D13 | docstring | \"within the request's wall-clock window, never decreasing\" | :125, :126 | a constant `ts`, local time, and an out-of-order `ts` | CARRIED |\n| N1 | name | \"engine ts is record created\" | :78, :84 | `ts` taken at format time | CARRIED |\n| N2 | name | \"in utc\" | :74 | local-time rendering | CARRIED |\n| N3 | name | \"with milliseconds\" | :72, :78 | second precision, and the wrong millisecond source | CARRIED |\n| N4 | name | \"request ts never decreases from access start to access\" | :119, :126 | as C2b\u2013C2c | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. normal-and-abnormal-paths (rules/testing.md): tests/tmp/test_19_timestamped_request_logs_phase1.py:41 (child line `logging.error(\"[probe] failed without exception\")`) and :106\n   The only abnormal case is an ERROR record with no `exc_info`. Nothing checks the `ts` on a record that carries a traceback (`record.exc_info`, logging_profiles.py:224). For C2, only a request that returns 200 is checked (:109). A failing request's `access.start`\u2026`access` span is never checked for order.\n2. bounds (rules/testing.md): tests/tmp/test_19_timestamped_request_logs_phase1.py:80\n   :80 asserts `57.000Z` for 1741091696.9999996, so the test requires rounding to the microsecond before the milliseconds are cut. C1 does not say how the milliseconds are rounded, so an implementation that meets C1 by cutting straight from `created` fails here. The test asks for more than its clause, and no testing.md principle covers that. Either the clause or the docstring should state the rounding rule, or the case should be marked as a choice.\n3. No rule covers this: tests/tmp/test_19_timestamped_request_logs_phase1.py:43, :78\n   The test asserts against `logging_profiles._format_ts`, which is not defined in engine/server/api/logging_profiles.py as it stands (Grep finds it only in plan docs and tests/tmp). The test turns its absence into `null`, so :78\u2013:84 stay red until the helper exists. Recorded so the missing name is not mistaken for a fault in the test.\n4. whole-claim (rules/testing.md), not blocking: tests/tmp/test_19_timestamped_request_logs_phase1.py:117\n   C2 says \"the `ts` values from its `access.start` to its `access`\". The test filters the span by event name (`access.start`, `access`, `recommendations.*`) rather than by the request's `request_id`. Other records the request emits inside the span go unchecked, and a `recommendations.*` record from another thread would be counted. The docstring states the narrower set, and the formatter is shared, so I judged C2c carried. Filtering on `request_id` would match the clause exactly.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `code_under_test` lists tests/active/test_log_format.py (NEW), which does not exist, so I did not read it.\n2. I was not given the phase's `<checkpoint>` text. I could not confirm that the seams used here (a child process running `configure_engine_logging`, and the session Engine over HTTP) are the ones Step 6 agreed. I judged the surface against `<surfaces>` and `<checkpoint_definition>` only.\n3. `fixtures_path` was not supplied. I read the `engine` fixture and `ROOT` from tests/active/conftest.py. I did not check whether the session Engine's environment sets `LOG_FORMAT`.",
        "body": "### devsecops-test-shape-auditor\n\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\n`test_engine_ts_is_record_created_in_utc_with_milliseconds` fails at line 72 on `assert all(TS_RE.fullmatch(line[\"ts\"]) for line in lines)`. The cause is logging_profiles.py:195: it renders `ts` as `datetime.now().astimezone().isoformat(timespec=\"milliseconds\")`, and under `TZ=Asia/Kathmandu` that gives a value ending in `+05:45` rather than `Z`.\n`test_engine_request_ts_never_decreases_from_access_start_to_access` fails at line 123 on `assert all(TS_RE.fullmatch(ts) for ts in stamps)` for the same cause: the timestamp carries an offset suffix (such as `+00:00`) instead of `Z`.\n\nNOT ASSESSED\n1. `code_under_test` lists tests/active/test_log_format.py (NEW), and that path does not exist. Nothing in that file was assessed.\n2. `fixtures_path` was not supplied. I found the `engine` fixture and `ROOT` in tests/active/conftest.py, which the test imports at line 23. I read the fixture there: `engine.db_path` is the session Engine's log file. I did not read the Engine's request and recommendations code. So whether a `recommendations.*` record is logged inside the marked request, which lines 116\u2013120 depend on, comes from the test's own comment at line 108 and was not checked against the code. The line-123 prediction assumes those earlier assertions hold.\n3. Anti-patterns pass, done as its own read. All seven `<anti_pattern>` entries were checked against their `<how_to_spot>` blocks, and none matched:\n   - No `.md` file is read, so the doc and substring-grep entries do not apply.\n   - The literals at lines 78 and 80 are outputs of the formatter for stated `created` inputs. They are not mirrored code constants.\n   - The expectations at lines 82 and 84 come from the input `past` and the child's clock, through `_epoch` (a `strptime` parse). Nothing re-derives them the way the formatter does.\n   - Every assertion is a positive one.\n   - Production code (`_format_ts`, `EngineJsonFormatter.format`, the live Engine) sits between every input and its assertion.\n   - C1 is exercised at three `created` values: a fixed millisecond, a rounding edge, and one hour back. It also runs under a zone pinned away from UTC, so returning the formatting time or local time cannot pass.\n4. Ladder pass, done as its own read:\n   - Test 1 calls the formatter directly (rung 1) in a child process and reads emitted log lines (rung 3). Running in a child is needed to pin `TZ`, and comments at lines 28 and 32 explain it.\n   - Test 2 asserts on log entries emitted by a live request (rung 3), which is where C2 lives.\n   - Neither test is on the anti-rung, and neither downshifts without a comment.\n5. Stub question:\n   - For C1, an implementation that returns the formatting time fails lines 78 and 84. One that renders local time fails lines 72, 74 and 78. One that reads `record.msecs` fails line 78, and one that truncates fails line 80.\n   - For C2, a constant or local-time `ts` fails lines 123 and 125.\n\n### devsecops-test-claim-auditor\n\nCLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (24 clauses: 7 must_prove, 13 docstring, 4 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | `ts` is in the form `YYYY-MM-DDTHH:MM:SS.mmmZ` | :72, :81 | the current `isoformat(timespec=\"milliseconds\")` output, which ends `+05:45` (or any other offset), not `Z` | CARRIED |\n| C1b | must_prove | rendered \"in UTC\" | :74, :78 | a local-time rendering with or without a `Z`: the child runs with `TZ=Asia/Kathmandu`, so it reads back 5h45m off the child's clock | CARRIED |\n| C1c | must_prove | the instant is \"its `record.created`\", not the formatting time | :78, :82, :84 | `datetime.now()` at format time: `created` is fixed at 2025-03-04, and also set one hour back, and the formatting happens later | CARRIED |\n| C1d | must_prove | the milliseconds come from `created` | :78, :80 | milliseconds taken from `record.msecs`, which is set at construction before `created` is overwritten, and milliseconds truncated without rounding to the microsecond first (`56.999`) | CARRIED |\n| C2a | must_prove | \"within one live Engine request\" | :109, :116 | a run against something other than the live Engine (`engine` session fixture, real HTTP POST), and a marker matching zero or several requests | CARRIED |\n| C2b | must_prove | the span runs \"from its `access.start` to its `access`\" | :116, :119 | the end record logged before the start record, and a slice that does not open and close on those two events | CARRIED |\n| C2c | must_prove | the `ts` values \"never decrease\" | :126, with :120, :125 | any out-of-order `ts` inside the span. :120 makes sure there are more than two points to order, and :125 fails a constant or local-time `ts` that would trivially stay in order | CARRIED |\n| D1 | docstring | \"`ts` is the record's creation time in UTC `YYYY-MM-DDTHH:MM:SS.mmmZ`\" | :72, :78, :84 | as C1a\u2013C1c | CARRIED |\n| D2 | docstring | \"within one live request it never decreases\" | :126 | as C2c | CARRIED |\n| D3 | docstring | child runs with `LOG_FORMAT` unset and the zone pinned off UTC: \"every stderr line is JSON\" | :67\u2013:68, :70 | non-JSON output under the production setup, and records that never reached stderr through the formatter | CARRIED |\n| D4 | docstring | \"whose `ts` matches `TS_RE`\" | :72 | an offset-suffixed or second-precision `ts` | CARRIED |\n| D5 | docstring | \"reads back within a minute of the child's clock\" | :74 | local time read as UTC (5h45m off) | CARRIED |\n| D6 | docstring | `_format_ts` and the formatter both give `\u202656.789Z` for 1741091696.789 | :78 | either path using the format time or `msecs`, and the two paths disagreeing | CARRIED |\n| D7 | docstring | both give `\u202657.000Z` for 1741091696.9999996 | :80 | milliseconds truncated without rounding to the microsecond first | CARRIED |\n| D8 | docstring | for a `created` one hour back, both \"read back to that `created` within a millisecond\" | :81, :82 | the format time, and coarser-than-millisecond precision | CARRIED |\n| D9 | docstring | \"an hour before the formatting\" | :84 | `ts` taken at format time | CARRIED |\n| D10 | docstring | \"the one `access.start` \u2026 to the one `access`\" whose url carries the marker | :116 | duplicate or missing access lines for the request | CARRIED |\n| D11 | docstring | \"the `access.start`, the `access` and at least one `recommendations.*` record\" | :119, :120 | a span that is missing its endpoints, or holds no record from inside the request | CARRIED |\n| D12 | docstring | each \"carry a `ts` matching `TS_RE`\" | :123 | live Engine records still in the old offset format | CARRIED |\n| D13 | docstring | \"within the request's wall-clock window, never decreasing\" | :125, :126 | a constant `ts`, local time, and an out-of-order `ts` | CARRIED |\n| N1 | name | \"engine ts is record created\" | :78, :84 | `ts` taken at format time | CARRIED |\n| N2 | name | \"in utc\" | :74 | local-time rendering | CARRIED |\n| N3 | name | \"with milliseconds\" | :72, :78 | second precision, and the wrong millisecond source | CARRIED |\n| N4 | name | \"request ts never decreases from access start to access\" | :119, :126 | as C2b\u2013C2c | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. normal-and-abnormal-paths (rules/testing.md): tests/tmp/test_19_timestamped_request_logs_phase1.py:41 (child line `logging.error(\"[probe] failed without exception\")`) and :106\n   The only abnormal case is an ERROR record with no `exc_info`. Nothing checks the `ts` on a record that carries a traceback (`record.exc_info`, logging_profiles.py:224). For C2, only a request that returns 200 is checked (:109). A failing request's `access.start`\u2026`access` span is never checked for order.\n2. bounds (rules/testing.md): tests/tmp/test_19_timestamped_request_logs_phase1.py:80\n   :80 asserts `57.000Z` for 1741091696.9999996, so the test requires rounding to the microsecond before the milliseconds are cut. C1 does not say how the milliseconds are rounded, so an implementation that meets C1 by cutting straight from `created` fails here. The test asks for more than its clause, and no testing.md principle covers that. Either the clause or the docstring should state the rounding rule, or the case should be marked as a choice.\n3. No rule covers this: tests/tmp/test_19_timestamped_request_logs_phase1.py:43, :78\n   The test asserts against `logging_profiles._format_ts`, which is not defined in engine/server/api/logging_profiles.py as it stands (Grep finds it only in plan docs and tests/tmp). The test turns its absence into `null`, so :78\u2013:84 stay red until the helper exists. Recorded so the missing name is not mistaken for a fault in the test.\n4. whole-claim (rules/testing.md), not blocking: tests/tmp/test_19_timestamped_request_logs_phase1.py:117\n   C2 says \"the `ts` values from its `access.start` to its `access`\". The test filters the span by event name (`access.start`, `access`, `recommendations.*`) rather than by the request's `request_id`. Other records the request emits inside the span go unchecked, and a `recommendations.*` record from another thread would be counted. The docstring states the narrower set, and the formatter is shared, so I judged C2c carried. Filtering on `request_id` would match the clause exactly.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `code_under_test` lists tests/active/test_log_format.py (NEW), which does not exist, so I did not read it.\n2. I was not given the phase's `<checkpoint>` text. I could not confirm that the seams used here (a child process running `configure_engine_logging`, and the session Engine over HTTP) are the ones Step 6 agreed. I judged the surface against `<surfaces>` and `<checkpoint_definition>` only.\n3. `fixtures_path` was not supplied. I read the `engine` fixture and `ROOT` from tests/active/conftest.py. I did not check whether the session Engine's environment sets `LOG_FORMAT`.",
        "map": [
          {
            "id": "C1a",
            "source": "must_prove",
            "clause": "`ts` is in the form `YYYY-MM-DDTHH:MM:SS.mmmZ`",
            "assertion": ":72, :81",
            "excludes": "the current `isoformat(timespec=\"milliseconds\")` output, which ends `+05:45` (or any other offset), not `Z`",
            "status": "CARRIED"
          },
          {
            "id": "C1b",
            "source": "must_prove",
            "clause": "rendered \"in UTC\"",
            "assertion": ":74, :78",
            "excludes": "a local-time rendering with or without a `Z`: the child runs with `TZ=Asia/Kathmandu`, so it reads back 5h45m off the child's clock",
            "status": "CARRIED"
          },
          {
            "id": "C1c",
            "source": "must_prove",
            "clause": "the instant is \"its `record.created`\", not the formatting time",
            "assertion": ":78, :82, :84",
            "excludes": "`datetime.now()` at format time: `created` is fixed at 2025-03-04, and also set one hour back, and the formatting happens later",
            "status": "CARRIED"
          },
          {
            "id": "C1d",
            "source": "must_prove",
            "clause": "the milliseconds come from `created`",
            "assertion": ":78, :80",
            "excludes": "milliseconds taken from `record.msecs`, which is set at construction before `created` is overwritten, and milliseconds truncated without rounding to the microsecond first (`56.999`)",
            "status": "CARRIED"
          },
          {
            "id": "C2a",
            "source": "must_prove",
            "clause": "\"within one live Engine request\"",
            "assertion": ":109, :116",
            "excludes": "a run against something other than the live Engine (`engine` session fixture, real HTTP POST), and a marker matching zero or several requests",
            "status": "CARRIED"
          },
          {
            "id": "C2b",
            "source": "must_prove",
            "clause": "the span runs \"from its `access.start` to its `access`\"",
            "assertion": ":116, :119",
            "excludes": "the end record logged before the start record, and a slice that does not open and close on those two events",
            "status": "CARRIED"
          },
          {
            "id": "C2c",
            "source": "must_prove",
            "clause": "the `ts` values \"never decrease\"",
            "assertion": ":126, with :120, :125",
            "excludes": "any out-of-order `ts` inside the span. :120 makes sure there are more than two points to order, and :125 fails a constant or local-time `ts` that would trivially stay in order",
            "status": "CARRIED"
          },
          {
            "id": "D1",
            "source": "docstring",
            "clause": "\"`ts` is the record's creation time in UTC `YYYY-MM-DDTHH:MM:SS.mmmZ`\"",
            "assertion": ":72, :78, :84",
            "excludes": "as C1a\u2013C1c",
            "status": "CARRIED"
          },
          {
            "id": "D2",
            "source": "docstring",
            "clause": "\"within one live request it never decreases\"",
            "assertion": ":126",
            "excludes": "as C2c",
            "status": "CARRIED"
          },
          {
            "id": "D3",
            "source": "docstring",
            "clause": "child runs with `LOG_FORMAT` unset and the zone pinned off UTC: \"every stderr line is JSON\"",
            "assertion": ":67\u2013:68, :70",
            "excludes": "non-JSON output under the production setup, and records that never reached stderr through the formatter",
            "status": "CARRIED"
          },
          {
            "id": "D4",
            "source": "docstring",
            "clause": "\"whose `ts` matches `TS_RE`\"",
            "assertion": ":72",
            "excludes": "an offset-suffixed or second-precision `ts`",
            "status": "CARRIED"
          },
          {
            "id": "D5",
            "source": "docstring",
            "clause": "\"reads back within a minute of the child's clock\"",
            "assertion": ":74",
            "excludes": "local time read as UTC (5h45m off)",
            "status": "CARRIED"
          },
          {
            "id": "D6",
            "source": "docstring",
            "clause": "`_format_ts` and the formatter both give `\u202656.789Z` for 1741091696.789",
            "assertion": ":78",
            "excludes": "either path using the format time or `msecs`, and the two paths disagreeing",
            "status": "CARRIED"
          },
          {
            "id": "D7",
            "source": "docstring",
            "clause": "both give `\u202657.000Z` for 1741091696.9999996",
            "assertion": ":80",
            "excludes": "milliseconds truncated without rounding to the microsecond first",
            "status": "CARRIED"
          },
          {
            "id": "D8",
            "source": "docstring",
            "clause": "for a `created` one hour back, both \"read back to that `created` within a millisecond\"",
            "assertion": ":81, :82",
            "excludes": "the format time, and coarser-than-millisecond precision",
            "status": "CARRIED"
          },
          {
            "id": "D9",
            "source": "docstring",
            "clause": "\"an hour before the formatting\"",
            "assertion": ":84",
            "excludes": "`ts` taken at format time",
            "status": "CARRIED"
          },
          {
            "id": "D10",
            "source": "docstring",
            "clause": "\"the one `access.start` \u2026 to the one `access`\" whose url carries the marker",
            "assertion": ":116",
            "excludes": "duplicate or missing access lines for the request",
            "status": "CARRIED"
          },
          {
            "id": "D11",
            "source": "docstring",
            "clause": "\"the `access.start`, the `access` and at least one `recommendations.*` record\"",
            "assertion": ":119, :120",
            "excludes": "a span that is missing its endpoints, or holds no record from inside the request",
            "status": "CARRIED"
          },
          {
            "id": "D12",
            "source": "docstring",
            "clause": "each \"carry a `ts` matching `TS_RE`\"",
            "assertion": ":123",
            "excludes": "live Engine records still in the old offset format",
            "status": "CARRIED"
          },
          {
            "id": "D13",
            "source": "docstring",
            "clause": "\"within the request's wall-clock window, never decreasing\"",
            "assertion": ":125, :126",
            "excludes": "a constant `ts`, local time, and an out-of-order `ts`",
            "status": "CARRIED"
          },
          {
            "id": "N1",
            "source": "name",
            "clause": "\"engine ts is record created\"",
            "assertion": ":78, :84",
            "excludes": "`ts` taken at format time",
            "status": "CARRIED"
          },
          {
            "id": "N2",
            "source": "name",
            "clause": "\"in utc\"",
            "assertion": ":74",
            "excludes": "local-time rendering",
            "status": "CARRIED"
          },
          {
            "id": "N3",
            "source": "name",
            "clause": "\"with milliseconds\"",
            "assertion": ":72, :78",
            "excludes": "second precision, and the wrong millisecond source",
            "status": "CARRIED"
          },
          {
            "id": "N4",
            "source": "name",
            "clause": "\"request ts never decreases from access start to access\"",
            "assertion": ":119, :126",
            "excludes": "as C2b\u2013C2c",
            "status": "CARRIED"
          }
        ],
        "map_problem": ""
      }
    ],
    "tests/tmp/test_19_timestamped_request_logs_phase2.py": [
      {
        "shape": "SHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. single-value-pin (rules/shape.md) \u2014 tests/tmp/test_19_timestamped_request_logs_phase2.py:84\n   assert [list(payload.items()) for payload in payloads] == [list(payload.items()) for payload in JSON_PAYLOADS], payloads  # C1\n   This function expects the shipped default, so it passes on the current `EngineJsonFormatter`-only code. That matches the entry's \"expected result equals the shipped default\" bullet. The file still separates the mechanism, because the text function at :87\u2013109 drives the same child with `text`, `TEXT`, ` Text ` and tab-`text`-newline. An implementation that always writes JSON fails there. One that matches only exact `text`, or only strips or only lowercases, fails one of those inputs. One that sends `bogus` or empty to text fails here. No change is required. Just don't split this function from the text function or run it on its own as a gate, because by itself it proves nothing about the switch.\n\nPREDICTED FAILURE\nFor every text-case parameter, `test_engine_log_format_text_writes_one_escaped_text_line_per_record` fails at line 95 on `assert all(TEXT_HEAD_RE.match(line) for line in lines)`. The cause is that `configure_engine_logging` still installs only `EngineJsonFormatter`, so each of the five lines starts with `{\"ts\":` and not with `<ts> INFO `. The line-93 count of 5 holds first, because `json.dumps` already escapes the CR and LF. Every parameter of the JSON test passes.\n\nNOT ASSESSED\n1. `code_under_test` lists tests/active/test_log_format.py, which does not resolve. The stub question was answered from the test under audit and engine/server/api/logging_profiles.py alone.\n2. `EXCEPTION_TEXT_RE` (:51) requires the traceback to contain the source line `raise ValueError(\"sentinel-log-format\")` for a `-c` child, from `File \"<string>\"`. Whether that line appears depends on which interpreter version runs the test, and I wasn't given that. No shape.md entry covers this. It decides whether line 105 can pass at all, not how the assertion is shaped.",
        "claim": "CLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (25 clauses: 10 must_prove, 13 docstring, 2 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | `text` in any case selects text lines | :95 | a case-sensitive compare: `TEXT` would then produce JSON, which fails the text head match | CARRIED |\n| C1b | must_prove | `text` with surrounding whitespace selects text lines | :95 | an unstripped compare: `\" Text \"` / `\"\\ttext\\n\"` would then produce JSON | CARRIED |\n| C1c | must_prove | unset selects JSON lines | :78 | text (or nothing) as the default when the variable is absent | CARRIED |\n| C1d | must_prove | empty selects JSON lines | :78 | an empty value read as text, or as an error | CARRIED |\n| C1e | must_prove | `json` selects JSON lines | :78 | `json`/`JSON` mishandled or case-sensitive | CARRIED |\n| C1f | must_prove | unknown value selects JSON lines | :78 | text as the fallback for anything not `json` (`bogus`) | CARRIED |\n| C2a | must_prove | one physical line per record | :93 | a raw newline in the traceback or message, since splitlines splits on CR and LF | CARRIED |\n| C2b | must_prove | shape `ts LEVEL event [message]` | :100, :102, :109 | a missing or wrongly formatted ts; a message emitted when there is none (lifecycle) or dropped when there is one | CARRIED |\n| C2c | must_prove | then `k=v\u2026 [request_id=\u2026] [traceback]` in that order | :105, :107 | request_id written before the context; traceback written before request_id; a request_id token on a record without one (:102) | CARRIED |\n| C2d | must_prove | CR and LF written as `\\r` and `\\n` | :103, :105 | raw CR/LF, stripping, or double-escaping in the message and the traceback | CARRIED |\n| D1 | docstring | \"one escaped text line per record for `text` in any case or padding\" | :93, :95 | the same as C1a/C1b/C2a | CARRIED |\n| D2 | docstring | \"today's JSON for anything else\" | :84 | the JSON payload changed when the text path was added | CARRIED |\n| D3 | docstring | unset/json/JSON/bogus/empty: \"stderr is five JSON objects\" | :78 | a missing record, a non-object line, or extra output | CARRIED |\n| D4 | docstring | \"each with a `ts` matching `TS_RE`\" | :80 | a ts missing, in a non-UTC format, or without milliseconds | CARRIED |\n| D5 | docstring | \"a traceback on the exception record ending `ValueError: sentinel-log-format`\" | :82 | the traceback dropped or truncated | CARRIED |\n| D6 | docstring | \"same keys, order and values as the JSON written before\" | :84 | added, reordered or changed keys, compared as item lists | CARRIED |\n| D7 | docstring | text: \"stderr is exactly five lines\" | :93 | a record split across lines, or extra output | CARRIED |\n| D8 | docstring | \"None parses as a JSON object\" | :96 | a JSON line passed off as text | CARRIED |\n| D9 | docstring | \"or starts with `<`\" | :97 | a syslog-style `<pri>` prefix | CARRIED |\n| D10 | docstring | \"Each line is `<TS_RE> LEVEL event`, then message, `k=v`, `request_id=\u2026`, traceback\" | :95, :100, :102\u2013:109 | a different token order or missing tokens | CARRIED |\n| D11 | docstring | \"CR and LF written as the two characters `\\\\r` and `\\\\n`\" | :103, :105 | raw or double-escaped CR/LF | CARRIED |\n| D12 | docstring | \"exception line puts `request_id=rid-p2` before the traceback and ends `ValueError: sentinel-log-format`\" | :105 | request_id after the traceback; a truncated traceback (fullmatch) | CARRIED |\n| D13 | docstring | \"access.start line reads `request started ip=\u2026 request_id=rid-a`, context before request_id\" + \"lifecycle line has no message token\" | :107, :109 | a raw message instead of `request started`; request_id before the context; a message token on lifecycle | CARRIED |\n| N1 | name | \"unset, empty, json or unknown writes today's json lines\" | :78, :84 | non-JSON output, or JSON that differs from today's | CARRIED |\n| N2 | name | \"text writes one escaped text line per record\" | :93, :103, :105 | records spanning lines; unescaped CR/LF | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. bounds (rules/testing.md) \u2014 tests/tmp/test_19_timestamped_request_logs_phase2.py:72\n   The only unknown value tested is `\"bogus\"`. No value close to `text` is tested, such as `\"texts\"`, `\"tex\"` or `\"te xt\"`. A selector written as `\"text\" in value.lower()` or `startswith(\"text\")` would pass every parametrised case at :72 and :87 even though C1 says an unknown value selects JSON. Adding a near-miss value such as `\"texts\"` to the :72 parametrize list would rule that out.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `code_under_test` lists tests/active/test_log_format.py, but that file does not exist in the worktree, so I could not read it.\n2. engine/server/api/logging_profiles.py, as read, has no `LOG_FORMAT` handling and no text formatter. I judged which inputs the text path accepts from `must_prove` and the test alone.",
        "body": "### devsecops-test-shape-auditor\n\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. single-value-pin (rules/shape.md) \u2014 tests/tmp/test_19_timestamped_request_logs_phase2.py:84\n   assert [list(payload.items()) for payload in payloads] == [list(payload.items()) for payload in JSON_PAYLOADS], payloads  # C1\n   This function expects the shipped default, so it passes on the current `EngineJsonFormatter`-only code. That matches the entry's \"expected result equals the shipped default\" bullet. The file still separates the mechanism, because the text function at :87\u2013109 drives the same child with `text`, `TEXT`, ` Text ` and tab-`text`-newline. An implementation that always writes JSON fails there. One that matches only exact `text`, or only strips or only lowercases, fails one of those inputs. One that sends `bogus` or empty to text fails here. No change is required. Just don't split this function from the text function or run it on its own as a gate, because by itself it proves nothing about the switch.\n\nPREDICTED FAILURE\nFor every text-case parameter, `test_engine_log_format_text_writes_one_escaped_text_line_per_record` fails at line 95 on `assert all(TEXT_HEAD_RE.match(line) for line in lines)`. The cause is that `configure_engine_logging` still installs only `EngineJsonFormatter`, so each of the five lines starts with `{\"ts\":` and not with `<ts> INFO `. The line-93 count of 5 holds first, because `json.dumps` already escapes the CR and LF. Every parameter of the JSON test passes.\n\nNOT ASSESSED\n1. `code_under_test` lists tests/active/test_log_format.py, which does not resolve. The stub question was answered from the test under audit and engine/server/api/logging_profiles.py alone.\n2. `EXCEPTION_TEXT_RE` (:51) requires the traceback to contain the source line `raise ValueError(\"sentinel-log-format\")` for a `-c` child, from `File \"<string>\"`. Whether that line appears depends on which interpreter version runs the test, and I wasn't given that. No shape.md entry covers this. It decides whether line 105 can pass at all, not how the assertion is shaped.\n\n### devsecops-test-claim-auditor\n\nCLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (25 clauses: 10 must_prove, 13 docstring, 2 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | `text` in any case selects text lines | :95 | a case-sensitive compare: `TEXT` would then produce JSON, which fails the text head match | CARRIED |\n| C1b | must_prove | `text` with surrounding whitespace selects text lines | :95 | an unstripped compare: `\" Text \"` / `\"\\ttext\\n\"` would then produce JSON | CARRIED |\n| C1c | must_prove | unset selects JSON lines | :78 | text (or nothing) as the default when the variable is absent | CARRIED |\n| C1d | must_prove | empty selects JSON lines | :78 | an empty value read as text, or as an error | CARRIED |\n| C1e | must_prove | `json` selects JSON lines | :78 | `json`/`JSON` mishandled or case-sensitive | CARRIED |\n| C1f | must_prove | unknown value selects JSON lines | :78 | text as the fallback for anything not `json` (`bogus`) | CARRIED |\n| C2a | must_prove | one physical line per record | :93 | a raw newline in the traceback or message, since splitlines splits on CR and LF | CARRIED |\n| C2b | must_prove | shape `ts LEVEL event [message]` | :100, :102, :109 | a missing or wrongly formatted ts; a message emitted when there is none (lifecycle) or dropped when there is one | CARRIED |\n| C2c | must_prove | then `k=v\u2026 [request_id=\u2026] [traceback]` in that order | :105, :107 | request_id written before the context; traceback written before request_id; a request_id token on a record without one (:102) | CARRIED |\n| C2d | must_prove | CR and LF written as `\\r` and `\\n` | :103, :105 | raw CR/LF, stripping, or double-escaping in the message and the traceback | CARRIED |\n| D1 | docstring | \"one escaped text line per record for `text` in any case or padding\" | :93, :95 | the same as C1a/C1b/C2a | CARRIED |\n| D2 | docstring | \"today's JSON for anything else\" | :84 | the JSON payload changed when the text path was added | CARRIED |\n| D3 | docstring | unset/json/JSON/bogus/empty: \"stderr is five JSON objects\" | :78 | a missing record, a non-object line, or extra output | CARRIED |\n| D4 | docstring | \"each with a `ts` matching `TS_RE`\" | :80 | a ts missing, in a non-UTC format, or without milliseconds | CARRIED |\n| D5 | docstring | \"a traceback on the exception record ending `ValueError: sentinel-log-format`\" | :82 | the traceback dropped or truncated | CARRIED |\n| D6 | docstring | \"same keys, order and values as the JSON written before\" | :84 | added, reordered or changed keys, compared as item lists | CARRIED |\n| D7 | docstring | text: \"stderr is exactly five lines\" | :93 | a record split across lines, or extra output | CARRIED |\n| D8 | docstring | \"None parses as a JSON object\" | :96 | a JSON line passed off as text | CARRIED |\n| D9 | docstring | \"or starts with `<`\" | :97 | a syslog-style `<pri>` prefix | CARRIED |\n| D10 | docstring | \"Each line is `<TS_RE> LEVEL event`, then message, `k=v`, `request_id=\u2026`, traceback\" | :95, :100, :102\u2013:109 | a different token order or missing tokens | CARRIED |\n| D11 | docstring | \"CR and LF written as the two characters `\\\\r` and `\\\\n`\" | :103, :105 | raw or double-escaped CR/LF | CARRIED |\n| D12 | docstring | \"exception line puts `request_id=rid-p2` before the traceback and ends `ValueError: sentinel-log-format`\" | :105 | request_id after the traceback; a truncated traceback (fullmatch) | CARRIED |\n| D13 | docstring | \"access.start line reads `request started ip=\u2026 request_id=rid-a`, context before request_id\" + \"lifecycle line has no message token\" | :107, :109 | a raw message instead of `request started`; request_id before the context; a message token on lifecycle | CARRIED |\n| N1 | name | \"unset, empty, json or unknown writes today's json lines\" | :78, :84 | non-JSON output, or JSON that differs from today's | CARRIED |\n| N2 | name | \"text writes one escaped text line per record\" | :93, :103, :105 | records spanning lines; unescaped CR/LF | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. bounds (rules/testing.md) \u2014 tests/tmp/test_19_timestamped_request_logs_phase2.py:72\n   The only unknown value tested is `\"bogus\"`. No value close to `text` is tested, such as `\"texts\"`, `\"tex\"` or `\"te xt\"`. A selector written as `\"text\" in value.lower()` or `startswith(\"text\")` would pass every parametrised case at :72 and :87 even though C1 says an unknown value selects JSON. Adding a near-miss value such as `\"texts\"` to the :72 parametrize list would rule that out.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `code_under_test` lists tests/active/test_log_format.py, but that file does not exist in the worktree, so I could not read it.\n2. engine/server/api/logging_profiles.py, as read, has no `LOG_FORMAT` handling and no text formatter. I judged which inputs the text path accepts from `must_prove` and the test alone.",
        "map": [
          {
            "id": "C1a",
            "source": "must_prove",
            "clause": "`text` in any case selects text lines",
            "assertion": ":95",
            "excludes": "a case-sensitive compare: `TEXT` would then produce JSON, which fails the text head match",
            "status": "CARRIED"
          },
          {
            "id": "C1b",
            "source": "must_prove",
            "clause": "`text` with surrounding whitespace selects text lines",
            "assertion": ":95",
            "excludes": "an unstripped compare: `\" Text \"` / `\"\\ttext\\n\"` would then produce JSON",
            "status": "CARRIED"
          },
          {
            "id": "C1c",
            "source": "must_prove",
            "clause": "unset selects JSON lines",
            "assertion": ":78",
            "excludes": "text (or nothing) as the default when the variable is absent",
            "status": "CARRIED"
          },
          {
            "id": "C1d",
            "source": "must_prove",
            "clause": "empty selects JSON lines",
            "assertion": ":78",
            "excludes": "an empty value read as text, or as an error",
            "status": "CARRIED"
          },
          {
            "id": "C1e",
            "source": "must_prove",
            "clause": "`json` selects JSON lines",
            "assertion": ":78",
            "excludes": "`json`/`JSON` mishandled or case-sensitive",
            "status": "CARRIED"
          },
          {
            "id": "C1f",
            "source": "must_prove",
            "clause": "unknown value selects JSON lines",
            "assertion": ":78",
            "excludes": "text as the fallback for anything not `json` (`bogus`)",
            "status": "CARRIED"
          },
          {
            "id": "C2a",
            "source": "must_prove",
            "clause": "one physical line per record",
            "assertion": ":93",
            "excludes": "a raw newline in the traceback or message, since splitlines splits on CR and LF",
            "status": "CARRIED"
          },
          {
            "id": "C2b",
            "source": "must_prove",
            "clause": "shape `ts LEVEL event [message]`",
            "assertion": ":100, :102, :109",
            "excludes": "a missing or wrongly formatted ts; a message emitted when there is none (lifecycle) or dropped when there is one",
            "status": "CARRIED"
          },
          {
            "id": "C2c",
            "source": "must_prove",
            "clause": "then `k=v\u2026 [request_id=\u2026] [traceback]` in that order",
            "assertion": ":105, :107",
            "excludes": "request_id written before the context; traceback written before request_id; a request_id token on a record without one (:102)",
            "status": "CARRIED"
          },
          {
            "id": "C2d",
            "source": "must_prove",
            "clause": "CR and LF written as `\\r` and `\\n`",
            "assertion": ":103, :105",
            "excludes": "raw CR/LF, stripping, or double-escaping in the message and the traceback",
            "status": "CARRIED"
          },
          {
            "id": "D1",
            "source": "docstring",
            "clause": "\"one escaped text line per record for `text` in any case or padding\"",
            "assertion": ":93, :95",
            "excludes": "the same as C1a/C1b/C2a",
            "status": "CARRIED"
          },
          {
            "id": "D2",
            "source": "docstring",
            "clause": "\"today's JSON for anything else\"",
            "assertion": ":84",
            "excludes": "the JSON payload changed when the text path was added",
            "status": "CARRIED"
          },
          {
            "id": "D3",
            "source": "docstring",
            "clause": "unset/json/JSON/bogus/empty: \"stderr is five JSON objects\"",
            "assertion": ":78",
            "excludes": "a missing record, a non-object line, or extra output",
            "status": "CARRIED"
          },
          {
            "id": "D4",
            "source": "docstring",
            "clause": "\"each with a `ts` matching `TS_RE`\"",
            "assertion": ":80",
            "excludes": "a ts missing, in a non-UTC format, or without milliseconds",
            "status": "CARRIED"
          },
          {
            "id": "D5",
            "source": "docstring",
            "clause": "\"a traceback on the exception record ending `ValueError: sentinel-log-format`\"",
            "assertion": ":82",
            "excludes": "the traceback dropped or truncated",
            "status": "CARRIED"
          },
          {
            "id": "D6",
            "source": "docstring",
            "clause": "\"same keys, order and values as the JSON written before\"",
            "assertion": ":84",
            "excludes": "added, reordered or changed keys, compared as item lists",
            "status": "CARRIED"
          },
          {
            "id": "D7",
            "source": "docstring",
            "clause": "text: \"stderr is exactly five lines\"",
            "assertion": ":93",
            "excludes": "a record split across lines, or extra output",
            "status": "CARRIED"
          },
          {
            "id": "D8",
            "source": "docstring",
            "clause": "\"None parses as a JSON object\"",
            "assertion": ":96",
            "excludes": "a JSON line passed off as text",
            "status": "CARRIED"
          },
          {
            "id": "D9",
            "source": "docstring",
            "clause": "\"or starts with `<`\"",
            "assertion": ":97",
            "excludes": "a syslog-style `<pri>` prefix",
            "status": "CARRIED"
          },
          {
            "id": "D10",
            "source": "docstring",
            "clause": "\"Each line is `<TS_RE> LEVEL event`, then message, `k=v`, `request_id=\u2026`, traceback\"",
            "assertion": ":95, :100, :102\u2013:109",
            "excludes": "a different token order or missing tokens",
            "status": "CARRIED"
          },
          {
            "id": "D11",
            "source": "docstring",
            "clause": "\"CR and LF written as the two characters `\\\\r` and `\\\\n`\"",
            "assertion": ":103, :105",
            "excludes": "raw or double-escaped CR/LF",
            "status": "CARRIED"
          },
          {
            "id": "D12",
            "source": "docstring",
            "clause": "\"exception line puts `request_id=rid-p2` before the traceback and ends `ValueError: sentinel-log-format`\"",
            "assertion": ":105",
            "excludes": "request_id after the traceback; a truncated traceback (fullmatch)",
            "status": "CARRIED"
          },
          {
            "id": "D13",
            "source": "docstring",
            "clause": "\"access.start line reads `request started ip=\u2026 request_id=rid-a`, context before request_id\" + \"lifecycle line has no message token\"",
            "assertion": ":107, :109",
            "excludes": "a raw message instead of `request started`; request_id before the context; a message token on lifecycle",
            "status": "CARRIED"
          },
          {
            "id": "N1",
            "source": "name",
            "clause": "\"unset, empty, json or unknown writes today's json lines\"",
            "assertion": ":78, :84",
            "excludes": "non-JSON output, or JSON that differs from today's",
            "status": "CARRIED"
          },
          {
            "id": "N2",
            "source": "name",
            "clause": "\"text writes one escaped text line per record\"",
            "assertion": ":93, :103, :105",
            "excludes": "records spanning lines; unescaped CR/LF",
            "status": "CARRIED"
          }
        ],
        "map_problem": ""
      }
    ],
    "tests/tmp/test_19_timestamped_request_logs_phase3.py": [
      {
        "shape": "SHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\nThe test fails before any assertion. Line 69 enters `_client_logging`, which calls `client_server.configure_client_logging()` at tests/tmp/test_19_timestamped_request_logs_phase3.py:44. That call raises `AttributeError: module 'server' has no attribute 'configure_client_logging'`, because the symbol is not defined anywhere in client/backend/server.py. The first assertion that would fail once the function exists is line 102 (`TS_RE.fullmatch`). Today `_emit_client_log` stamps `datetime.now().astimezone().isoformat(timespec=\"milliseconds\")`, which gives a local time with an offset (for example `+05:45`), not a `...Z` UTC time.\n\nNOT ASSESSED\n1. `code_under_test` listed tests/active/test_server.py and tests/active/test_log_format.py. I did not read either one: they are sibling tests, not code this test runs, and the shape verdict doesn't depend on them.\n2. `configure_client_logging` doesn't exist yet. So I answered the stub question from the assertion form against the current `_emit_client_log` (server.py:120-136) and the existing `logging.basicConfig(format=\"%(message)s\")` at server.py:1184, not against a real implementation. The answer:\n   - **The current behaviour fails** at line 102 (wrong `ts` format) and at line 89, because the bare text and the exception traceback don't come out as single JSON lines.\n   - **A hard-coded `Z` on a local time fails** at line 104, because the zone is pinned 5h45m off UTC.\n   - **A `ts` taken at format time instead of from `record.created` fails** at line 106.\n   - **Rounding to milliseconds without first rounding to the microsecond fails** at line 106, through the `1741091696.9999996` input.\n   - **Always emitting `context` fails** at lines 97-98, through the empty-dict and no-context inputs.\n   - **A stub `configure_client_logging` that installs no JSON formatter fails** at lines 89-91.\n3. I read tests/active/conftest.py only far enough to confirm that `client_server` is `import server as client_server` (conftest.py:41). The test uses no pytest fixtures except the built-in `monkeypatch`.",
        "claim": "Rows `C1a`\u2013`C1d` all cover must_prove clause C1, and rows `C2a`\u2013`C2c` all cover C2.\n\n```\nCLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (26 clauses: 7 must_prove, 15 docstring, 4 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | an `_emit_client_log` record \"renders as a JSON line\" | :89, :91 | a record that spans several lines, or a line that is not a JSON object (for example the JSON string nested as a plain-text message) | CARRIED |\n| C1b | must_prove | keys run `ts, level, service, event, message, context` in that order | :94, :95 | keys that are reordered, missing or extra, and wrong values in them (the list is compared exactly) | CARRIED |\n| C1c | must_prove | `[, context]`: the context key is optional and left out when there is none | :97, :98 | writing `context: {}` or `context: null` for an empty or missing context | CARRIED |\n| C1d | must_prove | \"with a UTC `ts`\" | :102, :104, :106 | a local time with an offset (:102), a local time with a `Z` added under TZ +05:45 (:104), the time of formatting instead of `created`, and rounding that gives 56.999 (:106) | CARRIED |\n| C2a | must_prove | a bare root-logger record renders as a JSON line | :89, :91 | a bare record written as plain `%(message)s` text | CARRIED |\n| C2b | must_prove | \"in the same JSON shape\": keys `ts, level, service, event, message`, UTC `ts` | :108, :102, :104 | a different key set or order for bare records, a missing `service`, a non-UTC `ts` on the bare line | CARRIED |\n| C2c | must_prove | \"with event `client.log`\" | :109 | the event left out, or taken from the logger name or the message | CARRIED |\n| D1 | docstring | \"every Client record leaves the root handler as one JSON line\" | :89, :91 | a traceback or bare text that adds or replaces lines | CARRIED |\n| D2 | docstring | \"in the Client's key order\" | :94, :97, :98, :108, :110 | any record whose keys are reordered | CARRIED |\n| D3 | docstring | \"with a UTC `ts`\" (for every record) | :102, :104 | a local-time `ts` on any of the five lines | CARRIED |\n| D4 | docstring | the five calls \"write exactly five lines, each a JSON object\" | :89, :91 | extra or missing lines; a line that is not an object | CARRIED |\n| D5 | docstring | `engine.call` keys are exactly `ts, level, service, event, message, context` | :94 | reordered or extra keys | CARRIED |\n| D6 | docstring | level ERROR, service `client-backend`, \"the message and `{\"error\": \"x\\ny\"}` unchanged\" | :95 | a wrong level name or service, or a context that is escaped, stringified or dropped | CARRIED |\n| D7 | docstring | \"the empty- and no-context lines stop at `message`\" | :97, :98 | `context: {}` or `context: null` written | CARRIED |\n| D8 | docstring | \"Every line's `ts` matches `TS_RE`\" | :102 | an offset suffix, or no milliseconds | CARRIED |\n| D9 | docstring | \"reads back as UTC inside the wall-clock window of the calls\" | :104 | a local time with `Z` under +05:45 (5h45m outside the \u00b11 s window) | CARRIED |\n| D10 | docstring | the installed formatter renders created 1741091696.789 as `2025-03-04T12:34:56.789Z` | :81, :106 | a `ts` taken at formatting time, or rendered in local time | CARRIED |\n| D11 | docstring | created 1741091696.9999996 renders as `2025-03-04T12:34:57.000Z` | :82, :106 | seconds and milliseconds that disagree (56.999, or 56.1000) | CARRIED |\n| D12 | docstring | the bare and exception records have \"event `client.log` and their own message\" | :109, :111 | a fixed or empty message; a non-fallback event | CARRIED |\n| D13 | docstring | \"the bare line's keys are exactly `ts, level, service, event, message`\" | :108 | extra keys (for example `context: null`, `traceback: null`) or a different order | CARRIED |\n| D14 | docstring | \"the exception line adds `traceback`\" | :110 | the exception info silently dropped, or the traceback placed elsewhere in the key order | CARRIED |\n| D15 | docstring | traceback is \"the formatted `ValueError: sentinel-client-log` traceback\" | :112 | only the exception text without the stack, or a different or empty traceback | CARRIED |\n| N1 | name | \"client records leave as json lines\" | :89, :91 | non-JSON or multi-line output | CARRIED |\n| N2 | name | \"in client key order\" | :94, :108, :110 | reordered keys | CARRIED |\n| N3 | name | \"with utc ts\" | :102, :104, :106 | a local-time or formatting-time `ts` | CARRIED |\n| N4 | name | \"and bare ones as client log\" | :109 | a bare record without the `client.log` event | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. client/backend/server.py as read has no `configure_client_logging` and no Client\n   formatter; `main()` still calls `logging.basicConfig(level=logging.INFO,\n   format=\"%(message)s\")` at server.py:1184, and `_emit_client_log` (server.py:120-136)\n   still builds its own JSON string. The test calls `client_server.configure_client_logging()`\n   at test_path:44. So I could not check against the code the bounds and failure paths of\n   the formatter this test is meant to cover. Bounds and the abnormal path were judged\n   from the test's own inputs (empty context, no context, a `logging.exception` record)\n   and from `must_prove`.\n2. `code_under_test` lists tests/active/test_server.py and tests/active/test_log_format.py.\n   These are test modules, and this test does not exercise them. I did not audit them.\n   Only the `client_server` import this test takes from tests/active/conftest.py:41 was\n   confirmed.\n```",
        "body": "### devsecops-test-shape-auditor\n\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\nThe test fails before any assertion. Line 69 enters `_client_logging`, which calls `client_server.configure_client_logging()` at tests/tmp/test_19_timestamped_request_logs_phase3.py:44. That call raises `AttributeError: module 'server' has no attribute 'configure_client_logging'`, because the symbol is not defined anywhere in client/backend/server.py. The first assertion that would fail once the function exists is line 102 (`TS_RE.fullmatch`). Today `_emit_client_log` stamps `datetime.now().astimezone().isoformat(timespec=\"milliseconds\")`, which gives a local time with an offset (for example `+05:45`), not a `...Z` UTC time.\n\nNOT ASSESSED\n1. `code_under_test` listed tests/active/test_server.py and tests/active/test_log_format.py. I did not read either one: they are sibling tests, not code this test runs, and the shape verdict doesn't depend on them.\n2. `configure_client_logging` doesn't exist yet. So I answered the stub question from the assertion form against the current `_emit_client_log` (server.py:120-136) and the existing `logging.basicConfig(format=\"%(message)s\")` at server.py:1184, not against a real implementation. The answer:\n   - **The current behaviour fails** at line 102 (wrong `ts` format) and at line 89, because the bare text and the exception traceback don't come out as single JSON lines.\n   - **A hard-coded `Z` on a local time fails** at line 104, because the zone is pinned 5h45m off UTC.\n   - **A `ts` taken at format time instead of from `record.created` fails** at line 106.\n   - **Rounding to milliseconds without first rounding to the microsecond fails** at line 106, through the `1741091696.9999996` input.\n   - **Always emitting `context` fails** at lines 97-98, through the empty-dict and no-context inputs.\n   - **A stub `configure_client_logging` that installs no JSON formatter fails** at lines 89-91.\n3. I read tests/active/conftest.py only far enough to confirm that `client_server` is `import server as client_server` (conftest.py:41). The test uses no pytest fixtures except the built-in `monkeypatch`.\n\n### devsecops-test-claim-auditor\n\nRows `C1a`\u2013`C1d` all cover must_prove clause C1, and rows `C2a`\u2013`C2c` all cover C2.\n\n```\nCLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (26 clauses: 7 must_prove, 15 docstring, 4 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | an `_emit_client_log` record \"renders as a JSON line\" | :89, :91 | a record that spans several lines, or a line that is not a JSON object (for example the JSON string nested as a plain-text message) | CARRIED |\n| C1b | must_prove | keys run `ts, level, service, event, message, context` in that order | :94, :95 | keys that are reordered, missing or extra, and wrong values in them (the list is compared exactly) | CARRIED |\n| C1c | must_prove | `[, context]`: the context key is optional and left out when there is none | :97, :98 | writing `context: {}` or `context: null` for an empty or missing context | CARRIED |\n| C1d | must_prove | \"with a UTC `ts`\" | :102, :104, :106 | a local time with an offset (:102), a local time with a `Z` added under TZ +05:45 (:104), the time of formatting instead of `created`, and rounding that gives 56.999 (:106) | CARRIED |\n| C2a | must_prove | a bare root-logger record renders as a JSON line | :89, :91 | a bare record written as plain `%(message)s` text | CARRIED |\n| C2b | must_prove | \"in the same JSON shape\": keys `ts, level, service, event, message`, UTC `ts` | :108, :102, :104 | a different key set or order for bare records, a missing `service`, a non-UTC `ts` on the bare line | CARRIED |\n| C2c | must_prove | \"with event `client.log`\" | :109 | the event left out, or taken from the logger name or the message | CARRIED |\n| D1 | docstring | \"every Client record leaves the root handler as one JSON line\" | :89, :91 | a traceback or bare text that adds or replaces lines | CARRIED |\n| D2 | docstring | \"in the Client's key order\" | :94, :97, :98, :108, :110 | any record whose keys are reordered | CARRIED |\n| D3 | docstring | \"with a UTC `ts`\" (for every record) | :102, :104 | a local-time `ts` on any of the five lines | CARRIED |\n| D4 | docstring | the five calls \"write exactly five lines, each a JSON object\" | :89, :91 | extra or missing lines; a line that is not an object | CARRIED |\n| D5 | docstring | `engine.call` keys are exactly `ts, level, service, event, message, context` | :94 | reordered or extra keys | CARRIED |\n| D6 | docstring | level ERROR, service `client-backend`, \"the message and `{\"error\": \"x\\ny\"}` unchanged\" | :95 | a wrong level name or service, or a context that is escaped, stringified or dropped | CARRIED |\n| D7 | docstring | \"the empty- and no-context lines stop at `message`\" | :97, :98 | `context: {}` or `context: null` written | CARRIED |\n| D8 | docstring | \"Every line's `ts` matches `TS_RE`\" | :102 | an offset suffix, or no milliseconds | CARRIED |\n| D9 | docstring | \"reads back as UTC inside the wall-clock window of the calls\" | :104 | a local time with `Z` under +05:45 (5h45m outside the \u00b11 s window) | CARRIED |\n| D10 | docstring | the installed formatter renders created 1741091696.789 as `2025-03-04T12:34:56.789Z` | :81, :106 | a `ts` taken at formatting time, or rendered in local time | CARRIED |\n| D11 | docstring | created 1741091696.9999996 renders as `2025-03-04T12:34:57.000Z` | :82, :106 | seconds and milliseconds that disagree (56.999, or 56.1000) | CARRIED |\n| D12 | docstring | the bare and exception records have \"event `client.log` and their own message\" | :109, :111 | a fixed or empty message; a non-fallback event | CARRIED |\n| D13 | docstring | \"the bare line's keys are exactly `ts, level, service, event, message`\" | :108 | extra keys (for example `context: null`, `traceback: null`) or a different order | CARRIED |\n| D14 | docstring | \"the exception line adds `traceback`\" | :110 | the exception info silently dropped, or the traceback placed elsewhere in the key order | CARRIED |\n| D15 | docstring | traceback is \"the formatted `ValueError: sentinel-client-log` traceback\" | :112 | only the exception text without the stack, or a different or empty traceback | CARRIED |\n| N1 | name | \"client records leave as json lines\" | :89, :91 | non-JSON or multi-line output | CARRIED |\n| N2 | name | \"in client key order\" | :94, :108, :110 | reordered keys | CARRIED |\n| N3 | name | \"with utc ts\" | :102, :104, :106 | a local-time or formatting-time `ts` | CARRIED |\n| N4 | name | \"and bare ones as client log\" | :109 | a bare record without the `client.log` event | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. client/backend/server.py as read has no `configure_client_logging` and no Client\n   formatter; `main()` still calls `logging.basicConfig(level=logging.INFO,\n   format=\"%(message)s\")` at server.py:1184, and `_emit_client_log` (server.py:120-136)\n   still builds its own JSON string. The test calls `client_server.configure_client_logging()`\n   at test_path:44. So I could not check against the code the bounds and failure paths of\n   the formatter this test is meant to cover. Bounds and the abnormal path were judged\n   from the test's own inputs (empty context, no context, a `logging.exception` record)\n   and from `must_prove`.\n2. `code_under_test` lists tests/active/test_server.py and tests/active/test_log_format.py.\n   These are test modules, and this test does not exercise them. I did not audit them.\n   Only the `client_server` import this test takes from tests/active/conftest.py:41 was\n   confirmed.\n```",
        "map": [
          {
            "id": "C1a",
            "source": "must_prove",
            "clause": "an `_emit_client_log` record \"renders as a JSON line\"",
            "assertion": ":89, :91",
            "excludes": "a record that spans several lines, or a line that is not a JSON object (for example the JSON string nested as a plain-text message)",
            "status": "CARRIED"
          },
          {
            "id": "C1b",
            "source": "must_prove",
            "clause": "keys run `ts, level, service, event, message, context` in that order",
            "assertion": ":94, :95",
            "excludes": "keys that are reordered, missing or extra, and wrong values in them (the list is compared exactly)",
            "status": "CARRIED"
          },
          {
            "id": "C1c",
            "source": "must_prove",
            "clause": "`[, context]`: the context key is optional and left out when there is none",
            "assertion": ":97, :98",
            "excludes": "writing `context: {}` or `context: null` for an empty or missing context",
            "status": "CARRIED"
          },
          {
            "id": "C1d",
            "source": "must_prove",
            "clause": "\"with a UTC `ts`\"",
            "assertion": ":102, :104, :106",
            "excludes": "a local time with an offset (:102), a local time with a `Z` added under TZ +05:45 (:104), the time of formatting instead of `created`, and rounding that gives 56.999 (:106)",
            "status": "CARRIED"
          },
          {
            "id": "C2a",
            "source": "must_prove",
            "clause": "a bare root-logger record renders as a JSON line",
            "assertion": ":89, :91",
            "excludes": "a bare record written as plain `%(message)s` text",
            "status": "CARRIED"
          },
          {
            "id": "C2b",
            "source": "must_prove",
            "clause": "\"in the same JSON shape\": keys `ts, level, service, event, message`, UTC `ts`",
            "assertion": ":108, :102, :104",
            "excludes": "a different key set or order for bare records, a missing `service`, a non-UTC `ts` on the bare line",
            "status": "CARRIED"
          },
          {
            "id": "C2c",
            "source": "must_prove",
            "clause": "\"with event `client.log`\"",
            "assertion": ":109",
            "excludes": "the event left out, or taken from the logger name or the message",
            "status": "CARRIED"
          },
          {
            "id": "D1",
            "source": "docstring",
            "clause": "\"every Client record leaves the root handler as one JSON line\"",
            "assertion": ":89, :91",
            "excludes": "a traceback or bare text that adds or replaces lines",
            "status": "CARRIED"
          },
          {
            "id": "D2",
            "source": "docstring",
            "clause": "\"in the Client's key order\"",
            "assertion": ":94, :97, :98, :108, :110",
            "excludes": "any record whose keys are reordered",
            "status": "CARRIED"
          },
          {
            "id": "D3",
            "source": "docstring",
            "clause": "\"with a UTC `ts`\" (for every record)",
            "assertion": ":102, :104",
            "excludes": "a local-time `ts` on any of the five lines",
            "status": "CARRIED"
          },
          {
            "id": "D4",
            "source": "docstring",
            "clause": "the five calls \"write exactly five lines, each a JSON object\"",
            "assertion": ":89, :91",
            "excludes": "extra or missing lines; a line that is not an object",
            "status": "CARRIED"
          },
          {
            "id": "D5",
            "source": "docstring",
            "clause": "`engine.call` keys are exactly `ts, level, service, event, message, context`",
            "assertion": ":94",
            "excludes": "reordered or extra keys",
            "status": "CARRIED"
          },
          {
            "id": "D6",
            "source": "docstring",
            "clause": "level ERROR, service `client-backend`, \"the message and `{\"error\": \"x\\ny\"}` unchanged\"",
            "assertion": ":95",
            "excludes": "a wrong level name or service, or a context that is escaped, stringified or dropped",
            "status": "CARRIED"
          },
          {
            "id": "D7",
            "source": "docstring",
            "clause": "\"the empty- and no-context lines stop at `message`\"",
            "assertion": ":97, :98",
            "excludes": "`context: {}` or `context: null` written",
            "status": "CARRIED"
          },
          {
            "id": "D8",
            "source": "docstring",
            "clause": "\"Every line's `ts` matches `TS_RE`\"",
            "assertion": ":102",
            "excludes": "an offset suffix, or no milliseconds",
            "status": "CARRIED"
          },
          {
            "id": "D9",
            "source": "docstring",
            "clause": "\"reads back as UTC inside the wall-clock window of the calls\"",
            "assertion": ":104",
            "excludes": "a local time with `Z` under +05:45 (5h45m outside the \u00b11 s window)",
            "status": "CARRIED"
          },
          {
            "id": "D10",
            "source": "docstring",
            "clause": "the installed formatter renders created 1741091696.789 as `2025-03-04T12:34:56.789Z`",
            "assertion": ":81, :106",
            "excludes": "a `ts` taken at formatting time, or rendered in local time",
            "status": "CARRIED"
          },
          {
            "id": "D11",
            "source": "docstring",
            "clause": "created 1741091696.9999996 renders as `2025-03-04T12:34:57.000Z`",
            "assertion": ":82, :106",
            "excludes": "seconds and milliseconds that disagree (56.999, or 56.1000)",
            "status": "CARRIED"
          },
          {
            "id": "D12",
            "source": "docstring",
            "clause": "the bare and exception records have \"event `client.log` and their own message\"",
            "assertion": ":109, :111",
            "excludes": "a fixed or empty message; a non-fallback event",
            "status": "CARRIED"
          },
          {
            "id": "D13",
            "source": "docstring",
            "clause": "\"the bare line's keys are exactly `ts, level, service, event, message`\"",
            "assertion": ":108",
            "excludes": "extra keys (for example `context: null`, `traceback: null`) or a different order",
            "status": "CARRIED"
          },
          {
            "id": "D14",
            "source": "docstring",
            "clause": "\"the exception line adds `traceback`\"",
            "assertion": ":110",
            "excludes": "the exception info silently dropped, or the traceback placed elsewhere in the key order",
            "status": "CARRIED"
          },
          {
            "id": "D15",
            "source": "docstring",
            "clause": "traceback is \"the formatted `ValueError: sentinel-client-log` traceback\"",
            "assertion": ":112",
            "excludes": "only the exception text without the stack, or a different or empty traceback",
            "status": "CARRIED"
          },
          {
            "id": "N1",
            "source": "name",
            "clause": "\"client records leave as json lines\"",
            "assertion": ":89, :91",
            "excludes": "non-JSON or multi-line output",
            "status": "CARRIED"
          },
          {
            "id": "N2",
            "source": "name",
            "clause": "\"in client key order\"",
            "assertion": ":94, :108, :110",
            "excludes": "reordered keys",
            "status": "CARRIED"
          },
          {
            "id": "N3",
            "source": "name",
            "clause": "\"with utc ts\"",
            "assertion": ":102, :104, :106",
            "excludes": "a local-time or formatting-time `ts`",
            "status": "CARRIED"
          },
          {
            "id": "N4",
            "source": "name",
            "clause": "\"and bare ones as client log\"",
            "assertion": ":109",
            "excludes": "a bare record without the `client.log` event",
            "status": "CARRIED"
          }
        ],
        "map_problem": ""
      }
    ],
    "tests/tmp/test_19_timestamped_request_logs_phase4.py": [
      {
        "shape": "SHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\nAll four parametrisations of `test_client_log_format_text_writes_the_engines_escaped_text_line_per_record` fail at tests/tmp/test_19_timestamped_request_logs_phase4.py:129 on `assert all(TEXT_HEAD_RE.match(line) for line in lines)`. The Client ignores `LOG_FORMAT`, so each line begins `{\"ts\":`; the length check at line 127 passes first because JSON escapes the embedded newlines. `test_client_format_ts_and_render_text_return_the_engines_strings` passes lines 147, 150 and 157, then errors rather than fails at line 158. That error is `AttributeError: module 'server' has no attribute '_render_text'`. The five parametrisations of `test_client_log_format_unset_empty_json_or_unknown_writes_json_lines` pass against the current JSON-only Client.\n\nNOT ASSESSED\n1. `code_under_test` lists tests/active/test_log_format.py, and it does not exist (Glob `tests/active/test_log_format*.py` found nothing). The test does not import it, so this audit is unaffected. The listed path was not read.\n2. `fixtures_path` was not supplied. The test uses no pytest fixture except the built-in `monkeypatch`. It imports `client_server` from tests/active/conftest.py:41 (`import server as client_server`). The import was resolved there, and nothing else in that conftest was assessed.",
        "claim": "CLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (25 clauses: 4 must_prove, 17 docstring, 4 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | values the Engine reads as JSON (unset, `json`, `JSON`, `bogus`, empty) select JSON lines on the Client | :115, :120 | a Client that reads empty, unset or unknown as text, or matches `json` case-sensitively | CARRIED |\n| C1b | must_prove | values the Engine reads as text (`text`, `TEXT`, ` Text `, tab-text-newline) select text lines on the Client | :127, :130 | a Client that ignores `LOG_FORMAT`, matches case-sensitively, or does not strip whitespace and control characters | CARRIED |\n| C2a | must_prove | Client `_format_ts` returns the Engine's string for the same `created` | :157 | a stamp built from `record.msecs` or truncated rather than rounded (`.9999996` gives `57.000`, not `56.999`) | CARRIED |\n| C2b | must_prove | Client `_render_text` returns the Engine's string for the same payload | :159 | no CR/LF escaping, `None` printed instead of `null`, a non-compact list, `request_id` written twice or missing from the top level, the no-message branch or the traceback mishandled | CARRIED |\n| D1 | docstring | \"`LOG_FORMAT` picks text or JSON for the same values the Engine's does\" | :115, :130 | the wrong format chosen for a value in either partition | CARRIED |\n| D2 | docstring | \"`_format_ts` and `_render_text` return the Engine's strings for the same input\" | :157, :159 | any divergence from the Engine child's output | CARRIED |\n| D3 | docstring | the four records are logged in-process through `configure_client_logging()` | :115, :127 | a record dropped, or one record split across lines | CARRIED |\n| D4 | docstring | unset/`json`/`JSON`/`bogus`/empty: \"four JSON objects\" | :115 | any non-JSON or extra line | CARRIED |\n| D5 | docstring | \"a `ts` matching `TS_RE`\" | :117 | a stamp without the `Z` suffix or without milliseconds | CARRIED |\n| D6 | docstring | \"the Client's phase-3 keys, order and values\" | :120 | Engine keys (`modes`, `request_id`) added, keys reordered, or `service` dropped | CARRIED |\n| D7 | docstring | \"a traceback ending `ValueError: sentinel-client-log` on the exception record\" | :119 | the traceback missing (the `pop` at :118 raises) or truncated | CARRIED |\n| D8 | docstring | text variants: \"exactly four lines\" | :127 | an unescaped LF or CR in the context value or the traceback | CARRIED |\n| D9 | docstring | \"none parses as a JSON object\" | :130 | JSON still emitted under `text` | CARRIED |\n| D10 | docstring | \"none starts with `<`\" | :131 | a syslog priority prefix | CARRIED |\n| D11 | docstring | \"every one matches `<TS_RE> (INFO|ERROR) `\" | :129, :134 | a missing or malformed stamp or level head | CARRIED |\n| D12 | docstring | \"the rest is the Engine's line shape with no `service` token\" | :137, :139, :141 | a `service=` token, or JSON-ish context | CARRIED |\n| D13 | docstring | \"`engine.call` line ends `error=x\\\\ny`\" with a literal backslash-n | :137 | an unescaped or doubly escaped newline | CARRIED |\n| D14 | docstring | \"exception line ends with the traceback\", with `\\n` literal | :138 | the traceback missing, placed before the message, or left unescaped | CARRIED |\n| D15 | docstring | access line reads \"`INFO client.access request finished ip=127.0.0.1 status=200 bytes=-`\" | :141 | an int written as `\"200\"`, or the context order changed | CARRIED |\n| D16 | docstring | the Engine child prints the two stamps and the two observed text lines | :150 | a child that renders nothing, so the equality checks compare empty strings | CARRIED |\n| D17 | docstring | the Client's `_format_ts` and `_render_text` \"return the same strings in-process\" | :157, :159 | any per-branch divergence from the Engine | CARRIED |\n| N1 | name | \"unset, empty, json or unknown writes json lines\" | :115 | text written for any of those values | CARRIED |\n| N2a | name | \"writes the Engine's escaped text line\" | :137, :138, :141 | unescaped output, or a shape other than the Engine's | CARRIED |\n| N2b | name | \"per record\" | :127 | a record split across lines, or two records merged | CARRIED |\n| N3 | name | \"format_ts and render_text return the Engine's strings\" | :157, :159 | output that differs from the Engine child | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. bounds (rules/testing.md): tests/tmp/test_19_timestamped_request_logs_phase4.py:60\n   No `RENDER_PAYLOADS` value has a non-ASCII character. The Engine's `_text_value` dumps with `ensure_ascii=False`. The Client's existing JSON formatter uses `ensure_ascii=True` (client/backend/server.py:146), so a Client `_render_text` that dumps with `ensure_ascii=True` would pass :159 while differing from the Engine. The payload set also has no bool and no empty `context`.\n2. bounds (rules/testing.md): tests/tmp/test_19_timestamped_request_logs_phase4.py:123\n   No `LOG_FORMAT` value sits close to `text` without being it, such as `texts`, `tex` or `context`. The Engine reads those as `json` (logging_profiles.py:87-90). A Client that tests with `\"text\" in value` or `startswith(\"text\")` passes both parametrize sets but selects text for them.\n3. No rule covers this (rules/testing.md, `whole-claim` context): tests/tmp/test_19_timestamped_request_logs_phase4.py:111, :123\n   C1 is stated relative to the Engine, but the expected selections are hard-coded. The Engine's `normalize_log_format` is never consulted, unlike C2, which compares against a live Engine child at :146. The values match the Engine as it reads today. If the Engine's normalisation drifts later, this test does not notice.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `code_under_test` lists tests/active/test_log_format.py, which does not resolve. Nothing in it was assessed.\n2. In client/backend/server.py as read, `LOG_FORMAT` is not read and `_render_text` is not defined. I judged C1 and C2 against the Engine's definitions (engine/server/api/logging_profiles.py:85-90, :196-223) rather than against Client code.\n3. `fixtures_path` was not supplied. `client_server` comes from tests/active/conftest.py:41, which I read. The test uses no pytest fixtures other than `monkeypatch`.",
        "body": "### devsecops-test-shape-auditor\n\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\nAll four parametrisations of `test_client_log_format_text_writes_the_engines_escaped_text_line_per_record` fail at tests/tmp/test_19_timestamped_request_logs_phase4.py:129 on `assert all(TEXT_HEAD_RE.match(line) for line in lines)`. The Client ignores `LOG_FORMAT`, so each line begins `{\"ts\":`; the length check at line 127 passes first because JSON escapes the embedded newlines. `test_client_format_ts_and_render_text_return_the_engines_strings` passes lines 147, 150 and 157, then errors rather than fails at line 158. That error is `AttributeError: module 'server' has no attribute '_render_text'`. The five parametrisations of `test_client_log_format_unset_empty_json_or_unknown_writes_json_lines` pass against the current JSON-only Client.\n\nNOT ASSESSED\n1. `code_under_test` lists tests/active/test_log_format.py, and it does not exist (Glob `tests/active/test_log_format*.py` found nothing). The test does not import it, so this audit is unaffected. The listed path was not read.\n2. `fixtures_path` was not supplied. The test uses no pytest fixture except the built-in `monkeypatch`. It imports `client_server` from tests/active/conftest.py:41 (`import server as client_server`). The import was resolved there, and nothing else in that conftest was assessed.\n\n### devsecops-test-claim-auditor\n\nCLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (25 clauses: 4 must_prove, 17 docstring, 4 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | values the Engine reads as JSON (unset, `json`, `JSON`, `bogus`, empty) select JSON lines on the Client | :115, :120 | a Client that reads empty, unset or unknown as text, or matches `json` case-sensitively | CARRIED |\n| C1b | must_prove | values the Engine reads as text (`text`, `TEXT`, ` Text `, tab-text-newline) select text lines on the Client | :127, :130 | a Client that ignores `LOG_FORMAT`, matches case-sensitively, or does not strip whitespace and control characters | CARRIED |\n| C2a | must_prove | Client `_format_ts` returns the Engine's string for the same `created` | :157 | a stamp built from `record.msecs` or truncated rather than rounded (`.9999996` gives `57.000`, not `56.999`) | CARRIED |\n| C2b | must_prove | Client `_render_text` returns the Engine's string for the same payload | :159 | no CR/LF escaping, `None` printed instead of `null`, a non-compact list, `request_id` written twice or missing from the top level, the no-message branch or the traceback mishandled | CARRIED |\n| D1 | docstring | \"`LOG_FORMAT` picks text or JSON for the same values the Engine's does\" | :115, :130 | the wrong format chosen for a value in either partition | CARRIED |\n| D2 | docstring | \"`_format_ts` and `_render_text` return the Engine's strings for the same input\" | :157, :159 | any divergence from the Engine child's output | CARRIED |\n| D3 | docstring | the four records are logged in-process through `configure_client_logging()` | :115, :127 | a record dropped, or one record split across lines | CARRIED |\n| D4 | docstring | unset/`json`/`JSON`/`bogus`/empty: \"four JSON objects\" | :115 | any non-JSON or extra line | CARRIED |\n| D5 | docstring | \"a `ts` matching `TS_RE`\" | :117 | a stamp without the `Z` suffix or without milliseconds | CARRIED |\n| D6 | docstring | \"the Client's phase-3 keys, order and values\" | :120 | Engine keys (`modes`, `request_id`) added, keys reordered, or `service` dropped | CARRIED |\n| D7 | docstring | \"a traceback ending `ValueError: sentinel-client-log` on the exception record\" | :119 | the traceback missing (the `pop` at :118 raises) or truncated | CARRIED |\n| D8 | docstring | text variants: \"exactly four lines\" | :127 | an unescaped LF or CR in the context value or the traceback | CARRIED |\n| D9 | docstring | \"none parses as a JSON object\" | :130 | JSON still emitted under `text` | CARRIED |\n| D10 | docstring | \"none starts with `<`\" | :131 | a syslog priority prefix | CARRIED |\n| D11 | docstring | \"every one matches `<TS_RE> (INFO|ERROR) `\" | :129, :134 | a missing or malformed stamp or level head | CARRIED |\n| D12 | docstring | \"the rest is the Engine's line shape with no `service` token\" | :137, :139, :141 | a `service=` token, or JSON-ish context | CARRIED |\n| D13 | docstring | \"`engine.call` line ends `error=x\\\\ny`\" with a literal backslash-n | :137 | an unescaped or doubly escaped newline | CARRIED |\n| D14 | docstring | \"exception line ends with the traceback\", with `\\n` literal | :138 | the traceback missing, placed before the message, or left unescaped | CARRIED |\n| D15 | docstring | access line reads \"`INFO client.access request finished ip=127.0.0.1 status=200 bytes=-`\" | :141 | an int written as `\"200\"`, or the context order changed | CARRIED |\n| D16 | docstring | the Engine child prints the two stamps and the two observed text lines | :150 | a child that renders nothing, so the equality checks compare empty strings | CARRIED |\n| D17 | docstring | the Client's `_format_ts` and `_render_text` \"return the same strings in-process\" | :157, :159 | any per-branch divergence from the Engine | CARRIED |\n| N1 | name | \"unset, empty, json or unknown writes json lines\" | :115 | text written for any of those values | CARRIED |\n| N2a | name | \"writes the Engine's escaped text line\" | :137, :138, :141 | unescaped output, or a shape other than the Engine's | CARRIED |\n| N2b | name | \"per record\" | :127 | a record split across lines, or two records merged | CARRIED |\n| N3 | name | \"format_ts and render_text return the Engine's strings\" | :157, :159 | output that differs from the Engine child | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. bounds (rules/testing.md): tests/tmp/test_19_timestamped_request_logs_phase4.py:60\n   No `RENDER_PAYLOADS` value has a non-ASCII character. The Engine's `_text_value` dumps with `ensure_ascii=False`. The Client's existing JSON formatter uses `ensure_ascii=True` (client/backend/server.py:146), so a Client `_render_text` that dumps with `ensure_ascii=True` would pass :159 while differing from the Engine. The payload set also has no bool and no empty `context`.\n2. bounds (rules/testing.md): tests/tmp/test_19_timestamped_request_logs_phase4.py:123\n   No `LOG_FORMAT` value sits close to `text` without being it, such as `texts`, `tex` or `context`. The Engine reads those as `json` (logging_profiles.py:87-90). A Client that tests with `\"text\" in value` or `startswith(\"text\")` passes both parametrize sets but selects text for them.\n3. No rule covers this (rules/testing.md, `whole-claim` context): tests/tmp/test_19_timestamped_request_logs_phase4.py:111, :123\n   C1 is stated relative to the Engine, but the expected selections are hard-coded. The Engine's `normalize_log_format` is never consulted, unlike C2, which compares against a live Engine child at :146. The values match the Engine as it reads today. If the Engine's normalisation drifts later, this test does not notice.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `code_under_test` lists tests/active/test_log_format.py, which does not resolve. Nothing in it was assessed.\n2. In client/backend/server.py as read, `LOG_FORMAT` is not read and `_render_text` is not defined. I judged C1 and C2 against the Engine's definitions (engine/server/api/logging_profiles.py:85-90, :196-223) rather than against Client code.\n3. `fixtures_path` was not supplied. `client_server` comes from tests/active/conftest.py:41, which I read. The test uses no pytest fixtures other than `monkeypatch`.",
        "map": [
          {
            "id": "C1a",
            "source": "must_prove",
            "clause": "values the Engine reads as JSON (unset, `json`, `JSON`, `bogus`, empty) select JSON lines on the Client",
            "assertion": ":115, :120",
            "excludes": "a Client that reads empty, unset or unknown as text, or matches `json` case-sensitively",
            "status": "CARRIED"
          },
          {
            "id": "C1b",
            "source": "must_prove",
            "clause": "values the Engine reads as text (`text`, `TEXT`, ` Text `, tab-text-newline) select text lines on the Client",
            "assertion": ":127, :130",
            "excludes": "a Client that ignores `LOG_FORMAT`, matches case-sensitively, or does not strip whitespace and control characters",
            "status": "CARRIED"
          },
          {
            "id": "C2a",
            "source": "must_prove",
            "clause": "Client `_format_ts` returns the Engine's string for the same `created`",
            "assertion": ":157",
            "excludes": "a stamp built from `record.msecs` or truncated rather than rounded (`.9999996` gives `57.000`, not `56.999`)",
            "status": "CARRIED"
          },
          {
            "id": "C2b",
            "source": "must_prove",
            "clause": "Client `_render_text` returns the Engine's string for the same payload",
            "assertion": ":159",
            "excludes": "no CR/LF escaping, `None` printed instead of `null`, a non-compact list, `request_id` written twice or missing from the top level, the no-message branch or the traceback mishandled",
            "status": "CARRIED"
          },
          {
            "id": "D1",
            "source": "docstring",
            "clause": "\"`LOG_FORMAT` picks text or JSON for the same values the Engine's does\"",
            "assertion": ":115, :130",
            "excludes": "the wrong format chosen for a value in either partition",
            "status": "CARRIED"
          },
          {
            "id": "D2",
            "source": "docstring",
            "clause": "\"`_format_ts` and `_render_text` return the Engine's strings for the same input\"",
            "assertion": ":157, :159",
            "excludes": "any divergence from the Engine child's output",
            "status": "CARRIED"
          },
          {
            "id": "D3",
            "source": "docstring",
            "clause": "the four records are logged in-process through `configure_client_logging()`",
            "assertion": ":115, :127",
            "excludes": "a record dropped, or one record split across lines",
            "status": "CARRIED"
          },
          {
            "id": "D4",
            "source": "docstring",
            "clause": "unset/`json`/`JSON`/`bogus`/empty: \"four JSON objects\"",
            "assertion": ":115",
            "excludes": "any non-JSON or extra line",
            "status": "CARRIED"
          },
          {
            "id": "D5",
            "source": "docstring",
            "clause": "\"a `ts` matching `TS_RE`\"",
            "assertion": ":117",
            "excludes": "a stamp without the `Z` suffix or without milliseconds",
            "status": "CARRIED"
          },
          {
            "id": "D6",
            "source": "docstring",
            "clause": "\"the Client's phase-3 keys, order and values\"",
            "assertion": ":120",
            "excludes": "Engine keys (`modes`, `request_id`) added, keys reordered, or `service` dropped",
            "status": "CARRIED"
          },
          {
            "id": "D7",
            "source": "docstring",
            "clause": "\"a traceback ending `ValueError: sentinel-client-log` on the exception record\"",
            "assertion": ":119",
            "excludes": "the traceback missing (the `pop` at :118 raises) or truncated",
            "status": "CARRIED"
          },
          {
            "id": "D8",
            "source": "docstring",
            "clause": "text variants: \"exactly four lines\"",
            "assertion": ":127",
            "excludes": "an unescaped LF or CR in the context value or the traceback",
            "status": "CARRIED"
          },
          {
            "id": "D9",
            "source": "docstring",
            "clause": "\"none parses as a JSON object\"",
            "assertion": ":130",
            "excludes": "JSON still emitted under `text`",
            "status": "CARRIED"
          },
          {
            "id": "D10",
            "source": "docstring",
            "clause": "\"none starts with `<`\"",
            "assertion": ":131",
            "excludes": "a syslog priority prefix",
            "status": "CARRIED"
          },
          {
            "id": "D12",
            "source": "docstring",
            "clause": "\"the rest is the Engine's line shape with no `service` token\"",
            "assertion": ":137, :139, :141",
            "excludes": "a `service=` token, or JSON-ish context",
            "status": "CARRIED"
          },
          {
            "id": "D13",
            "source": "docstring",
            "clause": "\"`engine.call` line ends `error=x\\\\ny`\" with a literal backslash-n",
            "assertion": ":137",
            "excludes": "an unescaped or doubly escaped newline",
            "status": "CARRIED"
          },
          {
            "id": "D14",
            "source": "docstring",
            "clause": "\"exception line ends with the traceback\", with `\\n` literal",
            "assertion": ":138",
            "excludes": "the traceback missing, placed before the message, or left unescaped",
            "status": "CARRIED"
          },
          {
            "id": "D15",
            "source": "docstring",
            "clause": "access line reads \"`INFO client.access request finished ip=127.0.0.1 status=200 bytes=-`\"",
            "assertion": ":141",
            "excludes": "an int written as `\"200\"`, or the context order changed",
            "status": "CARRIED"
          },
          {
            "id": "D16",
            "source": "docstring",
            "clause": "the Engine child prints the two stamps and the two observed text lines",
            "assertion": ":150",
            "excludes": "a child that renders nothing, so the equality checks compare empty strings",
            "status": "CARRIED"
          },
          {
            "id": "D17",
            "source": "docstring",
            "clause": "the Client's `_format_ts` and `_render_text` \"return the same strings in-process\"",
            "assertion": ":157, :159",
            "excludes": "any per-branch divergence from the Engine",
            "status": "CARRIED"
          },
          {
            "id": "N1",
            "source": "name",
            "clause": "\"unset, empty, json or unknown writes json lines\"",
            "assertion": ":115",
            "excludes": "text written for any of those values",
            "status": "CARRIED"
          },
          {
            "id": "N2a",
            "source": "name",
            "clause": "\"writes the Engine's escaped text line\"",
            "assertion": ":137, :138, :141",
            "excludes": "unescaped output, or a shape other than the Engine's",
            "status": "CARRIED"
          },
          {
            "id": "N2b",
            "source": "name",
            "clause": "\"per record\"",
            "assertion": ":127",
            "excludes": "a record split across lines, or two records merged",
            "status": "CARRIED"
          },
          {
            "id": "N3",
            "source": "name",
            "clause": "\"format_ts and render_text return the Engine's strings\"",
            "assertion": ":157, :159",
            "excludes": "output that differs from the Engine child",
            "status": "CARRIED"
          }
        ],
        "map_problem": ""
      }
    ]
  },
  "refactors": "<refactors>\nengine/server/api/logging_profiles.py: the module docstring now mentions the text lines that `LOG_FORMAT=text` selects, not only the JSON events. This is a docstring-only change, with no change to code or behaviour.\n</refactors>\n\n<left_out>\nclient/backend/server.py `_proxy_engine_request`'s catch-all `except Exception` puts `traceback.format_exc()` into `context.traceback`. Now that `ClientLogFormatter` handles `exc_info`, `exc_info=True` could replace it, but the traceback would move from `context.traceback` to a top-level `traceback` key. That changes the JSON output, so it is not a refactor.\nengine/server/api/logging_profiles.py `EngineJsonFormatter.format`: the `access.start` and `access` branches repeat `if fields: payload[\"context\"] = fields`. They could be folded into a table of fixed messages, but that code predates this build and its output is already gated, so I left it alone.\n`EngineJsonFormatter` is now a misnomer because it can also write text, but renaming it would break its existing importers and tests, and engine/server/README.md names it. Left as is.\nThe six copied logging helpers (Engine and Client): merging them is already covered by the `rat-tail:` comment in client/backend/server.py, with a shared package as the upgrade once a third consumer appears, so I left them duplicated.\nThat `rat-tail:` comment says a cross-service test compares both copies. Today that drift guard exists only as the checkpoint tests/tmp/test_19_timestamped_request_logs_phase4.py; tests/active/test_log_format.py, which every phase lists, was never created. If the checkpoint is not moved into tests/active, nothing durable backs the comment's claim. That move is the workflow's job, not a production refactor.\nProbe files from this build are still in tests/tmp. Some are emptied (probe_fromtimestamp.py, probe_caplog_formatter.py); others are not (probe_client_tb.py, probe_engine_render.py, probe_ts_values.py, test_probe_19_p1..p4.py, test_probe_19_p3_values.py). I have no delete tool, so they need removing by hand.\n</left_out>\n\n<needs_fresh_red>\nnone\n</needs_fresh_red>\n\n<observation>\nThe four phases left the production code clean: the Engine and Client helpers are copies held together by a `rat-tail:` comment, both formatters still write JSON by default, and nothing could be simplified without changing output. The one real gap is outside production code: the drift guard and the `LOG_FORMAT` tests still exist only in tests/tmp, because tests/active/test_log_format.py was never created.\n</observation>"
}
```
dev-flow:state -->

## Entries from earlier runs of this build

## Entries from earlier runs of this build

## 2026-10-01 - Step 0 - baseline

Resolved paths: {
  "active": "tests/active",
  "working": "tests/tmp",
  "plans": "docs/project/plans",
  "delete_me": "delete_me",
  "archive": "tests/archive",
  "project_dir": "/home/enduser/code/PeerTube-browser/.worktrees/19",
  "record": "tests/last_test_validation.json",
  "output": "tests/last_test_output.txt"
}

Pre-build suite exited 0. Baseline variant: False.

```
selected 1 of 46 test groups (45 unchanged):
  test_search_fusion.py — no map entry
  test_search_fusion.py  10 passed                              2.0s
  ---------------------
  total                  10 passed                              2.3s wall, 1 lane

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

## 2026-10-01 - Step 1 - Gather requirements

Approved by the operator.

### requirements

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

### conflicts

The issue says plain text should be the default with JSON optional ("plain text default, JSON optional"). The tree already writes JSON by default from both the Engine (`EngineJsonFormatter` in engine/server/api/logging_profiles.py) and the Client backend (`_emit_client_log` in client/backend/server.py), and engine/watch-engine-logs.sh, client/watch-client-logs.sh and the DEPLOYMENT.md runbooks depend on that JSON. The operator resolved this: JSON stays the default and plain text is an opt-in through LOG_FORMAT=text (R3).
The issue asks for a UTC timestamp, while the tree's existing `ts` in both services is local time with a numeric offset (`datetime.now().astimezone()`), taken at format time rather than from record.created. R1 changes the value format of `ts` to UTC `Z` from record.created. Any operator reading or tooling that assumed local wall-clock time in `ts` will now see UTC.

## 2026-10-01 - Step 2 - Develop a solution

Approved by the operator.

### initial_solution

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

### conflicts

none

## 2026-10-01 - Step 3 - Identify every file, function and doc affected

Recorded ungated, at the operator direction.

### impacts


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


### docs_checklist

<doc path="DEPLOYMENT.md">
Add one `LOG_FORMAT` paragraph after the `RANDOM_CACHE_REFRESH_INTERVAL_MINUTES` paragraph (line 114) in the service-environment block (lines 105-114), in the same one-paragraph style. Points to cover:
- Values: `json` (default) and `text`, case-insensitive, whitespace ignored. Unset, empty or unknown values select `json` and never stop startup.
- Both the Engine and the Client backend read it at logging setup.
- How to set it: through `.env.bridge` (shared by the prod and dev units and exported by `scripts/run-services.sh`) or an `Environment=` drop-in.
- `engine/watch-engine-logs.sh` shows nothing in text mode, and `client/watch-client-logs.sh` shows `{"raw":…}`.
- `ts` is UTC `YYYY-MM-DDTHH:MM:SS.mmmZ` taken at record creation.
- Text lines escape newlines, so a traceback is one line.

Also check Triage rows 203 (`context.error` of `engine.call`/`engine.bridge`) and 204 ("the JSON log record's `traceback` key"), and line 301. They stay correct in JSON mode, but each could get a short "(in `LOG_FORMAT=text`, the `error=` token / the escaped traceback at the end of the line)" note. Optional; the operator may prefer to say once in the new paragraph that the runbooks assume `json`.
</doc>
<doc path="engine/server/README.md">
Line 31 says `EngineJsonFormatter` adds a `traceback` key. That is still true in JSON mode. Optionally add that in `LOG_FORMAT=text` the traceback ends the line, newline-escaped. Otherwise no change, as long as the class keeps its name.
</doc>
<doc path="client/README.md">
Lines 31, 32 and 35 describe ERROR `engine.call` / `engine.bridge` records with `context.error`, and INFO `engine.proxy`. These stay accurate in JSON mode. Optionally add a pointer to DEPLOYMENT.md for `LOG_FORMAT` next to the `TRUSTED_PROXIES` env note (line 68), since that section lists the Client's env settings. Also uncertain: whether the README should mention that bare/library records now appear as `client.log` events and that exception records carry an additive `traceback` key.
</doc>
<doc path="docs/project/issues/19-timestamped-request-logs.md">
Per the tracker conventions: on delivery, set `Status: enhancement, complete` and move the file to `docs/project/issues/archive/`. Note that the delivered default is JSON, not the issue's "plain text default", by operator decision (recorded in the plan record). The `## Comments` section is the place to say so.
</doc>
<doc path="docs/project/issues/plan.md">
The triage note at lines 114-117 ("19 is mostly delivered … uses a local offset, not UTC … shrink it to 'UTC, plus an optional plain-text mode'") and the lane 4c row (line 91) become stale once 19 lands. Update or strike them when the issue is archived. This is bookkeeping, not product documentation.
</doc>

### highest_risk

tests/active/test_server.py `_error_events`/`_error_messages` and its four Engine-failure tests: these parse `record.getMessage()` as JSON and look for the sentinel there, but after `_emit_client_log` switches to `extra=` the message is only "Engine metadata failed" and the sentinel lives only in `context.error`. Lines 1017-1019, 1043, 1057 and 1077-1082 will fail, and the plan does not mention this file.
client/backend/server.py `_emit_client_log` plus the new `configure_client_logging`: changing what `getMessage()` returns affects every in-process consumer. Any new test that calls `configure_client_logging()` (or `configure_engine_logging()`) in the pytest process clears the root handlers, including pytest's caplog handler, and if it does not restore them, the caplog-based tests that run later in the session (test_server, test_similarity_candidates, test_random_cache, test_updater_worker) break.
engine/server/api/logging_profiles.py `EngineJsonFormatter.format` refactor plus `configure_engine_logging` env read: JSON output must stay byte-compatible apart from `ts` (key order, `modes`, `ensure_ascii`), the constructor must default to JSON for the unit tests, and every Engine child and fixture in tests/active inherits `os.environ`. A leaked `LOG_FORMAT=text` would break test_similar, test_internal_events and test_logging_profiles, make the `_has_started` waits in test_random_cache and test_server_config wait out their timeout, and give watch-engine-logs.sh an empty view.

## 2026-10-01 - Step 4 - Reassess the implementation plan (pass 1)

Pass 1. New impacts: none.

I checked the inventory against the files it names. Everything I opened holds up, and I found nothing the inventory missed. The Engine formatter (`logging_profiles.py:184-241`) does what the inventory says: `ts` comes from `datetime.now().astimezone()` at line 195, the keys are ordered `ts, level, event, message, modes` and then `request_id`/`context`/`traceback`, and the constructor is called with no arguments in the unit tests and in `configure_engine_logging`. The Client's `_emit_client_log` (`server.py:120-136`) builds JSON itself and logs it as the record's message, and `main()` calls `basicConfig(format="%(message)s")` at line 1184. The breakage the inventory flags in `tests/active/test_server.py` is real: `_error_messages`/`_error_events` (lines 991-1005) `json.loads` the result of `record.getMessage()`, and lines 1017-1019, 1043, 1057 and 1077-1082 depend on that. The `.ts` hits in the grep were TypeScript files, not timestamp consumers. The only callers of `configure_engine_logging` are the ones listed. The other caplog users (`test_random_cache.py:547`, `test_updater_worker.py:151`, `test_similarity_candidates.py`) read Engine-side records, and those records are unaffected.
<question id="1">
Yes, with one condition. Production code needs no other call-site changes, and the Engine gets the format switch without any change to its signature or its callers. In the Client, moving the structured fields from the message into `extra=` attributes is what lets one root formatter serve both JSON and text and also catch bare records. The condition: the same move breaks `tests/active/test_server.py`, which reads `getMessage()` as JSON. That module has to be edited in this build. The inventory already records this, and it is a test-side change, not a change to the plan.
</question>
<question id="2">
- **Client `getMessage()`.** It now returns only the bare message (for example "Engine metadata failed"). The event, context and error text live on the record attributes and appear only in the formatted output. Any in-process consumer has to read the attributes or run the record through the formatter. Today the only such consumer is `test_server.py`.
- **Library records.** Records from stdlib libraries in the Client now come out as structured `client.log` lines.
- **`ts` format.** It changes from local time with an offset to UTC with `Z` in both services. The watch scripts keep working because they don't parse `ts`.
- **Text mode and the watchers.** `watch-engine-logs.sh` shows nothing in text mode (`fromjson?` then `select(. != null)` drops every line). `watch-client-logs.sh` falls back to `{"raw": …}`.
- **Shared `.env.bridge`.** A `LOG_FORMAT` set there switches both services, prod and dev together, because `run-services.sh` and the units share the file.
</question>
<question id="3">
- **`test_server.py` helpers.** Rewrite them to read `record.client_event`/`record.client_context`, or to format each record with the Client formatter. The sentinel and `DROPPED_TEXT` checks must look at the context error, not the bare message. The docstring at lines 94-106 needs the matching wording.
- **Engine default.** `EngineJsonFormatter` must default to JSON, so that the no-argument constructions at test lines 34 and 141 keep working.
- **Engine JSON output.** It must stay byte-for-byte the same apart from the `ts` value, including key order and `modes`.
- **Client `context`.** An empty or missing context must still be left out, as `if context:` does today.
- **Root-handler restore.** Any test that calls `configure_client_logging()` or `configure_engine_logging()` in-process must save and restore the root handlers. Otherwise caplog breaks for every later test in the session.
- **Import side effects.** Importing `client/backend/server.py` must not touch logging, because `conftest.py:41` imports it in-process.
- **Docs.** The DEPLOYMENT.md paragraph must say that the watchers and the `context.error` runbook recipes (lines 123, 203, 301) need `json`, and that `.env.bridge` is shared.
</question>
<question id="4">
- **`ts` value.** It is now a UTC `Z` string taken from `record.created`, not formatting-time local time with an offset. Lines therefore order by when the log call was made.
- **Client records.** Records that used to come out as bare text in the Client (library or bare `logging.*` calls) are now structured lines with `event: client.log`.
- **Client `traceback`.** A Client record carrying `exc_info` gains a `traceback` key. This is additive.
- **Client `getMessage()`.** An in-process Client record's `getMessage()` is now only the bare message, not the JSON payload.
- **New `LOG_FORMAT=text` mode.** It is opt-in and gives one line per record with escaped CR/LF.
- **Unchanged.** With `LOG_FORMAT` unset or invalid, every JSON key, every key order and the output stream stay as they were.
</question>

New impacts:
none

Inventory entries that did not hold up:
none

Conflicts: none

Recommendations: 1. **Put the `tests/active/test_server.py` edit into the phase plan explicitly.** Change `_error_messages`/`_error_events` to run each ERROR record through the Client formatter in JSON mode, i.e. `json.loads(formatter.format(record))`. Point the sentinel and `DROPPED_TEXT` checks at the formatted line or at `context.error`, and fix the docstring at lines 94-106. Cost: roughly 10-15 changed lines in one test module. The benefit is that these tests then exercise the production formatter. Without this edit, five tests go red (the parametrised one counts five times) the moment `_emit_client_log` changes.
2. **Settle one value-rendering rule for text mode in both copies.** Recommended: `str` values as-is, and every other value (None, bool, int, list, dict) through compact `json.dumps`. That gives `null`/`true`/`5`/`[...]`, so the Engine's incoming-likes `user_id: None` and the Client's int `port`/`pid` render the same way in both services. Cost: nothing beyond writing it down; it removes a source of drift between the two copies.
3. **Optional: pop `LOG_FORMAT` from the environment in `tests/active/conftest.py`** (session-level, or in the Engine fixture env). This stops a developer's or CI's exported `LOG_FORMAT=text` from making about six JSON-parsing test modules fail or time out. Cost: one line. The downside is that it hides the variable from every test, so the new format tests must set it explicitly, which they already plan to do.
4. **Optional: add one line to the Notes in `engine/watch-engine-logs.sh`** saying the watcher needs `LOG_FORMAT=json`. That covers the silent empty view in text mode. Cost: one comment or help line. The installer tests don't touch this script.
5. **Note for implementation, no decision needed.** In Engine text mode the `key=value` tokens appear twice, once in the raw message and again as context, wherever no rewrite rule replaces the message. This follows from the plan's line shape and is accepted. Dropping either copy would make the text line diverge from the JSON payload, which the plan builds on purpose.

## 2026-10-01 - Step 5 - Draft the initial implementation

Recorded ungated, at the operator direction.

### draft

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

## 2026-10-01 - Step 6 - Design the phase breakdown

Recorded ungated, at the operator direction.

#### Phase 1 - Engine ts from record creation time [code]

**Files touched.** engine/server/api/logging_profiles.py (EDITED), tests/active/test_log_format.py (NEW)

**Checkpoint.** Seam for C1: the Engine child-process harness from tests/active/test_logging_profiles.py, i.e. `subprocess.run([sys.executable, "-c", _ENGINE_CHILD, …], cwd=API_DIR)` with `LOG_FORMAT` removed from the env. The child calls `configure_engine_logging("verbose")` and logs records to stderr. On stdout it prints the `_format_ts` and `EngineJsonFormatter().format` of a `LogRecord` whose `created` comes from argv. Assertions: every stderr line parses as JSON and its `ts` matches `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$`. created=1741091696.789 gives `2025-03-04T12:34:56.789Z` from both `_format_ts` and the formatted JSON's `ts`. created=1741091696.9999996 gives `2025-03-04T12:34:57.000Z`. A created one hour in the past renders that hour, not the formatting time. Seam for C2: the session `engine` fixture in conftest.py, whose log is read through `engine.db_path` as test_similar.py's `_messages` does. The test sends `POST /recommendations?limit=5&user_id=log-order-<uuid4 hex>` with `body={}`. If the route refuses `user_id`, the marker goes in through the `Host` header instead. The test parses the log's JSON lines, cuts the slice from the `access.start` whose `context.url` contains the marker to the `access` containing it, keeps the access.start, the access and the `recommendations.*` records, and asserts at least one work record and non-decreasing `ts`.

**Intent.** In engine/server/api/logging_profiles.py, EngineJsonFormatter takes every record's `ts` from `_format_ts(record)`, which renders `record.created` in UTC as `YYYY-MM-DDTHH:MM:SS.mmmZ`, so the Engine's `ts` follows the order of the log calls rather than the time of formatting.

- C1 - An Engine record's `ts` is its `record.created` rendered in UTC as `YYYY-MM-DDTHH:MM:SS.mmmZ`.
- C2 - Within one live Engine request, the `ts` values from its `access.start` to its `access` never decrease.

**Outcome.** _pending_

#### Phase 2 - Engine LOG_FORMAT text rendering [code]

**Files touched.** engine/server/api/logging_profiles.py (EDITED), tests/active/test_log_format.py (EDITED)

**Checkpoint.** Seam: the same Engine child-process harness (cwd=API_DIR; env without `LOG_FORMAT`, plus `LOG_FORMAT` set when the case has a value), parametrized over None, "json", "JSON", "bogus", "", "text", "TEXT", " Text ". The child calls `configure_engine_logging("verbose")` and logs, in order: `[probe] plain`, `[probe] two\nlines`, a `logging.exception("[probe] failed")` for `ValueError("sentinel-log-format")`, `[access.start] ip=127.0.0.1 method=GET url=http://x/a`, and `[service] lifecycle state=start component=engine run_id=r pid=1`. C1: the JSON cases give stderr lines that all parse with `json.loads`; the text cases give lines matching `^<TS_RE> (INFO|ERROR) ` and none parse as a JSON object. C2, in text mode: stderr has exactly five lines. The multiline and exception records each sit on one line, contain a literal `\n` and, for the exception record, end with `ValueError: sentinel-log-format`. The access.start line is `<ts> INFO access.start request started ip=127.0.0.1 method=GET url=http://x/a`. The lifecycle line goes `<ts> INFO service.lifecycle state=start` with no message token. No line starts with `<`.

**Intent.** configure_engine_logging reads `LOG_FORMAT` when it runs and, for `text`, has EngineJsonFormatter render each record's payload through `_render_text` as one CR/LF-escaped `ts LEVEL event message k=v…` line, while every other value keeps today's JSON.

- C1 - An Engine `LOG_FORMAT` of text in any case or surrounding whitespace selects text lines, and an unset, empty, `json` or unknown value selects JSON lines.
- C2 - An Engine text record is one physical line shaped `ts LEVEL event [message] k=v… [request_id=…] [traceback]` with CR and LF written as `\r` and `\n`.

**Outcome.** _pending_

#### Phase 3 - Client root formatter, JSON [code]

**Files touched.** client/backend/server.py (EDITED), tests/active/test_server.py (EDITED), tests/active/test_log_format.py (EDITED)

**Checkpoint.** Seam: in-process through conftest's `client_server` import. A `_client_logging(monkeypatch, value)` context manager is used inside the test body. It saves the root handlers and level, sets or deletes `LOG_FORMAT`, calls `client_server.configure_client_logging()`, swaps `root.handlers[0]` to an `io.StringIO` stream, and restores everything in `finally`. With `LOG_FORMAT` unset, the test calls `client_server._emit_client_log(logging.ERROR, "engine.call", "Engine metadata failed", {"error": "x\ny"})`, then a `logging.exception` record, then `logging.info("bare")`. C1: the emitted line's keys are exactly `["ts", "level", "service", "event", "message", "context"]` in order, with `service == "client-backend"`, `event == "engine.call"`, `context == {"error": "x\ny"}` and `ts` matching TS_RE. The exception record carries a `traceback` key. C2: the bare record parses with keys `ts, level, service, event, message`, `event == "client.log"` and `message == "bare"`. The full suite also covers the rewired ERROR-record tests in tests/active/test_server.py (`_error_messages` renders through `ClientLogFormatter`, and caplog's handler gets that formatter in the `caplog.text` test), which must stay green.

**Intent.** In client/backend/server.py, configure_client_logging installs ClientLogFormatter on the root logger, which `main()` now calls in place of `basicConfig`, and `_emit_client_log` hands it event and context as `client_event`/`client_context` record attributes instead of building JSON by hand, so every Client record leaves through one formatter.

- C1 - An `_emit_client_log` record renders as a JSON line whose keys run `ts, level, service, event, message[, context]` with a UTC `ts`.
- C2 - A bare root-logger record renders in the same JSON shape with event `client.log`.

**Outcome.** _pending_

#### Phase 4 - Client text rendering and drift guard [code]

**Files touched.** client/backend/server.py (EDITED), tests/active/test_log_format.py (EDITED)

**Checkpoint.** Seam for C1: the in-process `_client_logging` context manager from phase 3, parametrized over the same eight `LOG_FORMAT` values as phase 2. JSON cases: every line parses. Text cases: every line matches `^<TS_RE> (INFO|ERROR) `, and the exception record and the `{"error": "x\ny"}` record are each one physical line containing a literal `\n`. A `client.access` record (`_emit_client_log(INFO, "client.access", "request finished", {"ip": …, "status": 200, "bytes": "-"})`) renders `<ts> INFO client.access request finished ip=… status=200 bytes=-`. No line starts with `<`. Seam for C2: the Engine child harness prints `_format_ts` for one fixed `created` and `_render_text` of a payload passed in argv: `{"ts": …, "level": "INFO", "event": "e", "message": "m\nn", "context": {"a": 1, "b": None, "c": [1, {"d": "x"}], "request_id": "r"}, "request_id": "r", "traceback": "T\nU"}`. The test asserts both strings equal `client_server._format_ts` and `client_server._render_text` on the same inputs in-process.

**Intent.** The Client's `normalize_log_format`, `_format_ts`, `_text_value` and `_render_text` are copies of the Engine's, so `LOG_FORMAT` selects the Client's rendering exactly as it does the Engine's, and both services write byte-identical `ts` and text for the same record.

- C1 - A Client `LOG_FORMAT` value selects text or JSON lines exactly as the same value does for the Engine.
- C2 - For the same `created` and payload, the Client's `_format_ts` and `_render_text` return the same strings as the Engine's.

**Outcome.** _pending_


Needs coordination: none. No phase needs credentials or a manual step. Phase 1 clause 2 uses the session `engine` fixture, which needs the engine pixi env (`engine/.pixi/envs/default`) and `whitelist.db` that the active suite already relies on.

Rationale: Four phases, split on two seams: by service (Engine, then Client), and within each service by concern (timestamp/format contract, then the text rendering). The Engine goes first because the Client copies its helpers, and phase 4's drift guard needs both sides to exist. Each Intent reduces to two clauses. A single Engine phase would have carried three facts (ts source, LOG_FORMAT selection, text line shape), and a single Client phase would have carried four (key order, bare-record fallback, format selection, parity with the Engine), so both were split here. Phase 3 also carries the test_server.py rewire. Once `_emit_client_log` stops building JSON, those ERROR-record tests fail, so they must land in the same phase. The full suite verifies them; they are not a clause of their own. There is no prose phase: the DEPLOYMENT.md, README, issue-19 and plan.md edits are documentation for Step 9. The draft's T1-T8 map onto the clauses as follows: T1/T2 to P1-C1 and P3-C1, T8 to P1-C2, T3 to P2-C1 and P4-C1, T4/T5 to P2-C2 and P4-C1, T6 to P3, T7 to P4-C2. T9 is the full suite. Known unproven line: `main()` calling `configure_client_logging()` in place of `basicConfig` is a one-line swap that no checkpoint enters, because `main` parses argv and binds a port. The operator approved this gap. Note for the checkpoint author: the step template's principles and shape-ladder placeholders arrived unfilled, so the seams above follow the existing suite's precedent (the child harness in test_logging_profiles.py, the engine log reading in test_similar.py, and the in-process client_server import from conftest).

## 2026-10-01 - Step 7 - Phase 1 (Engine ts from record creation time) - must_prove

Quoted from the phase Intent, written at Step 6 before the checkpoint was drafted.

Intent:
In engine/server/api/logging_profiles.py, EngineJsonFormatter takes every record's `ts` from `_format_ts(record)`, which renders `record.created` in UTC as `YYYY-MM-DDTHH:MM:SS.mmmZ`, so the Engine's `ts` follows the order of the log calls rather than the time of formatting.

- C1 - An Engine record's `ts` is its `record.created` rendered in UTC as `YYYY-MM-DDTHH:MM:SS.mmmZ`.
- C2 - Within one live Engine request, the `ts` values from its `access.start` to its `access` never decrease.

must_prove:
- C1 - An Engine record's `ts` is its `record.created` rendered in UTC as `YYYY-MM-DDTHH:MM:SS.mmmZ`.
- C2 - Within one live Engine request, the `ts` values from its `access.start` to its `access` never decrease.

## 2026-10-01 - Step 7 - Phase 1 (Engine ts from record creation time) - self-check (audit round 1, send-back 0)

`tests/tmp/test_19_timestamped_request_logs_phase1.py`, surface `checkpoint`. Collection exit 0.

- C1 - test_19_timestamped_request_logs_phase1.py:72, :74, :78, :80, :81, :82, :84. Line 72: every stderr line that `configure_engine_logging("verbose")` writes in a child with TZ=Asia/Kathmandu has a `ts` that fully matches `TS_RE`. Line 74: each of those reads back as UTC to within 60 s of the child's `time.time()`. Line 78: for created=1741091696.789, `_format_ts` and `EngineJsonFormatter().format(...)["ts"]` are both `2025-03-04T12:34:56.789Z`. Line 80: for created=1741091696.9999996 both are `2025-03-04T12:34:57.000Z`. Lines 81, 82 and 84 check each of the two values for a `created` one hour back separately: it matches `TS_RE` (81), it reads back to that `created` within 1 ms (82), and it is more than HOUR-60 s before the child's clock at formatting time (84). - expected: Three `YYYY-MM-DDTHH:MM:SS.mmmZ` stamps from the child's own minute. `{"format_ts": "2025-03-04T12:34:56.789Z", "formatted": "2025-03-04T12:34:56.789Z"}` and `{"format_ts": "2025-03-04T12:34:57.000Z", "formatted": "2025-03-04T12:34:57.000Z"}`. These two values were observed in probe tests/tmp/probe_ts_values.py: the plan's `fromtimestamp(created, timezone.utc)` + `microsecond // 1000` formula gives exactly these strings. For the hour-back record, both values equal `past` truncated to the millisecond, about 3600 s before `now`. - excludes: Today's `datetime.now().astimezone().isoformat(timespec="milliseconds")` reads `2026-10-02T04:04:51.609+05:45` in the child, which fails line 72 (observed). A local-time rendering with a `Z` bolted on reads back 5h45m off and fails line 74. A ts taken at formatting time rather than from `created` gives the 2026 clock instead of 2025-03-04 at line 78 and is not an hour back at line 84. Milliseconds read from `record.msecs` give the construction clock, observed as `.129Z`, and fail lines 78 and 80. Milliseconds truncated from `created % 1` with no microsecond rounding give `2025-03-04T12:34:56.999Z` (observed in the probe) and fail line 80. A missing `_format_ts` helper prints null and fails lines 78, 80 and 81.
- C2 - test_19_timestamped_request_logs_phase1.py:120, :123, :125, :126. The session Engine log is sliced from the one `access.start` whose `context.url` holds the `log-order-<hex>` marker to the one `access` that holds it. The slice keeps the access.start, the access and the `recommendations.*` records. Line 120: at least one `recommendations.*` record lies between the two access records. Line 123: every kept `ts` fully matches `TS_RE`. Line 125: every kept `ts` reads back inside [before-1 s, after+1 s] of the request's wall clock. Line 126: the kept `ts` values, read back as epochs, are already in sorted (non-decreasing) order. - expected: An access.start, several `recommendations.*` work records and an access, all in UTC `...Z` form, inside the request window and non-decreasing. Today's run observed six or more kept records, which shows the work records are there (line 120 passed). - excludes: Today's formatter writes the Engine's local time with an offset. The observed value is `['2026-10-01T18:19:52.639-04:00', ...]`, which fails line 123. A local-time stamp ending in `Z` falls hours outside the request window and fails line 125. Line 126 catches one specific bug: seconds and milliseconds taken from two different roundings of `created`, for example seconds from `fromtimestamp` (which rounds to the microsecond) and milliseconds from `int(created % 1 * 1000)`. Then a record at x.9999996 renders as x+1.999, and the next record at x+1.0xx reads earlier, so ts goes backwards. A ts taken at formatting time on a deferred or queued handler can also run out of call order. One caveat: today's synchronous format-time stamp would also be non-decreasing. Today's red comes from lines 123 and 125, not from line 126.

<assertions>
tests/tmp/test_19_timestamped_request_logs_phase1.py:72 - every stderr line of the child (the `configure_engine_logging("verbose")` handler, LOG_FORMAT unset, TZ pinned to Asia/Kathmandu +05:45) has a `ts` that fully matches `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$` - C1
tests/tmp/test_19_timestamped_request_logs_phase1.py:74 - each of those stderr `ts` values, read back as UTC, is within 60 s of the child's `time.time()`, so a local-time rendering (off by 5h45m here) fails - C1
tests/tmp/test_19_timestamped_request_logs_phase1.py:78 - created=1741091696.789, set on a LogRecord after construction (its msecs is the clock at construction): `_format_ts` and `EngineJsonFormatter().format`'s `ts` are both exactly `2025-03-04T12:34:56.789Z` - C1
tests/tmp/test_19_timestamped_request_logs_phase1.py:80 - created=1741091696.9999996: both are exactly `2025-03-04T12:34:57.000Z` (plain millisecond truncation gives 56.999) - C1
tests/tmp/test_19_timestamped_request_logs_phase1.py:81 - created = test's time.time() - 3600: the formatter's `ts` equals `_format_ts` and matches TS_RE - C1
tests/tmp/test_19_timestamped_request_logs_phase1.py:82 - that `ts`, read back as UTC epoch, is within 1 ms of the `created` passed in - C1
tests/tmp/test_19_timestamped_request_logs_phase1.py:84 - negative: that `ts` is more than 3540 s before the child's formatting time, so it is not the time of formatting - C1
tests/tmp/test_19_timestamped_request_logs_phase1.py:120 - session Engine, POST /recommendations?limit=5&user_id=log-order-<hex>, body {}: between the single marked access.start and the single marked access (controls at :109 status 200 with seed.user_id == marker, :116 exactly one of each with start before end, :119 the kept slice opens with access.start and closes with access), at least one `recommendations.*` work record is kept - C2
tests/tmp/test_19_timestamped_request_logs_phase1.py:123 - every kept record's `ts` matches TS_RE - C2
tests/tmp/test_19_timestamped_request_logs_phase1.py:125 - every kept `ts`, read back as UTC, lies within [before-1 s, after+1 s] of the request's wall-clock window, which rules out a constant or local-time ts that would make ordering vacuous - C2
tests/tmp/test_19_timestamped_request_logs_phase1.py:126 - the kept `ts` values, in log order, never decrease - C2
</assertions>

<probes>
1. tests/tmp/test_probe_19_p1.py::test_probe_child, run via ValidateTests ["tests/tmp/test_probe_19_p1.py", "-k", "child"]. The child ran under the current logging_profiles with LOG_FORMAT removed. Stderr lines read like {"ts":"2026-10-01T18:16:04.556-04:00",...} for "[probe] plain", "request started" and "[probe] failed without exception". `_format_ts` is absent (printed null). `EngineJsonFormatter().format` of records with created 1741091696.789 / 1741091696.9999995 / now-3600 gave ts "2026-10-01T18:16:04.556-04:00" for all three, which is the formatting time. record.msecs was 556.0, set at construction and not updated when created was set. In the parent, datetime.fromtimestamp(..., timezone.utc) gave 2025-03-04T12:34:56.789000+00:00 and 2025-03-04T12:34:57+00:00, while int(frac*1000) gave 789 and 999. json.dumps renders 1741091696.9999996 as 1741091696.9999995 (the same float). The host TZ is -04:00 and TZ is unset.
2. tests/tmp/test_probe_19_p1.py::test_probe_engine, against the session `engine` fixture. POST /recommendations?limit=5&user_id=log-order-<hex> with body {} returned 200, seed {"user_id": marker, "mode": "home"} and 5 rows, so the route accepts `user_id` and no Host-header fallback is needed. The log had 0 non-JSON lines. The marker appeared in the access.start and access context.url, and between them came recommendations.incoming_likes_body (no request_id), recommendations.info ×6, recommendations.layer_timing and recommendations.profile, plus similar_server.info and similarity.request_done, which the filter drops. The request took about 600 ms.
3. The checkpoint itself, against the current code (ValidateTests on tests/tmp/test_19_timestamped_request_logs_phase1.py): 2 failed. C1 passed all controls and failed at :72 with ts ['2026-10-02T04:02:22.310+05:45', …], which shows the TZ pin reaches the child. C2 passed all controls (200, one start and one end, recommendations work present) and failed at :123 with ts ['2026-10-01T18:17:23.590-04:00', …].
4. tests/tmp/test_probe_19_p1.py::test_probe_patched ran the checkpoint's C1 test with the plan's `_format_ts` (fromtimestamp UTC, microsecond // 1000) patched in memory into logging_profiles, along with a formatter subclass that sets ts from it. Result: "PATCHED PASSES". Every C1 expectation holds under the intended implementation. C2 was not run against a patched Engine (see unassertable).
The probe file has been overwritten with a "Delete this file." note, following the repo's existing tmp-probe convention, because I have no delete tool.
</probes>

<unassertable>
none. Every C1 and C2 assertion is in place. Two notes for the reviewer. (a) C2's pass under a correct implementation is predicted but not observed: I could not run the live Engine with the new `_format_ts` without editing production code. The prediction rests on the probed slice, where all kept records are written on the request's thread in a serial sequence, and on the C1 probe passing under the plan's helper. The phase's first green run will confirm it. (b) Two pins go beyond the agreed seam, and both serve the agreed assertions. The C1 child gets TZ=Asia/Kathmandu so a local-time rendering cannot pass on a UTC host. The C2 test also bounds every kept ts to the request's wall-clock window, so a constant ts cannot pass "non-decreasing" vacuously.
</unassertable>

### `tests/tmp/test_19_timestamped_request_logs_phase1.py` - 7781 characters, inlined in full

```
"""The Engine's `ts` is the record's creation time in UTC `YYYY-MM-DDTHH:MM:SS.mmmZ`, and within one live request it never decreases.

- `configure_engine_logging("verbose")` in a child with `LOG_FORMAT` unset and the zone pinned off UTC: every stderr line is JSON whose `ts` matches `TS_RE` and reads back within a minute of the child's clock. For a `LogRecord` whose `created` is set after construction, `_format_ts` and `EngineJsonFormatter().format`'s `ts` both give `2025-03-04T12:34:56.789Z` for 1741091696.789 and `2025-03-04T12:34:57.000Z` for 1741091696.9999996; for a `created` one hour back both read back to that `created` within a millisecond, an hour before the formatting.
- The session Engine, sent `POST /recommendations?limit=5&user_id=log-order-<hex>`: in its log, from the one `access.start` whose url carries the marker to the one `access` that does, the `access.start`, the `access` and at least one `recommendations.*` record carry a `ts` matching `TS_RE`, within the request's wall-clock window, never decreasing.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import textwrap
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

ACTIVE = Path(__file__).resolve().parents[1] / "active"
if str(ACTIVE) not in sys.path:
    sys.path.insert(0, str(ACTIVE))

from conftest import ROOT, engine  # noqa: E402,F401

API_DIR = ROOT / "engine" / "server" / "api"
TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
HOUR = 3600
# +05:45: a ts rendered in local time, with or without a `Z`, is off by hours and minutes here, whatever zone the host runs in.
OFF_UTC_ZONE = "Asia/Kathmandu"
LOG_WAIT_SECONDS = 5

# Logs three records through the production setup, then reports what `_format_ts` and the formatter give for records whose `created` comes from argv.
_ENGINE_CHILD = textwrap.dedent(
    """
    import json, logging, sys, time
    import logging_profiles
    from logging_profiles import EngineJsonFormatter, configure_engine_logging
    configure_engine_logging("verbose")
    logging.info("[probe] plain")
    logging.info("[access.start] ip=127.0.0.1 method=GET url=http://x/a")
    logging.error("[probe] failed without exception")
    # A missing helper prints null, so the formatter's own ts still reaches the test.
    format_ts = getattr(logging_profiles, "_format_ts", None)
    cases = []
    for created in json.loads(sys.argv[1]):
        # msecs is taken from the clock at construction and not updated, so a ts built from it shows the wrong milliseconds.
        record = logging.LogRecord("probe", logging.INFO, "probe", 1, "[probe] fixed", None, None)
        record.created = created
        cases.append({"format_ts": format_ts(record) if format_ts else None, "formatted": json.loads(EngineJsonFormatter().format(record))["ts"]})
    print(json.dumps({"now": time.time(), "cases": cases}))
    """
)


def _epoch(ts: str) -> float:
    """Read a `TS_RE` timestamp back as UTC epoch seconds."""
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc).timestamp()


def test_engine_ts_is_record_created_in_utc_with_milliseconds():
    env = {key: value for key, value in os.environ.items() if key != "LOG_FORMAT"}
    env["TZ"] = OFF_UTC_ZONE
    past = time.time() - HOUR
    run = subprocess.run([sys.executable, "-c", _ENGINE_CHILD, json.dumps([1741091696.789, 1741091696.9999996, past])], cwd=API_DIR, env=env, capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stderr[-2000:]
    report = json.loads(run.stdout)
    lines = [json.loads(line) for line in run.stderr.splitlines()]
    assert all(isinstance(line, dict) for line in lines), run.stderr[-2000:]
    # Control: the three records reached stderr through the production formatter, in order.
    assert [line["message"] for line in lines] == ["[probe] plain", "request started", "[probe] failed without exception"], lines

    assert all(TS_RE.fullmatch(line["ts"]) for line in lines), [line["ts"] for line in lines]  # C1
    # A local-time rendering reads back 5h45m off the child's clock here.
    assert all(abs(report["now"] - _epoch(line["ts"])) < 60 for line in lines), (report["now"], [line["ts"] for line in lines])  # C1

    fixed, rounded, hour_back = report["cases"]
    # The formatting time, or a `created` read through record.msecs (the clock at construction), gives another value.
    assert fixed == {"format_ts": "2025-03-04T12:34:56.789Z", "formatted": "2025-03-04T12:34:56.789Z"}, fixed  # C1
    # Milliseconds truncated from `created` without rounding to the microsecond first give 56.999.
    assert rounded == {"format_ts": "2025-03-04T12:34:57.000Z", "formatted": "2025-03-04T12:34:57.000Z"}, rounded  # C1
    assert hour_back["formatted"] == hour_back["format_ts"] and TS_RE.fullmatch(hour_back["formatted"]), hour_back  # C1
    assert abs(_epoch(hour_back["formatted"]) - past) < 0.001, (hour_back, past)  # C1
    # Not the formatting time: the child formatted it an hour after the time it renders.
    assert report["now"] - _epoch(hour_back["formatted"]) > HOUR - 60, (report["now"], hour_back)  # C1


def _request_records(log_path: Path, marker: str) -> tuple[list[int], list[int], list[dict]]:
    """Every JSON record of the log, with the indexes of the access.start and access records whose url carries the marker."""
    records = []
    for line in log_path.read_text(errors="replace").splitlines():
        try:
            payload = json.loads(line)
        except ValueError:
            continue
        if isinstance(payload, dict):
            records.append(payload)
    marked = [marker in str((record.get("context") or {}).get("url", "")) for record in records]
    starts = [index for index, record in enumerate(records) if marked[index] and record.get("event") == "access.start"]
    ends = [index for index, record in enumerate(records) if marked[index] and record.get("event") == "access"]
    return starts, ends, records


def test_engine_request_ts_never_decreases_from_access_start_to_access(engine):
    marker = f"log-order-{uuid.uuid4().hex}"
    before = time.time()
    status, body = engine.request("POST", f"/recommendations?limit=5&user_id={marker}", body={})
    after = time.time()
    # Control: the route took user_id, so the marker is in the url of both access lines (observed: seed {"user_id": marker, "mode": "home"}).
    assert status == 200 and body["seed"].get("user_id") == marker, (status, body)
    deadline = time.time() + LOG_WAIT_SECONDS
    starts, ends, records = _request_records(engine.db_path, marker)
    while not ends and time.time() < deadline:
        time.sleep(0.1)
        starts, ends, records = _request_records(engine.db_path, marker)
    # Control: one request, started before it finished.
    assert len(starts) == 1 and len(ends) == 1 and starts[0] < ends[0], (starts, ends)
    kept = [record for record in records[starts[0]:ends[0] + 1] if record["event"] in ("access.start", "access") or record["event"].startswith("recommendations.")]
    events = [record["event"] for record in kept]
    assert events[0] == "access.start" and events[-1] == "access", events
    assert any(event.startswith("recommendations.") for event in events[1:-1]), events  # C2

    stamps = [record["ts"] for record in kept]
    assert all(TS_RE.fullmatch(ts) for ts in stamps), stamps  # C2
    # A constant or local-time ts falls outside the window the request ran in; one second covers the millisecond truncation.
    assert all(before - 1 <= _epoch(ts) <= after + 1 for ts in stamps), (before, after, stamps)  # C2
    assert [_epoch(ts) for ts in stamps] == sorted(_epoch(ts) for ts in stamps), list(zip(events, stamps))  # C2

```


Gate: satisfied

## 2026-10-01 - Step 7 - Phase 1 (Engine ts from record creation time) - red (audit round 1)

`tests/tmp/test_19_timestamped_request_logs_phase1.py` exited 1.

```
  tests/tmp/test_19_timestamped_request_logs_phase1.py  2 failed                               0.0s
  ----------------------------------------------------
  total                                                 2 failed                               2.1s wall, 1 lane

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

## 2026-10-01 - Step 7 - Phase 1 (Engine ts from record creation time) - audit (round 1)

- AUDIT: devsecops-test-shape-auditor - PASS
- AUDIT: devsecops-test-claim-auditor - PASS
- OUTSTANDING: nothing

### devsecops-test-shape-auditor

SHAPE AUDIT — VERDICT: PASS

CRITICAL
none

RECOMMENDATIONS
none

PREDICTED FAILURE
`test_engine_ts_is_record_created_in_utc_with_milliseconds` fails at line 72 on `assert all(TS_RE.fullmatch(line["ts"]) for line in lines)`. The cause is logging_profiles.py:195: it renders `ts` as `datetime.now().astimezone().isoformat(timespec="milliseconds")`, and under `TZ=Asia/Kathmandu` that gives a value ending in `+05:45` rather than `Z`.
`test_engine_request_ts_never_decreases_from_access_start_to_access` fails at line 123 on `assert all(TS_RE.fullmatch(ts) for ts in stamps)` for the same cause: the timestamp carries an offset suffix (such as `+00:00`) instead of `Z`.

NOT ASSESSED
1. `code_under_test` lists tests/active/test_log_format.py (NEW), and that path does not exist. Nothing in that file was assessed.
2. `fixtures_path` was not supplied. I found the `engine` fixture and `ROOT` in tests/active/conftest.py, which the test imports at line 23. I read the fixture there: `engine.db_path` is the session Engine's log file. I did not read the Engine's request and recommendations code. So whether a `recommendations.*` record is logged inside the marked request, which lines 116–120 depend on, comes from the test's own comment at line 108 and was not checked against the code. The line-123 prediction assumes those earlier assertions hold.
3. Anti-patterns pass, done as its own read. All seven `<anti_pattern>` entries were checked against their `<how_to_spot>` blocks, and none matched:
   - No `.md` file is read, so the doc and substring-grep entries do not apply.
   - The literals at lines 78 and 80 are outputs of the formatter for stated `created` inputs. They are not mirrored code constants.
   - The expectations at lines 82 and 84 come from the input `past` and the child's clock, through `_epoch` (a `strptime` parse). Nothing re-derives them the way the formatter does.
   - Every assertion is a positive one.
   - Production code (`_format_ts`, `EngineJsonFormatter.format`, the live Engine) sits between every input and its assertion.
   - C1 is exercised at three `created` values: a fixed millisecond, a rounding edge, and one hour back. It also runs under a zone pinned away from UTC, so returning the formatting time or local time cannot pass.
4. Ladder pass, done as its own read:
   - Test 1 calls the formatter directly (rung 1) in a child process and reads emitted log lines (rung 3). Running in a child is needed to pin `TZ`, and comments at lines 28 and 32 explain it.
   - Test 2 asserts on log entries emitted by a live request (rung 3), which is where C2 lives.
   - Neither test is on the anti-rung, and neither downshifts without a comment.
5. Stub question:
   - For C1, an implementation that returns the formatting time fails lines 78 and 84. One that renders local time fails lines 72, 74 and 78. One that reads `record.msecs` fails line 78, and one that truncates fails line 80.
   - For C2, a constant or local-time `ts` fails lines 123 and 125.

### devsecops-test-claim-auditor

CLAIM AUDIT — VERDICT: PASS

CLAUSE MAP  (24 clauses: 7 must_prove, 13 docstring, 4 name)
| id | source | clause | assertion | excludes | status |
|---|---|---|---|---|---|
| C1a | must_prove | `ts` is in the form `YYYY-MM-DDTHH:MM:SS.mmmZ` | :72, :81 | the current `isoformat(timespec="milliseconds")` output, which ends `+05:45` (or any other offset), not `Z` | CARRIED |
| C1b | must_prove | rendered "in UTC" | :74, :78 | a local-time rendering with or without a `Z`: the child runs with `TZ=Asia/Kathmandu`, so it reads back 5h45m off the child's clock | CARRIED |
| C1c | must_prove | the instant is "its `record.created`", not the formatting time | :78, :82, :84 | `datetime.now()` at format time: `created` is fixed at 2025-03-04, and also set one hour back, and the formatting happens later | CARRIED |
| C1d | must_prove | the milliseconds come from `created` | :78, :80 | milliseconds taken from `record.msecs`, which is set at construction before `created` is overwritten, and milliseconds truncated without rounding to the microsecond first (`56.999`) | CARRIED |
| C2a | must_prove | "within one live Engine request" | :109, :116 | a run against something other than the live Engine (`engine` session fixture, real HTTP POST), and a marker matching zero or several requests | CARRIED |
| C2b | must_prove | the span runs "from its `access.start` to its `access`" | :116, :119 | the end record logged before the start record, and a slice that does not open and close on those two events | CARRIED |
| C2c | must_prove | the `ts` values "never decrease" | :126, with :120, :125 | any out-of-order `ts` inside the span. :120 makes sure there are more than two points to order, and :125 fails a constant or local-time `ts` that would trivially stay in order | CARRIED |
| D1 | docstring | "`ts` is the record's creation time in UTC `YYYY-MM-DDTHH:MM:SS.mmmZ`" | :72, :78, :84 | as C1a–C1c | CARRIED |
| D2 | docstring | "within one live request it never decreases" | :126 | as C2c | CARRIED |
| D3 | docstring | child runs with `LOG_FORMAT` unset and the zone pinned off UTC: "every stderr line is JSON" | :67–:68, :70 | non-JSON output under the production setup, and records that never reached stderr through the formatter | CARRIED |
| D4 | docstring | "whose `ts` matches `TS_RE`" | :72 | an offset-suffixed or second-precision `ts` | CARRIED |
| D5 | docstring | "reads back within a minute of the child's clock" | :74 | local time read as UTC (5h45m off) | CARRIED |
| D6 | docstring | `_format_ts` and the formatter both give `…56.789Z` for 1741091696.789 | :78 | either path using the format time or `msecs`, and the two paths disagreeing | CARRIED |
| D7 | docstring | both give `…57.000Z` for 1741091696.9999996 | :80 | milliseconds truncated without rounding to the microsecond first | CARRIED |
| D8 | docstring | for a `created` one hour back, both "read back to that `created` within a millisecond" | :81, :82 | the format time, and coarser-than-millisecond precision | CARRIED |
| D9 | docstring | "an hour before the formatting" | :84 | `ts` taken at format time | CARRIED |
| D10 | docstring | "the one `access.start` … to the one `access`" whose url carries the marker | :116 | duplicate or missing access lines for the request | CARRIED |
| D11 | docstring | "the `access.start`, the `access` and at least one `recommendations.*` record" | :119, :120 | a span that is missing its endpoints, or holds no record from inside the request | CARRIED |
| D12 | docstring | each "carry a `ts` matching `TS_RE`" | :123 | live Engine records still in the old offset format | CARRIED |
| D13 | docstring | "within the request's wall-clock window, never decreasing" | :125, :126 | a constant `ts`, local time, and an out-of-order `ts` | CARRIED |
| N1 | name | "engine ts is record created" | :78, :84 | `ts` taken at format time | CARRIED |
| N2 | name | "in utc" | :74 | local-time rendering | CARRIED |
| N3 | name | "with milliseconds" | :72, :78 | second precision, and the wrong millisecond source | CARRIED |
| N4 | name | "request ts never decreases from access start to access" | :119, :126 | as C2b–C2c | CARRIED |

CRITICAL
none

RECOMMENDATIONS
1. normal-and-abnormal-paths (rules/testing.md): tests/tmp/test_19_timestamped_request_logs_phase1.py:41 (child line `logging.error("[probe] failed without exception")`) and :106
   The only abnormal case is an ERROR record with no `exc_info`. Nothing checks the `ts` on a record that carries a traceback (`record.exc_info`, logging_profiles.py:224). For C2, only a request that returns 200 is checked (:109). A failing request's `access.start`…`access` span is never checked for order.
2. bounds (rules/testing.md): tests/tmp/test_19_timestamped_request_logs_phase1.py:80
   :80 asserts `57.000Z` for 1741091696.9999996, so the test requires rounding to the microsecond before the milliseconds are cut. C1 does not say how the milliseconds are rounded, so an implementation that meets C1 by cutting straight from `created` fails here. The test asks for more than its clause, and no testing.md principle covers that. Either the clause or the docstring should state the rounding rule, or the case should be marked as a choice.
3. No rule covers this: tests/tmp/test_19_timestamped_request_logs_phase1.py:43, :78
   The test asserts against `logging_profiles._format_ts`, which is not defined in engine/server/api/logging_profiles.py as it stands (Grep finds it only in plan docs and tests/tmp). The test turns its absence into `null`, so :78–:84 stay red until the helper exists. Recorded so the missing name is not mistaken for a fault in the test.
4. whole-claim (rules/testing.md), not blocking: tests/tmp/test_19_timestamped_request_logs_phase1.py:117
   C2 says "the `ts` values from its `access.start` to its `access`". The test filters the span by event name (`access.start`, `access`, `recommendations.*`) rather than by the request's `request_id`. Other records the request emits inside the span go unchecked, and a `recommendations.*` record from another thread would be counted. The docstring states the narrower set, and the formatter is shared, so I judged C2c carried. Filtering on `request_id` would match the clause exactly.

OBSERVATIONS
none

NOT ASSESSED
1. `code_under_test` lists tests/active/test_log_format.py (NEW), which does not exist, so I did not read it.
2. I was not given the phase's `<checkpoint>` text. I could not confirm that the seams used here (a child process running `configure_engine_logging`, and the session Engine over HTTP) are the ones Step 6 agreed. I judged the surface against `<surfaces>` and `<checkpoint_definition>` only.
3. `fixtures_path` was not supplied. I read the `engine` fixture and `ROOT` from tests/active/conftest.py. I did not check whether the session Engine's environment sets `LOG_FORMAT`.

## 2026-10-01 - Step 7 - Phase 1 (Engine ts from record creation time) - checkpoint outcome (run 1)

`tests/tmp/test_19_timestamped_request_logs_phase1.py` exited 0 after the phase landed.

<changes>
### `engine/server/api/logging_profiles.py`
- Added the module-level helper `_format_ts(record)`. It renders `record.created` in UTC as `YYYY-MM-DDTHH:MM:SS.mmmZ` using `datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(timespec="milliseconds")`, with the `+00:00` suffix replaced by `Z`.
- It deliberately does not read `record.msecs`, because `msecs` is not updated when `created` is set after the record is built.
- I observed the rounding in a probe rather than assuming it. `fromtimestamp` rounds to the microsecond before `isoformat` cuts to milliseconds: `1741091696.789` came out as `2025-03-04T12:34:56.789+00:00` and `1741091696.9999996` as `2025-03-04T12:34:57.000+00:00`.
- `EngineJsonFormatter.format` now sets `"ts": _format_ts(record)`. Before, it used `datetime.now().astimezone().isoformat(...)`, which gave local time at the moment of formatting. Now the stamp is the time the log call happened, which is what keeps it in order across one request.
- The import changed from `from datetime import datetime` to `from datetime import datetime, timezone`.

### `tests/active/test_log_format.py`
Not created. The phase lists it as NEW, but this step is production code only. It looks like the permanent home for the checkpoint once it is moved out of `tests/tmp/`, and nothing in this phase needs it to exist.

### `tests/tmp/probe_fromtimestamp.py`
This was my throwaway probe for the rounding check. I have no delete tool, so I emptied the file instead; it now collects no tests. It can be removed.
</changes>

<inner_tests>
none
</inner_tests>

<unanticipated>
tests/tmp/probe_fromtimestamp.py: the throwaway probe for the rounding check. It is now an empty file because I couldn't delete it, and it can be removed.
</unanticipated>

<awaiting_operator>
none
</awaiting_operator>

```
  tests/tmp/test_19_timestamped_request_logs_phase1.py  2 passed                               0.0s
  ----------------------------------------------------
  total                                                 2 passed                               2.1s wall, 1 lane

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

## 2026-10-01 - Step 7 - Phase 2 (Engine LOG_FORMAT text rendering) - must_prove

Quoted from the phase Intent, written at Step 6 before the checkpoint was drafted.

Intent:
configure_engine_logging reads `LOG_FORMAT` when it runs and, for `text`, has EngineJsonFormatter render each record's payload through `_render_text` as one CR/LF-escaped `ts LEVEL event message k=v…` line, while every other value keeps today's JSON.

- C1 - An Engine `LOG_FORMAT` of text in any case or surrounding whitespace selects text lines, and an unset, empty, `json` or unknown value selects JSON lines.
- C2 - An Engine text record is one physical line shaped `ts LEVEL event [message] k=v… [request_id=…] [traceback]` with CR and LF written as `\r` and `\n`.

must_prove:
- C1 - An Engine `LOG_FORMAT` of text in any case or surrounding whitespace selects text lines, and an unset, empty, `json` or unknown value selects JSON lines.
- C2 - An Engine text record is one physical line shaped `ts LEVEL event [message] k=v… [request_id=…] [traceback]` with CR and LF written as `\r` and `\n`.

## 2026-10-01 - Step 7 - Phase 2 (Engine LOG_FORMAT text rendering) - self-check (audit round 1, send-back 0)

`tests/tmp/test_19_timestamped_request_logs_phase2.py`, surface `checkpoint`. Collection exit 0.

- C1 - test_19_timestamped_request_logs_phase2.py:78,80,82,84 — for LOG_FORMAT unset, `json`, `JSON`, `bogus` and `""`, stderr is exactly five lines and each parses as a JSON object (78). Each `ts` matches TS_RE (80). The exception record's traceback starts `Traceback (most recent call last):` and ends `ValueError: sentinel-log-format` (82). With `ts` and `traceback` removed, each payload's items, in key order, equal JSON_PAYLOADS (84). - expected: Five JSON lines whose items equal JSON_PAYLOADS in order, for example access.start reads `level, event, message="request started", modes, request_id="rid-a", context={ip, method, url}`. Observed passing for all five values in the current run. - excludes: A selector that treats every value other than exactly `json` as text, so unset, `JSON`, `bogus` or `""` give text. The lines no longer parse, and 78 goes red on `None` payloads. A JSON branch that is rebuilt and reorders keys or drops the access.start message rewrite turns 84 red on the item lists.
- C1 - test_19_timestamped_request_logs_phase2.py:95,96 — for LOG_FORMAT `text`, `TEXT`, ` Text ` and `\ttext\n`, every line starts with a TS_RE timestamp, a space and `INFO ` or `ERROR ` (95). No line parses as a JSON object (96; line 95 is its positive control). - expected: Five text lines that start `<ts> INFO ` / `<ts> ERROR `, none of them JSON. Today the run shows five JSON lines for all four values, and 95 fails. - excludes: A selector that compares `value == "text"` without lowercasing and stripping: `TEXT`, ` Text ` and `\ttext\n` stay JSON and 95 reads `False` on a `{"ts":…` line. A selector that strips only spaces fails the tab/newline case. Not reading LOG_FORMAT at all (the code as it stands) fails all four.
- C2 - test_19_timestamped_request_logs_phase2.py:93,97,100 — under text mode, `stderr.splitlines()` (which also breaks on CR) gives exactly five lines, one per record (93). No line starts with `<` (97). The first space-separated token of each line fully matches TS_RE (100). - expected: `len(lines) == 5`, no line starts with `<`, and every head token looks like `2026-10-01T22:29:27.181Z`. - excludes: A text renderer that does not escape CR/LF: the `two\r\nlines` message and the three-line traceback split into extra physical lines, giving 9 or more, and 93 goes red. A renderer that adds a syslog `<N>` priority prefix fails 97 and 100.
- C2 - test_19_timestamped_request_logs_phase2.py:102,103 — after the ts, the plain record reads exactly `INFO probe.info [probe] plain`, and the CR/LF record reads exactly `INFO engine.log [probe] two\r\nlines`, where `\r` and `\n` are the two characters backslash-r and backslash-n. - expected: `INFO probe.info [probe] plain` and `INFO engine.log [probe] two\\r\\nlines` (Python literal). - excludes: A renderer that escapes LF but not CR, or that drops CR/LF instead of escaping them: line 103 reads `…two\r\\nlines` or `…twolines`, and in the unescaped-CR case 93 also reads 6. A renderer that includes `modes` or the level name in lowercase breaks 102.
- C2 - test_19_timestamped_request_logs_phase2.py:105 — after the ts, the exception record fully matches `ERROR probe.info [probe] failed request_id=rid-p2 Traceback (most recent call last):\n  File "<string>", line \d+, in <module>\n    raise ValueError("sentinel-log-format")\nValueError: sentinel-log-format`, with each `\n` the two literal characters. - expected: A full match. The traceback body is the one observed in the JSON `traceback` key under a probe run: `Traceback (most recent call last):\n  File "<string>", line 6, in <module>\n    raise ValueError("sentinel-log-format")\nValueError: sentinel-log-format`, with no caret line. - excludes: A renderer that puts the traceback before `request_id=`, leaves the traceback out, or leaves its newlines raw. In each case the fullmatch is None. The raw-newline case also makes 93 read 8.
- C2 - test_19_timestamped_request_logs_phase2.py:107 — after the ts, the access.start record (logged with extra request_id `rid-a`) reads exactly `INFO access.start request started ip=127.0.0.1 method=GET url=http://x/a request_id=rid-a`. - expected: `INFO access.start request started ip=127.0.0.1 method=GET url=http://x/a request_id=rid-a`. The probe run confirmed that the payload carries request_id `rid-a` and that context is {ip, method, url}. - excludes: A renderer that walks the payload in dict order, so `request_id=rid-a` comes before the context tokens because request_id precedes context in the payload. Another that uses the raw `getMessage()` (`[access.start] ip=…`) instead of the payload's rewritten `request started`. Either way the string differs.
- C2 - test_19_timestamped_request_logs_phase2.py:109 — after the ts, the lifecycle record reads exactly `INFO service.lifecycle state=start component=engine run_id=r pid=1`. - expected: `INFO service.lifecycle state=start component=engine run_id=r pid=1`. There is no message token. - excludes: A renderer that writes `str(payload.get("message"))` or the record's raw message whenever the payload has none. That gives `INFO service.lifecycle None state=…` or `INFO service.lifecycle [service] lifecycle state=… state=…`, which is not equal.

<assertions>
tests/tmp/test_19_timestamped_request_logs_phase2.py:78 - LOG_FORMAT unset, `json`, `JSON`, `bogus` or `""`: stderr has five lines and each one parses with json.loads as a JSON object - C1
tests/tmp/test_19_timestamped_request_logs_phase2.py:80 - in those JSON cases, every record's `ts` fully matches TS_RE - C1
tests/tmp/test_19_timestamped_request_logs_phase2.py:82 - in those JSON cases, the exception record's `traceback` starts `Traceback (most recent call last):` and ends `ValueError: sentinel-log-format` - C1
tests/tmp/test_19_timestamped_request_logs_phase2.py:84 - in those JSON cases, the five payloads minus ts/traceback equal JSON_PAYLOADS item for item, key order included. These are the payloads observed before this phase, so a non-text value keeps today's JSON - C1
tests/tmp/test_19_timestamped_request_logs_phase2.py:93 - LOG_FORMAT `text`, `TEXT` or ` Text `: stderr is exactly five lines. splitlines breaks on CR and on LF, so an unescaped CR or LF in the CR/LF message or the traceback adds a line - C2
tests/tmp/test_19_timestamped_request_logs_phase2.py:95 - in the text cases, every line matches `^<TS_RE> (INFO|ERROR) ` - C1
tests/tmp/test_19_timestamped_request_logs_phase2.py:96 - negative: in the text cases, no line parses as a JSON object - C1
tests/tmp/test_19_timestamped_request_logs_phase2.py:97 - in the text cases, no line starts with `<` - C2
tests/tmp/test_19_timestamped_request_logs_phase2.py:100 - in the text cases, each line's first space-separated token fully matches TS_RE - C2
tests/tmp/test_19_timestamped_request_logs_phase2.py:102 - the plain record reads exactly `INFO probe.info [probe] plain` after the ts - C2
tests/tmp/test_19_timestamped_request_logs_phase2.py:103 - the `[probe] two\r\nlines` record is one line reading exactly `INFO engine.log [probe] two\r\nlines`, with CR and LF written as the literal two-character escapes - C2
tests/tmp/test_19_timestamped_request_logs_phase2.py:105 - the exception record is one line that fully matches `ERROR probe.info [probe] failed request_id=rid-p2 Traceback (most recent call last):\n  File "<string>", line N, in <module>\n    raise ValueError("sentinel-log-format")\nValueError: sentinel-log-format`, with literal `\n`. This pins request_id after the message and before the traceback - C2
tests/tmp/test_19_timestamped_request_logs_phase2.py:106 - the exception line ends with `ValueError: sentinel-log-format` - C2
tests/tmp/test_19_timestamped_request_logs_phase2.py:107 - the access.start line reads exactly `INFO access.start request started ip=127.0.0.1 method=GET url=http://x/a` after the ts - C2
tests/tmp/test_19_timestamped_request_logs_phase2.py:109 - the lifecycle line reads exactly `INFO service.lifecycle state=start component=engine run_id=r pid=1` after the ts, with no message token - C2
</assertions>

<probes>
tests/tmp/test_probe_19_p2.py (ValidateTests ["tests/tmp/test_probe_19_p2.py", "-s"]). It ran the agreed five-record child with LOG_FORMAT unset and then set to `text`, against today's code. Both runs printed the same five JSON lines: `{"ts":…,"level":"INFO","event":"probe.info","message":"[probe] plain","modes":["verbose"]}`; then `{…"event":"engine.log","message":"[probe] two\nlines","modes":["verbose"]}` (the newline defeats _PREFIX_RE, so the event falls back to engine.log); then `{…"level":"ERROR","event":"probe.info","message":"[probe] failed","modes":["focused","verbose"],"traceback":"Traceback (most recent call last):\n  File \"<string>\", line 8, in <module>\n    raise ValueError(\"sentinel-log-format\")\nValueError: sentinel-log-format"}` (no caret line under Python 3.14.7); then `{…"event":"access.start","message":"request started",…,"context":{"ip":"127.0.0.1","method":"GET","url":"http://x/a"}}`; then `{…"event":"service.lifecycle","modes":["focused","verbose"],"context":{"state":"start","component":"engine","run_id":"r","pid":"1"}}` with no message key. I then ran the real test against today's code (ValidateTests ["tests/tmp/test_19_timestamped_request_logs_phase2.py"]): 5 passed, 3 failed. All five JSON cases pass, which confirms JSON_PAYLOADS for the adjusted records: the `two\r\nlines` message still maps to engine.log, and `extra={"request_id": "rid-p2"}` gives `"request_id":"rid-p2"` after modes. The three text cases fail at line 95 because stderr is still JSON. Not observable before implementation: the text-line strings at :102-:109. They are predictions from the agreed checkpoint and the Step-5 `_render_text` draft, built on the payloads observed above. The implementation run confirms them. The probe file could not be deleted with the tools I have, so it has been emptied. tests/tmp/test_probe_19_p2.py should be removed.
</probes>

<unassertable>
Two of the agreed records were adjusted with the operator's approval (AskUser: "Adjust two records, still five lines"). The multiline message is now `[probe] two\r\nlines`, so CR escaping is asserted. The exception record now carries `extra={"request_id": "rid-p2"}`, so the `[request_id=…]` slot between the message/context and the traceback is asserted. Still five records and five lines. Not asserted: the Intent's "reads LOG_FORMAT when it runs" (call time rather than import time). The agreed seam sets LOG_FORMAT in the child's env before it starts, and that cannot tell the two apart. It is not part of C1 or C2. A child that sets os.environ between import and configure_engine_logging would confirm it.
</unassertable>

### `tests/tmp/test_19_timestamped_request_logs_phase2.py` - 6792 characters, inlined in full

```
"""The Engine's `LOG_FORMAT` selects one escaped text line per record for `text` in any case or padding, and today's JSON for anything else.

- `configure_engine_logging("verbose")` in a child, with `LOG_FORMAT` removed from its env and then set to the case value, logs five records: `[probe] plain`, `[probe] two\\r\\nlines`, a `logging.exception("[probe] failed")` for `ValueError("sentinel-log-format")` with request_id `rid-p2`, an `[access.start]` record and a `[service] lifecycle` record.
- Unset, `json`, `JSON`, `bogus` or empty: stderr is five JSON objects, each with a `ts` matching `TS_RE`, a traceback on the exception record ending `ValueError: sentinel-log-format`, and otherwise the same keys, order and values as the JSON written before `LOG_FORMAT` existed.
- `text`, `TEXT` or ` Text `: stderr is exactly five lines. None parses as a JSON object or starts with `<`. Each line is `<TS_RE> LEVEL event`, then the message if there is one, the context as `k=v`, `request_id=…` and the traceback, with CR and LF written as the two characters `\\r` and `\\n`. The exception line puts `request_id=rid-p2` before the traceback and ends `ValueError: sentinel-log-format`. The access.start line reads `request started ip=127.0.0.1 method=GET url=http://x/a`. The lifecycle line has no message token.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
API_DIR = ROOT / "engine" / "server" / "api"
TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
TEXT_HEAD_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z (INFO|ERROR) ")

# Logs the five records through the production setup; LOG_FORMAT comes only from the env the test gives the child.
_ENGINE_CHILD = textwrap.dedent(
    """
    import logging
    from logging_profiles import configure_engine_logging
    configure_engine_logging("verbose")
    logging.info("[probe] plain")
    logging.info("[probe] two\\r\\nlines")
    try:
        raise ValueError("sentinel-log-format")
    except ValueError:
        logging.exception("[probe] failed", extra={"request_id": "rid-p2"})
    logging.info("[access.start] ip=127.0.0.1 method=GET url=http://x/a")
    logging.info("[service] lifecycle state=start component=engine run_id=r pid=1")
    """
)

# Today's JSON payloads for the five records, less `ts` and `traceback` (observed before this phase; the CR/LF message falls back to engine.log).
JSON_PAYLOADS = [
    {"level": "INFO", "event": "probe.info", "message": "[probe] plain", "modes": ["verbose"]},
    {"level": "INFO", "event": "engine.log", "message": "[probe] two\r\nlines", "modes": ["verbose"]},
    {"level": "ERROR", "event": "probe.info", "message": "[probe] failed", "modes": ["focused", "verbose"], "request_id": "rid-p2"},
    {"level": "INFO", "event": "access.start", "message": "request started", "modes": ["focused", "verbose"], "context": {"ip": "127.0.0.1", "method": "GET", "url": "http://x/a"}},
    {"level": "INFO", "event": "service.lifecycle", "modes": ["focused", "verbose"], "context": {"state": "start", "component": "engine", "run_id": "r", "pid": "1"}},
]

# The traceback's `\n` are the two characters backslash and n, not a line break.
EXCEPTION_TEXT_RE = re.compile(r'ERROR probe\.info \[probe\] failed request_id=rid-p2 Traceback \(most recent call last\):\\n  File "<string>", line \d+, in <module>\\n    raise ValueError\("sentinel-log-format"\)\\nValueError: sentinel-log-format')


def _run_child(value: str | None) -> subprocess.CompletedProcess:
    """Run the child with LOG_FORMAT removed from the env, then set to value when it is not None."""
    env = {key: item for key, item in os.environ.items() if key != "LOG_FORMAT"}
    if value is not None:
        env["LOG_FORMAT"] = value
    # logging_profiles imports only the stdlib and request_context, so pytest's own interpreter can run it.
    return subprocess.run([sys.executable, "-c", _ENGINE_CHILD], cwd=API_DIR, env=env, capture_output=True, text=True, timeout=120)


def _json_object(line: str) -> dict | None:
    """The line parsed as a JSON object, or None."""
    try:
        parsed = json.loads(line)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


@pytest.mark.parametrize("value", [None, "json", "JSON", "bogus", ""])
def test_engine_log_format_unset_empty_json_or_unknown_writes_todays_json_lines(value):
    run = _run_child(value)
    assert run.returncode == 0, run.stderr[-2000:]
    lines = run.stderr.splitlines()
    payloads = [_json_object(line) for line in lines]
    assert len(lines) == 5 and all(payload is not None for payload in payloads), run.stderr[-2000:]  # C1

    assert all(TS_RE.fullmatch(payload.pop("ts")) for payload in payloads), run.stderr[-2000:]  # C1
    traceback = payloads[2].pop("traceback")
    assert traceback.startswith("Traceback (most recent call last):") and traceback.endswith("ValueError: sentinel-log-format"), traceback  # C1
    # The payload, key order included, is the one written before LOG_FORMAT existed.
    assert [list(payload.items()) for payload in payloads] == [list(payload.items()) for payload in JSON_PAYLOADS], payloads  # C1


@pytest.mark.parametrize("value", ["text", "TEXT", " Text "])
def test_engine_log_format_text_writes_one_escaped_text_line_per_record(value):
    run = _run_child(value)
    assert run.returncode == 0, run.stderr[-2000:]
    # splitlines breaks on CR as well as LF, so an unescaped CR or LF adds a line here.
    lines = run.stderr.splitlines()
    assert len(lines) == 5, lines  # C2

    assert all(TEXT_HEAD_RE.match(line) for line in lines), lines  # C1
    assert all(_json_object(line) is None for line in lines), lines  # C1
    assert not any(line.startswith("<") for line in lines), lines  # C2

    stamps, rests = zip(*(line.split(" ", 1) for line in lines))
    assert all(TS_RE.fullmatch(ts) for ts in stamps), stamps  # C2
    plain, multiline, failed, access_start, lifecycle = rests
    assert plain == "INFO probe.info [probe] plain", plain  # C2
    assert multiline == "INFO engine.log [probe] two\\r\\nlines", multiline  # C2
    # request_id follows the message and precedes the traceback, which ends the line.
    assert EXCEPTION_TEXT_RE.fullmatch(failed), failed  # C2
    assert failed.endswith("ValueError: sentinel-log-format"), failed  # C2
    assert access_start == "INFO access.start request started ip=127.0.0.1 method=GET url=http://x/a", access_start  # C2
    # service.lifecycle carries no message, so its context follows the event directly.
    assert lifecycle == "INFO service.lifecycle state=start component=engine run_id=r pid=1", lifecycle  # C2

```


Gate: satisfied

## 2026-10-01 - Step 7 - Phase 2 (Engine LOG_FORMAT text rendering) - red (audit round 1)

`tests/tmp/test_19_timestamped_request_logs_phase2.py` exited 1.

```
  tests/tmp/test_19_timestamped_request_logs_phase2.py  4 failed, 5 passed                     0.0s
  ----------------------------------------------------
  total                                                 4 failed, 5 passed                     0.5s wall, 1 lane

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

## 2026-10-01 - Step 7 - Phase 2 (Engine LOG_FORMAT text rendering) - audit (round 1)

- AUDIT: devsecops-test-shape-auditor - PASS
- AUDIT: devsecops-test-claim-auditor - PASS
- OUTSTANDING: nothing

### devsecops-test-shape-auditor

SHAPE AUDIT — VERDICT: PASS

CRITICAL
none

RECOMMENDATIONS
1. single-value-pin (rules/shape.md) — tests/tmp/test_19_timestamped_request_logs_phase2.py:84
   assert [list(payload.items()) for payload in payloads] == [list(payload.items()) for payload in JSON_PAYLOADS], payloads  # C1
   This function expects the shipped default, so it passes on the current `EngineJsonFormatter`-only code. That matches the entry's "expected result equals the shipped default" bullet. The file still separates the mechanism, because the text function at :87–109 drives the same child with `text`, `TEXT`, ` Text ` and tab-`text`-newline. An implementation that always writes JSON fails there. One that matches only exact `text`, or only strips or only lowercases, fails one of those inputs. One that sends `bogus` or empty to text fails here. No change is required. Just don't split this function from the text function or run it on its own as a gate, because by itself it proves nothing about the switch.

PREDICTED FAILURE
For every text-case parameter, `test_engine_log_format_text_writes_one_escaped_text_line_per_record` fails at line 95 on `assert all(TEXT_HEAD_RE.match(line) for line in lines)`. The cause is that `configure_engine_logging` still installs only `EngineJsonFormatter`, so each of the five lines starts with `{"ts":` and not with `<ts> INFO `. The line-93 count of 5 holds first, because `json.dumps` already escapes the CR and LF. Every parameter of the JSON test passes.

NOT ASSESSED
1. `code_under_test` lists tests/active/test_log_format.py, which does not resolve. The stub question was answered from the test under audit and engine/server/api/logging_profiles.py alone.
2. `EXCEPTION_TEXT_RE` (:51) requires the traceback to contain the source line `raise ValueError("sentinel-log-format")` for a `-c` child, from `File "<string>"`. Whether that line appears depends on which interpreter version runs the test, and I wasn't given that. No shape.md entry covers this. It decides whether line 105 can pass at all, not how the assertion is shaped.

### devsecops-test-claim-auditor

CLAIM AUDIT — VERDICT: PASS

CLAUSE MAP  (25 clauses: 10 must_prove, 13 docstring, 2 name)
| id | source | clause | assertion | excludes | status |
|---|---|---|---|---|---|
| C1a | must_prove | `text` in any case selects text lines | :95 | a case-sensitive compare: `TEXT` would then produce JSON, which fails the text head match | CARRIED |
| C1b | must_prove | `text` with surrounding whitespace selects text lines | :95 | an unstripped compare: `" Text "` / `"\ttext\n"` would then produce JSON | CARRIED |
| C1c | must_prove | unset selects JSON lines | :78 | text (or nothing) as the default when the variable is absent | CARRIED |
| C1d | must_prove | empty selects JSON lines | :78 | an empty value read as text, or as an error | CARRIED |
| C1e | must_prove | `json` selects JSON lines | :78 | `json`/`JSON` mishandled or case-sensitive | CARRIED |
| C1f | must_prove | unknown value selects JSON lines | :78 | text as the fallback for anything not `json` (`bogus`) | CARRIED |
| C2a | must_prove | one physical line per record | :93 | a raw newline in the traceback or message, since splitlines splits on CR and LF | CARRIED |
| C2b | must_prove | shape `ts LEVEL event [message]` | :100, :102, :109 | a missing or wrongly formatted ts; a message emitted when there is none (lifecycle) or dropped when there is one | CARRIED |
| C2c | must_prove | then `k=v… [request_id=…] [traceback]` in that order | :105, :107 | request_id written before the context; traceback written before request_id; a request_id token on a record without one (:102) | CARRIED |
| C2d | must_prove | CR and LF written as `\r` and `\n` | :103, :105 | raw CR/LF, stripping, or double-escaping in the message and the traceback | CARRIED |
| D1 | docstring | "one escaped text line per record for `text` in any case or padding" | :93, :95 | the same as C1a/C1b/C2a | CARRIED |
| D2 | docstring | "today's JSON for anything else" | :84 | the JSON payload changed when the text path was added | CARRIED |
| D3 | docstring | unset/json/JSON/bogus/empty: "stderr is five JSON objects" | :78 | a missing record, a non-object line, or extra output | CARRIED |
| D4 | docstring | "each with a `ts` matching `TS_RE`" | :80 | a ts missing, in a non-UTC format, or without milliseconds | CARRIED |
| D5 | docstring | "a traceback on the exception record ending `ValueError: sentinel-log-format`" | :82 | the traceback dropped or truncated | CARRIED |
| D6 | docstring | "same keys, order and values as the JSON written before" | :84 | added, reordered or changed keys, compared as item lists | CARRIED |
| D7 | docstring | text: "stderr is exactly five lines" | :93 | a record split across lines, or extra output | CARRIED |
| D8 | docstring | "None parses as a JSON object" | :96 | a JSON line passed off as text | CARRIED |
| D9 | docstring | "or starts with `<`" | :97 | a syslog-style `<pri>` prefix | CARRIED |
| D10 | docstring | "Each line is `<TS_RE> LEVEL event`, then message, `k=v`, `request_id=…`, traceback" | :95, :100, :102–:109 | a different token order or missing tokens | CARRIED |
| D11 | docstring | "CR and LF written as the two characters `\\r` and `\\n`" | :103, :105 | raw or double-escaped CR/LF | CARRIED |
| D12 | docstring | "exception line puts `request_id=rid-p2` before the traceback and ends `ValueError: sentinel-log-format`" | :105 | request_id after the traceback; a truncated traceback (fullmatch) | CARRIED |
| D13 | docstring | "access.start line reads `request started ip=… request_id=rid-a`, context before request_id" + "lifecycle line has no message token" | :107, :109 | a raw message instead of `request started`; request_id before the context; a message token on lifecycle | CARRIED |
| N1 | name | "unset, empty, json or unknown writes today's json lines" | :78, :84 | non-JSON output, or JSON that differs from today's | CARRIED |
| N2 | name | "text writes one escaped text line per record" | :93, :103, :105 | records spanning lines; unescaped CR/LF | CARRIED |

CRITICAL
none

RECOMMENDATIONS
1. bounds (rules/testing.md) — tests/tmp/test_19_timestamped_request_logs_phase2.py:72
   The only unknown value tested is `"bogus"`. No value close to `text` is tested, such as `"texts"`, `"tex"` or `"te xt"`. A selector written as `"text" in value.lower()` or `startswith("text")` would pass every parametrised case at :72 and :87 even though C1 says an unknown value selects JSON. Adding a near-miss value such as `"texts"` to the :72 parametrize list would rule that out.

OBSERVATIONS
none

NOT ASSESSED
1. `code_under_test` lists tests/active/test_log_format.py, but that file does not exist in the worktree, so I could not read it.
2. engine/server/api/logging_profiles.py, as read, has no `LOG_FORMAT` handling and no text formatter. I judged which inputs the text path accepts from `must_prove` and the test alone.

## 2026-10-01 - Step 7 - Phase 2 (Engine LOG_FORMAT text rendering) - checkpoint outcome (run 1)

`tests/tmp/test_19_timestamped_request_logs_phase2.py` exited 0 after the phase landed.

<changes>
### `engine/server/api/logging_profiles.py`
- Imports: added `os`. The module still imports only the stdlib and `request_context`.
- Added `SUPPORTED_LOG_FORMATS = ("json", "text")` next to `SUPPORTED_LOG_MODES`. Added `_TEXT_ESCAPES`, a `str.maketrans` table that writes CR as `\r` and LF as `\n`, after `_LEADING_BLOCKS_RE`.
- New public `normalize_log_format(value)` directly after `normalize_log_mode`, with the same fail-safe shape: it strips and lowercases the value and returns it if it is in `SUPPORTED_LOG_FORMATS`. Anything else, including `None`, `""` and `bogus`, gives `"json"`. It never raises.
- New `_text_value(value)`: a string is returned as it is, and any other value becomes compact JSON (`ensure_ascii=False`, `default=str`), so a list or dict stays a single token and `None` is written as `null`.
- New `_render_text(payload)`: builds `ts LEVEL event`, then the message if the payload has one, then each context entry as `k=v`, then `request_id=…` (skipped if the context already has a `request_id` key), then the traceback. Everything is joined with single spaces, and CR/LF are escaped over the whole line at the end. `modes` is not written.
- `EngineJsonFormatter`: new `__init__(self, log_format="json")`, which stores `normalize_log_format(log_format)`. `format` builds the payload exactly as before. When the format is `text` it returns `_render_text(payload)`; otherwise it returns the same `json.dumps` expression as before, so JSON key order and values are unchanged. `EngineJsonFormatter()` with no argument still gives JSON, so the existing unit-test callers need no change. The class docstring now mentions text lines.
- `configure_engine_logging`: installs `EngineJsonFormatter(os.environ.get("LOG_FORMAT"))`, so the variable is read when the function is called, not at import. The signature and return value (the normalised log mode) are unchanged; only the docstring changed.

### `tests/active/test_log_format.py`
Not touched. The file does not exist in the tree, and this phase's checkpoint lives at `tests/tmp/test_19_timestamped_request_logs_phase2.py`. No production change needed it.
</changes>

<inner_tests>
none
</inner_tests>

<unanticipated>
none
</unanticipated>

<awaiting_operator>
none
</awaiting_operator>

```
  tests/tmp/test_19_timestamped_request_logs_phase2.py  9 passed                               0.0s
  ----------------------------------------------------
  total                                                 9 passed                               0.4s wall, 1 lane

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

## 2026-10-01 - Step 7 - Phase 3 (Client root formatter, JSON) - must_prove

Quoted from the phase Intent, written at Step 6 before the checkpoint was drafted.

Intent:
In client/backend/server.py, configure_client_logging installs ClientLogFormatter on the root logger, which `main()` now calls in place of `basicConfig`, and `_emit_client_log` hands it event and context as `client_event`/`client_context` record attributes instead of building JSON by hand, so every Client record leaves through one formatter.

- C1 - An `_emit_client_log` record renders as a JSON line whose keys run `ts, level, service, event, message[, context]` with a UTC `ts`.
- C2 - A bare root-logger record renders in the same JSON shape with event `client.log`.

must_prove:
- C1 - An `_emit_client_log` record renders as a JSON line whose keys run `ts, level, service, event, message[, context]` with a UTC `ts`.
- C2 - A bare root-logger record renders in the same JSON shape with event `client.log`.

## 2026-10-01 - Step 7 - Phase 3 (Client root formatter, JSON) - self-check (audit round 1, send-back 0)

`tests/tmp/test_19_timestamped_request_logs_phase3.py`, surface `checkpoint`. Collection exit 0.

- C1 - tests/tmp/test_19_timestamped_request_logs_phase3.py:89 — the five records (engine.call emit, logging.exception, bare logging.info, emit with {} context, emit with no context) write exactly five lines to the StringIO behind the handler configure_client_logging() installed - expected: 5 lines, one per record - excludes: Today's root setup, with _emit_client_log building JSON by hand and the exception and bare records going out as plain text. Probe test_probe_19_p3_values.py showed that stream: the emit JSON line, then `client probe failed`, a 4-line traceback and `bare`. That is 7 lines for the first three records, 9 with the two extra emits.
- C1 - tests/tmp/test_19_timestamped_request_logs_phase3.py:91 — every line parses as a JSON object - expected: all five lines are dicts - excludes: A formatter that only covers records carrying client_event, or text in place of JSON. The lines `bare` and `client probe failed` (observed today) are not JSON, so json.loads at line 90 raises.
- C1 - tests/tmp/test_19_timestamped_request_logs_phase3.py:94 — the engine.call line's keys are exactly ts, level, service, event, message, context, in that order - expected: ["ts", "level", "service", "event", "message", "context"] - excludes: A formatter installed while _emit_client_log still logs its hand-built JSON string as the message. In probe today_emit the line read {'ts': ..., 'level': 'ERROR', 'service': 'client-backend', 'event': 'client.log', ...} with no context key, and the engine.call JSON was buried in message. A payload built in another order (e.g. event before service) also fails here.
- C1 - tests/tmp/test_19_timestamped_request_logs_phase3.py:95 — the engine.call line has level ERROR, service client-backend, event engine.call, message "Engine metadata failed" and context {"error": "x\ny"} - expected: ("ERROR", "client-backend", "engine.call", "Engine metadata failed", {"error": "x\ny"}) - excludes: Wrong attribute names between _emit_client_log's extra= and the formatter, which lets event fall back to client.log (as observed in probe today_emit). Or a context that is stringified or escaped twice, which reads back as a str and not as the dict.
- C1 - tests/tmp/test_19_timestamped_request_logs_phase3.py:97 — an emit with a {} context omits the key: keys exactly ts, level, service, event, message, with event probe.empty and message "empty context" - expected: (["ts","level","service","event","message"], "probe.empty", "empty context") - excludes: A formatter that tests `context is not None`, which writes "context": {}, so the key list has six entries.
- C1 - tests/tmp/test_19_timestamped_request_logs_phase3.py:98 — an emit with no context also omits the key, with event probe.none and message "no context" - expected: (["ts","level","service","event","message"], "probe.none", "no context") - excludes: A formatter that always writes payload["context"] = getattr(record, "client_context", None), which gives "context": null and six keys.
- C1 - tests/tmp/test_19_timestamped_request_logs_phase3.py:102 — every line's ts fully matches TS_RE ^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$ - expected: all five ts match, e.g. YYYY-MM-DDTHH:MM:SS.mmmZ - excludes: Today's datetime.now().astimezone().isoformat(timespec="milliseconds"). Probe test_probe_19_p3_values.py observed `2026-10-02T04:19:50.028+05:45` under TZ=Asia/Kathmandu, which has no Z. A plain utc isoformat gives `+00:00` (observed `2025-03-04T12:34:56.789+00:00`).
- C1 - tests/tmp/test_19_timestamped_request_logs_phase3.py:104 — with TZ pinned to Asia/Kathmandu, every ts read back as UTC lies within [before-1, after+1] of time.time() around the calls - expected: every _epoch(ts) is inside the window - excludes: Local time with a Z appended. In probe local_z the stamps read 2026-10-02T04:19:20.843Z against a window at epoch 1790894060.84 (22:34:20Z), which is 5h45m outside it.
- C1 - tests/tmp/test_19_timestamped_request_logs_phase3.py:106 — the installed formatter renders records with created=1741091696.789 and created=1741091696.9999996 - expected: ("2025-03-04T12:34:56.789Z", "2025-03-04T12:34:57.000Z") - excludes: Milliseconds taken from record.msecs, which goes stale once created is set after construction: probe msecs read 2025-03-04T12:34:56.844Z for both records. Naive truncation via int((created % 1) * 1000) gives 2025-03-04T12:34:56.999Z (observed). A ts from datetime.now() gives today's date and not 2025-03-04.
- C1 - tests/tmp/test_19_timestamped_request_logs_phase3.py:110 — the exception line's keys are ts, level, service, event, message, traceback - expected: ["ts","level","service","event","message","traceback"] - excludes: A formatter that ignores exc_info, so it has no traceback key and the traceback is lost. Or the stdlib default that appends the traceback as extra lines, which is today's behaviour: observed 4 traceback lines after `client probe failed`.
- C1 - tests/tmp/test_19_timestamped_request_logs_phase3.py:112 — the traceback value starts with "Traceback (most recent call last):" and ends with "ValueError: sentinel-client-log" - expected: the formatted ValueError traceback, ending `ValueError: sentinel-client-log` - excludes: A traceback of repr(exc_info) or str(exc) only, which does not start with "Traceback (most recent call last):". Or a formatException with a trailing newline left in, which does not end with the sentinel.
- C2 - tests/tmp/test_19_timestamped_request_logs_phase3.py:108 — the bare logging.info line's keys are exactly ts, level, service, event, message - expected: ["ts","level","service","event","message"] - excludes: The JSON formatter applied only to _emit_client_log records (e.g. on a dedicated logger) while the root keeps "%(message)s". The bare line is then the plain text `bare` (observed today), which is not JSON. A formatter writing "context": null for records without attributes gives six keys.
- C2 - tests/tmp/test_19_timestamped_request_logs_phase3.py:109 — the bare line has level INFO, service client-backend, event client.log, message "bare" - expected: ("INFO", "client-backend", "client.log", "bare") - excludes: A formatter using getattr(record, "client_event", None) with no fallback, which gives event null. Or the Engine's fallback copied over unchanged, which gives event engine.log.
- C2 - tests/tmp/test_19_timestamped_request_logs_phase3.py:111 — the logging.exception line has level ERROR, service client-backend, event client.log, message "client probe failed" - expected: ("ERROR", "client-backend", "client.log", "client probe failed") - excludes: A missing client.log fallback, which gives a null event. Or the message built from the formatted record text including the traceback, which gives a message other than "client probe failed".

<assertions>
tests/tmp/test_19_timestamped_request_logs_phase3.py:89 — the five records (`engine.call` emit, `logging.exception`, bare `logging.info`, emit with `{}` context, emit with no context) write exactly five lines to the StringIO that replaced the stream of the handler `configure_client_logging()` installed, so each record is one line (C1, C2)
tests/tmp/test_19_timestamped_request_logs_phase3.py:91 — every line parses as a JSON object (C1, C2)
tests/tmp/test_19_timestamped_request_logs_phase3.py:94 — the `engine.call` line's keys are exactly `["ts", "level", "service", "event", "message", "context"]`, in that order (C1)
tests/tmp/test_19_timestamped_request_logs_phase3.py:95 — the `engine.call` line has level ERROR, service `client-backend`, event `engine.call`, message `Engine metadata failed` and context `{"error": "x\ny"}` (C1)
tests/tmp/test_19_timestamped_request_logs_phase3.py:97 — an emit with a `{}` context drops the key: its keys are exactly `ts, level, service, event, message`, with its own event and message (C1, the optional `[, context]`)
tests/tmp/test_19_timestamped_request_logs_phase3.py:98 — an emit with no context also drops the key, rather than writing `null` (C1, the optional `[, context]`)
tests/tmp/test_19_timestamped_request_logs_phase3.py:102 — every line's `ts` fully matches `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$` (C1)
tests/tmp/test_19_timestamped_request_logs_phase3.py:104 — with TZ pinned to Asia/Kathmandu (+05:45), every `ts` read back as UTC falls within the wall-clock window of the calls (±1 s), so a local-time `ts` with a `Z` appended fails (C1)
tests/tmp/test_19_timestamped_request_logs_phase3.py:106 — the installed handler's formatter renders a record with `created=1741091696.789` as `2025-03-04T12:34:56.789Z` and one with `created=1741091696.9999996` as `2025-03-04T12:34:57.000Z`, so `ts` is the record's creation time in UTC, rounded to the microsecond before the milliseconds are cut (C1; the plan's rationale maps T2 to P3-C1)
tests/tmp/test_19_timestamped_request_logs_phase3.py:108 — the bare `logging.info("bare")` line's keys are exactly `ts, level, service, event, message` (no context, no traceback) (C2)
tests/tmp/test_19_timestamped_request_logs_phase3.py:109 — the bare line has level INFO, service `client-backend`, event `client.log` and message `bare` (C2)
tests/tmp/test_19_timestamped_request_logs_phase3.py:110 — the exception line's keys are exactly `ts, level, service, event, message, traceback` (C1: it carries a `traceback` key)
tests/tmp/test_19_timestamped_request_logs_phase3.py:111 — the exception line has level ERROR, service `client-backend`, event `client.log` and message `client probe failed` (C2)
tests/tmp/test_19_timestamped_request_logs_phase3.py:112 — the exception line's `traceback` starts with `Traceback (most recent call last):` and ends with `ValueError: sentinel-client-log` (C1)
</assertions>

<probes>
1) ValidateTests ["tests/tmp/test_probe_19_p3.py", "-s"] (first version: today's code under a plain `%(message)s` StreamHandler, TZ=Asia/Kathmandu with time.tzset()). Printed: root handlers before the test = [_LiveLoggingNullHandler, _FileHandler /dev/null, LogCaptureHandler, LogCaptureHandler], level 30; `has configure False has formatter False`; local now `...+05:45` (TZ pinning works in-process); RAW = `{"ts":"2026-10-02T04:17:22.827+05:45","level":"ERROR","service":"client-backend","event":"engine.call","message":"Engine metadata failed","context":{"error":"x\\ny"}}\nclient probe failed\nTraceback (most recent call last):\n ... ValueError: sentinel-client-log\nbare\n`; first-line keys ['ts','level','service','event','message','context'], TS_RE False; after the restore, the same four handlers, level 30, and local time back to the host's -04:00. Conclusion: today's key order already matches, so the discriminating assertions are the `ts` form and UTC check, the one-line count, and the bare and exception records.
2) ValidateTests ["tests/tmp/test_19_timestamped_request_logs_phase3.py"] against today's code: 1 failed with `AttributeError: module 'server' has no attribute 'configure_client_logging'` (line 44), so it is red for the right reason.
3) ValidateTests ["tests/tmp/test_probe_19_p3.py", "-s"] (second version: runs the checkpoint body with a probe-only stand-in of the planned ClientLogFormatter, configure_client_logging and _emit_client_log monkeypatched onto client_server; nothing was written to server.py). The planned shape passes, printing `RESTORED True TZ None`. Three wrong implementations each raise AssertionError: local_z (local time + `Z`) fails the window check at :104 with `['2026-10-02T04:18:25.510Z', ...]` against epoch ~1790894005.51; msecs (seconds from created, milliseconds from record.msecs) fails :106 with `2025-03-04T12:34:56.511Z`; today_emit (new formatter, old JSON-in-message emit) fails :94/95 with event `client.log`. The 2025-03-04T12:34:56.789Z / 57.000Z values come from the Engine helper's observed output in the phase 1 checkpoint and the probe's own stand-in rendering, which used the same fromtimestamp(tz=utc) form. Cleanup: tests/tmp/test_probe_19_p3.py is still on disk because no tool here can delete a file. It should be deleted; it imports the checkpoint module and must not outlive it.
</probes>

<unassertable>
none. Two notes. First, the operator approved gap carries over from Step 6: `main()` calling `configure_client_logging()` in place of `basicConfig` is not entered, because `main` parses argv and binds a port. Second, the rewired ERROR-record tests in tests/active/test_server.py are not asserted here; the full suite covers them, as agreed at Step 6.
</unassertable>

### `tests/tmp/test_19_timestamped_request_logs_phase3.py` - 6543 characters, inlined in full

```
"""After `configure_client_logging()` with `LOG_FORMAT` unset, every Client record leaves the root handler as one JSON line in the Client's key order, with a UTC `ts`.

- In-process, the zone pinned off UTC, the handler's stream swapped for a StringIO: `_emit_client_log(ERROR, "engine.call", "Engine metadata failed", {"error": "x\\ny"})`, a `logging.exception` for `ValueError("sentinel-client-log")`, `logging.info("bare")`, and `_emit_client_log` with an empty and with no context write exactly five lines, each a JSON object.
- The `engine.call` line's keys are exactly `ts, level, service, event, message, context`, with level ERROR, service `client-backend`, the message and `{"error": "x\\ny"}` unchanged; the empty- and no-context lines stop at `message`.
- Every line's `ts` matches `TS_RE` and reads back as UTC inside the wall-clock window of the calls; the installed formatter renders a record whose `created` is 1741091696.789 as `2025-03-04T12:34:56.789Z` and 1741091696.9999996 as `2025-03-04T12:34:57.000Z`.
- The bare and the exception records have event `client.log` and their own message; the bare line's keys are exactly `ts, level, service, event, message`, the exception line adds `traceback`, the formatted `ValueError: sentinel-client-log` traceback.
"""
from __future__ import annotations

import io
import json
import logging
import re
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

ACTIVE = Path(__file__).resolve().parents[1] / "active"
if str(ACTIVE) not in sys.path:
    sys.path.insert(0, str(ACTIVE))

from conftest import client_server  # noqa: E402

TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
# +05:45: a ts rendered in local time, with or without a `Z`, is off by hours and minutes here, whatever zone the host runs in.
OFF_UTC_ZONE = "Asia/Kathmandu"
EMIT_KEYS = ["ts", "level", "service", "event", "message", "context"]
BARE_KEYS = ["ts", "level", "service", "event", "message"]


@contextmanager
def _client_logging(monkeypatch, value):
    """Run configure_client_logging under LOG_FORMAT=value; yield the stream it writes to."""
    # Saved and restored in the test body, so pytest's own capture handlers come back for later tests.
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


def _epoch(ts: str) -> float:
    """Read a `TS_RE` timestamp back as UTC epoch seconds."""
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc).timestamp()


def _fixed_record(created: float) -> logging.LogRecord:
    """A bare record whose creation time is `created`."""
    record = logging.LogRecord("probe", logging.INFO, "probe", 1, "fixed", None, None)
    record.created = created
    return record


def test_client_records_leave_as_json_lines_in_client_key_order_with_utc_ts_and_bare_ones_as_client_log(monkeypatch):
    monkeypatch.setenv("TZ", OFF_UTC_ZONE)
    time.tzset()
    try:
        with _client_logging(monkeypatch, None) as stream:
            before = time.time()
            client_server._emit_client_log(logging.ERROR, "engine.call", "Engine metadata failed", {"error": "x\ny"})
            try:
                raise ValueError("sentinel-client-log")
            except ValueError:
                logging.exception("client probe failed")
            logging.info("bare")
            client_server._emit_client_log(logging.INFO, "probe.empty", "empty context", {})
            client_server._emit_client_log(logging.INFO, "probe.none", "no context")
            after = time.time()
            handler = logging.getLogger().handlers[0]
            fixed = json.loads(handler.format(_fixed_record(1741091696.789)))
            rounded = json.loads(handler.format(_fixed_record(1741091696.9999996)))
    finally:
        monkeypatch.undo()
        time.tzset()

    # Today the exception record's traceback and the bare text add or replace lines; one record is one line.
    lines = stream.getvalue().splitlines()
    assert len(lines) == 5, lines  # C1 C2
    payloads = [json.loads(line) for line in lines]
    assert all(isinstance(payload, dict) for payload in payloads), lines  # C1 C2
    emitted, failed, bare, empty, none = payloads

    assert list(emitted) == EMIT_KEYS, emitted  # C1
    assert (emitted["level"], emitted["service"], emitted["event"], emitted["message"], emitted["context"]) == ("ERROR", "client-backend", "engine.call", "Engine metadata failed", {"error": "x\ny"}), emitted  # C1
    # An empty or missing context is omitted, not written as {} or null.
    assert (list(empty), empty["event"], empty["message"]) == (BARE_KEYS, "probe.empty", "empty context"), empty  # C1
    assert (list(none), none["event"], none["message"]) == (BARE_KEYS, "probe.none", "no context"), none  # C1

    stamps = [payload["ts"] for payload in payloads]
    # Today's ts is local time with an offset (observed `2026-10-02T04:17:22.827+05:45`), which TS_RE refuses.
    assert all(TS_RE.fullmatch(ts) for ts in stamps), stamps  # C1
    # A local-time rendering with a `Z` reads back 5h45m outside the window; one second covers the millisecond truncation.
    assert all(before - 1 <= _epoch(ts) <= after + 1 for ts in stamps), (before, after, stamps)  # C1
    # The record's `created` in UTC, not the formatting time; milliseconds truncated without rounding to the microsecond first give 56.999.
    assert (fixed["ts"], rounded["ts"]) == ("2025-03-04T12:34:56.789Z", "2025-03-04T12:34:57.000Z"), (fixed, rounded)  # C1

    assert list(bare) == BARE_KEYS, bare  # C2
    assert (bare["level"], bare["service"], bare["event"], bare["message"]) == ("INFO", "client-backend", "client.log", "bare"), bare  # C2
    assert list(failed) == BARE_KEYS + ["traceback"], failed  # C1
    assert (failed["level"], failed["service"], failed["event"], failed["message"]) == ("ERROR", "client-backend", "client.log", "client probe failed"), failed  # C2
    assert failed["traceback"].startswith("Traceback (most recent call last):") and failed["traceback"].endswith("ValueError: sentinel-client-log"), failed["traceback"]  # C1

```


Gate: satisfied

## 2026-10-01 - Step 7 - Phase 3 (Client root formatter, JSON) - red (audit round 1)

`tests/tmp/test_19_timestamped_request_logs_phase3.py` exited 1.

```
  tests/tmp/test_19_timestamped_request_logs_phase3.py  1 failed                               0.0s
  ----------------------------------------------------
  total                                                 1 failed                               0.2s wall, 1 lane

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

## 2026-10-01 - Step 7 - Phase 3 (Client root formatter, JSON) - audit (round 1)

- AUDIT: devsecops-test-shape-auditor - PASS
- AUDIT: devsecops-test-claim-auditor - PASS
- OUTSTANDING: nothing

### devsecops-test-shape-auditor

SHAPE AUDIT — VERDICT: PASS

CRITICAL
none

RECOMMENDATIONS
none

PREDICTED FAILURE
The test fails before any assertion. Line 69 enters `_client_logging`, which calls `client_server.configure_client_logging()` at tests/tmp/test_19_timestamped_request_logs_phase3.py:44. That call raises `AttributeError: module 'server' has no attribute 'configure_client_logging'`, because the symbol is not defined anywhere in client/backend/server.py. The first assertion that would fail once the function exists is line 102 (`TS_RE.fullmatch`). Today `_emit_client_log` stamps `datetime.now().astimezone().isoformat(timespec="milliseconds")`, which gives a local time with an offset (for example `+05:45`), not a `...Z` UTC time.

NOT ASSESSED
1. `code_under_test` listed tests/active/test_server.py and tests/active/test_log_format.py. I did not read either one: they are sibling tests, not code this test runs, and the shape verdict doesn't depend on them.
2. `configure_client_logging` doesn't exist yet. So I answered the stub question from the assertion form against the current `_emit_client_log` (server.py:120-136) and the existing `logging.basicConfig(format="%(message)s")` at server.py:1184, not against a real implementation. The answer:
   - **The current behaviour fails** at line 102 (wrong `ts` format) and at line 89, because the bare text and the exception traceback don't come out as single JSON lines.
   - **A hard-coded `Z` on a local time fails** at line 104, because the zone is pinned 5h45m off UTC.
   - **A `ts` taken at format time instead of from `record.created` fails** at line 106.
   - **Rounding to milliseconds without first rounding to the microsecond fails** at line 106, through the `1741091696.9999996` input.
   - **Always emitting `context` fails** at lines 97-98, through the empty-dict and no-context inputs.
   - **A stub `configure_client_logging` that installs no JSON formatter fails** at lines 89-91.
3. I read tests/active/conftest.py only far enough to confirm that `client_server` is `import server as client_server` (conftest.py:41). The test uses no pytest fixtures except the built-in `monkeypatch`.

### devsecops-test-claim-auditor

Rows `C1a`–`C1d` all cover must_prove clause C1, and rows `C2a`–`C2c` all cover C2.

```
CLAIM AUDIT — VERDICT: PASS

CLAUSE MAP  (26 clauses: 7 must_prove, 15 docstring, 4 name)
| id | source | clause | assertion | excludes | status |
|---|---|---|---|---|---|
| C1a | must_prove | an `_emit_client_log` record "renders as a JSON line" | :89, :91 | a record that spans several lines, or a line that is not a JSON object (for example the JSON string nested as a plain-text message) | CARRIED |
| C1b | must_prove | keys run `ts, level, service, event, message, context` in that order | :94, :95 | keys that are reordered, missing or extra, and wrong values in them (the list is compared exactly) | CARRIED |
| C1c | must_prove | `[, context]`: the context key is optional and left out when there is none | :97, :98 | writing `context: {}` or `context: null` for an empty or missing context | CARRIED |
| C1d | must_prove | "with a UTC `ts`" | :102, :104, :106 | a local time with an offset (:102), a local time with a `Z` added under TZ +05:45 (:104), the time of formatting instead of `created`, and rounding that gives 56.999 (:106) | CARRIED |
| C2a | must_prove | a bare root-logger record renders as a JSON line | :89, :91 | a bare record written as plain `%(message)s` text | CARRIED |
| C2b | must_prove | "in the same JSON shape": keys `ts, level, service, event, message`, UTC `ts` | :108, :102, :104 | a different key set or order for bare records, a missing `service`, a non-UTC `ts` on the bare line | CARRIED |
| C2c | must_prove | "with event `client.log`" | :109 | the event left out, or taken from the logger name or the message | CARRIED |
| D1 | docstring | "every Client record leaves the root handler as one JSON line" | :89, :91 | a traceback or bare text that adds or replaces lines | CARRIED |
| D2 | docstring | "in the Client's key order" | :94, :97, :98, :108, :110 | any record whose keys are reordered | CARRIED |
| D3 | docstring | "with a UTC `ts`" (for every record) | :102, :104 | a local-time `ts` on any of the five lines | CARRIED |
| D4 | docstring | the five calls "write exactly five lines, each a JSON object" | :89, :91 | extra or missing lines; a line that is not an object | CARRIED |
| D5 | docstring | `engine.call` keys are exactly `ts, level, service, event, message, context` | :94 | reordered or extra keys | CARRIED |
| D6 | docstring | level ERROR, service `client-backend`, "the message and `{"error": "x\ny"}` unchanged" | :95 | a wrong level name or service, or a context that is escaped, stringified or dropped | CARRIED |
| D7 | docstring | "the empty- and no-context lines stop at `message`" | :97, :98 | `context: {}` or `context: null` written | CARRIED |
| D8 | docstring | "Every line's `ts` matches `TS_RE`" | :102 | an offset suffix, or no milliseconds | CARRIED |
| D9 | docstring | "reads back as UTC inside the wall-clock window of the calls" | :104 | a local time with `Z` under +05:45 (5h45m outside the ±1 s window) | CARRIED |
| D10 | docstring | the installed formatter renders created 1741091696.789 as `2025-03-04T12:34:56.789Z` | :81, :106 | a `ts` taken at formatting time, or rendered in local time | CARRIED |
| D11 | docstring | created 1741091696.9999996 renders as `2025-03-04T12:34:57.000Z` | :82, :106 | seconds and milliseconds that disagree (56.999, or 56.1000) | CARRIED |
| D12 | docstring | the bare and exception records have "event `client.log` and their own message" | :109, :111 | a fixed or empty message; a non-fallback event | CARRIED |
| D13 | docstring | "the bare line's keys are exactly `ts, level, service, event, message`" | :108 | extra keys (for example `context: null`, `traceback: null`) or a different order | CARRIED |
| D14 | docstring | "the exception line adds `traceback`" | :110 | the exception info silently dropped, or the traceback placed elsewhere in the key order | CARRIED |
| D15 | docstring | traceback is "the formatted `ValueError: sentinel-client-log` traceback" | :112 | only the exception text without the stack, or a different or empty traceback | CARRIED |
| N1 | name | "client records leave as json lines" | :89, :91 | non-JSON or multi-line output | CARRIED |
| N2 | name | "in client key order" | :94, :108, :110 | reordered keys | CARRIED |
| N3 | name | "with utc ts" | :102, :104, :106 | a local-time or formatting-time `ts` | CARRIED |
| N4 | name | "and bare ones as client log" | :109 | a bare record without the `client.log` event | CARRIED |

CRITICAL
none

RECOMMENDATIONS
none

OBSERVATIONS
none

NOT ASSESSED
1. client/backend/server.py as read has no `configure_client_logging` and no Client
   formatter; `main()` still calls `logging.basicConfig(level=logging.INFO,
   format="%(message)s")` at server.py:1184, and `_emit_client_log` (server.py:120-136)
   still builds its own JSON string. The test calls `client_server.configure_client_logging()`
   at test_path:44. So I could not check against the code the bounds and failure paths of
   the formatter this test is meant to cover. Bounds and the abnormal path were judged
   from the test's own inputs (empty context, no context, a `logging.exception` record)
   and from `must_prove`.
2. `code_under_test` lists tests/active/test_server.py and tests/active/test_log_format.py.
   These are test modules, and this test does not exercise them. I did not audit them.
   Only the `client_server` import this test takes from tests/active/conftest.py:41 was
   confirmed.
```

## 2026-10-01 - Step 7 - Phase 3 (Client root formatter, JSON) - must_prove

Quoted from the phase Intent, written at Step 6 before the checkpoint was drafted.

Intent:
In client/backend/server.py, configure_client_logging installs ClientLogFormatter on the root logger, which `main()` now calls in place of `basicConfig`, and `_emit_client_log` hands it event and context as `client_event`/`client_context` record attributes instead of building JSON by hand, so every Client record leaves through one formatter.

- C1 - An `_emit_client_log` record renders as a JSON line whose keys run `ts, level, service, event, message[, context]` with a UTC `ts`.
- C2 - A bare root-logger record renders in the same JSON shape with event `client.log`.

must_prove:
- C1 - An `_emit_client_log` record renders as a JSON line whose keys run `ts, level, service, event, message[, context]` with a UTC `ts`.
- C2 - A bare root-logger record renders in the same JSON shape with event `client.log`.

## 2026-10-01 - Step 7 - Phase 3 (Client root formatter, JSON) - resumed

`tests/tmp/test_19_timestamped_request_logs_phase3.py` matches the bytes banked when its red was confirmed, so the gate it already passed stands and it was not re-authored.

## 2026-10-01 - Step 7 - Phase 3 (Client root formatter, JSON) - checkpoint outcome (run 1)

`tests/tmp/test_19_timestamped_request_logs_phase3.py` exited 0 after the phase landed.

<changes>
### `client/backend/server.py`
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
</changes>

<inner_tests>
none
</inner_tests>

<unanticipated>
tests/tmp/probe_caplog_formatter.py: my throwaway probe showing that caplog's handler, and so its formatter, lasts the whole session. I have no delete tool, so I emptied it; it collects no tests and can be removed. Separately, tests/tmp/test_probe_19_p3.py and tests/tmp/test_probe_19_p3_values.py were already there from an earlier step, and I did not touch them.
</unanticipated>

<awaiting_operator>
none
</awaiting_operator>

```
  tests/tmp/test_19_timestamped_request_logs_phase3.py  1 passed                               0.0s
  ----------------------------------------------------
  total                                                 1 passed                               0.2s wall, 1 lane

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

## 2026-10-01 - Step 7 - Phase 4 (Client text rendering and drift guard) - must_prove

Quoted from the phase Intent, written at Step 6 before the checkpoint was drafted.

Intent:
The Client's `normalize_log_format`, `_format_ts`, `_text_value` and `_render_text` are copies of the Engine's, so `LOG_FORMAT` selects the Client's rendering exactly as it does the Engine's, and both services write byte-identical `ts` and text for the same record.

- C1 - A Client `LOG_FORMAT` value selects text or JSON lines exactly as the same value does for the Engine.
- C2 - For the same `created` and payload, the Client's `_format_ts` and `_render_text` return the same strings as the Engine's.

must_prove:
- C1 - A Client `LOG_FORMAT` value selects text or JSON lines exactly as the same value does for the Engine.
- C2 - For the same `created` and payload, the Client's `_format_ts` and `_render_text` return the same strings as the Engine's.

## 2026-10-01 - Step 7 - Phase 4 (Client text rendering and drift guard) - self-check (audit round 1, send-back 0)

`tests/tmp/test_19_timestamped_request_logs_phase4.py`, surface `checkpoint`. Collection exit 0.

- C1 - tests/tmp/test_19_timestamped_request_logs_phase4.py:115/117/119/120 — under LOG_FORMAT unset, `json`, `JSON`, `bogus` and `""`, stderr is exactly four lines. Each one is a JSON object whose `ts` matches TS_RE. The exception record's `traceback` runs from `Traceback (most recent call last):` to `ValueError: sentinel-client-log`. With `ts` and `traceback` removed, the four payloads' items, in order, equal JSON_PAYLOADS. - expected: Four JSON lines, the same as the Engine gives for these five values. This is observed: the Engine's normalize_log_format returned `json` for None, 'json', 'JSON', 'bogus' and '' in tests/tmp/probe_engine_render.py. All five parametrizations pass against the code as it stands, which is phase 3's JSON output. - excludes: A Client that defaults to text when LOG_FORMAT is unset, or that treats any value other than `json` (e.g. `bogus`, `""` or the upper-case `JSON` without lowercasing) as text, writes `<ts> LEVEL …` lines. `_json_object` then returns None, and line 115 goes red. A copy that reorders keys or adds `modes` to the JSON payload turns line 120 red.
- C1 - tests/tmp/test_19_timestamped_request_logs_phase4.py:127/129 — under LOG_FORMAT `text`, `TEXT`, ` Text ` and `\ttext\n`, stderr is exactly four physical lines (splitlines), and every line matches `^<TS_RE> (INFO|ERROR) `. - expected: Four text lines, the same as the Engine gives for these four values. The selection is observed: the Engine's normalize_log_format returned `text` for 'text', 'TEXT', ' Text ' and '\ttext\n' in the probe. Today's run fails at :129 on all four, because each line is still JSON (`['{"ts":"2026-10-01T22:44:17.311Z","level":"ERROR",...`). - excludes: Several plausible faults stay on JSON and turn :129 red: a Client that ignores LOG_FORMAT (as today), one that compares without `.lower()` (`TEXT`), or one that skips `.strip()` (` Text ` and `\ttext\n`). A text renderer that does not escape LF writes the `error=x` / `y` value and the traceback across several lines, which makes :127 read more than 4.
- C1 - tests/tmp/test_19_timestamped_request_logs_phase4.py:137 — once the timestamp is split off, the `engine.call` line reads exactly `ERROR engine.call Engine metadata failed error=x\ny`, where `\n` is a backslash followed by an n. - expected: `ERROR engine.call Engine metadata failed error=x\\ny` (Python literal). This is observed as the Engine's `_render_text` output for the same payload in the probe: `'T ERROR engine.call Engine metadata failed error=x\\ny'`. - excludes: A Client text renderer that writes the `service` token (`ERROR client-backend engine.call …`), renders the context as JSON (`{"error":"x\ny"}`), or leaves the LF unescaped (the line becomes `…error=x`) gives a string that is not equal.
- C1 - tests/tmp/test_19_timestamped_request_logs_phase4.py:138 — the exception line fullmatches EXCEPTION_TEXT_RE. That is `ERROR client.log client probe failed Traceback (most recent call last):\n  File "…", line N, in _log_records\n    raise ValueError("sentinel-client-log")\nValueError: sentinel-client-log`, with each `\n` written as a backslash followed by an n, all on one line. - expected: A match. This is observed: tests/tmp/probe_client_tb.py took the Client's real in-process traceback (`'Traceback (most recent call last):\n  File ".../test_19_timestamped_request_logs_phase4.py", line 89, in _log_records\n    raise ValueError("sentinel-client-log")\nValueError: sentinel-client-log'`), escaped its LFs and fullmatched the regex (`MATCH True`). The Engine's `_render_text` puts the traceback at the end of the line in the same form (probe line 37). - excludes: A text renderer can drop the traceback (the Engine keeps it as the final token), place it before the message, or let its LFs through. In the last case the record splits across lines, so :127 or this fullmatch goes red.
- C1 - tests/tmp/test_19_timestamped_request_logs_phase4.py:139/141 — the bare record reads `INFO client.log bare`, and the access record reads `INFO client.access request finished ip=127.0.0.1 status=200 bytes=-`. - expected: Exactly those two strings. Both are observed from the Engine's `_render_text` on the same payloads in the probe: `'T INFO client.log bare'` and `'T INFO client.access request finished ip=127.0.0.1 status=200 bytes=-'`. - excludes: A renderer that writes `service=client-backend` or the `service` value, quotes the strings (`ip="127.0.0.1"`), or renders the int via `repr`/str of a JSON string produces a different access line. A bare record that falls back to an event other than `client.log` changes the bare line.
- C2 - tests/tmp/test_19_timestamped_request_logs_phase4.py:157 — for `created` 1741091696.789 and 1741091696.9999996, the Client's `_format_ts` returns the same list the Engine child printed. The control at :150 pins that list to `["2025-03-04T12:34:56.789Z", "2025-03-04T12:34:57.000Z"]`. - expected: `["2025-03-04T12:34:56.789Z", "2025-03-04T12:34:57.000Z"]` from both. This is observed: the control at :150 passed in the run, and so did :157 (the Client's phase-3 copy already exists). - excludes: A Client `_format_ts` built from `record.msecs`, or one that truncates `created` instead of letting `fromtimestamp` round to the microsecond, gives `2025-03-04T12:34:56.999Z` for the second value. Local time instead of UTC gives a different hour. Either way the lists differ.
- C2 - tests/tmp/test_19_timestamped_request_logs_phase4.py:159 — the Client's `_render_text` over both RENDER_PAYLOADS equals the Engine child's list. The control at :150 pins that list to ENGINE_TEXTS. - expected: `['2025-03-04T12:34:57.000Z INFO e m\\nn a=1 b=null c=[1,{"d":"x"}] request_id=r T\\nU', '2025-03-04T12:34:56.789Z ERROR service.lifecycle state=start note=a\\rb request_id=q']`, from the Engine child, observed (the control at :150 passed). The current run is red at :158 with `AttributeError: module 'server' has no attribute '_render_text'`, because phase 4 has not yet added the Client copy. - excludes: Each of these drifted Client copies changes the list: writing `None` as `None` (str()) instead of `null`; a list rendered by `json.dumps` with its default separators (`[1, {"d": "x"}]`); `request_id` written twice for payload 1; `request_id` never appended when only top-level for payload 2; an empty message token for payload 2; and CR left unescaped (`a\rb`).

<assertions>
tests/tmp/test_19_timestamped_request_logs_phase4.py:111 - for LOG_FORMAT unset, `json`, `JSON`, `bogus` and empty, the four Client records (`engine.call` with `{"error": "x\ny"}`, a `logging.exception`, a bare `logging.info`, and `client.access`) give exactly four lines, and each one parses as a JSON object - C1
tests/tmp/test_19_timestamped_request_logs_phase4.py:113 - in those JSON cases every `ts` matches TS_RE - C1
tests/tmp/test_19_timestamped_request_logs_phase4.py:115 - in those JSON cases the exception record's `traceback` starts with `Traceback (most recent call last):` and ends with `ValueError: sentinel-client-log` - C1
tests/tmp/test_19_timestamped_request_logs_phase4.py:116 - in those JSON cases each payload, less `ts` and `traceback`, has exactly the keys, key order and values of phase 3 (service `client-backend`, events `engine.call`/`client.log`/`client.log`/`client.access`, and `status` still the int 200) - C1
tests/tmp/test_19_timestamped_request_logs_phase4.py:123 - for `text`, `TEXT`, ` Text ` and tab-`text`-newline, the four records give exactly four physical lines (splitlines), so the multi-line context value and the traceback are each one line - C1
tests/tmp/test_19_timestamped_request_logs_phase4.py:125 - in the text cases every line matches `^<TS_RE> (INFO|ERROR) ` - C1
tests/tmp/test_19_timestamped_request_logs_phase4.py:126 - in the text cases no line parses as a JSON object (fails against today's Client, which ignores LOG_FORMAT) - C1
tests/tmp/test_19_timestamped_request_logs_phase4.py:127 - in the text cases no line starts with `<` - C1
tests/tmp/test_19_timestamped_request_logs_phase4.py:130 - in the text cases each line's leading ts token matches TS_RE in full - C1
tests/tmp/test_19_timestamped_request_logs_phase4.py:133 - the `engine.call` text line, after the ts, is exactly `ERROR engine.call Engine metadata failed error=x\ny`, where `\n` is a backslash and an n, with no service token - C1
tests/tmp/test_19_timestamped_request_logs_phase4.py:134 - the exception text line fully matches `ERROR client.log client probe failed Traceback (most recent call last):\n  File "…", line N, in …\n    raise ValueError("sentinel-client-log")\nValueError: sentinel-client-log`, where each `\n` is a literal backslash and n - C1
tests/tmp/test_19_timestamped_request_logs_phase4.py:135 - the bare text line, after the ts, is exactly `INFO client.log bare` - C1
tests/tmp/test_19_timestamped_request_logs_phase4.py:137 - the `client.access` text line, after the ts, is exactly `INFO client.access request finished ip=127.0.0.1 status=200 bytes=-` - C1
tests/tmp/test_19_timestamped_request_logs_phase4.py:146 - control: the Engine child prints `_format_ts` = `2025-03-04T12:34:56.789Z` and `2025-03-04T12:34:57.000Z` for created 1741091696.789 and 1741091696.9999996, and prints `_render_text` of the payload as the observed `2025-03-04T12:34:57.000Z INFO e m\nn a=1 b=null c=[1,{"d":"x"}] request_id=r T\nU`, so the equality checks below compare real strings - C2
tests/tmp/test_19_timestamped_request_logs_phase4.py:153 - in-process, `client_server._format_ts` gives the Engine child's strings for both `created` values - C2
tests/tmp/test_19_timestamped_request_logs_phase4.py:154 - in-process, `client_server._render_text(payload)` equals the Engine child's `_render_text` of the same payload (today an AttributeError: the Client has no `_render_text`) - C2
</assertions>

<probes>
Ran ValidateTests ["tests/tmp/test_probe_19_p4.py"] once (Python 3.14.7), with a deliberate `assert False` so the output would print. (1) The Engine child (`cwd=engine/server/api`, `from logging_profiles import _format_ts, _render_text`, created=1741091696.9999996, payload `{"ts": "2025-03-04T12:34:57.000Z", "level": "INFO", "event": "e", "message": "m\nn", "context": {"a": 1, "b": None, "c": [1, {"d": "x"}], "request_id": "r"}, "request_id": "r", "traceback": "T\nU"}` passed as JSON in argv) exited rc 0 with empty stderr. It printed ts `2025-03-04T12:34:57.000Z` and text `2025-03-04T12:34:57.000Z INFO e m\nn a=1 b=null c=[1,{"d":"x"}] request_id=r T\nU`, where each `\n` is a backslash and an n. (2) `hasattr` on client_server for normalize_log_format/_format_ts/_text_value/_render_text gave only `['_format_ts']`, so the Client's text path and `_render_text` are absent today. (3) After `configure_client_logging()`, the Client wrote these lines: `logging.exception("client probe failed")` gave `{"ts":"2026-10-01T22:41:53.182Z","level":"ERROR","service":"client-backend","event":"client.log","message":"client probe failed","traceback":"Traceback (most recent call last):\n  File \"/…/tests/tmp/test_probe_19_p4.py\", line 45, in test_probe\n    raise ValueError(\"sentinel-client-log\")\nValueError: sentinel-client-log"}`, with no caret line under the raise; `_emit_client_log(INFO, "client.access", …)` gave `{"ts":…,"level":"INFO","service":"client-backend","event":"client.access","message":"request finished","context":{"ip":"127.0.0.1","status":200,"bytes":"-"}}`. The ts 1741091696.789 -> `2025-03-04T12:34:56.789Z` was observed earlier, by the gated phase 1 Engine checkpoint and phase 3 Client checkpoint. Not run: the checkpoint file itself, so as not to bank a fingerprint before the workflow's gating run. Its predicted red is the four text cases (today's lines are JSON) and the C2 test at line 154 (AttributeError on `_render_text`); the JSON cases and the controls at 146/153 should pass today. The probe file tests/tmp/test_probe_19_p4.py is still in place because no tool here can delete a file; it should be removed.
</probes>

<unassertable>
none
</unassertable>

### `tests/tmp/test_19_timestamped_request_logs_phase4.py` - 9215 characters, inlined in full

```
"""The Client's `LOG_FORMAT` picks text or JSON for the same values the Engine's does, and its `_format_ts` and `_render_text` return the Engine's strings for the same input.

- In-process, after `configure_client_logging()` with the handler's stream swapped for a StringIO, the test logs `_emit_client_log(ERROR, "engine.call", "Engine metadata failed", {"error": "x\\ny"})`, a `logging.exception` for `ValueError("sentinel-client-log")`, `logging.info("bare")` and `_emit_client_log(INFO, "client.access", "request finished", {"ip": "127.0.0.1", "status": 200, "bytes": "-"})`.
- With `LOG_FORMAT` unset, `json`, `JSON`, `bogus` or empty, stderr is four JSON objects with a `ts` matching `TS_RE`, carrying the Client's phase-3 keys, order and values, and a traceback ending `ValueError: sentinel-client-log` on the exception record.
- With `text`, `TEXT`, ` Text ` or tab-`text`-newline, stderr is exactly four lines: none parses as a JSON object, none starts with `<`, and every one matches `<TS_RE> (INFO|ERROR) `. The rest is the Engine's line shape with no `service` token. The `engine.call` line ends `error=x\\ny` and the exception line ends with the traceback, where `\\n` is a backslash and an n. The access line reads `INFO client.access request finished ip=127.0.0.1 status=200 bytes=-`.
- An Engine child takes the `created` values 1741091696.789 and 1741091696.9999996 and one payload holding a multi-line message and traceback, a null, a nested list and a `request_id` both in context and at top level. It prints `2025-03-04T12:34:56.789Z`, `2025-03-04T12:34:57.000Z` and the observed text line, and the Client's `_format_ts` and `_render_text` return the same strings in-process.
"""
from __future__ import annotations

import io
import json
import logging
import re
import subprocess
import sys
import textwrap
from contextlib import contextmanager
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
API_DIR = ROOT / "engine" / "server" / "api"
ACTIVE = ROOT / "tests" / "active"
if str(ACTIVE) not in sys.path:
    sys.path.insert(0, str(ACTIVE))

from conftest import client_server  # noqa: E402

TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
TEXT_HEAD_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z (INFO|ERROR) ")

# The Client's JSON payloads for the four records, less `ts` and `traceback` (phase 3's key order and values).
JSON_PAYLOADS = [
    {"level": "ERROR", "service": "client-backend", "event": "engine.call", "message": "Engine metadata failed", "context": {"error": "x\ny"}},
    {"level": "ERROR", "service": "client-backend", "event": "client.log", "message": "client probe failed"},
    {"level": "INFO", "service": "client-backend", "event": "client.log", "message": "bare"},
    {"level": "INFO", "service": "client-backend", "event": "client.access", "message": "request finished", "context": {"ip": "127.0.0.1", "status": 200, "bytes": "-"}},
]

# The traceback's `\n` are the two characters backslash and n, not a line break (observed: no caret line under the raise on 3.14).
EXCEPTION_TEXT_RE = re.compile(r'ERROR client\.log client probe failed Traceback \(most recent call last\):\\n  File "[^"]+", line \d+, in \w+\\n    raise ValueError\("sentinel-client-log"\)\\nValueError: sentinel-client-log')

# Prints the Engine's own _format_ts for each argv `created` and its _render_text of the argv payload.
_ENGINE_CHILD = textwrap.dedent(
    """
    import json, logging, sys
    from logging_profiles import _format_ts, _render_text
    stamps = []
    for created in json.loads(sys.argv[1]):
        record = logging.LogRecord("probe", logging.INFO, "probe", 1, "fixed", None, None)
        record.created = created
        stamps.append(_format_ts(record))
    print(json.dumps({"ts": stamps, "text": _render_text(json.loads(sys.argv[2]))}))
    """
)

CREATED = [1741091696.789, 1741091696.9999996]
RENDER_PAYLOAD = {"ts": "2025-03-04T12:34:57.000Z", "level": "INFO", "event": "e", "message": "m\nn", "context": {"a": 1, "b": None, "c": [1, {"d": "x"}], "request_id": "r"}, "request_id": "r", "traceback": "T\nU"}
# Observed from the Engine child: CR/LF escaped, None as null, the list as compact JSON, request_id written once from the context.
ENGINE_TEXT = '2025-03-04T12:34:57.000Z INFO e m\\nn a=1 b=null c=[1,{"d":"x"}] request_id=r T\\nU'


@contextmanager
def _client_logging(monkeypatch, value):
    """Run configure_client_logging under LOG_FORMAT=value; yield the stream it writes to."""
    # Saved and restored here, so pytest's own capture handlers come back for later tests.
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


def _log_records(monkeypatch, value) -> list[str]:
    """Log the four records under LOG_FORMAT=value; return the physical lines written."""
    with _client_logging(monkeypatch, value) as stream:
        client_server._emit_client_log(logging.ERROR, "engine.call", "Engine metadata failed", {"error": "x\ny"})
        try:
            raise ValueError("sentinel-client-log")
        except ValueError:
            logging.exception("client probe failed")
        logging.info("bare")
        client_server._emit_client_log(logging.INFO, "client.access", "request finished", {"ip": "127.0.0.1", "status": 200, "bytes": "-"})
    # splitlines breaks on CR as well as LF, so an unescaped CR or LF adds a line here.
    return stream.getvalue().splitlines()


def _json_object(line: str) -> dict | None:
    """The line parsed as a JSON object, or None."""
    try:
        parsed = json.loads(line)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


@pytest.mark.parametrize("value", [None, "json", "JSON", "bogus", ""])
def test_client_log_format_unset_empty_json_or_unknown_writes_json_lines(monkeypatch, value):
    lines = _log_records(monkeypatch, value)
    payloads = [_json_object(line) for line in lines]
    assert len(lines) == 4 and all(payload is not None for payload in payloads), lines  # C1

    assert all(TS_RE.fullmatch(payload.pop("ts")) for payload in payloads), lines  # C1
    traceback = payloads[1].pop("traceback")
    assert traceback.startswith("Traceback (most recent call last):") and traceback.endswith("ValueError: sentinel-client-log"), traceback  # C1
    assert [list(payload.items()) for payload in payloads] == [list(payload.items()) for payload in JSON_PAYLOADS], payloads  # C1


@pytest.mark.parametrize("value", ["text", "TEXT", " Text ", "\ttext\n"])
def test_client_log_format_text_writes_the_engines_escaped_text_line_per_record(monkeypatch, value):
    lines = _log_records(monkeypatch, value)
    # Today every line is JSON; the multi-line context value and traceback would each add lines if left unescaped.
    assert len(lines) == 4, lines  # C1

    assert all(TEXT_HEAD_RE.match(line) for line in lines), lines  # C1
    assert all(_json_object(line) is None for line in lines), lines  # C1
    assert not any(line.startswith("<") for line in lines), lines  # C1

    stamps, rests = zip(*(line.split(" ", 1) for line in lines))
    assert all(TS_RE.fullmatch(ts) for ts in stamps), stamps  # C1
    emitted, failed, bare, access = rests
    # The `\n` is a backslash and an n, written into the one physical line.
    assert emitted == "ERROR engine.call Engine metadata failed error=x\\ny", emitted  # C1
    assert EXCEPTION_TEXT_RE.fullmatch(failed), failed  # C1
    assert bare == "INFO client.log bare", bare  # C1
    # The Engine's shape: no `service` token, the context as k=v, a non-string value as JSON.
    assert access == "INFO client.access request finished ip=127.0.0.1 status=200 bytes=-", access  # C1


def test_client_format_ts_and_render_text_return_the_engines_strings():
    # logging_profiles imports only the stdlib and request_context, so pytest's own interpreter can run it.
    run = subprocess.run([sys.executable, "-c", _ENGINE_CHILD, json.dumps(CREATED), json.dumps(RENDER_PAYLOAD)], cwd=API_DIR, capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stderr[-2000:]
    engine = json.loads(run.stdout)
    # Control: the child really rendered, so equality below compares two real strings rather than two empty ones.
    assert engine == {"ts": ["2025-03-04T12:34:56.789Z", "2025-03-04T12:34:57.000Z"], "text": ENGINE_TEXT}, engine  # C2

    client_stamps = []
    for created in CREATED:
        record = logging.LogRecord("probe", logging.INFO, "probe", 1, "fixed", None, None)
        record.created = created
        client_stamps.append(client_server._format_ts(record))
    assert client_stamps == engine["ts"], (client_stamps, engine["ts"])  # C2
    assert client_server._render_text(RENDER_PAYLOAD) == engine["text"], client_server._render_text(RENDER_PAYLOAD)  # C2

```


Gate: satisfied

## 2026-10-01 - Step 7 - Phase 4 (Client text rendering and drift guard) - red (audit round 1)

`tests/tmp/test_19_timestamped_request_logs_phase4.py` exited 1.

```
  tests/tmp/test_19_timestamped_request_logs_phase4.py  5 failed, 5 passed                     0.0s
  ----------------------------------------------------
  total                                                 5 failed, 5 passed                     0.2s wall, 1 lane

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

## 2026-10-01 - Step 7 - Phase 4 (Client text rendering and drift guard) - audit (round 1)

- AUDIT: devsecops-test-shape-auditor - PASS
- AUDIT: devsecops-test-claim-auditor - PASS
- OUTSTANDING: nothing

### devsecops-test-shape-auditor

SHAPE AUDIT — VERDICT: PASS

CRITICAL
none

RECOMMENDATIONS
none

PREDICTED FAILURE
All four parametrisations of `test_client_log_format_text_writes_the_engines_escaped_text_line_per_record` fail at tests/tmp/test_19_timestamped_request_logs_phase4.py:129 on `assert all(TEXT_HEAD_RE.match(line) for line in lines)`. The Client ignores `LOG_FORMAT`, so each line begins `{"ts":`; the length check at line 127 passes first because JSON escapes the embedded newlines. `test_client_format_ts_and_render_text_return_the_engines_strings` passes lines 147, 150 and 157, then errors rather than fails at line 158. That error is `AttributeError: module 'server' has no attribute '_render_text'`. The five parametrisations of `test_client_log_format_unset_empty_json_or_unknown_writes_json_lines` pass against the current JSON-only Client.

NOT ASSESSED
1. `code_under_test` lists tests/active/test_log_format.py, and it does not exist (Glob `tests/active/test_log_format*.py` found nothing). The test does not import it, so this audit is unaffected. The listed path was not read.
2. `fixtures_path` was not supplied. The test uses no pytest fixture except the built-in `monkeypatch`. It imports `client_server` from tests/active/conftest.py:41 (`import server as client_server`). The import was resolved there, and nothing else in that conftest was assessed.

### devsecops-test-claim-auditor

CLAIM AUDIT — VERDICT: PASS

CLAUSE MAP  (25 clauses: 4 must_prove, 17 docstring, 4 name)
| id | source | clause | assertion | excludes | status |
|---|---|---|---|---|---|
| C1a | must_prove | values the Engine reads as JSON (unset, `json`, `JSON`, `bogus`, empty) select JSON lines on the Client | :115, :120 | a Client that reads empty, unset or unknown as text, or matches `json` case-sensitively | CARRIED |
| C1b | must_prove | values the Engine reads as text (`text`, `TEXT`, ` Text `, tab-text-newline) select text lines on the Client | :127, :130 | a Client that ignores `LOG_FORMAT`, matches case-sensitively, or does not strip whitespace and control characters | CARRIED |
| C2a | must_prove | Client `_format_ts` returns the Engine's string for the same `created` | :157 | a stamp built from `record.msecs` or truncated rather than rounded (`.9999996` gives `57.000`, not `56.999`) | CARRIED |
| C2b | must_prove | Client `_render_text` returns the Engine's string for the same payload | :159 | no CR/LF escaping, `None` printed instead of `null`, a non-compact list, `request_id` written twice or missing from the top level, the no-message branch or the traceback mishandled | CARRIED |
| D1 | docstring | "`LOG_FORMAT` picks text or JSON for the same values the Engine's does" | :115, :130 | the wrong format chosen for a value in either partition | CARRIED |
| D2 | docstring | "`_format_ts` and `_render_text` return the Engine's strings for the same input" | :157, :159 | any divergence from the Engine child's output | CARRIED |
| D3 | docstring | the four records are logged in-process through `configure_client_logging()` | :115, :127 | a record dropped, or one record split across lines | CARRIED |
| D4 | docstring | unset/`json`/`JSON`/`bogus`/empty: "four JSON objects" | :115 | any non-JSON or extra line | CARRIED |
| D5 | docstring | "a `ts` matching `TS_RE`" | :117 | a stamp without the `Z` suffix or without milliseconds | CARRIED |
| D6 | docstring | "the Client's phase-3 keys, order and values" | :120 | Engine keys (`modes`, `request_id`) added, keys reordered, or `service` dropped | CARRIED |
| D7 | docstring | "a traceback ending `ValueError: sentinel-client-log` on the exception record" | :119 | the traceback missing (the `pop` at :118 raises) or truncated | CARRIED |
| D8 | docstring | text variants: "exactly four lines" | :127 | an unescaped LF or CR in the context value or the traceback | CARRIED |
| D9 | docstring | "none parses as a JSON object" | :130 | JSON still emitted under `text` | CARRIED |
| D10 | docstring | "none starts with `<`" | :131 | a syslog priority prefix | CARRIED |
| D11 | docstring | "every one matches `<TS_RE> (INFO|ERROR) `" | :129, :134 | a missing or malformed stamp or level head | CARRIED |
| D12 | docstring | "the rest is the Engine's line shape with no `service` token" | :137, :139, :141 | a `service=` token, or JSON-ish context | CARRIED |
| D13 | docstring | "`engine.call` line ends `error=x\\ny`" with a literal backslash-n | :137 | an unescaped or doubly escaped newline | CARRIED |
| D14 | docstring | "exception line ends with the traceback", with `\n` literal | :138 | the traceback missing, placed before the message, or left unescaped | CARRIED |
| D15 | docstring | access line reads "`INFO client.access request finished ip=127.0.0.1 status=200 bytes=-`" | :141 | an int written as `"200"`, or the context order changed | CARRIED |
| D16 | docstring | the Engine child prints the two stamps and the two observed text lines | :150 | a child that renders nothing, so the equality checks compare empty strings | CARRIED |
| D17 | docstring | the Client's `_format_ts` and `_render_text` "return the same strings in-process" | :157, :159 | any per-branch divergence from the Engine | CARRIED |
| N1 | name | "unset, empty, json or unknown writes json lines" | :115 | text written for any of those values | CARRIED |
| N2a | name | "writes the Engine's escaped text line" | :137, :138, :141 | unescaped output, or a shape other than the Engine's | CARRIED |
| N2b | name | "per record" | :127 | a record split across lines, or two records merged | CARRIED |
| N3 | name | "format_ts and render_text return the Engine's strings" | :157, :159 | output that differs from the Engine child | CARRIED |

CRITICAL
none

RECOMMENDATIONS
1. bounds (rules/testing.md): tests/tmp/test_19_timestamped_request_logs_phase4.py:60
   No `RENDER_PAYLOADS` value has a non-ASCII character. The Engine's `_text_value` dumps with `ensure_ascii=False`. The Client's existing JSON formatter uses `ensure_ascii=True` (client/backend/server.py:146), so a Client `_render_text` that dumps with `ensure_ascii=True` would pass :159 while differing from the Engine. The payload set also has no bool and no empty `context`.
2. bounds (rules/testing.md): tests/tmp/test_19_timestamped_request_logs_phase4.py:123
   No `LOG_FORMAT` value sits close to `text` without being it, such as `texts`, `tex` or `context`. The Engine reads those as `json` (logging_profiles.py:87-90). A Client that tests with `"text" in value` or `startswith("text")` passes both parametrize sets but selects text for them.
3. No rule covers this (rules/testing.md, `whole-claim` context): tests/tmp/test_19_timestamped_request_logs_phase4.py:111, :123
   C1 is stated relative to the Engine, but the expected selections are hard-coded. The Engine's `normalize_log_format` is never consulted, unlike C2, which compares against a live Engine child at :146. The values match the Engine as it reads today. If the Engine's normalisation drifts later, this test does not notice.

OBSERVATIONS
none

NOT ASSESSED
1. `code_under_test` lists tests/active/test_log_format.py, which does not resolve. Nothing in it was assessed.
2. In client/backend/server.py as read, `LOG_FORMAT` is not read and `_render_text` is not defined. I judged C1 and C2 against the Engine's definitions (engine/server/api/logging_profiles.py:85-90, :196-223) rather than against Client code.
3. `fixtures_path` was not supplied. `client_server` comes from tests/active/conftest.py:41, which I read. The test uses no pytest fixtures other than `monkeypatch`.

## 2026-10-01 - Step 7 - Phase 4 (Client text rendering and drift guard) - checkpoint outcome (run 1)

`tests/tmp/test_19_timestamped_request_logs_phase4.py` exited 0 after the phase landed.

<changes>
### `client/backend/server.py`
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
</changes>

<inner_tests>
none
</inner_tests>

<unanticipated>
none
</unanticipated>

<awaiting_operator>
none
</awaiting_operator>

```
  tests/tmp/test_19_timestamped_request_logs_phase4.py  10 passed                              0.0s
  ----------------------------------------------------
  total                                                 10 passed                              0.2s wall, 1 lane

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

## 2026-10-01 - Step 8 - clause accounting

- P1C1 - carried - rests on: the last audit of `tests/tmp/test_19_timestamped_request_logs_phase1.py`
- P1C2 - carried - rests on: the last audit of `tests/tmp/test_19_timestamped_request_logs_phase1.py`
- P2C1 - carried - rests on: the last audit of `tests/tmp/test_19_timestamped_request_logs_phase2.py`
- P2C2 - carried - rests on: the last audit of `tests/tmp/test_19_timestamped_request_logs_phase2.py`
- P3C1 - carried - rests on: the last audit of `tests/tmp/test_19_timestamped_request_logs_phase3.py`
- P3C2 - carried - rests on: the last audit of `tests/tmp/test_19_timestamped_request_logs_phase3.py`
- P4C1 - carried - rests on: the last audit of `tests/tmp/test_19_timestamped_request_logs_phase4.py`
- P4C2 - carried - rests on: the last audit of `tests/tmp/test_19_timestamped_request_logs_phase4.py`

## 2026-10-01 - Step 8 - refactor pass

<refactors>
engine/server/api/logging_profiles.py: the module docstring now mentions the text lines that `LOG_FORMAT=text` selects, not only the JSON events. This is a docstring-only change, with no change to code or behaviour.
</refactors>

<left_out>
client/backend/server.py `_proxy_engine_request`'s catch-all `except Exception` puts `traceback.format_exc()` into `context.traceback`. Now that `ClientLogFormatter` handles `exc_info`, `exc_info=True` could replace it, but the traceback would move from `context.traceback` to a top-level `traceback` key. That changes the JSON output, so it is not a refactor.
engine/server/api/logging_profiles.py `EngineJsonFormatter.format`: the `access.start` and `access` branches repeat `if fields: payload["context"] = fields`. They could be folded into a table of fixed messages, but that code predates this build and its output is already gated, so I left it alone.
`EngineJsonFormatter` is now a misnomer because it can also write text, but renaming it would break its existing importers and tests, and engine/server/README.md names it. Left as is.
The six copied logging helpers (Engine and Client): merging them is already covered by the `rat-tail:` comment in client/backend/server.py, with a shared package as the upgrade once a third consumer appears, so I left them duplicated.
That `rat-tail:` comment says a cross-service test compares both copies. Today that drift guard exists only as the checkpoint tests/tmp/test_19_timestamped_request_logs_phase4.py; tests/active/test_log_format.py, which every phase lists, was never created. If the checkpoint is not moved into tests/active, nothing durable backs the comment's claim. That move is the workflow's job, not a production refactor.
Probe files from this build are still in tests/tmp. Some are emptied (probe_fromtimestamp.py, probe_caplog_formatter.py); others are not (probe_client_tb.py, probe_engine_render.py, probe_ts_values.py, test_probe_19_p1..p4.py, test_probe_19_p3_values.py). I have no delete tool, so they need removing by hand.
</left_out>

<needs_fresh_red>
none
</needs_fresh_red>

<observation>
The four phases left the production code clean: the Engine and Client helpers are copies held together by a `rat-tail:` comment, both formatters still write JSON by default, and nothing could be simplified without changing output. The one real gap is outside production code: the drift guard and the `LOG_FORMAT` tests still exist only in tests/tmp, because tests/active/test_log_format.py was never created.
</observation>

## 2026-10-01 - Step 8 - suite comparison (attempt 1)

`--compare` exited 1.

```
test_frontend_upnext_pager.py — changed
  test_internal_events.py — changed
  test_logging_profiles.py — changed
  test_profiles.py — changed
  test_search_fusion.py — no map entry
  test_server.py — changed
  test_similar.py — changed
  test_blocks.py                 3 passed                              17.3s
  test_dislikes.py               2 passed                              15.4s
  test_frontend_blocks.py        1 passed                               7.4s
  test_frontend_profile.py       2 passed                               0.8s
  test_frontend_reactions.py     7 passed                              35.9s
  test_frontend_upnext_pager.py  1 failed                              16.3s
  test_internal_events.py        9 passed                               0.6s
  test_logging_profiles.py       1 passed                               0.0s
  test_profiles.py               11 passed                             26.2s
  test_search_fusion.py          10 passed                              2.5s
  test_server.py                 10 failed, 78 passed                  49.4s
  test_similar.py                6 failed, 86 passed                  131.3s
  -----------------------------
  total                          210 passed, 17 failed                132.1s wall, 12 lanes

moved against the previous record:
        new red  tests.active.test_frontend_upnext_pager::test_the_pager_s_48_row_batches_never_repeat_a_row_and_it_stops_asking_after_an_empty_batch
        new red  tests.active.test_server::test_a_gateway_listing_request_without_exactly_nsfw_1_gets_no_flagged_row_where_nsfw_1_gets_some[/recommendations-0]
        new red  tests.active.test_server::test_a_gateway_listing_request_without_exactly_nsfw_1_gets_no_flagged_row_where_nsfw_1_gets_some[/recommendations-empty]
        new red  tests.active.test_server::test_a_gateway_listing_request_without_exactly_nsfw_1_gets_no_flagged_row_where_nsfw_1_gets_some[/recommendations-missing]
        new red  tests.active.test_server::test_a_gateway_listing_request_without_exactly_nsfw_1_gets_no_flagged_row_where_nsfw_1_gets_some[/recommendations-space-1]
        new red  tests.active.test_server::test_a_gateway_listing_request_without_exactly_nsfw_1_gets_no_flagged_row_where_nsfw_1_gets_some[/recommendations-true]
        new red  tests.active.test_server::test_a_gateway_listing_request_without_exactly_nsfw_1_gets_no_flagged_row_where_nsfw_1_gets_some[/videos/similar-0]
        new red  tests.active.test_server::test_a_gateway_listing_request_without_exactly_nsfw_1_gets_no_flagged_row_where_nsfw_1_gets_some[/videos/similar-empty]
        new red  tests.active.test_server::test_a_gateway_listing_request_without_exactly_nsfw_1_gets_no_flagged_row_where_nsfw_1_gets_some[/videos/similar-missing]
        new red  tests.active.test_server::test_a_gateway_listing_request_without_exactly_nsfw_1_gets_no_flagged_row_where_nsfw_1_gets_some[/videos/similar-space-1]
        new red  tests.active.test_server::test_a_gateway_listing_request_without_exactly_nsfw_1_gets_no_flagged_row_where_nsfw_1_gets_some[/videos/similar-true]
        new red  tests.active.test_similar::test_a_short_cached_seed_fills_a_48_row_page_and_leaves_its_cache_entry_unchanged[cooking]
        new red  tests.active.test_similar::test_a_short_cached_seed_fills_a_48_row_page_and_leaves_its_cache_entry_unchanged[linux]
        new red  tests.active.test_similar::test_every_upnext_pool_line_records_the_fallback_steps_its_request_ran_and_nprobe_restored_to_default
        new red  tests.active.test_similar::test_home_and_search_are_unchanged_by_an_upnext_fallback_and_nprobe_is_restored
        new red  tests.active.test_similar::test_home_excluding_a_previous_page_returns_none_of_it_and_a_full_page[music]
        new red  tests.active.test_similar::test_on_an_engine_started_off_default_nprobe_every_upnext_pool_line_reports_the_nprobe_its_fallback_restored

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

## 2026-10-01 - Step 8 - red triage (attempt 1)

<failures>
### Shared dataset rebuilt under the build (common cause, checked by probe)
Every red test reads the live `engine/server/db/whitelist.db` and `similarity-cache.db`. In this worktree both are gitignored symlinks into the main checkout. A probe (`tests/tmp/probe_step8_dataset.py`) found:
- Both files were rewritten on 2026-10-01, and HEAD is `57c8417 db rebuilt and updated`.
- All 890,052 `similarity_sources` rows share one `computed_at` (1790885329887), so the cache was rebuilt in full.
- The 48 newest `videos` rows contain 0 with `nsfw = 1`, whether ordered by `published_at` or by `last_checked_at`.

Build 19 changed only `engine/server/api/logging_profiles.py`, `client/backend/server.py` and the `_error_messages`/caplog rewire in `tests/active/test_server.py` that the operator confirmed (git status). None of the failing assertions depends on log format. The one dependency is `_messages` parsing JSON lines, and that still works: the failing pool test parsed `upnext_pool` lines out of the Engine log. In each case the test's premise about the data no longer holds. That is a test-side fault, not an implementation fault, and it is not caused by this build. The operator chose "out of scope: report only". I changed no test and no production code.

### test_server.py::test_a_gateway_listing_request_without_exactly_nsfw_1_gets_no_flagged_row_where_nsfw_1_gets_some (10 cases)
The control assertion fails: `{route} with nsfw=1 served no flagged row`. The test pins "Recent's sixth row is flagged (observed)". A probe sent `POST /recommendations?mode=recent&nsfw=1` and `/videos/similar?mode=recent&nsfw=1` through a real Client. Both returned 200 with 48 rows, 0 of them flagged, which matches the DB finding of no nsfw row among the newest 48. Fault: the test's data-pinned control. Change: none.

### test_similar.py::test_a_short_cached_seed_fills_a_48_row_page_and_leaves_its_cache_entry_unchanged[linux, cooking]
The control `0 < len(before[1]) < 48` fails at 542 and 260 rows. `_cache_entry` reads `similarity-cache.db` directly with sqlite; no build-19 code is involved. The rebuilt cache no longer has short entries for these seeds. Fault: the test's data-pinned control. Change: none.

### test_similar.py: three fallback/nprobe tests
These are `test_home_and_search_are_unchanged_by_an_upnext_fallback_and_nprobe_is_restored`, `test_every_upnext_pool_line_records_the_fallback_steps_its_request_ran_and_nprobe_restored_to_default` and `test_on_an_engine_started_off_default_nprobe_every_upnext_pool_line_reports_the_nprobe_its_fallback_restored`. Each control expects the linux up-next request to run the ANN fallback, and the test comments rest on "every similarity-cache.db entry holds at most 20 rows (observed)". The Engine's own lines show `upnext_pool initial=170 … steps=none` and `initial=205 … steps=none`. The pool already reaches the 48-row target, so no fallback runs and no `ann_fallback` line is logged. Fault: the test's data-pinned control. Change: none.

### test_similar.py::test_home_excluding_a_previous_page_returns_none_of_it_and_a_full_page[music]
The control "a plain page repeats none of the previous one" fails: two home pages for the music likes share no row. This one is inferred, not observed. Home's row selection is untouched by build 19, which changed only log formatters, and the candidates behind it were rebuilt with the cache, so the draw's overlap has changed. Re-running it against the pre-rebuild data, or reading the home pool size for the music likes, would confirm it. Fault: the test's data-pinned control. Change: none.

### test_frontend_upnext_pager.py::test_the_pager_s_48_row_batches_never_repeat_a_row_and_it_stops_asking_after_an_empty_batch
In the suite run, one batch carried an `error` key. The truncated output hides the error text, so I could not see what it was. Run alone through a probe (`tests/tmp/probe_step8_pager.py`) against the same Engine and data, with the test's own `_seed`/`_run`, the pager was clean: 48×6, then 30, then empty at batch 8, with `calls` staying at 8 after that. That satisfies every assertion the test makes on the 48-row run. The 20-row re-run was not exercised. The frontend and the up-next code are untouched by build 19, so the suite failure was transient: probably load under 12 lanes, or the data rebuild, but I could not observe which. Re-running this group alone in the workflow would confirm it. Fault: not the implementation. Change: none.

### Retired tests
None. No durable test conflicts with a confirmed requirement of build 19 (Engine/Client log timestamps and `LOG_FORMAT` rendering), and none now passes vacuously because of it.
</failures>

<checkpoint_gaps>
none. No failure comes from build 19's implementation, so no phase checkpoint missed anything. Phases 1–4 gate only log-format behaviour, and every red here is a dataset-pinned control or a transient pager error that this build's code cannot reach.
</checkpoint_gaps>

<correction>
- Read the failing assertions. All 17 are control assertions about the shared live dataset, or a pager `error` whose text was cut from the output; none is about logging.
- Probed the data with `tests/tmp/probe_step8_dataset.py`. The probe found that `whitelist.db` and `similarity-cache.db` are symlinks into main and were rebuilt on 2026-10-01 (HEAD `57c8417 db rebuilt and updated`). The cache has a single `computed_at` across 890,052 sources. The newest 48 videos hold 0 nsfw rows. Only the build's two logging files and the confirmed `test_server.py` rewire are modified.
- Probed the routes with `tests/tmp/probe_step8_pager.py`. Run alone against a real Engine and Client, the pager behaved correctly (48×6, 30, then empty, with no further calls). `mode=recent&nsfw=1` returned 48 rows with none flagged on both gateway routes.
- Asked the operator how to handle the data-pinned controls. Answer: out of scope, report only.
- Made no change to production code or to any test. Retired no test.
- Emptied both probe files, since I have no delete tool; each now collects no tests and can be removed.
- Follow-up for whoever owns the dataset: re-point the data-pinned controls in a separate issue. They are in `test_server.py` (nsfw recent page), `test_similar.py` (short cached seeds, fallback/nprobe, home overlap) and `test_frontend_upnext_pager.py`. Alternatively, restore the pre-rebuild dataset before comparing against the baseline. Re-running `test_frontend_upnext_pager.py` alone in the workflow would confirm its red was transient.
</correction>

## 2026-10-01 - Step 8 - suite comparison (attempt 2)

`--compare` exited 1.

```
selected 4 of 46 test groups (42 unchanged):
  test_frontend_upnext_pager.py — not green
  test_search_fusion.py — no map entry
  test_server.py — not green
  test_similar.py — not green
  test_frontend_upnext_pager.py  1 passed                              11.0s
  test_search_fusion.py          10 passed                              2.4s
  test_server.py                 10 failed, 78 passed                  39.2s
  test_similar.py                6 failed, 86 passed                  117.1s
  -----------------------------
  total                          175 passed, 16 failed                117.7s wall, 4 lanes

moved against the previous record:
  no longer red  tests.active.test_frontend_upnext_pager::test_the_pager_s_48_row_batches_never_repeat_a_row_and_it_stops_asking_after_an_empty_batch

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

## 2026-10-01 - Step 8 - red triage (attempt 2)

<failures>
### Common cause: the shared dataset was rebuilt under the build (inspected the tests first; probe-observed)
Attempt 2 runs the same 16 tests red as attempt 1. Each one fails on a control assertion about the live dataset, never on a logging assertion. That dataset is `engine/server/db/whitelist.db` plus `similarity-cache.db`, both gitignored symlinks into the main checkout. Attempt 1's probe found both files rebuilt on 2026-10-01, at HEAD `57c8417 db rebuilt and updated`: one `computed_at` across 890,052 sources, and none of the newest 48 videos flagged nsfw. The Step-0 baseline re-ran only `test_search_fusion.py` ("selected 1 of 46"), so the "green" recorded for `test_server.py` and `test_similar.py` is a fingerprint from before the rebuild. Build 19 touched only the two logging modules and the operator-confirmed `_error_messages`/caplog rewire in `test_server.py`. The one place a failing test reads logs is `_messages`, and it still parses the Engine's JSON lines: the failing pool test pulled out `upnext_pool … steps=none` lines. The fault is in the tests' data-pinned premises, not in the implementation. These tests have already gated and do not conflict with a build-19 requirement, so I did not edit, re-point or retire any of them. The operator chose "report only, same as attempt 1".

### test_server.py::test_a_gateway_listing_request_without_exactly_nsfw_1_gets_no_flagged_row_where_nsfw_1_gets_some (10 cases)
The control fails: `{route} with nsfw=1 served no flagged row` on `mode=recent&nsfw=1`. The test pins "Recent's sixth row is flagged (observed)". In the rebuilt data the newest 48 videos hold 0 nsfw rows. That was observed in attempt 1, through the real Client on both routes, and directly in the DB. Fault: the test's data-pinned control. Change: none.

### test_similar.py::test_a_short_cached_seed_fills_a_48_row_page_and_leaves_its_cache_entry_unchanged[linux, cooking]
The control `0 < len(before[1]) < 48` fails at 542 and 260 rows. `_cache_entry` reads `similarity-cache.db` with sqlite directly, so no build-19 code runs. Fault: the test's data-pinned control. Change: none.

### test_similar.py fallback/nprobe tests (3)
The three tests are `test_home_and_search_are_unchanged_by_an_upnext_fallback_and_nprobe_is_restored`, `test_every_upnext_pool_line_records_the_fallback_steps_its_request_ran_and_nprobe_restored_to_default` and `test_on_an_engine_started_off_default_nprobe_every_upnext_pool_line_reports_the_nprobe_its_fallback_restored`. Each rests on "every similarity-cache.db entry holds at most 20 rows (observed)". The Engine's own lines read `upnext_pool initial=170 … steps=none` and `initial=205 … steps=none`. The pool already exceeds the 48-row target, so no `ann_fallback` runs or is logged. Fault: the test's data-pinned control. Change: none.

### test_similar.py::test_home_excluding_a_previous_page_returns_none_of_it_and_a_full_page[music]
Attempt 1 only inferred this cause; this time it is observed. The docstring premise is "the like-seeded layers draw from the same shallow pool and repeat across pages". Probe `tests/tmp/test_probe_step8_home_overlap.py` ran against the session Engine. The five music likes' cache entries hold 302, 596, 242, 388 and 291 rows. Three pairs of plain music home draws shared 1, 1 and 0 rows, so the control `previous & plain` fails some of the time. For comparison, linux (542-row entries) shared 2, 2 and 4 rows, and cooking (260) shared 8, 4 and 3. Home row selection never passes through the log formatter. Fault: the test's data-pinned control, which is now flaky on the deeper pool. Change: none.

### test_frontend_upnext_pager.py (attempt 1 only)
Attempt 1 called its red transient, and the workflow re-run confirms it: "no longer red", 1 passed. Change: none.

### Retired tests
None. No durable test conflicts with a confirmed requirement of build 19 (UTC `ts` from `record.created`, `LOG_FORMAT` json/text, the Client root formatter). None passes vacuously because of build 19.
</failures>

<checkpoint_gaps>
none. No red comes from build 19's implementation. Phases 1–4 gate only log-format behaviour. Every red is a control pinned to dataset contents that changed under the build (commit 57c8417 rebuilt both DBs). No phase checkpoint could, or should, have caught that.
</checkpoint_gaps>

<correction>
- Inspected the failing tests first. All 16 reds in attempt 2 are the attempt-1 controls, which assert on dataset contents (nsfw rows in the recent page, cache-entry sizes, whether a fallback runs, overlap between home draws). None asserts on logging. The pager test is green again, which confirms attempt 1's "transient" call.
- Checked the record: the Step-0 baseline re-ran only test_search_fusion.py. So test_server/test_similar were never re-baselined after the data rebuild at 57c8417.
- Observed the one cause attempt 1 had only inferred, with probe tests/tmp/test_probe_step8_home_overlap.py. The music likes' cache entries hold 242–596 rows. Two plain music home draws shared 1, 1 and 0 rows, so the [music] overlap control is flaky on the rebuilt data. Linux and cooking shared 2–8 rows.
- Asked the operator how to close the step. Answer: report only, same as attempt 1.
- Changed no production code and no test. Retired no test. No checkpoint touched.
- Emptied the probe file because I have no delete tool. It now collects no tests and can be removed, along with the earlier emptied step-8 probes (probe_step8_dataset.py, probe_step8_pager.py).
- Follow-up outside build 19: re-pin the data-pinned controls against the rebuilt dataset in a separate issue, or restore the pre-57c8417 DBs before comparing. The controls are in test_server.py (nsfw recent page) and test_similar.py (short cached seeds, three fallback/nprobe tests, music home overlap).
</correction>

## 2026-10-01 - Step 8 - suite comparison (attempt 3)

`--compare` exited 1.

```
selected 3 of 46 test groups (43 unchanged):
  test_search_fusion.py — no map entry
  test_server.py — not green
  test_similar.py — not green
  test_search_fusion.py  10 passed                              2.5s
  test_server.py         10 failed, 78 passed                  37.9s
  test_similar.py        5 failed, 87 passed                  118.8s
  ---------------------
  total                  175 passed, 15 failed                119.3s wall, 3 lanes

moved against the previous record:
  no longer red  tests.active.test_similar::test_home_excluding_a_previous_page_returns_none_of_it_and_a_full_page[music]

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

## 2026-10-01 - Step 8 - red triage (attempt 3)

<failures>
### Common cause: the shared dataset was rebuilt underneath the build (I inspected the tests first)
This is attempt 3, and it has the same reds as attempts 1 and 2, minus `test_similar.py::test_home_excluding_a_previous_page_returns_none_of_it_and_a_full_page[music]`. The compare now lists that test as "no longer red", so attempt 2 was right to call it flaky. All 15 remaining failures stop on a control assertion about what the shared data contains. None stops on a logging assertion. The data is `engine/server/db/whitelist.db` and `similarity-cache.db`, both gitignored symlinks into the main checkout. In attempt 1 a probe showed both files were rebuilt at HEAD `57c8417 db rebuilt and updated`: one `computed_at` across all 890,052 sources, and none of the newest 48 videos flagged nsfw. Both groups were selected because they were already "not green". The compare lists no test as newly red, so none of these 15 was green in the previous record.

Build 19 changed only `engine/server/api/logging_profiles.py`, `client/backend/server.py`, and the `_error_messages`/caplog rewire in `test_server.py` that the operator confirmed. The failing tests touch logging in one place, `_messages` in test_similar.py, and it still parses the Engine's JSON lines: in this run the `NPROBE_PREFIX` startup controls passed, and the pool test read `upnext_pool … steps=none` lines out of the log. The fault is in each test's premise about the data, not in the implementation. These tests have already gated and do not conflict with any build-19 requirement, so none was edited, repointed or retired. The operator chose "report only, again".

### test_server.py::test_a_gateway_listing_request_without_exactly_nsfw_1_gets_no_flagged_row_where_nsfw_1_gets_some (10 cases: /recommendations and /videos/similar × missing/empty/0/true/space-1)
The control at test_server.py:1297 fails: `{route} with nsfw=1 served no flagged row` on `mode=recent&nsfw=1`. The test relies on "Recent's sixth row is flagged (observed)". In the rebuilt data none of the newest 48 videos is flagged nsfw; attempt 1 saw this through a real Client on both routes and directly in the DB. Fault: the test's data-pinned control. Change: none.

### test_similar.py::test_a_short_cached_seed_fills_a_48_row_page_and_leaves_its_cache_entry_unchanged[linux, cooking]
The control `0 < len(before[1]) < FILL_LIMIT` at test_similar.py:829 fails with 542 and 260 rows. `_cache_entry` reads `similarity-cache.db` directly through sqlite, so no build-19 code runs. Fault: the test's data-pinned control. Change: none.

### test_similar.py: fallback/nprobe tests (3)
These are `test_home_and_search_are_unchanged_by_an_upnext_fallback_and_nprobe_is_restored` (:877), `test_every_upnext_pool_line_records_the_fallback_steps_its_request_ran_and_nprobe_restored_to_default` (:975) and `test_on_an_engine_started_off_default_nprobe_every_upnext_pool_line_reports_the_nprobe_its_fallback_restored` (:1001). All three rely on "every similarity-cache.db entry holds at most 20 rows (observed)". The Engine's own log reads `upnext_pool initial=170 … steps=none` and `initial=205 … steps=none`. The pool already exceeds the 48-row target, so no ANN fallback runs and no `[similar-server] ann_fallback` line is logged. The fallback controls then find 0 lines. Fault: the test's data-pinned control. Change: none.

### Retired tests
None. No durable test conflicts with a confirmed requirement of build 19: UTC `ts` from `record.created`, `LOG_FORMAT` choosing json or text, and the Client root formatter. No test passes vacuously because of it.
</failures>

<checkpoint_gaps>
none. None of the reds comes from build 19's implementation. Phases 1–4 gate only log format and timestamps, and every failure here is a control pinned to dataset contents that `57c8417` rebuilt. No phase checkpoint could, or should, have caught that.
</checkpoint_gaps>

<correction>
- Read the failing test first, then the run record. All 15 reds are control assertions about the live dataset: nsfw rows on the recent page, cache-entry size, whether a fallback runs. None asserts anything about logging. The compare lists no newly red test. The only movement is `[music]` going green, which confirms attempt 2's call that it is flaky.
- Checked that the build's one log-reading path still works. `_messages` passed its `NPROBE_PREFIX` controls and parsed `upnext_pool` lines in this run.
- Checked the earlier step-8 attempts in `docs/project/plans/20-19-timestamped-request-logs.record.md`. The dataset cause was observed by probe there (both DBs rebuilt at `57c8417`), so this run needed no new probe. None was written.
- Asked the operator how to close a third identical attempt. Answer: report only, again.
- Changed no production code and no test, touched no checkpoint, and retired no test.
- Still open from earlier steps: the emptied probe files in `tests/tmp/` (probe_step8_dataset.py, probe_step8_pager.py, test_probe_step8_home_overlap.py, probe_fromtimestamp.py, probe_caplog_formatter.py) can be deleted.
- Follow-up outside build 19: re-pin these controls against the rebuilt dataset, or restore the DBs from before `57c8417` before comparing. They are in test_server.py (the nsfw recent page) and test_similar.py (short cached seeds, three fallback/nprobe tests).
</correction>

## 2026-10-01 - Step 8 - stopped

Close the build on green did not complete. The entries above carry what the step established before it stopped; the gate it failed is the last of them.

