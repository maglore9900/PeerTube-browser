"""The Engine's production `EngineJsonFormatter` writes an exception record's traceback under a `traceback` key, and only for such records.

- `configure_engine_logging("verbose")` in a child: a `logging.exception` record renders as a JSON line whose `traceback` is a string starting `Traceback (most recent call last):` and ending with the exception's `ValueError: <text>` line, while its `message` stays the logged text; an INFO record and an ERROR record logged without an exception carry no `traceback` key.

Every stderr line of the child is parsed as JSON, so a log written by `logging.lastResort` instead of the production formatter fails the test.
"""
from __future__ import annotations

import json
import subprocess
import sys
import textwrap

from conftest import ROOT

API_DIR = ROOT / "engine" / "server" / "api"
TRACEBACK_HEAD = "Traceback (most recent call last):"

# Logs through the production formatter only: an INFO record, an ERROR record with no exception, and a logging.exception record.
_FORMAT_CHILD = textwrap.dedent(
    """
    import logging
    from logging_profiles import configure_engine_logging
    configure_engine_logging("verbose")
    logging.info("[probe] plain")
    logging.error("[probe] failed without exception")
    try:
        raise ValueError("sentinel-format-7b3e")
    except ValueError:
        logging.exception("[probe] failed")
    """
)


def test_formatter_writes_the_traceback_of_an_exception_record_only():
    # logging_profiles imports only the stdlib and request_context, so pytest's own interpreter can run it.
    run = subprocess.run([sys.executable, "-c", _FORMAT_CHILD], cwd=API_DIR, capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stderr[-2000:]
    lines = [json.loads(line) for line in run.stderr.splitlines()]
    assert all(isinstance(line, dict) for line in lines), run.stderr[-2000:]
    plain, no_exc, failed = lines

    # Control: the three records reached stderr through the formatter, in order.
    assert [plain["message"], no_exc["message"], failed["message"]] == ["[probe] plain", "[probe] failed without exception", "[probe] failed"]
    assert [plain["level"], no_exc["level"], failed["level"]] == ["INFO", "ERROR", "ERROR"]

    traceback = failed.get("traceback")
    assert isinstance(traceback, str) and traceback.startswith(TRACEBACK_HEAD), failed
    assert traceback.rstrip().endswith("ValueError: sentinel-format-7b3e"), traceback
    # Only a record carrying an exception gets the key.
    assert "traceback" not in plain and "traceback" not in no_exc
