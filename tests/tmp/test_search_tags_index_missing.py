"""Inner unit for phase 1: `search_videos_by_tag` raises `SearchIndexMissing`, not a raw SQLite error, on a database with no `videos_fts`, and answers once the index exists.

The checkpoint's fixture always builds the index, so it cannot reach this branch.
"""
from __future__ import annotations

import json
import subprocess
import textwrap

from test_search_tags import ENGINE_PY, SERVER_DIR, _statements

_CHILD = textwrap.dedent(
    """
    import json, sqlite3, sys, threading, types
    sys.path[:0] = [sys.argv[1], sys.argv[1] + "/api"]
    from data import search

    out = []
    for with_index in (False, True):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        for sql, params in json.loads(sys.argv[2]):
            if with_index or "videos_fts" not in sql:
                conn.execute(sql, params)
        server = types.SimpleNamespace(db=conn, db_lock=threading.Lock())
        try:
            out.append(search.search_videos_by_tag(server, "linux", 1, 50)[1])
        except Exception as exc:
            out.append(type(exc).__name__)
    print(json.dumps(out))
    """
)


def test_a_database_without_the_fts_index_raises_search_index_missing():
    proc = subprocess.run([str(ENGINE_PY), "-c", _CHILD, str(SERVER_DIR), json.dumps(_statements())], capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    without_index, with_index = json.loads(proc.stdout)
    assert with_index == 6  # control: the same call answers once the index exists
    assert without_index == "SearchIndexMissing"
