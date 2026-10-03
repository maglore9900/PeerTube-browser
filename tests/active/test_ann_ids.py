"""`data/ann_ids.py`: the derived ANN id of a (video_id, host) key, the `video_embeddings` guards that refuse an id another key holds, and the schema check that refuses a `video_embeddings` predating `ann_id`.

- `compute_ann_id("abc", "peertube.example")` is 3578322927313005651, the big-endian 8-byte blake2b of `abc::peertube.example` masked to 63 bits; a literal computed outside the helper stands for "the same id in any process". `"Peertube.Example."`, `"https://peertube.example/w/abc"` and `"  PEERTUBE.EXAMPLE  "` give that same id, because the host goes through `normalize_host`.
- 300 keys give 300 distinct ids, each in 1..2**63-1.
- A domain `normalize_host` rejects (`"..."`, `"bad host"`, `"  Bad Host  "`) does not raise: its id is the pinned blake2b of `v::<trimmed, lowercased domain>`.
- On a table made by `create_video_embeddings_table` + `create_ann_id_guards`, holding (v1, h) with ann_id 111: an ann_id of 0 raises IntegrityError; another key carrying 111 raises IntegrityError under INSERT and under INSERT OR REPLACE, and the table is left exactly as it was (the holder row unchanged, the row count the same); an UPDATE of another key to 111 raises IntegrityError and changes nothing; a same-key INSERT OR REPLACE with a new payload goes through, keeps one row and keeps ann_id 111.
- `ensure_video_embeddings_schema` on a six-column table raises RuntimeError (not the raw OperationalError of creating the guards on it) naming `main.video_embeddings`, `migrate-whitelist.py` and `--resume-staging`, and leaves the table, its row and `sqlite_master` untouched. On a fresh DB it creates the seven-column table with `idx_video_embeddings_ann_id` and `video_embeddings_ann_id_collision`, and accepts that table on a second call. `assert_video_embeddings_has_ann_id` on a DB with no `video_embeddings` returns and creates nothing.

Each refusal is paired with the same write carrying a free id, which succeeds, so the refusal is the id's and not the fixture's. Runs in-process on tmp sqlite DBs.
"""
from __future__ import annotations

import sqlite3
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

SERVER_DIR = Path(__file__).resolve().parents[2] / "engine" / "server"
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from data.ann_ids import assert_video_embeddings_has_ann_id, compute_ann_id, create_ann_id_guards, create_video_embeddings_table, ensure_video_embeddings_schema  # noqa: E402

HOST = "peertube.example"
# int.from_bytes(hashlib.blake2b(b"abc::peertube.example", digest_size=8).digest(), "big") & ((1 << 63) - 1), run outside the helper; unmasked it is 12801694964167781459, little-endian 6029229592441628849, with a single-colon separator 5495739039877475741.
PINNED_ABC_ID = 3578322927313005651
HOLDER_ID = 111
COLUMNS = "video_id, instance_domain, embedding, embedding_dim, model_name, created_at, ann_id"
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
OLD_COLUMNS = ["video_id", "instance_domain", "embedding", "embedding_dim", "model_name", "created_at"]
OLD_ROW = ("v1", HOST, b"\x01", 1, "m", "t1")


def _write(conn: sqlite3.Connection, verb: str, video_id: str, ann_id: int, embedding: bytes = b"\x01", model_name: str = "m") -> None:
    conn.execute(f"{verb} INTO video_embeddings ({COLUMNS}) VALUES (?, ?, ?, 1, ?, 't', ?)", (video_id, HOST, embedding, model_name, ann_id))


def _rows(conn: sqlite3.Connection) -> list[tuple]:
    return conn.execute(f"SELECT {COLUMNS} FROM video_embeddings ORDER BY video_id").fetchall()


def _guard(conn: sqlite3.Connection) -> sqlite3.Connection:
    """Build the table from the shared definition and guards, holding (v1, HOST) with HOLDER_ID."""
    create_video_embeddings_table(conn)
    create_ann_id_guards(conn)
    _write(conn, "INSERT", "v1", HOLDER_ID)
    conn.commit()
    return conn


def _master(conn: sqlite3.Connection) -> list[tuple]:
    return conn.execute("SELECT type, name FROM sqlite_master ORDER BY name").fetchall()


def _old_table_with_a_row(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.executescript(OLD_VIDEO_EMBEDDINGS_SQL)
    conn.execute("INSERT INTO video_embeddings VALUES (?, ?, ?, ?, ?, ?)", OLD_ROW)
    conn.commit()
    return conn


@pytest.fixture
def db(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    """A tmp DB whose minimal `videos` table holds v1-v3 on HOST."""
    conn = sqlite3.connect(tmp_path / "whitelist.db")
    conn.execute("CREATE TABLE videos (video_id TEXT NOT NULL, instance_domain TEXT NOT NULL, PRIMARY KEY (video_id, instance_domain))")
    conn.executemany("INSERT INTO videos (video_id, instance_domain) VALUES (?, ?)", [(v, HOST) for v in ("v1", "v2", "v3")])
    conn.commit()
    yield conn
    conn.close()


def test_pinned_id():
    """The id of a key is the pinned big-endian, 63-bit-masked blake2b of `video_id::host`, the same in every process."""
    assert compute_ann_id("abc", HOST) == PINNED_ABC_ID


@pytest.mark.parametrize("spelling", ["Peertube.Example.", "https://peertube.example/w/abc", "  PEERTUBE.EXAMPLE  "])
def test_host_spelling_gives_the_pinned_id(spelling):
    """Every spelling of a host that `normalize_host` folds to one host gives that host's id."""
    assert compute_ann_id("abc", spelling) == PINNED_ABC_ID


def test_ids_are_distinct_positive_63_bit_values():
    """Ids are positive and fit in 63 bits, and distinct keys give distinct ids."""
    ids = [compute_ann_id(f"video-{n}", f"host{n % 7}.example") for n in range(300)]
    assert [i for i in ids if not 1 <= i <= 2**63 - 1] == []
    assert len(set(ids)) == 300


# blake2b of v::..., v::bad host, v::bad host, run outside the helper; untrimmed "v::  bad host  " is 6430014395957678378 and unlowered "v::  Bad Host  " is 8528140052437447888.
@pytest.mark.parametrize(("domain", "expected"), [("...", 2717215193390831227), ("bad host", 9164601000067536921), ("  Bad Host  ", 9164601000067536921)])
def test_unparsable_domain_falls_back_to_trimmed_lowercased_text(domain, expected):
    """A domain `normalize_host` rejects does not raise; its id is taken over the trimmed, lowercased text."""
    assert compute_ann_id("v", domain) == expected


def test_zero_ann_id_is_refused(db):
    """The table refuses an ann_id of 0."""
    guarded = _guard(db)
    before = _rows(guarded)
    with pytest.raises(sqlite3.IntegrityError):
        _write(guarded, "INSERT", "v2", 0)
    assert _rows(guarded) == before
    _write(guarded, "INSERT", "v2", 5)
    assert len(_rows(guarded)) == 2  # control: the same row with a non-zero id is accepted


def test_insert_of_another_keys_id_is_refused(db):
    """A plain INSERT of an ann_id another key holds is refused and leaves the table as it was."""
    guarded = _guard(db)
    before = _rows(guarded)
    with pytest.raises(sqlite3.IntegrityError):
        _write(guarded, "INSERT", "v2", HOLDER_ID)
    assert _rows(guarded) == before
    _write(guarded, "INSERT", "v2", 222)
    assert len(_rows(guarded)) == 2  # control: the same row with a free id is accepted


def test_insert_or_replace_of_another_keys_id_is_refused_and_keeps_the_holder(db):
    """INSERT OR REPLACE of an ann_id another key holds is refused before the replace can delete the holder."""
    guarded = _guard(db)
    before = _rows(guarded)
    with pytest.raises(sqlite3.IntegrityError):
        _write(guarded, "INSERT OR REPLACE", "v2", HOLDER_ID)
    assert _rows(guarded) == before
    _write(guarded, "INSERT OR REPLACE", "v2", 222)
    assert len(_rows(guarded)) == 2  # control: the same row with a free id is accepted


def test_same_key_replace_keeps_its_id(db):
    """The guards let a key replace its own row under its own ann_id."""
    guarded = _guard(db)
    _write(guarded, "INSERT OR REPLACE", "v1", HOLDER_ID, embedding=b"\x02", model_name="m2")
    assert _rows(guarded) == [("v1", HOST, b"\x02", 1, "m2", "t", HOLDER_ID)]


def test_update_to_another_keys_id_is_refused(db):
    """An UPDATE moving a row onto an ann_id another key holds is refused and changes nothing."""
    guarded = _guard(db)
    _write(guarded, "INSERT", "v2", 222)
    guarded.commit()
    before = _rows(guarded)
    with pytest.raises(sqlite3.IntegrityError):
        guarded.execute("UPDATE video_embeddings SET ann_id = ? WHERE video_id = 'v2'", (HOLDER_ID,))
    assert _rows(guarded) == before
    guarded.execute("UPDATE video_embeddings SET ann_id = 333 WHERE video_id = 'v2'")
    assert [row[-1] for row in _rows(guarded)] == [HOLDER_ID, 333]  # control: an UPDATE to a free id is accepted


def test_ensure_schema_refuses_a_six_column_table_with_the_migrate_pointer_and_writes_nothing(tmp_path):
    """A `video_embeddings` without `ann_id` is refused with a RuntimeError naming the schema, the migration and `--resume-staging`, before anything is written."""
    conn = _old_table_with_a_row(tmp_path / "whitelist.db")
    try:
        master_before = _master(conn)

        # RuntimeError, not sqlite3.OperationalError: creating the guards on this table fails with "no such column: ann_id", which is not a RuntimeError.
        with pytest.raises(RuntimeError) as refused:
            ensure_video_embeddings_schema(conn)

        message = str(refused.value)
        assert "main.video_embeddings" in message
        assert "migrate-whitelist.py" in message
        assert "--resume-staging" in message
        assert [row[1] for row in conn.execute("PRAGMA table_info(video_embeddings)")] == OLD_COLUMNS
        assert conn.execute("SELECT * FROM video_embeddings").fetchall() == [OLD_ROW]
        assert _master(conn) == master_before
    finally:
        conn.close()


def test_ensure_schema_creates_and_then_accepts_the_ann_id_table(tmp_path):
    """On a fresh DB the schema step creates the seven-column table with both guards, and accepts it on a second call."""
    conn = sqlite3.connect(tmp_path / "whitelist.db")
    try:
        ensure_video_embeddings_schema(conn)
        assert [row[1] for row in conn.execute("PRAGMA table_info(video_embeddings)")] == OLD_COLUMNS + ["ann_id"]
        assert {("index", "idx_video_embeddings_ann_id"), ("trigger", "video_embeddings_ann_id_collision")} <= set(_master(conn))
        ensure_video_embeddings_schema(conn)  # the migrated shape is not refused
    finally:
        conn.close()


def test_has_ann_id_check_does_nothing_without_the_table(tmp_path):
    """The ann_id check is a no-op on a DB with no `video_embeddings`."""
    conn = sqlite3.connect(tmp_path / "whitelist.db")
    try:
        assert assert_video_embeddings_has_ann_id(conn) is None
        assert _master(conn) == []
        # control: the same call does refuse once a six-column table exists, so the silence above is the missing table's.
        conn.executescript(OLD_VIDEO_EMBEDDINGS_SQL)
        with pytest.raises(RuntimeError, match="migrate-whitelist.py"):
            assert_video_embeddings_has_ann_id(conn)
    finally:
        conn.close()
