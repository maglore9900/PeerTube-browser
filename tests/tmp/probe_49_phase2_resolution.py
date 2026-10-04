"""Throwaway probe: what B1's resolution answers, under ENGINE_PY, for each request the phase 2 checkpoint makes against its tmp whitelist.db."""
import importlib.util
import json
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("cp2", HERE / "test_49_translate_whisper_worker_phase2.py")
cp2 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cp2)

CHILD = r"""
import json, sqlite3, sys
sys.path[:0] = [sys.argv[1], sys.argv[1] + "/api"]
from data.db import connect_readonly_db
from data.moderation import normalize_host, list_active_denied_hosts
from handlers.video import fetch_video_row
from server_config import VIDEO_ERROR_THRESHOLD
path = sys.argv[2]
out = {}
for vid, host in json.loads(sys.argv[3]):
    h = normalize_host(host)
    conn = connect_readonly_db(__import__("pathlib").Path(path))
    row = fetch_video_row(conn, vid, h, error_threshold=VIDEO_ERROR_THRESHOLD)
    denied = sorted(list_active_denied_hosts(conn))
    conn.close()
    out[f"{vid}@{host!r}"] = {"norm": h, "row": None if row is None else [row["video_id"], row["instance_domain"], row["duration"]], "denied": denied}
print(json.dumps(out, indent=1))
"""


def test_probe(tmp_path):
    path = tmp_path / "whitelist.db"
    cp2._whitelist(path)
    reqs = [["u-1", "PEER.Example."], ["u-1", "peer.example"], ["no-such-video", "peer.example"], ["u-1", "other.example"], ["du-1", "denied.example"], ["lu-1", "peer.example"], ["mu-1", "peer.example"], ["u-1", ""], ["u-2", "peer.example"]]
    run = subprocess.run([str(cp2.ENGINE_PY), "-c", CHILD, str(cp2.SERVER_DIR), str(path), json.dumps(reqs)], capture_output=True, text=True, timeout=60)
    print(run.returncode, run.stdout, run.stderr)
    conn = __import__("sqlite3").connect(path)
    conn.execute("UPDATE instance_denylist SET is_active = 0")
    conn.commit()
    conn.close()
    run = subprocess.run([str(cp2.ENGINE_PY), "-c", CHILD, str(cp2.SERVER_DIR), str(path), json.dumps([["du-1", "denied.example"]])], capture_output=True, text=True, timeout=60)
    print("after lift", run.returncode, run.stdout, run.stderr)
    assert False
