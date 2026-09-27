"""Across 460 videos, which cross the 450-entry chunk boundary, the error threshold drops an errored video from `fetch_metadata_by_ids` wherever it sits in its chunk.

- At threshold 3 the id lookup returns exactly the 459 healthy `video_id::instance_domain` keys, c452 as its full joined row, and not c455, which has error_count 5 and sits sixth of the ten pairs in the second chunk, so it is not the last pair. The uuid lookup over the same videos returns the same 459 healthy videos.
- With no threshold the id lookup returns c455's full row.

Everything runs in-process against a temporary SQLite database with the Engine's three joined tables, built the way `tests/active/test_metadata.py` builds them. Nothing is stubbed.
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

BULK = "bulk.example"
THRESHOLD = 3
VIDEO_TEXT = ("video_id", "video_uuid", "instance_domain", "channel_id", "channel_name", "channel_url", "account_name", "account_url", "title", "description", "tags_json", "category", "published_at", "video_url", "thumbnail_url", "embed_path", "preview_path", "last_checked_at")
VIDEO_INT = ("video_numeric_id", "duration", "views", "likes", "dislikes", "comments_count", "nsfw")
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


def _add(conn: sqlite3.Connection, video: tuple, error_count: int | None = 0) -> None:
    video_id, uuid, host, n, _channel = video
    values = {**_video(video_id, uuid, host, n), "error_count": error_count}
    conn.execute(f"INSERT INTO videos ({', '.join(values)}) VALUES ({', '.join('?' * len(values))})", list(values.values()))
    conn.execute("INSERT INTO video_embeddings VALUES (?, ?, x'00', 3, 'm')", (video_id, host))


def _bulk(i: int) -> tuple:
    return (f"c{i:03d}", f"uc{i:03d}", BULK, 100 + i, (None, None))


@pytest.fixture
def conn(tmp_path):
    db = sqlite3.connect(tmp_path / "metadata.db")
    db.row_factory = sqlite3.Row
    columns = ", ".join([f"{column} TEXT" for column in VIDEO_TEXT] + [f"{column} INTEGER" for column in VIDEO_INT] + ["error_count INTEGER"])
    db.execute(f"CREATE TABLE videos ({columns}, PRIMARY KEY (video_id, instance_domain))")
    db.execute("CREATE TABLE video_embeddings (video_id TEXT, instance_domain TEXT, embedding BLOB, embedding_dim INTEGER, model_name TEXT, PRIMARY KEY (video_id, instance_domain))")
    db.execute("CREATE TABLE channels (channel_id TEXT, instance_domain TEXT, display_name TEXT, avatar_url TEXT)")
    db.commit()
    yield db
    db.close()


def test_both_lookups_return_every_healthy_video_across_the_450_entry_chunk_boundary(conn):
    for i in range(BULK_SIZE):
        _add(conn, _bulk(i), error_count=5 if i == BULK_ERRORED else 0)
    conn.commit()
    healthy = [i for i in range(BULK_SIZE) if i != BULK_ERRORED]
    id_entries = [{"video_id": _bulk(i)[0], "instance_domain": BULK} for i in range(BULK_SIZE)]
    assert id_entries[450:][BULK_ERRORED - 450] == {"video_id": "c455", "instance_domain": BULK} and len(id_entries[450:]) == 10, "c455 is no longer mid-way through the second chunk"
    by_id = metadata.fetch_metadata_by_ids(conn, id_entries, error_threshold=THRESHOLD)
    assert {key: row["video_id"] for key, row in by_id.items()} == {f"{_bulk(i)[0]}::{BULK}": _bulk(i)[0] for i in healthy}  # C1
    assert by_id[f"c452::{BULK}"] == _row(*_bulk(452))  # C1
    assert metadata.fetch_metadata_by_ids(conn, id_entries, error_threshold=None)[f"c455::{BULK}"] == _row(*_bulk(BULK_ERRORED))  # C2
    by_uuid = metadata.fetch_metadata_by_uuids(conn, [{"video_uuid": _bulk(i)[1], "instance_domain": BULK} for i in range(BULK_SIZE)], error_threshold=THRESHOLD)
    assert {key: row["video_id"] for key, row in by_uuid.items()} == {f"{_bulk(i)[1]}::{BULK}": _bulk(i)[0] for i in healthy}
