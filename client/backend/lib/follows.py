"""A profile's follows: channels and accounts whose newest videos it wants to see.

Keyed exactly like a block (see `blocks.py`): a channel by `(instance_domain, channel_id)`, an
account by `account_url`, with `''` in the unused key columns. A follow and a block on the same
key replace each other, each inside the add's own transaction; following an account leaves a
block on one of its channels in place.
"""
from __future__ import annotations

import sqlite3
from typing import Any

from .blocks import _key
from .time_utils import now_ms

MAX_FOLLOWS = 1000


class FollowLimitReached(Exception):
    """The profile already holds `MAX_FOLLOWS` follows."""


def add_follow(conn: sqlite3.Connection, profile_id: str, target: dict[str, Any]) -> None:
    """Store a follow and drop the block on exactly the same key; re-following an existing target is a no-op.

    :raises FollowLimitReached: When the target is new and the profile is at `MAX_FOLLOWS`; nothing is written, so the block stays.
    """
    kind, instance_domain, channel_id, account_url = _key(target)
    with conn:
        exists = conn.execute(
            "SELECT 1 FROM follows WHERE profile_id = ? AND kind = ? AND instance_domain = ? "
            "AND channel_id = ? AND account_url = ?",
            (profile_id, kind, instance_domain, channel_id, account_url),
        ).fetchone()
        if exists:
            return
        count = conn.execute(
            "SELECT COUNT(*) FROM follows WHERE profile_id = ?", (profile_id,)
        ).fetchone()[0]
        if count >= MAX_FOLLOWS:
            raise FollowLimitReached
        conn.execute(
            "INSERT INTO follows (profile_id, kind, instance_domain, channel_id, account_url, label, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (profile_id, kind, instance_domain, channel_id, account_url,
             str(target.get("label") or ""), now_ms()),
        )
        conn.execute(
            "DELETE FROM blocks WHERE profile_id = ? AND kind = ? AND instance_domain = ? "
            "AND channel_id = ? AND account_url = ?",
            (profile_id, kind, instance_domain, channel_id, account_url),
        )


def remove_follow(conn: sqlite3.Connection, profile_id: str, target: dict[str, Any]) -> None:
    """Remove one follow, identified by its kind and key columns."""
    kind, instance_domain, channel_id, account_url = _key(target)
    with conn:
        conn.execute(
            "DELETE FROM follows WHERE profile_id = ? AND kind = ? AND instance_domain = ? "
            "AND channel_id = ? AND account_url = ?",
            (profile_id, kind, instance_domain, channel_id, account_url),
        )


def list_follows(conn: sqlite3.Connection, profile_id: str) -> list[dict[str, Any]]:
    """Return the profile's follows, newest first."""
    rows = conn.execute(
        "SELECT kind, instance_domain, channel_id, account_url, label, created_at FROM follows "
        "WHERE profile_id = ? ORDER BY created_at DESC, rowid DESC",
        (profile_id,),
    ).fetchall()
    return [dict(row) for row in rows]
