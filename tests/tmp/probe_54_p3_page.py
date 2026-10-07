"""Probe: how many rows the session Engine serves for the newest linux page, against the Python reference."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_blocks_tags import TAG_SEARCH, _keys, _newest_tagged  # noqa: E402
from conftest import dataset, engine, shared_trending_before, trending_seed  # noqa: E402,F401


def test_probe(engine, dataset):
    status, body = engine.request("GET", TAG_SEARCH)
    newest = _newest_tagged(dataset)
    served = _keys(body.get("rows") or [])
    assert False, (status, len(served), len(newest), served == [k for k in newest if k in set(served)])
