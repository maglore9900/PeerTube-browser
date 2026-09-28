#!/usr/bin/env bash
# Harvest of issue 13, Step 6: one mutation of the video page, run, restore, re-run.
# usage: delete_me/h13_mutate.sh <tag> <test_name> <old> <new>
set -u
cd /home/enduser/code/PeerTube-browser
F=client/frontend/src/pages/video-page/index.ts
B=$F.bak-h13-$1
T=tests/active/test_frontend_video_page.py
cp "$F" "$B"
python3 - "$F" "$3" "$4" <<'EOF'
import sys
path, old, new = sys.argv[1:]
src = open(path).read()
assert src.count(old) == 1, f"old occurs {src.count(old)} times"
open(path, "w").write(src.replace(old, new))
EOF
echo "=== mutated ($1)"; diff "$B" "$F"
./.un/skills/devsecops/scripts/validate_tests.py "$T" -k "$2" >/dev/null
echo "=== mutated run exit $?"
python3 - <<'EOF'
import re
out = open("tests/last_test_output.txt").read()
for m in re.finditer(r"^E\s+(assert.*|AssertionError.*)$", out, re.M):
    print(m.group(0)[:300])
for m in re.finditer(r"^(FAILED|PASSED).*$", out, re.M):
    print(m.group(0)[:200])
EOF
cp "$B" "$F"
diff "$B" "$F" && echo "=== restore exact"
mv -n "$B" delete_me/
./.un/skills/devsecops/scripts/validate_tests.py "$T" -k "$2" | tail -3
echo "=== restored run exit ${PIPESTATUS[0]}"
