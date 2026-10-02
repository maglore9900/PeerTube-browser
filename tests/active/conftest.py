"""A real Client backend on an ephemeral port, over a users.db under tmp_path.

`client_backend` points the Client at a closed Engine port: the profile routes its tests
drive either never call the Engine or refuse before they would.

`engine` starts the real Engine from its pixi env on the repo's dataset, once per session,
the way `tests/run-arch-split-smoke.sh` does; `engine_client` is a Client wired to it with a
shared bridge token, and `unpublished_client` the same Client publishing no events; `dataset`
is `whitelist.db` opened read-only, the independent source of what a video's channel, account
and embedding are.

`exclude_entries`, `upnext_pool` and `pin_upnext` are plain helpers that pin an up-next page to a fixed set of its seed's pool with `exclude`, so it is served whole, not drawn.
"""
from __future__ import annotations

import fcntl
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
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ENGINE_PY = ROOT / "engine" / ".pixi" / "envs" / "default" / "bin" / "python"
ENGINE_SERVER = ROOT / "engine" / "server" / "api" / "server.py"
WHITELIST_DB = ROOT / "engine" / "server" / "db" / "whitelist.db"
BRIDGE_TOKEN = "active-suite-bridge-token"

BACKEND_DIR = ROOT / "client" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import server as client_server  # noqa: E402
from lib.http_utils import RateLimiter  # noqa: E402
from lib.users_store import ensure_user_schema  # noqa: E402

CLOSED_ENGINE = "http://127.0.0.1:9"


@dataclass
class ClientBackend:
    base: str
    db_path: Path

    def request(self, method: str, path: str, headers: dict[str, str] | None = None,
                body: dict | None = None) -> tuple[int, object]:
        """Send one request; return the status and the parsed JSON body (or None)."""
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method)
        req.add_header("content-type", "application/json")
        for name, value in (headers or {}).items():
            req.add_header(name, value)
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                raw = resp.read()
                status = resp.status
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            status = exc.code
        return status, (json.loads(raw) if raw else None)


@pytest.fixture
def client_backend(tmp_path):
    db_path = tmp_path / "users.db"
    conn = client_server.connect_db(db_path)
    ensure_user_schema(conn)
    srv = client_server.ClientBackendServer(
        ("127.0.0.1", 0),
        client_server.ClientBackendHandler,
        conn,
        CLOSED_ENGINE,
        "bridge",
        RateLimiter(1000, 60),
    )
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield ClientBackend(f"http://127.0.0.1:{srv.server_address[1]}", db_path)
    finally:
        srv.shutdown()
        srv.server_close()
        conn.close()


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


ENGINE_START_ATTEMPTS = 5
# Shared by every lane's pytest process on this machine, so their Engine starts take turns.
ENGINE_START_LOCK = Path(tempfile.gettempdir()) / "peertube-browser-engine-start.lock"


@pytest.fixture(scope="session")
def engine(tmp_path_factory):
    log_path = tmp_path_factory.mktemp("engine") / "engine.log"
    log = open(log_path, "w")
    # Debug is off by default; the profile tests read `debug.profile`, so the session Engine opts in.
    env = {**os.environ, "ENGINE_INGEST_MODE": "bridge", "ENGINE_BRIDGE_TOKEN": BRIDGE_TOKEN, "RECOMMENDATIONS_DEBUG": "1"}
    proc = None
    try:
        # No start writes random-cache.db before listening: builds run in a background worker into a per-pid temp file that is renamed in, and with --no-random-cache-refresh a start on a usable cache runs no startup build.
        # Starts across lanes are serialised up to healthy as a guard against concurrent starts; a start that still exits is retried.
        with open(ENGINE_START_LOCK, "w") as start_lock:
            fcntl.flock(start_lock, fcntl.LOCK_EX)
            for attempt in range(ENGINE_START_ATTEMPTS):
                port = _free_port()
                proc = subprocess.Popen(
                    [str(ENGINE_PY), str(ENGINE_SERVER), "--host", "127.0.0.1", "--port", str(port),
                     "--no-random-cache-refresh"],
                    env=env, stdout=log, stderr=log,
                )
                http = ClientBackend(f"http://127.0.0.1:{port}", log_path)
                deadline = time.time() + 120
                while proc.poll() is None and time.time() < deadline:
                    try:
                        if http.request("GET", "/api/health")[0] == 200:
                            break
                    except OSError:
                        pass
                    time.sleep(0.25)
                else:
                    assert proc.poll() is not None, "Engine not healthy within 120s"
                    time.sleep(1 + attempt)
                    continue
                break
        assert proc.poll() is None, f"Engine exited on every start; see {log_path}"
        yield http
    finally:
        if proc is not None and proc.poll() is None:
            proc.terminate()
            proc.wait(timeout=30)
        log.close()


@pytest.fixture
def engine_client(tmp_path, engine, monkeypatch):
    yield from _engine_client(tmp_path, engine, monkeypatch, "bridge")


@pytest.fixture
def unpublished_client(tmp_path, engine, monkeypatch):
    """A Client wired to the Engine that publishes no interaction events.

    Its publish mode is `activitypub`, which is not implemented and sends nothing, so like and
    un-like actions leave no Like/UndoLike rows in the repo's live whitelist.db. Such an
    action is answered 502 after its profile state is stored.
    """
    yield from _engine_client(tmp_path, engine, monkeypatch, "activitypub")


def _engine_client(tmp_path, engine, monkeypatch, publish_mode):
    monkeypatch.setenv("ENGINE_BRIDGE_TOKEN", BRIDGE_TOKEN)
    db_path = tmp_path / "users.db"
    conn = client_server.connect_db(db_path)
    ensure_user_schema(conn)
    srv = client_server.ClientBackendServer(
        ("127.0.0.1", 0),
        client_server.ClientBackendHandler,
        conn,
        engine.base,
        publish_mode,
        RateLimiter(100000, 60),
    )
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield ClientBackend(f"http://127.0.0.1:{srv.server_address[1]}", db_path)
    finally:
        srv.shutdown()
        srv.server_close()
        conn.close()


@pytest.fixture(scope="session")
def dataset():
    conn = sqlite3.connect(f"file:{WHITELIST_DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


BRIDGE_HEADERS = {"X-Bridge-Token": BRIDGE_TOKEN}
# The pinning helpers' own Engine rate bucket: a TEST-NET-1 address no test uses, so listing never spends a test's 127.0.0.1 budget.
# rat-tail: one bucket per process caps listing and pinning at 60 requests a minute per route; a per-module header or a pin cache is the way up if a file pins many seeds.
UPNEXT_PIN_HEADERS = {"X-Client-IP": "192.0.2.150"}
# The Engine's limit cap, default_limit * 2 (similar.py `_handle_similar`).
UPNEXT_LIST_LIMIT = 96
# DEFAULT_CLIENT_EXCLUDE_MAX on the Engine, MAX_FEED_EXCLUDE on the Client.
UPNEXT_EXCLUDE_CAP = 500
# Enough 96-row pages to list 500 rows, plus the empty page that ends a listing.
UPNEXT_LIST_PAGES = -(-UPNEXT_EXCLUDE_CAP // UPNEXT_LIST_LIMIT) + 1
UPNEXT_PIN_TRIES = 3
# Seeded, so the rows each excluding step serves do not depend on a fresh draw.
UPNEXT_LIST_SEED = 0
# One listing per (route, seed video) per pytest process; never kept across processes, since the shared similarity cache can move between runs.
_UPNEXT_POOLS: dict[tuple[str, str, str], list[dict]] = {}


def embedding_of(dataset, video_id: str, instance_domain: str) -> list[float]:
    """The unit-length embedding whitelist.db holds for one video."""
    from array import array

    row = dataset.execute(
        "SELECT embedding FROM video_embeddings WHERE video_id = ? AND instance_domain = ?",
        (video_id, instance_domain),
    ).fetchone()
    assert row is not None, f"{video_id}@{instance_domain} has no embedding"
    vector = array("f", row["embedding"]).tolist()
    norm = sum(x * x for x in vector) ** 0.5
    return [x / norm for x in vector]


def cosine(a: list[float], b: list[float]) -> float:
    """Cosine of two vectors, neither assumed unit-length."""
    dot = sum(x * y for x, y in zip(a, b))
    return dot / ((sum(x * x for x in a) ** 0.5) * (sum(y * y for y in b) ** 0.5))


def closeness(dataset, rows: list[dict], video: dict) -> float:
    """Mean cosine between a page's rows and one video, from whitelist.db embeddings."""
    target = embedding_of(dataset, video["video_id"], video["instance_domain"])
    sims = [cosine(embedding_of(dataset, r["video_id"], r["instance_domain"]), target) for r in rows]
    assert sims, "closeness of an empty page"
    return sum(sims) / len(sims)


def identity_of(dataset, video_id: str, instance_domain: str) -> dict[str, str]:
    """The channel_id and account_url whitelist.db holds for one video."""
    row = dataset.execute(
        "SELECT channel_id, account_url FROM videos WHERE video_id = ? AND instance_domain = ?",
        (video_id, instance_domain),
    ).fetchone()
    assert row is not None, f"{video_id}@{instance_domain} not in whitelist.db"
    return {"channel_id": row["channel_id"], "account_url": row["account_url"]}


def exclude_entries(rows) -> list[dict[str, str]]:
    """The `exclude` body entries naming these rows."""
    return [{"id": r["video_id"], "host": r["instance_domain"]} for r in rows]


def _upnext_key(row: dict) -> tuple[str, str]:
    return (row["video_id"], row["instance_domain"])


def _upnext_page(engine, route: str, seed: dict, exclude: list[dict[str, str]]) -> list[dict]:
    """One seeded, debug, 96-row up-next page on the Engine, on the helpers' own rate bucket."""
    path = f"{route}?id={seed['video_uuid']}&host={seed['instance_domain']}&limit={UPNEXT_LIST_LIMIT}&seed={UPNEXT_LIST_SEED}&debug=1"
    status, body = engine.request("POST", path, headers=UPNEXT_PIN_HEADERS, body={"exclude": exclude})
    assert status == 200, (route, status, body)
    return body["rows"]


def upnext_pool(engine, route: str, seed: dict) -> list[dict]:
    """Every row of a seed's up-next pool on `route`, head first by debug similarity_score; listed once per process, not to be mutated."""
    cache_key = (route, seed["video_uuid"], seed["instance_domain"])
    if cache_key in _UPNEXT_POOLS:
        return _UPNEXT_POOLS[cache_key]
    listed: dict[tuple[str, str], dict] = {}
    for _ in range(UPNEXT_LIST_PAGES):
        assert len(listed) <= UPNEXT_EXCLUDE_CAP, f"{route} pool of {cache_key[1:]} at seed={UPNEXT_LIST_SEED}: {len(listed)} rows listed, past the {UPNEXT_EXCLUDE_CAP}-entry exclude cap"
        page = _upnext_page(engine, route, seed, exclude_entries(listed.values()))
        if not page:
            break
        listed.update((_upnext_key(r), r) for r in page)
    else:
        raise AssertionError(f"{route} pool of {cache_key[1:]} at seed={UPNEXT_LIST_SEED}: no empty page within {UPNEXT_LIST_PAGES} pages, {len(listed)} rows listed")
    # Head first: a draw can put a tail row first, and a tail row may not survive the wider fallback a narrow pin runs.
    pool = sorted(listed.values(), key=lambda r: (-r["debug"]["similarity_score"], _upnext_key(r)))
    _UPNEXT_POOLS[cache_key] = pool
    return pool


def pin_upnext(engine, route: str, seed: dict, chosen: list[dict]) -> list[dict[str, str]]:
    """The `exclude` entries under which an up-next request at limit >= len(chosen) is served exactly `chosen`, checked on the Engine."""
    want = {_upnext_key(r) for r in chosen}
    excluded = [r for r in upnext_pool(engine, route, seed) if _upnext_key(r) not in want]
    extra: set[tuple[str, str]] = set()
    for _ in range(UPNEXT_PIN_TRIES + 1):
        assert len(excluded) <= UPNEXT_EXCLUDE_CAP, f"{route} pin of {seed['video_uuid']}: {len(excluded)} exclude entries, past the {UPNEXT_EXCLUDE_CAP}-entry cap"
        served = {_upnext_key(r): r for r in _upnext_page(engine, route, seed, exclude_entries(excluded))}
        missing, extra = want - served.keys(), served.keys() - want
        assert not missing, f"{route} pin of {seed['video_uuid']}: chosen rows not served {sorted(missing)}, extra rows served {sorted(extra)}"
        if not extra:
            return exclude_entries(excluded)
        # A narrower pool runs the fallback further and can surface rows the listing never reached.
        excluded += [served[k] for k in sorted(extra)]
    raise AssertionError(f"{route} pin of {seed['video_uuid']}: extra rows still served after {UPNEXT_PIN_TRIES} widenings {sorted(extra)}")
