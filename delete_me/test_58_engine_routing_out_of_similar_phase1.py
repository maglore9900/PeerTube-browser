"""Engine routing through `engine/server/api/router.py`, over real HTTP into a real `SimilarServer` running the real `SimilarHandler` in an Engine child.

Bridge gate (POST `/internal/*`):

- The Engine token set, a POST to `/internal/videos/resolve`, `/internal/translate`, `/internal/events/ingest` or the unknown `/internal/no-such-route` answers 401 `{"error": "Unauthorized"}` without an `X-Bridge-Token` and with a near-miss one (the real token less its last character), and 503 `{"error": "Bridge token is not configured on the Engine"}` once the Engine's token is "".
- None of those requests reaches its route: the three routes' `POST_ROUTES` entries are recording stubs, which record nothing for them. With the right token each stub is reached exactly once, and the unknown path answers 404 `{"error": "Not found"}`.
- Before the stubs go in, a valid-token ingest under `engine_ingest_mode` None answers the router's own 501 with `mode: None`.
- A GET to `/internal/videos/resolve` answers a plain 404, with no gate.

Fake route (one `GET_ROUTES` entry, no edit to `handlers/similar.py`):

- Before the entry, GET `/fake` answers 404 `{"error": "Not found"}`.
- After `router.GET_ROUTES["/fake"]` is set, GET `/fake?x=1` answers 200 with the entry's body, which carries the raw request path, query included; the entry was called with the `SimilarHandler` serving the request and the `SimilarServer` itself.
- The entry serves only its exact path on GET: GET `/fake/` and POST `/fake` still answer 404.

The only shim is a replaced router table entry, never a patched module function: dispatch looks the table up per request. The server is built the `tests/active/test_video.py` way (`dict.fromkeys` over the constructor's parameters), so `db`, `rate_limiter` and `engine_ingest_mode` are None; none of these paths reaches the DB. Until `router` exists the children write to an unwired stand-in table, so the requests still run and the stub and `/fake` assertions read today's dispatch.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

# tests/tmp has no conftest, and tests/active's loads the Client backend: the same two expressions as conftest's, until this file is archived to tests/active.
ROOT = Path(__file__).resolve().parents[2]
ENGINE_PY = ROOT / "engine" / ".pixi" / "envs" / "default" / "bin" / "python"
API_DIR = ROOT / "engine" / "server" / "api"

STUBBED = ["/internal/videos/resolve", "/internal/translate", "/internal/events/ingest"]
PATHS = STUBBED + ["/internal/no-such-route"]
UNAUTHORIZED = [401, {"error": "Unauthorized"}]
UNSET = [503, {"error": "Bridge token is not configured on the Engine"}]
NOT_FOUND = [404, {"error": "Not found"}]

# Shared by both children: `server` first, so its sys.path setup puts engine/server on the path.
PRELUDE = r'''
import http.client, inspect, json, sys, threading, types
import server
try:
    import router
except ModuleNotFoundError as exc:
    if exc.name != "router":
        raise
    # Before the phase there is no router: an unwired table nothing reads lets every request still run, so the red lands on the assertions that judge routing, not on this import.
    router = types.SimpleNamespace(GET_ROUTES={}, POST_ROUTES={})
from handlers.similar import SimilarHandler
from http_utils import respond_json

def send(port, method, path, headers=None):
    try:
        client = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
        client.request(method, path, body=b"{}" if method == "POST" else None, headers=headers or {})
        resp = client.getresponse()
        body = json.loads(resp.read() or b"null")
        client.close()
        return [resp.status, body]
    except Exception as exc:
        return [None, repr(exc)]

args = dict.fromkeys(list(inspect.signature(server.SimilarServer.__init__).parameters)[3:])
srv = server.SimilarServer(("127.0.0.1", 0), SimilarHandler, **args)
threading.Thread(target=srv.serve_forever, daemon=True).start()
port = srv.server_address[1]
report = {}
'''

BRIDGE_CHILD = PRELUDE + r'''
TOKEN = "router-test-token"
STUBBED = json.loads(sys.argv[1])
PATHS = STUBBED + ["/internal/no-such-route"]
calls = []
def stub(handler, server_):
    calls.append(handler.path)
    respond_json(handler, 200, {"stub": handler.path})
# Set explicitly: the child's ENGINE_BRIDGE_TOKEN env (observed unset, so "") is not this test's input.
srv.bridge_token = TOKEN
try:
    report["ingest_mode"] = send(port, "POST", "/internal/events/ingest", {"X-Bridge-Token": TOKEN})
    for path in STUBBED:
        router.POST_ROUTES[path] = stub
    report["missing"] = {p: send(port, "POST", p) for p in PATHS}
    report["near_miss"] = {p: send(port, "POST", p, {"X-Bridge-Token": TOKEN[:-1]}) for p in PATHS}
    report["calls_rejected"] = list(calls)
    report["valid"] = {p: send(port, "POST", p, {"X-Bridge-Token": TOKEN}) for p in PATHS}
    report["calls_valid"] = list(calls)
    srv.bridge_token = ""
    report["unset"] = {p: send(port, "POST", p, {"X-Bridge-Token": TOKEN}) for p in PATHS}
    report["calls_after_unset"] = list(calls)
    report["get_internal"] = send(port, "GET", "/internal/videos/resolve", {"X-Bridge-Token": TOKEN})
finally:
    srv.shutdown()
    srv.server_close()
print(json.dumps(report))
'''

FAKE_CHILD = PRELUDE + r'''
seen = []
def fake(handler, server_):
    seen.append({"handler_is_similar": type(handler) is SimilarHandler, "server_is_srv": server_ is srv})
    respond_json(handler, 200, {"fake": True, "path": handler.path})
try:
    report["before"] = send(port, "GET", "/fake")
    router.GET_ROUTES["/fake"] = fake
    report["after"] = send(port, "GET", "/fake?x=1")
    report["trailing_slash"] = send(port, "GET", "/fake/")
    report["post"] = send(port, "POST", "/fake")
    report["seen"] = seen
finally:
    srv.shutdown()
    srv.server_close()
print(json.dumps(report))
'''


def _run(child: str, *argv: str) -> dict:
    assert ENGINE_PY.exists(), f"Engine interpreter missing at {ENGINE_PY}; run `pixi install` in engine/"
    run = subprocess.run([str(ENGINE_PY), "-c", child, *argv], cwd=API_DIR, capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stderr[-2000:]  # control: the Engine's interpreter built the server and ran every request
    return json.loads(run.stdout)


def test_internal_posts_answer_the_bridge_gate_before_their_route_runs():
    report = _run(BRIDGE_CHILD, json.dumps(STUBBED))
    # The router's own ingest adapter, before its entry is stubbed: a stub installed too early, or a lost 501 branch, reads anything else.
    assert report["ingest_mode"] == [501, {"error": "Bridge ingest is disabled in current ENGINE_INGEST_MODE", "mode": None}]
    # A gate run after the table lookup reads [200, {"stub": ...}] here; a gate keyed on known routes only reads 404 for the unknown path.
    assert report["missing"] == {path: UNAUTHORIZED for path in PATHS}  # C1
    # A prefix or containment compare in place of an exact one accepts the near-miss token.
    assert report["near_miss"] == {path: UNAUTHORIZED for path in PATHS}  # C1
    assert report["calls_rejected"] == []  # C1
    # Past the gate the POST_ROUTES entry is what runs, once per request, so the empty record above means the gate stopped the request; dispatch that bypasses the table, or a table copied at import, answers the real handlers' 400/501 here.
    assert report["valid"] == {**{path: [200, {"stub": path}] for path in STUBBED}, "/internal/no-such-route": NOT_FOUND}  # C1
    assert report["calls_valid"] == STUBBED  # C1
    # A gate that falls back to another token, or treats "" as a token, reads 401 or the stub's 200 here.
    assert report["unset"] == {path: UNSET for path in PATHS}  # C1
    assert report["calls_after_unset"] == STUBBED  # C1
    # GET /internal/* is ungated: a gate on both methods reads 401 here.
    assert report["get_internal"] == NOT_FOUND


def test_a_route_added_as_one_get_routes_entry_is_served_through_the_real_handler():
    report = _run(FAKE_CHILD)
    # control: nothing serves /fake until the entry exists, so the 200 below comes from the entry.
    assert report["before"] == NOT_FOUND
    # A table bound or copied at import still reads 404; the path proves the entry answered this request, query string and all.
    assert report["after"] == [200, {"fake": True, "path": "/fake?x=1"}]  # C2
    # Called once, for GET /fake?x=1 only, with the SimilarHandler serving it and the SimilarServer as `server`.
    assert report["seen"] == [{"handler_is_similar": True, "server_is_srv": True}]  # C2
    # Exact-path, GET-only: a prefix match reads 200 for /fake/, a method-blind table reads 200 for POST.
    assert report["trailing_slash"] == NOT_FOUND
    assert report["post"] == NOT_FOUND
