from __future__ import annotations

import importlib.util
import json
import sqlite3
from pathlib import Path

CHECKPOINT = Path(__file__).resolve().parent / "test_45_trending_from_source_instances_phase1.py"
spec = importlib.util.spec_from_file_location("checkpoint_setup", CHECKPOINT)
cp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cp)


def test_setup(tmp_path):
    embedded = [("a-v1", "a.example"), ("a-v2", "a.example"), ("y-v1", "Denied.Example")]
    conn = cp._db(tmp_path / "whitelist.db", embedded)
    conn.execute("INSERT INTO videos (video_id, instance_domain, last_checked_at) VALUES ('u-v1', 'unembedded.example', 0)")
    conn.execute("INSERT INTO instances (host, health_status) VALUES ('healthy.example', 'ok')")
    conn.executemany("INSERT INTO instance_denylist (host, is_active, created_at, updated_at) VALUES (?, ?, 0, 0)", [("blocked.example", 1), ("denied.example", 1), ("lifted.example", 0)])
    conn.commit()
    print("distinct", [tuple(r) for r in conn.execute("SELECT DISTINCT instance_domain FROM video_embeddings")])
    from data.moderation import list_active_denied_hosts, purge_host_data
    print("denied", list_active_denied_hosts(conn))
    conn.executescript("CREATE TABLE trending_ranks (instance_domain TEXT NOT NULL, video_id TEXT NOT NULL, rank INTEGER NOT NULL, likes INTEGER NOT NULL, views INTEGER NOT NULL, fetched_at INTEGER NOT NULL, PRIMARY KEY (instance_domain, video_id));")
    conn.execute("INSERT INTO trending_ranks VALUES ('a.example', ?, 2, 0, 0, 5)", (102,))
    conn.execute("INSERT INTO trending_ranks VALUES ('a.example', 'u1', 1, 5, 50, 5)")
    conn.commit()
    print("rows", cp._rows(conn, "a.example"))
    print("purge today", purge_host_data(conn, "a.example"), cp._rows(conn, "a.example"))
    urlopen, attempts = cp._fake_urlopen([b'{"data": [1]}', cp.FAILURES["http-500"]])
    with urlopen(cp.Request(cp.TRENDING_URL), timeout=0.25) as response:
        print("fake body", json.loads(response.read()), response.status)
    try:
        urlopen(cp.TRENDING_URL, None, 0.25)
    except Exception as exc:
        print("fake raised", type(exc).__name__, exc)
    print("attempts", attempts)
    fetch_list, calls = cp._fetcher({"x": None, "y": RuntimeError("boom")})
    print("fetcher", fetch_list("x"), calls)
    holder = sqlite3.connect(tmp_path / "whitelist.db", isolation_level=None)
    holder.execute("BEGIN IMMEDIATE")
    holder.rollback()
    holder.close()
    print("job exists", cp.JOB.exists())
