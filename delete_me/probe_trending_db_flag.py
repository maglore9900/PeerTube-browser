import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ACTIVE = ROOT / "tests" / "active"
if str(ACTIVE) not in sys.path:
    sys.path.insert(0, str(ACTIVE))
_SPEC = importlib.util.spec_from_file_location("server_config_harness", ACTIVE / "test_server_config.py")
harness = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(harness)


def test_probe(tmp_path):
    print("tmp_path", tmp_path, "resolved equal", tmp_path == tmp_path.resolve())
    server = str(harness.API_DIR / "server.py")
    help_run = harness._run([str(harness.ENGINE_PY), server, "--help"], None)
    print("HELP rc", help_run.returncode, "has flag", "--trending-db PATH" in help_run.stdout)
    print("HELP stdout tail", help_run.stdout[-1500:])
    missing = tmp_path / "absent.db"
    run = harness._run([str(harness.ENGINE_PY), server, "--host", "127.0.0.1", "--port", "1", "--trending-db", str(missing)], None)
    print("MISSING rc", run.returncode, "exists after", missing.exists())
    print("MISSING stderr", run.stderr[-2000:])
    junk = tmp_path / "junk.db"
    junk.write_bytes((b"not a sqlite database\n" * 200)[:4096])
    run = harness._run([str(harness.ENGINE_PY), server, "--host", "127.0.0.1", "--port", "1", "--trending-db", str(junk)], None)
    print("JUNK rc", run.returncode, "size", junk.stat().st_size)
    print("JUNK stderr", run.stderr[-2000:])
