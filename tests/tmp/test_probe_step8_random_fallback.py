"""Probe: how long the random feed's DB fallback (fetch_random_rows, served while the random cache is unusable) takes on whitelist.db, and whether it survives the Engine's statement deadline."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE_PY = ROOT / "engine" / ".pixi" / "envs" / "default" / "bin" / "python"

CHILD = """
import sys, time
sys.path.insert(0, 'engine/server'); sys.path.insert(0, 'engine/server/api')
from data.db import connect_readonly_db, statement_deadline
from data.random_videos import fetch_random_rows
from server_config import DEFAULT_STATEMENT_TIMEOUT_SECONDS
from pathlib import Path
db = connect_readonly_db(Path('engine/server/db/whitelist.db'))
print('deadline', DEFAULT_STATEMENT_TIMEOUT_SECONDS)
for nsfw in (True, False):
    t = time.time()
    try:
        with statement_deadline(DEFAULT_STATEMENT_TIMEOUT_SECONDS):
            rows = fetch_random_rows(db, 96, error_threshold=None, include_nsfw=nsfw)
        print('include_nsfw', nsfw, 'rows', len(rows), f'{time.time() - t:.2f}s')
    except Exception as exc:
        print('include_nsfw', nsfw, 'raised', type(exc).__name__, exc, f'{time.time() - t:.2f}s')
"""


def test_probe():
    out = subprocess.run([str(ENGINE_PY), "-c", CHILD], cwd=ROOT, capture_output=True, text=True)
    print("exit", out.returncode)
    print(out.stdout)
    print(out.stderr[-3000:])
    assert False, "probe"
