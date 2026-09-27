import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SERVER_DIR = ROOT / "engine" / "server"


def test_probe():
    code = "import sys; sys.path.insert(0, sys.argv[1]); import argparse; from scripts.cli_format import CompactHelpFormatter; p = argparse.ArgumentParser(formatter_class=CompactHelpFormatter); p.add_argument('--db', required=True, metavar='PATH'); p.parse_args([])"
    ap = subprocess.run([sys.executable, "-c", code, str(SERVER_DIR)], capture_output=True, text=True)
    print("COMPACT", ap.returncode, repr(ap.stdout), repr(ap.stderr))
    assert False, "probe"
