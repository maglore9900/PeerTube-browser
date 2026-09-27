import json
import subprocess
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE_PY = ROOT / "engine" / ".pixi" / "envs" / "default" / "bin" / "python"
SERVER_DIR = ROOT / "engine" / "server"

CHILD = textwrap.dedent(
    """
    import http.client, json, sys, types
    sys.path[:0] = [sys.argv[1], sys.argv[2]]
    from handlers.similar import SimilarHandler
    from http_utils import RateLimiter

    def fixed(self):
        v = self.headers.get("X-Client-IP", "").strip()
        return v or self.client_address[0]

    def real_ip_fallback(self):
        v = self.headers.get("X-Client-IP", "").strip() or self.headers.get("X-Real-IP", "").strip()
        return v or self.client_address[0]

    def loopback(self):
        v = self.headers.get("X-Client-IP", "").strip()
        return v or "127.0.0.1"

    res = {}
    for name, fn in [("fixed", fixed), ("real_ip_fallback", real_ip_fallback), ("loopback", loopback)]:
        out = []
        for sequence in json.loads(sys.argv[3]):
            limiter = RateLimiter(1, 3600)
            allowed = []
            for peer, headers in sequence:
                message = http.client.HTTPMessage()
                for k, v in headers.items():
                    message[k] = v
                stub = types.SimpleNamespace(headers=message, client_address=(peer, 50000), server=types.SimpleNamespace(rate_limiter=limiter))
                stub._get_client_ip = types.MethodType(fn, stub)
                allowed.append(SimilarHandler._rate_limit_check(stub, "/recommendations"))
            out.append({"allowed": allowed, "buckets": sorted(limiter.requests)})
        res[name] = out
    print(json.dumps(res))
    """
)


def test_probe():
    forwarded_sequence = [["127.0.0.1", {"X-Forwarded-For": "6.6.6.6, 203.0.113.9", "X-Real-IP": "7.7.7.7"}], ["127.0.0.1", {"X-Forwarded-For": "8.8.8.8", "X-Real-IP": "9.9.9.9"}], ["192.0.2.10", {"X-Forwarded-For": "6.6.6.6", "X-Real-IP": "7.7.7.7"}]]
    client_ip_sequence = [["127.0.0.1", {"X-Client-IP": " 203.0.113.9 ", "X-Forwarded-For": "6.6.6.6"}], ["127.0.0.1", {"X-Client-IP": "198.51.100.4", "X-Forwarded-For": "6.6.6.6"}]]
    run = subprocess.run([str(ENGINE_PY), "-c", CHILD, str(SERVER_DIR / "api"), str(SERVER_DIR), json.dumps([forwarded_sequence, client_ip_sequence])], capture_output=True, text=True, timeout=120)
    print("RC", run.returncode)
    print("STDOUT", run.stdout)
    print("STDERR", run.stderr[-3000:])
    assert False
