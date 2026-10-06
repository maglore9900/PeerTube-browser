"""`sync-whitelist.py` reloads `video_embeddings` carrying the derived `ann_id`, refuses an unmigrated target before any write, and rolls a run that hits an `ann_id` collision back whole.

- `rebuild_content_tables` from a crawl source whose `video_embeddings` has no `ann_id` stores each row whole with the pinned blake2b id of its key, `v3`'s taken from the normalised host `b.example`, not the stored `B.Example.`. From a source carrying `ann_id`, it stores the source's value, including a sentinel that is not the derived id.
- sync's `main()` on a six-column target raises RuntimeError naming `main.video_embeddings`, `missing columns: ann_id` and `migrate-whitelist.py`, and leaves the target's `instances`, `videos` and `video_embeddings` rows as they were.
- sync's `main()` from a source whose v2 carries v1's ann_id raises the collision trigger's IntegrityError and leaves the target's `instances`, `videos` and `video_embeddings` rows as they were and the `videos_fts_ai/ad/au` triggers in place; the same source with v2's own id syncs, adding `b.example` and v2.
- sync's `ensure_whitelist_schema` and `ensure_content_schema`, run twice on a fresh DB, leave idx_videos_channel_published on `videos` keyed (instance_domain, channel_id, published_at DESC, video_id DESC) and idx_videos_account_published keyed (account_url, published_at DESC, video_id DESC), read back through `PRAGMA index_xinfo`.

Every DB is a tmp file. The crawl source is `engine/crawler/schema.sql` plus a literal `video_embeddings`. sync runs in-process, with `fetch_hosts` (the network) replaced by a fixed host set.
"""
from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
JOBS_DIR = ROOT / "engine" / "server" / "db" / "jobs"
CRAWL_SCHEMA = ROOT / "engine" / "crawler" / "schema.sql"

# video_embeddings as `ensure_content_schema` created it before `ann_id` existed.
OLD_VIDEO_EMBEDDINGS_SQL = """
CREATE TABLE video_embeddings (
  video_id TEXT NOT NULL,
  instance_domain TEXT NOT NULL,
  embedding BLOB NOT NULL,
  embedding_dim INTEGER NOT NULL,
  model_name TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (video_id, instance_domain),
  FOREIGN KEY (video_id, instance_domain) REFERENCES videos (video_id, instance_domain)
);
"""
# A crawl DB's video_embeddings carrying ann_id, with no UNIQUE index or trigger of its own.
SOURCE_ANN_ID_EMBEDDINGS_SQL = """
CREATE TABLE video_embeddings (
  video_id TEXT NOT NULL,
  instance_domain TEXT NOT NULL,
  embedding BLOB NOT NULL,
  embedding_dim INTEGER NOT NULL,
  model_name TEXT NOT NULL,
  created_at TEXT NOT NULL,
  ann_id INTEGER NOT NULL,
  PRIMARY KEY (video_id, instance_domain)
);
"""
HOST = "a.example"
# A host only the remote whitelist adds, so a sync that committed any of its work changes `instances`.
NEW_HOST = "b.example"
# int.from_bytes(hashlib.blake2b(key, digest_size=8).digest(), "big") & (2**63 - 1) for v1::a.example, v2::a.example, v3::b.example, run outside the helper; the raw `v3::B.Example.` would give 5421220993327846826.
V1_ID = 8241284212183890047
V2_ID = 8744784223012906678
V3_ID = 3553096638009034147
# Not v3's derived id: the reload must copy it from a source that carries it.
V3_SENTINEL = 777
RELOAD_HOSTS = {"a.example", "B.Example."}
CHANNELS = [("c1", "a.example"), ("c3", "B.Example.")]
VIDEOS = [("v1", "a.example", "c1"), ("v2", "a.example", "c1"), ("v3", "B.Example.", "c3")]
# (video_id, instance_domain, embedding, embedding_dim, model_name, created_at); v3's host is stored unnormalised.
EMBEDDINGS = [("v1", "a.example", b"\x01\x02", 2, "m", "t1"), ("v2", "a.example", b"\x03\x04", 2, "m", "t2"), ("v3", "B.Example.", b"\x05\x06", 2, "m", "t3")]
COLUMNS = "video_id, instance_domain, embedding, embedding_dim, model_name, created_at, ann_id"
ROWS_SQL = f"SELECT {COLUMNS} FROM video_embeddings ORDER BY video_id"
TARGET_V1 = ("v1", HOST, b"\x01", 1, "m", "t1")
SOURCE_V2 = ("v2", HOST, b"\x02", 1, "m", "t2")
FTS_TRIGGERS = {"videos_fts_ai", "videos_fts_ad", "videos_fts_au"}
COLLISION_MESSAGE = "video_embeddings ann_id collision"


def _load_job(module_name: str, filename: str):
    spec = importlib.util.spec_from_file_location(module_name, JOBS_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def sync_job():
    return _load_job("sync_whitelist_for_test_sync_whitelist", "sync-whitelist.py")


def _whitelist_db(sync_job, path: Path, old: bool = False) -> sqlite3.Connection:
    """A whitelist-shaped DB from sync's own schema helpers; with `old`, its video_embeddings is the six-column table."""
    conn = sqlite3.connect(path)
    if old:
        conn.executescript(OLD_VIDEO_EMBEDDINGS_SQL)
    sync_job.ensure_whitelist_schema(conn)
    sync_job.ensure_content_schema(conn)
    return conn


def _reload_source(path: Path, ann_ids: list[int] | None = None) -> Path:
    """A crawl DB holding CHANNELS, VIDEOS and EMBEDDINGS, its video_embeddings carrying `ann_ids` when given."""
    conn = sqlite3.connect(path)
    conn.executescript(CRAWL_SCHEMA.read_text(encoding="utf-8"))
    conn.executemany("INSERT INTO channels (channel_id, instance_domain) VALUES (?, ?)", CHANNELS)
    conn.executemany("INSERT INTO videos (video_id, instance_domain, channel_id, last_checked_at) VALUES (?, ?, ?, 1)", VIDEOS)
    if ann_ids is None:
        conn.executescript(OLD_VIDEO_EMBEDDINGS_SQL)
        conn.executemany("INSERT INTO video_embeddings VALUES (?, ?, ?, ?, ?, ?)", EMBEDDINGS)
    else:
        conn.executescript(SOURCE_ANN_ID_EMBEDDINGS_SQL)
        conn.executemany(f"INSERT INTO video_embeddings ({COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?)", [row + (ann_id,) for row, ann_id in zip(EMBEDDINGS, ann_ids)])
    conn.commit()
    conn.close()
    return path


def _attach_source(conn: sqlite3.Connection, path: Path) -> None:
    conn.execute("ATTACH DATABASE ? AS source", (path.as_posix(),))


def _seed(conn: sqlite3.Connection, video_ids: list[str], embeddings: list[tuple]) -> None:
    conn.execute("INSERT INTO instances (host, health_status, health_checked_at) VALUES (?, 'ok', 1)", (HOST,))
    conn.executemany("INSERT INTO videos (video_id, instance_domain, title, last_checked_at) VALUES (?, ?, ?, 1)", [(v, HOST, f"title {v}") for v in video_ids])
    for row in embeddings:
        conn.execute(f"INSERT INTO video_embeddings VALUES ({', '.join('?' * len(row))})", row)
    conn.commit()
    conn.close()


def _state(path: Path) -> dict:
    conn = sqlite3.connect(path)
    try:
        state = {table: conn.execute(f"SELECT * FROM {table} ORDER BY 1, 2").fetchall() for table in ("instances", "videos", "video_embeddings")}
        state["triggers"] = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'")}
        return state
    finally:
        conn.close()


def _crawl_source(path: Path, v2_id: int) -> Path:
    conn = sqlite3.connect(path)
    conn.executescript(CRAWL_SCHEMA.read_text(encoding="utf-8"))
    conn.execute("INSERT INTO channels (channel_id, instance_domain) VALUES ('c1', ?)", (HOST,))
    conn.executemany("INSERT INTO videos (video_id, instance_domain, channel_id, title, last_checked_at) VALUES (?, ?, 'c1', ?, 1)", [("v1", HOST, "title v1"), ("v2", HOST, "title v2")])
    conn.executescript(SOURCE_ANN_ID_EMBEDDINGS_SQL)
    conn.executemany("INSERT INTO video_embeddings VALUES (?, ?, ?, ?, ?, ?, ?)", [TARGET_V1 + (V1_ID,), SOURCE_V2 + (v2_id,)])
    conn.commit()
    conn.close()
    return path


def _run_sync(sync_job, monkeypatch, source_db: Path, target_db: Path) -> None:
    # The remote whitelist adds NEW_HOST, so a sync that commits any of its work changes `instances`.
    monkeypatch.setattr(sync_job, "fetch_hosts", lambda url: {HOST, NEW_HOST})
    monkeypatch.setattr(sys, "argv", ["sync-whitelist.py", "--source-db", str(source_db), "--output-db", str(target_db)])
    sync_job.main()


def test_reload_from_a_source_without_ann_id_stores_the_derived_id(sync_job, tmp_path):
    """A reload from a source with no `ann_id` stores each row with the id derived from its normalised key."""
    conn = _whitelist_db(sync_job, tmp_path / "whitelist.db")
    try:
        _attach_source(conn, _reload_source(tmp_path / "crawl.db"))
        sync_job.rebuild_content_tables(conn, RELOAD_HOSTS)
        conn.commit()

        assert conn.execute(ROWS_SQL).fetchall() == [row + (ann_id,) for row, ann_id in zip(EMBEDDINGS, [V1_ID, V2_ID, V3_ID])]
    finally:
        conn.close()


def test_reload_from_a_source_with_ann_id_stores_the_sources_value(sync_job, tmp_path):
    """A reload from a source that carries `ann_id` copies the source's value rather than recomputing it."""
    conn = _whitelist_db(sync_job, tmp_path / "whitelist.db")
    try:
        source_ids = [V1_ID, V2_ID, V3_SENTINEL]
        _attach_source(conn, _reload_source(tmp_path / "crawl.db", source_ids))
        sync_job.rebuild_content_tables(conn, RELOAD_HOSTS)
        conn.commit()

        assert conn.execute(ROWS_SQL).fetchall() == [row + (ann_id,) for row, ann_id in zip(EMBEDDINGS, source_ids)]
    finally:
        conn.close()


def test_sync_refuses_a_six_column_target_naming_main_before_any_write(sync_job, tmp_path, monkeypatch):
    """A target whose `video_embeddings` predates `ann_id` is refused with the migrate pointer before sync writes anything."""
    target_db = tmp_path / "whitelist.db"
    _seed(_whitelist_db(sync_job, target_db, old=True), ["v1"], [TARGET_V1])
    before = _state(target_db)

    with pytest.raises(RuntimeError) as refused:
        _run_sync(sync_job, monkeypatch, _crawl_source(tmp_path / "crawl.db", V2_ID), target_db)

    message = str(refused.value)
    assert "main.video_embeddings" in message
    assert "missing columns: ann_id" in message
    assert "migrate-whitelist.py" in message
    after = _state(target_db)
    assert after["instances"] == before["instances"]
    assert after["videos"] == before["videos"]
    assert after["video_embeddings"] == before["video_embeddings"]


def test_sync_collision_fails_and_leaves_target_rows_and_fts_triggers_as_they_were(sync_job, tmp_path, monkeypatch):
    """A sync whose source carries another key's `ann_id` fails and rolls the whole run back, the FTS triggers included."""
    target_db = tmp_path / "whitelist.db"
    _seed(_whitelist_db(sync_job, target_db), ["v1"], [TARGET_V1 + (V1_ID,)])
    source_db = _crawl_source(tmp_path / "crawl.db", V1_ID)
    before = _state(target_db)
    assert FTS_TRIGGERS <= before["triggers"], "control: the target starts with its videos_fts triggers"

    with pytest.raises(sqlite3.IntegrityError, match=COLLISION_MESSAGE):
        _run_sync(sync_job, monkeypatch, source_db, target_db)

    after = _state(target_db)
    assert after["instances"] == before["instances"]
    assert after["videos"] == before["videos"]
    assert after["video_embeddings"] == before["video_embeddings"]
    assert FTS_TRIGGERS <= after["triggers"]


def test_sync_without_collision_replaces_the_target_rows(sync_job, tmp_path, monkeypatch):
    """A sync onto a migrated target with no collision rewrites `instances`, `videos` and `video_embeddings` from the source."""
    target_db = tmp_path / "whitelist.db"
    _seed(_whitelist_db(sync_job, target_db), ["v1"], [TARGET_V1 + (V1_ID,)])

    _run_sync(sync_job, monkeypatch, _crawl_source(tmp_path / "crawl.db", V2_ID), target_db)

    # control: the run the collision and old-target tests refuse does change all three tables when nothing collides.
    after = _state(target_db)
    assert [row[0] for row in after["instances"]] == [HOST, NEW_HOST]
    assert [row[0] for row in after["videos"]] == ["v1", "v2"]
    assert after["video_embeddings"] == [TARGET_V1 + (V1_ID,), SOURCE_V2 + (V2_ID,)]


# (column, desc) of each index key column, read from PRAGMA index_xinfo rows (seqno, cid, name, desc, coll, key); key = 0 rows are the rowid tail.
RECENCY_INDEXES = {
    "idx_videos_channel_published": [("instance_domain", 0), ("channel_id", 0), ("published_at", 1), ("video_id", 1)],
    "idx_videos_account_published": [("account_url", 0), ("published_at", 1), ("video_id", 1)],
}


def _key_columns(conn: sqlite3.Connection) -> dict[str, tuple[str | None, list[tuple[str, int]]]]:
    """Per recency index: the table it is on, and its key columns with their DESC flag; an absent index reads (None, [])."""
    out = {}
    for name in RECENCY_INDEXES:
        table = conn.execute("SELECT tbl_name FROM sqlite_master WHERE type = 'index' AND name = ?", (name,)).fetchone()
        out[name] = (table[0] if table else None, [(row[2], row[3]) for row in conn.execute(f"PRAGMA index_xinfo({name})") if row[5] == 1])
    return out


EXPECTED_INDEXES = {name: ("videos", columns) for name, columns in RECENCY_INDEXES.items()}


def test_the_sync_stage_schema_creates_the_channel_and_account_recency_indexes_and_runs_again_on_a_database_that_has_them(sync_job, tmp_path):
    conn = sqlite3.connect(tmp_path / "whitelist.db")
    # Twice, as a second sync over the same target would; a bare CREATE INDEX raises on the second.
    for _ in range(2):
        sync_job.ensure_whitelist_schema(conn)
        sync_job.ensure_content_schema(conn)
    # An ASC published_at or video_id, a missing or reordered column, or no index reads differently.
    assert _key_columns(conn) == EXPECTED_INDEXES  # C2
    conn.close()
