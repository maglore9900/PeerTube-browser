"""For each mutation's red run, print the failed node ids and the source line of each failing assertion (pytest's `>` line), shortened."""
import re
import sys
from pathlib import Path

LOG = Path("/home/enduser/code/PeerTube-browser/delete_me/harvest26/log")
for mid in sys.argv[1:]:
    text = (LOG / f"{mid}.red.output.txt").read_text(errors="replace")
    failed = sorted(set(re.findall(r"^FAILED (\S+)", text, re.M)))
    arrows = []
    for line in text.splitlines():
        if line.startswith(">"):
            stripped = line[1:].strip()
            if stripped not in arrows:
                arrows.append(stripped)
    errors = []
    for line in text.splitlines():
        if line.startswith("E ") and len(errors) < 2:
            errors.append(line[1:].strip()[:160])
    print(f"== {mid} failed={len(failed)} {[f.split('::')[-1] for f in failed]}")
    for arrow in arrows[:3]:
        print("   >", arrow[:230])
    for error in errors:
        print("   E", error)
