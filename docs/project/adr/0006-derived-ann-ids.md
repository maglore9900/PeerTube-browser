# ADR-0006: ANN ids are derived from video identity, not the SQLite rowid

Status: accepted
Date: decided while planning issue 08 (stable ANN ids), plan `docs/project/plans/17-stable-ann-ids.md`
Related: ADR-0001 (derived interaction event ids)

## Context

The FAISS index stored `video_embeddings.rowid` as each vector's id. Every reader that turned an index hit or a random-cache entry back into a video looked it up by that rowid. Rowids are positional. `INSERT OR REPLACE` in the merge, the full DELETE+INSERT in `sync-whitelist.py`, `--force` re-embeds and table-rebuild migrations all renumber rows. Any of these without a matching index rebuild, including an updater cycle whose ANN build fails after the merge, leaves the index returning the wrong videos.

## Decision

1. **`ann_id` is derived:** blake2b with an 8-byte digest of `video_id + "::" + normalize_host(instance_domain)`, masked to 63 bits. One helper computes it for every writer. The same video gets the same id in any DB and any process.
2. **It is stored:** `video_embeddings.ann_id INTEGER NOT NULL` with a UNIQUE index. Readers never compute it; they read it.
3. **A collision fails loudly.** An id of 0 counts as a collision too, because FAISS's empty result is `-1` and readers drop ids ≤ 0. No probing for a free id, since that would make an id depend on insertion order. At 890k keys the odds are about 4e-8, and 0 collisions were measured on the live dataset.
4. **Hard cutover.** The index sidecar records `id_source: "video_embeddings.ann_id"`, and the Engine refuses to start on any other id source.

## Consequences

- A stale index can miss videos (deleted, or added since the build), but it can't return the wrong one.
- FAISS can later add or remove single vectors by `ann_id` (F3/F4-M2) without further id work.
- Existing databases need a one-time table rebuild (`migrate-whitelist.py`) and an index rebuild before the Engine starts. The similarity cache is already keyed by `(video_id, instance_domain)` and needs no rebuild.
- Rejected: a separate mapping table (an extra join and a second thing to keep in step), pinning the rowid (still positional), and an assigned counter (staging and prod assign different numbers).
