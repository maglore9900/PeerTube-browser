import importlib.util
import sqlite3
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("updater", REPO / "engine/server/db/jobs/updater-worker.py")
updater = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(updater)

HOSTS = ["a.example", "b.example", "c.example", "d.example", "e.example", "f.example", "g.example", "h.example"]


def test_probe_subquery_count_matches(tmp_path):
    db = tmp_path / "s.db"
    conn = sqlite3.connect(db)
    conn.executescript((REPO / "engine/crawler/schema.sql").read_text())
    conn.executemany("INSERT INTO instances(host) VALUES (?)", [(h,) for h in HOSTS])
    conn.execute("INSERT INTO instances(host) VALUES (NULL)")
    rows = [(f"ch{i}-{h}", h) for i, h in enumerate(HOSTS) for _ in range(1)] + [("x", "a.example"), ("y", "orphan.example")]
    conn.executemany("INSERT INTO channels(channel_id, instance_domain) VALUES (?, ?)", rows)
    conn.commit()
    conn.close()
    group = updater.host_increment_group("a.example", 7)
    result = updater.filter_staging_to_increment(db, group, 7)
    conn = sqlite3.connect(db)
    sub = conn.execute("SELECT COUNT(*) FROM channels WHERE instance_domain IN (SELECT host FROM instances)").fetchone()[0]
    kept_sql = conn.execute("SELECT COUNT(*) FROM instances WHERE host IS NOT NULL").fetchone()[0]
    null_rows = conn.execute("SELECT COUNT(*) FROM instances WHERE host IS NULL").fetchone()[0]
    conn.close()
    print("result", result, "subquery", sub, "kept_sql", kept_sql, "null_rows", null_rows, "groups", {h: updater.host_increment_group(h, 7) for h in HOSTS})
    assert result["channels"] == sub
    assert result["kept"] == kept_sql
