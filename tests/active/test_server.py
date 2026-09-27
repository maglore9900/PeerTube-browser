"""The Client backend carries a browser's `exclude` to the Engine, keyed profiles included, and
caps it at 500 entries.

- A keyed home request, for a profile holding five likes and four dislikes (so the Client rewrites
  the body with the profile's likes and taste vectors), carrying 500 `exclude` entries - a
  previous keyed page's rows, topped up with the dataset's longest-host videos to over 50 KB of
  `exclude` alone - is answered 200 with a home page holding none of them, where the same
  request without `exclude` repeats rows of that page.
- The Client answers 400 `Invalid exclude payload` to 501 entries, and passes 500 on to the
  Engine (a closed port here, so 502).

The keyed Client is the `unpublished_client` fixture.

The client address (`TRUSTED_PROXIES`, `resolve_client_address`, and what the limiters and the
Engine request are keyed on):

- `parse_trusted_proxies` returns exactly the listed networks, in order, with whitespace and stray
  commas ignored; a value listing nothing is the `127.0.0.1,::1` default.
- `main()` given a malformed `TRUSTED_PROXIES` entry raises `SystemExit` naming it, before it swaps
  the signal handlers or opens `users.db`, so before it binds.
- Behind a trusted peer, `X-Forwarded-For` hops are walked right to left, trusted ones skipped,
  and the first untrusted hop is returned, stripped and canonical; a chain trusted end to end gives
  its leftmost hop. IPv4-mapped v6 addresses are judged by the v4 address they carry. An untrusted
  peer, an unparseable peer, or a trusted peer whose last hop is empty or not an IP gives the peer,
  as it was passed. A configured set replaces the loopback default.
- Over live HTTP from 127.0.0.1, the per-route limiter and the profile-mint limiter bucket by the
  last untrusted hop: requests differing only in their first hop, or in a trusted hop appended
  after it, share a bucket, and a different last untrusted hop gets its own.
- The `x-client-ip` the Engine receives is that resolved address, not the forgeable first hop nor
  a trusted last hop; with no `X-Forwarded-For` it is the peer, whatever `X-Real-IP` claims.

Published interaction events (`/api/user-action`): a profile's action publishes a Like or UndoLike
only when it opens or closes the profile's like of the video, and every event's id is `client-`
plus the SHA-256 of the JSON list [actor, uuid, host, event type, like generation]:

- Two likes of one video by one profile publish one Like, at generation 1, and the video's signal
  is (1, 1.0).
- like, undo_like, like publishes Like, UndoLike, Like at generations 1, 1 and 2; the two Like ids
  differ and the signal ends at (1, 1.0).
- Two anonymous likes both publish the Like id for actor `anonymous` at generation 0; the Engine
  counts the second as a duplicate and the signal is (1, 1.0).
- A like naming the video by an upper-case uuid and a mixed-case host publishes the id over the
  uuid and host the Engine resolved them to, not over the spelling sent.
- undo_like of a video the profile never liked answers 200 and publishes nothing; a like afterwards
  publishes at generation 1.
- A dislike replacing a like publishes the UndoLike id an undo_like would have used (generation 1)
  and leaves (0, 0.0); a dislike, and an undo_dislike, of a video the profile does not like publish
  nothing.
- like, reset, like publishes one Like, though the re-like is stored; the undo_like after it
  publishes that Like's UndoLike and leaves (0, 0.0).
- undo_like of an imported like publishes nothing, though the import stored the like and the undo
  removed it; a like afterwards publishes at generation 1.

Those run a real Client backend in bridge mode against a stub Engine: resolve and metadata answer
the video lower-cased as its canonical identity, centroids are empty, and ingest runs the real
`ingest_interaction_event` on a tmp engine.db, recording each payload and result.
"""
from __future__ import annotations

import hashlib
import json
import signal
import socket
import sqlite3
import sys
import threading
import urllib.error
import urllib.request
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import ip_network
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote
from uuid import uuid4

import pytest
from conftest import CLOSED_ENGINE, ClientBackend, RateLimiter, client_server, ensure_user_schema

# The Engine dirs go on sys.path after conftest's import: both trees hold a `server` module.
ENGINE_SERVER_DIR = Path(__file__).resolve().parents[2] / "engine" / "server"
for _path in (ENGINE_SERVER_DIR, ENGINE_SERVER_DIR / "api"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))
from data.interaction_events import ensure_interaction_event_schema, ingest_interaction_event  # noqa: E402

EXCLUDE_CAP = 500
EVENT_HOST = "ids.example"
LOOPBACK = (ip_network("127.0.0.1/32"), ip_network("::1/128"))


def _mint(client) -> dict[str, str]:
    status, body = client.request("POST", "/api/profile")
    assert status == 201, body
    return {"X-Profile-Key": body["key"]}


def _search(client, query: str, n: int) -> list[dict]:
    status, body = client.request("GET", f"/api/v1/search/videos?q={quote(query)}&limit={n}")
    assert status == 200 and len(body["rows"]) == n, body
    return body["rows"]


def _home(client, headers, body: dict) -> list[dict]:
    status, payload = client.request("POST", "/recommendations", headers=headers, body=body)
    assert status == 200, payload
    assert payload["seed"].get("mode") == "home" and not payload["seed"].get("random"), payload["seed"]
    return payload["rows"]


def _keys(rows: list[dict]) -> set[tuple[str, str]]:
    return {(r["video_id"], r["instance_domain"]) for r in rows}


def _longest_host_entries(dataset, n: int, skip: set[tuple[str, str]]) -> list[dict]:
    rows = dataset.execute(
        "SELECT video_id, instance_domain FROM videos ORDER BY length(instance_domain) DESC LIMIT ?",
        (n + len(skip),),
    ).fetchall()
    entries = [{"id": r["video_id"], "host": r["instance_domain"]} for r in rows
               if (r["video_id"], r["instance_domain"]) not in skip]
    return entries[:n]


def test_a_keyed_request_s_500_entry_exclude_reaches_the_engine_and_none_of_it_is_returned(
        unpublished_client, dataset):
    client = unpublished_client
    key = _mint(client)
    liked = {(row["video_uuid"], row["instance_domain"]) for row in _search(client, "linux", 5)}
    for uuid, host in liked:
        # 502: the like is stored, then its Like event cannot be published in this mode.
        client.request("POST", "/api/user-action", headers=key, body={"action": "like", "uuid": uuid, "host": host})
    status, body = client.request("GET", "/api/user-profile/likes", headers=key)
    assert status == 200, body
    assert {(r["video_uuid"], r["instance_domain"]) for r in body["likes"]} == liked  # the profile holds the likes
    # Four dislikes give the four taste vectors (min(4, n)) that make the Engine's body largest.
    for disliked in _search(client, "cooking", 4):
        status, body = client.request("POST", "/api/user-action", headers=key,
                                      body={"action": "dislike", "uuid": disliked["video_uuid"],
                                            "host": disliked["instance_domain"]})
        assert status == 200, body  # control: the dislike and its taste vectors are stored

    previous = _home(client, key, {})
    plain = _home(client, key, {})
    assert _keys(previous) & _keys(plain), "control: a plain keyed page repeats none of the previous one"

    exclude = [{"id": v, "host": h} for v, h in _keys(previous)]
    exclude += _longest_host_entries(dataset, EXCLUDE_CAP - len(exclude), _keys(previous))
    assert len(exclude) == EXCLUDE_CAP
    # control: with the ~16 KB of four taste vectors the Client adds, the Engine's body passes 64 KB
    assert len(json.dumps({"exclude": exclude})) > 50_000

    page = _home(client, key, {"exclude": exclude})  # C1: 200, a home page

    excluded = {(e["id"], e["host"]) for e in exclude}
    assert page, "the page is empty"  # C1
    assert not _keys(page) & excluded, sorted(_keys(page) & excluded)  # C1


def test_the_client_refuses_501_exclude_entries_and_passes_500_on_to_the_engine(client_backend, dataset):
    rows = dataset.execute("SELECT video_id, instance_domain FROM videos LIMIT ?", (EXCLUDE_CAP + 1,)).fetchall()
    entries = [{"id": r["video_id"], "host": r["instance_domain"]} for r in rows]

    status, body = client_backend.request("POST", "/recommendations", body={"exclude": entries[:EXCLUDE_CAP]})
    assert status == 502, body  # C2: past validation, to the (closed) Engine

    status, body = client_backend.request("POST", "/recommendations", body={"exclude": entries})
    assert (status, body.get("error")) == (400, "Invalid exclude payload"), body  # C2


def test_a_single_range_parses_to_exactly_that_network():
    assert client_server.parse_trusted_proxies("10.0.0.0/8") == (ip_network("10.0.0.0/8"),)


def test_bare_v4_and_v6_addresses_parse_to_host_networks():
    # Off the default, and v6 before v4 so a parse that sorts its output fails too.
    assert client_server.parse_trusted_proxies("2001:db8::1,192.0.2.7") == (ip_network("2001:db8::1/128"), ip_network("192.0.2.7/32"))


def test_whitespace_and_stray_commas_are_tolerated():
    parsed = client_server.parse_trusted_proxies(" 10.0.0.0/8 ,, 192.0.2.1 , 2001:db8::/32,")
    assert parsed == (ip_network("10.0.0.0/8"), ip_network("192.0.2.1/32"), ip_network("2001:db8::/32"))


@pytest.mark.parametrize("value", ["", "  ", ",", " , "])
def test_a_value_listing_no_entries_is_the_loopback_default(value):
    assert client_server.parse_trusted_proxies(value) == LOOPBACK


@pytest.fixture
def startup(monkeypatch, tmp_path):
    """main() pointed at a port held by a listener here, so a startup that gets as far as binding fails instead of serving forever; yields the users.db directory it would create."""
    held = socket.socket()
    held.bind(("127.0.0.1", 0))
    held.listen()
    # A valid argv, so argparse cannot be the SystemExit.
    monkeypatch.setattr(sys, "argv", ["server.py", "--host", "127.0.0.1", "--port", str(held.getsockname()[1])])
    # Keeps a startup that gets past the check off the real users.db.
    monkeypatch.setattr(client_server, "ROOT_DIR", tmp_path)
    before = (signal.getsignal(signal.SIGINT), signal.getsignal(signal.SIGTERM))
    try:
        yield (tmp_path / client_server.DEFAULT_USERS_DB_PATH).parent
    finally:
        # A startup that failed at bind leaves its handlers installed in this process.
        signal.signal(signal.SIGINT, before[0])
        signal.signal(signal.SIGTERM, before[1])
        held.close()


def test_a_valid_value_gets_main_as_far_as_swapping_signals_and_creating_the_db(startup, monkeypatch):
    # Control: proves the two absences in the malformed-entry test would be seen if startup got past the check.
    monkeypatch.setenv("TRUSTED_PROXIES", "127.0.0.1, 10.0.0.0/8")
    before = (signal.getsignal(signal.SIGINT), signal.getsignal(signal.SIGTERM))
    with pytest.raises(OSError):
        client_server.main()
    assert (signal.getsignal(signal.SIGINT), signal.getsignal(signal.SIGTERM)) != before
    assert startup.is_dir()


@pytest.mark.parametrize("entry", ["10.0.0.0/33", "not-an-ip", "300.1.1.1"])
def test_a_malformed_entry_stops_main_naming_it_before_signals_or_the_db(entry, startup, monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXIES", f"127.0.0.1, {entry}")
    before = (signal.getsignal(signal.SIGINT), signal.getsignal(signal.SIGTERM))
    with pytest.raises(SystemExit) as exc:
        client_server.main()
    assert entry in str(exc.value.code)
    assert (signal.getsignal(signal.SIGINT), signal.getsignal(signal.SIGTERM)) == before
    assert not startup.exists()


def test_a_trusted_peer_resolves_to_the_rightmost_hop_not_the_forgeable_leftmost():
    assert client_server.resolve_client_address("127.0.0.1", "6.6.6.6, 203.0.113.9", client_server.DEFAULT_TRUSTED_PROXY_NETWORKS) == "203.0.113.9"


def test_the_trusted_set_decides_which_hops_are_skipped():
    trusted = client_server.parse_trusted_proxies("127.0.0.1,10.0.0.5")
    assert client_server.resolve_client_address("127.0.0.1", "203.0.113.9, 10.0.0.5", trusted) == "203.0.113.9"
    # The same chain under the default, where 10.0.0.5 is an untrusted hop and so the answer.
    assert client_server.resolve_client_address("127.0.0.1", "203.0.113.9, 10.0.0.5", client_server.DEFAULT_TRUSTED_PROXY_NETWORKS) == "10.0.0.5"


def test_a_chain_trusted_end_to_end_resolves_to_its_leftmost_hop():
    trusted = client_server.parse_trusted_proxies("127.0.0.1,10.0.0.0/8")
    # Three hops, so neither the peer, the rightmost nor the second hop can pass for the leftmost.
    assert client_server.resolve_client_address("127.0.0.1", "10.0.0.7, 10.0.0.6, 10.0.0.5", trusted) == "10.0.0.7"


def test_ipv4_mapped_addresses_are_judged_by_the_v4_address_they_carry():
    trusted = client_server.DEFAULT_TRUSTED_PROXY_NETWORKS
    assert client_server.resolve_client_address("::ffff:127.0.0.1", "203.0.113.9", trusted) == "203.0.113.9"
    assert client_server.resolve_client_address("127.0.0.1", "203.0.113.9, ::ffff:127.0.0.1", trusted) == "203.0.113.9"
    # Unmapping is for the trust check only: the untrusted peer is not handed back as 198.51.100.7.
    assert client_server.resolve_client_address("::ffff:198.51.100.7", "203.0.113.9", trusted) == "::ffff:198.51.100.7"


def test_a_returned_peer_is_not_canonicalised():
    # Unlike an accepted hop, which comes back as 2001:db8::7.
    assert client_server.resolve_client_address("2001:DB8:0::7", "203.0.113.9", client_server.DEFAULT_TRUSTED_PROXY_NETWORKS) == "2001:DB8:0::7"
    # 0:0:0:0:0:0:0:1 is ::1, so it is trusted and walks to a good hop; that puts the next assertion on the bad-last-hop fallback, not the untrusted early return.
    assert client_server.resolve_client_address("0:0:0:0:0:0:0:1", "203.0.113.9", client_server.DEFAULT_TRUSTED_PROXY_NETWORKS) == "203.0.113.9"
    assert client_server.resolve_client_address("0:0:0:0:0:0:0:1", "6.6.6.6, not-an-ip", client_server.DEFAULT_TRUSTED_PROXY_NETWORKS) == "0:0:0:0:0:0:0:1"


def test_an_accepted_v6_hop_comes_back_canonical():
    assert client_server.resolve_client_address("127.0.0.1", "6.6.6.6, 2001:DB8:0:0::1 ", client_server.DEFAULT_TRUSTED_PROXY_NETWORKS) == "2001:db8::1"


@pytest.mark.parametrize("forwarded_for", ["", "203.0.113.9", "6.6.6.6, 203.0.113.9", "203.0.113.9, 127.0.0.1"])
def test_an_untrusted_peer_resolves_to_itself_whatever_it_forwards(forwarded_for):
    assert client_server.resolve_client_address("198.51.100.7", forwarded_for, client_server.DEFAULT_TRUSTED_PROXY_NETWORKS) == "198.51.100.7"


@pytest.mark.parametrize("forwarded_for", ["", "   ", "6.6.6.6, not-an-ip", "6.6.6.6, ", "unknown"])
def test_a_trusted_peer_whose_last_hop_is_empty_or_not_an_ip_resolves_to_itself(forwarded_for):
    # 6.6.6.6 sits left of a bad last hop, so a walk that skips the bad hop instead of stopping returns it.
    assert client_server.resolve_client_address("127.0.0.1", forwarded_for, client_server.DEFAULT_TRUSTED_PROXY_NETWORKS) == "127.0.0.1"


def test_an_unparseable_peer_resolves_to_itself():
    assert client_server.resolve_client_address("unknown", "203.0.113.9", client_server.DEFAULT_TRUSTED_PROXY_NETWORKS) == "unknown"


def test_a_configured_range_replaces_the_loopback_default():
    trusted = client_server.parse_trusted_proxies("10.0.0.0/8")
    assert client_server.resolve_client_address("10.1.2.3", "203.0.113.9", trusted) == "203.0.113.9"
    # Loopback is trusted only by the default, not in addition to what is configured.
    assert client_server.resolve_client_address("127.0.0.1", "203.0.113.9", trusted) == "127.0.0.1"


@contextmanager
def _serving(srv):
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}"
    finally:
        srv.shutdown()
        srv.server_close()


@contextmanager
def _client_backend(tmp_path, engine_base, rate_limiter):
    """A Client backend on 127.0.0.1:0 under the default trusted set, as conftest's `client_backend` is built but with its Engine and limiter chosen here."""
    conn = client_server.connect_db(tmp_path / "users.db")
    ensure_user_schema(conn)
    try:
        with _serving(client_server.ClientBackendServer(("127.0.0.1", 0), client_server.ClientBackendHandler, conn, engine_base, "bridge", rate_limiter)) as base:
            yield base
    finally:
        conn.close()


def _status(base, method, path, headers):
    req = urllib.request.Request(base + path, data=b"{}" if method == "POST" else None, method=method)
    for name, value in headers.items():
        req.add_header(name, value)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code


def test_route_limiter_buckets_by_last_hop(tmp_path):
    with _client_backend(tmp_path, CLOSED_ENGINE, RateLimiter(2, 60)) as base:
        # Without a profile key an allowed request is 401, so 429 is the limiter and nothing else.
        statuses = [_status(base, "GET", "/api/user-profile", {"X-Forwarded-For": f"198.51.100.{i}, 203.0.113.9"}) for i in (1, 2, 3)]
        assert statuses == [401, 401, 429]
        # A trusted hop after 203.0.113.9 is stripped by the resolver; keying on the raw last hop would open a fresh 127.0.0.1 bucket and answer 401.
        assert _status(base, "GET", "/api/user-profile", {"X-Forwarded-For": "198.51.100.4, 203.0.113.9, 127.0.0.1"}) == 429
        # Keying on the socket peer puts every request in 127.0.0.1's bucket and answers 429 here.
        assert _status(base, "GET", "/api/user-profile", {"X-Forwarded-For": "198.51.100.1, 203.0.113.10"}) == 401


def test_mint_limiter_buckets_by_last_hop(tmp_path):
    with _client_backend(tmp_path, CLOSED_ENGINE, RateLimiter(1000, 60)) as base:
        statuses = [_status(base, "POST", "/api/profile", {"X-Forwarded-For": f"198.51.100.{i}, 203.0.113.9"}) for i in range(1, 7)]
        assert statuses == [201] * 5 + [429]
        assert _status(base, "POST", "/api/profile", {"X-Forwarded-For": "198.51.100.7, 203.0.113.9, 127.0.0.1"}) == 429
        assert _status(base, "POST", "/api/profile", {"X-Forwarded-For": "198.51.100.1, 203.0.113.10"}) == 201


def test_engine_receives_the_resolved_address_as_x_client_ip(tmp_path):
    received = []

    class EngineStub(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            received.append(self.headers.get("x-client-ip"))
            body = json.dumps({"rows": []}).encode("utf-8")
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            pass

    with _serving(ThreadingHTTPServer(("127.0.0.1", 0), EngineStub)) as engine_base, _client_backend(tmp_path, engine_base, RateLimiter(1000, 60)) as base:
        assert _status(base, "GET", "/api/channels", {"X-Forwarded-For": "6.6.6.6, 203.0.113.9"}) == 200
        assert _status(base, "GET", "/api/channels", {"X-Forwarded-For": "6.6.6.6, 203.0.113.9, 127.0.0.1"}) == 200
        assert _status(base, "GET", "/api/channels", {}) == 200
        assert _status(base, "GET", "/api/channels", {"X-Real-IP": "6.6.6.6"}) == 200
    # Sending the first hop gives 6.6.6.6 first; trusting X-Real-IP gives it last; a raw last-hop read gives 127.0.0.1 second.
    assert received == ["203.0.113.9", "203.0.113.9", "127.0.0.1", "127.0.0.1"]


# --- published interaction events ------------------------------------------------------


def _event_id(actor: str, video: dict, event_type: str, generation: int) -> str:
    """The id the requirement derives for one event."""
    return "client-" + hashlib.sha256(json.dumps([actor, video["uuid"], video["host"], event_type, generation]).encode("utf-8")).hexdigest()


def _canonical(uuid: str, host: str) -> dict[str, str]:
    # Lower-casing stands in for the Engine's canonicalisation, so a request spelled otherwise resolves to an identity other than the one it named.
    uuid, host = uuid.lower(), host.lower()
    return {"video_id": "vid-" + uuid, "instance_domain": host, "video_uuid": uuid, "video_url": f"https://{host}/w/{uuid}"}


@pytest.fixture
def rig(tmp_path):
    engine_db = sqlite3.connect(tmp_path / "engine.db", check_same_thread=False)
    engine_db.row_factory = sqlite3.Row
    ensure_interaction_event_schema(engine_db)
    lock = threading.Lock()
    events = []

    class EngineStub(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            body = json.loads(self.rfile.read(int(self.headers["content-length"])))
            status = 200
            if self.path == "/internal/videos/resolve":
                answer = {"video": _canonical(body["uuid"], body["host"])}
            elif self.path == "/internal/videos/metadata":
                # Likes import resolves its uuid entries here in one call.
                rows = [_canonical(e["video_uuid"], e["instance_domain"]) for e in body["entries"]]
                answer = {"ok": True, "count": len(rows), "rows": rows}
            elif self.path == "/internal/dislikes/centroids":
                answer = {"space": "test", "centroids": []}
            elif self.path == "/internal/events/ingest":
                # The real ingest, so a repeated id is collapsed by the Engine's own ON CONFLICT.
                with lock:
                    result = ingest_interaction_event(engine_db, body)
                    events.append((body, result))
                answer = {"ok": True, "duplicates": int(result["duplicate"]), "results": [result]}
            else:
                status, answer = 404, {"error": "Not found"}
            data = json.dumps(answer).encode("utf-8")
            self.send_response(status)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format, *args):
            pass

    try:
        with _serving(ThreadingHTTPServer(("127.0.0.1", 0), EngineStub)) as engine_base, _client_backend(tmp_path, engine_base, RateLimiter(1000, 60)) as base:
            yield SimpleNamespace(client=ClientBackend(base, tmp_path / "users.db"), engine_db=engine_db, events=events)
    finally:
        engine_db.close()


def _mint_profile(client) -> tuple[str, dict[str, str]]:
    status, body = client.request("POST", "/api/profile")
    assert status == 201, body
    return body["profile_id"], {"X-Profile-Key": body["key"]}


def _video() -> dict[str, str]:
    return {"uuid": uuid4().hex, "host": EVENT_HOST}


def _act(client, headers, action: str, video: dict) -> int:
    return client.request("POST", "/api/user-action", headers, {"action": action, **video})[0]


def _reaction(client, headers, video: dict) -> dict:
    status, body = client.request("GET", f"/api/profile/reaction?uuid={video['uuid']}&host={video['host']}", headers)
    assert status == 200, body
    return body


def _published(events) -> list[tuple[str, str]]:
    return [(payload["event_type"], payload["event_id"]) for payload, _ in events]


def _signal(engine_db, video: dict) -> tuple[int, float]:
    row = engine_db.execute("SELECT likes_count, signal_score FROM interaction_signals WHERE video_uuid = ? AND instance_domain = ?", (video["uuid"], video["host"])).fetchone()
    return (row["likes_count"], row["signal_score"]) if row else (0, 0.0)


def test_a_repeated_like_publishes_one_like_at_generation_1(rig):
    pid, key = _mint_profile(rig.client)
    video = _video()
    assert [_act(rig.client, key, "like", video) for _ in range(2)] == [200, 200]
    assert [event_type for event_type, _ in _published(rig.events)] == ["Like"]
    assert _signal(rig.engine_db, video) == (1, 1.0)
    assert _published(rig.events) == [("Like", _event_id(pid, video, "Like", 1))]


def test_like_undo_like_like_publishes_like_undolike_like_under_generations_1_1_2(rig):
    pid, key = _mint_profile(rig.client)
    video = _video()
    assert [_act(rig.client, key, action, video) for action in ("like", "undo_like", "like")] == [200, 200, 200]
    published = _published(rig.events)
    assert [event_type for event_type, _ in published] == ["Like", "UndoLike", "Like"]
    assert published[0][1] != published[2][1]
    assert published == [("Like", _event_id(pid, video, "Like", 1)), ("UndoLike", _event_id(pid, video, "UndoLike", 1)), ("Like", _event_id(pid, video, "Like", 2))]
    assert _signal(rig.engine_db, video) == (1, 1.0)


def test_two_anonymous_likes_carry_one_id_and_the_engine_counts_the_second_as_a_duplicate(rig):
    video = _video()
    assert [_act(rig.client, None, "like", video) for _ in range(2)] == [200, 200]
    assert _published(rig.events) == [("Like", _event_id("anonymous", video, "Like", 0))] * 2
    assert [result["duplicate"] for _, result in rig.events] == [False, True]
    assert _signal(rig.engine_db, video) == (1, 1.0)


def test_a_like_named_in_a_non_canonical_spelling_derives_its_id_from_the_resolved_identity(rig):
    pid, key = _mint_profile(rig.client)
    canonical = _video()
    spelled = {"uuid": canonical["uuid"].upper(), "host": "IDS.Example"}
    assert _act(rig.client, key, "like", spelled) == 200
    assert [payload["object"]["video_uuid"] for payload, _ in rig.events] == [canonical["uuid"]]  # control: the Engine's resolved uuid reached the payload
    assert [payload["object"]["instance_domain"] for payload, _ in rig.events] == [canonical["host"]]  # control: and its resolved host
    assert _published(rig.events) == [("Like", _event_id(pid, canonical, "Like", 1))]


def test_an_undo_like_of_an_unliked_video_answers_200_and_publishes_nothing(rig):
    pid, key = _mint_profile(rig.client)
    video = _video()
    assert _act(rig.client, key, "undo_like", video) == 200
    assert rig.events == []
    # This rig does publish an opening like, and the refused undo advanced no generation.
    assert _act(rig.client, key, "like", video) == 200
    assert _published(rig.events) == [("Like", _event_id(pid, video, "Like", 1))]  # control


def test_a_dislike_replacing_a_like_publishes_the_undo_likes_id_and_one_of_an_unliked_video_publishes_nothing(rig):
    pid, key = _mint_profile(rig.client)
    liked, unliked = _video(), _video()
    assert [_act(rig.client, key, action, liked) for action in ("like", "dislike")] == [200, 200]
    assert [event_type for event_type, _ in _published(rig.events)] == ["Like", "UndoLike"]
    assert _published(rig.events) == [("Like", _event_id(pid, liked, "Like", 1)), ("UndoLike", _event_id(pid, liked, "UndoLike", 1))]
    assert _signal(rig.engine_db, liked) == (0, 0.0)
    assert _act(rig.client, key, "dislike", unliked) == 200
    assert _reaction(rig.client, key, unliked) == {"liked": False, "disliked": True}  # control: the dislike was stored
    assert _act(rig.client, key, "undo_dislike", unliked) == 200
    assert len(rig.events) == 2


def test_a_like_after_a_reset_publishes_nothing_and_the_next_undo_like_withdraws_the_first(rig):
    pid, key = _mint_profile(rig.client)
    video = _video()
    assert _act(rig.client, key, "like", video) == 200
    assert rig.client.request("POST", "/api/user-profile/reset", key, {})[0] == 200
    assert _reaction(rig.client, key, video) == {"liked": False, "disliked": False}  # control: the reset removed the like
    assert _act(rig.client, key, "like", video) == 200
    assert _reaction(rig.client, key, video) == {"liked": True, "disliked": False}  # control: the re-like is stored
    assert [event_type for event_type, _ in _published(rig.events)] == ["Like"]
    assert _act(rig.client, key, "undo_like", video) == 200
    assert [event_type for event_type, _ in _published(rig.events)] == ["Like", "UndoLike"]
    assert _signal(rig.engine_db, video) == (0, 0.0)
    # The undo withdraws the first like's generation.
    assert _published(rig.events) == [("Like", _event_id(pid, video, "Like", 1)), ("UndoLike", _event_id(pid, video, "UndoLike", 1))]


def test_an_undo_like_of_an_imported_like_publishes_nothing(rig):
    pid, key = _mint_profile(rig.client)
    video = _video()
    assert rig.client.request("POST", "/api/profile/likes/import", key, {"likes": [video]}) == (200, {"imported": 1})
    assert _reaction(rig.client, key, video) == {"liked": True, "disliked": False}  # control: the import stored the like
    assert _act(rig.client, key, "undo_like", video) == 200
    assert _reaction(rig.client, key, video) == {"liked": False, "disliked": False}  # control: the undo removed it
    assert rig.events == []
    # The import opened no generation, so the first published like is generation 1.
    assert _act(rig.client, key, "like", video) == 200
    assert _published(rig.events) == [("Like", _event_id(pid, video, "Like", 1))]  # control
