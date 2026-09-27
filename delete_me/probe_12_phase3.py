import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "client" / "backend"))

import server as client_server  # noqa: E402


def test_probe():
    d = client_server.DEFAULT_TRUSTED_PROXY_NETWORKS
    r = client_server.resolve_client_address
    out = [r("127.0.0.1", "6.6.6.6, 203.0.113.9, 127.0.0.1", d), r("127.0.0.1", "198.51.100.4, 203.0.113.9, 127.0.0.1", d), r("127.0.0.1", "198.51.100.1, 203.0.113.10", d)]
    assert out is None
