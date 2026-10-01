#!/usr/bin/env bash
#
# run-catalog-update.sh - the updater timer's job, without systemd.
#
# Runs engine/server/db/jobs/updater-worker.py with the flags install-service.sh gives the
# timer. The worker stops the Engine just before the merge and starts it after the ANN
# rebuild. Here those stop/start calls go to scripts/run-services.sh instead of systemctl,
# so the Engine and Client stay up through the crawl and embeddings and are down only for
# the merge, popularity and index rebuild.
#
# Usage:
#   bash scripts/run-catalog-update.sh [--foreground] [--cpu] [-- <extra updater-worker flags>]
#
# Options:
#   --foreground   Run attached to this terminal instead of detaching.
#   --cpu          Embeddings and FAISS on CPU (default: --gpu, with CPU retry on failure).
#   --help         Show this help.
#
# Detached by default: progress goes to catalog-update-<timestamp>.log in the repo root,
# and its last line says whether the update succeeded. The services are started again
# only if the Engine was running when the worker stopped it. If the worker dies while the
# Engine is down, this script starts it again.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
SERVICES="${SCRIPT_DIR}/run-services.sh"
WORKER="${REPO_DIR}/engine/server/db/jobs/updater-worker.py"
ENGINE_PATTERN="engine/server/api/server.py"

FOREGROUND=0
ACCEL="--gpu"
EXTRA_ARGS=()
ORIG_ARGS=("$@")

while [[ $# -gt 0 ]]; do
  case "$1" in
    --foreground) FOREGROUND=1; shift ;;
    --cpu) ACCEL="--cpu"; shift ;;
    --gpu) ACCEL="--gpu"; shift ;;
    --help|-h) sed -n '2,22p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    --) shift; EXTRA_ARGS=("$@"); break ;;
    *) echo "Unknown option: $1 (worker flags go after --)" >&2; exit 2 ;;
  esac
done

if (( FOREGROUND == 0 )); then
  LOG="${REPO_DIR}/catalog-update-$(date +%Y%m%d-%H%M%S).log"
  nohup setsid bash "${BASH_SOURCE[0]}" --foreground "${ORIG_ARGS[@]}" >"${LOG}" 2>&1 </dev/null &
  echo "catalog update started (pid $!)"
  echo "log: ${LOG}"
  exit 0
fi

log() {
  echo "[catalog-update $(date '+%Y-%m-%d %H:%M:%S')] $*"
}

resolve_python() {
  local candidates=(
    "${REPO_DIR}/engine/.pixi/envs/default/bin/python"
    "${REPO_DIR}/.pixi/envs/default/bin/python"
    "${REPO_DIR}/venv/bin/python3"
  )
  for candidate in "${candidates[@]}"; do
    if [[ -x "${candidate}" ]]; then echo "${candidate}"; return 0; fi
  done
  command -v python3
}

PY="$(resolve_python)"
command -v node >/dev/null 2>&1 || { log "FAILED: node not on PATH (the crawler needs it)"; exit 1; }
[[ -d "${REPO_DIR}/engine/crawler/dist" ]] || {
  log "FAILED: engine/crawler/dist missing; run 'npm install && npm run build' in engine/crawler"
  exit 1
}

SHIM_DIR="$(mktemp -d)"
STATE_FILE="${SHIM_DIR}/engine-was-running"
trap 'rm -rf "${SHIM_DIR}"' EXIT

# Stands in for systemctl: the worker calls "<bin> stop <unit>" and "<bin> start <unit>".
cat >"${SHIM_DIR}/systemctl" <<EOF
#!/usr/bin/env bash
set -uo pipefail
case "\${1:-}" in
  stop)
    if pgrep -f "${ENGINE_PATTERN}" >/dev/null 2>&1; then touch "${STATE_FILE}"; fi
    bash "${SERVICES}" stop
    ;;
  start)
    if [[ -f "${STATE_FILE}" ]]; then
      bash "${SERVICES}" start
    else
      echo "Engine was not running before the update; leaving it stopped"
    fi
    ;;
  *) echo "systemctl shim: unsupported command: \$*" >&2; exit 2 ;;
esac
EOF
chmod +x "${SHIM_DIR}/systemctl"

log "python: ${PY}"
log "worker log: ${REPO_DIR}/engine/server/db/updater-worker.log"

cd "${REPO_DIR}" || exit 1
"${PY}" "${WORKER}" \
  --systemctl-bin "${SHIM_DIR}/systemctl" \
  --service-name local-engine \
  "${ACCEL}" --skip-local-dead --concurrency 5 --timeout-ms 15000 --max-retries 3 \
  "${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"}"
STATUS=$?

# The worker restarts the Engine in a `finally`, but not if it was killed outright.
if [[ -f "${STATE_FILE}" ]] && ! pgrep -f "${ENGINE_PATTERN}" >/dev/null 2>&1; then
  log "Engine is down after the worker exited; starting services"
  bash "${SERVICES}" start || log "WARNING: services did not come back; see engine.log"
fi

if (( STATUS == 0 )); then
  log "OK: catalog update complete"
else
  log "FAILED: updater-worker exited ${STATUS}; see engine/server/db/updater-worker.log"
fi
exit "${STATUS}"
