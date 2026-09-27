"""Phase 2 checkpoint: the crawler's compiled `normalizeHostToken` against the pinned pairs, and the durable test that checks it failing loudly when it cannot.

- `engine/crawler/dist/host-filters.js`, imported by node through its file:// URL, maps the 15 pinned inputs to exactly the pinned values, and `tests/active/host_tokens.json` holds exactly those 15 pairs, so with phase 1 the Python port equals the crawler on the fixture.
- `tests/active/test_host_normalisation.py -k crawler_dist`, run in its own pytest, passes on this tree, and fails, without the build hint, on a current dist that returns a wrong value for one input, whichever of the fixture's 15 inputs that is.
- That run fails, never skips, with the build hint in its message when node is off PATH, when dist is missing, when src was committed after dist, when src has an uncommitted edit newer on disk than dist, and when dist has no history and is older on disk than src; it fails when git is off PATH; and it passes when dist was committed after src, or at the same time as a clean src, though older on disk.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DURABLE = ROOT / "tests" / "active" / "test_host_normalisation.py"
FIXTURE_PAIRS = json.loads((ROOT / "tests" / "active" / "host_tokens.json").read_text(encoding="utf-8"))
REAL_SRC = ROOT / "engine" / "crawler" / "src" / "host-filters.ts"
REAL_DIST = ROOT / "engine" / "crawler" / "dist" / "host-filters.js"
BUILD_HINT = "cd engine/crawler && npm install && npm run build"
NODE = shutil.which("node")
GIT = shutil.which("git")

# The pinned values from the requirements, written out independently of the fixture and of the crawler.
PINNED = {
    " Tube.Example ": "tube.example",
    "tube.example.": "tube.example",
    "..tube.example..": "tube.example",
    "https://Tube.Example/": "tube.example",
    "http://tube.example:8080/path": "tube.example",
    "https://user@tube.example": "tube.example",
    "tube.example/videos": "tube.example",
    "tube.example:9000": "tube.example:9000",
    "https://[::1]:8080/": "[::1]",
    "https://bücher.example/": "xn--bcher-kva.example",
    "": None,
    "   ": None,
    ".": None,
    "https://": None,
    "https://tube.example./": "tube.example.",
}

NODE_SCRIPT = """
import { readFileSync } from "node:fs";
const { normalizeHostToken } = await import(process.env.HOST_FILTERS_URL);
const inputs = JSON.parse(readFileSync(0, "utf8"));
process.stdout.write(JSON.stringify(inputs.map((value) => normalizeHostToken(value))));
"""

# Loaded into the durable test's own pytest: points its SRC/DIST constants at a scenario's files, and errors (not fails) if a constant is gone, so a rename cannot pass as a loud failure.
PATHS_PLUGIN = """
import json
import os
from pathlib import Path


def pytest_runtest_setup(item):
    for name, value in json.loads(os.environ["HOST_FILTERS_PATHS"]).items():
        if not isinstance(getattr(item.module, name, None), Path):
            raise RuntimeError(f"{item.module.__name__} has no Path constant {name} to redirect")
        setattr(item.module, name, Path(value))
"""

# The one line whose removal makes a single pinned input (" Tube.Example ") come out wrong.
LOWERCASE_LINE = "const raw = value.trim().toLowerCase();"

# Renamed so an appended wrapper can take over the export and be wrong on one chosen input only.
EXPORT_LINE = "export function normalizeHostToken(value) {"
WRONG_HOST = "wrong-host.invalid"


def _run_crawler_test(tmp_path: Path, env: dict[str, str] | None = None, paths: dict[str, Path] | None = None) -> tuple[str, str]:
    """Run the durable crawler test in its own pytest; return its junit outcome (passed, failure, error, skipped or not collected) and message."""
    report = tmp_path / "report.xml"
    cmd = [sys.executable, "-m", "pytest", str(DURABLE), "-k", "crawler_dist", "-p", "no:cacheprovider", f"--junit-xml={report}"]
    run_env = {**os.environ, **(env or {})}
    if paths:
        plugin_dir = tmp_path / "plugin"
        plugin_dir.mkdir()
        (plugin_dir / "host_paths_plugin.py").write_text(PATHS_PLUGIN, encoding="utf-8")
        run_env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(plugin_dir), os.environ.get("PYTHONPATH")]))
        run_env["HOST_FILTERS_PATHS"] = json.dumps({name: str(path) for name, path in paths.items()})
        cmd += ["-p", "host_paths_plugin"]
    proc = subprocess.run(cmd, cwd=ROOT, env=run_env, capture_output=True, text=True, encoding="utf-8", timeout=600)
    output = proc.stdout[-4000:] + proc.stderr[-2000:]
    cases = list(ET.parse(report).getroot().iter("testcase")) if report.is_file() else []
    # Control: -k selected at most one test, so the outcome below belongs to a single durable crawler test.
    assert len(cases) <= 1, output
    # No durable crawler test is itself an outcome every judged assertion rejects, never a pass.
    if not cases:
        return "not collected", output
    for tag in ("failure", "error", "skipped"):
        found = cases[0].find(tag)
        if found is not None:
            # Only junit's message, never the traceback text: that lists the durable test's source, so a hint written there would match without being raised.
            return tag, found.get("message", "")
    return "passed", output


def _git(repo: Path, *args: str, date: str | None = None) -> None:
    env = {**os.environ, "GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date} if date else None
    subprocess.run([GIT, "-c", "user.name=checkpoint", "-c", "user.email=checkpoint@example.invalid", "-c", "commit.gpgsign=false", *args], cwd=repo, env=env, capture_output=True, check=True)


def _commit(repo: Path, path: Path, date: str) -> None:
    _git(repo, "add", str(path.relative_to(repo)))
    _git(repo, "commit", "-q", "-m", path.name, date=date)


def _crawler_copy(tmp_path: Path) -> tuple[Path, Path, Path]:
    """A throwaway git repo holding copies of the crawler's src and dist, nothing committed yet."""
    assert GIT is not None and NODE is not None
    repo = tmp_path / "crawler"
    src = repo / "src" / "host-filters.ts"
    dist = repo / "dist" / "host-filters.js"
    src.parent.mkdir(parents=True)
    dist.parent.mkdir()
    shutil.copyfile(REAL_SRC, src)
    shutil.copyfile(REAL_DIST, dist)
    # The crawler package's "type": "module" is what makes node load dist/*.js as ESM; the copy needs the same.
    (repo / "package.json").write_text('{"type": "module"}\n', encoding="utf-8")
    _git(repo, "init", "-q")
    return repo, src, dist


def _older_on_disk(older: Path, newer: Path) -> None:
    now = time.time()
    os.utime(older, (now - 3600, now - 3600))
    os.utime(newer, (now, now))


def _git_env(repo: Path) -> dict[str, str]:
    # The durable test runs git from the real worktree root; these make that git answer for the scenario's repo instead.
    return {"GIT_DIR": str(repo / ".git"), "GIT_WORK_TREE": str(repo)}


def _path_with_only(tmp_path: Path, name: str, target: str) -> str:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / name).symlink_to(os.path.realpath(target))
    return str(bin_dir)


def _dist_outputs(dist: Path) -> dict[str, str | None]:
    """What `normalizeHostToken` in `dist`, run under node, returns for each pinned input."""
    inputs = list(PINNED)
    proc = subprocess.run([NODE, "--input-type=module", "-e", NODE_SCRIPT], input=json.dumps(inputs), capture_output=True, text=True, encoding="utf-8", timeout=60, env={**os.environ, "HOST_FILTERS_URL": dist.as_uri()})
    assert proc.returncode == 0, proc.stderr
    return dict(zip(inputs, json.loads(proc.stdout)))


def test_crawler_dist_under_node_returns_pinned_values():
    # Premise, true before the phase: the real dist already yields PINNED, so the durable test passing on this tree below means it agrees with the crawler.
    assert NODE is not None
    assert _dist_outputs(REAL_DIST) == PINNED
    # The fixture phase 1's port is held to is these same pairs; a dict alone would hide a duplicated input.
    assert len(FIXTURE_PAIRS) == len(PINNED)
    assert {pair["input"]: pair["expected"] for pair in FIXTURE_PAIRS} == PINNED


def test_durable_crawler_test_passes_on_this_tree(tmp_path):
    # When written, this tree's dist was committed with src yet a few ms older on disk; that boundary is pinned in a controlled repo below, since a checkout can change it.
    outcome, message = _run_crawler_test(tmp_path)
    assert outcome == "passed", message  # C1


@pytest.mark.parametrize("broken", [pair["input"] for pair in FIXTURE_PAIRS], ids=[repr(pair["input"]) for pair in FIXTURE_PAIRS])
def test_durable_crawler_test_fails_on_current_dist_wrong_on_this_fixture_input(tmp_path, broken):
    repo, src, dist = _crawler_copy(tmp_path)
    text = dist.read_text(encoding="utf-8")
    assert text.count(EXPORT_LINE) == 1
    wrapper = f"export function normalizeHostToken(value) {{ return value === {json.dumps(broken)} ? {json.dumps(WRONG_HOST)} : pinnedNormalizeHostToken(value); }}\n"
    dist.write_text(text.replace(EXPORT_LINE, "function pinnedNormalizeHostToken(value) {") + wrapper, encoding="utf-8")
    # Control: this dist is wrong on the broken input alone, so a durable test that leaves out any one fixture pair passes one of these runs.
    assert _dist_outputs(dist) == {**PINNED, broken: WRONG_HOST}
    _commit(repo, src, "2020-01-01T00:00:00Z")
    _commit(repo, dist, "2021-01-01T00:00:00Z")
    outcome, message = _run_crawler_test(tmp_path, env=_git_env(repo), paths={"SRC": src, "DIST": dist})
    assert outcome == "failure", message  # C1
    assert WRONG_HOST in message  # C1
    assert BUILD_HINT not in message  # C2


def test_durable_crawler_test_fails_on_current_dist_with_one_wrong_value(tmp_path):
    repo, src, dist = _crawler_copy(tmp_path)
    text = dist.read_text(encoding="utf-8")
    assert text.count(LOWERCASE_LINE) == 1
    dist.write_text(text.replace(LOWERCASE_LINE, "const raw = value.trim();"), encoding="utf-8")
    _commit(repo, src, "2020-01-01T00:00:00Z")
    _commit(repo, dist, "2021-01-01T00:00:00Z")
    outcome, message = _run_crawler_test(tmp_path, env=_git_env(repo), paths={"SRC": src, "DIST": dist})
    assert outcome == "failure", message  # C1
    assert "'Tube.Example'" in message  # C1
    assert BUILD_HINT not in message  # C2


def test_durable_crawler_test_fails_loudly_without_node(tmp_path):
    assert GIT is not None
    outcome, message = _run_crawler_test(tmp_path, env={"PATH": _path_with_only(tmp_path, "git", GIT)})
    assert outcome == "failure", message  # C2
    assert BUILD_HINT in message  # C2


def test_durable_crawler_test_fails_loudly_when_dist_is_missing(tmp_path):
    outcome, message = _run_crawler_test(tmp_path, paths={"DIST": tmp_path / "dist" / "host-filters.js"})
    assert outcome == "failure", message  # C2
    assert BUILD_HINT in message  # C2


def test_durable_crawler_test_fails_loudly_when_src_committed_after_dist(tmp_path):
    repo, src, dist = _crawler_copy(tmp_path)
    _commit(repo, dist, "2020-01-01T00:00:00Z")
    _commit(repo, src, "2021-01-01T00:00:00Z")
    # Newer on disk, so only the commit-time rule can call this dist stale.
    _older_on_disk(src, dist)
    outcome, message = _run_crawler_test(tmp_path, env=_git_env(repo), paths={"SRC": src, "DIST": dist})
    assert outcome == "failure", message  # C2
    assert BUILD_HINT in message  # C2


def test_durable_crawler_test_passes_when_dist_committed_after_src_though_older_on_disk(tmp_path):
    repo, src, dist = _crawler_copy(tmp_path)
    _commit(repo, src, "2020-01-01T00:00:00Z")
    _commit(repo, dist, "2021-01-01T00:00:00Z")
    _older_on_disk(dist, src)
    outcome, message = _run_crawler_test(tmp_path, env=_git_env(repo), paths={"SRC": src, "DIST": dist})
    assert outcome == "passed", message  # C2


def test_durable_crawler_test_passes_when_dist_committed_with_clean_src_though_older_on_disk(tmp_path):
    repo, src, dist = _crawler_copy(tmp_path)
    _commit(repo, dist, "2020-01-01T00:00:00Z")
    _commit(repo, src, "2020-01-01T00:00:00Z")
    # Equal commit times and no edit, as a checkout leaves this tree: an mtime-only rule or a >= commit-time rule fails here.
    _older_on_disk(dist, src)
    outcome, message = _run_crawler_test(tmp_path, env=_git_env(repo), paths={"SRC": src, "DIST": dist})
    assert outcome == "passed", message  # C2


def test_durable_crawler_test_fails_loudly_when_uncommitted_src_edit_is_newer_than_dist(tmp_path):
    repo, src, dist = _crawler_copy(tmp_path)
    _commit(repo, dist, "2020-01-01T00:00:00Z")
    _commit(repo, src, "2020-01-01T00:00:00Z")
    # Equal commit times: only the uncommitted edit, judged by mtime, can call this dist stale.
    src.write_text(src.read_text(encoding="utf-8") + "// edited, not rebuilt\n", encoding="utf-8")
    _older_on_disk(dist, src)
    outcome, message = _run_crawler_test(tmp_path, env=_git_env(repo), paths={"SRC": src, "DIST": dist})
    assert outcome == "failure", message  # C2
    assert BUILD_HINT in message  # C2


def test_durable_crawler_test_fails_loudly_when_dist_has_no_history_and_is_older(tmp_path):
    repo, src, dist = _crawler_copy(tmp_path)
    _commit(repo, src, "2020-01-01T00:00:00Z")
    _older_on_disk(dist, src)
    outcome, message = _run_crawler_test(tmp_path, env=_git_env(repo), paths={"SRC": src, "DIST": dist})
    assert outcome == "failure", message  # C2
    assert BUILD_HINT in message  # C2


def test_durable_crawler_test_fails_without_git(tmp_path):
    assert NODE is not None
    outcome, message = _run_crawler_test(tmp_path, env={"PATH": _path_with_only(tmp_path, "node", NODE)})
    assert outcome == "failure", message  # C2
    assert "git" in message  # C2
