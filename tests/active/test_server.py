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

Browser likes (the likes page `POST /api/user-profile/likes` and likes import) are resolved with
one Engine call, to `/internal/videos/metadata`, and at most the first 50 like entries of a body
reach the Engine on each of the three paths that read `MAX_CLIENT_LIKES`:

- A likes-page body of three likes, a repeat and an unknown one reaches the Engine as one metadata
  request whose `entries` are the five submitted `{video_uuid, instance_domain}` pairs, in order,
  and is answered 200 with the three known rows in submitted order.
- An empty body, an empty `likes` list, and a list of only malformed likes are each answered 200
  with `likes == []` and reach the Engine not at all; a well-formed like sent next does reach it.
- Importing two clean likes, one the profile dislikes and an unknown one reaches the Engine as one
  metadata request carrying the four pairs, answers `{"imported": 2}`, and leaves the profile
  liking exactly the two clean videos, keyed on the `video_id` of their Engine rows.
- A 60-like likes page, a 60-like import, and a keyless 60-like `POST /recommendations` each pass
  the Engine exactly the first 50; the page answers those 50 rows and the import likes those 50.

Those use a stand-in Engine that records every request and answers the metadata route as the
Engine does: one row per known uuid entry, in entry order, each video once.

CORS: the Client sends CORS headers only to a request whose `Origin` is exactly one it lists.

- `parse_cors_origins` turns a `CLIENT_CORS_ORIGINS` value into a frozenset of exact origins:
  surrounding whitespace, blank entries and `*` are dropped, and a value listing nothing is the
  empty set.
- `ClientBackendServer` takes the set as a trailing argument after `trusted_proxies` and holds it
  as `cors_origins`; a six-argument construction holds the empty set.
- A Client whose `cors_origins` is empty answers GET /api/health and OPTIONS /api/user-profile
  with no `access-control-*` header, whatever the `Origin`; OPTIONS is 204.
- A Client listing http://127.0.0.1:5173 and https://dev.example:8443 answers each of them with
  exactly allow-origin (that origin echoed), allow-methods `GET, POST, OPTIONS` and allow-headers
  `content-type, x-profile-key`, plus `Vary: Origin`; no max-age and no allow-credentials, except
  that OPTIONS answers 204 with max-age `600`.
- The same Client answers http://localhost:5173, HTTP://127.0.0.1:5173, http://127.0.0.1:5173/,
  https://evil.example, `*` and no `Origin` with no `access-control-*` header.
- A `respond_json` 401 and `respond_bytes` 204s carry the same echo and `Vary: Origin` for a
  listed Origin, and nothing for unlisted ones. No header value is ever `*`.

Engine failures: a failed Engine call or bridge publish answers the Client's caller with fixed
text, and its cause goes only to the Client log at ERROR.

- Over a stub Engine answering 500 `{"error": SENTINEL}`, the likes page, likes import, block add,
  and a user action at its resolve and its dislike-centroids call each answer 502 whose `error`
  is exactly the fixed text naming its operation, without the sentinel or `HTTP 500`; the
  sentinel is in an ERROR record, and the likes page's has event `engine.call`.
- A like whose bridge publish meets a dropped connection answers 502 with `bridge_error` exactly
  `engine bridge unavailable`, the exception's text going to an ERROR record; one meeting an
  ingest 500 gets exactly `engine bridge HTTP 500` and no Engine text.
- `_publish_to_engine_bridge` against a closed port returns exactly
  `{"ok": False, "error": "engine bridge unavailable"}` and logs `engine.bridge` at ERROR with a
  `context.error` naming the refused connection.
- A likes page with a malformed JSON body still answers 400 `Invalid JSON body` without calling
  the Engine.
"""
from __future__ import annotations

import hashlib
import http.client
import json
import logging
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
from urllib.parse import quote, urlparse
from uuid import uuid4

import pytest
from conftest import CLOSED_ENGINE, ClientBackend, RateLimiter, client_server, ensure_user_schema
from lib.dislikes import write_dislike
from lib.profiles import mint_profile, resolve_profile
from lib.users_store import load_liked_keys, record_like

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


# --- browser likes: one metadata call, and the 50-entry cap -----------------------------

LIKES_HOST = "h.example"
METADATA_ROUTE = "/internal/videos/metadata"
# Engine rows; each video_id differs from its uuid, so a like stored from the browser's entry rather than the row is told apart.
ROW_A = {"video_id": "id-a", "video_uuid": "u-a", "instance_domain": LIKES_HOST, "title": "A"}
ROW_B = {"video_id": "id-b", "video_uuid": "u-b", "instance_domain": LIKES_HOST, "title": "B"}
ROW_C = {"video_id": "id-c", "video_uuid": "u-c", "instance_domain": LIKES_HOST, "title": "C"}
CAP_VIDEOS = [{"video_id": f"id-{i:02d}", "video_uuid": f"u-{i:02d}", "instance_domain": LIKES_HOST, "title": f"V{i}"} for i in range(60)]


def _browser_like(uuid: str) -> dict:
    return {"uuid": uuid, "host": LIKES_HOST}


def _uuid_entry(uuid: str) -> dict:
    return {"video_uuid": uuid, "instance_domain": LIKES_HOST}


CAP_LIKES = [_browser_like(f"u-{i:02d}") for i in range(60)]


@contextmanager
def _likes_client(tmp_path, engine_base):
    """`_client_backend` wrapped in conftest's `ClientBackend`, for `.request` and `.db_path`."""
    with _client_backend(tmp_path, engine_base, RateLimiter(1000, 60)) as base:
        yield ClientBackend(base, tmp_path / "users.db")


@contextmanager
def _recording_engine(videos):
    """A stand-in Engine that records `(path, json body)` for every request and answers the metadata route from `videos` by uuid and host, in entry order, each video once; any other route gets no rows."""
    table = {f"{v['video_uuid']}::{v['instance_domain']}": v for v in videos}
    received = []

    class EngineStub(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            body = json.loads(self.rfile.read(int(self.headers.get("content-length") or 0)) or b"null")
            received.append((self.path, body))
            rows = []
            if self.path == METADATA_ROUTE:
                for entry in body["entries"]:
                    row = table.get(f"{entry.get('video_uuid')}::{entry.get('instance_domain')}")
                    if row is not None and row not in rows:
                        rows.append(row)
            self._answer({"ok": True, "count": len(rows), "rows": rows})

        def do_GET(self):  # noqa: N802
            received.append((self.path, None))
            self._answer({"rows": []})

        def _answer(self, payload):
            data = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format, *args):
            pass

    with _serving(ThreadingHTTPServer(("127.0.0.1", 0), EngineStub)) as base:
        yield base, received


def test_a_likes_page_is_one_metadata_call_answered_with_the_known_rows_in_submitted_order(tmp_path):
    likes = [_browser_like("u-c"), _browser_like("u-a"), _browser_like("u-c"), _browser_like("u-x"), _browser_like("u-b")]
    with _recording_engine([ROW_A, ROW_B, ROW_C]) as (engine_base, received), _likes_client(tmp_path, engine_base) as client:
        status, body = client.request("POST", "/api/user-profile/likes", body={"likes": likes})
    # A per-like resolve loop would record `/internal/videos/resolve` requests instead.
    assert received == [(METADATA_ROUTE, {"entries": [_uuid_entry("u-c"), _uuid_entry("u-a"), _uuid_entry("u-c"), _uuid_entry("u-x"), _uuid_entry("u-b")]})]
    # Submitted order, not the table's [A, B, C]; the repeat and u-x omitted.
    assert (status, body["likes"]) == (200, [ROW_C, ROW_A, ROW_B])


def test_a_likes_page_with_no_well_formed_like_is_answered_empty_without_the_engine(tmp_path):
    malformed = ["x", {"uuid": "u-a"}, {"host": LIKES_HOST}, {"uuid": "   ", "host": LIKES_HOST}, {"uuid": "u-a", "host": 7}]
    with _recording_engine([ROW_A]) as (engine_base, received), _likes_client(tmp_path, engine_base) as client:
        replies = [client.request("POST", "/api/user-profile/likes", body=body) for body in ({}, {"likes": []}, {"likes": malformed})]
        assert received == []
        client.request("POST", "/api/user-profile/likes", body={"likes": [_browser_like("u-a")]})
    assert [(status, body["likes"]) for status, body in replies] == [(200, [])] * 3
    assert received, "control: a well-formed like reaches this Engine and is recorded, so the empty record above is not a deaf Engine"
    assert received == [(METADATA_ROUTE, {"entries": [_uuid_entry("u-a")]})]


def test_an_import_is_one_metadata_call_and_likes_each_returned_video_the_profile_has_not_disliked(tmp_path):
    with _recording_engine([ROW_A, ROW_B, ROW_C]) as (engine_base, received), _likes_client(tmp_path, engine_base) as client:
        status, minted = client.request("POST", "/api/profile")
        assert status == 201, minted
        conn = client_server.connect_db(client.db_path)
        try:
            profile_id = resolve_profile(conn, minted["key"])
            assert profile_id == minted["profile_id"]  # control: the second connection sees the minted profile
            with conn:
                write_dislike(conn, profile_id, ROW_B, None)
            # The disliked video sits between the clean ones, so skipping the first or the last returned row imports one, not two.
            status, body = client.request("POST", "/api/profile/likes/import", headers={"X-Profile-Key": minted["key"]}, body={"likes": [_browser_like("u-a"), _browser_like("u-b"), _browser_like("u-x"), _browser_like("u-c")]})
            liked = load_liked_keys(conn, profile_id)
            stored = {(row["video_id"], row["video_uuid"], row["instance_domain"]) for row in conn.execute("SELECT video_id, video_uuid, instance_domain FROM likes WHERE user_id = ?", (profile_id,))}
        finally:
            conn.close()
    assert received == [(METADATA_ROUTE, {"entries": [_uuid_entry("u-a"), _uuid_entry("u-b"), _uuid_entry("u-x"), _uuid_entry("u-c")]})]
    # 3 when the dislike is ignored or a like is keyed on the uuid; 1 when the first or last row is skipped.
    assert (status, body) == (200, {"imported": 2})
    assert liked == {("id-a", LIKES_HOST), ("id-c", LIKES_HOST)}  # the rows' video_ids, and not id-b, which the profile dislikes
    # Each like carries its video_uuid and host, not nulls; row and entry share them, so their source is not told apart.
    assert stored == {("id-a", "u-a", LIKES_HOST), ("id-c", "u-c", LIKES_HOST)}


def test_a_60_like_likes_page_reaches_the_engine_as_its_first_50_and_is_answered_with_their_rows(tmp_path):
    with _recording_engine(CAP_VIDEOS) as (engine_base, received), _likes_client(tmp_path, engine_base) as client:
        status, body = client.request("POST", "/api/user-profile/likes", body={"likes": CAP_LIKES})
    # A cap of 49 or 51, or keeping the last 50, fails here as well as a missing cap.
    assert received == [(METADATA_ROUTE, {"entries": [_uuid_entry(f"u-{i:02d}") for i in range(50)]})]
    assert (status, [row["video_id"] for row in body["likes"]]) == (200, [f"id-{i:02d}" for i in range(50)])


def test_a_60_like_import_reaches_the_engine_as_its_first_50_and_likes_exactly_those(tmp_path):
    with _recording_engine(CAP_VIDEOS) as (engine_base, received), _likes_client(tmp_path, engine_base) as client:
        status, minted = client.request("POST", "/api/profile")
        assert status == 201, minted
        status, body = client.request("POST", "/api/profile/likes/import", headers={"X-Profile-Key": minted["key"]}, body={"likes": CAP_LIKES})
        conn = client_server.connect_db(client.db_path)
        try:
            liked = load_liked_keys(conn, resolve_profile(conn, minted["key"]))
        finally:
            conn.close()
    assert received == [(METADATA_ROUTE, {"entries": [_uuid_entry(f"u-{i:02d}") for i in range(50)]})]
    assert (status, body) == (200, {"imported": 50})
    assert liked == {(f"id-{i:02d}", LIKES_HOST) for i in range(50)}


def test_a_keyless_60_like_recommendations_request_forwards_its_first_50_likes(tmp_path):
    with _recording_engine(CAP_VIDEOS) as (engine_base, received), _likes_client(tmp_path, engine_base) as client:
        status, _ = client.request("POST", "/recommendations", body={"likes": CAP_LIKES})
    assert status == 200
    # The Client adds its own `?limit=48` page size to the forwarded path, which this test does not concern.
    assert [(urlparse(path).path, body["likes"]) for path, body in received] == [("/recommendations", [_browser_like(f"u-{i:02d}") for i in range(50)])]


def _wire(base, method, path, headers=None, body=None):
    """Send one request through raw `http.client`, `body` as given when bytes and JSON-encoded otherwise; return the status, every header as lower-cased name -> list of values (duplicates visible), and the raw body."""
    if body is not None and not isinstance(body, bytes):
        body = json.dumps(body).encode()
    if body is None and method == "POST":
        body = b""
    conn = http.client.HTTPConnection("127.0.0.1", urlparse(base).port, timeout=30)
    try:
        conn.request(method, path, body=body, headers=dict(headers or {}))
        resp = conn.getresponse()
        data = resp.read()
        seen: dict[str, list[str]] = {}
        for name, value in resp.getheaders():
            seen.setdefault(name.lower(), []).append(value)
        return resp.status, seen, data
    finally:
        conn.close()


# --- CORS: only an exactly listed Origin gets CORS headers ------------------------------

CORS_LISTED = "http://127.0.0.1:5173"
CORS_SECOND = "https://dev.example:8443"
CORS_BOTH = frozenset({CORS_LISTED, CORS_SECOND})
CORS_UNLISTED = ("http://localhost:5173", "HTTP://127.0.0.1:5173", "http://127.0.0.1:5173/", "https://evil.example", "*", None)
# Removing a block nobody added still answers 204 through respond_bytes, so one minted key serves every Origin without hitting the 5-per-hour mint limit.
BLOCK_REMOVE = json.dumps({"kind": "account", "account_url": "https://x.example/a/b"}).encode()


def _origin(origin):
    return {} if origin is None else {"Origin": origin}


def _cors_echo(origin):
    return {"access-control-allow-origin": [origin], "access-control-allow-methods": ["GET, POST, OPTIONS"], "access-control-allow-headers": ["content-type, x-profile-key"]}


def _cors_preflight_echo(origin):
    return {**_cors_echo(origin), "access-control-max-age": ["600"]}


def _cors(headers):
    return {name: values for name, values in headers.items() if name.startswith("access-control-")}


def _star_values(responses):
    return [(name, value) for _, headers, _ in responses for name, values in headers.items() for value in values if value.strip() == "*"]


@contextmanager
def _cors_client(tmp_path, cors_origins):
    """A Client backend on 127.0.0.1:0 over a closed Engine, constructed with `cors_origins`; yields its base URL."""
    conn = client_server.connect_db(tmp_path / "users.db")
    ensure_user_schema(conn)
    try:
        with _serving(client_server.ClientBackendServer(("127.0.0.1", 0), client_server.ClientBackendHandler, conn, CLOSED_ENGINE, "bridge", RateLimiter(1000, 60), client_server.DEFAULT_TRUSTED_PROXY_NETWORKS, cors_origins)) as base:
            yield base
    finally:
        conn.close()


@pytest.mark.parametrize(("value", "expected"), [
    ("", frozenset()),
    (" http://a:1 , ,http://b ", frozenset({"http://a:1", "http://b"})),
    ("*, http://a", frozenset({"http://a"})),
    (",,", frozenset()),
    ("*", frozenset()),
    (" * ,http://a", frozenset({"http://a"})),
])
def test_parse_cors_origins_keeps_exact_origins_only(value, expected):
    parsed = client_server.parse_cors_origins(value)
    assert isinstance(parsed, frozenset)
    assert parsed == expected


def test_server_holds_trailing_cors_origins(tmp_path):
    conn = client_server.connect_db(tmp_path / "users.db")
    servers = []
    try:
        servers.append(client_server.ClientBackendServer(("127.0.0.1", 0), client_server.ClientBackendHandler, conn, CLOSED_ENGINE, "bridge", RateLimiter(1000, 60), client_server.DEFAULT_TRUSTED_PROXY_NETWORKS, CORS_BOTH))
        servers.append(client_server.ClientBackendServer(("127.0.0.1", 0), client_server.ClientBackendHandler, conn, CLOSED_ENGINE, "bridge", RateLimiter(1000, 60)))
        assert servers[0].cors_origins == CORS_BOTH
        assert servers[0].trusted_proxies == client_server.DEFAULT_TRUSTED_PROXY_NETWORKS
        assert servers[1].cors_origins == frozenset()
    finally:
        for srv in servers:
            srv.server_close()
        conn.close()


def test_no_listed_origin_sends_no_cors_headers(tmp_path):
    # Positive control: the same Origin on the same routes is echoed by a Client that lists it, so the empty result below is the set's doing.
    with _cors_client(tmp_path, CORS_BOTH) as base:
        control = [_wire(base, "GET", "/api/health", _origin(CORS_LISTED)), _wire(base, "OPTIONS", "/api/user-profile", _origin(CORS_LISTED))]
    assert _cors(control[0][1]) == _cors_echo(CORS_LISTED)
    assert _cors(control[1][1]) == _cors_preflight_echo(CORS_LISTED)
    responses = []
    with _cors_client(tmp_path, frozenset()) as base:
        for origin in (CORS_LISTED, *CORS_UNLISTED):
            got = _wire(base, "GET", "/api/health", _origin(origin))
            assert got[0] == 200
            assert _cors(got[1]) == {}, origin
            responses.append(got)
            got = _wire(base, "OPTIONS", "/api/user-profile", _origin(origin))
            assert got[0] == 204, origin
            assert _cors(got[1]) == {}, origin
            responses.append(got)
    assert _star_values(responses) == []


def test_listed_origins_are_echoed_with_vary_and_preflight_max_age(tmp_path):
    responses = []
    with _cors_client(tmp_path, CORS_BOTH) as base:
        for origin in (CORS_LISTED, CORS_SECOND):
            get = _wire(base, "GET", "/api/health", _origin(origin))
            assert get[0] == 200
            assert _cors(get[1]) == _cors_echo(origin), origin
            assert "access-control-max-age" not in get[1]
            assert "access-control-allow-credentials" not in get[1]
            assert get[1].get("vary") == ["Origin"], origin
            preflight = _wire(base, "OPTIONS", "/api/user-profile", _origin(origin))
            assert preflight[0] == 204, origin
            assert _cors(preflight[1]) == _cors_preflight_echo(origin), origin
            assert preflight[1].get("vary") == ["Origin"], origin
            responses += [get, preflight]
    assert _star_values(responses) == []


def test_unlisted_origin_gets_no_cors_headers(tmp_path):
    responses = []
    with _cors_client(tmp_path, CORS_BOTH) as base:
        # Positive control on this same Client: a listed Origin is echoed, so the membership check runs before the unlisted ones are read.
        control = [_wire(base, "GET", "/api/health", _origin(CORS_LISTED)), _wire(base, "OPTIONS", "/api/user-profile", _origin(CORS_LISTED))]
        assert _cors(control[0][1]) == _cors_echo(CORS_LISTED)
        assert _cors(control[1][1]) == _cors_preflight_echo(CORS_LISTED)
        for origin in CORS_UNLISTED:
            got = _wire(base, "GET", "/api/health", _origin(origin))
            assert got[0] == 200
            assert _cors(got[1]) == {}, origin
            responses.append(got)
            got = _wire(base, "OPTIONS", "/api/user-profile", _origin(origin))
            assert got[0] == 204, origin
            assert _cors(got[1]) == {}, origin
            responses.append(got)
    assert _star_values(responses) == []


def test_error_and_bytes_responses_echo_listed_origin(tmp_path):
    with _cors_client(tmp_path, CORS_BOTH) as base:
        refused = _wire(base, "GET", "/api/user-profile", _origin(CORS_LISTED))
        minted = _wire(base, "POST", "/api/profile")
        assert minted[0] == 201
        key = {"X-Profile-Key": json.loads(minted[2])["key"]}
        removed = {origin: _wire(base, "POST", "/api/profile/blocks/remove", {**key, **_origin(origin)}, BLOCK_REMOVE) for origin in (CORS_SECOND, *CORS_UNLISTED)}
        deleted = _wire(base, "POST", "/api/profile/delete", {**key, **_origin(CORS_SECOND)})
    assert removed[CORS_SECOND][0] == 204
    assert _cors(removed[CORS_SECOND][1]) == _cors_echo(CORS_SECOND)
    assert removed[CORS_SECOND][1].get("vary") == ["Origin"]
    for origin in CORS_UNLISTED:
        assert removed[origin][0] == 204, origin
        assert _cors(removed[origin][1]) == {}, origin
    assert refused[0] == 401
    assert _cors(refused[1]) == _cors_echo(CORS_LISTED)
    assert refused[1].get("vary") == ["Origin"]
    assert deleted[0] == 204
    assert _cors(deleted[1]) == _cors_echo(CORS_SECOND)
    assert deleted[1].get("vary") == ["Origin"]
    assert _star_values([refused, deleted, *removed.values()]) == []


# --- Engine failures: fixed text to the caller, the cause to the log --------------------

ENGINE_SENTINEL = "engine-sentinel-metadata-9c1d"
FAILURE_LIKES = {"likes": [{"uuid": "u1", "host": "h.example"}]}
FAILURE_SEED = {"video": {"video_id": "v1", "instance_domain": "h.example", "video_uuid": "u1", "video_url": "https://h.example/w/u1"}}
BRIDGE_FIXED = "engine bridge unavailable"
# What urllib's http.client raises when the Engine drops the ingest connection unanswered, observed against this stub.
DROPPED_TEXT = "Remote end closed connection without response"
JSON_HEADERS = {"content-type": "application/json"}


class _FailingEngine(BaseHTTPRequestHandler):
    """Answers each path from `server.replies` - (status, body), or None to drop the connection unanswered - and 500 `{"error": ENGINE_SENTINEL}` otherwise."""

    def do_POST(self):  # noqa: N802
        self.server.seen.append(self.path)
        self.rfile.read(int(self.headers.get("content-length") or 0))
        reply = self.server.replies.get(self.path, (500, {"error": ENGINE_SENTINEL}))
        if reply is None:
            self.close_connection = True
            return
        data = json.dumps(reply[1]).encode()
        self.send_response(reply[0])
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


@contextmanager
def _failing_engine(replies=None):
    """A `_FailingEngine` on 127.0.0.1:0; yields its base URL and the list of paths it was sent."""
    stub = ThreadingHTTPServer(("127.0.0.1", 0), _FailingEngine)
    stub.seen = []
    stub.replies = replies or {}
    with _serving(stub) as base:
        yield base, stub.seen


@contextmanager
def _liking_client(tmp_path, engine_base):
    """A Client backend on 127.0.0.1:0 over `engine_base`, holding one profile that likes v1@h.example; yields its base URL and the profile's key headers."""
    conn = client_server.connect_db(tmp_path / "users.db")
    ensure_user_schema(conn)
    profile_id, key = mint_profile(conn)
    record_like(conn, profile_id, "like", {"video_id": "v1", "instance_domain": "h.example", "video_uuid": "u1"}, client_server.MAX_LIKES)
    try:
        with _serving(client_server.ClientBackendServer(("127.0.0.1", 0), client_server.ClientBackendHandler, conn, engine_base, "bridge", RateLimiter(1000, 60))) as base:
            yield base, {"X-Profile-Key": key}
    finally:
        conn.close()


def _error_messages(caplog):
    return [record.getMessage() for record in caplog.records if record.levelno >= logging.ERROR]


def _error_events(caplog):
    """The JSON payloads of the ERROR records that are JSON objects."""
    events = []
    for message in _error_messages(caplog):
        try:
            payload = json.loads(message)
        except ValueError:
            continue
        if isinstance(payload, dict):
            events.append(payload)
    return events


def test_client_likes_502_is_fixed_text_and_engine_error_is_logged(tmp_path, caplog):
    caplog.set_level(logging.ERROR)
    with _failing_engine() as (engine_base, seen), _liking_client(tmp_path, engine_base) as (base, _):
        status, _, raw = _wire(base, "POST", "/api/user-profile/likes", JSON_HEADERS, FAILURE_LIKES)
    # Control: the Client made the metadata call, so the sentinel was in reach of the response.
    assert seen == ["/internal/videos/metadata"]
    assert status == 502
    assert json.loads(raw) == {"error": "Engine metadata failed"}
    assert ENGINE_SENTINEL.encode() not in raw
    assert ENGINE_SENTINEL in caplog.text
    assert any(ENGINE_SENTINEL in message for message in _error_messages(caplog))
    assert any(event.get("event") == "engine.call" for event in _error_events(caplog))


# Each failing site's fixed text names the operation it was attempting; likes-import names the metadata call it makes.
FAILURE_ROUTES = [
    ("likes-get", "GET", "/api/user-profile/likes", True, None, {}, ["/internal/videos/metadata"], "Engine metadata failed"),
    ("likes-import", "POST", "/api/profile/likes/import", True, FAILURE_LIKES, {}, ["/internal/videos/metadata"], "Engine metadata failed"),
    ("block-add", "POST", "/api/profile/blocks", True, {"kind": "channel", "uuid": "u1", "host": "h.example"}, {}, ["/internal/videos/resolve"], "Engine lookup failed"),
    ("action-resolve", "POST", "/api/user-action", False, {"action": "like", "uuid": "u1", "host": "h.example"}, {}, ["/internal/videos/resolve"], "Engine resolve failed"),
    ("action-centroids", "POST", "/api/user-action", True, {"action": "dislike", "uuid": "u1", "host": "h.example"}, {"/internal/videos/resolve": (200, FAILURE_SEED)}, ["/internal/videos/resolve", "/internal/dislikes/centroids"], "Engine centroids failed"),
]


@pytest.mark.parametrize("method, path, keyed, body, replies, calls, expected", [case[1:] for case in FAILURE_ROUTES], ids=[case[0] for case in FAILURE_ROUTES])
def test_other_engine_502s_carry_no_engine_text(tmp_path, caplog, method, path, keyed, body, replies, calls, expected):
    caplog.set_level(logging.ERROR)
    with _failing_engine(replies) as (engine_base, seen), _liking_client(tmp_path, engine_base) as (base, key):
        status, _, raw = _wire(base, method, path, {**JSON_HEADERS, **(key if keyed else {})}, body)
    # Control: the request got past validation to the Engine call that fails, ending on it.
    assert seen == calls
    assert status == 502
    assert json.loads(raw).get("error") == expected
    assert ENGINE_SENTINEL.encode() not in raw
    assert b"HTTP 500" not in raw
    assert any(ENGINE_SENTINEL in message for message in _error_messages(caplog))


def test_user_action_bridge_error_carries_no_exception_text(tmp_path, caplog):
    caplog.set_level(logging.ERROR)
    with _failing_engine({"/internal/videos/resolve": (200, FAILURE_SEED), "/internal/events/ingest": None}) as (engine_base, seen), _liking_client(tmp_path, engine_base) as (base, _):
        status, _, raw = _wire(base, "POST", "/api/user-action", JSON_HEADERS, {"action": "like", "uuid": "u1", "host": "h.example"})
    # Control: the like was resolved and its publish reached the ingest route, which dropped it.
    assert seen == ["/internal/videos/resolve", "/internal/events/ingest"]
    assert status == 502
    body = json.loads(raw)
    assert body["bridge_ok"] is False
    assert body["bridge_error"] == BRIDGE_FIXED
    assert DROPPED_TEXT.encode() not in raw
    assert any(DROPPED_TEXT in message for message in _error_messages(caplog))


def test_user_action_bridge_http_error_carries_no_engine_text(tmp_path):
    with _failing_engine({"/internal/videos/resolve": (200, FAILURE_SEED)}) as (engine_base, seen), _liking_client(tmp_path, engine_base) as (base, _):
        status, _, raw = _wire(base, "POST", "/api/user-action", JSON_HEADERS, {"action": "like", "uuid": "u1", "host": "h.example"})
    # Control: the like was resolved and its publish reached the ingest route, which answered 500 {"error": ENGINE_SENTINEL}.
    assert seen == ["/internal/videos/resolve", "/internal/events/ingest"]
    assert status == 502
    body = json.loads(raw)
    assert body["bridge_ok"] is False
    # Operator-confirmed: the fixed status string names the operation and the status, never the Engine's body.
    assert body["bridge_error"] == "engine bridge HTTP 500"
    assert ENGINE_SENTINEL.encode() not in raw


def test_bridge_publish_to_closed_port_returns_fixed_text_and_logs_cause(caplog):
    caplog.set_level(logging.ERROR)
    result = client_server._publish_to_engine_bridge(CLOSED_ENGINE, {"event_type": "Like"})
    assert result == {"ok": False, "error": BRIDGE_FIXED}
    bridge = [event for event in _error_events(caplog) if event.get("event") == "engine.bridge"]
    assert bridge
    errors = [event.get("context", {}).get("error") for event in bridge]
    assert any(isinstance(error, str) and error and error != BRIDGE_FIXED for error in errors)
    # The cause observed from urlopen against this port is `<urlopen error [Errno 111] Connection refused>`.
    assert any(isinstance(error, str) and "Connection refused" in error for error in errors)


def test_client_likes_malformed_json_still_answers_400(tmp_path):
    with _failing_engine() as (engine_base, seen), _liking_client(tmp_path, engine_base) as (base, _):
        status, _, raw = _wire(base, "POST", "/api/user-profile/likes", JSON_HEADERS, b"{not json")
    assert status == 400
    assert json.loads(raw) == {"error": "Invalid JSON body"}
    assert seen == []
