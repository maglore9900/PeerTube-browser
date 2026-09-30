# ADR-0007: The NSFW filter defaults on at the request edge, not in the data layer

Status: accepted
Date: decided while building issue 36 (NSFW filter), `docs/project/issues/archive/36-nsfw-filter.md`

## Context

Every video listing leaves out rows with `videos.nsfw = 1` unless the request opts in with `nsfw=1`. The listing queries live in shared data-layer functions (`data/metadata.py`, `data/random_videos.py`, `data/search.py`, `data/similarity_candidates.py`), and some of their callers must see every video whatever the visitor's setting:

- `/api/video` and `/api/video/refresh`, which play whatever video a link points to.
- The `/internal/*` reads the Client backend uses to resolve likes, blocks and imports (`fetch_metadata_by_ids` and `fetch_metadata_by_uuids` in `api/handlers/internal_client_reads.py`).
- The similarity cache. `ann.compute_similar_items` computes neighbours and `get_similar_candidates` writes them to one cache shared by both settings, so the cache must hold NSFW neighbours too.

## Decision

1. **The data layer defaults to unfiltered.** Every data-layer function that can filter takes `include_nsfw: bool = True`, and applies `NSFW_ALLOWED_SQL` (`data/metadata.py`) or drops rows only when it is False. Callers that must see everything pass nothing.
2. **The filtered default lives at the request edge.** `_handle_similar` (in `api/handlers/similar.py`) parses `nsfw` with `_parse_include_nsfw`, which is True only for the exact string `1`, into the request context. `_handle_search` parses it the same way and passes it to `search_videos`. `fetch_request_include_nsfw()` in `api/request_context.py` returns False when nothing was set, and `RecommendationBuilderDeps.fetch_include_nsfw` defaults to `lambda: False`. A path that forgets to set the flag at the edge therefore stays filtered.
3. **The similarity cache is filtered on read.** The ANN compute and the cache write stay unfiltered; `_build_rows` drops flagged rows when cached or computed entries are turned into rows.

A data layer that defaulted to filtered was rejected: every unfiltered caller above would have to opt out, and one missed opt-out would hide videos from `/api/video`, from the likes page resolution, or poison the shared cache for visitors who opted in.

## Consequences

- **Any new listing path must pass the flag.** A listing that calls a data-layer function without `include_nsfw=fetch_request_include_nsfw()` (or the value its handler parsed) serves NSFW rows to every visitor, because the data layer leaks by default. The request-edge default protects only code that reads the flag.
- A new unfiltered read (a lookup, a resolver, a cache fill) needs no change: the default already serves it.
- The builder reads the flag on every call through `deps.fetch_include_nsfw()`, not once at build time, so one builder serves both settings.
- The random cache stores only rowids and no flag; the flag is read from `whitelist.db` when rows are resolved at draw time, so no cache rebuild follows from this decision.
