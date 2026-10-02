import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from test_20_request_lifecycle_logs_phase2 import _run_child, _is_probe


def test_probe_keepalive(tmp_path):
    report = _run_child(tmp_path)
    keep = report["keepalive"]
    records = [json.loads(line) for line in keep["lines"]]
    print("PORTS", keep["client_ports"], "MS", keep["ms"], "STATUSES", keep["statuses"], "SETTLED", keep["settled"])
    print("MARKERS", [index for index, record in enumerate(records) if _is_probe(record)], "N", len(records))
    for record in records:
        print("REC", record.get("event"), record.get("message"), record.get("request_id"))
    assert False
