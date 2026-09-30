"""With `include_nsfw=False` the Engine's listing reads leave out every `nsfw = 1` video inside their SQL, so LIMIT and OFFSET count only the rows that are allowed.

- fetch_metadata, fetch_metadata_by_ids, fetch_random_rows, fetch_recent_videos, fetch_popular_videos and fetch_ordered_page for hot, popular and recent, each with no error threshold and with a threshold of 3: the default call and `include_nsfw=True` return all nine videos (E dropped under the threshold), and `include_nsfw=False` returns exactly A, B, C, D and E (E dropped under the threshold). Those rows' `nsfw` values are 0 and NULL, and none is 1. The id lookup is asked for its pairs with NSFW ones first, in the middle and last in the chunk. lexical_candidates, which takes no error threshold, gives the same with no threshold.
- fetch_metadata_by_uuids is unchanged: with and without the threshold it still returns the NSFW videos.
- NSFW videos head Hot, Popular, Recent and FTS relevance, and one more sits mid-order. With the filter on, fetch_popular_videos, fetch_recent_videos and lexical_candidates at LIMIT n return the first n allowed videos for every n up to the allowed count, and fetch_random_rows at LIMIT (allowed count) returns every allowed video on each of five draws. fetch_ordered_page pages of 1, 2 and 3 rows, fetched at increasing offsets to one past the end, concatenate with no repeat into the single filtered page, and that page is the allowed videos in order.
- search_videos with the filter on reports a `total` of 5, the allowed matches, against 9 unfiltered; pages 1 and 2 of two rows are A, B then C, D; and a candidate pool of 2 gives a total of 2 and rows A, B.

Every read runs on an in-memory SQLite database with the Engine's `videos`, `video_embeddings`, `channels` and external-content `videos_fts` tables, built from `_statements()`. `data.search` imports numpy and faiss, which only the Engine's environment has, so the search reads run in a child on the Engine's interpreter. That child builds the same database from the same statements and reports back as JSON. It has no query encoder, the path search already takes when the model is unavailable, so search_videos ranks the keyword half alone.
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SERVER_DIR = ROOT / "engine" / "server"
ENGINE_PY = ROOT / "engine" / ".pixi" / "envs" / "default" / "bin" / "python"
# `data` imports `recommendations`, which lives under `api`, as the Engine's server.py runs it.
for path in (SERVER_DIR, SERVER_DIR / "api"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from data import metadata, random_videos  # noqa: E402

HOST = "h.example"
THRESHOLD = 3
DAY_MS = 86_400_000
PAST_MS = 1_700_000_000_000
# One rank for every order the phase reads: the video at rank r has popularity and likes 100 - 10r, views 1000 - 100r, is r days old, and has 10 - r "cats" in a ten-word title, so Hot, Popular, Recent and FTS relevance all run in this sequence. NSFW rows lead it, sit in its middle and end it.
ORDER = ("X1", "X2", "A", "B", "X3", "C", "D", "E", "X4")
NSFW = {"X1": 1, "X2": 1, "A": 0, "B": None, "X3": 1, "C": 0, "D": None, "E": 0, "X4": 1}
# E sits at the threshold, so a threshold drops it whatever the flag.
ERRORED = "E"
# Derived by hand from ORDER, NSFW and ERRORED, keyed by (error_threshold, include_nsfw).
EXPECTED = {
    (None, True): ["X1", "X2", "A", "B", "X3", "C", "D", "E", "X4"],
    (None, False): ["A", "B", "C", "D", "E"],
    (THRESHOLD, True): ["X1", "X2", "A", "B", "X3", "C", "D", "X4"],
    (THRESHOLD, False): ["A", "B", "C", "D"],
}
# The id lookup's pairs: NSFW first, in the middle and last, so a predicate bound to only one pair of the OR lets the others through.
PAIR_ORDER = ("X1", "A", "B", "X2", "X3", "C", "D", "E", "X4")


def _statements() -> list[tuple[str, list]]:
    """The statements that build the fixture database, run here and in the search child alike."""
    statements: list[tuple[str, list]] = [
        ("CREATE TABLE videos (video_id TEXT NOT NULL, video_uuid TEXT, video_numeric_id INTEGER, instance_domain TEXT NOT NULL, channel_id TEXT, channel_name TEXT, channel_url TEXT, account_name TEXT, account_url TEXT, title TEXT, description TEXT, tags_json TEXT, category TEXT, published_at INTEGER, video_url TEXT, duration INTEGER, thumbnail_url TEXT, embed_path TEXT, views INTEGER, likes INTEGER, dislikes INTEGER, comments_count INTEGER, nsfw INTEGER, preview_path TEXT, popularity REAL NOT NULL DEFAULT 0, last_checked_at INTEGER NOT NULL, error_count INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (video_id, instance_domain))", []),
        ("CREATE TABLE video_embeddings (video_id TEXT, instance_domain TEXT, embedding BLOB, embedding_dim INTEGER, model_name TEXT, PRIMARY KEY (video_id, instance_domain))", []),
        ("CREATE TABLE channels (channel_id TEXT, instance_domain TEXT, display_name TEXT, avatar_url TEXT)", []),
        ("CREATE VIRTUAL TABLE videos_fts USING fts5(title, description, tags_json, category, channel_name, content='videos', content_rowid='rowid')", []),
    ]
    # Stored last rank first, so storage order is never the order under test.
    for label in reversed(ORDER):
        rank = ORDER.index(label) + 1
        title = " ".join(["cats"] * (10 - rank) + [f"w{label.lower()}{i}" for i in range(rank)])
        statements.append((
            "INSERT INTO videos (video_id, video_uuid, instance_domain, channel_id, title, published_at, views, likes, nsfw, popularity, last_checked_at, error_count) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)",
            [label, f"u-{label}", HOST, f"ch-{label}", title, PAST_MS - rank * DAY_MS, 1000 - 100 * rank, 100 - 10 * rank, NSFW[label], 100.0 - 10 * rank, THRESHOLD if label == ERRORED else 0],
        ))
        statements.append(("INSERT INTO video_embeddings VALUES (?, ?, x'00', 3, 'm')", [label, HOST]))
    statements.append(("INSERT INTO videos_fts(videos_fts) VALUES('rebuild')", []))
    return statements


@pytest.fixture
def conn():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    for sql, params in _statements():
        db.execute(sql, params)
    db.commit()
    yield db
    db.close()


def _metadata(conn: sqlite3.Connection, threshold: int | None, **flag) -> list[dict]:
    rowids = [row[0] for row in conn.execute("SELECT rowid FROM video_embeddings")]
    return list(metadata.fetch_metadata(conn, rowids, error_threshold=threshold, **flag).values())


def _by_ids(conn: sqlite3.Connection, threshold: int | None, **flag) -> list[dict]:
    entries = [{"video_id": label, "instance_domain": HOST} for label in PAIR_ORDER]
    return list(metadata.fetch_metadata_by_ids(conn, entries, error_threshold=threshold, **flag).values())


# Each read at a limit past the nine videos, so it returns every row it may serve.
READS = {
    "fetch_metadata": _metadata,
    "fetch_metadata_by_ids": _by_ids,
    "fetch_random_rows": lambda conn, threshold, **flag: random_videos.fetch_random_rows(conn, 100, error_threshold=threshold, **flag),
    "fetch_recent_videos": lambda conn, threshold, **flag: random_videos.fetch_recent_videos(conn, 100, error_threshold=threshold, **flag),
    "fetch_popular_videos": lambda conn, threshold, **flag: random_videos.fetch_popular_videos(conn, 100, error_threshold=threshold, **flag),
    "fetch_ordered_page:hot": lambda conn, threshold, **flag: random_videos.fetch_ordered_page(conn, "hot", 100, 0, error_threshold=threshold, **flag),
    "fetch_ordered_page:popular": lambda conn, threshold, **flag: random_videos.fetch_ordered_page(conn, "popular", 100, 0, error_threshold=threshold, **flag),
    "fetch_ordered_page:recent": lambda conn, threshold, **flag: random_videos.fetch_ordered_page(conn, "recent", 100, 0, error_threshold=threshold, **flag),
}
# Reads whose row order is their contract; the rest are compared in ORDER's sequence, duplicates kept.
ORDERED_READS = {"fetch_recent_videos", "fetch_ordered_page:hot", "fetch_ordered_page:popular", "fetch_ordered_page:recent"}


def _labels(rows: list[dict]) -> list[str]:
    return [row["video_id"] for row in rows]


def _ranked(rows: list[dict]) -> list[str]:
    return sorted(_labels(rows), key=ORDER.index)


@pytest.mark.parametrize("threshold", (None, THRESHOLD))
@pytest.mark.parametrize("name", READS)
def test_the_filter_drops_every_nsfw_row_and_keeps_the_null_and_0_rows(conn, name, threshold):
    read = READS[name]
    shape = _labels if name in ORDERED_READS else _ranked
    assert shape(read(conn, threshold)) == EXPECTED[(threshold, True)]  # control: unfiltered, the NSFW rows come back
    assert shape(read(conn, threshold, include_nsfw=True)) == EXPECTED[(threshold, True)]  # C1: filter off runs and is today's read
    filtered = read(conn, threshold, include_nsfw=False)
    assert shape(filtered) == EXPECTED[(threshold, False)]  # C1: exactly the allowed rows, in order where order is the contract
    assert [row["video_id"] for row in filtered if row["nsfw"] == 1] == []  # C1: no nsfw = 1 row
    assert {row["nsfw"] for row in filtered} == {0, None}  # C1: the 0 and the NULL rows both stay


@pytest.mark.parametrize("threshold", (None, THRESHOLD))
def test_the_uuid_lookup_still_returns_nsfw_videos(conn, threshold):
    entries = [{"video_uuid": f"u-{label}", "instance_domain": HOST} for label in PAIR_ORDER]
    by_uuid = metadata.fetch_metadata_by_uuids(conn, entries, error_threshold=threshold)
    assert _ranked(list(by_uuid.values())) == EXPECTED[(threshold, True)]  # guard, no clause: fetch_metadata_by_uuids is outside the filter and stays unchanged


@pytest.mark.parametrize("threshold", (None, THRESHOLD))
def test_limits_count_only_allowed_rows(conn, threshold):
    allowed = EXPECTED[(threshold, False)]
    assert _labels(random_videos.fetch_popular_videos(conn, 1, error_threshold=threshold)) == ["X1"]  # control: an NSFW video heads Hot
    assert _labels(random_videos.fetch_recent_videos(conn, 1, error_threshold=threshold)) == ["X1"]  # control: an NSFW video heads Recent
    for n in range(1, len(allowed) + 1):
        assert _ranked(random_videos.fetch_popular_videos(conn, n, error_threshold=threshold, include_nsfw=False)) == allowed[:n], n  # C2
        assert _labels(random_videos.fetch_recent_videos(conn, n, error_threshold=threshold, include_nsfw=False)) == allowed[:n], n  # C2
    # A LIMIT counting NSFW rows fills every allowed slot on one draw in 70 at best; five draws in a row make that chance negligible.
    for _ in range(5):
        assert _ranked(random_videos.fetch_random_rows(conn, len(allowed), error_threshold=threshold, include_nsfw=False)) == allowed  # C2


@pytest.mark.parametrize("threshold", (None, THRESHOLD))
@pytest.mark.parametrize("order", ("hot", "popular", "recent"))
def test_filtered_pages_concatenate_into_the_one_filtered_page(conn, order, threshold):
    allowed = EXPECTED[(threshold, False)]
    assert _labels(random_videos.fetch_ordered_page(conn, order, 1, 0, error_threshold=threshold)) == ["X1"]  # control: an NSFW video heads the order
    whole = _labels(random_videos.fetch_ordered_page(conn, order, 100, 0, error_threshold=threshold, include_nsfw=False))
    assert whole == allowed  # C2: the single filtered page is the allowed order
    for size in (1, 2, 3):
        rows = []
        # One offset past the last allowed row, so a page beyond the end must come back empty.
        for offset in range(0, len(allowed) + size, size):
            page = random_videos.fetch_ordered_page(conn, order, size, offset, error_threshold=threshold, include_nsfw=False)
            assert len(page) <= size, (size, offset)
            rows += page
        labels = _labels(rows)
        assert len(labels) == len(set(labels)), (size, labels)  # C2: no repeat
        assert labels == whole, (size, labels)  # C2: no gap, the OFFSET walks the filtered order


_CHILD = textwrap.dedent(
    """
    import json, sqlite3, sys, threading, types
    sys.path[:0] = [sys.argv[1], sys.argv[1] + "/api"]
    from data import search

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    for sql, params in json.loads(sys.argv[2]):
        conn.execute(sql, params)
    conn.commit()
    server = types.SimpleNamespace(db=conn, db_lock=threading.Lock(), query_encoder=None)
    match_expression = search.sanitize_query("cats", 8, 32)[0]

    def pairs(rows):
        return [[row["video_id"], row["nsfw"]] for row in rows]

    out = []
    for call in json.loads(sys.argv[3]):
        if call["op"] == "lexical":
            out.append(pairs(search.lexical_candidates(conn, match_expression, call["limit"], **call["flag"])))
        else:
            rows, total = search.search_videos(server, "cats", call["page"], call["limit"], "relevance", 8, 32, call["pool"], 60, **call["flag"])
            out.append({"rows": pairs(rows), "total": total})
    print(json.dumps(out))
    """
)


def _search(calls: list[dict]) -> list:
    proc = subprocess.run([str(ENGINE_PY), "-c", _CHILD, str(SERVER_DIR), json.dumps(_statements()), json.dumps(calls)], capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _lexical(limit: int, **flag) -> dict:
    return {"op": "lexical", "limit": limit, "flag": flag}


def _search_page(page: int, limit: int, pool: int, **flag) -> dict:
    return {"op": "search", "page": page, "limit": limit, "pool": pool, "flag": flag}


def test_lexical_candidates_drop_every_nsfw_match_and_keep_the_null_and_0_ones():
    unfiltered, flag_off, filtered = _search([_lexical(100), _lexical(100, include_nsfw=True), _lexical(100, include_nsfw=False)])
    assert [label for label, _ in unfiltered] == EXPECTED[(None, True)]  # control: every video matches, in relevance order
    assert [label for label, _ in flag_off] == EXPECTED[(None, True)]  # C1: filter off runs and is today's read
    assert [label for label, _ in filtered] == EXPECTED[(None, False)]  # C1
    assert [label for label, nsfw in filtered if nsfw == 1] == []  # C1: no nsfw = 1 row
    assert {nsfw for _, nsfw in filtered} == {0, None}  # C1: the 0 and the NULL rows both stay


def test_lexical_limit_and_search_total_count_only_allowed_rows():
    allowed = EXPECTED[(None, False)]
    head, unfiltered_search, *rest = _search(
        [_lexical(1), _search_page(1, 2, 100)]
        + [_lexical(n, include_nsfw=False) for n in range(1, len(allowed) + 1)]
        + [_search_page(1, 2, 100, include_nsfw=False), _search_page(2, 2, 100, include_nsfw=False), _search_page(1, 2, 2, include_nsfw=False)]
    )
    lexical, (first_page, second_page, small_pool) = rest[:len(allowed)], rest[len(allowed):]
    assert [label for label, _ in head] == ["X1"]  # control: an NSFW video heads relevance
    assert unfiltered_search["total"] == len(ORDER)  # control: unfiltered, every video counts
    for n, rows in enumerate(lexical, start=1):
        assert [label for label, _ in rows] == allowed[:n], n  # C2: LIMIT n keeps the first n allowed matches
    assert first_page == {"rows": [["A", 0], ["B", None]], "total": len(allowed)}  # C2: total counts only allowed rows
    assert second_page == {"rows": [["C", 0], ["D", None]], "total": len(allowed)}  # C2
    assert small_pool == {"rows": [["A", 0], ["B", None]], "total": 2}  # C2: the candidate pool's LIMIT counts only allowed rows
