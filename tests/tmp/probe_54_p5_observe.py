"""Probe: what the plan's draft and today's page show, phase by phase, for the checkpoint's scenarios and the planned popstate one. The report is the failure message."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("p5_draft_probe", HERE / "probe_54_p5_draft.py")
dp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dp)
cp = dp.cp
A = cp._answer

SCENARIOS = {
    "load-tag": ("?tag=Linux", [A("linux", 2, 5)], []),
    "sort": ("?tag=Linux&sort=popularity", [A("popular", 2, 5), A("viewed", 3, 7), A("newest", 0, 0)], [{"sort": "views"}, {"sort": "published_at"}]),
    "back": ("?q=music", [A("music", 2, 9), A("linux", 4, 6)], [{"popstate": "/search.html?tag=Linux&sort=views"}, {"popstate": "/search.html"}]),
    "new-popstate": ("?tag=Linux", [A("linux", 2, 5), A("abc", 1, 3), A("abcviewed", 2, 3), A("music", 3, 8)],
                     [{"popstate": "/search.html?tag=a+b%26c"}, {"sort": "views"}, {"popstate": "/search.html?q=music&tag=Linux"}]),
}


def _dump(page: Path) -> list[str]:
    lines = []
    for name, (search, answers, steps) in SCENARIOS.items():
        report = cp._run(page, search, answers, steps)
        lines.append(f"-- {name}: errors={report['errors']} missing={report['missing']}")
        lines.extend("   " + json.dumps(phase) for phase in report["phases"])
    return lines


def test_observe(tmp_path):
    lines = ["DRAFT"]
    out = tmp_path / "draft_out"
    out.mkdir()
    lines += _dump(cp._prepare(dp._tree(tmp_path / "draft", {}), out))
    lines.append("TODAY")
    today = tmp_path / "today_out"
    today.mkdir()
    lines += _dump(cp._prepare(cp.FRONTEND, today))
    pytest.fail("\n".join(lines))
