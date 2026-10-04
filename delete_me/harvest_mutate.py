#!/usr/bin/env python3
"""Harvest Step 6 mutation driver. For each row of a table: back up the production file, replace one exact snippet, run only the targeted tests, restore from the backup, confirm the restore is byte-exact, park the backup in delete_me/, and re-run the same tests green.

Usage: harvest_mutate.py <table.py> [label ...]
The table module defines PROD (path from the repo root), TEST (test file) and MUTATIONS, a list of (label, old, new, k_expression).
"""
from __future__ import annotations

import filecmp
import importlib.util
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path("/home/enduser/code/PeerTube-browser")
RUNNER = "./.un/skills/devsecops/scripts/validate_tests.py"
OUTPUT = ROOT / "tests" / "last_test_output.txt"


def run(test: str, kexpr: str) -> tuple[int, str]:
    proc = subprocess.run([RUNNER, test, "-k", kexpr], cwd=ROOT, capture_output=True, text=True, timeout=900)
    return proc.returncode, OUTPUT.read_text(encoding="utf-8", errors="replace")


def touch(path: Path) -> None:
    # A same-second restore can reuse the mutated .pyc; move the mtime on.
    time.sleep(1.1)
    os.utime(path, None)


def mutate(prod: str, test: str, label: str, old: str, new: str, kexpr: str) -> bool:
    prod_path = ROOT / prod
    backup = prod_path.with_name(prod_path.name + ".bak")
    if backup.exists():
        print(f"ABORT {label}: {backup} already exists")
        return False
    source = prod_path.read_text(encoding="utf-8")
    if source.count(old) != 1:
        print(f"ABORT {label}: snippet occurs {source.count(old)} times in {prod}")
        return False
    shutil.copy2(prod_path, backup)
    try:
        prod_path.write_text(source.replace(old, new), encoding="utf-8")
        touch(prod_path)
        code, out = run(test, kexpr)
        print(f"=== {label}: mutated exit {code}")
        for line in out.splitlines():
            if line.startswith(("FAILED", "ERROR ", "E  ")):
                print("   ", line[:300])
            elif line.startswith("=") and (" passed" in line or " failed" in line):
                print("   ", line)
    finally:
        shutil.copy2(backup, prod_path)
    same = filecmp.cmp(backup, prod_path, shallow=False)
    shutil.move(str(backup), ROOT / "delete_me" / f"{prod_path.name}.bak-harvest53-58-{label}")
    touch(prod_path)
    code, out = run(test, kexpr)
    summary = [line for line in out.splitlines() if line.startswith("=") and (" passed" in line or " failed" in line)]
    print(f"=== {label}: restore exact {same}; restored exit {code} {summary[-1] if summary else ''}")
    return same and code == 0


def main() -> int:
    table_path, *only = sys.argv[1:]
    spec = importlib.util.spec_from_file_location("table", table_path)
    table = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(table)
    ok = True
    for label, old, new, kexpr in table.MUTATIONS:
        if only and label not in only:
            continue
        ok = mutate(table.PROD, table.TEST, label, old, new, kexpr) and ok
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
