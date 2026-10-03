"""S0 streaming variant: translate while the media file is still downloading.

Usage:
  .venv/bin/python translate_stream.py <url> [--model medium|large-v3] [--chunk-seconds 30]

The file is downloaded in one sequential pass and piped into ffmpeg's stdin, so ffmpeg
never range-requests the remote file. Audio is translated in fixed chunks as it arrives;
a word cut at a chunk boundary can be lost or garbled (acceptable for feasibility).
"""
import argparse
import shutil
import subprocess
import sys
import threading
import time
import urllib.request

import cuda_libs
from translate_probe import MAX_SECONDS, VramSampler, fetch_json, resolve, smallest_media, stamp

RATE = 16000


def feed(url: str, sink, counter: dict) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "peertube-browser-s0-probe"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            while block := resp.read(1 << 16):
                counter["bytes"] += len(block)
                sink.write(block)
    except BrokenPipeError:
        pass
    finally:
        counter["done"] = time.monotonic()
        sink.close()


def main() -> None:
    import numpy as np

    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--model", default="medium")
    ap.add_argument("--chunk-seconds", type=int, default=30)
    args = ap.parse_args()

    host, video_id = resolve(args.url)
    video = fetch_json(f"https://{host}/api/v1/videos/{video_id}")
    duration = video.get("duration") or 0
    print(f"{video.get('name')!r} on {host}, {stamp(duration)}, "
          f"instance language: {(video.get('language') or {}).get('id')}")
    if duration > MAX_SECONDS:
        sys.exit(f"refused: longer than {stamp(MAX_SECONDS)}")
    media = smallest_media(video)
    print(f"media: {media.get('resolution', {}).get('label')} {(media.get('size') or 0) / 1e6:.1f} MB")

    sampler = VramSampler()
    sampler.start()
    cuda_libs.preload()
    from faster_whisper import WhisperModel

    t_start = time.monotonic()
    model = WhisperModel(args.model, device="cuda", compute_type="int8_float16")
    print(f"model {args.model} loaded in {time.monotonic() - t_start:.1f} s\n", flush=True)

    ffmpeg = subprocess.Popen(
        [shutil.which("ffmpeg"), "-nostdin", "-loglevel", "error", "-i", "pipe:0",
         "-vn", "-ac", "1", "-ar", str(RATE), "-f", "s16le", "-"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    counter = {"bytes": 0, "done": None}
    t0 = time.monotonic()
    threading.Thread(target=feed, args=(media["fileUrl"], ffmpeg.stdin, counter), daemon=True).start()

    chunk_bytes = args.chunk_seconds * RATE * 2
    offset = 0.0
    first_line = None
    busy = 0.0
    while raw := ffmpeg.stdout.read(chunk_bytes):
        audio = np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0
        t_chunk = time.monotonic()
        segments, info = model.transcribe(audio, task="translate", vad_filter=True)
        for seg in segments:
            if first_line is None:
                first_line = time.monotonic() - t0
                print(f"(first line after {first_line:.1f} s; detected {info.language} "
                      f"p={info.language_probability:.2f})")
            print(f"[{stamp(offset + seg.start)} -> {stamp(offset + seg.end)}] {seg.text.strip()}", flush=True)
        busy += time.monotonic() - t_chunk
        offset += len(audio) / RATE
    ffmpeg.wait()

    total = time.monotonic() - t0
    if counter["done"]:
        mb = counter["bytes"] / 1e6
        print(f"\ndownload: {mb:.1f} MB in {counter['done'] - t0:.1f} s")
    print(f"audio translated: {stamp(offset)} in {total:.1f} s wall, {busy:.1f} s of it on the GPU")
    sampler.stop.set()
    sampler.join()
    print(f"VRAM: desktop baseline {sampler.baseline} MiB, peak total {sampler.peak_total} MiB of 8192, "
          f"this process peak {sampler.peak_own} MiB")


if __name__ == "__main__":
    main()
