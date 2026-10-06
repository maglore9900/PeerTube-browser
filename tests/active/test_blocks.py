"""Profile blocks on the Client backend, against a real Engine.

- Blocking a video's channel stores the channel `(instance_domain, channel_id)`, and blocking
  its account stores the `account_url`, as `whitelist.db` holds them; the profile lists them,
  and removal takes them off the list. Another profile's list is its own.
- A profile holds at most 1,000 blocks: the next one is refused with 400 and not stored.
- Through the read gateway, a profile's up-next (`/recommendations`, `/videos/similar`) and
  search pages leave out its blocked channel and account, while keyless requests and other
  profiles still receive them.
- An up-next page for a profile with blocks is refilled to the requested size from the
  Client's over-fetch, with no blocked target in it.
- Blocking a channel removes the profile's follow of that channel and leaves its follows of the same channel_id on another host, of the video's account and of an unrelated account, and another profile's follow of it.
- Blocking an account removes the profile's follow of that account and leaves its follows of the video's channel, of the twin channel's account and of an unrelated account, and another profile's follow of the same account.

Each up-next page is pinned with `exclude` to a fixed set of the seed's pool (conftest `pin_upnext`), so it is served whole, not drawn.
"""
from __future__ import annotations

import pytest

from conftest import pin_upnext, upnext_pool

TARGET_FIELDS = ("kind", "instance_domain", "channel_id", "account_url")
SEARCH = "/api/v1/search/videos?q=music&limit=20"
ROUTES = ("/recommendations", "/videos/similar")
PAGE = 8

# Videos the Engine can resolve: it resolves only embedded videos, and its metadata read
# skips videos with fetch errors.
RESOLVABLE = (
    "FROM videos v JOIN video_embeddings e "
    "ON e.video_id = v.video_id AND e.instance_domain = v.instance_domain "
    "WHERE v.error_count = 0"
)


def _mint(client) -> str:
    status, body = client.request("POST", "/api/profile")
    assert status == 201, body
    return body["key"]


def _targets(client, key: str) -> list[tuple[str, str, str, str]]:
    status, body = client.request("GET", "/api/profile/blocks", headers={"X-Profile-Key": key})
    assert status == 200, body
    return [tuple(block[field] for field in TARGET_FIELDS) for block in body["blocks"]]


def _post_block(client, key: str, kind: str, video) -> tuple[int, object]:
    return client.request("POST", "/api/profile/blocks", headers={"X-Profile-Key": key},
                          body={"kind": kind, "uuid": video["video_uuid"], "host": video["instance_domain"]})


def _block(client, key: str, kind: str, row: dict) -> None:
    status, body = _post_block(client, key, kind, row)
    assert status == 201, body


def _rows(client, method: str, path: str, key: str | None = None, pin: dict | None = None) -> list[dict]:
    headers = {"X-Profile-Key": key} if key else {}
    status, body = client.request(method, path, headers=headers, body=(pin or {}) if method == "POST" else None)
    assert status == 200, body
    return body["rows"]


def _channel(row: dict) -> tuple[str, str]:
    return (row["instance_domain"], row["channel_id"])


def _keys(rows) -> set[tuple[str, str]]:
    return {(r["video_id"], r["instance_domain"]) for r in rows}


def _upnext(route: str, seed: dict, limit: int) -> str:
    return f"{route}?id={seed['video_uuid']}&host={seed['instance_domain']}&limit={limit}"


def _pinned(client, engine, route: str, size: int) -> tuple[dict, list[dict], dict]:
    """The search seed, its pool's first `size` rows on `route`, and the up-next body under which a page at limit >= size is exactly those rows."""
    seed = _rows(client, "GET", SEARCH)[0]
    chosen = upnext_pool(engine, route, seed)[:size]
    return seed, chosen, {"exclude": pin_upnext(engine, route, seed, chosen)}


def _surface(client, engine, surface: str) -> tuple[str, str, dict | None, list[dict] | None]:
    """The method, path and body of one page of the named surface, the same page on every call, and the rows an up-next page is pinned to."""
    if surface == "search":
        return "GET", SEARCH, None, None
    seed, chosen, pin = _pinned(client, engine, surface, PAGE)
    return "POST", _upnext(surface, seed, PAGE), pin, chosen


def _two_channels_of_one_account(dataset):
    """Two videos whose account is the same and whose channels differ."""
    account = dataset.execute(
        f"SELECT v.account_url {RESOLVABLE} "
        "GROUP BY v.account_url HAVING COUNT(DISTINCT v.channel_id) > 1 LIMIT 1"
    ).fetchone()["account_url"]
    rows = dataset.execute(
        f"SELECT v.video_uuid, v.instance_domain, v.channel_id, v.account_url {RESOLVABLE} "
        "AND v.account_url = ? GROUP BY v.channel_id LIMIT 2",
        (account,),
    ).fetchall()
    assert rows[0]["channel_id"] != rows[1]["channel_id"]
    return dict(rows[0]), dict(rows[1])


# --- storing blocks ----------------------------------------------------------------------


def test_a_video_s_channel_and_account_are_listed_after_blocking_and_gone_after_removal(
        engine_client, dataset):
    key = _mint(engine_client)
    by_channel, by_account = _two_channels_of_one_account(dataset)
    channel_target = ("channel", by_channel["instance_domain"], by_channel["channel_id"], "")
    account_target = ("account", "", "", by_account["account_url"])

    assert _post_block(engine_client, key, "channel", by_channel)[0] == 201
    assert _post_block(engine_client, key, "account", by_account)[0] == 201
    listed = _targets(engine_client, key)
    assert channel_target in listed
    assert account_target in listed
    assert len(listed) == 2
    assert _targets(engine_client, _mint(engine_client)) == []  # another profile's list is its own

    status, _ = engine_client.request(
        "POST", "/api/profile/blocks/remove", headers={"X-Profile-Key": key},
        body=dict(zip(TARGET_FIELDS, channel_target)))
    assert status == 204
    assert _targets(engine_client, key) == [account_target]  # channel gone, account kept

    status, _ = engine_client.request(
        "POST", "/api/profile/blocks/remove", headers={"X-Profile-Key": key},
        body=dict(zip(TARGET_FIELDS, account_target)))
    assert status == 204
    assert _targets(engine_client, key) == []


def test_a_profile_holding_1000_blocks_is_refused_a_further_one_and_keeps_1000(
        engine_client, dataset):
    key = _mint(engine_client)
    videos = [dict(row) for row in dataset.execute(
        f"SELECT v.video_uuid, v.instance_domain, v.channel_id {RESOLVABLE} "
        "GROUP BY v.instance_domain, v.channel_id LIMIT 1001"
    ).fetchall()]
    assert len(videos) == 1001

    for video in videos[:1000]:
        status, body = _post_block(engine_client, key, "channel", video)
        assert status == 201, body  # control: the first 1,000 are accepted
    assert len(_targets(engine_client, key)) == 1000

    before = _targets(engine_client, key)
    status, body = _post_block(engine_client, key, "channel", videos[1000])
    assert status == 400, body
    after = _targets(engine_client, key)
    assert len(after) == 1000
    # Refused means not stored: the list is unchanged, not trimmed to make room.
    assert sorted(after) == sorted(before)
    assert ("channel", videos[1000]["instance_domain"], videos[1000]["channel_id"], "") not in after


# --- filtering reads ---------------------------------------------------------------------


def _distinct(rows: list[dict], *taken: dict) -> dict:
    """A row sharing neither a channel nor an account with any row in `taken`."""
    return next(r for r in rows
                if _channel(r) not in {_channel(t) for t in taken}
                and r["account_url"] not in {t["account_url"] for t in taken})


@pytest.mark.parametrize("surface", [*ROUTES, "search"])
def test_blocked_channel_and_account_leave_only_the_blocking_profile_s_page(engine_client, engine, surface):
    method, path, pin, pinned = _surface(engine_client, engine, surface)
    keyless = _rows(engine_client, method, path, None, pin)
    if pinned is not None:
        # Control: the keyless page is exactly the pinned rows, so the targets taken from it would otherwise be served.
        assert _keys(keyless) == _keys(pinned), sorted(_keys(keyless))

    # Both targets are taken from this very page, and share no channel or account, so each
    # block is seen on its own.
    blocked_channel = keyless[0]
    blocked_account = _distinct(keyless, blocked_channel)
    unrelated = _distinct(list(reversed(keyless)), blocked_channel, blocked_account)

    blocker = _mint(engine_client)
    _block(engine_client, blocker, "channel", blocked_channel)
    _block(engine_client, blocker, "account", blocked_account)
    # A second profile holding a block of its own, so its request takes the filtering path too.
    bystander = _mint(engine_client)
    _block(engine_client, bystander, "channel", unrelated)

    def hit(rows: list[dict]) -> tuple[bool, bool]:
        return (any(_channel(r) == _channel(blocked_channel) for r in rows),
                any(r["account_url"] == blocked_account["account_url"] for r in rows))

    blocker_rows = _rows(engine_client, method, path, blocker, pin)
    assert blocker_rows  # the blocker still gets results
    assert not hit(blocker_rows)[0]  # blocked channel absent
    assert not hit(blocker_rows)[1]  # blocked account absent

    keyless_after = _rows(engine_client, method, path, None, pin)
    bystander_rows = _rows(engine_client, method, path, bystander, pin)
    assert hit(keyless_after) == (True, True)  # keyless still has both
    assert hit(bystander_rows) == (True, True)  # second profile too
    if pinned is not None:
        # Pinned, each page is those rows less exactly the ones its own profile blocks.
        assert _keys(blocker_rows) == _keys(r for r in pinned if hit([r]) == (False, False))
        assert _keys(keyless_after) == _keys(pinned)
        assert _keys(bystander_rows) == _keys(r for r in pinned if _channel(r) != _channel(unrelated))


@pytest.mark.parametrize("route", ROUTES)
def test_an_upnext_page_stays_full_after_blocks_remove_rows_from_it(engine_client, engine, route):
    # Pinned to a page plus the three rows the blocks remove, all of which the blocker's over-fetch is served.
    seed, chosen, pin = _pinned(engine_client, engine, route, PAGE + 3)
    keyless = _rows(engine_client, "POST", _upnext(route, seed, PAGE + 3), None, pin)
    assert _keys(keyless) == _keys(chosen), sorted(_keys(keyless))  # control: the pinned rows, whole

    key = _mint(engine_client)
    blocked = keyless[:3]
    for row in blocked:
        _block(engine_client, key, "channel", row)
    blocked_channels = {_channel(r) for r in blocked}

    rows = _rows(engine_client, "POST", _upnext(route, seed, PAGE), key, pin)
    assert len(rows) == PAGE, len(rows)
    assert not blocked_channels & {_channel(r) for r in rows}
    assert _keys(rows) == _keys(r for r in chosen if _channel(r) not in blocked_channels)


# A block replaces a follow on exactly one key. These helpers follow and list through `/api/profile/follows`.
FOLLOWS = "/api/profile/follows"
BLOCKS = "/api/profile/blocks"
KEY_FIELDS = ("kind", "instance_domain", "channel_id", "account_url")
LISTED_FIELDS = (*KEY_FIELDS, "label")

# Videos the Engine resolves and serves metadata for: embedded, no fetch errors, not NSFW.
SERVED_RESOLVABLE = (
    "FROM videos v JOIN video_embeddings e "
    "ON e.video_id = v.video_id AND e.instance_domain = v.instance_domain "
    "WHERE v.error_count = 0 AND (v.nsfw IS NULL OR v.nsfw = 0)"
)


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
        f"SELECT v.video_uuid, v.instance_domain, v.channel_id, v.account_url {SERVED_RESOLVABLE} "
        "AND v.channel_id = ? AND v.instance_domain <> ? AND v.account_url <> ? ORDER BY v.rowid LIMIT 1",
        (video["channel_id"], video["instance_domain"], video["account_url"]),
    ).fetchone())


def _unrelated(dataset, *videos: dict) -> dict:
    """A served video sharing neither a channel id nor an account with any of `videos`."""
    ids = [v["channel_id"] for v in videos]
    accounts = [v["account_url"] for v in videos]
    return dict(dataset.execute(
        f"SELECT v.video_uuid, v.instance_domain, v.channel_id, v.account_url {SERVED_RESOLVABLE} "
        f"AND v.channel_id NOT IN ({', '.join('?' * len(ids))}) AND v.account_url NOT IN ({', '.join('?' * len(accounts))}) ORDER BY v.rowid LIMIT 1",
        (*ids, *accounts),
    ).fetchone())


def _mint_profile(client) -> tuple[str, str]:
    status, body = client.request("POST", "/api/profile")
    assert status == 201, body
    return body["profile_id"], body["key"]


def _key(client) -> str:
    return _mint_profile(client)[1]


def _follow(client, key: str, body: dict) -> tuple[int, object]:
    return client.request("POST", FOLLOWS, headers={"X-Profile-Key": key}, body=body)


def _by_video(kind: str, video: dict) -> dict:
    return {"kind": kind, "uuid": video["video_uuid"], "host": video["instance_domain"]}


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


def _add_block(client, key: str, kind: str, video: dict) -> None:
    status, body = client.request("POST", BLOCKS, headers={"X-Profile-Key": key}, body=_by_video(kind, video))
    assert status == 201, body


def _channel_key(video: dict) -> tuple[str, ...]:
    return ("channel", video["instance_domain"], video["channel_id"], "")


def _account_key(video: dict) -> tuple[str, ...]:
    return ("account", "", "", video["account_url"])


def test_blocking_a_channel_removes_the_follow_of_that_channel_and_no_other_follow(engine_client, dataset):
    video = _labelled_video(dataset)
    twin = _twin(dataset, video)
    other = _unrelated(dataset, video, twin)
    key, bystander = _key(engine_client), _key(engine_client)
    for kind, followed in (("channel", video), ("channel", twin), ("account", video), ("account", other)):
        assert _follow(engine_client, key, _by_video(kind, followed))[0] == 201
    assert _follow(engine_client, bystander, _by_video("channel", video))[0] == 201
    assert _follow_keys(engine_client, key) == {_channel_key(video), _channel_key(twin), _account_key(video), _account_key(other)}  # control

    _add_block(engine_client, key, "channel", video)
    assert _follow_keys(engine_client, key) == {_channel_key(twin), _account_key(video), _account_key(other)}  # C2
    assert _block_keys(engine_client, key) == {_channel_key(video)}
    assert _follow_keys(engine_client, bystander) == {_channel_key(video)}  # C2: another profile's follow of the same channel stays


def test_blocking_an_account_removes_the_follow_of_that_account_and_no_other_follow(engine_client, dataset):
    video = _labelled_video(dataset)
    twin = _twin(dataset, video)
    other = _unrelated(dataset, video, twin)
    key, bystander = _key(engine_client), _key(engine_client)
    for kind, followed in (("account", video), ("channel", video), ("account", twin), ("account", other)):
        assert _follow(engine_client, key, _by_video(kind, followed))[0] == 201
    assert _follow(engine_client, bystander, _by_video("account", video))[0] == 201
    assert _follow_keys(engine_client, key) == {_account_key(video), _channel_key(video), _account_key(twin), _account_key(other)}  # control

    _add_block(engine_client, key, "account", video)
    # A block-add that clears only channel follows keeps the account follow; one that clears every follow on the video drops its channel's.
    assert _follow_keys(engine_client, key) == {_channel_key(video), _account_key(twin), _account_key(other)}  # C2
    assert _block_keys(engine_client, key) == {_account_key(video)}
    assert _follow_keys(engine_client, bystander) == {_account_key(video)}  # C2: another profile's follow of the same account stays
