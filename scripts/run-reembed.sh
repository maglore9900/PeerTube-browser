#!/usr/bin/env bash
#
# run-reembed.sh - re-embed the dataset on a new model and rebuild every derived artifact.
#
# Kickoff wrapper for the model change in task 87 (F6-M3). It runs pre-flight checks that
# a model swap can fail on, then starts run-dataset-build.sh at the embeddings stage,
# detached, and hands back the log path.
#
# It starts at `embeddings`, not `enrichment`: the crawl output already lives in
# crawl.db and whitelist.db, so changing the embedding model needs no re-crawl. The
# enrichment (tags) stage additionally does not converge - videos that genuinely have no
# tags are re-requested on every pass - so running it here would stall the pipeline
# without improving the vectors.
#
# Usage:
#   bash run-reembed.sh [options]
#
# Options:
#   --cpu / --gpu        Acceleration passed through (default: gpu).
#   --from <stage>       Override the start stage (default: embeddings).
#   --restart-engine     Restart the services once the build succeeds. Off by default.
#   --skip-model-check   Proceed even if the configured model still looks English-only.
#   --dry-run            Run the checks, print the command, start nothing.
#   --help               Show this help.
#
# After a successful run the Engine must be restarted to load the new index. Until then
# it serves the old one; it will refuse to start against a half-rebuilt pair, because
# api/server.py compares the index sidecar's model_name with video_embeddings.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# These scripts operate on the repository root. They used to live there; they now live in
# scripts/, so every ${SCRIPT_DIR}/... path below would resolve one level too deep.
if [[ ! -d "${SCRIPT_DIR}/engine" && -d "${SCRIPT_DIR}/../engine" ]]; then
  SCRIPT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
fi
BUILD_SCRIPT="${SCRIPT_DIR}/run-dataset-build.sh"
SERVICES_SCRIPT="${SCRIPT_DIR}/run-services.sh"
EMBED_JOB="${SCRIPT_DIR}/engine/server/db/jobs/build-video-embeddings.py"
WHITELIST_DB="${SCRIPT_DIR}/engine/server/db/whitelist.db"
INDEX_PATH="${SCRIPT_DIR}/engine/server/db/whitelist-video-embeddings.faiss"
LOG_FILE="${SCRIPT_DIR}/dataset-build-$(date +%Y%m%d-%H%M%S).log"

ACCEL="--gpu"
START_STAGE="embeddings"
RESTART_ENGINE=0
SKIP_MODEL_CHECK=0
DRY_RUN=0

# Print the usage block from this file's header.
print_usage() {
  sed -n '2,27p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --cpu) ACCEL="--cpu"; shift ;;
    --gpu) ACCEL="--gpu"; shift ;;
    --from) START_STAGE="$2"; shift 2 ;;
    --restart-engine) RESTART_ENGINE=1; shift ;;
    --skip-model-check) SKIP_MODEL_CHECK=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    --help|-h) print_usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; print_usage >&2; exit 2 ;;
  esac
done

# Emit a timestamped line.
log() {
  echo "[reembed $(date '+%Y-%m-%d %H:%M:%S')] $*"
}

# Report a failed check and stop. Every check here guards a failure that would otherwise
# surface hours into the run, or silently produce an unusable index.
fail() {
  echo "[reembed] BLOCKED: $*" >&2
  exit 1
}

# Resolve the interpreter that carries the project dependencies, matching the resolution
# order the other scripts use.
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

log "pre-flight checks"

[[ -x "${PY}" || -n "${PY}" ]] || fail "no usable Python interpreter found"
[[ -f "${BUILD_SCRIPT}" ]] || fail "missing ${BUILD_SCRIPT}"
[[ -f "${EMBED_JOB}" ]] || fail "missing ${EMBED_JOB}"
[[ -f "${WHITELIST_DB}" ]] || fail "missing ${WHITELIST_DB}; run the sync stage first"

# A second build writing the same tables would interleave two model spaces.
#
# Matched on whole argv entries rather than with `pgrep -f`, whose substring match also
# hits any shell whose command line merely mentions the script - including the one that
# launched this check.
build_already_running() {
  local cmdline_file pid arg
  for cmdline_file in /proc/[0-9]*/cmdline; do
    pid="${cmdline_file#/proc/}"
    pid="${pid%/cmdline}"
    [[ "${pid}" == "$$" ]] && continue
    while IFS= read -r -d '' arg; do
      if [[ "${arg##*/}" == "run-dataset-build.sh" ]]; then
        echo "${pid}"
        return 0
      fi
    done < "${cmdline_file}" 2>/dev/null
  done
  return 1
}

if RUNNING_PID="$(build_already_running)"; then
  fail "a dataset build is already running (pid ${RUNNING_PID}); check the newest dataset-build-*.log before starting another"
fi

# The embeddings stage rewrites video_embeddings wholesale. A running Engine holds the old
# index open, which is fine, but it must not be restarted mid-run: the startup gate
# compares the index sidecar against the database and will refuse a mismatched pair.
if [[ -f "${SCRIPT_DIR}/engine.pid" ]] && kill -0 "$(cat "${SCRIPT_DIR}/engine.pid")" 2>/dev/null; then
  log "note: Engine is running (pid $(cat "${SCRIPT_DIR}/engine.pid")). Leave it up, but do not restart it until this finishes."
fi

# Read the model the batch job will actually use, so a forgotten task 87 is caught before
# the expensive pass rather than after it.
MODEL_NAME="$("${PY}" - "${EMBED_JOB}" <<'PYEOF'
"""Print the default --model-name declared by the embeddings job."""
import ast
import sys

tree = ast.parse(open(sys.argv[1], encoding="utf-8").read())
for node in ast.walk(tree):
    if not isinstance(node, ast.Call):
        continue
    func = node.func
    if not (isinstance(func, ast.Attribute) and func.attr == "add_argument"):
        continue
    if not node.args or not isinstance(node.args[0], ast.Constant):
        continue
    if node.args[0].value != "--model-name":
        continue
    for keyword in node.keywords:
        if keyword.arg == "default" and isinstance(keyword.value, ast.Constant):
            print(keyword.value.value)
            sys.exit(0)
sys.exit(1)
PYEOF
)" || fail "could not read the default model from ${EMBED_JOB}"

log "model of record: ${MODEL_NAME}"
if [[ "${SKIP_MODEL_CHECK}" -eq 0 && "${MODEL_NAME}" != *multilingual* ]]; then
  fail "model '${MODEL_NAME}' does not look multilingual; task 87 has not landed. Re-run with --skip-model-check to proceed anyway."
fi

# A model absent from the HuggingFace cache is downloaded on first use. That works, but it
# happens inside the detached run, so a network failure surfaces as a dead build.
CACHE_DIR="${HF_HOME:-${HOME}/.cache/huggingface}/hub"
CACHE_KEY="models--sentence-transformers--${MODEL_NAME##*/}"
if [[ -d "${CACHE_DIR}/${CACHE_KEY}" ]]; then
  log "model cache: present (${CACHE_DIR}/${CACHE_KEY})"
else
  log "model cache: ABSENT. The first embedding batch will download it; a network failure will kill the run."
fi

# Row counts the stage is about to work through, so the log records the starting point.
"${PY}" - "${WHITELIST_DB}" <<'PYEOF'
"""Report the row counts the embeddings stage starts from."""
import sqlite3
import sys

conn = sqlite3.connect(sys.argv[1])
videos = conn.execute("SELECT COUNT(*) FROM videos").fetchone()[0]
try:
    rows = conn.execute(
        "SELECT model_name, embedding_dim, COUNT(*) FROM video_embeddings"
        " GROUP BY model_name, embedding_dim"
    ).fetchall()
except sqlite3.OperationalError:
    rows = []
print(f"[reembed] videos={videos}")
for model, dim, count in rows:
    print(f"[reembed] existing embeddings: {model} dim={dim} rows={count} (all replaced by --force)")
PYEOF

if [[ -f "${INDEX_PATH}.json" ]]; then
  log "current index sidecar: $(tr -d '\n' < "${INDEX_PATH}.json" | sed 's/  */ /g')"
fi

BUILD_CMD=(bash "${BUILD_SCRIPT}" --from "${START_STAGE}" "${ACCEL}" --log "${LOG_FILE}")

if [[ "${DRY_RUN}" -eq 1 ]]; then
  log "dry run; would execute: ${BUILD_CMD[*]}"
  exit 0
fi

log "starting: ${BUILD_CMD[*]}"
nohup "${BUILD_CMD[@]}" >/dev/null 2>&1 &
BUILD_PID=$!
log "detached as pid ${BUILD_PID}"
log "follow with: tail -f ${LOG_FILE}"

if [[ "${RESTART_ENGINE}" -eq 1 ]]; then
  log "waiting for the build to finish before restarting services"
  if wait "${BUILD_PID}"; then
    log "build succeeded; restarting services"
    bash "${SERVICES_SCRIPT}" restart
  else
    fail "build failed; services left untouched. Read ${LOG_FILE}."
  fi
else
  log "when it finishes, restart the Engine to load the new index: bash run-services.sh restart"
fi
