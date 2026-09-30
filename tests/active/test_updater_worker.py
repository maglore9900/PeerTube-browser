"""`updater-worker.py` builds its similarity precompute argv with `--refresh-existing` and never `--recreate-out-db`, and its CPU retry keeps that flag.

- `similarity_precompute_cmd` returns, token for token, the precompute argv with `--refresh-existing` after `--search-batch-size 1024`, ending in `--gpu --gpu-device 0` or `--cpu`, and without `--recreate-out-db`.
- `_to_cpu_cmd` turns the GPU argv into exactly the CPU argv, `--refresh-existing` included.
- `main` calls `similarity_precompute_cmd`, and no `--recreate-out-db` literal is left anywhere in the module.

The module is loaded in-process from its file, the way `test_host_normalisation._load_job` does.
"""
from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

import pytest
from conftest import ROOT

JOBS_DIR = ROOT / "engine" / "server" / "db" / "jobs"
UPDATER = JOBS_DIR / "updater-worker.py"


def _load_job(module_name: str, filename: str):
    spec = importlib.util.spec_from_file_location(module_name, JOBS_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def updater():
    return _load_job("updater_worker_precompute", "updater-worker.py")


def _paths(tmp_path: Path) -> dict[str, Path]:
    # Four distinct paths, so a builder that swaps two of them fails the exact comparison.
    return {"script_path": tmp_path / "jobs" / "precompute-similar-ann.py", "db_path": tmp_path / "prod.db", "index_path": tmp_path / "ann.faiss", "out_path": tmp_path / "similarity-cache.db"}


@pytest.mark.parametrize(("use_gpu", "suffix"), [(True, ["--gpu", "--gpu-device", "0"]), (False, ["--cpu"])], ids=["gpu", "cpu"])
def test_updater_builds_refresh_command(updater, tmp_path: Path, use_gpu: bool, suffix: list[str]) -> None:
    """The builder's argv is the precompute command token for token, with `--refresh-existing` and never `--recreate-out-db`, and the accelerator suffix for `use_gpu`."""
    cmd = updater.similarity_precompute_cmd(python_bin="python3", use_gpu=use_gpu, **_paths(tmp_path))

    assert cmd == ["python3", f"{tmp_path}/jobs/precompute-similar-ann.py", "--db", f"{tmp_path}/prod.db", "--index", f"{tmp_path}/ann.faiss", "--out", f"{tmp_path}/similarity-cache.db", "--top-k", "1000", "--nprobe", "16", "--search-batch-size", "1024", "--refresh-existing", *suffix]
    assert "--recreate-out-db" not in cmd


def test_cpu_fallback_keeps_refresh(updater, tmp_path: Path) -> None:
    """`_to_cpu_cmd` over the GPU argv gives exactly the CPU argv, `--refresh-existing` still in its slot."""
    gpu_cmd = updater.similarity_precompute_cmd(python_bin="python3", use_gpu=True, **_paths(tmp_path))
    # `run_with_cpu_fallback` retries only a command carrying `--gpu`; without it the retry below is never taken.
    assert gpu_cmd[-3:] == ["--gpu", "--gpu-device", "0"], gpu_cmd

    assert updater._to_cpu_cmd(gpu_cmd) == ["python3", f"{tmp_path}/jobs/precompute-similar-ann.py", "--db", f"{tmp_path}/prod.db", "--index", f"{tmp_path}/ann.faiss", "--out", f"{tmp_path}/similarity-cache.db", "--top-k", "1000", "--nprobe", "16", "--search-batch-size", "1024", "--refresh-existing", "--cpu"]


def test_updater_main_uses_builder() -> None:
    """`main` calls `similarity_precompute_cmd`, and the module holds no `--recreate-out-db` string literal."""
    # rat-tail: a source scan, because reaching the precompute stage through `main` means running the whole crawl/merge/ANN pipeline; a pipeline harness with the stage commands shimmed would replace it.
    tree = ast.parse(UPDATER.read_text(encoding="utf-8"))
    main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main")
    called = {node.func.id for node in ast.walk(main) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}

    assert "similarity_precompute_cmd" in called, sorted(called)
    constants = {node.value for node in ast.walk(tree) if isinstance(node, ast.Constant)}
    # `_to_cpu_cmd` matches the `--gpu-device` literal, so the scan below is shown to see the module's string constants.
    assert "--gpu-device" in constants
    assert "--recreate-out-db" not in constants
