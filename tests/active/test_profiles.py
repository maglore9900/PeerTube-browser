"""Per-visitor profiles on the Client backend: minting, proof by key, refusal, rotation, deletion.

- A minted key, presented in `X-Profile-Key`, reads its own profile's likes and no other's.
- `users.db` never holds a minted key, only what it hashes to.
- Every profile route answers any presentation other than a valid header key with one
  identical 401, so a caller cannot tell a malformed key from an unknown one.
- One address can mint five profiles an hour.
- Rotating retires the old key; deleting removes every row keyed to the profile, including its
  `like_generations` rows, the open one and the closed one alike, and keeps another profile's.
- Deleting a profile that followed a video's channel and account through the real Engine leaves none of its rows in `follows` and keeps another profile's two.
- Importing browser likes marks each imported video liked for the profile, and no other.
- A keyed up-next request is seeded from the profile's likes, not from likes the browser sends.
- A keyed search marks the profile's liked row `reaction: "liked"` and its disliked row, still
  present, `reaction: "disliked"`; every other row, and every row of the keyless search, carries none.
"""
from __future__ import annotations

import base64
import http.client
import json
import secrets
import sqlite3
from datetime import datetime as real_datetime
from urllib.parse import quote, urlencode

import pytest
from lib import http_utils
from lib.users_store import close_like, record_like, remove_like

PROFILE_ROUTES = [
    ("GET", "/api/user-profile"),
    ("GET", "/api/user-profile/likes"),
    ("POST", "/api/user-profile/reset"),
]


def _mint(client) -> tuple[str, str]:
    status, body = client.request("POST", "/api/profile")
    assert status == 201, body
    return body["profile_id"], body["key"]


def _seed_like(db_path, profile_id: str, video_id: str, host: str = "h.example", publish: bool = False) -> None:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    record_like(conn, profile_id, "like",
                {"video_id": video_id, "instance_domain": host, "video_uuid": f"u-{video_id}"}, 100, publish=publish)
    conn.close()


def _seed_undone_like(db_path, profile_id: str, video_id: str, host: str = "h.example") -> None:
    """A published like, then undone: its likes row goes, its closed generation row stays."""
    _seed_like(db_path, profile_id, video_id, host, publish=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    with conn:
        remove_like(conn, profile_id, video_id, host)
        close_like(conn, profile_id, video_id, host)
    conn.close()


def _read(client, key: str):
    return client.request("GET", "/api/user-profile", headers={"X-Profile-Key": key})


def _liked(client, key: str) -> set[tuple[str, str]]:
    status, body = _read(client, key)
    assert status == 200, body
    return {(like["video_id"], like["instance_domain"]) for like in body["likes"]}


def _rows_for(db_path, profile_id: str) -> dict[str, int]:
    conn = sqlite3.connect(db_path)
    counts = {
        "profiles": conn.execute("SELECT COUNT(*) FROM profiles WHERE profile_id = ?", (profile_id,)).fetchone()[0],
        "users": conn.execute("SELECT COUNT(*) FROM users WHERE user_id = ?", (profile_id,)).fetchone()[0],
        "likes": conn.execute("SELECT COUNT(*) FROM likes WHERE user_id = ?", (profile_id,)).fetchone()[0],
        "like_generations": conn.execute("SELECT COUNT(*) FROM like_generations WHERE user_id = ?", (profile_id,)).fetchone()[0],
    }
    conn.close()
    return counts


# --- minting and reading ---------------------------------------------------------------


def test_a_minted_key_reads_its_own_likes_and_not_another_profiles(client_backend):
    a_id, a_key = _mint(client_backend)
    b_id, b_key = _mint(client_backend)
    assert a_id != b_id and a_key != b_key
    _seed_like(client_backend.db_path, a_id, "va", "a.example")
    _seed_like(client_backend.db_path, a_id, "va2", "a.example")
    _seed_like(client_backend.db_path, b_id, "vb", "b.example")

    assert _liked(client_backend, a_key) == {("va", "a.example"), ("va2", "a.example")}
    assert _liked(client_backend, b_key) == {("vb", "b.example")}


def test_users_db_holds_the_minted_profiles_but_none_of_their_keys(client_backend):
    minted = [_mint(client_backend) for _ in range(3)]
    conn = sqlite3.connect(client_backend.db_path)
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()
    stored = b"".join(p.read_bytes() for p in client_backend.db_path.parent.glob("users.db*"))

    # Control: the file does hold the minted profiles, so absent keys are not an empty file.
    for profile_id, _key in minted:
        assert profile_id.encode("ascii") in stored
    for _profile_id, key in minted:
        assert key.encode("ascii") not in stored
        # The key's raw bytes too, so storing it decoded is caught.
        assert base64.urlsafe_b64decode(key + "=" * (-len(key) % 4)) not in stored


# --- refusal and the mint limit --------------------------------------------------------


@pytest.mark.parametrize(("method", "path"), PROFILE_ROUTES)
def test_every_presentation_but_a_valid_header_gets_the_same_refusal(client_backend, method, path):
    profile_id, key = _mint(client_backend)
    body = {} if method == "POST" else None

    # Control: the route serves a profile when the key arrives in the header.
    status, _ = client_backend.request(method, path, headers={"X-Profile-Key": key}, body=body)
    assert status == 200

    malformed = {
        "empty": "",
        "short": key[:42],
        "long": key + "A",
        "bad char": key[:42] + "!",
        "not a key": "not-a-key",
    }
    responses = {
        "absent": client_backend.request(method, path, body=body),
        **{f"malformed {name}": client_backend.request(
            method, path, headers={"X-Profile-Key": value}, body=body)
           for name, value in malformed.items()},
        "unknown": client_backend.request(
            method, path, headers={"X-Profile-Key": secrets.token_urlsafe(32)}, body=body),
        "key in query": client_backend.request(method, f"{path}?key={key}", body=body),
        "id in query": client_backend.request(method, f"{path}?user_id={profile_id}", body=body),
        "in body": client_backend.request(
            method, path, body={"key": key, "user_id": profile_id}),
    }
    refusals = {(status, json.dumps(payload, sort_keys=True)) for status, payload in responses.values()}
    assert len(refusals) == 1, responses
    assert responses["absent"][0] == 401


class _Clock:
    """Stands in for the wall clock the rate limiter reads: a system boundary."""

    def __init__(self, start: float) -> None:
        self.now_ts = start

    def now(self, tz=None):
        return real_datetime.fromtimestamp(self.now_ts, tz)


def _mint_from(client, source_ip: str) -> int:
    """Mint over a connection bound to `source_ip`, so the server sees that address."""
    host, port = client.base.removeprefix("http://").split(":")
    conn = http.client.HTTPConnection(host, int(port), timeout=10, source_address=(source_ip, 0))
    try:
        conn.request("POST", "/api/profile", body=b"", headers={"content-type": "application/json"})
        return conn.getresponse().status
    finally:
        conn.close()


def test_a_sixth_mint_from_one_address_within_the_hour_is_refused(client_backend, monkeypatch):
    clock = _Clock(1_800_000_000.0)
    monkeypatch.setattr(http_utils, "datetime", clock)

    first_five = [_mint_from(client_backend, "127.0.0.1") for _ in range(5)]
    clock.now_ts += 3599
    sixth = _mint_from(client_backend, "127.0.0.1")
    other_address = _mint_from(client_backend, "127.0.0.2")
    clock.now_ts += 2
    after_the_hour = _mint_from(client_backend, "127.0.0.1")

    assert first_five == [201] * 5
    assert sixth == 429
    # The limit is per address: another address still mints while the first is refused.
    assert other_address == 201
    # The window is an hour: one second past it, the first address mints again.
    assert after_the_hour == 201


# --- rotation and deletion -------------------------------------------------------------


def test_after_rotation_only_the_new_key_reads_the_same_profile(client_backend):
    profile_id, old_key = _mint(client_backend)
    _seed_like(client_backend.db_path, profile_id, "v1")
    assert _read(client_backend, old_key)[0] == 200  # control: the old key worked before

    status, body = client_backend.request("POST", "/api/profile/rotate",
                                          headers={"X-Profile-Key": old_key}, body={})
    assert status == 200, body
    new_key = body["key"]
    assert new_key != old_key

    assert _read(client_backend, old_key)[0] == 401
    status, body = _read(client_backend, new_key)
    assert status == 200
    assert [like["video_id"] for like in body["likes"]] == ["v1"]


def test_deleting_a_profile_removes_its_rows_and_like_generations_and_keeps_anothers(client_backend):
    gone_id, gone_key = _mint(client_backend)
    kept_id, kept_key = _mint(client_backend)
    for profile_id in (gone_id, kept_id):
        # record_like also creates the `users` row; publishing opens a generation row.
        _seed_like(client_backend.db_path, profile_id, f"v-{profile_id}", publish=True)
    # A closed generation outlives its likes row, so a delete keyed on the likes it removes would leave it.
    _seed_undone_like(client_backend.db_path, gone_id, "v-undone")
    assert _read(client_backend, gone_key)[0] == 200
    assert _read(client_backend, kept_key)[0] == 200
    # Control: one open and one closed generation row for the profile to be deleted, one open for the other.
    assert _rows_for(client_backend.db_path, gone_id) == {"profiles": 1, "users": 1, "likes": 1, "like_generations": 2}
    assert _rows_for(client_backend.db_path, kept_id) == {"profiles": 1, "users": 1, "likes": 1, "like_generations": 1}

    # A delete without the key is refused and removes nothing.
    assert client_backend.request("POST", "/api/profile/delete", body={})[0] == 401
    assert _rows_for(client_backend.db_path, gone_id) == {"profiles": 1, "users": 1, "likes": 1, "like_generations": 2}

    status, _ = client_backend.request("POST", "/api/profile/delete",
                                       headers={"X-Profile-Key": gone_key}, body={})
    assert status == 204

    assert _rows_for(client_backend.db_path, gone_id) == {"profiles": 0, "users": 0, "likes": 0, "like_generations": 0}
    assert _rows_for(client_backend.db_path, kept_id) == {"profiles": 1, "users": 1, "likes": 1, "like_generations": 1}
    assert _read(client_backend, gone_key)[0] == 401
    assert _read(client_backend, kept_key)[0] == 200


# --- likes held by the profile ---------------------------------------------------------


def _embedded_videos(dataset, n: int) -> list[dict]:
    """n embedded, error-free videos from different channels, which the Engine resolves."""
    rows = dataset.execute(
        "SELECT v.video_uuid, v.instance_domain FROM videos v JOIN video_embeddings e "
        "ON e.video_id = v.video_id AND e.instance_domain = v.instance_domain "
        "WHERE v.error_count = 0 GROUP BY v.channel_id, v.instance_domain ORDER BY v.rowid LIMIT ?",
        (n,),
    ).fetchall()
    assert len(rows) == n
    return [{"uuid": r["video_uuid"], "host": r["instance_domain"]} for r in rows]


def _key_header(client) -> dict[str, str]:
    return {"X-Profile-Key": _mint(client)[1]}


def _reaction_liked(client, headers, video) -> bool:
    status, body = client.request("GET", f"/api/profile/reaction?{urlencode(video)}", headers=headers)
    assert status == 200, body
    return body["liked"]


def test_importing_browser_likes_marks_each_imported_video_liked_and_no_other(unpublished_client, dataset):
    client = unpublished_client
    key = _key_header(client)
    *imported, untouched = _embedded_videos(dataset, 4)
    assert not any(_reaction_liked(client, key, v) for v in imported)
    status, body = client.request("POST", "/api/profile/likes/import", headers=key, body={"likes": imported})
    assert status == 200, body
    assert all(_reaction_liked(client, key, v) for v in imported)
    assert not _reaction_liked(client, key, untouched)


def _upnext_profile(client, seed, headers=None, likes=None) -> str:
    """The recommendation profile the Engine served a debug up-next request with."""
    path = f"/recommendations?id={seed['video_uuid']}&host={seed['instance_domain']}&limit=16&debug=1"
    status, body = client.request("POST", path, headers=headers, body={"likes": likes} if likes else {})
    assert status == 200 and body["rows"], body
    return body["rows"][0]["debug"]["profile"]


def test_a_keyed_upnext_request_is_seeded_from_the_profile_s_likes_not_the_browser_s(
        unpublished_client, dataset):
    client = unpublished_client
    status, body = client.request("GET", f"/api/v1/search/videos?q={quote('linux')}&limit=1")
    assert status == 200 and body["rows"], body
    seed = body["rows"][0]
    (liked,) = _embedded_videos(dataset, 1)
    browser_likes = [liked]

    assert _upnext_profile(client, seed) == "guest_upnext"
    assert _upnext_profile(client, seed, likes=browser_likes) == "upnext"

    holder = _key_header(client)
    client.request("POST", "/api/user-action", headers=holder, body={"action": "like", **liked})
    assert _reaction_liked(client, holder, liked)
    assert _upnext_profile(client, seed, headers=holder) == "upnext"

    empty = _key_header(client)
    assert _upnext_profile(client, seed, headers=empty, likes=browser_likes) == "guest_upnext"


def _search_by_key(client, headers=None) -> dict[str, dict]:
    status, body = client.request("GET", "/api/v1/search/videos?q=music", headers=headers)
    assert status == 200 and body["rows"], body
    return {f"{r['instance_domain']}::{r['video_uuid']}": r for r in body["rows"]}


def test_a_keyed_search_marks_the_profile_s_liked_and_disliked_rows_and_a_keyless_one_marks_none(
        unpublished_client):
    client = unpublished_client
    keyless = list(_search_by_key(client).values())
    liked, disliked, neutral = keyless[0], keyless[1], keyless[2]
    key = lambda row: f"{row['instance_domain']}::{row['video_uuid']}"  # noqa: E731
    headers = _key_header(client)
    # An unpublished Client stores the like, then answers 502 for the publish it cannot send;
    # a dislike of an unliked video publishes nothing and is answered 200.
    for action, row, expected in (("like", liked, 502), ("dislike", disliked, 200)):
        status, body = client.request("POST", "/api/user-action", headers=headers,
                                      body={"action": action, "uuid": row["video_uuid"], "host": row["instance_domain"]})
        assert status == expected, (action, status, body)

    keyed = _search_by_key(client, headers)
    assert keyed.get(key(liked), {}).get("reaction") == "liked", keyed.get(key(liked))
    assert key(disliked) in keyed  # search keeps the disliked video
    assert keyed[key(disliked)].get("reaction") == "disliked"
    others = {k: r.get("reaction") for k, r in keyed.items() if k not in (key(liked), key(disliked))}
    assert key(neutral) in others and set(others.values()) == {None}, others  # every other row unmarked
    again = _search_by_key(client)
    assert key(liked) in again and key(disliked) in again  # control: the keyless page holds both
    assert [k for k, r in again.items() if "reaction" in r] == []


# Deleting a profile removes its follows. These helpers follow and list through `/api/profile/follows`.
FOLLOWS = "/api/profile/follows"
KEY_FIELDS = ("kind", "instance_domain", "channel_id", "account_url")
LISTED_FIELDS = (*KEY_FIELDS, "label")


def _labelled_video(dataset) -> dict:
    """A served video whose channel's display name differs from its channel name and id, and whose account name differs from its URL, so each label can only come from its own column."""
    return dict(dataset.execute(
        "SELECT v.video_uuid, v.instance_domain, v.channel_id, v.account_url, v.account_name, c.display_name AS channel_label "
        "FROM videos v JOIN video_embeddings e ON e.video_id = v.video_id AND e.instance_domain = v.instance_domain "
        "JOIN channels c ON c.channel_id = v.channel_id AND c.instance_domain = v.instance_domain "
        "WHERE v.error_count = 0 AND (v.nsfw IS NULL OR v.nsfw = 0) "
        "AND c.display_name <> '' AND c.display_name <> v.channel_id AND c.display_name <> COALESCE(v.channel_name, '') "
        "AND v.account_name <> '' AND v.account_name <> v.account_url "
        "ORDER BY v.rowid LIMIT 1"
    ).fetchone())


def _follow(client, key: str, body: dict) -> tuple[int, object]:
    return client.request("POST", FOLLOWS, headers={"X-Profile-Key": key}, body=body)


def _by_video(kind: str, video: dict) -> dict:
    return {"kind": kind, "uuid": video["video_uuid"], "host": video["instance_domain"]}


def _listed(client, key: str) -> list[tuple[str, ...]]:
    """The profile's follows as GET /api/profile/follows lists them: kind, the three key fields, label."""
    status, body = client.request("GET", FOLLOWS, headers={"X-Profile-Key": key})
    assert status == 200, body
    return [tuple(follow[field] for field in LISTED_FIELDS) for follow in body["follows"]]


def _follow_rows(db_path, profile_id: str) -> int:
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute("SELECT COUNT(*) FROM follows WHERE profile_id = ?", (profile_id,)).fetchone()[0]
    finally:
        conn.close()


def test_deleting_a_profile_removes_its_follows_and_keeps_another_s(engine_client, dataset):
    video = _labelled_video(dataset)
    (gone_id, gone_key), (kept_id, kept_key) = _mint(engine_client), _mint(engine_client)
    for key in (gone_key, kept_key):
        for kind in ("channel", "account"):
            assert _follow(engine_client, key, _by_video(kind, video))[0] == 201
    # rung 3: once its key is gone no route reads a deleted profile's follows, so its rows are counted in users.db.
    assert (_follow_rows(engine_client.db_path, gone_id), _follow_rows(engine_client.db_path, kept_id)) == (2, 2)  # control

    assert engine_client.request("POST", "/api/profile/delete", headers={"X-Profile-Key": gone_key}, body={})[0] == 204
    assert (_follow_rows(engine_client.db_path, gone_id), _follow_rows(engine_client.db_path, kept_id)) == (0, 2)
    assert len(_listed(engine_client, kept_key)) == 2
