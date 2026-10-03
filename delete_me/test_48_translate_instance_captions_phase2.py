"""`handle_internal_translate` answers 404 `Video not found` with no instance fetch until the video resolves and its host is not denied, stores only a `ready` track in subtitles.db and serves it from there with no fetch; an Engine start creates that store at its configured path and routes `/internal/translate` behind the bridge gate. "translate" is plan 48's build identifier (the Translate toggle): the cues served are an English track the instance already holds.

Gate (`handle_internal_translate`, `fetch_bounded` recording every fetch):

- An unknown id, and a known uuid on a host it does not belong to, each answer exactly `404 {"error": "Video not found"}` with no fetch; the same server then fetches twice for the video that resolves.
- A video whose host is in the denylist, stored as `DENIED.EXAMPLE` and active, answers the same 404 with no fetch. With the row inactive the same request answers `ready`, fetched from `denied.example`, and stores a row; active again, it answers 404 with no further fetch, so the stored track is not served either.

Store (subtitles.db opened with `connect_subtitles_db` and `ensure_subtitles_schema`, as server.py does):

- A miss for uuid `u-1` requested as host `PEER.Example.` answers `ready` with the two cues the track parses to, sorted, markup stripped; both fetches (caption list and track) go to the row's `peer.example`.
- It stores exactly one row: `v-1` (the row's canonical id, not the requested uuid), `peer.example`, `en`, `ready`, `instance`, the original track text, and cues_json that loads to those cues with no whitespace.
- A fresh connection to that file answers the same cues by uuid and by canonical id with no further fetch; a server over an empty subtitles file fetches again, so those answers came from the file.
- No en track, a track with two-digit milliseconds, a failed caption-list fetch and a failed track fetch each answer exactly `{"state": "none"}` after fetching the caption list, and leave the table empty.

Startup: server.py run with `DEFAULT_SUBTITLES_DB_PATH` overridden to a missing file answers health, has created that file with a `subtitles` table, answers `/internal/translate` with the token for an unknown video `404 Video not found` (an Engine without the route answers `404 Not found`), and without the token 401.

The instance is stood in for at `internal_translate.fetch_bounded`, so the real caption pick and WebVTT parse run; the server is a `SimpleNamespace` over a temporary whitelist.db (videos, channels, instance_denylist) and a temporary subtitles.db, and the handler gets a stand-in for the stdlib request handler so the real body reader and responder run. Stored rows are read back through a separate read-only connection.
"""
from __future__ import annotations

import fcntl
import importlib
import io
import json
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
SERVER_DIR = ROOT / "engine" / "server"
API_DIR = SERVER_DIR / "api"
for _path in (SERVER_DIR, API_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

ENGINE_PY = ROOT / "engine" / ".pixi" / "envs" / "default" / "bin" / "python"
ENGINE_SERVER = API_DIR / "server.py"
# The lock tests/active/conftest.py serialises every Engine start on, so this start takes its turn with the session Engine's.
ENGINE_START_LOCK = Path(tempfile.gettempdir()) / "peertube-browser-engine-start.lock"
BRIDGE_TOKEN = "phase2-bridge-token"
HEALTHY_WITHIN_SECONDS = 120
STOP_WITHIN_SECONDS = 30
THRESHOLD = 3
HOST = "peer.example"
DENIED_HOST = "denied.example"
# (video_id, video_uuid, instance_domain): the uuid differs from the id, so a row keyed on the request id instead of the canonical one shows.
PEER_VIDEO = ("v-1", "u-1", HOST)
DENIED_VIDEO = ("d-1", "du-1", DENIED_HOST)
TRACK_PATH = "/lazy-static/video-captions/en.vtt"
TRACK = "WEBVTT\n\n00:03.000 --> 00:04.000\n<i>World</i>\n\n00:01.000 --> 00:02.500\nHello\n"
# TRACK parsed: sorted by start, markup stripped. No text holds a space, so any space in the stored cues_json is padding.
CUES = [{"start": 1.0, "end": 2.5, "text": "Hello"}, {"start": 3.0, "end": 4.0, "text": "World"}]
VIDEO_NOT_FOUND = [[404, {"error": "Video not found"}]]
NONE = [[200, {"state": "none"}]]
READY = [[200, {"state": "ready", "cues": CUES}]]
EN_LISTING = json.dumps({"total": 1, "data": [{"language": {"id": "en", "label": "English"}, "captionPath": TRACK_PATH}]}).encode("utf-8")
FR_LISTING = json.dumps({"total": 1, "data": [{"language": {"id": "fr", "label": "French"}, "captionPath": "/lazy-static/video-captions/fr.vtt"}]}).encode("utf-8")
# Each way the instance answers `none`: what its caption list and its track fetch return (None is a failed fetch).
NONE_PATHS = {
    "no en track": (FR_LISTING, TRACK.encode("utf-8")),
    "track fails to parse": (EN_LISTING, b"WEBVTT\n\n00:01.00 --> 00:02.000\nTwo-digit milliseconds\n"),
    "caption list fetch failed": (None, TRACK.encode("utf-8")),
    "track fetch failed": (EN_LISTING, None),
}


class Request:
    """The parts of a BaseHTTPRequestHandler that http_utils reads and writes: each send_response opens a [status, payload] response."""

    def __init__(self, body: dict) -> None:
        raw = json.dumps(body).encode("utf-8")
        self.headers = {"content-length": str(len(raw))}
        self.rfile = io.BytesIO(raw)
        self.responses: list[list] = []
        self.wfile = SimpleNamespace(write=lambda data: self.responses[-1].append(json.loads(data)))

    def send_response(self, status: int) -> None:
        self.responses.append([status])

    def send_header(self, name: str, value: str) -> None:
        pass

    def end_headers(self) -> None:
        pass


class Instance:
    """The video instances as `fetch_bounded` reaches them: each (host, path) answers its served bytes, any other None, and every fetch is recorded in order."""

    def __init__(self) -> None:
        self.routes: dict[tuple[str, str], bytes | None] = {}
        self.fetched: list[tuple[str, str]] = []

    def serve(self, video: tuple[str, str, str], listing: bytes | None, track: bytes | None) -> None:
        _, uuid, host = video
        self.routes[(host, f"/api/v1/videos/{uuid}/captions")] = listing
        self.routes[(host, TRACK_PATH)] = track

    def fetch_bounded(self, host: str, path: str, budget_at: float) -> bytes | None:
        self.fetched.append((host, path))
        return self.routes.get((host, path))

    def hosts(self) -> list[str]:
        return [host for host, _ in self.fetched]


def _translate(instance: Instance, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """The handler module, imported inside each test so that before phase 2 each test fails on its own; its fetch reaches the scripted instance."""
    module = importlib.import_module("handlers.internal_translate")
    monkeypatch.setattr(module, "fetch_bounded", instance.fetch_bounded)
    return module


def _whitelist(path: Path) -> sqlite3.Connection:
    """A whitelist.db holding PEER_VIDEO and DENIED_VIDEO, with an inactive denylist row for DENIED_HOST stored uppercase."""
    from data.moderation import ensure_moderation_schema

    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE videos (video_id TEXT, video_uuid TEXT, instance_domain TEXT, channel_id TEXT, channel_name TEXT, channel_url TEXT, account_name TEXT, account_url TEXT, title TEXT, description TEXT, embed_path TEXT, published_at TEXT, video_url TEXT, views INTEGER, likes INTEGER, dislikes INTEGER, tags_json TEXT, category TEXT, nsfw INTEGER, language TEXT, duration INTEGER, thumbnail_url TEXT, last_checked_at TEXT, error_count INTEGER, PRIMARY KEY (video_id, instance_domain))")
    conn.execute("CREATE TABLE channels (channel_id TEXT, instance_domain TEXT, channel_name TEXT, display_name TEXT, followers_count INTEGER, avatar_url TEXT)")
    ensure_moderation_schema(conn)
    for video_id, uuid, host in (PEER_VIDEO, DENIED_VIDEO):
        conn.execute("INSERT INTO videos (video_id, video_uuid, instance_domain, title, error_count) VALUES (?, ?, ?, ?, 0)", (video_id, uuid, host, f"title:{video_id}"))
    conn.execute("INSERT INTO instance_denylist (host, is_active, created_at, updated_at) VALUES (?, 0, 0, 0)", (DENIED_HOST.upper(),))
    conn.commit()
    return conn


def _set_denied(whitelist: sqlite3.Connection, active: bool) -> None:
    whitelist.execute("UPDATE instance_denylist SET is_active = ? WHERE host = ?", (int(active), DENIED_HOST.upper()))
    whitelist.commit()


def _subtitles_db(path: Path) -> sqlite3.Connection:
    """The subtitles store as server.py opens it at startup."""
    from data.subtitles import connect_subtitles_db, ensure_subtitles_schema

    conn = connect_subtitles_db(path)
    ensure_subtitles_schema(conn)
    return conn


def _server(whitelist: sqlite3.Connection, subtitles_path: Path) -> SimpleNamespace:
    """The server attributes the handler reads, over a fresh connection to the subtitles file at `subtitles_path`."""
    return SimpleNamespace(db=whitelist, db_lock=threading.Lock(), video_error_threshold=THRESHOLD, subtitles_db=_subtitles_db(subtitles_path), subtitles_db_lock=threading.Lock(), statement_timeout_seconds=5.0)


def _handle(module: ModuleType, server: SimpleNamespace, body: dict) -> list[list]:
    request = Request(body)
    module.handle_internal_translate(request, server)
    return request.responses


def _stored(subtitles_path: Path) -> list[tuple]:
    """Every subtitles row, read through a separate read-only connection."""
    conn = sqlite3.connect(f"file:{subtitles_path}?mode=ro", uri=True)
    try:
        return conn.execute("SELECT video_id, instance_domain, target_language, state, source, track_text, cues_json FROM subtitles ORDER BY video_id").fetchall()
    finally:
        conn.close()


@pytest.fixture
def whitelist(tmp_path) -> sqlite3.Connection:
    conn = _whitelist(tmp_path / "whitelist.db")
    yield conn
    conn.close()


@pytest.fixture
def instance() -> Instance:
    instance = Instance()
    instance.serve(PEER_VIDEO, EN_LISTING, TRACK.encode("utf-8"))
    instance.serve(DENIED_VIDEO, EN_LISTING, TRACK.encode("utf-8"))
    return instance


def test_an_unknown_video_is_404_video_not_found_with_no_fetch(tmp_path, whitelist, instance, monkeypatch):
    internal_translate = _translate(instance, monkeypatch)
    server = _server(whitelist, tmp_path / "subtitles.db")
    assert _handle(internal_translate, server, {"id": "no-such-video", "host": HOST}) == VIDEO_NOT_FOUND  # C1
    assert _handle(internal_translate, server, {"id": PEER_VIDEO[1], "host": "other.example"}) == VIDEO_NOT_FOUND  # C1: a known id on a host it does not belong to
    assert instance.fetched == []  # C1
    # Control: the same server and instance fetch for a video that resolves, so the empty list above is the gate's doing.
    assert _handle(internal_translate, server, {"id": PEER_VIDEO[1], "host": HOST}) == READY
    assert instance.hosts() == [HOST, HOST]


def test_a_denylisted_host_is_404_video_not_found_with_no_fetch_even_with_a_stored_track(tmp_path, whitelist, instance, monkeypatch):
    internal_translate = _translate(instance, monkeypatch)
    server = _server(whitelist, tmp_path / "subtitles.db")
    body = {"id": DENIED_VIDEO[1], "host": DENIED_HOST}
    _set_denied(whitelist, True)
    assert _handle(internal_translate, server, body) == VIDEO_NOT_FOUND  # C1: denylist row stored as DENIED.EXAMPLE
    assert instance.fetched == []  # C1
    # Control: with the row inactive the same request fetches from the video's host and stores a ready track.
    _set_denied(whitelist, False)
    assert _handle(internal_translate, server, body) == READY
    assert instance.hosts() == [DENIED_HOST, DENIED_HOST]
    assert [row[:2] for row in _stored(tmp_path / "subtitles.db")] == [DENIED_VIDEO[::2]]
    # Denied again, the stored track is not served and nothing more is fetched: the denylist is checked before the store and the network.
    _set_denied(whitelist, True)
    assert _handle(internal_translate, server, body) == VIDEO_NOT_FOUND  # C1
    assert instance.hosts() == [DENIED_HOST, DENIED_HOST]  # C1


def test_a_ready_track_is_fetched_from_the_row_host_stored_and_then_served_from_subtitles_db_without_a_fetch(tmp_path, whitelist, instance, monkeypatch):
    internal_translate = _translate(instance, monkeypatch)
    subtitles_path = tmp_path / "subtitles.db"
    # The request host differs from the row's `peer.example` in case and a trailing dot, so fetching the request host would show.
    body = {"id": PEER_VIDEO[1], "host": "PEER.Example."}
    assert _handle(internal_translate, _server(whitelist, subtitles_path), body) == READY  # C2
    assert instance.hosts() == [HOST, HOST]  # C2: the caption list and the track, both from the row's instance_domain
    (row,) = _stored(subtitles_path)
    # Keyed on the row's canonical video_id `v-1`, not the requested uuid `u-1`; the original track text, markup and order included.
    assert row[:6] == ("v-1", HOST, "en", "ready", "instance", TRACK)  # C2
    assert json.loads(row[6]) == CUES  # C2
    assert " " not in row[6] and "\n" not in row[6], row[6]  # C2: compact
    # A fresh connection to the same file, as after a restart: the uuid request and the canonical-id request both answer the stored cues with no fetch.
    reopened = _server(whitelist, subtitles_path)
    assert _handle(internal_translate, reopened, body) == READY  # C2
    assert _handle(internal_translate, reopened, {"id": PEER_VIDEO[0], "host": HOST}) == READY  # C2
    assert len(instance.fetched) == 2  # C2
    # Control: a server over an empty subtitles file fetches again, so the answers above came from what subtitles.db holds, not from process memory.
    assert _handle(internal_translate, _server(whitelist, tmp_path / "empty-subtitles.db"), body) == READY
    assert instance.hosts() == [HOST] * 4


@pytest.mark.parametrize("listing, track", NONE_PATHS.values(), ids=NONE_PATHS.keys())
def test_each_none_path_answers_none_and_stores_nothing(tmp_path, whitelist, monkeypatch, listing, track):
    instance = Instance()
    instance.serve(PEER_VIDEO, listing, track)
    internal_translate = _translate(instance, monkeypatch)
    subtitles_path = tmp_path / "subtitles.db"
    assert _handle(internal_translate, _server(whitelist, subtitles_path), {"id": PEER_VIDEO[1], "host": HOST}) == NONE  # C2
    assert instance.fetched[0] == (HOST, f"/api/v1/videos/{PEER_VIDEO[1]}/captions")  # control: the answer came from the instance, past the gate
    assert _stored(subtitles_path) == []  # C2


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _post(base: str, path: str, body: dict, headers: dict[str, str]) -> tuple[int, object]:
    req = urllib.request.Request(base + path, data=json.dumps(body).encode("utf-8"), method="POST", headers={"content-type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


# Runs server.py as __main__ with `server_config` bound to the real file's module and the overrides set on it, as test_random_cache.py's CACHE_VARIANT_RUNNER does.
VARIANT_RUNNER = """
import importlib.util, json, os, runpy, sys
server, overrides = sys.argv[1], json.loads(sys.argv[2])
api = os.path.dirname(server)
sys.path.insert(0, api)
sys.path.insert(0, os.path.dirname(api))
spec = importlib.util.spec_from_file_location("server_config", os.path.join(api, "server_config.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
for name, value in overrides.items():
    setattr(module, name, value)
sys.modules["server_config"] = module
sys.argv = [server, *sys.argv[3:]]
runpy.run_path(server, run_name="__main__")
"""


def test_an_engine_start_creates_the_subtitles_table_at_its_configured_path_and_routes_internal_translate_behind_the_bridge_gate(tmp_path):
    assert ENGINE_PY.exists(), f"Engine interpreter missing at {ENGINE_PY}; run `pixi install` in engine/"
    subtitles_path = tmp_path / "subtitles.db"
    assert not subtitles_path.exists()  # control: only the start can create it
    env = {**os.environ, "ENGINE_INGEST_MODE": "bridge", "ENGINE_BRIDGE_TOKEN": BRIDGE_TOKEN}
    log_path = tmp_path / "engine.log"
    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    with open(log_path, "w") as log:
        with open(ENGINE_START_LOCK, "w") as start_lock:
            fcntl.flock(start_lock, fcntl.LOCK_EX)
            proc = subprocess.Popen([str(ENGINE_PY), "-c", VARIANT_RUNNER, str(ENGINE_SERVER), json.dumps({"DEFAULT_SUBTITLES_DB_PATH": str(subtitles_path)}), "--host", "127.0.0.1", "--port", str(port), "--no-random-cache-refresh"], env=env, stdout=log, stderr=log)
            healthy = False
            deadline = time.time() + HEALTHY_WITHIN_SECONDS
            while proc.poll() is None and time.time() < deadline and not healthy:
                try:
                    with urllib.request.urlopen(base + "/api/health", timeout=5) as resp:
                        healthy = resp.status == 200
                except OSError:
                    time.sleep(0.1)
    try:
        assert healthy, f"the variant Engine did not answer /api/health 200 within {HEALTHY_WITHIN_SECONDS}s (exit {proc.poll()}); see {log_path}"
        assert subtitles_path.exists(), f"the Engine start did not create {subtitles_path}"
        conn = sqlite3.connect(f"file:{subtitles_path}?mode=ro", uri=True)
        try:
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        finally:
            conn.close()
        assert "subtitles" in tables, tables
        # An Engine without the route falls through to 404 {"error": "Not found"}; this video and host resolve to no row, so the handler answers before any fetch.
        assert _post(base, "/internal/translate", {"id": "no-such-video", "host": "no-such-host.invalid"}, {"X-Bridge-Token": BRIDGE_TOKEN}) == (404, {"error": "Video not found"})  # C1
        assert _post(base, "/internal/translate", {"id": "no-such-video", "host": "no-such-host.invalid"}, {}) == (401, {"error": "Unauthorized"})  # behind the bridge gate
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=STOP_WITHIN_SECONDS)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
