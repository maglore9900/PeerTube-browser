"""A profile's blocks: channels and accounts whose videos it never wants to see.

A channel block is keyed by `(instance_domain, channel_id)` and an account block by
`account_url`, both as the Engine's dataset holds them. Unused key columns hold `''` rather
than NULL, because SQLite treats NULLs as distinct in a primary key and would admit the same
account block twice. A block replaces a follow on the same key (see `follows.py`).
"""
from __future__ import annotations

import sqlite3
from typing import Any

from .time_utils import now_ms

MAX_BLOCKS = 1000
KINDS = ("channel", "account")


class BlockLimitReached(Exception):
    """The profile already holds `MAX_BLOCKS` blocks."""


def block_target(kind: str, row: dict[str, Any]) -> dict[str, str] | None:
    """Return what blocking `kind` of the video described by `row` blocks.

    :param row: The video's metadata as the Engine returns it.
    :returns: The target with its display label, or None when the row lacks that identity.
    """
    if kind == "channel":
        instance_domain = str(row.get("instance_domain") or "")
        channel_id = str(row.get("channel_id") or "")
        if not instance_domain or not channel_id:
            return None
        label = row.get("channel_display_name") or row.get("channel_name") or channel_id
        return {"kind": kind, "instance_domain": instance_domain, "channel_id": channel_id,
                "account_url": "", "label": str(label)}
    account_url = str(row.get("account_url") or "")
    if not account_url:
        return None
    label = row.get("account_name") or account_url
    return {"kind": kind, "instance_domain": "", "channel_id": "", "account_url": account_url,
            "label": str(label)}


def _key(target: dict[str, Any]) -> tuple[str, str, str, str]:
    return (str(target.get("kind") or ""), str(target.get("instance_domain") or ""),
            str(target.get("channel_id") or ""), str(target.get("account_url") or ""))


def add_block(conn: sqlite3.Connection, profile_id: str, target: dict[str, Any]) -> None:
    """Store a block and drop the follow on exactly the same key; re-blocking an existing target is a no-op.

    :raises BlockLimitReached: When the target is new and the profile is at `MAX_BLOCKS`.
    """
    kind, instance_domain, channel_id, account_url = _key(target)
    with conn:
        exists = conn.execute(
            "SELECT 1 FROM blocks WHERE profile_id = ? AND kind = ? AND instance_domain = ? "
            "AND channel_id = ? AND account_url = ?",
            (profile_id, kind, instance_domain, channel_id, account_url),
        ).fetchone()
        if exists:
            return
        count = conn.execute(
            "SELECT COUNT(*) FROM blocks WHERE profile_id = ?", (profile_id,)
        ).fetchone()[0]
        if count >= MAX_BLOCKS:
            raise BlockLimitReached
        conn.execute(
            "INSERT INTO blocks (profile_id, kind, instance_domain, channel_id, account_url, label, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (profile_id, kind, instance_domain, channel_id, account_url,
             str(target.get("label") or ""), now_ms()),
        )
        conn.execute(
            "DELETE FROM follows WHERE profile_id = ? AND kind = ? AND instance_domain = ? "
            "AND channel_id = ? AND account_url = ?",
            (profile_id, kind, instance_domain, channel_id, account_url),
        )


def remove_block(conn: sqlite3.Connection, profile_id: str, target: dict[str, Any]) -> None:
    """Remove one block, identified by its kind and key columns."""
    kind, instance_domain, channel_id, account_url = _key(target)
    with conn:
        conn.execute(
            "DELETE FROM blocks WHERE profile_id = ? AND kind = ? AND instance_domain = ? "
            "AND channel_id = ? AND account_url = ?",
            (profile_id, kind, instance_domain, channel_id, account_url),
        )


BlockKeys = tuple[set[tuple[str, str]], set[str]]


def load_block_keys(conn: sqlite3.Connection, profile_id: str) -> BlockKeys:
    """Return the profile's blocked channels as `(instance_domain, channel_id)` and accounts."""
    channels: set[tuple[str, str]] = set()
    accounts: set[str] = set()
    for row in conn.execute(
        "SELECT kind, instance_domain, channel_id, account_url FROM blocks WHERE profile_id = ?",
        (profile_id,),
    ):
        if row["kind"] == "channel":
            channels.add((row["instance_domain"], row["channel_id"]))
        else:
            accounts.add(row["account_url"])
    return channels, accounts


def filter_blocked(rows: list[dict[str, Any]], keys: BlockKeys) -> list[dict[str, Any]]:
    """Drop every row whose channel or account is blocked."""
    channels, accounts = keys
    return [
        row for row in rows
        if (str(row.get("instance_domain") or ""), str(row.get("channel_id") or "")) not in channels
        and str(row.get("account_url") or "") not in accounts
    ]


def list_blocks(conn: sqlite3.Connection, profile_id: str) -> list[dict[str, Any]]:
    """Return the profile's blocks, newest first."""
    rows = conn.execute(
        "SELECT kind, instance_domain, channel_id, account_url, label, created_at FROM blocks "
        "WHERE profile_id = ? ORDER BY created_at DESC, rowid DESC",
        (profile_id,),
    ).fetchall()
    return [dict(row) for row in rows]
