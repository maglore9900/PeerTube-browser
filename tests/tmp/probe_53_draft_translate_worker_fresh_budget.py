#!/usr/bin/env python3
"""Translate worker (plan 49): English cues for whitelisted videos with Whisper's translate task, one queued job at a time, into subtitles.db.

enqueue --id --host resolves the video against whitelist.db the way B1's /internal/translate does and queues it under the row's canonical video_id and instance_domain, printing one line with one exit code per outcome.

run_job takes one claimed job through the whitelist again, the instance's English track, the video JSON, one sequential media download piped into ffmpeg's stdin, and silence-cut PCM chunks handed to a runner (speech, transcribe, unload), rewriting the running row's cues after each chunk until exactly one end state.

run is the service, in this order: ffmpeg check, flock (a refused second run exits 6 having written nothing), schema and crash recovery, a heartbeat thread beating every 5 s while the main loop makes progress, then the claim loop until SIGTERM. numpy, faster_whisper and the CUDA wheels are imported only inside WhisperRunner, so enqueue and the Engine never need them.
"""

from __future__ import annotations

import argparse
import fcntl
import gc
import http.client
import json
import logging
import math
import os
import re
import shutil
import signal
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit
from urllib.request import Request, build_opener

script_dir = Path(__file__).resolve().parent
server_dir = script_dir.parents[1]
if str(server_dir) not in sys.path:
    sys.path.insert(0, str(server_dir))
api_dir = server_dir / "api"
if str(api_dir) not in sys.path:
    sys.path.insert(0, str(api_dir))

from scripts.cli_format import CompactHelpFormatter
from server_config import DEFAULT_DB_PATH, DEFAULT_SUBTITLES_DB_PATH, SUBTITLE_MAX_BYTES, SUBTITLE_MAX_CHUNK_SECONDS, SUBTITLE_MAX_DURATION, SUBTITLE_QUEUE_CAP, VIDEO_ERROR_THRESHOLD
from data.db import connect_readonly_db
from data.moderation import list_active_denied_hosts, normalize_host
from data.subtitles import claim_translate_job, connect_subtitles_db, enqueue_translate_job, ensure_subtitles_schema, finish_translate_already_english, finish_translate_failed, finish_translate_ready, mark_translate_finished, recover_translate_jobs, requeue_translate_job, store_ready_subtitles, store_running_cues, write_translate_heartbeat
from data.time import now_ms
from data.source_fetch import READ_CHUNK_BYTES, SourceFetchFailed, fetch_bounded, stream_media
from handlers.internal_translate import SOURCE_INSTANCE, TARGET_LANGUAGE, fetch_instance_track
from handlers.video import fetch_video_row

EXIT_QUEUED = 0
EXIT_ERROR = 1
# 2 is argparse's usage error.
EXIT_EXISTS = 3
EXIT_CAP = 4
EXIT_REFUSED = 5
EXIT_LOCKED = 6
MODEL_NAME = "medium"
COMPUTE_TYPE = "int8_float16"
# rat-tail: the Engine's HEARTBEAT_FRESH_MS (internal_translate.py, 15 s) is three of these beats with no shared constant; raise both together.
HEARTBEAT_SECONDS = 5.0
IDLE_UNLOAD_SECONDS = 300.0
# Far longer than one chunk on the GPU; a main loop silent this long stops the heartbeat, so plan 50 reads a hung worker as unavailable.
STALL_SECONDS = 600.0
# Cut-point VAD: shorter silences than faster-whisper's 2 s default count as gaps, so fewer chunks are hard-cut.
VAD_MIN_SILENCE_MS = 500
VAD_SPEECH_PAD_MS = 200
SAMPLE_RATE = 16_000
BYTES_PER_SAMPLE = 2
# A silence cut closer than this to the chunk start is not taken, so speech with short pauses is not cut into slivers.
MIN_CHUNK_SAMPLES = 5 * SAMPLE_RATE
POLL_SECONDS = 2.0
# The requeued job stays at the head, so without this wait serve reclaims it at once and spins on a locked or missing whitelist.db.
TRANSIENT_BACKOFF_SECONDS = 30.0
# The only stall bound on the download; there is no whole-job deadline.
MEDIA_SOCKET_TIMEOUT_SECONDS = 15.0
STDERR_TAIL_BYTES = 4096
# ffmpeg reads the download from stdin, never the URL: it stalls seeking a remote fragmented MP4 (R1).
FFMPEG_ARGS = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", "pipe:0", "-vn", "-f", "s16le", "-ac", "1", "-ar", str(SAMPLE_RATE), "pipe:1"]
# A DNS name's last label is letters or punycode, never digits or hex.
_TLD = re.compile(r"[a-z]{2,63}|xn--[a-z0-9-]{1,59}")


class JobFailed(Exception):
    """A bound refused the job or a step failed; the message is the stored error text."""


class JobStopped(Exception):
    """stop was set mid-job; the job is requeued without spending its claim."""


class JobTakenOver(Exception):
    """A conditional update matched no row: B1's route replaced the running row."""


class WhitelistBusy(Exception):
    """whitelist.db was locked, busy or could not be opened at claim; the job is requeued without spending its claim."""


def resolve_video(whitelist_path: Path, video_id: str, host: str, max_duration: int) -> tuple[dict[str, Any] | None, str | None]:
    """The whitelisted row and None, or None and the refusal text: B1's check (fetch_video_row with VIDEO_ERROR_THRESHOLD, then the active denylist on the row's normalised domain) plus the stored-duration bound; NULL duration passes."""
    conn = connect_readonly_db(whitelist_path)
    try:
        # sqlite3's 5 s default is shorter than the updater merge's commit; past 30 s this raises, never reads as not-found.
        conn.execute("PRAGMA busy_timeout = 30000")
        row = fetch_video_row(conn, video_id, host, error_threshold=VIDEO_ERROR_THRESHOLD)
        denied = list_active_denied_hosts(conn) if row is not None else set()
    finally:
        conn.close()
    if row is None:
        return None, "not in whitelist"
    if normalize_host(row["instance_domain"]) in denied:
        return None, "host denied"
    duration = row["duration"]
    if isinstance(duration, int) and duration > max_duration:
        return None, f"duration {duration}s over {max_duration}s"
    return row, None


def command_enqueue(args: argparse.Namespace) -> int:
    """Resolve and queue one video; one output line and one exit code per outcome."""
    video_id = args.id.strip()
    # Refused before the lookup: fetch_video_row with a None host matches the id on any host.
    host = normalize_host(args.host)
    if host is None or not video_id:
        print("refused: invalid id or host")
        return EXIT_REFUSED
    try:
        row, refusal = resolve_video(args.whitelist_db, video_id, host, args.max_duration)
    except sqlite3.Error as exc:
        print(f"error: whitelist.db: {exc}")
        return EXIT_ERROR
    if refusal is not None:
        print(f"refused: {refusal}")
        return EXIT_REFUSED
    args.subtitles_db.parent.mkdir(parents=True, exist_ok=True)
    try:
        conn = connect_subtitles_db(args.subtitles_db)
        try:
            ensure_subtitles_schema(conn)
            outcome, state = enqueue_translate_job(conn, row["video_id"], row["instance_domain"], TARGET_LANGUAGE, args.cap, now_ms())
        finally:
            conn.close()
    except sqlite3.Error as exc:
        print(f"error: subtitles.db: {exc}")
        return EXIT_ERROR
    where = f"video_id={row['video_id']} host={row['instance_domain']}"
    if outcome == "queued":
        print(f"queued {where}")
        return EXIT_QUEUED
    if outcome == "exists":
        print(f"already present: {state} {where}")
        return EXIT_EXISTS
    print(f"refused: queue cap {args.cap}")
    return EXIT_CAP


def media_host(url: str) -> str | None:
    """The raw urlsplit hostname of an acceptable media URL (https, a DNS name, no port, no userinfo), else None; raw, not normalize_host's, so SameHostRedirectHandler's exact compare holds."""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return None
    host = parts.hostname or ""
    labels = host.rstrip(".").split(".")
    if parts.scheme != "https" or port is not None or parts.username is not None or parts.password is not None or normalize_host(host) is None:
        return None
    # Two labels or more ending in a real TLD refuses every IP literal, and also 127.1, 2130706433 and 0x7f.0x1, which inet_aton resolves but ipaddress rejects.
    return host if len(labels) >= 2 and _TLD.fullmatch(labels[-1]) else None


def _items(value: Any) -> list[Any]:
    """value when it is a JSON array, else empty: the instance's JSON is untrusted."""
    return value if isinstance(value, list) else []


def pick_media_url(video: dict[str, Any]) -> str | None:
    """The smallest acceptable fileUrl in streamingPlaylists[].files[], else in files[]; hasAudio false is skipped (PeerTube 7 split HLS), a missing hasAudio is kept, unknown sizes sort last."""
    # HLS files are fragmented MP4, which ffmpeg decodes from a pipe; a web-video MP4 may keep its moov atom at the end, and ffmpeg reading it from stdin then decodes nothing and still exits 0.
    files = [(1, item) for item in _items(video.get("files"))]
    for playlist in _items(video.get("streamingPlaylists")):
        files += [(0, item) for item in _items(playlist.get("files"))] if isinstance(playlist, dict) else []
    ranked: list[tuple[int, float, str]] = []
    for group, item in files:
        if not isinstance(item, dict) or item.get("hasAudio") is False or not isinstance(item.get("fileUrl"), str) or media_host(item["fileUrl"]) is None:
            continue
        size = item.get("size")
        ranked.append((group, size if isinstance(size, int) and not isinstance(size, bool) and size > 0 else math.inf, item["fileUrl"]))
    return min(ranked, key=lambda entry: entry[:2])[2] if ranked else None


def video_duration(video: dict[str, Any]) -> float | None:
    """The JSON's duration in seconds when it is a finite non-negative number, else None (the bound cannot be checked)."""
    value = video.get("duration")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        return None
    return float(value)


class AudioPipe:
    """One sequential download fed to ffmpeg's stdin, 16 kHz mono s16le read from its stdout into memory, each on its own thread so the download runs at network speed whatever the GPU does; nothing touches disk."""

    def __init__(self, url: str, host: str, max_bytes: int, max_samples: int) -> None:
        """Start ffmpeg and the feeder, stdout reader and stderr drain threads for one media URL, its raw host and both caps."""
        self.url = url
        self.host = host
        self.max_bytes = max_bytes
        self.max_samples = max_samples
        # rat-tail: all PCM stays in RAM (about 115 MB at the 60-minute cap); drop samples already transcribed if the cap ever grows.
        self.pcm = bytearray()
        self.done = False
        self.error: str | None = None
        self.cond = threading.Condition()
        self.stop = threading.Event()
        self.stderr_tail = b""
        self.proc = subprocess.Popen(FFMPEG_ARGS, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.threads = [threading.Thread(target=target, daemon=True) for target in (self._feed, self._read, self._drain_stderr)]
        for thread in self.threads:
            thread.start()

    def _fail(self, text: str) -> None:
        """Record the first error, wake the waiting chunk loop, stop the feeder and kill ffmpeg."""
        with self.cond:
            if self.error is None:
                self.error = text
            self.cond.notify_all()
        self.stop.set()
        self.proc.kill()

    def _feed(self) -> None:
        """draft"""
        try:
            stream_media(self.url, self.host, self.max_bytes, self.proc.stdin.write, self.stop)
        except BrokenPipeError:
            pass
        except SourceFetchFailed as exc:
            self._fail(str(exc))
        finally:
            try:
                self.proc.stdin.close()
            except OSError:
                pass

    def _read(self) -> None:
        """Drain stdout into pcm, aborting past max_samples so a JSON that understates the duration is still bounded; then reap ffmpeg and report a non-zero exit with its stderr tail."""
        while True:
            data = self.proc.stdout.read1(READ_CHUNK_BYTES)
            if not data:
                break
            with self.cond:
                self.pcm += data
                self.cond.notify_all()
            if len(self.pcm) // BYTES_PER_SAMPLE > self.max_samples:
                self._fail(f"audio longer than {self.max_samples // SAMPLE_RATE}s")
                break
        code = self.proc.wait()
        self.threads[2].join()
        if code != 0 and not self.stop.is_set():
            self._fail(f"ffmpeg exit {code}: {self.stderr_tail.decode('utf-8', 'replace').strip()}")
        # Set after any error, under the lock, so a reader that sees done also sees the error.
        with self.cond:
            self.done = True
            self.cond.notify_all()

    def _drain_stderr(self) -> None:
        """Keep the tail of ffmpeg's stderr, read to its end so a full pipe never blocks ffmpeg."""
        for line in self.proc.stderr:
            self.stderr_tail = (self.stderr_tail + line)[-STDERR_TAIL_BYTES:]

    def wait_samples(self, end: int) -> tuple[int, bool]:
        """Block up to POLL_SECONDS for end samples, an error or the end of the audio; the samples buffered and whether the audio has ended."""
        with self.cond:
            self.cond.wait_for(lambda: self.done or self.error is not None or len(self.pcm) >= end * BYTES_PER_SAMPLE, timeout=POLL_SECONDS)
            return len(self.pcm) // BYTES_PER_SAMPLE, self.done

    def slice(self, start: int, end: int) -> bytes:
        """A copy of samples [start, end)."""
        with self.cond:
            return bytes(self.pcm[start * BYTES_PER_SAMPLE:end * BYTES_PER_SAMPLE])

    def close(self) -> None:
        """Stop the feeder, kill ffmpeg if it still runs and join the threads; the feeder's join is bounded by one socket timeout."""
        self.stop.set()
        self.proc.kill()
        for thread in self.threads:
            thread.join()
        self.proc.stdout.close()
        self.proc.stderr.close()


def preload_cuda_libraries() -> None:
    """dlopen the pip CUDA wheels' cuBLAS and cuDNN with RTLD_GLOBAL, as S0 did, so CTranslate2 finds them without LD_LIBRARY_PATH."""
    import ctypes
    import importlib.util
    for package, names in (("nvidia.cublas", ("libcublasLt.so.12", "libcublas.so.12")), ("nvidia.cudnn", ("libcudnn.so.9",))):
        lib = Path(next(iter(importlib.util.find_spec(package).submodule_search_locations))) / "lib"
        for name in names:
            ctypes.CDLL(str(lib / name), mode=ctypes.RTLD_GLOBAL)


def _float_audio(pcm: bytes) -> Any:
    """s16le bytes as float32 in [-1, 1), the form faster_whisper takes."""
    import numpy as np
    return np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0


class WhisperRunner:
    """The faster-whisper model, loaded on the first transcribe and dropped by unload; run_job takes any object with model, speech, transcribe and unload."""

    def __init__(self) -> None:
        """Start without a model."""
        self.model: Any = None

    def speech(self, pcm: bytes) -> list[tuple[int, int]]:
        """Silero speech spans in samples (faster-whisper's own VAD, on CPU)."""
        from faster_whisper.vad import VadOptions, get_speech_timestamps
        spans = get_speech_timestamps(_float_audio(pcm), VadOptions(min_silence_duration_ms=VAD_MIN_SILENCE_MS, speech_pad_ms=VAD_SPEECH_PAD_MS))
        return [(span["start"], span["end"]) for span in spans]

    def transcribe(self, pcm: bytes, language: str | None) -> tuple[list[tuple[float, float, str]], str]:
        """Translate one chunk to English: its (start, end, text) segments in chunk seconds and the language, detected when language is None."""
        if self.model is None:
            preload_cuda_libraries()
            from faster_whisper import WhisperModel
            self.model = WhisperModel(MODEL_NAME, device="cuda", compute_type=COMPUTE_TYPE)
            logging.info("[translate-worker] model loaded name=%s compute_type=%s", MODEL_NAME, COMPUTE_TYPE)
        segments, info = self.model.transcribe(_float_audio(pcm), task="translate", language=language, vad_filter=True)
        # transcribe is lazy: decoding, and any CUDA out-of-memory, happens while this list is built.
        return [(segment.start, segment.end, segment.text) for segment in segments], info.language

    def unload(self) -> None:
        """Drop the model and collect it; the CUDA context stays until exit (accepted)."""
        if self.model is not None:
            self.model = None
            gc.collect()
            logging.info("[translate-worker] model unloaded")


def is_cuda_oom(exc: BaseException) -> bool:
    """CTranslate2 raises CUDA out-of-memory as a RuntimeError naming it."""
    return isinstance(exc, RuntimeError) and "out of memory" in str(exc).lower()


def cut_point(spans: list[tuple[int, int]], length: int, final: bool) -> int:
    """Where a window is cut, in samples: its end when it is the last window, holds no speech or ends in silence; else the middle of its last gap between speech spans when that is MIN_CHUNK_SAMPLES in or more; else its end, a hard cut (R2)."""
    if final or not spans or spans[-1][1] < length:
        return length
    gaps = [(gap_start + gap_end) // 2 for (_, gap_start), (gap_end, _) in zip(spans, spans[1:])]
    return gaps[-1] if gaps and gaps[-1] >= MIN_CHUNK_SAMPLES else length


def chunk_cues(segments: list[tuple[float, float, str]], offset: float) -> list[dict[str, Any]]:
    """Segments as absolute cues: stripped text, empty texts dropped, times plus the chunk offset rounded to ms like parse_webvtt, non-finite or reversed times dropped."""
    cues: list[dict[str, Any]] = []
    for start, end, text in segments:
        text = text.strip()
        begin = round(offset + start, 3)
        finish = round(offset + end, 3)
        if text and math.isfinite(begin) and math.isfinite(finish) and finish >= begin:
            cues.append({"start": begin, "end": finish, "text": text})
    return cues


def translate_audio(conn: sqlite3.Connection, claim: tuple[str, str, str, int], pipe: AudioPipe, runner: Any, max_chunk: int, stop: threading.Event, progress: dict[str, float]) -> str:
    """Transcribe pipe's PCM window by window, rewriting the running row's cues after each chunk that adds some; the end state written."""
    cues: list[dict[str, Any]] = []
    language: str | None = None
    pos = 0
    while True:
        available, done = pipe.wait_samples(pos + max_chunk)
        progress["at"] = time.monotonic()
        if stop.is_set():
            raise JobStopped()
        if pipe.error is not None:
            raise JobFailed(pipe.error)
        final = available < pos + max_chunk
        if final and not done:
            continue
        if available <= pos:
            break
        window = pipe.slice(pos, min(available, pos + max_chunk))
        spans = runner.speech(window)
        cut = cut_point(spans, len(window) // BYTES_PER_SAMPLE, final)
        # A chunk with no speech is never transcribed: no GPU time, no invented lines (R5), and detection runs on the first chunk that has speech.
        if any(start < cut for start, _ in spans):
            segments, detected = runner.transcribe(window[:cut * BYTES_PER_SAMPLE], language)
            if language is None:
                language = detected
                if language == TARGET_LANGUAGE:
                    if not finish_translate_already_english(conn, *claim, language, now_ms()):
                        raise JobTakenOver()
                    return "already_english"
            new = chunk_cues(segments, pos / SAMPLE_RATE)
            if new:
                cues += new
                if not store_running_cues(conn, *claim, cues, language):
                    raise JobTakenOver()
        pos += cut
    if pos == 0:
        raise JobFailed("no audio decoded")
    if not cues:
        raise JobFailed("no speech detected")
    # Segments may come out of order or overlap at a join; B1's reader and the page binary-search by start.
    cues.sort(key=lambda cue: (cue["start"], cue["end"]))
    if not finish_translate_ready(conn, *claim, cues, now_ms()):
        raise JobTakenOver()
    return "ready"


def generate(conn: sqlite3.Connection, claim: tuple[str, str, str, int], args: argparse.Namespace, runner: Any, stop: threading.Event, progress: dict[str, float]) -> str:
    """AC3 for one claim (video_id, instance_domain, target_language, started_at), each bound raising JobFailed before the next remote request, a locked or unopenable whitelist.db raising WhitelistBusy; the end state written."""
    try:
        row, refusal = resolve_video(args.whitelist_db, *claim[:2], args.max_duration)
    except sqlite3.OperationalError as exc:
        # Only a lock or a missing file (the updater's merge, a restore) is transient; a corrupt or unmigrated file still fails the job.
        if any(word in str(exc).lower() for word in ("locked", "busy", "unable to open")):
            raise WhitelistBusy(str(exc)) from exc
        raise
    if refusal is not None:
        raise JobFailed(refusal)
    instance = row["instance_domain"]
    video_key = row["video_uuid"] or row["video_id"]
    fetched = fetch_instance_track(instance, video_key)
    if fetched is not None:
        store_ready_subtitles(conn, *claim[:3], SOURCE_INSTANCE, fetched[0], fetched[1], now_ms())
        mark_translate_finished(conn, *claim, now_ms())
        return "ready from the instance track"
    try:
        raw = fetch_bounded(instance, f"/api/v1/videos/{quote(video_key, safe='')}")
    except SourceFetchFailed as exc:
        raise JobFailed(f"video JSON fetch failed: {exc}") from exc
    try:
        video = json.loads(raw.decode("utf-8"))
        exc = "not an object"
    except (ValueError, RecursionError) as error:
        video = None
        exc = error
    if not isinstance(video, dict):
        raise JobFailed("video JSON fetch failed")
    duration = video_duration(video)
    if duration is None:
        raise JobFailed("video duration unknown")
    if duration > args.max_duration:
        raise JobFailed(f"duration {duration:g}s over {args.max_duration}s")
    url = pick_media_url(video)
    if url is None:
        raise JobFailed("no usable https media file")
    pipe = AudioPipe(url, media_host(url), args.max_bytes, args.max_duration * SAMPLE_RATE)
    try:
        return translate_audio(conn, claim, pipe, runner, args.max_chunk_seconds * SAMPLE_RATE, stop, progress)
    finally:
        pipe.close()


def run_job(conn: sqlite3.Connection, job: sqlite3.Row, args: argparse.Namespace, runner: Any, stop: threading.Event, progress: dict[str, float]) -> bool:
    """Take one claimed job to exactly one end state, or back to queued with its claim unspent when stop is set mid-job or whitelist.db is locked or unopenable at claim; a row B1's route took over is left as B1 wrote it. True only for the whitelist.db requeue."""
    claim = (job["video_id"], job["instance_domain"], TARGET_LANGUAGE, job["started_at"])
    try:
        state = generate(conn, claim, args, runner, stop, progress)
        logging.info("[translate-worker] job %s video_id=%s host=%s", state, *claim[:2])
    except JobStopped:
        requeue_translate_job(conn, *claim)
        logging.info("[translate-worker] stopped mid-job, requeued video_id=%s host=%s", *claim[:2])
    except WhitelistBusy as exc:
        # The attempt is given back, so MAX_CLAIMS recovery never counts these cycles.
        requeue_translate_job(conn, *claim)
        logging.warning("[translate-worker] whitelist.db unavailable, requeued video_id=%s host=%s: %s", *claim[:2], exc)
        return True
    except JobTakenOver:
        logging.info("[translate-worker] taken over by the instance track video_id=%s host=%s", *claim[:2])
    except JobFailed as exc:
        finish_translate_failed(conn, *claim, str(exc), now_ms())
        logging.info("[translate-worker] job failed video_id=%s host=%s: %s", *claim[:2], exc)
    except Exception as exc:
        # A CUDA out-of-memory fails only this job; the model is dropped so the next job loads it afresh instead of retrying in a loop (AC7).
        if is_cuda_oom(exc):
            runner.unload()
        logging.exception("[translate-worker] job error video_id=%s host=%s", *claim[:2])
        finish_translate_failed(conn, *claim, f"{type(exc).__name__}: {exc}", now_ms())
    return False


def heartbeat_loop(db_path: Path, stop: threading.Event, progress: dict[str, float]) -> None:
    """Beat every HEARTBEAT_SECONDS on its own connection, idle or busy, unless the main loop has been silent for STALL_SECONDS; a failed beat is logged and retried next tick."""
    conn = connect_subtitles_db(db_path)
    try:
        while True:
            if time.monotonic() - progress["at"] <= STALL_SECONDS:
                try:
                    write_translate_heartbeat(conn, now_ms(), os.getpid())
                except sqlite3.Error as exc:
                    logging.warning("[translate-worker] heartbeat failed: %s", exc)
            if stop.wait(HEARTBEAT_SECONDS):
                break
    finally:
        conn.close()


def serve(conn: sqlite3.Connection, args: argparse.Namespace, runner: Any, stop: threading.Event, progress: dict[str, float]) -> None:
    """Claim and run jobs one at a time until stop, polling every POLL_SECONDS when idle, waiting TRANSIENT_BACKOFF_SECONDS after a whitelist.db requeue, and unloading the model after IDLE_UNLOAD_SECONDS without a job."""
    idle_since = time.monotonic()
    while not stop.is_set():
        progress["at"] = time.monotonic()
        try:
            job = claim_translate_job(conn, TARGET_LANGUAGE, now_ms())
        except sqlite3.Error as exc:
            logging.warning("[translate-worker] claim failed: %s", exc)
            job = None
        if job is None:
            if runner.model is not None and time.monotonic() - idle_since >= IDLE_UNLOAD_SECONDS:
                runner.unload()
            # time.sleep, not stop.wait: the SIGTERM handler sets stop on this thread, and Event.set deadlocks if it lands while this thread holds the event's lock inside wait.
            time.sleep(POLL_SECONDS)
            continue
        logging.info("[translate-worker] claimed video_id=%s host=%s attempts=%s", job["video_id"], job["instance_domain"], job["attempts"])
        if run_job(conn, job, args, runner, stop, progress):
            # Slept in POLL_SECONDS slices so a stop still ends serve within one slice, and progress refreshed each slice so the heartbeat does not read the wait as a stall.
            resume = time.monotonic() + TRANSIENT_BACKOFF_SECONDS
            while not stop.is_set() and time.monotonic() < resume:
                progress["at"] = time.monotonic()
                time.sleep(max(0.0, min(POLL_SECONDS, resume - time.monotonic())))
        idle_since = time.monotonic()


def setup_logging(log_path: Path) -> None:
    """Log to stdout and to the --log file, as updater-worker.py does."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(log_path, "a")])


def command_run(args: argparse.Namespace) -> int:
    """The service: ffmpeg check, then the flock before subtitles.db is opened, so a refused second run writes nothing; then schema, recovery, the heartbeat thread and the claim loop until SIGTERM."""
    setup_logging(args.log)
    if shutil.which("ffmpeg") is None:
        logging.error("[translate-worker] ffmpeg not found on PATH")
        return EXIT_ERROR
    args.lock.parent.mkdir(parents=True, exist_ok=True)
    # O_RDONLY as in updater-worker.py's acquire_deploy_lock; the kernel drops the flock when the process dies, so a crash leaves no stale lock.
    lock_fd = os.open(args.lock.as_posix(), os.O_RDONLY | os.O_CREAT, 0o644)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(lock_fd)
        logging.error("[translate-worker] another worker holds %s", args.lock)
        return EXIT_LOCKED
    try:
        stop = threading.Event()
        for signum in (signal.SIGTERM, signal.SIGINT):
            signal.signal(signum, lambda *_: stop.set())
        progress = {"at": time.monotonic()}
        args.subtitles_db.parent.mkdir(parents=True, exist_ok=True)
        conn = connect_subtitles_db(args.subtitles_db)
        beat: threading.Thread | None = None
        try:
            ensure_subtitles_schema(conn)
            requeued, failed = recover_translate_jobs(conn, now_ms())
            logging.info("[translate-worker] started pid=%s recovered requeued=%s failed=%s", os.getpid(), requeued, failed)
            beat = threading.Thread(target=heartbeat_loop, args=(args.subtitles_db, stop, progress), daemon=True)
            beat.start()
            serve(conn, args, WhisperRunner(), stop, progress)
        finally:
            stop.set()
            if beat is not None:
                beat.join(HEARTBEAT_SECONDS)
            conn.close()
    finally:
        os.close(lock_fd)
    logging.info("[translate-worker] stopped")
    return 0


def _positive_int(value: str) -> int:
    """An argparse type for a whole number of at least 1."""
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError(f"must be a positive integer, got {value!r}")
    return number


def parse_args() -> argparse.Namespace:
    """Handle parse args."""
    repo_root = script_dir.parents[3]
    parser = argparse.ArgumentParser(description="Queue English translate jobs for whitelisted videos.", formatter_class=CompactHelpFormatter)
    parser.add_argument("--whitelist-db", type=Path, default=(repo_root / DEFAULT_DB_PATH).resolve(), help="Path to the Engine's whitelist DB (read only).")
    parser.add_argument("--subtitles-db", type=Path, default=(repo_root / DEFAULT_SUBTITLES_DB_PATH).resolve(), help="Path to the subtitles DB holding the queue.")
    sub = parser.add_subparsers(dest="command", required=True, title="commands")
    enqueue = sub.add_parser("enqueue", help="Queue one video by id or uuid and host.", formatter_class=CompactHelpFormatter)
    enqueue.add_argument("--id", required=True, help="Video id or uuid.")
    enqueue.add_argument("--host", required=True, help="Instance host.")
    enqueue.add_argument("--cap", type=_positive_int, default=SUBTITLE_QUEUE_CAP, help="Most queued jobs at once.")
    enqueue.add_argument("--max-duration", type=_positive_int, default=SUBTITLE_MAX_DURATION, help="Longest stored duration accepted, in seconds.")
    run = sub.add_parser("run", help="Serve the queue, one job at a time (the service).", formatter_class=CompactHelpFormatter)
    run.add_argument("--lock", type=Path, default=(repo_root / "engine/server/db/translate-worker.lock").resolve(), help="flock file; a second run against a held lock exits 6.")
    run.add_argument("--log", type=Path, default=(repo_root / "engine/server/db/translate-worker.log").resolve(), help="Path to log file.")
    run.add_argument("--max-duration", type=_positive_int, default=SUBTITLE_MAX_DURATION, help="Longest video accepted, in seconds.")
    run.add_argument("--max-bytes", type=_positive_int, default=SUBTITLE_MAX_BYTES, help="Largest media download accepted, in bytes.")
    run.add_argument("--max-chunk-seconds", type=_positive_int, default=SUBTITLE_MAX_CHUNK_SECONDS, help="Longest audio chunk handed to Whisper, in seconds.")
    return parser.parse_args()


def main() -> None:
    """Handle main."""
    args = parse_args()
    sys.exit(command_enqueue(args) if args.command == "enqueue" else command_run(args))


if __name__ == "__main__":
    main()
