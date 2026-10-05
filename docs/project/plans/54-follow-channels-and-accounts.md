# Follow channels and accounts

_Status: DRAFT_

## Requirements

### Source issue

`docs/project/issues/59-follow-channels-and-accounts.md`. It asks for the Follow defined in `CONTEXT.md`, which replaces the roadmap's "saved channels" (feed panel I4 and I5, `docs/project/plans/archive/04-feed-parameter-panel.md`):

- a profile's positive mark on a channel (`instance_domain` + `channel_id`) or an account (`account_url`), keyed like a block, where following an account covers every channel it owns;
- a layer of the followed sources' newest videos in the profile's home Recommendations mix;
- a Following feed mode showing only followed sources;
- up-next and the global feed modes left untouched;
- a follow and a block on the same source replacing each other;
- local to this site, never sent over ActivityPub.

The issue's open questions Q1-Q7 are answered below as they land.

### Purpose

The operator set two equal goals (2026-10-04):

- **Catch up:** a feed of the newest videos from the channels and accounts the visitor follows.
- **Steer:** the home Recommendations mix leans towards the sources the visitor follows.

Follow is useful only with both.

### Scope

Set by the operator (2026-10-04):

- **This plan (54):** the per-profile follow store and its routes, the Follow controls, an Engine read of the newest videos from a set of followed sources, and the Following feed mode.
- **Controls:** Follow and Unfollow on the video page, on feed and search cards, and on the channels page (operator, 2026-10-04). The channels page lists channels, so it can offer only a channel follow.
- **Keyless visitors:** treated as blocks treat them (operator, 2026-10-04). The controls show without a key, and a click says a profile is needed, as feed, search and video-page blocking already do ("Blocking needs a profile. Create one from the Profile button."). The Following mode is offered and says the same.
- **Following feed order:** newest first across every followed source, paged by a cursor on `(published_at, video_id)`, so the feed ends only when the followed sources run out (operator, 2026-10-04). The other ordered modes keep their `exclude` paging, and the roadmap's M1 cursor item for them stays separate.
- **Follow limit:** 1000 follows per profile, channels and accounts together, like `MAX_BLOCKS`. Adding one past the limit answers 400 "Follow limit reached (1000)" (operator, 2026-10-04).
- **Managing follows:** a list of the profile's follows, each with an Unfollow button (operator, 2026-10-04). Proposed placement, for the operator to confirm at review: a "Following" section in the home page's Profile modal, beside the existing "Blocked" section (`renderBlocks`, `client/frontend/src/pages/videos/index.ts`), which lists blocks with an Unblock button each.
- **Route:** Rt1, a `following` mode on `/recommendations`, with follows injected by the gateway and new per-source indexes (operator, 2026-10-04; see Routes).
- **The next plan:** the follow layer in the home Recommendations mix. It reuses this plan's Engine read. Until it lands, following something changes only the Following mode.
- **Out of scope:** sending follows over ActivityPub; follows in up-next or the global feed modes; importing follows into a profile.

### Acceptance criteria

**Store and routes (Client backend)**

- **AC1:** a keyed profile can add, list and remove follows. Each follow is either a channel, keyed `(instance_domain, channel_id)`, or an account, keyed `account_url`, and carries a display label. The key and the label always come from the Engine's record, never from the browser. The routes mirror the block routes' shape, rate limits and 401 behaviour.
- **AC2:** a follow can be added from a video, named by `uuid`, `host` and `kind` as blocks are, or, for a channel, from its `(instance_domain, channel_id)`. The channel form answers 404 when the Engine's catalogue does not hold that channel.
- **AC3:** adding a follow removes a block on the same key, and adding a block removes a follow on the same key. Following an account does not remove a block on one of its channels; the gateway still filters that channel's videos out.
- **AC4:** a profile holds at most 1000 follows. Adding one past the limit answers 400 "Follow limit reached (1000)", and adding one already held succeeds without making a duplicate. Deleting the profile deletes its follows.

**Following mode (Engine and gateway)**

- **AC5:** `mode=following` is accepted on unseeded `/recommendations` requests. For a keyed profile, the gateway adds the profile's stored follows to the Engine request, and any follows the browser sent are rejected as an unknown body field. A keyless request for the mode, or one from a profile that follows nothing, answers an empty page with no random fallback.
- **AC6:** the Engine returns the videos from the followed channels and from every channel of the followed accounts, newest first by `(published_at, video_id)`. Each answer carries the cursor for the next page, or none when nothing is left. Given that cursor, the next page starts strictly after the last row the Engine returned, so no video repeats or is skipped across pages, whatever the gateway then filters.
- **AC7:** the mode applies the same filters as the other ordered feeds: the error threshold, serving moderation, the NSFW filter (ADR-0007), and the gateway's blocks and dislikes.
- **AC8:** with the new indexes, a page for any followed set of up to 1000 sources takes its database read in at most 0.1 s, warm, on the dev `whitelist.db`, including the last page and sets of quiet sources. The build reruns the five sets measured above against the new indexes and records the numbers. 0.1 s is three times the 0.03 s that big followed sets take today, and is my proposal for the operator to confirm.
- **AC9:** the indexes exist after a sync run and after an Engine start on an existing database. Both creation paths make them.

**Frontend**

- **AC10:** "Follow channel" and "Follow account" (or "Unfollow …" once followed) appear on the video page beside the block buttons, on feed and search cards beside the card actions, and as "Follow" or "Unfollow" per row on the channels page. Each shows its in-flight and error states the way the block controls do.
- **AC11:** without a profile key, the controls show, and a click says a follow needs a profile, in the wording the block controls use. The Following mode can be chosen, and then says the same instead of a feed.
- **AC12:** the home feed's mode switch offers Following, which is remembered in the URL and `localStorage` like the other modes. It pages on scroll through the cursor until the Engine returns none, then says the feed has ended. With no follows, it says how to follow a channel.
- **AC13:** the Profile modal lists the profile's follows under "Following", one `Channel: <label>` or `Account: <label>` item each with an Unfollow button, built with `textContent`. Unfollowing removes the item.

### Consistency constraints

- The follow store, routes and messages mirror blocks (`client/backend/lib/blocks.py`, `data/blocks.ts`, `renderBlocks`).
- Profile data reaches the Engine only as the gateway injects it after sanitising, never from the browser.
- A new listing path passes `include_nsfw` from the request edge (ADR-0007).
- Indexes are added where the existing ones are created: the sync-stage schema and `ensure_video_indexes`.

### Conflicts

- **`CONTEXT.md` describes all of Follow, while this plan builds only part of it.** Its definition includes the Recommendations layer, which the operator moved to the next plan. Resolution: the glossary stays as it is, and this plan's Out of scope names the layer as the next plan.
- **The channel form of AC2 against the block rule "the browser never supplies a channel id".** In the channel form, the browser names the channel, and the gateway accepts it only once the Engine confirms the channel exists and supplies its label. Proposed, for the operator to confirm at review.

### Checked in the tree (2026-10-04)

- **Profile routes.** The Client backend serves blocks at `GET /api/profile/blocks`, `POST /api/profile/blocks` and `POST /api/profile/blocks/remove` (`client/backend/server.py`). Each is rate-limited and needs `X-Profile-Key`, through `_require_profile`, which answers a single 401 for every failure.
- **The block store.** `client/backend/lib/blocks.py` keys a channel by `(instance_domain, channel_id)` and an account by `account_url`, with `''` in the unused columns. It is capped at `MAX_BLOCKS = 1000`. `block_target` derives the target from the Engine's metadata row for the video.
- **Adding a block takes a video, not a source.** `_handle_block_add` takes a video's `uuid` and `host` plus a `kind`. It resolves the video through the Engine, and `block_target` reads the channel or account from the Engine's own record of it, "so the browser never supplies a channel id or an account URL". Removing a block takes the stored key fields. A channels-page row has no video. It carries `instance_domain` and `channel_id` (`ChannelRow`, `client/frontend/src/types/channels.ts`) but no `account_url`, so a channel follow from that page cannot use the block route's video lookup as it stands.
- **The block list lives in the Profile modal.** `renderBlocks` lists `GET /api/profile/blocks` under "Blocked", one `Channel: <label>` or `Account: <label>` item each with an Unblock button. Labels are set with `textContent`.
- **Profile data reaches the Engine through the gateway.** `_handle_engine_read_proxy_post` drops any body field not allowlisted for the route. For a keyed profile it then replaces the body's `likes` with a sample of the stored likes and adds the stored `dislike_centroids`, so the browser can supply neither. Blocks are not sent to the Engine: the gateway filters rows after the Engine answers.
- **Ordered feeds page through `exclude`.** The gateway rejects an `exclude` longer than `MAX_FEED_EXCLUDE = 500` (`client/backend/server.py:63`), which is where the roughly 500-row end of the ordered feeds comes from.
- **Feed modes.** The Engine accepts `mode` in `FEED_MODES = ("recommendations", "trending", "recent", "random", "popular")` (`engine/server/api/handlers/similar.py:84`) and answers 400 for any other value. `ORDERED_FEED_MODES` are trending, popular and recent.
- **Mix layers.** The home Recommendations mix has five layers: explore, exploit, popular, random and fresh. Each has a `gather_ratio` and a `mix_ratio` (`engine/server/api/server_config.py`, around line 90). They are mixed in the order `["explore", "exploit", "popular", "random", "fresh"]`, and a short layer falls back to the others.
- **No Engine read by source.** Nothing in the Engine lists videos for a set of channels or accounts. `whitelist.db` has no index on `videos.channel_id` or `videos.account_url`. Its `videos` indexes are the primary key, `(published_at DESC, video_id DESC)`, `(popularity DESC)` and `(video_uuid, instance_domain)`. This was checked by `.scratch/follow-channels-and-accounts/whitelist_indexes.py`.
- **Catalogue shape** (same script, dev `whitelist.db`): every one of the 909,004 videos has an `account_url`. The catalogue has 46,680 channels and 37,357 accounts, and 4,156 accounts own more than one channel.

### Measured for the Engine read (2026-10-04)

`.scratch/follow-channels-and-accounts/following_query_timing.py` was run read-only against the dev `whitelist.db` with a warm cache. It runs a newest-first page of 48 rows over a followed set, `WHERE (instance_domain, channel_id) pairs OR account_url IN (...) ORDER BY published_at DESC, video_id DESC`, with today's indexes. Every plan was `SCAN v USING INDEX idx_videos_published`.

- **20 small channels** (under 20 videos each): first page 1.39 s, next page 0.80 s.
- **5 accounts that each own more than one channel:** 0.76 s, then 0.10 s.
- **20 small channels plus 5 accounts:** 0.55 s, then 0.34 s.
- **5 big channels** (over 500 videos each): 0.03 s, then 0.02 s.
- **1000 random channels:** 0.12 s, then 0.16 s.

The scan walks every video newer than the page's oldest followed row. A set of small or quiet sources therefore costs close to a full walk, and so does the last page of any feed. The Engine's statement deadline is 5 s (`DEFAULT_STATEMENT_TIMEOUT_SECONDS`, `engine/server/api/server_config.py:500`).

Indexes on `videos` are created in two places: the sync stage's schema (`sync-whitelist.py`, beside `idx_videos_published`) and `ensure_video_indexes` (`engine/server/data/videos.py`).

## Routes

### Rt1: a `following` mode on `/recommendations`, follows injected by the gateway, new per-source indexes (recommended)

- **How it works:** the browser asks for `mode=following`. For a keyed profile, the gateway adds the profile's stored follows to the Engine request body, after sanitising and in the same way it adds `likes` and `dislike_centroids`, so the browser never supplies them.
- **The Engine read:** the Engine answers newest first over those sources, starting after an opaque cursor, and returns the next cursor, or none at the end.
- **New indexes:** `videos (instance_domain, channel_id, published_at DESC, video_id DESC)` and `videos (account_url, published_at DESC, video_id DESC)`, so each source's newest rows after the cursor are an index range rather than a walk over the whole catalogue.
- **Evidence:** the measurements above, without the indexes. I did not measure with them, because the dev database was opened read-only.
- **Cost:** a mode, a body field and a cursor in the Engine, the gateway and the frontend; two indexes in both creation paths; the one-off index build on the 909k-row table.
- **Risk:** the index build time and size on prod, which I have not measured. The gateway removes blocked and disliked rows after the Engine answers, so a page can come back short, and the cursor must still move past the removed rows.

### Rt1b: as Rt1, with no new index

- **Cost:** saves the indexes.
- **Risk:** 0.8–1.4 s for quiet followed sets and for the last page, measured warm. The feed read holds the shared connection's lock for that time, unlike search, which has its own connection, so it stalls other routes.

### Rt2: the gateway builds the Following feed from a new internal Engine read

- **How it works:** the Client backend calls a new `/internal/...` read for a page of the followed sources' videos and serves the mode itself.
- **Cost:** feed logic moves into the gateway, beside the Engine's other modes rather than among them.
- **Risk:** a second place that knows how to build a feed. It gives no gain over Rt1.

### Rt3: follows stored in the Engine (rejected)

The Engine holds no profile state. Likes, dislikes and blocks all live in the Client's `users.db`.

## High-level plan

_Not started: waiting for the route to be chosen._
