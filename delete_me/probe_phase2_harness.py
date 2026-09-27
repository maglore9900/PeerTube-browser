import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import test_10_normalise_instance_hosts_phase2 as checkpoint  # noqa: E402
from test_10_normalise_instance_hosts_phase2 import *  # noqa: E402,F401,F403

checkpoint.DURABLE = Path(__file__).parent / "probe_durable_host.py"


@pytest.fixture(autouse=True, params=["correct", "skip", "mtime_only", "git_only", "no_compare", "no_dist_check", "subset", "equal_is_stale"])
def variant(request, monkeypatch):
    monkeypatch.setenv("PROBE_VARIANT", request.param)
