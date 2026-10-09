"""Retired from `tests/active/test_frontend_translate.py` in build 57-56-translate-viewer-lease-uncapped (plan 57), step 8.

Retired whole: `test_a_none_state_without_a_serving_worker_sends_no_request_polls_nothing_and_reads_the_plan_48_message`, with the two `GENERATION_SCENARIOS` entries only it read (`"unavailable"` and its twin `"available"`) and its line in the module docstring.

It conflicts with that build's confirmed requirement AC6 (Phase 4, C2): a poll-path `none` with `available` while Translate is on requests generation again instead of ending the poll. The function's control `assert len(_translate_by_method(twin, "POST")) == 1` reads the `"available"` twin, whose stub serves `none` (with `available` true) to every GET because the last answer repeats. Before the build that `none` ended the poll after the one turn-on POST; under AC6 every poll answers it with a fresh POST, about every 2 s, so the twin sent 4 POSTs in its 6.5 s wait (step 8 suite comparison: `assert 4 == 1`). The control fails before the unavailable page's own assertions are reached.

Retired and not repointed: the plan's impact list proposed changing the twin's GETs to `[none, queued]`, which would edit an already-gated control to fit the new behaviour. What stays active elsewhere: a `none` without `available` at turn-on, asked once and reading "No English translation is available for this video.", in `test_a_none_state_reads_no_english_translation_and_a_reported_position_shows_nothing`; a turn-on `none` with `available` sending exactly one POST of `{id, host}` with the key, in `test_a_none_state_from_a_serving_worker_sends_one_generation_request_with_the_video_and_key_and_no_second_while_polled`; and a poll-path `none` without `available` sending no further POST, in Phase 4's `re-request-unavailable` checkpoint twin (`tests/tmp/test_56_translate_viewer_lease_uncapped_phase4.py`). What goes with it: the turn-on `none` without `available` checked against a twin differing only in the flag, and "no GET after the first" for that page.

The original code follows unchanged, as excerpts of the file as it stood. The helpers it calls (`_state`, `STOP_WAIT`, `_generation_page`, `_translate_by_method`, `_asked`, `NO_TRANSLATION`, the `generation_pages` fixture) stay in the active file.
"""
# --- excerpt: module docstring, line 19 ---
# - A `none` answer with `available` false sends no POST, no GET after the first, and reads "No English translation is available for this video.", although a POST would have been answered `queued`; the same scenario with only `available` true sends one POST.

# --- excerpt: GENERATION_SCENARIOS entries, lines 565-568 ---
GENERATION_SCENARIOS = {
    # a POST would be answered queued, so a page that requested anyway would also start polling
    "unavailable": {"gets": [_state("none", available=False)], "posts": [_state("queued")], "steps": [{"wait": STOP_WAIT}]},
    # the unavailable case with only `available` flipped, so its one POST shows this page reads the flag rather than never requesting
    "available": {"gets": [_state("none")], "posts": [_state("queued")], "steps": [{"wait": STOP_WAIT}]},
}

# --- excerpt: lines 641-650 ---

def test_a_none_state_without_a_serving_worker_sends_no_request_polls_nothing_and_reads_the_plan_48_message(generation_pages):
    page = _generation_page(generation_pages, "unavailable")
    twin = _generation_page(generation_pages, "available")
    last = page["snapshots"][-1]

    # control: the same stubs and steps with `available` true make this page send its POST, so the empty list below is the flag being read and not a page that never requests
    assert len(_translate_by_method(twin, "POST")) == 1, _asked(twin)
    assert _translate_by_method(page, "POST") == [], _asked(page)
    assert len(_translate_by_method(page, "GET")) == 1, _asked(page)
    assert last["status"] == NO_TRANSLATION, (last, _asked(page))
