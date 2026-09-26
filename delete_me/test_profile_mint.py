"""Checkpoint for plan 06, Phase 1 — mint a profile and read only its own data.

must_prove:
  C1 — `GET /api/user-profile` with a minted key in `X-Profile-Key` returns the likes stored
       for that key's profile and none stored for another profile.
  C2 — After minting, no minted key appears anywhere in the bytes of `users.db`.
"""
from __future__ import annotations

import base64
import sqlite3

from lib.users_store import record_like


def _mint(client) -> tuple[str, str]:
    status, body = client.request("POST", "/api/profile")
    assert status == 201, body
    return body["profile_id"], body["key"]


def _seed_like(db_path, profile_id: str, video_id: str, host: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    record_like(conn, profile_id, "like",
                {"video_id": video_id, "instance_domain": host, "video_uuid": f"u-{video_id}"}, 100)
    conn.close()


def _liked(client, key: str) -> set[tuple[str, str]]:
    status, body = client.request("GET", "/api/user-profile", headers={"X-Profile-Key": key})
    assert status == 200, body
    return {(like["video_id"], like["instance_domain"]) for like in body["likes"]}


def test_a_minted_key_reads_its_own_likes_and_not_another_profiles(client_backend):
    a_id, a_key = _mint(client_backend)
    b_id, b_key = _mint(client_backend)
    assert a_id != b_id and a_key != b_key
    _seed_like(client_backend.db_path, a_id, "va", "a.example")
    _seed_like(client_backend.db_path, a_id, "va2", "a.example")
    _seed_like(client_backend.db_path, b_id, "vb", "b.example")

    assert _liked(client_backend, a_key) == {("va", "a.example"), ("va2", "a.example")}  # C1
    assert _liked(client_backend, b_key) == {("vb", "b.example")}  # C1


def test_users_db_holds_the_minted_profiles_but_none_of_their_keys(client_backend):
    minted = [_mint(client_backend) for _ in range(3)]
    conn = sqlite3.connect(client_backend.db_path)
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()
    stored = b"".join(p.read_bytes() for p in client_backend.db_path.parent.glob("users.db*"))

    # Control: the file does hold the minted profiles, so absent keys are not an empty file.
    for profile_id, _key in minted:
        assert profile_id.encode("ascii") in stored
    for _profile_id, key in minted:
        assert key.encode("ascii") not in stored  # C2
        # The key's raw bytes too, so storing it decoded is caught.
        assert base64.urlsafe_b64decode(key + "=" * (-len(key) % 4)) not in stored  # C2
