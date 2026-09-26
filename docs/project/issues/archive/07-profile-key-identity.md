# Issue and verify an opaque profile key for per-visitor identity

Status: bug, complete
Origin: task 82, SI3-M1 — security audit run 1, finding F7

## Problem

`resolve_user_id` (`client/backend/lib/http_utils.py`) returns whatever string the caller supplies and falls back to `"local-user"`, so `GET /api/user-profile`, `GET /api/user-profile/likes` and `POST /api/user-profile/reset` let any visitor read or wipe the shared profile. There is no per-visitor identity at all, which also blocks the like/dislike feature: an Engine-side filter profile built on this would apply one visitor's blocks to everyone (`docs/project/plans/03-like-dislike.md`, R10).

## Proposed solution

An opaque, server-generated profile key presented in a request header, per the like/dislike plan's O7. This supersedes the earlier signed-cookie proposal: a key is portable across devices, carries no CSRF surface and needs no cookie-consent machinery, at the accepted cost of being readable by any script on the page.

1. Add a `profiles` table to the Client users database in `client/backend/lib/users_store.py`: `profile_id` (opaque public id), `key_hash`, `created_at`, `last_seen_at`. Store no plaintext key.
2. Generate keys with `secrets.token_urlsafe(32)` and hash with `hashlib.sha256` before storage; return the plaintext exactly once, at creation.
3. Add `POST /api/profile` to `client/backend/server.py` to mint a profile, returning `profile_id` and the one-time key.
4. Rate-limit that route with the existing `RateLimiter` in `client/backend/lib/http_utils.py`, on a tighter budget than the read routes: it creates durable rows on an unauthenticated call.
5. Add `resolve_profile(handler)` reading the key from an `X-Profile-Key` header only — never a query parameter or body, so it stays out of access logs, `Referer` and browser history — and resolving it to a `profile_id` by hash comparison with `hmac.compare_digest`.
6. Replace all `resolve_user_id` call sites in `client/backend/server.py` with the resolved profile identity; delete the `"local-user"` fallback.
7. Keep profiles optional: a request with no key stays anonymous and unfiltered, exactly as today, and the profile routes answer 401 rather than acting on a shared row.
8. Return an identical rejection for an absent, malformed and unknown key, so the response does not reveal whether a profile exists.
9. Store the key in the frontend alongside `localLikes:v1`, send it on profile requests, and show it once at creation as copyable text stating plainly that it is the only copy.
10. Fix `_handle_user_profile_reset` in `client/backend/server.py` to call `read_json_body` inside a `try`, matching its sibling handlers.
11. Add the header to the gateway's allowed request headers and to `DEPLOYMENT.md`; note that any deployment reachable beyond localhost must serve it over TLS only.
12. Verify: two browsers with different keys see different profiles; the same key in a second browser restores the first profile; no key behaves as today; `tests/run-arch-split-smoke.sh` still passes.

## Related

- Open decision O8 in the like/dislike plan (key rotation, revocation, recovery) is unresolved and should be settled before this is built.
- Hard prerequisite for the Engine-side profile items of `docs/project/plans/03-like-dislike.md` (I5, I6, I7).
- Land before `03-batch-like-resolution`.

## Comments

- 2026-09-26 — Delivered by `docs/project/plans/archive/06-profile-key-identity.md`.
  - O8 settled: rotate and delete, no recovery.
  - The proposal's steps landed as written, with three changes:
    - the profile controls sit behind a "Profile" button in the page header, because the likes modal was unreachable;
    - the paste function is `storeProfileKey`;
    - a key is looked up by its SHA-256 rather than compared with `hmac.compare_digest`.
  - Durable tests: `tests/active/test_profiles.py`, `tests/active/test_frontend_profile.py`.
  - The operator's browser check of the page wiring is still open. `dist/` is built but not rsynced.
