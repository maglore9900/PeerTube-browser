"""Video metadata endpoint handlers for /api/video and /api/video/refresh.

Responsibilities:
- Resolve video row by id/uuid/host.
- Merge live instance metadata over DB metadata field by field, falling back to the row where the instance supplied nothing.
- Persist the merged metadata back to the DB, only when the instance's video detail call answered.
- Return normalized response for the client video page.
"""
import json
import logging
import sqlite3
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from data.db import statement_deadline
from data.time import now_ms
from data.popularity import compute_popularity
from data.peertube_labels import category_label, language_label
from http_utils import respond_json
from server_config import DEFAULT_STATEMENT_TIMEOUT_SECONDS


def fetch_video_row(
    conn: sqlite3.Connection,
    video_id: str,
    host: str | None,
    error_threshold: int | None = None,
) -> dict[str, Any] | None:
    """Fetch a video row from DB by id/uuid and optional host."""
    error_clause = ""
    params = {"id": video_id, "host": host}
    if error_threshold is not None and error_threshold > 0:
        error_clause = "AND (v.error_count IS NULL OR v.error_count < :threshold)"
        params["threshold"] = error_threshold
    row = conn.execute(
        """
        SELECT
          v.video_id,
          v.video_uuid,
          v.instance_domain,
          v.channel_id,
          v.channel_name,
          v.channel_url,
          v.account_name,
          v.account_url,
          v.title,
          v.description,
          v.embed_path,
          v.published_at,
          v.video_url,
          v.views,
          v.likes,
          v.dislikes,
          v.tags_json,
          v.category,
          v.nsfw,
          v.language,
          v.duration,
          v.thumbnail_url,
          v.last_checked_at,
          c.channel_name AS channel_slug,
          c.display_name AS channel_display_name,
          c.followers_count AS channel_followers_count,
          c.avatar_url AS channel_avatar_url
        FROM videos v
        LEFT JOIN channels c
          ON c.channel_id = v.channel_id AND c.instance_domain = v.instance_domain
        WHERE (v.video_id = :id OR v.video_uuid = :id)
          AND (:host IS NULL OR v.instance_domain = :host)
          {error_clause}
        LIMIT 1
        """.format(error_clause=error_clause),
        params,
    ).fetchone()
    if row is None:
        return None
    return dict(row)


def fetch_instance_json(host: str, path: str) -> dict[str, Any] | None:
    """Fetch a JSON object from a PeerTube instance API path; None on network failure, non-200, a malformed body or a non-object body."""
    url = f"https://{host}{path}"
    req = Request(url, headers={"accept": "application/json"})
    try:
        with urlopen(req, timeout=8) as resp:
            if resp.status != 200:
                return None
            data = json.loads(resp.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError) as exc:
        logging.info("[video] instance request failed: %s", exc)
        return None
    except ValueError as exc:
        # UnicodeDecodeError and JSONDecodeError are both ValueError.
        logging.info("[video] instance response is not valid JSON: host=%s path=%s: %s", host, path, exc)
        return None
    if not isinstance(data, dict):
        logging.info("[video] instance response is not a JSON object: host=%s path=%s", host, path)
        return None
    return data


def resolve_asset_url(host: str, value: str | None) -> str:
    """Normalize asset URL to absolute https URL for an instance."""
    if not value or not host:
        return ""
    if value.startswith("http://") or value.startswith("https://"):
        return value
    return f"https://{host}{value}"


def pick_text(*values: Any) -> str | None:
    """Return the first non-empty string value."""
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def pick_number(*values: Any) -> int | None:
    """Return the first numeric value (int-like) or None."""
    for value in values:
        if isinstance(value, (int, float)):
            return int(value)
        if isinstance(value, str) and value.isdigit():
            return int(value)
    return None


def pick_present(value: Any, fallback: Any) -> Any:
    """Return value unless it is None, so a supplied 0 or 0/1 flag is kept over the fallback."""
    return fallback if value is None else value


def resolve_avatar_url(host: str, source: Any) -> str:
    """Extract avatar URL from API payload and normalize to absolute URL."""
    if not isinstance(source, dict):
        return ""
    avatar = source.get("avatar")
    if isinstance(avatar, dict):
        url = avatar.get("url")
        if isinstance(url, str):
            return resolve_asset_url(host, url)
        path = avatar.get("path")
        if isinstance(path, str):
            return resolve_asset_url(host, path)
    return ""


def id_text(value: Any) -> str | None:
    """Normalize a PeerTube id to text: a non-empty trimmed string or an int (never a bool); None otherwise."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value)
    return pick_text(value)


def to_tags_json(value: Any) -> str | None:
    """Convert a tag list to a JSON array of its string elements ("[]" when there are none); None when the value is not a list."""
    if isinstance(value, list):
        # Raw UTF-8 like the crawler's JSON.stringify, so FTS indexes words rather than \u escapes.
        return json.dumps([tag for tag in value if isinstance(tag, str)], ensure_ascii=False)
    return None


def tags_from_json(value: Any) -> list[str]:
    """Parse stored tags_json into its string tags; [] when null, empty, invalid or not a list."""
    if not isinstance(value, str) or not value:
        return []
    try:
        parsed = json.loads(value)
    except ValueError:
        return []
    if not isinstance(parsed, list):
        return []
    return [tag for tag in parsed if isinstance(tag, str)]


def extract_category(value: Any) -> str | None:
    """Extract the category label/name, else its id as text; a plain string or int is kept as text; None when absent or empty."""
    if isinstance(value, dict):
        return pick_text(value.get("label"), value.get("name")) or id_text(value.get("id"))
    return id_text(value)


def extract_language(value: Any) -> str | None:
    """Extract the PeerTube language code: an object's id or a plain non-empty string; None for a null id or anything else."""
    if isinstance(value, dict):
        return pick_text(value.get("id"))
    return pick_text(value)


def to_nullable_bool(value: Any) -> int | None:
    """Normalize truthy/falsy values into 0/1 or None."""
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value != 0)
    if isinstance(value, str):
        return int(value.strip().lower() in {"1", "true", "yes"})
    return None


def fetch_instance_video_dynamic(host: str, video_id: str) -> dict[str, Any] | None:
    """Fetch live video metadata from instance and normalize fields; None when the video detail fetch fails or answers an empty object (the single success signal)."""
    detail = fetch_instance_json(host, f"/api/v1/videos/{quote(video_id)}")
    # A real video detail always carries id, uuid and name, so `{}` means the instance did not answer.
    if not isinstance(detail, dict) or not detail:
        return None
    account = detail.get("account")
    if not isinstance(account, dict):
        account = {}
    channel = detail.get("channel")
    if not isinstance(channel, dict):
        channel = {}
    channel_slug = pick_text(channel.get("name"))
    channel_display = pick_text(channel.get("displayName"), channel.get("display_name"))
    channel_followers = pick_number(
        channel.get("followersCount"), channel.get("followers_count"), channel.get("followers")
    )

    channel_detail = None
    if channel_slug:
        channel_detail = fetch_instance_json(host, f"/api/v1/video-channels/{quote(channel_slug)}")
        if isinstance(channel_detail, dict):
            channel_display = pick_text(
                channel_display,
                channel_detail.get("displayName"),
                channel_detail.get("display_name"),
            )
            channel_followers = pick_number(
                channel_detail.get("followersCount"),
                channel_detail.get("followers_count"),
                channel_detail.get("followers"),
            ) or channel_followers
    return {
        "title": pick_text(detail.get("name"), detail.get("title")),
        "description": pick_text(detail.get("description")),
        "views": pick_number(detail.get("views"), detail.get("viewsCount"), detail.get("views_count")),
        "likes": pick_number(detail.get("likes"), detail.get("likesCount"), detail.get("likes_count")),
        "dislikes": pick_number(
            detail.get("dislikes"), detail.get("dislikesCount"), detail.get("dislikes_count")
        ),
        "tags_json": to_tags_json(detail.get("tags")),
        "category": extract_category(detail.get("category")),
        "language": extract_language(detail.get("language")),
        "nsfw": to_nullable_bool(detail.get("nsfw")),
        "duration": pick_number(detail.get("duration")),
        # resolve_asset_url answers "" for a missing value, which must read as absent, not overwrite the stored thumbnail.
        "thumbnail_url": resolve_asset_url(host, pick_text(detail.get("thumbnailUrl"), detail.get("thumbnailPath"))) or None,
        "channel_slug": channel_slug,
        "channel_display": channel_display,
        "channel_followers": channel_followers,
        "account_name": pick_text(account.get("displayName"), account.get("display_name"), account.get("name")),
        "account_url": pick_text(account.get("url")),
        "account_avatar_url": resolve_avatar_url(host, account) or resolve_avatar_url(host, detail),
    }


def resolve_video_row(
    handler: Any, server: Any, params: dict[str, list[str]]
) -> tuple[dict[str, Any], str, str] | None:
    """Resolve the requested video row, or answer 400/404 and return None.

    Returns the row, the requested id and the instance domain.
    """
    id_param = params.get("id", params.get("video_id", [None]))[0]
    host_param = params.get("host", params.get("instance_domain", [None]))[0]
    if not id_param:
        respond_json(handler, 400, {"error": "Missing video id"})
        return None
    with server.db_lock:
        row = fetch_video_row(
            server.db,
            id_param,
            host_param,
            error_threshold=server.video_error_threshold,
        )
    if not row:
        respond_json(handler, 404, {"error": "Video not found"})
        return None
    return row, id_param, row.get("instance_domain") or host_param or ""


def merge_video_metadata(
    row: dict[str, Any], source: dict[str, Any], instance_domain: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Merge live instance values over the DB row field by field; an empty `source` answers the DB row.

    Returns the client response and the merged values to persist; one value set feeds both.
    """
    title = source.get("title") or row.get("title")
    description = source.get("description") or row.get("description")
    views = pick_present(source.get("views"), row.get("views"))
    likes = pick_present(source.get("likes"), row.get("likes"))
    dislikes = pick_present(source.get("dislikes"), row.get("dislikes"))

    channel_display = (
        source.get("channel_display")
        or row.get("channel_display_name")
        or row.get("channel_name")
    )
    channel_slug = source.get("channel_slug") or row.get("channel_slug")
    channel_followers = pick_present(source.get("channel_followers"), row.get("channel_followers_count"))
    tags_json = pick_present(source.get("tags_json"), row.get("tags_json"))
    category = pick_present(source.get("category"), row.get("category"))
    language = pick_present(source.get("language"), row.get("language"))
    nsfw = pick_present(source.get("nsfw"), row.get("nsfw"))
    duration = pick_present(source.get("duration"), row.get("duration"))
    thumbnail_url = pick_present(source.get("thumbnail_url"), row.get("thumbnail_url"))

    channel_url = row.get("channel_url")
    if not channel_url and channel_slug and instance_domain:
        channel_url = f"https://{instance_domain}/video-channels/{quote(channel_slug)}"

    embed_url = resolve_asset_url(instance_domain, row.get("embed_path"))
    original_url = row.get("video_url")
    if not original_url and instance_domain:
        video_key = row.get("video_uuid") or row.get("video_id")
        if video_key:
            original_url = f"https://{instance_domain}/videos/watch/{quote(video_key)}"

    response = {
        "videoUuid": row.get("video_uuid") or "",
        "title": title or "",
        "description": description or "",
        "channelName": channel_display or "",
        "channelUrl": channel_url or "",
        "channelAvatarUrl": row.get("channel_avatar_url") or "",
        "subscribersCount": channel_followers,
        "instanceName": instance_domain or "",
        "instanceUrl": f"https://{instance_domain}" if instance_domain else "",
        "accountName": row.get("account_name") or "",
        "accountUrl": row.get("account_url") or "",
        "accountAvatarUrl": source.get("account_avatar_url") or "",
        "embedUrl": embed_url or "",
        "originalUrl": original_url or "",
        "views": views,
        "likes": likes,
        "dislikes": dislikes,
        "publishedAt": row.get("published_at"),
        # Labels are display only: `category` and the stored language code are written back raw, since FTS and embeddings read them.
        "category": category_label(category),
        "language": language_label(language),
        "tags": tags_from_json(tags_json),
        "nsfw": None if nsfw is None else bool(nsfw),
        "duration": duration,
        "thumbnailUrl": thumbnail_url or "",
    }
    merged = {
        "title": title,
        "description": description,
        "views": views,
        "likes": likes,
        "dislikes": dislikes,
        "channel_display": channel_display,
        "channel_slug": channel_slug,
        "channel_followers": channel_followers,
        "tags_json": tags_json,
        "category": category,
        "language": language,
        "nsfw": nsfw,
        "duration": duration,
        "thumbnail_url": thumbnail_url,
    }
    return response, merged


def persist_video_metadata(
    server: Any, row: dict[str, Any], instance_domain: str, merged: dict[str, Any]
) -> None:
    """Write merged metadata back to the video, its channel and its instance."""
    channel_id = row.get("channel_id")
    checked_at = now_ms()
    popularity = compute_popularity(
        merged["views"],
        merged["likes"],
        row.get("published_at"),
        float(getattr(server, "popularity_like_weight", 2.0)),
        now_ms_value=checked_at,
    )
    try:
        # A fresh budget: the request's own deadline was spent waiting on the instance, not on the DB.
        with statement_deadline(getattr(server, "statement_timeout_seconds", DEFAULT_STATEMENT_TIMEOUT_SECONDS)), server.db_lock:
            with server.db:
                server.db.execute(
                    """
                    UPDATE videos
                    SET title = ?, description = ?, channel_name = ?, views = ?, likes = ?, dislikes = ?,
                        popularity = ?,
                        tags_json = ?, category = ?, language = ?, nsfw = ?, duration = ?, thumbnail_url = ?, last_checked_at = ?
                    WHERE video_id = ? AND instance_domain = ?
                    """,
                    (
                        merged["title"],
                        merged["description"],
                        merged["channel_display"],
                        merged["views"],
                        merged["likes"],
                        merged["dislikes"],
                        popularity,
                        merged["tags_json"],
                        merged["category"],
                        merged["language"],
                        merged["nsfw"],
                        merged["duration"],
                        merged["thumbnail_url"],
                        checked_at,
                        row.get("video_id"),
                        instance_domain,
                    ),
                )
                if channel_id:
                    server.db.execute(
                        """
                        UPDATE channels
                        SET channel_name = ?, display_name = ?, followers_count = ?
                        WHERE channel_id = ? AND instance_domain = ?
                        """,
                        (
                            merged["channel_slug"],
                            merged["channel_display"],
                            merged["channel_followers"],
                            channel_id,
                            instance_domain,
                        ),
                    )
                server.db.execute(
                    """
                    UPDATE instances
                    SET last_error = NULL, last_error_at = NULL, last_error_source = NULL
                    WHERE host = ?
                    """,
                    (instance_domain,),
                )
    except sqlite3.OperationalError as exc:
        logging.warning(
            "[video] failed to persist dynamic metadata for video_id=%s host=%s: %s",
            row.get("video_id"),
            instance_domain,
            exc,
        )


def handle_video_refresh_request(handler: Any, server: Any, params: dict[str, list[str]]) -> bool:
    """Handle /api/video/refresh: live instance values merged over the DB row, persisted."""
    resolved = resolve_video_row(handler, server, params)
    if resolved is None:
        return True
    row, id_param, instance_domain = resolved
    dynamic = fetch_instance_video_dynamic(instance_domain, id_param) if instance_domain else None
    response, merged = merge_video_metadata(row, dynamic or {}, instance_domain)
    if dynamic is not None and instance_domain and row.get("video_id"):
        persist_video_metadata(server, row, instance_domain, merged)
    respond_json(handler, 200, response)
    return True


def handle_video_request(handler: Any, server: Any, params: dict[str, list[str]]) -> bool:
    """Handle /api/video request and respond with merged metadata."""
    # rat-tail: /api/video still calls the instance and writes on every request, exactly as a refresh does; the follow-up plan makes it DB-only by answering merge_video_metadata(row, {}, instance_domain) with no instance call or write.
    return handle_video_refresh_request(handler, server, params)
