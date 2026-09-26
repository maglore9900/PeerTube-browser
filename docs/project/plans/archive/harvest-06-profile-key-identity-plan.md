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

From `docs/project/plans/archive/06-profile-key-identity.md`:

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

## Approval

Operator approved the plan as presented, 2026-09-26.

## Config incident

When the map was about to be written, `.un/skills/devsecops/config.json` was found replaced. The whole skill directory had been refreshed at 07:45 and had brought `unstable_number_dev`'s config:
- its `project_dir`;
- about 60 foreign `test_groups`;
- no `test_db.py` entry.

With the operator's approval, the config was restored for this project:
- `version: "6"` and the path keys kept;
- `project_dir` set to this repo;
- `test_groups` = `test_db.py` plus the two entries below.

`--show-config` afterwards: `defaulted` empty, `conflicts` empty, `map_health` clean. `--audit-map` exit 0. Advisories: `test_db.py` MISSING `engine/server/data/time.py`, a misread of `import time`; both new files BARREN, because they import through `sys.path`.

## Applied

- `tests/active/test_profiles.py` (new) — the seven backend tests, whole. Helpers merged once (`_mint`, `_seed_like`, `_read`, `_liked`, `_rows_for`, `_Clock`, `_mint_from`); docstring states the rules; clause markers dropped.
- `tests/active/test_frontend_profile.py` (new) — both frontend tests, whole; docstring states the rules.
- `tests/active/conftest.py` (new) — the `client_backend` fixture, unclaimed.
- Nothing retired; `tests/archive` untouched.

## Mutations

Each production change was made on a backup copy, the named test was run, and the file was restored. Every restore was byte-identical and the test green again.

1. `resolve_profile` returns the first profile for any key → `test_a_minted_key_reads_its_own_likes…` failed: B's key read A's likes.
2. `mint_profile` stores the key itself → `test_users_db_holds…` failed at line 91 (key bytes found).
3. `_require_profile` answers a presented-but-bad key with a different body → `test_every_presentation…` failed at line 128 (two distinct refusals).
4. Mint limit set to 6 → the sixth-mint test failed at line 165.
   - One counter for every address → failed at line 167 (the other address refused).
   - A 60 s window → failed at line 165 (the sixth mint allowed).
5. Rotate inserts a new key and leaves the old one valid → `test_after_rotation_only_the_new_key…` failed at line 186.
6. `delete_profile` keeps the likes → `test_deleting_a_profile…` failed at line 210.
7. Frontend reset sends no key:
   - As first written, the reset failed at the node step (the refusal throws), not at line 133. Recorded as a different assertion felled.
   - Second mutation: no key sent and the refusal swallowed → failed at line 133 (the created profile's likes not cleared).
   - Lines 141-142 (key-less reset reaches no profile) can only fail when both the frontend guard and the server refusal are removed. The server refusal is guarded by mutation 3's test. Removing only the guard fails at line 139.
8. Frontend rotate does not store the new key → failed at line 153 (supporting). Second mutation: it stores a key the server never issued → failed at line 154 (the held key refused).

No `.bak` remains under `client/`. The mutation backups are in `delete_me/*.mutation.bak`, one per production file: each later mutation of the same file overwrote the earlier backup, and every one was restored before the next.

## Disposed

Moved to `delete_me/` (no name collided, so none was renamed):
- `conftest.py`;
- `test_profile_mint.py`, `test_profile_refusal.py`, `test_profile_lifecycle.py`, `test_profile_frontend.py`;
- `probe_actor_ids.py`, `probe_source_addr.py`, `probe_live_acs.py`, `mutate.py`.

`tests/tmp` holds only `__pycache__`.

## Final run

Snapshot restored, then `validate_tests.py --compare`, no tier:
- `test_db.py` 2 passed, `test_frontend_profile.py` 2 passed, `test_profiles.py` 8 passed; 12 passed, 3 lanes.
- Appeared: the 10 harvested test ids. Departed: none. `test_db.py` unchanged. This matches the harvest.

### Map entries to add

- `"test_profiles.py": ["client/backend/server.py", "client/backend/lib/profiles.py", "client/backend/lib/users_store.py", "client/backend/lib/http_utils.py"]`
- `"test_frontend_profile.py": ["client/frontend/src/data/profile.ts", "client/frontend/src/data/user-profile.ts", "client/backend/server.py", "client/backend/lib/profiles.py"]`
