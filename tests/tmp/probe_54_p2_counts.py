"""Probe: on the dev whitelist.db (read-only), check the checkpoint's Python reference against Phase 1's search_videos_by_tag pages."""
import json
import sqlite3
import subprocess
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_similar_tags import SERVER_DIR, TAG_LIMIT, TAGS, _direct_matches, _is_ordered_subset, _leading  # noqa: E402
from conftest import ENGINE_PY, WHITELIST_DB  # noqa: E402

_CHILD = textwrap.dedent(
    """
    import json, sqlite3, sys, threading, types
    sys.path[:0] = [sys.argv[1], sys.argv[1] + "/api"]
    from data import search
    conn = sqlite3.connect(f"file:{sys.argv[2]}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    server = types.SimpleNamespace(db=conn, db_lock=threading.Lock())
    out = {}
    for tag in json.loads(sys.argv[3]):
        for sort in ("published_at", "views"):
            rows, total = search.search_videos_by_tag(server, tag.upper(), 1, int(sys.argv[4]), sort=sort, include_nsfw=False)
            out[f"{tag}:{sort}"] = {"total": total, "keys": [[r["video_id"], r["instance_domain"]] for r in rows]}
    print(json.dumps(out))
    """
)


def test_probe():
    proc = subprocess.run([str(ENGINE_PY), "-c", _CHILD, str(SERVER_DIR), str(WHITELIST_DB), json.dumps(TAGS), str(TAG_LIMIT)], capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, proc.stderr[-2000:]
    engine = json.loads(proc.stdout)
    conn = sqlite3.connect(f"file:{WHITELIST_DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    report = {}
    for tag in TAGS:
        matches = _direct_matches(conn, tag)
        newest = [tuple(k) for k in engine[f"{tag}:published_at"]["keys"]]
        views = [tuple(k) for k in engine[f"{tag}:views"]["keys"]]
        report[tag] = {
            "total_engine": engine[f"{tag}:published_at"]["total"],
            "total_python": len(matches),
            "newest_exact": newest == _leading(matches, "published_at"),
            "newest_subset": _is_ordered_subset(newest, _leading(matches, "published_at")),
            "views_exact": views == _leading(matches, "views"),
            "views_subset": _is_ordered_subset(views, _leading(matches, "views")),
            "views_not_from_newest": not set(views) <= set(newest),
        }
    assert False, json.dumps(report)
