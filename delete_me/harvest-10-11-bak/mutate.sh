#!/usr/bin/env bash
# usage: mutate.sh <label> <production_file> <sed_expression> <test_file> <k_expression>
# One mutation: back up outside the production tree, mutate, run red, restore, prove byte-identical, run green.
set -u
cd /home/enduser/code/PeerTube-browser || exit 2
label=$1; prod=$2; expr=$3; testfile=$4; kexpr=$5
bakdir=delete_me/harvest-10-11-bak
bak="$bakdir/$label.$(basename "$prod").bak"
[ -e "$bak" ] && { echo "ABORT: $bak already exists"; exit 2; }
cp "$prod" "$bak" && cmp "$prod" "$bak" || { echo "ABORT: backup failed"; exit 2; }
sleep 1
sed -i "$expr" "$prod"
touch "$prod"
if cmp -s "$prod" "$bak"; then
  echo "MUTATION DID NOT APPLY"
  sleep 1; cp "$bak" "$prod"; touch "$prod"; cmp "$bak" "$prod" && echo "RESTORE_EXACT"
  exit 3
fi
echo "--- mutation diff ($label)"
diff "$bak" "$prod"
echo "--- RED run"
timeout 600 ./.un/skills/devsecops/scripts/validate_tests.py "$testfile" -k "$kexpr" 2>&1 | tail -n 3
echo "--- failing assertion lines"
sed -n '/^E  /p' tests/last_test_output.txt | head -n 12
sed -n '/^FAILED /p;/^ERROR /p' tests/last_test_output.txt | head -n 12
sleep 1
cp "$bak" "$prod"
touch "$prod"
if cmp "$bak" "$prod"; then echo "RESTORE_EXACT"; else echo "RESTORE_MISMATCH"; exit 4; fi
echo "--- GREEN run"
timeout 600 ./.un/skills/devsecops/scripts/validate_tests.py "$testfile" -k "$kexpr" 2>&1 | tail -n 3
