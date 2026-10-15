#!/usr/bin/env python3
"""Pull the devsecops skill and the dev-flow workflow from this repo into the repo you run it in, when this repo's version is newer.

Run from the target repo: `python <this-repo>/scripts/sync_devsecops.py [--dry-run] [--deploy]`. Each part is compared by the version file it ships; a part the target has without a version file is treated as older, and a part the target does not have at all is left alone. The replaced directory is backed up under `~/.cache/un-sync/` first. `--deploy` also refreshes the target's deployed agent and command copies, which otherwise are only reported when they differ.
"""

import argparse
import filecmp
import json
import os
import shutil
import sys
import time
from pathlib import Path

SOURCE = Path(__file__).resolve().parent.parent

# name -> (directory, version file inside it, [(staged dir inside it, deployed dir in the project)])
PARTS = {
    "devsecops": (".un/skills/devsecops", "skill.json",
                  [("agents", ".un/agents/devsecops"), ("commands", ".un/commands/devsecops")]),
    "dev-flow": (".un/workflows/dev-flow", "version.json",
                 [("agents", ".un/agents/workflows")]),
}
SKIP = shutil.ignore_patterns("__pycache__", "*.pyc")


def version(directory: Path, file: str) -> tuple[int, ...] | None:
    path = directory / file
    if not path.is_file():
        return None
    text = json.loads(path.read_text(encoding="utf-8"))["version"]
    return tuple(int(part) for part in text.split("."))


def shown(v: tuple[int, ...] | None) -> str:
    return ".".join(map(str, v)) if v else "none"


def staged_files(src: Path) -> list[Path]:
    return [p for p in sorted(src.glob("*.md")) if p.name != "README.md"]


def deployed(name: str, target: Path, deploy: bool, dry: bool) -> None:
    directory, _, pairs = PARTS[name]
    for staged, dest in pairs:
        for src in staged_files(SOURCE / directory / staged):
            out = target / dest / src.name
            if out.is_file() and filecmp.cmp(src, out, shallow=False):
                continue
            state = "is missing" if not out.exists() else "differs from the staged copy"
            if deploy and not dry:
                out.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, out)
                print(f"  deployed {dest}/{src.name}")
            else:
                print(f"  {dest}/{src.name} {state}" + ("" if deploy else "; --deploy refreshes it"))


def sync(name: str, target: Path, deploy: bool, dry: bool) -> None:
    directory, file, _ = PARTS[name]
    src, dest = SOURCE / directory, target / directory
    ours = version(src, file)
    if ours is None:
        sys.exit(f"{name}: no {directory}/{file} in {SOURCE}")
    if not dest.is_dir():
        print(f"{name}: not installed in {target}, skipped")
        return
    theirs = version(dest, file)
    if theirs is not None and theirs >= ours:
        print(f"{name}: {shown(theirs)} is current (source {shown(ours)})")
    else:
        print(f"{name}: {shown(theirs)} -> {shown(ours)}" + (" (dry run)" if dry else ""))
        if not dry:
            cache = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
            backup = cache / "un-sync" / target.name / f"{name}-{shown(theirs)}-{time.strftime('%Y%m%d-%H%M%S')}"
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(dest, backup)
            shutil.copytree(src, dest, ignore=SKIP)
            print(f"  backup: {backup}")
    deployed(name, target, deploy, dry)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--target", type=Path, default=Path.cwd(), help="repo to update; defaults to the working directory")
    p.add_argument("--dry-run", action="store_true", help="report what would change, write nothing")
    p.add_argument("--deploy", action="store_true", help="also refresh the deployed agent and command copies")
    args = p.parse_args()
    target = args.target.resolve()
    if target == SOURCE:
        sys.exit("the target is the source repo; run this from the repo you want to update")
    if not (target / ".un").is_dir():
        sys.exit(f"{target} has no .un/ directory")
    for name in PARTS:
        sync(name, target, args.deploy, args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
