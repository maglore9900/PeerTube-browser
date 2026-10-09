#!/usr/bin/env bash
# One harvest mutation pass: copy, move the copy to .scratch, mutate, run red, restore, diff, run green.
# Usage: mut_one.sh <mutation id> <production file> <subject test file> <test name>
set -u
id=$1; prod=$2; subject=$3; name=$4
P=/home/enduser/code/PeerTube-browser
base=$(basename "$prod")
dir=$P/.scratch/harvest/$name
mkdir -p "$dir"
rm -f "$dir/$base.bak"
cp "$P/$prod" "$P/$prod.bak"
mv "$P/$prod.bak" "$dir/"
python3 "$P/.scratch/harvest/mutate.py" "$id" || { echo "MUTATE REFUSED"; exit 2; }
# A same-size edit inside one mtime second leaves the old .pyc valid, so drop the module's bytecode after every write.
pyc="$P/$(dirname "$prod")/__pycache__/${base%.py}.cpython-314.pyc"
drop_pyc() { case "$prod" in *.py) rm -f "$pyc";; esac; }
drop_pyc
echo "=== RED RUN ($id)"
timeout 600 ./.un/skills/devsecops/scripts/validate_tests.py "$P/$subject" -k "$name" > "$dir/red.log" 2>&1
echo "red exit=$?"
cp "$P/tests/last_test_output.txt" "$dir/red_output.txt"
cp "$dir/$base.bak" "$P/$prod"
diff "$dir/$base.bak" "$P/$prod" && echo "RESTORE DIFF CLEAN"
drop_pyc
echo "=== GREEN RUN ($id)"
timeout 600 ./.un/skills/devsecops/scripts/validate_tests.py "$P/$subject" -k "$name" > "$dir/green.log" 2>&1
echo "green exit=$?"
