# Fast response with similars on the video page

Status: enhancement, needs-triage
Origin: task 1, [M2][F1]

## Problem

Until the server receives a response from the source instance, the client shows an empty page; some instances respond slowly.

## Proposed solution

Show similar videos first (fast, from the local DB), then load the current video's metadata when it arrives.

- Opening the video page starts two independent requests in parallel: similars, and metadata for the current video.
- The server answers the similars request immediately from local cache/DB, without waiting for the instance.
- Metadata refresh goes through a separate request to the instance, is saved to the DB, and updates the UI.

## Related

- After `09-similars-diversity`; before `12-similars-on-scroll`.

## Comments

- 2026-09-27 — Latency from `09-similars-diversity` (plan 19). A seed whose filtered cached pool holds fewer than `SIMILAR_VIDEO_TARGET_MIN_POOL` (48) rows, or that has no cache entry, runs a live ANN fallback in `get_upnext_candidates`. That covers nearly every seed today, because the precompute keeps 20 per seed. The fallback runs up to three `search_similar_above` searches (nprobe 32/64/128, k 5000/10000/20000), each under the global `index_lock` that home and search share. The pool can reach `SIMILAR_VIDEO_TOP_K` (300) rows, so the metadata fetch and the dislike-penalty scoring cover up to 300 rows per request. Raising the precompute `--top-k` and rebuilding `similarity-cache.db` removes most of this cost (see `DATA_BUILD.md`, step 5).
