import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WHITELIST_DB = ROOT / "engine" / "server" / "db" / "whitelist.db"


def test_probe_schema():
    conn = sqlite3.connect(f"file:{WHITELIST_DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    for table in ("videos", "video_embeddings", "channels"):
        print(table, conn.execute("SELECT sql FROM sqlite_master WHERE name = ?", (table,)).fetchone()[0])
        print("INDEXES", [r[0] for r in conn.execute("SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name = ?", (table,))])
    rows = conn.execute(
        "SELECT v.rowid, v.video_id, v.instance_domain, v.video_uuid, typeof(v.video_id) tid, v.published_at, typeof(v.published_at) tp, v.likes, v.views, v.popularity, v.error_count "
        "FROM videos v JOIN video_embeddings e ON e.video_id = v.video_id AND e.instance_domain = v.instance_domain "
        "WHERE v.video_uuid IS NOT NULL ORDER BY v.rowid LIMIT 8"
    ).fetchall()
    for r in rows:
        print(dict(r))
    print("non-embedded", dict(conn.execute("SELECT v.rowid, v.video_id, v.instance_domain FROM videos v LEFT JOIN video_embeddings e ON e.video_id = v.video_id AND e.instance_domain = v.instance_domain WHERE e.video_id IS NULL AND v.video_uuid IS NOT NULL ORDER BY v.rowid LIMIT 1").fetchone() or {}))
    print("published_at range", dict(conn.execute("SELECT MIN(published_at) mn, MAX(published_at) mx, SUM(published_at IS NULL) nulls FROM videos").fetchone()))
    assert False
