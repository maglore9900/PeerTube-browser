import sqlite3
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_probe_dev_whitelist_indexes():
    conn = sqlite3.connect(f"file:{ROOT / 'engine/server/db/whitelist.db'}?mode=ro", uri=True)
    names = sorted(r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='videos'"))
    print("INDEXES", names)
    assert False, names


def test_probe_timing_script_imports():
    code = (
        "import sys; sys.path[:0]=[sys.argv[1], sys.argv[2]]\n"
        "from data.random_videos import decode_followed_cursor, fetch_followed_page\n"
        "from data.videos import ensure_video_indexes\nprint('imports ok')"
    )
    run = subprocess.run([str(ROOT / "engine/.pixi/envs/default/bin/python"), "-c", code, str(ROOT / "engine/server/api"), str(ROOT / "engine/server")], capture_output=True, text=True, cwd=ROOT)
    assert run.returncode == 0 and "imports ok" in run.stdout, run.stderr
