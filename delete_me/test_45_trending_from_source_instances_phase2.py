"""`mode=trending` walks catalogue rows in `trending_ranks` order and ends on an empty page, and the popular layer's pool is the head of that order.

On a temp DB holding the labelled rows in `RANKS` (four hosts, ranks with gaps, a ranked row absent from `videos`, a ranked row with no embedding, an embedded row with no rank, an NSFW row and a row at the error threshold; crawled likes and popularity run opposite to the ranks):

- `fetch_ordered_page(conn, "trending", ...)`, with and without an error threshold of 3 and the NSFW filter, and with `idx_trending_ranks_order` present and dropped, paged at 1, 2 and 3 rows to one page past the end, concatenates with no repeat into the hand-derived `EXPECTED` order (rank, then listed likes, listed views, `video_id` and domain, all descending but rank), and the page at the end offset is `[]`. A 100-row page holds exactly the ranked catalogue rows: never the row absent from `videos`, the unembedded row or the unranked one.
- With `trending_ranks` emptied, the Trending page and `fetch_popular_videos` are both `[]` while the Popular order still serves the catalogue.
- `fetch_popular_videos(conn, n, ...)` is the hand-derived head of `EXPECTED` and equals `fetch_ordered_page(conn, "trending", n, 0, ...)` row for row, for every n up to one past the order and every filter combination.
- On a 4,000-row DB, the query `fetch_ordered_page` runs for a Trending page has an `EXPLAIN QUERY PLAN` naming `idx_trending_ranks_order` and no `TEMP B-TREE`; the same capture for Popular shows the temp B-tree (control).
- Every order in `ORDERED_FEED_ORDER_BY` serves rows through `fetch_ordered_page`, and `ORDERED_FEED_SOURCE` holds a source for each of them and no other.

Under the Engine interpreter, the real `SimilarHandler._handle_similar` on a stub server over that DB serves `mode=trending` as the order under its threshold and NSFW filter (`nsfw=1` keeping the flagged row) with `seed` `{}`, continues it past an excluded head, and answers an empty page with `seed` `{}` once every ranked row is excluded or the ranks table is empty, where `mode=random` on the same DB serves rows. The real `MixingRecommendationStrategy` on `RECOMMENDATION_PIPELINE`, with the real `PopularVideosGenerator` over `fetch_popular_videos` and stub other layers, serves no popular row once `trending_ranks` is emptied though the catalogue holds rows, gives `guest_home` a full 48-row batch and `home` with likes 43 rows, short by exactly popular's 5-row share; with ranks present, popular fills its 5 slots (control).

Against the session Engine on the repo's `whitelist.db`, whose ranks the active suite's seed fixture writes: `mode=hot` is answered 400 with exactly the five modes, `trending` in place of `hot`; three `mode=trending` pages walked with `exclude` are full, disjoint, the head of `fetch_ordered_page(dataset, "trending", ...)` less moderated rows, and in rank, listed likes, listed views, `video_id`, domain order by the stored ranks; `mode=trending` serves a flagged row with `nsfw=1` and none, on a non-empty page, without exactly `nsfw=1`.
"""
from __future__ import annotations

import importlib.util
import json
import sqlite3
import subprocess
import sys
import textwrap
from pathlib import Path
from urllib.parse import quote

import pytest

ROOT = Path(__file__).resolve().parents[2]
ACTIVE_DIR = ROOT / "tests" / "active"
if str(ACTIVE_DIR) not in sys.path:
    sys.path.insert(0, str(ACTIVE_DIR))
import conftest as active  # noqa: E402

# Every active-suite fixture is registered here, so `engine` and `dataset` bring along whatever they take, the rank seed the build adds included.
globals().update({name: value for name, value in vars(active).items() if type(value).__name__ == "FixtureFunctionDefinition"})

SERVER_DIR = ROOT / "engine" / "server"
# The Engine dirs go on sys.path after conftest's import: both trees hold a `server` module.
for _path in (SERVER_DIR, SERVER_DIR / "api"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))
from data import random_videos  # noqa: E402
from data.ann_ids import compute_ann_id, create_video_embeddings_table  # noqa: E402
from data.moderation import ensure_moderation_schema  # noqa: E402
from data.trending import ensure_trending_schema  # noqa: E402

ENGINE_PY = active.ENGINE_PY
CRAWL_SCHEMA = ROOT / "engine" / "crawler" / "schema.sql"
THRESHOLD = 3
# label: (video_id, instance_domain, rank or None, listed likes, listed views, nsfw, error_count, in videos, embedded).
RANKS = {
    "C1": ("c1", "c.example", 1, 70, 10, 0, 0, True, True),
    "X": ("x1", "d.example", 1, 60, 10, 1, 0, True, True),
    "B1": ("b1", "b.example", 1, 50, 900, None, 0, True, True),
    "A1": ("a1", "a.example", 1, 50, 100, 0, 0, True, True),
    "B2": ("v-z", "b.example", 2, 10, 10, 0, 0, True, True),
    "C2": ("v-m", "c.example", 2, 10, 10, 0, 0, True, True),
    "A2": ("v-m", "a.example", 2, 10, 10, 0, 0, True, True),
    "E": ("v-a", "d.example", 2, 10, 10, 0, THRESHOLD, True, True),
    "A3": ("a3", "a.example", 3, 500, 5000, 0, 0, True, True),
    "B5": ("b5", "b.example", 5, 400, 4000, 0, 0, True, True),
    "GHOST": ("g1", "f.example", 1, 999, 999, 0, 0, False, False),
    "U": ("u1", "e.example", 1, 999, 999, 0, 0, True, False),
    "N": ("n1", "b.example", None, 0, 0, 0, 0, True, True),
}
# Derived by hand from RANKS. Rank 1: C1 (70 listed likes), X (60), then B1 and A1 on 50 with B1's 900 listed views first. Rank 2: all on 10 likes and 10 views, so video_id descending puts v-z (B2), then the two v-m with c.example (C2) before a.example (A2), then v-a (E). Rank 3: A3, whatever its 500 likes. Rank 5: B5. GHOST is not in videos, U has no embedding and N no rank, so none is served.
EXPECTED = ["C1", "X", "B1", "A1", "B2", "C2", "A2", "E", "A3", "B5"]
# Keyed by (error_threshold, include_nsfw): the threshold drops E, the filter drops X.
FILTERED = {
    (None, True): EXPECTED,
    (None, False): ["C1", "B1", "A1", "B2", "C2", "A2", "E", "A3", "B5"],
    (THRESHOLD, True): ["C1", "X", "B1", "A1", "B2", "C2", "A2", "A3", "B5"],
    (THRESHOLD, False): ["C1", "B1", "A1", "B2", "C2", "A2", "A3", "B5"],
}
FILTERS = list(FILTERED)
LABEL_OF = {(spec[0], spec[1]): label for label, spec in RANKS.items()}


def _schema(path: Path) -> sqlite3.Connection:
    """A whitelist-shaped DB: the crawler schema with the Engine's popularity column, the shared embeddings table, moderation and trending ranks."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(CRAWL_SCHEMA.read_text(encoding="utf-8"))
    conn.execute("ALTER TABLE videos ADD COLUMN popularity REAL NOT NULL DEFAULT 0")
    create_video_embeddings_table(conn)
    ensure_moderation_schema(conn)
    ensure_trending_schema(conn)
    return conn


def _ranks_db(path: Path, ranks_index: bool = True) -> sqlite3.Connection:
    """The RANKS rows, stored last expected first, with crawled likes, views and popularity rising along EXPECTED and highest on the unranked N, so Hot or Popular comes out reversed."""
    conn = _schema(path)
    if not ranks_index:
        # A walk on the index already runs in the full tie-break order, so an ORDER BY on rank alone passes there (observed); without it, only the ORDER BY orders ties.
        conn.execute("DROP INDEX idx_trending_ranks_order")
    for label in reversed(list(RANKS)):
        video_id, host, rank, likes, views, nsfw, errors, in_videos, embedded = RANKS[label]
        crawled = 100 if label == "N" else EXPECTED.index(label) + 1 if label in EXPECTED else 200
        if in_videos:
            conn.execute(
                "INSERT INTO videos (video_id, video_uuid, instance_domain, channel_id, likes, views, nsfw, popularity, error_count, published_at, last_checked_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)",
                (video_id, f"uuid-{label}", host, f"ch-{label}", crawled, 10 * crawled, nsfw, float(crawled), errors, 1_700_000_000_000),
            )
        if embedded:
            conn.execute("INSERT INTO video_embeddings VALUES (?, ?, x'00', 1, 'm', 't', ?)", (video_id, host, compute_ann_id(video_id, host)))
        if rank is not None:
            conn.execute("INSERT INTO trending_ranks VALUES (?, ?, ?, ?, ?, 0)", (host, video_id, rank, likes, views))
    conn.commit()
    return conn


def _labels(rows: list[dict]) -> list[str]:
    return [LABEL_OF.get((row["video_id"], row["instance_domain"]), row["video_id"]) for row in rows]


@pytest.mark.parametrize("ranks_index", (True, False), ids=("ranks-index", "no-ranks-index"))
@pytest.mark.parametrize("threshold,include_nsfw", FILTERS)
def test_trending_pages_walk_ranked_catalogue_rows_by_rank_then_listed_likes_views_video_id_and_domain(tmp_path, threshold, include_nsfw, ranks_index):
    conn = _ranks_db(tmp_path / "ranks.db", ranks_index)
    expected = FILTERED[(threshold, include_nsfw)]
    for limit in (1, 2, 3):
        rows = []
        # One offset past the last row, so a page beyond the end must come back empty.
        for offset in range(0, len(expected) + limit, limit):
            page = random_videos.fetch_ordered_page(conn, "trending", limit, offset, error_threshold=threshold, include_nsfw=include_nsfw)
            assert len(page) <= limit, (limit, offset)
            rows += page
        labels = _labels(rows)
        assert len(labels) == len(set(labels)), (limit, labels)  # C1 no row repeated
        assert labels == expected, (limit, labels)  # C1 no row skipped, in rank, listed likes, listed views, video_id, domain order
        assert random_videos.fetch_ordered_page(conn, "trending", limit, len(expected), error_threshold=threshold, include_nsfw=include_nsfw) == []  # C1 the order ends, with no fallback


def test_a_trending_page_holds_only_ranked_catalogue_rows(tmp_path):
    conn = _ranks_db(tmp_path / "ranks.db")
    # Control: GHOST is ranked but has no videos row, U has a videos row but no embedding, and N is embedded with no rank.
    assert {tuple(row) for row in conn.execute("SELECT video_id, instance_domain FROM trending_ranks WHERE video_id IN ('g1', 'u1', 'n1')")} == {("g1", "f.example"), ("u1", "e.example")}
    served = _labels(random_videos.fetch_ordered_page(conn, "trending", 100, 0))
    assert set(served) == set(EXPECTED), served  # C1
    assert not {"GHOST", "U", "N"} & set(served), served  # C1 never a ranked row outside the catalogue, never an unranked one


def test_an_empty_ranks_table_gives_an_empty_trending_page_and_an_empty_popular_pool(tmp_path):
    conn = _ranks_db(tmp_path / "ranks.db")
    # Control: with ranks present both read rows on this connection, so the two empty results below are the emptied ranks and not a stub.
    assert random_videos.fetch_ordered_page(conn, "trending", 100, 0)
    assert random_videos.fetch_popular_videos(conn, 100)
    conn.execute("DELETE FROM trending_ranks")
    conn.commit()
    # Control: the catalogue still serves, so an empty page is the empty order and not an empty DB.
    assert len(random_videos.fetch_ordered_page(conn, "popular", 100, 0)) == 11
    assert random_videos.fetch_ordered_page(conn, "trending", 100, 0) == []  # C1 no fallback to another order
    assert random_videos.fetch_popular_videos(conn, 100) == []  # C2


@pytest.mark.parametrize("threshold,include_nsfw", FILTERS)
def test_the_popular_pool_of_size_n_is_the_first_n_rows_of_the_trending_order_under_the_same_filters(tmp_path, threshold, include_nsfw):
    conn = _ranks_db(tmp_path / "ranks.db")
    expected = FILTERED[(threshold, include_nsfw)]
    for n in range(1, len(expected) + 2):
        pool = random_videos.fetch_popular_videos(conn, n, error_threshold=threshold, include_nsfw=include_nsfw)
        assert _labels(pool) == expected[:n], (n, _labels(pool))  # C2 hand-derived head, not the popularity order N leads
        assert pool == random_videos.fetch_ordered_page(conn, "trending", n, 0, error_threshold=threshold, include_nsfw=include_nsfw), n  # C2 same rows, same shape


class _Recorder:
    """A connection that records each statement and its parameters before running it."""

    def __init__(self, inner: sqlite3.Connection):
        self.inner = inner
        self.calls: list[tuple[str, list]] = []

    def execute(self, sql, params=()):
        self.calls.append((sql, list(params)))
        return self.inner.execute(sql, params)

    def __getattr__(self, name):
        return getattr(self.inner, name)


def _plan(conn: sqlite3.Connection, order: str) -> list[str]:
    """The EXPLAIN QUERY PLAN details of the statement fetch_ordered_page runs for one filtered 50-row page past the head."""
    recorder = _Recorder(conn)
    rows = random_videos.fetch_ordered_page(recorder, order, 50, 100, error_threshold=THRESHOLD, include_nsfw=False)
    assert len(rows) == 50 and len(recorder.calls) == 1, (len(rows), len(recorder.calls))  # control: one real query read a full page
    sql, params = recorder.calls[0]
    return [row[3] for row in conn.execute("EXPLAIN QUERY PLAN " + sql, params)]


def test_a_trending_page_walks_the_ranks_index_without_sorting(tmp_path):
    conn = _schema(tmp_path / "plan.db")
    # 30 hosts of 100 ranked catalogue rows, and 1,000 embedded rows with no rank.
    for h in range(30):
        host = f"h{h:02d}.example"
        for rank in range(1, 101):
            video_id = f"v{rank:03d}"
            conn.execute("INSERT INTO videos (video_id, instance_domain, likes, views, popularity, last_checked_at) VALUES (?, ?, ?, ?, ?, 0)", (video_id, host, rank, 10 * rank, rank))
            conn.execute("INSERT INTO video_embeddings VALUES (?, ?, x'00', 1, 'm', 't', ?)", (video_id, host, compute_ann_id(video_id, host)))
            conn.execute("INSERT INTO trending_ranks VALUES (?, ?, ?, ?, ?, 0)", (host, video_id, rank, 100 - rank, 1000 - rank))
    for n in range(1000):
        conn.execute("INSERT INTO videos (video_id, instance_domain, likes, views, last_checked_at) VALUES (?, 'u.example', 1, 1, 0)", (f"u{n}",))
        conn.execute("INSERT INTO video_embeddings VALUES (?, 'u.example', x'00', 1, 'm', 't', ?)", (f"u{n}", compute_ann_id(f"u{n}", "u.example")))
    conn.commit()
    # Control: the plan shows a sort where an order has no index (observed: USE TEMP B-TREE FOR ORDER BY).
    assert any("TEMP B-TREE" in detail for detail in _plan(conn, "popular"))
    details = _plan(conn, "trending")
    assert any("idx_trending_ranks_order" in detail for detail in details), details  # C1
    assert not any("TEMP B-TREE" in detail for detail in details), details  # C1


def test_every_ordered_feed_has_a_source_and_serves_catalogue_rows(tmp_path):
    conn = _ranks_db(tmp_path / "ranks.db")
    for order in random_videos.ORDERED_FEED_ORDER_BY:
        assert random_videos.fetch_ordered_page(conn, order, 100, 0), order  # control: each ordered feed serves rows through fetch_ordered_page
    assert set(getattr(random_videos, "ORDERED_FEED_SOURCE", {})) == set(random_videos.ORDERED_FEED_ORDER_BY)  # C1


# Runs under the Engine interpreter: importing handlers.similar needs numpy and faiss, which only its pixi env carries.
# The stub server holds what the ordered-feed path reads; the HTTP transport is replaced so a response is read as the status and body it sends.
_HANDLER_CHILD = textwrap.dedent(
    """
    import io, json, sqlite3, sys, threading, types
    sys.path[:0] = [sys.argv[1], sys.argv[2]]
    from handlers import similar
    from request_context import set_request_excluded_keys

    class Handler(similar.SimilarHandler):
        def __init__(self, server):
            self.server = server
            self.wfile = io.BytesIO()
            self.statuses = []

        def send_response(self, status, message=None):
            self.statuses.append(status)

        def send_header(self, name, value):
            pass

        def end_headers(self):
            pass

    out = []
    for db_path, params, excluded in json.loads(sys.argv[3]):
        db = sqlite3.connect(db_path)
        db.row_factory = sqlite3.Row
        # No random cache, so the random feed reads whitelist rows: a fallback would fill the page.
        server = types.SimpleNamespace(default_limit=20, refresh_similarity_cache=False, recommendations_debug_enabled=False, db=db, db_lock=threading.Lock(), video_error_threshold=int(sys.argv[4]), embeddings_count=0, random_cache_db=None, random_cache_lock=threading.Lock())
        handler = Handler(server)
        set_request_excluded_keys(set(excluded))
        similar.SimilarHandler._handle_similar(handler, params)
        out.append({"statuses": handler.statuses, "body": json.loads(handler.wfile.getvalue() or b"null")})
        db.close()
    print(json.dumps(out))
    """
)


def _handle(cases: list[list]) -> list[dict]:
    assert ENGINE_PY.exists(), f"Engine interpreter missing at {ENGINE_PY}; run `pixi install` in engine/"
    run = subprocess.run([str(ENGINE_PY), "-c", _HANDLER_CHILD, str(SERVER_DIR), str(SERVER_DIR / "api"), json.dumps(cases), str(THRESHOLD)], cwd=SERVER_DIR / "api", capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stderr[-2000:]  # control: the Engine's interpreter imported the handler and ran every case
    return json.loads(run.stdout.strip().splitlines()[-1])


def _key(label: str) -> str:
    return f"{RANKS[label][0]}::{RANKS[label][1]}"


def test_the_handler_serves_trending_until_the_ranked_rows_run_out_then_an_empty_page_not_a_fallback(tmp_path):
    ranked = str(tmp_path / "ranks.db")
    _ranks_db(Path(ranked)).close()
    empty = str(tmp_path / "empty.db")
    _ranks_db(Path(empty)).execute("DELETE FROM trending_ranks").connection.commit()
    served = FILTERED[(THRESHOLD, False)]
    trending = {"mode": ["trending"], "limit": ["20"]}
    random_case, plain, flagged, past_head, run_out, emptied = _handle([
        [empty, {"mode": ["random"], "limit": ["20"]}, []],
        [ranked, trending, []],
        [ranked, {**trending, "nsfw": ["1"]}, []],
        [ranked, trending, [_key(label) for label in served[:3]]],
        [ranked, trending, [_key(label) for label in served]],
        [empty, trending, []],
    ])
    # Control: on the emptied DB the random feed still serves rows, so a fallback would show as a non-empty page.
    assert random_case["statuses"] == [200] and random_case["body"]["seed"] == {"random": True} and random_case["body"]["rows"], random_case
    for case in (plain, flagged, past_head, run_out, emptied):
        assert case["statuses"] == [200] and case["body"]["seed"] == {}, case  # C1 the ordered feed answered, not the random fallback
    assert _labels(plain["body"]["rows"]) == served  # C1 the Engine's threshold and the default NSFW filter applied to the rank order
    assert _labels(flagged["body"]["rows"]) == FILTERED[(THRESHOLD, True)]  # C1
    assert _labels(past_head["body"]["rows"]) == served[3:]  # C1 the walk continues past the excluded head
    assert run_out["body"]["rows"] == []  # C1 every ranked row excluded: an empty page
    assert emptied["body"]["rows"] == []  # C1 no ranked rows: an empty page


# Runs under the Engine interpreter, which the mixer's imports need. The popular layer is the real generator over the real fetch_popular_videos on a temp DB; the other layers stand in for generators whose output size is the mixer's input, each returning `limit` distinct rows on h.example.
_MIX_CHILD = textwrap.dedent(
    """
    import json, sqlite3, sys, threading, types
    sys.path[:0] = [sys.argv[1], sys.argv[2]]
    import server_config
    from data.random_videos import fetch_popular_videos
    from recommendations.candidates.popular_videos import PopularVideosDeps, PopularVideosGenerator
    from recommendations.keys import like_key
    from recommendations.mixer import MixerDeps, MixingRecommendationStrategy

    class Layer:
        def __init__(self, name):
            self.name = name

        def get_candidates(self, server, user_id, limit, refresh_cache=False, config=None):
            return [{"video_id": f"{self.name}-{i}", "instance_domain": "h.example", "channel_id": f"{self.name}-ch-{i}", "views": 10, "likes": 1, "published_at": 1700000000000, "similarity_score": 0.5} for i in range(limit)]

    likes = [{"video_id": "liked-1", "instance_domain": "h.example"}]
    out = {}
    for case, (with_likes, db_path) in json.loads(sys.argv[3]).items():
        db = sqlite3.connect(db_path)
        db.row_factory = sqlite3.Row
        server = types.SimpleNamespace(db=db, db_lock=threading.Lock())
        recent_likes = lambda user_id, limit, w=with_likes: list(likes) if w else []
        popular = PopularVideosGenerator(PopularVideosDeps(fetch_popular_videos=fetch_popular_videos, fetch_recent_likes=recent_likes, fetch_embeddings_by_ids=lambda conn, rows: {}, like_key=like_key, max_likes=50))
        layers = {name: Layer(name) for name in ("random", "explore", "exploit", "fresh")}
        layers["popular"] = popular
        deps = MixerDeps(like_key=like_key, fetch_recent_likes=recent_likes, max_likes=50, fetch_embeddings_by_ids=lambda server, rows: {}, fetch_dislike_centroids=lambda: None, fetch_excluded_keys=set, dislike_similarity_floor=0.0)
        rows = MixingRecommendationStrategy(layers, server_config.RECOMMENDATION_PIPELINE, deps).generate_recommendations(server, "u", 0, mode="home")
        out[case] = {"count": len(rows), "distinct": len({like_key(r) for r in rows}), "popular_served": sum(1 for r in rows if r["instance_domain"] != "h.example")}
        db.close()
    print(json.dumps(out))
    """
)


def test_the_mix_answers_with_an_empty_popular_layer_full_for_guests_and_short_by_popular_s_share_with_likes(tmp_path):
    assert ENGINE_PY.exists(), f"Engine interpreter missing at {ENGINE_PY}; run `pixi install` in engine/"
    ranked = str(tmp_path / "ranks.db")
    _ranks_db(Path(ranked)).close()
    empty = str(tmp_path / "empty.db")
    emptied = _ranks_db(Path(empty))
    emptied.execute("DELETE FROM trending_ranks")
    emptied.commit()
    # Control: the emptied DB still serves its catalogue, so a popular layer with nothing to serve is the empty ranks and not an empty DB.
    assert len(random_videos.fetch_ordered_page(emptied, "popular", 100, 0)) == 11
    emptied.close()
    cases = {"guest_empty": [False, empty], "home_empty": [True, empty], "home_full": [True, ranked]}
    run = subprocess.run([str(ENGINE_PY), "-c", _MIX_CHILD, str(SERVER_DIR), str(SERVER_DIR / "api"), json.dumps(cases)], cwd=SERVER_DIR / "api", capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stderr[-2000:]
    out = json.loads(run.stdout.strip().splitlines()[-1])
    # Control: with likes and ranked rows the home batch is full and the real popular layer fills its 5 gathered slots.
    assert out["home_full"] == {"count": 48, "distinct": 48, "popular_served": 5}, out["home_full"]
    assert out["home_empty"]["popular_served"] == 0, out["home_empty"]  # C2 an empty ranks table gives the popular layer an empty pool, though the catalogue holds rows
    assert out["home_empty"]["count"] == out["home_empty"]["distinct"] == 48 - 5, out["home_empty"]  # R2 non-empty, short by exactly popular's share
    assert out["guest_empty"] == {"count": 48, "distinct": 48, "popular_served": 0}, out["guest_empty"]  # R2 an empty pool still gives guests a full batch


def _server_config():
    spec = importlib.util.spec_from_file_location("engine_server_config", SERVER_DIR / "api" / "server_config.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SERVER_CONFIG = _server_config()
FEED_PAGE = 12
REFERENCE_DEPTH = 200
# The largest page the Engine serves: twice its default.
LIVE_LIMIT = 2 * int(SERVER_CONFIG.BATCH_SIZE)
# Their own rate-limit buckets, clear of the 192.0.2.x addresses tests/active uses.
MODE_HEADERS = {"X-Client-IP": "192.0.2.231"}
ORDERED_HEADERS = {"X-Client-IP": "192.0.2.232"}
NSFW_HEADERS = {"X-Client-IP": "192.0.2.233"}


def _post(engine, path: str, headers: dict[str, str], body: dict) -> dict:
    status, payload = engine.request("POST", path, headers=headers, body=body)
    assert status == 200 and isinstance(payload, dict) and "rows" in payload, (path, status, payload)
    return payload


def _keys(rows) -> list[tuple[str, str]]:
    return [(r["video_id"], r["instance_domain"]) for r in rows]


def _exclude(keys: list[tuple[str, str]]) -> list[dict[str, str]]:
    return [{"id": video_id, "host": host} for video_id, host in keys]


def test_mode_hot_is_refused_400_with_trending_among_the_allowed_modes(engine):
    status, body = engine.request("POST", f"/recommendations?mode=trending&limit={FEED_PAGE}", headers=MODE_HEADERS, body={})
    assert status == 200 and "rows" in body, (status, body)  # C1 trending is a mode the Engine serves
    status, body = engine.request("POST", f"/recommendations?mode=hot&limit={FEED_PAGE}", headers=MODE_HEADERS, body={})
    assert (status, body) == (400, {"error": "Unknown mode", "allowed": ["recommendations", "trending", "recent", "random", "popular"]})  # C1


def _reference(dataset) -> list[tuple[str, str]]:
    """The Trending order's first rows as fetch_ordered_page reads them from whitelist.db for a request without nsfw, less those the Engine's moderation removes."""
    denied = {row["host"].lower() for row in dataset.execute("SELECT host FROM instance_denylist WHERE is_active = 1")}
    blocked = {(row["channel_id"], row["instance_domain"].lower()) for row in dataset.execute("SELECT channel_id, instance_domain FROM channel_moderation WHERE status = 'blocked'")}
    rows = random_videos.fetch_ordered_page(dataset, "trending", REFERENCE_DEPTH, 0, error_threshold=SERVER_CONFIG.VIDEO_ERROR_THRESHOLD, include_nsfw=False)
    return _keys(r for r in rows if r["instance_domain"].lower() not in denied and (r["channel_id"], r["instance_domain"].lower()) not in blocked)


def _in_rank_order(dataset, keys: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """The keys sorted by their stored rank, then listed likes, listed views, video_id and domain, all descending but rank; every key must be ranked."""
    stored = {}
    for key in keys:
        row = dataset.execute("SELECT rank, likes, views FROM trending_ranks WHERE video_id = ? AND instance_domain = ?", key).fetchone()
        assert row is not None, f"served row {key} has no rank"
        stored[key] = tuple(row)
    ordered = sorted(keys, key=lambda k: k[1], reverse=True)
    ordered.sort(key=lambda k: k[0], reverse=True)
    ordered.sort(key=lambda k: (stored[k][0], -stored[k][1], -stored[k][2]))
    return ordered


def test_trending_pages_after_excluded_pages_continue_the_rank_order_with_no_row_repeated(engine, dataset):
    reference = _reference(dataset)
    # Rehearsed read-only with the plan's trending_seed SELECT on today's whitelist.db: 195 of the first 200 rows pass the filters.
    assert len(reference) >= 4 * FEED_PAGE, len(reference)  # control: the order holds three pages and a last page beyond them
    path = f"/recommendations?mode=trending&limit={FEED_PAGE}"
    plain = _post(engine, path, ORDERED_HEADERS, {})
    second = _post(engine, path, ORDERED_HEADERS, {"exclude": _exclude(_keys(plain["rows"]))})
    # Page 3 also excludes the reference's last page, which lies past it: a walk jumping len(exclude) rows ahead starts page 3 at the wrong row.
    third = _post(engine, path, ORDERED_HEADERS, {"exclude": _exclude(_keys(plain["rows"]) + _keys(second["rows"]) + reference[-FEED_PAGE:])})
    assert _reference(dataset) == reference  # control: the ranks did not move while the requests ran

    for payload in (plain, second, third):
        assert "random" not in payload["seed"] and "mode" not in payload["seed"], payload["seed"]  # C1 the ordered feed, not a fallback or a home page
    first, following, last = _keys(plain["rows"]), _keys(second["rows"]), _keys(third["rows"])
    assert len(first) == len(following) == len(last) == FEED_PAGE, (len(first), len(following), len(last))  # C1
    assert not set(first) & set(following) and not set(first + following) & set(last)  # C1 no row repeated
    assert first + following + last == reference[: 3 * FEED_PAGE]  # C1 no row skipped
    served = first + following + last
    assert served == _in_rank_order(dataset, served)  # C1 rank, listed likes, listed views, video_id, domain by the stored ranks


@pytest.fixture(scope="module")
def nsfw_flagged(dataset) -> set[tuple[str, str]]:
    keys = {(r["video_id"], r["instance_domain"]) for r in dataset.execute("SELECT video_id, instance_domain FROM videos WHERE nsfw = 1")}
    assert keys, "control: whitelist.db flags no video nsfw = 1"
    return keys


# Every value but exactly "1"; parse_qs drops the empty one, so it arrives as missing.
NSFW_VALUES = {"missing": "", "empty": "&nsfw=", "0": "&nsfw=0", "true": "&nsfw=true", "space-1": f"&nsfw={quote(' 1')}"}


@pytest.mark.parametrize("nsfw", NSFW_VALUES)
def test_trending_without_exactly_nsfw_1_serves_no_flagged_row_where_nsfw_1_serves_some(engine, nsfw_flagged, nsfw):
    path = f"/recommendations?mode=trending&limit={LIVE_LIMIT}"
    shown = set(_keys(_post(engine, f"{path}&nsfw=1", NSFW_HEADERS, {})["rows"])) & nsfw_flagged
    # Rehearsed read-only with the plan's trending_seed SELECT: exactly one flagged row in the first 96, so this control is tight.
    assert shown, "control: mode=trending with nsfw=1 served no flagged row"
    keys = _keys(_post(engine, f"{path}{NSFW_VALUES[nsfw]}", NSFW_HEADERS, {})["rows"])
    assert keys, "mode=trending served an empty page"  # C1
    assert not set(keys) & nsfw_flagged, sorted(set(keys) & nsfw_flagged)[:5]  # C1
