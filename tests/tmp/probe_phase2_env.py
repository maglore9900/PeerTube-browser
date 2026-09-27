import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CRAWLER = ROOT / "engine" / "crawler"
SRC = CRAWLER / "src" / "host-filters.ts"
DIST = CRAWLER / "dist" / "host-filters.js"
NODE_SCRIPT = """
import { readFileSync } from "node:fs";
const { normalizeHostToken } = await import(process.env.HOST_FILTERS_URL);
const inputs = JSON.parse(readFileSync(0, "utf8"));
process.stdout.write(JSON.stringify(inputs.map((value) => normalizeHostToken(value))));
"""


def run(cmd, **kw):
    proc = subprocess.run(cmd, capture_output=True, text=True, **kw)
    print("$", cmd, "->", proc.returncode, repr(proc.stdout), repr(proc.stderr))
    return proc


def test_probe(tmp_path):
    print("python", sys.executable, sys.version)
    print("node", shutil.which("node"), "git", shutil.which("git"), "PATH", os.environ.get("PATH"))
    print("node realpath", os.path.realpath(shutil.which("node")), "git realpath", os.path.realpath(shutil.which("git")))
    run(["node", "--version"])
    git = shutil.which("git")
    run([git, "log", "-1", "--format=%ct", "--", str(SRC)], cwd=ROOT)
    run([git, "log", "-1", "--format=%ct", "--", str(DIST)], cwd=ROOT)
    run([git, "status", "--porcelain", "--", str(SRC), str(DIST)], cwd=ROOT)
    run([git, "check-ignore", "-v", str(ROOT / "tests" / "tmp" / "x.js")], cwd=ROOT)
    print("mtime src", SRC.stat().st_mtime, "dist", DIST.stat().st_mtime)
    pairs = json.loads((ROOT / "tests" / "active" / "host_tokens.json").read_text(encoding="utf-8"))
    inputs = [p["input"] for p in pairs]
    proc = run([shutil.which("node"), "--input-type=module", "-e", NODE_SCRIPT], input=json.dumps(inputs), encoding="utf-8", env={**os.environ, "HOST_FILTERS_URL": DIST.as_uri()})
    print("node map", dict(zip(inputs, json.loads(proc.stdout))))
    # temp repo driven by GIT_DIR/GIT_WORK_TREE, commands run from the real worktree root
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "dist").mkdir()
    genv = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    run([git, "init", "-q", str(repo)], env=genv)
    (repo / "dist" / "a.js").write_text("d\n")
    run([git, "add", "dist/a.js"], cwd=repo, env=genv)
    run([git, "commit", "-q", "-m", "d"], cwd=repo, env={**genv, "GIT_AUTHOR_DATE": "2020-01-01T00:00:00Z", "GIT_COMMITTER_DATE": "2020-01-01T00:00:00Z"})
    (repo / "src" / "a.ts").write_text("s\n")
    run([git, "add", "src/a.ts"], cwd=repo, env=genv)
    run([git, "commit", "-q", "-m", "s"], cwd=repo, env={**genv, "GIT_AUTHOR_DATE": "2021-01-01T00:00:00Z", "GIT_COMMITTER_DATE": "2021-01-01T00:00:00Z"})
    redirect = {**os.environ, "GIT_DIR": str(repo / ".git"), "GIT_WORK_TREE": str(repo)}
    run([git, "log", "-1", "--format=%ct", "--", str(repo / "src" / "a.ts")], cwd=ROOT, env=redirect)
    run([git, "log", "-1", "--format=%ct", "--", str(repo / "dist" / "a.js")], cwd=ROOT, env=redirect)
    run([git, "status", "--porcelain", "--", str(repo / "src" / "a.ts")], cwd=ROOT, env=redirect)
    (repo / "src" / "a.ts").write_text("s2\n")
    run([git, "status", "--porcelain", "--", str(repo / "src" / "a.ts")], cwd=ROOT, env=redirect)
    (repo / "src" / "new.ts").write_text("n\n")
    run([git, "log", "-1", "--format=%ct", "--", str(repo / "src" / "new.ts")], cwd=ROOT, env=redirect)
    run([git, "status", "--porcelain", "--", str(repo / "src" / "new.ts")], cwd=ROOT, env=redirect)
