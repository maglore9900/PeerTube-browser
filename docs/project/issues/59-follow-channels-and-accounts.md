# Follow channels and accounts

Status: enhancement, needs-triage
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

## Open questions

- Q1. **Controls:** where are Follow and Unfollow offered? On feed and search cards next to Block channel and Block account, on the video page, on the channels page, or a combination?
- Q2. **Keyless visitors:** a follow belongs to a profile. Does a visitor without a profile key see the controls (with a prompt to create a profile, as blocking does on the video page), or not see them?
- Q3. **Following feed order:** newest first across all followed sources? How does it page, given the ordered feeds' `exclude` limit of about 500 rows (roadmap M1, cursor item)?
- Q4. **Recommendations layer:** what share of the mix does the follow layer take, and does it stay out when the profile follows nothing?
- Q5. **Cap:** a follow limit like `MAX_BLOCKS`, and what happens when it is reached?
- Q6. **Managing follows:** a list of followed sources that can be unfollowed, like My likes?
- Q7. **Engine request size:** how does the Client send the followed set to the Engine? The set could reach the cap, and taste vectors are already sent in the request body.

## Related

- `CONTEXT.md`, **Follow** and **Block**.
- `docs/project/plans/archive/04-feed-parameter-panel.md`, C2, I4 and I5.
- `docs/project/plans/archive/07-channel-blocks.md`: the block store this would mirror.
- Roadmap M1, cursor parameter for the ordered feeds: the Following mode would inherit the same paging limit.
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
