from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import textwrap
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ACTIVE = ROOT / "tests" / "active"
if str(ACTIVE) not in sys.path:
    sys.path.insert(0, str(ACTIVE))
import conftest as active  # noqa: E402

engine = active.engine
SERVER_DIR = ROOT / "engine" / "server"
for _path in (SERVER_DIR, SERVER_DIR / "api"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))
from data import random_videos  # noqa: E402
from data.ann_ids import compute_ann_id, create_video_embeddings_table  # noqa: E402
from data.moderation import ensure_moderation_schema  # noqa: E402
from data.trending import ensure_trending_schema  # noqa: E402

CRAWL_SCHEMA = ROOT / "engine" / "crawler" / "schema.sql"
ENGINE_PY = active.ENGINE_PY


def _db(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(CRAWL_SCHEMA.read_text(encoding="utf-8"))
    conn.execute("ALTER TABLE videos ADD COLUMN popularity REAL NOT NULL DEFAULT 0")
    create_video_embeddings_table(conn)
    ensure_moderation_schema(conn)
    ensure_trending_schema(conn)
    return conn


def test_plan(tmp_path):
    conn = _db(tmp_path / "plan.db")
    for h in range(30):
        host = f"h{h:02d}.example"
        for r in range(1, 101):
            vid = f"v{r:03d}"
            conn.execute("INSERT INTO videos (video_id, instance_domain, likes, views, popularity, last_checked_at) VALUES (?, ?, ?, ?, ?, 0)", (vid, host, r, r * 10, r))
            conn.execute("INSERT INTO video_embeddings VALUES (?, ?, x'00', 1, 'm', 't', ?)", (vid, host, compute_ann_id(vid, host)))
            conn.execute("INSERT INTO trending_ranks VALUES (?, ?, ?, ?, ?, 0)", (host, vid, r, 100 - r, 1000 - r))
    for n in range(1000):
        conn.execute("INSERT INTO videos (video_id, instance_domain, likes, views, last_checked_at) VALUES (?, 'u.example', 1, 1, 0)", (f"u{n}",))
        conn.execute("INSERT INTO video_embeddings VALUES (?, 'u.example', x'00', 1, 'm', 't', ?)", (f"u{n}", compute_ann_id(f"u{n}", "u.example")))
    conn.commit()

    class Recorder:
        def __init__(self, inner):
            self.inner = inner
            self.calls = []

        def execute(self, sql, params=()):
            self.calls.append((sql, list(params)))
            return self.inner.execute(sql, params)

    rec = Recorder(conn)
    rows = random_videos.fetch_ordered_page(rec, "popular", 50, 100, error_threshold=3, include_nsfw=False)
    print("popular rows", len(rows), "calls", len(rec.calls))
    sql, params = rec.calls[0]
    print("popular plan", [tuple(r) for r in conn.execute("EXPLAIN QUERY PLAN " + sql, params)])
    planned = random_videos.fetch_ordered_page.__code__  # noqa: F841
    trending_sql = sql.replace("FROM video_embeddings e", "FROM trending_ranks t\n          CROSS JOIN video_embeddings e\n            ON e.video_id = t.video_id AND e.instance_domain = t.instance_domain").replace(random_videos.ORDERED_FEED_ORDER_BY["popular"], "\n    t.rank ASC,\n    t.likes DESC,\n    t.views DESC,\n    t.video_id DESC,\n    t.instance_domain DESC\n")
    print("trending sim plan", [tuple(r) for r in conn.execute("EXPLAIN QUERY PLAN " + trending_sql, params)])
    print("trending sim rows", len(conn.execute(trending_sql, params).fetchall()))


HANDLER_CHILD = textwrap.dedent(
    """
    import io, json, sqlite3, sys, threading, types
    sys.path[:0] = [sys.argv[1], sys.argv[2]]
    from handlers import similar
    from request_context import set_request_excluded_keys

    class Handler(similar.SimilarHandler):
        def __init__(self, server):
            self.server = server
            self.wfile = io.BytesIO()
            self.statuses = []

        def send_response(self, status, message=None):
            self.statuses.append(status)

        def send_header(self, name, value):
            pass

        def end_headers(self):
            pass

    out = []
    for db_path, params, excluded in json.loads(sys.argv[3]):
        db = sqlite3.connect(db_path)
        db.row_factory = sqlite3.Row
        server = types.SimpleNamespace(default_limit=20, refresh_similarity_cache=False, recommendations_debug_enabled=False, db=db, db_lock=threading.Lock(), video_error_threshold=3, embeddings_count=0, random_cache_db=None, random_cache_lock=threading.Lock())
        handler = Handler(server)
        set_request_excluded_keys(set(excluded))
        similar.SimilarHandler._handle_similar(handler, params)
        out.append({"statuses": handler.statuses, "body": json.loads(handler.wfile.getvalue() or b"null")})
        db.close()
    print(json.dumps(out))
    """
)


def test_handler_child(tmp_path):
    conn = _db(tmp_path / "h.db")
    for vid, nsfw in (("a", 0), ("b", 1), ("c", None)):
        conn.execute("INSERT INTO videos (video_id, instance_domain, likes, views, nsfw, last_checked_at, published_at) VALUES (?, 'h.example', 1, 1, ?, 0, 1)", (vid, nsfw))
        conn.execute("INSERT INTO video_embeddings VALUES (?, 'h.example', x'00', 1, 'm', 't', ?)", (vid, compute_ann_id(vid, "h.example")))
    conn.commit()
    cases = [[str(tmp_path / "h.db"), {"mode": ["popular"], "limit": ["20"]}, []], [str(tmp_path / "h.db"), {"mode": ["popular"], "limit": ["20"]}, ["a::h.example", "c::h.example"]], [str(tmp_path / "h.db"), {"mode": ["trending"], "limit": ["20"]}, []], [str(tmp_path / "h.db"), {"mode": ["random"], "limit": ["20"]}, []]]
    run = subprocess.run([str(ENGINE_PY), "-c", HANDLER_CHILD, str(SERVER_DIR), str(SERVER_DIR / "api"), json.dumps(cases)], cwd=SERVER_DIR / "api", capture_output=True, text=True, timeout=120)
    print("rc", run.returncode, run.stdout[-3000:], run.stderr[-3000:])


def test_live(engine):
    start = time.monotonic()
    for mode in ("hot", "trending", "popular"):
        status, body = engine.request("POST", f"/recommendations?mode={mode}&limit=12", headers={"X-Client-IP": "192.0.2.201"}, body={})
        print(mode, status, body.get("error"), body.get("allowed"), body.get("seed"), len(body.get("rows") or []))
    print("live ms", int((time.monotonic() - start) * 1000))
