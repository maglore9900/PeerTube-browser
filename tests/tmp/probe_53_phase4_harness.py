"""Probe: run the phase 4 checkpoint's own test functions against the plan's fetch_host_list and against plausible wrong versions, to observe which assertions each one trips."""
from __future__ import annotations

import json
import logging
import sys
import traceback
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))

import test_53_source_instance_fetch_adapter_phase4 as cp  # noqa: E402
from test_fetch_trending import _load_job  # noqa: E402

from data.source_fetch import SourceFetchFailed, fetch_bounded  # noqa: E402

TRENDING_PATH = "/api/v1/videos?sort=-trending&isLocal=true&count=100&nsfw=both"


def _variant(cap_holder, no_retry_on_fetch_failure=False, **overrides):
    def fetch_host_list(host, timeout_s, max_retries):
        kwargs = {"max_bytes": cap_holder.TRENDING_MAX_BYTES, "deadline_seconds": timeout_s, "socket_timeout": timeout_s, "headers": {"User-Agent": "peertube-browser-trending/1.0"}}
        for key, value in overrides.items():
            if value is None:
                kwargs.pop(key)
            else:
                kwargs[key] = value
        for attempt in range(max_retries + 1):
            try:
                body = json.loads(fetch_bounded(host, TRENDING_PATH, **kwargs))
                data = body.get("data") if isinstance(body, dict) else None
                if not isinstance(data, list):
                    raise ValueError("body has no data list")
                return data
            except (SourceFetchFailed, ValueError) as exc:
                logging.debug("attempt %d failed: %s", attempt + 1, exc)
                if no_retry_on_fetch_failure and isinstance(exc, SourceFetchFailed):
                    return None
        return None
    return fetch_host_list


CASES = [
    ("base", lambda job: cp.test_fetch_host_list_reads_the_trending_page_through_the_adapter),
    *[(f"fail-{name}", (lambda failure: lambda job: (lambda job_, mp: cp.test_fetch_host_list_returns_none_after_max_retries_plus_one_failed_attempts(job_, mp, failure)))(failure)) for name, failure in cp.FAILURES.items()],
    ("no-retries", lambda job: cp.test_fetch_host_list_with_no_retries_makes_one_attempt),
    ("retry-ok", lambda job: cp.test_fetch_host_list_returns_the_list_when_a_retry_succeeds),
    ("redirect", lambda job: cp.test_an_off_host_redirect_fails_every_attempt_and_its_target_is_never_opened),
    ("cap", lambda job: cp.test_a_body_one_byte_over_trending_max_bytes_fails_every_attempt),
    ("deadline", lambda job: cp.test_an_attempt_whose_clock_passes_timeout_s_fails_on_the_deadline_and_is_retried),
]

VARIANTS = {
    "right": {},
    "no-max-bytes": {"max_bytes": None},
    "no-deadline": {"deadline_seconds": None},
    "no-user-agent": {"headers": None},
    "no-socket-timeout": {"socket_timeout": None},
    "no-retry-on-fetch-failure": {"no_retry_on_fetch_failure": True},
}


@pytest.mark.parametrize("cap", [500_000])
def test_probe(cap):
    job = _load_job("probe_fetch_trending_job", "fetch-trending.py")
    for variant, overrides in VARIANTS.items():
        for name, make in CASES:
            with pytest.MonkeyPatch.context() as mp:
                mp.setattr(job, "TRENDING_MAX_BYTES", cap, raising=False)
                mp.setattr(job, "fetch_host_list", _variant(job, **overrides))
                try:
                    make(job)(job, mp)
                    outcome = "PASS"
                except AssertionError as exc:
                    tb = traceback.extract_tb(exc.__traceback__)
                    line = next((frame.lineno for frame in reversed(tb) if frame.filename.endswith("phase4.py")), None)
                    outcome = f"FAIL line {line}: {str(exc).splitlines()[0][:160]}"
                except Exception as exc:  # noqa: BLE001
                    outcome = f"ERROR {type(exc).__name__}: {exc}"
            print(f"cap={cap} {variant:18} {name:22} {outcome}")
    assert False, "probe output above"
