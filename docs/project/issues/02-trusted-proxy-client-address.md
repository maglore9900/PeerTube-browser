# Trusted-proxy client address resolution shared by both services

Status: bug, ready-for-agent
Origin: task 81, SI3-M1 — security audit run 1, finding F6

## Problem

The Client backend buckets on the TCP peer (the proxy) while the Engine trusts `X-Forwarded-For` unconditionally, so one service shares a bucket across all users and the other accepts a spoofed key.

## Proposed solution

One resolution helper gated on a trusted-proxy list.

1. Add a `TRUSTED_PROXIES` configuration value to the Client backend.
2. Implement one helper that returns the last `X-Forwarded-For` hop when the peer is in that list, and the peer address otherwise.
3. Use the helper for `_rate_limit_check` in `client/backend/server.py` and for the `X-Client-IP` identity the gateway already forwards to the Engine.
4. Confirm the limiter keys on distinct client addresses behind a proxy.

## Related

- The gateway identity header (`X-Client-IP`, old task 77) is already delivered; this helper becomes its single source rather than a second resolution rule.

## Comments

**Triage.** Confirmed against the code, but the problem statement predates the `X-Client-IP` work and security-audit run 2's correction. As things stand:

- The Client backend's per-route limiter and its profile-creation limiter key on the TCP peer, which behind the `DEPLOYMENT.md` nginx is always `127.0.0.1`: one bucket for every visitor.
- The Client backend's `_get_client_ip` returns the **first** `X-Forwarded-For` hop, from any peer. nginx appends to the browser's own header, so that hop is caller-chosen, and it is what reaches the Engine as `X-Client-IP` and what the access log records.
- The Engine no longer trusts `X-Forwarded-For` first. It prefers `X-Client-IP`, which is fine while it binds loopback, but that value inherits the spoofable hop above. It still falls back to `X-Forwarded-For` / `X-Real-IP`.

No existing implementation, no prior rejection. Decisions (recorded in `docs/project/adr/0002-trusted-proxy-client-address.md` and `CONTEXT.md`, **Client address**):

- `TRUSTED_PROXIES` defaults to loopback (`127.0.0.1`, `::1`) and accepts IPs and CIDRs.
- In scope beyond the limiter and `X-Client-IP`: the profile-creation limiter, the access log, and removing the Engine's `X-Forwarded-For` / `X-Real-IP` fallback.

## Agent Brief

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
