import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "active"))
from conftest import client_backend  # noqa: E402,F401
from lib.users_store import close_like, record_like, remove_like  # noqa: E402


def _counts(db_path, pid):
    conn = sqlite3.connect(db_path)
    out = {t: conn.execute(f"SELECT COUNT(*) FROM {t} WHERE {c} = ?", (pid,)).fetchone()[0] for t, c in (("profiles", "profile_id"), ("users", "user_id"), ("likes", "user_id"), ("like_generations", "user_id"))}
    out["gen_rows"] = conn.execute("SELECT video_id, generation, published FROM like_generations WHERE user_id = ?", (pid,)).fetchall()
    conn.close()
    return out


def test_probe(client_backend):
    ids = []
    for _ in range(2):
        status, body = client_backend.request("POST", "/api/profile")
        ids.append((body["profile_id"], body["key"]))
    for pid, _ in ids:
        conn = sqlite3.connect(client_backend.db_path)
        conn.row_factory = sqlite3.Row
        print("seed", record_like(conn, pid, "like", {"video_id": f"v-{pid}", "instance_domain": "h.example", "video_uuid": "u"}, 100, publish=True))
        conn.close()
    gone = ids[0][0]
    conn = sqlite3.connect(client_backend.db_path)
    conn.row_factory = sqlite3.Row
    print("undone seed", record_like(conn, gone, "like", {"video_id": "v-undone", "instance_domain": "h.example", "video_uuid": "u2"}, 100, publish=True))
    with conn:
        remove_like(conn, gone, "v-undone", "h.example")
        print("close", close_like(conn, gone, "v-undone", "h.example"))
    conn.close()
    print("before", _counts(client_backend.db_path, gone), _counts(client_backend.db_path, ids[1][0]))
    print("unkeyed delete", client_backend.request("POST", "/api/profile/delete", body={}))
    print("delete", client_backend.request("POST", "/api/profile/delete", headers={"X-Profile-Key": ids[0][1]}, body={}))
    print("after", _counts(client_backend.db_path, gone), _counts(client_backend.db_path, ids[1][0]))
    assert False
