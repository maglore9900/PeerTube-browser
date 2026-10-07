"""`search_videos_by_tag` in `data/search.py` returns exactly the videos whose stored tag list holds the requested tag once both are trimmed and lowercased, by the FTS prefilter or the no-token full scan, and a `total` counting every match the NSFW setting allows on any page.

- `linux` has a non-empty FTS prefilter expression, and returns, once each, the rows tagged `["Linux"," linux ","x"]`, `["  linux "]`, `["LINUX"]`, `[1,"linux"]`, `["linux","mint"]` and the NSFW `["linux"]`, and none of `["linuxmint"]`, `linux` only in the description, the object `{"a":"linux"}`, the unterminated `["linux"`, or NULL. The unterminated row raises nothing. The padded, upper-cased request `"\\t LINUX \\n"` returns the same six. `linux mint` returns only `["linux mint"]`, not `["linux","mint"]`.
- `música` and `MÚSICA` each return both the `["MÚSICA"]` and the `["música"]` rows, so case folds beyond ASCII on both sides.
- `???` has no FTS token (`tag_match_expression` is empty), and the full scan still returns both `["???"]` and `["\\t???\\n"]`, with a `total` of 2.
- `a"b` returns only its own row, with no FTS syntax error.
- Walking `linux` at limit 2, `total` is 6 on each of the three pages and on the empty page past the end; with `include_nsfw=False` the NSFW row leaves the pages and `total` is 5 on every page, including the one past the end.

Every read runs on an in-memory SQLite database with the Engine's `videos`, `channels` and external-content `videos_fts` tables. `data.search` imports numpy and faiss, which only the Engine's environment has, so the reads run in a child on the Engine's interpreter, as in `test_search.py`. The child reports each call's rows, total, or the exception it raised.
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
DAY_MS = 86_400_000
PAST_MS = 1_700_000_000_000

# label -> (tags_json as stored, nsfw, description). Listed in published_at order, newest first.
ROWS = {
    "L1": ('["Linux"," linux ","x"]', 0, None),
    "TRIM": ('["  linux "]', None, None),
    "MINT": ('["linuxmint"]', 0, None),
    "NS": ('["linux"]', 1, None),
    "UPPER": ('["LINUX"]', 0, None),
    "DESC": ('["other"]', 0, "all about linux"),
    "OBJ": ('{"a":"linux"}', 0, None),
    "BAD": ('["linux"', 0, None),
    "MIX": ('[1,"linux"]', 0, None),
    "NUL": (None, 0, None),
    "SPLIT": ('["linux","mint"]', 0, None),
    "PHRASE": ('["linux mint"]', 0, None),
    "MU_UP": ('["MÚSICA"]', 0, None),
    "MU_LO": ('["música"]', 0, None),
    "Q1": ('["???"]', 0, None),
    "Q2": ('["\\t???\\n"]', 0, None),
    "QUOTE": ('["a\\"b"]', 0, None),
}
NEWEST_FIRST = list(ROWS)

# Derived by hand from ROWS, in published_at DESC order.
LINUX_ALL = ["L1", "TRIM", "NS", "UPPER", "MIX", "SPLIT"]
LINUX_ALLOWED = ["L1", "TRIM", "UPPER", "MIX", "SPLIT"]


def _statements() -> list[tuple[str, list]]:
    statements: list[tuple[str, list]] = [
        ("CREATE TABLE videos (video_id TEXT NOT NULL, video_uuid TEXT, video_numeric_id INTEGER, instance_domain TEXT NOT NULL, channel_id TEXT, channel_name TEXT, channel_url TEXT, account_name TEXT, account_url TEXT, title TEXT, description TEXT, tags_json TEXT, category TEXT, published_at INTEGER, video_url TEXT, duration INTEGER, thumbnail_url TEXT, embed_path TEXT, views INTEGER, likes INTEGER, dislikes INTEGER, comments_count INTEGER, nsfw INTEGER, preview_path TEXT, popularity REAL NOT NULL DEFAULT 0, last_checked_at INTEGER NOT NULL, error_count INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (video_id, instance_domain))", []),
        ("CREATE TABLE channels (channel_id TEXT, instance_domain TEXT, display_name TEXT, avatar_url TEXT)", []),
        ("CREATE VIRTUAL TABLE videos_fts USING fts5(title, description, tags_json, category, channel_name, content='videos', content_rowid='rowid')", []),
    ]
    # Stored in a scrambled order, so neither rowid order matches the published_at order under test.
    for label in sorted(NEWEST_FIRST, key=lambda label: (NEWEST_FIRST.index(label) + 1) * 5 % len(NEWEST_FIRST)):
        tags_json, nsfw, description = ROWS[label]
        rank = NEWEST_FIRST.index(label) + 1
        statements.append((
            "INSERT INTO videos (video_id, video_uuid, instance_domain, channel_id, title, description, tags_json, published_at, views, nsfw, popularity, last_checked_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)",
            [label, f"u-{label}", HOST, f"ch-{label}", f"video {label.lower()}", description, tags_json, PAST_MS - rank * DAY_MS, 10 * rank, nsfw, float(rank)],
        ))
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

    out = []
    for call in json.loads(sys.argv[3]):
        try:
            if call["op"] == "expression":
                out.append({"expression": search.tag_match_expression(call["tag"])})
            else:
                rows, total = search.search_videos_by_tag(server, call["tag"], call["page"], call["limit"], **call["flag"])
                out.append({"rows": [row["video_id"] for row in rows], "total": total})
        except Exception as exc:
            out.append({"error": repr(exc)})
    print(json.dumps(out))
    """
)


def _run(calls: list[dict]) -> list[dict]:
    proc = subprocess.run([str(ENGINE_PY), "-c", _CHILD, str(SERVER_DIR), json.dumps(_statements()), json.dumps(calls)], capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _tag(tag: str, page: int = 1, limit: int = 50, **flag) -> dict:
    return {"op": "tag", "tag": tag, "page": page, "limit": limit, "flag": flag}


def test_a_tag_returns_exactly_the_videos_carrying_it_after_trim_and_lowercase_on_both_sides():
    linux, padded, linux_expression, linux_mint, musica_lower, musica_upper, question, question_expression, quote = _run([
        _tag("linux"),
        _tag("\t LINUX \n"),
        {"op": "expression", "tag": "linux"},
        _tag("linux mint"),
        _tag("música"),
        _tag("MÚSICA"),
        _tag("???"),
        {"op": "expression", "tag": "???"},
        _tag('a"b'),
    ])
    # Case, padding, a non-text element, a second tag and a repeated tag each yield the row once;
    # the near-miss rows (prefix token, description, object, malformed JSON) do not.
    assert sorted(linux.get("rows", [linux])) == sorted(LINUX_ALL)  # C1
    # ...and on the FTS prefilter path: `linux` has a token, so a prefilter expression exists for it.
    assert linux_expression.get("expression")
    # The requested tag is trimmed (tab, space, newline) and lowercased too.
    assert sorted(padded.get("rows", [padded])) == sorted(LINUX_ALL)  # C1
    assert linux_mint.get("rows") == ["PHRASE"]  # C1: two adjacent tags are not one tag
    # Case folds beyond ASCII, whichever side carries the capital letters.
    assert sorted(musica_lower.get("rows", [musica_lower])) == ["MU_LO", "MU_UP"]  # C1
    assert sorted(musica_upper.get("rows", [musica_upper])) == ["MU_LO", "MU_UP"]  # C1
    # No-token path: `???` gives FTS nothing to match, so only the full scan can find these rows.
    assert question_expression == {"expression": ""}
    assert sorted(question.get("rows", [question])) == ["Q1", "Q2"]  # C1
    assert question.get("total") == 2  # C2: the full scan counts its matches too
    assert quote.get("rows") == ["QUOTE"]  # an embedded quote reaches neither an FTS error nor another row


def test_total_counts_every_allowed_match_on_every_page():
    results = _run([_tag("linux", page, 2) for page in (1, 2, 3, 4)] + [_tag("linux", page, 2, include_nsfw=False) for page in (1, 2, 3, 4)])
    pages_all, past_end, pages_off, past_end_off = results[:3], results[3], results[4:7], results[7]
    walked = [row for page in pages_all for row in page.get("rows", [page])]
    assert walked == LINUX_ALL  # C2: three pages of two walk the six matches newest first, no overlap
    assert [page.get("total") for page in pages_all] == [6, 6, 6]  # C2: the full count on the first, middle and last page
    assert past_end == {"rows": [], "total": 6}  # C2: a page past the end still counts every match
    walked_off = [row for page in pages_off for row in page.get("rows", [page])]
    assert walked_off == LINUX_ALLOWED  # C2: the NSFW row leaves the pages, so the last page holds one
    assert [page.get("total") for page in pages_off] == [5, 5, 5]  # C2: and leaves the count on every page
    assert past_end_off == {"rows": [], "total": 5}  # C2
