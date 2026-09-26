# Like/dislike functionality (add/remove)

Status: planned, not approved. Requirements and High-level plan migrated from the retired `dev/FEATURE_PLANS.md` (feature `F12-M2`, milestone M2); a build re-confirms them at dev_flow Steps 1 and 2. Open decision O3 is unresolved; O8 was settled by plan 06 (rotate and delete, no recovery).

**Split, decided by the operator at the blocks build's Step 1:**
- Blocks (S7, and S8 as far as blocks need it; I6, I7, and the block part of I5 and I8) were built first and are delivered: `docs/project/plans/archive/07-channel-blocks.md`.
- Dislikes (S5, S6; I3, I4, and the dislike part of I5 and I8) are a second build from this file.
- **O4 is superseded.** Blocks and dislikes are stored by the Client backend in `users.db`, keyed by `profile_id`. The Client reads them and passes them to the Engine over the internal hop when it proxies a feed request. The Engine stays free of user state. The browser's request stays a constant size (criterion 16). The Client-to-Engine request grows with the number of entries.
- Blocks and dislikes require a profile. Without a key, the controls prompt the visitor to create one (criterion 19).
- **A dislike also removes a like** on the same video (criterion 7). The dislike build therefore owns the un-like path, and it must settle issue 01 and issue 15 before it starts.

## Requirements

### What was asked

Liking works end to end today — the POST reaches the Engine and the video is stored in `localLikes:v1` and in the server-side profile — but the UI gives almost no feedback, so a successful like is indistinguishable from a dead button. Observed directly: a like was registered and visible in the profile while the user believed nothing had happened. Dislike is wanted as a real negative signal, and blocking a channel or account as a separate hard control.

### Purpose

Make the like state honest and visible, and give the visitor two ways to shape their own feed: a soft one (dislike down-ranks similar videos) and a hard one (block excludes a channel or account), without affecting any other visitor.

### Current behaviour (measured, not assumed)

- **Click like** — `video-page/index.ts:62-70`, `:1009-1041`: adds `active` class, POSTs `/api/user-action`, stores in `localLikes:v1`.
- **Visual feedback** — `video.css` `.ghost-button.active`: faint background tint and border colour only.
- **Like count** — shows the source instance's count; never reflects a local like.
- **After reload** — button renders un-highlighted even though the like persists.
- **Request failure** — `:1031-1038`: logged to `console.warn`; the local like is added anyway in `finally`.
- **Click an active like** — `toggleReaction` removes the highlight, sends nothing, leaves the stored like.
- **Dislike** — `:69` toggles a class only. No storage, no API, no ranking effect.

Line numbers are from planning time and must be re-checked.

### Scope

- **S1 Persisted visual state.** On page load, read `localLikes:v1` and render the like button as active when the current video is present, so state survives a reload.
- **S2 A real indicator.** Replace the faint tint with an unambiguous active state (filled icon and/or label change), plus an in-flight state while the POST is outstanding.
- **S3 Honest failure.** Stop adding the local like unconditionally in `finally`. A failed request leaves the button un-liked and surfaces the failure to the user, not only the console.
- **S4 Un-like.** Clicking an active like removes the stored like and emits the corresponding `UndoLike` event, so the button and the store cannot disagree.
- **S5 Dislike as a negative signal.** A dislike is the inverse of a like: it makes similar videos less likely to appear. Same treatment as a like — persisted store, visible state, un-dislike — plus Engine support in S6.
- **S6 Reverse-match down-ranking.** The feed down-ranks videos similar to disliked ones — a score penalty proportional to similarity, not a removal. Applied on the random feed and on by default on the home feed. The disliked video itself is excluded outright; its neighbours are only penalised.
- **S7 Block channel or account.** Blocking a channel or an account excludes every video from it, unconditionally, until unblocked. Identity-based (`instance_domain` + `channel_id`, or account), not similarity-based. Distinct from the Engine's operator moderation (`data/moderation.py`), which this feature does not touch.
- **S8 Engine-side filter profile.** Dislikes and blocks are stored by the Engine in a per-visitor filter profile and applied server-side. The browser sends a profile reference, not the lists, so request size stays constant. Blocks are enforced by an anti-join against the profile table, not a per-request `IN (...)` list.

### Out of scope

- Building per-visitor identity itself: that is `docs/project/issues/archive/07-profile-key-identity.md`, which this feature consumes and cannot ship before (R10).
- Sending likes to the source PeerTube instance (ActivityPub delivery, roadmap `F4-M5`).
- Changing how likes influence ranking: `docs/project/issues/01-deterministic-event-ids.md` caps `signal_score` separately.

### Acceptance criteria

1. Liking a video shows an unmistakable active state, distinguishable at a glance from the inactive state.
2. Reloading the video page preserves the active state for a previously liked video.
3. A like whose request fails leaves the button inactive and shows the user an error; the video does not appear in `localLikes:v1`.
4. Clicking an active like removes the video from `localLikes:v1` and the button returns to inactive.
5. The profile view and the like button never disagree about whether a video is liked.
6. The source instance's like count is never presented as if it included the local like.
7. Disliking a video shows an unmistakable active state, persists across reload, and is mutually exclusive with like on the same video.
8. After disliking a video, videos similar to it appear measurably lower in the home feed without further action; the disliked video itself does not appear at all.
9. The random feed exposes dislike down-ranking as an option.
10. With many dislikes recorded, the feed still returns a full page — down-ranking reorders, it does not empty.
11. A dislike changes nothing for any other visitor: no global ranking signal is emitted.
12. Blocking a channel removes every video from that channel from every feed, immediately and on later visits, until unblocked.
13. Blocking an account behaves the same across all of that account's channels.
14. Blocks and dislikes are independent: blocking does not require disliking, and a disliked video's channel is not blocked implicitly.
15. A blocked channel's videos are absent from the candidate pool, not hidden after selection, so the feed still returns a full page.
16. Feed request size is constant regardless of how many channels are blocked.
17. Blocks and dislikes survive a full dataset rebuild, including an updater staging merge.
18. One visitor's blocks and dislikes have no effect on another visitor's feed.
19. With no profile, the app behaves exactly as today: anonymous, unfiltered, no key required.
20. A profile key presented from a second browser restores the same blocks and dislikes.
21. An absent, malformed or unknown profile key is rejected without revealing whether the profile exists.
22. The profile database stores no plaintext key.

### Consistency constraints

- `localLikes:v1` is shared with the videos page profile view and the recommendation request payload; any change to its shape affects both. Every mutation stays in `data/local-likes.ts` (R1).
- New request parameters travel through the Client gateway allowlist; the frontend never calls the Engine directly.

### Conflicts

- **Issue 15 (remove a single like)** covers S4. Either it is absorbed here or S4 defers to it. Unresolved.
- **R4 — track.** The old tracker recorded this as a Client-track feature, but S6-S8 change the Engine. Unresolved.
- **R9 — Client/Engine boundary.** The Engine holds no user state today, enforced by `tests/run-arch-split-smoke.sh` (fails if the Engine has `users.db` open) and stated as mandatory in `DEPLOYMENT.md`. S8 gives the Engine per-visitor state. The contract wording and boundary docs must be amended deliberately, not quietly contradicted.

### Test trees for this build

_Filled at build Step 0._

### Baseline suite state

_Filled at build Step 0._

## High-level plan

### Approach

Client-only correctness first (S1-S4), then the dislike store and controls, then the Engine-side profile store, down-ranking, blocks, and feed wiring. The draft decomposition from planning, in dependency order:

- **I1 Like state rendering and persistence** — read `localLikes:v1` on load; render active state; in-flight state.
- **I2 Like action correctness** — remove the unconditional `finally` store; surface failures; un-like path including `UndoLike`.
- **I3 Dislike store and controls** — `localDislikes:v1`; dislike/un-dislike with the same state rules as like; mutually exclusive with like.
- **I5 Engine filter-profile store** — a dedicated profile database, separate from `users.db` and `whitelist.db`; profile id plus hashed key; dislikes and blocks keyed by profile; survives dataset rebuild and updater merge; rate-limited creation.
- **I4 Reverse-match down-ranking in the Engine** — dislikes in the recommendation request with a cap; vector search from disliked videos; similarity-scaled penalty; disliked videos excluded.
- **I6 Block controls and profile API** — block/unblock on the video page, cards and channels page; a manage-blocks view; read/write endpoints through the gateway.
- **I7 Block enforcement in the Engine** — anti-join against the profile block table by `instance_domain`+`channel_id` and by account, before scoring.
- **I8 Home and random feed wiring** — down-ranking on by default on home, optional on random; blocks always applied; gateway allowlist entries for the profile reference.

Eight items exceed the four phases one build allows; expect to split this into more than one plan file before building, most naturally client-side (I1-I3) and Engine profile (I4-I8).

Order constraints: I1 and I2 need no identity and no Engine change, so they can land as soon as issue 01 has (it changes how repeated likes deduplicate, which I2's un-like must match). I5 creates the store every later item reads, and requires issue 07. I4's calibration needs the rebuilt multilingual index (done).

### Resolved decisions

- **O1 — dislike is a negative signal**, specifically reverse matching, not a cosmetic control or hide-this-video.
- **O2 — dislike down-ranks, block excludes.** The feed degrades gracefully under dislikes; hard exclusion comes only from an explicit block.
- **O4 — transport: Engine-side filter profile, no per-request lists.** Consequences accepted: no cap on blocks (anti-join cost is flat); a dislike cap remains because each dislike costs one vector search per feed request (R6); filters follow the visitor across devices once identity exists; the Engine gains per-visitor state (R9), stored in a dedicated database file, not `users.db` and not `whitelist.db` (R8).
- **O5 — no global `Dislike` event.** Dislikes never move `interaction_signals.signal_score`; that would let an anonymous caller push videos down for everyone (audit finding F5 in mirror image).
- **O7 — profile identity is an opaque profile key, API-key style.** Profiles are optional. The key is generated server-side from a CSPRNG, stored as a hash, presented in a header, creation is rate-limited, and it travels only over TLS beyond localhost. Accepted tradeoff: a key in `localStorage` is readable by any script on the page; the XSS sinks were closed and a CSP added, which reduces but does not eliminate that. Implemented by issue 07.

### Open decisions

- **O3 — penalty magnitude.** Starting point: symmetric with a like (same magnitude, reversed sign, scaled by similarity). To be confirmed by calibration against the rebuilt index. Blocks Phase I4.
- **O8 — key lifecycle.** Rotation, revocation and recovery are undecided. A lost key is a lost profile. At minimum the UI shows the key, makes it copyable, and says it is the only copy. Blocks issue 07.

### Risks

- **R1 — Store/UI drift.** Button, profile view and recommendation payload read the same store; keep every mutation in `data/local-likes.ts`.
- **R2 — Count confusion.** A local like next to a remote count reads as if it incremented it. Criterion 6.
- **R3 — Duplicate work with issue 15.** See Conflicts.
- **R4 — Track mismatch.** See Conflicts.
- **R5 — Pool starvation from blocks.** Blocks can empty the feed; criterion 15 requires exclusion before scoring so the pool refills.
- **R6 — Cost per request.** One extra vector search per disliked video per feed request, under the same locks as everything else. The dislike cap is a performance control.
- **R7 — Two filters, one surface.** Dislike and block need visibly different controls and wording.
- **R8 — Dataset rebuilds must not destroy profiles.** `whitelist.db` is rebuilt from the crawl and merged over by the updater; profiles live in their own file no dataset job touches.
- **R9 — Client/Engine boundary change.** See Conflicts.
- **R10 — Hard dependency on identity.** Without issue 07, an Engine-side profile is the shared `local-user` row.
- **R11 — Key loss is profile loss.** No recovery path.
- **R12 — Profile creation as a growth vector.** Rate limiting is functional, not hardening.

### Validation strategy (from planning)

- Manual: like, reload, state persists; un-like, reload, gone; stop the Client backend and a failed like does not appear liked.
- Console: `JSON.parse(localStorage.getItem('localLikes:v1'))` agrees with the button after every operation.
- `tests/run-arch-split-smoke.sh` still passes.

### Rollback notes (from planning)

The client-only issues (I1-I3) revert with the bundle and a redeploy `rsync`, with no stored-data format change. The Engine-side issues add a new database file and are not covered by that statement; a build must state their rollback.

## Impacts

_Filled at build Step 3._

### Highest risk

### Reassessment

### Documentation to update

## Implementation plan

_Filled at build Steps 5-6._

### Phases

## Inner unit tests

## Close
