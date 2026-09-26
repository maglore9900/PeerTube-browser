# Likes and dislikes

Status: delivered (server half: Engine and Client backend), harvested. The frontend half is `docs/project/plans/08-likes-dislikes-frontend.md`. Adopted as WORKING_FILE at Step 1. Blocks, the other half of the original plan 03, were delivered by `docs/project/plans/archive/07-channel-blocks.md`. The planning-time text this file carried before Step 1 is in git history; where it differs from the Requirements below, the Requirements win.

## Requirements

Confirmed by the operator at Step 1 ("confirmed").

### What was asked

"lets implement the dislike feature." Widened at Step 1 (Q1 "both") to include plan 03's like fixes S1-S4, and (Q6 "full") to absorb issue 15.

### Purpose

Make the like and dislike state honest and visible, and let a visitor shape their own feed with a soft negative signal: a dislike removes that video and pushes similar videos down, for that visitor only. A profile holder's likes and dislikes live server-side, so the browser does not send them with every request (operator, Q3: "what I want to avoid is unnecessary sending of data from the client to the server").

### Current state (read at Step 1)

- **Dislike does nothing.** `client/frontend/src/pages/video-page/index.ts:75` toggles a CSS class only: no storage, no request, no ranking effect.
- **The backend maps `dislike` to un-like.** `client/backend/server.py:635` accepts `action` `dislike`; `:670` publishes `UndoLike` for it and `:686` removes the profile's like. No UI sends it.
- **Like state is not honest.** The like button renders inactive after reload; `handleLikeAction` (`video-page/index.ts:1068`) stores the like in `localLikes:v1` in `finally`, so a failed request still stores it and the failure goes only to `console.warn`; clicking an active like clears the class and sends nothing.
- **Likes are local-first.** `localLikes:v1` (cap 50, `data/local-likes.ts`) is the source of truth. `fetchSimilarVideosPayload` (`data/videos.ts:80`) POSTs 5 random likes in every feed body; the Engine uses them as similarity seeds and excludes them from results (`engine/server/api/recommendations/mixer.py:119`). The My likes modal reads `localLikes:v1` (`data/user-profile.ts:15`, `USE_LOCAL_LIKES_PROFILE = true`). With a key, `users.db` `likes` holds a copy (cap `MAX_LIKES` = 100, `server.py:43`) that no feed reads.
- **Scoring.** A candidate's score is `similarity_weight·similarity + freshness + popularity + layer_bonus` (`engine/server/api/recommendations/scoring.py:55`). Embeddings are 384-dimensional (`paraphrase-multilingual-MiniLM-L12-v2`).
- **Blocks precedent.** The Client proxy already resolves an optional key on `/recommendations`, `/videos/similar` and search, over-fetches twice the page for a profile with blocks, and filters rows by identity (`server.py` `_block_filter`, `_proxy_engine_request`).

### Acceptance criteria

Likes (plan 03 S1-S4, issue 15):
- **L1.** On load, the video page shows the like as active when the video is liked: from `users.db` with a key, from `localLikes:v1` without one.
- **L2.** An active like is unmistakable: a filled icon and a label change ("Liked"), plus an in-flight state while the request is outstanding.
- **L3.** A like whose request fails leaves the button inactive, shows an error on the page, and stores nothing.
- **L4.** Clicking an active like removes it from the source of truth and emits `UndoLike`.
- **L5.** With a key, `users.db` is the source of truth for likes. The browser sends no `likes` in feed bodies, and the Client injects the profile's likes into the Engine request in the shape the Engine accepts today. Without a key, behaviour is unchanged.
- **L6.** When a key is present and `localLikes:v1` holds entries, the frontend imports them into the profile once, then clears the local store.
- **L7.** The My likes modal lists the source of truth, and each card has a remove control that behaves as L4 (issue 15).

Dislikes (plan 03 S5, S6):
- **D1.** Dislike needs a profile. Without a key, the dislike control prompts the visitor to create one. Dislikes are stored in `users.db`, at most 1,000 per profile. No global Dislike event is emitted (O5).
- **D2.** The video page offers dislike and un-dislike. The active state survives reload and follows the L2 and L3 rules.
- **D3.** Like and dislike are mutually exclusive per video. Disliking a liked video removes the like and emits `UndoLike`; liking a disliked video removes the dislike.
- **D4.** When a profile's dislikes change, the Client obtains from a stateless Engine endpoint up to four centroids (k-means over the disliked videos' embeddings, k = min(4, n)) and stores them in `users.db`.
- **D5.** On home and up-next feeds for that profile, the Client passes the centroids to the Engine over the internal hop, and the Engine subtracts `similarity_weight × max cos(candidate, centroid)` from each candidate's score before ranking. The browser's request does not grow.
- **D6.** Disliked videos are absent from that profile's home, random and up-next feeds, removed by the Client proxy by exact identity. Search is not filtered.
- **D7.** Feed pages stay full under dislikes, using the existing over-fetch.
- **D8.** One profile's likes and dislikes never change another visitor's feed.
- **D9.** Deleting a profile deletes its dislikes and centroids.

### In scope / out of scope

In scope: the Client backend (`server.py`, `lib/users_store.py`, `lib/profiles.py`, a dislike store module), one stateless Engine endpoint and the Engine's scoring for home and up-next, the frontend like and dislike controls, `data/local-likes.ts`, `data/user-actions.ts`, `data/user-profile.ts`, `data/videos.ts`, the My likes modal, and the docs.

Out of scope:
- Issue 01 (deterministic event ids, signal_score cap). It stays a separate fix (Q5 "separate"); Like and UndoLike are emitted as today.
- A random-feed down-rank toggle (plan 03 criterion 9, dropped at Q2). Random only excludes disliked videos.
- A taste vector for likes.
- Sending likes to the source instance (ActivityPub, roadmap `F4-M5`).
- Filtering search by dislikes.

### Consistency constraints

Backend matches `client/backend` style: stdlib `http.server`, `respond_json`, `sqlite3.Row`, module docstrings, `from __future__ import annotations`. Frontend matches `data/*.ts` (fetch through `resolveClientApiBase`, `profileHeaders`, `readErrorMessage`), and every rendered value is escaped or set with `textContent`. Engine matches `engine/server/api` handler and recommendations module style. Every `localLikes:v1` mutation stays in `data/local-likes.ts`. The Engine holds no user state. Backwards compatibility is not required.

### Conflicts

- **Plan 03 S6 ("vector search from disliked videos") and O3 (penalty magnitude open) against D4/D5.** Resolved by the operator at Q2 and Q3: a penalty from clustered centroids, `similarity_weight × max cos`, on home and up-next.
- **Plan 03 S1 ("read `localLikes:v1`") against L5.** Resolved at Q4: with a key, `users.db` is the source of truth.
- **`server.py:635` maps `dislike` to un-like, against D1-D3.** Replaced by this build.
- **Plan 03 criterion 16 (constant request size) against the internal hop.** The browser request stays constant; the Client-to-Engine request carries the centroids (about 6 KB) and the profile's likes.
- **Plan 03 split note: "it must settle issue 01 and issue 15 before it starts".** Settled: issue 01 stays separate (Q5); issue 15 is absorbed in full (Q6).

### Test trees for this build

- `active`: `tests/active`
- `working`: `tests/tmp`

### Baseline suite state

Step 0, `scripts/validate_tests.py` bare run: "unchanged since 2026-09-26T08:49:57-04:00 — every fingerprint still holds", 27 passed (25.2 s). Reused from the banked record. Green. `--compare`: "nothing moved against the previous record".

## High-level plan

Approved by the operator at Step 2 ("approve"), including the split in T1.

### Approach

- **A1. Engine centroid endpoint (D4).** A bridge-token route `POST /internal/dislikes/centroids` takes disliked video identities, loads their embeddings, runs a deterministically-initialised k-means with k = min(4, n), and returns normalised centroids tagged with the embedding-space id. It stores nothing.
- **A2. Engine penalty (D5).** `/recommendations` and `/videos/similar` accept an optional `dislike_centroids` body field. It is used only when it holds at most 4 finite vectors of the index dimension from the current embedding space; otherwise it is ignored. Home (in the mixer, after `score_candidate`) and up-next (before ranking in `score_and_rank_list`) subtract `similarity_weight × max cos(candidate, centroid)`, with candidate embeddings from one `fetch_embeddings_by_ids` batch. A similarity floor, calibrated from a measured distribution, leaves unrelated videos unpenalised. Random is unscored and is not penalised.
- **A3. Client dislike store (D1, D3, D9).** `dislikes` and `dislike_profiles` tables in `users.db`. `/api/user-action` gains `undo_dislike`. `dislike` and `undo_dislike` need a key (401 otherwise). `dislike` removes any like (emitting `UndoLike` when one existed), stores the dislike and recomputes the centroids through A1 in one transaction; an Engine failure stores nothing and answers 502. `like` removes any dislike. Profile deletion clears both tables.
- **A4. Client reaction state (L1, D2).** `GET /api/profile/reaction?uuid=&host=` returns `{liked, disliked}` from `users.db`, with no Engine call.
- **A5. Client proxy (L5, D5-D8).** For a keyed feed request the proxy replaces the body's `likes` with the profile's (a random five of its stored likes, as the browser does today) and adds `dislike_centroids`. The blocks filter also drops disliked videos on home, random and up-next (not search), and the proxy over-fetches when the profile has blocks or dislikes. The browser cannot send `dislike_centroids`: the body allowlist rejects it.
- **A6. Client like import (L6).** `POST /api/profile/likes/import` records a browser-supplied like list into the profile without emitting events, because those likes were published when they were made.
- **A7. Frontend (L1-L7, D1-D3) — follow-on plan 08.** `data/` modules for reactions, import and un-like; the video page's like and dislike controls with active, in-flight and error states and the no-profile prompt; `fetchSimilarVideosPayload` sends no likes when a key is held; the My likes modal reads the server with a key and has a remove control per card; the one-time import on load.

**Amended at Step 7 (Phase 1), operator-approved ("O2"):** on home, candidates carrying a dislike penalty are set aside while the mixer fills layer slots and are placed after every other candidate, so similar videos sink below the whole page rather than within their own layer. A probe showed the within-layer penalty alone left home unchanged whenever the dislike was close to what a like brings in (Phase 1, implementation triage). R2 is superseded by this.

### This build and plan 08

This build delivers A1-A6: D1 (store, 401), D3, D4, D5, D6, D7, D8, D9, and the server halves of L1 (A4), L4 (un-like via `undo_like`, existing), L5, L6 and L7 (the routes). Plan 08 delivers A7 against these routes: L1-L3 and D2 on the page, L5's browser half, L6's trigger, L7's modal, and D1's prompt.

### Alternatives

- **Per-dislike neighbour penalties.** Rejected at Q3: cost grows with the number of dislikes.
- **Centroids computed in the Client.** Rejected: the Client has no embeddings.
- **Dislike ids sent per request and clustered on every request.** Rejected: the internal request grows and every feed pays for the k-means.
- **An Engine-side dislike store.** Rejected: gives the Engine user state (plan 03 R9, the blocks decision).
- **Disliked videos excluded in the Engine.** Rejected: the Client already has the ids and the filter path; the Engine would need the ids on every request.
- **A global Dislike event.** Rejected by O5.

### Risks

- **R1. Embedding-space change.** After a re-embed, stored centroids are in the old space. The Engine ignores centroids whose space id differs, so the penalty lapses until the profile's next dislike change. Accepted: re-embeds are rare.
- **R2. Calibration.** Cosine similarity between unrelated videos is not zero; without the floor every candidate is penalised a little. The floor is set from a measured distribution at Step 7. The mixer ranks within layers, so the penalty sinks a video within its layer rather than removing it.
- **R3. Dislike latency.** Each dislike or un-dislike costs one Engine round trip (k-means over at most 1,000 × 384).
- **R4. Likes move server-side for key holders.** A lost key now loses likes as well; before, they survived in localStorage.
- **R5. Up-next near a dislike.** Opening a video similar to one's dislikes penalises its own neighbours. Accepted as the intended effect.
- **R6. Proxy work.** For a visitor with likes, dislikes or blocks, every feed request adds a `users.db` read and a JSON rewrite.

### Tradeoffs accepted

- **T1.** Two plan files: this build (Engine and Client backend, A1-A6) and follow-on plan 08 (frontend, A7).
- **T2.** Dislikes need a profile; likes do not.
- **T3.** Search is not filtered by dislikes; the random feed only excludes.
- **T4.** Issue 01 stays open; the un-like paths add `UndoLike` emissions.

## Impacts

### E1 Engine dislike-profile module (NEW)
- **path:** `engine/server/api/recommendations/dislike_profile.py`
- **Changes:** new. `compute_centroids(vectors, k)`, a deterministic k-means (farthest-point initialisation, fixed iterations) returning at most 4 normalised centroids; `dislike_penalty(candidates, centroids, embeddings, weight, floor)`, which subtracts `weight × max(0, max cos − floor)`-style penalty from each candidate's `score` (exact form fixed at Step 5).
- **Depends on it:** E2 (endpoint), E4 (mixer), E5 (up-next).
- **Regression risk:** medium. It defines the ranking effect. Pattern precedent: `related_personalization.py` (`_normalize_vector`, `_max_similarity`, embeddings via `fetch_embeddings_by_ids` under `db_lock`).

### E2 Engine centroid endpoint and route
- **path:** `engine/server/api/handlers/similar.py` (`_dispatch_post`, line 345)
- **Changes:** `/internal/dislikes/centroids` added beside `/internal/videos/resolve`. It is bridge-token-guarded by the existing `url.path.startswith("/internal/")` check. The handler lives in `engine/server/api/handlers/internal_client_reads.py` (see E3).
- **Depends on it:** Client E11.
- **Regression risk:** low. A new route.

### E3 Engine internal handler
- **path:** `engine/server/api/handlers/internal_client_reads.py`
- **Changes:** `handle_internal_dislike_centroids`. Validates `entries` as `(video_id, instance_domain)` pairs (at most 1,000), loads embeddings with `fetch_embeddings_by_ids` under `server.db_lock`, and answers `{ok, space, centroids}`. Videos with no embedding are skipped; none at all gives `centroids: []`.
- **Depends on it:** E2.
- **Regression risk:** low.

### E4 Engine request parsing and context
- **path:** `engine/server/api/handlers/similar.py` (`_handle_similar_request`, lines 525-568); `engine/server/api/request_context.py`
- **Changes:** reads an optional `dislike_centroids` body field. It is accepted only as `{space, vectors}` with `space` equal to the running space and at most 4 finite vectors of `embeddings_dim`; anything else is ignored. The result goes into request context beside the client likes. `clear_request_context` clears it.
- **Depends on it:** E5, E6. `engine/server/api/tests/test_recommendations_likes_limit.py` patches `set_request_client_likes` and asserts its call; the new parsing must not change that call.
- **Regression risk:** low. Body size: `DEFAULT_CLIENT_LIKES_BODY_LIMIT` = 65,536 bytes (`server_config.py:379`). Four 384-float vectors at full float repr are about 30 KB, inside the limit, but only if the Client rounds (E13).

### E5 Engine mixer (home)
- **path:** `engine/server/api/recommendations/mixer.py` (`MixerDeps`, `_soft_mix_candidates` lines 316-326)
- **Changes:** after `score_candidate` for the pool, when the request carries centroids, one `fetch_embeddings_by_ids` over the pool and the penalty from E1, applied before the per-layer sort at line 355. `MixerDeps` gains `fetch_embeddings_by_ids` and `fetch_dislike_centroids`; `generate_recommendations` passes `server` down.
- **Depends on it:** every home request. With no centroids it is a no-op.
- **Regression risk:** high. The ranking pipeline. The pool is `batch_size × overfetch_factor` candidates, up to 96 × factor, so the embedding batch is a few hundred rows.

### E6 Engine up-next
- **path:** `engine/server/api/handlers/similar.py` (`_handle_seed_with_embedding`, lines 699-705); `engine/server/api/recommendations/scoring.py` (`score_and_rank_list`, line 151)
- **Changes:** the penalty sits between scoring and `rank_scored_candidates`, so that the explore/exploit split and the jitter see penalised scores. `score_and_rank_list` gains an optional adjust step, or the handler scores and ranks in two calls (decided at Step 5).
- **Depends on it:** every up-next request.
- **Regression risk:** medium.

### E7 Engine wiring and config
- **path:** `engine/server/api/server.py` (`SimilarServer.__init__` line 203; `main` lines 342, 379-401); `engine/server/api/recommendations/builder.py` (`MixerDeps` construction, line 193); `engine/server/api/server_config.py`
- **Changes:** `SimilarServer` keeps `embeddings_model` (the space id; today it is logged at line 343 and dropped). The builder passes `fetch_embeddings_by_ids` and the context reader into `MixerDeps`. Config gains `DISLIKE_MAX_CENTROIDS` = 4, `DISLIKE_MAX_ENTRIES` = 1000 and `DISLIKE_SIMILARITY_FLOOR` (value from the Step 7 probe).
- **Regression risk:** low.

### E8 Client user schema
- **path:** `client/backend/lib/users_store.py` (`ensure_user_schema`)
- **Changes:** `dislikes` (`profile_id`, `video_id`, `instance_domain`, `video_uuid`, `created_at`, primary key `(profile_id, video_id, instance_domain)`) and `dislike_profiles` (`profile_id` primary key, `space`, `centroids` JSON, `updated_at`).
- **Depends on it:** `server.py` `main`, `tests/active/conftest.py` (calls `ensure_user_schema`).
- **Regression risk:** low. `CREATE TABLE IF NOT EXISTS`.

### E9 Client dislike store (NEW)
- **path:** `client/backend/lib/dislikes.py`
- **Changes:** `MAX_DISLIKES` = 1000, `DislikeLimitReached`, `add_dislike`, `remove_dislike`, `list_dislike_entries`, `load_dislike_keys` (the `(video_uuid, instance_domain)` set the filter needs), `store_centroids`, `load_centroids`, `filter_disliked`. Follows `lib/blocks.py`.
- **Depends on it:** E12-E16.
- **Regression risk:** medium. It defines what a match is.

### E10 Client profile deletion
- **path:** `client/backend/lib/profiles.py` (`delete_profile`, line 69)
- **Changes:** also deletes `dislikes` and `dislike_profiles` rows in the same transaction.
- **Depends on it:** `POST /api/profile/delete`; `tests/active/test_profiles.py:192` counts `profiles`, `users` and `likes` only, so it stays green.
- **Regression risk:** low.

### E11 Client Engine API client
- **path:** `client/backend/lib/engine_api_client.py`
- **Changes:** `compute_dislike_centroids(engine_base_url, entries)` over `_post_json`, raising `EngineApiError` on a non-200 or malformed body.
- **Regression risk:** low.

### E12 Client user action
- **path:** `client/backend/server.py` (`_handle_user_action`, lines 627-716)
- **Changes:**
  - Actions become `like`, `undo_like`, `dislike`, `undo_dislike`.
  - `dislike` and `undo_dislike` take the key through `_require_profile` (the same 401).
  - `dislike`: resolve; compute the centroids over the new set (Engine call); then, in one `users.db` transaction, remove any like, insert the dislike, store the centroids. Publish `UndoLike` only when a like was removed; publish nothing otherwise (O5). The Engine failing stores nothing and answers 502.
  - `undo_dislike`: the same recompute and transaction without the like. An empty set stores no centroids.
  - `like` with a key also removes any dislike, and recomputes the centroids when one was removed.
  - Today `dislike` publishes `UndoLike` and removes the like unconditionally (lines 670, 686); that is replaced.
- **Depends on it:** the frontend's `sendUserAction` (`data/user-actions.ts`, `action: "like"` only today); `tests/run-arch-split-smoke.sh:592` and `tests/run-installers-smoke.sh:658` (keyless like, still 200).
- **Regression risk:** high. The write path, with an Engine call inside, and the event-emission rules.

### E13 Client read proxy
- **path:** `client/backend/server.py` (`_block_filter` lines 347-371, `_handle_engine_read_proxy_post` lines 373-448, `_proxy_engine_request` line 450, `_filter_payload` line 870, constants lines 50-84)
- **Changes:**
  - `_block_filter` becomes a per-profile filter returning blocks, disliked keys, the profile's likes and centroids.
  - On a feed route with a resolved profile, the POST body's `likes` is replaced by a random `DEFAULT_CLIENT_LIKES_MAX` (5) of the profile's stored likes, and `dislike_centroids` (rounded to 6 decimals) is added after sanitising, so the browser cannot supply it.
  - `_filter_payload` also drops disliked videos, on the feed routes only.
  - The over-fetch applies when the profile has blocks or dislikes.
- **Depends on it:** every feed and search request; `tests/active/test_blocks.py` (filtering, over-fetch); `tests/run-arch-split-smoke.sh` (keyless feeds, pass-through).
- **Regression risk:** high. Every read goes through it.

### E14 Client reaction route
- **path:** `client/backend/server.py` (`do_GET`, line 198)
- **Changes:** `GET /api/profile/reaction?uuid=&host=`, rate-limited, behind `_require_profile`, answering `{liked, disliked}` from `users.db` by `(video_uuid, instance_domain)`. `uuid` and `host` are validated like the block routes (non-empty, at most 200 characters).
- **Regression risk:** low. A new route.

### E15 Client like import route
- **path:** `client/backend/server.py` (`do_POST`, line 248)
- **Changes:** `POST /api/profile/likes/import` with `{likes: [{uuid, host}]}` (at most `MAX_CLIENT_LIKES`, reusing `_parse_client_likes`). Resolves through `resolve_videos_by_uuid_host`, records each with `record_like`, emits no event, and answers `{imported}`. Behind `_require_profile` and the rate limiter. A liked video that the profile has disliked is skipped (D3).
- **Depends on it:** plan 08's import trigger.
- **Regression risk:** low. A new route. `resolve_videos_by_uuid_host` makes one Engine call per like (at most 200).

### E16 Existing durable tests
- **path:** `tests/active/test_blocks.py`, `tests/active/test_profiles.py`, `tests/active/test_similar.py`, `tests/active/test_frontend_blocks.py`, `tests/active/test_frontend_profile.py`, `engine/server/api/tests/test_recommendations_likes_limit.py`
- **Changes:** none planned. `test_blocks.py` exercises the proxy E13 rewrites and is the regression net for it. `test_frontend_blocks.py` bundles `data/videos.ts`, which sends browser likes; with a key the Client now replaces them, which those tests do not observe.
- **Regression risk:** medium, through E13.

### E17 Frontend (unchanged in this build)
- **path:** `client/frontend/src/data/videos.ts`, `client/frontend/src/data/user-actions.ts`, `client/frontend/src/pages/video-page/index.ts`
- **Changes:** none; plan 08. Until then a keyed browser still sends `likes`, and the Client replaces them with the profile's. The dislike button stays cosmetic.
- **Regression risk:** low. Behaviour change for keyed visitors: feed seeds come from their server-side likes (the copies made while keyed), not `localLikes:v1`.

### E18 Split and installer smoke tests
- **path:** `tests/run-arch-split-smoke.sh`, `tests/run-installers-smoke.sh`
- **Changes:** none planned. Both send a keyless `like`, which is unchanged. Checked at Step 8.
- **Regression risk:** low.

### E19 Documentation
- **path:** `DEPLOYMENT.md` (line 253 user-action paragraph; line 261 boundary list), `client/README.md` (routes, lines 11-36), `README.md` (boundary table, lines 47-49), `engine/server/README.md` (internal routes, lines 10-12), `CONTEXT.md` (glossary), `engine/server/api/recommendations/docs/LAYER_PARAMS.md` (scoring), `docs/project/roadmap.md` (F12-M2, lines 40, 133-136), `docs/project/issues/15-remove-single-like.md`.

### E20 Engine up-next personalization (found at Step 4)
- **path:** `engine/server/api/recommendations/related_personalization.py` (`rerank_related_videos`, line 79)
- **Changes:** the final score becomes `alpha × base + beta × user_score − (1 − alpha) × dislike_penalty`, where `base` is the candidate's `score` (already penalised) and `dislike_penalty` is the value E1 recorded on the candidate (0 when absent). The two terms add up to the full penalty. Without this, the rerank (enabled, `alpha` 0.2, `beta` 0.8, `server_config.py:283`) cuts the penalty to a fifth whenever the visitor has likes.
- **Depends on it:** every up-next request with likes.
- **Regression risk:** low. Without dislikes the penalty is 0 and the order is unchanged.

### E21 Engine recommendation docs (found at Step 4)
- **path:** `engine/server/api/recommendations/docs/OVERVIEW.md`, `engine/server/api/recommendations/docs/PIPELINE_DIAGRAM.md`
- **Changes:** checked at Step 9 for their description of scoring; added to the docs checklist.

### Highest risk

- **E13 read proxy.** Every feed and search request passes through it, and this build adds body rewriting to the path blocks already filter.
- **E5 mixer penalty.** It changes home ranking, and the size of the effect depends on the floor, which is not yet measured.
- **E12 user action.** It orders an Engine call, a `users.db` transaction and an event publish; a wrong order either stores a dislike with stale centroids or publishes an `UndoLike` for a like that stayed.

### Reassessment

#### Pass 1

**1. Will it still work as intended?** On home, yes. On up-next, only partly: `rerank_related_videos` re-sorts after ranking by `0.2 × score + 0.8 × like-similarity`, so a penalty on `score` keeps a fifth of its weight whenever the visitor has likes.

**2. Ramifications.** Keyed visitors' feed seeds come from their server-side likes. Home and up-next add one embedding batch per request. Dislike and un-dislike add one Engine call each.

**3. What else must happen.** The new body parsing in `_handle_similar_request` must not read `self.server.embeddings_dim` when no `dislike_centroids` is present: `engine/server/api/tests/test_recommendations_likes_limit.py` drives that method with a `SimpleNamespace(use_client_likes=True)` server.

**4. How the original functionality is altered.** `action: "dislike"` stops meaning un-like and requires a key. Keyed feed requests ignore the browser's `likes`.

**Entries the files did not bear out.** None. Checked: `like_key` and `fetch_embeddings_by_ids` share the `video_id::instance_domain` key (`recommendations/keys.py:16`, `data/embeddings.py:303`); the Engine's `read_json_body` accepts up to 1,000,000 bytes, enough for 1,000 entries; the feed body limit (65,536) holds rounded centroids.

**New impacts.** E20, E21.

**Approved by the operator:** E20 as full-weight ("full-weight"): the rerank subtracts each candidate's recorded penalty at full weight.

#### Pass 2

E1, E5, E6 and E20 re-read together. The penalty is computed once per candidate (E1), stored on it as `dislike_penalty`, and subtracted from `score` before ranking (E5, E6). The rerank's base already carries `alpha × penalty`, so E20 subtracts only the remaining `(1 − alpha) × penalty`; E20's entry was corrected to say so. No new impact and no unconfirmed entry. Steps 3-4 converged.

### Documentation to update

Step 9, each against what landed:
- [x] `DEPLOYMENT.md` — **updated.** The profile-routes sentence names the reaction and import routes and the dislike actions. A new paragraph covers likes and dislikes in `users.db`, their mutual replacement, the 1,000 cap, no event for a dislike, the centroid round trip, keyed feeds carrying the profile's likes and taste vectors, dislike exclusion with over-fetch, search unfiltered, and taste vectors lapsing after a model change. The boundary list gains `/internal/dislikes/centroids`.
- [x] `client/README.md` — **updated.** The `/api/user-action` entry lists the four actions and their rules; the reaction and import routes are added; deletion names dislikes and taste vectors; the 401 sentence covers the new routes; the read-gateway bullet adds dislike exclusion on feeds; a bullet covers the keyed feed's likes and taste vectors; the internal contract gains the centroid route.
- [x] `README.md` — **updated.** The write/profile row names reactions and the likes import; the read-gateway row adds dislike filtering and the likes and taste vectors keyed feeds carry; the internal-contract row adds `/internal/dislikes/centroids`.
- [x] `engine/server/README.md` — **updated.** The centroid route, and dislike centroids read from request input.
- [x] `CONTEXT.md` — **updated.** Dislike and Taste vector defined; Profile names dislikes. The Block entry said a dislike "only down-ranks similar videos", which this build made false; it now says a dislike removes one video and down-ranks similar ones (**inventory gap**: found at 9.1).
- [x] `engine/server/api/recommendations/docs/LAYER_PARAMS.md` — **updated.** The penalty and the floor, and penalised candidates placed after the rest.
- [x] `engine/server/api/recommendations/docs/OVERVIEW.md` — **updated.** § 5 describes the penalty; § 6 describes the O2 placement.
- [x] `engine/server/api/recommendations/docs/PIPELINE_DIAGRAM.md` — **updated.** Nodes J2 (penalty) and K3 (placement).
- [x] `docs/project/roadmap.md` — **updated.** F12-M2 points at plan 08; Delivered lists the server half. Implementation order: step 1's issue-01-before-I2 constraint removed (Q5); the identity step (delivered by plan 06), like correctness and filter-profile steps replaced by plan 08; saved channels and feed paging restated against what exists.
- [x] `docs/project/issues/15-remove-single-like.md` — **updated.** Related says where each half lives and that it closes with plan 08; a comment records Q6.
- [x] `docs/project/issues/01-deterministic-event-ids.md` — **updated** (**inventory gap**: found at 9.1). Its "must land before the un-like path" was contradicted by Q5; it now says the un-like paths shipped without it and that its fix must cover `UndoLike`.
- [x] `docs/project/plans/08-likes-dislikes-frontend.md` — **written.** The follow-on feature file T1 approved, holding L1-L7 and the page halves of D1-D3.
- **No update:**
  - `docs/project/plans/04-feed-parameter-panel.md`: its references to plan 03's I4/I5 were already superseded by plan 07's storage decision, and nothing it states became false in this build.
  - Issue 01's `_handle_client_publish_event` name predates this build.
  - `docs/wiki/` and `docs/project/adr/` do not exist.
- No ADR is contradicted.

## Implementation plan

### Draft (Step 5)

#### What this build must test

- **T1.** The centroid endpoint returns at most four unit vectors, k = min(4, n), each disliked video lying close to one of them; the same input gives the same output.
- **T2.** Given centroids, the Engine ranks videos similar to a disliked one lower on home and up-next than without them, and leaves the order unchanged without them.
- **T3.** `/api/user-action` `dislike` / `undo_dislike`: the key rule (401), the stored state, like removal, and the centroids kept in step with the set.
- **T4.** The proxy: disliked videos absent from the profile's home, random and up-next pages, the page still full, other visitors unaffected; the centroids reach the Engine; the profile's likes replace the browser's.
- **T5.** The reaction and import routes.
- **T6.** Profile deletion removes dislikes and centroids.

#### Engine

`engine/server/api/recommendations/dislike_profile.py` (NEW)
```python
"""A visitor's dislikes as up to four taste centroids, and the ranking penalty they give."""
MAX_CENTROIDS = 4
KMEANS_ITERATIONS = 20

def compute_centroids(vectors: np.ndarray, k: int = MAX_CENTROIDS) -> np.ndarray
    # rows L2-normalised; k = min(k, n). Farthest-point init from row 0 (deterministic),
    # then assign each row to its highest-cosine centroid and replace each centroid by the
    # normalised mean of its rows; an empty cluster keeps its centroid. Returns (k, dim).

def apply_dislike_penalty(server, candidates, centroids, weight, fetch_embeddings_by_ids,
                          floor) -> None
    # No-op when centroids is None or candidates empty. One fetch_embeddings_by_ids batch
    # under server.db_lock; for each candidate with an embedding, s = max cos to centroids;
    # when s >= floor: candidate["dislike_penalty"] = weight * s and score -= that.
```
Invariant: without centroids no candidate is touched, so every existing request ranks exactly as before.

`engine/server/api/server_config.py`
```python
# Dislike taste vector: at most this many disliked videos per centroid request.
DISLIKE_MAX_ENTRIES = 1000
# Cosine similarity below which a candidate is not penalised (set from the Step 7 probe).
DISLIKE_SIMILARITY_FLOOR = <measured>
```

`engine/server/api/handlers/internal_client_reads.py`
- The entry parsing in `handle_internal_videos_metadata` moves into `_parse_entries(raw) -> list[dict] | None`, shared with the new handler.
- `handle_internal_dislike_centroids(handler, server)`: `entries` required, at most `DISLIKE_MAX_ENTRIES` (else 400); embeddings through `fetch_embeddings_by_ids` under `db_lock`; answers `{"ok": True, "space": server.embeddings_model, "centroids": [[round(x, 6), ...], ...]}`, `[]` when no entry has an embedding.

`engine/server/api/handlers/similar.py`
- `_dispatch_post`: `/internal/dislikes/centroids` → the handler (bridge token already enforced for `/internal/`).
- `_parse_dislike_centroids(raw, space, dim) -> np.ndarray | None`: a dict whose `space` equals the running space and whose `vectors` is 1-4 lists of `dim` finite numbers; normalised; anything else None. Called in `_handle_similar_request` only when the body holds the key, reading `space` and `dim` with `getattr`, so the existing unit test's bare server is untouched.
- `set_request_dislike_centroids(...)` beside `set_request_client_likes`.
- `_handle_seed_with_embedding`: `score_and_rank_list(..., adjust=penalise)`, where `penalise` calls `apply_dislike_penalty` with the up-next profile's `similarity_weight`.

`engine/server/api/request_context.py`: `set_request_dislike_centroids`, `fetch_request_dislike_centroids`, and `clear_request_context` clears it.

`engine/server/api/recommendations/scoring.py`: `score_and_rank_list(..., adjust: Callable[[list[dict]], None] | None = None)` calls `adjust(candidates)` after scoring and before `rank_scored_candidates`.

`engine/server/api/recommendations/mixer.py`
- `MixerDeps` gains `fetch_embeddings_by_ids` and `fetch_dislike_centroids: Callable[[], np.ndarray | None]`.
- `generate_recommendations` passes `server` to `_soft_mix_candidates`, which after its scoring loop calls `apply_dislike_penalty(server, pool, self.deps.fetch_dislike_centroids(), settings.similarity_weight, self.deps.fetch_embeddings_by_ids, DISLIKE_SIMILARITY_FLOOR)`.

`engine/server/api/recommendations/related_personalization.py`: `final_score = alpha * base + beta * user_score - (1 - alpha) * float(candidate.get("dislike_penalty") or 0.0)`.

`engine/server/api/recommendations/builder.py`: `MixerDeps(..., fetch_embeddings_by_ids=deps.fetch_embeddings_by_ids, fetch_dislike_centroids=fetch_request_dislike_centroids)` — the reader is injected like `fetch_recent_likes`.

`engine/server/api/server.py` `main`: `server.embeddings_model = embeddings_model` after construction, as `recommendation_strategy.settings` is set at line 402.

#### Client store

`client/backend/lib/users_store.py` (`ensure_user_schema` gains):
```sql
CREATE TABLE IF NOT EXISTS dislikes (
  profile_id TEXT NOT NULL,
  video_id TEXT NOT NULL,
  instance_domain TEXT NOT NULL,
  video_uuid TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  PRIMARY KEY (profile_id, video_id, instance_domain)
);
CREATE TABLE IF NOT EXISTS dislike_profiles (
  profile_id TEXT PRIMARY KEY,
  space TEXT NOT NULL,
  centroids TEXT NOT NULL,
  updated_at INTEGER NOT NULL
);
```
`remove_like` returns whether a row was deleted and stops committing; its one caller already wraps it in `with self.server.user_db:`.

`client/backend/lib/dislikes.py` (NEW)
```python
MAX_DISLIKES = 1000
class DislikeLimitReached(Exception): ...

def dislike_entries(conn, profile_id) -> list[dict]           # video_id, instance_domain
def is_disliked(conn, profile_id, video_id, instance_domain) -> bool
def write_dislike(conn, profile_id, video: dict, centroids: dict | None) -> None
    # INSERT OR IGNORE the dislike; store or clear the centroids. No commit: the caller's
    # transaction also holds the like removal.
def delete_dislike(conn, profile_id, video_id, instance_domain, centroids: dict | None) -> bool
def load_centroids(conn, profile_id) -> dict | None           # {"space", "vectors"}
def load_disliked_keys(conn, profile_id) -> set[tuple[str, str]]  # (video_id, instance_domain)
def filter_disliked(rows, keys) -> list[dict]
```

`client/backend/lib/profiles.py` `delete_profile` deletes `dislikes` and `dislike_profiles` in its transaction.

`client/backend/lib/engine_api_client.py`: `compute_dislike_centroids(base, entries) -> dict | None` (`{"space", "vectors"}`, None for an empty result), raising `EngineApiError` on a non-200 or malformed body.

#### Client server

`client/backend/server.py`
- **Constants.** `ENGINE_FEED_LIKES_MAX = 5` (`rat-tail:` mirrors the Engine's `DEFAULT_CLIENT_LIKES_MAX`). The user-action set becomes `USER_ACTIONS = {"like", "undo_like", "dislike", "undo_dislike"}`.
- **`_handle_user_action`.**
  - `dislike`/`undo_dislike`: `_require_profile` first (401), then resolve.
  - The new dislike set is computed; `dislike` of a new video at `MAX_DISLIKES` → 400.
  - `compute_dislike_centroids` runs before any write; an `EngineApiError` → 502 and nothing stored.
  - Then one `with self.server.user_db:`: `dislike` removes any like (`remove_like`'s result kept) and writes the dislike and centroids; `undo_dislike` deletes them.
  - Events: `UndoLike` only when `dislike` removed a like; otherwise no publish, and the answer is `{"ok": True, "updatedAt": ...}`.
  - `like` with a key, when the video is disliked: the same recompute over the set without it, then `record_like` and `delete_dislike` in one transaction, then the `Like` publish as today.
  - `rat-tail:` read-compute-write is not serialised per profile; two concurrent dislikes by one visitor can leave centroids one dislike stale until the next change.
- **`GET /api/profile/reaction`** (`uuid`, `host`, validated as the block routes): `{"liked": bool, "disliked": bool}` by `(video_uuid, instance_domain)` from `users.db`.
- **`POST /api/profile/likes/import`** `{likes: [{uuid, host}]}`: `_parse_client_likes(body, MAX_CLIENT_LIKES)`, `resolve_videos_by_uuid_host`, `record_like` each that is not disliked, no event; answers `{"imported": n}`; `EngineApiError` → 502.
- **Proxy.** `_block_filter` becomes `_profile_filter(path, query) -> (proceed, keys, page_size, profile_id)` where `keys` is `(block_keys, disliked_keys)`; disliked keys are loaded on the feed routes only. The over-fetch applies when either is non-empty. In `_handle_engine_read_proxy_post`, after sanitising and with a `profile_id` on a feed route: `body["likes"] = random.sample` of up to 5 of the profile's stored likes as `{uuid, host}`, and `body["dislike_centroids"] = load_centroids(...)` when present. `_filter_payload` also drops rows whose `(video_id, instance_domain)` is disliked. `dislike_centroids` is not in `PROXY_ALLOWED_BODY_KEYS`, so a browser sending it gets 400.

#### Check against plan and requirements (pass 1)

- **Covered here:** D1 (store, cap, 401), D3, D4, D5, D6, D7, D8, D9; L1/D2 server half (reaction route); L4 (`undo_like`, unchanged); L5 server half (likes injected); L6 route; L7 routes (the modal's list is `GET /api/user-profile/likes`, and its remove is `undo_like`).
- **Misses found and fixed in the draft.**
  - `remove_like` committed on its own, which would split the dislike transaction; it no longer commits.
  - The import route could re-like a disliked video, breaking D3; it skips those.
  - `record_like` commits internally, which could commit the like before the dislike delete. Fixed by order: `delete_dislike` runs first in the transaction, so `record_like`'s commit commits both.
- **Converged in one pass.**

### Phases

Approved by the operator at Step 6 ("approve").

#### Common seam

- **Services.** Every phase runs against a real Engine and a real Client backend, with no double for either. `tests/tmp/conftest.py` is a copy of `tests/active/conftest.py` (the `engine` session fixture, `engine_client`, `dataset`), plus a bridge-token header for direct `/internal/*` calls. It is the precedent harness plan 07's checkpoints were harvested into.
- **Expected values.** Similarities are computed by the test from `video_embeddings` in `engine/server/db/whitelist.db`, opened read-only. They never come from a response. Reaction state is read back through `GET /api/profile/reaction`, not from `users.db`.
- **Measure.** `closeness(page, video)`: the mean cosine similarity between the embeddings of a page's rows and the disliked video's embedding. Up-next is deterministic per seed. Home draws are shuffled per request, so home is compared across several requests, with the spread measured by the 7.1 probe.

#### Phase 1 — The Engine turns dislikes into centroids and ranks against them

- **Kind:** code
- **Files:** `engine/server/api/recommendations/dislike_profile.py` (NEW), `engine/server/api/handlers/internal_client_reads.py`, `engine/server/api/handlers/similar.py`, `engine/server/api/request_context.py`, `engine/server/api/recommendations/scoring.py`, `engine/server/api/recommendations/mixer.py`, `engine/server/api/recommendations/related_personalization.py`, `engine/server/api/recommendations/builder.py`, `engine/server/api/server.py`, `engine/server/api/server_config.py` (EDITED); `tests/tmp/conftest.py` (NEW, common seam); `tests/tmp/test_dislike_engine.py` (NEW, checkpoint)
- **Intent (post-phase state):** A caller of the Engine's bridge can turn a set of disliked videos into at most four taste centroids. A home or up-next request that carries those centroids returns videos less similar to the disliked ones than the same request without them.
- **Clauses:**
  - `C1` — `POST /internal/dislikes/centroids` for n disliked videos returns min(4, n) unit-length centroids, and for n ≤ 4 each disliked video's embedding is one of them.
  - `C2` — A home request and an up-next request carrying the centroids of one disliked video return pages whose closeness to that video is lower than the same requests without the centroids.
- **Checkpoint and seam:** rung 1 over HTTP to the real Engine. C1 at n = 1, 3 and 6 (the bound either side of k = 4), with each video's embedding read from `whitelist.db`. C2 on up-next with a fixed seed, disliking the seed's nearest neighbour on the page; on home, across repeated requests, with the margin from the probe. Red today: the route answers 404 and the body field is ignored.

**Probe (7.1, observed)** — `tests/tmp/probe_dislike.py`
- Cosine between 600 random video pairs: p50 0.235, p90 0.411, p95 0.484, p99 0.592. **`DISLIKE_SIMILARITY_FLOOR` = 0.5** (about the 96th percentile): only similarity above the corpus background is penalised.
- Space: `paraphrase-multilingual-MiniLM-L12-v2`, 384 dimensions, read from `video_embeddings.model_name`.
- Up-next for the first search hit of `music`, `cooking` and `linux` is identical on repeated requests (`music` returns only 7 rows; the checkpoint uses the other two, which return 16).
- Home seeded with one like (profile `home`, layers explore/exploit/popular/random/fresh): closeness of five draws to the disliked video varies by about ±0.02 (`cooking` 0.313-0.323, `linux` 0.477-0.493).

**Self-check (dispatch 1)** — `tests/tmp/test_dislike_engine.py`, seam `tests/tmp/conftest.py`

- `C1 — test_dislike_engine.py:47, the number of centroids for n = 1, 3, 6 — expected: 1, 3, 4 — under a single mean vector: 1 at n = 3 and 6; under returning every disliked vector: 6 at n = 6; under no route: 404 at line 45 (observed).`
- `C1 — test_dislike_engine.py:49, each centroid's length — expected: 1 ± 1e-4 — under cluster means left unnormalised: below 1 at n = 6, where clusters hold several videos.`
- `C1 — test_dislike_engine.py:53, each disliked video's best cosine to a centroid, n = 1 and 3 — expected: > 0.9999 — under k fixed at 4 regardless of n or a single mean: a video matched only by a blend, cosine well below 1.`
- `C2 — test_dislike_engine.py:83, up-next closeness to the disliked video with the centroid, against without, seeds cooking and linux — expected: lower — under the field ignored: equal (observed 0.5127 = 0.5127 and 0.7315 = 0.7315).`
- `C2 — test_dislike_engine.py:101, the largest of five home closenesses with the centroid against the smallest of five without — expected: lower — under the field ignored: overlapping draws (observed 0.3406 vs 0.3175, 0.5005 vs 0.4751).`

Supporting (no row): line 45, the route answers 200; line 63, the seed's up-next page holds 16 rows; line 80, the disliked video is on the plain up-next page; line 82, the shaped page still holds 16; lines 95 and 99, home pages are non-empty.

1. **Whole claim** — C1: count at three sizes, unit length, and the n ≤ 4 identity. C2: up-next and home, each with and without.
2. **Absence only** — no; every assertion is a positive comparison.
3. **Echoed literal** — the centroid sent in C2 is the disliked embedding, but what is asserted is the closeness of the page the Engine chose, computed from `whitelist.db`; deleting the penalty turns lines 83 and 101 red. In C1 the expected vectors come from `whitelist.db`, not from the response.
4. **One value** — n at 1, 3, 6; two seeds; with against without on the same request.
5. **The double** — none: the real Engine on the real dataset.
6. **It collects** — 7 node ids.
7. **Observed** — the probe above and this run.
8. **Red** — exit 1, 7 failed.
9. **Right reason** — C1 at line 45, `404 == 200`, `{'error': 'Not found'}`: no route. C2 at line 83, equal closeness, because the Engine ignores the unknown body field; at line 101, the with and without draws overlap for the same reason. The controls at lines 63, 80, 82, 95 and 99 passed.
10. **Observed expected output** — yes. A false green on the home rows under an ignored field needs five draws to separate by chance, 1 in 252 per seed.

**Checkpoint audit (dispatch 1)**
- `AUDIT: devsecops-test-shape-auditor — BLOCK: single-value-pin, line 65. The disliked video was the page row nearest the seed, so "moved away from the disliked video" and "moved away from the seed" coincide; a penalty on seed similarity, or any change keyed on the field's presence, passes lines 83 and 101.`
- `AUDIT: devsecops-test-claim-auditor — PASS.` Frozen ledger: 18 rows, one UNCARRIED, D8 (`_distinct_videos` promises no two embeddings coincide; only the count was asserted).

**Remediation**
- Shape Critical: each seed's page now yields its least-similar pair `d1`, `d2` (line 70; the pair probe `tests/tmp/probe_dislike_pair.py` found such pairs at cosine 0.49-0.64 on every seed tried). Each is disliked in turn. The clause's own comparison stays (line 95, 116: less close to its own dislike than the plain page). A discrimination assertion is added (lines 96-97, 119): the within-page margin `closeness(page, d1) − closeness(page, d2)` is lower on d1's page than on d2's. A penalty keyed on the seed or on the field's presence gives both pages the same rows, so the margins are equal.
- D8 fixed: `_distinct_videos` asserts every pair's cosine is below 0.999 (line 39).
- Recommendation taken: n = 4 and 5 added, the bound either side of k = 4.
- Recommendations not taken, recorded:
  - Chaining the endpoint's output into the feed requests: C2's red must reach its own assertion, and with the endpoint absent it would stop at the setup. The chain is exercised in P3, where the Client passes the endpoint's centroids to the feed.
  - Missing bridge token, malformed `entries`, malformed `dislike_centroids`: the token rule is existing behaviour for every `/internal/` route; malformed input is validated at the boundary and is not a phase clause.

**Self-check (dispatch 2)**

- `C1 — test_dislike_engine.py:51, centroid count for n = 1, 3, 4, 5, 6 — expected: 1, 3, 4, 4, 4 — under a single mean: 1; under every vector returned: 5 and 6; under min(3, n) or min(5, n): wrong at 4 or 5; under no route: 404 at line 49 (observed).`
- `C1 — test_dislike_engine.py:53, each centroid's length — expected: 1 ± 1e-4 — under unnormalised cluster means: below 1 at n = 5 and 6.`
- `C1 — test_dislike_engine.py:57, each disliked video's best cosine to a centroid, n = 1, 3, 4 — expected: > 0.9999 — under a single mean or k fixed below n: a blend, well below 1.`
- `C2 — test_dislike_engine.py:95, up-next closeness to each of d1, d2 with its centroid, against the plain page — expected: lower — under the field ignored: equal (observed 0.5362 = 0.5362, 0.6820 = 0.6820).`
- `C2 — test_dislike_engine.py:96-97, up-next margin on d1's page against d2's — expected: lower — under a penalty keyed on the seed or on the field's presence: equal, the two pages being the same.`
- `C2 — test_dislike_engine.py:116, the largest of five home closenesses to each dislike with its centroid, against the smallest of five plain — expected: lower — under the field ignored: overlapping (observed 0.3443 vs 0.3310, 0.4417 vs 0.4162).`
- `C2 — test_dislike_engine.py:119, home margins on d1's pages against d2's — expected: every d1 margin below every d2 margin — under a penalty keyed on the seed, the like or the field's presence: the same distribution, separating by chance 1 in 252.`

Supporting (no row): line 49, the route answers 200; lines 38-39, n distinct embeddings; line 67, a 16-row plain page; line 72, the pair is below cosine 0.7; line 93, each shaped page holds 16; line 111, home pages are non-empty.

1. **Whole claim** — C1 at five sizes; C2 on up-next and home, each with the clause's comparison and the discrimination between two dislikes.
2. **Absence only** — no.
3. **Echoed literal** — no; the Engine chooses the pages and the test measures them against `whitelist.db`.
4. **One value** — two dislikes per seed, two seeds, five sizes; the Critical is this item, now answered by the pair.
5. **The double** — none.
6. **It collects** — 9 node ids.
7. **Observed** — the probes and this run. The discrimination's premise, that the pair points in different directions, is observed (line 72); the separation it expects under the real penalty is a prediction the implementation run will confirm.
8. **Red** — exit 1, 9 failed.
9. **Right reason** — C1 at line 49, `404`, no route. C2 at line 95 (equal closeness) and line 116 (overlap), the field being ignored. The controls at lines 38-39, 67, 72, 93 and 111 passed.
10. **Observed expected output** — yes.

**Checkpoint audit (dispatch 2)**
- `AUDIT: devsecops-test-shape-auditor — BLOCK: single-value-pin, lines 70-73 and 95. d1 and d2 are rows of the page measured, each at cosine 1 to its own centroid; an implementation that only drops the row matching a centroid passes line 95 and the margin (2(c−1)/16 < 0).`
- `AUDIT: devsecops-test-claim-auditor — PASS.` Frozen ledger: all 18 rows CARRIED, D8 by the assertion at line 36. Observations (non-blocking): n = 0 and failure paths untested; C2 sends the raw embedding rather than the endpoint's output.

**Remediation**
- Shape Critical: every closeness and margin is now measured over `_others(rows, d1, d2)`, the page without the two disliked videos, so a page scores lower only by what was re-ranked. The module docstring says "whose other rows".

**Self-check (dispatch 3)** — rows as dispatch 2, with these lines and values:
- `C2 — test_dislike_engine.py:100-101, up-next closeness of the page's other rows to each dislike, with its centroid against plain — expected: lower — under the field ignored: equal (observed 0.5167 = 0.5167, 0.6681 = 0.6681); under dropping only the exact-match row: equal, since the other rows are unchanged.`
- `C2 — test_dislike_engine.py:102-103, up-next margin over the other rows, d1's page against d2's — expected: lower — under a seed- or presence-keyed penalty, or exact-match dropping: equal.`
- `C2 — test_dislike_engine.py:123, home: the largest of five shaped other-row closenesses against the smallest of five plain — expected: lower — under the field ignored: overlapping (observed 0.3264 vs 0.2962, 0.4176 vs 0.4070).`
- `C2 — test_dislike_engine.py:126, home margins over the other rows — expected: every d1 margin below every d2 margin — under a seed-, like- or presence-keyed penalty, or exact-match dropping: the same distribution.`
- C1 rows unchanged (lines 51, 53, 57).

Answers 1-10 as dispatch 2, with: **4. One value** — the pair, and now the exclusion of the matched rows, answer the Critical. **8-9. Red** — exit 1, 9 failed: line 49 (404), line 101 (equal), line 123 (overlap); controls passed.

**Checkpoint audit (dispatch 3)**
- `AUDIT: devsecops-test-shape-auditor — BLOCK: single-value-pin (disliked videos measured as members of their own page). Fixed: closeness and margins measured over the page without d1 and d2. Re-audit: PASS. Predicted failure: line 49 for every n (404, no route); line 101 (equal closeness, dislike_centroids ignored); line 123 (home draws overlap).`
- `AUDIT: devsecops-test-claim-auditor — PASS.` Frozen ledger: 18 rows, all CARRIED.
- Observation 2 taken: the module docstring's "each page moves away from its own disliked video" claimed a per-page property that the one cross-page margin does not assert; narrowed to "a page carrying one of two dislikes leans away from it, relative to the other, more than a page carrying the other". A docstring change answering a recorded finding before the test gated.
- Observations 1, 3, 4 not taken: they restate the dispatch-1 recommendations recorded above.

**Implementation run 1 and triage (7.5)**
- First run after implementing: 6 passed, 3 failed. C1 passed at every n. Up-next `cooking` failed at line 102 (0.4824 against a plain 0.4816), and home failed on both seeds at line 124.
- Probe `tests/tmp/probe_penalty.py` (debug scores): the penalty is applied. Every up-next candidate at cosine ≥ 0.5 to the dislike lost that cosine from its score and sank to the bottom. But the up-next pool is about 17 deep (`similarity_max_per_author` = 1), so the page kept nearly the same set, reordered. The checkpoint's whole-page mean cannot see a reorder. **Checkpoint defect.**
- Probes `tests/tmp/probe_penalty_home.py` and `probe_home_position.py`: on home, the exploit layer's 17 candidates are on the page with or without the dislike. The mixer fills each layer's slots by ratio whatever the scores, so the penalty only reorders within a layer. On `cooking` (mixed like-layer) videos similar to the dislike moved from about position 19 to 29-36. On `linux`, `cats` and `news` every like-layer row is already close to the dislike (18/18, 13/13, 9-10/10), and nothing moved. **Design finding** (R2 made concrete): a dislike close to what a like brings in, the common case, left home unchanged.
- Put to the operator, one question each:
  - Checkpoint change, closeness over the leading rows: **"approve"**.
  - Home mixing, O2 (penalised candidates placed after every other candidate) against O1 (keep, assert on a mixed seed only): **"O2"**. With O2 the home check measures position; this was part of the O2 option as presented.
- **Checkpoint changes after gating, operator-approved:**
  - Up-next closeness is over the first 8 rows other than d1 and d2 (`UPNEXT_LEADING`).
  - Home measures the mean page position of rows at cosine ≥ 0.6 to each dislike (`CLEARLY_SIMILAR`, above the corpus p99 of 0.59, and deliberately not the production floor). A page holding none counts as its own length.
  - A plain-page control asserts such rows exist (line 144).
  - The test name and docstring were rewritten from the assertions.
- **Mutation, observed:** with O2's set-aside disabled in `mixer.py`, the home test fails on `linux` at line 146 (min 21.6 against max 21.8) and passes on `cooking`, as the probe predicted. Restored.

**Checkpoint audit (dispatch 4, on the altered test)**
- `AUDIT: devsecops-test-shape-auditor — PASS. Predicted failure: an Engine ignoring dislike_centroids fails lines 110-111 (equal leading closeness) and line 146 (shaped not below plain across 5 draws); a centroid-blind penalty fails lines 112-113 and 151; demoting only d1/d2 by key fails 110-111 and 146; unclustered or unnormalised centroids fail lines 56 and 58.`
- `AUDIT: devsecops-test-claim-auditor — PASS.` Fresh CLAUSE MAP: 18 rows, all CARRIED.
- Recommendations not taken, recorded: n = 0, more than `DISLIKE_MAX_ENTRIES`, and malformed entries on the endpoint; malformed `dislike_centroids` (wrong space, dimension, count, zero vector) being ignored. They are validation at the boundary, not a phase clause. The wrong-space case is R1's mitigation, so it is added to the Step 8 checks.

**Changes**
- `engine/server/api/recommendations/dislike_profile.py` (NEW)
  - `compute_centroids`: farthest-point initialisation from row 0, 20 k-means iterations, unit rows, k = min(4, n).
  - `apply_dislike_penalty`: one `fetch_embeddings_by_ids` batch under `db_lock`. For each candidate at cosine ≥ floor to the nearest centroid, it subtracts `weight × cosine` from `score` and records `dislike_penalty`.
- `engine/server/api/handlers/internal_client_reads.py`
  - The entry parsing moved into `_parse_entries`, shared by the metadata handler.
  - `handle_internal_dislike_centroids` answers `{ok, space, centroids}`, rounded to 6 decimals, with 400 above `DISLIKE_MAX_ENTRIES`.
- `engine/server/api/handlers/similar.py`
  - The `/internal/dislikes/centroids` route.
  - `_parse_dislike_centroids` accepts 1-4 finite, non-zero vectors of `embeddings_dim` whose `space` equals the running space, and anything else becomes None. It reads the server with `getattr`, so the unit test's bare server is untouched.
  - Up-next scores through `score_and_rank_list(..., adjust=penalise)`.
- `engine/server/api/request_context.py` — `set_request_dislike_centroids` and `fetch_request_dislike_centroids`, cleared with the rest.
- `engine/server/api/recommendations/scoring.py` — `score_and_rank_list` takes `adjust(candidates, settings)`, called between scoring and ranking.
- `engine/server/api/recommendations/mixer.py`
  - `MixerDeps` gains `fetch_embeddings_by_ids`, `fetch_dislike_centroids` and `dislike_similarity_floor`.
  - `_soft_mix_candidates` takes `server`, applies the penalty after scoring, and (O2) sets penalised candidates aside while the schedule fills, appending them after everything else.
- `engine/server/api/recommendations/related_personalization.py` — the final score subtracts `(1 − alpha) × dislike_penalty` (E20).
- `engine/server/api/recommendations/builder.py` — the deps gain `fetch_dislike_centroids`, the settings gain `dislike_similarity_floor`, and both are passed to `MixerDeps`. The floor is injected rather than imported, because no recommendations module imports `server_config`.
- `engine/server/api/server.py` — wires both, and sets `server.embeddings_model` after construction.
- `engine/server/api/server_config.py` — `DISLIKE_MAX_ENTRIES` = 1000, `DISLIKE_SIMILARITY_FLOOR` = 0.5.
- `tests/tmp/conftest.py` (NEW) — the active seam plus `BRIDGE_HEADERS`, `embedding_of`, `cosine`, `closeness`.
- **Inventory gaps:** none. `builder.py`'s settings dataclass (`RecommendationBuilderSettings`) was touched inside the listed file.
- **Rate limit (noted for later phases):** the Engine allows 60 requests a minute per address. This checkpoint makes about 45 in its run; probes that exceeded it got 429s.

**Checkpoint outcome** — PASS: `test_dislike_engine.py` 9 passed (46.6 s). Regression: `tests/active/test_similar.py` and `test_blocks.py` 13 passed; `engine/server/api/tests/test_recommendations_likes_limit.py` 3 OK.

#### Phase 2 — A profile dislikes and un-dislikes a video

- **Kind:** code
- **Files:** `client/backend/lib/users_store.py`, `client/backend/lib/profiles.py`, `client/backend/lib/engine_api_client.py`, `client/backend/server.py` (EDITED); `client/backend/lib/dislikes.py` (NEW); `tests/tmp/test_dislike_actions.py` (NEW, checkpoint)
- **Intent (post-phase state):** A profile holder can dislike and un-dislike a video through `/api/user-action`, a dislike and a like on one video replace each other, and `GET /api/profile/reaction` reads back the video's state. A visitor without a valid key cannot dislike.
- **Clauses:**
  - `C1` — For one video, the profile's reaction reads `liked` after `like`, `disliked` and not `liked` after `dislike`, neither after `undo_dislike`, and `liked` and not `disliked` after `like` on a disliked video.
  - `C2` — `dislike` with no key or an unknown key is answered 401, where the same request with the profile's key is answered 200.
- **Checkpoint and seam:** rung 1 over HTTP to the real Client wired to the real Engine. Videos are taken from `whitelist.db` (embedded, `error_count = 0`). Red today: the reaction route answers 404, and `dislike` is accepted without a key.
- **Seam detail (7.1):** the checkpoint's Client runs with publish mode `activitypub` (`unpublished_client` in `tests/tmp/conftest.py`). It is the real Client in its other shipped mode, which publishes nothing, so the test writes no `Like`/`UndoLike` rows into the repo's live `whitelist.db`. An action that would publish is answered 502 after its profile state is stored; the clauses read state through the reaction route, not the action's status.

**Self-check (dispatch 1)** — `tests/tmp/test_dislike_actions.py`
- `C1 — test_dislike_actions.py:53, the reaction after like — expected: (200, liked, not disliked) — under no route: (404, None, None) (observed).`
- `C1 — test_dislike_actions.py:55, after dislike on the liked video — expected: (200, False, True) — under a dislike that leaves the like: (200, True, True); under today's dislike-as-un-like: (200, False, False).`
- `C1 — test_dislike_actions.py:60, after undo_dislike — expected: (200, False, False) — under an undo that does nothing: (200, False, True).`
- `C1 — test_dislike_actions.py:63, after like on a disliked video — expected: (200, True, False) — under a like that leaves the dislike: (200, True, True).`
- `C2 — test_dislike_actions.py:71-72, dislike with no key and with an unknown well-formed key — expected: 401 — under no key check: the Engine resolve and publish run, 502 (observed) or 200.`
- `C2 — test_dislike_actions.py:73, dislike with the profile's key — expected: 200 — under a refusal of every dislike: 401.`

Supporting (no row): line 54, the dislike that removes a like answers 200 or 502 (502 when its `UndoLike` cannot be published in this mode); lines 57-58, a second video's reaction is its own while the first stays disliked, which excludes a route that ignores `uuid`; lines 59 and 61, undo_dislike and a fresh dislike answer 200; line 74, the accepted dislike was stored.

1. **Whole claim** — C1: all four transitions. C2: no key, unknown key, and the valid key.
2. **Absence only** — the 401s at lines 71-72 are armed by line 73's 200 for the same request with the key.
3. **Echoed literal** — no: the test sends uuid and host, and the reaction comes from the Client's store through its route.
4. **One value** — two videos; four transitions; three key states.
5. **The double** — none. The publish mode is the Client's own configuration, not a stand-in for a module.
6. **It collects** — 2 node ids.
7. **Observed** — this run: the Engine resolves the chosen videos (the keyless dislike reached publish, hence 502).
8. **Red** — exit 1, 2 failed.
9. **Right reason** — C1 at line 53, `(404, None, None)`: no reaction route. C2 at line 71, `502 == 401`: the dislike ran without a key. `_mint` and `_videos` passed.
10. **Observed expected output** — yes.

**Checkpoint audit**
- `AUDIT: devsecops-test-shape-auditor — PASS. Predicted failure: line 53, (404, None, None), no GET /api/profile/reaction; line 71, 502 == 401, the key is optional today and the unpublished Client answers 502.`
- `AUDIT: devsecops-test-claim-auditor — PASS.` CLAUSE MAP: 19 rows, all CARRIED.
- Recommendations:
  - Claim 1 taken: after the re-dislike (line 61), the reaction is read back as disliked (line 62), so line 64's "not disliked" cannot pass on a re-dislike that was silently dropped.
  - Shape 1 not taken: line 54 allows 502 because that dislike removes a like and so publishes `UndoLike`, which this Client cannot send. Line 61's dislike removes nothing and publishes nothing (D3, O5), so 200. Both lines fit one implementation.
  - Claim 2 and 3 not taken: malformed keys go through the same `resolve_profile` that `tests/active/test_profiles.py` covers; the 401 on `undo_dislike` and on the reaction route is checked at Step 8.
- The added line changes no clause row; C1's last row moves from line 63 to 64. The test still failed first at line 53 (404) before implementing.

**Changes**
- `client/backend/lib/users_store.py`
  - `ensure_user_schema` creates `dislikes` and `dislike_profiles`.
  - `remove_like` returns whether a row went and no longer commits; its callers hold `with conn:`.
  - `video_reaction` reads liked and disliked by `(video_uuid, instance_domain)`.
- `client/backend/lib/dislikes.py` (NEW)
  - `MAX_DISLIKES` = 1000 and `DislikeLimitReached`.
  - `dislike_entries`, `is_disliked`, `write_dislike`, `delete_dislike`, `load_centroids`. The writes run inside the caller's transaction.
- `client/backend/lib/profiles.py` — `delete_profile` deletes `dislikes` and `dislike_profiles`.
- `client/backend/lib/engine_api_client.py` — `compute_dislike_centroids` (None for an empty result).
- `client/backend/server.py`
  - `USER_ACTIONS` and `DISLIKE_ACTIONS`.
  - `_handle_user_action`: dislike actions go through `_require_profile`; a like keeps its optional key. It publishes only for like and undo_like, or when a dislike removed a like; otherwise it answers `{ok, updatedAt}` with 200. `DislikeLimitReached` → 400; an Engine centroid failure → 502 with nothing stored.
  - `_store_reaction` computes the centroids before any write. It removes the like and writes the dislike in one transaction; on a like of a disliked video it deletes the dislike first, then `record_like`, whose commit covers both.
  - `GET /api/profile/reaction` (`_handle_reaction_get`), rate-limited, with `uuid`/`host` validated as the block routes.
- `tests/tmp/conftest.py` — `unpublished_client` (publish mode `activitypub`) and a shared `_engine_client`.
- **Inventory gaps:** none.

**Checkpoint outcome** — PASS: `test_dislike_actions.py` 2 passed (11.4 s; a first run took 52.6 s on a slow Engine start). Active suite: `test_blocks.py` 7, `test_frontend_blocks.py` 2, `test_frontend_profile.py` 2, `test_profiles.py` 8 passed.

#### Phase 3 — Dislikes shape the profile's feeds

- **Kind:** code
- **Files:** `client/backend/server.py`, `client/backend/lib/dislikes.py` (EDITED); `tests/tmp/test_dislike_feeds.py` (NEW, checkpoint)
- **Intent (post-phase state):** A profile holder's disliked videos are absent from their up-next and random pages, which stay full, and their up-next page is less similar to what they disliked. A visitor without that profile gets the same pages as before.
- **Clauses:**
  - `C1` — A disliked video is absent from the profile's up-next (`/recommendations` and `/videos/similar`) and random pages, each still the requested size, while the keyless page for the same up-next request contains it.
  - `C2` — The profile's up-next page for a seed has lower closeness to its disliked video than the keyless page for the same seed.
- **Checkpoint and seam:** rung 1 over HTTP to the real Client and Engine. The disliked video is taken from the keyless up-next page, so its presence there is the control. Random is checked by size and absence across repeated draws, with the disliked video chosen from a random page. Red today: the proxy passes rows through and sends no centroids.
- _Amended at 7.1 with operator approval ("approve"): "and random" removed from C1._ The probe `tests/tmp/probe_feeds.py` saw no video recur across five 48-row random draws (0 of 240), so the absence of a disliked video from a random page holds with or without the filter. Random exclusion runs through the same `_filter_payload` as up-next. The random page's size and absence remain as a supporting check.
- **Probe (7.1, observed)** — up-next depth through the Client at `limit` 16 and 48: `linux` 16/19, `football` 16/18, `cats` 15/15, `guitar` and `news` 10/10. The checkpoint uses `linux` and `football`, whose pool can lose one video and still fill 16.

**Self-check (dispatch 1)** — `tests/tmp/test_dislike_feeds.py` (Client in `unpublished_client` mode; a dislike that removes no like publishes nothing)
- `C1 — test_dislike_feeds.py:65, the disliked video in the profile's up-next page, both routes, both seeds — expected: absent — under no filtering: present (observed).`
- `C1 — test_dislike_feeds.py:66, the profile's page size — expected: 16 — under filtering without the over-fetch for dislikes: 15.`
- `C1 — test_dislike_feeds.py:67, the disliked video in a keyless page after the dislike — expected: present — under a filter applied to every caller: absent.`
- `C2 — test_dislike_feeds.py:98-101, leading-8 closeness of each profile's page (other rows) to its own dislike against the keyless page — expected: lower — under no centroids sent: equal (observed 0.6643 = 0.6643, 0.4866 = 0.4866).`
- `C2 — test_dislike_feeds.py:102, margin of d1's profile page against d2's — expected: lower — under the Client sending one fixed or another profile's centroids: equal or reversed.`

Supporting (no row): line 61, a 16-row keyless page; `_profile_disliking`, the keyed dislike answers 200; lines 68-69, the profile's random page is 48 rows without the disliked video; line 77, the pair is below cosine 0.7.

1. **Whole claim** — C1: absence on both routes, the page size, and presence for a keyless caller. C2: both dislikes against keyless, and the discrimination between the two profiles.
2. **Absence only** — line 65 is armed by line 67 (the same request without the key still holds the video) and by line 66.
3. **Echoed literal** — no: the test names the dislike by uuid and host; the Client resolves, stores, loads and forwards; the Engine ranks.
4. **One value** — two seeds, two routes; two profiles with different dislikes.
5. **The double** — none; publish mode is the Client's own configuration.
6. **It collects** — 6 node ids.
7. **Observed** — the depth probe and this run.
8. **Red** — exit 1, 6 failed.
9. **Right reason** — C1 at line 65 on every seed and route: the proxy relays the Engine's page unfiltered. C2 at line 98: equal closeness, because the Client sends no centroids. Controls at line 61 and in `_profile_disliking` passed.
10. **Observed expected output** — yes.

**Checkpoint audit (dispatch 1)**
- `AUDIT: devsecops-test-shape-auditor — PASS. Predicted failure: line 65 on both routes and seeds (no dislike filtering, page equals keyless); line 98 (equal closeness, no centroids forwarded).` Recommendation: the random absence at line 69 has no control and gates nothing.
- `AUDIT: devsecops-test-claim-auditor — BLOCK: whole-claim, line 94 — C2 is over up-next, both routes, but the lean test requested only /recommendations (C2b UNCARRIED).` Frozen ledger: 16 rows, UNCARRIED C2b and N3b ("present for others" checked only for a keyless visitor).

**Remediation**
- C2b fixed: the lean test is parametrized over both routes.
- N3b fixed: a bystander profile disliking a different video (`keyless[0]`) still gets the disliked video on its page (line 68). This also carries D8 for two profiles.
- The random line is removed. Both auditors found its absence cannot fail; the size half cannot either (a random page loses nothing to a filter). This departs from the amendment's note that it "remains as a supporting check": it earned no place.
- Recommendations not taken, recorded: the 48-row clamp and a pool too shallow to refill are plan 07's (`test_blocks.py`); several dislikes on one page and the key failures on `/api/user-action` are P2's and Step 8's; a centroid failure on the dislike leaves no stored dislike (P2's `_store_reaction` order).

**Self-check (dispatch 2)** — rows as dispatch 1, re-lined:
- `C1 — :66 absent; :67 size 16; :68 keyless contains it — as dispatch 1 (observed red at :66, both routes, both seeds).`
- `C1 — :69, the bystander profile's page contains it — expected: present — under dislikes applied per route rather than per profile, or to the last profile that disliked: absent.` (supporting to C1's clause; carries the name's "others")
- `C2 — :99-102, both routes: each profile's leading-8 closeness to its own dislike against keyless — expected: lower — under no centroids forwarded on a route: equal (observed at :99 on both routes).`
- `C2 — :103, margin d1's page against d2's, both routes — as dispatch 1.`

Red: exit 1, 8 failed — line 66 (4) and line 99 (4). Answers 1-10 otherwise as dispatch 1.

**Checkpoint audit (dispatch 2)**
- `AUDIT: devsecops-test-shape-auditor — PASS. Predicted failure: line 66 on all four (no dislike filtering, keyed page equals keyless); lines 99-100 on all four (equal leading closeness, no centroids forwarded).`
- `AUDIT: devsecops-test-claim-auditor — BLOCK: whole-claim (C2 on /recommendations only). Fixed: lean test parametrized over both routes; N3b carried by a bystander profile. Re-audit: PASS.` Frozen ledger: 16 rows, all CARRIED.
- Observations, not blocking and not taken: the leading-8 measure is narrower than a whole page (stated in the docstring, and the operator-approved Phase 1 measure); failure modes and bounds as recorded at dispatch 1.

**Changes**
- `client/backend/lib/dislikes.py` — `load_disliked_keys` and `filter_disliked`, which match on `(video_id, instance_domain)`.
- `client/backend/server.py`
  - `_block_filter` becomes `_profile_filter`, returning `(proceed, row_filter, page_size, profile_id)`. Dislikes are loaded on the feed routes only, so search stays unfiltered by them (D6). The over-fetch applies when the profile has blocks or dislikes.
  - `_handle_engine_read_proxy_post` adds the profile's stored `dislike_centroids` to the body after sanitising, so the browser cannot supply them.
  - `_proxy_engine_request` and `_filter_payload` take the `RowFilter` (blocks plus disliked keys).
- **Inventory gaps:** none.

**Checkpoint outcome** — PASS: `test_dislike_feeds.py` 8 passed (14.0 s). Phase 1 and 2 checkpoints still pass (11 passed). Active suite: 19 passed across `test_blocks.py`, `test_frontend_blocks.py`, `test_frontend_profile.py` and `test_profiles.py`.

#### Phase 4 — Likes come from the profile

- **Kind:** code
- **Files:** `client/backend/server.py` (EDITED); `tests/tmp/test_profile_likes.py` (NEW, checkpoint)
- **Intent (post-phase state):** A profile holder can import a list of browser likes into their profile, and their feeds are seeded from the profile's likes, not from likes the browser sends.
- **Clauses:**
  - `C1` — After `POST /api/profile/likes/import` with a list of videos, the profile's reaction reads `liked` for each of them.
  - `C2` — A keyed up-next request is served with the liked-visitor profile (`debug.profile` `upnext`) when the profile holds likes and the browser sends none, and with the guest profile (`guest_upnext`) when the profile holds none and the browser sends some.
- **Checkpoint and seam:** rung 1 over HTTP to the real Client and Engine. C2 reads `debug.profile`, which the Engine returns for `debug=1` (`recommendations/debug.py`, enabled by `RECOMMENDATIONS_DEBUG_ENABLED`) and which `resolve_profile_config_with_guest` sets from whether the request carried likes. Red today: the import route answers 404, and the proxy forwards the browser's likes.

**Self-check (dispatch 1)** — `tests/tmp/test_profile_likes.py` (Client in `unpublished_client` mode; the profile's like is seeded with the `like` action, not the import, so C2 does not rest on C1)
- `C1 — test_profile_likes.py:45, each of three imported videos reads liked — expected: all liked — under no route: 404 at line 43 (observed); under an import that stores nothing or only the first entry: not all liked.`
- `C2 — test_profile_likes.py:71, a keyed up-next request from a profile holding a like, with no browser likes — expected: "upnext" — under a proxy that forwards only the browser's likes: "guest_upnext" (observed).`
- `C2 — test_profile_likes.py:74, a keyed up-next request from a profile holding no likes, with browser likes — expected: "guest_upnext" — under a proxy that keeps the browser's likes, or merges them: "upnext".`

Supporting (no row): line 41, no imported video is liked before; line 46, a fourth video stays unliked, excluding a route that marks everything; lines 65-66, keyless requests are served "guest_upnext" without likes and "upnext" with the browser's, which shows the profile names track likes on this seed; line 70, the holder's like is stored.

1. **Whole claim** — C1: every imported video, and not another. C2: both halves, profile likes without browser likes and browser likes without profile likes.
2. **Absence only** — line 46 is armed by line 45; line 74's "guest" is armed by line 66, where the same browser likes without a key give "upnext".
3. **Echoed literal** — no: the profile names come from the Engine's profile resolution, and the likes' effect is read, not echoed.
4. **One value** — four keyless/keyed and likes/no-likes combinations.
5. **The double** — none.
6. **It collects** — 2 node ids.
7. **Observed** — this run: the profile names on the keyless controls.
8. **Red** — exit 1, 2 failed.
9. **Right reason** — C1 at line 43: `404`, no import route. C2 at line 71: `'guest_upnext' == 'upnext'`, the profile's like never reaches the Engine. Controls at lines 41, 65, 66, 70 passed.
10. **Observed expected output** — yes.

**Checkpoint audit**
- `AUDIT: devsecops-test-shape-auditor — PASS. Predicted failure: line 43, 404 {"error": "Not found"}, no /api/profile/likes/import route; line 71, "guest_upnext", the Client forwards the empty browser body without the profile's likes; lines 65, 66 and 70 pass first.`
- `AUDIT: devsecops-test-claim-auditor — PASS.` CLAUSE MAP: 12 rows, all CARRIED.
- Recommendations not taken, recorded: the import's bounds (empty, malformed, unknown, duplicate, over the cap) and its 401 — the parsing is the existing `_parse_client_likes` and the 401 is `_require_profile`; the import's 401 is added to the Step 8 checks. Whether up-next rows derive from the liked video: C2 claims the profile label only.

**Changes**
- `client/backend/server.py`
  - `ENGINE_FEED_LIKES_MAX` = 5, with a `rat-tail:` comment naming the Engine constant it mirrors.
  - `_handle_engine_read_proxy_post`: for a resolved profile, the body's `likes` becomes a random sample of up to 5 of the profile's stored likes, replacing whatever the browser sent; empty when it holds none.
  - `POST /api/profile/likes/import` (`_handle_likes_import`), rate-limited and behind `_require_profile`. It resolves through `resolve_videos_by_uuid_host`, skips a video the profile dislikes, records the rest with `record_like`, publishes nothing, and answers `{imported}`.
- **Inventory gaps:** none.

**Checkpoint outcome** — PASS: `test_profile_likes.py` 2 passed (14.9 s). All checkpoints together: `tests/tmp` 21 passed. Active suite: 19 passed across the four groups that depend on `server.py`.

#### Acceptance criteria without a clause (checked at Step 8)

- **401 on `POST /api/profile/likes/import`** — no key and an unknown key (added at Phase 4).

- **D1's cap** — a profile at 1,000 dislikes has a further one refused with 400. A live request at Step 8.
- **D6 on home** — a disliked video absent from home pages. Home rarely draws a given video; the filter is the same code path as P3C1's random and up-next.
- **D6 on search** — search is not filtered: a disliked video still appears in the profile's search results. A live request at Step 8.
- **D9** — deleting a profile deletes its `dislikes` and `dislike_profiles` rows. A request pair and a read of `users.db` at Step 8.
- **L6's skip rule** — the import skips a disliked video. A live request at Step 8.
- **401 on `undo_dislike` and `GET /api/profile/reaction`** — no key and an unknown key. A live request each at Step 8 (added at Phase 2).
- **R1's guard** — `dislike_centroids` from another embedding space is ignored: an up-next page with wrong-space centroids equals the plain page. A live request at Step 8 (added at Phase 1).
- **Event rules (D3, O5)** — `dislike` publishes `UndoLike` only when it removed a like. No checkpoint asserts it, because the test Engine writes events into the repo's live `whitelist.db`. Checked at Step 8 from the response: `bridge_ok` is present only when an event was sent.
- **Frontend (plan 08)** — L1-L3, D2 on the page, L5's browser half, L6's trigger, L7's modal, D1's prompt.

#### Coordination

- All phases start the Engine from `engine/.pixi/envs/default` on the repo's dataset, as the active suite does. Up-next requests may write the live `similarity-cache.db`, a cache.
- After Phase 4: restart the live Engine and Client (`scripts/run-services.sh restart`), then run `tests/run-arch-split-smoke.sh`.

#### Rationale

- Four phases, two clauses each, one Intent each, split along the path a dislike travels: the Engine's capability, the Client's store, the proxy that joins them, and the like half that shares the proxy.
- Phases 3 and 4 both edit the proxy, but on separate clauses: exclusion and centroids in 3, likes in 4.
- Plan 08 holds the frontend (T1 of the high-level plan).

## Inner unit tests

None. Every phase's behaviour was expressible at its checkpoint.

## Close

### Refactors

- `_store_reaction` (`client/backend/server.py`): a like that touches no dislike, and an `undo_like`, no longer load the profile's whole dislike list. The `dislike` branch's `not is_disliked(...)` guard was removed as redundant: the list it counts already excludes the video, so a re-dislike at the cap never reaches 1,000 (checked at Step 8). Re-run green: `tests/tmp` 21, active 19.
- Left as they are:
  - `ENGINE_FEED_LIKES_MAX` duplicates the Engine's `DEFAULT_CLIENT_LIKES_MAX`, marked `rat-tail:`, the same way plan 07 left `FEED_PAGE_SIZE`.
  - The checkpoints repeat small helpers (`_videos`, `_mint`); the harvest decides where they land.
  - The Client's `recommendations.incoming_likes` log line still records the browser's likes before a keyed request replaces them.
- Nothing needed new behaviour.

### Clause accounting

- `P1C1`, `P1C2` — carried; dispatch 4 of `test_dislike_engine.py` (both PASS, on the operator-approved altered test).
- `P2C1`, `P2C2` — carried; dispatch 1 of `test_dislike_actions.py` (both PASS).
- `P3C1`, `P3C2` — carried; dispatch 2 of `test_dislike_feeds.py` (both PASS). P3C1 as amended with operator approval (random removed).
- `P4C1`, `P4C2` — carried; dispatch 1 of `test_profile_likes.py` (both PASS).

### Acceptance items without a clause (checked at Step 8)

`tests/tmp/probe_step8_checks.py` ran against the checkpoint seam (a real Engine and a real Client in `unpublished_client` mode):
- **401s:** `undo_dislike`, `GET /api/profile/reaction` and `POST /api/profile/likes/import` answer 401 with no key and with an unknown key.
- **Event rules (D3, O5):** a dislike with no like to remove answers `{"ok": true}` with no publish. A dislike that removed a like attempted a publish (`bridge_ok: false`, "activitypub is not implemented yet" in this mode).
- **L6's skip rule:** importing [a disliked video, another] gives `{"imported": 1}`. The disliked video stays disliked and not liked; the other reads liked.
- **D6 on search:** a disliked search hit is still in that profile's keyed search results.
- **D9:** `POST /api/profile/delete` → 204; `dislikes` 3 → 0, `dislike_profiles` 1 → 0.
- **D1's cap:** with 1,000 dislikes seeded, a new dislike → 400 "Dislike limit reached (1000)"; re-disliking one of the 1,000 → 200.
- **R1's guard:** an up-next page with centroids tagged `some-other-model` equals the plain page; the same vector tagged with the real space changes it.
- **D6 on home:** not checked live. Home rarely draws a given video; the filter is the same `_filter_payload` path that P3C1 proves on up-next.
- **Split smoke:** `tests/run-arch-split-smoke.sh` on ports 7182/7282, run through `pixi run --manifest-path engine/pixi.toml`: all 21 checks passed. As in plans 06 and 07, the smoke's keyless test Like remains in the live Engine database.
- **Boundaries:** `tests/check-client-engine-boundary.sh` and `tests/check-frontend-client-gateway.sh` PASS.

### Suite

- `--compare`: "unchanged since 2026-09-26T10:02:22-04:00 — every fingerprint still holds", 27 passed; "nothing moved against the previous record". The baseline was 27 passed.
- Phase checkpoints together: `tests/tmp` 21 passed.
- `engine/server/api/tests/test_recommendations_likes_limit.py` (unittest, outside `active`): 3 OK.

### Harvest (Step 10)

- **Record:** `docs/project/plans/harvest-03-like-dislike-plan.md`.
- **Moved (operator-approved), all 9 checkpoint tests DURABLE:**
  - the Engine tests to `tests/active/test_dislike_profile.py` (NEW);
  - the dislike action and feed tests to `tests/active/test_dislikes.py` (NEW);
  - the like import and keyed-likes tests to `tests/active/test_profiles.py`.
  - The seam helpers and `unpublished_client` went into `tests/active/conftest.py`; `test_groups` gained the two new groups; `--audit-map` exits 0.
- **Mutations:** each felled its assertion. Three backups captured their own mutation, because each was taken in the same batch as its Edit. That was caught when the subject files failed together, and the three lines were restored by hand and verified by grep. Details in the harvest record.
- **Disposed:** `tests/tmp` went to `delete_me/plan03-tmp/`.
- **Suite:** 48 passed (27 + 21 harvested nodes). `--compare` moved only the 21 appearances.

### Coordination

- The operator restarted the live Engine and Client with `scripts/run-services.sh restart` ("ran script") and cleared `delete_me/`, which held the working tests, the probes and the Step 6 `.bak` copies. No browser check is due from this build: the frontend is plan 08.
