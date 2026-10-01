#!/usr/bin/env bash
# engine-upstream.sh - shared by the Engine installers and scripts/deploy-bluegreen.sh. Sourced, never run.
# The nginx upstream snippet is the single source of truth for which prod Engine instance (7070 or 7071) takes traffic.
# Its parse rule is mirrored by parse_upstream_snippet() in engine/server/db/jobs/updater-worker.py; tests/active/upstream_snippet_cases.json pins both.

ENGINE_INSTANCE_BASE="peertube-engine"
ENGINE_INSTANCE_PORTS=(7070 7071)
ENGINE_LISTENER_PORT=7079
# Overridable for tests only; production uses the default.
UPSTREAM_SNIPPET="${PEERTUBE_ENGINE_UPSTREAM_SNIPPET:-/etc/nginx/peertube-engine-upstream.conf}"
ENGINE_LISTENER_CONF="/etc/nginx/conf.d/peertube-engine-internal.conf"

# Print the deploy lock path for a repository root. Deploy, installer and updater all derive it the same way.
engine_deploy_lock_path() {
  printf '%s' "$1/engine/server/db/engine-deploy.lock"
}

# Print the active port: exactly one line starting with `server`, and that line is `server 127.0.0.1:7070;` or `…7071;`. Non-zero otherwise, including a missing or unreadable file.
read_active_port() {
  local path="$1" count line
  [[ -f "${path}" && -r "${path}" ]] || return 1
  count="$(grep -cE '^[[:blank:]]*server([[:blank:]]|$)' "${path}" || true)"
  [[ "${count}" == "1" ]] || return 1
  line="$(grep -E '^[[:blank:]]*server[[:blank:]]+127\.0\.0\.1:(7070|7071);[[:blank:]]*$' "${path}")" || return 1
  line="${line##*:}"
  printf '%s' "${line%%;*}"
}

# Print the other port of the pair.
other_instance_port() {
  if [[ "$1" == "7070" ]]; then printf '7071'; else printf '7070'; fi
}

# Print the snippet for a port. Three lines; nothing else lives in the file.
snippet_text() {
  printf 'upstream peertube_engine {\n    server 127.0.0.1:%s;\n}\n' "$1"
}

# Replace a file atomically from stdin with mode 0644. The temp file sits in the destination's directory under a dotted name that does not end in .conf, so nginx never includes it. 0644 lets the updater (service user) read the snippet.
replace_file() {
  local dest="$1" tmp
  tmp="$(mktemp "$(dirname "${dest}")/.$(basename "${dest}").XXXXXX")" || return 1
  if cat > "${tmp}" && chmod 0644 "${tmp}" && mv -f "${tmp}" "${dest}"; then
    return 0
  fi
  rm -f "${tmp}"
  return 1
}
