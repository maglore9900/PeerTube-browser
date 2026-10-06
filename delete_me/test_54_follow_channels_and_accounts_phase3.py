"""The Client gateway's unseeded `POST /recommendations?mode=following`, in front of a stand-in Engine that records each request and answers seven rows and a cursor:

- For a keyed profile holding follows, likes, a dislike with centroids, a channel block and an account block, the Engine receives exactly the profile's followed (instance_domain, channel_id) pairs and account URLs, and no `likes`, `dislike_centroids` or `exclude`, though the browser sent likes and exclude; another profile's follow is not among them. The query reaches it as `mode=following` and `limit=3`, the page size and not twice it.
- A keyed profile holding nothing but one account follow gets that follow sent, at `limit=3`.
- The served page carries the stand-in's cursor, drops the blocked channel's, the blocked account's and the disliked video's rows, and serves all four other rows in the Engine's order, past the page size of three.
- A keyless request reaches the Engine with no `follows`, at `limit=3`, and is served all seven rows and the cursor.
- A body carrying `follows`, keyed or keyless, answers 400 `Unknown body field: follows`; a cursor that is not a string, is empty, holds `+`, `=` or a space, or runs 1025 characters answers 400 `Invalid cursor payload`; none reaches the Engine. A cursor of URL-safe characters, the stand-in's own or one of 1024 characters, reaches the Engine unchanged, with the follows still sent.
- The same profile seeded (`id` and `host` with `mode=following`), and with `mode` recommendations, trending, recent, random, popular or absent, still sends its stored like and its centroids, keeps the browser's exclude, sends no `follows`, asks for `limit=6` and is served three rows.

Against the real Engine (`engine_client`): a profile following one catalogue channel by its key gets a first page of five that is the Engine's own answer to that one follow, cursor included; the next page by that cursor is five more of that channel's videos, none repeated, the first of them strictly after the first page's last in (published_at, video_id, instance_domain) order, published_at read from whitelist.db.
"""
from __future__ import annotations

import json
import sys
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

# tests/active/conftest.py holds the Client and session Engine fixtures; a working-tree test sees them only by importing the chain `engine_client` and `dataset` depend on.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))
from conftest import ClientBackend, RateLimiter, client_server, dataset, engine, engine_client, ensure_user_schema, shared_trending_before, trending_seed  # noqa: E402,F401
from lib.blocks import add_block  # noqa: E402
from lib.dislikes import write_dislike  # noqa: E402
from lib.follows import add_follow  # noqa: E402
from lib.profiles import resolve_profile  # noqa: E402
from lib.users_store import record_like  # noqa: E402

HOST = "g.example"
PAGE = 3
FOLLOWING = f"/recommendations?mode=following&limit={PAGE}"
# Opaque to the gateway; URL-safe, as the Engine's base64url cursors are.
STUB_CURSOR = "WzE3MDAwMDAwMDAwMDAsInYiLCJnIl0"
# The gateway's cursor bound (draft FEED_CURSOR_PATTERN, `[A-Za-z0-9_-]{1,1024}`).
CURSOR_MAX = 1024


def _row(n: str, channel_id: str = "ch-a", account_url: str = "https://g.example/a/one") -> dict:
    return {"video_id": f"vid-{n}", "video_uuid": f"u-{n}", "instance_domain": HOST, "channel_id": channel_id, "account_url": account_url, "title": n}


CLEAN = [_row("c0"), _row("c1"), _row("c2"), _row("c3")]
BLOCKED_CHANNEL = _row("bc", channel_id="ch-blocked", account_url="https://g.example/a/two")
BLOCKED_ACCOUNT = _row("ba", channel_id="ch-c", account_url="https://g.example/a/blocked")
# Same channel and account as the clean rows, so only the dislike can remove it.
DISLIKED = _row("d")
ENGINE_ROWS = [CLEAN[0], BLOCKED_CHANNEL, CLEAN[1], DISLIKED, CLEAN[2], BLOCKED_ACCOUNT, CLEAN[3]]

# The keyed profile's follows: one channel_id on two hosts, and two accounts.
FOLLOWED_CHANNELS = [("f1.example", "7"), ("f2.example", "7")]
FOLLOWED_ACCOUNTS = ["https://f1.example/a/alice", "https://f3.example/a/bob"]
LONE_ACCOUNT = "https://f4.example/a/carol"
BYSTANDER_CHANNEL = ("f9.example", "9")
STORED_LIKE = {"video_id": "vid-liked", "instance_domain": "l.example", "video_uuid": "u-liked"}
CENTROIDS = {"space": "probe-space", "vectors": [[0.6, 0.8]]}
BROWSER_BODY = {"likes": [{"uuid": "u-browser", "host": "b.example"}], "exclude": [{"id": "vid-x", "host": "x.example"}], "mode": "following"}


def _channel(host: str, channel_id: str) -> dict:
    return {"kind": "channel", "instance_domain": host, "channel_id": channel_id, "account_url": "", "label": channel_id}


def _account(account_url: str) -> dict:
    return {"kind": "account", "instance_domain": "", "channel_id": "", "account_url": account_url, "label": account_url}


def _recording_engine(received: list):
    """A stand-in Engine answering every POST with ENGINE_ROWS and STUB_CURSOR, recording each request's path and JSON body."""

    class EngineStub(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            raw = self.rfile.read(int(self.headers.get("content-length") or 0))
            received.append((self.path, json.loads(raw) if raw else None))
            data = json.dumps({"seed": {}, "count": len(ENGINE_ROWS), "rows": ENGINE_ROWS, "cursor": STUB_CURSOR}).encode("utf-8")
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format, *args):
            pass

    return ThreadingHTTPServer(("127.0.0.1", 0), EngineStub)


@contextmanager
def _serving(srv):
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}"
    finally:
        srv.shutdown()
        srv.server_close()


@pytest.fixture
def gateway(tmp_path):
    """A real Client backend in front of the recording Engine, with three profiles: `keyed` (follows, a like, a dislike with centroids, a channel and an account block), `lone` (one account follow and nothing else) and a bystander following another channel."""
    received: list[tuple[str, dict | None]] = []
    conn = client_server.connect_db(tmp_path / "users.db")
    ensure_user_schema(conn)
    try:
        with _serving(_recording_engine(received)) as engine_base, _serving(client_server.ClientBackendServer(("127.0.0.1", 0), client_server.ClientBackendHandler, conn, engine_base, "bridge", RateLimiter(1000, 60))) as base:
            client = ClientBackend(base, tmp_path / "users.db")
            keys = {}
            for name in ("keyed", "lone", "bystander"):
                status, minted = client.request("POST", "/api/profile")
                assert status == 201, minted
                keys[name] = minted["key"]
            store = client_server.connect_db(client.db_path)
            try:
                ids = {name: resolve_profile(store, key) for name, key in keys.items()}
                assert None not in ids.values(), ids  # control: the second connection sees the minted profiles
                for host, channel_id in FOLLOWED_CHANNELS:
                    add_follow(store, ids["keyed"], _channel(host, channel_id))
                for account_url in FOLLOWED_ACCOUNTS:
                    add_follow(store, ids["keyed"], _account(account_url))
                add_block(store, ids["keyed"], _channel(HOST, BLOCKED_CHANNEL["channel_id"]))
                add_block(store, ids["keyed"], _account(BLOCKED_ACCOUNT["account_url"]))
                record_like(store, ids["keyed"], "like", STORED_LIKE, 50)
                with store:
                    write_dislike(store, ids["keyed"], DISLIKED, CENTROIDS)
                add_follow(store, ids["lone"], _account(LONE_ACCOUNT))
                add_follow(store, ids["bystander"], _channel(*BYSTANDER_CHANNEL))
            finally:
                store.close()
            yield _Gateway(client, received, keys)
    finally:
        conn.close()


class _Gateway:
    def __init__(self, client, received, keys):
        self.client = client
        self.received = received
        self.keys = keys

    def read(self, path: str, profile: str | None, body: dict) -> tuple[int, object, list[tuple[str, dict | None]]]:
        """POST one feed read; return the status, the served payload and the Engine requests it caused."""
        before = len(self.received)
        headers = {"X-Profile-Key": self.keys[profile]} if profile else {}
        status, payload = self.client.request("POST", path, headers=headers, body=body)
        return status, payload, self.received[before:]


def _query(path: str) -> dict[str, list[str]]:
    return parse_qs(urlparse(path).query)


def _sent_follows(body: dict) -> tuple[list[tuple[str, str]], list[str]] | None:
    """The `follows` an Engine body carries, as sorted (instance_domain, channel_id) pairs and sorted account URLs; None when absent."""
    follows = body.get("follows")
    if follows is None:
        return None
    return sorted(tuple(pair) for pair in follows.get("channels", [])), sorted(follows.get("accounts", []))


def _keys(rows: list[dict]) -> list[tuple[str, str]]:
    return [(r["video_id"], r["instance_domain"]) for r in rows]


# --- C1: the Engine receives the stored follows and nothing else of the profile, at the page limit ---


def test_a_keyed_following_read_sends_exactly_the_profile_s_stored_follows_and_no_likes_centroids_or_exclude_at_the_page_limit(gateway):
    status, payload, calls = gateway.read(FOLLOWING, "keyed", BROWSER_BODY)
    assert status == 200 and len(calls) == 1, (status, payload, calls)
    path, body = calls[0]
    # The bystander's follow and the profile's own blocks are stored too; an injection reading either, or the pair reversed, differs.
    assert _sent_follows(body) == (sorted(FOLLOWED_CHANNELS), sorted(FOLLOWED_ACCOUNTS)), body  # C1
    # Today the stored like, the browser's exclude and the stored centroids all reach the Engine (observed).
    assert {"likes", "dislike_centroids", "exclude"} & body.keys() == set(), body  # C1
    # This profile blocks and dislikes, so the over-fetch asks for 6 (observed today: limit=6; the lone profile already gets 3).
    assert (urlparse(path).path, _query(path)) == ("/recommendations", {"mode": ["following"], "limit": [str(PAGE)]}), path  # C1


def test_a_keyed_profile_with_nothing_to_filter_still_sends_its_follow(gateway):
    status, payload, calls = gateway.read(FOLLOWING, "lone", BROWSER_BODY)
    assert status == 200 and len(calls) == 1, (status, payload, calls)
    path, body = calls[0]
    # An injection keyed off the row filter, which is None for this profile, sends nothing.
    assert _sent_follows(body) == ([], [LONE_ACCOUNT]), body  # C1
    assert {"likes", "dislike_centroids", "exclude"} & body.keys() == set(), body  # C1
    assert _query(path) == {"mode": ["following"], "limit": [str(PAGE)]}, path  # C1


# --- C2: the served page keeps the cursor and is filtered but not cut ---


def test_a_keyed_following_page_keeps_the_engine_s_cursor_and_serves_every_row_not_blocked_or_disliked_past_the_page_size(gateway):
    status, payload, calls = gateway.read(FOLLOWING, "keyed", BROWSER_BODY)
    assert status == 200 and len(calls) == 1, (status, payload, calls)
    assert payload.get("cursor") == STUB_CURSOR, payload  # C2
    # Four rows survive a page of three: a trim gives three, no filter gives seven (observed today: c0, c1, c2, the filter then a trim to three).
    assert _keys(payload["rows"]) == _keys(CLEAN), payload["rows"]  # C2


def test_a_keyless_following_read_reaches_the_engine_without_follows_and_is_served_the_whole_page(gateway):
    status, payload, calls = gateway.read(FOLLOWING, None, BROWSER_BODY)
    assert status == 200 and len(calls) == 1, (status, payload, calls)
    path, body = calls[0]
    assert "follows" not in body, body
    assert _query(path) == {"mode": ["following"], "limit": [str(PAGE)]}, path
    assert (_keys(payload["rows"]), payload.get("cursor")) == (_keys(ENGINE_ROWS), STUB_CURSOR), payload


# --- the browser cannot supply follows, and the cursor is checked at the edge ---


@pytest.mark.parametrize("profile", ["keyed", None])
def test_a_browser_body_carrying_follows_is_refused_400_before_the_engine(gateway, profile):
    body = {**BROWSER_BODY, "follows": {"channels": [[HOST, "ch-a"]], "accounts": []}}
    status, payload, calls = gateway.read(FOLLOWING, profile, body)
    assert (status, payload, calls) == (400, {"error": "Unknown body field: follows"}, [])


MALFORMED_CURSORS = {"int": 123, "list": [STUB_CURSOR], "object": {"c": STUB_CURSOR}, "empty": "", "plus": "abc+def", "padding": "abc=", "space": "abc def", "over-long": "a" * (CURSOR_MAX + 1)}


@pytest.mark.parametrize("name", MALFORMED_CURSORS)
def test_a_malformed_cursor_is_refused_400_before_the_engine(gateway, name):
    status, payload, calls = gateway.read(FOLLOWING, "keyed", {"cursor": MALFORMED_CURSORS[name]})
    assert (status, payload, calls) == (400, {"error": "Invalid cursor payload"}, [])


@pytest.mark.parametrize("cursor", [STUB_CURSOR, "A-_z9" + "a" * (CURSOR_MAX - 5)], ids=["engine", "longest"])
def test_a_url_safe_cursor_reaches_the_engine_unchanged_beside_the_follows(gateway, cursor):
    status, payload, calls = gateway.read(FOLLOWING, "keyed", {"cursor": cursor})
    # Today `cursor` is not an allowed body field and answers 400 (observed).
    assert status == 200 and len(calls) == 1, (status, payload, calls)
    body = calls[0][1]
    assert body.get("cursor") == cursor, body
    assert _sent_follows(body) == (sorted(FOLLOWED_CHANNELS), sorted(FOLLOWED_ACCOUNTS)), body


# --- every other read keeps the likes, centroids and over-fetch ---


OTHER_READS = {
    "seeded following": "mode=following&id=u-seed&host=g.example&",
    **{mode: f"mode={mode}&" for mode in ("recommendations", "trending", "recent", "random", "popular")},
    "no mode": "",
}


@pytest.mark.parametrize("name", OTHER_READS)
def test_a_seeded_following_read_and_every_other_mode_keep_the_profile_s_like_centroids_exclude_and_doubled_limit(gateway, name):
    path = f"/recommendations?{OTHER_READS[name]}limit={PAGE}"
    status, payload, calls = gateway.read(path, "keyed", BROWSER_BODY)
    assert status == 200 and len(calls) == 1, (status, payload, calls)
    sent_path, body = calls[0]
    # The browser body says mode following in every case, so a gate reading the body's mode, or ignoring the seed, breaks these.
    assert body.get("likes") == [{"uuid": STORED_LIKE["video_uuid"], "host": STORED_LIKE["instance_domain"]}], body
    assert body.get("dislike_centroids") == CENTROIDS, body
    assert body.get("exclude") == BROWSER_BODY["exclude"], body
    assert "follows" not in body, body
    assert _query(sent_path)["limit"] == [str(2 * PAGE)], sent_path
    assert _keys(payload["rows"]) == _keys(CLEAN[:PAGE]), payload["rows"]


# --- the real Engine behind the real gateway: two cursor pages of one followed channel ---


WALK_PAGE = 5


def _published_key(dataset, row: dict) -> tuple[int, str, str]:
    published_at = dataset.execute("SELECT published_at FROM videos WHERE video_id = ? AND instance_domain = ?", (row["video_id"], row["instance_domain"])).fetchone()[0]
    return published_at, row["video_id"], row["instance_domain"]


def test_a_followed_channel_is_walked_through_the_gateway_in_two_cursor_pages_the_second_strictly_after_the_first(engine, engine_client, dataset):
    # The smallest channel with more than two pages of served, dated videos (810video.com 1699, 12 videos, observed).
    host, channel_id = dataset.execute(
        "SELECT v.instance_domain, v.channel_id FROM videos v JOIN video_embeddings e ON e.video_id = v.video_id AND e.instance_domain = v.instance_domain "
        "WHERE v.error_count = 0 AND (v.nsfw IS NULL OR v.nsfw = 0) AND v.published_at IS NOT NULL "
        "GROUP BY v.instance_domain, v.channel_id HAVING COUNT(*) > ? ORDER BY COUNT(*), v.instance_domain, v.channel_id LIMIT 1",
        (2 * WALK_PAGE,),
    ).fetchone()
    status, minted = engine_client.request("POST", "/api/profile")
    assert status == 201, minted
    headers = {"X-Profile-Key": minted["key"]}
    status, body = engine_client.request("POST", "/api/profile/follows", headers=headers, body={"kind": "channel", "instance_domain": host, "channel_id": channel_id})
    assert status == 201, body  # control: the follow is stored
    path = f"/recommendations?mode=following&limit={WALK_PAGE}"

    status, direct = engine.request("POST", path, body={"follows": {"channels": [[host, channel_id]], "accounts": []}})
    assert status == 200 and len(direct["rows"]) == WALK_PAGE and direct.get("cursor"), direct  # control: the Engine pages this channel
    status, first = engine_client.request("POST", path, headers=headers, body={})
    assert status == 200, first
    # Today the Engine gets no follows and answers an empty page with no cursor (observed: ([], None)).
    assert (_keys(first["rows"]), first.get("cursor")) == (_keys(direct["rows"]), direct["cursor"]), first  # C1 C2

    status, second = engine_client.request("POST", path, headers=headers, body={"cursor": first["cursor"]})
    assert status == 200, second
    assert len(second["rows"]) == WALK_PAGE, second
    assert {(r["instance_domain"], r["channel_id"]) for r in second["rows"]} == {(host, channel_id)}, second["rows"]
    assert not set(_keys(first["rows"])) & set(_keys(second["rows"])), second["rows"]
    assert _published_key(dataset, second["rows"][0]) < _published_key(dataset, first["rows"][-1]), (first["rows"][-1], second["rows"][0])
