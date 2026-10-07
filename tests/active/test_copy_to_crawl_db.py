"""`copy-to-crawl-db.py` inserts into crawl.db the instances, channels and videos a whitelist DB holds and crawl.db lacks, and on a video crawl.db already holds changes only a NULL `tags_json`.

- A crawl.db older than `videos.language` gains the column, and a copied video keeps its language and tags.
- A video crawl.db holds with NULL tags takes the whitelist's tags; one with tags or `[]` keeps them; every other value, and every channel, stays crawl.db's; a crawl.db-only row stays.
- A whitelist-only column (`popularity`) does not stop the copy.
- A second run copies nothing.

Both DBs are tmp files from the crawler's `schema.sql`.
"""
from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
JOB = ROOT / "engine" / "server" / "db" / "jobs" / "copy-to-crawl-db.py"
CRAWL_SCHEMA = ROOT / "engine" / "crawler" / "schema.sql"
VIDEO_SQL = "INSERT INTO videos (video_id, instance_domain, channel_id, title, tags_json, language, last_checked_at) VALUES (?, ?, ?, ?, ?, ?, 0)"


@pytest.fixture(scope="module")
def job():
    spec = importlib.util.spec_from_file_location("copy_to_crawl_db_job", JOB)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _schema_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.executescript(CRAWL_SCHEMA.read_text(encoding="utf-8"))
    return conn


def _dbs(tmp_path: Path) -> sqlite3.Connection:
    """A whitelist DB (with popularity) holding hosts a and b, and an older crawl.db (no language) holding host a and a crawl-only video; return the crawl.db connection with the whitelist attached as `source`."""
    source = _schema_db(tmp_path / "whitelist.db")
    source.execute("ALTER TABLE videos ADD COLUMN popularity REAL NOT NULL DEFAULT 0")
    source.executemany("INSERT INTO instances (host) VALUES (?)", [("a.example",), ("b.example",)])
    source.executemany("INSERT INTO channels (channel_id, instance_domain, channel_name) VALUES (?, ?, ?)", [("c1", "a.example", "whitelist name"), ("c2", "b.example", "new channel")])
    source.executemany(VIDEO_SQL, [("v1", "a.example", "c1", "whitelist title", '["backfilled"]', None), ("v2", "b.example", "c2", "updater video", '["Linux"]', "fr"), ("v3", "a.example", "c1", "whitelist title", '["other"]', None), ("v4", "a.example", "c1", "whitelist title", None, None)])
    source.commit()
    source.close()

    crawl = _schema_db(tmp_path / "crawl.db")
    crawl.execute("ALTER TABLE videos DROP COLUMN language")
    crawl.execute("INSERT INTO instances (host) VALUES ('a.example')")
    crawl.execute("INSERT INTO channels (channel_id, instance_domain, channel_name) VALUES ('c1', 'a.example', 'crawl name')")
    crawl.executemany("INSERT INTO videos (video_id, instance_domain, channel_id, title, tags_json, last_checked_at) VALUES (?, ?, ?, ?, ?, 0)", [("v1", "a.example", "c1", "crawl title", None), ("v0", "a.example", "c1", "crawl only", None), ("v3", "a.example", "c1", "crawl tags", '["crawl"]'), ("v4", "a.example", "c1", "crawl untagged", '[]')])
    crawl.commit()
    crawl.execute("ATTACH DATABASE ? AS source", (str(tmp_path / "whitelist.db"),))
    return crawl


def test_the_rows_crawl_db_lacks_are_copied_with_their_language_and_crawl_db_rows_are_left_alone(job, tmp_path):
    crawl = _dbs(tmp_path)
    assert "language" not in [row[1] for row in crawl.execute("PRAGMA main.table_info(videos)")]  # control: an older crawl.db

    copied = job.copy_missing_rows(crawl)

    assert copied == {"instances": 1, "channels": 1, "videos": 1, "tags": 1}
    assert sorted(row[0] for row in crawl.execute("SELECT host FROM main.instances")) == ["a.example", "b.example"]
    assert dict(crawl.execute("SELECT channel_id, channel_name FROM main.channels")) == {"c1": "crawl name", "c2": "new channel"}  # c1 keeps crawl.db's value
    videos = {row[0]: row[1:] for row in crawl.execute("SELECT video_id, title, tags_json, language FROM main.videos")}
    assert videos == {
        "v0": ("crawl only", None, None),  # a crawl-only row stays
        "v1": ("crawl title", '["backfilled"]', None),  # a NULL tag list takes the whitelist's tags; the title stays crawl.db's
        "v2": ("updater video", '["Linux"]', "fr"),  # the updater video arrives whole
        "v3": ("crawl tags", '["crawl"]', None),  # crawl.db's own tags are never overwritten
        "v4": ("crawl untagged", "[]", None),  # nor its "no tags" answer by a whitelist NULL
    }
    assert job.copy_missing_rows(crawl) == {"instances": 0, "channels": 0, "videos": 0, "tags": 0}  # nothing left to copy
