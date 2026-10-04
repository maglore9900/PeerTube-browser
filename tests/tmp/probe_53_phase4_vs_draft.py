from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))

from test_fetch_trending import _load_job  # noqa: E402
import test_53_source_instance_fetch_adapter_phase4 as checkpoint  # noqa: E402

from data import source_fetch  # noqa: E402

VARIANTS = {
    "draft": dict(cap=500_000, use_cap=True, deadline=True, ua=True, socket=True),
    "default-cap": dict(cap=500_000, use_cap=False, deadline=True, ua=True, socket=True),
    "cap-over-default": dict(cap=3_000_000, use_cap=False, deadline=True, ua=True, socket=True),
    "default-deadline": dict(cap=500_000, use_cap=True, deadline=False, ua=True, socket=True),
    "no-ua": dict(cap=500_000, use_cap=True, deadline=True, ua=False, socket=True),
    "default-socket": dict(cap=500_000, use_cap=True, deadline=True, ua=True, socket=False),
}


@pytest.fixture(params=list(VARIANTS))
def job(request):
    module = _load_job(f"fetch_trending_{request.param}", "fetch-trending.py")
    v = VARIANTS[request.param]
    module.TRENDING_MAX_BYTES = v["cap"]

    def fetch_host_list(host, timeout_s, max_retries):
        kwargs = {}
        if v["use_cap"]:
            kwargs["max_bytes"] = v["cap"]
        if v["deadline"]:
            kwargs["deadline_seconds"] = timeout_s
        if v["socket"]:
            kwargs["socket_timeout"] = timeout_s
        if v["ua"]:
            kwargs["headers"] = {"User-Agent": "peertube-browser-trending/1.0"}
        for _ in range(max_retries + 1):
            try:
                body = json.loads(source_fetch.fetch_bounded(host, module.TRENDING_PATH, **kwargs))
                data = body.get("data") if isinstance(body, dict) else None
                if not isinstance(data, list):
                    raise ValueError("no data list")
                return data
            except (source_fetch.SourceFetchFailed, ValueError):
                pass
        return None

    module.fetch_host_list = fetch_host_list
    return module


for _name in dir(checkpoint):
    if _name.startswith("test_"):
        globals()[_name] = getattr(checkpoint, _name)
