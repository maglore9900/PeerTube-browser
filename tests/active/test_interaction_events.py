"""One `prune_interaction_raw_events` call strips the actor and payload data from every raw event older than the cutoff (ADR-0005).

- A row ingested 31 days ago loses `raw_payload_json`, `actor_id` and `source_instance`, and every other column keeps its value; a 29-day row is left as it was, no row is deleted, and the call returns 1.
- The cutoff is exclusive: a row at `cutoff - 1` is stripped and a row at `cutoff` is not. A stale row holding only one of the three columns is stripped too.
- With `chunk_size=2`, five stale rows are stripped in three committed chunks of at most 2, one per hold of the lock, and a fourth hold finds nothing. Another connection sees each chunk before the lock is released.
- An event ingested for real, aged and stripped, is still reported as a duplicate when replayed; the replay moves no signal and does not restore the stripped columns.
- `ensure_interaction_event_schema` creates `interaction_raw_events_unstripped_idx`, and the prune's statement finds its rows through it, going by SQLite's query plan.

Every database is a temporary one built by `ensure_interaction_event_schema`; rows are aged by writing `ingested_at` directly.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SERVER_DIR = ROOT / "engine" / "server"
# `data` imports `recommendations`, which lives under `api`, as the Engine's server.py runs it.
for path in (SERVER_DIR, SERVER_DIR / "api"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from data import interaction_events  # noqa: E402
from data.interaction_events import ensure_interaction_event_schema, ingest_interaction_event  # noqa: E402
from data.time import now_ms  # noqa: E402

DAY_MS = 86_400_000
STRIPPED = ("raw_payload_json", "actor_id", "source_instance")
UNSTRIPPED_INDEX = "interaction_raw_events_unstripped_idx"


def _db(tmp_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(tmp_path / "engine.db")
    conn.row_factory = sqlite3.Row
    ensure_interaction_event_schema(conn)
    return conn


def _insert_raw(conn: sqlite3.Connection, event_id: str, ingested_at: int, **columns) -> None:
    row = {"event_id": event_id, "event_type": "Like", "actor_id": "actor", "video_uuid": f"uuid-{event_id}", "instance_domain": "v.example", "canonical_url": f"https://v.example/w/{event_id}", "source_instance": "src.example", "published_at": 1_700_000_000_000, "raw_payload_json": '{"k": "v"}', "ingested_at": ingested_at, **columns}
    conn.execute(f"INSERT INTO interaction_raw_events ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})", list(row.values()))
    conn.commit()


def _rows(conn: sqlite3.Connection) -> dict[str, dict]:
    return {row["event_id"]: dict(row) for row in conn.execute("SELECT * FROM interaction_raw_events")}


def _stripped(row: dict) -> dict:
    return {**row, **dict.fromkeys(STRIPPED)}


class _CountingLock:
    """A lock stand-in that records, at each release, how many stale rows a second connection sees fully stripped."""

    def __init__(self, db_path: Path, cutoff: int) -> None:
        self.entered = 0
        self.seen_at_release: list[int] = []
        self._reader = sqlite3.connect(db_path)
        self._cutoff = cutoff

    def __enter__(self) -> None:
        self.entered += 1

    def __exit__(self, *exc) -> bool:
        self.seen_at_release.append(self._reader.execute("SELECT COUNT(*) FROM interaction_raw_events WHERE ingested_at < ? AND raw_payload_json IS NULL AND actor_id IS NULL AND source_instance IS NULL", (self._cutoff,)).fetchone()[0])
        return False

    def close(self) -> None:
        self._reader.close()


def test_a_31_day_row_is_stripped_of_actor_and_payload_only_and_a_29_day_row_is_untouched(tmp_path):
    conn = _db(tmp_path)
    now = now_ms()
    _insert_raw(conn, "old", now - 31 * DAY_MS)
    _insert_raw(conn, "young", now - 29 * DAY_MS)
    before = _rows(conn)
    assert all(before["old"][column] is not None for column in STRIPPED)  # control: the old row holds all three

    assert interaction_events.prune_interaction_raw_events(conn, now_ms() - 30 * DAY_MS, 500) == 1
    after = _rows(conn)
    assert after["old"] == _stripped(before["old"])
    assert after["young"] == before["young"]
    assert conn.execute("SELECT COUNT(*) FROM interaction_raw_events").fetchone()[0] == 2


def test_the_cutoff_is_exclusive_and_a_row_holding_any_one_column_is_stripped(tmp_path):
    conn = _db(tmp_path)
    cutoff = 1_700_000_000_000
    _insert_raw(conn, "below", cutoff - 1)
    _insert_raw(conn, "at", cutoff)
    _insert_raw(conn, "actor-only", cutoff - DAY_MS, raw_payload_json=None, source_instance=None)
    _insert_raw(conn, "source-only", cutoff - DAY_MS, raw_payload_json=None, actor_id=None)
    _insert_raw(conn, "payload-only", cutoff - DAY_MS, actor_id=None, source_instance=None)
    before = _rows(conn)
    assert [[before[event_id][column] is not None for column in STRIPPED] for event_id in ("payload-only", "actor-only", "source-only")] == [[True, False, False], [False, True, False], [False, False, True]]  # control: each single-column row holds exactly its one column

    interaction_events.prune_interaction_raw_events(conn, cutoff, 500)

    assert _rows(conn) == {
        "below": _stripped(before["below"]),
        "at": before["at"],
        "actor-only": _stripped(before["actor-only"]),
        "source-only": _stripped(before["source-only"]),
        "payload-only": _stripped(before["payload-only"]),
    }


def test_five_stale_rows_are_stripped_two_per_committed_lock_hold(tmp_path):
    conn = _db(tmp_path)
    now = now_ms()
    for n in range(5):
        _insert_raw(conn, f"e{n}", now - 40 * DAY_MS + n)
    before = _rows(conn)
    cutoff = now - 30 * DAY_MS
    lock = _CountingLock(tmp_path / "engine.db", cutoff)

    try:
        assert interaction_events.prune_interaction_raw_events(conn, cutoff, 2, lock=lock) == 5
    finally:
        lock.close()
    assert lock.entered == 4
    assert lock.seen_at_release == [2, 4, 5, 5]  # each hold commits one chunk of at most 2 before it releases
    assert _rows(conn) == {event_id: _stripped(row) for event_id, row in before.items()}


def test_a_stripped_event_replayed_is_still_a_duplicate_and_moves_no_signal(tmp_path):
    conn = _db(tmp_path)
    event = {
        "event_id": "t-like-1",
        "event_type": "Like",
        "actor_id": "https://peer.example/accounts/alice",
        "object": {"video_uuid": "uuid-1", "instance_domain": "v.example"},
        "published_at": 1_700_000_000_000,
        "source_instance": "peer.example",
        "raw_payload": {"k": "v"},
    }
    assert ingest_interaction_event(conn, event)["duplicate"] is False  # control: the first ingest lands
    assert all(_rows(conn)["t-like-1"][column] is not None for column in STRIPPED)  # control: the ingest stored all three
    conn.execute("UPDATE interaction_raw_events SET ingested_at = ingested_at - ? WHERE event_id = ?", (31 * DAY_MS, "t-like-1"))
    conn.commit()
    assert interaction_events.prune_interaction_raw_events(conn, now_ms() - 30 * DAY_MS, 500) == 1
    stripped = _rows(conn)
    assert [stripped["t-like-1"][column] for column in STRIPPED] == [None, None, None]
    signals = [dict(row) for row in conn.execute("SELECT * FROM interaction_signals")]
    assert [row["likes_count"] for row in signals] == [1]  # control: the first ingest counted once

    assert ingest_interaction_event(conn, event)["duplicate"] is True
    assert [dict(row) for row in conn.execute("SELECT * FROM interaction_signals")] == signals
    assert _rows(conn) == stripped  # the replay restores neither actor nor payload


def test_the_schema_creates_the_unstripped_index_and_the_prune_finds_its_rows_through_it(tmp_path):
    conn = _db(tmp_path)
    assert UNSTRIPPED_INDEX in [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'interaction_raw_events'")]  # the schema, not the prune, creates the index
    _insert_raw(conn, "old", now_ms() - 31 * DAY_MS)
    statements: list[str] = []
    conn.set_trace_callback(statements.append)
    interaction_events.prune_interaction_raw_events(conn, now_ms() - 30 * DAY_MS, 500)
    conn.set_trace_callback(None)
    pruning = [sql for sql in statements if "interaction_raw_events" in sql]
    assert pruning  # control: the prune ran at least one statement against the table

    # The trace hands back the statement with its parameters expanded (observed); any `?` it still carried would be bound to NULL, which EXPLAIN never evaluates.
    plans = [" | ".join(row[3] for row in conn.execute(f"EXPLAIN QUERY PLAN {sql}", (None,) * sql.count("?"))) for sql in pruning]
    # SQLite uses a partial index only when the query repeats its WHERE term, so a drift between the two shows here as a scan.
    assert any(UNSTRIPPED_INDEX in plan for plan in plans), plans
