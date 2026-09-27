"""Harvest Step 6 driver: one exact mutation, the target test run red, the file restored byte-exact, the test run green.

usage: mutate.py <label> <production_file> <test_file> <test_name> <old> <new>
"""
import filecmp
import shutil
import subprocess
import sys
from pathlib import Path

label, prod, test_file, test_name, old, new = sys.argv[1:7]
prod_path = Path(prod)
bak = prod_path.with_name(prod_path.name + f".bak-{label}")
delete_me = Path("delete_me")
runner = ["./.un/skills/devsecops/scripts/validate_tests.py", test_file, "-k", test_name]


def run() -> str:
    proc = subprocess.run(runner, capture_output=True, text=True)
    out = Path("tests/last_test_output.txt").read_text()
    failures = [line for line in out.splitlines() if line.startswith(("E ", "FAILED")) or "Error" in line[:40]]
    summary = [line for line in proc.stdout.splitlines() if "total" in line]
    return f"exit={proc.returncode} {summary[-1].strip() if summary else ''}\n" + "\n".join(failures[:6])


text = prod_path.read_text()
count = text.count(old)
if count != 1:
    sys.exit(f"{label}: old text occurs {count} times in {prod}, need exactly 1")
shutil.copy2(prod_path, bak)
prod_path.write_text(text.replace(old, new))
try:
    print(f"[{label}] MUTATED {prod}: {test_name}\n{run()}")
finally:
    shutil.copy2(bak, prod_path)
restored = filecmp.cmp(bak, prod_path, shallow=False)
delete_me.mkdir(exist_ok=True)
shutil.move(str(bak), delete_me / bak.name)
print(f"[{label}] restore byte-exact: {restored}")
print(f"[{label}] RESTORED\n{run()}")
