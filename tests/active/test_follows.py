"""Profile follows on the real Client backend against the session Engine, through `/api/profile/follows`.

Stored keys and labels, and refusals (fixtures read from `whitelist.db`):

- Following a video's channel answers 201 and lists ("channel", instance_domain, channel_id, "", the channel's `channels.display_name`); following its account lists ("account", "", "", account_url, `account_name`), each label distinct from the name, id or URL it could wrongly fall back to. Another profile's list is empty; removal by the listed key fields answers 204 and takes off that follow alone.
- A channel named by its key, its host in upper case and both fields padded, is stored under the catalogue's lowercase key and display name; the channel has no row in `videos`.
- A channel key whose host and id each exist in the catalogue but not together answers 404 `Channel not found in Engine`, and an unknown video uuid 404 `Video not found in Engine` for either kind; nothing is stored.
- Malformed bodies answer 400 with their reason (`kind must be channel or account`, `Name a video or a channel, not both`, `instance_domain and channel_id must be non-empty strings` for a blank, numeric or 201-character channel_id, `uuid and host must be non-empty strings` for a channel key under kind account or a uuid without a host); a 200-character channel_id is checked against the catalogue and answers 404. None stores anything.
- Re-following by the video form and by the channel form answers 201 each time and keeps one follow per key.
- At 1000 follows a held target is still re-followed with 201; a 1001st answers 400 `Follow limit reached (1000)`, the list is unchanged, and the block on the refused key stays.
- A missing, unknown or malformed key gets the one 401 `Profile key required` on list, add and remove, and neither adds nor removes; each route answers 429 `Rate limit exceeded` once the one address driven has spent the Client's budget.

A follow replaces a block on exactly one key, a channel's or an account's:

- Following a channel removes the profile's block on that channel and leaves its blocks on the same channel_id on another host, on the video's account and on an unrelated account, and another profile's block on the same channel; the channel form swaps the same way.
- Following an account removes the profile's block on that account and leaves its blocks on the video's channel, on the twin channel's account and on an unrelated account, and another profile's block on the same account.
- Following an account leaves the block on one of its channels, whose rows stay off the profile's search page while the keyless page serves them.

Blocking replacing a follow is `test_blocks.py`'s; deleting a profile's follows is `test_profiles.py`'s.
"""
from __future__ import annotations

import secrets
import threading

import pytest

from conftest import CLOSED_ENGINE, ClientBackend, RateLimiter, client_server, ensure_user_schema

FOLLOWS = "/api/profile/follows"
REMOVE = "/api/profile/follows/remove"
BLOCKS = "/api/profile/blocks"
SEARCH = "/api/v1/search/videos?q=music&limit=20"
KEY_FIELDS = ("kind", "instance_domain", "channel_id", "account_url")
LISTED_FIELDS = (*KEY_FIELDS, "label")
# AC4's limit, written down rather than imported, so a wrong constant in follows.py shows.
MAX_FOLLOWS = 1000
# BLOCK_REFERENCE_MAX_LENGTH: a channel key field of this many characters is checked against the catalogue, one more is refused at the edge.
REFERENCE_MAX = 200
# A uuid no catalogue video carries (checked against whitelist.db in the test that uses it).
NO_SUCH_UUID = "00000000-0000-4000-8000-000000000054"
# The limited Client's per-address budget, so a 429 shows within a few requests.
RATE_BUDGET = 2
REFUSAL = (401, {"error": "Profile key required"})

# Videos the Engine resolves and serves metadata for: embedded, no fetch errors, not NSFW.
RESOLVABLE = (
    "FROM videos v JOIN video_embeddings e "
    "ON e.video_id = v.video_id AND e.instance_domain = v.instance_domain "
    "WHERE v.error_count = 0 AND (v.nsfw IS NULL OR v.nsfw = 0)"
)


@pytest.fixture
def limited_client(tmp_path):
    """The real Client backend with a per-address budget of RATE_BUDGET requests a minute; the follow routes it is driven on refuse or answer without calling the Engine."""
    db_path = tmp_path / "users.db"
    conn = client_server.connect_db(db_path)
    ensure_user_schema(conn)
    srv = client_server.ClientBackendServer(("127.0.0.1", 0), client_server.ClientBackendHandler, conn, CLOSED_ENGINE, "bridge", RateLimiter(RATE_BUDGET, 60))
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield ClientBackend(f"http://127.0.0.1:{srv.server_address[1]}", db_path)
    finally:
        srv.shutdown()
        srv.server_close()
        conn.close()


# --- fixtures read from whitelist.db, the independent source of a video's channel, account and labels ---


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


def _twin(dataset, video: dict) -> dict:
    """A served video on another host whose channel has the same channel_id, under another account: the same channel id, a different channel key."""
    return dict(dataset.execute(
        f"SELECT v.video_uuid, v.instance_domain, v.channel_id, v.account_url {RESOLVABLE} "
        "AND v.channel_id = ? AND v.instance_domain <> ? AND v.account_url <> ? ORDER BY v.rowid LIMIT 1",
        (video["channel_id"], video["instance_domain"], video["account_url"]),
    ).fetchone())


def _unrelated(dataset, *videos: dict) -> dict:
    """A served video sharing neither a channel id nor an account with any of `videos`."""
    ids = [v["channel_id"] for v in videos]
    accounts = [v["account_url"] for v in videos]
    return dict(dataset.execute(
        f"SELECT v.video_uuid, v.instance_domain, v.channel_id, v.account_url {RESOLVABLE} "
        f"AND v.channel_id NOT IN ({', '.join('?' * len(ids))}) AND v.account_url NOT IN ({', '.join('?' * len(accounts))}) ORDER BY v.rowid LIMIT 1",
        (*ids, *accounts),
    ).fetchone())


def _videoless_channel(dataset) -> dict:
    """A channel the catalogue's `channels` table holds with no video in `videos`, its display name distinct from its name and id."""
    return dict(dataset.execute(
        "SELECT c.instance_domain, c.channel_id, c.display_name FROM channels c "
        "WHERE c.display_name <> '' AND c.display_name <> c.channel_id AND c.display_name <> COALESCE(c.channel_name, '') "
        "AND NOT EXISTS (SELECT 1 FROM videos v WHERE v.instance_domain = c.instance_domain AND v.channel_id = c.channel_id) "
        "ORDER BY c.rowid LIMIT 1"
    ).fetchone())


def _channel_id_held_elsewhere(dataset, host: str) -> str:
    """A channel_id the catalogue holds on another host and not on `host`."""
    return dataset.execute(
        "SELECT channel_id FROM channels WHERE instance_domain <> ? AND channel_id NOT IN (SELECT channel_id FROM channels WHERE instance_domain = ?) ORDER BY rowid LIMIT 1",
        (host, host),
    ).fetchone()[0]


# --- the routes, as the browser calls them ---


def _mint(client) -> tuple[str, str]:
    status, body = client.request("POST", "/api/profile")
    assert status == 201, body
    return body["profile_id"], body["key"]


def _key(client) -> str:
    return _mint(client)[1]


def _follow(client, key: str, body: dict) -> tuple[int, object]:
    return client.request("POST", FOLLOWS, headers={"X-Profile-Key": key}, body=body)


def _by_video(kind: str, video: dict) -> dict:
    return {"kind": kind, "uuid": video["video_uuid"], "host": video["instance_domain"]}


def _by_channel(instance_domain: str, channel_id) -> dict:
    return {"kind": "channel", "instance_domain": instance_domain, "channel_id": channel_id}


def _listed(client, key: str) -> list[tuple[str, ...]]:
    """The profile's follows as GET /api/profile/follows lists them: kind, the three key fields, label."""
    status, body = client.request("GET", FOLLOWS, headers={"X-Profile-Key": key})
    assert status == 200, body
    return [tuple(follow[field] for field in LISTED_FIELDS) for follow in body["follows"]]


def _follow_keys(client, key: str) -> set[tuple[str, ...]]:
    return {row[:4] for row in _listed(client, key)}


def _block_keys(client, key: str) -> set[tuple[str, ...]]:
    status, body = client.request("GET", BLOCKS, headers={"X-Profile-Key": key})
    assert status == 200, body
    return {tuple(block[field] for field in KEY_FIELDS) for block in body["blocks"]}


def _block(client, key: str, kind: str, video: dict) -> None:
    status, body = client.request("POST", BLOCKS, headers={"X-Profile-Key": key}, body=_by_video(kind, video))
    assert status == 201, body


def _remove(client, key: str, target: tuple[str, ...]) -> int:
    return client.request("POST", REMOVE, headers={"X-Profile-Key": key}, body=dict(zip(KEY_FIELDS, target)))[0]


def _channel_key(video: dict) -> tuple[str, ...]:
    return ("channel", video["instance_domain"], video["channel_id"], "")


def _account_key(video: dict) -> tuple[str, ...]:
    return ("account", "", "", video["account_url"])


def _row(follow: dict) -> tuple[str, ...]:
    return tuple(follow[field] for field in LISTED_FIELDS)


# --- C1: the stored follow is the Engine's key and label, and a target the catalogue lacks is refused ---


def test_a_video_s_channel_and_account_are_followed_under_whitelist_db_s_keys_and_labels_listed_per_profile_and_removed(engine_client, dataset):
    video = _labelled_video(dataset)
    channel = (*_channel_key(video), video["channel_label"])
    account = (*_account_key(video), video["account_name"])
    key = _key(engine_client)

    status, body = _follow(engine_client, key, _by_video("channel", video))
    # A label taken from channel_name or channel_id, or a key from anywhere but the Engine's row, reads differently.
    assert (status, _row(body["follow"]) if status == 201 else body) == (201, channel)  # C1
    status, body = _follow(engine_client, key, _by_video("account", video))
    assert (status, _row(body["follow"]) if status == 201 else body) == (201, account)  # C1: the account label is account_name, not the URL
    assert sorted(_listed(engine_client, key)) == sorted([channel, account])  # C1
    assert _listed(engine_client, _key(engine_client)) == []  # another profile's list is its own

    assert _remove(engine_client, key, channel[:4]) == 204
    assert _listed(engine_client, key) == [account]  # the channel goes, the account stays
    assert _remove(engine_client, key, account[:4]) == 204
    assert _listed(engine_client, key) == []


def test_a_channel_named_in_upper_case_and_padded_is_stored_under_the_catalogue_s_own_key_and_label(engine_client, dataset):
    channel = _videoless_channel(dataset)
    body = _by_channel(f"  {channel['instance_domain'].upper()} ", f" {channel['channel_id']}  ")
    # control: the browser's host differs from the catalogue's in case, not only in padding, and both fields are padded.
    assert body["instance_domain"].strip() != channel["instance_domain"] and body["channel_id"] != channel["channel_id"]
    expected = ("channel", channel["instance_domain"], channel["channel_id"], "", channel["display_name"])

    key = _key(engine_client)
    status, answer = _follow(engine_client, key, body)
    # Storing the browser's fields reads the padded or upper-case host; a case-sensitive lookup, or one through `videos` (this channel has none), answers 404; a label from the id reads differently.
    assert (status, _row(answer["follow"]) if status == 201 else answer) == (201, expected)  # C1
    assert _listed(engine_client, key) == [expected]  # C1


def test_a_channel_or_a_video_the_catalogue_lacks_is_refused_404_and_nothing_is_stored(engine_client, dataset):
    video = _labelled_video(dataset)
    host = video["instance_domain"]
    missing = _channel_id_held_elsewhere(dataset, host)
    # control: the host holds channels and the id is a channel elsewhere, so only the exact pair is absent.
    assert dataset.execute("SELECT COUNT(*) FROM channels WHERE instance_domain = ? AND channel_id = ?", (host, missing)).fetchone()[0] == 0
    assert dataset.execute("SELECT COUNT(*) FROM channels WHERE channel_id = ?", (missing,)).fetchone()[0] > 0
    assert dataset.execute("SELECT COUNT(*) FROM videos WHERE video_uuid = ?", (NO_SUCH_UUID,)).fetchone()[0] == 0

    key = _key(engine_client)
    # A lookup on channel_id alone, or on the host alone, finds a channel and stores it.
    assert _follow(engine_client, key, _by_channel(host, missing)) == (404, {"error": "Channel not found in Engine"})  # C1
    for kind in ("channel", "account"):
        assert _follow(engine_client, key, _by_video(kind, {"video_uuid": NO_SUCH_UUID, "instance_domain": host})) == (404, {"error": "Video not found in Engine"})  # C1
    assert _listed(engine_client, key) == []  # C1: neither refusal stored anything
    assert _follow(engine_client, key, _by_video("channel", video))[0] == 201 and len(_listed(engine_client, key)) == 1  # control: this profile's list shows a follow once one is stored


MALFORMED = {
    "kind is neither channel nor account": (lambda v: _by_video("video", v), 400, "kind must be channel or account"),
    "no kind": (lambda v: {"uuid": v["video_uuid"], "host": v["instance_domain"]}, 400, "kind must be channel or account"),
    "a video and a channel": (lambda v: {**_by_video("channel", v), "instance_domain": v["instance_domain"], "channel_id": v["channel_id"]}, 400, "Name a video or a channel, not both"),
    "a blank channel_id": (lambda v: _by_channel(v["instance_domain"], "   "), 400, "instance_domain and channel_id must be non-empty strings"),
    "a numeric channel_id": (lambda v: _by_channel(v["instance_domain"], int(v["channel_id"])), 400, "instance_domain and channel_id must be non-empty strings"),
    "a 201-character channel_id": (lambda v: _by_channel(v["instance_domain"], "9" * (REFERENCE_MAX + 1)), 400, "instance_domain and channel_id must be non-empty strings"),
    # One under the refusal, the key is checked against the catalogue instead, which lacks it.
    "a 200-character channel_id": (lambda v: _by_channel(v["instance_domain"], "9" * REFERENCE_MAX), 404, "Channel not found in Engine"),
    "a channel key under kind account": (lambda v: {"kind": "account", "instance_domain": v["instance_domain"], "channel_id": v["channel_id"]}, 400, "uuid and host must be non-empty strings"),
    "a uuid without a host": (lambda v: {"kind": "channel", "uuid": v["video_uuid"]}, 400, "uuid and host must be non-empty strings"),
}


@pytest.mark.parametrize("case", MALFORMED.keys())
def test_a_malformed_follow_body_is_refused_with_its_reason_and_stores_nothing(engine_client, dataset, case):
    build, status, error = MALFORMED[case]
    video = _labelled_video(dataset)
    key = _key(engine_client)
    # Each body carries a real video's or channel's fields, so an add that skipped the check would store one.
    assert _follow(engine_client, key, build(video)) == (status, {"error": error})
    assert _listed(engine_client, key) == []
    assert _follow(engine_client, key, _by_video("channel", video))[0] == 201 and len(_listed(engine_client, key)) == 1  # control: this profile's list shows a follow once one is stored


def test_following_a_target_already_followed_by_either_form_keeps_one_follow(engine_client, dataset):
    video = _labelled_video(dataset)
    key = _key(engine_client)
    answers = [_follow(engine_client, key, body)[0] for body in (
        _by_video("channel", video), _by_video("channel", video), _by_channel(video["instance_domain"], video["channel_id"]),
        _by_video("account", video), _by_video("account", video),
    )]
    # An add without the exists check hits the primary key and answers 500.
    assert answers == [201] * 5
    assert sorted(_listed(engine_client, key)) == sorted([(*_channel_key(video), video["channel_label"]), (*_account_key(video), video["account_name"])])


def test_a_profile_holding_1000_follows_is_refused_a_1001st_keeps_its_1000_and_keeps_the_block_on_the_refused_key(engine_client, dataset):
    extra = _unrelated(dataset, _labelled_video(dataset))
    channels = dataset.execute(
        "SELECT instance_domain, channel_id FROM channels WHERE NOT (instance_domain = ? AND channel_id = ?) ORDER BY rowid LIMIT ?",
        (extra["instance_domain"], extra["channel_id"], MAX_FOLLOWS),
    ).fetchall()
    assert len(channels) == MAX_FOLLOWS
    key = _key(engine_client)
    for channel in channels:
        status, body = _follow(engine_client, key, _by_channel(channel["instance_domain"], channel["channel_id"]))
        assert status == 201, (tuple(channel), body)  # AC4: each of the first 1000 is accepted, so the limit is not 999
    before = _listed(engine_client, key)
    assert len(before) == MAX_FOLLOWS
    # The channel form across 1000 catalogue keys: each is stored under the catalogue's own (instance_domain, channel_id).
    assert {row[:4] for row in before} == {("channel", channel["instance_domain"], channel["channel_id"], "") for channel in channels}  # C1

    # At the limit a target already held is still a no-op success, not a refusal: the exists check comes before the count.
    assert _follow(engine_client, key, _by_channel(channels[0]["instance_domain"], channels[0]["channel_id"]))[0] == 201
    _block(engine_client, key, "channel", extra)
    assert _block_keys(engine_client, key) == {_channel_key(extra)}  # control

    assert _follow(engine_client, key, _by_channel(extra["instance_domain"], extra["channel_id"])) == (400, {"error": f"Follow limit reached ({MAX_FOLLOWS})"})
    after = _listed(engine_client, key)
    # Refused means not stored: the list is unchanged, not trimmed to make room.
    assert sorted(after) == sorted(before)
    assert _channel_key(extra) not in {row[:4] for row in after}
    # A block dropped before the count check, or outside the add's transaction, is gone here.
    assert _block_keys(engine_client, key) == {_channel_key(extra)}  # C2


def test_every_follow_route_refuses_a_missing_or_unknown_key_with_the_one_401_and_changes_nothing(engine_client, dataset):
    video = _labelled_video(dataset)
    key = _key(engine_client)
    presented = ({}, {"X-Profile-Key": secrets.token_urlsafe(32)}, {"X-Profile-Key": "not-a-key"})
    for headers in presented:
        assert engine_client.request("GET", FOLLOWS, headers=headers) == REFUSAL
        assert engine_client.request("POST", FOLLOWS, headers=headers, body=_by_video("channel", video)) == REFUSAL
    assert _listed(engine_client, key) == []
    assert _follow(engine_client, key, _by_video("channel", video))[0] == 201  # control: the same body with the key is stored

    for headers in presented:
        assert engine_client.request("POST", REMOVE, headers=headers, body=dict(zip(KEY_FIELDS, _channel_key(video)))) == REFUSAL
    assert _follow_keys(engine_client, key) == {_channel_key(video)}  # a refused removal removed nothing
    assert _remove(engine_client, key, _channel_key(video)) == 204  # control: the same removal with the key
    assert _listed(engine_client, key) == []


@pytest.mark.parametrize(("method", "path", "body", "served"), [("GET", FOLLOWS, None, 200), ("POST", FOLLOWS, {}, 400), ("POST", REMOVE, {}, 400)], ids=["list", "add", "remove"])
def test_a_follow_route_answers_429_once_an_address_has_spent_its_budget(limited_client, method, path, body, served):
    key = _key(limited_client)
    answers = [limited_client.request(method, path, headers={"X-Profile-Key": key}, body=body) for _ in range(RATE_BUDGET + 1)]
    # A route without the limiter answers its usual status a third time.
    assert [status for status, _ in answers] == [served] * RATE_BUDGET + [429], answers
    assert answers[-1][1] == {"error": "Rate limit exceeded"}


# --- C2: a follow and a block on exactly the same key replace each other, and no other key is touched ---


def test_following_a_channel_removes_the_block_on_that_channel_and_no_other_block(engine_client, dataset):
    video = _labelled_video(dataset)
    twin = _twin(dataset, video)
    other = _unrelated(dataset, video, twin)
    key, bystander = _key(engine_client), _key(engine_client)
    for kind, blocked in (("channel", video), ("channel", twin), ("account", video), ("account", other)):
        _block(engine_client, key, kind, blocked)
    _block(engine_client, bystander, "channel", video)
    assert _block_keys(engine_client, key) == {_channel_key(video), _channel_key(twin), _account_key(video), _account_key(other)}  # control

    assert _follow(engine_client, key, _by_video("channel", video))[0] == 201
    # Matching on channel_id alone drops the twin's block; dropping every block on the video drops its account's.
    assert _block_keys(engine_client, key) == {_channel_key(twin), _account_key(video), _account_key(other)}  # C2
    assert _follow_keys(engine_client, key) == {_channel_key(video)}
    assert _block_keys(engine_client, bystander) == {_channel_key(video)}  # C2: another profile's block on the same channel stays

    # The channel form swaps the same way.
    assert _follow(engine_client, key, _by_channel(twin["instance_domain"], twin["channel_id"]))[0] == 201
    assert _block_keys(engine_client, key) == {_account_key(video), _account_key(other)}  # C2


def test_following_an_account_removes_the_block_on_that_account_and_no_other_block(engine_client, dataset):
    video = _labelled_video(dataset)
    twin = _twin(dataset, video)
    other = _unrelated(dataset, video, twin)
    key, bystander = _key(engine_client), _key(engine_client)
    for kind, blocked in (("account", video), ("channel", video), ("account", twin), ("account", other)):
        _block(engine_client, key, kind, blocked)
    _block(engine_client, bystander, "account", video)
    assert _block_keys(engine_client, key) == {_account_key(video), _channel_key(video), _account_key(twin), _account_key(other)}  # control

    assert _follow(engine_client, key, _by_video("account", video))[0] == 201
    # A swap written only for kind channel keeps the account block; dropping every block on the video drops its channel's; dropping every account block drops the twin's and the unrelated one.
    assert _block_keys(engine_client, key) == {_channel_key(video), _account_key(twin), _account_key(other)}  # C2
    assert _follow_keys(engine_client, key) == {_account_key(video)}
    assert _block_keys(engine_client, bystander) == {_account_key(video)}  # C2: another profile's block on the same account stays


def _search(client, key: str | None) -> list[dict]:
    status, body = client.request("GET", SEARCH, headers={"X-Profile-Key": key} if key else {})
    assert status == 200, body
    return body["rows"]


def test_an_account_follow_leaves_the_block_on_one_of_its_channels_in_place_and_that_channel_s_rows_still_go(engine_client):
    row = _search(engine_client, None)[0]
    channel = (row["instance_domain"], row["channel_id"])
    key = _key(engine_client)
    _block(engine_client, key, "channel", row)
    assert _follow(engine_client, key, _by_video("account", row))[0] == 201

    # Following an account by dropping the blocks on all of its channels removes this one.
    assert _block_keys(engine_client, key) == {_channel_key(row)}  # C2
    assert _follow_keys(engine_client, key) == {_account_key(row)}
    keyed = _search(engine_client, key)
    assert keyed  # the profile still gets results
    assert not [r for r in keyed if (r["instance_domain"], r["channel_id"]) == channel]  # C2: the blocked channel's rows are still dropped
    assert [r for r in _search(engine_client, None) if (r["instance_domain"], r["channel_id"]) == channel]  # control: the keyless page still serves them
