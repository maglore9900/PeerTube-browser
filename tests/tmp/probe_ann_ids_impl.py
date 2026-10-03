import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "engine" / "server"))

from data.ann_ids import compute_ann_id, create_ann_id_guards, create_video_embeddings_table


def test_probe():
    print("pinned", compute_ann_id("abc", "peertube.example"), compute_ann_id("abc", "https://peertube.example/w/abc"))
    print("fallback", compute_ann_id("v", "..."), compute_ann_id("v", "  Bad Host  "))
    conn = sqlite3.connect(":memory:")
    create_video_embeddings_table(conn)
    create_ann_id_guards(conn)
    conn.execute("INSERT INTO video_embeddings VALUES ('v1', 'h', x'01', 1, 'm', 't', 111)")
    for sql in ("INSERT INTO video_embeddings VALUES ('v2', 'h', x'01', 1, 'm', 't', 111)", "INSERT OR REPLACE INTO video_embeddings VALUES ('v2', 'h', x'01', 1, 'm', 't', 111)", "INSERT INTO video_embeddings VALUES ('v3', 'h', x'01', 1, 'm', 't', 0)"):
        try:
            conn.execute(sql)
            print("accepted", sql)
        except Exception as exc:
            print(type(exc).__name__, exc)
    print(conn.execute("SELECT video_id, ann_id FROM video_embeddings").fetchall())
    assert False, "show output"
