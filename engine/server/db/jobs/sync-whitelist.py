#!/usr/bin/env python3
"""Filter crawled data using trusted PeerTube instances from joinpeertube.org.

Fetches the whitelist and uses it to keep only data from approved instances.
"""
import argparse
import json
import logging
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

script_dir = Path(__file__).resolve().parent
server_dir = script_dir.parents[1]
if str(server_dir) not in sys.path:
    sys.path.insert(0, str(server_dir))
api_dir = server_dir / "api"
if str(api_dir) not in sys.path:
    sys.path.insert(0, str(api_dir))

from scripts.cli_format import CompactHelpFormatter
from server_config import DEFAULT_DB_PATH
from data.moderation import ensure_moderation_schema, list_active_denied_hosts, normalize_host_token

DEFAULT_URL = (
    "https://instances.joinpeertube.org/api/v1/instances/hosts?count=5000&healthy=true"
)
DEFAULT_SOURCE_DB_PATH = Path(DEFAULT_DB_PATH)
DEFAULT_WHITELIST_DB_PATH = Path("engine/server/db/whitelist.db")
TABLE_NAME = "instances"
SOURCE_SCHEMA = "source"
MODES = ("include", "exclude")
SCHEMA_SQL_PATH = (script_dir.parents[3] / "engine" / "crawler" / "schema.sql").resolve()

EXCLUDED_CHANNEL_COLUMNS: set[str] = set()
EXCLUDED_VIDEO_COLUMNS: set[str] = set()
EXCLUDED_INSTANCE_COLUMNS: set[str] = set()


def _load_schema_columns(schema_path: Path, table: str) -> list[str]:
    """Handle load schema columns."""
    sql = schema_path.read_text(encoding="utf-8")
    marker = f"CREATE TABLE IF NOT EXISTS {table}"
    start = sql.find(marker)
    if start == -1:
        raise ValueError(f"Missing {table} definition in {schema_path}")
    open_paren = sql.find("(", start)
    if open_paren == -1:
        raise ValueError(f"Missing columns for {table} in {schema_path}")
    close_paren = sql.find(");", open_paren)
    if close_paren == -1:
        raise ValueError(f"Missing end of {table} definition in {schema_path}")
    body = sql[open_paren + 1 : close_paren]
    # Split on top-level commas only: a composite `PRIMARY KEY (a, b)` clause must be
    # consumed as one chunk, otherwise its trailing member is parsed as a phantom
    # column named `b)` that no real table can satisfy.
    chunks: list[str] = []
    current: list[str] = []
    depth = 0
    for char in body:
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        if char == "," and depth == 0:
            chunks.append("".join(current))
            current = []
            continue
        current.append(char)
    chunks.append("".join(current))
    columns: list[str] = []
    for chunk in chunks:
        item = chunk.strip()
        if not item:
            continue
        token = item.split()[0].strip("`\"")
        if token.upper() in {"PRIMARY", "FOREIGN", "UNIQUE", "CHECK", "CONSTRAINT"}:
            continue
        columns.append(token)
    if not columns:
        raise ValueError(f"No columns parsed for {table} from {schema_path}")
    return columns


def _schema_columns(schema_path: Path, table: str, exclude: set[str]) -> list[str]:
    """Handle schema columns."""
    return [col for col in _load_schema_columns(schema_path, table) if col not in exclude]

INSTANCE_COLUMNS = _schema_columns(
    SCHEMA_SQL_PATH, "instances", EXCLUDED_INSTANCE_COLUMNS
)
CHANNEL_COLUMNS = _schema_columns(SCHEMA_SQL_PATH, "channels", EXCLUDED_CHANNEL_COLUMNS)
VIDEO_COLUMNS = _schema_columns(SCHEMA_SQL_PATH, "videos", EXCLUDED_VIDEO_COLUMNS)

# Columns that exist only in the whitelist DB, created by `ensure_content_schema` and
# filled by `recompute-popularity.py`. The crawl DB never has them, so they belong in
# the exact check against `main.videos` but not in the superset check against
# `source.videos` or in the column list used to copy rows across.
WHITELIST_DERIVED_VIDEO_COLUMNS = ["popularity"]

EMBEDDING_COLUMNS = [
    "video_id",
    "instance_domain",
    "embedding",
    "embedding_dim",
    "model_name",
    "created_at",
]


def _table_exists(
    conn: sqlite3.Connection,
    table: str,
    schema: str | None = None,
) -> bool:
    """Handle table exists."""
    master = f"{schema}.sqlite_master" if schema else "sqlite_master"
    row = conn.execute(
        f"SELECT name FROM {master} WHERE type = 'table' AND name = ?;",
        (table,),
    ).fetchone()
    return bool(row)


def _table_columns(
    conn: sqlite3.Connection,
    table: str,
    schema: str | None = None,
) -> list[str]:
    """Handle table columns."""
    prefix = f"{schema}." if schema else ""
    return [row[1] for row in conn.execute(f"PRAGMA {prefix}table_info({table});")]


def _assert_columns_exact(
    conn: sqlite3.Connection,
    table: str,
    expected: list[str],
    schema: str | None = None,
) -> None:
    """Handle assert columns exact."""
    if not _table_exists(conn, table, schema=schema):
        raise RuntimeError(
            f"Missing table {schema + '.' if schema else ''}{table}."
        )
    actual = _table_columns(conn, table, schema=schema)
    missing = set(expected) - set(actual)
    extra = set(actual) - set(expected)
    if missing or extra:
        details: list[str] = []
        if missing:
            details.append(f"missing columns: {', '.join(sorted(missing))}")
        if extra:
            details.append(f"extra columns: {', '.join(sorted(extra))}")
        raise RuntimeError(
            "Schema mismatch for "
            f"{schema + '.' if schema else ''}{table} "
            f"({'; '.join(details)})."
        )


def _assert_columns_superset(
    conn: sqlite3.Connection,
    table: str,
    required: list[str],
    schema: str | None = None,
) -> None:
    """Handle assert columns superset."""
    if not _table_exists(conn, table, schema=schema):
        raise RuntimeError(
            f"Missing table {schema + '.' if schema else ''}{table}."
        )
    actual = _table_columns(conn, table, schema=schema)
    missing = set(required) - set(actual)
    if missing:
        raise RuntimeError(
            "Schema mismatch for "
            f"{schema + '.' if schema else ''}{table} "
            f"(missing columns: {', '.join(sorted(missing))})."
        )


def ensure_schema_compatibility(conn: sqlite3.Connection) -> None:
    """Handle ensure schema compatibility."""
    try:
        _assert_columns_exact(conn, TABLE_NAME, INSTANCE_COLUMNS)
        _assert_columns_exact(conn, "channels", CHANNEL_COLUMNS)
        _assert_columns_exact(
            conn, "videos", VIDEO_COLUMNS + WHITELIST_DERIVED_VIDEO_COLUMNS
        )
        _assert_columns_exact(conn, "video_embeddings", EMBEDDING_COLUMNS)
    except RuntimeError as exc:
        raise RuntimeError(
            f"{exc} Run `engine/server/db/jobs/migrate-whitelist.py` to migrate the whitelist DB."
        ) from exc

    try:
        _assert_columns_superset(
            conn,
            "channels",
            CHANNEL_COLUMNS,
            schema=SOURCE_SCHEMA,
        )
        _assert_columns_superset(
            conn,
            "videos",
            VIDEO_COLUMNS,
            schema=SOURCE_SCHEMA,
        )
    except RuntimeError as exc:
        raise RuntimeError(
            f"{exc} Update the crawl DB to match `engine/crawler/schema.sql` before syncing."
        ) from exc


def fetch_hosts(url: str) -> set[str]:
    """Handle fetch hosts."""
    request = Request(
        url,
        headers={"User-Agent": "peertube-graph-whitelist-sync/1.0"},
    )
    try:
        with urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except (HTTPError, URLError) as exc:
        raise RuntimeError(f"Failed to fetch whitelist from {url}: {exc}") from exc

    if isinstance(payload, dict) and "data" in payload:
        entries = payload["data"]
    elif isinstance(payload, list):
        entries = payload
    else:
        raise ValueError("Unexpected whitelist JSON shape.")

    hosts: set[str] = set()
    for entry in entries:
        host = entry.get("host") if isinstance(entry, dict) else entry
        if not host:
            continue
        host_value = normalize_host_token(str(host))
        if host_value:
            hosts.add(host_value)

    if not hosts:
        raise ValueError("Whitelist contained no hosts.")

    return hosts


def ensure_whitelist_schema(conn: sqlite3.Connection) -> None:
    """Handle ensure whitelist schema."""
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
          host TEXT PRIMARY KEY,
          health_status TEXT,
          health_checked_at INTEGER,
          health_error TEXT,
          last_error TEXT,
          last_error_at INTEGER,
          last_error_source TEXT
        );
        """
    )


VIDEOS_FTS_TRIGGERS_SQL = """
CREATE TRIGGER IF NOT EXISTS videos_fts_ai AFTER INSERT ON videos BEGIN
  INSERT INTO videos_fts (rowid, title, description, tags_json, category, channel_name)
  VALUES (new.rowid, new.title, new.description, new.tags_json, new.category, new.channel_name);
END;
CREATE TRIGGER IF NOT EXISTS videos_fts_ad AFTER DELETE ON videos BEGIN
  INSERT INTO videos_fts (videos_fts, rowid, title, description, tags_json, category, channel_name)
  VALUES ('delete', old.rowid, old.title, old.description, old.tags_json, old.category, old.channel_name);
END;
CREATE TRIGGER IF NOT EXISTS videos_fts_au AFTER UPDATE ON videos BEGIN
  INSERT INTO videos_fts (videos_fts, rowid, title, description, tags_json, category, channel_name)
  VALUES ('delete', old.rowid, old.title, old.description, old.tags_json, old.category, old.channel_name);
  INSERT INTO videos_fts (rowid, title, description, tags_json, category, channel_name)
  VALUES (new.rowid, new.title, new.description, new.tags_json, new.category, new.channel_name);
END;
"""

VIDEOS_FTS_DROP_TRIGGERS_SQL = """
DROP TRIGGER IF EXISTS videos_fts_ai;
DROP TRIGGER IF EXISTS videos_fts_ad;
DROP TRIGGER IF EXISTS videos_fts_au;
"""


def create_videos_fts_triggers(conn: sqlite3.Connection) -> None:
    """Create the triggers that keep videos_fts in step with videos."""
    conn.executescript(VIDEOS_FTS_TRIGGERS_SQL)


def drop_videos_fts_triggers(conn: sqlite3.Connection) -> None:
    """Drop the videos_fts triggers.

    Used around a bulk reload, where per-row trigger work is pure waste: the wholesale
    delete and re-insert would fire one index write per row in each direction, and the
    `rebuild` that follows discards all of it anyway.
    """
    conn.executescript(VIDEOS_FTS_DROP_TRIGGERS_SQL)


def rebuild_videos_fts(conn: sqlite3.Connection) -> int:
    """Rebuild videos_fts from its content table and return the indexed row count.

    This is the only way to recover an index that drifted while the triggers were absent:
    after a migration that dropped `videos`, after a bulk reload, or after a sync written
    by a version of this script that predates the index.

    :param conn: Connection to the whitelist database.
    :returns: Number of rows in the rebuilt index.
    """
    conn.execute("INSERT INTO videos_fts (videos_fts) VALUES ('rebuild');")
    return int(conn.execute("SELECT COUNT(*) FROM videos_fts").fetchone()[0])


def ensure_content_schema(conn: sqlite3.Connection) -> None:
    """Create the content tables, the full-text index and its synchronising triggers.

    `videos_fts` is an external-content index: it stores no second copy of the text, so
    the triggers below are what keep it in step with `videos`. They are not optional -
    the updater merge writes `videos` outside the sync stage, and without them the index
    silently drifts from the data.
    """
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS channels (
          channel_id TEXT NOT NULL,
          channel_name TEXT,
          display_name TEXT,
          instance_domain TEXT NOT NULL,
          videos_count INTEGER,
          followers_count INTEGER,
          avatar_url TEXT,
          health_status TEXT,
          health_checked_at INTEGER,
          health_error TEXT,
          channel_url TEXT,
          last_error TEXT,
          last_error_at INTEGER,
          last_error_source TEXT,
          PRIMARY KEY (channel_id, instance_domain)
        );
        CREATE TABLE IF NOT EXISTS videos (
          video_id TEXT NOT NULL,
          video_uuid TEXT,
          video_numeric_id INTEGER,
          instance_domain TEXT NOT NULL,
          channel_id TEXT,
          channel_name TEXT,
          channel_url TEXT,
          account_name TEXT,
          account_url TEXT,
          title TEXT,
          description TEXT,
          tags_json TEXT,
          category TEXT,
          published_at INTEGER,
          video_url TEXT,
          duration INTEGER,
          thumbnail_url TEXT,
          embed_path TEXT,
          views INTEGER,
          likes INTEGER,
          dislikes INTEGER,
          comments_count INTEGER,
          nsfw INTEGER,
          preview_path TEXT,
          popularity REAL NOT NULL DEFAULT 0,
          last_checked_at INTEGER NOT NULL,
          last_error TEXT,
          last_error_at INTEGER,
          error_count INTEGER NOT NULL DEFAULT 0,
          invalid_reason TEXT,
          invalid_at INTEGER,
          PRIMARY KEY (video_id, instance_domain)
        );
        CREATE TABLE IF NOT EXISTS video_embeddings (
          video_id TEXT NOT NULL,
          instance_domain TEXT NOT NULL,
          embedding BLOB NOT NULL,
          embedding_dim INTEGER NOT NULL,
          model_name TEXT NOT NULL,
          created_at TEXT NOT NULL,
          PRIMARY KEY (video_id, instance_domain),
          FOREIGN KEY (video_id, instance_domain) REFERENCES videos (video_id, instance_domain)
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS videos_fts USING fts5(
          title,
          description,
          tags_json,
          category,
          channel_name,
          content='videos',
          content_rowid='rowid'
        );
        CREATE INDEX IF NOT EXISTS idx_videos_published
          ON videos (published_at DESC, video_id DESC);
        CREATE INDEX IF NOT EXISTS idx_videos_popularity
          ON videos (popularity DESC);
        CREATE INDEX IF NOT EXISTS idx_channels_followers_videos_name
          ON channels (followers_count DESC, videos_count DESC, channel_name ASC);
        CREATE INDEX IF NOT EXISTS idx_channels_videos
          ON channels (videos_count DESC);
        CREATE INDEX IF NOT EXISTS idx_channels_name
          ON channels (channel_name);
        CREATE INDEX IF NOT EXISTS idx_channels_instance
          ON channels (instance_domain);
        """
    )
    create_videos_fts_triggers(conn)


def sync_hosts(conn: sqlite3.Connection, hosts: set[str]) -> tuple[int, int]:
    """Handle sync hosts."""
    existing = {row[0] for row in conn.execute(f"SELECT host FROM {TABLE_NAME}")}
    added = hosts - existing
    to_delete = existing - hosts
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

    conn.executemany(
        f"""
        INSERT INTO {TABLE_NAME} (host, health_status, health_checked_at, health_error)
        VALUES (?, 'ok', ?, NULL)
        ON CONFLICT(host)
        DO UPDATE SET
          health_status = excluded.health_status,
          health_checked_at = excluded.health_checked_at,
          health_error = NULL;
        """,
        [(host, now_ms) for host in hosts],
    )
    if to_delete:
        conn.executemany(
            f"DELETE FROM {TABLE_NAME} WHERE host = ?;",
            [(host,) for host in to_delete],
        )

    return len(hosts), len(to_delete), len(added)


def rebuild_content_tables(
    conn: sqlite3.Connection,
    hosts: set[str],
) -> tuple[int, int, int]:
    """Handle rebuild content tables."""
    # The triggers are per-row and this is a wholesale reload; the rebuild at the end
    # produces the same index for a fraction of the work.
    drop_videos_fts_triggers(conn)

    conn.execute("DELETE FROM video_embeddings;")
    conn.execute("DELETE FROM videos;")
    conn.execute("DELETE FROM channels;")

    if not hosts:
        create_videos_fts_triggers(conn)
        rebuild_videos_fts(conn)
        return 0, 0, 0

    channel_columns = ", ".join(CHANNEL_COLUMNS)
    host_placeholders = ", ".join(["?"] * len(hosts))
    conn.execute(
        f"""
        INSERT INTO channels ({channel_columns})
        SELECT {channel_columns}
        FROM {SOURCE_SCHEMA}.channels
        WHERE instance_domain IN ({host_placeholders});
        """,
        tuple(hosts),
    )

    video_columns = ", ".join(VIDEO_COLUMNS)
    conn.execute(
        f"""
        INSERT INTO videos ({video_columns})
        SELECT {video_columns}
        FROM {SOURCE_SCHEMA}.videos
        WHERE instance_domain IN ({host_placeholders})
          AND (channel_id, instance_domain) IN (
            SELECT channel_id, instance_domain FROM channels
          );
        """,
        tuple(hosts),
    )

    source_embedding_columns = {
        row[1]
        for row in conn.execute(
            f"PRAGMA {SOURCE_SCHEMA}.table_info(video_embeddings)"
        ).fetchall()
    }
    if source_embedding_columns.issuperset(EMBEDDING_COLUMNS):
        embedding_columns = ", ".join(EMBEDDING_COLUMNS)
        conn.execute(
            f"""
            INSERT INTO video_embeddings ({embedding_columns})
            SELECT {embedding_columns}
            FROM {SOURCE_SCHEMA}.video_embeddings
            WHERE (video_id, instance_domain) IN (
              SELECT video_id, instance_domain FROM videos
            );
            """
        )

    # Rebuilt inside the caller's transaction, after every writer to `videos` has run.
    create_videos_fts_triggers(conn)
    fts_count = rebuild_videos_fts(conn)
    channels_count = conn.execute("SELECT COUNT(*) FROM channels").fetchone()[0]
    videos_count = conn.execute("SELECT COUNT(*) FROM videos").fetchone()[0]
    embeddings_count = conn.execute("SELECT COUNT(*) FROM video_embeddings").fetchone()[0]
    if fts_count != videos_count:
        raise RuntimeError(
            f"videos_fts holds {fts_count} rows but videos holds {videos_count}; "
            "the full-text index did not rebuild cleanly."
        )
    return channels_count, videos_count, embeddings_count


def parse_args() -> argparse.Namespace:
    """Handle parse args."""
    parser = argparse.ArgumentParser(
        description=(
            "Synchronize the PeerTube instance whitelist into a dedicated database."
        ),
        formatter_class=CompactHelpFormatter,
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_URL,
        help="Whitelist JSON URL.",
    )
    parser.add_argument(
        "--db",
        "--source-db",
        dest="source_db",
        type=Path,
        default=DEFAULT_SOURCE_DB_PATH,
        help="Path to the main crawl database.",
    )
    parser.add_argument(
        "--output-db",
        "--whitelist-db",
        dest="whitelist_db",
        type=Path,
        default=DEFAULT_WHITELIST_DB_PATH,
        help="Path to the output database.",
    )
    parser.add_argument(
        "--mode",
        choices=MODES,
        default="include",
        help=(
            "include: build whitelist.db from hosts in the remote whitelist; "
            "exclude: build whitelist.db from hosts missing in the remote whitelist."
        ),
    )
    return parser.parse_args()


def main() -> None:
    """Handle main."""
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    remote_hosts = fetch_hosts(args.url)

    source_hosts: set[str] = set()
    selected_hosts: set[str] = set()
    selected_hosts_before_deny: set[str] = set()
    denylisted_hosts: set[str] = set()
    denylisted_skipped = 0
    denylisted_purged = 0
    total = 0
    removed = 0
    added = 0
    conn = sqlite3.connect(args.whitelist_db.as_posix())
    # data.moderation reads its rows by column name, as the API server's connections
    # do; without this the denylist lookup raises TypeError on a tuple row.
    conn.row_factory = sqlite3.Row
    attached = False
    try:
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute(
            "ATTACH DATABASE ? AS source;",
            (args.source_db.as_posix(),),
        )
        attached = True
        with conn:
            ensure_moderation_schema(conn)
            ensure_whitelist_schema(conn)
            ensure_content_schema(conn)
            ensure_schema_compatibility(conn)
            denylisted_hosts = list_active_denied_hosts(conn)
            source_hosts = {
                row[0]
                for row in conn.execute(
                    f"SELECT DISTINCT instance_domain FROM {SOURCE_SCHEMA}.videos"
                )
            }
            if args.mode == "exclude":
                selected_hosts_before_deny = source_hosts - remote_hosts
            else:
                selected_hosts_before_deny = remote_hosts
            if denylisted_hosts:
                selected_hosts = selected_hosts_before_deny - denylisted_hosts
                denylisted_skipped = len(selected_hosts_before_deny - selected_hosts)
                placeholders = ", ".join(["?"] * len(denylisted_hosts))
                denylisted_purged += int(
                    conn.execute(
                        f"SELECT COUNT(*) FROM channels WHERE instance_domain IN ({placeholders})",
                        tuple(sorted(denylisted_hosts)),
                    ).fetchone()[0]
                )
                denylisted_purged += int(
                    conn.execute(
                        f"SELECT COUNT(*) FROM videos WHERE instance_domain IN ({placeholders})",
                        tuple(sorted(denylisted_hosts)),
                    ).fetchone()[0]
                )
                denylisted_purged += int(
                    conn.execute(
                        f"SELECT COUNT(*) FROM video_embeddings WHERE instance_domain IN ({placeholders})",
                        tuple(sorted(denylisted_hosts)),
                    ).fetchone()[0]
                )
                denylisted_purged += int(
                    conn.execute(
                        f"SELECT COUNT(*) FROM {TABLE_NAME} WHERE host IN ({placeholders})",
                        tuple(sorted(denylisted_hosts)),
                    ).fetchone()[0]
                )
            else:
                selected_hosts = selected_hosts_before_deny
            total, removed, added = sync_hosts(conn, selected_hosts)
            channels_count, videos_count, embeddings_count = rebuild_content_tables(
                conn, selected_hosts
            )
    finally:
        if attached:
            conn.execute("DETACH DATABASE source;")
        conn.close()

    logging.info(
        "Whitelist mode=%s remote_hosts=%d source_hosts=%d selected_hosts=%d",
        args.mode,
        len(remote_hosts),
        len(source_hosts),
        len(selected_hosts),
    )
    logging.info(
        "Denylist integration: active=%d denylisted_skipped=%d denylisted_purged=%d",
        len(denylisted_hosts),
        denylisted_skipped,
        denylisted_purged,
    )
    logging.info(
        "Whitelist synced: %s entries, %s added, %s removed.",
        total,
        added,
        removed,
    )
    logging.info(
        "Whitelist DB updated: %s channels, %s videos, %s embeddings.",
        channels_count,
        videos_count,
        embeddings_count,
    )


if __name__ == "__main__":
    main()
