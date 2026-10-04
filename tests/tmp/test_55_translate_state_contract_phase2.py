"""Phase 2 checkpoint of plan 55: the replay runner phase 2 adds to tests/active/test_frontend_translate.py (`CONTRACT_RUNNER`), run over the real client/frontend/src/data/translate.ts bundled on its own, shows translate.ts agreeing with every case of tests/active/fixtures/translate_contract.json.

The runner is the durable module's own, as the plan writes it: the test hands it the fixture path, base, bundle and host in the CONTRACT, BASE, BUNDLE and HOST environment variables (which of them it reads is not asserted here), and it serves each case as a 200 to `fetchTranslate` (state route, with the case's `after`) or `requestTranslate` (enqueue route), the gateway answer for a valid case and the Engine body for a rejected one, and prints one JSON report keyed by case name of `{value | thrown, nonFinite}`. `FETCH_RECORDER`, put ahead of it, wraps whatever `fetch` the runner installs and writes every request to the ASKED file when node exits. While test_frontend_translate.py has no `CONTRACT_RUNNER`, every case fails on its absence.

- Valid (C1): the returned value deep-equals the gateway answer, with ready cues sorted by (start, end) and running cues in the order given; the fixture's ready and running lists are themselves out of that order, so an unsorted or a wrongly sorted list reads differently.
- Rejected (C2): the call threw exactly "Translate response was malformed", so a JSON SyntaxError or a gateway error text cannot pass as the parser's refusal.
- Controls on every case: the runner made one request per case, and this case's was a GET of /api/translate carrying the case's `after` for a state case and a POST for an enqueue case; and the served text parsed to a non-finite number exactly where Python's reading of the fixture finds one (its `1e999`).
"""
from __future__ import annotations

import json
import math
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))

import test_frontend_translate as durable  # noqa: E402

CONTRACT = Path(__file__).resolve().parents[1] / "active" / "fixtures" / "translate_contract.json"
CASES = json.loads(CONTRACT.read_text())["cases"]
VALID = [case for case in CASES if case["gateway"] != "rejected"]
REJECTED = [case for case in CASES if case["gateway"] == "rejected"]
MALFORMED = "Translate response was malformed"
# Both ready cases carry the same three cues; this is their (start, end) order written down, as observed from the real translate.ts.
READY_CUES = [{"start": 1.0, "end": 2.0, "text": "Short first"}, {"start": 1.0, "end": 3.0, "text": "Long first"}, {"start": 4.0, "end": 5.0, "text": "Later"}]

# ES imports are hoisted, so the runner's own imports still resolve; the setter catches the runner's `globalThis.fetch = ...` and the getter hands translate.ts a recording wrapper around it.
FETCH_RECORDER = """
import { writeFileSync as recordAsked } from "node:fs";
const askedLog = [];
let innerFetch = null;
Object.defineProperty(globalThis, "fetch", { configurable: true, get() { return async (input, init) => {
  const url = new URL(String(input?.url ?? input), process.env.BASE);
  askedLog.push({ method: String(init?.method ?? input?.method ?? "GET").toUpperCase(), path: url.pathname, after: url.searchParams.get("after") });
  return innerFetch(input, init);
}; }, set(f) { innerFetch = f; } });
process.on("exit", () => recordAsked(process.env.ASKED, JSON.stringify(askedLog)));
"""


def _contract_report(out: Path, source: Path, runner: str) -> dict:
    subprocess.run(
        [str(durable.ESBUILD), str(source), "--bundle", "--format=esm", "--platform=node", f"--outfile={out / 'bundle.mjs'}",
         f"--define:import.meta.env.VITE_CLIENT_API_BASE={json.dumps(durable.BASE)}",
         "--define:import.meta.env.DEV=false"],
        check=True, capture_output=True,
    )
    (out / "runner.mjs").write_text(FETCH_RECORDER + runner)
    proc = subprocess.run(
        ["node", str(out / "runner.mjs")], capture_output=True, text=True, timeout=60,
        env={"BASE": durable.BASE, "BUNDLE": str(out / "bundle.mjs"), "CONTRACT": str(CONTRACT), "HOST": durable.HOST, "ASKED": str(out / "asked.json"), "PATH": os.environ.get("PATH", "")},
    )
    assert proc.returncode == 0, proc.stderr
    return {"report": json.loads(proc.stdout.splitlines()[-1]), "asked": json.loads((out / "asked.json").read_text())}


@pytest.fixture(scope="module")
def contract_report(tmp_path_factory) -> dict | None:
    runner = getattr(durable, "CONTRACT_RUNNER", None)
    return None if runner is None else _contract_report(tmp_path_factory.mktemp("translate_contract"), durable.FRONTEND / "src" / "data" / "translate.ts", runner)


def _has_non_finite(value) -> bool:
    if isinstance(value, float):
        return not math.isfinite(value)
    if isinstance(value, dict):
        return any(_has_non_finite(v) for v in value.values())
    return isinstance(value, list) and any(_has_non_finite(v) for v in value)


def _by_start_then_end(cues: list[dict]) -> list[dict]:
    return sorted(cues, key=lambda cue: (cue["start"], cue["end"]))


def _result(contract_report: dict | None, case: dict, served: dict) -> dict:
    assert contract_report is not None, "tests/active/test_frontend_translate.py has no CONTRACT_RUNNER: the phase's replay runner is not written yet"
    result = contract_report["report"][case["name"]]
    asked = contract_report["asked"]
    # Control: one request per case, so request i is case i's; this case's reached its route's parser, a GET with the case's after for the state route and a POST for the enqueue route.
    assert len(asked) == len(CASES), asked
    assert asked[CASES.index(case)] == {"method": "GET" if case["route"] == "state" else "POST", "path": "/api/translate", "after": str(case["after"]) if "after" in case else None}, asked
    # Control: the parser read a non-finite number exactly where Python's reading of the fixture finds one (its 1e999), so that case is refused for infinity and not for a null.
    assert result["nonFinite"] == _has_non_finite(served), result
    return result


@pytest.mark.parametrize("case", VALID, ids=[case["name"] for case in VALID])
def test_each_valid_contract_case_comes_back_with_exactly_its_gateway_fields_ready_cues_sorted_by_start_then_end_running_in_given_order(contract_report, case):
    expected = case["gateway"]
    result = _result(contract_report, case, expected)
    if "cues" in expected:
        # Control: the fixture's list is out of (start, end) order, so a parser that leaves ready unsorted, or sorts running, reads differently below.
        assert _by_start_then_end(expected["cues"]) != expected["cues"], case["name"]
    if expected["state"] == "ready" and "cues" in expected:
        expected = {**expected, "cues": READY_CUES}
    assert result.get("value") == expected, result  # C1


@pytest.mark.parametrize("case", REJECTED, ids=[case["name"] for case in REJECTED])
def test_each_rejected_contract_case_served_as_a_200_throws_exactly_translate_response_was_malformed(contract_report, case):
    result = _result(contract_report, case, case["engine"]["body"])
    assert result.get("thrown") == MALFORMED, result  # C2
