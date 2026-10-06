"""The Engine's Following feed and the per-source recency indexes it reads.

Following pages, through the real `SimilarHandler.do_POST` under the Engine interpreter in a child process, on a stub server over a temp catalogue of the labelled rows in `CATALOGUE` (only the socket transport is replaced, so body parsing, dispatch, the read and `_respond_rows` are the Engine's own):

- Following channels a.example/ch-a, b.example/ch-b and x.example/ch-x1 and the account that owns ch-x1 and ch-x2, at limit 4, the walk that sends each page's `cursor` back serves exactly `MAIN_PAGES`: newest first by (published_at, video_id, instance_domain) DESC, rows of the account's other channel included, ch-x1's row once though both its channel and its account are followed, the `v-tie` pair split across the page edge with the b.example copy closing page 1 and the a.example copy opening page 2, the two full pages carrying a cursor and the short last page none. An unfollowed newer channel, ch-a on another host, an undated, a future-dated, an unembedded and an at-threshold row of a followed source, and the NSFW-flagged one are never served.
- With `nsfw=1` the same walk serves `NSFW_PAGES`, the flagged row first; without it the walk is `MAIN_PAGES`, the flagged row on no page.
- At limit 9 the first page holds all nine rows and carries a cursor, and the page that cursor names is empty and carries none.
- 524 sources, the real ones on both sides of the 500th, and exactly 1000 sources (600 channels, 400 accounts) are each answered 200 and walked to `MAIN_PAGES`.
- Following ch-a and m.example/ch-m, on a catalogue where ch-m is not moderated the walk is `M2 A3 TA M1` then `AM A1`; where ch-m is blocked it is `A3 TA` then `AM A1`, page 1 carrying the very cursor the unmoderated page 1 carried.

Following requests against the session Engine:

- `mode=following` with no `follows` field, or with empty channel and account lists, is answered 200 with no rows and no cursor and no `random` key in its seed, where `mode=random` on the same Engine serves rows.
- A `follows` that is a list, has a non-list `channels`, a one-part channel or a non-string account is answered 400 `Invalid follows payload`; 1001 sources (600 channels, 401 accounts) 400 `Too many follow sources in request body`; a cursor that is not base64url, decodes to the wrong arity or is not a string 400 `Invalid cursor`.
- `mode=following&random=1` is answered the random feed: seed `{"random": True}`, rows, no cursor.
- A seeded request (seed=11) with `mode=following` and a `follows` body is answered the same seed and rows as the same request without them, a draw that repeats without them (control).

Both index-creation paths, in-process on temp sqlite files, read back through `PRAGMA index_xinfo`:

- `ensure_video_indexes` on a crawl-shaped DB holding neither index (control), run twice as two Engine starts would, leaves idx_videos_channel_published on `videos` keyed (instance_domain, channel_id, published_at DESC, video_id DESC) and idx_videos_account_published keyed (account_url, published_at DESC, video_id DESC).
- The sync stage's `ensure_whitelist_schema` and `ensure_content_schema`, run twice on a fresh DB, leave the same two indexes with the same keys.
"""
from __future__ import annotations

import base64
import importlib.util
import json
import sqlite3
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from urllib.parse import quote

import pytest

# tests/active/conftest.py holds the session Engine fixtures; a working-tree test sees them only by importing the chain `engine` depends on.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))
from conftest import ENGINE_PY, ROOT, engine, shared_trending_before, trending_seed  # noqa: E402,F401

# The Engine dirs go on sys.path after conftest's import: both trees hold a `server` module.
SERVER_DIR = ROOT / "engine" / "server"
for _path in (SERVER_DIR, SERVER_DIR / "api"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))
from data.ann_ids import compute_ann_id, create_video_embeddings_table  # noqa: E402
from data.moderation import ensure_moderation_schema  # noqa: E402
from data.videos import ensure_video_indexes  # noqa: E402

CRAWL_SCHEMA = ROOT / "engine" / "crawler" / "schema.sql"
SYNC_JOB = SERVER_DIR / "db" / "jobs" / "sync-whitelist.py"

# The temp catalogue: epoch-ms publish dates as offsets from T0, years before any run.
T0 = 1_700_000_000_000
FUTURE = "future"
FOLLOW_PAGE = 4
THRESHOLD = 3
# A walk stops here, so a cursor that never runs out shows as a long page list rather than a hang.
MAX_PAGES = 6
ACCT_A = "https://a.example/accounts/alice"
ACCT_B = "https://b.example/accounts/bob"
ACCT_X = "https://x.example/accounts/xena"
# label: (video_id, instance_domain, channel_id, account_url, published_at offset | None | FUTURE, nsfw, error_count, embedded).
CATALOGUE = {
    "C1": ("c1", "c.example", "ch-c", "https://c.example/accounts/carol", 9900, 0, 0, True),
    "UNE": ("une", "a.example", "ch-a", ACCT_A, 9800, 0, 0, False),
    "M2": ("m2", "m.example", "ch-m", "https://m.example/accounts/mallory", 9500, 0, 0, True),
    "ERR": ("err", "b.example", "ch-b", ACCT_B, 9300, 0, THRESHOLD, True),
    "NSF": ("nsf", "b.example", "ch-b", ACCT_B, 9100, 1, 0, True),
    "A3": ("a3", "a.example", "ch-a", ACCT_A, 9000, 0, 0, True),
    "BA": ("ba1", "b.example", "ch-a", "https://b.example/accounts/barry", 8500, 0, 0, True),
    "X2": ("x2", "x.example", "ch-x2", ACCT_X, 8000, None, 0, True),
    "X1": ("x1", "x.example", "ch-x1", ACCT_X, 7000, 0, 0, True),
    "TB": ("v-tie", "b.example", "ch-b", ACCT_B, 6000, 0, 0, True),
    "TA": ("v-tie", "a.example", "ch-a", ACCT_A, 6000, 0, 0, True),
    "M1": ("m1", "m.example", "ch-m", "https://m.example/accounts/mallory", 5500, 0, 0, True),
    "BZ": ("v-z", "b.example", "ch-b", ACCT_B, 4000, 0, 0, True),
    "AM": ("v-m", "a.example", "ch-a", ACCT_A, 4000, 0, THRESHOLD - 1, True),
    "X0": ("x0", "x.example", "ch-x2", ACCT_X, 3000, 0, 0, True),
    "A1": ("a1", "a.example", "ch-a", ACCT_A, 2000, 0, 0, True),
    "UND": ("und", "a.example", "ch-a", ACCT_A, None, 0, 0, True),
    "FUT": ("fut", "b.example", "ch-b", ACCT_B, FUTURE, 0, 0, True),
}
LABEL_OF = {(spec[0], spec[1]): label for label, spec in CATALOGUE.items()}
MAIN_CHANNELS = [["a.example", "ch-a"], ["b.example", "ch-b"], ["x.example", "ch-x1"]]
MAIN_FOLLOWS = {"channels": MAIN_CHANNELS, "accounts": [ACCT_X]}
# Derived by hand from CATALOGUE and MAIN_FOLLOWS: published_at, video_id, instance_domain, all descending, in pages of 4. C1, M1, M2 and BA (ch-a on b.example) are unfollowed; UNE has no embedding, ERR is at the threshold, NSF is flagged, UND is undated and FUT future-dated. AM, one under the threshold, and X2, nsfw NULL, are served.
MAIN_PAGES = [["A3", "X2", "X1", "TB"], ["TA", "BZ", "AM", "X0"], ["A1"]]
NSFW_PAGES = [["NSF", "A3", "X2", "X1"], ["TB", "TA", "BZ", "AM"], ["X0", "A1"]]
MODERATION_FOLLOWS = {"channels": [["a.example", "ch-a"], ["m.example", "ch-m"]], "accounts": []}
FOLLOWING_PATH = f"/recommendations?mode=following&limit={FOLLOW_PAGE}"


def _dummy_channels(count: int) -> list[list[str]]:
    return [[f"q{n}.example", f"ch-q{n}"] for n in range(count)]


def _dummy_accounts(count: int) -> list[str]:
    return [f"https://q{n}.example/accounts/q{n}" for n in range(count)]


def _catalogue(path: Path, blocked: bool) -> str:
    """A whitelist-shaped DB of the CATALOGUE rows, stored in label order (not the served order); with `blocked`, ch-m is a blocked channel."""
    conn = sqlite3.connect(path)
    conn.executescript(CRAWL_SCHEMA.read_text(encoding="utf-8"))
    conn.execute("ALTER TABLE videos ADD COLUMN popularity REAL NOT NULL DEFAULT 0")
    create_video_embeddings_table(conn)
    ensure_moderation_schema(conn)
    future = int(time.time() * 1000) + 30 * 86_400_000
    for label in sorted(CATALOGUE):
        video_id, host, channel_id, account_url, offset, nsfw, errors, embedded = CATALOGUE[label]
        published_at = future if offset == FUTURE else None if offset is None else T0 + offset
        conn.execute(
            "INSERT INTO videos (video_id, video_uuid, instance_domain, channel_id, channel_name, account_url, published_at, nsfw, error_count, last_checked_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)",
            (video_id, f"uuid-{label}", host, channel_id, channel_id, account_url, published_at, nsfw, errors),
        )
        if embedded:
            conn.execute("INSERT INTO video_embeddings VALUES (?, ?, x'00', 1, 'm', 't', ?)", (video_id, host, compute_ann_id(video_id, host)))
    if blocked:
        conn.execute("INSERT INTO channel_moderation (channel_id, instance_domain, status, updated_at, created_at) VALUES ('ch-m', 'm.example', 'blocked', 0, 0)")
    conn.commit()
    conn.close()
    return str(path)


# Runs under the Engine interpreter: importing handlers.similar needs numpy and faiss, which only its pixi env carries.
# The handler is entered at do_POST with a real JSON body; only the socket transport is replaced, so a response is read as the status and body it sends.
_FOLLOWING_CHILD = textwrap.dedent(
    """
    import io, json, sqlite3, sys, threading, types
    sys.path[:0] = [sys.argv[1], sys.argv[2]]
    from handlers import similar

    class Handler(similar.SimilarHandler):
        def __init__(self, server, path, body):
            raw = json.dumps(body).encode("utf-8")
            self.server = server
            self.path = path
            self.command = "POST"
            self.request_version = "HTTP/1.1"
            self.client_address = ("127.0.0.1", 0)
            self.headers = {"content-type": "application/json", "content-length": str(len(raw))}
            self.rfile = io.BytesIO(raw)
            self.wfile = io.BytesIO()
            self.statuses = []

        def send_response(self, status, message=None):
            self.statuses.append(status)

        def send_header(self, name, value):
            pass

        def end_headers(self):
            pass

    out = []
    for db_path, path, body in json.loads(sys.argv[3]):
        db = sqlite3.connect(db_path)
        db.row_factory = sqlite3.Row
        # No random cache, so the random feed reads catalogue rows: a fallback would fill the page.
        server = types.SimpleNamespace(default_limit=20, refresh_similarity_cache=False, recommendations_debug_enabled=False, db=db, db_lock=threading.Lock(), video_error_threshold=int(sys.argv[4]), embeddings_count=0, random_cache_db=None, random_cache_lock=threading.Lock())
        pages = []
        while len(pages) < int(sys.argv[5]):
            handler = Handler(server, path, body)
            handler.do_POST()
            payload = json.loads(handler.wfile.getvalue() or b"null")
            pages.append({"statuses": handler.statuses, "body": payload})
            cursor = payload.get("cursor") if handler.statuses == [200] and isinstance(payload, dict) else None
            if not cursor:
                break
            # The next page is asked for as the frontend pager asks: the same body carrying the cursor the last page carried.
            body = {**body, "cursor": cursor}
        out.append(pages)
        db.close()
    print(json.dumps(out))
    """
)


def _walk(cases: list[list]) -> list[list[dict]]:
    """Each case's pages: [db_path, path, body] posted, then posted again with each page's cursor until a page carries none."""
    assert ENGINE_PY.exists(), f"Engine interpreter missing at {ENGINE_PY}; run `pixi install` in engine/"
    run = subprocess.run([str(ENGINE_PY), "-c", _FOLLOWING_CHILD, str(SERVER_DIR), str(SERVER_DIR / "api"), json.dumps(cases), str(THRESHOLD), str(MAX_PAGES)], cwd=SERVER_DIR / "api", capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stderr[-2000:]  # control: the Engine's interpreter imported the handler and ran every case
    return json.loads(run.stdout.strip().splitlines()[-1])


def _cursor(page: dict) -> str | None:
    body = page["body"]
    return body.get("cursor") if isinstance(body, dict) else None


def _served(pages: list[dict]) -> list[tuple[list[int], list[str], bool]]:
    """Per page: the statuses sent, the rows' labels (or the error body), and whether it carried a non-empty string cursor."""
    out = []
    for page in pages:
        body = page["body"] if isinstance(page["body"], dict) else {}
        rows = body.get("rows")
        labels = [LABEL_OF.get((r["video_id"], r["instance_domain"]), f"{r['video_id']}@{r['instance_domain']}") for r in rows] if page["statuses"] == [200] and isinstance(rows, list) else [f"answer: {body}"]
        cursor = _cursor(page)
        out.append((page["statuses"], labels, isinstance(cursor, str) and bool(cursor)))
    return out


def _pages(labels: list[list[str]], last_has_cursor: bool = False) -> list[tuple[list[int], list[str], bool]]:
    """The expected `_served` of 200 pages holding `labels`: every page but the last carries a cursor."""
    return [([200], page, index < len(labels) - 1 or last_has_cursor) for index, page in enumerate(labels)]


def test_a_following_walk_serves_the_followed_channels_and_accounts_newest_first_once_each_in_pages_that_start_strictly_after_the_cursor(tmp_path):
    db = _catalogue(tmp_path / "catalogue.db", blocked=False)
    (walk,) = _walk([[db, FOLLOWING_PATH, {"follows": MAIN_FOLLOWS}]])
    # A recency feed ignoring follows opens with C1; channel-only matching serves BA; no dedup serves X1 twice; ignoring accounts drops X2 and X0; a (published_at, video_id) cursor skips TA, an inclusive one repeats TB; no cursor on a full page ends the walk at page 1.
    assert _served(walk) == _pages(MAIN_PAGES)  # C1


def test_nsfw_flagged_rows_of_a_followed_source_are_served_only_with_nsfw_1(tmp_path):
    db = _catalogue(tmp_path / "catalogue.db", blocked=False)
    filtered, flagged = _walk([[db, FOLLOWING_PATH, {"follows": MAIN_FOLLOWS}], [db, f"{FOLLOWING_PATH}&nsfw=1", {"follows": MAIN_FOLLOWS}]])
    assert _served(filtered) == _pages(MAIN_PAGES)  # C1: no flagged row on any page without nsfw=1
    assert _served(flagged) == _pages(NSFW_PAGES)  # C1: the flagged row takes its place in the order with nsfw=1


def test_a_full_last_page_carries_a_cursor_whose_page_is_empty_and_carries_none(tmp_path):
    db = _catalogue(tmp_path / "catalogue.db", blocked=False)
    every = [label for page in MAIN_PAGES for label in page]
    (walk,) = _walk([[db, f"/recommendations?mode=following&limit={len(every)}", {"follows": MAIN_FOLLOWS}]])
    # A cursor issued only when rows remain would end here with one page; one issued on an empty page would loop to MAX_PAGES.
    assert _served(walk) == _pages([every, []])  # C1


def test_more_than_500_sources_and_exactly_1000_are_served_the_pages_their_few_row_holding_sources_give(tmp_path):
    db = _catalogue(tmp_path / "catalogue.db", blocked=False)
    batched = {"channels": [MAIN_CHANNELS[0], *_dummy_channels(520), *MAIN_CHANNELS[1:]], "accounts": [ACCT_X]}
    capped = {"channels": [*MAIN_CHANNELS, *_dummy_channels(597)], "accounts": [ACCT_X, *_dummy_accounts(399)]}
    # control: a.example/ch-a sits in the first 500 sources and ch-b, ch-x1 and the account after them, so a read of the first batch alone loses rows.
    assert len(batched["channels"]) + len(batched["accounts"]) == 524 and batched["channels"].index(MAIN_CHANNELS[0]) < 500 <= batched["channels"].index(MAIN_CHANNELS[1])
    assert (len(capped["channels"]), len(capped["accounts"])) == (600, 400)  # control: the cap exactly, channels and accounts together
    over, at_cap = _walk([[db, FOLLOWING_PATH, {"follows": batched}], [db, FOLLOWING_PATH, {"follows": capped}]])
    assert _served(over) == _pages(MAIN_PAGES)  # C1
    assert _served(at_cap) == _pages(MAIN_PAGES)  # C1: 1000 sources are under the cap, not over it


def test_moderation_shortens_a_following_page_but_leaves_its_cursor_and_the_next_page_as_they_were(tmp_path):
    open_db = _catalogue(tmp_path / "open.db", blocked=False)
    moderated_db = _catalogue(tmp_path / "moderated.db", blocked=True)
    unmoderated, moderated = _walk([[open_db, FOLLOWING_PATH, {"follows": MODERATION_FOLLOWS}], [moderated_db, FOLLOWING_PATH, {"follows": MODERATION_FOLLOWS}]])
    assert _served(unmoderated) == _pages([["M2", "A3", "TA", "M1"], ["AM", "A1"]])  # control: ch-m's rows are in the selection when it is not blocked
    # Moderating before selection refills page 1 to A3 TA AM A1 and serves no page 2.
    assert _served(moderated) == _pages([["A3", "TA"], ["AM", "A1"]])  # C1: a short page that still carries a cursor
    # A cursor taken from the last row served (TA) differs: selection fixed it at M1 before moderation ran.
    assert _cursor(moderated[0]) == _cursor(unmoderated[0])  # C1


# The session Engine, over HTTP. Their own rate-limit buckets: 60 requests a minute per client IP and path, clear of every other address tests/active uses.
EMPTY_HEADERS = {"X-Client-IP": "203.0.113.51"}
PAYLOAD_HEADERS = {"X-Client-IP": "203.0.113.52"}
CURSOR_HEADERS = {"X-Client-IP": "203.0.113.53"}
RANDOM_HEADERS = {"X-Client-IP": "203.0.113.54"}
SEEDED_HEADERS = {"X-Client-IP": "203.0.113.55"}
# Sources no catalogue holds: a Following read of them is an empty page, so a page with rows came from another feed.
NOWHERE_FOLLOWS = {"channels": [["follow-probe.invalid", "ch-none"]], "accounts": ["https://follow-probe.invalid/accounts/none"]}
UPNEXT_PAGE = 8
MALFORMED_FOLLOWS = {
    "a list": ["a.example", "ch-a"],
    "channels not a list": {"channels": "a.example", "accounts": []},
    "a one-part channel": {"channels": [["a.example"]], "accounts": []},
    "a non-string account": {"channels": [], "accounts": [42]},
}
MALFORMED_CURSORS = {
    "not base64url": "@@@",
    "one value, not three": base64.urlsafe_b64encode(b"[1700000000000]").decode("ascii").rstrip("="),
    "not a string": 1700000000000,
}


def test_a_following_request_without_follows_is_an_empty_page_with_no_cursor_not_a_fallback(engine):
    status, random_page = engine.request("POST", f"/recommendations?mode=random&limit={FOLLOW_PAGE}", headers=EMPTY_HEADERS, body={})
    assert status == 200 and random_page["rows"], random_page  # control: the session Engine's random feed serves rows, so a fallback shows
    for body in ({}, {"follows": {"channels": [], "accounts": []}}):
        status, page = engine.request("POST", FOLLOWING_PATH, headers=EMPTY_HEADERS, body=body)
        assert (status, page.get("rows")) == (200, []), (body, status, page)  # C1: no home mix, no random fallback
        assert page.get("cursor") is None and "random" not in page["seed"], (body, page)  # C1: an empty page carries no cursor


@pytest.mark.parametrize("follows", MALFORMED_FOLLOWS.values(), ids=MALFORMED_FOLLOWS.keys())
def test_a_malformed_follows_payload_is_refused_400(engine, follows):
    status, body = engine.request("POST", FOLLOWING_PATH, headers=PAYLOAD_HEADERS, body={"follows": follows})
    assert (status, body.get("error")) == (400, "Invalid follows payload"), body  # C1: refused at the request edge, not read, not a 500


def test_more_than_1000_follow_sources_counted_across_channels_and_accounts_are_refused_400(engine):
    follows = {"channels": [[f"q{n}.invalid", f"ch-q{n}"] for n in range(600)], "accounts": [f"https://q{n}.invalid/accounts/q{n}" for n in range(401)]}
    status, body = engine.request("POST", FOLLOWING_PATH, headers=PAYLOAD_HEADERS, body={"follows": follows})
    # Counting channels alone (600) lets this through; 1000 together are served (the temp-catalogue test above).
    assert (status, body.get("error")) == (400, "Too many follow sources in request body"), body  # C1


@pytest.mark.parametrize("cursor", MALFORMED_CURSORS.values(), ids=MALFORMED_CURSORS.keys())
def test_a_malformed_cursor_is_refused_400(engine, cursor):
    status, body = engine.request("POST", FOLLOWING_PATH, headers=CURSOR_HEADERS, body={"follows": NOWHERE_FOLLOWS, "cursor": cursor})
    # A decode error left to _handle_similar becomes 500 "Recommendations request failed".
    assert (status, body.get("error")) == (400, "Invalid cursor"), body  # C1


def test_random_1_still_wins_over_mode_following(engine):
    status, body = engine.request("POST", f"{FOLLOWING_PATH}&random=1", headers=RANDOM_HEADERS, body={"follows": NOWHERE_FOLLOWS})
    # A following arm checked before random answers seed {} and no rows for these sources.
    assert status == 200 and body["seed"] == {"random": True} and body["rows"], (status, body.get("seed"), len(body.get("rows") or []))  # C1
    assert body.get("cursor") is None, body.get("cursor")  # C1


def test_a_seeded_request_with_mode_following_and_follows_is_still_the_same_upnext(engine):
    status, found = engine.request("GET", "/api/v1/search/videos?q=linux&limit=1", headers=SEEDED_HEADERS)
    assert status == 200 and found["rows"], found
    seed = found["rows"][0]
    path = f"/recommendations?id={quote(seed['video_uuid'])}&host={quote(seed['instance_domain'])}&limit={UPNEXT_PAGE}&seed=11"
    status, plain = engine.request("POST", path, headers=SEEDED_HEADERS, body={})
    assert status == 200 and plain["seed"].get("mode") == "upnext" and len(plain["rows"]) == UPNEXT_PAGE, (status, plain.get("seed"))
    status, again = engine.request("POST", path, headers=SEEDED_HEADERS, body={})
    assert status == 200 and [r["video_id"] for r in again["rows"]] == [r["video_id"] for r in plain["rows"]], "control: the seeded draw repeats without mode"
    status, following = engine.request("POST", f"{path}&mode=following", headers=SEEDED_HEADERS, body={"follows": NOWHERE_FOLLOWS})
    # Dispatching a seeded request on mode serves the Following page of these sources: seed {} and no rows.
    assert status == 200 and following["seed"] == plain["seed"], (status, following.get("seed"))  # C1
    assert [(r["video_id"], r["instance_domain"]) for r in following["rows"]] == [(r["video_id"], r["instance_domain"]) for r in plain["rows"]]  # C1


# (column, desc) of each index key column, read from PRAGMA index_xinfo rows (seqno, cid, name, desc, coll, key); key = 0 rows are the rowid tail.
RECENCY_INDEXES = {
    "idx_videos_channel_published": [("instance_domain", 0), ("channel_id", 0), ("published_at", 1), ("video_id", 1)],
    "idx_videos_account_published": [("account_url", 0), ("published_at", 1), ("video_id", 1)],
}


def _key_columns(conn: sqlite3.Connection) -> dict[str, tuple[str | None, list[tuple[str, int]]]]:
    """Per recency index: the table it is on, and its key columns with their DESC flag; an absent index reads (None, [])."""
    out = {}
    for name in RECENCY_INDEXES:
        table = conn.execute("SELECT tbl_name FROM sqlite_master WHERE type = 'index' AND name = ?", (name,)).fetchone()
        out[name] = (table[0] if table else None, [(row[2], row[3]) for row in conn.execute(f"PRAGMA index_xinfo({name})") if row[5] == 1])
    return out


EXPECTED_INDEXES = {name: ("videos", columns) for name, columns in RECENCY_INDEXES.items()}


def test_ensure_video_indexes_creates_the_channel_and_account_recency_indexes_and_runs_again_on_a_database_that_has_them(tmp_path):
    conn = sqlite3.connect(tmp_path / "engine.db")
    conn.executescript(CRAWL_SCHEMA.read_text(encoding="utf-8"))
    create_video_embeddings_table(conn)
    assert _key_columns(conn) == {name: (None, []) for name in RECENCY_INDEXES}  # control: only ensure_video_indexes can add them
    # Twice, as a first and a later Engine start on the same database; a bare CREATE INDEX raises on the second.
    ensure_video_indexes(conn)
    ensure_video_indexes(conn)
    # An ASC published_at or video_id, a missing or reordered column, or no index reads differently.
    assert _key_columns(conn) == EXPECTED_INDEXES  # C2
    conn.close()


def test_the_sync_stage_schema_creates_the_channel_and_account_recency_indexes_and_runs_again_on_a_database_that_has_them(tmp_path):
    spec = importlib.util.spec_from_file_location("sync_whitelist_for_test_54_phase1", SYNC_JOB)
    sync_job = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sync_job)
    conn = sqlite3.connect(tmp_path / "whitelist.db")
    for _ in range(2):
        sync_job.ensure_whitelist_schema(conn)
        sync_job.ensure_content_schema(conn)
    assert _key_columns(conn) == EXPECTED_INDEXES  # C2
    conn.close()
