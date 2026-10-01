"""Probe: what the current (legacy) purge returns and leaves for the phase-4 fixture content."""
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "engine" / "server", ROOT / "engine" / "server" / "api"):
    sys.path.insert(0, str(path))
from data.moderation import collect_similarity_host_stats, purge_similarity_for_host  # noqa: E402

A, BAD = "a.example", "bad.example"
DDL = """
CREATE TABLE similarity_sources (video_id TEXT NOT NULL, instance_domain TEXT NOT NULL, computed_at INTEGER NOT NULL, PRIMARY KEY (video_id, instance_domain));
CREATE TABLE similarity_items (source_video_id TEXT NOT NULL, source_instance_domain TEXT NOT NULL, similar_video_id TEXT NOT NULL, similar_instance_domain TEXT NOT NULL, score REAL, rank INTEGER NOT NULL, PRIMARY KEY (source_video_id, source_instance_domain, similar_video_id, similar_instance_domain));
"""


def test_probe(tmp_path):
    conn = sqlite3.connect(tmp_path / "legacy.db")
    conn.row_factory = sqlite3.Row
    conn.executescript(DDL)
    conn.executemany("INSERT INTO similarity_sources VALUES (?, ?, 1)", [("s1", A), ("s2", A), ("s3", A), ("s4", A), ("b1", BAD), ("b2", BAD)])
    conn.executemany(
        "INSERT INTO similarity_items VALUES (?, ?, ?, ?, ?, ?)",
        [("s1", A, "x1", BAD, 0.875, 1), ("s1", A, "n1", A, 0.75, 2), ("s1", A, "x2", BAD, 0.625, 3), ("s1", A, "n2", A, 0.5, 4), ("s2", A, "n1", A, 0.5, 1), ("s3", A, "n1", A, 0.75, 1), ("s3", A, "x1", BAD, 0.5, 2), ("s4", A, "x2", BAD, 0.5, 1), ("b1", BAD, "n1", A, 0.75, 1), ("b1", BAD, "x1", BAD, 0.5, 2)],
    )
    conn.commit()
    print("stats", collect_similarity_host_stats(conn, BAD))
    print("purge", purge_similarity_for_host(conn, BAD))
    print("nokeys", purge_similarity_for_host(conn, "nokeys.example"))
    print("left", [tuple(r) for r in conn.execute("SELECT * FROM similarity_items ORDER BY source_video_id, rank")])
    print("sources", [tuple(r) for r in conn.execute("SELECT video_id, instance_domain FROM similarity_sources ORDER BY video_id")])
    assert False, "probe"
