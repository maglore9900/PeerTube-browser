"""Checkpoint for plan 06, Phase 3 — rotate and delete.

must_prove:
  C1 — After `POST /api/profile/rotate`, the old key is refused on `GET /api/user-profile`
       and the new key reads the same profile's likes.
  C2 — After `POST /api/profile/delete`, `users.db` holds no row in `profiles`, `users` or
       `likes` keyed to that `profile_id`, while another profile's rows remain.
"""
from __future__ import annotations

import sqlite3

from lib.users_store import record_like


def _mint(client) -> tuple[str, str]:
    status, body = client.request("POST", "/api/profile")
    assert status == 201, body
    return body["profile_id"], body["key"]


def _seed_like(db_path, profile_id: str, video_id: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    record_like(conn, profile_id, "like",
                {"video_id": video_id, "instance_domain": "h.example", "video_uuid": f"u-{video_id}"}, 100)
    conn.close()


def _read(client, key: str):
    return client.request("GET", "/api/user-profile", headers={"X-Profile-Key": key})


def _rows_for(db_path, profile_id: str) -> dict[str, int]:
    conn = sqlite3.connect(db_path)
    counts = {
        "profiles": conn.execute("SELECT COUNT(*) FROM profiles WHERE profile_id = ?", (profile_id,)).fetchone()[0],
        "users": conn.execute("SELECT COUNT(*) FROM users WHERE user_id = ?", (profile_id,)).fetchone()[0],
        "likes": conn.execute("SELECT COUNT(*) FROM likes WHERE user_id = ?", (profile_id,)).fetchone()[0],
    }
    conn.close()
    return counts


def test_after_rotation_only_the_new_key_reads_the_same_profile(client_backend):
    profile_id, old_key = _mint(client_backend)
    _seed_like(client_backend.db_path, profile_id, "v1")
    assert _read(client_backend, old_key)[0] == 200  # control: the old key worked before

    status, body = client_backend.request("POST", "/api/profile/rotate",
                                          headers={"X-Profile-Key": old_key}, body={})
    assert status == 200, body
    new_key = body["key"]
    assert new_key != old_key

    assert _read(client_backend, old_key)[0] == 401  # C1
    status, body = _read(client_backend, new_key)
    assert status == 200  # C1
    assert [like["video_id"] for like in body["likes"]] == ["v1"]  # C1


def test_deleting_a_profile_removes_its_rows_and_keeps_anothers(client_backend):
    gone_id, gone_key = _mint(client_backend)
    kept_id, kept_key = _mint(client_backend)
    for profile_id in (gone_id, kept_id):
        # record_like also creates the `users` row, so all three tables hold rows for both.
        _seed_like(client_backend.db_path, profile_id, f"v-{profile_id}")
    assert _read(client_backend, gone_key)[0] == 200
    assert _read(client_backend, kept_key)[0] == 200
    assert _rows_for(client_backend.db_path, gone_id) == {"profiles": 1, "users": 1, "likes": 1}

    # A delete without the key is refused and removes nothing.
    assert client_backend.request("POST", "/api/profile/delete", body={})[0] == 401
    assert _rows_for(client_backend.db_path, gone_id) == {"profiles": 1, "users": 1, "likes": 1}

    status, _ = client_backend.request("POST", "/api/profile/delete",
                                       headers={"X-Profile-Key": gone_key}, body={})
    assert status == 204

    assert _rows_for(client_backend.db_path, gone_id) == {"profiles": 0, "users": 0, "likes": 0}  # C2
    assert _rows_for(client_backend.db_path, kept_id) == {"profiles": 1, "users": 1, "likes": 1}  # C2
    assert _read(client_backend, gone_key)[0] == 401
