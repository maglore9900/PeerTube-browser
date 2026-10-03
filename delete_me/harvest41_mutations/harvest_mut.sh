#!/usr/bin/env bash
# One harvest mutation: back up the production file, apply one sed mutation, run the one test red, restore from the copy, prove it byte-identical with diff, move the copy to delete_me, run the test green.
# usage: harvest_mut.sh N prod_file test_file test_name sed_expr
set -u
cd /home/enduser/code/PeerTube-browser
n=$1; prod=$2; tfile=$3; tname=$4; expr=$5
V=./.un/skills/devsecops/scripts/validate_tests.py
L=delete_me/harvest41_mutations
cp "$prod" "$prod.bak"
sed -i "$expr" "$prod"
if cmp -s "$prod" "$prod.bak"; then echo "M$n: MUTATION DID NOT APPLY"; cp "$prod.bak" "$prod"; mv "$prod.bak" "$L/$(basename "$prod").bak.m$n"; exit 2; fi
echo "M$n mutation: $(diff "$prod.bak" "$prod" | tr '\n' ' ' | cut -c1-400)"
timeout 300 "$V" "$tfile" -k "$tname" > "$L/m$n.red" 2>&1; rc=$?
echo "RED rc=$rc: $(tail -n 1 "$L/m$n.red")"
cp tests/last_test_output.txt "$L/m$n.log"
cp "$prod.bak" "$prod"
if diff "$prod.bak" "$prod"; then echo "restore: diff-clean"; else echo "restore: DIFF NOT CLEAN"; exit 3; fi
mv "$prod.bak" "$L/$(basename "$prod").bak.m$n"
timeout 300 "$V" "$tfile" -k "$tname" > "$L/m$n.green" 2>&1; rc=$?
echo "GREEN rc=$rc: $(tail -n 1 "$L/m$n.green")"
