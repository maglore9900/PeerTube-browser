from __future__ import annotations

import io
import sqlite3
import subprocess
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request

ROOT = Path(__file__).resolve().parents[2]
SERVER_DIR = ROOT / "engine" / "server"
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))


def test_env():
    print("python", sys.version, sys.executable, "ROOT", ROOT)
    try:
        import conftest  # noqa: F401
        print("conftest importable", conftest.__file__)
    except Exception as exc:
        print("conftest NOT importable", type(exc).__name__, exc)
    from data.moderation import ensure_moderation_schema, purge_host_data  # noqa: F401
    from data.ann_ids import create_video_embeddings_table  # noqa: F401
    proc = subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, 'engine/server'); sys.path.insert(0, 'engine/server/api'); import data.moderation, data.time, scripts.cli_format, server_config; print(server_config.DEFAULT_DB_PATH)"], cwd=ROOT, capture_output=True, text=True)
    print("subprocess imports rc", proc.returncode, proc.stdout, proc.stderr[-500:])


def test_sqlite(tmp_path):
    path = tmp_path / "w.db"
    conn = sqlite3.connect(path, timeout=0.2)
    conn.row_factory = sqlite3.Row
    conn.executescript((ROOT / "engine" / "crawler" / "schema.sql").read_text())
    from data.ann_ids import create_video_embeddings_table
    from data.moderation import ensure_moderation_schema, purge_host_data
    create_video_embeddings_table(conn)
    ensure_moderation_schema(conn)
    conn.executescript("CREATE TABLE IF NOT EXISTS t (instance_domain TEXT NOT NULL, video_id TEXT NOT NULL, rank INTEGER NOT NULL, PRIMARY KEY (instance_domain, video_id)); CREATE INDEX IF NOT EXISTS idx_t ON t (rank ASC, video_id DESC);")
    conn.execute("INSERT INTO t VALUES ('a', ?, 1)", (102,))
    conn.commit()
    print("affinity", conn.execute("SELECT video_id, typeof(video_id) FROM t").fetchall()[0][:])
    other = sqlite3.connect(path, isolation_level=None)
    other.execute("BEGIN IMMEDIATE")
    try:
        conn.executescript("CREATE TABLE IF NOT EXISTS t (instance_domain TEXT NOT NULL, video_id TEXT NOT NULL, rank INTEGER NOT NULL, PRIMARY KEY (instance_domain, video_id)); CREATE INDEX IF NOT EXISTS idx_t ON t (rank ASC, video_id DESC);")
        print("executescript IF NOT EXISTS under other's RESERVED: ok")
    except Exception as exc:
        print("executescript under RESERVED raised", type(exc).__name__, exc)
    print("select under RESERVED", conn.execute("SELECT DISTINCT instance_domain FROM video_embeddings").fetchall())
    try:
        conn.execute("BEGIN IMMEDIATE")
        print("BEGIN IMMEDIATE succeeded?!")
    except Exception as exc:
        print("BEGIN IMMEDIATE raised", type(exc).__name__, repr(str(exc)), "in_transaction", conn.in_transaction)
    other.rollback()
    print("purge_host_data today", purge_host_data(conn, "a"))
    print("isolation", repr(conn.isolation_level))


def test_urllib():
    req = Request("https://tube.example/api/v1/videos?sort=-trending&isLocal=true&count=100&nsfw=both", headers={"Accept": "application/json"})
    print("full_url", req.full_url)
    err = HTTPError(req.full_url, 500, "boom", {}, None)
    try:
        raise err
    except (HTTPError, URLError, OSError) as exc:
        print("HTTPError caught", type(exc).__mro__, exc)
    try:
        raise URLError("refused")
    except OSError as exc:
        print("URLError is OSError", exc)
    print("TimeoutError is OSError", issubclass(TimeoutError, OSError))

    class _Response(io.BytesIO):
        status = 200
    with _Response(b'{"data": []}') as r:
        print("bytesio read", r.read(), r.status)
