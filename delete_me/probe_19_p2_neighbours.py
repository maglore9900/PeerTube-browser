"""Probe: what the current precompute job writes for the phase-2 fixture at --top-k 2 (legacy layout, full mode)."""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_19_compact_similarity_cache_phase2 import _run_job, source  # noqa: E402,F401


def test_probe(source, tmp_path):
    out = tmp_path / "legacy.db"
    result = _run_job(source, out)
    print(result.returncode, result.stderr[-500:])
    conn = sqlite3.connect(out)
    for row in conn.execute("SELECT source_video_id, similar_video_id, score, rank FROM similarity_items ORDER BY source_video_id, rank"):
        print(row)
    assert False, "probe"
