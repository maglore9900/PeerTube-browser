from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SERVER_DIR = ROOT / "engine" / "server"
REAL = SERVER_DIR / "db" / "jobs" / "whitelist_migrations.py"
CHECKPOINT = str(Path(__file__).with_name("test_41_ann_ids_a_schema_writers_phase2.py"))

DRAFT = '''

import sys as _sys
_sys.path.insert(0, {server!r})
import hashlib as _hashlib
from data.ann_ids import compute_ann_id, create_ann_id_guards

ann_id_of = compute_ann_id

NEW_DDL = """
CREATE TABLE IF NOT EXISTS video_embeddings_new (
  video_id TEXT NOT NULL,
  instance_domain TEXT NOT NULL,
  embedding BLOB NOT NULL,
  embedding_dim INTEGER NOT NULL,
  model_name TEXT NOT NULL,
  created_at TEXT NOT NULL,
  ann_id INTEGER NOT NULL CHECK (ann_id > 0),
  PRIMARY KEY (video_id, instance_domain),
  FOREIGN KEY (video_id, instance_domain) REFERENCES videos (video_id, instance_domain)
)
"""
COPY = "INSERT INTO video_embeddings_new (ROWIDCOL video_id, instance_domain, embedding, embedding_dim, model_name, created_at, ann_id) SELECT ROWIDCOL video_id, instance_domain, embedding, embedding_dim, model_name, created_at, ann_id_of(video_id, instance_domain) FROM video_embeddings"


def _raw(v, h):
    return int.from_bytes(_hashlib.blake2b(f"{{v}}::{{h}}".encode(), digest_size=8).digest(), "big") & ((1 << 63) - 1)


def migrate_video_embeddings_schema(conn):
    if BEGIN_FIRST:
        conn.execute("BEGIN")
    if not _table_exists(conn, "video_embeddings"):
        return
    if EARLY_RETURN and "ann_id" in _columns(conn, "video_embeddings"):
        return
    if conn.in_transaction:
        conn.commit()
    fn = FN
    if SCRIPT:
        conn.create_function("ann_id_of", 2, fn)
        conn.executescript(NEW_DDL + ";" + COPY + "; DROP TABLE video_embeddings; ALTER TABLE video_embeddings_new RENAME TO video_embeddings;")
        create_ann_id_guards(conn)
        conn.commit()
        return
    conn.execute("BEGIN")
    try:
        conn.create_function("ann_id_of", 2, fn)
        conn.execute(NEW_DDL)
        conn.execute(COPY)
        conn.execute("DROP TABLE video_embeddings")
        conn.execute("ALTER TABLE video_embeddings_new RENAME TO video_embeddings")
        if GUARDS:
            create_ann_id_guards(conn)
    except Exception:
        if ROLLBACK:
            conn.rollback()
        raise
    conn.commit()


def migrate_whitelist_schema(conn, table_name):
    migrate_instances_schema(conn, table_name)
    migrate_channels_schema(conn)
    migrate_videos_schema(conn)
    migrate_videos_language(conn)
    migrate_video_embeddings_schema(conn)
'''

LIVE = "lambda v, h: ann_id_of(v, h)"
VARIANTS = {
    "draft": {},
    "captured_fn": {"FN": "compute_ann_id"},
    "raw_host": {"FN": "_raw"},
    "renumber": {"ROWIDCOL": ""},
    "script": {"SCRIPT": "True"},
    "no_early_return": {"EARLY_RETURN": "False"},
    "begin_first": {"BEGIN_FIRST": "True"},
    "no_guards": {"GUARDS": "False"},
    "no_rollback": {"ROLLBACK": "False"},
}


def _source(overrides: dict) -> str:
    knobs = {"FN": LIVE, "ROWIDCOL": "rowid,", "SCRIPT": "False", "EARLY_RETURN": "True", "BEGIN_FIRST": "False", "GUARDS": "True", "ROLLBACK": "True"}
    knobs.update(overrides)
    body = DRAFT.format(server=str(SERVER_DIR)).replace("ROWIDCOL", knobs.pop("ROWIDCOL"))
    for key, value in knobs.items():
        body = body.replace(f"fn = FN" if key == "FN" else key, f"fn = {value}" if key == "FN" else value)
    return REAL.read_text() + body


@pytest.mark.parametrize("name", list(VARIANTS))
def test_mutant(name, tmp_path, monkeypatch):
    target = tmp_path / "whitelist_migrations.py"
    target.write_text(_source(VARIANTS[name]))
    real_spec = importlib.util.spec_from_file_location

    def spec(module_name, location, *args, **kwargs):
        if str(location).endswith("whitelist_migrations.py"):
            location = target
        return real_spec(module_name, location, *args, **kwargs)

    monkeypatch.setattr(importlib.util, "spec_from_file_location", spec)
    sys.modules.pop("test_41_ann_ids_a_schema_writers_phase2", None)
    code = pytest.main([CHECKPOINT, "-q", "-p", "no:cacheprovider", "-rf", "--no-header", "--tb=line"])
    print(f"\nMUTANT {name} exit={int(code)}")
