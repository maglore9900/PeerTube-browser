#!/usr/bin/env bash
#
# run-services.sh - start, stop and inspect the Engine, Client backend and translate worker.
#
# All three are foreground Python processes. This runs them detached with PID files,
# starts them in dependency order (the Client needs the Engine answering /api/health),
# and loads the shared bridge secret they require. The translate worker needs ffmpeg
# and a GPU; set CUDA_VISIBLE_DEVICES before running this to pin it to one card.
#
# Usage:
#   bash run-services.sh start|stop|restart|status|logs [options]
#
# Options:
#   --engine-port <n>  Engine port (default: 7070).
#   --client-port <n>  Client backend port (default: 7072).
#   --timeout <sec>    How long to wait for the Engine to become healthy (default: 300).
#                      First start loads the FAISS index and is slow on a full dataset.
#   --help             Show this help.
#
# The bridge secret is read from .env.bridge in the project root. Without it the Engine
# answers 503 on every /internal/* route and likes/profile break while browsing works.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# These scripts operate on the repository root. They used to live there; they now live in
# scripts/, so every ${SCRIPT_DIR}/... path below would resolve one level too deep.
if [[ ! -d "${SCRIPT_DIR}/engine" && -d "${SCRIPT_DIR}/../engine" ]]; then
  SCRIPT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
fi
ENV_FILE="${SCRIPT_DIR}/.env.bridge"
ENGINE_PID_FILE="${SCRIPT_DIR}/engine.pid"
CLIENT_PID_FILE="${SCRIPT_DIR}/client.pid"
ENGINE_LOG="${SCRIPT_DIR}/engine.log"
CLIENT_LOG="${SCRIPT_DIR}/client.log"
ENGINE_SCRIPT="${SCRIPT_DIR}/engine/server/api/server.py"
CLIENT_SCRIPT="${SCRIPT_DIR}/client/backend/server.py"
WORKER_PID_FILE="${SCRIPT_DIR}/translate-worker.pid"
WORKER_LOG="${SCRIPT_DIR}/translate-worker.log"
WORKER_SCRIPT="${SCRIPT_DIR}/engine/server/db/jobs/translate-worker.py"
# The worker's SIGTERM path finishes the current fetch or Whisper chunk and requeues
# the job; a SIGKILL instead leaves it `running` and costs it a claim on the next start.
WORKER_STOP_TIMEOUT=120

ENGINE_PORT=7070
CLIENT_PORT=7072
HEALTH_TIMEOUT=300

# Search fusion weights: how much keyword (BM25) rank and vector rank count. Edit here and
# run `restart`; set explicitly so a variable left in the shell never changes them unseen.
# 1 and 1 is the old equal weighting. See SEARCH_WEIGHT_* in engine/server/api/server_config.py.
SEARCH_WEIGHT_LEXICAL=0.3
SEARCH_WEIGHT_VECTOR=0.7

COMMAND="${1:-}"
[[ $# -gt 0 ]] && shift

# Print the usage block from this file's header.
print_usage() {
  sed -n '2,22p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --engine-port) ENGINE_PORT="$2"; shift 2 ;;
    --client-port) CLIENT_PORT="$2"; shift 2 ;;
    --timeout) HEALTH_TIMEOUT="$2"; shift 2 ;;
    --help|-h) print_usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; print_usage >&2; exit 2 ;;
  esac
done

# Emit a timestamped line.
log() {
  echo "[services $(date '+%H:%M:%S')] $*"
}

# Resolve the Python interpreter that has the project dependencies installed.
resolve_python() {
  local candidates=(
    "${SCRIPT_DIR}/engine/.pixi/envs/default/bin/python"
    "${SCRIPT_DIR}/.pixi/envs/default/bin/python"
    "${SCRIPT_DIR}/venv/bin/python3"
    "${SCRIPT_DIR}/venv/bin/python"
  )
  for candidate in "${candidates[@]}"; do
    if [[ -x "${candidate}" ]]; then echo "${candidate}"; return 0; fi
  done
  command -v python3
}

PY="$(resolve_python)"

# Load ENGINE_BRIDGE_TOKEN, refusing to start without it.
load_bridge_secret() {
  if [[ ! -f "${ENV_FILE}" ]]; then
    log "ERROR: ${ENV_FILE} not found."
    log "  Create it with:"
    log "    printf 'ENGINE_BRIDGE_TOKEN=%s\\n' \"\$(openssl rand -hex 32)\" > .env.bridge"
    log "    chmod 600 .env.bridge"
    exit 1
  fi
  set -a
  # shellcheck disable=SC1090
  source "${ENV_FILE}"
  set +a
  if [[ -z "${ENGINE_BRIDGE_TOKEN:-}" ]]; then
    log "ERROR: ENGINE_BRIDGE_TOKEN is empty in ${ENV_FILE}"
    exit 1
  fi
}

# Report whether the process recorded in a PID file is alive.
is_running() {
  local pid_file="$1" pid
  [[ -f "${pid_file}" ]] || return 1
  pid="$(cat "${pid_file}" 2>/dev/null)"
  [[ -n "${pid}" ]] || return 1
  kill -0 "${pid}" 2>/dev/null
}

# Return the HTTP status of a health endpoint, or 000 when unreachable.
health_status() {
  curl -s -o /dev/null -m 5 -w '%{http_code}' "http://127.0.0.1:$1/api/health" 2>/dev/null
}

# Block until a port answers 200 on /api/health, or the timeout expires.
wait_for_health() {
  local port="$1" label="$2" waited=0
  while (( waited < HEALTH_TIMEOUT )); do
    if [[ "$(health_status "${port}")" == "200" ]]; then
      log "${label} healthy on ${port} after ${waited}s"
      return 0
    fi
    sleep 5
    waited=$((waited + 5))
  done
  log "ERROR: ${label} did not become healthy within ${HEALTH_TIMEOUT}s"
  return 1
}

# Start the Engine, then the Client once the Engine answers.
start_services() {
  load_bridge_secret

  if is_running "${ENGINE_PID_FILE}"; then
    log "Engine already running (pid $(cat "${ENGINE_PID_FILE}"))"
  else
    log "starting Engine on ${ENGINE_PORT} (first start loads the ANN index; this is slow)"
    log "search weights: keyword ${SEARCH_WEIGHT_LEXICAL}, vector ${SEARCH_WEIGHT_VECTOR}"
    ENGINE_INGEST_MODE=bridge ENGINE_BRIDGE_TOKEN="${ENGINE_BRIDGE_TOKEN}" \
      SEARCH_WEIGHT_LEXICAL="${SEARCH_WEIGHT_LEXICAL}" SEARCH_WEIGHT_VECTOR="${SEARCH_WEIGHT_VECTOR}" \
      nohup "${PY}" "${ENGINE_SCRIPT}" --port "${ENGINE_PORT}" \
      >"${ENGINE_LOG}" 2>&1 &
    echo "$!" > "${ENGINE_PID_FILE}"
    log "Engine pid $(cat "${ENGINE_PID_FILE}"), log ${ENGINE_LOG}"
  fi

  wait_for_health "${ENGINE_PORT}" "Engine" || {
    log "see ${ENGINE_LOG} for why"
    return 1
  }

  if is_running "${CLIENT_PID_FILE}"; then
    log "Client already running (pid $(cat "${CLIENT_PID_FILE}"))"
  else
    log "starting Client backend on ${CLIENT_PORT}"
    CLIENT_PUBLISH_MODE=bridge ENGINE_BRIDGE_TOKEN="${ENGINE_BRIDGE_TOKEN}" \
      nohup "${PY}" "${CLIENT_SCRIPT}" \
      --port "${CLIENT_PORT}" --engine-url "http://127.0.0.1:${ENGINE_PORT}" \
      >"${CLIENT_LOG}" 2>&1 &
    echo "$!" > "${CLIENT_PID_FILE}"
    log "Client pid $(cat "${CLIENT_PID_FILE}"), log ${CLIENT_LOG}"
  fi

  wait_for_health "${CLIENT_PORT}" "Client" || {
    log "see ${CLIENT_LOG} for why"
    return 1
  }

  if is_running "${WORKER_PID_FILE}"; then
    log "translate worker already running (pid $(cat "${WORKER_PID_FILE}"))"
  else
    log "starting translate worker"
    nohup "${PY}" "${WORKER_SCRIPT}" run >"${WORKER_LOG}" 2>&1 &
    echo "$!" > "${WORKER_PID_FILE}"
    # It exits at once when ffmpeg is missing (1) or another worker holds the lock (6).
    sleep 3
    if ! is_running "${WORKER_PID_FILE}"; then
      rm -f "${WORKER_PID_FILE}"
      log "ERROR: translate worker exited at startup; see ${WORKER_LOG}"
      status_services
      return 1
    fi
    log "translate worker pid $(cat "${WORKER_PID_FILE}"), log ${WORKER_LOG}"
  fi
  status_services
}

# Stop one service by PID file, falling back to a pattern match.
stop_one() {
  local pid_file="$1" label="$2" pattern="$3" wait_s="${4:-20}" pid
  if is_running "${pid_file}"; then
    pid="$(cat "${pid_file}")"
    log "stopping ${label} (pid ${pid})"
    kill "${pid}" 2>/dev/null
    for _ in $(seq 1 "${wait_s}"); do
      kill -0 "${pid}" 2>/dev/null || break
      sleep 1
    done
    if kill -0 "${pid}" 2>/dev/null; then
      log "${label} did not exit; sending SIGKILL"
      kill -9 "${pid}" 2>/dev/null
    fi
    rm -f "${pid_file}"
  elif pgrep -f "${pattern}" >/dev/null 2>&1; then
    log "stopping ${label} by pattern (no valid PID file)"
    pkill -f "${pattern}"
    rm -f "${pid_file}"
  else
    log "${label} not running"
    rm -f "${pid_file}"
  fi
}

# Stop the Client first so it never talks to a dead Engine.
stop_services() {
  stop_one "${WORKER_PID_FILE}" "translate worker" "engine/server/db/jobs/translate-worker.py run" \
    "${WORKER_STOP_TIMEOUT}"
  stop_one "${CLIENT_PID_FILE}" "Client backend" "client/backend/server.py"
  stop_one "${ENGINE_PID_FILE}" "Engine" "engine/server/api/server.py"
}

# Describe one service, distinguishing "we started it", "someone else did" and "down".
#
# A healthy port with no PID file means the process was started outside this script -
# by hand, or by systemd. Reporting that as "not running" next to a 200 would be
# actively misleading, and `stop` would still find it by pattern.
report_one() {
  local label="$1" pid_file="$2" port="$3" health="$4" pattern="$5"
  if is_running "${pid_file}"; then
    log "${label}: running pid $(cat "${pid_file}") port ${port} health ${health}"
  elif [[ "${health}" == "200" ]]; then
    local found
    found="$(pgrep -f "${pattern}" | head -1)"
    log "${label}: running port ${port} health 200 (started outside this script${found:+, pid ${found}})"
  elif pgrep -f "${pattern}" >/dev/null 2>&1; then
    log "${label}: process alive but health ${health} on ${port} - still starting, or failing"
  else
    log "${label}: not running (health ${health})"
  fi
}

# Print health and PID state for both services.
status_services() {
  local engine_health client_health
  engine_health="$(health_status "${ENGINE_PORT}")"
  client_health="$(health_status "${CLIENT_PORT}")"
  report_one "Engine" "${ENGINE_PID_FILE}" "${ENGINE_PORT}" "${engine_health}" \
    "engine/server/api/server.py"
  report_one "Client" "${CLIENT_PID_FILE}" "${CLIENT_PORT}" "${client_health}" \
    "client/backend/server.py"
  # The worker has no port; its heartbeat in subtitles.db is what the Engine checks.
  if is_running "${WORKER_PID_FILE}"; then
    log "translate worker: running pid $(cat "${WORKER_PID_FILE}")"
  elif pgrep -f "engine/server/db/jobs/translate-worker.py run" >/dev/null 2>&1; then
    log "translate worker: running (started outside this script, pid $(pgrep -f "engine/server/db/jobs/translate-worker.py run" | head -1))"
  else
    log "translate worker: not running"
  fi
}

case "${COMMAND}" in
  start) start_services ;;
  stop) stop_services ;;
  restart) stop_services; sleep 2; start_services ;;
  status) status_services ;;
  logs) tail -n 40 -f "${ENGINE_LOG}" "${CLIENT_LOG}" "${WORKER_LOG}" ;;
  --help|-h|help) print_usage ;;
  "") echo "Missing command." >&2; print_usage >&2; exit 2 ;;
  *) echo "Unknown command: ${COMMAND}" >&2; print_usage >&2; exit 2 ;;
esac
