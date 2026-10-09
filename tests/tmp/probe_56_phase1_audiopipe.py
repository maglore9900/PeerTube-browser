"""Probe: the edited worker imports, and AudioPipe parks at limit then drains to done with a fake ffmpeg and a no-op download."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))
from test_translate_worker import _worker  # noqa: E402


def test_probe(monkeypatch):
    worker = _worker()
    monkeypatch.setattr(worker, "stream_media", lambda *args: None)
    monkeypatch.setattr(worker, "FFMPEG_ARGS", [sys.executable, "-c", "import sys; sys.stdout.buffer.write(bytes(100000))"])
    monkeypatch.setattr(worker, "LOOKAHEAD_SECONDS", 1)
    pipe = worker.AudioPipe("https://media.example/x", "media.example", 1000)
    try:
        time.sleep(1.0)
        with pipe.cond:
            print("parked", len(pipe.pcm), pipe.done, pipe.limit)
        pos = 0
        while True:
            available, done = pipe.wait_samples(pos + 1000)
            pipe.slice(pos, available)
            pipe.release(available)
            pos = available
            if done and available == pos:
                break
        print("end", pos, done, pipe.error)
    finally:
        pipe.close()
    print("closed")
