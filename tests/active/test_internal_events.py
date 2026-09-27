"""A successful `/internal/events/ingest` strips raw events older than the server's `raw_retention_days`, at most once per `INTERACTION_RAW_PRUNE_INTERVAL_SECONDS`, and a strip that raises leaves its 200 body unchanged.

- The first ingest strips a 31-day row under a 30-day window and leaves the 29-day row and the posted events alone. A second ingest does not strip a newly stale row or move `last_raw_prune_at`, and neither does one with `last_raw_prune_at` 60 s short of an interval old. Once `last_raw_prune_at` is an interval and 1 s old, the next ingest strips it.
- With `raw_retention_days=7` on the server, one ingest strips an 8-day row and leaves a 6-day row as it was; with `raw_retention_days=9` it strips a 10-day row and leaves an 8-day one, so no single fixed window passes both.
- The Engine's own `SimilarServer`, built by the Engine's interpreter under `INTERACTION_RAW_RETENTION_DAYS=7`, and again under `=9`, carries that value as `raw_retention_days` and `None` as `last_raw_prune_at`, and its first ingest strips the row a day past the window and leaves the row a day inside it.
- When the real strip raises `OperationalError("interrupted")` because SQLite interrupts it, `IntegrityError` because a trigger aborts it, or `RuntimeError` because its lock raises, the ingest still answers 200 with the same body a clean ingest gives, and the posted event is committed.
- Under the Engine interpreter with `configure_engine_logging("verbose")` installed, the ingest reading one event through the real `read_json_body`, on a server whose `db_lock` raises `RuntimeError` or `sqlite3.OperationalError` on enter, sends exactly one 500 `{"error": "Event ingest failed"}` through the real `respond_json`, and stderr has an ERROR JSON line whose `traceback` ends with that exception.

Apart from the `SimilarServer` test, the handler runs against a stand-in server on a temporary database, with the HTTP body reader and responder patched; rows are aged by writing `ingested_at` directly. The strip itself is never replaced: it is only spied on, and its failures are armed on the database and the lock it is given.
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from conftest import ENGINE_PY, ROOT

SERVER_DIR = ROOT / "engine" / "server"
API_DIR = SERVER_DIR / "api"
# `data` imports `recommendations`, which lives under `api`, as the Engine's server.py runs it.
for path in (SERVER_DIR, API_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import server_config  # noqa: E402
from data import interaction_events  # noqa: E402
from data.interaction_events import ensure_interaction_event_schema  # noqa: E402
from data.time import now_ms  # noqa: E402
from handlers import internal_events  # noqa: E402

DAY_MS = 86_400_000
STRIPPED = ("raw_payload_json", "actor_id", "source_instance")
RETENTION_VAR = "INTERACTION_RAW_RETENTION_DAYS"
# Builds the real SimilarServer on the test's database, reports the two attributes it starts with, and posts one event through the real handler. pytest's own interpreter has no numpy, so it cannot import server.py (observed).
ENGINE_INGEST = r'''
import inspect, json, sqlite3, sys
from http.server import BaseHTTPRequestHandler
from unittest.mock import patch
import server
from handlers import internal_events
db_path, event = sys.argv[1], json.loads(sys.argv[2])
conn = sqlite3.connect(db_path)
args = dict.fromkeys(list(inspect.signature(server.SimilarServer.__init__).parameters)[3:])
srv = server.SimilarServer(("127.0.0.1", 0), BaseHTTPRequestHandler, **{**args, "db": conn})
try:
    started = {name: getattr(srv, name, "MISSING") for name in ("raw_retention_days", "last_raw_prune_at")}
    with patch.object(internal_events, "read_json_body", return_value={"events": [event]}), patch.object(internal_events, "respond_json") as respond:
        internal_events.handle_internal_events_ingest(object(), srv)
    _, status, payload = respond.call_args.args
    print(json.dumps({"server": started, "calls": respond.call_count, "status": status, "payload": payload}))
finally:
    srv.server_close()
'''


def _db(tmp_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(tmp_path / "engine.db")
    conn.row_factory = sqlite3.Row
    ensure_interaction_event_schema(conn)
    return conn


def _server(conn: sqlite3.Connection, **attrs) -> SimpleNamespace:
    # The two attributes the real SimilarServer starts with are checked by the SimilarServer test; the timestamp starts unset, as after an Engine start.
    return SimpleNamespace(db=conn, db_lock=threading.Lock(), last_raw_prune_at=None, **attrs)


def _insert_raw(conn: sqlite3.Connection, event_id: str, ingested_at: int) -> None:
    row = {"event_id": event_id, "event_type": "Like", "actor_id": "actor", "video_uuid": f"uuid-{event_id}", "instance_domain": "v.example", "canonical_url": f"https://v.example/w/{event_id}", "source_instance": "src.example", "published_at": 1_700_000_000_000, "raw_payload_json": '{"k": "v"}', "ingested_at": ingested_at}
    conn.execute(f"INSERT INTO interaction_raw_events ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})", list(row.values()))
    conn.commit()


def _rows(conn: sqlite3.Connection) -> dict[str, dict]:
    return {row["event_id"]: dict(row) for row in conn.execute("SELECT * FROM interaction_raw_events")}


def _stripped(row: dict) -> dict:
    return {**row, **dict.fromkeys(STRIPPED)}


def _stripped_ids(conn: sqlite3.Connection) -> set[str]:
    return {event_id for event_id, row in _rows(conn).items() if all(row[column] is None for column in STRIPPED)}


def _event(event_id: str) -> dict:
    return {"event_id": event_id, "event_type": "Like", "actor_id": "https://peer.example/accounts/alice", "object": {"video_uuid": f"uuid-{event_id}", "instance_domain": "v.example"}, "published_at": 1_700_000_000_000, "source_instance": "peer.example", "raw_payload": {"k": "v"}}


def _ok_body(event_id: str) -> dict:
    # The body a clean single-event ingest answers with (observed).
    return {"ok": True, "count": 1, "ingested": 1, "duplicates": 0, "results": [{"ok": True, "duplicate": False, "event_id": event_id, "event_type": "Like"}]}


def _post(server: SimpleNamespace, event_id: str) -> tuple[int, dict]:
    with (
        patch.object(internal_events, "read_json_body", return_value={"events": [_event(event_id)]}),
        patch.object(internal_events, "respond_json") as respond,
    ):
        internal_events.handle_internal_events_ingest(object(), server)
    respond.assert_called_once()  # one answer per request, not an error followed by a 200
    _, status, payload = respond.call_args.args
    return status, payload


def test_the_first_ingest_strips_and_the_next_strip_waits_until_the_last_one_is_an_interval_old(tmp_path):
    conn = _db(tmp_path)
    now = now_ms()
    _insert_raw(conn, "stale-1", now - 31 * DAY_MS)
    _insert_raw(conn, "young", now - 29 * DAY_MS)
    server = _server(conn, raw_retention_days=30)
    assert _stripped_ids(conn) == set()  # control: nothing starts stripped

    with patch.object(internal_events, "prune_interaction_raw_events", wraps=interaction_events.prune_interaction_raw_events) as prune:
        assert _post(server, "post-1") == (200, _ok_body("post-1"))  # control: the ingest itself succeeds
        assert prune.call_count == 1  # the first ingest strips
        assert _stripped_ids(conn) == {"stale-1"}  # the 31-day row, and neither the 29-day row nor the posted event
        first_run = server.last_raw_prune_at
        assert first_run is not None

        _insert_raw(conn, "stale-2", now - 31 * DAY_MS)
        assert _post(server, "post-2") == (200, _ok_body("post-2"))  # control
        assert prune.call_count == 1  # inside the interval, no second strip
        assert _stripped_ids(conn) == {"stale-1"}  # the newly stale row keeps its data
        assert server.last_raw_prune_at == first_run  # a skipped ingest does not restart the interval

        interval = server_config.INTERACTION_RAW_PRUNE_INTERVAL_SECONDS
        server.last_raw_prune_at = first_run - (interval - 60)
        assert _post(server, "post-3") == (200, _ok_body("post-3"))  # control
        assert prune.call_count == 1  # 60 s short of an interval is still inside it
        assert _stripped_ids(conn) == {"stale-1"}
        assert server.last_raw_prune_at == first_run - (interval - 60)

        server.last_raw_prune_at = first_run - (interval + 1)
        assert _post(server, "post-4") == (200, _ok_body("post-4"))  # control
        assert prune.call_count == 2  # an interval and 1 s old, the next ingest strips
        assert _stripped_ids(conn) == {"stale-1", "stale-2"}
        assert server.last_raw_prune_at >= first_run  # the strip claims a fresh slot


@pytest.mark.parametrize("days", [7, 9])
def test_the_strip_uses_the_servers_retention_days(tmp_path, days):
    conn = _db(tmp_path)
    now = now_ms()
    _insert_raw(conn, "stale", now - (days + 1) * DAY_MS)
    _insert_raw(conn, "young", now - (days - 1) * DAY_MS)
    before = _rows(conn)

    assert _post(_server(conn, raw_retention_days=days), "post-1") == (200, _ok_body("post-1"))  # control: the ingest itself succeeds

    after = _rows(conn)
    assert after["stale"] == _stripped(before["stale"])  # a day past the server's window
    assert after["young"] == before["young"]  # a day inside it; any one fixed window strips the 8-day row in both cases or in neither, so it fails one of them


@pytest.mark.parametrize("days", [7, 9])
def test_the_engines_server_carries_the_env_retention_days_and_an_unset_last_strip(tmp_path, days):
    conn = _db(tmp_path)
    now = now_ms()
    _insert_raw(conn, "stale", now - (days + 1) * DAY_MS)
    _insert_raw(conn, "young", now - (days - 1) * DAY_MS)
    before = _rows(conn)
    # The value goes only into the child's env: this process has already imported `server_config`.
    env = {**{key: val for key, val in os.environ.items() if key != RETENTION_VAR}, RETENTION_VAR: str(days)}

    run = subprocess.run([str(ENGINE_PY), "-c", ENGINE_INGEST, str(tmp_path / "engine.db"), json.dumps(_event("post-1"))], cwd=API_DIR, env=env, capture_output=True, text=True, timeout=120)

    assert run.returncode == 0, run.stderr[-2000:]  # control: the Engine's interpreter built the server and ran the handler
    report = json.loads(run.stdout)
    assert (report["calls"], report["status"], report["payload"]) == (1, 200, _ok_body("post-1"))  # control: the ingest itself succeeds
    assert report["server"] == {"raw_retention_days": days, "last_raw_prune_at": None}  # the real server carries the configured window and no previous strip
    after = _rows(conn)
    assert after["stale"] == _stripped(before["stale"])  # its first ingest strips a day past the window
    assert after["young"] == before["young"]  # and leaves a day inside it


class _LockFailingInsideTheStrip:
    """A db_lock that works for the ingest and raises RuntimeError when the strip enters it."""

    def __init__(self) -> None:
        self._lock = threading.Lock()

    def __enter__(self):
        if sys._getframe(1).f_code.co_name == "prune_interaction_raw_events":
            raise RuntimeError("strip failed")
        return self._lock.__enter__()

    def __exit__(self, *exc_info):
        return self._lock.__exit__(*exc_info)


def _interrupt_the_strip(conn: sqlite3.Connection):
    # sqlite3_interrupt is what the Engine's statement deadline trips; the strip's UPDATE fires the trigger, the ingest's INSERT does not.
    conn.create_function("interrupt_strip", 0, lambda: conn.interrupt())
    conn.execute("CREATE TRIGGER strip_fails BEFORE UPDATE ON interaction_raw_events BEGIN SELECT interrupt_strip(); END")
    conn.commit()
    return threading.Lock()


def _abort_the_strip(conn: sqlite3.Connection):
    conn.execute("CREATE TRIGGER strip_fails BEFORE UPDATE ON interaction_raw_events BEGIN SELECT RAISE(ABORT, 'strip failed'); END")
    conn.commit()
    return threading.Lock()


def _fail_the_strips_lock(conn: sqlite3.Connection):
    return _LockFailingInsideTheStrip()


@pytest.mark.parametrize("arm, raised", [(_interrupt_the_strip, "OperationalError('interrupted')"), (_abort_the_strip, "IntegrityError('strip failed')"), (_fail_the_strips_lock, "RuntimeError('strip failed')")], ids=["interrupted", "integrity-error", "runtime-error"])
def test_a_strip_that_raises_leaves_the_200_body_unchanged(tmp_path, arm, raised):
    conn = _db(tmp_path)
    _insert_raw(conn, "stale", now_ms() - 31 * DAY_MS)
    server = _server(conn, raw_retention_days=30)
    server.db_lock = arm(conn)
    seen = []

    def _recording_strip(*args, **kwargs):
        # The real strip, with what it raised kept so each case shows the failure it arms (reprs observed).
        try:
            return interaction_events.prune_interaction_raw_events(*args, **kwargs)
        except Exception as exc:
            seen.append(repr(exc))
            raise

    with patch.object(internal_events, "prune_interaction_raw_events", side_effect=_recording_strip) as prune:
        status, payload = _post(server, "post-1")

    assert (status, payload) == (200, _ok_body("post-1"))  # exactly the keys ok, count, ingested, duplicates, results, with a clean ingest's values
    assert prune.call_count == 1  # the strip was due and ran
    assert seen == [raised]  # and raised the failure this case arms
    assert _stripped_ids(conn) == set()  # before stripping the stale row, so the body above is the one a failed strip leaves
    reader = sqlite3.connect(tmp_path / "engine.db")
    try:
        assert sorted(row[0] for row in reader.execute("SELECT event_id FROM interaction_raw_events")) == ["post-1", "stale"]  # the posted event is committed, seen from another connection
    finally:
        reader.close()


TRACEBACK_HEAD = "Traceback (most recent call last):"
INGEST_FAILED = ([500], {"error": "Event ingest failed"})
# Two unrelated failure types, so a fixed body cannot come from special-casing one of them.
INGEST_FAILURES = (("RuntimeError", "sentinel-ingest-5d7e", "RuntimeError"), ("OperationalError", "sentinel-ingest-9c21", "sqlite3.OperationalError"))
# Runs under the Engine interpreter with the production logging installed; only the transport (statuses and bytes written) and the DB lock are doubled, and read_json_body and respond_json run for real.
_FAILING_INGEST_CHILD = r'''
import io, json, sqlite3, sys, types
sys.path[:0] = [sys.argv[1], sys.argv[2]]
from logging_profiles import configure_engine_logging
configure_engine_logging("verbose")
from handlers import internal_events

ERRORS = {"RuntimeError": RuntimeError, "OperationalError": sqlite3.OperationalError}

class Wire:
    def __init__(self, body):
        self.statuses = []
        self.headers = {"content-length": str(len(body))}
        self.rfile = io.BytesIO(body)
        self.wfile = io.BytesIO()

    def send_response(self, status):
        self.statuses.append(status)

    def send_header(self, name, value):
        pass

    def end_headers(self):
        pass

# Stands in for the DB lock guarding the chunk's writes; failing on enter is a failure no event validation raises.
class RaisingLock:
    entered = 0

    def __enter__(self):
        RaisingLock.entered += 1
        raise ERRORS[sys.argv[3]](sys.argv[4])

    def __exit__(self, *exc):
        return False

handler = Wire(json.dumps({"events": [{"event_id": "x"}]}).encode("utf-8"))
internal_events.handle_internal_events_ingest(handler, types.SimpleNamespace(db=None, db_lock=RaisingLock()))
print(json.dumps({"entered": RaisingLock.entered, "statuses": handler.statuses, "body": handler.wfile.getvalue().decode("utf-8")}))
'''


def test_ingest_failure_answers_a_fixed_500_and_logs_its_traceback():
    assert ENGINE_PY.exists(), f"Engine interpreter missing at {ENGINE_PY}; run `pixi install` in engine/"
    for kind, text, raised in INGEST_FAILURES:
        run = subprocess.run([str(ENGINE_PY), "-c", _FAILING_INGEST_CHILD, str(SERVER_DIR), str(API_DIR), kind, text], cwd=API_DIR, capture_output=True, text=True, timeout=120)
        assert run.returncode == 0, run.stderr[-2000:]  # control: the Engine's interpreter imported the handler and ran the case
        report = json.loads(run.stdout)
        # Every line must be a JSON object: plain-text lines would mean logging.lastResort wrote them, not the production formatter.
        lines = [json.loads(line) for line in run.stderr.splitlines()]
        assert all(isinstance(line, dict) for line in lines), run.stderr[-2000:]

        assert report["entered"] == 1, kind  # control: the event passed validation and the failure came from the chunk's lock
        assert (report["statuses"], json.loads(report["body"])) == INGEST_FAILED, kind  # one answer, fixed text, no exception text
        tracebacks = [line["traceback"] for line in lines if line.get("level") == "ERROR" and "traceback" in line]
        assert any(tb.startswith(TRACEBACK_HEAD) and tb.rstrip().endswith(f"{raised}: {text}") for tb in tracebacks), lines
