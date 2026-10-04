import importlib
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_53_source_instance_fetch_adapter_phase2 as checkpoint  # noqa: E402

REAL = importlib.import_module("handlers.internal_translate")
SOURCE = Path(REAL.__file__).read_text()
MUTANTS = {
    "after ignored": ('"cues": cues[after:]', '"cues": cues'),
    "after unchecked": ('if isinstance(after, bool) or not isinstance(after, int) or after < 0:', 'if False:'),
    "beat ignored": ("if conn is not None and _generation_available(conn) else None", "if conn is not None else None"),
    "busy as queued": ('"busy" if kind == "cap" else state', 'state'),
    "503 body": ('{"error": "Translate store unavailable"}', '{"error": "unavailable"}'),
}
TESTS = ["test_each_bad_body_answers_its_400_with_nothing_opened", "test_a_running_row_answers_its_cues_from_after_with_the_stored_total_and_opens_nothing", "test_enqueue_without_a_serving_worker_answers_none_not_available_and_queues_and_opens_nothing", "test_enqueue_at_the_queue_cap_answers_busy_and_one_below_it_queues_opening_nothing", "test_a_store_error_from_the_enqueue_answers_503_and_queues_and_opens_nothing"]


@pytest.mark.parametrize("mutant", MUTANTS)
def test_mutant(mutant, monkeypatch):
    old, new = MUTANTS[mutant]
    assert SOURCE.count(old) == 1, old
    module = types.ModuleType("handlers.internal_translate")
    module.__file__ = REAL.__file__
    exec(compile(SOURCE.replace(old, new), REAL.__file__, "exec"), module.__dict__)
    monkeypatch.setitem(sys.modules, "handlers.internal_translate", module)
    print("MUTANT", mutant, "->", pytest.main([checkpoint.__file__, "-q", "-p", "no:cacheprovider", "--tb=line", "-k", " or ".join(TESTS)]))
