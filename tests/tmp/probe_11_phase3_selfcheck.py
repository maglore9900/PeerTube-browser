import sys
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))
from conftest import RateLimiter  # noqa: E402
from test_11_fast_similars_response_phase3 import QUERY, _engine_stub, _get  # noqa: E402
from test_server import _client_backend, _serving, _status  # noqa: E402


def test_probe(tmp_path):
    received = []
    with _serving(ThreadingHTTPServer(("127.0.0.1", 0), _engine_stub(received, 0))) as engine_base, _client_backend(tmp_path, engine_base, RateLimiter(1000, 60)) as base:
        print("video body", _get(base, f"/api/video?{QUERY}"))
        print("video refresh_cache", _status(base, "GET", f"/api/video?{QUERY}&refresh_cache=1", {}))
        print("video repeated id", _status(base, "GET", f"/api/video?id=uuid-2&{QUERY}", {}))
    print("received", received)
    received.clear()
    with _serving(ThreadingHTTPServer(("127.0.0.1", 0), _engine_stub(received, 1.5))) as engine_base, _client_backend(tmp_path, engine_base, RateLimiter(1000, 60)) as base:
        started = time.monotonic()
        print("slow video default timeout", _status(base, "GET", f"/api/video?{QUERY}", {}), round(time.monotonic() - started, 2))
    print("received", received)
