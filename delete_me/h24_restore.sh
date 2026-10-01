#!/usr/bin/env bash
# usage: h24_restore.sh <production_file> <bak_suffix> <subject_test_file> <test_name>
set -euo pipefail
prod="$1"; bak="$1.$2"; subject="$3"; name="$4"
cp "$bak" "$prod"
diff "$bak" "$prod"
echo "DIFF-CLEAN $prod"
mv "$bak" delete_me/
./.un/skills/devsecops/scripts/validate_tests.py "$subject" -k "$name" 2>&1 | tail -3
