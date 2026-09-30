# Rank Hot and Popular on source-instance counts only (issue 37)

## Requirements

### Request

Build `docs/project/issues/37-hot-popular-drop-local-signal.md` (now in `issues/archive/`): Hot and Popular must rank on the counts the source PeerTube instance reports, without this site's likes. The operator's reasoning, verbatim: "likes and unlikes come from me, and recommended is based on me. for hot to work it has to come from likes that are external to our db, like actual likes."

### Purpose

The global feeds (Hot, Popular) and the popular layer of the Recommendations mix are meant to reflect what is popular on PeerTube. Today they also count `interaction_signals`, which only this site's Client backend fills, from the operator's own likes (+1 Like, −1 UndoLike, capped at 25 in Hot). Personalisation already comes through similarity to the operator's likes in Recommendations, so the global orders must not carry it a second time. Likes shown on a card must likewise be the source instance's number.

### Current state found in the tree

- `engine/server/data/random_videos.py`:
  - `POPULAR_SIGNAL_CAP = 25.0` (line 13). `POPULAR_ORDER_BY` (line 15): `v.popularity + MIN(COALESCE(sig.signal_score, 0), 25)`, then `v.likes + COALESCE(sig.likes_count, 0)`, then `v.views`, `v.published_at`, `v.video_id`, `v.instance_domain`, all DESC.
  - `ORDERED_FEED_ORDER_BY["hot"]` is `POPULAR_ORDER_BY`. `ORDERED_FEED_ORDER_BY["popular"]` is `v.likes + COALESCE(sig.likes_count, 0)`, then `v.views`, `v.video_id`, `v.instance_domain`, all DESC.
  - `fetch_random_rows` (DB random fallback) reports `likes` as `v.likes + COALESCE(sig.likes_count, 0)`.
  - `fetch_popular_videos` (the Recommendations popular layer, via `recommendations/candidates/popular_videos.py`) orders by `POPULAR_ORDER_BY` and returns `interaction_signal_score`.
  - `fetch_ordered_page` (Hot, Popular, Recent feeds) reports `likes` as crawled plus signal, and returns `interaction_signal_score`.
  - `fetch_recent_videos` and `data/metadata.py` (random-cache rows) already report crawled `v.likes` and do not join `interaction_signals`.
- No reader of `interaction_signal_score` exists outside `random_videos.py` (searched `engine/`, `client/`).
- `interaction_signals` is filled by `data/interaction_events.py::ingest_interaction_event`, and is read only by `random_videos.py`.

### Confirmed requirements

- **R1.** Hot orders by `v.popularity` DESC, then `v.likes` DESC, then `v.views`, `v.published_at`, `v.video_id`, `v.instance_domain`, all DESC. No `interaction_signals` term.
- **R2.** Popular orders by `v.likes` DESC, then `v.views`, `v.video_id`, `v.instance_domain`, all DESC. No `interaction_signals` term.
- **R3.** The Recommendations popular layer (`fetch_popular_videos`) uses the same order as Hot (operator: "Yes, one order everywhere").
- **R4.** Every row `random_videos.py` returns reports `likes` as the crawled `v.likes` only (operator: "Yes, PeerTube's count only"). This covers `fetch_random_rows`, `fetch_popular_videos` and `fetch_ordered_page`.
- **R5.** Nothing no longer read is kept: `POPULAR_SIGNAL_CAP`, the `interaction_signals` joins in `random_videos.py`, and the `interaction_signal_score` row key go.

### Out of scope

- `interaction_signals` ingestion (`data/interaction_events.py`, the Client backend's event publishing) stays as it is. Issue 38 decides whether trending uses it.
- Real trending (issue 38), the `popularity` formula, and `recompute-popularity.py`.
- Recent's order and the random cache.

### Conflicts

- The durable `tests/active/test_random_videos.py` pins the behaviour R1–R4 remove: "a Like adds 1 to the random row's likes", "the popular order caps the interaction signal", and hot and popular expected orders that include B's signal. Per `dev_flow.md` Step 8 these tests are retired or replaced, not repointed. The operator's answers to Q1 and Q2 settle this in favour of R1–R4.

### Standing constraints

- New code matches the existing style of `random_videos.py` (SQL layout, constant naming, row dict shape).
- Backwards compatibility is not required.

### Test trees

- `active`: `tests/active`
- `working`: `tests/tmp`
- `plans`: `docs/project/plans`

### Baseline suite state

Run 2026-09-29 through `./.un/skills/devsecops/scripts/validate_tests.py`: exit 0. It selected 1 of 30 groups (`test_search_fusion.py`, no map entry): 10 passed. The other 29 groups were unchanged and answered green by the banked record `tests/last_test_validation.json`. Not RED, so no baseline variant applies.

## High-level plan

### Approach

The whole change sits in `engine/server/data/random_videos.py`, which owns every order and row that counts `interaction_signals`.

- **R1, R3.** `POPULAR_ORDER_BY` loses both `sig` terms, so it leads on `v.popularity`, then `v.likes`, views, `published_at`, `video_id`, `instance_domain`. It stays one constant: `ORDERED_FEED_ORDER_BY["hot"]` keeps pointing at it, and `fetch_popular_videos` keeps ordering by it. The Hot feed and the Recommendations popular layer therefore stay the same order, which the operator chose.
- **R2.** `ORDERED_FEED_ORDER_BY["popular"]` loses its `sig.likes_count` term.
- **R4.** `fetch_random_rows`, `fetch_popular_videos` and `fetch_ordered_page` select `v.likes` directly, as `fetch_recent_videos` and `data/metadata.py` already do.
- **R5.** With no order and no column reading `sig` any more, the `LEFT JOIN interaction_signals sig` clauses go from all three functions (twice in `fetch_popular_videos`: the ranking subquery and the outer select). `interaction_signal_score` goes from the SELECTs and the row dicts. `POPULAR_SIGNAL_CAP` and its comment go.

Nothing outside `random_videos.py` reads the removed key or constant, so no caller changes. The Engine serves the new orders after a restart.

### Alternatives considered

- **Set the cap to 0, or make the signal a config weight.** Rejected: it keeps a join and a knob nobody wants, and R5 asks for unused code to go. A weight could return later with issue 38 if trending needs one.
- **Stop ingesting interaction events.** Rejected: out of scope. Ingestion also records the event history issue 38 may use, and removing it touches the Client backend and the bridge.
- **Split Hot from the Recommendations popular layer.** Rejected by the operator (R3).

### Risks and limitations

- **Durable tests pin the old behaviour.** `tests/active/test_random_videos.py` asserts the cap, a Like adding to row likes, and hot and popular orders built on B's signal. These go red by design. At Step 8 they are retired to `tests/archive` or replaced by the harvested checkpoint, per the confirmed conflict note, and are never edited to pass.
- **Query plan.** Hot's leading key becomes the plain column `v.popularity`, which `idx_videos_popularity` (`popularity DESC`, created by `sync-whitelist.py` and `recompute-popularity.py`) can serve. The popular subquery also drops a join. Both should make these reads cheaper, not dearer. This is not a requirement and will not be measured.
- **Hot stays a totals order.** Hot still ranks by stored `popularity`, frozen at its last recompute. Issue 38 addresses that.
- **Running Engine.** The change reaches the browser only after `scripts/run-services.sh restart`.

### Tradeoffs the operator accepts

- Likes clicked on this site no longer affect any order or any displayed like count. Until issue 38, they only feed the operator's personalisation (Recommendations similarity) and the `interaction_signals` table.
- The retired durable tests are replaced only by what this build's checkpoint asserts, harvested at Step 10.

## Impacts

### `POPULAR_SIGNAL_CAP` and its comment
- **path:** `engine/server/data/random_videos.py` (lines 12-13)
- **Changes:** deleted.
- **Depends on it:** only `POPULAR_ORDER_BY` in the same file. `tests/active/test_random_videos.py` defines its own `CAP = 25.0` and never imports the constant. The docs name it (entries below).
- **Risk:** low. An import elsewhere would break at load, but the search of `engine/` and `client/` found none.

### `POPULAR_ORDER_BY`
- **path:** `engine/server/data/random_videos.py` (lines 14-22)
- **Changes:** the first key becomes `v.popularity DESC`, and the second becomes `v.likes DESC`. `v.views`, `v.published_at`, `v.video_id` and `v.instance_domain` stay. The tie-break comment stays.
- **Depends on it:** `ORDERED_FEED_ORDER_BY["hot"]` (the Hot feed through `fetch_ordered_page`), and `fetch_popular_videos` (the Recommendations popular layer through `recommendations/candidates/popular_videos.py`, wired in `builder.py:109-111` and `server.py:402`).
- **Risk:** medium. This one change reorders both surfaces. Any `sig.` reference left in the constant while the join is removed raises `no such column` at query time, not at import.

### `ORDERED_FEED_ORDER_BY["popular"]`
- **path:** `engine/server/data/random_videos.py` (lines 25-30)
- **Changes:** the first key becomes `v.likes DESC`.
- **Depends on it:** the Popular feed through `fetch_ordered_page`, served by `handlers/similar.py::_handle_ordered_feed`.
- **Risk:** low.

### `fetch_random_rows`
- **path:** `engine/server/data/random_videos.py` (lines 39-129)
- **Changes:** selects `v.likes`, not `v.likes + COALESCE(sig.likes_count, 0) AS likes`. The `LEFT JOIN interaction_signals sig` goes.
- **Depends on it:** `handlers/similar.py::_fetch_random_rows` (the random feed's DB fallback and other fallbacks at lines 725, 796 and 1100), and `builder.py:93` for the `random`, `explore` and `similar_from_likes` generators while no random cache is open. `recommendations/scoring.py:53` reads the row's `likes` into the popularity sub-score.
- **Risk:** low. Rows keep the same keys. Their `likes` values can only drop, and only for videos with local likes, so the popularity sub-score moves by the log of a few likes at most.

### `fetch_popular_videos`
- **path:** `engine/server/data/random_videos.py` (lines 222-325)
- **Changes:** the ranking subquery drops its `LEFT JOIN interaction_signals sig` and still orders by `POPULAR_ORDER_BY`. The outer select drops its join, selects `v.likes` (it already does) and drops `interaction_signal_score` from the SELECT and the row dict.
- **Depends on it:** the Recommendations popular layer (`candidates/popular_videos.py:53`). That module reads the rows' keys through `like_key` and `apply_author_instance_caps`, and sets `similarity_score`. It never reads `interaction_signal_score` or `popularity`. `recommendations/scoring.py` reads `views` and `likes`.
- **Risk:** medium. The subquery and the outer query each carried a `sig` join, and missing either leaves a `sig.` reference or an orphan join.

### `fetch_ordered_page`
- **path:** `engine/server/data/random_videos.py` (lines 328-428)
- **Changes:** selects `v.likes`, drops `interaction_signal_score` from the SELECT and the row dict, and drops the `LEFT JOIN interaction_signals sig`. The recent filter, the error threshold and the paging are unchanged.
- **Depends on it:** `handlers/similar.py::_handle_ordered_feed` (Hot, Popular, Recent), which passes rows through serving moderation to the response. The response's rows lose the `interaction_signal_score` key. No frontend or Client backend code reads it (searched `client/`).
- **Risk:** low.

### `fetch_recent_videos`, `data/metadata.py`
- **path:** `engine/server/data/random_videos.py` (lines 132-219) and `engine/server/data/metadata.py`
- **Changes:** none. They already report crawled `v.likes` with no `sig` join. They are listed as the precedent R4 aligns the others to.
- **Risk:** none.

### Recommendations popular layer
- **path:** `engine/server/api/recommendations/candidates/popular_videos.py`
- **Changes:** none in code. Its pool is now the top of the signal-free order.
- **Risk:** low.

### Recommendation scoring
- **path:** `engine/server/api/recommendations/scoring.py` (`_popularity_score`, line 212)
- **Changes:** none in code. Rows from `fetch_random_rows` and `fetch_popular_videos` feed it crawled likes only (as random-cache rows already do).
- **Risk:** low. A few likes change a log-normalised sub-score weighted 0.2.

### Engine route handlers
- **path:** `engine/server/api/handlers/similar.py`
- **Changes:** none. `_handle_ordered_feed` and `_fetch_random_rows` pass rows through unchanged.
- **Risk:** low.

### `_handle_ordered_feed` chunk dedup comment
- **path:** `engine/server/api/handlers/similar.py` (line 762)
- **Changes:** the comment "A signal landing between two chunks can move a row across the boundary; keep its first place." is wrong once no order reads the signal. The dedup it explains is still needed, because an `/api/video` refresh rewrites a video's `popularity`, `likes` and `views` (`handlers/video.py:379-403`) and can move it between chunks. The comment is reworded to name that cause. The code is unchanged.
- **Risk:** none (comment only). Found at Step 4, pass 1.

### Durable test `test_random_videos.py`
- **path:** `tests/active/test_random_videos.py`
- **Changes:** at Step 8, its tests asserting the removed behaviour go red and are retired (or replaced by the harvested checkpoint):
  - `test_an_undone_like_leaves_the_random_row_s_likes_at_the_crawled_count`: its control asserts a Like adds 1 to row likes.
  - `test_an_undone_like_keeps_the_popular_order_of_two_tied_videos`: its control reads `interaction_signal_score`.
  - `test_the_popular_order_caps_the_interaction_signal`: the cap.
  - `test_consecutive_pages_concatenate_into_the_order_s_total_sort[hot|popular]`: `EXPECTED` builds B's position from its signal. `[recent]` keeps passing.
  - `test_a_page_holds_exactly_the_embedded_rows_under_the_threshold` should keep passing, because it does not depend on the signal.
- **Depends on it:** `test_groups["test_random_videos.py"]` → `engine/server/data/random_videos.py` in `.un/skills/devsecops/config.json`, updated at harvest (Step 10).
- **Risk:** high for the suite. These reds are expected and are handled by retirement, never by editing.

### Durable tests `test_interaction_events.py`, `test_server.py`
- **path:** `tests/active/test_interaction_events.py`, `tests/active/test_server.py`
- **Changes:** none. They assert ingestion into `interaction_signals` (dedup, and the bridge publish in `test_server.py:523`), which is out of scope and unchanged.
- **Risk:** low.

### Frontend card likes
- **path:** `client/frontend/src/components/video-card.ts` (lines 323, 383)
- **Changes:** none in code. It shows `stats.likes`, which is now the PeerTube count on every path.
- **Risk:** none.

### Documentation entries

#### `engine/server/api/recommendations/docs/OVERVIEW.md`
- **path:** `engine/server/api/recommendations/docs/OVERVIEW.md` (lines 14, 15, 91, 121)
- **Changes:** hot, popular, the popular layer and the popular pool are described as including the capped signal or "crawled plus signal likes". Rewrite them to the signal-free orders.

#### `engine/server/api/recommendations/docs/LAYER_PARAMS.md`
- **path:** `engine/server/api/recommendations/docs/LAYER_PARAMS.md` (line 142)
- **Changes:** the popular layer's Source sentence names `POPULAR_SIGNAL_CAP`. Rewrite it.

#### `engine/server/api/recommendations/docs/PIPELINE_DIAGRAM.md`
- **path:** `engine/server/api/recommendations/docs/PIPELINE_DIAGRAM.md` (line 28)
- **Changes:** the node label is `popularity + capped signal`. Relabel it.

#### `engine/server/README.md`
- **path:** `engine/server/README.md` (lines 31-33)
- **Changes:** "write-derived signals are consumed from aggregated `interaction_signals`" becomes false, because ranking reads nothing from it. Rewrite.

#### `DEPLOYMENT.md`
- **path:** `DEPLOYMENT.md` (lines 73-75, and 269)
- **Changes:** lines 73-75 describe the cap and ranking signals from `interaction_signals`, which is now false. Line 269 says hot and popular sort "on a computed key". Check it against the delivered orders at Step 9.

#### `CONTEXT.md`
- **path:** `CONTEXT.md` (lines 7, 13, 14)
- **Changes:** the **Interaction signal**, **Hot** and **Popular** entries describe the cap and the signal likes. Rewrite them.

#### ADR-0001
- **path:** `docs/project/adr/0001-derived-interaction-event-ids.md` (decision 4)
- **Changes:** "The popular ordering caps the signal" is superseded, since the ordering no longer reads the signal. Amending an ADR is the operator's decision (Step 9.1). It is raised at Step 4.

### Highest risk
1. **`fetch_popular_videos`**: two `sig` joins (subquery and outer), and a `sig.` reference left in `POPULAR_ORDER_BY` fails only at query time. It feeds both Hot's twin and the Recommendations layer.
2. **`POPULAR_ORDER_BY`**: one constant reorders two surfaces. Its tie-breaks must survive untouched, or paging repeats rows.
3. **`tests/active/test_random_videos.py`**: five tests go red by design. Mis-triaging them (editing rather than retiring) is the failure `dev_flow.md` Step 8 guards against.

### Reassessment

#### Pass 1

Opened: `random_videos.py` (whole file), `candidates/popular_videos.py` (whole), `handlers/similar.py:734-778`, `scoring.py` (via grep at 30-53, 212-220), `builder.py:93-111` and `server.py:399-402` (via grep), `video-card.ts:323-383`, `pages/videos/index.ts` debug block (464-490), and every doc entry at its cited line.

1. **Will it still work as intended?** Yes. Every reader of `sig` is inside `random_videos.py`. `candidates/popular_videos.py` reads only `like_key` fields and sets `similarity_score`. The debug metrics block renders `row.debug` (`score`, `similarity_score`, `freshness_score`, `popularity_score`, layer, ranks), never `interaction_signal_score`. So removing the key and the joins breaks no reader.
2. **Ramifications.** Hot, the Recommendations popular layer and Popular reorder for videos with local likes only. Every other video keeps its relative place. Row `likes` drop by the local count on the DB-random, popular and ordered paths. `interaction_signals` keeps filling but is read by nothing until issue 38.
3. **What else must happen.** An Engine restart to serve it. The doc entries at Step 9. The retirement of the `test_random_videos.py` tests at Step 8. The comment at `similar.py:762` (new, below).
4. **How the original functionality is altered.** ADR-0001 decision 4 ("The popular ordering caps the signal") no longer describes the system. Decisions 1-3 (derived event ids) are untouched.

**Entries not borne out:** none. All line numbers and claims matched the files.

**New impact:** `engine/server/api/handlers/similar.py:762`, a comment that attributes the chunk dedup to a signal landing between chunks. Added above as "`_handle_ordered_feed` chunk dedup comment".

**Recommendations put to the operator:**
- **A1.** Reword the `similar.py:762` comment to name the `/api/video` refresh as the cause. Cost: one comment line in a file the plan otherwise leaves alone.
- **A2.** At Step 9, add an amendment to ADR-0001 marking decision 4 superseded by this build (the ordering no longer reads the signal, so there is nothing to cap), leaving decisions 1-3 as they stand. Cost: one short section in an ADR, and this is your call. The alternative is to leave the ADR as history and say so in CONTEXT.md only.

**Operator decision:** A1 and A2 both approved. A1 adds `similar.py:762` (comment only) to the build's files. A2 is carried out at Step 9.

#### Pass 2

Searched every Python file under `engine/server` for `signal` to find any other reader or comment tied to the ranking signal. The only hits outside `random_videos.py` and the inventoried `similar.py:762` are OS signal handling (`server.py`, `precompute-similar-ann.py`), the unrelated "single success signal" docstring in `handlers/video.py:209`, and ingestion (`interaction_events.py`, `db/jobs/tests/test-interaction-events.py`), which is out of scope. **No new impact, no unconfirmed entry.** Steps 3-4 have converged.

### Documentation to update
- [x] `engine/server/api/recommendations/docs/OVERVIEW.md`: **updated.** §1 hot and popular now read `popularity`, then crawled likes…, and "crawled likes, then views…, no age decay". §3 popular Source and §4 popular pool drop the capped signal.
- [x] `engine/server/api/recommendations/docs/LAYER_PARAMS.md`: **updated.** The popular layer Source reads "top videos by `popularity`, then by crawled likes and views (`POPULAR_ORDER_BY`, …)".
- [x] `engine/server/api/recommendations/docs/PIPELINE_DIAGRAM.md`: **updated.** Node G3 is labelled `popularity, then likes`.
- [x] `engine/server/README.md`: **updated.** The ranking bullet says `interaction_signals` is aggregated and read by no feed order or returned row.
- [x] `DEPLOYMENT.md`: **updated.**
  - The §1 note replaces the cap paragraph with one sentence: signals are aggregated, and the popular ordering and popular mode sort on crawled `popularity`, likes and views only.
  - The ordered-feed-load paragraph says hot and popular sort on stored columns rather than "a computed key".
  - The dislike paragraph no longer implies a like moves a global ranking signal. This last one is an inventory gap found at 9.1.
- [x] `CONTEXT.md`: **updated.** **Interaction signal** is read by no order or row (ADR-0001, amended). **Hot** is the age-decayed popular ordering (`popularity`, then crawled likes and views). **Popular** is all-time crawled likes, then views.
- [x] `docs/project/adr/0001-derived-interaction-event-ids.md`: **updated** (operator approved A2). A new "Amendment: decision 4 superseded (issue 37)" section. Decisions 1-3 and the original text are unchanged.
- [x] `README.md` (root): **updated. Inventory gap found at 9.1.** Line 40 said `interaction_signals` "are also used by ranking" and now says ranking does not read them.
- **No update:**
  - `docs/project/adr/0005-raw-event-retention-keeps-ids.md`: its sentence "Nothing reads it for ranking" is about `interaction_raw_events` and stays true.
  - `client/README.md` and `client/frontend/README.md`: neither describes the orders' keys; they point to OVERVIEW.md.
  - `docs/wiki/` does not exist.

## Implementation plan

### What must be testable

- **T1 (R1, R3).** With `interaction_signals` holding a large `signal_score` and `likes_count` for a low-popularity video, Hot pages (`fetch_ordered_page(conn, "hot", …)`) and `fetch_popular_videos` rank it by `popularity`, then `v.likes`, views and the tie-breaks, exactly as if the table were empty.
- **T2 (R2).** In the same state, Popular pages rank by `v.likes`, views and the tie-breaks, ignoring `likes_count`.
- **T3 (R4, R5).** Rows from `fetch_random_rows`, `fetch_popular_videos` and `fetch_ordered_page` report `likes` equal to the stored `videos.likes` for a video with signal likes, and carry no `interaction_signal_score` key.

`POPULAR_SIGNAL_CAP` and the joins going (R5) shows as those behaviours. Nothing observable remains of a join that no expression reads, and the constant has no reader to test through. The rung-1 check is the deletion itself, confirmed at Step 8 by a search showing no `sig`, `interaction_signals` or `POPULAR_SIGNAL_CAP` left in `random_videos.py`.

### Module map

One production module, `engine/server/data/random_videos.py`, plus one comment in `engine/server/api/handlers/similar.py`. No new module, function, type or constant (ladder rung 1: everything here is deletion).

### Draft

`engine/server/data/random_videos.py`, top of the file:

```python
from data.metadata import fetch_metadata
from data.random_cache import fetch_random_rowids

# video_id then instance_domain close every order, so rows equal on the other keys still sort one way and an OFFSET page never repeats or skips one.
POPULAR_ORDER_BY = """
    v.popularity DESC,
    v.likes DESC,
    v.views DESC,
    v.published_at DESC,
    v.video_id DESC,
    v.instance_domain DESC
"""
ORDERED_FEED_ORDER_BY = {
    "hot": POPULAR_ORDER_BY,
    "popular": """
    v.likes DESC,
    v.views DESC,
    v.video_id DESC,
    v.instance_domain DESC
""",
    "recent": ...unchanged...,
}
```

`POPULAR_ORDER_BY` is no longer an f-string, because it has nothing left to interpolate.

`fetch_random_rows`: `(v.likes + COALESCE(sig.likes_count, 0)) AS likes,` becomes `v.likes,`. The two-line `LEFT JOIN interaction_signals sig ON …` goes. The row dict is unchanged.

`fetch_popular_videos`:
- Ranking subquery: `FROM videos v {error_clause} ORDER BY {POPULAR_ORDER_BY} LIMIT ?`, with the subquery's `LEFT JOIN interaction_signals sig ON …` gone.
- Outer select: `COALESCE(sig.signal_score, 0) AS interaction_signal_score,` goes, and so does the outer `LEFT JOIN interaction_signals sig ON …`. It keeps selecting `v.likes` and `v.popularity`.
- Row dict: the `"interaction_signal_score"` entry goes.
- Params are unchanged (`[error_threshold?, limit, limit]`).

`fetch_ordered_page`: `(v.likes + COALESCE(sig.likes_count, 0)) AS likes,` becomes `v.likes,`. The `interaction_signal_score` select line, the `LEFT JOIN interaction_signals sig ON …` and the row dict entry go. `v.popularity` stays in SELECT and row. The recent filter, params and paging are unchanged.

`engine/server/api/handlers/similar.py:762` (A1):

```python
                # An /api/video refresh landing between two chunks can move a row across the boundary; keep its first place.
```

### Invariants

- Every `ORDER BY` still ends on `v.video_id DESC, v.instance_domain DESC`, so OFFSET paging stays a total order.
- Row dict key sets are unchanged apart from dropping `interaction_signal_score` from the popular and ordered rows. `likes` stays an int from `videos.likes`.
- `fetch_ordered_page(…, "hot", …)` and `fetch_popular_videos` rank by the same `POPULAR_ORDER_BY` object, which keeps R3 structural.

### Seams

The data layer directly, as `tests/active/test_random_videos.py` does. Its harness copies real rows from `whitelist.db` into a tmp SQLite DB, runs `ensure_interaction_event_schema`, writes `interaction_signals` rows, and calls `fetch_ordered_page`, `fetch_popular_videos` and `fetch_random_rows`. That is the lowest layer that changes, and every caller (`_handle_ordered_feed`, the popular generator, `_fetch_random_rows`) passes these rows and orders through unchanged, per the inventory.

### Draft check

Pass 1 against R1-R5 and the plan: R1 (hot keys) ✓. R2 (popular keys) ✓. R3 (same constant for both readers) ✓. R4 (three readers select `v.likes`) ✓. R5 (constant, joins and key gone) ✓. A1 comment ✓. Out of scope untouched (`interaction_events.py`, recent order, random cache) ✓. Converged in one pass.

### Phases

#### Phase 1 — Signal-free orders
- **Kind:** code
- **Files:** `engine/server/data/random_videos.py` EDITED (`POPULAR_SIGNAL_CAP` and its comment deleted, `POPULAR_ORDER_BY` and `ORDERED_FEED_ORDER_BY["popular"]` rewritten). `engine/server/api/handlers/similar.py` EDITED (line 762 comment, A1). `tests/tmp/test_37_hot_popular_drop_local_signal_phase1.py` NEW.
- **Intent (post-phase state):** The Hot feed (`fetch_ordered_page(conn, "hot", …)`) and the Recommendations popular pool (`fetch_popular_videos`) rank embedded videos by stored `popularity`, then stored `videos.likes`, then views and the existing tie-breaks. The Popular feed (`fetch_ordered_page(conn, "popular", …)`) ranks them by stored `videos.likes`, then views and the tie-breaks. A video's `interaction_signals` row (its `signal_score` and `likes_count`) moves it in none of these orders.
- **Clauses:**
  - **C1.** Hot pages and the `fetch_popular_videos` pool rank by `popularity`, then `videos.likes`, then views, ignoring the video's `interaction_signals` `signal_score` and `likes_count`.
  - **C2.** Popular pages rank by `videos.likes`, then views, ignoring the video's `interaction_signals` `likes_count`.
- **Checkpoint and seam:** the data layer, entered directly as `tests/active/test_random_videos.py` does. That file's `_feed_db` harness (real rows copied from `whitelist.db` into a tmp DB, `ensure_interaction_event_schema`, values set per label) is copied into `working` and adjusted. Fixture: labelled videos with hand-set `popularity`, `likes` and `views`, plus `interaction_signals` rows giving (a) a low-popularity video a `signal_score` of 1000, which under today's cap lifts it by 25 past videos it should trail, (b) a video tied on `popularity` with a rival that has more crawled likes, given a `likes_count` that puts it ahead under today's code, and (c) a low-crawled-likes video a `likes_count` that leads Popular under today's code. Assertions:
  - C1: pages of 1, 2 and 3 from `fetch_ordered_page(…, "hot", …)` concatenate to a hand-derived signal-free order. For every k, `fetch_popular_videos(conn, k)` keeps exactly that order's first k.
  - C2: pages from `fetch_ordered_page(…, "popular", …)` concatenate to a hand-derived signal-free order.
  - A control asserts the `interaction_signals` rows are keyed to the fixture videos' `(video_uuid, instance_domain)`, so "ignored" cannot mean "never matched".
  - Against today's code each order places the signalled videos differently, so the test is red. A stub or hard-coded order fails the hand-derived sequence.

##### Self-check (Step 7.2, first dispatch)

Checkpoint: `tests/tmp/test_37_hot_popular_drop_local_signal_phase1.py`.

- **C1 — `test_37_…_phase1.py:110`**, pages of 1, 2 and 3 from `fetch_ordered_page(conn, "hot", …)` concatenate to `["A", "B", "C", "G", "D", "E", "F"]`. **Expected:** that list. **Wrong implementation it excludes:** today's capped signal and signal likes, which read `['D', 'A', 'C', 'B', 'G', 'E', 'F']` (observed in the run to start `D, A, C…` and end `…G, E, …`). Also excluded: a Hot order missing its `likes` key, which reads C, G, B at 20 (views, then id), and one missing `views`, which reads G before C (equal likes and date fall to `video_id DESC`, and G's id is higher).
- **C1 — `test_37_…_phase1.py:113`**, for k = 1..7, `fetch_popular_videos(conn, k)` keeps exactly `{first k of the hot list}`. **Expected:** `{A}`, `{A, B}`, … **Wrong implementation it excludes:** a pool order that keeps the signal while Hot drops it (R3 split). Under today's code k=1 keeps `{D}`.
- **C2 — `test_37_…_phase1.py:119`**, pages of 1, 2 and 3 from `fetch_ordered_page(conn, "popular", …)` concatenate to `["B", "F", "A", "C", "G", "E", "D"]`. **Expected:** that list. **Wrong implementation it excludes:** today's crawled + signal likes, which read `['E', 'C', 'B', 'F', 'A', 'G', 'D']` (observed to start `E, C, B…`). Also excluded: a Popular order missing `views`, which puts G before C.

Supporting assertions: the distinct-ids control, the signal-rows-matched control in `_signal_db`, and the `len(page) <= limit` guard.

**The ten answers**
1. **Whole claim.** C1 names Hot pages and the popular pool, each ranked by popularity, likes and views, whatever the signal score and signal likes. Hot is carried at :110 and the pool at :113. Popularity (A 30 over the 20s), likes (B over C and G), views (C over G), `signal_score` (D) and `likes_count` (C) all move a position in the expected list. C2 names likes, views and signal likes: B over F on likes, C over G on views, E held at 2. The names and docstring claim no more than that.
2. **Absence only.** No. Every clause assertion is a positive equality on a full sequence.
3. **Echoed literal.** No. The expected lists are hand-derived literals, and no production transformation runs in the test. Deleting `ORDER BY {order_by}` or any key in it turns :110/:119 red.
4. **One value.** No. Three page sizes, seven k values, and seven videos with asymmetric keys. D's signal and C's signal likes each flip a pair only if they are read.
5. **The double.** None. Real `whitelist.db` rows in a tmp DB, and real `fetch_ordered_page` and `fetch_popular_videos`.
6. **It collects.** `--collect-only -q` listed both node ids: 2 tests collected.
7. **Observed, not predicted.** The fixture and harness are copied from the durable `test_random_videos.py`, which runs green on the same calls. The expected orders are the spec (R1, R2) applied by hand to `VIDEOS`. They can't be observed before the phase lands, and the red run confirmed the fixture reaches both assertions.
8. **Red, not green.** Yes: exit 1, 2 failed.
9. **Red for the right reason.** Yes. Both controls in `_signal_db` passed. The run failed at `:110` (`At index 0 diff: 'D' != 'A'`: D rides its capped signal to the top) and at `:119` (`'E' != 'B'`: E's signal likes lead Popular). That is today's signal-reading order, not a harness defect.
10. **Observed expected output.** The rows' "wrong implementation" readings match the run's printed lists (D, A, C … G, E and E, C, B … A, G). The expected lists come from the spec, and nothing in the run contradicted them.

##### Checkpoint audit (round 1)

- `AUDIT: devsecops-test-shape-auditor — PASS. Predicted failure: line 110 at limit 1, hot reads ["D", "A", "C", "B", "G", "E", "F"] (D 10+25, C 4+10 likes); line 119 at limit 1, popular reads ["E", "C", "B", "F", "A", "G", "D"] (E 2+100, C 4+10).` No recommendations.
- `AUDIT: devsecops-test-claim-auditor — PASS.` CLAUSE MAP: 22 clauses (10 must_prove, 7 docstring, 5 name), all CARRIED. The ledger is frozen with no UNCARRIED rows.
- Recommendations:
  - **R1 (bounds, NULL counts): not taken.** NULL `popularity`, `likes` or `views` ranking is not part of R1-R5, and the removed `COALESCE` only wrapped `sig.*`, never `v.*`, so NULL handling of stored counts is unchanged by this build.
  - **R2 (whole-claim, signal as a lower tie-break): taken.** `SIGNALS` gains `"G": (1000.0, 0)`, inside the popularity-20 group, and the docstring now says "among lower and among equal popularities". A signal used as a tie-break below popularity would now lead G in that group. This answers a recorded audit finding before the test has gated.

##### Self-check (Step 7.4, after R2, before re-dispatch)

- **C1 — `:111`**, hot pages concatenate to `["A", "B", "C", "G", "D", "E", "F"]`. **Expected:** that list. **Under today's code (observed):** `['G', 'D', 'A', 'C', 'B', 'E', 'F']`. **Under a signal-as-tie-break implementation:** G ahead of B and C in the 20 group.
- **C1 — `:114`**, the `fetch_popular_videos` kept set for k = 1..7 is the first k of the hot list. **Expected:** `{A}` … **Under today's code:** k=1 keeps `{G}`.
- **C2 — `:120`**, popular pages concatenate to `["B", "F", "A", "C", "G", "E", "D"]`. **Expected:** that list. **Under today's code (observed):** `['E', 'C', 'B', 'F', 'A', 'G', 'D']`.

Questions 2-7 walked again: all clause assertions are still positive full-sequence equalities; the expected values are still hand-derived literals; the added G signal widens inputs rather than pinning one; there are no doubles; it collects (2 tests); the new expected lists are unchanged by construction, since the spec order ignores signals. **Still red for its own reason:** exit 1, both controls pass, `:111` fails with G's capped signal on top, and `:120` with E's signal likes on top.

##### Checkpoint audit (round 2)

- `AUDIT: devsecops-test-shape-auditor — PASS. Predicted failure: line 111 at limit 1, hot reads ["G", "D", "A", "C", "B", "E", "F"] (G 45, D 35, C 14 likes ahead of B 9); line 120 at limit 1, popular reads ["E", "C", "B", "F", "A", "G", "D"].` This matches the observed red exactly.
- `AUDIT: devsecops-test-claim-auditor — PASS.` 22/22 ledger rows CARRIED, and D3's widened sentence is carried at :111/:114.
- Observations (non-blocking, outside the frozen ledger, recorded and not taken): `likes_count` as a tie-break between likes and views, and `signal_score` as a tie-break after views, are not excluded by the fixture's data. Neither is a plausible route: the phase deletes every `sig` term from both orders, and Phase 2 deletes the join, after which no `sig` column can be referenced at all.

Gate cleared: both PASS, no Critical, no UNCARRIED row.

##### Changes
- `engine/server/data/random_videos.py`:
  - Deleted `POPULAR_SIGNAL_CAP` and its comment.
  - `POPULAR_ORDER_BY` is a plain string (no f-string) leading `v.popularity DESC, v.likes DESC`, then the unchanged `v.views`, `v.published_at`, `v.video_id` and `v.instance_domain`. The tie-break comment is kept.
  - `ORDERED_FEED_ORDER_BY["popular"]` leads `v.likes DESC`.
  - The `sig` joins and `likes` selects are untouched (Phase 2).
- `engine/server/api/handlers/similar.py:762`: the comment now names the `/api/video` refresh as the cause of the chunk dedup (A1). No code change.
- No file outside the phase's list was touched. No inner unit test.

##### Checkpoint outcome
`tests/tmp/test_37_hot_popular_drop_local_signal_phase1.py`: 2 passed, exit 0.

#### Phase 2 — Crawled likes on every row
- **Kind:** code
- **Files:** `engine/server/data/random_videos.py` EDITED (`fetch_random_rows`, `fetch_popular_videos`, `fetch_ordered_page`: select `v.likes`, drop `interaction_signal_score` and every `interaction_signals` join). `tests/tmp/test_37_hot_popular_drop_local_signal_phase2.py` NEW.
- **Intent (post-phase state):** Every row that `fetch_random_rows`, `fetch_popular_videos` and `fetch_ordered_page` return reports `likes` as the video's stored `videos.likes`, whatever its `interaction_signals` row holds, and no row carries an `interaction_signal_score` key.
- **Clauses:**
  - **C1.** Rows from `fetch_random_rows`, `fetch_popular_videos` and `fetch_ordered_page` (each of hot, popular and recent) report `likes` equal to the stored `videos.likes` of a video whose `interaction_signals` `likes_count` is non-zero.
  - **C2.** Rows from `fetch_popular_videos` and `fetch_ordered_page` carry no `interaction_signal_score` key.
- **Checkpoint and seam:** the same data-layer harness as Phase 1. Fixture: videos with distinct crawled `likes`, one given an `interaction_signals` row with `likes_count` 50 and `signal_score` 50.
  - C1: for each reader and order, the signalled video's row `likes` equals its crawled value and the unsignalled video's equals its own crawled value. A second video pins that the value tracks each row, not a constant.
  - C2: those rows' key sets do not contain `interaction_signal_score`. A positive control asserts each row still carries `video_id`, `likes` and (popular and ordered) `popularity`, and that the signalled video is present, so absence means "dropped" rather than "no rows".
  - Red today: `fetch_random_rows` and `fetch_ordered_page` report crawled + 50, and both popular and ordered rows carry `interaction_signal_score`.

##### Self-check (Step 7.2, first dispatch)

Checkpoint: `tests/tmp/test_37_hot_popular_drop_local_signal_phase2.py`. Probe: `tests/tmp/probe_37_phase2_likes.py`, which printed each read's `(likes, has interaction_signal_score)` per video under today's code.

- **C1 — `:87`**, for each of random, popular pool, hot, popular and recent, `{label: row["likes"]}` equals `{"X": 3, "Y": 11}`. **Expected:** `{"X": 3, "Y": 11}` on every read. **Wrong implementation it excludes:** crawled plus signal likes. Observed today: random `{'X': 53, 'Y': 11}` (the checkpoint's own failure), hot `X: 53`, popular `X: 53` (probe; recent was cut off in the probe's printout). A constant or an echoed signal-free value fails too, because Y's 11 must track Y. The popular pool already reads `X: 3` today (probe), so for that read the assertion guards against the signal returning rather than turning red.
- **C2 — `:99`**, for popular pool, hot, popular and recent, `"interaction_signal_score" not in row` for X and Y. **Expected:** absent. **Wrong implementation it excludes:** today's rows, which carry the key (observed: the checkpoint failed on `('popular pool', 'Y')` with `'interaction_signal_score': 0` in the row, and the probe shows `True` for pool, hot and popular). The controls at `:96` (both videos present) and `:98` (`video_id`, `likes` and `popularity` present) make the absence mean "dropped from a full row".

Supporting assertions: `:44` (two distinct videos) and `:67` (the signal row joins X and only X).

**The ten answers**
1. **Whole claim.** C1 names three functions and three orders, and `_reads` covers all five reads. The name and docstring claim the crawled count for X (3) and Y (11), both asserted. C2 names popular and ordered rows, which is four reads, all asserted, plus the kept keys in the docstring (controls at :98). `fetch_random_rows` never carried the key, so C2 does not claim it, and the loop skips it.
2. **Absence only.** C2 is a negative assertion, paired with positive controls in the same loop: both labels returned (:96) and a full row (:98). Deleting the read makes :96 fail.
3. **Echoed literal.** No. VIDEOS' likes are written into the DB and read back through production SQL. The signal of 50 is the distractor, and deleting the `v.likes` select (or selecting the sum) turns :87 red. It is observed red today on random.
4. **One value.** No. Two videos with different crawled likes, one with a signal and one without, over five reads.
5. **The double.** None. Real rows in a tmp DB, and real functions.
6. **It collects.** 2 tests collected.
7. **Observed, not predicted.** Today's readings come from the probe run and the checkpoint run. The expected values are the stored crawled likes, which the popular pool already reports today (observed `X: 3`), so the shape "crawled likes on a row" has been seen from real code.
8. **Red, not green.** Yes: exit 1, 2 failed.
9. **Red for the right reason.** Yes. Controls :44, :67, :96 and :98 passed. `:87` failed on `random` with `{'X': 53, 'Y': 11}`, and `:99` failed on `('popular pool', 'Y')` with the key present. Both are the unbuilt phase.
10. **Observed expected output.** The rows' today-readings are copied from the runs above. Nothing contradicted the expected values.

##### Checkpoint audit (round 1)

- `AUDIT: devsecops-test-shape-auditor — PASS. Predicted failure: line 87 on "random", {"X": 53, "Y": 11} instead of {"X": 3, "Y": 11}; line 99 on "popular pool", the first row still carries interaction_signal_score.` No recommendations.
- `AUDIT: devsecops-test-claim-auditor — PASS.` CLAUSE MAP: 19 clauses (7 must_prove, 9 docstring, 3 name). This frozen ledger has one UNCARRIED row: D2.
- Ledger:
  - **D2 (docstring: the summary line claimed random rows carry no signal score): fixed by narrowing.** The summary line now reads "…and the popular and ordered rows carry no interaction signal score", which matches C2 and bullet 2. `fetch_random_rows` never selected the key, and no requirement asks for it.
- Recommendations:
  - **R1 (whole-claim, D2):** handled above.
  - **R2 (bounds: stored likes of 0 or NULL): not taken.** A NULL crawled count gives NULL under both today's sum and the pass-through (`NULL + 50` is NULL), so it cannot separate them. A crawled 0 is just another value like 3. Paging offsets are Phase 1's concern.
  - **R3 (abnormal path: error threshold): taken.** `_reads` now runs every read with `error_threshold` None and 3 (`THRESHOLDS`). Both videos have `error_count` 0, so both stay while each read builds its filtered WHERE and parameter list. The docstring bullets now say "with no error threshold and with one". This answers a recorded finding before the test gated.

##### Self-check (Step 7.4, after remediation, before re-dispatch)

- **C1 — `:92`**, for each (read, threshold) in random, popular pool, hot, popular and recent × {None, 3}, `{label: likes}` equals `{"X": 3, "Y": 11}`. **Expected:** that on all ten reads. **Today (observed):** `('random', None)` reads `{'Y': 11, 'X': 53}`. The earlier probe showed hot and popular `X: 53`, and the pool `X: 3`.
- **C2 — `:104`**, for the eight popular and ordered reads × thresholds, the key is absent. **Expected:** absent. **Today (observed):** present, failing on `(('popular pool', None), 'Y')` with `'interaction_signal_score': 0`.

Questions 2-7 walked again: C2's absence is still paired with the :101/:103 controls in the same loop; no echoed value; two videos over ten reads; no doubles; it collects (2 tests); today's readings come from the run. **Still red for its own reason:** exit 1, controls :46 and :69 pass, `:92` fails on random's 53, and `:104` fails on the pool's key.

##### Checkpoint audit (round 2)

- `AUDIT: devsecops-test-shape-auditor — PASS. Predicted failure: line 92 on ("random", None), {"X": 53, "Y": 11}; line 104 on ("popular pool", None) after the :101/:103 controls pass, the key still present.` This matches the observed red.
- `AUDIT: devsecops-test-claim-auditor — PASS.` 19/19 ledger rows CARRIED, with D2 carried at :104 after the narrowing.
- Observations (non-blocking): D2 was fixed by narrowing, so random rows' key absence is unasserted. That is correct because C2 never named the random read, which never had the key. The threshold clause added by R3 is carried at :92/:104.

Gate cleared: both PASS, no Critical, no UNCARRIED row.

##### Changes
- `engine/server/data/random_videos.py`:
  - `fetch_random_rows`: selects `v.likes`; its `LEFT JOIN interaction_signals sig` is removed.
  - `fetch_popular_videos`: the ranking subquery and the outer select each lose their `LEFT JOIN interaction_signals sig`; `COALESCE(sig.signal_score, 0) AS interaction_signal_score` and the row's `interaction_signal_score` entry are removed.
  - `fetch_ordered_page`: selects `v.likes`; the `interaction_signal_score` select line, its row entry and the `LEFT JOIN interaction_signals sig` are removed.
  - A search of the file for `sig`, `interaction_signal` and `SIGNAL` returns no matches.
- No file outside the phase's list was touched. No inner unit test.

##### Checkpoint outcome
`tests/tmp/test_37_hot_popular_drop_local_signal_phase2.py`: 2 passed, exit 0. Phase 1's checkpoint re-run: 2 passed.

#### Coordination and rationale
- **No operator coordination needed.** Everything runs against tmp copies of `whitelist.db` rows. Seeing it in the browser needs `bash scripts/run-services.sh restart` after the build, which is not a gate.
- **Why two phases.** R1-R5 cut into four observable facts: two about ordering (Hot and the popular pool, then Popular) and two about row contents (likes, the dropped key). At two clauses per phase that makes two phases, and it matches the code: Phase 1 touches only the order constants, Phase 2 only the SELECTs and joins, which Phase 1 must leave in place while `likes` still reads `sig`.
- **R5 without a clause.** `POPULAR_SIGNAL_CAP` and the joins going have no observable of their own beyond the clauses above. The Step 8 search for `sig`, `interaction_signals` and `POPULAR_SIGNAL_CAP` in `random_videos.py` records their removal.

## Inner unit tests

None. Both phases' checkpoints expressed every behaviour.

## Close

### Refactor pass
None made. The production change is pure deletion (a constant, two order terms, six join/select lines, two row keys), leaving no duplication or hard-coding to remove. `POPULAR_ORDER_BY` became a plain string in Phase 1, since nothing is interpolated. Nothing needed new behaviour.

### Clause accounting
- **P1C1:** carried in the last clean audit of `test_37_…_phase1.py` (round 2, rows C1a-C1h).
- **P1C2:** carried (round 2, rows C2a-C2b).
- **P2C1:** carried in the last clean audit of `test_37_…_phase2.py` (round 2, rows C1a-C1e).
- **P2C2:** carried (round 2, rows C2a-C2b).
- **R5 (no clause):** a search of `engine/server/data/random_videos.py` for `sig`, `interaction_signal` and `SIGNAL` returns no matches.

### `--compare` and reds
First full `--compare` (8 of 30 groups selected): 195 passed, 8 failed.
- **7 in `tests/active/test_random_videos.py`: the test was at fault, not the implementation.** They pinned behaviour this build's confirmed requirements remove. Retired per the operator's decision ("Retire all four functions now, restore paging coverage at harvest") into `tests/archive/37_local_signal/test_random_videos.py`, with a header naming each function and its conflict:
  - `test_an_undone_like_leaves_the_random_row_s_likes_at_the_crawled_count` (R4)
  - `test_an_undone_like_keeps_the_popular_order_of_two_tied_videos` (R5 key)
  - `test_the_popular_order_caps_the_interaction_signal` (R1, R5)
  - `test_consecutive_pages_concatenate_into_the_order_s_total_sort` (R1, R2 expectations; its recent, tie-break and threshold coverage goes back in at harvest as a COMBINE)

  `test_a_page_holds_exactly_the_embedded_rows_under_the_threshold` stays active, with its helpers and a docstring narrowed to it: 6 passed. The pre-retirement copy is at `.scratch/test_random_videos.pre37.py`.
- **1 in `tests/active/test_similar.py::test_home_and_search_are_unchanged_by_an_upnext_fallback_and_nprobe_is_restored`**, at `:883` `len(home["rows"]) == 48`, which read 47 on a keyless home page. **Not reproduced:** it passed 3/3 alone and in 2/2 full `test_similar.py` runs (42 passed each). Inspecting the test first: it asserts exactly `BATCH_SIZE` on a fresh random home draw, and the plan 09 memory `feed-page-sizes-and-request-body-sizes` measured home pages at 45-48 rows. Read as a pre-existing intermittent assertion under suite load. It could be linked to this build only through the popular layer's pool (20% of a keyless page), whose membership changes only for videos with signal rows. **Finding, not fixed:** out of scope, and the test is left untouched.

Second `--compare` after retirement: exit 0, 16 passed in the 2 changed groups, 28 unchanged groups answered green by the record, `nothing moved against the previous record`. **The full suite is green.**
