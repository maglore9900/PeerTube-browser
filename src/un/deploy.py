"""Write the shipped container files from this checkout's deploy/ into the deploy/ of the project UN_PROJECT names, creating it, and keeping the files the operator changed.

Run by the operator at a terminal on the host: `UN_PROJECT=<project> python <checkout>/src/un/deploy.py`. Standard library only, so it runs where un is not installed, Windows included. `deploy/deploy-manifest.json` records the sha256 of what un last wrote to each file; a file matching neither that record nor the checkout is replaced only when the operator answers y, otherwise the checkout's copy lands beside it as `new_<name>`.
"""

import argparse
import hashlib
import json
import os
import shutil
import sys
import tomllib
from pathlib import Path

# Read at call time so tests can repoint it; the image creates it root-owned on a read-only root.
CONTAINER_MARKER = Path("/etc/un-container")

# rat-tail: hand-copied as VERBATIM in scripts/export_runtime.py and in .gitignore's container block, since neither can import this; one manifest replaces all three when un has its own repo.
DEPLOY_FILES = ("Containerfile", "compose.yaml", "proxy.py", "allowlist.example", "env.example", "reinstall.py")

MANIFEST = "deploy-manifest.json"

# rat-tail: copies of core's exit codes, since this script cannot import un; they can drift until un has one place both can read.
EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2


def un_root(root: Path) -> Path | None:
    """`root` when it holds un as src/un beside a pyproject.toml naming unstable-number."""
    try:
        name = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["name"]
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError, KeyError, TypeError):
        return None
    return root if name == "unstable-number" and (root / "src/un/core.py").is_file() else None


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_manifest(folder: Path) -> dict[str, str]:
    """The hashes `folder`'s manifest records; a missing, unreadable or malformed one reads as empty."""
    try:
        entries = json.loads((folder / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(entries, dict) or not all(isinstance(value, str) for value in entries.values()):
        return {}
    return entries


def write_manifest(folder: Path, entries: dict[str, str]) -> None:
    (folder / MANIFEST).write_text(json.dumps(entries, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _replace(name: str) -> bool:
    try:
        answer = input(f"deploy/{name} holds changes un did not write; replace it with the checkout's copy? [y/N] ")
    except EOFError:
        print()
        return False
    return answer.strip().lower() in ("y", "yes")


def deploy(checkout: Path, project: Path) -> tuple[list[str], list[str], list[str]]:
    """Write each shipped file `checkout` carries into `project`'s deploy/ by the manifest rule, then record what un wrote; the names written, left unchanged and kept."""
    source, folder = checkout / "deploy", project / "deploy"
    folder.mkdir(exist_ok=True)
    record = read_manifest(folder)
    written, unchanged, kept = [], [], []
    for name in DEPLOY_FILES:
        new, old = source / name, folder / name
        if not new.is_file():
            continue
        data = new.read_bytes()
        # exists(), not is_file(): a directory in the way raises and stops the run instead of receiving a copy.
        current = old.read_bytes() if old.exists() else None
        if current == data:
            # Mode only, so an identical file's bytes and mtime are left alone.
            shutil.copymode(new, old)
            unchanged.append(name)
        elif current is None or digest(current) == record.get(name) or _replace(name):
            shutil.copy2(new, old)
            written.append(name)
        else:
            shutil.copy2(new, folder / f"new_{name}")
            kept.append(name)
            continue
        record[name] = digest(data)
    write_manifest(folder, record)
    return written, unchanged, kept


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write this checkout's shipped deploy/ files into $UN_PROJECT/deploy/, creating it.")
    parser.parse_args(argv)
    # Only a person at a terminal may run it; an agent's shell has its output piped.
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        print("deploy.py runs only at a terminal; run it yourself from a shell", file=sys.stderr)
        return EXIT_USAGE
    if CONTAINER_MARKER.exists():
        print("deploy.py runs on the host only, not in a container", file=sys.stderr)
        return EXIT_USAGE
    here = Path(__file__).resolve().parents[2]
    checkout = un_root(here)
    if checkout is None:
        print(f"deploy.py: {here} is not a un checkout", file=sys.stderr)
        return EXIT_USAGE
    named = os.environ.get("UN_PROJECT", "").strip()
    if not named:
        print("deploy.py: set UN_PROJECT to the project directory the container works on, e.g. `UN_PROJECT=~/code/myproject python <checkout>/src/un/deploy.py`", file=sys.stderr)
        return EXIT_USAGE
    project = Path(named).expanduser().resolve()
    if not project.is_dir():
        print(f"deploy.py: UN_PROJECT names {project}, which is not a directory", file=sys.stderr)
        return EXIT_USAGE
    if project == checkout:
        print(f"deploy.py: UN_PROJECT names {project}, the checkout this script deploys from", file=sys.stderr)
        return EXIT_USAGE
    try:
        written, unchanged, kept = deploy(checkout, project)
    except OSError as exc:
        # str() of an OSError carries its filename, which names the path that failed.
        print(f"deploy.py stopped: {exc}", file=sys.stderr)
        return EXIT_FAILED
    folder = project / "deploy"
    print(f"deployed {checkout / 'deploy'} into {folder}")
    for label, names in (("written", written), ("unchanged, already identical", unchanged), ("kept, the checkout's copy is beside each as new_<name>", kept)):
        if names:
            print(f"{label}:")
            for name in names:
                print(f"  deploy/{name}")
    if kept:
        print("\nmerge each new_<name> into its file by hand, then delete it, before building")
    print(f"\nnext, from {folder}:")
    if not (folder / ".env").exists():
        print(f"  cp env.example .env, then set UN_RUNTIME to the exported runtime's root and UN_PROJECT={project}")
    print("  docker compose build  (podman: podman-compose build)")
    print("  docker compose --profile reinstall run --rm reinstall  (podman: podman-compose --profile reinstall run --rm reinstall)")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
