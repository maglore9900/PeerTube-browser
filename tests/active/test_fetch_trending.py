"""`fetch-trending.py` stores each answered host's own trending list in `trending_ranks`, and keeps a failed host's earlier rows until they are more than 10 days old. That `purge_host_data` removes a host's rank rows is gated in `test_moderation.py`.

- A run asks exactly the distinct hosts of `video_embeddings` minus the active denylist: not a host that is only in `videos` or `instances`, not an active denied host, not one stored mixed-case as `Denied.Example` against a denied `denied.example`, but a host whose denylist row is inactive.
- After a second run, an answered host's rows are exactly its new list and its earlier keys are gone: from a 120-entry list with a keyless entry at position 50, the 99 rows of positions 1-100 except 50, ranked by position. In a short list, `uuid` wins over `id`, an int `id` is stored as its decimal string, an entry with neither leaves a gap in the ranks, a key repeated by `uuid` or by `id` keeps its first rank and counts, and non-int or missing likes and views are 0. A host answering an empty list is left with no rows. Every written row carries the run's `now_ms`, and `run` returns asked 5, answered 3, failed 2, written 103, purged 0, with an int `transaction_ms`.
- A host whose fetcher returns None and one whose fetcher raises each keep their rows, `fetched_at` unchanged, through a run exactly 10 days after that fetch; a run 1 ms later purges them both (stats purged 3) while a row 1 ms old from a host failing the same run stays.
- `fetch_host_list` requests exactly `https://tube.example/api/v1/videos?sort=-trending&isLocal=true&count=100&nsfw=both` through `data.source_fetch` with the given timeout and the `peertube-browser-trending/1.0` User-Agent, and returns the body's `data` list, `[]` included; on HTTP 500 or 400, a URLError, a TimeoutError, a non-JSON body, a body without `data` or with a non-list `data` it makes `max_retries + 1` attempts (1 when `max_retries` is 0) and returns None; a retry that succeeds returns its list.
- With another connection holding `BEGIN IMMEDIATE`, `run` raises `database is locked` and the table keeps the earlier run's rows.
- Run as a script, `--db` naming a missing file exits non-zero and creates no file, while the same command on a ready DB with no embedded host exits 0 and creates `trending_ranks`.

The job is loaded in-process from its file, as `test_host_normalisation._load_job` does. The network is the only thing stood in for: `run` gets an injected per-host fetcher, `fetch_host_list` a scripted https open step under `data.source_fetch`'s real opener, and the clock is the module's own `now_ms`, patched. Each DB is a tmp `whitelist.db` from the crawler `schema.sql`, the shared `video_embeddings` definition and `ensure_moderation_schema`.
"""
from __future__ import annotations

import importlib.util
import io
import sqlite3
import subprocess
import sys
from http.client import HTTPMessage
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import HTTPSHandler, build_opener

import pytest

ROOT = Path(__file__).resolve().parents[2]
SERVER_DIR = ROOT / "engine" / "server"
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from data import source_fetch  # noqa: E402
from data.ann_ids import create_video_embeddings_table  # noqa: E402
from data.moderation import ensure_moderation_schema  # noqa: E402

JOBS_DIR = SERVER_DIR / "db" / "jobs"
JOB = JOBS_DIR / "fetch-trending.py"
CRAWL_SCHEMA = ROOT / "engine" / "crawler" / "schema.sql"
TRENDING_URL = "https://tube.example/api/v1/videos?sort=-trending&isLocal=true&count=100&nsfw=both"
USER_AGENT = "peertube-browser-trending/1.0"
T0 = 1_760_000_000_000
DAY_MS = 86_400_000
TEN_DAYS_MS = 864_000_000


def _load_job(module_name: str, filename: str):
    spec = importlib.util.spec_from_file_location(module_name, JOBS_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def job():
    return _load_job("fetch_trending_job", "fetch-trending.py")


def _db(path: Path, embedded: list[tuple[str, str]]) -> sqlite3.Connection:
    """A whitelist-shaped DB whose video_embeddings holds `embedded` (video_id, host) pairs, committed, with the Row factory the job's own connection sets."""
    # A short busy wait, so the competing-lock run fails at once instead of after sqlite's 5 s default.
    conn = sqlite3.connect(path, timeout=0.2)
    conn.row_factory = sqlite3.Row
    conn.executescript(CRAWL_SCHEMA.read_text(encoding="utf-8"))
    create_video_embeddings_table(conn)
    ensure_moderation_schema(conn)
    conn.executemany("INSERT INTO video_embeddings (video_id, instance_domain, embedding, embedding_dim, model_name, created_at, ann_id) VALUES (?, ?, x'00', 1, 'm', 't', ?)", [(video_id, host, ann_id) for ann_id, (video_id, host) in enumerate(embedded, start=1)])
    conn.commit()
    return conn


def _rows(conn: sqlite3.Connection, host: str) -> list[tuple]:
    return [tuple(row) for row in conn.execute("SELECT video_id, rank, likes, views, fetched_at FROM trending_ranks WHERE instance_domain = ? ORDER BY rank", (host,))]


def _fetcher(lists: dict[str, object]):
    """A per-host fetcher answering each host from `lists`: a list, None, or an exception it raises; it records every host it is asked."""
    calls: list[str] = []

    def fetch_list(host: str):
        calls.append(host)
        outcome = lists[host]
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    return fetch_list, calls


def _at(monkeypatch, job, ms: int) -> None:
    monkeypatch.setattr(job, "now_ms", lambda: ms)


def test_a_run_asks_only_undenied_embedded_hosts_and_replaces_each_answered_host_s_rows_with_its_list(job, tmp_path, monkeypatch):
    """Asked hosts are the distinct embedded hosts minus the active denylist, mixed case included; an answered host's rows become exactly its new list (positional ranks with gaps, first rank per key, uuid over id, at most 100), an empty list leaves none, and the stats count the run."""
    embedded = [("a-v1", "a.example"), ("a-v2", "a.example"), ("b-v1", "b.example"), ("c-v1", "c.example"), ("d-v1", "d.example"), ("l-v1", "lifted.example"), ("x-v1", "blocked.example"), ("y-v1", "Denied.Example")]
    conn = _db(tmp_path / "whitelist.db", embedded)
    conn.execute("INSERT INTO videos (video_id, instance_domain, last_checked_at) VALUES ('u-v1', 'unembedded.example', 0)")
    conn.execute("INSERT INTO instances (host, health_status) VALUES ('healthy.example', 'ok')")
    conn.executemany("INSERT INTO instance_denylist (host, is_active, created_at, updated_at) VALUES (?, ?, 0, 0)", [("blocked.example", 1), ("denied.example", 1), ("lifted.example", 0)])
    conn.commit()
    asked = ["a.example", "b.example", "c.example", "d.example", "lifted.example"]

    _at(monkeypatch, job, T0)
    fetch_list, calls = _fetcher({"a.example": [{"uuid": "a-old-1"}, {"uuid": "a-old-2"}], "b.example": [{"uuid": "b-old"}], "lifted.example": [{"id": 7}], "c.example": None, "d.example": RuntimeError("connection reset")})
    job.run(conn, fetch_list, 3)
    assert sorted(calls) == asked
    # Controls: the first run stored each answered host's list, so the second run below has earlier rows to replace.
    assert _rows(conn, "a.example") == [("a-old-1", 1, 0, 0, T0), ("a-old-2", 2, 0, 0, T0)]
    assert _rows(conn, "b.example") == [("b-old", 1, 0, 0, T0)]
    assert _rows(conn, "lifted.example") == [("7", 1, 0, 0, T0)]

    t1 = T0 + DAY_MS
    _at(monkeypatch, job, t1)
    long_list = [{"uuid": f"a-{n}", "likes": n, "views": 10 * n} for n in range(1, 121)]
    long_list[49] = {"name": "no uuid and no id"}
    short_list = [
        {"uuid": "b-uuid-1", "id": 101, "likes": 5, "views": 50},
        {"id": 102, "likes": "7", "views": None},
        {"name": "no uuid and no id", "likes": 9, "views": 90},
        {"uuid": "b-uuid-1", "likes": 100, "views": 1000},
        {"uuid": "b-uuid-5", "likes": 1.5, "views": 2},
        {"id": 102, "likes": 4, "views": 40},
        {"uuid": "b-uuid-7", "likes": 3, "views": 30},
    ]
    fetch_list, calls = _fetcher({"a.example": long_list, "b.example": short_list, "lifted.example": [], "c.example": None, "d.example": RuntimeError("connection reset")})
    stats = job.run(conn, fetch_list, 3)

    assert sorted(calls) == asked
    assert [(row[0], row[1]) for row in _rows(conn, "a.example")] == [(f"a-{n}", n) for n in range(1, 101) if n != 50]  # C1
    assert {row[4] for row in _rows(conn, "a.example")} == {t1}  # C1
    assert _rows(conn, "b.example") == [("b-uuid-1", 1, 5, 50, t1), ("102", 2, 0, 0, t1), ("b-uuid-5", 5, 0, 2, t1), ("b-uuid-7", 7, 3, 30, t1)]  # C1
    assert _rows(conn, "lifted.example") == []  # C1
    assert {key: value for key, value in stats.items() if key != "transaction_ms"} == {"asked": 5, "answered": 3, "failed": 2, "written": 103, "purged": 0}
    assert isinstance(stats["transaction_ms"], int) and stats["transaction_ms"] >= 0


def test_a_failed_host_keeps_its_rows_for_ten_days_and_loses_them_one_ms_later(job, tmp_path, monkeypatch):
    """A host whose fetcher returns None and one whose fetcher raises keep their rows and fetched_at at exactly 10 days; 1 ms later the age purge removes them, but not a fresh row of another failed host."""
    conn = _db(tmp_path / "whitelist.db", [("a-v1", "a.example"), ("c-v1", "c.example"), ("d-v1", "d.example")])
    _at(monkeypatch, job, T0)
    job.run(conn, _fetcher({"a.example": [{"uuid": "a-1"}], "c.example": [{"uuid": "c-1"}, {"uuid": "c-2"}], "d.example": [{"uuid": "d-1"}]})[0], 3)
    # Control: every host answered the first run, so each has rows fetched at T0.
    assert _rows(conn, "c.example") == [("c-1", 1, 0, 0, T0), ("c-2", 2, 0, 0, T0)]
    assert _rows(conn, "d.example") == [("d-1", 1, 0, 0, T0)]

    t_kept = T0 + TEN_DAYS_MS
    _at(monkeypatch, job, t_kept)
    stats = job.run(conn, _fetcher({"a.example": [{"uuid": "a-2"}], "c.example": None, "d.example": OSError("timed out")})[0], 3)
    assert _rows(conn, "c.example") == [("c-1", 1, 0, 0, T0), ("c-2", 2, 0, 0, T0)]  # C2
    assert _rows(conn, "d.example") == [("d-1", 1, 0, 0, T0)]  # C2
    assert _rows(conn, "a.example") == [("a-2", 1, 0, 0, t_kept)]
    assert (stats["failed"], stats["purged"]) == (2, 0)  # C2

    _at(monkeypatch, job, t_kept + 1)
    stats = job.run(conn, _fetcher({"a.example": None, "c.example": None, "d.example": OSError("timed out")})[0], 3)
    assert _rows(conn, "c.example") == []  # C2
    assert _rows(conn, "d.example") == []  # C2
    assert _rows(conn, "a.example") == [("a-2", 1, 0, 0, t_kept)]  # C2
    assert (stats["failed"], stats["purged"]) == (3, 3)  # C2


class _Response(io.BytesIO):
    """One 200 answer as urllib's https open step hands it on: status, headers and a body read in chunks."""

    code = status = 200
    msg = "Scripted"

    def __init__(self, body: bytes):
        super().__init__(body)
        self.headers = HTTPMessage()

    def info(self) -> HTTPMessage:
        return self.headers


def _scripted(monkeypatch, outcomes: list[object]) -> list[tuple[str, object, str | None]]:
    """Replace the https open step under `data.source_fetch`'s real opener: each attempt gets the next outcome, raised when it is an exception, else served as a 200 body; return each attempt's (url, timeout, User-Agent)."""
    attempts: list[tuple[str, object, str | None]] = []
    pending = list(outcomes)

    class Scripted(HTTPSHandler):
        def https_open(self, req):
            attempts.append((req.full_url, req.timeout, req.get_header("User-agent")))
            outcome = pending.pop(0)
            if isinstance(outcome, BaseException):
                raise outcome
            return _Response(outcome)

    monkeypatch.setattr(source_fetch, "build_opener", lambda *handlers: build_opener(Scripted(), *handlers))
    return attempts


def test_fetch_host_list_reads_the_host_s_trending_page(job, monkeypatch):
    """One attempt at the exact trending URL with the given timeout and the job's User-Agent returns the body's `data` list, and an empty list is returned as `[]`, not None."""
    attempts = _scripted(monkeypatch, [b'{"total": 2, "data": [{"uuid": "x"}, {"id": 3}]}', b'{"total": 0, "data": []}'])

    assert job.fetch_host_list("tube.example", timeout_s=0.25, max_retries=2) == [{"uuid": "x"}, {"id": 3}]
    assert attempts == [(TRENDING_URL, 0.25, USER_AGENT)]
    assert job.fetch_host_list("tube.example", timeout_s=0.25, max_retries=2) == []
    assert attempts == [(TRENDING_URL, 0.25, USER_AGENT)] * 2


FAILURES = {
    "http-500": HTTPError(TRENDING_URL, 500, "Internal Server Error", {}, None),
    "http-400": HTTPError(TRENDING_URL, 400, "Bad Request", {}, None),
    "url-error": URLError("connection refused"),
    "timeout": TimeoutError("timed out"),
    "not-json": b"<html>maintenance</html>",
    "no-data": b'{"total": 0}',
    "data-not-a-list": b'{"total": 1, "data": "nope"}',
}


@pytest.mark.parametrize("failure", list(FAILURES.values()), ids=list(FAILURES))
def test_fetch_host_list_returns_none_after_max_retries_plus_one_failed_attempts(job, monkeypatch, failure):
    """Every failure kind is retried: with max_retries 2 the host gets exactly 3 attempts, then None."""
    attempts = _scripted(monkeypatch, [failure] * 10)

    assert job.fetch_host_list("tube.example", timeout_s=0.25, max_retries=2) is None
    assert attempts == [(TRENDING_URL, 0.25, USER_AGENT)] * 3


def test_fetch_host_list_with_no_retries_makes_one_attempt(job, monkeypatch):
    attempts = _scripted(monkeypatch, [URLError("connection refused")] * 10)

    assert job.fetch_host_list("tube.example", timeout_s=0.25, max_retries=0) is None
    assert attempts == [(TRENDING_URL, 0.25, USER_AGENT)]


def test_fetch_host_list_returns_the_list_when_a_retry_succeeds(job, monkeypatch):
    attempts = _scripted(monkeypatch, [URLError("connection refused"), b'{"total": 1, "data": [{"uuid": "x"}]}'])

    assert job.fetch_host_list("tube.example", timeout_s=0.25, max_retries=2) == [{"uuid": "x"}]
    assert attempts == [(TRENDING_URL, 0.25, USER_AGENT)] * 2


def test_a_run_that_cannot_take_the_write_lock_raises_and_leaves_the_table_unchanged(job, tmp_path, monkeypatch):
    """With another connection holding BEGIN IMMEDIATE, `run` raises `database is locked` instead of reporting success, and the earlier run's rows stay."""
    path = tmp_path / "whitelist.db"
    conn = _db(path, [("a-v1", "a.example")])
    _at(monkeypatch, job, T0)
    job.run(conn, _fetcher({"a.example": [{"uuid": "a-old"}]})[0], 3)
    # Control: the table holds the earlier run's row before the lock is taken.
    assert _rows(conn, "a.example") == [("a-old", 1, 0, 0, T0)]

    holder = sqlite3.connect(path, isolation_level=None)
    holder.execute("BEGIN IMMEDIATE")
    try:
        _at(monkeypatch, job, T0 + DAY_MS)
        with pytest.raises(sqlite3.OperationalError, match="database is locked"):
            job.run(conn, _fetcher({"a.example": [{"uuid": "a-new"}]})[0], 3)
    finally:
        holder.rollback()
        holder.close()

    assert _rows(conn, "a.example") == [("a-old", 1, 0, 0, T0)]


def test_the_job_exits_non_zero_on_a_missing_db_and_creates_no_file(tmp_path):
    """`--db` naming a missing file exits non-zero and leaves no file; the same command on a ready DB exits 0 and creates `trending_ranks`."""
    ready = tmp_path / "ready.db"
    _db(ready, []).close()
    ok = subprocess.run([sys.executable, str(JOB), "--db", str(ready)], cwd=ROOT, capture_output=True, text=True, timeout=60)
    # The positive half of the claim, which also arms the missing-DB assertions below: the job runs to completion under this interpreter and these arguments, so a non-zero exit there is the missing DB and not an import or argument error.
    assert ok.returncode == 0, ok.stderr
    check = sqlite3.connect(ready)
    try:
        assert check.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'trending_ranks'").fetchall() == [("trending_ranks",)]
    finally:
        check.close()

    missing = tmp_path / "absent.db"
    proc = subprocess.run([sys.executable, str(JOB), "--db", str(missing)], cwd=ROOT, capture_output=True, text=True, timeout=60)

    assert proc.returncode != 0
    assert not missing.exists()
