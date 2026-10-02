"""users.db's analytics_events table from ensure_user_schema, and insert_analytics_event writing one row inside the caller's transaction.

- After ensure_user_schema, analytics_events has exactly the eight settled columns with their types, NOT NULLs and primary key; its CHECK refuses an unknown type; it is indexed on (type, track_id, created_at); a second ensure_user_schema keeps the table and its rows.
- An insert_analytics_event whose `with conn:` block raises leaves nothing; one inside a `with conn:` that completes leaves exactly one row with the passed values, read through a second connection.

Called directly on a tmp users.db; no server is involved.
"""
from __future__ import annotations

import sqlite3
import sys
from contextlib import closing
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT / "client" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import lib.users_store as users_store  # noqa: E402

COLUMNS = ["id", "type", "track_id", "href", "page_path", "created_at", "user_agent", "referer"]
# (name, declared type, notnull, pk) as PRAGMA table_info reports the settled DDL.
COLUMN_DEFS = [("id", "INTEGER", 0, 1), ("type", "TEXT", 1, 0), ("track_id", "TEXT", 0, 0), ("href", "TEXT", 0, 0), ("page_path", "TEXT", 1, 0), ("created_at", "INTEGER", 1, 0), ("user_agent", "TEXT", 0, 0), ("referer", "TEXT", 0, 0)]
STORED = "SELECT type, track_id, href, page_path, created_at, user_agent, referer FROM analytics_events ORDER BY id"


def _index_columns(conn: sqlite3.Connection) -> list[list[str]]:
    """Each index on analytics_events as its ordered column names; the index name is not part of the contract."""
    return [[info[2] for info in conn.execute(f"PRAGMA index_info({index[1]})")] for index in conn.execute("PRAGMA index_list(analytics_events)")]


def test_ensure_user_schema_creates_settled_analytics_events_idempotently(tmp_path: Path) -> None:
    """ensure_user_schema, run twice, leaves analytics_events with exactly id, type, track_id, href, page_path, created_at, user_agent, referer (types, NOT NULLs and pk as settled) and an index on (type, track_id, created_at); a third run keeps a row written before it; the CHECK refuses an unknown type."""
    db = tmp_path / "users.db"
    with closing(sqlite3.connect(db)) as conn:
        users_store.ensure_user_schema(conn)
        users_store.ensure_user_schema(conn)

        assert [row[1] for row in conn.execute("PRAGMA table_info(analytics_events)")] == COLUMNS  # C1: exactly the eight settled columns, so no address-derived one
        assert [(row[1], row[2], row[3], row[5]) for row in conn.execute("PRAGMA table_info(analytics_events)")] == COLUMN_DEFS  # C1: each settled column as declared
        assert _index_columns(conn) == [["type", "track_id", "created_at"]]  # C1: the settled index, and only it

        with conn:
            conn.execute("INSERT INTO analytics_events (type, track_id, href, page_path, created_at, user_agent, referer) VALUES ('page_view', NULL, NULL, '/about', 1, NULL, NULL)")
        users_store.ensure_user_schema(conn)
        with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
            with conn:
                conn.execute("INSERT INTO analytics_events (type, page_path, created_at) VALUES ('click', '/about', 2)")  # C1: the CHECK refuses a type outside the two
        assert conn.execute(STORED).fetchall() == [("page_view", None, None, "/about", 1, None, None)]  # C1: the third run neither dropped the table nor its row, and the refused insert left none


def test_insert_analytics_event_writes_one_row_in_callers_transaction(tmp_path: Path) -> None:
    """insert_analytics_event inside a `with conn:` that raises leaves no row; inside one that completes it leaves exactly one row with the passed values, read through a second connection."""
    db = tmp_path / "users.db"
    with closing(sqlite3.connect(db)) as conn:
        users_store.ensure_user_schema(conn)
        with pytest.raises(RuntimeError, match="abort"):
            with conn:
                users_store.insert_analytics_event(conn, "page_view", None, None, "/rolled-back", 1, None, None)
                raise RuntimeError("abort")
        with closing(sqlite3.connect(db)) as reader:
            assert reader.execute(STORED).fetchall() == []  # C2: the insert is the caller's transaction, so a rollback takes it back

        with conn:
            users_store.insert_analytics_event(conn, "outbound_click", "about_patreon", "https://www.patreon.com/x", "/about.html", 1767225600123, "Mozilla/5.0 analytics-test", "https://example.org/about")

    with closing(sqlite3.connect(db)) as reader:
        assert reader.execute(STORED).fetchall() == [("outbound_click", "about_patreon", "https://www.patreon.com/x", "/about.html", 1767225600123, "Mozilla/5.0 analytics-test", "https://example.org/about")]  # C2: exactly one committed row, each value in its own column
