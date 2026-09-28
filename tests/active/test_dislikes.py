"""A profile's dislikes on the Client backend: the actions and the key rule.

- The profile's reaction to a video reads back like, dislike, undo_dislike, and a like that
  replaces a dislike; another video's reaction is its own.
- A dislike with no key or an unknown key is refused with 401, where the profile's key is
  accepted.

Every test runs the Client in `unpublished_client` mode, so no Like/UndoLike reaches the
repo's live whitelist.db.
"""
from __future__ import annotations

from urllib.parse import urlencode

UNKNOWN_KEY = "A" * 43  # the shape a minted key has, issued to nobody


def _videos(dataset, n: int) -> list[dict]:
    """n embedded, error-free videos from different channels, which the Engine resolves."""
    rows = dataset.execute(
        "SELECT v.video_uuid, v.instance_domain FROM videos v JOIN video_embeddings e "
        "ON e.video_id = v.video_id AND e.instance_domain = v.instance_domain "
        "WHERE v.error_count = 0 GROUP BY v.channel_id, v.instance_domain ORDER BY v.rowid LIMIT ?",
        (n,),
    ).fetchall()
    assert len(rows) == n
    return [{"uuid": r["video_uuid"], "host": r["instance_domain"]} for r in rows]


def _mint(client) -> dict[str, str]:
    status, body = client.request("POST", "/api/profile")
    assert status == 201, body
    return {"X-Profile-Key": body["key"]}


def _act(client, headers, action: str, video: dict) -> int:
    status, _ = client.request("POST", "/api/user-action", headers=headers,
                               body={"action": action, **video})
    return status


def _reaction(client, headers, video: dict) -> tuple[int, bool | None, bool | None]:
    status, body = client.request("GET", f"/api/profile/reaction?{urlencode(video)}", headers=headers)
    if status != 200:
        return status, None, None
    return status, body["liked"], body["disliked"]


# --- actions ------------------------------------------------------------------------------


def test_a_video_s_reaction_follows_like_dislike_undo_dislike_and_a_like_replacing_a_dislike(
        unpublished_client, dataset):
    client = unpublished_client
    key = _mint(client)
    video, other = _videos(dataset, 2)

    _act(client, key, "like", video)
    assert _reaction(client, key, video) == (200, True, False)
    # 502: this dislike removes a like, so it publishes UndoLike, which this Client cannot send.
    assert _act(client, key, "dislike", video) in (200, 502)
    assert _reaction(client, key, video) == (200, False, True)
    _act(client, key, "like", other)
    assert _reaction(client, key, other) == (200, True, False)
    assert _reaction(client, key, video) == (200, False, True)
    assert _act(client, key, "undo_dislike", video) == 200
    assert _reaction(client, key, video) == (200, False, False)
    assert _act(client, key, "dislike", video) == 200
    assert _reaction(client, key, video) == (200, False, True)
    _act(client, key, "like", video)
    assert _reaction(client, key, video) == (200, True, False)


def test_a_dislike_without_a_valid_key_is_refused_where_the_profile_s_key_is_accepted(
        unpublished_client, dataset):
    client = unpublished_client
    key = _mint(client)
    (video,) = _videos(dataset, 1)
    assert _act(client, {}, "dislike", video) == 401
    assert _act(client, {"X-Profile-Key": UNKNOWN_KEY}, "dislike", video) == 401
    assert _act(client, key, "dislike", video) == 200
    assert _reaction(client, key, video) == (200, False, True)
