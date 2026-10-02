"""Probe: the lifecycle child against the current tree, and the session Engine's log around one POST /recommendations."""
import json
import subprocess
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ACTIVE = ROOT / "tests" / "active"
if str(ACTIVE) not in sys.path:
    sys.path.insert(0, str(ACTIVE))

from conftest import ENGINE_PY, WHITELIST_DB, engine  # noqa: E402,F401

API_DIR = ROOT / "engine" / "server" / "api"

CHILD = r'''
import http.client, inspect, io, json, logging, sqlite3, sys, threading, time
from pathlib import Path
import server
from data.db import connect_db
from handlers.similar import SimilarHandler
from logging_profiles import EngineJsonFormatter
print("ROOT_HANDLERS_AFTER_IMPORT", logging.getLogger().handlers, logging.getLogger().level, file=sys.stderr)
stream = io.StringIO()
handler = logging.StreamHandler(stream)
handler.setFormatter(EngineJsonFormatter())
root = logging.getLogger()
root.handlers[:] = [handler]
root.setLevel(logging.INFO)

class Refusing:
    def allow(self, key):
        return False

class InterruptedHandler(SimilarHandler):
    def _dispatch_get(self):
        time.sleep(0.25)
        raise sqlite3.OperationalError("interrupted")

class KeepAliveHandler(SimilarHandler):
    protocol_version = "HTTP/1.1"
    def handle_one_request(self):
        super().handle_one_request()
        logging.info("[probe] between requests")

conn = connect_db(Path(sys.argv[1]))
args = dict.fromkeys(list(inspect.signature(server.SimilarServer.__init__).parameters)[3:])
def start(cls):
    srv = server.SimilarServer(("127.0.0.1", 0), cls, **{**args, "db": conn})
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv
main, interrupted, keep = start(SimilarHandler), start(InterruptedHandler), start(KeepAliveHandler)
baseline = threading.active_count()
print("LINES_AFTER_START", len(stream.getvalue().splitlines()), file=sys.stderr)
def settle():
    deadline = time.time() + 10
    while threading.active_count() > baseline and time.time() < deadline:
        time.sleep(0.01)
    return threading.active_count()
out = []
def send(srv, method, path, headers, body=None):
    before = len(stream.getvalue().splitlines())
    t0 = time.perf_counter()
    c = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=30)
    c.request(method, path, body=body, headers=headers)
    r = c.getresponse(); r.read(); c.close()
    left = settle()
    out.append({"path": path, "headers": headers, "status": r.status, "left": left, "ms": (time.perf_counter() - t0) * 1000, "lines": stream.getvalue().splitlines()[before:]})
send(main, "GET", "/api/health", {"X-Request-ID": "probe.id-1"})
send(main, "GET", "/api/health", {"X-Request-ID": "bad id"})
send(main, "GET", "/api/health", {"X-Request-ID": "a/b"})
send(main, "GET", "/nope", {})
main.rate_limiter = Refusing()
send(main, "GET", "/api/channels", {})
main.rate_limiter = None
send(main, "POST", "/recommendations", {"Content-Type": "application/json"}, b"{")
send(interrupted, "GET", "/api/health", {})
before = len(stream.getvalue().splitlines())
c = http.client.HTTPConnection("127.0.0.1", keep.server_address[1], timeout=30)
c.request("GET", "/nope"); r1 = c.getresponse(); r1.read()
print("THREADS_MID_KEEPALIVE", threading.active_count(), baseline, file=sys.stderr)
c.request("GET", "/api/health"); r2 = c.getresponse(); r2.read()
c.close()
left = settle()
out.append({"keepalive": [r1.status, r2.status], "left": left, "lines": stream.getvalue().splitlines()[before:]})
print(json.dumps(out, indent=1))
'''


def test_probe_env():
    print("ENGINE_PY", ENGINE_PY, ENGINE_PY.exists())
    print("WHITELIST_DB", WHITELIST_DB, WHITELIST_DB.exists())
    print("PYTEST_PY", sys.executable)
    assert False, "probe"


def test_probe_child(tmp_path):
    run = subprocess.run([str(ENGINE_PY), "-c", CHILD, str(tmp_path / "engine.db")], cwd=API_DIR, capture_output=True, text=True, timeout=120)
    print("RC", run.returncode)
    print("STDERR", run.stderr[-4000:])
    print("STDOUT", run.stdout[-12000:])
    assert False, "probe"


def test_probe_session_engine(engine):
    marker = f"log-order-{uuid.uuid4().hex}"
    status, body = engine.request("POST", f"/recommendations?limit=5&user_id={marker}", body={})
    print("STATUS", status, body.get("seed") if isinstance(body, dict) else body)
    time.sleep(1)
    lines = engine.db_path.read_text(errors="replace").splitlines()
    idx = [i for i, line in enumerate(lines) if marker in line]
    print("MARKED", idx, len(lines))
    if idx:
        for line in lines[max(0, idx[0] - 3): idx[-1] + 4]:
            print("LINE", line[:400])
    print("NONJSON", [line[:200] for line in lines if not line.startswith("{")][:20])
    assert False, "probe"
