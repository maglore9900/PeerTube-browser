#!/usr/bin/env bash
# Usage: mutate.sh <production_file> <tag> <subject_test_file> <test_name> <sed_expr>
# One mutation: copy, break, run red, restore from the copy, prove byte-identical, park the copy in delete_me, run green.
prod="$1"; tag="$2"; testfile="$3"; name="$4"; expr="$5"
V=./.un/skills/devsecops/scripts/validate_tests.py
park=delete_me/harvest42_mutations
cp "$prod" "$prod.bak"
sed -i "$expr" "$prod"
if cmp -s "$prod.bak" "$prod"; then echo "MUTATION DID NOT APPLY"; cp "$prod.bak" "$prod"; mv "$prod.bak" "$park/$(basename "$prod").$tag.bak"; exit 3; fi
echo "=== mutation diff ($tag)"; diff "$prod.bak" "$prod"
echo "=== RED run"
timeout 600 $V "$testfile" -k "$name" > "$park/$tag.red.txt" 2>&1; echo "red exit=$?"
tail -4 "$park/$tag.red.txt"
cp tests/last_test_output.txt "$park/$tag.red.out"
awk '/^>   /' "$park/$tag.red.out" | head -3
awk '/^E  /' "$park/$tag.red.out" | head -4
cp "$prod.bak" "$prod"
diff "$prod.bak" "$prod" && echo "restore: diff clean"
cmp "$prod.bak" "$prod" && echo "restore: cmp byte-identical"
mv "$prod.bak" "$park/$(basename "$prod").$tag.bak"
echo "=== GREEN run"
timeout 600 $V "$testfile" -k "$name" > "$park/$tag.green.txt" 2>&1; echo "green exit=$?"
tail -3 "$park/$tag.green.txt"
