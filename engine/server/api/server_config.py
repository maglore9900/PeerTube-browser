"""Provide server config runtime helpers."""

import os


def _resolve_mode_env(name: str, default: str) -> str:
    """Handle resolve mode env."""
    raw = os.environ.get(name, default).strip().lower()
    return raw if raw in {"bridge", "activitypub"} else default


def _resolve_log_profile_env(name: str, default: str) -> str:
    """Handle resolve log profile env."""
    raw = os.environ.get(name, default).strip().lower()
    return raw if raw in {"verbose", "focused"} else default


def _resolve_positive_int_env(name: str, default: int) -> int:
    """Handle resolve positive int env."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        value = 0
    if value < 1:
        # Exit rather than fall back: a mistyped retention window would otherwise silently delete or keep data on the wrong schedule.
        raise SystemExit(f"{name} must be a positive integer, got {raw!r}")
    return value


def _resolve_non_negative_int_env(name: str) -> int | None:
    """Return a non-negative int from the environment, or None when unset or blank; exit on anything else."""
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return None
    try:
        value = int(raw)
    except ValueError:
        value = -1
    if value < 0:
        # Exit rather than fall back: a mistyped interval would otherwise silently rebuild the cache on the wrong schedule, or never.
        raise SystemExit(f"{name} must be a non-negative integer, got {raw!r}")
    return value


def _resolve_weight_env(name: str, default: float) -> float:
    """Return a non-negative finite float from the environment, or `default` when unset; exit on anything else."""
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError:
        value = -1.0
    if not (0.0 <= value < float("inf")):
        raise SystemExit(f"{name} must be a non-negative number, got {raw!r}")
    return value


def _resolve_flag_env(name: str) -> bool:
    """Handle resolve flag env: true only for 1, true or yes in any case, false for any other value, blank or unset."""
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes"}


# Pool size for popular candidates (0 uses per-request limit).
DEFAULT_POPULAR_POOL_SIZE = 5000
# Pool size for fresh candidates (0 uses DEFAULT_SIMILAR_PER_LIKE).
DEFAULT_FRESH_POOL_SIZE = 5000

# Recommendation pipeline configuration and batch sizing.
# Notes:
# - Profiles allow distinct behavior for "home" (no seed) and "upnext" (seed).
# - gather_ratio sets candidate fetch share; mix_ratio sets output mix (with fallback when a layer is short).
# - overfetch_factor inflates per-layer fetch sizes to survive filters/dedup.
# - scoring combines similarity/freshness/popularity (+ layer bonus) into final score.
# - layers (explore/exploit/fresh) are mixed by configured ratios with fallback order.
# - soft_caps are applied after mixing to enforce diversity constraints.

RECOMMENDATION_PIPELINE = {
    "default_profile": "home",
    "profiles": {
        "home": {
            # Total items returned per feed batch.
            "batch_size": 48,

            # Fetch extra per layer to improve fill rate after filtering/dedup.
            # 2 means "fetch ~2x more than needed per layer" to compensate for filters.
            "overfetch_factor": 1,
            "generators": {
                # gather_ratio controls candidate fetch share; mix_ratio controls output share.
                # shuffle applies within the generator pool before scoring.
                # enabled toggles generator participation.
                "random": {
                    "enabled": True,
                    "gather_ratio": 0.1,
                    "mix_ratio": 0.1,
                    "shuffle": True,
                    "below_explore_min": True,
                    "explore_min": 0.2,
                    "max_per_instance": 5,
                    "max_per_author": 2,
                },
                "popular": {
                    "enabled": True,
                    "gather_ratio": 0.1,
                    "mix_ratio": 0.1,
                    "shuffle": True,
                    "pool_size": DEFAULT_POPULAR_POOL_SIZE,
                    # With likes, draw by similarity ** alpha instead of uniformly; 0/None/missing keeps the uniform draw.
                    "weighted_random_alpha": 1.0,
                    "max_per_instance": 5,
                    "max_per_author": 2,
                },
                "explore": {
                    "enabled": True,
                    "gather_ratio": 0.2,
                    "mix_ratio": 0.2,
                    "shuffle": True,
                    "pool_size": 5000,
                    "similarity_min": 0.2,
                    "similarity_max": 0.4,
                    "requires_likes": True,
                    "max_per_instance": 5,
                    "max_per_author": 2,
                },
                "exploit": {
                    "enabled": True,
                    "gather_ratio": 0.5,
                    "mix_ratio": 0.5,
                    "shuffle": True,
                    "pool_size": 2000,
                    "exploit_min": 0.4,
                    "requires_likes": True,
                    "max_per_instance": 5,
                    "max_per_author": 2,
                },
                "fresh": {
                    "enabled": True,
                    "gather_ratio": 0.1,
                    "mix_ratio": 0.1,
                    "shuffle": True,
                    "pool_size": DEFAULT_FRESH_POOL_SIZE,
                    "max_per_instance": 5,
                    "max_per_author": 2,
                },
            },
            # Order for candidate collection and fallback when a layer runs out.
            "mixing": {"order": ["explore", "exploit", "popular", "random", "fresh"]},
            # Scoring configuration for unified ranking.
            "scoring": {
                # Weights for feature aggregation into final score.
                # Higher weight = stronger influence on final order.
                # similarity=1.0 is the baseline; freshness/popularity are smaller nudges.
                "weights": {"similarity": 1.0, "freshness": 0.25, "popularity": 0.2},
                # Per-layer additive bonus to nudge sources up/down.
                # Example: exploit +0.15 shifts high-similarity candidates upward.
                "layer_weights": {
                    "exploit": 0.15,
                    "explore": 0.05,
                    "popular": 0.05,
                    "random": 0.0,
                    "fresh": 0.05,
                },
                # Half-life (days) for freshness decay.
                # 14 => score halves every ~14 days since publish.
                "freshness_half_life_days": 14,
                # Popularity feature weighting (log-normalized internally).
                # likes are weighted more than views in the popularity sub-score.
                "popularity": {"views": 1.0, "likes": 2.0},
            },
            # Optional caps and post-filters.
            # soft_caps.min/max are per-layer constraints applied after ranking.
            # fresh<=12 keeps fresh from dominating (even if scored high).
            "soft_caps": {"max": {"fresh": 12}},
            # post_filters removed: limits are enforced per-layer before mixing.
        },
        "guest_home": {
            "batch_size": 48,
            "overfetch_factor": 2,
            "generators": {
                "random": {
                    "enabled": True,
                    "gather_ratio": 0.6,
                    "mix_ratio": 0.6,
                    "shuffle": True,
                    "below_explore_min": False,
                    "explore_min": 0.2,
                    "max_per_instance": 0,
                    "max_per_author": 2,
                },
                "popular": {
                    "enabled": True,
                    "gather_ratio": 0.2,
                    "mix_ratio": 0.2,
                    "shuffle": True,
                    "pool_size": DEFAULT_POPULAR_POOL_SIZE,
                    "max_per_instance": 0,
                    "max_per_author": 2,
                },
                "fresh": {
                    "enabled": True,
                    "gather_ratio": 0.2,
                    "mix_ratio": 0.2,
                    "shuffle": True,
                    "pool_size": DEFAULT_FRESH_POOL_SIZE,
                    "max_per_instance": 0,
                    "max_per_author": 2,
                },
            },
            "mixing": {"order": ["popular", "random", "fresh"]},
            "scoring": {
                "weights": {"similarity": 0.2, "freshness": 0.35, "popularity": 0.45},
                "layer_weights": {"popular": 0.05, "random": 0.0, "fresh": 0.05},
                "freshness_half_life_days": 14,
                "popularity": {"views": 1.0, "likes": 2.0},
            },
            "soft_caps": {"max": {"fresh": 12}},
        },
        "upnext": {
            # Up Next uses the same layers but different scoring/ratios.
            "scoring": {
                # Bias more toward similarity, less toward freshness/popularity.
                "weights": {"similarity": 1.0, "freshness": 0.1, "popularity": 0.1},
                # Longer half-life => freshness decays slower for upnext.
                "freshness_half_life_days": 30,
                "popularity": {"views": 1.0, "likes": 1.0},
            },
            "generators": {
                "random": {
                    "enabled": True,
                    "gather_ratio": 0.2,
                    "mix_ratio": 0.05,
                    "shuffle": True,
                    "below_explore_min": True,
                    "explore_min": 0.25,
                    "max_per_instance": 5,
                    "max_per_author": 2,
                },
                "popular": {
                    "enabled": True,
                    "gather_ratio": 0.2,
                    "mix_ratio": 0.05,
                    "shuffle": True,
                    "pool_size": DEFAULT_POPULAR_POOL_SIZE,
                    "weighted_random_alpha": 1.0,
                    "max_per_instance": 5,
                    "max_per_author": 2,
                },
                "explore": {
                    "enabled": True,
                    "gather_ratio": 0.1,
                    "mix_ratio": 0.1,
                    "shuffle": True,
                    "pool_size": 1200,
                    "similarity_min": 0.25,
                    "similarity_max": 0.55,
                    "requires_likes": True,
                    "max_per_instance": 5,
                    "max_per_author": 2,
                },
                "exploit": {
                    "enabled": True,
                    "gather_ratio": 0.75,
                    "mix_ratio": 0.75,
                    "shuffle": True,
                    "pool_size": 2000,
                    "exploit_min": 0.7,
                    "requires_likes": True,
                    "max_per_instance": 5,
                    "max_per_author": 2,
                },
                "fresh": {
                    "enabled": True,
                    "gather_ratio": 0.05,
                    "mix_ratio": 0.05,
                    "shuffle": True,
                    "pool_size": DEFAULT_FRESH_POOL_SIZE,
                    "max_per_instance": 5,
                    "max_per_author": 2,
                },
            },
            "mixing": {"order": ["explore", "exploit", "popular", "random", "fresh"]},
        },
        "guest_upnext": {
            "scoring": {
                "weights": {"similarity": 1.0, "freshness": 0.1, "popularity": 0.1},
                "freshness_half_life_days": 30,
                "popularity": {"views": 1.0, "likes": 1.0},
            },
            "generators": {
                "random": {
                    "enabled": True,
                    "gather_ratio": 0.4,
                    "mix_ratio": 0.4,
                    "shuffle": True,
                    "below_explore_min": False,
                    "explore_min": 0.25,
                    "max_per_instance": 5,
                    "max_per_author": 2,
                },
                "popular": {
                    "enabled": True,
                    "gather_ratio": 0.4,
                    "mix_ratio": 0.4,
                    "shuffle": True,
                    "pool_size": DEFAULT_POPULAR_POOL_SIZE,
                    "max_per_instance": 5,
                    "max_per_author": 2,
                },
                "fresh": {
                    "enabled": True,
                    "gather_ratio": 0.2,
                    "mix_ratio": 0.2,
                    "shuffle": True,
                    "pool_size": DEFAULT_FRESH_POOL_SIZE,
                    "max_per_instance": 5,
                    "max_per_author": 2,
                },
            },
            "mixing": {"order": ["popular", "random", "fresh"]},
        },
    },
}

# Default number of videos returned per feed batch.
BATCH_SIZE = RECOMMENDATION_PIPELINE["profiles"]["home"]["batch_size"]

# Related videos personalization configuration (watch page).
# enabled: toggles re-ranking of the up-next top-M window by likes; the reranked score is the draw weight and page order.
# alpha: weight for the base similarity score (video-to-video).
# beta: weight for the user similarity score (candidate vs liked embeddings).
# max_likes: max recent likes considered when computing user similarity.
RELATED_VIDEOS_PERSONALIZATION = {
    "enabled": True,
    "alpha": 0.7,
    "beta": 0.3,
    "max_likes": 5,
}

# Number of recent likes to sample for like-based recommendations.
MAX_LIKES_FOR_RECS = 10
# Number of likes stored per user (0 means unlimited).
MAX_LIKES = 100
# FAISS nprobe: higher improves recall, lower improves speed.
DEFAULT_NPROBE = 24
# Use similarity cache for personalized feed (fallback to ANN if cache misses).
DEFAULT_USE_SIMILARITY_CACHE = True
# Whether to L2-normalize query vectors before ANN search.
DEFAULT_NORMALIZE_QUERIES = False
# Precomputed random ANN ids stored for fast random feed responses.
DEFAULT_RANDOM_CACHE_SIZE = 500000
# When enabled, random cache is built with per-instance/author caps.
DEFAULT_RANDOM_CACHE_FILTERED_MODE = True
# Caps applied only when DEFAULT_RANDOM_CACHE_FILTERED_MODE is enabled (0 disables).
DEFAULT_RANDOM_CACHE_MAX_PER_INSTANCE = 0
DEFAULT_RANDOM_CACHE_MAX_PER_AUTHOR = 100
# Run a startup random cache build even when a usable cache exists. The build runs in the background after the Engine listens; this does not govern the periodic rebuilds.
DEFAULT_RANDOM_CACHE_REFRESH = True
# Minutes between background random cache rebuilds when RANDOM_CACHE_REFRESH_INTERVAL_MINUTES is unset and --dev is off (0 disables).
DEFAULT_RANDOM_CACHE_REFRESH_INTERVAL_MINUTES = 60
# Environment override of the rebuild interval; None when unset, so --dev can pick 0. Read it through random_cache_refresh_interval_minutes.
RANDOM_CACHE_REFRESH_INTERVAL_MINUTES = _resolve_non_negative_int_env("RANDOM_CACHE_REFRESH_INTERVAL_MINUTES")


def random_cache_refresh_interval_minutes(dev: bool) -> int:
    """Return the periodic random cache rebuild interval: the environment value when set, else 0 under --dev and the default otherwise."""
    # `is not None`, not truthiness: an explicit value, 0 included, must win over --dev and the default.
    if RANDOM_CACHE_REFRESH_INTERVAL_MINUTES is not None:
        return RANDOM_CACHE_REFRESH_INTERVAL_MINUTES
    return 0 if dev else DEFAULT_RANDOM_CACHE_REFRESH_INTERVAL_MINUTES


# Weight multiplier for likes in the materialized popularity score.
DEFAULT_POPULARITY_LIKE_WEIGHT = 2.0
# Force rewrite similarity cache entries on recommendation requests by default.
DEFAULT_SIMILARITY_CACHE_REFRESH = False
# Number of similar videos cached per seed video.
DEFAULT_SIMILAR_PER_LIKE = 1000
# Require full cache entries (exactly limit rows) before using similarity cache.
DEFAULT_SIMILARITY_REQUIRE_FULL_CACHE = False
# Allow ANN fallback when cache misses/partial in cache-optimized source.
DEFAULT_SIMILARITY_ALLOW_ANN_ON_CACHE_MISS = True
# Absolute ANN search limit for similarity queries (0 means use per-request limit).
DEFAULT_SIMILARITY_SEARCH_LIMIT = 5000
# Max similar videos cached per author/channel (0 disables the limit).
DEFAULT_SIMILARITY_MAX_PER_AUTHOR = 1
# Whether to exclude the source video's author from the cache build.
DEFAULT_SIMILARITY_EXCLUDE_SOURCE_AUTHOR = False
# Up-next (seeded similar) pool: serve-time ANN fallback bounds, relevance floors and the sampling window.
# These govern up-next only; DEFAULT_NPROBE / DEFAULT_SIMILARITY_SEARCH_LIMIT / DEFAULT_SIMILAR_PER_LIKE still govern every other route.
# Initial ANN k for the up-next fallback when the cached pool is short.
SIMILAR_VIDEO_SEARCH_LIMIT = 5000
# Most candidates kept in the up-next pool after filters.
SIMILAR_VIDEO_TOP_K = 300
# Initial FAISS nprobe for the up-next fallback.
SIMILAR_VIDEO_NPROBE = 32
# Pool size below which the up-next fallback runs: one feed batch.
SIMILAR_VIDEO_TARGET_MIN_POOL = BATCH_SIZE
# Hard caps for the fallback's doubling of nprobe and search limit.
SIMILAR_VIDEO_MAX_NPROBE = 128
SIMILAR_VIDEO_MAX_SEARCH_LIMIT = 20000
# Relevance floor for fallback candidates.
SIMILAR_VIDEO_MIN_SCORE = 0.35
# Relaxed floor for the tail fill; nothing below it reaches an up-next pool.
SIMILAR_VIDEO_TAIL_MIN_SCORE = 0.25
# The up-next draw samples from the top M rows, M = factor x limit, capped at the pool size.
SIMILAR_VIDEO_SAMPLE_WINDOW_FACTOR = 4
# Host and port for the similarity server.
DEFAULT_SERVER_HOST = "127.0.0.1"
DEFAULT_SERVER_PORT = 7070
# Default data paths used by the Engine server (repo-root relative).
DEFAULT_DB_PATH = "engine/server/db/whitelist.db"
DEFAULT_INDEX_PATH = "engine/server/db/whitelist-video-embeddings.faiss"
DEFAULT_USERS_DB_PATH = "engine/server/db/users.db"
DEFAULT_SIMILARITY_DB_PATH = "engine/server/db/similarity-cache.db"
DEFAULT_RANDOM_CACHE_DB_PATH = "engine/server/db/random-cache.db"
# Instance caption tracks served by /internal/translate, and the translate worker's jobs and heartbeat; created empty at first start, so a worktree gets its own.
DEFAULT_SUBTITLES_DB_PATH = "engine/server/db/subtitles.db"
# Most queued translate jobs at once; the enqueue CLI and plan 50's route refuse past it.
SUBTITLE_QUEUE_CAP = 50
# Longest audio chunk, in seconds, handed to Whisper; cut at the last silence before it, hard-cut at it otherwise (R2).
SUBTITLE_MAX_CHUNK_SECONDS = 30
# A page-queued translate job that no state read renewed for this long is dropped before it starts or abandoned mid-run (the viewer lease); above Chrome's one-minute timer clamp for hidden tabs.
TRANSLATE_LEASE_MS = 180_000
# A cancel caps the lease to lapse this long from now; above the page's 16 s STATE_POLL_MAX_MS, so a co-viewer still polling renews it first.
TRANSLATE_CANCEL_GRACE_MS = 20_000
# Seconds between the translate worker's heartbeat upserts, idle or busy.
HEARTBEAT_SECONDS = 5.0
# Age in ms up to which the Engine counts a heartbeat as a serving worker; three beats, so one late beat is tolerated.
HEARTBEAT_FRESH_MS = int(HEARTBEAT_SECONDS * 3 * 1000)

# Master switch for the vector half of search. Turning it off degrades search to its
# lexical half, which is the same state the startup identity gate falls back to when the
# encoder model and the index model disagree.
QUERY_ENCODER_ENABLED = True
# Sentence-transformer model used to encode search queries. It must name the same model
# that produced video_embeddings: vectors from two models are not comparable, and the
# server refuses to serve vector search results when they disagree.
QUERY_ENCODER_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
# Seconds a loaded query encoder may sit unused before its weights are released. The
# reload from cache is a fraction of a second, so holding an idle model costs more than
# dropping it. 0 keeps the model resident once loaded.
QUERY_ENCODER_IDLE_SECONDS = 900
# Device for query encoding. One short query is milliseconds on CPU, and a CUDA context
# in the serving process would cost memory permanently for no perceptible gain.
QUERY_ENCODER_DEVICE = "cpu"

# Master switch for the search route. Search runs the only long-running statements in
# the service, so it uses its own read-only connection and installs its deadline while
# holding its own lock. Both are required: a long statement on a connection that another
# request installs a progress handler on deadlocks the whole process.
SEARCH_ENABLED = True

# Search request limits. The token caps bound both the FTS5 query and the encoder input.
SEARCH_DEFAULT_LIMIT = 20
SEARCH_MAX_LIMIT = 100
SEARCH_MAX_QUERY_TOKENS = 16
SEARCH_MAX_TOKEN_LENGTH = 64
# Longest tag the exact-tag mode accepts, in characters after trimming; the longest stored tag is 30.
SEARCH_MAX_TAG_LENGTH = 64
# Candidates each retrieval half contributes before fusion.
SEARCH_CANDIDATE_POOL = 200
# Reciprocal-rank-fusion constant. 60 is the standard value from the original paper.
SEARCH_RRF_K = 60
# Weight of each half's reciprocal-rank term. The vector half leads because it is the one
# that matches meaning across languages; keyword rank adds a smaller push. The weights
# scale rank positions, not scores: at 0.3/0.7 keyword rank 1 is worth vector rank ~82.
# Override with SEARCH_WEIGHT_LEXICAL / SEARCH_WEIGHT_VECTOR at Engine start.
SEARCH_WEIGHT_LEXICAL = _resolve_weight_env("SEARCH_WEIGHT_LEXICAL", 0.3)
SEARCH_WEIGHT_VECTOR = _resolve_weight_env("SEARCH_WEIGHT_VECTOR", 0.7)

# Include cached dynamic stats (views, likes) in API responses.
INCLUDE_DYNAMIC_STATS = True
# Allow returning debug metadata in recommendation responses when debug=1 is passed; off unless RECOMMENDATIONS_DEBUG is 1, true or yes.
RECOMMENDATIONS_DEBUG_ENABLED = _resolve_flag_env("RECOMMENDATIONS_DEBUG")
# Hide videos after this many recorded access errors (0 disables the filter).
VIDEO_ERROR_THRESHOLD = 3

# Rank with the likes carried in the request body; off, every request has none and gets the guest profile.
DEFAULT_USE_CLIENT_LIKES = True
# Max client likes accepted per request.
DEFAULT_CLIENT_LIKES_MAX = 5
# Max `exclude` entries (videos a paging feed has already shown) accepted per request.
DEFAULT_CLIENT_EXCLUDE_MAX = 500
# rat-tail: mirrors the Client's MAX_FOLLOWS, the most channels and accounts together one Following request may name.
MAX_FOLLOW_SOURCES = 1000
# Max JSON body size for recommendation POST requests (bytes).
# rat-tail: sized for a 500-entry `exclude` of the dataset's longest hosts (53 chars) plus a
# profile's four taste vectors, about 74 KB; raise it if hosts grow.
DEFAULT_CLIENT_LIKES_BODY_LIMIT = 131072
# Max disliked videos one /internal/dislikes/centroids request may cluster.
DISLIKE_MAX_ENTRIES = 1000
# Cosine similarity to a dislike centroid below which a candidate is not penalised. Random
# video pairs in this corpus sit at p50 0.24 and p95 0.48, so this penalises only what is
# closer than the background.
DISLIKE_SIMILARITY_FLOOR = 0.5
# Simple in-memory rate limit for API requests (0 disables).
DEFAULT_RATE_LIMIT_MAX_REQUESTS = 60
DEFAULT_RATE_LIMIT_WINDOW_SECONDS = 60
# Wall-clock budget for database work in one request (0 disables). Every request path
# holds one global lock around one connection, so an unbounded statement is an outage.
DEFAULT_STATEMENT_TIMEOUT_SECONDS = 5.0
# Shared secret the Client backend must present on /internal/* bridge routes. Those
# routes write to the interaction event stream, so the Engine fails closed when it is
# unset rather than accepting unauthenticated writes.
ENGINE_BRIDGE_TOKEN = os.environ.get("ENGINE_BRIDGE_TOKEN", "").strip()
BRIDGE_TOKEN_HEADER = "X-Bridge-Token"
# Max events accepted in one /internal/events/ingest batch.
DEFAULT_MAX_INGEST_EVENTS = 100
# Events committed per transaction while the global DB lock is held.
DEFAULT_INGEST_CHUNK_SIZE = 25
# Days a raw interaction event is kept before it becomes eligible for deletion.
INTERACTION_RAW_RETENTION_DAYS = _resolve_positive_int_env("INTERACTION_RAW_RETENTION_DAYS", 30)
# Raw events stripped per transaction while the global DB lock is held.
INTERACTION_RAW_PRUNE_CHUNK_SIZE = 500
# Min seconds between retention strips triggered by /internal/events/ingest.
INTERACTION_RAW_PRUNE_INTERVAL_SECONDS = 3600

# Moderation filters for feed/similar output.
DEFAULT_ENABLE_INSTANCE_IGNORE = True
DEFAULT_ENABLE_CHANNEL_BLOCKLIST = True
# Optional future toggle for /api/video hide behavior.
DEFAULT_HIDE_BLOCKED_IN_VIDEO_API = False

# Bridge contract switch for Engine ingest surface.
# bridge: accept /internal/events/ingest from trusted client service.
# activitypub: bridge endpoint remains disabled; AP subscriber path will own writes.
ENGINE_INGEST_MODE = _resolve_mode_env("ENGINE_INGEST_MODE", "bridge")

# Recommendation/similarity log view mode hint.
# verbose: full stream.
# focused: compact operational subset for live viewer scripts.
DEFAULT_RECOMMENDATIONS_LOG_PROFILE = _resolve_log_profile_env(
    "RECOMMENDATIONS_LOG_PROFILE", "verbose"
)
