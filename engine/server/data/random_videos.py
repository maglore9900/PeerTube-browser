"""Provide random videos runtime helpers."""

from __future__ import annotations

import base64
import json
import sqlite3
import time
from typing import Any

from data.metadata import NSFW_ALLOWED_SQL, fetch_metadata
from data.random_cache import fetch_random_ann_ids

# Filter-on draws per request before a short Random page is returned as is; the cache holds no NSFW flag, so allowed rows are found by redrawing.
RANDOM_CACHE_NSFW_MAX_DRAWS = 4
# video_id then instance_domain close every order, so rows equal on the other keys still sort one way and an OFFSET page never repeats or skips one.
ORDERED_FEED_ORDER_BY = {
    "trending": """
    t.rank ASC,
    t.likes DESC,
    t.views DESC,
    t.video_id DESC,
    t.instance_domain DESC
""",
    "popular": """
    v.likes DESC,
    v.views DESC,
    v.video_id DESC,
    v.instance_domain DESC
""",
    "recent": """
    v.published_at DESC,
    v.video_id DESC,
    v.instance_domain DESC
""",
}
# The rows an order walks before joining videos: trending drives from its ranks index (CROSS JOIN fixes the join order), so only listed catalogue rows are read, already in order, and an OFFSET walk stops early.
ORDERED_FEED_SOURCE = {
    "trending": """trending_ranks t
        CROSS JOIN video_embeddings e
          ON e.video_id = t.video_id AND e.instance_domain = t.instance_domain""",
    "popular": "video_embeddings e",
    "recent": "video_embeddings e",
}
# The select list `_ordered_row` reads, over videos v, video_embeddings e and channels c.
ORDERED_COLUMNS = """v.video_id,
          v.video_uuid,
          v.video_numeric_id,
          v.instance_domain,
          v.channel_id,
          v.channel_name,
          v.channel_url,
          c.display_name AS channel_display_name,
          c.avatar_url AS channel_avatar_url,
          v.account_name,
          v.account_url,
          v.title,
          v.description,
          v.tags_json,
          v.category,
          v.published_at,
          v.video_url,
          v.duration,
          v.thumbnail_url,
          v.embed_path,
          v.views,
          v.likes,
          v.dislikes,
          v.comments_count,
          v.nsfw,
          v.preview_path,
          v.popularity,
          v.last_checked_at,
          e.embedding_dim,
          e.model_name"""
# SQLite's cap on terms in one compound SELECT (SQLITE_MAX_COMPOUND_SELECT, observed: 501 raises under the Engine's 3.53); a full batch binds about 4,500 parameters, which needs SQLite 3.32+ (999 before).
FOLLOWED_TERMS_PER_STATEMENT = 500


def _listing_conditions(error_threshold: int | None, include_nsfw: bool) -> tuple[list[str], list[Any]]:
    """Return the WHERE conditions every listing query shares and their params: the error threshold, then the NSFW filter when it is on."""
    conditions: list[str] = []
    params: list[Any] = []
    if error_threshold is not None and error_threshold > 0:
        conditions.append("(v.error_count IS NULL OR v.error_count < ?)")
        params.append(error_threshold)
    if not include_nsfw:
        conditions.append(NSFW_ALLOWED_SQL)
    return conditions, params


def fetch_random_rows(
    conn: sqlite3.Connection, limit: int, error_threshold: int | None = None, include_nsfw: bool = True
) -> list[dict[str, Any]]:
    """Return random video rows for fallback."""
    conditions, params = _listing_conditions(error_threshold, include_nsfw)
    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    params.append(limit)
    query = conn.execute(
        f"""
        SELECT
          v.video_id,
          v.video_uuid,
          v.video_numeric_id,
          v.instance_domain,
          v.channel_id,
          v.channel_name,
          v.channel_url,
          c.display_name AS channel_display_name,
          c.avatar_url AS channel_avatar_url,
          v.account_name,
          v.account_url,
          v.title,
          v.description,
          v.tags_json,
          v.category,
          v.published_at,
          v.video_url,
          v.duration,
          v.thumbnail_url,
          v.embed_path,
          v.views,
          v.likes,
          v.dislikes,
          v.comments_count,
          v.nsfw,
          v.preview_path,
          v.popularity,
          v.last_checked_at,
          e.embedding_dim,
          e.model_name
        FROM video_embeddings e
        JOIN videos v
          ON v.video_id = e.video_id AND v.instance_domain = e.instance_domain
        LEFT JOIN channels c
          ON c.channel_id = v.channel_id AND c.instance_domain = v.instance_domain
        {where_clause}
        ORDER BY RANDOM()
        LIMIT ?
        """,
        params,
    )
    rows = []
    for row in query:
        rows.append(
            {
                "video_id": row["video_id"],
                "video_uuid": row["video_uuid"],
                "video_numeric_id": row["video_numeric_id"],
                "instance_domain": row["instance_domain"],
                "channel_id": row["channel_id"],
                "channel_name": row["channel_name"],
                "channel_url": row["channel_url"],
                "channel_display_name": row["channel_display_name"],
                "channel_avatar_url": row["channel_avatar_url"],
                "account_name": row["account_name"],
                "account_url": row["account_url"],
                "title": row["title"],
                "description": row["description"],
                "tags_json": row["tags_json"],
                "category": row["category"],
                "published_at": row["published_at"],
                "video_url": row["video_url"],
                "duration": row["duration"],
                "thumbnail_url": row["thumbnail_url"],
                "embed_path": row["embed_path"],
                "views": row["views"],
                "likes": row["likes"],
                "dislikes": row["dislikes"],
                "comments_count": row["comments_count"],
                "nsfw": row["nsfw"],
                "preview_path": row["preview_path"],
                "last_checked_at": row["last_checked_at"],
                "embedding_dim": row["embedding_dim"],
                "model_name": row["model_name"],
            }
        )
    return rows


def fetch_recent_videos(
    conn: sqlite3.Connection, limit: int, error_threshold: int | None = None, include_nsfw: bool = True
) -> list[dict[str, Any]]:
    """Return most recently published videos."""
    conditions, params = _listing_conditions(error_threshold, include_nsfw)
    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    params.append(limit)
    query = conn.execute(
        f"""
        SELECT
          v.video_id,
          v.video_uuid,
          v.video_numeric_id,
          v.instance_domain,
          v.channel_id,
          v.channel_name,
          v.channel_url,
          c.display_name AS channel_display_name,
          c.avatar_url AS channel_avatar_url,
          v.account_name,
          v.account_url,
          v.title,
          v.description,
          v.tags_json,
          v.category,
          v.published_at,
          v.video_url,
          v.duration,
          v.thumbnail_url,
          v.embed_path,
          v.views,
          v.likes,
          v.dislikes,
          v.comments_count,
          v.nsfw,
          v.preview_path,
          v.last_checked_at,
          e.embedding_dim,
          e.model_name
        FROM video_embeddings e
        JOIN videos v
          ON v.video_id = e.video_id AND v.instance_domain = e.instance_domain
        LEFT JOIN channels c
          ON c.channel_id = v.channel_id AND c.instance_domain = v.instance_domain
        {where_clause}
        ORDER BY v.published_at DESC, v.video_id DESC
        LIMIT ?
        """,
        params,
    )
    rows = []
    for row in query:
        rows.append(
            {
                "video_id": row["video_id"],
                "video_uuid": row["video_uuid"],
                "video_numeric_id": row["video_numeric_id"],
                "instance_domain": row["instance_domain"],
                "channel_id": row["channel_id"],
                "channel_name": row["channel_name"],
                "channel_url": row["channel_url"],
                "channel_display_name": row["channel_display_name"],
                "channel_avatar_url": row["channel_avatar_url"],
                "account_name": row["account_name"],
                "account_url": row["account_url"],
                "title": row["title"],
                "description": row["description"],
                "tags_json": row["tags_json"],
                "category": row["category"],
                "published_at": row["published_at"],
                "video_url": row["video_url"],
                "duration": row["duration"],
                "thumbnail_url": row["thumbnail_url"],
                "embed_path": row["embed_path"],
                "views": row["views"],
                "likes": row["likes"],
                "dislikes": row["dislikes"],
                "comments_count": row["comments_count"],
                "nsfw": row["nsfw"],
                "preview_path": row["preview_path"],
                "last_checked_at": row["last_checked_at"],
                "embedding_dim": row["embedding_dim"],
                "model_name": row["model_name"],
            }
        )
    return rows


def fetch_popular_videos(
    conn: sqlite3.Connection, limit: int, error_threshold: int | None = None, include_nsfw: bool = True
) -> list[dict[str, Any]]:
    """Return the popular layer's pool: the head of the Trending order under the same filters, empty while trending_ranks is."""
    return fetch_ordered_page(conn, "trending", limit, 0, error_threshold=error_threshold, include_nsfw=include_nsfw)


def _ordered_row(row: sqlite3.Row) -> dict[str, Any]:
    """Return one `ORDERED_COLUMNS` row as the dict every ordered listing serves."""
    return {
        "video_id": row["video_id"],
        "video_uuid": row["video_uuid"],
        "video_numeric_id": row["video_numeric_id"],
        "instance_domain": row["instance_domain"],
        "channel_id": row["channel_id"],
        "channel_name": row["channel_name"],
        "channel_url": row["channel_url"],
        "channel_display_name": row["channel_display_name"],
        "channel_avatar_url": row["channel_avatar_url"],
        "account_name": row["account_name"],
        "account_url": row["account_url"],
        "title": row["title"],
        "description": row["description"],
        "tags_json": row["tags_json"],
        "category": row["category"],
        "published_at": row["published_at"],
        "video_url": row["video_url"],
        "duration": row["duration"],
        "thumbnail_url": row["thumbnail_url"],
        "embed_path": row["embed_path"],
        "views": row["views"],
        "likes": row["likes"],
        "dislikes": row["dislikes"],
        "comments_count": row["comments_count"],
        "nsfw": row["nsfw"],
        "preview_path": row["preview_path"],
        "popularity": row["popularity"],
        "last_checked_at": row["last_checked_at"],
        "embedding_dim": row["embedding_dim"],
        "model_name": row["model_name"],
    }


def fetch_ordered_page(
    conn: sqlite3.Connection, order: str, limit: int, offset: int, error_threshold: int | None = None, include_nsfw: bool = True
) -> list[dict[str, Any]]:
    """Return one page of embedded videos in a global feed order."""
    order_by = ORDERED_FEED_ORDER_BY[order]
    source = ORDERED_FEED_SOURCE[order]
    conditions, params = _listing_conditions(error_threshold, include_nsfw)
    if order == "recent":
        # published_at is epoch milliseconds; an undated or future-dated video has no place in a recency order.
        conditions.append("v.published_at IS NOT NULL AND v.published_at <= ?")
        params.append(int(time.time() * 1000))
    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    params += [limit, offset]
    query = conn.execute(
        f"""
        SELECT
          {ORDERED_COLUMNS}
        FROM {source}
        JOIN videos v
          ON v.video_id = e.video_id AND v.instance_domain = e.instance_domain
        LEFT JOIN channels c
          ON c.channel_id = v.channel_id AND c.instance_domain = v.instance_domain
        {where_clause}
        ORDER BY {order_by}
        LIMIT ? OFFSET ?
        """,
        params,
    )
    return [_ordered_row(row) for row in query]


def encode_followed_cursor(row: dict[str, Any]) -> str:
    """Return the opaque cursor that resumes the Following order strictly after `row`."""
    raw = json.dumps([row["published_at"], row["video_id"], row["instance_domain"]], separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")


def decode_followed_cursor(value: Any) -> tuple[int, str, str]:
    """Return the (published_at, video_id, instance_domain) a Following cursor names.

    :raises ValueError: For anything `encode_followed_cursor` could not have made.
    """
    if not isinstance(value, str) or not value:
        raise ValueError("Invalid cursor")
    try:
        # validate=True refuses characters outside base64url, which the default decode silently drops.
        decoded = json.loads(base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True))
    except ValueError as exc:
        raise ValueError("Invalid cursor") from exc
    if not isinstance(decoded, list) or len(decoded) != 3 or type(decoded[0]) is not int or not isinstance(decoded[1], str) or not isinstance(decoded[2], str):
        raise ValueError("Invalid cursor")
    return decoded[0], decoded[1], decoded[2]


def fetch_followed_page(
    conn: sqlite3.Connection,
    channels: list[tuple[str, str]],
    accounts: list[str],
    cursor: tuple[int, str, str] | None,
    limit: int,
    error_threshold: int | None = None,
    include_nsfw: bool = True,
) -> tuple[list[dict[str, Any]], str | None]:
    """Return the next page of embedded videos from the followed channels and accounts, newest first, and the cursor of the page after it.

    Each source is one UNION ALL term that seeks its own recency index and reads at most `limit` rows past the cursor, so a quiet source or the last page costs a few index steps. The cursor is issued only when the page is full; a short page means nothing is left.
    """
    sources: list[tuple[str, list[Any]]] = [("v.instance_domain = ? AND v.channel_id = ?", [host, channel_id]) for host, channel_id in channels]
    sources += [("v.account_url = ?", [account_url]) for account_url in accounts]
    if limit <= 0 or not sources:
        return [], None
    conditions, shared = _listing_conditions(error_threshold, include_nsfw)
    # published_at is epoch milliseconds; as in recent, an undated or future-dated video has no place in the order or the cursor.
    conditions.append("v.published_at IS NOT NULL AND v.published_at <= ?")
    shared.append(int(time.time() * 1000))
    if cursor is not None:
        published_at, video_id, instance_domain = cursor
        # The two-column bound is a range on both indexes; the three-column one breaks a (published_at, video_id) tie across instances.
        conditions.append("(v.published_at, v.video_id) <= (?, ?) AND (v.published_at, v.video_id, v.instance_domain) < (?, ?, ?)")
        shared += [published_at, video_id, published_at, video_id, instance_domain]
    where = " AND ".join(conditions)
    rows: list[dict[str, Any]] = []
    for start in range(0, len(sources), FOLLOWED_TERMS_PER_STATEMENT):
        terms: list[str] = []
        params: list[Any] = []
        for predicate, source_params in sources[start:start + FOLLOWED_TERMS_PER_STATEMENT]:
            # CROSS JOIN keeps videos the outer loop, so each term seeks its source's index rather than walking video_embeddings.
            terms.append(
                f"""
                SELECT * FROM (
                  SELECT {ORDERED_COLUMNS}
                  FROM videos v
                  CROSS JOIN video_embeddings e
                    ON e.video_id = v.video_id AND e.instance_domain = v.instance_domain
                  LEFT JOIN channels c
                    ON c.channel_id = v.channel_id AND c.instance_domain = v.instance_domain
                  WHERE {predicate} AND {where}
                  ORDER BY {ORDERED_FEED_ORDER_BY["recent"]}
                  LIMIT ?
                )"""
            )
            params += [*source_params, *shared, limit]
        # A video can come from its channel's term and its account's term, so twice `limit` rows always hold the batch's first `limit` distinct ones.
        params.append(limit * 2)
        query = " UNION ALL ".join(terms) + " ORDER BY published_at DESC, video_id DESC, instance_domain DESC LIMIT ?"
        rows.extend(_ordered_row(row) for row in conn.execute(query, params))
    # Batches are merged here; Python's str order matches SQLite's BINARY collation, as UTF-8 byte order is code-point order.
    rows.sort(key=lambda row: (row["published_at"], row["video_id"], row["instance_domain"]), reverse=True)
    page: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        key = (row["video_id"], row["instance_domain"])
        if key in seen:
            continue
        seen.add(key)
        page.append(row)
        if len(page) == limit:
            break
    return page, encode_followed_cursor(page[-1]) if len(page) == limit else None


def fetch_random_rows_from_cache(
    server: Any, limit: int, error_threshold: int | None = None, include_nsfw: bool = True
) -> list[dict[str, Any]]:
    """Return random videos using the precomputed ANN-id cache; with the filter on, redraw windows until the page is full, the draws run out or a draw adds no unseen ANN id."""
    if server.random_cache_db is None or limit <= 0:
        return []
    # Filter off makes one draw so pages that error_threshold leaves short stay as they are today.
    draws = 1 if include_nsfw else RANDOM_CACHE_NSFW_MAX_DRAWS
    seen: set[int] = set()
    rows: list[dict[str, Any]] = []
    for _ in range(draws):
        # The handle is re-read under the lock on every draw: a refresh swap closes the old one once the lock is free.
        with server.random_cache_lock:
            ann_ids = fetch_random_ann_ids(server.random_cache_db, limit) if server.random_cache_db is not None else []
        # seen is empty on the first draw, so a window's own duplicates are kept, as today.
        fresh = [ann_id for ann_id in ann_ids if ann_id not in seen]
        if not fresh:
            break
        seen.update(fresh)
        with server.db_lock:
            metadata = fetch_metadata(server.db, fresh, error_threshold=error_threshold, include_nsfw=include_nsfw)
        for ann_id in fresh:
            meta = metadata.get(ann_id)
            if meta:
                rows.append(meta)
        if len(rows) >= limit:
            break
    return rows[:limit]
