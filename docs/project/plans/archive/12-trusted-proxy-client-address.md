# Resolve the client address once, trusting X-Forwarded-For only from configured proxies

## Requirements

### What was asked for

Build issue `docs/project/issues/02-trusted-proxy-client-address.md` as triaged: Resolve the client address once, trusting `X-Forwarded-For` only from a configured proxy, and key every limiter and the Engine's `X-Client-IP` on it. The Agent Brief below, copied from the issue, is the confirmed requirement set; the build starts from this file.

### Purpose

Close the security-audit finding the issue records. This build is one of issues 01-06, delivered concurrently to use as little operator time and cause as few merge conflicts as possible.

### Decisions this rests on

`docs/project/adr/0002-trusted-proxy-client-address.md`; `CONTEXT.md` **Client address**.

### Agent Brief

**Category:** bug
**Summary:** Resolve the client address once, trusting `X-Forwarded-For` only from a configured proxy, and key every limiter and the Engine's `X-Client-IP` on it

**Current behavior:**
The Client backend has two address rules and both are wrong behind a reverse proxy. Its rate limiters (the per-route limiter and the `/api/profile` mint limiter) key on the TCP peer, so behind nginx every visitor shares one bucket. Its client-IP resolver returns the first `X-Forwarded-For` hop (then `X-Real-IP`) from any peer. Because nginx's `$proxy_add_x_forwarded_for` appends to whatever the browser sent, that first hop is chosen by the caller. The value is forwarded to the Engine as `X-Client-IP`, which keys the Engine's limiter, so rotating the header bypasses it. The same value goes into the access log. The Engine takes `X-Client-IP`, then falls back to `X-Forwarded-For`, `X-Real-IP`, and the peer.

**Desired behavior:**
- **One resolution rule** in the Client backend. If the TCP peer address is in the trusted-proxy set and the request carries a non-empty `X-Forwarded-For`, the client address is its **last** comma-separated hop, trimmed. Otherwise it is the TCP peer address. `X-Real-IP` is ignored. If the peer is trusted but the last hop is empty or not a valid IP address, fall back to the peer.
- **Configuration.** The Client backend reads `TRUSTED_PROXIES` from the environment: comma-separated IPv4/IPv6 addresses and CIDR ranges, whitespace tolerated. Unset or empty means the default `127.0.0.1,::1`. A malformed entry makes the backend refuse to start with an error naming the entry. IPv4-mapped IPv6 peers (`::ffff:127.0.0.1`) match their IPv4 entry.
- **Every consumer uses that rule:** the per-route rate limiter key, the profile-creation (mint) limiter key, the `X-Client-IP` header sent on every Engine request, and the `ip` field of the access log.
- **Engine.** Its client-IP resolution becomes: `X-Client-IP` if present and non-empty, otherwise the TCP peer. It no longer reads `X-Forwarded-For` or `X-Real-IP`.
- `DEPLOYMENT.md` states `TRUSTED_PROXIES`, its loopback default, and that each additional proxy layer must be listed.

**Key interfaces:**
- The Client backend handler's client-IP method (currently `_get_client_ip`): replaced by, or reimplemented as, the single rule. The rule should be a pure function of `(peer address, X-Forwarded-For value, trusted set)` so it can be tested without a socket.
- The Client backend's `_rate_limit_check` and the `/api/profile` mint-limiter call: key on the resolved address, not `client_address[0]`.
- The Client backend server object: holds the parsed trusted set, built once at startup (the stdlib `ipaddress` networks are sufficient).
- The Engine handler's `_get_client_ip`: `X-Client-IP`, else peer.

**Acceptance criteria:**
- [ ] With the peer `127.0.0.1` and `X-Forwarded-For: 6.6.6.6, 203.0.113.9`, the resolved address is `203.0.113.9`.
- [ ] With the peer `198.51.100.7` (not trusted) and any `X-Forwarded-For`, the resolved address is `198.51.100.7`.
- [ ] With a trusted peer and no `X-Forwarded-For`, or a last hop that is not an IP, the resolved address is the peer.
- [ ] `TRUSTED_PROXIES=10.0.0.0/8` trusts peer `10.1.2.3` and no longer trusts `127.0.0.1`.
- [ ] A malformed `TRUSTED_PROXIES` entry stops startup with an error naming it.
- [ ] Behind a trusted peer, two requests with different last hops land in different rate-limit buckets for one route, and two requests that differ only in the *first* hop share one bucket. This holds for the per-route limiter and the mint limiter.
- [ ] The `X-Client-IP` header the Client backend sends to the Engine equals the resolved address.
- [ ] The Engine, given `X-Forwarded-For` and `X-Real-IP` but no `X-Client-IP`, keys its limiter on the TCP peer.
- [ ] `DEPLOYMENT.md` documents `TRUSTED_PROXIES`.

**Out of scope:**
- Rate-limit sizes and windows.
- Adding rate limiting to `/internal/*` Engine routes.
- `X-Forwarded-Proto` / `Host` handling in `_get_full_url`.
- Supporting the Engine bound on a non-loopback address.
- The nginx configuration itself, which already sends `X-Forwarded-For`.

### Consistency constraints

- Match the surrounding code's style: stdlib HTTP handlers, `respond_json`, module-level named constants, and env vars read once at startup.
- Backwards compatibility is not required beyond what the brief states.
- Run `validate_tests.py` from the root of the tree this build runs in (a worktree for waves 1-2, main for wave 3). That tree's `.un` config carries it as `project_dir`.

### Batch context

Part of the security hardening batch (`.scratch/security-hardening-batch/notes.md`): issues 01-06 delivered in three waves of git worktrees. Wave 1 is plans 10, 11 and 12. Wave 2 is 13 and 14, branched from main after wave 1 merges. Wave 3 is 15, on the merged main. A wave 1 or 2 build runs in its own worktree created by `.scratch/security-hardening-batch/worktree-setup.sh`, merges to main when it closes, and is harvested on main, not in the worktree.

Wave 1. It shares `client/backend/server.py` with plans 13-15 (later waves), `engine/server/api/handlers/similar.py` with plan 11 (a different function), and `DEPLOYMENT.md` with plan 15.

### Conflicts

The brief does not conflict with the tree. Every function and line it names was checked against the source on 2026-09-26 (`.scratch/security-hardening-batch/notes.md`, File overlap). Line numbers will drift once earlier waves merge, so re-locate by function name at Step 3.

## High-level plan

### Approach

**Rule.** A pure function in the Client backend takes the peer address, the `X-Forwarded-For` value and the trusted set. If the peer is in the set and the last trimmed `X-Forwarded-For` hop is a valid IP, it returns that hop; otherwise it returns the peer. IPv4-mapped IPv6 peers are unmapped before the membership check. `X-Real-IP` is not read.

**Config.** `TRUSTED_PROXIES` is parsed once at startup with `ipaddress` into networks held on the server object. Unset or empty means `127.0.0.1,::1`. A malformed entry raises at startup with an error naming the entry.

**Consumers.** `_get_client_ip` (`server.py:171`) is reimplemented on the rule, and all four consumers read it: the access log (`:202`), the mint limiter (`:280`), `_rate_limit_check` (`:350`) and the `X-Client-IP` header (`:527`). Today `:280` and `:350` read `client_address[0]` directly.

**Engine.** `_get_client_ip` in `engine/server/api/handlers/similar.py:283` returns `X-Client-IP` when it is non-empty, and the peer otherwise.

**Docs.** `DEPLOYMENT.md` documents `TRUSTED_PROXIES`, its loopback default, and that every proxy layer must be listed.

### Alternatives considered

- **The first `X-Forwarded-For` hop** (the audit's suggested fix). Rejected by ADR-0002: nginx appends to the caller's header, so the caller chooses the first hop.
- **Fixing each call site separately.** Rejected: that is how the two rules diverged, which is the bug.
- **Keeping the Engine's `X-Forwarded-For` fallback.** Rejected by ADR-0002: the Engine binds loopback, and its only peer is the Client backend.

### Risks and limitations

- A deployment with several proxy layers that does not list them all will key on the inner proxy. This is documented, not detected.
- Existing tests that send `X-Forwarded-For` from a loopback peer and expect the first hop will now resolve differently. The build's Step 0 baseline will show them.
- The engine test fixture calls the Engine directly, not through the Client, so the Engine gets no `X-Client-IP` and keys on the peer. The harness behaves as it does today.
- **Shared `whitelist.db`.** The worktree symlinks the main tree's `whitelist.db`, so this build's test Engines write interaction rows into the same file as other lanes, and as the live Engine if it runs. Every test run already does this; worktrees only make it concurrent.
- **Tracked test record.** `tests/last_test_validation.json` and `tests/last_test_output.txt` always conflict on merge. Take main's copy and re-run `validate_tests.py --compare` on the merged tree.
- **Engine rate limit.** Run Engine-backed test files in their own `validate_tests.py` invocations (memory `engine-rate-limit-single-lane-test-runs`).

### Tradeoffs accepted

A deployment with several proxy layers must list every layer in `TRUSTED_PROXIES`.
