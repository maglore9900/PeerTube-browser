"""With the NSFW filter on, the random-cache draw and the up-next pool refill past NSFW rows instead of coming back short; with it off, both are today's.

- fetch_random_rows_from_cache(include_nsfw=False), limit 4, over the cache X1 A X2 B C X3 D E with windows starting at 0, 2 and 4: three draws, and the page is A, B, C, D. The rows are in draw order, B and C are not repeated from the overlapping window, and E is cut at the limit.
- With one allowed row per window and a limit of RANDOM_CACHE_NSFW_MAX_DRAWS + 2, it makes exactly RANDOM_CACHE_NSFW_MAX_DRAWS draws, although the next window would add an unseen allowed row. The page is those draws' allowed rows.
- Over a 3-row cache (X1 A X2) at limit 5 it makes two draws of that same whole window and returns A.
- Over an all-NSFW 8-row cache it returns [] after three draws (windows 0, 4, then 0 again, which adds no unseen rowid). The same cache with the filter off returns X1..X4.
- include_nsfw=True and the default call each make one draw of A X1 A R and return A, X1, A. The duplicate is kept, NSFW is included, and the errored R leaves the page short without a redraw.
- get_upnext_candidates with no cache entry, a per-author cap of 1 and target pool 5, over an ANN script whose step 2 adds only NSFW hits and whose step 3 adds Y on NSFW X1's channel. Filtered, it steps (1,10), (2,20), (4,40), (8,80) with pool counts 1, 1, 2, 4, stops at the caps, and returns A, Y, B, C. Unfiltered, it steps (1,10), (2,20), (4,40) with counts 2, 3, 3 and returns X1, A, X2, which is today's.
- The same ladder when step 2 adds no hit: filtered, it stops after (2,20) with counts 1, 1 and returns A. Unfiltered, it stops at the same step with counts 2, 2 and returns X1, A.
- One ANN step with top_k 3, target 3 and a per-author cap of 1, where NSFW X1 outscores A on A's channel and NSFW X2 also outscores A. Filtered, it returns A, B, C with a pool count of 3. Unfiltered, it returns X1, X2, B, which is today's.

The Engine db and the random cache are in-memory SQLite tables. The owner is a SimpleNamespace holding `random_cache_db`, `random_cache_lock`, `db` and `db_lock`, as `tests/active/test_random_cache.py` uses. The random-cache window start comes from `random.randint`. It is scripted through `data.random_cache.random`, and draws are counted by wrapping `fetch_random_rowids`. For up-next, `data.ann` is replaced in `sys.modules` by a stub `search_similar_above`: the real module needs numpy and faiss, which this interpreter lacks. The stub returns scripted hits unfiltered, as the real search does. The server's moderation switches are off, so only the NSFW filter, the author cap and the pool count shape the rows.
"""
from __future__ import annotations

import sqlite3
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
SERVER_DIR = ROOT / "engine" / "server"
# `data` imports `recommendations`, which lives under `api`, as the Engine's server.py runs it.
for path in (SERVER_DIR, SERVER_DIR / "api"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from data import random_cache, random_videos, similarity_candidates  # noqa: E402

HOST = "h.example"
THRESHOLD = 3


def _video_db(videos: list[tuple[str, str]]) -> tuple[sqlite3.Connection, dict[str, int]]:
    """An in-memory Engine db holding `videos` as (label, channel), embedded in that order, and each label's embedding rowid.

    A label starting X is flagged nsfw = 1 and one starting R sits at THRESHOLD errors; the rest alternate nsfw 0 and NULL.
    """
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute("CREATE TABLE videos (video_id TEXT NOT NULL, video_uuid TEXT, video_numeric_id INTEGER, instance_domain TEXT NOT NULL, channel_id TEXT, channel_name TEXT, channel_url TEXT, account_name TEXT, account_url TEXT, title TEXT, description TEXT, tags_json TEXT, category TEXT, published_at INTEGER, video_url TEXT, duration INTEGER, thumbnail_url TEXT, embed_path TEXT, views INTEGER, likes INTEGER, dislikes INTEGER, comments_count INTEGER, nsfw INTEGER, preview_path TEXT, popularity REAL NOT NULL DEFAULT 0, last_checked_at INTEGER NOT NULL, error_count INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (video_id, instance_domain))")
    db.execute("CREATE TABLE video_embeddings (video_id TEXT, instance_domain TEXT, embedding BLOB, embedding_dim INTEGER, model_name TEXT, PRIMARY KEY (video_id, instance_domain))")
    db.execute("CREATE TABLE channels (channel_id TEXT, instance_domain TEXT, display_name TEXT, avatar_url TEXT)")
    rowids: dict[str, int] = {}
    for index, (label, channel) in enumerate(videos):
        nsfw = 1 if label.startswith("X") else (0 if index % 2 else None)
        db.execute(
            "INSERT INTO videos (video_id, video_uuid, instance_domain, channel_id, nsfw, last_checked_at, error_count) VALUES (?, ?, ?, ?, ?, 0, ?)",
            (label, f"u-{label}", HOST, channel, nsfw, THRESHOLD if label.startswith("R") else 0),
        )
        rowids[label] = db.execute("INSERT INTO video_embeddings VALUES (?, ?, x'00', 3, 'm')", (label, HOST)).lastrowid
    db.commit()
    return db, rowids


def _cache_owner(monkeypatch: pytest.MonkeyPatch, cache: list[str], offsets: list[int]) -> tuple[SimpleNamespace, list[list[str]]]:
    """An owner serving a random cache whose positions hold `cache` in order, and the list each draw appends its window to, as labels.

    Draws start at `offsets` in turn; a draw past them fails the test.
    """
    db, rowids = _video_db([(label, f"ch-{label}") for label in dict.fromkeys(cache)])
    labels = {rowid: label for label, rowid in rowids.items()}
    cache_db = sqlite3.connect(":memory:")
    cache_db.row_factory = sqlite3.Row
    cache_db.execute("CREATE TABLE random_rowids (position INTEGER PRIMARY KEY, video_rowid INTEGER NOT NULL)")
    cache_db.executemany("INSERT INTO random_rowids (position, video_rowid) VALUES (?, ?)", [(position, rowids[label]) for position, label in enumerate(cache, start=1)])
    cache_db.commit()
    scripted = list(offsets)

    def randint(low: int, high: int) -> int:
        assert scripted, "a draw past the scripted windows"
        offset = scripted.pop(0)
        assert low <= offset <= high, (low, high, offset)
        return offset

    # The window start is the draw's random source; scripting it fixes which cache positions each draw reads.
    monkeypatch.setattr(random_cache, "random", SimpleNamespace(randint=randint))
    draws: list[list[str]] = []
    real_fetch = random_cache.fetch_random_rowids

    def counting_fetch(cache_conn: sqlite3.Connection, limit: int) -> list[int]:
        window = real_fetch(cache_conn, limit)
        draws.append([labels[rowid] for rowid in window])
        return window

    monkeypatch.setattr(random_videos, "fetch_random_rowids", counting_fetch)
    return SimpleNamespace(random_cache_db=cache_db, random_cache_lock=threading.Lock(), db=db, db_lock=threading.Lock()), draws


def _labels(rows: list[dict]) -> list[str]:
    return [row["video_id"] for row in rows]


def test_filter_on_redraws_past_nsfw_and_seen_rowids_until_the_page_is_full(monkeypatch):
    owner, draws = _cache_owner(monkeypatch, ["X1", "A", "X2", "B", "C", "X3", "D", "E"], [0, 2, 4])
    rows = random_videos.fetch_random_rows_from_cache(owner, 4, include_nsfw=False)
    assert draws == [["X1", "A", "X2", "B"], ["X2", "B", "C", "X3"], ["C", "X3", "D", "E"]]  # C1: short after two draws, so a third, and none once the page is full
    assert _labels(rows) == ["A", "B", "C", "D"]  # C1: draw order, B and C not repeated from the overlap, E cut at the limit


def test_filter_on_stops_at_the_draw_cap_with_the_page_still_short(monkeypatch):
    cap = random_videos.RANDOM_CACHE_NSFW_MAX_DRAWS
    # One allowed row per window and a limit two above the cap, so neither the cap's draws nor one more fill the page: only the cap stops the loop.
    limit = cap + 2
    windows = [[f"X{k}_{j}" for j in range(limit - 1)] for k in range(cap + 1)]
    for k, window in enumerate(windows):
        window.insert(1, f"A{k}")
    owner, draws = _cache_owner(monkeypatch, [label for window in windows for label in window], [k * limit for k in range(cap + 1)])
    rows = random_videos.fetch_random_rows_from_cache(owner, limit, include_nsfw=False)
    assert draws == windows[:cap]  # C1: exactly the cap, although the next window holds an unseen allowed row
    assert _labels(rows) == [f"A{k}" for k in range(cap)]  # C1


def test_filter_on_stops_after_a_draw_adds_no_unseen_rowid(monkeypatch):
    # No bigger than the limit, so every draw reads the whole cache from position 1 without a random start.
    owner, draws = _cache_owner(monkeypatch, ["X1", "A", "X2"], [])
    rows = random_videos.fetch_random_rows_from_cache(owner, 5, include_nsfw=False)
    assert draws == [["X1", "A", "X2"], ["X1", "A", "X2"]]  # C1: the second draw added nothing unseen, so no third
    assert _labels(rows) == ["A"]  # C1


def test_filter_on_returns_nothing_from_an_all_nsfw_cache(monkeypatch):
    cache = [f"X{index}" for index in range(1, 9)]
    owner, _ = _cache_owner(monkeypatch, cache, [0])
    assert _labels(random_videos.fetch_random_rows_from_cache(owner, 4, include_nsfw=True)) == cache[:4]  # control: the same cache serves rows with the filter off
    owner, draws = _cache_owner(monkeypatch, cache, [0, 4, 0])
    rows = random_videos.fetch_random_rows_from_cache(owner, 4, include_nsfw=False)
    assert rows == []  # C1
    assert draws == [cache[:4], cache[4:], cache[:4]]  # C1: redrew while a draw added unseen rowids, stopped at the first that added none


@pytest.mark.parametrize("flag", [{"include_nsfw": True}, {}], ids=["include_nsfw", "default"])
def test_filter_off_makes_one_draw_and_returns_its_rows_duplicates_included(monkeypatch, flag):
    owner, draws = _cache_owner(monkeypatch, ["A", "X1", "A", "R", "B", "C", "D", "E"], [0, 4])
    rows = random_videos.fetch_random_rows_from_cache(owner, 4, error_threshold=THRESHOLD, **flag)
    assert draws == [["A", "X1", "A", "R"]]  # C1: one draw, although R's error count leaves the page short
    assert _labels(rows) == ["A", "X1", "A"]  # C1: today's rows for that window


# Every up-next run starts at (1, 10) and doubles to the (8, 80) caps; the floors keep all scripted hits in the core pool.
UPNEXT_POLICY = {"top_k": 48, "target_min_pool": 5, "nprobe": 1, "search_limit": 10, "max_nprobe": 8, "max_search_limit": 80, "min_score": 0.5, "tail_min_score": 0.3, "cache_limit": 20}
STEP_1 = [("X1", 0.95, "ch-X"), ("A", 0.9, "ch-A")]
# Its only new hit is NSFW.
STEP_2 = STEP_1 + [("X2", 0.85, "ch-X2")]
# Y shares NSFW X1's channel, so under a cap of 1 it shows only once X1 is filtered out.
STEP_3 = STEP_2 + [("Y", 0.8, "ch-X")]
STEP_4 = STEP_3 + [("B", 0.78, "ch-B"), ("C", 0.76, "ch-C")]
LADDER = {(1, 10): STEP_1, (2, 20): STEP_2, (4, 40): STEP_3, (8, 80): STEP_4}
# Step 2 finds no hit step 1 did not.
STALLED = {(1, 10): STEP_1, (2, 20): STEP_1, (4, 40): STEP_4, (8, 80): STEP_4}
# NSFW X1 outscores A on A's channel, and NSFW X2 outscores A too.
CAPPED = {(1, 10): [("X1", 0.95, "ch-A"), ("X2", 0.92, "ch-X2"), ("A", 0.9, "ch-A"), ("B", 0.85, "ch-B"), ("C", 0.8, "ch-C"), ("D", 0.75, "ch-D")]}


def _upnext(monkeypatch: pytest.MonkeyPatch, script: dict[tuple[int, int], list[tuple[str, float, str]]], include_nsfw: bool, author_limit: int, **policy) -> tuple[list[tuple[int, int]], list[str], list[tuple[int, int, int]]]:
    """Run get_upnext_candidates for a seed with no cache entry, the ANN search answering each (nprobe, search_limit) from `script` as (label, score, channel) hits.

    :returns: the steps the search was called at, the pool's labels, and the (nprobe, search_limit, pool count) steps the stats report.
    """
    db, _ = _video_db(list({label: channel for hits in script.values() for label, _, channel in hits}.items()))
    called: list[tuple[int, int]] = []

    def search_similar_above(server, seed, nprobe, search_limit, min_score):
        called.append((nprobe, search_limit))
        return [{"video_id": label, "instance_domain": HOST, "score": score} for label, score, _ in script[(nprobe, search_limit)]], None

    monkeypatch.setitem(sys.modules, "data.ann", SimpleNamespace(search_similar_above=search_similar_above))
    server = SimpleNamespace(db=db, db_lock=threading.Lock(), similarity_max_per_author=author_limit, enable_instance_ignore=False, enable_channel_blocklist=False)
    seed = {"video_id": "S", "instance_domain": HOST, "channel_id": "ch-S", "embedding": [0.0]}
    rows, stats = similarity_candidates.get_upnext_candidates(server, seed, similarity_candidates.UpnextPoolPolicy(**{**UPNEXT_POLICY, **policy}, include_nsfw=include_nsfw))
    return called, _labels(rows), stats["steps"]


@pytest.mark.parametrize(
    "include_nsfw, steps, pool",
    [
        (False, [(1, 10, 1), (2, 20, 1), (4, 40, 2), (8, 80, 4)], ["A", "Y", "B", "C"]),
        (True, [(1, 10, 2), (2, 20, 3), (4, 40, 3)], ["X1", "A", "X2"]),
    ],
    ids=["filtered", "unfiltered"],
)
def test_upnext_ladder_widens_past_an_all_nsfw_step_to_the_caps_when_filtered(monkeypatch, include_nsfw, steps, pool):
    called, rows, reported = _upnext(monkeypatch, LADDER, include_nsfw, 1)
    # Filtered: step 2 adds no row but a hit, so the ladder goes on; NSFW rows are out of every count and of the channel cap, so Y shows; the caps end it short of 5. Unfiltered: step 3 adds a hit but no row, so it stops there, as today.
    assert called == [step[:2] for step in steps]  # C2
    assert reported == steps  # C2
    assert rows == pool  # C2


@pytest.mark.parametrize(
    "include_nsfw, steps, pool",
    [
        (False, [(1, 10, 1), (2, 20, 1)], ["A"]),
        (True, [(1, 10, 2), (2, 20, 2)], ["X1", "A"]),
    ],
    ids=["filtered", "unfiltered"],
)
def test_upnext_ladder_stops_when_a_step_adds_no_hit(monkeypatch, include_nsfw, steps, pool):
    called, rows, reported = _upnext(monkeypatch, STALLED, include_nsfw, 0)
    assert called == [step[:2] for step in steps]  # C2: the raw hit count stopped growing, so the ladder stops below the caps
    assert reported == steps  # C2
    assert rows == pool  # C2


@pytest.mark.parametrize(
    "include_nsfw, pool",
    [
        (False, ["A", "B", "C"]),
        (True, ["X1", "X2", "B"]),
    ],
    ids=["filtered", "unfiltered"],
)
def test_upnext_nsfw_hits_take_no_author_slot_and_no_pool_place(monkeypatch, include_nsfw, pool):
    called, rows, reported = _upnext(monkeypatch, CAPPED, include_nsfw, 1, top_k=3, target_min_pool=3)
    assert called == [(1, 10)]  # control: one step fills the target, so the pool below comes from these hits alone
    assert reported == [(1, 10, 3)]  # C2
    assert rows == pool  # C2: filtered, X1 does not take A's channel slot and X1, X2 do not use up top_k; unfiltered, today's pool
