#!/usr/bin/env bash
#
# deploy-bluegreen.sh - restart the prod Engine on the code on disk with no gap for the Client.
#
# The Client reaches the Engine through nginx on 127.0.0.1:7079, whose upstream names one port of the
# fixed pair 7070/7071. This starts peertube-engine@<other port>, waits for its /api/health, points the
# upstream snippet at it, checks 7079, drains and stops the old instance. A failure before the switch
# is verified rolls back on its own and the old instance keeps serving.
#
# Usage:
#   sudo bash scripts/deploy-bluegreen.sh --blue-green [options]
#
# Options:
#   --blue-green      Required. Without it this help is printed and the exit code is 2.
#   --timeout <sec>   How long the new instance may take to answer /api/health 200 (default: 300).
#   --warmup <sec>    Extra wait after the first healthy answer, then one more check (default: 0).
#   --drain <sec>     Wait between the switch and stopping the old instance (default: 30; the
#                     Client's longest Engine request timeout is 20 s).
#   --dry-run         Print the active and target ports and every planned action; change nothing.
#   -h, --help        Show this help.
#
# Active port: cat /etc/nginx/peertube-engine-upstream.conf   Logs: journalctl -t peertube-engine-deploy

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Same root rule as run-services.sh: this lives in scripts/ and operates on the repository root.
if [[ ! -d "${SCRIPT_DIR}/engine" && -d "${SCRIPT_DIR}/../engine" ]]; then
  SCRIPT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
fi
# shellcheck source=../engine/engine-upstream.sh
source "${SCRIPT_DIR}/engine/engine-upstream.sh"

DB_DIR="${SCRIPT_DIR}/engine/server/db"
LOCK_FILE="$(engine_deploy_lock_path "${SCRIPT_DIR}")"
# Beside the snippet and not *.conf, so nginx never loads a second upstream from it.
SNIPPET_BACKUP="${UPSTREAM_SNIPPET}.bak"
# Overridable for tests only: the developer machine may carry a real prod Client unit.
CLIENT_UNIT_PATH="${PEERTUBE_CLIENT_UNIT_PATH:-/etc/systemd/system/peertube-client.service}"
UPDATER_UNIT="peertube-updater.service"
LOG_TAG="peertube-engine-deploy"
# 2 s keeps readiness polls at ~30/min, inside the Engine's 60 per 60 s /api/ limit; a 429 just counts as not ready.
READY_POLL_SECONDS=2
SWITCH_CHECK_ATTEMPTS=10
PROBE_MAX_TIME=5

BLUE_GREEN=0
HEALTH_TIMEOUT=300
WARMUP_SECONDS=0
DRAIN_SECONDS=30
DRY_RUN=0

DEPLOY_ID="$(date -u '+%Y%m%dT%H%M%SZ')-$$"
PHASE="init"
ACTIVE_PORT=""
TARGET_PORT=""
FAIL_REASON=""
EXIT_CODE=0

# Print the usage block from this file's header.
print_usage() {
  awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "${BASH_SOURCE[0]}"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --blue-green) BLUE_GREEN=1; shift ;;
    --timeout) HEALTH_TIMEOUT="${2:-}"; shift 2 ;;
    --warmup) WARMUP_SECONDS="${2:-}"; shift 2 ;;
    --drain) DRAIN_SECONDS="${2:-}"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    --help|-h) print_usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; print_usage >&2; exit 2 ;;
  esac
done

if (( BLUE_GREEN == 0 )); then
  echo "ERROR: --blue-green is required." >&2
  print_usage >&2
  exit 2
fi
[[ "${HEALTH_TIMEOUT}" =~ ^[1-9][0-9]*$ ]] || { echo "ERROR: --timeout must be a positive integer: ${HEALTH_TIMEOUT}" >&2; exit 2; }
[[ "${WARMUP_SECONDS}" =~ ^[0-9]+$ ]] || { echo "ERROR: --warmup must be a non-negative integer: ${WARMUP_SECONDS}" >&2; exit 2; }
[[ "${DRAIN_SECONDS}" =~ ^[0-9]+$ ]] || { echo "ERROR: --drain must be a non-negative integer: ${DRAIN_SECONDS}" >&2; exit 2; }

# Emit one deploy_id-tagged line to stdout and journald. Children get fd 9 closed so none of them outlives the lock.
log_event() {
  local line="deploy_id=${DEPLOY_ID} event=$*"
  echo "${line}"
  if (( DRY_RUN == 0 )); then
    logger -t "${LOG_TAG}" -- "${line}" 9>&- || echo "WARNING: logger failed; the line above is not in the journal." >&2
  fi
}

# Stop before any change and exit 1.
refuse() {
  log_event "refused reason=$*"
  echo "ERROR: deploy refused: $*" >&2
  exit 1
}

# Sleep where a trapped INT/TERM interrupts at once instead of after the sleep.
pause() {
  sleep "$1" 9>&- &
  wait "$!"
}

unit_state() {
  systemctl is-active "$1" 2>/dev/null || true
}

# Print the HTTP status for a URL, 000 when nothing answers.
http_status() {
  curl -s -o /dev/null -w '%{http_code}' --max-time "${PROBE_MAX_TIME}" "$1" 9>&- 2>/dev/null || true
}

# Print the snippet and both instances' states as key=value pairs, for the record a failed rollback leaves.
state_dump() {
  printf 'snippet="%s" old_state=%s new_state=%s' "$(tr '\n' ' ' < "${UPSTREAM_SNIPPET}" 2>/dev/null)" "$(unit_state "${ENGINE_INSTANCE_BASE}@${ACTIVE_PORT}")" "$(unit_state "${ENGINE_INSTANCE_BASE}@${TARGET_PORT}")"
}

# A step inside rollback failed: say so loudly with the state left behind, and stop.
rollback_failed() {
  log_event "rollback_failed msg=\"ROLLBACK FAILED\" at=$1 phase=${PHASE} $(state_dump)"
  echo "ROLLBACK FAILED at $1 (phase ${PHASE}). $(state_dump)" >&2
  exit 1
}

# Undo by phase. pre-switch: stop the target. switching: restore the snippet, nginx -t, reload, stop the target. switched: traffic is already on the target, so log and mark the exit non-zero.
rollback() {
  local step="$1" reason="$2"
  trap '' INT TERM
  if [[ "${PHASE}" == "switched" ]]; then
    log_event "post_switch_failure step=${step} reason=${reason} rollback=none"
    EXIT_CODE=1
    trap 'on_signal INT' INT
    trap 'on_signal TERM' TERM
    return 0
  fi
  log_event "rollback phase=${PHASE} step=${step} reason=${reason} old_port=${ACTIVE_PORT} new_port=${TARGET_PORT}"
  case "${PHASE}" in
    init) ;;
    pre-switch)
      systemctl stop "${ENGINE_INSTANCE_BASE}@${TARGET_PORT}" || rollback_failed "stop_target"
      ;;
    switching)
      replace_file "${UPSTREAM_SNIPPET}" < "${SNIPPET_BACKUP}" || rollback_failed "restore_snippet"
      nginx -t >/dev/null 2>&1 || rollback_failed "restore_nginx_test"
      systemctl reload nginx || rollback_failed "restore_nginx_reload"
      systemctl stop "${ENGINE_INSTANCE_BASE}@${TARGET_PORT}" || rollback_failed "stop_target"
      ;;
  esac
  log_event "rollback_done phase=${PHASE} step=${step} serving_port=${ACTIVE_PORT}"
  exit 1
}

on_signal() {
  log_event "signal name=$1 phase=${PHASE}"
  if [[ "${PHASE}" == "switched" ]]; then
    exit 1
  fi
  rollback "signal" "SIG$1"
}

# Poll the target until /api/health is 200 with the unit active. 429 or a refused connection means not ready; failed/inactive ends the wait at once.
wait_ready() {
  local port="$1" unit="${ENGINE_INSTANCE_BASE}@$1" started="${SECONDS}" state status="000"
  while :; do
    state="$(unit_state "${unit}")"
    if [[ "${state}" == "failed" || "${state}" == "inactive" ]]; then
      log_event "readiness_failed port=${port} unit_state=${state} last_status=${status} waited_s=$(( SECONDS - started ))"
      FAIL_REASON="unit_${state}"
      return 1
    fi
    status="$(http_status "http://127.0.0.1:${port}/api/health")"
    if [[ "${status}" == "200" && "${state}" == "active" ]]; then
      log_event "ready port=${port} status=200 waited_s=$(( SECONDS - started ))"
      return 0
    fi
    if (( SECONDS - started >= HEALTH_TIMEOUT )); then
      log_event "readiness_timeout port=${port} unit_state=${state} last_status=${status} waited_s=$(( SECONDS - started ))"
      FAIL_REASON="readiness_timeout"
      return 1
    fi
    pause "${READY_POLL_SECONDS}"
  done
}

# Ask 7079 until it answers 200 from the target. X-Engine-Upstream names the upstream nginx used, so an old worker still proxying to the old instance does not pass.
check_switched() {
  local want="127.0.0.1:${TARGET_PORT}" started="${SECONDS}" attempt out status="000" upstream=""
  for (( attempt = 1; attempt <= SWITCH_CHECK_ATTEMPTS; attempt++ )); do
    out="$(curl -s -o /dev/null -D - -w '%{http_code}' --max-time "${PROBE_MAX_TIME}" "http://127.0.0.1:${ENGINE_LISTENER_PORT}/api/health" 9>&- 2>/dev/null || true)"
    status="${out: -3}"
    upstream="$(printf '%s\n' "${out}" | tr -d '\r' | awk 'tolower($1) == "x-engine-upstream:" { value = $2 } END { print value }')"
    if [[ "${status}" == "200" && "${upstream}" == "${want}" ]]; then
      log_event "post_switch_check status=200 upstream=${upstream} attempts=${attempt} waited_s=$(( SECONDS - started ))"
      return 0
    fi
    (( attempt < SWITCH_CHECK_ATTEMPTS )) && pause 1
  done
  log_event "post_switch_check_failed last_status=${status:-000} upstream=${upstream:-none} want=${want} waited_s=$(( SECONDS - started ))"
  FAIL_REASON="post_switch_check"
  return 1
}

# The old instance's interrupted random-cache build: <stem>.tmp.<pid><suffix> plus -journal, as random_cache_temp_path()/remove_random_cache_temp() name them (engine/server/data/random_cache.py).
remove_random_cache_temp() {
  local pid="$1" path removed=0
  if [[ ! "${pid}" =~ ^[1-9][0-9]*$ ]]; then
    log_event "cache_cleanup skipped=no_pid"
    return 0
  fi
  for path in "${DB_DIR}/random-cache.tmp.${pid}.db" "${DB_DIR}/random-cache.tmp.${pid}.db-journal"; do
    if [[ -e "${path}" ]]; then
      rm -f -- "${path}" || { log_event "cache_cleanup_failed path=${path}"; return 1; }
      removed=$(( removed + 1 ))
    fi
  done
  log_event "cache_cleanup pid=${pid} removed=${removed}"
}

# Print the Client preflight verdict: absent | ok | wrong.
client_preflight() {
  [[ -f "${CLIENT_UNIT_PATH}" ]] || { printf 'absent'; return 0; }
  if grep -qE -- "--engine-url http://127\.0\.0\.1:${ENGINE_LISTENER_PORT}( |$)" "${CLIENT_UNIT_PATH}"; then printf 'ok'; else printf 'wrong'; fi
}

print_dry_run() {
  local updater_state client_state target_state
  updater_state="$(unit_state "${UPDATER_UNIT}")"
  client_state="$(client_preflight)"
  target_state="$(unit_state "${ENGINE_INSTANCE_BASE}@${TARGET_PORT}")"
  echo "[dry-run] deploy-bluegreen deploy_id=${DEPLOY_ID}"
  echo "  repo=${SCRIPT_DIR}"
  echo "  snippet=${UPSTREAM_SNIPPET} active_port=${ACTIVE_PORT} target_port=${TARGET_PORT}"
  echo "  updater=${UPDATER_UNIT} state=${updater_state}"
  echo "  client_unit=${CLIENT_UNIT_PATH} preflight=${client_state}"
  echo "  lock=${LOCK_FILE}"
  echo "  timeout=${HEALTH_TIMEOUT}s warmup=${WARMUP_SECONDS}s drain=${DRAIN_SECONDS}s"
  echo "  actions:"
  echo "    1. flock -n ${LOCK_FILE}; refuse if ${UPDATER_UNIT} is active|activating|deactivating|reloading; refuse unless the Client unit uses --engine-url http://127.0.0.1:${ENGINE_LISTENER_PORT}"
  echo "    2. systemctl stop ${ENGINE_INSTANCE_BASE}@${TARGET_PORT} (only if not inactive; now: ${target_state}); refuse if 127.0.0.1:${TARGET_PORT} still answers"
  echo "    3. systemctl start ${ENGINE_INSTANCE_BASE}@${TARGET_PORT}"
  echo "    4. poll http://127.0.0.1:${TARGET_PORT}/api/health every ${READY_POLL_SECONDS}s up to ${HEALTH_TIMEOUT}s; warm-up ${WARMUP_SECONDS}s and one more check"
  echo "    5. cp ${UPSTREAM_SNIPPET} ${SNIPPET_BACKUP}; write snippet naming 127.0.0.1:${TARGET_PORT} (temp + rename, 0644); nginx -t; systemctl reload nginx"
  echo "    6. check http://127.0.0.1:${ENGINE_LISTENER_PORT}/api/health = 200 with X-Engine-Upstream 127.0.0.1:${TARGET_PORT} (${SWITCH_CHECK_ATTEMPTS} x 1s)"
  echo "    7. sleep ${DRAIN_SECONDS}; systemctl stop ${ENGINE_INSTANCE_BASE}@${ACTIVE_PORT}; systemctl enable ${ENGINE_INSTANCE_BASE}@${TARGET_PORT}; systemctl disable ${ENGINE_INSTANCE_BASE}@${ACTIVE_PORT}"
  echo "    8. rm -f ${DB_DIR}/random-cache.tmp.<MainPID of ${ENGINE_INSTANCE_BASE}@${ACTIVE_PORT}>.db{,-journal}"
}

if (( DRY_RUN == 1 )); then
  ACTIVE_PORT="$(read_active_port "${UPSTREAM_SNIPPET}")" || { echo "ERROR: ${UPSTREAM_SNIPPET} is missing or does not name exactly one of 127.0.0.1:7070/7071." >&2; exit 1; }
  TARGET_PORT="$(other_instance_port "${ACTIVE_PORT}")"
  print_dry_run
  exit 0
fi

[[ "$(id -u)" == "0" ]] || { echo "ERROR: run as root: sudo bash scripts/deploy-bluegreen.sh --blue-green" >&2; exit 1; }
for cmd in flock curl systemctl nginx logger; do
  command -v "${cmd}" >/dev/null 2>&1 || { echo "ERROR: required command not found: ${cmd}" >&2; exit 1; }
done
[[ -d "${DB_DIR}" ]] || { echo "ERROR: missing ${DB_DIR}" >&2; exit 1; }

# Step 1. The lock is bound to fd 9, so it is released on every exit, SIGKILL included.
exec 9>>"${LOCK_FILE}" || { echo "ERROR: cannot open ${LOCK_FILE}" >&2; exit 1; }
# The updater (service user) opens this file read-only to flock it; root's umask must not leave it 0600.
chmod 0644 "${LOCK_FILE}" || { echo "ERROR: cannot chmod 0644 ${LOCK_FILE}" >&2; exit 1; }
flock -n 9 || refuse "lock_held lock=${LOCK_FILE}"
trap 'on_signal INT' INT
trap 'on_signal TERM' TERM
log_event "lock_acquired lock=${LOCK_FILE}"

# Step 2. The updater is Type=oneshot: while it runs, is-active prints "activating".
updater_state="$(unit_state "${UPDATER_UNIT}")"
case "${updater_state}" in
  active|activating|deactivating|reloading) refuse "updater_running unit=${UPDATER_UNIT} state=${updater_state}" ;;
esac
[[ "$(client_preflight)" != "wrong" ]] || refuse "client_not_on_listener unit=${CLIENT_UNIT_PATH} want=--engine-url_http://127.0.0.1:${ENGINE_LISTENER_PORT}"

# Step 3.
ACTIVE_PORT="$(read_active_port "${UPSTREAM_SNIPPET}")" || refuse "snippet_invalid path=${UPSTREAM_SNIPPET}"
TARGET_PORT="$(other_instance_port "${ACTIVE_PORT}")"
OLD_UNIT="${ENGINE_INSTANCE_BASE}@${ACTIVE_PORT}"
NEW_UNIT="${ENGINE_INSTANCE_BASE}@${TARGET_PORT}"
log_event "start old_port=${ACTIVE_PORT} new_port=${TARGET_PORT} timeout_s=${HEALTH_TIMEOUT} warmup_s=${WARMUP_SECONDS} drain_s=${DRAIN_SECONDS}"

PHASE="pre-switch"
# Step 4: a leftover is restarted, never reused.
target_state="$(unit_state "${NEW_UNIT}")"
if [[ "${target_state}" != "inactive" ]]; then
  log_event "stop_leftover unit=${NEW_UNIT} state=${target_state}"
  systemctl stop "${NEW_UNIT}" || rollback "stop_leftover" "systemctl_stop_failed"
fi
# Something else on the target port (server.py --dev binds 7071) would pass readiness in place of the unit.
leftover_status="$(http_status "http://127.0.0.1:${TARGET_PORT}/api/health")"
[[ "${leftover_status}" == "000" ]] || refuse "port_in_use_by_foreign_process port=${TARGET_PORT} status=${leftover_status}"

# Step 5.
log_event "start_target unit=${NEW_UNIT}"
systemctl start "${NEW_UNIT}" || rollback "start_target" "systemctl_start_failed"

# Step 6.
wait_ready "${TARGET_PORT}" || rollback "readiness" "${FAIL_REASON}"
if (( WARMUP_SECONDS > 0 )); then
  pause "${WARMUP_SECONDS}"
  warm_status="$(http_status "http://127.0.0.1:${TARGET_PORT}/api/health")"
  log_event "warmup_check port=${TARGET_PORT} status=${warm_status} warmup_s=${WARMUP_SECONDS}"
  [[ "${warm_status}" == "200" ]] || rollback "warmup_check" "warmup_status_${warm_status}"
fi

# Step 7. PHASE flips to switching only once the backup exists, so a switching rollback always has one to restore.
cp -p "${UPSTREAM_SNIPPET}" "${SNIPPET_BACKUP}" || rollback "snippet_backup" "cp_failed"
PHASE="switching"
snippet_text "${TARGET_PORT}" | replace_file "${UPSTREAM_SNIPPET}" || rollback "snippet_write" "write_failed"
log_event "snippet_written port=${TARGET_PORT}"
nginx -t >/dev/null 2>&1 || rollback "nginx_test" "nginx_test_failed"
systemctl reload nginx || rollback "nginx_reload" "nginx_reload_failed"
log_event "switched old_port=${ACTIVE_PORT} new_port=${TARGET_PORT} switch_time=$(date -u '+%Y-%m-%dT%H:%M:%SZ')"

# Step 8.
check_switched || rollback "post_switch_check" "${FAIL_REASON}"
PHASE="switched"

# Step 9. The PID is recorded before the stop, for step 10.
old_pid="$(systemctl show -p MainPID --value "${OLD_UNIT}" 2>/dev/null || true)"
log_event "drain_begin unit=${OLD_UNIT} main_pid=${old_pid:-0} drain_s=${DRAIN_SECONDS}"
pause "${DRAIN_SECONDS}"
if systemctl stop "${OLD_UNIT}"; then log_event "old_stopped unit=${OLD_UNIT}"; else rollback "stop_old" "systemctl_stop_failed"; fi
if systemctl enable "${NEW_UNIT}" 2>/dev/null; then log_event "enabled unit=${NEW_UNIT}"; else rollback "enable_new" "systemctl_enable_failed"; fi
if systemctl disable "${OLD_UNIT}" 2>/dev/null; then log_event "disabled unit=${OLD_UNIT}"; else rollback "disable_old" "systemctl_disable_failed"; fi

# Step 10.
remove_random_cache_temp "${old_pid}" || rollback "cache_cleanup" "rm_failed"

# Step 11: the lock goes with fd 9 at exit.
log_event "done result=$([[ ${EXIT_CODE} == 0 ]] && echo ok || echo degraded) active_port=${TARGET_PORT} exit_code=${EXIT_CODE}"
exit "${EXIT_CODE}"
