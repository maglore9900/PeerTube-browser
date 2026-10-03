import importlib
import importlib.util
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SERVER_DIR = ROOT / "engine" / "server"
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))
JOBS_DIR = SERVER_DIR / "db" / "jobs"
CRAWL_SCHEMA = ROOT / "engine" / "crawler" / "schema.sql"
MERGE_JOB = JOBS_DIR / "merge-staging-db.py"
OLD = """
CREATE TABLE video_embeddings (
  video_id TEXT NOT NULL, instance_domain TEXT NOT NULL, embedding BLOB NOT NULL, embedding_dim INTEGER NOT NULL, model_name TEXT NOT NULL, created_at TEXT NOT NULL,
  PRIMARY KEY (video_id, instance_domain),
  FOREIGN KEY (video_id, instance_domain) REFERENCES videos (video_id, instance_domain)
);
"""
SRC = """
CREATE TABLE video_embeddings (
  video_id TEXT NOT NULL, instance_domain TEXT NOT NULL, embedding BLOB NOT NULL, embedding_dim INTEGER NOT NULL, model_name TEXT NOT NULL, created_at TEXT NOT NULL, ann_id INTEGER NOT NULL,
  PRIMARY KEY (video_id, instance_domain)
);
"""
V1_ID = 8241284212183890047
V2_ID = 8744784223012906678


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, JOBS_DIR / filename)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _target(sj, path, shape="new"):
    conn = sqlite3.connect(path)
    if shape == "old":
        conn.executescript(OLD)
    sj.ensure_whitelist_schema(conn)
    sj.ensure_content_schema(conn)
    if shape == "unguarded":
        conn.execute("DROP TRIGGER video_embeddings_ann_id_collision")
        conn.execute("DROP INDEX idx_video_embeddings_ann_id")
    return conn


def _seed(conn, vids, embeddings, hosts=("a.example",)):
    for h in hosts:
        conn.execute("INSERT INTO instances (host, health_status, health_checked_at) VALUES (?, 'ok', 1)", (h,))
    conn.executemany("INSERT INTO videos (video_id, instance_domain, title, last_checked_at) VALUES (?, 'a.example', ?, 1)", [(v, v) for v in vids])
    for e in embeddings:
        conn.execute(f"INSERT INTO video_embeddings VALUES ({', '.join('?' * len(e))})", e)
    conn.commit()
    conn.close()


def _snap(path):
    c = sqlite3.connect(path)
    out = {t: c.execute(f"SELECT * FROM {t} ORDER BY 1, 2").fetchall() for t in ("instances", "videos", "video_embeddings")}
    out["triggers"] = sorted(r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='trigger'"))
    out["master"] = c.execute("SELECT type, name FROM sqlite_master ORDER BY name").fetchall()
    c.close()
    return out


def test_build_init_schema_old():
    bj = _load("build_probe_p4", "build-video-embeddings.py")
    print("BUILD module loaded; has init_schema:", hasattr(bj, "init_schema"), "numpy in sys.modules:", "numpy" in sys.modules, "torch:", "torch" in sys.modules)
    conn = sqlite3.connect(":memory:")
    conn.executescript(OLD)
    conn.execute("INSERT INTO video_embeddings VALUES ('v1', 'a.example', x'01', 1, 'm', 't1')")
    conn.commit()
    try:
        bj.init_schema(conn)
        print("BUILD init_schema old: no exception")
    except BaseException as exc:
        print("BUILD init_schema old raised", type(exc).__mro__, exc)
    print("BUILD cols", [r[1] for r in conn.execute("PRAGMA table_info(video_embeddings)")], "rows", conn.execute("SELECT * FROM video_embeddings").fetchall())


def _source(path, v2_id):
    c = sqlite3.connect(path)
    c.executescript(CRAWL_SCHEMA.read_text(encoding="utf-8"))
    c.execute("INSERT INTO channels (channel_id, instance_domain) VALUES ('c1', 'a.example')")
    c.executemany("INSERT INTO videos (video_id, instance_domain, channel_id, title, last_checked_at) VALUES (?, 'a.example', 'c1', ?, 1)", [("v1", "one"), ("v2", "two")])
    c.executescript(SRC)
    c.executemany("INSERT INTO video_embeddings VALUES (?, 'a.example', ?, 1, 'm', 't', ?)", [("v1", b"\x01", V1_ID), ("v2", b"\x02", v2_id)])
    c.commit()
    c.close()


def test_sync_old_target(tmp_path, monkeypatch):
    sj = _load("sync_probe_p4b", "sync-whitelist.py")
    _seed(_target(sj, tmp_path / "w.db", "old"), ["v1"], [("v1", "a.example", b"\x01", 1, "m", "t1")])
    _source(tmp_path / "c.db", V2_ID)
    monkeypatch.setattr(sj, "fetch_hosts", lambda url: {"a.example", "b.example"})
    monkeypatch.setattr(sys, "argv", ["sync-whitelist.py", "--source-db", str(tmp_path / "c.db"), "--output-db", str(tmp_path / "w.db")])
    before = _snap(tmp_path / "w.db")
    try:
        sj.main()
        print("SYNC old target: no exception")
    except BaseException as exc:
        print("SYNC old target raised", type(exc).__mro__, repr(str(exc)))
    after = _snap(tmp_path / "w.db")
    print("SYNC old before", before, "\nSYNC old after", after, "\nSYNC old same:", before == after)


def test_sync_collision_message(tmp_path, monkeypatch):
    sj = _load("sync_probe_p4c", "sync-whitelist.py")
    _seed(_target(sj, tmp_path / "w.db"), ["v1"], [("v1", "a.example", b"\x01", 1, "m", "t1", V1_ID)])
    _source(tmp_path / "c.db", V1_ID)
    monkeypatch.setattr(sj, "fetch_hosts", lambda url: {"a.example", "b.example"})
    monkeypatch.setattr(sys, "argv", ["sync-whitelist.py", "--source-db", str(tmp_path / "c.db"), "--output-db", str(tmp_path / "w.db")])
    try:
        sj.main()
        print("SYNC collision: no exception")
    except BaseException as exc:
        print("SYNC collision raised", type(exc).__name__, repr(str(exc)))


def test_merge_collision_and_extra_host(tmp_path):
    sj = _load("sync_probe_p4d", "sync-whitelist.py")
    for v2_id in (V1_ID, V2_ID):
        d = tmp_path / str(v2_id)
        d.mkdir()
        _seed(_target(sj, d / "p.db"), ["v1"], [("v1", "a.example", b"\x01", 1, "m", "t1", V1_ID)])
        _seed(_target(sj, d / "s.db", "unguarded"), ["v1", "v2"], [("v1", "a.example", b"\x11", 1, "m2", "t9", V1_ID), ("v2", "a.example", b"\x02", 1, "m", "t2", v2_id)], hosts=("a.example", "b.example"))
        before = _snap(d / "p.db")
        r = _merge(d / "p.db", d / "s.db")
        after = _snap(d / "p.db")
        print("MERGE v2_id", v2_id, "rc", r.returncode, "\nlast line:", repr(r.stderr.strip().splitlines()[-1]), "\nstderr:", r.stderr, "\ninstances before", before["instances"], "after", after["instances"])


def test_merge_old_stage_extra_host(tmp_path):
    sj = _load("sync_probe_p4e", "sync-whitelist.py")
    _seed(_target(sj, tmp_path / "p.db"), ["v1"], [("v1", "a.example", b"\x01", 1, "m", "t1", V1_ID)])
    _seed(_target(sj, tmp_path / "s.db", "old"), ["v1", "v2"], [("v1", "a.example", b"\x11", 1, "m2", "t9"), ("v2", "a.example", b"\x02", 1, "m", "t2")], hosts=("a.example", "b.example"))
    before = _snap(tmp_path / "p.db")
    r = _merge(tmp_path / "p.db", tmp_path / "s.db")
    after = _snap(tmp_path / "p.db")
    print("MERGE old-stage extra host rc", r.returncode, "\nstderr:", r.stderr, "\ninstances before", before["instances"], "after", after["instances"])


def test_fresh_shared_definition_without_videos():
    ann_ids = importlib.import_module("data.ann_ids")
    conn = sqlite3.connect(":memory:")
    ann_ids.create_video_embeddings_table(conn)
    ann_ids.create_ann_id_guards(conn)
    print("FRESH cols", [r[1] for r in conn.execute("PRAGMA table_info(video_embeddings)")], "master", conn.execute("SELECT type, name FROM sqlite_master ORDER BY name").fetchall())


def _merge(prod, stage):
    return subprocess.run([sys.executable, str(MERGE_JOB), "--prod-db", str(prod), "--staging-db", str(stage)], capture_output=True, text=True)
