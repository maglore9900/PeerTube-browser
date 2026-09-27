"""`fetch_metadata_by_uuids` answers an exact `(video_uuid, instance_domain)` pair with the row `fetch_metadata_by_ids` gives that video, and a pair shared by several videos with the lowest `video_id` under the error threshold.

- `u-b@h.example` at threshold 3 gives, keyed `u-b::h.example`, the 29-key row `fetch_metadata_by_ids` gives for `b1@h.example`, with its `channels` and `video_embeddings` columns joined in. That row is the one the fixture stored, and `b1`'s NULL `error_count` does not exclude it.
- `u-a@h.example` gives the `h.example` a1 and not the `other.example` a1. Asking for both gives each under its own key. `U-A@h.example`, `u-a@H.EXAMPLE` and `u-n@h.example` (no embedding) give `{}`. An empty list gives `{}` and runs no SQL statement on the connection.
- The fixture stores the three `u-s` siblings as s2, s1, s3, and a scan of `videos` yields them in that order, so the lowest id is neither the first row nor the last. The lookup keeps s1. With s1's `error_count` at 3 or 5 under threshold 3 it keeps s2; at 2 it keeps s1; and with no threshold it keeps s1 at 5. `u-e` (error_count 5) is dropped at threshold 3 and returned with no threshold.
- The id lookup returns a1's full joined row and skips the unembedded n1. Across 460 videos, which cross the 450-entry chunk boundary at threshold 3, both lookups return exactly the healthy videos, dropping the errored video mid-way through the second chunk.

Everything runs in-process against a temporary SQLite database with the Engine's three joined tables. Nothing is stubbed.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SERVER_DIR = ROOT / "engine" / "server"
API_DIR = SERVER_DIR / "api"
# `data.metadata` imports `recommendations.keys`, which lives under `api`, as the Engine's server.py runs it.
for path in (SERVER_DIR, API_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from data import metadata  # noqa: E402

HOST = "h.example"
OTHER = "other.example"
BULK = "bulk.example"
THRESHOLD = 3
VIDEO_TEXT = ("video_id", "video_uuid", "instance_domain", "channel_id", "channel_name", "channel_url", "account_name", "account_url", "title", "description", "tags_json", "category", "published_at", "video_url", "thumbnail_url", "embed_path", "preview_path", "last_checked_at")
VIDEO_INT = ("video_numeric_id", "duration", "views", "likes", "dislikes", "comments_count", "nsfw")
ROW_KEYS = ("video_id", "video_uuid", "video_numeric_id", "instance_domain", "channel_id", "channel_name", "channel_url", "channel_display_name", "channel_avatar_url", "account_name", "account_url", "title", "description", "tags_json", "category", "published_at", "video_url", "duration", "thumbnail_url", "embed_path", "views", "likes", "dislikes", "comments_count", "nsfw", "preview_path", "last_checked_at", "embedding_dim", "model_name")
# (video_id, video_uuid, instance_domain, n, channel display_name/avatar_url); n makes every integer column distinct per video.
A1 = ("a1", "u-a", HOST, 1, ("Chan A", "ava-a"))
B1 = ("b1", "u-b", HOST, 2, ("Chan B", "ava-b"))
S2 = ("s2", "u-s", HOST, 3, (None, None))
S1 = ("s1", "u-s", HOST, 4, (None, None))
S3 = ("s3", "u-s", HOST, 5, (None, None))
E1 = ("e1", "u-e", HOST, 6, (None, None))
N1 = ("n1", "u-n", HOST, 7, (None, None))
A1_OTHER = ("a1", "u-a", OTHER, 8, (None, None))
BULK_SIZE = 460
# In the second 450-entry chunk and not its last pair.
BULK_ERRORED = 455


def _video(video_id: str, uuid: str, host: str, n: int) -> dict:
    """The `videos` values the fixture stores for one video: each text column names its video, each integer is distinct."""
    values = {column: f"{column}:{video_id}@{host}" for column in VIDEO_TEXT}
    values.update({column: n * 10 + i for i, column in enumerate(VIDEO_INT)})
    values.update(video_id=video_id, video_uuid=uuid, instance_domain=host)
    return values


def _row(video_id: str, uuid: str, host: str, n: int, channel: tuple) -> dict:
    """The metadata row a fixture video should come back as."""
    return {**_video(video_id, uuid, host, n), "channel_display_name": channel[0], "channel_avatar_url": channel[1], "embedding_dim": 3, "model_name": "m"}


def _add(conn: sqlite3.Connection, video: tuple, error_count: int | None = 0, embedded: bool = True) -> None:
    video_id, uuid, host, n, channel = video
    values = {**_video(video_id, uuid, host, n), "error_count": error_count}
    conn.execute(f"INSERT INTO videos ({', '.join(values)}) VALUES ({', '.join('?' * len(values))})", list(values.values()))
    if embedded:
        conn.execute("INSERT INTO video_embeddings VALUES (?, ?, x'00', 3, 'm')", (video_id, host))
    if channel[0] is not None:
        conn.execute("INSERT INTO channels VALUES (?, ?, ?, ?)", (values["channel_id"], host, *channel))


def _bulk(i: int) -> tuple:
    return (f"c{i:03d}", f"uc{i:03d}", BULK, 100 + i, (None, None))


def _by_uuids(conn: sqlite3.Connection, *pairs: tuple[str, str], threshold: int | None = THRESHOLD) -> dict:
    return metadata.fetch_metadata_by_uuids(conn, [{"video_uuid": uuid, "instance_domain": host} for uuid, host in pairs], error_threshold=threshold)


@pytest.fixture
def conn(tmp_path):
    db = sqlite3.connect(tmp_path / "metadata.db")
    db.row_factory = sqlite3.Row
    columns = ", ".join([f"{column} TEXT" for column in VIDEO_TEXT] + [f"{column} INTEGER" for column in VIDEO_INT] + ["error_count INTEGER"])
    db.execute(f"CREATE TABLE videos ({columns}, PRIMARY KEY (video_id, instance_domain))")
    db.execute("CREATE TABLE video_embeddings (video_id TEXT, instance_domain TEXT, embedding BLOB, embedding_dim INTEGER, model_name TEXT, PRIMARY KEY (video_id, instance_domain))")
    db.execute("CREATE TABLE channels (channel_id TEXT, instance_domain TEXT, display_name TEXT, avatar_url TEXT)")
    _add(db, A1)
    _add(db, B1, error_count=None)
    # Stored s2, s1, s3 so a scan yields the lowest id neither first nor last; the shared-pair test asserts that order.
    _add(db, S2)
    _add(db, S1)
    _add(db, S3)
    _add(db, E1, error_count=5)
    _add(db, N1, embedded=False)
    _add(db, A1_OTHER)
    db.commit()
    yield db
    db.close()


def test_a_uuid_pair_gets_the_row_the_id_lookup_gives_its_video(conn):
    by_uuid = _by_uuids(conn, ("u-b", HOST))
    by_id = metadata.fetch_metadata_by_ids(conn, [{"video_id": "b1", "instance_domain": HOST}], error_threshold=THRESHOLD)
    assert set(by_uuid) == {"u-b::h.example"}
    assert set(by_uuid["u-b::h.example"]) == set(ROW_KEYS)
    assert by_uuid["u-b::h.example"] == by_id["b1::h.example"]
    assert by_uuid["u-b::h.example"] == _row(*B1)


def test_a_uuid_pair_matches_only_its_exact_uuid_and_host(conn):
    assert _by_uuids(conn, ("u-a", HOST)) == {"u-a::h.example": _row(*A1)}
    assert _by_uuids(conn, ("u-a", HOST), ("u-a", OTHER)) == {"u-a::h.example": _row(*A1), "u-a::other.example": _row(*A1_OTHER)}
    assert _by_uuids(conn, ("U-A", HOST)) == {}
    assert _by_uuids(conn, ("u-a", "H.EXAMPLE")) == {}
    assert _by_uuids(conn, ("u-n", HOST)) == {}


def test_an_empty_uuid_list_gives_nothing_and_runs_no_statement(conn):
    statements: list[str] = []
    conn.set_trace_callback(statements.append)
    assert _by_uuids(conn, ("u-a", HOST)) != {}
    assert statements, "the trace saw no statement for a lookup that found a row"
    statements.clear()
    assert _by_uuids(conn) == {}
    assert statements == []


def test_a_shared_uuid_pair_keeps_the_lowest_video_id_under_the_threshold(conn):
    assert [row["video_id"] for row in conn.execute("SELECT video_id FROM videos WHERE video_uuid = 'u-s'")] == ["s2", "s1", "s3"], "the fixture no longer puts s1 between its siblings, so first-row-wins would pass"
    assert _by_uuids(conn, ("u-s", HOST)) == {"u-s::h.example": _row(*S1)}
    conn.execute("UPDATE videos SET error_count = 3 WHERE video_id = 's1'")
    assert _by_uuids(conn, ("u-s", HOST)) == {"u-s::h.example": _row(*S2)}
    conn.execute("UPDATE videos SET error_count = 2 WHERE video_id = 's1'")
    assert _by_uuids(conn, ("u-s", HOST)) == {"u-s::h.example": _row(*S1)}
    conn.execute("UPDATE videos SET error_count = 5 WHERE video_id = 's1'")
    assert _by_uuids(conn, ("u-s", HOST)) == {"u-s::h.example": _row(*S2)}
    assert _by_uuids(conn, ("u-s", HOST), threshold=None) == {"u-s::h.example": _row(*S1)}


def test_an_errored_video_s_uuid_pair_is_dropped_only_while_a_threshold_is_set(conn):
    assert _by_uuids(conn, ("u-e", HOST)) == {}
    assert _by_uuids(conn, ("u-e", HOST), threshold=None) == {"u-e::h.example": _row(*E1)}


def test_the_id_lookup_returns_the_joined_row_and_skips_an_unembedded_video(conn):
    entries = [{"video_id": "a1", "instance_domain": HOST}, {"video_id": "n1", "instance_domain": HOST}]
    assert metadata.fetch_metadata_by_ids(conn, entries) == {"a1::h.example": _row(*A1)}


def test_both_lookups_return_every_healthy_video_across_the_450_entry_chunk_boundary(conn):
    for i in range(BULK_SIZE):
        _add(conn, _bulk(i), error_count=5 if i == BULK_ERRORED else 0)
    conn.commit()
    healthy = [i for i in range(BULK_SIZE) if i != BULK_ERRORED]
    by_id = metadata.fetch_metadata_by_ids(conn, [{"video_id": _bulk(i)[0], "instance_domain": BULK} for i in range(BULK_SIZE)], error_threshold=THRESHOLD)
    assert {key: row["video_id"] for key, row in by_id.items()} == {f"{_bulk(i)[0]}::{BULK}": _bulk(i)[0] for i in healthy}
    assert by_id[f"c452::{BULK}"] == _row(*_bulk(452))
    by_uuid = _by_uuids(conn, *[(_bulk(i)[1], BULK) for i in range(BULK_SIZE)])
    assert {key: row["video_id"] for key, row in by_uuid.items()} == {f"{_bulk(i)[1]}::{BULK}": _bulk(i)[0] for i in healthy}
    assert by_uuid[f"uc452::{BULK}"] == _row(*_bulk(452))
