import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))
from conftest import engine  # noqa: E402,F401


def test_inner(engine):
    assert engine.request("GET", "/api/health")[0] == 200
