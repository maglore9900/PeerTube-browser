"""Probe: run the phase 4 checkpoint's scenarios against the unchanged page, a sketch of the planned page, and wrong variants of it; print what each test reads."""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_56_translate_viewer_lease_uncapped_phase4 as cp  # noqa: E402

SRC = cp.FRONTEND / "src"
EDITS = [
    ('import { compareCues, fetchTranslate, readTranslate, requestTranslate,', 'import { cancelTranslate, compareCues, fetchTranslate, readTranslate, requestTranslate,'),
    ('let runningHeld = 0;\n', 'let runningHeld = 0;\nlet inFlight: Promise<unknown> = Promise.resolve();\nfunction track<T>(p: Promise<T>): Promise<T> { inFlight = p.catch(() => undefined); return p; }\n'),
    ('    if (on) turnOff();', '    if (on) turnOff(apiBase, video);'),
    ('    const state = await fetchTranslate(apiBase, video.id, video.host);', '    const state = await track(fetchTranslate(apiBase, video.id, video.host));'),
    ('      const requested = await requestTranslate(apiBase, video.id, video.host);', '      const requested = await track(requestTranslate(apiBase, video.id, video.host));'),
    ('function turnOff() {', 'function turnOff(apiBase: string, video: TranslateVideo) {'),
    ('  showText("");\n}\n\nfunction applyRequest', '  showText("");\n  CANCEL_HOOK\n}\n\nfunction applyRequest'),
    ('        if (ticket === requestTicket) applyState(state, apiBase, video, ticket);\n      },', '        if (ticket === requestTicket) applyState(state, apiBase, video, ticket);\n        STALE_HOOK\n      },'),
    ('    fetchTranslate(apiBase, video.id, video.host, runningHeld).then(', '    track(fetchTranslate(apiBase, video.id, video.host, runningHeld)).then('),
    ('  } else {\n    // none, already_english', '  } else if (state.state === "none" && AVAILABLE_TEST && on) {\n    dropRunning();\n    setStatus(NONE_STATUS);\n    stateDelay = Math.min(stateDelay * 2, STATE_POLL_MAX_MS);\n    track(requestTranslate(apiBase, video.id, video.host)).then((r) => { if (ticket === requestTicket) REREQ_THEN; }, (e: unknown) => { if (ticket === requestTicket) setStatus(e instanceof Error ? e.message : "x"); });\n    return;\n  } else {\n    // none, already_english'),
]
GOOD_CANCEL = 'inFlight.then(() => cancelTranslate(apiBase, video.id, video.host)).catch(() => undefined);'
VARIANTS = {
    "planned": {"CANCEL_HOOK": GOOD_CANCEL, "AVAILABLE_TEST": "state.available"},
    "cancel at click": {"CANCEL_HOOK": 'cancelTranslate(apiBase, video.id, video.host).catch(() => undefined);', "AVAILABLE_TEST": "state.available"},
    "two cancels": {"CANCEL_HOOK": GOOD_CANCEL + GOOD_CANCEL, "AVAILABLE_TEST": "state.available"},
    "no catch": {"CANCEL_HOOK": 'void inFlight.then(() => cancelTranslate(apiBase, video.id, video.host));', "AVAILABLE_TEST": "state.available"},
    "re-request ignoring available": {"CANCEL_HOOK": GOOD_CANCEL, "AVAILABLE_TEST": "true"},
    "cancel only from a stale poll": {"CANCEL_HOOK": "", "AVAILABLE_TEST": "state.available", "STALE_HOOK": "else if (!on) cancelTranslate(apiBase, video.id, video.host).catch(() => undefined);"},
    "cancel on a fixed delay": {"CANCEL_HOOK": "setTimeout(() => { cancelTranslate(apiBase, video.id, video.host).catch(() => undefined); }, 1800);", "AVAILABLE_TEST": "state.available"},
    "re-request answer not applied": {"CANCEL_HOOK": GOOD_CANCEL, "AVAILABLE_TEST": "state.available", "NONE_STATUS": "ENDED_LABELS.none", "REREQ_THEN": "scheduleStatePoll(apiBase, video, ticket, stateDelay)"},
    "re-request once per page": {"CANCEL_HOOK": GOOD_CANCEL, "AVAILABLE_TEST": "state.available && !(globalThis as any).__rr && ((globalThis as any).__rr = true)"},
}


def _variant_src(out: Path, fills: dict) -> Path:
    src = out / "src"
    shutil.copytree(SRC, src)
    page = src / "pages" / "video-page" / "translate.ts"
    text = page.read_text()
    for old, new in EDITS:
        assert text.count(old) == 1, old
        text = text.replace(old, new)
    for hole, fill in {"STALE_HOOK": "", "NONE_STATUS": "WAITING", "REREQ_THEN": "applyRequest(r, apiBase, video, ticket)", **fills}.items():
        text = text.replace(hole, fill)
    page.write_text(text)
    return src


def _check(pages: dict) -> dict:
    out = {}
    for name, fn in (("C1 held", cp.test_turning_translate_off_during_a_held_poll_sends_one_cancel_with_the_video_and_key_only_after_that_poll_answered),
                     ("C1 idle", cp.test_turning_translate_off_between_polls_sends_one_cancel_with_the_video_and_key_at_once),
                     ("C2", cp.test_a_poll_reading_none_from_a_serving_worker_requests_generation_again_each_time_with_the_video_and_key_and_shows_waiting_and_one_without_does_not)):
        try:
            fn(pages)
            out[name] = "PASS"
        except Exception as error:
            out[name] = f"FAIL {type(error).__name__} line {error.__traceback__.tb_next.tb_lineno if error.__traceback__.tb_next else '?'} " + (str(error).splitlines() or [""])[0][:400]
    return out


@pytest.mark.parametrize("variant", ["unchanged", *VARIANTS])
def test_probe(tmp_path, variant):
    src = SRC if variant == "unchanged" else _variant_src(tmp_path, VARIANTS[variant])
    pages = cp._run(cp._bundle(tmp_path, src))
    if variant in ("unchanged", "planned"):
        for name, scenario in pages.items():
            page = json.loads(scenario[1].splitlines()[-1])
            print(variant.upper(), name, json.dumps({"steps": page["steps"], "asked": cp._asked(page), "last": page["snapshots"][-1], "snap2": page["snapshots"][2], "click": page["snapshots"][3] if len(page["snapshots"]) > 3 else None}))
    print("RESULT", variant, json.dumps(_check(pages)))
    pytest.fail("probe output above")
