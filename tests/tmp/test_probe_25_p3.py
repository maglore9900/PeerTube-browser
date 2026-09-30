from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
UPDATER = ROOT / "engine" / "server" / "db" / "jobs" / "updater-worker.py"


def test_probe(tmp_path: Path) -> None:
    spec = importlib.util.spec_from_file_location("updater_worker_probe", UPDATER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    print("has builder:", hasattr(module, "similarity_precompute_cmd"))
    print("tmp_path str==posix:", str(tmp_path) == tmp_path.as_posix(), tmp_path.as_posix())
    gpu = ["python3", "s.py", "--db", "d", "--index", "i", "--out", "o", "--top-k", "1000", "--nprobe", "16", "--search-batch-size", "1024", "--refresh-existing", "--gpu", "--gpu-device", "0"]
    print("to_cpu:", module._to_cpu_cmd(gpu))
    tree = ast.parse(UPDATER.read_text(encoding="utf-8"))
    consts = [(n.lineno, n.value) for n in ast.walk(tree) if isinstance(n, ast.Constant) and n.value in ("--recreate-out-db", "--refresh-existing")]
    print("flag consts:", consts)
    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
    calls = sorted({n.func.id for n in ast.walk(main) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)})
    print("main calls:", calls)
    assert False
