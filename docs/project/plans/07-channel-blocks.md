# Block a channel or account

Parent: `docs/project/plans/03-like-dislike.md` (S7; the block part of S8, I5, I6, I7, I8). Dislikes are the second build from plan 03.
Depends on: `docs/project/plans/archive/06-profile-key-identity.md` (delivered).

## Requirements

Confirmed by the operator at Step 1.

### What was asked

"lets build the dislike and block features now." Split at Step 1 into two builds; this one is blocks.

### Purpose

A visitor with a profile can remove a channel or an account from their own feeds and search results for good, without affecting any other visitor. It is the hard control beside dislike's soft one (plan 03 O2).

### Current state (read at Step 1)

- Identity exists: `client/backend/lib/profiles.py` resolves `X-Profile-Key` to a `profile_id` held in `client/backend/db/users.db`; `ClientBackendHandler._require_profile` (`client/backend/server.py:282`) sends the single 401.
- Feed and search requests reach the Engine only through the Client's read proxy (`PROXY_READ_GET_ROUTES`, `PROXY_READ_POST_ROUTES`, `client/backend/server.py:50-74`). The frontend sends no profile key on them today.
- The Engine holds no user state; `DEPLOYMENT.md:258` states the boundary as mandatory and `tests/run-arch-split-smoke.sh` enforces it.
- The Engine's operator moderation (`engine/server/data/moderation.py`, `serving_moderation.py`) filters rows after selection. This feature does not touch it.
- `whitelist.db`, measured with `tests/tmp/probe_account_identity.py`: 890,052 videos, every one with a `channel_id` and an `account_url`; 45,807 channels, 36,651 accounts, 4,067 of those accounts own more than one channel. There is no account id column, so an account is identified by its `account_url`.

### Decisions (Step 1)

- **Storage.** Blocks are stored by the Client backend in `users.db`, keyed by `profile_id`. Plan 03 O4 (an Engine-side profile database) is superseded.
- **Where the filter runs.** The Client filters the Engine's response before returning it to the browser. Nothing about blocks is sent to the Engine, and the Engine does not change. To keep pages full, the Client over-fetches from the Engine when the visitor has any blocks, filters, and truncates to the requested limit.
- **A profile is required.** Blocks exist only for a profile.
- **Bad key on a feed (Q6, O1).** A feed or search request carrying a key that does not resolve gets the same 401 as the profile routes. The frontend then says the key is no longer valid and offers to forget it.
- **Search is filtered (Q7).**
- **Controls on video cards and on the channels page (Q8)** are deferred to a follow-up feature, listed in `docs/project/roadmap.md`.

### Acceptance criteria

- **B1.** The Client has profile routes to list, add and remove blocks. A channel block is keyed by `instance_domain` + `channel_id`; an account block by `account_url`. The routes take the key only from `X-Profile-Key` and answer an absent, malformed or unknown key with the same 401 as the existing profile routes.
- **B2.** Once a channel is blocked, its videos are absent from the home, random and up-next feeds (`/recommendations`, `/videos/similar`) and from search (`/api/v1/search/videos`), immediately and on later visits, until it is unblocked.
- **B3.** Blocking an account removes the videos of every channel it owns, on the same routes as B2.
- **B4.** A filtered response is a full page unless more than half of the over-fetched rows are blocked; in that case it returns what remains and does not refill.
- **B5.** The browser adds only the `X-Profile-Key` header to a feed or search request. Its request size does not depend on the number of blocks.
- **B6.** Blocks live in `users.db`, which no dataset build or updater touches.
- **B7.** One visitor's blocks never change another visitor's feed or search results.
- **B8.** Without a key, feeds and search behave exactly as today. The block controls prompt the visitor to create a profile.
- **B9.** A feed or search request carrying a key that does not resolve gets the same 401 as the profile routes, and the frontend offers to forget the key.
- **B10.** Deleting a profile deletes its blocks.
- **B11.** The video page offers "Block channel" and "Block account". The profile modal lists the profile's blocks, each with an unblock control.
- **B12.** Blocks are independent of dislikes. Nothing in this build blocks a channel implicitly.

### In scope

`client/backend/server.py`, `client/backend/lib/users_store.py`, `client/backend/lib/profiles.py` (profile deletion), a new block-store module under `client/backend/lib/`, the frontend feed and search data modules, `client/frontend/src/data/profile.ts`, the video page, the profile modal in `index.html` and `videos.html`, `DEPLOYMENT.md`.

### Out of scope

- Dislikes and any change to the like buttons (plan 03's second build).
- Block controls on video cards and on the channels page (follow-up feature).
- Any Engine change, including its operator moderation.
- Issue 02 (resolving the real client address behind nginx).
- Filtering `/api/video` (a single video page stays reachable, which is where a block is undone from).

### Consistency constraints

Backend matches `client/backend` style: stdlib `http.server`, `respond_json`, `sqlite3.Row`, module docstrings, `from __future__ import annotations`. Frontend matches `data/*.ts` (fetch through `resolveClientApiBase`, `readErrorMessage`) and the existing modal and `ghost-button` markup; every rendered value is escaped. Backwards compatibility is not required.

### Conflicts

- **Plan 03 O4 vs this build.** O4 put the filter profile in the Engine. Resolved by the operator: Client storage, Client-side filtering. Plan 03 records the supersession.
- **Plan 03 criterion 15 vs B4.** Criterion 15 asked for exclusion from the candidate pool so a page is always full. Resolved by the operator: B4's over-fetch, with a short page accepted when more than half the over-fetched rows are blocked.

### Test trees for this build

- `active`: `tests/active`
- `working`: `tests/tmp`

### Baseline suite state

Step 0, `scripts/validate_tests.py` bare run: "unchanged since 2026-09-26T07:48:44-04:00 — every fingerprint still holds", 12 passed. Reused from the banked record. Green.

## High-level plan

_Filled at Step 2._

## Impacts

_Filled at Step 3._

### Highest risk

### Reassessment

### Documentation to update

## Implementation plan

_Filled at Steps 5-6._

### Phases

## Inner unit tests

## Close
