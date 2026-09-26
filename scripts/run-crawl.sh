#!/usr/bin/env bash
#
# run-crawl.sh - run the PeerTube crawl stages in order, as one command.
#
# The crawl is a sequence of dependent stages: each one reads what the previous stage
# wrote into engine/crawler/data/crawl.db. Running them concurrently, or starting a
# later stage before an earlier one finishes, silently produces a partial dataset.
# This script enforces the order, stops on the first failure, and logs everything.
#
# Usage:
#   bash run-crawl.sh [options]
#
# Options:
#   --resume          Pass --resume to every stage that supports it (safe re-run).
#   --with-tags       Also run the tags and comments enrichment stages (very slow:
#                     one HTTP request per video).
#   --skip-health     Skip the instance health check stage.
#   --skip-build      Do not build the crawler TypeScript before crawling.
#   --log <path>      Log file (default: crawl-<timestamp>.log in the project root).
#   --help            Show this help.
#
# Run it detached for a long crawl:
#   nohup bash run-crawl.sh --resume > /dev/null 2>&1 &
#   tail -f crawl-*.log

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# These scripts operate on the repository root. They used to live there; they now live in
# scripts/, so every ${SCRIPT_DIR}/... path below would resolve one level too deep.
if [[ ! -d "${SCRIPT_DIR}/engine" && -d "${SCRIPT_DIR}/../engine" ]]; then
  SCRIPT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
fi
CRAWLER_DIR="${SCRIPT_DIR}/engine/crawler"
DB_PATH="${CRAWLER_DIR}/data/crawl.db"

RESUME=0
WITH_TAGS=0
SKIP_HEALTH=0
SKIP_BUILD=0
LOG_FILE="${SCRIPT_DIR}/crawl-$(date +%Y%m%d-%H%M%S).log"

# Print usage text and exit.
print_usage() {
  sed -n '2,25p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --resume) RESUME=1; shift ;;
    --with-tags) WITH_TAGS=1; shift ;;
    --skip-health) SKIP_HEALTH=1; shift ;;
    --skip-build) SKIP_BUILD=1; shift ;;
    --log) LOG_FILE="$2"; shift 2 ;;
    --help|-h) print_usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; print_usage >&2; exit 2 ;;
  esac
done

# Emit a timestamped progress line to stdout and the log.
log() {
  echo "[crawl $(date '+%Y-%m-%d %H:%M:%S')] $*"
}

# Report current row counts so a long run shows visible progress between stages.
report_counts() {
  [[ -f "${DB_PATH}" ]] || return 0
  python3 - "${DB_PATH}" <<'PYEOF'
import sqlite3
import sys

conn = sqlite3.connect(sys.argv[1])
parts = []
for table in ("instances", "channels", "videos"):
    try:
        parts.append(f"{table}={conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]}")
    except sqlite3.OperationalError:
        parts.append(f"{table}=-")
print("  rows: " + "  ".join(parts))
conn.close()
PYEOF
}

# Run one npm crawl stage by script name, appending --resume when requested.
run_stage() {
  local stage="$1"
  local supports_resume="${2:-yes}"
  log "stage start: ${stage}"
  if [[ ${RESUME} -eq 1 && "${supports_resume}" == "yes" ]]; then
    npm --prefix "${CRAWLER_DIR}" run "${stage}" -- --resume
  else
    npm --prefix "${CRAWLER_DIR}" run "${stage}"
  fi
  log "stage done:  ${stage}"
  report_counts
}

exec > >(tee -a "${LOG_FILE}") 2>&1

log "log file: ${LOG_FILE}"
log "crawler:  ${CRAWLER_DIR}"
[[ ${RESUME} -eq 1 ]] && log "resume:   enabled"

if [[ ! -d "${CRAWLER_DIR}/node_modules" ]]; then
  log "installing crawler dependencies"
  npm --prefix "${CRAWLER_DIR}" install
fi

if [[ ${SKIP_BUILD} -eq 0 ]]; then
  log "building crawler"
  npm --prefix "${CRAWLER_DIR}" run build
fi

run_stage "crawl:instances"

if [[ ${SKIP_HEALTH} -eq 0 ]]; then
  run_stage "crawl:instances:health" "no"
fi

run_stage "crawl:channels"
run_stage "crawl:channels:videos-count"
run_stage "crawl:videos"

if [[ ${WITH_TAGS} -eq 1 ]]; then
  run_stage "crawl:videos:tags" "no"
  run_stage "crawl:videos:comments" "no"
fi

log "crawl complete"
report_counts
log "next: build the API dataset and artifacts per DATA_BUILD.md, starting with sync-whitelist.py"
