"""Probe: what each read reports for likes and whether it carries interaction_signal_score, today."""
from test_37_hot_popular_drop_local_signal_phase2 import _by_label, _reads, _two_video_db


def test_probe(tmp_path):
    conn, label_of = _two_video_db(tmp_path)
    seen = {name: {label: (row["likes"], "interaction_signal_score" in row) for label, row in _by_label(rows, label_of).items()}
            for name, rows in _reads(conn).items()}
    assert False, seen
