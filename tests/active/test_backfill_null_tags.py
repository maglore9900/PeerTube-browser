"""`backfill-null-tags.py` fills `videos.tags_json` only where it is NULL, from each video's own instance, and the write reaches tag search.

- A run asks exactly the NULL-tag videos with a uuid on undenied hosts (not `'[]'`, not tagged, not denied, not uuid-less), writes each answer, leaves a failed fetch NULL, and the written tag is found by an FTS column match on `videos_fts.tags_json` that found nothing before.
- A host stops being asked after `give_up_after` failures in a row, a success resets the count, and another host in the same run is unaffected.
- `limit` caps the videos asked.
- `fetch_video_tags` asks `/api/v1/videos/<quoted uuid>` on the video's host and keeps only the string tags; a failed fetch, a non-JSON body or an answer with no tag list is None.

Each DB is a tmp whitelist-shaped DB (crawler `schema.sql`, moderation schema, and `videos_fts` with `sync-whitelist.py`'s own triggers); the network is the only thing stood in for.
"""
from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SERVER_DIR = ROOT / "engine" / "server"
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from data.moderation import ensure_moderation_schema  # noqa: E402
from data.source_fetch import SourceFetchFailed  # noqa: E402

JOBS_DIR = SERVER_DIR / "db" / "jobs"
CRAWL_SCHEMA = ROOT / "engine" / "crawler" / "schema.sql"
FTS_SQL = "CREATE VIRTUAL TABLE videos_fts USING fts5(title, description, tags_json, category, channel_name, content='videos', content_rowid='rowid')"


def _load_job(module_name: str, filename: str):
    spec = importlib.util.spec_from_file_location(module_name, JOBS_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def job():
    return _load_job("backfill_null_tags_job", "backfill-null-tags.py")


@pytest.fixture(scope="module")
def sync():
    return _load_job("sync_whitelist_for_backfill", "sync-whitelist.py")


def _db(path: Path, sync, videos: list[tuple[str, str, str | None, str | None]], denied: tuple[str, ...] = ()) -> sqlite3.Connection:
    """A whitelist-shaped DB holding `videos` as (video_id, host, uuid, tags_json), with videos_fts kept by the sync job's triggers."""
    conn = sqlite3.connect(path)
    # The Row factory the job's own connection sets.
    conn.row_factory = sqlite3.Row
    conn.executescript(CRAWL_SCHEMA.read_text(encoding="utf-8"))
    ensure_moderation_schema(conn)
    conn.execute(FTS_SQL)
    sync.create_videos_fts_triggers(conn)
    conn.executemany("INSERT INTO videos (video_id, instance_domain, video_uuid, tags_json, title, published_at, last_checked_at) VALUES (?, ?, ?, ?, 'video', 0, 0)", videos)
    conn.executemany("INSERT INTO instance_denylist (host, is_active, created_at, updated_at) VALUES (?, 1, 0, 0)", [(host,) for host in denied])
    conn.commit()
    return conn


def _fetcher(answers: dict[str, object]):
    """A (host, uuid) fetcher answering each uuid from `answers` (tags_json, None, or an exception to raise), recording every call."""
    calls: list[tuple[str, str]] = []

    def fetch(host: str, uuid: str):
        calls.append((host, uuid))
        outcome = answers[uuid]
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    return fetch, calls


def _tags(conn: sqlite3.Connection) -> dict[str, str | None]:
    return {video_id: tags for video_id, tags in conn.execute("SELECT video_id, tags_json FROM videos")}


def _fts_hits(conn: sqlite3.Connection, word: str) -> list[str]:
    return sorted(row[0] for row in conn.execute("SELECT v.video_id FROM videos_fts f JOIN videos v ON v.rowid = f.rowid WHERE videos_fts MATCH ?", (f'tags_json : "{word}"',)))


def test_a_run_fills_only_null_tags_on_undenied_hosts_and_the_tag_becomes_searchable(job, sync, tmp_path):
    conn = _db(tmp_path / "whitelist.db", sync, [
        ("A", "a.example", "uuid-a", None),
        ("B", "a.example", "uuid-b", "[]"),
        ("C", "a.example", "uuid-c", '["kept"]'),
        ("D", "denied.example", "uuid-d", None),
        ("E", "a.example", None, None),
        ("F", "b.example", "uuid-f", None),
        ("G", "b.example", "uuid-g", None),
    ], denied=("denied.example",))
    fetch, calls = _fetcher({"uuid-a": '["Linux", "zebrafish"]', "uuid-f": None, "uuid-g": RuntimeError("connection reset")})
    assert _fts_hits(conn, "zebrafish") == []  # control: nothing is tagged so before the run

    stats = job.run(conn, fetch, concurrency=2, host_delay_s=0)

    assert sorted(calls) == [("a.example", "uuid-a"), ("b.example", "uuid-f"), ("b.example", "uuid-g")]  # only NULL rows with a uuid on undenied hosts
    assert _tags(conn) == {"A": '["Linux", "zebrafish"]', "B": "[]", "C": '["kept"]', "D": None, "E": None, "F": None, "G": None}  # failures stay NULL for a later run
    assert stats == {"hosts": 2, "asked": 3, "written": 1, "failed": 2}
    assert _fts_hits(conn, "zebrafish") == ["A"]  # the update reached tag search through the triggers
    rerun, recalls = _fetcher({"uuid-f": '["late"]', "uuid-g": None})
    job.run(conn, rerun, concurrency=1, host_delay_s=0)
    assert sorted(recalls) == [("b.example", "uuid-f"), ("b.example", "uuid-g")]  # a second run asks only what is still NULL
    assert _tags(conn)["F"] == '["late"]'


def test_a_host_is_left_after_failures_in_a_row_and_a_success_resets_the_count(job, sync, tmp_path):
    dead = [(f"d{i}", "dead.example", f"dead-{i}", None) for i in range(7)]
    flaky = [(f"f{i}", "flaky.example", f"flaky-{i}", None) for i in range(6)]
    conn = _db(tmp_path / "whitelist.db", sync, dead + flaky)
    answers: dict[str, object] = {f"dead-{i}": None for i in range(7)}
    answers.update({"flaky-0": None, "flaky-1": None, "flaky-2": '["ok"]', "flaky-3": None, "flaky-4": None, "flaky-5": '["ok"]'})
    fetch, calls = _fetcher(answers)

    stats = job.run(conn, fetch, concurrency=2, host_delay_s=0, give_up_after=3)

    assert len([call for call in calls if call[0] == "dead.example"]) == 3  # left after three failures in a row
    assert len([call for call in calls if call[0] == "flaky.example"]) == 6  # never three in a row, so every video is asked
    assert stats["written"] == 2 and stats["failed"] == 7


def test_limit_caps_the_videos_asked(job, sync, tmp_path):
    conn = _db(tmp_path / "whitelist.db", sync, [(f"v{i}", "a.example", f"u{i}", None) for i in range(5)])
    fetch, calls = _fetcher({f"u{i}": '["t"]' for i in range(5)})
    stats = job.run(conn, fetch, concurrency=1, host_delay_s=0, limit=2)
    assert len(calls) == 2 and stats["written"] == 2
    assert sum(tags is None for tags in _tags(conn).values()) == 3


def test_fetch_video_tags_asks_the_video_s_page_and_keeps_string_tags(job, monkeypatch):
    asked: list[tuple[str, str]] = []

    def answer(body):
        def fake(host, path, **kwargs):
            asked.append((host, path))
            if isinstance(body, BaseException):
                raise body
            return body
        return fake

    monkeypatch.setattr(job, "fetch_bounded", answer(json.dumps({"tags": ["a b", 1, "c"]}).encode()))
    assert job.fetch_video_tags("tube.example", "x/y z", 5) == json.dumps(["a b", "c"], ensure_ascii=False)
    assert asked == [("tube.example", "/api/v1/videos/x/y%20z")]
    monkeypatch.setattr(job, "fetch_bounded", answer(json.dumps({"tags": []}).encode()))
    assert job.fetch_video_tags("tube.example", "u", 5) == "[]"  # an answer with no tags is stored, so it is not asked again
    for body in (json.dumps({"name": "no tags"}).encode(), b"<html>", SourceFetchFailed("HTTP 404")):
        monkeypatch.setattr(job, "fetch_bounded", answer(body))
        assert job.fetch_video_tags("tube.example", "u", 5) is None, body
