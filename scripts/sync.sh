#!/usr/bin/env bash
#
# sync - build the client (client/frontend) and copy dist/ to the nginx-served directory.
#
# nginx serves /var/www/peertube-browser, not the build directory (DEPLOYMENT.md §6). The
# build always runs first: the committed dist/ lags the source, and copying it unbuilt
# deploys an older client.
#
# Usage:
#   scripts/sync.sh

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
frontend="$repo_root/client/frontend"
src="$frontend/dist/"
dest="/var/www/peertube-browser/"

(cd "$frontend" && npm run build)

sudo mkdir -p "$dest"
sudo rsync -a --delete "$src" "$dest"
sudo chown -R www-data:www-data "$dest"
echo "sync: $src -> $dest"
