"""Probe: what the checkpoint's `_layout` reports on the real worker and on mutants placing the trending call right and wrong."""
import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location("phase3_layout_copy", Path(__file__).with_name("test_45_trending_from_source_instances_phase3.py"))
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

SOURCE = _mod.UPDATER.read_text(encoding="utf-8")
AFTER_TRY = "            # The Engine serves again from here"
IN_FINALLY = "                        service_stopped = False\n"
AFTER_STAGE = "                fail_gate=args.fail_similarity_gate,\n            )\n"
INLINE = '            run_cmd([args.python_bin, (script_dir / "fetch-trending.py").as_posix(), "--db", prod_db.as_posix()], cwd=repo_root)\n'
VARIABLE = '            trending_script = script_dir / "fetch-trending.py"\n            trending_cmd = [args.python_bin, trending_script.as_posix()]\n            run_cmd(trending_cmd, cwd=repo_root)\n'


def _indent(text: str, by: int) -> str:
    return "".join(" " * by + line + "\n" for line in text.splitlines())


def test_probe():
    assert SOURCE.count(AFTER_TRY) == 1 and SOURCE.count(IN_FINALLY) == 1 and SOURCE.count(AFTER_STAGE) == 1
    variants = {
        "current": SOURCE,
        "right-inline": SOURCE.replace(AFTER_TRY, INLINE + AFTER_TRY),
        "right-variable": SOURCE.replace(AFTER_TRY, VARIABLE + AFTER_TRY),
        "in-finally": SOURCE.replace(IN_FINALLY, IN_FINALLY + _indent(INLINE, 12)),
        "after-stage": SOURCE.replace(AFTER_STAGE, AFTER_STAGE + INLINE),
    }
    for name, text in variants.items():
        service_trys, stage_calls, trending_calls = _mod._layout(text)
        ok = len(service_trys) == 1 and len(stage_calls) == 1 and len(trending_calls) == 1 and service_trys[0] < trending_calls[0] < stage_calls[0]
        print("LAYOUT", name, service_trys, stage_calls, trending_calls, "PASS" if ok else "FAIL")
    assert False
