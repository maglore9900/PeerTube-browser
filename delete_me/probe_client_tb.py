import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_19_timestamped_request_logs_phase4 import EXCEPTION_TEXT_RE, _log_records  # noqa: E402


def test_probe(monkeypatch):
    lines = _log_records(monkeypatch, None)
    tb = json.loads(lines[1])["traceback"]
    print("TB", repr(tb))
    escaped = "ERROR client.log client probe failed " + tb.replace("\n", "\\n")
    print("MATCH", bool(EXCEPTION_TEXT_RE.fullmatch(escaped)))
    assert False
