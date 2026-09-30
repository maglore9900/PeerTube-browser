"""Harvest 36 mutation driver: back up a production file into delete_me, apply one mutation, run one test (red), restore, prove the bytes, run it again (green)."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = json.loads(Path(sys.argv[1]).read_text())
tag = spec["tag"]
prod = ROOT / spec["file"]
bak = ROOT / "delete_me" / f"{prod.name}.bak-h36r-{tag}"
assert not bak.exists(), bak
shutil.copy2(prod, bak)
text = prod.read_text()
start = text.index(spec["scope_start"]) if spec.get("scope_start") else 0
end = text.index(spec["scope_end"], start) if spec.get("scope_end") else len(text)
scope = text[start:end]
for old, new in spec["edits"]:
    assert scope.count(old) == 1, (tag, old, scope.count(old))
    scope = scope.replace(old, new)
prod.write_text(text[:start] + scope + text[end:])
cmd = ["./.un/skills/devsecops/scripts/validate_tests.py", str(ROOT / spec["test_file"]), "-k", spec["test"]]


def run(label):
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=spec.get("timeout", 900))
    out = proc.stdout + proc.stderr
    print(f"=== {tag} {label}: exit {proc.returncode}")
    print("\n".join(out.splitlines()[-spec.get("tail", 40):]))
    return proc.returncode


try:
    red = run("MUTATED")
    red_log = ROOT / "delete_me" / f"h36r_{tag}_red.txt"
    shutil.copy2(ROOT / "tests" / "last_test_output.txt", red_log)
    felled = [line for line in red_log.read_text().splitlines() if line.startswith("E ") or ".py:" in line and "Error" in line]
    print("\n".join(felled[: spec.get("felled", 12)]))
finally:
    shutil.copy2(bak, prod)
diff = subprocess.run(["diff", str(bak), str(prod)], capture_output=True, text=True)
print(f"=== {tag} restore diff exit {diff.returncode} {diff.stdout[:500]}")
green = run("RESTORED")
print(f"=== {tag} SUMMARY red_exit={red} diff_exit={diff.returncode} green_exit={green}")
