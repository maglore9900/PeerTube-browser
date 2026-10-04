"""Retired from `tests/active/test_internal_translate.py` in the harvest of builds 53 (source-instance fetch adapter) and 58.

`test_each_none_path_answers_none_and_stores_nothing` was replaced (REPLACES) by build 53's phase 2 checkpoint test, now `test_each_none_path_answers_none_stores_nothing_and_logs_each_failed_fetch_with_its_reason`. Its four cases are rows of that test's `NONE_CASES`, which adds a track over the cap by its Content-Length and a track redirected off the host, asserts every URL opened rather than only the first, and asserts the `[translate] instance fetch failed ... <reason>` line per failed fetch. Kept readable; the names it uses come from the active module and are not imported here, and the whole module is skipped.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.skip(reason="retired test, kept for reference")

# The table it ran over (it named active-module constants, so it is kept as text):
#
#     NONE_PATHS = {
#         "no en track": (FR_LISTING, TRACK.encode("utf-8")),
#         "track fails to parse": (EN_LISTING, b"WEBVTT\n\n00:01.00 --> 00:02.000\nTwo-digit milliseconds\n"),
#         "caption list fetch failed": (None, TRACK.encode("utf-8")),
#         "track fetch failed": (EN_LISTING, None),
#     }
#
# It was parametrized as @pytest.mark.parametrize("listing, track", NONE_PATHS.values(), ids=NONE_PATHS.keys()).


def test_each_none_path_answers_none_and_stores_nothing(tmp_path, whitelist, monkeypatch, listing, track):
    instance = RecordingInstance()  # noqa: F821
    instance.serve(PEER_VIDEO, listing, track)  # noqa: F821
    internal_translate = _handler_module(instance, monkeypatch)  # noqa: F821
    subtitles_path = tmp_path / "subtitles.db"
    assert _handle(internal_translate, _server(whitelist, subtitles_path), {"id": PEER_VIDEO[1], "host": HOST}) == NONE  # noqa: F821
    assert instance.fetched[0] == (HOST, f"/api/v1/videos/{PEER_VIDEO[1]}/captions")  # noqa: F821
    assert _stored(subtitles_path) == []  # noqa: F821
