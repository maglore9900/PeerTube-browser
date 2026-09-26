# ADR-0002: The client address is resolved once, in the Client backend, behind a trusted-proxy list

Status: accepted
Date: decided in triage of issue 02 (trusted-proxy client address)

## Context

Two resolution rules existed, and both were wrong behind the documented nginx deployment:

- The Client backend's rate limiters keyed on the TCP peer, which behind nginx is always `127.0.0.1`, so every visitor shared one bucket.
- Its `_get_client_ip` returned the **first** `X-Forwarded-For` hop, trusted from any peer. nginx's `$proxy_add_x_forwarded_for` appends to whatever the browser sent, so that hop is caller-chosen. It fed the `X-Client-IP` header the Engine keys its limiter on, and the access log.
- The Engine also fell back to `X-Forwarded-For` and `X-Real-IP` when `X-Client-IP` was absent.

## Decision

1. **One rule, in the Client backend.** The client address is the **last** `X-Forwarded-For` hop when the TCP peer is a trusted proxy, and the TCP peer otherwise. `X-Real-IP` is not consulted.
2. **Trusted proxies are configured** with the `TRUSTED_PROXIES` environment variable: comma-separated IP addresses or CIDR ranges. Unset, it defaults to loopback (`127.0.0.1`, `::1`), which matches the same-host nginx in `DEPLOYMENT.md`. A malformed value fails startup instead of silently trusting nothing, or everything.
3. **Every use goes through it:** the per-route rate limiter, the profile-creation limiter, the forwarded `X-Client-IP`, and the access log.
4. **The Engine trusts only `X-Client-IP`**, else its TCP peer. It no longer reads `X-Forwarded-For` or `X-Real-IP`. That trust rests on the Engine binding loopback with the Client backend as its only peer.

## Consequences

- A deployment with more than one proxy layer must list every layer's address; the rule takes only the last hop, so an untrusted intermediate proxy's address becomes the key.
- A deployment that exposes the Engine directly (not loopback-bound) makes `X-Client-IP` spoofable. That configuration is unsupported.
