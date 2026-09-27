# Build record - 13-deterministic-event-ids

Written by the `dev-flow` workflow. The plan it accompanies is `docs/project/plans/16-13-deterministic-event-ids.md`.

**Nothing but the workflow writes this file.** It carries the evidence each gate turned on: the baseline, both auditor verdicts verbatim, every self-check table, every red and its reason, every checkpoint outcome, and every amendment the operator approved to a settled section of the plan.

## Run state

<!-- dev-flow:state
```json
{
  "version": 1,
  "request": "# Derive interaction event ids and cap the signal in the popular ordering\n\n## Requirements\n\n### What was asked for\n\nBuild issue `docs/project/issues/01-deterministic-event-ids.md` as triaged: Derive interaction event ids so replays collapse at ingest, and cap the interaction signal's effect on the popular ordering. The Agent Brief below, copied from the issue, is the confirmed requirement set; the build starts from this file.\n\n### Purpose\n\nClose the security-audit finding the issue records. This build is one of issues 01-06, delivered concurrently to use as little operator time and cause as few merge conflicts as possible.\n\n### Decisions this rests on\n\n`docs/project/adr/0001-derived-interaction-event-ids.md`; `CONTEXT.md` **Interaction event**, **Interaction signal**.\n\n### Agent Brief\n\n**Category:** bug\n**Summary:** Derive interaction event ids so replays collapse at ingest, and cap the interaction signal's effect on the popular ordering\n\n**Current behavior:**\nWhen a visitor posts a `like` or `undo_like` user action, the Client backend publishes an interaction event with a freshly generated random `event_id` (`client-<uuid4>`). It publishes on every request, even when the profile already likes the video (or, for `undo_like`, does not). A request without `X-Profile-Key` is published as actor `anonymous`. The Engine ingests idempotently on `event_id`, but because every id is new, each repeated `Like` adds `+1.0` to the video's `interaction_signals.signal_score`. The Engine's popular pool orders by `popularity + signal_score` with no bound, so repeated posts can push any video to the top. A dislike that replaces a like publishes an `UndoLike` the same way.\n\n**Desired behavior:**\n- **Profile, publish on change only.** A `like` publishes a `Like` only when the profile did not already like the video. An `undo_like` publishes an `UndoLike` only when a like was actually removed. A dislike that replaces a like still publishes an `UndoLike` (it already does so only when a like was removed). A no-change request still returns 200 and publishes nothing.\n- **Profile, derived id.** The `event_id` is a deterministic function of actor, `video_uuid`, `instance_domain`, `event_type`, and a *like instance*. The instance must be the same for every publish of one like and of the un-like that ends it, and different for a like made after that un-like. There is no per-video like counter today: the `likes` row is deleted on un-like, so the agent must choose where the instance comes from, and it must survive the un-like. Any scheme meeting this contract is acceptable.\n- **Anonymous, derived id.** Actor `anonymous` uses a fixed instance, so every anonymous `Like` on a video carries one id and every anonymous `UndoLike` on it carries another.\n- The id must not embed raw user input unhashed; a hash (e.g. SHA-256 hex, with a prefix such as `client-`) over the joined fields is expected. It must stay a non-empty string that the Engine's `normalize_event_payload` accepts.\n- **Ranking cap.** The Engine's popular-pool ordering uses `popularity + MIN(COALESCE(signal_score, 0), C)`, where `C` is a named module-level constant set to `25.0`. `interaction_signals.signal_score` itself is still stored uncapped.\n\n**Key interfaces:**\n- The Client backend's user-action handler (currently `_handle_user_action`) and the event payload it builds for `_publish_event`: the `event_id` field and the decision whether to publish.\n- `record_like()` in the client users store currently returns `None`. It needs to report whether the like was new (or the handler must check the like state first), so the handler can gate publishing.\n- `remove_like()` already returns whether a like was removed; the `undo_like` path should use it.\n- The Engine's popular-pool query (the one ordering by `v.popularity + COALESCE(sig.signal_score, 0)`) and a new constant beside it.\n- `ingest_interaction_event()` / `normalize_event_payload()` in the Engine: **unchanged**. The existing `ON CONFLICT(event_id) DO NOTHING` does the collapsing.\n\n**Acceptance criteria:**\n- [ ] Posting `like` twice for one video with one profile publishes exactly one `Like`; the video's `likes_count` and `signal_score` rise by 1 and 1.0.\n- [ ] A profile's like \u2192 undo_like \u2192 like sequence publishes Like, UndoLike, Like, and the two `Like` events carry different `event_id`s. The video ends with `signal_score` 1.0.\n- [ ] Re-sending an identical already-published event to the Engine (a bridge retry) is reported as `duplicate: true` and changes no counts.\n- [ ] Two anonymous `like` posts for one video produce the same `event_id`, and the Engine counts the second as a duplicate.\n- [ ] `undo_like` for a video the profile does not like publishes nothing and returns 200.\n- [ ] A dislike replacing a like publishes one `UndoLike`, with the id the matching profile un-like would have used; a dislike on an unliked video publishes nothing.\n- [ ] In the popular ordering, a video with `signal_score` 1000 and `popularity` 0 ranks below a video with `popularity` 30 and no signal (the cap bounds the signal at 25.0).\n- [ ] The existing interaction-event and security-bundle test suites still pass.\n\n**Out of scope:**\n- Backfilling or rewriting events already stored with random ids.\n- Changing Engine ingest, `_event_deltas` weights, or the stored `signal_score`.\n- The secondary likes tiebreaker in the popular ordering (`likes + likes_count`, net of undos since plan 08); it only breaks ties and is left uncapped.\n- `Comment` events (the Client does not publish them today).\n- Rate limiting, or requiring a profile for likes.\n- The likes-import path, which publishes nothing.\n\n### Consistency constraints\n\n- Match the surrounding code's style: stdlib HTTP handlers, `respond_json`, module-level named constants, and env vars read once at startup.\n- Backwards compatibility is not required beyond what the brief states.\n- Run `validate_tests.py` from the root of the tree this build runs in (a worktree for waves 1-2, main for wave 3). That tree's `.un` config carries it as `project_dir`.\n\n### Batch context\n\nPart of the security hardening batch (`.scratch/security-hardening-batch/notes.md`): issues 01-06 delivered in three waves of git worktrees. Wave 1 is plans 10, 11 and 12. Wave 2 is 13 and 14, branched from main after wave 1 merges. Wave 3 is 15, on the merged main. A wave 1 or 2 build runs in its own worktree created by `.scratch/security-hardening-batch/worktree-setup.sh`, merges to main when it closes, and is harvested on main, not in the worktree.\n\nWave 2, branched from main after plans 10-12 merge, and running alongside plan 14. Both plans edit `client/backend/server.py`, in different handlers. Both also edit `client/backend/lib/users_store.py`: this plan changes what `record_like` returns, and plan 14's import calls `record_like` and ignores the return value.\n\n### Conflicts\n\nThe brief does not conflict with the tree. Every function and line it names was checked against the source on 2026-09-26 (`.scratch/security-hardening-batch/notes.md`, File overlap). Line numbers will drift once earlier waves merge, so re-locate by function name at Step 3.\n\n## High-level plan\n\n### Approach\n\n**Like instance.** The brief leaves its source to the build. The approved design is a new Client table `like_generations(user_id, video_id, instance_domain, generation)`. `ensure_user_schema` creates it with `CREATE TABLE IF NOT EXISTS`, and an un-like never deletes from it.\n- A `like` that inserts a new `likes` row increments the generation. `record_like` reports whether the like was new and returns the generation.\n- An `undo_like`, or a dislike that replaces a like, reads the video's current generation and removes the like with `remove_like`. It publishes only when a like was removed.\n- Anonymous actors use a fixed generation `0`.\n\n**Id.** The user-action handler sets `event_id` to `client-` followed by the SHA-256 hex of the joined `(actor, video_uuid, instance_domain, event_type, generation)`, replacing `client-<uuid4>`. Actor is the profile id, or `anonymous`.\n\n**Publish on change only.** In `_handle_user_action` (`server.py:684`), `publish` is true only for a new like or when a like was removed. A request that changes nothing still returns 200.\n\n**Ranking cap.** `engine/server/data/random_videos.py:247` orders by `v.popularity + MIN(COALESCE(sig.signal_score, 0), C)`, where `C` is a module-level constant set to `25.0`. Ingest, `_event_deltas` and the stored score are unchanged.\n\n### Alternatives considered\n\n- **A column on `likes`.** Rejected: an un-like deletes the row, so the instance would not survive to tell the next like apart.\n- **The like's timestamp as the instance.** Rejected: it does not follow from stored state, so retrying a request after a partial failure could produce a second id.\n- **The key without an instance** (the issue's step 1). Rejected at triage (ADR-0001): it drops genuine re-likes and lets any visitor permanently zero a video's anonymous contribution.\n\n### Risks and limitations\n\n- **Trimmed likes.** When the `max_likes` trim in `record_like` drops a like, the Engine keeps its `+1`. A later un-like finds nothing to remove and publishes nothing. This gap exists today, and the plan does not close it.\n- `like_generations` gains one row for each (profile, video) pair ever liked. It stays small. If a profile-deletion path exists, it should also remove that profile's rows; the build checks at Step 3.\n- Likes import (plan 14's path) also calls `record_like`. The new return value must not break that caller; import publishes nothing.\n- **Shared `whitelist.db`.** The worktree symlinks the main tree's `whitelist.db`, so this build's test Engines write interaction rows into the same file as other lanes, and as the live Engine if it runs. Every test run already does this; worktrees only make it concurrent.\n- **Tracked test record.** `tests/last_test_validation.json` and `tests/last_test_output.txt` always conflict on merge. Take main's copy and re-run `validate_tests.py --compare` on the merged tree.\n- **Engine rate limit.** Run Engine-backed test files in their own `validate_tests.py` invocations (memory `engine-rate-limit-single-lane-test-runs`).\n\n### Tradeoffs accepted\n\nAnonymous likes add at most +1 per video, permanently. Events stored before this change keep their random ids and are not backfilled.",
  "request_source": "read from docs/project/plans/13-deterministic-event-ids.md",
  "slug": "13-deterministic-event-ids",
  "steps": {
    "0": "done",
    "1": "done",
    "2": "done",
    "3": "done",
    "4": "done",
    "5": "done",
    "6": "done",
    "7": "done",
    "8": "done",
    "9": "done"
  },
  "phases": [
    {
      "n": "1",
      "kind": "code",
      "name": "Popular signal cap",
      "checkpoint": "T9, `test_the_popular_order_caps_the_interaction_signal(tmp_path)` in tests/active/test_random_videos.py. The seam is a direct call to `fetch_popular_videos(conn, 10, error_threshold=threshold)` on the isolated tmp engine.db built by the existing `_two_video_db` harness, so the file's own tests are the precedent. Setup: `first` gets popularity 0, `second` gets popularity 30, and an `interaction_signals` row gives `first` a signal_score of 1000.0 with likes_count 0. The test runs for threshold in (None, 1), an explicit set covering both params branches. It asserts that the result order by `video_id` is [second, first]. As a control it asserts that `first`'s `interaction_signal_score == 1000.0`, so the stored score is shown to be raw. `_set_views` sets error_count = 0, so threshold 1 keeps both rows. A wrong params order therefore breaks at least one branch.",
      "intent": "`fetch_popular_videos` in engine/server/data/random_videos.py orders videos by popularity plus the interaction signal capped at the module constant `POPULAR_SIGNAL_CAP`.",
      "clauses": [
        {
          "id": "C1",
          "text": "A video with signal 1000 and popularity 0 ranks below a video with popularity 30 and no signal, with and without an error threshold."
        }
      ],
      "files": [
        "engine/server/data/random_videos.py (EDITED)",
        "tests/active/test_random_videos.py (EDITED)"
      ],
      "done": true,
      "outcome": "### `engine/server/data/random_videos.py`\n- Added the module constant `POPULAR_SIGNAL_CAP = 25.0`. It has a one-line comment saying why it exists: a burst of interaction events should not be able to outrank crawled popularity.\n- `fetch_popular_videos` now ranks by `v.popularity + MIN(COALESCE(sig.signal_score, 0), ?)` instead of `v.popularity + COALESCE(sig.signal_score, 0)`. The cap is a bound parameter. It sits in `params` after the optional error threshold and before the two `limit`s, which matches where each `?` appears in the SQL. This is true with and without an error threshold.\n- The tie-breakers after the popularity term are unchanged (likes plus signal likes, views, published_at, video_id).\n- The returned `interaction_signal_score` column is unchanged and still reports the raw, uncapped signal.\n\n### `tests/active/test_random_videos.py`\nNot changed. It only uses a signal of 1.0, well under the cap, so the cap doesn't affect it. It has no expectation that conflicts with this change, so this phase had no reason to edit it."
    },
    {
      "n": "2",
      "kind": "code",
      "name": "Publish on change, derived ids",
      "checkpoint": "T1\u2013T8 in tests/active/test_event_ids.py (NEW). The seam is HTTP POST to /api/user-action, /api/user-profile/reset and /api/profile/likes/import on a real `ClientBackendServer` in \"bridge\" mode over a tmp users.db, with `RateLimiter(1000, 60)`. It follows the `_serving` / `_client_backend` harness in test_server.py and is wrapped in conftest's `ClientBackend`. The Engine is a `BaseHTTPRequestHandler` stub with three routes. `/internal/videos/resolve` echoes a video. `/internal/dislikes/centroids` answers with empty centroids. `/internal/events/ingest` runs the real `ingest_interaction_event` on a tmp engine.db under a lock and records (payload, result). Assertions are made at the Engine boundary: the published (event_type, event_id) list and `interaction_signals` (likes_count, signal_score).\nClause 1: T1 (double like gives one Like, (1, 1.0)). T5 (undo_like of an unliked video answers 200 with no event). T6b (dislike of an unliked video adds no event). T7 (like, reset, like publishes one Like, and the later undo_like gives one UndoLike, ending at (0, 0.0)). T8 (import then undo_like gives no events). For T8, the builder reads engine_api_client.py:136-166 and adds the resolve-by-uuid stub route. If that route costs more than about 15 lines, the test seeds with `record_like` without `publish`.\nClause 2: T2 (like \u2192 undo_like \u2192 like gives [Like, UndoLike, Like]; ids[0] equals sha256 of json.dumps([pid, uuid, host, \"Like\", 1]); ids[2] uses generation 2 and differs from ids[0]; the signal ends at 1.0). T3 (re-ingesting T1's payload returns duplicate True and leaves the counts unchanged). T4 (two anonymous likes carry equal ids, the second is a duplicate, and the signal is (1, 1.0)). T6a (a dislike replacing a like publishes an UndoLike whose id is sha256 of [pid, uuid, host, \"UndoLike\", 1]).",
      "intent": "A profile's POST /api/user-action publishes a Like or UndoLike only when it opens or closes that profile's published like of the video, tracked in the new `like_generations` table by `record_like(publish=True)` and `close_like` in users_store.py, and every event `_handle_user_action` publishes carries an id derived from actor, video, event type and like generation.",
      "clauses": [
        {
          "id": "C1",
          "text": "An action that neither opens nor closes the profile's published like of the video publishes no event."
        },
        {
          "id": "C2",
          "text": "A published event's id is `client-` plus the SHA-256 of the JSON list of actor, canonical uuid, canonical host, event type and like generation."
        }
      ],
      "files": [
        "client/backend/lib/users_store.py (EDITED)",
        "client/backend/server.py (EDITED)",
        "tests/active/test_event_ids.py (NEW)"
      ],
      "done": true,
      "outcome": "### `client/backend/lib/users_store.py`\n- `ensure_user_schema` now also creates `like_generations(user_id, video_id, instance_domain, generation INTEGER NOT NULL, published INTEGER NOT NULL DEFAULT 0)`, keyed on `(user_id, video_id, instance_domain)`, with `CREATE TABLE IF NOT EXISTS`. It sits before the `local-user` cleanup, and the docstring names the new table.\n- `record_like` takes a new keyword `publish: bool = False` and returns `(opened, generation)`.\n  - The `likes` INSERT is now `ON CONFLICT DO NOTHING`, and its own rowcount decides whether the like is new. An existing row gets a plain UPDATE of `video_uuid`/`updated_at`, so recency and the trim work as before.\n  - A new like with `publish=True` runs a conditional upsert on `like_generations`. It inserts `(g=1, published=1)`, or sets `g+1, published=1` only when `published = 0`. The rowcount is `opened`.\n  - A re-like after a reset or trim, while the like is still published, therefore opens nothing. An imported like (`publish` left False) never touches `like_generations`.\n  - The trim and the commit are unchanged. The import caller ignores the return value.\n- New `like_generation(conn, user_id, video_id, instance_domain) -> int` returns the stored generation, or 0 when there is no row. It uses `row[0]`, so it works with or without a `row_factory`.\n- New `close_like(conn, user_id, video_id, instance_domain) -> tuple[bool, int]` runs `UPDATE ... SET published = 0 ... AND published = 1`. It returns whether a published like was closed, plus that like's generation. It does not commit: it runs inside the caller's transaction, like `remove_like`.\n\n### `client/backend/server.py`\n- Added `import hashlib`. `close_like` joins the `lib.users_store` import. `uuid4` stays because `run_id` still uses it.\n- `_store_reaction` now returns `(publish, generation)`:\n  - plain like, and like replacing a dislike: `record_like(..., publish=True)`;\n  - undo_like: `remove_like` then `close_like`, in the same `with conn`;\n  - dislike: `remove_like`, `close_like` and `write_dislike` in the existing write transaction, still after the limit check and the centroids request;\n  - undo_dislike: `(False, 0)`.\n  - The `:returns:` docstring is rewritten.\n- `_handle_user_action`:\n  - Anonymous requests keep `publish = action in (\"like\", \"undo_like\")` at generation 0. A profile's request publishes only what `_store_reaction` reports. A no-change request falls through to the existing 200 `{ok, updatedAt}`.\n  - `actor = profile_id or \"anonymous\"` is computed once and used for both the id and `actor_id`.\n  - `event_id` is `\"client-\" + sha256(json.dumps([actor, canonical_uuid, canonical_host, event_type, generation]))`. It hashes the Engine-resolved uuid and host, not the spelling sent.\n  - The docstring now states the publish rule. Other payload fields and the error paths are unchanged.\n\n### `tests/active/test_event_ids.py`\nNot created. The gating checkpoint `tests/tmp/test_13_deterministic_event_ids_phase2.py` covers T1\u2013T8. I left moving it into `tests/active` to the workflow rather than make a copy.",
      "beyond": "tests/tmp/probe_like_generations.py: a throwaway probe I wrote to check SQLite's behaviour. When the `DO UPDATE ... WHERE` condition is false, the upsert reports rowcount 0. The probe ran the new users_store functions through open, repeat, close, re-open, reset and import. It passed, and every step returned the `(opened/closed, generation)` it should. I have no delete tool, so it is still there; please delete it. Running it also rewrote `tests/last_test_validation.json` and `tests/last_test_output.txt` with that one probe's result."
    },
    {
      "n": "3",
      "kind": "code",
      "name": "Delete removes generations",
      "checkpoint": "T10: extend the existing `test_deleting_a_profile_removes_its_rows_and_keeps_anothers` in tests/active/test_profiles.py. The seam is HTTP POST /api/profile/delete on conftest's `client_backend`, with row counts read straight from users.db through `_rows_for`, following the precedent in this test. `_seed_like` passes `publish=True`. `_rows_for` adds a `like_generations` count. The asserts at 205, 209 and 216 expect `\"like_generations\": 1`, and the one at 215 expects `\"like_generations\": 0`. The comment at 201 is updated to say all four tables hold rows.",
      "intent": "`delete_profile` in client/backend/lib/profiles.py removes the deleted profile's `like_generations` rows inside its existing transaction.",
      "clauses": [
        {
          "id": "C1",
          "text": "After one profile is deleted, it has no `like_generations` rows and another profile keeps its rows."
        }
      ],
      "files": [
        "client/backend/lib/profiles.py (EDITED)",
        "tests/active/test_profiles.py (EDITED)"
      ],
      "done": true,
      "outcome": "### client/backend/lib/profiles.py\n`delete_profile` now also runs `DELETE FROM like_generations WHERE user_id = ?` inside its existing `with conn:` transaction, right after the `likes` delete. It deletes by `user_id`, not by the likes it just removed, so closed generations (rows left behind after an undone like) go too. The table has no foreign keys, so the order of the deletes doesn't matter.\n\n### tests/active/test_profiles.py\nNot changed. The phase lists it as EDITED, but it is a durable test that has already gated, so this step can't touch it. Its `test_deleting_a_profile_removes_its_rows_and_keeps_anothers` still holds, because it only counts `profiles`, `users` and `likes`. Moving the checkpoint's `like_generations` assertions into this file is left to the promotion step."
    }
  ],
  "digests": {
    "tests/tmp/test_13_deterministic_event_ids_phase1.py": "2894bdc9975caf681b04d2584003b581f04ee21419c36525ab0dffa887a822cf",
    "tests/tmp/test_13_deterministic_event_ids_phase2.py": "a8b18fba80cfa7b479073b6d1f95fc3dc373ead412739ca1e8d5a5b78e858ecb",
    "tests/tmp/test_13_deterministic_event_ids_phase3.py": "59bea168d73f1b60df3edddfc371fe7b5f560e0664b377887de339a942398cb4"
  },
  "paths": {
    "active": "tests/active",
    "working": "tests/tmp",
    "plans": "docs/project/plans",
    "delete_me": "delete_me",
    "archive": "tests/archive",
    "project_dir": "/home/enduser/code/PeerTube-browser/.worktrees/fix-13-deterministic-event-ids",
    "record": "tests/last_test_validation.json",
    "output": "tests/last_test_output.txt"
  },
  "baseline": {
    "code": 0,
    "variant": false
  },
  "sessions": [
    "20260927T025910-105e-dev-flow",
    "20260927T030138-ea07-dev-flow"
  ],
  "plan": "docs/project/plans/16-13-deterministic-event-ids.md",
  "record": "docs/project/plans/16-13-deterministic-event-ids.record.md",
  "replies": {
    "step_1_gather_requirements": "<requirements>\n### Goal and purpose\n\nBuild issue `docs/project/issues/01-deterministic-event-ids.md` as triaged. It closes the security-audit finding that repeated `like` posts can push any video to the top of the Engine's popular ordering. Two changes do this. (1) The Client backend derives each interaction event's `event_id` deterministically, so the Engine's existing `ON CONFLICT(event_id) DO NOTHING` collapses replays at ingest. (2) The Engine caps how much the interaction signal can add in the popular ordering. Decisions: `docs/project/adr/0001-derived-interaction-event-ids.md` and `CONTEXT.md` **Interaction event** and **Interaction signal**. This build is plan 13, in wave 2 of the security hardening batch (issues 01-06, `.scratch/security-hardening-batch/notes.md`). It runs in the worktree `/home/enduser/code/PeerTube-browser/.worktrees/fix-13-deterministic-event-ids`, branched from main after plans 10-12 merged, and alongside plan 14.\n\n### Current behavior (verified in the tree)\n\n- `client/backend/server.py` `_handle_user_action` (currently around line 731) builds the event with `\"event_id\": f\"client-{uuid4()}\"` (around line 802). It sets `publish = action in (\"like\", \"undo_like\")`, so every like and undo_like is published even when nothing changed. `actor_id` is `profile_id or \"anonymous\"`. A dislike publishes an `UndoLike` only when `_store_reaction` reports that a like was removed.\n- `_store_reaction(profile_id, action, video)` returns whether a dislike removed a like. It calls `record_like` in two places: the plain-like branch, and the \"like replacing a dislike\" branch. It calls `remove_like` in the undo_like branch and in the dislike branch.\n- `client/backend/lib/users_store.py`: `record_like(conn, user_id, action, video, max_likes) -> None` upserts into `likes` (`ON CONFLICT ... DO UPDATE`), trims to `max_likes`, and commits. `remove_like(conn, user_id, video_id, instance_domain) -> bool` deletes the row and reports whether one was removed. The `likes` row is deleted on un-like, so there is no persistent per-video like instance.\n- `_handle_likes_import` calls `record_like` and publishes nothing.\n- `client/backend/lib/profiles.py` `delete_profile` deletes every row keyed to a profile (blocks, dislikes, dislike_profiles, likes, users, profiles) in one transaction.\n- `engine/server/data/random_videos.py` `fetch_popular_videos` orders its inner subquery by `(v.popularity + COALESCE(sig.signal_score, 0)) DESC` (around line 247), then by `(v.likes + COALESCE(sig.likes_count, 0)) DESC`, then views, published_at and video_id.\n\n### Requirements: like instance (generation)\n\n- Add a new Client table, `like_generations(user_id, video_id, instance_domain, generation)`, keyed on `(user_id, video_id, instance_domain)`. Create it in `ensure_user_schema` with `CREATE TABLE IF NOT EXISTS`, in the same executescript style as the other tables.\n- An un-like never deletes from `like_generations`, so the generation survives the un-like.\n- When `record_like` inserts a new `likes` row, it increments that video's generation for the user, starting from 1 on the first like. Re-liking a video that is already liked leaves the generation unchanged.\n- `record_like` reports whether the like was new and returns the current generation (for example, a `(new, generation)` pair). The exact return shape is the build's choice. The likes-import caller ignores the return value and must keep working unchanged.\n- An `undo_like`, or a dislike that replaces a like, reads the video's current generation for the profile and removes the like with `remove_like`. It publishes only when `remove_like` reports that a like was removed. The generation it uses is the one the matching Like used.\n- Anonymous actors (no resolvable `X-Profile-Key`) use the fixed generation `0`.\n- `delete_profile` in `client/backend/lib/profiles.py` also deletes that profile's `like_generations` rows, in the same transaction.\n\n### Requirements: derived event id\n\n- The event id is `client-` followed by the SHA-256 hex digest of the joined fields `(actor, video_uuid, instance_domain, event_type, generation)`. Actor is the profile id, or `anonymous`. `event_type` is `Like` or `UndoLike`. The joining must be unambiguous (e.g. a separator that cannot confuse field boundaries). This replaces `client-<uuid4>`, and the `uuid4` import goes if nothing else uses it.\n- Every publish of one like, and of the un-like that ends it, uses the same generation. A like made after that un-like uses a different one.\n- The id never embeds raw user input unhashed. It is a non-empty string that the Engine's `normalize_event_payload` accepts.\n- The payload's other fields (`event_type`, `actor_id`, `object`, `published_at`, `source_instance`, `raw_payload`) are unchanged.\n\n### Requirements: publish on change only\n\n- With a profile, a `like` publishes a `Like` only when the like is new. This covers the plain-like branch and a like that replaces a dislike.\n- With a profile, an `undo_like` publishes an `UndoLike` only when a like was actually removed.\n- A `dislike` that replaces a like publishes one `UndoLike`, with the id the matching profile `undo_like` would have used. A dislike on a video that is not liked publishes nothing. `undo_dislike` publishes nothing.\n- A request that changes nothing still returns 200 `{\"ok\": True, \"updatedAt\": ...}` and publishes nothing.\n- Anonymous `like` and `undo_like` always publish, with generation 0. Every anonymous `Like` on a video therefore carries one id, and every anonymous `UndoLike` carries another. Anonymous likes add at most +1 per video and anonymous un-likes subtract at most -1 (ADR-0001 \u00a73, accepted).\n- Error handling is unchanged: 400/404/502 paths, `DislikeLimitReached`, `EngineApiError`, and the centroids-before-write ordering.\n\n### Requirements: ranking cap\n\n- In `engine/server/data/random_videos.py`, add a module-level named constant (e.g. `POPULAR_SIGNAL_CAP = 25.0`). The popular-pool ordering becomes `(v.popularity + MIN(COALESCE(sig.signal_score, 0), <constant>)) DESC`, with the constant passed as a query parameter or interpolated from the constant, never a bare literal.\n- `interaction_signals.signal_score` stays uncapped in storage. The `interaction_signal_score` column the query returns stays the raw value.\n- The secondary likes tiebreaker is unchanged.\n\n### Unchanged (must not be modified)\n\nThe Engine's `ingest_interaction_event()`, `normalize_event_payload()`, the `_event_deltas` weights, and the stored `signal_score`.\n\n### Acceptance criteria\n\n- Posting `like` twice for one video with one profile publishes exactly one `Like`. The video's `likes_count` rises by 1 and its `signal_score` by 1.0.\n- A profile's like \u2192 undo_like \u2192 like sequence publishes Like, UndoLike, Like. The two `Like` events carry different `event_id`s, and the video ends with `signal_score` 1.0.\n- Re-sending an identical, already-published event to the Engine (a bridge retry) is reported as `duplicate: true` and changes no counts.\n- Two anonymous `like` posts for one video produce the same `event_id`, and the Engine counts the second as a duplicate.\n- `undo_like` for a video the profile does not like publishes nothing and returns 200.\n- A dislike replacing a like publishes one `UndoLike`, with the id the matching profile un-like would have used. A dislike on an unliked video publishes nothing.\n- In the popular ordering, a video with `signal_score` 1000 and `popularity` 0 ranks below a video with `popularity` 30 and no signal.\n- `delete_profile` removes the profile's `like_generations` rows.\n- The existing interaction-event tests (`tests/active/test_interaction_events.py`, `tests/active/test_internal_events.py`, `tests/active/test_random_videos.py`) and the security-bundle / frontend suites in `tests/active` still pass.\n\n### Out of scope\n\n- Backfilling or rewriting events already stored with random ids.\n- Changing Engine ingest, `_event_deltas`, or the stored `signal_score`.\n- The secondary likes tiebreaker.\n- `Comment` events.\n- Rate limiting, or requiring a profile for likes.\n- Making the likes-import path publish.\n- Closing the `max_likes` trim gap. When the trim drops a like, the Engine keeps its +1, a later un-like publishes nothing, and a re-like gets a new generation. This gap exists today and is accepted.\n\n### Consistency constraints\n\n- Match the surrounding style: stdlib HTTP handlers, `respond_json`, module-level named constants, env vars read once at startup, stdlib only (`hashlib`). Keep the fewest files, and add no new abstractions with a single implementation.\n- Backwards compatibility is not required beyond the above.\n- Line numbers drift, so re-locate code by function name.\n- Plan 14 edits other handlers in `server.py` and calls `record_like` from import, ignoring its return value. Keep the diff to `_handle_user_action`, `_store_reaction`, `record_like`, `ensure_user_schema`, `delete_profile` and `fetch_popular_videos` to limit merge conflicts.\n\n### Test and run constraints\n\n- Test trees: active `tests/active`, working `tests/tmp`, archive `tests/archive`, delete_me `delete_me`, plans `docs/project/plans`. Record: `tests/last_test_validation.json`. Output: `tests/last_test_output.txt`.\n- Run `validate_tests.py` from the worktree root (`project_dir` = `/home/enduser/code/PeerTube-browser/.worktrees/fix-13-deterministic-event-ids`).\n- Run Engine-backed test files in their own `validate_tests.py` invocations because of the Engine rate limit.\n- The worktree symlinks main's `whitelist.db`, so test Engines share it with other lanes. Tests must use unique video/actor identities, or isolated DBs, so concurrent lanes do not collide.\n- On merge, `tests/last_test_validation.json` and `tests/last_test_output.txt` will conflict. Take main's copy and re-run `validate_tests.py --compare` on the merged tree.\n\n### Baseline suite state\n\nPre-build baseline: exit code 0, variant false (the suite passes before any change).\n</requirements>\n\n<conflicts>\nnone\n</conflicts>",
    "step_2_develop_solution": "<initial_solution>\n### Approach\n\nTwo changes, one in each service. Both stay inside the six functions the requirements name, plus a small unavoidable edit to the import lines of `server.py`.\n\n**1. Client: generation table and `record_like` (`client/backend/lib/users_store.py`).** `ensure_user_schema` gets one more `CREATE TABLE IF NOT EXISTS like_generations` in the existing executescript, placed before the `local-user` cleanup. It has `user_id`, `video_id`, `instance_domain` and an integer `generation`, with `(user_id, video_id, instance_domain)` as the primary key. `record_like` stops using `ON CONFLICT ... DO UPDATE` to find out whether a like is new. It first inserts the `likes` row with `ON CONFLICT DO NOTHING` and reads the cursor's rowcount: 1 means new, 0 means the video was already liked. When the row already exists it runs the old refresh of `video_uuid` and `updated_at` as a plain UPDATE, so recency ordering and the trim behave exactly as today. When the like is new it upserts `like_generations`: insert generation 1, or on conflict set generation to generation + 1. It then reads the current generation back and returns `(new, generation)`. The trim and the trailing commit are unchanged. The trim never drops the row just inserted, because that row is the newest. The likes-import caller already ignores the result, so it keeps working without edits. An imported new like still advances that video's generation, which the plan accepts (see Risks). Nothing ever deletes from `like_generations` except `delete_profile`, so a generation survives an un-like. This covers \"increments on a new like, from 1\", \"unchanged on a re-like\", and \"the generation survives an un-like\".\n\nThe un-like side needs to read a generation, and `server.py` holds no SQL. So `users_store.py` gains one small reader function. It returns the stored generation for `(user, video_id, instance_domain)`, or 0 when there is no row. `server.py` imports it next to `record_like` and `remove_like`. `remove_like` itself is not changed.\n\n**2. Client: `_store_reaction` (`client/backend/server.py`).** Today it returns \"did a dislike remove a like\". It will return a `(changed, generation)` pair covering every branch:\n- Plain like: the result of `record_like`.\n- `undo_like`: read the generation, then `remove_like`, both inside the same `with conn` block. Returns `(removed, generation)`.\n- Dislike: in its existing write transaction, read the generation before `remove_like` and `write_dislike`. Returns `(removed, generation)`. The centroids are still computed before any write, so the error ordering is unchanged.\n- `undo_dislike`: returns `(False, 0)`.\n- Like replacing a dislike: `delete_dislike` then `record_like`. Returns `record_like`'s pair. Likes and dislikes exclude each other, so this is always new.\n\nThe generation an un-like reads is the value the matching Like got when it was recorded. Only a later new like changes it. So a Like and the un-like that ends it share a generation, and the next Like gets a different one. The docstring's `:returns:` is updated.\n\n**3. Client: `_handle_user_action`.**\n- With a profile: `publish` becomes `changed`. A replayed like, an un-like of an unliked video, a dislike of an unliked video and every `undo_dislike` publish nothing. They fall through to the existing 200 `{\"ok\": True, \"updatedAt\": ...}` response.\n- Without a profile: `publish` stays `action in (\"like\", \"undo_like\")` with generation 0. Dislike actions already require a profile, so anonymous input can only be a like or an undo_like.\n- `event_type` keeps the existing rule (`Like` for `like`, otherwise `UndoLike`), so a dislike that removed a like produces an `UndoLike`. Its generation is the one the profile's `undo_like` would have read, so the id is identical.\n- The id is `client-` plus the SHA-256 hex digest of `(actor, canonical_uuid, canonical_host, event_type, generation)`. The fields are serialised with `json.dumps` of a list, which is already imported. JSON quoting and escaping make field boundaries unambiguous whatever the field values contain.\n- The id is 71 characters of hex and contains no raw input. `normalize_event_payload` only requires a non-empty string, and `event_id` is a TEXT primary key with no length limit, so it is accepted.\n- `hashlib` is added to the stdlib imports. `uuid4` stays imported because `run_id` near the bottom of `server.py` still uses it, so the requirement to drop the import only if unused leaves it in place.\n- The other payload fields, the 400/404/502 paths, `DislikeLimitReached`, `EngineApiError` and the bridge response are untouched.\n\n**4. `delete_profile` (`client/backend/lib/profiles.py`).** One more `DELETE FROM like_generations WHERE user_id = ?` inside the existing `with conn` transaction.\n\n**5. Engine: ranking cap (`engine/server/data/random_videos.py`).** A module-level `POPULAR_SIGNAL_CAP = 25.0`. The first ORDER BY term in `fetch_popular_videos`'s inner subquery becomes `popularity + MIN(COALESCE(signal_score, 0), ?)`, with the constant bound as a query parameter. The params list now holds, in order: the optional error threshold, the cap, the inner limit, the outer limit. Getting this order right is the one fiddly part. `COALESCE` sits inside `MIN`, so SQLite's two-argument scalar `MIN` never sees NULL. The outer `interaction_signal_score` column, the stored `signal_score` and the likes tiebreaker are unchanged. A signal of 1000 now counts as 25, which ranks below popularity 30.\n\n**How the acceptance criteria follow:**\n- Double like: the second post finds the row, `new` is false, nothing is published.\n- like \u2192 undo \u2192 like: the ids use generations g, g, g+1, so the two Likes differ, the counts net +1 \u22121 +1, and `signal_score` ends at 1.0.\n- Bridge retry: the same id hits the Engine's existing `ON CONFLICT DO NOTHING` and is reported as a duplicate.\n- Anonymous: generation 0 gives one id per video, so the second post is a duplicate.\n- The un-like, dislike, ranking and `delete_profile` criteria follow directly from sections 2 to 5.\n\n**Tests:** new Client cases publish under fresh profiles, so their actor identities are unique per run. The anonymous criterion (\"the second is a duplicate\") holds on every run even against the shared `whitelist.db`. The ranking case uses an isolated in-memory Engine database, as `test_random_videos.py` already does.\n\n### Alternatives considered\n\n- **How to detect a new like.** Rejected: a SELECT for an existing row before the upsert. It adds a query and leaves a window where two concurrent requests both see \"absent\" and both publish. The conditional insert's rowcount is atomic at the statement level, so only one request ever sees \"new\".\n- **Where the un-like's generation comes from.** Rejected: widening `remove_like` to return the generation. That changes a shared helper's signature for one caller. Rejected: inline SQL in `_store_reaction`, because `server.py` has no SQL anywhere. The small reader in `users_store.py` costs one extra name on an existing import line.\n- **Hash input encoding.** Rejected: joining with a control-character separator such as `\\x1f` or `\\n`. It is only unambiguous if we can prove no field contains that character, and `video_uuid` and `instance_domain` come back from the Engine. JSON encoding needs no such proof.\n- **Keying the id on the `likes` row's rowid or timestamp.** Rejected: the row is deleted on un-like, so rowids and timestamps are not stable, and timestamps can repeat.\n- **Cap by interpolation versus a bound parameter.** Both are allowed. The parameter was chosen so the value never sits inside the SQL text. The cost is reordering the params list.\n- **Capping at ingest.** Out of scope and rejected by ADR-0001: the stored score must stay raw so the cap can change without a migration.\n\n### Risks and gotchas\n\n- **Likes that predate `like_generations`** have no row, so an un-like reads generation 0. The resulting `UndoLike` still has a unique, profile-scoped id. It cannot collide with the anonymous generation-0 ids because the actor differs. The next new like starts that video at generation 1, so the sequence stays correct.\n- **Imported likes** advance the generation without publishing. A later un-like then publishes an `UndoLike` for a Like id the Engine never saw. The count effect (\u22121) is what today's code already does, and import publishing is out of scope.\n- **The `max_likes` trim gap** remains as accepted: the Engine keeps its +1, a later un-like publishes nothing, and a re-like gets a new generation.\n- **Merge risk with plan 14:** besides the named functions, `server.py` gets two import-line edits (`hashlib`, and the new reader on the `users_store` import). If they conflict, resolve by union. `record_like`'s return value is additive, so plan 14's import caller, which ignores it, is unaffected.\n- **Test runs publish into the shared `whitelist.db`.** Any anonymous Like or UndoLike a test sends for a real video permanently takes that video's single anonymous Like and UndoLike ids. New tests must therefore publish as fresh profiles or use an isolated Engine DB. The existing frontend-reactions tests assert browser-store state, not Engine counts, so they are unaffected.\n- **Concurrency on the one shared SQLite connection** is unchanged. The existing rat-tail about unserialised read, compute and write for dislikes still applies.\n\n### Tradeoffs the operator accepts\n\n- **Anonymous likes collapse to at most +1 per video, and un-likes to at most \u22121.** Once an anonymous Like and UndoLike have both been stored for a video, anonymous visitors contribute nothing further to it, ever. This is ADR-0001 \u00a73 as accepted.\n- **The cap of 25.0 is a deliberate simplification.** One named constant bounds the signal's effect on ordering. It does nothing to stop the likes tiebreaker, which is uncapped and out of scope, from being inflated among videos that tie on the first term. To raise or lower the cap, edit the constant. If it ever needs to be configurable, the upgrade path is an env var read once at startup.\n- **Events already stored with random ids stay as they are.** No backfill.\n</initial_solution>\n\n<conflicts>\nnone\n</conflicts>",
    "step_3_identify_impacts": "<impacts>\n<impact path=\"client/backend/lib/users_store.py\" element=\"ensure_user_schema() (lines 10-63): new like_generations table\">\n**What changes.** The existing `executescript` gets one more `CREATE TABLE IF NOT EXISTS like_generations (user_id TEXT NOT NULL, video_id TEXT NOT NULL, instance_domain TEXT NOT NULL, generation INTEGER NOT NULL, PRIMARY KEY (user_id, video_id, instance_domain))`. It goes after `dislike_profiles` (lines 53-58) and before the `local-user` cleanup comment and DELETEs (lines 59-61), as the plan says. The docstring at line 11 (\"Create the users, likes, profile, block and dislike tables if missing.\") should also name the like generations table. No `local-user` DELETE is needed for the new table, because no such rows can exist in a table that is new.\n\n**What depends on it.**\n- `client/backend/server.py:1179` (`main`) runs it once at startup on `users.db`, so the live DB gets the table on the first restart. No migration step is needed.\n- `tests/active/conftest.py:73` (`client_backend`) and `:160` (`_engine_client`) call it.\n- `tests/active/test_server.py:266` (`_client_backend`) calls it.\n- `delete_me/test_12_*.py` and `delete_me/test_probe_phase3_http.py` call it. These are scratch copies and are not collected.\n- Every later `record_like` and `delete_profile` now needs the table.\n\n**Regression risk: low.** `CREATE TABLE IF NOT EXISTS` is idempotent. A DB on which this function never ran would now fail in `record_like` and `delete_profile` with \"no such table: like_generations\". I found no such path: every connection above runs the schema first, and the `_seed_like` helpers write to fixture DBs that already have it. Do not confuse this with `engine/server/data/users.py:11`, the Engine's separate `ensure_user_schema`, which is untouched.\n</impact>\n<impact path=\"client/backend/lib/users_store.py\" element=\"record_like() (lines 79-117): new-like detection, generation upsert, returns (new, generation)\">\n**What changes.**\n- The one `INSERT ... ON CONFLICT ... DO UPDATE` (lines 94-102) becomes `INSERT ... ON CONFLICT(user_id, video_id, instance_domain) DO NOTHING`. The code reads `cursor.rowcount`: 1 means a new like, 0 means the row already existed.\n- On 0, a plain `UPDATE likes SET video_uuid = ?, updated_at = ? WHERE user_id = ? AND video_id = ? AND instance_domain = ?` keeps today's recency refresh.\n- On 1, it runs `INSERT INTO like_generations ... VALUES (?, ?, ?, 1) ON CONFLICT(...) DO UPDATE SET generation = like_generations.generation + 1`.\n- It then reads the generation back.\n- The return annotation changes from `-> None` to `-> tuple[bool, int]`, and the docstring (line 86) gains `:returns:`.\n- The `max_likes` trim (103-116) and `conn.commit()` (117) are unchanged.\n- `connect_db` (`server.py:144`) uses the default isolation level, so the conflicting INSERT reports rowcount 0. The UPSERT syntax is already in use in this file.\n\n**What depends on it.** Five callers:\n- `server.py:846`, plain like in `_store_reaction`. It now consumes the result.\n- `server.py:869`, a like replacing a dislike. It now consumes the result.\n- `server.py:898`, `_handle_likes_import`. It ignores the result. Plan 14 also edits this handler.\n- `tests/active/test_profiles.py:44` (`_seed_like`), which ignores it.\n- `tests/active/test_frontend_profile.py:109` (`_seed_like`), which ignores it.\n\n**Transaction behaviour.**\n- `get_or_create_user` (line 76) commits by itself when it inserts a user.\n- The final commit inside `record_like` commits the caller's enclosing `with conn:` early. That ordering already exists and is documented in `docs/project/plans/archive/03-like-dislike.md:430`: `delete_dislike` runs first, so this commit covers both.\n- The generation upsert and read-back happen before that commit, so they are atomic with the likes INSERT.\n\n**Regression risk: medium.**\n1. The plan says \"the trim never drops the row just inserted\". That holds for a single like. It does not strictly hold in a bulk import: up to `MAX_CLIENT_LIKES = 200` (`server.py:52`) records can go in against `MAX_LIKES = 100` (`server.py:51`), in one `with conn:`, and many share one `now_ms()`. A tie at the boundary can therefore trim a row whose generation was just advanced. That is harmless, since the next new like takes generation+1, but the plan's claim holds only for single likes.\n2. `clear_likes` (the reset) leaves `like_generations` in place, so a re-like after a reset is new and publishes a fresh `Like`. See the reset entry: this is a repeatable +1 loop.\n3. The read-back must work whether or not the connection has a `row_factory`: the test helpers set `sqlite3.Row`, raw connections do not. Use `row[0]`.\n4. \"New\" must come from the INSERT's own rowcount, not from a SELECT beforehand, or two concurrent likes could both publish.\n</impact>\n<impact path=\"client/backend/lib/users_store.py\" element=\"new generation reader function (next to remove_like, line 159)\">\n**What changes.** A new function returns the stored `generation` for `(user_id, video_id, instance_domain)`, or 0 when there is no row. To match the file's style:\n- positional `conn, user_id, video_id, instance_domain`, so it can be called as `reader(conn, profile_id, *key)` the way `remove_like` is;\n- a docstring with `:returns:`;\n- no commit (\"inside the caller's transaction\", like `remove_like`).\n\n**What depends on it.** `_store_reaction`'s undo_like and dislike branches, through a new name on the `lib.users_store` import (`server.py:37-39`). New tests may call it directly.\n\n**Regression risk: low.** It should be read before `remove_like`. The value is the same either way, because `remove_like` never touches `like_generations`, but reading first keeps the intent clear. Returning 0 for a missing row gives the same generation anonymous actors use. That is safe only because the hashed actor differs: the profile id versus `\"anonymous\"`.\n</impact>\n<impact path=\"client/backend/lib/users_store.py\" element=\"remove_like() (159-168), clear_likes() (153-156), video_reaction(), fetch_recent_likes(), load_liked_keys(), get_or_create_user(): unchanged\">\n**What changes.** Nothing. The plan keeps `remove_like`'s signature. `remove_like` still does not commit, and its callers hold `with conn:`.\n\n**What depends on it.**\n- `remove_like` is called at `server.py:848` (undo_like) and `:861` (dislike).\n- `clear_likes` is called at `server.py:988` (reset). It deletes only `likes` and so deliberately leaves `like_generations`. That is required for \"the generation survives\", but it opens the reset loop described below.\n\n**Regression risk: none in code.** Listed so the reset interaction is on record.\n</impact>\n<impact path=\"client/backend/server.py\" element=\"stdlib import block (lines 5-22): add hashlib; keep uuid4\">\n**What changes.** `import hashlib` goes in alphabetical order between `argparse` (line 5) and `ipaddress` (line 6). Plan 12 has since added `ipaddress` at line 6, so the block reads argparse, ipaddress, json, ...\n\n`from uuid import uuid4` (line 21) must stay: `run_id = str(uuid4())` at line 1155 still uses it. The requirement is \"drop uuid4 if unused\", and it is still used.\n\n**What depends on it.** The event-id derivation in `_handle_user_action`.\n\n**Regression risk: nil.** This is a merge point with plan 14 if plan 14 touches the import block; resolve by union.\n</impact>\n<impact path=\"client/backend/server.py\" element=\"lib.users_store import (lines 37-39): add the generation reader\">\n**What changes.** The reader's name is added to the parenthesised import, which is alphabetised today: `clear_likes, ensure_user_schema, fetch_recent_likes, get_or_create_user, load_liked_keys, record_like, remove_like, video_reaction`.\n\n**What depends on it.** `tests/active/conftest.py:39` (`import server as client_server`) and `test_server.py:47`. A misspelt name raises ImportError, which breaks all of `tests/active`.\n\n**Regression risk: low.** A mistake fails loudly at import. This is a merge point with plan 14.\n</impact>\n<impact path=\"client/backend/server.py\" element=\"ClientBackendHandler._store_reaction() (lines 831-870): returns (changed, generation)\">\n**What changes.** The return type changes from `bool` to a pair, and `:returns:` (line 837, \"Whether a dislike removed a like.\") is rewritten. Branch by branch:\n- **Plain like** (line 846): the value of `record_like` must be captured inside the `with conn:` (lines 844-848) and returned. Today the function returns `False` at line 849, after the `with` block.\n- **undo_like** (line 848): read the generation, then `removed = remove_like(...)`, both inside the same `with`. Return `(removed, generation)`.\n- **dislike** (lines 855-863): the `DislikeLimitReached` check (856-857) and `compute_dislike_centroids` (859) stay before any write. Inside the `with` at line 860, read the generation, then `remove_like` and `write_dislike`. Return `(like_removed, generation)`.\n- **The shared tail** (lines 864-870) serves both `undo_dislike` and a like replacing a dislike. It must return `record_like`'s pair when `action == \"like\"` and `(False, 0)` for `undo_dislike`. Today it returns `False` for both, so this branch is the easy one to get wrong.\n\n**Exclusivity.** The plan says a like replacing a dislike is always new. That holds only because every path removes the other reaction; nothing in `lib/dislikes.py` enforces it at the DB level. If a `likes` row did co-exist, this branch would return `new=False` and publish nothing, which is still correct. `dislikes.py`'s `write_dislike` and `delete_dislike` do not commit, so the transaction is unchanged.\n\n**What depends on it.** Only `_handle_user_action` (line 787). The rat-tail comment at lines 853-854 stays true.\n\n**Regression risk: medium.** This is where \"a Like and its un-like share a generation\" either holds or fails. On the one shared `check_same_thread=False` connection of a `ThreadingHTTPServer`, two concurrent undo_likes can both read g, but only one `remove_like` sees rowcount 1, so only one publishes. A concurrent like and undo is the same class of race as the existing rat-tail.\n</impact>\n<impact path=\"client/backend/server.py\" element=\"ClientBackendHandler._handle_user_action() (lines 731-829): publish gating and derived event_id\">\n**What changes.**\n- Line 784, `publish = action in (\"like\", \"undo_like\")`, stays as the anonymous default, with generation 0.\n- In the profile branch (785-795), `like_removed = self._store_reaction(...)` becomes `changed, generation = ...`, and line 795 `publish = publish or like_removed` becomes `publish = changed`. The comment at line 794 needs rewording.\n- Line 802, `\"event_id\": f\"client-{uuid4()}\"`, becomes `\"client-\" + hashlib.sha256(json.dumps([actor, canonical_uuid, canonical_host, event_type, generation]).encode(\"utf-8\")).hexdigest()`.\n- `actor` is the same expression as line 804, `profile_id or \"anonymous\"`, and should be computed once and used in both places.\n- `event_type` (line 800) must be computed before the id.\n- The docstring \"Handle handle user action.\" (line 732) could state the publish rule.\n- The comment at lines 753-754 stays true.\n\n**Behaviour changes callers can see.**\n- With a key, a repeat `like`, an `undo_like` of an unliked video, a dislike of an unliked video, and every `undo_dislike` answer 200 `{ok, updatedAt}` and publish nothing.\n- On `unpublished_client` (activitypub mode), a repeat keyed like or undo_like used to answer 502 and now answers 200.\n- Keyless likes and un-likes still always publish, so they still answer 502 on an unpublished Client. `test_frontend_reactions.py:249-258` relies on that.\n\n**Hashing details.**\n- The `json.dumps` defaults (`ensure_ascii=True`, `\", \"` separators) are part of the id and must never change.\n- `generation` must be an `int`, never a `bool` or `str`.\n- `canonical_uuid` can be `\"\"` (line 774). The Engine then rejects the event with \"Missing object.video_uuid\" (`interaction_events.py:208-209`), which is unchanged behaviour.\n- The id is 71 characters and is accepted by `normalize_event_payload` (lines 194-198: a non-empty string after `_clean_text`, no length cap) and by `event_id TEXT PRIMARY KEY` (line 24).\n- `raw_payload: body` (line 812) is still sent raw. That is out of scope.\n\n**What depends on it.**\n- `sendUserAction` in `client/frontend/src/data/user-actions.ts:33` checks only `response.ok`.\n- The Engine answers a duplicate with 200 `ok: true` (`internal_events.py:84-93`), and `_publish_to_engine_bridge` maps that to `ok=True`. So a replayed anonymous like answers 200 `bridge_ok: true`.\n- The smokes: see their entries.\n\n**Regression risk: medium-high.** Any of these silently reopens the finding or breaks the contract:\n- publishing when `changed` is False;\n- hashing `None` as the actor instead of `\"anonymous\"`;\n- using a different generation for an undo than for its Like;\n- letting the serialisation drift.\n\nNo existing test exposes event ids.\n</impact>\n<impact path=\"client/backend/server.py\" element=\"_handle_user_profile_reset() (lines 976-993) with clear_likes(): repeatable +1 loop (Step 4 finding, not in the plan's Risks)\">\n**What changes.** Nothing in the plan's code. But its interaction with the new gating matters. Reset deletes every `likes` row, keeps `like_generations`, and publishes nothing. One profile can therefore repeat like \u2192 `POST /api/user-profile/reset` \u2192 like. Each like is \"new\", takes generation+1, gets a fresh id, and adds +1 to `likes_count` and `signal_score`. The only limit is the general per-route `RateLimiter` (lines 352-357).\n\n**What depends on it.** `test_profiles.py`'s `PROFILE_ROUTES` (line 31) uses the route, and the frontend reset flow.\n\n**Regression risk: not a regression.** Today every like adds +1. But the plan's \"Risks\" does not record this as an unbounded one-profile loop. The 25.0 cap limits the effect on ordering, but not the shown likes count or the likes tiebreaker (`random_videos.py:45,248`).\n\n**Uncertain: operator decision.** Accept it in \"Tradeoffs\", or change the gating (for example the \"open\" flag on `like_generations` proposed in the prior Step 4 record). I list it so it is not missed.\n</impact>\n<impact path=\"client/backend/server.py\" element=\"_handle_likes_import() (lines 872-900): record_like caller, and the repeatable \u22121 loop\">\n**What changes.** Nothing in code. `record_like` at line 898 now returns a pair, which is ignored, and `imported += 1` is unchanged. The whole loop runs inside one `with conn:` while `record_like` commits on each iteration, as today.\n\n**What depends on it.**\n- Plan 14 edits this handler.\n- `tests/active/test_profiles.py:245-253` and `tests/active/test_frontend_reactions.py:350-374` exercise it, on `unpublished_client`.\n\n**Risk: low for code, but a behaviour to record.**\n- Each imported new like advances the generation without publishing. The plan accepts this.\n- It is also repeatable. Import video X \u2192 `undo_like` X finds the row, publishes an `UndoLike` with a fresh generation, and takes \u22121 off X \u2192 import again \u2192 undo again. Each pass removes another 1 from any video other people liked, down to the Engine's `MAX(0, \u2026)` floor (`interaction_events.py:124-127`).\n- This gets around the plan's own rule that \"an un-like of an unliked video publishes nothing\".\n- Today's code allows the same, so it is not a regression, but the plan records only the single-shot case.\n- See also the tie-trim note in the `record_like` entry.\n</impact>\n<impact path=\"client/backend/server.py\" element=\"_publish_to_engine_bridge() / _publish_event() (lines 1032-1064): unchanged\">\n**What changes.** Nothing.\n\n**What depends on it.** It limits how tests can observe duplicates. It returns `{\"ok\", \"response\"}`, and the handler exposes only `ok`, `bridge_ok` and `bridge_error`. So \"the second is a duplicate\" cannot be read from the Client response. Tests must either read the Engine's `interaction_raw_events`/`interaction_signals`, post to `/internal/events/ingest` directly, or capture payloads with a stub Engine.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"client/backend/lib/profiles.py\" element=\"delete_profile() (lines 69-80)\">\n**What changes.** One more `conn.execute(\"DELETE FROM like_generations WHERE user_id = ?\", (profile_id,))` inside the `with conn:`. It belongs next to the `likes` delete at line 78, since both key on `user_id`. The docstring (\"every row keyed to it\") stays true.\n\n**What depends on it.**\n- `server.py:340-345` (`POST /api/profile/delete`).\n- `tests/active/test_profiles.py:197-217`.\n- The profile-delete steps in `tests/run-installers-smoke.sh:449,683` and `tests/run-arch-split-smoke.sh:617`.\n\n**Regression risk: low.** It only fails on a DB where the table was never created, and no such path exists. Because the delete runs in one transaction, a failure would roll back the whole profile delete.\n</impact>\n<impact path=\"engine/server/data/random_videos.py\" element=\"new module-level POPULAR_SIGNAL_CAP = 25.0\">\n**What changes.** A named constant goes after the imports (after line 9), with a `#` comment above it. The module has no constants today; the house style can be seen in `interaction_events.py:13-14`.\n\n**What depends on it.** `fetch_popular_videos` and the new ranking test, which may import it.\n\n**Regression risk: nil.**\n</impact>\n<impact path=\"engine/server/data/random_videos.py\" element=\"fetch_popular_videos() (lines 195-303): capped ORDER BY term and params order\">\n**What changes.**\n- Line 247, `(v.popularity + COALESCE(sig.signal_score, 0)) DESC`, becomes `(v.popularity + MIN(COALESCE(sig.signal_score, 0), ?)) DESC`.\n- Line 200 becomes `[POPULAR_SIGNAL_CAP, limit, limit]`, and line 203 becomes `[error_threshold, POPULAR_SIGNAL_CAP, limit, limit]`. That matches the placeholder order: the WHERE `?` from `{error_clause}` (245, inner subquery), then the cap (247), then the inner `LIMIT ?` (252), then the outer `LIMIT ?` (262).\n- Line 234 (`interaction_signal_score`, raw) and the tiebreaker at line 248 are unchanged.\n- The docstring \"by likes/views\" (198) could mention the capped signal.\n\n**What depends on it.**\n- `engine/server/api/server.py:90,398` wires it in.\n- `engine/server/api/recommendations/builder.py:109-113` wraps it with `error_threshold=settings.video_error_threshold`. That value is `VIDEO_ERROR_THRESHOLD = 3` (`server_config.py:387`), so production always takes the 4-parameter branch.\n- `candidates/popular_videos.py:52` consumes the pool.\n- `tests/active/test_random_videos.py:85` calls it without a threshold, which is the 3-parameter branch.\n\n**Regression risk: medium.**\n- A wrong params order raises nothing, because every placeholder takes a number. It silently turns the cap into a LIMIT or a threshold.\n- The tested branch is not the production branch, so the new test must cover both.\n- Two-argument `MIN` is SQLite's scalar function, which returns NULL if any argument is NULL. `COALESCE` inside it prevents that.\n- On the live dataset, videos with a signal above 25 drop in the popular pool. That is intended.\n</impact>\n<impact path=\"engine/server/data/random_videos.py\" element=\"fetch_random_rows() (line 45 likes), fetch_recent_videos(), cache readers: unchanged\">\n**What changes.** Nothing. `(v.likes + COALESCE(sig.likes_count, 0)) AS likes` is the displayed likes figure, not the ranking signal.\n\n**Regression risk: none.** Listed so the cap is not applied to the wrong query.\n</impact>\n<impact path=\"engine/server/data/interaction_events.py\" element=\"ingest_interaction_event() / normalize_event_payload() / _event_deltas() / prune_interaction_raw_events(): unchanged, relied upon\">\n**What changes.** Nothing; the requirements forbid changes here.\n\n**What depends on it.**\n- The collapsing relies on `ON CONFLICT(event_id) DO NOTHING` (line 85) and on the duplicate result (lines 100-109).\n- The deltas are Like +1.0, UndoLike \u22121.0 (lines 255, 262), floored by `MAX(0, \u2026)` (124-127).\n- The prune (150-189) strips payload, actor and source but keeps the row, and with it the `event_id`, so derived ids keep collapsing replays after retention.\n\n**Regression risk: none from this build.**\n</impact>\n<impact path=\"engine/server/api/handlers/internal_events.py\" element=\"handle_internal_events_ingest() duplicate accounting (lines 56-94): unchanged\">\n**What changes.** Nothing.\n\n**What depends on it.** The \"bridge retry is reported as duplicate\" and \"second anonymous like is a duplicate\" criteria. They can be observed through `results[i].duplicate` and `duplicates`. The route is served only in `ENGINE_INGEST_MODE=bridge`, which the conftest `engine` fixture sets (line 105).\n\n**Regression risk: none.**\n</impact>\n<impact path=\"engine/server/data/users.py\" element=\"Engine-side ensure_user_schema() (line 11) / record_like() (line 47): NOT touched\">\n**What changes.** Nothing. It has the same function names as the Client module, so a `def record_like` grep finds both. The one to edit is `client/backend/lib/users_store.py:79`.\n\n**Regression risk: none, provided the right file is edited.**\n</impact>\n<impact path=\"client/backend/lib/engine_api_client.py\" element=\"resolve_video_seed() (lines 66-89): unchanged; shape needed by a stub Engine\">\n**What changes.** Nothing.\n\n**What depends on it.** Any new isolated test that uses a stub Engine must answer `POST /internal/videos/resolve` with 200 `{\"video\": {\"video_id\", \"instance_domain\", \"video_uuid\", \"video_url\"}}`. A 404 becomes \"not found\"; any other status or a non-dict raises `EngineApiError`. The stub must also accept `POST /internal/events/ingest` and record the `event_id`. I verified this shape in the source; the prior record had it as unverified.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"client/frontend/src/data/user-actions.ts\" element=\"sendUserAction() (lines 18-38): unchanged\">\n**What changes.** Nothing. It treats any 2xx as success, so the new 200 `{ok, updatedAt}` answer to a keyed no-change action is accepted.\n\n**Side effect.** A keyed repeat like on a Client that cannot publish no longer throws \"Failed to send action\". That is correct.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"tests/active/test_random_videos.py\" element=\"existing popular tests (108-122), helpers _two_video_db/_set_views/_event (34-77); home for the ranking-cap test\">\n**What changes.** The existing tests stay green: they use signal 1.0, which is under the cap, and assert the raw `interaction_signal_score == 1.0` (line 119). The new criterion fits here:\n- Use `_two_video_db`, then `UPDATE videos SET popularity` to 0 and 30.\n- Set the signal to 1000 with a direct `INSERT INTO interaction_signals`, rather than 1000 ingests.\n- Run with and without `error_threshold`. `_set_views` sets `error_count = 0`, so a threshold of 1 keeps both rows.\n\n**Correction to the plan.** The plan says the file uses \"an isolated in-memory Engine database\". It actually uses a file DB under `tmp_path`, built by `ATTACH` of `whitelist.db` read-only (lines 36-52). It is still isolated from the live DB's writes, but it needs `whitelist.db` to exist.\n\n**What depends on it.** `.un/skills/devsecops/config.json:87-88` maps it to `random_videos.py`.\n\n**Regression risk: low.**\n</impact>\n<impact path=\"tests/active/test_profiles.py\" element=\"_seed_like (41-46), _rows_for (59-67), test_deleting_a_profile_removes_its_rows_and_keeps_anothers (197-217)\">\n**What changes.**\n- `_seed_like` now also writes a `like_generations` row and ignores the return value.\n- This is the natural home for the \"`delete_profile` removes the profile's `like_generations` rows\" criterion: add a `like_generations` count to `_rows_for`.\n- The four equality asserts (lines 205, 209, 215, 216) must then change together to include `\"like_generations\": 1` (or 0).\n- The comment at line 201 (\"all three tables\") becomes \"four\".\n\n**What depends on it.** `config.json:18-21` maps it to `server.py`, `profiles.py` and `users_store.py`.\n\n**Regression risk: low.** A partial update of those dicts fails the test.\n</impact>\n<impact path=\"tests/active/test_profiles.py\" element=\"test_a_keyed_upnext_request_is_seeded_... (264-282) and test_a_keyed_search_marks_... (291-313)\">\n**What changes.** Nothing.\n- The first like by a fresh profile is new, so line 300 still expects 502 on `unpublished_client`.\n- A dislike of an unliked video still answers 200.\n- Line 277 does not assert status.\n\n**Regression risk: none.** Line 300 guards against a like wrongly treated as not new, which would answer 200.\n</impact>\n<impact path=\"tests/active/test_frontend_profile.py\" element=\"_seed_like (106-111)\">\n**What changes.** Nothing required. It calls `record_like` on a fixture DB that already has the table, and ignores the result.\n\n**Regression risk: low.**\n</impact>\n<impact path=\"tests/active/test_frontend_reactions.py\" element=\"keyless tests (202-258), keyed sequence (264-308), keyed-vs-keyless store test (311-340), card test (396-409)\">\n**What changes.** Nothing in the file. Behaviour against the shared live `whitelist.db` does change.\n\n**Keyless tests.** They publish anonymous Like/UndoLike on the first rows of `_videos(dataset, n)`, which are the same every run.\n- After this build each such video has exactly one anonymous Like id and one anonymous UndoLike id.\n- The first run nets +1\u22121. Every later run gets duplicates, which still answer 200 `ok`, and the assertions check only `\"ok\"` and browser-store state.\n- The finally-block undos at lines 213-214 and 239-240 become duplicates, so they have no effect after the first run.\n\n**Keyed sequence (264-303).** Each step is a real change, or answers 200 without publishing:\n- like: g1, published;\n- dislike: removes the like, publishes UndoLike at g1;\n- undo_dislike: 200, nothing published;\n- out-of-band dislike on the now unliked video: 200;\n- like replacing that dislike: g2, published;\n- undo_like: UndoLike at g2.\n\nSo `all(\"ok\" in a ...)` (line 303) holds.\n\n**Card test (406).** It still expects a 502 for a fresh profile's first like on `unpublished_client`.\n\n**Regression risk: low for the assertions, medium for shared data.**\n- A test asserting that \"the first anonymous like counts +1\" would fail on every run after the first.\n- A run that dies between an anonymous Like and its UndoLike leaves +1 on that video for good, because every later anonymous Like is a duplicate. This is accepted under ADR-0001 \u00a73.\n</impact>\n<impact path=\"tests/active/test_dislikes.py\" element=\"test_a_video_s_reaction_follows_... (68-87), _profile_disliking (118-123)\">\n**What changes.** Nothing.\n- The dislike of a liked video still publishes, and line 77 accepts `in (200, 502)`.\n- `undo_dislike` answers 200 (line 82).\n- A dislike of an unliked video answers 200 (line 84, and `_profile_disliking` at line 122).\n- Lines 74, 79 and 86 do not assert status.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"tests/active/test_server.py\" element=\"keyed likes loop (86-102) and _client_backend / EngineStub harness (262-326)\">\n**What changes.** Nothing.\n- Each like in the loop is on a distinct row, the set removes duplicates, and status is not asserted.\n- The dislikes answer 200 (line 102).\n- The `_client_backend(tmp_path, engine_base, rate_limiter)` helper plus the `EngineStub` pattern (307-320) is the ready-made isolated harness for the new Client acceptance tests. Extend the stub with `do_POST` for resolve and ingest.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"tests/active (new test file(s) for this build)\" element=\"new Client acceptance tests: publish-on-change, derived ids, dislike UndoLike id, anonymous duplicate, delete_profile\">\n**What changes.** New tests. There are two ways to observe events:\n- (a) `engine_client`, reading the live `interaction_raw_events` by a fresh profile id through the `dataset` connection;\n- (b) the stub Engine from `test_server.py`, which records posted `event_id`s. This avoids the shared DB and the Engine rate limit.\n\n**Constraints.**\n- Profile tests must mint fresh profiles.\n- An anonymous test may assert only \"same id\" or \"second is a duplicate\", never \"first counts\".\n- Tests that publish real Likes under (a) must withdraw them in a `finally`, as the existing tests do.\n\n**What depends on it.**\n- `validate_tests.py` collects `tests/active/test_*.py` (and `tests/tmp`).\n- Engine-backed files run in their own invocation.\n- New files are unmapped in `.un/skills/devsecops/config.json` until harvest.\n\n**Regression risk: medium for suite stability** under (a); low under (b).\n</impact>\n<impact path=\"tests/run-arch-split-smoke.sh\" element=\"client_user_action like + validate_user_action_response (330-346, 584-602), profile delete (617)\">\n**What changes.** Nothing. The like by the freshly minted profile is new, so it publishes and `ok`, `bridge_ok` and an empty `bridge_error` hold.\n\nIf minting fails, the like is anonymous. After the first run it is then a duplicate, which still returns `bridge_ok: true`.\n\n**Regression risk: low.**\n</impact>\n<impact path=\"tests/run-installers-smoke.sh\" element=\"like flow (649-686), verify_engine_event_recorded (~459-496), cleanup_engine_test_events (~498-585), delete_client_test_profile (~444-457)\">\n**What changes.** Nothing.\n- The fresh profile's first like is new and publishes.\n- The raw row exists under `actor_id = profile_id`.\n- The cleanup deletes raw rows by actor and recomputes, which frees that derived id. That is harmless, because the profile is deleted and cannot replay.\n- The profile delete now also removes `like_generations`.\n\n**Regression risk: low.**\n</impact>\n<impact path=\"engine/server/db/jobs/tests/test-interaction-events.py\" element=\"ingest contract script\">\n**What changes.** Nothing. The acceptance criteria require it to keep passing. It is not collected by `validate_tests.py`, so it must be run explicitly. It does not reference Client event ids or `fetch_popular_videos` (grep).\n\n**Regression risk: none.**\n</impact>\n<impact path=\"engine/server/db/jobs/tests/test-security-bundle.py\" element=\"security bundle checks\">\n**What changes.** Nothing. A grep found no reference to popular ordering, `signal_score`, Client ids or user-action. It must be run explicitly.\n\n**Regression risk: none expected.**\n</impact>\n<impact path=\".un/skills/devsecops/config.json\" element=\"test_groups (test_profiles 18-21, groups at 37-40/45-46/56-85 naming server.py/users_store.py/profiles.py, test_random_videos 87-88)\">\n**What changes.** Nothing in this worktree. The existing mappings already re-run the affected groups when any of the four source files changes. A new test file needs an entry at harvest.\n\n**Regression risk: low.**\n</impact>\n<impact path=\"tests/last_test_validation.json\" element=\"tracked suite record\">\n**What changes.** The post-build run rewrites it. It conflicts on merge: take main's copy and re-run `validate_tests.py --compare`.\n\n**Regression risk: none functionally.**\n</impact>\n<impact path=\"tests/last_test_output.txt\" element=\"tracked captured output\">\n**What changes.** Rewritten by the post-build run. Resolve its merge conflict the same way as `last_test_validation.json`.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"delete_me/server.py.bak*\" element=\"stale copies of server.py matched by grep\">\n**What changes.** Nothing. They are backups under `delete_me/` that match every symbol grep here (`record_like`, `_store_reaction`, `uuid4`). They must not be edited in place of `client/backend/server.py`.\n\n**Regression risk: none.**\n</impact>\n</impacts>\n\n<docs_checklist>\n<doc path=\"client/README.md\">\n**Line 19 (`POST /api/user-action`).** It reads \"A like publishes its event and is kept server-side only when a profile key is sent\", which implies every like publishes. Reword it to say:\n- With a key, a `like` publishes a `Like` only when the profile did not already like the video.\n- An `undo_like` publishes an `UndoLike` only when a like was removed.\n- A request that changes nothing answers 200 and publishes nothing.\n- Without a key every like and un-like publishes, under one fixed id per video and event type, so repeats are duplicates.\n- Event ids are `client-` plus the SHA-256 of actor, video, event type and like generation.\n\n**Line 13 (`POST /api/profile/delete`).** Optionally add \"like generations\" to the list of what is removed.\n</doc>\n<doc path=\"DEPLOYMENT.md\">\n**Lines 259-261.** Optionally add that the Client backend publishes a profile's `Like`/`UndoLike` only on a real state change, with derived event ids, so replays collapse at the Engine's ingest.\n\n**Line 267.** Optionally add that the popular ordering adds at most 25.0 of a video's interaction signal (`POPULAR_SIGNAL_CAP` in `engine/server/data/random_videos.py`), and that `users.db` gains a `like_generations` table created at startup, with no migration step.\n</doc>\n<doc path=\"engine/server/api/recommendations/docs/OVERVIEW.md\">\n**Line 99** (\"popular pool: top by likes/views\"): state that the pool is ordered by `popularity` plus the interaction signal capped at `POPULAR_SIGNAL_CAP` (25.0), then by likes, views and recency.\n</doc>\n<doc path=\"engine/server/api/recommendations/docs/PIPELINE_DIAGRAM.md\">\n**Line 29** (`popular<br/>top likes/views`): optionally align it with the capped-signal ordering. This is cosmetic.\n</doc>\n<doc path=\"CONTEXT.md\">\n**Verify only.** **Interaction event** (line 6) already says ids are \"derived, never random\", and **Interaction signal** (line 7) already says the popular ordering adds at most a fixed cap. Both match the build.\n\nOptionally define **Like generation**: the per-profile, per-video counter that tells one like from the next, survives un-likes and resets, and is removed with the profile.\n</doc>\n<doc path=\"docs/project/adr/0001-derived-interaction-event-ids.md\">\nThe decision is unchanged. Optionally add to Consequences:\n- the chosen like-instance scheme (the Client's `like_generations`, kept through un-like and reset, deleted with the profile);\n- that likes predating the table un-like at generation 0;\n- that imported likes advance the generation without publishing;\n- the reset and import loops, if the operator accepts them rather than closing them.\n</doc>\n<doc path=\"docs/project/issues/01-deterministic-event-ids.md\">\nAt harvest on main: tick the acceptance criteria, set `Status:` to `bug, complete`, and move the file to `docs/project/issues/archive/` per `docs/project/triage-labels.md`.\n</doc>\n<doc path=\"docs/project/plans/13-deterministic-event-ids.md\">\nAt harvest: mark it delivered, point it to `16-13-deterministic-event-ids.md`, and archive it. Also record:\n- The answer to its line 97: a profile-deletion path exists (`delete_profile`) and now removes `like_generations`.\n- `clear_likes` (reset) intentionally keeps generations.\n</doc>\n<doc path=\"docs/project/roadmap.md\">\nOptional out-of-scope follow-ups:\n- Close the reset (+1) and import\u2192undo (\u22121) loops and the `max_likes` trim gap, for example with an \"open\" flag on `like_generations`.\n- Decide whether the likes import should publish.\n- Bound the popular likes tiebreaker.\n</doc>\n</docs_checklist>\n\n<highest_risk>\nclient/backend/server.py `_handle_user_action()`: this is the security fix itself. Publishing when `changed` is False, hashing a different actor from `actor_id` (`None` instead of `\"anonymous\"`), a non-int `generation`, or drift in the `json.dumps` defaults would each silently reopen the finding or break id stability for good. No existing test exposes event ids.\nengine/server/data/random_videos.py `fetch_popular_videos()`: every placeholder takes a number, so a wrong params order raises nothing and quietly turns the cap into a LIMIT or an error threshold. Production always takes the `error_threshold` branch (`VIDEO_ERROR_THRESHOLD = 3` via `builder.py:109-113`), while existing tests take only the other branch, so both need a test.\nclient/backend/server.py `_store_reaction()` with client/backend/lib/users_store.py `record_like()`: a Like and its un-like must share a generation. The value has to be captured inside `with conn:` blocks that today end in a bare `return False`, and the shared `undo_dislike`/like-replacing-dislike tail must return different things by action. Separately, the reset\u2192re-like (+1) and import\u2192undo_like (\u22121) loops stay open and repeatable per profile, which the plan's Risks section does not record. The operator needs to accept them or close them.\n</highest_risk>",
    "step_4_reassess": "<summary>\nI checked the inventory against the tree. Every claim I checked holds. I opened `users_store.py` in full. In `server.py` I read the imports (5-39), `connect_db` (142-146), `_handle_user_action` (731-829), `_store_reaction` (831-870), `_handle_likes_import` (872-900), the reset handler (976-993) and `run_id` (1155, used at 1198 and 1213). I also read `delete_profile` in `profiles.py` (69-80), `fetch_popular_videos` in `random_videos.py` (195-265), and the `test_profiles.py` helpers (41-67 and the \"all three tables\" comment at 201). A search outside `delete_me/` found nothing else that writes to `likes`. The only writers are `record_like`, `remove_like`, `clear_likes`, `delete_profile` and the `local-user` cleanup, and the inventory covers all of them. The Engine's `users.py` duplicate is correctly marked as untouched. The two loops the previous Step 4 raised are now inventory entries: reset \u2192 re-like gives +1 per pass, and import \u2192 undo_like gives \u22121 per pass. Both are still left as an operator decision. The inventory has converged.\n<question id=\"1\">\nYes. Each acceptance criterion follows from the code as it stands. `INSERT ... ON CONFLICT DO NOTHING` followed by a rowcount check gives an atomic \"new\". A Like and its un-like read the same generation, because only a new like advances it and neither `remove_like` nor `clear_likes` touches `like_generations`. A dislike that removes a like reads the same generation the profile's own un-like would have read, so it produces the same id. The placeholder order in `fetch_popular_videos` is: the optional error `?` (the `{error_clause}` in the inner subquery at 245), then the cap (247), the inner `LIMIT ?` (252) and the outer `LIMIT ?` (262). That matches `[error_threshold, CAP, limit, limit]` and `[CAP, limit, limit]`. `uuid4` has to stay imported, because `run_id` still uses it. One limit, already in the inventory: the plan does not stop a single profile from repeatedly adding +1 through reset, or \u22121 through import then undo_like. Today's code allows both as well.\n</question>\n<question id=\"2\">\nEvent ids become content-derived, so a repeat from the same actor in the same state collapses at the Engine. Anonymous likes contribute at most +1 per video, and anonymous un-likes at most \u22121. `users.db` gains one `like_generations` row per (profile, video) pair ever liked, and those rows are removed only with the profile. A keyed request that changes nothing now gets 200 and publishes nothing, where on an unpublished Client it used to get a 502. In the popular ordering the signal counts for at most 25. The stored score, the displayed likes and the likes tiebreaker stay uncapped. The inventory already carries all of this.\n</question>\n<question id=\"3\">\nNothing beyond what the inventory already lists:\n- create the table in `ensure_user_schema`;\n- add the `like_generations` delete to `delete_profile`;\n- add a `like_generations` count to `_rows_for`, update the four equality asserts, and change the \"three tables\" comment to \"four\";\n- add `hashlib` and keep `uuid4`;\n- add the reader name to the `users_store` import;\n- test the cap on both parameter branches;\n- in new Client tests, use fresh profiles or a stub Engine, and never assert that the first anonymous event counts.\n</question>\n<question id=\"4\">\n- With a key, these requests no longer publish anything and answer 200: a repeat like, an un-like of a video that isn't liked, a dislike of a video that isn't liked, and every `undo_dislike`.\n- Event ids change from `client-<uuid4>` to `client-<sha256>` over actor, video_uuid, host, event type and generation.\n- Anonymous repeats become duplicates at the Engine.\n- The popular pool stops rewarding any signal above 25.\n- `delete_profile` also removes generations.\n- Unchanged: import, reset, the error paths and the bridge response shape.\n</question>\n</summary>\n\n<new_impacts>\nnone\n</new_impacts>\n\n<unconfirmed>\nnone\n</unconfirmed>\n\n<new_conflicts>\nnone\n</new_conflicts>\n\n<recommendations>\n1. Decide the one item left open: the reset \u2192 re-like loop (+1 per pass) and the import \u2192 undo_like loop (\u22121 per pass). Both are recorded in the inventory as \"operator decision\". (a) Accept them. Add both to \"Tradeoffs the operator accepts\" next to the `max_likes` trim gap, and list them as a follow-up in `docs/project/roadmap.md`. This costs only wording, and the settled plan stays as it is. (b) Close them with an `open` flag on `like_generations`, as the previous Step 4 described. A like publishes only when the flag is 0. An un-like or dislike publishes only when it is 1. Import and reset never change it. This costs about 15 lines in `users_store.py` and three more test cases. It also reopens the settled plan's sections 1-2 and its \"imported likes\" risk, so it goes back to the plan step. I recommend (a). The build's requirements are about replays and repeated POSTs, and they explicitly keep the likes-import path and rate limiting out of scope. Neither loop is a regression.\n2. If (a) is taken, nothing else changes. The remaining work proceeds on the plan and inventory as written, and this step is closed.\n</recommendations>",
    "step_5_draft_implementation": "<draft>\n## Draft implementation: plan 13, derived event ids, publish on change, popular-signal cap\n\n**Operator decision taken at this step.** The inventory left two loops for the operator: reset \u2192 re-like (+1 each pass) and import \u2192 undo_like (\u22121 each pass). The operator chose to close both with a published flag. So this draft departs from the settled plan and inventory in the places listed under \"Deviations from the settled plan and inventory\" at the end. Everything else follows the plan as approved.\n\n### What has to be tested\n\n| # | Behaviour | Where |\n|---|---|---|\n| T1 | Two profile `like` posts publish one `Like`. `likes_count` +1 and `signal_score` +1.0 | new `tests/active/test_event_ids.py` (stub Engine) |\n| T2 | Profile like \u2192 undo_like \u2192 like publishes Like(g1), UndoLike(g1), Like(g2). The two Like ids differ and `signal_score` ends at 1.0 | same |\n| T3 | Re-sending a published payload is `duplicate: true` and changes no counts | same |\n| T4 | Two anonymous likes produce the same id, and the second is a duplicate | same |\n| T5 | undo_like on an unliked video answers 200 and publishes nothing | same |\n| T6 | A dislike that replaces a like publishes one UndoLike with the id the undo_like would have used. A dislike on an unliked video publishes nothing | same |\n| T7 | Reset loop closed: like \u2192 reset \u2192 like publishes one Like. A later undo_like publishes the UndoLike for that same Like, and `signal_score` ends at 0 | same |\n| T8 | Import loop closed: import X \u2192 undo_like X publishes nothing | same |\n| T9 | Popular ordering: signal 1000 with popularity 0 ranks below popularity 30 with no signal, on both parameter branches | `tests/active/test_random_videos.py` |\n| T10 | `delete_profile` removes the profile's `like_generations` rows and keeps another profile's | `tests/active/test_profiles.py` (existing delete test, extended) |\n| T11 | Existing suites stay green | `validate_tests.py` |\n\n### Module map\n\n| File | Change |\n|---|---|\n| `client/backend/lib/users_store.py` | table in `ensure_user_schema`; `record_like` gains `publish=False` and returns `(opened, generation)`; new `like_generation` (reader) and `close_like` (writer) |\n| `client/backend/lib/profiles.py` | `delete_profile` deletes `like_generations` |\n| `client/backend/server.py` | `import hashlib`; `close_like` added to the `users_store` import; `_store_reaction` returns `(publish, generation)`; `_handle_user_action` gates on it and derives the id |\n| `engine/server/data/random_videos.py` | `POPULAR_SIGNAL_CAP`; capped ORDER BY term; params reordered |\n| `tests/active/test_event_ids.py` | new: T1\u2013T8 |\n| `tests/active/test_random_videos.py` | new T9 test |\n| `tests/active/test_profiles.py` | `_seed_like` passes `publish=True`; `_rows_for` counts `like_generations`; the four delete asserts are updated |\n\n### The like-generation state machine\n\nThis is the core invariant. Each `(profile, video)` row in `like_generations` holds `generation` and `published`.\n\n| Event | Precondition | Effect | Publishes |\n|---|---|---|---|\n| keyed like (`record_like(publish=True)`) inserts a new `likes` row | no row | insert `(g=1, published=1)` | `Like` at g=1 |\n| same | `published=0` | `g+=1`, `published=1` | `Like` at the new g |\n| same | `published=1` (after a reset or trim, the Engine still holds this profile's Like) | nothing | nothing |\n| keyed like, `likes` row already exists | any | refresh `video_uuid` / `updated_at` only | nothing |\n| import (`record_like`, default `publish=False`) | any | `likes` row only; `like_generations` untouched | nothing |\n| undo_like, or a dislike (`close_like`) | `published=1` | `published=0`, g unchanged | `UndoLike` at g |\n| same | no row, or `published=0` | nothing | nothing |\n| reset (`clear_likes`) | any | untouched | nothing |\n| `delete_profile` | any | rows deleted | nothing |\n\n**Invariant.** g changes only on the 0\u21921 transition, so while `published=1` it is constant. Every Like(g) is matched by at most one UndoLike(g), and the next Like gets g+1. Per profile and video, the Engine sees each id at most once, so the profile's net contribution is always 0 or +1. Both loops are closed by construction: reset leaves `published=1`, so the re-like publishes nothing, and import never opens a like, so its undo publishes nothing.\n\n**Atomicity.** Opening and closing are single statements whose rowcount decides whether to publish. That is an `UPSERT ... DO UPDATE ... WHERE published = 0` for opening and an `UPDATE ... WHERE published = 1` for closing. Two concurrent requests can never both publish the same transition, and no request relies on a SELECT-then-write.\n\n### `client/backend/lib/users_store.py`\n\n`ensure_user_schema`: the docstring becomes \"Create the users, likes, like generation, profile, block and dislike tables if missing.\" Insert this after `dislike_profiles` and before the `local-user` comment:\n\n```sql\n        CREATE TABLE IF NOT EXISTS like_generations (\n          user_id TEXT NOT NULL,\n          video_id TEXT NOT NULL,\n          instance_domain TEXT NOT NULL,\n          generation INTEGER NOT NULL,\n          published INTEGER NOT NULL DEFAULT 0,\n          PRIMARY KEY (user_id, video_id, instance_domain)\n        );\n```\n\n`record_like`:\n\n```python\ndef record_like(\n    conn: sqlite3.Connection,\n    user_id: str,\n    action: str,\n    video: dict[str, Any],\n    max_likes: int,\n    publish: bool = False,\n) -> tuple[bool, int]:\n    \"\"\"Record a like with recency tracking.\n\n    :param publish: The caller publishes a `Like` when this opens one. The likes import passes nothing, so an imported like never opens one.\n    :returns: Whether this like opened the video's published like, and the video's like generation (0 when none was ever opened).\n    \"\"\"\n    if action != \"like\":\n        raise ValueError(\"Unsupported action\")\n    get_or_create_user(conn, user_id)\n    video_id = str(video.get(\"video_id\") or \"\")\n    instance_domain = str(video.get(\"instance_domain\") or \"\")\n    video_uuid = video.get(\"video_uuid\")\n    now = now_ms()\n    inserted = conn.execute(\n        \"\"\"\n        INSERT INTO likes (user_id, video_id, instance_domain, video_uuid, updated_at)\n        VALUES (?, ?, ?, ?, ?)\n        ON CONFLICT(user_id, video_id, instance_domain) DO NOTHING\n        \"\"\",\n        (user_id, video_id, instance_domain, video_uuid, now),\n    ).rowcount > 0\n    if not inserted:\n        conn.execute(\n            \"UPDATE likes SET video_uuid = ?, updated_at = ? WHERE user_id = ? AND video_id = ? AND instance_domain = ?\",\n            (video_uuid, now, user_id, video_id, instance_domain),\n        )\n    opened = False\n    if inserted and publish:\n        # A like still published (the Engine holds it through a reset or trim) is not opened again.\n        opened = conn.execute(\n            \"\"\"\n            INSERT INTO like_generations (user_id, video_id, instance_domain, generation, published)\n            VALUES (?, ?, ?, 1, 1)\n            ON CONFLICT(user_id, video_id, instance_domain)\n            DO UPDATE SET generation = like_generations.generation + 1, published = 1\n            WHERE like_generations.published = 0\n            \"\"\",\n            (user_id, video_id, instance_domain),\n        ).rowcount > 0\n    generation = like_generation(conn, user_id, video_id, instance_domain)\n    if max_likes > 0:\n        ...  # trim unchanged\n    conn.commit()\n    return opened, generation\n```\n\n- When the DO UPDATE's WHERE is false, SQLite treats the conflict as DO NOTHING, so `changes()` is 0 and `rowcount` is 0.\n- The `inserted` flag is taken from the INSERT's own cursor before any other statement runs.\n\nNew functions, placed after `remove_like`:\n\n```python\ndef like_generation(conn: sqlite3.Connection, user_id: str, video_id: str, instance_domain: str) -> int:\n    \"\"\"Return the profile's like generation for one video.\n\n    :returns: The generation, or 0 when no like of it was ever published.\n    \"\"\"\n    row = conn.execute(\n        \"SELECT generation FROM like_generations WHERE user_id = ? AND video_id = ? AND instance_domain = ?\",\n        (user_id, video_id, instance_domain),\n    ).fetchone()\n    return int(row[0]) if row else 0\n\n\ndef close_like(conn: sqlite3.Connection, user_id: str, video_id: str, instance_domain: str) -> tuple[bool, int]:\n    \"\"\"Close the profile's published like of one video, inside the caller's transaction.\n\n    :returns: Whether a published like was closed, so an `UndoLike` is due, and the generation that like was published under.\n    \"\"\"\n    closed = conn.execute(\n        \"UPDATE like_generations SET published = 0 WHERE user_id = ? AND video_id = ? AND instance_domain = ? AND published = 1\",\n        (user_id, video_id, instance_domain),\n    ).rowcount > 0\n    return closed, like_generation(conn, user_id, video_id, instance_domain)\n```\n\n- `row[0]` works with or without `row_factory`.\n- `remove_like` and `clear_likes` are unchanged.\n\n### `client/backend/lib/profiles.py`\n\nIn `delete_profile`, add `conn.execute(\"DELETE FROM like_generations WHERE user_id = ?\", (profile_id,))` after the `likes` delete, inside the same `with conn:`.\n\n### `client/backend/server.py`\n\nImports:\n- `import hashlib` goes between `argparse` and `ipaddress`.\n- `from uuid import uuid4` stays, because `run_id` still uses it.\n- `users_store` import: `(clear_likes, close_like, ensure_user_schema, fetch_recent_likes, get_or_create_user, load_liked_keys, record_like, remove_like, video_reaction)`. `like_generation` is not imported, since the server does not need it.\n\n`_store_reaction` (annotation `-> tuple[bool, int]`):\n\n```python\n        \"\"\"...\n        :returns: Whether to publish, a `Like` for a like and an `UndoLike` otherwise, and the like generation the event is published under.\n        ...\n        \"\"\"\n        conn = self.server.user_db\n        key = (video[\"video_id\"], video[\"instance_domain\"])\n        if action == \"undo_like\" or (action == \"like\" and not is_disliked(conn, profile_id, *key)):\n            with conn:\n                if action == \"like\":\n                    result = record_like(conn, profile_id, \"like\", video, MAX_LIKES, publish=True)\n                else:\n                    remove_like(conn, profile_id, *key)\n                    result = close_like(conn, profile_id, *key)\n            return result\n        entries = ...  # unchanged\n        if action == \"dislike\":\n            ...  # limit check and centroids unchanged, before any write\n            with conn:\n                remove_like(conn, profile_id, *key)\n                withdrawn = close_like(conn, profile_id, *key)\n                write_dislike(conn, profile_id, video, centroids)\n            return withdrawn\n        # undo_dislike, or a like replacing a dislike.\n        centroids = ...  # unchanged\n        result = (False, 0)\n        with conn:\n            delete_dislike(conn, profile_id, *key, centroids)\n            if action == \"like\":\n                result = record_like(conn, profile_id, \"like\", video, MAX_LIKES, publish=True)\n        return result\n```\n\n- The un-like decision comes from the flag, not from `remove_like`'s result. `remove_like` still removes the row, so reaction state is unchanged.\n- An un-like after a reset therefore still withdraws the Like the Engine holds. An un-like of an imported like, or of one that predates the table, withdraws nothing.\n\n`_handle_user_action` (docstring: \"Apply one like/dislike action and publish the `Like`/`UndoLike` it causes, if any.\"):\n\n```python\n        publish = action in (\"like\", \"undo_like\")\n        generation = 0  # the fixed generation of anonymous likes\n        if profile_id is not None:\n            try:\n                publish, generation = self._store_reaction(profile_id, action, video)\n            except DislikeLimitReached:\n                ...  # unchanged\n            except EngineApiError as exc:\n                ...  # unchanged\n            # A profile publishes only a like it opens or closes. A dislike publishes only to withdraw a like it replaced.\n        if not publish:\n            respond_json(self, 200, {\"ok\": True, \"updatedAt\": now_ms()})\n            return\n\n        event_type = \"Like\" if action == \"like\" else \"UndoLike\"\n        actor = profile_id or \"anonymous\"\n        # The JSON list keeps field boundaries unambiguous. Its encoding is part of every id, so it must never change.\n        identity = json.dumps([actor, canonical_uuid, canonical_host, event_type, generation])\n        event_payload = {\n            \"event_id\": \"client-\" + hashlib.sha256(identity.encode(\"utf-8\")).hexdigest(),\n            \"event_type\": event_type,\n            \"actor_id\": actor,\n            ...  # object, published_at, source_instance, raw_payload unchanged\n        }\n```\n\n`generation` is always an `int`: it comes from `int(row[0])`, the literal `1`, or `0`.\n\n### `engine/server/data/random_videos.py`\n\nAfter the imports:\n\n```python\n# The most of a video's interaction signal the popular ordering adds; the stored signal_score stays raw.\nPOPULAR_SIGNAL_CAP = 25.0\n```\n\nIn `fetch_popular_videos`:\n- docstring: \"Return the most popular videos: popularity plus the capped interaction signal, then likes and views.\"\n- `params: list[Any] = [POPULAR_SIGNAL_CAP, limit, limit]`\n- the threshold branch sets `params = [error_threshold, POPULAR_SIGNAL_CAP, limit, limit]`\n- the first ORDER BY term becomes `(v.popularity + MIN(COALESCE(sig.signal_score, 0), ?)) DESC,`\n\nThe placeholder order is: `{error_clause}` `?`, the cap `?`, the inner `LIMIT ?`, then the outer `LIMIT ?`. The `interaction_signal_score` column and the likes tiebreaker are untouched.\n\n### Tests\n\n**`tests/active/test_event_ids.py`** (new). It needs no live Engine or shared `whitelist.db` and is not rate-limited.\n\nModule docstring: the T1\u2013T8 bullets. Setup:\n- Add `engine/server` and `engine/server/api` to `sys.path`, as `test_random_videos.py` does.\n- Import `ensure_interaction_event_schema` and `ingest_interaction_event`.\n- From conftest, import `RateLimiter`, `client_server` and `ensure_user_schema`.\n\nHarness:\n- `_serving(srv)`: copied from `test_server.py`, about 8 lines.\n- A fixture `rig(tmp_path)` that yields `(client, engine_db, events)`:\n  - `engine_db` is `sqlite3.connect(tmp_path / \"engine.db\", check_same_thread=False)` with `row_factory = sqlite3.Row`, after `ensure_interaction_event_schema`.\n  - `events` is the list of `(payload, result)` pairs.\n  - An `EngineStub(BaseHTTPRequestHandler).do_POST` routes three paths:\n    - `/internal/videos/resolve`: answers `{\"video\": {\"video_id\": \"vid-\" + uuid, \"instance_domain\": host, \"video_uuid\": uuid, \"video_url\": f\"https://{host}/w/{uuid}\"}}`.\n    - `/internal/dislikes/centroids`: answers `{\"space\": \"test\", \"centroids\": []}`, which `compute_dislike_centroids` turns into None.\n    - `/internal/events/ingest`: runs `ingest_interaction_event(engine_db, payload)` under a lock, appends `(payload, result)`, and answers `{\"ok\": True, \"duplicates\": int(result[\"duplicate\"]), \"results\": [result]}`. This is the real ingest, not a mock.\n  - The Client is a `ClientBackendServer` on `tmp_path/\"users.db\"` in `\"bridge\"` mode with `RateLimiter(1000, 60)`, wrapped in conftest's `ClientBackend`.\n- Helpers:\n  - `_video()` returns a fresh `{\"uuid\": uuid4().hex, \"host\": \"ids.example\"}`.\n  - `_act(client, headers, action, video)` posts `/api/user-action` and returns the status.\n  - `_signal(engine_db, video)` returns `(likes_count, signal_score)`, or `(0, 0.0)`.\n  - `_published(events)` returns `[(p[\"event_type\"], p[\"event_id\"]) for p, r in events]`.\n\nCases:\n- **T1.** Mint, then like twice. Both answer 200. One event, a `Like`. `_signal == (1, 1.0)`.\n- **T2.** Like, undo_like, like. The types are `[Like, UndoLike, Like]`. `ids[0] == ids[1]` is false, because the types differ. `ids[0] != ids[2]`. `ids[0]` equals the expected sha256 of `[profile_id, uuid, host, \"Like\", 1]`, which pins the encoding, and `ids[2]` uses generation 2. The final signal score is 1.0.\n- **T3.** Take the first T1 payload and call `ingest_interaction_event(engine_db, payload)` again. `duplicate is True` and `_signal` is unchanged.\n- **T4.** Anonymous like twice. Both ids are equal, the second result has `duplicate is True`, and `_signal == (1, 1.0)`.\n- **T5.** Mint, then undo_like on a fresh video. Status 200 and no events.\n- **T6.** Mint, like, dislike. There are exactly two events, and the second is an `UndoLike` whose id equals sha256 of `[pid, uuid, host, \"UndoLike\", 1]`, the id an undo_like at g1 would have used. Then, on a second fresh video, a dislike answers 200 and adds no event.\n- **T7.** Mint, like, `POST /api/user-profile/reset` with the key, like again. Only one `Like` has been published. Then undo_like gives exactly one `UndoLike` at g1, and `_signal == (0, 0.0)`.\n- **T8.** Mint, `POST /api/profile/likes/import` with the key and `{\"likes\": [{\"video_uuid\": uuid, \"instance_domain\": host}]}`, then undo_like. There are no events.\n  - This depends on the stub's `resolve_videos_by_uuid_host` path. I have not read its endpoint yet (`engine_api_client.py:136-166`); the builder reads it and adds the matching stub route.\n  - If that route turns out to cost more than about 15 lines, fall back to seeding with `record_like(conn, pid, \"like\", video, 100)` without `publish` on the users.db. That is exactly the call the import makes.\n\n**`tests/active/test_random_videos.py`** gets `test_the_popular_order_caps_the_interaction_signal(tmp_path)`:\n- `_two_video_db`, then `UPDATE videos SET popularity = 0` on `first` and `30` on `second`.\n- `INSERT INTO interaction_signals (video_uuid, instance_domain, likes_count, signal_score, updated_at) VALUES (?, ?, 0, 1000.0, 0)` for `first`, then commit.\n- For `threshold in (None, 1)`, `fetch_popular_videos(conn, 10, error_threshold=threshold)` returns `[second, first]` by `video_id`, and `first`'s `interaction_signal_score == 1000.0`, which shows the stored value is still raw.\n- `_set_views` sets `error_count = 0`, so threshold 1 keeps both rows.\n- Add a docstring bullet.\n- A wrong params order either makes the cap act as the error threshold, which drops rows, or turns the limits into the cap. Both break one of the two branches.\n\n**`tests/active/test_profiles.py`**:\n- `_seed_like` passes `publish=True` to `record_like`.\n- `_rows_for` adds `\"like_generations\": conn.execute(\"SELECT COUNT(*) FROM like_generations WHERE user_id = ?\", (profile_id,)).fetchone()[0]`.\n- The asserts at 205, 209 and 216 gain `\"like_generations\": 1`, and the one at 215 gains `\"like_generations\": 0`.\n- The comment at 201 becomes \"record_like also creates the `users` row and opens a like generation, so all four tables hold rows for both.\"\n- `test_frontend_profile.py`'s `_seed_like` stays as it is (`publish` defaults to False).\n\n### Existing tests, walked through with the flag\n\n- `test_frontend_reactions` keyed sequence:\n  - like: opens g1 and publishes.\n  - dislike: closes g1, publishes UndoLike(g1).\n  - undo_dislike: publishes nothing.\n  - out-of-band dislike: nothing to close, 200.\n  - like replacing the dislike: opens g2 and publishes.\n  - undo_like: UndoLike(g2).\n  - The same shape as the settled walk-through, so `all(\"ok\" in a)` holds.\n- The card test and `test_profiles.py:300`: a fresh profile's first like opens and publishes, so still 502 on `unpublished_client`.\n- `test_dislikes` 74-87:\n  - line 77 closes the like opened at line 74, which publishes, so 200 or 502;\n  - line 82: 200;\n  - line 84: nothing to close, 200.\n- Keyless tests: unchanged from the inventory's account.\n- Smokes: a fresh profile's first like opens and publishes, and the raw row is keyed by the profile.\n\n### Acceptance criteria \u2192 evidence\n\n| Criterion | Holds because | Test |\n|---|---|---|\n| Double like, one Like, +1 / +1.0 | second INSERT rowcount 0, nothing is opened | T1 |\n| like\u2192undo\u2192like, distinct Like ids, 1.0 | g1 opened, closed, then g2 opened | T2 |\n| Bridge retry is a duplicate | same id, `ON CONFLICT(event_id) DO NOTHING` | T3 |\n| Anonymous duplicate | generation 0 and actor `anonymous` give a fixed id | T4 |\n| undo_like of an unliked video: 200, nothing | nothing to close | T5 |\n| Dislike UndoLike id = the undo_like id; unliked dislike publishes nothing | both go through `close_like` | T6 |\n| Signal 1000 / pop 0 below pop 30 | `MIN(1000, 25) = 25 < 30` | T9 |\n| `delete_profile` removes generations | new DELETE | T10 |\n| Existing suites | walk-through above | T11 |\n\n### Deviations from the settled plan and inventory\n\nAll of these follow from the operator's \"close both with a published flag\". None is silent.\n\n1. **Schema.** `like_generations` gains `published INTEGER NOT NULL DEFAULT 0`. The inventory's DDL lists only four columns.\n2. **When generation increments.** Only when a like is opened, that is, a new `likes` row from a publishing caller while `published=0`. The requirement says \"on every new likes row\". A re-like after a reset or trim, and every imported like, now leaves it unchanged. The contract still holds: a Like and its un-like share a generation, and the next Like differs.\n3. **Un-like gating.** Publishing depends on `close_like`, not on `remove_like`'s result. `remove_like` is still called and still removes the row.\n4. **`record_like` signature.** It gains the keyword `publish: bool = False`. `_handle_likes_import` (plan 14's handler) and the tests' `_seed_like` helpers keep working unedited. `record_like` returns `(opened, generation)` rather than `(new, generation)`.\n5. **Reader.** The inventory's reader exists as `like_generation(conn, user_id, video_id, instance_domain) -> int`, with the positional shape and `:returns:`. The server imports the new writer `close_like` instead of the reader, so the users_store import line gains `close_like`.\n6. **`test_profiles._seed_like`** passes `publish=True`. The inventory assumed `record_like` would always write a generation row.\n7. **Plan Risks, \"imported likes advance the generation, a later un-like publishes UndoLike (\u22121)\".** This no longer happens: an imported like never publishes either event.\n\n### Risks\n\n- **Likes that predate `like_generations`.** They have no row, so their un-like publishes nothing. The Engine keeps the +1 from the old random-id Like. The un-like side is bounded at 0, where the settled plan would have published a gen-0 UndoLike.\n- **Publish failure after the flag opens or closes** (bridge down, or `unpublished_client`). The Client's state moves while the Engine misses the event, and nothing retries it. Worst case, a later close publishes an UndoLike the Engine never saw a Like for. That is \u22121 once per generation, floored at 0. The settled plan had the same gap.\n- **Trim gap.** It is narrower as a side effect: a re-like after a trim publishes nothing and a later un-like withdraws. It stays open when the profile never re-likes.\n- **Anonymous import.** A like the browser published anonymously and then imported is never withdrawn by the profile. This falls under ADR-0001 \u00a73's anonymous +1.\n- **Concurrency.** Opening and closing are single conditional statements, so two concurrent requests cannot publish one transition twice. The existing dislike rat-tail is unchanged.\n- **Merge with plan 14.** The import-line edits (`hashlib`, `close_like`) resolve by union. Its import caller is untouched.\n\n### Documentation changes from the settled checklist\n\n- `client/README.md` line 19: \"an un-like publishes only when it withdraws a like the profile published, and a reset or import publishes nothing and never re-publishes\".\n- `CONTEXT.md` **Like generation**: add \"and whether its like is published\".\n- ADR-0001 Consequences: add the published flag, the closed loops, the legacy-like note and the import note.\n- `docs/project/roadmap.md`: drop the \"close the reset/import loops\" follow-up. Keep the import-publishing item, the likes-tiebreaker item, and a narrowed trim-gap item.\n\n### Convergence\n\nPass 1 checked the draft against the plan and requirements, with the operator decision applied. Every requirement is met or listed above as an approved deviation. Pass 2 found `_seed_like` needing `publish=True` and the dislike branch's `close_like` placement, and added both. No further change was needed.\n</draft>",
    "step_6_develop_phase_breakdown": "<phases>\n<phase n=\"1\" kind=\"code\">\n<checkpoint>T9, `test_the_popular_order_caps_the_interaction_signal(tmp_path)` in tests/active/test_random_videos.py. The seam is a direct call to `fetch_popular_videos(conn, 10, error_threshold=threshold)` on the isolated tmp engine.db built by the existing `_two_video_db` harness, so the file's own tests are the precedent. Setup: `first` gets popularity 0, `second` gets popularity 30, and an `interaction_signals` row gives `first` a signal_score of 1000.0 with likes_count 0. The test runs for threshold in (None, 1), an explicit set covering both params branches. It asserts that the result order by `video_id` is [second, first]. As a control it asserts that `first`'s `interaction_signal_score == 1000.0`, so the stored score is shown to be raw. `_set_views` sets error_count = 0, so threshold 1 keeps both rows. A wrong params order therefore breaks at least one branch.</checkpoint>\n<name>Popular signal cap</name>\n<intent>`fetch_popular_videos` in engine/server/data/random_videos.py orders videos by popularity plus the interaction signal capped at the module constant `POPULAR_SIGNAL_CAP`.</intent>\n<clause_1>A video with signal 1000 and popularity 0 ranks below a video with popularity 30 and no signal, with and without an error threshold.</clause_1>\n<files>engine/server/data/random_videos.py (EDITED), tests/active/test_random_videos.py (EDITED)</files>\n</phase>\n<phase n=\"2\" kind=\"code\">\n<checkpoint>T1\u2013T8 in tests/active/test_event_ids.py (NEW). The seam is HTTP POST to /api/user-action, /api/user-profile/reset and /api/profile/likes/import on a real `ClientBackendServer` in \"bridge\" mode over a tmp users.db, with `RateLimiter(1000, 60)`. It follows the `_serving` / `_client_backend` harness in test_server.py and is wrapped in conftest's `ClientBackend`. The Engine is a `BaseHTTPRequestHandler` stub with three routes. `/internal/videos/resolve` echoes a video. `/internal/dislikes/centroids` answers with empty centroids. `/internal/events/ingest` runs the real `ingest_interaction_event` on a tmp engine.db under a lock and records (payload, result). Assertions are made at the Engine boundary: the published (event_type, event_id) list and `interaction_signals` (likes_count, signal_score).\nClause 1: T1 (double like gives one Like, (1, 1.0)). T5 (undo_like of an unliked video answers 200 with no event). T6b (dislike of an unliked video adds no event). T7 (like, reset, like publishes one Like, and the later undo_like gives one UndoLike, ending at (0, 0.0)). T8 (import then undo_like gives no events). For T8, the builder reads engine_api_client.py:136-166 and adds the resolve-by-uuid stub route. If that route costs more than about 15 lines, the test seeds with `record_like` without `publish`.\nClause 2: T2 (like \u2192 undo_like \u2192 like gives [Like, UndoLike, Like]; ids[0] equals sha256 of json.dumps([pid, uuid, host, \"Like\", 1]); ids[2] uses generation 2 and differs from ids[0]; the signal ends at 1.0). T3 (re-ingesting T1's payload returns duplicate True and leaves the counts unchanged). T4 (two anonymous likes carry equal ids, the second is a duplicate, and the signal is (1, 1.0)). T6a (a dislike replacing a like publishes an UndoLike whose id is sha256 of [pid, uuid, host, \"UndoLike\", 1]).</checkpoint>\n<name>Publish on change, derived ids</name>\n<intent>A profile's POST /api/user-action publishes a Like or UndoLike only when it opens or closes that profile's published like of the video, tracked in the new `like_generations` table by `record_like(publish=True)` and `close_like` in users_store.py, and every event `_handle_user_action` publishes carries an id derived from actor, video, event type and like generation.</intent>\n<clause_1>An action that neither opens nor closes the profile's published like of the video publishes no event.</clause_1>\n<clause_2>A published event's id is `client-` plus the SHA-256 of the JSON list of actor, canonical uuid, canonical host, event type and like generation.</clause_2>\n<files>client/backend/lib/users_store.py (EDITED), client/backend/server.py (EDITED), tests/active/test_event_ids.py (NEW)</files>\n</phase>\n<phase n=\"3\" kind=\"code\">\n<checkpoint>T10: extend the existing `test_deleting_a_profile_removes_its_rows_and_keeps_anothers` in tests/active/test_profiles.py. The seam is HTTP POST /api/profile/delete on conftest's `client_backend`, with row counts read straight from users.db through `_rows_for`, following the precedent in this test. `_seed_like` passes `publish=True`. `_rows_for` adds a `like_generations` count. The asserts at 205, 209 and 216 expect `\"like_generations\": 1`, and the one at 215 expects `\"like_generations\": 0`. The comment at 201 is updated to say all four tables hold rows.</checkpoint>\n<name>Delete removes generations</name>\n<intent>`delete_profile` in client/backend/lib/profiles.py removes the deleted profile's `like_generations` rows inside its existing transaction.</intent>\n<clause_1>After one profile is deleted, it has no `like_generations` rows and another profile keeps its rows.</clause_1>\n<files>client/backend/lib/profiles.py (EDITED), tests/active/test_profiles.py (EDITED)</files>\n</phase>\n</phases>\n\n<needs_coordination>\nnone\n</needs_coordination>\n\n<rationale>\nThe Engine cap shares nothing with the Client work, so it is its own slice, checked at the harness test_random_videos.py already has. The users_store state machine (the table, `record_like(publish=True)` and `close_like`) and the server's gating and id derivation land together. The store only matters through what `_handle_user_action` publishes, so the one honest seam is HTTP in, Engine ingest out. A store-level suite would duplicate T1\u2013T8 and pin internals. That Intent reduces to exactly two observable facts, publish gating and id derivation. `delete_profile` is a separate phase for two reasons: adding it to phase 2 would make three clauses, and it depends on the table phase 2 creates. test_profiles.py's `_seed_like` changes with it, not earlier. Phase 2's own `_seed_like` callers keep working because `publish` defaults to False. No prose phase: the README, CONTEXT.md, ADR-0001 and roadmap edits are documentation for Step 9. No coordination is needed: every checkpoint runs on tmp databases and a stub Engine whose ingest route is real, and whitelist.db is only read. The operator approved this breakdown as presented.\n</rationale>",
    "author:tests/tmp/test_13_deterministic_event_ids_phase1.py": "<exemptions>\n<exemption clause=\"N2\">\n<answer>exempt (the operator picked \"Exempt N2\": \"Keep the workflow's path. The module name belongs to the build (plan 13), and the docstring already says nothing here tests event ids.\")</answer>\n<why>What is conceded: no assertion carries the \"deterministic event ids\" claim in the module name `test_13_deterministic_event_ids_phase1`. The name comes from the workflow's path scheme (plan 13, the build slug, phase 1) and is not a claim about behaviour. Docstring :7 already says nothing here asserts anything about event ids. Renaming the file would create a gating path this step does not name. No other test in this phase covers event-id behaviour, because this phase delivers the popular-order cap.</why>\n</exemption>\n</exemptions>\n\n<items>\n<item id=\"D1a\">\n<disposition>fixed</disposition>\n<what>The previous round added the (SIGNAL, CAP - 0.5) and (SIGNAL, CAP + 0.5) cases to the :86 loop, and :90 asserts them under both thresholds. With signal 1000, the first video must rank above popularity 24.5 and below popularity 25.5. That excludes any cap of 24.5 or less, which includes a dropped signal and the threshold 1 or limit 10 bound into the cap's slot. It also excludes any cap of 25.5 or more, which includes uncapped addition. The cap is now pinned to 25 \u00b1 0.5, and docstring :4 was narrowed to say exactly that. The current claim audit marks D1a CARRIED at :90.</what>\n</item>\n<item id=\"D1b\">\n<disposition>fixed</disposition>\n<what>The previous round added the (SUB_CAP_SIGNAL=10, 5.0) and (SUB_CAP_SIGNAL=10, 15.0) cases to the :86 loop, and :90 asserts them under both thresholds. A signal of 10 must rank above popularity 5 and below popularity 15. That excludes a flat bonus of the cap for any positive signal (25 > 15 would put the first video first) and a dropped signal (0 < 5). Docstring :5 states the claim at the precision the test asserts. The current claim audit marks D1b CARRIED at :90.</what>\n</item>\n</items>\n\n<findings_addressed>\nClaim audit CRITICAL 1 (N2: the module name claims \"deterministic event ids\"): the operator chose \"Exempt N2\" through AskUser, so N2 is declared in <exemptions> and needs no item. The test file is unchanged this round. This resubmission only adds the ledger items for D1a and D1b, which the previous round fixed at :86/:90. Leftover to report: tests/tmp/probe_cap.py is still on disk. It is emptied and does nothing, but it needs deleting, and I have no delete tool.\n</findings_addressed>\n\n<rows>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_13_deterministic_event_ids_phase1.py:80: for threshold in (None, 1), with the first video at popularity 0 and signal_score 1000.0 and the second at popularity 30 with no signal, `fetch_popular_videos(conn, 10, error_threshold=threshold)` returns video_ids in the order [second, first]. Its control is :82, which checks that `interaction_signal_score` stays raw: {first: 1000.0, second: 0}. The popularity-24.5 case at :90 is the below-cap control the operator approved earlier, moved from 20 to 24.5.</assertion>\n<expected>[second, first] under both thresholds, since 0 + min(1000, 25) = 25 < 30.</expected>\n<wrong_implementation>Today's uncapped `popularity + COALESCE(signal_score, 0)` returns [first, second], because 1000 > 30. The last red run failed at :80 with threshold None: ['fd640a96\u2026'] == ['d6abc74c\u2026']. A cap applied only in the no-threshold branch fails the threshold=1 pass. A params order that puts the threshold (1) or the limit (10) in the cap's slot still passes :80, but fails the 24.5 case at :90, because 1 and 10 are both below 24.5.</wrong_implementation>\n</row>\n</rows>\n\n<answers>\n1. No. There is no absence-only assertion. Every assertion is a positive check of order or score on rows that must be returned, so deleting the code under test fails all of them.\n2. No. The test never computes the capped sum itself. It asserts only which video leads, at popularities chosen to straddle 25, and that the raw score comes back unchanged. Removing the cap from the ORDER BY (random_videos.py:247) turns :80 and the 25.5 case at :90 red. Removing the signal term turns the 24.5 and popularity-5 cases red. Capping the output column turns :82 red.\n3. No. The order is read at popularities 30, 24.5 and 25.5 with signal 1000, and at 5 and 15 with signal 10, each under both thresholds.\n4. No. There are no doubles. The test uses the real `fetch_popular_videos` and `ensure_interaction_event_schema` on a temporary copy of real whitelist.db rows.\n5. Yes, it collects. The file is unchanged since the last run, which collected 1 test.\n6. Yes, the expected values were observed, in the earlier probe runs of today's `fetch_popular_videos` and of raw-SQL cap variants. Nothing changed this round.\n7. Yes. The file is unchanged, so it still fails at :80 (C1, threshold None) on the uncapped order, not on setup, collection or an import.\n</answers>",
    "self_check:tests/tmp/test_13_deterministic_event_ids_phase1.py": "<rows>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_13_deterministic_event_ids_phase1.py:69 \u2014 with `first` at popularity 0 plus signal 1000 and `second` at popularity 30 with no signal, `fetch_popular_videos(conn, 10, error_threshold=threshold)` returns the video ids in the order [second, first]. The loop runs this for threshold None and for threshold 1. Line 76 is a guard alongside it: with `second` at popularity 20, the order must be [first, second] at both thresholds.</assertion>\n<expected>[second[\"video_id\"], first[\"video_id\"]] at both thresholds, because first's score of 0 + min(1000, 25) = 25 is lower than 30. At line 76 it is [first, second], because 25 is higher than 20. Under the current code the probe run showed [('first', 0.0, 1000.0), ('second', 30.0, 0)] at threshold None and at threshold 1, so line 69 is red now. At popularity 20 the probe showed first above second at both thresholds, so line 76 already holds and only stops the fix from dropping the signal.</expected>\n<wrong_implementation>The code as it stands orders by `v.popularity + COALESCE(sig.signal_score, 0)` with no cap, and the run showed line 69 reading [first, second] ('fd640a96\u2026' ahead of 'd6abc74c\u2026'). A cap added to only one of the two error-threshold query shapes leaves the other iteration reading [first, second] at line 69. Dropping the signal from the order, or capping it at the wrong value (0, or anything up to 20), makes line 76 read [second, first]. A cap of 30 or more leaves line 69 reading [first, second].</wrong_implementation>\n</row>\n</rows>\n\n<answers>\n1. Whole claim: yes, it tests what the docstring bullet says. Line 69 checks the ranking below popularity 30, at threshold None and at threshold 1 (the loop at line 66). Line 76 checks the ranking above popularity 20 at both thresholds. Line 71 checks that the row still reports the raw signal of 1000. The header's \"cap of 25\" is only pinned between 20 and 30, which is exactly the range the docstring bullet and C1 name. No rewrite.\n2. Absence only: no. Every assertion is a positive ordering or a positive equality. Line 76 is the positive control for line 69: it proves the signal still reaches the order, so line 69 cannot be passed by throwing the signal away.\n3. Echoed literal: no. The test never computes a capped score itself; it only compares orderings the production query produces. The line 71 control compares against the SIGNAL the test inserted, but the value it reads comes from production's `COALESCE(sig.signal_score, 0) AS interaction_signal_score` (random_videos.py:234). Swapping that line for a capped value turns the control red. The C1 assertion turns green only when the ORDER BY at random_videos.py:247 changes; the uncapped `COALESCE(sig.signal_score, 0)` term there is what keeps it red.\n4. One value: no. The order is read at two thresholds and at two popularities (30 and 20), one on each side of the cap.\n5. The double: no. There are no doubles at all. It uses a real SQLite file built from real rows of `whitelist.db`, the real `ensure_interaction_event_schema`, and the real `fetch_popular_videos`.\n6. It collects: yes. The run printed \"collected 1 item\" and reached line 69, so both imports resolve, the `sys.path` setup works, and `_two_video_db`'s `assert len(picks) == 2` and the `error_count` UPDATE both ran. The \"no tests\" in the collect-only output is just how the harness summarises a run where nothing executed. The real run collected 1 test, matching the one I wrote.\n7. Observed, not predicted: every expected value is backed by a run. I wrote a probe in tests/tmp/probe_cap.py that ran the test's own fixture through `fetch_popular_videos` at threshold None and 1 and at popularity 30 and 20. It printed `[(None, 30.0, [('first', 0.0, 1000.0), ('second', 30.0, 0)]), (None, 20.0, [('first', 0.0, 1000.0), ('second', 20.0, 0)]), (1, 30.0, [('first', 0.0, 1000.0), ('second', 30.0, 0)]), (1, 20.0, [('first', 0.0, 1000.0), ('second', 20.0, 0)])]`. That confirms three things: the threshold-1 path reaches the query and returns both rows; the raw scores are 1000.0 and 0, as line 71 expects; and the popularity-20 order (line 76) already holds. The only expectation it cannot show is the capped order at 30, which is the phase's own claim. I emptied the probe again afterwards, back to the empty state I found it in.\n8. Red, not green: yes, it is red. `ValidateTests tests/tmp/test_13_deterministic_event_ids_phase1.py` printed \"1 failed\" and \"[exit status 1]\".\n9. Red for the right reason: yes. The failing assertion is line 69, `assert [row[\"video_id\"] for row in rows] == [second[\"video_id\"], first[\"video_id\"]], threshold  # C1`, which is the C1 assertion, not a control. It failed with \"AssertionError: None / At index 0 diff: 'fd640a96-d208-454d-9892-2872cb33a6bb' != 'd6abc74c-903a-43f6-9bff-ff5865970ed7'\" at \"tests/tmp/test_13_deterministic_event_ids_phase1.py:69: AssertionError\". The uncapped signal of 1000 lifts `first` above `second`'s 30. Setup got past `assert len(picks) == 2`, the schema creation, the signal insert and the popularity UPDATE before it failed. The probe shows the same order at threshold 1, so the threshold-1 run would fail at line 69 for the same reason.\n10. Observed expected output: yes. The C1 row's wrong-implementation reading, [first, second] under the current uncapped code, is what the run showed at line 69 and what the probe showed at both thresholds. The popularity-20 order and the raw scores match the probe output quoted in answer 7. Nothing contradicted the rows, so there was no rewrite. The test file is unchanged.\n</answers>\n\n<exemptions>\nnone\n</exemptions>",
    "step_7_implement:1": "<changes>\n### `engine/server/data/random_videos.py`\n- Added the module constant `POPULAR_SIGNAL_CAP = 25.0`. It has a one-line comment saying why it exists: a burst of interaction events should not be able to outrank crawled popularity.\n- `fetch_popular_videos` now ranks by `v.popularity + MIN(COALESCE(sig.signal_score, 0), ?)` instead of `v.popularity + COALESCE(sig.signal_score, 0)`. The cap is a bound parameter. It sits in `params` after the optional error threshold and before the two `limit`s, which matches where each `?` appears in the SQL. This is true with and without an error threshold.\n- The tie-breakers after the popularity term are unchanged (likes plus signal likes, views, published_at, video_id).\n- The returned `interaction_signal_score` column is unchanged and still reports the raw, uncapped signal.\n\n### `tests/active/test_random_videos.py`\nNot changed. It only uses a signal of 1.0, well under the cap, so the cap doesn't affect it. It has no expectation that conflicts with this change, so this phase had no reason to edit it.\n</changes>\n\n<inner_tests>\nnone\n</inner_tests>\n\n<unanticipated>\nnone\n</unanticipated>\n\n<awaiting_operator>\nnone\n</awaiting_operator>",
    "author:tests/tmp/test_13_deterministic_event_ids_phase2.py": "<exemptions>\nnone\n</exemptions>\n\n<items>\n<item id=\"D6\">\n<disposition>justified</disposition>\n<what>I narrowed the prose to match what the test asserts. The first docstring bullet now ends \"...publish one Like, at generation 1, and the video's signal is (1, 1.0).\" The clause \"re-ingesting that Like's payload unchanged, as a bridge retry does, is a duplicate\" is gone. I also deleted the old lines :143\u2013144 (the `ingest_interaction_event` re-send of `rig.events[0][0]` and its `duplicate is True` assertion). Re-sending the recorded dict collides with itself under any id scheme, `client-{uuid4}` included, so those lines excluded nothing. What they claimed to guard is really carried at :142, which pins the published id to the derived `client-` + SHA-256 value; any re-derivation of the same like gets that same id.</what>\n</item>\n<item id=\"D7\">\n<disposition>justified</disposition>\n<what>I removed \"and leaves (1, 1.0)\" from the docstring together with D6, and deleted the old :145 signal re-check that followed the self-colliding re-ingest. The (1, 1.0) the test actually proves is still asserted at :141, straight after the two likes, and the docstring still says so (\"the video's signal is (1, 1.0)\").</what>\n</item>\n<item id=\"N1b\">\n<disposition>justified</disposition>\n<what>I renamed the test from `test_a_repeated_like_publishes_one_like_and_a_bridge_retry_of_it_is_a_duplicate` to `test_a_repeated_like_publishes_one_like_at_generation_1`. The name no longer claims a bridge-retry duplicate, which nothing in the test could tell apart from a random id. It now names what :140 (one Like) and :142 (its id at generation 1) assert.</what>\n</item>\n</items>\n\n<findings_addressed>\nNeither auditor raised a CRITICAL. I took claim-audit recommendation 1 (the :143\u2013145 re-send excludes nothing) in its narrowing form: I deleted the three lines and narrowed the docstring and the test name to what :142 proves. The other form, driving a real Client re-publish, would have to assert retry behaviour that neither C1 nor C2 specifies. I left claim-audit recommendation 2 (the bridge-rejected publish path) alone. What the action answers, and which id and generation a retry uses after the bridge rejects a publish, are not in C1 or C2 or in this phase's Intent, so any expectation for them would be invented. It needs a requirement of its own first. The shape audit made no findings. After the edit I ran the file: all 8 tests still fail on their intended assertions and nowhere else (:140, :152, :159, :171, :178, :189, :205, :219).\n</findings_addressed>\n\n<rows>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_13_deterministic_event_ids_phase2.py:140 \u2014 after two keyed likes of one video the published types are exactly [\"Like\"]; :178 \u2014 undo_like of a never-liked video publishes nothing (armed by the :181 control, a like that does publish); :194 \u2014 after a dislike of an unliked video (stored, control :192) and an undo_dislike, still exactly 2 events have been published; :205 \u2014 like, reset, re-like (stored, control :204) has published exactly [\"Like\"]; :219 \u2014 undo_like of an imported like (stored :216, removed :218) publishes nothing, armed by the :222 control</assertion>\n<expected>:140 [\"Like\"]; :178 []; :194 2; :205 [\"Like\"]; :219 []</expected>\n<wrong_implementation>Today's `publish = action in (\"like\", \"undo_like\")` publishes on every like and every undo_like. Under it :140 and :205 read [\"Like\", \"Like\"], and :178 and :219 read one UndoLike (observed in this run). An implementation that decides whether to publish from the stored like rather than the published one passes :140 but still gives [\"Like\", \"Like\"] at :205. One that publishes on dislike or undo_dislike with no like to remove reads more than 2 at :194.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_13_deterministic_event_ids_phase2.py:142 \u2014 the one Like's id is \"client-\" + sha256(json.dumps([profile_id, uuid, host, \"Like\", 1])); :152 \u2014 like, undo_like, like publish the derived ids at (Like,1), (UndoLike,1), (Like,2); :159 \u2014 two anonymous likes both carry the derived id for [\"anonymous\", uuid, host, \"Like\", 0]; :171 \u2014 a like spelled with an upper-case uuid and host \"IDS.Example\" carries the id over the resolved lower-case uuid and host (controls :169\u2013170 confirm the resolved identity reached the payload)</assertion>\n<expected>Each id equals `_event_id(actor, canonical video, event_type, generation)` with the actor, type and generation named above. For :159 that is two identical ids, which the Engine flags [False, True] at :160.</expected>\n<wrong_implementation>Today's `f\"client-{uuid4()}\"` fails :142, :152, :159 and :171, since each reads a random `client-` uuid (observed). An id that leaves out the event type makes Like and UndoLike at generation 1 collide at :152. One that leaves out the generation, or reuses generation 1 on a re-like, fails :152 (and :151). One that uses a per-request actor or a generation other than 0 for anonymous fails :159. Hashing the uuid and host as sent fails :171.</wrong_implementation>\n</row>\n</rows>\n\n<answers>\n1. No. Every negative assertion has a positive control showing the path ran. :178 has the :181 like that does publish. :194 follows the stored dislike at :192 and the two events published at :188. :205 has the re-like stored at :204. :219 has the import stored at :216, the undo applied at :218, and the like at :222. If the handler were deleted, the controls and the positive id assertions would go red.\n2. No. `_event_id` implements the requirement's formula independently. Production does not compute it yet, and deleting server.py:802's id line, or changing its form, is what turns :142, :152, :159 and :171 red. I removed the only echo there was: re-sending the recorded payload at the old :143\u2013145, which compared an event_id to itself.\n3. No. The id is read across actor (a profile id or anonymous), type (Like or UndoLike), generation (0, 1 or 2) and spelling (canonical or non-canonical), each against the independently derived value.\n4. No. The only double is the Engine's HTTP surface across the bridge, a severed process boundary. Its ingest runs the real `ingest_interaction_event` on a real engine.db, and the Client backend is the real server.\n5. Yes, it collects. `ingest_interaction_event` is still imported and used by the stub. The run collected 8 tests, which matches the 8 test functions in the file.\n6. Yes. The rig's behaviour (statuses, event shapes, duplicate flags, signal rows, the import going through resolve) came from the earlier probe run. The derived ids are a prediction from the requirement's formula and cannot be observed until the phase is built. I said so in the previous round, and nothing I added this round rests on a new unobserved shape.\n7. Yes. I ran the file after the edit: 8 failed, each on its intended assertion after its controls passed. :140 read ['Like','Like']. :152, :159, :171 and :189 read client-<uuid4> ids instead of the derived ones. :178 and :219 read one UndoLike instead of []. :205 read ['Like','Like'].\nHousekeeping: the empty tests/tmp/probe_13_phase2.py from the previous round is still there, because I have no delete tool, and it needs removing.\n</answers>",
    "self_check:tests/tmp/test_13_deterministic_event_ids_phase2.py": "<rows>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_13_deterministic_event_ids_phase2.py:140 \u2014 after two keyed likes of one video (both 200), the published event types are exactly [\"Like\"]</assertion>\n<expected>[\"Like\"]. The second like opens nothing, so nothing is published for it.</expected>\n<wrong_implementation>Publishing every keyed like, as today's `publish = action in (\"like\", \"undo_like\")` does. The run read ['Like', 'Like'] at :140.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_13_deterministic_event_ids_phase2.py:181 \u2014 a keyed undo_like of a video the profile never liked (200 at :180) publishes nothing: rig.events == []</assertion>\n<expected>[]. The positive control at :184 then shows the same rig does publish a later like, at generation 1.</expected>\n<wrong_implementation>Publishing every undo_like whether or not a like was closed. The run read one ('UndoLike', client-<uuid4>) event at :181.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_13_deterministic_event_ids_phase2.py:197 \u2014 after a dislike and then an undo_dislike of a second, unliked video, the total published count is still 2 (the Like and UndoLike of the first video)</assertion>\n<expected>2. The control at :195 shows the dislike was stored ({\"liked\": False, \"disliked\": True}).</expected>\n<wrong_implementation>A gate that publishes an UndoLike on every dislike or undo_dislike, e.g. treating any dislike-branch write as a change. That reads 3 or 4. Today's code already passes this, so it is a regression guard and not a red gate: the earlier probe saw 0 events for both actions. This run stopped at :192 before reaching :197.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_13_deterministic_event_ids_phase2.py:208 \u2014 like, reset, like publishes exactly [\"Like\"], though the controls at :205 and :207 show the reset removed the like and the re-like was stored</assertion>\n<expected>[\"Like\"]. The profile's first Like is still published at the Engine, so the re-like opens nothing.</expected>\n<wrong_implementation>Opening a new generation on every new `likes` row, which was the pre-flag plan, or today's unconditional publish. Either publishes a second Like. The run read ['Like', 'Like'] at :208.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_13_deterministic_event_ids_phase2.py:222 \u2014 an undo_like of an imported like publishes nothing, though the controls at :218, :219 and :221 show the import stored the like and the undo removed it</assertion>\n<expected>[]. The positive control at :225 shows a later like publishes at generation 1.</expected>\n<wrong_implementation>Gating the UndoLike on `remove_like`'s result instead of on a published like being closed. The imported row is removed, so an UndoLike goes out. The run read one ('UndoLike', client-<uuid4>) event at :222.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_13_deterministic_event_ids_phase2.py:153 \u2014 like, undo_like, like publishes exactly [\"Like\", \"UndoLike\", \"Like\"]</assertion>\n<expected>[\"Like\", \"UndoLike\", \"Like\"]. Each action opens or closes the like, so each one publishes.</expected>\n<wrong_implementation>An over-eager gate whose published flag never reopens after a close. It suppresses the re-like and reads [\"Like\", \"UndoLike\"]. Today's code passes this line (the run got past :153 to :155), so it guards against over-suppression rather than gating red.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_13_deterministic_event_ids_phase2.py:142 \u2014 the one Like of a repeated like is (\"Like\", \"client-\" + sha256(json.dumps([pid, uuid, host, \"Like\", 1])))</assertion>\n<expected>[(\"Like\", _event_id(pid, video, \"Like\", 1))]</expected>\n<wrong_implementation>A random `client-<uuid4>` id (today), or a profile Like hashed at generation 0. Either gives a different id. This run stopped at :140 before reaching :142. The same shape of comparison failed at :155 with 'client-4a39328d-\u2026' != 'client-ebc4288c\u2026'.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_13_deterministic_event_ids_phase2.py:154 \u2014 in like, undo_like, like, the first and third event ids differ</assertion>\n<expected>published[0][1] != published[2][1], because generation 1 and generation 2 hash differently.</expected>\n<wrong_implementation>An id derived without the generation, i.e. sha256 of [actor, uuid, host, type]. Both Likes would carry one id and the re-like would collapse as a duplicate. Today's random ids pass this line (the run got past it); :155 carries the red.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_13_deterministic_event_ids_phase2.py:155 \u2014 like, undo_like, like publishes exactly [Like at generation 1, UndoLike at generation 1, Like at generation 2], each id from the formula</assertion>\n<expected>[(\"Like\", _event_id(pid, v, \"Like\", 1)), (\"UndoLike\", _event_id(pid, v, \"UndoLike\", 1)), (\"Like\", _event_id(pid, v, \"Like\", 2))]</expected>\n<wrong_implementation>Random ids fail at index 0: the run read 'client-4a39328d-d608-\u2026' against 'client-ebc4288cc953\u2026'. An UndoLike that reads the generation after bumping it (g2), or reads 0, fails at index 1. A different serialisation, such as a separator join or compact JSON, fails every index.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_13_deterministic_event_ids_phase2.py:162 \u2014 two anonymous likes both publish (\"Like\", id of [\"anonymous\", uuid, host, \"Like\", 0])</assertion>\n<expected>[(\"Like\", _event_id(\"anonymous\", video, \"Like\", 0))] * 2</expected>\n<wrong_implementation>Random ids (the run read 'client-b20648d6-\u2026' against 'client-aaf04505\u2026'). Hashing `profile_id` (None, which serialises as `null`) instead of \"anonymous\" also gives another id, as does using generation 1 for anonymous likes.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_13_deterministic_event_ids_phase2.py:163 \u2014 the real Engine ingest reports the two anonymous likes' duplicate flags as [False, True]</assertion>\n<expected>[False, True]</expected>\n<wrong_implementation>Any id that is not fixed for (anonymous, video, Like, 0). The earlier probe saw [False, False] with today's random ids. This run stopped at :162 first.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_13_deterministic_event_ids_phase2.py:174 \u2014 a like that names the video as an upper-case uuid and host \"IDS.Example\" publishes the id over the uuid and host the Engine resolved them to (lower-case)</assertion>\n<expected>[(\"Like\", _event_id(pid, canonical, \"Like\", 1))]. The controls at :172 and :173 passed, so the resolved lower-case uuid and host do reach the payload's object.</expected>\n<wrong_implementation>Hashing the request body's raw `uuid`/`host` instead of the resolved `canonical_uuid`/`canonical_host`. That hashes the upper-case spelling and gives a different digest. The run read today's 'client-2dd2d03b-\u2026' (uuid4) against 'client-e2fff181\u2026'.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_13_deterministic_event_ids_phase2.py:192 \u2014 like then dislike publishes the Like at generation 1 and the UndoLike at generation 1, the id a profile undo_like would have used</assertion>\n<expected>[(\"Like\", _event_id(pid, liked, \"Like\", 1)), (\"UndoLike\", _event_id(pid, liked, \"UndoLike\", 1))]</expected>\n<wrong_implementation>Random ids (the run read 'client-8964b24e-\u2026' against 'client-a5b72b00\u2026'). A dislike branch that returns generation 0, the `undo_dislike` tail's default, gives a different UndoLike id.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_13_deterministic_event_ids_phase2.py:212 \u2014 after like, reset, like, undo_like, the events are the Like and the UndoLike, both at generation 1</assertion>\n<expected>[(\"Like\", _event_id(pid, video, \"Like\", 1)), (\"UndoLike\", _event_id(pid, video, \"UndoLike\", 1))]</expected>\n<wrong_implementation>Bumping the generation on the post-reset re-like, which puts the UndoLike at generation 2 and leaves the Engine's generation-1 Like standing. This run stopped at :208 before reaching :212.</wrong_implementation>\n</row>\n</rows>\n\n<answers>\n1. Whole claim: yes, there was a gap, so I rewrote. C2 names the *canonical* uuid and host. The stub's resolve echoed the request, so the canonical and raw values were always identical. An implementation hashing the raw `body[\"uuid\"]`/`body[\"host\"]` would have passed every C2 assertion. I changed the stub's resolve to lower-case the uuid and host as its canonical identity. `_video()` inputs are already lower-case, so the other tests are unaffected. I added `test_a_like_named_in_a_non_canonical_spelling_derives_its_id_from_the_resolved_identity`: it sends an upper-case uuid and host \"IDS.Example\", checks with controls (:172, :173) that the resolved values reach the payload, and asserts the id over the canonical pair (:174). The docstring gains a matching bullet and describes the stub accurately. On a second pass every docstring bullet is carried: C1 by :140, :153, :181, :197, :208 and :222; C2 by :142, :154, :155, :162, :163, :174, :192 and :212.\n2. Absence only: no. Each negative has a positive control in the same test. :181 has :184 (the rig publishes a later like). :197 has :195 (the dislike was stored) and :191/:192 (this rig published in this test). :222 has :218, :219, :221 and :225. :208's single-Like assertion has :205 and :207 (the reset happened and the re-like was stored).\n3. Echoed literal: no. `_event_id` builds the expected id from the approved formula (plan 16-13 line 120, with the `json.dumps` defaults pinned at line 268), using inputs the test holds independently: pid from the mint response, the video it chose, and literal types and generations. It never calls production code. The production line whose deletion turns these red is the handler's `event_id` derivation that replaces `server.py:802` (`f\"client-{uuid4()}\"`). Today that line still produces uuid4, and every id assertion is red against it.\n4. One value: no, after the rewrite. The id is read at generations 0, 1 and 2, for actors pid and \"anonymous\", for types Like and UndoLike, across several videos, and now with a request spelling that differs from the canonical one. C1 is read across repeat like, undo of an unliked video, dislike and undo_dislike of an unliked video, re-like after reset, and undo of an imported like.\n5. The double: the Engine is stubbed at its HTTP seam, and the Engine is owned by this project. That seam is the approved phase 2 checkpoint's design. The part the claims judge, collapsing duplicates by id, runs the real `ingest_interaction_event` on a tmp engine.db. Resolve (now lower-casing, where the approved text said \"echoes\") and centroids are stand-ins for Engine lookups whose real behaviour is not under test. The lower-casing is a stand-in for canonicalisation. It is not a claim about the real Engine's rule, so it proves only that the Client hashes whatever resolve returns. I'm disclosing the change from \"echoes\".\n6. It collects: yes. Every import resolved and every name bound. The run printed \"collected 8 items\": 7 tests plus the one I added. The `--collect-only` summary handed to me said \"no tests\", but both full runs collected every test (7, then 8), so that summary line seems to be a reporter artifact rather than a collection failure. The new test uses only helpers already in the file.\n7. Observed, not predicted: controls and today's behaviour are observed. The controls at :172 and :173 passed in the run, which shows the lower-cased resolved identity reaches the payload. The earlier probe observed the reset, import and dislike controls, and they passed again here. The expected ids under the fixed code are a prediction from the plan's pinned formula. They cannot be observed until the phase is built, and the phase's green run will confirm them. I have not changed any assertion to rest on an unobserved harness premise.\n8. Red, not green: yes. `ValidateTests [\"tests/tmp/test_13_deterministic_event_ids_phase2.py\"]` gave \"8 failed\", [exit status 1].\n9. Red for the right reason: yes. Every failure is on a judging assertion, after its controls passed:\n- :140 `assert ['Like', 'Like'] == ['Like']`\n- :155 `('Like', 'client-4a39328d-d608-44b2-989f-e2b8dfe5711e') != ('Like', 'client-ebc4288cc953\u2026')`\n- :162 `('Like', 'client-b20648d6-\u2026') != ('Like', 'client-aaf04505\u2026')`\n- :174 `('Like', 'client-2dd2d03b-c886-477e-88f9-471aeab8447c') != ('Like', 'client-e2fff18147b6\u2026')`, with the controls at :172 and :173 passing\n- :181 `assert [({'event_id': 'client-baaa0e7b-\u2026', 'event_type': 'UndoLike', \u2026})] == []`\n- :192 `('Like', 'client-8964b24e-\u2026') != ('Like', 'client-a5b72b0049ff\u2026')`\n- :208 `assert ['Like', 'Like'] == ['Like']`, with :205 and :207 passing\n- :222 `assert [({'event_id': 'client-a6cd1e61-\u2026', 'event_type': 'UndoLike', \u2026})] == []`, with :218, :219 and :221 passing\n\nNo control failed, and there was no import error, typo or missing path.\n10. Observed expected output: each row's wrong-implementation reading at :140, :155, :162, :174, :181, :192, :208 and :222 is what the run printed. The `expected` column for ids is the formula's value, which the run printed as the right-hand side (e.g. 'client-ebc4288c\u2026'), not an output of fixed code. Rows :142, :163, :197 and :212 were not reached in this run because an earlier assertion in the same test failed first. Their today-values ([False, False] for :163, 0 events for :197) come from the earlier probe, and the rows say so. :153 and :154 passed today, as the rows state. They are guards, not red gates.\nHousekeeping: `tests/tmp/probe_13_phase2.py` (emptied) and `tests/tmp/probe_cap.py` are left over from earlier turns. They need deleting; I have no delete tool. Apart from the named test file, I touched nothing.\n</answers>\n\n<exemptions>\nnone\n</exemptions>",
    "step_7_implement:2": "<changes>\n### `client/backend/lib/users_store.py`\n- `ensure_user_schema` now also creates `like_generations(user_id, video_id, instance_domain, generation INTEGER NOT NULL, published INTEGER NOT NULL DEFAULT 0)`, keyed on `(user_id, video_id, instance_domain)`, with `CREATE TABLE IF NOT EXISTS`. It sits before the `local-user` cleanup, and the docstring names the new table.\n- `record_like` takes a new keyword `publish: bool = False` and returns `(opened, generation)`.\n  - The `likes` INSERT is now `ON CONFLICT DO NOTHING`, and its own rowcount decides whether the like is new. An existing row gets a plain UPDATE of `video_uuid`/`updated_at`, so recency and the trim work as before.\n  - A new like with `publish=True` runs a conditional upsert on `like_generations`. It inserts `(g=1, published=1)`, or sets `g+1, published=1` only when `published = 0`. The rowcount is `opened`.\n  - A re-like after a reset or trim, while the like is still published, therefore opens nothing. An imported like (`publish` left False) never touches `like_generations`.\n  - The trim and the commit are unchanged. The import caller ignores the return value.\n- New `like_generation(conn, user_id, video_id, instance_domain) -> int` returns the stored generation, or 0 when there is no row. It uses `row[0]`, so it works with or without a `row_factory`.\n- New `close_like(conn, user_id, video_id, instance_domain) -> tuple[bool, int]` runs `UPDATE ... SET published = 0 ... AND published = 1`. It returns whether a published like was closed, plus that like's generation. It does not commit: it runs inside the caller's transaction, like `remove_like`.\n\n### `client/backend/server.py`\n- Added `import hashlib`. `close_like` joins the `lib.users_store` import. `uuid4` stays because `run_id` still uses it.\n- `_store_reaction` now returns `(publish, generation)`:\n  - plain like, and like replacing a dislike: `record_like(..., publish=True)`;\n  - undo_like: `remove_like` then `close_like`, in the same `with conn`;\n  - dislike: `remove_like`, `close_like` and `write_dislike` in the existing write transaction, still after the limit check and the centroids request;\n  - undo_dislike: `(False, 0)`.\n  - The `:returns:` docstring is rewritten.\n- `_handle_user_action`:\n  - Anonymous requests keep `publish = action in (\"like\", \"undo_like\")` at generation 0. A profile's request publishes only what `_store_reaction` reports. A no-change request falls through to the existing 200 `{ok, updatedAt}`.\n  - `actor = profile_id or \"anonymous\"` is computed once and used for both the id and `actor_id`.\n  - `event_id` is `\"client-\" + sha256(json.dumps([actor, canonical_uuid, canonical_host, event_type, generation]))`. It hashes the Engine-resolved uuid and host, not the spelling sent.\n  - The docstring now states the publish rule. Other payload fields and the error paths are unchanged.\n\n### `tests/active/test_event_ids.py`\nNot created. The gating checkpoint `tests/tmp/test_13_deterministic_event_ids_phase2.py` covers T1\u2013T8. I left moving it into `tests/active` to the workflow rather than make a copy.\n</changes>\n\n<inner_tests>\nnone\n</inner_tests>\n\n<unanticipated>\ntests/tmp/probe_like_generations.py: a throwaway probe I wrote to check SQLite's behaviour. When the `DO UPDATE ... WHERE` condition is false, the upsert reports rowcount 0. The probe ran the new users_store functions through open, repeat, close, re-open, reset and import. It passed, and every step returned the `(opened/closed, generation)` it should. I have no delete tool, so it is still there; please delete it. Running it also rewrote `tests/last_test_validation.json` and `tests/last_test_output.txt` with that one probe's result.\n</unanticipated>\n\n<awaiting_operator>\nnone\n</awaiting_operator>",
    "author:tests/tmp/test_13_deterministic_event_ids_phase3.py": "<assertions>\ntests/tmp/test_13_deterministic_event_ids_phase3.py:65 \u2014 control: before the delete, the profile to be deleted holds {\"profiles\": 1, \"users\": 1, \"likes\": 1, \"like_generations\": 2}. That is one open generation row and one closed one (published=0) left by a like that was undone, so a count of 0 later cannot come from rows that were never seeded \u2014 control\ntests/tmp/test_13_deterministic_event_ids_phase3.py:66 \u2014 control: before the delete, the other profile holds {\"profiles\": 1, \"users\": 1, \"likes\": 1, \"like_generations\": 1} \u2014 control\ntests/tmp/test_13_deterministic_event_ids_phase3.py:69 \u2014 a delete with no key is refused with 401 \u2014 control\ntests/tmp/test_13_deterministic_event_ids_phase3.py:70 \u2014 after the refused delete, the profile still has 2 like_generations rows, so a delete that goes through without a valid key is caught \u2014 C1\ntests/tmp/test_13_deterministic_event_ids_phase3.py:73 \u2014 a delete with the key answers 204 \u2014 control\ntests/tmp/test_13_deterministic_event_ids_phase3.py:75 \u2014 after the delete, the deleted profile has {\"profiles\": 0, \"users\": 0, \"likes\": 0, \"like_generations\": 0}. Under the current delete_profile it still has like_generations 2 (observed). A delete that removed only published=1 rows, or only generations matching the likes rows it deletes, would leave 1 \u2014 C1\ntests/tmp/test_13_deterministic_event_ids_phase3.py:76 \u2014 after the delete, the other profile keeps {\"profiles\": 1, \"users\": 1, \"likes\": 1, \"like_generations\": 1}, so an unscoped DELETE FROM like_generations is caught \u2014 C1\n</assertions>\n\n<probes>\nWrote tests/tmp/probe_13_phase3.py and ran it with ValidateTests [\"tests/tmp/probe_13_phase3.py\", \"-s\"] against the current, unimplemented code. The probe mints two profiles over HTTP on client_backend and seeds each with record_like(..., publish=True). It then seeds the first profile with a second like and undoes it through remove_like and close_like, and prints the counts before and after the deletes. Output: seed (True, 1) twice; undone seed (True, 1); close (True, 1). Before: gone {'profiles': 1, 'users': 1, 'likes': 1, 'like_generations': 2} with generation rows [(v-\u2026, 1, published 1), ('v-undone', 1, published 0)]; kept {'profiles': 1, 'users': 1, 'likes': 1, 'like_generations': 1}. Unkeyed delete gave (401, {'error': 'Profile key required'}); keyed delete gave (204, None). After: gone {'profiles': 0, 'users': 0, 'likes': 0, 'like_generations': 2}; kept unchanged. The value under the wrong (current) implementation is therefore like_generations 2, and the checkpoint's line 75 fails on exactly that key. I have no delete tool, so tests/tmp/probe_13_phase3.py is still on disk and needs removing. It ends in `assert False`, but its probe_ prefix keeps pytest from collecting it by default.\n</probes>\n\n<unassertable>\nnone\n</unassertable>",
    "self_check:tests/tmp/test_13_deterministic_event_ids_phase3.py": "<rows>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_13_deterministic_event_ids_phase3.py:75 \u2014 after the keyed POST /api/profile/delete for `gone_id` returns 204, `_rows_for(gone_id)` == {\"profiles\": 0, \"users\": 0, \"likes\": 0, \"like_generations\": 0}. Line 76 checks the other profile: `_rows_for(kept_id)` == {\"profiles\": 1, \"users\": 1, \"likes\": 1, \"like_generations\": 1}.</assertion>\n<expected>Line 75: all four counts are 0 for the deleted profile. Before the delete that profile had 2 `like_generations` rows, one open (published=1) and one closed (the undone like, published=0), and the control on line 65 showed that. Line 76: the other profile still has 1/1/1/1, the same as before the delete (line 66).</expected>\n<wrong_implementation>(a) The current code leaves `like_generations` untouched. Line 75 then reads {\"profiles\": 0, \"users\": 0, \"likes\": 0, \"like_generations\": 2}, which is what this run showed. (b) A delete that finds generations through the likes rows it removes (e.g. `DELETE FROM like_generations WHERE (user_id, video_id, instance_domain) IN (SELECT ... FROM likes WHERE user_id = ?)`) misses the closed 'v-undone' generation, whose likes row is already gone. Line 75 then reads like_generations: 1. (c) A delete with no user filter (`DELETE FROM like_generations`) passes line 75, but line 76 then reads like_generations: 0 for the other profile.</wrong_implementation>\n</row>\n</rows>\n\n<answers>\n1. Whole claim: no gaps. C1 has two parts. \"No `like_generations` rows after delete\" is line 75, and it covers both an open and a closed generation row. \"Another profile keeps its rows\" is line 76. The docstring's claims about the open and closed rows are both set up by the seeding and checked. Lines 69\u201370 (an unkeyed delete gets 401 and removes nothing) are supporting controls, not a C1 row.\n2. Absence only: no. Line 75 asserts zero rows, but three things show the path ran and the rows existed first. Line 73 checks the delete returned 204. The controls on lines 65\u201366 show the rows were there beforehand (2 and 1). Line 75's own dict needs profiles/users/likes to go to 0, which proves the delete handler actually ran.\n3. Echoed literal: no. The test only seeds rows through `record_like`/`remove_like`/`close_like` and counts them with plain SELECT COUNT. It never performs the delete itself. The production line that will turn line 75 green is the `DELETE FROM like_generations WHERE user_id = ?` the phase adds to the profile-delete path. Take that line out and line 75 reads like_generations: 2, which is what this run shows now.\n4. One value: no. There are two profiles, and the deleted one has two kinds of generation row (open and closed). That separates \"delete by user\" from \"delete via likes rows\" and from \"delete everything\" (see wrong implementations b and c).\n5. The double: no. Nothing is faked. `client_backend` is the real Client backend over HTTP with a real users.db, and the seeding helpers are the project's real `lib.users_store` functions.\n6. It collects: yes. The collect-only summary printed \"no tests\" with exit 0, but the real run printed \"collected 1 item\". All imports resolve, `client_backend.db_path` exists (the failure output shows `ClientBackend(base=..., db_path=PosixPath('.../users.db'))`), and the helper signatures match the probe that ran them.\n7. Observed, not predicted: yes. I ran tests/tmp/probe_13_phase3.py with -s. It printed before: gone {'profiles': 1, 'users': 1, 'likes': 1, 'like_generations': 2, gen_rows [(..., 1, 1), ('v-undone', 1, 0)]}, kept {1,1,1,1}. Then unkeyed delete (401, {'error': 'Profile key required'}), then delete (204, None). After: gone {'profiles': 0, 'users': 0, 'likes': 0, 'like_generations': 2}, kept {1,1,1,1}. Every control value and the kept-profile expectation on line 76 comes from that run. The only unobserved value is like_generations: 0 on line 75, because it is the phase's own claim. There was no yes in 1\u20137, so I did not rewrite the test.\n8. Red, not green: yes, it fails. ValidateTests on the checkpoint: \"1 failed\", \"recorded: tests/last_test_validation.json (exit 1)\", [exit status 1].\n9. Red for the right reason: yes. It failed at line 75, `assert _rows_for(client_backend.db_path, gone_id) == {\"profiles\": 0, \"users\": 0, \"likes\": 0, \"like_generations\": 0}`, with \"Omitting 3 identical items ... Differing items: {'like_generations': 2} != {'like_generations': 0}\" (tests/tmp/test_13_deterministic_event_ids_phase3.py:75: AssertionError). Every control before it passed: 65, 66, 69, 70 and 73. So profiles/users/likes are deleted and only the phase's `like_generations` cleanup is missing.\n10. Observed expected output: yes. Line 75's actual value (like_generations 2, the other three counts 0) matches wrong implementation (a) in the row and the probe's \"after\" line. Line 76's expectation (kept 1/1/1/1 after the delete) comes from the probe's \"after\" output, since the checkpoint stops at line 75. Nothing the run showed contradicts the row. I left tests/tmp/probe_13_phase3.py in place because I have no delete tool; it ends in `assert False` and should be removed.\n</answers>\n\n<exemptions>\nnone\n</exemptions>",
    "step_7_implement:3": "<changes>\n### client/backend/lib/profiles.py\n`delete_profile` now also runs `DELETE FROM like_generations WHERE user_id = ?` inside its existing `with conn:` transaction, right after the `likes` delete. It deletes by `user_id`, not by the likes it just removed, so closed generations (rows left behind after an undone like) go too. The table has no foreign keys, so the order of the deletes doesn't matter.\n\n### tests/active/test_profiles.py\nNot changed. The phase lists it as EDITED, but it is a durable test that has already gated, so this step can't touch it. Its `test_deleting_a_profile_removes_its_rows_and_keeps_anothers` still holds, because it only counts `profiles`, `users` and `likes`. Moving the checkpoint's `like_generations` assertions into this file is left to the promotion step.\n</changes>\n\n<inner_tests>\nnone\n</inner_tests>\n\n<unanticipated>\nnone\n</unanticipated>\n\n<awaiting_operator>\nnone\n</awaiting_operator>",
    "step_8_i1_refactor": "<refactors>\nnone. The disk copies of users_store.py, server.py, profiles.py and random_videos.py match what was inlined, and none of the new code this build added needed restructuring.\n</refactors>\n\n<left_out>\nengine/server/data/random_videos.py: the three fetch_* functions repeat the same SELECT column list and the same row-to-dict loop. That repetition was there before this build. Phase 1 only changed the popular ORDER BY term and the params list, so pulling out a shared helper would change code this build never touched. It would also change fetch_recent_videos, which no checkpoint here covers.\nengine/server/data/random_videos.py: fetch_popular_videos builds params with its own two literal lists, one with the error threshold and one without. I kept that because the sibling functions build theirs the same way, and the two lists put each ? in SQL order where it is easy to see.\nclient/backend/lib/users_store.py: record_like calls like_generation separately rather than reading the generation back from the upsert with RETURNING. It costs one extra SELECT, but like_generation is also what close_like uses, and RETURNING would depend on the SQLite version in a way I haven't checked here.\nclient/backend/lib/users_store.py: get_or_create_user commits inside record_like, even though _store_reaction and _handle_likes_import call it within `with conn:`. That was true before this build. The likes and like_generations writes both come after that commit, so they still land together. Changing where commits happen would be a behaviour change, not a refactor.\nclient/backend/server.py: I left _store_reaction's three branches as they are. They return (publish, generation) in the same shape, and folding them together would mix the dislike path, which asks for centroids first, with the like paths, which don't.\nThe throwaway probes in tests/tmp (probe_cap.py, probe_13_phase2.py, probe_13_phase3.py, probe_like_generations.py) should be deleted. I have no delete tool, so they are still there. The step's \"What the pass is measured against\" section showed a blank placeholder ({rat_tail_rules}) instead of rules, so I checked the pass against the role's rat-tail and smallest-change rules.\n</left_out>\n\n<needs_fresh_red>\nnone\n</needs_fresh_red>\n\n<observation>\nNone of the build's new code (the popular signal cap, the like_generations tracking in record_like and close_like, the derived event ids in _handle_user_action, and the like_generations delete in delete_profile) needed restructuring. The only repetition in these files was there before the build, so the pass left all production code as it was and ran no tests.\n</observation>",
    "step_9_triage": "<docs>\n<doc path=\"client/README.md\" update=\"yes\">\nLine 19 (`POST /api/user-action`): \"A like publishes its event and is kept server-side only when a profile key is sent\" now reads as if every like publishes, which is wrong. Reword it to say that with a key, a `like` publishes a `Like` only when it opens the profile's published like of the video, and an `undo_like`, or a dislike replacing a like, publishes an `UndoLike` only when it closes one. A request that changes nothing answers 200 `{ok, updatedAt}` and publishes nothing. Without a key, every `like` and `undo_like` publishes under one fixed id per video and event type, so repeats are duplicates at the Engine. Event ids are `client-` plus the SHA-256 of actor, Engine-resolved video uuid and host, event type, and like generation (0 for anonymous). Line 15 (likes import): add that imported likes never open a published like, so un-liking one publishes nothing. Line 13 (`POST /api/profile/delete`): add like generations to the list of what is removed.\n</doc>\n<doc path=\"DEPLOYMENT.md\" update=\"yes\">\nLines 259-261 say only that `/api/user-action` emits the interaction events. Add that a profile's `Like`/`UndoLike` is published only when it opens or closes the profile's published like (tracked in `users.db` `like_generations`, created at startup with no migration step). Also add that event ids are derived, so replays collapse at the Engine's ingest, and that keyless likes carry one fixed id per video and event type. Line 267 (\"disliking a liked video publishes the `UndoLike` that withdraws the like\") stays true. Near lines 71-72 (the `interaction_signals` ranking signal), add that the popular ordering adds at most 25.0 of a video's signal (`POPULAR_SIGNAL_CAP` in `engine/server/data/random_videos.py`), while the stored score stays uncapped.\n</doc>\n<doc path=\"engine/server/api/recommendations/docs/OVERVIEW.md\" update=\"yes\">\nLine 99, \"popular pool: top by likes/views\", no longer describes `fetch_popular_videos`. State that the pool is ordered by `popularity` plus the interaction signal capped at `POPULAR_SIGNAL_CAP` (25.0), then by likes, views, recency and video id. The rest of the line (\"if likes exist, re-ranked by similarity; then caps\") is unchanged. Line 109 (the scoring `popularity` feature) is a different thing and stays.\n</doc>\n<doc path=\"engine/server/api/recommendations/docs/PIPELINE_DIAGRAM.md\" update=\"yes\">\nLine 29, `G3[popular<br/>top likes/views]`, misstates the pool order. Change the label to `popularity + capped signal`. The change is cosmetic, but the label is wrong as it stands.\n</doc>\n<doc path=\"engine/server/api/recommendations/docs/LAYER_PARAMS.md\" update=\"yes\">\nNot on the checklist. Line 137, \"**Source:** top videos by likes/views.\", has the same false claim as OVERVIEW line 99. Make it: top videos by `popularity` plus the interaction signal capped at `POPULAR_SIGNAL_CAP` (25.0), then likes and views. Line 148 describes scoring after the pool and stays.\n</doc>\n<doc path=\"CONTEXT.md\" update=\"yes\">\n**Interaction event** (line 6) and **Interaction signal** (line 7) still match the build and need no change. Add a term, because the build's \"real state change\" is defined by it and not by the profile's likes list: **Published like** \u2014 a profile's like of one video that has reached the Engine. The Client tracks it with a like generation in `like_generations`. Opening a new one advances the generation, and closing it (un-like, or a dislike replacing the like) keeps the generation. It is unaffected by a reset, the `max_likes` trim or the likes import, and it is removed with the profile. A `Like` is published only when one opens and an `UndoLike` only when one closes.\n</doc>\n<doc path=\"docs/project/adr/0001-derived-interaction-event-ids.md\" update=\"yes\">\nThe decision stands. Add to Consequences the like-instance scheme that landed: the Client's `like_generations` row per (profile, video) with a `published` flag. A like publishes, and advances the generation, only when it opens a published like. An un-like or replacing dislike publishes only when it closes one, at the same generation. Rows survive un-like, reset and trim and are deleted with the profile. As a result, imported likes never publish or open a like, so un-liking them publishes nothing; the reset (+1) and import\u2192undo (\u22121) loops do not exist; and a like dropped by the `max_likes` trim can still be withdrawn. Likes that predate the table un-like as nothing (no published row), so they publish no `UndoLike`. See also adr_conflicts on decision 1's wording.\n</doc>\n<doc path=\"docs/project/issues/01-deterministic-event-ids.md\" update=\"yes\">\nAt harvest on main: tick acceptance criteria lines 55-62, set `Status:` to `bug, complete`, and move the file to `docs/project/issues/archive/` per `docs/project/triage-labels.md`.\n</doc>\n<doc path=\"docs/project/plans/13-deterministic-event-ids.md\" update=\"yes\">\nAt harvest: mark it delivered, point it to `16-13-deterministic-event-ids.md`, and archive it. Line 97's open question is answered: `delete_profile` exists and removes `like_generations`. Line 96 (\"Trimmed likes ... the plan does not close it\") is superseded by the `published` flag, since a trimmed like still closes on un-like. Also record that `clear_likes` (reset) keeps generations and their published state by design. Line 98 holds: import publishes nothing, and it never touches `like_generations`.\n</doc>\n<doc path=\"docs/project/roadmap.md\" update=\"yes\">\nAt harvest, add a Delivered line for security issue `01`, deterministic event ids and the popular signal cap, pointing at the archived plan. Drop `01` from \"Open security issues: `01` to `05` and `07`\" (line 26) and from implementation-order step 1 (line 138). Of the checklist's optional follow-ups, the reset/import loops and the trim gap are closed by the delivered `published` flag and must not be added. Only two remain, as optional lines: decide whether the likes import should publish, and bound the popular likes tiebreaker (`v.likes + sig.likes_count`), which the cap does not cover.\n</doc>\n<doc path=\"docs/project/adr/0005-raw-event-retention-keeps-ids.md\" update=\"no\">\nIts claims (strip, don't delete; kept ids catch replays including the fixed anonymous `Like` id) are exactly what the build relies on, and nothing in it is made false.\n</doc>\n<doc path=\"README.md\" update=\"no\">\nLines 37-40 say only that interaction events update `interaction_signals`, which ranking uses. That is still true, and the file makes no claim about event ids or the popular ordering.\n</doc>\n</docs>\n\n<adr_conflicts>\nADR-0001 decision 1 reads: \"A `like` on a video the profile already likes, or an `undo_like` on one it does not, publishes nothing.\" The delivered gating does not key on the profile's `likes` list. It keys on the published-like state in `like_generations` (`published` flag). So after a reset or a `max_likes` trim, an `undo_like` on a video the profile no longer \"likes\" still publishes an `UndoLike`, because it closes a published like. And a re-like of that video, which is new in `likes`, publishes nothing, because the like is still published. An un-like of an imported like publishes nothing even though the profile \"likes\" it. This fits the decision's intent (\"only on a real state change\", and it closes the reset/import loops the requirements had accepted), but it departs from the ADR's literal wording. Amending decision 1 to say \"published like\" is the operator's call. The build also departs from the requirements text, though not from any ADR: the generation advances only when a published like opens, not on every new `likes` row, and imported likes do not advance it.\n</adr_conflicts>",
    "step_9_i2_update:client/README.md": "<changes>\n`client/README.md`: `POST /api/user-action` now says when each action publishes and how event ids are built. The likes import and profile delete entries now cover like generations.\n\n- **Line 19, `POST /api/user-action`:** removed the sentence saying every like publishes. With a key, the action is stored in the profile, and a like and a dislike on one video replace each other.\n  - A `like` publishes a `Like` only when it opens the profile's published like of the video. The line points to **Published like** in `CONTEXT.md` for the definition and does not repeat it there.\n  - An `undo_like`, or a dislike that replaces a like, publishes an `UndoLike` only when it closes one. No other dislike action publishes.\n  - A request that changes nothing answers 200 `{ok, updatedAt}` and publishes nothing.\n  - Without a key, nothing is stored. Every `like` and `undo_like` publishes, with one fixed id per video and event type, so the Engine counts repeats as duplicates.\n  - An event id is `client-` plus the SHA-256 of: the actor (profile id or `anonymous`), the video uuid and host as the Engine resolved them, the event type, and the like generation (0 without a key).\n  - The dislike limit, the taste-vector request and the 502 behaviour are unchanged.\n  - I checked all of this against `_handle_user_action` and `_store_reaction` in `server.py`.\n- **Line 15, likes import:** an imported like opens no published like, so un-liking it publishes nothing. The one exception: if the profile's own earlier like of that video is still published (for example after a reset), the un-like closes it and does publish. `record_like` with `publish=True` does not reopen a like that is still published, which is why the checklist's flat \"publishes nothing\" would be wrong.\n- **Line 13, profile delete:** added like generations to what is removed, matching `delete_profile`.\n</changes>\n\n<not_on_checklist>\nnone\n</not_on_checklist>",
    "step_9_i2_update:DEPLOYMENT.md": "<changes>\nDEPLOYMENT.md: added the 25.0 popular signal cap (section 1) and the publish-on-change rule, the `like_generations` table and derived event ids (section 5).\n\n- **Section 1**, after the `interaction_signals` note: the popular ordering adds at most 25.0 of a video's signal score to its crawled popularity. The limit is `POPULAR_SIGNAL_CAP` in `engine/server/data/random_videos.py`, and the stored score stays uncapped. I checked this against the `ORDER BY` in `fetch_popular_videos`, which reads `v.popularity + MIN(COALESCE(sig.signal_score, 0), ?)` with the constant bound as a parameter.\n- **Section 5**, new paragraph after the `/api/user-action` paragraph:\n  - With a key, a `Like` is published only when the request opens the profile's published like of the video, and an `UndoLike` only when it closes one.\n  - A request that changes nothing answers 200 and publishes nothing.\n  - Published likes are tracked in the `users.db` `like_generations` table. It is created at startup by `ensure_user_schema` in `server.py`, so there is no migration step.\n  - Event ids are derived, so a replayed event is a duplicate at the Engine's ingest and changes no counts.\n  - Keyless requests always publish, and every keyless `Like` of a video carries one fixed id, as does every keyless `UndoLike`.\n  - The section points to `CONTEXT.md` for what a published like is and to ADR-0001 for the id scheme rather than restating them.\n  - I checked all of this against `_handle_user_action`, `record_like` and `close_like`.\n- The existing line saying \"disliking a liked video publishes the `UndoLike` that withdraws the like\" is unchanged, since it is still true.\n</changes>\n\n<not_on_checklist>\nnone\n</not_on_checklist>",
    "step_9_i2_update:engine/server/api/recommendations/docs/OVERVIEW.md": "<changes>\nOVERVIEW.md: the popular pool's order now reads `popularity` plus the interaction signal capped at `POPULAR_SIGNAL_CAP` (25.0), not \"top by likes/views\".\n\n- \u00a74 \"What Pools Are\", the popular pool line (old line 99): changed \"top by likes/views\" to \"top by `popularity` plus the interaction signal capped at `POPULAR_SIGNAL_CAP`, then likes and views\". The rest of the line (\"if likes exist, re-ranked by similarity; then caps\") is unchanged.\n- \u00a73 popular layer, the `Source:` line (old line 69): this made the same wrong claim, \"top by likes/views with a soft freshness bonus\". It now gives the full order: `popularity` plus the capped signal (with the constant's value and file), then likes, views, recency and video id. I also removed the \"soft freshness bonus\", because neither `fetch_popular_videos` nor `PopularVideosGenerator` applies one. Freshness only comes in later, in the unified scoring (\u00a75), which covers every layer.\n- Checked against the code: in `engine/server/data/random_videos.py`, `POPULAR_SIGNAL_CAP = 25.0` is at line 12, and `fetch_popular_videos` orders by `(v.popularity + MIN(COALESCE(sig.signal_score, 0), ?)) DESC`, then `v.likes + sig.likes_count`, `views`, `published_at` and `video_id`.\n- The \u00a75 scoring `popularity` feature is a separate thing and is unchanged.\n</changes>\n\n<not_on_checklist>\nnone\n</not_on_checklist>",
    "step_9_i2_update:engine/server/api/recommendations/docs/PIPELINE_DIAGRAM.md": "<changes>\nChanged the popular-layer node label (line 29) from `top likes/views` to `popularity + capped signal`.\n\n- Line 29 is now `G --> G3[popular<br/>popularity + capped signal]`.\n- I checked it against the code. `fetch_popular_videos` in `engine/server/data/random_videos.py` orders first by `v.popularity + MIN(COALESCE(sig.signal_score, 0), ?)`, and the cap is bound from `POPULAR_SIGNAL_CAP = 25.0`.\n- The cap value and the tie-breakers are left out of the diagram. OVERVIEW.md and LAYER_PARAMS.md describe those.\n- No other node changed. `H3[Popular pool<br/>rank by similarity if likes]` and the scoring `w_pop*popularity` term are separate steps and were already correct.\n</changes>\n\n<not_on_checklist>\nnone\n</not_on_checklist>",
    "step_9_i2_update:engine/server/api/recommendations/docs/LAYER_PARAMS.md": "<changes>\nFixed the popular layer's **Source:** line (line 137). It now describes the actual pool order: `popularity` plus the capped interaction signal, then likes, then views.\n\n- Before, line 137 said \"top videos by likes/views\". It now reads: \"top videos by `popularity` plus the interaction signal capped at `POPULAR_SIGNAL_CAP` (25.0, `engine/server/data/random_videos.py`), then by likes and views.\"\n- I checked this against `fetch_popular_videos` on disk. The constant `POPULAR_SIGNAL_CAP = 25.0` is at line 12. The query orders by `(v.popularity + MIN(COALESCE(sig.signal_score, 0), ?)) DESC`, then `(v.likes + COALESCE(sig.likes_count, 0)) DESC`, then `v.views DESC`, and the cap is passed as a bound parameter.\n- The \"Behavior:\" line at the end describes re-ranking after the pool is built, so I left it as it was.\n</changes>\n\n<not_on_checklist>\nnone\n</not_on_checklist>",
    "step_9_i2_update:CONTEXT.md": "<changes>\nAdded the glossary term **Published like** to `CONTEXT.md`, which defines what counts as a real like/un-like change.\n\n- The new entry sits after **Interaction signal**. A published like is a profile's like of one video that has reached the Engine. The Client tracks it in `like_generations` with a like generation, and that generation goes into the event id.\n- Opening a published like advances the generation. Closing it (an un-like, or a dislike replacing the like) keeps the same generation.\n- A `Like` is published only when a published like opens, and an `UndoLike` only when one closes.\n- A published like is separate from the likes list. A reset or the `max_likes` trim leaves it open, an imported like never opens one, and deleting the profile removes it. The entry points to ADR-0001.\n- The **Interaction event** and **Interaction signal** entries are unchanged, because they already match the build.\n- I checked every claim against the code:\n  - `record_like` upserts only `WHERE published = 0`, and only for a new like with `publish=True`.\n  - `close_like` sets `published = 0` and runs even when `remove_like` removed nothing, so a like the trim dropped can still be closed.\n  - `clear_likes` touches only `likes`.\n  - `delete_profile` deletes from `like_generations`.\n  - The import calls `record_like` without `publish`.\n</changes>\n\n<not_on_checklist>\nnone\n</not_on_checklist>",
    "step_9_i2_update:docs/project/adr/0001-derived-interaction-event-ids.md": "<changes>\nAdded the like-generation scheme to ADR-0001's Consequences and said what \"real state change\" in decision 1 means. The decisions themselves are unchanged.\n\nFive new Consequences bullets, each checked against `client/backend/lib/users_store.py`, `client/backend/server.py` `_store_reaction` and `client/backend/lib/profiles.py`:\n- **Where the state lives:** the like instance is a generation in the `users.db` table `like_generations`, one row per profile and video with a `published` flag. The bullet names **Published like** and points to `CONTEXT.md` for its definition instead of repeating it. It also says decision 1's \"real state change\" means opening or closing a published like, not a change to the likes list. This covers the conflict with decision 1's wording that the checklist flagged, without rewording the decision.\n- **When events publish:** a like publishes and moves the generation forward only when it opens a published like. An un-like, or a dislike replacing a like, publishes only when it closes one, and uses the same generation as its `Like`. Rows survive un-like, reset (`clear_likes` does not touch the table) and the trim, and are deleted with the profile.\n- **Reset and import:** imported likes (`publish` left False) never open a published like, so un-liking one publishes nothing. A re-like after a reset publishes nothing, because the upsert only fires when `published = 0`. So neither reset nor import can be repeated to push a video's signal up or down.\n- **The `max_likes` trim:** a trimmed like stays published, and the undo_like path calls `close_like` whether or not `remove_like` found a row, so an un-like still withdraws it.\n- **Likes older than the table:** they have no published row, so un-liking one publishes no `UndoLike` and its +1 stays at the Engine.\n</changes>\n\n<not_on_checklist>\nnone\n</not_on_checklist>",
    "step_9_i2_update:docs/project/issues/01-deterministic-event-ids.md": "<changes>\nIssue 01 is marked `bug, complete` with all 8 acceptance criteria ticked, and a copy is in `docs/project/issues/archive/`. The original file still needs deleting, because I can't delete files.\n\n- **Status line:** `Status: bug, ready-for-agent` is now `Status: bug, complete`, the label `docs/project/triage-labels.md` gives delivered issues.\n- **Acceptance criteria:** all 8 boxes (lines 55-62) are ticked.\n- **Checked against the code before ticking:**\n  - `POPULAR_SIGNAL_CAP = 25.0` is a bound parameter in `fetch_popular_videos`.\n  - The `like_generations` upsert and `close_like` are in `users_store.py`.\n  - `server.py` builds `event_id` as `client-` plus a SHA-256 hex digest.\n  - The latest full `tests/active` run passed: exit 0, 146 tests. That includes `test_interaction_events.py`, `test_internal_events.py`, `test_random_videos.py`, `test_profiles.py` and the frontend suites.\n- **Move to archive:** `docs/project/issues/archive/01-deterministic-event-ids.md` is written with the same content. The original at `docs/project/issues/01-deterministic-event-ids.md` has the same edits, so the two agree until it is deleted.\n- **Left as it was:** the problem statement, triage comments, agent brief and out-of-scope list are the issue's own record, so they stay as filed.\n</changes>\n\n<not_on_checklist>\ndocs/project/issues/archive/01-deterministic-event-ids.md \u2014 new file, the archived copy of the issue that `docs/project/triage-labels.md` requires for a `complete` issue. The original `docs/project/issues/01-deterministic-event-ids.md` still needs deleting (e.g. `git rm`), because I can't delete files. Until then the issue is in both places, like `15-remove-single-like.md` is now.\n</not_on_checklist>",
    "step_9_i2_update:docs/project/plans/13-deterministic-event-ids.md": "<changes>\nPlan 13 is now marked delivered and points to `16-13-deterministic-event-ids.md`. Its risks describe the code as built, and a new Delivery section records what the build settled. The file has not been moved to `archive/` yet.\n\n- **Status line** (under the title): says the plan is delivered, built by `docs/project/plans/16-13-deterministic-event-ids.md`, and that plan 16-13 wins where the two differ. It also says the like-instance design in \"High-level plan\" is the one approved at planning, and sends the reader to \"Delivery\" for what the build settled on top of it. This follows the format of the archived plans 10 and 11.\n- **Risks, trimmed likes:** replaced with what the code now does. A trimmed like stays published, so a later un-like still closes it and publishes the `UndoLike`. A re-like opens nothing while the like stays published. I checked this against `record_like`, `close_like` and `_store_reaction`: the publish decision follows `close_like`, not `remove_like`.\n- **Risks, profile deletion:** the open question is answered. `delete_profile` in `client/backend/lib/profiles.py` removes the profile's `like_generations` rows in the same transaction.\n- **Risks, likes import:** still true, and now more precise. Import leaves `publish` unset and ignores the return value, so it publishes nothing and never touches `like_generations` (checked at `server.py`'s import call site).\n- **New \"Delivery / What the build settled\" section:**\n  - the `published` flag, pointing at `CONTEXT.md` **Published like** and ADR-0001's Consequences instead of restating the scheme;\n  - what `record_like(publish=True)` and `close_like` return;\n  - `clear_likes` keeps generations and their published state, by design (checked: it deletes only `likes` rows);\n  - likes stored before the table existed publish no `UndoLike` when un-liked;\n  - the id is hashed over the Engine-resolved uuid and host, and `uuid4` stays imported for `run_id`;\n  - `POPULAR_SIGNAL_CAP = 25.0` is passed as a bound parameter.\n\n**Still to do:** the move to `docs/project/plans/archive/` hasn't happened. I have no move or delete tool, and a copy would leave two versions of the plan. It needs a `git mv` at harvest on main, alongside plan 16-13 and the issue.\n</changes>\n\n<not_on_checklist>\nnone\n</not_on_checklist>",
    "step_9_i2_update:docs/project/roadmap.md": "<changes>\nRoadmap: security issue `01` is now listed as Delivered, removed from the open issues and the implementation order, and has its two remaining follow-ups added as optional M1 lines.\n\n- **Delivered**: added a line after security issue `06`, in the same format. It says the Client derives each `Like`/`UndoLike` id from actor, video, event type and like generation, and that a profile publishes only when a like opens or closes, so repeated likes collapse at the Engine's ingest. It also says the popular ordering adds at most `POPULAR_SIGNAL_CAP` of a video's signal. It points at `docs/project/plans/archive/13-deterministic-event-ids.md`, the path the plan will have once the harvest archives it. That follows the same naming as `archive/10-normalise-instance-hosts.md`, and the file does not exist there yet.\n- **M1**: \"Open security issues\" now reads `02` to `05` and `07`. Added two optional lines under it:\n  - decide whether the likes import should publish (imported likes publish nothing and never open a published like);\n  - bound the popular likes tiebreaker (`v.likes + sig.likes_count` in `fetch_popular_videos`), which `POPULAR_SIGNAL_CAP` does not cover.\n- **Implementation order, step 1**: removed `01`, so it now lists `02`, `03`, then `04`, `05`.\n- Did not add the reset/import loops or the trim gap, because the `published` flag closes them.\n- Checked against the code: `POPULAR_SIGNAL_CAP = 25.0` and the uncapped `v.likes + COALESCE(sig.likes_count, 0)` tiebreaker are both in `engine/server/data/random_videos.py`.\n</changes>\n\n<not_on_checklist>\nnone\n</not_on_checklist>"
  },
  "requirements": "### Goal and purpose\n\nBuild issue `docs/project/issues/01-deterministic-event-ids.md` as triaged. It closes the security-audit finding that repeated `like` posts can push any video to the top of the Engine's popular ordering. Two changes do this. (1) The Client backend derives each interaction event's `event_id` deterministically, so the Engine's existing `ON CONFLICT(event_id) DO NOTHING` collapses replays at ingest. (2) The Engine caps how much the interaction signal can add in the popular ordering. Decisions: `docs/project/adr/0001-derived-interaction-event-ids.md` and `CONTEXT.md` **Interaction event** and **Interaction signal**. This build is plan 13, in wave 2 of the security hardening batch (issues 01-06, `.scratch/security-hardening-batch/notes.md`). It runs in the worktree `/home/enduser/code/PeerTube-browser/.worktrees/fix-13-deterministic-event-ids`, branched from main after plans 10-12 merged, and alongside plan 14.\n\n### Current behavior (verified in the tree)\n\n- `client/backend/server.py` `_handle_user_action` (currently around line 731) builds the event with `\"event_id\": f\"client-{uuid4()}\"` (around line 802). It sets `publish = action in (\"like\", \"undo_like\")`, so every like and undo_like is published even when nothing changed. `actor_id` is `profile_id or \"anonymous\"`. A dislike publishes an `UndoLike` only when `_store_reaction` reports that a like was removed.\n- `_store_reaction(profile_id, action, video)` returns whether a dislike removed a like. It calls `record_like` in two places: the plain-like branch, and the \"like replacing a dislike\" branch. It calls `remove_like` in the undo_like branch and in the dislike branch.\n- `client/backend/lib/users_store.py`: `record_like(conn, user_id, action, video, max_likes) -> None` upserts into `likes` (`ON CONFLICT ... DO UPDATE`), trims to `max_likes`, and commits. `remove_like(conn, user_id, video_id, instance_domain) -> bool` deletes the row and reports whether one was removed. The `likes` row is deleted on un-like, so there is no persistent per-video like instance.\n- `_handle_likes_import` calls `record_like` and publishes nothing.\n- `client/backend/lib/profiles.py` `delete_profile` deletes every row keyed to a profile (blocks, dislikes, dislike_profiles, likes, users, profiles) in one transaction.\n- `engine/server/data/random_videos.py` `fetch_popular_videos` orders its inner subquery by `(v.popularity + COALESCE(sig.signal_score, 0)) DESC` (around line 247), then by `(v.likes + COALESCE(sig.likes_count, 0)) DESC`, then views, published_at and video_id.\n\n### Requirements: like instance (generation)\n\n- Add a new Client table, `like_generations(user_id, video_id, instance_domain, generation)`, keyed on `(user_id, video_id, instance_domain)`. Create it in `ensure_user_schema` with `CREATE TABLE IF NOT EXISTS`, in the same executescript style as the other tables.\n- An un-like never deletes from `like_generations`, so the generation survives the un-like.\n- When `record_like` inserts a new `likes` row, it increments that video's generation for the user, starting from 1 on the first like. Re-liking a video that is already liked leaves the generation unchanged.\n- `record_like` reports whether the like was new and returns the current generation (for example, a `(new, generation)` pair). The exact return shape is the build's choice. The likes-import caller ignores the return value and must keep working unchanged.\n- An `undo_like`, or a dislike that replaces a like, reads the video's current generation for the profile and removes the like with `remove_like`. It publishes only when `remove_like` reports that a like was removed. The generation it uses is the one the matching Like used.\n- Anonymous actors (no resolvable `X-Profile-Key`) use the fixed generation `0`.\n- `delete_profile` in `client/backend/lib/profiles.py` also deletes that profile's `like_generations` rows, in the same transaction.\n\n### Requirements: derived event id\n\n- The event id is `client-` followed by the SHA-256 hex digest of the joined fields `(actor, video_uuid, instance_domain, event_type, generation)`. Actor is the profile id, or `anonymous`. `event_type` is `Like` or `UndoLike`. The joining must be unambiguous (e.g. a separator that cannot confuse field boundaries). This replaces `client-<uuid4>`, and the `uuid4` import goes if nothing else uses it.\n- Every publish of one like, and of the un-like that ends it, uses the same generation. A like made after that un-like uses a different one.\n- The id never embeds raw user input unhashed. It is a non-empty string that the Engine's `normalize_event_payload` accepts.\n- The payload's other fields (`event_type`, `actor_id`, `object`, `published_at`, `source_instance`, `raw_payload`) are unchanged.\n\n### Requirements: publish on change only\n\n- With a profile, a `like` publishes a `Like` only when the like is new. This covers the plain-like branch and a like that replaces a dislike.\n- With a profile, an `undo_like` publishes an `UndoLike` only when a like was actually removed.\n- A `dislike` that replaces a like publishes one `UndoLike`, with the id the matching profile `undo_like` would have used. A dislike on a video that is not liked publishes nothing. `undo_dislike` publishes nothing.\n- A request that changes nothing still returns 200 `{\"ok\": True, \"updatedAt\": ...}` and publishes nothing.\n- Anonymous `like` and `undo_like` always publish, with generation 0. Every anonymous `Like` on a video therefore carries one id, and every anonymous `UndoLike` carries another. Anonymous likes add at most +1 per video and anonymous un-likes subtract at most -1 (ADR-0001 \u00a73, accepted).\n- Error handling is unchanged: 400/404/502 paths, `DislikeLimitReached`, `EngineApiError`, and the centroids-before-write ordering.\n\n### Requirements: ranking cap\n\n- In `engine/server/data/random_videos.py`, add a module-level named constant (e.g. `POPULAR_SIGNAL_CAP = 25.0`). The popular-pool ordering becomes `(v.popularity + MIN(COALESCE(sig.signal_score, 0), <constant>)) DESC`, with the constant passed as a query parameter or interpolated from the constant, never a bare literal.\n- `interaction_signals.signal_score` stays uncapped in storage. The `interaction_signal_score` column the query returns stays the raw value.\n- The secondary likes tiebreaker is unchanged.\n\n### Unchanged (must not be modified)\n\nThe Engine's `ingest_interaction_event()`, `normalize_event_payload()`, the `_event_deltas` weights, and the stored `signal_score`.\n\n### Acceptance criteria\n\n- Posting `like` twice for one video with one profile publishes exactly one `Like`. The video's `likes_count` rises by 1 and its `signal_score` by 1.0.\n- A profile's like \u2192 undo_like \u2192 like sequence publishes Like, UndoLike, Like. The two `Like` events carry different `event_id`s, and the video ends with `signal_score` 1.0.\n- Re-sending an identical, already-published event to the Engine (a bridge retry) is reported as `duplicate: true` and changes no counts.\n- Two anonymous `like` posts for one video produce the same `event_id`, and the Engine counts the second as a duplicate.\n- `undo_like` for a video the profile does not like publishes nothing and returns 200.\n- A dislike replacing a like publishes one `UndoLike`, with the id the matching profile un-like would have used. A dislike on an unliked video publishes nothing.\n- In the popular ordering, a video with `signal_score` 1000 and `popularity` 0 ranks below a video with `popularity` 30 and no signal.\n- `delete_profile` removes the profile's `like_generations` rows.\n- The existing interaction-event tests (`tests/active/test_interaction_events.py`, `tests/active/test_internal_events.py`, `tests/active/test_random_videos.py`) and the security-bundle / frontend suites in `tests/active` still pass.\n\n### Out of scope\n\n- Backfilling or rewriting events already stored with random ids.\n- Changing Engine ingest, `_event_deltas`, or the stored `signal_score`.\n- The secondary likes tiebreaker.\n- `Comment` events.\n- Rate limiting, or requiring a profile for likes.\n- Making the likes-import path publish.\n- Closing the `max_likes` trim gap. When the trim drops a like, the Engine keeps its +1, a later un-like publishes nothing, and a re-like gets a new generation. This gap exists today and is accepted.\n\n### Consistency constraints\n\n- Match the surrounding style: stdlib HTTP handlers, `respond_json`, module-level named constants, env vars read once at startup, stdlib only (`hashlib`). Keep the fewest files, and add no new abstractions with a single implementation.\n- Backwards compatibility is not required beyond the above.\n- Line numbers drift, so re-locate code by function name.\n- Plan 14 edits other handlers in `server.py` and calls `record_like` from import, ignoring its return value. Keep the diff to `_handle_user_action`, `_store_reaction`, `record_like`, `ensure_user_schema`, `delete_profile` and `fetch_popular_videos` to limit merge conflicts.\n\n### Test and run constraints\n\n- Test trees: active `tests/active`, working `tests/tmp`, archive `tests/archive`, delete_me `delete_me`, plans `docs/project/plans`. Record: `tests/last_test_validation.json`. Output: `tests/last_test_output.txt`.\n- Run `validate_tests.py` from the worktree root (`project_dir` = `/home/enduser/code/PeerTube-browser/.worktrees/fix-13-deterministic-event-ids`).\n- Run Engine-backed test files in their own `validate_tests.py` invocations because of the Engine rate limit.\n- The worktree symlinks main's `whitelist.db`, so test Engines share it with other lanes. Tests must use unique video/actor identities, or isolated DBs, so concurrent lanes do not collide.\n- On merge, `tests/last_test_validation.json` and `tests/last_test_output.txt` will conflict. Take main's copy and re-run `validate_tests.py --compare` on the merged tree.\n\n### Baseline suite state\n\nPre-build baseline: exit code 0, variant false (the suite passes before any change).",
  "approved": [
    "1",
    "2",
    "3",
    "3",
    "5",
    "6",
    "9"
  ],
  "initial_solution": "### Approach\n\nTwo changes, one in each service. Both stay inside the six functions the requirements name, plus a small unavoidable edit to the import lines of `server.py`.\n\n**1. Client: generation table and `record_like` (`client/backend/lib/users_store.py`).** `ensure_user_schema` gets one more `CREATE TABLE IF NOT EXISTS like_generations` in the existing executescript, placed before the `local-user` cleanup. It has `user_id`, `video_id`, `instance_domain` and an integer `generation`, with `(user_id, video_id, instance_domain)` as the primary key. `record_like` stops using `ON CONFLICT ... DO UPDATE` to find out whether a like is new. It first inserts the `likes` row with `ON CONFLICT DO NOTHING` and reads the cursor's rowcount: 1 means new, 0 means the video was already liked. When the row already exists it runs the old refresh of `video_uuid` and `updated_at` as a plain UPDATE, so recency ordering and the trim behave exactly as today. When the like is new it upserts `like_generations`: insert generation 1, or on conflict set generation to generation + 1. It then reads the current generation back and returns `(new, generation)`. The trim and the trailing commit are unchanged. The trim never drops the row just inserted, because that row is the newest. The likes-import caller already ignores the result, so it keeps working without edits. An imported new like still advances that video's generation, which the plan accepts (see Risks). Nothing ever deletes from `like_generations` except `delete_profile`, so a generation survives an un-like. This covers \"increments on a new like, from 1\", \"unchanged on a re-like\", and \"the generation survives an un-like\".\n\nThe un-like side needs to read a generation, and `server.py` holds no SQL. So `users_store.py` gains one small reader function. It returns the stored generation for `(user, video_id, instance_domain)`, or 0 when there is no row. `server.py` imports it next to `record_like` and `remove_like`. `remove_like` itself is not changed.\n\n**2. Client: `_store_reaction` (`client/backend/server.py`).** Today it returns \"did a dislike remove a like\". It will return a `(changed, generation)` pair covering every branch:\n- Plain like: the result of `record_like`.\n- `undo_like`: read the generation, then `remove_like`, both inside the same `with conn` block. Returns `(removed, generation)`.\n- Dislike: in its existing write transaction, read the generation before `remove_like` and `write_dislike`. Returns `(removed, generation)`. The centroids are still computed before any write, so the error ordering is unchanged.\n- `undo_dislike`: returns `(False, 0)`.\n- Like replacing a dislike: `delete_dislike` then `record_like`. Returns `record_like`'s pair. Likes and dislikes exclude each other, so this is always new.\n\nThe generation an un-like reads is the value the matching Like got when it was recorded. Only a later new like changes it. So a Like and the un-like that ends it share a generation, and the next Like gets a different one. The docstring's `:returns:` is updated.\n\n**3. Client: `_handle_user_action`.**\n- With a profile: `publish` becomes `changed`. A replayed like, an un-like of an unliked video, a dislike of an unliked video and every `undo_dislike` publish nothing. They fall through to the existing 200 `{\"ok\": True, \"updatedAt\": ...}` response.\n- Without a profile: `publish` stays `action in (\"like\", \"undo_like\")` with generation 0. Dislike actions already require a profile, so anonymous input can only be a like or an undo_like.\n- `event_type` keeps the existing rule (`Like` for `like`, otherwise `UndoLike`), so a dislike that removed a like produces an `UndoLike`. Its generation is the one the profile's `undo_like` would have read, so the id is identical.\n- The id is `client-` plus the SHA-256 hex digest of `(actor, canonical_uuid, canonical_host, event_type, generation)`. The fields are serialised with `json.dumps` of a list, which is already imported. JSON quoting and escaping make field boundaries unambiguous whatever the field values contain.\n- The id is 71 characters of hex and contains no raw input. `normalize_event_payload` only requires a non-empty string, and `event_id` is a TEXT primary key with no length limit, so it is accepted.\n- `hashlib` is added to the stdlib imports. `uuid4` stays imported because `run_id` near the bottom of `server.py` still uses it, so the requirement to drop the import only if unused leaves it in place.\n- The other payload fields, the 400/404/502 paths, `DislikeLimitReached`, `EngineApiError` and the bridge response are untouched.\n\n**4. `delete_profile` (`client/backend/lib/profiles.py`).** One more `DELETE FROM like_generations WHERE user_id = ?` inside the existing `with conn` transaction.\n\n**5. Engine: ranking cap (`engine/server/data/random_videos.py`).** A module-level `POPULAR_SIGNAL_CAP = 25.0`. The first ORDER BY term in `fetch_popular_videos`'s inner subquery becomes `popularity + MIN(COALESCE(signal_score, 0), ?)`, with the constant bound as a query parameter. The params list now holds, in order: the optional error threshold, the cap, the inner limit, the outer limit. Getting this order right is the one fiddly part. `COALESCE` sits inside `MIN`, so SQLite's two-argument scalar `MIN` never sees NULL. The outer `interaction_signal_score` column, the stored `signal_score` and the likes tiebreaker are unchanged. A signal of 1000 now counts as 25, which ranks below popularity 30.\n\n**How the acceptance criteria follow:**\n- Double like: the second post finds the row, `new` is false, nothing is published.\n- like \u2192 undo \u2192 like: the ids use generations g, g, g+1, so the two Likes differ, the counts net +1 \u22121 +1, and `signal_score` ends at 1.0.\n- Bridge retry: the same id hits the Engine's existing `ON CONFLICT DO NOTHING` and is reported as a duplicate.\n- Anonymous: generation 0 gives one id per video, so the second post is a duplicate.\n- The un-like, dislike, ranking and `delete_profile` criteria follow directly from sections 2 to 5.\n\n**Tests:** new Client cases publish under fresh profiles, so their actor identities are unique per run. The anonymous criterion (\"the second is a duplicate\") holds on every run even against the shared `whitelist.db`. The ranking case uses an isolated in-memory Engine database, as `test_random_videos.py` already does.\n\n### Alternatives considered\n\n- **How to detect a new like.** Rejected: a SELECT for an existing row before the upsert. It adds a query and leaves a window where two concurrent requests both see \"absent\" and both publish. The conditional insert's rowcount is atomic at the statement level, so only one request ever sees \"new\".\n- **Where the un-like's generation comes from.** Rejected: widening `remove_like` to return the generation. That changes a shared helper's signature for one caller. Rejected: inline SQL in `_store_reaction`, because `server.py` has no SQL anywhere. The small reader in `users_store.py` costs one extra name on an existing import line.\n- **Hash input encoding.** Rejected: joining with a control-character separator such as `\\x1f` or `\\n`. It is only unambiguous if we can prove no field contains that character, and `video_uuid` and `instance_domain` come back from the Engine. JSON encoding needs no such proof.\n- **Keying the id on the `likes` row's rowid or timestamp.** Rejected: the row is deleted on un-like, so rowids and timestamps are not stable, and timestamps can repeat.\n- **Cap by interpolation versus a bound parameter.** Both are allowed. The parameter was chosen so the value never sits inside the SQL text. The cost is reordering the params list.\n- **Capping at ingest.** Out of scope and rejected by ADR-0001: the stored score must stay raw so the cap can change without a migration.\n\n### Risks and gotchas\n\n- **Likes that predate `like_generations`** have no row, so an un-like reads generation 0. The resulting `UndoLike` still has a unique, profile-scoped id. It cannot collide with the anonymous generation-0 ids because the actor differs. The next new like starts that video at generation 1, so the sequence stays correct.\n- **Imported likes** advance the generation without publishing. A later un-like then publishes an `UndoLike` for a Like id the Engine never saw. The count effect (\u22121) is what today's code already does, and import publishing is out of scope.\n- **The `max_likes` trim gap** remains as accepted: the Engine keeps its +1, a later un-like publishes nothing, and a re-like gets a new generation.\n- **Merge risk with plan 14:** besides the named functions, `server.py` gets two import-line edits (`hashlib`, and the new reader on the `users_store` import). If they conflict, resolve by union. `record_like`'s return value is additive, so plan 14's import caller, which ignores it, is unaffected.\n- **Test runs publish into the shared `whitelist.db`.** Any anonymous Like or UndoLike a test sends for a real video permanently takes that video's single anonymous Like and UndoLike ids. New tests must therefore publish as fresh profiles or use an isolated Engine DB. The existing frontend-reactions tests assert browser-store state, not Engine counts, so they are unaffected.\n- **Concurrency on the one shared SQLite connection** is unchanged. The existing rat-tail about unserialised read, compute and write for dislikes still applies.\n\n### Tradeoffs the operator accepts\n\n- **Anonymous likes collapse to at most +1 per video, and un-likes to at most \u22121.** Once an anonymous Like and UndoLike have both been stored for a video, anonymous visitors contribute nothing further to it, ever. This is ADR-0001 \u00a73 as accepted.\n- **The cap of 25.0 is a deliberate simplification.** One named constant bounds the signal's effect on ordering. It does nothing to stop the likes tiebreaker, which is uncapped and out of scope, from being inflated among videos that tie on the first term. To raise or lower the cap, edit the constant. If it ever needs to be configurable, the upgrade path is an env var read once at startup.\n- **Events already stored with random ids stay as they are.** No backfill.",
  "conflicts": "none",
  "impacts": "<impact path=\"client/backend/lib/users_store.py\" element=\"ensure_user_schema() (lines 10-63): new like_generations table\">\n**What changes.** The existing `executescript` gets one more `CREATE TABLE IF NOT EXISTS like_generations (user_id TEXT NOT NULL, video_id TEXT NOT NULL, instance_domain TEXT NOT NULL, generation INTEGER NOT NULL, PRIMARY KEY (user_id, video_id, instance_domain))`. It goes after `dislike_profiles` (lines 53-58) and before the `local-user` cleanup comment and DELETEs (lines 59-61), as the plan says. The docstring at line 11 (\"Create the users, likes, profile, block and dislike tables if missing.\") should also name the like generations table. No `local-user` DELETE is needed for the new table, because no such rows can exist in a table that is new.\n\n**What depends on it.**\n- `client/backend/server.py:1179` (`main`) runs it once at startup on `users.db`, so the live DB gets the table on the first restart. No migration step is needed.\n- `tests/active/conftest.py:73` (`client_backend`) and `:160` (`_engine_client`) call it.\n- `tests/active/test_server.py:266` (`_client_backend`) calls it.\n- `delete_me/test_12_*.py` and `delete_me/test_probe_phase3_http.py` call it. These are scratch copies and are not collected.\n- Every later `record_like` and `delete_profile` now needs the table.\n\n**Regression risk: low.** `CREATE TABLE IF NOT EXISTS` is idempotent. A DB on which this function never ran would now fail in `record_like` and `delete_profile` with \"no such table: like_generations\". I found no such path: every connection above runs the schema first, and the `_seed_like` helpers write to fixture DBs that already have it. Do not confuse this with `engine/server/data/users.py:11`, the Engine's separate `ensure_user_schema`, which is untouched.\n</impact>\n<impact path=\"client/backend/lib/users_store.py\" element=\"record_like() (lines 79-117): new-like detection, generation upsert, returns (new, generation)\">\n**What changes.**\n- The one `INSERT ... ON CONFLICT ... DO UPDATE` (lines 94-102) becomes `INSERT ... ON CONFLICT(user_id, video_id, instance_domain) DO NOTHING`. The code reads `cursor.rowcount`: 1 means a new like, 0 means the row already existed.\n- On 0, a plain `UPDATE likes SET video_uuid = ?, updated_at = ? WHERE user_id = ? AND video_id = ? AND instance_domain = ?` keeps today's recency refresh.\n- On 1, it runs `INSERT INTO like_generations ... VALUES (?, ?, ?, 1) ON CONFLICT(...) DO UPDATE SET generation = like_generations.generation + 1`.\n- It then reads the generation back.\n- The return annotation changes from `-> None` to `-> tuple[bool, int]`, and the docstring (line 86) gains `:returns:`.\n- The `max_likes` trim (103-116) and `conn.commit()` (117) are unchanged.\n- `connect_db` (`server.py:144`) uses the default isolation level, so the conflicting INSERT reports rowcount 0. The UPSERT syntax is already in use in this file.\n\n**What depends on it.** Five callers:\n- `server.py:846`, plain like in `_store_reaction`. It now consumes the result.\n- `server.py:869`, a like replacing a dislike. It now consumes the result.\n- `server.py:898`, `_handle_likes_import`. It ignores the result. Plan 14 also edits this handler.\n- `tests/active/test_profiles.py:44` (`_seed_like`), which ignores it.\n- `tests/active/test_frontend_profile.py:109` (`_seed_like`), which ignores it.\n\n**Transaction behaviour.**\n- `get_or_create_user` (line 76) commits by itself when it inserts a user.\n- The final commit inside `record_like` commits the caller's enclosing `with conn:` early. That ordering already exists and is documented in `docs/project/plans/archive/03-like-dislike.md:430`: `delete_dislike` runs first, so this commit covers both.\n- The generation upsert and read-back happen before that commit, so they are atomic with the likes INSERT.\n\n**Regression risk: medium.**\n1. The plan says \"the trim never drops the row just inserted\". That holds for a single like. It does not strictly hold in a bulk import: up to `MAX_CLIENT_LIKES = 200` (`server.py:52`) records can go in against `MAX_LIKES = 100` (`server.py:51`), in one `with conn:`, and many share one `now_ms()`. A tie at the boundary can therefore trim a row whose generation was just advanced. That is harmless, since the next new like takes generation+1, but the plan's claim holds only for single likes.\n2. `clear_likes` (the reset) leaves `like_generations` in place, so a re-like after a reset is new and publishes a fresh `Like`. See the reset entry: this is a repeatable +1 loop.\n3. The read-back must work whether or not the connection has a `row_factory`: the test helpers set `sqlite3.Row`, raw connections do not. Use `row[0]`.\n4. \"New\" must come from the INSERT's own rowcount, not from a SELECT beforehand, or two concurrent likes could both publish.\n</impact>\n<impact path=\"client/backend/lib/users_store.py\" element=\"new generation reader function (next to remove_like, line 159)\">\n**What changes.** A new function returns the stored `generation` for `(user_id, video_id, instance_domain)`, or 0 when there is no row. To match the file's style:\n- positional `conn, user_id, video_id, instance_domain`, so it can be called as `reader(conn, profile_id, *key)` the way `remove_like` is;\n- a docstring with `:returns:`;\n- no commit (\"inside the caller's transaction\", like `remove_like`).\n\n**What depends on it.** `_store_reaction`'s undo_like and dislike branches, through a new name on the `lib.users_store` import (`server.py:37-39`). New tests may call it directly.\n\n**Regression risk: low.** It should be read before `remove_like`. The value is the same either way, because `remove_like` never touches `like_generations`, but reading first keeps the intent clear. Returning 0 for a missing row gives the same generation anonymous actors use. That is safe only because the hashed actor differs: the profile id versus `\"anonymous\"`.\n</impact>\n<impact path=\"client/backend/lib/users_store.py\" element=\"remove_like() (159-168), clear_likes() (153-156), video_reaction(), fetch_recent_likes(), load_liked_keys(), get_or_create_user(): unchanged\">\n**What changes.** Nothing. The plan keeps `remove_like`'s signature. `remove_like` still does not commit, and its callers hold `with conn:`.\n\n**What depends on it.**\n- `remove_like` is called at `server.py:848` (undo_like) and `:861` (dislike).\n- `clear_likes` is called at `server.py:988` (reset). It deletes only `likes` and so deliberately leaves `like_generations`. That is required for \"the generation survives\", but it opens the reset loop described below.\n\n**Regression risk: none in code.** Listed so the reset interaction is on record.\n</impact>\n<impact path=\"client/backend/server.py\" element=\"stdlib import block (lines 5-22): add hashlib; keep uuid4\">\n**What changes.** `import hashlib` goes in alphabetical order between `argparse` (line 5) and `ipaddress` (line 6). Plan 12 has since added `ipaddress` at line 6, so the block reads argparse, ipaddress, json, ...\n\n`from uuid import uuid4` (line 21) must stay: `run_id = str(uuid4())` at line 1155 still uses it. The requirement is \"drop uuid4 if unused\", and it is still used.\n\n**What depends on it.** The event-id derivation in `_handle_user_action`.\n\n**Regression risk: nil.** This is a merge point with plan 14 if plan 14 touches the import block; resolve by union.\n</impact>\n<impact path=\"client/backend/server.py\" element=\"lib.users_store import (lines 37-39): add the generation reader\">\n**What changes.** The reader's name is added to the parenthesised import, which is alphabetised today: `clear_likes, ensure_user_schema, fetch_recent_likes, get_or_create_user, load_liked_keys, record_like, remove_like, video_reaction`.\n\n**What depends on it.** `tests/active/conftest.py:39` (`import server as client_server`) and `test_server.py:47`. A misspelt name raises ImportError, which breaks all of `tests/active`.\n\n**Regression risk: low.** A mistake fails loudly at import. This is a merge point with plan 14.\n</impact>\n<impact path=\"client/backend/server.py\" element=\"ClientBackendHandler._store_reaction() (lines 831-870): returns (changed, generation)\">\n**What changes.** The return type changes from `bool` to a pair, and `:returns:` (line 837, \"Whether a dislike removed a like.\") is rewritten. Branch by branch:\n- **Plain like** (line 846): the value of `record_like` must be captured inside the `with conn:` (lines 844-848) and returned. Today the function returns `False` at line 849, after the `with` block.\n- **undo_like** (line 848): read the generation, then `removed = remove_like(...)`, both inside the same `with`. Return `(removed, generation)`.\n- **dislike** (lines 855-863): the `DislikeLimitReached` check (856-857) and `compute_dislike_centroids` (859) stay before any write. Inside the `with` at line 860, read the generation, then `remove_like` and `write_dislike`. Return `(like_removed, generation)`.\n- **The shared tail** (lines 864-870) serves both `undo_dislike` and a like replacing a dislike. It must return `record_like`'s pair when `action == \"like\"` and `(False, 0)` for `undo_dislike`. Today it returns `False` for both, so this branch is the easy one to get wrong.\n\n**Exclusivity.** The plan says a like replacing a dislike is always new. That holds only because every path removes the other reaction; nothing in `lib/dislikes.py` enforces it at the DB level. If a `likes` row did co-exist, this branch would return `new=False` and publish nothing, which is still correct. `dislikes.py`'s `write_dislike` and `delete_dislike` do not commit, so the transaction is unchanged.\n\n**What depends on it.** Only `_handle_user_action` (line 787). The rat-tail comment at lines 853-854 stays true.\n\n**Regression risk: medium.** This is where \"a Like and its un-like share a generation\" either holds or fails. On the one shared `check_same_thread=False` connection of a `ThreadingHTTPServer`, two concurrent undo_likes can both read g, but only one `remove_like` sees rowcount 1, so only one publishes. A concurrent like and undo is the same class of race as the existing rat-tail.\n</impact>\n<impact path=\"client/backend/server.py\" element=\"ClientBackendHandler._handle_user_action() (lines 731-829): publish gating and derived event_id\">\n**What changes.**\n- Line 784, `publish = action in (\"like\", \"undo_like\")`, stays as the anonymous default, with generation 0.\n- In the profile branch (785-795), `like_removed = self._store_reaction(...)` becomes `changed, generation = ...`, and line 795 `publish = publish or like_removed` becomes `publish = changed`. The comment at line 794 needs rewording.\n- Line 802, `\"event_id\": f\"client-{uuid4()}\"`, becomes `\"client-\" + hashlib.sha256(json.dumps([actor, canonical_uuid, canonical_host, event_type, generation]).encode(\"utf-8\")).hexdigest()`.\n- `actor` is the same expression as line 804, `profile_id or \"anonymous\"`, and should be computed once and used in both places.\n- `event_type` (line 800) must be computed before the id.\n- The docstring \"Handle handle user action.\" (line 732) could state the publish rule.\n- The comment at lines 753-754 stays true.\n\n**Behaviour changes callers can see.**\n- With a key, a repeat `like`, an `undo_like` of an unliked video, a dislike of an unliked video, and every `undo_dislike` answer 200 `{ok, updatedAt}` and publish nothing.\n- On `unpublished_client` (activitypub mode), a repeat keyed like or undo_like used to answer 502 and now answers 200.\n- Keyless likes and un-likes still always publish, so they still answer 502 on an unpublished Client. `test_frontend_reactions.py:249-258` relies on that.\n\n**Hashing details.**\n- The `json.dumps` defaults (`ensure_ascii=True`, `\", \"` separators) are part of the id and must never change.\n- `generation` must be an `int`, never a `bool` or `str`.\n- `canonical_uuid` can be `\"\"` (line 774). The Engine then rejects the event with \"Missing object.video_uuid\" (`interaction_events.py:208-209`), which is unchanged behaviour.\n- The id is 71 characters and is accepted by `normalize_event_payload` (lines 194-198: a non-empty string after `_clean_text`, no length cap) and by `event_id TEXT PRIMARY KEY` (line 24).\n- `raw_payload: body` (line 812) is still sent raw. That is out of scope.\n\n**What depends on it.**\n- `sendUserAction` in `client/frontend/src/data/user-actions.ts:33` checks only `response.ok`.\n- The Engine answers a duplicate with 200 `ok: true` (`internal_events.py:84-93`), and `_publish_to_engine_bridge` maps that to `ok=True`. So a replayed anonymous like answers 200 `bridge_ok: true`.\n- The smokes: see their entries.\n\n**Regression risk: medium-high.** Any of these silently reopens the finding or breaks the contract:\n- publishing when `changed` is False;\n- hashing `None` as the actor instead of `\"anonymous\"`;\n- using a different generation for an undo than for its Like;\n- letting the serialisation drift.\n\nNo existing test exposes event ids.\n</impact>\n<impact path=\"client/backend/server.py\" element=\"_handle_user_profile_reset() (lines 976-993) with clear_likes(): repeatable +1 loop (Step 4 finding, not in the plan's Risks)\">\n**What changes.** Nothing in the plan's code. But its interaction with the new gating matters. Reset deletes every `likes` row, keeps `like_generations`, and publishes nothing. One profile can therefore repeat like \u2192 `POST /api/user-profile/reset` \u2192 like. Each like is \"new\", takes generation+1, gets a fresh id, and adds +1 to `likes_count` and `signal_score`. The only limit is the general per-route `RateLimiter` (lines 352-357).\n\n**What depends on it.** `test_profiles.py`'s `PROFILE_ROUTES` (line 31) uses the route, and the frontend reset flow.\n\n**Regression risk: not a regression.** Today every like adds +1. But the plan's \"Risks\" does not record this as an unbounded one-profile loop. The 25.0 cap limits the effect on ordering, but not the shown likes count or the likes tiebreaker (`random_videos.py:45,248`).\n\n**Uncertain: operator decision.** Accept it in \"Tradeoffs\", or change the gating (for example the \"open\" flag on `like_generations` proposed in the prior Step 4 record). I list it so it is not missed.\n</impact>\n<impact path=\"client/backend/server.py\" element=\"_handle_likes_import() (lines 872-900): record_like caller, and the repeatable \u22121 loop\">\n**What changes.** Nothing in code. `record_like` at line 898 now returns a pair, which is ignored, and `imported += 1` is unchanged. The whole loop runs inside one `with conn:` while `record_like` commits on each iteration, as today.\n\n**What depends on it.**\n- Plan 14 edits this handler.\n- `tests/active/test_profiles.py:245-253` and `tests/active/test_frontend_reactions.py:350-374` exercise it, on `unpublished_client`.\n\n**Risk: low for code, but a behaviour to record.**\n- Each imported new like advances the generation without publishing. The plan accepts this.\n- It is also repeatable. Import video X \u2192 `undo_like` X finds the row, publishes an `UndoLike` with a fresh generation, and takes \u22121 off X \u2192 import again \u2192 undo again. Each pass removes another 1 from any video other people liked, down to the Engine's `MAX(0, \u2026)` floor (`interaction_events.py:124-127`).\n- This gets around the plan's own rule that \"an un-like of an unliked video publishes nothing\".\n- Today's code allows the same, so it is not a regression, but the plan records only the single-shot case.\n- See also the tie-trim note in the `record_like` entry.\n</impact>\n<impact path=\"client/backend/server.py\" element=\"_publish_to_engine_bridge() / _publish_event() (lines 1032-1064): unchanged\">\n**What changes.** Nothing.\n\n**What depends on it.** It limits how tests can observe duplicates. It returns `{\"ok\", \"response\"}`, and the handler exposes only `ok`, `bridge_ok` and `bridge_error`. So \"the second is a duplicate\" cannot be read from the Client response. Tests must either read the Engine's `interaction_raw_events`/`interaction_signals`, post to `/internal/events/ingest` directly, or capture payloads with a stub Engine.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"client/backend/lib/profiles.py\" element=\"delete_profile() (lines 69-80)\">\n**What changes.** One more `conn.execute(\"DELETE FROM like_generations WHERE user_id = ?\", (profile_id,))` inside the `with conn:`. It belongs next to the `likes` delete at line 78, since both key on `user_id`. The docstring (\"every row keyed to it\") stays true.\n\n**What depends on it.**\n- `server.py:340-345` (`POST /api/profile/delete`).\n- `tests/active/test_profiles.py:197-217`.\n- The profile-delete steps in `tests/run-installers-smoke.sh:449,683` and `tests/run-arch-split-smoke.sh:617`.\n\n**Regression risk: low.** It only fails on a DB where the table was never created, and no such path exists. Because the delete runs in one transaction, a failure would roll back the whole profile delete.\n</impact>\n<impact path=\"engine/server/data/random_videos.py\" element=\"new module-level POPULAR_SIGNAL_CAP = 25.0\">\n**What changes.** A named constant goes after the imports (after line 9), with a `#` comment above it. The module has no constants today; the house style can be seen in `interaction_events.py:13-14`.\n\n**What depends on it.** `fetch_popular_videos` and the new ranking test, which may import it.\n\n**Regression risk: nil.**\n</impact>\n<impact path=\"engine/server/data/random_videos.py\" element=\"fetch_popular_videos() (lines 195-303): capped ORDER BY term and params order\">\n**What changes.**\n- Line 247, `(v.popularity + COALESCE(sig.signal_score, 0)) DESC`, becomes `(v.popularity + MIN(COALESCE(sig.signal_score, 0), ?)) DESC`.\n- Line 200 becomes `[POPULAR_SIGNAL_CAP, limit, limit]`, and line 203 becomes `[error_threshold, POPULAR_SIGNAL_CAP, limit, limit]`. That matches the placeholder order: the WHERE `?` from `{error_clause}` (245, inner subquery), then the cap (247), then the inner `LIMIT ?` (252), then the outer `LIMIT ?` (262).\n- Line 234 (`interaction_signal_score`, raw) and the tiebreaker at line 248 are unchanged.\n- The docstring \"by likes/views\" (198) could mention the capped signal.\n\n**What depends on it.**\n- `engine/server/api/server.py:90,398` wires it in.\n- `engine/server/api/recommendations/builder.py:109-113` wraps it with `error_threshold=settings.video_error_threshold`. That value is `VIDEO_ERROR_THRESHOLD = 3` (`server_config.py:387`), so production always takes the 4-parameter branch.\n- `candidates/popular_videos.py:52` consumes the pool.\n- `tests/active/test_random_videos.py:85` calls it without a threshold, which is the 3-parameter branch.\n\n**Regression risk: medium.**\n- A wrong params order raises nothing, because every placeholder takes a number. It silently turns the cap into a LIMIT or a threshold.\n- The tested branch is not the production branch, so the new test must cover both.\n- Two-argument `MIN` is SQLite's scalar function, which returns NULL if any argument is NULL. `COALESCE` inside it prevents that.\n- On the live dataset, videos with a signal above 25 drop in the popular pool. That is intended.\n</impact>\n<impact path=\"engine/server/data/random_videos.py\" element=\"fetch_random_rows() (line 45 likes), fetch_recent_videos(), cache readers: unchanged\">\n**What changes.** Nothing. `(v.likes + COALESCE(sig.likes_count, 0)) AS likes` is the displayed likes figure, not the ranking signal.\n\n**Regression risk: none.** Listed so the cap is not applied to the wrong query.\n</impact>\n<impact path=\"engine/server/data/interaction_events.py\" element=\"ingest_interaction_event() / normalize_event_payload() / _event_deltas() / prune_interaction_raw_events(): unchanged, relied upon\">\n**What changes.** Nothing; the requirements forbid changes here.\n\n**What depends on it.**\n- The collapsing relies on `ON CONFLICT(event_id) DO NOTHING` (line 85) and on the duplicate result (lines 100-109).\n- The deltas are Like +1.0, UndoLike \u22121.0 (lines 255, 262), floored by `MAX(0, \u2026)` (124-127).\n- The prune (150-189) strips payload, actor and source but keeps the row, and with it the `event_id`, so derived ids keep collapsing replays after retention.\n\n**Regression risk: none from this build.**\n</impact>\n<impact path=\"engine/server/api/handlers/internal_events.py\" element=\"handle_internal_events_ingest() duplicate accounting (lines 56-94): unchanged\">\n**What changes.** Nothing.\n\n**What depends on it.** The \"bridge retry is reported as duplicate\" and \"second anonymous like is a duplicate\" criteria. They can be observed through `results[i].duplicate` and `duplicates`. The route is served only in `ENGINE_INGEST_MODE=bridge`, which the conftest `engine` fixture sets (line 105).\n\n**Regression risk: none.**\n</impact>\n<impact path=\"engine/server/data/users.py\" element=\"Engine-side ensure_user_schema() (line 11) / record_like() (line 47): NOT touched\">\n**What changes.** Nothing. It has the same function names as the Client module, so a `def record_like` grep finds both. The one to edit is `client/backend/lib/users_store.py:79`.\n\n**Regression risk: none, provided the right file is edited.**\n</impact>\n<impact path=\"client/backend/lib/engine_api_client.py\" element=\"resolve_video_seed() (lines 66-89): unchanged; shape needed by a stub Engine\">\n**What changes.** Nothing.\n\n**What depends on it.** Any new isolated test that uses a stub Engine must answer `POST /internal/videos/resolve` with 200 `{\"video\": {\"video_id\", \"instance_domain\", \"video_uuid\", \"video_url\"}}`. A 404 becomes \"not found\"; any other status or a non-dict raises `EngineApiError`. The stub must also accept `POST /internal/events/ingest` and record the `event_id`. I verified this shape in the source; the prior record had it as unverified.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"client/frontend/src/data/user-actions.ts\" element=\"sendUserAction() (lines 18-38): unchanged\">\n**What changes.** Nothing. It treats any 2xx as success, so the new 200 `{ok, updatedAt}` answer to a keyed no-change action is accepted.\n\n**Side effect.** A keyed repeat like on a Client that cannot publish no longer throws \"Failed to send action\". That is correct.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"tests/active/test_random_videos.py\" element=\"existing popular tests (108-122), helpers _two_video_db/_set_views/_event (34-77); home for the ranking-cap test\">\n**What changes.** The existing tests stay green: they use signal 1.0, which is under the cap, and assert the raw `interaction_signal_score == 1.0` (line 119). The new criterion fits here:\n- Use `_two_video_db`, then `UPDATE videos SET popularity` to 0 and 30.\n- Set the signal to 1000 with a direct `INSERT INTO interaction_signals`, rather than 1000 ingests.\n- Run with and without `error_threshold`. `_set_views` sets `error_count = 0`, so a threshold of 1 keeps both rows.\n\n**Correction to the plan.** The plan says the file uses \"an isolated in-memory Engine database\". It actually uses a file DB under `tmp_path`, built by `ATTACH` of `whitelist.db` read-only (lines 36-52). It is still isolated from the live DB's writes, but it needs `whitelist.db` to exist.\n\n**What depends on it.** `.un/skills/devsecops/config.json:87-88` maps it to `random_videos.py`.\n\n**Regression risk: low.**\n</impact>\n<impact path=\"tests/active/test_profiles.py\" element=\"_seed_like (41-46), _rows_for (59-67), test_deleting_a_profile_removes_its_rows_and_keeps_anothers (197-217)\">\n**What changes.**\n- `_seed_like` now also writes a `like_generations` row and ignores the return value.\n- This is the natural home for the \"`delete_profile` removes the profile's `like_generations` rows\" criterion: add a `like_generations` count to `_rows_for`.\n- The four equality asserts (lines 205, 209, 215, 216) must then change together to include `\"like_generations\": 1` (or 0).\n- The comment at line 201 (\"all three tables\") becomes \"four\".\n\n**What depends on it.** `config.json:18-21` maps it to `server.py`, `profiles.py` and `users_store.py`.\n\n**Regression risk: low.** A partial update of those dicts fails the test.\n</impact>\n<impact path=\"tests/active/test_profiles.py\" element=\"test_a_keyed_upnext_request_is_seeded_... (264-282) and test_a_keyed_search_marks_... (291-313)\">\n**What changes.** Nothing.\n- The first like by a fresh profile is new, so line 300 still expects 502 on `unpublished_client`.\n- A dislike of an unliked video still answers 200.\n- Line 277 does not assert status.\n\n**Regression risk: none.** Line 300 guards against a like wrongly treated as not new, which would answer 200.\n</impact>\n<impact path=\"tests/active/test_frontend_profile.py\" element=\"_seed_like (106-111)\">\n**What changes.** Nothing required. It calls `record_like` on a fixture DB that already has the table, and ignores the result.\n\n**Regression risk: low.**\n</impact>\n<impact path=\"tests/active/test_frontend_reactions.py\" element=\"keyless tests (202-258), keyed sequence (264-308), keyed-vs-keyless store test (311-340), card test (396-409)\">\n**What changes.** Nothing in the file. Behaviour against the shared live `whitelist.db` does change.\n\n**Keyless tests.** They publish anonymous Like/UndoLike on the first rows of `_videos(dataset, n)`, which are the same every run.\n- After this build each such video has exactly one anonymous Like id and one anonymous UndoLike id.\n- The first run nets +1\u22121. Every later run gets duplicates, which still answer 200 `ok`, and the assertions check only `\"ok\"` and browser-store state.\n- The finally-block undos at lines 213-214 and 239-240 become duplicates, so they have no effect after the first run.\n\n**Keyed sequence (264-303).** Each step is a real change, or answers 200 without publishing:\n- like: g1, published;\n- dislike: removes the like, publishes UndoLike at g1;\n- undo_dislike: 200, nothing published;\n- out-of-band dislike on the now unliked video: 200;\n- like replacing that dislike: g2, published;\n- undo_like: UndoLike at g2.\n\nSo `all(\"ok\" in a ...)` (line 303) holds.\n\n**Card test (406).** It still expects a 502 for a fresh profile's first like on `unpublished_client`.\n\n**Regression risk: low for the assertions, medium for shared data.**\n- A test asserting that \"the first anonymous like counts +1\" would fail on every run after the first.\n- A run that dies between an anonymous Like and its UndoLike leaves +1 on that video for good, because every later anonymous Like is a duplicate. This is accepted under ADR-0001 \u00a73.\n</impact>\n<impact path=\"tests/active/test_dislikes.py\" element=\"test_a_video_s_reaction_follows_... (68-87), _profile_disliking (118-123)\">\n**What changes.** Nothing.\n- The dislike of a liked video still publishes, and line 77 accepts `in (200, 502)`.\n- `undo_dislike` answers 200 (line 82).\n- A dislike of an unliked video answers 200 (line 84, and `_profile_disliking` at line 122).\n- Lines 74, 79 and 86 do not assert status.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"tests/active/test_server.py\" element=\"keyed likes loop (86-102) and _client_backend / EngineStub harness (262-326)\">\n**What changes.** Nothing.\n- Each like in the loop is on a distinct row, the set removes duplicates, and status is not asserted.\n- The dislikes answer 200 (line 102).\n- The `_client_backend(tmp_path, engine_base, rate_limiter)` helper plus the `EngineStub` pattern (307-320) is the ready-made isolated harness for the new Client acceptance tests. Extend the stub with `do_POST` for resolve and ingest.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"tests/active (new test file(s) for this build)\" element=\"new Client acceptance tests: publish-on-change, derived ids, dislike UndoLike id, anonymous duplicate, delete_profile\">\n**What changes.** New tests. There are two ways to observe events:\n- (a) `engine_client`, reading the live `interaction_raw_events` by a fresh profile id through the `dataset` connection;\n- (b) the stub Engine from `test_server.py`, which records posted `event_id`s. This avoids the shared DB and the Engine rate limit.\n\n**Constraints.**\n- Profile tests must mint fresh profiles.\n- An anonymous test may assert only \"same id\" or \"second is a duplicate\", never \"first counts\".\n- Tests that publish real Likes under (a) must withdraw them in a `finally`, as the existing tests do.\n\n**What depends on it.**\n- `validate_tests.py` collects `tests/active/test_*.py` (and `tests/tmp`).\n- Engine-backed files run in their own invocation.\n- New files are unmapped in `.un/skills/devsecops/config.json` until harvest.\n\n**Regression risk: medium for suite stability** under (a); low under (b).\n</impact>\n<impact path=\"tests/run-arch-split-smoke.sh\" element=\"client_user_action like + validate_user_action_response (330-346, 584-602), profile delete (617)\">\n**What changes.** Nothing. The like by the freshly minted profile is new, so it publishes and `ok`, `bridge_ok` and an empty `bridge_error` hold.\n\nIf minting fails, the like is anonymous. After the first run it is then a duplicate, which still returns `bridge_ok: true`.\n\n**Regression risk: low.**\n</impact>\n<impact path=\"tests/run-installers-smoke.sh\" element=\"like flow (649-686), verify_engine_event_recorded (~459-496), cleanup_engine_test_events (~498-585), delete_client_test_profile (~444-457)\">\n**What changes.** Nothing.\n- The fresh profile's first like is new and publishes.\n- The raw row exists under `actor_id = profile_id`.\n- The cleanup deletes raw rows by actor and recomputes, which frees that derived id. That is harmless, because the profile is deleted and cannot replay.\n- The profile delete now also removes `like_generations`.\n\n**Regression risk: low.**\n</impact>\n<impact path=\"engine/server/db/jobs/tests/test-interaction-events.py\" element=\"ingest contract script\">\n**What changes.** Nothing. The acceptance criteria require it to keep passing. It is not collected by `validate_tests.py`, so it must be run explicitly. It does not reference Client event ids or `fetch_popular_videos` (grep).\n\n**Regression risk: none.**\n</impact>\n<impact path=\"engine/server/db/jobs/tests/test-security-bundle.py\" element=\"security bundle checks\">\n**What changes.** Nothing. A grep found no reference to popular ordering, `signal_score`, Client ids or user-action. It must be run explicitly.\n\n**Regression risk: none expected.**\n</impact>\n<impact path=\".un/skills/devsecops/config.json\" element=\"test_groups (test_profiles 18-21, groups at 37-40/45-46/56-85 naming server.py/users_store.py/profiles.py, test_random_videos 87-88)\">\n**What changes.** Nothing in this worktree. The existing mappings already re-run the affected groups when any of the four source files changes. A new test file needs an entry at harvest.\n\n**Regression risk: low.**\n</impact>\n<impact path=\"tests/last_test_validation.json\" element=\"tracked suite record\">\n**What changes.** The post-build run rewrites it. It conflicts on merge: take main's copy and re-run `validate_tests.py --compare`.\n\n**Regression risk: none functionally.**\n</impact>\n<impact path=\"tests/last_test_output.txt\" element=\"tracked captured output\">\n**What changes.** Rewritten by the post-build run. Resolve its merge conflict the same way as `last_test_validation.json`.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"delete_me/server.py.bak*\" element=\"stale copies of server.py matched by grep\">\n**What changes.** Nothing. They are backups under `delete_me/` that match every symbol grep here (`record_like`, `_store_reaction`, `uuid4`). They must not be edited in place of `client/backend/server.py`.\n\n**Regression risk: none.**\n</impact>",
  "docs_checklist": "- [x] `client/README.md` - updated: `client/README.md`: `POST /api/user-action` now says when each action publishes and how event ids are built. The likes import and profile delete entries now cover like generations.\n- [x] `DEPLOYMENT.md` - updated: DEPLOYMENT.md: added the 25.0 popular signal cap (section 1) and the publish-on-change rule, the `like_generations` table and derived event ids (section 5).\n- [x] `engine/server/api/recommendations/docs/OVERVIEW.md` - updated: OVERVIEW.md: the popular pool's order now reads `popularity` plus the interaction signal capped at `POPULAR_SIGNAL_CAP` (25.0), not \"top by likes/views\".\n- [x] `engine/server/api/recommendations/docs/PIPELINE_DIAGRAM.md` - updated: Changed the popular-layer node label (line 29) from `top likes/views` to `popularity + capped signal`.\n- [x] `engine/server/api/recommendations/docs/LAYER_PARAMS.md` - updated: Fixed the popular layer's **Source:** line (line 137). It now describes the actual pool order: `popularity` plus the capped interaction signal, then likes, then views.\n- [x] `CONTEXT.md` - updated: Added the glossary term **Published like** to `CONTEXT.md`, which defines what counts as a real like/un-like change.\n- [x] `docs/project/adr/0001-derived-interaction-event-ids.md` - updated: Added the like-generation scheme to ADR-0001's Consequences and said what \"real state change\" in decision 1 means. The decisions themselves are unchanged.\n- [x] `docs/project/issues/01-deterministic-event-ids.md` - updated: Issue 01 is marked `bug, complete` with all 8 acceptance criteria ticked, and a copy is in `docs/project/issues/archive/`. The original file still needs deleting, because I can't delete files.\n- [x] `docs/project/plans/13-deterministic-event-ids.md` - updated: Plan 13 is now marked delivered and points to `16-13-deterministic-event-ids.md`. Its risks describe the code as built, and a new Delivery section records what the build settled. The file has not been moved to `archive/` yet.\n- [x] `docs/project/roadmap.md` - updated: Roadmap: security issue `01` is now listed as Delivered, removed from the open issues and the implementation order, and has its two remaining follow-ups added as optional M1 lines.\n- [x] `docs/project/adr/0005-raw-event-retention-keeps-ids.md` - out of scope: Its claims (strip, don't delete; kept ids catch replays including the fixed anonymous `Like` id) are exactly what the build relies on, and nothing in it is made false.\n- [x] `README.md` - out of scope: Lines 37-40 say only that interaction events update `interaction_signals`, which ranking uses. That is still true, and the file makes no claim about event ids or the popular ordering.",
  "docs": [
    {
      "path": "client/README.md",
      "note": "**Line 19 (`POST /api/user-action`).** It reads \"A like publishes its event and is kept server-side only when a profile key is sent\", which implies every like publishes. Reword it to say:\n- With a key, a `like` publishes a `Like` only when the profile did not already like the video.\n- An `undo_like` publishes an `UndoLike` only when a like was removed.\n- A request that changes nothing answers 200 and publishes nothing.\n- Without a key every like and un-like publishes, under one fixed id per video and event type, so repeats are duplicates.\n- Event ids are `client-` plus the SHA-256 of actor, video, event type and like generation.\n\n**Line 13 (`POST /api/profile/delete`).** Optionally add \"like generations\" to the list of what is removed."
    },
    {
      "path": "DEPLOYMENT.md",
      "note": "**Lines 259-261.** Optionally add that the Client backend publishes a profile's `Like`/`UndoLike` only on a real state change, with derived event ids, so replays collapse at the Engine's ingest.\n\n**Line 267.** Optionally add that the popular ordering adds at most 25.0 of a video's interaction signal (`POPULAR_SIGNAL_CAP` in `engine/server/data/random_videos.py`), and that `users.db` gains a `like_generations` table created at startup, with no migration step."
    },
    {
      "path": "engine/server/api/recommendations/docs/OVERVIEW.md",
      "note": "**Line 99** (\"popular pool: top by likes/views\"): state that the pool is ordered by `popularity` plus the interaction signal capped at `POPULAR_SIGNAL_CAP` (25.0), then by likes, views and recency."
    },
    {
      "path": "engine/server/api/recommendations/docs/PIPELINE_DIAGRAM.md",
      "note": "**Line 29** (`popular<br/>top likes/views`): optionally align it with the capped-signal ordering. This is cosmetic."
    },
    {
      "path": "CONTEXT.md",
      "note": "**Verify only.** **Interaction event** (line 6) already says ids are \"derived, never random\", and **Interaction signal** (line 7) already says the popular ordering adds at most a fixed cap. Both match the build.\n\nOptionally define **Like generation**: the per-profile, per-video counter that tells one like from the next, survives un-likes and resets, and is removed with the profile."
    },
    {
      "path": "docs/project/adr/0001-derived-interaction-event-ids.md",
      "note": "The decision is unchanged. Optionally add to Consequences:\n- the chosen like-instance scheme (the Client's `like_generations`, kept through un-like and reset, deleted with the profile);\n- that likes predating the table un-like at generation 0;\n- that imported likes advance the generation without publishing;\n- the reset and import loops, if the operator accepts them rather than closing them."
    },
    {
      "path": "docs/project/issues/01-deterministic-event-ids.md",
      "note": "At harvest on main: tick the acceptance criteria, set `Status:` to `bug, complete`, and move the file to `docs/project/issues/archive/` per `docs/project/triage-labels.md`."
    },
    {
      "path": "docs/project/plans/13-deterministic-event-ids.md",
      "note": "At harvest: mark it delivered, point it to `16-13-deterministic-event-ids.md`, and archive it. Also record:\n- The answer to its line 97: a profile-deletion path exists (`delete_profile`) and now removes `like_generations`.\n- `clear_likes` (reset) intentionally keeps generations."
    },
    {
      "path": "docs/project/roadmap.md",
      "note": "Optional out-of-scope follow-ups:\n- Close the reset (+1) and import\u2192undo (\u22121) loops and the `max_likes` trim gap, for example with an \"open\" flag on `like_generations`.\n- Decide whether the likes import should publish.\n- Bound the popular likes tiebreaker."
    }
  ],
  "reassessments": 2,
  "draft": "## Draft implementation: plan 13, derived event ids, publish on change, popular-signal cap\n\n**Operator decision taken at this step.** The inventory left two loops for the operator: reset \u2192 re-like (+1 each pass) and import \u2192 undo_like (\u22121 each pass). The operator chose to close both with a published flag. So this draft departs from the settled plan and inventory in the places listed under \"Deviations from the settled plan and inventory\" at the end. Everything else follows the plan as approved.\n\n### What has to be tested\n\n| # | Behaviour | Where |\n|---|---|---|\n| T1 | Two profile `like` posts publish one `Like`. `likes_count` +1 and `signal_score` +1.0 | new `tests/active/test_event_ids.py` (stub Engine) |\n| T2 | Profile like \u2192 undo_like \u2192 like publishes Like(g1), UndoLike(g1), Like(g2). The two Like ids differ and `signal_score` ends at 1.0 | same |\n| T3 | Re-sending a published payload is `duplicate: true` and changes no counts | same |\n| T4 | Two anonymous likes produce the same id, and the second is a duplicate | same |\n| T5 | undo_like on an unliked video answers 200 and publishes nothing | same |\n| T6 | A dislike that replaces a like publishes one UndoLike with the id the undo_like would have used. A dislike on an unliked video publishes nothing | same |\n| T7 | Reset loop closed: like \u2192 reset \u2192 like publishes one Like. A later undo_like publishes the UndoLike for that same Like, and `signal_score` ends at 0 | same |\n| T8 | Import loop closed: import X \u2192 undo_like X publishes nothing | same |\n| T9 | Popular ordering: signal 1000 with popularity 0 ranks below popularity 30 with no signal, on both parameter branches | `tests/active/test_random_videos.py` |\n| T10 | `delete_profile` removes the profile's `like_generations` rows and keeps another profile's | `tests/active/test_profiles.py` (existing delete test, extended) |\n| T11 | Existing suites stay green | `validate_tests.py` |\n\n### Module map\n\n| File | Change |\n|---|---|\n| `client/backend/lib/users_store.py` | table in `ensure_user_schema`; `record_like` gains `publish=False` and returns `(opened, generation)`; new `like_generation` (reader) and `close_like` (writer) |\n| `client/backend/lib/profiles.py` | `delete_profile` deletes `like_generations` |\n| `client/backend/server.py` | `import hashlib`; `close_like` added to the `users_store` import; `_store_reaction` returns `(publish, generation)`; `_handle_user_action` gates on it and derives the id |\n| `engine/server/data/random_videos.py` | `POPULAR_SIGNAL_CAP`; capped ORDER BY term; params reordered |\n| `tests/active/test_event_ids.py` | new: T1\u2013T8 |\n| `tests/active/test_random_videos.py` | new T9 test |\n| `tests/active/test_profiles.py` | `_seed_like` passes `publish=True`; `_rows_for` counts `like_generations`; the four delete asserts are updated |\n\n### The like-generation state machine\n\nThis is the core invariant. Each `(profile, video)` row in `like_generations` holds `generation` and `published`.\n\n| Event | Precondition | Effect | Publishes |\n|---|---|---|---|\n| keyed like (`record_like(publish=True)`) inserts a new `likes` row | no row | insert `(g=1, published=1)` | `Like` at g=1 |\n| same | `published=0` | `g+=1`, `published=1` | `Like` at the new g |\n| same | `published=1` (after a reset or trim, the Engine still holds this profile's Like) | nothing | nothing |\n| keyed like, `likes` row already exists | any | refresh `video_uuid` / `updated_at` only | nothing |\n| import (`record_like`, default `publish=False`) | any | `likes` row only; `like_generations` untouched | nothing |\n| undo_like, or a dislike (`close_like`) | `published=1` | `published=0`, g unchanged | `UndoLike` at g |\n| same | no row, or `published=0` | nothing | nothing |\n| reset (`clear_likes`) | any | untouched | nothing |\n| `delete_profile` | any | rows deleted | nothing |\n\n**Invariant.** g changes only on the 0\u21921 transition, so while `published=1` it is constant. Every Like(g) is matched by at most one UndoLike(g), and the next Like gets g+1. Per profile and video, the Engine sees each id at most once, so the profile's net contribution is always 0 or +1. Both loops are closed by construction: reset leaves `published=1`, so the re-like publishes nothing, and import never opens a like, so its undo publishes nothing.\n\n**Atomicity.** Opening and closing are single statements whose rowcount decides whether to publish. That is an `UPSERT ... DO UPDATE ... WHERE published = 0` for opening and an `UPDATE ... WHERE published = 1` for closing. Two concurrent requests can never both publish the same transition, and no request relies on a SELECT-then-write.\n\n### `client/backend/lib/users_store.py`\n\n`ensure_user_schema`: the docstring becomes \"Create the users, likes, like generation, profile, block and dislike tables if missing.\" Insert this after `dislike_profiles` and before the `local-user` comment:\n\n```sql\n        CREATE TABLE IF NOT EXISTS like_generations (\n          user_id TEXT NOT NULL,\n          video_id TEXT NOT NULL,\n          instance_domain TEXT NOT NULL,\n          generation INTEGER NOT NULL,\n          published INTEGER NOT NULL DEFAULT 0,\n          PRIMARY KEY (user_id, video_id, instance_domain)\n        );\n```\n\n`record_like`:\n\n```python\ndef record_like(\n    conn: sqlite3.Connection,\n    user_id: str,\n    action: str,\n    video: dict[str, Any],\n    max_likes: int,\n    publish: bool = False,\n) -> tuple[bool, int]:\n    \"\"\"Record a like with recency tracking.\n\n    :param publish: The caller publishes a `Like` when this opens one. The likes import passes nothing, so an imported like never opens one.\n    :returns: Whether this like opened the video's published like, and the video's like generation (0 when none was ever opened).\n    \"\"\"\n    if action != \"like\":\n        raise ValueError(\"Unsupported action\")\n    get_or_create_user(conn, user_id)\n    video_id = str(video.get(\"video_id\") or \"\")\n    instance_domain = str(video.get(\"instance_domain\") or \"\")\n    video_uuid = video.get(\"video_uuid\")\n    now = now_ms()\n    inserted = conn.execute(\n        \"\"\"\n        INSERT INTO likes (user_id, video_id, instance_domain, video_uuid, updated_at)\n        VALUES (?, ?, ?, ?, ?)\n        ON CONFLICT(user_id, video_id, instance_domain) DO NOTHING\n        \"\"\",\n        (user_id, video_id, instance_domain, video_uuid, now),\n    ).rowcount > 0\n    if not inserted:\n        conn.execute(\n            \"UPDATE likes SET video_uuid = ?, updated_at = ? WHERE user_id = ? AND video_id = ? AND instance_domain = ?\",\n            (video_uuid, now, user_id, video_id, instance_domain),\n        )\n    opened = False\n    if inserted and publish:\n        # A like still published (the Engine holds it through a reset or trim) is not opened again.\n        opened = conn.execute(\n            \"\"\"\n            INSERT INTO like_generations (user_id, video_id, instance_domain, generation, published)\n            VALUES (?, ?, ?, 1, 1)\n            ON CONFLICT(user_id, video_id, instance_domain)\n            DO UPDATE SET generation = like_generations.generation + 1, published = 1\n            WHERE like_generations.published = 0\n            \"\"\",\n            (user_id, video_id, instance_domain),\n        ).rowcount > 0\n    generation = like_generation(conn, user_id, video_id, instance_domain)\n    if max_likes > 0:\n        ...  # trim unchanged\n    conn.commit()\n    return opened, generation\n```\n\n- When the DO UPDATE's WHERE is false, SQLite treats the conflict as DO NOTHING, so `changes()` is 0 and `rowcount` is 0.\n- The `inserted` flag is taken from the INSERT's own cursor before any other statement runs.\n\nNew functions, placed after `remove_like`:\n\n```python\ndef like_generation(conn: sqlite3.Connection, user_id: str, video_id: str, instance_domain: str) -> int:\n    \"\"\"Return the profile's like generation for one video.\n\n    :returns: The generation, or 0 when no like of it was ever published.\n    \"\"\"\n    row = conn.execute(\n        \"SELECT generation FROM like_generations WHERE user_id = ? AND video_id = ? AND instance_domain = ?\",\n        (user_id, video_id, instance_domain),\n    ).fetchone()\n    return int(row[0]) if row else 0\n\n\ndef close_like(conn: sqlite3.Connection, user_id: str, video_id: str, instance_domain: str) -> tuple[bool, int]:\n    \"\"\"Close the profile's published like of one video, inside the caller's transaction.\n\n    :returns: Whether a published like was closed, so an `UndoLike` is due, and the generation that like was published under.\n    \"\"\"\n    closed = conn.execute(\n        \"UPDATE like_generations SET published = 0 WHERE user_id = ? AND video_id = ? AND instance_domain = ? AND published = 1\",\n        (user_id, video_id, instance_domain),\n    ).rowcount > 0\n    return closed, like_generation(conn, user_id, video_id, instance_domain)\n```\n\n- `row[0]` works with or without `row_factory`.\n- `remove_like` and `clear_likes` are unchanged.\n\n### `client/backend/lib/profiles.py`\n\nIn `delete_profile`, add `conn.execute(\"DELETE FROM like_generations WHERE user_id = ?\", (profile_id,))` after the `likes` delete, inside the same `with conn:`.\n\n### `client/backend/server.py`\n\nImports:\n- `import hashlib` goes between `argparse` and `ipaddress`.\n- `from uuid import uuid4` stays, because `run_id` still uses it.\n- `users_store` import: `(clear_likes, close_like, ensure_user_schema, fetch_recent_likes, get_or_create_user, load_liked_keys, record_like, remove_like, video_reaction)`. `like_generation` is not imported, since the server does not need it.\n\n`_store_reaction` (annotation `-> tuple[bool, int]`):\n\n```python\n        \"\"\"...\n        :returns: Whether to publish, a `Like` for a like and an `UndoLike` otherwise, and the like generation the event is published under.\n        ...\n        \"\"\"\n        conn = self.server.user_db\n        key = (video[\"video_id\"], video[\"instance_domain\"])\n        if action == \"undo_like\" or (action == \"like\" and not is_disliked(conn, profile_id, *key)):\n            with conn:\n                if action == \"like\":\n                    result = record_like(conn, profile_id, \"like\", video, MAX_LIKES, publish=True)\n                else:\n                    remove_like(conn, profile_id, *key)\n                    result = close_like(conn, profile_id, *key)\n            return result\n        entries = ...  # unchanged\n        if action == \"dislike\":\n            ...  # limit check and centroids unchanged, before any write\n            with conn:\n                remove_like(conn, profile_id, *key)\n                withdrawn = close_like(conn, profile_id, *key)\n                write_dislike(conn, profile_id, video, centroids)\n            return withdrawn\n        # undo_dislike, or a like replacing a dislike.\n        centroids = ...  # unchanged\n        result = (False, 0)\n        with conn:\n            delete_dislike(conn, profile_id, *key, centroids)\n            if action == \"like\":\n                result = record_like(conn, profile_id, \"like\", video, MAX_LIKES, publish=True)\n        return result\n```\n\n- The un-like decision comes from the flag, not from `remove_like`'s result. `remove_like` still removes the row, so reaction state is unchanged.\n- An un-like after a reset therefore still withdraws the Like the Engine holds. An un-like of an imported like, or of one that predates the table, withdraws nothing.\n\n`_handle_user_action` (docstring: \"Apply one like/dislike action and publish the `Like`/`UndoLike` it causes, if any.\"):\n\n```python\n        publish = action in (\"like\", \"undo_like\")\n        generation = 0  # the fixed generation of anonymous likes\n        if profile_id is not None:\n            try:\n                publish, generation = self._store_reaction(profile_id, action, video)\n            except DislikeLimitReached:\n                ...  # unchanged\n            except EngineApiError as exc:\n                ...  # unchanged\n            # A profile publishes only a like it opens or closes. A dislike publishes only to withdraw a like it replaced.\n        if not publish:\n            respond_json(self, 200, {\"ok\": True, \"updatedAt\": now_ms()})\n            return\n\n        event_type = \"Like\" if action == \"like\" else \"UndoLike\"\n        actor = profile_id or \"anonymous\"\n        # The JSON list keeps field boundaries unambiguous. Its encoding is part of every id, so it must never change.\n        identity = json.dumps([actor, canonical_uuid, canonical_host, event_type, generation])\n        event_payload = {\n            \"event_id\": \"client-\" + hashlib.sha256(identity.encode(\"utf-8\")).hexdigest(),\n            \"event_type\": event_type,\n            \"actor_id\": actor,\n            ...  # object, published_at, source_instance, raw_payload unchanged\n        }\n```\n\n`generation` is always an `int`: it comes from `int(row[0])`, the literal `1`, or `0`.\n\n### `engine/server/data/random_videos.py`\n\nAfter the imports:\n\n```python\n# The most of a video's interaction signal the popular ordering adds; the stored signal_score stays raw.\nPOPULAR_SIGNAL_CAP = 25.0\n```\n\nIn `fetch_popular_videos`:\n- docstring: \"Return the most popular videos: popularity plus the capped interaction signal, then likes and views.\"\n- `params: list[Any] = [POPULAR_SIGNAL_CAP, limit, limit]`\n- the threshold branch sets `params = [error_threshold, POPULAR_SIGNAL_CAP, limit, limit]`\n- the first ORDER BY term becomes `(v.popularity + MIN(COALESCE(sig.signal_score, 0), ?)) DESC,`\n\nThe placeholder order is: `{error_clause}` `?`, the cap `?`, the inner `LIMIT ?`, then the outer `LIMIT ?`. The `interaction_signal_score` column and the likes tiebreaker are untouched.\n\n### Tests\n\n**`tests/active/test_event_ids.py`** (new). It needs no live Engine or shared `whitelist.db` and is not rate-limited.\n\nModule docstring: the T1\u2013T8 bullets. Setup:\n- Add `engine/server` and `engine/server/api` to `sys.path`, as `test_random_videos.py` does.\n- Import `ensure_interaction_event_schema` and `ingest_interaction_event`.\n- From conftest, import `RateLimiter`, `client_server` and `ensure_user_schema`.\n\nHarness:\n- `_serving(srv)`: copied from `test_server.py`, about 8 lines.\n- A fixture `rig(tmp_path)` that yields `(client, engine_db, events)`:\n  - `engine_db` is `sqlite3.connect(tmp_path / \"engine.db\", check_same_thread=False)` with `row_factory = sqlite3.Row`, after `ensure_interaction_event_schema`.\n  - `events` is the list of `(payload, result)` pairs.\n  - An `EngineStub(BaseHTTPRequestHandler).do_POST` routes three paths:\n    - `/internal/videos/resolve`: answers `{\"video\": {\"video_id\": \"vid-\" + uuid, \"instance_domain\": host, \"video_uuid\": uuid, \"video_url\": f\"https://{host}/w/{uuid}\"}}`.\n    - `/internal/dislikes/centroids`: answers `{\"space\": \"test\", \"centroids\": []}`, which `compute_dislike_centroids` turns into None.\n    - `/internal/events/ingest`: runs `ingest_interaction_event(engine_db, payload)` under a lock, appends `(payload, result)`, and answers `{\"ok\": True, \"duplicates\": int(result[\"duplicate\"]), \"results\": [result]}`. This is the real ingest, not a mock.\n  - The Client is a `ClientBackendServer` on `tmp_path/\"users.db\"` in `\"bridge\"` mode with `RateLimiter(1000, 60)`, wrapped in conftest's `ClientBackend`.\n- Helpers:\n  - `_video()` returns a fresh `{\"uuid\": uuid4().hex, \"host\": \"ids.example\"}`.\n  - `_act(client, headers, action, video)` posts `/api/user-action` and returns the status.\n  - `_signal(engine_db, video)` returns `(likes_count, signal_score)`, or `(0, 0.0)`.\n  - `_published(events)` returns `[(p[\"event_type\"], p[\"event_id\"]) for p, r in events]`.\n\nCases:\n- **T1.** Mint, then like twice. Both answer 200. One event, a `Like`. `_signal == (1, 1.0)`.\n- **T2.** Like, undo_like, like. The types are `[Like, UndoLike, Like]`. `ids[0] == ids[1]` is false, because the types differ. `ids[0] != ids[2]`. `ids[0]` equals the expected sha256 of `[profile_id, uuid, host, \"Like\", 1]`, which pins the encoding, and `ids[2]` uses generation 2. The final signal score is 1.0.\n- **T3.** Take the first T1 payload and call `ingest_interaction_event(engine_db, payload)` again. `duplicate is True` and `_signal` is unchanged.\n- **T4.** Anonymous like twice. Both ids are equal, the second result has `duplicate is True`, and `_signal == (1, 1.0)`.\n- **T5.** Mint, then undo_like on a fresh video. Status 200 and no events.\n- **T6.** Mint, like, dislike. There are exactly two events, and the second is an `UndoLike` whose id equals sha256 of `[pid, uuid, host, \"UndoLike\", 1]`, the id an undo_like at g1 would have used. Then, on a second fresh video, a dislike answers 200 and adds no event.\n- **T7.** Mint, like, `POST /api/user-profile/reset` with the key, like again. Only one `Like` has been published. Then undo_like gives exactly one `UndoLike` at g1, and `_signal == (0, 0.0)`.\n- **T8.** Mint, `POST /api/profile/likes/import` with the key and `{\"likes\": [{\"video_uuid\": uuid, \"instance_domain\": host}]}`, then undo_like. There are no events.\n  - This depends on the stub's `resolve_videos_by_uuid_host` path. I have not read its endpoint yet (`engine_api_client.py:136-166`); the builder reads it and adds the matching stub route.\n  - If that route turns out to cost more than about 15 lines, fall back to seeding with `record_like(conn, pid, \"like\", video, 100)` without `publish` on the users.db. That is exactly the call the import makes.\n\n**`tests/active/test_random_videos.py`** gets `test_the_popular_order_caps_the_interaction_signal(tmp_path)`:\n- `_two_video_db`, then `UPDATE videos SET popularity = 0` on `first` and `30` on `second`.\n- `INSERT INTO interaction_signals (video_uuid, instance_domain, likes_count, signal_score, updated_at) VALUES (?, ?, 0, 1000.0, 0)` for `first`, then commit.\n- For `threshold in (None, 1)`, `fetch_popular_videos(conn, 10, error_threshold=threshold)` returns `[second, first]` by `video_id`, and `first`'s `interaction_signal_score == 1000.0`, which shows the stored value is still raw.\n- `_set_views` sets `error_count = 0`, so threshold 1 keeps both rows.\n- Add a docstring bullet.\n- A wrong params order either makes the cap act as the error threshold, which drops rows, or turns the limits into the cap. Both break one of the two branches.\n\n**`tests/active/test_profiles.py`**:\n- `_seed_like` passes `publish=True` to `record_like`.\n- `_rows_for` adds `\"like_generations\": conn.execute(\"SELECT COUNT(*) FROM like_generations WHERE user_id = ?\", (profile_id,)).fetchone()[0]`.\n- The asserts at 205, 209 and 216 gain `\"like_generations\": 1`, and the one at 215 gains `\"like_generations\": 0`.\n- The comment at 201 becomes \"record_like also creates the `users` row and opens a like generation, so all four tables hold rows for both.\"\n- `test_frontend_profile.py`'s `_seed_like` stays as it is (`publish` defaults to False).\n\n### Existing tests, walked through with the flag\n\n- `test_frontend_reactions` keyed sequence:\n  - like: opens g1 and publishes.\n  - dislike: closes g1, publishes UndoLike(g1).\n  - undo_dislike: publishes nothing.\n  - out-of-band dislike: nothing to close, 200.\n  - like replacing the dislike: opens g2 and publishes.\n  - undo_like: UndoLike(g2).\n  - The same shape as the settled walk-through, so `all(\"ok\" in a)` holds.\n- The card test and `test_profiles.py:300`: a fresh profile's first like opens and publishes, so still 502 on `unpublished_client`.\n- `test_dislikes` 74-87:\n  - line 77 closes the like opened at line 74, which publishes, so 200 or 502;\n  - line 82: 200;\n  - line 84: nothing to close, 200.\n- Keyless tests: unchanged from the inventory's account.\n- Smokes: a fresh profile's first like opens and publishes, and the raw row is keyed by the profile.\n\n### Acceptance criteria \u2192 evidence\n\n| Criterion | Holds because | Test |\n|---|---|---|\n| Double like, one Like, +1 / +1.0 | second INSERT rowcount 0, nothing is opened | T1 |\n| like\u2192undo\u2192like, distinct Like ids, 1.0 | g1 opened, closed, then g2 opened | T2 |\n| Bridge retry is a duplicate | same id, `ON CONFLICT(event_id) DO NOTHING` | T3 |\n| Anonymous duplicate | generation 0 and actor `anonymous` give a fixed id | T4 |\n| undo_like of an unliked video: 200, nothing | nothing to close | T5 |\n| Dislike UndoLike id = the undo_like id; unliked dislike publishes nothing | both go through `close_like` | T6 |\n| Signal 1000 / pop 0 below pop 30 | `MIN(1000, 25) = 25 < 30` | T9 |\n| `delete_profile` removes generations | new DELETE | T10 |\n| Existing suites | walk-through above | T11 |\n\n### Deviations from the settled plan and inventory\n\nAll of these follow from the operator's \"close both with a published flag\". None is silent.\n\n1. **Schema.** `like_generations` gains `published INTEGER NOT NULL DEFAULT 0`. The inventory's DDL lists only four columns.\n2. **When generation increments.** Only when a like is opened, that is, a new `likes` row from a publishing caller while `published=0`. The requirement says \"on every new likes row\". A re-like after a reset or trim, and every imported like, now leaves it unchanged. The contract still holds: a Like and its un-like share a generation, and the next Like differs.\n3. **Un-like gating.** Publishing depends on `close_like`, not on `remove_like`'s result. `remove_like` is still called and still removes the row.\n4. **`record_like` signature.** It gains the keyword `publish: bool = False`. `_handle_likes_import` (plan 14's handler) and the tests' `_seed_like` helpers keep working unedited. `record_like` returns `(opened, generation)` rather than `(new, generation)`.\n5. **Reader.** The inventory's reader exists as `like_generation(conn, user_id, video_id, instance_domain) -> int`, with the positional shape and `:returns:`. The server imports the new writer `close_like` instead of the reader, so the users_store import line gains `close_like`.\n6. **`test_profiles._seed_like`** passes `publish=True`. The inventory assumed `record_like` would always write a generation row.\n7. **Plan Risks, \"imported likes advance the generation, a later un-like publishes UndoLike (\u22121)\".** This no longer happens: an imported like never publishes either event.\n\n### Risks\n\n- **Likes that predate `like_generations`.** They have no row, so their un-like publishes nothing. The Engine keeps the +1 from the old random-id Like. The un-like side is bounded at 0, where the settled plan would have published a gen-0 UndoLike.\n- **Publish failure after the flag opens or closes** (bridge down, or `unpublished_client`). The Client's state moves while the Engine misses the event, and nothing retries it. Worst case, a later close publishes an UndoLike the Engine never saw a Like for. That is \u22121 once per generation, floored at 0. The settled plan had the same gap.\n- **Trim gap.** It is narrower as a side effect: a re-like after a trim publishes nothing and a later un-like withdraws. It stays open when the profile never re-likes.\n- **Anonymous import.** A like the browser published anonymously and then imported is never withdrawn by the profile. This falls under ADR-0001 \u00a73's anonymous +1.\n- **Concurrency.** Opening and closing are single conditional statements, so two concurrent requests cannot publish one transition twice. The existing dislike rat-tail is unchanged.\n- **Merge with plan 14.** The import-line edits (`hashlib`, `close_like`) resolve by union. Its import caller is untouched.\n\n### Documentation changes from the settled checklist\n\n- `client/README.md` line 19: \"an un-like publishes only when it withdraws a like the profile published, and a reset or import publishes nothing and never re-publishes\".\n- `CONTEXT.md` **Like generation**: add \"and whether its like is published\".\n- ADR-0001 Consequences: add the published flag, the closed loops, the legacy-like note and the import note.\n- `docs/project/roadmap.md`: drop the \"close the reset/import loops\" follow-up. Keep the import-publishing item, the likes-tiebreaker item, and a narrowed trim-gap item.\n\n### Convergence\n\nPass 1 checked the draft against the plan and requirements, with the operator decision applied. Every requirement is met or listed above as an approved deviation. Pass 2 found `_seed_like` needing `publish=True` and the dislike branch's `close_like` placement, and added both. No further change was needed.",
  "coordination": "none",
  "tests": {
    "tests/tmp/test_13_deterministic_event_ids_phase1.py": {
      "rows": [
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_13_deterministic_event_ids_phase1.py:80: for threshold in (None, 1), with the first video at popularity 0 and signal_score 1000.0 and the second at popularity 30 with no signal, `fetch_popular_videos(conn, 10, error_threshold=threshold)` returns video_ids in the order [second, first]. Its control is :82, which checks that `interaction_signal_score` stays raw: {first: 1000.0, second: 0}. The popularity-24.5 case at :90 is the below-cap control the operator approved earlier, moved from 20 to 24.5.",
          "expected": "[second, first] under both thresholds, since 0 + min(1000, 25) = 25 < 30.",
          "wrong_implementation": "Today's uncapped `popularity + COALESCE(signal_score, 0)` returns [first, second], because 1000 > 30. The last red run failed at :80 with threshold None: ['fd640a96\u2026'] == ['d6abc74c\u2026']. A cap applied only in the no-threshold branch fails the threshold=1 pass. A params order that puts the threshold (1) or the limit (10) in the cap's slot still passes :80, but fails the 24.5 case at :90, because 1 and 10 are both below 24.5."
        }
      ],
      "clauses": [
        {
          "id": "C1",
          "text": "A video with signal 1000 and popularity 0 ranks below a video with popularity 30 and no signal, with and without an error threshold."
        }
      ],
      "surface": "checkpoint",
      "results": {
        "command": "validate_tests.py tests/tmp/test_13_deterministic_event_ids_phase1.py",
        "code": 1,
        "output": "  tests/tmp/test_13_deterministic_event_ids_phase1.py  1 failed                               0.0s\n  ---------------------------------------------------\n  total                                                1 failed                               0.2s wall, 1 lane\n\nrecorded: tests/last_test_validation.json (exit 1)\nwrote tests/last_test_output.txt"
      }
    },
    "tests/tmp/test_13_deterministic_event_ids_phase2.py": {
      "rows": [
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_13_deterministic_event_ids_phase2.py:140 \u2014 after two keyed likes of one video the published types are exactly [\"Like\"]; :178 \u2014 undo_like of a never-liked video publishes nothing (armed by the :181 control, a like that does publish); :194 \u2014 after a dislike of an unliked video (stored, control :192) and an undo_dislike, still exactly 2 events have been published; :205 \u2014 like, reset, re-like (stored, control :204) has published exactly [\"Like\"]; :219 \u2014 undo_like of an imported like (stored :216, removed :218) publishes nothing, armed by the :222 control",
          "expected": ":140 [\"Like\"]; :178 []; :194 2; :205 [\"Like\"]; :219 []",
          "wrong_implementation": "Today's `publish = action in (\"like\", \"undo_like\")` publishes on every like and every undo_like. Under it :140 and :205 read [\"Like\", \"Like\"], and :178 and :219 read one UndoLike (observed in this run). An implementation that decides whether to publish from the stored like rather than the published one passes :140 but still gives [\"Like\", \"Like\"] at :205. One that publishes on dislike or undo_dislike with no like to remove reads more than 2 at :194."
        },
        {
          "clause": "C2",
          "assertion": "tests/tmp/test_13_deterministic_event_ids_phase2.py:142 \u2014 the one Like's id is \"client-\" + sha256(json.dumps([profile_id, uuid, host, \"Like\", 1])); :152 \u2014 like, undo_like, like publish the derived ids at (Like,1), (UndoLike,1), (Like,2); :159 \u2014 two anonymous likes both carry the derived id for [\"anonymous\", uuid, host, \"Like\", 0]; :171 \u2014 a like spelled with an upper-case uuid and host \"IDS.Example\" carries the id over the resolved lower-case uuid and host (controls :169\u2013170 confirm the resolved identity reached the payload)",
          "expected": "Each id equals `_event_id(actor, canonical video, event_type, generation)` with the actor, type and generation named above. For :159 that is two identical ids, which the Engine flags [False, True] at :160.",
          "wrong_implementation": "Today's `f\"client-{uuid4()}\"` fails :142, :152, :159 and :171, since each reads a random `client-` uuid (observed). An id that leaves out the event type makes Like and UndoLike at generation 1 collide at :152. One that leaves out the generation, or reuses generation 1 on a re-like, fails :152 (and :151). One that uses a per-request actor or a generation other than 0 for anonymous fails :159. Hashing the uuid and host as sent fails :171."
        }
      ],
      "clauses": [
        {
          "id": "C1",
          "text": "An action that neither opens nor closes the profile's published like of the video publishes no event."
        },
        {
          "id": "C2",
          "text": "A published event's id is `client-` plus the SHA-256 of the JSON list of actor, canonical uuid, canonical host, event type and like generation."
        }
      ],
      "surface": "checkpoint",
      "results": {
        "command": "validate_tests.py tests/tmp/test_13_deterministic_event_ids_phase2.py",
        "code": 1,
        "output": "  tests/tmp/test_13_deterministic_event_ids_phase2.py  8 failed                               0.0s\n  ---------------------------------------------------\n  total                                                8 failed                               5.2s wall, 1 lane\n\nrecorded: tests/last_test_validation.json (exit 1)\nwrote tests/last_test_output.txt"
      }
    },
    "tests/tmp/test_13_deterministic_event_ids_phase3.py": {
      "rows": [
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_13_deterministic_event_ids_phase3.py:75 \u2014 after the keyed POST /api/profile/delete for `gone_id` returns 204, `_rows_for(gone_id)` == {\"profiles\": 0, \"users\": 0, \"likes\": 0, \"like_generations\": 0}. Line 76 checks the other profile: `_rows_for(kept_id)` == {\"profiles\": 1, \"users\": 1, \"likes\": 1, \"like_generations\": 1}.",
          "expected": "Line 75: all four counts are 0 for the deleted profile. Before the delete that profile had 2 `like_generations` rows, one open (published=1) and one closed (the undone like, published=0), and the control on line 65 showed that. Line 76: the other profile still has 1/1/1/1, the same as before the delete (line 66).",
          "wrong_implementation": "(a) The current code leaves `like_generations` untouched. Line 75 then reads {\"profiles\": 0, \"users\": 0, \"likes\": 0, \"like_generations\": 2}, which is what this run showed. (b) A delete that finds generations through the likes rows it removes (e.g. `DELETE FROM like_generations WHERE (user_id, video_id, instance_domain) IN (SELECT ... FROM likes WHERE user_id = ?)`) misses the closed 'v-undone' generation, whose likes row is already gone. Line 75 then reads like_generations: 1. (c) A delete with no user filter (`DELETE FROM like_generations`) passes line 75, but line 76 then reads like_generations: 0 for the other profile."
        }
      ],
      "clauses": [
        {
          "id": "C1",
          "text": "After one profile is deleted, it has no `like_generations` rows and another profile keeps its rows."
        }
      ],
      "surface": "checkpoint",
      "results": {
        "command": "validate_tests.py tests/tmp/test_13_deterministic_event_ids_phase3.py",
        "code": 1,
        "output": "  tests/tmp/test_13_deterministic_event_ids_phase3.py  1 failed                               0.0s\n  ---------------------------------------------------\n  total                                                1 failed                               0.7s wall, 1 lane\n\nrecorded: tests/last_test_validation.json (exit 1)\nwrote tests/last_test_output.txt"
      }
    }
  },
  "audits": {
    "tests/tmp/test_13_deterministic_event_ids_phase1.py": [
      {
        "shape": "SHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\nThe test should fail first at line 69, on the order assertion when threshold is `None`. `fetch_popular_videos` sorts by `(v.popularity + COALESCE(sig.signal_score, 0)) DESC` with no cap (engine/server/data/random_videos.py:247). The first video scores 0 + 1000 = 1000, which beats the second video's 30, so the rows come back as `[first, second]` instead of `[second, first]`.\n\nNOT ASSESSED\n1. tests/active/test_random_videos.py was listed under `code_under_test` but only searched with Grep for test names and signal references, not read in full. The test under audit neither imports it nor uses anything from it.\n2. No `fixtures_path` was supplied. The test uses only pytest's built-in `tmp_path` and its own helpers (`_two_video_db`, `_set_popularity`), so no conftest was needed. The fixture reads live data from engine/server/db/whitelist.db, whose contents were not checked.",
        "claim": "CLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (11 clauses: 2 must_prove, 7 docstring, 2 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | signal 1000 / popularity 0 ranks below popularity 30 / no signal, without an error threshold | :69 (threshold=None pass of the :66 loop) | adding the signal with no cap (0+1000 > 30 would put `first` first) | CARRIED |\n| C1b | must_prove | the same order with an error threshold | :69 (threshold=1 pass of the :66 loop) | a cap applied only in the no-threshold branch; a query that breaks when the `error_clause` and its param are added | CARRIED |\n| D1a | docstring | \"adds a video's interaction signal only up to a cap of 25\": the cap is 25 | :69 + :76 | only places the cap between 20 and 30. A cap of 21 or 29 passes both | UNCARRIED |\n| D1b | docstring | \"adds ... up to a cap\": a signal below the cap is added in full | none | nothing. Every signal in the test is 1000, so a flat bonus for any positive signal passes | UNCARRIED |\n| D2 | docstring | \"ranks ... below a video with popularity 30 and no signal\" | :69 | uncapped addition | CARRIED |\n| D3 | docstring | \"and above one with popularity 20\" | :76 | dropping the signal from the order entirely (0 < 20) | CARRIED |\n| D4 | docstring | \"with and without an error threshold\" | :66, :69, :71, :76 | behaviour that differs between the two branches | CARRIED |\n| D5 | docstring | \"the row still reports the raw signal of 1000\" | :71 | returning the capped value in `interaction_signal_score` | CARRIED |\n| D6 | docstring | \"a temporary copy of two real videos out of `whitelist.db`\" | :39 | a fixture that silently copies fewer than two videos | CARRIED |\n| N1 | name | `the_popular_order_caps_the_interaction_signal` | :69, :76 | uncapped addition (:69) and a dropped signal (:76) | CARRIED |\n| N2 | name | module name `test_13_deterministic_event_ids_phase1`: \"deterministic event ids\" | none | nothing. No assertion touches event ids | UNCARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. whole-claim (rules/testing.md) \u2014 tests/tmp/test_13_deterministic_event_ids_phase1.py:1\n   `\"\"\"The Engine's popular order adds a video's interaction signal only up to a cap of 25.`\n   D1a and D1b are UNCARRIED. The popularities of 30 at :67 and `CAP - 5` = 20 at :74 only show the cap is somewhere between 20 and 30. The value 25 is never pinned. Because every signal is 1000, \"adds ... up to\" is never shown to add a sub-cap signal in full, so a fixed +25 bonus for any positive signal passes. These are docstring clauses that are not in `must_prove`, so this does not block.\n2. bounds (rules/testing.md) \u2014 tests/tmp/test_13_deterministic_event_ids_phase1.py:24\n   Only one signal value is tested (`SIGNAL = 1000.0`). These edges are untested: a signal of exactly 25, a signal just past 25, a signal below the cap, a zero signal, and a video with no `interaction_signals` row alongside one that has a signal.\n3. normal-and-abnormal-paths (rules/testing.md) \u2014 tests/tmp/test_13_deterministic_event_ids_phase1.py:56\n   `error_count = 0` keeps both rows under the threshold of 1, so the threshold never excludes anything. No case shows how a high-signal video with `error_count >= threshold` is handled in the popular order.\n4. name-as-sentence (rules/testing.md) \u2014 tests/tmp/test_13_deterministic_event_ids_phase1.py:1 (module name)\n   N2 is UNCARRIED. The module name says \"deterministic event ids\", but the test is about a signal cap in the popular order. The runner's node id will point readers at the wrong behaviour.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `fixtures_path` was \"none found\". The test defines all its helpers itself (:29, :53) and uses only pytest's built-in `tmp_path`, so there was no conftest to read.\n2. The test depends on the external read-only `engine/server/db/whitelist.db` (:19, :33) holding at least two videos with embeddings and a non-null uuid. I did not check the file's contents. :39 guards the count.",
        "body": "### devsecops-test-shape-auditor\n\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\nThe test should fail first at line 69, on the order assertion when threshold is `None`. `fetch_popular_videos` sorts by `(v.popularity + COALESCE(sig.signal_score, 0)) DESC` with no cap (engine/server/data/random_videos.py:247). The first video scores 0 + 1000 = 1000, which beats the second video's 30, so the rows come back as `[first, second]` instead of `[second, first]`.\n\nNOT ASSESSED\n1. tests/active/test_random_videos.py was listed under `code_under_test` but only searched with Grep for test names and signal references, not read in full. The test under audit neither imports it nor uses anything from it.\n2. No `fixtures_path` was supplied. The test uses only pytest's built-in `tmp_path` and its own helpers (`_two_video_db`, `_set_popularity`), so no conftest was needed. The fixture reads live data from engine/server/db/whitelist.db, whose contents were not checked.\n\n### devsecops-test-claim-auditor\n\nCLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (11 clauses: 2 must_prove, 7 docstring, 2 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | signal 1000 / popularity 0 ranks below popularity 30 / no signal, without an error threshold | :69 (threshold=None pass of the :66 loop) | adding the signal with no cap (0+1000 > 30 would put `first` first) | CARRIED |\n| C1b | must_prove | the same order with an error threshold | :69 (threshold=1 pass of the :66 loop) | a cap applied only in the no-threshold branch; a query that breaks when the `error_clause` and its param are added | CARRIED |\n| D1a | docstring | \"adds a video's interaction signal only up to a cap of 25\": the cap is 25 | :69 + :76 | only places the cap between 20 and 30. A cap of 21 or 29 passes both | UNCARRIED |\n| D1b | docstring | \"adds ... up to a cap\": a signal below the cap is added in full | none | nothing. Every signal in the test is 1000, so a flat bonus for any positive signal passes | UNCARRIED |\n| D2 | docstring | \"ranks ... below a video with popularity 30 and no signal\" | :69 | uncapped addition | CARRIED |\n| D3 | docstring | \"and above one with popularity 20\" | :76 | dropping the signal from the order entirely (0 < 20) | CARRIED |\n| D4 | docstring | \"with and without an error threshold\" | :66, :69, :71, :76 | behaviour that differs between the two branches | CARRIED |\n| D5 | docstring | \"the row still reports the raw signal of 1000\" | :71 | returning the capped value in `interaction_signal_score` | CARRIED |\n| D6 | docstring | \"a temporary copy of two real videos out of `whitelist.db`\" | :39 | a fixture that silently copies fewer than two videos | CARRIED |\n| N1 | name | `the_popular_order_caps_the_interaction_signal` | :69, :76 | uncapped addition (:69) and a dropped signal (:76) | CARRIED |\n| N2 | name | module name `test_13_deterministic_event_ids_phase1`: \"deterministic event ids\" | none | nothing. No assertion touches event ids | UNCARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. whole-claim (rules/testing.md) \u2014 tests/tmp/test_13_deterministic_event_ids_phase1.py:1\n   `\"\"\"The Engine's popular order adds a video's interaction signal only up to a cap of 25.`\n   D1a and D1b are UNCARRIED. The popularities of 30 at :67 and `CAP - 5` = 20 at :74 only show the cap is somewhere between 20 and 30. The value 25 is never pinned. Because every signal is 1000, \"adds ... up to\" is never shown to add a sub-cap signal in full, so a fixed +25 bonus for any positive signal passes. These are docstring clauses that are not in `must_prove`, so this does not block.\n2. bounds (rules/testing.md) \u2014 tests/tmp/test_13_deterministic_event_ids_phase1.py:24\n   Only one signal value is tested (`SIGNAL = 1000.0`). These edges are untested: a signal of exactly 25, a signal just past 25, a signal below the cap, a zero signal, and a video with no `interaction_signals` row alongside one that has a signal.\n3. normal-and-abnormal-paths (rules/testing.md) \u2014 tests/tmp/test_13_deterministic_event_ids_phase1.py:56\n   `error_count = 0` keeps both rows under the threshold of 1, so the threshold never excludes anything. No case shows how a high-signal video with `error_count >= threshold` is handled in the popular order.\n4. name-as-sentence (rules/testing.md) \u2014 tests/tmp/test_13_deterministic_event_ids_phase1.py:1 (module name)\n   N2 is UNCARRIED. The module name says \"deterministic event ids\", but the test is about a signal cap in the popular order. The runner's node id will point readers at the wrong behaviour.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `fixtures_path` was \"none found\". The test defines all its helpers itself (:29, :53) and uses only pytest's built-in `tmp_path`, so there was no conftest to read.\n2. The test depends on the external read-only `engine/server/db/whitelist.db` (:19, :33) holding at least two videos with embeddings and a non-null uuid. I did not check the file's contents. :39 guards the count.",
        "map": [
          {
            "id": "C1a",
            "source": "must_prove",
            "clause": "signal 1000 / popularity 0 ranks below popularity 30 / no signal, without an error threshold",
            "assertion": ":69 (threshold=None pass of the :66 loop)",
            "excludes": "adding the signal with no cap (0+1000 > 30 would put `first` first)",
            "status": "CARRIED"
          },
          {
            "id": "C1b",
            "source": "must_prove",
            "clause": "the same order with an error threshold",
            "assertion": ":69 (threshold=1 pass of the :66 loop)",
            "excludes": "a cap applied only in the no-threshold branch; a query that breaks when the `error_clause` and its param are added",
            "status": "CARRIED"
          },
          {
            "id": "D1a",
            "source": "docstring",
            "clause": "\"adds a video's interaction signal only up to a cap of 25\": the cap is 25",
            "assertion": ":69 + :76",
            "excludes": "only places the cap between 20 and 30. A cap of 21 or 29 passes both",
            "status": "UNCARRIED"
          },
          {
            "id": "D1b",
            "source": "docstring",
            "clause": "\"adds ... up to a cap\": a signal below the cap is added in full",
            "assertion": "none",
            "excludes": "nothing. Every signal in the test is 1000, so a flat bonus for any positive signal passes",
            "status": "UNCARRIED"
          },
          {
            "id": "D2",
            "source": "docstring",
            "clause": "\"ranks ... below a video with popularity 30 and no signal\"",
            "assertion": ":69",
            "excludes": "uncapped addition",
            "status": "CARRIED"
          },
          {
            "id": "D3",
            "source": "docstring",
            "clause": "\"and above one with popularity 20\"",
            "assertion": ":76",
            "excludes": "dropping the signal from the order entirely (0 < 20)",
            "status": "CARRIED"
          },
          {
            "id": "D4",
            "source": "docstring",
            "clause": "\"with and without an error threshold\"",
            "assertion": ":66, :69, :71, :76",
            "excludes": "behaviour that differs between the two branches",
            "status": "CARRIED"
          },
          {
            "id": "D5",
            "source": "docstring",
            "clause": "\"the row still reports the raw signal of 1000\"",
            "assertion": ":71",
            "excludes": "returning the capped value in `interaction_signal_score`",
            "status": "CARRIED"
          },
          {
            "id": "D6",
            "source": "docstring",
            "clause": "\"a temporary copy of two real videos out of `whitelist.db`\"",
            "assertion": ":39",
            "excludes": "a fixture that silently copies fewer than two videos",
            "status": "CARRIED"
          },
          {
            "id": "N1",
            "source": "name",
            "clause": "`the_popular_order_caps_the_interaction_signal`",
            "assertion": ":69, :76",
            "excludes": "uncapped addition (:69) and a dropped signal (:76)",
            "status": "CARRIED"
          },
          {
            "id": "N2",
            "source": "name",
            "clause": "module name `test_13_deterministic_event_ids_phase1`: \"deterministic event ids\"",
            "assertion": "none",
            "excludes": "nothing. No assertion touches event ids",
            "status": "UNCARRIED"
          }
        ],
        "map_problem": ""
      },
      {
        "shape": "```\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\nFails at tests/tmp/test_13_deterministic_event_ids_phase1.py:80 on the first pass\n(threshold None). The ordering assertion expects [second, first] but gets\n[first[\"video_id\"], second[\"video_id\"]], because fetch_popular_videos\n(engine/server/data/random_videos.py:247) sorts by\n`v.popularity + COALESCE(sig.signal_score, 0)` with no cap, so 0 + 1000 ranks above 30.\n\nNOT ASSESSED\n1. `fixtures_path` was not supplied. The test's only fixture is pytest's built-in\n   `tmp_path`, and tests/active/conftest.py does not cover tests/tmp/, so no fixture\n   went unread.\n2. The test builds its database from engine/server/db/whitelist.db at run time\n   (lines 38-44). The data in that file was not read. The stub question assumes the\n   query returns two videos with a non-null video_uuid, which line 44 asserts.\n```",
        "claim": "CLAIM AUDIT \u2014 VERDICT: BLOCK\n\nCLAUSE MAP  (11 clauses: 2 must_prove, 7 docstring, 2 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | signal 1000 / popularity 0 ranks below popularity 30 / no signal, without an error threshold | :80 (threshold=None pass of the :76 loop) | adding the signal with no cap (0+1000 > 30 would put `first` first) | CARRIED |\n| C1b | must_prove | the same order with an error threshold | :80 (threshold=1 pass of the :76 loop) | a cap applied only in the no-threshold branch; a query that breaks when the `error_clause` and its param are added | CARRIED |\n| D1a | docstring | \"adds a video's interaction signal only up to a cap of 25\": the cap is 25 | :90 (cases 1000 vs 24.5 and 1000 vs 25.5 at :86) | any cap of 24.5 or less (including a dropped signal) and any cap of 25.5 or more. This puts the cap within half a point of 25, which is what docstring :4 now claims | CARRIED |\n| D1b | docstring | \"adds ... up to a cap\": a signal below the cap is added in full | :90 (cases 10 vs 5 and 10 vs 15 at :86) | a flat cap bonus for any positive signal (25 > 15 fails) and a dropped signal (0 < 5 fails). A signal scaled into the open range (5, 15) still passes, which docstring :5 now states | CARRIED |\n| D2 | docstring | \"ranks ... below a video with popularity 30 and no signal\" | :80 | uncapped addition | CARRIED |\n| D3 | docstring | withdrawn | n/a | n/a | CARRIED |\n| D4 | docstring | \"with and without an error threshold\" | :76, :80, :82, :90 | behaviour that differs between the two branches | CARRIED |\n| D5 | docstring | \"the row still reports the raw signal of 1000\" | :82 | returning the capped value in `interaction_signal_score` | CARRIED |\n| D6 | docstring | \"a temporary copy of two real videos out of `whitelist.db`\" | :44 | a fixture that silently copies fewer than two videos | CARRIED |\n| N1 | name | `the_popular_order_caps_the_interaction_signal` | :80, :90 | uncapped addition (:80), and a cap set anywhere but 25 \u00b1 0.5 (:90) | CARRIED |\n| N2 | name | module name `test_13_deterministic_event_ids_phase1`: \"deterministic event ids\" | none | nothing. No assertion touches event ids. Docstring :7 now says so in prose, which does not carry the clause | UNCARRIED |\n\nCRITICAL\n1. whole-claim (rules/testing.md), re-audit rule 2. tests/tmp/test_13_deterministic_event_ids_phase1.py:7\n   `The module is named for its build, plan 13 (deterministic event ids), whose second change is this cap; nothing here asserts anything about event ids.`\n   N2 was UNCARRIED on the first audit and is still UNCARRIED. The module name still claims \"deterministic event ids\". The rewrite added a docstring sentence explaining the mismatch but did not add an assertion or rename the module, so nothing rules out any wrong event-id implementation. A reader of the runner output sees `test_13_deterministic_event_ids_phase1` and trusts a claim the file admits it does not test. The rule requires the name's clause to be carried by an assertion. The fix is to rename the module to what it proves (for example, the popular-order signal cap), not to explain the name in prose.\n\nRECOMMENDATIONS\nnone\n\nOBSERVATIONS\n1. whole-claim (rules/testing.md): tests/tmp/test_13_deterministic_event_ids_phase1.py:4. Row D3 (\"and above one with popularity 20\") no longer appears in the docstring. It was replaced by a stronger sentence, \"ranks above popularity 24.5 and below popularity 25.5\", which :90 asserts. So the prose was replaced by a stricter claim that is asserted. It was not narrowed to escape the finding. Recorded here as re-audit rule 4 requires.\n2. normal-and-abnormal-paths (rules/testing.md): tests/tmp/test_13_deterministic_event_ids_phase1.py:61, :76. `_set_popularity` sets `error_count = 0` on both rows, so the threshold=1 pass never has a row the threshold removes. The with-threshold pass proves the order holds when the `error_clause` is present. It does not prove the cap still holds when the clause actually filters out a row. C1 does not ask for that, so this does not block.\n3. bounds (rules/testing.md): tests/tmp/test_13_deterministic_event_ids_phase1.py:86. The signals tested are 1000 and 10. A signal exactly at the cap (25) and a signal of 0 on the scored video are not tested. A `<`-versus-`<=` mistake at the cap boundary would not be caught.\n\nNOT ASSESSED\n1. `fixtures_path` was not supplied. The test uses only pytest's built-in `tmp_path` and defines no other fixtures, so no conftest was needed.\n2. What is actually in `engine/server/db/whitelist.db` was not inspected. The only check is that :44 asserts two qualifying videos exist.\n3. `tests/active/test_random_videos.py` is listed in `code_under_test`. I only searched it for its popular-order assertions and did not read it in full. It is a sibling test, not code this test exercises.",
        "body": "### devsecops-test-shape-auditor\n\n```\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\nFails at tests/tmp/test_13_deterministic_event_ids_phase1.py:80 on the first pass\n(threshold None). The ordering assertion expects [second, first] but gets\n[first[\"video_id\"], second[\"video_id\"]], because fetch_popular_videos\n(engine/server/data/random_videos.py:247) sorts by\n`v.popularity + COALESCE(sig.signal_score, 0)` with no cap, so 0 + 1000 ranks above 30.\n\nNOT ASSESSED\n1. `fixtures_path` was not supplied. The test's only fixture is pytest's built-in\n   `tmp_path`, and tests/active/conftest.py does not cover tests/tmp/, so no fixture\n   went unread.\n2. The test builds its database from engine/server/db/whitelist.db at run time\n   (lines 38-44). The data in that file was not read. The stub question assumes the\n   query returns two videos with a non-null video_uuid, which line 44 asserts.\n```\n\n### devsecops-test-claim-auditor\n\nCLAIM AUDIT \u2014 VERDICT: BLOCK\n\nCLAUSE MAP  (11 clauses: 2 must_prove, 7 docstring, 2 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | signal 1000 / popularity 0 ranks below popularity 30 / no signal, without an error threshold | :80 (threshold=None pass of the :76 loop) | adding the signal with no cap (0+1000 > 30 would put `first` first) | CARRIED |\n| C1b | must_prove | the same order with an error threshold | :80 (threshold=1 pass of the :76 loop) | a cap applied only in the no-threshold branch; a query that breaks when the `error_clause` and its param are added | CARRIED |\n| D1a | docstring | \"adds a video's interaction signal only up to a cap of 25\": the cap is 25 | :90 (cases 1000 vs 24.5 and 1000 vs 25.5 at :86) | any cap of 24.5 or less (including a dropped signal) and any cap of 25.5 or more. This puts the cap within half a point of 25, which is what docstring :4 now claims | CARRIED |\n| D1b | docstring | \"adds ... up to a cap\": a signal below the cap is added in full | :90 (cases 10 vs 5 and 10 vs 15 at :86) | a flat cap bonus for any positive signal (25 > 15 fails) and a dropped signal (0 < 5 fails). A signal scaled into the open range (5, 15) still passes, which docstring :5 now states | CARRIED |\n| D2 | docstring | \"ranks ... below a video with popularity 30 and no signal\" | :80 | uncapped addition | CARRIED |\n| D3 | docstring | withdrawn | n/a | n/a | CARRIED |\n| D4 | docstring | \"with and without an error threshold\" | :76, :80, :82, :90 | behaviour that differs between the two branches | CARRIED |\n| D5 | docstring | \"the row still reports the raw signal of 1000\" | :82 | returning the capped value in `interaction_signal_score` | CARRIED |\n| D6 | docstring | \"a temporary copy of two real videos out of `whitelist.db`\" | :44 | a fixture that silently copies fewer than two videos | CARRIED |\n| N1 | name | `the_popular_order_caps_the_interaction_signal` | :80, :90 | uncapped addition (:80), and a cap set anywhere but 25 \u00b1 0.5 (:90) | CARRIED |\n| N2 | name | module name `test_13_deterministic_event_ids_phase1`: \"deterministic event ids\" | none | nothing. No assertion touches event ids. Docstring :7 now says so in prose, which does not carry the clause | UNCARRIED |\n\nCRITICAL\n1. whole-claim (rules/testing.md), re-audit rule 2. tests/tmp/test_13_deterministic_event_ids_phase1.py:7\n   `The module is named for its build, plan 13 (deterministic event ids), whose second change is this cap; nothing here asserts anything about event ids.`\n   N2 was UNCARRIED on the first audit and is still UNCARRIED. The module name still claims \"deterministic event ids\". The rewrite added a docstring sentence explaining the mismatch but did not add an assertion or rename the module, so nothing rules out any wrong event-id implementation. A reader of the runner output sees `test_13_deterministic_event_ids_phase1` and trusts a claim the file admits it does not test. The rule requires the name's clause to be carried by an assertion. The fix is to rename the module to what it proves (for example, the popular-order signal cap), not to explain the name in prose.\n\nRECOMMENDATIONS\nnone\n\nOBSERVATIONS\n1. whole-claim (rules/testing.md): tests/tmp/test_13_deterministic_event_ids_phase1.py:4. Row D3 (\"and above one with popularity 20\") no longer appears in the docstring. It was replaced by a stronger sentence, \"ranks above popularity 24.5 and below popularity 25.5\", which :90 asserts. So the prose was replaced by a stricter claim that is asserted. It was not narrowed to escape the finding. Recorded here as re-audit rule 4 requires.\n2. normal-and-abnormal-paths (rules/testing.md): tests/tmp/test_13_deterministic_event_ids_phase1.py:61, :76. `_set_popularity` sets `error_count = 0` on both rows, so the threshold=1 pass never has a row the threshold removes. The with-threshold pass proves the order holds when the `error_clause` is present. It does not prove the cap still holds when the clause actually filters out a row. C1 does not ask for that, so this does not block.\n3. bounds (rules/testing.md): tests/tmp/test_13_deterministic_event_ids_phase1.py:86. The signals tested are 1000 and 10. A signal exactly at the cap (25) and a signal of 0 on the scored video are not tested. A `<`-versus-`<=` mistake at the cap boundary would not be caught.\n\nNOT ASSESSED\n1. `fixtures_path` was not supplied. The test uses only pytest's built-in `tmp_path` and defines no other fixtures, so no conftest was needed.\n2. What is actually in `engine/server/db/whitelist.db` was not inspected. The only check is that :44 asserts two qualifying videos exist.\n3. `tests/active/test_random_videos.py` is listed in `code_under_test`. I only searched it for its popular-order assertions and did not read it in full. It is a sibling test, not code this test exercises.",
        "map": [
          {
            "id": "C1a",
            "source": "must_prove",
            "clause": "signal 1000 / popularity 0 ranks below popularity 30 / no signal, without an error threshold",
            "assertion": ":80 (threshold=None pass of the :76 loop)",
            "excludes": "adding the signal with no cap (0+1000 > 30 would put `first` first)",
            "status": "CARRIED"
          },
          {
            "id": "C1b",
            "source": "must_prove",
            "clause": "the same order with an error threshold",
            "assertion": ":80 (threshold=1 pass of the :76 loop)",
            "excludes": "a cap applied only in the no-threshold branch; a query that breaks when the `error_clause` and its param are added",
            "status": "CARRIED"
          },
          {
            "id": "D1a",
            "source": "docstring",
            "clause": "\"adds a video's interaction signal only up to a cap of 25\": the cap is 25",
            "assertion": ":90 (cases 1000 vs 24.5 and 1000 vs 25.5 at :86)",
            "excludes": "any cap of 24.5 or less (including a dropped signal) and any cap of 25.5 or more. This puts the cap within half a point of 25, which is what docstring :4 now claims",
            "status": "CARRIED"
          },
          {
            "id": "D1b",
            "source": "docstring",
            "clause": "\"adds ... up to a cap\": a signal below the cap is added in full",
            "assertion": ":90 (cases 10 vs 5 and 10 vs 15 at :86)",
            "excludes": "a flat cap bonus for any positive signal (25 > 15 fails) and a dropped signal (0 < 5 fails). A signal scaled into the open range (5, 15) still passes, which docstring :5 now states",
            "status": "CARRIED"
          },
          {
            "id": "D2",
            "source": "docstring",
            "clause": "\"ranks ... below a video with popularity 30 and no signal\"",
            "assertion": ":80",
            "excludes": "uncapped addition",
            "status": "CARRIED"
          },
          {
            "id": "D3",
            "source": "docstring",
            "clause": "withdrawn",
            "assertion": "n/a",
            "excludes": "n/a",
            "status": "CARRIED"
          },
          {
            "id": "D4",
            "source": "docstring",
            "clause": "\"with and without an error threshold\"",
            "assertion": ":76, :80, :82, :90",
            "excludes": "behaviour that differs between the two branches",
            "status": "CARRIED"
          },
          {
            "id": "D5",
            "source": "docstring",
            "clause": "\"the row still reports the raw signal of 1000\"",
            "assertion": ":82",
            "excludes": "returning the capped value in `interaction_signal_score`",
            "status": "CARRIED"
          },
          {
            "id": "D6",
            "source": "docstring",
            "clause": "\"a temporary copy of two real videos out of `whitelist.db`\"",
            "assertion": ":44",
            "excludes": "a fixture that silently copies fewer than two videos",
            "status": "CARRIED"
          },
          {
            "id": "N1",
            "source": "name",
            "clause": "`the_popular_order_caps_the_interaction_signal`",
            "assertion": ":80, :90",
            "excludes": "uncapped addition (:80), and a cap set anywhere but 25 \u00b1 0.5 (:90)",
            "status": "CARRIED"
          },
          {
            "id": "N2",
            "source": "name",
            "clause": "module name `test_13_deterministic_event_ids_phase1`: \"deterministic event ids\"",
            "assertion": "none",
            "excludes": "nothing. No assertion touches event ids. Docstring :7 now says so in prose, which does not carry the clause",
            "status": "UNCARRIED"
          }
        ],
        "map_problem": ""
      },
      {
        "shape": "```\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\nFails at tests/tmp/test_13_deterministic_event_ids_phase1.py:80 on the first pass of the loop\n(threshold None). The order assertion receives [first[\"video_id\"], second[\"video_id\"]] where it\nexpects [second[\"video_id\"], first[\"video_id\"]]. The cause is engine/server/data/random_videos.py:247,\nwhich orders by the uncapped `v.popularity + COALESCE(sig.signal_score, 0)`, so 0 + 1000 ranks above 30 + 0.\n\nNOT ASSESSED\n1. `code_under_test` lists tests/active/test_random_videos.py, which is a test file and not code this\n   test exercises. It was read and has no bearing on this verdict.\n2. `fixtures_path` was not supplied. The test uses only pytest's built-in `tmp_path` and defines its\n   own helpers, so no conftest was needed. The symbols it imports exist:\n   ensure_interaction_event_schema at engine/server/data/interaction_events.py:19, and\n   fetch_popular_videos at engine/server/data/random_videos.py:195. So do the interaction_signals\n   columns written at line 72, at interaction_events.py:42-51.\n3. Anti-patterns pass (rules/shape.md): no entry matches.\n   - doc-lint-grep, section-scoped-substring-grep, whole-file-source-name-grep: the test reads no\n     document and does no substring check.\n   - hardcoded-spec-mirror: CAP at line 30 is compared with no code constant. The test only uses it\n     to build inputs.\n   - tautological-assertion: the expected values at lines 80 and 90 are written-down orderings, not\n     worked out the way the code works them out.\n   - absence-only-assertion: every assertion is a positive equality.\n   - echoed-literal: line 82 gets SIGNAL back, but through the production SELECT in\n     fetch_popular_videos, and it is a control that sits next to the order assertions rather than\n     standing alone.\n   - single-value-pin: the ranking is read at six input pairs (lines 78 and 86), each checked under\n     two thresholds, so an output that ignored its input would fail at least one.\n4. Ladder pass (rules/shape.md <ladder>): rung 1. The test calls fetch_popular_videos directly and\n   asserts on the rows it returns. That is the highest rung for a ranking invariant, so there is no\n   downshift and no comment is needed. It is not on the anti-rung.\n5. Stub question: the unchanged code ranks signal 1000 first and fails line 80. Dropping the signal\n   altogether, or capping at 24 or less, fails the (CAP - 0.5) case at line 86. Capping at 26 or more\n   fails the (CAP + 0.5) case. Adding a flat cap bonus for any signal fails the (SUB_CAP_SIGNAL, 15.0)\n   case. A hard-coded order cannot satisfy both the leader-first and trailer-first cases at line 86.\n   The test fails against each of these wrong implementations, so it works as a gate.\n```",
        "claim": "CLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (11 clauses: 2 must_prove, 7 docstring, 2 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | signal 1000 / popularity 0 ranks below popularity 30 / no signal, without an error threshold | :80 (threshold=None pass of the :76 loop) | adding the signal with no cap (0+1000 > 30 would put `first` first) | CARRIED |\n| C1b | must_prove | the same order with an error threshold | :80 (threshold=1 pass of the :76 loop) | a cap applied only in the no-threshold branch; a query that breaks when `error_clause` and its param are added | CARRIED |\n| D1a | docstring | \"adds a video's interaction signal only up to a cap of 25\": the cap is 25 | :90 (cases `CAP - 0.5`, `CAP + 0.5`, both thresholds) | any cap of 24.5 or less (including a dropped signal) and any cap of 25.5 or more, so every integer cap other than 25. Docstring :4 gives the half-point tolerance itself | CARRIED |\n| D1b | docstring | \"adds ... up to a cap\": a signal below the cap is added in full | :90 (cases `SUB_CAP_SIGNAL` against 5.0 and 15.0, both thresholds) | a flat cap-sized bonus for any positive signal (25 > 15), and a dropped sub-cap signal (0 < 5) | CARRIED |\n| D2 | docstring | \"ranks ... below a video with popularity 30 and no signal\" | :80 | uncapped addition | CARRIED |\n| D3 | docstring | withdrawn | n/a | n/a | CARRIED |\n| D4 | docstring | \"with and without an error threshold\" | :76, :80, :82, :90 | behaviour that differs between the two branches | CARRIED |\n| D5 | docstring | \"the row still reports the raw signal of 1000\" | :82 | returning the capped value in `interaction_signal_score` | CARRIED |\n| D6 | docstring | \"a temporary copy of two real videos out of `whitelist.db`\" | :44 | a fixture that silently copies fewer than two videos | CARRIED |\n| N1 | name | `the_popular_order_caps_the_interaction_signal` | :80, :90 | uncapped addition (:80); a cap anywhere other than 25 \u00b1 0.5 (:90) | CARRIED |\n| N2 | name | module name `test_13_deterministic_event_ids_phase1`: \"deterministic event ids\" | n/a | n/a | EXEMPT |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nOBSERVATIONS\n1. whole-claim (rules/testing.md): D3 at tests/tmp/test_13_deterministic_event_ids_phase1.py:1-5. The first-audit sentence \"and above one with popularity 20\" is no longer in the docstring, so under `<re_audit>` rule 4 the row is recorded as withdrawn. This was a replacement, not a retreat. Docstring :4 now claims a stronger bound (\"ranks above popularity 24.5\"), and :90 asserts it (`(SIGNAL, CAP - 0.5, first, second)`). That bound implies the one that was dropped.\n2. whole-claim (rules/testing.md): D1b at tests/tmp/test_13_deterministic_event_ids_phase1.py:86/:90. \"Counts in full\" is only pinned to the range (5, 15). A signal scaled before it is capped, such as `min(0.6 * signal, 25)`, gives 6 for a signal of 10 and passes both sub-cap cases. It also passes the 24.5/25.5 cases. Docstring :5 describes exactly the range it checks (\"ranks above popularity 5 and below popularity 15\"), so the prose and the assertion agree. Checking against 9.5 and 10.5 would pin \"in full\" as tightly as :4 pins the cap.\n3. normal-and-abnormal-paths (rules/testing.md): tests/tmp/test_13_deterministic_event_ids_phase1.py:59/:61. The threshold=1 pass always sets `error_count = 0` on both rows, so the error threshold never excludes a row. Nothing shows that the capped order still holds when the threshold filters out one of the ranked videos.\n4. bounds (rules/testing.md): tests/tmp/test_13_deterministic_event_ids_phase1.py:86. The signals tested are 1000, 10 and 0, the last being the unsignalled `second`. There is no case for a signal exactly at the cap (25) or at zero on a row that has an `interaction_signals` entry.\n\nNOT ASSESSED\n1. `fixtures_path` was none, and the test defines its own helpers (`_two_video_db`, `_set_popularity`, `_set_signal`) and uses only pytest's built-in `tmp_path`, so there is no conftest to read. The contents of `engine/server/db/whitelist.db` were not read. D6 was judged from the `assert len(picks) == 2` guard at :44.",
        "body": "### devsecops-test-shape-auditor\n\n```\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\nFails at tests/tmp/test_13_deterministic_event_ids_phase1.py:80 on the first pass of the loop\n(threshold None). The order assertion receives [first[\"video_id\"], second[\"video_id\"]] where it\nexpects [second[\"video_id\"], first[\"video_id\"]]. The cause is engine/server/data/random_videos.py:247,\nwhich orders by the uncapped `v.popularity + COALESCE(sig.signal_score, 0)`, so 0 + 1000 ranks above 30 + 0.\n\nNOT ASSESSED\n1. `code_under_test` lists tests/active/test_random_videos.py, which is a test file and not code this\n   test exercises. It was read and has no bearing on this verdict.\n2. `fixtures_path` was not supplied. The test uses only pytest's built-in `tmp_path` and defines its\n   own helpers, so no conftest was needed. The symbols it imports exist:\n   ensure_interaction_event_schema at engine/server/data/interaction_events.py:19, and\n   fetch_popular_videos at engine/server/data/random_videos.py:195. So do the interaction_signals\n   columns written at line 72, at interaction_events.py:42-51.\n3. Anti-patterns pass (rules/shape.md): no entry matches.\n   - doc-lint-grep, section-scoped-substring-grep, whole-file-source-name-grep: the test reads no\n     document and does no substring check.\n   - hardcoded-spec-mirror: CAP at line 30 is compared with no code constant. The test only uses it\n     to build inputs.\n   - tautological-assertion: the expected values at lines 80 and 90 are written-down orderings, not\n     worked out the way the code works them out.\n   - absence-only-assertion: every assertion is a positive equality.\n   - echoed-literal: line 82 gets SIGNAL back, but through the production SELECT in\n     fetch_popular_videos, and it is a control that sits next to the order assertions rather than\n     standing alone.\n   - single-value-pin: the ranking is read at six input pairs (lines 78 and 86), each checked under\n     two thresholds, so an output that ignored its input would fail at least one.\n4. Ladder pass (rules/shape.md <ladder>): rung 1. The test calls fetch_popular_videos directly and\n   asserts on the rows it returns. That is the highest rung for a ranking invariant, so there is no\n   downshift and no comment is needed. It is not on the anti-rung.\n5. Stub question: the unchanged code ranks signal 1000 first and fails line 80. Dropping the signal\n   altogether, or capping at 24 or less, fails the (CAP - 0.5) case at line 86. Capping at 26 or more\n   fails the (CAP + 0.5) case. Adding a flat cap bonus for any signal fails the (SUB_CAP_SIGNAL, 15.0)\n   case. A hard-coded order cannot satisfy both the leader-first and trailer-first cases at line 86.\n   The test fails against each of these wrong implementations, so it works as a gate.\n```\n\n### devsecops-test-claim-auditor\n\nCLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (11 clauses: 2 must_prove, 7 docstring, 2 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | signal 1000 / popularity 0 ranks below popularity 30 / no signal, without an error threshold | :80 (threshold=None pass of the :76 loop) | adding the signal with no cap (0+1000 > 30 would put `first` first) | CARRIED |\n| C1b | must_prove | the same order with an error threshold | :80 (threshold=1 pass of the :76 loop) | a cap applied only in the no-threshold branch; a query that breaks when `error_clause` and its param are added | CARRIED |\n| D1a | docstring | \"adds a video's interaction signal only up to a cap of 25\": the cap is 25 | :90 (cases `CAP - 0.5`, `CAP + 0.5`, both thresholds) | any cap of 24.5 or less (including a dropped signal) and any cap of 25.5 or more, so every integer cap other than 25. Docstring :4 gives the half-point tolerance itself | CARRIED |\n| D1b | docstring | \"adds ... up to a cap\": a signal below the cap is added in full | :90 (cases `SUB_CAP_SIGNAL` against 5.0 and 15.0, both thresholds) | a flat cap-sized bonus for any positive signal (25 > 15), and a dropped sub-cap signal (0 < 5) | CARRIED |\n| D2 | docstring | \"ranks ... below a video with popularity 30 and no signal\" | :80 | uncapped addition | CARRIED |\n| D3 | docstring | withdrawn | n/a | n/a | CARRIED |\n| D4 | docstring | \"with and without an error threshold\" | :76, :80, :82, :90 | behaviour that differs between the two branches | CARRIED |\n| D5 | docstring | \"the row still reports the raw signal of 1000\" | :82 | returning the capped value in `interaction_signal_score` | CARRIED |\n| D6 | docstring | \"a temporary copy of two real videos out of `whitelist.db`\" | :44 | a fixture that silently copies fewer than two videos | CARRIED |\n| N1 | name | `the_popular_order_caps_the_interaction_signal` | :80, :90 | uncapped addition (:80); a cap anywhere other than 25 \u00b1 0.5 (:90) | CARRIED |\n| N2 | name | module name `test_13_deterministic_event_ids_phase1`: \"deterministic event ids\" | n/a | n/a | EXEMPT |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nOBSERVATIONS\n1. whole-claim (rules/testing.md): D3 at tests/tmp/test_13_deterministic_event_ids_phase1.py:1-5. The first-audit sentence \"and above one with popularity 20\" is no longer in the docstring, so under `<re_audit>` rule 4 the row is recorded as withdrawn. This was a replacement, not a retreat. Docstring :4 now claims a stronger bound (\"ranks above popularity 24.5\"), and :90 asserts it (`(SIGNAL, CAP - 0.5, first, second)`). That bound implies the one that was dropped.\n2. whole-claim (rules/testing.md): D1b at tests/tmp/test_13_deterministic_event_ids_phase1.py:86/:90. \"Counts in full\" is only pinned to the range (5, 15). A signal scaled before it is capped, such as `min(0.6 * signal, 25)`, gives 6 for a signal of 10 and passes both sub-cap cases. It also passes the 24.5/25.5 cases. Docstring :5 describes exactly the range it checks (\"ranks above popularity 5 and below popularity 15\"), so the prose and the assertion agree. Checking against 9.5 and 10.5 would pin \"in full\" as tightly as :4 pins the cap.\n3. normal-and-abnormal-paths (rules/testing.md): tests/tmp/test_13_deterministic_event_ids_phase1.py:59/:61. The threshold=1 pass always sets `error_count = 0` on both rows, so the error threshold never excludes a row. Nothing shows that the capped order still holds when the threshold filters out one of the ranked videos.\n4. bounds (rules/testing.md): tests/tmp/test_13_deterministic_event_ids_phase1.py:86. The signals tested are 1000, 10 and 0, the last being the unsignalled `second`. There is no case for a signal exactly at the cap (25) or at zero on a row that has an `interaction_signals` entry.\n\nNOT ASSESSED\n1. `fixtures_path` was none, and the test defines its own helpers (`_two_video_db`, `_set_popularity`, `_set_signal`) and uses only pytest's built-in `tmp_path`, so there is no conftest to read. The contents of `engine/server/db/whitelist.db` were not read. D6 was judged from the `assert len(picks) == 2` guard at :44.",
        "map": [
          {
            "id": "C1a",
            "source": "must_prove",
            "clause": "signal 1000 / popularity 0 ranks below popularity 30 / no signal, without an error threshold",
            "assertion": ":80 (threshold=None pass of the :76 loop)",
            "excludes": "adding the signal with no cap (0+1000 > 30 would put `first` first)",
            "status": "CARRIED"
          },
          {
            "id": "C1b",
            "source": "must_prove",
            "clause": "the same order with an error threshold",
            "assertion": ":80 (threshold=1 pass of the :76 loop)",
            "excludes": "a cap applied only in the no-threshold branch; a query that breaks when `error_clause` and its param are added",
            "status": "CARRIED"
          },
          {
            "id": "D1a",
            "source": "docstring",
            "clause": "\"adds a video's interaction signal only up to a cap of 25\": the cap is 25",
            "assertion": ":90 (cases `CAP - 0.5`, `CAP + 0.5`, both thresholds)",
            "excludes": "any cap of 24.5 or less (including a dropped signal) and any cap of 25.5 or more, so every integer cap other than 25. Docstring :4 gives the half-point tolerance itself",
            "status": "CARRIED"
          },
          {
            "id": "D1b",
            "source": "docstring",
            "clause": "\"adds ... up to a cap\": a signal below the cap is added in full",
            "assertion": ":90 (cases `SUB_CAP_SIGNAL` against 5.0 and 15.0, both thresholds)",
            "excludes": "a flat cap-sized bonus for any positive signal (25 > 15), and a dropped sub-cap signal (0 < 5)",
            "status": "CARRIED"
          },
          {
            "id": "D2",
            "source": "docstring",
            "clause": "\"ranks ... below a video with popularity 30 and no signal\"",
            "assertion": ":80",
            "excludes": "uncapped addition",
            "status": "CARRIED"
          },
          {
            "id": "D3",
            "source": "docstring",
            "clause": "withdrawn",
            "assertion": "n/a",
            "excludes": "n/a",
            "status": "CARRIED"
          },
          {
            "id": "D4",
            "source": "docstring",
            "clause": "\"with and without an error threshold\"",
            "assertion": ":76, :80, :82, :90",
            "excludes": "behaviour that differs between the two branches",
            "status": "CARRIED"
          },
          {
            "id": "D5",
            "source": "docstring",
            "clause": "\"the row still reports the raw signal of 1000\"",
            "assertion": ":82",
            "excludes": "returning the capped value in `interaction_signal_score`",
            "status": "CARRIED"
          },
          {
            "id": "D6",
            "source": "docstring",
            "clause": "\"a temporary copy of two real videos out of `whitelist.db`\"",
            "assertion": ":44",
            "excludes": "a fixture that silently copies fewer than two videos",
            "status": "CARRIED"
          },
          {
            "id": "N1",
            "source": "name",
            "clause": "`the_popular_order_caps_the_interaction_signal`",
            "assertion": ":80, :90",
            "excludes": "uncapped addition (:80); a cap anywhere other than 25 \u00b1 0.5 (:90)",
            "status": "CARRIED"
          },
          {
            "id": "N2",
            "source": "name",
            "clause": "module name `test_13_deterministic_event_ids_phase1`: \"deterministic event ids\"",
            "assertion": "n/a",
            "excludes": "n/a",
            "status": "EXEMPT"
          }
        ],
        "map_problem": ""
      }
    ],
    "tests/tmp/test_13_deterministic_event_ids_phase2.py": [
      {
        "shape": "```\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\nFails at line 140 in test_a_repeated_like_publishes_one_like_and_a_bridge_retry_of_it_is_a_duplicate.\nThe published event types come out as [\"Like\", \"Like\"] instead of [\"Like\"], because the handler\nat client/backend/server.py:784 sets `publish = action in (\"like\", \"undo_like\")` and so publishes\non every like. Every test that compares an id to `_event_id` (for example line 174) fails on its\nown terms, since server.py:802 still mints `f\"client-{uuid4()}\"`.\n\nNOT ASSESSED\n1. `code_under_test` listed tests/active/test_event_ids.py (NEW), which does not resolve. It had\n   no part in the assessment.\n2. client/backend/lib/users_store.py was read only as far as its function signatures and any\n   `generation` symbol, of which there is none yet. The stub question was answered from the\n   assertion form and the server.py publish path (lines 760-830).\n3. `fixtures_path` was \"none found\". The fixtures the test uses (`rig`, `_serving`) are defined\n   in the test file. `ClientBackend`, `RateLimiter`, `ensure_user_schema` and `client_server`\n   were traced to tests/active/conftest.py lines 39-47, and `ingest_interaction_event` to\n   engine/server/data/interaction_events.py:57. Their bodies were not read beyond those lines.\n```",
        "claim": "CLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (54 clauses: 12 must_prove, 29 docstring, 13 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | a repeat like of a video the profile already likes publishes nothing | :140 | publishing a Like on every `like` action | CARRIED |\n| C1b | must_prove | undo_like of a video with no published like publishes nothing | :181 | publishing an UndoLike on every `undo_like` | CARRIED |\n| C1c | must_prove | a dislike of a video the profile does not like publishes nothing | :197 | publishing on a dislike that removed no like | CARRIED |\n| C1d | must_prove | undo_dislike of a video the profile does not like publishes nothing | :197 | publishing on undo_dislike (the count stays 2 after both actions) | CARRIED |\n| C1e | must_prove | re-like after a reset, while the published like is still open, publishes nothing | :208 | deciding to publish from the stored like instead of the published one | CARRIED |\n| C1f | must_prove | undo_like of an imported (never published) like publishes nothing | :222 | publishing an UndoLike because a stored like was removed | CARRIED |\n| C2a | must_prove | id is `client-` + SHA-256 hex of the JSON list | :142 | a `client-{uuid4}` id or any other hash or encoding | CARRIED |\n| C2b | must_prove | actor in the hashed list (profile id / `anonymous`) | :142, :162 | leaving out the actor, or using some other actor string | CARRIED |\n| C2c | must_prove | canonical uuid in the hashed list | :174 | hashing the upper-case uuid as sent | CARRIED |\n| C2d | must_prove | canonical host in the hashed list | :174 | hashing `IDS.Example` as sent | CARRIED |\n| C2e | must_prove | event type in the hashed list | :155 | Like and UndoLike at generation 1 sharing one id | CARRIED |\n| C2f | must_prove | like generation in the hashed list | :154, :155, :162 | a re-like after an undo reusing generation 1; anonymous not at 0 | CARRIED |\n| D1 | docstring | \"publishes a Like or UndoLike only when it opens or closes\" the like | :140, :153, :181, :191, :197 | publishing on no-op actions, or failing to publish on real open/close | CARRIED |\n| D2 | docstring | \"every published event's id is `client-` plus the SHA-256 of\u2026\" | :142, :155, :162, :174 | any id other than the derived one | CARRIED |\n| D3 | docstring | \"Two likes \u2026 publish one Like\" | :140 | a Like per action | CARRIED |\n| D4 | docstring | \"at generation 1\" | :142 | generation 0 or 2 on the first like | CARRIED |\n| D5 | docstring | \"the video's signal is (1, 1.0)\" | :141 | the Engine counting two likes | CARRIED |\n| D6 | docstring | \"re-ingesting that Like's payload unchanged, as a bridge retry does, is a duplicate\" | :144 | nothing: the test re-sends the dict it recorded, so the same `event_id` collides with itself under any id scheme, `uuid4` included | UNCARRIED |\n| D7 | docstring | \"and leaves (1, 1.0)\" | :145 | nothing beyond D6: once the re-ingest is a duplicate, the signal cannot move | UNCARRIED |\n| D8 | docstring | \"publishes Like, UndoLike, Like at generations 1, 1 and 2\" | :155 | wrong order, or wrong generation on any of the three | CARRIED |\n| D9 | docstring | \"the two Like ids differ\" | :154 | a re-like reusing the first Like's id | CARRIED |\n| D10 | docstring | \"the signal ends at (1, 1.0)\" | :156 | the re-like collapsed as a duplicate (signal 0) | CARRIED |\n| D11 | docstring | \"Two anonymous likes both publish the Like id for actor `anonymous` at generation 0\" | :162 | a per-request id, or a generation other than 0 | CARRIED |\n| D12 | docstring | \"the Engine counts the second as a duplicate\" | :163 | distinct ids for the two anonymous likes | CARRIED |\n| D13 | docstring | \"the signal is (1, 1.0)\" | :164 | the Engine counting two | CARRIED |\n| D14 | docstring | id \"over the uuid and host the Engine resolved them to, not over the spelling sent\" | :174 (controls :172\u2013173) | hashing the request's spelling | CARRIED |\n| D15 | docstring | \"undo_like of a video the profile never liked answers 200\" | :180 | a 4xx/5xx on the no-op undo | CARRIED |\n| D16 | docstring | \"and publishes nothing\" | :181 | publishing an UndoLike | CARRIED |\n| D17 | docstring | \"a like afterwards publishes at generation 1\" | :184 | the refused undo moving the generation forward | CARRIED |\n| D18 | docstring | \"A dislike replacing a like publishes the UndoLike id an undo_like would have used (generation 1)\" | :192 | a different id or generation on the dislike's withdrawal | CARRIED |\n| D19 | docstring | \"and leaves (0, 0.0)\" | :193 | the withdrawal not reaching the signal | CARRIED |\n| D20 | docstring | \"a dislike \u2026 of a video the profile does not like publish[es] nothing\" | :197 | publishing on that dislike | CARRIED |\n| D21 | docstring | \"and an undo_dislike \u2026 publish[es] nothing\" | :197 | publishing on that undo_dislike | CARRIED |\n| D22 | docstring | \"like, reset, like publishes one Like\" | :208 | the re-like or the reset publishing | CARRIED |\n| D23 | docstring | \"though the re-like is stored\" | :207 | the re-like being refused rather than stored and left unpublished | CARRIED |\n| D24 | docstring | \"the undo_like after it publishes that Like's UndoLike\" | :210, :212 | an UndoLike at generation 2, or none | CARRIED |\n| D25 | docstring | \"and leaves (0, 0.0)\" | :211 | the UndoLike missing the first Like's generation | CARRIED |\n| D26 | docstring | \"undo_like of an imported like publishes nothing\" | :222 | publishing on removal of an imported like | CARRIED |\n| D27 | docstring | \"though the import stored the like\" | :219 | an import that stored nothing, which would make the undo a trivial no-op | CARRIED |\n| D28 | docstring | \"and the undo removed it\" | :221 | the undo being refused instead of applied without publishing | CARRIED |\n| D29 | docstring | \"a like afterwards publishes at generation 1\" | :225 | the import or the undo consuming a generation | CARRIED |\n| N1a | name | \"a repeated like publishes one like\" | :140 | a Like per action | CARRIED |\n| N1b | name | \"a bridge retry of it is a duplicate\" | :144 | nothing: the retry is simulated by re-sending the recorded payload, which is a duplicate whatever the id scheme | UNCARRIED |\n| N2 | name | \"like, undo_like, like publishes Like, UndoLike, Like under generations 1, 1, 2\" | :155 | wrong sequence or generations | CARRIED |\n| N3a | name | \"two anonymous likes carry one id\" | :162 | a per-request anonymous id | CARRIED |\n| N3b | name | \"the engine counts the second as a duplicate\" | :163 | a second non-duplicate ingest | CARRIED |\n| N4 | name | \"a like named in a non-canonical spelling derives its id from the resolved identity\" | :174 | hashing the spelling sent | CARRIED |\n| N5a | name | \"an undo_like of an unliked video answers 200\" | :180 | an error status | CARRIED |\n| N5b | name | \"and publishes nothing\" | :181 | publishing an UndoLike | CARRIED |\n| N6a | name | \"a dislike replacing a like publishes the undo_like's id\" | :192 | a different id on the withdrawal | CARRIED |\n| N6b | name | \"one of an unliked video publishes nothing\" | :197 | publishing on that dislike | CARRIED |\n| N7a | name | \"a like after a reset publishes nothing\" | :208 | the re-like publishing | CARRIED |\n| N7b | name | \"the next undo_like withdraws the first\" | :212 | an UndoLike at the re-like's generation | CARRIED |\n| N8 | name | \"an undo_like of an imported like publishes nothing\" | :222 | publishing on removal of an imported like | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. whole-claim (rules/testing.md): tests/tmp/test_13_deterministic_event_ids_phase2.py:143\u2013145\n   `retry = ingest_interaction_event(rig.engine_db, rig.events[0][0])`\n   D6, D7 and N1b are UNCARRIED. The test hands the Engine's ingest the same dict object the Client already sent. That dict collides with itself under any id scheme, including the `client-{uuid4}` ids that C2 replaces, so these lines exclude no wrong implementation. They are tagged `# C2`, but C2 is carried by the equality at :142, not by them. To carry the clause, drive a real re-publish of the same action through the Client and assert that the id matches. The other option is to narrow the name and the docstring to what :142 already proves.\n2. normal-and-abnormal-paths (rules/testing.md): tests/tmp/test_13_deterministic_event_ids_phase2.py:79\u201384\n   The stub's ingest always answers `{\"ok\": True}`, so every test takes the success path. No test covers a publish the bridge rejects: what the action answers, and whether the next attempt at the same like reuses the id and generation or moves on.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `code_under_test` lists tests/active/test_event_ids.py (NEW), but that file does not exist.\n2. client/backend/lib/users_store.py was not read in full. The server handlers and the imported symbols it relies on were checked (`/api/user-action`, `/api/profile/reaction`, `/api/user-profile/reset`, `/api/profile/likes/import`, `ensure_user_schema`). The id's `generation` input has no definition anywhere under client/backend yet, so bounds on it were judged from the test alone.\n3. `fixtures_path` was not supplied. The test imports its harness from tests/active/conftest.py (`ClientBackend`, `RateLimiter`, `client_server`, `ensure_user_schema`), and that file was read; the `rig` fixture is defined in the test file itself.",
        "body": "### devsecops-test-shape-auditor\n\n```\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\nFails at line 140 in test_a_repeated_like_publishes_one_like_and_a_bridge_retry_of_it_is_a_duplicate.\nThe published event types come out as [\"Like\", \"Like\"] instead of [\"Like\"], because the handler\nat client/backend/server.py:784 sets `publish = action in (\"like\", \"undo_like\")` and so publishes\non every like. Every test that compares an id to `_event_id` (for example line 174) fails on its\nown terms, since server.py:802 still mints `f\"client-{uuid4()}\"`.\n\nNOT ASSESSED\n1. `code_under_test` listed tests/active/test_event_ids.py (NEW), which does not resolve. It had\n   no part in the assessment.\n2. client/backend/lib/users_store.py was read only as far as its function signatures and any\n   `generation` symbol, of which there is none yet. The stub question was answered from the\n   assertion form and the server.py publish path (lines 760-830).\n3. `fixtures_path` was \"none found\". The fixtures the test uses (`rig`, `_serving`) are defined\n   in the test file. `ClientBackend`, `RateLimiter`, `ensure_user_schema` and `client_server`\n   were traced to tests/active/conftest.py lines 39-47, and `ingest_interaction_event` to\n   engine/server/data/interaction_events.py:57. Their bodies were not read beyond those lines.\n```\n\n### devsecops-test-claim-auditor\n\nCLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (54 clauses: 12 must_prove, 29 docstring, 13 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | a repeat like of a video the profile already likes publishes nothing | :140 | publishing a Like on every `like` action | CARRIED |\n| C1b | must_prove | undo_like of a video with no published like publishes nothing | :181 | publishing an UndoLike on every `undo_like` | CARRIED |\n| C1c | must_prove | a dislike of a video the profile does not like publishes nothing | :197 | publishing on a dislike that removed no like | CARRIED |\n| C1d | must_prove | undo_dislike of a video the profile does not like publishes nothing | :197 | publishing on undo_dislike (the count stays 2 after both actions) | CARRIED |\n| C1e | must_prove | re-like after a reset, while the published like is still open, publishes nothing | :208 | deciding to publish from the stored like instead of the published one | CARRIED |\n| C1f | must_prove | undo_like of an imported (never published) like publishes nothing | :222 | publishing an UndoLike because a stored like was removed | CARRIED |\n| C2a | must_prove | id is `client-` + SHA-256 hex of the JSON list | :142 | a `client-{uuid4}` id or any other hash or encoding | CARRIED |\n| C2b | must_prove | actor in the hashed list (profile id / `anonymous`) | :142, :162 | leaving out the actor, or using some other actor string | CARRIED |\n| C2c | must_prove | canonical uuid in the hashed list | :174 | hashing the upper-case uuid as sent | CARRIED |\n| C2d | must_prove | canonical host in the hashed list | :174 | hashing `IDS.Example` as sent | CARRIED |\n| C2e | must_prove | event type in the hashed list | :155 | Like and UndoLike at generation 1 sharing one id | CARRIED |\n| C2f | must_prove | like generation in the hashed list | :154, :155, :162 | a re-like after an undo reusing generation 1; anonymous not at 0 | CARRIED |\n| D1 | docstring | \"publishes a Like or UndoLike only when it opens or closes\" the like | :140, :153, :181, :191, :197 | publishing on no-op actions, or failing to publish on real open/close | CARRIED |\n| D2 | docstring | \"every published event's id is `client-` plus the SHA-256 of\u2026\" | :142, :155, :162, :174 | any id other than the derived one | CARRIED |\n| D3 | docstring | \"Two likes \u2026 publish one Like\" | :140 | a Like per action | CARRIED |\n| D4 | docstring | \"at generation 1\" | :142 | generation 0 or 2 on the first like | CARRIED |\n| D5 | docstring | \"the video's signal is (1, 1.0)\" | :141 | the Engine counting two likes | CARRIED |\n| D6 | docstring | \"re-ingesting that Like's payload unchanged, as a bridge retry does, is a duplicate\" | :144 | nothing: the test re-sends the dict it recorded, so the same `event_id` collides with itself under any id scheme, `uuid4` included | UNCARRIED |\n| D7 | docstring | \"and leaves (1, 1.0)\" | :145 | nothing beyond D6: once the re-ingest is a duplicate, the signal cannot move | UNCARRIED |\n| D8 | docstring | \"publishes Like, UndoLike, Like at generations 1, 1 and 2\" | :155 | wrong order, or wrong generation on any of the three | CARRIED |\n| D9 | docstring | \"the two Like ids differ\" | :154 | a re-like reusing the first Like's id | CARRIED |\n| D10 | docstring | \"the signal ends at (1, 1.0)\" | :156 | the re-like collapsed as a duplicate (signal 0) | CARRIED |\n| D11 | docstring | \"Two anonymous likes both publish the Like id for actor `anonymous` at generation 0\" | :162 | a per-request id, or a generation other than 0 | CARRIED |\n| D12 | docstring | \"the Engine counts the second as a duplicate\" | :163 | distinct ids for the two anonymous likes | CARRIED |\n| D13 | docstring | \"the signal is (1, 1.0)\" | :164 | the Engine counting two | CARRIED |\n| D14 | docstring | id \"over the uuid and host the Engine resolved them to, not over the spelling sent\" | :174 (controls :172\u2013173) | hashing the request's spelling | CARRIED |\n| D15 | docstring | \"undo_like of a video the profile never liked answers 200\" | :180 | a 4xx/5xx on the no-op undo | CARRIED |\n| D16 | docstring | \"and publishes nothing\" | :181 | publishing an UndoLike | CARRIED |\n| D17 | docstring | \"a like afterwards publishes at generation 1\" | :184 | the refused undo moving the generation forward | CARRIED |\n| D18 | docstring | \"A dislike replacing a like publishes the UndoLike id an undo_like would have used (generation 1)\" | :192 | a different id or generation on the dislike's withdrawal | CARRIED |\n| D19 | docstring | \"and leaves (0, 0.0)\" | :193 | the withdrawal not reaching the signal | CARRIED |\n| D20 | docstring | \"a dislike \u2026 of a video the profile does not like publish[es] nothing\" | :197 | publishing on that dislike | CARRIED |\n| D21 | docstring | \"and an undo_dislike \u2026 publish[es] nothing\" | :197 | publishing on that undo_dislike | CARRIED |\n| D22 | docstring | \"like, reset, like publishes one Like\" | :208 | the re-like or the reset publishing | CARRIED |\n| D23 | docstring | \"though the re-like is stored\" | :207 | the re-like being refused rather than stored and left unpublished | CARRIED |\n| D24 | docstring | \"the undo_like after it publishes that Like's UndoLike\" | :210, :212 | an UndoLike at generation 2, or none | CARRIED |\n| D25 | docstring | \"and leaves (0, 0.0)\" | :211 | the UndoLike missing the first Like's generation | CARRIED |\n| D26 | docstring | \"undo_like of an imported like publishes nothing\" | :222 | publishing on removal of an imported like | CARRIED |\n| D27 | docstring | \"though the import stored the like\" | :219 | an import that stored nothing, which would make the undo a trivial no-op | CARRIED |\n| D28 | docstring | \"and the undo removed it\" | :221 | the undo being refused instead of applied without publishing | CARRIED |\n| D29 | docstring | \"a like afterwards publishes at generation 1\" | :225 | the import or the undo consuming a generation | CARRIED |\n| N1a | name | \"a repeated like publishes one like\" | :140 | a Like per action | CARRIED |\n| N1b | name | \"a bridge retry of it is a duplicate\" | :144 | nothing: the retry is simulated by re-sending the recorded payload, which is a duplicate whatever the id scheme | UNCARRIED |\n| N2 | name | \"like, undo_like, like publishes Like, UndoLike, Like under generations 1, 1, 2\" | :155 | wrong sequence or generations | CARRIED |\n| N3a | name | \"two anonymous likes carry one id\" | :162 | a per-request anonymous id | CARRIED |\n| N3b | name | \"the engine counts the second as a duplicate\" | :163 | a second non-duplicate ingest | CARRIED |\n| N4 | name | \"a like named in a non-canonical spelling derives its id from the resolved identity\" | :174 | hashing the spelling sent | CARRIED |\n| N5a | name | \"an undo_like of an unliked video answers 200\" | :180 | an error status | CARRIED |\n| N5b | name | \"and publishes nothing\" | :181 | publishing an UndoLike | CARRIED |\n| N6a | name | \"a dislike replacing a like publishes the undo_like's id\" | :192 | a different id on the withdrawal | CARRIED |\n| N6b | name | \"one of an unliked video publishes nothing\" | :197 | publishing on that dislike | CARRIED |\n| N7a | name | \"a like after a reset publishes nothing\" | :208 | the re-like publishing | CARRIED |\n| N7b | name | \"the next undo_like withdraws the first\" | :212 | an UndoLike at the re-like's generation | CARRIED |\n| N8 | name | \"an undo_like of an imported like publishes nothing\" | :222 | publishing on removal of an imported like | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. whole-claim (rules/testing.md): tests/tmp/test_13_deterministic_event_ids_phase2.py:143\u2013145\n   `retry = ingest_interaction_event(rig.engine_db, rig.events[0][0])`\n   D6, D7 and N1b are UNCARRIED. The test hands the Engine's ingest the same dict object the Client already sent. That dict collides with itself under any id scheme, including the `client-{uuid4}` ids that C2 replaces, so these lines exclude no wrong implementation. They are tagged `# C2`, but C2 is carried by the equality at :142, not by them. To carry the clause, drive a real re-publish of the same action through the Client and assert that the id matches. The other option is to narrow the name and the docstring to what :142 already proves.\n2. normal-and-abnormal-paths (rules/testing.md): tests/tmp/test_13_deterministic_event_ids_phase2.py:79\u201384\n   The stub's ingest always answers `{\"ok\": True}`, so every test takes the success path. No test covers a publish the bridge rejects: what the action answers, and whether the next attempt at the same like reuses the id and generation or moves on.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `code_under_test` lists tests/active/test_event_ids.py (NEW), but that file does not exist.\n2. client/backend/lib/users_store.py was not read in full. The server handlers and the imported symbols it relies on were checked (`/api/user-action`, `/api/profile/reaction`, `/api/user-profile/reset`, `/api/profile/likes/import`, `ensure_user_schema`). The id's `generation` input has no definition anywhere under client/backend yet, so bounds on it were judged from the test alone.\n3. `fixtures_path` was not supplied. The test imports its harness from tests/active/conftest.py (`ClientBackend`, `RateLimiter`, `client_server`, `ensure_user_schema`), and that file was read; the `rig` fixture is defined in the test file itself.",
        "map": [
          {
            "id": "C1a",
            "source": "must_prove",
            "clause": "a repeat like of a video the profile already likes publishes nothing",
            "assertion": ":140",
            "excludes": "publishing a Like on every `like` action",
            "status": "CARRIED"
          },
          {
            "id": "C1b",
            "source": "must_prove",
            "clause": "undo_like of a video with no published like publishes nothing",
            "assertion": ":181",
            "excludes": "publishing an UndoLike on every `undo_like`",
            "status": "CARRIED"
          },
          {
            "id": "C1c",
            "source": "must_prove",
            "clause": "a dislike of a video the profile does not like publishes nothing",
            "assertion": ":197",
            "excludes": "publishing on a dislike that removed no like",
            "status": "CARRIED"
          },
          {
            "id": "C1d",
            "source": "must_prove",
            "clause": "undo_dislike of a video the profile does not like publishes nothing",
            "assertion": ":197",
            "excludes": "publishing on undo_dislike (the count stays 2 after both actions)",
            "status": "CARRIED"
          },
          {
            "id": "C1e",
            "source": "must_prove",
            "clause": "re-like after a reset, while the published like is still open, publishes nothing",
            "assertion": ":208",
            "excludes": "deciding to publish from the stored like instead of the published one",
            "status": "CARRIED"
          },
          {
            "id": "C1f",
            "source": "must_prove",
            "clause": "undo_like of an imported (never published) like publishes nothing",
            "assertion": ":222",
            "excludes": "publishing an UndoLike because a stored like was removed",
            "status": "CARRIED"
          },
          {
            "id": "C2a",
            "source": "must_prove",
            "clause": "id is `client-` + SHA-256 hex of the JSON list",
            "assertion": ":142",
            "excludes": "a `client-{uuid4}` id or any other hash or encoding",
            "status": "CARRIED"
          },
          {
            "id": "C2b",
            "source": "must_prove",
            "clause": "actor in the hashed list (profile id / `anonymous`)",
            "assertion": ":142, :162",
            "excludes": "leaving out the actor, or using some other actor string",
            "status": "CARRIED"
          },
          {
            "id": "C2c",
            "source": "must_prove",
            "clause": "canonical uuid in the hashed list",
            "assertion": ":174",
            "excludes": "hashing the upper-case uuid as sent",
            "status": "CARRIED"
          },
          {
            "id": "C2d",
            "source": "must_prove",
            "clause": "canonical host in the hashed list",
            "assertion": ":174",
            "excludes": "hashing `IDS.Example` as sent",
            "status": "CARRIED"
          },
          {
            "id": "C2e",
            "source": "must_prove",
            "clause": "event type in the hashed list",
            "assertion": ":155",
            "excludes": "Like and UndoLike at generation 1 sharing one id",
            "status": "CARRIED"
          },
          {
            "id": "C2f",
            "source": "must_prove",
            "clause": "like generation in the hashed list",
            "assertion": ":154, :155, :162",
            "excludes": "a re-like after an undo reusing generation 1; anonymous not at 0",
            "status": "CARRIED"
          },
          {
            "id": "D1",
            "source": "docstring",
            "clause": "\"publishes a Like or UndoLike only when it opens or closes\" the like",
            "assertion": ":140, :153, :181, :191, :197",
            "excludes": "publishing on no-op actions, or failing to publish on real open/close",
            "status": "CARRIED"
          },
          {
            "id": "D2",
            "source": "docstring",
            "clause": "\"every published event's id is `client-` plus the SHA-256 of\u2026\"",
            "assertion": ":142, :155, :162, :174",
            "excludes": "any id other than the derived one",
            "status": "CARRIED"
          },
          {
            "id": "D3",
            "source": "docstring",
            "clause": "\"Two likes \u2026 publish one Like\"",
            "assertion": ":140",
            "excludes": "a Like per action",
            "status": "CARRIED"
          },
          {
            "id": "D4",
            "source": "docstring",
            "clause": "\"at generation 1\"",
            "assertion": ":142",
            "excludes": "generation 0 or 2 on the first like",
            "status": "CARRIED"
          },
          {
            "id": "D5",
            "source": "docstring",
            "clause": "\"the video's signal is (1, 1.0)\"",
            "assertion": ":141",
            "excludes": "the Engine counting two likes",
            "status": "CARRIED"
          },
          {
            "id": "D6",
            "source": "docstring",
            "clause": "\"re-ingesting that Like's payload unchanged, as a bridge retry does, is a duplicate\"",
            "assertion": ":144",
            "excludes": "nothing: the test re-sends the dict it recorded, so the same `event_id` collides with itself under any id scheme, `uuid4` included",
            "status": "UNCARRIED"
          },
          {
            "id": "D7",
            "source": "docstring",
            "clause": "\"and leaves (1, 1.0)\"",
            "assertion": ":145",
            "excludes": "nothing beyond D6: once the re-ingest is a duplicate, the signal cannot move",
            "status": "UNCARRIED"
          },
          {
            "id": "D8",
            "source": "docstring",
            "clause": "\"publishes Like, UndoLike, Like at generations 1, 1 and 2\"",
            "assertion": ":155",
            "excludes": "wrong order, or wrong generation on any of the three",
            "status": "CARRIED"
          },
          {
            "id": "D9",
            "source": "docstring",
            "clause": "\"the two Like ids differ\"",
            "assertion": ":154",
            "excludes": "a re-like reusing the first Like's id",
            "status": "CARRIED"
          },
          {
            "id": "D10",
            "source": "docstring",
            "clause": "\"the signal ends at (1, 1.0)\"",
            "assertion": ":156",
            "excludes": "the re-like collapsed as a duplicate (signal 0)",
            "status": "CARRIED"
          },
          {
            "id": "D11",
            "source": "docstring",
            "clause": "\"Two anonymous likes both publish the Like id for actor `anonymous` at generation 0\"",
            "assertion": ":162",
            "excludes": "a per-request id, or a generation other than 0",
            "status": "CARRIED"
          },
          {
            "id": "D12",
            "source": "docstring",
            "clause": "\"the Engine counts the second as a duplicate\"",
            "assertion": ":163",
            "excludes": "distinct ids for the two anonymous likes",
            "status": "CARRIED"
          },
          {
            "id": "D13",
            "source": "docstring",
            "clause": "\"the signal is (1, 1.0)\"",
            "assertion": ":164",
            "excludes": "the Engine counting two",
            "status": "CARRIED"
          },
          {
            "id": "D14",
            "source": "docstring",
            "clause": "id \"over the uuid and host the Engine resolved them to, not over the spelling sent\"",
            "assertion": ":174 (controls :172\u2013173)",
            "excludes": "hashing the request's spelling",
            "status": "CARRIED"
          },
          {
            "id": "D15",
            "source": "docstring",
            "clause": "\"undo_like of a video the profile never liked answers 200\"",
            "assertion": ":180",
            "excludes": "a 4xx/5xx on the no-op undo",
            "status": "CARRIED"
          },
          {
            "id": "D16",
            "source": "docstring",
            "clause": "\"and publishes nothing\"",
            "assertion": ":181",
            "excludes": "publishing an UndoLike",
            "status": "CARRIED"
          },
          {
            "id": "D17",
            "source": "docstring",
            "clause": "\"a like afterwards publishes at generation 1\"",
            "assertion": ":184",
            "excludes": "the refused undo moving the generation forward",
            "status": "CARRIED"
          },
          {
            "id": "D18",
            "source": "docstring",
            "clause": "\"A dislike replacing a like publishes the UndoLike id an undo_like would have used (generation 1)\"",
            "assertion": ":192",
            "excludes": "a different id or generation on the dislike's withdrawal",
            "status": "CARRIED"
          },
          {
            "id": "D19",
            "source": "docstring",
            "clause": "\"and leaves (0, 0.0)\"",
            "assertion": ":193",
            "excludes": "the withdrawal not reaching the signal",
            "status": "CARRIED"
          },
          {
            "id": "D20",
            "source": "docstring",
            "clause": "\"a dislike \u2026 of a video the profile does not like publish[es] nothing\"",
            "assertion": ":197",
            "excludes": "publishing on that dislike",
            "status": "CARRIED"
          },
          {
            "id": "D21",
            "source": "docstring",
            "clause": "\"and an undo_dislike \u2026 publish[es] nothing\"",
            "assertion": ":197",
            "excludes": "publishing on that undo_dislike",
            "status": "CARRIED"
          },
          {
            "id": "D22",
            "source": "docstring",
            "clause": "\"like, reset, like publishes one Like\"",
            "assertion": ":208",
            "excludes": "the re-like or the reset publishing",
            "status": "CARRIED"
          },
          {
            "id": "D23",
            "source": "docstring",
            "clause": "\"though the re-like is stored\"",
            "assertion": ":207",
            "excludes": "the re-like being refused rather than stored and left unpublished",
            "status": "CARRIED"
          },
          {
            "id": "D24",
            "source": "docstring",
            "clause": "\"the undo_like after it publishes that Like's UndoLike\"",
            "assertion": ":210, :212",
            "excludes": "an UndoLike at generation 2, or none",
            "status": "CARRIED"
          },
          {
            "id": "D25",
            "source": "docstring",
            "clause": "\"and leaves (0, 0.0)\"",
            "assertion": ":211",
            "excludes": "the UndoLike missing the first Like's generation",
            "status": "CARRIED"
          },
          {
            "id": "D26",
            "source": "docstring",
            "clause": "\"undo_like of an imported like publishes nothing\"",
            "assertion": ":222",
            "excludes": "publishing on removal of an imported like",
            "status": "CARRIED"
          },
          {
            "id": "D27",
            "source": "docstring",
            "clause": "\"though the import stored the like\"",
            "assertion": ":219",
            "excludes": "an import that stored nothing, which would make the undo a trivial no-op",
            "status": "CARRIED"
          },
          {
            "id": "D28",
            "source": "docstring",
            "clause": "\"and the undo removed it\"",
            "assertion": ":221",
            "excludes": "the undo being refused instead of applied without publishing",
            "status": "CARRIED"
          },
          {
            "id": "D29",
            "source": "docstring",
            "clause": "\"a like afterwards publishes at generation 1\"",
            "assertion": ":225",
            "excludes": "the import or the undo consuming a generation",
            "status": "CARRIED"
          },
          {
            "id": "N1a",
            "source": "name",
            "clause": "\"a repeated like publishes one like\"",
            "assertion": ":140",
            "excludes": "a Like per action",
            "status": "CARRIED"
          },
          {
            "id": "N1b",
            "source": "name",
            "clause": "\"a bridge retry of it is a duplicate\"",
            "assertion": ":144",
            "excludes": "nothing: the retry is simulated by re-sending the recorded payload, which is a duplicate whatever the id scheme",
            "status": "UNCARRIED"
          },
          {
            "id": "N2",
            "source": "name",
            "clause": "\"like, undo_like, like publishes Like, UndoLike, Like under generations 1, 1, 2\"",
            "assertion": ":155",
            "excludes": "wrong sequence or generations",
            "status": "CARRIED"
          },
          {
            "id": "N3a",
            "source": "name",
            "clause": "\"two anonymous likes carry one id\"",
            "assertion": ":162",
            "excludes": "a per-request anonymous id",
            "status": "CARRIED"
          },
          {
            "id": "N3b",
            "source": "name",
            "clause": "\"the engine counts the second as a duplicate\"",
            "assertion": ":163",
            "excludes": "a second non-duplicate ingest",
            "status": "CARRIED"
          },
          {
            "id": "N4",
            "source": "name",
            "clause": "\"a like named in a non-canonical spelling derives its id from the resolved identity\"",
            "assertion": ":174",
            "excludes": "hashing the spelling sent",
            "status": "CARRIED"
          },
          {
            "id": "N5a",
            "source": "name",
            "clause": "\"an undo_like of an unliked video answers 200\"",
            "assertion": ":180",
            "excludes": "an error status",
            "status": "CARRIED"
          },
          {
            "id": "N5b",
            "source": "name",
            "clause": "\"and publishes nothing\"",
            "assertion": ":181",
            "excludes": "publishing an UndoLike",
            "status": "CARRIED"
          },
          {
            "id": "N6a",
            "source": "name",
            "clause": "\"a dislike replacing a like publishes the undo_like's id\"",
            "assertion": ":192",
            "excludes": "a different id on the withdrawal",
            "status": "CARRIED"
          },
          {
            "id": "N6b",
            "source": "name",
            "clause": "\"one of an unliked video publishes nothing\"",
            "assertion": ":197",
            "excludes": "publishing on that dislike",
            "status": "CARRIED"
          },
          {
            "id": "N7a",
            "source": "name",
            "clause": "\"a like after a reset publishes nothing\"",
            "assertion": ":208",
            "excludes": "the re-like publishing",
            "status": "CARRIED"
          },
          {
            "id": "N7b",
            "source": "name",
            "clause": "\"the next undo_like withdraws the first\"",
            "assertion": ":212",
            "excludes": "an UndoLike at the re-like's generation",
            "status": "CARRIED"
          },
          {
            "id": "N8",
            "source": "name",
            "clause": "\"an undo_like of an imported like publishes nothing\"",
            "assertion": ":222",
            "excludes": "publishing on removal of an imported like",
            "status": "CARRIED"
          }
        ],
        "map_problem": ""
      },
      {
        "shape": "SHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\nThe first failure is at tests/tmp/test_13_deterministic_event_ids_phase2.py:140, where `[event_type for event_type, _ in _published(rig.events)] == [\"Like\"]` gets `[\"Like\", \"Like\"]`, because server.py:784 still publishes on every `like`. Each later test should fail at its first id-equality assertion, lines 152, 159, 171, 189, 209 and 222, because server.py:802 still builds `event_id` as `f\"client-{uuid4()}\"`. Two tests fail earlier: the one at lines 174\u2013181 fails at 178 on `rig.events == []`, because an `undo_like` of an unliked video still publishes an UndoLike, and the one at lines 212\u2013222 fails the same way at 219.\n\nNOT ASSESSED\n1. `code_under_test` listed tests/active/test_event_ids.py (NEW), which does not resolve. The stub question was answered from the test's assertion form and from client/backend/server.py and client/backend/lib/users_store.py.\n2. `fixtures_path` was not supplied. Instead I read the imported harness symbols (`ClientBackend`, `RateLimiter`, `client_server`, `ensure_user_schema`) from tests/active/conftest.py, which the test imports directly at line 34. I did not read how `ensure_user_schema` is built.\n3. Anti-pattern pass: `_event_id` at line 45 computes the expected id in the test body. I did not class it as `tautological-assertion`. It encodes C2's formula as written, imports nothing from production, and takes the inputs that matter from independent literals: generation 0/1/2, actor pid vs `anonymous`, and the canonical rather than the as-sent spelling. A wrong actor, identity, generation or field order would show on one side only. Only a wrong formula would move both sides together, and that formula is the requirement itself.\n4. Absence assertions at lines 178 and 219 each have a positive publish control later in the same test (lines 181 and 222). The one at line 194 comes after two positive publishes asserted at line 189. So none is `absence-only-assertion`.\n5. Ladder pass: the test drives the real Client handler over HTTP and asserts on the payloads the Engine stub receives and on engine.db rows (rungs 1\u20133). No downshift is needed and none was made. The Engine stub's lower-casing at line 75 stands in for the Engine's canonicalisation, not for the code under test, so it gives no stub route.",
        "claim": "CLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (54 clauses: 12 must_prove, 29 docstring, 13 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | a repeat like of a video the profile already likes publishes nothing | :140 | publishing a Like on every `like` action | CARRIED |\n| C1b | must_prove | undo_like of a video with no published like publishes nothing | :178 | publishing an UndoLike on every `undo_like` | CARRIED |\n| C1c | must_prove | a dislike of a video the profile does not like publishes nothing | :194 | publishing on a dislike that removed no like | CARRIED |\n| C1d | must_prove | undo_dislike of a video the profile does not like publishes nothing | :194 | publishing on undo_dislike (the count stays 2 after both actions) | CARRIED |\n| C1e | must_prove | re-like after a reset, while the published like is still open, publishes nothing | :205 | deciding to publish from the stored like instead of the published one (:204 shows the re-like was stored) | CARRIED |\n| C1f | must_prove | undo_like of an imported (never published) like publishes nothing | :219 | publishing an UndoLike because a stored like was removed | CARRIED |\n| C2a | must_prove | id is `client-` + SHA-256 hex of the JSON list | :142 | a `client-{uuid4}` id or any other hash or encoding | CARRIED |\n| C2b | must_prove | actor in the hashed list (profile id / `anonymous`) | :142, :159 | leaving out the actor, or using some other actor string | CARRIED |\n| C2c | must_prove | canonical uuid in the hashed list | :171 | hashing the upper-case uuid as sent | CARRIED |\n| C2d | must_prove | canonical host in the hashed list | :171 | hashing `IDS.Example` as sent | CARRIED |\n| C2e | must_prove | event type in the hashed list | :152 | Like and UndoLike at generation 1 sharing one id | CARRIED |\n| C2f | must_prove | like generation in the hashed list | :151, :152, :159 | a re-like after an undo reusing generation 1; anonymous not at 0 | CARRIED |\n| D1 | docstring | \"publishes a Like or UndoLike only when it opens or closes\" the like | :140, :150, :178, :188, :194 | publishing on no-op actions, or not publishing on a real open or close | CARRIED |\n| D2 | docstring | \"every published event's id is `client-` plus the SHA-256 of\u2026\" | :142, :152, :159, :171 | any id other than the derived one | CARRIED |\n| D3 | docstring | \"Two likes \u2026 publish one Like\" | :140 | a Like per action | CARRIED |\n| D4 | docstring | \"at generation 1\" | :142 | generation 0 or 2 on the first like | CARRIED |\n| D5 | docstring | \"the video's signal is (1, 1.0)\" | :141 | the Engine counting two likes | CARRIED |\n| D6 | docstring | withdrawn | n/a | n/a | CARRIED |\n| D7 | docstring | withdrawn | n/a | n/a | CARRIED |\n| D8 | docstring | \"publishes Like, UndoLike, Like at generations 1, 1 and 2\" | :152 | wrong order, or wrong generation on any of the three | CARRIED |\n| D9 | docstring | \"the two Like ids differ\" | :151 | a re-like reusing the first Like's id | CARRIED |\n| D10 | docstring | \"the signal ends at (1, 1.0)\" | :153 | the re-like collapsed as a duplicate (signal 0) | CARRIED |\n| D11 | docstring | \"Two anonymous likes both publish the Like id for actor `anonymous` at generation 0\" | :159 | a per-request id, or a generation other than 0 | CARRIED |\n| D12 | docstring | \"the Engine counts the second as a duplicate\" | :160 | distinct ids for the two anonymous likes | CARRIED |\n| D13 | docstring | \"the signal is (1, 1.0)\" | :161 | the Engine counting two | CARRIED |\n| D14 | docstring | id \"over the uuid and host the Engine resolved them to, not over the spelling sent\" | :171 (controls :169\u2013170) | hashing the request's spelling | CARRIED |\n| D15 | docstring | \"undo_like of a video the profile never liked answers 200\" | :177 | a 4xx/5xx on the no-op undo | CARRIED |\n| D16 | docstring | \"and publishes nothing\" | :178 | publishing an UndoLike | CARRIED |\n| D17 | docstring | \"a like afterwards publishes at generation 1\" | :181 | the refused undo moving the generation forward | CARRIED |\n| D18 | docstring | \"A dislike replacing a like publishes the UndoLike id an undo_like would have used (generation 1)\" | :189 | a different id or generation on the dislike's withdrawal | CARRIED |\n| D19 | docstring | \"and leaves (0, 0.0)\" | :190 | the withdrawal not reaching the signal | CARRIED |\n| D20 | docstring | \"a dislike \u2026 of a video the profile does not like publish[es] nothing\" | :194 | publishing on that dislike | CARRIED |\n| D21 | docstring | \"and an undo_dislike \u2026 publish[es] nothing\" | :194 | publishing on that undo_dislike | CARRIED |\n| D22 | docstring | \"like, reset, like publishes one Like\" | :205 | the re-like or the reset publishing | CARRIED |\n| D23 | docstring | \"though the re-like is stored\" | :204 | the re-like being refused rather than stored and left unpublished | CARRIED |\n| D24 | docstring | \"the undo_like after it publishes that Like's UndoLike\" | :207, :209 | an UndoLike at generation 2, or none | CARRIED |\n| D25 | docstring | \"and leaves (0, 0.0)\" | :208 | the UndoLike missing the first Like's generation | CARRIED |\n| D26 | docstring | \"undo_like of an imported like publishes nothing\" | :219 | publishing on removal of an imported like | CARRIED |\n| D27 | docstring | \"though the import stored the like\" | :216 | an import that stored nothing, which would make the undo a trivial no-op | CARRIED |\n| D28 | docstring | \"and the undo removed it\" | :218 | the undo being refused instead of applied without publishing | CARRIED |\n| D29 | docstring | \"a like afterwards publishes at generation 1\" | :222 | the import or the undo consuming a generation | CARRIED |\n| N1a | name | \"a repeated like publishes one like\" | :140 | a Like per action | CARRIED |\n| N1b | name | withdrawn | n/a | n/a | CARRIED |\n| N2 | name | \"like, undo_like, like publishes Like, UndoLike, Like under generations 1, 1, 2\" | :152 | wrong sequence or generations | CARRIED |\n| N3a | name | \"two anonymous likes carry one id\" | :159 | a per-request anonymous id | CARRIED |\n| N3b | name | \"the engine counts the second as a duplicate\" | :160 | a second ingest that is not a duplicate | CARRIED |\n| N4 | name | \"a like named in a non-canonical spelling derives its id from the resolved identity\" | :171 | hashing the spelling sent | CARRIED |\n| N5a | name | \"an undo_like of an unliked video answers 200\" | :177 | an error status | CARRIED |\n| N5b | name | \"and publishes nothing\" | :178 | publishing an UndoLike | CARRIED |\n| N6a | name | \"a dislike replacing a like publishes the undo_like's id\" | :189 | a different id on the withdrawal | CARRIED |\n| N6b | name | \"one of an unliked video publishes nothing\" | :194 | publishing on that dislike | CARRIED |\n| N7a | name | \"a like after a reset publishes nothing\" | :205 | the re-like publishing | CARRIED |\n| N7b | name | \"the next undo_like withdraws the first\" | :209 | an UndoLike at the re-like's generation | CARRIED |\n| N8 | name | \"an undo_like of an imported like publishes nothing\" | :219 | publishing on removal of an imported like | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nOBSERVATIONS\n1. whole-claim (rules/testing.md): tests/tmp/test_13_deterministic_event_ids_phase2.py:3\n   D6 and D7 were closed by narrowing the prose, not by adding an assertion. The docstring bullet now ends at \"and the video's signal is (1, 1.0)\". The sentence \"re-ingesting that Like's payload unchanged, as a bridge retry does, is a duplicate and leaves (1, 1.0)\" was removed, and nothing in the test asserts retry-duplicate behaviour.\n2. whole-claim (rules/testing.md): tests/tmp/test_13_deterministic_event_ids_phase2.py:136\n   N1b was also closed by narrowing, this time the test name. `..._and_a_bridge_retry_of_it_is_a_duplicate` became `test_a_repeated_like_publishes_one_like_at_generation_1`. The name's new clause, \"at generation 1\", has no ledger row. It is carried by :142, which excludes a generation-0 or generation-2 first like, so no defect comes of it.\n\nNOT ASSESSED\n1. `code_under_test` lists tests/active/test_event_ids.py (NEW). That path does not resolve, so it was not read.\n2. `fixtures_path` was not supplied. The fixture `rig` is defined in the test file. The harness imports (`ClientBackend`, `RateLimiter`, `client_server`, `ensure_user_schema`) were resolved to tests/active/conftest.py and read there. The Engine's `ensure_interaction_event_schema` / `ingest_interaction_event` (engine/server/api/data/interaction_events.py) is outside `code_under_test` and was not read. The duplicate outcomes at :160 were therefore judged from the test's own use of `result[\"duplicate\"]`.",
        "body": "### devsecops-test-shape-auditor\n\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\nThe first failure is at tests/tmp/test_13_deterministic_event_ids_phase2.py:140, where `[event_type for event_type, _ in _published(rig.events)] == [\"Like\"]` gets `[\"Like\", \"Like\"]`, because server.py:784 still publishes on every `like`. Each later test should fail at its first id-equality assertion, lines 152, 159, 171, 189, 209 and 222, because server.py:802 still builds `event_id` as `f\"client-{uuid4()}\"`. Two tests fail earlier: the one at lines 174\u2013181 fails at 178 on `rig.events == []`, because an `undo_like` of an unliked video still publishes an UndoLike, and the one at lines 212\u2013222 fails the same way at 219.\n\nNOT ASSESSED\n1. `code_under_test` listed tests/active/test_event_ids.py (NEW), which does not resolve. The stub question was answered from the test's assertion form and from client/backend/server.py and client/backend/lib/users_store.py.\n2. `fixtures_path` was not supplied. Instead I read the imported harness symbols (`ClientBackend`, `RateLimiter`, `client_server`, `ensure_user_schema`) from tests/active/conftest.py, which the test imports directly at line 34. I did not read how `ensure_user_schema` is built.\n3. Anti-pattern pass: `_event_id` at line 45 computes the expected id in the test body. I did not class it as `tautological-assertion`. It encodes C2's formula as written, imports nothing from production, and takes the inputs that matter from independent literals: generation 0/1/2, actor pid vs `anonymous`, and the canonical rather than the as-sent spelling. A wrong actor, identity, generation or field order would show on one side only. Only a wrong formula would move both sides together, and that formula is the requirement itself.\n4. Absence assertions at lines 178 and 219 each have a positive publish control later in the same test (lines 181 and 222). The one at line 194 comes after two positive publishes asserted at line 189. So none is `absence-only-assertion`.\n5. Ladder pass: the test drives the real Client handler over HTTP and asserts on the payloads the Engine stub receives and on engine.db rows (rungs 1\u20133). No downshift is needed and none was made. The Engine stub's lower-casing at line 75 stands in for the Engine's canonicalisation, not for the code under test, so it gives no stub route.\n\n### devsecops-test-claim-auditor\n\nCLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (54 clauses: 12 must_prove, 29 docstring, 13 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | a repeat like of a video the profile already likes publishes nothing | :140 | publishing a Like on every `like` action | CARRIED |\n| C1b | must_prove | undo_like of a video with no published like publishes nothing | :178 | publishing an UndoLike on every `undo_like` | CARRIED |\n| C1c | must_prove | a dislike of a video the profile does not like publishes nothing | :194 | publishing on a dislike that removed no like | CARRIED |\n| C1d | must_prove | undo_dislike of a video the profile does not like publishes nothing | :194 | publishing on undo_dislike (the count stays 2 after both actions) | CARRIED |\n| C1e | must_prove | re-like after a reset, while the published like is still open, publishes nothing | :205 | deciding to publish from the stored like instead of the published one (:204 shows the re-like was stored) | CARRIED |\n| C1f | must_prove | undo_like of an imported (never published) like publishes nothing | :219 | publishing an UndoLike because a stored like was removed | CARRIED |\n| C2a | must_prove | id is `client-` + SHA-256 hex of the JSON list | :142 | a `client-{uuid4}` id or any other hash or encoding | CARRIED |\n| C2b | must_prove | actor in the hashed list (profile id / `anonymous`) | :142, :159 | leaving out the actor, or using some other actor string | CARRIED |\n| C2c | must_prove | canonical uuid in the hashed list | :171 | hashing the upper-case uuid as sent | CARRIED |\n| C2d | must_prove | canonical host in the hashed list | :171 | hashing `IDS.Example` as sent | CARRIED |\n| C2e | must_prove | event type in the hashed list | :152 | Like and UndoLike at generation 1 sharing one id | CARRIED |\n| C2f | must_prove | like generation in the hashed list | :151, :152, :159 | a re-like after an undo reusing generation 1; anonymous not at 0 | CARRIED |\n| D1 | docstring | \"publishes a Like or UndoLike only when it opens or closes\" the like | :140, :150, :178, :188, :194 | publishing on no-op actions, or not publishing on a real open or close | CARRIED |\n| D2 | docstring | \"every published event's id is `client-` plus the SHA-256 of\u2026\" | :142, :152, :159, :171 | any id other than the derived one | CARRIED |\n| D3 | docstring | \"Two likes \u2026 publish one Like\" | :140 | a Like per action | CARRIED |\n| D4 | docstring | \"at generation 1\" | :142 | generation 0 or 2 on the first like | CARRIED |\n| D5 | docstring | \"the video's signal is (1, 1.0)\" | :141 | the Engine counting two likes | CARRIED |\n| D6 | docstring | withdrawn | n/a | n/a | CARRIED |\n| D7 | docstring | withdrawn | n/a | n/a | CARRIED |\n| D8 | docstring | \"publishes Like, UndoLike, Like at generations 1, 1 and 2\" | :152 | wrong order, or wrong generation on any of the three | CARRIED |\n| D9 | docstring | \"the two Like ids differ\" | :151 | a re-like reusing the first Like's id | CARRIED |\n| D10 | docstring | \"the signal ends at (1, 1.0)\" | :153 | the re-like collapsed as a duplicate (signal 0) | CARRIED |\n| D11 | docstring | \"Two anonymous likes both publish the Like id for actor `anonymous` at generation 0\" | :159 | a per-request id, or a generation other than 0 | CARRIED |\n| D12 | docstring | \"the Engine counts the second as a duplicate\" | :160 | distinct ids for the two anonymous likes | CARRIED |\n| D13 | docstring | \"the signal is (1, 1.0)\" | :161 | the Engine counting two | CARRIED |\n| D14 | docstring | id \"over the uuid and host the Engine resolved them to, not over the spelling sent\" | :171 (controls :169\u2013170) | hashing the request's spelling | CARRIED |\n| D15 | docstring | \"undo_like of a video the profile never liked answers 200\" | :177 | a 4xx/5xx on the no-op undo | CARRIED |\n| D16 | docstring | \"and publishes nothing\" | :178 | publishing an UndoLike | CARRIED |\n| D17 | docstring | \"a like afterwards publishes at generation 1\" | :181 | the refused undo moving the generation forward | CARRIED |\n| D18 | docstring | \"A dislike replacing a like publishes the UndoLike id an undo_like would have used (generation 1)\" | :189 | a different id or generation on the dislike's withdrawal | CARRIED |\n| D19 | docstring | \"and leaves (0, 0.0)\" | :190 | the withdrawal not reaching the signal | CARRIED |\n| D20 | docstring | \"a dislike \u2026 of a video the profile does not like publish[es] nothing\" | :194 | publishing on that dislike | CARRIED |\n| D21 | docstring | \"and an undo_dislike \u2026 publish[es] nothing\" | :194 | publishing on that undo_dislike | CARRIED |\n| D22 | docstring | \"like, reset, like publishes one Like\" | :205 | the re-like or the reset publishing | CARRIED |\n| D23 | docstring | \"though the re-like is stored\" | :204 | the re-like being refused rather than stored and left unpublished | CARRIED |\n| D24 | docstring | \"the undo_like after it publishes that Like's UndoLike\" | :207, :209 | an UndoLike at generation 2, or none | CARRIED |\n| D25 | docstring | \"and leaves (0, 0.0)\" | :208 | the UndoLike missing the first Like's generation | CARRIED |\n| D26 | docstring | \"undo_like of an imported like publishes nothing\" | :219 | publishing on removal of an imported like | CARRIED |\n| D27 | docstring | \"though the import stored the like\" | :216 | an import that stored nothing, which would make the undo a trivial no-op | CARRIED |\n| D28 | docstring | \"and the undo removed it\" | :218 | the undo being refused instead of applied without publishing | CARRIED |\n| D29 | docstring | \"a like afterwards publishes at generation 1\" | :222 | the import or the undo consuming a generation | CARRIED |\n| N1a | name | \"a repeated like publishes one like\" | :140 | a Like per action | CARRIED |\n| N1b | name | withdrawn | n/a | n/a | CARRIED |\n| N2 | name | \"like, undo_like, like publishes Like, UndoLike, Like under generations 1, 1, 2\" | :152 | wrong sequence or generations | CARRIED |\n| N3a | name | \"two anonymous likes carry one id\" | :159 | a per-request anonymous id | CARRIED |\n| N3b | name | \"the engine counts the second as a duplicate\" | :160 | a second ingest that is not a duplicate | CARRIED |\n| N4 | name | \"a like named in a non-canonical spelling derives its id from the resolved identity\" | :171 | hashing the spelling sent | CARRIED |\n| N5a | name | \"an undo_like of an unliked video answers 200\" | :177 | an error status | CARRIED |\n| N5b | name | \"and publishes nothing\" | :178 | publishing an UndoLike | CARRIED |\n| N6a | name | \"a dislike replacing a like publishes the undo_like's id\" | :189 | a different id on the withdrawal | CARRIED |\n| N6b | name | \"one of an unliked video publishes nothing\" | :194 | publishing on that dislike | CARRIED |\n| N7a | name | \"a like after a reset publishes nothing\" | :205 | the re-like publishing | CARRIED |\n| N7b | name | \"the next undo_like withdraws the first\" | :209 | an UndoLike at the re-like's generation | CARRIED |\n| N8 | name | \"an undo_like of an imported like publishes nothing\" | :219 | publishing on removal of an imported like | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nOBSERVATIONS\n1. whole-claim (rules/testing.md): tests/tmp/test_13_deterministic_event_ids_phase2.py:3\n   D6 and D7 were closed by narrowing the prose, not by adding an assertion. The docstring bullet now ends at \"and the video's signal is (1, 1.0)\". The sentence \"re-ingesting that Like's payload unchanged, as a bridge retry does, is a duplicate and leaves (1, 1.0)\" was removed, and nothing in the test asserts retry-duplicate behaviour.\n2. whole-claim (rules/testing.md): tests/tmp/test_13_deterministic_event_ids_phase2.py:136\n   N1b was also closed by narrowing, this time the test name. `..._and_a_bridge_retry_of_it_is_a_duplicate` became `test_a_repeated_like_publishes_one_like_at_generation_1`. The name's new clause, \"at generation 1\", has no ledger row. It is carried by :142, which excludes a generation-0 or generation-2 first like, so no defect comes of it.\n\nNOT ASSESSED\n1. `code_under_test` lists tests/active/test_event_ids.py (NEW). That path does not resolve, so it was not read.\n2. `fixtures_path` was not supplied. The fixture `rig` is defined in the test file. The harness imports (`ClientBackend`, `RateLimiter`, `client_server`, `ensure_user_schema`) were resolved to tests/active/conftest.py and read there. The Engine's `ensure_interaction_event_schema` / `ingest_interaction_event` (engine/server/api/data/interaction_events.py) is outside `code_under_test` and was not read. The duplicate outcomes at :160 were therefore judged from the test's own use of `result[\"duplicate\"]`.",
        "map": [
          {
            "id": "C1a",
            "source": "must_prove",
            "clause": "a repeat like of a video the profile already likes publishes nothing",
            "assertion": ":140",
            "excludes": "publishing a Like on every `like` action",
            "status": "CARRIED"
          },
          {
            "id": "C1b",
            "source": "must_prove",
            "clause": "undo_like of a video with no published like publishes nothing",
            "assertion": ":178",
            "excludes": "publishing an UndoLike on every `undo_like`",
            "status": "CARRIED"
          },
          {
            "id": "C1c",
            "source": "must_prove",
            "clause": "a dislike of a video the profile does not like publishes nothing",
            "assertion": ":194",
            "excludes": "publishing on a dislike that removed no like",
            "status": "CARRIED"
          },
          {
            "id": "C1d",
            "source": "must_prove",
            "clause": "undo_dislike of a video the profile does not like publishes nothing",
            "assertion": ":194",
            "excludes": "publishing on undo_dislike (the count stays 2 after both actions)",
            "status": "CARRIED"
          },
          {
            "id": "C1e",
            "source": "must_prove",
            "clause": "re-like after a reset, while the published like is still open, publishes nothing",
            "assertion": ":205",
            "excludes": "deciding to publish from the stored like instead of the published one (:204 shows the re-like was stored)",
            "status": "CARRIED"
          },
          {
            "id": "C1f",
            "source": "must_prove",
            "clause": "undo_like of an imported (never published) like publishes nothing",
            "assertion": ":219",
            "excludes": "publishing an UndoLike because a stored like was removed",
            "status": "CARRIED"
          },
          {
            "id": "C2a",
            "source": "must_prove",
            "clause": "id is `client-` + SHA-256 hex of the JSON list",
            "assertion": ":142",
            "excludes": "a `client-{uuid4}` id or any other hash or encoding",
            "status": "CARRIED"
          },
          {
            "id": "C2b",
            "source": "must_prove",
            "clause": "actor in the hashed list (profile id / `anonymous`)",
            "assertion": ":142, :159",
            "excludes": "leaving out the actor, or using some other actor string",
            "status": "CARRIED"
          },
          {
            "id": "C2c",
            "source": "must_prove",
            "clause": "canonical uuid in the hashed list",
            "assertion": ":171",
            "excludes": "hashing the upper-case uuid as sent",
            "status": "CARRIED"
          },
          {
            "id": "C2d",
            "source": "must_prove",
            "clause": "canonical host in the hashed list",
            "assertion": ":171",
            "excludes": "hashing `IDS.Example` as sent",
            "status": "CARRIED"
          },
          {
            "id": "C2e",
            "source": "must_prove",
            "clause": "event type in the hashed list",
            "assertion": ":152",
            "excludes": "Like and UndoLike at generation 1 sharing one id",
            "status": "CARRIED"
          },
          {
            "id": "C2f",
            "source": "must_prove",
            "clause": "like generation in the hashed list",
            "assertion": ":151, :152, :159",
            "excludes": "a re-like after an undo reusing generation 1; anonymous not at 0",
            "status": "CARRIED"
          },
          {
            "id": "D1",
            "source": "docstring",
            "clause": "\"publishes a Like or UndoLike only when it opens or closes\" the like",
            "assertion": ":140, :150, :178, :188, :194",
            "excludes": "publishing on no-op actions, or not publishing on a real open or close",
            "status": "CARRIED"
          },
          {
            "id": "D2",
            "source": "docstring",
            "clause": "\"every published event's id is `client-` plus the SHA-256 of\u2026\"",
            "assertion": ":142, :152, :159, :171",
            "excludes": "any id other than the derived one",
            "status": "CARRIED"
          },
          {
            "id": "D3",
            "source": "docstring",
            "clause": "\"Two likes \u2026 publish one Like\"",
            "assertion": ":140",
            "excludes": "a Like per action",
            "status": "CARRIED"
          },
          {
            "id": "D4",
            "source": "docstring",
            "clause": "\"at generation 1\"",
            "assertion": ":142",
            "excludes": "generation 0 or 2 on the first like",
            "status": "CARRIED"
          },
          {
            "id": "D5",
            "source": "docstring",
            "clause": "\"the video's signal is (1, 1.0)\"",
            "assertion": ":141",
            "excludes": "the Engine counting two likes",
            "status": "CARRIED"
          },
          {
            "id": "D6",
            "source": "docstring",
            "clause": "withdrawn",
            "assertion": "n/a",
            "excludes": "n/a",
            "status": "CARRIED"
          },
          {
            "id": "D7",
            "source": "docstring",
            "clause": "withdrawn",
            "assertion": "n/a",
            "excludes": "n/a",
            "status": "CARRIED"
          },
          {
            "id": "D8",
            "source": "docstring",
            "clause": "\"publishes Like, UndoLike, Like at generations 1, 1 and 2\"",
            "assertion": ":152",
            "excludes": "wrong order, or wrong generation on any of the three",
            "status": "CARRIED"
          },
          {
            "id": "D9",
            "source": "docstring",
            "clause": "\"the two Like ids differ\"",
            "assertion": ":151",
            "excludes": "a re-like reusing the first Like's id",
            "status": "CARRIED"
          },
          {
            "id": "D10",
            "source": "docstring",
            "clause": "\"the signal ends at (1, 1.0)\"",
            "assertion": ":153",
            "excludes": "the re-like collapsed as a duplicate (signal 0)",
            "status": "CARRIED"
          },
          {
            "id": "D11",
            "source": "docstring",
            "clause": "\"Two anonymous likes both publish the Like id for actor `anonymous` at generation 0\"",
            "assertion": ":159",
            "excludes": "a per-request id, or a generation other than 0",
            "status": "CARRIED"
          },
          {
            "id": "D12",
            "source": "docstring",
            "clause": "\"the Engine counts the second as a duplicate\"",
            "assertion": ":160",
            "excludes": "distinct ids for the two anonymous likes",
            "status": "CARRIED"
          },
          {
            "id": "D13",
            "source": "docstring",
            "clause": "\"the signal is (1, 1.0)\"",
            "assertion": ":161",
            "excludes": "the Engine counting two",
            "status": "CARRIED"
          },
          {
            "id": "D14",
            "source": "docstring",
            "clause": "id \"over the uuid and host the Engine resolved them to, not over the spelling sent\"",
            "assertion": ":171 (controls :169\u2013170)",
            "excludes": "hashing the request's spelling",
            "status": "CARRIED"
          },
          {
            "id": "D15",
            "source": "docstring",
            "clause": "\"undo_like of a video the profile never liked answers 200\"",
            "assertion": ":177",
            "excludes": "a 4xx/5xx on the no-op undo",
            "status": "CARRIED"
          },
          {
            "id": "D16",
            "source": "docstring",
            "clause": "\"and publishes nothing\"",
            "assertion": ":178",
            "excludes": "publishing an UndoLike",
            "status": "CARRIED"
          },
          {
            "id": "D17",
            "source": "docstring",
            "clause": "\"a like afterwards publishes at generation 1\"",
            "assertion": ":181",
            "excludes": "the refused undo moving the generation forward",
            "status": "CARRIED"
          },
          {
            "id": "D18",
            "source": "docstring",
            "clause": "\"A dislike replacing a like publishes the UndoLike id an undo_like would have used (generation 1)\"",
            "assertion": ":189",
            "excludes": "a different id or generation on the dislike's withdrawal",
            "status": "CARRIED"
          },
          {
            "id": "D19",
            "source": "docstring",
            "clause": "\"and leaves (0, 0.0)\"",
            "assertion": ":190",
            "excludes": "the withdrawal not reaching the signal",
            "status": "CARRIED"
          },
          {
            "id": "D20",
            "source": "docstring",
            "clause": "\"a dislike \u2026 of a video the profile does not like publish[es] nothing\"",
            "assertion": ":194",
            "excludes": "publishing on that dislike",
            "status": "CARRIED"
          },
          {
            "id": "D21",
            "source": "docstring",
            "clause": "\"and an undo_dislike \u2026 publish[es] nothing\"",
            "assertion": ":194",
            "excludes": "publishing on that undo_dislike",
            "status": "CARRIED"
          },
          {
            "id": "D22",
            "source": "docstring",
            "clause": "\"like, reset, like publishes one Like\"",
            "assertion": ":205",
            "excludes": "the re-like or the reset publishing",
            "status": "CARRIED"
          },
          {
            "id": "D23",
            "source": "docstring",
            "clause": "\"though the re-like is stored\"",
            "assertion": ":204",
            "excludes": "the re-like being refused rather than stored and left unpublished",
            "status": "CARRIED"
          },
          {
            "id": "D24",
            "source": "docstring",
            "clause": "\"the undo_like after it publishes that Like's UndoLike\"",
            "assertion": ":207, :209",
            "excludes": "an UndoLike at generation 2, or none",
            "status": "CARRIED"
          },
          {
            "id": "D25",
            "source": "docstring",
            "clause": "\"and leaves (0, 0.0)\"",
            "assertion": ":208",
            "excludes": "the UndoLike missing the first Like's generation",
            "status": "CARRIED"
          },
          {
            "id": "D26",
            "source": "docstring",
            "clause": "\"undo_like of an imported like publishes nothing\"",
            "assertion": ":219",
            "excludes": "publishing on removal of an imported like",
            "status": "CARRIED"
          },
          {
            "id": "D27",
            "source": "docstring",
            "clause": "\"though the import stored the like\"",
            "assertion": ":216",
            "excludes": "an import that stored nothing, which would make the undo a trivial no-op",
            "status": "CARRIED"
          },
          {
            "id": "D28",
            "source": "docstring",
            "clause": "\"and the undo removed it\"",
            "assertion": ":218",
            "excludes": "the undo being refused instead of applied without publishing",
            "status": "CARRIED"
          },
          {
            "id": "D29",
            "source": "docstring",
            "clause": "\"a like afterwards publishes at generation 1\"",
            "assertion": ":222",
            "excludes": "the import or the undo consuming a generation",
            "status": "CARRIED"
          },
          {
            "id": "N1a",
            "source": "name",
            "clause": "\"a repeated like publishes one like\"",
            "assertion": ":140",
            "excludes": "a Like per action",
            "status": "CARRIED"
          },
          {
            "id": "N1b",
            "source": "name",
            "clause": "withdrawn",
            "assertion": "n/a",
            "excludes": "n/a",
            "status": "CARRIED"
          },
          {
            "id": "N2",
            "source": "name",
            "clause": "\"like, undo_like, like publishes Like, UndoLike, Like under generations 1, 1, 2\"",
            "assertion": ":152",
            "excludes": "wrong sequence or generations",
            "status": "CARRIED"
          },
          {
            "id": "N3a",
            "source": "name",
            "clause": "\"two anonymous likes carry one id\"",
            "assertion": ":159",
            "excludes": "a per-request anonymous id",
            "status": "CARRIED"
          },
          {
            "id": "N3b",
            "source": "name",
            "clause": "\"the engine counts the second as a duplicate\"",
            "assertion": ":160",
            "excludes": "a second ingest that is not a duplicate",
            "status": "CARRIED"
          },
          {
            "id": "N4",
            "source": "name",
            "clause": "\"a like named in a non-canonical spelling derives its id from the resolved identity\"",
            "assertion": ":171",
            "excludes": "hashing the spelling sent",
            "status": "CARRIED"
          },
          {
            "id": "N5a",
            "source": "name",
            "clause": "\"an undo_like of an unliked video answers 200\"",
            "assertion": ":177",
            "excludes": "an error status",
            "status": "CARRIED"
          },
          {
            "id": "N5b",
            "source": "name",
            "clause": "\"and publishes nothing\"",
            "assertion": ":178",
            "excludes": "publishing an UndoLike",
            "status": "CARRIED"
          },
          {
            "id": "N6a",
            "source": "name",
            "clause": "\"a dislike replacing a like publishes the undo_like's id\"",
            "assertion": ":189",
            "excludes": "a different id on the withdrawal",
            "status": "CARRIED"
          },
          {
            "id": "N6b",
            "source": "name",
            "clause": "\"one of an unliked video publishes nothing\"",
            "assertion": ":194",
            "excludes": "publishing on that dislike",
            "status": "CARRIED"
          },
          {
            "id": "N7a",
            "source": "name",
            "clause": "\"a like after a reset publishes nothing\"",
            "assertion": ":205",
            "excludes": "the re-like publishing",
            "status": "CARRIED"
          },
          {
            "id": "N7b",
            "source": "name",
            "clause": "\"the next undo_like withdraws the first\"",
            "assertion": ":209",
            "excludes": "an UndoLike at the re-like's generation",
            "status": "CARRIED"
          },
          {
            "id": "N8",
            "source": "name",
            "clause": "\"an undo_like of an imported like publishes nothing\"",
            "assertion": ":219",
            "excludes": "publishing on removal of an imported like",
            "status": "CARRIED"
          }
        ],
        "map_problem": ""
      }
    ],
    "tests/tmp/test_13_deterministic_event_ids_phase3.py": [
      {
        "shape": "```\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\nFails at tests/tmp/test_13_deterministic_event_ids_phase3.py:75, on the dict equality for the deleted\nprofile. The actual value is {\"profiles\": 0, \"users\": 0, \"likes\": 0, \"like_generations\": 2}, because\ndelete_profile in client/backend/lib/profiles.py:69-80 as read deletes from blocks, dislikes,\ndislike_profiles, likes, users and profiles, and never from like_generations.\n\nNOT ASSESSED\n1. `fixtures_path` was \"none found\". The `client_backend` fixture the test imports at line 15 was\n   found by Grep and read at tests/active/conftest.py:46-89. The `connect_db`, `ClientBackendServer`\n   and `/api/profile/delete` routing in client/backend/server.py were not in `code_under_test` and\n   were not read. The stub question was answered on the assumption that the route calls\n   delete_profile.\n2. tests/active/test_profiles.py is listed in `code_under_test`. It is a sibling test file, not code\n   this test runs. Only its test index was read, and nothing in it bears on this test's shape.\n```",
        "claim": "CLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (10 clauses: 2 must_prove, 5 docstring, 3 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | \"after one profile is deleted, it has no `like_generations` rows\" | :75 | a delete that leaves `like_generations` untouched. The :65 control shows 2 rows were there before, so a count of 0 cannot pass by default | CARRIED |\n| C1b | must_prove | \"another profile keeps its rows\" | :76 | a delete not scoped by profile, e.g. an unqualified `DELETE FROM like_generations`, or one keyed on the wrong column | CARRIED |\n| D1 | docstring | \"Deleting a profile removes its `like_generations` rows\" | :75 | leaving the deleted profile's generation rows behind | CARRIED |\n| D2 | docstring | \"the open one ... alike\" | :65, :75 | a delete that skips rows with `published = 1`. The control shows the open row existed, and :75 needs it gone | CARRIED |\n| D3 | docstring | \"and the closed one alike\" | :65, :75 | a delete keyed on the profile's remaining `likes` rows. The closed row from `_seed_undone_like` (:63) has no `likes` row, so a delete keyed that way would leave it and :75 would see 1 | CARRIED |\n| D4 | docstring | \"and keeps another profile's\" | :76 | a delete that removes every profile's generations | CARRIED |\n| D5 | docstring | \"A real Client backend ... serves POST /api/profile/delete\" | :72-73 | an endpoint that is missing or refuses the keyed request. The status must be 204, sent to the real `client_backend` server | CARRIED |\n| N1 | name | \"removes its open ... like_generations\" | :75 | the same wrong implementation as D2 | CARRIED |\n| N2 | name | \"removes its ... closed like_generations\" | :75 | the same wrong implementation as D3 | CARRIED |\n| N3 | name | \"keeps anothers\" | :76 | the same wrong implementation as C1b | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. bounds (rules/testing.md) \u2014 tests/tmp/test_13_deterministic_event_ids_phase3.py:57\n   Only the populated case is tested: the profile being deleted always has 2 generation rows (:65). No test deletes a profile that has no `like_generations` rows, which is the \"empty\" edge the bounds principle names. The kept profile also holds only an open row, so there is no check that a closed row belonging to another profile survives the delete.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `fixtures_path` was not supplied. I found `client_backend` in tests/active/conftest.py:69-89 and read it: it creates a fresh `tmp_path` database and server for each test, so I could judge independence. I did not open `client_server.ClientBackendServer` or the handler at client/backend/server.py:341-344 past the lines that route `/api/profile/delete` to `delete_profile`.\n2. `code_under_test` lists tests/active/test_profiles.py (EDITED). It contains nothing matching `like_generations` or a delete test. I did not read it in full because it is not the test under audit and this test does not depend on it.",
        "body": "### devsecops-test-shape-auditor\n\n```\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\nFails at tests/tmp/test_13_deterministic_event_ids_phase3.py:75, on the dict equality for the deleted\nprofile. The actual value is {\"profiles\": 0, \"users\": 0, \"likes\": 0, \"like_generations\": 2}, because\ndelete_profile in client/backend/lib/profiles.py:69-80 as read deletes from blocks, dislikes,\ndislike_profiles, likes, users and profiles, and never from like_generations.\n\nNOT ASSESSED\n1. `fixtures_path` was \"none found\". The `client_backend` fixture the test imports at line 15 was\n   found by Grep and read at tests/active/conftest.py:46-89. The `connect_db`, `ClientBackendServer`\n   and `/api/profile/delete` routing in client/backend/server.py were not in `code_under_test` and\n   were not read. The stub question was answered on the assumption that the route calls\n   delete_profile.\n2. tests/active/test_profiles.py is listed in `code_under_test`. It is a sibling test file, not code\n   this test runs. Only its test index was read, and nothing in it bears on this test's shape.\n```\n\n### devsecops-test-claim-auditor\n\nCLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (10 clauses: 2 must_prove, 5 docstring, 3 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | \"after one profile is deleted, it has no `like_generations` rows\" | :75 | a delete that leaves `like_generations` untouched. The :65 control shows 2 rows were there before, so a count of 0 cannot pass by default | CARRIED |\n| C1b | must_prove | \"another profile keeps its rows\" | :76 | a delete not scoped by profile, e.g. an unqualified `DELETE FROM like_generations`, or one keyed on the wrong column | CARRIED |\n| D1 | docstring | \"Deleting a profile removes its `like_generations` rows\" | :75 | leaving the deleted profile's generation rows behind | CARRIED |\n| D2 | docstring | \"the open one ... alike\" | :65, :75 | a delete that skips rows with `published = 1`. The control shows the open row existed, and :75 needs it gone | CARRIED |\n| D3 | docstring | \"and the closed one alike\" | :65, :75 | a delete keyed on the profile's remaining `likes` rows. The closed row from `_seed_undone_like` (:63) has no `likes` row, so a delete keyed that way would leave it and :75 would see 1 | CARRIED |\n| D4 | docstring | \"and keeps another profile's\" | :76 | a delete that removes every profile's generations | CARRIED |\n| D5 | docstring | \"A real Client backend ... serves POST /api/profile/delete\" | :72-73 | an endpoint that is missing or refuses the keyed request. The status must be 204, sent to the real `client_backend` server | CARRIED |\n| N1 | name | \"removes its open ... like_generations\" | :75 | the same wrong implementation as D2 | CARRIED |\n| N2 | name | \"removes its ... closed like_generations\" | :75 | the same wrong implementation as D3 | CARRIED |\n| N3 | name | \"keeps anothers\" | :76 | the same wrong implementation as C1b | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. bounds (rules/testing.md) \u2014 tests/tmp/test_13_deterministic_event_ids_phase3.py:57\n   Only the populated case is tested: the profile being deleted always has 2 generation rows (:65). No test deletes a profile that has no `like_generations` rows, which is the \"empty\" edge the bounds principle names. The kept profile also holds only an open row, so there is no check that a closed row belonging to another profile survives the delete.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `fixtures_path` was not supplied. I found `client_backend` in tests/active/conftest.py:69-89 and read it: it creates a fresh `tmp_path` database and server for each test, so I could judge independence. I did not open `client_server.ClientBackendServer` or the handler at client/backend/server.py:341-344 past the lines that route `/api/profile/delete` to `delete_profile`.\n2. `code_under_test` lists tests/active/test_profiles.py (EDITED). It contains nothing matching `like_generations` or a delete test. I did not read it in full because it is not the test under audit and this test does not depend on it.",
        "map": [
          {
            "id": "C1a",
            "source": "must_prove",
            "clause": "\"after one profile is deleted, it has no `like_generations` rows\"",
            "assertion": ":75",
            "excludes": "a delete that leaves `like_generations` untouched. The :65 control shows 2 rows were there before, so a count of 0 cannot pass by default",
            "status": "CARRIED"
          },
          {
            "id": "C1b",
            "source": "must_prove",
            "clause": "\"another profile keeps its rows\"",
            "assertion": ":76",
            "excludes": "a delete not scoped by profile, e.g. an unqualified `DELETE FROM like_generations`, or one keyed on the wrong column",
            "status": "CARRIED"
          },
          {
            "id": "D1",
            "source": "docstring",
            "clause": "\"Deleting a profile removes its `like_generations` rows\"",
            "assertion": ":75",
            "excludes": "leaving the deleted profile's generation rows behind",
            "status": "CARRIED"
          },
          {
            "id": "D2",
            "source": "docstring",
            "clause": "\"the open one ... alike\"",
            "assertion": ":65, :75",
            "excludes": "a delete that skips rows with `published = 1`. The control shows the open row existed, and :75 needs it gone",
            "status": "CARRIED"
          },
          {
            "id": "D3",
            "source": "docstring",
            "clause": "\"and the closed one alike\"",
            "assertion": ":65, :75",
            "excludes": "a delete keyed on the profile's remaining `likes` rows. The closed row from `_seed_undone_like` (:63) has no `likes` row, so a delete keyed that way would leave it and :75 would see 1",
            "status": "CARRIED"
          },
          {
            "id": "D4",
            "source": "docstring",
            "clause": "\"and keeps another profile's\"",
            "assertion": ":76",
            "excludes": "a delete that removes every profile's generations",
            "status": "CARRIED"
          },
          {
            "id": "D5",
            "source": "docstring",
            "clause": "\"A real Client backend ... serves POST /api/profile/delete\"",
            "assertion": ":72-73",
            "excludes": "an endpoint that is missing or refuses the keyed request. The status must be 204, sent to the real `client_backend` server",
            "status": "CARRIED"
          },
          {
            "id": "N1",
            "source": "name",
            "clause": "\"removes its open ... like_generations\"",
            "assertion": ":75",
            "excludes": "the same wrong implementation as D2",
            "status": "CARRIED"
          },
          {
            "id": "N2",
            "source": "name",
            "clause": "\"removes its ... closed like_generations\"",
            "assertion": ":75",
            "excludes": "the same wrong implementation as D3",
            "status": "CARRIED"
          },
          {
            "id": "N3",
            "source": "name",
            "clause": "\"keeps anothers\"",
            "assertion": ":76",
            "excludes": "the same wrong implementation as C1b",
            "status": "CARRIED"
          }
        ],
        "map_problem": ""
      }
    ]
  },
  "refactors": "<refactors>\nnone. The disk copies of users_store.py, server.py, profiles.py and random_videos.py match what was inlined, and none of the new code this build added needed restructuring.\n</refactors>\n\n<left_out>\nengine/server/data/random_videos.py: the three fetch_* functions repeat the same SELECT column list and the same row-to-dict loop. That repetition was there before this build. Phase 1 only changed the popular ORDER BY term and the params list, so pulling out a shared helper would change code this build never touched. It would also change fetch_recent_videos, which no checkpoint here covers.\nengine/server/data/random_videos.py: fetch_popular_videos builds params with its own two literal lists, one with the error threshold and one without. I kept that because the sibling functions build theirs the same way, and the two lists put each ? in SQL order where it is easy to see.\nclient/backend/lib/users_store.py: record_like calls like_generation separately rather than reading the generation back from the upsert with RETURNING. It costs one extra SELECT, but like_generation is also what close_like uses, and RETURNING would depend on the SQLite version in a way I haven't checked here.\nclient/backend/lib/users_store.py: get_or_create_user commits inside record_like, even though _store_reaction and _handle_likes_import call it within `with conn:`. That was true before this build. The likes and like_generations writes both come after that commit, so they still land together. Changing where commits happen would be a behaviour change, not a refactor.\nclient/backend/server.py: I left _store_reaction's three branches as they are. They return (publish, generation) in the same shape, and folding them together would mix the dislike path, which asks for centroids first, with the like paths, which don't.\nThe throwaway probes in tests/tmp (probe_cap.py, probe_13_phase2.py, probe_13_phase3.py, probe_like_generations.py) should be deleted. I have no delete tool, so they are still there. The step's \"What the pass is measured against\" section showed a blank placeholder ({rat_tail_rules}) instead of rules, so I checked the pass against the role's rat-tail and smallest-change rules.\n</left_out>\n\n<needs_fresh_red>\nnone\n</needs_fresh_red>\n\n<observation>\nNone of the build's new code (the popular signal cap, the like_generations tracking in record_like and close_like, the derived event ids in _handle_user_action, and the like_generations delete in delete_profile) needed restructuring. The only repetition in these files was there before the build, so the pass left all production code as it was and ran no tests.\n</observation>"
}
```
dev-flow:state -->

## Entries from earlier runs of this build

## 2026-09-27 - Step 0 - baseline

Resolved paths: {
  "active": "tests/active",
  "working": "tests/tmp",
  "plans": "docs/project/plans",
  "delete_me": "delete_me",
  "archive": "tests/archive",
  "project_dir": "/home/enduser/code/PeerTube-browser/.worktrees/fix-13-deterministic-event-ids",
  "record": "tests/last_test_validation.json",
  "output": "tests/last_test_output.txt"
}

Pre-build suite exited 0. Baseline variant: False.

```
unchanged since 2026-09-27T02:58:17-04:00 — every fingerprint still holds
  146 passed (46.7s)
```

## 2026-09-27 - Step 1 - Gather requirements

Approved by the operator.

### requirements

### Goal and purpose

Build issue `docs/project/issues/01-deterministic-event-ids.md` as triaged. It closes the security-audit finding that repeated `like` posts can push any video to the top of the Engine's popular ordering. Two changes do this. (1) The Client backend derives each interaction event's `event_id` deterministically, so the Engine's existing `ON CONFLICT(event_id) DO NOTHING` collapses replays at ingest. (2) The Engine caps how much the interaction signal can add in the popular ordering. Decisions: `docs/project/adr/0001-derived-interaction-event-ids.md` and `CONTEXT.md` **Interaction event** and **Interaction signal**. This build is plan 13, in wave 2 of the security hardening batch (issues 01-06, `.scratch/security-hardening-batch/notes.md`). It runs in the worktree `/home/enduser/code/PeerTube-browser/.worktrees/fix-13-deterministic-event-ids`, branched from main after plans 10-12 merged, and alongside plan 14.

### Current behavior (verified in the tree)

- `client/backend/server.py` `_handle_user_action` (currently around line 731) builds the event with `"event_id": f"client-{uuid4()}"` (around line 802). It sets `publish = action in ("like", "undo_like")`, so every like and undo_like is published even when nothing changed. `actor_id` is `profile_id or "anonymous"`. A dislike publishes an `UndoLike` only when `_store_reaction` reports that a like was removed.
- `_store_reaction(profile_id, action, video)` returns whether a dislike removed a like. It calls `record_like` in two places: the plain-like branch, and the "like replacing a dislike" branch. It calls `remove_like` in the undo_like branch and in the dislike branch.
- `client/backend/lib/users_store.py`: `record_like(conn, user_id, action, video, max_likes) -> None` upserts into `likes` (`ON CONFLICT ... DO UPDATE`), trims to `max_likes`, and commits. `remove_like(conn, user_id, video_id, instance_domain) -> bool` deletes the row and reports whether one was removed. The `likes` row is deleted on un-like, so there is no persistent per-video like instance.
- `_handle_likes_import` calls `record_like` and publishes nothing.
- `client/backend/lib/profiles.py` `delete_profile` deletes every row keyed to a profile (blocks, dislikes, dislike_profiles, likes, users, profiles) in one transaction.
- `engine/server/data/random_videos.py` `fetch_popular_videos` orders its inner subquery by `(v.popularity + COALESCE(sig.signal_score, 0)) DESC` (around line 247), then by `(v.likes + COALESCE(sig.likes_count, 0)) DESC`, then views, published_at and video_id.

### Requirements: like instance (generation)

- Add a new Client table, `like_generations(user_id, video_id, instance_domain, generation)`, keyed on `(user_id, video_id, instance_domain)`. Create it in `ensure_user_schema` with `CREATE TABLE IF NOT EXISTS`, in the same executescript style as the other tables.
- An un-like never deletes from `like_generations`, so the generation survives the un-like.
- When `record_like` inserts a new `likes` row, it increments that video's generation for the user, starting from 1 on the first like. Re-liking a video that is already liked leaves the generation unchanged.
- `record_like` reports whether the like was new and returns the current generation (for example, a `(new, generation)` pair). The exact return shape is the build's choice. The likes-import caller ignores the return value and must keep working unchanged.
- An `undo_like`, or a dislike that replaces a like, reads the video's current generation for the profile and removes the like with `remove_like`. It publishes only when `remove_like` reports that a like was removed. The generation it uses is the one the matching Like used.
- Anonymous actors (no resolvable `X-Profile-Key`) use the fixed generation `0`.
- `delete_profile` in `client/backend/lib/profiles.py` also deletes that profile's `like_generations` rows, in the same transaction.

### Requirements: derived event id

- The event id is `client-` followed by the SHA-256 hex digest of the joined fields `(actor, video_uuid, instance_domain, event_type, generation)`. Actor is the profile id, or `anonymous`. `event_type` is `Like` or `UndoLike`. The joining must be unambiguous (e.g. a separator that cannot confuse field boundaries). This replaces `client-<uuid4>`, and the `uuid4` import goes if nothing else uses it.
- Every publish of one like, and of the un-like that ends it, uses the same generation. A like made after that un-like uses a different one.
- The id never embeds raw user input unhashed. It is a non-empty string that the Engine's `normalize_event_payload` accepts.
- The payload's other fields (`event_type`, `actor_id`, `object`, `published_at`, `source_instance`, `raw_payload`) are unchanged.

### Requirements: publish on change only

- With a profile, a `like` publishes a `Like` only when the like is new. This covers the plain-like branch and a like that replaces a dislike.
- With a profile, an `undo_like` publishes an `UndoLike` only when a like was actually removed.
- A `dislike` that replaces a like publishes one `UndoLike`, with the id the matching profile `undo_like` would have used. A dislike on a video that is not liked publishes nothing. `undo_dislike` publishes nothing.
- A request that changes nothing still returns 200 `{"ok": True, "updatedAt": ...}` and publishes nothing.
- Anonymous `like` and `undo_like` always publish, with generation 0. Every anonymous `Like` on a video therefore carries one id, and every anonymous `UndoLike` carries another. Anonymous likes add at most +1 per video and anonymous un-likes subtract at most -1 (ADR-0001 §3, accepted).
- Error handling is unchanged: 400/404/502 paths, `DislikeLimitReached`, `EngineApiError`, and the centroids-before-write ordering.

### Requirements: ranking cap

- In `engine/server/data/random_videos.py`, add a module-level named constant (e.g. `POPULAR_SIGNAL_CAP = 25.0`). The popular-pool ordering becomes `(v.popularity + MIN(COALESCE(sig.signal_score, 0), <constant>)) DESC`, with the constant passed as a query parameter or interpolated from the constant, never a bare literal.
- `interaction_signals.signal_score` stays uncapped in storage. The `interaction_signal_score` column the query returns stays the raw value.
- The secondary likes tiebreaker is unchanged.

### Unchanged (must not be modified)

The Engine's `ingest_interaction_event()`, `normalize_event_payload()`, the `_event_deltas` weights, and the stored `signal_score`.

### Acceptance criteria

- Posting `like` twice for one video with one profile publishes exactly one `Like`. The video's `likes_count` rises by 1 and its `signal_score` by 1.0.
- A profile's like → undo_like → like sequence publishes Like, UndoLike, Like. The two `Like` events carry different `event_id`s, and the video ends with `signal_score` 1.0.
- Re-sending an identical, already-published event to the Engine (a bridge retry) is reported as `duplicate: true` and changes no counts.
- Two anonymous `like` posts for one video produce the same `event_id`, and the Engine counts the second as a duplicate.
- `undo_like` for a video the profile does not like publishes nothing and returns 200.
- A dislike replacing a like publishes one `UndoLike`, with the id the matching profile un-like would have used. A dislike on an unliked video publishes nothing.
- In the popular ordering, a video with `signal_score` 1000 and `popularity` 0 ranks below a video with `popularity` 30 and no signal.
- `delete_profile` removes the profile's `like_generations` rows.
- The existing interaction-event tests (`tests/active/test_interaction_events.py`, `tests/active/test_internal_events.py`, `tests/active/test_random_videos.py`) and the security-bundle / frontend suites in `tests/active` still pass.

### Out of scope

- Backfilling or rewriting events already stored with random ids.
- Changing Engine ingest, `_event_deltas`, or the stored `signal_score`.
- The secondary likes tiebreaker.
- `Comment` events.
- Rate limiting, or requiring a profile for likes.
- Making the likes-import path publish.
- Closing the `max_likes` trim gap. When the trim drops a like, the Engine keeps its +1, a later un-like publishes nothing, and a re-like gets a new generation. This gap exists today and is accepted.

### Consistency constraints

- Match the surrounding style: stdlib HTTP handlers, `respond_json`, module-level named constants, env vars read once at startup, stdlib only (`hashlib`). Keep the fewest files, and add no new abstractions with a single implementation.
- Backwards compatibility is not required beyond the above.
- Line numbers drift, so re-locate code by function name.
- Plan 14 edits other handlers in `server.py` and calls `record_like` from import, ignoring its return value. Keep the diff to `_handle_user_action`, `_store_reaction`, `record_like`, `ensure_user_schema`, `delete_profile` and `fetch_popular_videos` to limit merge conflicts.

### Test and run constraints

- Test trees: active `tests/active`, working `tests/tmp`, archive `tests/archive`, delete_me `delete_me`, plans `docs/project/plans`. Record: `tests/last_test_validation.json`. Output: `tests/last_test_output.txt`.
- Run `validate_tests.py` from the worktree root (`project_dir` = `/home/enduser/code/PeerTube-browser/.worktrees/fix-13-deterministic-event-ids`).
- Run Engine-backed test files in their own `validate_tests.py` invocations because of the Engine rate limit.
- The worktree symlinks main's `whitelist.db`, so test Engines share it with other lanes. Tests must use unique video/actor identities, or isolated DBs, so concurrent lanes do not collide.
- On merge, `tests/last_test_validation.json` and `tests/last_test_output.txt` will conflict. Take main's copy and re-run `validate_tests.py --compare` on the merged tree.

### Baseline suite state

Pre-build baseline: exit code 0, variant false (the suite passes before any change).

### conflicts

none

## 2026-09-27 - Step 2 - Develop a solution

Approved by the operator.

### initial_solution

### Approach

Two changes, one in each service. Both stay inside the six functions the requirements name, plus a small unavoidable edit to the import lines of `server.py`.

**1. Client: generation table and `record_like` (`client/backend/lib/users_store.py`).** `ensure_user_schema` gets one more `CREATE TABLE IF NOT EXISTS like_generations` in the existing executescript, placed before the `local-user` cleanup. It has `user_id`, `video_id`, `instance_domain` and an integer `generation`, with `(user_id, video_id, instance_domain)` as the primary key. `record_like` stops using `ON CONFLICT ... DO UPDATE` to find out whether a like is new. It first inserts the `likes` row with `ON CONFLICT DO NOTHING` and reads the cursor's rowcount: 1 means new, 0 means the video was already liked. When the row already exists it runs the old refresh of `video_uuid` and `updated_at` as a plain UPDATE, so recency ordering and the trim behave exactly as today. When the like is new it upserts `like_generations`: insert generation 1, or on conflict set generation to generation + 1. It then reads the current generation back and returns `(new, generation)`. The trim and the trailing commit are unchanged. The trim never drops the row just inserted, because that row is the newest. The likes-import caller already ignores the result, so it keeps working without edits. An imported new like still advances that video's generation, which the plan accepts (see Risks). Nothing ever deletes from `like_generations` except `delete_profile`, so a generation survives an un-like. This covers "increments on a new like, from 1", "unchanged on a re-like", and "the generation survives an un-like".

The un-like side needs to read a generation, and `server.py` holds no SQL. So `users_store.py` gains one small reader function. It returns the stored generation for `(user, video_id, instance_domain)`, or 0 when there is no row. `server.py` imports it next to `record_like` and `remove_like`. `remove_like` itself is not changed.

**2. Client: `_store_reaction` (`client/backend/server.py`).** Today it returns "did a dislike remove a like". It will return a `(changed, generation)` pair covering every branch:
- Plain like: the result of `record_like`.
- `undo_like`: read the generation, then `remove_like`, both inside the same `with conn` block. Returns `(removed, generation)`.
- Dislike: in its existing write transaction, read the generation before `remove_like` and `write_dislike`. Returns `(removed, generation)`. The centroids are still computed before any write, so the error ordering is unchanged.
- `undo_dislike`: returns `(False, 0)`.
- Like replacing a dislike: `delete_dislike` then `record_like`. Returns `record_like`'s pair. Likes and dislikes exclude each other, so this is always new.

The generation an un-like reads is the value the matching Like got when it was recorded. Only a later new like changes it. So a Like and the un-like that ends it share a generation, and the next Like gets a different one. The docstring's `:returns:` is updated.

**3. Client: `_handle_user_action`.**
- With a profile: `publish` becomes `changed`. A replayed like, an un-like of an unliked video, a dislike of an unliked video and every `undo_dislike` publish nothing. They fall through to the existing 200 `{"ok": True, "updatedAt": ...}` response.
- Without a profile: `publish` stays `action in ("like", "undo_like")` with generation 0. Dislike actions already require a profile, so anonymous input can only be a like or an undo_like.
- `event_type` keeps the existing rule (`Like` for `like`, otherwise `UndoLike`), so a dislike that removed a like produces an `UndoLike`. Its generation is the one the profile's `undo_like` would have read, so the id is identical.
- The id is `client-` plus the SHA-256 hex digest of `(actor, canonical_uuid, canonical_host, event_type, generation)`. The fields are serialised with `json.dumps` of a list, which is already imported. JSON quoting and escaping make field boundaries unambiguous whatever the field values contain.
- The id is 71 characters of hex and contains no raw input. `normalize_event_payload` only requires a non-empty string, and `event_id` is a TEXT primary key with no length limit, so it is accepted.
- `hashlib` is added to the stdlib imports. `uuid4` stays imported because `run_id` near the bottom of `server.py` still uses it, so the requirement to drop the import only if unused leaves it in place.
- The other payload fields, the 400/404/502 paths, `DislikeLimitReached`, `EngineApiError` and the bridge response are untouched.

**4. `delete_profile` (`client/backend/lib/profiles.py`).** One more `DELETE FROM like_generations WHERE user_id = ?` inside the existing `with conn` transaction.

**5. Engine: ranking cap (`engine/server/data/random_videos.py`).** A module-level `POPULAR_SIGNAL_CAP = 25.0`. The first ORDER BY term in `fetch_popular_videos`'s inner subquery becomes `popularity + MIN(COALESCE(signal_score, 0), ?)`, with the constant bound as a query parameter. The params list now holds, in order: the optional error threshold, the cap, the inner limit, the outer limit. Getting this order right is the one fiddly part. `COALESCE` sits inside `MIN`, so SQLite's two-argument scalar `MIN` never sees NULL. The outer `interaction_signal_score` column, the stored `signal_score` and the likes tiebreaker are unchanged. A signal of 1000 now counts as 25, which ranks below popularity 30.

**How the acceptance criteria follow:**
- Double like: the second post finds the row, `new` is false, nothing is published.
- like → undo → like: the ids use generations g, g, g+1, so the two Likes differ, the counts net +1 −1 +1, and `signal_score` ends at 1.0.
- Bridge retry: the same id hits the Engine's existing `ON CONFLICT DO NOTHING` and is reported as a duplicate.
- Anonymous: generation 0 gives one id per video, so the second post is a duplicate.
- The un-like, dislike, ranking and `delete_profile` criteria follow directly from sections 2 to 5.

**Tests:** new Client cases publish under fresh profiles, so their actor identities are unique per run. The anonymous criterion ("the second is a duplicate") holds on every run even against the shared `whitelist.db`. The ranking case uses an isolated in-memory Engine database, as `test_random_videos.py` already does.

### Alternatives considered

- **How to detect a new like.** Rejected: a SELECT for an existing row before the upsert. It adds a query and leaves a window where two concurrent requests both see "absent" and both publish. The conditional insert's rowcount is atomic at the statement level, so only one request ever sees "new".
- **Where the un-like's generation comes from.** Rejected: widening `remove_like` to return the generation. That changes a shared helper's signature for one caller. Rejected: inline SQL in `_store_reaction`, because `server.py` has no SQL anywhere. The small reader in `users_store.py` costs one extra name on an existing import line.
- **Hash input encoding.** Rejected: joining with a control-character separator such as `\x1f` or `\n`. It is only unambiguous if we can prove no field contains that character, and `video_uuid` and `instance_domain` come back from the Engine. JSON encoding needs no such proof.
- **Keying the id on the `likes` row's rowid or timestamp.** Rejected: the row is deleted on un-like, so rowids and timestamps are not stable, and timestamps can repeat.
- **Cap by interpolation versus a bound parameter.** Both are allowed. The parameter was chosen so the value never sits inside the SQL text. The cost is reordering the params list.
- **Capping at ingest.** Out of scope and rejected by ADR-0001: the stored score must stay raw so the cap can change without a migration.

### Risks and gotchas

- **Likes that predate `like_generations`** have no row, so an un-like reads generation 0. The resulting `UndoLike` still has a unique, profile-scoped id. It cannot collide with the anonymous generation-0 ids because the actor differs. The next new like starts that video at generation 1, so the sequence stays correct.
- **Imported likes** advance the generation without publishing. A later un-like then publishes an `UndoLike` for a Like id the Engine never saw. The count effect (−1) is what today's code already does, and import publishing is out of scope.
- **The `max_likes` trim gap** remains as accepted: the Engine keeps its +1, a later un-like publishes nothing, and a re-like gets a new generation.
- **Merge risk with plan 14:** besides the named functions, `server.py` gets two import-line edits (`hashlib`, and the new reader on the `users_store` import). If they conflict, resolve by union. `record_like`'s return value is additive, so plan 14's import caller, which ignores it, is unaffected.
- **Test runs publish into the shared `whitelist.db`.** Any anonymous Like or UndoLike a test sends for a real video permanently takes that video's single anonymous Like and UndoLike ids. New tests must therefore publish as fresh profiles or use an isolated Engine DB. The existing frontend-reactions tests assert browser-store state, not Engine counts, so they are unaffected.
- **Concurrency on the one shared SQLite connection** is unchanged. The existing rat-tail about unserialised read, compute and write for dislikes still applies.

### Tradeoffs the operator accepts

- **Anonymous likes collapse to at most +1 per video, and un-likes to at most −1.** Once an anonymous Like and UndoLike have both been stored for a video, anonymous visitors contribute nothing further to it, ever. This is ADR-0001 §3 as accepted.
- **The cap of 25.0 is a deliberate simplification.** One named constant bounds the signal's effect on ordering. It does nothing to stop the likes tiebreaker, which is uncapped and out of scope, from being inflated among videos that tie on the first term. To raise or lower the cap, edit the constant. If it ever needs to be configurable, the upgrade path is an env var read once at startup.
- **Events already stored with random ids stay as they are.** No backfill.

### conflicts

none

## 2026-09-27 - Step 3 - Identify every file, function and doc affected

Recorded ungated, at the operator direction.

### impacts

<impact path="client/backend/lib/users_store.py" element="ensure_user_schema() (lines 10-63): new like_generations table">
**What changes.** The existing executescript gets one more `CREATE TABLE IF NOT EXISTS like_generations (user_id TEXT NOT NULL, video_id TEXT NOT NULL, instance_domain TEXT NOT NULL, generation INTEGER NOT NULL, PRIMARY KEY (user_id, video_id, instance_domain))`. It goes after `dislike_profiles` (lines 53-58) and before the `local-user` cleanup comment and DELETEs (lines 59-61). The docstring (line 11), "Create the users, likes, profile, block and dislike tables if missing.", should also name the like generations table.

**Should the local-user cleanup cover this table?** Generation rows keyed to `local-user` cannot exist, because the table is new, so no extra `DELETE` is needed.

**What depends on it.**
- `client/backend/server.py:1179` `main()` calls it once at startup against `client/backend/db/users.db`, so the live DB gains the table on the first restart.
- `tests/active/conftest.py:73` (`client_backend`) and `:160` (`_engine_client`) call it on every fixture DB.
- Test helpers call `record_like` on a raw `sqlite3.connect` after the fixture has run the schema: `tests/active/test_profiles.py:41-46` and `tests/active/test_frontend_profile.py:106-111`. They therefore rely on the fixture having created `like_generations`.

**Regression risk: low.** `CREATE TABLE IF NOT EXISTS` is idempotent. Any caller that writes via `record_like` on a DB where `ensure_user_schema` never ran now fails with "no such table: like_generations", where before only `likes`/`users` were needed. I found no such caller: every path runs the schema first. Separately, `engine/server/data/users.py` has its own `ensure_user_schema`/`record_like` (lines 11-85) that are Engine-side duplicates and are NOT touched. They must not be confused with the Client module.
</impact>
<impact path="client/backend/lib/users_store.py" element="record_like() (lines 79-117): new-like detection, generation upsert, return (new, generation)">
**What changes.**
- The single `INSERT ... ON CONFLICT DO UPDATE` (lines 94-102) becomes `INSERT ... ON CONFLICT(user_id, video_id, instance_domain) DO NOTHING`, and `cursor.rowcount` is read: 1 means new, 0 means existing. CPython's sqlite3 reports 0 for a DO-NOTHING conflict.
- When the row exists, a plain `UPDATE likes SET video_uuid = ?, updated_at = ? WHERE user_id = ? AND video_id = ? AND instance_domain = ?` keeps today's recency refresh.
- When the like is new, `INSERT INTO like_generations ... VALUES (?, ?, ?, 1) ON CONFLICT(...) DO UPDATE SET generation = like_generations.generation + 1`.
- The current generation is read back and returned. The return annotation changes from `-> None` to `-> tuple[bool, int]`, and the docstring (line 86) gains `:returns:`.
- The `max_likes` trim (lines 103-116) and the trailing `conn.commit()` (line 117) are unchanged.

**What depends on it.** Five callers, all ignoring or consuming the result:
- `server.py:846`, the plain-like branch of `_store_reaction`, which now consumes it.
- `server.py:869`, the like-replacing-a-dislike branch, which now consumes it.
- `server.py:898`, `_handle_likes_import`, which ignores it. Plan 14 also edits this caller.
- `tests/active/test_profiles.py:44`, which ignores it.
- `tests/active/test_frontend_profile.py:109`, which ignores it.

**Transaction and commit behaviour.**
- `get_or_create_user` (line 89) commits on its own when it inserts a user, and `record_like` commits at the end.
- In `_store_reaction` it runs inside `with conn:`, so the commit inside it commits the enclosing transaction early. This is the pre-existing ordering documented in `docs/project/plans/archive/03-like-dislike.md:430`, where `delete_dislike` runs first so `record_like`'s commit covers both.
- The generation upsert and read happen before that commit, so they are atomic with the like insert.

**Regression risk: medium.**
1. **Uncapped `updated_at` ties in a bulk import.** The trim orders by `updated_at DESC` with `LIMIT max_likes` (`MAX_LIKES = 100`, `server.py:51`). The likes import can bring up to `MAX_CLIENT_LIKES = 200` (`server.py:52`) in one transaction, and many rows share one `now_ms()`. The "just inserted row is newest, so never trimmed" claim then does not strictly hold. A tie at the boundary can trim a row whose generation was just advanced. The effect is harmless, since the next like just takes generation+1, but the plan's statement is only true for single likes.
2. **`like_generations` survives `clear_likes`.** `/api/user-profile/reset` (`server.py:987-988`) runs `clear_likes`, which deletes only `likes`, publishes nothing, and leaves generations. A re-like after a reset is new and gets generation+1, so a fresh id and a +1 on top of the Engine's earlier +1. That matches today's behaviour (today every like adds +1), so it is not a regression, but it is a second way besides the trim for the Engine count to drift.
3. **The read-back must work on connections without `row_factory`.** The server's `connect_db` (`server.py:144-145`) and the test helpers set `sqlite3.Row`. Reading with `row[0]` is safe either way.
4. The new-like detection must stay atomic, meaning rowcount comes from the INSERT itself and not a prior SELECT, as the plan says.
</impact>
<impact path="client/backend/lib/users_store.py" element="new generation reader function (placed near remove_like, lines 159-168)">
**What changes.** A new function returns the stored `generation` for `(user_id, video_id, instance_domain)`, or 0 when there is no row. It should match the file's style:
- a one-line docstring plus `:returns:`, like `remove_like`;
- positional `conn, user_id, video_id, instance_domain` so it can be called as `reader(conn, profile_id, *key)`, which is how `_store_reaction` calls `remove_like`;
- no commit, "inside the caller's transaction".

**What depends on it.** Only `_store_reaction` (the undo_like and dislike branches), through a new name on the `lib.users_store` import at `server.py:37-39`. New tests may also call it directly.

**Regression risk: low.** It must be read BEFORE `remove_like` in each branch. The value is the same either way, since `remove_like` never touches `like_generations`, but reading first keeps the intent clear. The 0 returned for a missing row is also the anonymous generation, which is safe only because the actor field differs: profile id versus `"anonymous"`.
</impact>
<impact path="client/backend/lib/users_store.py" element="remove_like() (lines 159-168), clear_likes() (153-156), video_reaction() (171-182), fetch_recent_likes(), load_liked_keys(): unchanged">
**What changes.** Nothing. The plan explicitly keeps `remove_like`'s signature.

**What depends on it.** `remove_like` is called at `server.py:848` (undo_like) and `:861` (dislike). `clear_likes` is called at `server.py:988` (reset). `clear_likes` does not delete `like_generations`, which is correct: generations must survive un-likes and resets so that later ids are fresh.

**Regression risk: none.** Listed so the reset path's interaction with generations is on record (see the `record_like` entry).
</impact>
<impact path="client/backend/server.py" element="stdlib import block (lines 5-22): add hashlib; keep uuid4">
**What changes.** `import hashlib` is added in alphabetical position between `argparse` (line 5) and `ipaddress` (line 6). The file sorts stdlib `import x` lines alphabetically: argparse, ipaddress, json, logging, ...

`from uuid import uuid4` (line 21) must stay. Checked: `run_id = str(uuid4())` at line 1155 is used at lines 1198 and 1213.

**What depends on it.** The new event-id derivation in `_handle_user_action`.

**Regression risk: nil.** It is a merge-conflict point with plan 14 if that plan touches the import block; resolve by union.
</impact>
<impact path="client/backend/server.py" element="lib.users_store import (lines 37-39): add the generation reader">
**What changes.** The new reader's name is added to the parenthesised, alphabetised import `(clear_likes, ensure_user_schema, fetch_recent_likes, get_or_create_user, load_liked_keys, record_like, remove_like, video_reaction)`, in sorted position. For example, `like_generation` would fall after `get_or_create_user` and before `load_liked_keys`.

**What depends on it.** `tests/active/conftest.py:39` does `import server as client_server`, so an ImportError here breaks every test in `tests/active`.

**Regression risk: low.** Any misspelling fails at import time, so it is loud. This is a merge-conflict point with plan 14.
</impact>
<impact path="client/backend/server.py" element="ClientBackendHandler._store_reaction() (lines 831-870): returns (changed, generation)">
**What changes.** The return type changes from `bool` to a pair, and the docstring's `:returns:` (line 837) is rewritten. Per branch:
- **Plain like** (line 846): return `record_like(...)`. The `with conn:` block must capture the value.
- **undo_like** (line 848): inside the same `with conn:`, read the generation, then `removed = remove_like(...)`, and return `(removed, generation)`. Today this branch returns `False` (line 849), so `publish` came only from `action in ("like","undo_like")`.
- **dislike** (lines 860-863): inside the existing `with conn:`, read the generation before `remove_like` and `write_dislike`, and return `(like_removed, generation)`. `compute_dislike_centroids` (line 859) and the `DislikeLimitReached` check (lines 856-857) still run before any write.
- **undo_dislike** (lines 866-870, `action != "like"`): return `(False, 0)`.
- **like replacing a dislike** (line 869): return `record_like`'s pair. This is always new, because `write_dislike` implies no `likes` row. One uncertainty: nothing in `lib/dislikes.py` enforces that exclusivity at the DB level. It holds only because every path removes the other reaction. If a `likes` row somehow co-existed with a dislike, this branch would return `new=False` and publish nothing, which is the correct outcome anyway.

**What depends on it.** Only `_handle_user_action` (line 787). The rat-tail comment (lines 853-854) about unserialised read, compute and write stays true.

**Regression risk: medium.** This is the correctness core of "a Like and its un-like share a generation".
- **Early return.** The existing early `return False` at line 849 sits after the `with` block, so the new value must be captured inside the block and returned after it.
- **Concurrency on the single shared connection.** The server is a `ThreadingHTTPServer` with one `check_same_thread=False` connection (`server.py:144`). Two concurrent undo_likes on one profile and video can both read generation g. Only one `remove_like` then sees rowcount 1, so only one publishes. That is safe.
- **Concurrent like and undo_like.** These can interleave, so the undo reads g before the like's upsert commits. The outcome is still consistent, because the like either existed before or not. This is the same class of race as the existing rat-tail.
</impact>
<impact path="client/backend/server.py" element="ClientBackendHandler._handle_user_action() (lines 731-829): publish gating and derived event_id">
**What changes.**
- Line 784 `publish = action in ("like", "undo_like")` stays as the anonymous default.
- In the profile branch (lines 785-795), `like_removed = self._store_reaction(...)` becomes `changed, generation = ...`, and `publish = changed` replaces `publish = publish or like_removed` (line 795). The comment at line 794 should be reworded to "publishes only on a real change".
- The anonymous generation is 0.
- Line 802 `"event_id": f"client-{uuid4()}"` becomes `client-` + `hashlib.sha256(json.dumps([actor, canonical_uuid, canonical_host, event_type, generation]).encode(...)).hexdigest()`, where `actor = profile_id or "anonymous"`. That is the same expression as `actor_id` (line 804), so it should be computed once.
- `event_type` (line 800) is unchanged.
- The docstring "Handle handle user action." (line 732) could state the publish rule.

**Behaviour changes callers can see.**
- With a key, a repeat `like` of a held video now returns 200 `{"ok": true, "updatedAt"}` and publishes nothing, where before it published and returned `{"ok","bridge_ok","bridge_error","updatedAt"}`. This is also 200 on the `unpublished_client` (activitypub) Client, which used to answer 502.
- With a key, an `undo_like` of an unliked video returns 200 with no publish, even on an unpublished Client, where it used to answer 502.
- Anonymous likes and un-likes always publish, as before, and still answer 502 on an unpublished Client (`test_frontend_reactions.py:249-258` relies on this).

**Hashing details.** `json.dumps` defaults (`ensure_ascii=True`, `", "` separators) must stay fixed forever, since changing them changes every id. `generation` must be an `int`, not a `bool` or `str`, or the same logical id serialises differently. `canonical_uuid` may be `""` when the Engine resolves a video without a uuid (line 774). The Engine then rejects the event with "Missing object.video_uuid" (`interaction_events.py:208-209`), which is unchanged behaviour. The id would still be well-formed.

**What depends on it.**
- The frontend `sendUserAction` (`client/frontend/src/data/user-actions.ts:33`) checks only `response.ok`, so a 200 without `bridge_ok` is fine.
- The Engine bridge `/internal/events/ingest` answers a duplicate with 200 `ok: true` (`engine/server/api/handlers/internal_events.py:68-91`). `_publish_to_engine_bridge` (`server.py:1032-1051`) maps that to `ok=True`, so a replayed anonymous like still answers 200 `bridge_ok: true`.
- `tests/run-arch-split-smoke.sh:584-602` and `tests/run-installers-smoke.sh:649-669` validate `ok`, `bridge_ok` and empty `bridge_error` after a like by a freshly minted profile. That like is always new, so it still publishes. If minting fails, the like is anonymous. The anonymous id for that seed video is then shared across smoke runs and later reported as a duplicate, which still gives `bridge_ok: true`.

**Regression risk: medium-high.** This is the security fix itself. Mistakes that would silently reopen the finding or break the contract:
- publishing when `changed` is False;
- computing the id before `event_type`;
- using a different generation for an undo than for its Like;
- hashing `profile_id` as `None` rather than `"anonymous"`.

The 400/404/502 paths, `DislikeLimitReached`, `EngineApiError` and the bridge response shape are unchanged. `raw_payload: body` (line 812) is still sent unhashed in the payload, as today, which is out of scope. The requirement only concerns the id.
</impact>
<impact path="client/backend/server.py" element="_handle_likes_import() (lines 872-900): record_like caller, unchanged">
**What changes.** Nothing in code. `record_like` at line 898 now returns a pair, which is ignored, and `imported += 1` still counts every non-disliked resolved video.

**What depends on it.**
- Plan 14 edits this handler, so a merge conflict is possible only if either plan touches line 898.
- `tests/active/test_profiles.py:245-253` and `tests/active/test_frontend_reactions.py:350-374` exercise it.

**Regression risk: low.**
- Behaviour change: each imported NEW like now advances that video's generation without publishing. A later profile un-like then publishes an `UndoLike` with that generation, for a Like id the Engine never saw. Its −1 effect is identical to today's. The plan accepts this.
- An import of up to 200 items against `MAX_LIKES = 100` can trim newly inserted rows (see the `record_like` entry).
</impact>
<impact path="client/backend/server.py" element="_publish_to_engine_bridge() / _publish_event() (lines 1032-1064), unchanged">
**What changes.** Nothing.

**What depends on it.** The "bridge retry is a duplicate" criterion. The Engine returns `{"ok": true, "duplicates": 1, "results": [{"duplicate": true, ...}]}`, and this function returns `{"ok": True, "response": parsed}`. The handler exposes only `ok`/`bridge_ok`, not `duplicate`, so a test of "the second is a duplicate" must read the Engine DB or post to `/internal/events/ingest` directly. It cannot use the Client response.

**Regression risk: none.** It constrains how the new tests observe duplicates.
</impact>
<impact path="client/backend/lib/profiles.py" element="delete_profile() (lines 69-80)">
**What changes.** One more `conn.execute("DELETE FROM like_generations WHERE user_id = ?", (profile_id,))` inside the existing `with conn:` block, in the same style. It belongs next to the `likes` delete (line 78), since both key on `user_id`. The docstring, "every row keyed to it", stays true.

**What depends on it.**
- `server.py:340-345` (`POST /api/profile/delete`).
- `tests/active/test_profiles.py:197-217`. Its `_rows_for` (lines 59-67) counts only profiles, users and likes, so the new criterion needs either an extra count there or a new test.
- `tests/run-installers-smoke.sh:444-457,683`, which deletes the smoke profile after the like.

**Regression risk: low.** This function runs on DBs where `ensure_user_schema` has run: server startup and every fixture. If it ever ran on a DB without the table, the whole transaction would fail with "no such table". No such path exists.
</impact>
<impact path="engine/server/data/random_videos.py" element="new module-level POPULAR_SIGNAL_CAP constant">
**What changes.** `POPULAR_SIGNAL_CAP = 25.0` goes after the imports (after line 9), with a `#` comment above it in the house style (compare `MAX_RAW_PAYLOAD_BYTES` in `interaction_events.py:13-14`). This module has no constants today.

**What depends on it.** `fetch_popular_videos`, and the new ranking test, which may import it.

**Regression risk: nil.**
</impact>
<impact path="engine/server/data/random_videos.py" element="fetch_popular_videos() (lines 195-303): capped ORDER BY term and params order">
**What changes.** Line 247 `(v.popularity + COALESCE(sig.signal_score, 0)) DESC` becomes `(v.popularity + MIN(COALESCE(sig.signal_score, 0), ?)) DESC`. The params lists (lines 200 and 203) must become:
- `[POPULAR_SIGNAL_CAP, limit, limit]`;
- `[error_threshold, POPULAR_SIGNAL_CAP, limit, limit]` when the error clause is present.

That order matches the placeholder order in the SQL: the error `?` in the inner WHERE (line 245), then the ORDER BY cap `?` (247), then the inner `LIMIT ?` (252), then the outer `LIMIT ?` (262).

Unchanged: line 234 `COALESCE(sig.signal_score, 0) AS interaction_signal_score` stays raw, and the tiebreaker at line 248 is unchanged. The docstring "by likes/views" (line 198) could mention the capped signal.

**What depends on it.**
- `engine/server/api/server.py:86-90,398` wires it as `deps.fetch_popular_videos`.
- `engine/server/api/recommendations/builder.py:109-113` wraps it with `error_threshold=settings.video_error_threshold`. That is `VIDEO_ERROR_THRESHOLD` via `server.py:264,407`, so production normally takes the 4-param branch.
- `engine/server/api/recommendations/candidates/popular_videos.py:52` consumes the pool, and does not read `interaction_signal_score`.
- `tests/active/test_random_videos.py:85` calls it with no threshold, the 3-param branch. Line 118 asserts `interaction_signal_score` is raw 1.0.

**Regression risk: medium.**
- **Swapped parameters.** Getting the params order wrong does not raise, because every placeholder takes a number. It silently turns the cap into the LIMIT or the threshold. For example, `[error_threshold, limit, cap, limit]` would cap the signal at `limit` and LIMIT the pool to 25.
- **Only the no-threshold branch is tested.** The existing tests take only that branch, so the production branch needs its own test case, with an `error_threshold > 0`.
- **Two-argument MIN.** SQLite's two-argument `MIN` is the scalar function and returns NULL if any argument is NULL. `COALESCE` inside it avoids that, and the cap parameter is never NULL.
- **Type affinity.** The cap is bound as a Python float, so `MIN(int_or_real, 25.0)` compares numerically.
- **Ordering changes on the live dataset.** Any video with `signal_score` above 25 drops in the popular pool. That is intended.
</impact>
<impact path="engine/server/data/random_videos.py" element="fetch_random_rows(), fetch_recent_videos(), fetch_random_rows_from_cache(): unchanged">
**What changes.** Nothing. `fetch_random_rows` keeps `(v.likes + COALESCE(sig.likes_count, 0)) AS likes` (line 45), which is the likes figure and not the ranking signal.

**Regression risk: none.** Listed so the cap is not applied to the wrong query.
</impact>
<impact path="engine/server/data/interaction_events.py" element="ingest_interaction_event() / normalize_event_payload() / _event_deltas() / prune_interaction_raw_events(): unchanged, relied upon">
**What changes.** Nothing. This is a requirement.

**What depends on it.**
- The collapsing relies on `ON CONFLICT(event_id) DO NOTHING` (line 85) and on the `rowcount == 0` duplicate return (lines 100-109).
- `normalize_event_payload` requires only a non-empty stripped string `event_id` (lines 194-198), so a 71-character `client-<hex>` id is accepted.
- `event_id TEXT PRIMARY KEY` (line 24) has no length limit.
- The retention prune (lines 150-189) strips payload and actor but keeps `event_id`, so derived ids keep collapsing replays after the 30-day window (ADR-0005).

**Regression risk: none from this build.** One interaction to record: `tests/run-installers-smoke.sh:498-585` `cleanup_engine_test_events` DELETEs raw rows by `actor_id`. For the smoke's own freshly minted and then deleted profile this is harmless, since no one can replay that actor.
</impact>
<impact path="engine/server/data/users.py" element="Engine-side duplicate ensure_user_schema()/record_like() (lines 11-85): NOT touched">
**What changes.** Nothing. It is a separate Engine module with the same function names as the Client's `users_store`.

**What depends on it.** Nothing in this build. `client/backend` must not import `engine.*` (`client/README.md:43`).

**Regression risk: none, as long as the implementer edits the right file.** A grep for `def record_like` finds both. The Client one is `client/backend/lib/users_store.py:79`.
</impact>
<impact path="engine/server/api/handlers/internal_events.py" element="handle_internal_events_ingest() duplicate accounting (lines 58-91), unchanged">
**What changes.** Nothing.

**What depends on it.** The "bridge retry reported as `duplicate: true`" and "anonymous second like is a duplicate" criteria. The response's `results[i].duplicate` and `duplicates` count are the observable. The route is served only when `ENGINE_INGEST_MODE=bridge`, which the `engine` fixture sets (`conftest.py:105`).

**Regression risk: none.** New tests can post a derived-id payload twice directly here, or read `interaction_raw_events`, to observe duplicates.
</impact>
<impact path="tests/active/test_random_videos.py" element="existing popular-order tests (lines 108-122) and _two_video_db/_event helpers (34-77); home for the new ranking test">
**What changes.** The existing tests must stay green.
- `test_an_undone_like_keeps_the_popular_order_of_two_tied_videos` uses signal 1.0, which is under the cap, and asserts the raw `interaction_signal_score == 1.0` (line 119). Both hold after the change.
- The new criterion ("signal 1000 and popularity 0 below popularity 30 and no signal") fits here. Use `_two_video_db` and `UPDATE videos SET popularity`. Set the signal either with a direct `INSERT INTO interaction_signals` or with 1000 ingested Likes, and prefer the direct insert.
- It should cover both param branches (with and without `error_threshold`). `_set_views` sets `error_count = 0`, so a threshold of 1 keeps both rows.

**What depends on it.** `.un/skills/devsecops/config.json:87-88` maps `test_random_videos.py` to `engine/server/data/random_videos.py`, so the group re-runs on that change.

**Regression risk: low.** The file already uses an isolated `tmp_path` DB, so it does not touch the live `whitelist.db`.
</impact>
<impact path="tests/active/test_profiles.py" element="_seed_like (41-46), _rows_for (59-67), test_deleting_a_profile_removes_its_rows_and_keeps_anothers (197-217)">
**What changes.**
- `_seed_like` calls `record_like` on a raw connection. It now also writes a `like_generations` row, which works because the fixture ran `ensure_user_schema`, and it ignores the new return value.
- The delete test is the natural place for the "`delete_profile` removes the profile's `like_generations` rows" criterion. Add `like_generations` to `_rows_for`, which then expects `{"profiles": 1, "users": 1, "likes": 1, "like_generations": 1}` before the delete and 0 after, with the kept profile still at 1.
- The comment at line 201 ("record_like also creates the `users` row, so all three tables hold rows for both") would become "four tables".

**What depends on it.** `config.json:18-21` maps it to `server.py`, `profiles.py` and `users_store.py`.

**Regression risk: low.** The existing equality assertions on `_rows_for` must be updated together with the dict, or they fail.
</impact>
<impact path="tests/active/test_frontend_profile.py" element="_seed_like (106-111)">
**What changes.** Nothing required. It calls `record_like` on a raw connection over a `client_backend` DB that already has the table, and ignores the return value.

**Regression risk: low.** It would break only if the fixture stopped running the schema.
</impact>
<impact path="tests/active/test_frontend_reactions.py" element="keyless engine_client tests (202-258) and keyed sequence test (264-308, 311-340)">
**What changes.** Nothing in the file. Its behaviour against the shared live `whitelist.db` changes.
- **Keyless tests.** They publish anonymous Like/UndoLike for the first rows of `_videos(dataset, n)`, which are deterministic across runs. After this build each of those videos has exactly one anonymous Like id and one anonymous UndoLike id. The first run after the change nets +1−1. Every later run gets `duplicate` for both and is still answered 200 `ok`. Assertions check only `"ok" in ...` and browser-store state, so they hold.
- **The finally blocks** (lines 213-214 and 239-240) that send a withdrawing anonymous `undo_like` become no-ops after the first run, since they are duplicates.
- **Keyed sequence** (lines 264-303): like (new, g1, publish), dislike on liked (removed, UndoLike g1), undo_dislike (no publish, 200 `{ok}`), out-of-band dislike on unliked (200, no publish), like on disliked (new, g2, publish), undo_like (removed, UndoLike g2). Every step answers 200, so `all("ok" in a ...)` (line 303) holds.
- **`_withdraw_if_liked`** (lines 193-196) acts only if the profile still likes the video.

**What depends on it.** Shared-DB state across lanes and runs.

**Regression risk: low for assertions, medium for shared data.**
- The first post-change run permanently claims the anonymous Like and UndoLike ids for those dataset videos. A new test asserting "the second anonymous like is a duplicate" passes, and one asserting "the first anonymous like counts +1" would fail on any run after the first.
- If a run dies between the anonymous Like and its UndoLike, the video keeps +1 forever: the retry's UndoLike is new (−1 applies once), but any future anonymous Like is a duplicate. This is acceptable per ADR-0001 §3.
</impact>
<impact path="tests/active/test_dislikes.py" element="test_a_video_s_reaction_follows_like_dislike_undo_dislike_and_a_like_replacing_a_dislike (68-87) and _profile_disliking (118-123)">
**What changes.** Nothing. It runs on `unpublished_client`.
- The first like is new, so it publishes and gets a 502, which is not asserted.
- The dislike on the liked video removes the like and publishes an UndoLike, giving a 502. The test already accepts `in (200, 502)` (line 77).
- `undo_dislike` gives 200 (line 82), and a dislike on an unliked video gives 200 (line 84).
- The final like replacing a dislike is new and gets a 502, not asserted.
- `_profile_disliking` expects 200 for a dislike on an unliked video, which is unchanged.

**Regression risk: none.**
</impact>
<impact path="tests/active/test_server.py" element="keyed likes loop on unpublished_client (lines 86-102)">
**What changes.** Nothing. Each like is on a distinct search row, so it is new, publishes and gets the 502 the comment at line 92 describes. Status is not asserted. The dislikes that follow on unliked videos return 200 (line 102).

**Regression risk: none.** If a row appeared twice in `_search(client, "linux", 5)`, the set dedups it, so there are no repeats.
</impact>
<impact path="tests/active/test_profiles.py" element="test_a_keyed_search_marks_... (291-313) and test_a_keyed_upnext_request_is_seeded_... (264-282)">
**What changes.** Nothing. The fresh-profile like of `liked` is new, so it still answers 502 on `unpublished_client` (line 300 expects 502). The dislike on an unliked row still answers 200.

**Regression risk: none.** The line-300 expectation is a guard: it would catch the like wrongly being treated as not-new (a 200).
</impact>
<impact path="tests/active (new test file(s) for this build)" element="new Client acceptance tests for publish-on-change, derived ids, dislike UndoLike id, delete_profile, and anonymous duplicate">
**What changes.** New tests.

**Observing events.** The Client response does not expose event ids or duplicate flags. The tests therefore need one of these:
- (a) `engine_client` plus reading the live `interaction_raw_events`/`interaction_signals` by the fresh profile id. `dataset` is a read-only connection to the same `whitelist.db`, and WAL visibility applies.
- (b) A capturing stand-in Engine server that records the posted payloads and answers `{"ok": true}` for `/internal/events/ingest` and `/internal/videos/resolve`. The trusted-proxy build used this pattern in `tests/active/test_server.py:~300-310` (`received.append(self.headers.get("x-client-ip"))`).

Option (b) isolates the test from the shared DB and from the Engine rate limit. It needs a resolve response shaped like `resolve_video_seed` expects (`client/backend/lib/engine_api_client.py`, not opened here, so the exact shape is unverified).

**Isolation.** Profile-keyed tests must mint fresh profiles, so their actor ids are unique per run.

**Anonymous test.** It must assert only "second is a duplicate" or "same id", never "first counts", because the shared DB makes the first-ever post non-repeatable.

**What depends on it.** `validate_tests.py` discovers `tests/active/test_*.py`. Engine-backed files run in their own invocation.

**Regression risk: medium for suite stability.** Tests that increment `signal_score` on real dataset videos under a fresh profile leave a permanent +1 unless they undo it. Follow the existing withdraw-in-finally convention.
</impact>
<impact path="tests/run-installers-smoke.sh" element="run_interaction_check_for_contour() like flow (649-686), verify_engine_event_recorded (459-496), cleanup_engine_test_events (498-585)">
**What changes.** Nothing.
- The fresh profile's like is new, so it publishes and `bridge_ok` is true (`validate_user_action_ok`, lines 407-425).
- The raw event row exists under `actor_id = profile_id`.
- The cleanup deletes that row and recomputes signals from the remaining raw rows.
- `delete_client_test_profile` now also removes `like_generations`.

**Regression risk: low.** If the mint fails (`user_id=""`), the like is anonymous and its id is shared across smoke runs, so it is a duplicate after the first run. The verification looks for `actor_id = ''` and fails anyway, as it does today.
</impact>
<impact path="tests/run-arch-split-smoke.sh" element="client_user_action like + validate_user_action_response (lines 330-346, 584-602)">
**What changes.** Nothing. A freshly minted profile's first like is new, so it publishes and `ok`, `bridge_ok` and empty `bridge_error` hold.

**Regression risk: low.** The smoke would break only if the like were not new, for example if the smoke re-used a persisted profile key, which it does not.
</impact>
<impact path="engine/server/db/jobs/tests/test-interaction-events.py" element="ingest idempotency contract script">
**What changes.** Nothing. The acceptance criteria say the existing interaction-event and security-bundle suites must still pass.

**Regression risk: none.** It is not collected by `validate_tests.py`, so it must be run explicitly, like `engine/server/db/jobs/tests/test-security-bundle.py`.
</impact>
<impact path="engine/server/db/jobs/tests/test-security-bundle.py" element="security bundle checks">
**What changes.** Nothing. It is named in the acceptance criteria as needing to pass.

**Regression risk: none expected.** I did not open it in detail. A grep found no Client event-id or `fetch_popular_videos` reference in it. It must be run explicitly.
</impact>
<impact path=".un/skills/devsecops/config.json" element="test_groups map (test_profiles.py lines 18-21, test_random_videos.py 87-88, other groups at 37-40, 45-46, 57-85 listing server.py/users_store.py/profiles.py)">
**What changes.** Nothing in this worktree. Any new test file is unmapped, so it runs on every invocation until harvest adds an entry mapping it to `client/backend/server.py`, `client/backend/lib/users_store.py`, `client/backend/lib/profiles.py` and/or `engine/server/data/random_videos.py`.

**Regression risk: low.** The existing mappings already make an edit to `server.py`, `users_store.py`, `profiles.py` or `random_videos.py` re-run the affected groups.
</impact>
<impact path="tests/last_test_validation.json" element="tracked suite record">
**What changes.** It is rewritten by the post-build `validate_tests.py` run.

**Regression risk: none functionally.** It conflicts on merge: take main's copy and re-run `--compare` on the merged tree.
</impact>
<impact path="tests/last_test_output.txt" element="tracked captured output">
**What changes.** It is rewritten by the post-build run.

**Regression risk: none.** Resolve its merge conflict the same way as `last_test_validation.json`.
</impact>
<impact path="client/frontend/src/data/user-actions.ts" element="sendUserAction() (lines 18-38), unchanged">
**What changes.** Nothing. It treats any 2xx as success and ignores the body, so the new 200 `{ok, updatedAt}` answer to a no-change keyed like or un-like, with no `bridge_ok`, is accepted.

**Regression risk: none.** One side-effect: a keyed repeat like on a Client that cannot publish now succeeds (200) where it used to throw "Failed to send action". That is correct, since nothing needs publishing.
</impact>

### docs_checklist

<doc path="client/README.md">
Line 19 (`POST /api/user-action`): today it says "A like publishes its event and is kept server-side only when a profile key is sent", which implies every like publishes. It should say that with a key, a `like` publishes a `Like` only when the profile did not already like the video, an `undo_like` publishes an `UndoLike` only when a like was removed, and a request that changes nothing answers 200 and publishes nothing. Without a key every like and un-like publishes, but under one fixed id per video and event type, so repeats are duplicates. Event ids are derived (`client-` plus the SHA-256 of actor, video, event type and like generation), not random.

Line 13 (`POST /api/profile/delete`, "likes, dislikes, taste vectors and blocks"): optionally add "like generations".
</doc>
<doc path="DEPLOYMENT.md">
Lines 259-261 and 267: optionally add a sentence saying that the Client backend publishes a profile's `Like`/`UndoLike` only on a real state change, with derived event ids, so replays collapse at the Engine's ingest, and that the popular ordering adds at most 25.0 of a video's interaction signal (`POPULAR_SIGNAL_CAP` in `engine/server/data/random_videos.py`). `users.db` gains a `like_generations` table, which is created automatically at startup, so no migration step is needed.
</doc>
<doc path="engine/server/api/recommendations/docs/OVERVIEW.md">
Line 99 ("popular pool: top by likes/views"): optionally state that the pool is ordered by `popularity` plus the interaction signal capped at `POPULAR_SIGNAL_CAP` (25.0), then by likes, views and recency.
</doc>
<doc path="CONTEXT.md">
Verify only. **Interaction event** (line 6) already says ids are "derived, never random", and **Interaction signal** (line 7) already says the popular ordering adds at most a fixed cap. Both match this build, so no edit is expected. Optionally define **like generation** (the per-profile, per-video counter that tells one like from the next) if the term will be used elsewhere.
</doc>
<doc path="docs/project/adr/0001-derived-interaction-event-ids.md">
The decision is unchanged. Optionally add to Consequences the chosen like-instance scheme and its accepted edges:
- the Client's `like_generations` table, which survives un-likes and resets and is deleted only with the profile;
- likes that predate the table un-like with generation 0;
- imported likes advance the generation without publishing.
</doc>
<doc path="docs/project/issues/01-deterministic-event-ids.md">
At harvest, on main: tick the acceptance criteria, set `Status:` to `bug, complete`, and move the file to `docs/project/issues/archive/` per `docs/project/triage-labels.md`.
</doc>
<doc path="docs/project/plans/13-deterministic-event-ids.md">
At harvest: mark it delivered, point to `16-13-deterministic-event-ids.md`, and archive it. Record the discovery finding that answers its line 97: a profile-deletion path exists (`delete_profile`) and it now removes `like_generations`. Also record that `clear_likes` (reset) intentionally keeps generations.
</doc>
<doc path="docs/project/roadmap.md">
Optional follow-ups, out of scope:
- close the `max_likes` trim gap and the reset gap, where the Engine keeps +1 for likes removed without an `UndoLike`;
- decide whether the likes-import path should publish;
- cap or otherwise bound the popular-ordering likes tiebreaker.
</doc>

### highest_risk

client/backend/server.py `_handle_user_action()`: this is where the security fix lives. Four mistakes would each silently reopen the ranking-manipulation finding or break id stability for good: publishing when `changed` is False, hashing a different actor string than `actor_id` (`None` instead of `"anonymous"`), serialising `generation` as anything other than an `int`, or letting the `json.dumps` defaults drift. No existing test exposes event ids, so only the new tests can catch these.
engine/server/data/random_videos.py `fetch_popular_videos()`: every placeholder takes a number, so getting the new params order wrong raises no error. It quietly turns the cap into a LIMIT or an error threshold. Production always takes the `error_threshold` branch (`builder.py:109-113`), but the existing tests only take the branch without it, so the new test must cover both.
client/backend/server.py `_store_reaction()` plus `client/backend/lib/users_store.py` `record_like()`: a Like and its un-like must share a generation, and the next like must get a new one. That depends on detecting a new like from the rowcount of `INSERT ... ON CONFLICT DO NOTHING`, on upserting the generation before `record_like`'s internal commit, and on returning values captured inside `with conn:` blocks that today end in bare `return False`. Bulk imports that tie on `updated_at` can trim a row whose generation was just advanced.

## 2026-09-27 - Step 4 - Reassess the implementation plan (pass 1)

Pass 1. New impacts: YES.

I opened every file the core entries cite: `users_store.py`, `server.py` (imports, `_handle_user_action`, `_store_reaction`, `_handle_likes_import`, the reset handler, `connect_db`, `run_id`), `profiles.py`, `random_videos.py`, `interaction_events.py`, `test_profiles.py`, the conftest schema calls, and the security bundle. Every line reference and factual claim I checked holds. The inventory missed one caller of `ensure_user_schema`: `tests/active/test_server.py:266`, the `_client_backend` helper for the trusted-proxy tests. That path never sends a like, so nothing changes, and it supports the inventory's claim that every path runs the schema first. The mechanics of the plan are sound: the atomic rowcount check, a Like and its un-like reading the same generation, a dislike's UndoLike getting the same id as the profile's own un-like, and the order of the SQL parameters. What the inventory under-weights is this. The plan decides whether to publish from the local `likes` table, and two existing endpoints change that table without publishing anything. Each can be repeated without limit by one profile. The inventory mentions both mechanisms, but only as one-off drift or "same as today". Neither the plan nor the inventory treats them as repeatable ways to push a count up or down, which is what this build is meant to stop.
<question id="1">
Yes, for every case the plan lists. Double like, like → undo → like, bridge retry, anonymous duplicate, dislike-as-UndoLike, the ranking cap and `delete_profile` all follow from the code as it stands. The steps are: `ON CONFLICT DO NOTHING` plus rowcount gives an atomic "new"; `like_generations` survives `remove_like` and `clear_likes`; the Engine collapses a repeated id through `ON CONFLICT(event_id) DO NOTHING` (`interaction_events.py:85,100-109`); and the ORDER BY placeholders run in the order error, cap, inner LIMIT, outer LIMIT (`random_videos.py:245,247,252,262`). It does not work if the aim is "one profile adds at most +1 to a video, and takes away at most what it added". Two loops break that. Like → `POST /api/user-profile/reset` → like publishes a new Like with a fresh generation on every pass, so +1 each time, limited only by the general rate limiter. `POST /api/profile/likes/import` → `undo_like` (or `dislike`) publishes a new UndoLike each pass, so −1 each time against a video other people liked, down to the Engine's `MAX(0, …)` floor. Today's code allows both too, so neither is a regression. But the plan's own rule, "an un-like of an unliked video publishes nothing", can be bypassed by importing first.
</question>
<question id="2">
Event ids become deterministic and derived from content, so every replay by the same actor of the same state collapses in the Engine. Anonymous traffic can contribute at most +1 and −1 per video, ever. A generation row per (profile, video) builds up forever and is removed only by `delete_profile`. Profile keyed actions that change nothing stop publishing and answer 200. The popular pool caps the signal at 25 when ordering, while the stored score and the displayed likes (`random_videos.py:45`, the tiebreaker at 248) stay uncapped. The cap limits how far the two loops above can move a video in the popular ordering. It does not limit the count shown to users or the likes tiebreaker.
</question>
<question id="3">
Nothing beyond what the inventory already carries. That covers: `like_generations` in the schema, a `like_generations` count in `_rows_for` and the test at `test_profiles.py:205-216` updated to match, `hashlib` added while `uuid4` stays (`server.py:1155`), a test of the ranking cap on both parameter branches, and new Client tests that use fresh profiles and never assert that the first anonymous event counts. The imports at `server.py:37-39` and 5-7 match what the inventory describes. If the operator takes the recommendation below, the reset and import paths need the changes it lists.
</question>
<question id="4">
With a profile key, a repeat like, an un-like of an unliked video, a dislike of an unliked video and every `undo_dislike` now answer 200 `{ok, updatedAt}` and publish nothing. On the unpublished Client that used to be a 502 for likes and un-likes. Event ids change from `client-<uuid4>` to `client-<sha256>`. A video with `signal_score` above 25 no longer gains position beyond 25 in the popular pool. `delete_profile` also removes generations. Anonymous likes collapse to one per video. Import, reset, the bridge response shape and the error paths behave as before.
</question>


New impacts:
client/backend/server.py `_handle_user_profile_reset()` (lines 976-993) with `client/backend/lib/users_store.py` `clear_likes()`/`record_like()`: the reset clears `likes` and publishes nothing, but `like_generations` survives. So one profile can repeat like → reset → like, and every like is "new", takes generation+1, gets a fresh `client-` id and adds +1 to `signal_score` and `likes_count`, limited only by the general `RateLimiter`. The inventory records reset-then-re-like as "a second way for the Engine count to drift". It does not record it as a loop that lets one profile push a count up without limit. The 25.0 cap limits the ordering effect but not the shown likes or the tiebreaker (`engine/server/data/random_videos.py:45,248`).
client/backend/server.py `_handle_likes_import()` (lines 872-900) with `_store_reaction()` undo_like/dislike branches: an import inserts a `likes` row and advances the generation without publishing. A following `undo_like` (or `dislike`) then finds the row, publishes an UndoLike with a new id, and takes −1 off the video. Repeating import → undo_like takes one more −1 each pass from any video other people liked, down to the `MAX(0, …)` floor in `engine/server/data/interaction_events.py:124-127`. The inventory records one imported like leading to one UndoLike as "identical to today's". It does not record that this is repeatable, or that it gets around the plan's "an un-like of an unliked video publishes nothing".

Inventory entries that did not hold up:
none

Conflicts: none

Recommendations: 1. **Decide whether the two loops are in scope.** I could not see the text of the requirements. If the finding is only "replayed or repeated POSTs inflate counts", the plan closes it, and the operator should add both loops to "Tradeoffs the operator accepts" alongside the trim gap. That costs nothing beyond wording. If the finding is "one visitor can inflate or deflate a video's count", the plan as settled does not close it. In that case this is a conflict with the requirements, and the plan step should be reopened.
2. **If they are in scope, publish on an "open" flag rather than on the `likes` table.** Add an `open INTEGER NOT NULL DEFAULT 0` column to `like_generations`. The rule becomes: a like publishes only when `open = 0`, which sets `open = 1` and generation+1; an un-like or a dislike publishes only when `open = 1`, at the current generation, which sets `open = 0`. Import and reset never touch `open`. That closes both loops and the `max_likes` trim gap: a re-like after a trim or reset publishes nothing, and an un-like of an imported like publishes nothing. Each profile's effect on a video becomes a strict 0/+1 toggle. Cost: one more column; `record_like` takes a keyword such as `publish=False`, and with that default the import caller, which plan 14 also edits, stays unchanged; the planned reader becomes a small read-and-close writer; `changed` for un-likes comes from the flag and not from `remove_like`, so an un-like after a reset still withdraws the Like the Engine is holding. That is about 15 more lines in `users_store.py`, three more test cases, and a revision of the settled plan's sections 1-2 and its "imported likes" risk.
3. **For the Client acceptance tests, use the existing isolated harness.** That is `tests/active/test_server.py:262-271`, `_client_backend(tmp_path, engine_base, …)`, with a stub Engine in the style of `EngineStub` (lines 304-314), which records the posted `event_id`s. It answers the inventory's option (b) without touching the shared `whitelist.db`. Cost: the stub must answer `/internal/videos/resolve` with the shape `resolve_video_seed` expects, which neither I nor the inventory has checked.

## 2026-09-27 - Step 3 - Identify every file, function and doc affected

Recorded ungated, at the operator direction.

### impacts

<impact path="client/backend/lib/users_store.py" element="ensure_user_schema() (lines 10-63): new like_generations table">
**What changes.** The existing `executescript` gets one more `CREATE TABLE IF NOT EXISTS like_generations (user_id TEXT NOT NULL, video_id TEXT NOT NULL, instance_domain TEXT NOT NULL, generation INTEGER NOT NULL, PRIMARY KEY (user_id, video_id, instance_domain))`. It goes after `dislike_profiles` (lines 53-58) and before the `local-user` cleanup comment and DELETEs (lines 59-61), as the plan says. The docstring at line 11 ("Create the users, likes, profile, block and dislike tables if missing.") should also name the like generations table. No `local-user` DELETE is needed for the new table, because no such rows can exist in a table that is new.

**What depends on it.**
- `client/backend/server.py:1179` (`main`) runs it once at startup on `users.db`, so the live DB gets the table on the first restart. No migration step is needed.
- `tests/active/conftest.py:73` (`client_backend`) and `:160` (`_engine_client`) call it.
- `tests/active/test_server.py:266` (`_client_backend`) calls it.
- `delete_me/test_12_*.py` and `delete_me/test_probe_phase3_http.py` call it. These are scratch copies and are not collected.
- Every later `record_like` and `delete_profile` now needs the table.

**Regression risk: low.** `CREATE TABLE IF NOT EXISTS` is idempotent. A DB on which this function never ran would now fail in `record_like` and `delete_profile` with "no such table: like_generations". I found no such path: every connection above runs the schema first, and the `_seed_like` helpers write to fixture DBs that already have it. Do not confuse this with `engine/server/data/users.py:11`, the Engine's separate `ensure_user_schema`, which is untouched.
</impact>
<impact path="client/backend/lib/users_store.py" element="record_like() (lines 79-117): new-like detection, generation upsert, returns (new, generation)">
**What changes.**
- The one `INSERT ... ON CONFLICT ... DO UPDATE` (lines 94-102) becomes `INSERT ... ON CONFLICT(user_id, video_id, instance_domain) DO NOTHING`. The code reads `cursor.rowcount`: 1 means a new like, 0 means the row already existed.
- On 0, a plain `UPDATE likes SET video_uuid = ?, updated_at = ? WHERE user_id = ? AND video_id = ? AND instance_domain = ?` keeps today's recency refresh.
- On 1, it runs `INSERT INTO like_generations ... VALUES (?, ?, ?, 1) ON CONFLICT(...) DO UPDATE SET generation = like_generations.generation + 1`.
- It then reads the generation back.
- The return annotation changes from `-> None` to `-> tuple[bool, int]`, and the docstring (line 86) gains `:returns:`.
- The `max_likes` trim (103-116) and `conn.commit()` (117) are unchanged.
- `connect_db` (`server.py:144`) uses the default isolation level, so the conflicting INSERT reports rowcount 0. The UPSERT syntax is already in use in this file.

**What depends on it.** Five callers:
- `server.py:846`, plain like in `_store_reaction`. It now consumes the result.
- `server.py:869`, a like replacing a dislike. It now consumes the result.
- `server.py:898`, `_handle_likes_import`. It ignores the result. Plan 14 also edits this handler.
- `tests/active/test_profiles.py:44` (`_seed_like`), which ignores it.
- `tests/active/test_frontend_profile.py:109` (`_seed_like`), which ignores it.

**Transaction behaviour.**
- `get_or_create_user` (line 76) commits by itself when it inserts a user.
- The final commit inside `record_like` commits the caller's enclosing `with conn:` early. That ordering already exists and is documented in `docs/project/plans/archive/03-like-dislike.md:430`: `delete_dislike` runs first, so this commit covers both.
- The generation upsert and read-back happen before that commit, so they are atomic with the likes INSERT.

**Regression risk: medium.**
1. The plan says "the trim never drops the row just inserted". That holds for a single like. It does not strictly hold in a bulk import: up to `MAX_CLIENT_LIKES = 200` (`server.py:52`) records can go in against `MAX_LIKES = 100` (`server.py:51`), in one `with conn:`, and many share one `now_ms()`. A tie at the boundary can therefore trim a row whose generation was just advanced. That is harmless, since the next new like takes generation+1, but the plan's claim holds only for single likes.
2. `clear_likes` (the reset) leaves `like_generations` in place, so a re-like after a reset is new and publishes a fresh `Like`. See the reset entry: this is a repeatable +1 loop.
3. The read-back must work whether or not the connection has a `row_factory`: the test helpers set `sqlite3.Row`, raw connections do not. Use `row[0]`.
4. "New" must come from the INSERT's own rowcount, not from a SELECT beforehand, or two concurrent likes could both publish.
</impact>
<impact path="client/backend/lib/users_store.py" element="new generation reader function (next to remove_like, line 159)">
**What changes.** A new function returns the stored `generation` for `(user_id, video_id, instance_domain)`, or 0 when there is no row. To match the file's style:
- positional `conn, user_id, video_id, instance_domain`, so it can be called as `reader(conn, profile_id, *key)` the way `remove_like` is;
- a docstring with `:returns:`;
- no commit ("inside the caller's transaction", like `remove_like`).

**What depends on it.** `_store_reaction`'s undo_like and dislike branches, through a new name on the `lib.users_store` import (`server.py:37-39`). New tests may call it directly.

**Regression risk: low.** It should be read before `remove_like`. The value is the same either way, because `remove_like` never touches `like_generations`, but reading first keeps the intent clear. Returning 0 for a missing row gives the same generation anonymous actors use. That is safe only because the hashed actor differs: the profile id versus `"anonymous"`.
</impact>
<impact path="client/backend/lib/users_store.py" element="remove_like() (159-168), clear_likes() (153-156), video_reaction(), fetch_recent_likes(), load_liked_keys(), get_or_create_user(): unchanged">
**What changes.** Nothing. The plan keeps `remove_like`'s signature. `remove_like` still does not commit, and its callers hold `with conn:`.

**What depends on it.**
- `remove_like` is called at `server.py:848` (undo_like) and `:861` (dislike).
- `clear_likes` is called at `server.py:988` (reset). It deletes only `likes` and so deliberately leaves `like_generations`. That is required for "the generation survives", but it opens the reset loop described below.

**Regression risk: none in code.** Listed so the reset interaction is on record.
</impact>
<impact path="client/backend/server.py" element="stdlib import block (lines 5-22): add hashlib; keep uuid4">
**What changes.** `import hashlib` goes in alphabetical order between `argparse` (line 5) and `ipaddress` (line 6). Plan 12 has since added `ipaddress` at line 6, so the block reads argparse, ipaddress, json, ...

`from uuid import uuid4` (line 21) must stay: `run_id = str(uuid4())` at line 1155 still uses it. The requirement is "drop uuid4 if unused", and it is still used.

**What depends on it.** The event-id derivation in `_handle_user_action`.

**Regression risk: nil.** This is a merge point with plan 14 if plan 14 touches the import block; resolve by union.
</impact>
<impact path="client/backend/server.py" element="lib.users_store import (lines 37-39): add the generation reader">
**What changes.** The reader's name is added to the parenthesised import, which is alphabetised today: `clear_likes, ensure_user_schema, fetch_recent_likes, get_or_create_user, load_liked_keys, record_like, remove_like, video_reaction`.

**What depends on it.** `tests/active/conftest.py:39` (`import server as client_server`) and `test_server.py:47`. A misspelt name raises ImportError, which breaks all of `tests/active`.

**Regression risk: low.** A mistake fails loudly at import. This is a merge point with plan 14.
</impact>
<impact path="client/backend/server.py" element="ClientBackendHandler._store_reaction() (lines 831-870): returns (changed, generation)">
**What changes.** The return type changes from `bool` to a pair, and `:returns:` (line 837, "Whether a dislike removed a like.") is rewritten. Branch by branch:
- **Plain like** (line 846): the value of `record_like` must be captured inside the `with conn:` (lines 844-848) and returned. Today the function returns `False` at line 849, after the `with` block.
- **undo_like** (line 848): read the generation, then `removed = remove_like(...)`, both inside the same `with`. Return `(removed, generation)`.
- **dislike** (lines 855-863): the `DislikeLimitReached` check (856-857) and `compute_dislike_centroids` (859) stay before any write. Inside the `with` at line 860, read the generation, then `remove_like` and `write_dislike`. Return `(like_removed, generation)`.
- **The shared tail** (lines 864-870) serves both `undo_dislike` and a like replacing a dislike. It must return `record_like`'s pair when `action == "like"` and `(False, 0)` for `undo_dislike`. Today it returns `False` for both, so this branch is the easy one to get wrong.

**Exclusivity.** The plan says a like replacing a dislike is always new. That holds only because every path removes the other reaction; nothing in `lib/dislikes.py` enforces it at the DB level. If a `likes` row did co-exist, this branch would return `new=False` and publish nothing, which is still correct. `dislikes.py`'s `write_dislike` and `delete_dislike` do not commit, so the transaction is unchanged.

**What depends on it.** Only `_handle_user_action` (line 787). The rat-tail comment at lines 853-854 stays true.

**Regression risk: medium.** This is where "a Like and its un-like share a generation" either holds or fails. On the one shared `check_same_thread=False` connection of a `ThreadingHTTPServer`, two concurrent undo_likes can both read g, but only one `remove_like` sees rowcount 1, so only one publishes. A concurrent like and undo is the same class of race as the existing rat-tail.
</impact>
<impact path="client/backend/server.py" element="ClientBackendHandler._handle_user_action() (lines 731-829): publish gating and derived event_id">
**What changes.**
- Line 784, `publish = action in ("like", "undo_like")`, stays as the anonymous default, with generation 0.
- In the profile branch (785-795), `like_removed = self._store_reaction(...)` becomes `changed, generation = ...`, and line 795 `publish = publish or like_removed` becomes `publish = changed`. The comment at line 794 needs rewording.
- Line 802, `"event_id": f"client-{uuid4()}"`, becomes `"client-" + hashlib.sha256(json.dumps([actor, canonical_uuid, canonical_host, event_type, generation]).encode("utf-8")).hexdigest()`.
- `actor` is the same expression as line 804, `profile_id or "anonymous"`, and should be computed once and used in both places.
- `event_type` (line 800) must be computed before the id.
- The docstring "Handle handle user action." (line 732) could state the publish rule.
- The comment at lines 753-754 stays true.

**Behaviour changes callers can see.**
- With a key, a repeat `like`, an `undo_like` of an unliked video, a dislike of an unliked video, and every `undo_dislike` answer 200 `{ok, updatedAt}` and publish nothing.
- On `unpublished_client` (activitypub mode), a repeat keyed like or undo_like used to answer 502 and now answers 200.
- Keyless likes and un-likes still always publish, so they still answer 502 on an unpublished Client. `test_frontend_reactions.py:249-258` relies on that.

**Hashing details.**
- The `json.dumps` defaults (`ensure_ascii=True`, `", "` separators) are part of the id and must never change.
- `generation` must be an `int`, never a `bool` or `str`.
- `canonical_uuid` can be `""` (line 774). The Engine then rejects the event with "Missing object.video_uuid" (`interaction_events.py:208-209`), which is unchanged behaviour.
- The id is 71 characters and is accepted by `normalize_event_payload` (lines 194-198: a non-empty string after `_clean_text`, no length cap) and by `event_id TEXT PRIMARY KEY` (line 24).
- `raw_payload: body` (line 812) is still sent raw. That is out of scope.

**What depends on it.**
- `sendUserAction` in `client/frontend/src/data/user-actions.ts:33` checks only `response.ok`.
- The Engine answers a duplicate with 200 `ok: true` (`internal_events.py:84-93`), and `_publish_to_engine_bridge` maps that to `ok=True`. So a replayed anonymous like answers 200 `bridge_ok: true`.
- The smokes: see their entries.

**Regression risk: medium-high.** Any of these silently reopens the finding or breaks the contract:
- publishing when `changed` is False;
- hashing `None` as the actor instead of `"anonymous"`;
- using a different generation for an undo than for its Like;
- letting the serialisation drift.

No existing test exposes event ids.
</impact>
<impact path="client/backend/server.py" element="_handle_user_profile_reset() (lines 976-993) with clear_likes(): repeatable +1 loop (Step 4 finding, not in the plan's Risks)">
**What changes.** Nothing in the plan's code. But its interaction with the new gating matters. Reset deletes every `likes` row, keeps `like_generations`, and publishes nothing. One profile can therefore repeat like → `POST /api/user-profile/reset` → like. Each like is "new", takes generation+1, gets a fresh id, and adds +1 to `likes_count` and `signal_score`. The only limit is the general per-route `RateLimiter` (lines 352-357).

**What depends on it.** `test_profiles.py`'s `PROFILE_ROUTES` (line 31) uses the route, and the frontend reset flow.

**Regression risk: not a regression.** Today every like adds +1. But the plan's "Risks" does not record this as an unbounded one-profile loop. The 25.0 cap limits the effect on ordering, but not the shown likes count or the likes tiebreaker (`random_videos.py:45,248`).

**Uncertain: operator decision.** Accept it in "Tradeoffs", or change the gating (for example the "open" flag on `like_generations` proposed in the prior Step 4 record). I list it so it is not missed.
</impact>
<impact path="client/backend/server.py" element="_handle_likes_import() (lines 872-900): record_like caller, and the repeatable −1 loop">
**What changes.** Nothing in code. `record_like` at line 898 now returns a pair, which is ignored, and `imported += 1` is unchanged. The whole loop runs inside one `with conn:` while `record_like` commits on each iteration, as today.

**What depends on it.**
- Plan 14 edits this handler.
- `tests/active/test_profiles.py:245-253` and `tests/active/test_frontend_reactions.py:350-374` exercise it, on `unpublished_client`.

**Risk: low for code, but a behaviour to record.**
- Each imported new like advances the generation without publishing. The plan accepts this.
- It is also repeatable. Import video X → `undo_like` X finds the row, publishes an `UndoLike` with a fresh generation, and takes −1 off X → import again → undo again. Each pass removes another 1 from any video other people liked, down to the Engine's `MAX(0, …)` floor (`interaction_events.py:124-127`).
- This gets around the plan's own rule that "an un-like of an unliked video publishes nothing".
- Today's code allows the same, so it is not a regression, but the plan records only the single-shot case.
- See also the tie-trim note in the `record_like` entry.
</impact>
<impact path="client/backend/server.py" element="_publish_to_engine_bridge() / _publish_event() (lines 1032-1064): unchanged">
**What changes.** Nothing.

**What depends on it.** It limits how tests can observe duplicates. It returns `{"ok", "response"}`, and the handler exposes only `ok`, `bridge_ok` and `bridge_error`. So "the second is a duplicate" cannot be read from the Client response. Tests must either read the Engine's `interaction_raw_events`/`interaction_signals`, post to `/internal/events/ingest` directly, or capture payloads with a stub Engine.

**Regression risk: none.**
</impact>
<impact path="client/backend/lib/profiles.py" element="delete_profile() (lines 69-80)">
**What changes.** One more `conn.execute("DELETE FROM like_generations WHERE user_id = ?", (profile_id,))` inside the `with conn:`. It belongs next to the `likes` delete at line 78, since both key on `user_id`. The docstring ("every row keyed to it") stays true.

**What depends on it.**
- `server.py:340-345` (`POST /api/profile/delete`).
- `tests/active/test_profiles.py:197-217`.
- The profile-delete steps in `tests/run-installers-smoke.sh:449,683` and `tests/run-arch-split-smoke.sh:617`.

**Regression risk: low.** It only fails on a DB where the table was never created, and no such path exists. Because the delete runs in one transaction, a failure would roll back the whole profile delete.
</impact>
<impact path="engine/server/data/random_videos.py" element="new module-level POPULAR_SIGNAL_CAP = 25.0">
**What changes.** A named constant goes after the imports (after line 9), with a `#` comment above it. The module has no constants today; the house style can be seen in `interaction_events.py:13-14`.

**What depends on it.** `fetch_popular_videos` and the new ranking test, which may import it.

**Regression risk: nil.**
</impact>
<impact path="engine/server/data/random_videos.py" element="fetch_popular_videos() (lines 195-303): capped ORDER BY term and params order">
**What changes.**
- Line 247, `(v.popularity + COALESCE(sig.signal_score, 0)) DESC`, becomes `(v.popularity + MIN(COALESCE(sig.signal_score, 0), ?)) DESC`.
- Line 200 becomes `[POPULAR_SIGNAL_CAP, limit, limit]`, and line 203 becomes `[error_threshold, POPULAR_SIGNAL_CAP, limit, limit]`. That matches the placeholder order: the WHERE `?` from `{error_clause}` (245, inner subquery), then the cap (247), then the inner `LIMIT ?` (252), then the outer `LIMIT ?` (262).
- Line 234 (`interaction_signal_score`, raw) and the tiebreaker at line 248 are unchanged.
- The docstring "by likes/views" (198) could mention the capped signal.

**What depends on it.**
- `engine/server/api/server.py:90,398` wires it in.
- `engine/server/api/recommendations/builder.py:109-113` wraps it with `error_threshold=settings.video_error_threshold`. That value is `VIDEO_ERROR_THRESHOLD = 3` (`server_config.py:387`), so production always takes the 4-parameter branch.
- `candidates/popular_videos.py:52` consumes the pool.
- `tests/active/test_random_videos.py:85` calls it without a threshold, which is the 3-parameter branch.

**Regression risk: medium.**
- A wrong params order raises nothing, because every placeholder takes a number. It silently turns the cap into a LIMIT or a threshold.
- The tested branch is not the production branch, so the new test must cover both.
- Two-argument `MIN` is SQLite's scalar function, which returns NULL if any argument is NULL. `COALESCE` inside it prevents that.
- On the live dataset, videos with a signal above 25 drop in the popular pool. That is intended.
</impact>
<impact path="engine/server/data/random_videos.py" element="fetch_random_rows() (line 45 likes), fetch_recent_videos(), cache readers: unchanged">
**What changes.** Nothing. `(v.likes + COALESCE(sig.likes_count, 0)) AS likes` is the displayed likes figure, not the ranking signal.

**Regression risk: none.** Listed so the cap is not applied to the wrong query.
</impact>
<impact path="engine/server/data/interaction_events.py" element="ingest_interaction_event() / normalize_event_payload() / _event_deltas() / prune_interaction_raw_events(): unchanged, relied upon">
**What changes.** Nothing; the requirements forbid changes here.

**What depends on it.**
- The collapsing relies on `ON CONFLICT(event_id) DO NOTHING` (line 85) and on the duplicate result (lines 100-109).
- The deltas are Like +1.0, UndoLike −1.0 (lines 255, 262), floored by `MAX(0, …)` (124-127).
- The prune (150-189) strips payload, actor and source but keeps the row, and with it the `event_id`, so derived ids keep collapsing replays after retention.

**Regression risk: none from this build.**
</impact>
<impact path="engine/server/api/handlers/internal_events.py" element="handle_internal_events_ingest() duplicate accounting (lines 56-94): unchanged">
**What changes.** Nothing.

**What depends on it.** The "bridge retry is reported as duplicate" and "second anonymous like is a duplicate" criteria. They can be observed through `results[i].duplicate` and `duplicates`. The route is served only in `ENGINE_INGEST_MODE=bridge`, which the conftest `engine` fixture sets (line 105).

**Regression risk: none.**
</impact>
<impact path="engine/server/data/users.py" element="Engine-side ensure_user_schema() (line 11) / record_like() (line 47): NOT touched">
**What changes.** Nothing. It has the same function names as the Client module, so a `def record_like` grep finds both. The one to edit is `client/backend/lib/users_store.py:79`.

**Regression risk: none, provided the right file is edited.**
</impact>
<impact path="client/backend/lib/engine_api_client.py" element="resolve_video_seed() (lines 66-89): unchanged; shape needed by a stub Engine">
**What changes.** Nothing.

**What depends on it.** Any new isolated test that uses a stub Engine must answer `POST /internal/videos/resolve` with 200 `{"video": {"video_id", "instance_domain", "video_uuid", "video_url"}}`. A 404 becomes "not found"; any other status or a non-dict raises `EngineApiError`. The stub must also accept `POST /internal/events/ingest` and record the `event_id`. I verified this shape in the source; the prior record had it as unverified.

**Regression risk: none.**
</impact>
<impact path="client/frontend/src/data/user-actions.ts" element="sendUserAction() (lines 18-38): unchanged">
**What changes.** Nothing. It treats any 2xx as success, so the new 200 `{ok, updatedAt}` answer to a keyed no-change action is accepted.

**Side effect.** A keyed repeat like on a Client that cannot publish no longer throws "Failed to send action". That is correct.

**Regression risk: none.**
</impact>
<impact path="tests/active/test_random_videos.py" element="existing popular tests (108-122), helpers _two_video_db/_set_views/_event (34-77); home for the ranking-cap test">
**What changes.** The existing tests stay green: they use signal 1.0, which is under the cap, and assert the raw `interaction_signal_score == 1.0` (line 119). The new criterion fits here:
- Use `_two_video_db`, then `UPDATE videos SET popularity` to 0 and 30.
- Set the signal to 1000 with a direct `INSERT INTO interaction_signals`, rather than 1000 ingests.
- Run with and without `error_threshold`. `_set_views` sets `error_count = 0`, so a threshold of 1 keeps both rows.

**Correction to the plan.** The plan says the file uses "an isolated in-memory Engine database". It actually uses a file DB under `tmp_path`, built by `ATTACH` of `whitelist.db` read-only (lines 36-52). It is still isolated from the live DB's writes, but it needs `whitelist.db` to exist.

**What depends on it.** `.un/skills/devsecops/config.json:87-88` maps it to `random_videos.py`.

**Regression risk: low.**
</impact>
<impact path="tests/active/test_profiles.py" element="_seed_like (41-46), _rows_for (59-67), test_deleting_a_profile_removes_its_rows_and_keeps_anothers (197-217)">
**What changes.**
- `_seed_like` now also writes a `like_generations` row and ignores the return value.
- This is the natural home for the "`delete_profile` removes the profile's `like_generations` rows" criterion: add a `like_generations` count to `_rows_for`.
- The four equality asserts (lines 205, 209, 215, 216) must then change together to include `"like_generations": 1` (or 0).
- The comment at line 201 ("all three tables") becomes "four".

**What depends on it.** `config.json:18-21` maps it to `server.py`, `profiles.py` and `users_store.py`.

**Regression risk: low.** A partial update of those dicts fails the test.
</impact>
<impact path="tests/active/test_profiles.py" element="test_a_keyed_upnext_request_is_seeded_... (264-282) and test_a_keyed_search_marks_... (291-313)">
**What changes.** Nothing.
- The first like by a fresh profile is new, so line 300 still expects 502 on `unpublished_client`.
- A dislike of an unliked video still answers 200.
- Line 277 does not assert status.

**Regression risk: none.** Line 300 guards against a like wrongly treated as not new, which would answer 200.
</impact>
<impact path="tests/active/test_frontend_profile.py" element="_seed_like (106-111)">
**What changes.** Nothing required. It calls `record_like` on a fixture DB that already has the table, and ignores the result.

**Regression risk: low.**
</impact>
<impact path="tests/active/test_frontend_reactions.py" element="keyless tests (202-258), keyed sequence (264-308), keyed-vs-keyless store test (311-340), card test (396-409)">
**What changes.** Nothing in the file. Behaviour against the shared live `whitelist.db` does change.

**Keyless tests.** They publish anonymous Like/UndoLike on the first rows of `_videos(dataset, n)`, which are the same every run.
- After this build each such video has exactly one anonymous Like id and one anonymous UndoLike id.
- The first run nets +1−1. Every later run gets duplicates, which still answer 200 `ok`, and the assertions check only `"ok"` and browser-store state.
- The finally-block undos at lines 213-214 and 239-240 become duplicates, so they have no effect after the first run.

**Keyed sequence (264-303).** Each step is a real change, or answers 200 without publishing:
- like: g1, published;
- dislike: removes the like, publishes UndoLike at g1;
- undo_dislike: 200, nothing published;
- out-of-band dislike on the now unliked video: 200;
- like replacing that dislike: g2, published;
- undo_like: UndoLike at g2.

So `all("ok" in a ...)` (line 303) holds.

**Card test (406).** It still expects a 502 for a fresh profile's first like on `unpublished_client`.

**Regression risk: low for the assertions, medium for shared data.**
- A test asserting that "the first anonymous like counts +1" would fail on every run after the first.
- A run that dies between an anonymous Like and its UndoLike leaves +1 on that video for good, because every later anonymous Like is a duplicate. This is accepted under ADR-0001 §3.
</impact>
<impact path="tests/active/test_dislikes.py" element="test_a_video_s_reaction_follows_... (68-87), _profile_disliking (118-123)">
**What changes.** Nothing.
- The dislike of a liked video still publishes, and line 77 accepts `in (200, 502)`.
- `undo_dislike` answers 200 (line 82).
- A dislike of an unliked video answers 200 (line 84, and `_profile_disliking` at line 122).
- Lines 74, 79 and 86 do not assert status.

**Regression risk: none.**
</impact>
<impact path="tests/active/test_server.py" element="keyed likes loop (86-102) and _client_backend / EngineStub harness (262-326)">
**What changes.** Nothing.
- Each like in the loop is on a distinct row, the set removes duplicates, and status is not asserted.
- The dislikes answer 200 (line 102).
- The `_client_backend(tmp_path, engine_base, rate_limiter)` helper plus the `EngineStub` pattern (307-320) is the ready-made isolated harness for the new Client acceptance tests. Extend the stub with `do_POST` for resolve and ingest.

**Regression risk: none.**
</impact>
<impact path="tests/active (new test file(s) for this build)" element="new Client acceptance tests: publish-on-change, derived ids, dislike UndoLike id, anonymous duplicate, delete_profile">
**What changes.** New tests. There are two ways to observe events:
- (a) `engine_client`, reading the live `interaction_raw_events` by a fresh profile id through the `dataset` connection;
- (b) the stub Engine from `test_server.py`, which records posted `event_id`s. This avoids the shared DB and the Engine rate limit.

**Constraints.**
- Profile tests must mint fresh profiles.
- An anonymous test may assert only "same id" or "second is a duplicate", never "first counts".
- Tests that publish real Likes under (a) must withdraw them in a `finally`, as the existing tests do.

**What depends on it.**
- `validate_tests.py` collects `tests/active/test_*.py` (and `tests/tmp`).
- Engine-backed files run in their own invocation.
- New files are unmapped in `.un/skills/devsecops/config.json` until harvest.

**Regression risk: medium for suite stability** under (a); low under (b).
</impact>
<impact path="tests/run-arch-split-smoke.sh" element="client_user_action like + validate_user_action_response (330-346, 584-602), profile delete (617)">
**What changes.** Nothing. The like by the freshly minted profile is new, so it publishes and `ok`, `bridge_ok` and an empty `bridge_error` hold.

If minting fails, the like is anonymous. After the first run it is then a duplicate, which still returns `bridge_ok: true`.

**Regression risk: low.**
</impact>
<impact path="tests/run-installers-smoke.sh" element="like flow (649-686), verify_engine_event_recorded (~459-496), cleanup_engine_test_events (~498-585), delete_client_test_profile (~444-457)">
**What changes.** Nothing.
- The fresh profile's first like is new and publishes.
- The raw row exists under `actor_id = profile_id`.
- The cleanup deletes raw rows by actor and recomputes, which frees that derived id. That is harmless, because the profile is deleted and cannot replay.
- The profile delete now also removes `like_generations`.

**Regression risk: low.**
</impact>
<impact path="engine/server/db/jobs/tests/test-interaction-events.py" element="ingest contract script">
**What changes.** Nothing. The acceptance criteria require it to keep passing. It is not collected by `validate_tests.py`, so it must be run explicitly. It does not reference Client event ids or `fetch_popular_videos` (grep).

**Regression risk: none.**
</impact>
<impact path="engine/server/db/jobs/tests/test-security-bundle.py" element="security bundle checks">
**What changes.** Nothing. A grep found no reference to popular ordering, `signal_score`, Client ids or user-action. It must be run explicitly.

**Regression risk: none expected.**
</impact>
<impact path=".un/skills/devsecops/config.json" element="test_groups (test_profiles 18-21, groups at 37-40/45-46/56-85 naming server.py/users_store.py/profiles.py, test_random_videos 87-88)">
**What changes.** Nothing in this worktree. The existing mappings already re-run the affected groups when any of the four source files changes. A new test file needs an entry at harvest.

**Regression risk: low.**
</impact>
<impact path="tests/last_test_validation.json" element="tracked suite record">
**What changes.** The post-build run rewrites it. It conflicts on merge: take main's copy and re-run `validate_tests.py --compare`.

**Regression risk: none functionally.**
</impact>
<impact path="tests/last_test_output.txt" element="tracked captured output">
**What changes.** Rewritten by the post-build run. Resolve its merge conflict the same way as `last_test_validation.json`.

**Regression risk: none.**
</impact>
<impact path="delete_me/server.py.bak*" element="stale copies of server.py matched by grep">
**What changes.** Nothing. They are backups under `delete_me/` that match every symbol grep here (`record_like`, `_store_reaction`, `uuid4`). They must not be edited in place of `client/backend/server.py`.

**Regression risk: none.**
</impact>

### docs_checklist

<doc path="client/README.md">
**Line 19 (`POST /api/user-action`).** It reads "A like publishes its event and is kept server-side only when a profile key is sent", which implies every like publishes. Reword it to say:
- With a key, a `like` publishes a `Like` only when the profile did not already like the video.
- An `undo_like` publishes an `UndoLike` only when a like was removed.
- A request that changes nothing answers 200 and publishes nothing.
- Without a key every like and un-like publishes, under one fixed id per video and event type, so repeats are duplicates.
- Event ids are `client-` plus the SHA-256 of actor, video, event type and like generation.

**Line 13 (`POST /api/profile/delete`).** Optionally add "like generations" to the list of what is removed.
</doc>
<doc path="DEPLOYMENT.md">
**Lines 259-261.** Optionally add that the Client backend publishes a profile's `Like`/`UndoLike` only on a real state change, with derived event ids, so replays collapse at the Engine's ingest.

**Line 267.** Optionally add that the popular ordering adds at most 25.0 of a video's interaction signal (`POPULAR_SIGNAL_CAP` in `engine/server/data/random_videos.py`), and that `users.db` gains a `like_generations` table created at startup, with no migration step.
</doc>
<doc path="engine/server/api/recommendations/docs/OVERVIEW.md">
**Line 99** ("popular pool: top by likes/views"): state that the pool is ordered by `popularity` plus the interaction signal capped at `POPULAR_SIGNAL_CAP` (25.0), then by likes, views and recency.
</doc>
<doc path="engine/server/api/recommendations/docs/PIPELINE_DIAGRAM.md">
**Line 29** (`popular<br/>top likes/views`): optionally align it with the capped-signal ordering. This is cosmetic.
</doc>
<doc path="CONTEXT.md">
**Verify only.** **Interaction event** (line 6) already says ids are "derived, never random", and **Interaction signal** (line 7) already says the popular ordering adds at most a fixed cap. Both match the build.

Optionally define **Like generation**: the per-profile, per-video counter that tells one like from the next, survives un-likes and resets, and is removed with the profile.
</doc>
<doc path="docs/project/adr/0001-derived-interaction-event-ids.md">
The decision is unchanged. Optionally add to Consequences:
- the chosen like-instance scheme (the Client's `like_generations`, kept through un-like and reset, deleted with the profile);
- that likes predating the table un-like at generation 0;
- that imported likes advance the generation without publishing;
- the reset and import loops, if the operator accepts them rather than closing them.
</doc>
<doc path="docs/project/issues/01-deterministic-event-ids.md">
At harvest on main: tick the acceptance criteria, set `Status:` to `bug, complete`, and move the file to `docs/project/issues/archive/` per `docs/project/triage-labels.md`.
</doc>
<doc path="docs/project/plans/13-deterministic-event-ids.md">
At harvest: mark it delivered, point it to `16-13-deterministic-event-ids.md`, and archive it. Also record:
- The answer to its line 97: a profile-deletion path exists (`delete_profile`) and now removes `like_generations`.
- `clear_likes` (reset) intentionally keeps generations.
</doc>
<doc path="docs/project/roadmap.md">
Optional out-of-scope follow-ups:
- Close the reset (+1) and import→undo (−1) loops and the `max_likes` trim gap, for example with an "open" flag on `like_generations`.
- Decide whether the likes import should publish.
- Bound the popular likes tiebreaker.
</doc>

### highest_risk

client/backend/server.py `_handle_user_action()`: this is the security fix itself. Publishing when `changed` is False, hashing a different actor from `actor_id` (`None` instead of `"anonymous"`), a non-int `generation`, or drift in the `json.dumps` defaults would each silently reopen the finding or break id stability for good. No existing test exposes event ids.
engine/server/data/random_videos.py `fetch_popular_videos()`: every placeholder takes a number, so a wrong params order raises nothing and quietly turns the cap into a LIMIT or an error threshold. Production always takes the `error_threshold` branch (`VIDEO_ERROR_THRESHOLD = 3` via `builder.py:109-113`), while existing tests take only the other branch, so both need a test.
client/backend/server.py `_store_reaction()` with client/backend/lib/users_store.py `record_like()`: a Like and its un-like must share a generation. The value has to be captured inside `with conn:` blocks that today end in a bare `return False`, and the shared `undo_dislike`/like-replacing-dislike tail must return different things by action. Separately, the reset→re-like (+1) and import→undo_like (−1) loops stay open and repeatable per profile, which the plan's Risks section does not record. The operator needs to accept them or close them.

## 2026-09-27 - Step 4 - Reassess the implementation plan (pass 2)

Pass 2. New impacts: none.

I checked the inventory against the tree. Every claim I checked holds. I opened `users_store.py` in full. In `server.py` I read the imports (5-39), `connect_db` (142-146), `_handle_user_action` (731-829), `_store_reaction` (831-870), `_handle_likes_import` (872-900), the reset handler (976-993) and `run_id` (1155, used at 1198 and 1213). I also read `delete_profile` in `profiles.py` (69-80), `fetch_popular_videos` in `random_videos.py` (195-265), and the `test_profiles.py` helpers (41-67 and the "all three tables" comment at 201). A search outside `delete_me/` found nothing else that writes to `likes`. The only writers are `record_like`, `remove_like`, `clear_likes`, `delete_profile` and the `local-user` cleanup, and the inventory covers all of them. The Engine's `users.py` duplicate is correctly marked as untouched. The two loops the previous Step 4 raised are now inventory entries: reset → re-like gives +1 per pass, and import → undo_like gives −1 per pass. Both are still left as an operator decision. The inventory has converged.
<question id="1">
Yes. Each acceptance criterion follows from the code as it stands. `INSERT ... ON CONFLICT DO NOTHING` followed by a rowcount check gives an atomic "new". A Like and its un-like read the same generation, because only a new like advances it and neither `remove_like` nor `clear_likes` touches `like_generations`. A dislike that removes a like reads the same generation the profile's own un-like would have read, so it produces the same id. The placeholder order in `fetch_popular_videos` is: the optional error `?` (the `{error_clause}` in the inner subquery at 245), then the cap (247), the inner `LIMIT ?` (252) and the outer `LIMIT ?` (262). That matches `[error_threshold, CAP, limit, limit]` and `[CAP, limit, limit]`. `uuid4` has to stay imported, because `run_id` still uses it. One limit, already in the inventory: the plan does not stop a single profile from repeatedly adding +1 through reset, or −1 through import then undo_like. Today's code allows both as well.
</question>
<question id="2">
Event ids become content-derived, so a repeat from the same actor in the same state collapses at the Engine. Anonymous likes contribute at most +1 per video, and anonymous un-likes at most −1. `users.db` gains one `like_generations` row per (profile, video) pair ever liked, and those rows are removed only with the profile. A keyed request that changes nothing now gets 200 and publishes nothing, where on an unpublished Client it used to get a 502. In the popular ordering the signal counts for at most 25. The stored score, the displayed likes and the likes tiebreaker stay uncapped. The inventory already carries all of this.
</question>
<question id="3">
Nothing beyond what the inventory already lists:
- create the table in `ensure_user_schema`;
- add the `like_generations` delete to `delete_profile`;
- add a `like_generations` count to `_rows_for`, update the four equality asserts, and change the "three tables" comment to "four";
- add `hashlib` and keep `uuid4`;
- add the reader name to the `users_store` import;
- test the cap on both parameter branches;
- in new Client tests, use fresh profiles or a stub Engine, and never assert that the first anonymous event counts.
</question>
<question id="4">
- With a key, these requests no longer publish anything and answer 200: a repeat like, an un-like of a video that isn't liked, a dislike of a video that isn't liked, and every `undo_dislike`.
- Event ids change from `client-<uuid4>` to `client-<sha256>` over actor, video_uuid, host, event type and generation.
- Anonymous repeats become duplicates at the Engine.
- The popular pool stops rewarding any signal above 25.
- `delete_profile` also removes generations.
- Unchanged: import, reset, the error paths and the bridge response shape.
</question>

New impacts:
none

Inventory entries that did not hold up:
none

Conflicts: none

Recommendations: 1. Decide the one item left open: the reset → re-like loop (+1 per pass) and the import → undo_like loop (−1 per pass). Both are recorded in the inventory as "operator decision". (a) Accept them. Add both to "Tradeoffs the operator accepts" next to the `max_likes` trim gap, and list them as a follow-up in `docs/project/roadmap.md`. This costs only wording, and the settled plan stays as it is. (b) Close them with an `open` flag on `like_generations`, as the previous Step 4 described. A like publishes only when the flag is 0. An un-like or dislike publishes only when it is 1. Import and reset never change it. This costs about 15 lines in `users_store.py` and three more test cases. It also reopens the settled plan's sections 1-2 and its "imported likes" risk, so it goes back to the plan step. I recommend (a). The build's requirements are about replays and repeated POSTs, and they explicitly keep the likes-import path and rate limiting out of scope. Neither loop is a regression.
2. If (a) is taken, nothing else changes. The remaining work proceeds on the plan and inventory as written, and this step is closed.

## 2026-09-27 - Step 5 - Draft the initial implementation

Recorded ungated, at the operator direction.

### draft

## Draft implementation: plan 13, derived event ids, publish on change, popular-signal cap

**Operator decision taken at this step.** The inventory left two loops for the operator: reset → re-like (+1 each pass) and import → undo_like (−1 each pass). The operator chose to close both with a published flag. So this draft departs from the settled plan and inventory in the places listed under "Deviations from the settled plan and inventory" at the end. Everything else follows the plan as approved.

### What has to be tested

| # | Behaviour | Where |
|---|---|---|
| T1 | Two profile `like` posts publish one `Like`. `likes_count` +1 and `signal_score` +1.0 | new `tests/active/test_event_ids.py` (stub Engine) |
| T2 | Profile like → undo_like → like publishes Like(g1), UndoLike(g1), Like(g2). The two Like ids differ and `signal_score` ends at 1.0 | same |
| T3 | Re-sending a published payload is `duplicate: true` and changes no counts | same |
| T4 | Two anonymous likes produce the same id, and the second is a duplicate | same |
| T5 | undo_like on an unliked video answers 200 and publishes nothing | same |
| T6 | A dislike that replaces a like publishes one UndoLike with the id the undo_like would have used. A dislike on an unliked video publishes nothing | same |
| T7 | Reset loop closed: like → reset → like publishes one Like. A later undo_like publishes the UndoLike for that same Like, and `signal_score` ends at 0 | same |
| T8 | Import loop closed: import X → undo_like X publishes nothing | same |
| T9 | Popular ordering: signal 1000 with popularity 0 ranks below popularity 30 with no signal, on both parameter branches | `tests/active/test_random_videos.py` |
| T10 | `delete_profile` removes the profile's `like_generations` rows and keeps another profile's | `tests/active/test_profiles.py` (existing delete test, extended) |
| T11 | Existing suites stay green | `validate_tests.py` |

### Module map

| File | Change |
|---|---|
| `client/backend/lib/users_store.py` | table in `ensure_user_schema`; `record_like` gains `publish=False` and returns `(opened, generation)`; new `like_generation` (reader) and `close_like` (writer) |
| `client/backend/lib/profiles.py` | `delete_profile` deletes `like_generations` |
| `client/backend/server.py` | `import hashlib`; `close_like` added to the `users_store` import; `_store_reaction` returns `(publish, generation)`; `_handle_user_action` gates on it and derives the id |
| `engine/server/data/random_videos.py` | `POPULAR_SIGNAL_CAP`; capped ORDER BY term; params reordered |
| `tests/active/test_event_ids.py` | new: T1–T8 |
| `tests/active/test_random_videos.py` | new T9 test |
| `tests/active/test_profiles.py` | `_seed_like` passes `publish=True`; `_rows_for` counts `like_generations`; the four delete asserts are updated |

### The like-generation state machine

This is the core invariant. Each `(profile, video)` row in `like_generations` holds `generation` and `published`.

| Event | Precondition | Effect | Publishes |
|---|---|---|---|
| keyed like (`record_like(publish=True)`) inserts a new `likes` row | no row | insert `(g=1, published=1)` | `Like` at g=1 |
| same | `published=0` | `g+=1`, `published=1` | `Like` at the new g |
| same | `published=1` (after a reset or trim, the Engine still holds this profile's Like) | nothing | nothing |
| keyed like, `likes` row already exists | any | refresh `video_uuid` / `updated_at` only | nothing |
| import (`record_like`, default `publish=False`) | any | `likes` row only; `like_generations` untouched | nothing |
| undo_like, or a dislike (`close_like`) | `published=1` | `published=0`, g unchanged | `UndoLike` at g |
| same | no row, or `published=0` | nothing | nothing |
| reset (`clear_likes`) | any | untouched | nothing |
| `delete_profile` | any | rows deleted | nothing |

**Invariant.** g changes only on the 0→1 transition, so while `published=1` it is constant. Every Like(g) is matched by at most one UndoLike(g), and the next Like gets g+1. Per profile and video, the Engine sees each id at most once, so the profile's net contribution is always 0 or +1. Both loops are closed by construction: reset leaves `published=1`, so the re-like publishes nothing, and import never opens a like, so its undo publishes nothing.

**Atomicity.** Opening and closing are single statements whose rowcount decides whether to publish. That is an `UPSERT ... DO UPDATE ... WHERE published = 0` for opening and an `UPDATE ... WHERE published = 1` for closing. Two concurrent requests can never both publish the same transition, and no request relies on a SELECT-then-write.

### `client/backend/lib/users_store.py`

`ensure_user_schema`: the docstring becomes "Create the users, likes, like generation, profile, block and dislike tables if missing." Insert this after `dislike_profiles` and before the `local-user` comment:

```sql
        CREATE TABLE IF NOT EXISTS like_generations (
          user_id TEXT NOT NULL,
          video_id TEXT NOT NULL,
          instance_domain TEXT NOT NULL,
          generation INTEGER NOT NULL,
          published INTEGER NOT NULL DEFAULT 0,
          PRIMARY KEY (user_id, video_id, instance_domain)
        );
```

`record_like`:

```python
def record_like(
    conn: sqlite3.Connection,
    user_id: str,
    action: str,
    video: dict[str, Any],
    max_likes: int,
    publish: bool = False,
) -> tuple[bool, int]:
    """Record a like with recency tracking.

    :param publish: The caller publishes a `Like` when this opens one. The likes import passes nothing, so an imported like never opens one.
    :returns: Whether this like opened the video's published like, and the video's like generation (0 when none was ever opened).
    """
    if action != "like":
        raise ValueError("Unsupported action")
    get_or_create_user(conn, user_id)
    video_id = str(video.get("video_id") or "")
    instance_domain = str(video.get("instance_domain") or "")
    video_uuid = video.get("video_uuid")
    now = now_ms()
    inserted = conn.execute(
        """
        INSERT INTO likes (user_id, video_id, instance_domain, video_uuid, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(user_id, video_id, instance_domain) DO NOTHING
        """,
        (user_id, video_id, instance_domain, video_uuid, now),
    ).rowcount > 0
    if not inserted:
        conn.execute(
            "UPDATE likes SET video_uuid = ?, updated_at = ? WHERE user_id = ? AND video_id = ? AND instance_domain = ?",
            (video_uuid, now, user_id, video_id, instance_domain),
        )
    opened = False
    if inserted and publish:
        # A like still published (the Engine holds it through a reset or trim) is not opened again.
        opened = conn.execute(
            """
            INSERT INTO like_generations (user_id, video_id, instance_domain, generation, published)
            VALUES (?, ?, ?, 1, 1)
            ON CONFLICT(user_id, video_id, instance_domain)
            DO UPDATE SET generation = like_generations.generation + 1, published = 1
            WHERE like_generations.published = 0
            """,
            (user_id, video_id, instance_domain),
        ).rowcount > 0
    generation = like_generation(conn, user_id, video_id, instance_domain)
    if max_likes > 0:
        ...  # trim unchanged
    conn.commit()
    return opened, generation
```

- When the DO UPDATE's WHERE is false, SQLite treats the conflict as DO NOTHING, so `changes()` is 0 and `rowcount` is 0.
- The `inserted` flag is taken from the INSERT's own cursor before any other statement runs.

New functions, placed after `remove_like`:

```python
def like_generation(conn: sqlite3.Connection, user_id: str, video_id: str, instance_domain: str) -> int:
    """Return the profile's like generation for one video.

    :returns: The generation, or 0 when no like of it was ever published.
    """
    row = conn.execute(
        "SELECT generation FROM like_generations WHERE user_id = ? AND video_id = ? AND instance_domain = ?",
        (user_id, video_id, instance_domain),
    ).fetchone()
    return int(row[0]) if row else 0


def close_like(conn: sqlite3.Connection, user_id: str, video_id: str, instance_domain: str) -> tuple[bool, int]:
    """Close the profile's published like of one video, inside the caller's transaction.

    :returns: Whether a published like was closed, so an `UndoLike` is due, and the generation that like was published under.
    """
    closed = conn.execute(
        "UPDATE like_generations SET published = 0 WHERE user_id = ? AND video_id = ? AND instance_domain = ? AND published = 1",
        (user_id, video_id, instance_domain),
    ).rowcount > 0
    return closed, like_generation(conn, user_id, video_id, instance_domain)
```

- `row[0]` works with or without `row_factory`.
- `remove_like` and `clear_likes` are unchanged.

### `client/backend/lib/profiles.py`

In `delete_profile`, add `conn.execute("DELETE FROM like_generations WHERE user_id = ?", (profile_id,))` after the `likes` delete, inside the same `with conn:`.

### `client/backend/server.py`

Imports:
- `import hashlib` goes between `argparse` and `ipaddress`.
- `from uuid import uuid4` stays, because `run_id` still uses it.
- `users_store` import: `(clear_likes, close_like, ensure_user_schema, fetch_recent_likes, get_or_create_user, load_liked_keys, record_like, remove_like, video_reaction)`. `like_generation` is not imported, since the server does not need it.

`_store_reaction` (annotation `-> tuple[bool, int]`):

```python
        """...
        :returns: Whether to publish, a `Like` for a like and an `UndoLike` otherwise, and the like generation the event is published under.
        ...
        """
        conn = self.server.user_db
        key = (video["video_id"], video["instance_domain"])
        if action == "undo_like" or (action == "like" and not is_disliked(conn, profile_id, *key)):
            with conn:
                if action == "like":
                    result = record_like(conn, profile_id, "like", video, MAX_LIKES, publish=True)
                else:
                    remove_like(conn, profile_id, *key)
                    result = close_like(conn, profile_id, *key)
            return result
        entries = ...  # unchanged
        if action == "dislike":
            ...  # limit check and centroids unchanged, before any write
            with conn:
                remove_like(conn, profile_id, *key)
                withdrawn = close_like(conn, profile_id, *key)
                write_dislike(conn, profile_id, video, centroids)
            return withdrawn
        # undo_dislike, or a like replacing a dislike.
        centroids = ...  # unchanged
        result = (False, 0)
        with conn:
            delete_dislike(conn, profile_id, *key, centroids)
            if action == "like":
                result = record_like(conn, profile_id, "like", video, MAX_LIKES, publish=True)
        return result
```

- The un-like decision comes from the flag, not from `remove_like`'s result. `remove_like` still removes the row, so reaction state is unchanged.
- An un-like after a reset therefore still withdraws the Like the Engine holds. An un-like of an imported like, or of one that predates the table, withdraws nothing.

`_handle_user_action` (docstring: "Apply one like/dislike action and publish the `Like`/`UndoLike` it causes, if any."):

```python
        publish = action in ("like", "undo_like")
        generation = 0  # the fixed generation of anonymous likes
        if profile_id is not None:
            try:
                publish, generation = self._store_reaction(profile_id, action, video)
            except DislikeLimitReached:
                ...  # unchanged
            except EngineApiError as exc:
                ...  # unchanged
            # A profile publishes only a like it opens or closes. A dislike publishes only to withdraw a like it replaced.
        if not publish:
            respond_json(self, 200, {"ok": True, "updatedAt": now_ms()})
            return

        event_type = "Like" if action == "like" else "UndoLike"
        actor = profile_id or "anonymous"
        # The JSON list keeps field boundaries unambiguous. Its encoding is part of every id, so it must never change.
        identity = json.dumps([actor, canonical_uuid, canonical_host, event_type, generation])
        event_payload = {
            "event_id": "client-" + hashlib.sha256(identity.encode("utf-8")).hexdigest(),
            "event_type": event_type,
            "actor_id": actor,
            ...  # object, published_at, source_instance, raw_payload unchanged
        }
```

`generation` is always an `int`: it comes from `int(row[0])`, the literal `1`, or `0`.

### `engine/server/data/random_videos.py`

After the imports:

```python
# The most of a video's interaction signal the popular ordering adds; the stored signal_score stays raw.
POPULAR_SIGNAL_CAP = 25.0
```

In `fetch_popular_videos`:
- docstring: "Return the most popular videos: popularity plus the capped interaction signal, then likes and views."
- `params: list[Any] = [POPULAR_SIGNAL_CAP, limit, limit]`
- the threshold branch sets `params = [error_threshold, POPULAR_SIGNAL_CAP, limit, limit]`
- the first ORDER BY term becomes `(v.popularity + MIN(COALESCE(sig.signal_score, 0), ?)) DESC,`

The placeholder order is: `{error_clause}` `?`, the cap `?`, the inner `LIMIT ?`, then the outer `LIMIT ?`. The `interaction_signal_score` column and the likes tiebreaker are untouched.

### Tests

**`tests/active/test_event_ids.py`** (new). It needs no live Engine or shared `whitelist.db` and is not rate-limited.

Module docstring: the T1–T8 bullets. Setup:
- Add `engine/server` and `engine/server/api` to `sys.path`, as `test_random_videos.py` does.
- Import `ensure_interaction_event_schema` and `ingest_interaction_event`.
- From conftest, import `RateLimiter`, `client_server` and `ensure_user_schema`.

Harness:
- `_serving(srv)`: copied from `test_server.py`, about 8 lines.
- A fixture `rig(tmp_path)` that yields `(client, engine_db, events)`:
  - `engine_db` is `sqlite3.connect(tmp_path / "engine.db", check_same_thread=False)` with `row_factory = sqlite3.Row`, after `ensure_interaction_event_schema`.
  - `events` is the list of `(payload, result)` pairs.
  - An `EngineStub(BaseHTTPRequestHandler).do_POST` routes three paths:
    - `/internal/videos/resolve`: answers `{"video": {"video_id": "vid-" + uuid, "instance_domain": host, "video_uuid": uuid, "video_url": f"https://{host}/w/{uuid}"}}`.
    - `/internal/dislikes/centroids`: answers `{"space": "test", "centroids": []}`, which `compute_dislike_centroids` turns into None.
    - `/internal/events/ingest`: runs `ingest_interaction_event(engine_db, payload)` under a lock, appends `(payload, result)`, and answers `{"ok": True, "duplicates": int(result["duplicate"]), "results": [result]}`. This is the real ingest, not a mock.
  - The Client is a `ClientBackendServer` on `tmp_path/"users.db"` in `"bridge"` mode with `RateLimiter(1000, 60)`, wrapped in conftest's `ClientBackend`.
- Helpers:
  - `_video()` returns a fresh `{"uuid": uuid4().hex, "host": "ids.example"}`.
  - `_act(client, headers, action, video)` posts `/api/user-action` and returns the status.
  - `_signal(engine_db, video)` returns `(likes_count, signal_score)`, or `(0, 0.0)`.
  - `_published(events)` returns `[(p["event_type"], p["event_id"]) for p, r in events]`.

Cases:
- **T1.** Mint, then like twice. Both answer 200. One event, a `Like`. `_signal == (1, 1.0)`.
- **T2.** Like, undo_like, like. The types are `[Like, UndoLike, Like]`. `ids[0] == ids[1]` is false, because the types differ. `ids[0] != ids[2]`. `ids[0]` equals the expected sha256 of `[profile_id, uuid, host, "Like", 1]`, which pins the encoding, and `ids[2]` uses generation 2. The final signal score is 1.0.
- **T3.** Take the first T1 payload and call `ingest_interaction_event(engine_db, payload)` again. `duplicate is True` and `_signal` is unchanged.
- **T4.** Anonymous like twice. Both ids are equal, the second result has `duplicate is True`, and `_signal == (1, 1.0)`.
- **T5.** Mint, then undo_like on a fresh video. Status 200 and no events.
- **T6.** Mint, like, dislike. There are exactly two events, and the second is an `UndoLike` whose id equals sha256 of `[pid, uuid, host, "UndoLike", 1]`, the id an undo_like at g1 would have used. Then, on a second fresh video, a dislike answers 200 and adds no event.
- **T7.** Mint, like, `POST /api/user-profile/reset` with the key, like again. Only one `Like` has been published. Then undo_like gives exactly one `UndoLike` at g1, and `_signal == (0, 0.0)`.
- **T8.** Mint, `POST /api/profile/likes/import` with the key and `{"likes": [{"video_uuid": uuid, "instance_domain": host}]}`, then undo_like. There are no events.
  - This depends on the stub's `resolve_videos_by_uuid_host` path. I have not read its endpoint yet (`engine_api_client.py:136-166`); the builder reads it and adds the matching stub route.
  - If that route turns out to cost more than about 15 lines, fall back to seeding with `record_like(conn, pid, "like", video, 100)` without `publish` on the users.db. That is exactly the call the import makes.

**`tests/active/test_random_videos.py`** gets `test_the_popular_order_caps_the_interaction_signal(tmp_path)`:
- `_two_video_db`, then `UPDATE videos SET popularity = 0` on `first` and `30` on `second`.
- `INSERT INTO interaction_signals (video_uuid, instance_domain, likes_count, signal_score, updated_at) VALUES (?, ?, 0, 1000.0, 0)` for `first`, then commit.
- For `threshold in (None, 1)`, `fetch_popular_videos(conn, 10, error_threshold=threshold)` returns `[second, first]` by `video_id`, and `first`'s `interaction_signal_score == 1000.0`, which shows the stored value is still raw.
- `_set_views` sets `error_count = 0`, so threshold 1 keeps both rows.
- Add a docstring bullet.
- A wrong params order either makes the cap act as the error threshold, which drops rows, or turns the limits into the cap. Both break one of the two branches.

**`tests/active/test_profiles.py`**:
- `_seed_like` passes `publish=True` to `record_like`.
- `_rows_for` adds `"like_generations": conn.execute("SELECT COUNT(*) FROM like_generations WHERE user_id = ?", (profile_id,)).fetchone()[0]`.
- The asserts at 205, 209 and 216 gain `"like_generations": 1`, and the one at 215 gains `"like_generations": 0`.
- The comment at 201 becomes "record_like also creates the `users` row and opens a like generation, so all four tables hold rows for both."
- `test_frontend_profile.py`'s `_seed_like` stays as it is (`publish` defaults to False).

### Existing tests, walked through with the flag

- `test_frontend_reactions` keyed sequence:
  - like: opens g1 and publishes.
  - dislike: closes g1, publishes UndoLike(g1).
  - undo_dislike: publishes nothing.
  - out-of-band dislike: nothing to close, 200.
  - like replacing the dislike: opens g2 and publishes.
  - undo_like: UndoLike(g2).
  - The same shape as the settled walk-through, so `all("ok" in a)` holds.
- The card test and `test_profiles.py:300`: a fresh profile's first like opens and publishes, so still 502 on `unpublished_client`.
- `test_dislikes` 74-87:
  - line 77 closes the like opened at line 74, which publishes, so 200 or 502;
  - line 82: 200;
  - line 84: nothing to close, 200.
- Keyless tests: unchanged from the inventory's account.
- Smokes: a fresh profile's first like opens and publishes, and the raw row is keyed by the profile.

### Acceptance criteria → evidence

| Criterion | Holds because | Test |
|---|---|---|
| Double like, one Like, +1 / +1.0 | second INSERT rowcount 0, nothing is opened | T1 |
| like→undo→like, distinct Like ids, 1.0 | g1 opened, closed, then g2 opened | T2 |
| Bridge retry is a duplicate | same id, `ON CONFLICT(event_id) DO NOTHING` | T3 |
| Anonymous duplicate | generation 0 and actor `anonymous` give a fixed id | T4 |
| undo_like of an unliked video: 200, nothing | nothing to close | T5 |
| Dislike UndoLike id = the undo_like id; unliked dislike publishes nothing | both go through `close_like` | T6 |
| Signal 1000 / pop 0 below pop 30 | `MIN(1000, 25) = 25 < 30` | T9 |
| `delete_profile` removes generations | new DELETE | T10 |
| Existing suites | walk-through above | T11 |

### Deviations from the settled plan and inventory

All of these follow from the operator's "close both with a published flag". None is silent.

1. **Schema.** `like_generations` gains `published INTEGER NOT NULL DEFAULT 0`. The inventory's DDL lists only four columns.
2. **When generation increments.** Only when a like is opened, that is, a new `likes` row from a publishing caller while `published=0`. The requirement says "on every new likes row". A re-like after a reset or trim, and every imported like, now leaves it unchanged. The contract still holds: a Like and its un-like share a generation, and the next Like differs.
3. **Un-like gating.** Publishing depends on `close_like`, not on `remove_like`'s result. `remove_like` is still called and still removes the row.
4. **`record_like` signature.** It gains the keyword `publish: bool = False`. `_handle_likes_import` (plan 14's handler) and the tests' `_seed_like` helpers keep working unedited. `record_like` returns `(opened, generation)` rather than `(new, generation)`.
5. **Reader.** The inventory's reader exists as `like_generation(conn, user_id, video_id, instance_domain) -> int`, with the positional shape and `:returns:`. The server imports the new writer `close_like` instead of the reader, so the users_store import line gains `close_like`.
6. **`test_profiles._seed_like`** passes `publish=True`. The inventory assumed `record_like` would always write a generation row.
7. **Plan Risks, "imported likes advance the generation, a later un-like publishes UndoLike (−1)".** This no longer happens: an imported like never publishes either event.

### Risks

- **Likes that predate `like_generations`.** They have no row, so their un-like publishes nothing. The Engine keeps the +1 from the old random-id Like. The un-like side is bounded at 0, where the settled plan would have published a gen-0 UndoLike.
- **Publish failure after the flag opens or closes** (bridge down, or `unpublished_client`). The Client's state moves while the Engine misses the event, and nothing retries it. Worst case, a later close publishes an UndoLike the Engine never saw a Like for. That is −1 once per generation, floored at 0. The settled plan had the same gap.
- **Trim gap.** It is narrower as a side effect: a re-like after a trim publishes nothing and a later un-like withdraws. It stays open when the profile never re-likes.
- **Anonymous import.** A like the browser published anonymously and then imported is never withdrawn by the profile. This falls under ADR-0001 §3's anonymous +1.
- **Concurrency.** Opening and closing are single conditional statements, so two concurrent requests cannot publish one transition twice. The existing dislike rat-tail is unchanged.
- **Merge with plan 14.** The import-line edits (`hashlib`, `close_like`) resolve by union. Its import caller is untouched.

### Documentation changes from the settled checklist

- `client/README.md` line 19: "an un-like publishes only when it withdraws a like the profile published, and a reset or import publishes nothing and never re-publishes".
- `CONTEXT.md` **Like generation**: add "and whether its like is published".
- ADR-0001 Consequences: add the published flag, the closed loops, the legacy-like note and the import note.
- `docs/project/roadmap.md`: drop the "close the reset/import loops" follow-up. Keep the import-publishing item, the likes-tiebreaker item, and a narrowed trim-gap item.

### Convergence

Pass 1 checked the draft against the plan and requirements, with the operator decision applied. Every requirement is met or listed above as an approved deviation. Pass 2 found `_seed_like` needing `publish=True` and the dislike branch's `close_like` placement, and added both. No further change was needed.

## 2026-09-27 - Step 6 - Design the phase breakdown

Approved by the operator.

#### Phase 1 - Popular signal cap [code]

**Files touched.** engine/server/data/random_videos.py (EDITED), tests/active/test_random_videos.py (EDITED)

**Checkpoint.** T9, `test_the_popular_order_caps_the_interaction_signal(tmp_path)` in tests/active/test_random_videos.py. The seam is a direct call to `fetch_popular_videos(conn, 10, error_threshold=threshold)` on the isolated tmp engine.db built by the existing `_two_video_db` harness, so the file's own tests are the precedent. Setup: `first` gets popularity 0, `second` gets popularity 30, and an `interaction_signals` row gives `first` a signal_score of 1000.0 with likes_count 0. The test runs for threshold in (None, 1), an explicit set covering both params branches. It asserts that the result order by `video_id` is [second, first]. As a control it asserts that `first`'s `interaction_signal_score == 1000.0`, so the stored score is shown to be raw. `_set_views` sets error_count = 0, so threshold 1 keeps both rows. A wrong params order therefore breaks at least one branch.

**Intent.** `fetch_popular_videos` in engine/server/data/random_videos.py orders videos by popularity plus the interaction signal capped at the module constant `POPULAR_SIGNAL_CAP`.

- C1 - A video with signal 1000 and popularity 0 ranks below a video with popularity 30 and no signal, with and without an error threshold.

**Outcome.** _pending_

#### Phase 2 - Publish on change, derived ids [code]

**Files touched.** client/backend/lib/users_store.py (EDITED), client/backend/server.py (EDITED), tests/active/test_event_ids.py (NEW)

**Checkpoint.** T1–T8 in tests/active/test_event_ids.py (NEW). The seam is HTTP POST to /api/user-action, /api/user-profile/reset and /api/profile/likes/import on a real `ClientBackendServer` in "bridge" mode over a tmp users.db, with `RateLimiter(1000, 60)`. It follows the `_serving` / `_client_backend` harness in test_server.py and is wrapped in conftest's `ClientBackend`. The Engine is a `BaseHTTPRequestHandler` stub with three routes. `/internal/videos/resolve` echoes a video. `/internal/dislikes/centroids` answers with empty centroids. `/internal/events/ingest` runs the real `ingest_interaction_event` on a tmp engine.db under a lock and records (payload, result). Assertions are made at the Engine boundary: the published (event_type, event_id) list and `interaction_signals` (likes_count, signal_score).
Clause 1: T1 (double like gives one Like, (1, 1.0)). T5 (undo_like of an unliked video answers 200 with no event). T6b (dislike of an unliked video adds no event). T7 (like, reset, like publishes one Like, and the later undo_like gives one UndoLike, ending at (0, 0.0)). T8 (import then undo_like gives no events). For T8, the builder reads engine_api_client.py:136-166 and adds the resolve-by-uuid stub route. If that route costs more than about 15 lines, the test seeds with `record_like` without `publish`.
Clause 2: T2 (like → undo_like → like gives [Like, UndoLike, Like]; ids[0] equals sha256 of json.dumps([pid, uuid, host, "Like", 1]); ids[2] uses generation 2 and differs from ids[0]; the signal ends at 1.0). T3 (re-ingesting T1's payload returns duplicate True and leaves the counts unchanged). T4 (two anonymous likes carry equal ids, the second is a duplicate, and the signal is (1, 1.0)). T6a (a dislike replacing a like publishes an UndoLike whose id is sha256 of [pid, uuid, host, "UndoLike", 1]).

**Intent.** A profile's POST /api/user-action publishes a Like or UndoLike only when it opens or closes that profile's published like of the video, tracked in the new `like_generations` table by `record_like(publish=True)` and `close_like` in users_store.py, and every event `_handle_user_action` publishes carries an id derived from actor, video, event type and like generation.

- C1 - An action that neither opens nor closes the profile's published like of the video publishes no event.
- C2 - A published event's id is `client-` plus the SHA-256 of the JSON list of actor, canonical uuid, canonical host, event type and like generation.

**Outcome.** _pending_

#### Phase 3 - Delete removes generations [code]

**Files touched.** client/backend/lib/profiles.py (EDITED), tests/active/test_profiles.py (EDITED)

**Checkpoint.** T10: extend the existing `test_deleting_a_profile_removes_its_rows_and_keeps_anothers` in tests/active/test_profiles.py. The seam is HTTP POST /api/profile/delete on conftest's `client_backend`, with row counts read straight from users.db through `_rows_for`, following the precedent in this test. `_seed_like` passes `publish=True`. `_rows_for` adds a `like_generations` count. The asserts at 205, 209 and 216 expect `"like_generations": 1`, and the one at 215 expects `"like_generations": 0`. The comment at 201 is updated to say all four tables hold rows.

**Intent.** `delete_profile` in client/backend/lib/profiles.py removes the deleted profile's `like_generations` rows inside its existing transaction.

- C1 - After one profile is deleted, it has no `like_generations` rows and another profile keeps its rows.

**Outcome.** _pending_


Needs coordination: none

Rationale: The Engine cap shares nothing with the Client work, so it is its own slice, checked at the harness test_random_videos.py already has. The users_store state machine (the table, `record_like(publish=True)` and `close_like`) and the server's gating and id derivation land together. The store only matters through what `_handle_user_action` publishes, so the one honest seam is HTTP in, Engine ingest out. A store-level suite would duplicate T1–T8 and pin internals. That Intent reduces to exactly two observable facts, publish gating and id derivation. `delete_profile` is a separate phase for two reasons: adding it to phase 2 would make three clauses, and it depends on the table phase 2 creates. test_profiles.py's `_seed_like` changes with it, not earlier. Phase 2's own `_seed_like` callers keep working because `publish` defaults to False. No prose phase: the README, CONTEXT.md, ADR-0001 and roadmap edits are documentation for Step 9. No coordination is needed: every checkpoint runs on tmp databases and a stub Engine whose ingest route is real, and whitelist.db is only read. The operator approved this breakdown as presented.

## 2026-09-27 - Step 7 - Phase 1 (Popular signal cap) - must_prove

Quoted from the phase Intent, written at Step 6 before the checkpoint was drafted.

Intent:
`fetch_popular_videos` in engine/server/data/random_videos.py orders videos by popularity plus the interaction signal capped at the module constant `POPULAR_SIGNAL_CAP`.

- C1 - A video with signal 1000 and popularity 0 ranks below a video with popularity 30 and no signal, with and without an error threshold.

must_prove:
- C1 - A video with signal 1000 and popularity 0 ranks below a video with popularity 30 and no signal, with and without an error threshold.

## 2026-09-27 - Step 7 - Phase 1 (Popular signal cap) - self-check (audit round 1, send-back 0)

`tests/tmp/test_13_deterministic_event_ids_phase1.py`, surface `checkpoint`. Collection exit 0.

- C1 - tests/tmp/test_13_deterministic_event_ids_phase1.py:69 — with `first` at popularity 0 plus signal 1000 and `second` at popularity 30 with no signal, `fetch_popular_videos(conn, 10, error_threshold=threshold)` returns the video ids in the order [second, first]. The loop runs this for threshold None and for threshold 1. Line 76 is a guard alongside it: with `second` at popularity 20, the order must be [first, second] at both thresholds. - expected: [second["video_id"], first["video_id"]] at both thresholds, because first's score of 0 + min(1000, 25) = 25 is lower than 30. At line 76 it is [first, second], because 25 is higher than 20. Under the current code the probe run showed [('first', 0.0, 1000.0), ('second', 30.0, 0)] at threshold None and at threshold 1, so line 69 is red now. At popularity 20 the probe showed first above second at both thresholds, so line 76 already holds and only stops the fix from dropping the signal. - excludes: The code as it stands orders by `v.popularity + COALESCE(sig.signal_score, 0)` with no cap, and the run showed line 69 reading [first, second] ('fd640a96…' ahead of 'd6abc74c…'). A cap added to only one of the two error-threshold query shapes leaves the other iteration reading [first, second] at line 69. Dropping the signal from the order, or capping it at the wrong value (0, or anything up to 20), makes line 76 read [second, first]. A cap of 30 or more leaves line 69 reading [first, second].

<assertions>
tests/tmp/test_13_deterministic_event_ids_phase1.py:69 - for threshold in (None, 1), with first at popularity 0 plus signal_score 1000.0 and second at popularity 30 with no signal, `fetch_popular_videos(conn, 10, error_threshold=threshold)` returns video_ids in the order [second, first]. If the signal is uncapped (today's code) it returns [first, second], which I saw in the red run. If the error clause dropped a row, the list would be shorter. - C1
tests/tmp/test_13_deterministic_event_ids_phase1.py:71 - control, on the same rows: `interaction_signal_score` is {first: 1000.0, second: 0}, so the returned score is still raw and the cap only acts on the ordering. It fails if the cap is applied to the output column or to storage. - C1 (control)
tests/tmp/test_13_deterministic_event_ids_phase1.py:76 - below-cap control, which the operator approved via AskUser (option control_literal): for threshold in (None, 1), with second at popularity CAP - 5 = 20, the order is [first, second], because 0 + min(1000, 25) = 25 > 20. It fails if the signal is dropped from the ordering. It also fails if the cap slot is filled by the threshold (1) or the limit (10) through a wrong params order: the probe showed those values give 1 and 10, both below 20. - C1
</assertions>

<probes>
Ran `ValidateTests ["tests/tmp/probe_cap.py", "-s"]`. It built the same tmp harness from whitelist.db, with first at popularity 0 plus a signal of 1000 and second at popularity 30. What it printed:
- whitelist.db gave two picks: first = fd640a96-d208-454d-9892-2872cb33a6bb and second = d6abc74c-903a-43f6-9bff-ff5865970ed7, both on yt.orokoro.ru.
- The interaction_signals columns are video_uuid, instance_domain, likes_count, undo_likes_count, comments_count, signal_score REAL and updated_at NOT NULL, so the INSERT needs updated_at.
- `hasattr(random_videos, 'POPULAR_SIGNAL_CAP')` is False today.
- `fetch_popular_videos` with threshold None and with threshold 1 both return [first(0.0, 1000.0 float), second(30.0, 0 int)]. That means threshold 1 keeps both rows when error_count = 0, the score for a video with no signal comes back as int 0, and today's order is uncapped, i.e. red.
- Raw SQL `popularity + MIN(COALESCE(signal_score,0), ?)` gives [second 30, first 25.0] for cap 25.0, [second 30, first 10.0] for cap 10 and [second 30, first 1.0] for cap 1. So the agreed C1 assertion alone cannot catch a params swap that puts 10 or 1 in the cap slot. I took that finding to the operator, who approved the below-cap control.
Then ran `ValidateTests ["tests/tmp/test_13_deterministic_event_ids_phase1.py"]`. It fails at line 69 (the C1 assertion, threshold None) with ['fd640a96…'] == ['d6abc74c…'], so the test is red on the missing cap and not on its own setup.
Leftovers:
- I have no delete tool, so I emptied tests/tmp/probe_cap.py to make it inert instead of deleting it. It is outside the named file and needs deleting.
- Those two ValidateTests runs rewrote tests/last_test_validation.json and tests/last_test_output.txt.
</probes>

<unassertable>
none. C1 is fully carried. Two deviations from the agreed Step 6 text, both reported here:
(1) The agreed checkpoint said the test lives in tests/active/test_random_videos.py and uses its `_two_video_db` harness. This step names tests/tmp/test_13_deterministic_event_ids_phase1.py, so the new file carries its own copy of the harness instead of importing from another test module. It also uses `_set_popularity`, which only sets popularity and error_count = 0.
(2) The agreed claim that "a wrong params order breaks at least one branch" turned out false for the threshold↔cap and limit↔cap swaps (see probes). With the operator's approval I added the below-cap control at line 76, which uses the requirement's cap of 25.0 as a literal (CAP) rather than importing POPULAR_SIGNAL_CAP.
</unassertable>

### `tests/tmp/test_13_deterministic_event_ids_phase1.py` - 4160 characters, inlined in full

```
"""The Engine's popular order adds a video's interaction signal only up to a cap of 25.

- `fetch_popular_videos` ranks a video with popularity 0 and a signal of 1000 below a video with popularity 30 and no signal, and above one with popularity 20, with and without an error threshold; the row still reports the raw signal of 1000.

The database is a temporary copy of two real videos out of `whitelist.db`; the signal is written straight into `interaction_signals`.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SERVER_DIR = ROOT / "engine" / "server"
# `data` imports `recommendations`, which lives under `api`, as the Engine's server.py runs it.
for path in (SERVER_DIR, SERVER_DIR / "api"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
WHITELIST_DB = SERVER_DIR / "db" / "whitelist.db"

from data.interaction_events import ensure_interaction_event_schema  # noqa: E402
from data.random_videos import fetch_popular_videos  # noqa: E402

SIGNAL = 1000.0
# The requirement's cap: a signal counts for at most this much in the popular order.
CAP = 25.0


def _two_video_db(tmp_path: Path) -> tuple[sqlite3.Connection, dict, dict]:
    """A database holding two real videos, in rowid order."""
    conn = sqlite3.connect(tmp_path / "engine.db")
    conn.row_factory = sqlite3.Row
    conn.execute(f"ATTACH DATABASE 'file:{WHITELIST_DB}?mode=ro' AS src")
    picks = conn.execute(
        "SELECT v.video_id, v.instance_domain FROM src.videos v JOIN src.video_embeddings e "
        "ON e.video_id = v.video_id AND e.instance_domain = v.instance_domain "
        "WHERE v.video_uuid IS NOT NULL ORDER BY v.rowid LIMIT 2"
    ).fetchall()
    assert len(picks) == 2
    where = " OR ".join(["(video_id = ? AND instance_domain = ?)"] * 2)
    args = [value for pick in picks for value in (pick["video_id"], pick["instance_domain"])]
    conn.execute(f"CREATE TABLE videos AS SELECT * FROM src.videos WHERE {where}", args)
    conn.execute(f"CREATE TABLE video_embeddings AS SELECT * FROM src.video_embeddings WHERE {where}", args)
    conn.execute("CREATE TABLE channels AS SELECT DISTINCT c.* FROM src.channels c JOIN videos v "
                 "ON c.channel_id = v.channel_id AND c.instance_domain = v.instance_domain")
    conn.commit()
    conn.execute("DETACH DATABASE src")
    ensure_interaction_event_schema(conn)
    rows = conn.execute("SELECT rowid, video_id, video_uuid, instance_domain FROM videos ORDER BY rowid").fetchall()
    return conn, dict(rows[0]), dict(rows[1])


def _set_popularity(conn: sqlite3.Connection, *popularities: tuple[dict, float]) -> None:
    # error_count 0 keeps both rows under an error threshold of 1.
    for video, popularity in popularities:
        conn.execute("UPDATE videos SET popularity = ?, error_count = 0 WHERE rowid = ?", (popularity, video["rowid"]))
    conn.commit()


def test_the_popular_order_caps_the_interaction_signal(tmp_path):
    conn, first, second = _two_video_db(tmp_path)
    conn.execute("INSERT INTO interaction_signals (video_uuid, instance_domain, likes_count, signal_score, updated_at) VALUES (?, ?, 0, ?, 0)",
                 (first["video_uuid"], first["instance_domain"], SIGNAL))
    conn.commit()

    for threshold in (None, 1):
        _set_popularity(conn, (first, 0.0), (second, 30.0))
        rows = fetch_popular_videos(conn, 10, error_threshold=threshold)
        assert [row["video_id"] for row in rows] == [second["video_id"], first["video_id"]], threshold  # C1
        scores = {row["video_id"]: row["interaction_signal_score"] for row in rows}
        assert scores == {first["video_id"]: SIGNAL, second["video_id"]: 0}, threshold  # control: the returned score stays raw

        # Below the cap the signal still lifts first over second, so a cap bound to the wrong parameter or a dropped signal fails here.
        _set_popularity(conn, (first, 0.0), (second, CAP - 5))
        rows = fetch_popular_videos(conn, 10, error_threshold=threshold)
        assert [row["video_id"] for row in rows] == [first["video_id"], second["video_id"]], threshold  # C1

```


Gate: satisfied

## 2026-09-27 - Step 7 - Phase 1 (Popular signal cap) - red (audit round 1)

`tests/tmp/test_13_deterministic_event_ids_phase1.py` exited 1.

```
  tests/tmp/test_13_deterministic_event_ids_phase1.py  1 failed                               0.0s
  ---------------------------------------------------
  total                                                1 failed                               0.2s wall, 1 lane

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

## 2026-09-27 - Step 7 - Phase 1 (Popular signal cap) - audit (round 1)

- AUDIT: devsecops-test-shape-auditor - PASS
- AUDIT: devsecops-test-claim-auditor - PASS
- OUTSTANDING: 3 UNCARRIED clause(s) - D1a, D1b, N2

### devsecops-test-shape-auditor

SHAPE AUDIT — VERDICT: PASS

CRITICAL
none

RECOMMENDATIONS
none

PREDICTED FAILURE
The test should fail first at line 69, on the order assertion when threshold is `None`. `fetch_popular_videos` sorts by `(v.popularity + COALESCE(sig.signal_score, 0)) DESC` with no cap (engine/server/data/random_videos.py:247). The first video scores 0 + 1000 = 1000, which beats the second video's 30, so the rows come back as `[first, second]` instead of `[second, first]`.

NOT ASSESSED
1. tests/active/test_random_videos.py was listed under `code_under_test` but only searched with Grep for test names and signal references, not read in full. The test under audit neither imports it nor uses anything from it.
2. No `fixtures_path` was supplied. The test uses only pytest's built-in `tmp_path` and its own helpers (`_two_video_db`, `_set_popularity`), so no conftest was needed. The fixture reads live data from engine/server/db/whitelist.db, whose contents were not checked.

### devsecops-test-claim-auditor

CLAIM AUDIT — VERDICT: PASS

CLAUSE MAP  (11 clauses: 2 must_prove, 7 docstring, 2 name)
| id | source | clause | assertion | excludes | status |
|---|---|---|---|---|---|
| C1a | must_prove | signal 1000 / popularity 0 ranks below popularity 30 / no signal, without an error threshold | :69 (threshold=None pass of the :66 loop) | adding the signal with no cap (0+1000 > 30 would put `first` first) | CARRIED |
| C1b | must_prove | the same order with an error threshold | :69 (threshold=1 pass of the :66 loop) | a cap applied only in the no-threshold branch; a query that breaks when the `error_clause` and its param are added | CARRIED |
| D1a | docstring | "adds a video's interaction signal only up to a cap of 25": the cap is 25 | :69 + :76 | only places the cap between 20 and 30. A cap of 21 or 29 passes both | UNCARRIED |
| D1b | docstring | "adds ... up to a cap": a signal below the cap is added in full | none | nothing. Every signal in the test is 1000, so a flat bonus for any positive signal passes | UNCARRIED |
| D2 | docstring | "ranks ... below a video with popularity 30 and no signal" | :69 | uncapped addition | CARRIED |
| D3 | docstring | "and above one with popularity 20" | :76 | dropping the signal from the order entirely (0 < 20) | CARRIED |
| D4 | docstring | "with and without an error threshold" | :66, :69, :71, :76 | behaviour that differs between the two branches | CARRIED |
| D5 | docstring | "the row still reports the raw signal of 1000" | :71 | returning the capped value in `interaction_signal_score` | CARRIED |
| D6 | docstring | "a temporary copy of two real videos out of `whitelist.db`" | :39 | a fixture that silently copies fewer than two videos | CARRIED |
| N1 | name | `the_popular_order_caps_the_interaction_signal` | :69, :76 | uncapped addition (:69) and a dropped signal (:76) | CARRIED |
| N2 | name | module name `test_13_deterministic_event_ids_phase1`: "deterministic event ids" | none | nothing. No assertion touches event ids | UNCARRIED |

CRITICAL
none

RECOMMENDATIONS
1. whole-claim (rules/testing.md) — tests/tmp/test_13_deterministic_event_ids_phase1.py:1
   `"""The Engine's popular order adds a video's interaction signal only up to a cap of 25.`
   D1a and D1b are UNCARRIED. The popularities of 30 at :67 and `CAP - 5` = 20 at :74 only show the cap is somewhere between 20 and 30. The value 25 is never pinned. Because every signal is 1000, "adds ... up to" is never shown to add a sub-cap signal in full, so a fixed +25 bonus for any positive signal passes. These are docstring clauses that are not in `must_prove`, so this does not block.
2. bounds (rules/testing.md) — tests/tmp/test_13_deterministic_event_ids_phase1.py:24
   Only one signal value is tested (`SIGNAL = 1000.0`). These edges are untested: a signal of exactly 25, a signal just past 25, a signal below the cap, a zero signal, and a video with no `interaction_signals` row alongside one that has a signal.
3. normal-and-abnormal-paths (rules/testing.md) — tests/tmp/test_13_deterministic_event_ids_phase1.py:56
   `error_count = 0` keeps both rows under the threshold of 1, so the threshold never excludes anything. No case shows how a high-signal video with `error_count >= threshold` is handled in the popular order.
4. name-as-sentence (rules/testing.md) — tests/tmp/test_13_deterministic_event_ids_phase1.py:1 (module name)
   N2 is UNCARRIED. The module name says "deterministic event ids", but the test is about a signal cap in the popular order. The runner's node id will point readers at the wrong behaviour.

OBSERVATIONS
none

NOT ASSESSED
1. `fixtures_path` was "none found". The test defines all its helpers itself (:29, :53) and uses only pytest's built-in `tmp_path`, so there was no conftest to read.
2. The test depends on the external read-only `engine/server/db/whitelist.db` (:19, :33) holding at least two videos with embeddings and a non-null uuid. I did not check the file's contents. :39 guards the count.

## 2026-09-27 - Step 7 - Phase 1 (Popular signal cap) - self-check (audit round 2, send-back 0)

`tests/tmp/test_13_deterministic_event_ids_phase1.py`, surface `checkpoint`. Collection exit 0.

- C1 - tests/tmp/test_13_deterministic_event_ids_phase1.py:80: for threshold in (None, 1), with first at popularity 0 and signal_score 1000.0 and second at popularity 30 with no signal, `fetch_popular_videos(conn, 10, error_threshold=threshold)` returns video_ids in the order [second, first]. :82 is its control: `interaction_signal_score` stays raw, {first: 1000.0, second: 0}. The :90 case at popularity 24.5 is the operator-approved below-cap control, moved from 20 to 24.5. - expected: [second, first] for both thresholds, since 0 + min(1000, 25) = 25 < 30. - excludes: Today's uncapped `popularity + COALESCE(signal_score, 0)` returns [first, second] (1000 > 30). The red run just now fails at :80 with threshold None and ['fd640a96…'] == ['d6abc74c…']. A cap applied only in the no-threshold branch fails the threshold=1 pass. A params order that puts the threshold (1) or the limit (10) in the cap slot still passes :80, but fails the 24.5 case at :90 (1 or 10 < 24.5).

<exemptions>
none
</exemptions>

<items>
<item id="D1a">
<disposition>fixed</disposition>
<what>I replaced the old `CAP - 5` = 20 control with two cases in the :86 loop, both checked by the :90 order assertion for threshold None and threshold 1, with first at popularity 0 and signal 1000. With second at `CAP - 0.5` = 24.5 the order is [first, second]. With second at `CAP + 0.5` = 25.5 the order is [second, first]. Together these pin the cap strictly between 24.5 and 25.5, and neither case is a tie. A probe using raw SQL `popularity + MIN(COALESCE(signal_score, 0), cap)` gave these results: cap 25 gives [first 25.0, second 24.5] and [second 25.5, first 25.0]; cap 24 gives [second 24.5, first 24.0], which fails the first case; cap 26 gives [first 26.0, second 25.5], which fails the second. So any integer cap other than 25 is excluded, and so are a dropped signal and a threshold (1) or limit (10) bound in the cap's slot. The docstring now says "pins the cap at 25 to within half a point". An earlier probe at 24/26 produced ties that were broken by row order, which is why I moved to ±0.5.</what>
</item>
<item id="D1b">
<disposition>fixed</disposition>
<what>The :86 loop now sets first's signal to `SUB_CAP_SIGNAL` = 10.0 using the new `_set_signal` helper, and :90 checks two orders: [first, second] with second at popularity 5, and [second, first] with second at popularity 15. This carries "a signal below the cap is added in full". A flat +25 bonus for any positive signal gives [first 25.0, second 15.0] at 15, so it fails there (seen in the probe). A dropped signal gives [second 5.0, first 0.0] at 5, so it fails there. The probe also ran today's `fetch_popular_videos` on these two cases and got [first(10.0), second] and [second, first(10.0)] for both thresholds, so the expected orders were observed in production code, where capped and uncapped agree below the cap. A new docstring bullet states this.</what>
</item>
<item id="N2">
<disposition>justified</disposition>
<what>I narrowed the prose. The file path `test_13_deterministic_event_ids_phase1` is the one this step names, and renaming it would touch a file outside the step. The module docstring now says: "The module is named for its build, plan 13 (deterministic event ids), whose second change is this cap; nothing here asserts anything about event ids." The cap is requirement (2) in the "Requirements: ranking cap" section of docs/project/plans/16-13-deterministic-event-ids.md, so the name is the build's, and the docstring no longer lets it read as a claim about the behaviour.</what>
</item>
</items>

<findings_addressed>
Claim audit RECOMMENDATION 1 (D1a/D1b whole-claim): taken. The cap is pinned by the 24.5/25.5 cases and full addition below the cap by the signal-10 cases at 5/15, all in the :86 loop and checked by :90; details in the D1a and D1b items.
Claim audit RECOMMENDATION 2 (bounds): partly taken. The signal is now tested below the cap (10) as well as far above it (1000), and the cap is bracketed at ±0.5. I did not add an exact-25 signal, a zero signal or a no-row case: an exact tie depends on the tiebreaker, and second already covers the no-row video.
Claim audit RECOMMENDATION 3 (a threshold that excludes a row): not taken. It is outside C1 and the phase leaves the threshold unchanged.
Claim audit RECOMMENDATION 4 (module name): addressed as N2. The file name is fixed by the step, and the docstring now says the name is the build's (plan 13), not the behaviour's.
No CRITICAL from either auditor.
Leftovers to report: tests/tmp/probe_cap.py is outside the named file. I emptied it again to make it inert, but it still needs deleting because I have no delete tool. My ValidateTests runs of the probe and the test also rewrote tests/last_test_validation.json and tests/last_test_output.txt.
</findings_addressed>

<rows>
<row clause="C1">
<assertion>tests/tmp/test_13_deterministic_event_ids_phase1.py:80: for threshold in (None, 1), with first at popularity 0 and signal_score 1000.0 and second at popularity 30 with no signal, `fetch_popular_videos(conn, 10, error_threshold=threshold)` returns video_ids in the order [second, first]. :82 is its control: `interaction_signal_score` stays raw, {first: 1000.0, second: 0}. The :90 case at popularity 24.5 is the operator-approved below-cap control, moved from 20 to 24.5.</assertion>
<expected>[second, first] for both thresholds, since 0 + min(1000, 25) = 25 < 30.</expected>
<wrong_implementation>Today's uncapped `popularity + COALESCE(signal_score, 0)` returns [first, second] (1000 > 30). The red run just now fails at :80 with threshold None and ['fd640a96…'] == ['d6abc74c…']. A cap applied only in the no-threshold branch fails the threshold=1 pass. A params order that puts the threshold (1) or the limit (10) in the cap slot still passes :80, but fails the 24.5 case at :90 (1 or 10 < 24.5).</wrong_implementation>
</row>
</rows>

<answers>
1. No. The test has no absence-only assertion. Every assertion is a positive order or score equality on rows that must be returned, and deleting the code under test fails them all.
2. No. The test never computes the capped sum. It asserts only which video leads, at popularities chosen to straddle 25, and that the raw score is echoed back. If the cap were removed from the ORDER BY (random_videos.py:247 as planned), :80 and the 25.5 case at :90 would turn red. If the signal term were removed, the 24.5 and popularity-5 cases would turn red. If the output column were capped, :82 would turn red.
3. No. The order is read at popularities 30, 24.5 and 25.5 with signal 1000, and at 5 and 15 with signal 10, each under both thresholds. That covers both sides of the cap and a sub-cap signal on both sides of its own value.
4. No. There are no doubles. The test uses the real `fetch_popular_videos` and `ensure_interaction_event_schema` on a tmp copy of real whitelist.db rows.
5. Yes, it collects. The imports are unchanged. `_set_signal` updates `interaction_signals.signal_score` by (video_uuid, instance_domain), and the probe saw rowcount 1 with the new value read back through `fetch_popular_videos` (10.0). The run collected 1 test.
6. Yes, the expected values were observed. The probe ran today's `fetch_popular_videos` for the sub-cap cases (orders [first, second] at 5 and [second, first] at 15) and raw-SQL cap/flat/dropped variants at 24.5 and 25.5 (cap 25 gives [first, second] and then [second, first], with no ties). An earlier probe at 24/26 showed ties, so I rewrote those cases to use ±0.5.
7. Yes. The ValidateTests run after the edit fails at :80 (C1, threshold None) on the uncapped order, not on setup, collection or an import.
</answers>

Gate: satisfied

## 2026-09-27 - Step 7 - Phase 1 (Popular signal cap) - red (audit round 2)

`tests/tmp/test_13_deterministic_event_ids_phase1.py` exited 1.

```
  tests/tmp/test_13_deterministic_event_ids_phase1.py  1 failed                               0.0s
  ---------------------------------------------------
  total                                                1 failed                               0.2s wall, 1 lane

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

## 2026-09-27 - Step 7 - Phase 1 (Popular signal cap) - audit (round 2)

- AUDIT: devsecops-test-shape-auditor - PASS
- AUDIT: devsecops-test-claim-auditor - BLOCK
- OUTSTANDING: 1 UNCARRIED clause(s) - N2; devsecops-test-claim-auditor: critical

### devsecops-test-shape-auditor

```
SHAPE AUDIT — VERDICT: PASS

CRITICAL
none

RECOMMENDATIONS
none

PREDICTED FAILURE
Fails at tests/tmp/test_13_deterministic_event_ids_phase1.py:80 on the first pass
(threshold None). The ordering assertion expects [second, first] but gets
[first["video_id"], second["video_id"]], because fetch_popular_videos
(engine/server/data/random_videos.py:247) sorts by
`v.popularity + COALESCE(sig.signal_score, 0)` with no cap, so 0 + 1000 ranks above 30.

NOT ASSESSED
1. `fixtures_path` was not supplied. The test's only fixture is pytest's built-in
   `tmp_path`, and tests/active/conftest.py does not cover tests/tmp/, so no fixture
   went unread.
2. The test builds its database from engine/server/db/whitelist.db at run time
   (lines 38-44). The data in that file was not read. The stub question assumes the
   query returns two videos with a non-null video_uuid, which line 44 asserts.
```

### devsecops-test-claim-auditor

CLAIM AUDIT — VERDICT: BLOCK

CLAUSE MAP  (11 clauses: 2 must_prove, 7 docstring, 2 name)
| id | source | clause | assertion | excludes | status |
|---|---|---|---|---|---|
| C1a | must_prove | signal 1000 / popularity 0 ranks below popularity 30 / no signal, without an error threshold | :80 (threshold=None pass of the :76 loop) | adding the signal with no cap (0+1000 > 30 would put `first` first) | CARRIED |
| C1b | must_prove | the same order with an error threshold | :80 (threshold=1 pass of the :76 loop) | a cap applied only in the no-threshold branch; a query that breaks when the `error_clause` and its param are added | CARRIED |
| D1a | docstring | "adds a video's interaction signal only up to a cap of 25": the cap is 25 | :90 (cases 1000 vs 24.5 and 1000 vs 25.5 at :86) | any cap of 24.5 or less (including a dropped signal) and any cap of 25.5 or more. This puts the cap within half a point of 25, which is what docstring :4 now claims | CARRIED |
| D1b | docstring | "adds ... up to a cap": a signal below the cap is added in full | :90 (cases 10 vs 5 and 10 vs 15 at :86) | a flat cap bonus for any positive signal (25 > 15 fails) and a dropped signal (0 < 5 fails). A signal scaled into the open range (5, 15) still passes, which docstring :5 now states | CARRIED |
| D2 | docstring | "ranks ... below a video with popularity 30 and no signal" | :80 | uncapped addition | CARRIED |
| D3 | docstring | withdrawn | n/a | n/a | CARRIED |
| D4 | docstring | "with and without an error threshold" | :76, :80, :82, :90 | behaviour that differs between the two branches | CARRIED |
| D5 | docstring | "the row still reports the raw signal of 1000" | :82 | returning the capped value in `interaction_signal_score` | CARRIED |
| D6 | docstring | "a temporary copy of two real videos out of `whitelist.db`" | :44 | a fixture that silently copies fewer than two videos | CARRIED |
| N1 | name | `the_popular_order_caps_the_interaction_signal` | :80, :90 | uncapped addition (:80), and a cap set anywhere but 25 ± 0.5 (:90) | CARRIED |
| N2 | name | module name `test_13_deterministic_event_ids_phase1`: "deterministic event ids" | none | nothing. No assertion touches event ids. Docstring :7 now says so in prose, which does not carry the clause | UNCARRIED |

CRITICAL
1. whole-claim (rules/testing.md), re-audit rule 2. tests/tmp/test_13_deterministic_event_ids_phase1.py:7
   `The module is named for its build, plan 13 (deterministic event ids), whose second change is this cap; nothing here asserts anything about event ids.`
   N2 was UNCARRIED on the first audit and is still UNCARRIED. The module name still claims "deterministic event ids". The rewrite added a docstring sentence explaining the mismatch but did not add an assertion or rename the module, so nothing rules out any wrong event-id implementation. A reader of the runner output sees `test_13_deterministic_event_ids_phase1` and trusts a claim the file admits it does not test. The rule requires the name's clause to be carried by an assertion. The fix is to rename the module to what it proves (for example, the popular-order signal cap), not to explain the name in prose.

RECOMMENDATIONS
none

OBSERVATIONS
1. whole-claim (rules/testing.md): tests/tmp/test_13_deterministic_event_ids_phase1.py:4. Row D3 ("and above one with popularity 20") no longer appears in the docstring. It was replaced by a stronger sentence, "ranks above popularity 24.5 and below popularity 25.5", which :90 asserts. So the prose was replaced by a stricter claim that is asserted. It was not narrowed to escape the finding. Recorded here as re-audit rule 4 requires.
2. normal-and-abnormal-paths (rules/testing.md): tests/tmp/test_13_deterministic_event_ids_phase1.py:61, :76. `_set_popularity` sets `error_count = 0` on both rows, so the threshold=1 pass never has a row the threshold removes. The with-threshold pass proves the order holds when the `error_clause` is present. It does not prove the cap still holds when the clause actually filters out a row. C1 does not ask for that, so this does not block.
3. bounds (rules/testing.md): tests/tmp/test_13_deterministic_event_ids_phase1.py:86. The signals tested are 1000 and 10. A signal exactly at the cap (25) and a signal of 0 on the scored video are not tested. A `<`-versus-`<=` mistake at the cap boundary would not be caught.

NOT ASSESSED
1. `fixtures_path` was not supplied. The test uses only pytest's built-in `tmp_path` and defines no other fixtures, so no conftest was needed.
2. What is actually in `engine/server/db/whitelist.db` was not inspected. The only check is that :44 asserts two qualifying videos exist.
3. `tests/active/test_random_videos.py` is listed in `code_under_test`. I only searched it for its popular-order assertions and did not read it in full. It is a sibling test, not code this test exercises.

## 2026-09-27 - Step 7 - Phase 1 (Popular signal cap) - self-check (audit round 3, send-back 0)

`tests/tmp/test_13_deterministic_event_ids_phase1.py`, surface `checkpoint`. Collection exit 0.

- C1 - tests/tmp/test_13_deterministic_event_ids_phase1.py:80. For threshold in (None, 1), with first at popularity 0 and signal_score 1000.0 and second at popularity 30 with no signal, `fetch_popular_videos(conn, 10, error_threshold=threshold)` returns video_ids in the order [second, first]. :82 is its control: `interaction_signal_score` stays raw, {first: 1000.0, second: 0}. The :90 case at popularity 24.5 is the below-cap control the operator approved earlier, moved from 20 to 24.5. - expected: [second, first] for both thresholds, since 0 + min(1000, 25) = 25 < 30. - excludes: Today's uncapped `popularity + COALESCE(signal_score, 0)` returns [first, second], because 1000 > 30. The last red run failed at :80 with threshold None and ['fd640a96…'] == ['d6abc74c…']. A cap applied only in the no-threshold branch fails the threshold=1 pass. A params order that puts the threshold (1) or the limit (10) in the cap's slot still passes :80, but fails the 24.5 case at :90 (1 or 10 < 24.5).

Exemptions the operator granted, verified against the agent's own transcript: N2

<exemptions>
<exemption clause="N2">
<answer>exempt (the operator picked "Exempt N2": "Keep the workflow's path. The module name belongs to the build (plan 13), and the docstring already says nothing here tests event ids.")</answer>
<why>What is conceded: no assertion carries the "deterministic event ids" claim in the module name `test_13_deterministic_event_ids_phase1`. The name comes from the workflow's path scheme: plan 13, the build slug, phase 1. It is not a claim about behaviour. Docstring :7 already says nothing here asserts anything about event ids. Renaming the file would create a gating path this step does not name. No other test in this phase carries event-id behaviour; this phase delivers the popular-order cap.</why>
</exemption>
</exemptions>

<items>
none
</items>

<findings_addressed>
Claim audit CRITICAL 1 (N2, module name claims "deterministic event ids"): I asked the operator with AskUser whether to rename the module or exempt N2, and they chose "exempt". N2 is declared in <exemptions>, so it needs no item. The test file is unchanged this round. Leftover to report again: tests/tmp/probe_cap.py is still on disk (emptied, so it does nothing) and needs deleting; I have no delete tool.
</findings_addressed>

<rows>
<row clause="C1">
<assertion>tests/tmp/test_13_deterministic_event_ids_phase1.py:80. For threshold in (None, 1), with first at popularity 0 and signal_score 1000.0 and second at popularity 30 with no signal, `fetch_popular_videos(conn, 10, error_threshold=threshold)` returns video_ids in the order [second, first]. :82 is its control: `interaction_signal_score` stays raw, {first: 1000.0, second: 0}. The :90 case at popularity 24.5 is the below-cap control the operator approved earlier, moved from 20 to 24.5.</assertion>
<expected>[second, first] for both thresholds, since 0 + min(1000, 25) = 25 < 30.</expected>
<wrong_implementation>Today's uncapped `popularity + COALESCE(signal_score, 0)` returns [first, second], because 1000 > 30. The last red run failed at :80 with threshold None and ['fd640a96…'] == ['d6abc74c…']. A cap applied only in the no-threshold branch fails the threshold=1 pass. A params order that puts the threshold (1) or the limit (10) in the cap's slot still passes :80, but fails the 24.5 case at :90 (1 or 10 < 24.5).</wrong_implementation>
</row>
</rows>

<answers>
1. No. The test has no absence-only assertion. Every assertion is a positive order or score equality on rows that must be returned, and deleting the code under test fails them all.
2. No. The test never computes the capped sum. It asserts only which video leads, at popularities chosen to straddle 25, and that the raw score comes back unchanged. If the cap were removed from the ORDER BY (random_videos.py:247), :80 and the 25.5 case at :90 would turn red. If the signal term were removed, the 24.5 and popularity-5 cases would turn red. If the output column were capped, :82 would turn red.
3. No. The order is read at popularities 30, 24.5 and 25.5 with signal 1000, and at 5 and 15 with signal 10, each under both thresholds.
4. No. There are no doubles. The test uses the real `fetch_popular_videos` and `ensure_interaction_event_schema` on a temporary copy of real whitelist.db rows.
5. Yes, it collects. The file is unchanged since the last run, which collected 1 test.
6. Yes, the expected values were observed. They come from the earlier probe runs of today's `fetch_popular_videos` and of raw-SQL cap variants. Nothing changed this round.
7. Yes. The file is unchanged, so it still fails at :80 (C1, threshold None) on the uncapped order, not on setup, collection or an import.
</answers>

Gate: NOT SATISFIED - the frozen ledger leaves D1a, D1b UNCARRIED and your reply carries no item for them

## 2026-09-27 - Step 7 - Phase 1 (Popular signal cap) - self-check (audit round 3, send-back 1)

`tests/tmp/test_13_deterministic_event_ids_phase1.py`, surface `checkpoint`. Collection exit 0.

- C1 - tests/tmp/test_13_deterministic_event_ids_phase1.py:80: for threshold in (None, 1), with the first video at popularity 0 and signal_score 1000.0 and the second at popularity 30 with no signal, `fetch_popular_videos(conn, 10, error_threshold=threshold)` returns video_ids in the order [second, first]. Its control is :82, which checks that `interaction_signal_score` stays raw: {first: 1000.0, second: 0}. The popularity-24.5 case at :90 is the below-cap control the operator approved earlier, moved from 20 to 24.5. - expected: [second, first] under both thresholds, since 0 + min(1000, 25) = 25 < 30. - excludes: Today's uncapped `popularity + COALESCE(signal_score, 0)` returns [first, second], because 1000 > 30. The last red run failed at :80 with threshold None: ['fd640a96…'] == ['d6abc74c…']. A cap applied only in the no-threshold branch fails the threshold=1 pass. A params order that puts the threshold (1) or the limit (10) in the cap's slot still passes :80, but fails the 24.5 case at :90, because 1 and 10 are both below 24.5.

Exemptions the operator granted, verified against the agent's own transcript: N2

<exemptions>
<exemption clause="N2">
<answer>exempt (the operator picked "Exempt N2": "Keep the workflow's path. The module name belongs to the build (plan 13), and the docstring already says nothing here tests event ids.")</answer>
<why>What is conceded: no assertion carries the "deterministic event ids" claim in the module name `test_13_deterministic_event_ids_phase1`. The name comes from the workflow's path scheme (plan 13, the build slug, phase 1) and is not a claim about behaviour. Docstring :7 already says nothing here asserts anything about event ids. Renaming the file would create a gating path this step does not name. No other test in this phase covers event-id behaviour, because this phase delivers the popular-order cap.</why>
</exemption>
</exemptions>

<items>
<item id="D1a">
<disposition>fixed</disposition>
<what>The previous round added the (SIGNAL, CAP - 0.5) and (SIGNAL, CAP + 0.5) cases to the :86 loop, and :90 asserts them under both thresholds. With signal 1000, the first video must rank above popularity 24.5 and below popularity 25.5. That excludes any cap of 24.5 or less, which includes a dropped signal and the threshold 1 or limit 10 bound into the cap's slot. It also excludes any cap of 25.5 or more, which includes uncapped addition. The cap is now pinned to 25 ± 0.5, and docstring :4 was narrowed to say exactly that. The current claim audit marks D1a CARRIED at :90.</what>
</item>
<item id="D1b">
<disposition>fixed</disposition>
<what>The previous round added the (SUB_CAP_SIGNAL=10, 5.0) and (SUB_CAP_SIGNAL=10, 15.0) cases to the :86 loop, and :90 asserts them under both thresholds. A signal of 10 must rank above popularity 5 and below popularity 15. That excludes a flat bonus of the cap for any positive signal (25 > 15 would put the first video first) and a dropped signal (0 < 5). Docstring :5 states the claim at the precision the test asserts. The current claim audit marks D1b CARRIED at :90.</what>
</item>
</items>

<findings_addressed>
Claim audit CRITICAL 1 (N2: the module name claims "deterministic event ids"): the operator chose "Exempt N2" through AskUser, so N2 is declared in <exemptions> and needs no item. The test file is unchanged this round. This resubmission only adds the ledger items for D1a and D1b, which the previous round fixed at :86/:90. Leftover to report: tests/tmp/probe_cap.py is still on disk. It is emptied and does nothing, but it needs deleting, and I have no delete tool.
</findings_addressed>

<rows>
<row clause="C1">
<assertion>tests/tmp/test_13_deterministic_event_ids_phase1.py:80: for threshold in (None, 1), with the first video at popularity 0 and signal_score 1000.0 and the second at popularity 30 with no signal, `fetch_popular_videos(conn, 10, error_threshold=threshold)` returns video_ids in the order [second, first]. Its control is :82, which checks that `interaction_signal_score` stays raw: {first: 1000.0, second: 0}. The popularity-24.5 case at :90 is the below-cap control the operator approved earlier, moved from 20 to 24.5.</assertion>
<expected>[second, first] under both thresholds, since 0 + min(1000, 25) = 25 < 30.</expected>
<wrong_implementation>Today's uncapped `popularity + COALESCE(signal_score, 0)` returns [first, second], because 1000 > 30. The last red run failed at :80 with threshold None: ['fd640a96…'] == ['d6abc74c…']. A cap applied only in the no-threshold branch fails the threshold=1 pass. A params order that puts the threshold (1) or the limit (10) in the cap's slot still passes :80, but fails the 24.5 case at :90, because 1 and 10 are both below 24.5.</wrong_implementation>
</row>
</rows>

<answers>
1. No. There is no absence-only assertion. Every assertion is a positive check of order or score on rows that must be returned, so deleting the code under test fails all of them.
2. No. The test never computes the capped sum itself. It asserts only which video leads, at popularities chosen to straddle 25, and that the raw score comes back unchanged. Removing the cap from the ORDER BY (random_videos.py:247) turns :80 and the 25.5 case at :90 red. Removing the signal term turns the 24.5 and popularity-5 cases red. Capping the output column turns :82 red.
3. No. The order is read at popularities 30, 24.5 and 25.5 with signal 1000, and at 5 and 15 with signal 10, each under both thresholds.
4. No. There are no doubles. The test uses the real `fetch_popular_videos` and `ensure_interaction_event_schema` on a temporary copy of real whitelist.db rows.
5. Yes, it collects. The file is unchanged since the last run, which collected 1 test.
6. Yes, the expected values were observed, in the earlier probe runs of today's `fetch_popular_videos` and of raw-SQL cap variants. Nothing changed this round.
7. Yes. The file is unchanged, so it still fails at :80 (C1, threshold None) on the uncapped order, not on setup, collection or an import.
</answers>

Gate: satisfied

## 2026-09-27 - Step 7 - Phase 1 (Popular signal cap) - red (audit round 3)

`tests/tmp/test_13_deterministic_event_ids_phase1.py` exited 1.

```
  tests/tmp/test_13_deterministic_event_ids_phase1.py  1 failed                               0.0s
  ---------------------------------------------------
  total                                                1 failed                               0.2s wall, 1 lane

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

## 2026-09-27 - Step 7 - Phase 1 (Popular signal cap) - audit (round 3)

- AUDIT: devsecops-test-shape-auditor - PASS
- AUDIT: devsecops-test-claim-auditor - PASS
- OUTSTANDING: nothing

### devsecops-test-shape-auditor

```
SHAPE AUDIT — VERDICT: PASS

CRITICAL
none

RECOMMENDATIONS
none

PREDICTED FAILURE
Fails at tests/tmp/test_13_deterministic_event_ids_phase1.py:80 on the first pass of the loop
(threshold None). The order assertion receives [first["video_id"], second["video_id"]] where it
expects [second["video_id"], first["video_id"]]. The cause is engine/server/data/random_videos.py:247,
which orders by the uncapped `v.popularity + COALESCE(sig.signal_score, 0)`, so 0 + 1000 ranks above 30 + 0.

NOT ASSESSED
1. `code_under_test` lists tests/active/test_random_videos.py, which is a test file and not code this
   test exercises. It was read and has no bearing on this verdict.
2. `fixtures_path` was not supplied. The test uses only pytest's built-in `tmp_path` and defines its
   own helpers, so no conftest was needed. The symbols it imports exist:
   ensure_interaction_event_schema at engine/server/data/interaction_events.py:19, and
   fetch_popular_videos at engine/server/data/random_videos.py:195. So do the interaction_signals
   columns written at line 72, at interaction_events.py:42-51.
3. Anti-patterns pass (rules/shape.md): no entry matches.
   - doc-lint-grep, section-scoped-substring-grep, whole-file-source-name-grep: the test reads no
     document and does no substring check.
   - hardcoded-spec-mirror: CAP at line 30 is compared with no code constant. The test only uses it
     to build inputs.
   - tautological-assertion: the expected values at lines 80 and 90 are written-down orderings, not
     worked out the way the code works them out.
   - absence-only-assertion: every assertion is a positive equality.
   - echoed-literal: line 82 gets SIGNAL back, but through the production SELECT in
     fetch_popular_videos, and it is a control that sits next to the order assertions rather than
     standing alone.
   - single-value-pin: the ranking is read at six input pairs (lines 78 and 86), each checked under
     two thresholds, so an output that ignored its input would fail at least one.
4. Ladder pass (rules/shape.md <ladder>): rung 1. The test calls fetch_popular_videos directly and
   asserts on the rows it returns. That is the highest rung for a ranking invariant, so there is no
   downshift and no comment is needed. It is not on the anti-rung.
5. Stub question: the unchanged code ranks signal 1000 first and fails line 80. Dropping the signal
   altogether, or capping at 24 or less, fails the (CAP - 0.5) case at line 86. Capping at 26 or more
   fails the (CAP + 0.5) case. Adding a flat cap bonus for any signal fails the (SUB_CAP_SIGNAL, 15.0)
   case. A hard-coded order cannot satisfy both the leader-first and trailer-first cases at line 86.
   The test fails against each of these wrong implementations, so it works as a gate.
```

### devsecops-test-claim-auditor

CLAIM AUDIT — VERDICT: PASS

CLAUSE MAP  (11 clauses: 2 must_prove, 7 docstring, 2 name)
| id | source | clause | assertion | excludes | status |
|---|---|---|---|---|---|
| C1a | must_prove | signal 1000 / popularity 0 ranks below popularity 30 / no signal, without an error threshold | :80 (threshold=None pass of the :76 loop) | adding the signal with no cap (0+1000 > 30 would put `first` first) | CARRIED |
| C1b | must_prove | the same order with an error threshold | :80 (threshold=1 pass of the :76 loop) | a cap applied only in the no-threshold branch; a query that breaks when `error_clause` and its param are added | CARRIED |
| D1a | docstring | "adds a video's interaction signal only up to a cap of 25": the cap is 25 | :90 (cases `CAP - 0.5`, `CAP + 0.5`, both thresholds) | any cap of 24.5 or less (including a dropped signal) and any cap of 25.5 or more, so every integer cap other than 25. Docstring :4 gives the half-point tolerance itself | CARRIED |
| D1b | docstring | "adds ... up to a cap": a signal below the cap is added in full | :90 (cases `SUB_CAP_SIGNAL` against 5.0 and 15.0, both thresholds) | a flat cap-sized bonus for any positive signal (25 > 15), and a dropped sub-cap signal (0 < 5) | CARRIED |
| D2 | docstring | "ranks ... below a video with popularity 30 and no signal" | :80 | uncapped addition | CARRIED |
| D3 | docstring | withdrawn | n/a | n/a | CARRIED |
| D4 | docstring | "with and without an error threshold" | :76, :80, :82, :90 | behaviour that differs between the two branches | CARRIED |
| D5 | docstring | "the row still reports the raw signal of 1000" | :82 | returning the capped value in `interaction_signal_score` | CARRIED |
| D6 | docstring | "a temporary copy of two real videos out of `whitelist.db`" | :44 | a fixture that silently copies fewer than two videos | CARRIED |
| N1 | name | `the_popular_order_caps_the_interaction_signal` | :80, :90 | uncapped addition (:80); a cap anywhere other than 25 ± 0.5 (:90) | CARRIED |
| N2 | name | module name `test_13_deterministic_event_ids_phase1`: "deterministic event ids" | n/a | n/a | EXEMPT |

CRITICAL
none

RECOMMENDATIONS
none

OBSERVATIONS
1. whole-claim (rules/testing.md): D3 at tests/tmp/test_13_deterministic_event_ids_phase1.py:1-5. The first-audit sentence "and above one with popularity 20" is no longer in the docstring, so under `<re_audit>` rule 4 the row is recorded as withdrawn. This was a replacement, not a retreat. Docstring :4 now claims a stronger bound ("ranks above popularity 24.5"), and :90 asserts it (`(SIGNAL, CAP - 0.5, first, second)`). That bound implies the one that was dropped.
2. whole-claim (rules/testing.md): D1b at tests/tmp/test_13_deterministic_event_ids_phase1.py:86/:90. "Counts in full" is only pinned to the range (5, 15). A signal scaled before it is capped, such as `min(0.6 * signal, 25)`, gives 6 for a signal of 10 and passes both sub-cap cases. It also passes the 24.5/25.5 cases. Docstring :5 describes exactly the range it checks ("ranks above popularity 5 and below popularity 15"), so the prose and the assertion agree. Checking against 9.5 and 10.5 would pin "in full" as tightly as :4 pins the cap.
3. normal-and-abnormal-paths (rules/testing.md): tests/tmp/test_13_deterministic_event_ids_phase1.py:59/:61. The threshold=1 pass always sets `error_count = 0` on both rows, so the error threshold never excludes a row. Nothing shows that the capped order still holds when the threshold filters out one of the ranked videos.
4. bounds (rules/testing.md): tests/tmp/test_13_deterministic_event_ids_phase1.py:86. The signals tested are 1000, 10 and 0, the last being the unsignalled `second`. There is no case for a signal exactly at the cap (25) or at zero on a row that has an `interaction_signals` entry.

NOT ASSESSED
1. `fixtures_path` was none, and the test defines its own helpers (`_two_video_db`, `_set_popularity`, `_set_signal`) and uses only pytest's built-in `tmp_path`, so there is no conftest to read. The contents of `engine/server/db/whitelist.db` were not read. D6 was judged from the `assert len(picks) == 2` guard at :44.

## 2026-09-27 - Step 7 - Phase 1 (Popular signal cap) - checkpoint outcome (run 1)

`tests/tmp/test_13_deterministic_event_ids_phase1.py` exited 0 after the phase landed.

<changes>
### `engine/server/data/random_videos.py`
- Added the module constant `POPULAR_SIGNAL_CAP = 25.0`. It has a one-line comment saying why it exists: a burst of interaction events should not be able to outrank crawled popularity.
- `fetch_popular_videos` now ranks by `v.popularity + MIN(COALESCE(sig.signal_score, 0), ?)` instead of `v.popularity + COALESCE(sig.signal_score, 0)`. The cap is a bound parameter. It sits in `params` after the optional error threshold and before the two `limit`s, which matches where each `?` appears in the SQL. This is true with and without an error threshold.
- The tie-breakers after the popularity term are unchanged (likes plus signal likes, views, published_at, video_id).
- The returned `interaction_signal_score` column is unchanged and still reports the raw, uncapped signal.

### `tests/active/test_random_videos.py`
Not changed. It only uses a signal of 1.0, well under the cap, so the cap doesn't affect it. It has no expectation that conflicts with this change, so this phase had no reason to edit it.
</changes>

<inner_tests>
none
</inner_tests>

<unanticipated>
none
</unanticipated>

<awaiting_operator>
none
</awaiting_operator>

```
  tests/tmp/test_13_deterministic_event_ids_phase1.py  1 passed                               0.0s
  ---------------------------------------------------
  total                                                1 passed                               0.2s wall, 1 lane

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

## 2026-09-27 - Step 7 - Phase 2 (Publish on change, derived ids) - must_prove

Quoted from the phase Intent, written at Step 6 before the checkpoint was drafted.

Intent:
A profile's POST /api/user-action publishes a Like or UndoLike only when it opens or closes that profile's published like of the video, tracked in the new `like_generations` table by `record_like(publish=True)` and `close_like` in users_store.py, and every event `_handle_user_action` publishes carries an id derived from actor, video, event type and like generation.

- C1 - An action that neither opens nor closes the profile's published like of the video publishes no event.
- C2 - A published event's id is `client-` plus the SHA-256 of the JSON list of actor, canonical uuid, canonical host, event type and like generation.

must_prove:
- C1 - An action that neither opens nor closes the profile's published like of the video publishes no event.
- C2 - A published event's id is `client-` plus the SHA-256 of the JSON list of actor, canonical uuid, canonical host, event type and like generation.

## 2026-09-27 - Step 7 - Phase 2 (Publish on change, derived ids) - self-check (audit round 1, send-back 0)

`tests/tmp/test_13_deterministic_event_ids_phase2.py`, surface `checkpoint`. Collection exit 0.

- C1 - tests/tmp/test_13_deterministic_event_ids_phase2.py:140 — after two keyed likes of one video (both 200), the published event types are exactly ["Like"] - expected: ["Like"]. The second like opens nothing, so nothing is published for it. - excludes: Publishing every keyed like, as today's `publish = action in ("like", "undo_like")` does. The run read ['Like', 'Like'] at :140.
- C1 - tests/tmp/test_13_deterministic_event_ids_phase2.py:181 — a keyed undo_like of a video the profile never liked (200 at :180) publishes nothing: rig.events == [] - expected: []. The positive control at :184 then shows the same rig does publish a later like, at generation 1. - excludes: Publishing every undo_like whether or not a like was closed. The run read one ('UndoLike', client-<uuid4>) event at :181.
- C1 - tests/tmp/test_13_deterministic_event_ids_phase2.py:197 — after a dislike and then an undo_dislike of a second, unliked video, the total published count is still 2 (the Like and UndoLike of the first video) - expected: 2. The control at :195 shows the dislike was stored ({"liked": False, "disliked": True}). - excludes: A gate that publishes an UndoLike on every dislike or undo_dislike, e.g. treating any dislike-branch write as a change. That reads 3 or 4. Today's code already passes this, so it is a regression guard and not a red gate: the earlier probe saw 0 events for both actions. This run stopped at :192 before reaching :197.
- C1 - tests/tmp/test_13_deterministic_event_ids_phase2.py:208 — like, reset, like publishes exactly ["Like"], though the controls at :205 and :207 show the reset removed the like and the re-like was stored - expected: ["Like"]. The profile's first Like is still published at the Engine, so the re-like opens nothing. - excludes: Opening a new generation on every new `likes` row, which was the pre-flag plan, or today's unconditional publish. Either publishes a second Like. The run read ['Like', 'Like'] at :208.
- C1 - tests/tmp/test_13_deterministic_event_ids_phase2.py:222 — an undo_like of an imported like publishes nothing, though the controls at :218, :219 and :221 show the import stored the like and the undo removed it - expected: []. The positive control at :225 shows a later like publishes at generation 1. - excludes: Gating the UndoLike on `remove_like`'s result instead of on a published like being closed. The imported row is removed, so an UndoLike goes out. The run read one ('UndoLike', client-<uuid4>) event at :222.
- C1 - tests/tmp/test_13_deterministic_event_ids_phase2.py:153 — like, undo_like, like publishes exactly ["Like", "UndoLike", "Like"] - expected: ["Like", "UndoLike", "Like"]. Each action opens or closes the like, so each one publishes. - excludes: An over-eager gate whose published flag never reopens after a close. It suppresses the re-like and reads ["Like", "UndoLike"]. Today's code passes this line (the run got past :153 to :155), so it guards against over-suppression rather than gating red.
- C2 - tests/tmp/test_13_deterministic_event_ids_phase2.py:142 — the one Like of a repeated like is ("Like", "client-" + sha256(json.dumps([pid, uuid, host, "Like", 1]))) - expected: [("Like", _event_id(pid, video, "Like", 1))] - excludes: A random `client-<uuid4>` id (today), or a profile Like hashed at generation 0. Either gives a different id. This run stopped at :140 before reaching :142. The same shape of comparison failed at :155 with 'client-4a39328d-…' != 'client-ebc4288c…'.
- C2 - tests/tmp/test_13_deterministic_event_ids_phase2.py:154 — in like, undo_like, like, the first and third event ids differ - expected: published[0][1] != published[2][1], because generation 1 and generation 2 hash differently. - excludes: An id derived without the generation, i.e. sha256 of [actor, uuid, host, type]. Both Likes would carry one id and the re-like would collapse as a duplicate. Today's random ids pass this line (the run got past it); :155 carries the red.
- C2 - tests/tmp/test_13_deterministic_event_ids_phase2.py:155 — like, undo_like, like publishes exactly [Like at generation 1, UndoLike at generation 1, Like at generation 2], each id from the formula - expected: [("Like", _event_id(pid, v, "Like", 1)), ("UndoLike", _event_id(pid, v, "UndoLike", 1)), ("Like", _event_id(pid, v, "Like", 2))] - excludes: Random ids fail at index 0: the run read 'client-4a39328d-d608-…' against 'client-ebc4288cc953…'. An UndoLike that reads the generation after bumping it (g2), or reads 0, fails at index 1. A different serialisation, such as a separator join or compact JSON, fails every index.
- C2 - tests/tmp/test_13_deterministic_event_ids_phase2.py:162 — two anonymous likes both publish ("Like", id of ["anonymous", uuid, host, "Like", 0]) - expected: [("Like", _event_id("anonymous", video, "Like", 0))] * 2 - excludes: Random ids (the run read 'client-b20648d6-…' against 'client-aaf04505…'). Hashing `profile_id` (None, which serialises as `null`) instead of "anonymous" also gives another id, as does using generation 1 for anonymous likes.
- C2 - tests/tmp/test_13_deterministic_event_ids_phase2.py:163 — the real Engine ingest reports the two anonymous likes' duplicate flags as [False, True] - expected: [False, True] - excludes: Any id that is not fixed for (anonymous, video, Like, 0). The earlier probe saw [False, False] with today's random ids. This run stopped at :162 first.
- C2 - tests/tmp/test_13_deterministic_event_ids_phase2.py:174 — a like that names the video as an upper-case uuid and host "IDS.Example" publishes the id over the uuid and host the Engine resolved them to (lower-case) - expected: [("Like", _event_id(pid, canonical, "Like", 1))]. The controls at :172 and :173 passed, so the resolved lower-case uuid and host do reach the payload's object. - excludes: Hashing the request body's raw `uuid`/`host` instead of the resolved `canonical_uuid`/`canonical_host`. That hashes the upper-case spelling and gives a different digest. The run read today's 'client-2dd2d03b-…' (uuid4) against 'client-e2fff181…'.
- C2 - tests/tmp/test_13_deterministic_event_ids_phase2.py:192 — like then dislike publishes the Like at generation 1 and the UndoLike at generation 1, the id a profile undo_like would have used - expected: [("Like", _event_id(pid, liked, "Like", 1)), ("UndoLike", _event_id(pid, liked, "UndoLike", 1))] - excludes: Random ids (the run read 'client-8964b24e-…' against 'client-a5b72b00…'). A dislike branch that returns generation 0, the `undo_dislike` tail's default, gives a different UndoLike id.
- C2 - tests/tmp/test_13_deterministic_event_ids_phase2.py:212 — after like, reset, like, undo_like, the events are the Like and the UndoLike, both at generation 1 - expected: [("Like", _event_id(pid, video, "Like", 1)), ("UndoLike", _event_id(pid, video, "UndoLike", 1))] - excludes: Bumping the generation on the post-reset re-like, which puts the UndoLike at generation 2 and leaves the Engine's generation-1 Like standing. This run stopped at :208 before reaching :212.

<assertions>
tests/tmp/test_13_deterministic_event_ids_phase2.py:137 - T1: after two keyed likes of one video (both 200, :136), the published event types are exactly ["Like"]. Today: ['Like', 'Like'] (observed, red here) - C1
tests/tmp/test_13_deterministic_event_ids_phase2.py:138 - T1: interaction_signals for the video is (likes_count 1, signal_score 1.0). Today the probe showed (2, 2.0) - C1
tests/tmp/test_13_deterministic_event_ids_phase2.py:139 - T1: the one published event is ("Like", "client-" + sha256(json.dumps([profile_id, uuid, host, "Like", 1]))). Today the id is client-<uuid4> - C2
tests/tmp/test_13_deterministic_event_ids_phase2.py:141 - T3: re-ingesting T1's recorded payload unchanged through the real ingest_interaction_event returns duplicate True. This also holds today, because the same payload carries the same id. It guards the retry contract - C2
tests/tmp/test_13_deterministic_event_ids_phase2.py:142 - T3: after the retry the signal is still (1, 1.0) - C2
tests/tmp/test_13_deterministic_event_ids_phase2.py:150 - T2: like, undo_like, like (all 200, :148) publish exactly the types ["Like", "UndoLike", "Like"]. This holds today too; it guards an over-eager gate - C1
tests/tmp/test_13_deterministic_event_ids_phase2.py:151 - T2: the first and third event ids differ. This holds today too, since the ids are random; it fails an id with no generation in it - C2
tests/tmp/test_13_deterministic_event_ids_phase2.py:152 - T2: the published list equals [Like at generation 1, UndoLike at generation 1, Like at generation 2], each id from the spec formula. Today: random client-<uuid4> ids (observed, red here) - C2
tests/tmp/test_13_deterministic_event_ids_phase2.py:153 - T2: the signal ends at (1, 1.0) - C2
tests/tmp/test_13_deterministic_event_ids_phase2.py:159 - T4: two anonymous likes (both 200, :158) both publish ("Like", id of ["anonymous", uuid, host, "Like", 0]). Today: two different client-<uuid4> ids (observed, red here) - C2
tests/tmp/test_13_deterministic_event_ids_phase2.py:160 - T4: the Engine results' duplicate flags are [False, True]. Today: [False, False] (observed) - C2
tests/tmp/test_13_deterministic_event_ids_phase2.py:161 - T4: the signal is (1, 1.0). With distinct ids it would be (2, 2.0) - C2
tests/tmp/test_13_deterministic_event_ids_phase2.py:167 - T5: a keyed undo_like of a video the profile never liked answers 200 - C1
tests/tmp/test_13_deterministic_event_ids_phase2.py:168 - T5: nothing is published. Today it publishes one UndoLike (observed, red here) - C1
tests/tmp/test_13_deterministic_event_ids_phase2.py:171 - T5 control: a like afterwards publishes exactly the Like at generation 1. This shows the rig does publish and the refused undo moved no generation - control
tests/tmp/test_13_deterministic_event_ids_phase2.py:178 - T6a: like then dislike (both 200, :177) publish exactly the types ["Like", "UndoLike"]. This holds today too - C1
tests/tmp/test_13_deterministic_event_ids_phase2.py:179 - T6a: those events are the Like at generation 1 and the UndoLike at generation 1, the same id the matching undo_like gets at :152. Today: random ids (observed, red here) - C2
tests/tmp/test_13_deterministic_event_ids_phase2.py:180 - T6a: the signal ends at (0, 0.0) - C2
tests/tmp/test_13_deterministic_event_ids_phase2.py:182 - T6b control: after a dislike of a second, unliked video (200, :181), the reaction reads {"liked": False, "disliked": True}, so the dislike was stored - control
tests/tmp/test_13_deterministic_event_ids_phase2.py:184 - T6b: after that dislike and an undo_dislike (200, :183), still exactly 2 events have been published. This holds today too (probe: 0 events for both); it is a regression guard - C1
tests/tmp/test_13_deterministic_event_ids_phase2.py:192 - T7 control: after like and reset (200, :191), the reaction reads not liked - control
tests/tmp/test_13_deterministic_event_ids_phase2.py:194 - T7 control: after the re-like (200, :193), the reaction reads liked, so the re-like was stored and not refused - control
tests/tmp/test_13_deterministic_event_ids_phase2.py:195 - T7: like, reset, like has published exactly ["Like"]. Today: ['Like', 'Like'] (observed, red here). A generation bumped on every new likes row would also give two - C1
tests/tmp/test_13_deterministic_event_ids_phase2.py:197 - T7: the following undo_like (200, :196) brings the types to exactly ["Like", "UndoLike"] - C1
tests/tmp/test_13_deterministic_event_ids_phase2.py:198 - T7: the signal ends at (0, 0.0) - C1
tests/tmp/test_13_deterministic_event_ids_phase2.py:199 - T7: the events are the Like and the UndoLike, both at generation 1, so the undo withdraws the first like - C2
tests/tmp/test_13_deterministic_event_ids_phase2.py:205 - T8: POST /api/profile/likes/import of the video answers (200, {"imported": 1}) through the stub's existing resolve route - control
tests/tmp/test_13_deterministic_event_ids_phase2.py:206 - T8 control: the reaction reads liked after the import - control
tests/tmp/test_13_deterministic_event_ids_phase2.py:208 - T8 control: after the undo_like (200, :207), the reaction reads not liked, so the undo removed the imported like - control
tests/tmp/test_13_deterministic_event_ids_phase2.py:209 - T8: nothing has been published. Today it publishes one UndoLike (observed, red here) - C1
tests/tmp/test_13_deterministic_event_ids_phase2.py:212 - T8 control: a like afterwards publishes exactly the Like at generation 1, so the import opened no generation. An import that advanced the generation would give generation 2 - control
</assertions>

<probes>
1. Harness and current behaviour. I wrote tests/tmp/probe_13_phase2.py, built the same rig (conftest imported by path from tests/tmp, a real ClientBackendServer in bridge mode, a stub Engine with resolve, centroids and a real-ingest route) and ran `ValidateTests ["tests/tmp/probe_13_phase2.py", "-s"]` against today's code. It printed:
- MINT 201 ['key', 'profile_id'].
- Keyed like, like, undo_like, like: all 200 with bridge_ok True. EVENTS were Like, Like, UndoLike, Like, each with a distinct client-<uuid4> id, actor = profile_id, all duplicate False. SIGNAL was likes_count 2, signal_score 2.0.
- Re-ingesting the first payload: {'ok': True, 'duplicate': True, ...}.
- DISLIKE-UNLIKED 200 with 0 events. UNDO-DISLIKE 200 with 0 events. UNDO-UNLIKED 200 with ['UndoLike'].
- IMPORT (200, {'imported': 1}). UNDO-IMPORTED 200 with ['UndoLike'].
- RESET-LIKE 200, RESET 200, RESET-LIKE2 200 with ['Like', 'Like'].
- ANON 200 twice: two different client-<uuid4> ids, both duplicate False.
- PATHS hit: /internal/dislikes/centroids, /internal/events/ingest, /internal/videos/resolve. So the import resolves through the same resolve route, T8 needs no extra stub route, and no fallback to seeding with record_like was needed.

2. The checkpoint itself. `ValidateTests ["tests/tmp/test_13_deterministic_event_ids_phase2.py"]` gave 7 failed, exit 1, each on its intended assertion after its controls passed:
- :137 ['Like', 'Like'] == ['Like']
- :152, :159 and :179: client-<uuid4> ids vs the derived client-<sha256> ids (:150, :151 and :178 passed)
- :168 one UndoLike vs []
- :195 ['Like', 'Like'] == ['Like'] (the controls at :192 and :194 passed)
- :209 one UndoLike vs [] (the controls at :205, :206 and :208 passed)

3. Housekeeping: I emptied the probe file afterwards. There is no delete tool, so an empty tests/tmp/probe_13_phase2.py is left and needs removing. It is the only file touched outside the named test.
</probes>

<unassertable>
none. Every C1 and C2 case in the checkpoint (T1-T8) is asserted. Three limits to know about:

(a) What the fixed code will output is a prediction from the requirement's formula: "client-" + sha256 of json.dumps([actor, uuid, host, event_type, generation]) with default separators, UTF-8 encoded, anonymous at generation 0. It cannot be observed until the phase is built. The phase's green run will confirm it.

(b) These assertions pass on today's code and act as regression guards rather than red gates: T3 (:141, :142), T6b (:184), and the event-type and id-distinctness checks at :150, :151 and :178. They are in the agreed checkpoint as written.

(c) The file lives at tests/tmp/, as this step names, rather than at the checkpoint's tests/active/test_event_ids.py. So it imports conftest's ClientBackend, RateLimiter, client_server and ensure_user_schema by adding tests/active to sys.path. This is done before the Engine dirs go on the path, because both trees hold a `server` module.
</unassertable>

### `tests/tmp/test_13_deterministic_event_ids_phase2.py` - 11391 characters, inlined in full

```
"""A profile's user action publishes a Like or UndoLike only when it opens or closes the profile's like of the video, and every published event's id is `client-` plus the SHA-256 of the JSON list [actor, uuid, host, event type, like generation].

- Two likes of one video by one profile publish one Like, at generation 1, and the video's signal is (1, 1.0); re-ingesting that Like's payload unchanged, as a bridge retry does, is a duplicate and leaves (1, 1.0).
- like, undo_like, like publishes Like, UndoLike, Like at generations 1, 1 and 2, the two Like ids differ, and the signal ends at (1, 1.0).
- Two anonymous likes both publish the Like id for actor `anonymous` at generation 0; the Engine counts the second as a duplicate and the signal is (1, 1.0).
- undo_like of a video the profile never liked answers 200 and publishes nothing; a like afterwards publishes at generation 1.
- A dislike replacing a like publishes the UndoLike id an undo_like would have used (generation 1) and leaves (0, 0.0); a dislike, and an undo_dislike, of a video the profile does not like publish nothing.
- like, reset, like publishes one Like, though the re-like is stored; the undo_like after it publishes that Like's UndoLike and leaves (0, 0.0).
- undo_like of an imported like publishes nothing, though the import stored the like and the undo removed it; a like afterwards publishes at generation 1.

A real Client backend in bridge mode over a tmp users.db talks to a stub Engine: resolve echoes the video, centroids are empty, and ingest runs the real `ingest_interaction_event` on a tmp engine.db, recording each payload and result.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[2]
# conftest's Client harness is imported before the Engine dirs go on sys.path: both trees hold a `server` module.
ACTIVE_DIR = ROOT / "tests" / "active"
if str(ACTIVE_DIR) not in sys.path:
    sys.path.insert(0, str(ACTIVE_DIR))
from conftest import ClientBackend, RateLimiter, client_server, ensure_user_schema  # noqa: E402

SERVER_DIR = ROOT / "engine" / "server"
for path in (SERVER_DIR, SERVER_DIR / "api"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
from data.interaction_events import ensure_interaction_event_schema, ingest_interaction_event  # noqa: E402

HOST = "ids.example"


def _event_id(actor: str, video: dict, event_type: str, generation: int) -> str:
    """The id the requirement derives for one event."""
    return "client-" + hashlib.sha256(json.dumps([actor, video["uuid"], video["host"], event_type, generation]).encode("utf-8")).hexdigest()


@contextmanager
def _serving(srv):
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}"
    finally:
        srv.shutdown()
        srv.server_close()


@pytest.fixture
def rig(tmp_path):
    engine_db = sqlite3.connect(tmp_path / "engine.db", check_same_thread=False)
    engine_db.row_factory = sqlite3.Row
    ensure_interaction_event_schema(engine_db)
    lock = threading.Lock()
    events = []

    class EngineStub(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            body = json.loads(self.rfile.read(int(self.headers["content-length"])))
            status = 200
            if self.path == "/internal/videos/resolve":
                answer = {"video": {"video_id": "vid-" + body["uuid"], "instance_domain": body["host"], "video_uuid": body["uuid"], "video_url": f"https://{body['host']}/w/{body['uuid']}"}}
            elif self.path == "/internal/dislikes/centroids":
                answer = {"space": "test", "centroids": []}
            elif self.path == "/internal/events/ingest":
                # The real ingest, so a repeated id is collapsed by the Engine's own ON CONFLICT.
                with lock:
                    result = ingest_interaction_event(engine_db, body)
                    events.append((body, result))
                answer = {"ok": True, "duplicates": int(result["duplicate"]), "results": [result]}
            else:
                status, answer = 404, {"error": "Not found"}
            data = json.dumps(answer).encode("utf-8")
            self.send_response(status)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format, *args):
            pass

    conn = client_server.connect_db(tmp_path / "users.db")
    ensure_user_schema(conn)
    try:
        with _serving(ThreadingHTTPServer(("127.0.0.1", 0), EngineStub)) as engine_base, _serving(client_server.ClientBackendServer(("127.0.0.1", 0), client_server.ClientBackendHandler, conn, engine_base, "bridge", RateLimiter(1000, 60))) as base:
            yield SimpleNamespace(client=ClientBackend(base, tmp_path / "users.db"), engine_db=engine_db, events=events)
    finally:
        conn.close()
        engine_db.close()


def _mint(client) -> tuple[str, dict[str, str]]:
    status, body = client.request("POST", "/api/profile")
    assert status == 201, body
    return body["profile_id"], {"X-Profile-Key": body["key"]}


def _video() -> dict[str, str]:
    return {"uuid": uuid4().hex, "host": HOST}


def _act(client, headers, action: str, video: dict) -> int:
    return client.request("POST", "/api/user-action", headers, {"action": action, **video})[0]


def _reaction(client, headers, video: dict) -> dict:
    status, body = client.request("GET", f"/api/profile/reaction?uuid={video['uuid']}&host={video['host']}", headers)
    assert status == 200, body
    return body


def _published(events) -> list[tuple[str, str]]:
    return [(payload["event_type"], payload["event_id"]) for payload, _ in events]


def _signal(engine_db, video: dict) -> tuple[int, float]:
    row = engine_db.execute("SELECT likes_count, signal_score FROM interaction_signals WHERE video_uuid = ? AND instance_domain = ?", (video["uuid"], video["host"])).fetchone()
    return (row["likes_count"], row["signal_score"]) if row else (0, 0.0)


def test_a_repeated_like_publishes_one_like_and_a_bridge_retry_of_it_is_a_duplicate(rig):
    pid, key = _mint(rig.client)
    video = _video()
    assert [_act(rig.client, key, "like", video) for _ in range(2)] == [200, 200]
    assert [event_type for event_type, _ in _published(rig.events)] == ["Like"]  # C1
    assert _signal(rig.engine_db, video) == (1, 1.0)  # C1
    assert _published(rig.events) == [("Like", _event_id(pid, video, "Like", 1))]  # C2
    retry = ingest_interaction_event(rig.engine_db, rig.events[0][0])
    assert retry["duplicate"] is True  # C2
    assert _signal(rig.engine_db, video) == (1, 1.0)  # C2


def test_like_undo_like_like_publishes_like_undolike_like_under_generations_1_1_2(rig):
    pid, key = _mint(rig.client)
    video = _video()
    assert [_act(rig.client, key, action, video) for action in ("like", "undo_like", "like")] == [200, 200, 200]
    published = _published(rig.events)
    assert [event_type for event_type, _ in published] == ["Like", "UndoLike", "Like"]  # C1
    assert published[0][1] != published[2][1]  # C2
    assert published == [("Like", _event_id(pid, video, "Like", 1)), ("UndoLike", _event_id(pid, video, "UndoLike", 1)), ("Like", _event_id(pid, video, "Like", 2))]  # C2
    assert _signal(rig.engine_db, video) == (1, 1.0)  # C2


def test_two_anonymous_likes_carry_one_id_and_the_engine_counts_the_second_as_a_duplicate(rig):
    video = _video()
    assert [_act(rig.client, None, "like", video) for _ in range(2)] == [200, 200]
    assert _published(rig.events) == [("Like", _event_id("anonymous", video, "Like", 0))] * 2  # C2
    assert [result["duplicate"] for _, result in rig.events] == [False, True]  # C2
    assert _signal(rig.engine_db, video) == (1, 1.0)  # C2


def test_an_undo_like_of_an_unliked_video_answers_200_and_publishes_nothing(rig):
    pid, key = _mint(rig.client)
    video = _video()
    assert _act(rig.client, key, "undo_like", video) == 200  # C1
    assert rig.events == []  # C1
    # This rig does publish an opening like, and the refused undo advanced no generation.
    assert _act(rig.client, key, "like", video) == 200
    assert _published(rig.events) == [("Like", _event_id(pid, video, "Like", 1))]  # control


def test_a_dislike_replacing_a_like_publishes_the_undo_likes_id_and_one_of_an_unliked_video_publishes_nothing(rig):
    pid, key = _mint(rig.client)
    liked, unliked = _video(), _video()
    assert [_act(rig.client, key, action, liked) for action in ("like", "dislike")] == [200, 200]
    assert [event_type for event_type, _ in _published(rig.events)] == ["Like", "UndoLike"]  # C1
    assert _published(rig.events) == [("Like", _event_id(pid, liked, "Like", 1)), ("UndoLike", _event_id(pid, liked, "UndoLike", 1))]  # C2
    assert _signal(rig.engine_db, liked) == (0, 0.0)  # C2
    assert _act(rig.client, key, "dislike", unliked) == 200
    assert _reaction(rig.client, key, unliked) == {"liked": False, "disliked": True}  # control: the dislike was stored
    assert _act(rig.client, key, "undo_dislike", unliked) == 200
    assert len(rig.events) == 2  # C1


def test_a_like_after_a_reset_publishes_nothing_and_the_next_undo_like_withdraws_the_first(rig):
    pid, key = _mint(rig.client)
    video = _video()
    assert _act(rig.client, key, "like", video) == 200
    assert rig.client.request("POST", "/api/user-profile/reset", key, {})[0] == 200
    assert _reaction(rig.client, key, video) == {"liked": False, "disliked": False}  # control: the reset removed the like
    assert _act(rig.client, key, "like", video) == 200
    assert _reaction(rig.client, key, video) == {"liked": True, "disliked": False}  # control: the re-like is stored
    assert [event_type for event_type, _ in _published(rig.events)] == ["Like"]  # C1
    assert _act(rig.client, key, "undo_like", video) == 200
    assert [event_type for event_type, _ in _published(rig.events)] == ["Like", "UndoLike"]  # C1
    assert _signal(rig.engine_db, video) == (0, 0.0)  # C1
    assert _published(rig.events) == [("Like", _event_id(pid, video, "Like", 1)), ("UndoLike", _event_id(pid, video, "UndoLike", 1))]  # C2: the undo withdraws the first like's generation


def test_an_undo_like_of_an_imported_like_publishes_nothing(rig):
    pid, key = _mint(rig.client)
    video = _video()
    assert rig.client.request("POST", "/api/profile/likes/import", key, {"likes": [video]}) == (200, {"imported": 1})
    assert _reaction(rig.client, key, video) == {"liked": True, "disliked": False}  # control: the import stored the like
    assert _act(rig.client, key, "undo_like", video) == 200
    assert _reaction(rig.client, key, video) == {"liked": False, "disliked": False}  # control: the undo removed it
    assert rig.events == []  # C1
    # The import opened no generation, so the first published like is generation 1.
    assert _act(rig.client, key, "like", video) == 200
    assert _published(rig.events) == [("Like", _event_id(pid, video, "Like", 1))]  # control

```


Gate: satisfied

## 2026-09-27 - Step 7 - Phase 2 (Publish on change, derived ids) - red (audit round 1)

`tests/tmp/test_13_deterministic_event_ids_phase2.py` exited 1.

```
  tests/tmp/test_13_deterministic_event_ids_phase2.py  8 failed                               0.0s
  ---------------------------------------------------
  total                                                8 failed                               5.2s wall, 1 lane

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

## 2026-09-27 - Step 7 - Phase 2 (Publish on change, derived ids) - audit (round 1)

- AUDIT: devsecops-test-shape-auditor - PASS
- AUDIT: devsecops-test-claim-auditor - PASS
- OUTSTANDING: 3 UNCARRIED clause(s) - D6, D7, N1b

### devsecops-test-shape-auditor

```
SHAPE AUDIT — VERDICT: PASS

CRITICAL
none

RECOMMENDATIONS
none

PREDICTED FAILURE
Fails at line 140 in test_a_repeated_like_publishes_one_like_and_a_bridge_retry_of_it_is_a_duplicate.
The published event types come out as ["Like", "Like"] instead of ["Like"], because the handler
at client/backend/server.py:784 sets `publish = action in ("like", "undo_like")` and so publishes
on every like. Every test that compares an id to `_event_id` (for example line 174) fails on its
own terms, since server.py:802 still mints `f"client-{uuid4()}"`.

NOT ASSESSED
1. `code_under_test` listed tests/active/test_event_ids.py (NEW), which does not resolve. It had
   no part in the assessment.
2. client/backend/lib/users_store.py was read only as far as its function signatures and any
   `generation` symbol, of which there is none yet. The stub question was answered from the
   assertion form and the server.py publish path (lines 760-830).
3. `fixtures_path` was "none found". The fixtures the test uses (`rig`, `_serving`) are defined
   in the test file. `ClientBackend`, `RateLimiter`, `ensure_user_schema` and `client_server`
   were traced to tests/active/conftest.py lines 39-47, and `ingest_interaction_event` to
   engine/server/data/interaction_events.py:57. Their bodies were not read beyond those lines.
```

### devsecops-test-claim-auditor

CLAIM AUDIT — VERDICT: PASS

CLAUSE MAP  (54 clauses: 12 must_prove, 29 docstring, 13 name)
| id | source | clause | assertion | excludes | status |
|---|---|---|---|---|---|
| C1a | must_prove | a repeat like of a video the profile already likes publishes nothing | :140 | publishing a Like on every `like` action | CARRIED |
| C1b | must_prove | undo_like of a video with no published like publishes nothing | :181 | publishing an UndoLike on every `undo_like` | CARRIED |
| C1c | must_prove | a dislike of a video the profile does not like publishes nothing | :197 | publishing on a dislike that removed no like | CARRIED |
| C1d | must_prove | undo_dislike of a video the profile does not like publishes nothing | :197 | publishing on undo_dislike (the count stays 2 after both actions) | CARRIED |
| C1e | must_prove | re-like after a reset, while the published like is still open, publishes nothing | :208 | deciding to publish from the stored like instead of the published one | CARRIED |
| C1f | must_prove | undo_like of an imported (never published) like publishes nothing | :222 | publishing an UndoLike because a stored like was removed | CARRIED |
| C2a | must_prove | id is `client-` + SHA-256 hex of the JSON list | :142 | a `client-{uuid4}` id or any other hash or encoding | CARRIED |
| C2b | must_prove | actor in the hashed list (profile id / `anonymous`) | :142, :162 | leaving out the actor, or using some other actor string | CARRIED |
| C2c | must_prove | canonical uuid in the hashed list | :174 | hashing the upper-case uuid as sent | CARRIED |
| C2d | must_prove | canonical host in the hashed list | :174 | hashing `IDS.Example` as sent | CARRIED |
| C2e | must_prove | event type in the hashed list | :155 | Like and UndoLike at generation 1 sharing one id | CARRIED |
| C2f | must_prove | like generation in the hashed list | :154, :155, :162 | a re-like after an undo reusing generation 1; anonymous not at 0 | CARRIED |
| D1 | docstring | "publishes a Like or UndoLike only when it opens or closes" the like | :140, :153, :181, :191, :197 | publishing on no-op actions, or failing to publish on real open/close | CARRIED |
| D2 | docstring | "every published event's id is `client-` plus the SHA-256 of…" | :142, :155, :162, :174 | any id other than the derived one | CARRIED |
| D3 | docstring | "Two likes … publish one Like" | :140 | a Like per action | CARRIED |
| D4 | docstring | "at generation 1" | :142 | generation 0 or 2 on the first like | CARRIED |
| D5 | docstring | "the video's signal is (1, 1.0)" | :141 | the Engine counting two likes | CARRIED |
| D6 | docstring | "re-ingesting that Like's payload unchanged, as a bridge retry does, is a duplicate" | :144 | nothing: the test re-sends the dict it recorded, so the same `event_id` collides with itself under any id scheme, `uuid4` included | UNCARRIED |
| D7 | docstring | "and leaves (1, 1.0)" | :145 | nothing beyond D6: once the re-ingest is a duplicate, the signal cannot move | UNCARRIED |
| D8 | docstring | "publishes Like, UndoLike, Like at generations 1, 1 and 2" | :155 | wrong order, or wrong generation on any of the three | CARRIED |
| D9 | docstring | "the two Like ids differ" | :154 | a re-like reusing the first Like's id | CARRIED |
| D10 | docstring | "the signal ends at (1, 1.0)" | :156 | the re-like collapsed as a duplicate (signal 0) | CARRIED |
| D11 | docstring | "Two anonymous likes both publish the Like id for actor `anonymous` at generation 0" | :162 | a per-request id, or a generation other than 0 | CARRIED |
| D12 | docstring | "the Engine counts the second as a duplicate" | :163 | distinct ids for the two anonymous likes | CARRIED |
| D13 | docstring | "the signal is (1, 1.0)" | :164 | the Engine counting two | CARRIED |
| D14 | docstring | id "over the uuid and host the Engine resolved them to, not over the spelling sent" | :174 (controls :172–173) | hashing the request's spelling | CARRIED |
| D15 | docstring | "undo_like of a video the profile never liked answers 200" | :180 | a 4xx/5xx on the no-op undo | CARRIED |
| D16 | docstring | "and publishes nothing" | :181 | publishing an UndoLike | CARRIED |
| D17 | docstring | "a like afterwards publishes at generation 1" | :184 | the refused undo moving the generation forward | CARRIED |
| D18 | docstring | "A dislike replacing a like publishes the UndoLike id an undo_like would have used (generation 1)" | :192 | a different id or generation on the dislike's withdrawal | CARRIED |
| D19 | docstring | "and leaves (0, 0.0)" | :193 | the withdrawal not reaching the signal | CARRIED |
| D20 | docstring | "a dislike … of a video the profile does not like publish[es] nothing" | :197 | publishing on that dislike | CARRIED |
| D21 | docstring | "and an undo_dislike … publish[es] nothing" | :197 | publishing on that undo_dislike | CARRIED |
| D22 | docstring | "like, reset, like publishes one Like" | :208 | the re-like or the reset publishing | CARRIED |
| D23 | docstring | "though the re-like is stored" | :207 | the re-like being refused rather than stored and left unpublished | CARRIED |
| D24 | docstring | "the undo_like after it publishes that Like's UndoLike" | :210, :212 | an UndoLike at generation 2, or none | CARRIED |
| D25 | docstring | "and leaves (0, 0.0)" | :211 | the UndoLike missing the first Like's generation | CARRIED |
| D26 | docstring | "undo_like of an imported like publishes nothing" | :222 | publishing on removal of an imported like | CARRIED |
| D27 | docstring | "though the import stored the like" | :219 | an import that stored nothing, which would make the undo a trivial no-op | CARRIED |
| D28 | docstring | "and the undo removed it" | :221 | the undo being refused instead of applied without publishing | CARRIED |
| D29 | docstring | "a like afterwards publishes at generation 1" | :225 | the import or the undo consuming a generation | CARRIED |
| N1a | name | "a repeated like publishes one like" | :140 | a Like per action | CARRIED |
| N1b | name | "a bridge retry of it is a duplicate" | :144 | nothing: the retry is simulated by re-sending the recorded payload, which is a duplicate whatever the id scheme | UNCARRIED |
| N2 | name | "like, undo_like, like publishes Like, UndoLike, Like under generations 1, 1, 2" | :155 | wrong sequence or generations | CARRIED |
| N3a | name | "two anonymous likes carry one id" | :162 | a per-request anonymous id | CARRIED |
| N3b | name | "the engine counts the second as a duplicate" | :163 | a second non-duplicate ingest | CARRIED |
| N4 | name | "a like named in a non-canonical spelling derives its id from the resolved identity" | :174 | hashing the spelling sent | CARRIED |
| N5a | name | "an undo_like of an unliked video answers 200" | :180 | an error status | CARRIED |
| N5b | name | "and publishes nothing" | :181 | publishing an UndoLike | CARRIED |
| N6a | name | "a dislike replacing a like publishes the undo_like's id" | :192 | a different id on the withdrawal | CARRIED |
| N6b | name | "one of an unliked video publishes nothing" | :197 | publishing on that dislike | CARRIED |
| N7a | name | "a like after a reset publishes nothing" | :208 | the re-like publishing | CARRIED |
| N7b | name | "the next undo_like withdraws the first" | :212 | an UndoLike at the re-like's generation | CARRIED |
| N8 | name | "an undo_like of an imported like publishes nothing" | :222 | publishing on removal of an imported like | CARRIED |

CRITICAL
none

RECOMMENDATIONS
1. whole-claim (rules/testing.md): tests/tmp/test_13_deterministic_event_ids_phase2.py:143–145
   `retry = ingest_interaction_event(rig.engine_db, rig.events[0][0])`
   D6, D7 and N1b are UNCARRIED. The test hands the Engine's ingest the same dict object the Client already sent. That dict collides with itself under any id scheme, including the `client-{uuid4}` ids that C2 replaces, so these lines exclude no wrong implementation. They are tagged `# C2`, but C2 is carried by the equality at :142, not by them. To carry the clause, drive a real re-publish of the same action through the Client and assert that the id matches. The other option is to narrow the name and the docstring to what :142 already proves.
2. normal-and-abnormal-paths (rules/testing.md): tests/tmp/test_13_deterministic_event_ids_phase2.py:79–84
   The stub's ingest always answers `{"ok": True}`, so every test takes the success path. No test covers a publish the bridge rejects: what the action answers, and whether the next attempt at the same like reuses the id and generation or moves on.

OBSERVATIONS
none

NOT ASSESSED
1. `code_under_test` lists tests/active/test_event_ids.py (NEW), but that file does not exist.
2. client/backend/lib/users_store.py was not read in full. The server handlers and the imported symbols it relies on were checked (`/api/user-action`, `/api/profile/reaction`, `/api/user-profile/reset`, `/api/profile/likes/import`, `ensure_user_schema`). The id's `generation` input has no definition anywhere under client/backend yet, so bounds on it were judged from the test alone.
3. `fixtures_path` was not supplied. The test imports its harness from tests/active/conftest.py (`ClientBackend`, `RateLimiter`, `client_server`, `ensure_user_schema`), and that file was read; the `rig` fixture is defined in the test file itself.

## 2026-09-27 - Step 7 - Phase 2 (Publish on change, derived ids) - self-check (audit round 2, send-back 0)

`tests/tmp/test_13_deterministic_event_ids_phase2.py`, surface `checkpoint`. Collection exit 0.

- C1 - tests/tmp/test_13_deterministic_event_ids_phase2.py:140 — after two keyed likes of one video the published types are exactly ["Like"]; :178 — undo_like of a never-liked video publishes nothing (armed by the :181 control, a like that does publish); :194 — after a dislike of an unliked video (stored, control :192) and an undo_dislike, still exactly 2 events have been published; :205 — like, reset, re-like (stored, control :204) has published exactly ["Like"]; :219 — undo_like of an imported like (stored :216, removed :218) publishes nothing, armed by the :222 control - expected: :140 ["Like"]; :178 []; :194 2; :205 ["Like"]; :219 [] - excludes: Today's `publish = action in ("like", "undo_like")` publishes on every like and every undo_like. Under it :140 and :205 read ["Like", "Like"], and :178 and :219 read one UndoLike (observed in this run). An implementation that decides whether to publish from the stored like rather than the published one passes :140 but still gives ["Like", "Like"] at :205. One that publishes on dislike or undo_dislike with no like to remove reads more than 2 at :194.
- C2 - tests/tmp/test_13_deterministic_event_ids_phase2.py:142 — the one Like's id is "client-" + sha256(json.dumps([profile_id, uuid, host, "Like", 1])); :152 — like, undo_like, like publish the derived ids at (Like,1), (UndoLike,1), (Like,2); :159 — two anonymous likes both carry the derived id for ["anonymous", uuid, host, "Like", 0]; :171 — a like spelled with an upper-case uuid and host "IDS.Example" carries the id over the resolved lower-case uuid and host (controls :169–170 confirm the resolved identity reached the payload) - expected: Each id equals `_event_id(actor, canonical video, event_type, generation)` with the actor, type and generation named above. For :159 that is two identical ids, which the Engine flags [False, True] at :160. - excludes: Today's `f"client-{uuid4()}"` fails :142, :152, :159 and :171, since each reads a random `client-` uuid (observed). An id that leaves out the event type makes Like and UndoLike at generation 1 collide at :152. One that leaves out the generation, or reuses generation 1 on a re-like, fails :152 (and :151). One that uses a per-request actor or a generation other than 0 for anonymous fails :159. Hashing the uuid and host as sent fails :171.

<exemptions>
none
</exemptions>

<items>
<item id="D6">
<disposition>justified</disposition>
<what>I narrowed the prose to match what the test asserts. The first docstring bullet now ends "...publish one Like, at generation 1, and the video's signal is (1, 1.0)." The clause "re-ingesting that Like's payload unchanged, as a bridge retry does, is a duplicate" is gone. I also deleted the old lines :143–144 (the `ingest_interaction_event` re-send of `rig.events[0][0]` and its `duplicate is True` assertion). Re-sending the recorded dict collides with itself under any id scheme, `client-{uuid4}` included, so those lines excluded nothing. What they claimed to guard is really carried at :142, which pins the published id to the derived `client-` + SHA-256 value; any re-derivation of the same like gets that same id.</what>
</item>
<item id="D7">
<disposition>justified</disposition>
<what>I removed "and leaves (1, 1.0)" from the docstring together with D6, and deleted the old :145 signal re-check that followed the self-colliding re-ingest. The (1, 1.0) the test actually proves is still asserted at :141, straight after the two likes, and the docstring still says so ("the video's signal is (1, 1.0)").</what>
</item>
<item id="N1b">
<disposition>justified</disposition>
<what>I renamed the test from `test_a_repeated_like_publishes_one_like_and_a_bridge_retry_of_it_is_a_duplicate` to `test_a_repeated_like_publishes_one_like_at_generation_1`. The name no longer claims a bridge-retry duplicate, which nothing in the test could tell apart from a random id. It now names what :140 (one Like) and :142 (its id at generation 1) assert.</what>
</item>
</items>

<findings_addressed>
Neither auditor raised a CRITICAL. I took claim-audit recommendation 1 (the :143–145 re-send excludes nothing) in its narrowing form: I deleted the three lines and narrowed the docstring and the test name to what :142 proves. The other form, driving a real Client re-publish, would have to assert retry behaviour that neither C1 nor C2 specifies. I left claim-audit recommendation 2 (the bridge-rejected publish path) alone. What the action answers, and which id and generation a retry uses after the bridge rejects a publish, are not in C1 or C2 or in this phase's Intent, so any expectation for them would be invented. It needs a requirement of its own first. The shape audit made no findings. After the edit I ran the file: all 8 tests still fail on their intended assertions and nowhere else (:140, :152, :159, :171, :178, :189, :205, :219).
</findings_addressed>

<rows>
<row clause="C1">
<assertion>tests/tmp/test_13_deterministic_event_ids_phase2.py:140 — after two keyed likes of one video the published types are exactly ["Like"]; :178 — undo_like of a never-liked video publishes nothing (armed by the :181 control, a like that does publish); :194 — after a dislike of an unliked video (stored, control :192) and an undo_dislike, still exactly 2 events have been published; :205 — like, reset, re-like (stored, control :204) has published exactly ["Like"]; :219 — undo_like of an imported like (stored :216, removed :218) publishes nothing, armed by the :222 control</assertion>
<expected>:140 ["Like"]; :178 []; :194 2; :205 ["Like"]; :219 []</expected>
<wrong_implementation>Today's `publish = action in ("like", "undo_like")` publishes on every like and every undo_like. Under it :140 and :205 read ["Like", "Like"], and :178 and :219 read one UndoLike (observed in this run). An implementation that decides whether to publish from the stored like rather than the published one passes :140 but still gives ["Like", "Like"] at :205. One that publishes on dislike or undo_dislike with no like to remove reads more than 2 at :194.</wrong_implementation>
</row>
<row clause="C2">
<assertion>tests/tmp/test_13_deterministic_event_ids_phase2.py:142 — the one Like's id is "client-" + sha256(json.dumps([profile_id, uuid, host, "Like", 1])); :152 — like, undo_like, like publish the derived ids at (Like,1), (UndoLike,1), (Like,2); :159 — two anonymous likes both carry the derived id for ["anonymous", uuid, host, "Like", 0]; :171 — a like spelled with an upper-case uuid and host "IDS.Example" carries the id over the resolved lower-case uuid and host (controls :169–170 confirm the resolved identity reached the payload)</assertion>
<expected>Each id equals `_event_id(actor, canonical video, event_type, generation)` with the actor, type and generation named above. For :159 that is two identical ids, which the Engine flags [False, True] at :160.</expected>
<wrong_implementation>Today's `f"client-{uuid4()}"` fails :142, :152, :159 and :171, since each reads a random `client-` uuid (observed). An id that leaves out the event type makes Like and UndoLike at generation 1 collide at :152. One that leaves out the generation, or reuses generation 1 on a re-like, fails :152 (and :151). One that uses a per-request actor or a generation other than 0 for anonymous fails :159. Hashing the uuid and host as sent fails :171.</wrong_implementation>
</row>
</rows>

<answers>
1. No. Every negative assertion has a positive control showing the path ran. :178 has the :181 like that does publish. :194 follows the stored dislike at :192 and the two events published at :188. :205 has the re-like stored at :204. :219 has the import stored at :216, the undo applied at :218, and the like at :222. If the handler were deleted, the controls and the positive id assertions would go red.
2. No. `_event_id` implements the requirement's formula independently. Production does not compute it yet, and deleting server.py:802's id line, or changing its form, is what turns :142, :152, :159 and :171 red. I removed the only echo there was: re-sending the recorded payload at the old :143–145, which compared an event_id to itself.
3. No. The id is read across actor (a profile id or anonymous), type (Like or UndoLike), generation (0, 1 or 2) and spelling (canonical or non-canonical), each against the independently derived value.
4. No. The only double is the Engine's HTTP surface across the bridge, a severed process boundary. Its ingest runs the real `ingest_interaction_event` on a real engine.db, and the Client backend is the real server.
5. Yes, it collects. `ingest_interaction_event` is still imported and used by the stub. The run collected 8 tests, which matches the 8 test functions in the file.
6. Yes. The rig's behaviour (statuses, event shapes, duplicate flags, signal rows, the import going through resolve) came from the earlier probe run. The derived ids are a prediction from the requirement's formula and cannot be observed until the phase is built. I said so in the previous round, and nothing I added this round rests on a new unobserved shape.
7. Yes. I ran the file after the edit: 8 failed, each on its intended assertion after its controls passed. :140 read ['Like','Like']. :152, :159, :171 and :189 read client-<uuid4> ids instead of the derived ones. :178 and :219 read one UndoLike instead of []. :205 read ['Like','Like'].
Housekeeping: the empty tests/tmp/probe_13_phase2.py from the previous round is still there, because I have no delete tool, and it needs removing.
</answers>

Gate: satisfied

## 2026-09-27 - Step 7 - Phase 2 (Publish on change, derived ids) - red (audit round 2)

`tests/tmp/test_13_deterministic_event_ids_phase2.py` exited 1.

```
  tests/tmp/test_13_deterministic_event_ids_phase2.py  8 failed                               0.0s
  ---------------------------------------------------
  total                                                8 failed                               5.2s wall, 1 lane

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

## 2026-09-27 - Step 7 - Phase 2 (Publish on change, derived ids) - audit (round 2)

- AUDIT: devsecops-test-shape-auditor - PASS
- AUDIT: devsecops-test-claim-auditor - PASS
- OUTSTANDING: nothing

### devsecops-test-shape-auditor

SHAPE AUDIT — VERDICT: PASS

CRITICAL
none

RECOMMENDATIONS
none

PREDICTED FAILURE
The first failure is at tests/tmp/test_13_deterministic_event_ids_phase2.py:140, where `[event_type for event_type, _ in _published(rig.events)] == ["Like"]` gets `["Like", "Like"]`, because server.py:784 still publishes on every `like`. Each later test should fail at its first id-equality assertion, lines 152, 159, 171, 189, 209 and 222, because server.py:802 still builds `event_id` as `f"client-{uuid4()}"`. Two tests fail earlier: the one at lines 174–181 fails at 178 on `rig.events == []`, because an `undo_like` of an unliked video still publishes an UndoLike, and the one at lines 212–222 fails the same way at 219.

NOT ASSESSED
1. `code_under_test` listed tests/active/test_event_ids.py (NEW), which does not resolve. The stub question was answered from the test's assertion form and from client/backend/server.py and client/backend/lib/users_store.py.
2. `fixtures_path` was not supplied. Instead I read the imported harness symbols (`ClientBackend`, `RateLimiter`, `client_server`, `ensure_user_schema`) from tests/active/conftest.py, which the test imports directly at line 34. I did not read how `ensure_user_schema` is built.
3. Anti-pattern pass: `_event_id` at line 45 computes the expected id in the test body. I did not class it as `tautological-assertion`. It encodes C2's formula as written, imports nothing from production, and takes the inputs that matter from independent literals: generation 0/1/2, actor pid vs `anonymous`, and the canonical rather than the as-sent spelling. A wrong actor, identity, generation or field order would show on one side only. Only a wrong formula would move both sides together, and that formula is the requirement itself.
4. Absence assertions at lines 178 and 219 each have a positive publish control later in the same test (lines 181 and 222). The one at line 194 comes after two positive publishes asserted at line 189. So none is `absence-only-assertion`.
5. Ladder pass: the test drives the real Client handler over HTTP and asserts on the payloads the Engine stub receives and on engine.db rows (rungs 1–3). No downshift is needed and none was made. The Engine stub's lower-casing at line 75 stands in for the Engine's canonicalisation, not for the code under test, so it gives no stub route.

### devsecops-test-claim-auditor

CLAIM AUDIT — VERDICT: PASS

CLAUSE MAP  (54 clauses: 12 must_prove, 29 docstring, 13 name)
| id | source | clause | assertion | excludes | status |
|---|---|---|---|---|---|
| C1a | must_prove | a repeat like of a video the profile already likes publishes nothing | :140 | publishing a Like on every `like` action | CARRIED |
| C1b | must_prove | undo_like of a video with no published like publishes nothing | :178 | publishing an UndoLike on every `undo_like` | CARRIED |
| C1c | must_prove | a dislike of a video the profile does not like publishes nothing | :194 | publishing on a dislike that removed no like | CARRIED |
| C1d | must_prove | undo_dislike of a video the profile does not like publishes nothing | :194 | publishing on undo_dislike (the count stays 2 after both actions) | CARRIED |
| C1e | must_prove | re-like after a reset, while the published like is still open, publishes nothing | :205 | deciding to publish from the stored like instead of the published one (:204 shows the re-like was stored) | CARRIED |
| C1f | must_prove | undo_like of an imported (never published) like publishes nothing | :219 | publishing an UndoLike because a stored like was removed | CARRIED |
| C2a | must_prove | id is `client-` + SHA-256 hex of the JSON list | :142 | a `client-{uuid4}` id or any other hash or encoding | CARRIED |
| C2b | must_prove | actor in the hashed list (profile id / `anonymous`) | :142, :159 | leaving out the actor, or using some other actor string | CARRIED |
| C2c | must_prove | canonical uuid in the hashed list | :171 | hashing the upper-case uuid as sent | CARRIED |
| C2d | must_prove | canonical host in the hashed list | :171 | hashing `IDS.Example` as sent | CARRIED |
| C2e | must_prove | event type in the hashed list | :152 | Like and UndoLike at generation 1 sharing one id | CARRIED |
| C2f | must_prove | like generation in the hashed list | :151, :152, :159 | a re-like after an undo reusing generation 1; anonymous not at 0 | CARRIED |
| D1 | docstring | "publishes a Like or UndoLike only when it opens or closes" the like | :140, :150, :178, :188, :194 | publishing on no-op actions, or not publishing on a real open or close | CARRIED |
| D2 | docstring | "every published event's id is `client-` plus the SHA-256 of…" | :142, :152, :159, :171 | any id other than the derived one | CARRIED |
| D3 | docstring | "Two likes … publish one Like" | :140 | a Like per action | CARRIED |
| D4 | docstring | "at generation 1" | :142 | generation 0 or 2 on the first like | CARRIED |
| D5 | docstring | "the video's signal is (1, 1.0)" | :141 | the Engine counting two likes | CARRIED |
| D6 | docstring | withdrawn | n/a | n/a | CARRIED |
| D7 | docstring | withdrawn | n/a | n/a | CARRIED |
| D8 | docstring | "publishes Like, UndoLike, Like at generations 1, 1 and 2" | :152 | wrong order, or wrong generation on any of the three | CARRIED |
| D9 | docstring | "the two Like ids differ" | :151 | a re-like reusing the first Like's id | CARRIED |
| D10 | docstring | "the signal ends at (1, 1.0)" | :153 | the re-like collapsed as a duplicate (signal 0) | CARRIED |
| D11 | docstring | "Two anonymous likes both publish the Like id for actor `anonymous` at generation 0" | :159 | a per-request id, or a generation other than 0 | CARRIED |
| D12 | docstring | "the Engine counts the second as a duplicate" | :160 | distinct ids for the two anonymous likes | CARRIED |
| D13 | docstring | "the signal is (1, 1.0)" | :161 | the Engine counting two | CARRIED |
| D14 | docstring | id "over the uuid and host the Engine resolved them to, not over the spelling sent" | :171 (controls :169–170) | hashing the request's spelling | CARRIED |
| D15 | docstring | "undo_like of a video the profile never liked answers 200" | :177 | a 4xx/5xx on the no-op undo | CARRIED |
| D16 | docstring | "and publishes nothing" | :178 | publishing an UndoLike | CARRIED |
| D17 | docstring | "a like afterwards publishes at generation 1" | :181 | the refused undo moving the generation forward | CARRIED |
| D18 | docstring | "A dislike replacing a like publishes the UndoLike id an undo_like would have used (generation 1)" | :189 | a different id or generation on the dislike's withdrawal | CARRIED |
| D19 | docstring | "and leaves (0, 0.0)" | :190 | the withdrawal not reaching the signal | CARRIED |
| D20 | docstring | "a dislike … of a video the profile does not like publish[es] nothing" | :194 | publishing on that dislike | CARRIED |
| D21 | docstring | "and an undo_dislike … publish[es] nothing" | :194 | publishing on that undo_dislike | CARRIED |
| D22 | docstring | "like, reset, like publishes one Like" | :205 | the re-like or the reset publishing | CARRIED |
| D23 | docstring | "though the re-like is stored" | :204 | the re-like being refused rather than stored and left unpublished | CARRIED |
| D24 | docstring | "the undo_like after it publishes that Like's UndoLike" | :207, :209 | an UndoLike at generation 2, or none | CARRIED |
| D25 | docstring | "and leaves (0, 0.0)" | :208 | the UndoLike missing the first Like's generation | CARRIED |
| D26 | docstring | "undo_like of an imported like publishes nothing" | :219 | publishing on removal of an imported like | CARRIED |
| D27 | docstring | "though the import stored the like" | :216 | an import that stored nothing, which would make the undo a trivial no-op | CARRIED |
| D28 | docstring | "and the undo removed it" | :218 | the undo being refused instead of applied without publishing | CARRIED |
| D29 | docstring | "a like afterwards publishes at generation 1" | :222 | the import or the undo consuming a generation | CARRIED |
| N1a | name | "a repeated like publishes one like" | :140 | a Like per action | CARRIED |
| N1b | name | withdrawn | n/a | n/a | CARRIED |
| N2 | name | "like, undo_like, like publishes Like, UndoLike, Like under generations 1, 1, 2" | :152 | wrong sequence or generations | CARRIED |
| N3a | name | "two anonymous likes carry one id" | :159 | a per-request anonymous id | CARRIED |
| N3b | name | "the engine counts the second as a duplicate" | :160 | a second ingest that is not a duplicate | CARRIED |
| N4 | name | "a like named in a non-canonical spelling derives its id from the resolved identity" | :171 | hashing the spelling sent | CARRIED |
| N5a | name | "an undo_like of an unliked video answers 200" | :177 | an error status | CARRIED |
| N5b | name | "and publishes nothing" | :178 | publishing an UndoLike | CARRIED |
| N6a | name | "a dislike replacing a like publishes the undo_like's id" | :189 | a different id on the withdrawal | CARRIED |
| N6b | name | "one of an unliked video publishes nothing" | :194 | publishing on that dislike | CARRIED |
| N7a | name | "a like after a reset publishes nothing" | :205 | the re-like publishing | CARRIED |
| N7b | name | "the next undo_like withdraws the first" | :209 | an UndoLike at the re-like's generation | CARRIED |
| N8 | name | "an undo_like of an imported like publishes nothing" | :219 | publishing on removal of an imported like | CARRIED |

CRITICAL
none

RECOMMENDATIONS
none

OBSERVATIONS
1. whole-claim (rules/testing.md): tests/tmp/test_13_deterministic_event_ids_phase2.py:3
   D6 and D7 were closed by narrowing the prose, not by adding an assertion. The docstring bullet now ends at "and the video's signal is (1, 1.0)". The sentence "re-ingesting that Like's payload unchanged, as a bridge retry does, is a duplicate and leaves (1, 1.0)" was removed, and nothing in the test asserts retry-duplicate behaviour.
2. whole-claim (rules/testing.md): tests/tmp/test_13_deterministic_event_ids_phase2.py:136
   N1b was also closed by narrowing, this time the test name. `..._and_a_bridge_retry_of_it_is_a_duplicate` became `test_a_repeated_like_publishes_one_like_at_generation_1`. The name's new clause, "at generation 1", has no ledger row. It is carried by :142, which excludes a generation-0 or generation-2 first like, so no defect comes of it.

NOT ASSESSED
1. `code_under_test` lists tests/active/test_event_ids.py (NEW). That path does not resolve, so it was not read.
2. `fixtures_path` was not supplied. The fixture `rig` is defined in the test file. The harness imports (`ClientBackend`, `RateLimiter`, `client_server`, `ensure_user_schema`) were resolved to tests/active/conftest.py and read there. The Engine's `ensure_interaction_event_schema` / `ingest_interaction_event` (engine/server/api/data/interaction_events.py) is outside `code_under_test` and was not read. The duplicate outcomes at :160 were therefore judged from the test's own use of `result["duplicate"]`.

## 2026-09-27 - Step 7 - Phase 2 (Publish on change, derived ids) - checkpoint outcome (run 1)

`tests/tmp/test_13_deterministic_event_ids_phase2.py` exited 0 after the phase landed.

<changes>
### `client/backend/lib/users_store.py`
- `ensure_user_schema` now also creates `like_generations(user_id, video_id, instance_domain, generation INTEGER NOT NULL, published INTEGER NOT NULL DEFAULT 0)`, keyed on `(user_id, video_id, instance_domain)`, with `CREATE TABLE IF NOT EXISTS`. It sits before the `local-user` cleanup, and the docstring names the new table.
- `record_like` takes a new keyword `publish: bool = False` and returns `(opened, generation)`.
  - The `likes` INSERT is now `ON CONFLICT DO NOTHING`, and its own rowcount decides whether the like is new. An existing row gets a plain UPDATE of `video_uuid`/`updated_at`, so recency and the trim work as before.
  - A new like with `publish=True` runs a conditional upsert on `like_generations`. It inserts `(g=1, published=1)`, or sets `g+1, published=1` only when `published = 0`. The rowcount is `opened`.
  - A re-like after a reset or trim, while the like is still published, therefore opens nothing. An imported like (`publish` left False) never touches `like_generations`.
  - The trim and the commit are unchanged. The import caller ignores the return value.
- New `like_generation(conn, user_id, video_id, instance_domain) -> int` returns the stored generation, or 0 when there is no row. It uses `row[0]`, so it works with or without a `row_factory`.
- New `close_like(conn, user_id, video_id, instance_domain) -> tuple[bool, int]` runs `UPDATE ... SET published = 0 ... AND published = 1`. It returns whether a published like was closed, plus that like's generation. It does not commit: it runs inside the caller's transaction, like `remove_like`.

### `client/backend/server.py`
- Added `import hashlib`. `close_like` joins the `lib.users_store` import. `uuid4` stays because `run_id` still uses it.
- `_store_reaction` now returns `(publish, generation)`:
  - plain like, and like replacing a dislike: `record_like(..., publish=True)`;
  - undo_like: `remove_like` then `close_like`, in the same `with conn`;
  - dislike: `remove_like`, `close_like` and `write_dislike` in the existing write transaction, still after the limit check and the centroids request;
  - undo_dislike: `(False, 0)`.
  - The `:returns:` docstring is rewritten.
- `_handle_user_action`:
  - Anonymous requests keep `publish = action in ("like", "undo_like")` at generation 0. A profile's request publishes only what `_store_reaction` reports. A no-change request falls through to the existing 200 `{ok, updatedAt}`.
  - `actor = profile_id or "anonymous"` is computed once and used for both the id and `actor_id`.
  - `event_id` is `"client-" + sha256(json.dumps([actor, canonical_uuid, canonical_host, event_type, generation]))`. It hashes the Engine-resolved uuid and host, not the spelling sent.
  - The docstring now states the publish rule. Other payload fields and the error paths are unchanged.

### `tests/active/test_event_ids.py`
Not created. The gating checkpoint `tests/tmp/test_13_deterministic_event_ids_phase2.py` covers T1–T8. I left moving it into `tests/active` to the workflow rather than make a copy.
</changes>

<inner_tests>
none
</inner_tests>

<unanticipated>
tests/tmp/probe_like_generations.py: a throwaway probe I wrote to check SQLite's behaviour. When the `DO UPDATE ... WHERE` condition is false, the upsert reports rowcount 0. The probe ran the new users_store functions through open, repeat, close, re-open, reset and import. It passed, and every step returned the `(opened/closed, generation)` it should. I have no delete tool, so it is still there; please delete it. Running it also rewrote `tests/last_test_validation.json` and `tests/last_test_output.txt` with that one probe's result.
</unanticipated>

<awaiting_operator>
none
</awaiting_operator>

```
  tests/tmp/test_13_deterministic_event_ids_phase2.py  8 passed                               0.0s
  ---------------------------------------------------
  total                                                8 passed                               4.8s wall, 1 lane

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

## 2026-09-27 - Step 7 - Phase 3 (Delete removes generations) - must_prove

Quoted from the phase Intent, written at Step 6 before the checkpoint was drafted.

Intent:
`delete_profile` in client/backend/lib/profiles.py removes the deleted profile's `like_generations` rows inside its existing transaction.

- C1 - After one profile is deleted, it has no `like_generations` rows and another profile keeps its rows.

must_prove:
- C1 - After one profile is deleted, it has no `like_generations` rows and another profile keeps its rows.

## 2026-09-27 - Step 7 - Phase 3 (Delete removes generations) - self-check (audit round 1, send-back 0)

`tests/tmp/test_13_deterministic_event_ids_phase3.py`, surface `checkpoint`. Collection exit 0.

- C1 - tests/tmp/test_13_deterministic_event_ids_phase3.py:75 — after the keyed POST /api/profile/delete for `gone_id` returns 204, `_rows_for(gone_id)` == {"profiles": 0, "users": 0, "likes": 0, "like_generations": 0}. Line 76 checks the other profile: `_rows_for(kept_id)` == {"profiles": 1, "users": 1, "likes": 1, "like_generations": 1}. - expected: Line 75: all four counts are 0 for the deleted profile. Before the delete that profile had 2 `like_generations` rows, one open (published=1) and one closed (the undone like, published=0), and the control on line 65 showed that. Line 76: the other profile still has 1/1/1/1, the same as before the delete (line 66). - excludes: (a) The current code leaves `like_generations` untouched. Line 75 then reads {"profiles": 0, "users": 0, "likes": 0, "like_generations": 2}, which is what this run showed. (b) A delete that finds generations through the likes rows it removes (e.g. `DELETE FROM like_generations WHERE (user_id, video_id, instance_domain) IN (SELECT ... FROM likes WHERE user_id = ?)`) misses the closed 'v-undone' generation, whose likes row is already gone. Line 75 then reads like_generations: 1. (c) A delete with no user filter (`DELETE FROM like_generations`) passes line 75, but line 76 then reads like_generations: 0 for the other profile.

<assertions>
tests/tmp/test_13_deterministic_event_ids_phase3.py:65 — control: before the delete, the profile to be deleted holds {"profiles": 1, "users": 1, "likes": 1, "like_generations": 2}. That is one open generation row and one closed one (published=0) left by a like that was undone, so a count of 0 later cannot come from rows that were never seeded — control
tests/tmp/test_13_deterministic_event_ids_phase3.py:66 — control: before the delete, the other profile holds {"profiles": 1, "users": 1, "likes": 1, "like_generations": 1} — control
tests/tmp/test_13_deterministic_event_ids_phase3.py:69 — a delete with no key is refused with 401 — control
tests/tmp/test_13_deterministic_event_ids_phase3.py:70 — after the refused delete, the profile still has 2 like_generations rows, so a delete that goes through without a valid key is caught — C1
tests/tmp/test_13_deterministic_event_ids_phase3.py:73 — a delete with the key answers 204 — control
tests/tmp/test_13_deterministic_event_ids_phase3.py:75 — after the delete, the deleted profile has {"profiles": 0, "users": 0, "likes": 0, "like_generations": 0}. Under the current delete_profile it still has like_generations 2 (observed). A delete that removed only published=1 rows, or only generations matching the likes rows it deletes, would leave 1 — C1
tests/tmp/test_13_deterministic_event_ids_phase3.py:76 — after the delete, the other profile keeps {"profiles": 1, "users": 1, "likes": 1, "like_generations": 1}, so an unscoped DELETE FROM like_generations is caught — C1
</assertions>

<probes>
Wrote tests/tmp/probe_13_phase3.py and ran it with ValidateTests ["tests/tmp/probe_13_phase3.py", "-s"] against the current, unimplemented code. The probe mints two profiles over HTTP on client_backend and seeds each with record_like(..., publish=True). It then seeds the first profile with a second like and undoes it through remove_like and close_like, and prints the counts before and after the deletes. Output: seed (True, 1) twice; undone seed (True, 1); close (True, 1). Before: gone {'profiles': 1, 'users': 1, 'likes': 1, 'like_generations': 2} with generation rows [(v-…, 1, published 1), ('v-undone', 1, published 0)]; kept {'profiles': 1, 'users': 1, 'likes': 1, 'like_generations': 1}. Unkeyed delete gave (401, {'error': 'Profile key required'}); keyed delete gave (204, None). After: gone {'profiles': 0, 'users': 0, 'likes': 0, 'like_generations': 2}; kept unchanged. The value under the wrong (current) implementation is therefore like_generations 2, and the checkpoint's line 75 fails on exactly that key. I have no delete tool, so tests/tmp/probe_13_phase3.py is still on disk and needs removing. It ends in `assert False`, but its probe_ prefix keeps pytest from collecting it by default.
</probes>

<unassertable>
none
</unassertable>

### `tests/tmp/test_13_deterministic_event_ids_phase3.py` - 3658 characters, inlined in full

```
"""Deleting a profile removes its `like_generations` rows, the open one and the closed one alike, and keeps another profile's.

A real Client backend (conftest's `client_backend`) serves POST /api/profile/delete; row counts are read straight from its users.db.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ACTIVE_DIR = ROOT / "tests" / "active"
if str(ACTIVE_DIR) not in sys.path:
    sys.path.insert(0, str(ACTIVE_DIR))
from conftest import client_backend  # noqa: E402,F401
from lib.users_store import close_like, record_like, remove_like  # noqa: E402

HOST = "h.example"


def _mint(client) -> tuple[str, str]:
    status, body = client.request("POST", "/api/profile")
    assert status == 201, body
    return body["profile_id"], body["key"]


def _seed_like(db_path, profile_id: str, video_id: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    record_like(conn, profile_id, "like", {"video_id": video_id, "instance_domain": HOST, "video_uuid": f"u-{video_id}"}, 100, publish=True)
    conn.close()


def _seed_undone_like(db_path, profile_id: str, video_id: str) -> None:
    """A published like, then undone: its likes row goes, its closed generation row stays."""
    _seed_like(db_path, profile_id, video_id)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    with conn:
        remove_like(conn, profile_id, video_id, HOST)
        close_like(conn, profile_id, video_id, HOST)
    conn.close()


def _rows_for(db_path, profile_id: str) -> dict[str, int]:
    conn = sqlite3.connect(db_path)
    counts = {
        "profiles": conn.execute("SELECT COUNT(*) FROM profiles WHERE profile_id = ?", (profile_id,)).fetchone()[0],
        "users": conn.execute("SELECT COUNT(*) FROM users WHERE user_id = ?", (profile_id,)).fetchone()[0],
        "likes": conn.execute("SELECT COUNT(*) FROM likes WHERE user_id = ?", (profile_id,)).fetchone()[0],
        "like_generations": conn.execute("SELECT COUNT(*) FROM like_generations WHERE user_id = ?", (profile_id,)).fetchone()[0],
    }
    conn.close()
    return counts


def test_deleting_a_profile_removes_its_open_and_closed_like_generations_and_keeps_anothers(client_backend):
    gone_id, gone_key = _mint(client_backend)
    kept_id, _kept_key = _mint(client_backend)
    for profile_id in (gone_id, kept_id):
        _seed_like(client_backend.db_path, profile_id, f"v-{profile_id}")
    # A closed generation outlives its likes row, so a delete keyed on the likes it removes would leave it.
    _seed_undone_like(client_backend.db_path, gone_id, "v-undone")
    # Control: seeding left one open and one closed generation row for the profile to be deleted, one open for the other.
    assert _rows_for(client_backend.db_path, gone_id) == {"profiles": 1, "users": 1, "likes": 1, "like_generations": 2}
    assert _rows_for(client_backend.db_path, kept_id) == {"profiles": 1, "users": 1, "likes": 1, "like_generations": 1}

    # A delete without the key is refused and removes nothing.
    assert client_backend.request("POST", "/api/profile/delete", body={})[0] == 401
    assert _rows_for(client_backend.db_path, gone_id)["like_generations"] == 2  # C1

    status, _ = client_backend.request("POST", "/api/profile/delete", headers={"X-Profile-Key": gone_key}, body={})
    assert status == 204

    assert _rows_for(client_backend.db_path, gone_id) == {"profiles": 0, "users": 0, "likes": 0, "like_generations": 0}  # C1
    assert _rows_for(client_backend.db_path, kept_id) == {"profiles": 1, "users": 1, "likes": 1, "like_generations": 1}  # C1

```


Gate: satisfied

## 2026-09-27 - Step 7 - Phase 3 (Delete removes generations) - red (audit round 1)

`tests/tmp/test_13_deterministic_event_ids_phase3.py` exited 1.

```
  tests/tmp/test_13_deterministic_event_ids_phase3.py  1 failed                               0.0s
  ---------------------------------------------------
  total                                                1 failed                               0.7s wall, 1 lane

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

## 2026-09-27 - Step 7 - Phase 3 (Delete removes generations) - audit (round 1)

- AUDIT: devsecops-test-shape-auditor - PASS
- AUDIT: devsecops-test-claim-auditor - PASS
- OUTSTANDING: nothing

### devsecops-test-shape-auditor

```
SHAPE AUDIT — VERDICT: PASS

CRITICAL
none

RECOMMENDATIONS
none

PREDICTED FAILURE
Fails at tests/tmp/test_13_deterministic_event_ids_phase3.py:75, on the dict equality for the deleted
profile. The actual value is {"profiles": 0, "users": 0, "likes": 0, "like_generations": 2}, because
delete_profile in client/backend/lib/profiles.py:69-80 as read deletes from blocks, dislikes,
dislike_profiles, likes, users and profiles, and never from like_generations.

NOT ASSESSED
1. `fixtures_path` was "none found". The `client_backend` fixture the test imports at line 15 was
   found by Grep and read at tests/active/conftest.py:46-89. The `connect_db`, `ClientBackendServer`
   and `/api/profile/delete` routing in client/backend/server.py were not in `code_under_test` and
   were not read. The stub question was answered on the assumption that the route calls
   delete_profile.
2. tests/active/test_profiles.py is listed in `code_under_test`. It is a sibling test file, not code
   this test runs. Only its test index was read, and nothing in it bears on this test's shape.
```

### devsecops-test-claim-auditor

CLAIM AUDIT — VERDICT: PASS

CLAUSE MAP  (10 clauses: 2 must_prove, 5 docstring, 3 name)
| id | source | clause | assertion | excludes | status |
|---|---|---|---|---|---|
| C1a | must_prove | "after one profile is deleted, it has no `like_generations` rows" | :75 | a delete that leaves `like_generations` untouched. The :65 control shows 2 rows were there before, so a count of 0 cannot pass by default | CARRIED |
| C1b | must_prove | "another profile keeps its rows" | :76 | a delete not scoped by profile, e.g. an unqualified `DELETE FROM like_generations`, or one keyed on the wrong column | CARRIED |
| D1 | docstring | "Deleting a profile removes its `like_generations` rows" | :75 | leaving the deleted profile's generation rows behind | CARRIED |
| D2 | docstring | "the open one ... alike" | :65, :75 | a delete that skips rows with `published = 1`. The control shows the open row existed, and :75 needs it gone | CARRIED |
| D3 | docstring | "and the closed one alike" | :65, :75 | a delete keyed on the profile's remaining `likes` rows. The closed row from `_seed_undone_like` (:63) has no `likes` row, so a delete keyed that way would leave it and :75 would see 1 | CARRIED |
| D4 | docstring | "and keeps another profile's" | :76 | a delete that removes every profile's generations | CARRIED |
| D5 | docstring | "A real Client backend ... serves POST /api/profile/delete" | :72-73 | an endpoint that is missing or refuses the keyed request. The status must be 204, sent to the real `client_backend` server | CARRIED |
| N1 | name | "removes its open ... like_generations" | :75 | the same wrong implementation as D2 | CARRIED |
| N2 | name | "removes its ... closed like_generations" | :75 | the same wrong implementation as D3 | CARRIED |
| N3 | name | "keeps anothers" | :76 | the same wrong implementation as C1b | CARRIED |

CRITICAL
none

RECOMMENDATIONS
1. bounds (rules/testing.md) — tests/tmp/test_13_deterministic_event_ids_phase3.py:57
   Only the populated case is tested: the profile being deleted always has 2 generation rows (:65). No test deletes a profile that has no `like_generations` rows, which is the "empty" edge the bounds principle names. The kept profile also holds only an open row, so there is no check that a closed row belonging to another profile survives the delete.

OBSERVATIONS
none

NOT ASSESSED
1. `fixtures_path` was not supplied. I found `client_backend` in tests/active/conftest.py:69-89 and read it: it creates a fresh `tmp_path` database and server for each test, so I could judge independence. I did not open `client_server.ClientBackendServer` or the handler at client/backend/server.py:341-344 past the lines that route `/api/profile/delete` to `delete_profile`.
2. `code_under_test` lists tests/active/test_profiles.py (EDITED). It contains nothing matching `like_generations` or a delete test. I did not read it in full because it is not the test under audit and this test does not depend on it.

## 2026-09-27 - Step 7 - Phase 3 (Delete removes generations) - checkpoint outcome (run 1)

`tests/tmp/test_13_deterministic_event_ids_phase3.py` exited 0 after the phase landed.

<changes>
### client/backend/lib/profiles.py
`delete_profile` now also runs `DELETE FROM like_generations WHERE user_id = ?` inside its existing `with conn:` transaction, right after the `likes` delete. It deletes by `user_id`, not by the likes it just removed, so closed generations (rows left behind after an undone like) go too. The table has no foreign keys, so the order of the deletes doesn't matter.

### tests/active/test_profiles.py
Not changed. The phase lists it as EDITED, but it is a durable test that has already gated, so this step can't touch it. Its `test_deleting_a_profile_removes_its_rows_and_keeps_anothers` still holds, because it only counts `profiles`, `users` and `likes`. Moving the checkpoint's `like_generations` assertions into this file is left to the promotion step.
</changes>

<inner_tests>
none
</inner_tests>

<unanticipated>
none
</unanticipated>

<awaiting_operator>
none
</awaiting_operator>

```
  tests/tmp/test_13_deterministic_event_ids_phase3.py  1 passed                               0.0s
  ---------------------------------------------------
  total                                                1 passed                               0.7s wall, 1 lane

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

## 2026-09-27 - Step 8 - clause accounting

- P1C1 - carried - rests on: the last audit of `tests/tmp/test_13_deterministic_event_ids_phase1.py`
- P2C1 - carried - rests on: the last audit of `tests/tmp/test_13_deterministic_event_ids_phase2.py`
- P2C2 - carried - rests on: the last audit of `tests/tmp/test_13_deterministic_event_ids_phase2.py`
- P3C1 - carried - rests on: the last audit of `tests/tmp/test_13_deterministic_event_ids_phase3.py`

## 2026-09-27 - Step 8 - refactor pass

<refactors>
none. The disk copies of users_store.py, server.py, profiles.py and random_videos.py match what was inlined, and none of the new code this build added needed restructuring.
</refactors>

<left_out>
engine/server/data/random_videos.py: the three fetch_* functions repeat the same SELECT column list and the same row-to-dict loop. That repetition was there before this build. Phase 1 only changed the popular ORDER BY term and the params list, so pulling out a shared helper would change code this build never touched. It would also change fetch_recent_videos, which no checkpoint here covers.
engine/server/data/random_videos.py: fetch_popular_videos builds params with its own two literal lists, one with the error threshold and one without. I kept that because the sibling functions build theirs the same way, and the two lists put each ? in SQL order where it is easy to see.
client/backend/lib/users_store.py: record_like calls like_generation separately rather than reading the generation back from the upsert with RETURNING. It costs one extra SELECT, but like_generation is also what close_like uses, and RETURNING would depend on the SQLite version in a way I haven't checked here.
client/backend/lib/users_store.py: get_or_create_user commits inside record_like, even though _store_reaction and _handle_likes_import call it within `with conn:`. That was true before this build. The likes and like_generations writes both come after that commit, so they still land together. Changing where commits happen would be a behaviour change, not a refactor.
client/backend/server.py: I left _store_reaction's three branches as they are. They return (publish, generation) in the same shape, and folding them together would mix the dislike path, which asks for centroids first, with the like paths, which don't.
The throwaway probes in tests/tmp (probe_cap.py, probe_13_phase2.py, probe_13_phase3.py, probe_like_generations.py) should be deleted. I have no delete tool, so they are still there. The step's "What the pass is measured against" section showed a blank placeholder ({rat_tail_rules}) instead of rules, so I checked the pass against the role's rat-tail and smallest-change rules.
</left_out>

<needs_fresh_red>
none
</needs_fresh_red>

<observation>
None of the build's new code (the popular signal cap, the like_generations tracking in record_like and close_like, the derived event ids in _handle_user_action, and the like_generations delete in delete_profile) needed restructuring. The only repetition in these files was there before the build, so the pass left all production code as it was and ran no tests.
</observation>

## 2026-09-27 - Step 8 - suite comparison (attempt 1)

`--compare` exited 0.

```
selected 9 of 16 test groups (7 unchanged):
  test_blocks.py — changed
  test_dislikes.py — changed
  test_frontend_blocks.py — changed
  test_frontend_profile.py — changed
  test_frontend_reactions.py — changed
  test_frontend_videos.py — changed
  test_profiles.py — changed
  test_random_videos.py — changed
  test_server.py — changed
  test_blocks.py              7 passed                              25.6s
  test_dislikes.py            10 passed                             37.7s
  test_frontend_blocks.py     2 passed                              33.3s
  test_frontend_profile.py    2 passed                               1.3s
  test_frontend_reactions.py  7 passed                              55.5s
  test_frontend_videos.py     1 passed                               9.9s
  test_profiles.py            11 passed                             29.8s
  test_random_videos.py       2 passed                               0.0s
  test_server.py              33 passed                             23.9s
  --------------------------
  total                       75 passed                             55.7s wall, 9 lanes

nothing moved against the previous record

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

## 2026-09-27 - Step 9 - document triage

- [ ] `client/README.md` - Line 19 (`POST /api/user-action`): "A like publishes its event and is kept server-side only when a profile key is sent" now reads as if every like publishes, which is wrong. Reword it to say that with a key, a `like` publishes a `Like` only when it opens the profile's published like of the video, and an `undo_like`, or a dislike replacing a like, publishes an `UndoLike` only when it closes one. A request that changes nothing answers 200 `{ok, updatedAt}` and publishes nothing. Without a key, every `like` and `undo_like` publishes under one fixed id per video and event type, so repeats are duplicates at the Engine. Event ids are `client-` plus the SHA-256 of actor, Engine-resolved video uuid and host, event type, and like generation (0 for anonymous). Line 15 (likes import): add that imported likes never open a published like, so un-liking one publishes nothing. Line 13 (`POST /api/profile/delete`): add like generations to the list of what is removed.
- [ ] `DEPLOYMENT.md` - Lines 259-261 say only that `/api/user-action` emits the interaction events. Add that a profile's `Like`/`UndoLike` is published only when it opens or closes the profile's published like (tracked in `users.db` `like_generations`, created at startup with no migration step). Also add that event ids are derived, so replays collapse at the Engine's ingest, and that keyless likes carry one fixed id per video and event type. Line 267 ("disliking a liked video publishes the `UndoLike` that withdraws the like") stays true. Near lines 71-72 (the `interaction_signals` ranking signal), add that the popular ordering adds at most 25.0 of a video's signal (`POPULAR_SIGNAL_CAP` in `engine/server/data/random_videos.py`), while the stored score stays uncapped.
- [ ] `engine/server/api/recommendations/docs/OVERVIEW.md` - Line 99, "popular pool: top by likes/views", no longer describes `fetch_popular_videos`. State that the pool is ordered by `popularity` plus the interaction signal capped at `POPULAR_SIGNAL_CAP` (25.0), then by likes, views, recency and video id. The rest of the line ("if likes exist, re-ranked by similarity; then caps") is unchanged. Line 109 (the scoring `popularity` feature) is a different thing and stays.
- [ ] `engine/server/api/recommendations/docs/PIPELINE_DIAGRAM.md` - Line 29, `G3[popular<br/>top likes/views]`, misstates the pool order. Change the label to `popularity + capped signal`. The change is cosmetic, but the label is wrong as it stands.
- [ ] `engine/server/api/recommendations/docs/LAYER_PARAMS.md` - Not on the checklist. Line 137, "**Source:** top videos by likes/views.", has the same false claim as OVERVIEW line 99. Make it: top videos by `popularity` plus the interaction signal capped at `POPULAR_SIGNAL_CAP` (25.0), then likes and views. Line 148 describes scoring after the pool and stays.
- [ ] `CONTEXT.md` - **Interaction event** (line 6) and **Interaction signal** (line 7) still match the build and need no change. Add a term, because the build's "real state change" is defined by it and not by the profile's likes list: **Published like** — a profile's like of one video that has reached the Engine. The Client tracks it with a like generation in `like_generations`. Opening a new one advances the generation, and closing it (un-like, or a dislike replacing the like) keeps the generation. It is unaffected by a reset, the `max_likes` trim or the likes import, and it is removed with the profile. A `Like` is published only when one opens and an `UndoLike` only when one closes.
- [ ] `docs/project/adr/0001-derived-interaction-event-ids.md` - The decision stands. Add to Consequences the like-instance scheme that landed: the Client's `like_generations` row per (profile, video) with a `published` flag. A like publishes, and advances the generation, only when it opens a published like. An un-like or replacing dislike publishes only when it closes one, at the same generation. Rows survive un-like, reset and trim and are deleted with the profile. As a result, imported likes never publish or open a like, so un-liking them publishes nothing; the reset (+1) and import→undo (−1) loops do not exist; and a like dropped by the `max_likes` trim can still be withdrawn. Likes that predate the table un-like as nothing (no published row), so they publish no `UndoLike`. See also adr_conflicts on decision 1's wording.
- [ ] `docs/project/issues/01-deterministic-event-ids.md` - At harvest on main: tick acceptance criteria lines 55-62, set `Status:` to `bug, complete`, and move the file to `docs/project/issues/archive/` per `docs/project/triage-labels.md`.
- [ ] `docs/project/plans/13-deterministic-event-ids.md` - At harvest: mark it delivered, point it to `16-13-deterministic-event-ids.md`, and archive it. Line 97's open question is answered: `delete_profile` exists and removes `like_generations`. Line 96 ("Trimmed likes ... the plan does not close it") is superseded by the `published` flag, since a trimmed like still closes on un-like. Also record that `clear_likes` (reset) keeps generations and their published state by design. Line 98 holds: import publishes nothing, and it never touches `like_generations`.
- [ ] `docs/project/roadmap.md` - At harvest, add a Delivered line for security issue `01`, deterministic event ids and the popular signal cap, pointing at the archived plan. Drop `01` from "Open security issues: `01` to `05` and `07`" (line 26) and from implementation-order step 1 (line 138). Of the checklist's optional follow-ups, the reset/import loops and the trim gap are closed by the delivered `published` flag and must not be added. Only two remain, as optional lines: decide whether the likes import should publish, and bound the popular likes tiebreaker (`v.likes + sig.likes_count`), which the cap does not cover.

Out of scope:
- [ ] `docs/project/adr/0005-raw-event-retention-keeps-ids.md` - Its claims (strip, don't delete; kept ids catch replays including the fixed anonymous `Like` id) are exactly what the build relies on, and nothing in it is made false.
- [ ] `README.md` - Lines 37-40 say only that interaction events update `interaction_signals`, which ranking uses. That is still true, and the file makes no claim about event ids or the popular ordering.

ADR conflicts: ADR-0001 decision 1 reads: "A `like` on a video the profile already likes, or an `undo_like` on one it does not, publishes nothing." The delivered gating does not key on the profile's `likes` list. It keys on the published-like state in `like_generations` (`published` flag). So after a reset or a `max_likes` trim, an `undo_like` on a video the profile no longer "likes" still publishes an `UndoLike`, because it closes a published like. And a re-like of that video, which is new in `likes`, publishes nothing, because the like is still published. An un-like of an imported like publishes nothing even though the profile "likes" it. This fits the decision's intent ("only on a real state change", and it closes the reset/import loops the requirements had accepted), but it departs from the ADR's literal wording. Amending decision 1 to say "published like" is the operator's call. The build also departs from the requirements text, though not from any ADR: the generation advances only when a published like opens, not on every new `likes` row, and imported likes do not advance it.

## 2026-09-27 - Step 9 - Update documentation

- [x] `client/README.md` - updated: `client/README.md`: `POST /api/user-action` now says when each action publishes and how event ids are built. The likes import and profile delete entries now cover like generations.
- [x] `DEPLOYMENT.md` - updated: DEPLOYMENT.md: added the 25.0 popular signal cap (section 1) and the publish-on-change rule, the `like_generations` table and derived event ids (section 5).
- [x] `engine/server/api/recommendations/docs/OVERVIEW.md` - updated: OVERVIEW.md: the popular pool's order now reads `popularity` plus the interaction signal capped at `POPULAR_SIGNAL_CAP` (25.0), not "top by likes/views".
- [x] `engine/server/api/recommendations/docs/PIPELINE_DIAGRAM.md` - updated: Changed the popular-layer node label (line 29) from `top likes/views` to `popularity + capped signal`.
- [x] `engine/server/api/recommendations/docs/LAYER_PARAMS.md` - updated: Fixed the popular layer's **Source:** line (line 137). It now describes the actual pool order: `popularity` plus the capped interaction signal, then likes, then views.
- [x] `CONTEXT.md` - updated: Added the glossary term **Published like** to `CONTEXT.md`, which defines what counts as a real like/un-like change.
- [x] `docs/project/adr/0001-derived-interaction-event-ids.md` - updated: Added the like-generation scheme to ADR-0001's Consequences and said what "real state change" in decision 1 means. The decisions themselves are unchanged.
- [x] `docs/project/issues/01-deterministic-event-ids.md` - updated: Issue 01 is marked `bug, complete` with all 8 acceptance criteria ticked, and a copy is in `docs/project/issues/archive/`. The original file still needs deleting, because I can't delete files.
- [x] `docs/project/plans/13-deterministic-event-ids.md` - updated: Plan 13 is now marked delivered and points to `16-13-deterministic-event-ids.md`. Its risks describe the code as built, and a new Delivery section records what the build settled. The file has not been moved to `archive/` yet.
- [x] `docs/project/roadmap.md` - updated: Roadmap: security issue `01` is now listed as Delivered, removed from the open issues and the implementation order, and has its two remaining follow-ups added as optional M1 lines.
- [x] `docs/project/adr/0005-raw-event-retention-keeps-ids.md` - out of scope: Its claims (strip, don't delete; kept ids catch replays including the fixed anonymous `Like` id) are exactly what the build relies on, and nothing in it is made false.
- [x] `README.md` - out of scope: Lines 37-40 say only that interaction events update `interaction_signals`, which ranking uses. That is still true, and the file makes no claim about event ids or the popular ordering.

**Updated but not named by the Step 3 inventory.** engine/server/api/recommendations/docs/LAYER_PARAMS.md

**Other files that had to be touched.** - while updating `docs/project/issues/01-deterministic-event-ids.md`: docs/project/issues/archive/01-deterministic-event-ids.md — new file, the archived copy of the issue that `docs/project/triage-labels.md` requires for a `complete` issue. The original `docs/project/issues/01-deterministic-event-ids.md` still needs deleting (e.g. `git rm`), because I can't delete files. Until then the issue is in both places, like `15-remove-single-like.md` is now.

**ADR conflicts.** ADR-0001 decision 1 reads: "A `like` on a video the profile already likes, or an `undo_like` on one it does not, publishes nothing." The delivered gating does not key on the profile's `likes` list. It keys on the published-like state in `like_generations` (`published` flag). So after a reset or a `max_likes` trim, an `undo_like` on a video the profile no longer "likes" still publishes an `UndoLike`, because it closes a published like. And a re-like of that video, which is new in `likes`, publishes nothing, because the like is still published. An un-like of an imported like publishes nothing even though the profile "likes" it. This fits the decision's intent ("only on a real state change", and it closes the reset/import loops the requirements had accepted), but it departs from the ADR's literal wording. Amending decision 1 to say "published like" is the operator's call. The build also departs from the requirements text, though not from any ADR: the generation advances only when a published like opens, not on every new `likes` row, and imported likes do not advance it.

### `client/README.md`

<changes>
`client/README.md`: `POST /api/user-action` now says when each action publishes and how event ids are built. The likes import and profile delete entries now cover like generations.

- **Line 19, `POST /api/user-action`:** removed the sentence saying every like publishes. With a key, the action is stored in the profile, and a like and a dislike on one video replace each other.
  - A `like` publishes a `Like` only when it opens the profile's published like of the video. The line points to **Published like** in `CONTEXT.md` for the definition and does not repeat it there.
  - An `undo_like`, or a dislike that replaces a like, publishes an `UndoLike` only when it closes one. No other dislike action publishes.
  - A request that changes nothing answers 200 `{ok, updatedAt}` and publishes nothing.
  - Without a key, nothing is stored. Every `like` and `undo_like` publishes, with one fixed id per video and event type, so the Engine counts repeats as duplicates.
  - An event id is `client-` plus the SHA-256 of: the actor (profile id or `anonymous`), the video uuid and host as the Engine resolved them, the event type, and the like generation (0 without a key).
  - The dislike limit, the taste-vector request and the 502 behaviour are unchanged.
  - I checked all of this against `_handle_user_action` and `_store_reaction` in `server.py`.
- **Line 15, likes import:** an imported like opens no published like, so un-liking it publishes nothing. The one exception: if the profile's own earlier like of that video is still published (for example after a reset), the un-like closes it and does publish. `record_like` with `publish=True` does not reopen a like that is still published, which is why the checklist's flat "publishes nothing" would be wrong.
- **Line 13, profile delete:** added like generations to what is removed, matching `delete_profile`.
</changes>

<not_on_checklist>
none
</not_on_checklist>

### `DEPLOYMENT.md`

<changes>
DEPLOYMENT.md: added the 25.0 popular signal cap (section 1) and the publish-on-change rule, the `like_generations` table and derived event ids (section 5).

- **Section 1**, after the `interaction_signals` note: the popular ordering adds at most 25.0 of a video's signal score to its crawled popularity. The limit is `POPULAR_SIGNAL_CAP` in `engine/server/data/random_videos.py`, and the stored score stays uncapped. I checked this against the `ORDER BY` in `fetch_popular_videos`, which reads `v.popularity + MIN(COALESCE(sig.signal_score, 0), ?)` with the constant bound as a parameter.
- **Section 5**, new paragraph after the `/api/user-action` paragraph:
  - With a key, a `Like` is published only when the request opens the profile's published like of the video, and an `UndoLike` only when it closes one.
  - A request that changes nothing answers 200 and publishes nothing.
  - Published likes are tracked in the `users.db` `like_generations` table. It is created at startup by `ensure_user_schema` in `server.py`, so there is no migration step.
  - Event ids are derived, so a replayed event is a duplicate at the Engine's ingest and changes no counts.
  - Keyless requests always publish, and every keyless `Like` of a video carries one fixed id, as does every keyless `UndoLike`.
  - The section points to `CONTEXT.md` for what a published like is and to ADR-0001 for the id scheme rather than restating them.
  - I checked all of this against `_handle_user_action`, `record_like` and `close_like`.
- The existing line saying "disliking a liked video publishes the `UndoLike` that withdraws the like" is unchanged, since it is still true.
</changes>

<not_on_checklist>
none
</not_on_checklist>

### `engine/server/api/recommendations/docs/OVERVIEW.md`

<changes>
OVERVIEW.md: the popular pool's order now reads `popularity` plus the interaction signal capped at `POPULAR_SIGNAL_CAP` (25.0), not "top by likes/views".

- §4 "What Pools Are", the popular pool line (old line 99): changed "top by likes/views" to "top by `popularity` plus the interaction signal capped at `POPULAR_SIGNAL_CAP`, then likes and views". The rest of the line ("if likes exist, re-ranked by similarity; then caps") is unchanged.
- §3 popular layer, the `Source:` line (old line 69): this made the same wrong claim, "top by likes/views with a soft freshness bonus". It now gives the full order: `popularity` plus the capped signal (with the constant's value and file), then likes, views, recency and video id. I also removed the "soft freshness bonus", because neither `fetch_popular_videos` nor `PopularVideosGenerator` applies one. Freshness only comes in later, in the unified scoring (§5), which covers every layer.
- Checked against the code: in `engine/server/data/random_videos.py`, `POPULAR_SIGNAL_CAP = 25.0` is at line 12, and `fetch_popular_videos` orders by `(v.popularity + MIN(COALESCE(sig.signal_score, 0), ?)) DESC`, then `v.likes + sig.likes_count`, `views`, `published_at` and `video_id`.
- The §5 scoring `popularity` feature is a separate thing and is unchanged.
</changes>

<not_on_checklist>
none
</not_on_checklist>

### `engine/server/api/recommendations/docs/PIPELINE_DIAGRAM.md`

<changes>
Changed the popular-layer node label (line 29) from `top likes/views` to `popularity + capped signal`.

- Line 29 is now `G --> G3[popular<br/>popularity + capped signal]`.
- I checked it against the code. `fetch_popular_videos` in `engine/server/data/random_videos.py` orders first by `v.popularity + MIN(COALESCE(sig.signal_score, 0), ?)`, and the cap is bound from `POPULAR_SIGNAL_CAP = 25.0`.
- The cap value and the tie-breakers are left out of the diagram. OVERVIEW.md and LAYER_PARAMS.md describe those.
- No other node changed. `H3[Popular pool<br/>rank by similarity if likes]` and the scoring `w_pop*popularity` term are separate steps and were already correct.
</changes>

<not_on_checklist>
none
</not_on_checklist>

### `engine/server/api/recommendations/docs/LAYER_PARAMS.md`

<changes>
Fixed the popular layer's **Source:** line (line 137). It now describes the actual pool order: `popularity` plus the capped interaction signal, then likes, then views.

- Before, line 137 said "top videos by likes/views". It now reads: "top videos by `popularity` plus the interaction signal capped at `POPULAR_SIGNAL_CAP` (25.0, `engine/server/data/random_videos.py`), then by likes and views."
- I checked this against `fetch_popular_videos` on disk. The constant `POPULAR_SIGNAL_CAP = 25.0` is at line 12. The query orders by `(v.popularity + MIN(COALESCE(sig.signal_score, 0), ?)) DESC`, then `(v.likes + COALESCE(sig.likes_count, 0)) DESC`, then `v.views DESC`, and the cap is passed as a bound parameter.
- The "Behavior:" line at the end describes re-ranking after the pool is built, so I left it as it was.
</changes>

<not_on_checklist>
none
</not_on_checklist>

### `CONTEXT.md`

<changes>
Added the glossary term **Published like** to `CONTEXT.md`, which defines what counts as a real like/un-like change.

- The new entry sits after **Interaction signal**. A published like is a profile's like of one video that has reached the Engine. The Client tracks it in `like_generations` with a like generation, and that generation goes into the event id.
- Opening a published like advances the generation. Closing it (an un-like, or a dislike replacing the like) keeps the same generation.
- A `Like` is published only when a published like opens, and an `UndoLike` only when one closes.
- A published like is separate from the likes list. A reset or the `max_likes` trim leaves it open, an imported like never opens one, and deleting the profile removes it. The entry points to ADR-0001.
- The **Interaction event** and **Interaction signal** entries are unchanged, because they already match the build.
- I checked every claim against the code:
  - `record_like` upserts only `WHERE published = 0`, and only for a new like with `publish=True`.
  - `close_like` sets `published = 0` and runs even when `remove_like` removed nothing, so a like the trim dropped can still be closed.
  - `clear_likes` touches only `likes`.
  - `delete_profile` deletes from `like_generations`.
  - The import calls `record_like` without `publish`.
</changes>

<not_on_checklist>
none
</not_on_checklist>

### `docs/project/adr/0001-derived-interaction-event-ids.md`

<changes>
Added the like-generation scheme to ADR-0001's Consequences and said what "real state change" in decision 1 means. The decisions themselves are unchanged.

Five new Consequences bullets, each checked against `client/backend/lib/users_store.py`, `client/backend/server.py` `_store_reaction` and `client/backend/lib/profiles.py`:
- **Where the state lives:** the like instance is a generation in the `users.db` table `like_generations`, one row per profile and video with a `published` flag. The bullet names **Published like** and points to `CONTEXT.md` for its definition instead of repeating it. It also says decision 1's "real state change" means opening or closing a published like, not a change to the likes list. This covers the conflict with decision 1's wording that the checklist flagged, without rewording the decision.
- **When events publish:** a like publishes and moves the generation forward only when it opens a published like. An un-like, or a dislike replacing a like, publishes only when it closes one, and uses the same generation as its `Like`. Rows survive un-like, reset (`clear_likes` does not touch the table) and the trim, and are deleted with the profile.
- **Reset and import:** imported likes (`publish` left False) never open a published like, so un-liking one publishes nothing. A re-like after a reset publishes nothing, because the upsert only fires when `published = 0`. So neither reset nor import can be repeated to push a video's signal up or down.
- **The `max_likes` trim:** a trimmed like stays published, and the undo_like path calls `close_like` whether or not `remove_like` found a row, so an un-like still withdraws it.
- **Likes older than the table:** they have no published row, so un-liking one publishes no `UndoLike` and its +1 stays at the Engine.
</changes>

<not_on_checklist>
none
</not_on_checklist>

### `docs/project/issues/01-deterministic-event-ids.md`

<changes>
Issue 01 is marked `bug, complete` with all 8 acceptance criteria ticked, and a copy is in `docs/project/issues/archive/`. The original file still needs deleting, because I can't delete files.

- **Status line:** `Status: bug, ready-for-agent` is now `Status: bug, complete`, the label `docs/project/triage-labels.md` gives delivered issues.
- **Acceptance criteria:** all 8 boxes (lines 55-62) are ticked.
- **Checked against the code before ticking:**
  - `POPULAR_SIGNAL_CAP = 25.0` is a bound parameter in `fetch_popular_videos`.
  - The `like_generations` upsert and `close_like` are in `users_store.py`.
  - `server.py` builds `event_id` as `client-` plus a SHA-256 hex digest.
  - The latest full `tests/active` run passed: exit 0, 146 tests. That includes `test_interaction_events.py`, `test_internal_events.py`, `test_random_videos.py`, `test_profiles.py` and the frontend suites.
- **Move to archive:** `docs/project/issues/archive/01-deterministic-event-ids.md` is written with the same content. The original at `docs/project/issues/01-deterministic-event-ids.md` has the same edits, so the two agree until it is deleted.
- **Left as it was:** the problem statement, triage comments, agent brief and out-of-scope list are the issue's own record, so they stay as filed.
</changes>

<not_on_checklist>
docs/project/issues/archive/01-deterministic-event-ids.md — new file, the archived copy of the issue that `docs/project/triage-labels.md` requires for a `complete` issue. The original `docs/project/issues/01-deterministic-event-ids.md` still needs deleting (e.g. `git rm`), because I can't delete files. Until then the issue is in both places, like `15-remove-single-like.md` is now.
</not_on_checklist>

### `docs/project/plans/13-deterministic-event-ids.md`

<changes>
Plan 13 is now marked delivered and points to `16-13-deterministic-event-ids.md`. Its risks describe the code as built, and a new Delivery section records what the build settled. The file has not been moved to `archive/` yet.

- **Status line** (under the title): says the plan is delivered, built by `docs/project/plans/16-13-deterministic-event-ids.md`, and that plan 16-13 wins where the two differ. It also says the like-instance design in "High-level plan" is the one approved at planning, and sends the reader to "Delivery" for what the build settled on top of it. This follows the format of the archived plans 10 and 11.
- **Risks, trimmed likes:** replaced with what the code now does. A trimmed like stays published, so a later un-like still closes it and publishes the `UndoLike`. A re-like opens nothing while the like stays published. I checked this against `record_like`, `close_like` and `_store_reaction`: the publish decision follows `close_like`, not `remove_like`.
- **Risks, profile deletion:** the open question is answered. `delete_profile` in `client/backend/lib/profiles.py` removes the profile's `like_generations` rows in the same transaction.
- **Risks, likes import:** still true, and now more precise. Import leaves `publish` unset and ignores the return value, so it publishes nothing and never touches `like_generations` (checked at `server.py`'s import call site).
- **New "Delivery / What the build settled" section:**
  - the `published` flag, pointing at `CONTEXT.md` **Published like** and ADR-0001's Consequences instead of restating the scheme;
  - what `record_like(publish=True)` and `close_like` return;
  - `clear_likes` keeps generations and their published state, by design (checked: it deletes only `likes` rows);
  - likes stored before the table existed publish no `UndoLike` when un-liked;
  - the id is hashed over the Engine-resolved uuid and host, and `uuid4` stays imported for `run_id`;
  - `POPULAR_SIGNAL_CAP = 25.0` is passed as a bound parameter.

**Still to do:** the move to `docs/project/plans/archive/` hasn't happened. I have no move or delete tool, and a copy would leave two versions of the plan. It needs a `git mv` at harvest on main, alongside plan 16-13 and the issue.
</changes>

<not_on_checklist>
none
</not_on_checklist>

### `docs/project/roadmap.md`

<changes>
Roadmap: security issue `01` is now listed as Delivered, removed from the open issues and the implementation order, and has its two remaining follow-ups added as optional M1 lines.

- **Delivered**: added a line after security issue `06`, in the same format. It says the Client derives each `Like`/`UndoLike` id from actor, video, event type and like generation, and that a profile publishes only when a like opens or closes, so repeated likes collapse at the Engine's ingest. It also says the popular ordering adds at most `POPULAR_SIGNAL_CAP` of a video's signal. It points at `docs/project/plans/archive/13-deterministic-event-ids.md`, the path the plan will have once the harvest archives it. That follows the same naming as `archive/10-normalise-instance-hosts.md`, and the file does not exist there yet.
- **M1**: "Open security issues" now reads `02` to `05` and `07`. Added two optional lines under it:
  - decide whether the likes import should publish (imported likes publish nothing and never open a published like);
  - bound the popular likes tiebreaker (`v.likes + sig.likes_count` in `fetch_popular_videos`), which `POPULAR_SIGNAL_CAP` does not cover.
- **Implementation order, step 1**: removed `01`, so it now lists `02`, `03`, then `04`, `05`.
- Did not add the reset/import loops or the trim gap, because the `published` flag closes them.
- Checked against the code: `POPULAR_SIGNAL_CAP = 25.0` and the uncapped `v.likes + COALESCE(sig.likes_count, 0)` tiebreaker are both in `engine/server/data/random_videos.py`.
</changes>

<not_on_checklist>
none
</not_on_checklist>

