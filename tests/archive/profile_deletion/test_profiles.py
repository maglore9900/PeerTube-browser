"""Retired from `tests/active/test_profiles.py` by harvest 13 (deterministic event ids).

Its assertions live on in `test_deleting_a_profile_removes_its_rows_and_like_generations_and_keeps_anothers`,
which adds the profile's open and closed `like_generations` rows to what a delete must remove. Kept
readable here. It depends on helpers in the active file, so a bare `pytest` run skips it.
"""
import pytest

pytestmark = pytest.mark.skip(reason="retired test, kept for reference")


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

    assert _rows_for(client_backend.db_path, gone_id) == {"profiles": 0, "users": 0, "likes": 0}
    assert _rows_for(client_backend.db_path, kept_id) == {"profiles": 1, "users": 1, "likes": 1}
    assert _read(client_backend, gone_key)[0] == 401
