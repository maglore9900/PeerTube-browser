import hashlib
import importlib.util
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".un" / "skills" / "devsecops" / "scripts" / "validate_tests.py"
ARCHIVE = ROOT / "tests" / "archive" / "upnext_random_draw"


def test_probe():
    print("DEVSECOPS_CONFIG env:", os.environ.get("DEVSECOPS_CONFIG"))
    spec = importlib.util.spec_from_file_location("probe_validate_tests", SCRIPT)
    vt = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(vt)
    print("CONFIG:", vt.CONFIG, "SKILL_CONFIG:", vt.SKILL_CONFIG)
    claims = vt.claimed(ROOT, vt.load_config())
    for name in ("test_blocks.py", "test_dislikes.py", "test_frontend_blocks.py", "test_dislike_profile.py", "test_similar.py"):
        print(name, [p.relative_to(ROOT).as_posix() for p in claims.get(name, [])])
    print("archive entries:", sorted(p.name for p in ARCHIVE.iterdir()))
    for p in sorted(ARCHIVE.glob("*.py")):
        data = p.read_bytes()
        print(p.name, hashlib.sha256(data).hexdigest(), len(data), [l for l in data.decode().splitlines() if "pytestmark" in l or "mark.skip" in l][:3])
    print("delete_me same names:", sorted(p.name for p in (ROOT / "delete_me").glob("test_*.py")))
    assert False
