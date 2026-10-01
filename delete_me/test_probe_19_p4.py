from __future__ import annotations

import io
import json
import logging
import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
API_DIR = ROOT / "engine" / "server" / "api"
ACTIVE = ROOT / "tests" / "active"
if str(ACTIVE) not in sys.path:
    sys.path.insert(0, str(ACTIVE))

from conftest import client_server  # noqa: E402

CHILD = textwrap.dedent(
    """
    import json, logging, sys
    from logging_profiles import _format_ts, _render_text, normalize_log_format
    record = logging.LogRecord("probe", logging.INFO, "probe", 1, "fixed", None, None)
    record.created = float(sys.argv[1])
    print(json.dumps({"ts": _format_ts(record), "text": _render_text(json.loads(sys.argv[2]))}))
    """
)

PAYLOAD = {"ts": "2025-03-04T12:34:57.000Z", "level": "INFO", "event": "e", "message": "m\nn", "context": {"a": 1, "b": None, "c": [1, {"d": "x"}], "request_id": "r"}, "request_id": "r", "traceback": "T\nU"}


def test_probe():
    print("PY", sys.version)
    run = subprocess.run([sys.executable, "-c", CHILD, "1741091696.9999996", json.dumps(PAYLOAD)], cwd=API_DIR, capture_output=True, text=True, timeout=60)
    print("RC", run.returncode, "STDERR", run.stderr)
    print("STDOUT", repr(run.stdout))
    print("CLIENT ATTRS", [name for name in ("normalize_log_format", "_format_ts", "_text_value", "_render_text") if hasattr(client_server, name)])
    root = logging.getLogger()
    saved, level = root.handlers[:], root.level
    try:
        client_server.configure_client_logging()
        stream = io.StringIO()
        root.handlers[0].setStream(stream)
        try:
            raise ValueError("sentinel-client-log")
        except ValueError:
            logging.exception("client probe failed")
        client_server._emit_client_log(logging.INFO, "client.access", "request finished", {"ip": "127.0.0.1", "status": 200, "bytes": "-"})
    finally:
        root.handlers[:] = saved
        root.setLevel(level)
    print("LINES", repr(stream.getvalue()))
    assert False
