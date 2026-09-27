#!/usr/bin/env bash
# usage: mutate.sh <production_file> <id> <test_file> <-k expr> <sed script>
# Harvest Step 6: back up, mutate, run the one test, restore, diff, dispose the backup, re-run.
set -u
F=$1; M=$2; TF=$3; K=$4; S=$5
V=./.un/skills/devsecops/scripts/validate_tests.py
LOG=delete_me/mutation-logs
cp "$F" "$F.bak-$M" || exit 2
# Python's .pyc check is mtime-seconds + size: a same-size edit in the same second as the last compile runs stale bytecode.
sleep 1
sed -i "$S" "$F"
echo "--- mutation $M"
if diff "$F.bak-$M" "$F"; then
    echo "MUTATION DID NOT APPLY"; cp "$F.bak-$M" "$F"; mv "$F.bak-$M" delete_me/; exit 3
fi
echo "--- mutated run"
"$V" "$TF" -k "$K" 2>&1 | sed -n '/ total /p'
cp tests/last_test_output.txt "$LOG/$M.txt"
sed -n '/^E  /p' "$LOG/$M.txt" | head -8
sed -n '/^FAILED\|^ERROR\|[0-9] passed\|[0-9] failed/p' "$LOG/$M.txt" | head -12
echo "--- restore"
cp "$F.bak-$M" "$F"
if diff "$F.bak-$M" "$F"; then echo "diff clean"; else echo "RESTORE NOT CLEAN"; exit 4; fi
mv "$F.bak-$M" delete_me/
sleep 1
touch "$F"
echo "--- green run"
"$V" "$TF" -k "$K" 2>&1 | sed -n '/ total /p'
