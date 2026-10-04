"""Triage probe for issue 45: a claim whose whitelist.db stays locked past the busy timeout ends failed, and the key can never be queued again."""
import argparse
import sqlite3
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))

from test_translate_worker import HOST, JOB_VIDEOS, _subtitles, _whitelist, _worker  # noqa: E402
from data.subtitles import claim_translate_job, enqueue_translate_job  # noqa: E402


def test_locked_whitelist_at_claim_fails_the_job_for_good(tmp_path):
    worker = _worker()
    whitelist = tmp_path / "whitelist.db"
    _whitelist(whitelist, JOB_VIDEOS, deny=True)
    subs = _subtitles(tmp_path / "subtitles.db")
    assert enqueue_translate_job(subs, "v-1", HOST, "en", 50, 1000) == ("queued", "queued")
    job = claim_translate_job(subs, "en", 2000)

    holder = sqlite3.connect(whitelist, isolation_level=None)
    holder.execute("BEGIN EXCLUSIVE")
    try:
        args = argparse.Namespace(whitelist_db=whitelist, max_duration=3600, max_bytes=1 << 30, max_chunk_seconds=30)
        worker.run_job(subs, job, args, runner=None, stop=threading.Event(), progress={"at": 0.0})
    finally:
        holder.execute("ROLLBACK")
        holder.close()

    state, error, attempts = subs.execute("SELECT state, error, attempts FROM subtitles WHERE video_id = 'v-1'").fetchone()
    print("after claim under lock:", state, repr(error), "attempts", attempts)
    print("re-enqueue once unlocked:", enqueue_translate_job(subs, "v-1", HOST, "en", 50, 3000))
    assert state == "failed" and error.startswith("OperationalError: database is locked")
    assert enqueue_translate_job(subs, "v-1", HOST, "en", 50, 4000) == ("exists", "failed")
