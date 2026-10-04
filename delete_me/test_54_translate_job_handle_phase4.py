"""Phase 4 checkpoint of plan 54: `resolve_translatable_video` in engine/server/api/handlers/internal_translate.py refuses a missing host before any lookup, then a video not in the whitelist, then an actively denied host, and otherwise answers the row.

Called directly on test_internal_translate.py's whitelist.db: v-1/u-1 on peer.example, d-1/du-1 on denied.example, with a denylist row for denied.example stored as `DENIED.EXAMPLE`.

- C1, missing host: host None and host "" each answer `(None, "missing host")` for v-1, a video that resolves with its host. A None host is the case that matters: `fetch_video_row` with no host matches the id on any host. On a closed connection, which raises on any read once a host is given, they answer the same, so no lookup ran.
- C1, not in whitelist: an unknown id, the known uuid on another host, and v-1 with its error_count at the threshold each answer `(None, "not in whitelist")`. Controls: v-1 one error below the threshold, and with the threshold 0 (no error filter), answers its row.
- C1, host denied: d-1 with its denylist row active answers `(None, "host denied")`, while d-1 with no host answers `missing host` and an unknown id on the denied host answers `not in whitelist`, so the denylist is checked last. Control: with the row inactive, the same call answers d-1's row.
- C1, the row: v-1 by its id and by its uuid answers the row (canonical video_id v-1, instance_domain peer.example) and no refusal.
"""
from __future__ import annotations

import importlib
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))

from test_internal_translate import DENIED_HOST, DENIED_VIDEO, HOST, PEER_VIDEO, THRESHOLD, _set_denied, _whitelist  # noqa: E402


@pytest.fixture
def whitelist(tmp_path):
    conn = _whitelist(tmp_path / "whitelist.db")
    yield conn
    conn.close()


def _resolve():  # noqa: ANN202
    """The function under test, looked up per test so a missing name fails each test at its own call."""
    return importlib.import_module("handlers.internal_translate").resolve_translatable_video


def _error_count(whitelist, count: int) -> None:
    whitelist.execute("UPDATE videos SET error_count = ? WHERE video_id = ?", (count, PEER_VIDEO[0]))
    whitelist.commit()


def _key(answer: tuple) -> tuple:
    """(canonical video_id, instance_domain, refusal) of an answer, or (None, None, refusal) when no row came back."""
    row, refusal = answer
    return (row["video_id"], row["instance_domain"], refusal) if row is not None else (None, None, refusal)


@pytest.mark.parametrize("host", [None, ""], ids=["None", "empty"])
def test_a_missing_host_is_refused_before_any_lookup(whitelist, host):
    resolve = _resolve()
    assert _key(resolve(whitelist, PEER_VIDEO[0], HOST, THRESHOLD)) == (PEER_VIDEO[0], HOST, None)  # control: v-1 resolves with its host
    assert resolve(whitelist, PEER_VIDEO[0], host, THRESHOLD) == (None, "missing host")  # C1
    # A closed connection raises on any read, so an answer from it shows no lookup ran.
    closed = sqlite3.connect(":memory:")
    closed.close()
    with pytest.raises(sqlite3.ProgrammingError):
        resolve(closed, PEER_VIDEO[0], HOST, THRESHOLD)  # control: with a host, the lookup reads the connection
    assert resolve(closed, PEER_VIDEO[0], host, THRESHOLD) == (None, "missing host")  # C1: refused before any lookup


def test_a_video_not_in_the_whitelist_is_refused(whitelist):
    resolve = _resolve()
    assert resolve(whitelist, "no-such-video", HOST, THRESHOLD) == (None, "not in whitelist")  # C1
    assert resolve(whitelist, PEER_VIDEO[1], "other.example", THRESHOLD) == (None, "not in whitelist")  # C1: a known uuid on another host
    _error_count(whitelist, THRESHOLD - 1)
    assert _key(resolve(whitelist, PEER_VIDEO[0], HOST, THRESHOLD)) == (PEER_VIDEO[0], HOST, None)  # control: one error below the threshold still resolves
    _error_count(whitelist, THRESHOLD)
    assert resolve(whitelist, PEER_VIDEO[0], HOST, THRESHOLD) == (None, "not in whitelist")  # C1: the error threshold applies
    assert _key(resolve(whitelist, PEER_VIDEO[0], HOST, 0)) == (PEER_VIDEO[0], HOST, None)  # control: the same row with no error filter


def test_an_actively_denied_host_is_refused_only_after_the_host_and_the_whitelist_checks(whitelist):
    resolve = _resolve()
    _set_denied(whitelist, True)
    assert resolve(whitelist, DENIED_VIDEO[1], DENIED_HOST, THRESHOLD) == (None, "host denied")  # C1
    # The denylist is the last check: a missing host and an unknown video on the denied host keep their own refusals.
    assert resolve(whitelist, DENIED_VIDEO[1], None, THRESHOLD) == (None, "missing host")  # C1
    assert resolve(whitelist, "no-such-video", DENIED_HOST, THRESHOLD) == (None, "not in whitelist")  # C1
    _set_denied(whitelist, False)
    assert _key(resolve(whitelist, DENIED_VIDEO[1], DENIED_HOST, THRESHOLD)) == (DENIED_VIDEO[0], DENIED_HOST, None)  # control: inactive, the same call answers the row


@pytest.mark.parametrize("video_key", [PEER_VIDEO[0], PEER_VIDEO[1]], ids=["id", "uuid"])
def test_a_whitelisted_video_answers_its_row_and_no_refusal(whitelist, video_key):
    assert _key(_resolve()(whitelist, video_key, HOST, THRESHOLD)) == (PEER_VIDEO[0], HOST, None)  # C1
