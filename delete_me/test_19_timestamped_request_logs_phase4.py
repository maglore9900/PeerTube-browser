"""The Client's `LOG_FORMAT` picks text or JSON for the same values the Engine's does, and its `_format_ts` and `_render_text` return the Engine's strings for the same input.

- In-process, after `configure_client_logging()` with the handler's stream swapped for a StringIO, the test logs `_emit_client_log(ERROR, "engine.call", "Engine metadata failed", {"error": "x\\ny"})`, a `logging.exception` for `ValueError("sentinel-client-log")`, `logging.info("bare")` and `_emit_client_log(INFO, "client.access", "request finished", {"ip": "127.0.0.1", "status": 200, "bytes": "-"})`.
- With `LOG_FORMAT` unset, `json`, `JSON`, `bogus` or empty, stderr is four JSON objects with a `ts` matching `TS_RE`, carrying the Client's phase-3 keys, order and values, and a traceback ending `ValueError: sentinel-client-log` on the exception record.
- With `text`, `TEXT`, ` Text ` or tab-`text`-newline, stderr is exactly four lines: none parses as a JSON object, none starts with `<`, and every one matches `<TS_RE> (INFO|ERROR) `. The rest is the Engine's line shape with no `service` token. The `engine.call` line ends `error=x\\ny` and the exception line ends with the traceback, where `\\n` is a backslash and an n. The access line reads `INFO client.access request finished ip=127.0.0.1 status=200 bytes=-`.
- An Engine child takes the `created` values 1741091696.789 and 1741091696.9999996 and two payloads: one holding a multi-line message and traceback, a null, a nested list and a `request_id` both in context and at top level; one with no message, a CR in a context value and a `request_id` only at top level. It prints `2025-03-04T12:34:56.789Z`, `2025-03-04T12:34:57.000Z` and the two observed text lines, and the Client's `_format_ts` and `_render_text` return the same strings in-process.
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
    print(json.dumps({"ts": stamps, "text": [_render_text(payload) for payload in json.loads(sys.argv[2])]}))
    """
)

CREATED = [1741091696.789, 1741091696.9999996]
# The second payload takes the branches the first skips: no message, request_id only at top level, a CR.
RENDER_PAYLOADS = [
    {"ts": "2025-03-04T12:34:57.000Z", "level": "INFO", "event": "e", "message": "m\nn", "context": {"a": 1, "b": None, "c": [1, {"d": "x"}], "request_id": "r"}, "request_id": "r", "traceback": "T\nU"},
    {"ts": "2025-03-04T12:34:56.789Z", "level": "ERROR", "event": "service.lifecycle", "context": {"state": "start", "note": "a\rb"}, "request_id": "q"},
]
# Observed from the Engine child: CR/LF escaped, None as null, the list as compact JSON, request_id written once from the context or appended from the top level.
ENGINE_TEXTS = ['2025-03-04T12:34:57.000Z INFO e m\\nn a=1 b=null c=[1,{"d":"x"}] request_id=r T\\nU', "2025-03-04T12:34:56.789Z ERROR service.lifecycle state=start note=a\\rb request_id=q"]


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
    run = subprocess.run([sys.executable, "-c", _ENGINE_CHILD, json.dumps(CREATED), json.dumps(RENDER_PAYLOADS)], cwd=API_DIR, capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stderr[-2000:]
    engine = json.loads(run.stdout)
    # Control: the child really rendered, so equality below compares real strings rather than empty ones.
    assert engine == {"ts": ["2025-03-04T12:34:56.789Z", "2025-03-04T12:34:57.000Z"], "text": ENGINE_TEXTS}, engine

    client_stamps = []
    for created in CREATED:
        record = logging.LogRecord("probe", logging.INFO, "probe", 1, "fixed", None, None)
        record.created = created
        client_stamps.append(client_server._format_ts(record))
    assert client_stamps == engine["ts"], (client_stamps, engine["ts"])  # C2
    client_texts = [client_server._render_text(payload) for payload in RENDER_PAYLOADS]
    assert client_texts == engine["text"], client_texts  # C2
