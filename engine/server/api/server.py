#!/usr/bin/env python3
"""Similarity server API for embeddings and recommendations.

This module wires together data access, ANN search, cache-backed similarity
candidate generation, and recommendation mixing into HTTP handlers.
"""
import logging
import argparse
import faulthandler
import os
import sqlite3
import sys
import signal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading
from uuid import uuid4

script_dir = Path(__file__).resolve().parent
server_dir = script_dir.parent
if str(server_dir) not in sys.path:
    # Allow imports from engine/server when running this module directly.
    sys.path.insert(0, str(server_dir))

from server_config import (
    BATCH_SIZE,
    QUERY_ENCODER_ENABLED,
    QUERY_ENCODER_MODEL,
    QUERY_ENCODER_IDLE_SECONDS,
    QUERY_ENCODER_DEVICE,
    DEFAULT_NPROBE,
    DEFAULT_NORMALIZE_QUERIES,
    DEFAULT_RANDOM_CACHE_SIZE,
    DEFAULT_RANDOM_CACHE_FILTERED_MODE,
    DEFAULT_RANDOM_CACHE_MAX_PER_AUTHOR,
    DEFAULT_RANDOM_CACHE_MAX_PER_INSTANCE,
    DEFAULT_RANDOM_CACHE_REFRESH,
    DEFAULT_FRESH_POOL_SIZE,
    DEFAULT_POPULARITY_LIKE_WEIGHT,
    DEFAULT_SIMILAR_PER_LIKE,
    DEFAULT_SIMILARITY_CACHE_REFRESH,
    DEFAULT_SIMILARITY_EXCLUDE_SOURCE_AUTHOR,
    DEFAULT_SIMILARITY_MAX_PER_AUTHOR,
    DEFAULT_SIMILARITY_ALLOW_ANN_ON_CACHE_MISS,
    DEFAULT_SIMILARITY_REQUIRE_FULL_CACHE,
    DEFAULT_SIMILARITY_SEARCH_LIMIT,
    DEFAULT_USE_SIMILARITY_CACHE,
    DEFAULT_DB_PATH,
    DEFAULT_INDEX_PATH,
    DEFAULT_RANDOM_CACHE_DB_PATH,
    DEFAULT_SERVER_HOST,
    DEFAULT_SERVER_PORT,
    DEFAULT_SIMILARITY_DB_PATH,
    MAX_LIKES,
    MAX_LIKES_FOR_RECS,
    RECOMMENDATIONS_DEBUG_ENABLED,
    RECOMMENDATION_PIPELINE,
    RELATED_VIDEOS_PERSONALIZATION,
    SIMILAR_VIDEO_SEARCH_LIMIT,
    SIMILAR_VIDEO_TOP_K,
    SIMILAR_VIDEO_NPROBE,
    SIMILAR_VIDEO_TARGET_MIN_POOL,
    SIMILAR_VIDEO_MAX_NPROBE,
    SIMILAR_VIDEO_MAX_SEARCH_LIMIT,
    SIMILAR_VIDEO_MIN_SCORE,
    SIMILAR_VIDEO_TAIL_MIN_SCORE,
    SIMILAR_VIDEO_SAMPLE_WINDOW_FACTOR,
    VIDEO_ERROR_THRESHOLD,
    DEFAULT_USE_CLIENT_LIKES,
    DEFAULT_RATE_LIMIT_MAX_REQUESTS,
    DEFAULT_RATE_LIMIT_WINDOW_SECONDS,
    DEFAULT_STATEMENT_TIMEOUT_SECONDS,
    DEFAULT_MAX_INGEST_EVENTS,
    DEFAULT_INGEST_CHUNK_SIZE,
    INTERACTION_RAW_RETENTION_DAYS,
    ENGINE_BRIDGE_TOKEN,
    DEFAULT_ENABLE_INSTANCE_IGNORE,
    DEFAULT_ENABLE_CHANNEL_BLOCKLIST,
    ENGINE_INGEST_MODE,
    DEFAULT_RECOMMENDATIONS_LOG_PROFILE,
    DISLIKE_SIMILARITY_FLOOR,
    random_cache_refresh_interval_minutes,
)
from logging_profiles import configure_engine_logging
from data.ann import set_nprobe
from data.db import connect_db, connect_readonly_db, connect_similarity_db
from data.embedding_space import (
    assert_index_matches_embeddings,
    resolve_embedding_space,
)
from data.query_encoder import QueryEncoder
from data.embeddings import (
    fetch_embeddings_by_ids,
    fetch_seed_embedding,
    fetch_seed_embeddings_for_likes,
)
from data.random_videos import (
    fetch_random_rows,
    fetch_random_rows_from_cache,
    fetch_recent_videos,
    fetch_popular_videos,
)
from data.similarity_candidates import get_similar_candidates
from data.similarity_cache import ensure_similarity_schema
from data.interaction_events import ensure_interaction_event_schema
from data.random_cache import open_random_cache_if_usable, run_random_cache_worker
from data.channels import ensure_channels_indexes
from data.videos import ensure_video_indexes
from data.moderation import ensure_moderation_schema
from recommendations import RecommendationStrategy
from recommendations.keys import like_key
from recommendations.builder import (
    RecommendationBuilderDeps,
    RecommendationBuilderSettings,
    build_recommendation_strategy,
)
from recommendations.related_personalization import (
    RelatedPersonalizationDeps,
)
from handlers.similar import SimilarHandler
from http_utils import RateLimiter
from request_context import (
    fetch_recent_likes_request,
    fetch_request_dislike_centroids,
    fetch_request_excluded_keys,
    fetch_request_include_nsfw,
)
from scripts.cli_format import CompactHelpFormatter
try:
    import faiss  # type: ignore
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "faiss is required. Install faiss-cpu in your Python environment."
    ) from exc


SIMILAR_PER_LIKE = DEFAULT_SIMILAR_PER_LIKE
SIMILARITY_SEARCH_LIMIT = DEFAULT_SIMILARITY_SEARCH_LIMIT
SIMILARITY_MAX_PER_AUTHOR = DEFAULT_SIMILARITY_MAX_PER_AUTHOR
SIMILARITY_EXCLUDE_SOURCE_AUTHOR = DEFAULT_SIMILARITY_EXCLUDE_SOURCE_AUTHOR
DEV_SERVER_PORT = 7071


def _parse_port(value: str) -> int:
    """Handle parse port."""
    port = int(value)
    if port < 1 or port > 65535:
        raise argparse.ArgumentTypeError("port must be in range 1..65535")
    return port


def parse_args() -> argparse.Namespace:
    """Handle parse args."""
    parser = argparse.ArgumentParser(
        description="Run PeerTube Browser API server.",
        formatter_class=CompactHelpFormatter,
    )
    parser.add_argument(
        "--dev",
        action="store_true",
        help=(
            "Enable dev defaults: bind port 7071, skip the random cache startup build "
            "when a usable cache exists (unless a refresh flag is given), and set the "
            "periodic random cache interval to 0 (unless "
            "RANDOM_CACHE_REFRESH_INTERVAL_MINUTES is set)."
        ),
    )
    parser.add_argument(
        "--host",
        default=DEFAULT_SERVER_HOST,
        help="Server host/interface to bind.",
    )
    parser.add_argument(
        "--port",
        type=_parse_port,
        default=None,
        help=(
            "Server TCP port to bind. "
            f"Defaults to {DEFAULT_SERVER_PORT} (or {DEV_SERVER_PORT} with --dev)."
        ),
    )
    refresh_group = parser.add_mutually_exclusive_group()
    refresh_group.add_argument(
        "--random-cache-refresh",
        dest="random_cache_refresh",
        action="store_true",
        help=(
            "Run a background random cache build at startup, after the server is "
            "listening. Does not affect the periodic build."
        ),
    )
    refresh_group.add_argument(
        "--no-random-cache-refresh",
        dest="random_cache_refresh",
        action="store_false",
        help=(
            "Skip the startup random cache build when a usable cache exists. "
            "Does not affect the periodic build."
        ),
    )
    parser.set_defaults(random_cache_refresh=None)
    return parser.parse_args()


class SimilarServer(ThreadingHTTPServer):
    """Threaded HTTP server with shared DB and index handles."""
    def __init__(
        self,
        server_address: tuple[str, int],
        handler_class: type[BaseHTTPRequestHandler],
        db: sqlite3.Connection,
        similarity_db: sqlite3.Connection | None,
        random_cache_db: sqlite3.Connection | None,
        index: faiss.Index,
        embeddings_dim: int,
        embeddings_count: int,
        default_limit: int,
        normalize_queries: bool,
        refresh_similarity_cache: bool,
        similarity_require_full_cache: bool,
        similarity_allow_ann_on_cache_miss: bool,
        similarity_search_limit: int,
        similarity_max_per_author: int,
        similarity_exclude_source_author: bool,
        recommendation_strategy: RecommendationStrategy,
        related_personalization_deps: RelatedPersonalizationDeps | None,
        related_personalization_enabled: bool,
        video_error_threshold: int,
        recommendations_debug_enabled: bool,
        use_client_likes: bool,
        rate_limiter: RateLimiter | None,
        popularity_like_weight: float,
        enable_instance_ignore: bool,
        enable_channel_blocklist: bool,
        engine_ingest_mode: str,
        query_encoder: QueryEncoder,
        search_db: sqlite3.Connection,
    ) -> None:
        """Initialize the instance."""
        super().__init__(server_address, handler_class)
        self.db = db
        self.query_encoder = query_encoder
        # Search runs the only long statements in the service, on their own read-only
        # connection guarded by their own lock, so they never hold `db_lock`.
        self.search_db = search_db
        self.index = index
        self.embeddings_dim = embeddings_dim
        self.embeddings_count = embeddings_count
        self.default_limit = default_limit
        self.normalize_queries = normalize_queries
        self.similarity_db = similarity_db
        self.random_cache_db = random_cache_db
        self.refresh_similarity_cache = refresh_similarity_cache
        self.similarity_require_full_cache = similarity_require_full_cache
        self.similarity_allow_ann_on_cache_miss = similarity_allow_ann_on_cache_miss
        self.similarity_search_limit = similarity_search_limit
        self.similarity_max_per_author = similarity_max_per_author
        self.similarity_exclude_source_author = similarity_exclude_source_author
        self.recommendation_strategy = recommendation_strategy
        self.related_personalization_deps = related_personalization_deps
        self.related_personalization_enabled = related_personalization_enabled
        self.video_error_threshold = video_error_threshold
        self.recommendations_debug_enabled = recommendations_debug_enabled
        self.use_client_likes = use_client_likes
        self.rate_limiter = rate_limiter
        self.popularity_like_weight = popularity_like_weight
        self.enable_instance_ignore = enable_instance_ignore
        self.enable_channel_blocklist = enable_channel_blocklist
        self.engine_ingest_mode = engine_ingest_mode
        self.statement_timeout_seconds = DEFAULT_STATEMENT_TIMEOUT_SECONDS
        self.max_ingest_events = DEFAULT_MAX_INGEST_EVENTS
        self.ingest_chunk_size = DEFAULT_INGEST_CHUNK_SIZE
        self.raw_retention_days = INTERACTION_RAW_RETENTION_DAYS
        # None makes the first successful ingest after startup run a strip.
        self.last_raw_prune_at = None
        self.bridge_token = ENGINE_BRIDGE_TOKEN
        self.index_lock = threading.Lock()
        self.db_lock = threading.Lock()
        self.search_db_lock = threading.Lock()
        self.similarity_db_lock = threading.Lock()
        self.random_cache_lock = threading.Lock()


def main() -> None:
    """Run the similarity server."""
    args = parse_args()
    run_id = str(uuid4())
    stop_reason = "unknown"

    def _signal_name(signum: int) -> str:
        """Return a stable signal name for lifecycle logging."""
        try:
            return signal.Signals(signum).name
        except ValueError:
            return str(signum)

    def _handle_shutdown_signal(signum: int, _frame: object) -> None:
        """Translate SIGTERM/SIGINT into KeyboardInterrupt for graceful shutdown."""
        nonlocal stop_reason
        stop_reason = f"signal:{_signal_name(signum)}"
        raise KeyboardInterrupt

    # `kill -USR1 <pid>` dumps every thread's Python stack to stderr, which the service
    # wrapper captures into engine.log. A wedged process cannot be asked what it is doing
    # any other way: it answers no requests, and its threads are all parked in futex.
    faulthandler.register(signal.SIGUSR1, all_threads=True, chain=False)

    previous_sigint = signal.getsignal(signal.SIGINT)
    previous_sigterm = signal.getsignal(signal.SIGTERM)
    signal.signal(signal.SIGINT, _handle_shutdown_signal)
    signal.signal(signal.SIGTERM, _handle_shutdown_signal)

    script_dir = Path(__file__).resolve().parent
    host = args.host
    default_port = DEV_SERVER_PORT if args.dev else DEFAULT_SERVER_PORT
    port = args.port if args.port is not None else default_port
    if args.random_cache_refresh is None:
        random_cache_refresh = False if args.dev else DEFAULT_RANDOM_CACHE_REFRESH
    else:
        random_cache_refresh = bool(args.random_cache_refresh)
    random_cache_interval = random_cache_refresh_interval_minutes(args.dev)

    active_log_profile = configure_engine_logging(DEFAULT_RECOMMENDATIONS_LOG_PROFILE)

    repo_root = script_dir.parents[2]
    db_path = (repo_root / DEFAULT_DB_PATH).resolve()
    index_path = (repo_root / DEFAULT_INDEX_PATH).resolve()
    similarity_db_path = (repo_root / DEFAULT_SIMILARITY_DB_PATH).resolve()
    random_cache_path = (repo_root / DEFAULT_RANDOM_CACHE_DB_PATH).resolve()

    db = connect_db(db_path)
    search_db = connect_readonly_db(db_path)
    ensure_moderation_schema(db)
    ensure_interaction_event_schema(db)
    ensure_channels_indexes(db)
    ensure_video_indexes(db)
    similarity_db = connect_similarity_db(similarity_db_path)
    ensure_similarity_schema(similarity_db)
    # The build's temp file is written in this directory.
    random_cache_path.parent.mkdir(parents=True, exist_ok=True)
    # Nothing is built before listening: a usable cache serves as it is, and a missing or empty one leaves the random feed on the DB until the background build swaps one in.
    random_cache_db = open_random_cache_if_usable(random_cache_path)
    random_cache_startup_build = random_cache_refresh or random_cache_db is None
    dim_value, embeddings_model = resolve_embedding_space(db)
    logging.info("embedding space model=%s dim=%d", embeddings_model, dim_value)

    logging.info("loading FAISS index=%s", index_path)
    index = faiss.read_index(str(index_path), faiss.IO_FLAG_MMAP | faiss.IO_FLAG_READ_ONLY)
    set_nprobe(index, DEFAULT_NPROBE)
    logging.info(
        "[similar-server] upnext_config SIMILAR_VIDEO_SEARCH_LIMIT=%s SIMILAR_VIDEO_TOP_K=%s SIMILAR_VIDEO_NPROBE=%s SIMILAR_VIDEO_TARGET_MIN_POOL=%s SIMILAR_VIDEO_MAX_NPROBE=%s SIMILAR_VIDEO_MAX_SEARCH_LIMIT=%s SIMILAR_VIDEO_MIN_SCORE=%s SIMILAR_VIDEO_TAIL_MIN_SCORE=%s SIMILAR_VIDEO_SAMPLE_WINDOW_FACTOR=%s",
        SIMILAR_VIDEO_SEARCH_LIMIT,
        SIMILAR_VIDEO_TOP_K,
        SIMILAR_VIDEO_NPROBE,
        SIMILAR_VIDEO_TARGET_MIN_POOL,
        SIMILAR_VIDEO_MAX_NPROBE,
        SIMILAR_VIDEO_MAX_SEARCH_LIMIT,
        SIMILAR_VIDEO_MIN_SCORE,
        SIMILAR_VIDEO_TAIL_MIN_SCORE,
        SIMILAR_VIDEO_SAMPLE_WINDOW_FACTOR,
    )

    assert_index_matches_embeddings(index_path, index, dim_value, embeddings_model)

    # The encoder must speak the same semantic space as the index. Two models can share a
    # dimension, so this compares names, and a mismatch degrades search to its lexical
    # half rather than stopping the Engine: every other route is unaffected by it.
    query_encoder = QueryEncoder(
        QUERY_ENCODER_MODEL,
        device=QUERY_ENCODER_DEVICE,
        idle_seconds=QUERY_ENCODER_IDLE_SECONDS,
        enabled=QUERY_ENCODER_ENABLED,
    )
    if not QUERY_ENCODER_ENABLED:
        query_encoder.disable(
            "QUERY_ENCODER_ENABLED is off; serving lexical search only. In-process torch "
            "loads a second OpenMP runtime beside faiss and deadlocked the server."
        )
    elif QUERY_ENCODER_MODEL != embeddings_model:
        query_encoder.disable(
            f"query encoder model {QUERY_ENCODER_MODEL} does not match index model "
            f"{embeddings_model}; serving lexical search only. Re-embed with --force "
            "and rebuild the index, or set QUERY_ENCODER_MODEL to the index model."
        )
    else:
        logging.info(
            "query encoder armed model=%s device=%s idle_seconds=%d",
            QUERY_ENCODER_MODEL,
            QUERY_ENCODER_DEVICE,
            QUERY_ENCODER_IDLE_SECONDS,
        )
    embeddings_count = int(index.ntotal)
    recommendation_deps = RecommendationBuilderDeps(
        fetch_recent_likes=fetch_recent_likes_request,
        fetch_seed_embedding=fetch_seed_embedding,
        fetch_seed_embeddings_for_likes=fetch_seed_embeddings_for_likes,
        get_similar_candidates=get_similar_candidates,
        like_key=like_key,
        fetch_embeddings_by_ids=fetch_embeddings_by_ids,
        fetch_random_rows=fetch_random_rows,
        fetch_random_rows_from_cache=fetch_random_rows_from_cache,
        fetch_recent_videos=fetch_recent_videos,
        fetch_popular_videos=fetch_popular_videos,
        fetch_dislike_centroids=fetch_request_dislike_centroids,
        fetch_excluded_keys=fetch_request_excluded_keys,
        fetch_include_nsfw=fetch_request_include_nsfw,
    )
    recommendation_settings = RecommendationBuilderSettings(
        max_likes=MAX_LIKES,
        max_likes_for_recs=MAX_LIKES_FOR_RECS,
        similar_per_like=SIMILAR_PER_LIKE,
        default_similar_from_likes_source=DEFAULT_USE_SIMILARITY_CACHE,
        video_error_threshold=VIDEO_ERROR_THRESHOLD,
        fresh_pool_size=DEFAULT_FRESH_POOL_SIZE,
        dislike_similarity_floor=DISLIKE_SIMILARITY_FLOOR,
    )
    recommendation_strategy = build_recommendation_strategy(
        RECOMMENDATION_PIPELINE, recommendation_deps, recommendation_settings
    )
    recommendation_strategy.settings = recommendation_settings
    personalization_config = RELATED_VIDEOS_PERSONALIZATION
    related_personalization_deps = None
    if personalization_config.get("enabled"):
        related_personalization_deps = RelatedPersonalizationDeps(
            fetch_recent_likes=fetch_recent_likes_request,
            fetch_embeddings_by_ids=fetch_embeddings_by_ids,
            max_likes=int(personalization_config.get("max_likes", MAX_LIKES)),
            alpha=float(personalization_config.get("alpha", 0.0)),
            beta=float(personalization_config.get("beta", 0.0)),
        )

    rate_limiter = RateLimiter(
        DEFAULT_RATE_LIMIT_MAX_REQUESTS, DEFAULT_RATE_LIMIT_WINDOW_SECONDS
    )
    server = SimilarServer(
        (host, port),
        SimilarHandler,
        db,
        similarity_db,
        random_cache_db,
        index,
        dim_value,
        embeddings_count,
        BATCH_SIZE,
        DEFAULT_NORMALIZE_QUERIES,
        DEFAULT_SIMILARITY_CACHE_REFRESH,
        DEFAULT_SIMILARITY_REQUIRE_FULL_CACHE,
        DEFAULT_SIMILARITY_ALLOW_ANN_ON_CACHE_MISS,
        SIMILARITY_SEARCH_LIMIT,
        SIMILARITY_MAX_PER_AUTHOR,
        SIMILARITY_EXCLUDE_SOURCE_AUTHOR,
        recommendation_strategy,
        related_personalization_deps,
        bool(personalization_config.get("enabled")),
        VIDEO_ERROR_THRESHOLD,
        RECOMMENDATIONS_DEBUG_ENABLED,
        DEFAULT_USE_CLIENT_LIKES,
        rate_limiter,
        DEFAULT_POPULARITY_LIKE_WEIGHT,
        DEFAULT_ENABLE_INSTANCE_IGNORE,
        DEFAULT_ENABLE_CHANNEL_BLOCKLIST,
        ENGINE_INGEST_MODE,
        query_encoder,
        search_db,
    )
    # The space id a dislike centroid must carry to be applied: centroids from another
    # model's embeddings would rank against the wrong space.
    server.embeddings_model = embeddings_model

    logging.info("[similar-server] listening on http://%s:%d", host, port)
    logging.info(
        "[service] lifecycle state=start component=engine run_id=%s pid=%d host=%s port=%d",
        run_id,
        os.getpid(),
        host,
        port,
    )
    logging.info("[similar-server] log_mode_hint=%s", active_log_profile)
    logging.info(
        "[similar-server] mode=%s random_cache_refresh=%s random_cache_refresh_interval_minutes=%s",
        "dev" if args.dev else "default",
        "true" if random_cache_refresh else "false",
        random_cache_interval,
    )
    logging.info("[similar-server] ingest_mode=%s", ENGINE_INGEST_MODE)
    logging.info("[similar-server] db=%s index=%s total=%d", db_path, index_path, embeddings_count)
    logging.info("[similar-server] strategy=%s", recommendation_strategy.name)
    random_cache_stop = threading.Event()
    if random_cache_startup_build or random_cache_interval > 0:
        # Started after `server` exists, since it is the owner the swap updates; daemon, so an in-progress build dies with the interpreter instead of delaying shutdown.
        threading.Thread(
            target=run_random_cache_worker,
            args=(
                db_path,
                random_cache_path,
                DEFAULT_RANDOM_CACHE_SIZE,
                DEFAULT_RANDOM_CACHE_FILTERED_MODE,
                DEFAULT_RANDOM_CACHE_MAX_PER_INSTANCE,
                DEFAULT_RANDOM_CACHE_MAX_PER_AUTHOR,
                server,
                random_cache_stop,
                random_cache_startup_build,
                random_cache_interval * 60,
            ),
            name="random-cache-refresh",
            daemon=True,
        ).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        if stop_reason == "unknown":
            stop_reason = "keyboard_interrupt"
        logging.info(
            "[service] lifecycle state=stop component=engine run_id=%s pid=%d reason=%s",
            run_id,
            os.getpid(),
            stop_reason,
        )
    finally:
        # Not joined: the worker skips a swap once this is set, and a build still running dies with the daemon thread.
        random_cache_stop.set()
        signal.signal(signal.SIGINT, previous_sigint)
        signal.signal(signal.SIGTERM, previous_sigterm)
        server.server_close()
        db.close()
        if similarity_db is not None:
            similarity_db.close()
        # The handle the worker last swapped in, not the startup one it may already have closed; taken under the lock so no read is mid-flight on it.
        with server.random_cache_lock:
            live_random_cache_db = server.random_cache_db
            server.random_cache_db = None
        if live_random_cache_db is not None:
            live_random_cache_db.close()


if __name__ == "__main__":
    main()
