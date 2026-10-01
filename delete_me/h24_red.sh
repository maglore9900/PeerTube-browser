#!/usr/bin/env bash
# usage: h24_red.sh <subject_test_file> <test_name>
set -uo pipefail
./.un/skills/devsecops/scripts/validate_tests.py "$1" -k "$2" 2>&1 | tail -6
echo "--- failure lines"
awk '/^>|^E  |\.py:[0-9]+: /' tests/last_test_output.txt | head -20
