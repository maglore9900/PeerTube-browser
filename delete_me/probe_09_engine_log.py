import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))
from conftest import engine  # noqa: E402,F401


def test_probe(engine):
    print("db_path", engine.db_path, type(engine.db_path))
    lines = engine.db_path.read_text(errors="replace").splitlines()
    print("line count", len(lines))
    for line in lines:
        try:
            payload = json.loads(line)
        except ValueError:
            print("NONJSON", repr(line[:200]))
            continue
        if "similar-server" in str(payload.get("message", "")):
            print("JSON", line)
    assert False, "probe"
