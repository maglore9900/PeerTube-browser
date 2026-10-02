import json
import logging
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

ENGINE_CHILD = """
import json, logging
from logging_profiles import EngineJsonFormatter
f = EngineJsonFormatter()
out = []
for msg, extra, level in [("[request.start] request started", {"structured_context": {"ip": "1", "method": "GET", "url": "u", "user_agent": "a b"}}, logging.INFO), ("[request.end] request finished", {"structured_context": {"status": 200, "duration_ms": 3}}, logging.INFO), ("[request.end] request finished", {}, logging.INFO), ("[request.start] x", {}, logging.WARNING), ("[probe] plain k=v", {}, logging.INFO)]:
    r = logging.LogRecord("p", level, "p", 1, msg, None, None)
    for k, v in extra.items():
        setattr(r, k, v)
    p = json.loads(f.format(r)); p.pop("ts")
    out.append(p)
print(json.dumps(out))
"""

CLIENT_CHILD = """
import server
print(server.REQUEST_ID_HEADER, server.resolve_request_id("probe.id-1"), len(server.resolve_request_id("a b")))
"""


def test_probe():
    engine = subprocess.run([sys.executable, "-c", ENGINE_CHILD], cwd=ROOT / "engine" / "server" / "api", capture_output=True, text=True)
    print(engine.stdout, engine.stderr)
    client = subprocess.run([sys.executable, "-c", CLIENT_CHILD], cwd=ROOT / "client" / "backend", capture_output=True, text=True)
    print(client.stdout, client.stderr)
    assert False
