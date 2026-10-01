"""Run one harvest mutation: copy the production file out of the tree, mutate it, run the one test (red), restore from the copy, prove it byte-identical with diff, re-run the test (green)."""
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path("/home/enduser/code/PeerTube-browser")
HERE = ROOT / "delete_me" / "harvest26"
sys.path.insert(0, str(HERE))
from mutations import MUTATIONS  # noqa: E402

VALIDATE = "./.un/skills/devsecops/scripts/validate_tests.py"
OUTPUT = ROOT / "tests" / "last_test_output.txt"


def purge_bytecode(prod_path: Path) -> None:
    # A same-length edit inside the same second as the last write leaves a .pyc whose mtime and size still match, so the mutated or restored source would never be read.
    for pyc in (prod_path.parent / "__pycache__").glob(f"{prod_path.stem}.*.pyc"):
        pyc.unlink()


def run_test(test: str, name: str, tag: str) -> int:
    purge_bytecode(ROOT / MUTATIONS[tag.split(".")[0]][0])
    proc = subprocess.run([VALIDATE, str(ROOT / test), "-k", name], cwd=ROOT, capture_output=True, text=True, timeout=900)
    (HERE / "log").mkdir(exist_ok=True)
    (HERE / "log" / f"{tag}.stdout.txt").write_text(proc.stdout + proc.stderr)
    if OUTPUT.exists():
        shutil.copyfile(OUTPUT, HERE / "log" / f"{tag}.output.txt")
    return proc.returncode


for mid in sys.argv[1:]:
    prod, test, name, edits = MUTATIONS[mid]
    prod_path = ROOT / prod
    backup = HERE / "bak" / f"{prod_path.name}.{mid}"
    backup.parent.mkdir(exist_ok=True)
    subprocess.run(["cp", str(prod_path), str(backup)], check=True)
    text = prod_path.read_text()
    for old, new in edits:
        assert text.count(old) == 1, f"{mid}: {old!r} occurs {text.count(old)} times"
        text = text.replace(old, new)
    prod_path.write_text(text)
    try:
        red = run_test(test, name, f"{mid}.red")
    finally:
        subprocess.run(["cp", str(backup), str(prod_path)], check=True)
    diff = subprocess.run(["diff", str(backup), str(prod_path)], capture_output=True, text=True)
    green = run_test(test, name, f"{mid}.green")
    print(f"{mid} red_exit={red} diff_exit={diff.returncode} green_exit={green} {prod} {name}", flush=True)
