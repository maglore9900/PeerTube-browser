"""The Engine's `LOG_FORMAT` selects one escaped text line per record for `text` in any case or padding, and today's JSON for anything else.

- `configure_engine_logging("verbose")` in a child, with `LOG_FORMAT` removed from its env and then set to the case value, logs five records: `[probe] plain`, `[probe] two\\r\\nlines`, a `logging.exception("[probe] failed")` for `ValueError("sentinel-log-format")` with request_id `rid-p2`, an `[access.start]` record with request_id `rid-a` and a `[service] lifecycle` record.
- Unset, `json`, `JSON`, `bogus` or empty: stderr is five JSON objects, each with a `ts` matching `TS_RE`, a traceback on the exception record ending `ValueError: sentinel-log-format`, and otherwise the same keys, order and values as the JSON written before `LOG_FORMAT` existed.
- `text`, `TEXT`, ` Text ` or tab-`text`-newline: stderr is exactly five lines. None parses as a JSON object or starts with `<`. Each line is `<TS_RE> LEVEL event`, then the message if there is one, the context as `k=v`, `request_id=…` and the traceback, with CR and LF written as the two characters `\\r` and `\\n`. The exception line puts `request_id=rid-p2` before the traceback and ends `ValueError: sentinel-log-format`. The access.start line reads `request started ip=127.0.0.1 method=GET url=http://x/a request_id=rid-a`, context before request_id. The lifecycle line has no message token.
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
    logging.info("[access.start] ip=127.0.0.1 method=GET url=http://x/a", extra={"request_id": "rid-a"})
    logging.info("[service] lifecycle state=start component=engine run_id=r pid=1")
    """
)

# Today's JSON payloads for the five records, less `ts` and `traceback` (observed before this phase; the CR/LF message falls back to engine.log).
JSON_PAYLOADS = [
    {"level": "INFO", "event": "probe.info", "message": "[probe] plain", "modes": ["verbose"]},
    {"level": "INFO", "event": "engine.log", "message": "[probe] two\r\nlines", "modes": ["verbose"]},
    {"level": "ERROR", "event": "probe.info", "message": "[probe] failed", "modes": ["focused", "verbose"], "request_id": "rid-p2"},
    {"level": "INFO", "event": "access.start", "message": "request started", "modes": ["focused", "verbose"], "request_id": "rid-a", "context": {"ip": "127.0.0.1", "method": "GET", "url": "http://x/a"}},
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


@pytest.mark.parametrize("value", ["text", "TEXT", " Text ", "\ttext\n"])
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
    # The context tokens precede request_id.
    assert access_start == "INFO access.start request started ip=127.0.0.1 method=GET url=http://x/a request_id=rid-a", access_start  # C2
    # service.lifecycle carries no message, so its context follows the event directly.
    assert lifecycle == "INFO service.lifecycle state=start component=engine run_id=r pid=1", lifecycle  # C2
