import importlib.util
import sqlite3
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("checkpoint49", HERE / "test_49_translate_whisper_worker_phase1.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

OK = "import sys, time\nfrom pathlib import Path\nready, go = Path(sys.argv[3]), Path(sys.argv[4])\nready.touch()\nwhile not go.exists():\n    time.sleep(0.001)\nprint('ran')\n"
DIES = "import sys\nraise SystemExit('died before the barrier')\n"


def test_probe_barrier(tmp_path):
    synced, results = mod._run_together([(OK, ["x"]), (OK, ["x"])], tmp_path, "ok")
    print("both reach:", synced, [(rc, out.strip()) for rc, out, err in results])
    synced, results = mod._run_together([(OK, ["x"]), (DIES, ["x"])], tmp_path, "dies")
    print("one dies:", synced, [(rc, out.strip(), err.strip()) for rc, out, err in results])
    path = tmp_path / "b1.db"
    mod._b1_file(path)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.close()
    plain = mod._plain(path)
    print("plain mode after WAL switch and close:", plain.execute("PRAGMA journal_mode").fetchone()[0])
    plain.close()
