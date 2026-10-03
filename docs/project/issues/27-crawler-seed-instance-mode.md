# Crawler mode: start from one instance and its subscriptions

Status: enhancement, wontfix
Origin: task 15, [M4][F3] (roadmap feature F2-M4 "crawler mode with federated scope limitation" is the closer match)

## Problem

There is no crawler mode that starts from one instance and walks its federated subscriptions.

## Proposed solution

A mode taking a seed instance domain, in which the crawler:

1. finds all instances it follows,
2. collects all channels from that instance and its federated instances,
3. collects all videos from those channels.

- CLI parameter for the seed domain (e.g. `--seed-instance`).
- Aligned with the existing instance crawler flags.

## Comments

### Triage

Moved to `enhancement, ready-for-agent`. The work fits in one agent session and in `engine/crawler` alone. It touches no Engine file, so it can run alongside issue 08. No `docs/project/rejected/` entry or ADR covers it.

**Already in the tree (checked against `engine/crawler/src`):**

- `crawl:instances` (`instances-cli.ts`, `crawler.ts`) already reads each host's `/api/v1/server/following` and `/followers`, paged. It takes its start list from the joinpeertube whitelist or `--whitelist-file`. Without `--expand-beyond-whitelist` it keeps only followed hosts that are on the whitelist. With the flag, discovery spreads across the whole federation, in both directions and with no hop limit.
- `crawl:channels` crawls every instance in `crawl.db` and keeps only each host's own channels: federated copies are skipped where `channelHost !== host`. `crawl:videos` crawls those channels.
- So steps 2 and 3 of the request already work once `crawl.db` holds the right instances. The gap is step 1: discovering instances limited to one seed's follows.

**Decided (operator):**

- **Reach:** the seed plus the hosts on the seed's own following list. One hop only: no followers, no transitive walk.
- **Filtering:** the excluded-hosts file applies. The whitelist is neither fetched nor used.
- **Scope by DB:** a seed run owns its own `--db`. Only `crawl:instances` gains the flag. The channels and videos stages run unchanged against that DB. A DB that holds a different crawl is refused, not mixed.
- `CONTEXT.md` defined **Seed instance**. The entry was removed when this issue was shelved.

### Shelved (operator): no current use for a seed catalogue

Closed as `wontfix`. This is a deferral, not a rejection, so there is no `docs/project/rejected/` entry. Roadmap F2-M4 still points here. The brief below is **superseded and must not be built as written**: it delivers a crawl DB that nothing downstream can turn into a catalogue the site serves. Anyone picking this up again starts from these findings:

- **The jobs take paths.** `sync-whitelist.py` takes `--db` (the crawl DB) and `--output-db`. The embeddings, ANN, similarity precompute, random cache and popularity jobs all take paths.
- **`sync-whitelist.py` cannot keep a seed's hosts.** It always fetches the joinpeertube list. In the default `include` mode the hosts it selects are exactly that list. In `exclude` mode they are the source hosts missing from it. No mode keeps every host in the source DB, so every followed host that is not on joinpeertube's list would be dropped. That contradicts the "whitelist is neither fetched nor used" decision above.
- **The Engine has no data-path flags.** `server.py` always reads `whitelist.db`, the `.faiss` index, `similarity-cache.db` and `random-cache.db` under `engine/server/db/` relative to the repo root. `scripts/run-dataset-build.sh` hardcodes `crawl.db` and `whitelist.db`. A seed catalogue could only be served by replacing the full catalogue, or from a separate checkout.
- The choice that was left open when this was shelved:
  - replace a deployment's catalogue with the seed's (a sync mode that keeps all source hosts, plus build-script options; probably one brief);
  - serve it beside the full catalogue (Engine path flags as well; plan-sized);
  - feed the seed's hosts into the main crawl (a different feature).

## Agent Brief (superseded, see "Shelved" above)

**Category:** enhancement
**Summary:** Add a seed-instance mode to the instance crawl that fills `crawl.db` with one host plus the hosts it follows, so that the existing channel and video stages crawl only that neighbourhood.

**Current behavior:**
The instance crawl (`crawl:instances`) starts from the joinpeertube whitelist, or from a local whitelist file. It can walk the federation graph through each host's following and followers lists, but only either restricted to the whitelist or unrestricted with no hop limit. There is no way to say "start from this one instance and take what it follows". The channel and video stages crawl every instance stored in the DB and keep only each host's own channels. That part already behaves as needed.

**Desired behavior:**
- `crawl:instances --seed-instance <host>` stores in the DB the seed and every host on the seed's paged `/api/v1/server/following` list, after excluded-host filtering. It stores nothing else. It does not fetch followers, does not walk further from the followed hosts, and does not fetch or read the whitelist.
- The seed and each followed host go through the crawler's existing host normalisation and its `/server/following` host extraction, so that `channel@host` and actor-URL entries resolve to their host. Duplicates and the seed itself appearing in its own list collapse to one row.
- The DB records which seed it belongs to, through the crawl state the store already keeps (key/value).
  - A seed run against an empty or new DB proceeds.
  - A seed run against a DB recorded for the same seed proceeds (a re-run or `--resume`). It adds any newly followed hosts and leaves existing rows alone.
  - A seed run against a DB that holds instances and has no recorded seed (a whitelist crawl), or has a different seed recorded, exits non-zero without writing. The message names the DB and says to use a fresh `--db`.
  - A non-seed `crawl:instances` run against a DB recorded for a seed is also refused, so the two kinds of crawl never mix.
- If `--graph` is given, the seed → followed-host edges are recorded as the existing graph mode records them.
- **Error conditions:**
  - A seed that is itself in the excluded-hosts file is refused before any request.
  - A seed whose following list cannot be fetched (after the existing retry and protocol fallback) makes the run exit non-zero, leaving no partial instance set that claims to be complete.
  - A seed that follows nobody yields a DB holding the seed alone, which is valid.
  - `--seed-instance` combined with `--whitelist-url`, `--whitelist-file` or `--expand-beyond-whitelist` is a usage error. The other existing flags (`--db`, `--exclude-hosts-file`, `--timeout`, `--max-retries`, `--concurrency`, `--resume`, `--graph`) keep their meaning. `--max-instances` caps the followed hosts kept.
- The seed is requested over https first, with the existing http fallback. A seed run has no whitelist URL to take a protocol from.

**Key interfaces:**
- `instances-cli.ts` options: a new `--seed-instance <host>` option. The default (whitelist) mode is unchanged byte for byte when the option is absent.
- `CrawlOptions` (crawler types): gains an optional seed host.
- The crawl entry in `crawler.ts`: a seed branch that builds the instance set from the seed's following list instead of the whitelist, and reuses the existing paged follow fetch, host extraction and excluded-host filtering.
- `CrawlerStore` state: a key recording the seed host, read before any write to decide whether to proceed or refuse.
- `DATA_BUILD.md`, crawler section: the new flag, the one-hop rule, the fresh-`--db` requirement, and the follow-on `crawl:channels` / `crawl:videos` commands run with that same `--db`.

**Acceptance criteria:**
- [ ] Against a stub PeerTube server whose seed follows hosts A and B (spread over more than one page) and is followed by C, a seed run into a new DB stores exactly {seed, A, B}. No followers request is made, and A's and B's following lists are not requested.
- [ ] A followed host listed in the excluded-hosts file is not stored. A seed that is itself excluded exits non-zero with no request made.
- [ ] No request goes to the whitelist URL in seed mode.
- [ ] Re-running the same seed against its own DB succeeds and adds a host the seed newly follows.
- [ ] A seed run against a DB holding a whitelist crawl, or another seed's crawl, exits non-zero, names the DB, and leaves the DB unchanged. A whitelist run against a seed DB exits non-zero likewise.
- [ ] A seed whose following endpoint fails on both protocols exits non-zero.
- [ ] `--seed-instance` with `--whitelist-file`, `--whitelist-url` or `--expand-beyond-whitelist` is rejected as a usage error.
- [ ] `crawl:channels --db <seed db>` then processes only the seed's instance set. This is observed with the stub server, or shown from the instance list the channels stage reads.
- [ ] Without `--seed-instance`, `crawl:instances` behaves exactly as before. The existing crawler tests pass unchanged.
- [ ] `DATA_BUILD.md` documents the seed flow end to end.

**Out of scope:**
- Followers of the seed, and more than one hop. A `--seed-depth` option is not requested.
- Any change to `crawl:channels`, `crawl:videos`, the embedding build, `sync-whitelist.py` or the Engine.
- Merging a seed crawl into the main `crawl.db` or `whitelist.db`.
- Users' channel subscriptions on the seed. "Subscriptions" in this issue means the seed's server follows.
- Applying the Engine's instance denylist. That happens downstream, as it does today.
