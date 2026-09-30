"""With `include_nsfw=False` the search reads in `data/search.py` leave out every `nsfw = 1` match inside their SQL, so the FTS LIMIT and search's `total` count only the rows that are allowed.

- `lexical_candidates` at a limit past the nine matches: the default call and `include_nsfw=True` return all nine videos in relevance order, and `include_nsfw=False` returns exactly A, B, C, D and E, whose `nsfw` values are 0 and NULL and none 1.
- NSFW videos head FTS relevance, and one more sits mid-order. With the filter on, `lexical_candidates` at LIMIT n returns the first n allowed matches for every n up to the allowed count.
- `search_videos` with the filter on reports a `total` of 5, the allowed matches, against 9 unfiltered; pages 1 and 2 of two rows are A, B then C, D; and a candidate pool of 2 gives a total of 2 and rows A, B.

Every read runs on an in-memory SQLite database with the Engine's `videos`, `video_embeddings`, `channels` and external-content `videos_fts` tables, built from `_statements()`. The video at rank r has 10 - r "cats" in a ten-word title, so FTS relevance runs in `ORDER`. `data.search` imports numpy and faiss, which only the Engine's environment has, so the reads run in a child on the Engine's interpreter. That child builds the database from the same statements and reports back as JSON. It has no query encoder, the path search already takes when the model is unavailable, so `search_videos` ranks the keyword half alone.
"""
from __future__ import annotations

import json
import subprocess
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SERVER_DIR = ROOT / "engine" / "server"
ENGINE_PY = ROOT / "engine" / ".pixi" / "envs" / "default" / "bin" / "python"

HOST = "h.example"
THRESHOLD = 3
DAY_MS = 86_400_000
PAST_MS = 1_700_000_000_000
# One rank order: NSFW rows lead it, sit in its middle and end it.
ORDER = ("X1", "X2", "A", "B", "X3", "C", "D", "E", "X4")
NSFW = {"X1": 1, "X2": 1, "A": 0, "B": None, "X3": 1, "C": 0, "D": None, "E": 0, "X4": 1}
# E sits at the threshold; search takes no error threshold, so it is served like any other allowed row.
ERRORED = "E"
# Derived by hand from ORDER and NSFW, keyed by include_nsfw.
EXPECTED = {
    True: ["X1", "X2", "A", "B", "X3", "C", "D", "E", "X4"],
    False: ["A", "B", "C", "D", "E"],
}


def _statements() -> list[tuple[str, list]]:
    """The statements that build the fixture database in the child."""
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
    assert [label for label, _ in unfiltered] == EXPECTED[True]  # control: every video matches, in relevance order
    assert [label for label, _ in flag_off] == EXPECTED[True]  # filter off runs and is the unfiltered read
    assert [label for label, _ in filtered] == EXPECTED[False]
    assert [label for label, nsfw in filtered if nsfw == 1] == []  # no nsfw = 1 row
    assert {nsfw for _, nsfw in filtered} == {0, None}  # the 0 and the NULL rows both stay


def test_lexical_limit_and_search_total_count_only_allowed_rows():
    allowed = EXPECTED[False]
    head, unfiltered_search, *rest = _search(
        [_lexical(1), _search_page(1, 2, 100)]
        + [_lexical(n, include_nsfw=False) for n in range(1, len(allowed) + 1)]
        + [_search_page(1, 2, 100, include_nsfw=False), _search_page(2, 2, 100, include_nsfw=False), _search_page(1, 2, 2, include_nsfw=False)]
    )
    lexical, (first_page, second_page, small_pool) = rest[:len(allowed)], rest[len(allowed):]
    assert [label for label, _ in head] == ["X1"]  # control: an NSFW video heads relevance
    assert unfiltered_search["total"] == len(ORDER)  # control: unfiltered, every video counts
    for n, rows in enumerate(lexical, start=1):
        assert [label for label, _ in rows] == allowed[:n], n  # LIMIT n keeps the first n allowed matches
    assert first_page == {"rows": [["A", 0], ["B", None]], "total": len(allowed)}  # total counts only allowed rows
    assert second_page == {"rows": [["C", 0], ["D", None]], "total": len(allowed)}
    assert small_pool == {"rows": [["A", 0], ["B", None]], "total": 2}  # the candidate pool's LIMIT counts only allowed rows
