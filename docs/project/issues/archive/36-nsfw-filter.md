# Hide NSFW videos by default, with a profile setting and a feed toggle

Status: enhancement, complete
Origin: operator request

## Problem

Feeds show NSFW videos with nothing to hide them. Every video already has an `nsfw` 0/1 column in `whitelist.db`. The crawler fills it, and `/api/video` refreshes it from the source instance (issue 10). `engine/server/data/random_videos.py`, `metadata.py` and `search.py` select it and pass it through, but nothing filters on it. `client/frontend` has no NSFW setting or control.

## Requested behaviour

- **Home:** NSFW videos are hidden by default. A setting in the Profile modal (`#profile-section`) turns the filter off.
- **Recommendations and Random feed modes:** each gets a toggle button for the NSFW filter, on by default.

## Proposed solution

- **Filter in the Engine, not the browser.** The up-next and home like-layer pools are about 17 rows deep, and the mixer fills layer slots by ratio. Dropping flagged rows from a page after it arrives would leave rows missing or pages empty. The Engine should leave NSFW rows out while it builds the pool, so a page is still filled to size.
- **One request parameter,** e.g. `nsfw=0|1`. It needs adding to the gateway allowlist in `client/backend/server.py` (`/recommendations`, `/videos/similar`, and any other route it applies to). A missing parameter means filtered, so a request that omits it never gets NSFW rows.
- **Unknown flags:** `nsfw` can be NULL. Decide whether the filter hides NULL rows or keeps them. Before choosing, measure how many rows are NULL, 0 and 1.
- **Random cache:** `random-cache.db` is prebuilt. The filter either reads the video's flag when the page is drawn, or the cache stores the flag. Check which of these keeps the random draw's page size.

## Open questions

- Q1. How do the Profile setting and the mode toggle combine? One option: the Profile setting sets the default, and the toggle overrides it for that session or mode. The other: the Profile setting only affects feeds that have no toggle.
- Q2. Which surfaces does the filter cover? The request names home, Recommendations and Random. Still open: Hot, Recent, Popular, the up-next feed (`?id=`), search, and channel pages.
- Q3. Where does the setting live? A server-side setting on the profile key (`user_db`, like blocks) follows the key across browsers. A `localStorage` value (like `feedParams:v1`) also works for visitors with no key. Keyless visitors must get the filtered default either way.
- Q4. Does the toggle state persist across reloads, like the feed mode does in `feedParams:v1`?
- Q5. Should a video page opened directly (for example from a link) show a warning when the video is NSFW, or is that out of scope?

## Related

- `10-video-metadata-completeness` (archive): stores and refreshes `nsfw`.
- `17-feed-modes` (archive): the mode switcher and `feedParams:v1`, which the toggle goes next to.
- `07-profile-key-identity` (archive): the profile key a server-side setting would hang off.

## Comments

### Delivered

Delivered by `docs/project/plans/22-36-nsfw-filter.md`. Not yet committed.

- **Q1:** no per-mode toggles, at the operator's decision. The only control is one checkbox in the Profile modal, shown with or without a profile key. The feed-mode switcher is unchanged.
- **Q2:** the filter covers all five home feed modes, the up-next feed (home `?id=` and the video page) and search. `/api/video`, `/api/video/refresh` and `/internal/*` are never filtered. The channels page lists no videos, so it is unaffected.
- **Q3, Q4:** the setting lives in the browser's `localStorage` only, under `nsfwFilter:v1`, and persists across reloads. It is not stored on the profile key and does not follow it to another browser.
- **Q5:** out of scope. A video page opened directly plays the video with no warning.
- **Unknown flags:** NULL counts as not NSFW; only `nsfw = 1` rows are hidden. The operator chose this without a measurement, since no `whitelist.db` is in the tree.
- **Random cache:** unchanged, and no rebuild is needed. The flag is read from `whitelist.db` at draw time, and with the filter on a request makes up to 4 draws to fill its page.
- **Opt-in:** only the exact value `nsfw=1` shows NSFW videos; a missing, empty or any other value filters them.
- **Open:** the likes page still shows liked NSFW videos, because it resolves them through `/internal/videos/metadata`, which is unfiltered. Whether it should hide them is undecided.
- **Behaviour.** For the API contract see `engine/server/README.md`. For how each pool refills past flagged rows see `engine/server/api/recommendations/docs/OVERVIEW.md`. For the gateway see `client/README.md`. For the setting and its control see `client/frontend/README.md`. For why the data layer defaults to unfiltered and the request edge enforces the filter see `docs/project/adr/0007-nsfw-filter-default-at-request-edge.md`.
