import json
import subprocess
import sys
import textwrap
from pathlib import Path

API_DIR = Path(__file__).resolve().parents[2] / "engine" / "server" / "api"

CHILD = textwrap.dedent(
    """
    import json, logging, sys
    from logging_profiles import _render_text, normalize_log_format
    try:
        raise ValueError("sentinel-client-log")
    except ValueError:
        tb = logging.Formatter().formatException(sys.exc_info())
    payloads = [
        {"ts": "T", "level": "ERROR", "service": "client-backend", "event": "engine.call", "message": "Engine metadata failed", "context": {"error": "x\\ny"}},
        {"ts": "T", "level": "ERROR", "service": "client-backend", "event": "client.log", "message": "client probe failed", "traceback": tb},
        {"ts": "T", "level": "INFO", "service": "client-backend", "event": "client.log", "message": "bare"},
        {"ts": "T", "level": "INFO", "service": "client-backend", "event": "client.access", "message": "request finished", "context": {"ip": "127.0.0.1", "status": 200, "bytes": "-"}},
        {"ts": "2025-03-04T12:34:56.789Z", "level": "ERROR", "event": "service.lifecycle", "context": {"state": "start", "note": "a\\rb"}, "request_id": "q"},
    ]
    print(json.dumps({"formats": {repr(v): normalize_log_format(v) for v in [None, "json", "JSON", "bogus", "", "text", "TEXT", " Text ", "\\ttext\\n"]}, "lines": [_render_text(p) for p in payloads]}))
    """
)


def test_probe():
    run = subprocess.run([sys.executable, "-c", CHILD], cwd=API_DIR, capture_output=True, text=True, timeout=120)
    print(run.stderr)
    out = json.loads(run.stdout)
    for k, v in out["formats"].items():
        print("FORMAT", k, v)
    for line in out["lines"]:
        print("LINE", repr(line))
    assert False
