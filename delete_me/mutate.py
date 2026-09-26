"""Harvest Step 6 helper: break one rule, run one test, restore exactly.

Usage: python3 tests/tmp/mutate.py <file> <old> <new> <test_file> <-k expr>
Prints the test run's summary and whether the restore is byte-identical and green again.
"""
import filecmp
import shutil
import subprocess
import sys
from pathlib import Path

target, old, new, test_file, expr = sys.argv[1:6]
path = Path(target)
backup = path.with_name(path.name + ".bak")
shutil.copy2(path, backup)
text = path.read_text()
assert text.count(old) == 1, f"mutation anchor found {text.count(old)} times"
path.write_text(text.replace(old, new))

run = [sys.executable, ".un/skills/devsecops/scripts/validate_tests.py", test_file, "-k", expr]
mutated = subprocess.run(run, capture_output=True, text=True)
out = Path("tests/last_test_output.txt").read_text()
felled = [line for line in out.splitlines() if line.startswith(("E  ", "FAILED")) or ".py:" in line and "Error" in line]
print("MUTATED exit", mutated.returncode)
print("\n".join(felled[:8]))

shutil.copy2(backup, path)
identical = filecmp.cmp(backup, path, shallow=False)
shutil.move(str(backup), f"delete_me/{path.name}.mutation.bak")
restored = subprocess.run(run, capture_output=True, text=True)
print("RESTORED identical", identical, "exit", restored.returncode)
