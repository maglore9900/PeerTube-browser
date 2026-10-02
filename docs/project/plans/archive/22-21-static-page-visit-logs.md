# 21-static-page-visit-logs

_Rendered by the `dev-flow` workflow from its run state. Every edit here is overwritten on the next step; the evidence each gate turned on is in `docs/project/plans/22-21-static-page-visit-logs.record.md`._

## Requirements

### Purpose

Make visits to the About page visible and attributable. About is the only purely informational page: it has no scripts and makes no API calls, so a visit never reaches the Client backend or the Engine and leaves no app log record. Today it does not even serve in prod (see "Serve About in prod"). The build gives operators a dedicated, greppable record of About visits from nginx, and a runbook that ties a visit to the same visitor's app traces. This is request-log visibility. It is not event analytics: About outbound-click analytics belong to `docs/project/issues/18-about-outbound-click-tracking.md`, and nothing here may duplicate that.

### Scope decisions (operator-approved)

- Only the About page counts as an "informational static page": URLs `/about`, `/about/` and `/about.html`. Other pages (index, videos, search, likes, video-page, channels) are out of scope, because their API calls already show in app logs. Adding another informational page later means adding one more exact-match location of the same shape.
- The visit log is a separate file, and it does not replace the existing access log: About requests are written to both.
- The optional client-side pageview beacon is out of scope. It is named in the runbook as the upgrade path, riding on the beacon endpoint that issue 18 introduces, and not as a second endpoint.
- No Python, JavaScript or HTML change in the app or frontend. The deliverable is the documented nginx configuration and the runbook.

### Serve About in prod

- Current state, verified in the tree: `client/frontend/vite.config.ts` builds the `about` input from `client/frontend/dev-pages/about.html` when that local, untracked file exists, otherwise from `client/frontend/dev-pages/about.template.html`. The build output is therefore `dist/dev-pages/about.html` or `dist/dev-pages/about.template.html`, and there is never a `dist/about.html`. Every page's nav links to `/about.html`. The `/about`, `/about/`, `/about.html` rewrite exists only in vite's dev and preview servers. The public nginx site documented in `DEPLOYMENT.md` §6 has only `location / { try_files $uri $uri/ =404; }`, so `/about.html` returns 404 in prod. The operator confirmed it really 404s.
- Requirement: the public nginx site (`/etc/nginx/sites-available/peertube-browser` as documented in `DEPLOYMENT.md` §6) gets exact-match handling for `/about`, `/about/` and `/about.html`. It serves `/dev-pages/about.html` if present in the document root, otherwise `/dev-pages/about.template.html`, otherwise 404. Each of the three URLs answers 200 with the built About page.
- The About response must still carry the server-level `Content-Security-Policy` header. In nginx, a location that declares any `add_header` inherits none from the server level, so the About location must either declare none or repeat the CSP.
- All other routes (`location /`, `/api/`, `/recommendations`, `/videos/similar`, `/client/`) behave exactly as before.

### Dedicated About visit log

- Every request handled by the About location writes one line to a new file, `/var/log/nginx/peertube-browser.pages.access.log`, in a new `log_format` defined beside `peertube_browser`. Like that one, it sits outside `server {}` because the site file is included in nginx's `http` block.
- The same request also still writes its usual line to `/var/log/nginx/peertube-browser.access.log` in the `peertube_browser` format. In nginx, an `access_log` inside a location replaces the server-level one, so the About location must list both logs explicitly.
- Each pages-log line carries:
  - an explicit marker identifying the page (`page=about`);
  - a timestamp with millisecond precision that can be compared with the apps' `ts` (UTC `YYYY-MM-DDTHH:MM:SS.mmmZ`), e.g. nginx `$msec` and/or `$time_iso8601`;
  - client IP (`$remote_addr`);
  - method;
  - the URL as requested, path plus query (`$request_uri`);
  - response status;
  - response time (`$request_time`);
  - user-agent;
  - nginx's `$request_id`, the same id the visit's line in the main access log carries, so the two lines of one visit can be joined;
  - the incoming `X-Request-ID` request header when the client or an upstream layer sent one (`$http_x_request_id`), with `-` when absent. This is the "preserve when available" part of the request. Nothing is proxied from this location, so there is nothing to propagate onward.
- Every method and status that reaches the location is logged, including `HEAD`, `304` and `404`. The method and status fields let a reader filter.
- Log rotation: the new file sits under `/var/log/nginx/` with a `.log` suffix, so the Debian/Ubuntu nginx logrotate rule covers it. The docs state this.

### Runbook

A new Triage entry in `DEPLOYMENT.md`, beside "Follow one request", that:
- lists About visits from `/var/log/nginx/peertube-browser.pages.access.log` (grep for the marker; filter by status or method);
- finds the same visit's line in the main access log by its `request_id`;
- correlates a visit with the visitor's app traces by client IP plus a time window: Client backend `request.start` records whose `ip` equals the visit's client IP and whose `ts` falls within a stated window after the visit. It gives the commands in the same `journalctl … | jq` style as "Follow one request", with the `LOG_FORMAT=text` grep variant. From a Client record, the existing "Follow one request" steps reach the Engine;
- states the caveats:
  - an About visit shares no request id with later API calls: About makes no API calls, and nginx assigns each request its own `$request_id`. Correlation with app traces is by IP and time only, and therefore probabilistic (shared IPs and NAT).
  - The Client's `ip` is resolved through `X-Forwarded-For` and `TRUSTED_PROXIES`, so it equals nginx's `$remote_addr` only when nginx is the sole proxy. Behind a CDN or load balancer, nginx's `$remote_addr` is that layer's address.
  - The nginx timestamp and the app `ts` differ in format and time zone, so the reader must normalise to UTC.
  - Bots and crawlers appear in the log. The user-agent is the only filter, and cleaner human-intent counting is the beacon upgrade path.

### Documentation to update

- `DEPLOYMENT.md` §6, nginx (production): the site block gains the About location and the second `log_format`, with prose explaining the About mapping, why both `access_log` lines are repeated, the CSP inheritance rule, and the new file.
- `DEPLOYMENT.md` §3: the page list and the `try_files` note say that About is built under `dev-pages/` and served at `/about`, `/about/` and `/about.html` through the mapping.
- `DEPLOYMENT.md` Triage: the runbook above. The "What each log is for" text mentions the pages log.
- `docs/project/issues/21-static-page-visit-logs.md`: a delivery comment and a status update at completion, per `docs/project/issue-tracker.md` and `docs/project/triage-labels.md`.
- Any other doc that states About is served at `/about.html` or lists the nginx logs (e.g. `client/frontend/README.md` "Local About Overrides"), checked during the impact inventory.

### Validation

- With the documented config, a request to each of `/about`, `/about/` and `/about.html` returns 200 with the built About page and the CSP header.
- Each such request produces exactly one line in `peertube-browser.pages.access.log` carrying every field listed above, plus one line in `peertube-browser.access.log` with the same `request_id`.
- Requests to other pages and API routes produce no pages-log line, and their main-log lines are unchanged.
- Following the runbook against a visit and a subsequent API request from the same client finds the visit and that client's `request.start` record within the window.
- Where an `nginx` binary is available, the documented site config passes `nginx -t`. Where it is not, any automated check must skip rather than fail.
- The existing suite stays green.

### Baseline suite state

Pre-build suite exited 0, baseline variant false (selected 1 of 46 test groups: `test_search_fusion.py`, 10 passed). Active tests are in `tests/active`, working tests in `tests/tmp`, archive in `tests/archive`. Run record: `tests/last_test_validation.json`; output: `tests/last_test_output.txt`. Project dir: `/home/enduser/code/PeerTube-browser/.worktrees/21`.

### Out of scope

- Client-side pageview beacon and any new API endpoint (upgrade path: issue 18's beacon endpoint).
- Visit logging for pages other than About.
- Outbound-click tracking (issue 18).
- Any change to the Client backend, the Engine, their logging, or the 127.0.0.1:7079 Engine listener.
- Changing the vite build layout of About: the mapping lives in nginx.

## High-level plan

### Approach

The whole deliverable is documentation: the nginx site block in `DEPLOYMENT.md` §6 and a new Triage runbook. No app, frontend or build change. I read the tree to check the premises. `vite.config.ts` builds the `about` input from `dev-pages/about.html` or `dev-pages/about.template.html`, and the vite rewrite set is exactly `/about`, `/about/`, `/about.html`. The template uses only root-absolute links (`/favicon.png`, `/src/videos.css`, which the build turns into `/assets/…`, and nav links like `/about.html`), so serving the built file at `/about/` does not break any relative URL. The public site has only `location /`, the server-level `access_log` and the `add_header Content-Security-Policy … always`.

**Serving About (one location holds the logic, two exact aliases point to it).** The site block gains `location = /about.html`, which holds everything About needs:
- `set $static_page about;` names the page;
- `try_files /dev-pages/about.html /dev-pages/about.template.html =404;` serves the file in the same order vite builds it;
- the two `access_log` lines (main log in `peertube_browser`, pages log in the new format);
- no `add_header`, so the server-level CSP is inherited.

Two more exact locations, `location = /about` and `location = /about/`, contain only an internal `rewrite ^ /about.html last;`. That restarts the location search inside the same request, so the request ends in the About location. Exact-match (`=`) locations win over the `location /` prefix, and the other routes' locations are untouched, so they behave exactly as before. How each requirement is met:
- **200 on all three URLs.** `try_files` serves a found file in the current location, which also answers `HEAD` and conditional requests (`304`). When neither file exists, it answers nginx's own 404, and that request is still logged in this location.
- **CSP.** The About location declares no `add_header`, so the server-level CSP is inherited. The `always` flag means the 404 case carries it too.
- **One line per log per visit.** nginx writes access logs once per request, in the log phase, using the location where processing ended. A rewritten `/about` therefore writes exactly one line to each file. `$request_id` and `$request_uri` are fixed per request, so the logged URL is still `/about` as requested, query included.

**The pages log format.** A second `log_format`, `peertube_browser_pages`, sits directly under `peertube_browser`, outside `server {}`. It uses the same `key=value` style the main format already uses for `request_id=`, roughly in this order:
- `page=$static_page` — the marker;
- `ts=$msec` — epoch seconds with milliseconds, UTC by definition;
- `time=$time_iso8601` — readable local time;
- `ip=$remote_addr`;
- `method=$request_method`;
- `uri="$request_uri"`;
- `status=$status`;
- `rt=$request_time`;
- `request_id=$request_id`;
- `x_request_id=$http_x_request_id` — nginx writes `-` for an empty or absent variable, which gives the "`-` when absent" rule with no extra config;
- `ua="$http_user_agent"`.

The marker comes from a per-location variable, not a literal in the format. Adding a second informational page then means one more location of the same shape (its own `set`, `try_files` and the same two `access_log` lines), with no second `log_format`.

**Why both logs are listed.** The About location lists `access_log /var/log/nginx/peertube-browser.access.log peertube_browser;` and `access_log /var/log/nginx/peertube-browser.pages.access.log peertube_browser_pages;`. A location-level `access_log` replaces the inherited one, so without the first line About would drop out of the main log. §6 prose explains this next to the existing note on why `proxy_set_header` is repeated. It also says that `/var/log/nginx/*.log` is covered by the Debian/Ubuntu nginx logrotate rule, and that its postrotate signal reopens the new file as well.

**Runbook.** A new Triage subsection, "Follow an About visit", goes right after "Follow one request":
1. List visits: `sudo grep 'page=about'` on the pages log, narrowed with `grep ' status=200 '` or `' method=GET '`, or `awk` on those fields.
2. Find the visit's main-log line: `sudo grep "request_id=$id"` on `peertube-browser.access.log`, the same command "Follow one request" uses.
3. Correlate with the Client: take the visit's `ts=` (`$msec`) and `ip=`, and turn the epoch into the apps' format with `date -u -d @<msec> +%Y-%m-%dT%H:%M:%S.%3NZ` for the window start and start plus the window for its end. Then filter with `journalctl -u peertube-client.service -o cat | jq -cR --arg ip … --arg from … --arg to … 'fromjson? | select(.event == "request.start" and .context.ip == $ip and .ts >= $from and .ts <= $to)'`. The apps' `ts` is fixed-width UTC, so comparing the strings orders correctly and needs no date parsing in jq. The window is stated as 5 minutes by default and widened by hand. The `LOG_FORMAT=text` variant greps `request.start` and `ip=$ip`, then compares the leading `ts` field as a string with `awk`.
4. From a matched record's `request_id`, the existing "Follow one request" steps reach the Engine.

The runbook lists the four required caveats: no shared id; the IP is resolved through `TRUSTED_PROXIES`; formats and time zones differ, which the `date -u` step handles; bots are filtered only by user-agent, and the upgrade path is a pageview beacon on issue 18's endpoint, not a second endpoint. "What each log is for" gains a bullet for the pages log.

**Other docs.**
- `DEPLOYMENT.md` §3: the page list and the `try_files` paragraph say that About is built under `dev-pages/` and reached at `/about`, `/about/`, `/about.html` through the §6 mapping.
- §6 "Verify": add `curl -I http://localhost/about` (200, CSP header present) and a `tail` of the pages log.
- `client/frontend/README.md` "Local About Overrides": one line saying that prod nginx serves whichever file was built at those three URLs.
- Issue 21: delivery comment and status at completion.
- No other doc in the tree states the About URL or lists the nginx logs. `CONTEXT.md`, `client/README.md` and `README.md` mention nginx only for the request id and the 7079 listener.

**Validation hook (for the test step, sketched here only).** A test in `tests/active` pulls the fenced nginx block out of `DEPLOYMENT.md`. It swaps `root`, the log paths and `listen` for temp-dir values, wraps the block in a minimal `http {}` config, and runs `nginx -t`. Where possible it also starts nginx on a free high port to check the three 200s, the CSP header, the exact line counts in both logs, matching `request_id`s, and that `/` and `/api/…` produce no pages line. It is skipped when `shutil.which("nginx")` is None. The runbook check uses a synthetic pages line plus a synthetic Client JSON record.

### Alternatives considered

- **One regex location `~ ^/about(/|\.html)?$`.** It is one block, but the requirement asks for exact-match handling, and regex locations are matched in file order, which makes later edits easier to get wrong. Rejected.
- **Three full copies of the About body, one per exact URL.** No rewrite, but the two `access_log` lines, `set` and `try_files` would have to stay identical in three places. Missing one `access_log` line silently drops that URL from the main log. Rejected for that drift risk; the rewrite aliases are one line each.
- **`return 301` from `/about` and `/about/` to `/about.html`.** The requirement says each URL answers 200, and a redirect doubles the log lines per visit. Rejected.
- **A literal `page=about` in the format.** One variable fewer, but a second page would need a second `log_format`. Rejected for the `set` variable.
- **Building an ISO UTC millisecond timestamp in nginx** (a `map` on `$time_iso8601` plus the fraction of `$msec`). `$time_iso8601` is the server's local time, so the result is UTC only when the host's TZ is UTC, and doing better needs njs or a third-party module. Rejected. This is a deliberate simplification: the line carries `$msec`, which is exact UTC, and the runbook converts it in one `date -u` call. Upgrade path: if operators find this tedious, add the `map` on hosts that run in UTC.
- **A `map $uri` choosing the marker.** `$uri` changes to the `dev-pages` path after `try_files`, and `$request_uri` includes the query. Rejected.
- **Adding `$request_id` to the About response headers.** That needs an `add_header` in the location, which would then have to repeat the CSP, and nothing reads the header. Not done.

### Gotchas and risks

- **Rewrite semantics.** `last` keeps one request: one `$request_id`, one log phase. Using `break` or `redirect` instead would break this, so the prose says not to change it.
- **Direct hits on `/dev-pages/about*.html`** still go through `location /` and leave no pages line. Nothing links there. The docs state it as a limitation rather than hiding the path.
- **Escaping.** The default escape in `log_format` writes a `"` in the user-agent or URI as `\x22`, so the quoted fields stay parseable. The runbook's greps match on `key=` tokens, not positions.
- **IP text form.** The Client's `ip` and nginx's `$remote_addr` normally render the same, but IPv6 and IPv4-mapped forms can differ. This is noted under the proxy caveat.
- **Stale dev-pages files.** If both dev-pages files existed in the document root, `try_files` would prefer the override, as vite does. `rsync --delete` keeps only what the last build produced.
- **Existing deployments.** The site file is copied by hand, so existing hosts get About only after the operator re-applies §6 and reloads. The §6 text says so.
- **The automated nginx test** runs nginx without root and with temp paths. Its warning about the `user` directive is harmless. Hosts without nginx skip the test, as the requirements ask.

### Tradeoffs asked of the operator

- The timestamp is `$msec` (epoch milliseconds) plus `$time_iso8601` (local time, seconds only), not a ready UTC ISO-ms string. Comparing a visit with app `ts` takes one documented conversion step.
- Correlation is by IP plus time window only, so it is probabilistic. A NAT or shared IP can match the wrong visitor's records, and a visitor who leaves About without further API calls has none. The beacon is the named upgrade path.
- Bots are counted in the log and are filtered only by user-agent.
- About traffic writes two log lines per request. The extra volume is negligible.

## Impacts

<impacts>
<impact path="DEPLOYMENT.md" element="§6 nginx (production), the fenced `/etc/nginx/sites-available/peertube-browser` block: the `log_format` line (line 416)">
**What changes.** A second one-line, single-quoted `log_format peertube_browser_pages '…';` goes directly under `log_format peertube_browser` (line 416), outside `server {}`. Its tokens use the same `key=value` style the main format already uses for `request_id=`/`upstream=`/`rt=`: `page=$static_page ts=$msec time=$time_iso8601 ip=$remote_addr method=$request_method uri="$request_uri" status=$status rt=$request_time request_id=$request_id x_request_id=$http_x_request_id ua="$http_user_agent"`.

**What depends on it.** Only the new About location refers to it. It names `$static_page`, which nginx resolves at config load, so that variable must be declared by a `set` somewhere in the config. The plan's `set $static_page about;` in `location = /about.html` does that. If the `set` is removed or renamed, `nginx -t` fails with `unknown "static_page" variable`, and the whole host's nginx then fails its config test.

**Risk of regression.**
- **Field order is a security issue.** nginx's default log escaping turns `"`, `\` and bytes outside 0x20–0x7E into `\xNN`, but it leaves spaces alone. `$http_user_agent` and `$http_x_request_id` are fully client-controlled and can contain a forged ` status=200 ` or ` method=GET ` token. The plan suggests `grep ' status=200 '` / `' method=GET '` filters, and those can be spoofed.
  - Keep every client-controlled field (`x_request_id`, `ua`) at the end of the line.
  - The runbook should anchor on `^page=about ` and filter by awk field position over the fixed-format leading fields, not by an unanchored grep.
  - `uri="$request_uri"` sits before `status` in the plan's order. Recent nginx rejects a raw space in the request line with 400, so this is lower risk, but it is safer to put `uri` after `status`/`rt` as well. The plan only says the order is "roughly" this, so that is allowed.
- **`$msec`** renders as `1700000000.123`, seconds with a 3-digit fraction, which GNU `date -u -d @…` accepts.
- **`$time_iso8601`** is server-local time with a numeric offset, as the plan states.
</impact>
<impact path="DEPLOYMENT.md" element="§6 nginx (production) block: `server {}` body, the new `location = /about.html`, `location = /about`, `location = /about/` (insert among lines 428-457)">
**What changes.** Three exact-match locations are added. The best placement is right after `location /` (lines 428-430), so the four proxied blocks (432-457) stay together.
- `location = /about.html` holds:
  - `set $static_page about;`
  - `try_files /dev-pages/about.html /dev-pages/about.template.html =404;`
  - `access_log /var/log/nginx/peertube-browser.access.log peertube_browser;`
  - `access_log /var/log/nginx/peertube-browser.pages.access.log peertube_browser_pages;`
  - no `add_header`.
- `location = /about` and `location = /about/` each hold only `rewrite ^ /about.html last;`.

**Facts verified in the file.**
- Server level: `root /var/www/peertube-browser`, `index index.html`, a server-level `access_log` (424) and `add_header Content-Security-Policy … always` (426).
- `location /` is `try_files $uri $uri/ =404`. Nothing names `/about` today.
- The build emits only `dist/dev-pages/about*.html`. `client/frontend/dist/dev-pages/about.template.html` exists and there is no `dist/about.html`. So `/about.html`, which every page's nav links to, is a 404 in prod today. This change fixes that as a side effect, and it is a visible behaviour change for users.

**What depends on it.**
- Operators copy this block by hand.
- The whole nginx config, this site file included, is gated by `nginx -t` in `engine/install-engine-service.sh:401`, `engine/uninstall-engine-service.sh:115` and `scripts/deploy-bluegreen.sh:148,317`. A syntax error here therefore turns an Engine deploy into a `rollback … nginx_test`, and makes the installer refuse.
- "Follow one request" (line 236) greps the main log. That still works for About because the main `access_log` line is repeated in the location.

**Risk of regression.**
- A location-level `access_log` replaces the inherited server-level one. If the first `access_log` line is dropped, About disappears from the main log silently.
- Using `break`, `redirect` or `permanent` instead of `last` either serves from the rewrite location or doubles the requests and log lines.
- An `add_header` added later to the About location would drop the inherited CSP. The About template has no `<meta http-equiv>` CSP, unlike the other six pages, so the server header is its only CSP.
- With `=` exact matches, `/about.html?x=1` still matches, because the query is not part of the location match. `/About` and `/about//` do not match and fall to `location /`, which answers 404.
- The other routes' behaviour is unchanged.
</impact>
<impact path="DEPLOYMENT.md" element="§6 prose after the block, line 463 (the request-id / `proxy_set_header` / `log_format stays outside server {}` paragraph) and new prose next to it">
**What changes.**
- The sentence "`log_format` stays outside `server {}`…" becomes plural, because there are now two formats.
- New prose sits beside the existing note on why `proxy_set_header` is repeated. It covers:
  - why the About location lists both `access_log` lines (a location-level `access_log` replaces the inherited one);
  - that the location inherits the CSP because it has no `add_header`, and that About has no meta CSP;
  - that the `try_files` order mirrors vite's override-then-template order;
  - to keep `last`;
  - the new file `/var/log/nginx/peertube-browser.pages.access.log`, which falls under the Debian/Ubuntu `/var/log/nginx/*.log` logrotate rule, whose postrotate USR1 reopens it;
  - that direct hits on `/dev-pages/about*.html` go through `location /` and leave no pages line;
  - that existing hosts must re-apply §6 and reload.

**What depends on it.** The Triage runbook links here.

**Risk of regression.** Low, since this is prose. The logrotate claim holds only for the distro package layout. State it as Debian/Ubuntu-specific, as the plan does.
</impact>
<impact path="DEPLOYMENT.md" element="§6 TLS subsection (lines 525-533, `sudo certbot --nginx`)">
**What changes.** No change in the plan, but one is needed. `certbot --nginx` edits the live `/etc/nginx/sites-available/peertube-browser` in place: it adds `listen 443 ssl`, the certificate paths and a redirect. The plan tells existing hosts to "re-apply §6 and reload". An operator who copies the whole block over a certbot-edited file deletes the TLS config.

**What depends on it.** Every host that followed the TLS section.

**Risk of regression.** High for operators. The re-apply instruction should say to merge in only the new `log_format` line and the three locations, or to re-run `certbot --nginx` (or `certbot install`) afterwards. A full overwrite must not be the instruction.
</impact>
<impact path="DEPLOYMENT.md" element="§6 Verify (lines 475-481)">
**What changes.**
- Add `curl -I http://localhost/about`: 200 with a `Content-Security-Policy` header. `/about/` and `/about.html` can be listed as well.
- Add a `sudo tail -n 3 /var/log/nginx/peertube-browser.pages.access.log`.
- Optionally add a hint that a 404 on `/about` means the build did not produce `dev-pages/about*.html`, or §6 was not re-applied.

**What depends on it.** Operators after an install or re-apply.

**Risk of regression.** Low. `curl -I` sends HEAD, so it is logged as `method=HEAD`. The runbook's GET filter would exclude it, which is correct but worth knowing when someone checks that the tail shows "a visit".
</impact>
<impact path="DEPLOYMENT.md" element="§6 Engine listener paragraph, line 485 (\"leave the public site file above as it is, since nothing here changes it\")">
**What changes.** Nothing. I checked it against the plan: the plan touches only the public site file, not the 7079 listener, and this sentence still holds.

**What depends on it.** Nothing new.

**Risk of regression.** None. Listed only to confirm it was checked.
</impact>
<impact path="DEPLOYMENT.md" element="§3 Build the client, the `try_files` paragraph and page list (lines 299-303)">
**What changes.** The current text says every page is served through `try_files` and lists `about` among the pages. Add that About is built under `dist/dev-pages/` (`about.html` if the local override exists, else `about.template.html`) and is reached at `/about`, `/about/` and `/about.html` only through the §6 mapping.

**What depends on it.** The `scripts/sync.sh` workflow, and readers who add pages. The "Adding another informational page" story (one more location of the same shape) could be stated here or in §6.

**Risk of regression.** Low.
</impact>
<impact path="DEPLOYMENT.md" element="Triage: \"Follow one request\" (lines 231-249) and the new \"Follow an About visit\" subsection inserted after line 249, before \"Centralized installer\" at line 251">
**What changes.** A new subsection with four steps:
1. List visits from the pages log.
2. `sudo grep "request_id=$id"` on the main log.
3. Convert `ts=` with `date -u -d @<msec> +%Y-%m-%dT%H:%M:%S.%3NZ` and filter the Client journal with `jq` on `.event == "request.start" and .context.ip == $ip and .ts >= $from and .ts <= $to`. There is also a `LOG_FORMAT=text` variant.
4. Hand off to "Follow one request".

It also carries the four caveats: no shared id; IP resolved through `TRUSTED_PROXIES`, with IPv6 and IPv4-mapped text forms; formats and time zones; bots filtered only by user agent, with issue 18's beacon as the upgrade path. "What each log is for" (242-244) gains a pages-log bullet.

**Facts verified.** `client/backend/server.py:346-350`: `request.start` context is `{"ip", "method", "url", "user_agent"?}`. `_format_ts` (136-140) is a fixed-width UTC `YYYY-MM-DDTHH:MM:SS.mmmZ`, so comparing the strings orders correctly. JSON keys are `ts`, `event`, `context`, `request_id` (176-189). The existing jq idiom at line 237 is `jq -cR … 'fromjson? | select(…)'`.

**What depends on it.** Operators. Issue 21's validation clause "Correlation by request id/time window works against app traces".

**Risk of regression.**
- **Text mode.** `_render_text` (150-163) writes context as unquoted `key=value`. A grep for `ip=$ip` without a trailing space also matches `ip=1.2.3.45` when looking for `1.2.3.4`, so the runbook must use `"ip=$ip "`. `user_agent` comes after `ip` in the text line and is unquoted, so a UA can forge an ` ip=… ` token. Text-mode matching is weaker than JSON, and the runbook should say so.
- **Pages log.** `grep 'page=about'` without the `^` anchor can be forged through `ua`/`x_request_id`.
- **Time window.** The window must account for clock skew only within one host, which is fine. A visitor who leaves About makes no API call, so they have no Client record. That is stated as a tradeoff.
</impact>
<impact path="DEPLOYMENT.md" element="Triage table (lines 197-229)">
**What changes.** Optional. Add a row: `/about` (or `/about.html`) answers 404 → §6 not re-applied, or no `dev-pages/about*.html` in the document root → re-apply §6 / run `scripts/sync.sh`. Possibly another row: "About visit has no pages-log line" → the hit went to `/dev-pages/…` directly, or the second `access_log` line is missing.

**What depends on it.** Operators.

**Risk of regression.** None. It is additive.
</impact>
<impact path="DEPLOYMENT.md" element="§2 `LOG_FORMAT` paragraph (line 116)">
**What changes.** Optional. A pointer to "Follow an About visit" next to the existing pointer to "Follow one request". It should note that the text-mode recipe in the new runbook is weaker, because values are unquoted, which this paragraph already says ("values are not quoted, so it is for reading by eye").

**What depends on it.** Nothing.

**Risk of regression.** None.
</impact>
<impact path="DEPLOYMENT.md" element="§7 Verify page list (lines 561-565)">
**What changes.** Optional: add `/about` to the list of pages to open.

**What depends on it.** Nothing.

**Risk of regression.** None.
</impact>
<impact path="client/frontend/README.md" element="\"Local About Overrides\" (lines 36-39)">
**What changes.** Add one line: in prod, nginx serves whichever file was built (the `dev-pages/about.html` override first, then the template) at `/about`, `/about/` and `/about.html` (`DEPLOYMENT.md` §6). Optionally also:
- an override must use root-absolute URLs, because the same file is served at `/about/`, where relative URLs would resolve under `/about/`;
- it gets only the server CSP header (`script-src 'self'`, no inline script).

**What depends on it.** Developers writing the untracked override. `.gitignore:29-30` ignores `client/frontend/dev-pages/*` except the template, so the override is never in the repo and nothing checks it.

**Risk of regression.** Low. It is documentation. The real risk it guards against is an override that uses relative links, which break at `/about/`.
</impact>
<impact path="client/frontend/vite.config.ts" element="`aboutSourcePath`, `rewriteToAbout` (lines 13-22) and `build.rollupOptions.input.about` (lines 91-93)">
**What changes.** Nothing. This is the contract the nginx block copies:
- the `existsSync(dev-pages/about.html)` override, otherwise `about.template.html`, emitted at `dist/dev-pages/<same name>`;
- the rewrite set `/about`, `/about/`, `/about.html` (line 22), which is exactly the three nginx exact locations.

**What depends on it.** The nginx `try_files` order and its paths.

**Risk of regression.**
- If someone later renames the input, moves it out of `dev-pages/` or adds a URL to `rewriteToAbout`, nginx drifts silently. Nothing tests the two against each other. The new test could assert that the three exact-location URLs equal the `rewriteToAbout` set and that the `try_files` paths match the two `dev-pages` names, which would close that drift.
- Out of scope: the vite-only rewrites of `/videos` and `/search` (lines 20-21) have no prod nginx counterpart either. That is the same dev/prod gap class.
</impact>
<impact path="client/frontend/dev-pages/about.template.html" element="the whole template">
**What changes.** Nothing. I checked it: every URL is root-absolute (`/favicon.png`, `/src/videos.css`, which becomes `/assets/videos-*.css` in `dist/dev-pages/about.template.html:8`, and the nav `/channels.html`, `/`, `/likes.html`, `/about.html`). It has no `<meta http-equiv>` CSP, unlike the six top-level pages, and no script.

**What depends on it.** It is served at `/about/`, so relative URLs would break there. None exist.

**Risk of regression.** None for the template. If a later edit adds a relative link or an inline script, the link breaks at `/about/` or the script is blocked by the header CSP.
</impact>
<impact path="client/frontend/index.html" element="nav `href=\"/about.html\"` link (line 26); same link in videos.html:26, search.html:26, likes.html:26, channels.html:26, video-page.html:24">
**What changes.** Nothing in the files. These links 404 in prod today and resolve to 200 after the change, through `location = /about.html` with no rewrite. That is a user-visible fix.

**What depends on it.** Every page's navigation.

**Risk of regression.** None. It is noted because every About visit via nav arrives as `/about.html` and logs as `uri="/about.html"`, so the runbook should not assume `/about`.
</impact>
<impact path="client/frontend/dist/dev-pages/about.template.html" element="committed build output">
**What changes.** Nothing. It confirms the output layout: `dist/dev-pages/about.template.html` exists, and `dist/about.html` does not.

**What depends on it.** The `try_files` second candidate.

**Risk of regression.** None. The committed `dist/` lags the source (DEPLOYMENT.md line 412), but the about path layout is stable.
</impact>
<impact path="scripts/sync.sh" element="build then `rsync -a --delete` to `/var/www/peertube-browser/`">
**What changes.** Nothing.

**What depends on it.** `--delete` removes a stale `dev-pages/about.html` once the override is removed locally and rebuilt. That is what keeps the `try_files` preference correct, as the plan's "stale dev-pages files" gotcha says.

**Risk of regression.** Low. A manual copy without `--delete` would leave a stale override, and nginx would keep preferring it over a newer template.
</impact>
<impact path="client/backend/server.py" element="`_run_request` request.start context (lines 339-357), `_format_ts` (136-140), `_render_text` (150-163), `ClientLogFormatter.format` (174-195)">
**What changes.** Nothing; the runbook's step 3 depends on these.

**What depends on it.** The runbook's jq filter (`.event`, `.context.ip`, `.ts`) and its string comparison of `ts`.

**Risk of regression.**
- If `ts` ever stops being fixed-width UTC with a `Z` suffix, or `ip` moves out of `context`, the runbook silently matches nothing. No test ties the runbook to these. The planned synthetic-record runbook test should build its Client record by calling the real `ClientLogFormatter`, not a hand-written JSON string, so that drift turns the test red.
- The `rat-tail` comment at line 122 notes this module is mirrored in `engine/server/api/logging_profiles.py`. Step 4 of the runbook hands off to the Engine through "Follow one request", which relies on `request_id` only.
</impact>
<impact path="engine/install-engine-service.sh" element="`nginx -t` gate (line 401-406)">
**What changes.** Nothing.

**What depends on it.** It runs `nginx -t` over the whole host config, including the public site file.

**Risk of regression.** An invalid About block, such as a missing `set` or a misspelled format name, makes the prod Engine install fail with "nginx -t failed".
</impact>
<impact path="scripts/deploy-bluegreen.sh" element="`nginx -t` at line 317 and during rollback at line 148">
**What changes.** Nothing.

**What depends on it.** Same as above.

**Risk of regression.** A broken site file turns every deploy into `rollback phase=switching step=nginx_test`, and a broken restore into `rollback_failed … restore_nginx_test`. Triage row 225 already says `nginx -t` is "often an unrelated broken config", so no doc change is needed there.
</impact>
<impact path="engine/uninstall-engine-service.sh" element="`nginx -t` at line 115">
**What changes.** Nothing.

**What depends on it.** Same as above.

**Risk of regression.** A broken site file makes the uninstaller fail after it removes the listener.
</impact>
<impact path="tests/active/test_static_page_visit_logs.py" element="new test file (name to be chosen by the test step)">
**What changes.** A new test. It extracts the site block from `DEPLOYMENT.md`, rewrites `root`, the log paths and `listen` to temp-dir values, wraps the block in `http {}` and runs `nginx -t`. Where possible it also starts nginx on a free port and checks:
- 200 on the three URLs and the CSP header;
- exactly one line per log per request;
- matching `request_id` values;
- that `/` and `/api/…` produce no pages line.

A synthetic runbook check runs as well. The test is skipped when `shutil.which("nginx")` is None.

**What depends on it.** `.un/skills/devsecops/config.json` test_groups, which needs a new entry.

**Risk of regression / pitfalls (verified against the doc).**
- **Selecting the block.** `DEPLOYMENT.md` has two fenced `nginx` blocks: the site block (415-459) and the upstream snippet (488-492). The extraction must pick the one after the `/etc/nginx/sites-available/peertube-browser` caption, not the first or last ```` ```nginx ````.
- **Running unprivileged.**
  - nginx opens its compiled-in error log (`/var/log/nginx/error.log`) before it reads the config. Use `-e <tmp>/error.log` (nginx ≥1.19.5) or accept the alert.
  - `nginx -t` and the start fail with `mkdir() "/var/lib/nginx/body" failed (13)` unless `client_body_temp_path`, `proxy_temp_path`, `fastcgi_temp_path`, `uwsgi_temp_path` and `scgi_temp_path` point into the temp dir.
  - `pid` also needs a temp path, as does `-p <prefix>`.
- **The wrapper.**
  - Without `include mime.types` it serves `text/plain`, so do not assert `text/html` unless the wrapper includes it.
  - The `proxy_pass http://127.0.0.1:7072` lines are fine for `-t`. `/api/…` will answer 502 with nothing listening, which is still enough to assert "no pages line".
- **Log timing.** nginx writes the access-log line after it sends the response, so the test must poll the log files before counting lines.
- **Rewrites.** The rewrites of `/var/log/nginx/…` must cover both `access_log` lines inside the About location, not just the server-level one, or nginx tries to open `/var/log/nginx/…` and fails as non-root.
- **Bound to the doc text.** The test reads a doc's content, so a reflow of the doc or a quoting style change can break the extraction. Match on directive tokens, as `_statements()` in `tests/active/test_install_engine_service.py:141-145` does, not on whole lines.
</impact>
<impact path=".un/skills/devsecops/config.json" element="`test_groups` (lines 14-263)">
**What changes.** Add a group for the new test that maps `DEPLOYMENT.md`, and possibly `client/frontend/vite.config.ts` if the test asserts the URL set and `dev-pages` names. Non-code paths are already allowed: `tests/active/host_tokens.json` and `upstream_snippet_cases.json` are listed.

**What depends on it.** The runner selects groups from the changed files. Today no group maps `DEPLOYMENT.md`, so without this entry a doc-only change selects no test, and the new test never runs in the build's suite.

**Risk of regression.** Medium. Leaving it out silently skips the only validation of this build.
</impact>
<impact path="tests/active/test_install_engine_service.py" element="`_statements()` helper (lines 141-145)">
**What changes.** Nothing. It is the existing idiom for parsing nginx text into directives with comments stripped.

**What depends on it.** The new test may copy it. Test modules do not import from one another, so copying matches the repo's style.

**Risk of regression.** None.
</impact>
<impact path="docs/project/issues/21-static-page-visit-logs.md" element="`Status:` line and `## Comments`">
**What changes.** At completion:
- `Status: enhancement, complete`;
- a delivery comment naming `docs/project/plans/22-21-static-page-visit-logs.md`, in the same shape as the archived issue 19/20 comments;
- a move to `docs/project/issues/archive/`, as `docs/project/issue-tracker.md:21` requires.

The plan says only "status at completion", but the move is mandatory.

**What depends on it.** `docs/project/issues/plan.md` and the issue numbering, which counts `archive/`.

**Risk of regression.** Low. The issue-20 build left a duplicate in `issues/` because its agent had no delete tool (record step 9). The same could happen here.
</impact>
<impact path="docs/project/issues/plan.md" element="P5 row (line 42) and wave lane 5c (line 98)">
**What changes.**
- Lane 5c's "Main files" says "nginx docs, the About template, one Client endpoint". For 21, that is the nginx docs only; the template and the endpoint belong to 18. Mark 21 delivered there.
- Line 42 still says "19 and part of 20 are already delivered". That is stale on this branch, and it could be updated to say 19, 20 and 21 are delivered.

**What depends on it.** Planning.

**Risk of regression.** None.
</impact>
<impact path="docs/project/roadmap.md" element="`## Delivered` list (lines 7-25) and Logging chain line 157">
**What changes.** Optional: a Delivered bullet for issue 21 pointing to the plan. Line 157 (`19` -> `20` -> `21`) needs no change. The convention is applied unevenly: issues 19 and 20 have no Delivered bullet.

**What depends on it.** Nothing.

**Risk of regression.** None. Uncertain whether a bullet is expected.
</impact>
<impact path="docs/project/issues/18-about-outbound-click-tracking.md" element="`## Comments`">
**What changes.** Optional comment. Issue 21's runbook names 18's beacon endpoint as the pageview upgrade path. Line 14 plans `/api/analytics/outbound-click`, a click-specific endpoint, so a pageview would need 18's endpoint design to allow a page-view event type. There is no duplication, because 21 adds no endpoint.

**What depends on it.** The future design of 18.

**Risk of regression.** None. It is a naming-only forward reference: if 18 lands with a click-only schema, the runbook's "upgrade path" statement becomes inaccurate.
</impact>
<impact path="CONTEXT.md" element="glossary, \"Request id\" (line 10)">
**What changes.** Nothing required. The entry is still true: About lines carry nginx's `$request_id`, but no app record shares it, and the runbook says so. An optional glossary term ("pages log" / "informational static page") could be added. I consider it unnecessary because the plan scopes it to About only.

**What depends on it.** Nothing.

**Risk of regression.** None.
</impact>
<impact path="client/README.md" element="line 75 (request.start / \"byte counts are in the nginx access log\") and line 69 (`TRUSTED_PROXIES`)">
**What changes.** Nothing. It is the source of the runbook's statement that the Client's `ip` is resolved through `TRUSTED_PROXIES`. It points to "Follow one request", and a pointer to "Follow an About visit" could optionally be added.

**What depends on it.** Nothing.

**Risk of regression.** None.
</impact>
<impact path="engine/server/README.md" element="line 32 (request.start/end and the pointer to DEPLOYMENT.md Triage)">
**What changes.** Nothing. It is checked because step 4 of the runbook reaches the Engine through the same `request_id` flow.

**What depends on it.** Nothing.

**Risk of regression.** None.
</impact>
<impact path="docs/project/plans/22-21-static-page-visit-logs.md" element="the plan file">
**What changes.** Nothing by hand. Its header (line 3) says the dev-flow workflow renders it, and every edit is overwritten.

**What depends on it.** It is named in the issue 21 delivery comment.

**Risk of regression.** None.
</impact>
</impacts>

## Documentation to update

- [x] `DEPLOYMENT.md` - updated: I updated the prose in `DEPLOYMENT.md` to match what the build delivered: how About is served, the pages log, the About runbook caveats, and checks and warnings for operators. I didn't change the §6 nginx site block or the fenced runbook commands, since the tests check both.
- [x] `client/frontend/README.md` - updated: "Local About Overrides" now says how prod serves the built About page, that overrides need root-absolute URLs, and which CSP applies.
- [x] `docs/project/issues/21-static-page-visit-logs.md` - updated: Issue 21 marked delivered and copied to `docs/project/issues/archive/21-static-page-visit-logs.md` with a delivery comment. **The original at `docs/project/issues/21-static-page-visit-logs.md` still exists and needs deleting.** I have no tool that deletes files, so until it goes there are two copies.
- [x] `docs/project/issues/plan.md` - updated: plan.md: P5 row now says 19, 20 and 21 are delivered and 18 remains; lane 5c splits the file list between 21 and 18 and marks 21 delivered with its plan path.
- [x] `docs/project/issues/18-about-outbound-click-tracking.md` - updated: Added a comment to issue 18: issue 21 names this issue's beacon endpoint as the way to count pageviews, so the endpoint should also accept a page-view event type.
- [x] `docs/project/roadmap.md` - out of scope: No change needed. The Delivered list has no bullet for the sibling logging issues 19 and 20, so the convention does not call for one for 21. The Logging chain line (`19` -> `20` -> `21`) is still accurate.
- [x] `CONTEXT.md` - out of scope: No change needed. The "Request id" entry is still true: About lines carry nginx's `$request_id`, but no app record shares it. The scope is About only, so no new glossary term is warranted.
- [x] `client/README.md` - out of scope: No change needed. Its `TRUSTED_PROXIES` and `request.start` statements, which the runbook relies on, are unchanged and still true, and it makes no claim about About or the nginx logs.
- [x] `docs/project/adr/0002-trusted-proxy-client-address.md` - out of scope: No change needed. The runbook's IP caveat restates this ADR's resolution rule and does not change it. The build touches neither the Client backend nor the proxy headers.
- [x] `docs/project/adr/0004-cors-opt-in-by-origin.md` - out of scope: No change needed. Prod nginx still serves everything on one origin. The About locations add no headers and no cross-origin path.
- [x] `docs/project/adr/0009-engine-blue-green-through-nginx-upstream-snippet.md` - out of scope: No change needed. Only the public site file changed. The upstream snippet and the 7079 listener are untouched, and §6 line 526 ("leave the public site file above as it is, since nothing here changes it") is still accurate.

## Implementation plan

## Draft: issue 21, About visit log (documentation build)

Note on the brief: the ladder heading arrived with an unrendered `{rat_tail_ladder}` placeholder. I followed the two numbered ladder steps printed under it. The one deliberate mirror in this build (nginx copying vite's About mapping) is marked with the repo's existing `rat-tail:` comment convention, the same one used at `client/backend/server.py:122`.

### Module map

| File | Change |
|---|---|
| `DEPLOYMENT.md` §6 site block | Second `log_format`, three exact About locations |
| `DEPLOYMENT.md` §6 prose / Verify / TLS | About mapping prose, re-apply-without-overwrite rule, verify lines, certbot warning |
| `DEPLOYMENT.md` §3 | About's build location and URLs |
| `DEPLOYMENT.md` Triage | Two table rows, new "Follow an About visit" subsection, pages-log bullet |
| `DEPLOYMENT.md` §2, §7 | One pointer sentence, one page-list bullet |
| `client/frontend/README.md` | "Local About Overrides" gains the prod mapping and two constraints |
| `tests/active/test_static_page_visit_logs.py` | New (written by the test step; contract below) |
| `.un/skills/devsecops/config.json` | New `test_groups` entry |
| `docs/project/issues/21-…` | At completion: status, comment, move to `archive/` |
| `docs/project/issues/plan.md` | P5 row and lane 5c |
| `docs/project/issues/18-…` | One forward-reference comment |
| `docs/project/roadmap.md` | **Not changed.** Issues 19 and 20 have no Delivered bullet, and adding one only for 21 would make the list less consistent, not more. |

No app, frontend source or build file changes.

---

### 1. `DEPLOYMENT.md` §6: the site block (replaces lines 415–459)

````
```nginx
log_format peertube_browser '$remote_addr - $remote_user [$time_local] "$request" $status $body_bytes_sent "$http_referer" "$http_user_agent" request_id=$request_id upstream=$upstream_addr rt=$request_time';
log_format peertube_browser_pages 'page=$static_page ts=$msec time=$time_iso8601 ip=$remote_addr method=$request_method status=$status rt=$request_time request_id=$request_id uri="$request_uri" x_request_id=$http_x_request_id ua="$http_user_agent"';

server {
    listen 80;
    server_name _;

    root /var/www/peertube-browser;
    index index.html;
    access_log /var/log/nginx/peertube-browser.access.log peertube_browser;

    add_header Content-Security-Policy "default-src 'self'; script-src 'self'; object-src 'none'; base-uri 'self'; frame-src https:; connect-src 'self' https:; img-src 'self' https: data:" always;

    location / {
        try_files $uri $uri/ =404;
    }

    # rat-tail: these three URLs and the two dev-pages names mirror rewriteToAbout and aboutSourcePath in client/frontend/vite.config.ts; tests/active/test_static_page_visit_logs.py compares them, and building About to dist/about.html is the upgrade if the mapping grows.
    location = /about.html {
        set $static_page about;
        try_files /dev-pages/about.html /dev-pages/about.template.html =404;
        access_log /var/log/nginx/peertube-browser.access.log peertube_browser;
        access_log /var/log/nginx/peertube-browser.pages.access.log peertube_browser_pages;
    }
    location = /about {
        rewrite ^ /about.html last;
    }
    location = /about/ {
        rewrite ^ /about.html last;
    }

    location /api/ {
        … unchanged …
    }
    … /recommendations, /videos/similar, /client/ unchanged …
}
```
````

**Invariants**

- **Field order.** The first eight space-separated fields are fixed-format, and clients cannot inject spaces into them:

  | Position | Field |
  |---|---|
  | 1 | `page=` |
  | 2 | `ts=` |
  | 3 | `time=` |
  | 4 | `ip=` |
  | 5 | `method=` |
  | 6 | `status=` |
  | 7 | `rt=` |
  | 8 | `request_id=` |

  Every client-controlled field (`uri`, `x_request_id`, `ua`) comes after them. The runbook filters by `awk` field position, never with an unanchored grep. The plan said the order was only "roughly" fixed; I moved `uri` after `status`/`rt`, as the impact inventory recommends.
- **`x_request_id` stays unquoted.** nginx then writes a bare `-` when the header is absent, which is the format the requirement asks for.
- **No `add_header` in the About location.** That is how it inherits the server's CSP, `always` included, so the 404 carries it too.
- **The rewrites use `last`.** That keeps one request: one `$request_id`, one log phase, ending in `= /about.html`.
- **`$static_page` is declared once, by the `set`.** Removing the `set` makes `nginx -t` fail with `unknown "static_page" variable`.
- **`try_files` order matches vite's:** the override first, then the template.

### 2. `DEPLOYMENT.md` §6: prose after the block

**Line 463, last sentence, made plural:** "`log_format` stays outside `server {}`: the file is included in nginx's `http` block, the only place `log_format` is allowed, so both formats sit above the `server` block."

**New paragraph after line 463** (one line in the file):

> `/about`, `/about/` and `/about.html` are served by the three exact locations. The build emits About only as `dev-pages/about.html` (a local override) or `dev-pages/about.template.html` (`client/frontend/README.md`), never as `about.html`, so without them every page's About link is a 404. `location = /about.html` serves the override if the document root has one, otherwise the template, otherwise 404, in the same order as the build. The other two locations hand the request to it with `rewrite … last`. Keep `last`: it continues the same request, so a visit to `/about` is one request with one `$request_id`, logged once. `break` would serve from the rewriting location, which has no `try_files` and no pages log. `redirect` and `permanent` send the browser a second request. The About location writes both `access_log` lines because a location that declares any `access_log` inherits none from the server level. Dropping the first line silently removes About from `peertube-browser.access.log`. The location declares no `add_header`, so it inherits the server's `Content-Security-Policy`. About has no `<meta>` CSP of its own, so that header is its only CSP, and any `add_header` added there must repeat it. The second line writes `/var/log/nginx/peertube-browser.pages.access.log` in the `peertube_browser_pages` format, one line per About request of any method and status (see "Follow an About visit" under Triage). On Debian and Ubuntu, the nginx package's logrotate rule for `/var/log/nginx/*.log` rotates it, and its postrotate signal reopens it with the other logs. Elsewhere, add it to your rotation. Requests made directly to `/dev-pages/about*.html` go through `location /` and write no pages line. Nothing links there. To log another informational page, add one more exact location of the same shape, with its own `set $static_page <name>;`, its `try_files` and the same two `access_log` lines.

**New paragraph after it:**

> On a host that already runs this site, add the `peertube_browser_pages` line and the three About locations to the live `/etc/nginx/sites-available/peertube-browser` by hand, inside the `server` block that has `root /var/www/peertube-browser`. Then run `sudo nginx -t && sudo systemctl reload nginx`. Do not copy the whole block over the file: `sudo certbot --nginx` (see "TLS") edits it in place, and overwriting it removes the HTTPS listener and the redirect. If it was overwritten, run `sudo certbot --nginx` again. A broken site file fails `nginx -t` for the whole host, which also stops a prod Engine install and rolls back a deploy (Triage).

### 3. `DEPLOYMENT.md` §6 Verify (replaces lines 475–481)

````
Verify:
```bash
curl -I http://localhost/                 # 200, text/html
curl -s http://localhost/api/health       # client-backend JSON, publish_mode=bridge
curl -I http://localhost/about            # 200, text/html, Content-Security-Policy header; /about/ and /about.html the same
sudo tail -n 3 /var/log/nginx/peertube-browser.pages.access.log    # one page=about line per request above, method=HEAD for curl -I
```
A 404 on `/` with a successful `nginx -t` means the document root is unreadable by
`www-data`; check with `sudo -u www-data stat /var/www/peertube-browser/index.html`.
A 404 on `/about` while `/` answers 200 means the About locations are missing from the live site file, or the document root holds neither `dev-pages/about.html` nor `dev-pages/about.template.html` (`ls /var/www/peertube-browser/dev-pages/`; rebuild and sync, section 3).
````

The existing two-line hard wrap on the first 404 sentence is kept as it is. The new sentence is one line.

### 4. `DEPLOYMENT.md` §6 TLS (after line 533)

> `certbot --nginx` edits `/etc/nginx/sites-available/peertube-browser` in place. When this guide later changes that file, merge the change into it rather than copying the block over it (section 6), or run `sudo certbot --nginx` again afterwards.

### 5. `DEPLOYMENT.md` §3 (replaces lines 299–303, as one line)

> Every page is a separate build input, so adding one means rebuilding and re-copying: nginx serves `dist/` through `try_files`, and a page missing from the document root is a 404 rather than a fallback. After adding or changing a page, re-run this build and repeat the `rsync` in section 6. The current pages are `index`, `videos`, `search`, `likes`, `video-page`, `channels` and `about`. About is the exception to the one-file-per-URL layout: it is built as `dist/dev-pages/about.html` when the local override exists, otherwise as `dist/dev-pages/about.template.html` (`client/frontend/README.md`), and is reached at `/about`, `/about/` and `/about.html` only through the About locations in section 6.

I rewrote the paragraph as one line, following the no-softwrap rule. Most recent paragraphs in this file are already single lines.

### 6. `DEPLOYMENT.md` Triage table: two rows appended after line 229

```
| `/about`, `/about/` or `/about.html` answers 404 while `/` answers 200 | The live site file lacks the About locations, or the document root has no `dev-pages/about*.html` | Merge the About locations into the site file (section 6), or rebuild and sync (section 3) |
| An About visit has no line in `peertube-browser.pages.access.log`, or none in `peertube-browser.access.log` | The request went to `/dev-pages/about*.html` directly, or one of the About location's two `access_log` lines is missing | Section 6; the location must list both logs |
```

### 7. `DEPLOYMENT.md` Triage: "What each log is for", new bullet after line 244

> - The pages log, `/var/log/nginx/peertube-browser.pages.access.log`, records About visits only: one `page=about` line per request, beside its usual line in the access log. About makes no API call, so this is the only record of a visit (see "Follow an About visit").

### 8. `DEPLOYMENT.md` Triage: new subsection after line 249, before "Centralized installer"

````
### Follow an About visit

About is static and makes no API call, so a visit leaves no app record. nginx writes it to `/var/log/nginx/peertube-browser.pages.access.log` (section 6) as one line per request:
```
page=about ts=1700000000.123 time=2023-11-14T22:13:20+00:00 ip=203.0.113.7 method=GET status=200 rt=0.000 request_id=3f2a… uri="/about.html" x_request_id=- ua="Mozilla/5.0 …"
```
`ts` is the epoch in seconds with milliseconds, which is UTC. `time` is the server's local time, to the second. `x_request_id` is the `X-Request-ID` the request arrived with, or `-`. The first eight fields have a fixed form. `uri`, `x_request_id` and `ua` come from the client and can contain spaces and look-alike tokens, so match by field position, as below, not with a plain `grep`.

List visits, optionally only successful page loads:
```bash
sudo awk '$1 == "page=about"' /var/log/nginx/peertube-browser.pages.access.log
sudo awk '$1 == "page=about" && $5 == "method=GET" && $6 == "status=200"' /var/log/nginx/peertube-browser.pages.access.log
```
Nav links arrive as `uri="/about.html"`; `/about` and `/about/` are typed or shared URLs.

Find the same visit's access-log line by its id:
```bash
id=<request_id of the visit>
sudo grep "request_id=$id" /var/log/nginx/peertube-browser.access.log
```

Find the visitor's later API requests in the Client backend by client address and a time window after the visit (5 minutes here; widen `window` by hand):
```bash
line=$(sudo awk -v id="request_id=$id" '$1 == "page=about" && $8 == id' /var/log/nginx/peertube-browser.pages.access.log)
ip=$(printf '%s\n' "$line" | awk '{ sub(/^ip=/, "", $4); print $4 }')
msec=$(printf '%s\n' "$line" | awk '{ sub(/^ts=/, "", $2); print $2 }')
window=300
from=$(date -u -d "@$msec" +%Y-%m-%dT%H:%M:%S.%3NZ)
to=$(date -u -d "@$(( ${msec%.*} + window )).${msec#*.}" +%Y-%m-%dT%H:%M:%S.%3NZ)
journalctl -u peertube-client.service -o cat | jq -cR --arg ip "$ip" --arg from "$from" --arg to "$to" 'fromjson? | select(.event == "request.start" and .context.ip == $ip and .ts >= $from and .ts <= $to)'
```
The apps' `ts` is fixed-width UTC (section 2), so comparing it as a string orders it correctly. With `LOG_FORMAT=text`:
```bash
journalctl -u peertube-client.service -o cat | awk -v from="$from" -v to="$to" '$3 == "request.start" && $1 >= from && $1 <= to' | grep -F " ip=$ip "
```
Keep the spaces around `ip=$ip`, or `1.2.3.4` also matches `1.2.3.45`. Take `request_id` from a matching record and continue with "Follow one request" to reach the Engine.

Caveats:
- A visit shares no id with the visitor's API requests. About makes none, and nginx gives every request its own `$request_id`, so the match is by address and time only and is probabilistic. Visitors behind one NAT or shared address match each other's requests, and a visitor who leaves without opening another page has no Client record at all.
- The Client's `ip` is the address it resolves through `X-Forwarded-For` and `TRUSTED_PROXIES` (section 6), and it equals nginx's `ip` only when nginx is the only proxy. Behind a CDN or load balancer, nginx's `ip` is that layer's address and the Client's is the visitor's, so the two do not match. IPv6 and IPv4-mapped addresses (`::ffff:1.2.3.4`) can also be written differently in the two logs.
- nginx's `ts` is epoch seconds and `time` is local time. The apps' `ts` is UTC `YYYY-MM-DDTHH:MM:SS.mmmZ`. Convert with `date -u` as above before comparing, never `time`.
- Bots and crawlers are logged like visitors. The `ua` field is the only filter, and a client can put anything in it. In text mode, `user_agent` follows `ip` unquoted, so a user agent can also forge an ` ip=… ` token. JSON mode does not have this weakness. A client-side pageview beacon on the endpoint that `docs/project/issues/18-about-outbound-click-tracking.md` introduces would count human visits more cleanly. That is the upgrade path, not a second endpoint.
````

**Checked against the code.** `_render_text` writes `ts LEVEL event message k=v…`. `$3` is the event, and the message "request started" comes after it, so `$1` and `$3` are positional before any free text. Context order is `ip`, `method`, `url`, `user_agent` (`server.py:346-349`), so `ip=` is always followed by ` method=` and the trailing space is reliable. `$msec` always has a 3-digit fraction, so `${msec%.*}` and `${msec#*.}` split it safely, and `@<int>.<frac>` is GNU `date` syntax.

### 9. `DEPLOYMENT.md` §2 (line 116)

The pointer sentence at the end of the paragraph becomes: "To read every line of one request across nginx, the Client backend and the Engine, see "Follow one request" under Triage; to tie an About visit, which has no app record, to the visitor's later requests, see "Follow an About visit"."

### 10. `DEPLOYMENT.md` §7 (after line 564)

New bullet: `- `/about` (About; `/about/` and `/about.html` serve the same page)`.

### 11. `client/frontend/README.md` "Local About Overrides" (lines 36–39)

The existing three bullets stay. Two new bullets are appended:

```
- The build emits whichever source it used under `dist/dev-pages/` with the same name. In production nginx serves the override if present, otherwise the template, at `/about`, `/about/` and `/about.html` (`DEPLOYMENT.md` section 6), and logs each visit to its pages log.
- Because the same file is served at `/about/`, an override must use root-absolute URLs (`/favicon.png`, `/src/…`, `/about.html`); relative ones resolve under `/about/` there. It gets only nginx's `Content-Security-Policy` header (`script-src 'self'`), so inline scripts are blocked.
```

### 12. Test contract: `tests/active/test_static_page_visit_logs.py`

The test step writes this file; the contract is fixed here.

**Helpers**
- `_site_block()` takes the first fenced ```` ```nginx ```` block after the line containing `` `/etc/nginx/sites-available/peertube-browser`: ``. That is the right block, not the upstream snippet.
- `_statements()` is copied from `test_install_engine_service.py:141-145`.
- `_runbook()` takes the fenced `bash` blocks under `### Follow an About visit`.

**Wrapper config.** It is written to `tmp/nginx.conf` and run with `nginx -p tmp -e tmp/error.log -c tmp/nginx.conf`:
- `pid`, `events {}`;
- `http { client_body_temp_path`, `proxy_temp_path`, `fastcgi_temp_path`, `uwsgi_temp_path`, `scgi_temp_path` under tmp;
- `include <the block> }`.

**Substitutions** are made on directive tokens, not lines:
- `root` → `tmp/www`;
- every `/var/log/nginx/` (the server-level line and both About lines) → `tmp/log/`;
- `listen 80` → `listen 127.0.0.1:<free port>`.

**Skip rules.** Tests that need nginx are skipped when `shutil.which("nginx") is None`. jq tests are skipped without `jq`. The live-server tests are also skipped if nginx refuses to start unprivileged.

| Test | Asserts |
|---|---|
| `test_site_block_passes_nginx_t` | `nginx -t` exits 0 on the wrapped block |
| `test_about_urls_serve_page_with_csp` (param `/about`, `/about/`, `/about.html`, `/about.html?x=1`; GET and HEAD) | 200, the template's bytes for GET, a `Content-Security-Policy` header equal to the block's value |
| `test_override_preferred_and_404_without_files` | With both files, the override is served. With neither, 404 with CSP, and still one pages line with `status=404` |
| `test_each_about_request_logs_once_per_file` | After polling, exactly one new pages line and one new main line per request. Fields 1–8 are `page=about`, `ts=<d+.ddd>`, `time=`, `ip=127.0.0.1`, `method=`, `status=`, `rt=`, `request_id=<32 hex>`. `uri=` is the requested path plus query. The main line carries the same `request_id`. `x_request_id=-` without the header, and the sent value with it |
| `test_forged_user_agent_does_not_move_fields` | A UA ` status=200 method=GET page=about` on a 404 request leaves `$6 == status=404`, and the runbook's awk filter excludes it |
| `test_other_routes_write_no_pages_line` (`/`, `/index.html`, `/api/health` → 502, `/dev-pages/about.template.html`) | No new pages line; each still writes one main line |
| `test_about_mapping_matches_vite` (no nginx needed) | The exact-location URLs equal the string set in `rewriteToAbout` in `vite.config.ts`, and the `try_files` candidates are `/dev-pages/` plus the two names `aboutSourcePath` chooses between |
| `test_runbook_finds_visit_and_client_record` (needs jq, bash, GNU date) | Builds a pages line and a `request.start` record from the real `ClientLogFormatter` in JSON and text, with `record.created` = visit + 10 s, plus a decoy outside the window and a decoy on `1.2.3.45`. Running the runbook's `from`/`to`/jq/awk commands (journalctl swapped for `cat file`) selects exactly the in-window record |

**`config.json` entry:**

```json
"test_static_page_visit_logs.py": [
  "DEPLOYMENT.md",
  "client/frontend/vite.config.ts",
  "client/backend/server.py"
]
```

`server.py` is listed because the runbook test uses `ClientLogFormatter`, so a change to `ts` or the context shape selects the test.

### 13. Tracker edits at completion

**`docs/project/issues/21-static-page-visit-logs.md`.** Set `Status: enhancement, complete`, add the comment below under `## Comments`, then move the file to `docs/project/issues/archive/`. The move deletes the original; the build that lands this must have a delete, unlike the issue-20 build.

> - Delivered by `docs/project/plans/22-21-static-page-visit-logs.md`. About now serves in prod: public nginx answers `/about`, `/about/` and `/about.html` from `dev-pages/about.html` or `dev-pages/about.template.html` with the site's CSP, where `/about.html` used to be a 404. Each About request writes one `page=about` line to `/var/log/nginx/peertube-browser.pages.access.log` (`ts` epoch ms, local `time`, `ip`, `method`, `status`, `rt`, `request_id`, `uri`, `x_request_id` or `-`, `ua`) as well as its usual access-log line with the same `request_id`. `DEPLOYMENT.md` "Follow an About visit" lists visits and ties one to the visitor's Client `request.start` records by address and a time window, with its caveats. Only About is covered, and the client-side pageview beacon remains the upgrade path on issue 18's endpoint.

**`docs/project/issues/plan.md`**
- Line 42: "19, 20 and 21 are delivered (see triage). None of these block other work."
- Line 98: Main files "nginx docs (21); the About template, one Client endpoint (18)"; Depends on "20. 21 delivered, see `docs/project/plans/22-21-static-page-visit-logs.md`."

**`docs/project/issues/18-about-outbound-click-tracking.md`**, new comment:

> - Issue 21 (`DEPLOYMENT.md` "Follow an About visit") names this issue's beacon endpoint as the upgrade path for counting human About pageviews. If the endpoint stays outbound-click-only (`/api/analytics/outbound-click`), a pageview needs its own event type there. 21 added no endpoint.

---

### Ladder check

**Pass 1.** Problems found in the first draft:
- The listing used an unanchored `grep 'page=about'` with `' status=200 '`, which a client can spoof. Replaced by positional `awk` on `$1`, `$5` and `$6`.
- `uri` came before `status`. Moved behind the fixed fields.
- The text variant matched `ip=$ip` without delimiters. Now `" ip=$ip "` with `grep -F`.
- The window's end was computed with `date -d "@x + 300 seconds"`, which is unreliable. Replaced with bash integer arithmetic on `${msec%.*}`.
- "Re-apply §6" read as an overwrite. Replaced with a merge instruction plus the certbot warning.

**Pass 2.** Every requirement is met:

| Requirement | Where |
|---|---|
| Three URLs answer 200 | §1 locations |
| Override → template → 404 | §1 `try_files` |
| CSP | §1, no `add_header` |
| Other routes unchanged | `=` matches only; existing locations byte-identical |
| Separate file, both logs | §1, two `access_log` lines |
| Every listed field incl. `x_request_id` `-` | §1 format |
| All methods and statuses | Logging in the location's log phase |
| Rotation stated | §2 |
| Runbook steps and four caveats | §8 |
| Docs | §2–§11 and §13 |
| Validation: `nginx -t`, skip without nginx, line counts, runbook correlation, suite | §12 |

Every plan point is covered: the format and `set` variable, the alias rewrites, the prose, the runbook and `$msec` with `date -u`. Every settled impact is covered as well: TLS, Verify, the `config.json` group, the vite drift test, the archive move, plan.md and the issue 18 comment. Nothing is left open, so the draft converged in two passes.

### Simplifications named

- **Timestamp.** The line carries `$msec` (exact UTC) and local `$time_iso8601` rather than a ready UTC ISO-ms string, and the runbook converts with one `date -u`. The ceiling is one manual step per lookup. Upgrade path: a `map` that builds the string on hosts set to UTC.
- **Correlation is by address and time only.** The ceiling is NAT, shared addresses and visitors who leave without another request. The upgrade path is issue 18's beacon.
- **The nginx block mirrors vite's mapping.** It is kept in step by a test rather than shared code, and is marked `rat-tail:` in the block. The upgrade is building About as `dist/about.html`, which is out of scope here.


### Phases

#### Phase 1 - Serve About [code]

**Files touched.** DEPLOYMENT.md (EDITED: §6 site block, the three About locations and the rat-tail comment), tests/active/test_static_page_visit_logs.py (NEW), .un/skills/devsecops/config.json (EDITED: test_static_page_visit_logs.py group)

**Checkpoint.** Seam: the fenced nginx site block in DEPLOYMENT.md §6 running in a real nginx. `_site_block()` takes the first ```nginx fence after the `/etc/nginx/sites-available/peertube-browser`: line. Tokens are swapped (root → tmp/www, /var/log/nginx/ → tmp/log/, listen 80 → 127.0.0.1:<free port>), the block is wrapped in a minimal http{} config with temp paths, and it is run with `nginx -p tmp -e tmp/error.log -c tmp/nginx.conf`. `_statements()` is copied from test_install_engine_service.py:141-145, which is the precedent for parsing the block. No existing test starts a real nginx, so the live-server harness is new. Asserts: `nginx -t` exits 0. GET and HEAD on /about, /about/, /about.html and /about.html?x=1 return 200 with the template's bytes (GET) and a Content-Security-Policy header equal to the block's value. With both dev-pages files present, the override is served. With neither present, the answer is 404 and still carries the CSP. test_about_mapping_matches_vite needs no nginx: it parses vite.config.ts and asserts that the exact-location URLs equal the rewriteToAbout set, and that the try_files candidates are /dev-pages/ plus the two names aboutSourcePath picks between. Skipped when shutil.which("nginx") is None or nginx refuses to start unprivileged.

**Intent.** The §6 nginx site block in DEPLOYMENT.md serves About at /about, /about/ and /about.html through three exact locations, using the same file choice vite's build makes.

- C1 - Each of /about, /about/ and /about.html returns the dev-pages override if it exists, otherwise the template, otherwise a 404, and every one of those responses carries the server-level Content-Security-Policy.
- C2 - The block's exact-location URLs and try_files candidates equal the About mapping in client/frontend/vite.config.ts (rewriteToAbout and aboutSourcePath).

**Outcome.** ### DEPLOYMENT.md
In the §6 site block (`/etc/nginx/sites-available/peertube-browser`), right after `location / { … }`, I added three exact locations: `location = /about`, `location = /about/` and `location = /about.html`. Each one holds a single `try_files /dev-pages/about.html /dev-pages/about.template.html =404;`. That serves the dev-pages override if it exists, otherwise the template, otherwise a 404. The candidate order is vite's `aboutSourcePath` order, and the three URLs are vite's `rewriteToAbout` set.

None of the three locations has its own `add_header`, so each one picks up the server-level `Content-Security-Policy … always`, including on the 404.

Above the three locations sits a one-line `rat-tail:` comment. It says the URLs and the two file names copy vite.config.ts by hand, that `tests/active/test_static_page_visit_logs.py` compares the two, and that building About to `dist/about.html` is the fix if the mapping grows.

Each location has its own `try_files` rather than the draft's `rewrite ^ /about.html last` aliases. The checkpoint requires exactly one `try_files` per exact location, with vite's two picks. Nothing else in the block changed, and the §6 prose is untouched; the docs pass covers it.

### tests/active/test_static_page_visit_logs.py
Not created. The step asked for production code only. This phase's form of the durable test is the gated checkpoint in `tests/tmp/`, and a hand-made copy in `tests/active/` would be a second, ungated version of the same test. I followed the 01-32 build, where the implementer also left the active test for the workflow to promote.

### .un/skills/devsecops/config.json
Not edited, for a related reason. An entry naming `test_static_page_visit_logs.py` before that file exists shows up in `map_health` as an `unknown_groups` entry. The plan's entry also includes `client/backend/server.py`, which only the phase 3 runbook test needs. Whoever adds the entry should also list `client/frontend/dev-pages/about.template.html`, because the checkpoint reads its bytes. The plan's entry leaves it out.

#### Phase 2 - Pages log [code]

**Files touched.** DEPLOYMENT.md (EDITED: §6 site block, the peertube_browser_pages log_format, set $static_page and both access_log lines in the About location), tests/active/test_static_page_visit_logs.py (EDITED)

**Checkpoint.** Seam: the same live-nginx harness as phase 1, now reading the two temp log files (tmp/log/peertube-browser.access.log and tmp/log/peertube-browser.pages.access.log). After each request it polls for new lines. Asserts, for About requests (GET, HEAD, a 404 with no dev-pages files, with and without an X-Request-ID header): exactly one new pages line and exactly one new main line. Fields 1–8 of the pages line are page=about, ts=<digits.3digits>, time=, ip=127.0.0.1, method=, status=, rt=, request_id=<32 hex>. uri= is the requested path plus query. x_request_id is - when the header is absent and the sent value when present. The main line carries the same request_id. For /, /index.html, /api/health (502, since no upstream runs) and /dev-pages/about.template.html: no new pages line, and exactly one new main line each. Skipped like phase 1.

**Intent.** Every About request writes exactly one line to the new peertube_browser_pages log beside its usual main-log line, and requests to other routes write nothing there.

- C1 - Each About request, of any method or status, writes exactly one pages-log line and exactly one main-log line, and both carry the same request_id.
- C2 - Requests to /, /index.html, /api/ and /dev-pages/about*.html write no pages-log line and still write one main-log line each.

**Outcome.** ### DEPLOYMENT.md
In the §6 `/etc/nginx/sites-available/peertube-browser` block:
- Added `log_format peertube_browser_pages` beside `peertube_browser`, outside `server {}`. The fields are `page=$static_page ts=$msec time=$time_iso8601 ip=$remote_addr method=$request_method status=$status rt=$request_time request_id=$request_id uri=$request_uri x_request_id="$http_x_request_id" ua="$http_user_agent"`. The two values the client sends are in quotes because they may contain spaces. nginx writes `-` when they are empty.
- Each of the three About locations (`= /about`, `= /about/`, `= /about.html`) now has `set $static_page about;` and two `access_log` lines: the main `peertube-browser.access.log` with `peertube_browser`, and the new `peertube-browser.pages.access.log` with `peertube_browser_pages`. A comment above them gives the reason: an `access_log` in a location replaces the server's, so without the repeated main line, About requests would drop out of the main log. `try_files` and the rat-tail mapping comment are unchanged, so the phase-1 checks still match (one `try_files` per exact location, no nested braces).
- Other routes have no `access_log` of their own, so they keep only the server-level main log.

**Observed:** I ran a throwaway probe that loaded the checkpoint's own helpers against real nginx. It confirmed `nginx -t` passes and the request results below. I did not run the checkpoint itself.
- GET `/about.html?x=1` with an `X-Request-ID` header gave one main line and one pages line: `page=about ts=1790923037.172 time=2026-10-02T02:37:17-04:00 ip=127.0.0.1 method=GET status=200 rt=0.000 request_id=84a2…468d uri=/about.html?x=1 x_request_id="client-sent-7" ua="probe-agent/1"`. The main line had the same request_id.
- HEAD `/about/` without the header logged `x_request_id="-"` and the same request_id in both logs.
- `/api/health` (502) and a `/dev-pages/` path each wrote one main line and no pages line.

### tests/active/test_static_page_visit_logs.py
I didn't touch this file. The phase lists it as EDITED, but it doesn't exist in the worktree. I left creating or promoting it to the workflow, since writing it isn't production code for this checkpoint.

**Beyond the files named.** tests/tmp/probe_pages_log.py — the throwaway probe described in changes. I have no tool to delete files, so I emptied it instead (pytest collects nothing from it). Please delete it.

#### Phase 3 - Runbook commands [code]

**Files touched.** DEPLOYMENT.md (EDITED: Triage "Follow an About visit" heading and its fenced bash blocks), tests/active/test_static_page_visit_logs.py (EDITED)

**Checkpoint.** Seam: the fenced bash blocks under `### Follow an About visit` in DEPLOYMENT.md, which `_runbook()` extracts and runs under bash with journalctl replaced by `cat file`. test_forged_user_agent_does_not_move_fields (needs nginx) sends a 404 About request with UA ` status=200 method=GET page=about`. It asserts that the request's pages line has $6 == status=404, and that the runbook's listing awk filtered to GET/200 does not list it. test_runbook_finds_visit_and_client_record (needs jq, bash, GNU date; no nginx) writes a synthetic pages line plus request.start records produced by the real ClientLogFormatter from client/backend/server.py, in JSON and in text mode. The matching record has record.created = visit + 10 s, and there is one decoy outside the window and one decoy on 1.2.3.45. It asserts that the runbook's from/to/jq commands (JSON) and its awk/grep -F commands (text) each select exactly the in-window record.

**Intent.** The shell commands in DEPLOYMENT.md's new "Follow an About visit" Triage subsection select About visits by field position and find a visit's Client request.start records by its IP and time window.

- C1 - The runbook's listing filter, which selects by field position, does not list a 404 About request whose user agent carries forged status=200, method=GET and page=about tokens as a successful GET.
- C2 - The runbook's correlation commands select exactly the visitor's in-window request.start record from real ClientLogFormatter output in both JSON and text modes.

**Outcome.** ### DEPLOYMENT.md
- Added a `### Follow an About visit` subsection right after the Triage table, before `### Follow one request`. It sits there because the installer fences after "Follow one request" have no heading of their own. Had the section gone after them, the next-heading boundary would have pulled `sudo bash scripts/install-service.sh …` into the runbook.
- The prose says the pages log `/var/log/nginx/peertube-browser.pages.access.log` records every `/about`, `/about/` and `/about.html` request, HEAD requests and 404s included. It says the fields come in a fixed order and the visitor-supplied `x_request_id` and `ua` come last, so filtering goes by position: `$5` is the method, `$6` the status, `$8` the request_id. It also warns that a substring grep for `status=200` matches a forged user agent.
- Listing block (C1): `sudo awk '$5 == "method=GET" && $6 == "status=200"' …pages.access.log`.
- Correlation block (C2):
  - One `id=<request_id of the visit's pages line>` placeholder.
  - A `read -r ts ip < <(sudo awk -v id="$id" '$8 == "request_id=" id {…}' …)` line that takes the visit's `ts` and `ip` from the pages line. It contains neither `GET` nor `200`, so C1's filter selection does not pick it up as a listing line.
  - `from`/`to` built as UTC ISO strings with `date -u -d "@${ts%.*}" +%Y-%m-%dT%H:%M:%S` plus the log's own `.ms` and `Z`. I avoided `%3N` because this host's `date` prints `.123000000` for it, and `date -d "@… + 60 seconds"` because it is rejected as an invalid date.
  - A JSON-mode `jq` select on `event == "request.start"`, an exact `context.ip`, and `ts` between `from` and `to`.
  - A text-mode `awk` that checks `$3 == "request.start"`, `$6 == "ip=" ip` (the message is always the two words `request started`) and a string comparison of `$1` against the window.
- The window is the 60 s after the visit. The prose says to widen it for a slow visitor and that visitors behind one shared address are not told apart.
- The section closes by pointing to "Follow one request" for the rest of each printed record's request.

### tests/active/test_static_page_visit_logs.py
- Not touched. It does not exist in the worktree yet, and nothing in this phase's checkpoint needs it. I read the phase's `(EDITED)` entry as belonging to a later step that makes the durable copy.

### tests/tmp/probe_about_runbook_date.py
- A throwaway probe. It showed how `date` behaves under `TZ=EST5` and ran the checkpoint's two test functions against the new section from a separate path. Both passed, neither was skipped, and nginx ran for the forged-UA case. I have no delete tool, so I emptied the file; it holds no tests now and can be removed.

**Beyond the files named.** tests/tmp/probe_about_runbook_date.py — the probe file I used to observe `date` and the runbook's behaviour. It is empty now but still exists, because I had no tool to delete it; please remove it.


