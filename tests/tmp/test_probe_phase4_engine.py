import json
import subprocess
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE_PY = ROOT / "engine" / ".pixi" / "envs" / "default" / "bin" / "python"
SERVER_DIR = ROOT / "engine" / "server"

CHILD = textwrap.dedent(
    """
    import json, sys, types
    sys.path[:0] = [sys.argv[1], sys.argv[2]]
    from handlers.similar import SimilarHandler

    class Limiter:
        def __init__(self):
            self.keys = []
        def allow(self, key):
            self.keys.append(key)
            return True

    out = []
    for headers in json.loads(sys.argv[3]):
        stub = types.SimpleNamespace(headers=headers, client_address=("127.0.0.1", 50000), server=types.SimpleNamespace(rate_limiter=Limiter()))
        stub._get_client_ip = types.MethodType(SimilarHandler._get_client_ip, stub)
        allowed = SimilarHandler._rate_limit_check(stub, "/recommendations")
        out.append({"allowed": allowed, "keys": stub.server.rate_limiter.keys})
    print(json.dumps(out))
    """
)


def test_probe():
    cases = [{"X-Forwarded-For": "6.6.6.6, 203.0.113.9", "X-Real-IP": "7.7.7.7"}, {"X-Client-IP": " 203.0.113.9 ", "X-Forwarded-For": "6.6.6.6"}, {"X-Real-IP": "7.7.7.7"}, {}]
    print("EXISTS", ENGINE_PY.exists(), ENGINE_PY)
    run = subprocess.run([str(ENGINE_PY), "-c", CHILD, str(SERVER_DIR / "api"), str(SERVER_DIR), json.dumps(cases)], capture_output=True, text=True, timeout=120)
    print("RC", run.returncode)
    print("STDOUT", run.stdout)
    print("STDERR", run.stderr[-3000:])
    assert False
