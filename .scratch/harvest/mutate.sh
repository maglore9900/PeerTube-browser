#!/usr/bin/env bash
# usage: mutate.sh <test_name> <production_file> <sed_expr> <subject_test_file>
set -u
P=$PWD; T=$1; F=$2; S=$3; TF=$4; B=$(basename "$F")
mkdir -p "$P/.scratch/harvest/$T"
cp "$P/$F" "$P/$F.bak" && mv "$P/$F.bak" "$P/.scratch/harvest/$T/"
sed -i "$S" "$P/$F"
echo "--- mutation diff"; diff "$P/.scratch/harvest/$T/$B.bak" "$P/$F"
echo "--- RED run"; timeout 900 ./.un/skills/devsecops/scripts/validate_tests.py "$P/$TF" -k "$T" 2>&1 | tail -8
cp "$P/tests/last_test_output.txt" "$P/.scratch/harvest/$T/red.txt"; cp "$P/.scratch/harvest/$T/$B.bak" "$P/$F"
diff "$P/.scratch/harvest/$T/$B.bak" "$P/$F" && echo "--- RESTORED byte-identical"
echo "--- GREEN run"; timeout 900 ./.un/skills/devsecops/scripts/validate_tests.py "$P/$TF" -k "$T" 2>&1 | tail -4
