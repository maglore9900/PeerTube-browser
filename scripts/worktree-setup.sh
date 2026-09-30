#!/usr/bin/env bash
# Prototype: create one build worktree with the gitignored runtime it needs.
# usage: worktree-setup.sh <branch>   e.g. worktree-setup.sh fix/10-normalise-instance-hosts
# Run from the main checkout, on an up-to-date main.
set -euo pipefail

branch="$1"
root="$(git rev-parse --show-toplevel)"
wt="$root/.worktrees/${branch//\//-}"

grep -qxF '/.worktrees/' "$root/.git/info/exclude" 2>/dev/null \
  || echo '/.worktrees/' >> "$root/.git/info/exclude"

# These paths become symlinks below. If main tracks any of them (a symlink committed from an
# earlier worktree), a later merge deletes the real ignored directory on main. Refuse instead.
tracked="$(git -C "$root" ls-files -- engine/.pixi client/frontend/node_modules engine/crawler/node_modules)"
if [ -n "$tracked" ]; then
  echo "refusing: main tracks runtime paths that must stay untracked:" >&2
  echo "$tracked" >&2
  echo "run: git rm --cached $tracked && commit" >&2
  exit 1
fi

git -C "$root" worktree add -b "$branch" "$wt" main

# Large, read-mostly data: shared.
for f in whitelist.db similarity-cache.db whitelist-video-embeddings.faiss whitelist-video-embeddings.faiss.json; do
  ln -s "$root/engine/server/db/$f" "$wt/engine/server/db/$f"
done
# Replaced by rename at every Engine cache build, startup and periodic: a private copy, not a symlink, because the Engine resolves the path and would build and rename into main's db/.
cp "$root/engine/server/db/random-cache.db" "$wt/engine/server/db/random-cache.db"

# Environments: shared (no editable installs).
ln -s "$root/engine/.pixi" "$wt/engine/.pixi"
ln -s "$root/client/frontend/node_modules" "$wt/client/frontend/node_modules"
ln -s "$root/engine/crawler/node_modules" "$wt/engine/crawler/node_modules"

# Skills and config: private copy with project_dir pointed at the worktree.
# Memory stays shared so learnings from every lane land in one place.
rsync -a --exclude sessions --exclude memory "$root/.un/" "$wt/.un/"
ln -s "$root/.un/memory" "$wt/.un/memory"
python3 - "$wt" <<'PY'
import json, sys, pathlib
wt = pathlib.Path(sys.argv[1])
cfg = wt / ".un/skills/devsecops/config.json"
data = json.loads(cfg.read_text())
data["project_dir"] = str(wt)
cfg.write_text(json.dumps(data, indent=2) + "\n")
PY

if [ -n "$(git -C "$wt" status --porcelain -- engine client)" ]; then
  echo "warning: the worktree's runtime symlinks show in git status; check .gitignore before committing" >&2
fi

echo "ready: $wt"
echo "smoke: cd $wt && ./.un/skills/devsecops/scripts/validate_tests.py --show-config"
