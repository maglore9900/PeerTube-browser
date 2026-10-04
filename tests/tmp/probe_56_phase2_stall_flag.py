"""Probe: the checkpoint's assertions against a tmp copy of the worker with the planned `run --stall-seconds` line added (green expected), and with a type=int mutant (red expected)."""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))

from test_translate_worker import ENGINE_PY, SERVER_DIR, WORKER, _paths  # noqa: E402

ANCHOR = '    return parser.parse_args()\n'
GOOD = '    run.add_argument("--stall-seconds", type=_positive_int, default=STALL_SECONDS, help="x")\n'
MUTANT = '    run.add_argument("--stall-seconds", type=int, default=STALL_SECONDS, help="x")\n'


def _copy(root: Path, line: str) -> Path:
    path = root / "a" / "db" / "jobs" / "translate-worker.py"
    path.parent.mkdir(parents=True)
    text = WORKER.read_text()
    assert ANCHOR in text
    path.write_text(text.replace(ANCHOR, line + ANCHOR))
    return path


def test_probe(tmp_path, monkeypatch):
    out = []
    env = {**os.environ, "PYTHONPATH": f"{SERVER_DIR}:{SERVER_DIR / 'api'}"}
    for name, line in (("good", GOOD), ("mutant", MUTANT)):
        root = tmp_path / name
        script = _copy(root, line)
        for value in ("0", "-1", "1.5", "x"):
            work = root / f"w{value}"
            work.mkdir()
            paths = _paths(work)
            argv = [str(ENGINE_PY), str(script), "--whitelist-db", str(paths["whitelist"]), "--subtitles-db", str(paths["subtitles"]), "run", "--lock", str(paths["lock"]), "--log", str(paths["log"]), "--stall-seconds", value]
            try:
                result = subprocess.run(argv, capture_output=True, text=True, timeout=8, cwd=work, env=env)
                out.append(f"{name} {value!r} {result.returncode} {result.stderr.splitlines()[-1:]!r} {sorted(p.name for p in work.iterdir())}")
            except subprocess.TimeoutExpired:
                out.append(f"{name} {value!r} TIMEOUT {sorted(p.name for p in work.iterdir())}")
        spec = importlib.util.spec_from_file_location(f"tw_{name}", script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        monkeypatch.setattr(sys, "argv", [str(script), "run"])
        default = module.parse_args().stall_seconds
        monkeypatch.setattr(sys, "argv", [str(script), "run", "--stall-seconds", "1"])
        one = module.parse_args().stall_seconds
        out.append(f"{name} default {default!r} == 600 {default == 600} == STALL_SECONDS {default == module.STALL_SECONDS}; one {one!r}")
    raise AssertionError("\n".join(out))
