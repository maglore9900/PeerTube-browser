"""Per-visitor profiles proved by an opaque, server-issued key.

The key is 32 random bytes, handed to the visitor once and stored only as its SHA-256.
Looking a key up by its hash is safe against timing: what a comparison could leak is the
hash, from which a 256-bit random key cannot be recovered.
"""
from __future__ import annotations

import hashlib
import re
import secrets
import sqlite3

from .time_utils import now_ms

# The exact shape `secrets.token_urlsafe(32)` produces. Anything else is refused before
# it is hashed or looked up.
KEY_PATTERN = re.compile(r"[A-Za-z0-9_-]{43}")


def _hash(key: str) -> str:
    """Return the stored form of a key."""
    return hashlib.sha256(key.encode("ascii")).hexdigest()


def mint_profile(conn: sqlite3.Connection) -> tuple[str, str]:
    """Create a profile and return its id with its key, which is never stored.

    :returns: ``(profile_id, key)``; the caller hands the key to the visitor once.
    """
    profile_id = secrets.token_urlsafe(12)
    key = secrets.token_urlsafe(32)
    now = now_ms()
    conn.execute(
        "INSERT INTO profiles (profile_id, key_hash, created_at, last_seen_at) VALUES (?, ?, ?, ?)",
        (profile_id, _hash(key), now, now),
    )
    conn.commit()
    return profile_id, key


def resolve_profile(conn: sqlite3.Connection, presented: str | None) -> str | None:
    """Return the profile a presented key proves, or None for anything else.

    :param presented: The raw `X-Profile-Key` header value, possibly absent.
    """
    if not presented or not KEY_PATTERN.fullmatch(presented):
        return None
    row = conn.execute(
        "SELECT profile_id FROM profiles WHERE key_hash = ?", (_hash(presented),)
    ).fetchone()
    return row["profile_id"] if row else None


def rotate_key(conn: sqlite3.Connection, profile_id: str) -> str:
    """Replace the profile's key and return the new one; the old key stops resolving.

    :param profile_id: A profile the caller has already proved with its current key.
    """
    key = secrets.token_urlsafe(32)
    conn.execute(
        "UPDATE profiles SET key_hash = ?, last_seen_at = ? WHERE profile_id = ?",
        (_hash(key), now_ms(), profile_id),
    )
    conn.commit()
    return key


def delete_profile(conn: sqlite3.Connection, profile_id: str) -> None:
    """Remove the profile and every row keyed to it, in one transaction.

    :param profile_id: A profile the caller has already proved with its current key.
    """
    with conn:
        conn.execute("DELETE FROM blocks WHERE profile_id = ?", (profile_id,))
        conn.execute("DELETE FROM likes WHERE user_id = ?", (profile_id,))
        conn.execute("DELETE FROM users WHERE user_id = ?", (profile_id,))
        conn.execute("DELETE FROM profiles WHERE profile_id = ?", (profile_id,))
