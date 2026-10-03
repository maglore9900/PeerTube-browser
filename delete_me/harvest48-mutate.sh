#!/usr/bin/env bash
# One harvest-48 mutation: copy the production file into delete_me, apply one sed edit, run one test (expect red), restore from the copy, prove it byte-identical, re-run (expect green).
# usage: harvest48-mutate.sh <tag> <production_file> <sed_expr> <test_file> <k_expr>
set -u
tag="$1"; prod="$2"; expr="$3"; test_file="$4"; k="$5"
cd /home/enduser/code/PeerTube-browser
bak="delete_me/$(basename "$prod").bak-harvest48-$tag"
cp "$prod" "$bak"
drop_pyc() { rm -f "$(dirname "$prod")/__pycache__/$(basename "$prod" .py)".cpython-*.pyc; }
sed -i -e "$expr" "$prod"
# A same-size edit inside the same second as the last write leaves the old .pyc looking fresh, so the bytecode cache is dropped after every write.
drop_pyc
if cmp -s "$bak" "$prod"; then echo "[$tag] MUTATION DID NOT APPLY"; cp "$bak" "$prod"; exit 2; fi
echo "[$tag] mutated $prod:"; diff "$bak" "$prod" | head -6
timeout 600 ./.un/skills/devsecops/scripts/validate_tests.py "$test_file" -k "$k" > "delete_me/harvest48-$tag.red.txt" 2>&1
red=$?
echo "[$tag] red run exit=$red: $(awk '/^  total/' "delete_me/harvest48-$tag.red.txt")"
awk '/^E  /' tests/last_test_output.txt | head -4
cp "$bak" "$prod"
drop_pyc
if diff "$bak" "$prod" > /dev/null; then echo "[$tag] restore diff-clean"; else echo "[$tag] RESTORE NOT CLEAN"; exit 3; fi
timeout 600 ./.un/skills/devsecops/scripts/validate_tests.py "$test_file" -k "$k" > "delete_me/harvest48-$tag.green.txt" 2>&1
green=$?
echo "[$tag] green run exit=$green: $(awk '/^  total/' "delete_me/harvest48-$tag.green.txt")"
