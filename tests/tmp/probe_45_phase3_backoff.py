import sys
import threading
import time
from argparse import Namespace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))

from test_translate_worker import HOST, MAX_DURATION, QUEUED_AT, StubRunner, clip, rig  # noqa: E402,F401

from data.subtitles import enqueue_translate_job  # noqa: E402


def test_probe_today_c2(rig, monkeypatch):
    monkeypatch.setattr(rig.worker, "POLL_SECONDS", 0.05)
    monkeypatch.setattr(rig.worker, "TRANSIENT_BACKOFF_SECONDS", 1.5)
    real = rig.worker.resolve_video
    calls = []

    def spy(*a):
        calls.append(time.monotonic())
        return real(*a)

    monkeypatch.setattr(rig.worker, "resolve_video", spy)
    rig.whitelist.unlink()
    enqueue_translate_job(rig.conn, "v-1", HOST, "en", 50, QUEUED_AT)
    args = Namespace(whitelist_db=rig.whitelist, max_duration=MAX_DURATION, max_bytes=len(rig.clip), max_chunk_seconds=1)
    stop = threading.Event()
    progress = {"at": time.monotonic()}
    thread = threading.Thread(target=rig.worker.serve, args=(rig.conn, args, StubRunner(rig), stop, progress), daemon=True)
    thread.start()
    while len(calls) < 2:
        time.sleep(0.01)
    while rig.row().get("state") != "queued":
        time.sleep(0.01)
    seen = time.monotonic()
    ages, values = [], set()
    end = seen + 0.25
    while time.monotonic() < end:
        values.add(progress["at"])
        ages.append(time.monotonic() - progress["at"])
        time.sleep(0.01)
    stop_at = time.monotonic()
    left = calls[1] + 1.5 - stop_at
    stop.set()
    thread.join(5)
    elapsed = time.monotonic() - stop_at
    print("PROBE seen_after_lookup", seen - calls[1], "max_age", max(ages), "min_age", min(ages), "distinct", len(values), "left", left, "elapsed", elapsed, "alive", thread.is_alive(), "calls", len(calls), "row", rig.row()["state"], rig.row()["attempts"])
    assert False


def test_probe_sliced_refresh_jitter():
    progress = {"at": time.monotonic()}
    stop = threading.Event()

    def loop():
        while not stop.is_set():
            progress["at"] = time.monotonic()
            time.sleep(0.05)

    worst = []
    for _ in range(20):
        stop.clear()
        t = threading.Thread(target=loop, daemon=True)
        t.start()
        time.sleep(0.02)
        ages, values = [], set()
        end = time.monotonic() + 0.25
        while time.monotonic() < end:
            values.add(progress["at"])
            ages.append(time.monotonic() - progress["at"])
            time.sleep(0.01)
        stop.set()
        t.join()
        worst.append((max(ages), len(values)))
    print("PROBE jitter max_age", max(w[0] for w in worst), "distinct min", min(w[1] for w in worst), "distinct max", max(w[1] for w in worst))
    assert False
