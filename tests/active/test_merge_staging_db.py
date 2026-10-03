"""`merge-staging-db.py` carries the staged `ann_id` into prod, refuses an unmigrated side before any write, and rolls a merge that hits an `ann_id` collision back whole.

- Run over a prod holding v1 and a staging holding a replacement v1 plus v2 and v3, it exits 0 and leaves prod with the staging rows, each carrying its pinned id; prod's v1, seeded under a sentinel that is not its derived id, ends under the pinned id, not the old one. Staging already holds the derived ids, which the merge carries across unchanged, so this does not show the merge deriving them.
- With a six-column stage, and again with a six-column main, it exits non-zero with a RuntimeError naming that side's `video_embeddings` (and not the other side's) and `migrate-whitelist.py`, logs no merged table, and leaves prod's `instances`, `videos` and `video_embeddings` rows as they were, though stage holds a host, a video and a re-embed prod lacks.
- With an unguarded stage holding v1's ann_id on (v2, h), it exits non-zero on the collision trigger, leaves prod's `instances`, `videos` and `video_embeddings` rows byte-identical and its `videos_fts_ai/ad/au` triggers in place; the same stage with v2's own id merges, adding the host, v2 and both staged embeddings.

Every DB is a tmp file built with `sync-whitelist.py`'s schema helpers; the merge runs as a command.
"""
from __future__ import annotations

import importlib.util
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
JOBS_DIR = ROOT / "engine" / "server" / "db" / "jobs"
MERGE_JOB = JOBS_DIR / "merge-staging-db.py"

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
HOST = "a.example"
# A host only the staging DB holds, so a merge that wrote `instances` at all changes prod's rows.
STAGE_ONLY_HOST = "b.example"
# int.from_bytes(hashlib.blake2b(key, digest_size=8).digest(), "big") & (2**63 - 1) for v1::a.example, v2::a.example, v3::b.example, run outside the helper.
V1_ID = 8241284212183890047
V2_ID = 8744784223012906678
V3_ID = 3553096638009034147
# Not v1's derived id: prod's v1 holds it before the merge, so a replace that keeps prod's old id is told apart from one that takes the staged V1_ID.
V1_SENTINEL = 555
# (video_id, instance_domain, embedding, embedding_dim, model_name, created_at); v3's host is stored unnormalised.
EMBEDDINGS = [("v1", "a.example", b"\x01\x02", 2, "m", "t1"), ("v2", "a.example", b"\x03\x04", 2, "m", "t2"), ("v3", "B.Example.", b"\x05\x06", 2, "m", "t3")]
COLUMNS = "video_id, instance_domain, embedding, embedding_dim, model_name, created_at, ann_id"
ROWS_SQL = f"SELECT {COLUMNS} FROM video_embeddings ORDER BY video_id"
# The staged v1 is a re-embed, so a merge that went through would change prod's v1.
PROD_V1 = ("v1", HOST, b"\x01", 1, "m", "t1")
STAGE_V1 = ("v1", HOST, b"\x11", 1, "m2", "t9")
STAGE_V2 = ("v2", HOST, b"\x02", 1, "m", "t2")
FTS_TRIGGERS = {"videos_fts_ai", "videos_fts_ad", "videos_fts_au"}
COLLISION_MESSAGE = "video_embeddings ann_id collision"


def _load_job(module_name: str, filename: str):
    spec = importlib.util.spec_from_file_location(module_name, JOBS_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def sync_job():
    return _load_job("sync_whitelist_for_test_merge_staging_db", "sync-whitelist.py")


def _whitelist_db(sync_job, path: Path, shape: str = "new") -> sqlite3.Connection:
    """A whitelist-shaped DB: `new` from the shared definition with its guards, `old` with the six-column table, `unguarded` new without the ann_id index and trigger."""
    conn = sqlite3.connect(path)
    if shape == "old":
        conn.executescript(OLD_VIDEO_EMBEDDINGS_SQL)
    sync_job.ensure_whitelist_schema(conn)
    sync_job.ensure_content_schema(conn)
    if shape == "unguarded":
        conn.execute("DROP TRIGGER video_embeddings_ann_id_collision")
        conn.execute("DROP INDEX idx_video_embeddings_ann_id")
    return conn


def _seed(conn: sqlite3.Connection, video_ids: list[str], embeddings: list[tuple], hosts: tuple[str, ...] = (HOST,)) -> None:
    conn.executemany("INSERT INTO instances (host, health_status, health_checked_at) VALUES (?, 'ok', 1)", [(host,) for host in hosts])
    conn.executemany("INSERT INTO videos (video_id, instance_domain, title, last_checked_at) VALUES (?, ?, ?, 1)", [(v, HOST, f"title {v}") for v in video_ids])
    for row in embeddings:
        conn.execute(f"INSERT INTO video_embeddings VALUES ({', '.join('?' * len(row))})", row)
    conn.commit()
    conn.close()


def _seed_keys(conn: sqlite3.Connection, videos: list[tuple], embeddings: list[tuple]) -> None:
    """Seed `videos` by (video_id, instance_domain) and `video_embeddings` by its seven named columns, with no `instances` rows."""
    conn.executemany("INSERT INTO videos (video_id, instance_domain, last_checked_at) VALUES (?, ?, 1)", videos)
    conn.executemany(f"INSERT INTO video_embeddings ({COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?)", embeddings)
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


def _merge(prod_db: Path, staging_db: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(MERGE_JOB), "--prod-db", str(prod_db), "--staging-db", str(staging_db)], capture_output=True, text=True)


def _collision_pair(sync_job, tmp_path: Path, v2_id: int) -> tuple[Path, Path]:
    prod_db, staging_db = tmp_path / "prod.db", tmp_path / "staging.db"
    _seed(_whitelist_db(sync_job, prod_db), ["v1"], [PROD_V1 + (V1_ID,)])
    # Unguarded, so staging itself can hold the doctored row a buggy writer would leave there.
    _seed(_whitelist_db(sync_job, staging_db, "unguarded"), ["v1", "v2"], [STAGE_V1 + (V1_ID,), STAGE_V2 + (v2_id,)], hosts=(HOST, STAGE_ONLY_HOST))
    return prod_db, staging_db


def test_merge_leaves_prod_rows_carrying_the_derived_id(sync_job, tmp_path):
    """A merge replaces prod's rows with the staged ones, `ann_id` included, so prod ends on each key's derived id rather than the one it held."""
    prod_db, staging_db = tmp_path / "prod.db", tmp_path / "staging.db"
    replacement_v1 = ("v1", "a.example", b"\x11\x12", 2, "m2", "t9", V1_ID)
    staged = [replacement_v1, EMBEDDINGS[1] + (V2_ID,), EMBEDDINGS[2] + (V3_ID,)]
    _seed_keys(_whitelist_db(sync_job, prod_db), [("v1", "a.example")], [EMBEDDINGS[0] + (V1_SENTINEL,)])
    _seed_keys(_whitelist_db(sync_job, staging_db), [row[:2] for row in EMBEDDINGS], staged)

    result = _merge(prod_db, staging_db)

    assert result.returncode == 0, result.stderr
    prod = sqlite3.connect(prod_db)
    try:
        assert prod.execute(ROWS_SQL).fetchall() == staged
    finally:
        prod.close()


@pytest.mark.parametrize(("old_side", "other_side"), [("stage", "main"), ("main", "stage")], ids=["old-stage", "old-main"])
def test_merge_refuses_a_six_column_side_naming_it_before_any_write(sync_job, tmp_path, old_side, other_side):
    """A side whose `video_embeddings` predates `ann_id` is refused, naming only that side and the migration, before the merge writes anything."""
    prod_db, staging_db = tmp_path / "prod.db", tmp_path / "staging.db"
    prod_old, stage_old = old_side == "main", old_side == "stage"
    _seed(_whitelist_db(sync_job, prod_db, "old" if prod_old else "new"), ["v1"], [PROD_V1 if prod_old else PROD_V1 + (V1_ID,)])
    _seed(_whitelist_db(sync_job, staging_db, "old" if stage_old else "new"), ["v1", "v2"], [STAGE_V1, STAGE_V2] if stage_old else [STAGE_V1 + (V1_ID,), STAGE_V2 + (V2_ID,)], hosts=(HOST, STAGE_ONLY_HOST))
    before = _state(prod_db)

    result = _merge(prod_db, staging_db)

    assert result.returncode != 0, result.stderr
    refusal = result.stderr.strip().splitlines()[-1]
    assert refusal.startswith("RuntimeError:"), result.stderr
    assert f"{old_side}.video_embeddings" in refusal
    assert f"{other_side}.video_embeddings" not in refusal
    assert "migrate-whitelist.py" in refusal
    # The merge logs one "merged table=" line per rule it has written; none means the refusal came before the first table.
    assert "merged table=" not in result.stderr
    after = _state(prod_db)
    assert after["instances"] == before["instances"]
    assert after["videos"] == before["videos"]
    assert after["video_embeddings"] == before["video_embeddings"]


def test_merge_collision_fails_and_leaves_prod_rows_as_they_were(sync_job, tmp_path):
    """A staged row carrying another key's `ann_id` fails the merge and rolls all of it back, prod's FTS triggers included."""
    prod_db, staging_db = _collision_pair(sync_job, tmp_path, V1_ID)
    before = _state(prod_db)

    result = _merge(prod_db, staging_db)

    assert result.returncode != 0, result.stderr
    assert COLLISION_MESSAGE in result.stderr.strip().splitlines()[-1], result.stderr  # the run failed on the collision trigger, not on anything else
    after = _state(prod_db)
    assert after["instances"] == before["instances"]
    assert after["videos"] == before["videos"]
    assert after["video_embeddings"] == before["video_embeddings"]
    assert FTS_TRIGGERS <= after["triggers"]


def test_merge_without_collision_writes_the_staged_rows(sync_job, tmp_path):
    """A merge with no collision writes the staged `instances`, `videos` and `video_embeddings` into prod and logs each table."""
    prod_db, staging_db = _collision_pair(sync_job, tmp_path, V2_ID)

    result = _merge(prod_db, staging_db)

    # control: the pair the collision test refuses merges once v2 carries its own id, changing all three tables; its log line arms the "merged table=" absence in the refusal test.
    assert result.returncode == 0, result.stderr
    assert "merged table=video_embeddings" in result.stderr
    after = _state(prod_db)
    assert [row[0] for row in after["instances"]] == [HOST, STAGE_ONLY_HOST]
    assert [row[0] for row in after["videos"]] == ["v1", "v2"]
    assert after["video_embeddings"] == [STAGE_V1 + (V1_ID,), STAGE_V2 + (V2_ID,)]
