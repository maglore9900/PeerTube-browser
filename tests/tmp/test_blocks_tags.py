"""A tag search sent through the Client's read gateway returns the tagged videos, less the channel the profile blocks, against a real Engine.

`GET /api/v1/search/videos?tag=LINUX&limit=50` through the gateway answers 200 keyless, with rows from at least two channels, every one carrying `linux` in its `tags`, and those rows are the 50 newest `linux` videos found independently in `whitelist.db` (NSFW-flagged ones left out), in order, less at most five the Engine's moderation removed. A profile blocking the first row's channel gets exactly the keyless rows less that channel's videos, in the same order. A second profile, blocking another channel, gets exactly the keyless rows less that other channel's videos, so it still has the first channel's videos and the block, not the query, removed them; its rows are all tagged.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))
from conftest import dataset, engine, engine_client, shared_trending_before, trending_seed  # noqa: E402,F401

TAG = "linux"
LIMIT = 50
TAG_SEARCH = f"/api/v1/search/videos?tag={TAG.upper()}&limit={LIMIT}"


def _newest_tagged(dataset) -> list[tuple[str, str]]:
    """The newest videos carrying TAG after trimming and lowercasing, NSFW-flagged ones left out, found in Python over whitelist.db."""
    keys = []
    for row in dataset.execute(
        "SELECT video_id, instance_domain, tags_json, nsfw FROM videos WHERE tags_json LIKE ? ORDER BY published_at DESC, video_id DESC",
        (f"%{TAG}%",),
    ):
        try:
            parsed = json.loads(row["tags_json"])
        except ValueError:
            continue
        if row["nsfw"] != 1 and isinstance(parsed, list) and any(isinstance(t, str) and t.strip(" \t\r\n").lower() == TAG for t in parsed):
            keys.append((row["video_id"], row["instance_domain"]))
            if len(keys) == LIMIT:
                break
    return keys


def _mint(client) -> str:
    status, body = client.request("POST", "/api/profile")
    assert status == 201, body
    return body["key"]


def _block_channel(client, key: str, row: dict) -> None:
    status, body = client.request("POST", "/api/profile/blocks", headers={"X-Profile-Key": key},
                                  body={"kind": "channel", "uuid": row["video_uuid"], "host": row["instance_domain"]})
    assert status == 201, body


def _tag_rows(client, key: str | None) -> list[dict]:
    status, body = client.request("GET", TAG_SEARCH, headers={"X-Profile-Key": key} if key else {})
    assert status == 200, body  # C1: the gateway forwards `tag`; a parameter outside its allowlist is answered 400
    return body["rows"]


def _channel(row: dict) -> tuple[str, str]:
    return (row["instance_domain"], row["channel_id"])


def _keys(rows) -> list[tuple[str, str]]:
    return [(row["video_id"], row["instance_domain"]) for row in rows]


def _carries(row: dict) -> bool:
    return any(tag.strip().lower() == TAG for tag in row.get("tags") or [])


def test_a_tag_search_through_the_gateway_returns_the_tagged_videos_less_the_profile_s_blocked_channel(engine_client, dataset):
    keyless = _tag_rows(engine_client, None)
    assert keyless and all(_carries(row) for row in keyless), [row.get("tags") for row in keyless[:3]]  # C1
    # The tagged set itself: the newest matches in order, less only rows the Engine's moderation removed.
    newest = _newest_tagged(dataset)
    served = set(_keys(keyless))
    assert _keys(keyless) == [key for key in newest if key in served] and len(keyless) >= LIMIT - 5, len(keyless)  # C1
    channels = {_channel(row) for row in keyless}
    assert len(channels) >= 2, channels  # control: more than one channel, so a block leaves rows behind
    blocked = _channel(keyless[0])
    unrelated = next(row for row in keyless if _channel(row) != blocked)

    blocker = _mint(engine_client)
    _block_channel(engine_client, blocker, keyless[0])
    # A second profile holding a block of its own, so its request takes the filtering path too.
    bystander = _mint(engine_client)
    _block_channel(engine_client, bystander, unrelated)

    blocker_rows = _tag_rows(engine_client, blocker)
    # The keyless page less exactly the blocked channel's videos, in the same order.
    assert _keys(blocker_rows) == _keys(row for row in keyless if _channel(row) != blocked)  # C1
    assert blocked not in {_channel(row) for row in blocker_rows}  # C1
    bystander_rows = _tag_rows(engine_client, bystander)
    assert blocked in {_channel(row) for row in bystander_rows}  # control: the block, not the query, removed the channel
    assert _keys(bystander_rows) == _keys(row for row in keyless if _channel(row) != _channel(unrelated))  # C1: its own block only
    assert all(_carries(row) for row in bystander_rows)  # C1
