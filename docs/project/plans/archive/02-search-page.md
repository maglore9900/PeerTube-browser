# Video search page

Status: delivered. Migrated from the retired `dev/FEATURE_PLANS.md` (feature `F10-M2`, milestone M2, old tasks 92, 93, 10, 94). Built before the switch to devsecops, so there is no dev_flow build record; the operator accepted it as delivered at migration.

## Requirements

### What was asked

`GET /api/v1/search/videos` (archive 01) was live through the gateway, but nothing in the frontend called it: no search page, no search control, no link. Deliver the consuming half — one page, its data client, and the navigation that reaches it.

### Scope

- **S1 Shared video-card module.** `renderCard` and its helpers move to `client/frontend/src/components/video-card.ts`, used by both the videos page and search. A move, not a redesign: the feed must render identically.
- **S2 Search data client.** `client/frontend/src/data/search.ts` with `fetchSearchResults({ q, page, limit, sort })` on `resolveClientApiBase` and `fetchJsonWithCache`, plus `SearchPayload`/`SearchRow` in `src/types/videos.ts`. Sends only the four allowlisted parameters.
- **S3 The page.** `search.html` plus `src/pages/search/index.ts`: query input, sort control with the API's four values, results grid, result count, "Load more".
- **S4 URL as state.** `?q=&sort=&page=` read on load and written on change.
- **S5 Explicit states.** Idle, loading, empty, error, and the Engine's 503 (no FTS index yet).
- **S6 Out-of-order protection.** A `requestSeq` guard.
- **S7 Reachability.** A `Search` nav link on `index.html`, `videos.html`, `channels.html`, `video-page.html`.
- **S8 Build wiring.** A rollup input in `vite.config.ts` and `/search` dev/preview rewrites.

### Out of scope

Ranking and fusion changes; filters beyond `sort`; a header search box on every page and suggestions; saved searches and history; `videos.css` changes beyond the extraction.

### Acceptance criteria

1. `/search?q=<term>` renders cards linking to the video page with the feed's parameters.
2. Search and home feed cards come from one module; the feed renders identically to before.
3. Changing sort re-queries and reorders; all four values work.
4. "Load more" appends without duplicates or skips and disappears at `total`.
5. Reloading a result URL reproduces query, sort and page; back returns to the previous result set.
6. No matches shows an empty state naming the term.
7. With the Engine stopped, an error state renders.
8. Without `videos_fts`, the 503 renders as "search is not ready yet".
9. Fast typing never renders a stale query's results.
10. HTML in a title or channel name renders literally.
11. Reachable in three clicks or fewer from home.
12. `npm run build` emits `dist/search.html`; `/search` resolves in dev, preview and production.
13. `tests/check-frontend-client-gateway.sh` and `tests/check-client-engine-boundary.sh` pass.

## High-level plan

### Resolved decisions

- **O1 — ships against the current ranking**, which favours same-language results (first Cyrillic result around rank 19-60 for English queries). Tuning waits until real result pages have been judged.
- **O2 — extract the card, do not copy it**: two copies are two places to fix an escaping bug.
- **O3 — "Load more", not infinite scroll.**
- **O4 — one dedicated page**, not a modal or header instant search.
- **O5 — `vectorSearch` is not shown in the UI.**

### Risks carried forward

- The card component is shared by the home feed: any change to it is visible on the most-used page. Feed-specific behaviour (cached stats, debug block) is passed in, not moved.
- `total` counts the fused candidate pool, capped by the Engine's pool size, not the corpus; UI wording must not promise a corpus total.
- Production serves rsynced `dist/`; a page not rebuilt and copied 404s under `try_files`.
- The gateway rejects unlisted parameters with 400; any new search filter needs the allowlist changed in the same change.

## Impacts

Not recorded: built outside dev_flow. Files touched are in commit `45180d6` (`client/frontend/src/components/video-card.ts`, `src/data/search.ts`, `src/pages/search/index.ts`, `src/pages/videos/index.ts`, `src/search.css`, `src/types/videos.ts`, `search.html`, the four page headers, `vite.config.ts`, `dist/`, `DEPLOYMENT.md`).

## Implementation plan

Not recorded: built outside dev_flow.

## Inner unit tests

None under devsecops.

## Close

Delivered in commit `45180d6`. Clause accounting and `--compare` do not apply: no dev_flow build. Which acceptance criteria were verified before migration is not recorded; the operator verifies frontend behaviour manually in a browser.
