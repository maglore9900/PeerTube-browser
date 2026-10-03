"""Probe: run the checkpoint's in-process tests against the plan's draft job, to see whether its controls arm and its expectations hold under a plausible implementation. Deleted after the probe."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("checkpoint_draft", HERE / "test_45_trending_from_source_instances_phase1.py")
cp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cp)
dspec = importlib.util.spec_from_file_location("draft_job", HERE / "draft_fetch_trending.py")
draft = importlib.util.module_from_spec(dspec)
dspec.loader.exec_module(draft)

import data.moderation as moderation  # noqa: E402


def test_run_replaces(tmp_path, monkeypatch):
    cp.test_a_run_asks_only_undenied_embedded_hosts_and_replaces_each_answered_host_s_rows_with_its_list(draft, tmp_path, monkeypatch)


def test_ten_days(tmp_path, monkeypatch):
    cp.test_a_failed_host_keeps_its_rows_for_ten_days_and_loses_them_one_ms_later(draft, tmp_path, monkeypatch)


def test_purge(tmp_path, monkeypatch):
    pairs = moderation._host_table_column_pairs()
    monkeypatch.setattr(moderation, "_host_table_column_pairs", lambda: pairs + [("trending_ranks", "instance_domain")])
    cp.test_purge_host_data_deletes_and_counts_the_host_s_trending_rows(draft, tmp_path, monkeypatch)


def test_purge_today(tmp_path, monkeypatch):
    with pytest.raises(KeyError) as info:
        cp.test_purge_host_data_deletes_and_counts_the_host_s_trending_rows(draft, tmp_path, monkeypatch)
    print("purge without the pair:", repr(info.value))


def test_fetch(monkeypatch):
    cp.test_fetch_host_list_reads_the_host_s_trending_page(draft, monkeypatch)
    for name, failure in cp.FAILURES.items():
        cp.test_fetch_host_list_returns_none_after_max_retries_plus_one_failed_attempts(draft, monkeypatch, failure)
        print("failure kind ok", name)
    cp.test_fetch_host_list_with_no_retries_makes_one_attempt(draft, monkeypatch)
    cp.test_fetch_host_list_returns_the_list_when_a_retry_succeeds(draft, monkeypatch)


def test_lock(tmp_path, monkeypatch):
    cp.test_a_run_that_cannot_take_the_write_lock_raises_and_leaves_the_table_unchanged(draft, tmp_path, monkeypatch)
