from __future__ import annotations

import hashlib
import sys
import types
from pathlib import Path

import pytest

SERVER_DIR = Path(__file__).resolve().parents[2] / "engine" / "server"
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from data.moderation import normalize_host  # noqa: E402

CHECKPOINT = str(Path(__file__).with_name("test_41_ann_ids_a_schema_writers_phase1.py"))
TABLE = """CREATE TABLE IF NOT EXISTS {table} (video_id TEXT NOT NULL, instance_domain TEXT NOT NULL, embedding BLOB NOT NULL, embedding_dim INTEGER NOT NULL, model_name TEXT NOT NULL, created_at TEXT NOT NULL, ann_id INTEGER NOT NULL {check}, PRIMARY KEY (video_id, instance_domain), FOREIGN KEY (video_id, instance_domain) REFERENCES videos (video_id, instance_domain))"""
INDEX = "CREATE UNIQUE INDEX IF NOT EXISTS idx_video_embeddings_ann_id ON video_embeddings (ann_id)"
TRIGGER = """CREATE TRIGGER IF NOT EXISTS video_embeddings_ann_id_collision BEFORE INSERT ON video_embeddings WHEN EXISTS (SELECT 1 FROM video_embeddings WHERE ann_id = NEW.ann_id AND (video_id <> NEW.video_id OR instance_domain <> NEW.instance_domain)) BEGIN SELECT RAISE(ABORT, 'collision'); END"""


def _make(name, *, order="big", mask=True, normalise=True, fallback="strip_lower", check=True, unique=True, trigger=True):
    mod = types.ModuleType("data.ann_ids")

    def compute_ann_id(video_id, instance_domain):
        host = normalize_host(instance_domain) if normalise else instance_domain
        if host is None:
            host = str(instance_domain).strip().lower() if fallback == "strip_lower" else str(instance_domain)
        value = int.from_bytes(hashlib.blake2b(f"{video_id}::{host}".encode("utf-8"), digest_size=8).digest(), order)
        return value & ((1 << 63) - 1) if mask else value

    def create_video_embeddings_table(conn, table="video_embeddings"):
        conn.execute(TABLE.format(table=table, check="CHECK (ann_id > 0)" if check else ""))

    def create_ann_id_guards(conn):
        if unique:
            conn.execute(INDEX)
        if trigger:
            conn.execute(TRIGGER)

    mod.compute_ann_id = compute_ann_id
    mod.create_video_embeddings_table = create_video_embeddings_table
    mod.create_ann_id_guards = create_ann_id_guards
    return name, mod


VARIANTS = [
    _make("draft"),
    _make("little_endian", order="little"),
    _make("unmasked", mask=False),
    _make("raw_host", normalise=False),
    _make("raw_fallback", fallback="raw"),
    _make("no_check", check=False),
    _make("unique_only", trigger=False),
    _make("trigger_only", unique=False),
]


@pytest.mark.parametrize(("name", "mod"), VARIANTS, ids=[v[0] for v in VARIANTS])
def test_mutant(name, mod, monkeypatch):
    monkeypatch.setitem(sys.modules, "data.ann_ids", mod)
    sys.modules.pop("test_41_ann_ids_a_schema_writers_phase1", None)
    code = pytest.main([CHECKPOINT, "-q", "-p", "no:cacheprovider", "-rf", "--no-header"])
    print(f"\nMUTANT {name} exit={int(code)}")
