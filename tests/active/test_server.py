"""The Client backend carries a browser's `exclude` to the Engine, keyed profiles included, and
caps it at 500 entries.

- A keyed home request, for a profile holding five likes and four dislikes (so the Client rewrites
  the body with the profile's likes and taste vectors), carrying 500 `exclude` entries - a
  previous keyed page's rows, topped up with the dataset's longest-host videos to over 50 KB of
  `exclude` alone - is answered 200 with a home page holding none of them, where the same
  request without `exclude` repeats rows of that page within five draws.
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
  sentinel is in an ERROR record's `context.error`, as the Client's formatter renders it, and the likes page's has event `engine.call`.
- A like whose bridge publish meets a dropped connection answers 502 with `bridge_error` exactly
  `engine bridge unavailable`, the exception's text going to an ERROR record; one meeting an
  ingest 500 gets exactly `engine bridge HTTP 500` and no Engine text.
- `_publish_to_engine_bridge` against a closed port returns exactly
  `{"ok": False, "error": "engine bridge unavailable"}` and logs `engine.bridge` at ERROR with a
  `context.error` naming the refused connection.
- A likes page with a malformed JSON body still answers 400 `Invalid JSON body` without calling
  the Engine.

Client log lines, in-process after `configure_client_logging()` with the handler's stream swapped for a StringIO:

- With `LOG_FORMAT` unset and the zone pinned off UTC, `_emit_client_log(ERROR, "engine.call", "Engine metadata failed", {"error": "x\\ny"})`, a `logging.exception` for `ValueError("sentinel-client-log")`, `logging.info("bare")`, and `_emit_client_log` with an empty and with no context write exactly five lines, each a JSON object. The `engine.call` line's keys are exactly `ts, level, service, event, message, context`, with level ERROR, service `client-backend` and the message and context unchanged; the empty- and no-context lines stop at `message`. Every `ts` matches `LOG_TS_RE` and reads back as UTC inside the wall-clock window of the calls; the installed formatter renders a record whose `created` is 1741091696.789 as `2025-03-04T12:34:56.789Z` and 1741091696.9999996 as `2025-03-04T12:34:57.000Z`. The bare and exception records have event `client.log` and their own message; the bare line's keys are exactly `ts, level, service, event, message`, and the exception line adds `traceback`, ending `ValueError: sentinel-client-log`.
- Four records (`engine.call` with `{"error": "x\\ny"}`, a `logging.exception`, a bare `logging.info`, and `client.access` with an int `status`): with `LOG_FORMAT` unset, `json`, `JSON`, `bogus` or empty they are four JSON objects with a `ts` matching `LOG_TS_RE`, exactly the keys, order and values of `CLIENT_LOG_JSON_PAYLOADS`, and a traceback on the exception record.
- With `text`, `TEXT`, ` Text ` or tab-`text`-newline they are exactly four lines: none parses as a JSON object, none starts with `<`, and every one matches `<LOG_TS_RE> (INFO|ERROR) `, then the Engine's line shape with no `service` token. The `engine.call` line ends `error=x\\ny` and the exception line ends with the traceback, where `\\n` is a backslash and an n; the access line reads `INFO client.access request finished ip=127.0.0.1 status=200 bytes=-`.
- An Engine child prints its `_format_ts` for `created` 1741091696.789 and 1741091696.9999996 and its `_render_text` of two payloads that between them take every branch (a multi-line message and traceback, a null, a nested list, `request_id` in context and at top level; no message, a CR, `request_id` only at top level). The Client's `_format_ts` and `_render_text` return the same strings, so the two copies have not drifted.

The video refresh proxy (`GET /api/video/refresh`), in front of a stub Engine that records each GET's path and query:

- `?id=…&host=…` reaches the Engine as `/api/video/refresh` with exactly those two params, and the browser gets the Engine's 200 body. The same query plus `user_id`, plus `refresh_cache`, plus `foo`, with `id` repeated, or with `host` repeated each answers 400 and reaches the Engine not at all.
- With the refresh's entry in `ENGINE_PROXY_ROUTE_TIMEOUT_SECONDS` patched to 0.3 s and an Engine that sleeps 1.5 s before answering, the refresh answers 502 and the Engine saw it once. `/api/video` against that Engine, with `ENGINE_PROXY_TIMEOUT_SECONDS` at 0.3 s, answers 502 after two attempts.

Feed modes through the Client:

- Against `engine_client` (a real Client backend in front of the session Engine), `?mode=bogus` reaches the caller as the Engine's own 400 `{"error": "Unknown mode", "allowed": FEED_MODES}` body, the answer the Engine gives it directly; `FEED_MODES` is read from `handlers.similar` under the Engine interpreter.
- Against a recording stand-in Engine, a keyed `mode=hot&limit=10` page, for a profile blocking one row's channel and disliking another row, omits both rows and keeps the rest in the Engine's order, and reaches the Engine with `mode=hot` and `limit=20`; the same request without a key reaches it with `limit=10` and returns every row.

The NSFW opt-in through the Client, with rows cross-checked against the non-empty set of keys whitelist.db flags nsfw = 1:

- Through `engine_client`, up-next for one flagged seed on POST /recommendations and POST /videos/similar, and q=hentai on GET /api/v1/search/videos, each with nsfw=1, answer 200 with at least one flagged key. Each is then sent with nsfw missing, empty, "0", "true" and " 1", and every response is 200, holds rows, and holds no flagged key.
- Through a Client backend in front of a closed Engine port, GET /api/video without nsfw passes the allowlist and fails upstream (502), and with nsfw=1 is refused 400 {"error": "Unknown query parameter: nsfw"}.

The translate gateway (`GET /api/translate`, and `fetch_translate` mapping the Engine's answer), in front of a stub Engine recording each request, its `ENGINE_BRIDGE_TOKEN` set by the `translate_bridge_token` fixture:

- Under a one-request limiter, a keyless request answers 401, then a keyless request with an unknown param and a keyed valid request each answer 429 `Rate limit exceeded`, with no Engine call.
- A keyless or wrong-key request with an unknown param, a repeated `id`, a missing `host` or no params answers 401 `Profile key required`, never 400, with no Engine call; the same server's keyed valid request then reaches the Engine.
- Keyed, an unknown param answers 400 `Unknown query parameter: lang`, a repeated `id` 400 `Multiple values are not allowed for query parameter: id`, and a blank `id`, a whitespace `id`, a missing `host`, no params, a 201-character `id` and a 201-character `host` each answer 400, with no Engine call. Afterwards the Engine has seen exactly two requests: POST `/internal/translate` with the configured `X-Bridge-Token`, the `X-Request-ID` each request sent, and the body `{"id": "uuid-1", "host": "peer.example"}` from ` uuid-1 ` / ` peer.example `, then a 200-character `id`.
- From an Engine called exactly once, 404 `{"error": "Not found"}`, 500, cues that are an object, a `start` of `true` and a `text` of 7 each answer 502 `{"error": "Engine translate failed"}`, and so does an Engine on a closed port; a `ready` whose cues carry `id`, `voice` and `settings` answers 200 with exactly those cues' start, end and text and its `available`.

The valid Engine answers above carry `available` false, as plan 50's Engine sends it while no translate worker is serving.
"""
from __future__ import annotations

import hashlib
import http.client
import io
import itertools
import json
import logging
import re
import signal
import socket
import sqlite3
import subprocess
import sys
import textwrap
import threading
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import ip_network
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, quote, urlparse
from uuid import uuid4

import pytest
from conftest import CLOSED_ENGINE, ENGINE_PY, ClientBackend, RateLimiter, client_server, ensure_user_schema
from lib.blocks import add_block, block_target
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
PLAIN_DRAWS = 5
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
    # The likes' cache entries hold hundreds of rows, so two plain pages can share none (observed for the Engine's home); five draws all sharing none is rare.
    shared: set[tuple[str, str]] = set()
    for _ in range(PLAIN_DRAWS):
        shared = _keys(previous) & _keys(_home(client, key, {}))
        if shared:
            break
    assert shared, f"control: {PLAIN_DRAWS} plain keyed pages repeat none of the previous one"

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


_CLIENT_FORMATTER = client_server.ClientLogFormatter()


def _error_messages(caplog):
    """The ERROR records, each rendered as the Client's production JSON line."""
    return [_CLIENT_FORMATTER.format(record) for record in caplog.records if record.levelno >= logging.ERROR]


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


def test_client_likes_502_is_fixed_text_and_engine_error_is_logged(tmp_path, caplog, monkeypatch):
    caplog.set_level(logging.ERROR)
    # caplog's handler is shared by the whole session, so the formatter is swapped back at teardown.
    monkeypatch.setattr(caplog.handler, "formatter", _CLIENT_FORMATTER)
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


LOG_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
LOG_TEXT_HEAD_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z (INFO|ERROR) ")
# +05:45: a ts rendered in local time, with or without a `Z`, is off by hours and minutes here, whatever zone the host runs in.
OFF_UTC_ZONE = "Asia/Kathmandu"
LOG_EMIT_KEYS = ["ts", "level", "service", "event", "message", "context"]
LOG_BARE_KEYS = ["ts", "level", "service", "event", "message"]
LOG_API_DIR = ENGINE_SERVER_DIR / "api"

# The Client's JSON payloads for the four `_log_records` records, less `ts` and `traceback`.
CLIENT_LOG_JSON_PAYLOADS = [
    {"level": "ERROR", "service": "client-backend", "event": "engine.call", "message": "Engine metadata failed", "context": {"error": "x\ny"}},
    {"level": "ERROR", "service": "client-backend", "event": "client.log", "message": "client probe failed"},
    {"level": "INFO", "service": "client-backend", "event": "client.log", "message": "bare"},
    {"level": "INFO", "service": "client-backend", "event": "client.access", "message": "request finished", "context": {"ip": "127.0.0.1", "status": 200, "bytes": "-"}},
]

# The traceback's `\n` are the two characters backslash and n, not a line break (observed: no caret line under the raise on 3.14).
CLIENT_EXCEPTION_TEXT_RE = re.compile(r'ERROR client\.log client probe failed Traceback \(most recent call last\):\\n  File "[^"]+", line \d+, in \w+\\n    raise ValueError\("sentinel-client-log"\)\\nValueError: sentinel-client-log')

# Prints the Engine's own _format_ts for each argv `created` and its _render_text of each argv payload.
_ENGINE_RENDER_CHILD = textwrap.dedent(
    """
    import json, logging, sys
    from logging_profiles import _format_ts, _render_text
    stamps = []
    for created in json.loads(sys.argv[1]):
        record = logging.LogRecord("probe", logging.INFO, "probe", 1, "fixed", None, None)
        record.created = created
        stamps.append(_format_ts(record))
    print(json.dumps({"ts": stamps, "text": [_render_text(payload) for payload in json.loads(sys.argv[2])]}))
    """
)

RENDER_CREATED = [1741091696.789, 1741091696.9999996]
# The second payload takes the branches the first skips: no message, request_id only at top level, a CR.
RENDER_PAYLOADS = [
    {"ts": "2025-03-04T12:34:57.000Z", "level": "INFO", "event": "e", "message": "m\nn", "context": {"a": 1, "b": None, "c": [1, {"d": "x"}], "request_id": "r"}, "request_id": "r", "traceback": "T\nU"},
    {"ts": "2025-03-04T12:34:56.789Z", "level": "ERROR", "event": "service.lifecycle", "context": {"state": "start", "note": "a\rb"}, "request_id": "q"},
]
# Observed from the Engine child: CR/LF escaped, None as null, the list as compact JSON, request_id written once from the context or appended from the top level.
ENGINE_RENDER_TEXTS = ['2025-03-04T12:34:57.000Z INFO e m\\nn a=1 b=null c=[1,{"d":"x"}] request_id=r T\\nU', "2025-03-04T12:34:56.789Z ERROR service.lifecycle state=start note=a\\rb request_id=q"]


@contextmanager
def _client_logging(monkeypatch, value):
    """Run configure_client_logging under LOG_FORMAT=value; yield the stream it writes to."""
    # Saved and restored in the test body, so pytest's own capture handlers come back for later tests.
    root = logging.getLogger()
    saved_handlers, saved_level = root.handlers[:], root.level
    if value is None:
        monkeypatch.delenv("LOG_FORMAT", raising=False)
    else:
        monkeypatch.setenv("LOG_FORMAT", value)
    try:
        client_server.configure_client_logging()
        stream = io.StringIO()
        root.handlers[0].setStream(stream)
        yield stream
    finally:
        root.handlers[:] = saved_handlers
        root.setLevel(saved_level)


def _epoch(ts: str) -> float:
    """Read a `LOG_TS_RE` timestamp back as UTC epoch seconds."""
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc).timestamp()


def _fixed_record(created: float) -> logging.LogRecord:
    """A bare record whose creation time is `created`."""
    record = logging.LogRecord("probe", logging.INFO, "probe", 1, "fixed", None, None)
    record.created = created
    return record


def _log_records(monkeypatch, value) -> list[str]:
    """Log the four records under LOG_FORMAT=value; return the physical lines written."""
    with _client_logging(monkeypatch, value) as stream:
        client_server._emit_client_log(logging.ERROR, "engine.call", "Engine metadata failed", {"error": "x\ny"})
        try:
            raise ValueError("sentinel-client-log")
        except ValueError:
            logging.exception("client probe failed")
        logging.info("bare")
        client_server._emit_client_log(logging.INFO, "client.access", "request finished", {"ip": "127.0.0.1", "status": 200, "bytes": "-"})
    # splitlines breaks on CR as well as LF, so an unescaped CR or LF adds a line here.
    return stream.getvalue().splitlines()


def _json_object(line: str) -> dict | None:
    """The line parsed as a JSON object, or None."""
    try:
        parsed = json.loads(line)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


def test_client_records_leave_as_json_lines_in_client_key_order_with_utc_ts_and_bare_ones_as_client_log(monkeypatch):
    monkeypatch.setenv("TZ", OFF_UTC_ZONE)
    time.tzset()
    try:
        with _client_logging(monkeypatch, None) as stream:
            before = time.time()
            client_server._emit_client_log(logging.ERROR, "engine.call", "Engine metadata failed", {"error": "x\ny"})
            try:
                raise ValueError("sentinel-client-log")
            except ValueError:
                logging.exception("client probe failed")
            logging.info("bare")
            client_server._emit_client_log(logging.INFO, "probe.empty", "empty context", {})
            client_server._emit_client_log(logging.INFO, "probe.none", "no context")
            after = time.time()
            handler = logging.getLogger().handlers[0]
            fixed = json.loads(handler.format(_fixed_record(1741091696.789)))
            rounded = json.loads(handler.format(_fixed_record(1741091696.9999996)))
    finally:
        monkeypatch.undo()
        time.tzset()

    # One record is one line: a traceback or bare text written outside the formatter would add or replace lines.
    lines = stream.getvalue().splitlines()
    assert len(lines) == 5, lines
    payloads = [json.loads(line) for line in lines]
    assert all(isinstance(payload, dict) for payload in payloads), lines
    emitted, failed, bare, empty, none = payloads

    assert list(emitted) == LOG_EMIT_KEYS, emitted
    assert (emitted["level"], emitted["service"], emitted["event"], emitted["message"], emitted["context"]) == ("ERROR", "client-backend", "engine.call", "Engine metadata failed", {"error": "x\ny"}), emitted
    # An empty or missing context is omitted, not written as {} or null.
    assert (list(empty), empty["event"], empty["message"]) == (LOG_BARE_KEYS, "probe.empty", "empty context"), empty
    assert (list(none), none["event"], none["message"]) == (LOG_BARE_KEYS, "probe.none", "no context"), none

    stamps = [payload["ts"] for payload in payloads]
    assert all(LOG_TS_RE.fullmatch(ts) for ts in stamps), stamps
    # A local-time rendering with a `Z` reads back 5h45m outside the window; one second covers the millisecond truncation.
    assert all(before - 1 <= _epoch(ts) <= after + 1 for ts in stamps), (before, after, stamps)
    # The record's `created` in UTC, not the formatting time; milliseconds truncated without rounding to the microsecond first give 56.999.
    assert (fixed["ts"], rounded["ts"]) == ("2025-03-04T12:34:56.789Z", "2025-03-04T12:34:57.000Z"), (fixed, rounded)

    assert list(bare) == LOG_BARE_KEYS, bare
    assert (bare["level"], bare["service"], bare["event"], bare["message"]) == ("INFO", "client-backend", "client.log", "bare"), bare
    assert list(failed) == LOG_BARE_KEYS + ["traceback"], failed
    assert (failed["level"], failed["service"], failed["event"], failed["message"]) == ("ERROR", "client-backend", "client.log", "client probe failed"), failed
    assert failed["traceback"].startswith("Traceback (most recent call last):") and failed["traceback"].endswith("ValueError: sentinel-client-log"), failed["traceback"]


@pytest.mark.parametrize("value", [None, "json", "JSON", "bogus", ""])
def test_client_log_format_unset_empty_json_or_unknown_writes_json_lines(monkeypatch, value):
    lines = _log_records(monkeypatch, value)
    payloads = [_json_object(line) for line in lines]
    assert len(lines) == 4 and all(payload is not None for payload in payloads), lines

    assert all(LOG_TS_RE.fullmatch(payload.pop("ts")) for payload in payloads), lines
    traceback = payloads[1].pop("traceback")
    assert traceback.startswith("Traceback (most recent call last):") and traceback.endswith("ValueError: sentinel-client-log"), traceback
    assert [list(payload.items()) for payload in payloads] == [list(payload.items()) for payload in CLIENT_LOG_JSON_PAYLOADS], payloads


@pytest.mark.parametrize("value", ["text", "TEXT", " Text ", "\ttext\n"])
def test_client_log_format_text_writes_the_engines_escaped_text_line_per_record(monkeypatch, value):
    lines = _log_records(monkeypatch, value)
    # The multi-line context value and traceback would each add lines if left unescaped.
    assert len(lines) == 4, lines

    assert all(LOG_TEXT_HEAD_RE.match(line) for line in lines), lines
    assert all(_json_object(line) is None for line in lines), lines
    assert not any(line.startswith("<") for line in lines), lines

    stamps, rests = zip(*(line.split(" ", 1) for line in lines))
    assert all(LOG_TS_RE.fullmatch(ts) for ts in stamps), stamps
    emitted, failed, bare, access = rests
    # The `\n` is a backslash and an n, written into the one physical line.
    assert emitted == "ERROR engine.call Engine metadata failed error=x\\ny", emitted
    assert CLIENT_EXCEPTION_TEXT_RE.fullmatch(failed), failed
    assert bare == "INFO client.log bare", bare
    # The Engine's shape: no `service` token, the context as k=v, a non-string value as JSON.
    assert access == "INFO client.access request finished ip=127.0.0.1 status=200 bytes=-", access


def test_client_format_ts_and_render_text_return_the_engines_strings():
    # logging_profiles imports only the stdlib and request_context, so pytest's own interpreter can run it.
    run = subprocess.run([sys.executable, "-c", _ENGINE_RENDER_CHILD, json.dumps(RENDER_CREATED), json.dumps(RENDER_PAYLOADS)], cwd=LOG_API_DIR, capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stderr[-2000:]
    engine = json.loads(run.stdout)
    # Control: the child really rendered, so equality below compares real strings rather than empty ones.
    assert engine == {"ts": ["2025-03-04T12:34:56.789Z", "2025-03-04T12:34:57.000Z"], "text": ENGINE_RENDER_TEXTS}, engine

    client_stamps = [client_server._format_ts(_fixed_record(created)) for created in RENDER_CREATED]
    assert client_stamps == engine["ts"], (client_stamps, engine["ts"])
    client_texts = [client_server._render_text(payload) for payload in RENDER_PAYLOADS]
    assert client_texts == engine["text"], client_texts


REFRESH_ROUTE = "/api/video/refresh"
REFRESH_QUERY = "id=uuid-1&host=tube.example"
REFRESH_FORWARDED = {"id": ["uuid-1"], "host": ["tube.example"]}
REFRESH_ANSWER = {"videoUuid": "uuid-1", "title": "Refreshed"}


def _refresh_engine_stub(received, delay):
    class EngineStub(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            url = urlparse(self.path)
            received.append((url.path, parse_qs(url.query)))
            time.sleep(delay)
            body = json.dumps(REFRESH_ANSWER).encode("utf-8")
            try:
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                # The proxy gave up on a slow answer and closed the socket, which is the case under test.
                pass

        def log_message(self, format, *args):
            pass

    return EngineStub


def _get_json(base, path):
    try:
        with urllib.request.urlopen(base + path, timeout=30) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"null")


def test_a_refresh_reaches_the_engine_with_only_id_and_host_and_any_other_or_repeated_key_answers_400(tmp_path):
    received = []
    with _serving(ThreadingHTTPServer(("127.0.0.1", 0), _refresh_engine_stub(received, 0))) as engine_base, _client_backend(tmp_path, engine_base, RateLimiter(1000, 60)) as base:
        # The /api/video allow-list takes user_id and refresh_cache (observed 200, user_id forwarded), foo is in no allow-list, and each allowed key is repeated once; unrouted, all answer 404 (observed).
        refused = [_status(base, "GET", f"{REFRESH_ROUTE}?{query}", {}) for query in (f"{REFRESH_QUERY}&user_id=u-1", f"{REFRESH_QUERY}&refresh_cache=1", f"{REFRESH_QUERY}&foo=1", f"id=uuid-2&{REFRESH_QUERY}", f"{REFRESH_QUERY}&host=other.example")]
        answered = _get_json(base, f"{REFRESH_ROUTE}?{REFRESH_QUERY}")
    assert refused == [400, 400, 400, 400, 400]
    assert answered == (200, REFRESH_ANSWER)
    # Sent before the allowed refresh, a refused one reaching the Engine would stand first here.
    assert received == [(REFRESH_ROUTE, REFRESH_FORWARDED)]


def test_a_refresh_that_times_out_at_the_proxy_is_sent_once_and_answered_502(tmp_path, monkeypatch):
    received = []
    # The mapping is a module global read per request; raising=False lets a server without it reach the refresh's own answer instead of stopping on the missing name.
    monkeypatch.setattr(client_server, "ENGINE_PROXY_ROUTE_TIMEOUT_SECONDS", {**getattr(client_server, "ENGINE_PROXY_ROUTE_TIMEOUT_SECONDS", {}), REFRESH_ROUTE: 0.3}, raising=False)
    with _serving(ThreadingHTTPServer(("127.0.0.1", 0), _refresh_engine_stub(received, 1.5))) as engine_base, _client_backend(tmp_path, engine_base, RateLimiter(1000, 60)) as base:
        # Under the shared 10 s timeout the 1.5 s answer arrives and this is 200; under the shared retry it is sent twice.
        refresh_status = _status(base, "GET", f"{REFRESH_ROUTE}?{REFRESH_QUERY}", {})
        refresh_sent = list(received)
        received.clear()
        monkeypatch.setattr(client_server, "ENGINE_PROXY_TIMEOUT_SECONDS", 0.3)
        video_status = _status(base, "GET", f"/api/video?{REFRESH_QUERY}", {})
    assert refresh_status == 502
    assert refresh_sent == [(REFRESH_ROUTE, REFRESH_FORWARDED)]
    # guard: the same sleeping Engine still gets /api/video twice, so the single refresh is the refresh's own retry count and not retries dropped for every route.
    assert (video_status, received) == (502, [("/api/video", REFRESH_FORWARDED)] * 2)


MODE_PAGE = 8
# Its own rate-limit bucket at the session Engine, which allows 60 requests a minute per client IP and path; other tests share 127.0.0.1's.
MODE_HEADERS = {"X-Client-IP": "192.0.2.175"}
# The gateway trusts its loopback peer, so this is the address it resolves and sends the Engine as X-Client-IP.
MODE_GATEWAY_HEADERS = {"X-Forwarded-For": "192.0.2.175"}

# Runs under the Engine interpreter: importing handlers.similar needs numpy and faiss, which only its pixi env carries.
# A missing FEED_MODES prints null rather than failing the import, so the import stays a control and the constant's absence reaches the assertion.
_FEED_MODES_CHILD = textwrap.dedent(
    """
    import json, sys
    sys.path[:0] = [sys.argv[1], sys.argv[2]]
    import handlers.similar as similar
    print(json.dumps(list(similar.FEED_MODES) if hasattr(similar, "FEED_MODES") else None))
    """
)


def _feed_modes() -> list[str] | None:
    assert ENGINE_PY.exists(), f"Engine interpreter missing at {ENGINE_PY}; run `pixi install` in engine/"
    run = subprocess.run([str(ENGINE_PY), "-c", _FEED_MODES_CHILD, str(ENGINE_SERVER_DIR), str(ENGINE_SERVER_DIR / "api")], cwd=ENGINE_SERVER_DIR / "api", capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stderr[-2000:]  # control: the Engine's interpreter imported handlers.similar
    return json.loads(run.stdout.strip().splitlines()[-1])


def test_the_gateway_passes_the_engines_unknown_mode_400_through(engine, engine_client):
    path = f"/recommendations?mode=bogus&limit={MODE_PAGE}"
    status, body = engine_client.request("POST", path, headers=MODE_GATEWAY_HEADERS, body={})
    # A gateway forwarding mode to an Engine that ignores it answers 200 with a home page (observed before validation).
    assert (status, body.get("error")) == (400, "Unknown mode"), (status, body.get("seed"))
    # The Engine's own answer to the same request: a gateway that dropped mode, refused it itself or wrapped the 400 differs from it.
    assert (status, body) == engine.request("POST", path, headers=MODE_HEADERS, body={})
    assert body == {"error": "Unknown mode", "allowed": _feed_modes()}


GATEWAY_HOST = "g.example"
CLEAN_A = {"video_id": "vid-a", "video_uuid": "u-a", "instance_domain": GATEWAY_HOST, "channel_id": "ch-a", "account_url": "https://g.example/a/one", "title": "A"}
BLOCKED = {"video_id": "vid-b", "video_uuid": "u-b", "instance_domain": GATEWAY_HOST, "channel_id": "ch-blocked", "account_url": "https://g.example/a/two", "title": "B"}
CLEAN_C = {"video_id": "vid-c", "video_uuid": "u-c", "instance_domain": GATEWAY_HOST, "channel_id": "ch-a", "account_url": "https://g.example/a/one", "title": "C"}
# Same channel and account as the clean rows, so only the dislike can remove it.
DISLIKED = {"video_id": "vid-d", "video_uuid": "u-d", "instance_domain": GATEWAY_HOST, "channel_id": "ch-a", "account_url": "https://g.example/a/one", "title": "D"}
GATEWAY_ROWS = [CLEAN_A, BLOCKED, CLEAN_C, DISLIKED]
GATEWAY_PAGE = 10


def _ordered_keys(rows: list[dict]) -> list[tuple[str, str]]:
    return [(r["video_id"], r["instance_domain"]) for r in rows]


def _hot_engine(received: list):
    """A stand-in Engine answering every POST with GATEWAY_ROWS, in order, recording each request's path."""

    class EngineStub(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            self.rfile.read(int(self.headers.get("content-length") or 0))
            received.append(self.path)
            data = json.dumps({"seed": {}, "count": len(GATEWAY_ROWS), "rows": GATEWAY_ROWS}).encode("utf-8")
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format, *args):
            pass

    return ThreadingHTTPServer(("127.0.0.1", 0), EngineStub)


def test_a_keyed_hot_page_drops_the_blocked_channel_and_disliked_video_and_asks_the_engine_for_twice_the_page(tmp_path):
    received: list[str] = []
    path = f"/recommendations?mode=hot&limit={GATEWAY_PAGE}"
    with _serving(_hot_engine(received)) as engine_base, _client_backend(tmp_path, engine_base, RateLimiter(1000, 60)) as base:
        client = ClientBackend(base, tmp_path / "users.db")
        status, unkeyed = client.request("POST", path, body={})
        assert status == 200, unkeyed
        status, minted = client.request("POST", "/api/profile")
        assert status == 201, minted
        conn = client_server.connect_db(client.db_path)
        try:
            profile_id = resolve_profile(conn, minted["key"])
            assert profile_id == minted["profile_id"]  # control: the second connection sees the minted profile
            add_block(conn, profile_id, block_target("channel", BLOCKED))
            with conn:
                write_dislike(conn, profile_id, DISLIKED, None)
        finally:
            conn.close()
        status, keyed = client.request("POST", path, headers={"X-Profile-Key": minted["key"]}, body={})
        assert status == 200, keyed

    assert len(received) == 2, received  # control: one Engine request per page
    # Control: with no profile nothing is filtered, so the page is the Engine's four rows under the limit sent.
    assert (urlparse(received[0]).path, parse_qs(urlparse(received[0]).query)) == ("/recommendations", {"mode": ["hot"], "limit": [str(GATEWAY_PAGE)]}), received[0]
    assert _ordered_keys(unkeyed["rows"]) == _ordered_keys(GATEWAY_ROWS), unkeyed["rows"]
    assert _ordered_keys(keyed["rows"]) == _ordered_keys([CLEAN_A, CLEAN_C]), keyed["rows"]  # blocked channel and disliked video absent, Engine order kept
    assert (urlparse(received[1]).path, parse_qs(urlparse(received[1]).query)) == ("/recommendations", {"mode": ["hot"], "limit": [str(2 * GATEWAY_PAGE)]}), received[1]  # mode forwarded, limit doubled


# The gateway's NSFW opt-in: nsfw is forwarded unstripped on the three listing routes, and refused elsewhere.
# One fresh address per request from the benchmark range, clear of the 192.0.2.x buckets the rest of tests/active uses.
NSFW_CLIENT_IPS = (f"198.19.{n // 250}.{n % 250 + 1}" for n in itertools.count())
# 84 of the top 100 matches are flagged (observed).
NSFW_SEARCH_QUERY = "hentai"
NSFW_SEARCH_LIMIT = 100
# Every value but exactly "1"; parse_qs drops the empty one, so it arrives as missing.
NSFW_VALUES = {"missing": "", "empty": "&nsfw=", "0": "&nsfw=0", "true": "&nsfw=true", "space-1": f"&nsfw={quote(' 1')}"}
# Up-next for a flagged seed, not a feed order: the newest flagged video sat 84th in recent after the 57c8417 rebuild, past the gateway's 48-row cap. This seed's 48-row draws on both routes carried 5 to 9 flagged rows in 10 of 10 (observed).
NSFW_SEED = "id=59b6239b-15c6-4bc4-b5e6-6ebac4ea9751&host=810video.com"
NSFW_GATEWAY_LISTINGS = {
    "/recommendations": ("POST", f"/recommendations?{NSFW_SEED}", {}),
    "/videos/similar": ("POST", f"/videos/similar?{NSFW_SEED}", {}),
    "/api/v1/search/videos": ("GET", f"/api/v1/search/videos?q={NSFW_SEARCH_QUERY}&limit={NSFW_SEARCH_LIMIT}", None),
}


@pytest.fixture(scope="module")
def nsfw_flagged(dataset) -> set[tuple[str, str]]:
    keys = {(r["video_id"], r["instance_domain"]) for r in dataset.execute("SELECT video_id, instance_domain FROM videos WHERE nsfw = 1")}
    assert keys, "control: whitelist.db flags no video nsfw = 1"
    return keys


def _nsfw_keys(client, method: str, path: str, body: dict | None) -> list[tuple[str, str]]:
    status, payload = client.request(method, path, headers={"X-Forwarded-For": next(NSFW_CLIENT_IPS)}, body=body)
    assert status == 200 and isinstance(payload, dict) and "rows" in payload, (path[:160], status, payload)
    return [(r["video_id"], r["instance_domain"]) for r in payload["rows"]]


@pytest.mark.parametrize("nsfw", NSFW_VALUES)
@pytest.mark.parametrize("route", NSFW_GATEWAY_LISTINGS)
def test_a_gateway_listing_request_without_exactly_nsfw_1_gets_no_flagged_row_where_nsfw_1_gets_some(engine_client, nsfw_flagged, route, nsfw):
    method, path, body = NSFW_GATEWAY_LISTINGS[route]
    # A gateway refusing nsfw answers 400 here, and one dropping or rewriting it gets the Engine's filtered page.
    assert set(_nsfw_keys(engine_client, method, f"{path}&nsfw=1", body)) & nsfw_flagged, f"control: {route} with nsfw=1 served no flagged row"
    keys = _nsfw_keys(engine_client, method, f"{path}{NSFW_VALUES[nsfw]}", body)
    assert keys, f"{route} served an empty page"
    # A gateway stripping the values it forwards turns " 1" into the opt-in; "true" and "0" catch one that normalises or opts in on the key alone.
    assert not set(keys) & nsfw_flagged, sorted(set(keys) & nsfw_flagged)[:5]


def test_the_gateway_still_refuses_nsfw_on_api_video(client_backend):
    status, body = client_backend.request("GET", "/api/video?id=x&host=y")
    assert status == 502, (status, body)  # control: without nsfw the request passes the allowlist and is proxied to the closed Engine port
    status, body = client_backend.request("GET", "/api/video?id=x&host=y&nsfw=1")
    assert (status, body) == (400, {"error": "Unknown query parameter: nsfw"})  # the opt-in is allowlisted on the three listing routes only


TRANSLATE_ROUTE = "/api/translate"
TRANSLATE_BRIDGE_TOKEN = "translate-bridge-token"
TRANSLATE_VALID = "id=uuid-1&host=peer.example"
TRANSLATE_FAILED = (502, {"error": "Engine translate failed"})
TRANSLATE_UNAUTHORIZED = (401, {"error": "Profile key required"})
TRANSLATE_RATE_LIMITED = (429, {"error": "Rate limit exceeded"})
TRANSLATE_READY = {"state": "ready", "cues": [{"start": 1.0, "end": 2.5, "text": "Hello"}], "available": False}
# Each bad query a keyed request is refused 400 for, and the error text where the shared allow-list rule fixes it (None: any error text).
TRANSLATE_BAD_QUERIES = {
    "unknown param": (f"{TRANSLATE_VALID}&lang=fr", "Unknown query parameter: lang"),
    "repeated id": ("id=uuid-1&id=uuid-2&host=peer.example", "Multiple values are not allowed for query parameter: id"),
    "blank id": ("id=&host=peer.example", None),
    "whitespace id": ("id=%20%20&host=peer.example", None),
    "missing host": ("id=uuid-1", None),
    "no params": ("", None),
    "201-character id": (f"id={'a' * 201}&host=peer.example", None),
    "201-character host": (f"id=uuid-1&host={'h' * 201}", None),
}
# What the Engine answers -> what the visitor gets.
TRANSLATE_ENGINE_ANSWERS = {
    "route missing": ((404, {"error": "Not found"}), TRANSLATE_FAILED),
    "engine 500": ((500, {"error": "translate-engine-sentinel"}), TRANSLATE_FAILED),
    "cues not a list": ((200, {"state": "ready", "cues": {"start": 1.0, "end": 2.5, "text": "Hello"}}), TRANSLATE_FAILED),
    "start true": ((200, {"state": "ready", "cues": [{"start": True, "end": 2.5, "text": "Hello"}]}), TRANSLATE_FAILED),
    "text not a string": ((200, {"state": "ready", "cues": [{"start": 1.0, "end": 2.5, "text": 7}]}), TRANSLATE_FAILED),
}


class _TranslateEngine(BaseHTTPRequestHandler):
    """Records each request as (method, path, X-Bridge-Token, X-Request-ID, JSON body) and answers `server.reply`, a (status, payload) pair."""

    def do_POST(self):  # noqa: N802
        raw = self.rfile.read(int(self.headers.get("content-length") or 0))
        self.server.seen.append((self.command, self.path, self.headers.get("X-Bridge-Token"), self.headers.get("X-Request-ID"), json.loads(raw) if raw else None))
        status, payload = self.server.reply
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    # A route that proxied by GET instead of the bridge POST would be recorded too.
    do_GET = do_POST

    def log_message(self, *args):
        pass


@contextmanager
def _translate_engine(reply):
    """A _TranslateEngine on 127.0.0.1:0 answering `reply`; yields its base URL and its request log."""
    stub = ThreadingHTTPServer(("127.0.0.1", 0), _TranslateEngine)
    stub.seen = []
    stub.reply = reply
    with _serving(stub) as base:
        yield base, stub.seen


@contextmanager
def _keyed_client_backend(tmp_path, engine_base, rate_limiter):
    """`_client_backend` holding one minted profile; yields its base URL and that profile's key header."""
    conn = client_server.connect_db(tmp_path / "users.db")
    ensure_user_schema(conn)
    _, key = mint_profile(conn)
    try:
        with _serving(client_server.ClientBackendServer(("127.0.0.1", 0), client_server.ClientBackendHandler, conn, engine_base, "bridge", rate_limiter)) as base:
            yield base, {"X-Profile-Key": key}
    finally:
        conn.close()


def _translate_get(base, query, headers):
    req = urllib.request.Request(f"{base}{TRANSLATE_ROUTE}?{query}" if query else base + TRANSLATE_ROUTE, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"null")


@pytest.fixture
def translate_bridge_token(monkeypatch):
    monkeypatch.setenv("ENGINE_BRIDGE_TOKEN", TRANSLATE_BRIDGE_TOKEN)


def test_a_rate_limited_request_is_429_before_the_profile_and_param_checks_with_no_engine_call(tmp_path, translate_bridge_token):
    limiter = RateLimiter(1, 60)
    with _translate_engine((200, TRANSLATE_READY)) as (engine_base, seen), _keyed_client_backend(tmp_path, engine_base, limiter) as (base, key):
        first = _translate_get(base, TRANSLATE_VALID, {})
        limited = {"keyless with an unknown param": _translate_get(base, f"{TRANSLATE_VALID}&lang=fr", {}), "keyed and valid": _translate_get(base, TRANSLATE_VALID, key)}
        limited_seen = list(seen)
        # Emptied, the limiter lets the same keyed valid request through, so the empty log above is the 429's doing.
        limiter.requests.clear()
        unlimited = _translate_get(base, TRANSLATE_VALID, key)
    assert limited == dict.fromkeys(limited, TRANSLATE_RATE_LIMITED)  # 429, not 401 or 400
    assert limited_seen == []
    # Control: the limiter let the first request through, so the route's own keyless answer is 401, and an unlimited keyed valid request reaches the Engine.
    assert first == TRANSLATE_UNAUTHORIZED
    assert unlimited == (200, TRANSLATE_READY)
    assert [entry[:2] for entry in seen] == [("POST", "/internal/translate")]


def test_a_keyless_request_with_bad_params_is_401_not_400_with_no_engine_call(tmp_path, translate_bridge_token):
    with _translate_engine((200, TRANSLATE_READY)) as (engine_base, seen), _keyed_client_backend(tmp_path, engine_base, RateLimiter(1000, 60)) as (base, key):
        keyless = {name: _translate_get(base, query, {}) for name, query in (("unknown param", f"{TRANSLATE_VALID}&lang=fr"), ("repeated id", "id=uuid-1&id=uuid-2&host=peer.example"), ("missing host", "id=uuid-1"), ("no params", ""))}
        wrong_key = _translate_get(base, f"{TRANSLATE_VALID}&lang=fr", {"X-Profile-Key": "not-a-profile-key"})
        refused_seen = list(seen)
        allowed = _translate_get(base, TRANSLATE_VALID, key)
    assert keyless == dict.fromkeys(keyless, TRANSLATE_UNAUTHORIZED)
    assert wrong_key == TRANSLATE_UNAUTHORIZED
    assert refused_seen == []
    # Control: the same server's keyed valid request does reach the Engine, so the empty log above is the 401's doing.
    assert allowed == (200, TRANSLATE_READY)
    assert [entry[:2] for entry in seen] == [("POST", "/internal/translate")]


def test_each_bad_param_is_400_with_no_engine_call_and_a_valid_request_reaches_the_bridge_route_with_token_request_id_and_stripped_id_host(tmp_path, translate_bridge_token):
    with _translate_engine((200, TRANSLATE_READY)) as (engine_base, seen), _keyed_client_backend(tmp_path, engine_base, RateLimiter(1000, 60)) as (base, key):
        refused = {name: _translate_get(base, query, key) for name, (query, _) in TRANSLATE_BAD_QUERIES.items()}
        refused_seen = list(seen)
        # Sent after every refusal, so a refused request reaching the Engine would stand first in its log.
        stripped = _translate_get(base, "id=%20uuid-1%20&host=%20peer.example%20", {**key, "X-Request-ID": "translate-req-1"})
        longest = _translate_get(base, f"id={'a' * 200}&host=peer.example", {**key, "X-Request-ID": "translate-req-2"})
    assert {name: status for name, (status, _) in refused.items()} == dict.fromkeys(TRANSLATE_BAD_QUERIES, 400)
    assert {name: body.get("error") for name, (_, body) in refused.items() if TRANSLATE_BAD_QUERIES[name][1]} == {name: text for name, (_, text) in TRANSLATE_BAD_QUERIES.items() if text}  # the shared allow-list texts
    assert all(isinstance(body.get("error"), str) and body["error"] for _, body in refused.values()), refused
    assert refused_seen == []
    # Control: valid requests, the 200-character id included (one under the 201 refused above), reach the Engine's bridge route.
    assert stripped == (200, TRANSLATE_READY)
    assert longest == (200, TRANSLATE_READY)
    assert seen == [
        ("POST", "/internal/translate", TRANSLATE_BRIDGE_TOKEN, "translate-req-1", {"id": "uuid-1", "host": "peer.example"}),
        ("POST", "/internal/translate", TRANSLATE_BRIDGE_TOKEN, "translate-req-2", {"id": "a" * 200, "host": "peer.example"}),
    ]


@pytest.mark.parametrize("engine_reply, expected", TRANSLATE_ENGINE_ANSWERS.values(), ids=TRANSLATE_ENGINE_ANSWERS.keys())
def test_the_engine_answer_reaches_the_visitor_as_none_or_a_fixed_502(tmp_path, translate_bridge_token, engine_reply, expected):
    with _translate_engine(engine_reply) as (engine_base, seen), _keyed_client_backend(tmp_path, engine_base, RateLimiter(1000, 60)) as (base, key):
        answered = _translate_get(base, TRANSLATE_VALID, key)
    assert answered == expected
    # Control: the answer under test is the Engine's, from one bridge call.
    assert [entry[:2] for entry in seen] == [("POST", "/internal/translate")]


def test_an_unreachable_engine_is_a_fixed_502(tmp_path, translate_bridge_token):
    with _keyed_client_backend(tmp_path, CLOSED_ENGINE, RateLimiter(1000, 60)) as (base, key):
        assert _translate_get(base, TRANSLATE_VALID, key) == TRANSLATE_FAILED


def test_a_ready_answer_reaches_the_visitor_with_only_start_end_and_text_per_cue(tmp_path, translate_bridge_token):
    engine_cues = [
        {"start": 1.0, "end": 2.5, "text": "Hello", "id": "c1", "voice": "narrator"},
        {"start": 3, "end": 4.25, "text": "World", "settings": "line:0"},
    ]
    with _translate_engine((200, {"state": "ready", "cues": engine_cues, "available": False})) as (engine_base, seen), _keyed_client_backend(tmp_path, engine_base, RateLimiter(1000, 60)) as (base, key):
        answered = _translate_get(base, TRANSLATE_VALID, key)
    assert answered == (200, {"state": "ready", "cues": [{"start": 1.0, "end": 2.5, "text": "Hello"}, {"start": 3, "end": 4.25, "text": "World"}], "available": False})
    # Control: the answer under test is the Engine's, from one bridge call.
    assert [entry[:2] for entry in seen] == [("POST", "/internal/translate")]
