"""Provide moderation runtime helpers."""

from __future__ import annotations

# Shared moderation primitives for deny/block/ignore flows.
#
# This module centralizes:
# - moderation schema creation,
# - host normalization (normalize_host for operator input, normalize_host_token for hosts-list entries, a port of the crawler's normalizeHostToken),
# - serving-time row filtering (denylist + blocked channels),
# - purge helpers for host-linked rows in main/similarity databases.


import ipaddress
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlparse

from data.similarity_cache import pack_neighbours, unpack_neighbours

URL_SCHEME_PREFIXES = ("http://", "https://")


@dataclass(frozen=True)
class ModerationFilterStats:
    """Counters for serving-time moderation filtering."""

    filtered_by_denylist: int = 0
    filtered_by_blocked_channel: int = 0

    @property
    def total_filtered(self) -> int:
        """Handle total filtered."""
        return self.filtered_by_denylist + self.filtered_by_blocked_channel


def now_ms() -> int:
    """Return current UTC epoch time in milliseconds."""
    return int(datetime.now(timezone.utc).timestamp() * 1000)


# Part of the ANN id contract (data/ann_ids.compute_ann_id): any change to this output re-keys every stored ann_id.
def normalize_host(value: str | None) -> str | None:
    """Normalize host input (lower, strip protocol/path, trim dots/spaces)."""
    if value is None:
        return None
    raw = str(value).strip().lower()
    if not raw:
        return None

    candidate = raw
    if "://" not in candidate:
        candidate = f"https://{candidate}"
    try:
        parsed = urlparse(candidate)
    except ValueError:
        return None
    host = (parsed.hostname or "").strip().lower()
    if not host:
        return None
    host = host.strip(".")
    if not host:
        return None
    # Reject clearly invalid hosts.
    if re.search(r"\s", host):
        return None
    return host


def normalize_host_token(value: str) -> str | None:
    """Normalize a hosts-list entry exactly as the crawler's normalizeHostToken (engine/crawler/src/host-filters.ts) does; unlike normalize_host, bare entries keep ports and URL entries yield the WHATWG hostname."""
    raw = value.strip().lower()
    if not raw:
        return None
    # One except stands in for the crawler's whole-body try/catch: urlsplit, .port, ipaddress and the idna codec all raise ValueError subclasses.
    try:
        if raw.startswith(URL_SCHEME_PREFIXES):
            return _whatwg_hostname(raw)
        if "/" in raw:
            return _whatwg_hostname(f"https://{raw}")
        return raw.strip(".") or None
    except ValueError:
        return None


def _whatwg_hostname(url: str) -> str | None:
    """Handle the hostname WHATWG URL.hostname returns for url; raise ValueError where WHATWG throws."""
    # rat-tail: urlparse accepts hosts WHATWG rejects (forbidden code points such as space, <, >, ^), so parity holds only on the pinned fixture inputs; upgrade with a module-level forbidden-code-point set checked here once a fixture input exposes the gap.
    parsed = urlparse(url)
    # Reading .port raises ValueError on a non-numeric or out-of-range port, which WHATWG also rejects.
    _ = parsed.port
    host = parsed.hostname or ""
    if not host:
        return None
    # .hostname never keeps the port, so a colon means an IPv6 literal, whose brackets WHATWG keeps.
    if ":" in host:
        return f"[{ipaddress.IPv6Address(host).compressed}]"
    # ASCII hosts skip the idna codec, which rejects empty and over-long labels that WHATWG accepts.
    if not host.isascii():
        host = host.encode("idna").decode("ascii")
    return host


def ensure_moderation_schema(conn: sqlite3.Connection) -> None:
    """Create moderation tables used by denylist and channel blocking flows."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS instance_denylist (
          host TEXT PRIMARY KEY,
          is_active INTEGER NOT NULL DEFAULT 1,
          reason TEXT,
          note TEXT,
          created_at INTEGER NOT NULL,
          updated_at INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_instance_denylist_active
          ON instance_denylist (is_active, host);

        CREATE TABLE IF NOT EXISTS channel_moderation (
          channel_id TEXT NOT NULL,
          instance_domain TEXT NOT NULL,
          status TEXT NOT NULL CHECK(status IN ('blocked', 'allowed')),
          reason TEXT,
          source_video_url TEXT,
          updated_at INTEGER NOT NULL,
          created_at INTEGER NOT NULL,
          PRIMARY KEY (channel_id, instance_domain)
        );
        CREATE INDEX IF NOT EXISTS idx_channel_moderation_status_instance
          ON channel_moderation (status, instance_domain);
        """
    )


def list_active_denied_hosts(conn: sqlite3.Connection) -> set[str]:
    """Return active deny hosts from canonical denylist."""
    denied: set[str] = set()
    if _table_exists(conn, "instance_denylist"):
        rows = conn.execute(
            "SELECT host FROM instance_denylist WHERE is_active = 1"
        ).fetchall()
        denied.update(_row_value(rows, "host"))
    return {host.lower() for host in denied if isinstance(host, str) and host}


def filter_rows_by_moderation(
    conn: sqlite3.Connection,
    rows: list[dict[str, object]],
    *,
    apply_instance_filter: bool = True,
    apply_channel_filter: bool = True,
) -> tuple[list[dict[str, object]], ModerationFilterStats]:
    """Filter API output rows by denylisted hosts and blocked channels."""
    if not rows:
        return rows, ModerationFilterStats()

    hosts: set[str] = set()
    channel_pairs: set[tuple[str, str]] = set()
    for row in rows:
        host = _row_host(row)
        if host:
            hosts.add(host)
        channel_id = _row_channel_id(row)
        if host and channel_id:
            channel_pairs.add((channel_id, host))

    denied_hosts = _lookup_denied_hosts(conn, hosts) if apply_instance_filter else set()
    blocked_channels = (
        _lookup_blocked_channels(conn, channel_pairs) if apply_channel_filter else set()
    )

    filtered: list[dict[str, object]] = []
    deny_count = 0
    blocked_count = 0
    for row in rows:
        host = _row_host(row)
        if host and host in denied_hosts:
            deny_count += 1
            continue
        channel_id = _row_channel_id(row)
        if host and channel_id and (channel_id, host) in blocked_channels:
            blocked_count += 1
            continue
        filtered.append(row)

    return filtered, ModerationFilterStats(
        filtered_by_denylist=deny_count,
        filtered_by_blocked_channel=blocked_count,
    )


def purge_host_data(
    conn: sqlite3.Connection,
    host: str,
    *,
    dry_run: bool = False,
    precomputed_counts: dict[str, int] | None = None,
) -> dict[str, int]:
    """Delete host-linked rows from the main DB and return per-table counters."""
    normalized = normalize_host(host)
    if not normalized:
        raise ValueError(f"Invalid host: {host}")

    table_column_pairs = _host_table_column_pairs()
    counts: dict[str, int]
    if precomputed_counts is None:
        counts = _count_host_rows(conn, normalized, table_column_pairs)
    else:
        counts = {
            table: int(precomputed_counts.get(table, 0))
            for table, _ in table_column_pairs
            if _table_exists(conn, table)
        }

    if dry_run:
        return counts

    with conn:
        for table, column in table_column_pairs:
            if not _table_exists(conn, table):
                continue
            conn.execute(
                f"DELETE FROM {table} WHERE {column} = ?",
                (normalized,),
            )
    return counts


def purge_similarity_for_host(
    conn: sqlite3.Connection,
    host: str,
    *,
    dry_run: bool = False,
    precomputed_counts: dict[str, int] | None = None,
) -> dict[str, int]:
    """Remove host's sources and its videos from every other source's neighbours; return the source-neighbour pairs and sources removed."""
    normalized = normalize_host(host)
    if not normalized:
        raise ValueError(f"Invalid host: {host}")

    with conn:
        stats = _host_similarity_pass(conn, normalized, apply=not dry_run)
    if precomputed_counts is not None:
        return {
            "similarity_items": int(precomputed_counts.get("similarity_items", 0)),
            "similarity_sources": int(precomputed_counts.get("similarity_sources", 0)),
        }
    return {
        "similarity_items": stats["similarity_items"],
        "similarity_sources": stats["similarity_sources"],
    }


def collect_similarity_host_stats(
    conn: sqlite3.Connection, host: str
) -> dict[str, int]:
    """Return a host's similarity stats: neighbours of its sources, its videos as neighbours elsewhere, and the pairs a purge removes."""
    normalized = normalize_host(host)
    if not normalized:
        raise ValueError(f"Invalid host: {host}")
    return _host_similarity_pass(conn, normalized, apply=False)


def _host_similarity_pass(
    conn: sqlite3.Connection, host: str, *, apply: bool
) -> dict[str, int]:
    """Count, and with apply remove, host's sources, its videos inside other sources' neighbours, and its video_keys rows.

    A pair whose source and neighbour are both on host counts once in similarity_items and in both as_ buckets, as the legacy row purge did.
    """
    stats = {
        "similarity_items": 0,
        "similarity_sources": 0,
        "similarity_items_as_source": 0,
        "similarity_items_as_similar": 0,
        "similarity_items_total_mentions": 0,
    }
    keys = {row[0] for row in conn.execute("SELECT key FROM video_keys WHERE instance_domain = ?", (host,))}
    if not keys:
        return stats
    # rat-tail: one full scan of similarity_sources per host that still has keys; a key -> sources index if live-host purges become frequent.
    # fetchall: the loop rewrites the table it reads.
    for source_key, blob in conn.execute("SELECT source_key, neighbours FROM similarity_sources").fetchall():
        pairs = unpack_neighbours(blob)
        hits = sum(1 for key, _ in pairs if key in keys)
        stats["similarity_items_as_similar"] += hits
        if source_key in keys:
            stats["similarity_sources"] += 1
            stats["similarity_items_as_source"] += len(pairs)
            stats["similarity_items"] += len(pairs)
            if apply:
                conn.execute("DELETE FROM similarity_sources WHERE source_key = ?", (source_key,))
        elif hits:
            stats["similarity_items"] += hits
            if apply:
                kept = pack_neighbours(pair for pair in pairs if pair[0] not in keys)
                conn.execute("UPDATE similarity_sources SET neighbours = ? WHERE source_key = ?", (kept, source_key))
    if apply:
        conn.execute("DELETE FROM video_keys WHERE instance_domain = ?", (host,))
    stats["similarity_items_total_mentions"] = (
        stats["similarity_items_as_source"] + stats["similarity_items_as_similar"]
    )
    return stats


def _host_table_column_pairs() -> list[tuple[str, str]]:
    """Handle host table column pairs."""
    return [
        ("video_embeddings", "instance_domain"),
        ("videos", "instance_domain"),
        ("channels", "instance_domain"),
        ("instances", "host"),
        ("video_crawl_progress", "instance_domain"),
        ("channel_crawl_progress", "instance_domain"),
        ("instance_crawl_progress", "host"),
    ]


def _count_host_rows(
    conn: sqlite3.Connection,
    normalized_host: str,
    table_column_pairs: list[tuple[str, str]],
) -> dict[str, int]:
    """Handle count host rows."""
    counts: dict[str, int] = {}
    for table, column in table_column_pairs:
        if not _table_exists(conn, table):
            continue
        counts[table] = int(
            conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE {column} = ?",
                (normalized_host,),
            ).fetchone()[0]
        )
    return counts


def _lookup_denied_hosts(
    conn: sqlite3.Connection, hosts: set[str]
) -> set[str]:
    """Handle lookup denied hosts."""
    if not hosts:
        return set()

    placeholders = ", ".join(["?"] * len(hosts))
    params = tuple(sorted(hosts))
    denied: set[str] = set()

    if _table_exists(conn, "instance_denylist"):
        rows = conn.execute(
            f"""
            SELECT host
            FROM instance_denylist
            WHERE is_active = 1
              AND host IN ({placeholders})
            """,
            params,
        ).fetchall()
        denied.update(_row_value(rows, "host"))
    return {host.lower() for host in denied if isinstance(host, str) and host}


def _lookup_blocked_channels(
    conn: sqlite3.Connection,
    pairs: set[tuple[str, str]],
) -> set[tuple[str, str]]:
    """Handle lookup blocked channels."""
    if not pairs or not _table_exists(conn, "channel_moderation"):
        return set()

    conditions = " OR ".join(
        ["(channel_id = ? AND instance_domain = ?)"] * len(pairs)
    )
    params: list[str] = []
    for channel_id, host in sorted(pairs):
        params.extend([channel_id, host])
    rows = conn.execute(
        f"""
        SELECT channel_id, instance_domain
        FROM channel_moderation
        WHERE status = 'blocked'
          AND ({conditions})
        """,
        params,
    ).fetchall()
    return {
        (str(row["channel_id"]), str(row["instance_domain"]).lower()) for row in rows
    }


def _row_host(row: dict[str, object]) -> str | None:
    """Handle row host."""
    raw = row.get("instance_domain")
    if raw is None:
        raw = row.get("instanceDomain")
    if not isinstance(raw, str):
        return None
    normalized = normalize_host(raw)
    return normalized


def _row_channel_id(row: dict[str, object]) -> str | None:
    """Handle row channel id."""
    raw = row.get("channel_id")
    if raw is None:
        raw = row.get("channelId")
    if isinstance(raw, str) and raw:
        return raw
    return None


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    """Handle table exists."""
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def _row_value(rows: list[sqlite3.Row], key: str) -> set[object]:
    """Handle row value."""
    values: set[object] = set()
    for row in rows:
        values.add(row[key])
    return values
