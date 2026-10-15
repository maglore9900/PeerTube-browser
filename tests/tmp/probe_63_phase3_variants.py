"""Probe: the phase-3 checkpoint against the plan's implementation and three wrong ones, built as source rewrites of the current updater."""
import importlib.util
import subprocess
import sys
import types
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location("phase3_checkpoint", Path(__file__).with_name("test_63_catalog_update_weekly_increments_phase3.py"))
t = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(t)

SRC = (t.JOBS_DIR / "updater-worker.py").read_text(encoding="utf-8")

LOCALS_OLD = "    selected_group: int | None = None\n"
LOCALS_NEW = "    selected_group: int | None = None\n    pointer_settled = False\n    pointer_error: OSError | None = None\n"
OUTER_OLD = "    finally:\n        for temp_path in temp_files:"
OUTER_NEW = "    except Exception as exc:\n        if selected_group is not None and {cond}:\n            logging.error(\"pointer not advanced: %s\", exc)\n        raise\n    finally:\n        for temp_path in temp_files:"
WRITE_OLD = "                if args.increments >= 1:\n                    write_increment_pointer(increment_state, selected_group, args.increments)\n"
WRITE_NEW = "                if args.increments >= 1:\n                    try:\n                        write_increment_pointer(increment_state, selected_group, args.increments)\n                    except OSError as exc:\n                        logging.error(\"pointer not advanced: write failed: %s\", exc)\n                        {held}\n                    pointer_settled = True\n"
HELD_OLD = "                raise RuntimeError(\"trending stage failed\") from trending_error\n"
HELD_NEW = HELD_OLD + "            if pointer_error is not None:\n                raise RuntimeError(f\"increment pointer not advanced: {pointer_error}\") from pointer_error\n"


def _variant(name):
    src = SRC.replace(LOCALS_OLD, LOCALS_NEW).replace(HELD_OLD, HELD_NEW)
    cond = "not pointer_settled" if name != "double-log" else "True"
    held = {"correct": "pointer_error = exc", "double-log": "pointer_error = exc", "swallow": "pass", "propagate": "raise"}.get(name)
    held = "pointer_error = exc" if name in ("unguarded", "read-early") else held
    cond = "not pointer_settled" if name == "read-early" else cond
    outer = OUTER_NEW.format(cond=cond)
    if name == "unguarded":
        outer = outer.replace("selected_group is not None and ", "args.increments >= 1 and ")
    src = src.replace(OUTER_OLD, outer).replace(WRITE_OLD, WRITE_NEW.format(held=held))
    assert src.count("pointer_settled = True") == 1 and "except Exception as exc:\n        if " in src
    if name == "read-early":
        block = "            if args.increments >= 1:\n                selected_group, pointer_read = read_increment_pointer(increment_state, args.increments)\n                logging.info(\n                    \"increment read n=%d pointer=%s group=%d state=%s\",\n                    args.increments,\n                    pointer_read,\n                    selected_group,\n                    increment_state,\n                )\n"
        assert src.count(block) == 1
        early = "".join(line[4:] + "\n" for line in block.splitlines())
        src = src.replace(block, "").replace("    try:\n        with single_run_lock(lock_file):\n", "    try:\n" + early + "        with single_run_lock(lock_file):\n", 1)
        assert src.index("read_increment_pointer(increment_state, args.increments)") < src.index("with single_run_lock(lock_file):")
    module = types.ModuleType(f"probe_updater_{name}")
    module.__file__ = (t.JOBS_DIR / "updater-worker.py").as_posix()
    exec(compile(src, module.__file__, "exec"), module.__dict__)
    return module


@pytest.fixture(params=["correct", "double-log", "swallow", "propagate", "unguarded", "read-early"])
def updater(request):
    return _variant(request.param)


test_a_run_failing_before_the_merge_commits_logs_one_pointer_not_advanced_line_with_the_reason = t.test_a_run_failing_before_the_merge_commits_logs_one_pointer_not_advanced_line_with_the_reason
test_a_run_refused_by_the_run_lock_logs_no_pointer_not_advanced_line = t.test_a_run_refused_by_the_run_lock_logs_no_pointer_not_advanced_line
test_a_completed_run_logs_worker_completed_and_no_pointer_not_advanced_line = t.test_a_completed_run_logs_worker_completed_and_no_pointer_not_advanced_line
test_a_failed_pointer_write_runs_ann_trending_and_similarity_then_fails_the_run = t.test_a_failed_pointer_write_runs_ann_trending_and_similarity_then_fails_the_run


def test_called_process_error_text():
    print("CPE", str(subprocess.CalledProcessError(1, ["/opt/updater-python", "merge-staging-db.py"])))
