"""Probe: print the phase-2 lifecycle child's report against the current tree."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_20_request_lifecycle_logs_phase2 import _run_child  # noqa: E402


def test_probe_report(tmp_path):
    report = _run_child(tmp_path)
    print("PORTS", report["ports"])
    for request in report["requests"]:
        print("REQ", request["status"], request["settled"], round(request["ms"], 1))
        for line in request["lines"]:
            print("  ", line[:300])
    print("KEEP", report["keepalive"]["statuses"], report["keepalive"]["settled"])
    for line in report["keepalive"]["lines"]:
        print("  ", line[:300])
    assert False, "probe"
