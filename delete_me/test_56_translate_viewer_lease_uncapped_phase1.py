"""Plan 56 phase 1 checkpoint: the translate worker has no duration or media-size cap, and `AudioPipe` buffers at most `limit` samples.

Uncapped (`run_job` through the `Rig` harness of tests/active/test_translate_worker.py: scripted instance and media hosts behind `data.source_fetch.build_opener`, a StubRunner, tmp subtitles.db and whitelist.db, the real ffmpeg decoding the 4 s clip): a video JSON with no `duration`, a JSON duration of 7754 s, a stored whitelist.db duration of 7754 s (JSON 4 s), and a media response declaring a 2 GiB Content-Length each end ready/whisper with the clip's four cues, after the media URL is fetched.

Bounded buffer (`AudioPipe(url, host, max_chunk)` built directly, the real `stream_media` downloading a 256000-byte patterned body from the scripted media host behind `data.source_fetch.build_opener`, `FFMPEG_ARGS` a Python script copying all of stdin to stdout in one write, `LOOKAHEAD_SECONDS` 1, an 8000-sample window, so `limit` is 24000 samples, 48000 bytes): `len(pcm)` read under `cond` never exceeds 48000 bytes while filling; with no release `done` stays False and the buffer stays at exactly 48000 bytes; after `release(8000)` the absolute count `wait_samples` reports grows past the 24000 it reported before and settles at 32000 with the buffer back at 48000 bytes; slicing and releasing all that is buffered until the end leaves `done` True, no error, all 128000 samples counted, and every byte of the body from sample 8000 on delivered in order.
"""
from __future__ import annotations

import importlib
import json
import sqlite3
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))
from test_translate_worker import MEDIA_HOST, MEDIA_URL, ScriptedHost, StubRunner, VIDEO_URL, _dispatching_opener, _worker, clip, rig  # noqa: E402,F401

# The stub runner's segments for the clip's two speech seconds, offset to absolute ms and sorted (probed: the ready row of a JSON-4 s run on this rig).
CLIP_CUES = [{"start": 0.123, "end": 0.568, "text": "call 1 a"}, {"start": 0.6, "end": 0.9, "text": "call 1 b"}, {"start": 2.123, "end": 2.568, "text": "call 2 a"}, {"start": 2.6, "end": 2.9, "text": "call 2 b"}]
# The operator's 2026-10-06 refused video; above the 5 s the rig passed, the 600 s and the 3600 s SUBTITLE_MAX_DURATION.
LONG_SECONDS = 7754
# Above the removed SUBTITLE_MAX_BYTES (1 GiB) and the clip-sized max_bytes the rig passed; the scripted host serves the clip whatever the header says (probed: ready under max_bytes 1e12).
HUGE_LENGTH = 2 * 1024 ** 3

# (JSON duration, None leaving the key out; stored whitelist.db duration; declared media Content-Length, None for the clip's own). Probed on the capped worker: the three duration cases end failed `video duration unknown`, `duration 7754s over 5s`, `duration 7754s over 5s`.
UNCAPPED = {
    "JSON without duration": (None, None, None),
    "JSON duration far over the old cap": (LONG_SECONDS, None, None),
    # JSON 4 s passes any JSON check, so only a surviving stored-duration branch could refuse it.
    "stored duration far over the old cap": (4, LONG_SECONDS, None),
    "declared media size over the old cap": (4, None, HUGE_LENGTH),
}

# AudioPipe: LOOKAHEAD_SECONDS 1 at 16 kHz plus a half-second window; unequal, so a limit of twice the lookahead or of the lookahead alone (32000, 16000) reads differently.
LOOKAHEAD_SECONDS = 1
WINDOW_SAMPLES = 8_000
LIMIT_SAMPLES = 24_000
LIMIT_BYTES = 48_000
BYTES_PER_SAMPLE = 2
# Over five limits, patterned so a dropped, repeated or reordered stretch shows; the fake ffmpeg writes it in one call, so the pipe holds 65536 bytes at once and one unclamped read1(65536) overshoots LIMIT_BYTES (probed: 65536).
MEDIA_BODY = bytes(range(256)) * 1000
DECODED_SAMPLES = 128_000
RELEASED_TO = 8_000
FAKE_FFMPEG = "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read()); sys.stdout.buffer.flush()"
QUIET_SECONDS = 0.5
FILL_SECONDS = 10.0
PARKED_SECONDS = 1.0
DRAIN_SECONDS = 20.0
CLOSE_SECONDS = 10.0


def _video(duration: int | None) -> bytes:
    """The instance's video JSON with the rig's one media file; duration None leaves the key out."""
    video: dict = {"uuid": "u-1", "files": [{"fileUrl": MEDIA_URL, "size": 4096}], "streamingPlaylists": []}
    if duration is not None:
        video["duration"] = duration
    return json.dumps(video).encode("utf-8")


@pytest.mark.parametrize("case", UNCAPPED.values(), ids=UNCAPPED.keys())
def test_a_video_with_no_duration_a_long_json_or_stored_duration_or_a_huge_declared_size_translates_to_ready(rig, case):
    """Each input a capped worker refused ends ready/whisper with the clip's four cues, its media fetched."""
    json_duration, stored_duration, declared_length = case
    rig.instance.serve(VIDEO_URL, body=_video(json_duration))
    if stored_duration is not None:
        conn = sqlite3.connect(rig.whitelist)
        conn.execute("UPDATE videos SET duration = ? WHERE video_id = 'v-1'", (stored_duration,))
        conn.commit()
        conn.close()
    if declared_length is not None:
        rig.media.serve(MEDIA_URL, headers={"Content-Length": str(declared_length)}, body=rig.clip)

    rig.run(StubRunner(rig))

    row = rig.row()
    assert (row["state"], row["source"], row["error"]) == ("ready", "whisper", None), row  # C1: not failed on an unknown or long duration, or on the declared size
    assert json.loads(row["cues_json"]) == CLIP_CUES  # C1: the clip's cues, so the audio was decoded and transcribed
    assert rig.media.opened == [MEDIA_URL]  # C1: the media was requested, not refused before the download


def _buffered(pipe) -> tuple[int, bool]:
    """len(pcm) in bytes and done, read together under the pipe's condition."""
    with pipe.cond:
        return len(pipe.pcm), pipe.done


def _settle(pipe) -> tuple[int, int, bool]:
    """Sample the buffer every 5 ms until it is non-empty and unchanged for QUIET_SECONDS, or done; (largest length seen, length then, done then)."""
    deadline = time.monotonic() + FILL_SECONDS
    largest, last, quiet_since = 0, -1, time.monotonic()
    while time.monotonic() < deadline:
        length, done = _buffered(pipe)
        largest = max(largest, length)
        if done:
            return largest, length, done
        if length != last:
            last, quiet_since = length, time.monotonic()
        elif length > 0 and time.monotonic() - quiet_since >= QUIET_SECONDS:
            return largest, length, done
        time.sleep(0.005)
    pytest.fail(f"the reader never settled within {FILL_SECONDS} s: largest {largest}, last {last}")


def _close(pipe) -> None:
    """pipe.close() on a daemon thread, so a reader parked past close fails this test instead of hanging the session."""
    closer = threading.Thread(target=pipe.close, daemon=True)
    closer.start()
    closer.join(CLOSE_SECONDS)
    if closer.is_alive():
        pytest.fail(f"AudioPipe.close did not return within {CLOSE_SECONDS} s")


def test_audio_pipe_never_buffers_past_its_limit_parks_until_release_frees_room_and_still_ends_at_eof(monkeypatch):
    """With a download and decoder passing four limits of audio, the buffer never exceeds limit, stays full and not done without a release, refills past the old absolute count after release, and reaches done with every sample, in order, once released to the end."""
    worker = _worker()
    media = ScriptedHost()
    media.serve(MEDIA_URL, body=MEDIA_BODY)
    monkeypatch.setattr(importlib.import_module("data.source_fetch"), "build_opener", _dispatching_opener(ScriptedHost(), media))
    monkeypatch.setattr(worker, "FFMPEG_ARGS", [sys.executable, "-c", FAKE_FFMPEG])
    monkeypatch.setattr(worker, "LOOKAHEAD_SECONDS", LOOKAHEAD_SECONDS)

    pipe = worker.AudioPipe(MEDIA_URL, MEDIA_HOST, WINDOW_SAMPLES)
    try:
        assert pipe.limit == LIMIT_SAMPLES  # C2 control: the lookahead plus the window, so the download carries over five limits
        largest, length, done = _settle(pipe)
        assert largest <= LIMIT_BYTES, largest  # C2: never more than limit samples buffered, not even by one read chunk
        assert (length, done) == (LIMIT_BYTES, False), (length, done)  # C2: stalled exactly full, not at the end of the audio

        time.sleep(PARKED_SECONDS)
        assert _buffered(pipe) == (LIMIT_BYTES, False)  # C2: with no release the reader stays parked: still full, still not done

        before, _ = pipe.wait_samples(0)
        assert before == LIMIT_SAMPLES, before  # C2 control: wait_samples counts from the stream's start
        pipe.release(RELEASED_TO)
        after, _ = pipe.wait_samples(before + 1)
        assert after > before, (before, after)  # C2: release freed room and the reader resumed, counted in absolute samples

        largest, length, done = _settle(pipe)
        assert largest <= LIMIT_BYTES and (length, done) == (LIMIT_BYTES, False), (largest, length, done)  # C2: refilled to the limit again, no further
        assert pipe.wait_samples(0)[0] == RELEASED_TO + LIMIT_SAMPLES  # C2: absolute count is the release point plus a full buffer

        pos = RELEASED_TO
        delivered = bytearray()
        deadline = time.monotonic() + DRAIN_SECONDS
        while True:
            available, done = pipe.wait_samples(pos + WINDOW_SAMPLES)
            if available > pos:
                delivered += pipe.slice(pos, available)
                pipe.release(available)
                pos = available
            if done and available == pos:
                break
            if time.monotonic() > deadline:
                pytest.fail(f"not done {DRAIN_SECONDS} s into releasing: at {pos} of {DECODED_SAMPLES}")
        assert media.opened == [MEDIA_URL]  # C2 control: the real feeder downloaded the media once
        assert done is True  # C2: a normal EOF still completes
        assert pos == DECODED_SAMPLES, pos  # C2: every decoded sample came through, none dropped at the limit
        assert delivered == MEDIA_BODY[RELEASED_TO * BYTES_PER_SAMPLE:]  # C2: the samples after the release point arrive in order, none dropped or repeated across a park
        assert pipe.error is None, pipe.error  # C2: the decoder's exit 0 is not an error
    finally:
        _close(pipe)
