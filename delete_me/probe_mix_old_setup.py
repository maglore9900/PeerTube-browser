import importlib.util
import json
import subprocess
from pathlib import Path

_spec = importlib.util.spec_from_file_location("checkpoint45", Path(__file__).with_name("test_45_trending_from_source_instances_phase2.py"))
cp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cp)


def test_probe_old_setup(tmp_path):
    ranked = str(tmp_path / "ranks.db")
    cp._ranks_db(Path(ranked)).close()
    empty = str(tmp_path / "empty.db")
    cp._ranks_db(Path(empty)).execute("DELETE FROM trending_ranks").connection.commit()
    cases = {"guest_empty": [False, empty], "home_empty": [True, empty], "home_full": [True, ranked]}
    run = subprocess.run([str(cp.ENGINE_PY), "-c", cp._MIX_CHILD, str(cp.SERVER_DIR), str(cp.SERVER_DIR / "api"), json.dumps(cases)], cwd=cp.SERVER_DIR / "api", capture_output=True, text=True, timeout=120)
    print("RC", run.returncode, run.stderr[-500:])
    print("OUT", run.stdout.strip().splitlines()[-1] if run.stdout.strip() else None)
