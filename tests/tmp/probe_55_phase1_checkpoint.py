"""Probe: run the checkpoint's own test bodies against the plan's draft fixture and against mutants of it, by exec'ing the checkpoint source with CONTRACT pointed at a tmp copy."""
import copy
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLAN = HERE.parents[1] / "docs" / "project" / "plans" / "01-55-translate-state-contract.md"
CHECKPOINT = HERE / "test_55_translate_state_contract_phase1.py"


def _draft():
    block = re.search(r"### 1\. `tests/active/fixtures/translate_contract.json`.*?```json\n(.*?)```", PLAN.read_text(), re.S).group(1)
    return json.loads(block)


def _run(tmp_path, label, fixture, only=()):
    path = tmp_path / f"{label}.json"
    path.write_text(json.dumps(fixture))
    source = CHECKPOINT.read_text().replace('Path(__file__).resolve().parents[1] / "active" / "fixtures" / "translate_contract.json"', repr(str(path)).join(("Path(", ")")))
    ns = {"__file__": str(CHECKPOINT), "__name__": "cp"}
    exec(compile(source, str(CHECKPOINT), "exec"), ns)
    failures = []
    for case in [c for c in ns["CASES"] if c["name"] in only]:
        try:
            ns["test_each_contract_case_parses_through_the_real_gateway_to_its_stated_answer_from_one_request_to_its_route"](case)
        except BaseException as exc:  # noqa: BLE001
            failures.append((case["name"], type(exc).__name__, str(exc).splitlines()[0][:160] if str(exc) else ""))
    try:
        ns["test_the_contract_fixture_states_exactly_the_gateway_state_sets_with_and_without_available_under_unique_names"]()
        coverage = "pass"
    except BaseException as exc:  # noqa: BLE001
        coverage = f"{type(exc).__name__}: {(str(exc).splitlines() or [''])[0][:200]} at line {exc.__traceback__.tb_next.tb_lineno}"
    print(f"== {label}: replay failures {failures} | coverage {coverage}")


def test_probe(tmp_path):
    sys.path.insert(0, str(HERE.parent / "active"))
    draft = _draft()
    _run(tmp_path, "draft", draft, {"state start 1e999", "state running after 3", "enqueue route missing 404"})
    m = copy.deepcopy(draft)
    m["cases"].append(copy.deepcopy(m["cases"][0]))
    _run(tmp_path, "duplicate name", m)
    m = copy.deepcopy(draft)
    next(c for c in m["cases"] if c["name"] == "state none without available")["gateway"] = {"state": "none"}
    _run(tmp_path, "gateway missing available default", m, {"state none without available"})
    m = copy.deepcopy(draft)
    next(c for c in m["cases"] if c["name"] == "state ready")["gateway"] = "rejected"
    _run(tmp_path, "valid marked rejected", m, {"state ready"})
    m = copy.deepcopy(draft)
    m["cases"].append({**copy.deepcopy(m["cases"][16]), "name": "enqueue with after", "after": 2})
    _run(tmp_path, "after on enqueue", m, {"enqueue with after"})
    m = copy.deepcopy(draft)
    m["cases"] = [c for c in m["cases"] if c["gateway"] != "rejected" or c["route"] == "state"]
    _run(tmp_path, "no enqueue rejection", m)
    m = copy.deepcopy(draft)
    m["cases"] = [c for c in m["cases"] if c["name"] != "enqueue video not found"]
    _run(tmp_path, "enqueue not-found dropped", m)
