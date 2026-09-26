# Opaque profile key for per-visitor identity

Issue: `docs/project/issues/07-profile-key-identity.md`
Unblocks: `docs/project/plans/03-like-dislike.md` (I5-I8, via R10)

## Requirements

Confirmed by the operator 2026-09-26, all defaults accepted as written.

### What was asked

Build issue 07, as the first step of dislike and block ("Identity first"). Plan 03's O8 was settled beforehand: a profile supports **rotate and delete**; there is no recovery.

### Purpose

Each visitor can hold their own profile, proved by a server-issued key, so no server-side state is shared through the `"local-user"` fallback. This is the identity plan 03's Engine-side filter profile is keyed on.

### Current state (read 2026-09-26)

- `client/backend/lib/http_utils.py:12,33` — `resolve_user_id` returns any caller-supplied string, falling back to `DEFAULT_USER_ID = "local-user"`.
- The frontend never sends a user id. Every server-side profile row, every server-side like, and every published event's `actor_id` is `"local-user"`.
- `client/frontend/src/data/user-profile.ts` — "My likes" reads `localLikes:v1` and resolves it through `POST /api/user-profile/likes` (`USE_LOCAL_LIKES_PROFILE = true`). "Reset" posts `{}` to `/api/user-profile/reset`, which wipes `local-user`'s server-side likes for everyone.
- `client/backend/server.py:204-213` — `GET /api/user-profile` creates and reads the profile of any supplied id; no frontend caller.
- `client/backend/server.py:610-622` — `_handle_user_profile_reset` calls `read_json_body` outside a `try`.
- `client/backend/lib/http_utils.py:47-76` — CORS allows only the `content-type` request header.
- One `RateLimiter(90, 60)` keyed `"{peer ip}:{path}"`; behind nginx the peer is the proxy (issue 02).
- No frontend test harness exists (no `*.test.*`, no vitest/jest config under `client/`).

### Acceptance criteria

1. `POST /api/profile` returns `{profile_id, key}`. The key is 32 random bytes from `secrets` and is returned only in this response; only its SHA-256 hash is stored.
2. Minting is rate-limited per client address, separately from the read routes: 5 per hour.
3. A profile is proved only by the `X-Profile-Key` request header, never by a query parameter or body field.
4. On every route that requires a profile, an absent, malformed or unknown key receives the same 401 response, which does not reveal whether a profile exists.
5. `POST /api/profile/rotate` with the current key returns a new key; the old key is rejected from then on.
6. `POST /api/profile/delete` with the current key removes the profile and every row keyed to it; the key is rejected from then on.
7. `GET /api/user-profile`, `GET /api/user-profile/likes` and `POST /api/user-profile/reset` require a profile and act only on it. `resolve_user_id` and the `"local-user"` fallback no longer exist.
8. With no key, behaviour is as today: browsing, likes in `localLikes:v1`, and `POST /api/user-profile/likes` (resolving a browser-supplied like list) all work. `POST /api/user-action` still publishes its event, records a server-side like only when a key is presented, and sets `actor_id` to the `profile_id`, or to `"anonymous"` without a key.
9. Existing `"local-user"` rows in `users.db` are deleted.
10. A "Profile" button in the header of the home and videos pages (`index.html`, `videos.html`) opens the existing profile modal, which gains a profile section above the likes. _(Amended at Step 4: the modal as originally named is unreachable, because its opener sits in a hidden section.)_ The profile section lets a visitor create a profile (the key shown once, copyable, stating it is the only copy), use an existing key in this browser, rotate it, and delete the profile. The key is kept in `localStorage` and sent as `X-Profile-Key` on profile routes. "Reset" without a profile clears only local likes.
11. `_handle_user_profile_reset` answers a malformed body with 400, as its sibling handlers do.
12. CORS allows the `x-profile-key` request header. `DEPLOYMENT.md` states the key must travel over TLS beyond localhost.

### In scope

`client/backend/lib/http_utils.py`, `client/backend/lib/users_store.py`, a new profile module under `client/backend/lib/`, `client/backend/server.py`, `client/frontend/src/data/user-profile.ts`, a new frontend profile data module, `client/frontend/src/pages/videos/index.ts`, the modal markup in `client/frontend/index.html` and `client/frontend/videos.html`, `DEPLOYMENT.md`.

### Out of scope

The Engine-side filter profile, dislikes and blocks (plan 03); issue 01's deterministic event ids; key recovery; expiry of idle profiles; issue 02's trusted-proxy address resolution.

### Consistency constraints

Backend matches `client/backend` style: stdlib `http.server`, `respond_json`, `sqlite3.Row`, module docstrings, `from __future__ import annotations`. Frontend matches `data/*.ts` (fetch through `resolveClientApiBase`, `readErrorMessage`) and the existing modal and `ghost-button` markup. Every value rendered into the modal is escaped. Backwards compatibility is not required.

### Conflicts

- **AC2 vs issue 02.** The limiter keys on the TCP peer, which behind nginx is the proxy, so until issue 02 lands the 5-per-hour mint limit is per deployment, not per visitor. Accepted as written; issue 02 stays separate.
- **Frontend verification.** No frontend test harness exists; how the frontend phase is checked is settled at Step 6.

### Test trees for this build

- `active`: `tests/active`
- `working`: `tests/tmp`

### Baseline suite state

2026-09-26, fresh run at Step 0: `tests/active/test_db.py` 2 passed, exit 0. Green.

## High-level plan

Approved by the operator 2026-09-26.

### Approach

- **Store.** A `profiles` table in the Client's `users.db`: `profile_id TEXT PRIMARY KEY` (opaque, random, independent of the key), `key_hash TEXT NOT NULL UNIQUE`, `created_at`, `last_seen_at`. The existing `users` and `likes` tables key on `profile_id`, so the routes in AC7 keep their storage. Deleting a profile removes its `profiles`, `users` and `likes` rows in one transaction.
- **`client/backend/lib/profiles.py` (new).**
  - `mint_profile` generates the key with `secrets.token_urlsafe(32)` and stores its SHA-256.
  - `resolve_profile` rejects anything that is not the exact token shape (43 base64url characters) before hashing, then looks the hash up.
  - `rotate_key` replaces the hash.
  - `delete_profile` removes the profile's rows.
- **`client/backend/server.py`.** Three routes: `POST /api/profile`, `/api/profile/rotate`, `/api/profile/delete`. A `_require_profile()` helper sends the single fixed 401 (AC4). Minting has its own `RateLimiter(5, 3600)`. `resolve_user_id` is removed: the profile routes call `_require_profile()`, and `/api/user-action` does an optional lookup (AC8).
- **Migration.** `ensure_user_schema` deletes `"local-user"` rows once. The statement is idempotent (AC9).
- **CORS and docs.** The CORS header list in `http_utils.py` gains `x-profile-key`; `DEPLOYMENT.md` gets the TLS note (AC12).
- **Frontend.**
  - `client/frontend/src/data/profile.ts` (new) owns the stored key and the create, use-existing, rotate and delete calls.
  - `user-profile.ts` sends the header.
  - The "My likes" modal gets a profile section in `index.html` and `videos.html`, wired in `pages/videos/index.ts`.

### Alternatives

- **Signed httpOnly cookie** — rejected in plan 03 O7: not portable across devices, adds a CSRF surface and cookie consent.
- **Identity in the Engine** — breaks the Client-owns-user-state boundary; the Engine receives only a verified `profile_id` over the authenticated bridge.
- **`hmac.compare_digest` over stored keys** (issue 07's wording) — needs a full scan or a second secret. Lookup by SHA-256 of a 256-bit random key is the standard API-key pattern: a timing leak can reveal the hash, never the key.

### Risks

- **R1** — A key in `localStorage` is readable by any script on the page. Accepted in O7; CSP and the escaping work reduce it.
- **R2** — Until issue 02 lands, the mint limit is shared by the whole deployment. It is too tight for many visitors, and gives no per-visitor protection against abuse.
- **R3** — Rotating logs out every other tab or device holding the old key: they get 401. Intended; the UI must say so.
- **R4** — Server-side like writes from `/api/user-action` become profile-only. Nothing displays server-side likes without a profile today.
- **R5** — No frontend test harness; the UI phase rests on the operator's manual browser check unless one is added.

### Tradeoffs accepted

No recovery path; a mint limit shared by the whole deployment until issue 02; the key held in `localStorage`.

## Impacts

### Profile store module (NEW)
- **path:** `client/backend/lib/profiles.py`
- **Changes:** `mint_profile`, `resolve_profile`, `rotate_key`, `delete_profile`, and the key-shape check.
- **Depends on it:** `server.py` profile routes, `_require_profile`, `_handle_user_action`.
- **Regression risk:** high — the security boundary for every profile route.

### User schema
- **path:** `client/backend/lib/users_store.py` (`ensure_user_schema`, lines 10-30)
- **Changes:** creates `profiles`; deletes `"local-user"` rows from `users` and `likes`.
- **Depends on it:** `server.py` `main` (line 772), every function in the module.
- **Regression risk:** medium. The delete runs at every start; it must stay idempotent and never touch a real profile's rows.

### User identity helper and CORS
- **path:** `client/backend/lib/http_utils.py` (lines 12, 33-39, 47-49, 63-65, 73-76)
- **Changes:** `DEFAULT_USER_ID` and `resolve_user_id` removed; `access-control-allow-headers` gains `x-profile-key` in `respond_json`, `respond_bytes`, `respond_options`.
- **Depends on it:** `server.py` import (line 25) and five call sites.
- **Regression risk:** low.

### Client backend routes
- **path:** `client/backend/server.py`
- **Changes:**
  - Profile routes: `/api/user-profile` GET (204-213), `/api/user-profile/likes` GET (214-219, 624-637), `/api/user-profile/reset` (237-242, 610-622) require a profile.
  - New routes: `POST /api/profile`, `/api/profile/rotate`, `/api/profile/delete`.
  - `_handle_user_action` (518-608): optional profile, like writes only with one, `actor_id` from it.
  - `ClientBackendServer.__init__` (119-133) and `main` (773-780) gain the mint limiter.
  - Imports (25-29).
- **Depends on it:** the frontend data modules, both smoke scripts.
- **Regression risk:** high — every write/profile route changes.

### Gateway `user_id` passthrough
- **path:** `client/backend/server.py` (lines 51-71, `PROXY_ALLOWED_QUERY_PARAMS` and `PROXY_ALLOWED_BODY_KEYS`)
- **Changes:** none. A caller-supplied `user_id` is still forwarded to the Engine on `/recommendations`, `/videos/similar` and `/api/video`. The Engine ignores it for likes (`engine/server/api/request_context.py:43-51`, `DEFAULT_USE_CLIENT_LIKES = True`), so no identity rides on it.
- **Regression risk:** none; noted so plan 03 does not mistake it for identity.

### Frontend profile module (NEW)
- **path:** `client/frontend/src/data/profile.ts`
- **Changes:** the stored key (`localStorage`); create, use-existing, rotate and delete calls; the header helper.
- **Depends on it:** `user-profile.ts`, `user-actions.ts`, `pages/videos/index.ts`.
- **Regression risk:** medium.

### Frontend likes/profile client
- **path:** `client/frontend/src/data/user-profile.ts`
- **Changes:** `resetUserProfileLikes` sends the header, or skips the server call without a key.
- **Depends on it:** `pages/videos/index.ts` (lines 8, 91-114).
- **Regression risk:** low.

### Frontend user action
- **path:** `client/frontend/src/data/user-actions.ts`
- **Changes:** sends `X-Profile-Key` when a key is stored, so a like is recorded server-side for that profile (AC8).
- **Depends on it:** `pages/video-page/index.ts` like button.
- **Regression risk:** low. Without a key, the request is unchanged.

### Videos page script
- **path:** `client/frontend/src/pages/videos/index.ts` (lines 43-45, 91-114, modal functions)
- **Changes:** profile section wiring: create (key shown once), use-existing, rotate, delete; reset behaviour.
- **Depends on it:** `index.html`, `videos.html`.
- **Regression risk:** medium — the home feed page.

### Page markup
- **path:** `client/frontend/index.html`, `client/frontend/videos.html` (lines 30-59)
- **Changes:** a "Profile" button in the header nav that opens `#profile-modal`; a profile section in the modal above the likes. The modal's existing opener, `#show-profile`, sits in `<section class="summary" hidden>`, which stays hidden.
- **Regression risk:** medium.

### Videos page styles
- **path:** `client/frontend/src/videos.css`
- **Changes:** styles for the profile section, reusing `.ghost-button`, `.modal-*`.
- **Regression risk:** low.

### Built frontend
- **path:** `client/frontend/dist/`
- **Changes:** rebuilt by `npm run build`; production serves the rsynced `dist/` (`DEPLOYMENT.md`), so the UI is not live until rebuilt and deployed.
- **Regression risk:** low.

### Architecture smoke
- **path:** `tests/run-arch-split-smoke.sh` (lines 578-601)
- **Changes:** `client_profile_likes` does `GET /api/user-profile/likes` with no identity and expects 200 plus a non-empty likes array after an anonymous like. Under AC7-AC8 that is a 401. The smoke must mint a profile and send `X-Profile-Key` on the like and the read.
- **Regression risk:** high if left: the smoke goes red.

### Installer smoke
- **path:** `tests/run-installers-smoke.sh` (lines 441-451, 643-670)
- **Changes:**
  - It sends `user_id` in the like body and the likes query, resets with a `user_id` body, and `verify_engine_event_recorded` finds the Engine event by `actor_id == user_id`.
  - Under AC8 the actor is the `profile_id`, so the smoke must mint a profile, use the header, and look the event up by `profile_id`. The cleanup deletes the profile.
- **Regression risk:** high if left.

### Highest risk

1. `client/backend/lib/profiles.py` — the key check, hashing and lookup are the whole security boundary; a lookup that accepts a prefix, a case-folded match or an empty header grants someone else's profile.
2. `client/backend/server.py` profile routes — a route missed by `_require_profile` keeps acting on whatever identity it had, now with no fallback defined.
3. `tests/run-installers-smoke.sh` — it encodes the old identity model end to end (body `user_id`, Engine `actor_id`), and the installers are how deployments are validated.

### Reassessment

**Pass 1.** Opened every path above.

1. *Will it still work as intended?* Not as written: AC10's modal is unreachable. `#show-profile` is inside `<section class="summary" hidden>` in `index.html:30` and `videos.html:30`, and no script unhides it.
2. *Ramifications?* Both smoke scripts encode the old identity model and would fail. `run-arch-split-smoke.sh:591` expects an anonymous 200 with likes; `run-installers-smoke.sh:643-670` finds the Engine event by the body `user_id`. The UI is not live until `dist/` is rebuilt and rsynced.
3. *What else must happen?* Update both smoke scripts and the three docs in the checklist.
4. *How is functionality altered?*
   - Anonymous likes are no longer written server-side.
   - Profile reads without a key get 401 instead of the shared row.
   - "Reset" without a profile clears only local likes.
   - Engine events carry `profile_id` or `"anonymous"` as `actor_id` instead of `"local-user"`.

Recommendation approved by the operator: a "Profile" button in the header of the home and videos pages opens the modal; the hidden summary controls stay hidden. AC10 amended. The two smoke scripts were added to the inventory above.

**Pass 2.** Re-read the markup entry against `index.html` and `videos.html`. The header nav is in the same files already listed, and only these two pages carry the modal. No new impact, no unconfirmed entry. Converged.

### Documentation to update

- [ ] `client/README.md` (lines 11-21) — route list gains `/api/profile*`; profile routes require `X-Profile-Key`.
- [ ] `README.md` (lines 129-136) — the smoke checks it describes (`/api/user-profile/likes` non-empty after a like) now need a profile.
- [ ] `DEPLOYMENT.md` — TLS requirement for the key beyond localhost; CORS header; the rebuild-and-rsync step for the UI.

## Implementation plan

### Draft (Step 5)

Ladder: `secrets`, `hashlib` and `sqlite3` are stdlib (rung 3); the rate limiter and `respond_json` already exist (rung 2). No dependency is added.

**`client/backend/lib/profiles.py`**

```python
KEY_PATTERN = re.compile(r"[A-Za-z0-9_-]{43}")  # secrets.token_urlsafe(32)

def _hash(key: str) -> str: return hashlib.sha256(key.encode("ascii")).hexdigest()

def mint_profile(conn) -> tuple[str, str]:
    profile_id, key = secrets.token_urlsafe(12), secrets.token_urlsafe(32)
    conn.execute("INSERT INTO profiles (profile_id, key_hash, created_at, last_seen_at) VALUES (?,?,?,?)", ...)
    conn.commit(); return profile_id, key

def resolve_profile(conn, presented: str | None) -> str | None:
    if not presented or not KEY_PATTERN.fullmatch(presented): return None
    row = conn.execute("SELECT profile_id FROM profiles WHERE key_hash = ?", (_hash(presented),)).fetchone()
    return row["profile_id"] if row else None

def rotate_key(conn, profile_id) -> str        # new key, UPDATE key_hash, commit
def delete_profile(conn, profile_id) -> None    # DELETE likes, users, profiles WHERE id; one commit
```

**`users_store.ensure_user_schema`** adds `CREATE TABLE IF NOT EXISTS profiles (profile_id TEXT PRIMARY KEY, key_hash TEXT NOT NULL UNIQUE, created_at INTEGER NOT NULL, last_seen_at INTEGER NOT NULL)`, and `DELETE FROM likes/users WHERE user_id = 'local-user'`.

**`server.py`**
- `PROFILE_MINT_MAX_REQUESTS = 5`, `PROFILE_MINT_WINDOW_SECONDS = 3600`.
- `ClientBackendServer.__init__` takes `mint_rate_limiter`.
- `_profile_id()` returns `resolve_profile(user_db, self.headers.get("X-Profile-Key"))`. `_require_profile()` returns it, or sends `401 {"error": "Profile key required"}` and returns `None`.
- `POST /api/profile` → 429 over the mint limit, else 201 `{profile_id, key}`.
- `POST /api/profile/rotate` → `{key}`.
- `POST /api/profile/delete` → 204.
- The three `/api/user-profile*` handlers use `_require_profile()` in place of `resolve_user_id`.
- `_handle_user_action` uses `_profile_id()`: `record_like`/`remove_like` only when not `None`; `actor_id = profile_id or "anonymous"`.
- `_handle_user_profile_reset` wraps `read_json_body` in `try`.

**`http_utils.py`** drops `DEFAULT_USER_ID`/`resolve_user_id`; `access-control-allow-headers: content-type, x-profile-key`.

**`client/frontend/src/data/profile.ts`**
- `STORAGE_KEY = "profileKey:v1"`.
- `getProfileKey()` and `profileHeaders()`, which returns `{ "x-profile-key": key }` or `{}`.
- `createProfile(apiBase)` stores the returned key and returns it.
- `useProfileKey(key)` stores a pasted key.
- `rotateProfileKey(apiBase)` stores the new key.
- `deleteProfile(apiBase)` clears the stored key.
- `user-profile.ts` and `user-actions.ts` spread `profileHeaders()`; `resetUserProfileLikes` returns `[]` without a server call when no key is stored.

**UI.** A `#show-profile-header` `ghost-button` in `.header-nav` of `index.html` and `videos.html` opens `#profile-modal`. The modal gains a `#profile-section` above the likes: no key → "Create profile" and "Use a key"; key → "Rotate key", "Delete profile"; a newly issued key is rendered once in a read-only input with a copy button and the sentence "This is the only copy of your key." All text goes through `textContent`.

**Smoke scripts.** Both mint a profile first (`POST /api/profile`), send `X-Profile-Key` on the like and the profile reads, and `run-installers-smoke.sh` looks the Engine event up by the returned `profile_id`, then deletes the profile instead of resetting a `user_id`.

Checked against the plan and requirements: every AC maps to a draft element above. Converged on pass 1.

### Phases

Common seam for Phases 1-3: a real `ClientBackendServer` on `127.0.0.1:0` in a thread, over a `users.db` under `tmp_path`, driven by `urllib` requests from the test. `engine_ingest_base` points at a closed port: every route these phases assert on either never calls the Engine (`GET /api/user-profile`, `/api/profile*`) or refuses before calling it. No existing Client harness enters in-process; the precedent for driving the running server is `tests/run-arch-split-smoke.sh`, which enters the same routes over HTTP.

#### Phase 1 — Mint a profile and read only its own data

- **Kind:** code
- **Files:** `client/backend/lib/profiles.py` (NEW), `client/backend/lib/users_store.py` (EDITED), `client/backend/server.py` (EDITED), `client/backend/lib/http_utils.py` (EDITED), `tests/tmp/conftest.py` (NEW, shared server fixture), `tests/tmp/test_profile_mint.py` (NEW, checkpoint)
- **Intent (post-phase state):** A visitor who calls `POST /api/profile` receives a key that, presented in `X-Profile-Key`, makes `GET /api/user-profile` answer with that profile's likes and no other profile's, while `users.db` holds no copy of the key.
- **Clauses:**
  - `C1` — `GET /api/user-profile` with a minted key in `X-Profile-Key` returns the likes stored for that key's profile and none stored for another profile.
  - `C2` — After minting, no minted key appears anywhere in the bytes of `users.db`.
- **Checkpoint and seam:** the common seam. Two profiles are minted over HTTP; likes are seeded for each through `users_store.record_like` under the returned `profile_id`s (fixture setup, since recording a like over HTTP needs the Engine); each key reads back only its own. C2 reads the database file's bytes after minting and checkpoints the WAL.

- **Scaffolding (7.1):** `client/backend/lib/profiles.py` with `mint_profile` and `resolve_profile` raising `NotImplementedError`; `POST /api/profile` wired to `mint_profile` in `server.py`.
- **Probe (observed):** with a plaintext implementation swapped in for one run — `mint_profile` storing the key as-is, `GET /api/user-profile` left on `resolve_user_id` — test 1 failed at line 42 (`set() == {('va', 'a.example')}`) and test 2 at line 57 (the key found in the bytes of `users.db`), with both controls passing. Scaffolding restored afterwards (backup in `delete_me/profiles.scaffold.bak`).

**Self-check (dispatch 1)** — `tests/tmp/test_profile_mint.py`

- `C1 — test_profile_mint.py:42-43, likes read with each profile's key — expected: {("va","a.example")} and {("vb","b.example")} — under a read route that ignores the header (today's resolve_user_id → "local-user"): set() (observed); under one that returns every profile's likes: both pairs for each key.`
- `C2 — test_profile_mint.py:57, each minted key's bytes absent from users.db* — expected: absent — under plaintext storage: present (observed).`

Supporting (no row): `_mint`'s 201; the two profiles differing (line 38); line 54, each `profile_id` present in the file, which arms C2 against an empty or unwritten file.

1. **Whole claim** — C1's "its own" and "none of another's" are both carried by exact set equality, in both directions. C2 covers every minted key, three of them.
2. **Absence only** — C2 is armed by line 54; C1 is equality, not absence.
3. **Echoed literal** — no: the likes come back through the route from `users.db`, and the keys from the server.
4. **One value** — two profiles, each read by its own key.
5. **The double** — none: the real server, the real `users_store`, a real SQLite file. `record_like` seeds the likes as fixture setup, because liking over HTTP needs the Engine; that is data setup, not a stand-in for the code under test.
6. **It collects** — 2 node ids.
7. **Observed** — the wrong-implementation readings come from the probe run above.
8. **Red** — yes: exit 1, 2 failed.
9. **Right reason** — both fail inside `_mint` (line 16) with `RemoteDisconnected`. The server's traceback shows `NotImplementedError` raised from `mint_profile`, the scaffolding body. That is the phase's own behaviour missing, not a harness defect: the probe run shows the harness reaching the clause assertions once minting exists.
10. **Observed expected output** — the expected sets are the fixtures' seeded values; the wrong-implementation values are from the probe.

**Checkpoint audit**

- Dispatch 1:
  - `AUDIT: devsecops-test-shape-auditor — PASS. Predicted failure: both tests error in _mint (line 16), RemoteDisconnected after mint_profile raises NotImplementedError.`
  - `AUDIT: devsecops-test-claim-auditor — PASS. CLAUSE MAP: 10 rows (C1a, C1b, C2a, C2b, D1, D2, N1-N4), all CARRIED.`
- Recommendations taken before the test gated (covered by that record):
  - (shape) Assert each key's decoded raw bytes absent as well.
  - (claim) Seed two likes for profile A, so a read returning only the newest like fails.
- Recommendation left to Phase 2: failure paths, which are Phase 2's checkpoint.
- Re-run: still red at `_mint` for the same reason.
- Dispatch 2:
  - `AUDIT: devsecops-test-shape-auditor — PASS. Predicted failure: both error in _mint at line 17, RemoteDisconnected. Recommendation: the comment on the raw-bytes check claimed "or re-encoded"; narrowed to "decoded" (comment-only edit).`
  - `AUDIT: devsecops-test-claim-auditor — PASS. CLAUSE MAP: the same 10 rows, all CARRIED. Observations only (failure paths → Phase 2; the decode line depends on the key format, which the implementation fixes as base64url).`

**Changes**

- `client/backend/lib/profiles.py` — `KEY_PATTERN`, `_hash`, `mint_profile`, `resolve_profile`.
- `client/backend/lib/users_store.py` — `profiles` table in `ensure_user_schema`; the one-time `"local-user"` delete (AC9).
- `client/backend/server.py` — `POST /api/profile` → 201 `{profile_id, key}`; `_require_profile`; `GET /api/user-profile` uses it in place of `resolve_user_id`; imports.
- `client/backend/lib/http_utils.py` — not yet touched; its changes land with Phase 2's routes.

**Checkpoint outcome** — PASS: `test_profile_mint.py` 2 passed, exit 0.

#### Phase 2 — Refuse every other presentation, and bound minting

- **Kind:** code
- **Files:** `client/backend/server.py` (EDITED), `tests/tmp/test_profile_refusal.py` (NEW, checkpoint)
- **Intent (post-phase state):** Each profile-requiring route answers a request without a valid `X-Profile-Key` with one identical 401, and one client address cannot mint more than five profiles an hour.
- **Clauses:**
  - `C1` — On `GET /api/user-profile`, `GET /api/user-profile/likes` and `POST /api/user-profile/reset`, an absent header, a malformed key, an unknown well-formed key, and a valid key sent in the query string or body instead of the header all receive the same status and the same body.
  - `C2` — The sixth `POST /api/profile` from one client address within an hour is refused with 429, and the first five succeed.
- **Checkpoint and seam:** the common seam. C1 parametrizes over the three routes, taken as a list in the test, and the four bad presentations, and compares each response to the others. A valid key on the header is the positive control proving the route does serve a real profile. C2 mints six times.

**Self-check (dispatch 1)** — `tests/tmp/test_profile_refusal.py`

- `C1 — test_profile_refusal.py:52-53, the six bad presentations collapse to one (status, body) and it is 401 — expected: 1 distinct response, 401 — under the unbound routes (resolve_user_id): 5 and 4 distinct 200 responses, "in body" serving the minted profile_id's data (observed).`
- `C2 — test_profile_refusal.py:58-59, six mints from 127.0.0.1 — expected: [201]*5 then 429 — under an unlimited mint: the sixth is 201 (observed).`

Supporting (no row): `_mint`'s 201; line 45, the valid-header control `!= 401`, which proves each route serves a real profile, so a route refusing everything cannot pass.

1. **Whole claim** — all three routes (parametrized), all four presentation kinds (six requests: absent, malformed, unknown, key in query, id in query, body), "same status and same body" by set size 1, and the refusal pinned to 401. C2 carries both halves.
2. **Absence only** — no; the control at line 45 arms C1.
3. **Echoed literal** — no.
4. **One value** — six presentations compared across each other, three routes.
5. **The double** — none.
6. **It collects** — 4 node ids (3 parametrized, 1).
7. **Observed** — the wrong-implementation values are from this red run.
8. **Red** — exit 1: 3 failed, 1 passed. The passing case is `GET /api/user-profile`, which Phase 1 bound; it stays as coverage of the third route in C1's list.
9. **Right reason** — the first run failed on a harness defect: `TypeError`, unhashable lists in the response bodies at line 50. It was rewritten to compare canonical JSON. The second run fails at line 52 (`assert 5 == 1`, `4 == 1`) and at line 59 (`201 == 429`), because the routes and the mint are not bound yet.
10. **Observed expected output** — yes.

**Checkpoint audit, dispatch 1**

- `AUDIT: devsecops-test-shape-auditor — PASS. Predicted failure: /api/user-profile passes (bound in Phase 1); /likes and /reset fail at line 52; the mint test at line 59. Recommendation: per-address grouping tried at one address only.`
- `AUDIT: devsecops-test-claim-auditor — BLOCK: C2 is per client address and per hour, and the test used one address and no elapsed time, so a global counter, a 60 s window or a lifetime cap all passed. Fixed: see below.`
- **Frozen ledger:** 17 rows. UNCARRIED: C2c (per address), C2d (hour window), N2 (the name's "within the hour").
  - **C2c — fixed.** After the first address is refused, a mint from `127.0.0.2` must return 201 (line 102). This excludes one counter shared by every address. The probe `tests/tmp/probe_source_addr.py` confirmed the server sees `127.0.0.2` as a separate peer.
  - **C2d — fixed.** The limiter's clock (`lib.http_utils.datetime`) is replaced by a controllable one, a stand-in for a system boundary. The sixth mint at +3599 s must be 429 (line 100), which excludes a 60 s window. A mint at +3601 s must be 201 (line 105), which excludes a lifetime cap.
  - **N2 — fixed.** The test was renamed `test_a_sixth_mint_from_one_address_within_the_hour_is_refused`, and the window is now asserted.
- **Recommendations:**
  - (claim, bounds) Taken: the malformed presentations are now empty, 42 characters, 44 characters, 43 characters with `!`, and `not-a-key`.
  - (claim, independence) Not taken: every test gets a fresh server from the fixture, so a fresh mint limiter.

**Self-check (dispatch 2)**

- `C1 — test_profile_refusal.py:63-64, ten bad presentations → one response, 401 — under the unbound routes: 7 distinct 200 responses on /likes and /reset (observed).`
- `C2 — test_profile_refusal.py:99-105, five 201s; the sixth at +3599 s is 429; 127.0.0.2 gets 201; 127.0.0.1 at +3601 s gets 201.`
  - Under an unlimited mint the sixth is 201 (observed, line 100).
  - Under one global counter the other address gets 429.
  - Under a 60 s window the sixth is 201.
  - Under a lifetime cap the call at +3601 s is 429.

  Those last three are predictions from the limiter's code. They are checked by mutation at the harvest, because no such implementation exists to run against now.

Questions 2-7 walked again. The only double is the clock, which is a system boundary. The test collects 4 nodes. It is still red for its own reason: C1 fails at line 63 (`7 == 1`) and C2 at line 100 (`201 == 429`).

**Checkpoint audit, dispatch 2**

- `AUDIT: devsecops-test-shape-auditor — PASS. Predicted failure: line 63 for /likes and /reset; line 100 (201) for the mint. Recommendation: pin the positive control at line 41 to the success status. Taken: changed to == 200.`
- `AUDIT: devsecops-test-claim-auditor — PASS. CLAUSE MAP: 17 rows, all CARRIED, including C2c (line 102), C2d (lines 100 and 104) and N2.`
- The claim auditor made two observations, which don't block:
  - The name was widened, and line 102 carries the added words.
  - Line 104 relies on refused attempts not counting toward the window, which is how `RateLimiter.allow` works: it returns before appending.

**Changes**

- `client/backend/server.py`:
  - `PROFILE_MINT_MAX_REQUESTS = 5`, `PROFILE_MINT_WINDOW_SECONDS = 3600`.
  - `ClientBackendServer.mint_rate_limiter`, keyed on the peer address in `POST /api/profile`, answering 429.
  - `_handle_user_profile_likes_get` and `_handle_user_profile_reset` use `_require_profile`. Reset reads its body inside `try` and answers 400 when it is malformed (AC11).
  - `_handle_user_action` resolves the key optionally. It records or removes a server-side like only for a profile, and sets `actor_id` to the `profile_id` or `"anonymous"` (AC8). Its response no longer echoes `user_id`.
  - `resolve_user_id` is no longer imported.
- `client/backend/lib/http_utils.py` — `DEFAULT_USER_ID` and `resolve_user_id` are deleted. `ALLOWED_REQUEST_HEADERS = "content-type, x-profile-key"` is used by all three CORS writers (AC12). This file is in Phase 1's files list and was changed here: an inventory gap between phases, recorded.

**Checkpoint outcome** — PASS: `test_profile_refusal.py` 4 passed, and `test_profile_mint.py` still 2 passed.

#### Phase 3 — Rotate and delete

- **Kind:** code
- **Files:** `client/backend/server.py` (EDITED), `client/backend/lib/profiles.py` (EDITED), `tests/run-arch-split-smoke.sh` (EDITED), `tests/run-installers-smoke.sh` (EDITED), `tests/tmp/test_profile_lifecycle.py` (NEW, checkpoint)
- **Intent (post-phase state):** A visitor can rotate their key, after which only the new key reads their profile, and can delete their profile, after which nothing keyed to it remains in `users.db`.
- **Clauses:**
  - `C1` — After `POST /api/profile/rotate`, the old key is refused on `GET /api/user-profile` and the new key reads the same profile's likes.
  - `C2` — After `POST /api/profile/delete`, `users.db` holds no row in `profiles`, `users` or `likes` keyed to that `profile_id`, while another profile's rows remain.
- **Checkpoint and seam:** the common seam; C2 reads `users.db` directly after the request, which is the claim itself (rows removed), with the second profile's surviving rows as the positive control.
- **Scaffolding (7.1):** `rotate_key` and `delete_profile` raising `NotImplementedError`; `POST /api/profile/rotate` and `/api/profile/delete` wired behind `_require_profile`.
- **Probe (observed):** two wrong implementations were swapped in for one run, then restored (backup in `delete_me/profiles.phase3-scaffold.bak`):
  - A rotate that adds a new key without retiring the old one failed at line 56 (`200 == 401`).
  - A delete that removes only the `profiles` row failed at line 76 (`users` and `likes` still 1).

**Self-check (dispatch 1)** — `tests/tmp/test_profile_lifecycle.py`

- `C1 — test_profile_lifecycle.py:56-59, old key refused, new key reads ["v1"] — expected: 401, 200, ["v1"] — under a rotate that does not retire the old key: 200 at line 56 (observed); under a rotate whose new key maps to a fresh profile: likes [] at line 59.`
- `C2 — test_profile_lifecycle.py:76-77, row counts for the deleted and the kept profile — expected: all 0 / all 1 — under a delete of only the profiles row: users 1, likes 1 (observed); under a delete that wipes every profile: the kept profile's counts 0.`

Supporting (no row): the mint 201s; line 49, the old key reading before rotation; line 52, the rotate returning 200 with a different key; lines 71-73, both profiles read and three rows present before deletion; line 76's 204.

1. **Whole claim** — yes. C1 covers both "old refused" and "new reads the same likes". C2 covers all three tables and "another's remain".
2. **Absence only** — no. C1's refusal is armed by line 49; C2's zeros are armed by line 73 and by line 77.
3. **Echoed literal** — no.
4. **One value** — two profiles in C2; old against new key in C1.
5. **The double** — none. `record_like` seeds fixtures.
6. **It collects** — 2 node ids.
7. **Observed** — wrong-implementation readings come from the probe.
8. **Red** — exit 1, 2 failed.
9. **Right reason** — both fail with `RemoteDisconnected` at the rotate request (line 50) and the delete request (line 72), and the server trace shows `NotImplementedError` from the scaffolding. The probe shows the harness reaching the clause assertions once the functions exist.
10. **Observed expected output** — yes.

**Checkpoint audit**

- `AUDIT: devsecops-test-shape-auditor — PASS. Predicted failure: both tests error with RemoteDisconnected at the rotate request (line 50) and the delete request (line 72), NotImplementedError inside the handler.`
- `AUDIT: devsecops-test-claim-auditor — PASS. CLAUSE MAP: 13 rows (C1a, C1b, C2a-C2d, D1, D2, N1-N5), all CARRIED.`
- Recommendations taken, as supporting assertions with no clause:
  - A delete without a key is refused and removes nothing.
  - A deleted profile's key is refused afterwards.
- Not taken:
  - Rotate and delete failure paths on every bad presentation: Phase 2's refusal is shared through `_require_profile`, which both routes call.
  - Zero-like profiles and double rotation: noted as bounds; `rotate_key` is a single `UPDATE`.

**Changes**

- `client/backend/lib/profiles.py` — `rotate_key` (a new key, `UPDATE key_hash`), `delete_profile` (likes, users, profiles in one transaction).
- `client/backend/server.py` — `POST /api/profile/rotate` → 200 `{key}`; `POST /api/profile/delete` → 204 with an empty body (sent through `respond_bytes`, since a 204 carries none); both behind `_require_profile`.
- `tests/run-arch-split-smoke.sh` — `request_json` sends `x-profile-key` when `PROFILE_KEY` is set; the like flow mints a profile first, sends the key on the like and the likes read, and deletes the profile after.
- `tests/run-installers-smoke.sh` — the same `request_json` change; the like flow mints a profile and uses its `profile_id` for the Engine event lookup and cleanup; `reset_client_test_profile` replaced by `delete_client_test_profile` (204).

**Checkpoint outcome** — PASS: `test_profile_lifecycle.py` 2 passed; with Phases 1-2, 8 passed.

**Coordination (after Phase 3)**

- Live services restarted: Engine and Client healthy, site 200. `users.db` was migrated by `ensure_user_schema` at start.
- `tests/run-arch-split-smoke.sh` on ports 7180/7280, run inside the Engine pixi env: **all 21 checks passed**, including `client_profile_mint` 201, `client_user_action` 200, `client_profile_likes` 200 with a non-empty likes array, `client_profile_delete` 204.
  - The first attempt could not start the Engine. The script resolves `python3` from `PATH`, which in the build shell is the root env without `numpy`, and that failure predates this build. Running it through `pixi run --manifest-path engine/pixi.toml` resolved it.
- **AC8, profile half:** the Engine's `interaction_raw_events` holds the smoke's like with `actor_id` = the minted `profile_id`, where every earlier row reads `local-user` (`tests/tmp/probe_actor_ids.py`). The arch smoke does not delete its event, so one test Like remains in the live Engine database, as before this build.
- `run-installers-smoke.sh` was not run: it installs services, and the operator did not ask for it.

#### Phase 4 — Frontend profile data module

- **Kind:** code
- **Files:** `client/frontend/src/data/profile.ts` (NEW), `client/frontend/src/data/user-profile.ts` (EDITED), `client/frontend/src/data/user-actions.ts` (EDITED), `client/frontend/src/pages/videos/index.ts` (EDITED), `client/frontend/index.html` (EDITED), `client/frontend/videos.html` (EDITED), `client/frontend/src/videos.css` (EDITED), `tests/tmp/test_profile_frontend.py` (NEW, checkpoint)
- **Intent (post-phase state):** After a visitor creates a profile in the browser, the frontend's profile requests carry the issued key, and after a rotation the key the browser holds is the one the server accepts.
- **Clauses:**
  - `C1` — After `createProfile`, `resetUserProfileLikes` clears the likes of the profile the server issued, and without a stored key it clears no profile's likes.
  - `C2` — After `rotateProfileKey`, the key `getProfileKey` returns is accepted by `GET /api/user-profile` and the previous one is not.
- **Checkpoint and seam:** rung 2. The test bundles `client/frontend/src/data/profile.ts`, `user-profile.ts` and `user-actions.ts` with the installed `esbuild` into `tmp_path`, and runs a node script against the common seam's real server. `localStorage` is shimmed with an in-memory store: it is the browser platform, which node lacks, not project code. `sendUserAction` sending the header is not asserted here. `/api/user-action` needs the Engine to resolve the video before the key matters, and standing in for the Engine would be a double for a module this project owns. It moves to the operator's browser check.

- **Scaffolding (7.1):** `client/frontend/src/data/profile.ts` with all six exports throwing `Error("not implemented")`. `useProfileKey` from the draft is named `storeProfileKey`, so it does not read as a React hook.
- **Probe (observed):** one run with a wrong implementation: `profile.ts` working except that `rotateProfileKey` does not store the new key, and `user-profile.ts` unchanged, so it sends no header.
  - Test 1 failed: `resetUserProfileLikes` was refused (`Error: Profile key required`), and the node step never replied (line 78, reached from 132).
  - Test 2 failed at line 151 (`now == created`).
- **Mishap:** the scaffolding backup ended up holding the probe instead, because the copy ran after the probe was written. The scaffolding was rewritten from its recorded text and confirmed red on `not implemented` in both tests. The probe file is kept as `delete_me/profile.ts.phase4-probe`.

**Self-check (dispatch 1)** — `tests/tmp/test_profile_frontend.py`

- `C1 — test_profile_frontend.py:135, the created profile's like count after resetUserProfileLikes — expected: 0 — under a reset that sends no header: the reset is refused and the step fails (observed); under a reset that swallows the refusal: 1.`
- `C1 — test_profile_frontend.py:141, a bystander profile's like count after a key-less browser resets — expected: 1 — under a reset that falls back to any server-side identity (the pre-build local-user fallback, or the last minted profile): 0.`
- `C2 — test_profile_frontend.py:152-155, GET /api/user-profile with the key getProfileKey returns after rotation, and with the previous key — expected: 200, 401 — under a rotate that does not store the new key: the held key is the retired one → 401 at line 153 (observed through line 151's supporting check).`

Supporting (no row): the esbuild bundle and node exit codes; line 131, one like present before the reset; line 150, `old == created`; line 151, the key changed.

1. **Whole claim** — both halves of C1, "clears the created profile's" and "without a key clears none", and both halves of C2, "new accepted" and "old refused".
2. **Absence only** — C1's bystander-kept assertion is armed by line 135: a reset that does nothing fails there.
3. **Echoed literal** — no. Keys and counts come from the server, and the key the browser holds comes from `getProfileKey` after the module ran.
4. **One value** — two browsers, one with a key and one without; old against new key.
5. **The double** — `window` and `localStorage` are minimal stand-ins for the browser platform, which node lacks. They are not project code. The modules under test are the real ones, bundled by the installed esbuild.
6. **It collects** — 2 node ids.
7. **Observed** — the probe run above.
8. **Red** — exit 1, 2 failed.
9. **Right reason** — both fail at the first node step with `Error: not implemented`, thrown by the scaffolding's `createProfile`. The harness itself works: the bundle builds, node runs, and the probe reached the clause assertions.
10. **Observed expected output** — yes.

**Checkpoint audit**

- Dispatch 1:
  - `AUDIT: devsecops-test-shape-auditor — PASS. Predicted failure: both tests fail at line 78 (no stdout line), with node's stderr naming "not implemented" from createProfile.`
  - `AUDIT: devsecops-test-claim-auditor — BLOCK: C1's "without a stored key it clears no profile's likes" was checked only on the bystander. The created profile had already been emptied, so a server that sends key-less resets to the latest profile passed.`
- **Frozen ledger:** UNCARRIED C1b2, D2, N2. Fixed: before the key-less reset, the created profile gets a like back (`v2`), and line 143 asserts it survives. This excludes a key-less reset that reaches the most recently created profile.
- Re-run: still red on `not implemented`.
- Dispatch 2:
  - `AUDIT: devsecops-test-claim-auditor — PASS. CLAUSE MAP: 14 rows, all CARRIED. Observations: reset with an invalid stored key untested; line 140 also requires a key-less reset to complete without throwing.`
  - `AUDIT: devsecops-test-shape-auditor — PASS. Predicted failure: line 78, from lines 128 and 149.`
- Recommendations from dispatch 1, not taken:
  - Failure paths of rotate and create in the module: the module rethrows the server's error, and the UI shows it.
  - Reset with a refused stored key: it surfaces the server's 401 as an error.

**Changes**

- `client/frontend/src/data/profile.ts` (NEW) — `getProfileKey`, `profileHeaders`, `storeProfileKey`, `createProfile`, `rotateProfileKey`, `deleteProfile`; the key is kept under `profileKey:v1`.
- `client/frontend/src/data/user-profile.ts` — `resetUserProfileLikes` returns `[]` without a server call when no key is stored, and otherwise sends `x-profile-key`.
- `client/frontend/src/data/user-actions.ts` — `sendUserAction` sends `x-profile-key` when a key is stored.
- `client/frontend/src/pages/videos/index.ts` — the `#show-profile-header` handler opens the modal. It falls back to no likes if resolving them fails, so the profile controls still show. `renderProfileSection` has three states:
  - issued key: shown once, read-only, with Copy and the only-copy warning;
  - held key: Rotate and Delete, each confirmed;
  - no key: Create, and paste a key, checked against the 43-character shape.

  All text is set through `textContent`.
- `client/frontend/index.html`, `client/frontend/videos.html` — a "Profile" button in `.header-nav`; the modal title is "Profile"; `#profile-section` sits above the likes.
- `client/frontend/src/videos.css` — `.nav-button`, `.profile-section`, `.profile-actions`, `.profile-key`, `.profile-warning`, `.profile-status`.
- `client/frontend/dist/` — rebuilt by `npm run build`, not rsynced.

**Checkpoint outcome** — PASS: `test_profile_frontend.py` 2 passed. All four phase checkpoints together: 10 passed.

`tsc --noEmit` reports 40 lines of errors, none in the new or edited data modules and none in the line ranges this phase added to `pages/videos/index.ts`. They are in older code (`cards`/`summaryCounts` possibly null, `VideoRow` field-name mismatches). The Vite build does not typecheck, and it succeeded.

#### Acceptance criteria without a clause

Recorded so the gap is visible and approved, not discovered later:

- **AC8** (anonymous path; `actor_id` is the `profile_id` or `"anonymous"`) — needs the Engine to resolve the video. Verified by both updated smoke scripts against the live stack, where `run-installers-smoke.sh` finds the Engine event by `profile_id`.
- **AC9** (`"local-user"` rows deleted) — verified at Step 8 by querying the live `users.db` after restart.
- **AC10's page wiring** (header button, modal section, key shown once, copy, delete clears the stored key, the like button sending the key so a like appears in the profile) — verified by the operator in a browser after `npm run build`.
- **AC11** (malformed reset body → 400) and **AC12** (CORS header, `DEPLOYMENT.md`) — verified at Step 8 by one request each against the live Client backend; the doc half at Step 9.

#### Coordination

- After Phase 3: restart services and run `tests/run-arch-split-smoke.sh` (and `tests/run-installers-smoke.sh` if the operator wants it; it installs services).
- After Phase 4: `npm run build` in `client/frontend`, rsync per `DEPLOYMENT.md` if the operator wants it live, and the operator's browser check of AC10's page wiring.

#### Rationale

Four phases, two clauses each, one Intent each. The split follows the boundary a visitor experiences: getting a profile (1), being refused without one (2), managing it (3), the browser holding it (4). Phases 1-3 share one server seam through a `tests/tmp/conftest.py` fixture, each with its own checkpoint file; Phase 4 enters through the frontend module against the same server. Five acceptance criteria carry no clause and are verified outside a checkpoint, as listed above.

## Inner unit tests

None. Each phase's checkpoint expressed its clauses at the seam.

## Close

### Refactor pass

None made. `_require_profile` already holds the one refusal every route shares. Left out:
- The two smoke scripts carry the same `request_json` change. That duplication predates this build: the scripts were already two copies of one helper.
- The installer smoke parses the mint response twice. Merging the two reads is cosmetic.

### Clause accounting

- `P1C1`, `P1C2` — carried: `test_profile_mint.py`, dispatch 2, both PASS.
- `P2C1`, `P2C2` — carried: `test_profile_refusal.py`, dispatch 2, both PASS (C2c and C2d fixed after the dispatch-1 BLOCK).
- `P3C1`, `P3C2` — carried: `test_profile_lifecycle.py`, dispatch 1, both PASS.
- `P4C1`, `P4C2` — carried: `test_profile_frontend.py`, dispatch 2, both PASS (C1b2 fixed after the dispatch-1 BLOCK).

### Clause-free criteria, checked live (`tests/tmp/probe_live_acs.py` against the Client on :7072)

- **AC8:**
  - Profile half: the arch smoke's like is stored under the minted `profile_id` in the Engine's `interaction_raw_events` (Phase 3 coordination).
  - Anonymous half (`actor_id = "anonymous"`): not exercised live; it is the `profile_id or "anonymous"` expression in `_handle_user_action`.
- **AC9:** 0 `local-user` rows in `users` and in `likes` after restart.
- **AC11:** a malformed reset body with a valid key → 400 `Invalid JSON body`.
- **AC12:** the preflight answers `access-control-allow-headers: content-type, x-profile-key`.
- The probe minted one profile on the live service and deleted it (204).
- **AC10's page wiring** — pending the operator's browser check; `dist/` rebuilt, not rsynced.

### Suite

`validate_tests.py --compare`: `test_db.py` 2 passed, "nothing moved against the previous record". All four phase checkpoints together: 10 passed.

### Documentation (Step 9)

- `client/README.md` — update: route list gains `/api/profile`, rotate, delete; the `X-Profile-Key` requirement, 401 and hash storage are stated; `/api/user-action`'s profile-only server-side like.
- `README.md` — update: the arch-smoke description gains the mint (201) and delete (204) checks, and says the key is sent on the like and the read.
- `DEPLOYMENT.md` — update:
  - §5 describes profiles, the header-only key, no recovery, and the mint limit being shared by the whole deployment behind nginx until the real client address is resolved.
  - §6 TLS names the `X-Profile-Key` header.
  - The rebuild-and-rsync step was already documented in §3/§6; no change there.
- ADRs: `docs/project/adr/` does not exist. `docs/wiki/` does not exist.
- **Found, not caused by this build:** DEPLOYMENT §8B says the arch smoke's ports are "unrelated to the 7070/7072 pair used in production". The smoke's default Engine port is 7072, which is the live Client's port. Reported to the operator, not changed.
