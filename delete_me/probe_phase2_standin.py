"""Probe: run the phase-2 checkpoint's in-process tests against the plan's phase-2 handler and store (the real phase-1 module with the plan's §2.1 additions appended, and §2.2 as data.subtitles), then against mutants of them."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEST = ROOT / "tests" / "tmp" / "test_48_translate_instance_captions_phase2.py"
PHASE1 = (ROOT / "engine" / "server" / "api" / "handlers" / "internal_translate.py").read_text()

HANDLER = r'''

import sqlite3
from urllib.parse import quote

from data.db import statement_deadline
from data.moderation import list_active_denied_hosts, normalize_host
from data.subtitles import fetch_ready_subtitles, store_ready_subtitles
from data.time import now_ms
from handlers.video import resolve_video_row
from http_utils import read_json_body, respond_json
from server_config import DEFAULT_STATEMENT_TIMEOUT_SECONDS

SOURCE_INSTANCE = "instance"
REQUEST_BUDGET_SECONDS = 15.0
VIDEO_NOT_FOUND = {"error": "Video not found"}


def _stripped(value):
    return (value.strip() or None) if isinstance(value, str) else None


def fetch_instance_track(host, video_key):
    budget_at = time.monotonic() + REQUEST_BUDGET_SECONDS
    listing = fetch_bounded(host, f"/api/v1/videos/{quote(video_key, safe='')}/captions", budget_at)
    path = pick_english_track_path(listing, host) if listing is not None else None
    raw = fetch_bounded(host, path, budget_at) if path is not None else None
    if raw is None:
        return None
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    cues = parse_webvtt(text)
    return (text, cues) if cues is not None else None


def _cached_cues(server, video_id, instance_domain):
    lock = getattr(server, "subtitles_db_lock", None)
    if lock is None or getattr(server, "subtitles_db", None) is None:
        return None
    try:
        with lock:
            return fetch_ready_subtitles(server.subtitles_db, video_id, instance_domain, TARGET_LANGUAGE)
    except sqlite3.Error:
        return None


def _store_cues(server, video_id, instance_domain, track_text, cues):
    lock = getattr(server, "subtitles_db_lock", None)
    if lock is None or getattr(server, "subtitles_db", None) is None:
        return
    try:
        with statement_deadline(getattr(server, "statement_timeout_seconds", DEFAULT_STATEMENT_TIMEOUT_SECONDS)), lock:
            store_ready_subtitles(server.subtitles_db, video_id, instance_domain, TARGET_LANGUAGE, SOURCE_INSTANCE, track_text, cues, now_ms())
    except sqlite3.Error:
        pass


def handle_internal_translate(handler, server):
    try:
        body = read_json_body(handler)
    except ValueError as exc:
        respond_json(handler, 400, {"error": str(exc)})
        return True
    video_id = _stripped(body.get("id"))
    raw_host = _stripped(body.get("host"))
    if video_id is None or raw_host is None:
        respond_json(handler, 400, {"error": "Missing id or host"})
        return True
    host = normalize_host(raw_host)
    if host is None:
        respond_json(handler, 400, {"error": "Invalid host"})
        return True
    resolved = resolve_video_row(handler, server, {"id": [video_id], "host": [host]})
    if resolved is None:
        return True
    row = resolved[0]
    instance = row.get("instance_domain") or ""
    canonical_id = str(row.get("video_id") or "")
    with server.db_lock:
        denied = list_active_denied_hosts(server.db)
    if not instance or not canonical_id or normalize_host(instance) in denied:
        respond_json(handler, 404, VIDEO_NOT_FOUND)
        return True
    cues = _cached_cues(server, canonical_id, instance)
    if cues is None:
        fetched = fetch_instance_track(instance, str(row.get("video_uuid") or canonical_id))
        if fetched is None:
            respond_json(handler, 200, {"state": "none"})
            return True
        track_text, cues = fetched
        _store_cues(server, canonical_id, instance, track_text, cues)
    respond_json(handler, 200, {"state": "ready", "cues": cues})
    return True
'''

SUBTITLES = r'''
from __future__ import annotations

import json
import sqlite3
from pathlib import Path


def connect_subtitles_db(path):
    conn = sqlite3.connect(Path(path).as_posix(), check_same_thread=False, timeout=30.0)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_subtitles_schema(conn):
    with conn:
        conn.execute("CREATE TABLE IF NOT EXISTS subtitles (video_id TEXT NOT NULL, instance_domain TEXT NOT NULL, target_language TEXT NOT NULL, state TEXT NOT NULL, source TEXT NOT NULL, fetched_at INTEGER NOT NULL, track_text TEXT, cues_json TEXT, PRIMARY KEY (video_id, instance_domain, target_language))")


def fetch_ready_subtitles(conn, video_id, instance_domain, target_language):
    row = conn.execute("SELECT cues_json FROM subtitles WHERE video_id = ? AND instance_domain = ? AND target_language = ? AND state = 'ready'", (video_id, instance_domain, target_language)).fetchone()
    if row is None:
        return None
    try:
        cues = json.loads(row["cues_json"] or "")
    except (ValueError, RecursionError):
        return None
    return cues if isinstance(cues, list) and cues else None


def store_ready_subtitles(conn, video_id, instance_domain, target_language, source, track_text, cues, fetched_at):
    with conn:
        conn.execute("INSERT INTO subtitles (video_id, instance_domain, target_language, state, source, fetched_at, track_text, cues_json) VALUES (?, ?, ?, 'ready', ?, ?, ?, ?) ON CONFLICT(video_id, instance_domain, target_language) DO UPDATE SET state = excluded.state, source = excluded.source, fetched_at = excluded.fetched_at, track_text = excluded.track_text, cues_json = excluded.cues_json", (video_id, instance_domain, target_language, source, fetched_at, track_text, json.dumps(cues, ensure_ascii=False, separators=(",", ":"))))
'''

DENY_CHECK = "    if not instance or not canonical_id or normalize_host(instance) in denied:\n        respond_json(handler, 404, VIDEO_NOT_FOUND)\n        return True\n"
CACHE_READ = "    cues = _cached_cues(server, canonical_id, instance)\n"
# Each mutant: (file, old, new) edits.
MUTANTS = {
    "correct": [],
    "no denylist check": [("h", DENY_CHECK, "")],
    "denied answers none": [("h", "        respond_json(handler, 404, VIDEO_NOT_FOUND)\n        return True\n    cues", "        respond_json(handler, 200, {\"state\": \"none\"})\n        return True\n    cues")],
    "cache read before the denylist": [("h", DENY_CHECK + CACHE_READ, CACHE_READ + "    if cues is None and (not instance or not canonical_id or normalize_host(instance) in denied):\n        respond_json(handler, 404, VIDEO_NOT_FOUND)\n        return True\n")],
    "case-sensitive denylist query": [("h", "normalize_host(instance) in denied", "server.db.execute(\"SELECT 1 FROM instance_denylist WHERE is_active = 1 AND host = ?\", (instance,)).fetchone() is not None")],
    "fetch the request host": [("h", "fetch_instance_track(instance, ", "fetch_instance_track(raw_host, ")],
    "key on the request id": [("h", "cues = _cached_cues(server, canonical_id, instance)", "cues = _cached_cues(server, video_id, instance)"), ("h", "_store_cues(server, canonical_id, instance, track_text, cues)", "_store_cues(server, video_id, instance, track_text, cues)")],
    "never reads the store": [("h", CACHE_READ, "    cues = None\n")],
    "never writes the store": [("h", "        _store_cues(server, canonical_id, instance, track_text, cues)\n", "")],
    "in-memory cache instead of the store": [("h", CACHE_READ, "    cues = _MEMORY.get((canonical_id, instance))\n"), ("h", "        _store_cues(server, canonical_id, instance, track_text, cues)\n", "        _MEMORY[(canonical_id, instance)] = cues\n        _store_cues(server, canonical_id, instance, track_text, cues)\n"), ("h", "SOURCE_INSTANCE = \"instance\"\n", "SOURCE_INSTANCE = \"instance\"\n_MEMORY = {}\n")],
    "stores none too": [("h", "        if fetched is None:\n            respond_json(handler, 200, {\"state\": \"none\"})\n", "        if fetched is None:\n            with server.subtitles_db_lock, server.subtitles_db:\n                server.subtitles_db.execute(\"INSERT OR REPLACE INTO subtitles VALUES (?, ?, 'en', 'none', 'instance', 0, NULL, NULL)\", (canonical_id, instance))\n            respond_json(handler, 200, {\"state\": \"none\"})\n")],
    "padded cues_json": [("s", "json.dumps(cues, ensure_ascii=False, separators=(\",\", \":\"))", "json.dumps(cues, ensure_ascii=False)")],
    "parsed text stored as the track": [("h", "        _store_cues(server, canonical_id, instance, track_text, cues)\n", "        _store_cues(server, canonical_id, instance, \"\\n\".join(cue[\"text\"] for cue in cues), cues)\n")],
    "source not instance": [("h", "SOURCE_INSTANCE = \"instance\"", "SOURCE_INSTANCE = \"peertube\"")],
    "always none": [("h", "    respond_json(handler, 200, {\"state\": \"ready\", \"cues\": cues})\n", "    respond_json(handler, 200, {\"state\": \"none\"})\n")],
}

RUNNER = r'''
import importlib.util, sys
sys.path[:0] = [sys.argv[1], sys.argv[1] + "/api"]
import data, handlers
for name, path, parent, attr in (("data.subtitles", sys.argv[3], data, "subtitles"), ("handlers.internal_translate", sys.argv[2], handlers, "internal_translate")):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    setattr(parent, attr, module)
import pytest
sys.exit(pytest.main([sys.argv[4], "-q", "-p", "no:cacheprovider", "--no-header", "-rf", "--tb=line", "-k", "not engine_start"]))
'''


def test_standin(tmp_path):
    report = []
    for name, edits in MUTANTS.items():
        sources = {"h": PHASE1 + HANDLER, "s": SUBTITLES}
        for which, old, new in edits:
            assert old in sources[which], (name, old)
            sources[which] = sources[which].replace(old, new)
        handler_path = tmp_path / f"handler_{abs(hash(name))}.py"
        subtitles_path = tmp_path / f"subtitles_{abs(hash(name))}.py"
        handler_path.write_text(sources["h"])
        subtitles_path.write_text(sources["s"])
        run = subprocess.run([sys.executable, "-c", RUNNER, str(ROOT / "engine" / "server"), str(handler_path), str(subtitles_path), str(TEST)], capture_output=True, text=True, cwd=ROOT)
        lines = [line for line in run.stdout.splitlines() if line.strip()]
        report.append(f"== {name}: exit {run.returncode}: {lines[-1] if lines else run.stderr[-500:]}")
        report.extend("    " + line.split("::", 1)[-1][:220] for line in run.stdout.splitlines() if line.startswith("FAILED"))
        if name == "correct" and run.returncode != 0:
            report.append(run.stdout[-4000:] + run.stderr[-2000:])
    assert False, "\n".join(report)
