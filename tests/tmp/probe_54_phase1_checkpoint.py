"""Probe: PRAGMA index_xinfo for a DESC index, and the do_POST child harness on a tmp catalogue as the code stands."""
import json
import sqlite3
import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "active"))
from conftest import ENGINE_PY  # noqa: E402

SERVER_DIR = ROOT / "engine" / "server"
for p in (SERVER_DIR, SERVER_DIR / "api"):
    sys.path.insert(0, str(p))
from data.ann_ids import compute_ann_id, create_video_embeddings_table  # noqa: E402
from data.moderation import ensure_moderation_schema  # noqa: E402

CHILD = textwrap.dedent(
    """
    import io, json, sqlite3, sys, threading, types
    sys.path[:0] = [sys.argv[1], sys.argv[2]]
    from handlers import similar

    class Handler(similar.SimilarHandler):
        def __init__(self, server, path, body):
            raw = json.dumps(body).encode("utf-8")
            self.server = server
            self.path = path
            self.command = "POST"
            self.request_version = "HTTP/1.1"
            self.client_address = ("127.0.0.1", 0)
            self.headers = {"content-type": "application/json", "content-length": str(len(raw))}
            self.rfile = io.BytesIO(raw)
            self.wfile = io.BytesIO()
            self.statuses = []

        def send_response(self, status, message=None):
            self.statuses.append(status)

        def send_header(self, name, value):
            pass

        def end_headers(self):
            pass

    out = []
    for db_path, path, body in json.loads(sys.argv[3]):
        db = sqlite3.connect(db_path)
        db.row_factory = sqlite3.Row
        server = types.SimpleNamespace(default_limit=20, refresh_similarity_cache=False, recommendations_debug_enabled=False, db=db, db_lock=threading.Lock(), video_error_threshold=3, embeddings_count=0, random_cache_db=None, random_cache_lock=threading.Lock())
        handler = Handler(server, path, body)
        handler.do_POST()
        out.append({"statuses": handler.statuses, "body": json.loads(handler.wfile.getvalue() or b"null")})
        db.close()
    print(json.dumps(out))
    """
)


def test_index_xinfo(tmp_path):
    conn = sqlite3.connect(tmp_path / "x.db")
    print("sqlite", sqlite3.sqlite_version)
    conn.execute("CREATE TABLE videos (video_id TEXT, instance_domain TEXT, channel_id TEXT, account_url TEXT, published_at INTEGER, PRIMARY KEY (video_id, instance_domain))")
    conn.execute("CREATE INDEX i1 ON videos (instance_domain, channel_id, published_at DESC, video_id DESC)")
    conn.execute("CREATE INDEX i2 ON videos (account_url, published_at, video_id)")
    for name in ("i1", "i2"):
        print(name, conn.execute(f"PRAGMA index_xinfo({name})").fetchall())
    print("missing", conn.execute("PRAGMA index_xinfo(nope)").fetchall())


def test_child_harness(tmp_path):
    db_path = tmp_path / "cat.db"
    conn = sqlite3.connect(db_path)
    conn.executescript((ROOT / "engine" / "crawler" / "schema.sql").read_text(encoding="utf-8"))
    conn.execute("ALTER TABLE videos ADD COLUMN popularity REAL NOT NULL DEFAULT 0")
    create_video_embeddings_table(conn)
    ensure_moderation_schema(conn)
    for n in range(3):
        conn.execute("INSERT INTO videos (video_id, video_uuid, instance_domain, channel_id, account_url, published_at, last_checked_at) VALUES (?, ?, 'a.example', 'ch-a', 'acct', ?, 0)", (f"v{n}", f"u{n}", 1_700_000_000_000 + n))
        conn.execute("INSERT INTO video_embeddings VALUES (?, 'a.example', x'00', 1, 'm', 't', ?)", (f"v{n}", compute_ann_id(f"v{n}", "a.example")))
    conn.commit()
    conn.close()
    cases = [
        [str(db_path), "/recommendations?mode=random&limit=4", {}],
        [str(db_path), "/recommendations?mode=recent&limit=4", {}],
        [str(db_path), "/recommendations?mode=following&limit=4", {"follows": {"channels": [["a.example", "ch-a"]], "accounts": []}}],
        [str(db_path), "/recommendations?mode=following&limit=4", {}],
    ]
    run = subprocess.run([str(ENGINE_PY), "-c", CHILD, str(SERVER_DIR), str(SERVER_DIR / "api"), json.dumps(cases)], cwd=SERVER_DIR / "api", capture_output=True, text=True, timeout=120)
    print("rc", run.returncode)
    print("stderr tail", run.stderr[-1500:])
    for case in json.loads(run.stdout.strip().splitlines()[-1]):
        body = case["body"]
        print(case["statuses"], {k: v for k, v in body.items() if k != "rows"}, [(r["video_id"], r["published_at"]) for r in body.get("rows", [])])
