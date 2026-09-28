"""Profile blocks on the Client backend, against a real Engine.

- Blocking a video's channel stores the channel `(instance_domain, channel_id)`, and blocking
  its account stores the `account_url`, as `whitelist.db` holds them; the profile lists them,
  and removal takes them off the list. Another profile's list is its own.
- A profile holds at most 1,000 blocks: the next one is refused with 400 and not stored.
- Through the read gateway, a profile's search page leaves out its blocked channel and account,
  while keyless requests and other profiles still receive them.
"""
from __future__ import annotations

import pytest

TARGET_FIELDS = ("kind", "instance_domain", "channel_id", "account_url")
SEARCH = "/api/v1/search/videos?q=music&limit=20"

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


def _rows(client, method: str, path: str, key: str | None = None) -> list[dict]:
    headers = {"X-Profile-Key": key} if key else {}
    status, body = client.request(method, path, headers=headers, body={} if method == "POST" else None)
    assert status == 200, body
    return body["rows"]


def _channel(row: dict) -> tuple[str, str]:
    return (row["instance_domain"], row["channel_id"])


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


# The up-next cases, and the up-next stays-full test, were retired to tests/archive/upnext_random_draw/test_blocks.py: an up-next page is a random draw, not the same page on every call.
@pytest.mark.parametrize("surface", ["search"])
def test_blocked_channel_and_account_leave_only_the_blocking_profile_s_page(engine_client, surface):
    method, path = "GET", SEARCH
    keyless = _rows(engine_client, method, path)

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

    blocker_rows = _rows(engine_client, method, path, blocker)
    assert blocker_rows  # the blocker still gets results
    assert not hit(blocker_rows)[0]  # blocked channel absent
    assert not hit(blocker_rows)[1]  # blocked account absent

    assert hit(_rows(engine_client, method, path)) == (True, True)  # keyless still has both
    assert hit(_rows(engine_client, method, path, bystander)) == (True, True)  # second profile too
