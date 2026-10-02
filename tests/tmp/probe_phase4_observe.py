import hashlib
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".un" / "skills" / "devsecops" / "scripts" / "validate_tests.py"
ARCHIVE = ROOT / "tests" / "archive" / "upnext_random_draw"


def test_probe(monkeypatch):
    monkeypatch.delenv("DEVSECOPS_CONFIG", raising=False)
    spec = importlib.util.spec_from_file_location("vt_probe", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    claims = {n: sorted(p.relative_to(ROOT).as_posix() for p in ps) for n, ps in module.claimed(ROOT, module.load_config()).items()}
    lines = [f"CONFIG={module.CONFIG}"]
    for g in ("test_blocks.py", "test_dislikes.py", "test_frontend_blocks.py", "test_dislike_profile.py"):
        lines.append(f"{g}: {claims.get(g)}")
    for p in sorted(ARCHIVE.iterdir()):
        lines.append(f"{p.name} {hashlib.sha256(p.read_bytes()).hexdigest()}")
    lines.append(f"delete_me exists={(ROOT / 'delete_me').exists()} contents={sorted(x.name for x in (ROOT / 'delete_me').iterdir()) if (ROOT / 'delete_me').is_dir() else None}")
    assert False, "\n".join(lines)
