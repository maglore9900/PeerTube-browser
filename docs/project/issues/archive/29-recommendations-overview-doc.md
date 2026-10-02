# Update the recommendation description (RECOMMENDATIONS_OVERVIEW)

Status: enhancement, complete
Origin: task 16, [M8][F5]

## Problem

`RECOMMENDATIONS_OVERVIEW.md` does not match the current recommendation logic.

## Proposed solution

Rewrite the document to describe the whole pipeline:

- data preparation (embeddings, cache, index),
- candidate generation and layer mixing,
- filters, deduplication and mixing rules,
- what the client receives and how the frontend uses it.

## Related

- Best done after the similarity and feed issues (`09`, `16`, `17`) land, or it is rewritten twice.

## Comments

### Triage (2026-10-02): mostly done; narrowed to three gaps

- **No `RECOMMENDATIONS_OVERVIEW.md` exists.** The recommendation overview is `engine/server/api/recommendations/docs/OVERVIEW.md`, next to `LAYER_PARAMS.md` and `PIPELINE_DIAGRAM.md`. Build 09 already pointed the diagram's old link at it.
- **The dependencies have landed.** 09, 16 and 17 are archived. Their builds, and 36 (NSFW filter), each updated the overview in their docs step.
- **What the overview already covers:** data preparation, candidate layers, fetch limits, unified scoring, the dislike penalty, mixing and fallback, exclude and paging per mode, the NSFW filter, and post-filters.
- **What is left:**
  1. The "Likes Source" section says that with client likes disabled, likes are read from `users.db`. The Engine has no such fallback: `fetch_recent_likes_request` returns request-carried likes only.
  2. That section is framed as a temporary no-auth mode. It does not mention profile keys, where the Client backend sends the profile's likes and dislike taste vectors.
  3. "What the Client Receives" covers only the Engine's batch. It leaves out the Client backend's per-profile filtering, over-fetch and reaction marks (documented in `client/README.md`), and the frontend's paging. The document's title still says "Home Recommendations".

The maintainer chose a narrowed doc-only brief over a full rewrite. The overview is current because each build maintained it, and a rewrite risks losing detail those builds checked.

### Delivered

A doc-only edit to `engine/server/api/recommendations/docs/OVERVIEW.md` closed the three gaps. The title and short version now cover every feed mode and Up Next. The "Likes Source" section now names both sources of request likes (the browser's local likes when keyless, the profile's likes substituted by the Client backend when keyed) and states that the Engine has no stored-likes fallback. Section 8 now covers the Engine batch, the gateway's filtering, over-fetch, `reaction` marks and short ordered-feed pages (linking `client/README.md`), and the frontend pager in each mode. No sentence outside those three areas was changed.

## Agent Brief

**Category:** enhancement
**Summary:** Bring the recommendation overview document up to date in three places: where likes come from, what happens between the Engine's batch and the page, and its title.

**Current behavior:**
The Engine's recommendation overview (`OVERVIEW.md` in the recommendations docs directory, beside `LAYER_PARAMS.md` and `PIPELINE_DIAGRAM.md`) describes the pipeline accurately for every feed mode and up-next, with three exceptions:

1. Its likes-source section says that when client-supplied likes are disabled, the Engine reads likes from `users.db`. In the code, `fetch_recent_likes_request` returns only the likes carried on the request, and returns none when client likes are off. Nothing reads likes from a users database.
2. The same section presents client-supplied likes as a temporary no-auth mode fed from the browser's storage. Since profile keys exist, a request that carries `X-Profile-Key` reaches the Engine with the profile's likes, which the Client backend substitutes for the browser's. Dislike taste vectors (`dislike_centroids`) also come from the Client backend. The section mentions neither.
3. Its final section, on what the client receives, covers only the Engine's ordered batch and its `seed` field. It does not say that the Client backend's read gateway, for a keyed request:
   - removes the profile's blocked channels and accounts, and on feeds its disliked videos;
   - over-fetches twice the page so the page stays full;
   - marks rows with `reaction`;
   - can return short pages in the fixed-order feeds.
   It also does not say how the frontend pages a feed. The document is titled for home recommendations only, though it covers every mode and up-next.

**Desired behavior:**
- The likes-source section says that the Engine ranks only with the likes carried on the request, and that with client likes disabled a request has none and gets the guest profile. It says where the request's likes come from: the browser's local likes for a keyless visitor, and the profile's likes, substituted by the Client backend, for a keyed one. The likes cap and the 400 answers stay as they are. The "temporary no-auth" framing and the `users.db` sentence are gone.
- The final section describes the whole path from the Engine's batch to the page:
  - the Engine's ordered batch and `seed`, as now;
  - the Client backend's per-profile filtering, over-fetch and reaction marks, stated in a few sentences, with a link to `client/README.md` for the full contract rather than a copy of it;
  - how the frontend asks for the next page in each kind of feed: home and the ordered feeds send shown rows as `exclude`, up-next asks for batches and shows them in steps, and random does not use `exclude`. Point to the exclude rules already in section 1 instead of repeating them.
- The title, and the short version under it, describe the document's real scope: every feed mode and up-next.
- Every sentence the agent adds or changes matches the current code. Where the agent finds another sentence that contradicts the code while doing this, it fixes that sentence and lists it in its report.

**Key interfaces:**
- `fetch_recent_likes_request` (the Engine's request context): the source of truth for where ranking likes come from.
- The Client backend's read gateway for `/recommendations`, `/videos/similar` and `/api/v1/search/videos`: per-profile filtering, over-fetch and `reaction` marks, as documented in `client/README.md`.
- The frontend's feed and up-next pagers: what each sends to ask for the next page.

**Acceptance criteria:**
- [ ] The overview no longer says likes are read from `users.db`, nor calls client likes a temporary no-auth mode.
- [ ] The likes-source section names both sources of request likes (browser local likes when keyless, profile likes substituted by the Client backend when keyed) and says the Engine has no stored-likes fallback.
- [ ] The final section names the Client backend's block and dislike filtering, its twice-the-page over-fetch, the `reaction` marks, and the short pages possible in ordered feeds, and links to `client/README.md`.
- [ ] The final section says how the frontend requests the next page for home, the ordered feeds, up-next and random, consistent with section 1's exclude rules.
- [ ] The title and opening summary cover all feed modes and up-next.
- [ ] Every link in the overview resolves to an existing file. No file in the repo links to `RECOMMENDATIONS_OVERVIEW.md`.
- [ ] The agent's report lists each sentence changed outside the three areas above and the code that showed it was wrong, or says there were none.

**Out of scope:**
- Rewriting or restructuring sections 1 to 7 beyond the likes-source section and sentences found to contradict the code.
- `LAYER_PARAMS.md` and `PIPELINE_DIAGRAM.md`, except a link that would otherwise break.
- Copying the Client backend's gateway contract or the Engine README's parameter contracts into the overview.
- Any code change.
