# Trusted-proxy client address resolution shared by both services

Status: bug, needs-triage
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
