"""Provide db runtime helpers."""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

# SQLite VM instructions between progress-handler callbacks. Small enough that the
# deadline is honoured promptly, large enough that the callback overhead is noise.
PROGRESS_HANDLER_INSTRUCTIONS = 10_000


@contextmanager
def statement_deadline(
    conn: sqlite3.Connection,
    seconds: float,
    lock: Any | None = None,
) -> Iterator[None]:
    """Interrupt any statement on `conn` that is still running after `seconds`.

    Every Engine request path takes one global lock around one shared connection, so
    a single long statement blocks the whole service. SQLite offers no statement
    timeout; the progress handler is the only cancellation point, and returning a
    truthy value from it aborts the running statement with
    `sqlite3.OperationalError: interrupted`.

    The handler is cleared on exit so background and job code sharing the connection
    is never subject to a stale deadline.

    **`lock` is not optional in a threaded server.** Installing a progress handler on a
    connection that is mid-statement deadlocks the process: the running statement needs
    the GIL to invoke the handler, while the installing thread holds the GIL waiting on
    the connection's mutex. Both park forever and the whole service stops answering,
    including routes that touch no database. Passing the same lock that guards statements
    on this connection makes installation wait for the statement instead. Omit it only
    when the caller already holds that lock, or in single-threaded code.

    :param conn: Connection to guard for the duration of the block.
    :param seconds: Wall-clock budget; non-positive disables the guard.
    :param lock: Lock guarding statements on `conn`; held only across handler changes.
    """
    if seconds <= 0:
        yield
        return
    deadline = time.monotonic() + seconds

    def install(handler: Any, instructions: int) -> None:
        """Change the handler without racing a statement on the same connection."""
        if lock is None:
            conn.set_progress_handler(handler, instructions)
            return
        with lock:
            conn.set_progress_handler(handler, instructions)

    install(
        lambda: 1 if time.monotonic() > deadline else 0, PROGRESS_HANDLER_INSTRUCTIONS
    )
    try:
        yield
    finally:
        install(None, 0)


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


def connect_readonly_db(path: Path) -> sqlite3.Connection:
    """Open a second, read-only handle on the same database file.

    A long statement and a `set_progress_handler` call on one connection deadlock each
    other: the statement needs the GIL to invoke its Python progress handler, while the
    installer holds the GIL waiting on the connection's mutex. A query whose duration is
    long enough for another request to arrive mid-flight therefore needs a connection no
    other request path touches, and a deadline installed only while its own lock is held.
    """
    uri = f"file:{path.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
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
