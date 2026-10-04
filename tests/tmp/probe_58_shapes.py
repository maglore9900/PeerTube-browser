import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE_PY = ROOT / "engine" / ".pixi" / "envs" / "default" / "bin" / "python"
API_DIR = ROOT / "engine" / "server" / "api"

CHILD = r'''
import http.client, inspect, json, sys, threading
import server
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

seen = []
calls = []
def fake(handler, server_):
    seen.append({"handler_is_similar": isinstance(handler, SimilarHandler), "server_is_srv": server_ is srv})
    respond_json(handler, 200, {"fake": True, "path": handler.path})
def stub(handler, server_):
    calls.append(handler.path)
    respond_json(handler, 200, {"stub": handler.path})

class Probe(SimilarHandler):
    def _dispatch_get(self):
        if self.path.startswith("/fake"):
            return fake(self, self.server)
        return super()._dispatch_get()
    def _dispatch_post(self):
        if self.path == "/stubbed":
            return stub(self, self.server)
        return super()._dispatch_post()

args = dict.fromkeys(list(inspect.signature(server.SimilarServer.__init__).parameters)[3:])
srv = server.SimilarServer(("127.0.0.1", 0), Probe, **args)
threading.Thread(target=srv.serve_forever, daemon=True).start()
port = srv.server_address[1]
srv.bridge_token = "tok"
report = {
    "fake": send(port, "GET", "/fake?x=1"),
    "stub": send(port, "POST", "/stubbed"),
    "seen": seen, "calls": calls,
    "valid_real": {p: send(port, "POST", p, {"X-Bridge-Token": "tok"}) for p in ["/internal/videos/resolve", "/internal/translate", "/internal/events/ingest", "/internal/no-such-route"]},
}
report["get_internal"] = send(port, "GET", "/internal/videos/resolve", {"X-Bridge-Token": "tok"})
report["post_fake"] = send(port, "POST", "/fake")
srv.bridge_token = ""
report["unset"] = {p: send(port, "POST", p, {"X-Bridge-Token": "tok"}) for p in ["/internal/videos/resolve", "/internal/no-such-route"]}
srv.shutdown(); srv.server_close()
print(json.dumps(report))
'''


def test_probe():
    run = subprocess.run([str(ENGINE_PY), "-c", CHILD], cwd=API_DIR, capture_output=True, text=True, timeout=120)
    print("RC", run.returncode)
    print("OUT", run.stdout)
    print("ERR", run.stderr[-3000:])
    assert False
