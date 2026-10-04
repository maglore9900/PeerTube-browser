import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _path in (ROOT / "client" / "backend", ROOT / "engine" / "server", ROOT / "engine" / "server" / "api"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))


def test_probe():
    import server_config
    import handlers.internal_translate as handler

    spec = importlib.util.spec_from_file_location("translate_worker_probe", ROOT / "engine" / "server" / "db" / "jobs" / "translate-worker.py")
    worker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(worker)
    print("fresh", server_config.HEARTBEAT_FRESH_MS, type(server_config.HEARTBEAT_FRESH_MS), handler.HEARTBEAT_FRESH_MS is server_config.HEARTBEAT_FRESH_MS)
    print("worker beat", worker.HEARTBEAT_SECONDS, worker.HEARTBEAT_SECONDS is server_config.HEARTBEAT_SECONDS)
    assert False, "show output"
