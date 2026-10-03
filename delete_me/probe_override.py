import importlib.util
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location("random_videos_harness", ROOT / "tests" / "active" / "test_random_videos.py")
harness = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(harness)

from data import random_videos, trending  # noqa: E402
from data.ann_ids import compute_ann_id  # noqa: E402

OVERRIDE_EXPECTED = ["B5", "A3", "E", "A2", "C2", "B2", "A1", "B1", "X", "C1"]


def _emulate(conn, private, view=True):
    conn.execute("ATTACH DATABASE ? AS trending_override", (str(private),))
    if view:
        conn.execute("CREATE TEMP VIEW trending_ranks AS SELECT * FROM trending_override.trending_ranks")


def test_probe_a(tmp_path):
    print("sqlite", sqlite3.sqlite_version, "trending attrs", [n for n in dir(trending) if "override" in n])
    main = tmp_path / "main.db"
    plain = harness._ranks_db(main)
    private = tmp_path / "private.db"
    w = sqlite3.connect(private)
    trending.ensure_trending_schema(w)
    for rank, label in enumerate(OVERRIDE_EXPECTED, start=1):
        video_id, host = harness.RANKS[label][:2]
        w.execute("INSERT INTO trending_ranks VALUES (?, ?, ?, 10, 10, 0)", (host, video_id, rank))
    for label in ("GHOST", "U"):
        video_id, host = harness.RANKS[label][:2]
        w.execute("INSERT INTO trending_ranks VALUES (?, ?, 1, 999, 999, 0)", (host, video_id))
    w.commit()
    w.close()
    print("plain page", harness._trending_labels(random_videos.fetch_ordered_page(plain, "trending", 100, 0)))
    print("plain pool", harness._trending_labels(random_videos.fetch_popular_videos(plain, 100)))
    bare = sqlite3.connect(main)
    bare.row_factory = sqlite3.Row
    _emulate(bare, private, view=False)
    print("bare attach page", harness._trending_labels(random_videos.fetch_ordered_page(bare, "trending", 100, 0)))
    prepared = sqlite3.connect(main)
    prepared.row_factory = sqlite3.Row
    _emulate(prepared, private)
    print("view page", harness._trending_labels(random_videos.fetch_ordered_page(prepared, "trending", 100, 0)))
    print("view pool", harness._trending_labels(random_videos.fetch_popular_videos(prepared, 100)))
    print("plain after", harness._trending_labels(random_videos.fetch_ordered_page(plain, "trending", 100, 0)))
    print("main rows", sorted(tuple(r) for r in plain.execute("SELECT * FROM main.trending_ranks")))


def test_probe_b(tmp_path):
    main = tmp_path / "main.db"
    conn = harness._schema(main)
    private = tmp_path / "private.db"
    w = sqlite3.connect(private)
    trending.ensure_trending_schema(w)
    for h in range(30):
        host = f"h{h:02d}.example"
        for rank in range(1, 101):
            video_id = f"v{rank:03d}"
            conn.execute("INSERT INTO videos (video_id, instance_domain, likes, views, popularity, last_checked_at) VALUES (?, ?, ?, ?, ?, 0)", (video_id, host, rank, 10 * rank, rank))
            conn.execute("INSERT INTO video_embeddings VALUES (?, ?, x'00', 1, 'm', 't', ?)", (video_id, host, compute_ann_id(video_id, host)))
            w.execute("INSERT INTO trending_ranks VALUES (?, ?, ?, ?, ?, 0)", (host, video_id, rank, 100 - rank, 1000 - rank))
    for n in range(1000):
        conn.execute("INSERT INTO videos (video_id, instance_domain, likes, views, last_checked_at) VALUES (?, 'u.example', 1, 1, 0)", (f"u{n}",))
        conn.execute("INSERT INTO video_embeddings VALUES (?, 'u.example', x'00', 1, 'm', 't', ?)", (f"u{n}", compute_ann_id(f"u{n}", "u.example")))
    conn.commit()
    w.commit()
    w.close()
    print("main page", random_videos.fetch_ordered_page(conn, "trending", 100, 0))
    print("plain popular plan", harness._plan(conn, "popular"))
    bare = sqlite3.connect(main)
    bare.row_factory = sqlite3.Row
    _emulate(bare, private, view=False)
    print("bare attach page len", len(random_videos.fetch_ordered_page(bare, "trending", 100, 0)))
    prepared = sqlite3.connect(main)
    prepared.row_factory = sqlite3.Row
    _emulate(prepared, private)
    print("view popular plan", harness._plan(prepared, "popular"))
    print("view trending plan", harness._plan(prepared, "trending"))
    # A non-flattened source: the file's ranks copied into an unindexed temp table.
    temp = sqlite3.connect(main)
    temp.row_factory = sqlite3.Row
    _emulate(temp, private, view=False)
    temp.execute("CREATE TEMP TABLE trending_ranks AS SELECT * FROM trending_override.trending_ranks")
    print("unindexed temp copy trending plan", harness._plan(temp, "trending"))


def test_probe_touched_file(tmp_path):
    path = tmp_path / "touched.db"
    path.touch()
    conn = sqlite3.connect(f"file:{path}?mode=rw", uri=True)
    trending.ensure_trending_schema(conn)
    conn.close()
    print("touched file size", path.stat().st_size, "tables", sqlite3.connect(path).execute("SELECT type, name FROM sqlite_master ORDER BY name").fetchall())
