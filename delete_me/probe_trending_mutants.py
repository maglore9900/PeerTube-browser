"""Probe: run the checkpoint's C1/C2 tests against wrong variants of the plan's draft job and print which assertion catches each. Deleted after the probe."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cp = _load("checkpoint_mut", "test_45_trending_from_source_instances_phase1.py")
C1 = cp.test_a_run_asks_only_undenied_embedded_hosts_and_replaces_each_answered_host_s_rows_with_its_list
C2 = cp.test_a_failed_host_keeps_its_rows_for_ten_days_and_loses_them_one_ms_later


def _filter_then_cap(host, videos, fetched_at):
    rows, seen = [], set()
    for rank, video in enumerate(videos, start=1):
        key = video.get("uuid") or (str(video["id"]) if "id" in video else None)
        if key is None or key in seen:
            continue
        seen.add(key)
        rows.append((host, key, rank, video.get("likes") if isinstance(video.get("likes"), int) else 0, video.get("views") if isinstance(video.get("views"), int) else 0, fetched_at))
    return rows[:100]


def _dense(host, videos, fetched_at):
    rows = []
    seen = set()
    for video in videos[:100]:
        key = video.get("uuid") if video.get("uuid") is not None else video.get("id")
        if key is None or str(key) in seen:
            continue
        seen.add(str(key))
        rows.append((host, str(key), len(rows) + 1, video.get("likes") if type(video.get("likes")) is int else 0, video.get("views") if type(video.get("views")) is int else 0, fetched_at))
    return rows


def _last_wins(host, videos, fetched_at):
    by_key = {}
    for rank, video in enumerate(videos[:100], start=1):
        key = video.get("uuid") if video.get("uuid") is not None else video.get("id")
        if key is None:
            continue
        by_key[str(key)] = (host, str(key), rank, video.get("likes") if type(video.get("likes")) is int else 0, video.get("views") if type(video.get("views")) is int else 0, fetched_at)
    return sorted(by_key.values(), key=lambda row: row[2])


def _patch_run(monkeypatch, job, *, delete=True, empty_is_failed=False, op="<"):
    original_execute_run = job.run

    def run(conn, fetch_list, concurrency):
        def wrapped(host):
            result = fetch_list(host)
            return None if empty_is_failed and result == [] else result
        if delete and op == "<":
            return original_execute_run(conn, wrapped, concurrency)
        job.ensure_trending_schema(conn)
        denied = job.list_active_denied_hosts(conn)
        hosts = sorted(row[0] for row in conn.execute("SELECT DISTINCT instance_domain FROM video_embeddings") if row[0].lower() not in denied)
        lists = {host: job._fetch_safely(wrapped, host) for host in hosts}
        run_ms = job.now_ms()
        answered = {host: job.rank_rows(host, videos, run_ms) for host, videos in lists.items() if videos is not None}
        conn.execute("BEGIN IMMEDIATE")
        for host, rows in answered.items():
            if delete:
                conn.execute("DELETE FROM trending_ranks WHERE instance_domain = ?", (host,))
            conn.executemany("INSERT OR REPLACE INTO trending_ranks (instance_domain, video_id, rank, likes, views, fetched_at) VALUES (?, ?, ?, ?, ?, ?)", rows)
        purged = conn.execute(f"DELETE FROM trending_ranks WHERE fetched_at {op} ?", (run_ms - job.AGE_OUT_MS,)).rowcount
        conn.commit()
        return {"asked": len(hosts), "answered": len(answered), "failed": len(hosts) - len(answered), "written": sum(map(len, answered.values())), "purged": purged, "transaction_ms": 0}

    monkeypatch.setattr(job, "run", run)


MUTANTS = {
    "filter-then-cap": (C1, lambda mp, job: mp.setattr(job, "rank_rows", _filter_then_cap)),
    "dense-rank": (C1, lambda mp, job: mp.setattr(job, "rank_rows", _dense)),
    "last-key-wins": (C1, lambda mp, job: mp.setattr(job, "rank_rows", _last_wins)),
    "upsert-no-delete": (C1, lambda mp, job: _patch_run(mp, job, delete=False)),
    "empty-list-is-failed": (C1, lambda mp, job: _patch_run(mp, job, empty_is_failed=True)),
    "purge-at-or-before-cutoff": (C2, lambda mp, job: _patch_run(mp, job, op="<=")),
    "no-age-purge": (C2, lambda mp, job: _patch_run(mp, job, op="< -1 + 0 * ")),
    "failed-host-rows-deleted": (C2, lambda mp, job: mp.setattr(job, "_fetch_safely", lambda fetch_list, host: (lambda r: [] if r is None else r)(_safe(fetch_list, host)))),
}


def _safe(fetch_list, host):
    try:
        return fetch_list(host)
    except Exception:
        return None


@pytest.mark.parametrize("name", list(MUTANTS))
def test_mutant(name, tmp_path, monkeypatch):
    job = _load(f"draft_{name}", "draft_fetch_trending.py")
    test, mutate = MUTANTS[name]
    mutate(monkeypatch, job)
    with pytest.raises(AssertionError) as info:
        test(job, tmp_path, monkeypatch)
    entry = info.traceback[-1]
    print(f"\nMUTANT {name}: caught at checkpoint line {entry.lineno + 1}: {str(entry.statement).strip()[:200]}")
