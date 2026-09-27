"""Runs the phase 4 checkpoint against the current code and emulated caps: only a cap of exactly 50 should pass."""
from __future__ import annotations

import importlib.util
import traceback
from pathlib import Path

spec = importlib.util.spec_from_file_location("phase4", Path(__file__).with_name("test_14_batch_like_resolution_phase4.py"))
phase4 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(phase4)
srv = phase4.client_server

TESTS = [phase4.test_a_60_like_likes_page_reaches_the_engine_as_its_first_50_and_is_answered_with_their_rows, phase4.test_a_60_like_import_reaches_the_engine_as_its_first_50_and_likes_exactly_those, phase4.test_a_keyless_60_like_recommendations_request_forwards_its_first_50_likes]


def _run(test, tmp_path):
    tmp_path.mkdir()
    try:
        test(tmp_path)
        return "PASS"
    except AssertionError as exc:
        tb = exc.__traceback__
        while tb.tb_next is not None:
            tb = tb.tb_next
        return f"FAIL at line {tb.tb_lineno}: {str(exc)[:160]}"
    except Exception:
        return "ERROR " + traceback.format_exc()[-400:]


def test_emulated(tmp_path, monkeypatch):
    print("current MAX_CLIENT_LIKES =", srv.MAX_CLIENT_LIKES)
    for cap in (srv.MAX_CLIENT_LIKES, 50, 49, 51):
        monkeypatch.setattr(srv, "MAX_CLIENT_LIKES", cap)
        for test in TESTS:
            print(f"cap={cap} {test.__name__}:", _run(test, tmp_path / f"{cap}-{test.__name__}"))
    monkeypatch.setattr(srv, "MAX_CLIENT_LIKES", 50)
    real = srv._parse_client_likes
    print("real(body, 0) length:", len(real({"likes": phase4.LIKES}, 0)), "real(body, 10**6) length:", len(real({"likes": phase4.LIKES}, 10**6)))
    monkeypatch.setattr(srv, "_parse_client_likes", lambda body, n: real(body, 10**6)[-n:])
    for test in TESTS[:2]:
        print(f"last-50 {test.__name__}:", _run(test, tmp_path / f"last-{test.__name__}"))
    assert False, "print"
