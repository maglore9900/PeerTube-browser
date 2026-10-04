"""Probe: the edited route and worker import, and the route and worker no longer carry their own fetch code."""
import importlib
import importlib.util
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))

import test_internal_translate  # noqa: E402,F401  (puts engine/server and api on sys.path)
from test_translate_worker import WORKER  # noqa: E402


def test_imports():
    route = importlib.import_module("handlers.internal_translate")
    spec = importlib.util.spec_from_file_location("translate_worker_probe", WORKER)
    worker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(worker)
    source_fetch = importlib.import_module("data.source_fetch")
    print("route has", [name for name in ("fetch_bounded", "SameHostRedirectHandler", "build_opener", "FETCH_MAX_BYTES", "same_host_https") if hasattr(route, name)])
    print("worker has", [name for name in ("build_opener", "Request", "MEDIA_SOCKET_TIMEOUT_SECONDS", "_TLD") if hasattr(worker, name)])
    assert route.fetch_bounded is source_fetch.fetch_bounded
    assert worker.media_host is source_fetch.media_host
