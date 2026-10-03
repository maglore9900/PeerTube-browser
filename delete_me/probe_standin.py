"""Probe: run the phase-1 checkpoint against the plan's own phase-1 code as a stand-in module, then against mutants of it, to see the harness pass a correct implementation and fail wrong ones."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEST = ROOT / "tests" / "tmp" / "test_48_translate_instance_captions_phase1.py"

STANDIN = r'''
from __future__ import annotations

import html
import http.client
import json
import logging
import re
import time
from typing import Any
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

TARGET_LANGUAGE = "en"
FETCH_MAX_BYTES = 2_000_000
FETCH_DEADLINE_SECONDS = 8.0
SOCKET_TIMEOUT_SECONDS = 4.0
READ_CHUNK_BYTES = 65_536
_HEADER = re.compile(r"WEBVTT(?:[ \t].*)?")
_SKIPPED_BLOCK = re.compile(r"(?:NOTE|STYLE|REGION)(?:[ \t].*)?")
_TIMESTAMP = r"(?:(\d{2,}):)?([0-5]\d):([0-5]\d)\.(\d{3})"
_TIMING_LINE = re.compile(rf"{_TIMESTAMP}[ \t]+-->[ \t]+{_TIMESTAMP}(?:[ \t].*)?")
_TAG = re.compile(r"<[^>]*>")


def same_host_https(url: str, host: str) -> bool:
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return False
    return parts.scheme == "https" and parts.hostname == host and port is None and parts.username is None and parts.password is None


class SameHostRedirectHandler(HTTPRedirectHandler):
    def __init__(self, host: str) -> None:
        super().__init__()
        self.host = host

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not same_host_https(newurl, self.host):
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_bounded(host: str, path: str, budget_at: float) -> bytes | None:
    deadline = min(time.monotonic() + FETCH_DEADLINE_SECONDS, budget_at)
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return None
    request = Request(f"https://{host}{path}", headers={"accept": "application/json, text/vtt"})
    chunks: list[bytes] = []
    size = 0
    try:
        with build_opener(SameHostRedirectHandler(host)).open(request, timeout=min(SOCKET_TIMEOUT_SECONDS, remaining)) as resp:
            if resp.status != 200:
                return None
            length = (resp.headers.get("content-length") or "").strip()
            if length.isdigit() and int(length) > FETCH_MAX_BYTES:
                return None
            while True:
                if time.monotonic() > deadline:
                    return None
                chunk = resp.read1(READ_CHUNK_BYTES)
                if not chunk:
                    break
                size += len(chunk)
                if size > FETCH_MAX_BYTES:
                    return None
                chunks.append(chunk)
    except (OSError, ValueError, http.client.HTTPException) as exc:
        return None
    return b"".join(chunks)


def pick_english_track_path(listing: bytes, host: str) -> str | None:
    try:
        payload = json.loads(listing.decode("utf-8"))
    except (ValueError, RecursionError):
        return None
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        return None
    for item in data:
        language = item.get("language") if isinstance(item, dict) else None
        if isinstance(language, dict) and language.get("id") == TARGET_LANGUAGE:
            return _track_path(item, host)
    return None


def _track_path(item, host):
    caption_path = item.get("captionPath")
    if isinstance(caption_path, str) and caption_path.startswith("/") and not caption_path.startswith("//"):
        return caption_path
    file_url = item.get("fileUrl")
    if isinstance(file_url, str) and same_host_https(file_url, host):
        parts = urlsplit(file_url)
        return (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
    return None


def _seconds(hours, minutes, seconds, millis):
    return round(int(hours or 0) * 3600 + int(minutes) * 60 + int(seconds) + int(millis) / 1000, 3)


def _blocks(lines):
    blocks = []
    current = []
    for line in lines:
        if line.strip():
            current.append(line)
        elif current:
            blocks.append(current)
            current = []
    if current:
        blocks.append(current)
    return blocks


def parse_webvtt(text: str):
    lines = text.removeprefix("\ufeff").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if not _HEADER.fullmatch(lines[0]):
        return None
    cues = []
    for block in _blocks(lines)[1:]:
        if _SKIPPED_BLOCK.fullmatch(block[0]):
            continue
        timing_at = 0 if "-->" in block[0] else 1
        match = _TIMING_LINE.fullmatch(block[timing_at]) if len(block) > timing_at else None
        if match is None:
            return None
        start = _seconds(*match.group(1, 2, 3, 4))
        end = _seconds(*match.group(5, 6, 7, 8))
        if end < start:
            return None
        cue_text = html.unescape(_TAG.sub("", "\n".join(block[timing_at + 1:]))).strip()
        if cue_text:
            cues.append({"start": start, "end": end, "text": cue_text})
    cues.sort(key=lambda cue: (cue["start"], cue["end"]))
    return cues or None
'''

MUTANTS = {
    "correct": [],
    "stub returning None": [("    def redirect_request(self, req, fp, code, msg, headers, newurl):\n", "    def redirect_request(self, req, fp, code, msg, headers, newurl):\n        return None\n"), ("def fetch_bounded(host: str, path: str, budget_at: float) -> bytes | None:\n", "def fetch_bounded(host: str, path: str, budget_at: float) -> bytes | None:\n    return None\n"), ("def pick_english_track_path(listing: bytes, host: str) -> str | None:\n", "def pick_english_track_path(listing: bytes, host: str) -> str | None:\n    return None\n"), ("def parse_webvtt(text: str):\n", "def parse_webvtt(text: str):\n    return None\n")],
    "fetch opens then returns None": [("            if resp.status != 200:\n", "            return None\n            if resp.status != 200:\n")],
    "default redirect handler": [("build_opener(SameHostRedirectHandler(host))", "build_opener()")],
    "no length precheck": [("if length.isdigit() and int(length) > FETCH_MAX_BYTES:", "if False:")],
    "no stream cap": [("if size > FETCH_MAX_BYTES:", "if False:")],
    "no deadline check": [("if time.monotonic() > deadline:", "if False:")],
    "budget checked only before open": [("    deadline = min(time.monotonic() + FETCH_DEADLINE_SECONDS, budget_at)", "    fetch_started = time.monotonic()\n    deadline = min(fetch_started + FETCH_DEADLINE_SECONDS, budget_at)"), ("if time.monotonic() > deadline:", "if time.monotonic() > fetch_started + FETCH_DEADLINE_SECONDS:")],
    "budget ignored": [("deadline = min(time.monotonic() + FETCH_DEADLINE_SECONDS, budget_at)", "deadline = time.monotonic() + FETCH_DEADLINE_SECONDS")],
    "startswith host": [("parts.hostname == host", "(parts.hostname or '').startswith(host)")],
    "drops bad cues": [("        if match is None:\n            return None", "        if match is None:\n            continue"), ("        if end < start:\n            return None", "        if end < start:\n            continue")],
    "unsorted": [("    cues.sort(key=lambda cue: (cue[\"start\"], cue[\"end\"]))\n", "")],
    "decode before strip": [("html.unescape(_TAG.sub(\"\", \"\\n\".join(block[timing_at + 1:])))", "_TAG.sub(\"\", html.unescape(\"\\n\".join(block[timing_at + 1:])))")],
    "tags left in": [("html.unescape(_TAG.sub(\"\", \"\\n\".join(block[timing_at + 1:])))", "html.unescape(\"\\n\".join(block[timing_at + 1:]))")],
    "empty list not None": [("    return cues or None", "    return cues")],
    "end <= start rejected": [("if end < start:", "if end <= start:")],
    "lenient header": [("if not _HEADER.fullmatch(lines[0]):", "if not lines[0].startswith(\"WEBVTT\"):")],
    "string times": [("return round(int(hours or 0) * 3600 + int(minutes) * 60 + int(seconds) + int(millis) / 1000, 3)", "return f\"{round(int(hours or 0) * 3600 + int(minutes) * 60 + int(seconds) + int(millis) / 1000, 3)}\"")],
    "pick any en prefix": [("language.get(\"id\") == TARGET_LANGUAGE", "str(language.get(\"id\")).startswith(TARGET_LANGUAGE)")],
}

RUNNER = r'''
import importlib.util, sys
sys.path[:0] = [sys.argv[1], sys.argv[1] + "/api"]
import handlers
spec = importlib.util.spec_from_file_location("handlers.internal_translate", sys.argv[2])
module = importlib.util.module_from_spec(spec)
sys.modules["handlers.internal_translate"] = module
spec.loader.exec_module(module)
handlers.internal_translate = module
import pytest
sys.exit(pytest.main([sys.argv[3], "-q", "-p", "no:cacheprovider", "--no-header", "-rf", "--tb=no"]))
'''


def test_standin(tmp_path):
    for name, edits in MUTANTS.items():
        source = STANDIN
        for old, new in edits:
            assert old in source, (name, old)
            source = source.replace(old, new)
        path = tmp_path / f"standin_{abs(hash(name))}.py"
        path.write_text(source)
        run = subprocess.run([sys.executable, "-c", RUNNER, str(ROOT / "engine" / "server"), str(path), str(TEST)], capture_output=True, text=True, cwd=ROOT)
        lines = [line for line in run.stdout.splitlines() if line.strip()]
        failed = [line for line in run.stdout.splitlines() if line.startswith("FAILED") or "::" in line and "FAIL" in line]
        print(f"== {name}: exit {run.returncode}: {lines[-1] if lines else run.stderr[-500:]}")
        for line in run.stdout.splitlines():
            if line.startswith("FAILED"):
                print("   ", line.split("::", 1)[-1])
        if name == "correct" and run.returncode != 0:
            print(run.stdout[-4000:], run.stderr[-2000:])
