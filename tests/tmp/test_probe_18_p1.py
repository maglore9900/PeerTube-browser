"""Self-check: the phase 1 checkpoint against the planned implementation (green) and against mutants (red)."""
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "client" / "backend"))
sys.path.insert(0, str(ROOT / "tests" / "tmp"))

import lib.users_store as users_store  # noqa: E402
import test_18_about_outbound_click_tracking_phase1 as checkpoint  # noqa: E402

DDL = """
CREATE TABLE IF NOT EXISTS analytics_events (
  id INTEGER PRIMARY KEY,
  type TEXT NOT NULL CHECK (type IN ('outbound_click', 'page_view')),
  track_id TEXT,
  href TEXT,
  page_path TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  user_agent TEXT,
  referer TEXT
);
CREATE INDEX IF NOT EXISTS analytics_events_type_track_created_idx
  ON analytics_events (type, track_id, created_at);
"""
INSERT = "INSERT INTO analytics_events (type, track_id, href, page_path, created_at, user_agent, referer) VALUES (?, ?, ?, ?, ?, ?, ?)"
original = users_store.ensure_user_schema


def schema(ddl):
    def ensure(conn):
        original(conn)
        conn.executescript(ddl)
    return ensure


def planned_insert(conn, *values):
    conn.execute(INSERT, values)


def committing_insert(conn, *values):
    conn.execute(INSERT, values)
    conn.commit()


def swapped_insert(conn, t, track, href, path, created, ua, ref):
    conn.execute(INSERT, (t, track, href, path, created, ref, ua))


MUTANT_SCHEMAS = {
    "ip_hash": DDL.replace("referer TEXT\n", "referer TEXT,\n  ip_hash TEXT\n"),
    "no_check": DDL.replace(" CHECK (type IN ('outbound_click', 'page_view'))", ""),
    "no_index": DDL.split("CREATE INDEX")[0],
    "drop_recreate": "DROP TABLE IF EXISTS analytics_events;" + DDL,
    "nullable_path": DDL.replace("page_path TEXT NOT NULL", "page_path TEXT"),
}


def test_planned_green(tmp_path, monkeypatch):
    monkeypatch.setattr(users_store, "ensure_user_schema", schema(DDL))
    monkeypatch.setattr(users_store, "insert_analytics_event", planned_insert, raising=False)
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    checkpoint.test_ensure_user_schema_creates_settled_analytics_events_idempotently(tmp_path / "a")
    checkpoint.test_insert_analytics_event_writes_one_row_in_callers_transaction(tmp_path / "b")


@pytest.mark.parametrize("name", sorted(MUTANT_SCHEMAS))
def test_schema_mutant_red(tmp_path, monkeypatch, name):
    monkeypatch.setattr(users_store, "ensure_user_schema", schema(MUTANT_SCHEMAS[name]))
    with pytest.raises((AssertionError, pytest.fail.Exception)) as info:
        checkpoint.test_ensure_user_schema_creates_settled_analytics_events_idempotently(tmp_path)
    print(name, "->", str(info.value).splitlines()[0])


@pytest.mark.parametrize("insert", [committing_insert, swapped_insert], ids=["commits", "swapped"])
def test_insert_mutant_red(tmp_path, monkeypatch, insert):
    monkeypatch.setattr(users_store, "ensure_user_schema", schema(DDL))
    monkeypatch.setattr(users_store, "insert_analytics_event", insert, raising=False)
    with pytest.raises(AssertionError) as info:
        checkpoint.test_insert_analytics_event_writes_one_row_in_callers_transaction(tmp_path)
    print(insert.__name__, "->", str(info.value).splitlines()[0])
