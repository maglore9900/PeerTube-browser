# Harvest: plan 06, profile key identity

## Resolved paths (from `--show-config`, 2026-09-26)

- `project_dir`: `/home/enduser/code/PeerTube-browser`
- `active`: `tests/active`
- `working`: `tests/tmp`
- `plans`: `docs/project/plans`
- `delete_me`: `delete_me`
- `archive`: `tests/archive`
- `record`: `tests/last_test_validation.json`

Bootstrap gate clear.

## Scope

From `docs/project/plans/06-profile-key-identity.md`:

- `tests/tmp/test_profile_mint.py`
- `tests/tmp/test_profile_refusal.py`
- `tests/tmp/test_profile_lifecycle.py`
- `tests/tmp/test_profile_frontend.py`
- `tests/tmp/conftest.py` — the shared `client_backend` fixture the four depend on.

Also in `tests/tmp` from this build, not test files: `probe_actor_ids.py`, `probe_source_addr.py`, `probe_live_acs.py`. They are disposed at Step 7.

## Snapshot

`tests/last_test_validation.json.preharvest` taken before any harvest run. The record holds the `test_db.py` group only.

## Inventory

### `tests/tmp/conftest.py`

- **Provides:** `client_backend`, a real `ClientBackendServer` on an ephemeral port over a `users.db` under `tmp_path`, with the Engine address pointing at a closed port. `ClientBackend.request`.
- **Imports:** `client/backend/server.py`, `lib.http_utils.RateLimiter`, `lib.users_store.ensure_user_schema`.

### `tests/tmp/test_profile_mint.py`

- **Drives:** `client/backend/server.py` (`POST /api/profile`, `GET /api/user-profile`), `client/backend/lib/profiles.py`.
- **Tests:** `test_a_minted_key_reads_its_own_likes_and_not_another_profiles`, `test_users_db_holds_the_minted_profiles_but_none_of_their_keys`.

### `tests/tmp/test_profile_refusal.py`

- **Drives:** `server.py` (the three profile routes, `POST /api/profile` with the mint limiter), `lib/profiles.py`, `lib/http_utils.py` (`RateLimiter`, its clock).
- **Tests:** `test_every_presentation_but_a_valid_header_gets_the_same_refusal` (×3 routes), `test_a_sixth_mint_from_one_address_within_the_hour_is_refused`.

### `tests/tmp/test_profile_lifecycle.py`

- **Drives:** `server.py` (rotate, delete), `lib/profiles.py`.
- **Tests:** `test_after_rotation_only_the_new_key_reads_the_same_profile`, `test_deleting_a_profile_removes_its_rows_and_keeps_anothers`.

### `tests/tmp/test_profile_frontend.py`

- **Drives:** `client/frontend/src/data/profile.ts`, `client/frontend/src/data/user-profile.ts`, bundled by the installed esbuild and run in node against the server fixture.
- **Tests:** `test_reset_clears_the_created_profile_and_without_a_key_clears_none`, `test_after_rotation_the_browser_holds_the_key_the_server_accepts`.

## Classification

No `active` test covers the Client backend or the frontend. Every test below is **DURABLE**, and nothing is retired.

- The three backend files are one subject: the profile routes of the Client backend and `lib/profiles.py`. They go into **`tests/active/test_profiles.py`** (new), which becomes the only guard of the identity boundary.
- `test_profile_frontend.py` goes into **`tests/active/test_frontend_profile.py`** (new), named for the frontend profile module.
- `conftest.py` goes to **`tests/active/conftest.py`** as a shared helper, claimed by no group.

### Map entries to add

- `"test_profiles.py": ["client/backend/server.py", "client/backend/lib/profiles.py", "client/backend/lib/users_store.py", "client/backend/lib/http_utils.py"]`
- `"test_frontend_profile.py": ["client/frontend/src/data/profile.ts", "client/frontend/src/data/user-profile.ts", "client/backend/server.py", "client/backend/lib/profiles.py"]`
