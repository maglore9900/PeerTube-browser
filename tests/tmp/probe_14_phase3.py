"""Runs the phase 3 checkpoint against emulated implementations: the correct one should pass, each wrong one should fail on a C2 line."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("phase3", Path(__file__).with_name("test_14_batch_like_resolution_phase3.py"))
phase3 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(phase3)
srv = phase3.client_server


def _run(test, tmp_path):
    tmp_path.mkdir()
    try:
        test(tmp_path)
        return "PASS"
    except AssertionError as exc:
        tb = exc.__traceback__
        while tb.tb_next is not None:
            tb = tb.tb_next
        return f"FAIL at line {tb.tb_lineno}"


def test_emulated(tmp_path, monkeypatch):
    # New behaviour: the likes page sends the parsed likes straight to metadata; import records from metadata rows.
    monkeypatch.setattr(srv, "resolve_videos_by_uuid_host", lambda base, likes: likes)
    print("PAGE correct:", _run(phase3.test_a_likes_page_is_one_metadata_call_answered_with_the_known_rows_in_submitted_order, tmp_path / "p"))
    print("EMPTY correct:", _run(phase3.test_a_likes_page_with_no_well_formed_like_is_answered_empty_without_the_engine, tmp_path / "e"))
    monkeypatch.setattr(srv, "resolve_videos_by_uuid_host", srv.fetch_metadata_for_entries)
    print("IMPORT correct:", _run(phase3.test_an_import_is_one_metadata_call_and_likes_each_returned_video_the_profile_has_not_disliked, tmp_path / "i1"))
    monkeypatch.setattr(srv, "is_disliked", lambda *a: False)
    print("IMPORT ignores dislikes:", _run(phase3.test_an_import_is_one_metadata_call_and_likes_each_returned_video_the_profile_has_not_disliked, tmp_path / "i2"))
    monkeypatch.undo()
    monkeypatch.setattr(srv, "resolve_videos_by_uuid_host", lambda base, likes: [{"video_id": r["video_uuid"], "video_uuid": r["video_uuid"], "instance_domain": r["instance_domain"]} for r in srv.fetch_metadata_for_entries(base, likes)])
    print("IMPORT keys on entry uuid:", _run(phase3.test_an_import_is_one_metadata_call_and_likes_each_returned_video_the_profile_has_not_disliked, tmp_path / "i3"))
    monkeypatch.setattr(srv, "resolve_videos_by_uuid_host", lambda base, likes: srv.fetch_metadata_for_entries(base, likes)[1:])
    print("IMPORT skips first row:", _run(phase3.test_an_import_is_one_metadata_call_and_likes_each_returned_video_the_profile_has_not_disliked, tmp_path / "i4"))
    monkeypatch.setattr(srv, "resolve_videos_by_uuid_host", lambda base, likes: srv.fetch_metadata_for_entries(base, likes)[:-1])
    print("IMPORT skips last row:", _run(phase3.test_an_import_is_one_metadata_call_and_likes_each_returned_video_the_profile_has_not_disliked, tmp_path / "i5"))
    monkeypatch.setattr(srv, "resolve_videos_by_uuid_host", lambda base, likes: [{k: v for k, v in r.items() if k != "video_uuid"} for r in srv.fetch_metadata_for_entries(base, likes)])
    print("IMPORT drops uuid:", _run(phase3.test_an_import_is_one_metadata_call_and_likes_each_returned_video_the_profile_has_not_disliked, tmp_path / "i6"))
