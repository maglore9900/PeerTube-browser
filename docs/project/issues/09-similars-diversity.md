# Video page similars: diversity on refresh and larger candidate coverage

Status: enhancement, needs-triage
Origin: task 33, [M3][F2] (marker was wrong in the old tracker: this is similarity work, not API versioning)

## Problem

On the video page (`/api/similar` for up-next), refresh often returns the same small set; for some videos only 1-5 similars are found. Diversity should be stable with and without likes, and similar pools larger.

## Proposed solution

Expand ANN candidate recall (`search_limit`, `top-k`, `nprobe`), add deterministic shuffle/window sampling for the final output, and broaden when the candidate count is low.

- **Config-driven ANN for up-next:** `SIMILAR_VIDEO_SEARCH_LIMIT`, `SIMILAR_VIDEO_TOP_K`, `SIMILAR_VIDEO_NPROBE` in `server_config`, logged at startup.
- **Low-candidate fallback:** below `target_min_pool`, step up `nprobe` and `search_limit` (bounded), optionally relax the similarity floor for a tail fill; stop at enough pool or hard caps.
- **Diversity per refresh:** do not always take the first N; windowed sampling from top-M, weighted random by similarity without replacement, or a daily seed plus request nonce. Keep similarity-weighted preference.
- **Likes vs no likes:** with likes, mix source-video similars with profile-aware candidates keeping source relevance dominant; without likes, still diversify from the source pool.
- **Dedup/quality:** strict dedup by `(video_uuid, instance_domain)`; keep blocked-instance/channel filters; relevance floor before the fallback tail.
- **Observability:** per request log initial pool size, fallback steps, final pool size, sampling mode, unique items returned.

## Validation (from the original task)

- Same video, 10 refreshes: overlap ratio below a threshold while relevance stays acceptable.
- Low-similarity video: fallback expands the pool above the minimum.
- Compare `likes=yes` and `likes=no`.

## Related

- Should settle before `11-fast-similars-response` and `12-similars-on-scroll`, which build the UX on it.
- Should follow `08-stable-ann-ids`.

## Comments
