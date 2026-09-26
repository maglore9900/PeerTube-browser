"""Hybrid video search: FTS5 keyword retrieval fused with ANN vector retrieval.

Neither half is sufficient on its own. BM25 matches only tokens the query and the
document share, so it cannot reach a Russian title from an English query; the vector half
can, but it is weaker on exact titles, tags, channel names and other proper nouns. Each
half retrieves its own candidates and the two ranked lists are fused by reciprocal rank,
which needs no score calibration - bm25 returns an unbounded negative relevance and the
index returns a cosine similarity, and normalising one onto the other would have to be
re-tuned whenever either side changed.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from data.ann import search_index
from data.db import statement_deadline
from data.metadata import fetch_metadata

# Anything that is not a word character in some script, a digit or an underscore. Splitting
# on this drops every FTS5 operator (NEAR, *, ^, ", :, -, parentheses) as a side effect,
# because none of them survive as a token.
_TOKEN_SPLIT = re.compile(r"[^\w]+", re.UNICODE)


class SearchIndexMissing(RuntimeError):
    """Raised when the full-text index has not been built in this database."""


def search_connection(server: Any) -> tuple[Any, Any]:
    """Return the connection and lock search must use.

    Search owns a dedicated read-only connection. Its statements are the only long ones
    in the service, and running them under the shared connection's lock would stall every
    other route. Falling back to the shared connection keeps older callers and tests
    working, at that cost.
    """
    conn = getattr(server, "search_db", None)
    if conn is not None:
        return conn, server.search_db_lock
    return server.db, server.db_lock


def search_deadline(server: Any):
    """Guard this thread's search statements with the request time budget."""
    seconds = float(getattr(server, "statement_timeout_seconds", 0) or 0)
    return statement_deadline(seconds)

VIDEO_ROW_SQL = """
  v.rowid AS rowid,
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
  v.last_checked_at
"""

LEXICAL_SORTS = {
    "published_at": "v.published_at DESC, v.video_id DESC",
    "views": "v.views DESC, v.video_id DESC",
    "popularity": "v.popularity DESC, v.video_id DESC",
}


def sanitize_query(raw: str, max_tokens: int, max_token_length: int) -> tuple[str, str]:
    """Turn caller text into a safe FTS5 MATCH expression and a plain encoder string.

    FTS5 `MATCH` takes a query *language*, not a string: an unescaped term can inject
    operators and column filters, which either errors or builds a deliberately expensive
    scan. Every token is therefore quoted as a string literal, and the count and length
    are capped so one request cannot turn into an unbounded amount of work - in the index
    or in the encoder.

    :param raw: Caller-supplied query text.
    :param max_tokens: Maximum tokens kept from the query.
    :param max_token_length: Maximum characters kept per token.
    :returns: ``(match_expression, plain_text)``; both empty when nothing survives.
    """
    if not raw:
        return "", ""
    tokens = [token for token in _TOKEN_SPLIT.split(raw.strip()) if token]
    tokens = [token[:max_token_length] for token in tokens[:max_tokens]]
    if not tokens:
        return "", ""
    # Doubling quotes is what escapes a quote inside an FTS5 string literal. Tokens cannot
    # contain one after the split above; this stays correct if that ever changes.
    quoted = ['"' + token.replace('"', '""') + '"' for token in tokens]
    # Joined with OR, not by juxtaposition. FTS5 defaults to AND, which makes every extra
    # word a filter: "cats and kittens" would require the literal token "and" to appear
    # and return nothing. OR recovers the matches and lets bm25 rank documents containing
    # more of the terms above those containing fewer.
    match_expression = " OR ".join(quoted)
    return match_expression, " ".join(tokens)


def fts_available(db: Any) -> bool:
    """Whether the full-text index exists in this database.

    An Engine started against a dataset synced before the index existed would otherwise
    answer every search with a 500 from a missing table. Checked per request because the
    table appears mid-process when a sync runs underneath a live server.
    """
    row = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='videos_fts'"
    ).fetchone()
    return row is not None


def lexical_candidates(
    db: Any,
    match_expression: str,
    limit: int,
    sort: str = "relevance",
) -> list[dict[str, Any]]:
    """Return rows matching the FTS5 expression, best first.

    :param db: Whitelist database connection.
    :param match_expression: Output of :func:`sanitize_query`.
    :param limit: Maximum rows to return.
    :param sort: ``relevance`` for bm25 order, or a key of :data:`LEXICAL_SORTS`.
    """
    if not match_expression:
        return []
    order_by = LEXICAL_SORTS.get(sort, "bm25(videos_fts)")
    query = db.execute(
        f"""
        SELECT
        {VIDEO_ROW_SQL}
        FROM videos_fts f
        JOIN videos v ON v.rowid = f.rowid
        LEFT JOIN channels c
          ON c.channel_id = v.channel_id AND c.instance_domain = v.instance_domain
        WHERE videos_fts MATCH ?
        ORDER BY {order_by}
        LIMIT ?
        """,
        (match_expression, limit),
    )
    return [dict(row) for row in query]


def vector_candidates(
    server: Any,
    text: str,
    limit: int,
) -> list[dict[str, Any]]:
    """Return rows semantically near the query text, best first.

    Encoding happens outside ``db_lock``: it is the slowest part of the request and holding
    the one global read lock across it would stall every other route. Returns an empty
    list when the encoder is disabled, which is how a model/index mismatch degrades to
    lexical-only search instead of to wrong results.
    """
    encoder = getattr(server, "query_encoder", None)
    if encoder is None or not encoder.enabled or not text:
        return []
    vector = encoder.encode(text)
    if vector is None:
        return []
    with server.index_lock:
        rowids, _scores = search_index(server.index, vector, limit, None)
    if not rowids:
        return []
    conn, lock = search_connection(server)
    with lock:
        with search_deadline(server):
            metadata = fetch_metadata(
                conn,
                rowids,
                error_threshold=getattr(server, "video_error_threshold", None),
            )
    ordered: list[dict[str, Any]] = []
    for rowid in rowids:
        row = metadata.get(int(rowid))
        if row:
            ordered.append(row)
    return ordered


def fuse_by_rank(
    lexical: list[dict[str, Any]],
    vector: list[dict[str, Any]],
    rrf_k: int,
) -> list[dict[str, Any]]:
    """Fuse two ranked lists by reciprocal rank and return one ranked list.

    A row appearing in both halves scores the sum of its two reciprocal ranks, which is
    what lets agreement between keyword and semantic evidence outrank a strong showing in
    only one of them.

    :param lexical: Keyword results, best first.
    :param vector: Vector results, best first.
    :param rrf_k: Rank damping constant; larger flattens the contribution of top ranks.
    """
    scores: dict[tuple[str, str], float] = {}
    rows: dict[tuple[str, str], dict[str, Any]] = {}
    sources: dict[tuple[str, str], set[str]] = {}

    for name, candidates in (("lexical", lexical), ("vector", vector)):
        for rank, row in enumerate(candidates, start=1):
            key = (str(row.get("video_id")), str(row.get("instance_domain")))
            scores[key] = scores.get(key, 0.0) + 1.0 / (rrf_k + rank)
            sources.setdefault(key, set()).add(name)
            # The lexical half carries `popularity` and the vector half does not, so the
            # first row seen wins and later ones only fill gaps.
            if key in rows:
                for field, value in row.items():
                    rows[key].setdefault(field, value)
            else:
                rows[key] = dict(row)

    ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    fused: list[dict[str, Any]] = []
    for key, score in ranked:
        row = rows[key]
        row["search_score"] = score
        row["search_sources"] = sorted(sources[key])
        fused.append(row)
    return fused


def search_videos(
    server: Any,
    raw_query: str,
    page: int,
    limit: int,
    sort: str,
    max_tokens: int,
    max_token_length: int,
    candidate_pool: int,
    rrf_k: int,
) -> tuple[list[dict[str, Any]], int]:
    """Run one search and return the requested page plus the candidate total.

    `total` counts the fused candidate set, not every matching row in the database: both
    halves are pooled retrievals, so a true corpus-wide count would mean a second full
    scan for a number only used to draw pagination.

    :returns: ``(rows_for_page, total_candidates)``.
    """
    match_expression, plain_text = sanitize_query(raw_query, max_tokens, max_token_length)
    if not match_expression:
        return [], 0

    conn, lock = search_connection(server)
    with lock:
        with search_deadline(server):
            if not fts_available(conn):
                raise SearchIndexMissing(
                    "videos_fts is not present in this database; run the dataset build's "
                    "sync stage to create it."
                )
            lexical = lexical_candidates(conn, match_expression, candidate_pool, sort)

    if sort == "relevance":
        vector = vector_candidates(server, plain_text, candidate_pool)
        candidates = fuse_by_rank(lexical, vector, rrf_k)
    else:
        # An explicit ordering has nothing to fuse: mixing in semantic neighbours would
        # only add rows the caller did not ask to see, in an order they did not choose.
        vector = []
        candidates = lexical

    logging.info(
        "[search] tokens=%d lexical=%d vector=%d fused=%d sort=%s",
        len(plain_text.split()),
        len(lexical),
        len(vector),
        len(candidates),
        sort,
    )

    start = max(0, (page - 1) * limit)
    return candidates[start : start + limit], len(candidates)
