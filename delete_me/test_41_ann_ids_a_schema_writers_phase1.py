"""`data/ann_ids.py`: the derived ANN id of a (video_id, host) key, and the `video_embeddings` guards that refuse an id another key holds.

- `compute_ann_id("abc", "peertube.example")` is 3578322927313005651, the big-endian 8-byte blake2b of `abc::peertube.example` masked to 63 bits; a literal computed outside the helper stands for "the same id in any process". `"Peertube.Example."`, `"https://peertube.example/w/abc"` and `"  PEERTUBE.EXAMPLE  "` give that same id, because the host goes through `normalize_host`.
- 300 keys give 300 distinct ids, each in 1..2**63-1.
- A domain `normalize_host` rejects (`"..."`, `"bad host"`, `"  Bad Host  "`) does not raise: its id is the pinned blake2b of `v::<trimmed, lowercased domain>`.
- On a table made by `create_video_embeddings_table` + `create_ann_id_guards`, holding (v1, h) with ann_id 111: an ann_id of 0 raises IntegrityError; another key carrying 111 raises IntegrityError under INSERT and under INSERT OR REPLACE, and the table is left exactly as it was (the holder row unchanged, the row count the same); an UPDATE of another key to 111 raises IntegrityError and changes nothing; a same-key INSERT OR REPLACE with a new payload goes through, keeps one row and keeps ann_id 111.

Each refusal is paired with the same write carrying a free id, which succeeds, so the refusal is the id's and not the fixture's. Runs in-process on a tmp sqlite DB with a minimal `videos` table.
"""
from __future__ import annotations

import importlib
import sqlite3
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest

SERVER_DIR = Path(__file__).resolve().parents[2] / "engine" / "server"
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

HOST = "peertube.example"
# int.from_bytes(hashlib.blake2b(b"abc::peertube.example", digest_size=8).digest(), "big") & ((1 << 63) - 1), run outside the helper; unmasked it is 12801694964167781459, little-endian 6029229592441628849, with a single-colon separator 5495739039877475741.
PINNED_ABC_ID = 3578322927313005651
HOLDER_ID = 111
COLUMNS = "video_id, instance_domain, embedding, embedding_dim, model_name, created_at, ann_id"


def _ann_ids() -> ModuleType:
    # Imported per test rather than at module level so the file collects before the module exists and each test fails on its own.
    return importlib.import_module("data.ann_ids")


def _write(conn: sqlite3.Connection, verb: str, video_id: str, ann_id: int, embedding: bytes = b"\x01", model_name: str = "m") -> None:
    conn.execute(f"{verb} INTO video_embeddings ({COLUMNS}) VALUES (?, ?, ?, 1, ?, 't', ?)", (video_id, HOST, embedding, model_name, ann_id))


def _rows(conn: sqlite3.Connection) -> list[tuple]:
    return conn.execute(f"SELECT {COLUMNS} FROM video_embeddings ORDER BY video_id").fetchall()


def _guard(conn: sqlite3.Connection) -> sqlite3.Connection:
    """Build the table from the shared definition and guards, holding (v1, HOST) with HOLDER_ID."""
    ann_ids = _ann_ids()
    ann_ids.create_video_embeddings_table(conn)
    ann_ids.create_ann_id_guards(conn)
    _write(conn, "INSERT", "v1", HOLDER_ID)
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
    assert _ann_ids().compute_ann_id("abc", HOST) == PINNED_ABC_ID  # C1


@pytest.mark.parametrize("spelling", ["Peertube.Example.", "https://peertube.example/w/abc", "  PEERTUBE.EXAMPLE  "])
def test_host_spelling_gives_the_pinned_id(spelling):
    assert _ann_ids().compute_ann_id("abc", spelling) == PINNED_ABC_ID  # C1


def test_ids_are_distinct_positive_63_bit_values():
    compute_ann_id = _ann_ids().compute_ann_id
    ids = [compute_ann_id(f"video-{n}", f"host{n % 7}.example") for n in range(300)]
    assert [i for i in ids if not 1 <= i <= 2**63 - 1] == []  # C1
    assert len(set(ids)) == 300  # C1


# blake2b of v::..., v::bad host, v::bad host, run outside the helper; untrimmed "v::  bad host  " is 6430014395957678378 and unlowered "v::  Bad Host  " is 8528140052437447888.
@pytest.mark.parametrize(("domain", "expected"), [("...", 2717215193390831227), ("bad host", 9164601000067536921), ("  Bad Host  ", 9164601000067536921)])
def test_unparsable_domain_falls_back_to_trimmed_lowercased_text(domain, expected):
    assert _ann_ids().compute_ann_id("v", domain) == expected  # C1


def test_zero_ann_id_is_refused(db):
    guarded = _guard(db)
    before = _rows(guarded)
    with pytest.raises(sqlite3.IntegrityError):
        _write(guarded, "INSERT", "v2", 0)  # C2
    assert _rows(guarded) == before  # C2
    _write(guarded, "INSERT", "v2", 5)
    assert len(_rows(guarded)) == 2  # control: the same row with a non-zero id is accepted


def test_insert_of_another_keys_id_is_refused(db):
    guarded = _guard(db)
    before = _rows(guarded)
    with pytest.raises(sqlite3.IntegrityError):
        _write(guarded, "INSERT", "v2", HOLDER_ID)  # C2
    assert _rows(guarded) == before  # C2
    _write(guarded, "INSERT", "v2", 222)
    assert len(_rows(guarded)) == 2  # control: the same row with a free id is accepted


def test_insert_or_replace_of_another_keys_id_is_refused_and_keeps_the_holder(db):
    guarded = _guard(db)
    before = _rows(guarded)
    with pytest.raises(sqlite3.IntegrityError):
        _write(guarded, "INSERT OR REPLACE", "v2", HOLDER_ID)  # C2
    assert _rows(guarded) == before  # C2
    _write(guarded, "INSERT OR REPLACE", "v2", 222)
    assert len(_rows(guarded)) == 2  # control: the same row with a free id is accepted


def test_same_key_replace_keeps_its_id(db):
    guarded = _guard(db)
    _write(guarded, "INSERT OR REPLACE", "v1", HOLDER_ID, embedding=b"\x02", model_name="m2")
    assert _rows(guarded) == [("v1", HOST, b"\x02", 1, "m2", "t", HOLDER_ID)]  # C2


def test_update_to_another_keys_id_is_refused(db):
    guarded = _guard(db)
    _write(guarded, "INSERT", "v2", 222)
    guarded.commit()
    before = _rows(guarded)
    with pytest.raises(sqlite3.IntegrityError):
        guarded.execute("UPDATE video_embeddings SET ann_id = ? WHERE video_id = 'v2'", (HOLDER_ID,))  # C2
    assert _rows(guarded) == before  # C2
    guarded.execute("UPDATE video_embeddings SET ann_id = 333 WHERE video_id = 'v2'")
    assert [row[-1] for row in _rows(guarded)] == [HOLDER_ID, 333]  # control: an UPDATE to a free id is accepted
