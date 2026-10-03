"""An unmigrated `video_embeddings` is refused before any write, and an `ann_id` collision in a sync or a merge leaves the target DB as it was.

- `ensure_video_embeddings_schema` on a six-column table raises RuntimeError (not the raw OperationalError of creating the guards on it) naming `main.video_embeddings`, `migrate-whitelist.py` and `--resume-staging`, and leaves the table, its row and `sqlite_master` untouched. On a fresh DB it creates the seven-column table with `idx_video_embeddings_ann_id` and `video_embeddings_ann_id_collision`, and accepts that table on a second call. `assert_video_embeddings_has_ann_id` on a DB with no `video_embeddings` returns and creates nothing.
- `build-video-embeddings.py`'s `init_schema`, the step its `main()` runs before the model loads, on a six-column table (a staging DB reused with `--resume-staging`) raises the same RuntimeError and leaves the table, its row and `sqlite_master` untouched; on a fresh DB it creates the seven-column table with both guards.
- sync's `main()` on a six-column target raises RuntimeError naming `main.video_embeddings`, `missing columns: ann_id` and `migrate-whitelist.py`, and leaves the target's `instances`, `videos` and `video_embeddings` rows as they were.
- `merge-staging-db.py` with a six-column stage, and again with a six-column main, exits non-zero with a RuntimeError naming that side's `video_embeddings` (and not the other side's) and `migrate-whitelist.py`, logs no merged table, and leaves prod's `instances`, `videos` and `video_embeddings` rows as they were, though stage holds a host, a video and a re-embed prod lacks.
- `merge-staging-db.py` with an unguarded stage holding v1's ann_id on (v2, h) exits non-zero on the collision trigger, leaves prod's `instances`, `videos` and `video_embeddings` rows byte-identical and its `videos_fts_ai/ad/au` triggers in place; the same stage with v2's own id merges, adding the host, v2 and both staged embeddings.
- sync's `main()` from a source whose v2 carries v1's ann_id raises the collision trigger's IntegrityError and leaves the target's `instances`, `videos` and `video_embeddings` rows as they were and the `videos_fts_ai/ad/au` triggers in place; the same source with v2's own id syncs, adding `b.example` and v2.

Every DB is a tmp file; the merge runs as a command and sync in-process with `fetch_hosts` (the network) replaced by a fixed host set. Of `build-video-embeddings.py` only `init_schema` is called: the model stack is imported inside its `main()`, so its row tuple is not proven here.
"""
from __future__ import annotations

import importlib
import importlib.util
import sqlite3
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
SERVER_DIR = ROOT / "engine" / "server"
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))
JOBS_DIR = SERVER_DIR / "db" / "jobs"
CRAWL_SCHEMA = ROOT / "engine" / "crawler" / "schema.sql"
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
OLD_COLUMNS = ["video_id", "instance_domain", "embedding", "embedding_dim", "model_name", "created_at"]
HOST = "a.example"
# A host only the staging DB holds, so a merge that wrote `instances` at all changes prod's rows.
STAGE_ONLY_HOST = "b.example"
# int.from_bytes(hashlib.blake2b(key, digest_size=8).digest(), "big") & (2**63 - 1) for v1::a.example and v2::a.example, run outside the helper.
V1_ID = 8241284212183890047
V2_ID = 8744784223012906678
# (video_id, instance_domain, embedding, embedding_dim, model_name, created_at); the staged v1 is a re-embed, so a merge that went through would change prod's v1.
PROD_V1 = ("v1", HOST, b"\x01", 1, "m", "t1")
STAGE_V1 = ("v1", HOST, b"\x11", 1, "m2", "t9")
STAGE_V2 = ("v2", HOST, b"\x02", 1, "m", "t2")
FTS_TRIGGERS = {"videos_fts_ai", "videos_fts_ad", "videos_fts_au"}
COLLISION_MESSAGE = "video_embeddings ann_id collision"


def _ann_ids() -> ModuleType:
    return importlib.import_module("data.ann_ids")


def _load_job(module_name: str, filename: str):
    spec = importlib.util.spec_from_file_location(module_name, JOBS_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def sync_job():
    return _load_job("sync_whitelist_for_test_41_phase4", "sync-whitelist.py")


@pytest.fixture(scope="module")
def build_job():
    return _load_job("build_video_embeddings_for_test_41_phase4", "build-video-embeddings.py")


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


def _master(conn: sqlite3.Connection) -> list[tuple]:
    return conn.execute("SELECT type, name FROM sqlite_master ORDER BY name").fetchall()


def _old_table_with_a_row(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.executescript(OLD_VIDEO_EMBEDDINGS_SQL)
    conn.execute("INSERT INTO video_embeddings VALUES (?, ?, ?, ?, ?, ?)", PROD_V1)
    conn.commit()
    return conn


def test_ensure_schema_refuses_a_six_column_table_with_the_migrate_pointer_and_writes_nothing(tmp_path):
    conn = _old_table_with_a_row(tmp_path / "whitelist.db")
    try:
        master_before = _master(conn)

        # RuntimeError, not sqlite3.OperationalError: creating the guards on this table fails with "no such column: ann_id", which is not a RuntimeError.
        with pytest.raises(RuntimeError) as refused:
            _ann_ids().ensure_video_embeddings_schema(conn)  # C1

        message = str(refused.value)
        assert "main.video_embeddings" in message  # C1
        assert "migrate-whitelist.py" in message  # C1
        assert "--resume-staging" in message  # C1
        assert [row[1] for row in conn.execute("PRAGMA table_info(video_embeddings)")] == OLD_COLUMNS  # C1
        assert conn.execute("SELECT * FROM video_embeddings").fetchall() == [PROD_V1]  # C1
        assert _master(conn) == master_before  # C1
    finally:
        conn.close()


def test_ensure_schema_creates_and_then_accepts_the_ann_id_table(tmp_path):
    conn = sqlite3.connect(tmp_path / "whitelist.db")
    try:
        ensure = _ann_ids().ensure_video_embeddings_schema
        ensure(conn)
        assert [row[1] for row in conn.execute("PRAGMA table_info(video_embeddings)")] == OLD_COLUMNS + ["ann_id"]  # C1
        assert {("index", "idx_video_embeddings_ann_id"), ("trigger", "video_embeddings_ann_id_collision")} <= set(_master(conn))  # C1
        ensure(conn)  # C1: the migrated shape is not refused
    finally:
        conn.close()


def test_has_ann_id_check_does_nothing_without_the_table(tmp_path):
    conn = sqlite3.connect(tmp_path / "whitelist.db")
    try:
        assert _ann_ids().assert_video_embeddings_has_ann_id(conn) is None  # C1
        assert _master(conn) == []  # C1
        # control: the same call does refuse once a six-column table exists, so the silence above is the missing table's.
        conn.executescript(OLD_VIDEO_EMBEDDINGS_SQL)
        with pytest.raises(RuntimeError, match="migrate-whitelist.py"):
            _ann_ids().assert_video_embeddings_has_ann_id(conn)
    finally:
        conn.close()


def test_build_init_schema_refuses_a_resumed_six_column_staging_table_and_writes_nothing(build_job, tmp_path):
    # build-video-embeddings opens the staging DB as its main connection, so a resumed six-column staging table is `main.video_embeddings` to it.
    conn = _old_table_with_a_row(tmp_path / "staging.db")
    try:
        master_before = _master(conn)

        with pytest.raises(RuntimeError) as refused:
            build_job.init_schema(conn)  # C1

        message = str(refused.value)
        assert "main.video_embeddings" in message  # C1
        assert "migrate-whitelist.py" in message  # C1
        assert "--resume-staging" in message  # C1
        assert [row[1] for row in conn.execute("PRAGMA table_info(video_embeddings)")] == OLD_COLUMNS  # C1
        assert conn.execute("SELECT * FROM video_embeddings").fetchall() == [PROD_V1]  # C1
        assert _master(conn) == master_before  # C1
    finally:
        conn.close()


def test_build_init_schema_creates_the_ann_id_table_on_a_fresh_db(build_job, tmp_path):
    conn = sqlite3.connect(tmp_path / "staging.db")
    try:
        build_job.init_schema(conn)
        # control: the writer that refuses the six-column table above creates the guarded seven-column one, so the refusal is the old shape's.
        assert [row[1] for row in conn.execute("PRAGMA table_info(video_embeddings)")] == OLD_COLUMNS + ["ann_id"]
        assert {("index", "idx_video_embeddings_ann_id"), ("trigger", "video_embeddings_ann_id_collision")} <= set(_master(conn))
    finally:
        conn.close()


@pytest.mark.parametrize(("old_side", "other_side"), [("stage", "main"), ("main", "stage")], ids=["old-stage", "old-main"])
def test_merge_refuses_a_six_column_side_naming_it_before_any_write(sync_job, tmp_path, old_side, other_side):
    prod_db, staging_db = tmp_path / "prod.db", tmp_path / "staging.db"
    prod_old, stage_old = old_side == "main", old_side == "stage"
    _seed(_whitelist_db(sync_job, prod_db, "old" if prod_old else "new"), ["v1"], [PROD_V1 if prod_old else PROD_V1 + (V1_ID,)])
    _seed(_whitelist_db(sync_job, staging_db, "old" if stage_old else "new"), ["v1", "v2"], [STAGE_V1, STAGE_V2] if stage_old else [STAGE_V1 + (V1_ID,), STAGE_V2 + (V2_ID,)], hosts=(HOST, STAGE_ONLY_HOST))
    before = _state(prod_db)

    result = _merge(prod_db, staging_db)

    assert result.returncode != 0, result.stderr  # C1
    refusal = result.stderr.strip().splitlines()[-1]
    assert refusal.startswith("RuntimeError:"), result.stderr  # C1
    assert f"{old_side}.video_embeddings" in refusal  # C1
    assert f"{other_side}.video_embeddings" not in refusal  # C1
    assert "migrate-whitelist.py" in refusal  # C1
    # The merge logs one "merged table=" line per rule it has written; none means the refusal came before the first table.
    assert "merged table=" not in result.stderr  # C1
    after = _state(prod_db)
    assert after["instances"] == before["instances"]  # C1
    assert after["videos"] == before["videos"]  # C1
    assert after["video_embeddings"] == before["video_embeddings"]  # C1


def _collision_pair(sync_job, tmp_path: Path, v2_id: int) -> tuple[Path, Path]:
    prod_db, staging_db = tmp_path / "prod.db", tmp_path / "staging.db"
    _seed(_whitelist_db(sync_job, prod_db), ["v1"], [PROD_V1 + (V1_ID,)])
    # Unguarded, so staging itself can hold the doctored row a buggy writer would leave there.
    _seed(_whitelist_db(sync_job, staging_db, "unguarded"), ["v1", "v2"], [STAGE_V1 + (V1_ID,), STAGE_V2 + (v2_id,)], hosts=(HOST, STAGE_ONLY_HOST))
    return prod_db, staging_db


def test_merge_collision_fails_and_leaves_prod_rows_as_they_were(sync_job, tmp_path):
    prod_db, staging_db = _collision_pair(sync_job, tmp_path, V1_ID)
    before = _state(prod_db)

    result = _merge(prod_db, staging_db)

    assert result.returncode != 0, result.stderr  # C2
    assert COLLISION_MESSAGE in result.stderr.strip().splitlines()[-1], result.stderr  # C2: the run failed on the collision trigger, not on anything else
    after = _state(prod_db)
    assert after["instances"] == before["instances"]  # C2
    assert after["videos"] == before["videos"]  # C2
    assert after["video_embeddings"] == before["video_embeddings"]  # C2
    assert FTS_TRIGGERS <= after["triggers"]  # C2


def test_merge_without_collision_writes_the_staged_rows(sync_job, tmp_path):
    prod_db, staging_db = _collision_pair(sync_job, tmp_path, V2_ID)

    result = _merge(prod_db, staging_db)

    # control: the pair the collision test refuses merges once v2 carries its own id, changing all three tables; its log line arms the "merged table=" absence in the refusal test.
    assert result.returncode == 0, result.stderr
    assert "merged table=video_embeddings" in result.stderr
    after = _state(prod_db)
    assert [row[0] for row in after["instances"]] == [HOST, STAGE_ONLY_HOST]
    assert [row[0] for row in after["videos"]] == ["v1", "v2"]
    assert after["video_embeddings"] == [STAGE_V1 + (V1_ID,), STAGE_V2 + (V2_ID,)]


def _crawl_source(path: Path, v2_id: int) -> Path:
    conn = sqlite3.connect(path)
    conn.executescript(CRAWL_SCHEMA.read_text(encoding="utf-8"))
    conn.execute("INSERT INTO channels (channel_id, instance_domain) VALUES ('c1', ?)", (HOST,))
    conn.executemany("INSERT INTO videos (video_id, instance_domain, channel_id, title, last_checked_at) VALUES (?, ?, 'c1', ?, 1)", [("v1", HOST, "title v1"), ("v2", HOST, "title v2")])
    conn.executescript(SOURCE_ANN_ID_EMBEDDINGS_SQL)
    conn.executemany("INSERT INTO video_embeddings VALUES (?, ?, ?, ?, ?, ?, ?)", [PROD_V1 + (V1_ID,), STAGE_V2 + (v2_id,)])
    conn.commit()
    conn.close()
    return path


def _run_sync(sync_job, monkeypatch, source_db: Path, target_db: Path) -> None:
    # The remote whitelist adds b.example, so a sync that commits any of its work changes `instances`.
    monkeypatch.setattr(sync_job, "fetch_hosts", lambda url: {HOST, STAGE_ONLY_HOST})
    monkeypatch.setattr(sys, "argv", ["sync-whitelist.py", "--source-db", str(source_db), "--output-db", str(target_db)])
    sync_job.main()


def test_sync_refuses_a_six_column_target_naming_main_before_any_write(sync_job, tmp_path, monkeypatch):
    target_db = tmp_path / "whitelist.db"
    _seed(_whitelist_db(sync_job, target_db, "old"), ["v1"], [PROD_V1])
    before = _state(target_db)

    with pytest.raises(RuntimeError) as refused:
        _run_sync(sync_job, monkeypatch, _crawl_source(tmp_path / "crawl.db", V2_ID), target_db)  # C1

    message = str(refused.value)
    assert "main.video_embeddings" in message  # C1
    assert "missing columns: ann_id" in message  # C1
    assert "migrate-whitelist.py" in message  # C1
    after = _state(target_db)
    assert after["instances"] == before["instances"]  # C1
    assert after["videos"] == before["videos"]  # C1
    assert after["video_embeddings"] == before["video_embeddings"]  # C1


def test_sync_collision_fails_and_leaves_target_rows_and_fts_triggers_as_they_were(sync_job, tmp_path, monkeypatch):
    target_db = tmp_path / "whitelist.db"
    _seed(_whitelist_db(sync_job, target_db), ["v1"], [PROD_V1 + (V1_ID,)])
    source_db = _crawl_source(tmp_path / "crawl.db", V1_ID)
    before = _state(target_db)
    assert FTS_TRIGGERS <= before["triggers"], "control: the target starts with its videos_fts triggers"

    with pytest.raises(sqlite3.IntegrityError, match=COLLISION_MESSAGE):
        _run_sync(sync_job, monkeypatch, source_db, target_db)  # C2

    after = _state(target_db)
    assert after["instances"] == before["instances"]  # C2
    assert after["videos"] == before["videos"]  # C2
    assert after["video_embeddings"] == before["video_embeddings"]  # C2
    assert FTS_TRIGGERS <= after["triggers"]  # C2


def test_sync_without_collision_replaces_the_target_rows(sync_job, tmp_path, monkeypatch):
    target_db = tmp_path / "whitelist.db"
    _seed(_whitelist_db(sync_job, target_db), ["v1"], [PROD_V1 + (V1_ID,)])

    _run_sync(sync_job, monkeypatch, _crawl_source(tmp_path / "crawl.db", V2_ID), target_db)

    # control: the run the collision and old-target tests refuse does change all three tables when nothing collides.
    after = _state(target_db)
    assert [row[0] for row in after["instances"]] == [HOST, STAGE_ONLY_HOST]
    assert [row[0] for row in after["videos"]] == ["v1", "v2"]
    assert after["video_embeddings"] == [PROD_V1 + (V1_ID,), STAGE_V2 + (V2_ID,)]
