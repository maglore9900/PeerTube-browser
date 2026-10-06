# Follow channels and accounts

Status: enhancement, ready-for-agent
Origin: roadmap, "Implementation order" step 2 (Saved channels, feed panel I4 and I5); operator request, 2026-10-04

## Problem

A visitor who likes a channel has no way to see more of it. Their only per-channel controls are negative: a block hides a channel or an account. Nothing keeps a channel or account the visitor wants to come back to, and no feed shows a chosen set of sources.

## Proposed solution

`CONTEXT.md` already defines the term, with **Follow** replacing the roadmap's "saved channels":

- **What a follow is:** a profile's positive mark on a channel (`instance_domain` + `channel_id`) or an account (`account_url`). It is keyed the same way as a block, and following an account covers every channel the account owns.
- **Recommendations layer:** a follow adds a layer of the followed sources' newest videos to the profile's home Recommendations mix.
- **Following feed mode:** a new home feed mode that shows only videos from followed channels and accounts.
- **Follow and block replace each other** on the same channel or account.
- **Nothing else changes:** up-next and the global feed modes (Trending, Recent, Random, Popular) are untouched.
- **Local only:** a follow stays on this site and is never sent over ActivityPub. It is not roadmap F2-M5, the ActivityPub follow logic.

## Checked in the tree (2026-10-04)

- **No follow code exists.** No Engine or Client backend module, route, table or frontend control implements follows. The only "follow" matches in the client code are PeerTube follower counts on the channels page and video page.
- **Blocks are the model to mirror.** `client/backend/lib/blocks.py` stores a profile's blocks in `users.db`, keyed by `(instance_domain, channel_id)` or by `account_url`, with `''` in the unused columns and a cap of `MAX_BLOCKS = 1000`. The Client gateway applies blocks to feed and search rows (`FILTERED_ROUTES` in `client/backend/server.py`). The Engine never sees them.
- **The Engine has no query by source.** No query in `engine/server` (outside a moderation test) selects videos by a set of channels or accounts, so the Following mode and the follow layer need new Engine reads. Filtering at the gateway, as blocks do, cannot build a feed of followed sources.
- **The `(issue 39)` reference in the Follow definition in `CONTEXT.md` is stale.** Issue 39 is now `archive/39-logging-tests-retired-by-request-lifecycle-rename.md`, and no issue file about follows exists.
- **The original design** is `docs/project/plans/archive/04-feed-parameter-panel.md`, C2, I4 and I5. It planned a `localStorage` list. It flagged a conflict with the profile store used by likes, dislikes and blocks, and the `CONTEXT.md` definition settles that conflict in favour of the profile.

## Questions and answers

Answered by plan 54 (`docs/project/plans/54-follow-channels-and-accounts.md`), except Q4.

- Q1. **Controls:** where are Follow and Unfollow offered? **Answer:** on the video page, on feed and search cards, and on the channels page (channel follow only, since a channels-page row has no `account_url`).
- Q2. **Keyless visitors:** do visitors without a profile key see the controls? **Answer:** yes; a click sends no request and shows the profile-needed text.
- Q3. **Following feed order and paging:** **Answer:** newest first by `(published_at, video_id, instance_domain)` DESC, paged by an opaque cursor rather than `exclude`.
- Q4. **Recommendations layer:** what share of the mix does the follow layer take, and does it stay out when the profile follows nothing? **Open:** deferred to the next plan.
- Q5. **Cap:** **Answer:** `MAX_FOLLOWS = 1000` per profile, channels and accounts together; past it, 400 `Follow limit reached (1000)`.
- Q6. **Managing follows:** **Answer:** a Following list in the home page's Profile modal, each item with an Unfollow button. Planned, not yet built.
- Q7. **Engine request size:** **Answer:** the gateway injects the profile's stored follows into the `/recommendations` body after sanitising, so the browser cannot supply them; the Engine caps a request at `MAX_FOLLOW_SOURCES = 1000` sources.

## Related

- `CONTEXT.md`, **Follow** and **Block**.
- `docs/project/plans/archive/04-feed-parameter-panel.md`, C2, I4 and I5.
- `docs/project/plans/archive/07-channel-blocks.md`: the block store this would mirror.
- Roadmap M1, cursor parameter for the ordered feeds: the Following mode already pages by cursor; trending, recent and popular still page by `exclude`.
- Roadmap F2-M5: ActivityPub follow logic, a separate thing.

## Comments

**Triage (2026-10-04):** enhancement, kept at `needs-triage` and sent to `/devsecops:plan` on the operator's call. As `CONTEXT.md` defines it, Follow spans three layers and two feed changes, which is more than one agent brief:

- a per-profile follow store with routes in the Client backend, modelled on blocks;
- Follow and Unfollow controls in the frontend;
- a new Engine read for videos from a set of channels or accounts;
- the Following feed mode;
- a follow layer in the Recommendations mix.

Planning answers Q1-Q7 and may split the work into several builds. None of them was settled at triage.

- **Not already built:** no Engine, Client backend or frontend code implements follows. The only Engine queries by channel are the single-channel lookup in `/api/video` (`api/handlers/video.py`) and operator moderation's `_lookup_blocked_channels` (`data/moderation.py`). Neither lists videos for a set of sources.
- **No prior rejection:** `docs/project/rejected/` does not exist.

**Plan 54 delivered (2026-10-05):** the Catch-up half of the operator's two goals. The 2026-10-04 "Checked in the tree" notes on missing follow code and on the Engine having no query by source no longer hold. What exists now:

- **Store and routes:** a `follows` table in `users.db` (`client/backend/lib/follows.py`, mirroring `blocks.py`) behind `GET /api/profile/follows`, `POST /api/profile/follows` and `POST /api/profile/follows/remove`. A follow is added from a video (`uuid`, `host`, `kind`) or, for a channel, from `(instance_domain, channel_id)` once the Engine's `/internal/channels/resolve` confirms it. A follow and a block on the same key replace each other; deleting a profile deletes its follows.
- **Engine read:** `mode=following` on unseeded `/recommendations` (`_handle_following` in `engine/server/api/handlers/similar.py` over `fetch_followed_page` in `engine/server/data/random_videos.py`), served by `idx_videos_channel_published` and `idx_videos_account_published`, which both index-creation paths build.
- **Gateway:** on a keyed Following read the Client injects the stored follows, drops blocked and disliked rows without over-fetching or trimming, and passes the Engine's cursor through, so a page can be short or empty while still carrying a cursor.
- **Frontend:** Follow and Unfollow controls on feed and search cards, on the video page and on the channels page, and a Following home feed mode that pages by cursor until none comes back.

Still open on this issue:

- the follow layer in the Recommendations mix (Q4, the next plan);
- the Following feed's end note and its follow-nothing and no-videos empty states (an empty Following feed reads "No videos found.");
- the Profile modal's Following list (Q6);
- `channelId` on `/api/video` (`engine/server/api/handlers/video.py`), so the video page labels a followed channel "Unfollow channel" at load;
- reloading the follow list after Create profile, Use key or Delete profile.
