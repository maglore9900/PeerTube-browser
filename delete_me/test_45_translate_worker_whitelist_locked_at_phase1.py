"""Issue 45, phase 1 checkpoint: `run_job` called on a job claimed through test_translate_worker.py's `Rig` (`rig.claim()`, the rig's args and a `StubRunner`), whose claim-time `resolve_video` hits a broken whitelist.db.

- Locked or unopenable (a deleted file, a file held under `BEGIN EXCLUSIVE` past the 30 s busy timeout): the row is back to queued with attempts 0, queued_at 1000, no error and no finished_at; neither host saw a request; exactly one WARNING names `[translate-worker]`, the key and the error text, nothing is logged at ERROR; `run_job` returns True.
- Any other OperationalError (a videos table with its video_uuid column dropped, a zero-byte file read as an empty database): the row ends failed with `OperationalError: <text>`, exactly one ERROR record carries the exception, no WARNING; `run_job` returns False.
- Control: the same rig with whitelist.db intact reaches both hosts, so the empty request lists above are the break's doing.
"""
from __future__ import annotations

import logging
import sqlite3
import sys
import threading
import time
from argparse import Namespace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))

from test_translate_worker import HOST, INSTANCE_THEN_JSON, MAX_DURATION, MEDIA_URL, QUEUED_AT, StubRunner, clip, rig  # noqa: E402,F401

# (how whitelist.db is broken, the OperationalError text it raises); texts probed through run_job on this rig.
REQUEUED = {
    "missing file": ("delete", "unable to open database file"),
    "held EXCLUSIVE lock": ("hold", "database is locked"),
}
FAILED = {
    "videos without video_uuid": ("drop column", "no such column: v.video_uuid"),
    "zero-byte file": ("truncate", "no such table: videos"),
}


def _break_whitelist(rig, how: str) -> sqlite3.Connection | None:
    """Break the rig's whitelist.db as `how` says; the holding connection when it is held, for the caller to close."""
    if how == "drop column":
        conn = sqlite3.connect(rig.whitelist)
        conn.execute("ALTER TABLE videos DROP COLUMN video_uuid")
        conn.commit()
        conn.close()
    elif how == "delete":
        rig.whitelist.unlink()
    elif how == "truncate":
        rig.whitelist.write_bytes(b"")
    else:
        holder = sqlite3.connect(rig.whitelist, isolation_level=None)
        holder.execute("BEGIN EXCLUSIVE")
        return holder
    return None


def _run_job(rig) -> object:
    """`run_job` with Rig.run's args, called directly because Rig.run drops its return value."""
    args = Namespace(whitelist_db=rig.whitelist, max_duration=MAX_DURATION, max_bytes=len(rig.clip), max_chunk_seconds=1)
    return rig.worker.run_job(rig.conn, rig.job, args, StubRunner(rig), threading.Event(), {"at": time.monotonic()})


def _run_broken(rig, caplog: pytest.LogCaptureFixture, how: str) -> object:
    caplog.set_level(logging.INFO)
    rig.claim()
    holder = _break_whitelist(rig, how)
    try:
        return _run_job(rig)
    finally:
        if holder is not None:
            holder.close()


def _job(rig) -> tuple:
    row = rig.row()
    return row["state"], row["attempts"], row["queued_at"], row["error"], row["finished_at"]


def test_control_an_intact_whitelist_reaches_both_hosts(rig):
    rig.claim()
    _run_job(rig)
    assert rig.row()["state"] == "ready", rig.row()  # control: the job ran the whole path
    assert rig.instance.opened == INSTANCE_THEN_JSON and rig.media.opened == [MEDIA_URL]  # control: both recorders see requests on this rig


@pytest.mark.parametrize("case", REQUEUED.values(), ids=REQUEUED.keys())
def test_a_locked_or_unopenable_whitelist_at_claim_requeues_the_job_unspent_requests_nothing_logs_one_warning_and_returns_true(rig, caplog, case):
    how, text = case
    result = _run_broken(rig, caplog, how)

    assert _job(rig) == ("queued", 0, QUEUED_AT, None, None)  # C1: claim unspent, queued_at kept, no error, no finished_at
    warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert len(warnings) == 1, [record.getMessage() for record in warnings]  # C1: one warning, not none and not two
    message = warnings[0].getMessage()
    assert all(part in message for part in ("[translate-worker]", "v-1", HOST, text)), message  # C1: names the worker, the key and the error text
    assert [record.getMessage() for record in caplog.records if record.levelno >= logging.ERROR] == []  # C1: not routed through the catch-all
    assert rig.instance.opened == [] and rig.media.opened == []  # C1: nothing requested
    assert result is True  # C1


@pytest.mark.parametrize("case", FAILED.values(), ids=FAILED.keys())
def test_any_other_whitelist_error_at_claim_still_fails_the_job_through_the_logged_catch_all_and_returns_false(rig, caplog, case):
    how, text = case
    result = _run_broken(rig, caplog, how)

    row = rig.row()
    assert (row["state"], row["error"]) == ("failed", f"OperationalError: {text}"), row  # C2: today's failure, not requeued or rewrapped
    errors = [record for record in caplog.records if record.levelno >= logging.ERROR]
    assert len(errors) == 1 and errors[0].levelno == logging.ERROR, [record.getMessage() for record in errors]  # C2: one ERROR record
    assert errors[0].exc_info is not None and errors[0].exc_info[0] is sqlite3.OperationalError, errors[0].exc_info  # C2: the catch-all's logging.exception
    assert [record.getMessage() for record in caplog.records if record.levelno == logging.WARNING] == []  # C2: the requeue branch's warning did not fire
    assert result is False  # C2
