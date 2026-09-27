"""How the Engine's `SimilarHandler._rate_limit_check` buckets requests in its real `RateLimiter` (one request per bucket), with the client address resolved by the real `_get_client_ip`.

- With `X-Forwarded-For` and `X-Real-IP` but no `X-Client-IP`, the bucket is the TCP peer: a second request from the same peer is refused whatever it forwards, and a request from another peer gets its own bucket.
- With `X-Client-IP`, the bucket is its stripped value even when `X-Forwarded-For` is also sent, so two callers behind one peer are limited separately.
"""
from __future__ import annotations

import json
import subprocess
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE_PY = ROOT / "engine" / ".pixi" / "envs" / "default" / "bin" / "python"
SERVER_DIR = ROOT / "engine" / "server"

# Runs under the Engine interpreter: importing handlers.similar needs numpy and faiss, which only its pixi env carries.
_CHILD = textwrap.dedent(
    """
    import http.client, json, sys, types
    sys.path[:0] = [sys.argv[1], sys.argv[2]]
    from handlers.similar import SimilarHandler
    from http_utils import RateLimiter

    out = []
    for sequence in json.loads(sys.argv[3]):
        limiter = RateLimiter(1, 3600)
        allowed = []
        for peer, headers in sequence:
            message = http.client.HTTPMessage()
            for name, value in headers.items():
                message[name] = value
            stub = types.SimpleNamespace(headers=message, client_address=(peer, 50000), server=types.SimpleNamespace(rate_limiter=limiter))
            stub._get_client_ip = types.MethodType(SimilarHandler._get_client_ip, stub)
            allowed.append(SimilarHandler._rate_limit_check(stub, "/recommendations"))
        out.append({"allowed": allowed, "buckets": sorted(limiter.requests)})
    print(json.dumps(out), flush=True)
    """
)


def test_engine_limiter_buckets_on_x_client_ip_else_the_tcp_peer():
    assert ENGINE_PY.exists(), f"Engine interpreter missing at {ENGINE_PY}; run `pixi install` in engine/"
    forwarded_sequence = [["127.0.0.1", {"X-Forwarded-For": "6.6.6.6, 203.0.113.9", "X-Real-IP": "7.7.7.7"}], ["127.0.0.1", {"X-Forwarded-For": "8.8.8.8", "X-Real-IP": "9.9.9.9"}], ["192.0.2.10", {"X-Forwarded-For": "6.6.6.6", "X-Real-IP": "7.7.7.7"}]]
    client_ip_sequence = [["127.0.0.1", {"X-Client-IP": " 203.0.113.9 ", "X-Forwarded-For": "6.6.6.6"}], ["127.0.0.1", {"X-Client-IP": "198.51.100.4", "X-Forwarded-For": "6.6.6.6"}]]
    run = subprocess.run([str(ENGINE_PY), "-c", _CHILD, str(SERVER_DIR / "api"), str(SERVER_DIR), json.dumps([forwarded_sequence, client_ip_sequence])], capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stderr[-2000:]
    forwarded, client_ip = json.loads(run.stdout)

    # Control: X-Client-IP still wins over X-Forwarded-For and the peer, so a limiter bucketing every request on the peer cannot pass.
    assert client_ip == {"allowed": [True, True], "buckets": ["198.51.100.4:/recommendations", "203.0.113.9:/recommendations"]}
    # Unfixed code buckets on the first X-Forwarded-For hop and reads [True, True, False]; one dropping only X-Forwarded-For buckets on X-Real-IP the same way; one hardcoding loopback refuses the third.
    assert forwarded == {"allowed": [True, False, True], "buckets": ["127.0.0.1:/recommendations", "192.0.2.10:/recommendations"]}  # C1
