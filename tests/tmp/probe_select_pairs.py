import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "engine" / "server", ROOT / "engine" / "server" / "api"):
    sys.path.insert(0, str(path))

from data import metadata  # noqa: E402


def test_probe():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute("CREATE TABLE videos (video_id TEXT, video_uuid TEXT, video_numeric_id INTEGER, instance_domain TEXT, channel_id TEXT, channel_name TEXT, channel_url TEXT, account_name TEXT, account_url TEXT, title TEXT, description TEXT, tags_json TEXT, category TEXT, published_at TEXT, video_url TEXT, duration INTEGER, thumbnail_url TEXT, embed_path TEXT, views INTEGER, likes INTEGER, dislikes INTEGER, comments_count INTEGER, nsfw INTEGER, preview_path TEXT, last_checked_at TEXT, error_count INTEGER)")
    db.execute("CREATE TABLE video_embeddings (video_id TEXT, instance_domain TEXT, embedding BLOB, embedding_dim INTEGER, model_name TEXT)")
    db.execute("CREATE TABLE channels (channel_id TEXT, instance_domain TEXT, display_name TEXT, avatar_url TEXT)")
    for i in range(460):
        db.execute("INSERT INTO videos (video_id, video_uuid, instance_domain, error_count) VALUES (?, ?, 'b', ?)", (f"c{i:03d}", f"u{i:03d}", 5 if i == 455 else 0))
        db.execute("INSERT INTO video_embeddings VALUES (?, 'b', x'00', 3, 'm')", (f"c{i:03d}",))
    for vid in ("s2", "s1", "s3"):
        db.execute("INSERT INTO videos (video_id, video_uuid, instance_domain, error_count) VALUES (?, 'us', 'b', 0)", (vid,))
        db.execute("INSERT INTO video_embeddings VALUES (?, 'b', x'00', 3, 'm')", (vid,))
    statements = []
    db.set_trace_callback(statements.append)
    assert metadata.fetch_metadata_by_ids(db, []) == {}
    assert metadata.fetch_metadata_by_uuids(db, []) == {}
    print("empty statements:", statements)
    by_id = metadata.fetch_metadata_by_ids(db, [{"video_id": f"c{i:03d}", "instance_domain": "b"} for i in range(460)], error_threshold=3)
    by_uuid = metadata.fetch_metadata_by_uuids(db, [{"video_uuid": f"u{i:03d}", "instance_domain": "b"} for i in range(460)], error_threshold=3)
    print("by_id", len(by_id), "c455::b" in by_id, "by_uuid", len(by_uuid), "u455::b" in by_uuid)
    print("no threshold c455:", "c455::b" in metadata.fetch_metadata_by_ids(db, [{"video_id": "c455", "instance_domain": "b"}]))
    print("shared:", {k: v["video_id"] for k, v in metadata.fetch_metadata_by_uuids(db, [{"video_uuid": "us", "instance_domain": "b"}], error_threshold=3).items()})
    print("statement count:", len(statements), "keys:", len(next(iter(by_id.values()))))
