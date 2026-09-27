# 12-trusted-proxy-client-address

_Rendered by the `dev-flow` workflow from its run state. Every edit here is overwritten on the next step; the evidence each gate turned on is in `docs/project/plans/16-12-trusted-proxy-client-address.record.md`._

## Requirements

### What is being built

Build issue `docs/project/issues/02-trusted-proxy-client-address.md` (plan `docs/project/plans/12-trusted-proxy-client-address.md`, category bug). The Client backend resolves the client address once, trusting `X-Forwarded-For` only from configured proxies. Every Client rate limiter, the access log, and the `X-Client-IP` header sent to the Engine are keyed on that address. The Engine trusts only `X-Client-IP`, else its TCP peer. Decisions this rests on: `docs/project/adr/0002-trusted-proxy-client-address.md`; `CONTEXT.md` **Client address**.

### Purpose

Close the security-audit finding (run 1 and run 2 reports under `docs/project/security-audit/`). Today, behind nginx, the Client limiters key on the TCP peer (`127.0.0.1`), so every visitor shares one bucket. Meanwhile `_get_client_ip` returns the caller-chosen first `X-Forwarded-For` hop from any peer, and that value reaches the Engine as `X-Client-IP`, so rotating the header bypasses the Engine's limiter and falsifies the access log. After this build, one visitor is one bucket everywhere and a caller cannot choose its own key. The build is one of issues 01-06 in the security hardening batch (wave 1, plan 12).

### Operator decision taken at requirements (supersedes the brief's "last hop" wording)

The brief and ADR-0002 say both "the client address is the last `X-Forwarded-For` hop" and "each additional proxy layer must be listed". With a strict last-hop rule, listing outer layers has no effect: for CDN -> nginx -> backend, the last hop is always the CDN. The operator chose to **walk `X-Forwarded-For` right to left, skipping trusted hops**. For the documented single same-host nginx deployment this gives exactly the brief's last-hop result, and every brief acceptance criterion holds unchanged. ADR-0002 decision 1 and its Consequences say "last hop"; this build does not edit the ADR. The harvest step should note that the ADR wording is now "last untrusted hop, walking right to left".

### Resolution rule (Client backend, `client/backend/server.py`)

- A module-level pure function of `(peer address string, X-Forwarded-For header value, trusted networks)` that returns the client address string. It needs no socket or handler, so tests can call it directly.
- If the peer is not in the trusted set, return the peer.
- If the peer is trusted and `X-Forwarded-For` is absent or empty after trimming, return the peer.
- Otherwise split `X-Forwarded-For` on commas and walk the hops from right (last) to left, starting with current address = peer. While the current address is trusted, take the next hop leftward, trimmed. If that hop is empty or not a valid IP address (`ipaddress.ip_address` fails), stop and return the current address. Otherwise it becomes the current address. Stop at the first untrusted address and return it. If every hop is trusted, return the leftmost hop.
- Consequence: a trusted peer with an empty or invalid last hop returns the peer, as the brief requires.
- A hop that is accepted is returned as the canonical string of the parsed address (for example, `203.0.113.9`). A peer that is returned is returned as the socket gave it.
- IPv4-mapped IPv6 addresses (`::ffff:127.0.0.1`) are unmapped (`ipv4_mapped`) before any trusted-set membership check, for both the peer and hops, so they match their IPv4 entry.
- `X-Real-IP` is never read.
- If the handler has no `client_address`, the peer is `"unknown"`, which is never trusted, so the result is `"unknown"`. This matches today's fallback.

### Configuration: `TRUSTED_PROXIES`

- Read from the environment once at startup in `main()`, matching how the file reads other env vars once.
- Format: comma-separated IPv4/IPv6 addresses and CIDR ranges, with whitespace around entries tolerated. Each entry is parsed with `ipaddress.ip_network(entry, strict=False)`; a bare address becomes a /32 or /128. Empty items from stray commas are ignored.
- Unset, empty or whitespace-only means the default `127.0.0.1,::1`, held as a module-level named constant.
- A malformed entry makes the backend refuse to start. The parse function raises `ValueError` with a message that names the offending entry verbatim, and `main()` turns that into a startup failure (for example `SystemExit`/`parser.error`) whose message includes the entry, before the server binds.
- Setting `TRUSTED_PROXIES` replaces the default rather than adding to it: `TRUSTED_PROXIES=10.0.0.0/8` trusts `10.1.2.3` and no longer trusts `127.0.0.1`.
- `ClientBackendServer.__init__` gains a trailing parameter holding the parsed trusted networks, stored on the server object (for example `self.trusted_proxies`). It defaults to the parsed loopback default, so the two existing constructions in `tests/active/conftest.py` (lines 74 and 161, six positional args) keep working unchanged. `main()` passes the parsed env value.

### Consumers (all go through the one rule)

- `ClientBackendHandler._get_client_ip` (`server.py:171`) is reimplemented as a thin call to the pure function with `self.client_address[0]` (or `"unknown"`), `self.headers.get("X-Forwarded-For", "")`, and `self.server.trusted_proxies`.
- Access log `ip` field in `log_message` (`:202`): already calls `_get_client_ip`; keeps doing so.
- Mint limiter on `POST /api/profile` (`:280`): key on `self._get_client_ip()` instead of `client_address[0]`.
- `_rate_limit_check` (`:350`): key `f"{ip}:{path}"` with `ip = self._get_client_ip()` instead of `client_address[0]`.
- `x-client-ip` header on every Engine request in the proxy path (`:527`): already calls `_get_client_ip`; keeps doing so. Its comment stays accurate.
- Line numbers are as of this worktree; re-locate by function name if they drift.

### Engine (`engine/server/api/handlers/similar.py`)

- `SimilarHandler._get_client_ip` (`:283`) returns the trimmed `X-Client-IP` if present and non-empty, otherwise `self.client_address[0]`, otherwise `"unknown"`. The `X-Forwarded-For` and `X-Real-IP` branches are removed and the docstring is updated. Its callers (`:318`, `:329`, `:355`, `:390`, `:575`) are unchanged. Plan 11 edits a different function in this file.

### Documentation (`DEPLOYMENT.md`)

- Next to the existing paragraph after the nginx block (about line 333, "The `X-Forwarded-For` lines are required..."), document `TRUSTED_PROXIES`: what it is, the syntax (comma-separated IPs/CIDRs), the loopback default `127.0.0.1,::1` that matches the same-host nginx shown, that setting it replaces the default, that a malformed entry stops the Client backend at startup, and that each additional proxy layer in front of nginx (a CDN, a load balancer) must be listed or the key becomes that layer's address. Also update that paragraph so it describes the address as the last untrusted `X-Forwarded-For` hop, not "the caller from them". The nginx config itself is not changed. Plan 15 also edits this file.

### Acceptance criteria

- [ ] With the peer `127.0.0.1` (default trusted set) and `X-Forwarded-For: 6.6.6.6, 203.0.113.9`, the resolved address is `203.0.113.9`.
- [ ] With the peer `198.51.100.7` (not trusted) and any `X-Forwarded-For`, the resolved address is `198.51.100.7`.
- [ ] With a trusted peer and no `X-Forwarded-For`, or a last hop that is not an IP, the resolved address is the peer.
- [ ] `TRUSTED_PROXIES=10.0.0.0/8` trusts peer `10.1.2.3` and no longer trusts `127.0.0.1`.
- [ ] A malformed `TRUSTED_PROXIES` entry stops startup with an error naming it.
- [ ] Behind a trusted peer, two requests with different last hops land in different rate-limit buckets for one route, and two requests that differ only in the *first* hop share one bucket. This holds for the per-route limiter and the mint limiter.
- [ ] The `X-Client-IP` header the Client backend sends to the Engine equals the resolved address.
- [ ] The Engine, given `X-Forwarded-For` and `X-Real-IP` but no `X-Client-IP`, keys its limiter on the TCP peer.
- [ ] `DEPLOYMENT.md` documents `TRUSTED_PROXIES`.
- [ ] (Operator decision) Multi-layer walk: with trusted set `127.0.0.1,10.0.0.5`, peer `127.0.0.1` and `X-Forwarded-For: 203.0.113.9, 10.0.0.5`, the resolved address is `203.0.113.9`. With only the default set, the same request resolves to `10.0.0.5`.
- [ ] IPv4-mapped peer `::ffff:127.0.0.1` is trusted under the default set.

### Out of scope

- Rate-limit sizes and windows.
- Adding rate limiting to `/internal/*` Engine routes.
- `X-Forwarded-Proto` / `Host` handling in `_get_full_url` (both services).
- Supporting the Engine bound on a non-loopback address.
- The nginx configuration itself, which already sends `X-Forwarded-For`.
- Editing ADR-0002 or `CONTEXT.md` (their wording change is noted for harvest).

### Consistency constraints

- Match the file's style: stdlib `http.server` handlers, `respond_json`, module-level named constants (for example the default trusted-proxy string), and env vars read once at startup. Use stdlib `ipaddress` only, with no new dependency, no new module, and no class hierarchy for one rule. The pure function and the parser live in `client/backend/server.py`.
- Backwards compatibility is not required beyond what is stated. The `ClientBackendServer` constructor default exists only so the existing test fixtures stay valid.
- Run `validate_tests.py` from the worktree root `/home/enduser/code/PeerTube-browser/.worktrees/fix-12-trusted-proxy-client-address` (the `.un` `project_dir`). Test trees: active `tests/active`, working `tests/tmp`, archive `tests/archive`; record `tests/last_test_validation.json`, output `tests/last_test_output.txt`.
- Run Engine-backed test files in their own `validate_tests.py` invocations (memory `engine-rate-limit-single-lane-test-runs`).

### Baseline suite state

The pre-build baseline ran clean: exit code 0, no variant. Any failure after the change is attributable to this build. Existing tests found in the tree do not send `X-Forwarded-For`, `X-Real-IP` or `X-Client-IP` (grep of `tests/`), so no existing test is expected to change behaviour. Test servers bind `127.0.0.1`, so their peer is trusted under the default set, and with no `X-Forwarded-For` they resolve to the peer as today.

### Batch context and risks

- Wave 1 of the security hardening batch (`.scratch/security-hardening-batch/notes.md`), in its own worktree; it merges to main at close and is harvested on main. It shares `client/backend/server.py` with plans 13-15, `engine/server/api/handlers/similar.py` with plan 11 (a different function), and `DEPLOYMENT.md` with plan 15.
- A multi-layer deployment that does not list every layer keys on the unlisted layer's address. This is documented, not detected.
- The engine test fixture calls the Engine directly, so the Engine gets no `X-Client-IP` and keys on the peer, as today.
- The worktree symlinks the main tree's `whitelist.db`; test Engines write interaction rows into it concurrently with other lanes.
- `tests/last_test_validation.json` and `tests/last_test_output.txt` conflict on merge: take main's copy and re-run `validate_tests.py --compare` on the merged tree.

## High-level plan

### Approach

Everything on the Client side goes through one module-level pure function in `client/backend/server.py`. It takes the peer string, the raw `X-Forwarded-For` value and the trusted networks, and returns the client address. The handler methods call it; they do not repeat the logic. A second small module-level function parses the `TRUSTED_PROXIES` string into a tuple of `ipaddress` networks. Beside it sit a named constant for the default string `127.0.0.1,::1` and a constant holding that default already parsed, which `ClientBackendServer.__init__` uses as its trailing default. There is no new module, no class and no dependency; only stdlib `ipaddress` is added to the imports.

**Resolution.** A small internal helper checks membership. It parses a string with `ipaddress.ip_address`, unmaps it through `ipv4_mapped` if it is a mapped v6 address, and tests it against every trusted network. A peer that does not parse (for example `"unknown"`) counts as untrusted. Testing an address against a network of the other IP version returns False rather than raising, so v4 and v6 entries can be mixed safely. The walk follows the settled rule exactly:
- An untrusted peer is returned as the socket gave it.
- A trusted peer with an empty `X-Forwarded-For` is returned as-is.
- Otherwise the function splits on commas and moves leftward from the last hop while the current address is trusted.
- An empty or unparseable hop stops the walk and returns the current address. That is the peer when it is the last hop, as the brief requires.
- An accepted hop becomes the current address, held as its canonical parsed string.
- The walk returns the first untrusted address, or the leftmost hop if every hop is trusted.
- `X-Real-IP` is never read.

**Requirement by requirement.**
- **Default trusted set.** `127.0.0.1` with `6.6.6.6, 203.0.113.9` resolves to `203.0.113.9`: the peer is trusted, `203.0.113.9` is not, so the walk stops there.
- **Untrusted peer.** `198.51.100.7` is returned at once.
- **No header or bad last hop.** A trusted peer with no header, or a non-IP last hop, returns the peer.
- **Multi-layer walk.** With `127.0.0.1,10.0.0.5` configured, the walk skips `10.0.0.5` and returns `203.0.113.9`. Under the default set it stops at `10.0.0.5`.
- **Mapped peer.** `::ffff:127.0.0.1` unmaps to `127.0.0.1`, which is in the default set.
- **Handler.** `_get_client_ip` (line 171) becomes a thin call using `self.client_address[0]` or `"unknown"`, the header, and `self.server.trusted_proxies`.
- **Limiters.** The mint limiter (line 280) and `_rate_limit_check` (line 350) switch from `client_address[0]` to `self._get_client_ip()`. Buckets now follow the last untrusted hop, and a caller changing only the first hop still lands in the same bucket.
- **Access log and Engine header.** The access log (line 202) and the `x-client-ip` header (line 527) already call `_get_client_ip`, so they now carry the same resolved value with no edit.
- **Configuration.** `main()` has no `ArgumentParser` in scope; `parse_args()` is a separate function. Right after `parse_args()`, and before the DB is opened or the server constructed (constructing it binds the socket), `main()` reads `os.environ.get("TRUSTED_PROXIES")`. It falls back to the default constant when the value is unset or blank, parses it, turns a `ValueError` into `SystemExit` with a message naming the bad entry, and passes the result as the new trailing constructor argument. The parser splits on commas, trims each item, drops empty items and runs `ip_network(entry, strict=False)` on the rest. On failure it raises `ValueError` quoting the entry verbatim. Setting the variable replaces the default, so `10.0.0.0/8` trusts `10.1.2.3` and not `127.0.0.1`. It would be reasonable to add the parsed set to the existing `service.start` log payload, but I would leave it out unless asked: it goes beyond the requirements.
- **Existing fixtures.** The six-argument constructions in `tests/active/conftest.py` keep working through the constructor default.
- **Engine.** `SimilarHandler._get_client_ip` in `similar.py` (line 283) loses its `X-Forwarded-For` and `X-Real-IP` branches. It becomes: trimmed `X-Client-IP`, else `client_address[0]`, else `"unknown"`. The docstring is reworded; the callers do not change.
- **`DEPLOYMENT.md`.** Around line 333, the paragraph is reworded to say the backend takes the last untrusted `X-Forwarded-For` hop. A new paragraph documents `TRUSTED_PROXIES`: what it is, the syntax, the loopback default matching the same-host nginx example, that setting it replaces the default, that a malformed entry stops startup, and that each outer layer must be listed. The nginx block is not changed. The existing paragraph is hard-wrapped, so the new text follows that wrapping to match the file.

**Testing.**
- **Unit tests** in the style of `tests/active` call the pure function and the parser directly. They cover every resolution criterion, the multi-layer and mapped cases, replace-not-add, and the `ValueError` naming the entry. Startup failure is tested through `main()` with the env var set, asserting `SystemExit` and the entry in the message.
- **Live-server tests** use the conftest backend, which binds `127.0.0.1` and so is trusted. With `X-Forwarded-For` varied they show that different last hops get separate buckets and a differing first hop shares one, for one per-route path and for `POST /api/profile`. They also check that the `x-client-ip` reaching a capturing stand-in Engine equals the resolved address.
- **Engine test.** A request with `X-Forwarded-For` and `X-Real-IP` but no `X-Client-IP` must key on the peer. Calling `SimilarHandler._get_client_ip` on a minimal stub carrying `headers` and `client_address` tests this with no running Engine. Any Engine-backed test file runs in its own `validate_tests.py` invocation.

### Alternatives considered

- **Strict last hop.** Rejected by the operator: with it, listing outer layers has no effect. Right-to-left skipping gives the same answer for the single-nginx deployment and makes multi-layer configuration mean something.
- **Caching the resolved address on the handler instance.** Rejected. `BaseHTTPRequestHandler` keeps one instance across keep-alive requests, so a cached value could leak one request's address into the next. The function is cheap, so the handler recomputes it on each call (up to three times per request). "Resolved once" holds in the sense that one rule and one input produce one value per request.
- **Parsing `TRUSTED_PROXIES` at import time**, like `DEFAULT_CLIENT_PUBLISH_MODE`. Rejected: the requirement puts it in `main()`, and a malformed environment variable would then break every test that imports `server`.
- **An argparse flag or a `parser.error` path.** Not used: `main()` has no parser object. A plain `SystemExit` carrying the message is the smallest route to the same startup failure.
- **nginx `real_ip` module or a WSGI-style middleware.** Out of scope (nginx is unchanged), and heavier than one function.
- **A resolver class, or a separate module for it.** Rejected under the one-rule, no-hierarchy constraint.

### Risks, gotchas, limitations

- **Unlisted proxy layers.** A multi-layer deployment that does not list every layer keys on the innermost unlisted layer's address, so all its visitors share one bucket. This is documented, not detected.
- **An invalid hop partway through.** It stops the walk at the trusted address to its right, which can be a proxy address. That is the settled rule and it fails safe (the caller cannot pick a key), but those requests share a bucket.
- **Mapped addresses in hops.** A mapped hop that is accepted is returned in its canonical mapped form (`::ffff:…`), because unmapping applies only to the membership check. A v4-mapped hop and the plain v4 address would therefore key separately. This follows the rule as written; nginx does not emit mapped forms in practice.
- **An all-trusted chain** returns the leftmost hop even though it is itself trusted, as specified.
- **Merge overlap.** `server.py` is shared with plans 13-15, `similar.py` with plan 11 (a different function), and `DEPLOYMENT.md` with plan 15. The edits are local, so conflicts should be textual and small. The test-record files take main's copy and are re-run with `--compare` after the merge.
- **Shared `whitelist.db`.** Engine-backed tests write to the symlinked `whitelist.db` alongside other lanes. That is why they run in their own invocations.
- **The Engine trusts `X-Client-IP` from any peer.** This rests on the Engine binding loopback; a non-loopback Engine is out of scope.

### Tradeoffs the operator accepts

- An outer layer that is not configured makes that layer's address the key instead of failing loudly.
- The ADR and `CONTEXT.md` keep saying "last hop" until harvest rewords them to "last untrusted hop, walking right to left".
- The constructor default exists only for the fixtures: an embedder that forgets to pass trusted networks silently gets the loopback default.
- The address is recomputed per call rather than cached, trading a few microseconds for safety across keep-alive requests.

## Impacts

<impacts>
<impact path="client/backend/server.py" element="stdlib import block (lines 5-21)">
Add `import ipaddress` to the alphabetised stdlib group, between `argparse` (line 5) and `json` (line 6). It is stdlib, so there is no new dependency. Nothing depends on it except the new functions below. `tests/check-client-engine-boundary.sh` only looks for engine imports, so it is unaffected. Regression risk: nil.
</impact>
<impact path="client/backend/server.py" element="new module constants: DEFAULT_TRUSTED_PROXIES string and its parsed tuple (constant block, lines 43-100)">
New `DEFAULT_TRUSTED_PROXIES = "127.0.0.1,::1"`, named like `DEFAULT_CLIENT_HOST` (line 43) and `DEFAULT_ENGINE_INGEST_BASE` (line 45), plus a constant holding the same value already parsed.

**Ordering gotcha.** Every existing constant sits above the first function, `_resolve_mode` (line 103). The parsed constant has to call the new parser, so it must be assigned after the parser's `def`, or the module fails to import. That breaks `conftest.py:39` (`import server as client_server`) and so every test in `tests/active`.

**Import-time rule.** Parsing a hard-coded literal at import is safe. It must not read the environment at import: `DEFAULT_CLIENT_PUBLISH_MODE` (line 47) does, but the plan rejects that for this variable.

**Depends on it:** the default of `ClientBackendServer.__init__`, the fallback in `main()`, and any test that checks the default.

**Risk:** the parsed value must be an immutable tuple, because every server built on the default shares that one object.
</impact>
<impact path="client/backend/server.py" element="new module-level TRUSTED_PROXIES parser function">
New pure function. It splits on commas, trims each item, drops empty items, runs `ipaddress.ip_network(entry, strict=False)` on each and returns a tuple. It raises `ValueError` quoting the offending entry verbatim.

**Depends on it:** `main()`, the parsed-default constant and the new unit tests.

**Risks:**
- `ip_network` raises `AddressValueError` / `NetmaskValueError` (both `ValueError` subclasses), and their text does not reliably contain the raw entry. For example, `10.0.0.0/33` reports only the netmask. The function must catch each entry's failure and build its own message, or the "error naming the entry" criterion can fail.
- A value of only commas or whitespace (`","`, `" , "`) parses to an empty tuple, which trusts nothing. The plan's blank-value fallback in `main()` does not catch this case. Decide whether an empty result falls back to the default (recommended, per ADR-0002 decision 2 "instead of silently trusting nothing") or is an error, and test it.
- `strict=False` accepts `10.1.2.3/8` as `10.0.0.0/8`. This is intended, but a typo can silently widen trust.
</impact>
<impact path="client/backend/server.py" element="new membership helper and pure client-address resolver (module level, before ClientBackendServer at line 145)">
Two new functions.
- **Membership helper:** `ipaddress.ip_address`, then unmap through `.ipv4_mapped` when it is set, then `any(addr in net for net in trusted)`. An `in` test across IP versions returns False rather than raising, so mixed v4/v6 entries are safe.
- **Resolver** `(peer, x_forwarded_for, trusted) -> str`. It walks the hops right to left as specified.

**Called from:** `ClientBackendHandler._get_client_ip` only, and the new tests directly.

**Details to get right:**
- `"unknown"` and any peer that does not parse must count as untrusted (catch `ValueError`).
- A returned peer is verbatim. An accepted hop is `str(parsed)` in canonical form, so `2001:DB8::1` becomes `2001:db8::1`.
- An empty or unparseable hop stops the walk and returns the current address.
- An all-trusted chain returns the leftmost hop.
- A mapped hop is returned in mapped form (a limitation the plan accepts).
- Scoped v6 literals such as `fe80::1%eth0` parse on 3.9+ and would key with the scope included. This is harmless but untested.

**Regression risk: high.** This is the core of the fix. An off-by-one in the walk silently reopens a bug: starting at `hops[-2]`, returning the peer when the last hop is untrusted, or returning the first hop. Either the caller-chosen key comes back or the shared nginx bucket does. Each acceptance criterion needs a direct unit test, including multi-layer (`127.0.0.1,10.0.0.5` gives `203.0.113.9`, and the default set gives `10.0.0.5`) and the mapped peer `::ffff:127.0.0.1`.
</impact>
<impact path="client/backend/server.py" element="ClientBackendServer.__init__ (lines 145-165)">
Gains a trailing parameter for the trusted networks, defaulting to the parsed-default constant, and stores it as `self.trusted_proxies`.

**Depends on it:**
- `main()` (constructor call at lines 1128-1135).
- `tests/active/conftest.py:74` and `:161`, which pass six positional args and rely on the default.
- `ClientBackendHandler._get_client_ip`, through `self.server.trusted_proxies`.

**Risks:**
- The parameter must come after `rate_limiter`, or both fixtures break.
- `mint_rate_limiter` (line 165) is built inside `__init__` from fixed constants (5 per 3600 s). A live mint-bucket test therefore needs either the `_Clock` monkeypatch trick from `test_profiles.py` or access to the server object, which the `ClientBackend` dataclass does not expose.
- The class inherits `ThreadingHTTPServer`'s `AF_INET`. A live peer is always IPv4 today, so the `::1` entry and the unmapping can only be exercised through the pure function.
</impact>
<impact path="client/backend/server.py" element="ClientBackendHandler._get_client_ip (lines 171-183)">
The body becomes a thin call: the resolver of `self.client_address[0] if self.client_address else "unknown"`, `self.headers.get("X-Forwarded-For", "")` and `self.server.trusted_proxies`.

**Removed:**
- The first-hop return (lines 173-177), which is the spoofable key.
- The `X-Real-IP` branch (lines 178-180).

**Callers today:**
- `log_message` (line 202).
- `_proxy_engine_request` (line 527).

**Callers after this change:** the two above, plus the mint limiter (line 280) and `_rate_limit_check` (line 350).

**Risks:**
- `log_message` also runs for `send_error` on a malformed request line, which can happen before `self.headers` is set. The current code already reads `self.headers.get` there, so this exposure is not new. Do not make the call stricter. Reading `self.server.trusted_proxies` is new, but every server that uses this handler is a `ClientBackendServer`.
- Nothing is cached, which is correct for keep-alive.
- The docstring "Handle get client ip." should state the rule.
</impact>
<impact path="client/backend/server.py" element="log_message access-log `ip` field (lines 193-208)">
No edit. The logged `ip` changes:
- **Behind nginx:** the last untrusted hop instead of the caller-chosen first hop.
- **Untrusted peers:** the TCP peer, even when they send `X-Forwarded-For` or `X-Real-IP`.
- **Local runs without XFF** (Vite, tests, smoke): `127.0.0.1` as before.

Anything that searches journald or `client.access` lines sees different IPs for spoofed traffic, which is the intent. Low risk.
</impact>
<impact path="client/backend/server.py" element="do_POST `/api/profile` mint limiter (lines 279-283)">
`peer = self.client_address[0] ...` becomes `self._get_client_ip()` as the key to `self.server.mint_rate_limiter.allow`. Rename the local variable (for example `ip`).

**Behaviour:** behind nginx, each visitor gets their own 5-per-hour budget instead of one shared budget.

**Existing test:** `tests/active/test_profiles.py::test_a_sixth_mint_from_one_address_within_the_hour_is_refused` (lines 158-174) binds `127.0.0.1` and `127.0.0.2` with no XFF. `127.0.0.1` is trusted, and with no header the peer is returned. `127.0.0.2` is outside `127.0.0.1/32`, so it is untrusted and returned as-is. The test still passes.

**Risk:** that test would also pass if the default were widened to `127.0.0.0/8`, so it does not guard the default.

**Other callers:** several `tests/active` tests mint repeatedly through `_mint` (for example 3 in `test_users_db_holds…`). Each `client_backend` fixture is a fresh server, so the budget resets and nothing changes.

**Doc impact:** the "per peer address" wording in `DEPLOYMENT.md:256` and `client/README.md:11` becomes stale.
</impact>
<impact path="client/backend/server.py" element="_rate_limit_check (lines 348-352) and its 11 call sites">
`ip = self.client_address[0] ...` becomes `ip = self._get_client_ip()`. The key `f"{ip}:{path}"` is unchanged.

**Call sites whose bucketing changes:**
- `do_GET`: lines 219, 237, 249, 255, 263.
- `do_POST`: lines 274, 299, 305, 311, 317, 323.

`/api/profile/rotate`, `/api/profile/delete` and `/api/health` stay unlimited.

**Test hint:** `/api/user-profile` checks the rate limit before `_require_profile`, so a live bucket test can drive it against `CLOSED_ENGINE` with no Engine and no key. Keyless requests get 401 until the bucket is exhausted, then 429. That test needs a small limiter, and the fixtures use `RateLimiter(1000, 60)`.

**Risk:** `RateLimiter.requests` never evicts, so keys grow with distinct visitors (see the `http_utils` entry).
</impact>
<impact path="client/backend/lib/http_utils.py" element="RateLimiter (lines 91-117)">
No edit. The `requests` dict (line 99) keeps an entry for every key it has ever seen; buckets are emptied but never removed. Behind nginx the key set used to be bounded (one per route). After this change there is one key per visitor per route, growing for the life of the process. The keys are not header-chosen, but a v6 client can rotate addresses within its /64 cheaply. Sizes and windows are out of scope, so record this as a known limitation or follow-up. `test_profiles.py:160` monkeypatches `http_utils.datetime`, and that keeps working.
</impact>
<impact path="client/backend/server.py" element="_proxy_engine_request `x-client-ip` header (lines 523-527)">
No edit. The header now carries the resolved address, so rotating `X-Forwarded-For` can no longer bypass the Engine's limiter. The comment at lines 523-526 stays accurate.

Only this method sends the header. The `lib/engine_api_client.py` helpers (`resolve_video_seed`, `fetch_metadata_for_entries`, `compute_dislike_centroids`, `resolve_videos_by_uuid_host`) and the bridge publish send no `x-client-ip`, but the `/internal/*` routes they call are not rate-limited, so nothing changes there.

The new "x-client-ip equals resolved address" test must go through a proxied route (for example `GET /api/channels` or `POST /recommendations`) to a capturing stand-in Engine. `CLOSED_ENGINE` (port 9) cannot capture.
</impact>
<impact path="client/backend/server.py" element="main() (lines 1099-1168)">
Right after `args = parse_args()` (line 1101), it:
- reads `os.environ.get("TRUSTED_PROXIES")`, using the default when the value is unset or blank;
- parses it, turning `ValueError` into `SystemExit(<message naming the entry>)`;
- passes the result as the new trailing argument to `ClientBackendServer(...)` (line 1128).

**Placement:**
- The check must run before `signal.signal(...)` (lines 1121-1122). That swap is only undone in the `finally` after `serve_forever`, so an exit after it leaves `_handle_shutdown_signal` installed in a pytest process.
- It must also run before `mkdir`/`connect_db` (lines 1124-1127), so a bad value creates no DB file, and before the constructor, which binds the socket.

**Test gotcha:**
- `parse_args()` (lines 128-135) reads `sys.argv`. Under pytest, argparse fails on pytest's own arguments with `SystemExit(2)`, so a test that asserts only `SystemExit` passes for the wrong reason. The test must monkeypatch `sys.argv` and assert that the entry text is in `exc.code`/`str(exc)`.
- The test should also set a valid `--port` so a mistaken success path cannot bind 7172.

**Optional:** add the trusted set to the `service.start` payload (line 1140). The plan leaves this out.

**Operational:** under systemd with `Restart=on-failure`, a malformed value crash-loops the unit until it hits the start limit, with the message in journald.
</impact>
<impact path="client/backend/server.py" element="_get_full_url (lines 185-191), explicitly unchanged">
No edit. It still trusts `X-Forwarded-Proto` and `Host` from any peer, for the access-log URL only. That is out of scope per the brief. It is listed so a reviewer does not take it for a missed consumer: it does not read `X-Forwarded-For`.
</impact>
<impact path="engine/server/api/handlers/similar.py" element="SimilarHandler._get_client_ip (lines 283-304)">
Delete the `X-Forwarded-For` branch (lines 294-298) and the `X-Real-IP` branch (lines 299-301). What remains: trimmed `X-Client-IP`, else `self.client_address[0]`, else `"unknown"`. Reword the docstring, since line 284 says "behind the gateway and reverse proxy headers"; the paragraph at lines 286-289 stays true.

**Callers are unchanged:**
- `_log_access_start` (line 318)
- `log_message` (line 329)
- `_respond_interrupted` (line 355)
- `_bridge_authorized` warning log (line 390)
- `_rate_limit_check` (line 575)

**Behaviour change:** only direct-to-Engine requests without `X-Client-IP` are affected: the `engine` test fixture, smoke scripts and manual curls to 7070. They now key on the peer even when they carry `X-Forwarded-For`/`X-Real-IP`. A grep of `tests/` finds no test sending those headers.

**Merge risk:** plan 11 edits another function in this file.
</impact>
<impact path="engine/server/api/handlers/similar.py" element="SimilarHandler._rate_limit_check (lines 570-577) and its gates (lines 443, 497, 582)">
No edit. Its key source narrows as described in the `_get_client_ip` entry. The Engine still trusts `X-Client-IP` from any peer. That rests on the loopback bind (`server_config.py:326`) and on `DEPLOYMENT.md` "Never open 7070 or 7072" (line 354).
</impact>
<impact path="engine/server/api/http_utils.py" element="RateLimiter (lines 66-90)">
No edit. It has the same never-evicting `requests` dict as the Client's. Once `x-client-ip` carries real per-visitor addresses behind nginx, its keys grow per visitor per route. Before this change they collapsed or were caller-chosen. Record it with the Client limiter limitation.
</impact>
<impact path="engine/server/api/server_config.py" element="DEFAULT_SERVER_HOST (line 326)">
Read only; no edit. `"127.0.0.1"` is the premise for the Engine trusting `X-Client-IP` unconditionally (ADR-0002, decision 4). Running the Engine with `--host 0.0.0.0` makes the header spoofable. That setup is unsupported and out of scope.
</impact>
<impact path="engine/server/data/ann.py" element="module import of numpy and faiss (lines 8-15)">
No edit, but it constrains the planned Engine test. `handlers/similar.py` imports numpy (line 28) and `data.ann` (line 30). `data.ann` imports numpy and, if faiss is missing, raises `SystemExit("faiss is required…")` at import.

The Client test interpreter that runs `tests/active`/`tests/tmp` has no evident numpy or faiss:
- No test file imports either.
- `test_random_videos.py` imports only `data.interaction_events`/`data.random_videos`, and `test_db.py` only `data.db`.
- `conftest.py:30` runs the Engine under a separate `ENGINE_PY` (the pixi env).

The plan's in-process stub call to `SimilarHandler._get_client_ip` may therefore abort the test module, and possibly the lane, with `SystemExit`. Options:
- **(a)** Run the stub check in a subprocess under `conftest.ENGINE_PY`, following `test_db.py:80-84`, which uses `sys.executable`. Put `engine/server` and `engine/server/api` on the path and print the result.
- **(b)** Use the live `engine` fixture: send `X-Forwarded-For`/`X-Real-IP` directly and assert that the Engine log line (the fixture's `db_path` is the log path) has `ip=127.0.0.1`. The file then becomes Engine-backed and needs its own `validate_tests.py` invocation.

(a) is cheaper. I have not confirmed which packages the Client test interpreter has installed.
</impact>
<impact path="engine/server/api/tests/test_recommendations_likes_limit.py" element="existing SimilarHandler stub-test precedent (lines 12-39)">
No edit. This is the established pattern for calling `SimilarHandler` methods without a running Engine:
- insert `engine/server` and `engine/server/api` into `sys.path`;
- `from handlers import similar`;
- call `similar.SimilarHandler._method(stub)`.

The stub is a small hand-written class (`_DummySimilarHandler`) with a dict `headers`. `SimpleNamespace` is used only for `server`. The new Engine test's stub needs `headers` (dict) and `client_address`. This precedent runs under the Engine interpreter, not the `tests/active` one; see the `ann.py` entry.

Name clash: `engine/server/api/server.py` and the Client `server` module share a name, and `conftest.py:39` has already imported the Client's. `handlers.similar` does not import `server`, so this is safe as long as the test does not import the Engine's.
</impact>
<impact path="tests/active/conftest.py" element="client_backend fixture (lines 69-89) and _engine_client (lines 156-176)">
No edit is needed for existing behaviour. Both six-argument constructions get the loopback default. The server binds `127.0.0.1`, so the test peer is trusted, and with no XFF the key stays `127.0.0.1`.

**Gaps for the new tests:**
- `ClientBackend` (lines 46-66) exposes only `base` and `db_path`, not the server. Tests that need a small per-route limiter, a custom trusted set or a stand-in Engine must build their own `ClientBackendServer` or add a fixture.
- `ClientBackend.request` already takes arbitrary headers, so it can send `X-Forwarded-For`.
- Any fixture added here is shared by every file in `tests/active`.
</impact>
<impact path="tests/active/test_profiles.py" element="_mint_from helper and test_a_sixth_mint_from_one_address_within_the_hour_is_refused (lines 147-174)">
No edit is required, and the test keeps passing (see the mint limiter entry). `_mint_from` hard-codes its headers (line 152), so a new mint-bucket test that varies XFF needs either a headers parameter or a sibling helper. It can reuse the `_Clock` pattern (lines 137-144, 159-160). The docstring line 7, "One address can mint five profiles an hour", stays true.
</impact>
<impact path="tests/active/test_server.py" element="Engine-backed Client tests via engine_client">
No edit. These tests send no XFF, so the forwarded `x-client-ip` stays `127.0.0.1`, and the Engine keys them exactly as before. Low risk.
</impact>
<impact path="tests/active/test_similar.py" element="Engine-direct tests via the engine fixture">
No edit. The tests call the Engine directly without `X-Client-IP`/XFF, so the key is the peer both before and after. The shared 60/min Engine bucket is why Engine-backed files run in separate invocations, and that is unchanged.
</impact>
<impact path="tests/active/test_db.py" element="subprocess child pattern (lines 38-88)">
No edit. It is the precedent for running code in a child interpreter from a test (`subprocess.run([sys.executable, "-c", ...])`). For the Engine `_get_client_ip` check, swap in `conftest.ENGINE_PY` for `sys.executable`.
</impact>
<impact path="tests/tmp/test_client_address.py" element="new working test file(s) (tests/tmp does not exist yet)">
New file(s); the name is illustrative. Contents:
- Unit tests of the resolver and parser: every criterion, multi-layer, mapped peer, replace-not-add, the empty-after-commas decision, and a `ValueError` naming the entry.
- A `main()` startup-failure test with `sys.argv` and `TRUSTED_PROXIES` patched.
- Live per-route bucket tests (for example `/api/user-profile` with a small limiter) and mint bucket tests, varying the last hop against the first hop.
- A capturing stand-in Engine that checks the `x-client-ip` header.
- The Engine `_get_client_ip` check, run under `ENGINE_PY` (see the `ann.py` entry).

Import `server` the way `conftest.py` does. Any file that uses the `engine` fixture runs in its own `validate_tests.py` invocation.
</impact>
<impact path="tests/last_test_validation.json" element="tracked test record">
Regenerated by `validate_tests.py`. It conflicts on every merge: take main's copy and re-run with `--compare` on the merged tree. Existing test outcomes should not change.
</impact>
<impact path="tests/last_test_output.txt" element="tracked test output">
Same handling as the validation record: regenerated, and it conflicts on merge. Take main's copy and re-run.
</impact>
<impact path=".un/skills/devsecops/scripts/validate_tests.py" element="test runner">
No edit. Run it from the worktree root. Engine-backed files go in separate invocations.
</impact>
<impact path="tests/run-arch-split-smoke.sh" element="real Client start (line 542)">
No edit. The smoke sends no forwarded headers, so every key resolves to `127.0.0.1`. New failure surface: a malformed `TRUSTED_PROXIES` exported in the invoking shell now stops the Client, and the smoke reports a health failure. That is correct behaviour.
</impact>
<impact path="client/install-client-service.sh" element="systemd unit template (lines 186-203)">
No edit planned. The unit sets `PYTHONUNBUFFERED` and `CLIENT_PUBLISH_MODE`, reads `EnvironmentFile=-${PROJECT_DIR}/.env.bridge` (line 196) and uses `Restart=on-failure` (line 198). An operator sets `TRUSTED_PROXIES` in `.env.bridge` or in a drop-in. The Engine unit reads the same file (`engine/install-engine-service.sh:182`) and ignores the variable. A malformed value crash-loops the Client unit. `--host` can be set to non-loopback. In that case peers are real clients, which are untrusted, so the result is correct. An installer flag is out of scope.
</impact>
<impact path="scripts/run-services.sh" element="background Client start (CLIENT_SCRIPT, line 36)">
No edit. It starts the Client with the caller's environment, so a malformed `TRUSTED_PROXIES` makes the Client exit at once. The script then reports it not running, and the reason is in the client log. Low risk; listed as a new failure surface.
</impact>
<impact path="client/frontend/vite.config.ts" element="dev proxy (lines 27-40)">
No edit. It uses `changeOrigin: true` without `xfwd`, so it sends no XFF. The peer is `127.0.0.1` and the dev flow is unchanged.
</impact>
<impact path="DEPLOYMENT.md" element="paragraph after the nginx block (lines 333-335)">
Reword "resolves the caller from them" to: the last untrusted `X-Forwarded-For` hop, walking right to left past trusted proxies. Add a `TRUSTED_PROXIES` paragraph covering:
- syntax: comma-separated IPs/CIDRs, whitespace tolerated;
- the default `127.0.0.1,::1`, which matches the same-host nginx above;
- setting it replaces the default;
- a malformed entry stops the Client backend at startup;
- every extra layer (CDN or load balancer) must be listed, otherwise its address becomes everyone's key;
- `X-Real-IP` is ignored;
- where systemd reads it (`.env.bridge` or a drop-in).

Keep the file's hard wrap. The nginx block (lines 294-331) is unchanged; its `X-Real-IP` lines become inert. Plan 15 also edits this file, so a merge conflict is possible.
</impact>
<impact path="DEPLOYMENT.md" element="section 5 profile paragraph, mint-limit sentences (line 256)">
The plan's doc list misses this line. It reads: "Minting is limited to 5 per hour per peer address. Behind nginx the peer is nginx itself, so until the Client backend resolves the real client address, that limit is shared by every visitor of the deployment." After this build it is false. Change it to "per client address" and drop the caveat, or point it at `TRUSTED_PROXIES`. This paragraph is one long unwrapped line.
</impact>
<impact path="DEPLOYMENT.md" element="systemd environment paragraph (lines 104-108) and Triage table (lines 139-148)">
Optional edit. The environment paragraph is where units get their variables, so it could name `TRUSTED_PROXIES`. The Triage table could gain a row: Client unit `failed`, journal names a `TRUSTED_PROXIES` entry, meaning a malformed value. At minimum, the section-6 paragraph should say where systemd reads the variable. Whether both are wanted is a judgment call.
</impact>
<impact path="client/README.md" element="POST /api/profile bullet (line 11) and Run Backend Locally (lines 47-58)">
The plan misses line 11: "Rate-limited to 5 per hour per peer address" becomes "per client address", possibly with a pointer to `TRUSTED_PROXIES`. "Run Backend Locally" documents only `CLIENT_PUBLISH_MODE` (lines 56-58). Adding `TRUSTED_PROXIES` there is optional but keeps the env list complete.
</impact>
<impact path="CONTEXT.md" element="**Client address** glossary entry (line 8)">
It says "the last `X-Forwarded-For` hop when the TCP peer is a trusted proxy". Under the operator's decision it should read "the last untrusted hop, walking right to left". The requirements say harvest edits it, not this build. Listed so harvest does not miss it.
</impact>
<impact path="docs/project/adr/0002-trusted-proxy-client-address.md" element="Decision 1 (line 16) and Consequences (line 23)">
Both lines say "last hop". Line 23 also says "the rule takes only the last hop, so an untrusted intermediate proxy's address becomes the key", which is now inaccurate: listed layers are skipped. Decision 2 (line 17), "fails startup instead of silently trusting nothing", bears on the all-commas case. Harvest edits this file, not this build.
</impact>
<impact path="docs/project/issues/02-trusted-proxy-client-address.md" element="Status line and acceptance checkboxes">
At close the status becomes `complete` and the file moves to `docs/project/issues/archive/`, per `docs/project/triage-labels.md`. This happens at harvest on main, not in this worktree.
</impact>
<impact path="docs/project/plans/16-12-trusted-proxy-client-address.md" element="build plan and its .record.md">
The build's own plan. Later steps append to it. It has no effect on code behaviour.
</impact>
<impact path="docs/project/security-audit/run-1/REPORT.md" element="F6 finding text (lines 228-247), historical">
No edit. It is a historical audit record whose line references are now stale. Listed only so nobody "fixes" it. The same applies to `run-1/FINDINGS-DETAIL.md`, `run-1/findings.json` and the `run-2/*` reports.
</impact>
</impacts>

## Documentation to update

- [x] `DEPLOYMENT.md` - updated: DEPLOYMENT.md: added `TRUSTED_PROXIES` and how the client address is resolved, and replaced the old wording that said the mint limit was per peer.
- [x] `client/README.md` - updated: `client/README.md`: the mint limit is now per client address, and `TRUSTED_PROXIES` is listed with the backend's environment variables.
- [x] `CONTEXT.md` - out of scope: Not in this build. The **Client address** entry (line 8) says "the last `X-Forwarded-For` hop when the TCP peer is a trusted proxy". Under the operator's decision the delivered rule is "the last untrusted hop, walking right to left past trusted proxies". The settled requirements put editing `CONTEXT.md` out of scope and defer this change to harvest on main, so harvest must reword it. For the documented single same-host nginx deployment the current wording still gives the same result.
- [x] `docs/project/adr/0002-trusted-proxy-client-address.md` - out of scope: Not edited by this build. The requirements put editing ADR-0002 out of scope and defer it to harvest, and amending an ADR is the operator's decision. The contradiction is recorded in adr_conflicts: decision 1 (line 16) and the first Consequence (line 23) against the delivered right-to-left walk. Decisions 2-4 match what was delivered, including the fallback to the loopback default for an all-comma or blank value, which avoids "silently trusting nothing".

## Implementation plan

## Draft: trusted-proxy client address (plan 12, issue 02)

I read every file below in this worktree before drafting. Line numbers match the tree as it stands now. The ladder placeholder in the step prompt (`{rat_tail_ladder}`) came through unfilled, so this draft is written against the plan, the requirements and the settled impacts.

### Module map

| File | Change |
|---|---|
| `client/backend/server.py` | Adds `import ipaddress`, the constant `DEFAULT_TRUSTED_PROXIES`, and the functions `parse_trusted_proxies`, `DEFAULT_TRUSTED_PROXY_NETWORKS`, `_is_trusted_proxy` and `resolve_client_address`. Adds a trailing constructor parameter, a thin `_get_client_ip`, two limiter keys and the `main()` wiring. |
| `engine/server/api/handlers/similar.py` | `_get_client_ip` becomes: `X-Client-IP`, else the peer, else `"unknown"`. |
| `DEPLOYMENT.md` | Rewords lines 333-335, adds a `TRUSTED_PROXIES` paragraph, fixes line 256, adds one Triage row. |
| `client/README.md` | Line 11 wording. |
| `tests/tmp/test_client_address.py` | New working test file. It is self-contained: see "Test seams". |

No new module, class or dependency.

### `client/backend/server.py`

**Imports (lines 5-6).** Add `import ipaddress` between `argparse` and `json`.

**Constant block.** Add after `DEFAULT_USERS_DB_PATH` (line 46). It is a literal and does not read the environment at import:
```python
DEFAULT_TRUSTED_PROXIES = "127.0.0.1,::1"
```

**New functions.** They go between `connect_db` (ends line 142) and `class ClientBackendServer` (line 145), in this order, so the parsed constant is assigned after the parser's `def`. The ordering gotcha from the impact inventory is met.
```python
def parse_trusted_proxies(value: str) -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    """Parse a `TRUSTED_PROXIES` value: comma-separated IPv4/IPv6 addresses and CIDR ranges.

    Whitespace around entries and empty items are ignored; a bare address is a /32 or /128. A value with no entries is the loopback default, so a stray comma never trusts nothing.

    :raises ValueError: naming the first entry that is not an address or range.
    """
    networks = []
    for raw_entry in value.split(","):
        entry = raw_entry.strip()
        if not entry:
            continue
        try:
            networks.append(ipaddress.ip_network(entry, strict=False))
        except ValueError:
            raise ValueError(f"TRUSTED_PROXIES entry is not an IP address or CIDR range: {entry!r}") from None
    if not networks:
        return DEFAULT_TRUSTED_PROXY_NETWORKS
    return tuple(networks)


DEFAULT_TRUSTED_PROXY_NETWORKS = parse_trusted_proxies(DEFAULT_TRUSTED_PROXIES)


def _is_trusted_proxy(address: str, trusted: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]) -> bool:
    """Whether `address` is in a trusted network; an IPv4-mapped IPv6 address matches its IPv4 entry, and anything that does not parse is untrusted."""
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return False
    mapped = getattr(parsed, "ipv4_mapped", None)
    if mapped is not None:
        parsed = mapped
    return any(parsed in network for network in trusted)


def resolve_client_address(peer: str, x_forwarded_for: str, trusted: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]) -> str:
    """Return the client address of one request.

    From an untrusted peer it is the peer. From a trusted peer, walk `X-Forwarded-For` right to left while the current address is trusted: an empty or non-IP hop stops the walk at the current address, and the first untrusted hop is the address. An all-trusted chain resolves to its leftmost hop. `X-Real-IP` is never read. A returned peer is verbatim; an accepted hop is its canonical form.
    """
    if not _is_trusted_proxy(peer, trusted):
        return peer
    current = peer
    for raw_hop in reversed(x_forwarded_for.split(",")):
        try:
            current = str(ipaddress.ip_address(raw_hop.strip()))
        except ValueError:
            return current
        if not _is_trusted_proxy(current, trusted):
            return current
    return current
```

**Invariants.**
- `DEFAULT_TRUSTED_PROXY_NETWORKS` is an immutable tuple shared by every server built on the default.
- The recursive reference inside `parse_trusted_proxies` is only reached for a value with no entries, and the default literal has entries, so assigning the constant terminates.
- `"".split(",") == [""]`, so an absent or empty header falls straight into the "empty hop, return the peer" branch. No separate check is needed.
- An `in` test across IP versions returns False; it does not raise.
- `"unknown"` fails `ip_address`, so it is untrusted and returned verbatim.

**Decisions.**
- **All-commas value.** A value like `","` or `" , "` falls back to the default rather than parsing to "trust nothing". ADR-0002 decision 2 says "instead of silently trusting nothing". The fallback sits inside the parser, so it is one pure, directly testable place, and `main()` needs no blank-check of its own.
- **Error message.** The message is built by hand with `from None`, because `ip_network`'s own text omits the entry (for example for `10.0.0.0/33`).
- **No type alias.** Signatures spell out the union because annotations are lazy (`from __future__ import annotations`). A module-level alias would evaluate `X | Y` at runtime.

**`ClientBackendServer.__init__` (lines 148-165).** Add a trailing parameter after `rate_limiter`: `trusted_proxies: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = DEFAULT_TRUSTED_PROXY_NETWORKS,`. Store it with `self.trusted_proxies = trusted_proxies`. The six-argument fixtures at `conftest.py:74` and `:161` keep working unchanged.

**`ClientBackendHandler._get_client_ip` (lines 171-183).** Replace the whole body:
```python
    def _get_client_ip(self) -> str:
        """The client address: the last untrusted `X-Forwarded-For` hop behind a trusted proxy, else the TCP peer."""
        peer = self.client_address[0] if self.client_address else "unknown"
        return resolve_client_address(peer, self.headers.get("X-Forwarded-For", ""), self.server.trusted_proxies)
```
The first-hop and `X-Real-IP` branches are gone. Nothing is cached, which keeps keep-alive safe. `log_message` (line 202) and `_proxy_engine_request` (line 527) are not edited. Their comment stays accurate.

**Mint limiter (lines 280-281):**
```python
            ip = self._get_client_ip()
            if not self.server.mint_rate_limiter.allow(ip):
```

**`_rate_limit_check` (line 350):** `ip = self._get_client_ip()`. The key `f"{ip}:{path}"` is unchanged, as are the 11 call sites.

**`main()` (after line 1101).** This runs before `logging.basicConfig`, the signal swap (1121-1122), `mkdir`/`connect_db` (1124-1127) and the constructor that binds:
```python
    args = parse_args()
    try:
        trusted_proxies = parse_trusted_proxies(os.environ.get("TRUSTED_PROXIES", ""))
    except ValueError as exc:
        raise SystemExit(f"client backend: {exc}") from None
```
The constructor call (1128-1135) gains `trusted_proxies,` as its last argument. `SystemExit(str)` prints the message to stderr, which journald captures, and exits 1. The `service.start` payload is unchanged, as the plan says.

### `engine/server/api/handlers/similar.py` (lines 283-304)

```python
    def _get_client_ip(self) -> str:
        """Resolve the client IP: the Client backend's `X-Client-IP`, else the TCP peer.

        `X-Client-IP` is the address the Client backend resolved for the original
        caller. It is trusted because the Engine binds loopback and the gateway is
        its only reachable peer; without it every proxied request looks like
        127.0.0.1 and shares one rate-limit bucket. No other forwarding header is
        read: a direct caller could choose it.
        """
        client_ip = self.headers.get("X-Client-IP", "").strip()
        if client_ip:
            return client_ip
        if self.client_address:
            return self.client_address[0]
        return "unknown"
```
Callers (318, 329, 355, 390, 575) are unchanged.

### Documentation

**`DEPLOYMENT.md` lines 333-335.** Replace with the text below, hard-wrapped at the file's width:
```
The `X-Forwarded-For` lines are required, not cosmetic. When a request comes from a
trusted proxy, the Client backend walks `X-Forwarded-For` from right to left past the
trusted proxies and takes the last untrusted hop as the client address. It keys its own
rate limiters on that address and forwards it to the Engine as `X-Client-IP`, which is
what the Engine's rate limiter keys on. Omit them and every visitor shares one bucket.

`TRUSTED_PROXIES` names the peers allowed to set `X-Forwarded-For`: a comma-separated
list of IPv4/IPv6 addresses and CIDR ranges, with whitespace around entries allowed
(`TRUSTED_PROXIES=127.0.0.1, ::1, 10.0.0.0/8`). Unset or blank, it is `127.0.0.1,::1`,
which matches the same-host nginx above. Setting it replaces that default rather than
adding to it, so keep the loopback entries while nginx runs on this host. Every proxy
layer in front of nginx (a CDN, a load balancer) must be listed as well; an unlisted
layer's address becomes the key shared by all of its visitors. A malformed entry stops
the Client backend at startup with an error naming the entry. `X-Real-IP` is ignored,
so the `X-Real-IP` lines above have no effect. Under systemd, set the variable in
`.env.bridge` (section 3b) or in a drop-in for the Client unit.
```

**`DEPLOYMENT.md` line 256** (one unwrapped line; keep it that way). Replace the last two sentences with: `Minting is limited to 5 per hour per client address (see `TRUSTED_PROXIES` in section 6).` The "Behind nginx the peer is nginx itself…" sentence is removed.

**`DEPLOYMENT.md` Triage table.** Add one row after line 145:
`| Client unit restarts, then `failed`; journal names a `TRUSTED_PROXIES` entry | Malformed `TRUSTED_PROXIES` in `.env.bridge` or a drop-in | Fix the entry (section 6), then `systemctl reset-failed peertube-client` and start it |`

The optional systemd-environment paragraph (104-108) is **not** edited: the new section-6 paragraph already says where systemd reads the variable.

**`client/README.md` line 11.** Change the tail to: `Rate-limited to 5 per hour per client address: behind a proxy listed in `TRUSTED_PROXIES` (default `127.0.0.1,::1`) the last untrusted `X-Forwarded-For` hop, else the TCP peer.` The optional "Run Backend Locally" addition is skipped. It is named here as a deliberate omission and is cheap to add at harvest.

`CONTEXT.md` and ADR-0002 are not edited. Their "last untrusted hop, walking right to left" rewording is for harvest.

### Test seams: `tests/tmp/test_client_address.py`

**Deviation from the plan.** The plan's live tests "use the conftest backend", but `conftest.py` exists only under `tests/active`, so a file in `tests/tmp` cannot see its fixtures. The file therefore sets its own `sys.path` the way `conftest.py:35-39` does and builds its own `ClientBackendServer`s. It needs its own servers anyway, for a small per-route limiter and a capturing Engine. It uses no `engine` fixture, so it is **not** Engine-backed and needs no separate invocation.

**Engine check.** Per the `ann.py` impact, importing `handlers.similar` in the Client test interpreter can raise `SystemExit` (no faiss). The Engine check therefore runs in a subprocess under the pixi `ENGINE_PY`, following `test_db.py` and the `test_recommendations_likes_limit.py` stub precedent. If `ENGINE_PY` is missing, it fails loudly rather than skipping, as the `engine` fixture does.

```python
"""The Client address: one rule, trusted proxies only, behind every Client limiter and the Engine header.

- From a trusted peer the address is the last untrusted `X-Forwarded-For` hop, walking right to left; from any other peer it is the peer.
- `TRUSTED_PROXIES` replaces the loopback default; a malformed entry stops startup, naming it.
- Per-route and mint buckets follow the resolved address: a different last hop is a different bucket, a different first hop is not.
- The Engine is sent the resolved address, and itself keys on `X-Client-IP` or its peer, never `X-Forwarded-For`/`X-Real-IP`.
"""
from __future__ import annotations

import re
import signal
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import ip_network
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ENGINE_PY = ROOT / "engine" / ".pixi" / "envs" / "default" / "bin" / "python"
ENGINE_API = ROOT / "engine" / "server" / "api"
BACKEND_DIR = ROOT / "client" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import server as client_server  # noqa: E402
from lib.http_utils import RateLimiter  # noqa: E402
from lib.users_store import ensure_user_schema  # noqa: E402

CLOSED_ENGINE = "http://127.0.0.1:9"
DEFAULT = client_server.DEFAULT_TRUSTED_PROXY_NETWORKS
parse = client_server.parse_trusted_proxies
resolve = client_server.resolve_client_address


# --- the rule ----------------------------------------------------------------------------


def test_behind_a_trusted_peer_the_last_hop_is_the_address():
    assert resolve("127.0.0.1", "6.6.6.6, 203.0.113.9", DEFAULT) == "203.0.113.9"


def test_an_untrusted_peer_is_the_address_whatever_it_forwards():
    assert resolve("198.51.100.7", "6.6.6.6, 203.0.113.9", DEFAULT) == "198.51.100.7"
    assert resolve("198.51.100.7", "", DEFAULT) == "198.51.100.7"


@pytest.mark.parametrize("header", ["", "   ", "6.6.6.6, not-an-ip", "6.6.6.6, ", "unknown"])
def test_a_trusted_peer_without_a_usable_last_hop_is_the_address(header):
    assert resolve("127.0.0.1", header, DEFAULT) == "127.0.0.1"


def test_listed_layers_are_walked_past_and_an_unlisted_layer_is_the_address():
    header = "203.0.113.9, 10.0.0.5"
    assert resolve("127.0.0.1", header, parse("127.0.0.1,10.0.0.5")) == "203.0.113.9"
    assert resolve("127.0.0.1", header, DEFAULT) == "10.0.0.5"


def test_an_all_trusted_chain_resolves_to_its_leftmost_hop():
    assert resolve("127.0.0.1", "10.0.0.7, 10.0.0.5", parse("127.0.0.1,10.0.0.0/8")) == "10.0.0.7"


def test_an_ipv4_mapped_peer_matches_its_ipv4_entry():
    assert resolve("::ffff:127.0.0.1", "203.0.113.9", DEFAULT) == "203.0.113.9"
    # Control: a mapped untrusted peer stays untrusted, and is returned verbatim.
    assert resolve("::ffff:198.51.100.7", "203.0.113.9", DEFAULT) == "::ffff:198.51.100.7"


def test_an_accepted_hop_is_canonical_and_an_unknown_peer_is_itself():
    assert resolve("::1", "2001:DB8::1", DEFAULT) == "2001:db8::1"
    assert resolve("unknown", "203.0.113.9", DEFAULT) == "unknown"


# --- TRUSTED_PROXIES ---------------------------------------------------------------------


def test_the_default_is_loopback_v4_and_v6():
    assert DEFAULT == (ip_network("127.0.0.1/32"), ip_network("::1/128"))


def test_setting_trusted_proxies_replaces_the_default():
    trusted = parse("10.0.0.0/8")
    assert resolve("10.1.2.3", "203.0.113.9", trusted) == "203.0.113.9"
    assert resolve("127.0.0.1", "203.0.113.9", trusted) == "127.0.0.1"


@pytest.mark.parametrize("value", ["", "  ", ",", " , "])
def test_a_value_with_no_entries_is_the_default(value):
    assert parse(value) == DEFAULT


def test_whitespace_and_stray_commas_are_tolerated():
    assert parse(" 10.0.0.0/8 ,, 192.0.2.1 ") == (ip_network("10.0.0.0/8"), ip_network("192.0.2.1/32"))


@pytest.mark.parametrize("entry", ["10.0.0.0/33", "not-an-ip", "300.1.1.1"])
def test_a_malformed_entry_is_named_in_the_error(entry):
    with pytest.raises(ValueError, match=re.escape(entry)):
        parse(f"127.0.0.1, {entry}")


def test_a_malformed_trusted_proxies_stops_startup_naming_the_entry(monkeypatch):
    # A valid argv, so argparse cannot be the SystemExit; port 1 would fail to bind if startup got that far.
    monkeypatch.setattr(sys, "argv", ["server.py", "--port", "1"])
    monkeypatch.setenv("TRUSTED_PROXIES", "127.0.0.1, 10.0.0.0/33")
    before = signal.getsignal(signal.SIGINT)
    with pytest.raises(SystemExit) as exc:
        client_server.main()
    assert "10.0.0.0/33" in str(exc.value.code)
    # It stopped before the signal handlers were swapped, so nothing leaks into this process.
    assert signal.getsignal(signal.SIGINT) is before


# --- live buckets and the Engine header --------------------------------------------------


@contextmanager
def _serving(server):
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


@contextmanager
def _client(tmp_path, engine_base=CLOSED_ENGINE, limiter=None):
    """A Client backend on 127.0.0.1, a trusted peer under the default set."""
    conn = client_server.connect_db(tmp_path / "users.db")
    ensure_user_schema(conn)
    srv = client_server.ClientBackendServer(("127.0.0.1", 0), client_server.ClientBackendHandler, conn,
                                            engine_base, "bridge", limiter or RateLimiter(1000, 60))
    try:
        with _serving(srv) as base:
            yield base
    finally:
        conn.close()


def _status(base: str, method: str, path: str, forwarded_for: str | None = None) -> int:
    headers = {"content-type": "application/json"}
    if forwarded_for is not None:
        headers["X-Forwarded-For"] = forwarded_for
    req = urllib.request.Request(base + path, data=b"" if method == "POST" else None, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code


def test_per_route_buckets_follow_the_last_hop_not_the_first(tmp_path):
    # /api/user-profile checks the limit before the key, so keyless requests are 401 until the bucket empties.
    with _client(tmp_path, limiter=RateLimiter(2, 60)) as base:
        same_last = [_status(base, "GET", "/api/user-profile", f"{first}, 203.0.113.9")
                     for first in ("1.1.1.1", "2.2.2.2", "3.3.3.3")]
        other_last = _status(base, "GET", "/api/user-profile", "1.1.1.1, 203.0.113.10")
    assert same_last == [401, 401, 429]
    assert other_last == 401


def test_mint_buckets_follow_the_last_hop_not_the_first(tmp_path):
    with _client(tmp_path) as base:
        same_last = [_status(base, "POST", "/api/profile", f"198.51.100.{n}, 203.0.113.9") for n in range(6)]
        other_last = _status(base, "POST", "/api/profile", "198.51.100.0, 203.0.113.10")
    assert same_last == [201] * 5 + [429]
    assert other_last == 201


class _CapturingEngine(BaseHTTPRequestHandler):
    """Stands in for the Engine: records the `x-client-ip` each request carries."""

    def do_GET(self):  # noqa: N802
        self.server.seen.append(self.headers.get("x-client-ip"))
        body = b"{}"
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def test_the_engine_is_sent_the_resolved_address(tmp_path):
    engine = ThreadingHTTPServer(("127.0.0.1", 0), _CapturingEngine)
    engine.seen = []
    with _serving(engine) as engine_base, _client(tmp_path, engine_base) as base:
        statuses = [_status(base, "GET", "/api/channels", "6.6.6.6, 203.0.113.9"),
                    _status(base, "GET", "/api/channels")]
    assert statuses == [200, 200]
    assert engine.seen == ["203.0.113.9", "127.0.0.1"]


ENGINE_KEY_CHECK = r'''
import sys
from types import SimpleNamespace
sys.path[:0] = sys.argv[1:3]
from handlers import similar

class Recorder:
    def __init__(self):
        self.keys = []
    def allow(self, key):
        self.keys.append(key)
        return True

class Stub:
    _get_client_ip = similar.SimilarHandler._get_client_ip
    _rate_limit_check = similar.SimilarHandler._rate_limit_check
    def __init__(self, headers):
        self.headers = headers
        self.client_address = ("127.0.0.1", 50000)
        self.server = SimpleNamespace(rate_limiter=Recorder())

for headers in ({"X-Forwarded-For": "6.6.6.6, 203.0.113.9", "X-Real-IP": "7.7.7.7"},
                {"X-Client-IP": " 203.0.113.9 ", "X-Forwarded-For": "6.6.6.6"}):
    stub = Stub(headers)
    stub._rate_limit_check("/recommendations")
    print(stub.server.rate_limiter.keys[0])
'''


def test_the_engine_keys_on_x_client_ip_else_its_peer():
    # Under the Engine's interpreter: handlers.similar needs numpy and faiss.
    result = subprocess.run([str(ENGINE_PY), "-c", ENGINE_KEY_CHECK, str(ENGINE_API.parent), str(ENGINE_API)],
                            capture_output=True, text=True, timeout=120, cwd=ROOT)
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["127.0.0.1:/recommendations", "203.0.113.9:/recommendations"]
```

### Check against plan and requirements

The draft converged on pass 2. Pass 1 left the all-commas case open; it is now resolved to the default.

| Acceptance criterion | Covered by |
|---|---|
| `127.0.0.1` + `6.6.6.6, 203.0.113.9` → `203.0.113.9` | `test_behind_a_trusted_peer_…` |
| Untrusted peer → the peer | `test_an_untrusted_peer_…` |
| Trusted peer with no XFF, or a non-IP last hop → the peer | parametrised test with `""`, `"   "`, `not-an-ip`, a trailing comma, `unknown` |
| `10.0.0.0/8` trusts `10.1.2.3`, not `127.0.0.1` | `test_setting_trusted_proxies_replaces_the_default` |
| Malformed entry stops startup, naming it | parser test plus `main()` test (valid argv, message assertion, signal handler not leaked) |
| Buckets per last hop, shared across first hops, per-route and mint | the two live tests |
| `X-Client-IP` equals the resolved address | capturing stand-in Engine |
| Engine keys on the peer despite XFF / X-Real-IP | `ENGINE_PY` subprocess, asserting the actual limiter key |
| `DEPLOYMENT.md` documents `TRUSTED_PROXIES` | new paragraph |
| Multi-layer walk, both trusted sets | `test_listed_layers_…` |
| Mapped peer `::ffff:127.0.0.1` trusted | `test_an_ipv4_mapped_peer_…` |

Every constraint in the settled impacts is met:
- `ipaddress` import position.
- Constant ordering and no import-time environment read.
- Immutable tuple.
- Own error message.
- Parameter after `rate_limiter`.
- `main()` check before the signal swap, DB and bind.
- Engine callers untouched.
- `_get_full_url` untouched.
- `http_utils` untouched.

### Named simplifications and limitations

- **`_is_trusted_proxy` parses each address twice.** It parses once to accept the hop and again in the membership check, which costs microseconds. Upgrade path: pass the parsed object if this ever shows up in profiles.
- **`RateLimiter` dicts grow per visitor and route**, on both services, because they never evict. Rate-limit sizes and windows are out of scope, so this is recorded as a follow-up.
- **A mapped hop keys in mapped form**, separately from its plain v4 address. The plan accepts this.
- **Scoped v6 literals key with their scope included.** Not tested.
- **`strict=False` widens `10.1.2.3/8` to `10.0.0.0/8` silently.** This is intended.
- **Live peers are always IPv4 (`AF_INET`)**, so the `::1` entry and unmapping are covered only through the pure function.
- **Two optional doc edits are skipped:** the README "Run Backend Locally" mention and the systemd-environment paragraph (104-108).


### Phases

#### Phase 1 - TRUSTED_PROXIES configuration [code]

**Files touched.** client/backend/server.py (EDITED), tests/tmp/test_client_address.py (NEW)

**Checkpoint.** Seam: calls `client_server.parse_trusted_proxies` and `client_server.main()` directly in `tests/tmp/test_client_address.py`, which imports `server` the way `tests/active/conftest.py:35-39` does. For the parser it asserts four things: `parse("10.0.0.0/8")` is exactly that network; `"127.0.0.1,::1"` gives `(127.0.0.1/32, ::1/128)`; `""`, `"  "`, `","` and `" , "` give the default; and whitespace and stray commas are tolerated. For `main()` it monkeypatches `sys.argv` to a valid `["server.py", "--port", "1"]` and sets `TRUSTED_PROXIES="127.0.0.1, 10.0.0.0/33"`. It then asserts `SystemExit`, that `str(exc.value.code)` contains `10.0.0.0/33`, and that `signal.getsignal(SIGINT)` is unchanged, which shows the stop came before the signal swap, the DB open and the bind. Parametrized over malformed entries: `10.0.0.0/33`, `not-an-ip`, `300.1.1.1`.

**Intent.** In `client/backend/server.py`, `TRUSTED_PROXIES` becomes the Client backend's trusted-proxy networks at startup and replaces the loopback default. A malformed entry stops `main()` before it binds, and the error names the entry.

- C1 - `parse_trusted_proxies` returns exactly the networks listed, and a value with no entries returns the `127.0.0.1,::1` default.
- C2 - `main()` with a malformed `TRUSTED_PROXIES` entry raises `SystemExit` whose message contains that entry.

**Outcome.** ### `client/backend/server.py`

- Added `import ipaddress` to the stdlib imports.
- Added the constant `DEFAULT_TRUSTED_PROXIES = "127.0.0.1,::1"` after `DEFAULT_USERS_DB_PATH`.
- Added `parse_trusted_proxies(value)`, placed between `connect_db` and `ClientBackendServer`:
  - It splits the value on commas, trims each item and drops empty ones.
  - If nothing is left (`""`, `"  "`, `","`, `" , "`), it parses the default string instead, so a blank value never ends up trusting no proxy.
  - Each entry goes through `ipaddress.ip_network(entry, strict=False)`, and the networks come back as a tuple in the order listed.
  - On a failed entry it raises its own `ValueError` that quotes the entry, because `ipaddress`'s message leaves the entry out for some inputs such as a `/33` prefix.
- Added the module constant `DEFAULT_TRUSTED_PROXY_NETWORKS = parse_trusted_proxies(DEFAULT_TRUSTED_PROXIES)`. It is assigned after the function is defined, so importing the module still works.
- `ClientBackendServer.__init__` has a new last parameter, `trusted_proxies`, which defaults to `DEFAULT_TRUSTED_PROXY_NETWORKS` and is stored as `self.trusted_proxies`. The two six-argument constructions in `tests/active/conftest.py` still work unchanged.
- `main()` reads `TRUSTED_PROXIES` from the environment and parses it straight after `parse_args()`. That is before `logging.basicConfig`, the signal swap, the users.db `mkdir`/open and the constructor that binds the socket. A `ValueError` becomes `SystemExit("client backend: <message naming the entry>")`. The parsed networks are passed as the constructor's new last argument, so a set value replaces the loopback default rather than adding to it.
- Nothing uses `self.trusted_proxies` yet: `_get_client_ip` and the two rate limiters are unchanged, and switching them over is phases 2 and 3.

**Beyond the files named.** tests/tmp/test_client_address.py: not created. The phase lists it as NEW, but the checkpoint that gates this phase is `tests/tmp/test_12_trusted_proxy_client_address_phase1.py` and already covers both clauses, so this phase needs no second test file. The files list names a file this phase does not produce.

#### Phase 2 - The resolution rule [code]

**Files touched.** client/backend/server.py (EDITED), tests/tmp/test_client_address.py (EDITED)

**Checkpoint.** Seam: the pure function `client_server.resolve_client_address(peer, x_forwarded_for, trusted)`, called directly. The trusted sets come from `DEFAULT_TRUSTED_PROXY_NETWORKS` or `parse_trusted_proxies`. It asserts the following:
- `127.0.0.1` with `"6.6.6.6, 203.0.113.9"` gives `203.0.113.9`.
- `"203.0.113.9, 10.0.0.5"` gives `203.0.113.9` under `127.0.0.1,10.0.0.5` and `10.0.0.5` under the default.
- An all-trusted chain gives its leftmost hop.
- `::ffff:127.0.0.1` is trusted, and `::ffff:198.51.100.7` is untrusted and returned verbatim.
- An accepted v6 hop comes back in canonical form.
- `198.51.100.7` gives itself whatever it forwards.
- `127.0.0.1` with `""`, `"   "`, `"6.6.6.6, not-an-ip"`, `"6.6.6.6, "` or `"unknown"` gives `127.0.0.1`.
- Peer `unknown` gives `unknown`.
- Under `parse("10.0.0.0/8")`, `10.1.2.3` is trusted and `127.0.0.1` is not.

**Intent.** When the peer is trusted, `resolve_client_address` in `client/backend/server.py` returns the last untrusted `X-Forwarded-For` hop, walking right to left. Otherwise it returns the peer.

- C1 - Behind a trusted peer, the walk skips trusted hops and returns the first untrusted hop, or the leftmost hop when every hop is trusted.
- C2 - An untrusted peer, or a trusted peer whose last hop is empty or not an IP, resolves to the peer.

**Outcome.** ### `client/backend/server.py`
Added two module-level functions after `DEFAULT_TRUSTED_PROXY_NETWORKS`, following the design in `docs/project/plans/16-12-trusted-proxy-client-address.md`:
- `_is_trusted_proxy(address, trusted)`: parses `address` with `ipaddress.ip_address`. If it doesn't parse, the address is untrusted (so `"unknown"` is untrusted). An IPv4-mapped IPv6 address is unmapped to its v4 address, but only for this trust check. Returns whether it falls in any trusted network.
- `resolve_client_address(peer, x_forwarded_for, trusted)`: returns an untrusted or unparseable peer exactly as passed. For a trusted peer it walks the comma-split `X-Forwarded-For` from right to left. An empty or non-IP hop stops the walk and returns the current address: the peer as passed, or the last trusted hop accepted before it. The first untrusted hop is returned in canonical form (`str(ip_address(hop.strip()))`). A chain that is trusted all the way through returns its leftmost hop. `"".split(",") == [""]`, so an empty header takes the empty-hop branch and returns the peer. `X-Real-IP` is not read.

Nothing calls the new function yet. `_get_client_ip`, the limiter keys and the `x-client-ip` header are wired to it in Phase 3, as planned.

### `tests/tmp/test_client_address.py`
Not created. The files list marks it EDITED, but it does not exist: Phase 1 did not create it either, as that phase's record says. The checkpoint `tests/tmp/test_12_trusted_proxy_client_address_phase2.py` covers both clauses on its own, so this phase needs no second test file.

### Note
`tests/tmp/test_probe_phase2_resolve.py` is an empty probe left by the test-authoring step. I did not create it and left it untouched.

#### Phase 3 - Client consumers use the resolved address [code]

**Files touched.** client/backend/server.py (EDITED), tests/tmp/test_client_address.py (EDITED)

**Checkpoint.** Seam: live HTTP against a `ClientBackendServer` bound to `127.0.0.1:0`, which is a trusted peer under the default set. It is built the way `tests/active/conftest.py:69-89` builds the `client_backend` fixture, but inside the test file, because conftest is not visible from `tests/tmp`. It checks three things:
- **Per-route limiter.** With `RateLimiter(2, 60)`, three `GET /api/user-profile` requests share the last hop `203.0.113.9` and have different first hops. They return `[401, 401, 429]`. A request with a different last hop, `203.0.113.10`, returns 401.
- **Mint limiter.** Six `POST /api/profile` requests with last hop `203.0.113.9` and varying first hops return `[201]*5 + [429]`. A different last hop returns 201.
- **Engine header.** A capturing `ThreadingHTTPServer` stands in for the Engine as `engine_base`. `GET /api/channels` with `"6.6.6.6, 203.0.113.9"` delivers `x-client-ip == "203.0.113.9"`. Without the header it delivers `"127.0.0.1"`.

**Intent.** In `client/backend/server.py`, the per-route limiter, the mint limiter and the `x-client-ip` header sent to the Engine all carry the address `resolve_client_address` returns, through `_get_client_ip`.

- C1 - The per-route and mint rate-limit buckets follow the last untrusted hop: a different last hop gets a separate bucket, and a different first hop shares one.
- C2 - The `x-client-ip` reaching the Engine equals the resolved address.

**Outcome.** ### client/backend/server.py
- `ClientBackendHandler._get_client_ip` now returns `resolve_client_address(peer, X-Forwarded-For, self.server.trusted_proxies)`, where the peer is `client_address[0]` or `"unknown"` if there isn't one. It no longer reads the first `X-Forwarded-For` hop, and it no longer reads `X-Real-IP` at all. So a trusted peer gets the last untrusted hop, and any other peer gets its own socket address (C2).
- `_rate_limit_check` keys the per-route limiter on `f"{self._get_client_ip()}:{path}"` instead of the raw socket peer (C1).
- The `/api/profile` mint limiter keys on `self._get_client_ip()` instead of the raw socket peer (C1).
- Nothing else calls `_get_client_ip`, so two more things change with it: the `x-client-ip` header on Engine proxy requests now carries the resolved address (C2), and so does the `ip` field of the `client.access` log line. Before this change the log line recorded the forgeable first hop or `X-Real-IP`.

### tests/tmp/test_client_address.py
Not touched. The phase's files list names this file, but it doesn't exist in the worktree, and the checkpoint didn't need it.

#### Phase 4 - The Engine ignores forwarding headers [code]

**Files touched.** engine/server/api/handlers/similar.py (EDITED), tests/tmp/test_client_address.py (EDITED)

**Checkpoint.** Seam: `SimilarHandler._rate_limit_check` together with the real `_get_client_ip`, bound onto a minimal stub. The stub carries `headers`, `client_address=("127.0.0.1", 50000)` and a recording `server.rate_limiter`. It runs in a child process under the Engine interpreter `ENGINE_PY`, the path `tests/active/conftest.py:30` already uses, because importing `handlers.similar` needs numpy and faiss. The subprocess-child pattern follows `tests/active/test_db.py`. It asserts two recorded keys. Headers `{X-Forwarded-For: "6.6.6.6, 203.0.113.9", X-Real-IP: "7.7.7.7"}` give `127.0.0.1:/recommendations`. The control, `{X-Client-IP: " 203.0.113.9 ", X-Forwarded-For: "6.6.6.6"}`, gives `203.0.113.9:/recommendations`. A missing interpreter fails the test rather than skipping it. No Engine runs and `whitelist.db` is not written, so no separate `validate_tests.py` invocation is needed.

**Intent.** `SimilarHandler._get_client_ip` in `engine/server/api/handlers/similar.py` keys the Engine limiter on `X-Client-IP`, else the TCP peer, and no longer reads `X-Forwarded-For` or `X-Real-IP`.

- C1 - A request that carries `X-Forwarded-For` and `X-Real-IP` but no `X-Client-IP` is rate-limited on the TCP peer.

**Outcome.** ### `engine/server/api/handlers/similar.py`
- `SimilarHandler._get_client_ip` now returns the stripped `X-Client-IP` if it is present. Otherwise it returns `self.client_address[0]`, or `"unknown"` if there is no peer. I deleted the `X-Forwarded-For` first-hop branch and the `X-Real-IP` branch. So a request that sends those headers without `X-Client-IP` is keyed on its TCP peer (C1).
- Docstring: the summary line now states the new rule. A new paragraph says why the forwarding headers are ignored: a direct caller sets them, so keying on them let it choose its own rate-limit bucket. The existing paragraph that explains why `X-Client-IP` is trusted is unchanged.
- Callers are not edited: `_log_access_start`, `log_message`, `_respond_interrupted`, the `_bridge_authorized` warning and `_rate_limit_check`. Their logged `ip` and the limiter key now follow the narrower rule. That only affects direct-to-Engine requests that send no `X-Client-IP`.

### `tests/tmp/test_client_address.py`
Not touched. The phase's files list names it as EDITED, but it does not exist in the worktree. Phases 1–3 did not create it either (see their records). The checkpoint `tests/tmp/test_12_trusted_proxy_client_address_phase4.py` covers C1 on its own.

### Note
The probe files `tests/tmp/test_probe_phase3_http.py`, `tests/tmp/test_probe_phase4_engine.py` and `tests/tmp/test_probe_phase4_variants.py` came from earlier test-authoring steps and are still on disk. I did not create or touch them, and they need removing before merge.


