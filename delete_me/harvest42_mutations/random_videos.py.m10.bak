"""Provide random videos runtime helpers."""

from __future__ import annotations

import sqlite3
import time
from typing import Any

from data.metadata import NSFW_ALLOWED_SQL, fetch_metadata
from data.random_cache import fetch_random_ann_ids

# Filter-on draws per request before a short Random page is returned as is; the cache holds no NSFW flag, so allowed rows are found by redrawing.
RANDOM_CACHE_NSFW_MAX_DRAWS = 4
# video_id then instance_domain close every order, so rows equal on the other keys still sort one way and an OFFSET page never repeats or skips one.
POPULAR_ORDER_BY = """
    v.popularity DESC,
    v.likes DESC,
    v.views DESC,
    v.published_at DESC,
    v.video_id DESC,
    v.instance_domain DESC
"""
ORDERED_FEED_ORDER_BY = {
    "hot": POPULAR_ORDER_BY,
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
    """Return most popular videos by likes/views."""
    conditions, params = _listing_conditions(error_threshold, include_nsfw)
    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    params += [limit, limit]
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
        FROM (
          SELECT
            v.video_id,
            v.instance_domain
          FROM videos v
          {where_clause}
          ORDER BY {POPULAR_ORDER_BY}
          LIMIT ?
        ) AS popular_ids
        JOIN video_embeddings e
          ON e.video_id = popular_ids.video_id AND e.instance_domain = popular_ids.instance_domain
        JOIN videos v
          ON v.video_id = e.video_id AND v.instance_domain = e.instance_domain
        LEFT JOIN channels c
          ON c.channel_id = v.channel_id AND c.instance_domain = v.instance_domain
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
                "popularity": row["popularity"],
                "last_checked_at": row["last_checked_at"],
                "embedding_dim": row["embedding_dim"],
                "model_name": row["model_name"],
            }
        )
    return rows


def fetch_ordered_page(
    conn: sqlite3.Connection, order: str, limit: int, offset: int, error_threshold: int | None = None, include_nsfw: bool = True
) -> list[dict[str, Any]]:
    """Return one page of embedded videos in a global feed order."""
    order_by = ORDERED_FEED_ORDER_BY[order]
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
        ORDER BY {order_by}
        LIMIT ? OFFSET ?
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
                "popularity": row["popularity"],
                "last_checked_at": row["last_checked_at"],
                "embedding_dim": row["embedding_dim"],
                "model_name": row["model_name"],
            }
        )
    return rows


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
