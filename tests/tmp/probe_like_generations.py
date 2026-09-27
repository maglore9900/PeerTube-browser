import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "client" / "backend"))
from lib.users_store import clear_likes, close_like, ensure_user_schema, record_like, remove_like  # noqa: E402


def test_probe():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    print("sqlite", sqlite3.sqlite_version)
    ensure_user_schema(conn)
    v = {"video_id": "v1", "instance_domain": "h", "video_uuid": "u"}
    steps = []
    steps.append(("like", record_like(conn, "p", "like", v, 100, publish=True)))
    steps.append(("like", record_like(conn, "p", "like", v, 100, publish=True)))
    with conn:
        remove_like(conn, "p", "v1", "h")
        steps.append(("undo", close_like(conn, "p", "v1", "h")))
    steps.append(("undo", close_like(conn, "p", "v1", "h")))
    steps.append(("like", record_like(conn, "p", "like", v, 100, publish=True)))
    clear_likes(conn, "p")
    steps.append(("like after reset", record_like(conn, "p", "like", v, 100, publish=True)))
    steps.append(("import", record_like(conn, "q", "like", v, 100)))
    steps.append(("undo import", close_like(conn, "q", "v1", "h")))
    print(steps)
    assert steps == [("like", (True, 1)), ("like", (False, 1)), ("undo", (True, 1)), ("undo", (False, 1)), ("like", (True, 2)), ("like after reset", (False, 2)), ("import", (False, 0)), ("undo import", (False, 0))]
