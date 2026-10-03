import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engine" / "server"))
from data import trending  # noqa: E402


def test_probe(tmp_path):
    main = tmp_path / "main.db"
    m = sqlite3.connect(main)
    trending.ensure_trending_schema(m)
    m.execute("CREATE TABLE video_embeddings (video_id TEXT, instance_domain TEXT, PRIMARY KEY (video_id, instance_domain))")
    m.commit()
    m.close()
    private = tmp_path / "private.db"
    private.touch()
    trending.prepare_trending_override(str(private))
    conn = sqlite3.connect(main)
    trending.attach_trending_override(conn, str(private))
    sql = "SELECT t.video_id FROM trending_ranks t CROSS JOIN video_embeddings e ON e.video_id = t.video_id AND e.instance_domain = t.instance_domain ORDER BY t.rank ASC, t.likes DESC, t.views DESC, t.video_id DESC, t.instance_domain DESC LIMIT 5 OFFSET 10"
    print(sqlite3.sqlite_version, [row[3] for row in conn.execute("EXPLAIN QUERY PLAN " + sql)])
    try:
        trending.prepare_trending_override(str(tmp_path / "absent.db"))
    except SystemExit as exc:
        print("missing:", exc, (tmp_path / "absent.db").exists())
    assert False
