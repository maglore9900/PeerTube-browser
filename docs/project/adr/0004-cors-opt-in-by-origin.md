# ADR-0004: CORS is opt-in by origin on the Client backend and absent from the Engine

Status: accepted
Date: decided in triage of issue 04 (tighten response defaults)

## Context

Both services answered every response and preflight with `access-control-allow-origin: *`. In the deployment `DEPLOYMENT.md` describes, the browser reaches the Client backend on its own origin through nginx, and never reaches the Engine, which binds loopback. Only the Vite dev server makes a cross-origin call, to the Client API at `VITE_CLIENT_API_BASE`.

## Decision

1. **Client backend:** sends no CORS headers unless `CLIENT_CORS_ORIGINS` (comma-separated exact origins) is set. When the request's `Origin` is in that list, the response echoes it in `access-control-allow-origin`, adds `Vary: Origin`, and carries the existing allow-methods / allow-headers. An unlisted or absent `Origin` gets no allow-origin header. `*` is never sent.
2. **Engine:** sends no CORS headers. No browser calls it.
3. Recommendations debug output is off unless the Engine is started with `RECOMMENDATIONS_DEBUG=1`.

## Consequences

- The dev workflow must set `CLIENT_CORS_ORIGINS` to the Vite origin on the Client backend, or run the frontend same-origin.
- A future browser-facing Engine route would need its own CORS decision; this ADR assumes there is none.
