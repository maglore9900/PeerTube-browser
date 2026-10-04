import logging
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))

from test_translate_worker import StubRunner, clip, rig  # noqa: E402,F401


def _raising(exc):
    def resolve_video(*args, **kwargs):
        raise exc
    return resolve_video


@pytest.mark.parametrize("case", ["inj-locked", "missing", "held", "inj-column", "zero-byte"])
def test_probe(rig, caplog, monkeypatch, case):
    caplog.set_level(logging.INFO)
    rig.claim()
    holder = None
    if case == "inj-locked":
        monkeypatch.setattr(rig.worker, "resolve_video", _raising(sqlite3.OperationalError("database is locked")))
    elif case == "inj-column":
        monkeypatch.setattr(rig.worker, "resolve_video", _raising(sqlite3.OperationalError("no such column: video_uuid")))
    elif case == "missing":
        rig.whitelist.unlink()
    elif case == "zero-byte":
        rig.whitelist.write_bytes(b"")
    else:
        holder = sqlite3.connect(rig.whitelist, isolation_level=None)
        holder.execute("BEGIN EXCLUSIVE")
    try:
        result = rig.worker.run_job(rig.conn, rig.job, __import__("argparse").Namespace(whitelist_db=rig.whitelist, max_duration=5, max_bytes=len(rig.clip), max_chunk_seconds=1), StubRunner(rig), __import__("threading").Event(), {"at": 0.0})
    finally:
        if holder is not None:
            holder.close()
    row = rig.row()
    print("CASE", case, "RESULT", repr(result))
    print("ROW", {k: row[k] for k in ("state", "attempts", "queued_at", "error", "finished_at")})
    print("RIG.RUN returns", repr(rig.run.__annotations__.get("return")))
    for r in caplog.records:
        print("REC", r.levelname, repr(r.getMessage()), r.exc_info[0] if r.exc_info else None)
    print("OPENED", rig.instance.opened, rig.media.opened, rig.whitelist.exists())
    assert False
