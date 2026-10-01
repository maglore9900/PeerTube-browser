"""Probe: today's Client emit ts under +05:45, and a naive millisecond truncation at the .9999996 edge."""
from __future__ import annotations

import io
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ACTIVE = Path(__file__).resolve().parents[1] / "active"
if str(ACTIVE) not in sys.path:
    sys.path.insert(0, str(ACTIVE))

from conftest import client_server  # noqa: E402


def test_values(monkeypatch):
    monkeypatch.setenv("TZ", "Asia/Kathmandu")
    time.tzset()
    root = logging.getLogger()
    saved, level = root.handlers[:], root.level
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    root.handlers[:] = [handler]
    root.setLevel(logging.INFO)
    try:
        client_server._emit_client_log(logging.ERROR, "engine.call", "Engine metadata failed", {"error": "x\ny"})
        try:
            raise ValueError("sentinel-client-log")
        except ValueError:
            logging.exception("client probe failed")
        logging.info("bare")
    finally:
        root.handlers[:] = saved
        root.setLevel(level)
        monkeypatch.undo()
        time.tzset()
    print("TODAY", repr(stream.getvalue()))
    created = 1741091696.9999996
    naive = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(created)) + f".{int((created % 1) * 1000):03d}Z"
    proper = datetime.fromtimestamp(created, tz=timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    print("NAIVE", naive, "PROPER", proper)
    print("FIXED", datetime.fromtimestamp(1741091696.789, tz=timezone.utc).isoformat(timespec="milliseconds"))
