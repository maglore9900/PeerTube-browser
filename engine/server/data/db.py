"""Provide db runtime helpers."""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

# SQLite VM instructions between progress-handler callbacks. Small enough that the
# deadline is honoured promptly, large enough that the callback overhead is noise.
PROGRESS_HANDLER_INSTRUCTIONS = 10_000


@contextmanager
def statement_deadline(conn: sqlite3.Connection, seconds: float) -> Iterator[None]:
    """Interrupt any statement on `conn` that is still running after `seconds`.

    Every Engine request path takes one global lock around one shared connection, so
    a single long statement blocks the whole service. SQLite offers no statement
    timeout; the progress handler is the only cancellation point, and returning a
    truthy value from it aborts the running statement with
    `sqlite3.OperationalError: interrupted`.

    The handler is cleared on exit so background and job code sharing the connection
    is never subject to a stale deadline.

    :param conn: Connection to guard for the duration of the block.
    :param seconds: Wall-clock budget; non-positive disables the guard.
    """
    if seconds <= 0:
        yield
        return
    deadline = time.monotonic() + seconds
    conn.set_progress_handler(
        lambda: 1 if time.monotonic() > deadline else 0, PROGRESS_HANDLER_INSTRUCTIONS
    )
    try:
        yield
    finally:
        conn.set_progress_handler(None, 0)


def is_interrupted_error(exc: sqlite3.OperationalError) -> bool:
    """Report whether `exc` is the abort raised by a tripped progress handler.

    :param exc: Error raised out of a statement executed under `statement_deadline`.
    :returns: True when the statement was cancelled rather than failing on its own.
    """
    return "interrupted" in str(exc).lower()


def connect_db(path: Path) -> sqlite3.Connection:
    """Open the crawl database for shared reads and writes."""
    conn = sqlite3.connect(path.as_posix(), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def connect_user_db(path: Path) -> sqlite3.Connection:
    """Open or create the users database."""
    conn = sqlite3.connect(path.as_posix(), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def connect_similarity_db(path: Path) -> sqlite3.Connection:
    """Open the similarity cache database."""
    conn = sqlite3.connect(path.as_posix(), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn
