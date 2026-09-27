#!/usr/bin/env bash
#
# sync - copy the built client (client/frontend/dist/) to the nginx-served directory.
#
# nginx serves /var/www/peertube-browser, not the build directory (DEPLOYMENT.md §6), so
# every `npm run build` needs this before a browser shows the change.
#
# Usage:
#   scripts/sync

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
src="$repo_root/client/frontend/dist/"
dest="/var/www/peertube-browser/"

if [[ ! -f "$src/index.html" ]]; then
    echo "sync: $src has no index.html; run 'npm run build' in client/frontend first" >&2
    exit 1
fi

sudo mkdir -p "$dest"
sudo rsync -a --delete "$src" "$dest"
sudo chown -R www-data:www-data "$dest"
echo "sync: $src -> $dest"
