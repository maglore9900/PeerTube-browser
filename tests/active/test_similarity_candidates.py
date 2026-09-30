"""With the NSFW filter on, the up-next pool in `data/similarity_candidates.py` refills past NSFW hits instead of coming back short; with it off, it is unchanged.

- `get_upnext_candidates` with no cache entry, a per-author cap of 1 and target pool 5, over an ANN script whose step 2 adds only NSFW hits and whose step 3 adds Y on NSFW X1's channel. Filtered, it steps (1,10), (2,20), (4,40), (8,80) with pool counts 1, 1, 2, 4, stops at the caps, and returns A, Y, B, C. Unfiltered, it steps (1,10), (2,20), (4,40) with counts 2, 3, 3 and returns X1, A, X2.
- The same ladder when step 2 adds no hit: filtered, it stops after (2,20) with counts 1, 1 and returns A. Unfiltered, it stops at the same step with counts 2, 2 and returns X1, A.
- One ANN step with top_k 3, target 3 and a per-author cap of 1, where NSFW X1 outscores A on A's channel and NSFW X2 also outscores A. Filtered, it returns A, B, C with a pool count of 3. Unfiltered, it returns X1, X2, B.

The Engine db is an in-memory SQLite table. `data.ann` is replaced in `sys.modules` by a stub `search_similar_above`, because the real module needs numpy and faiss, which this interpreter lacks. The stub returns scripted hits unfiltered, as the real search does. The server's moderation switches are off, so only the NSFW filter, the author cap and the pool count shape the rows.
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

from data import similarity_candidates  # noqa: E402

HOST = "h.example"
THRESHOLD = 3


def _video_db(videos: list[tuple[str, str]]) -> sqlite3.Connection:
    """An in-memory Engine db holding `videos` as (label, channel), embedded in that order.

    A label starting X is flagged nsfw = 1 and one starting R sits at THRESHOLD errors; the rest alternate nsfw 0 and NULL.
    """
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute("CREATE TABLE videos (video_id TEXT NOT NULL, video_uuid TEXT, video_numeric_id INTEGER, instance_domain TEXT NOT NULL, channel_id TEXT, channel_name TEXT, channel_url TEXT, account_name TEXT, account_url TEXT, title TEXT, description TEXT, tags_json TEXT, category TEXT, published_at INTEGER, video_url TEXT, duration INTEGER, thumbnail_url TEXT, embed_path TEXT, views INTEGER, likes INTEGER, dislikes INTEGER, comments_count INTEGER, nsfw INTEGER, preview_path TEXT, popularity REAL NOT NULL DEFAULT 0, last_checked_at INTEGER NOT NULL, error_count INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (video_id, instance_domain))")
    db.execute("CREATE TABLE video_embeddings (video_id TEXT, instance_domain TEXT, embedding BLOB, embedding_dim INTEGER, model_name TEXT, PRIMARY KEY (video_id, instance_domain))")
    db.execute("CREATE TABLE channels (channel_id TEXT, instance_domain TEXT, display_name TEXT, avatar_url TEXT)")
    for index, (label, channel) in enumerate(videos):
        nsfw = 1 if label.startswith("X") else (0 if index % 2 else None)
        db.execute(
            "INSERT INTO videos (video_id, video_uuid, instance_domain, channel_id, nsfw, last_checked_at, error_count) VALUES (?, ?, ?, ?, ?, 0, ?)",
            (label, f"u-{label}", HOST, channel, nsfw, THRESHOLD if label.startswith("R") else 0),
        )
        db.execute("INSERT INTO video_embeddings VALUES (?, ?, x'00', 3, 'm')", (label, HOST))
    db.commit()
    return db


def _labels(rows: list[dict]) -> list[str]:
    return [row["video_id"] for row in rows]


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
    db = _video_db(list({label: channel for hits in script.values() for label, _, channel in hits}.items()))
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
    # Filtered: step 2 adds no row but a hit, so the ladder goes on; NSFW rows are out of every count and of the channel cap, so Y shows; the caps end it short of 5. Unfiltered: step 3 adds a hit but no row, so it stops there.
    assert called == [step[:2] for step in steps]
    assert reported == steps
    assert rows == pool


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
    assert called == [step[:2] for step in steps]  # the raw hit count stopped growing, so the ladder stops below the caps
    assert reported == steps
    assert rows == pool


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
    assert reported == [(1, 10, 3)]
    assert rows == pool  # filtered, X1 does not take A's channel slot and X1, X2 do not use up top_k; unfiltered, the NSFW hits take both
