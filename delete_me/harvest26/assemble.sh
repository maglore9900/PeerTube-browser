#!/usr/bin/env bash
# Harvest 26: cut the approved tests out of the four checkpoints into their subject files; headers are fixed by hand afterwards.
set -euo pipefail
cd /home/enduser/code/PeerTube-browser
T=tests/tmp/test_26_zero_downtime_deploy_phase
A=tests/active
OUT=delete_me/harvest26/parts
mkdir -p "$OUT"
strip() { sed -E 's/  # C[12](\/C[12])?( \([a-z]+\))?: /  # /; s/  # C[12](\/C[12])?( \([a-z]+\))?$//'; }

# Phase 1 body for test_updater_worker.py: constants and cases, _write, the parse test, then everything after the SPENT shape test.
{ sed -n '36,64p' ${T}1.py; sed -n '74,93p' ${T}1.py; sed -n '105,362p' ${T}1.py; } | strip > "$OUT/p1_body.py"

# Phase 2 -> test_deploy_bluegreen.py: the whole file up to _bash_cases.
sed -n '1,591p' ${T}2.py | strip > "$OUT/deploy_bluegreen.py"
# Phase 2 -> test_engine_upstream.py: _case_params, _bash_cases and the bash parser test.
{ sed -n '508,513p' ${T}2.py; sed -n '592,611p' ${T}2.py; } | strip > "$OUT/engine_upstream_body.py"

# Phase 3 -> both engine (un)installer files start from the whole file and are pruned by hand.
strip < ${T}3.py > "$OUT/install_engine_service.py"
strip < ${T}3.py > "$OUT/uninstall_engine_service.py"

# Phase 4 -> three installer files start from the whole file and are pruned by hand.
for name in install_client_service install_service install_updater_service; do strip < ${T}4.py > "$OUT/$name.py"; done
wc -l "$OUT"/*
