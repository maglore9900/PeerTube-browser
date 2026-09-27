"""Deleting a profile removes its `like_generations` rows, the open one and the closed one alike, and keeps another profile's.

A real Client backend (conftest's `client_backend`) serves POST /api/profile/delete; row counts are read straight from its users.db.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ACTIVE_DIR = ROOT / "tests" / "active"
if str(ACTIVE_DIR) not in sys.path:
    sys.path.insert(0, str(ACTIVE_DIR))
from conftest import client_backend  # noqa: E402,F401
from lib.users_store import close_like, record_like, remove_like  # noqa: E402

HOST = "h.example"


def _mint(client) -> tuple[str, str]:
    status, body = client.request("POST", "/api/profile")
    assert status == 201, body
    return body["profile_id"], body["key"]


def _seed_like(db_path, profile_id: str, video_id: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    record_like(conn, profile_id, "like", {"video_id": video_id, "instance_domain": HOST, "video_uuid": f"u-{video_id}"}, 100, publish=True)
    conn.close()


def _seed_undone_like(db_path, profile_id: str, video_id: str) -> None:
    """A published like, then undone: its likes row goes, its closed generation row stays."""
    _seed_like(db_path, profile_id, video_id)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    with conn:
        remove_like(conn, profile_id, video_id, HOST)
        close_like(conn, profile_id, video_id, HOST)
    conn.close()


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


def test_deleting_a_profile_removes_its_open_and_closed_like_generations_and_keeps_anothers(client_backend):
    gone_id, gone_key = _mint(client_backend)
    kept_id, _kept_key = _mint(client_backend)
    for profile_id in (gone_id, kept_id):
        _seed_like(client_backend.db_path, profile_id, f"v-{profile_id}")
    # A closed generation outlives its likes row, so a delete keyed on the likes it removes would leave it.
    _seed_undone_like(client_backend.db_path, gone_id, "v-undone")
    # Control: seeding left one open and one closed generation row for the profile to be deleted, one open for the other.
    assert _rows_for(client_backend.db_path, gone_id) == {"profiles": 1, "users": 1, "likes": 1, "like_generations": 2}
    assert _rows_for(client_backend.db_path, kept_id) == {"profiles": 1, "users": 1, "likes": 1, "like_generations": 1}

    # A delete without the key is refused and removes nothing.
    assert client_backend.request("POST", "/api/profile/delete", body={})[0] == 401
    assert _rows_for(client_backend.db_path, gone_id)["like_generations"] == 2  # C1

    status, _ = client_backend.request("POST", "/api/profile/delete", headers={"X-Profile-Key": gone_key}, body={})
    assert status == 204

    assert _rows_for(client_backend.db_path, gone_id) == {"profiles": 0, "users": 0, "likes": 0, "like_generations": 0}  # C1
    assert _rows_for(client_backend.db_path, kept_id) == {"profiles": 1, "users": 1, "likes": 1, "like_generations": 1}  # C1
