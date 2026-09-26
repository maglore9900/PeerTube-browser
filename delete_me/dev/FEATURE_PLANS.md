# Feature Plans

Approval-gated plans produced by `plan feature <id>`.
`dev/map/DEV_MAP.json` remains the source of truth for feature status.
A plan here is not approved until `approve feature plan` sets the feature `status` to
`Approved` in `dev/map/DEV_MAP.json`.

---

## Implementation order

Dependency order across the planned features and the open security tasks. Existing IDs
are used as-is; nothing is renumbered. Items in the same phase are independent of each
other and may run in any order or in parallel. A later phase may not start before the
constraint named under it is satisfied.

### Phase 0 — Dataset migration (in progress)

Tags/comments enrichment crawl -> `sync-whitelist.py` -> re-embed with `--force` on the
multilingual model chosen in `F6-M3` O2 -> ANN index -> similarity cache
(`--recreate-out-db`) -> random cache -> Engine restart.

No re-crawl is required to change the model. `build-video-embeddings.py:176-208` reads
`title`, `description`, `tags_json`, `category`, `channel_name` and `comments_count` from
`whitelist.db`, which `sync-whitelist.py` fills from `crawl.db`; the crawl output is not
consumed by embedding. A model change resumes at
`run-dataset-build.sh --from embeddings`.

**Why first:** every relevance decision downstream is calibrated against the index.
`F12-M2` O3 (dislike penalty magnitude) and any search-quality tuning are meaningless
against vectors that are about to be replaced. The model is now also a **correctness**
precondition, not only a calibration one: `F6-M3` cross-language retrieval does not exist
in an English-only space, whatever the endpoint does.

### Phase 1 — Security remainder, identity-independent

Tasks **80**, **81**, **83**, then **84**, **85**, **86**.

**Why here:** none of them depend on the features below, and all of them are already
decomposed and synced. **80** must precede `F12-M2` I2 because it changes how repeated
likes deduplicate, which that issue's un-like path has to match.

### Phase 2 — Identity

Rewrite task **82** to issue and verify a profile key per `F12-M2` O7, then implement it.

**Constraint:** `F12-M2` R10 — every Engine-side profile item below is blocked on this.
Without it a profile is the shared `local-user` row and one visitor's filters apply to
everyone. Task 82's current text (signed httpOnly cookie, or removal) is superseded and
must be rewritten before it is executed.

### Phase 3 — Like correctness, client-only

`F12-M2` **I1** and **I2**. Resolve the task **9b** overlap first: either absorb 9b into
this feature or defer I2's un-like half to it.

**Why here:** these need no identity and no Engine change, so they can land as soon as
Phase 1's task 80 has. May run in parallel with Phase 4.

### Phase 4 — Search (parallel track)

`F6-M3` (planned, hybrid BM25 + vector) -> approve -> search page (`F10-M2`, existing
task **10**).

**Why parallel:** depends only on Phase 0's index, not on profiles or filters. The FTS5
index must be built in the same pass as embeddings so the two stay in sync; adding that
stage after Phase 5 would mean rebuilding twice.

**Scope widened at re-plan time (supersedes the earlier BM25-only narrowing):** the
vector half is back, because cross-language retrieval is now a requirement and BM25
cannot deliver it — a Russian title shares no tokens with an English query. The original
objection was that the serving process has no encoder and would need `torch`; that was
measured and is wrong, the Engine environment already ships `torch` and
`sentence_transformers`. See `F6-M3` O1. Translation, captions and full descriptions
remain each their own later feature: a multilingual *encoder* makes foreign content
findable, not readable.

### Phase 5 — Filter profile and its consumers

In strict order: `F12-M2` **I5** (profile store) -> **I3** (dislike controls) and
**I4** (down-ranking) -> **I6** (block controls) and **I7** (block enforcement) ->
**I8** (feed wiring).

**Constraint:** I5 creates the profile store every later item reads. I4's calibration
needs Phase 0 complete. Requires Phase 2.

### Phase 6 — Language

`F4-M4` **I1** (schema + crawler capture) and **I2** (serving and filtering), then
**I3** (backfill) whenever convenient.

**Constraint:** I1's schema change must land in `engine/crawler/schema.sql` and
`ensure_content_schema` together or the sync gate fails. Capture only affects newly
crawled rows, so landing this *before* a crawl avoids a second full re-crawl — if
another enrichment pass is planned, fold I1 into it.

### Phase 7 — Saved channels

`F4-M4` **I4** and **I5**.

**Constraint:** saved channels are a positive per-visitor channel list and blocks are a
negative one. They must share the Phase 5 profile store rather than inventing a second
mechanism, so this follows `F12-M2` I5.

### Phase 8 — Feed paging

`F4-M4` **I6**.

**Constraint:** paging needs stable ordering or a seed, and dislike down-ranking changes
the ordering it pages through. Landing paging after `F12-M2` I4 avoids designing the
seed twice.

### Phase 9 — Feed parameter panel

`F4-M4` **I7**.

**Why last:** the panel is the single surface binding language, saved channels, dislike
down-ranking and paging. Building it before its inputs exist means rebuilding it as each
one arrives.

### Unsequenced

- Task **4** (read-only comments) depends only on the comments enrichment in Phase 0 and
  may land at any point after it.
- Open decisions block their own phase, not the sequence: `F12-M2` O8 (key lifecycle)
  before Phase 2, `F12-M2` O3 (penalty magnitude, calibration) before Phase 5, `F4-M4`
  O1-O3 before Phase 6.
- Structural items to settle before `approve feature plan` on `F12-M2`: R4 (the feature
  is recorded as `track: "Client"` but Phases 5 and 7 change the Engine) and R9 (the
  Client/Engine boundary contract and its documentation must be amended deliberately).

---

## F12-M2 — Implement like/dislike functionality (add/remove)

- **feature_id:** `F12-M2`
- **feature_title:** Implement like/dislike functionality (add/remove).
- **milestone_id:** `M2` (Video-ID indexing and UI rewrite foundations)
- **status:** `Planned` (not approved)
- **track:** `Client`

Liking works end to end today — the POST reaches the Engine and the video is stored in
`localLikes:v1` and in the server-side profile — but the UI gives almost no feedback, so
a successful like is indistinguishable from a dead button. Observed directly: a like was
registered and visible in the profile while the user believed nothing had happened.

### Current behaviour (measured, not assumed)

| Behaviour | Where | Today |
|---|---|---|
| Click like | `video-page/index.ts:62-70`, `:1009-1041` | Adds `active` class, POSTs `/api/user-action`, stores in `localLikes:v1` |
| Visual feedback | `video.css` `.ghost-button.active` | Faint background tint and border colour only |
| Like count | `video-page/index.ts` | Shows the **source instance's** count; never reflects a local like |
| After reload | — | Button renders un-highlighted even though the like persists |
| Request failure | `:1031-1038` | Logged to `console.warn`; the local like is added anyway in `finally` |
| Click an active like | `toggleReaction` | Removes the highlight, sends nothing, leaves the stored like |
| Dislike | `:69` | Toggles a class only. No storage, no API, no ranking effect |

### Scope

- **S1 Persisted visual state.** On page load, read `localLikes:v1` and render the like
  button as active when the current video is present, so state survives a reload.
- **S2 A real indicator.** Replace the faint tint with an unambiguous active state
  (filled icon and/or label change), plus an in-flight state while the POST is
  outstanding.
- **S3 Honest failure.** Stop adding the local like unconditionally in `finally`. A
  failed request must leave the button un-liked and surface the failure to the user
  rather than only to the console.
- **S4 Un-like.** Clicking an active like removes the stored like and emits the
  corresponding `UndoLike` event, so the button and the store cannot disagree.
- **S5 Dislike as a negative signal.** A dislike is the inverse of a like: where a like
  makes similar videos *more* likely to appear, a dislike makes them *less* likely. It
  needs the same treatment as a like — persisted store, visible state, un-dislike — plus
  Engine support described in S6.
- **S6 Reverse-match down-ranking.** The feed *down-ranks* videos similar to disliked
  ones — a score penalty proportional to similarity, not a removal. Applied on the random
  feed and **on by default on the home feed**. The disliked video itself is excluded
  outright; its neighbours are only penalised.
- **S7 Block channel or account.** A separate, harder control: blocking a channel or an
  account excludes **every** video from it, unconditionally and permanently, until
  unblocked. Identity-based (`instance_domain` + `channel_id`, or account), not
  similarity-based, so it is exact and cheap. Distinct from the Engine's existing global
  moderation (`data/moderation.py`, instance denylist and channel blocklist), which is an
  operator control and is not touched by this feature.
- **S8 Engine-side filter profile.** Dislikes and blocks are stored by the Engine in a
  per-visitor filter profile and applied server-side. The browser sends a profile
  reference, not the lists, so request size stays constant no matter how much is
  blocked. Blocks are enforced by an **anti-join against the profile table**, not an
  `IN (...)` list built per request — which is what makes an unbounded block list
  practical.

### Resolved decisions

- **O1 — dislike: implemented as a negative signal.** Initially removed during planning,
  then reversed: dislike is wanted, and specifically as reverse matching rather than a
  cosmetic control or a simple hide-this-video.
- **O2 — dislike down-ranks, block excludes.** Dislike applies a score penalty to
  similar videos, so the feed degrades gracefully instead of collapsing. Hard exclusion
  is provided separately and explicitly by S7's channel/account block, where the user
  has stated the intent directly rather than having it inferred from a similarity score.

### Open decisions

- **O8 — key lifecycle.** Rotation, revocation and recovery are undecided. A lost key
  means a lost profile, since there is no email or account to recover from. At minimum
  the UI must show the key and make it copyable, and say plainly that it is the only
  copy.
- **O3 — penalty magnitude: symmetric with a like.** A dislike applies a penalty of the
  same magnitude a like applies as a boost, with the sign reversed, scaled by similarity
  to the disliked video. This is the starting point, to be confirmed by calibration
  against the rebuilt index rather than assumed correct.
- **O4 — transport: Engine-side filter profile, no per-request lists.** The browser
  sends a profile reference; the Engine reads the visitor's dislikes and blocks from its
  own store. Consequences accepted deliberately:
  - **no cap on blocks.** Because enforcement is an anti-join against a table rather
    than a query term per entry, 10 blocks and 10,000 cost the same. The cap existed
    only to bound a caller-supplied list in a request body (audit finding F11's shape),
    and that list no longer exists. A dislike cap remains, because each dislike still
    costs one vector search per feed request (R6);
  - filters follow the visitor across devices once identity exists, unlike likes today;
  - the Engine gains per-visitor state, which changes the Client/Engine contract — see
    R9. Storage must be a dedicated database file, **not** `users.db` and **not**
    `whitelist.db` — see R8.
- **O7 — profile identity: an opaque profile key, API-key style.** Profiles are
  **optional**: with no profile the app behaves as it does today, anonymous and
  unfiltered. Creating one returns a key that the browser stores locally and presents on
  each request to authenticate the profile. Required properties:
  - generated **server-side** from a CSPRNG, never derived in the browser;
  - stored by the Engine as a **hash**, never in plaintext, exactly as an API key would
    be, so a leaked profile database does not yield working keys;
  - presented in a header, not a query parameter, so it does not land in access logs,
    `Referer` headers or browser history;
  - profile creation is **rate-limited** — an unauthenticated endpoint that mints a
    database row on demand is unbounded growth by another name, the same class as audit
    finding F5;
  - transmitted only over TLS in any deployment reachable beyond localhost.

  **Accepted tradeoff:** a key in `localStorage` is readable by any script that runs on
  the page, where an httpOnly cookie is not — this is the exposure audit finding F1
  demonstrated against `localLikes:v1`. Tasks 69-73 closed those sinks and added a CSP,
  which reduces but does not structurally eliminate it. Accepted in exchange for
  portability across devices, no CSRF surface, and no cookie-consent machinery.

  **This supersedes security task 82's current text**, which proposes a signed httpOnly
  cookie or removing the profile endpoints. Task 82 must be rewritten to issue and
  verify a profile key instead; it remains a hard prerequisite (R10).
- **O5 — no global `Dislike` event.** Agreed during planning. A `Dislike` event type
  would let dislikes move `interaction_signals.signal_score`, letting an anonymous
  caller push videos *down* for every visitor — audit finding F5 in mirror image on a
  service with no accounts. Dislikes stay local to the requesting client, purely a
  filter input. No new event type is added to the Engine.

### Out of scope

- Building per-visitor identity itself. Security task 82 delivers the signed-cookie
  identity; this feature consumes it and cannot ship before it (R10).
- Sending likes to the source PeerTube instance. That is ActivityPub delivery (`F4-M5`).
- Changing how likes influence ranking. Task 80 caps `signal_score` influence separately.

### Dependencies and overlaps

- **Task 9b** `[M2][F1]` "Remove a single like (UI + API)" already covers single-like
  removal. S4 overlaps it directly. Either 9b is absorbed into this feature or S4 defers
  to it — shipping both produces two implementations of the same button.
- **Task 80** (SI3-M1, deterministic `event_id`) changes how repeated likes of the same
  video are deduplicated. S4's `UndoLike` emission should land after it, or be written to
  match the deterministic key.
- `localLikes:v1` is shared with the videos page profile view and the recommendation
  request payload; any change to its shape affects both.

### Draft decomposition

| Issue | Title | Indicative tasks |
|---|---|---|
| I1-F12-M2 | Like state rendering and persistence | read `localLikes:v1` on load; render active state; in-flight state |
| I2-F12-M2 | Like action correctness | remove unconditional `finally` store; surface failures; un-like path incl. `UndoLike` |
| I3-F12-M2 | Dislike store and controls | `localDislikes:v1` store; dislike/un-dislike button with the same state rules as like; mutual exclusivity with like |
| I4-F12-M2 | Reverse-match down-ranking in the Engine | accept dislikes in the recommendation request with a cap; vector search from disliked videos; apply a similarity-scaled score penalty; exclude the disliked videos themselves |
| I5-F12-M2 | Engine filter-profile store | dedicated profile database, separate from `users.db` and `whitelist.db`; profile id plus hashed key; dislikes and blocks keyed by profile; survives dataset rebuild and updater merge; rate-limited creation |
| I6-F12-M2 | Block controls and profile API | block/unblock on the video page, cards and channels page; a manage-blocks view; read/write endpoints through the Client gateway |
| I7-F12-M2 | Block enforcement in the Engine | anti-join against the profile block table by `instance_domain`+`channel_id` and by account, applied before candidates are scored |
| I8-F12-M2 | Home and random feed wiring | dislike down-rank on by default on home and available on random; blocks always applied; gateway allowlist entries for the profile reference |

Task IDs are allocated at `sync issues to task list for F12-M2` time from `task_count`
in `dev/map/DEV_MAP.json` (currently 86, so the first new task is 87).

### Acceptance criteria

1. Liking a video shows an unmistakable active state, distinguishable at a glance from
   the inactive state.
2. Reloading the video page preserves the active state for a previously liked video.
3. A like whose request fails leaves the button inactive and shows the user an error;
   the video does not appear in `localLikes:v1`.
4. Clicking an active like removes the video from `localLikes:v1` and the button returns
   to inactive.
5. The profile view and the like button never disagree about whether a video is liked.
6. The source instance's like count is never presented as if it included the local like.
7. Disliking a video shows an unmistakable active state, persists across reload, and is
   mutually exclusive with like on the same video.
8. After disliking a video, videos similar to it appear measurably lower in the home
   feed, without any further action by the user; the disliked video itself does not
   appear at all.
9. The random feed exposes dislike down-ranking as an option.
10. With many dislikes recorded, the feed still returns a full page of results —
    down-ranking reorders, it does not empty.
11. A dislike changes nothing for any other visitor: no global ranking signal is emitted.
12. Blocking a channel removes every video from that channel from every feed,
    immediately and on subsequent visits, until it is unblocked.
13. Blocking an account behaves the same way across all of that account's channels.
14. Blocks and dislikes are independent: blocking does not require disliking, and a
    disliked video's channel is not blocked implicitly.
15. A blocked channel's videos are absent from the candidate pool, not merely hidden
    after selection, so the feed still returns a full page.
16. Feed request size is constant regardless of how many channels are blocked.
17. Blocks and dislikes survive a full dataset rebuild, including an updater staging
    merge.
18. One visitor's blocks and dislikes have no effect on another visitor's feed.
19. With no profile, the app behaves exactly as it does today: anonymous, unfiltered,
    no key required.
20. A profile key presented from a second browser restores the same blocks and dislikes.
21. An absent, malformed or unknown profile key is rejected without revealing whether
    the profile exists.
22. The profile database stores no plaintext key.

### Risks

- **R1 — Store/UI drift.** The button, the profile view and the recommendation payload
  all read the same store; changing one write path without the others is how they
  desynchronise. Mitigated by keeping every mutation in `data/local-likes.ts`.
- **R2 — Count confusion.** Showing a local like next to a remote count invites the
  reading that the local like incremented it. Mitigated by criterion 6.
- **R3 — Duplicate work with 9b.** Tracked as a dependency above; resolve before sync.
- **R4 — Track mismatch.** `F12-M2` is recorded as `track: "Client"`, but S6 changes the
  Engine's candidate pipeline. Either the track widens at approval, or `I4-F12-M2` moves
  to an Engine-side feature and only the store, controls and wiring stay here.
- **R5 — Pool starvation from blocks.** Down-ranking cannot empty the feed, but blocks
  can: a visitor who blocks enough channels removes them permanently. Criterion 15
  requires exclusion before scoring so the pool is refilled rather than thinned, and the
  block list cap in O4 bounds how far this can go.
- **R6 — Cost per request.** Reverse matching means an extra vector search per disliked
  video per feed request, against the same index and under the same locks as everything
  else. The dislike cap in O4 is what bounds it; treat it as a performance control, not
  a formality. Blocks are cheap by comparison — an identity match, not a vector search.
- **R7 — Two filters, one surface.** Dislike and block are easy to conflate in the UI.
  They need visibly different controls and wording, or users will dislike expecting a
  block and conclude the feature is broken when similar videos keep appearing.
- **R8 — Dataset rebuilds must not destroy profiles.** `whitelist.db` is rebuilt from
  the crawl and the updater merges a staging database over it; anything stored there is
  transient. Filter profiles are durable user data and must live in their own database
  file that no dataset job touches. Getting this wrong loses every visitor's blocks on
  the next update, silently.
- **R9 — Client/Engine boundary change.** The Engine is currently read/analytics and
  holds no user state; the Client backend owns write and profile. This is enforced, not
  merely documented: `tests/run-arch-split-smoke.sh:435` fails the build if the Engine
  process has `users.db` open, and `DEPLOYMENT.md` states the contract as mandatory.
  Using a separate profile database keeps that specific check passing, but the contract
  wording, the boundary documentation and milestone M1's "Done" boundary work all
  describe an Engine with no user state. They must be amended deliberately as part of
  this feature rather than quietly contradicted.
- **R10 — Hard dependency on identity.** Without per-visitor identity, an Engine-side
  profile is the shared `local-user` row: one visitor's blocks would apply to every
  visitor, and any visitor could read or wipe another's filters. This feature cannot
  ship before security task 82, whose scope changes under O7 from a signed cookie to a
  profile key.
- **R11 — Key loss is profile loss.** There is no account recovery path and no email.
  A cleared browser store loses the profile unless the user saved the key. The UI must
  make the key visible and copyable at creation and state that it is the only copy.
- **R12 — Profile creation as a growth vector.** An anonymous endpoint that creates a
  durable row on request is free unbounded storage for anyone who finds it. Rate
  limiting is a functional requirement here, not hardening.

### Validation strategy

- Manual: like, reload, confirm state persists; un-like, reload, confirm it is gone;
  stop the Client backend and confirm a failed like does not appear liked.
- Console: `JSON.parse(localStorage.getItem('localLikes:v1'))` agrees with the button
  state after every operation.
- `tests/run-arch-split-smoke.sh` still passes (`client_user_action_validate` covers the
  POST path).

### Rollback notes

- All changes are frontend-only under the current scope; reverting the bundle and
  re-running the deploy `rsync` restores previous behaviour.
- No schema or stored-data format changes, so no migration and no data loss on revert.

---

## F4-M4 — Implement a feed parameter panel

- **feature_id:** `F4-M4`
- **feature_title:** Implement a feed parameter panel.
- **milestone_id:** `M4` (Discovery and controlled content scope)
- **status:** `Planned` (not approved)
- **track (current):** `Client` — see R4, this plan spans Crawler and Engine as well.

The panel is the single surface for "what shows up in my feed". Three capabilities are
planned together because they share one mechanism: a set of client-held preferences that
are persisted locally and applied to the feed request.

### Scope

**C1 — Language capture and filtering**

- Add `language_id` (lowercase code, e.g. `en`) and `language_label` to the `videos`
  table in `engine/crawler/schema.sql` and to `ensure_content_schema` in
  `engine/server/db/jobs/sync-whitelist.py`.
- Capture `video.language` in `videos-worker.ts` (`toVideoRow`); PeerTube returns it as
  `{"id": "en", "label": "English"}` on both the channel-videos listing and the
  per-video detail endpoint.
- Accept a `language` parameter on the Engine feed/serving paths, parameterised in the
  same style as the existing channel filters, and add `language` to the response
  projection so it reaches the client.
- Add `language` to the per-route query allowlists in `client/backend/server.py`;
  unlisted parameters are rejected outright by the gateway.
- Two independent toggles in the panel, both persisted:
  - **on/off** — whether language is considered at all (default **off**),
  - **strict/preference** — when on, either exclude other languages, or rank them lower
    while still showing them.

**C2 — Saved channels**

- A client-held list of saved channels (`instance_domain` + `channel_id`), persisted in
  `localStorage` alongside the existing `localLikes:v1` store and following the same
  shape and size-cap conventions.
- A save/unsave control on the channels page rows and on the video page channel line.
- A feed mode that restricts or boosts results to saved channels, expressed through the
  same panel as C1.
- Engine support for filtering a feed by a set of `(instance_domain, channel_id)` pairs,
  with a server-side cap on how many pairs one request may carry.

**C3 — Feed paging**

- The feed currently reveals six already-fetched rows at a time (`CHUNK_SIZE` in
  `client/frontend/src/pages/videos/index.ts`) and never refetches, so scrolling stops
  when the first response is exhausted.
- Refetch with an increasing offset when the scroll sentinel is reached, so the feed
  continues past the first response.
- Requires a stable ordering or seed on the Engine side so page N+1 does not repeat
  page N.

### Out of scope

- **Backfilling `language` for existing rows.** At the time of writing the dataset holds
  887,214 videos with no language value. Backfill is one HTTP request per video, the same
  cost as the tags enrichment stage, and is tracked as its own issue. The C1 toggle
  defaults to off precisely so delivery does not depend on it.
- **Following in the PeerTube/ActivityPub sense.** C2 is a local list only. Real
  following requires the Engine to be an ActivityPub actor and belongs to `F1-M5` and
  `F2-M5`.
- Server-side user accounts or cross-device sync of preferences. Preferences are local,
  consistent with how likes already work.
- Any change to the recommendation mixer's scoring model beyond applying these filters.

### Dependencies

- **D1 → D2:** the schema change and the crawler capture must land in the same change
  set. `_assert_columns_exact` in `sync-whitelist.py` compares the whitelist DB against
  `engine/crawler/schema.sql`; if one side gains a column without the other, the sync
  gate fails outright. This has already broken the build twice for unrelated reasons.
- **D2 → C1 filtering:** no filter can be validated until crawled rows carry a language.
- **C3 → Engine ordering:** paging needs deterministic ordering or a seeded random
  sequence; the current random feed path would otherwise repeat rows across pages.
- **C2 → gateway allowlist:** saved-channel filtering sends a new body/query shape, which
  the Client gateway rejects until explicitly allowlisted.

### Overlaps with `dev/TASK_EXECUTION_PIPELINE.md`

- **Task 76** (cap crawled display name/channel name length, SI2-M1) touches
  `videos-worker.ts` ingest, the same function C1's capture modifies. Land 76 first or
  combine them to avoid two passes over `toVideoRow`.
- **Task 73** (reject non-http(s) URLs at crawl time, SI1-M1) already added
  `toHttpUrlOrNull` to `engine/crawler/src/host-filters.ts`; C1's normalisation helper
  belongs in the same module rather than a new one.
- **Block C** in the pipeline (`8b -> 10 -> 15`, feed modes and search) covers feed-mode
  switching. C1 and C2 add parameters to that same surface; do not build a second,
  parallel feed-parameter mechanism.
- `F6-M3` (separate search API) may absorb language as a *search* filter. Keep one
  parameter name and one validation path across both surfaces.

### Draft decomposition

| Issue | Title | Tasks (indicative) |
|---|---|---|
| I1-F4-M4 | Language capture in crawler and schema | schema columns + `ensure_content_schema`; `toVideoRow` capture and normalisation |
| I2-F4-M4 | Language serving and filtering | Engine parameter + response projection; gateway allowlist entry |
| I3-F4-M4 | Language backfill for existing rows | backfill job over `/api/v1/videos/<uuid>`, resumable, rate-limited per host |
| I4-F4-M4 | Saved channels store and controls | `localStorage` store; save/unsave on channels page and video page |
| I5-F4-M4 | Saved channels feed filtering | Engine filter by `(instance_domain, channel_id)` set with a server-side cap; gateway allowlist |
| I6-F4-M4 | Feed paging | offset/seed handling on the Engine; sentinel-triggered refetch in the feed |
| I7-F4-M4 | Feed parameter panel UI | one panel binding the language toggles, saved-channels mode and existing feed modes; preferences persisted |

Task IDs are allocated at `sync issues to task list for F4-M4` time from `task_count` in
`dev/map/DEV_MAP.json`, never by scanning `dev/TASK_LIST.md`.

### Acceptance criteria

1. A newly crawled video row carries a non-null `language_id` when the source instance
   reports one, and null when it does not.
2. `sync-whitelist.py` completes against a fresh crawl DB with the new columns present on
   both sides.
3. With the language toggle **off**, feed results are identical to current behaviour,
   including for rows with no language value.
4. With the toggle **on** in strict mode, every returned row matches a selected language.
5. With the toggle **on** in preference mode, other languages still appear but rank below
   matching ones, and rows with no language are not silently dropped.
6. Saving a channel and selecting the saved-channels feed mode returns only videos from
   saved channels; unsaving removes it without a reload.
7. Saved channels and language preferences survive a page reload and a browser restart.
8. Scrolling the feed past the first response loads further results without repeating
   rows already shown.
9. The gateway rejects a request carrying an unlisted parameter, and accepts `language`
   and the saved-channels parameter.

### Risks

- **R1 — Sparse language data.** Many instances leave `language` unset or wrong. Strict
  mode may empty the feed. Mitigated by defaulting to off, defaulting to preference
  rather than strict, and never dropping unknown-language rows in preference mode.
- **R2 — Backfill cost.** 887k per-video requests is a multi-day job and re-runs the same
  rate-limit exposure as the tags stage. Mitigated by keeping it a separate, resumable
  issue that no other work blocks on.
- **R3 — Paging stability.** The random feed path has no stable ordering; naive offset
  paging will repeat and skip rows. Mitigated by requiring a seed in the request.
- **R4 — Track mismatch.** `F4-M4` is recorded as `track: "Client"` and
  `optional: true`, but this plan changes the crawler schema and the Engine. Either the
  track is widened at approval time, or C1's capture half moves to a Crawler/Engine
  feature and only the panel stays here.
- **R5 — Saved-channel request size.** An unbounded set of channel pairs in one request
  is the same class of problem as audit finding F11. The server-side cap in I5 is not
  optional.

### Validation strategy

- Unit-level: language normalisation and the saved-channel store round-trip, as standalone
  harnesses in the style of `engine/crawler/test-url-safety.mjs`.
- Schema gate: run `sync-whitelist.py` against a scratch crawl DB built from
  `engine/crawler/schema.sql` before touching real data.
- Contract: `tests/check-frontend-client-gateway.sh` and
  `tests/check-client-engine-boundary.sh` must still pass; new parameters must travel
  through the gateway, never direct from the frontend to the Engine.
- End-to-end: `tests/run-arch-split-smoke.sh` after the Engine parameter lands.
- Manual: toggle each preference on a live feed and confirm criteria 3-8 in a browser.

### Rollback notes

- C1 filtering, C2 and C3 are all client-triggered; shipping them with the panel default
  to off makes rollback a matter of not enabling the control.
- The schema columns are additive and nullable; leaving them in place with no writer is
  harmless, so a crawler-side revert does not require a DB migration.
- The backfill job is resumable and writes only the new columns, so a partial run can be
  abandoned without affecting existing fields.

---

## F6-M3 — Implement a separate search API

- **feature_id:** `F6-M3`
- **feature_title:** Implement a separate search API.
- **milestone_id:** `M3` (API v1 and discovery behavior)
- **status:** `Approved` (re-approved after the O9 amendment)
- **track:** `Engine`

There is no video search of any kind today. The Engine serves similarity, recommendation
and channel-listing routes; a free-text video query has no endpoint and no index behind
it. This feature adds both retrieval halves: an FTS5 lexical index over the metadata the
dataset already holds, and a vector half over the existing FAISS index, fused behind one
read endpoint.

The vector half exists for one reason: **cross-language retrieval**. The corpus is
mostly non-English. BM25 can only match tokens the query and the document share, so an
English query cannot reach a Russian video except through incidental English tokens.
A multilingual embedding space can, which makes the query encoder a requirement rather
than a quality refinement.

### Current state (measured, not assumed)

| Fact | Where | Today |
|---|---|---|
| Video search endpoint | `similar.py:375-436` (`_dispatch_get`) | None. Routes are `/api/health`, `/api/channels`, `/api/video`, `/videos/{id}/similar` |
| Full-text index | `engine/crawler/schema.sql:90-98`, `sync-whitelist.py:335-345` | None. Only b-tree indexes on `published_at`, `popularity`, `views`, channel columns |
| FTS5 availability | probed against both interpreters | Available. SQLite 3.53.4, `ENABLE_FTS5` in `PRAGMA compile_options`. No new dependency |
| Encoder libraries in the serving env | `engine/.pixi/envs/default/lib/python3.12/site-packages` | Already present: `torch` 2.5.1+cu121, `sentence_transformers` 5.2.0, `faiss_gpu_cu12` 1.13.2. The serving process and the batch job share one environment, so the vector half adds **no new dependency** |
| Encoder load cost | measured in that interpreter, CPU | `import torch` 1.62s, `import sentence_transformers` 2.60s (one-time per process, not reclaimable), model load from HF cache **0.13s**, first encode 0.123s, warm encode **0.005s**, process RSS 605MB |
| Model cache | `~/.cache/huggingface/hub` | Holds `all-MiniLM-L6-v2` and `multi-qa-MiniLM-L6-cos-v1`. No multilingual model is cached, so its first load downloads (~470MB for the L12 candidate) |
| Serving concurrency | `api/server.py:13,191` | `ThreadingHTTPServer`. Handlers run on concurrent threads, so any lazily created singleton needs its own lock |
| Existing locks | `api/server.py:255-256`, `data/ann.py:36` | `db_lock`, `similarity_db_lock`, `index_lock` |
| FAISS index at runtime | `api/server.py:324-331` | Already resident, mmap read-only, `nprobe` set, dimension checked against `video_embeddings` at startup |
| Vector-to-rows path | `data/ann.py:88-114`, `similar.py:709-731` | `search_index(index, vector, limit, exclude)` -> rowids -> `fetch_metadata`. Takes an arbitrary vector; nothing about it is similarity-specific |
| Model identity check | `api/server.py:319-331` vs `build-ann-index.py:310` | The index metadata records `model_name`, but the server reads only `index.d`. A dimension check cannot catch a model change, because the current model and the multilingual L12 candidate are **both 384-dim** |
| Embedding source data | `build-video-embeddings.py:176-208` | Read from `whitelist.db` only. Changing models needs no re-crawl |
| Model selection in the pipeline | `run-dataset-build.sh:221-222` | Calls the job with no `--model-name`, so it silently takes the script default at `build-video-embeddings.py:116`. The model cannot be chosen without a code change |
| Searchable text | `build-video-embeddings.py:34-58` | `title`, `description`, `tags_json`, `category`, `channel_name` |
| Description length | `videos-worker.ts:684` | Truncated at the source (~250 chars); the crawler never calls the description endpoint |
| Language metadata | `engine/crawler/schema.sql`, `videos-worker.ts` | None. No `language`, `caption` or `subtitle` field is stored anywhere, though PeerTube exposes them |
| Writers to `videos` | `sync-whitelist.py:385-406`, `merge_rules.json:14`, `whitelist_migrations.py:357` | Full rebuild on sync, upsert on updater merge, and a drop/rename on migration |
| GPU | `nvidia-smi` | RTX 3070, 8192MiB total, ~1810MiB in use |

### Scope

- **S1 Multilingual embedding space.** `build-video-embeddings.py`'s default model becomes
  the multilingual model from O2, and `run-dataset-build.sh` gains a `--model-name`
  pass-through so the choice is explicit at the pipeline level rather than implied by a
  default. `DATA_BUILD.md:165` is corrected in the same change (it still names
  `all-MiniLM-L6-v2`, which has not been the default for two model changes). The re-embed
  itself is Phase 0's run, not a task here.
- **S2 FTS5 index in the dataset.** An external-content `videos_fts` virtual table in
  `whitelist.db` over `title`, `description`, `tags_json`, `category`, `channel_name`,
  created in `ensure_content_schema` and populated in the existing `sync` stage. No new
  stage in `run-dataset-build.sh`. `tags_json` is indexed as stored: the default
  `unicode61` tokenizer discards the JSON punctuation and leaves the tag words.
- **S3 Index consistency under every writer.** Insert/update/delete triggers on `videos`
  keep the external-content index in step, because the updater merge writes `videos`
  outside the sync stage (`merge_rules.json:14`). `whitelist_migrations.py` drops and
  renames `videos`, so it must drop and rebuild the FTS table in the same migration.
- **S4 Query encoder with a managed lifecycle.** A module owning one
  `SentenceTransformer`, loaded on first use behind a lock and released after an idle
  timeout, so an Engine that is never searched pays nothing and an Engine that is searched
  once does not hold the weights forever. Detail in O3 and O4.
- **S5 Model identity gate.** The index-versus-database half of this **has already landed**
  as a side edit outside this feature: `api/server.py` now resolves the single
  `(embedding_dim, model_name)` in `video_embeddings`, refuses to start on a mixed table,
  and compares `model_name` against the FAISS sidecar JSON. What remains in scope here is
  the third comparison the encoder introduces — the configured query-encoder model against
  that same index model — which refuses to serve the vector half, rather than the process,
  when they disagree.
- **S6 The endpoint.** `GET /api/v1/search/videos?q=&page=&limit=&sort=` returning the same
  stable video row shape the other read routes return, plus `total` and `generatedAt`.
  `sort=relevance` (default) is the fused hybrid ranking from O5; `published_at`, `views`
  and `popularity` are lexical-only orderings, since a non-relevance sort has nothing to
  fuse. `limit` capped the way `/api/channels` caps it at `similar.py:393-396`.
- **S7 Query sanitization.** FTS5 `MATCH` takes a query *language*, not a string: a raw
  user term can inject `NEAR`, `*`, `^`, column filters and quotes, which either errors
  or builds a deliberately expensive scan. The term is tokenized, FTS operators are
  dropped, each token is quoted as a string literal, and token count and length are
  capped. The same capped term is what reaches the encoder, so one sanitizer serves both
  halves and an oversized query cannot be used to burn encoder time either. This is the
  same class of fix task 74 applied to the `/api/channels` `LIKE` path, and it is not
  optional.
- **S8 Parity with the other read routes.** Search results pass
  `apply_serving_moderation_filters`, run under the per-path rate limiter and under the
  statement deadline, exactly as `/api/channels` and `/api/video` do. Encoding happens
  **outside** `db_lock` (see R6).
- **S9 Gateway exposure.** `/api/v1/search/videos` is added to `PROXY_READ_GET_ROUTES` and
  `PROXY_ALLOWED_QUERY_PARAMS` in `client/backend/server.py:47-64`, so the frontend
  reaches it through the Client gateway and never the Engine directly.

### Resolved decisions

- **O1 — hybrid, reversing the earlier BM25-only decision.** The original O1 rejected the
  vector half on two grounds: the serving process has no encoder, and keyword matching
  reaches most of the available quality. The first is factually wrong — `torch` and
  `sentence_transformers` are already installed in the Engine environment, so the cost is
  an import and a lock, not a dependency. The second assumed same-language search; it does
  not hold for cross-language retrieval, which is the requirement that triggered this
  re-plan. BM25 stays, because it beats vectors on exact titles, tags, channel names and
  proper nouns.
- **O2 — model: `paraphrase-multilingual-MiniLM-L12-v2` (384-dim).** Chosen over
  `multilingual-e5-base` because it keeps the current dimension, so the embeddings table,
  the FAISS index shape and the startup dimension check are unchanged in size and
  behaviour: 892k rows at 384-dim is ~1.37GB against ~2.7GB at 768-dim. It also has no
  prefix protocol, whereas e5 requires `query:` and `passage:` prefixes added to both the
  batch payload and the query path, which is one more way for the two sides to disagree
  silently. **Confirm this at approval:** it is the one decision here whose reversal costs
  a full re-embed rather than an edit.
- **O3 — lifecycle: lazy load, resident while used, idle release.** Measured, the
  expensive part is the *import* (4.2s, one-time, not reclaimable once done) and not the
  *load* (0.13s from cache). So the split is: import and load together on the first query
  that needs a vector, keep the model while queries keep arriving, and drop the reference
  after `QUERY_ENCODER_IDLE_SECONDS` (default 900) to return the weights. A reload after
  eviction costs the 0.13s load, not the 4.2s import, which is what makes eviction worth
  doing at all. First-ever load also downloads the model, so it is pre-warmed by the
  deployment step rather than paid by a user's first search.
- **O4 — eviction by a daemon timer thread, and the model handed out by value.**
  Checking idleness on the request path cannot free anything, because memory is only
  released when a request *does* arrive, which is exactly when it is not idle. One daemon
  thread checking last-use against the timeout is the smallest thing that works. Under
  `ThreadingHTTPServer` the getter returns a strong reference under the lock and the
  caller encodes with that reference, so an eviction landing mid-encode drops the
  singleton without pulling the model out from under a running thread.
- **O5 — fusion by rank (RRF), not by score.** `bm25()` returns an unbounded negative
  relevance and the index returns a cosine similarity in [-1, 1]; adding or weighting them
  requires a normalization that has to be re-tuned whenever either side changes.
  Reciprocal rank fusion over the two ranked lists needs no calibration and no score
  comparison. Each half retrieves its own candidates, the fused list is truncated to the
  page.
- **O6 — query encoding on CPU.** A single short query is 5ms warm on CPU, measured. The
  GPU has headroom but is wanted by the batch re-embed, and a CUDA context in the serving
  process costs memory permanently for a 5ms saving that no user perceives.
- **O7 — external content, not a standalone copy.** `content='videos'` stores no second
  copy of the text, which matters at dataset scale. The cost is that consistency becomes
  the triggers' job (S3) rather than a rebuild's.
- **O9 — the route is born versioned, at `/api/v1/search/videos`.** Adding the segment
  now costs one string in a route that has no callers yet; adding it later is a breaking
  move for whatever consumes search by then, including task 10's page. This deliberately
  leaves a mixed surface — `/api/channels` and `/api/video` stay unversioned until
  `F2-M3` migrates them — which is accepted as the normal shape of incremental
  versioning, not an oversight. Folding all of `F2-M3` in here was considered and
  rejected: it reaches Engine dispatch, both gateway allowlists, two frontend call sites
  (`data/channels.ts:36`, `video-page/index.ts:385`) and roughly twenty hardcoded URLs in
  `tests/run-arch-split-smoke.sh` and `tests/run-installers-smoke.sh`, and it needs an
  alias-and-deprecation policy this feature has no reason to decide.
- **O8 — FTS built in the `sync` stage, not a new one.** `rebuild_content_tables` already
  rewrites `videos` wholesale; the index is rebuilt at the end of the same transaction.
  This satisfies the Phase 4 constraint that the index is built in the same pass as the
  embeddings, without a stage that can be skipped or ordered wrongly.

### Out of scope

- **Translation and subtitles.** A multilingual encoder makes foreign-language video
  *findable*; it cannot make it *readable*, because it is an encoder and emits vectors,
  not text. Translated titles, captions and ASR are a separate feature, and one that
  starts with the crawler storing `language` and captions, which it does not.
- **Storing `language` on `videos`.** Useful for a search filter and cheap to add, but not
  required for this endpoint to work. Deliberately deferred with translation rather than
  smuggled in here.
- Reranking beyond RRF: cross-encoders, learned weights, per-language tuning.
- The search page UI. That is `F10-M2` / task **10**, which consumes this endpoint.
- Widening the corpus: full descriptions and captions are separate features.
- Channel search. `/api/channels?q=` already covers it.
- Personalized or profile-filtered results. Search is anonymous and identical for every
  caller.

### Dependencies and overlaps

- **Phase 0, now a hard precondition.** The vector half retrieves from the space the index
  was built in. Until Phase 0 re-embeds on the O2 model, `sort=relevance` returns
  English-only semantics, and S5's identity gate will refuse the vector half outright if
  the index still records the old model. The FTS half additionally needs one
  `run-dataset-build.sh --from sync` before the endpoint returns anything.
- **Model choice precedes the re-embed, not the code.** O2 must be settled before Phase 0
  runs, because the re-embed is the expensive pass and running it twice is the failure
  this ordering exists to prevent.
- **No identity dependency.** Unlike Phases 2 and 5, nothing here needs a profile, which
  is why Phase 4 runs as a parallel track.
- **Task 10 "Video search page" — resolved at sync.** It is rebound to `[M2][F10]`, its
  path carries the `v1` segment per O9, and the LIKE fallback is dropped because FTS5 is
  confirmed present. It keeps the UI half only; this feature delivers the server half.
- **`F2-M3` "Implement API versioning" stays a separate feature.** O9 puts only the new
  route under `/api/v1/`; the four existing routes are F2-M3's work. `TASK_LIST.md:157`
  and the Block C outcome line in `TASK_EXECUTION_PIPELINE.md:42` both name the
  unversioned path and are corrected at sync time.
- **Pipeline Block C** (`8b -> 10 -> 15`) names the search API in its outcome line. Block C
  must be updated to carry this feature's tasks at sync time.
- **Marker inconsistency — closed for task 10, open elsewhere.** Task 10 now reads
  `[M2][F10]`, matching `F10-M2` "Implement the video search page". Tasks **8b**, **12a**
  and **33** still carry `[M3][F2]` while being feed and similarity work, not API
  versioning; they are outside this feature and were left untouched.

### Draft decomposition

| Issue | Title | Indicative tasks |
|---|---|---|
| I1-F6-M3 | Multilingual embedding space | Change the default model at `build-video-embeddings.py:116`; add `--model-name` pass-through in `run-dataset-build.sh:221-222` and to its usage block; correct the stale default in `DATA_BUILD.md:165` |
| I2-F6-M3 | FTS5 index in the dataset build | `videos_fts` external-content table in `ensure_content_schema`; insert/update/delete triggers on `videos`; rebuild at the end of `rebuild_content_tables`; drop-and-rebuild in `whitelist_migrations.migrate_videos_schema`; `report_counts` gains an FTS row count |
| I3-F6-M3 | Query encoder lifecycle | Encoder module with lock-guarded lazy load, idle-eviction daemon thread, strong-reference handout; idle timeout and model name in `server_config.py`; startup identity gate reading `model_name` from the FAISS metadata JSON; vector half disabled with a logged reason on mismatch |
| I4-F6-M3 | Hybrid search endpoint | `GET /api/v1/search/videos` in `_dispatch_get`; FTS5 `MATCH` with `bm25` ordering; vector retrieval reusing `search_index` and `fetch_metadata`; RRF fusion; `published_at`/`views`/`popularity` lexical sorts; paging with `total`; query sanitization and token caps shared by both halves; serving-moderation filter, rate limit and statement deadline parity; encoding outside `db_lock` |
| I5-F6-M3 | Gateway exposure | `PROXY_READ_GET_ROUTES` and `PROXY_ALLOWED_QUERY_PARAMS` entries in the Client backend; boundary tests still pass |

Task IDs are allocated at `sync issues to task list for F6-M3` time from `task_count` in
`dev/map/DEV_MAP.json` (currently 86, so the first new task is 87).

### Acceptance criteria

1. After a `sync` stage run, `SELECT COUNT(*) FROM videos_fts` equals
   `SELECT COUNT(*) FROM videos` in `whitelist.db`.
2. Inserting, updating and deleting a `videos` row outside the sync stage leaves the two
   counts equal and the changed text findable or unfindable accordingly.
3. `GET /api/v1/search/videos?q=<term>` returns rows whose `title`, `description`, tags,
   category or channel name contain the term, in the stable row shape the other read
   routes return, with `total` and `generatedAt` present.
4. **Cross-language:** an English query returns relevant non-English-titled videos that
   share no query token with it, and the same query against the pre-migration
   English-only index does not. Verified manually against the live dataset.
5. An exact title, tag or channel name still ranks first, confirming the lexical half is
   not drowned by the vector half.
6. `page` and `limit` page the result set without repeating or skipping rows, and `limit`
   above the cap is clamped rather than honoured.
7. Each `sort` value orders the result set by that field; `sort=relevance` orders by the
   fused ranking.
8. A query containing FTS5 operators (`NEAR`, `*`, `^`, `"`, `col:`) returns a normal
   result set or an empty one, never a 500 and never an unbounded scan.
9. A query of many tokens or one very long token is capped and answers within the
   statement deadline.
10. The first search after start loads the encoder once even when several searches arrive
    concurrently, and the log records one load.
11. After `QUERY_ENCODER_IDLE_SECONDS` with no search, the process releases the model and
    its RSS drops; the next search reloads and answers correctly.
12. An Engine started against an index whose recorded `model_name` differs from the
    configured encoder does not serve vector results and logs both names.
13. Videos excluded by serving moderation do not appear in search results.
14. The endpoint is reachable through the Client gateway, and an unlisted query parameter
    is rejected there rather than forwarded.
15. `tests/check-client-engine-boundary.sh` and `tests/check-frontend-client-gateway.sh`
    pass.

### Risks

- **R1 — Silent model/index mismatch.** The candidate model and the current one are both
  384-dim, so the dimension check that existed before this plan passed against an index
  built in a different semantic space, and every vector result would have been plausible
  nonsense. **Closed for the index-versus-database case** by the S5 side edit, verified
  against the live artifacts. The check lives in `data/embedding_space.py` and is applied
  by both readers of the index: the API server at startup and
  `precompute-similar-ann.py`, which builds the similarity cache the feed serves. It
  remains open for the query encoder until I3 lands.
- **R2 — Index desync under the updater.** The updater merge upserts `videos`
  (`merge_rules.json:14`) with no knowledge of an FTS table. Without S3's triggers the
  index silently drifts on every background update, and the failure is invisible until
  someone searches for a recently merged video. Triggers, not a rebuild in the merge job,
  because the merge job is rules-driven and table-agnostic.
- **R3 — Migration drops the content table.** `whitelist_migrations.py:357` does
  `DROP TABLE videos; ALTER TABLE videos_new RENAME TO videos`. An external-content FTS
  table and its triggers do not survive that untouched, so the migration must drop and
  rebuild them explicitly or the next query errors against a missing content table.
- **R4 — MATCH injection and query cost.** Covered by S7. Untreated, this is audit finding
  F10's shape on a new endpoint: caller-controlled query structure executed under the
  global `db_lock`.
- **R5 — First-query latency.** The 4.2s import is paid by whoever searches first. Under a
  statement deadline that could surface as a timeout on an otherwise healthy request.
  Mitigated by pre-warming at deploy time (O3); if the deadline applies to the encode
  path, the load must sit outside it.
- **R6 — Encoding under `db_lock` would stall the feed.** Search shares the one global
  read lock. Holding it across a model load, or even across an encode, blocks every other
  read route. S8 puts encoding outside the lock; this is a correctness requirement, not an
  optimization.
- **R7 — Eviction race.** Under `ThreadingHTTPServer` the idle thread can drop the
  singleton while a request thread is encoding. O4's strong-reference handout covers it,
  and criterion 11 only proves the happy path, so this needs a deliberate concurrent test
  rather than an observed absence of crashes.
- **R8 — Serving memory.** The measured process RSS with model and libraries loaded is
  605MB, added to a process that already mmaps the FAISS index. On a 29GB host this is
  comfortable; it is stated so a smaller deployment target is not assumed to be fine.
- **R9 — Re-embed is single-shot and expensive.** An O2 reversal after Phase 0 means
  redoing the whole embed and every derived artifact. This is why O2 is called out for
  explicit confirmation at approval.
- **R10 — Multilingual models trade some monolingual precision.** A multilingual space is
  usually a little weaker on English-only matching than an English-only model of the same
  size. The lexical half absorbs most of that, and criterion 5 is the check.
- **R11 — Quality ceiling from the corpus.** Descriptions are ~250 characters
  (`videos-worker.ts:684`) and `comments_count` contributes a bare integer to the text
  payload. Relevance will be judged against the full descriptions users expect, not the
  blurbs the dataset holds. Accepted; the fix is a corpus change, not a retrieval change.
- **R12 — FTS build time and size.** The FTS build extends the `sync` stage on a full
  dataset. External content keeps the size down but the tokenizer pass is real. Measure on
  the first run before assuming the stage timing is unchanged.

### Validation strategy

- Schema gate: run `sync-whitelist.py` against a scratch crawl DB built from
  `engine/crawler/schema.sql`, then assert criterion 1.
- Trigger check: a standalone harness in the style of
  `engine/server/db/jobs/tests/test-security-bundle.py` that writes `videos` directly and
  asserts criterion 2, covering the updater-merge path that R2 names.
- Encoder lifecycle: concurrent first requests assert a single load (criterion 10); a
  shortened idle timeout asserts release and correct reload (criterion 11); an encode
  running concurrently with a forced eviction asserts R7 does not fault.
- Identity gate: start against an index metadata file naming a different model and assert
  criterion 12.
- Query safety: drive the endpoint with a fixed list of FTS5 operator strings and
  oversized terms, asserting criteria 8 and 9.
- Contract: `tests/check-client-engine-boundary.sh` and
  `tests/check-frontend-client-gateway.sh`.
- End-to-end: `tests/run-arch-split-smoke.sh` after the route lands.
- Manual, in the operator's browser: criteria 4 and 5 against the live dataset, including
  queries in English against known Russian-language content.

### Rollback notes

- The endpoint is purely additive; removing the route restores the previous surface with
  no effect on any other caller.
- The vector half is separable from the lexical half: disabling the encoder leaves a
  working BM25 endpoint, which is also the degraded mode S5 falls back to on a model
  mismatch.
- The FTS table and its triggers are droppable in one statement each. `videos` itself is
  untouched by this feature — no column is added, so no data migration is involved and the
  existing `_assert_columns_exact` sync gate is unaffected.
- A partially built index is not a half-broken state: the endpoint returns fewer rows
  until the next sync rebuilds it.
- The embedding-model change is **not** rollback-cheap. Reverting it means another full
  re-embed and rebuild of every derived artifact; treat O2 as a one-way door.

---

## F10-M2 — Implement the video search page

- **feature_id:** `F10-M2`
- **feature_title:** Implement the video search page.
- **milestone_id:** `M2` (Video-ID indexing and UI rewrite foundations)
- **status:** `Approved`
- **track:** `Client`

`F6-M3` delivered `GET /api/v1/search/videos` and it is live, reachable through the
gateway, answering with `vectorSearch: true`. Nothing in the frontend calls it: there is
no search page, no search control in any header, and no link to either. This feature is
the consuming half — one page, its data client, and the navigation that reaches it.

### Current state (measured, not assumed)

| Fact | Where | Today |
|---|---|---|
| Search UI | `client/frontend/*.html` | None. The four pages are `index.html` (home feed), `videos.html`, `video-page.html`, `channels.html` |
| Search endpoint | `engine/server/api/handlers/similar.py` | Live. Verified 200 through the gateway with `total`, `page`, `limit`, `sort`, `vectorSearch`, `rows` |
| Gateway allowlist | `client/backend/server.py:47-53` | Route and `q`, `page`, `limit`, `sort` permitted; any other parameter is rejected with 400 at the gateway |
| Card rendering | `client/frontend/src/pages/videos/index.ts:325-383` | `renderCard` plus ~10 helpers (`thumbnailUrl`, `channelName`, `formatDuration`, `formatTimeAgo`, `videoPageUrl`, `escapeHtml`) live inside a 954-line page module and are not exported |
| Card styles | `client/frontend/src/videos.css` | `.cards-grid`, `.video-card` and children, 506 lines, imported by the videos page module |
| A comparable page | `client/frontend/src/pages/channels/index.ts` | 352 lines: debounced filter input, `requestSeq` guard against out-of-order responses, explicit prev/next pager, `?api=` override |
| Data client pattern | `client/frontend/src/data/channels.ts` | Builds the URL against `resolveClientApiBase`, passes through `fetchJsonWithCache` with a TTL |
| Build inputs | `client/frontend/vite.config.ts:76-88` | Four named rollup inputs; a fifth page needs an entry here |
| Dev/preview routing | `client/frontend/vite.config.ts:19-20,46-56` | Extensionless paths are rewritten by a middleware set (`/videos`, `/about`) |
| Production routing | `DEPLOYMENT.md:292-296` | `location /` is `try_files $uri $uri/ =404` over the rsynced `dist/`, and `location /api/` already proxies the whole prefix, so the new route needs no nginx change |
| CSP | every page's `<head>` | `default-src 'self'; script-src 'self'` — inline scripts are not an option |
| XSS discipline | `videos/index.ts`, `utils/safe-url.ts` | Every interpolated value passes `escapeHtml`, every external URL `safeExternalUrl`. Audit tasks 69-73 established this |

### Scope

- **S1 Shared video-card module.** `renderCard` and the helpers it needs move to
  `client/frontend/src/components/video-card.ts`, exported and imported by both the videos
  page and the search page. The card markup, escaping and `videoPageUrl` logic exist once.
  This is a move, not a redesign: the videos page must render identically afterwards.
- **S2 Search data client.** `client/frontend/src/data/search.ts` with
  `fetchSearchResults({ q, page, limit, sort })`, built on `resolveClientApiBase` and
  `fetchJsonWithCache` exactly as `data/channels.ts` is, plus a `SearchPayload` type in
  `src/types/videos.ts`. It sends only the four allowlisted parameters, because a fifth is
  a 400 at the gateway.
- **S3 The page.** `search.html` plus `src/pages/search/index.ts`: a query input, a sort
  control offering the API's four values, a results grid of shared cards, a result count,
  and a "Load more" control that appends the next page.
- **S4 URL as state.** The query, sort and page live in the address bar (`?q=&sort=&page=`),
  so a result set is linkable, survives reload, and the back button works. The page reads
  them on load and writes them on change.
- **S5 Explicit states.** Idle (no query yet), loading, empty ("no results for X"), error,
  and the 503 the Engine returns before the FTS index exists, which gets its own message
  rather than a generic failure.
- **S6 Out-of-order protection.** A `requestSeq` guard as on the channels page: typing
  produces overlapping requests and the last response to arrive is not necessarily the
  current query's.
- **S7 Reachability.** A `Search` link in the header nav of `index.html`, `videos.html`,
  `channels.html` and `video-page.html`, matching the existing `nav-link` markup. Without
  this the page exists and no one finds it, which is the state the endpoint is in today.
- **S8 Build wiring.** A fifth rollup input in `vite.config.ts`, and `/search` added to the
  dev and preview rewrite sets so the extensionless path works in development as `/videos`
  does.

### Resolved decisions

- **O1 — ships against the current ranking.** Fusion currently favours same-language
  results: a row found by both halves outranks a vector-only row, so an English query
  returns mostly English titles and the first Cyrillic result appears around rank 19-60.
  Measured, the corpus is 3.7% Cyrillic-titled and 58.8% ASCII-only, so this may be close
  to what the data supports. Tuning it is deferred until real result pages have been
  looked at; the page is what makes that judgment possible.
- **O2 — extract the card, do not copy it.** Two copies of card markup means two places to
  fix an escaping bug, and audit tasks 69-73 were exactly that class of bug. The extraction
  is the larger part of the risk in this feature and is why it is its own issue, landing
  before the page that depends on it.
- **O3 — "Load more", not infinite scroll.** The feed scrolls infinitely because it is a
  browsing surface with no endpoint; search has a result count and an explicit page, and a
  user comparing results wants a stable list. It is also less code: no `IntersectionObserver`,
  no viewport-fill loop, no scroll listeners.
- **O4 — one page, not a modal or a header-wide instant search.** A dedicated page is
  linkable, needs no layout change on four existing pages, and matches `channels.html`.
  A header search box that jumps to it can follow later, cheaply, once the page exists.
- **O5 — `vectorSearch` is not surfaced in the UI.** It is an operational detail; a user
  cannot act on it. It stays in the payload for debugging and in the Engine log.
- **O6 — task 10 is this feature's first task, not a new one.** Task 10 "Video search page"
  already exists, is already `[M2][F10]`, and already describes this work. Sync attaches it
  under the page issue and allocates new IDs only for the parts it does not cover.

### Out of scope

- Ranking and fusion changes. That is an `F6-M3` follow-up; this feature must not smuggle
  scoring tweaks into a UI change, or neither can be judged.
- Search filters beyond `sort`: instance, language, duration, date range. Each needs a
  gateway allowlist entry and an Engine parameter that does not exist.
- A header search box on every page, and search-as-you-type suggestions.
- Saved searches, search history, result thumbnails preloading.
- Any change to `videos.css` beyond what the card extraction requires.

### Dependencies and overlaps

- **`F6-M3` I4/I5 must be deployed**, which they are: the route answers through the gateway
  and the gateway allowlist already carries it. No Engine change is needed by this feature.
- **The dataset must have been synced** since `videos_fts` was added, or every search
  answers 503. It has been, on this deployment.
- **S1 touches `pages/videos/index.ts`**, the feed page. A regression there is visible on
  the home page, so the extraction is verified by rendering the feed before and after.
- **Task 10's text is superseded in part.** It still says "SQLite FTS5, fallback to LIKE",
  which describes the server half that `F6-M3` delivered without a LIKE fallback. Sync
  rewrites it to the UI-only scope with concrete steps.
- **No overlap with `F12-M2`** (like/dislike): search cards are the shared card component,
  and if like controls are added to cards later they land in one place for both pages.

### Draft decomposition

| Issue | Title | Indicative tasks |
|---|---|---|
| I1-F10-M2 | Shared video-card component | Move `renderCard` and its helpers from `pages/videos/index.ts` into `components/video-card.ts`; export a typed `renderVideoCard(row)`; re-point the videos page at it; confirm the feed renders identically |
| I2-F10-M2 | Search data client | `data/search.ts` with `fetchSearchResults`; `SearchPayload` and `SearchRow` types; cache TTL matching the channels client; only the four allowlisted query parameters |
| I3-F10-M2 | Search page | `search.html` with the standard CSP head and nav; `pages/search/index.ts` with input, sort control, results grid, count, "Load more"; `search.css` or a reused grid from `videos.css`; URL state; idle/loading/empty/error/503 states; `requestSeq` guard |
| I4-F10-M2 | Reachability and build wiring | `Search` nav link on the four existing pages; fifth rollup input in `vite.config.ts`; `/search` dev and preview rewrites; `DEPLOYMENT.md` note that the new page needs a rebuild and rsync |

Task **10** attaches under `I3-F10-M2`. New numeric IDs come from `task_count` in
`dev/map/DEV_MAP.json` at sync time (currently 91, so the first new task is 92).

### Acceptance criteria

1. `/search?q=<term>` renders a grid of video cards for a term with known matches, each
   linking to the existing video page with the same parameters the feed uses.
2. The cards on `/search` and the cards on the home feed are produced by the same module,
   and the home feed renders identically to before the extraction.
3. Changing the sort control re-queries and reorders the results; all four API values work.
4. "Load more" appends the next page without duplicating or skipping rows, and disappears
   once `total` is reached.
5. Reloading a result URL reproduces the same query, sort and page; the back button returns
   to the previous result set.
6. A query with no matches shows an explicit empty state naming the term, not an empty grid.
7. With the Engine stopped, the page shows an error state rather than hanging or throwing.
8. Against an Engine whose dataset has no `videos_fts`, the 503 renders as "search is not
   ready yet" rather than a generic failure.
9. Typing quickly does not render results for a stale query.
10. A video whose title or channel name contains HTML renders that text literally; no
    markup is injected.
11. The page is reachable in three clicks or fewer from the home page, without typing a URL.
12. `npm run build` produces `search.html` in `dist/`, and `/search` resolves in dev,
    preview and production routing.
13. `tests/check-frontend-client-gateway.sh` and `tests/check-client-engine-boundary.sh`
    pass: the page calls the gateway origin, never the Engine.

### Risks

- **R1 — the card extraction is the real risk, not the new page.** `renderCard` reads from
  a page-local cache (`resolveCachedStats`), a debug renderer and several closures over
  module state. Moving it means deciding what is card-intrinsic and what is feed-specific;
  getting that wrong breaks the home page, which is the most visible surface in the app.
  Mitigation: the component takes a plain row plus optional stats, and the feed keeps its
  own caching around the call.
- **R2 — XSS at a new sink.** Search renders attacker-influenced text (remote titles,
  channel names) into HTML, exactly like the feed. Every interpolation goes through
  `escapeHtml`, every external URL through `safeExternalUrl`, and criterion 10 tests it.
- **R3 — search looks monolingual.** Per O1 this is expected and accepted, but it is the
  first thing anyone will notice. Stated here so it is not mistaken for a page bug.
- **R4 — gateway rejects unknown parameters with 400.** Any future filter needs the
  allowlist updated in the same change set, or it fails in a way that looks like a frontend
  bug.
- **R5 — stale `dist/`.** Production serves rsynced static files; a new page that is not
  rebuilt and copied 404s under `try_files`. Covered by S8 and criterion 12.
- **R6 — `total` is a candidate count, not a corpus count.** It counts the fused pool,
  capped by the Engine's candidate pool, so "N results" can understate a broad query and
  "Load more" ends at the pool boundary. The UI wording must not promise a corpus count.

### Validation strategy

- Build: `npm run build` in `client/frontend`, asserting `dist/search.html` and its asset.
- Contract: `tests/check-frontend-client-gateway.sh`, `tests/check-client-engine-boundary.sh`.
- Feed regression: render the home feed before and after S1 and compare card markup for a
  fixed row set.
- Escaping: a fixture row whose title contains `<img src=x onerror=...>` asserts literal
  rendering (criterion 10).
- States: exercise empty, error and 503 by pointing the page at a stopped Engine and at a
  database without `videos_fts`.
- Manual, in the operator's browser: criteria 1, 3, 4, 5 and 11 against the live dataset.

### Rollback notes

- The page is additive: deleting `search.html`, `pages/search/`, `data/search.ts` and the
  nav links restores the previous surface exactly.
- The card extraction is the one part that is not additive. It is a pure move, so reverting
  it is reverting one commit, but anything built on the shared component afterwards would
  have to come back with it.
- No Engine, gateway, database or nginx change is involved, so nothing here can affect
  data or the API surface.
