#!/usr/bin/env bash
#
# run-dataset-build.sh - enrich, re-embed and rebuild every derived artifact, in order.
#
# Runs the full pipeline after a crawl: tags/comments enrichment, whitelist sync,
# embeddings, ANN index, similarity cache, random cache and popularity. Each stage
# depends on the previous one, so the script stops at the first failure and reports
# row counts between stages rather than assuming a stage did what it claimed.
#
# Usage:
#   bash run-dataset-build.sh [options]
#
# Options:
#   --cpu / --gpu      Acceleration for embeddings, index and similarity (default: gpu).
#   --embed-model <name>
#                      SentenceTransformer model for the embeddings stage
#                      (default: paraphrase-multilingual-MiniLM-L12-v2). The Engine's
#                      QUERY_ENCODER_MODEL must name the same model, or it serves no
#                      vector search results.
#   --skip-enrichment  Skip the tags/comments crawl stages.
#   --skip-comments    Skip only the comments pass. The crawler fetches comment counts,
#                      not threads, and the count contributes a bare integer to the
#                      embedding text - low value for a full extra pass over every video.
#   --concurrency <n>  Hosts crawled in parallel during enrichment (crawler default: 4).
#   --exclude-hosts <path>
#                      Hosts to skip, one per line. Defaults to
#                      engine/crawler/excluded-hosts.txt when that file exists.
#   --allow-no-tags    Continue even if tags coverage is below the threshold.
#   --min-tag-pct <n>  Required tags coverage before embedding (default: 50).
#   --skip-popularity  Skip the final popularity recompute.
#   --from <stage>     Start at a stage: enrichment, sync, embeddings, index,
#                      similarity, random, popularity.
#   --log <path>       Log file (default: dataset-build-<timestamp>.log).
#   --help             Show this help.
#
# Run it detached; the whole pipeline is hours:
#   nohup bash run-dataset-build.sh > /dev/null 2>&1 &
#   tail -f dataset-build-*.log

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# These scripts operate on the repository root. They used to live there; they now live in
# scripts/, so every ${SCRIPT_DIR}/... path below would resolve one level too deep.
if [[ ! -d "${SCRIPT_DIR}/engine" && -d "${SCRIPT_DIR}/../engine" ]]; then
  SCRIPT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
fi
CRAWLER_DIR="${SCRIPT_DIR}/engine/crawler"
DB_DIR="${SCRIPT_DIR}/engine/server/db"
JOBS_DIR="${DB_DIR}/jobs"
CRAWL_DB="${CRAWLER_DIR}/data/crawl.db"
WHITELIST_DB="${DB_DIR}/whitelist.db"
INDEX_PATH="${DB_DIR}/whitelist-video-embeddings.faiss"
META_PATH="${DB_DIR}/whitelist-video-embeddings.faiss.json"
SIMILARITY_DB="${DB_DIR}/similarity-cache.db"
RANDOM_DB="${DB_DIR}/random-cache.db"

ACCEL="--gpu"
EMBED_MODEL="paraphrase-multilingual-MiniLM-L12-v2"
SKIP_ENRICHMENT=0
SKIP_COMMENTS=0
CONCURRENCY=""
EXCLUDE_HOSTS_FILE="${SCRIPT_DIR}/engine/crawler/excluded-hosts.txt"
ALLOW_NO_TAGS=0
MIN_TAG_PCT=50
SKIP_POPULARITY=0
START_STAGE="enrichment"
LOG_FILE="${SCRIPT_DIR}/dataset-build-$(date +%Y%m%d-%H%M%S).log"

# Print the usage block from this file's header.
print_usage() {
  sed -n '2,34p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --cpu) ACCEL="--cpu"; shift ;;
    --gpu) ACCEL="--gpu"; shift ;;
    --embed-model) EMBED_MODEL="$2"; shift 2 ;;
    --skip-enrichment) SKIP_ENRICHMENT=1; shift ;;
    --skip-comments) SKIP_COMMENTS=1; shift ;;
    --concurrency) CONCURRENCY="$2"; shift 2 ;;
    --exclude-hosts) EXCLUDE_HOSTS_FILE="$2"; shift 2 ;;
    --allow-no-tags) ALLOW_NO_TAGS=1; shift ;;
    --min-tag-pct) MIN_TAG_PCT="$2"; shift 2 ;;
    --skip-popularity) SKIP_POPULARITY=1; shift ;;
    --from) START_STAGE="$2"; shift 2 ;;
    --log) LOG_FILE="$2"; shift 2 ;;
    --help|-h) print_usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; print_usage >&2; exit 2 ;;
  esac
done

exec > >(tee -a "${LOG_FILE}") 2>&1

# Emit a timestamped progress line.
log() {
  echo "[build $(date '+%Y-%m-%d %H:%M:%S')] $*"
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

# Decide whether a stage runs, honouring --from.
STAGE_ORDER=(enrichment sync embeddings index similarity random popularity)
stage_index() {
  local target="$1" i=0
  for name in "${STAGE_ORDER[@]}"; do
    if [[ "${name}" == "${target}" ]]; then echo "${i}"; return 0; fi
    i=$((i + 1))
  done
  echo "-1"
}
START_INDEX="$(stage_index "${START_STAGE}")"
if [[ "${START_INDEX}" == "-1" ]]; then
  echo "Unknown --from stage: ${START_STAGE}" >&2
  exit 2
fi
should_run() {
  local this_index
  this_index="$(stage_index "$1")"
  (( this_index >= START_INDEX ))
}

# Report row counts for a database, so partial stages are visible rather than assumed.
report_counts() {
  local db="$1"
  [[ -f "${db}" ]] || { log "  (missing: ${db})"; return 0; }
  "${PY}" - "${db}" <<'PYEOF'
import sqlite3
import sys

conn = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)


def count(sql):
    """Return a single count, or None when the table is absent."""
    try:
        return conn.execute(sql).fetchone()[0]
    except sqlite3.OperationalError:
        return None


parts = {
    "videos": count("SELECT COUNT(*) FROM videos"),
    "with_tags": count("SELECT COUNT(*) FROM videos WHERE tags_json IS NOT NULL"),
    "with_comments": count("SELECT COUNT(*) FROM videos WHERE comments_count IS NOT NULL"),
    "embeddings": count("SELECT COUNT(*) FROM video_embeddings"),
    # Printed next to `videos` so a full-text index that drifted from its content table
    # is visible in the build log instead of at the first failed search.
    "fts": count("SELECT COUNT(*) FROM videos_fts"),
}
print("  " + "  ".join(f"{k}={v}" for k, v in parts.items() if v is not None))
conn.close()
PYEOF
}

# Abort before the expensive embedding stage if enrichment clearly did not land.
check_tag_coverage() {
  local pct
  pct="$("${PY}" - "${WHITELIST_DB}" <<'PYEOF'
import sqlite3
import sys

conn = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
total = conn.execute("SELECT COUNT(*) FROM videos").fetchone()[0]
tagged = conn.execute(
    "SELECT COUNT(*) FROM videos WHERE tags_json IS NOT NULL"
).fetchone()[0]
print(0 if total == 0 else int(tagged * 100 / total))
conn.close()
PYEOF
)"
  log "tags coverage: ${pct}% (threshold ${MIN_TAG_PCT}%)"
  if (( pct < MIN_TAG_PCT )); then
    if (( ALLOW_NO_TAGS == 1 )); then
      log "WARNING: continuing with low tag coverage because --allow-no-tags was given."
      log "         Embeddings will encode title and description only."
    else
      log "ABORT: tag coverage below threshold. Embedding now would have to be redone."
      log "       Re-run the enrichment stages, or pass --allow-no-tags to proceed."
      exit 1
    fi
  fi
}

log "log file:   ${LOG_FILE}"
log "python:     ${PY}"
log "accel:      ${ACCEL}"
log "start at:   ${START_STAGE}"

if should_run enrichment && (( SKIP_ENRICHMENT == 0 )); then
  ENRICH_ARGS=()
  [[ -n "${CONCURRENCY}" ]] && ENRICH_ARGS+=(--concurrency "${CONCURRENCY}")
  if [[ -f "${EXCLUDE_HOSTS_FILE}" ]]; then
    ENRICH_ARGS+=(--exclude-hosts-file "${EXCLUDE_HOSTS_FILE}")
    log "excluding hosts listed in ${EXCLUDE_HOSTS_FILE}"
  fi
  log "stage: enrichment (tags)${CONCURRENCY:+ concurrency=${CONCURRENCY}}"
  # The tags stage is resumable by construction: listVideosForTags selects only rows
  # with tags_json NULL or '[]', so an interrupted run resumes from what is missing.
  npm --prefix "${CRAWLER_DIR}" run crawl:videos:tags -- "${ENRICH_ARGS[@]+"${ENRICH_ARGS[@]}"}"
  if (( SKIP_COMMENTS == 0 )); then
    log "stage: enrichment (comments)"
    npm --prefix "${CRAWLER_DIR}" run crawl:videos:comments -- "${ENRICH_ARGS[@]+"${ENRICH_ARGS[@]}"}"
  else
    log "stage: enrichment (comments) SKIPPED"
  fi
  log "crawl.db after enrichment:"
  report_counts "${CRAWL_DB}"
fi

if should_run sync; then
  log "stage: sync-whitelist"
  "${PY}" "${JOBS_DIR}/sync-whitelist.py" --db "${CRAWL_DB}" --output-db "${WHITELIST_DB}"
  log "whitelist.db after sync:"
  report_counts "${WHITELIST_DB}"
fi

if should_run embeddings; then
  check_tag_coverage
  log "stage: embeddings (--force, full rebuild) model=${EMBED_MODEL}"
  "${PY}" "${JOBS_DIR}/build-video-embeddings.py" \
    --db-path "${WHITELIST_DB}" "${ACCEL}" --force --model-name "${EMBED_MODEL}"
  log "whitelist.db after embeddings:"
  report_counts "${WHITELIST_DB}"
fi

if should_run index; then
  log "stage: ANN index"
  "${PY}" "${JOBS_DIR}/build-ann-index.py" \
    --db-path "${WHITELIST_DB}" \
    --index-path "${INDEX_PATH}" \
    --meta-path "${META_PATH}" \
    --normalize "${ACCEL}"
fi

if should_run similarity; then
  log "stage: similarity cache (recreating ${SIMILARITY_DB})"
  "${PY}" "${JOBS_DIR}/precompute-similar-ann.py" \
    --db "${WHITELIST_DB}" \
    --index "${INDEX_PATH}" \
    --out "${SIMILARITY_DB}" \
    --top-k 20 --nprobe 16 --recreate-out-db "${ACCEL}"
fi

if should_run random; then
  log "stage: random cache"
  "${PY}" "${JOBS_DIR}/precompute-random-rowids.py" \
    --db "${WHITELIST_DB}" --out "${RANDOM_DB}" \
    --size 5000 --filtered --max-per-author 100 --reset
fi

if should_run popularity && (( SKIP_POPULARITY == 0 )); then
  log "stage: popularity"
  "${PY}" "${JOBS_DIR}/recompute-popularity.py" \
    --db "${WHITELIST_DB}" --like-weight 2.0 --reset
fi

log "dataset build complete"
report_counts "${WHITELIST_DB}"
log "restart the Engine so it loads the new index"
