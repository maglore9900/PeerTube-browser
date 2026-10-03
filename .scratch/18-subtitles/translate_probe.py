"""S0 feasibility probe: print Whisper's English translation of a PeerTube video in the terminal.

Usage:
  .venv/bin/python translate_probe.py <url> [--model medium|large-v3] [--device cuda|cpu]

<url> is a PeerTube watch URL (/w/<id>, /videos/watch/<id>, /videos/embed/<id>)
or a PeerTube Browser video-page URL carrying ?id=<id>&host=<domain>.
"""
import argparse
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
from urllib.parse import parse_qs, urlparse

import cuda_libs

MAX_SECONDS = 60 * 60  # plan 18, Q4


def resolve(url: str) -> tuple[str, str]:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    if "id" in query and "host" in query:
        return query["host"][0], query["id"][0]
    parts = [p for p in parsed.path.split("/") if p]
    for marker in ("w", "watch", "embed"):
        if marker in parts and parts.index(marker) + 1 < len(parts):
            return parsed.hostname, parts[parts.index(marker) + 1]
    sys.exit(f"cannot find a video id in {url}")


def fetch_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "peertube-browser-s0-probe"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.load(resp)


def smallest_media(video: dict) -> dict:
    files = list(video.get("files") or [])
    for playlist in video.get("streamingPlaylists") or []:
        files += playlist.get("files") or []
    files = [f for f in files if str(f.get("fileUrl", "")).startswith("https://")]
    if not files:
        sys.exit("no https media file in the video's API response")
    return min(files, key=lambda f: f.get("size") or float("inf"))


def load_audio(media_url: str):
    import numpy as np

    cmd = ["ffmpeg", "-nostdin", "-loglevel", "error", "-i", media_url,
           "-vn", "-ac", "1", "-ar", "16000", "-f", "s16le", "-"]
    raw = subprocess.run(cmd, check=True, capture_output=True).stdout
    return np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0


class VramSampler(threading.Thread):
    """Samples total used VRAM and this process's VRAM every 0.5 s."""

    def __init__(self) -> None:
        super().__init__(daemon=True)
        self.stop = threading.Event()
        self.peak_total = 0
        self.peak_own = 0
        self.baseline = self.total()

    @staticmethod
    def total() -> int:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True).stdout
        return int(out.split()[0])

    @staticmethod
    def own() -> int:
        out = subprocess.run(["nvidia-smi", "--query-compute-apps=pid,used_memory", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True).stdout
        for line in out.splitlines():
            pid, mem = (x.strip() for x in line.split(","))
            if pid == str(os.getpid()):
                return int(mem)
        return 0

    def run(self) -> None:
        while not self.stop.wait(0.5):
            self.peak_total = max(self.peak_total, self.total())
            self.peak_own = max(self.peak_own, self.own())


def stamp(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h:d}:{m:02d}:{s:02d}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--model", default="medium")
    ap.add_argument("--device", default="cuda", choices=["cuda", "cpu"])
    ap.add_argument("--compute-type", default=None)
    args = ap.parse_args()
    compute_type = args.compute_type or ("int8_float16" if args.device == "cuda" else "int8")

    host, video_id = resolve(args.url)
    video = fetch_json(f"https://{host}/api/v1/videos/{video_id}")
    duration = video.get("duration") or 0
    language = (video.get("language") or {}).get("id")
    print(f"{video.get('name')!r} on {host}, {stamp(duration)}, instance language: {language}")
    if duration > MAX_SECONDS:
        sys.exit(f"refused: longer than {stamp(MAX_SECONDS)}")
    captions = fetch_json(f"https://{host}/api/v1/videos/{video_id}/captions").get("data") or []
    print("instance captions:", [c.get("language", {}).get("id") for c in captions] or "none")

    media = smallest_media(video)
    print(f"media: {media.get('resolution', {}).get('label')} {(media.get('size') or 0) / 1e6:.1f} MB")
    t0 = time.monotonic()
    audio = load_audio(media["fileUrl"])
    t_audio = time.monotonic() - t0
    print(f"audio fetched and decoded in {t_audio:.1f} s")

    sampler = VramSampler() if args.device == "cuda" else None
    if sampler:
        sampler.start()
    if args.device == "cuda":
        cuda_libs.preload()
    from faster_whisper import WhisperModel

    t0 = time.monotonic()
    model = WhisperModel(args.model, device=args.device, compute_type=compute_type)
    t_load = time.monotonic() - t0
    print(f"model {args.model} ({args.device}, {compute_type}) loaded in {t_load:.1f} s\n")

    t0 = time.monotonic()
    segments, info = model.transcribe(audio, task="translate", vad_filter=True)
    print(f"detected language: {info.language} (p={info.language_probability:.2f})\n")
    for seg in segments:
        print(f"[{stamp(seg.start)} -> {stamp(seg.end)}] {seg.text.strip()}", flush=True)
    t_run = time.monotonic() - t0

    audio_seconds = len(audio) / 16000
    print(f"\ntranslate took {t_run:.1f} s for {stamp(audio_seconds)} of audio "
          f"({audio_seconds / t_run:.1f}x realtime)")
    if sampler:
        sampler.stop.set()
        sampler.join()
        print(f"VRAM: desktop baseline {sampler.baseline} MiB, peak total {sampler.peak_total} MiB of 8192, "
              f"this process peak {sampler.peak_own} MiB")


if __name__ == "__main__":
    main()
