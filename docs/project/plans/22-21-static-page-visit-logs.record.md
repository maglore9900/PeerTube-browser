# Build record - 21-static-page-visit-logs

Written by the `dev-flow` workflow. The plan it accompanies is `docs/project/plans/22-21-static-page-visit-logs.md`.

**Nothing but the workflow writes this file.** It carries the evidence each gate turned on: the baseline, both auditor verdicts verbatim, every self-check table, every red and its reason, every checkpoint outcome, and every amendment the operator approved to a settled section of the plan.

## Run state

<!-- dev-flow:state
```json
{
  "version": 1,
  "request": "# Static page visit logs for About and informational pages\n\nStatus: enhancement, needs-triage\nOrigin: task 43, [M7][F4]\n\n## Problem\n\nVisits to static informational pages (including About) are served as static files by nginx, so they are not visible in app request logs.\n\n## Proposed solution\n\nA dedicated logging path for static page visits, correlated with request tracing where possible.\n\n- Dedicated nginx logging for informational static routes: client IP, method, URL, status, response time, user-agent; a separate stream or an explicit marker field.\n- Preserve/propagate `X-Request-ID` in those nginx logs when available.\n- A runbook comparing static page visits from nginx logs with API traces from app logs.\n- Optional: a client-side pageview beacon for cleaner human-intent tracking.\n\n## Validation (from the original task)\n\n- Visiting informational pages produces entries with the expected fields.\n- Correlation by request id/time window works against app traces.\n\n## Related\n\n- After `20-request-lifecycle-logs`.\n- `18-about-outbound-click-tracking` instruments the same page as event analytics; do not duplicate.\n\n## Comments",
  "request_source": "read from docs/project/issues/21-static-page-visit-logs.md",
  "slug": "21-static-page-visit-logs",
  "steps": {
    "0": "done",
    "1": "done",
    "2": "done",
    "3": "done",
    "4": "done",
    "5": "done",
    "6": "done",
    "7": "done",
    "8": "done",
    "9": "done"
  },
  "phases": [
    {
      "n": "1",
      "kind": "code",
      "name": "Serve About",
      "checkpoint": "Seam: the fenced nginx site block in DEPLOYMENT.md \u00a76 running in a real nginx. `_site_block()` takes the first ```nginx fence after the `/etc/nginx/sites-available/peertube-browser`: line. Tokens are swapped (root \u2192 tmp/www, /var/log/nginx/ \u2192 tmp/log/, listen 80 \u2192 127.0.0.1:<free port>), the block is wrapped in a minimal http{} config with temp paths, and it is run with `nginx -p tmp -e tmp/error.log -c tmp/nginx.conf`. `_statements()` is copied from test_install_engine_service.py:141-145, which is the precedent for parsing the block. No existing test starts a real nginx, so the live-server harness is new. Asserts: `nginx -t` exits 0. GET and HEAD on /about, /about/, /about.html and /about.html?x=1 return 200 with the template's bytes (GET) and a Content-Security-Policy header equal to the block's value. With both dev-pages files present, the override is served. With neither present, the answer is 404 and still carries the CSP. test_about_mapping_matches_vite needs no nginx: it parses vite.config.ts and asserts that the exact-location URLs equal the rewriteToAbout set, and that the try_files candidates are /dev-pages/ plus the two names aboutSourcePath picks between. Skipped when shutil.which(\"nginx\") is None or nginx refuses to start unprivileged.",
      "intent": "The \u00a76 nginx site block in DEPLOYMENT.md serves About at /about, /about/ and /about.html through three exact locations, using the same file choice vite's build makes.",
      "clauses": [
        {
          "id": "C1",
          "text": "Each of /about, /about/ and /about.html returns the dev-pages override if it exists, otherwise the template, otherwise a 404, and every one of those responses carries the server-level Content-Security-Policy."
        },
        {
          "id": "C2",
          "text": "The block's exact-location URLs and try_files candidates equal the About mapping in client/frontend/vite.config.ts (rewriteToAbout and aboutSourcePath)."
        }
      ],
      "files": [
        "DEPLOYMENT.md (EDITED: \u00a76 site block",
        "the three About locations and the rat-tail comment)",
        "tests/active/test_static_page_visit_logs.py (NEW)",
        ".un/skills/devsecops/config.json (EDITED: test_static_page_visit_logs.py group)"
      ],
      "done": true,
      "outcome": "### DEPLOYMENT.md\nIn the \u00a76 site block (`/etc/nginx/sites-available/peertube-browser`), right after `location / { \u2026 }`, I added three exact locations: `location = /about`, `location = /about/` and `location = /about.html`. Each one holds a single `try_files /dev-pages/about.html /dev-pages/about.template.html =404;`. That serves the dev-pages override if it exists, otherwise the template, otherwise a 404. The candidate order is vite's `aboutSourcePath` order, and the three URLs are vite's `rewriteToAbout` set.\n\nNone of the three locations has its own `add_header`, so each one picks up the server-level `Content-Security-Policy \u2026 always`, including on the 404.\n\nAbove the three locations sits a one-line `rat-tail:` comment. It says the URLs and the two file names copy vite.config.ts by hand, that `tests/active/test_static_page_visit_logs.py` compares the two, and that building About to `dist/about.html` is the fix if the mapping grows.\n\nEach location has its own `try_files` rather than the draft's `rewrite ^ /about.html last` aliases. The checkpoint requires exactly one `try_files` per exact location, with vite's two picks. Nothing else in the block changed, and the \u00a76 prose is untouched; the docs pass covers it.\n\n### tests/active/test_static_page_visit_logs.py\nNot created. The step asked for production code only. This phase's form of the durable test is the gated checkpoint in `tests/tmp/`, and a hand-made copy in `tests/active/` would be a second, ungated version of the same test. I followed the 01-32 build, where the implementer also left the active test for the workflow to promote.\n\n### .un/skills/devsecops/config.json\nNot edited, for a related reason. An entry naming `test_static_page_visit_logs.py` before that file exists shows up in `map_health` as an `unknown_groups` entry. The plan's entry also includes `client/backend/server.py`, which only the phase 3 runbook test needs. Whoever adds the entry should also list `client/frontend/dev-pages/about.template.html`, because the checkpoint reads its bytes. The plan's entry leaves it out."
    },
    {
      "n": "2",
      "kind": "code",
      "name": "Pages log",
      "checkpoint": "Seam: the same live-nginx harness as phase 1, now reading the two temp log files (tmp/log/peertube-browser.access.log and tmp/log/peertube-browser.pages.access.log). After each request it polls for new lines. Asserts, for About requests (GET, HEAD, a 404 with no dev-pages files, with and without an X-Request-ID header): exactly one new pages line and exactly one new main line. Fields 1\u20138 of the pages line are page=about, ts=<digits.3digits>, time=, ip=127.0.0.1, method=, status=, rt=, request_id=<32 hex>. uri= is the requested path plus query. x_request_id is - when the header is absent and the sent value when present. The main line carries the same request_id. For /, /index.html, /api/health (502, since no upstream runs) and /dev-pages/about.template.html: no new pages line, and exactly one new main line each. Skipped like phase 1.",
      "intent": "Every About request writes exactly one line to the new peertube_browser_pages log beside its usual main-log line, and requests to other routes write nothing there.",
      "clauses": [
        {
          "id": "C1",
          "text": "Each About request, of any method or status, writes exactly one pages-log line and exactly one main-log line, and both carry the same request_id."
        },
        {
          "id": "C2",
          "text": "Requests to /, /index.html, /api/ and /dev-pages/about*.html write no pages-log line and still write one main-log line each."
        }
      ],
      "files": [
        "DEPLOYMENT.md (EDITED: \u00a76 site block",
        "the peertube_browser_pages log_format",
        "set $static_page and both access_log lines in the About location)",
        "tests/active/test_static_page_visit_logs.py (EDITED)"
      ],
      "done": true,
      "outcome": "### DEPLOYMENT.md\nIn the \u00a76 `/etc/nginx/sites-available/peertube-browser` block:\n- Added `log_format peertube_browser_pages` beside `peertube_browser`, outside `server {}`. The fields are `page=$static_page ts=$msec time=$time_iso8601 ip=$remote_addr method=$request_method status=$status rt=$request_time request_id=$request_id uri=$request_uri x_request_id=\"$http_x_request_id\" ua=\"$http_user_agent\"`. The two values the client sends are in quotes because they may contain spaces. nginx writes `-` when they are empty.\n- Each of the three About locations (`= /about`, `= /about/`, `= /about.html`) now has `set $static_page about;` and two `access_log` lines: the main `peertube-browser.access.log` with `peertube_browser`, and the new `peertube-browser.pages.access.log` with `peertube_browser_pages`. A comment above them gives the reason: an `access_log` in a location replaces the server's, so without the repeated main line, About requests would drop out of the main log. `try_files` and the rat-tail mapping comment are unchanged, so the phase-1 checks still match (one `try_files` per exact location, no nested braces).\n- Other routes have no `access_log` of their own, so they keep only the server-level main log.\n\n**Observed:** I ran a throwaway probe that loaded the checkpoint's own helpers against real nginx. It confirmed `nginx -t` passes and the request results below. I did not run the checkpoint itself.\n- GET `/about.html?x=1` with an `X-Request-ID` header gave one main line and one pages line: `page=about ts=1790923037.172 time=2026-10-02T02:37:17-04:00 ip=127.0.0.1 method=GET status=200 rt=0.000 request_id=84a2\u2026468d uri=/about.html?x=1 x_request_id=\"client-sent-7\" ua=\"probe-agent/1\"`. The main line had the same request_id.\n- HEAD `/about/` without the header logged `x_request_id=\"-\"` and the same request_id in both logs.\n- `/api/health` (502) and a `/dev-pages/` path each wrote one main line and no pages line.\n\n### tests/active/test_static_page_visit_logs.py\nI didn't touch this file. The phase lists it as EDITED, but it doesn't exist in the worktree. I left creating or promoting it to the workflow, since writing it isn't production code for this checkpoint.",
      "beyond": "tests/tmp/probe_pages_log.py \u2014 the throwaway probe described in changes. I have no tool to delete files, so I emptied it instead (pytest collects nothing from it). Please delete it."
    },
    {
      "n": "3",
      "kind": "code",
      "name": "Runbook commands",
      "checkpoint": "Seam: the fenced bash blocks under `### Follow an About visit` in DEPLOYMENT.md, which `_runbook()` extracts and runs under bash with journalctl replaced by `cat file`. test_forged_user_agent_does_not_move_fields (needs nginx) sends a 404 About request with UA ` status=200 method=GET page=about`. It asserts that the request's pages line has $6 == status=404, and that the runbook's listing awk filtered to GET/200 does not list it. test_runbook_finds_visit_and_client_record (needs jq, bash, GNU date; no nginx) writes a synthetic pages line plus request.start records produced by the real ClientLogFormatter from client/backend/server.py, in JSON and in text mode. The matching record has record.created = visit + 10 s, and there is one decoy outside the window and one decoy on 1.2.3.45. It asserts that the runbook's from/to/jq commands (JSON) and its awk/grep -F commands (text) each select exactly the in-window record.",
      "intent": "The shell commands in DEPLOYMENT.md's new \"Follow an About visit\" Triage subsection select About visits by field position and find a visit's Client request.start records by its IP and time window.",
      "clauses": [
        {
          "id": "C1",
          "text": "The runbook's listing filter, which selects by field position, does not list a 404 About request whose user agent carries forged status=200, method=GET and page=about tokens as a successful GET."
        },
        {
          "id": "C2",
          "text": "The runbook's correlation commands select exactly the visitor's in-window request.start record from real ClientLogFormatter output in both JSON and text modes."
        }
      ],
      "files": [
        "DEPLOYMENT.md (EDITED: Triage \"Follow an About visit\" heading and its fenced bash blocks)",
        "tests/active/test_static_page_visit_logs.py (EDITED)"
      ],
      "done": true,
      "outcome": "### DEPLOYMENT.md\n- Added a `### Follow an About visit` subsection right after the Triage table, before `### Follow one request`. It sits there because the installer fences after \"Follow one request\" have no heading of their own. Had the section gone after them, the next-heading boundary would have pulled `sudo bash scripts/install-service.sh \u2026` into the runbook.\n- The prose says the pages log `/var/log/nginx/peertube-browser.pages.access.log` records every `/about`, `/about/` and `/about.html` request, HEAD requests and 404s included. It says the fields come in a fixed order and the visitor-supplied `x_request_id` and `ua` come last, so filtering goes by position: `$5` is the method, `$6` the status, `$8` the request_id. It also warns that a substring grep for `status=200` matches a forged user agent.\n- Listing block (C1): `sudo awk '$5 == \"method=GET\" && $6 == \"status=200\"' \u2026pages.access.log`.\n- Correlation block (C2):\n  - One `id=<request_id of the visit's pages line>` placeholder.\n  - A `read -r ts ip < <(sudo awk -v id=\"$id\" '$8 == \"request_id=\" id {\u2026}' \u2026)` line that takes the visit's `ts` and `ip` from the pages line. It contains neither `GET` nor `200`, so C1's filter selection does not pick it up as a listing line.\n  - `from`/`to` built as UTC ISO strings with `date -u -d \"@${ts%.*}\" +%Y-%m-%dT%H:%M:%S` plus the log's own `.ms` and `Z`. I avoided `%3N` because this host's `date` prints `.123000000` for it, and `date -d \"@\u2026 + 60 seconds\"` because it is rejected as an invalid date.\n  - A JSON-mode `jq` select on `event == \"request.start\"`, an exact `context.ip`, and `ts` between `from` and `to`.\n  - A text-mode `awk` that checks `$3 == \"request.start\"`, `$6 == \"ip=\" ip` (the message is always the two words `request started`) and a string comparison of `$1` against the window.\n- The window is the 60 s after the visit. The prose says to widen it for a slow visitor and that visitors behind one shared address are not told apart.\n- The section closes by pointing to \"Follow one request\" for the rest of each printed record's request.\n\n### tests/active/test_static_page_visit_logs.py\n- Not touched. It does not exist in the worktree yet, and nothing in this phase's checkpoint needs it. I read the phase's `(EDITED)` entry as belonging to a later step that makes the durable copy.\n\n### tests/tmp/probe_about_runbook_date.py\n- A throwaway probe. It showed how `date` behaves under `TZ=EST5` and ran the checkpoint's two test functions against the new section from a separate path. Both passed, neither was skipped, and nginx ran for the forged-UA case. I have no delete tool, so I emptied the file; it holds no tests now and can be removed.",
      "beyond": "tests/tmp/probe_about_runbook_date.py \u2014 the probe file I used to observe `date` and the runbook's behaviour. It is empty now but still exists, because I had no tool to delete it; please remove it."
    }
  ],
  "digests": {
    "tests/tmp/test_21_static_page_visit_logs_phase1.py": "5b385fba5ea86326ad976854787ca200e17de85efee82ce88cd27e8ebb26d2b7",
    "tests/tmp/test_21_static_page_visit_logs_phase2.py": "b36a01b5e539446f9ad23687b3582cbe7597924818a986116776179b072ebf5c",
    "tests/tmp/test_21_static_page_visit_logs_phase3.py": "d6e465c4d71504208733be20c6df57f92fbd7034ec839759eaacb3e0d67f1345"
  },
  "paths": {
    "active": "tests/active",
    "working": "tests/tmp",
    "plans": "docs/project/plans",
    "delete_me": "delete_me",
    "archive": "tests/archive",
    "project_dir": "/home/enduser/code/PeerTube-browser/.worktrees/21",
    "record": "tests/last_test_validation.json",
    "output": "tests/last_test_output.txt"
  },
  "baseline": {
    "code": 0,
    "variant": false
  },
  "sessions": [
    "20261002T014454-82a0-dev-flow"
  ],
  "plan": "docs/project/plans/22-21-static-page-visit-logs.md",
  "record": "docs/project/plans/22-21-static-page-visit-logs.record.md",
  "replies": {
    "step_1_gather_requirements": "<requirements>\n### Purpose\n\nMake visits to the About page visible and attributable. About is the only purely informational page: it has no scripts and makes no API calls, so a visit never reaches the Client backend or the Engine and leaves no app log record. Today it does not even serve in prod (see \"Serve About in prod\"). The build gives operators a dedicated, greppable record of About visits from nginx, and a runbook that ties a visit to the same visitor's app traces. This is request-log visibility. It is not event analytics: About outbound-click analytics belong to `docs/project/issues/18-about-outbound-click-tracking.md`, and nothing here may duplicate that.\n\n### Scope decisions (operator-approved)\n\n- Only the About page counts as an \"informational static page\": URLs `/about`, `/about/` and `/about.html`. Other pages (index, videos, search, likes, video-page, channels) are out of scope, because their API calls already show in app logs. Adding another informational page later means adding one more exact-match location of the same shape.\n- The visit log is a separate file, and it does not replace the existing access log: About requests are written to both.\n- The optional client-side pageview beacon is out of scope. It is named in the runbook as the upgrade path, riding on the beacon endpoint that issue 18 introduces, and not as a second endpoint.\n- No Python, JavaScript or HTML change in the app or frontend. The deliverable is the documented nginx configuration and the runbook.\n\n### Serve About in prod\n\n- Current state, verified in the tree: `client/frontend/vite.config.ts` builds the `about` input from `client/frontend/dev-pages/about.html` when that local, untracked file exists, otherwise from `client/frontend/dev-pages/about.template.html`. The build output is therefore `dist/dev-pages/about.html` or `dist/dev-pages/about.template.html`, and there is never a `dist/about.html`. Every page's nav links to `/about.html`. The `/about`, `/about/`, `/about.html` rewrite exists only in vite's dev and preview servers. The public nginx site documented in `DEPLOYMENT.md` \u00a76 has only `location / { try_files $uri $uri/ =404; }`, so `/about.html` returns 404 in prod. The operator confirmed it really 404s.\n- Requirement: the public nginx site (`/etc/nginx/sites-available/peertube-browser` as documented in `DEPLOYMENT.md` \u00a76) gets exact-match handling for `/about`, `/about/` and `/about.html`. It serves `/dev-pages/about.html` if present in the document root, otherwise `/dev-pages/about.template.html`, otherwise 404. Each of the three URLs answers 200 with the built About page.\n- The About response must still carry the server-level `Content-Security-Policy` header. In nginx, a location that declares any `add_header` inherits none from the server level, so the About location must either declare none or repeat the CSP.\n- All other routes (`location /`, `/api/`, `/recommendations`, `/videos/similar`, `/client/`) behave exactly as before.\n\n### Dedicated About visit log\n\n- Every request handled by the About location writes one line to a new file, `/var/log/nginx/peertube-browser.pages.access.log`, in a new `log_format` defined beside `peertube_browser`. Like that one, it sits outside `server {}` because the site file is included in nginx's `http` block.\n- The same request also still writes its usual line to `/var/log/nginx/peertube-browser.access.log` in the `peertube_browser` format. In nginx, an `access_log` inside a location replaces the server-level one, so the About location must list both logs explicitly.\n- Each pages-log line carries:\n  - an explicit marker identifying the page (`page=about`);\n  - a timestamp with millisecond precision that can be compared with the apps' `ts` (UTC `YYYY-MM-DDTHH:MM:SS.mmmZ`), e.g. nginx `$msec` and/or `$time_iso8601`;\n  - client IP (`$remote_addr`);\n  - method;\n  - the URL as requested, path plus query (`$request_uri`);\n  - response status;\n  - response time (`$request_time`);\n  - user-agent;\n  - nginx's `$request_id`, the same id the visit's line in the main access log carries, so the two lines of one visit can be joined;\n  - the incoming `X-Request-ID` request header when the client or an upstream layer sent one (`$http_x_request_id`), with `-` when absent. This is the \"preserve when available\" part of the request. Nothing is proxied from this location, so there is nothing to propagate onward.\n- Every method and status that reaches the location is logged, including `HEAD`, `304` and `404`. The method and status fields let a reader filter.\n- Log rotation: the new file sits under `/var/log/nginx/` with a `.log` suffix, so the Debian/Ubuntu nginx logrotate rule covers it. The docs state this.\n\n### Runbook\n\nA new Triage entry in `DEPLOYMENT.md`, beside \"Follow one request\", that:\n- lists About visits from `/var/log/nginx/peertube-browser.pages.access.log` (grep for the marker; filter by status or method);\n- finds the same visit's line in the main access log by its `request_id`;\n- correlates a visit with the visitor's app traces by client IP plus a time window: Client backend `request.start` records whose `ip` equals the visit's client IP and whose `ts` falls within a stated window after the visit. It gives the commands in the same `journalctl \u2026 | jq` style as \"Follow one request\", with the `LOG_FORMAT=text` grep variant. From a Client record, the existing \"Follow one request\" steps reach the Engine;\n- states the caveats:\n  - an About visit shares no request id with later API calls: About makes no API calls, and nginx assigns each request its own `$request_id`. Correlation with app traces is by IP and time only, and therefore probabilistic (shared IPs and NAT).\n  - The Client's `ip` is resolved through `X-Forwarded-For` and `TRUSTED_PROXIES`, so it equals nginx's `$remote_addr` only when nginx is the sole proxy. Behind a CDN or load balancer, nginx's `$remote_addr` is that layer's address.\n  - The nginx timestamp and the app `ts` differ in format and time zone, so the reader must normalise to UTC.\n  - Bots and crawlers appear in the log. The user-agent is the only filter, and cleaner human-intent counting is the beacon upgrade path.\n\n### Documentation to update\n\n- `DEPLOYMENT.md` \u00a76, nginx (production): the site block gains the About location and the second `log_format`, with prose explaining the About mapping, why both `access_log` lines are repeated, the CSP inheritance rule, and the new file.\n- `DEPLOYMENT.md` \u00a73: the page list and the `try_files` note say that About is built under `dev-pages/` and served at `/about`, `/about/` and `/about.html` through the mapping.\n- `DEPLOYMENT.md` Triage: the runbook above. The \"What each log is for\" text mentions the pages log.\n- `docs/project/issues/21-static-page-visit-logs.md`: a delivery comment and a status update at completion, per `docs/project/issue-tracker.md` and `docs/project/triage-labels.md`.\n- Any other doc that states About is served at `/about.html` or lists the nginx logs (e.g. `client/frontend/README.md` \"Local About Overrides\"), checked during the impact inventory.\n\n### Validation\n\n- With the documented config, a request to each of `/about`, `/about/` and `/about.html` returns 200 with the built About page and the CSP header.\n- Each such request produces exactly one line in `peertube-browser.pages.access.log` carrying every field listed above, plus one line in `peertube-browser.access.log` with the same `request_id`.\n- Requests to other pages and API routes produce no pages-log line, and their main-log lines are unchanged.\n- Following the runbook against a visit and a subsequent API request from the same client finds the visit and that client's `request.start` record within the window.\n- Where an `nginx` binary is available, the documented site config passes `nginx -t`. Where it is not, any automated check must skip rather than fail.\n- The existing suite stays green.\n\n### Baseline suite state\n\nPre-build suite exited 0, baseline variant false (selected 1 of 46 test groups: `test_search_fusion.py`, 10 passed). Active tests are in `tests/active`, working tests in `tests/tmp`, archive in `tests/archive`. Run record: `tests/last_test_validation.json`; output: `tests/last_test_output.txt`. Project dir: `/home/enduser/code/PeerTube-browser/.worktrees/21`.\n\n### Out of scope\n\n- Client-side pageview beacon and any new API endpoint (upgrade path: issue 18's beacon endpoint).\n- Visit logging for pages other than About.\n- Outbound-click tracking (issue 18).\n- Any change to the Client backend, the Engine, their logging, or the 127.0.0.1:7079 Engine listener.\n- Changing the vite build layout of About: the mapping lives in nginx.\n</requirements>\n\n<conflicts>\nRequest \"Correlation by request id ... works against app traces\" and \"Preserve/propagate X-Request-ID\" vs tree: About has no scripts and makes no API calls (`client/frontend/dev-pages/about.template.html`), and public nginx assigns each request its own `$request_id`, so an About visit can never share a request id with the visitor's app traces. Request-id correlation only joins the pages-log line to the same visit's main access-log line; correlation with app traces is by client IP plus time window, unless a beacon is added, which the operator ruled out of scope.\nRequest's premise that About visits are served as static files vs tree: the build emits only `dist/dev-pages/about.html` or `dist/dev-pages/about.template.html` (`client/frontend/vite.config.ts`), while nav links and the request target `/about.html`, and the `DEPLOYMENT.md` \u00a76 nginx site (`try_files $uri $uri/ =404`) has no mapping, so About returns 404 in prod. The operator confirmed this and chose to add the mapping in this build.\nRequest Problem \"not visible in app request logs\" vs tree: static requests already appear in `/var/log/nginx/peertube-browser.access.log` with IP, request, status, UA, `request_id` and `rt` (`DEPLOYMENT.md` \u00a76 `peertube_browser` format). What is missing is a dedicated About stream with a marker, and About actually serving, not nginx visibility as such.\n</conflicts>",
    "step_2_develop_solution": "<initial_solution>\n### Approach\n\nThe whole deliverable is documentation: the nginx site block in `DEPLOYMENT.md` \u00a76 and a new Triage runbook. No app, frontend or build change. I read the tree to check the premises. `vite.config.ts` builds the `about` input from `dev-pages/about.html` or `dev-pages/about.template.html`, and the vite rewrite set is exactly `/about`, `/about/`, `/about.html`. The template uses only root-absolute links (`/favicon.png`, `/src/videos.css`, which the build turns into `/assets/\u2026`, and nav links like `/about.html`), so serving the built file at `/about/` does not break any relative URL. The public site has only `location /`, the server-level `access_log` and the `add_header Content-Security-Policy \u2026 always`.\n\n**Serving About (one location holds the logic, two exact aliases point to it).** The site block gains `location = /about.html`, which holds everything About needs:\n- `set $static_page about;` names the page;\n- `try_files /dev-pages/about.html /dev-pages/about.template.html =404;` serves the file in the same order vite builds it;\n- the two `access_log` lines (main log in `peertube_browser`, pages log in the new format);\n- no `add_header`, so the server-level CSP is inherited.\n\nTwo more exact locations, `location = /about` and `location = /about/`, contain only an internal `rewrite ^ /about.html last;`. That restarts the location search inside the same request, so the request ends in the About location. Exact-match (`=`) locations win over the `location /` prefix, and the other routes' locations are untouched, so they behave exactly as before. How each requirement is met:\n- **200 on all three URLs.** `try_files` serves a found file in the current location, which also answers `HEAD` and conditional requests (`304`). When neither file exists, it answers nginx's own 404, and that request is still logged in this location.\n- **CSP.** The About location declares no `add_header`, so the server-level CSP is inherited. The `always` flag means the 404 case carries it too.\n- **One line per log per visit.** nginx writes access logs once per request, in the log phase, using the location where processing ended. A rewritten `/about` therefore writes exactly one line to each file. `$request_id` and `$request_uri` are fixed per request, so the logged URL is still `/about` as requested, query included.\n\n**The pages log format.** A second `log_format`, `peertube_browser_pages`, sits directly under `peertube_browser`, outside `server {}`. It uses the same `key=value` style the main format already uses for `request_id=`, roughly in this order:\n- `page=$static_page` \u2014 the marker;\n- `ts=$msec` \u2014 epoch seconds with milliseconds, UTC by definition;\n- `time=$time_iso8601` \u2014 readable local time;\n- `ip=$remote_addr`;\n- `method=$request_method`;\n- `uri=\"$request_uri\"`;\n- `status=$status`;\n- `rt=$request_time`;\n- `request_id=$request_id`;\n- `x_request_id=$http_x_request_id` \u2014 nginx writes `-` for an empty or absent variable, which gives the \"`-` when absent\" rule with no extra config;\n- `ua=\"$http_user_agent\"`.\n\nThe marker comes from a per-location variable, not a literal in the format. Adding a second informational page then means one more location of the same shape (its own `set`, `try_files` and the same two `access_log` lines), with no second `log_format`.\n\n**Why both logs are listed.** The About location lists `access_log /var/log/nginx/peertube-browser.access.log peertube_browser;` and `access_log /var/log/nginx/peertube-browser.pages.access.log peertube_browser_pages;`. A location-level `access_log` replaces the inherited one, so without the first line About would drop out of the main log. \u00a76 prose explains this next to the existing note on why `proxy_set_header` is repeated. It also says that `/var/log/nginx/*.log` is covered by the Debian/Ubuntu nginx logrotate rule, and that its postrotate signal reopens the new file as well.\n\n**Runbook.** A new Triage subsection, \"Follow an About visit\", goes right after \"Follow one request\":\n1. List visits: `sudo grep 'page=about'` on the pages log, narrowed with `grep ' status=200 '` or `' method=GET '`, or `awk` on those fields.\n2. Find the visit's main-log line: `sudo grep \"request_id=$id\"` on `peertube-browser.access.log`, the same command \"Follow one request\" uses.\n3. Correlate with the Client: take the visit's `ts=` (`$msec`) and `ip=`, and turn the epoch into the apps' format with `date -u -d @<msec> +%Y-%m-%dT%H:%M:%S.%3NZ` for the window start and start plus the window for its end. Then filter with `journalctl -u peertube-client.service -o cat | jq -cR --arg ip \u2026 --arg from \u2026 --arg to \u2026 'fromjson? | select(.event == \"request.start\" and .context.ip == $ip and .ts >= $from and .ts <= $to)'`. The apps' `ts` is fixed-width UTC, so comparing the strings orders correctly and needs no date parsing in jq. The window is stated as 5 minutes by default and widened by hand. The `LOG_FORMAT=text` variant greps `request.start` and `ip=$ip`, then compares the leading `ts` field as a string with `awk`.\n4. From a matched record's `request_id`, the existing \"Follow one request\" steps reach the Engine.\n\nThe runbook lists the four required caveats: no shared id; the IP is resolved through `TRUSTED_PROXIES`; formats and time zones differ, which the `date -u` step handles; bots are filtered only by user-agent, and the upgrade path is a pageview beacon on issue 18's endpoint, not a second endpoint. \"What each log is for\" gains a bullet for the pages log.\n\n**Other docs.**\n- `DEPLOYMENT.md` \u00a73: the page list and the `try_files` paragraph say that About is built under `dev-pages/` and reached at `/about`, `/about/`, `/about.html` through the \u00a76 mapping.\n- \u00a76 \"Verify\": add `curl -I http://localhost/about` (200, CSP header present) and a `tail` of the pages log.\n- `client/frontend/README.md` \"Local About Overrides\": one line saying that prod nginx serves whichever file was built at those three URLs.\n- Issue 21: delivery comment and status at completion.\n- No other doc in the tree states the About URL or lists the nginx logs. `CONTEXT.md`, `client/README.md` and `README.md` mention nginx only for the request id and the 7079 listener.\n\n**Validation hook (for the test step, sketched here only).** A test in `tests/active` pulls the fenced nginx block out of `DEPLOYMENT.md`. It swaps `root`, the log paths and `listen` for temp-dir values, wraps the block in a minimal `http {}` config, and runs `nginx -t`. Where possible it also starts nginx on a free high port to check the three 200s, the CSP header, the exact line counts in both logs, matching `request_id`s, and that `/` and `/api/\u2026` produce no pages line. It is skipped when `shutil.which(\"nginx\")` is None. The runbook check uses a synthetic pages line plus a synthetic Client JSON record.\n\n### Alternatives considered\n\n- **One regex location `~ ^/about(/|\\.html)?$`.** It is one block, but the requirement asks for exact-match handling, and regex locations are matched in file order, which makes later edits easier to get wrong. Rejected.\n- **Three full copies of the About body, one per exact URL.** No rewrite, but the two `access_log` lines, `set` and `try_files` would have to stay identical in three places. Missing one `access_log` line silently drops that URL from the main log. Rejected for that drift risk; the rewrite aliases are one line each.\n- **`return 301` from `/about` and `/about/` to `/about.html`.** The requirement says each URL answers 200, and a redirect doubles the log lines per visit. Rejected.\n- **A literal `page=about` in the format.** One variable fewer, but a second page would need a second `log_format`. Rejected for the `set` variable.\n- **Building an ISO UTC millisecond timestamp in nginx** (a `map` on `$time_iso8601` plus the fraction of `$msec`). `$time_iso8601` is the server's local time, so the result is UTC only when the host's TZ is UTC, and doing better needs njs or a third-party module. Rejected. This is a deliberate simplification: the line carries `$msec`, which is exact UTC, and the runbook converts it in one `date -u` call. Upgrade path: if operators find this tedious, add the `map` on hosts that run in UTC.\n- **A `map $uri` choosing the marker.** `$uri` changes to the `dev-pages` path after `try_files`, and `$request_uri` includes the query. Rejected.\n- **Adding `$request_id` to the About response headers.** That needs an `add_header` in the location, which would then have to repeat the CSP, and nothing reads the header. Not done.\n\n### Gotchas and risks\n\n- **Rewrite semantics.** `last` keeps one request: one `$request_id`, one log phase. Using `break` or `redirect` instead would break this, so the prose says not to change it.\n- **Direct hits on `/dev-pages/about*.html`** still go through `location /` and leave no pages line. Nothing links there. The docs state it as a limitation rather than hiding the path.\n- **Escaping.** The default escape in `log_format` writes a `\"` in the user-agent or URI as `\\x22`, so the quoted fields stay parseable. The runbook's greps match on `key=` tokens, not positions.\n- **IP text form.** The Client's `ip` and nginx's `$remote_addr` normally render the same, but IPv6 and IPv4-mapped forms can differ. This is noted under the proxy caveat.\n- **Stale dev-pages files.** If both dev-pages files existed in the document root, `try_files` would prefer the override, as vite does. `rsync --delete` keeps only what the last build produced.\n- **Existing deployments.** The site file is copied by hand, so existing hosts get About only after the operator re-applies \u00a76 and reloads. The \u00a76 text says so.\n- **The automated nginx test** runs nginx without root and with temp paths. Its warning about the `user` directive is harmless. Hosts without nginx skip the test, as the requirements ask.\n\n### Tradeoffs asked of the operator\n\n- The timestamp is `$msec` (epoch milliseconds) plus `$time_iso8601` (local time, seconds only), not a ready UTC ISO-ms string. Comparing a visit with app `ts` takes one documented conversion step.\n- Correlation is by IP plus time window only, so it is probabilistic. A NAT or shared IP can match the wrong visitor's records, and a visitor who leaves About without further API calls has none. The beacon is the named upgrade path.\n- Bots are counted in the log and are filtered only by user-agent.\n- About traffic writes two log lines per request. The extra volume is negligible.\n</initial_solution>\n\n<conflicts>\nnone\n</conflicts>",
    "step_3_identify_impacts": "<impacts>\n<impacts>\n<impact path=\"DEPLOYMENT.md\" element=\"\u00a76 nginx (production), the fenced `/etc/nginx/sites-available/peertube-browser` block: the `log_format` line (line 416)\">\n**What changes.** A second one-line, single-quoted `log_format peertube_browser_pages '\u2026';` goes directly under `log_format peertube_browser` (line 416), outside `server {}`. Its tokens use the same `key=value` style the main format already uses for `request_id=`/`upstream=`/`rt=`: `page=$static_page ts=$msec time=$time_iso8601 ip=$remote_addr method=$request_method uri=\"$request_uri\" status=$status rt=$request_time request_id=$request_id x_request_id=$http_x_request_id ua=\"$http_user_agent\"`.\n\n**What depends on it.** Only the new About location refers to it. It names `$static_page`, which nginx resolves at config load, so that variable must be declared by a `set` somewhere in the config. The plan's `set $static_page about;` in `location = /about.html` does that. If the `set` is removed or renamed, `nginx -t` fails with `unknown \"static_page\" variable`, and the whole host's nginx then fails its config test.\n\n**Risk of regression.**\n- **Field order is a security issue.** nginx's default log escaping turns `\"`, `\\` and bytes outside 0x20\u20130x7E into `\\xNN`, but it leaves spaces alone. `$http_user_agent` and `$http_x_request_id` are fully client-controlled and can contain a forged ` status=200 ` or ` method=GET ` token. The plan suggests `grep ' status=200 '` / `' method=GET '` filters, and those can be spoofed.\n  - Keep every client-controlled field (`x_request_id`, `ua`) at the end of the line.\n  - The runbook should anchor on `^page=about ` and filter by awk field position over the fixed-format leading fields, not by an unanchored grep.\n  - `uri=\"$request_uri\"` sits before `status` in the plan's order. Recent nginx rejects a raw space in the request line with 400, so this is lower risk, but it is safer to put `uri` after `status`/`rt` as well. The plan only says the order is \"roughly\" this, so that is allowed.\n- **`$msec`** renders as `1700000000.123`, seconds with a 3-digit fraction, which GNU `date -u -d @\u2026` accepts.\n- **`$time_iso8601`** is server-local time with a numeric offset, as the plan states.\n</impact>\n<impact path=\"DEPLOYMENT.md\" element=\"\u00a76 nginx (production) block: `server {}` body, the new `location = /about.html`, `location = /about`, `location = /about/` (insert among lines 428-457)\">\n**What changes.** Three exact-match locations are added. The best placement is right after `location /` (lines 428-430), so the four proxied blocks (432-457) stay together.\n- `location = /about.html` holds:\n  - `set $static_page about;`\n  - `try_files /dev-pages/about.html /dev-pages/about.template.html =404;`\n  - `access_log /var/log/nginx/peertube-browser.access.log peertube_browser;`\n  - `access_log /var/log/nginx/peertube-browser.pages.access.log peertube_browser_pages;`\n  - no `add_header`.\n- `location = /about` and `location = /about/` each hold only `rewrite ^ /about.html last;`.\n\n**Facts verified in the file.**\n- Server level: `root /var/www/peertube-browser`, `index index.html`, a server-level `access_log` (424) and `add_header Content-Security-Policy \u2026 always` (426).\n- `location /` is `try_files $uri $uri/ =404`. Nothing names `/about` today.\n- The build emits only `dist/dev-pages/about*.html`. `client/frontend/dist/dev-pages/about.template.html` exists and there is no `dist/about.html`. So `/about.html`, which every page's nav links to, is a 404 in prod today. This change fixes that as a side effect, and it is a visible behaviour change for users.\n\n**What depends on it.**\n- Operators copy this block by hand.\n- The whole nginx config, this site file included, is gated by `nginx -t` in `engine/install-engine-service.sh:401`, `engine/uninstall-engine-service.sh:115` and `scripts/deploy-bluegreen.sh:148,317`. A syntax error here therefore turns an Engine deploy into a `rollback \u2026 nginx_test`, and makes the installer refuse.\n- \"Follow one request\" (line 236) greps the main log. That still works for About because the main `access_log` line is repeated in the location.\n\n**Risk of regression.**\n- A location-level `access_log` replaces the inherited server-level one. If the first `access_log` line is dropped, About disappears from the main log silently.\n- Using `break`, `redirect` or `permanent` instead of `last` either serves from the rewrite location or doubles the requests and log lines.\n- An `add_header` added later to the About location would drop the inherited CSP. The About template has no `<meta http-equiv>` CSP, unlike the other six pages, so the server header is its only CSP.\n- With `=` exact matches, `/about.html?x=1` still matches, because the query is not part of the location match. `/About` and `/about//` do not match and fall to `location /`, which answers 404.\n- The other routes' behaviour is unchanged.\n</impact>\n<impact path=\"DEPLOYMENT.md\" element=\"\u00a76 prose after the block, line 463 (the request-id / `proxy_set_header` / `log_format stays outside server {}` paragraph) and new prose next to it\">\n**What changes.**\n- The sentence \"`log_format` stays outside `server {}`\u2026\" becomes plural, because there are now two formats.\n- New prose sits beside the existing note on why `proxy_set_header` is repeated. It covers:\n  - why the About location lists both `access_log` lines (a location-level `access_log` replaces the inherited one);\n  - that the location inherits the CSP because it has no `add_header`, and that About has no meta CSP;\n  - that the `try_files` order mirrors vite's override-then-template order;\n  - to keep `last`;\n  - the new file `/var/log/nginx/peertube-browser.pages.access.log`, which falls under the Debian/Ubuntu `/var/log/nginx/*.log` logrotate rule, whose postrotate USR1 reopens it;\n  - that direct hits on `/dev-pages/about*.html` go through `location /` and leave no pages line;\n  - that existing hosts must re-apply \u00a76 and reload.\n\n**What depends on it.** The Triage runbook links here.\n\n**Risk of regression.** Low, since this is prose. The logrotate claim holds only for the distro package layout. State it as Debian/Ubuntu-specific, as the plan does.\n</impact>\n<impact path=\"DEPLOYMENT.md\" element=\"\u00a76 TLS subsection (lines 525-533, `sudo certbot --nginx`)\">\n**What changes.** No change in the plan, but one is needed. `certbot --nginx` edits the live `/etc/nginx/sites-available/peertube-browser` in place: it adds `listen 443 ssl`, the certificate paths and a redirect. The plan tells existing hosts to \"re-apply \u00a76 and reload\". An operator who copies the whole block over a certbot-edited file deletes the TLS config.\n\n**What depends on it.** Every host that followed the TLS section.\n\n**Risk of regression.** High for operators. The re-apply instruction should say to merge in only the new `log_format` line and the three locations, or to re-run `certbot --nginx` (or `certbot install`) afterwards. A full overwrite must not be the instruction.\n</impact>\n<impact path=\"DEPLOYMENT.md\" element=\"\u00a76 Verify (lines 475-481)\">\n**What changes.**\n- Add `curl -I http://localhost/about`: 200 with a `Content-Security-Policy` header. `/about/` and `/about.html` can be listed as well.\n- Add a `sudo tail -n 3 /var/log/nginx/peertube-browser.pages.access.log`.\n- Optionally add a hint that a 404 on `/about` means the build did not produce `dev-pages/about*.html`, or \u00a76 was not re-applied.\n\n**What depends on it.** Operators after an install or re-apply.\n\n**Risk of regression.** Low. `curl -I` sends HEAD, so it is logged as `method=HEAD`. The runbook's GET filter would exclude it, which is correct but worth knowing when someone checks that the tail shows \"a visit\".\n</impact>\n<impact path=\"DEPLOYMENT.md\" element=\"\u00a76 Engine listener paragraph, line 485 (\\\"leave the public site file above as it is, since nothing here changes it\\\")\">\n**What changes.** Nothing. I checked it against the plan: the plan touches only the public site file, not the 7079 listener, and this sentence still holds.\n\n**What depends on it.** Nothing new.\n\n**Risk of regression.** None. Listed only to confirm it was checked.\n</impact>\n<impact path=\"DEPLOYMENT.md\" element=\"\u00a73 Build the client, the `try_files` paragraph and page list (lines 299-303)\">\n**What changes.** The current text says every page is served through `try_files` and lists `about` among the pages. Add that About is built under `dist/dev-pages/` (`about.html` if the local override exists, else `about.template.html`) and is reached at `/about`, `/about/` and `/about.html` only through the \u00a76 mapping.\n\n**What depends on it.** The `scripts/sync.sh` workflow, and readers who add pages. The \"Adding another informational page\" story (one more location of the same shape) could be stated here or in \u00a76.\n\n**Risk of regression.** Low.\n</impact>\n<impact path=\"DEPLOYMENT.md\" element=\"Triage: \\\"Follow one request\\\" (lines 231-249) and the new \\\"Follow an About visit\\\" subsection inserted after line 249, before \\\"Centralized installer\\\" at line 251\">\n**What changes.** A new subsection with four steps:\n1. List visits from the pages log.\n2. `sudo grep \"request_id=$id\"` on the main log.\n3. Convert `ts=` with `date -u -d @<msec> +%Y-%m-%dT%H:%M:%S.%3NZ` and filter the Client journal with `jq` on `.event == \"request.start\" and .context.ip == $ip and .ts >= $from and .ts <= $to`. There is also a `LOG_FORMAT=text` variant.\n4. Hand off to \"Follow one request\".\n\nIt also carries the four caveats: no shared id; IP resolved through `TRUSTED_PROXIES`, with IPv6 and IPv4-mapped text forms; formats and time zones; bots filtered only by user agent, with issue 18's beacon as the upgrade path. \"What each log is for\" (242-244) gains a pages-log bullet.\n\n**Facts verified.** `client/backend/server.py:346-350`: `request.start` context is `{\"ip\", \"method\", \"url\", \"user_agent\"?}`. `_format_ts` (136-140) is a fixed-width UTC `YYYY-MM-DDTHH:MM:SS.mmmZ`, so comparing the strings orders correctly. JSON keys are `ts`, `event`, `context`, `request_id` (176-189). The existing jq idiom at line 237 is `jq -cR \u2026 'fromjson? | select(\u2026)'`.\n\n**What depends on it.** Operators. Issue 21's validation clause \"Correlation by request id/time window works against app traces\".\n\n**Risk of regression.**\n- **Text mode.** `_render_text` (150-163) writes context as unquoted `key=value`. A grep for `ip=$ip` without a trailing space also matches `ip=1.2.3.45` when looking for `1.2.3.4`, so the runbook must use `\"ip=$ip \"`. `user_agent` comes after `ip` in the text line and is unquoted, so a UA can forge an ` ip=\u2026 ` token. Text-mode matching is weaker than JSON, and the runbook should say so.\n- **Pages log.** `grep 'page=about'` without the `^` anchor can be forged through `ua`/`x_request_id`.\n- **Time window.** The window must account for clock skew only within one host, which is fine. A visitor who leaves About makes no API call, so they have no Client record. That is stated as a tradeoff.\n</impact>\n<impact path=\"DEPLOYMENT.md\" element=\"Triage table (lines 197-229)\">\n**What changes.** Optional. Add a row: `/about` (or `/about.html`) answers 404 \u2192 \u00a76 not re-applied, or no `dev-pages/about*.html` in the document root \u2192 re-apply \u00a76 / run `scripts/sync.sh`. Possibly another row: \"About visit has no pages-log line\" \u2192 the hit went to `/dev-pages/\u2026` directly, or the second `access_log` line is missing.\n\n**What depends on it.** Operators.\n\n**Risk of regression.** None. It is additive.\n</impact>\n<impact path=\"DEPLOYMENT.md\" element=\"\u00a72 `LOG_FORMAT` paragraph (line 116)\">\n**What changes.** Optional. A pointer to \"Follow an About visit\" next to the existing pointer to \"Follow one request\". It should note that the text-mode recipe in the new runbook is weaker, because values are unquoted, which this paragraph already says (\"values are not quoted, so it is for reading by eye\").\n\n**What depends on it.** Nothing.\n\n**Risk of regression.** None.\n</impact>\n<impact path=\"DEPLOYMENT.md\" element=\"\u00a77 Verify page list (lines 561-565)\">\n**What changes.** Optional: add `/about` to the list of pages to open.\n\n**What depends on it.** Nothing.\n\n**Risk of regression.** None.\n</impact>\n<impact path=\"client/frontend/README.md\" element=\"\\\"Local About Overrides\\\" (lines 36-39)\">\n**What changes.** Add one line: in prod, nginx serves whichever file was built (the `dev-pages/about.html` override first, then the template) at `/about`, `/about/` and `/about.html` (`DEPLOYMENT.md` \u00a76). Optionally also:\n- an override must use root-absolute URLs, because the same file is served at `/about/`, where relative URLs would resolve under `/about/`;\n- it gets only the server CSP header (`script-src 'self'`, no inline script).\n\n**What depends on it.** Developers writing the untracked override. `.gitignore:29-30` ignores `client/frontend/dev-pages/*` except the template, so the override is never in the repo and nothing checks it.\n\n**Risk of regression.** Low. It is documentation. The real risk it guards against is an override that uses relative links, which break at `/about/`.\n</impact>\n<impact path=\"client/frontend/vite.config.ts\" element=\"`aboutSourcePath`, `rewriteToAbout` (lines 13-22) and `build.rollupOptions.input.about` (lines 91-93)\">\n**What changes.** Nothing. This is the contract the nginx block copies:\n- the `existsSync(dev-pages/about.html)` override, otherwise `about.template.html`, emitted at `dist/dev-pages/<same name>`;\n- the rewrite set `/about`, `/about/`, `/about.html` (line 22), which is exactly the three nginx exact locations.\n\n**What depends on it.** The nginx `try_files` order and its paths.\n\n**Risk of regression.**\n- If someone later renames the input, moves it out of `dev-pages/` or adds a URL to `rewriteToAbout`, nginx drifts silently. Nothing tests the two against each other. The new test could assert that the three exact-location URLs equal the `rewriteToAbout` set and that the `try_files` paths match the two `dev-pages` names, which would close that drift.\n- Out of scope: the vite-only rewrites of `/videos` and `/search` (lines 20-21) have no prod nginx counterpart either. That is the same dev/prod gap class.\n</impact>\n<impact path=\"client/frontend/dev-pages/about.template.html\" element=\"the whole template\">\n**What changes.** Nothing. I checked it: every URL is root-absolute (`/favicon.png`, `/src/videos.css`, which becomes `/assets/videos-*.css` in `dist/dev-pages/about.template.html:8`, and the nav `/channels.html`, `/`, `/likes.html`, `/about.html`). It has no `<meta http-equiv>` CSP, unlike the six top-level pages, and no script.\n\n**What depends on it.** It is served at `/about/`, so relative URLs would break there. None exist.\n\n**Risk of regression.** None for the template. If a later edit adds a relative link or an inline script, the link breaks at `/about/` or the script is blocked by the header CSP.\n</impact>\n<impact path=\"client/frontend/index.html\" element=\"nav `href=\\\"/about.html\\\"` link (line 26); same link in videos.html:26, search.html:26, likes.html:26, channels.html:26, video-page.html:24\">\n**What changes.** Nothing in the files. These links 404 in prod today and resolve to 200 after the change, through `location = /about.html` with no rewrite. That is a user-visible fix.\n\n**What depends on it.** Every page's navigation.\n\n**Risk of regression.** None. It is noted because every About visit via nav arrives as `/about.html` and logs as `uri=\"/about.html\"`, so the runbook should not assume `/about`.\n</impact>\n<impact path=\"client/frontend/dist/dev-pages/about.template.html\" element=\"committed build output\">\n**What changes.** Nothing. It confirms the output layout: `dist/dev-pages/about.template.html` exists, and `dist/about.html` does not.\n\n**What depends on it.** The `try_files` second candidate.\n\n**Risk of regression.** None. The committed `dist/` lags the source (DEPLOYMENT.md line 412), but the about path layout is stable.\n</impact>\n<impact path=\"scripts/sync.sh\" element=\"build then `rsync -a --delete` to `/var/www/peertube-browser/`\">\n**What changes.** Nothing.\n\n**What depends on it.** `--delete` removes a stale `dev-pages/about.html` once the override is removed locally and rebuilt. That is what keeps the `try_files` preference correct, as the plan's \"stale dev-pages files\" gotcha says.\n\n**Risk of regression.** Low. A manual copy without `--delete` would leave a stale override, and nginx would keep preferring it over a newer template.\n</impact>\n<impact path=\"client/backend/server.py\" element=\"`_run_request` request.start context (lines 339-357), `_format_ts` (136-140), `_render_text` (150-163), `ClientLogFormatter.format` (174-195)\">\n**What changes.** Nothing; the runbook's step 3 depends on these.\n\n**What depends on it.** The runbook's jq filter (`.event`, `.context.ip`, `.ts`) and its string comparison of `ts`.\n\n**Risk of regression.**\n- If `ts` ever stops being fixed-width UTC with a `Z` suffix, or `ip` moves out of `context`, the runbook silently matches nothing. No test ties the runbook to these. The planned synthetic-record runbook test should build its Client record by calling the real `ClientLogFormatter`, not a hand-written JSON string, so that drift turns the test red.\n- The `rat-tail` comment at line 122 notes this module is mirrored in `engine/server/api/logging_profiles.py`. Step 4 of the runbook hands off to the Engine through \"Follow one request\", which relies on `request_id` only.\n</impact>\n<impact path=\"engine/install-engine-service.sh\" element=\"`nginx -t` gate (line 401-406)\">\n**What changes.** Nothing.\n\n**What depends on it.** It runs `nginx -t` over the whole host config, including the public site file.\n\n**Risk of regression.** An invalid About block, such as a missing `set` or a misspelled format name, makes the prod Engine install fail with \"nginx -t failed\".\n</impact>\n<impact path=\"scripts/deploy-bluegreen.sh\" element=\"`nginx -t` at line 317 and during rollback at line 148\">\n**What changes.** Nothing.\n\n**What depends on it.** Same as above.\n\n**Risk of regression.** A broken site file turns every deploy into `rollback phase=switching step=nginx_test`, and a broken restore into `rollback_failed \u2026 restore_nginx_test`. Triage row 225 already says `nginx -t` is \"often an unrelated broken config\", so no doc change is needed there.\n</impact>\n<impact path=\"engine/uninstall-engine-service.sh\" element=\"`nginx -t` at line 115\">\n**What changes.** Nothing.\n\n**What depends on it.** Same as above.\n\n**Risk of regression.** A broken site file makes the uninstaller fail after it removes the listener.\n</impact>\n<impact path=\"tests/active/test_static_page_visit_logs.py\" element=\"new test file (name to be chosen by the test step)\">\n**What changes.** A new test. It extracts the site block from `DEPLOYMENT.md`, rewrites `root`, the log paths and `listen` to temp-dir values, wraps the block in `http {}` and runs `nginx -t`. Where possible it also starts nginx on a free port and checks:\n- 200 on the three URLs and the CSP header;\n- exactly one line per log per request;\n- matching `request_id` values;\n- that `/` and `/api/\u2026` produce no pages line.\n\nA synthetic runbook check runs as well. The test is skipped when `shutil.which(\"nginx\")` is None.\n\n**What depends on it.** `.un/skills/devsecops/config.json` test_groups, which needs a new entry.\n\n**Risk of regression / pitfalls (verified against the doc).**\n- **Selecting the block.** `DEPLOYMENT.md` has two fenced `nginx` blocks: the site block (415-459) and the upstream snippet (488-492). The extraction must pick the one after the `/etc/nginx/sites-available/peertube-browser` caption, not the first or last ```` ```nginx ````.\n- **Running unprivileged.**\n  - nginx opens its compiled-in error log (`/var/log/nginx/error.log`) before it reads the config. Use `-e <tmp>/error.log` (nginx \u22651.19.5) or accept the alert.\n  - `nginx -t` and the start fail with `mkdir() \"/var/lib/nginx/body\" failed (13)` unless `client_body_temp_path`, `proxy_temp_path`, `fastcgi_temp_path`, `uwsgi_temp_path` and `scgi_temp_path` point into the temp dir.\n  - `pid` also needs a temp path, as does `-p <prefix>`.\n- **The wrapper.**\n  - Without `include mime.types` it serves `text/plain`, so do not assert `text/html` unless the wrapper includes it.\n  - The `proxy_pass http://127.0.0.1:7072` lines are fine for `-t`. `/api/\u2026` will answer 502 with nothing listening, which is still enough to assert \"no pages line\".\n- **Log timing.** nginx writes the access-log line after it sends the response, so the test must poll the log files before counting lines.\n- **Rewrites.** The rewrites of `/var/log/nginx/\u2026` must cover both `access_log` lines inside the About location, not just the server-level one, or nginx tries to open `/var/log/nginx/\u2026` and fails as non-root.\n- **Bound to the doc text.** The test reads a doc's content, so a reflow of the doc or a quoting style change can break the extraction. Match on directive tokens, as `_statements()` in `tests/active/test_install_engine_service.py:141-145` does, not on whole lines.\n</impact>\n<impact path=\".un/skills/devsecops/config.json\" element=\"`test_groups` (lines 14-263)\">\n**What changes.** Add a group for the new test that maps `DEPLOYMENT.md`, and possibly `client/frontend/vite.config.ts` if the test asserts the URL set and `dev-pages` names. Non-code paths are already allowed: `tests/active/host_tokens.json` and `upstream_snippet_cases.json` are listed.\n\n**What depends on it.** The runner selects groups from the changed files. Today no group maps `DEPLOYMENT.md`, so without this entry a doc-only change selects no test, and the new test never runs in the build's suite.\n\n**Risk of regression.** Medium. Leaving it out silently skips the only validation of this build.\n</impact>\n<impact path=\"tests/active/test_install_engine_service.py\" element=\"`_statements()` helper (lines 141-145)\">\n**What changes.** Nothing. It is the existing idiom for parsing nginx text into directives with comments stripped.\n\n**What depends on it.** The new test may copy it. Test modules do not import from one another, so copying matches the repo's style.\n\n**Risk of regression.** None.\n</impact>\n<impact path=\"docs/project/issues/21-static-page-visit-logs.md\" element=\"`Status:` line and `## Comments`\">\n**What changes.** At completion:\n- `Status: enhancement, complete`;\n- a delivery comment naming `docs/project/plans/22-21-static-page-visit-logs.md`, in the same shape as the archived issue 19/20 comments;\n- a move to `docs/project/issues/archive/`, as `docs/project/issue-tracker.md:21` requires.\n\nThe plan says only \"status at completion\", but the move is mandatory.\n\n**What depends on it.** `docs/project/issues/plan.md` and the issue numbering, which counts `archive/`.\n\n**Risk of regression.** Low. The issue-20 build left a duplicate in `issues/` because its agent had no delete tool (record step 9). The same could happen here.\n</impact>\n<impact path=\"docs/project/issues/plan.md\" element=\"P5 row (line 42) and wave lane 5c (line 98)\">\n**What changes.**\n- Lane 5c's \"Main files\" says \"nginx docs, the About template, one Client endpoint\". For 21, that is the nginx docs only; the template and the endpoint belong to 18. Mark 21 delivered there.\n- Line 42 still says \"19 and part of 20 are already delivered\". That is stale on this branch, and it could be updated to say 19, 20 and 21 are delivered.\n\n**What depends on it.** Planning.\n\n**Risk of regression.** None.\n</impact>\n<impact path=\"docs/project/roadmap.md\" element=\"`## Delivered` list (lines 7-25) and Logging chain line 157\">\n**What changes.** Optional: a Delivered bullet for issue 21 pointing to the plan. Line 157 (`19` -> `20` -> `21`) needs no change. The convention is applied unevenly: issues 19 and 20 have no Delivered bullet.\n\n**What depends on it.** Nothing.\n\n**Risk of regression.** None. Uncertain whether a bullet is expected.\n</impact>\n<impact path=\"docs/project/issues/18-about-outbound-click-tracking.md\" element=\"`## Comments`\">\n**What changes.** Optional comment. Issue 21's runbook names 18's beacon endpoint as the pageview upgrade path. Line 14 plans `/api/analytics/outbound-click`, a click-specific endpoint, so a pageview would need 18's endpoint design to allow a page-view event type. There is no duplication, because 21 adds no endpoint.\n\n**What depends on it.** The future design of 18.\n\n**Risk of regression.** None. It is a naming-only forward reference: if 18 lands with a click-only schema, the runbook's \"upgrade path\" statement becomes inaccurate.\n</impact>\n<impact path=\"CONTEXT.md\" element=\"glossary, \\\"Request id\\\" (line 10)\">\n**What changes.** Nothing required. The entry is still true: About lines carry nginx's `$request_id`, but no app record shares it, and the runbook says so. An optional glossary term (\"pages log\" / \"informational static page\") could be added. I consider it unnecessary because the plan scopes it to About only.\n\n**What depends on it.** Nothing.\n\n**Risk of regression.** None.\n</impact>\n<impact path=\"client/README.md\" element=\"line 75 (request.start / \\\"byte counts are in the nginx access log\\\") and line 69 (`TRUSTED_PROXIES`)\">\n**What changes.** Nothing. It is the source of the runbook's statement that the Client's `ip` is resolved through `TRUSTED_PROXIES`. It points to \"Follow one request\", and a pointer to \"Follow an About visit\" could optionally be added.\n\n**What depends on it.** Nothing.\n\n**Risk of regression.** None.\n</impact>\n<impact path=\"engine/server/README.md\" element=\"line 32 (request.start/end and the pointer to DEPLOYMENT.md Triage)\">\n**What changes.** Nothing. It is checked because step 4 of the runbook reaches the Engine through the same `request_id` flow.\n\n**What depends on it.** Nothing.\n\n**Risk of regression.** None.\n</impact>\n<impact path=\"docs/project/plans/22-21-static-page-visit-logs.md\" element=\"the plan file\">\n**What changes.** Nothing by hand. Its header (line 3) says the dev-flow workflow renders it, and every edit is overwritten.\n\n**What depends on it.** It is named in the issue 21 delivery comment.\n\n**Risk of regression.** None.\n</impact>\n</impacts>\n</impacts>\n\n<docs_checklist>\n<doc path=\"DEPLOYMENT.md\">\n- **\u00a76 site block:**\n  - Add `log_format peertube_browser_pages` under line 416, with the client-controlled `ua`/`x_request_id` (and ideally `uri`) last.\n  - Add `location = /about.html` with `set $static_page about;`, `try_files /dev-pages/about.html /dev-pages/about.template.html =404;`, both `access_log` lines and no `add_header`.\n  - Add the `= /about` / `= /about/` aliases with `rewrite ^ /about.html last;`, placed after `location /`.\n- **\u00a76 prose at line 463:**\n  - Make the `log_format` sentence plural.\n  - Explain why both `access_log` lines are needed and that the CSP is inherited (About has no meta CSP).\n  - Note that the `try_files` order mirrors vite, and to keep `last`.\n  - Name the new log file and its Debian/Ubuntu logrotate coverage.\n  - Say that direct `/dev-pages/\u2026` hits are not in the pages log.\n  - Tell existing hosts to merge the additions rather than overwrite a certbot-edited file, or to re-run certbot.\n- **\u00a76 TLS (525-533):** warn that re-applying \u00a76 by overwriting the site file drops certbot's edits.\n- **\u00a76 Verify (475-481):** add `curl -I http://localhost/about` (200 + CSP), a pages-log `tail`, and a 404 hint.\n- **\u00a73 (299-303):** About is built under `dist/dev-pages/` and reached at `/about`, `/about/`, `/about.html` via \u00a76.\n- **Triage:**\n  - Add the \"Follow an About visit\" subsection after line 249: the anchored `^page=about ` listing with positional awk, the main-log `request_id` grep, the `date -u` conversion with the JSON jq filter and the text variant using `\"ip=$ip \"`, and the hand-off to \"Follow one request\".\n  - Include the four caveats, plus the forgeable-token note.\n  - Add a pages-log bullet to \"What each log is for\".\n- **Optional:**\n  - a Triage table row for an `/about` 404;\n  - a pointer from the \u00a72 `LOG_FORMAT` paragraph (line 116);\n  - `/about` in the \u00a77 page list.\n</doc>\n<doc path=\"client/frontend/README.md\">\n\"Local About Overrides\" (lines 36-39): add that prod nginx serves whichever file was built (the override first, then the template) at `/about`, `/about/` and `/about.html` (`DEPLOYMENT.md` \u00a76). Optionally add that an override must use root-absolute URLs, because it is also served at `/about/`, and that it gets only the server CSP header.\n</doc>\n<doc path=\"docs/project/issues/21-static-page-visit-logs.md\">\nAt completion: `Status: enhancement, complete`, a delivery comment naming `docs/project/plans/22-21-static-page-visit-logs.md` and what was delivered, and a move to `docs/project/issues/archive/` per `docs/project/issue-tracker.md:21`.\n</doc>\n<doc path=\"docs/project/issues/plan.md\">\n- Lane 5c (line 98): mark 21 delivered and correct its file list for 21 to the nginx docs only.\n- P5 row (line 42): update the stale \"19 and part of 20\" wording.\n</doc>\n<doc path=\"docs/project/roadmap.md\">\nOptional Delivered bullet for issue 21. The convention is inconsistent: 19 and 20 have none.\n</doc>\n<doc path=\"docs/project/issues/18-about-outbound-click-tracking.md\">\nOptional comment: issue 21's runbook names 18's beacon endpoint as the pageview upgrade path, so 18's endpoint design may need a page-view event type besides outbound clicks.\n</doc>\n</docs_checklist>\n\n<highest_risk>\nDEPLOYMENT.md \u00a76 site block (About location): a location-level `access_log` replaces the inherited one, an `add_header` would drop the only CSP About has, `last` must stay, and the `set $static_page` must exist or `nginx -t` fails host-wide. A failing `nginx -t` blocks `scripts/deploy-bluegreen.sh` and `engine/install-engine-service.sh` too.\nDEPLOYMENT.md \u00a76 re-apply instruction against the TLS section: `certbot --nginx` edits the live site file, so telling existing hosts to \"re-apply \u00a76\" by copying the block over it deletes TLS on any host that followed the docs.\nDEPLOYMENT.md pages `log_format` field order and Triage runbook filters: nginx does not escape spaces, so the client-controlled `ua`, `x_request_id` (and `uri`) can forge ` status=200 ` / ` method=GET ` / `page=about` / `ip=` tokens. Unanchored greps, and text-mode `ip=$ip` without a trailing space, give spoofed or wrong matches unless the client-controlled fields come last and the runbook anchors and filters by field position.\n</highest_risk>",
    "step_4_reassess": "<summary>\nThe plan holds up against the inventory and the tree. I opened the files the impacts name and they match: `DEPLOYMENT.md` \u00a76, \u00a73, Triage, Verify, TLS and \u00a77 at the line numbers given; `vite.config.ts:13-22,91-93`; `server.py:136-195,339-357`; the three `nginx -t` gates; `config.json` test_groups, where no group maps `DEPLOYMENT.md`; the nav links on the six pages; the CSP meta tags missing from the template; the committed `dist/dev-pages/about.template.html`; issue 21's status; and `plan.md:42,98`. I found no impact the inventory misses. One inventory detail about nginx behaviour is slightly wrong (see unconfirmed), and it does not change the plan.\n<question id=\"1\">Yes. Exact-match locations win over `location /`. `rewrite \u2026 last` keeps one request, so there is one `$request_id`, one log phase, one line per log, and `$request_uri` is still the URL the visitor asked for. `try_files` serves the file in the same order vite builds it. The server-level CSP with `always` is inherited because the About location has no `add_header`. The `$static_page` variable is declared by the `set`, so `nginx -t` passes. The vite rewrite set (`vite.config.ts:22`) is exactly the three URLs. The template uses only root-absolute URLs, so serving it at `/about/` breaks nothing. Correlation will work, within the limits the plan already accepts: IP plus time window, and nothing to match when the visitor makes no further API call.</question>\n<question id=\"2\">1. The nav link `/about.html` on all six pages answers 404 in prod today and becomes 200. This is a visible fix for users. 2. A new log file appears under `/var/log/nginx/`. 3. A syntax mistake in the site file now breaks more than the site: the Engine installer, uninstaller and blue/green deploy all run `nginx -t` over the whole config, so a bad edit turns a deploy into a rollback. 4. Hosts change only when an operator re-applies \u00a76, and a full overwrite of the file erases what `certbot --nginx` added (the TLS impact). 5. Two client-controlled fields (`ua`, `x_request_id`) go into a space-separated log line, so field order and anchored greps matter (the field-order impact).</question>\n<question id=\"3\">Everything needed is already in the inventory: 1. The About location must repeat the main `access_log` line, or About drops out of the main log. 2. The rewrite must keep `last`. 3. The About location must have no `add_header`, or it loses the CSP. 4. The re-apply instruction must say \"merge these blocks\" or \"re-run certbot\", not \"overwrite\". 5. `config.json` needs a test group that maps `DEPLOYMENT.md` (and `vite.config.ts`), or the new test never runs. 6. Issue 21 must move to `archive/`, as `issue-tracker.md:21` requires. Nothing in app code or the build has to change.</question>\n<question id=\"4\">1. `/about`, `/about/` and `/about.html` change from 404 to 200 in prod. 2. About requests get a second log line, in the new pages log. Their main-log lines are unchanged in format. 3. Every other route is unchanged: same locations, same logs, same headers. 4. A direct hit on `/dev-pages/about*.html` behaves as before: it is served through `location /` and leaves no pages line.</question>\n</summary>\n\n<new_impacts>\nnone\n</new_impacts>\n\n<unconfirmed>\nThe inventory entry for the DEPLOYMENT.md \u00a76 locations (\"Risk of regression\") says `/about//` does not match the exact locations and falls to `location /` with a 404. That is not quite right. nginx's `merge_slashes` defaults to on, and location matching uses the normalised URI, so `/about//` is matched as `/about/`. It hits `location = /about/`, answers 200 and writes a pages line, and the line's `uri=` field still shows `/about//`. `/About` does stay a 404, because location matching is case-sensitive. This has no effect on the plan. It only matters if the test or the runbook asserts that `/about//` is a 404.\n</unconfirmed>\n\n<new_conflicts>\nnone\n</new_conflicts>\n\n<recommendations>\n1. Fix the pages-log field order and make the runbook filters anchored. Put `status`, `rt`, `request_id` and `uri` before the client-controlled `x_request_id` and `ua`. In the runbook, anchor on `^page=about ` and filter by field position with awk, not with unanchored `grep ' status=200 '`. Cost: a few words in the format line and the runbook. It stays inside the plan's \"roughly this order\".\n2. Change \u00a76's re-apply instruction from \"re-apply \u00a76\" to \"add the second `log_format` line and the three About locations to your existing site file, then `nginx -t && reload`\". Add a line saying that overwriting the whole file removes what `certbot --nginx` added, and that you then have to run `certbot --nginx` again. Cost: about two sentences. It prevents TLS from being silently removed on existing hosts.\n3. Add a `test_groups` entry in `.un/skills/devsecops/config.json` for the new test, mapping `DEPLOYMENT.md` and `client/frontend/vite.config.ts`. Have the test also check that the three exact-location URLs match vite's `rewriteToAbout` set and that the `try_files` paths match the two `dev-pages` names. Cost: one config entry and about 15 test lines. Without the entry, this build's only validation never runs.\n4. Build the runbook test's Client record with the real `ClientLogFormatter` rather than a hand-written JSON string. Cost: one import. If `ts` or `context.ip` ever changes, the test goes red instead of the runbook silently matching nothing.\n5. In the text-mode recipe, grep for `\"ip=$ip \"` with the trailing space, and say that text mode can be spoofed through the unquoted `user_agent`. Cost: one sentence.\n6. Make the test's nginx wrapper tolerate nginx older than 1.19.5, which has no `-e` flag (for example Ubuntu 20.04's 1.18): skip, or accept the error-log alert. Point all five `*_temp_path` directives and `pid` into the temp dir. Cost: wrapper lines in the test. Without this the test fails, rather than skips, on hosts with an older nginx.\n7. At completion, move issue 21 to `docs/project/issues/archive/`, update `plan.md` lines 42 and 98, and optionally comment on issue 18 that a pageview beacon would need its endpoint to accept a page-view event, since it is click-only as planned. Cost: doc edits only. The archive move is mandatory, and last time the agent had no delete tool, so it has to be checked by hand.\n8. Optional extras: a Triage row for \"`/about` answers 404\", `/about` in the \u00a77 page list, and the `client/frontend/README.md` line telling override authors to keep URLs root-absolute. Cost: one line each.\n</recommendations>",
    "step_5_draft_implementation": "<draft>\n## Draft: issue 21, About visit log (documentation build)\n\nNote on the brief: the ladder heading arrived with an unrendered `{rat_tail_ladder}` placeholder. I followed the two numbered ladder steps printed under it. The one deliberate mirror in this build (nginx copying vite's About mapping) is marked with the repo's existing `rat-tail:` comment convention, the same one used at `client/backend/server.py:122`.\n\n### Module map\n\n| File | Change |\n|---|---|\n| `DEPLOYMENT.md` \u00a76 site block | Second `log_format`, three exact About locations |\n| `DEPLOYMENT.md` \u00a76 prose / Verify / TLS | About mapping prose, re-apply-without-overwrite rule, verify lines, certbot warning |\n| `DEPLOYMENT.md` \u00a73 | About's build location and URLs |\n| `DEPLOYMENT.md` Triage | Two table rows, new \"Follow an About visit\" subsection, pages-log bullet |\n| `DEPLOYMENT.md` \u00a72, \u00a77 | One pointer sentence, one page-list bullet |\n| `client/frontend/README.md` | \"Local About Overrides\" gains the prod mapping and two constraints |\n| `tests/active/test_static_page_visit_logs.py` | New (written by the test step; contract below) |\n| `.un/skills/devsecops/config.json` | New `test_groups` entry |\n| `docs/project/issues/21-\u2026` | At completion: status, comment, move to `archive/` |\n| `docs/project/issues/plan.md` | P5 row and lane 5c |\n| `docs/project/issues/18-\u2026` | One forward-reference comment |\n| `docs/project/roadmap.md` | **Not changed.** Issues 19 and 20 have no Delivered bullet, and adding one only for 21 would make the list less consistent, not more. |\n\nNo app, frontend source or build file changes.\n\n---\n\n### 1. `DEPLOYMENT.md` \u00a76: the site block (replaces lines 415\u2013459)\n\n````\n```nginx\nlog_format peertube_browser '$remote_addr - $remote_user [$time_local] \"$request\" $status $body_bytes_sent \"$http_referer\" \"$http_user_agent\" request_id=$request_id upstream=$upstream_addr rt=$request_time';\nlog_format peertube_browser_pages 'page=$static_page ts=$msec time=$time_iso8601 ip=$remote_addr method=$request_method status=$status rt=$request_time request_id=$request_id uri=\"$request_uri\" x_request_id=$http_x_request_id ua=\"$http_user_agent\"';\n\nserver {\n    listen 80;\n    server_name _;\n\n    root /var/www/peertube-browser;\n    index index.html;\n    access_log /var/log/nginx/peertube-browser.access.log peertube_browser;\n\n    add_header Content-Security-Policy \"default-src 'self'; script-src 'self'; object-src 'none'; base-uri 'self'; frame-src https:; connect-src 'self' https:; img-src 'self' https: data:\" always;\n\n    location / {\n        try_files $uri $uri/ =404;\n    }\n\n    # rat-tail: these three URLs and the two dev-pages names mirror rewriteToAbout and aboutSourcePath in client/frontend/vite.config.ts; tests/active/test_static_page_visit_logs.py compares them, and building About to dist/about.html is the upgrade if the mapping grows.\n    location = /about.html {\n        set $static_page about;\n        try_files /dev-pages/about.html /dev-pages/about.template.html =404;\n        access_log /var/log/nginx/peertube-browser.access.log peertube_browser;\n        access_log /var/log/nginx/peertube-browser.pages.access.log peertube_browser_pages;\n    }\n    location = /about {\n        rewrite ^ /about.html last;\n    }\n    location = /about/ {\n        rewrite ^ /about.html last;\n    }\n\n    location /api/ {\n        \u2026 unchanged \u2026\n    }\n    \u2026 /recommendations, /videos/similar, /client/ unchanged \u2026\n}\n```\n````\n\n**Invariants**\n\n- **Field order.** The first eight space-separated fields are fixed-format, and clients cannot inject spaces into them:\n\n  | Position | Field |\n  |---|---|\n  | 1 | `page=` |\n  | 2 | `ts=` |\n  | 3 | `time=` |\n  | 4 | `ip=` |\n  | 5 | `method=` |\n  | 6 | `status=` |\n  | 7 | `rt=` |\n  | 8 | `request_id=` |\n\n  Every client-controlled field (`uri`, `x_request_id`, `ua`) comes after them. The runbook filters by `awk` field position, never with an unanchored grep. The plan said the order was only \"roughly\" fixed; I moved `uri` after `status`/`rt`, as the impact inventory recommends.\n- **`x_request_id` stays unquoted.** nginx then writes a bare `-` when the header is absent, which is the format the requirement asks for.\n- **No `add_header` in the About location.** That is how it inherits the server's CSP, `always` included, so the 404 carries it too.\n- **The rewrites use `last`.** That keeps one request: one `$request_id`, one log phase, ending in `= /about.html`.\n- **`$static_page` is declared once, by the `set`.** Removing the `set` makes `nginx -t` fail with `unknown \"static_page\" variable`.\n- **`try_files` order matches vite's:** the override first, then the template.\n\n### 2. `DEPLOYMENT.md` \u00a76: prose after the block\n\n**Line 463, last sentence, made plural:** \"`log_format` stays outside `server {}`: the file is included in nginx's `http` block, the only place `log_format` is allowed, so both formats sit above the `server` block.\"\n\n**New paragraph after line 463** (one line in the file):\n\n> `/about`, `/about/` and `/about.html` are served by the three exact locations. The build emits About only as `dev-pages/about.html` (a local override) or `dev-pages/about.template.html` (`client/frontend/README.md`), never as `about.html`, so without them every page's About link is a 404. `location = /about.html` serves the override if the document root has one, otherwise the template, otherwise 404, in the same order as the build. The other two locations hand the request to it with `rewrite \u2026 last`. Keep `last`: it continues the same request, so a visit to `/about` is one request with one `$request_id`, logged once. `break` would serve from the rewriting location, which has no `try_files` and no pages log. `redirect` and `permanent` send the browser a second request. The About location writes both `access_log` lines because a location that declares any `access_log` inherits none from the server level. Dropping the first line silently removes About from `peertube-browser.access.log`. The location declares no `add_header`, so it inherits the server's `Content-Security-Policy`. About has no `<meta>` CSP of its own, so that header is its only CSP, and any `add_header` added there must repeat it. The second line writes `/var/log/nginx/peertube-browser.pages.access.log` in the `peertube_browser_pages` format, one line per About request of any method and status (see \"Follow an About visit\" under Triage). On Debian and Ubuntu, the nginx package's logrotate rule for `/var/log/nginx/*.log` rotates it, and its postrotate signal reopens it with the other logs. Elsewhere, add it to your rotation. Requests made directly to `/dev-pages/about*.html` go through `location /` and write no pages line. Nothing links there. To log another informational page, add one more exact location of the same shape, with its own `set $static_page <name>;`, its `try_files` and the same two `access_log` lines.\n\n**New paragraph after it:**\n\n> On a host that already runs this site, add the `peertube_browser_pages` line and the three About locations to the live `/etc/nginx/sites-available/peertube-browser` by hand, inside the `server` block that has `root /var/www/peertube-browser`. Then run `sudo nginx -t && sudo systemctl reload nginx`. Do not copy the whole block over the file: `sudo certbot --nginx` (see \"TLS\") edits it in place, and overwriting it removes the HTTPS listener and the redirect. If it was overwritten, run `sudo certbot --nginx` again. A broken site file fails `nginx -t` for the whole host, which also stops a prod Engine install and rolls back a deploy (Triage).\n\n### 3. `DEPLOYMENT.md` \u00a76 Verify (replaces lines 475\u2013481)\n\n````\nVerify:\n```bash\ncurl -I http://localhost/                 # 200, text/html\ncurl -s http://localhost/api/health       # client-backend JSON, publish_mode=bridge\ncurl -I http://localhost/about            # 200, text/html, Content-Security-Policy header; /about/ and /about.html the same\nsudo tail -n 3 /var/log/nginx/peertube-browser.pages.access.log    # one page=about line per request above, method=HEAD for curl -I\n```\nA 404 on `/` with a successful `nginx -t` means the document root is unreadable by\n`www-data`; check with `sudo -u www-data stat /var/www/peertube-browser/index.html`.\nA 404 on `/about` while `/` answers 200 means the About locations are missing from the live site file, or the document root holds neither `dev-pages/about.html` nor `dev-pages/about.template.html` (`ls /var/www/peertube-browser/dev-pages/`; rebuild and sync, section 3).\n````\n\nThe existing two-line hard wrap on the first 404 sentence is kept as it is. The new sentence is one line.\n\n### 4. `DEPLOYMENT.md` \u00a76 TLS (after line 533)\n\n> `certbot --nginx` edits `/etc/nginx/sites-available/peertube-browser` in place. When this guide later changes that file, merge the change into it rather than copying the block over it (section 6), or run `sudo certbot --nginx` again afterwards.\n\n### 5. `DEPLOYMENT.md` \u00a73 (replaces lines 299\u2013303, as one line)\n\n> Every page is a separate build input, so adding one means rebuilding and re-copying: nginx serves `dist/` through `try_files`, and a page missing from the document root is a 404 rather than a fallback. After adding or changing a page, re-run this build and repeat the `rsync` in section 6. The current pages are `index`, `videos`, `search`, `likes`, `video-page`, `channels` and `about`. About is the exception to the one-file-per-URL layout: it is built as `dist/dev-pages/about.html` when the local override exists, otherwise as `dist/dev-pages/about.template.html` (`client/frontend/README.md`), and is reached at `/about`, `/about/` and `/about.html` only through the About locations in section 6.\n\nI rewrote the paragraph as one line, following the no-softwrap rule. Most recent paragraphs in this file are already single lines.\n\n### 6. `DEPLOYMENT.md` Triage table: two rows appended after line 229\n\n```\n| `/about`, `/about/` or `/about.html` answers 404 while `/` answers 200 | The live site file lacks the About locations, or the document root has no `dev-pages/about*.html` | Merge the About locations into the site file (section 6), or rebuild and sync (section 3) |\n| An About visit has no line in `peertube-browser.pages.access.log`, or none in `peertube-browser.access.log` | The request went to `/dev-pages/about*.html` directly, or one of the About location's two `access_log` lines is missing | Section 6; the location must list both logs |\n```\n\n### 7. `DEPLOYMENT.md` Triage: \"What each log is for\", new bullet after line 244\n\n> - The pages log, `/var/log/nginx/peertube-browser.pages.access.log`, records About visits only: one `page=about` line per request, beside its usual line in the access log. About makes no API call, so this is the only record of a visit (see \"Follow an About visit\").\n\n### 8. `DEPLOYMENT.md` Triage: new subsection after line 249, before \"Centralized installer\"\n\n````\n### Follow an About visit\n\nAbout is static and makes no API call, so a visit leaves no app record. nginx writes it to `/var/log/nginx/peertube-browser.pages.access.log` (section 6) as one line per request:\n```\npage=about ts=1700000000.123 time=2023-11-14T22:13:20+00:00 ip=203.0.113.7 method=GET status=200 rt=0.000 request_id=3f2a\u2026 uri=\"/about.html\" x_request_id=- ua=\"Mozilla/5.0 \u2026\"\n```\n`ts` is the epoch in seconds with milliseconds, which is UTC. `time` is the server's local time, to the second. `x_request_id` is the `X-Request-ID` the request arrived with, or `-`. The first eight fields have a fixed form. `uri`, `x_request_id` and `ua` come from the client and can contain spaces and look-alike tokens, so match by field position, as below, not with a plain `grep`.\n\nList visits, optionally only successful page loads:\n```bash\nsudo awk '$1 == \"page=about\"' /var/log/nginx/peertube-browser.pages.access.log\nsudo awk '$1 == \"page=about\" && $5 == \"method=GET\" && $6 == \"status=200\"' /var/log/nginx/peertube-browser.pages.access.log\n```\nNav links arrive as `uri=\"/about.html\"`; `/about` and `/about/` are typed or shared URLs.\n\nFind the same visit's access-log line by its id:\n```bash\nid=<request_id of the visit>\nsudo grep \"request_id=$id\" /var/log/nginx/peertube-browser.access.log\n```\n\nFind the visitor's later API requests in the Client backend by client address and a time window after the visit (5 minutes here; widen `window` by hand):\n```bash\nline=$(sudo awk -v id=\"request_id=$id\" '$1 == \"page=about\" && $8 == id' /var/log/nginx/peertube-browser.pages.access.log)\nip=$(printf '%s\\n' \"$line\" | awk '{ sub(/^ip=/, \"\", $4); print $4 }')\nmsec=$(printf '%s\\n' \"$line\" | awk '{ sub(/^ts=/, \"\", $2); print $2 }')\nwindow=300\nfrom=$(date -u -d \"@$msec\" +%Y-%m-%dT%H:%M:%S.%3NZ)\nto=$(date -u -d \"@$(( ${msec%.*} + window )).${msec#*.}\" +%Y-%m-%dT%H:%M:%S.%3NZ)\njournalctl -u peertube-client.service -o cat | jq -cR --arg ip \"$ip\" --arg from \"$from\" --arg to \"$to\" 'fromjson? | select(.event == \"request.start\" and .context.ip == $ip and .ts >= $from and .ts <= $to)'\n```\nThe apps' `ts` is fixed-width UTC (section 2), so comparing it as a string orders it correctly. With `LOG_FORMAT=text`:\n```bash\njournalctl -u peertube-client.service -o cat | awk -v from=\"$from\" -v to=\"$to\" '$3 == \"request.start\" && $1 >= from && $1 <= to' | grep -F \" ip=$ip \"\n```\nKeep the spaces around `ip=$ip`, or `1.2.3.4` also matches `1.2.3.45`. Take `request_id` from a matching record and continue with \"Follow one request\" to reach the Engine.\n\nCaveats:\n- A visit shares no id with the visitor's API requests. About makes none, and nginx gives every request its own `$request_id`, so the match is by address and time only and is probabilistic. Visitors behind one NAT or shared address match each other's requests, and a visitor who leaves without opening another page has no Client record at all.\n- The Client's `ip` is the address it resolves through `X-Forwarded-For` and `TRUSTED_PROXIES` (section 6), and it equals nginx's `ip` only when nginx is the only proxy. Behind a CDN or load balancer, nginx's `ip` is that layer's address and the Client's is the visitor's, so the two do not match. IPv6 and IPv4-mapped addresses (`::ffff:1.2.3.4`) can also be written differently in the two logs.\n- nginx's `ts` is epoch seconds and `time` is local time. The apps' `ts` is UTC `YYYY-MM-DDTHH:MM:SS.mmmZ`. Convert with `date -u` as above before comparing, never `time`.\n- Bots and crawlers are logged like visitors. The `ua` field is the only filter, and a client can put anything in it. In text mode, `user_agent` follows `ip` unquoted, so a user agent can also forge an ` ip=\u2026 ` token. JSON mode does not have this weakness. A client-side pageview beacon on the endpoint that `docs/project/issues/18-about-outbound-click-tracking.md` introduces would count human visits more cleanly. That is the upgrade path, not a second endpoint.\n````\n\n**Checked against the code.** `_render_text` writes `ts LEVEL event message k=v\u2026`. `$3` is the event, and the message \"request started\" comes after it, so `$1` and `$3` are positional before any free text. Context order is `ip`, `method`, `url`, `user_agent` (`server.py:346-349`), so `ip=` is always followed by ` method=` and the trailing space is reliable. `$msec` always has a 3-digit fraction, so `${msec%.*}` and `${msec#*.}` split it safely, and `@<int>.<frac>` is GNU `date` syntax.\n\n### 9. `DEPLOYMENT.md` \u00a72 (line 116)\n\nThe pointer sentence at the end of the paragraph becomes: \"To read every line of one request across nginx, the Client backend and the Engine, see \"Follow one request\" under Triage; to tie an About visit, which has no app record, to the visitor's later requests, see \"Follow an About visit\".\"\n\n### 10. `DEPLOYMENT.md` \u00a77 (after line 564)\n\nNew bullet: `- `/about` (About; `/about/` and `/about.html` serve the same page)`.\n\n### 11. `client/frontend/README.md` \"Local About Overrides\" (lines 36\u201339)\n\nThe existing three bullets stay. Two new bullets are appended:\n\n```\n- The build emits whichever source it used under `dist/dev-pages/` with the same name. In production nginx serves the override if present, otherwise the template, at `/about`, `/about/` and `/about.html` (`DEPLOYMENT.md` section 6), and logs each visit to its pages log.\n- Because the same file is served at `/about/`, an override must use root-absolute URLs (`/favicon.png`, `/src/\u2026`, `/about.html`); relative ones resolve under `/about/` there. It gets only nginx's `Content-Security-Policy` header (`script-src 'self'`), so inline scripts are blocked.\n```\n\n### 12. Test contract: `tests/active/test_static_page_visit_logs.py`\n\nThe test step writes this file; the contract is fixed here.\n\n**Helpers**\n- `_site_block()` takes the first fenced ```` ```nginx ```` block after the line containing `` `/etc/nginx/sites-available/peertube-browser`: ``. That is the right block, not the upstream snippet.\n- `_statements()` is copied from `test_install_engine_service.py:141-145`.\n- `_runbook()` takes the fenced `bash` blocks under `### Follow an About visit`.\n\n**Wrapper config.** It is written to `tmp/nginx.conf` and run with `nginx -p tmp -e tmp/error.log -c tmp/nginx.conf`:\n- `pid`, `events {}`;\n- `http { client_body_temp_path`, `proxy_temp_path`, `fastcgi_temp_path`, `uwsgi_temp_path`, `scgi_temp_path` under tmp;\n- `include <the block> }`.\n\n**Substitutions** are made on directive tokens, not lines:\n- `root` \u2192 `tmp/www`;\n- every `/var/log/nginx/` (the server-level line and both About lines) \u2192 `tmp/log/`;\n- `listen 80` \u2192 `listen 127.0.0.1:<free port>`.\n\n**Skip rules.** Tests that need nginx are skipped when `shutil.which(\"nginx\") is None`. jq tests are skipped without `jq`. The live-server tests are also skipped if nginx refuses to start unprivileged.\n\n| Test | Asserts |\n|---|---|\n| `test_site_block_passes_nginx_t` | `nginx -t` exits 0 on the wrapped block |\n| `test_about_urls_serve_page_with_csp` (param `/about`, `/about/`, `/about.html`, `/about.html?x=1`; GET and HEAD) | 200, the template's bytes for GET, a `Content-Security-Policy` header equal to the block's value |\n| `test_override_preferred_and_404_without_files` | With both files, the override is served. With neither, 404 with CSP, and still one pages line with `status=404` |\n| `test_each_about_request_logs_once_per_file` | After polling, exactly one new pages line and one new main line per request. Fields 1\u20138 are `page=about`, `ts=<d+.ddd>`, `time=`, `ip=127.0.0.1`, `method=`, `status=`, `rt=`, `request_id=<32 hex>`. `uri=` is the requested path plus query. The main line carries the same `request_id`. `x_request_id=-` without the header, and the sent value with it |\n| `test_forged_user_agent_does_not_move_fields` | A UA ` status=200 method=GET page=about` on a 404 request leaves `$6 == status=404`, and the runbook's awk filter excludes it |\n| `test_other_routes_write_no_pages_line` (`/`, `/index.html`, `/api/health` \u2192 502, `/dev-pages/about.template.html`) | No new pages line; each still writes one main line |\n| `test_about_mapping_matches_vite` (no nginx needed) | The exact-location URLs equal the string set in `rewriteToAbout` in `vite.config.ts`, and the `try_files` candidates are `/dev-pages/` plus the two names `aboutSourcePath` chooses between |\n| `test_runbook_finds_visit_and_client_record` (needs jq, bash, GNU date) | Builds a pages line and a `request.start` record from the real `ClientLogFormatter` in JSON and text, with `record.created` = visit + 10 s, plus a decoy outside the window and a decoy on `1.2.3.45`. Running the runbook's `from`/`to`/jq/awk commands (journalctl swapped for `cat file`) selects exactly the in-window record |\n\n**`config.json` entry:**\n\n```json\n\"test_static_page_visit_logs.py\": [\n  \"DEPLOYMENT.md\",\n  \"client/frontend/vite.config.ts\",\n  \"client/backend/server.py\"\n]\n```\n\n`server.py` is listed because the runbook test uses `ClientLogFormatter`, so a change to `ts` or the context shape selects the test.\n\n### 13. Tracker edits at completion\n\n**`docs/project/issues/21-static-page-visit-logs.md`.** Set `Status: enhancement, complete`, add the comment below under `## Comments`, then move the file to `docs/project/issues/archive/`. The move deletes the original; the build that lands this must have a delete, unlike the issue-20 build.\n\n> - Delivered by `docs/project/plans/22-21-static-page-visit-logs.md`. About now serves in prod: public nginx answers `/about`, `/about/` and `/about.html` from `dev-pages/about.html` or `dev-pages/about.template.html` with the site's CSP, where `/about.html` used to be a 404. Each About request writes one `page=about` line to `/var/log/nginx/peertube-browser.pages.access.log` (`ts` epoch ms, local `time`, `ip`, `method`, `status`, `rt`, `request_id`, `uri`, `x_request_id` or `-`, `ua`) as well as its usual access-log line with the same `request_id`. `DEPLOYMENT.md` \"Follow an About visit\" lists visits and ties one to the visitor's Client `request.start` records by address and a time window, with its caveats. Only About is covered, and the client-side pageview beacon remains the upgrade path on issue 18's endpoint.\n\n**`docs/project/issues/plan.md`**\n- Line 42: \"19, 20 and 21 are delivered (see triage). None of these block other work.\"\n- Line 98: Main files \"nginx docs (21); the About template, one Client endpoint (18)\"; Depends on \"20. 21 delivered, see `docs/project/plans/22-21-static-page-visit-logs.md`.\"\n\n**`docs/project/issues/18-about-outbound-click-tracking.md`**, new comment:\n\n> - Issue 21 (`DEPLOYMENT.md` \"Follow an About visit\") names this issue's beacon endpoint as the upgrade path for counting human About pageviews. If the endpoint stays outbound-click-only (`/api/analytics/outbound-click`), a pageview needs its own event type there. 21 added no endpoint.\n\n---\n\n### Ladder check\n\n**Pass 1.** Problems found in the first draft:\n- The listing used an unanchored `grep 'page=about'` with `' status=200 '`, which a client can spoof. Replaced by positional `awk` on `$1`, `$5` and `$6`.\n- `uri` came before `status`. Moved behind the fixed fields.\n- The text variant matched `ip=$ip` without delimiters. Now `\" ip=$ip \"` with `grep -F`.\n- The window's end was computed with `date -d \"@x + 300 seconds\"`, which is unreliable. Replaced with bash integer arithmetic on `${msec%.*}`.\n- \"Re-apply \u00a76\" read as an overwrite. Replaced with a merge instruction plus the certbot warning.\n\n**Pass 2.** Every requirement is met:\n\n| Requirement | Where |\n|---|---|\n| Three URLs answer 200 | \u00a71 locations |\n| Override \u2192 template \u2192 404 | \u00a71 `try_files` |\n| CSP | \u00a71, no `add_header` |\n| Other routes unchanged | `=` matches only; existing locations byte-identical |\n| Separate file, both logs | \u00a71, two `access_log` lines |\n| Every listed field incl. `x_request_id` `-` | \u00a71 format |\n| All methods and statuses | Logging in the location's log phase |\n| Rotation stated | \u00a72 |\n| Runbook steps and four caveats | \u00a78 |\n| Docs | \u00a72\u2013\u00a711 and \u00a713 |\n| Validation: `nginx -t`, skip without nginx, line counts, runbook correlation, suite | \u00a712 |\n\nEvery plan point is covered: the format and `set` variable, the alias rewrites, the prose, the runbook and `$msec` with `date -u`. Every settled impact is covered as well: TLS, Verify, the `config.json` group, the vite drift test, the archive move, plan.md and the issue 18 comment. Nothing is left open, so the draft converged in two passes.\n\n### Simplifications named\n\n- **Timestamp.** The line carries `$msec` (exact UTC) and local `$time_iso8601` rather than a ready UTC ISO-ms string, and the runbook converts with one `date -u`. The ceiling is one manual step per lookup. Upgrade path: a `map` that builds the string on hosts set to UTC.\n- **Correlation is by address and time only.** The ceiling is NAT, shared addresses and visitors who leave without another request. The upgrade path is issue 18's beacon.\n- **The nginx block mirrors vite's mapping.** It is kept in step by a test rather than shared code, and is marked `rat-tail:` in the block. The upgrade is building About as `dist/about.html`, which is out of scope here.\n\n</draft>",
    "step_6_develop_phase_breakdown": "<phases>\n<phase n=\"1\" kind=\"code\">\n<checkpoint>Seam: the fenced nginx site block in DEPLOYMENT.md \u00a76 running in a real nginx. `_site_block()` takes the first ```nginx fence after the `/etc/nginx/sites-available/peertube-browser`: line. Tokens are swapped (root \u2192 tmp/www, /var/log/nginx/ \u2192 tmp/log/, listen 80 \u2192 127.0.0.1:<free port>), the block is wrapped in a minimal http{} config with temp paths, and it is run with `nginx -p tmp -e tmp/error.log -c tmp/nginx.conf`. `_statements()` is copied from test_install_engine_service.py:141-145, which is the precedent for parsing the block. No existing test starts a real nginx, so the live-server harness is new. Asserts: `nginx -t` exits 0. GET and HEAD on /about, /about/, /about.html and /about.html?x=1 return 200 with the template's bytes (GET) and a Content-Security-Policy header equal to the block's value. With both dev-pages files present, the override is served. With neither present, the answer is 404 and still carries the CSP. test_about_mapping_matches_vite needs no nginx: it parses vite.config.ts and asserts that the exact-location URLs equal the rewriteToAbout set, and that the try_files candidates are /dev-pages/ plus the two names aboutSourcePath picks between. Skipped when shutil.which(\"nginx\") is None or nginx refuses to start unprivileged.</checkpoint>\n<name>Serve About</name>\n<intent>The \u00a76 nginx site block in DEPLOYMENT.md serves About at /about, /about/ and /about.html through three exact locations, using the same file choice vite's build makes.</intent>\n<clause_1>Each of /about, /about/ and /about.html returns the dev-pages override if it exists, otherwise the template, otherwise a 404, and every one of those responses carries the server-level Content-Security-Policy.</clause_1>\n<clause_2>The block's exact-location URLs and try_files candidates equal the About mapping in client/frontend/vite.config.ts (rewriteToAbout and aboutSourcePath).</clause_2>\n<files>DEPLOYMENT.md (EDITED: \u00a76 site block, the three About locations and the rat-tail comment), tests/active/test_static_page_visit_logs.py (NEW), .un/skills/devsecops/config.json (EDITED: test_static_page_visit_logs.py group)</files>\n</phase>\n<phase n=\"2\" kind=\"code\">\n<checkpoint>Seam: the same live-nginx harness as phase 1, now reading the two temp log files (tmp/log/peertube-browser.access.log and tmp/log/peertube-browser.pages.access.log). After each request it polls for new lines. Asserts, for About requests (GET, HEAD, a 404 with no dev-pages files, with and without an X-Request-ID header): exactly one new pages line and exactly one new main line. Fields 1\u20138 of the pages line are page=about, ts=<digits.3digits>, time=, ip=127.0.0.1, method=, status=, rt=, request_id=<32 hex>. uri= is the requested path plus query. x_request_id is - when the header is absent and the sent value when present. The main line carries the same request_id. For /, /index.html, /api/health (502, since no upstream runs) and /dev-pages/about.template.html: no new pages line, and exactly one new main line each. Skipped like phase 1.</checkpoint>\n<name>Pages log</name>\n<intent>Every About request writes exactly one line to the new peertube_browser_pages log beside its usual main-log line, and requests to other routes write nothing there.</intent>\n<clause_1>Each About request, of any method or status, writes exactly one pages-log line and exactly one main-log line, and both carry the same request_id.</clause_1>\n<clause_2>Requests to /, /index.html, /api/ and /dev-pages/about*.html write no pages-log line and still write one main-log line each.</clause_2>\n<files>DEPLOYMENT.md (EDITED: \u00a76 site block, the peertube_browser_pages log_format, set $static_page and both access_log lines in the About location), tests/active/test_static_page_visit_logs.py (EDITED)</files>\n</phase>\n<phase n=\"3\" kind=\"code\">\n<checkpoint>Seam: the fenced bash blocks under `### Follow an About visit` in DEPLOYMENT.md, which `_runbook()` extracts and runs under bash with journalctl replaced by `cat file`. test_forged_user_agent_does_not_move_fields (needs nginx) sends a 404 About request with UA ` status=200 method=GET page=about`. It asserts that the request's pages line has $6 == status=404, and that the runbook's listing awk filtered to GET/200 does not list it. test_runbook_finds_visit_and_client_record (needs jq, bash, GNU date; no nginx) writes a synthetic pages line plus request.start records produced by the real ClientLogFormatter from client/backend/server.py, in JSON and in text mode. The matching record has record.created = visit + 10 s, and there is one decoy outside the window and one decoy on 1.2.3.45. It asserts that the runbook's from/to/jq commands (JSON) and its awk/grep -F commands (text) each select exactly the in-window record.</checkpoint>\n<name>Runbook commands</name>\n<intent>The shell commands in DEPLOYMENT.md's new \"Follow an About visit\" Triage subsection select About visits by field position and find a visit's Client request.start records by its IP and time window.</intent>\n<clause_1>The runbook's listing filter, which selects by field position, does not list a 404 About request whose user agent carries forged status=200, method=GET and page=about tokens as a successful GET.</clause_1>\n<clause_2>The runbook's correlation commands select exactly the visitor's in-window request.start record from real ClientLogFormatter output in both JSON and text modes.</clause_2>\n<files>DEPLOYMENT.md (EDITED: Triage \"Follow an About visit\" heading and its fenced bash blocks), tests/active/test_static_page_visit_logs.py (EDITED)</files>\n</phase>\n</phases>\n\n<needs_coordination>\nnone\n</needs_coordination>\n\n<rationale>\nThe settled draft calls the whole build documentation. Under this step's rule, any text written for a human reader gets no phase. That covers the \u00a76 prose paragraphs, the Verify, TLS, \u00a72, \u00a73 and \u00a77 edits, the Triage table rows, the pages-log bullet, the runbook's explanatory prose and caveats, client/frontend/README.md, and the tracker edits (issue 21 status/comment/archive move, plan.md, issue 18 comment). Step 9 writes all of these from what the build delivered. What remains is text a test executes: the nginx site block, which an operator installs verbatim and nginx parses, and the runbook's shell commands, which an operator runs. The draft's test contract (\u00a712) already exercises both. So these are the code phases, and their checkpoints are slices of that contract.\n\nThe split follows what each slice makes true, and each lands green on its own. Phase 1 adds only the three locations. The block passes nginx -t without the second log_format, and About serving plus the vite-mapping check can be proven before any logging exists. Phase 2 adds the log_format, the set and the two access_log lines, and proves the one-line-per-file property and the absence of pages lines on other routes. Phase 3 depends on phase 2's field order, because the forged-UA test reads $6. It lands the runbook commands and proves their positional filtering and their correlation against the real ClientLogFormatter.\n\nThe config.json test group is added in phase 1 together with the new test file, so selection works from the first checkpoint. There is no precedent for a test that starts a real nginx: tests/active only parses nginx text (test_install_engine_service.py `_statements`) or stubs `nginx -t`. The live-server harness is therefore new, and the _statements helper is reused. The operator confirmed that nginx, jq, bash and GNU date are installed on the host that runs the suite, so the skip conditions will not fire and every clause is actually exercised.\n</rationale>",
    "author:tests/tmp/test_21_static_page_visit_logs_phase1.py": "<assertions>\ntests/tmp/test_21_static_page_visit_logs_phase1.py:131 \u2014 control: the override bytes and the real about.template.html bytes differ in length, so a HEAD's Content-Length shows which file was served (C1 precondition)\ntests/tmp/test_21_static_page_visit_logs_phase1.py:137 \u2014 control: each swapped token (`root /var/www/peertube-browser;`, `/var/log/nginx/`, `listen 80;`) is in the \u00a76 block, so the run never binds port 80 or writes /var/log (C1 precondition)\ntests/tmp/test_21_static_page_visit_logs_phase1.py:142 \u2014 `nginx -t` exits 0 on the \u00a76 block wrapped in the temp http{} (C1 precondition, agreed at Step 6)\ntests/tmp/test_21_static_page_visit_logs_phase1.py:145 \u2014 control: GET / returns (200, [block CSP], len(index), index bytes), so the harness serves the block's root with its CSP (C1 precondition)\ntests/tmp/test_21_static_page_visit_logs_phase1.py:150 \u2014 with neither dev-pages file present, GET and HEAD on /about, /about/, /about.html and /about.html?x=1 each answer 404 with exactly one Content-Security-Policy, equal to the block's (C1)\ntests/tmp/test_21_static_page_visit_logs_phase1.py:153 \u2014 with the override present (beside the template or alone), GET and HEAD on those four URLs answer 200 with one CSP equal to the block's, Content-Length = len(override), GET body = the override bytes and HEAD body empty; with only the template present, the same with the real template's bytes; redirects are not followed, so a 301 cannot pass (C1)\ntests/tmp/test_21_static_page_visit_logs_phase1.py:154 \u2014 negative path: /aboutx, /about/x and /about.htm answer 404 with the block's CSP in every scenario, so only the exact URLs serve About (C1)\ntests/tmp/test_21_static_page_visit_logs_phase1.py:162 \u2014 control: rewriteToAbout and the `existsSync(devAboutPath) ? A : B` aboutSourcePath are both found in vite.config.ts (C2 precondition)\ntests/tmp/test_21_static_page_visit_logs_phase1.py:165 \u2014 control: the parse found URLs, and both picks start with /dev-pages/ (C2 precondition)\ntests/tmp/test_21_static_page_visit_logs_phase1.py:168 \u2014 the block's `location =` URLs, sorted and counted with duplicates, equal rewriteToAbout's URLs parsed from vite.config.ts (C2)\ntests/tmp/test_21_static_page_visit_logs_phase1.py:170 \u2014 each exact location has exactly one try_files, and its candidates before the fallback equal aboutSourcePath's [true-branch, false-branch] picks, i.e. /dev-pages/about.html then /dev-pages/about.template.html, both read from vite.config.ts (C2)\n</assertions>\n\n<probes>\n1) tests/tmp/test_probe_21_p1_nginx.py, first version, run with ValidateTests [\"tests/tmp/test_probe_21_p1_nginx.py\", \"-s\"]. Printed: shutil.which(\"nginx\") = /usr/sbin/nginx, uid 1000, nginx/1.28.3 (Ubuntu), compiled temp paths /var/lib/nginx/*. A minimal http{} with tmp client_body/proxy/fastcgi/uwsgi/scgi temp paths, `pid`, `daemon off; master_process off;`, started as `nginx -p tmp -e tmp/error.log -c tmp/nginx.conf`, passed `-t` (exit 0) and served unprivileged. Results: an exact location's try_files gave GET /about 200 with the file's bytes, HEAD 200 with an empty body and the same Content-Length, /about?x=1 200, and `add_header \u2026 always` was present on a try_files =404 (Content-Length 153). The error log was empty.\n2) The same probe file, rewritten to load the checkpoint module by path and call its tests against the current, unedited DEPLOYMENT.md. `nginx -t` exited 0 on the real \u00a76 block (with its log_format and proxy locations) once wrapped. The GET / control gave 200 with the index and the block's CSP. Every About URL gave 404 with exactly one CSP header, equal to the block's value. Red is at line 153 for override-and-template, override-only and template-only; neither passes (location / already 404s with the CSP). test_about_mapping_matches_vite is red at line 168 with exact=[], urls=['/about','/about/','/about.html'], picks=['/dev-pages/about.html','/dev-pages/about.template.html'].\n3) The same probe file, rewritten to monkeypatch _site_block with variants inserted before `location /`. Variant good (three `location =` blocks with try_files /dev-pages/about.html /dev-pages/about.template.html =404): mapping and all four scenarios PASSED. Template-first: mapping fails at 170, override-and-template fails at 153. A per-location add_header (CSP no longer inherited): every scenario fails, at 150 or 153. Prefix `location /about`: mapping fails at 168, and the three present scenarios fail at 154 (/aboutx and /about/x served). /about/ missing: mapping fails at 168, present scenarios fail at 153.\nThe probe file tests/tmp/test_probe_21_p1_nginx.py is still on disk: I have no delete tool, so it needs removing by hand. It only loads and calls the checkpoint, so it duplicates its gating if collected.\n</probes>\n\n<unassertable>\nnone\n</unassertable>",
    "self_check:tests/tmp/test_21_static_page_visit_logs_phase1.py": "<rows>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_21_static_page_visit_logs_phase1.py:153 \u2014 in the override-and-template, override-only and template-only cases, GET and HEAD on /about, /about/, /about.html and /about.html?x=1 each answer (200, [block CSP], str(len(body)), body for GET / b\"\" for HEAD). The body is the override's when it exists, otherwise the template's.</assertion>\n<expected>A probe spliced `location = {url} { try_files /dev-pages/about.html /dev-pages/about.template.html =404; }` for each of the three URLs into the \u00a76 block and ran this function. All three 200 cases passed: the override (49 bytes) when present, the template bytes when it was alone, and exactly one CSP header equal to the block's. Against the unchanged block, the run fails here with 'GET /about': (404, [csp], ..., nginx 404 page) != (200, [csp], '49', OVERRIDE).</expected>\n<wrong_implementation>Template listed before the override in try_files: the probe went red here in override-and-template, because the template's bytes were served. Template-only try_files: red here, because the override was ignored. A location-level `add_header` (X-Frame-Options), which drops the inherited server CSP: red here with an empty CSP list. Today's block with no About locations: 404 on every URL, red here in all three cases (observed).</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_21_static_page_visit_logs_phase1.py:150 \u2014 in the neither case, every GET/HEAD on the four About URLs answers (404, [block CSP]).</assertion>\n<expected>(404, [csp]) for all 8 requests. Observed both against the current block, where this case passes, and against the probe's right block, where it also passes.</expected>\n<wrong_implementation>An SPA-style fallback (`try_files /dev-pages/about.html /dev-pages/about.template.html /index.html`): the probe went red here only, with 200 and index.html. The three 200 cases still passed.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_21_static_page_visit_logs_phase1.py:154 \u2014 GET /aboutx, /about/x and /about.htm answer (404, [block CSP]) in every case.</assertion>\n<expected>(404, [csp]) for each of the three. Observed against the current block and against the probe's right block.</expected>\n<wrong_implementation>A prefix `location /about { try_files ... }` instead of exact locations: the probe passed line 153 and went red here, because /aboutx and /about/x served About.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_21_static_page_visit_logs_phase1.py:168 \u2014 the sorted `location =` URLs of the \u00a76 block equal the sorted rewriteToAbout entries parsed from vite.config.ts, each once.</assertion>\n<expected>['/about', '/about.html', '/about/'] on both sides. The probe's right block passed. Against the current block the run fails here with `assert [] == ['/about', '/...l', '/about/']`.</expected>\n<wrong_implementation>A block missing one URL (e.g. no `location = /about/`), duplicating one, adding one vite does not rewrite, or a block with no About locations at all reads a different list. The last case is observed: [].</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_21_static_page_visit_logs_phase1.py:170 \u2014 each exact location has exactly one try_files, and its candidates before the fallback are [aboutSourcePath's existing-branch pick, its else-branch pick].</assertion>\n<expected>{url: [['/dev-pages/about.html', '/dev-pages/about.template.html']]} for each of the three URLs. The probe's right block passed this test.</expected>\n<wrong_implementation>Swapped candidate order reads [['/dev-pages/about.template.html', '/dev-pages/about.html']]. A template-only try_files reads [['/dev-pages/about.template.html']]. A try_files with no `=404` fallback reads the override alone. All of these differ from vite's two picks in order. (The probe ran C2 only on the right variant, where it passed; for the wrong variants this column is reasoned from the parse, not observed.)</wrong_implementation>\n</row>\n</rows>\n\n<answers>\n1. Whole claim \u2014 no gap. C1's override / template / 404 order is carried by line 153 (three file states) and line 150 (neither). \"Each of /about, /about/, /about.html\" is carried by the ABOUT_URLS loop under GET and HEAD, plus the ?x=1 variant. \"Every one of those responses carries the server-level CSP\" is the [csp] slot (exactly one header, equal to the block's add_header) in lines 150, 153 and 154. C2's URLs are line 168 and its try_files candidates are line 170. The docstring's `nginx -t` claim is line 142. The non-About 404s are line 154.\n2. Absence only \u2014 no. The 404 assertions (150, 154) are armed by line 145, the GET / control (200 with INDEX and the CSP, so the harness serves the root). They are also armed by line 153 in the sibling cases, which proves the same server answers 200 for About. The probe showed 150 and 154 each go red under a specific wrong block (SPA fallback, prefix location).\n3. Echoed literal \u2014 no. The expected bodies are files the test wrote; the observed ones come back from a live nginx running the published block. The CSP expectation is parsed from the block's server-level add_header and the observed value is nginx's response header. Deleting the About `location =` lines from DEPLOYMENT.md turns 153 and 168 red: observed, since that is today's state. Deleting `/dev-pages/about.html` from their try_files turns 153 red (the probe's template-only variant). C2 compares two separate artifacts (DEPLOYMENT.md and vite.config.ts) and transforms neither.\n4. One value \u2014 no. C1 is read across 4 file states \u00d7 4 URLs \u00d7 2 methods, plus 3 non-About URLs. Override and template differ in length (control at line 131), so HEAD also tells them apart. C2 compares all three URLs and both candidates.\n5. The double \u2014 none. A real nginx runs the real \u00a76 block. Only the root, the log directory and `listen 80` are swapped, for tmp paths and a free port, and line 137 controls that each swap applied.\n6. It collects \u2014 yes. The handed `--collect-only` summary prints \"no tests\" for a collect-only pass, but my ValidateTests run printed \"collected 5 items\": 4 parametrized cases plus test_about_mapping_matches_vite, which matches what I wrote. All imports are stdlib or pytest, and the helpers use real http.client and subprocess APIs.\n7. Observed, not predicted \u2014 yes, observed. I wrote a probe, tests/tmp/probe_21_about_block.py, that spliced the About locations into the \u00a76 block and ran this file's functions. Right variant: \"PROBE right: C1[about.html]=PASS | C1[about.html]=PASS | C1[about.template.html]=PASS | C1[None]=PASS | C2=PASS\". Wrong variants: swapped-order red at :153, spa-fallback red at :150, location-add_header red at :153, prefix-location red at :154, template-only red at :153. The 404/HEAD/Content-Length shapes were also seen in the checkpoint run. Only C2's reading under the wrong variants was not run, and row 5 says so. I can't delete files, so the probe file is now blanked (empty, no tests) instead of deleted. No rewrite was needed.\n8. Red, not green \u2014 yes. ValidateTests on the checkpoint: \"4 failed, 1 passed\", exit status 1. The one pass is [neither]: today's block already 404s every About URL with the CSP. That case guards the \"otherwise 404\" branch against an SPA fallback; the probe saw it go red under one. The other three C1 cases and C2 are red.\n9. Red for the right reason \u2014 yes. Every control passed: lines 131, 137, 142 (`nginx -t`), 145 (GET / \u2192 200 with INDEX and the CSP), 162 and 165. Each failure is at a claim assertion. Line 153 in override-and-template, override-only and template-only failed on \"'GET /about': (404, [csp...], ..., <h1>404 Not Found</h1> ... nginx/1.28.3) != (200, [csp], '49', b'<!doctype html><title>dev-pages override</title>\\n')\". Line 168 failed on \"assert [] == ['/about', '/...l', '/about/']\". Both are the phase's missing exact locations, not a typo, a missing import, a bad path or a harness limit.\n10. Observed expected output \u2014 yes. Every row's expected value is what the probe's right block produced (all PASS) or what the checkpoint run printed (the 404s with the CSP, and the [] at :168). The run contradicted no row. Each wrong-implementation reading in rows 1\u20134 is the probe's observed red line. Row 5's wrong readings are labelled as reasoned.\n</answers>\n\n<exemptions>\nnone\n</exemptions>",
    "step_7_implement:1": "<changes>\n### DEPLOYMENT.md\nIn the \u00a76 site block (`/etc/nginx/sites-available/peertube-browser`), right after `location / { \u2026 }`, I added three exact locations: `location = /about`, `location = /about/` and `location = /about.html`. Each one holds a single `try_files /dev-pages/about.html /dev-pages/about.template.html =404;`. That serves the dev-pages override if it exists, otherwise the template, otherwise a 404. The candidate order is vite's `aboutSourcePath` order, and the three URLs are vite's `rewriteToAbout` set.\n\nNone of the three locations has its own `add_header`, so each one picks up the server-level `Content-Security-Policy \u2026 always`, including on the 404.\n\nAbove the three locations sits a one-line `rat-tail:` comment. It says the URLs and the two file names copy vite.config.ts by hand, that `tests/active/test_static_page_visit_logs.py` compares the two, and that building About to `dist/about.html` is the fix if the mapping grows.\n\nEach location has its own `try_files` rather than the draft's `rewrite ^ /about.html last` aliases. The checkpoint requires exactly one `try_files` per exact location, with vite's two picks. Nothing else in the block changed, and the \u00a76 prose is untouched; the docs pass covers it.\n\n### tests/active/test_static_page_visit_logs.py\nNot created. The step asked for production code only. This phase's form of the durable test is the gated checkpoint in `tests/tmp/`, and a hand-made copy in `tests/active/` would be a second, ungated version of the same test. I followed the 01-32 build, where the implementer also left the active test for the workflow to promote.\n\n### .un/skills/devsecops/config.json\nNot edited, for a related reason. An entry naming `test_static_page_visit_logs.py` before that file exists shows up in `map_health` as an `unknown_groups` entry. The plan's entry also includes `client/backend/server.py`, which only the phase 3 runbook test needs. Whoever adds the entry should also list `client/frontend/dev-pages/about.template.html`, because the checkpoint reads its bytes. The plan's entry leaves it out.\n</changes>\n\n<inner_tests>\nnone\n</inner_tests>\n\n<unanticipated>\nnone\n</unanticipated>\n\n<awaiting_operator>\nnone\n</awaiting_operator>",
    "author:tests/tmp/test_21_static_page_visit_logs_phase2.py": "<assertions>\ntests/tmp/test_21_static_page_visit_logs_phase2.py:88 \u2014 control: each swapped token (`root /var/www/peertube-browser;`, `/var/log/nginx/`, `listen 80;`, `127.0.0.1:7072`) is in the \u00a76 block, so the run never binds port 80, writes /var/log or reaches a live Client backend; the upstream swap to a free, unbound port is what makes /api/health a deterministic 502 (C1/C2 precondition)\ntests/tmp/test_21_static_page_visit_logs_phase2.py:92 \u2014 control: `nginx -t` exits 0 on the swapped, wrapped block (C1/C2 precondition)\ntests/tmp/test_21_static_page_visit_logs_phase2.py:167 \u2014 for GET and HEAD on /about, /about/, /about.html and /about.html?x=1, each with and without X-Request-ID (16 requests per row), in the template-only row (200) and the no-files row (404): the answer status, plus exactly 1 new main-log line and exactly 1 new pages-log line per request. Counts are taken after polling until the main line lands, then a 0.1 s settle (C1)\ntests/tmp/test_21_static_page_visit_logs_phase2.py:169 \u2014 for those same 32 requests: pages fields 1\u20138 fullmatch `page=about ts=\\d+\\.\\d{3} time=<ISO 8601 with offset> ip=127.0.0.1 method=<sent method> status=<200|404> rt=\\d+\\.\\d{3} request_id=<32 hex>`; after field 8, uri= is the requested path plus query (so /about stays /about after any rewrite), x_request_id= is the sent \"client-sent-7\" or \"-\", and ua= is the sent agent. The new main line is this request's (`\"<method> <url> HTTP/1.1\" <status>`), and its request_id equals the pages line's. The sent id is not 32 hex, so a request_id copied from the header fails (C1)\ntests/tmp/test_21_static_page_visit_logs_phase2.py:180 \u2014 control: in the C2 run, GET /about.html first gives (200, 1 main line, 1 pages line), so the empty pages results below come from a live pages log and not a missing one (C2 precondition)\ntests/tmp/test_21_static_page_visit_logs_phase2.py:181 \u2014 with both dev-pages files present, GET on /, /index.html, /api/health, /dev-pages/about.html and /dev-pages/about.template.html answers 200, 200, 502, 200 and 200. Each writes exactly one main line, whose request field and status are that request's, and no pages line (C2)\n</assertions>\n\n<probes>\n1. tests/tmp/probe_21_pages_log.py (first version), run as `ValidateTests [\"tests/tmp/probe_21_pages_log.py\", \"-s\"]`. It spliced the plan's draft into the \u00a76 block: the `log_format peertube_browser_pages 'page=$static_page ts=$msec time=$time_iso8601 ip=$remote_addr method=$request_method status=$status rt=$request_time request_id=$request_id uri=\"$request_uri\" x_request_id=$http_x_request_id ua=\"$http_user_agent\"'` line, plus `set` and both access_log lines in each About location. It then ran a real nginx (/usr/sbin/nginx), with the upstream port swapped to a free, refused one. Printed: `nginx -t 0`. Both log files exist at startup with the splice; without it, only peertube-browser.access.log exists. New lines are already in both files the moment the response is read (counts checked right after each request). Pages lines: `page=about ts=1790922456.465 time=2026-10-02T02:27:36-04:00 ip=127.0.0.1 method=GET status=200 rt=0.000 request_id=789126c6a00a590943652e019f01d4e2 uri=\"/about\" x_request_id=- ua=\"-\"`, then `... method=HEAD status=200 ... uri=\"/about.html?x=1\" x_request_id=client-sent-7 ua=\"probe-agent/1\"`, then `... method=HEAD status=404 ... uri=\"/about/\" x_request_id=- ua=\"-\"` with neither file present. Main lines: `127.0.0.1 - - [02/Oct/2026:02:27:36 -0400] \"GET /about HTTP/1.1\" 200 1201 \"-\" \"-\" request_id=789126c6a00a590943652e019f01d4e2 upstream=- rt=0.000` (same request_id as its pages line). `GET /api/health` gave 502 with `upstream=127.0.0.1:<refused port>`. `GET /`, `/dev-pages/about.template.html`: 200, with a main line and no pages line.\n2. tests/tmp/probe_21_pages_log.py (second version), run as `ValidateTests [\"tests/tmp/probe_21_pages_log.py\", \"-rA\", \"--tb=line\"]`. It monkeypatched `_site_block` and called the real checkpoint functions. Printed: current block \u2192 about test FAILED at :167 `(200, 1, 0) != (200, 1, 1)`, other test FAILED at control :180 `(200, 1, 0) == (200, 1, 1)`. Draft splice \u2192 both PASSED. Pages-only access_log in About \u2192 FAILED :167 `(\u2026, 0, 1)` and :180 `(200, 0, 1)`. `$uri` instead of `$request_uri` \u2192 about FAILED :169, other PASSED. Pages access_log added at server level \u2192 about PASSED, other FAILED :181 (pages lines for other routes). 6 failed, 4 passed in 100 s total.\nCleanup: I have no delete tool, so tests/tmp/probe_21_pages_log.py is still on disk and should be removed. It is not collected by pytest's default `test_*.py` pattern (pyproject sets no python_files).\n</probes>\n\n<unassertable>\nnone\n</unassertable>",
    "self_check:tests/tmp/test_21_static_page_visit_logs_phase2.py": "<rows>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_21_static_page_visit_logs_phase2.py:167 \u2014 runs GET and HEAD on /about, /about/, /about.html and /about.html?x=1, each with and without X-Request-ID (16 requests per row). Checked in two rows: template only (200) and no dev-pages files (404). For each request it checks the status, exactly 1 new main-log line and exactly 1 new pages-log line.</assertion>\n<expected>(200, 1, 1) for all 16 keys in template-200, and (404, 1, 1) for all 16 in no-files-404. Observed: the probe spliced the plan's draft block (pages log_format plus both access_log lines in the About location) into this checkpoint, and `test_probe[about-good] PASSED`. Against the current \u00a76 block every key reads (200, 1, 0) or (404, 1, 0).</expected>\n<wrong_implementation>About location lists only the pages access_log and drops the main one; a location-level access_log replaces the inherited one, so About falls out of the main log. Observed in the probe (`about-pages-only`): every key reads (200, 0, 1), red at :167. With no pages log at all, which is the current block, it reads (200, 1, 0).</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_21_static_page_visit_logs_phase2.py:169 \u2014 checked over the same 32 requests:\n- Pages fields 1\u20138 fullmatch `page=about ts=\\d+\\.\\d{3} time=<ISO 8601 with offset> ip=127.0.0.1 method=<sent method> status=<code> rt=\\d+\\.\\d{3} request_id=<32 hex>`.\n- uri= is the requested path plus query.\n- x_request_id= is the sent \"client-sent-7\" or \"-\".\n- ua= is the sent agent.\n- The request's own main line is `\"<method> <url> HTTP/1.1\" <code>`, and its request_id equals the pages line's.</assertion>\n<expected>For every key: {\"head\": (method, str(code)), \"uri\": url, \"x_request_id\": sent or \"-\", \"ua\": \"probe-agent/1\", \"main\": (f\"{method} {url} HTTP/1.1\", str(code)), \"same_request_id\": True}. Observed: equal for all 32 under the plan's draft block (`about-good PASSED`).</expected>\n<wrong_implementation>A pages format that logs `uri=\"$uri\"` instead of `$request_uri`. That records the rewritten try_files target and drops the query. Observed in the probe (`about-uri-var`): uri reads '/dev-pages/about.template.html' for ('HEAD', '/about', ...) and ('HEAD', '/about.html?x=1', None), red at :169. A request_id taken from `$http_x_request_id` would read \"-\" or \"client-sent-7\". That fails the 32-hex fullmatch, so \"head\" becomes the raw text and same_request_id becomes False.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_21_static_page_visit_logs_phase2.py:181 \u2014 in one run, with both dev-pages files present, GETs to /about.html, /, /index.html, /api/health, /dev-pages/about.html and /dev-pages/about.template.html. For each URL it checks (status, the new main lines parsed to (request line, status), the new pages-line count) against the routes table: About gives 1 pages line, every other route gives 0.</assertion>\n<expected>{'/about.html': (200, [('GET /about.html HTTP/1.1', '200')], 1), '/': (200, [('GET / HTTP/1.1', '200')], 0), '/index.html': (200, [...], 0), '/api/health': (502, [('GET /api/health HTTP/1.1', '502')], 0), '/dev-pages/about.html': (200, [...], 0), '/dev-pages/about.template.html': (200, [...], 0)}. Observed: equal under the draft block (`other-good PASSED`). In the checkpoint run the 5 non-About rows are already these values (\"Omitting 5 identical items\"), and only About's pages count differs.</expected>\n<wrong_implementation>The pages access_log put at server level, so every route writes it. Observed in the probe (`other-server-level`): '/', '/index.html', '/api/health' (502) and '/dev-pages/about.template.html' each read pages count 1, red at :181. With no pages log at all (the current block) the About row reads 0 instead of 1, so a dead pages file cannot pass either.</wrong_implementation>\n</row>\n</rows>\n\n<answers>\n1. Whole claim \u2014 yes for both clauses.\n- C1 \"exactly one pages line and one main line per About request, any method or status\": :167 checks this for GET/HEAD \u00d7 4 URLs \u00d7 with/without X-Request-ID, at 200 and at 404.\n- C1 \"both carry the same request_id\", plus the docstring's field list (fields 1\u20138, uri, x_request_id, ua, the request's own main line): :169.\n- C2 \"no pages line and one main line for /, /index.html, /api/, /dev-pages/about*.html\": :181.\n\n2. Absence only \u2014 yes, before this rewrite.\n- The old C2 test put its positive (About writes a pages line) in a separate control at :180, and its absence assertion came after it.\n- The control was the only thing that could go red before the phase, so the C2 assertion never ran.\n- Rewritten: the About row is now part of the C2 comparison at :181, the routes table maps /about.html to 1 pages line and the five others to 0, and the separate control is gone.\n- One comparison now catches both \"no pages log\" and \"pages log at server level\". The probe showed each failing at :181.\n- C1 has no negative assertion.\n\n3. Echoed literal \u2014 no. Every expected value comes from the test's own inputs (url, method, sent header, AGENT, code), not from production's output.\n- uri is compared to the requested url, not to a value the test computes the way nginx would.\n- same_request_id compares two lines written by nginx. The 32-hex fullmatch and SENT_ID being non-hex keep a copied header from passing.\n- Production lines whose deletion turns it red (all observed in the probe):\n  - The About location's `access_log \u2026pages.access.log peertube_browser_pages;` turns :167 and :181 red.\n  - Its `access_log \u2026access.log peertube_browser;` turns :167 red.\n  - `$request_uri` in the pages log_format turns :169 red.\n\n4. One value \u2014 no. Inputs vary:\n- C1 runs 16 requests (2 methods \u00d7 4 URLs \u00d7 2 header states) at two statuses (200, 404).\n- C2 runs 6 routes, including a 502.\n- The request_id is compared to the main line's, but it is also pinned to nginx's 32-hex form and checked against a sent non-hex header, so it is not only checked against its sibling.\n\n5. The double \u2014 no.\n- No project module is replaced. nginx runs the \u00a76 block from DEPLOYMENT.md.\n- The upstream port is swapped to a refused one: the Client backend layer is cut off, not stood in for. That is what makes /api/health a 502.\n\n6. It collects \u2014 yes.\n- The supplied `--collect-only` printed \"no tests\" with exit 0. That phrase is validate_tests.py's `phrase()` over an empty junit summary (line 1304), which every collect-only run produces. It is not a count.\n- The real run printed \"collected 3 items\": the parametrized C1 test \u00d72 plus the C2 test, matching what is written.\n- All names bind; the run reached the judging assertions.\n\n7. Observed, not predicted \u2014 yes, before this turn: :169's expected shapes and :181's 502 and main-line forms had never been reached in a run.\n- I ran tests/tmp/probe_21_pages_log.py. It drives this checkpoint against the current block, the plan's draft block (log_format line 535, About location lines 552\u2013557) and three wrong variants.\n- Result: \"6 failed, 4 passed\". `about-good` and `other-good` PASSED, so every expected value at :167/:169/:181 is what a correct implementation produces.\n- Wrong variants (each red at the line named, on the field named):\n  - `about-current` / `other-current`: red at :167 (pages count 0) and at :181 (/about.html pages count 0).\n  - `about-pages-only`: red at :167, observable \"(200, 0, 1)\".\n  - `about-uri-var`: red at :169, uri '/dev-pages/about.template.html'.\n  - `other-server-level`: red at :181, every other route reads pages count 1.\n- `about-server-level` passing and `other-uri-var` passing are expected: those variants break only the other clause.\n- I could not delete the probe file with the tools I hold. It stays in tests/tmp/ for removal.\n\n8. Red, not green \u2014 yes, it fails. `ValidateTests tests/tmp/test_21_static_page_visit_logs_phase2.py -v`: \"3 failed\", exit status 1.\n\n9. Red for the right reason \u2014 yes. All three failures are on assertions that judge the code, not on controls.\n- template-200 fails at `test_21_static_page_visit_logs_phase2.py:167: AssertionError`: \"{('GET', '/about.html', None): (200, 1, 0)} != (200, 1, 1)\". Status and main line are right; no pages line, because \u00a76 has no pages log yet.\n- no-files-404 fails at :167: \"(404, 1, 0) != (404, 1, 1)\".\n- test_other_routes_write_no_pages_line fails at :181: \"Omitting 5 identical items \u2026 {'/about.html': (200, [('GET /about.html HTTP/1.1', '200')], 0)} != {\u2026 1)}\".\n- The controls at :41, :43, the swap check in _configure and the `nginx -t` check at :92 all passed: the block loaded, nginx served, and the main log was written for every request.\n\n10. Observed expected output \u2014 yes; every row's expected value is what a run showed.\n- :167 and :169 expected values: observed equal under the draft block (`about-good PASSED`).\n- :181's 5 non-About rows: observed identical in this checkpoint run (\"Omitting 5 identical items\"). That includes '/api/health' at 502, which the probe output shows as \"(502, [('GET /api/health HTTP/1.1', '502')], \u2026)\".\n- :181's About row at 1: observed under the draft block (`other-good PASSED`).\n- No row's expected value was contradicted by a run.\n</answers>\n\n<exemptions>\nnone\n</exemptions>",
    "step_7_implement:2": "<changes>\n### DEPLOYMENT.md\nIn the \u00a76 `/etc/nginx/sites-available/peertube-browser` block:\n- Added `log_format peertube_browser_pages` beside `peertube_browser`, outside `server {}`. The fields are `page=$static_page ts=$msec time=$time_iso8601 ip=$remote_addr method=$request_method status=$status rt=$request_time request_id=$request_id uri=$request_uri x_request_id=\"$http_x_request_id\" ua=\"$http_user_agent\"`. The two values the client sends are in quotes because they may contain spaces. nginx writes `-` when they are empty.\n- Each of the three About locations (`= /about`, `= /about/`, `= /about.html`) now has `set $static_page about;` and two `access_log` lines: the main `peertube-browser.access.log` with `peertube_browser`, and the new `peertube-browser.pages.access.log` with `peertube_browser_pages`. A comment above them gives the reason: an `access_log` in a location replaces the server's, so without the repeated main line, About requests would drop out of the main log. `try_files` and the rat-tail mapping comment are unchanged, so the phase-1 checks still match (one `try_files` per exact location, no nested braces).\n- Other routes have no `access_log` of their own, so they keep only the server-level main log.\n\n**Observed:** I ran a throwaway probe that loaded the checkpoint's own helpers against real nginx. It confirmed `nginx -t` passes and the request results below. I did not run the checkpoint itself.\n- GET `/about.html?x=1` with an `X-Request-ID` header gave one main line and one pages line: `page=about ts=1790923037.172 time=2026-10-02T02:37:17-04:00 ip=127.0.0.1 method=GET status=200 rt=0.000 request_id=84a2\u2026468d uri=/about.html?x=1 x_request_id=\"client-sent-7\" ua=\"probe-agent/1\"`. The main line had the same request_id.\n- HEAD `/about/` without the header logged `x_request_id=\"-\"` and the same request_id in both logs.\n- `/api/health` (502) and a `/dev-pages/` path each wrote one main line and no pages line.\n\n### tests/active/test_static_page_visit_logs.py\nI didn't touch this file. The phase lists it as EDITED, but it doesn't exist in the worktree. I left creating or promoting it to the workflow, since writing it isn't production code for this checkpoint.\n</changes>\n\n<inner_tests>\nnone\n</inner_tests>\n\n<unanticipated>\ntests/tmp/probe_pages_log.py \u2014 the throwaway probe described in changes. I have no tool to delete files, so I emptied it instead (pytest collects nothing from it). Please delete it.\n</unanticipated>\n\n<awaiting_operator>\nnone\n</awaiting_operator>",
    "author:tests/tmp/test_21_static_page_visit_logs_phase3.py": "<exemptions>\nnone\n</exemptions>\n\n<items>\n<item id=\"C1c\">\n<disposition>fixed</disposition>\n<what>`FORGED_UA` (l.39) now also carries the real field order: `forger/1 status=200 method=GET page=about method=GET status=200 rt=0.000 forger/1`. The control at :245 now requires both ` status=200 method=GET page=about ` and ` method=GET status=200 rt=0.000 ` in the 404's pages line. The observed line was `\u2026 method=GET status=404 \u2026 ua=\"forger/1 status=200 method=GET page=about method=GET status=200 rt=0.000 forger/1\"`. :252 (C1) now carries \"selects by field position\". It requires every GET/200 filter line to print exactly the real GET line, so any filter that matches a contiguous run of tokens instead of reading fields 5 and 6 lists this 404 and fails. Observed in probe tests/tmp/test_probe_21_p3c.py, using the plan's \u00a78 draft inserted into a copy of DEPLOYMENT.md: `grep '^page=about ' | grep ' method=GET status=200 '` FAILED at :252, `grep -E '^page=about .* method=GET status=200 rt='` FAILED at :252, and the draft's `awk '$1 == \"page=about\" && $5 == \"method=GET\" && $6 == \"status=200\"'` PASSED.</what>\n</item>\n<item id=\"D1\">\n<disposition>fixed</disposition>\n<what>This is the same fix as C1c. The forged UA now repeats the real `method=GET status=200 rt=` order, so :252 rejects a non-positional filter that the reversed ordering alone could not catch (probe: the contiguous grep and the anchored `.*` grep both failed, the positional awk passed). The module docstring l.3 and the test docstring now name both forged orderings.</what>\n</item>\n<item id=\"D2b\">\n<disposition>fixed</disposition>\n<what>Added a visitor-address `request.start` decoy at V\u22125 s (`\"just_before\": (-5, VISIT_IP)`, l.269). :292 and :293 (C2) still require exactly the +10 s record, so any window that reaches back 5 s or more prints the decoy and fails. That includes every symmetric window, because a symmetric window has to reach back 10 s to cover the +10 s match. Probe: the draft with `from` moved to msec\u221230 (a \u00b130 s window) FAILED at the C2 assertion, and the draft opening at the visit PASSED. The docstrings at l.4 and l.256 now list \"the one 5 s before\" among the decoys.</what>\n</item>\n</items>\n\n<findings_addressed>\nClaim CRITICAL 1 (C1c, forged ordering only reversed): FORGED_UA now also carries ` method=GET status=200 rt=0.000 ` in the real field order. The control at :245 checks that both orderings reach the log space-delimited. :252 now fails a contiguous grep and an anchored `.*` grep, and both were observed failing in the probe while the positional awk passed.\nClaim RECOMMENDATION 1 (D1): taken. It is closed by the same UA change, and the docstrings at l.3 and l.234 now describe both forged orderings.\nClaim RECOMMENDATION 2 (D2b, \"after\"): taken. Added a visitor-address request.start at V\u22125 s. A \u00b130 s window was observed failing at the C2 assertion, and the draft that opens at the visit passed. The docstrings at l.4 and l.256 now name the decoy.\n</findings_addressed>\n\n<rows>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_21_static_page_visit_logs_phase3.py:252. Each runbook line that names peertube-browser.pages.access.log and contains GET and 200 is run under bash against the real nginx pages log, and prints exactly [the real GET /about.html 200 line]. That log holds three lines: GET /about.html 200, HEAD /about 200, and a GET /about/ 404 whose UA carries both ` status=200 method=GET page=about ` and the real-order ` method=GET status=200 rt=0.000 ` (controls :243, :245, :247).</assertion>\n<expected>{filter_line: [the GET /about.html 200 pages line]} for every such line. Observed with the plan's draft `awk '$1 == \"page=about\" && $5 == \"method=GET\" && $6 == \"status=200\"'`: PASSED.</expected>\n<wrong_implementation>A substring filter such as `grep ' method=GET ' | grep ' status=200 '` lists the forged 404 too (earlier probe). A contiguous real-order grep `grep '^page=about ' | grep ' method=GET status=200 '` and `grep -E '^page=about .* method=GET status=200 rt='` also list the forged 404, and both were observed FAILED at :252. A filter on status alone lists the HEAD line. A runbook with no such line reads {} against the placeholder key.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_21_static_page_visit_logs_phase3.py:292 (JSON) and :293 (text). The pages log holds three visits: 198.51.100.9 at V\u2212120 s, 1.2.3.4 at V with VISIT_ID, and 1.2.3.45 at V+15 s. The Client log is rendered by the real ClientLogFormatter and holds request.start records from 1.2.3.4 at V\u22125 s, V\u221260 s, V+10 s and V+3600 s, and from 1.2.3.45 at V+20 s, each followed by its request.end. The whole runbook, given VISIT_ID, prints exactly one Client record.</assertion>\n<expected>[the formatter's rid-match (V+10 s) request.start], as a parsed dict in JSON and as the text line in text. Observed with the plan's draft: PASSED.</expected>\n<wrong_implementation>A window reaching back (\u00b130 s) also prints the V\u22125 s record: observed FAILED at the C2 assertion. Conversion without -u: FAILED (earlier probe). `ip=$ip` without the trailing space, or jq without the .context.ip test, also prints the 1.2.3.45 record: FAILED. `tail -n 1` for the visit line lands on the neighbour: FAILED. Printing request.end as well gives two records and fails the list equality.</wrong_implementation>\n</row>\n</rows>\n\n<answers>\n1. No. Every exclusion sits inside a positive list equality: :252 requires exactly the real GET line, and :292/:293 require exactly the rid-match record. Controls :243, :245, :247 and :283 prove the input exists. Delete the runbook section and both tests fail at :252 and :292.\n2. No. The expected values come from real nginx output and from real ClientLogFormatter output. Deleting the draft's `$6 == \"status=200\"` test, or its `.ts >= $from`, turns :252 or :292 red.\n3. No. C1 has three inputs, and the forged one now carries two token orderings. C2 has five candidate request.start records plus their request.end records, in two formats.\n4. No. Only `sudo` (runs its command) and `journalctl` (cats a tmp file) are shimmed. Those are system tools, not modules this project owns. The formatter is the real one.\n5. Yes, it collects. No imports or names changed. The edits are a constant, two assert operands, a dict entry and docstrings. The probe module loaded the checkpoint and ran both tests. records now holds 10 rendered lines, and the :283 control compares against len(records).\n6. Yes, all observed. The new forged line was observed from nginx: `\u2026 method=GET status=404 \u2026 ua=\"forger/1 status=200 method=GET page=about method=GET status=200 rt=0.000 forger/1\"`. The V\u22125 s decoy and the \u00b130 s mutant were observed through the probe. The probe file tests/tmp/test_probe_21_p3c.py is emptied (it collects nothing) and needs deleting, since I have no delete tool. The earlier tests/tmp/test_probe_21_p3.py also still needs deleting.\n7. Yes. DEPLOYMENT.md still has no `### Follow an About visit`, so `_runbook()` returns []. The first test passes its controls (observed with the new UA) and fails at :252 on {} against the placeholder key. The second fails at :292 with [] against the rid-match record.\n</answers>",
    "self_check:tests/tmp/test_21_static_page_visit_logs_phase3.py": "<rows>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_21_static_page_visit_logs_phase3.py:252: every runbook line that names peertube-browser.pages.access.log and contains GET and 200 (comments left out) is run under bash against the pages log a real nginx wrote. Each must print exactly the one GET /about.html 200 line. It must not print the HEAD /about 200 line or the GET /about/ 404 whose UA carries \" status=200 method=GET page=about \". If there are no such lines, the result is {}, which is compared against a placeholder key and fails here as well.</assertion>\n<expected>{filter_line: [the real GET /about.html 200 pages line]} for each filter line. Observed: I put the plan's draft runbook (plan \u00a78) into a copy of DEPLOYMENT.md and the test passed (`test_probe[draft-test_forged_user_agent_does_not_move_fields] PASSED`). The only filter line was `sudo awk '$1 == \"page=about\" && $5 == \"method=GET\" && $6 == \"status=200\"' \u2026`. On the current DEPLOYMENT.md, which has no runbook section, it reads {} against {'<a runbook line filtering the pages log for GET and 200>': [the GET line]}, and the test goes red at :252.</expected>\n<wrong_implementation>A substring filter, `sudo grep '^page=about ' \u2026 | grep ' method=GET ' | grep ' status=200 '`. Observed in the probe: that line printed two lines, the real GET 200 line and the forged `\u2026 method=GET status=404 \u2026 ua=\"forger/1 status=200 method=GET page=about forger/1\"` line. The test was red at :252.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_21_static_page_visit_logs_phase3.py:291: in JSON mode, the whole runbook runs with the visit's request_id substituted, journalctl printing real ClientLogFormatter JSON output, and TZ=EST5. The Client records it prints must be exactly [the request.start record of rid-match]: from 1.2.3.4, 10 s after the visit. They must not include rid-before (\u221260 s), rid-late (+3600 s) or rid-neighbour (1.2.3.45, +20 s).</assertion>\n<expected>[{'ts': '2023-11-14T22:13:30.123Z', 'service': 'client-backend', 'event': 'request.start', 'request_id': 'rid-match', 'context': {'ip': '1.2.3.4', \u2026}}]. Observed: the plan's draft runbook passes. On the current DEPLOYMENT.md the output is [] and the test is red at :291.</expected>\n<wrong_implementation>Each of these was observed in the probe and each went red at :291. `date -d` without `-u`: [], because the window lands five hours off. Taking the visit with `tail -n 1` instead of matching on request_id: [the rid-neighbour record from 1.2.3.45]. Dropping `.context.ip == $ip` from jq: [rid-match, rid-neighbour]. Dropping the upper bound `.ts <= $to`: [rid-match, rid-late (2023-11-14T23:13:20.123Z)].</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_21_static_page_visit_logs_phase3.py:292: the same run in text mode, with real ClientLogFormatter text lines. The Client lines it prints must be exactly [the rid-match request.start line].</assertion>\n<expected>['2023-11-14T22:13:30.123Z INFO request.start request started ip=1.2.3.4 method=GET url=http://127.0.0.1:7072/api/videos user_agent=Mozilla/5.0 (X11; Linux x86_64) request_id=rid-match']. Observed: this is the exact line the probe printed, and the plan's draft runbook passes here.</expected>\n<wrong_implementation>A text filter with no delimiter, `grep -F \"ip=$ip\"`. Observed in the probe: it printed the rid-match line and also the `ip=1.2.3.45 \u2026 request_id=rid-neighbour` line, and the test was red at :292 while :291 (JSON) passed. That shows the two modes are judged separately.</wrong_implementation>\n</row>\n</rows>\n\n<answers>\n1. Whole claim: yes, there was a gap, and it is now rewritten. Line 245 (sixth field == status=404) was tagged C1, but it is phase 2's field order and it was already green: the first run got past it. I retagged it as a control. It is the premise that a positional filter reads an unmoved field. C1 is now carried only by :252, which runs the runbook's own filter lines. C2 is carried by :291 (JSON) and :292 (text), using real ClientLogFormatter output. Every decoy the docstring names (\u221260 s, +1 h, 1.2.3.45 at +20 s, plus HEAD 200 and the forged 404 for C1) sits in the input, and an exact-list equality rules each one out.\n2. Absence only: no. Each exclusion is an exact equality against a non-empty expected list. The expected value contains the positive (the real GET line, or the rid-match record), so empty output fails.\n3. Echoed literal: no. The expected value is the formatter's rendering of the rid-match record, and the observed value is whatever the runbook's shell commands select from the full log. The test does none of the selecting itself. Deleting the runbook's `$6 == \"status=200\"` / `$5 == \"method=GET\"` positional awk line turns :252 red, because the filter set becomes empty. Deleting `.context.ip == $ip` or `-u` from the runbook's commands turns :291 red (observed).\n4. One value: no. C1 uses three requests (GET 200, HEAD 200, forged GET 404). C2 uses four request.start records plus four request.end records, three pages lines, and both log formats.\n5. The double: no project-owned module is replaced. `sudo` becomes a passthrough function and `journalctl` becomes `cat` of the tmp log; both are OS tools at a severed layer. nginx and ClientLogFormatter (client/backend/server.py) are the real ones.\n6. It collects: yes. The run collected 2 items and both executed to their claim assertions. All helpers bind, and `runbook` is now a local used by the placeholder control. The collect-only \"no tests\" summary was the runner's display; the real run says `collected 2 items`.\n7. Observed, not predicted: yes, now. I wrote tests/tmp/probe_phase3_runbook.py, which put the plan's draft runbook (plan \u00a78) into a copy of DEPLOYMENT.md, plus six wrong variants, and ran it through the test's own functions with assert rewriting. Draft: both tests PASSED. grep_listing: red at :252 with the forged 404 line listed. text_no_delim: red at :292 with rid-neighbour. no_utc: [] at :291. last_line: rid-neighbour at :291. json_no_ip: +rid-neighbour at :291. no_window_end: +rid-late at :291. Every row's expected and wrong values are taken from that output. ValidateTests cannot delete files, so I emptied the probe to zero bytes; it should be removed.\nRewrite for 8/9: the first run (exit 1) failed both tests at :75, `assert RUNBOOK_HEADING in lines` \u2192 `AssertionError: ### Follow an About visit not in DEPLOYMENT.md`. That is a setup assertion, so nothing was measured. `_runbook()` now returns [] when the heading is missing. :252 folds \"no filter line\" into the C1 equality through a placeholder key. The placeholder control at :277 became `placeholders == 1 or not runbook`, so an absent runbook runs empty and fails at C2.\n8. Red, not green: yes. Final ValidateTests run: `2 failed`, `[exit status 1]`.\n9. Red for the right reason: yes. test_forged_user_agent_does_not_move_fields fails at `tests/tmp/test_21_static_page_visit_logs_phase3.py:252: AssertionError`, `assert {} == {'<a runbook ...be-agent/1\"']}`: no runbook filter line exists yet. test_runbook_finds_visit_and_client_record fails at `:291: AssertionError`, `assert [] == [{'ts': '2023....start', ...}]` with `Right contains one more item: {'ts': '2023-11-14T22:13:30.123Z', \u2026 'event': 'request.start'\u2026}`: the runbook prints nothing because it is not written. All controls before these lines passed: nginx -t, the 200/200/404 one-line-each check, forged tokens present, field 6 == status=404, date TZ, and formatter output recognised.\n10. Observed expected output: yes. The rows' expected values are what the probe printed. The draft runbook passes, and the rid-match JSON and text records are the exact values shown in the probe diffs. The current-tree reds ({} and []) are quoted from the final run. No row was contradicted by a run.\n</answers>\n\n<exemptions>\nnone\n</exemptions>",
    "step_7_implement:3": "<changes>\n### DEPLOYMENT.md\n- Added a `### Follow an About visit` subsection right after the Triage table, before `### Follow one request`. It sits there because the installer fences after \"Follow one request\" have no heading of their own. Had the section gone after them, the next-heading boundary would have pulled `sudo bash scripts/install-service.sh \u2026` into the runbook.\n- The prose says the pages log `/var/log/nginx/peertube-browser.pages.access.log` records every `/about`, `/about/` and `/about.html` request, HEAD requests and 404s included. It says the fields come in a fixed order and the visitor-supplied `x_request_id` and `ua` come last, so filtering goes by position: `$5` is the method, `$6` the status, `$8` the request_id. It also warns that a substring grep for `status=200` matches a forged user agent.\n- Listing block (C1): `sudo awk '$5 == \"method=GET\" && $6 == \"status=200\"' \u2026pages.access.log`.\n- Correlation block (C2):\n  - One `id=<request_id of the visit's pages line>` placeholder.\n  - A `read -r ts ip < <(sudo awk -v id=\"$id\" '$8 == \"request_id=\" id {\u2026}' \u2026)` line that takes the visit's `ts` and `ip` from the pages line. It contains neither `GET` nor `200`, so C1's filter selection does not pick it up as a listing line.\n  - `from`/`to` built as UTC ISO strings with `date -u -d \"@${ts%.*}\" +%Y-%m-%dT%H:%M:%S` plus the log's own `.ms` and `Z`. I avoided `%3N` because this host's `date` prints `.123000000` for it, and `date -d \"@\u2026 + 60 seconds\"` because it is rejected as an invalid date.\n  - A JSON-mode `jq` select on `event == \"request.start\"`, an exact `context.ip`, and `ts` between `from` and `to`.\n  - A text-mode `awk` that checks `$3 == \"request.start\"`, `$6 == \"ip=\" ip` (the message is always the two words `request started`) and a string comparison of `$1` against the window.\n- The window is the 60 s after the visit. The prose says to widen it for a slow visitor and that visitors behind one shared address are not told apart.\n- The section closes by pointing to \"Follow one request\" for the rest of each printed record's request.\n\n### tests/active/test_static_page_visit_logs.py\n- Not touched. It does not exist in the worktree yet, and nothing in this phase's checkpoint needs it. I read the phase's `(EDITED)` entry as belonging to a later step that makes the durable copy.\n\n### tests/tmp/probe_about_runbook_date.py\n- A throwaway probe. It showed how `date` behaves under `TZ=EST5` and ran the checkpoint's two test functions against the new section from a separate path. Both passed, neither was skipped, and nginx ran for the forged-UA case. I have no delete tool, so I emptied the file; it holds no tests now and can be removed.\n</changes>\n\n<inner_tests>\nnone\n</inner_tests>\n\n<unanticipated>\ntests/tmp/probe_about_runbook_date.py \u2014 the probe file I used to observe `date` and the runbook's behaviour. It is empty now but still exists, because I had no tool to delete it; please remove it.\n</unanticipated>\n\n<awaiting_operator>\nnone\n</awaiting_operator>",
    "step_8_i1_refactor": "<refactors>\nnone \u2014 DEPLOYMENT.md was read in full over the changed regions (the \u00a76 site block at lines 433\u2013471 and \"Follow an About visit\" at lines 231\u2013247), and nothing in them could be changed without breaking a gated check or adding new behaviour.\n</refactors>\n\n<left_out>\nMerging the three About locations (`= /about`, `= /about/`, `= /about.html`) into one regex location in DEPLOYMENT.md \u00a76: left out because the gated phase-1 checkpoint parses exact locations and needs exactly one `try_files` in each, so merging them would break that check rather than refactor the code. The repetition is already documented by the rat-tail comment and the access_log comment above the locations.\nRemoving the repeated `set $static_page` and both `access_log` lines from each About location, by using an http-level `map $uri $static_page` plus a server-level `access_log \u2026 peertube_browser_pages if=$static_page;`: left out because I could not be sure of it without a run. It adds a brace-holding `map {}` block outside `server {}` that the checkpoint's `_site_block()`/`_statements()` parsing may not handle. It also moves the About URL set into a second place that the rat-tail mapping comparison does not check, and I have not seen how nginx handles the pages log for non-About routes under `if=`.\nNot refactors, but for whoever owns the next step: (1) `tests/active/test_static_page_visit_logs.py`, which the rat-tail comment names, does not exist in the worktree yet; promoting the gated checkpoints is up to the workflow. (2) `.un/skills/devsecops/config.json` has no `test_static_page_visit_logs.py` group. It should list DEPLOYMENT.md, client/frontend/vite.config.ts, client/frontend/dev-pages/about.template.html and client/backend/server.py (the source of ClientLogFormatter). (3) Earlier steps left probe files in tests/tmp/ that I have no tool to delete: probe_pages_log.py and probe_about_runbook_date.py (emptied), and probe_21_pages_log.py, probe_21_about_block.py, test_probe_21_p1_nginx.py, test_probe_21_p3.py and test_probe_21_p3c.py. (4) The step's \"What the pass is measured against\" section came through as the literal placeholder `{rat_tail_rules}`, so the pass was checked against the role's rat-tail rule only.\n</left_out>\n\n<needs_fresh_red>\nnone\n</needs_fresh_red>\n\n<observation>\nFrom reading the code only, without a run: the About site block and the runbook are already the smallest form the gated checkpoints allow, so this pass changed no file.\n</observation>",
    "step_9_triage": "<docs>\n<doc path=\"DEPLOYMENT.md\" update=\"yes\">\nThe \u00a76 site block and the Triage \"Follow an About visit\" commands were delivered and are correct. The prose around them is now incomplete or wrong. Edit the prose only. The block and the fenced runbook commands are gated and must not change.\n- **\u00a73 \"Build the client\" (lines 318-322).** \"nginx serves `dist/` through `try_files`, and a page missing from the document root is a 404\" now holds for every page except `about`. Say that About is built under `dist/dev-pages/`: `about.html` when the local override exists, otherwise `about.template.html`. Say that it is reached at `/about`, `/about/` and `/about.html` only through the \u00a76 About locations. Adding another informational page means adding one more exact location of the same shape.\n- **\u00a76 prose after the block (line 504).** \"`log_format` stays outside `server {}`\" must cover the two formats, `peertube_browser` and `peertube_browser_pages`. Add the following, beside the `proxy_set_header` repetition note:\n  - The three exact About locations serve `/dev-pages/about.html`, then `/dev-pages/about.template.html`, then 404, in vite's override-then-template order.\n  - Each one sets `$static_page` and lists both `access_log` lines, because a location-level `access_log` replaces the server's.\n  - They declare no `add_header`, so they inherit the server CSP, which is About's only CSP (the template has no meta CSP). Adding an `add_header` there would drop it.\n  - The new file `/var/log/nginx/peertube-browser.pages.access.log` is covered by the Debian/Ubuntu `/var/log/nginx/*.log` logrotate rule.\n  - Direct requests to `/dev-pages/about*.html` go through `location /` and write no pages line.\n  - Existing hosts merge in the new `log_format` line and the three locations, then run `nginx -t` and reload. They must not overwrite a certbot-edited file.\n- **\u00a76 Verify (lines 516-522).**\n  - Add `curl -I http://localhost/about`: expect 200 with a `Content-Security-Policy` header. `/about/` and `/about.html` can be listed too.\n  - Add a `sudo tail` of the pages log. The `curl -I` line logs as `method=HEAD`.\n  - Add a hint: a 404 on `/about` means \u00a76 was not re-applied or the document root has no `dev-pages/about*.html`.\n- **\u00a76 TLS (lines 566-574).** Warn that `certbot --nginx` edits the site file in place, so re-applying \u00a76 by copying the whole block over it drops TLS. Either merge the changes in or re-run certbot afterwards.\n- **Triage \"Follow an About visit\" (lines 231-248).** The requirements' runbook is only partly there. Add the following, in prose and one extra command:\n  - The step that finds the visit's line in the main access log by its id: `sudo grep \"request_id=$id\" /var/log/nginx/peertube-browser.access.log`.\n  - Caveat: the id is not shared with any app record, so correlation is probabilistic. NAT and shared IPs make it so.\n  - Caveat: the Client's `ip` is resolved through `X-Forwarded-For`/`TRUSTED_PROXIES`, so it equals nginx's `$remote_addr` only when nginx is the sole proxy. Behind a CDN or load balancer, `$remote_addr` is that layer's address.\n  - Caveat: the nginx `time=` field is server-local with an offset, while app `ts` is UTC. The `from`/`to` lines normalise from `ts=` (`$msec`) for that reason.\n  - Caveat: in text mode, the `ip` field and the unquoted `user_agent` make the match weaker than the JSON match.\n  - Caveat: bots and crawlers appear in the log, and the user-agent is the only filter. Name issue 18's beacon endpoint (`docs/project/issues/18-about-outbound-click-tracking.md`) as the upgrade path for counting human visits.\n- **Triage \"What each log is for\" (lines 261-263).** Add a bullet for the pages log: one line per About request, with page marker, ms timestamp, IP, method, status, request time, request id, URI, incoming `X-Request-ID` and user agent, joined to its main-log line by `request_id`.\n- **\u00a72 `LOG_FORMAT` paragraph (line 116), optional.** Point to \"Follow an About visit\" next to the existing \"Follow one request\" pointer.\n- **\u00a77 Verify page list (lines 603-606), optional.** Add `/about.html`, which every page's nav links to and which 404ed in prod before this build.\n- **Triage table, optional.** Add a row: `/about` returns 404 \u2192 re-apply \u00a76, or run `scripts/sync.sh` so `dev-pages/about*.html` is in the document root.\n</doc>\n<doc path=\"client/frontend/README.md\" update=\"yes\">\n\"Local About Overrides\" (lines 36-39) names the source files but not how prod serves them. Add that prod nginx serves whichever file was built at `/about`, `/about/` and `/about.html`, the `dev-pages/about.html` override first and the template otherwise (`DEPLOYMENT.md` \u00a76). Add that an override must use root-absolute URLs because the same file is served at `/about/`, and that it gets only the server's CSP header.\n</doc>\n<doc path=\"docs/project/issues/21-static-page-visit-logs.md\" update=\"yes\">\nStill `Status: enhancement, needs-triage` with an empty `## Comments`. At completion:\n- set `Status: enhancement, complete`;\n- add a delivery comment naming `docs/project/plans/22-21-static-page-visit-logs.md`. It should say what was delivered: About served at `/about`, `/about/` and `/about.html` in prod via \u00a76, the `peertube_browser_pages` log at `/var/log/nginx/peertube-browser.pages.access.log`, and the \"Follow an About visit\" runbook. It should also say what was scoped out: pages other than About, and the beacon, which is deferred to issue 18;\n- move the file to `docs/project/issues/archive/` per `docs/project/issue-tracker.md`, leaving no duplicate in `issues/`.\n</doc>\n<doc path=\"docs/project/issues/plan.md\" update=\"yes\">\n- **Lane 5c (line 98).** It lists 21's files as \"nginx docs, the About template, one Client endpoint\". For 21 that is only the nginx docs (`DEPLOYMENT.md`); the template and the endpoint belong to 18. Mark 21 delivered with the plan path.\n- **P5 row (line 42).** \"19 and part of 20 are already delivered\" is stale. 19, 20 and 21 are delivered, and 18 remains.\n</doc>\n<doc path=\"docs/project/issues/18-about-outbound-click-tracking.md\" update=\"yes\">\nAdd a comment. Issue 21's runbook names 18's beacon endpoint as the upgrade path for pageview counting, so 18's endpoint design should allow a page-view event type as well as outbound clicks. Line 14 plans a click-specific `/api/analytics/outbound-click`. 21 adds no endpoint, so the two do not duplicate each other.\n</doc>\n<doc path=\"docs/project/roadmap.md\" update=\"no\">\nNo change needed. The Delivered list has no bullet for the sibling logging issues 19 and 20, so the convention does not call for one for 21. The Logging chain line (`19` -> `20` -> `21`) is still accurate.\n</doc>\n<doc path=\"CONTEXT.md\" update=\"no\">\nNo change needed. The \"Request id\" entry is still true: About lines carry nginx's `$request_id`, but no app record shares it. The scope is About only, so no new glossary term is warranted.\n</doc>\n<doc path=\"client/README.md\" update=\"no\">\nNo change needed. Its `TRUSTED_PROXIES` and `request.start` statements, which the runbook relies on, are unchanged and still true, and it makes no claim about About or the nginx logs.\n</doc>\n<doc path=\"docs/project/adr/0002-trusted-proxy-client-address.md\" update=\"no\">\nNo change needed. The runbook's IP caveat restates this ADR's resolution rule and does not change it. The build touches neither the Client backend nor the proxy headers.\n</doc>\n<doc path=\"docs/project/adr/0004-cors-opt-in-by-origin.md\" update=\"no\">\nNo change needed. Prod nginx still serves everything on one origin. The About locations add no headers and no cross-origin path.\n</doc>\n<doc path=\"docs/project/adr/0009-engine-blue-green-through-nginx-upstream-snippet.md\" update=\"no\">\nNo change needed. Only the public site file changed. The upstream snippet and the 7079 listener are untouched, and \u00a76 line 526 (\"leave the public site file above as it is, since nothing here changes it\") is still accurate.\n</doc>\n</docs>\n\n<adr_conflicts>\nnone\n</adr_conflicts>",
    "step_9_i2_update:DEPLOYMENT.md": "<changes>\nI updated the prose in `DEPLOYMENT.md` to match what the build delivered: how About is served, the pages log, the About runbook caveats, and checks and warnings for operators. I didn't change the \u00a76 nginx site block or the fenced runbook commands, since the tests check both.\n\nI checked the claims against the code: `vite.config.ts` (`aboutSourcePath`, `rewriteToAbout`), `dev-pages/` (no `<meta>` CSP), and the Client's `request.start` record and text-mode output in `client/backend/server.py`.\n\n- **\u00a72 `LOG_FORMAT` paragraph:** added a pointer to \"Follow an About visit\" next to the \"Follow one request\" pointer.\n- **\u00a73 Build the client:** About is built under `dist/dev-pages/`, as `about.html` when the local override exists and `about.template.html` otherwise, never as `dist/about.html`. It is reached at `/about`, `/about/` and `/about.html` only through the \u00a76 About locations. Adding another informational page means one more exact location of the same shape.\n- **\u00a76 prose after the block:**\n  - The `log_format` note now covers both `peertube_browser` and `peertube_browser_pages`.\n  - A new paragraph on the About locations covers:\n    - the order they serve files in: `dev-pages/about.html`, then `dev-pages/about.template.html`, then 404, the same choice vite makes;\n    - why each one sets `$static_page` and repeats the main `access_log` line;\n    - the CSP: they inherit the server's header, which is About's only CSP, and an `add_header` in one of them would drop it;\n    - log rotation: the Debian/Ubuntu `/var/log/nginx/*.log` rule covers the new file;\n    - direct `/dev-pages/about*.html` requests go through `location /` and write no pages line.\n  - A note for hosts that already run the site: merge the new lines in rather than overwriting the file certbot edited, then `nginx -t` and reload.\n- **\u00a76 Verify:** added `curl -I http://localhost/about` (expect 200 with the CSP header) and a `sudo tail` of the pages log (expect a `method=HEAD` line). Added a hint for what a 404 on `/about` means.\n- **\u00a76 TLS:** `certbot --nginx` edits the site file in place, so copying the whole block over it drops TLS. Merge the changes in, or re-run certbot afterwards.\n- **Triage table:** a new row for `/about*` answering 404, pointing to merging the \u00a76 About locations or running `scripts/sync.sh`.\n- **Follow an About visit:**\n  - The main-log lookup by request id is written inline in the prose (`sudo grep \"request_id=$id\" \u2026access.log`) rather than as a new fenced block, so the tested blocks stay unchanged.\n  - A Caveats list covers:\n    - the request id is not shared with app records, so matching by IP and time is probabilistic under NAT or shared addresses;\n    - the Client's `ip` comes from `X-Forwarded-For`/`TRUSTED_PROXIES`, so it equals `$remote_addr` only when nginx is the sole proxy;\n    - the pages log's `time=` is local time with an offset while app `ts` is UTC, which is why the window is built from `ts=`;\n    - the text-mode match goes by field position over unquoted values, so it is looser than the JSON match;\n    - bots and crawlers appear in the log, and issue 18's beacon endpoint is the way to count human visits.\n- **What each log is for:** a bullet for the pages log listing its fields, joined to the main log by `request_id`.\n- **\u00a77 Verify:** added `/about.html` to the list of pages to open.\n</changes>\n\n<not_on_checklist>\nnone\n</not_on_checklist>",
    "step_9_i2_update:client/frontend/README.md": "<changes>\n\"Local About Overrides\" now says how prod serves the built About page, that overrides need root-absolute URLs, and which CSP applies.\n\n- New bullet: the build puts whichever source it used under `dist/dev-pages/`. Prod nginx serves it at `/about`, `/about/` and `/about.html`, trying the `dev-pages/about.html` override first and the template second. For the locations and the visit log it points to `DEPLOYMENT.md` sections 3 and 6 rather than repeating them.\n- New bullet: an override must use root-absolute URLs. The same file is also served at `/about/`, so a relative URL would resolve under `/about/`.\n- New bullet: the About page's only CSP is the server's `Content-Security-Policy` header, so an override must work under it.\n\nChecked against the code:\n- In `vite.config.ts`, `aboutSourcePath` and `rewriteToAbout` give the override-then-template order and the three URLs.\n- The `DEPLOYMENT.md` \u00a76 About locations serve those files and have no `add_header`. \u00a7519 says the template has no meta CSP.\n- The template's own links are root-absolute, for example `/favicon.png` and `/src/videos.css`.\n</changes>\n\n<not_on_checklist>\nnone\n</not_on_checklist>",
    "step_9_i2_update:docs/project/issues/21-static-page-visit-logs.md": "<changes>\nIssue 21 marked delivered and copied to `docs/project/issues/archive/21-static-page-visit-logs.md` with a delivery comment. **The original at `docs/project/issues/21-static-page-visit-logs.md` still exists and needs deleting.** I have no tool that deletes files, so until it goes there are two copies.\n\n- **Status:** changed `Status: enhancement, needs-triage` to `Status: enhancement, complete`.\n- **Delivery comment under `## Comments`:** a single bullet, in the same style as the archived issue 20. It covers:\n  - It names `docs/project/plans/22-21-static-page-visit-logs.md` and says the delivery is nginx config and docs only.\n  - Prod serves About at `/about`, `/about/` and `/about.html` through three exact locations in `DEPLOYMENT.md` \u00a76. Before this, About returned 404 in prod.\n  - Each About request writes one line to `/var/log/nginx/peertube-browser.pages.access.log` in the `peertube_browser_pages` format, carrying the `page=about` marker and the incoming `X-Request-ID` (`-` when absent). It also writes its usual main-log line, and the two are joined by `$request_id`.\n  - The \"Follow an About visit\" Triage runbook matches a visit to the visitor's records by client IP and a time window. No request id is shared with app records, so the match is probabilistic. For fields, commands and caveats the comment points to `DEPLOYMENT.md` instead of repeating them.\n  - Left out of this build: other pages (their API calls already show in app logs) and the pageview beacon, which the runbook names as the upgrade path using issue 18's beacon endpoint.\n- **Checked against `DEPLOYMENT.md`:** the log format (line 449), the three About locations (lines 467\u2013483) and the \"Follow an About visit\" heading (line 232).\n- **Unchanged:** the rest of the issue body (Problem, Proposed solution, Validation, Related).\n</changes>\n\n<not_on_checklist>\ndocs/project/issues/archive/21-static-page-visit-logs.md: new file. `docs/project/issue-tracker.md` says a delivered issue moves to `issues/archive/`, so this is the moved copy of the checklist file. The original `docs/project/issues/21-static-page-visit-logs.md` must be deleted (git rm) so only one copy remains; I have no tool that deletes files.\n</not_on_checklist>",
    "step_9_i2_update:docs/project/issues/plan.md": "<changes>\nplan.md: P5 row now says 19, 20 and 21 are delivered and 18 remains; lane 5c splits the file list between 21 and 18 and marks 21 delivered with its plan path.\n\n- **P5 row (line 42).** \"19 and part of 20 are already delivered (see triage)\" now reads \"19, 20 and 21 are delivered, and 18 remains.\" I checked this against the tree: `docs/project/issues/archive/{19,20,21}-*.md` all carry `Status: enhancement, complete`, and 18 is still `needs-triage` in `issues/`.\n- **Lane 5c (line 98).** The main-files cell now reads \"21: the nginx docs (`DEPLOYMENT.md`). 18: the About template, one Client endpoint\". 21 delivered no template or endpoint change. The depends-on cell keeps `20` and adds \"21 delivered, see `docs/project/plans/22-21-static-page-visit-logs.md`\". That plan file exists at that path.\n\nI left some text alone because it was outside this item's checklist. These parts of the file are still stale for 20: lane 4c's \"(19 delivered)\", which doesn't mark 20 delivered, and the Triage recommendation \"**20 is partly delivered.**\"\n</changes>\n\n<not_on_checklist>\nnone. One thing to check: `docs/project/issues/20-request-lifecycle-logs.md` (`needs-triage`) is still in `issues/` next to its `complete` copy in `issues/archive/`. That looks like a duplicate left over from the issue-20 build. I didn't touch it.\n</not_on_checklist>",
    "step_9_i2_update:docs/project/issues/18-about-outbound-click-tracking.md": "<changes>\nAdded a comment to issue 18: issue 21 names this issue's beacon endpoint as the way to count pageviews, so the endpoint should also accept a page-view event type.\n\n- I added one comment under `## Comments`, headed \"Issue 21 names this endpoint as its pageview upgrade path\". It follows the `### heading` plus paragraph format the other issues use.\n- The comment says issue 21 (`docs/project/issues/archive/21-static-page-visit-logs.md`) logs About visits in nginx and adds no endpoint, so the two issues don't overlap.\n- It cites the \"Follow an About visit\" runbook in `DEPLOYMENT.md`: bots and crawlers show up in the nginx pages log, and counting human visits would need a pageview beacon sent to this issue's endpoint. I checked `DEPLOYMENT.md` line 258, which points to this issue's beacon endpoint.\n- It notes that the endpoint planned above only handles clicks (`/api/analytics/outbound-click`, `outbound_click_events`). The design should also accept a page-view event type so pageviews don't need a second endpoint.\n- `Status`, the proposed solution, Validation and Related are unchanged. This issue isn't delivered, and the Related line still correctly separates event analytics from request-log visibility.\n</changes>\n\n<not_on_checklist>\nnone\n</not_on_checklist>"
  },
  "requirements": "### Purpose\n\nMake visits to the About page visible and attributable. About is the only purely informational page: it has no scripts and makes no API calls, so a visit never reaches the Client backend or the Engine and leaves no app log record. Today it does not even serve in prod (see \"Serve About in prod\"). The build gives operators a dedicated, greppable record of About visits from nginx, and a runbook that ties a visit to the same visitor's app traces. This is request-log visibility. It is not event analytics: About outbound-click analytics belong to `docs/project/issues/18-about-outbound-click-tracking.md`, and nothing here may duplicate that.\n\n### Scope decisions (operator-approved)\n\n- Only the About page counts as an \"informational static page\": URLs `/about`, `/about/` and `/about.html`. Other pages (index, videos, search, likes, video-page, channels) are out of scope, because their API calls already show in app logs. Adding another informational page later means adding one more exact-match location of the same shape.\n- The visit log is a separate file, and it does not replace the existing access log: About requests are written to both.\n- The optional client-side pageview beacon is out of scope. It is named in the runbook as the upgrade path, riding on the beacon endpoint that issue 18 introduces, and not as a second endpoint.\n- No Python, JavaScript or HTML change in the app or frontend. The deliverable is the documented nginx configuration and the runbook.\n\n### Serve About in prod\n\n- Current state, verified in the tree: `client/frontend/vite.config.ts` builds the `about` input from `client/frontend/dev-pages/about.html` when that local, untracked file exists, otherwise from `client/frontend/dev-pages/about.template.html`. The build output is therefore `dist/dev-pages/about.html` or `dist/dev-pages/about.template.html`, and there is never a `dist/about.html`. Every page's nav links to `/about.html`. The `/about`, `/about/`, `/about.html` rewrite exists only in vite's dev and preview servers. The public nginx site documented in `DEPLOYMENT.md` \u00a76 has only `location / { try_files $uri $uri/ =404; }`, so `/about.html` returns 404 in prod. The operator confirmed it really 404s.\n- Requirement: the public nginx site (`/etc/nginx/sites-available/peertube-browser` as documented in `DEPLOYMENT.md` \u00a76) gets exact-match handling for `/about`, `/about/` and `/about.html`. It serves `/dev-pages/about.html` if present in the document root, otherwise `/dev-pages/about.template.html`, otherwise 404. Each of the three URLs answers 200 with the built About page.\n- The About response must still carry the server-level `Content-Security-Policy` header. In nginx, a location that declares any `add_header` inherits none from the server level, so the About location must either declare none or repeat the CSP.\n- All other routes (`location /`, `/api/`, `/recommendations`, `/videos/similar`, `/client/`) behave exactly as before.\n\n### Dedicated About visit log\n\n- Every request handled by the About location writes one line to a new file, `/var/log/nginx/peertube-browser.pages.access.log`, in a new `log_format` defined beside `peertube_browser`. Like that one, it sits outside `server {}` because the site file is included in nginx's `http` block.\n- The same request also still writes its usual line to `/var/log/nginx/peertube-browser.access.log` in the `peertube_browser` format. In nginx, an `access_log` inside a location replaces the server-level one, so the About location must list both logs explicitly.\n- Each pages-log line carries:\n  - an explicit marker identifying the page (`page=about`);\n  - a timestamp with millisecond precision that can be compared with the apps' `ts` (UTC `YYYY-MM-DDTHH:MM:SS.mmmZ`), e.g. nginx `$msec` and/or `$time_iso8601`;\n  - client IP (`$remote_addr`);\n  - method;\n  - the URL as requested, path plus query (`$request_uri`);\n  - response status;\n  - response time (`$request_time`);\n  - user-agent;\n  - nginx's `$request_id`, the same id the visit's line in the main access log carries, so the two lines of one visit can be joined;\n  - the incoming `X-Request-ID` request header when the client or an upstream layer sent one (`$http_x_request_id`), with `-` when absent. This is the \"preserve when available\" part of the request. Nothing is proxied from this location, so there is nothing to propagate onward.\n- Every method and status that reaches the location is logged, including `HEAD`, `304` and `404`. The method and status fields let a reader filter.\n- Log rotation: the new file sits under `/var/log/nginx/` with a `.log` suffix, so the Debian/Ubuntu nginx logrotate rule covers it. The docs state this.\n\n### Runbook\n\nA new Triage entry in `DEPLOYMENT.md`, beside \"Follow one request\", that:\n- lists About visits from `/var/log/nginx/peertube-browser.pages.access.log` (grep for the marker; filter by status or method);\n- finds the same visit's line in the main access log by its `request_id`;\n- correlates a visit with the visitor's app traces by client IP plus a time window: Client backend `request.start` records whose `ip` equals the visit's client IP and whose `ts` falls within a stated window after the visit. It gives the commands in the same `journalctl \u2026 | jq` style as \"Follow one request\", with the `LOG_FORMAT=text` grep variant. From a Client record, the existing \"Follow one request\" steps reach the Engine;\n- states the caveats:\n  - an About visit shares no request id with later API calls: About makes no API calls, and nginx assigns each request its own `$request_id`. Correlation with app traces is by IP and time only, and therefore probabilistic (shared IPs and NAT).\n  - The Client's `ip` is resolved through `X-Forwarded-For` and `TRUSTED_PROXIES`, so it equals nginx's `$remote_addr` only when nginx is the sole proxy. Behind a CDN or load balancer, nginx's `$remote_addr` is that layer's address.\n  - The nginx timestamp and the app `ts` differ in format and time zone, so the reader must normalise to UTC.\n  - Bots and crawlers appear in the log. The user-agent is the only filter, and cleaner human-intent counting is the beacon upgrade path.\n\n### Documentation to update\n\n- `DEPLOYMENT.md` \u00a76, nginx (production): the site block gains the About location and the second `log_format`, with prose explaining the About mapping, why both `access_log` lines are repeated, the CSP inheritance rule, and the new file.\n- `DEPLOYMENT.md` \u00a73: the page list and the `try_files` note say that About is built under `dev-pages/` and served at `/about`, `/about/` and `/about.html` through the mapping.\n- `DEPLOYMENT.md` Triage: the runbook above. The \"What each log is for\" text mentions the pages log.\n- `docs/project/issues/21-static-page-visit-logs.md`: a delivery comment and a status update at completion, per `docs/project/issue-tracker.md` and `docs/project/triage-labels.md`.\n- Any other doc that states About is served at `/about.html` or lists the nginx logs (e.g. `client/frontend/README.md` \"Local About Overrides\"), checked during the impact inventory.\n\n### Validation\n\n- With the documented config, a request to each of `/about`, `/about/` and `/about.html` returns 200 with the built About page and the CSP header.\n- Each such request produces exactly one line in `peertube-browser.pages.access.log` carrying every field listed above, plus one line in `peertube-browser.access.log` with the same `request_id`.\n- Requests to other pages and API routes produce no pages-log line, and their main-log lines are unchanged.\n- Following the runbook against a visit and a subsequent API request from the same client finds the visit and that client's `request.start` record within the window.\n- Where an `nginx` binary is available, the documented site config passes `nginx -t`. Where it is not, any automated check must skip rather than fail.\n- The existing suite stays green.\n\n### Baseline suite state\n\nPre-build suite exited 0, baseline variant false (selected 1 of 46 test groups: `test_search_fusion.py`, 10 passed). Active tests are in `tests/active`, working tests in `tests/tmp`, archive in `tests/archive`. Run record: `tests/last_test_validation.json`; output: `tests/last_test_output.txt`. Project dir: `/home/enduser/code/PeerTube-browser/.worktrees/21`.\n\n### Out of scope\n\n- Client-side pageview beacon and any new API endpoint (upgrade path: issue 18's beacon endpoint).\n- Visit logging for pages other than About.\n- Outbound-click tracking (issue 18).\n- Any change to the Client backend, the Engine, their logging, or the 127.0.0.1:7079 Engine listener.\n- Changing the vite build layout of About: the mapping lives in nginx.",
  "approved": [
    "1",
    "2",
    "3",
    "3",
    "3",
    "5",
    "6",
    "9"
  ],
  "initial_solution": "### Approach\n\nThe whole deliverable is documentation: the nginx site block in `DEPLOYMENT.md` \u00a76 and a new Triage runbook. No app, frontend or build change. I read the tree to check the premises. `vite.config.ts` builds the `about` input from `dev-pages/about.html` or `dev-pages/about.template.html`, and the vite rewrite set is exactly `/about`, `/about/`, `/about.html`. The template uses only root-absolute links (`/favicon.png`, `/src/videos.css`, which the build turns into `/assets/\u2026`, and nav links like `/about.html`), so serving the built file at `/about/` does not break any relative URL. The public site has only `location /`, the server-level `access_log` and the `add_header Content-Security-Policy \u2026 always`.\n\n**Serving About (one location holds the logic, two exact aliases point to it).** The site block gains `location = /about.html`, which holds everything About needs:\n- `set $static_page about;` names the page;\n- `try_files /dev-pages/about.html /dev-pages/about.template.html =404;` serves the file in the same order vite builds it;\n- the two `access_log` lines (main log in `peertube_browser`, pages log in the new format);\n- no `add_header`, so the server-level CSP is inherited.\n\nTwo more exact locations, `location = /about` and `location = /about/`, contain only an internal `rewrite ^ /about.html last;`. That restarts the location search inside the same request, so the request ends in the About location. Exact-match (`=`) locations win over the `location /` prefix, and the other routes' locations are untouched, so they behave exactly as before. How each requirement is met:\n- **200 on all three URLs.** `try_files` serves a found file in the current location, which also answers `HEAD` and conditional requests (`304`). When neither file exists, it answers nginx's own 404, and that request is still logged in this location.\n- **CSP.** The About location declares no `add_header`, so the server-level CSP is inherited. The `always` flag means the 404 case carries it too.\n- **One line per log per visit.** nginx writes access logs once per request, in the log phase, using the location where processing ended. A rewritten `/about` therefore writes exactly one line to each file. `$request_id` and `$request_uri` are fixed per request, so the logged URL is still `/about` as requested, query included.\n\n**The pages log format.** A second `log_format`, `peertube_browser_pages`, sits directly under `peertube_browser`, outside `server {}`. It uses the same `key=value` style the main format already uses for `request_id=`, roughly in this order:\n- `page=$static_page` \u2014 the marker;\n- `ts=$msec` \u2014 epoch seconds with milliseconds, UTC by definition;\n- `time=$time_iso8601` \u2014 readable local time;\n- `ip=$remote_addr`;\n- `method=$request_method`;\n- `uri=\"$request_uri\"`;\n- `status=$status`;\n- `rt=$request_time`;\n- `request_id=$request_id`;\n- `x_request_id=$http_x_request_id` \u2014 nginx writes `-` for an empty or absent variable, which gives the \"`-` when absent\" rule with no extra config;\n- `ua=\"$http_user_agent\"`.\n\nThe marker comes from a per-location variable, not a literal in the format. Adding a second informational page then means one more location of the same shape (its own `set`, `try_files` and the same two `access_log` lines), with no second `log_format`.\n\n**Why both logs are listed.** The About location lists `access_log /var/log/nginx/peertube-browser.access.log peertube_browser;` and `access_log /var/log/nginx/peertube-browser.pages.access.log peertube_browser_pages;`. A location-level `access_log` replaces the inherited one, so without the first line About would drop out of the main log. \u00a76 prose explains this next to the existing note on why `proxy_set_header` is repeated. It also says that `/var/log/nginx/*.log` is covered by the Debian/Ubuntu nginx logrotate rule, and that its postrotate signal reopens the new file as well.\n\n**Runbook.** A new Triage subsection, \"Follow an About visit\", goes right after \"Follow one request\":\n1. List visits: `sudo grep 'page=about'` on the pages log, narrowed with `grep ' status=200 '` or `' method=GET '`, or `awk` on those fields.\n2. Find the visit's main-log line: `sudo grep \"request_id=$id\"` on `peertube-browser.access.log`, the same command \"Follow one request\" uses.\n3. Correlate with the Client: take the visit's `ts=` (`$msec`) and `ip=`, and turn the epoch into the apps' format with `date -u -d @<msec> +%Y-%m-%dT%H:%M:%S.%3NZ` for the window start and start plus the window for its end. Then filter with `journalctl -u peertube-client.service -o cat | jq -cR --arg ip \u2026 --arg from \u2026 --arg to \u2026 'fromjson? | select(.event == \"request.start\" and .context.ip == $ip and .ts >= $from and .ts <= $to)'`. The apps' `ts` is fixed-width UTC, so comparing the strings orders correctly and needs no date parsing in jq. The window is stated as 5 minutes by default and widened by hand. The `LOG_FORMAT=text` variant greps `request.start` and `ip=$ip`, then compares the leading `ts` field as a string with `awk`.\n4. From a matched record's `request_id`, the existing \"Follow one request\" steps reach the Engine.\n\nThe runbook lists the four required caveats: no shared id; the IP is resolved through `TRUSTED_PROXIES`; formats and time zones differ, which the `date -u` step handles; bots are filtered only by user-agent, and the upgrade path is a pageview beacon on issue 18's endpoint, not a second endpoint. \"What each log is for\" gains a bullet for the pages log.\n\n**Other docs.**\n- `DEPLOYMENT.md` \u00a73: the page list and the `try_files` paragraph say that About is built under `dev-pages/` and reached at `/about`, `/about/`, `/about.html` through the \u00a76 mapping.\n- \u00a76 \"Verify\": add `curl -I http://localhost/about` (200, CSP header present) and a `tail` of the pages log.\n- `client/frontend/README.md` \"Local About Overrides\": one line saying that prod nginx serves whichever file was built at those three URLs.\n- Issue 21: delivery comment and status at completion.\n- No other doc in the tree states the About URL or lists the nginx logs. `CONTEXT.md`, `client/README.md` and `README.md` mention nginx only for the request id and the 7079 listener.\n\n**Validation hook (for the test step, sketched here only).** A test in `tests/active` pulls the fenced nginx block out of `DEPLOYMENT.md`. It swaps `root`, the log paths and `listen` for temp-dir values, wraps the block in a minimal `http {}` config, and runs `nginx -t`. Where possible it also starts nginx on a free high port to check the three 200s, the CSP header, the exact line counts in both logs, matching `request_id`s, and that `/` and `/api/\u2026` produce no pages line. It is skipped when `shutil.which(\"nginx\")` is None. The runbook check uses a synthetic pages line plus a synthetic Client JSON record.\n\n### Alternatives considered\n\n- **One regex location `~ ^/about(/|\\.html)?$`.** It is one block, but the requirement asks for exact-match handling, and regex locations are matched in file order, which makes later edits easier to get wrong. Rejected.\n- **Three full copies of the About body, one per exact URL.** No rewrite, but the two `access_log` lines, `set` and `try_files` would have to stay identical in three places. Missing one `access_log` line silently drops that URL from the main log. Rejected for that drift risk; the rewrite aliases are one line each.\n- **`return 301` from `/about` and `/about/` to `/about.html`.** The requirement says each URL answers 200, and a redirect doubles the log lines per visit. Rejected.\n- **A literal `page=about` in the format.** One variable fewer, but a second page would need a second `log_format`. Rejected for the `set` variable.\n- **Building an ISO UTC millisecond timestamp in nginx** (a `map` on `$time_iso8601` plus the fraction of `$msec`). `$time_iso8601` is the server's local time, so the result is UTC only when the host's TZ is UTC, and doing better needs njs or a third-party module. Rejected. This is a deliberate simplification: the line carries `$msec`, which is exact UTC, and the runbook converts it in one `date -u` call. Upgrade path: if operators find this tedious, add the `map` on hosts that run in UTC.\n- **A `map $uri` choosing the marker.** `$uri` changes to the `dev-pages` path after `try_files`, and `$request_uri` includes the query. Rejected.\n- **Adding `$request_id` to the About response headers.** That needs an `add_header` in the location, which would then have to repeat the CSP, and nothing reads the header. Not done.\n\n### Gotchas and risks\n\n- **Rewrite semantics.** `last` keeps one request: one `$request_id`, one log phase. Using `break` or `redirect` instead would break this, so the prose says not to change it.\n- **Direct hits on `/dev-pages/about*.html`** still go through `location /` and leave no pages line. Nothing links there. The docs state it as a limitation rather than hiding the path.\n- **Escaping.** The default escape in `log_format` writes a `\"` in the user-agent or URI as `\\x22`, so the quoted fields stay parseable. The runbook's greps match on `key=` tokens, not positions.\n- **IP text form.** The Client's `ip` and nginx's `$remote_addr` normally render the same, but IPv6 and IPv4-mapped forms can differ. This is noted under the proxy caveat.\n- **Stale dev-pages files.** If both dev-pages files existed in the document root, `try_files` would prefer the override, as vite does. `rsync --delete` keeps only what the last build produced.\n- **Existing deployments.** The site file is copied by hand, so existing hosts get About only after the operator re-applies \u00a76 and reloads. The \u00a76 text says so.\n- **The automated nginx test** runs nginx without root and with temp paths. Its warning about the `user` directive is harmless. Hosts without nginx skip the test, as the requirements ask.\n\n### Tradeoffs asked of the operator\n\n- The timestamp is `$msec` (epoch milliseconds) plus `$time_iso8601` (local time, seconds only), not a ready UTC ISO-ms string. Comparing a visit with app `ts` takes one documented conversion step.\n- Correlation is by IP plus time window only, so it is probabilistic. A NAT or shared IP can match the wrong visitor's records, and a visitor who leaves About without further API calls has none. The beacon is the named upgrade path.\n- Bots are counted in the log and are filtered only by user-agent.\n- About traffic writes two log lines per request. The extra volume is negligible.",
  "conflicts": "none",
  "impacts": "<impacts>\n<impact path=\"DEPLOYMENT.md\" element=\"\u00a76 nginx (production), the fenced `/etc/nginx/sites-available/peertube-browser` block: the `log_format` line (line 416)\">\n**What changes.** A second one-line, single-quoted `log_format peertube_browser_pages '\u2026';` goes directly under `log_format peertube_browser` (line 416), outside `server {}`. Its tokens use the same `key=value` style the main format already uses for `request_id=`/`upstream=`/`rt=`: `page=$static_page ts=$msec time=$time_iso8601 ip=$remote_addr method=$request_method uri=\"$request_uri\" status=$status rt=$request_time request_id=$request_id x_request_id=$http_x_request_id ua=\"$http_user_agent\"`.\n\n**What depends on it.** Only the new About location refers to it. It names `$static_page`, which nginx resolves at config load, so that variable must be declared by a `set` somewhere in the config. The plan's `set $static_page about;` in `location = /about.html` does that. If the `set` is removed or renamed, `nginx -t` fails with `unknown \"static_page\" variable`, and the whole host's nginx then fails its config test.\n\n**Risk of regression.**\n- **Field order is a security issue.** nginx's default log escaping turns `\"`, `\\` and bytes outside 0x20\u20130x7E into `\\xNN`, but it leaves spaces alone. `$http_user_agent` and `$http_x_request_id` are fully client-controlled and can contain a forged ` status=200 ` or ` method=GET ` token. The plan suggests `grep ' status=200 '` / `' method=GET '` filters, and those can be spoofed.\n  - Keep every client-controlled field (`x_request_id`, `ua`) at the end of the line.\n  - The runbook should anchor on `^page=about ` and filter by awk field position over the fixed-format leading fields, not by an unanchored grep.\n  - `uri=\"$request_uri\"` sits before `status` in the plan's order. Recent nginx rejects a raw space in the request line with 400, so this is lower risk, but it is safer to put `uri` after `status`/`rt` as well. The plan only says the order is \"roughly\" this, so that is allowed.\n- **`$msec`** renders as `1700000000.123`, seconds with a 3-digit fraction, which GNU `date -u -d @\u2026` accepts.\n- **`$time_iso8601`** is server-local time with a numeric offset, as the plan states.\n</impact>\n<impact path=\"DEPLOYMENT.md\" element=\"\u00a76 nginx (production) block: `server {}` body, the new `location = /about.html`, `location = /about`, `location = /about/` (insert among lines 428-457)\">\n**What changes.** Three exact-match locations are added. The best placement is right after `location /` (lines 428-430), so the four proxied blocks (432-457) stay together.\n- `location = /about.html` holds:\n  - `set $static_page about;`\n  - `try_files /dev-pages/about.html /dev-pages/about.template.html =404;`\n  - `access_log /var/log/nginx/peertube-browser.access.log peertube_browser;`\n  - `access_log /var/log/nginx/peertube-browser.pages.access.log peertube_browser_pages;`\n  - no `add_header`.\n- `location = /about` and `location = /about/` each hold only `rewrite ^ /about.html last;`.\n\n**Facts verified in the file.**\n- Server level: `root /var/www/peertube-browser`, `index index.html`, a server-level `access_log` (424) and `add_header Content-Security-Policy \u2026 always` (426).\n- `location /` is `try_files $uri $uri/ =404`. Nothing names `/about` today.\n- The build emits only `dist/dev-pages/about*.html`. `client/frontend/dist/dev-pages/about.template.html` exists and there is no `dist/about.html`. So `/about.html`, which every page's nav links to, is a 404 in prod today. This change fixes that as a side effect, and it is a visible behaviour change for users.\n\n**What depends on it.**\n- Operators copy this block by hand.\n- The whole nginx config, this site file included, is gated by `nginx -t` in `engine/install-engine-service.sh:401`, `engine/uninstall-engine-service.sh:115` and `scripts/deploy-bluegreen.sh:148,317`. A syntax error here therefore turns an Engine deploy into a `rollback \u2026 nginx_test`, and makes the installer refuse.\n- \"Follow one request\" (line 236) greps the main log. That still works for About because the main `access_log` line is repeated in the location.\n\n**Risk of regression.**\n- A location-level `access_log` replaces the inherited server-level one. If the first `access_log` line is dropped, About disappears from the main log silently.\n- Using `break`, `redirect` or `permanent` instead of `last` either serves from the rewrite location or doubles the requests and log lines.\n- An `add_header` added later to the About location would drop the inherited CSP. The About template has no `<meta http-equiv>` CSP, unlike the other six pages, so the server header is its only CSP.\n- With `=` exact matches, `/about.html?x=1` still matches, because the query is not part of the location match. `/About` and `/about//` do not match and fall to `location /`, which answers 404.\n- The other routes' behaviour is unchanged.\n</impact>\n<impact path=\"DEPLOYMENT.md\" element=\"\u00a76 prose after the block, line 463 (the request-id / `proxy_set_header` / `log_format stays outside server {}` paragraph) and new prose next to it\">\n**What changes.**\n- The sentence \"`log_format` stays outside `server {}`\u2026\" becomes plural, because there are now two formats.\n- New prose sits beside the existing note on why `proxy_set_header` is repeated. It covers:\n  - why the About location lists both `access_log` lines (a location-level `access_log` replaces the inherited one);\n  - that the location inherits the CSP because it has no `add_header`, and that About has no meta CSP;\n  - that the `try_files` order mirrors vite's override-then-template order;\n  - to keep `last`;\n  - the new file `/var/log/nginx/peertube-browser.pages.access.log`, which falls under the Debian/Ubuntu `/var/log/nginx/*.log` logrotate rule, whose postrotate USR1 reopens it;\n  - that direct hits on `/dev-pages/about*.html` go through `location /` and leave no pages line;\n  - that existing hosts must re-apply \u00a76 and reload.\n\n**What depends on it.** The Triage runbook links here.\n\n**Risk of regression.** Low, since this is prose. The logrotate claim holds only for the distro package layout. State it as Debian/Ubuntu-specific, as the plan does.\n</impact>\n<impact path=\"DEPLOYMENT.md\" element=\"\u00a76 TLS subsection (lines 525-533, `sudo certbot --nginx`)\">\n**What changes.** No change in the plan, but one is needed. `certbot --nginx` edits the live `/etc/nginx/sites-available/peertube-browser` in place: it adds `listen 443 ssl`, the certificate paths and a redirect. The plan tells existing hosts to \"re-apply \u00a76 and reload\". An operator who copies the whole block over a certbot-edited file deletes the TLS config.\n\n**What depends on it.** Every host that followed the TLS section.\n\n**Risk of regression.** High for operators. The re-apply instruction should say to merge in only the new `log_format` line and the three locations, or to re-run `certbot --nginx` (or `certbot install`) afterwards. A full overwrite must not be the instruction.\n</impact>\n<impact path=\"DEPLOYMENT.md\" element=\"\u00a76 Verify (lines 475-481)\">\n**What changes.**\n- Add `curl -I http://localhost/about`: 200 with a `Content-Security-Policy` header. `/about/` and `/about.html` can be listed as well.\n- Add a `sudo tail -n 3 /var/log/nginx/peertube-browser.pages.access.log`.\n- Optionally add a hint that a 404 on `/about` means the build did not produce `dev-pages/about*.html`, or \u00a76 was not re-applied.\n\n**What depends on it.** Operators after an install or re-apply.\n\n**Risk of regression.** Low. `curl -I` sends HEAD, so it is logged as `method=HEAD`. The runbook's GET filter would exclude it, which is correct but worth knowing when someone checks that the tail shows \"a visit\".\n</impact>\n<impact path=\"DEPLOYMENT.md\" element=\"\u00a76 Engine listener paragraph, line 485 (\\\"leave the public site file above as it is, since nothing here changes it\\\")\">\n**What changes.** Nothing. I checked it against the plan: the plan touches only the public site file, not the 7079 listener, and this sentence still holds.\n\n**What depends on it.** Nothing new.\n\n**Risk of regression.** None. Listed only to confirm it was checked.\n</impact>\n<impact path=\"DEPLOYMENT.md\" element=\"\u00a73 Build the client, the `try_files` paragraph and page list (lines 299-303)\">\n**What changes.** The current text says every page is served through `try_files` and lists `about` among the pages. Add that About is built under `dist/dev-pages/` (`about.html` if the local override exists, else `about.template.html`) and is reached at `/about`, `/about/` and `/about.html` only through the \u00a76 mapping.\n\n**What depends on it.** The `scripts/sync.sh` workflow, and readers who add pages. The \"Adding another informational page\" story (one more location of the same shape) could be stated here or in \u00a76.\n\n**Risk of regression.** Low.\n</impact>\n<impact path=\"DEPLOYMENT.md\" element=\"Triage: \\\"Follow one request\\\" (lines 231-249) and the new \\\"Follow an About visit\\\" subsection inserted after line 249, before \\\"Centralized installer\\\" at line 251\">\n**What changes.** A new subsection with four steps:\n1. List visits from the pages log.\n2. `sudo grep \"request_id=$id\"` on the main log.\n3. Convert `ts=` with `date -u -d @<msec> +%Y-%m-%dT%H:%M:%S.%3NZ` and filter the Client journal with `jq` on `.event == \"request.start\" and .context.ip == $ip and .ts >= $from and .ts <= $to`. There is also a `LOG_FORMAT=text` variant.\n4. Hand off to \"Follow one request\".\n\nIt also carries the four caveats: no shared id; IP resolved through `TRUSTED_PROXIES`, with IPv6 and IPv4-mapped text forms; formats and time zones; bots filtered only by user agent, with issue 18's beacon as the upgrade path. \"What each log is for\" (242-244) gains a pages-log bullet.\n\n**Facts verified.** `client/backend/server.py:346-350`: `request.start` context is `{\"ip\", \"method\", \"url\", \"user_agent\"?}`. `_format_ts` (136-140) is a fixed-width UTC `YYYY-MM-DDTHH:MM:SS.mmmZ`, so comparing the strings orders correctly. JSON keys are `ts`, `event`, `context`, `request_id` (176-189). The existing jq idiom at line 237 is `jq -cR \u2026 'fromjson? | select(\u2026)'`.\n\n**What depends on it.** Operators. Issue 21's validation clause \"Correlation by request id/time window works against app traces\".\n\n**Risk of regression.**\n- **Text mode.** `_render_text` (150-163) writes context as unquoted `key=value`. A grep for `ip=$ip` without a trailing space also matches `ip=1.2.3.45` when looking for `1.2.3.4`, so the runbook must use `\"ip=$ip \"`. `user_agent` comes after `ip` in the text line and is unquoted, so a UA can forge an ` ip=\u2026 ` token. Text-mode matching is weaker than JSON, and the runbook should say so.\n- **Pages log.** `grep 'page=about'` without the `^` anchor can be forged through `ua`/`x_request_id`.\n- **Time window.** The window must account for clock skew only within one host, which is fine. A visitor who leaves About makes no API call, so they have no Client record. That is stated as a tradeoff.\n</impact>\n<impact path=\"DEPLOYMENT.md\" element=\"Triage table (lines 197-229)\">\n**What changes.** Optional. Add a row: `/about` (or `/about.html`) answers 404 \u2192 \u00a76 not re-applied, or no `dev-pages/about*.html` in the document root \u2192 re-apply \u00a76 / run `scripts/sync.sh`. Possibly another row: \"About visit has no pages-log line\" \u2192 the hit went to `/dev-pages/\u2026` directly, or the second `access_log` line is missing.\n\n**What depends on it.** Operators.\n\n**Risk of regression.** None. It is additive.\n</impact>\n<impact path=\"DEPLOYMENT.md\" element=\"\u00a72 `LOG_FORMAT` paragraph (line 116)\">\n**What changes.** Optional. A pointer to \"Follow an About visit\" next to the existing pointer to \"Follow one request\". It should note that the text-mode recipe in the new runbook is weaker, because values are unquoted, which this paragraph already says (\"values are not quoted, so it is for reading by eye\").\n\n**What depends on it.** Nothing.\n\n**Risk of regression.** None.\n</impact>\n<impact path=\"DEPLOYMENT.md\" element=\"\u00a77 Verify page list (lines 561-565)\">\n**What changes.** Optional: add `/about` to the list of pages to open.\n\n**What depends on it.** Nothing.\n\n**Risk of regression.** None.\n</impact>\n<impact path=\"client/frontend/README.md\" element=\"\\\"Local About Overrides\\\" (lines 36-39)\">\n**What changes.** Add one line: in prod, nginx serves whichever file was built (the `dev-pages/about.html` override first, then the template) at `/about`, `/about/` and `/about.html` (`DEPLOYMENT.md` \u00a76). Optionally also:\n- an override must use root-absolute URLs, because the same file is served at `/about/`, where relative URLs would resolve under `/about/`;\n- it gets only the server CSP header (`script-src 'self'`, no inline script).\n\n**What depends on it.** Developers writing the untracked override. `.gitignore:29-30` ignores `client/frontend/dev-pages/*` except the template, so the override is never in the repo and nothing checks it.\n\n**Risk of regression.** Low. It is documentation. The real risk it guards against is an override that uses relative links, which break at `/about/`.\n</impact>\n<impact path=\"client/frontend/vite.config.ts\" element=\"`aboutSourcePath`, `rewriteToAbout` (lines 13-22) and `build.rollupOptions.input.about` (lines 91-93)\">\n**What changes.** Nothing. This is the contract the nginx block copies:\n- the `existsSync(dev-pages/about.html)` override, otherwise `about.template.html`, emitted at `dist/dev-pages/<same name>`;\n- the rewrite set `/about`, `/about/`, `/about.html` (line 22), which is exactly the three nginx exact locations.\n\n**What depends on it.** The nginx `try_files` order and its paths.\n\n**Risk of regression.**\n- If someone later renames the input, moves it out of `dev-pages/` or adds a URL to `rewriteToAbout`, nginx drifts silently. Nothing tests the two against each other. The new test could assert that the three exact-location URLs equal the `rewriteToAbout` set and that the `try_files` paths match the two `dev-pages` names, which would close that drift.\n- Out of scope: the vite-only rewrites of `/videos` and `/search` (lines 20-21) have no prod nginx counterpart either. That is the same dev/prod gap class.\n</impact>\n<impact path=\"client/frontend/dev-pages/about.template.html\" element=\"the whole template\">\n**What changes.** Nothing. I checked it: every URL is root-absolute (`/favicon.png`, `/src/videos.css`, which becomes `/assets/videos-*.css` in `dist/dev-pages/about.template.html:8`, and the nav `/channels.html`, `/`, `/likes.html`, `/about.html`). It has no `<meta http-equiv>` CSP, unlike the six top-level pages, and no script.\n\n**What depends on it.** It is served at `/about/`, so relative URLs would break there. None exist.\n\n**Risk of regression.** None for the template. If a later edit adds a relative link or an inline script, the link breaks at `/about/` or the script is blocked by the header CSP.\n</impact>\n<impact path=\"client/frontend/index.html\" element=\"nav `href=\\\"/about.html\\\"` link (line 26); same link in videos.html:26, search.html:26, likes.html:26, channels.html:26, video-page.html:24\">\n**What changes.** Nothing in the files. These links 404 in prod today and resolve to 200 after the change, through `location = /about.html` with no rewrite. That is a user-visible fix.\n\n**What depends on it.** Every page's navigation.\n\n**Risk of regression.** None. It is noted because every About visit via nav arrives as `/about.html` and logs as `uri=\"/about.html\"`, so the runbook should not assume `/about`.\n</impact>\n<impact path=\"client/frontend/dist/dev-pages/about.template.html\" element=\"committed build output\">\n**What changes.** Nothing. It confirms the output layout: `dist/dev-pages/about.template.html` exists, and `dist/about.html` does not.\n\n**What depends on it.** The `try_files` second candidate.\n\n**Risk of regression.** None. The committed `dist/` lags the source (DEPLOYMENT.md line 412), but the about path layout is stable.\n</impact>\n<impact path=\"scripts/sync.sh\" element=\"build then `rsync -a --delete` to `/var/www/peertube-browser/`\">\n**What changes.** Nothing.\n\n**What depends on it.** `--delete` removes a stale `dev-pages/about.html` once the override is removed locally and rebuilt. That is what keeps the `try_files` preference correct, as the plan's \"stale dev-pages files\" gotcha says.\n\n**Risk of regression.** Low. A manual copy without `--delete` would leave a stale override, and nginx would keep preferring it over a newer template.\n</impact>\n<impact path=\"client/backend/server.py\" element=\"`_run_request` request.start context (lines 339-357), `_format_ts` (136-140), `_render_text` (150-163), `ClientLogFormatter.format` (174-195)\">\n**What changes.** Nothing; the runbook's step 3 depends on these.\n\n**What depends on it.** The runbook's jq filter (`.event`, `.context.ip`, `.ts`) and its string comparison of `ts`.\n\n**Risk of regression.**\n- If `ts` ever stops being fixed-width UTC with a `Z` suffix, or `ip` moves out of `context`, the runbook silently matches nothing. No test ties the runbook to these. The planned synthetic-record runbook test should build its Client record by calling the real `ClientLogFormatter`, not a hand-written JSON string, so that drift turns the test red.\n- The `rat-tail` comment at line 122 notes this module is mirrored in `engine/server/api/logging_profiles.py`. Step 4 of the runbook hands off to the Engine through \"Follow one request\", which relies on `request_id` only.\n</impact>\n<impact path=\"engine/install-engine-service.sh\" element=\"`nginx -t` gate (line 401-406)\">\n**What changes.** Nothing.\n\n**What depends on it.** It runs `nginx -t` over the whole host config, including the public site file.\n\n**Risk of regression.** An invalid About block, such as a missing `set` or a misspelled format name, makes the prod Engine install fail with \"nginx -t failed\".\n</impact>\n<impact path=\"scripts/deploy-bluegreen.sh\" element=\"`nginx -t` at line 317 and during rollback at line 148\">\n**What changes.** Nothing.\n\n**What depends on it.** Same as above.\n\n**Risk of regression.** A broken site file turns every deploy into `rollback phase=switching step=nginx_test`, and a broken restore into `rollback_failed \u2026 restore_nginx_test`. Triage row 225 already says `nginx -t` is \"often an unrelated broken config\", so no doc change is needed there.\n</impact>\n<impact path=\"engine/uninstall-engine-service.sh\" element=\"`nginx -t` at line 115\">\n**What changes.** Nothing.\n\n**What depends on it.** Same as above.\n\n**Risk of regression.** A broken site file makes the uninstaller fail after it removes the listener.\n</impact>\n<impact path=\"tests/active/test_static_page_visit_logs.py\" element=\"new test file (name to be chosen by the test step)\">\n**What changes.** A new test. It extracts the site block from `DEPLOYMENT.md`, rewrites `root`, the log paths and `listen` to temp-dir values, wraps the block in `http {}` and runs `nginx -t`. Where possible it also starts nginx on a free port and checks:\n- 200 on the three URLs and the CSP header;\n- exactly one line per log per request;\n- matching `request_id` values;\n- that `/` and `/api/\u2026` produce no pages line.\n\nA synthetic runbook check runs as well. The test is skipped when `shutil.which(\"nginx\")` is None.\n\n**What depends on it.** `.un/skills/devsecops/config.json` test_groups, which needs a new entry.\n\n**Risk of regression / pitfalls (verified against the doc).**\n- **Selecting the block.** `DEPLOYMENT.md` has two fenced `nginx` blocks: the site block (415-459) and the upstream snippet (488-492). The extraction must pick the one after the `/etc/nginx/sites-available/peertube-browser` caption, not the first or last ```` ```nginx ````.\n- **Running unprivileged.**\n  - nginx opens its compiled-in error log (`/var/log/nginx/error.log`) before it reads the config. Use `-e <tmp>/error.log` (nginx \u22651.19.5) or accept the alert.\n  - `nginx -t` and the start fail with `mkdir() \"/var/lib/nginx/body\" failed (13)` unless `client_body_temp_path`, `proxy_temp_path`, `fastcgi_temp_path`, `uwsgi_temp_path` and `scgi_temp_path` point into the temp dir.\n  - `pid` also needs a temp path, as does `-p <prefix>`.\n- **The wrapper.**\n  - Without `include mime.types` it serves `text/plain`, so do not assert `text/html` unless the wrapper includes it.\n  - The `proxy_pass http://127.0.0.1:7072` lines are fine for `-t`. `/api/\u2026` will answer 502 with nothing listening, which is still enough to assert \"no pages line\".\n- **Log timing.** nginx writes the access-log line after it sends the response, so the test must poll the log files before counting lines.\n- **Rewrites.** The rewrites of `/var/log/nginx/\u2026` must cover both `access_log` lines inside the About location, not just the server-level one, or nginx tries to open `/var/log/nginx/\u2026` and fails as non-root.\n- **Bound to the doc text.** The test reads a doc's content, so a reflow of the doc or a quoting style change can break the extraction. Match on directive tokens, as `_statements()` in `tests/active/test_install_engine_service.py:141-145` does, not on whole lines.\n</impact>\n<impact path=\".un/skills/devsecops/config.json\" element=\"`test_groups` (lines 14-263)\">\n**What changes.** Add a group for the new test that maps `DEPLOYMENT.md`, and possibly `client/frontend/vite.config.ts` if the test asserts the URL set and `dev-pages` names. Non-code paths are already allowed: `tests/active/host_tokens.json` and `upstream_snippet_cases.json` are listed.\n\n**What depends on it.** The runner selects groups from the changed files. Today no group maps `DEPLOYMENT.md`, so without this entry a doc-only change selects no test, and the new test never runs in the build's suite.\n\n**Risk of regression.** Medium. Leaving it out silently skips the only validation of this build.\n</impact>\n<impact path=\"tests/active/test_install_engine_service.py\" element=\"`_statements()` helper (lines 141-145)\">\n**What changes.** Nothing. It is the existing idiom for parsing nginx text into directives with comments stripped.\n\n**What depends on it.** The new test may copy it. Test modules do not import from one another, so copying matches the repo's style.\n\n**Risk of regression.** None.\n</impact>\n<impact path=\"docs/project/issues/21-static-page-visit-logs.md\" element=\"`Status:` line and `## Comments`\">\n**What changes.** At completion:\n- `Status: enhancement, complete`;\n- a delivery comment naming `docs/project/plans/22-21-static-page-visit-logs.md`, in the same shape as the archived issue 19/20 comments;\n- a move to `docs/project/issues/archive/`, as `docs/project/issue-tracker.md:21` requires.\n\nThe plan says only \"status at completion\", but the move is mandatory.\n\n**What depends on it.** `docs/project/issues/plan.md` and the issue numbering, which counts `archive/`.\n\n**Risk of regression.** Low. The issue-20 build left a duplicate in `issues/` because its agent had no delete tool (record step 9). The same could happen here.\n</impact>\n<impact path=\"docs/project/issues/plan.md\" element=\"P5 row (line 42) and wave lane 5c (line 98)\">\n**What changes.**\n- Lane 5c's \"Main files\" says \"nginx docs, the About template, one Client endpoint\". For 21, that is the nginx docs only; the template and the endpoint belong to 18. Mark 21 delivered there.\n- Line 42 still says \"19 and part of 20 are already delivered\". That is stale on this branch, and it could be updated to say 19, 20 and 21 are delivered.\n\n**What depends on it.** Planning.\n\n**Risk of regression.** None.\n</impact>\n<impact path=\"docs/project/roadmap.md\" element=\"`## Delivered` list (lines 7-25) and Logging chain line 157\">\n**What changes.** Optional: a Delivered bullet for issue 21 pointing to the plan. Line 157 (`19` -> `20` -> `21`) needs no change. The convention is applied unevenly: issues 19 and 20 have no Delivered bullet.\n\n**What depends on it.** Nothing.\n\n**Risk of regression.** None. Uncertain whether a bullet is expected.\n</impact>\n<impact path=\"docs/project/issues/18-about-outbound-click-tracking.md\" element=\"`## Comments`\">\n**What changes.** Optional comment. Issue 21's runbook names 18's beacon endpoint as the pageview upgrade path. Line 14 plans `/api/analytics/outbound-click`, a click-specific endpoint, so a pageview would need 18's endpoint design to allow a page-view event type. There is no duplication, because 21 adds no endpoint.\n\n**What depends on it.** The future design of 18.\n\n**Risk of regression.** None. It is a naming-only forward reference: if 18 lands with a click-only schema, the runbook's \"upgrade path\" statement becomes inaccurate.\n</impact>\n<impact path=\"CONTEXT.md\" element=\"glossary, \\\"Request id\\\" (line 10)\">\n**What changes.** Nothing required. The entry is still true: About lines carry nginx's `$request_id`, but no app record shares it, and the runbook says so. An optional glossary term (\"pages log\" / \"informational static page\") could be added. I consider it unnecessary because the plan scopes it to About only.\n\n**What depends on it.** Nothing.\n\n**Risk of regression.** None.\n</impact>\n<impact path=\"client/README.md\" element=\"line 75 (request.start / \\\"byte counts are in the nginx access log\\\") and line 69 (`TRUSTED_PROXIES`)\">\n**What changes.** Nothing. It is the source of the runbook's statement that the Client's `ip` is resolved through `TRUSTED_PROXIES`. It points to \"Follow one request\", and a pointer to \"Follow an About visit\" could optionally be added.\n\n**What depends on it.** Nothing.\n\n**Risk of regression.** None.\n</impact>\n<impact path=\"engine/server/README.md\" element=\"line 32 (request.start/end and the pointer to DEPLOYMENT.md Triage)\">\n**What changes.** Nothing. It is checked because step 4 of the runbook reaches the Engine through the same `request_id` flow.\n\n**What depends on it.** Nothing.\n\n**Risk of regression.** None.\n</impact>\n<impact path=\"docs/project/plans/22-21-static-page-visit-logs.md\" element=\"the plan file\">\n**What changes.** Nothing by hand. Its header (line 3) says the dev-flow workflow renders it, and every edit is overwritten.\n\n**What depends on it.** It is named in the issue 21 delivery comment.\n\n**Risk of regression.** None.\n</impact>\n</impacts>",
  "docs_checklist": "- [x] `DEPLOYMENT.md` - updated: I updated the prose in `DEPLOYMENT.md` to match what the build delivered: how About is served, the pages log, the About runbook caveats, and checks and warnings for operators. I didn't change the \u00a76 nginx site block or the fenced runbook commands, since the tests check both.\n- [x] `client/frontend/README.md` - updated: \"Local About Overrides\" now says how prod serves the built About page, that overrides need root-absolute URLs, and which CSP applies.\n- [x] `docs/project/issues/21-static-page-visit-logs.md` - updated: Issue 21 marked delivered and copied to `docs/project/issues/archive/21-static-page-visit-logs.md` with a delivery comment. **The original at `docs/project/issues/21-static-page-visit-logs.md` still exists and needs deleting.** I have no tool that deletes files, so until it goes there are two copies.\n- [x] `docs/project/issues/plan.md` - updated: plan.md: P5 row now says 19, 20 and 21 are delivered and 18 remains; lane 5c splits the file list between 21 and 18 and marks 21 delivered with its plan path.\n- [x] `docs/project/issues/18-about-outbound-click-tracking.md` - updated: Added a comment to issue 18: issue 21 names this issue's beacon endpoint as the way to count pageviews, so the endpoint should also accept a page-view event type.\n- [x] `docs/project/roadmap.md` - out of scope: No change needed. The Delivered list has no bullet for the sibling logging issues 19 and 20, so the convention does not call for one for 21. The Logging chain line (`19` -> `20` -> `21`) is still accurate.\n- [x] `CONTEXT.md` - out of scope: No change needed. The \"Request id\" entry is still true: About lines carry nginx's `$request_id`, but no app record shares it. The scope is About only, so no new glossary term is warranted.\n- [x] `client/README.md` - out of scope: No change needed. Its `TRUSTED_PROXIES` and `request.start` statements, which the runbook relies on, are unchanged and still true, and it makes no claim about About or the nginx logs.\n- [x] `docs/project/adr/0002-trusted-proxy-client-address.md` - out of scope: No change needed. The runbook's IP caveat restates this ADR's resolution rule and does not change it. The build touches neither the Client backend nor the proxy headers.\n- [x] `docs/project/adr/0004-cors-opt-in-by-origin.md` - out of scope: No change needed. Prod nginx still serves everything on one origin. The About locations add no headers and no cross-origin path.\n- [x] `docs/project/adr/0009-engine-blue-green-through-nginx-upstream-snippet.md` - out of scope: No change needed. Only the public site file changed. The upstream snippet and the 7079 listener are untouched, and \u00a76 line 526 (\"leave the public site file above as it is, since nothing here changes it\") is still accurate.",
  "docs": [
    {
      "path": "DEPLOYMENT.md",
      "note": "- **\u00a76 site block:**\n  - Add `log_format peertube_browser_pages` under line 416, with the client-controlled `ua`/`x_request_id` (and ideally `uri`) last.\n  - Add `location = /about.html` with `set $static_page about;`, `try_files /dev-pages/about.html /dev-pages/about.template.html =404;`, both `access_log` lines and no `add_header`.\n  - Add the `= /about` / `= /about/` aliases with `rewrite ^ /about.html last;`, placed after `location /`.\n- **\u00a76 prose at line 463:**\n  - Make the `log_format` sentence plural.\n  - Explain why both `access_log` lines are needed and that the CSP is inherited (About has no meta CSP).\n  - Note that the `try_files` order mirrors vite, and to keep `last`.\n  - Name the new log file and its Debian/Ubuntu logrotate coverage.\n  - Say that direct `/dev-pages/\u2026` hits are not in the pages log.\n  - Tell existing hosts to merge the additions rather than overwrite a certbot-edited file, or to re-run certbot.\n- **\u00a76 TLS (525-533):** warn that re-applying \u00a76 by overwriting the site file drops certbot's edits.\n- **\u00a76 Verify (475-481):** add `curl -I http://localhost/about` (200 + CSP), a pages-log `tail`, and a 404 hint.\n- **\u00a73 (299-303):** About is built under `dist/dev-pages/` and reached at `/about`, `/about/`, `/about.html` via \u00a76.\n- **Triage:**\n  - Add the \"Follow an About visit\" subsection after line 249: the anchored `^page=about ` listing with positional awk, the main-log `request_id` grep, the `date -u` conversion with the JSON jq filter and the text variant using `\"ip=$ip \"`, and the hand-off to \"Follow one request\".\n  - Include the four caveats, plus the forgeable-token note.\n  - Add a pages-log bullet to \"What each log is for\".\n- **Optional:**\n  - a Triage table row for an `/about` 404;\n  - a pointer from the \u00a72 `LOG_FORMAT` paragraph (line 116);\n  - `/about` in the \u00a77 page list."
    },
    {
      "path": "client/frontend/README.md",
      "note": "\"Local About Overrides\" (lines 36-39): add that prod nginx serves whichever file was built (the override first, then the template) at `/about`, `/about/` and `/about.html` (`DEPLOYMENT.md` \u00a76). Optionally add that an override must use root-absolute URLs, because it is also served at `/about/`, and that it gets only the server CSP header."
    },
    {
      "path": "docs/project/issues/21-static-page-visit-logs.md",
      "note": "At completion: `Status: enhancement, complete`, a delivery comment naming `docs/project/plans/22-21-static-page-visit-logs.md` and what was delivered, and a move to `docs/project/issues/archive/` per `docs/project/issue-tracker.md:21`."
    },
    {
      "path": "docs/project/issues/plan.md",
      "note": "- Lane 5c (line 98): mark 21 delivered and correct its file list for 21 to the nginx docs only.\n- P5 row (line 42): update the stale \"19 and part of 20\" wording."
    },
    {
      "path": "docs/project/roadmap.md",
      "note": "Optional Delivered bullet for issue 21. The convention is inconsistent: 19 and 20 have none."
    },
    {
      "path": "docs/project/issues/18-about-outbound-click-tracking.md",
      "note": "Optional comment: issue 21's runbook names 18's beacon endpoint as the pageview upgrade path, so 18's endpoint design may need a page-view event type besides outbound clicks."
    }
  ],
  "reassessments": 3,
  "draft": "## Draft: issue 21, About visit log (documentation build)\n\nNote on the brief: the ladder heading arrived with an unrendered `{rat_tail_ladder}` placeholder. I followed the two numbered ladder steps printed under it. The one deliberate mirror in this build (nginx copying vite's About mapping) is marked with the repo's existing `rat-tail:` comment convention, the same one used at `client/backend/server.py:122`.\n\n### Module map\n\n| File | Change |\n|---|---|\n| `DEPLOYMENT.md` \u00a76 site block | Second `log_format`, three exact About locations |\n| `DEPLOYMENT.md` \u00a76 prose / Verify / TLS | About mapping prose, re-apply-without-overwrite rule, verify lines, certbot warning |\n| `DEPLOYMENT.md` \u00a73 | About's build location and URLs |\n| `DEPLOYMENT.md` Triage | Two table rows, new \"Follow an About visit\" subsection, pages-log bullet |\n| `DEPLOYMENT.md` \u00a72, \u00a77 | One pointer sentence, one page-list bullet |\n| `client/frontend/README.md` | \"Local About Overrides\" gains the prod mapping and two constraints |\n| `tests/active/test_static_page_visit_logs.py` | New (written by the test step; contract below) |\n| `.un/skills/devsecops/config.json` | New `test_groups` entry |\n| `docs/project/issues/21-\u2026` | At completion: status, comment, move to `archive/` |\n| `docs/project/issues/plan.md` | P5 row and lane 5c |\n| `docs/project/issues/18-\u2026` | One forward-reference comment |\n| `docs/project/roadmap.md` | **Not changed.** Issues 19 and 20 have no Delivered bullet, and adding one only for 21 would make the list less consistent, not more. |\n\nNo app, frontend source or build file changes.\n\n---\n\n### 1. `DEPLOYMENT.md` \u00a76: the site block (replaces lines 415\u2013459)\n\n````\n```nginx\nlog_format peertube_browser '$remote_addr - $remote_user [$time_local] \"$request\" $status $body_bytes_sent \"$http_referer\" \"$http_user_agent\" request_id=$request_id upstream=$upstream_addr rt=$request_time';\nlog_format peertube_browser_pages 'page=$static_page ts=$msec time=$time_iso8601 ip=$remote_addr method=$request_method status=$status rt=$request_time request_id=$request_id uri=\"$request_uri\" x_request_id=$http_x_request_id ua=\"$http_user_agent\"';\n\nserver {\n    listen 80;\n    server_name _;\n\n    root /var/www/peertube-browser;\n    index index.html;\n    access_log /var/log/nginx/peertube-browser.access.log peertube_browser;\n\n    add_header Content-Security-Policy \"default-src 'self'; script-src 'self'; object-src 'none'; base-uri 'self'; frame-src https:; connect-src 'self' https:; img-src 'self' https: data:\" always;\n\n    location / {\n        try_files $uri $uri/ =404;\n    }\n\n    # rat-tail: these three URLs and the two dev-pages names mirror rewriteToAbout and aboutSourcePath in client/frontend/vite.config.ts; tests/active/test_static_page_visit_logs.py compares them, and building About to dist/about.html is the upgrade if the mapping grows.\n    location = /about.html {\n        set $static_page about;\n        try_files /dev-pages/about.html /dev-pages/about.template.html =404;\n        access_log /var/log/nginx/peertube-browser.access.log peertube_browser;\n        access_log /var/log/nginx/peertube-browser.pages.access.log peertube_browser_pages;\n    }\n    location = /about {\n        rewrite ^ /about.html last;\n    }\n    location = /about/ {\n        rewrite ^ /about.html last;\n    }\n\n    location /api/ {\n        \u2026 unchanged \u2026\n    }\n    \u2026 /recommendations, /videos/similar, /client/ unchanged \u2026\n}\n```\n````\n\n**Invariants**\n\n- **Field order.** The first eight space-separated fields are fixed-format, and clients cannot inject spaces into them:\n\n  | Position | Field |\n  |---|---|\n  | 1 | `page=` |\n  | 2 | `ts=` |\n  | 3 | `time=` |\n  | 4 | `ip=` |\n  | 5 | `method=` |\n  | 6 | `status=` |\n  | 7 | `rt=` |\n  | 8 | `request_id=` |\n\n  Every client-controlled field (`uri`, `x_request_id`, `ua`) comes after them. The runbook filters by `awk` field position, never with an unanchored grep. The plan said the order was only \"roughly\" fixed; I moved `uri` after `status`/`rt`, as the impact inventory recommends.\n- **`x_request_id` stays unquoted.** nginx then writes a bare `-` when the header is absent, which is the format the requirement asks for.\n- **No `add_header` in the About location.** That is how it inherits the server's CSP, `always` included, so the 404 carries it too.\n- **The rewrites use `last`.** That keeps one request: one `$request_id`, one log phase, ending in `= /about.html`.\n- **`$static_page` is declared once, by the `set`.** Removing the `set` makes `nginx -t` fail with `unknown \"static_page\" variable`.\n- **`try_files` order matches vite's:** the override first, then the template.\n\n### 2. `DEPLOYMENT.md` \u00a76: prose after the block\n\n**Line 463, last sentence, made plural:** \"`log_format` stays outside `server {}`: the file is included in nginx's `http` block, the only place `log_format` is allowed, so both formats sit above the `server` block.\"\n\n**New paragraph after line 463** (one line in the file):\n\n> `/about`, `/about/` and `/about.html` are served by the three exact locations. The build emits About only as `dev-pages/about.html` (a local override) or `dev-pages/about.template.html` (`client/frontend/README.md`), never as `about.html`, so without them every page's About link is a 404. `location = /about.html` serves the override if the document root has one, otherwise the template, otherwise 404, in the same order as the build. The other two locations hand the request to it with `rewrite \u2026 last`. Keep `last`: it continues the same request, so a visit to `/about` is one request with one `$request_id`, logged once. `break` would serve from the rewriting location, which has no `try_files` and no pages log. `redirect` and `permanent` send the browser a second request. The About location writes both `access_log` lines because a location that declares any `access_log` inherits none from the server level. Dropping the first line silently removes About from `peertube-browser.access.log`. The location declares no `add_header`, so it inherits the server's `Content-Security-Policy`. About has no `<meta>` CSP of its own, so that header is its only CSP, and any `add_header` added there must repeat it. The second line writes `/var/log/nginx/peertube-browser.pages.access.log` in the `peertube_browser_pages` format, one line per About request of any method and status (see \"Follow an About visit\" under Triage). On Debian and Ubuntu, the nginx package's logrotate rule for `/var/log/nginx/*.log` rotates it, and its postrotate signal reopens it with the other logs. Elsewhere, add it to your rotation. Requests made directly to `/dev-pages/about*.html` go through `location /` and write no pages line. Nothing links there. To log another informational page, add one more exact location of the same shape, with its own `set $static_page <name>;`, its `try_files` and the same two `access_log` lines.\n\n**New paragraph after it:**\n\n> On a host that already runs this site, add the `peertube_browser_pages` line and the three About locations to the live `/etc/nginx/sites-available/peertube-browser` by hand, inside the `server` block that has `root /var/www/peertube-browser`. Then run `sudo nginx -t && sudo systemctl reload nginx`. Do not copy the whole block over the file: `sudo certbot --nginx` (see \"TLS\") edits it in place, and overwriting it removes the HTTPS listener and the redirect. If it was overwritten, run `sudo certbot --nginx` again. A broken site file fails `nginx -t` for the whole host, which also stops a prod Engine install and rolls back a deploy (Triage).\n\n### 3. `DEPLOYMENT.md` \u00a76 Verify (replaces lines 475\u2013481)\n\n````\nVerify:\n```bash\ncurl -I http://localhost/                 # 200, text/html\ncurl -s http://localhost/api/health       # client-backend JSON, publish_mode=bridge\ncurl -I http://localhost/about            # 200, text/html, Content-Security-Policy header; /about/ and /about.html the same\nsudo tail -n 3 /var/log/nginx/peertube-browser.pages.access.log    # one page=about line per request above, method=HEAD for curl -I\n```\nA 404 on `/` with a successful `nginx -t` means the document root is unreadable by\n`www-data`; check with `sudo -u www-data stat /var/www/peertube-browser/index.html`.\nA 404 on `/about` while `/` answers 200 means the About locations are missing from the live site file, or the document root holds neither `dev-pages/about.html` nor `dev-pages/about.template.html` (`ls /var/www/peertube-browser/dev-pages/`; rebuild and sync, section 3).\n````\n\nThe existing two-line hard wrap on the first 404 sentence is kept as it is. The new sentence is one line.\n\n### 4. `DEPLOYMENT.md` \u00a76 TLS (after line 533)\n\n> `certbot --nginx` edits `/etc/nginx/sites-available/peertube-browser` in place. When this guide later changes that file, merge the change into it rather than copying the block over it (section 6), or run `sudo certbot --nginx` again afterwards.\n\n### 5. `DEPLOYMENT.md` \u00a73 (replaces lines 299\u2013303, as one line)\n\n> Every page is a separate build input, so adding one means rebuilding and re-copying: nginx serves `dist/` through `try_files`, and a page missing from the document root is a 404 rather than a fallback. After adding or changing a page, re-run this build and repeat the `rsync` in section 6. The current pages are `index`, `videos`, `search`, `likes`, `video-page`, `channels` and `about`. About is the exception to the one-file-per-URL layout: it is built as `dist/dev-pages/about.html` when the local override exists, otherwise as `dist/dev-pages/about.template.html` (`client/frontend/README.md`), and is reached at `/about`, `/about/` and `/about.html` only through the About locations in section 6.\n\nI rewrote the paragraph as one line, following the no-softwrap rule. Most recent paragraphs in this file are already single lines.\n\n### 6. `DEPLOYMENT.md` Triage table: two rows appended after line 229\n\n```\n| `/about`, `/about/` or `/about.html` answers 404 while `/` answers 200 | The live site file lacks the About locations, or the document root has no `dev-pages/about*.html` | Merge the About locations into the site file (section 6), or rebuild and sync (section 3) |\n| An About visit has no line in `peertube-browser.pages.access.log`, or none in `peertube-browser.access.log` | The request went to `/dev-pages/about*.html` directly, or one of the About location's two `access_log` lines is missing | Section 6; the location must list both logs |\n```\n\n### 7. `DEPLOYMENT.md` Triage: \"What each log is for\", new bullet after line 244\n\n> - The pages log, `/var/log/nginx/peertube-browser.pages.access.log`, records About visits only: one `page=about` line per request, beside its usual line in the access log. About makes no API call, so this is the only record of a visit (see \"Follow an About visit\").\n\n### 8. `DEPLOYMENT.md` Triage: new subsection after line 249, before \"Centralized installer\"\n\n````\n### Follow an About visit\n\nAbout is static and makes no API call, so a visit leaves no app record. nginx writes it to `/var/log/nginx/peertube-browser.pages.access.log` (section 6) as one line per request:\n```\npage=about ts=1700000000.123 time=2023-11-14T22:13:20+00:00 ip=203.0.113.7 method=GET status=200 rt=0.000 request_id=3f2a\u2026 uri=\"/about.html\" x_request_id=- ua=\"Mozilla/5.0 \u2026\"\n```\n`ts` is the epoch in seconds with milliseconds, which is UTC. `time` is the server's local time, to the second. `x_request_id` is the `X-Request-ID` the request arrived with, or `-`. The first eight fields have a fixed form. `uri`, `x_request_id` and `ua` come from the client and can contain spaces and look-alike tokens, so match by field position, as below, not with a plain `grep`.\n\nList visits, optionally only successful page loads:\n```bash\nsudo awk '$1 == \"page=about\"' /var/log/nginx/peertube-browser.pages.access.log\nsudo awk '$1 == \"page=about\" && $5 == \"method=GET\" && $6 == \"status=200\"' /var/log/nginx/peertube-browser.pages.access.log\n```\nNav links arrive as `uri=\"/about.html\"`; `/about` and `/about/` are typed or shared URLs.\n\nFind the same visit's access-log line by its id:\n```bash\nid=<request_id of the visit>\nsudo grep \"request_id=$id\" /var/log/nginx/peertube-browser.access.log\n```\n\nFind the visitor's later API requests in the Client backend by client address and a time window after the visit (5 minutes here; widen `window` by hand):\n```bash\nline=$(sudo awk -v id=\"request_id=$id\" '$1 == \"page=about\" && $8 == id' /var/log/nginx/peertube-browser.pages.access.log)\nip=$(printf '%s\\n' \"$line\" | awk '{ sub(/^ip=/, \"\", $4); print $4 }')\nmsec=$(printf '%s\\n' \"$line\" | awk '{ sub(/^ts=/, \"\", $2); print $2 }')\nwindow=300\nfrom=$(date -u -d \"@$msec\" +%Y-%m-%dT%H:%M:%S.%3NZ)\nto=$(date -u -d \"@$(( ${msec%.*} + window )).${msec#*.}\" +%Y-%m-%dT%H:%M:%S.%3NZ)\njournalctl -u peertube-client.service -o cat | jq -cR --arg ip \"$ip\" --arg from \"$from\" --arg to \"$to\" 'fromjson? | select(.event == \"request.start\" and .context.ip == $ip and .ts >= $from and .ts <= $to)'\n```\nThe apps' `ts` is fixed-width UTC (section 2), so comparing it as a string orders it correctly. With `LOG_FORMAT=text`:\n```bash\njournalctl -u peertube-client.service -o cat | awk -v from=\"$from\" -v to=\"$to\" '$3 == \"request.start\" && $1 >= from && $1 <= to' | grep -F \" ip=$ip \"\n```\nKeep the spaces around `ip=$ip`, or `1.2.3.4` also matches `1.2.3.45`. Take `request_id` from a matching record and continue with \"Follow one request\" to reach the Engine.\n\nCaveats:\n- A visit shares no id with the visitor's API requests. About makes none, and nginx gives every request its own `$request_id`, so the match is by address and time only and is probabilistic. Visitors behind one NAT or shared address match each other's requests, and a visitor who leaves without opening another page has no Client record at all.\n- The Client's `ip` is the address it resolves through `X-Forwarded-For` and `TRUSTED_PROXIES` (section 6), and it equals nginx's `ip` only when nginx is the only proxy. Behind a CDN or load balancer, nginx's `ip` is that layer's address and the Client's is the visitor's, so the two do not match. IPv6 and IPv4-mapped addresses (`::ffff:1.2.3.4`) can also be written differently in the two logs.\n- nginx's `ts` is epoch seconds and `time` is local time. The apps' `ts` is UTC `YYYY-MM-DDTHH:MM:SS.mmmZ`. Convert with `date -u` as above before comparing, never `time`.\n- Bots and crawlers are logged like visitors. The `ua` field is the only filter, and a client can put anything in it. In text mode, `user_agent` follows `ip` unquoted, so a user agent can also forge an ` ip=\u2026 ` token. JSON mode does not have this weakness. A client-side pageview beacon on the endpoint that `docs/project/issues/18-about-outbound-click-tracking.md` introduces would count human visits more cleanly. That is the upgrade path, not a second endpoint.\n````\n\n**Checked against the code.** `_render_text` writes `ts LEVEL event message k=v\u2026`. `$3` is the event, and the message \"request started\" comes after it, so `$1` and `$3` are positional before any free text. Context order is `ip`, `method`, `url`, `user_agent` (`server.py:346-349`), so `ip=` is always followed by ` method=` and the trailing space is reliable. `$msec` always has a 3-digit fraction, so `${msec%.*}` and `${msec#*.}` split it safely, and `@<int>.<frac>` is GNU `date` syntax.\n\n### 9. `DEPLOYMENT.md` \u00a72 (line 116)\n\nThe pointer sentence at the end of the paragraph becomes: \"To read every line of one request across nginx, the Client backend and the Engine, see \"Follow one request\" under Triage; to tie an About visit, which has no app record, to the visitor's later requests, see \"Follow an About visit\".\"\n\n### 10. `DEPLOYMENT.md` \u00a77 (after line 564)\n\nNew bullet: `- `/about` (About; `/about/` and `/about.html` serve the same page)`.\n\n### 11. `client/frontend/README.md` \"Local About Overrides\" (lines 36\u201339)\n\nThe existing three bullets stay. Two new bullets are appended:\n\n```\n- The build emits whichever source it used under `dist/dev-pages/` with the same name. In production nginx serves the override if present, otherwise the template, at `/about`, `/about/` and `/about.html` (`DEPLOYMENT.md` section 6), and logs each visit to its pages log.\n- Because the same file is served at `/about/`, an override must use root-absolute URLs (`/favicon.png`, `/src/\u2026`, `/about.html`); relative ones resolve under `/about/` there. It gets only nginx's `Content-Security-Policy` header (`script-src 'self'`), so inline scripts are blocked.\n```\n\n### 12. Test contract: `tests/active/test_static_page_visit_logs.py`\n\nThe test step writes this file; the contract is fixed here.\n\n**Helpers**\n- `_site_block()` takes the first fenced ```` ```nginx ```` block after the line containing `` `/etc/nginx/sites-available/peertube-browser`: ``. That is the right block, not the upstream snippet.\n- `_statements()` is copied from `test_install_engine_service.py:141-145`.\n- `_runbook()` takes the fenced `bash` blocks under `### Follow an About visit`.\n\n**Wrapper config.** It is written to `tmp/nginx.conf` and run with `nginx -p tmp -e tmp/error.log -c tmp/nginx.conf`:\n- `pid`, `events {}`;\n- `http { client_body_temp_path`, `proxy_temp_path`, `fastcgi_temp_path`, `uwsgi_temp_path`, `scgi_temp_path` under tmp;\n- `include <the block> }`.\n\n**Substitutions** are made on directive tokens, not lines:\n- `root` \u2192 `tmp/www`;\n- every `/var/log/nginx/` (the server-level line and both About lines) \u2192 `tmp/log/`;\n- `listen 80` \u2192 `listen 127.0.0.1:<free port>`.\n\n**Skip rules.** Tests that need nginx are skipped when `shutil.which(\"nginx\") is None`. jq tests are skipped without `jq`. The live-server tests are also skipped if nginx refuses to start unprivileged.\n\n| Test | Asserts |\n|---|---|\n| `test_site_block_passes_nginx_t` | `nginx -t` exits 0 on the wrapped block |\n| `test_about_urls_serve_page_with_csp` (param `/about`, `/about/`, `/about.html`, `/about.html?x=1`; GET and HEAD) | 200, the template's bytes for GET, a `Content-Security-Policy` header equal to the block's value |\n| `test_override_preferred_and_404_without_files` | With both files, the override is served. With neither, 404 with CSP, and still one pages line with `status=404` |\n| `test_each_about_request_logs_once_per_file` | After polling, exactly one new pages line and one new main line per request. Fields 1\u20138 are `page=about`, `ts=<d+.ddd>`, `time=`, `ip=127.0.0.1`, `method=`, `status=`, `rt=`, `request_id=<32 hex>`. `uri=` is the requested path plus query. The main line carries the same `request_id`. `x_request_id=-` without the header, and the sent value with it |\n| `test_forged_user_agent_does_not_move_fields` | A UA ` status=200 method=GET page=about` on a 404 request leaves `$6 == status=404`, and the runbook's awk filter excludes it |\n| `test_other_routes_write_no_pages_line` (`/`, `/index.html`, `/api/health` \u2192 502, `/dev-pages/about.template.html`) | No new pages line; each still writes one main line |\n| `test_about_mapping_matches_vite` (no nginx needed) | The exact-location URLs equal the string set in `rewriteToAbout` in `vite.config.ts`, and the `try_files` candidates are `/dev-pages/` plus the two names `aboutSourcePath` chooses between |\n| `test_runbook_finds_visit_and_client_record` (needs jq, bash, GNU date) | Builds a pages line and a `request.start` record from the real `ClientLogFormatter` in JSON and text, with `record.created` = visit + 10 s, plus a decoy outside the window and a decoy on `1.2.3.45`. Running the runbook's `from`/`to`/jq/awk commands (journalctl swapped for `cat file`) selects exactly the in-window record |\n\n**`config.json` entry:**\n\n```json\n\"test_static_page_visit_logs.py\": [\n  \"DEPLOYMENT.md\",\n  \"client/frontend/vite.config.ts\",\n  \"client/backend/server.py\"\n]\n```\n\n`server.py` is listed because the runbook test uses `ClientLogFormatter`, so a change to `ts` or the context shape selects the test.\n\n### 13. Tracker edits at completion\n\n**`docs/project/issues/21-static-page-visit-logs.md`.** Set `Status: enhancement, complete`, add the comment below under `## Comments`, then move the file to `docs/project/issues/archive/`. The move deletes the original; the build that lands this must have a delete, unlike the issue-20 build.\n\n> - Delivered by `docs/project/plans/22-21-static-page-visit-logs.md`. About now serves in prod: public nginx answers `/about`, `/about/` and `/about.html` from `dev-pages/about.html` or `dev-pages/about.template.html` with the site's CSP, where `/about.html` used to be a 404. Each About request writes one `page=about` line to `/var/log/nginx/peertube-browser.pages.access.log` (`ts` epoch ms, local `time`, `ip`, `method`, `status`, `rt`, `request_id`, `uri`, `x_request_id` or `-`, `ua`) as well as its usual access-log line with the same `request_id`. `DEPLOYMENT.md` \"Follow an About visit\" lists visits and ties one to the visitor's Client `request.start` records by address and a time window, with its caveats. Only About is covered, and the client-side pageview beacon remains the upgrade path on issue 18's endpoint.\n\n**`docs/project/issues/plan.md`**\n- Line 42: \"19, 20 and 21 are delivered (see triage). None of these block other work.\"\n- Line 98: Main files \"nginx docs (21); the About template, one Client endpoint (18)\"; Depends on \"20. 21 delivered, see `docs/project/plans/22-21-static-page-visit-logs.md`.\"\n\n**`docs/project/issues/18-about-outbound-click-tracking.md`**, new comment:\n\n> - Issue 21 (`DEPLOYMENT.md` \"Follow an About visit\") names this issue's beacon endpoint as the upgrade path for counting human About pageviews. If the endpoint stays outbound-click-only (`/api/analytics/outbound-click`), a pageview needs its own event type there. 21 added no endpoint.\n\n---\n\n### Ladder check\n\n**Pass 1.** Problems found in the first draft:\n- The listing used an unanchored `grep 'page=about'` with `' status=200 '`, which a client can spoof. Replaced by positional `awk` on `$1`, `$5` and `$6`.\n- `uri` came before `status`. Moved behind the fixed fields.\n- The text variant matched `ip=$ip` without delimiters. Now `\" ip=$ip \"` with `grep -F`.\n- The window's end was computed with `date -d \"@x + 300 seconds\"`, which is unreliable. Replaced with bash integer arithmetic on `${msec%.*}`.\n- \"Re-apply \u00a76\" read as an overwrite. Replaced with a merge instruction plus the certbot warning.\n\n**Pass 2.** Every requirement is met:\n\n| Requirement | Where |\n|---|---|\n| Three URLs answer 200 | \u00a71 locations |\n| Override \u2192 template \u2192 404 | \u00a71 `try_files` |\n| CSP | \u00a71, no `add_header` |\n| Other routes unchanged | `=` matches only; existing locations byte-identical |\n| Separate file, both logs | \u00a71, two `access_log` lines |\n| Every listed field incl. `x_request_id` `-` | \u00a71 format |\n| All methods and statuses | Logging in the location's log phase |\n| Rotation stated | \u00a72 |\n| Runbook steps and four caveats | \u00a78 |\n| Docs | \u00a72\u2013\u00a711 and \u00a713 |\n| Validation: `nginx -t`, skip without nginx, line counts, runbook correlation, suite | \u00a712 |\n\nEvery plan point is covered: the format and `set` variable, the alias rewrites, the prose, the runbook and `$msec` with `date -u`. Every settled impact is covered as well: TLS, Verify, the `config.json` group, the vite drift test, the archive move, plan.md and the issue 18 comment. Nothing is left open, so the draft converged in two passes.\n\n### Simplifications named\n\n- **Timestamp.** The line carries `$msec` (exact UTC) and local `$time_iso8601` rather than a ready UTC ISO-ms string, and the runbook converts with one `date -u`. The ceiling is one manual step per lookup. Upgrade path: a `map` that builds the string on hosts set to UTC.\n- **Correlation is by address and time only.** The ceiling is NAT, shared addresses and visitors who leave without another request. The upgrade path is issue 18's beacon.\n- **The nginx block mirrors vite's mapping.** It is kept in step by a test rather than shared code, and is marked `rat-tail:` in the block. The upgrade is building About as `dist/about.html`, which is out of scope here.\n",
  "coordination": "none",
  "tests": {
    "tests/tmp/test_21_static_page_visit_logs_phase1.py": {
      "rows": [
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_21_static_page_visit_logs_phase1.py:153 \u2014 in the override-and-template, override-only and template-only cases, GET and HEAD on /about, /about/, /about.html and /about.html?x=1 each answer (200, [block CSP], str(len(body)), body for GET / b\"\" for HEAD). The body is the override's when it exists, otherwise the template's.",
          "expected": "A probe spliced `location = {url} { try_files /dev-pages/about.html /dev-pages/about.template.html =404; }` for each of the three URLs into the \u00a76 block and ran this function. All three 200 cases passed: the override (49 bytes) when present, the template bytes when it was alone, and exactly one CSP header equal to the block's. Against the unchanged block, the run fails here with 'GET /about': (404, [csp], ..., nginx 404 page) != (200, [csp], '49', OVERRIDE).",
          "wrong_implementation": "Template listed before the override in try_files: the probe went red here in override-and-template, because the template's bytes were served. Template-only try_files: red here, because the override was ignored. A location-level `add_header` (X-Frame-Options), which drops the inherited server CSP: red here with an empty CSP list. Today's block with no About locations: 404 on every URL, red here in all three cases (observed)."
        },
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_21_static_page_visit_logs_phase1.py:150 \u2014 in the neither case, every GET/HEAD on the four About URLs answers (404, [block CSP]).",
          "expected": "(404, [csp]) for all 8 requests. Observed both against the current block, where this case passes, and against the probe's right block, where it also passes.",
          "wrong_implementation": "An SPA-style fallback (`try_files /dev-pages/about.html /dev-pages/about.template.html /index.html`): the probe went red here only, with 200 and index.html. The three 200 cases still passed."
        },
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_21_static_page_visit_logs_phase1.py:154 \u2014 GET /aboutx, /about/x and /about.htm answer (404, [block CSP]) in every case.",
          "expected": "(404, [csp]) for each of the three. Observed against the current block and against the probe's right block.",
          "wrong_implementation": "A prefix `location /about { try_files ... }` instead of exact locations: the probe passed line 153 and went red here, because /aboutx and /about/x served About."
        },
        {
          "clause": "C2",
          "assertion": "tests/tmp/test_21_static_page_visit_logs_phase1.py:168 \u2014 the sorted `location =` URLs of the \u00a76 block equal the sorted rewriteToAbout entries parsed from vite.config.ts, each once.",
          "expected": "['/about', '/about.html', '/about/'] on both sides. The probe's right block passed. Against the current block the run fails here with `assert [] == ['/about', '/...l', '/about/']`.",
          "wrong_implementation": "A block missing one URL (e.g. no `location = /about/`), duplicating one, adding one vite does not rewrite, or a block with no About locations at all reads a different list. The last case is observed: []."
        },
        {
          "clause": "C2",
          "assertion": "tests/tmp/test_21_static_page_visit_logs_phase1.py:170 \u2014 each exact location has exactly one try_files, and its candidates before the fallback are [aboutSourcePath's existing-branch pick, its else-branch pick].",
          "expected": "{url: [['/dev-pages/about.html', '/dev-pages/about.template.html']]} for each of the three URLs. The probe's right block passed this test.",
          "wrong_implementation": "Swapped candidate order reads [['/dev-pages/about.template.html', '/dev-pages/about.html']]. A template-only try_files reads [['/dev-pages/about.template.html']]. A try_files with no `=404` fallback reads the override alone. All of these differ from vite's two picks in order. (The probe ran C2 only on the right variant, where it passed; for the wrong variants this column is reasoned from the parse, not observed.)"
        }
      ],
      "clauses": [
        {
          "id": "C1",
          "text": "Each of /about, /about/ and /about.html returns the dev-pages override if it exists, otherwise the template, otherwise a 404, and every one of those responses carries the server-level Content-Security-Policy."
        },
        {
          "id": "C2",
          "text": "The block's exact-location URLs and try_files candidates equal the About mapping in client/frontend/vite.config.ts (rewriteToAbout and aboutSourcePath)."
        }
      ],
      "surface": "checkpoint",
      "results": {
        "command": "validate_tests.py tests/tmp/test_21_static_page_visit_logs_phase1.py",
        "code": 1,
        "output": "  tests/tmp/test_21_static_page_visit_logs_phase1.py  4 failed, 1 passed                     0.0s\n  --------------------------------------------------\n  total                                               4 failed, 1 passed                     0.5s wall, 1 lane\n\nrecorded: tests/last_test_validation.json (exit 1)\nwrote tests/last_test_output.txt"
      }
    },
    "tests/tmp/test_21_static_page_visit_logs_phase2.py": {
      "rows": [
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_21_static_page_visit_logs_phase2.py:167 \u2014 runs GET and HEAD on /about, /about/, /about.html and /about.html?x=1, each with and without X-Request-ID (16 requests per row). Checked in two rows: template only (200) and no dev-pages files (404). For each request it checks the status, exactly 1 new main-log line and exactly 1 new pages-log line.",
          "expected": "(200, 1, 1) for all 16 keys in template-200, and (404, 1, 1) for all 16 in no-files-404. Observed: the probe spliced the plan's draft block (pages log_format plus both access_log lines in the About location) into this checkpoint, and `test_probe[about-good] PASSED`. Against the current \u00a76 block every key reads (200, 1, 0) or (404, 1, 0).",
          "wrong_implementation": "About location lists only the pages access_log and drops the main one; a location-level access_log replaces the inherited one, so About falls out of the main log. Observed in the probe (`about-pages-only`): every key reads (200, 0, 1), red at :167. With no pages log at all, which is the current block, it reads (200, 1, 0)."
        },
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_21_static_page_visit_logs_phase2.py:169 \u2014 checked over the same 32 requests:\n- Pages fields 1\u20138 fullmatch `page=about ts=\\d+\\.\\d{3} time=<ISO 8601 with offset> ip=127.0.0.1 method=<sent method> status=<code> rt=\\d+\\.\\d{3} request_id=<32 hex>`.\n- uri= is the requested path plus query.\n- x_request_id= is the sent \"client-sent-7\" or \"-\".\n- ua= is the sent agent.\n- The request's own main line is `\"<method> <url> HTTP/1.1\" <code>`, and its request_id equals the pages line's.",
          "expected": "For every key: {\"head\": (method, str(code)), \"uri\": url, \"x_request_id\": sent or \"-\", \"ua\": \"probe-agent/1\", \"main\": (f\"{method} {url} HTTP/1.1\", str(code)), \"same_request_id\": True}. Observed: equal for all 32 under the plan's draft block (`about-good PASSED`).",
          "wrong_implementation": "A pages format that logs `uri=\"$uri\"` instead of `$request_uri`. That records the rewritten try_files target and drops the query. Observed in the probe (`about-uri-var`): uri reads '/dev-pages/about.template.html' for ('HEAD', '/about', ...) and ('HEAD', '/about.html?x=1', None), red at :169. A request_id taken from `$http_x_request_id` would read \"-\" or \"client-sent-7\". That fails the 32-hex fullmatch, so \"head\" becomes the raw text and same_request_id becomes False."
        },
        {
          "clause": "C2",
          "assertion": "tests/tmp/test_21_static_page_visit_logs_phase2.py:181 \u2014 in one run, with both dev-pages files present, GETs to /about.html, /, /index.html, /api/health, /dev-pages/about.html and /dev-pages/about.template.html. For each URL it checks (status, the new main lines parsed to (request line, status), the new pages-line count) against the routes table: About gives 1 pages line, every other route gives 0.",
          "expected": "{'/about.html': (200, [('GET /about.html HTTP/1.1', '200')], 1), '/': (200, [('GET / HTTP/1.1', '200')], 0), '/index.html': (200, [...], 0), '/api/health': (502, [('GET /api/health HTTP/1.1', '502')], 0), '/dev-pages/about.html': (200, [...], 0), '/dev-pages/about.template.html': (200, [...], 0)}. Observed: equal under the draft block (`other-good PASSED`). In the checkpoint run the 5 non-About rows are already these values (\"Omitting 5 identical items\"), and only About's pages count differs.",
          "wrong_implementation": "The pages access_log put at server level, so every route writes it. Observed in the probe (`other-server-level`): '/', '/index.html', '/api/health' (502) and '/dev-pages/about.template.html' each read pages count 1, red at :181. With no pages log at all (the current block) the About row reads 0 instead of 1, so a dead pages file cannot pass either."
        }
      ],
      "clauses": [
        {
          "id": "C1",
          "text": "Each About request, of any method or status, writes exactly one pages-log line and exactly one main-log line, and both carry the same request_id."
        },
        {
          "id": "C2",
          "text": "Requests to /, /index.html, /api/ and /dev-pages/about*.html write no pages-log line and still write one main-log line each."
        }
      ],
      "surface": "checkpoint",
      "results": {
        "command": "validate_tests.py tests/tmp/test_21_static_page_visit_logs_phase2.py",
        "code": 1,
        "output": "  tests/tmp/test_21_static_page_visit_logs_phase2.py  3 failed                               0.0s\n  --------------------------------------------------\n  total                                               3 failed                               4.2s wall, 1 lane\n\nrecorded: tests/last_test_validation.json (exit 1)\nwrote tests/last_test_output.txt"
      }
    },
    "tests/tmp/test_21_static_page_visit_logs_phase3.py": {
      "rows": [
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_21_static_page_visit_logs_phase3.py:252. Each runbook line that names peertube-browser.pages.access.log and contains GET and 200 is run under bash against the real nginx pages log, and prints exactly [the real GET /about.html 200 line]. That log holds three lines: GET /about.html 200, HEAD /about 200, and a GET /about/ 404 whose UA carries both ` status=200 method=GET page=about ` and the real-order ` method=GET status=200 rt=0.000 ` (controls :243, :245, :247).",
          "expected": "{filter_line: [the GET /about.html 200 pages line]} for every such line. Observed with the plan's draft `awk '$1 == \"page=about\" && $5 == \"method=GET\" && $6 == \"status=200\"'`: PASSED.",
          "wrong_implementation": "A substring filter such as `grep ' method=GET ' | grep ' status=200 '` lists the forged 404 too (earlier probe). A contiguous real-order grep `grep '^page=about ' | grep ' method=GET status=200 '` and `grep -E '^page=about .* method=GET status=200 rt='` also list the forged 404, and both were observed FAILED at :252. A filter on status alone lists the HEAD line. A runbook with no such line reads {} against the placeholder key."
        },
        {
          "clause": "C2",
          "assertion": "tests/tmp/test_21_static_page_visit_logs_phase3.py:292 (JSON) and :293 (text). The pages log holds three visits: 198.51.100.9 at V\u2212120 s, 1.2.3.4 at V with VISIT_ID, and 1.2.3.45 at V+15 s. The Client log is rendered by the real ClientLogFormatter and holds request.start records from 1.2.3.4 at V\u22125 s, V\u221260 s, V+10 s and V+3600 s, and from 1.2.3.45 at V+20 s, each followed by its request.end. The whole runbook, given VISIT_ID, prints exactly one Client record.",
          "expected": "[the formatter's rid-match (V+10 s) request.start], as a parsed dict in JSON and as the text line in text. Observed with the plan's draft: PASSED.",
          "wrong_implementation": "A window reaching back (\u00b130 s) also prints the V\u22125 s record: observed FAILED at the C2 assertion. Conversion without -u: FAILED (earlier probe). `ip=$ip` without the trailing space, or jq without the .context.ip test, also prints the 1.2.3.45 record: FAILED. `tail -n 1` for the visit line lands on the neighbour: FAILED. Printing request.end as well gives two records and fails the list equality."
        }
      ],
      "clauses": [
        {
          "id": "C1",
          "text": "The runbook's listing filter, which selects by field position, does not list a 404 About request whose user agent carries forged status=200, method=GET and page=about tokens as a successful GET."
        },
        {
          "id": "C2",
          "text": "The runbook's correlation commands select exactly the visitor's in-window request.start record from real ClientLogFormatter output in both JSON and text modes."
        }
      ],
      "surface": "checkpoint",
      "results": {
        "command": "validate_tests.py tests/tmp/test_21_static_page_visit_logs_phase3.py",
        "code": 1,
        "output": "  tests/tmp/test_21_static_page_visit_logs_phase3.py  2 failed                               0.0s\n  --------------------------------------------------\n  total                                               2 failed                               0.7s wall, 1 lane\n\nrecorded: tests/last_test_validation.json (exit 1)\nwrote tests/last_test_output.txt"
      }
    }
  },
  "audits": {
    "tests/tmp/test_21_static_page_visit_logs_phase1.py": [
      {
        "shape": "SHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. absence-only-assertion (rules/shape.md) \u2014 tests/tmp/test_21_static_page_visit_logs_phase1.py:150\n   assert {key: answer[:2] for key, answer in got.items()} == {key: (404, [csp]) for key in got}\n   Only the `neither` row reaches this line. Its result is the same with or without the About locations: today `location /` already returns 404 with the CSP for /about, /about/ and /about.html. The positive control at line 145 shows the harness works, not that the About path ran. The proof that the About path ran comes from the other parametrize rows (`override-and-template`, `override-only`, `template-only`), which fail on line 153 against an absent implementation. That matches the entry's third `<how_to_spot>` bullet for this one row only. The test function as a whole is not absence-only, so this is not Critical. Expect this row to be green when the build checks the red. The response cannot tell \"About locations falling to =404\" apart from \"no About locations\", so no extra assertion on this row can close that gap.\n\nPREDICTED FAILURE\n`test_about_urls_serve_override_then_template_then_404_with_csp[override-and-template|override-only|template-only]` fails at line 153: every About GET/HEAD answers `(404, [csp], ...)` instead of 200 with the override's or template's bytes, because the \u00a76 block (DEPLOYMENT.md:418-458) has no `location =` About entries. The `[neither]` row passes. `test_about_mapping_matches_vite` fails at line 168: `sorted([])` is compared with `['/about', '/about.html', '/about/']`, because `exact` finds no `location =` in the block.\n\nNOT ASSESSED\n1. `code_under_test` lists tests/active/test_static_page_visit_logs.py as NEW. It does not exist (Glob found no match), so it was not read. The test under audit does not import it.\n2. `code_under_test` lists .un/skills/devsecops/config.json. It was not read because the test under audit does not touch it, so it has no bearing on this test's assertion form.",
        "claim": "CLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (24 clauses: 7 must_prove, 14 docstring, 3 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | /about, /about/ and /about.html return the dev-pages override \"if it exists\" | :153 (params override-and-template, override-only) | serving the template, or index.html, when the override is present. Bytes and Content-Length differ (control :131), so GET and HEAD both catch it | CARRIED |\n| C1b | must_prove | \"otherwise the template\" | :153 (param template-only) | a 404 or an index.html fallback when only the template exists | CARRIED |\n| C1c | must_prove | \"otherwise a 404\" | :150 (param neither) | a fallback to /index.html, which exists in www (:129), or any other 200 | CARRIED |\n| C1d | must_prove | each of the three URLs, not just one | :150, :153: dict keyed per method and URL over ABOUT_URLS (:146) | covering /about but leaving /about/ or /about.html to fall to `location /` (404) | CARRIED |\n| C1e | must_prove | every response carries the server-level CSP | :150, :153 (`[csp]`), :154; csp is read from the block's add_header (:124) | a location-level `add_header` that drops the inherited server CSP, a CSP missing on the 404, a second or different CSP value | CARRIED |\n| C2a | must_prove | the block's exact-location URLs equal rewriteToAbout | :168 | a missing or extra `location =` URL, a duplicate, or a list hard-coded apart from vite (both sides are parsed live, :160/:167) | CARRIED |\n| C2b | must_prove | the try_files candidates equal aboutSourcePath | :170 | template-first order, a missing pick, a `$uri` candidate, or two try_files in one location | CARRIED |\n| D1 | docstring | \"`nginx -t` accepts the block\" | :142 | a block that does not load | CARRIED |\n| D2 | docstring | \"GET and HEAD on each About URL\" | :146, :153 (HEAD expects b\"\" body and the file's Content-Length) | HEAD answered differently from GET | CARRIED |\n| D3 | docstring | \"/about.html?x=1\" is answered as About | :153 / :150 via ABOUT_URLS (:29) | an exact match broken by a query string | CARRIED |\n| D4 | docstring | \"with the override (alone or beside the template)\" | :153 over two params (:119) | override served only when the template is absent, or the reverse | CARRIED |\n| D5 | docstring | \"the override's bytes and Content-Length\" | :153 | right status but wrong body or length | CARRIED |\n| D6 | docstring | \"with only the template, 200 with the template's\" | :153 (template-only) | 404, or override expected but absent | CARRIED |\n| D7 | docstring | \"with neither, 404\" | :150 | 200 fallback | CARRIED |\n| D8 | docstring | \"exactly one Content-Security-Policy header, equal to the block's\" | :150, :153 (list `[csp]`, all headers collected at :114) | zero, two, or a differing CSP header | CARRIED |\n| D9 | docstring | \"/aboutx, /about/x and /about.htm stay 404 with the CSP\" | :154 | a prefix or regex location that also captures neighbours | CARRIED |\n| D10 | docstring | \"`location =` URLs are rewriteToAbout's, once each\" | :168 | duplicates, since sorted lists are compared | CARRIED |\n| D11 | docstring | \"try_files candidates before the fallback are aboutSourcePath's two picks, the override first\" | :170 | reversed order, a single pick, extra candidates | CARRIED |\n| D12 | docstring | \"the block is the first ```nginx fence after the sites-available line\" | :39, :41 | auditing a different fence, or none | CARRIED |\n| D13 | docstring | root, log directory and `listen 80` are swapped for tmp paths | :137 | an unswapped token silently left (port 80, /var/log) | CARRIED |\n| D14 | docstring | \"Skipped when nginx is missing or will not run unprivileged\" | :74, :80 (pytest.skip, not an assertion) | describes the harness, not the code; nothing to exclude | CARRIED |\n| N1 | name | \"about_urls_serve_override_then_template_then_404\" | :150, :153 | wrong precedence or wrong fallback | CARRIED |\n| N2 | name | \"with_csp\" | :150, :153, :154 | a response without the block's CSP | CARRIED |\n| N3 | name | \"about_mapping_matches_vite\" | :168, :170 | drift between the nginx block and vite.config.ts | CARRIED |\n\nRows D1\u2013D14 count each docstring clause once. The module docstring (:1\u20136) and the two function docstrings (:121, :158) say the same things.\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. bounds (rules/testing.md) \u2014 tests/tmp/test_21_static_page_visit_logs_phase1.py:29\n   The URL edges cover a query string and three near-misses (:31). They do not cover a trailing variant of the exact form (`/about.html/`) or a case variant (`/About`). Both are cheap to add to NOT_ABOUT_URLS and would pin that only the three exact URLs are About. This is not a gap in any must_prove clause.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. Whether nginx is installed and runs unprivileged where this checkpoint will run could not be checked: the sandbox blocks reads outside the project. The C1 test skips without such an nginx (:74, :80). A skip proves C1a\u2013C1e nothing, so the checkpoint only stands for C1 where nginx actually runs. Its clause rows above were judged from the test as written.\n2. Two `code_under_test` paths do not exist yet: tests/active/test_static_page_visit_logs.py (Glob: no match) and the `test_static_page_visit_logs.py` group in .un/skills/devsecops/config.json (Grep: no match). The test under audit references neither, so this verdict is unaffected.\n3. The \u00a76 block in DEPLOYMENT.md (:414\u2013459) has no `location =` About entries yet. The test was judged on what it asserts, not on whether the current block passes it.",
        "body": "### devsecops-test-shape-auditor\n\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. absence-only-assertion (rules/shape.md) \u2014 tests/tmp/test_21_static_page_visit_logs_phase1.py:150\n   assert {key: answer[:2] for key, answer in got.items()} == {key: (404, [csp]) for key in got}\n   Only the `neither` row reaches this line. Its result is the same with or without the About locations: today `location /` already returns 404 with the CSP for /about, /about/ and /about.html. The positive control at line 145 shows the harness works, not that the About path ran. The proof that the About path ran comes from the other parametrize rows (`override-and-template`, `override-only`, `template-only`), which fail on line 153 against an absent implementation. That matches the entry's third `<how_to_spot>` bullet for this one row only. The test function as a whole is not absence-only, so this is not Critical. Expect this row to be green when the build checks the red. The response cannot tell \"About locations falling to =404\" apart from \"no About locations\", so no extra assertion on this row can close that gap.\n\nPREDICTED FAILURE\n`test_about_urls_serve_override_then_template_then_404_with_csp[override-and-template|override-only|template-only]` fails at line 153: every About GET/HEAD answers `(404, [csp], ...)` instead of 200 with the override's or template's bytes, because the \u00a76 block (DEPLOYMENT.md:418-458) has no `location =` About entries. The `[neither]` row passes. `test_about_mapping_matches_vite` fails at line 168: `sorted([])` is compared with `['/about', '/about.html', '/about/']`, because `exact` finds no `location =` in the block.\n\nNOT ASSESSED\n1. `code_under_test` lists tests/active/test_static_page_visit_logs.py as NEW. It does not exist (Glob found no match), so it was not read. The test under audit does not import it.\n2. `code_under_test` lists .un/skills/devsecops/config.json. It was not read because the test under audit does not touch it, so it has no bearing on this test's assertion form.\n\n### devsecops-test-claim-auditor\n\nCLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (24 clauses: 7 must_prove, 14 docstring, 3 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | /about, /about/ and /about.html return the dev-pages override \"if it exists\" | :153 (params override-and-template, override-only) | serving the template, or index.html, when the override is present. Bytes and Content-Length differ (control :131), so GET and HEAD both catch it | CARRIED |\n| C1b | must_prove | \"otherwise the template\" | :153 (param template-only) | a 404 or an index.html fallback when only the template exists | CARRIED |\n| C1c | must_prove | \"otherwise a 404\" | :150 (param neither) | a fallback to /index.html, which exists in www (:129), or any other 200 | CARRIED |\n| C1d | must_prove | each of the three URLs, not just one | :150, :153: dict keyed per method and URL over ABOUT_URLS (:146) | covering /about but leaving /about/ or /about.html to fall to `location /` (404) | CARRIED |\n| C1e | must_prove | every response carries the server-level CSP | :150, :153 (`[csp]`), :154; csp is read from the block's add_header (:124) | a location-level `add_header` that drops the inherited server CSP, a CSP missing on the 404, a second or different CSP value | CARRIED |\n| C2a | must_prove | the block's exact-location URLs equal rewriteToAbout | :168 | a missing or extra `location =` URL, a duplicate, or a list hard-coded apart from vite (both sides are parsed live, :160/:167) | CARRIED |\n| C2b | must_prove | the try_files candidates equal aboutSourcePath | :170 | template-first order, a missing pick, a `$uri` candidate, or two try_files in one location | CARRIED |\n| D1 | docstring | \"`nginx -t` accepts the block\" | :142 | a block that does not load | CARRIED |\n| D2 | docstring | \"GET and HEAD on each About URL\" | :146, :153 (HEAD expects b\"\" body and the file's Content-Length) | HEAD answered differently from GET | CARRIED |\n| D3 | docstring | \"/about.html?x=1\" is answered as About | :153 / :150 via ABOUT_URLS (:29) | an exact match broken by a query string | CARRIED |\n| D4 | docstring | \"with the override (alone or beside the template)\" | :153 over two params (:119) | override served only when the template is absent, or the reverse | CARRIED |\n| D5 | docstring | \"the override's bytes and Content-Length\" | :153 | right status but wrong body or length | CARRIED |\n| D6 | docstring | \"with only the template, 200 with the template's\" | :153 (template-only) | 404, or override expected but absent | CARRIED |\n| D7 | docstring | \"with neither, 404\" | :150 | 200 fallback | CARRIED |\n| D8 | docstring | \"exactly one Content-Security-Policy header, equal to the block's\" | :150, :153 (list `[csp]`, all headers collected at :114) | zero, two, or a differing CSP header | CARRIED |\n| D9 | docstring | \"/aboutx, /about/x and /about.htm stay 404 with the CSP\" | :154 | a prefix or regex location that also captures neighbours | CARRIED |\n| D10 | docstring | \"`location =` URLs are rewriteToAbout's, once each\" | :168 | duplicates, since sorted lists are compared | CARRIED |\n| D11 | docstring | \"try_files candidates before the fallback are aboutSourcePath's two picks, the override first\" | :170 | reversed order, a single pick, extra candidates | CARRIED |\n| D12 | docstring | \"the block is the first ```nginx fence after the sites-available line\" | :39, :41 | auditing a different fence, or none | CARRIED |\n| D13 | docstring | root, log directory and `listen 80` are swapped for tmp paths | :137 | an unswapped token silently left (port 80, /var/log) | CARRIED |\n| D14 | docstring | \"Skipped when nginx is missing or will not run unprivileged\" | :74, :80 (pytest.skip, not an assertion) | describes the harness, not the code; nothing to exclude | CARRIED |\n| N1 | name | \"about_urls_serve_override_then_template_then_404\" | :150, :153 | wrong precedence or wrong fallback | CARRIED |\n| N2 | name | \"with_csp\" | :150, :153, :154 | a response without the block's CSP | CARRIED |\n| N3 | name | \"about_mapping_matches_vite\" | :168, :170 | drift between the nginx block and vite.config.ts | CARRIED |\n\nRows D1\u2013D14 count each docstring clause once. The module docstring (:1\u20136) and the two function docstrings (:121, :158) say the same things.\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. bounds (rules/testing.md) \u2014 tests/tmp/test_21_static_page_visit_logs_phase1.py:29\n   The URL edges cover a query string and three near-misses (:31). They do not cover a trailing variant of the exact form (`/about.html/`) or a case variant (`/About`). Both are cheap to add to NOT_ABOUT_URLS and would pin that only the three exact URLs are About. This is not a gap in any must_prove clause.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. Whether nginx is installed and runs unprivileged where this checkpoint will run could not be checked: the sandbox blocks reads outside the project. The C1 test skips without such an nginx (:74, :80). A skip proves C1a\u2013C1e nothing, so the checkpoint only stands for C1 where nginx actually runs. Its clause rows above were judged from the test as written.\n2. Two `code_under_test` paths do not exist yet: tests/active/test_static_page_visit_logs.py (Glob: no match) and the `test_static_page_visit_logs.py` group in .un/skills/devsecops/config.json (Grep: no match). The test under audit references neither, so this verdict is unaffected.\n3. The \u00a76 block in DEPLOYMENT.md (:414\u2013459) has no `location =` About entries yet. The test was judged on what it asserts, not on whether the current block passes it.",
        "map": [
          {
            "id": "C1a",
            "source": "must_prove",
            "clause": "/about, /about/ and /about.html return the dev-pages override \"if it exists\"",
            "assertion": ":153 (params override-and-template, override-only)",
            "excludes": "serving the template, or index.html, when the override is present. Bytes and Content-Length differ (control :131), so GET and HEAD both catch it",
            "status": "CARRIED"
          },
          {
            "id": "C1b",
            "source": "must_prove",
            "clause": "\"otherwise the template\"",
            "assertion": ":153 (param template-only)",
            "excludes": "a 404 or an index.html fallback when only the template exists",
            "status": "CARRIED"
          },
          {
            "id": "C1c",
            "source": "must_prove",
            "clause": "\"otherwise a 404\"",
            "assertion": ":150 (param neither)",
            "excludes": "a fallback to /index.html, which exists in www (:129), or any other 200",
            "status": "CARRIED"
          },
          {
            "id": "C1d",
            "source": "must_prove",
            "clause": "each of the three URLs, not just one",
            "assertion": ":150, :153: dict keyed per method and URL over ABOUT_URLS (:146)",
            "excludes": "covering /about but leaving /about/ or /about.html to fall to `location /` (404)",
            "status": "CARRIED"
          },
          {
            "id": "C1e",
            "source": "must_prove",
            "clause": "every response carries the server-level CSP",
            "assertion": ":150, :153 (`[csp]`), :154; csp is read from the block's add_header (:124)",
            "excludes": "a location-level `add_header` that drops the inherited server CSP, a CSP missing on the 404, a second or different CSP value",
            "status": "CARRIED"
          },
          {
            "id": "C2a",
            "source": "must_prove",
            "clause": "the block's exact-location URLs equal rewriteToAbout",
            "assertion": ":168",
            "excludes": "a missing or extra `location =` URL, a duplicate, or a list hard-coded apart from vite (both sides are parsed live, :160/:167)",
            "status": "CARRIED"
          },
          {
            "id": "C2b",
            "source": "must_prove",
            "clause": "the try_files candidates equal aboutSourcePath",
            "assertion": ":170",
            "excludes": "template-first order, a missing pick, a `$uri` candidate, or two try_files in one location",
            "status": "CARRIED"
          },
          {
            "id": "D1",
            "source": "docstring",
            "clause": "\"`nginx -t` accepts the block\"",
            "assertion": ":142",
            "excludes": "a block that does not load",
            "status": "CARRIED"
          },
          {
            "id": "D2",
            "source": "docstring",
            "clause": "\"GET and HEAD on each About URL\"",
            "assertion": ":146, :153 (HEAD expects b\"\" body and the file's Content-Length)",
            "excludes": "HEAD answered differently from GET",
            "status": "CARRIED"
          },
          {
            "id": "D3",
            "source": "docstring",
            "clause": "\"/about.html?x=1\" is answered as About",
            "assertion": ":153 / :150 via ABOUT_URLS (:29)",
            "excludes": "an exact match broken by a query string",
            "status": "CARRIED"
          },
          {
            "id": "D4",
            "source": "docstring",
            "clause": "\"with the override (alone or beside the template)\"",
            "assertion": ":153 over two params (:119)",
            "excludes": "override served only when the template is absent, or the reverse",
            "status": "CARRIED"
          },
          {
            "id": "D5",
            "source": "docstring",
            "clause": "\"the override's bytes and Content-Length\"",
            "assertion": ":153",
            "excludes": "right status but wrong body or length",
            "status": "CARRIED"
          },
          {
            "id": "D6",
            "source": "docstring",
            "clause": "\"with only the template, 200 with the template's\"",
            "assertion": ":153 (template-only)",
            "excludes": "404, or override expected but absent",
            "status": "CARRIED"
          },
          {
            "id": "D7",
            "source": "docstring",
            "clause": "\"with neither, 404\"",
            "assertion": ":150",
            "excludes": "200 fallback",
            "status": "CARRIED"
          },
          {
            "id": "D8",
            "source": "docstring",
            "clause": "\"exactly one Content-Security-Policy header, equal to the block's\"",
            "assertion": ":150, :153 (list `[csp]`, all headers collected at :114)",
            "excludes": "zero, two, or a differing CSP header",
            "status": "CARRIED"
          },
          {
            "id": "D9",
            "source": "docstring",
            "clause": "\"/aboutx, /about/x and /about.htm stay 404 with the CSP\"",
            "assertion": ":154",
            "excludes": "a prefix or regex location that also captures neighbours",
            "status": "CARRIED"
          },
          {
            "id": "D10",
            "source": "docstring",
            "clause": "\"`location =` URLs are rewriteToAbout's, once each\"",
            "assertion": ":168",
            "excludes": "duplicates, since sorted lists are compared",
            "status": "CARRIED"
          },
          {
            "id": "D11",
            "source": "docstring",
            "clause": "\"try_files candidates before the fallback are aboutSourcePath's two picks, the override first\"",
            "assertion": ":170",
            "excludes": "reversed order, a single pick, extra candidates",
            "status": "CARRIED"
          },
          {
            "id": "D12",
            "source": "docstring",
            "clause": "\"the block is the first ```nginx fence after the sites-available line\"",
            "assertion": ":39, :41",
            "excludes": "auditing a different fence, or none",
            "status": "CARRIED"
          },
          {
            "id": "D13",
            "source": "docstring",
            "clause": "root, log directory and `listen 80` are swapped for tmp paths",
            "assertion": ":137",
            "excludes": "an unswapped token silently left (port 80, /var/log)",
            "status": "CARRIED"
          },
          {
            "id": "D14",
            "source": "docstring",
            "clause": "\"Skipped when nginx is missing or will not run unprivileged\"",
            "assertion": ":74, :80 (pytest.skip, not an assertion)",
            "excludes": "describes the harness, not the code; nothing to exclude",
            "status": "CARRIED"
          },
          {
            "id": "N1",
            "source": "name",
            "clause": "\"about_urls_serve_override_then_template_then_404\"",
            "assertion": ":150, :153",
            "excludes": "wrong precedence or wrong fallback",
            "status": "CARRIED"
          },
          {
            "id": "N2",
            "source": "name",
            "clause": "\"with_csp\"",
            "assertion": ":150, :153, :154",
            "excludes": "a response without the block's CSP",
            "status": "CARRIED"
          },
          {
            "id": "N3",
            "source": "name",
            "clause": "\"about_mapping_matches_vite\"",
            "assertion": ":168, :170",
            "excludes": "drift between the nginx block and vite.config.ts",
            "status": "CARRIED"
          }
        ],
        "map_problem": ""
      }
    ],
    "tests/tmp/test_21_static_page_visit_logs_phase2.py": [
      {
        "shape": "SHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\nBoth parametrised cases of `test_each_about_request_writes_one_pages_line_and_one_main_line_with_same_request_id` should fail at line 167 on the count comparison. Every About request gives `(code, 1, 0)` where `(code, 1, 1)` is expected, because the current \u00a76 block (DEPLOYMENT.md:414-470) has no pages log, so `peertube-browser.pages.access.log` is never written. `test_other_routes_write_no_pages_line` should fail at line 181 on the `/about.html` row only: it gets `(200, [(\"GET /about.html HTTP/1.1\", \"200\")], 0)` where the expected pages count is `1`. Both tests skip, and do not fail, if nginx is missing or will not run unprivileged (lines 63-70).\n\nNOT ASSESSED\n1. `code_under_test` lists tests/active/test_static_page_visit_logs.py, but that path does not exist in the worktree. It was not read, and this verdict does not depend on it.\n2. No `fixtures_path` was supplied. The test uses only pytest's built-in `tmp_path`, and no project fixture needed resolving.\n3. Anti-pattern pass (rules/shape.md, each `<how_to_spot>`). No entry matches:\n   - doc-lint-grep / whole-file-source-name-grep / section-scoped-substring-grep: lines 41, 43 and 88 check that a substring is present in DEPLOYMENT.md. Each one only guards the step that pulls out the nginx block (lines 41, 43) or the token swap (line 88). The pulled-out block is then loaded by `nginx -t` (line 92) and served for real. No assertion checks wording in place of behaviour.\n   - hardcoded-spec-mirror: ABOUT_URLS and OTHER_ROUTES are request inputs. They are not compared for equality against a code constant.\n   - tautological-assertion: expected values at lines 167, 169 and 181 are stated per key, such as `(code, 1, 1)`, `(method, str(code))` and `f\"{method} {url} HTTP/1.1\"`. None is worked out the way nginx works it out.\n   - absence-only-assertion: the zero-pages-line claim at line 181 is paired in the same test with `/about.html` \u2192 `(200, 1)` (line 177), which serves as a positive control.\n   - echoed-literal: `uri`, `x_request_id` and `ua` come back through the `log_format` that nginx runs, so the production config sits between input and assertion. SENT_ID (line 31) is not 32-hex, so if the pages log copied the incoming header into `request_id`, the regex at line 33 would reject it.\n   - single-value-pin: the inputs vary across method (GET, HEAD), status (200, 404), four URLs and header present/absent. `same_request_id` compares two separate `access_log` lines, so a constant or header-copied id fails.\n4. Ladder pass (rules/shape.md `<ladder>`, `<matching_rule>`): the test is at Rung 3. It starts real nginx as a subprocess with the published block and asserts on the log lines written. That is the right rung for an invariant about which log lines get written, it is not the anti-rung, and nothing was moved down a rung, so `<downshift_rule>` does not apply.\n5. Stub question: these plausible wrong implementations would each turn the test red:\n   - Leaving the current behaviour unchanged fails lines 167 and 181.\n   - A pages `access_log` at server level fails line 181 on every non-About route.\n   - A pages log in only one of the three About locations fails line 167 for the others.\n   - A location-level pages `access_log` that drops the inherited main log fails line 167 (main count 0).\n   - Using `$http_x_request_id` or a fixed id fails line 169.",
        "claim": "CLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (21 clauses: 7 must_prove, 9 docstring, 5 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | each About request writes exactly one pages-log line | :167 | No pages line. A duplicate line, for example from an About access_log plus a server-level one writing to the same file. Checked on all 16 requests at 200 and again at 404 | CARRIED |\n| C1b | must_prove | each About request writes exactly one main-log line | :167 | An About access_log that replaces the main log it inherits from the server, leaving 0 main lines. Two main lines | CARRIED |\n| C1c | must_prove | both lines carry the same request_id | :169 (`same_request_id: True` via `_record` :154-155) | A pages id taken from `$http_x_request_id` (SENT_ID is not 32 hex, and with no header the value is `-`). Lines whose ids differ. Lines paired across different requests | CARRIED |\n| C1d | must_prove | \"of any method\" | :167 over GET and HEAD | Logging only GET. It does not exclude a GET/HEAD-only filter, because no other method is sent | CARRIED |\n| C1e | must_prove | \"or status\" | :167 at 200 (template-200) and 404 (no-files-404) | Logging only 2xx. A filter that drops other statuses (for example 304 or 405) is not excluded | CARRIED |\n| C2a | must_prove | /, /index.html, /api/ (as /api/health), /dev-pages/about.html and /dev-pages/about.template.html write no pages-log line | :181 (`len(pages)` == 0 per route, with the /about.html row at 1 as the contrast) | A pages log written at server level or for every route. A regex location such as `~ about` that also matches dev-pages. A run where nothing writes the pages log, caught by the contrast row | CARRIED |\n| C2b | must_prove | and still write one main-log line each | :181 (exactly one main line per route, whose request line and status are that route's) | An access_log change that silences the main log for these routes. Two lines for one route. A line belonging to another request | CARRIED |\n| D1 | docstring | \"GET and HEAD on /about, /about/, /about.html and /about.html?x=1, with and without an X-Request-ID header \u2026 one new line in [pages log] and one in [main log]\" | :167 | Any one of the 16 combinations writing 0 or 2 lines to either log | CARRIED |\n| D2 | docstring | \"answered 200 from the template or 404 with no dev-pages files\" | :167 (status per parameter) | The wrong status. With only about.template.html present (:162), a 200 can come only from the template | CARRIED |\n| D3 | docstring | \"first eight fields are page=about, ts=\u2026, time=<ISO 8601>, ip=127.0.0.1, method=, status=, rt=, request_id=<32 hex>\" | :169 (`PAGES_HEAD.fullmatch` on fields[:8], groups compared to method and code) | A missing, reordered or misformatted field among the eight. The wrong method or status | CARRIED |\n| D4 | docstring | \"uri= is the requested path plus query\" | :169 (`\"uri\": url`, which includes `?x=1`) | Logging `$uri` (the query is lost) or the rewritten try_files path | CARRIED |\n| D5 | docstring | \"x_request_id= the sent header or -\" | :169 (`sent or \"-\"`) | Logging nginx's own id in that field, or dropping the client header | CARRIED |\n| D6 | docstring | \"ua= the sent User-Agent\" | :169 (`\"ua\": AGENT`) | A missing or wrong UA field | CARRIED |\n| D7 | docstring | \"The main line is that request's usual line and carries the same request_id\" | :169 (`\"main\"` request line and status, `same_request_id`) | A main line for a different request, or one in a format without the `\"request\" status` pair | CARRIED |\n| D8 | docstring | \"/, /index.html, /api/health (502, upstream refused), /dev-pages/about.html and /dev-pages/about.template.html each write one main line and no pages line\" | :181 | Same as C2a and C2b. The 502 status is also compared | CARRIED |\n| D9 | docstring | \"in a run where an About request does write one\" | :181 (row `/about.html: (200, 1)`) | A pages log that nothing writes passing the zero-line rows without being exercised | CARRIED |\n| N1 | name | \"each about request\" | :167 | One URL, method or header variant missing the behaviour | CARRIED |\n| N2 | name | \"writes one pages line\" | :167 | 0 or 2 pages lines | CARRIED |\n| N3 | name | \"and one main line\" | :167 | 0 or 2 main lines | CARRIED |\n| N4 | name | \"with same request_id\" | :169 | Ids that differ between the two lines | CARRIED |\n| N5 | name | \"other routes write no pages line\" | :181 | A pages line on any listed non-About route | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. bounds (rules/testing.md): tests/tmp/test_21_static_page_visit_logs_phase2.py:163\n   `requests = [(method, url, sent) for url in ABOUT_URLS for method in (\"GET\", \"HEAD\") for sent in (None, SENT_ID)]`\n   C1 claims \"any method or status\", but the test only sends GET and HEAD and only gets 200 and 404. It never sends a method the static location refuses (for example POST, answered 405) or a conditional GET (304). So a log condition that keeps only GET/HEAD, or drops 3xx, would still pass. Consider adding one POST and one `If-Modified-Since` request to the About matrix.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `code_under_test` lists tests/active/test_static_page_visit_logs.py. That file does not exist, and no `tests/**/test_static_page_visit_logs*.py` matches either, so it was not read.\n2. `code_under_test` says DEPLOYMENT.md was edited to add the peertube_browser_pages log_format, `set $static_page` and two access_log lines in the About location. None of these is in the \u00a76 block as read (DEPLOYMENT.md:414-470). So the expected format of the pages-line fields (D3-D6) was judged from the test and `must_prove`, not checked against the code.",
        "body": "### devsecops-test-shape-auditor\n\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\nBoth parametrised cases of `test_each_about_request_writes_one_pages_line_and_one_main_line_with_same_request_id` should fail at line 167 on the count comparison. Every About request gives `(code, 1, 0)` where `(code, 1, 1)` is expected, because the current \u00a76 block (DEPLOYMENT.md:414-470) has no pages log, so `peertube-browser.pages.access.log` is never written. `test_other_routes_write_no_pages_line` should fail at line 181 on the `/about.html` row only: it gets `(200, [(\"GET /about.html HTTP/1.1\", \"200\")], 0)` where the expected pages count is `1`. Both tests skip, and do not fail, if nginx is missing or will not run unprivileged (lines 63-70).\n\nNOT ASSESSED\n1. `code_under_test` lists tests/active/test_static_page_visit_logs.py, but that path does not exist in the worktree. It was not read, and this verdict does not depend on it.\n2. No `fixtures_path` was supplied. The test uses only pytest's built-in `tmp_path`, and no project fixture needed resolving.\n3. Anti-pattern pass (rules/shape.md, each `<how_to_spot>`). No entry matches:\n   - doc-lint-grep / whole-file-source-name-grep / section-scoped-substring-grep: lines 41, 43 and 88 check that a substring is present in DEPLOYMENT.md. Each one only guards the step that pulls out the nginx block (lines 41, 43) or the token swap (line 88). The pulled-out block is then loaded by `nginx -t` (line 92) and served for real. No assertion checks wording in place of behaviour.\n   - hardcoded-spec-mirror: ABOUT_URLS and OTHER_ROUTES are request inputs. They are not compared for equality against a code constant.\n   - tautological-assertion: expected values at lines 167, 169 and 181 are stated per key, such as `(code, 1, 1)`, `(method, str(code))` and `f\"{method} {url} HTTP/1.1\"`. None is worked out the way nginx works it out.\n   - absence-only-assertion: the zero-pages-line claim at line 181 is paired in the same test with `/about.html` \u2192 `(200, 1)` (line 177), which serves as a positive control.\n   - echoed-literal: `uri`, `x_request_id` and `ua` come back through the `log_format` that nginx runs, so the production config sits between input and assertion. SENT_ID (line 31) is not 32-hex, so if the pages log copied the incoming header into `request_id`, the regex at line 33 would reject it.\n   - single-value-pin: the inputs vary across method (GET, HEAD), status (200, 404), four URLs and header present/absent. `same_request_id` compares two separate `access_log` lines, so a constant or header-copied id fails.\n4. Ladder pass (rules/shape.md `<ladder>`, `<matching_rule>`): the test is at Rung 3. It starts real nginx as a subprocess with the published block and asserts on the log lines written. That is the right rung for an invariant about which log lines get written, it is not the anti-rung, and nothing was moved down a rung, so `<downshift_rule>` does not apply.\n5. Stub question: these plausible wrong implementations would each turn the test red:\n   - Leaving the current behaviour unchanged fails lines 167 and 181.\n   - A pages `access_log` at server level fails line 181 on every non-About route.\n   - A pages log in only one of the three About locations fails line 167 for the others.\n   - A location-level pages `access_log` that drops the inherited main log fails line 167 (main count 0).\n   - Using `$http_x_request_id` or a fixed id fails line 169.\n\n### devsecops-test-claim-auditor\n\nCLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (21 clauses: 7 must_prove, 9 docstring, 5 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | each About request writes exactly one pages-log line | :167 | No pages line. A duplicate line, for example from an About access_log plus a server-level one writing to the same file. Checked on all 16 requests at 200 and again at 404 | CARRIED |\n| C1b | must_prove | each About request writes exactly one main-log line | :167 | An About access_log that replaces the main log it inherits from the server, leaving 0 main lines. Two main lines | CARRIED |\n| C1c | must_prove | both lines carry the same request_id | :169 (`same_request_id: True` via `_record` :154-155) | A pages id taken from `$http_x_request_id` (SENT_ID is not 32 hex, and with no header the value is `-`). Lines whose ids differ. Lines paired across different requests | CARRIED |\n| C1d | must_prove | \"of any method\" | :167 over GET and HEAD | Logging only GET. It does not exclude a GET/HEAD-only filter, because no other method is sent | CARRIED |\n| C1e | must_prove | \"or status\" | :167 at 200 (template-200) and 404 (no-files-404) | Logging only 2xx. A filter that drops other statuses (for example 304 or 405) is not excluded | CARRIED |\n| C2a | must_prove | /, /index.html, /api/ (as /api/health), /dev-pages/about.html and /dev-pages/about.template.html write no pages-log line | :181 (`len(pages)` == 0 per route, with the /about.html row at 1 as the contrast) | A pages log written at server level or for every route. A regex location such as `~ about` that also matches dev-pages. A run where nothing writes the pages log, caught by the contrast row | CARRIED |\n| C2b | must_prove | and still write one main-log line each | :181 (exactly one main line per route, whose request line and status are that route's) | An access_log change that silences the main log for these routes. Two lines for one route. A line belonging to another request | CARRIED |\n| D1 | docstring | \"GET and HEAD on /about, /about/, /about.html and /about.html?x=1, with and without an X-Request-ID header \u2026 one new line in [pages log] and one in [main log]\" | :167 | Any one of the 16 combinations writing 0 or 2 lines to either log | CARRIED |\n| D2 | docstring | \"answered 200 from the template or 404 with no dev-pages files\" | :167 (status per parameter) | The wrong status. With only about.template.html present (:162), a 200 can come only from the template | CARRIED |\n| D3 | docstring | \"first eight fields are page=about, ts=\u2026, time=<ISO 8601>, ip=127.0.0.1, method=, status=, rt=, request_id=<32 hex>\" | :169 (`PAGES_HEAD.fullmatch` on fields[:8], groups compared to method and code) | A missing, reordered or misformatted field among the eight. The wrong method or status | CARRIED |\n| D4 | docstring | \"uri= is the requested path plus query\" | :169 (`\"uri\": url`, which includes `?x=1`) | Logging `$uri` (the query is lost) or the rewritten try_files path | CARRIED |\n| D5 | docstring | \"x_request_id= the sent header or -\" | :169 (`sent or \"-\"`) | Logging nginx's own id in that field, or dropping the client header | CARRIED |\n| D6 | docstring | \"ua= the sent User-Agent\" | :169 (`\"ua\": AGENT`) | A missing or wrong UA field | CARRIED |\n| D7 | docstring | \"The main line is that request's usual line and carries the same request_id\" | :169 (`\"main\"` request line and status, `same_request_id`) | A main line for a different request, or one in a format without the `\"request\" status` pair | CARRIED |\n| D8 | docstring | \"/, /index.html, /api/health (502, upstream refused), /dev-pages/about.html and /dev-pages/about.template.html each write one main line and no pages line\" | :181 | Same as C2a and C2b. The 502 status is also compared | CARRIED |\n| D9 | docstring | \"in a run where an About request does write one\" | :181 (row `/about.html: (200, 1)`) | A pages log that nothing writes passing the zero-line rows without being exercised | CARRIED |\n| N1 | name | \"each about request\" | :167 | One URL, method or header variant missing the behaviour | CARRIED |\n| N2 | name | \"writes one pages line\" | :167 | 0 or 2 pages lines | CARRIED |\n| N3 | name | \"and one main line\" | :167 | 0 or 2 main lines | CARRIED |\n| N4 | name | \"with same request_id\" | :169 | Ids that differ between the two lines | CARRIED |\n| N5 | name | \"other routes write no pages line\" | :181 | A pages line on any listed non-About route | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. bounds (rules/testing.md): tests/tmp/test_21_static_page_visit_logs_phase2.py:163\n   `requests = [(method, url, sent) for url in ABOUT_URLS for method in (\"GET\", \"HEAD\") for sent in (None, SENT_ID)]`\n   C1 claims \"any method or status\", but the test only sends GET and HEAD and only gets 200 and 404. It never sends a method the static location refuses (for example POST, answered 405) or a conditional GET (304). So a log condition that keeps only GET/HEAD, or drops 3xx, would still pass. Consider adding one POST and one `If-Modified-Since` request to the About matrix.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `code_under_test` lists tests/active/test_static_page_visit_logs.py. That file does not exist, and no `tests/**/test_static_page_visit_logs*.py` matches either, so it was not read.\n2. `code_under_test` says DEPLOYMENT.md was edited to add the peertube_browser_pages log_format, `set $static_page` and two access_log lines in the About location. None of these is in the \u00a76 block as read (DEPLOYMENT.md:414-470). So the expected format of the pages-line fields (D3-D6) was judged from the test and `must_prove`, not checked against the code.",
        "map": [
          {
            "id": "C1a",
            "source": "must_prove",
            "clause": "each About request writes exactly one pages-log line",
            "assertion": ":167",
            "excludes": "No pages line. A duplicate line, for example from an About access_log plus a server-level one writing to the same file. Checked on all 16 requests at 200 and again at 404",
            "status": "CARRIED"
          },
          {
            "id": "C1b",
            "source": "must_prove",
            "clause": "each About request writes exactly one main-log line",
            "assertion": ":167",
            "excludes": "An About access_log that replaces the main log it inherits from the server, leaving 0 main lines. Two main lines",
            "status": "CARRIED"
          },
          {
            "id": "C1c",
            "source": "must_prove",
            "clause": "both lines carry the same request_id",
            "assertion": ":169 (`same_request_id: True` via `_record` :154-155)",
            "excludes": "A pages id taken from `$http_x_request_id` (SENT_ID is not 32 hex, and with no header the value is `-`). Lines whose ids differ. Lines paired across different requests",
            "status": "CARRIED"
          },
          {
            "id": "C1d",
            "source": "must_prove",
            "clause": "\"of any method\"",
            "assertion": ":167 over GET and HEAD",
            "excludes": "Logging only GET. It does not exclude a GET/HEAD-only filter, because no other method is sent",
            "status": "CARRIED"
          },
          {
            "id": "C1e",
            "source": "must_prove",
            "clause": "\"or status\"",
            "assertion": ":167 at 200 (template-200) and 404 (no-files-404)",
            "excludes": "Logging only 2xx. A filter that drops other statuses (for example 304 or 405) is not excluded",
            "status": "CARRIED"
          },
          {
            "id": "C2a",
            "source": "must_prove",
            "clause": "/, /index.html, /api/ (as /api/health), /dev-pages/about.html and /dev-pages/about.template.html write no pages-log line",
            "assertion": ":181 (`len(pages)` == 0 per route, with the /about.html row at 1 as the contrast)",
            "excludes": "A pages log written at server level or for every route. A regex location such as `~ about` that also matches dev-pages. A run where nothing writes the pages log, caught by the contrast row",
            "status": "CARRIED"
          },
          {
            "id": "C2b",
            "source": "must_prove",
            "clause": "and still write one main-log line each",
            "assertion": ":181 (exactly one main line per route, whose request line and status are that route's)",
            "excludes": "An access_log change that silences the main log for these routes. Two lines for one route. A line belonging to another request",
            "status": "CARRIED"
          },
          {
            "id": "D1",
            "source": "docstring",
            "clause": "\"GET and HEAD on /about, /about/, /about.html and /about.html?x=1, with and without an X-Request-ID header \u2026 one new line in [pages log] and one in [main log]\"",
            "assertion": ":167",
            "excludes": "Any one of the 16 combinations writing 0 or 2 lines to either log",
            "status": "CARRIED"
          },
          {
            "id": "D2",
            "source": "docstring",
            "clause": "\"answered 200 from the template or 404 with no dev-pages files\"",
            "assertion": ":167 (status per parameter)",
            "excludes": "The wrong status. With only about.template.html present (:162), a 200 can come only from the template",
            "status": "CARRIED"
          },
          {
            "id": "D3",
            "source": "docstring",
            "clause": "\"first eight fields are page=about, ts=\u2026, time=<ISO 8601>, ip=127.0.0.1, method=, status=, rt=, request_id=<32 hex>\"",
            "assertion": ":169 (`PAGES_HEAD.fullmatch` on fields[:8], groups compared to method and code)",
            "excludes": "A missing, reordered or misformatted field among the eight. The wrong method or status",
            "status": "CARRIED"
          },
          {
            "id": "D4",
            "source": "docstring",
            "clause": "\"uri= is the requested path plus query\"",
            "assertion": ":169 (`\"uri\": url`, which includes `?x=1`)",
            "excludes": "Logging `$uri` (the query is lost) or the rewritten try_files path",
            "status": "CARRIED"
          },
          {
            "id": "D5",
            "source": "docstring",
            "clause": "\"x_request_id= the sent header or -\"",
            "assertion": ":169 (`sent or \"-\"`)",
            "excludes": "Logging nginx's own id in that field, or dropping the client header",
            "status": "CARRIED"
          },
          {
            "id": "D6",
            "source": "docstring",
            "clause": "\"ua= the sent User-Agent\"",
            "assertion": ":169 (`\"ua\": AGENT`)",
            "excludes": "A missing or wrong UA field",
            "status": "CARRIED"
          },
          {
            "id": "D7",
            "source": "docstring",
            "clause": "\"The main line is that request's usual line and carries the same request_id\"",
            "assertion": ":169 (`\"main\"` request line and status, `same_request_id`)",
            "excludes": "A main line for a different request, or one in a format without the `\"request\" status` pair",
            "status": "CARRIED"
          },
          {
            "id": "D8",
            "source": "docstring",
            "clause": "\"/, /index.html, /api/health (502, upstream refused), /dev-pages/about.html and /dev-pages/about.template.html each write one main line and no pages line\"",
            "assertion": ":181",
            "excludes": "Same as C2a and C2b. The 502 status is also compared",
            "status": "CARRIED"
          },
          {
            "id": "D9",
            "source": "docstring",
            "clause": "\"in a run where an About request does write one\"",
            "assertion": ":181 (row `/about.html: (200, 1)`)",
            "excludes": "A pages log that nothing writes passing the zero-line rows without being exercised",
            "status": "CARRIED"
          },
          {
            "id": "N1",
            "source": "name",
            "clause": "\"each about request\"",
            "assertion": ":167",
            "excludes": "One URL, method or header variant missing the behaviour",
            "status": "CARRIED"
          },
          {
            "id": "N2",
            "source": "name",
            "clause": "\"writes one pages line\"",
            "assertion": ":167",
            "excludes": "0 or 2 pages lines",
            "status": "CARRIED"
          },
          {
            "id": "N3",
            "source": "name",
            "clause": "\"and one main line\"",
            "assertion": ":167",
            "excludes": "0 or 2 main lines",
            "status": "CARRIED"
          },
          {
            "id": "N4",
            "source": "name",
            "clause": "\"with same request_id\"",
            "assertion": ":169",
            "excludes": "Ids that differ between the two lines",
            "status": "CARRIED"
          },
          {
            "id": "N5",
            "source": "name",
            "clause": "\"other routes write no pages line\"",
            "assertion": ":181",
            "excludes": "A pages line on any listed non-About route",
            "status": "CARRIED"
          }
        ],
        "map_problem": ""
      }
    ],
    "tests/tmp/test_21_static_page_visit_logs_phase3.py": [
      {
        "shape": "SHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. No rule in rules/shape.md covers this \u2014 tests/tmp/test_21_static_page_visit_logs_phase3.py:249\n   filters = [line for block in _runbook() for line in block.splitlines() if \"peertube-browser.pages.access.log\" in line and \"GET\" in line and \"200\" in line and not line.lstrip().startswith(\"#\")]\n   The C1 check runs only the runbook lines that literally contain the pages-log path, `GET` and `200`. It also runs each of those lines on its own in a separate bash. Two kinds of filter never run:\n   - A filter that names the log through a variable (`\"$PAGES\"`) or puts its pipeline on several lines without backslashes. If no line matches at all, line 252 fails on the placeholder key, so a missing filter is still caught. But if some other line does match, the test passes without ever running the skipped filter, even a substring-grep one.\n   - A line that needs a variable set earlier in the block.\n   Picking which commands to run by the author's wording is close in spirit to doc-lint-grep, but that entry does not cover it: the selected lines are executed, not grepped. Running the C1 filter the way the C2 test runs its commands would close the gap: the whole fenced block as one script, with the path swapped.\n\nPREDICTED FAILURE\nDEPLOYMENT.md has no `### Follow an About visit` heading, so `_runbook()` returns `[]`. `test_forged_user_agent_does_not_move_fields` gets through its controls at lines 243/245/247, then fails at line 252: `{}` does not equal `{\"<a runbook line filtering the pages log for GET and 200>\": [<the GET /about.html 200 pages line>]}`. `test_runbook_finds_visit_and_client_record` passes the control at line 277 (`not runbook`), runs an empty script, and fails at line 291: `got[\"json\"] == []` does not equal `expected[\"json\"] == [<the rid-match request.start dict>]`. Both tests skip instead if nginx cannot run unprivileged, or if jq or a `date -u -d @<epoch.ms>` is missing.\n\nNOT ASSESSED\n1. `fixtures_path` is \"none found\", and the test defines everything it uses itself, so there was no fixture to check.\n2. tests/active/test_static_page_visit_logs.py is listed in `code_under_test` but nothing in this test imports or runs it, so I didn't read it.\n3. I did not open the body of `ClientLogFormatter` (client/backend/server.py:166). I confirmed the class exists and that `REQUEST_CONTEXT` is defined in client/backend/lib/engine_api_client.py:15. I did not check whether `server.REQUEST_CONTEXT` resolves the way `_FORMAT_CHILD` expects. If it doesn't, the control at line 218 fails before C2 is reached.\n\nNotes on the passes (not findings):\n- Ladder: both tests are at rung 2. They take the runbook's ```bash fences and run them as subprocesses. Their input is a real nginx running the \u00a76 block (C1), or records rendered by the production `ClientLogFormatter` (C2). They check stdout. That is the highest rung a shell runbook supports. The markdown is parsed to get the commands to run, not grepped, so the anti-rung does not apply and no downshift is involved.\n- Anti-patterns: none apply.\n  - The expected values are independent: real nginx output and real formatter output.\n  - Every claim assertion is positive and non-empty, and an absent runbook fails it.\n  - C1 has three inputs (GET 200, HEAD 200, forged 404).\n  - C2 has four candidates (\u221260 s, +10 s, the neighbour's +20 s at the prefix address, +1 h) checked in two formats, with the timezone control at line 262.\n- Stub question: none of these would pass:\n  - a missing runbook\n  - a substring grep for `status=200`/`method=GET`\n  - `tail -1`, or printing every line\n  - an `ip=1.2.3.4` match without a delimiter\n  - a time conversion without `-u`",
        "claim": "CLAIM AUDIT \u2014 VERDICT: BLOCK\n\nCLAUSE MAP  (25 clauses: 10 must_prove, 12 docstring, 3 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | \"does not list a 404 About request whose user agent carries forged status=200, method=GET and page=about tokens as a successful GET\" | :252 | a substring grep for ` status=200 ` or ` method=GET `. The control at :245 shows the forged tokens reached the line space-delimited, so such a grep would list the 404 | CARRIED |\n| C1b | must_prove | the \"listing filter\" lists the real successful GET | :252 | a filter that prints nothing, and a runbook with no such filter (the placeholder key fails the comparison) | CARRIED |\n| C1c | must_prove | the filter \"selects by field position\" | none | nothing. :247 checks the log line's sixth field, not how the runbook's filter selects. :252 passes any filter the one forged ordering (`status=200 method=GET page=about`) fails to fool, including a non-positional contiguous grep ` method=GET status=200 ` | UNCARRIED |\n| C2a | must_prove | \"the visitor's\" record: matched by the visit's address | :291, :292 | an unanchored `ip=1.2.3.4` match picking up the 1.2.3.45 neighbour at +20 s; resolving the visit from the last pages line instead of by request_id | CARRIED |\n| C2b | must_prove | \"in-window\" | :291, :292 | no time filter (the \u221260 s and +3600 s records are present); a local-time conversion without `-u` (control :262) | CARRIED |\n| C2c | must_prove | \"request.start record\", not the rest of the request | :291, :292 | also printing the rid-match `request.end` record that :273 writes | CARRIED |\n| C2d | must_prove | \"exactly\" that one record | :291, :292 | extra or duplicate Client records (list equality against a one-element list) | CARRIED |\n| C2e | must_prove | \"from real ClientLogFormatter output\" | :283 (input via :217, :282) | hand-written Client lines that differ from what `server.ClientLogFormatter` renders | CARRIED |\n| C2f | must_prove | \"in \u2026 JSON\" mode | :291 | a correlation that works only on text lines | CARRIED |\n| C2g | must_prove | \"and text modes\" | :292 | a jq-only correlation that prints nothing for text lines | CARRIED |\n| D1 | docstring | \"list About visits by field position\" (module, l.1) | none | same gap as C1c: a non-positional filter that beats this one token ordering passes | UNCARRIED |\n| D2a | docstring | \"find a visit's Client request.start record by its address\" (l.1) | :291, :292 | the prefix-address neighbour | CARRIED |\n| D2b | docstring | \"and a time window after it\" (l.1) | none | only windows reaching back 60 s or more are excluded. A \u00b130 s window passes, because no visitor-address record sits a few seconds before the visit | UNCARRIED |\n| D3 | docstring | GET /about.html 200, HEAD /about 200, and GET /about/ 404 each write a pages line (l.3) | :243 | a missing or doubled pages line, or the forged request not answered 404 | CARRIED |\n| D4 | docstring | \"the forged one keeps `status=404` as its sixth field\" (l.3) | :247 | forged tokens shifting the status field | CARRIED |\n| D5 | docstring | \"every runbook line that filters the pages log for GET and 200 prints exactly the real GET line\" (l.3, l.234) | :252 | any filter line printing the forged, HEAD or extra lines | CARRIED |\n| D6 | docstring | \"not the one 60 s before, the one 1 h after, nor the one 20 s after from 1.2.3.45\" (l.4, l.256) | :291, :292 | each named decoy being printed | CARRIED |\n| D7 | docstring | \"Its one `name=<\u2026>` placeholder line gets the visit's request_id\" (l.6) | :277 | a non-empty runbook with zero or several placeholders | CARRIED |\n| D8 | docstring | \"A missing section is an empty runbook, which fails at the claim assertions\" (l.6) | :252, :291 | a missing section passing silently | CARRIED |\n| D9 | docstring | \"not \u2026 a HEAD /about 200\" (l.234) | :252 | a filter on status alone, which also lists the method=HEAD line | CARRIED |\n| D10 | docstring | \"Given the visit's request_id\" picks the right visit out of three (l.256, l.264) | :291, :292 | taking the last pages line (lands on the neighbour) or every line | CARRIED |\n| D11 | docstring | \"Skipped when nginx, bash, jq, awk or a `date` that reads `-u -d @<epoch.ms>` is missing\" (l.6) | :111, :117, :123, :261 | running against a missing tool or a `date` without epoch.ms support | CARRIED |\n| N1 | name | \"forged user agent does not move fields\" | :247 | the forged tokens shifting the positional fields | CARRIED |\n| N2 | name | \"runbook finds visit\" | :291, :292 | resolving the wrong pages line (only the right visit's address and time yield rid-match) | CARRIED |\n| N3 | name | \"and client record\" | :291, :292 | the wrong Client record or none | CARRIED |\n\nCRITICAL\n1. whole-claim (rules/testing.md) \u2014 tests/tmp/test_21_static_page_visit_logs_phase3.py:39\n   FORGED_UA = \"forger/1 status=200 method=GET page=about forger/1\"\n   C1 says the listing filter \"selects by field position\". The test uses only one forgery, with its tokens in an order the real format never uses (the format is `method=\u2026 status=\u2026`, DEPLOYMENT.md:417). At :252 it checks only that each filter beats that one ordering. A non-positional filter such as `grep ' method=GET status=200 '` is caught by the selection at :249 and prints exactly `get[1]`, so it passes. That same filter would list a 404 whose user agent carries `method=GET status=200`. :247 checks the log line's sixth field, not that the runbook's filter reads that field. Nothing excludes a wrong implementation of \"selects by field position\", so C1c is UNCARRIED. To carry it, add a forged request whose user agent repeats the real field order, e.g. ` method=GET status=200 rt=0.000 `, and require the filter not to list it.\n\nRECOMMENDATIONS\n1. whole-claim (rules/testing.md) \u2014 tests/tmp/test_21_static_page_visit_logs_phase3.py:1\n   D1 is UNCARRIED, for the same reason as Critical 1.\n2. whole-claim (rules/testing.md) \u2014 tests/tmp/test_21_static_page_visit_logs_phase3.py:268\n   D2b (\"a time window after it\") is UNCARRIED. The only earlier decoy is at \u221260 s, so a window open on both sides that reaches back less than 60 s passes. A visitor-address `request.start` a few seconds before the visit would carry \"after\".\n3. bounds (rules/testing.md) \u2014 tests/tmp/test_21_static_page_visit_logs_phase3.py:268\n   The window is tested at +10 s (inside), \u221260 s and +3600 s (outside) only. The edges are untested: a record at the visit's own millisecond, just before it, and at the window's closing bound and one past it.\n4. normal-and-abnormal-paths (rules/testing.md) \u2014 tests/tmp/test_21_static_page_visit_logs_phase3.py:276\n   Only a request_id present in the pages log is supplied. The correlation's expected failure mode is never tested: an id with no pages line, where an empty address and window could match every Client record.\n5. name-as-sentence (rules/testing.md) \u2014 tests/tmp/test_21_static_page_visit_logs_phase3.py:233\n   `test_forged_user_agent_does_not_move_fields` names the control at :247, not the claim at :252, which is that the runbook filter does not list the forged 404. If :252 fails, the runner's output reports a field-shift problem and does not say the runbook listed a forged visit. `test_runbook_finds_visit_and_client_record` (:255) states no \"when\".\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `code_under_test` lists tests/active/test_static_page_visit_logs.py, which does not resolve (no file matches tests/**/test_static_page_visit_logs*.py). It was not read.\n2. DEPLOYMENT.md has no `### Follow an About visit` heading. The Triage subsections run from `### Triage` (l.195) to `### Follow one request` (l.231), with no section between. So the runbook's listing filter and correlation commands could not be read, and C1c and C2 were judged against the test's assertions alone.\n3. `fixtures_path` was not supplied. The test uses only pytest's built-in `tmp_path`, so no conftest was needed.",
        "body": "### devsecops-test-shape-auditor\n\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. No rule in rules/shape.md covers this \u2014 tests/tmp/test_21_static_page_visit_logs_phase3.py:249\n   filters = [line for block in _runbook() for line in block.splitlines() if \"peertube-browser.pages.access.log\" in line and \"GET\" in line and \"200\" in line and not line.lstrip().startswith(\"#\")]\n   The C1 check runs only the runbook lines that literally contain the pages-log path, `GET` and `200`. It also runs each of those lines on its own in a separate bash. Two kinds of filter never run:\n   - A filter that names the log through a variable (`\"$PAGES\"`) or puts its pipeline on several lines without backslashes. If no line matches at all, line 252 fails on the placeholder key, so a missing filter is still caught. But if some other line does match, the test passes without ever running the skipped filter, even a substring-grep one.\n   - A line that needs a variable set earlier in the block.\n   Picking which commands to run by the author's wording is close in spirit to doc-lint-grep, but that entry does not cover it: the selected lines are executed, not grepped. Running the C1 filter the way the C2 test runs its commands would close the gap: the whole fenced block as one script, with the path swapped.\n\nPREDICTED FAILURE\nDEPLOYMENT.md has no `### Follow an About visit` heading, so `_runbook()` returns `[]`. `test_forged_user_agent_does_not_move_fields` gets through its controls at lines 243/245/247, then fails at line 252: `{}` does not equal `{\"<a runbook line filtering the pages log for GET and 200>\": [<the GET /about.html 200 pages line>]}`. `test_runbook_finds_visit_and_client_record` passes the control at line 277 (`not runbook`), runs an empty script, and fails at line 291: `got[\"json\"] == []` does not equal `expected[\"json\"] == [<the rid-match request.start dict>]`. Both tests skip instead if nginx cannot run unprivileged, or if jq or a `date -u -d @<epoch.ms>` is missing.\n\nNOT ASSESSED\n1. `fixtures_path` is \"none found\", and the test defines everything it uses itself, so there was no fixture to check.\n2. tests/active/test_static_page_visit_logs.py is listed in `code_under_test` but nothing in this test imports or runs it, so I didn't read it.\n3. I did not open the body of `ClientLogFormatter` (client/backend/server.py:166). I confirmed the class exists and that `REQUEST_CONTEXT` is defined in client/backend/lib/engine_api_client.py:15. I did not check whether `server.REQUEST_CONTEXT` resolves the way `_FORMAT_CHILD` expects. If it doesn't, the control at line 218 fails before C2 is reached.\n\nNotes on the passes (not findings):\n- Ladder: both tests are at rung 2. They take the runbook's ```bash fences and run them as subprocesses. Their input is a real nginx running the \u00a76 block (C1), or records rendered by the production `ClientLogFormatter` (C2). They check stdout. That is the highest rung a shell runbook supports. The markdown is parsed to get the commands to run, not grepped, so the anti-rung does not apply and no downshift is involved.\n- Anti-patterns: none apply.\n  - The expected values are independent: real nginx output and real formatter output.\n  - Every claim assertion is positive and non-empty, and an absent runbook fails it.\n  - C1 has three inputs (GET 200, HEAD 200, forged 404).\n  - C2 has four candidates (\u221260 s, +10 s, the neighbour's +20 s at the prefix address, +1 h) checked in two formats, with the timezone control at line 262.\n- Stub question: none of these would pass:\n  - a missing runbook\n  - a substring grep for `status=200`/`method=GET`\n  - `tail -1`, or printing every line\n  - an `ip=1.2.3.4` match without a delimiter\n  - a time conversion without `-u`\n\n### devsecops-test-claim-auditor\n\nCLAIM AUDIT \u2014 VERDICT: BLOCK\n\nCLAUSE MAP  (25 clauses: 10 must_prove, 12 docstring, 3 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | \"does not list a 404 About request whose user agent carries forged status=200, method=GET and page=about tokens as a successful GET\" | :252 | a substring grep for ` status=200 ` or ` method=GET `. The control at :245 shows the forged tokens reached the line space-delimited, so such a grep would list the 404 | CARRIED |\n| C1b | must_prove | the \"listing filter\" lists the real successful GET | :252 | a filter that prints nothing, and a runbook with no such filter (the placeholder key fails the comparison) | CARRIED |\n| C1c | must_prove | the filter \"selects by field position\" | none | nothing. :247 checks the log line's sixth field, not how the runbook's filter selects. :252 passes any filter the one forged ordering (`status=200 method=GET page=about`) fails to fool, including a non-positional contiguous grep ` method=GET status=200 ` | UNCARRIED |\n| C2a | must_prove | \"the visitor's\" record: matched by the visit's address | :291, :292 | an unanchored `ip=1.2.3.4` match picking up the 1.2.3.45 neighbour at +20 s; resolving the visit from the last pages line instead of by request_id | CARRIED |\n| C2b | must_prove | \"in-window\" | :291, :292 | no time filter (the \u221260 s and +3600 s records are present); a local-time conversion without `-u` (control :262) | CARRIED |\n| C2c | must_prove | \"request.start record\", not the rest of the request | :291, :292 | also printing the rid-match `request.end` record that :273 writes | CARRIED |\n| C2d | must_prove | \"exactly\" that one record | :291, :292 | extra or duplicate Client records (list equality against a one-element list) | CARRIED |\n| C2e | must_prove | \"from real ClientLogFormatter output\" | :283 (input via :217, :282) | hand-written Client lines that differ from what `server.ClientLogFormatter` renders | CARRIED |\n| C2f | must_prove | \"in \u2026 JSON\" mode | :291 | a correlation that works only on text lines | CARRIED |\n| C2g | must_prove | \"and text modes\" | :292 | a jq-only correlation that prints nothing for text lines | CARRIED |\n| D1 | docstring | \"list About visits by field position\" (module, l.1) | none | same gap as C1c: a non-positional filter that beats this one token ordering passes | UNCARRIED |\n| D2a | docstring | \"find a visit's Client request.start record by its address\" (l.1) | :291, :292 | the prefix-address neighbour | CARRIED |\n| D2b | docstring | \"and a time window after it\" (l.1) | none | only windows reaching back 60 s or more are excluded. A \u00b130 s window passes, because no visitor-address record sits a few seconds before the visit | UNCARRIED |\n| D3 | docstring | GET /about.html 200, HEAD /about 200, and GET /about/ 404 each write a pages line (l.3) | :243 | a missing or doubled pages line, or the forged request not answered 404 | CARRIED |\n| D4 | docstring | \"the forged one keeps `status=404` as its sixth field\" (l.3) | :247 | forged tokens shifting the status field | CARRIED |\n| D5 | docstring | \"every runbook line that filters the pages log for GET and 200 prints exactly the real GET line\" (l.3, l.234) | :252 | any filter line printing the forged, HEAD or extra lines | CARRIED |\n| D6 | docstring | \"not the one 60 s before, the one 1 h after, nor the one 20 s after from 1.2.3.45\" (l.4, l.256) | :291, :292 | each named decoy being printed | CARRIED |\n| D7 | docstring | \"Its one `name=<\u2026>` placeholder line gets the visit's request_id\" (l.6) | :277 | a non-empty runbook with zero or several placeholders | CARRIED |\n| D8 | docstring | \"A missing section is an empty runbook, which fails at the claim assertions\" (l.6) | :252, :291 | a missing section passing silently | CARRIED |\n| D9 | docstring | \"not \u2026 a HEAD /about 200\" (l.234) | :252 | a filter on status alone, which also lists the method=HEAD line | CARRIED |\n| D10 | docstring | \"Given the visit's request_id\" picks the right visit out of three (l.256, l.264) | :291, :292 | taking the last pages line (lands on the neighbour) or every line | CARRIED |\n| D11 | docstring | \"Skipped when nginx, bash, jq, awk or a `date` that reads `-u -d @<epoch.ms>` is missing\" (l.6) | :111, :117, :123, :261 | running against a missing tool or a `date` without epoch.ms support | CARRIED |\n| N1 | name | \"forged user agent does not move fields\" | :247 | the forged tokens shifting the positional fields | CARRIED |\n| N2 | name | \"runbook finds visit\" | :291, :292 | resolving the wrong pages line (only the right visit's address and time yield rid-match) | CARRIED |\n| N3 | name | \"and client record\" | :291, :292 | the wrong Client record or none | CARRIED |\n\nCRITICAL\n1. whole-claim (rules/testing.md) \u2014 tests/tmp/test_21_static_page_visit_logs_phase3.py:39\n   FORGED_UA = \"forger/1 status=200 method=GET page=about forger/1\"\n   C1 says the listing filter \"selects by field position\". The test uses only one forgery, with its tokens in an order the real format never uses (the format is `method=\u2026 status=\u2026`, DEPLOYMENT.md:417). At :252 it checks only that each filter beats that one ordering. A non-positional filter such as `grep ' method=GET status=200 '` is caught by the selection at :249 and prints exactly `get[1]`, so it passes. That same filter would list a 404 whose user agent carries `method=GET status=200`. :247 checks the log line's sixth field, not that the runbook's filter reads that field. Nothing excludes a wrong implementation of \"selects by field position\", so C1c is UNCARRIED. To carry it, add a forged request whose user agent repeats the real field order, e.g. ` method=GET status=200 rt=0.000 `, and require the filter not to list it.\n\nRECOMMENDATIONS\n1. whole-claim (rules/testing.md) \u2014 tests/tmp/test_21_static_page_visit_logs_phase3.py:1\n   D1 is UNCARRIED, for the same reason as Critical 1.\n2. whole-claim (rules/testing.md) \u2014 tests/tmp/test_21_static_page_visit_logs_phase3.py:268\n   D2b (\"a time window after it\") is UNCARRIED. The only earlier decoy is at \u221260 s, so a window open on both sides that reaches back less than 60 s passes. A visitor-address `request.start` a few seconds before the visit would carry \"after\".\n3. bounds (rules/testing.md) \u2014 tests/tmp/test_21_static_page_visit_logs_phase3.py:268\n   The window is tested at +10 s (inside), \u221260 s and +3600 s (outside) only. The edges are untested: a record at the visit's own millisecond, just before it, and at the window's closing bound and one past it.\n4. normal-and-abnormal-paths (rules/testing.md) \u2014 tests/tmp/test_21_static_page_visit_logs_phase3.py:276\n   Only a request_id present in the pages log is supplied. The correlation's expected failure mode is never tested: an id with no pages line, where an empty address and window could match every Client record.\n5. name-as-sentence (rules/testing.md) \u2014 tests/tmp/test_21_static_page_visit_logs_phase3.py:233\n   `test_forged_user_agent_does_not_move_fields` names the control at :247, not the claim at :252, which is that the runbook filter does not list the forged 404. If :252 fails, the runner's output reports a field-shift problem and does not say the runbook listed a forged visit. `test_runbook_finds_visit_and_client_record` (:255) states no \"when\".\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `code_under_test` lists tests/active/test_static_page_visit_logs.py, which does not resolve (no file matches tests/**/test_static_page_visit_logs*.py). It was not read.\n2. DEPLOYMENT.md has no `### Follow an About visit` heading. The Triage subsections run from `### Triage` (l.195) to `### Follow one request` (l.231), with no section between. So the runbook's listing filter and correlation commands could not be read, and C1c and C2 were judged against the test's assertions alone.\n3. `fixtures_path` was not supplied. The test uses only pytest's built-in `tmp_path`, so no conftest was needed.",
        "map": [
          {
            "id": "C1a",
            "source": "must_prove",
            "clause": "\"does not list a 404 About request whose user agent carries forged status=200, method=GET and page=about tokens as a successful GET\"",
            "assertion": ":252",
            "excludes": "a substring grep for ` status=200 ` or ` method=GET `. The control at :245 shows the forged tokens reached the line space-delimited, so such a grep would list the 404",
            "status": "CARRIED"
          },
          {
            "id": "C1b",
            "source": "must_prove",
            "clause": "the \"listing filter\" lists the real successful GET",
            "assertion": ":252",
            "excludes": "a filter that prints nothing, and a runbook with no such filter (the placeholder key fails the comparison)",
            "status": "CARRIED"
          },
          {
            "id": "C1c",
            "source": "must_prove",
            "clause": "the filter \"selects by field position\"",
            "assertion": "none",
            "excludes": "nothing. :247 checks the log line's sixth field, not how the runbook's filter selects. :252 passes any filter the one forged ordering (`status=200 method=GET page=about`) fails to fool, including a non-positional contiguous grep ` method=GET status=200 `",
            "status": "UNCARRIED"
          },
          {
            "id": "C2a",
            "source": "must_prove",
            "clause": "\"the visitor's\" record: matched by the visit's address",
            "assertion": ":291, :292",
            "excludes": "an unanchored `ip=1.2.3.4` match picking up the 1.2.3.45 neighbour at +20 s; resolving the visit from the last pages line instead of by request_id",
            "status": "CARRIED"
          },
          {
            "id": "C2b",
            "source": "must_prove",
            "clause": "\"in-window\"",
            "assertion": ":291, :292",
            "excludes": "no time filter (the \u221260 s and +3600 s records are present); a local-time conversion without `-u` (control :262)",
            "status": "CARRIED"
          },
          {
            "id": "C2c",
            "source": "must_prove",
            "clause": "\"request.start record\", not the rest of the request",
            "assertion": ":291, :292",
            "excludes": "also printing the rid-match `request.end` record that :273 writes",
            "status": "CARRIED"
          },
          {
            "id": "C2d",
            "source": "must_prove",
            "clause": "\"exactly\" that one record",
            "assertion": ":291, :292",
            "excludes": "extra or duplicate Client records (list equality against a one-element list)",
            "status": "CARRIED"
          },
          {
            "id": "C2e",
            "source": "must_prove",
            "clause": "\"from real ClientLogFormatter output\"",
            "assertion": ":283 (input via :217, :282)",
            "excludes": "hand-written Client lines that differ from what `server.ClientLogFormatter` renders",
            "status": "CARRIED"
          },
          {
            "id": "C2f",
            "source": "must_prove",
            "clause": "\"in \u2026 JSON\" mode",
            "assertion": ":291",
            "excludes": "a correlation that works only on text lines",
            "status": "CARRIED"
          },
          {
            "id": "C2g",
            "source": "must_prove",
            "clause": "\"and text modes\"",
            "assertion": ":292",
            "excludes": "a jq-only correlation that prints nothing for text lines",
            "status": "CARRIED"
          },
          {
            "id": "D1",
            "source": "docstring",
            "clause": "\"list About visits by field position\" (module, l.1)",
            "assertion": "none",
            "excludes": "same gap as C1c: a non-positional filter that beats this one token ordering passes",
            "status": "UNCARRIED"
          },
          {
            "id": "D2a",
            "source": "docstring",
            "clause": "\"find a visit's Client request.start record by its address\" (l.1)",
            "assertion": ":291, :292",
            "excludes": "the prefix-address neighbour",
            "status": "CARRIED"
          },
          {
            "id": "D2b",
            "source": "docstring",
            "clause": "\"and a time window after it\" (l.1)",
            "assertion": "none",
            "excludes": "only windows reaching back 60 s or more are excluded. A \u00b130 s window passes, because no visitor-address record sits a few seconds before the visit",
            "status": "UNCARRIED"
          },
          {
            "id": "D3",
            "source": "docstring",
            "clause": "GET /about.html 200, HEAD /about 200, and GET /about/ 404 each write a pages line (l.3)",
            "assertion": ":243",
            "excludes": "a missing or doubled pages line, or the forged request not answered 404",
            "status": "CARRIED"
          },
          {
            "id": "D4",
            "source": "docstring",
            "clause": "\"the forged one keeps `status=404` as its sixth field\" (l.3)",
            "assertion": ":247",
            "excludes": "forged tokens shifting the status field",
            "status": "CARRIED"
          },
          {
            "id": "D5",
            "source": "docstring",
            "clause": "\"every runbook line that filters the pages log for GET and 200 prints exactly the real GET line\" (l.3, l.234)",
            "assertion": ":252",
            "excludes": "any filter line printing the forged, HEAD or extra lines",
            "status": "CARRIED"
          },
          {
            "id": "D6",
            "source": "docstring",
            "clause": "\"not the one 60 s before, the one 1 h after, nor the one 20 s after from 1.2.3.45\" (l.4, l.256)",
            "assertion": ":291, :292",
            "excludes": "each named decoy being printed",
            "status": "CARRIED"
          },
          {
            "id": "D7",
            "source": "docstring",
            "clause": "\"Its one `name=<\u2026>` placeholder line gets the visit's request_id\" (l.6)",
            "assertion": ":277",
            "excludes": "a non-empty runbook with zero or several placeholders",
            "status": "CARRIED"
          },
          {
            "id": "D8",
            "source": "docstring",
            "clause": "\"A missing section is an empty runbook, which fails at the claim assertions\" (l.6)",
            "assertion": ":252, :291",
            "excludes": "a missing section passing silently",
            "status": "CARRIED"
          },
          {
            "id": "D9",
            "source": "docstring",
            "clause": "\"not \u2026 a HEAD /about 200\" (l.234)",
            "assertion": ":252",
            "excludes": "a filter on status alone, which also lists the method=HEAD line",
            "status": "CARRIED"
          },
          {
            "id": "D10",
            "source": "docstring",
            "clause": "\"Given the visit's request_id\" picks the right visit out of three (l.256, l.264)",
            "assertion": ":291, :292",
            "excludes": "taking the last pages line (lands on the neighbour) or every line",
            "status": "CARRIED"
          },
          {
            "id": "D11",
            "source": "docstring",
            "clause": "\"Skipped when nginx, bash, jq, awk or a `date` that reads `-u -d @<epoch.ms>` is missing\" (l.6)",
            "assertion": ":111, :117, :123, :261",
            "excludes": "running against a missing tool or a `date` without epoch.ms support",
            "status": "CARRIED"
          },
          {
            "id": "N1",
            "source": "name",
            "clause": "\"forged user agent does not move fields\"",
            "assertion": ":247",
            "excludes": "the forged tokens shifting the positional fields",
            "status": "CARRIED"
          },
          {
            "id": "N2",
            "source": "name",
            "clause": "\"runbook finds visit\"",
            "assertion": ":291, :292",
            "excludes": "resolving the wrong pages line (only the right visit's address and time yield rid-match)",
            "status": "CARRIED"
          },
          {
            "id": "N3",
            "source": "name",
            "clause": "\"and client record\"",
            "assertion": ":291, :292",
            "excludes": "the wrong Client record or none",
            "status": "CARRIED"
          }
        ],
        "map_problem": ""
      },
      {
        "shape": "SHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. doc-lint-grep (rules/shape.md), sitting outside the entry's intent \u2014 tests/tmp/test_21_static_page_visit_logs_phase3.py:66\n   assert SITE_LINE in text, f\"{SITE_LINE} not in DEPLOYMENT.md\"\n   This line matches three of the entry's <how_to_spot> bullets: it calls `read_text()` on a `.md` file, asserts that a substring is present, and runs no parse before the assertion. It does not match the fourth: it is not checking anyone's choice of words. It checks that the anchor `_site_block()` uses to find the \u00a76 nginx fence is still there. Line 141 (`assert old in server_text`) is the same kind of check: a safety precondition on the extracted fence before the test swaps in local paths and ports. Neither line carries C1 or C2. Both claims are asserted only on the output of the runbook commands when they are actually run. So I am not blocking on this. If someone retitles \u00a76 or rewrites a swapped token, these lines will fail as a test error that has nothing to do with the runbook's behaviour. `shape.md` has no entry for an assertion that only locates something on the way to a behavioural check.\n\nPREDICTED FAILURE\nDEPLOYMENT.md has no `### Follow an About visit` heading (its only Triage subsection is `### Follow one request`), so `_runbook()` returns `[]`. `test_forged_user_agent_does_not_move_fields` should then fail at line 252: `{}` is compared with `{\"<a runbook line filtering the pages log for GET and 200>\": [<the real GET /about.html 200 pages line>]}`. `test_runbook_finds_visit_and_client_record` should fail at line 292: `got[\"json\"] == []` is compared with the single rendered JSON request.start record for `rid-match`. Line 278's control lets the empty runbook through. If nginx, bash, jq, awk or a suitable `date` is missing, the affected test skips instead of failing.\n\nNOT ASSESSED\n1. `code_under_test` lists tests/active/test_static_page_visit_logs.py, but that path does not exist and no `tests/**/test_static_page_visit_logs*.py` file matched. Its role, if any, was not assessed. The test under audit does not import it.\n2. The stub question was answered from the assertion form and the fixture design. For C1, the 404 line has forged `status=200 method=GET page=about` tokens and also the real-order ` method=GET status=200 rt=0.000 ` sequence, and there is a HEAD 200 control line, so a substring grep, a `$5`-only filter or a status-only filter would fail line 252. For C2, the distractors (\u22125 s, \u221260 s, +1 h, and +20 s from the neighbour 1.2.3.45), the EST5 TZ and the JSON/text pair mean that taking the last line, every line, an IP prefix match, a window without `-u`, or a symmetric window would all fail lines 292\u2013293. I did not check this against an actual runbook, because none exists yet.",
        "claim": "CLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (25 clauses: 10 must_prove, 12 docstring, 3 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | \"does not list a 404 About request whose user agent carries forged status=200, method=GET and page=about tokens as a successful GET\" | :252 | A substring grep for ` status=200 ` or ` method=GET `. The control at :245 shows that the forged tokens reached the pages line space-delimited, so such a grep lists the 404 | CARRIED |\n| C1b | must_prove | the \"listing filter\" lists the real successful GET | :252 | A filter that prints nothing. Also a runbook with no such filter: its `{}` fails against the placeholder key | CARRIED |\n| C1c | must_prove | the filter \"selects by field position\" | :252 (control :245, :247) | A non-positional contiguous grep for the real field order ` method=GET status=200 rt=`. FORGED_UA (:39) now repeats that order inside the 404's user agent, so the grep lists the 404. :247 confirms field 6 is still `status=404` | CARRIED |\n| C2a | must_prove | \"the visitor's\" record: matched by the visit's address | :292, :293 | An unanchored `ip=1.2.3.4` match picking up the 1.2.3.45 neighbour at +20 s. Also resolving the visit from the last pages line (:265, the neighbour at +15 s) instead of by request_id | CARRIED |\n| C2b | must_prove | \"in-window\" | :292, :293 | No time filter: the \u221260 s and +3600 s records are present (:269). A local-time conversion without `-u` (control :262) | CARRIED |\n| C2c | must_prove | \"request.start record\", not the rest of the request | :292, :293 | Also printing the `request.end` record with the same rid (rid-match) that :274 writes | CARRIED |\n| C2d | must_prove | \"exactly\" that one record | :292, :293 | Extra or duplicate Client records: the comparison is list equality against a one-element list (:288) | CARRIED |\n| C2e | must_prove | \"from real ClientLogFormatter output\" | :284 (input via :217, :283) | Hand-written Client lines that differ from what `server.ClientLogFormatter` renders | CARRIED |\n| C2f | must_prove | \"in \u2026 JSON\" mode | :292 | A correlation that works only on text lines | CARRIED |\n| C2g | must_prove | \"and text modes\" | :293 | A jq-only correlation that prints nothing for text lines | CARRIED |\n| D1 | docstring | \"list About visits by field position\" (module, l.1) | :252 (control :245) | Same as C1c: the real-order contiguous grep lists the forged 404 | CARRIED |\n| D2a | docstring | \"find a visit's Client request.start record by its address\" (l.1) | :292, :293 | The neighbour whose address has the visitor's as a prefix | CARRIED |\n| D2b | docstring | \"and a time window after it\" (l.1) | :292, :293 | Any window reaching back 5 s or more. The `just_before` record at \u22125 s (:269) is printed by a symmetric \u00b130 s window, so that window fails | CARRIED |\n| D3 | docstring | GET /about.html 200, HEAD /about 200 and GET /about/ 404 each write a pages line (l.3) | :243 | A missing or doubled pages line, or the forged request not being answered 404 | CARRIED |\n| D4 | docstring | \"the forged one keeps `status=404` as its sixth field\" (l.3) | :247 | Forged tokens shifting the status field | CARRIED |\n| D5 | docstring | \"every runbook line that filters the pages log for GET and 200 prints exactly the real GET line\" (l.3, l.234) | :252 | Any filter line that prints the forged line, the HEAD line or extra lines | CARRIED |\n| D6 | docstring | \"not the one 60 s before, the one 1 h after, nor the one 20 s after from 1.2.3.45\" (l.4, l.256) | :292, :293 | Any of the named decoys being printed | CARRIED |\n| D7 | docstring | \"Its one `name=<\u2026>` placeholder line gets the visit's request_id\" (l.6) | :278 | A non-empty runbook with zero placeholders or several | CARRIED |\n| D8 | docstring | \"A missing section is an empty runbook, which fails at the claim assertions\" (l.6) | :252, :292 | A missing section passing silently | CARRIED |\n| D9 | docstring | \"not \u2026 a HEAD /about 200\" (l.234) | :252 | A filter on status alone, which also lists the `method=HEAD` line | CARRIED |\n| D10 | docstring | \"Given the visit's request_id\" picks the right visit out of three (l.256, l.264) | :292, :293 | Taking the last pages line (it lands on the neighbour) or every line | CARRIED |\n| D11 | docstring | \"Skipped when nginx, bash, jq, awk or a `date` that reads `-u -d @<epoch.ms>` is missing\" (l.6) | :111, :117, :123, :261 | Running against a missing tool, or against a `date` without epoch.ms support | CARRIED |\n| N1 | name | \"forged user agent does not move fields\" | :247 | The forged tokens shifting the positional fields | CARRIED |\n| N2 | name | \"runbook finds visit\" | :292, :293 | Resolving the wrong pages line: only the right visit's address and time yield rid-match | CARRIED |\n| N3 | name | \"and client record\" | :292, :293 | The wrong Client record, or none | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nOBSERVATIONS\n1. whole-claim (rules/testing.md): tests/tmp/test_21_static_page_visit_logs_phase3.py:39, :252\n   C1c and D1 are now CARRIED, but they exclude only some non-positional filters, not every one.\n   - FORGED_UA puts `page=about` in front of the repeated `method=GET status=200 rt=0.000`.\n   - So a grep anchored on the preceding key, such as `grep 'ip=[^ ]* method=GET status=200 '`, does not match the 404 and passes :252. That grep still does not select by field position.\n   - Forging the whole field prefix in the user agent would leave only line-anchored or field-number filters able to pass. An example is ` ip=1.2.3.4 method=GET status=200 rt=0.000 request_id=\u2026 `.\n   - The round-one gap (the contiguous real-order grep) is closed by an added assertion input, not by narrowing the prose.\n2. whole-claim (rules/testing.md): tests/tmp/test_21_static_page_visit_logs_phase3.py:4, :256, :268\u2013269\n   The docstring has grown a clause that no ledger row names: \"not the one 5 s before\". It is carried. The `just_before` record at \u22125 s (:269) is excluded by :292 and :293. This is the same input that now carries D2b.\n\nNOT ASSESSED\n1. `code_under_test` lists DEPLOYMENT.md's \"Follow an About visit\" heading and its fenced bash blocks. DEPLOYMENT.md as read has no `### Follow an About visit` heading; the Triage section goes from \"Follow one request\" (l.231) to \"## 3) Build the client\". So I judged what each assertion excludes from the test and the \u00a76 `peertube_browser_pages` log format (DEPLOYMENT.md:417). I did not check it against the runbook's actual commands.\n2. `code_under_test` lists tests/active/test_static_page_visit_logs.py, which does not resolve. The test under audit does not import it.",
        "body": "### devsecops-test-shape-auditor\n\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. doc-lint-grep (rules/shape.md), sitting outside the entry's intent \u2014 tests/tmp/test_21_static_page_visit_logs_phase3.py:66\n   assert SITE_LINE in text, f\"{SITE_LINE} not in DEPLOYMENT.md\"\n   This line matches three of the entry's <how_to_spot> bullets: it calls `read_text()` on a `.md` file, asserts that a substring is present, and runs no parse before the assertion. It does not match the fourth: it is not checking anyone's choice of words. It checks that the anchor `_site_block()` uses to find the \u00a76 nginx fence is still there. Line 141 (`assert old in server_text`) is the same kind of check: a safety precondition on the extracted fence before the test swaps in local paths and ports. Neither line carries C1 or C2. Both claims are asserted only on the output of the runbook commands when they are actually run. So I am not blocking on this. If someone retitles \u00a76 or rewrites a swapped token, these lines will fail as a test error that has nothing to do with the runbook's behaviour. `shape.md` has no entry for an assertion that only locates something on the way to a behavioural check.\n\nPREDICTED FAILURE\nDEPLOYMENT.md has no `### Follow an About visit` heading (its only Triage subsection is `### Follow one request`), so `_runbook()` returns `[]`. `test_forged_user_agent_does_not_move_fields` should then fail at line 252: `{}` is compared with `{\"<a runbook line filtering the pages log for GET and 200>\": [<the real GET /about.html 200 pages line>]}`. `test_runbook_finds_visit_and_client_record` should fail at line 292: `got[\"json\"] == []` is compared with the single rendered JSON request.start record for `rid-match`. Line 278's control lets the empty runbook through. If nginx, bash, jq, awk or a suitable `date` is missing, the affected test skips instead of failing.\n\nNOT ASSESSED\n1. `code_under_test` lists tests/active/test_static_page_visit_logs.py, but that path does not exist and no `tests/**/test_static_page_visit_logs*.py` file matched. Its role, if any, was not assessed. The test under audit does not import it.\n2. The stub question was answered from the assertion form and the fixture design. For C1, the 404 line has forged `status=200 method=GET page=about` tokens and also the real-order ` method=GET status=200 rt=0.000 ` sequence, and there is a HEAD 200 control line, so a substring grep, a `$5`-only filter or a status-only filter would fail line 252. For C2, the distractors (\u22125 s, \u221260 s, +1 h, and +20 s from the neighbour 1.2.3.45), the EST5 TZ and the JSON/text pair mean that taking the last line, every line, an IP prefix match, a window without `-u`, or a symmetric window would all fail lines 292\u2013293. I did not check this against an actual runbook, because none exists yet.\n\n### devsecops-test-claim-auditor\n\nCLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (25 clauses: 10 must_prove, 12 docstring, 3 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | \"does not list a 404 About request whose user agent carries forged status=200, method=GET and page=about tokens as a successful GET\" | :252 | A substring grep for ` status=200 ` or ` method=GET `. The control at :245 shows that the forged tokens reached the pages line space-delimited, so such a grep lists the 404 | CARRIED |\n| C1b | must_prove | the \"listing filter\" lists the real successful GET | :252 | A filter that prints nothing. Also a runbook with no such filter: its `{}` fails against the placeholder key | CARRIED |\n| C1c | must_prove | the filter \"selects by field position\" | :252 (control :245, :247) | A non-positional contiguous grep for the real field order ` method=GET status=200 rt=`. FORGED_UA (:39) now repeats that order inside the 404's user agent, so the grep lists the 404. :247 confirms field 6 is still `status=404` | CARRIED |\n| C2a | must_prove | \"the visitor's\" record: matched by the visit's address | :292, :293 | An unanchored `ip=1.2.3.4` match picking up the 1.2.3.45 neighbour at +20 s. Also resolving the visit from the last pages line (:265, the neighbour at +15 s) instead of by request_id | CARRIED |\n| C2b | must_prove | \"in-window\" | :292, :293 | No time filter: the \u221260 s and +3600 s records are present (:269). A local-time conversion without `-u` (control :262) | CARRIED |\n| C2c | must_prove | \"request.start record\", not the rest of the request | :292, :293 | Also printing the `request.end` record with the same rid (rid-match) that :274 writes | CARRIED |\n| C2d | must_prove | \"exactly\" that one record | :292, :293 | Extra or duplicate Client records: the comparison is list equality against a one-element list (:288) | CARRIED |\n| C2e | must_prove | \"from real ClientLogFormatter output\" | :284 (input via :217, :283) | Hand-written Client lines that differ from what `server.ClientLogFormatter` renders | CARRIED |\n| C2f | must_prove | \"in \u2026 JSON\" mode | :292 | A correlation that works only on text lines | CARRIED |\n| C2g | must_prove | \"and text modes\" | :293 | A jq-only correlation that prints nothing for text lines | CARRIED |\n| D1 | docstring | \"list About visits by field position\" (module, l.1) | :252 (control :245) | Same as C1c: the real-order contiguous grep lists the forged 404 | CARRIED |\n| D2a | docstring | \"find a visit's Client request.start record by its address\" (l.1) | :292, :293 | The neighbour whose address has the visitor's as a prefix | CARRIED |\n| D2b | docstring | \"and a time window after it\" (l.1) | :292, :293 | Any window reaching back 5 s or more. The `just_before` record at \u22125 s (:269) is printed by a symmetric \u00b130 s window, so that window fails | CARRIED |\n| D3 | docstring | GET /about.html 200, HEAD /about 200 and GET /about/ 404 each write a pages line (l.3) | :243 | A missing or doubled pages line, or the forged request not being answered 404 | CARRIED |\n| D4 | docstring | \"the forged one keeps `status=404` as its sixth field\" (l.3) | :247 | Forged tokens shifting the status field | CARRIED |\n| D5 | docstring | \"every runbook line that filters the pages log for GET and 200 prints exactly the real GET line\" (l.3, l.234) | :252 | Any filter line that prints the forged line, the HEAD line or extra lines | CARRIED |\n| D6 | docstring | \"not the one 60 s before, the one 1 h after, nor the one 20 s after from 1.2.3.45\" (l.4, l.256) | :292, :293 | Any of the named decoys being printed | CARRIED |\n| D7 | docstring | \"Its one `name=<\u2026>` placeholder line gets the visit's request_id\" (l.6) | :278 | A non-empty runbook with zero placeholders or several | CARRIED |\n| D8 | docstring | \"A missing section is an empty runbook, which fails at the claim assertions\" (l.6) | :252, :292 | A missing section passing silently | CARRIED |\n| D9 | docstring | \"not \u2026 a HEAD /about 200\" (l.234) | :252 | A filter on status alone, which also lists the `method=HEAD` line | CARRIED |\n| D10 | docstring | \"Given the visit's request_id\" picks the right visit out of three (l.256, l.264) | :292, :293 | Taking the last pages line (it lands on the neighbour) or every line | CARRIED |\n| D11 | docstring | \"Skipped when nginx, bash, jq, awk or a `date` that reads `-u -d @<epoch.ms>` is missing\" (l.6) | :111, :117, :123, :261 | Running against a missing tool, or against a `date` without epoch.ms support | CARRIED |\n| N1 | name | \"forged user agent does not move fields\" | :247 | The forged tokens shifting the positional fields | CARRIED |\n| N2 | name | \"runbook finds visit\" | :292, :293 | Resolving the wrong pages line: only the right visit's address and time yield rid-match | CARRIED |\n| N3 | name | \"and client record\" | :292, :293 | The wrong Client record, or none | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nOBSERVATIONS\n1. whole-claim (rules/testing.md): tests/tmp/test_21_static_page_visit_logs_phase3.py:39, :252\n   C1c and D1 are now CARRIED, but they exclude only some non-positional filters, not every one.\n   - FORGED_UA puts `page=about` in front of the repeated `method=GET status=200 rt=0.000`.\n   - So a grep anchored on the preceding key, such as `grep 'ip=[^ ]* method=GET status=200 '`, does not match the 404 and passes :252. That grep still does not select by field position.\n   - Forging the whole field prefix in the user agent would leave only line-anchored or field-number filters able to pass. An example is ` ip=1.2.3.4 method=GET status=200 rt=0.000 request_id=\u2026 `.\n   - The round-one gap (the contiguous real-order grep) is closed by an added assertion input, not by narrowing the prose.\n2. whole-claim (rules/testing.md): tests/tmp/test_21_static_page_visit_logs_phase3.py:4, :256, :268\u2013269\n   The docstring has grown a clause that no ledger row names: \"not the one 5 s before\". It is carried. The `just_before` record at \u22125 s (:269) is excluded by :292 and :293. This is the same input that now carries D2b.\n\nNOT ASSESSED\n1. `code_under_test` lists DEPLOYMENT.md's \"Follow an About visit\" heading and its fenced bash blocks. DEPLOYMENT.md as read has no `### Follow an About visit` heading; the Triage section goes from \"Follow one request\" (l.231) to \"## 3) Build the client\". So I judged what each assertion excludes from the test and the \u00a76 `peertube_browser_pages` log format (DEPLOYMENT.md:417). I did not check it against the runbook's actual commands.\n2. `code_under_test` lists tests/active/test_static_page_visit_logs.py, which does not resolve. The test under audit does not import it.",
        "map": [
          {
            "id": "C1a",
            "source": "must_prove",
            "clause": "\"does not list a 404 About request whose user agent carries forged status=200, method=GET and page=about tokens as a successful GET\"",
            "assertion": ":252",
            "excludes": "A substring grep for ` status=200 ` or ` method=GET `. The control at :245 shows that the forged tokens reached the pages line space-delimited, so such a grep lists the 404",
            "status": "CARRIED"
          },
          {
            "id": "C1b",
            "source": "must_prove",
            "clause": "the \"listing filter\" lists the real successful GET",
            "assertion": ":252",
            "excludes": "A filter that prints nothing. Also a runbook with no such filter: its `{}` fails against the placeholder key",
            "status": "CARRIED"
          },
          {
            "id": "C1c",
            "source": "must_prove",
            "clause": "the filter \"selects by field position\"",
            "assertion": ":252 (control :245, :247)",
            "excludes": "A non-positional contiguous grep for the real field order ` method=GET status=200 rt=`. FORGED_UA (:39) now repeats that order inside the 404's user agent, so the grep lists the 404. :247 confirms field 6 is still `status=404`",
            "status": "CARRIED"
          },
          {
            "id": "C2a",
            "source": "must_prove",
            "clause": "\"the visitor's\" record: matched by the visit's address",
            "assertion": ":292, :293",
            "excludes": "An unanchored `ip=1.2.3.4` match picking up the 1.2.3.45 neighbour at +20 s. Also resolving the visit from the last pages line (:265, the neighbour at +15 s) instead of by request_id",
            "status": "CARRIED"
          },
          {
            "id": "C2b",
            "source": "must_prove",
            "clause": "\"in-window\"",
            "assertion": ":292, :293",
            "excludes": "No time filter: the \u221260 s and +3600 s records are present (:269). A local-time conversion without `-u` (control :262)",
            "status": "CARRIED"
          },
          {
            "id": "C2c",
            "source": "must_prove",
            "clause": "\"request.start record\", not the rest of the request",
            "assertion": ":292, :293",
            "excludes": "Also printing the `request.end` record with the same rid (rid-match) that :274 writes",
            "status": "CARRIED"
          },
          {
            "id": "C2d",
            "source": "must_prove",
            "clause": "\"exactly\" that one record",
            "assertion": ":292, :293",
            "excludes": "Extra or duplicate Client records: the comparison is list equality against a one-element list (:288)",
            "status": "CARRIED"
          },
          {
            "id": "C2e",
            "source": "must_prove",
            "clause": "\"from real ClientLogFormatter output\"",
            "assertion": ":284 (input via :217, :283)",
            "excludes": "Hand-written Client lines that differ from what `server.ClientLogFormatter` renders",
            "status": "CARRIED"
          },
          {
            "id": "C2f",
            "source": "must_prove",
            "clause": "\"in \u2026 JSON\" mode",
            "assertion": ":292",
            "excludes": "A correlation that works only on text lines",
            "status": "CARRIED"
          },
          {
            "id": "C2g",
            "source": "must_prove",
            "clause": "\"and text modes\"",
            "assertion": ":293",
            "excludes": "A jq-only correlation that prints nothing for text lines",
            "status": "CARRIED"
          },
          {
            "id": "D1",
            "source": "docstring",
            "clause": "\"list About visits by field position\" (module, l.1)",
            "assertion": ":252 (control :245)",
            "excludes": "Same as C1c: the real-order contiguous grep lists the forged 404",
            "status": "CARRIED"
          },
          {
            "id": "D2a",
            "source": "docstring",
            "clause": "\"find a visit's Client request.start record by its address\" (l.1)",
            "assertion": ":292, :293",
            "excludes": "The neighbour whose address has the visitor's as a prefix",
            "status": "CARRIED"
          },
          {
            "id": "D2b",
            "source": "docstring",
            "clause": "\"and a time window after it\" (l.1)",
            "assertion": ":292, :293",
            "excludes": "Any window reaching back 5 s or more. The `just_before` record at \u22125 s (:269) is printed by a symmetric \u00b130 s window, so that window fails",
            "status": "CARRIED"
          },
          {
            "id": "D3",
            "source": "docstring",
            "clause": "GET /about.html 200, HEAD /about 200 and GET /about/ 404 each write a pages line (l.3)",
            "assertion": ":243",
            "excludes": "A missing or doubled pages line, or the forged request not being answered 404",
            "status": "CARRIED"
          },
          {
            "id": "D4",
            "source": "docstring",
            "clause": "\"the forged one keeps `status=404` as its sixth field\" (l.3)",
            "assertion": ":247",
            "excludes": "Forged tokens shifting the status field",
            "status": "CARRIED"
          },
          {
            "id": "D5",
            "source": "docstring",
            "clause": "\"every runbook line that filters the pages log for GET and 200 prints exactly the real GET line\" (l.3, l.234)",
            "assertion": ":252",
            "excludes": "Any filter line that prints the forged line, the HEAD line or extra lines",
            "status": "CARRIED"
          },
          {
            "id": "D6",
            "source": "docstring",
            "clause": "\"not the one 60 s before, the one 1 h after, nor the one 20 s after from 1.2.3.45\" (l.4, l.256)",
            "assertion": ":292, :293",
            "excludes": "Any of the named decoys being printed",
            "status": "CARRIED"
          },
          {
            "id": "D7",
            "source": "docstring",
            "clause": "\"Its one `name=<\u2026>` placeholder line gets the visit's request_id\" (l.6)",
            "assertion": ":278",
            "excludes": "A non-empty runbook with zero placeholders or several",
            "status": "CARRIED"
          },
          {
            "id": "D8",
            "source": "docstring",
            "clause": "\"A missing section is an empty runbook, which fails at the claim assertions\" (l.6)",
            "assertion": ":252, :292",
            "excludes": "A missing section passing silently",
            "status": "CARRIED"
          },
          {
            "id": "D9",
            "source": "docstring",
            "clause": "\"not \u2026 a HEAD /about 200\" (l.234)",
            "assertion": ":252",
            "excludes": "A filter on status alone, which also lists the `method=HEAD` line",
            "status": "CARRIED"
          },
          {
            "id": "D10",
            "source": "docstring",
            "clause": "\"Given the visit's request_id\" picks the right visit out of three (l.256, l.264)",
            "assertion": ":292, :293",
            "excludes": "Taking the last pages line (it lands on the neighbour) or every line",
            "status": "CARRIED"
          },
          {
            "id": "D11",
            "source": "docstring",
            "clause": "\"Skipped when nginx, bash, jq, awk or a `date` that reads `-u -d @<epoch.ms>` is missing\" (l.6)",
            "assertion": ":111, :117, :123, :261",
            "excludes": "Running against a missing tool, or against a `date` without epoch.ms support",
            "status": "CARRIED"
          },
          {
            "id": "N1",
            "source": "name",
            "clause": "\"forged user agent does not move fields\"",
            "assertion": ":247",
            "excludes": "The forged tokens shifting the positional fields",
            "status": "CARRIED"
          },
          {
            "id": "N2",
            "source": "name",
            "clause": "\"runbook finds visit\"",
            "assertion": ":292, :293",
            "excludes": "Resolving the wrong pages line: only the right visit's address and time yield rid-match",
            "status": "CARRIED"
          },
          {
            "id": "N3",
            "source": "name",
            "clause": "\"and client record\"",
            "assertion": ":292, :293",
            "excludes": "The wrong Client record, or none",
            "status": "CARRIED"
          }
        ],
        "map_problem": ""
      }
    ]
  },
  "refactors": "<refactors>\nnone \u2014 DEPLOYMENT.md was read in full over the changed regions (the \u00a76 site block at lines 433\u2013471 and \"Follow an About visit\" at lines 231\u2013247), and nothing in them could be changed without breaking a gated check or adding new behaviour.\n</refactors>\n\n<left_out>\nMerging the three About locations (`= /about`, `= /about/`, `= /about.html`) into one regex location in DEPLOYMENT.md \u00a76: left out because the gated phase-1 checkpoint parses exact locations and needs exactly one `try_files` in each, so merging them would break that check rather than refactor the code. The repetition is already documented by the rat-tail comment and the access_log comment above the locations.\nRemoving the repeated `set $static_page` and both `access_log` lines from each About location, by using an http-level `map $uri $static_page` plus a server-level `access_log \u2026 peertube_browser_pages if=$static_page;`: left out because I could not be sure of it without a run. It adds a brace-holding `map {}` block outside `server {}` that the checkpoint's `_site_block()`/`_statements()` parsing may not handle. It also moves the About URL set into a second place that the rat-tail mapping comparison does not check, and I have not seen how nginx handles the pages log for non-About routes under `if=`.\nNot refactors, but for whoever owns the next step: (1) `tests/active/test_static_page_visit_logs.py`, which the rat-tail comment names, does not exist in the worktree yet; promoting the gated checkpoints is up to the workflow. (2) `.un/skills/devsecops/config.json` has no `test_static_page_visit_logs.py` group. It should list DEPLOYMENT.md, client/frontend/vite.config.ts, client/frontend/dev-pages/about.template.html and client/backend/server.py (the source of ClientLogFormatter). (3) Earlier steps left probe files in tests/tmp/ that I have no tool to delete: probe_pages_log.py and probe_about_runbook_date.py (emptied), and probe_21_pages_log.py, probe_21_about_block.py, test_probe_21_p1_nginx.py, test_probe_21_p3.py and test_probe_21_p3c.py. (4) The step's \"What the pass is measured against\" section came through as the literal placeholder `{rat_tail_rules}`, so the pass was checked against the role's rat-tail rule only.\n</left_out>\n\n<needs_fresh_red>\nnone\n</needs_fresh_red>\n\n<observation>\nFrom reading the code only, without a run: the About site block and the runbook are already the smallest form the gated checkpoints allow, so this pass changed no file.\n</observation>"
}
```
dev-flow:state -->

## 2026-10-02 - Step 0 - baseline

Resolved paths: {
  "active": "tests/active",
  "working": "tests/tmp",
  "plans": "docs/project/plans",
  "delete_me": "delete_me",
  "archive": "tests/archive",
  "project_dir": "/home/enduser/code/PeerTube-browser/.worktrees/21",
  "record": "tests/last_test_validation.json",
  "output": "tests/last_test_output.txt"
}

Pre-build suite exited 0. Baseline variant: False.

```
selected 1 of 46 test groups (45 unchanged):
  test_search_fusion.py — no map entry
  test_search_fusion.py  10 passed                              2.2s
  ---------------------
  total                  10 passed                              2.4s wall, 1 lane

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

## 2026-10-02 - Step 1 - Gather requirements

Approved by the operator.

### requirements

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

### conflicts

Request "Correlation by request id ... works against app traces" and "Preserve/propagate X-Request-ID" vs tree: About has no scripts and makes no API calls (`client/frontend/dev-pages/about.template.html`), and public nginx assigns each request its own `$request_id`, so an About visit can never share a request id with the visitor's app traces. Request-id correlation only joins the pages-log line to the same visit's main access-log line; correlation with app traces is by client IP plus time window, unless a beacon is added, which the operator ruled out of scope.
Request's premise that About visits are served as static files vs tree: the build emits only `dist/dev-pages/about.html` or `dist/dev-pages/about.template.html` (`client/frontend/vite.config.ts`), while nav links and the request target `/about.html`, and the `DEPLOYMENT.md` §6 nginx site (`try_files $uri $uri/ =404`) has no mapping, so About returns 404 in prod. The operator confirmed this and chose to add the mapping in this build.
Request Problem "not visible in app request logs" vs tree: static requests already appear in `/var/log/nginx/peertube-browser.access.log` with IP, request, status, UA, `request_id` and `rt` (`DEPLOYMENT.md` §6 `peertube_browser` format). What is missing is a dedicated About stream with a marker, and About actually serving, not nginx visibility as such.

## 2026-10-02 - Step 2 - Develop a solution

Approved by the operator.

### initial_solution

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

### conflicts

none

## 2026-10-02 - Step 3 - Identify every file, function and doc affected

Recorded ungated, at the operator direction.

### impacts


<impact path="DEPLOYMENT.md" element="§6 nginx site block (lines 415-459): new `log_format peertube_browser_pages` line under `log_format peertube_browser` (line 416)">
What changes: a second `log_format` line goes directly under line 416 and outside `server {}`, with fields `page=$static_page ts=$msec time=$time_iso8601 ip=$remote_addr method=$request_method uri="$request_uri" status=$status rt=$request_time request_id=$request_id x_request_id=$http_x_request_id ua="$http_user_agent"`. It must stay a single physical line, as line 416 is.

What depends on it: the About location's second `access_log` names it, the new runbook's greps and awk depend on its field names and order (`page=` first, `ts=`, `ip=`, `status=`, `method=`, `request_id=`), and the planned test parses lines in this format.

Regression risk:
- **`x_request_id` is unquoted.** nginx's default `log_format` escaping escapes `"`, `\` and bytes outside 0x20-0x7E, but not the space. A client can send `X-Request-ID: x status=200 method=GET` and add forged `key=value` tokens to its own line, which the runbook's `grep ' status=200 '` and awk filters then match. Quote it (`x_request_id="$http_x_request_id"`), as `uri` and `ua` are quoted. `"-"` is still the absent value.
- **`page=about` can match elsewhere.** A plain `grep 'page=about'` also matches a `uri` or `ua` that contains `page=about`, so the runbook should anchor it as `^page=about `.
- **Field order is a contract.** Because `page=` is the first field, the runbook's anchor and awk depend on the order, and so does the test.
- **`$msec` and `$time_iso8601` are taken when the line is written, at request end, not at request start.** For a static file the difference is negligible, but the prose should not call either value the request start.
- **`$static_page` exists only in the About location.** A variable created by `set` is defined server-wide, but it is evaluated only in the About location, which always sets it, so no "uninitialized variable" warnings are expected.
</impact>
<impact path="DEPLOYMENT.md" element="§6 nginx site block: new `location = /about.html`, `location = /about`, `location = /about/` inside `server {}` (between `location /` at line 428 and `location /api/` at line 432, or after it)">
What changes:
- `location = /about.html` holds `set $static_page about;`, `try_files /dev-pages/about.html /dev-pages/about.template.html =404;`, `access_log /var/log/nginx/peertube-browser.access.log peertube_browser;` and `access_log /var/log/nginx/peertube-browser.pages.access.log peertube_browser_pages;`. It has no `add_header`.
- `location = /about` and `location = /about/` each hold only `rewrite ^ /about.html last;`.

What depends on it:
- **Nav links.** Every page's nav links to `/about.html` (`client/frontend/index.html:26`, `videos.html:26`, `search.html:26`, `likes.html:26`, `video-page.html:24`, `channels.html:26`, `dev-pages/about.template.html:22`). All of them 404 in prod today, and this block makes them resolve.
- **The vite rewrite.** The block mirrors `rewriteToAbout` and `aboutSourcePath` in `client/frontend/vite.config.ts:16-22`.
- **The server-level CSP.** It is inherited, at line 426.
- **`root /var/www/peertube-browser`.** `try_files` resolves under it to `/var/www/peertube-browser/dev-pages/…`, which `rsync` (lines 407-409) and `scripts/sync.sh:22` populate.

Regression risk:
- **Other routes are untouched.** Exact-match locations only take these three URIs, so `/`, `/api/`, `/recommendations`, `/videos/similar` and `/client/` are unaffected. `/aboutX` and `/about/x` still fall to `location /` and 404.
- **The one subtle failure is the location-level `access_log`.** It replaces the server-level one, so dropping the first line silently removes About from the main log, and the prose must say so.
- **`rewrite … last` must not become `break`.** `break` would stay in the alias location, which has no `try_files` and no `access_log`. The request would then be served by the default static handler from `$uri=/about.html`, which does not exist at the root, so it would 404 and land only in the main log.
- **Adding `add_header` here would drop the CSP.** Any `add_header` added to the About location later stops the server-level CSP from being inherited.
- **If neither dev-pages file is deployed, `/about.html` keeps returning 404.** That is the same as today, but the request now also writes a pages line with `status=404`.
</impact>
<impact path="DEPLOYMENT.md" element="§6 prose after the site block (line 461 CSP paragraph, line 463 `X-Request-ID`/`log_format` paragraph)">
What changes:
- **Line 463 gains the About paragraphs.** It currently explains why `proxy_set_header` is repeated and why `log_format` stays outside `server {}`. Next to it go new sentences covering:
  - why About lists both `access_log` lines, because a location-level `access_log` replaces the inherited one;
  - why the aliases use `rewrite … last` and not `break`, `redirect` or `return 301`;
  - that the `set $static_page` variable is how a second informational page is added (one more location of the same shape, no second `log_format`);
  - that direct hits on `/dev-pages/about*.html` go through `location /` and leave no pages line;
  - that `try_files` prefers the override, as vite does;
  - that existing hosts must re-apply this file and reload;
  - log rotation.
- **Line 461 may need a sentence.** It says the browser enforces the header together with each page's own `<meta>` CSP. The About template has no `<meta>` CSP (`client/frontend/dev-pages/about.template.html:1-9`), so only the header applies to About.

What depends on it: operators reading why the block looks the way it does, and the "Follow one request" back-reference at line 463.

Regression risk:
- **Logrotate cannot be verified from the repository.** The claim that `/etc/logrotate.d/nginx` covers `/var/log/nginx/*.log` with a postrotate `USR1`/`invoke-rc.d nginx rotate` holds for the Debian/Ubuntu nginx package, but `/etc/logrotate.d/nginx` is not in this repository. The prose should name the Debian/Ubuntu package as the condition.
- **Ownership of the new file.** nginx's master process creates the new log file as root, and logrotate then re-creates it with the package's mode and owner (`0640 www-data adm` on Debian). This is consistent with the `sudo grep` in the runbook.
</impact>
<impact path="DEPLOYMENT.md" element="§6 TLS subsection (lines 525-533), `sudo certbot --nginx`">
What changes: no text change is planned, but there is an interaction with the plan's "existing deployments re-apply §6" note.

What depends on it: `certbot --nginx` rewrites `/etc/nginx/sites-available/peertube-browser` in place. It adds `listen 443 ssl`, the `ssl_certificate*` lines and usually a port-80 redirect `server` block.

Regression risk: high on TLS hosts. An operator who follows "re-apply §6" by pasting the whole new block over the site file deletes certbot's TLS lines, and the next `nginx -t && reload` serves plain HTTP only, or nothing on 443. The §6 "existing deployments" text must say to merge the `log_format` line and the three locations into the existing file, not replace it, or to re-run `certbot --nginx` afterwards. A sentence here or in the re-apply note covers it.
</impact>
<impact path="DEPLOYMENT.md" element="§6 'Verify' block (lines 475-481)">
What changes: add `curl -I http://localhost/about` (200, `Content-Security-Policy` present), optionally `/about/` and `/about.html`, then `sudo tail -n 3 /var/log/nginx/peertube-browser.pages.access.log`. The follow-up sentence about a 404 on `/` could gain the About equivalent: a 404 on `/about` with `/` at 200 means no `dev-pages/about*.html` in the document root (a stale or unbuilt copy).

What depends on it: operators after reload, and the planned test mirrors these checks.

Regression risk: low. The `curl -I` uses HEAD, which `try_files` serves as 200, but it still writes a line to both logs, so the verify step itself adds a pages line. Say so, so that it is not mistaken for a visitor.
</impact>
<impact path="DEPLOYMENT.md" element="§6 `X-Forwarded-For` and `TRUSTED_PROXIES` paragraphs (lines 465, 467)">
What changes: nothing in these paragraphs. The runbook's proxy caveat points to them.

What depends on it: correlation. The pages log records `ip=$remote_addr`, which is nginx's TCP peer. The Client's `request.start` `context.ip` is `resolve_client_address` (`client/backend/server.py:276-292`) over `X-Forwarded-For`, which `TRUSTED_PROXIES` controls.

Regression risk:
- **With a proxy in front of nginx, the two IPs never match.** The paragraph at line 467 explicitly contemplates "a CDN or a load balancer" in front of nginx. In that setup `$remote_addr` is the CDN's address for every visitor, while the Client logs the real visitor, so IP plus time-window correlation yields zero or wrong matches. The plan's caveat ("IP is resolved through `TRUSTED_PROXIES`") must say this outright. It should also either add an `xff="$http_x_forwarded_for"` field to the pages format or tell operators to use nginx `real_ip` / `set_real_ip_from` in that case.
- **The text forms can differ.** `resolve_client_address` returns an accepted hop in canonical `ipaddress` form and a peer verbatim. With the same-host nginx the Client's peer is `127.0.0.1` and the hop comes from nginx's `$proxy_add_x_forwarded_for`, which is `$remote_addr`, canonicalised by Python. IPv6 forms normally agree, but an IPv4-mapped `::ffff:` form can differ, as the plan notes.
</impact>
<impact path="DEPLOYMENT.md" element="§3 'Build the client' page-list paragraph (lines 299-303)">
What changes: it currently says nginx serves `dist/` through `try_files` and lists the pages as `index, videos, search, likes, video-page, channels and about`. It needs to say that About is built under `dev-pages/` (`dev-pages/about.html` when the untracked override exists, else `dev-pages/about.template.html`) and is reached at `/about`, `/about/` and `/about.html` through the §6 mapping, not at a root `about.html`.

What depends on it: `client/frontend/vite.config.ts:91-93` (the build input) and the committed `client/frontend/dist/dev-pages/about.template.html`. That file confirms the output path; there is no `dist/about.html`.

Regression risk: low (documentation only). It must stay consistent with §6 and `client/frontend/README.md`.
</impact>
<impact path="DEPLOYMENT.md" element="§2 Triage: 'Follow one request' (lines 231-249) and new sibling 'Follow an About visit' subsection">
What changes:
- **New subsection placement.** A new `### Follow an About visit` goes after line 249, the end of the "Follow one request" caveats, and before "Centralized installer (source of truth):" at line 251. Note that line 251 is not a heading: it is loose text that currently follows the Triage subsections. Inserting a `###` before it would make the installer blocks visually belong to the new subsection, just as they now seem to belong to "Follow one request". Place it with that in mind, or accept the existing quirk.
- **Steps.**
  1. List visits with `sudo grep '^page=about '` (anchored) on `/var/log/nginx/peertube-browser.pages.access.log`.
  2. Find the main-log line with `sudo grep "request_id=$id" /var/log/nginx/peertube-browser.access.log` (identical to line 236).
  3. Convert `ts` with `date -u -d @<msec> +%Y-%m-%dT%H:%M:%S.%3NZ` (GNU `date`; the fractional epoch is supported) and compute the window end, for example `date -u -d @$(awk "BEGIN{print $ts+300}") …`.
  4. Filter the Client journal with `jq -cR … 'fromjson? | select(.event == "request.start" and .context.ip == $ip and .ts >= $from and .ts <= $to)'`.
  5. Hand off to "Follow one request".
- **Verified against code.** The Client's JSON keys `event`, `context.ip` and `ts` (`client/backend/server.py:176-189`, `346-350`) and the fixed-width UTC `ts` `YYYY-MM-DDTHH:MM:SS.mmmZ` (`_format_ts`, lines 136-140) make the string comparison valid.
- **Text variant.** The `LOG_FORMAT=text` line is `ts LEVEL event message k=v…` (`_render_text`, lines 150-163). The message "request started" contains a space, so awk's `$1` is `ts` and `$3` is the event. `grep "ip=$ip"` must be bounded (`"ip=$ip "`, or awk `$0 ~ " ip=" ip " "`), or `ip=1.2.3.4` also matches `ip=1.2.3.45`.
- **Caveats and log list.** Four caveats are added. "What each log is for" (lines 242-244) gains a pages-log bullet.

What depends on it:
- **Pointers.** `client/README.md:75`, `engine/server/README.md:32`, `CONTEXT.md:10` and `DEPLOYMENT.md:116` and `:353` all point to "Follow one request" by name, so that heading must not be renamed.
- **Commands.** The runbook depends on the `log_format` field names, on `jq` (already assumed at lines 237-238), and on GNU `date`.

Regression risk:
- **Some Client lines cannot match.** `request.start` records carry `ip` only for Client requests, and Engine records carry the Client-forwarded `X-Client-IP`. The runbook correctly goes through the Client.
- **Ordering of the window.** The visit's `ts` is when the About request ended. API calls made on the next page come after it, so a window of `[ts, ts+300s]` is right, while one centred on `ts` would include noise. State which direction the window runs.
</impact>
<impact path="DEPLOYMENT.md" element="§2 Triage table (lines 197-229) and §2 `LOG_FORMAT` paragraph (line 116)">
What changes: optional.
- **Triage table.** A row "About (`/about`, `/about.html`) answers 404" could be added, with cause "no `dev-pages/about*.html` in `/var/www/peertube-browser`, or the site file predates the About mapping", and action "§3 build + §6 rsync, re-apply §6 locations". This sits next to the "Nothing on port 80" row at line 210.
- **Line 116.** It ends "To read every line of one request across nginx, the Client backend and the Engine, see 'Follow one request' under Triage". It could add "for an About visit, see 'Follow an About visit'". It also states that Triage recipes naming JSON keys assume `json`, and the new runbook's jq step falls under the same rule.

What depends on it: operators using the table.

Regression risk: none if omitted. It is listed so the decision is explicit.
</impact>
<impact path="DEPLOYMENT.md" element="§7 Verify list (lines 561-565)">
What changes: optional. The list names `/`, `/videos.html` and `/videos.html?debug=1`, and it could add `/about`.

What depends on it: nothing.

Regression risk: none.
</impact>
<impact path="DEPLOYMENT.md" element="§6 'Engine listener on 127.0.0.1:7079' paragraph (line 485) and line 497">
What changes: none. Line 485 says "leave the public site file above as it is, since nothing here changes it", which stays true because the installers do not write the public site file.

What depends on it: the claim that only the operator edits the public site file. This is why existing hosts only get About by re-applying §6 by hand. I grepped the installers: no script writes `sites-available/peertube-browser`.

Regression risk: none. Line 497 (the 7079 listener's own access log) is unrelated to the new pages log. The runbook should not list it among the logs to grep for About.
</impact>
<impact path="client/frontend/README.md" element="'Local About Overrides' section (lines 36-39)">
What changes: add one line saying that production nginx serves whichever file the last build produced (`dist/dev-pages/about.html` or `dist/dev-pages/about.template.html`) at `/about`, `/about/` and `/about.html` (see `DEPLOYMENT.md` §6). It could also say that the override is served under the server CSP `script-src 'self'`, so inline scripts and inline `style` attributes in an override are blocked.

What depends on it: developers writing the untracked `dev-pages/about.html`.

Regression risk: low (documentation).
</impact>
<impact path="client/frontend/src/about.css" element="About tab/panel styles, used only by the untracked `dev-pages/about.html` override">
What changes: nothing.

What depends on it: the classes `.about-tabs`, `.about-tab.is-active` and `.about-panel[hidden]` imply that the real (untracked, gitignored by `.gitignore:29-30`) About override has tabs, and tabs most likely need JavaScript. Grep finds no tracked file referencing `about.css`.

Regression risk (uncertain, since the override cannot be inspected):
- **The plan's "About has no scripts and makes no API calls" is verified only for the template.** If the override has an inline `<script>` or `style=` attributes, the server CSP blocks them now that prod serves About for the first time: there is no `style-src`, so `default-src 'self'` applies, and `script-src 'self'`.
- **API calls change the correlation premise.** If the override's script makes API calls, About visits would show in app logs, and that changes the plan's premise.

The operator should confirm what the override contains. The test step should run against the template only.
</impact>
<impact path="client/frontend/vite.config.ts" element="`aboutSourcePath`, `rewriteToAbout`, `build.rollupOptions.input.about` (lines 13-22, 91-93)">
What changes: nothing. This is the source of truth that the nginx mapping copies: the URL set is `/about`, `/about/`, `/about.html`, and the order is override first, then template.

What depends on it: the §6 `try_files` order and the URL set. The docs prose should name this file as what the mapping mirrors.

Regression risk: drift. If a later change edits the vite URL set or output path (for example, emitting `dist/about.html`), the hand-copied nginx block silently diverges. Nothing ties the two together except the planned test, which reads only `DEPLOYMENT.md`. The test could also assert that the vite `rewriteToAbout` set equals the three nginx exact locations.
</impact>
<impact path="client/frontend/dev-pages/about.template.html" element="whole file (tracked template; built to `dist/dev-pages/about.template.html`)">
What changes: nothing.

What depends on it: it is the fallback `try_files` target. Its links are all root-absolute (`/favicon.png` line 6, `/src/videos.css` line 8 becoming `/assets/videos-*.css`, nav lines 19-22), so serving it at `/about/` breaks no relative URL. Verified in `client/frontend/dist/dev-pages/about.template.html:6-22`. It has no `<meta>` CSP and no script.

Regression risk: none. Plan premise confirmed.
</impact>
<impact path="client/frontend/dist/dev-pages/about.template.html" element="committed build output">
What changes: nothing.

What depends on it: it confirms that the build output path is `dev-pages/`. The planned test could use `client/frontend/dist` as the temp nginx `root` and get a real About file without running a build.

Regression risk: `DEPLOYMENT.md:412` notes that the committed `dist/` lags the source. A test that relies on it should copy it or create a synthetic `dev-pages/about.template.html` in a temp root rather than serve the repository tree.
</impact>
<impact path="client/frontend/index.html" element="nav link `/about.html` (line 26); same in videos.html:26, search.html:26, likes.html:26, video-page.html:24, channels.html:26">
What changes: nothing in the files. Behaviour changes in prod: these links stop returning 404 once §6 is applied.

What depends on it: users' navigation. Every click on About from another page is a pages-log line with `uri="/about.html"`.

Regression risk: none. Listed as a dependent of the new location.
</impact>
<impact path="scripts/sync.sh" element="build + `rsync -a --delete` + chown (lines 17-23)">
What changes: nothing.

What depends on it: the plan's "stale dev-pages files" mitigation relies on `--delete` (line 22) removing an old `dev-pages/about.html` when a later build produced only the template, and the reverse.

Regression risk: none, but an operator copying by hand without `--delete` could keep a stale override that `try_files` prefers. The §6 rsync at line 408 also uses `--delete`.
</impact>
<impact path="client/backend/server.py" element="`_format_ts` (136-140), `_render_text` (150-163), `ClientLogFormatter.format` (174-195), `_run_request` (339-357), `resolve_client_address` (276-292)">
What changes: nothing. The runbook depends on these.

What depends on it: the runbook jq filter (`.event`, `.context.ip`, `.ts`), the text-mode awk on `$1`, and the IP equality with nginx `$remote_addr`.

Regression risk: if the Client log schema changes, for example by renaming `context.ip` or the `ts` format, the runbook breaks silently, because no test ties them together. The planned synthetic-Client-record check should build its record by calling `ClientLogFormatter` on a `request.start` record, not by hard-coding the JSON. A hard-coded double would not notice a schema change.
</impact>
<impact path="client/README.md" element="logging paragraph (line 75)">
What changes: none required. It points to "Follow one request" and says byte counts are in the nginx access log. Optionally add "About visits never reach the backend; see 'Follow an About visit'".

What depends on it: nothing.

Regression risk: none.
</impact>
<impact path="engine/server/README.md" element="request logging bullet (line 32)">
What changes: none. It points to the Triage section of `DEPLOYMENT.md` by name.

What depends on it: the Triage heading names staying stable.

Regression risk: none.
</impact>
<impact path="CONTEXT.md" element="glossary 'Request id' (line 10)">
What changes: none required. The entry says public nginx sets `X-Request-ID` and that every log record of the request carries the id, which stays true. Optionally a glossary term for the "pages log" or "informational page" could be added, since the plan introduces the concept ("Adding a second informational page…"). The plan says no change, so this is a judgement call for the docs step.

What depends on it: nothing.

Regression risk: none.
</impact>
<impact path="docs/project/issues/21-static-page-visit-logs.md" element="Status line (line 3) and `## Comments` (line 29)">
What changes: at completion, `Status: enhancement, complete`, plus a comment naming the delivery (the `DEPLOYMENT.md` §6 block, the runbook, the plan file `docs/project/plans/22-21-static-page-visit-logs.md`). The comment should state the deviations from the issue's text:
- the request-id correlation with app traces is impossible for About and is replaced by IP plus time window;
- the beacon is deferred to issue 18.

Then the file moves to `docs/project/issues/archive/` per `docs/project/issue-tracker.md:21`.

What depends on it: `docs/project/issues/18-about-outbound-click-tracking.md:30` and `docs/project/roadmap.md:157` reference it by slug.

Regression risk: references by slug survive the move to `archive/`.
</impact>
<impact path="docs/project/issues/18-about-outbound-click-tracking.md" element="Proposed solution (line 14) and Related (line 30)">
What changes: none required. The runbook names its `/api/analytics/outbound-click` beacon endpoint as the upgrade path. Note two problems in this issue:
- Line 14 references `client/frontend/about.html`, which does not exist. The page is `client/frontend/dev-pages/about.html` or `about.template.html`.
- Line 20 says the owning service of that endpoint is undecided.

The runbook should therefore say "issue 18's endpoint" without asserting a route or service. An optional comment on issue 18 could record that issue 21 expects a pageview beacon to ride on it.

What depends on it: the runbook's upgrade-path caveat.

Regression risk: if the runbook names a concrete route that issue 18 later changes, the runbook goes stale.
</impact>
<impact path="docs/project/roadmap.md" element="'Implementation order' logging line (line 157)">
What changes: optional, on delivery. Line 158 marks delivered items ("`22`, `23` and `26` are delivered"), so line 157 could similarly say that `19`, `20` and `21` are delivered.

What depends on it: nothing.

Regression risk: none.
</impact>
<impact path="docs/project/plans/22-21-static-page-visit-logs.md" element="build working file">
What changes: the workflow records this impact inventory, the checkpoints and the outcomes here. On delivery it moves to `docs/project/plans/archive/` (`issue-tracker.md:29`).

What depends on it: the `.record.md` sibling.

Regression risk: none.
</impact>
<impact path=".un/skills/devsecops/config.json" element="`working` (`tests/tmp`), `active` (`tests/active`), `test_groups` map">
What changes: the plan places the nginx test in `tests/active`, but under this config a build writes its checkpoints to `working` = `tests/tmp`, and harvest later moves them into `active`. If the test lands in `active`, `test_groups` needs an entry for it mapping to `DEPLOYMENT.md`, plus `client/frontend/vite.config.ts` if the vite-parity check is added. Otherwise its group is not re-run when the doc changes. No existing group maps `DEPLOYMENT.md`; I grepped `config.json` for it.

What depends on it: `validate_tests.py` group digests.

Regression risk: a missing map entry means edits to the §6 block do not trigger the test.
</impact>
<impact path="tests/active" element="new nginx-config test (planned; e.g. tests/active/test_nginx_about_pages_log.py), or its checkpoint in tests/tmp">
What changes: a new test.
1. It extracts the site block from `DEPLOYMENT.md`. There are two ```` ```nginx ```` fences: the site block at line 415 and the upstream snippet at line 488. It must select the one following `/etc/nginx/sites-available/peertube-browser`, or the one containing `server {` and `log_format`, not just the first fence.
2. It substitutes `root`, the three log paths and `listen`, wraps the result in `events {}` and `http {}` with temp `pid`, `error_log` and `*_temp_path`, and runs `nginx -t -p <tmp> -c <conf> -e <tmp>/error.log`. `-e` needs nginx 1.19.5 or later; without it, the non-root run alerts on `/var/log/nginx/error.log`.
3. It optionally serves the config and asserts:
   - the three 200 responses and the CSP header;
   - exactly one main-log line and one pages line per request, with matching `request_id`;
   - no pages line for `/` and `/api/…`. The upstream at `127.0.0.1:7072` is absent, so `/api/` returns 502, which is fine for the "no pages line" check.

What depends on it: `DEPLOYMENT.md` §6 text.

Regression risk:
- **Skip versus fail.** The existing convention in `tests/active/test_host_normalisation.py:65-69` asserts that a missing `node` or `git` fails with a hint rather than skipping. The plan skips when `shutil.which("nginx")` is None, which the requirements ask for, so it is a deliberate deviation.
- **Brittle text extraction.** If the substitutions are regex-based, the test is brittle to whitespace edits in the doc.
- **Log flushing.** Log lines are buffered only when `buffer=` is set, which it is not, so the line-count assertions can read the files immediately after the response.
</impact>
<impact path=".gitignore" element="`client/frontend/dev-pages/*` with `!about.template.html` (lines 29-30)">
What changes: nothing.

What depends on it: it confirms that the override is untracked, so the tree never contains `dev-pages/about.html`, and that CI and test hosts always build from the template.

Regression risk: none.
</impact>
<impact path="docs/project/adr/0002-trusted-proxy-client-address.md" element="client address resolution decision">
What changes: none. The runbook's proxy caveat refers to this behaviour.

What depends on it: the runbook's IP correlation assumes that the Client's resolved `ip` equals nginx's `$remote_addr`. That holds only when nginx is the first hop, as described above.

Regression risk: none to the ADR. The docs should link it from the caveat rather than restate it. No new ADR is strictly required. The choice of an nginx pages log over a beacon is recorded in the plan and in issue 21, though an ADR could be written if the operator wants the "log via nginx, beacon deferred to 18" decision durable.
</impact>


### docs_checklist

<doc path="DEPLOYMENT.md">
- **§6 site block.** Add the `log_format peertube_browser_pages` line under line 416, with `x_request_id` quoted. Add the `location = /about.html` body (`set`, `try_files` with override then template then `=404`, and two `access_log` lines) and the `location = /about` and `location = /about/` lines with `rewrite ^ /about.html last;`.
- **§6 prose (around line 463).** Explain:
  - why both `access_log` lines are needed;
  - why it is `last` and not `break`, `redirect` or `301`;
  - that no `add_header` keeps the inherited CSP;
  - that `$static_page` is how another page is added;
  - that direct `/dev-pages/…` hits are not in the pages log;
  - that `try_files` prefers the override, as vite does;
  - logrotate (the Debian/Ubuntu package rule covers `*.log`, and the postrotate reopens it);
  - that existing hosts must merge the new lines into their site file without overwriting certbot's TLS lines, then run `nginx -t` and reload.
- **§6 Verify.** Add `curl -I http://localhost/about` (200, CSP header), a `tail` of the pages log, and a note that the check itself writes a line.
- **§3 (lines 299-303).** About is built under `dev-pages/` and reached at `/about`, `/about/` and `/about.html` through the §6 mapping.
- **Triage: new `### Follow an About visit` after "Follow one request".** Steps: an anchored `grep '^page=about '`, the main-log `request_id` grep, the `date -u -d @<msec>` conversion with the window running forward from `ts`, the jq filter on `request.start` plus `context.ip` plus `ts` range, the bounded `LOG_FORMAT=text` variant, and the handoff to "Follow one request". Four caveats:
  - no shared id;
  - the IP is resolved through `TRUSTED_PROXIES`, and with a CDN or load balancer in front of nginx `$remote_addr` is the proxy, so matching fails;
  - formats and time zones differ;
  - bots are filtered only by user-agent, and the upgrade path is a beacon on issue 18's endpoint.
- **Triage "What each log is for".** Add a pages-log bullet.
- **Optional.** A Triage table row for About returning 404, a pointer at line 116, and `/about` in the §7 Verify list.
</doc>
<doc path="client/frontend/README.md">
"Local About Overrides": one line saying that production nginx serves whichever of `dev-pages/about.html` or `dev-pages/about.template.html` was built at `/about`, `/about/` and `/about.html` (`DEPLOYMENT.md` §6). Optionally note that the override is served under the server CSP (`script-src 'self'`, no inline styles).
</doc>
<doc path="docs/project/issues/21-static-page-visit-logs.md">
At completion: `Status: enhancement, complete`, a delivery comment naming the `DEPLOYMENT.md` changes and the plan file, and stating that request-id correlation with app traces is replaced by IP plus time window and the beacon is deferred to issue 18. Then move to `docs/project/issues/archive/`.
</doc>
<doc path="docs/project/roadmap.md">
Optional: line 157 marks `19`, `20` and `21` as delivered, as line 158 does for its items.
</doc>
<doc path="docs/project/issues/18-about-outbound-click-tracking.md">
Optional comment: issue 21's runbook names a pageview beacon on this issue's endpoint as its upgrade path. The page path at line 14 (`client/frontend/about.html`) is actually `client/frontend/dev-pages/about*.html`.
</doc>


### highest_risk

DEPLOYMENT.md §6 "re-apply the site file" instruction on existing hosts: `certbot --nginx` (§6 TLS, line 532) edits `/etc/nginx/sites-available/peertube-browser` in place, so an operator who pastes the new block over it loses TLS on reload. The note must say to merge the new lines, not replace the file.
DEPLOYMENT.md §6 `log_format peertube_browser_pages`, unquoted `x_request_id=$http_x_request_id` and the plain `ip=$remote_addr`: nginx's default escaping does not escape spaces, so a client-supplied `X-Request-ID` can forge `status=` or `method=` tokens that the runbook's greps match. With a CDN or load balancer in front of nginx (which line 467 allows), `$remote_addr` is the proxy for every visitor, so IP correlation with the Client's `context.ip` fails silently.
DEPLOYMENT.md §6 About location's two `access_log` lines and `rewrite … last`: dropping the main-log line silently removes About from `peertube-browser.access.log`, and changing `last` to `break` sends the aliases to a 404 with no pages line. Nothing but prose and the planned test guards these, and the block also hand-copies `client/frontend/vite.config.ts`'s URL set and file order with no mechanical tie between them.

## 2026-10-02 - Step 4 - Reassess the implementation plan (pass 1)

Pass 1. New impacts: YES.

The plan holds. I checked the inventory against the tree: `DEPLOYMENT.md` §2/§3/§6, `client/frontend/vite.config.ts`, `client/backend/server.py` (`_format_ts`, `_render_text`, `ClientLogFormatter.format`, `resolve_client_address`, `_run_request`), `.un/skills/devsecops/config.json`, `.gitignore` and `tests/active/test_host_normalisation.py`. Every path and line reference matches what the files contain. I found one problem the inventory missed. Its fix for log-line forgery (quote `x_request_id`) is not enough. nginx's default `log_format` escaping leaves the space alone, so a `User-Agent` such as `x status=200 method=GET` already puts ` status=200 ` inside the quoted `ua` field. Any substring `grep` on a `key=value` token can be fooled, whatever is quoted. Only filtering on field position (awk `$N`), with every client-controlled field after the fields being filtered, is robust. Nothing conflicts with the settled requirements or plan.
<question id="1">
Yes. The exact-match locations plus `rewrite ^ /about.html last;` keep one request, one `$request_id` and one log phase per visit. `try_files` follows vite's order (override, then template) and URL set (`vite.config.ts:16-22`). No `add_header` means the server CSP at `DEPLOYMENT.md:426` is inherited, and `always` covers the 404 too. The two `access_log` lines in the location give one line in each log. The runbook's jq filter is valid against the Client's real keys: `event`, `context.ip` and a fixed-width UTC `ts` from `_format_ts`. The text-mode layout is `ts LEVEL event message…` with the two-word message "request started", so `ip=` is field 6. One part needs fixing to work as intended: the runbook's filters must be positional, not `grep ' status=200 '` (see new impacts).
</question>
<question id="2">
- About nav links (`/about.html` on every page) stop returning 404 in prod.
- Every About request (GET, HEAD, 304, 404, bots, and the operator's own `curl -I`) writes one line to the main log and one to the new pages log.
- The hand-copied nginx block now has to stay in step with `vite.config.ts`.
- The runbook now depends on the pages log's field order and on the Client log schema.
- On TLS hosts, re-applying §6 by pasting the whole block would wipe certbot's edits. The inventory already carries this.
- Correlation is probabilistic, and it fails completely behind a CDN or load balancer, where `$remote_addr` is the proxy's address. The inventory already carries this.
</question>
<question id="3">
- Existing hosts have to merge the `log_format` line and the three locations into their live site file (not replace it), then run `nginx -t` and reload.
- The About location must keep both `access_log` lines, `last` (not `break`), and no `add_header`.
- The "Follow one request" heading must not be renamed: five pointers use it.
- Deploys must keep using `rsync --delete`, so a stale override cannot shadow the template.
- If the test goes into `tests/active`, `config.json` `test_groups` needs an entry mapping it to `DEPLOYMENT.md`. No group maps that file today.
- The runbook's filters must be positional, and the free-text fields must come last in the format (see new impacts).
</question>
<question id="4">
- `/about`, `/about/` and `/about.html` now answer 200 in prod with the built About page. Today they answer 404.
- About requests are now logged under an explicit location. The main-log line is unchanged in format and content.
- Nothing changes for `/`, `/api/`, `/recommendations`, `/videos/similar` or `/client/`, or for any app or frontend code.
- Direct requests to `/dev-pages/about*.html` keep today's behaviour (served by `location /`) and write no pages line.
- The issue asked for correlation with app traces by request id. That is replaced by IP plus a time window, a deviation the plan already records.
</question>

New impacts:
DEPLOYMENT.md (§6 `peertube_browser_pages` field order, and the runbook filters in "Follow an About visit"): quoting `x_request_id` does not stop forged tokens. nginx's default escaping leaves spaces alone, so a quoted `ua` (or `x_request_id`) can contain ` status=200 method=GET page=about `. Any substring `grep` on a `key=` token can be spoofed by any client. The only robust filters are positional awk comparisons (`$1=="page=about"`, `$5=="method=GET"`, and so on) over fields that come before every client-controlled field. The plan's order already puts `x_request_id` and `ua` last, and that order must be kept as a contract. The runbook must use awk positions, not `grep ' status=200 '`. The inventory's "quote it" fix should be read as "quote it and filter by position".
DEPLOYMENT.md (§6 pages format, `uri="$request_uri"` placed before `status`/`rt`/`request_id`): nginx releases before 1.21.1 accept a raw space in the request target (Ubuntu 22.04 ships 1.18; that version is from my knowledge, not the tree). A `$request_uri` containing a space would shift every positional field after `uri`. Put `uri` after `status`, `rt` and `request_id` (just before `x_request_id` and `ua`), or the positional filters on those fields break on older nginx.
DEPLOYMENT.md (runbook text-mode variant, `client/backend/server.py:150-163` `_render_text`): Client text lines put `ip=` at field 6, and `url=` and `user_agent=` (unquoted, may contain spaces) come after it. A bounded `grep " ip=$ip "` can still match an `ip=` token forged inside a later `user_agent` value. The robust form is awk `$3=="request.start" && $6=="ip=" ip`. That depends on the context order `ip, method, url, user_agent` in `_run_request` (line 346), which no test pins.

Inventory entries that did not hold up:
none

Conflicts: none

Recommendations: 1. Write the runbook filters as positional awk on the pages log (`awk '$1=="page=about" && $5=="method=GET"'`, and similar), not substring greps. Fix the field order so that every field a client cannot control comes before every field it can: `page ts time ip method status rt request_id uri x_request_id ua`. Quote `x_request_id` as the inventory says. Cost: one line of format reordering, a slightly longer awk command in the runbook, and the planned test must assert the order. In exchange the filters cannot be spoofed by request headers.
2. Use the anchored awk form for the text-mode Client variant too (`$3=="request.start" && $6=="ip=" ip`). Cost: nothing beyond the doc text. It does make field 6 a documented dependency on `_run_request`'s context order.
3. In the §6 re-apply note, say "merge the `log_format` line and the three locations into the existing file; do not paste over it on a certbot-managed host". Cost: one sentence. It prevents losing TLS on existing hosts, which is the highest-severity item in the inventory.
4. State outright in the proxy caveat that IP correlation fails when anything sits in front of nginx. Point to `real_ip`/`set_real_ip_from` as the remedy rather than adding an `xff` field. Cost: one sentence, no extra log field.
5. If the nginx test goes into `tests/active`, add a `test_groups` entry mapping it to `DEPLOYMENT.md` and `client/frontend/vite.config.ts`, and have it assert that vite's `rewriteToAbout` set equals the three exact locations. Have it build the synthetic Client record with `ClientLogFormatter`, not hard-coded JSON. Cost: one config entry and about 15 extra test lines. In exchange, drift in either the vite URL set or the Client log schema fails the test instead of silently breaking the runbook.
6. Optional, low value: the Triage-table 404 row, the line 116 pointer, the §7 `/about` entry, the `client/frontend/README.md` CSP note for overrides, and the roadmap line. Each is one line of docs. Skipping them costs nothing functional.
7. Ask the operator about the untracked override `dev-pages/about.html`: `about.css` implies tabs. If it uses inline script or `style=` attributes, the server CSP will break it on its first prod serve. Cost: one question. Skipping it risks a broken About page in prod that the template-only test cannot catch.

## 2026-10-02 - Step 3 - Identify every file, function and doc affected

Recorded ungated, at the operator direction.

### impacts


<impact path="DEPLOYMENT.md" element="§6 nginx (production): the fenced `/etc/nginx/sites-available/peertube-browser` block (lines 414-459)">
**What changes.** A second `log_format peertube_browser_pages '…';` goes directly under the existing `log_format peertube_browser` on line 416, outside `server {}`. It uses the same single-quoted one-line style and `key=value` tokens: `page=$static_page ts=$msec time=$time_iso8601 ip=$remote_addr method=$request_method uri="$request_uri" status=$status rt=$request_time request_id=$request_id x_request_id=$http_x_request_id ua="$http_user_agent"`. Three exact locations go inside `server {}`. Best placement is after `location /` (line 428-430) and before the proxied locations, so the four proxy blocks stay contiguous. `location = /about.html` holds `set $static_page about;`, `try_files /dev-pages/about.html /dev-pages/about.template.html =404;` and both `access_log` lines (`/var/log/nginx/peertube-browser.access.log peertube_browser;` and `/var/log/nginx/peertube-browser.pages.access.log peertube_browser_pages;`), and it has no `add_header`. `location = /about` and `location = /about/` each hold only `rewrite ^ /about.html last;`.

**Facts verified in the file.** The server level has `root /var/www/peertube-browser`, `index index.html`, a server-level `access_log` (line 424) and `add_header Content-Security-Policy … always` (line 426). `location /` is `try_files $uri $uri/ =404`. Nothing in the block names `/about` today, so `/about.html`, which every page's nav links to, is a 404 in prod: the build emits only `dist/dev-pages/about*.html` (confirmed: `client/frontend/dist/dev-pages/about.template.html` exists and there is no `dist/about.html`).

**What depends on it.** Operators copy this block by hand. `scripts/deploy-bluegreen.sh` and `engine/install-engine-service.sh` both gate on `nginx -t` for the whole config, so this site file's validity affects them. "Follow one request" greps the main log by `request_id=`, which still works because About's location re-lists the main log. The planned `tests/active` test extracts this fenced block. It must find the first ```` ```nginx ```` fence after the `sites-available/peertube-browser` heading line: §6 has a second ```` ```nginx ```` fence at line 488 (the upstream snippet), so "first nginx fence in the file" is correct today but fragile. It must also substitute all three log paths, `root` and `listen 80`.

**Regression risk: medium-high.** (1) `$static_page` is used in a `log_format` that appears before any `set`. nginx resolves variable indexes after parsing, so this should pass `nginx -t`. The automated test must still prove it, because "unknown variable" would block every reload, deploys included. (2) A location-level `access_log` replaces the inherited one, so omitting the first line silently drops About from the main log. (3) Adding any `add_header` to the About location would drop the CSP. The About template has no `<meta>` CSP of its own (verified), so the header is its only CSP. (4) Changing `last` to `break` or `redirect` breaks the one-line-per-visit property. (5) The exact-match locations must not shadow anything: no other route starts with `/about`, verified by grepping the frontend and the block.
</impact>
<impact path="DEPLOYMENT.md" element="§6 prose after the block (lines 461-467: the CSP paragraph and the `X-Request-ID`/`log_format` paragraph)">
**What changes.** New prose next to the existing note on line 463 ("The line is repeated in every location because a location that sets any `proxy_set_header` inherits none…"). It says: why both `access_log` lines are repeated (location-level `access_log` replaces the server's); that About inherits the CSP only because its location declares no `add_header`; the URL mapping (`/about`, `/about/` rewrite internally with `last` to `/about.html`, which serves `dev-pages/about.html`, else `dev-pages/about.template.html`, else 404, in vite's order); do not change `last`; the new file `/var/log/nginx/peertube-browser.pages.access.log`, which the Debian/Ubuntu `/var/log/nginx/*.log` logrotate rule and its postrotate reopen cover; the field list; that `x_request_id` is `-` when absent; the limitation that direct hits on `/dev-pages/about*.html` go through `location /` and leave no pages line; and that existing hosts get About only after re-applying the site file and reloading.

**What depends on it.** The line-463 sentence "`log_format` stays outside `server {}`…" now applies to two formats; reword it to the plural. The CSP paragraph (line 461) says the browser enforces the header together with each page's `<meta>` CSP. About has no meta CSP, so the header alone applies there; worth a clause.

**Regression risk: low.** Prose only. The risk is inaccuracy (logrotate claim and `$msec` semantics) that later steps must check.
</impact>
<impact path="DEPLOYMENT.md" element="§6 &quot;Verify&quot; block (lines 475-481)">
**What changes.** Add `curl -I http://localhost/about` (expect 200, `Content-Security-Policy` present) and, optionally, `/about/` and `/about.html`. Add `sudo tail -n 3 /var/log/nginx/peertube-browser.pages.access.log` (expect a `page=about` line with the same `request_id` as the main log's last About line). A 404 hint can sit beside the existing "A 404 on `/`…" sentence: a 404 on `/about` with a passing `nginx -t` means neither `dev-pages/about*.html` is in the document root (build not re-synced).

**What depends on it.** Operators only.

**Regression risk: low.** It uses the same comment style as lines 477-478.
</impact>
<impact path="DEPLOYMENT.md" element="§6 &quot;Engine listener on 127.0.0.1:7079&quot; paragraph (line 485)">
**What changes.** Nothing. The sentence "leave the public site file above as it is, since nothing here changes it" stays true: the listener installer never writes the public site file, and `engine/install-engine-service.sh:259` uses the default log format, so there is no name clash with `peertube_browser_pages`.

**What depends on it.** It is listed so the next step does not edit it by mistake.

**Regression risk: none.**
</impact>
<impact path="DEPLOYMENT.md" element="§3 &quot;Build the client&quot;: page list and `try_files` paragraph (lines 299-303)">
**What changes.** Lines 299-303 say nginx serves `dist/` through `try_files` and list `about` among the pages as if it were served like the others. Amend this: About is built under `dev-pages/` (`dev-pages/about.html` when the untracked local file exists, else `dev-pages/about.template.html`) and is reached at `/about`, `/about/` and `/about.html` only through the §6 mapping, not as `/about.html` in `dist/`.

**What depends on it.** `scripts/sync.sh` and the §6 `rsync --delete` (lines 406-412), which together make the served root hold exactly the last build's About file.

**Regression risk: low.**
</impact>
<impact path="DEPLOYMENT.md" element="§2 Triage: new subsection &quot;Follow an About visit&quot; after &quot;Follow one request&quot; (insert after line 249, before &quot;Centralized installer&quot; at line 251)">
**What changes.** A new `### Follow an About visit` heading after the "Follow one request" caveats (line 249). It sits inside §2's "Triage" area, which runs on into "Centralized installer (source of truth):" at line 251 with no heading. Placing it before line 251 keeps the installer text attached to the end of the section as it is today. Steps:
1. `sudo grep 'page=about' /var/log/nginx/peertube-browser.pages.access.log`, filtered by `' status=200 '`, `' method=GET '` or awk.
2. `sudo grep "request_id=$id" /var/log/nginx/peertube-browser.access.log`, the same command as line 236.
3. Convert `ts=` with `date -u -d @<msec> +%Y-%m-%dT%H:%M:%S.%3NZ`, compute the window end (+300 s), then run `journalctl -u peertube-client.service -o cat | jq -cR --arg ip … --arg from … --arg to … 'fromjson? | select(.event == "request.start" and .context.ip == $ip and .ts >= $from and .ts <= $to)'`. Add a `LOG_FORMAT=text` variant.
4. Hand off to "Follow one request".

Add the four caveats.

**Verified against the code it relies on.** `client/backend/server.py` `_run_request` (lines 339-357) emits event `request.start` with context `ip`, `method`, `url`, `user_agent`. The JSON payload nests these under `"context"` (lines 187-189), so `.context.ip` and `.event` are correct. `ts` is `_format_ts` (lines 136-140), always `YYYY-MM-DDTHH:MM:SS.mmmZ` UTC, fixed width, so string comparison orders correctly. Text mode (`_render_text`, lines 150-163) is `ts LEVEL event message ip=… method=…`, so `ts` is field 1 and the message "request started" contains a space. `resolve_client_address` (lines 276-292) returns an accepted XFF hop in canonical `ipaddress` form, while nginx writes `$remote_addr` as it sees it. These match for IPv4 and usually for IPv6, but they can differ, for example IPv4-mapped `::ffff:` forms.

**Regression risk: medium (correctness of commands).** (a) A text-variant `grep "ip=$ip"` prefix-matches (`ip=10.0.0.1` matches `ip=10.0.0.12`). It must anchor on a trailing space (`"ip=$ip "`), or on end of line when `ip` is the last token: `user_agent` is omitted when empty, but `method` and `url` always follow `ip`, so a trailing space is safe. (b) Window-end arithmetic on a fractional `$msec` needs care (`date -d @$(( ${ts%.*} + 300 )).${ts#*.}` or awk). A bare `$((…))` on the float fails. (c) The runbook assumes the prod unit name `peertube-client.service`; the dev contour is `peertube-client-dev`. (d) No shared id, so correlation is probabilistic, and this must be stated.
</impact>
<impact path="DEPLOYMENT.md" element="§2 Triage &quot;What each log is for&quot; list (lines 242-244) and caveats (246-249)">
**What changes.** A new bullet: the pages log is the About visit view, with one line per About request, `page=about`, epoch `ts`, and the same `request_id` as the visit's main-log line, but no app records. The existing caveat "The 7079 listener's own access log does not carry the id" stays.

**What depends on it.** The cross-reference from §2's `LOG_FORMAT` paragraph (line 116), which points at "Follow one request".

**Regression risk: low.**
</impact>
<impact path="DEPLOYMENT.md" element="§2 Triage table (lines 197-229): candidate new row; and the `nginx_test` rollback row (line 225)">
**What changes.** Optional, recommended: one row for "`/about` answers 404". Causes: the site file has not been re-applied since this change, or the document root holds neither `dev-pages/about*.html` because the build was not re-synced. Action: re-apply §6 and `nginx -t && reload`, or run `scripts/sync.sh`. Row 225 already says a `rollback step=nginx_test` is "often an unrelated broken config". A half-applied site file (for example the new `access_log … peertube_browser_pages` copied without its `log_format`) is exactly such a cause, so no edit is strictly needed there; it is listed for the cross-impact.

**What depends on it.** Operators.

**Regression risk: low.** It is doc only. The underlying operational risk is listed under `scripts/deploy-bluegreen.sh`.
</impact>
<impact path="DEPLOYMENT.md" element="§2 `LOG_FORMAT` paragraph (line 116) and §7 &quot;Verify&quot; page list (lines 561-565)">
**What changes.** Optional. Line 116 ends with "To read every line of one request… see 'Follow one request'"; a half-sentence pointer to "Follow an About visit" could follow, since that runbook depends on `json` for its jq recipe. §7 lists pages to open (`/`, `/videos.html`), and `/about` could be added. The plan does not name either, so if both are skipped nothing is wrong.

**What depends on it.** Nothing.

**Regression risk: none.**
</impact>
<impact path="client/frontend/vite.config.ts" element="`devAboutPath`/`aboutTemplatePath`/`aboutSourcePath` (lines 13-18), `rewriteToAbout` (line 22), `build.rollupOptions.input.about` (lines 91-93)">
**What changes.** Nothing; the plan keeps the build layout. This is the contract the nginx `try_files` mirrors: an `existsSync(dev-pages/about.html)` override, otherwise the template, emitted at `dist/dev-pages/<same name>`. The rewrite set `/about`, `/about/`, `/about.html` (line 22) is exactly the three nginx exact locations. Note that `/videos`, `/search` (lines 20-21) are also vite-only rewrites with no prod nginx mapping. That is out of scope, but the same class of dev/prod gap.

**What depends on it.** The nginx `try_files` order and the three URLs in `DEPLOYMENT.md` §6.

**Regression risk: low now, drift later.** If someone renames `dev-pages/` or moves About to a top-level `about.html`, the documented nginx `try_files` silently 404s. A comment here pointing at `DEPLOYMENT.md` §6 would guard it, but the plan forbids frontend changes, so the doc prose should name `vite.config.ts` as the source of the order instead.
</impact>
<impact path="client/frontend/dev-pages/about.template.html" element="whole file (tracked template; built to dist/dev-pages/about.template.html)">
**What changes.** Nothing. Verified: every URL is root-absolute (`/favicon.png`, `/src/videos.css` → `/assets/videos-*.css` in `dist/dev-pages/about.template.html`, nav `/channels.html`, `/`, `/likes.html`, `/about.html`). There is no `<script>` and no `<meta http-equiv="Content-Security-Policy">`, unlike the six top-level pages, which all carry one. Serving it at `/about/` therefore breaks no relative URL, and the nginx header is its only CSP.

**What depends on it.** The `try_files` fallback in the new About location.

**Regression risk: low for the template.** The real exposure is the untracked operator override `dev-pages/about.html` (`.gitignore` lines 29-30 ignore everything in `dev-pages/` except the template). Its content is unknown. If it uses relative links (e.g. `href="about.css"` or `img/…`), they resolve under `/about/` differently than under `/about.html`. If it loads third-party scripts, the CSP's `script-src 'self'` blocks them, as it would anywhere. The docs should say the override must use root-absolute URLs. I could not inspect it because no such file is in the worktree.
</impact>
<impact path="client/frontend/index.html" element="nav link `href=&quot;/about.html&quot;` (line 26)">
**What changes.** Nothing in the file. Behaviour changes: the link goes from a prod 404 to a 200 served by the About location, and every click now writes a pages-log line.

**What depends on it.** Visitors navigating to About.

**Regression risk: low.** This is the intended fix.
</impact>
<impact path="client/frontend/videos.html" element="nav link `href=&quot;/about.html&quot;` (line 26)">
Same as `index.html`: unchanged file, and the link now resolves to 200 in prod through the About location. Risk low.
</impact>
<impact path="client/frontend/search.html" element="nav link `href=&quot;/about.html&quot;` (line 26)">
Same as `index.html`: unchanged file, and the link now resolves to 200 in prod. Risk low.
</impact>
<impact path="client/frontend/likes.html" element="nav link `href=&quot;/about.html&quot;` (line 26)">
Same as `index.html`: unchanged file, and the link now resolves to 200 in prod. Risk low.
</impact>
<impact path="client/frontend/video-page.html" element="nav link `href=&quot;/about.html&quot;` (line 24)">
Same as `index.html`: unchanged file, and the link now resolves to 200 in prod. Risk low.
</impact>
<impact path="client/frontend/channels.html" element="nav link `href=&quot;/about.html&quot;` (line 26)">
Same as `index.html`: unchanged file, and the link now resolves to 200 in prod. Risk low.
</impact>
<impact path="client/frontend/dist/dev-pages/about.template.html" element="committed build output">
**What changes.** Nothing. The committed `dist/` lags the source (DEPLOYMENT.md line 412). It holds only the template, so a host that copied `dist/` unbuilt serves the template at `/about`, which is correct behaviour for the fallback.

**What depends on it.** The planned nginx test may use a temp root with synthetic `dev-pages/about*.html` files rather than this directory. It should not rely on `dist/`, which can be stale.

**Regression risk: none.**
</impact>
<impact path="client/frontend/README.md" element="&quot;Local About Overrides&quot; section (lines 36-39)">
**What changes.** Add one line: in prod, nginx serves whichever of the two files was built (`dev-pages/about.html` first, then the template) at `/about`, `/about/` and `/about.html` (see `DEPLOYMENT.md` §6). Optionally add that an override should use root-absolute URLs.

**What depends on it.** Developers writing the override.

**Regression risk: none.** Match the existing bullet style.
</impact>
<impact path="scripts/sync.sh" element="build + `rsync -a --delete` + chown (lines 19-23)">
**What changes.** Nothing. This is what makes the served root hold exactly the last build's About file, so the "stale override wins" gotcha only arises if someone copies files without `--delete`.

**What depends on it.** The About location's `try_files` order.

**Regression risk: low.**
</impact>
<impact path="scripts/deploy-bluegreen.sh" element="`nginx -t` / reload in the switch (lines 317-318) and rollback (lines 148-149)">
**What changes.** Nothing in code. Cross-impact: the deploy validates and reloads the entire nginx config, the public site file included. A site file broken while applying this change (a missing `log_format peertube_browser_pages`, a typo in the location, or the format placed inside `server {}`) makes every blue/green deploy roll back at `step=nginx_test`. If the deploy's restore path also fails `nginx -t`, it hits `rollback_failed … restore_nginx_test`.

**What depends on it.** Every prod Engine deploy.

**Regression risk: medium (operational).** The docs should tell operators to run `sudo nginx -t` right after editing the site file (the existing line 472 does), and the automated `nginx -t` test on the documented block mitigates it.
</impact>
<impact path="engine/install-engine-service.sh" element="listener write and `nginx -t` gate (listener `access_log` at line 259)">
**What changes.** Nothing. The listener uses `access_log …peertube-engine-internal.access.log` with the default format, so there is no `log_format` name collision with `peertube_browser_pages`. Like the deploy, the installer refuses to reload when `nginx -t` fails, so a broken public site file also blocks a prod Engine install, which then removes the listener file it created.

**What depends on it.** Prod installs.

**Regression risk: low-medium.** This is the same cross-impact as the deploy script.
</impact>
<impact path="client/backend/server.py" element="`_format_ts` (136-140), `_render_text` (150-163), `ClientLogFormatter.format` (174-195), `resolve_client_address` (276-292), `_run_request` (339-357)">
**What changes.** Nothing; the out-of-scope list forbids Client changes. The runbook's jq and text recipes depend on these exact shapes: event name `request.start`, `context.ip`, the fixed-width UTC `ts`, text field order, and canonicalised XFF hops.

**What depends on it.** "Follow an About visit" step 3 and the runbook test with a synthetic Client record.

**Regression risk: low now.** A future rename of `request.start` or `context.ip`, or of the `ts` format, silently breaks the runbook. There is a rat-tail comment at line 122 for the Engine/Client mirror, but nothing ties these shapes to DEPLOYMENT.md. The runbook test should build its synthetic record through `ClientLogFormatter` rather than a hand-typed JSON string, so it fails if the shape changes.
</impact>
<impact path="tests/active/test_nginx_about_site.py" element="new test module (name to be decided)">
**What changes.** New file. It extracts the §6 site block from `DEPLOYMENT.md`: anchor on the `sites-available/peertube-browser` line, then take the next ```` ```nginx ```` fence, not the line-488 upstream fence. It substitutes `root`, all three log paths (server-level plus the two in the About location) and `listen 80`. It wraps the block in a minimal `events {}` plus `http {}` config with temp `pid`, `error_log` and `*_temp_path` values, runs `nginx -t -p <tmp> -c <conf>`, and, where possible, starts nginx on a free port to check: the three 200s, `HEAD`, CSP on the 200 and on the 404 case (no dev-pages files), one line per log per request with matching `request_id`, the uri carrying the query as requested (`/about?x=1`), `x_request_id=-` when absent and echoed when sent, `"` escaped as `\x22`, and no pages line for `/`, `/videos.html` or `/api/…`. Skip when `shutil.which("nginx")` is None. A runbook check uses a synthetic pages line and a Client record.

**What depends on it.** Validation items in the plan's Requirements.

**Regression risk: medium (test reliability).** (1) Other `tests/active` modules (`test_install_engine_service.py`, `test_deploy_bluegreen.py`, …) put a stub `nginx` on a PATH for their subprocesses. If any of them mutates `os.environ["PATH"]` in-process, `shutil.which("nginx")` could find a stub. They appear to pass env to subprocesses, but this needs a check. (2) `/api/` proxy targets `127.0.0.1:7072`, which is down in tests, so expect 502, still with no pages line. The substitution could point it at a free port instead. (3) Running nginx needs a free port helper; `tests/active/conftest.py:96 _free_port` exists and is reusable. (4) I could not confirm whether an `nginx` binary exists on this host (no shell). If it does not, the whole test skips and the config is unvalidated here.
</impact>
<impact path="docs/project/issues/21-static-page-visit-logs.md" element="Status line and `## Comments`">
**What changes.** At completion, per `docs/project/issue-tracker.md` lines 20-21: set `Status: enhancement, complete`, append a delivery comment naming `docs/project/plans/22-21-static-page-visit-logs.md` and what was delivered, and **move the file to `docs/project/issues/archive/`**. The plan text says only "status at completion"; the move is required by the tracker rules.

**What depends on it.** Slug references in `docs/project/issues/18-about-outbound-click-tracking.md:30` and `docs/project/issues/20-request-lifecycle-logs.md:31`, and in `archive/19-…`, `archive/20-…`. All cite the slug without a path, so the move breaks no link.

**Regression risk: none.** Side note: `docs/project/issues/20-request-lifecycle-logs.md` exists both in `issues/` and `issues/archive/`. That is pre-existing, not this build's to fix.
</impact>
<impact path="docs/project/issues/18-about-outbound-click-tracking.md" element="`## Related` / `## Comments`">
**What changes.** Optional. Note in a comment that issue 21's runbook names 18's beacon endpoint as the upgrade path for pageview counting, so 18's endpoint design may want a page-view event type. There is no duplication: 21 adds no endpoint.

**What depends on it.** Issue 18's future design.

**Regression risk: none.**
</impact>
<impact path="docs/project/issues/plan.md" element="Wave 5 lane 5c row (line 98) and P5 tier row (line 42)">
**What changes.** Mark 21 delivered in lane 5c's notes, as other lanes do ("Delivered."). Its "Main files" column says "nginx docs, the About template, one Client endpoint". For 21 alone that is only the nginx docs (no template, no endpoint, which belong to 18). Line 42 could note 21 delivered.

**What depends on it.** Planning only.

**Regression risk: none.**
</impact>
<impact path="docs/project/roadmap.md" element="`## Delivered` list (lines 7-25) and Implementation order line 157">
**What changes.** Optional, following the convention that delivered issues get a Delivered bullet (e.g. line 25 for issue 26): add "Issue `21`, About visit log" with a pointer to the plan. Line 157 (`19` -> `20` -> `21`) needs no change. Note that 19 and 20 have no Delivered bullets either, so the convention is not applied consistently; uncertain whether one is expected.

**What depends on it.** Nothing.

**Regression risk: none.**
</impact>
<impact path="CONTEXT.md" element="glossary; &quot;Request id&quot; entry (line 10)">
**What changes.** Probably nothing. The Request id entry stays accurate: About requests get a `$request_id` too, but nothing propagates it. `docs/project/domain.md` says a concept missing from the glossary signals a gap. The runbook introduces "pages log" / "About visit". I am unsure whether that rises to a glossary term. If added, it should be one line: an About visit is one request handled by the About location, logged with `page=about` to the pages log, and it shares no request id with app records.

**What depends on it.** Vocabulary in the new runbook.

**Regression risk: none.**
</impact>
<impact path="client/README.md" element="lines 31, 63, 69, 75 (nginx mentions)">
**What changes.** Nothing. Line 75 says byte counts are in the nginx access log, which is still true. None of these state the About URL or list the nginx logs. Checked to confirm the plan's "no other doc" claim.

**Regression risk: none.**
</impact>
<impact path="README.md" element="line 82-86 (nginx/deploy mentions)">
**What changes.** Nothing. It mentions nginx only for the blue/green listener and points at DEPLOYMENT.md. Checked to confirm.

**Regression risk: none.**
</impact>


### docs_checklist


<doc path="DEPLOYMENT.md">
§6 site block: second `log_format peertube_browser_pages` under line 416; `location = /about.html` (set, try_files, two access_log lines, no add_header) and the `= /about` / `= /about/` rewrite aliases. §6 prose after line 463: why both access_log lines, CSP inheritance (About has no meta CSP), the mapping and vite order, keep `last`, the new log file and logrotate coverage, direct `/dev-pages/…` hits are not logged, existing hosts must re-apply and reload. Pluralise the "`log_format` stays outside `server {}`" sentence. §6 Verify: `curl -I http://localhost/about` plus a pages-log tail, and a 404-on-/about hint. §3 lines 299-303: About is built under `dev-pages/` and reached via the §6 mapping. Triage: new "Follow an About visit" subsection after line 249 and before "Centralized installer" at line 251, with the four caveats. "What each log is for" gets a pages-log bullet. Optional: a Triage table row for `/about` 404, a pointer from the §2 `LOG_FORMAT` paragraph, and `/about` in §7's page list.
</doc>
<doc path="client/frontend/README.md">
"Local About Overrides": add that prod nginx serves whichever file was built (override first, then template) at `/about`, `/about/`, `/about.html` (DEPLOYMENT.md §6). Optionally add that an override should use root-absolute URLs.
</doc>
<doc path="docs/project/issues/21-static-page-visit-logs.md">
At completion: `Status: enhancement, complete`, a delivery comment naming the plan, and a move to `docs/project/issues/archive/` per issue-tracker.md.
</doc>
<doc path="docs/project/issues/plan.md">
Lane 5c (line 98): mark 21 delivered and correct its file list for 21 (nginx docs only).
</doc>
<doc path="docs/project/roadmap.md">
Optional Delivered bullet for issue 21. The convention is inconsistent, since 19 and 20 have none.
</doc>
<doc path="docs/project/issues/18-about-outbound-click-tracking.md">
Optional comment: 21's runbook names 18's beacon endpoint as the pageview upgrade path.
</doc>


### highest_risk


DEPLOYMENT.md §6 nginx site block: the only real artefact of the build. The CSP is the About template's only CSP, so a stray `add_header` drops it. A missing re-listed main `access_log` silently removes About from the main log. `last` must stay. `$static_page` is referenced in a `log_format` declared before its `set`, which must be proven by `nginx -t`.
scripts/deploy-bluegreen.sh (and engine/install-engine-service.sh): both gate on `nginx -t` of the whole config, so a half-applied public site file (e.g. the new access_log without its log_format) makes every prod Engine deploy roll back at `step=nginx_test` and blocks prod installs.
DEPLOYMENT.md "Follow an About visit" runbook: commands can be subtly wrong. A text-mode `grep "ip=$ip"` prefix-matches other IPs. Window arithmetic on fractional `$msec` breaks in bash `$((…))`. The recipe depends on Client shapes in client/backend/server.py (`request.start`, `.context.ip`, fixed-width UTC `ts`) that nothing ties to the doc.

## 2026-10-02 - Step 4 - Reassess the implementation plan (pass 2)

Pass 2. New impacts: YES.

The plan holds. I checked every inventory entry against its file: `DEPLOYMENT.md` §2, §3, §6 and §7 (lines 116, 195-251, 297-303, 400-499, 525-533, 561-565), `client/frontend/vite.config.ts`, `dev-pages/about.template.html`, the six top-level pages' nav links, the committed `dist/`, `client/backend/server.py`, `scripts/sync.sh`, `scripts/deploy-bluegreen.sh`, `engine/install-engine-service.sh`, `docs/project/issue-tracker.md`, `docs/project/issues/plan.md`, `docs/project/roadmap.md` and `.un/skills/devsecops/config.json`. Every path, line number and claim matches the files. I found four things the inventory does not carry. (1) `sudo certbot --ninx` in §6 "TLS" (lines 531-532) rewrites the live site file, so the plan's "re-apply §6" would delete TLS on any host that followed the docs. (2) nginx's default log escaping leaves spaces alone, so the client-controlled `ua`, `uri` and `x_request_id` can carry forged ` status=200 ` / ` method=GET ` tokens. The `grep ' status=200 '` filters the plan proposes can be spoofed, and positional awk with client-controlled fields last is the robust form. (3) The same forgery applies to the Client text-mode variant through the unquoted `user_agent`. (4) No `test_groups` entry maps `DEPLOYMENT.md`, so the planned test has no group to run under. These four repeat findings from an earlier step-4 pass recorded in `22-21-static-page-visit-logs.record.md`; they are not in the inventory I was given, so I re-checked each against the tree and report them again. Nothing conflicts with the settled requirements or plan: the plan already allows awk filters and gives the field order only "roughly".
<question id="1">
Yes. Three exact locations sit ahead of `location /`: `= /about` and `= /about/` each `rewrite ^ /about.html last;` into `= /about.html`, so the other routes at `DEPLOYMENT.md:428-457` are untouched. `last` keeps one request, so each visit gets one `$request_id` and one log phase. `try_files /dev-pages/about.html /dev-pages/about.template.html =404` follows the vite order (`vite.config.ts:13-18, 91-93`) and URL set (`vite.config.ts:22`). The About location has no `add_header`, so it inherits the server CSP at line 426, and `always` covers the 404 too. That header is About's only CSP: the template has no meta CSP and no script. The two `access_log` lines give one line in each log. The runbook's jq recipe fits the real Client shapes: `event` and `context` (server.py:176-189), the fixed-width UTC `ts` (136-140), and `request.start` with `ip, method, url[, user_agent]` (346-350). The text layout puts `ip=` at field 6, because the message "request started" is two words. One part does not work as intended yet: the runbook's substring filters can be spoofed (new impacts 2-3). A second part is fragile: on a certbot host, re-applying the block by pasting it over the live file loses TLS (new impact 1).
</question>
<question id="2">
- The About nav link on every page (`index.html:26`, `videos.html:26`, `search.html:26`, `likes.html:26`, `video-page.html:24`, `channels.html:26`) goes from a prod 404 to a 200.
- Every About request writes one line to the main log and one to the new pages log. That covers GET, HEAD, 304, 404, bots, and the operator's own `curl -I`.
- The hand-copied nginx block now has to stay in step with the vite build layout.
- The runbook now depends on the pages-log field order and on the Client log schema in `server.py`.
- The public site file now carries something a deploy or install can trip on: a half-applied edit fails `nginx -t` at `deploy-bluegreen.sh:317` and `install-engine-service.sh:401` (already in the inventory).
- On hosts where certbot ran (§6 TLS), applying the change means a merge, not a paste, and the About locations belong in the 443 server.
- Correlation stays probabilistic, and it fails when anything sits in front of nginx (already in the plan).
</question>
<question id="3">
- Existing hosts must merge the new `log_format` line and the three locations into their live site file (on certbot hosts, into the server block that serves the site), then run `nginx -t` and reload.
- The About location must keep both `access_log` lines, `last`, and no `add_header`.
- Deploys must keep `rsync --delete` (`sync.sh:22`), so a stale override cannot shadow the template.
- The runbook's filters must be positional awk over fields that come before every client-controlled field, and the format must place `uri`, `x_request_id` and `ua` last.
- The new test needs a `test_groups` entry in `.un/skills/devsecops/config.json` that maps it to `DEPLOYMENT.md`, or test selection never picks it.
- At completion, issue 21 moves to `docs/project/issues/archive/` (`issue-tracker.md:21`; already in the inventory).
</question>
<question id="4">
- `/about`, `/about/` and `/about.html` answer 200 in prod with the built About page, where all three were 404.
- About requests now end in an explicit location. Their main-log lines keep the same format and content.
- `/`, `/api/`, `/recommendations`, `/videos/similar`, `/client/`, every app and every frontend file behave as before.
- Direct hits on `/dev-pages/about*.html` still go through `location /` and write no pages line.
- The issue's request-id correlation with app traces becomes IP plus a time window. This deviation is already recorded in the requirements.
</question>

New impacts:
DEPLOYMENT.md (§6 "TLS", lines 525-533: `sudo certbot --nginx`): certbot edits `/etc/nginx/sites-available/peertube-browser` in place. It adds `listen 443 ssl` and certificate lines to the server block, and typically splits port 80 into a redirect server. The plan's "existing hosts re-apply §6 and reload" (Gotchas, Existing deployments) would delete TLS if an operator pastes the documented block over the live file. On such hosts the new locations must also go into the server that serves the site (443), not the port-80 redirect. The re-apply prose must say to merge the `log_format` line and the three locations, not to replace the file. The inventory's §6 prose entry covers only "re-applying the site file and reloading".
DEPLOYMENT.md (§6 `peertube_browser_pages` field order, and step 1 of "Follow an About visit"): nginx's default `log_format` escaping turns `"` into `\x22` but leaves the space alone. A client-controlled value (`ua="$http_user_agent"`, `x_request_id=$http_x_request_id`, and `uri="$request_uri"` on nginx releases before 1.21.1, which accepted a raw space in the request target; that version detail is from nginx's changelog, not the tree) can therefore contain ` status=200 method=GET page=about `. The planned `grep ' status=200 '` / `' method=GET '` filters can be spoofed by any visitor. The robust form is positional awk (`$1=="page=about" && $5=="method=GET" && $6=="status=200"`) over a fixed order where every client-controlled field comes last: `page ts time ip method status rt request_id uri x_request_id ua`. That moves `uri` after `request_id`, which the plan's "roughly in this order" permits. The plan's Gotchas line "the runbook's greps match on key= tokens, not positions" states exactly the weak form.
client/backend/server.py (`_render_text` lines 150-163, `_run_request` context order at line 346): in `LOG_FORMAT=text`, context values are unquoted (DEPLOYMENT.md:116 says so), and `user_agent` follows `ip`. A request whose User-Agent contains ` ip=<victim> ` therefore matches the runbook's text-mode `grep "ip=$ip "` even with the trailing-space anchor the inventory proposes. The robust filter is awk `$3=="request.start" && $6==("ip=" ip)`, which makes field 6 (two-word message "request started", then the first context key `ip`) a documented dependency on the context insertion order at line 346. No test pins that order.
.un/skills/devsecops/config.json (`test_groups`, lines 14-263): no group lists `DEPLOYMENT.md`, `client/frontend/vite.config.ts` or `scripts/sync.sh`, and the baseline ran "1 of 46 test groups" chosen by changed files. Without a new entry, e.g. `"test_nginx_about_site.py": ["DEPLOYMENT.md", "client/frontend/vite.config.ts", "client/backend/server.py"]`, the planned nginx/runbook test is never selected when the block or the runbook changes.

Inventory entries that did not hold up:
none

Conflicts: none

Recommendations: 1. In the §6 re-apply note, say: merge the `log_format` line into the top of the live file and the three locations into the server block that serves the site (the `listen 443 ssl` one on a host where `certbot --nginx` ran); do not paste the block over the file; then run `sudo nginx -t && sudo systemctl reload nginx`. Cost: two sentences of prose. It prevents the worst outcome of applying this change: a host losing TLS.
2. Fix the pages format order as `page ts time ip method status rt request_id uri x_request_id ua`, and write runbook step 1 as positional awk (`sudo awk '$1=="page=about" && $6=="status=200"' …`) rather than substring greps. Have the planned test assert the order and feed a forged User-Agent to prove the filter ignores it. Cost: one reordered format line, a slightly longer runbook command, and about 10 test lines. The field order becomes a documented contract that later edits must keep. Within the settled plan, which already allows awk and gives the order only "roughly".
3. Write the `LOG_FORMAT=text` variant as `awk -v ip="$ip" -v from="$from" -v to="$to" '$3=="request.start" && $6==("ip=" ip) && $1>=from && $1<=to'`. Cost: doc text only. It makes field 6 depend on `_run_request`'s context order; the planned test should produce its synthetic record through `ClientLogFormatter` in text mode as well as JSON, so a reorder fails the test.
4. Add a `test_groups` entry in `.un/skills/devsecops/config.json` that maps the new test to `DEPLOYMENT.md`, `client/frontend/vite.config.ts` and `client/backend/server.py`. Have the test also assert that vite's `rewriteToAbout` set equals the three exact nginx locations. Cost: one config entry and a few test lines. In exchange, drift in the doc block, the vite URL set or the Client log shape fails a selected test instead of silently breaking prod or the runbook.
5. In the planned test, run `nginx -t` with `-e stderr` (nginx 1.19.5 and later) or tolerate the alert about the compiled-in error log. Run as non-root, nginx tries to open that log (`/var/log/nginx/error.log` on Debian builds) before reading the temp config. Cost: one flag. It keeps the test's output clean and keeps the alert from being mistaken for a failure.
6. Optional items from the inventory: the Triage row for a 404 on `/about`, the pointer from the line-116 paragraph, `/about` in §7's page list, the root-absolute-URL note for overrides in `client/frontend/README.md`, the roadmap Delivered bullet and the comment on issue 18. Each costs one line. Skipping them loses no function, but the 404 row is the one an operator would actually reach for after an incomplete re-apply.

## 2026-10-02 - Step 3 - Identify every file, function and doc affected

Recorded ungated, at the operator direction.

### impacts

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

### docs_checklist

<doc path="DEPLOYMENT.md">
- **§6 site block:**
  - Add `log_format peertube_browser_pages` under line 416, with the client-controlled `ua`/`x_request_id` (and ideally `uri`) last.
  - Add `location = /about.html` with `set $static_page about;`, `try_files /dev-pages/about.html /dev-pages/about.template.html =404;`, both `access_log` lines and no `add_header`.
  - Add the `= /about` / `= /about/` aliases with `rewrite ^ /about.html last;`, placed after `location /`.
- **§6 prose at line 463:**
  - Make the `log_format` sentence plural.
  - Explain why both `access_log` lines are needed and that the CSP is inherited (About has no meta CSP).
  - Note that the `try_files` order mirrors vite, and to keep `last`.
  - Name the new log file and its Debian/Ubuntu logrotate coverage.
  - Say that direct `/dev-pages/…` hits are not in the pages log.
  - Tell existing hosts to merge the additions rather than overwrite a certbot-edited file, or to re-run certbot.
- **§6 TLS (525-533):** warn that re-applying §6 by overwriting the site file drops certbot's edits.
- **§6 Verify (475-481):** add `curl -I http://localhost/about` (200 + CSP), a pages-log `tail`, and a 404 hint.
- **§3 (299-303):** About is built under `dist/dev-pages/` and reached at `/about`, `/about/`, `/about.html` via §6.
- **Triage:**
  - Add the "Follow an About visit" subsection after line 249: the anchored `^page=about ` listing with positional awk, the main-log `request_id` grep, the `date -u` conversion with the JSON jq filter and the text variant using `"ip=$ip "`, and the hand-off to "Follow one request".
  - Include the four caveats, plus the forgeable-token note.
  - Add a pages-log bullet to "What each log is for".
- **Optional:**
  - a Triage table row for an `/about` 404;
  - a pointer from the §2 `LOG_FORMAT` paragraph (line 116);
  - `/about` in the §7 page list.
</doc>
<doc path="client/frontend/README.md">
"Local About Overrides" (lines 36-39): add that prod nginx serves whichever file was built (the override first, then the template) at `/about`, `/about/` and `/about.html` (`DEPLOYMENT.md` §6). Optionally add that an override must use root-absolute URLs, because it is also served at `/about/`, and that it gets only the server CSP header.
</doc>
<doc path="docs/project/issues/21-static-page-visit-logs.md">
At completion: `Status: enhancement, complete`, a delivery comment naming `docs/project/plans/22-21-static-page-visit-logs.md` and what was delivered, and a move to `docs/project/issues/archive/` per `docs/project/issue-tracker.md:21`.
</doc>
<doc path="docs/project/issues/plan.md">
- Lane 5c (line 98): mark 21 delivered and correct its file list for 21 to the nginx docs only.
- P5 row (line 42): update the stale "19 and part of 20" wording.
</doc>
<doc path="docs/project/roadmap.md">
Optional Delivered bullet for issue 21. The convention is inconsistent: 19 and 20 have none.
</doc>
<doc path="docs/project/issues/18-about-outbound-click-tracking.md">
Optional comment: issue 21's runbook names 18's beacon endpoint as the pageview upgrade path, so 18's endpoint design may need a page-view event type besides outbound clicks.
</doc>

### highest_risk

DEPLOYMENT.md §6 site block (About location): a location-level `access_log` replaces the inherited one, an `add_header` would drop the only CSP About has, `last` must stay, and the `set $static_page` must exist or `nginx -t` fails host-wide. A failing `nginx -t` blocks `scripts/deploy-bluegreen.sh` and `engine/install-engine-service.sh` too.
DEPLOYMENT.md §6 re-apply instruction against the TLS section: `certbot --nginx` edits the live site file, so telling existing hosts to "re-apply §6" by copying the block over it deletes TLS on any host that followed the docs.
DEPLOYMENT.md pages `log_format` field order and Triage runbook filters: nginx does not escape spaces, so the client-controlled `ua`, `x_request_id` (and `uri`) can forge ` status=200 ` / ` method=GET ` / `page=about` / `ip=` tokens. Unanchored greps, and text-mode `ip=$ip` without a trailing space, give spoofed or wrong matches unless the client-controlled fields come last and the runbook anchors and filters by field position.

## 2026-10-02 - Step 4 - Reassess the implementation plan (pass 3)

Pass 3. New impacts: none.

The plan holds up against the inventory and the tree. I opened the files the impacts name and they match: `DEPLOYMENT.md` §6, §3, Triage, Verify, TLS and §7 at the line numbers given; `vite.config.ts:13-22,91-93`; `server.py:136-195,339-357`; the three `nginx -t` gates; `config.json` test_groups, where no group maps `DEPLOYMENT.md`; the nav links on the six pages; the CSP meta tags missing from the template; the committed `dist/dev-pages/about.template.html`; issue 21's status; and `plan.md:42,98`. I found no impact the inventory misses. One inventory detail about nginx behaviour is slightly wrong (see unconfirmed), and it does not change the plan.
<question id="1">Yes. Exact-match locations win over `location /`. `rewrite … last` keeps one request, so there is one `$request_id`, one log phase, one line per log, and `$request_uri` is still the URL the visitor asked for. `try_files` serves the file in the same order vite builds it. The server-level CSP with `always` is inherited because the About location has no `add_header`. The `$static_page` variable is declared by the `set`, so `nginx -t` passes. The vite rewrite set (`vite.config.ts:22`) is exactly the three URLs. The template uses only root-absolute URLs, so serving it at `/about/` breaks nothing. Correlation will work, within the limits the plan already accepts: IP plus time window, and nothing to match when the visitor makes no further API call.</question>
<question id="2">1. The nav link `/about.html` on all six pages answers 404 in prod today and becomes 200. This is a visible fix for users. 2. A new log file appears under `/var/log/nginx/`. 3. A syntax mistake in the site file now breaks more than the site: the Engine installer, uninstaller and blue/green deploy all run `nginx -t` over the whole config, so a bad edit turns a deploy into a rollback. 4. Hosts change only when an operator re-applies §6, and a full overwrite of the file erases what `certbot --nginx` added (the TLS impact). 5. Two client-controlled fields (`ua`, `x_request_id`) go into a space-separated log line, so field order and anchored greps matter (the field-order impact).</question>
<question id="3">Everything needed is already in the inventory: 1. The About location must repeat the main `access_log` line, or About drops out of the main log. 2. The rewrite must keep `last`. 3. The About location must have no `add_header`, or it loses the CSP. 4. The re-apply instruction must say "merge these blocks" or "re-run certbot", not "overwrite". 5. `config.json` needs a test group that maps `DEPLOYMENT.md` (and `vite.config.ts`), or the new test never runs. 6. Issue 21 must move to `archive/`, as `issue-tracker.md:21` requires. Nothing in app code or the build has to change.</question>
<question id="4">1. `/about`, `/about/` and `/about.html` change from 404 to 200 in prod. 2. About requests get a second log line, in the new pages log. Their main-log lines are unchanged in format. 3. Every other route is unchanged: same locations, same logs, same headers. 4. A direct hit on `/dev-pages/about*.html` behaves as before: it is served through `location /` and leaves no pages line.</question>

New impacts:
none

Inventory entries that did not hold up:
The inventory entry for the DEPLOYMENT.md §6 locations ("Risk of regression") says `/about//` does not match the exact locations and falls to `location /` with a 404. That is not quite right. nginx's `merge_slashes` defaults to on, and location matching uses the normalised URI, so `/about//` is matched as `/about/`. It hits `location = /about/`, answers 200 and writes a pages line, and the line's `uri=` field still shows `/about//`. `/About` does stay a 404, because location matching is case-sensitive. This has no effect on the plan. It only matters if the test or the runbook asserts that `/about//` is a 404.

Conflicts: none

Recommendations: 1. Fix the pages-log field order and make the runbook filters anchored. Put `status`, `rt`, `request_id` and `uri` before the client-controlled `x_request_id` and `ua`. In the runbook, anchor on `^page=about ` and filter by field position with awk, not with unanchored `grep ' status=200 '`. Cost: a few words in the format line and the runbook. It stays inside the plan's "roughly this order".
2. Change §6's re-apply instruction from "re-apply §6" to "add the second `log_format` line and the three About locations to your existing site file, then `nginx -t && reload`". Add a line saying that overwriting the whole file removes what `certbot --nginx` added, and that you then have to run `certbot --nginx` again. Cost: about two sentences. It prevents TLS from being silently removed on existing hosts.
3. Add a `test_groups` entry in `.un/skills/devsecops/config.json` for the new test, mapping `DEPLOYMENT.md` and `client/frontend/vite.config.ts`. Have the test also check that the three exact-location URLs match vite's `rewriteToAbout` set and that the `try_files` paths match the two `dev-pages` names. Cost: one config entry and about 15 test lines. Without the entry, this build's only validation never runs.
4. Build the runbook test's Client record with the real `ClientLogFormatter` rather than a hand-written JSON string. Cost: one import. If `ts` or `context.ip` ever changes, the test goes red instead of the runbook silently matching nothing.
5. In the text-mode recipe, grep for `"ip=$ip "` with the trailing space, and say that text mode can be spoofed through the unquoted `user_agent`. Cost: one sentence.
6. Make the test's nginx wrapper tolerate nginx older than 1.19.5, which has no `-e` flag (for example Ubuntu 20.04's 1.18): skip, or accept the error-log alert. Point all five `*_temp_path` directives and `pid` into the temp dir. Cost: wrapper lines in the test. Without this the test fails, rather than skips, on hosts with an older nginx.
7. At completion, move issue 21 to `docs/project/issues/archive/`, update `plan.md` lines 42 and 98, and optionally comment on issue 18 that a pageview beacon would need its endpoint to accept a page-view event, since it is click-only as planned. Cost: doc edits only. The archive move is mandatory, and last time the agent had no delete tool, so it has to be checked by hand.
8. Optional extras: a Triage row for "`/about` answers 404", `/about` in the §7 page list, and the `client/frontend/README.md` line telling override authors to keep URLs root-absolute. Cost: one line each.

## 2026-10-02 - Step 5 - Draft the initial implementation

Recorded ungated, at the operator direction.

### draft

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

## 2026-10-02 - Step 6 - Design the phase breakdown

Recorded ungated, at the operator direction.

#### Phase 1 - Serve About [code]

**Files touched.** DEPLOYMENT.md (EDITED: §6 site block, the three About locations and the rat-tail comment), tests/active/test_static_page_visit_logs.py (NEW), .un/skills/devsecops/config.json (EDITED: test_static_page_visit_logs.py group)

**Checkpoint.** Seam: the fenced nginx site block in DEPLOYMENT.md §6 running in a real nginx. `_site_block()` takes the first ```nginx fence after the `/etc/nginx/sites-available/peertube-browser`: line. Tokens are swapped (root → tmp/www, /var/log/nginx/ → tmp/log/, listen 80 → 127.0.0.1:<free port>), the block is wrapped in a minimal http{} config with temp paths, and it is run with `nginx -p tmp -e tmp/error.log -c tmp/nginx.conf`. `_statements()` is copied from test_install_engine_service.py:141-145, which is the precedent for parsing the block. No existing test starts a real nginx, so the live-server harness is new. Asserts: `nginx -t` exits 0. GET and HEAD on /about, /about/, /about.html and /about.html?x=1 return 200 with the template's bytes (GET) and a Content-Security-Policy header equal to the block's value. With both dev-pages files present, the override is served. With neither present, the answer is 404 and still carries the CSP. test_about_mapping_matches_vite needs no nginx: it parses vite.config.ts and asserts that the exact-location URLs equal the rewriteToAbout set, and that the try_files candidates are /dev-pages/ plus the two names aboutSourcePath picks between. Skipped when shutil.which("nginx") is None or nginx refuses to start unprivileged.

**Intent.** The §6 nginx site block in DEPLOYMENT.md serves About at /about, /about/ and /about.html through three exact locations, using the same file choice vite's build makes.

- C1 - Each of /about, /about/ and /about.html returns the dev-pages override if it exists, otherwise the template, otherwise a 404, and every one of those responses carries the server-level Content-Security-Policy.
- C2 - The block's exact-location URLs and try_files candidates equal the About mapping in client/frontend/vite.config.ts (rewriteToAbout and aboutSourcePath).

**Outcome.** _pending_

#### Phase 2 - Pages log [code]

**Files touched.** DEPLOYMENT.md (EDITED: §6 site block, the peertube_browser_pages log_format, set $static_page and both access_log lines in the About location), tests/active/test_static_page_visit_logs.py (EDITED)

**Checkpoint.** Seam: the same live-nginx harness as phase 1, now reading the two temp log files (tmp/log/peertube-browser.access.log and tmp/log/peertube-browser.pages.access.log). After each request it polls for new lines. Asserts, for About requests (GET, HEAD, a 404 with no dev-pages files, with and without an X-Request-ID header): exactly one new pages line and exactly one new main line. Fields 1–8 of the pages line are page=about, ts=<digits.3digits>, time=, ip=127.0.0.1, method=, status=, rt=, request_id=<32 hex>. uri= is the requested path plus query. x_request_id is - when the header is absent and the sent value when present. The main line carries the same request_id. For /, /index.html, /api/health (502, since no upstream runs) and /dev-pages/about.template.html: no new pages line, and exactly one new main line each. Skipped like phase 1.

**Intent.** Every About request writes exactly one line to the new peertube_browser_pages log beside its usual main-log line, and requests to other routes write nothing there.

- C1 - Each About request, of any method or status, writes exactly one pages-log line and exactly one main-log line, and both carry the same request_id.
- C2 - Requests to /, /index.html, /api/ and /dev-pages/about*.html write no pages-log line and still write one main-log line each.

**Outcome.** _pending_

#### Phase 3 - Runbook commands [code]

**Files touched.** DEPLOYMENT.md (EDITED: Triage "Follow an About visit" heading and its fenced bash blocks), tests/active/test_static_page_visit_logs.py (EDITED)

**Checkpoint.** Seam: the fenced bash blocks under `### Follow an About visit` in DEPLOYMENT.md, which `_runbook()` extracts and runs under bash with journalctl replaced by `cat file`. test_forged_user_agent_does_not_move_fields (needs nginx) sends a 404 About request with UA ` status=200 method=GET page=about`. It asserts that the request's pages line has $6 == status=404, and that the runbook's listing awk filtered to GET/200 does not list it. test_runbook_finds_visit_and_client_record (needs jq, bash, GNU date; no nginx) writes a synthetic pages line plus request.start records produced by the real ClientLogFormatter from client/backend/server.py, in JSON and in text mode. The matching record has record.created = visit + 10 s, and there is one decoy outside the window and one decoy on 1.2.3.45. It asserts that the runbook's from/to/jq commands (JSON) and its awk/grep -F commands (text) each select exactly the in-window record.

**Intent.** The shell commands in DEPLOYMENT.md's new "Follow an About visit" Triage subsection select About visits by field position and find a visit's Client request.start records by its IP and time window.

- C1 - The runbook's listing filter, which selects by field position, does not list a 404 About request whose user agent carries forged status=200, method=GET and page=about tokens as a successful GET.
- C2 - The runbook's correlation commands select exactly the visitor's in-window request.start record from real ClientLogFormatter output in both JSON and text modes.

**Outcome.** _pending_


Needs coordination: none

Rationale: The settled draft calls the whole build documentation. Under this step's rule, any text written for a human reader gets no phase. That covers the §6 prose paragraphs, the Verify, TLS, §2, §3 and §7 edits, the Triage table rows, the pages-log bullet, the runbook's explanatory prose and caveats, client/frontend/README.md, and the tracker edits (issue 21 status/comment/archive move, plan.md, issue 18 comment). Step 9 writes all of these from what the build delivered. What remains is text a test executes: the nginx site block, which an operator installs verbatim and nginx parses, and the runbook's shell commands, which an operator runs. The draft's test contract (§12) already exercises both. So these are the code phases, and their checkpoints are slices of that contract.

The split follows what each slice makes true, and each lands green on its own. Phase 1 adds only the three locations. The block passes nginx -t without the second log_format, and About serving plus the vite-mapping check can be proven before any logging exists. Phase 2 adds the log_format, the set and the two access_log lines, and proves the one-line-per-file property and the absence of pages lines on other routes. Phase 3 depends on phase 2's field order, because the forged-UA test reads $6. It lands the runbook commands and proves their positional filtering and their correlation against the real ClientLogFormatter.

The config.json test group is added in phase 1 together with the new test file, so selection works from the first checkpoint. There is no precedent for a test that starts a real nginx: tests/active only parses nginx text (test_install_engine_service.py `_statements`) or stubs `nginx -t`. The live-server harness is therefore new, and the _statements helper is reused. The operator confirmed that nginx, jq, bash and GNU date are installed on the host that runs the suite, so the skip conditions will not fire and every clause is actually exercised.

## 2026-10-02 - Step 7 - Phase 1 (Serve About) - must_prove

Quoted from the phase Intent, written at Step 6 before the checkpoint was drafted.

Intent:
The §6 nginx site block in DEPLOYMENT.md serves About at /about, /about/ and /about.html through three exact locations, using the same file choice vite's build makes.

- C1 - Each of /about, /about/ and /about.html returns the dev-pages override if it exists, otherwise the template, otherwise a 404, and every one of those responses carries the server-level Content-Security-Policy.
- C2 - The block's exact-location URLs and try_files candidates equal the About mapping in client/frontend/vite.config.ts (rewriteToAbout and aboutSourcePath).

must_prove:
- C1 - Each of /about, /about/ and /about.html returns the dev-pages override if it exists, otherwise the template, otherwise a 404, and every one of those responses carries the server-level Content-Security-Policy.
- C2 - The block's exact-location URLs and try_files candidates equal the About mapping in client/frontend/vite.config.ts (rewriteToAbout and aboutSourcePath).

## 2026-10-02 - Step 7 - Phase 1 (Serve About) - self-check (audit round 1, send-back 0)

`tests/tmp/test_21_static_page_visit_logs_phase1.py`, surface `checkpoint`. Collection exit 0.

- C1 - tests/tmp/test_21_static_page_visit_logs_phase1.py:153 — in the override-and-template, override-only and template-only cases, GET and HEAD on /about, /about/, /about.html and /about.html?x=1 each answer (200, [block CSP], str(len(body)), body for GET / b"" for HEAD). The body is the override's when it exists, otherwise the template's. - expected: A probe spliced `location = {url} { try_files /dev-pages/about.html /dev-pages/about.template.html =404; }` for each of the three URLs into the §6 block and ran this function. All three 200 cases passed: the override (49 bytes) when present, the template bytes when it was alone, and exactly one CSP header equal to the block's. Against the unchanged block, the run fails here with 'GET /about': (404, [csp], ..., nginx 404 page) != (200, [csp], '49', OVERRIDE). - excludes: Template listed before the override in try_files: the probe went red here in override-and-template, because the template's bytes were served. Template-only try_files: red here, because the override was ignored. A location-level `add_header` (X-Frame-Options), which drops the inherited server CSP: red here with an empty CSP list. Today's block with no About locations: 404 on every URL, red here in all three cases (observed).
- C1 - tests/tmp/test_21_static_page_visit_logs_phase1.py:150 — in the neither case, every GET/HEAD on the four About URLs answers (404, [block CSP]). - expected: (404, [csp]) for all 8 requests. Observed both against the current block, where this case passes, and against the probe's right block, where it also passes. - excludes: An SPA-style fallback (`try_files /dev-pages/about.html /dev-pages/about.template.html /index.html`): the probe went red here only, with 200 and index.html. The three 200 cases still passed.
- C1 - tests/tmp/test_21_static_page_visit_logs_phase1.py:154 — GET /aboutx, /about/x and /about.htm answer (404, [block CSP]) in every case. - expected: (404, [csp]) for each of the three. Observed against the current block and against the probe's right block. - excludes: A prefix `location /about { try_files ... }` instead of exact locations: the probe passed line 153 and went red here, because /aboutx and /about/x served About.
- C2 - tests/tmp/test_21_static_page_visit_logs_phase1.py:168 — the sorted `location =` URLs of the §6 block equal the sorted rewriteToAbout entries parsed from vite.config.ts, each once. - expected: ['/about', '/about.html', '/about/'] on both sides. The probe's right block passed. Against the current block the run fails here with `assert [] == ['/about', '/...l', '/about/']`. - excludes: A block missing one URL (e.g. no `location = /about/`), duplicating one, adding one vite does not rewrite, or a block with no About locations at all reads a different list. The last case is observed: [].
- C2 - tests/tmp/test_21_static_page_visit_logs_phase1.py:170 — each exact location has exactly one try_files, and its candidates before the fallback are [aboutSourcePath's existing-branch pick, its else-branch pick]. - expected: {url: [['/dev-pages/about.html', '/dev-pages/about.template.html']]} for each of the three URLs. The probe's right block passed this test. - excludes: Swapped candidate order reads [['/dev-pages/about.template.html', '/dev-pages/about.html']]. A template-only try_files reads [['/dev-pages/about.template.html']]. A try_files with no `=404` fallback reads the override alone. All of these differ from vite's two picks in order. (The probe ran C2 only on the right variant, where it passed; for the wrong variants this column is reasoned from the parse, not observed.)

<assertions>
tests/tmp/test_21_static_page_visit_logs_phase1.py:131 — control: the override bytes and the real about.template.html bytes differ in length, so a HEAD's Content-Length shows which file was served (C1 precondition)
tests/tmp/test_21_static_page_visit_logs_phase1.py:137 — control: each swapped token (`root /var/www/peertube-browser;`, `/var/log/nginx/`, `listen 80;`) is in the §6 block, so the run never binds port 80 or writes /var/log (C1 precondition)
tests/tmp/test_21_static_page_visit_logs_phase1.py:142 — `nginx -t` exits 0 on the §6 block wrapped in the temp http{} (C1 precondition, agreed at Step 6)
tests/tmp/test_21_static_page_visit_logs_phase1.py:145 — control: GET / returns (200, [block CSP], len(index), index bytes), so the harness serves the block's root with its CSP (C1 precondition)
tests/tmp/test_21_static_page_visit_logs_phase1.py:150 — with neither dev-pages file present, GET and HEAD on /about, /about/, /about.html and /about.html?x=1 each answer 404 with exactly one Content-Security-Policy, equal to the block's (C1)
tests/tmp/test_21_static_page_visit_logs_phase1.py:153 — with the override present (beside the template or alone), GET and HEAD on those four URLs answer 200 with one CSP equal to the block's, Content-Length = len(override), GET body = the override bytes and HEAD body empty; with only the template present, the same with the real template's bytes; redirects are not followed, so a 301 cannot pass (C1)
tests/tmp/test_21_static_page_visit_logs_phase1.py:154 — negative path: /aboutx, /about/x and /about.htm answer 404 with the block's CSP in every scenario, so only the exact URLs serve About (C1)
tests/tmp/test_21_static_page_visit_logs_phase1.py:162 — control: rewriteToAbout and the `existsSync(devAboutPath) ? A : B` aboutSourcePath are both found in vite.config.ts (C2 precondition)
tests/tmp/test_21_static_page_visit_logs_phase1.py:165 — control: the parse found URLs, and both picks start with /dev-pages/ (C2 precondition)
tests/tmp/test_21_static_page_visit_logs_phase1.py:168 — the block's `location =` URLs, sorted and counted with duplicates, equal rewriteToAbout's URLs parsed from vite.config.ts (C2)
tests/tmp/test_21_static_page_visit_logs_phase1.py:170 — each exact location has exactly one try_files, and its candidates before the fallback equal aboutSourcePath's [true-branch, false-branch] picks, i.e. /dev-pages/about.html then /dev-pages/about.template.html, both read from vite.config.ts (C2)
</assertions>

<probes>
1) tests/tmp/test_probe_21_p1_nginx.py, first version, run with ValidateTests ["tests/tmp/test_probe_21_p1_nginx.py", "-s"]. Printed: shutil.which("nginx") = /usr/sbin/nginx, uid 1000, nginx/1.28.3 (Ubuntu), compiled temp paths /var/lib/nginx/*. A minimal http{} with tmp client_body/proxy/fastcgi/uwsgi/scgi temp paths, `pid`, `daemon off; master_process off;`, started as `nginx -p tmp -e tmp/error.log -c tmp/nginx.conf`, passed `-t` (exit 0) and served unprivileged. Results: an exact location's try_files gave GET /about 200 with the file's bytes, HEAD 200 with an empty body and the same Content-Length, /about?x=1 200, and `add_header … always` was present on a try_files =404 (Content-Length 153). The error log was empty.
2) The same probe file, rewritten to load the checkpoint module by path and call its tests against the current, unedited DEPLOYMENT.md. `nginx -t` exited 0 on the real §6 block (with its log_format and proxy locations) once wrapped. The GET / control gave 200 with the index and the block's CSP. Every About URL gave 404 with exactly one CSP header, equal to the block's value. Red is at line 153 for override-and-template, override-only and template-only; neither passes (location / already 404s with the CSP). test_about_mapping_matches_vite is red at line 168 with exact=[], urls=['/about','/about/','/about.html'], picks=['/dev-pages/about.html','/dev-pages/about.template.html'].
3) The same probe file, rewritten to monkeypatch _site_block with variants inserted before `location /`. Variant good (three `location =` blocks with try_files /dev-pages/about.html /dev-pages/about.template.html =404): mapping and all four scenarios PASSED. Template-first: mapping fails at 170, override-and-template fails at 153. A per-location add_header (CSP no longer inherited): every scenario fails, at 150 or 153. Prefix `location /about`: mapping fails at 168, and the three present scenarios fail at 154 (/aboutx and /about/x served). /about/ missing: mapping fails at 168, present scenarios fail at 153.
The probe file tests/tmp/test_probe_21_p1_nginx.py is still on disk: I have no delete tool, so it needs removing by hand. It only loads and calls the checkpoint, so it duplicates its gating if collected.
</probes>

<unassertable>
none
</unassertable>

### `tests/tmp/test_21_static_page_visit_logs_phase1.py` - 10110 characters, inlined in full

````
"""The §6 nginx site block in DEPLOYMENT.md, run in a real nginx, answers /about, /about/, /about.html and /about.html?x=1 with the dev-pages override when it exists, else the template, else 404, every answer carrying the block's Content-Security-Policy; its exact locations and try_files candidates are vite.config.ts's About mapping.

- `nginx -t` accepts the block. For GET and HEAD on each About URL: with the override (alone or beside the template) the answer is 200 with the override's bytes and Content-Length; with only the template, 200 with the template's; with neither, 404. Each answer has exactly one Content-Security-Policy header, equal to the block's. /aboutx, /about/x and /about.htm stay 404 with the CSP.
- The block's `location =` URLs are rewriteToAbout's, once each, and each one's try_files candidates before the fallback are aboutSourcePath's two picks, the override first.

The block is the first ```nginx fence after the sites-available line. Its root, log directory and `listen 80` are swapped for tmp paths and a free loopback port, and it is wrapped in a minimal http{} with tmp temp paths. Skipped when nginx is missing or will not run unprivileged.
"""
from __future__ import annotations

import contextlib
import http.client
import re
import shutil
import socket
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DEPLOYMENT = ROOT / "DEPLOYMENT.md"
VITE_CONFIG = ROOT / "client" / "frontend" / "vite.config.ts"
TEMPLATE = ROOT / "client" / "frontend" / "dev-pages" / "about.template.html"
NGINX = shutil.which("nginx")
SITE_LINE = "`/etc/nginx/sites-available/peertube-browser`:"
# What keeps the block from running unprivileged: the document root, the log directory and port 80.
SWAPS = (("root /var/www/peertube-browser;", "root {www};"), ("/var/log/nginx/", "{log}/"), ("listen 80;", "listen 127.0.0.1:{port};"))
ABOUT_URLS = ("/about", "/about/", "/about.html", "/about.html?x=1")
# Not About under exact locations: they fall to `location /`, where no such file exists.
NOT_ABOUT_URLS = ("/aboutx", "/about/x", "/about.htm")
OVERRIDE = b"<!doctype html><title>dev-pages override</title>\n"
INDEX = b"<!doctype html><title>index</title>\n"


def _site_block() -> str:
    """The first ```nginx fence after the sites-available line of §6."""
    text = DEPLOYMENT.read_text(encoding="utf-8")
    assert SITE_LINE in text, f"{SITE_LINE} not in DEPLOYMENT.md"
    match = re.search(r"^```nginx\n(.*?)^```", text[text.index(SITE_LINE):], re.S | re.M)
    assert match, "no ```nginx fence after the sites-available line"
    return match.group(1)


def _statements(nginx_text: str) -> list[str]:
    """nginx directives with comments dropped and whitespace collapsed, so a second `listen` on any line or inside a block is counted."""
    text = re.sub(r"#[^\n]*", "", nginx_text)
    return [" ".join(part.split()) for part in re.split(r"[;{}]", text) if part.strip()]


def _csp(block: str) -> str:
    match = re.search(r'add_header\s+Content-Security-Policy\s+"([^"]+)"', block)
    assert match, "no Content-Security-Policy add_header in the block"
    return match.group(1)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _write_config(run_dir: Path, server_text: str) -> None:
    temp_paths = "".join(f"    {name}_temp_path {run_dir / name};\n" for name in ("client_body", "proxy", "fastcgi", "uwsgi", "scgi"))
    (run_dir / "nginx.conf").write_text(f"pid {run_dir / 'nginx.pid'};\ndaemon off;\nmaster_process off;\nevents {{}}\nhttp {{\n{temp_paths}    access_log {run_dir / 'log' / 'access.log'};\n{server_text}\n}}\n")


def _nginx_args(run_dir: Path, *extra: str) -> list[str]:
    return [NGINX, *extra, "-p", str(run_dir), "-e", str(run_dir / "error.log"), "-c", str(run_dir / "nginx.conf")]


def _require_unprivileged_nginx(tmp_path: Path) -> None:
    if NGINX is None:
        pytest.skip("nginx is not installed")
    run_dir = tmp_path / "unprivileged"
    (run_dir / "log").mkdir(parents=True)
    _write_config(run_dir, f"server {{ listen 127.0.0.1:{_free_port()}; }}")
    check = subprocess.run(_nginx_args(run_dir, "-t"), stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30)
    if check.returncode != 0:
        pytest.skip(f"nginx will not run unprivileged: {check.stderr}")


@contextlib.contextmanager
def _serving(run_dir: Path, port: int):
    proc = subprocess.Popen(_nginx_args(run_dir), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 10
        while True:
            if proc.poll() is not None:
                pytest.fail(f"nginx exited {proc.returncode}: {proc.stderr.read().decode()}\n{(run_dir / 'error.log').read_text()}")
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
                break
            except OSError:
                if time.monotonic() > deadline:
                    pytest.fail(f"nginx did not listen on {port} within 10 s")
                time.sleep(0.05)
        yield
    finally:
        proc.terminate()
        try:
            proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()


def _answer(port: int, method: str, url: str) -> tuple[int, list[str], str | None, bytes]:
    """Status, every Content-Security-Policy value, Content-Length and body; http.client follows no redirect, so a 301 shows as one."""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request(method, url)
        resp = conn.getresponse()
        return resp.status, [value for name, value in resp.getheaders() if name.lower() == "content-security-policy"], resp.getheader("Content-Length"), resp.read()
    finally:
        conn.close()


@pytest.mark.parametrize(("present", "served"), [pytest.param(("about.html", "about.template.html"), "about.html", id="override-and-template"), pytest.param(("about.html",), "about.html", id="override-only"), pytest.param(("about.template.html",), "about.template.html", id="template-only"), pytest.param((), None, id="neither")])
def test_about_urls_serve_override_then_template_then_404_with_csp(tmp_path: Path, present: tuple[str, ...], served: str | None) -> None:
    """`nginx -t` accepts the §6 block; GET and HEAD on /about, /about/, /about.html and /about.html?x=1 answer 200 with the override's bytes and length when it exists, else the template's, else 404, each with exactly one CSP header equal to the block's; /aboutx, /about/x and /about.htm answer 404 with the CSP."""
    _require_unprivileged_nginx(tmp_path)
    block = _site_block()
    csp = _csp(block)
    run_dir = tmp_path / "site"
    www = run_dir / "www"
    (www / "dev-pages").mkdir(parents=True)
    (run_dir / "log").mkdir()
    (www / "index.html").write_bytes(INDEX)
    files = {"about.html": OVERRIDE, "about.template.html": TEMPLATE.read_bytes()}
    assert len(files["about.html"]) != len(files["about.template.html"])  # control: override and template differ in Content-Length, so HEAD tells them apart too
    for name in present:
        (www / "dev-pages" / name).write_bytes(files[name])
    port = _free_port()
    server_text = block
    for old, new in SWAPS:
        assert old in server_text, f"{old!r} not in the §6 block"  # control: an unswapped token would bind port 80 or write /var/log
        server_text = server_text.replace(old, new.format(www=www, log=run_dir / "log", port=port))
    _write_config(run_dir, server_text)

    check = subprocess.run(_nginx_args(run_dir, "-t"), stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30)
    assert check.returncode == 0, check.stderr  # the block as published loads

    with _serving(run_dir, port):
        assert _answer(port, "GET", "/") == (200, [csp], str(len(INDEX)), INDEX)  # control: the harness serves the block's root with the block's CSP
        got = {f"{method} {url}": _answer(port, method, url) for url in ABOUT_URLS for method in ("GET", "HEAD")}
        not_about = {f"GET {url}": _answer(port, "GET", url)[:2] for url in NOT_ABOUT_URLS}

    if served is None:
        assert {key: answer[:2] for key, answer in got.items()} == {key: (404, [csp]) for key in got}  # C1: neither file is a 404, still carrying the CSP
    else:
        body = files[served]
        assert got == {f"{method} {url}": (200, [csp], str(len(body)), body if method == "GET" else b"") for url in ABOUT_URLS for method in ("GET", "HEAD")}  # C1: override when present, else template; one CSP equal to the block's
    assert not_about == {f"GET {url}": (404, [csp]) for url in NOT_ABOUT_URLS}  # C1: only the three exact URLs are About


def test_about_mapping_matches_vite() -> None:
    """The block's `location =` URLs are rewriteToAbout's, once each, and each one's try_files candidates before the fallback are aboutSourcePath's two picks, the override first."""
    vite = VITE_CONFIG.read_text(encoding="utf-8")
    rewrite = re.search(r"const rewriteToAbout = new Set\(\[([^\]]*)\]\)", vite)
    source = re.search(r'const aboutSourcePath = existsSync\(devAboutPath\)\s*\?\s*"([^"]+)"\s*:\s*"([^"]+)"', vite)
    assert rewrite and source, "rewriteToAbout or aboutSourcePath not found in vite.config.ts"  # control
    urls = re.findall(r'"([^"]+)"', rewrite.group(1))
    picks = list(source.groups())
    assert urls and all(pick.startswith("/dev-pages/") for pick in picks), (urls, picks)  # control: the parse read the mapping

    exact = re.findall(r"location\s*=\s*([^\s{]+)\s*\{([^{}]*)\}", _site_block())
    assert sorted(url for url, _ in exact) == sorted(urls)  # C2: the exact locations are vite's About URLs, each once
    candidates = {url: [statement.split()[1:-1] for statement in _statements(body) if statement.split()[0] == "try_files"] for url, body in exact}
    assert candidates == {url: [picks] for url in urls}  # C2: one try_files each, override then template, as aboutSourcePath picks

````


Gate: satisfied

## 2026-10-02 - Step 7 - Phase 1 (Serve About) - red (audit round 1)

`tests/tmp/test_21_static_page_visit_logs_phase1.py` exited 1.

```
  tests/tmp/test_21_static_page_visit_logs_phase1.py  4 failed, 1 passed                     0.0s
  --------------------------------------------------
  total                                               4 failed, 1 passed                     0.5s wall, 1 lane

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

## 2026-10-02 - Step 7 - Phase 1 (Serve About) - audit (round 1)

- AUDIT: devsecops-test-shape-auditor - PASS
- AUDIT: devsecops-test-claim-auditor - PASS
- OUTSTANDING: nothing

### devsecops-test-shape-auditor

SHAPE AUDIT — VERDICT: PASS

CRITICAL
none

RECOMMENDATIONS
1. absence-only-assertion (rules/shape.md) — tests/tmp/test_21_static_page_visit_logs_phase1.py:150
   assert {key: answer[:2] for key, answer in got.items()} == {key: (404, [csp]) for key in got}
   Only the `neither` row reaches this line. Its result is the same with or without the About locations: today `location /` already returns 404 with the CSP for /about, /about/ and /about.html. The positive control at line 145 shows the harness works, not that the About path ran. The proof that the About path ran comes from the other parametrize rows (`override-and-template`, `override-only`, `template-only`), which fail on line 153 against an absent implementation. That matches the entry's third `<how_to_spot>` bullet for this one row only. The test function as a whole is not absence-only, so this is not Critical. Expect this row to be green when the build checks the red. The response cannot tell "About locations falling to =404" apart from "no About locations", so no extra assertion on this row can close that gap.

PREDICTED FAILURE
`test_about_urls_serve_override_then_template_then_404_with_csp[override-and-template|override-only|template-only]` fails at line 153: every About GET/HEAD answers `(404, [csp], ...)` instead of 200 with the override's or template's bytes, because the §6 block (DEPLOYMENT.md:418-458) has no `location =` About entries. The `[neither]` row passes. `test_about_mapping_matches_vite` fails at line 168: `sorted([])` is compared with `['/about', '/about.html', '/about/']`, because `exact` finds no `location =` in the block.

NOT ASSESSED
1. `code_under_test` lists tests/active/test_static_page_visit_logs.py as NEW. It does not exist (Glob found no match), so it was not read. The test under audit does not import it.
2. `code_under_test` lists .un/skills/devsecops/config.json. It was not read because the test under audit does not touch it, so it has no bearing on this test's assertion form.

### devsecops-test-claim-auditor

CLAIM AUDIT — VERDICT: PASS

CLAUSE MAP  (24 clauses: 7 must_prove, 14 docstring, 3 name)
| id | source | clause | assertion | excludes | status |
|---|---|---|---|---|---|
| C1a | must_prove | /about, /about/ and /about.html return the dev-pages override "if it exists" | :153 (params override-and-template, override-only) | serving the template, or index.html, when the override is present. Bytes and Content-Length differ (control :131), so GET and HEAD both catch it | CARRIED |
| C1b | must_prove | "otherwise the template" | :153 (param template-only) | a 404 or an index.html fallback when only the template exists | CARRIED |
| C1c | must_prove | "otherwise a 404" | :150 (param neither) | a fallback to /index.html, which exists in www (:129), or any other 200 | CARRIED |
| C1d | must_prove | each of the three URLs, not just one | :150, :153: dict keyed per method and URL over ABOUT_URLS (:146) | covering /about but leaving /about/ or /about.html to fall to `location /` (404) | CARRIED |
| C1e | must_prove | every response carries the server-level CSP | :150, :153 (`[csp]`), :154; csp is read from the block's add_header (:124) | a location-level `add_header` that drops the inherited server CSP, a CSP missing on the 404, a second or different CSP value | CARRIED |
| C2a | must_prove | the block's exact-location URLs equal rewriteToAbout | :168 | a missing or extra `location =` URL, a duplicate, or a list hard-coded apart from vite (both sides are parsed live, :160/:167) | CARRIED |
| C2b | must_prove | the try_files candidates equal aboutSourcePath | :170 | template-first order, a missing pick, a `$uri` candidate, or two try_files in one location | CARRIED |
| D1 | docstring | "`nginx -t` accepts the block" | :142 | a block that does not load | CARRIED |
| D2 | docstring | "GET and HEAD on each About URL" | :146, :153 (HEAD expects b"" body and the file's Content-Length) | HEAD answered differently from GET | CARRIED |
| D3 | docstring | "/about.html?x=1" is answered as About | :153 / :150 via ABOUT_URLS (:29) | an exact match broken by a query string | CARRIED |
| D4 | docstring | "with the override (alone or beside the template)" | :153 over two params (:119) | override served only when the template is absent, or the reverse | CARRIED |
| D5 | docstring | "the override's bytes and Content-Length" | :153 | right status but wrong body or length | CARRIED |
| D6 | docstring | "with only the template, 200 with the template's" | :153 (template-only) | 404, or override expected but absent | CARRIED |
| D7 | docstring | "with neither, 404" | :150 | 200 fallback | CARRIED |
| D8 | docstring | "exactly one Content-Security-Policy header, equal to the block's" | :150, :153 (list `[csp]`, all headers collected at :114) | zero, two, or a differing CSP header | CARRIED |
| D9 | docstring | "/aboutx, /about/x and /about.htm stay 404 with the CSP" | :154 | a prefix or regex location that also captures neighbours | CARRIED |
| D10 | docstring | "`location =` URLs are rewriteToAbout's, once each" | :168 | duplicates, since sorted lists are compared | CARRIED |
| D11 | docstring | "try_files candidates before the fallback are aboutSourcePath's two picks, the override first" | :170 | reversed order, a single pick, extra candidates | CARRIED |
| D12 | docstring | "the block is the first ```nginx fence after the sites-available line" | :39, :41 | auditing a different fence, or none | CARRIED |
| D13 | docstring | root, log directory and `listen 80` are swapped for tmp paths | :137 | an unswapped token silently left (port 80, /var/log) | CARRIED |
| D14 | docstring | "Skipped when nginx is missing or will not run unprivileged" | :74, :80 (pytest.skip, not an assertion) | describes the harness, not the code; nothing to exclude | CARRIED |
| N1 | name | "about_urls_serve_override_then_template_then_404" | :150, :153 | wrong precedence or wrong fallback | CARRIED |
| N2 | name | "with_csp" | :150, :153, :154 | a response without the block's CSP | CARRIED |
| N3 | name | "about_mapping_matches_vite" | :168, :170 | drift between the nginx block and vite.config.ts | CARRIED |

Rows D1–D14 count each docstring clause once. The module docstring (:1–6) and the two function docstrings (:121, :158) say the same things.

CRITICAL
none

RECOMMENDATIONS
1. bounds (rules/testing.md) — tests/tmp/test_21_static_page_visit_logs_phase1.py:29
   The URL edges cover a query string and three near-misses (:31). They do not cover a trailing variant of the exact form (`/about.html/`) or a case variant (`/About`). Both are cheap to add to NOT_ABOUT_URLS and would pin that only the three exact URLs are About. This is not a gap in any must_prove clause.

OBSERVATIONS
none

NOT ASSESSED
1. Whether nginx is installed and runs unprivileged where this checkpoint will run could not be checked: the sandbox blocks reads outside the project. The C1 test skips without such an nginx (:74, :80). A skip proves C1a–C1e nothing, so the checkpoint only stands for C1 where nginx actually runs. Its clause rows above were judged from the test as written.
2. Two `code_under_test` paths do not exist yet: tests/active/test_static_page_visit_logs.py (Glob: no match) and the `test_static_page_visit_logs.py` group in .un/skills/devsecops/config.json (Grep: no match). The test under audit references neither, so this verdict is unaffected.
3. The §6 block in DEPLOYMENT.md (:414–459) has no `location =` About entries yet. The test was judged on what it asserts, not on whether the current block passes it.

## 2026-10-02 - Step 7 - Phase 1 (Serve About) - checkpoint outcome (run 1)

`tests/tmp/test_21_static_page_visit_logs_phase1.py` exited 0 after the phase landed.

<changes>
### DEPLOYMENT.md
In the §6 site block (`/etc/nginx/sites-available/peertube-browser`), right after `location / { … }`, I added three exact locations: `location = /about`, `location = /about/` and `location = /about.html`. Each one holds a single `try_files /dev-pages/about.html /dev-pages/about.template.html =404;`. That serves the dev-pages override if it exists, otherwise the template, otherwise a 404. The candidate order is vite's `aboutSourcePath` order, and the three URLs are vite's `rewriteToAbout` set.

None of the three locations has its own `add_header`, so each one picks up the server-level `Content-Security-Policy … always`, including on the 404.

Above the three locations sits a one-line `rat-tail:` comment. It says the URLs and the two file names copy vite.config.ts by hand, that `tests/active/test_static_page_visit_logs.py` compares the two, and that building About to `dist/about.html` is the fix if the mapping grows.

Each location has its own `try_files` rather than the draft's `rewrite ^ /about.html last` aliases. The checkpoint requires exactly one `try_files` per exact location, with vite's two picks. Nothing else in the block changed, and the §6 prose is untouched; the docs pass covers it.

### tests/active/test_static_page_visit_logs.py
Not created. The step asked for production code only. This phase's form of the durable test is the gated checkpoint in `tests/tmp/`, and a hand-made copy in `tests/active/` would be a second, ungated version of the same test. I followed the 01-32 build, where the implementer also left the active test for the workflow to promote.

### .un/skills/devsecops/config.json
Not edited, for a related reason. An entry naming `test_static_page_visit_logs.py` before that file exists shows up in `map_health` as an `unknown_groups` entry. The plan's entry also includes `client/backend/server.py`, which only the phase 3 runbook test needs. Whoever adds the entry should also list `client/frontend/dev-pages/about.template.html`, because the checkpoint reads its bytes. The plan's entry leaves it out.
</changes>

<inner_tests>
none
</inner_tests>

<unanticipated>
none
</unanticipated>

<awaiting_operator>
none
</awaiting_operator>

```
  tests/tmp/test_21_static_page_visit_logs_phase1.py  5 passed                               0.0s
  --------------------------------------------------
  total                                               5 passed                               0.4s wall, 1 lane

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

## 2026-10-02 - Step 7 - Phase 2 (Pages log) - must_prove

Quoted from the phase Intent, written at Step 6 before the checkpoint was drafted.

Intent:
Every About request writes exactly one line to the new peertube_browser_pages log beside its usual main-log line, and requests to other routes write nothing there.

- C1 - Each About request, of any method or status, writes exactly one pages-log line and exactly one main-log line, and both carry the same request_id.
- C2 - Requests to /, /index.html, /api/ and /dev-pages/about*.html write no pages-log line and still write one main-log line each.

must_prove:
- C1 - Each About request, of any method or status, writes exactly one pages-log line and exactly one main-log line, and both carry the same request_id.
- C2 - Requests to /, /index.html, /api/ and /dev-pages/about*.html write no pages-log line and still write one main-log line each.

## 2026-10-02 - Step 7 - Phase 2 (Pages log) - self-check (audit round 1, send-back 0)

`tests/tmp/test_21_static_page_visit_logs_phase2.py`, surface `checkpoint`. Collection exit 0.

- C1 - tests/tmp/test_21_static_page_visit_logs_phase2.py:167 — runs GET and HEAD on /about, /about/, /about.html and /about.html?x=1, each with and without X-Request-ID (16 requests per row). Checked in two rows: template only (200) and no dev-pages files (404). For each request it checks the status, exactly 1 new main-log line and exactly 1 new pages-log line. - expected: (200, 1, 1) for all 16 keys in template-200, and (404, 1, 1) for all 16 in no-files-404. Observed: the probe spliced the plan's draft block (pages log_format plus both access_log lines in the About location) into this checkpoint, and `test_probe[about-good] PASSED`. Against the current §6 block every key reads (200, 1, 0) or (404, 1, 0). - excludes: About location lists only the pages access_log and drops the main one; a location-level access_log replaces the inherited one, so About falls out of the main log. Observed in the probe (`about-pages-only`): every key reads (200, 0, 1), red at :167. With no pages log at all, which is the current block, it reads (200, 1, 0).
- C1 - tests/tmp/test_21_static_page_visit_logs_phase2.py:169 — checked over the same 32 requests:
- Pages fields 1–8 fullmatch `page=about ts=\d+\.\d{3} time=<ISO 8601 with offset> ip=127.0.0.1 method=<sent method> status=<code> rt=\d+\.\d{3} request_id=<32 hex>`.
- uri= is the requested path plus query.
- x_request_id= is the sent "client-sent-7" or "-".
- ua= is the sent agent.
- The request's own main line is `"<method> <url> HTTP/1.1" <code>`, and its request_id equals the pages line's. - expected: For every key: {"head": (method, str(code)), "uri": url, "x_request_id": sent or "-", "ua": "probe-agent/1", "main": (f"{method} {url} HTTP/1.1", str(code)), "same_request_id": True}. Observed: equal for all 32 under the plan's draft block (`about-good PASSED`). - excludes: A pages format that logs `uri="$uri"` instead of `$request_uri`. That records the rewritten try_files target and drops the query. Observed in the probe (`about-uri-var`): uri reads '/dev-pages/about.template.html' for ('HEAD', '/about', ...) and ('HEAD', '/about.html?x=1', None), red at :169. A request_id taken from `$http_x_request_id` would read "-" or "client-sent-7". That fails the 32-hex fullmatch, so "head" becomes the raw text and same_request_id becomes False.
- C2 - tests/tmp/test_21_static_page_visit_logs_phase2.py:181 — in one run, with both dev-pages files present, GETs to /about.html, /, /index.html, /api/health, /dev-pages/about.html and /dev-pages/about.template.html. For each URL it checks (status, the new main lines parsed to (request line, status), the new pages-line count) against the routes table: About gives 1 pages line, every other route gives 0. - expected: {'/about.html': (200, [('GET /about.html HTTP/1.1', '200')], 1), '/': (200, [('GET / HTTP/1.1', '200')], 0), '/index.html': (200, [...], 0), '/api/health': (502, [('GET /api/health HTTP/1.1', '502')], 0), '/dev-pages/about.html': (200, [...], 0), '/dev-pages/about.template.html': (200, [...], 0)}. Observed: equal under the draft block (`other-good PASSED`). In the checkpoint run the 5 non-About rows are already these values ("Omitting 5 identical items"), and only About's pages count differs. - excludes: The pages access_log put at server level, so every route writes it. Observed in the probe (`other-server-level`): '/', '/index.html', '/api/health' (502) and '/dev-pages/about.template.html' each read pages count 1, red at :181. With no pages log at all (the current block) the About row reads 0 instead of 1, so a dead pages file cannot pass either.

<assertions>
tests/tmp/test_21_static_page_visit_logs_phase2.py:88 — control: each swapped token (`root /var/www/peertube-browser;`, `/var/log/nginx/`, `listen 80;`, `127.0.0.1:7072`) is in the §6 block, so the run never binds port 80, writes /var/log or reaches a live Client backend; the upstream swap to a free, unbound port is what makes /api/health a deterministic 502 (C1/C2 precondition)
tests/tmp/test_21_static_page_visit_logs_phase2.py:92 — control: `nginx -t` exits 0 on the swapped, wrapped block (C1/C2 precondition)
tests/tmp/test_21_static_page_visit_logs_phase2.py:167 — for GET and HEAD on /about, /about/, /about.html and /about.html?x=1, each with and without X-Request-ID (16 requests per row), in the template-only row (200) and the no-files row (404): the answer status, plus exactly 1 new main-log line and exactly 1 new pages-log line per request. Counts are taken after polling until the main line lands, then a 0.1 s settle (C1)
tests/tmp/test_21_static_page_visit_logs_phase2.py:169 — for those same 32 requests: pages fields 1–8 fullmatch `page=about ts=\d+\.\d{3} time=<ISO 8601 with offset> ip=127.0.0.1 method=<sent method> status=<200|404> rt=\d+\.\d{3} request_id=<32 hex>`; after field 8, uri= is the requested path plus query (so /about stays /about after any rewrite), x_request_id= is the sent "client-sent-7" or "-", and ua= is the sent agent. The new main line is this request's (`"<method> <url> HTTP/1.1" <status>`), and its request_id equals the pages line's. The sent id is not 32 hex, so a request_id copied from the header fails (C1)
tests/tmp/test_21_static_page_visit_logs_phase2.py:180 — control: in the C2 run, GET /about.html first gives (200, 1 main line, 1 pages line), so the empty pages results below come from a live pages log and not a missing one (C2 precondition)
tests/tmp/test_21_static_page_visit_logs_phase2.py:181 — with both dev-pages files present, GET on /, /index.html, /api/health, /dev-pages/about.html and /dev-pages/about.template.html answers 200, 200, 502, 200 and 200. Each writes exactly one main line, whose request field and status are that request's, and no pages line (C2)
</assertions>

<probes>
1. tests/tmp/probe_21_pages_log.py (first version), run as `ValidateTests ["tests/tmp/probe_21_pages_log.py", "-s"]`. It spliced the plan's draft into the §6 block: the `log_format peertube_browser_pages 'page=$static_page ts=$msec time=$time_iso8601 ip=$remote_addr method=$request_method status=$status rt=$request_time request_id=$request_id uri="$request_uri" x_request_id=$http_x_request_id ua="$http_user_agent"'` line, plus `set` and both access_log lines in each About location. It then ran a real nginx (/usr/sbin/nginx), with the upstream port swapped to a free, refused one. Printed: `nginx -t 0`. Both log files exist at startup with the splice; without it, only peertube-browser.access.log exists. New lines are already in both files the moment the response is read (counts checked right after each request). Pages lines: `page=about ts=1790922456.465 time=2026-10-02T02:27:36-04:00 ip=127.0.0.1 method=GET status=200 rt=0.000 request_id=789126c6a00a590943652e019f01d4e2 uri="/about" x_request_id=- ua="-"`, then `... method=HEAD status=200 ... uri="/about.html?x=1" x_request_id=client-sent-7 ua="probe-agent/1"`, then `... method=HEAD status=404 ... uri="/about/" x_request_id=- ua="-"` with neither file present. Main lines: `127.0.0.1 - - [02/Oct/2026:02:27:36 -0400] "GET /about HTTP/1.1" 200 1201 "-" "-" request_id=789126c6a00a590943652e019f01d4e2 upstream=- rt=0.000` (same request_id as its pages line). `GET /api/health` gave 502 with `upstream=127.0.0.1:<refused port>`. `GET /`, `/dev-pages/about.template.html`: 200, with a main line and no pages line.
2. tests/tmp/probe_21_pages_log.py (second version), run as `ValidateTests ["tests/tmp/probe_21_pages_log.py", "-rA", "--tb=line"]`. It monkeypatched `_site_block` and called the real checkpoint functions. Printed: current block → about test FAILED at :167 `(200, 1, 0) != (200, 1, 1)`, other test FAILED at control :180 `(200, 1, 0) == (200, 1, 1)`. Draft splice → both PASSED. Pages-only access_log in About → FAILED :167 `(…, 0, 1)` and :180 `(200, 0, 1)`. `$uri` instead of `$request_uri` → about FAILED :169, other PASSED. Pages access_log added at server level → about PASSED, other FAILED :181 (pages lines for other routes). 6 failed, 4 passed in 100 s total.
Cleanup: I have no delete tool, so tests/tmp/probe_21_pages_log.py is still on disk and should be removed. It is not collected by pytest's default `test_*.py` pattern (pyproject sets no python_files).
</probes>

<unassertable>
none
</unassertable>

### `tests/tmp/test_21_static_page_visit_logs_phase2.py` - 11385 characters, inlined in full

````
"""The §6 nginx site block in DEPLOYMENT.md, run in a real nginx, writes exactly one pages-log line and one main-log line for every About request, sharing nginx's request_id, and no pages-log line for other routes.

- For GET and HEAD on /about, /about/, /about.html and /about.html?x=1, with and without an X-Request-ID header, answered 200 from the template or 404 with no dev-pages files: one new line in tmp/log/peertube-browser.pages.access.log and one in tmp/log/peertube-browser.access.log. The pages line's first eight fields are page=about, ts=<digits.3 digits>, time=<ISO 8601>, ip=127.0.0.1, method=, status=, rt=, request_id=<32 hex>; after them uri= is the requested path plus query, x_request_id= the sent header or -, ua= the sent User-Agent. The main line is that request's usual line and carries the same request_id.
- /, /index.html, /api/health (502, upstream refused), /dev-pages/about.html and /dev-pages/about.template.html each write one main line and no pages line, in a run where an About request does write one.

The block is the first ```nginx fence after the sites-available line. Its root, log directory, `listen 80` and upstream port are swapped for tmp paths, a free loopback port and a refused one, and it is wrapped in a minimal http{} with tmp temp paths. Skipped when nginx is missing or will not run unprivileged.
"""
from __future__ import annotations

import contextlib
import http.client
import re
import shutil
import socket
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DEPLOYMENT = ROOT / "DEPLOYMENT.md"
TEMPLATE = ROOT / "client" / "frontend" / "dev-pages" / "about.template.html"
NGINX = shutil.which("nginx")
SITE_LINE = "`/etc/nginx/sites-available/peertube-browser`:"
# What keeps the block from running unprivileged or reaching a live backend: the document root, the log directory, port 80 and the Client backend's port.
SWAPS = (("root /var/www/peertube-browser;", "root {www};"), ("/var/log/nginx/", "{log}/"), ("listen 80;", "listen 127.0.0.1:{port};"), ("127.0.0.1:7072", "127.0.0.1:{upstream}"))
ABOUT_URLS = ("/about", "/about/", "/about.html", "/about.html?x=1")
OTHER_ROUTES = {"/": 200, "/index.html": 200, "/api/health": 502, "/dev-pages/about.html": 200, "/dev-pages/about.template.html": 200}
# Not 32 hex digits, so a request_id copied from the header cannot pass for nginx's own.
SENT_ID = "client-sent-7"
AGENT = "probe-agent/1"
PAGES_HEAD = re.compile(r"page=about ts=\d+\.\d{3} time=\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d ip=127\.0\.0\.1 method=(\S+) status=(\S+) rt=\d+\.\d{3} request_id=([0-9a-f]{32})")
INDEX = b"<!doctype html><title>index</title>\n"
OVERRIDE = b"<!doctype html><title>dev-pages override</title>\n"


def _site_block() -> str:
    """The first ```nginx fence after the sites-available line of §6."""
    text = DEPLOYMENT.read_text(encoding="utf-8")
    assert SITE_LINE in text, f"{SITE_LINE} not in DEPLOYMENT.md"
    match = re.search(r"^```nginx\n(.*?)^```", text[text.index(SITE_LINE):], re.S | re.M)
    assert match, "no ```nginx fence after the sites-available line"
    return match.group(1)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _write_config(run_dir: Path, server_text: str) -> None:
    temp_paths = "".join(f"    {name}_temp_path {run_dir / name};\n" for name in ("client_body", "proxy", "fastcgi", "uwsgi", "scgi"))
    (run_dir / "nginx.conf").write_text(f"pid {run_dir / 'nginx.pid'};\ndaemon off;\nmaster_process off;\nevents {{}}\nhttp {{\n{temp_paths}    access_log {run_dir / 'log' / 'access.log'};\n{server_text}\n}}\n")


def _nginx_args(run_dir: Path, *extra: str) -> list[str]:
    return [NGINX, *extra, "-p", str(run_dir), "-e", str(run_dir / "error.log"), "-c", str(run_dir / "nginx.conf")]


def _require_unprivileged_nginx(tmp_path: Path) -> None:
    if NGINX is None:
        pytest.skip("nginx is not installed")
    run_dir = tmp_path / "unprivileged"
    (run_dir / "log").mkdir(parents=True)
    _write_config(run_dir, f"server {{ listen 127.0.0.1:{_free_port()}; }}")
    check = subprocess.run(_nginx_args(run_dir, "-t"), stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30)
    if check.returncode != 0:
        pytest.skip(f"nginx will not run unprivileged: {check.stderr}")


def _configure(tmp_path: Path, present: dict[str, bytes]) -> tuple[Path, int]:
    """Writes www (index.html plus the given dev-pages files) and the swapped, wrapped §6 block; returns the run directory and the listen port."""
    run_dir = tmp_path / "site"
    www = run_dir / "www"
    (www / "dev-pages").mkdir(parents=True)
    (run_dir / "log").mkdir()
    (www / "index.html").write_bytes(INDEX)
    for name, body in present.items():
        (www / "dev-pages" / name).write_bytes(body)
    port = _free_port()
    upstream = _free_port()
    while upstream == port:
        upstream = _free_port()
    server_text = _site_block()
    for old, new in SWAPS:
        assert old in server_text, f"{old!r} not in the §6 block"  # control: an unswapped token would bind port 80, write /var/log or reach a running backend
        server_text = server_text.replace(old, new.format(www=www, log=run_dir / "log", port=port, upstream=upstream))
    _write_config(run_dir, server_text)
    check = subprocess.run(_nginx_args(run_dir, "-t"), stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30)
    assert check.returncode == 0, check.stderr  # control: the block as published loads
    return run_dir, port


@contextlib.contextmanager
def _serving(run_dir: Path, port: int):
    proc = subprocess.Popen(_nginx_args(run_dir), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 10
        while True:
            if proc.poll() is not None:
                pytest.fail(f"nginx exited {proc.returncode}: {proc.stderr.read().decode()}\n{(run_dir / 'error.log').read_text()}")
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
                break
            except OSError:
                if time.monotonic() > deadline:
                    pytest.fail(f"nginx did not listen on {port} within 10 s")
                time.sleep(0.05)
        yield
    finally:
        proc.terminate()
        try:
            proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()


def _lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines() if path.exists() else []


def _request(run_dir: Path, port: int, method: str, url: str, headers: dict[str, str]) -> tuple[int, list[str], list[str]]:
    """Status, then the new main-log and pages-log lines: polled until the main line lands, then given a moment for any later access_log of the same request."""
    main_log = run_dir / "log" / "peertube-browser.access.log"
    pages_log = run_dir / "log" / "peertube-browser.pages.access.log"
    main_before, pages_before = len(_lines(main_log)), len(_lines(pages_log))
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request(method, url, headers=headers)
        resp = conn.getresponse()
        resp.read()
    finally:
        conn.close()
    deadline = time.monotonic() + 5
    while len(_lines(main_log)) == main_before and time.monotonic() < deadline:
        time.sleep(0.02)
    time.sleep(0.1)
    return resp.status, _lines(main_log)[main_before:], _lines(pages_log)[pages_before:]


def _main_request(line: str) -> tuple[str, ...] | str:
    """The request line and status of a main-log line in the peertube_browser format, else the line itself."""
    match = re.search(r'"([^"]*)" (\d{3}) ', line)
    return match.groups() if match else line


def _record(pages_line: str, main_line: str) -> dict[str, object]:
    fields = pages_line.split(" ")
    head = PAGES_HEAD.fullmatch(" ".join(fields[:8]))
    after = {key: value.strip('"') for key, _, value in (field.partition("=") for field in fields[8:])}
    main_id = re.search(r" request_id=(\S+) ", main_line)
    return {"head": head.groups()[:2] if head else " ".join(fields[:8]), "uri": after.get("uri"), "x_request_id": after.get("x_request_id"), "ua": after.get("ua"), "main": _main_request(main_line), "same_request_id": bool(head and main_id and main_id.group(1) == head.group(3))}


@pytest.mark.parametrize(("present", "code"), [pytest.param(("about.template.html",), 200, id="template-200"), pytest.param((), 404, id="no-files-404")])
def test_each_about_request_writes_one_pages_line_and_one_main_line_with_same_request_id(tmp_path: Path, present: tuple[str, ...], code: int) -> None:
    """GET and HEAD on /about, /about/, /about.html and /about.html?x=1, with and without X-Request-ID, answered 200 or 404: each adds one pages line (page=about, ts, ISO time, ip=127.0.0.1, method, status, rt, 32-hex request_id, then the requested uri, the sent X-Request-ID or -, the sent UA) and one main line for that request carrying the same request_id."""
    _require_unprivileged_nginx(tmp_path)
    run_dir, port = _configure(tmp_path, {name: TEMPLATE.read_bytes() for name in present})
    requests = [(method, url, sent) for url in ABOUT_URLS for method in ("GET", "HEAD") for sent in (None, SENT_ID)]
    with _serving(run_dir, port):
        got = {(method, url, sent): _request(run_dir, port, method, url, {"User-Agent": AGENT, **({"X-Request-ID": sent} if sent else {})}) for method, url, sent in requests}

    assert {key: (status, len(main), len(pages)) for key, (status, main, pages) in got.items()} == {key: (code, 1, 1) for key in requests}  # C1: one main line and one pages line per About request, at 200 and at 404
    records = {key: _record(pages[0], main[0]) for key, (_, main, pages) in got.items()}
    assert records == {(method, url, sent): {"head": (method, str(code)), "uri": url, "x_request_id": sent or "-", "ua": AGENT, "main": (f"{method} {url} HTTP/1.1", str(code)), "same_request_id": True} for method, url, sent in requests}  # C1: fields 1-8 fixed, uri as requested, x_request_id sent or -, and the main line of the same request shares the request_id


def test_other_routes_write_no_pages_line(tmp_path: Path) -> None:
    """In a run where GET /about.html writes one pages line and one main line, /, /index.html, /api/health (502), /dev-pages/about.html and /dev-pages/about.template.html each write one main line for that request and no pages line."""
    _require_unprivileged_nginx(tmp_path)
    run_dir, port = _configure(tmp_path, {"about.html": OVERRIDE, "about.template.html": TEMPLATE.read_bytes()})
    with _serving(run_dir, port):
        about = _request(run_dir, port, "GET", "/about.html", {})
        got = {url: _request(run_dir, port, "GET", url, {}) for url in OTHER_ROUTES}

    assert (about[0], len(about[1]), len(about[2])) == (200, 1, 1)  # control: the pages log is written in this run, so an empty one below is not a dead file
    assert {url: (status, [_main_request(line) for line in main], pages) for url, (status, main, pages) in got.items()} == {url: (code, [(f"GET {url} HTTP/1.1", str(code))], []) for url, code in OTHER_ROUTES.items()}  # C2: one main line for the request, no pages line

````


Gate: satisfied

## 2026-10-02 - Step 7 - Phase 2 (Pages log) - red (audit round 1)

`tests/tmp/test_21_static_page_visit_logs_phase2.py` exited 1.

```
  tests/tmp/test_21_static_page_visit_logs_phase2.py  3 failed                               0.0s
  --------------------------------------------------
  total                                               3 failed                               4.2s wall, 1 lane

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

## 2026-10-02 - Step 7 - Phase 2 (Pages log) - audit (round 1)

- AUDIT: devsecops-test-shape-auditor - PASS
- AUDIT: devsecops-test-claim-auditor - PASS
- OUTSTANDING: nothing

### devsecops-test-shape-auditor

SHAPE AUDIT — VERDICT: PASS

CRITICAL
none

RECOMMENDATIONS
none

PREDICTED FAILURE
Both parametrised cases of `test_each_about_request_writes_one_pages_line_and_one_main_line_with_same_request_id` should fail at line 167 on the count comparison. Every About request gives `(code, 1, 0)` where `(code, 1, 1)` is expected, because the current §6 block (DEPLOYMENT.md:414-470) has no pages log, so `peertube-browser.pages.access.log` is never written. `test_other_routes_write_no_pages_line` should fail at line 181 on the `/about.html` row only: it gets `(200, [("GET /about.html HTTP/1.1", "200")], 0)` where the expected pages count is `1`. Both tests skip, and do not fail, if nginx is missing or will not run unprivileged (lines 63-70).

NOT ASSESSED
1. `code_under_test` lists tests/active/test_static_page_visit_logs.py, but that path does not exist in the worktree. It was not read, and this verdict does not depend on it.
2. No `fixtures_path` was supplied. The test uses only pytest's built-in `tmp_path`, and no project fixture needed resolving.
3. Anti-pattern pass (rules/shape.md, each `<how_to_spot>`). No entry matches:
   - doc-lint-grep / whole-file-source-name-grep / section-scoped-substring-grep: lines 41, 43 and 88 check that a substring is present in DEPLOYMENT.md. Each one only guards the step that pulls out the nginx block (lines 41, 43) or the token swap (line 88). The pulled-out block is then loaded by `nginx -t` (line 92) and served for real. No assertion checks wording in place of behaviour.
   - hardcoded-spec-mirror: ABOUT_URLS and OTHER_ROUTES are request inputs. They are not compared for equality against a code constant.
   - tautological-assertion: expected values at lines 167, 169 and 181 are stated per key, such as `(code, 1, 1)`, `(method, str(code))` and `f"{method} {url} HTTP/1.1"`. None is worked out the way nginx works it out.
   - absence-only-assertion: the zero-pages-line claim at line 181 is paired in the same test with `/about.html` → `(200, 1)` (line 177), which serves as a positive control.
   - echoed-literal: `uri`, `x_request_id` and `ua` come back through the `log_format` that nginx runs, so the production config sits between input and assertion. SENT_ID (line 31) is not 32-hex, so if the pages log copied the incoming header into `request_id`, the regex at line 33 would reject it.
   - single-value-pin: the inputs vary across method (GET, HEAD), status (200, 404), four URLs and header present/absent. `same_request_id` compares two separate `access_log` lines, so a constant or header-copied id fails.
4. Ladder pass (rules/shape.md `<ladder>`, `<matching_rule>`): the test is at Rung 3. It starts real nginx as a subprocess with the published block and asserts on the log lines written. That is the right rung for an invariant about which log lines get written, it is not the anti-rung, and nothing was moved down a rung, so `<downshift_rule>` does not apply.
5. Stub question: these plausible wrong implementations would each turn the test red:
   - Leaving the current behaviour unchanged fails lines 167 and 181.
   - A pages `access_log` at server level fails line 181 on every non-About route.
   - A pages log in only one of the three About locations fails line 167 for the others.
   - A location-level pages `access_log` that drops the inherited main log fails line 167 (main count 0).
   - Using `$http_x_request_id` or a fixed id fails line 169.

### devsecops-test-claim-auditor

CLAIM AUDIT — VERDICT: PASS

CLAUSE MAP  (21 clauses: 7 must_prove, 9 docstring, 5 name)
| id | source | clause | assertion | excludes | status |
|---|---|---|---|---|---|
| C1a | must_prove | each About request writes exactly one pages-log line | :167 | No pages line. A duplicate line, for example from an About access_log plus a server-level one writing to the same file. Checked on all 16 requests at 200 and again at 404 | CARRIED |
| C1b | must_prove | each About request writes exactly one main-log line | :167 | An About access_log that replaces the main log it inherits from the server, leaving 0 main lines. Two main lines | CARRIED |
| C1c | must_prove | both lines carry the same request_id | :169 (`same_request_id: True` via `_record` :154-155) | A pages id taken from `$http_x_request_id` (SENT_ID is not 32 hex, and with no header the value is `-`). Lines whose ids differ. Lines paired across different requests | CARRIED |
| C1d | must_prove | "of any method" | :167 over GET and HEAD | Logging only GET. It does not exclude a GET/HEAD-only filter, because no other method is sent | CARRIED |
| C1e | must_prove | "or status" | :167 at 200 (template-200) and 404 (no-files-404) | Logging only 2xx. A filter that drops other statuses (for example 304 or 405) is not excluded | CARRIED |
| C2a | must_prove | /, /index.html, /api/ (as /api/health), /dev-pages/about.html and /dev-pages/about.template.html write no pages-log line | :181 (`len(pages)` == 0 per route, with the /about.html row at 1 as the contrast) | A pages log written at server level or for every route. A regex location such as `~ about` that also matches dev-pages. A run where nothing writes the pages log, caught by the contrast row | CARRIED |
| C2b | must_prove | and still write one main-log line each | :181 (exactly one main line per route, whose request line and status are that route's) | An access_log change that silences the main log for these routes. Two lines for one route. A line belonging to another request | CARRIED |
| D1 | docstring | "GET and HEAD on /about, /about/, /about.html and /about.html?x=1, with and without an X-Request-ID header … one new line in [pages log] and one in [main log]" | :167 | Any one of the 16 combinations writing 0 or 2 lines to either log | CARRIED |
| D2 | docstring | "answered 200 from the template or 404 with no dev-pages files" | :167 (status per parameter) | The wrong status. With only about.template.html present (:162), a 200 can come only from the template | CARRIED |
| D3 | docstring | "first eight fields are page=about, ts=…, time=<ISO 8601>, ip=127.0.0.1, method=, status=, rt=, request_id=<32 hex>" | :169 (`PAGES_HEAD.fullmatch` on fields[:8], groups compared to method and code) | A missing, reordered or misformatted field among the eight. The wrong method or status | CARRIED |
| D4 | docstring | "uri= is the requested path plus query" | :169 (`"uri": url`, which includes `?x=1`) | Logging `$uri` (the query is lost) or the rewritten try_files path | CARRIED |
| D5 | docstring | "x_request_id= the sent header or -" | :169 (`sent or "-"`) | Logging nginx's own id in that field, or dropping the client header | CARRIED |
| D6 | docstring | "ua= the sent User-Agent" | :169 (`"ua": AGENT`) | A missing or wrong UA field | CARRIED |
| D7 | docstring | "The main line is that request's usual line and carries the same request_id" | :169 (`"main"` request line and status, `same_request_id`) | A main line for a different request, or one in a format without the `"request" status` pair | CARRIED |
| D8 | docstring | "/, /index.html, /api/health (502, upstream refused), /dev-pages/about.html and /dev-pages/about.template.html each write one main line and no pages line" | :181 | Same as C2a and C2b. The 502 status is also compared | CARRIED |
| D9 | docstring | "in a run where an About request does write one" | :181 (row `/about.html: (200, 1)`) | A pages log that nothing writes passing the zero-line rows without being exercised | CARRIED |
| N1 | name | "each about request" | :167 | One URL, method or header variant missing the behaviour | CARRIED |
| N2 | name | "writes one pages line" | :167 | 0 or 2 pages lines | CARRIED |
| N3 | name | "and one main line" | :167 | 0 or 2 main lines | CARRIED |
| N4 | name | "with same request_id" | :169 | Ids that differ between the two lines | CARRIED |
| N5 | name | "other routes write no pages line" | :181 | A pages line on any listed non-About route | CARRIED |

CRITICAL
none

RECOMMENDATIONS
1. bounds (rules/testing.md): tests/tmp/test_21_static_page_visit_logs_phase2.py:163
   `requests = [(method, url, sent) for url in ABOUT_URLS for method in ("GET", "HEAD") for sent in (None, SENT_ID)]`
   C1 claims "any method or status", but the test only sends GET and HEAD and only gets 200 and 404. It never sends a method the static location refuses (for example POST, answered 405) or a conditional GET (304). So a log condition that keeps only GET/HEAD, or drops 3xx, would still pass. Consider adding one POST and one `If-Modified-Since` request to the About matrix.

OBSERVATIONS
none

NOT ASSESSED
1. `code_under_test` lists tests/active/test_static_page_visit_logs.py. That file does not exist, and no `tests/**/test_static_page_visit_logs*.py` matches either, so it was not read.
2. `code_under_test` says DEPLOYMENT.md was edited to add the peertube_browser_pages log_format, `set $static_page` and two access_log lines in the About location. None of these is in the §6 block as read (DEPLOYMENT.md:414-470). So the expected format of the pages-line fields (D3-D6) was judged from the test and `must_prove`, not checked against the code.

## 2026-10-02 - Step 7 - Phase 2 (Pages log) - checkpoint outcome (run 1)

`tests/tmp/test_21_static_page_visit_logs_phase2.py` exited 0 after the phase landed.

<changes>
### DEPLOYMENT.md
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
</changes>

<inner_tests>
none
</inner_tests>

<unanticipated>
tests/tmp/probe_pages_log.py — the throwaway probe described in changes. I have no tool to delete files, so I emptied it instead (pytest collects nothing from it). Please delete it.
</unanticipated>

<awaiting_operator>
none
</awaiting_operator>

```
  tests/tmp/test_21_static_page_visit_logs_phase2.py  3 passed                               0.0s
  --------------------------------------------------
  total                                               3 passed                               4.2s wall, 1 lane

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

## 2026-10-02 - Step 7 - Phase 3 (Runbook commands) - must_prove

Quoted from the phase Intent, written at Step 6 before the checkpoint was drafted.

Intent:
The shell commands in DEPLOYMENT.md's new "Follow an About visit" Triage subsection select About visits by field position and find a visit's Client request.start records by its IP and time window.

- C1 - The runbook's listing filter, which selects by field position, does not list a 404 About request whose user agent carries forged status=200, method=GET and page=about tokens as a successful GET.
- C2 - The runbook's correlation commands select exactly the visitor's in-window request.start record from real ClientLogFormatter output in both JSON and text modes.

must_prove:
- C1 - The runbook's listing filter, which selects by field position, does not list a 404 About request whose user agent carries forged status=200, method=GET and page=about tokens as a successful GET.
- C2 - The runbook's correlation commands select exactly the visitor's in-window request.start record from real ClientLogFormatter output in both JSON and text modes.

## 2026-10-02 - Step 7 - Phase 3 (Runbook commands) - self-check (audit round 1, send-back 0)

`tests/tmp/test_21_static_page_visit_logs_phase3.py`, surface `checkpoint`. Collection exit 0.

- C1 - tests/tmp/test_21_static_page_visit_logs_phase3.py:252: every runbook line that names peertube-browser.pages.access.log and contains GET and 200 (comments left out) is run under bash against the pages log a real nginx wrote. Each must print exactly the one GET /about.html 200 line. It must not print the HEAD /about 200 line or the GET /about/ 404 whose UA carries " status=200 method=GET page=about ". If there are no such lines, the result is {}, which is compared against a placeholder key and fails here as well. - expected: {filter_line: [the real GET /about.html 200 pages line]} for each filter line. Observed: I put the plan's draft runbook (plan §8) into a copy of DEPLOYMENT.md and the test passed (`test_probe[draft-test_forged_user_agent_does_not_move_fields] PASSED`). The only filter line was `sudo awk '$1 == "page=about" && $5 == "method=GET" && $6 == "status=200"' …`. On the current DEPLOYMENT.md, which has no runbook section, it reads {} against {'<a runbook line filtering the pages log for GET and 200>': [the GET line]}, and the test goes red at :252. - excludes: A substring filter, `sudo grep '^page=about ' … | grep ' method=GET ' | grep ' status=200 '`. Observed in the probe: that line printed two lines, the real GET 200 line and the forged `… method=GET status=404 … ua="forger/1 status=200 method=GET page=about forger/1"` line. The test was red at :252.
- C2 - tests/tmp/test_21_static_page_visit_logs_phase3.py:291: in JSON mode, the whole runbook runs with the visit's request_id substituted, journalctl printing real ClientLogFormatter JSON output, and TZ=EST5. The Client records it prints must be exactly [the request.start record of rid-match]: from 1.2.3.4, 10 s after the visit. They must not include rid-before (−60 s), rid-late (+3600 s) or rid-neighbour (1.2.3.45, +20 s). - expected: [{'ts': '2023-11-14T22:13:30.123Z', 'service': 'client-backend', 'event': 'request.start', 'request_id': 'rid-match', 'context': {'ip': '1.2.3.4', …}}]. Observed: the plan's draft runbook passes. On the current DEPLOYMENT.md the output is [] and the test is red at :291. - excludes: Each of these was observed in the probe and each went red at :291. `date -d` without `-u`: [], because the window lands five hours off. Taking the visit with `tail -n 1` instead of matching on request_id: [the rid-neighbour record from 1.2.3.45]. Dropping `.context.ip == $ip` from jq: [rid-match, rid-neighbour]. Dropping the upper bound `.ts <= $to`: [rid-match, rid-late (2023-11-14T23:13:20.123Z)].
- C2 - tests/tmp/test_21_static_page_visit_logs_phase3.py:292: the same run in text mode, with real ClientLogFormatter text lines. The Client lines it prints must be exactly [the rid-match request.start line]. - expected: ['2023-11-14T22:13:30.123Z INFO request.start request started ip=1.2.3.4 method=GET url=http://127.0.0.1:7072/api/videos user_agent=Mozilla/5.0 (X11; Linux x86_64) request_id=rid-match']. Observed: this is the exact line the probe printed, and the plan's draft runbook passes here. - excludes: A text filter with no delimiter, `grep -F "ip=$ip"`. Observed in the probe: it printed the rid-match line and also the `ip=1.2.3.45 … request_id=rid-neighbour` line, and the test was red at :292 while :291 (JSON) passed. That shows the two modes are judged separately.

<assertions>
tests/tmp/test_21_static_page_visit_logs_phase3.py:139: control. Each swapped token (root, /var/log/nginx/, listen 80, 127.0.0.1:7072) is in the §6 block, so the nginx run never binds port 80, writes /var/log or reaches a live backend (precondition for C1).
tests/tmp/test_21_static_page_visit_logs_phase3.py:143: control. `nginx -t` exits 0 on the swapped, wrapped block (precondition for C1).
tests/tmp/test_21_static_page_visit_logs_phase3.py:241: control. GET /about.html (template present), HEAD /about (template present) and GET /about/ with the forged UA (template removed) answer 200, 200 and 404, and each writes exactly one pages line (precondition for C1).
tests/tmp/test_21_static_page_visit_logs_phase3.py:243: control. The 404 line contains " status=200 method=GET page=about ". The forged tokens reach the log space-delimited, so a substring grep for ' status=200 ' / ' method=GET ' would match this 404 (precondition for C1).
tests/tmp/test_21_static_page_visit_logs_phase3.py:245: The forged 404 request's pages line has whitespace field 6 (awk $6) == "status=404". The forged UA does not shift the fixed fields (C1).
tests/tmp/test_21_static_page_visit_logs_phase3.py:248: control. At least one runbook line (from the ```bash fences under `### Follow an About visit`, comments excluded) names peertube-browser.pages.access.log and contains GET and 200 (precondition for C1).
tests/tmp/test_21_static_page_visit_logs_phase3.py:250: Each such line is run under bash against the real nginx pages log (sudo shim, /var/log/nginx/ swapped to the tmp log dir) and prints exactly [the real GET /about.html 200 line]. It does not print the forged GET 404 line or the HEAD 200 line (C1).
tests/tmp/test_21_static_page_visit_logs_phase3.py:260: control. In the sandbox, `date -d @0 +%H` prints 19. TZ is five hours behind UTC, so a from/to conversion without `date -u` misses the window (precondition for C2).
tests/tmp/test_21_static_page_visit_logs_phase3.py:274: control. The runbook has exactly one `name=<…>` placeholder line, and it gets the visit's request_id. That id is the runbook's only input, so ip and ts must be derived from the pages log (precondition for C2).
tests/tmp/test_21_static_page_visit_logs_phase3.py:280: control. The real ClientLogFormatter, run in a child with cwd=client/backend, renders all 8 request.start/request.end records, and each one is recognised as a Client record (JSON with service=client-backend, or a text line with a leading ts). An empty selection therefore means the runbook selected nothing, not that the test failed to recognise the records (precondition for C2).
tests/tmp/test_21_static_page_visit_logs_phase3.py:288: The pages log has 3 visits: 198.51.100.9 at V-120 s, 1.2.3.4 at V with the given id, and 1.2.3.45 at V+15 s. The client log has request.start records from 1.2.3.4 at V-60 s, V+10 s and V+3600 s, and from 1.2.3.45 at V+20 s, each followed by its request.end. The whole runbook runs with journalctl → `cat <JSON client log>` and prints exactly one Client record, the 1.2.3.4 V+10 s request.start, compared as parsed JSON with the formatter's own line (C2).
tests/tmp/test_21_static_page_visit_logs_phase3.py:289: The same setup with journalctl → `cat <text client log>` prints exactly [the formatter's text line for the 1.2.3.4 V+10 s request.start] (C2).
</assertions>

<probes>
1. Forged UA and the nginx pages line. tests/tmp/test_probe_21_p3.py ran through ValidateTests with `-s`, reusing the phase-2 nginx harness. GET /about.html with UA probe-agent/1 logged `page=about ts=1790923269.845 time=2026-10-02T02:41:09-04:00 ip=127.0.0.1 method=GET status=200 rt=0.000 request_id=9d52… uri=/about.html x_request_id="-" ua="probe-agent/1"`. With Step 6's literal UA ` status=200 method=GET page=about` (leading space), the line was `… status=404 … ua="status=200 method=GET page=about"`. nginx strips the leading space, so `status=200` is glued to `ua="` and an unanchored `grep ' status=200 '` would NOT be fooled. That UA cannot tell a positional filter from the grep. The checkpoint therefore sends `forger/1 status=200 method=GET page=about forger/1`, which logged `… method=GET status=404 … ua="forger/1 status=200 method=GET page=about forger/1"`. Its split() gave $6 = 'status=404', and the forged tokens appear space-delimited.
2. ClientLogFormatter output. A child with cwd=client/backend did `import server`, set REQUEST_CONTEXT.request_id='rid-1', built a makeLogRecord with created=1700000010.123, client_event=request.start and a context, and formatted it in both modes. JSON gave `{"ts":"2023-11-14T22:13:30.123Z","level":"INFO","service":"client-backend","event":"request.start","message":"request started","request_id":"rid-1","context":{"ip":"1.2.3.4",…}}`. Text gave `2023-11-14T22:13:30.123Z INFO request.start request started ip=1.2.3.4 method=GET url=… user_agent=Mozilla/5.0 (X11) request_id=rid-1`. So created=V+10 renders .123 exactly.
3. Tools. bash, jq, awk (GNU Awk 5.3.2), grep and cat are at /usr/bin. `date --version` prints `date (uutils coreutils) 0.8.0`, which is NOT GNU. A skip on "no GNU date", as Step 6 worded it, would therefore skip the C2 test on this host. The checkpoint instead skips only when `date -u -d @1700000000.123 +%Y-%m-%dT%H:%M:%S` does not print 2023-11-14T22:13:20. Finding for the implementer: uutils ignores the width in `%3N`. With TZ=EST5, `date -u -d @1700000000.123 +%Y-%m-%dT%H:%M:%S.%3NZ` printed `2023-11-14T22:13:20.123000000Z` (9 digits), and without -u it printed `2023-11-14T17:13:20.123000000Z`. String comparison against the apps' `.mmmZ` still orders correctly except at the exact upper-bound millisecond, so the checkpoint's offsets (-60 s, +10 s, +20 s, +3600 s) avoid ms-boundary cases and select the same records under GNU and uutils date.
4. The checkpoint against a right runbook and wrong ones. tests/tmp/test_probe_21_p3.py monkeypatched the module's DEPLOYMENT to a tmp copy with the plan's §8 draft inserted before "Centralized installer (source of truth):", then ran both tests.
   - Right draft: both PASSED.
   - Listing as `grep '^page=about ' | grep ' method=GET ' | grep ' status=200 '`: C1 test FAILED at :250, listing the forged 404 line. C2 passed.
   - from/to without `-u`: FAILED at :288 (JSON selected []).
   - Text `grep -F "ip=$ip"` without the trailing space: FAILED at :289 (also selected rid-neighbour).
   - jq without `.context.ip == $ip`: FAILED at :288 (selected match + neighbour).
   - Visit line taken with `tail -n 1` instead of `$8 == id`: FAILED at :288 (selected the 22:13:40 neighbour record).
   - Current DEPLOYMENT.md (no subsection): FAILED at :75, `### Follow an About visit not in DEPLOYMENT.md` (the red expected now).
   In every run, the section runs to the next heading, which today means it takes in the "Centralized installer" bash fences. Their `sudo bash scripts/…` lines printed `bash: command not found`, because the sandbox PATH holds only awk, grep, cat, jq, date, sed, cut, tr, head, tail and sort, and cwd is tmp. The run showed the installers cannot execute. I have no delete tool, so I emptied the probe file tests/tmp/test_probe_21_p3.py (it collects nothing). Please delete it.
</probes>

<unassertable>
none. Both clauses are carried. Deviations from the Step 6 wording, each forced by an observation above: (a) the forged UA has a non-space prefix, because nginx strips a leading space, and Step 6's literal UA would leave a substring grep unfooled; (b) the C2 skip checks for a `date` that converts `-u -d @<epoch.ms>` rather than for GNU date, because this host has uutils date and a GNU-only skip would never run C2 here. Design constraints the checkpoint puts on the runbook: (c) the GET/200 listing is found as the runbook line(s) that name peertube-browser.pages.access.log and contain GET and 200; (d) the visit's request_id is the runbook's only operator input, given as exactly one `name=<…>` line, so ip and ts are derived from the pages log; (e) jq output must be one record per line (-c). Not pinned: the "late" decoy sits at +1 h, outside any window up to an hour, because the doc's window size (planned as 5 min) is not read by the test. Not asserted, because no Client event other than request.start carries `ip`: that a non-request.start record from the visitor's IP inside the window is excluded.
</unassertable>

### `tests/tmp/test_21_static_page_visit_logs_phase3.py` - 16804 characters, inlined in full

````
"""The shell commands under "Follow an About visit" in DEPLOYMENT.md list About visits by field position and find a visit's Client request.start record by its address and a time window after it.

- In a real nginx running the §6 block, a GET /about.html (200), a HEAD /about (200) and a GET /about/ answered 404 whose User-Agent carries ` status=200 method=GET page=about ` each write a pages line; the forged one keeps `status=404` as its sixth field, and every runbook line that filters the pages log for GET and 200 prints exactly the real GET line.
- With a pages log of three visits and Client request.start/request.end records rendered by the real ClientLogFormatter, the runbook, given the visit's request_id, prints exactly the record from the visit's address 10 s after it, in JSON and in text: not the one 60 s before, the one 1 h after, nor the one 20 s after from 1.2.3.45.

The runbook is every ```bash fence between `### Follow an About visit` and the next heading, run under bash with `/var/log/nginx/` swapped for a tmp directory, `sudo` running its command, `journalctl` printing the tmp Client log, TZ five hours behind UTC, and only text tools on PATH. Its one `name=<…>` placeholder line gets the visit's request_id. Skipped when nginx, bash, jq, awk or a `date` that reads `-u -d @<epoch.ms>` is missing.
"""
from __future__ import annotations

import contextlib
import http.client
import json
import re
import shutil
import socket
import subprocess
import sys
import textwrap
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DEPLOYMENT = ROOT / "DEPLOYMENT.md"
TEMPLATE = ROOT / "client" / "frontend" / "dev-pages" / "about.template.html"
BACKEND_DIR = ROOT / "client" / "backend"
NGINX = shutil.which("nginx")
BASH = shutil.which("bash")
SITE_LINE = "`/etc/nginx/sites-available/peertube-browser`:"
RUNBOOK_HEADING = "### Follow an About visit"
# What keeps the block from running unprivileged or reaching a live backend: the document root, the log directory, port 80 and the Client backend's port.
SWAPS = (("root /var/www/peertube-browser;", "root {www};"), ("/var/log/nginx/", "{log}/"), ("listen 80;", "listen 127.0.0.1:{port};"), ("127.0.0.1:7072", "127.0.0.1:{upstream}"))
# The runbook's commands get these and nothing else, so an installer line that falls inside the section cannot run.
TOOLS = ("awk", "grep", "cat", "jq", "date", "sed", "cut", "tr", "head", "tail", "sort")
AGENT = "probe-agent/1"
# Prefixed: nginx strips a header value's leading space, which would glue the first forged token to `ua="` (observed).
FORGED_UA = "forger/1 status=200 method=GET page=about forger/1"
# POSIX zone, no tzdata needed: a conversion without `date -u` lands five hours off.
LOCAL_TZ = "EST5"
VISIT_ID = "5f0c1d2e3a4b5c6d7e8f90a1b2c3d4e5"
VISIT_MS = 1700000000123
VISIT_IP = "1.2.3.4"
# A neighbour whose address has the visitor's as a prefix: `ip=1.2.3.4` without a delimiter matches it.
NEIGHBOUR_IP = "1.2.3.45"
TS_HEAD = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z ")

# Renders each record through the Client's own formatter, with the request id it would read from REQUEST_CONTEXT.
_FORMAT_CHILD = textwrap.dedent(
    """
    import json, logging, sys
    import server
    log_format, records = json.loads(sys.argv[1])
    formatter = server.ClientLogFormatter(log_format)
    for created, event, message, request_id, context in records:
        server.REQUEST_CONTEXT.request_id = request_id
        print(formatter.format(logging.makeLogRecord({"msg": message, "levelno": logging.INFO, "levelname": "INFO", "created": created, "client_event": event, "client_context": context})))
    """
)


def _site_block() -> str:
    """The first ```nginx fence after the sites-available line of §6."""
    text = DEPLOYMENT.read_text(encoding="utf-8")
    assert SITE_LINE in text, f"{SITE_LINE} not in DEPLOYMENT.md"
    match = re.search(r"^```nginx\n(.*?)^```", text[text.index(SITE_LINE):], re.S | re.M)
    assert match, "no ```nginx fence after the sites-available line"
    return match.group(1)


def _runbook() -> list[str]:
    """The ```bash fences between the runbook heading and the next heading outside a fence, backslash-continued lines joined."""
    lines = DEPLOYMENT.read_text(encoding="utf-8").splitlines()
    assert RUNBOOK_HEADING in lines, f"{RUNBOOK_HEADING} not in DEPLOYMENT.md"
    blocks, fence, body = [], None, []
    for line in lines[lines.index(RUNBOOK_HEADING) + 1:]:
        if fence is None:
            if re.match(r"#{1,6} ", line):
                break
            if line.startswith("```"):
                fence, body = line[3:].strip(), []
        elif line.startswith("```"):
            if fence == "bash":
                blocks.append("\n".join(body).replace("\\\n", ""))
            fence = None
        else:
            body.append(line)
    return blocks


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _write_config(run_dir: Path, server_text: str) -> None:
    temp_paths = "".join(f"    {name}_temp_path {run_dir / name};\n" for name in ("client_body", "proxy", "fastcgi", "uwsgi", "scgi"))
    (run_dir / "nginx.conf").write_text(f"pid {run_dir / 'nginx.pid'};\ndaemon off;\nmaster_process off;\nevents {{}}\nhttp {{\n{temp_paths}    access_log {run_dir / 'log' / 'access.log'};\n{server_text}\n}}\n")


def _nginx_args(run_dir: Path, *extra: str) -> list[str]:
    return [NGINX, *extra, "-p", str(run_dir), "-e", str(run_dir / "error.log"), "-c", str(run_dir / "nginx.conf")]


def _require_unprivileged_nginx(tmp_path: Path) -> None:
    if NGINX is None:
        pytest.skip("nginx is not installed")
    run_dir = tmp_path / "unprivileged"
    (run_dir / "log").mkdir(parents=True)
    _write_config(run_dir, f"server {{ listen 127.0.0.1:{_free_port()}; }}")
    check = subprocess.run(_nginx_args(run_dir, "-t"), stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30)
    if check.returncode != 0:
        pytest.skip(f"nginx will not run unprivileged: {check.stderr}")


def _require_tools(*tools: str) -> None:
    missing = [tool for tool in ("bash", *tools) if shutil.which(tool) is None]
    if missing:
        pytest.skip(f"not installed: {', '.join(missing)}")


def _configure(tmp_path: Path, present: dict[str, bytes]) -> tuple[Path, int]:
    """Writes www (an index.html plus the given dev-pages files) and the swapped, wrapped §6 block; returns the run directory and the listen port."""
    run_dir = tmp_path / "site"
    www = run_dir / "www"
    (www / "dev-pages").mkdir(parents=True)
    (run_dir / "log").mkdir()
    (www / "index.html").write_bytes(b"<!doctype html><title>index</title>\n")
    for name, body in present.items():
        (www / "dev-pages" / name).write_bytes(body)
    port = _free_port()
    upstream = _free_port()
    while upstream == port:
        upstream = _free_port()
    server_text = _site_block()
    for old, new in SWAPS:
        assert old in server_text, f"{old!r} not in the §6 block"  # control: an unswapped token would bind port 80, write /var/log or reach a running backend
        server_text = server_text.replace(old, new.format(www=www, log=run_dir / "log", port=port, upstream=upstream))
    _write_config(run_dir, server_text)
    check = subprocess.run(_nginx_args(run_dir, "-t"), stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30)
    assert check.returncode == 0, check.stderr  # control: the block as published loads
    return run_dir, port


@contextlib.contextmanager
def _serving(run_dir: Path, port: int):
    proc = subprocess.Popen(_nginx_args(run_dir), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 10
        while True:
            if proc.poll() is not None:
                pytest.fail(f"nginx exited {proc.returncode}: {proc.stderr.read().decode()}\n{(run_dir / 'error.log').read_text()}")
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
                break
            except OSError:
                if time.monotonic() > deadline:
                    pytest.fail(f"nginx did not listen on {port} within 10 s")
                time.sleep(0.05)
        yield
    finally:
        proc.terminate()
        try:
            proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()


def _lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines() if path.exists() else []


def _request(run_dir: Path, port: int, method: str, url: str, headers: dict[str, str]) -> tuple[int, list[str]]:
    """Status and the new pages-log lines: polled until the request's main-log line lands, then given a moment for any later access_log of the same request."""
    main_log = run_dir / "log" / "peertube-browser.access.log"
    pages_log = run_dir / "log" / "peertube-browser.pages.access.log"
    main_before, pages_before = len(_lines(main_log)), len(_lines(pages_log))
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request(method, url, headers=headers)
        resp = conn.getresponse()
        resp.read()
    finally:
        conn.close()
    deadline = time.monotonic() + 5
    while len(_lines(main_log)) == main_before and time.monotonic() < deadline:
        time.sleep(0.02)
    time.sleep(0.1)
    return resp.status, _lines(pages_log)[pages_before:]


def _bash(work_dir: Path, log_dir: Path, script: str, client_log: Path | None = None) -> subprocess.CompletedProcess:
    """Runs script in work_dir under bash, /var/log/nginx/ read from log_dir, with `sudo` running its command, `journalctl` printing client_log, TZ=EST5 and only TOOLS on PATH."""
    bin_dir = work_dir / "bin"
    if not bin_dir.exists():
        bin_dir.mkdir()
        for tool in TOOLS:
            if shutil.which(tool):
                (bin_dir / tool).symlink_to(shutil.which(tool))
    prelude = 'sudo() { "$@"; }\njournalctl() { cat "$CLIENT_LOG"; }\n'
    env = {"PATH": str(bin_dir), "TZ": LOCAL_TZ, "CLIENT_LOG": str(client_log or "/dev/null")}
    return subprocess.run([BASH, "-c", prelude + script.replace("/var/log/nginx/", f"{log_dir}/")], cwd=work_dir, env=env, capture_output=True, text=True, timeout=60)


def _pages_line(ms: int, ip: str, request_id: str) -> str:
    """A pages-log line as §6's peertube_browser_pages writes it (observed in phase 2), for a GET /about.html answered 200 on a host five hours behind UTC."""
    local = datetime.fromtimestamp(ms // 1000, tz=timezone(timedelta(hours=-5))).isoformat()
    return f'page=about ts={ms // 1000}.{ms % 1000:03d} time={local} ip={ip} method=GET status=200 rt=0.000 request_id={request_id} uri=/about.html x_request_id="-" ua="Mozilla/5.0 (X11; Linux x86_64)"'


def _client_lines(log_format: str, records: list[list]) -> list[str]:
    run = subprocess.run([sys.executable, "-c", _FORMAT_CHILD, json.dumps([log_format, records])], cwd=BACKEND_DIR, capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stderr[-2000:]
    return run.stdout.splitlines()


def _client_record(line: str) -> object | None:
    """A Client JSON record as a dict, a Client text line as itself, anything else (pages or access-log lines the runbook prints) as None."""
    if TS_HEAD.match(line):
        return line
    try:
        parsed = json.loads(line)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) and parsed.get("service") == "client-backend" else None


def test_forged_user_agent_does_not_move_fields(tmp_path: Path) -> None:
    """A GET /about/ answered 404 whose User-Agent carries space-delimited status=200, method=GET and page=about tokens keeps status=404 as its pages line's sixth field, and every runbook line filtering the pages log for GET and 200 prints only the real GET /about.html 200 line, not that one nor a HEAD /about 200."""
    _require_tools("awk", "grep", "cat")
    _require_unprivileged_nginx(tmp_path)
    run_dir, port = _configure(tmp_path, {"about.template.html": TEMPLATE.read_bytes()})
    with _serving(run_dir, port):
        get = _request(run_dir, port, "GET", "/about.html", {"User-Agent": AGENT})
        head = _request(run_dir, port, "HEAD", "/about", {"User-Agent": AGENT})
        (run_dir / "www" / "dev-pages" / "about.template.html").unlink()
        forged = _request(run_dir, port, "GET", "/about/", {"User-Agent": FORGED_UA})
    assert [(status, len(pages)) for status, pages in (get, head, forged)] == [(200, 1), (200, 1), (404, 1)]  # control: one pages line each, the forged one a 404
    forged_line = forged[1][0]
    assert " status=200 method=GET page=about " in forged_line, forged_line  # control: the forged tokens reached the log space-delimited, so a substring grep for ' status=200 ' or ' method=GET ' matches this 404

    assert forged_line.split()[5] == "status=404", forged_line  # C1

    filters = [line for block in _runbook() for line in block.splitlines() if "peertube-browser.pages.access.log" in line and "GET" in line and "200" in line and not line.lstrip().startswith("#")]
    assert filters, "no runbook command filters the pages log for GET and 200"  # control
    listed = {line: _bash(tmp_path, run_dir / "log", line) for line in filters}
    assert {line: run.stdout.splitlines() for line, run in listed.items()} == {line: get[1] for line in filters}, {line: run.stderr for line, run in listed.items()}  # C1


def test_runbook_finds_visit_and_client_record(tmp_path: Path) -> None:
    """Given the visit's request_id, the runbook prints exactly the Client request.start record from the visit's address 10 s after it, in JSON and in text: not the one 60 s before, the one 1 h after, nor the one 20 s after from 1.2.3.45 (the address of a later visit in the same pages log)."""
    _require_tools("awk", "grep", "cat", "jq", "date")
    log_dir = tmp_path / "log"
    log_dir.mkdir()
    if _bash(tmp_path, log_dir, "date -u -d @1700000000.123 +%Y-%m-%dT%H:%M:%S").stdout.strip() != "2023-11-14T22:13:20":
        pytest.skip("date does not convert -u -d @<epoch.ms>")
    assert _bash(tmp_path, log_dir, "date -d @0 +%H").stdout.strip() == "19"  # control: the runbook runs five hours behind UTC, so a conversion without -u misses the window

    # The visit sits between two others; the later one comes from the neighbour's address, so taking the last line, or every line, selects the neighbour.
    pages = [_pages_line(VISIT_MS - 120_000, "198.51.100.9", "a" * 32), _pages_line(VISIT_MS, VISIT_IP, VISIT_ID), _pages_line(VISIT_MS + 15_000, NEIGHBOUR_IP, "b" * 32)]
    (log_dir / "peertube-browser.pages.access.log").write_text("\n".join(pages) + "\n")
    (log_dir / "peertube-browser.access.log").write_text("")
    starts = {"before": (-60, VISIT_IP), "match": (10, VISIT_IP), "neighbour": (20, NEIGHBOUR_IP), "late": (3600, VISIT_IP)}
    records = []
    for name, (offset, ip) in starts.items():
        created = VISIT_MS / 1000 + offset
        records.append([created, "request.start", "request started", f"rid-{name}", {"ip": ip, "method": "GET", "url": "http://127.0.0.1:7072/api/videos", "user_agent": "Mozilla/5.0 (X11; Linux x86_64)"}])
        records.append([created + 0.05, "request.end", "request finished", f"rid-{name}", {"status": 200, "duration_ms": 50}])

    script, placeholders = re.subn(r"^(\w+)=<[^<>\n]+>$", rf"\g<1>={VISIT_ID}", "\n".join(_runbook()), flags=re.M)
    assert placeholders == 1, f"expected one `name=<…>` line for the visit's request_id, found {placeholders}"  # control: the runbook's only input is the visit's id

    match = next(index for index, record in enumerate(records) if record[1] == "request.start" and record[3] == "rid-match")
    expected, got, stderr = {}, {}, {}
    for log_format in ("json", "text"):
        lines = _client_lines(log_format, records)
        assert len(lines) == len(records) and all(_client_record(line) is not None for line in lines), lines  # control: every rendered record is recognised as a Client record in the runbook's output
        client_log = tmp_path / f"client.{log_format}.log"
        client_log.write_text("\n".join(lines) + "\n")
        run = _bash(tmp_path, log_dir, script, client_log)
        expected[log_format] = [_client_record(lines[match])]
        got[log_format] = [record for record in map(_client_record, run.stdout.splitlines()) if record is not None]
        stderr[log_format] = run.stderr[-2000:]

    assert got["json"] == expected["json"], stderr["json"]  # C2
    assert got["text"] == expected["text"], stderr["text"]  # C2

````


Gate: satisfied

## 2026-10-02 - Step 7 - Phase 3 (Runbook commands) - red (audit round 1)

`tests/tmp/test_21_static_page_visit_logs_phase3.py` exited 1.

```
  tests/tmp/test_21_static_page_visit_logs_phase3.py  2 failed                               0.0s
  --------------------------------------------------
  total                                               2 failed                               0.7s wall, 1 lane

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

## 2026-10-02 - Step 7 - Phase 3 (Runbook commands) - audit (round 1)

- AUDIT: devsecops-test-shape-auditor - PASS
- AUDIT: devsecops-test-claim-auditor - BLOCK
- OUTSTANDING: 3 UNCARRIED clause(s) - C1c, D1, D2b; devsecops-test-claim-auditor: critical

### devsecops-test-shape-auditor

SHAPE AUDIT — VERDICT: PASS

CRITICAL
none

RECOMMENDATIONS
1. No rule in rules/shape.md covers this — tests/tmp/test_21_static_page_visit_logs_phase3.py:249
   filters = [line for block in _runbook() for line in block.splitlines() if "peertube-browser.pages.access.log" in line and "GET" in line and "200" in line and not line.lstrip().startswith("#")]
   The C1 check runs only the runbook lines that literally contain the pages-log path, `GET` and `200`. It also runs each of those lines on its own in a separate bash. Two kinds of filter never run:
   - A filter that names the log through a variable (`"$PAGES"`) or puts its pipeline on several lines without backslashes. If no line matches at all, line 252 fails on the placeholder key, so a missing filter is still caught. But if some other line does match, the test passes without ever running the skipped filter, even a substring-grep one.
   - A line that needs a variable set earlier in the block.
   Picking which commands to run by the author's wording is close in spirit to doc-lint-grep, but that entry does not cover it: the selected lines are executed, not grepped. Running the C1 filter the way the C2 test runs its commands would close the gap: the whole fenced block as one script, with the path swapped.

PREDICTED FAILURE
DEPLOYMENT.md has no `### Follow an About visit` heading, so `_runbook()` returns `[]`. `test_forged_user_agent_does_not_move_fields` gets through its controls at lines 243/245/247, then fails at line 252: `{}` does not equal `{"<a runbook line filtering the pages log for GET and 200>": [<the GET /about.html 200 pages line>]}`. `test_runbook_finds_visit_and_client_record` passes the control at line 277 (`not runbook`), runs an empty script, and fails at line 291: `got["json"] == []` does not equal `expected["json"] == [<the rid-match request.start dict>]`. Both tests skip instead if nginx cannot run unprivileged, or if jq or a `date -u -d @<epoch.ms>` is missing.

NOT ASSESSED
1. `fixtures_path` is "none found", and the test defines everything it uses itself, so there was no fixture to check.
2. tests/active/test_static_page_visit_logs.py is listed in `code_under_test` but nothing in this test imports or runs it, so I didn't read it.
3. I did not open the body of `ClientLogFormatter` (client/backend/server.py:166). I confirmed the class exists and that `REQUEST_CONTEXT` is defined in client/backend/lib/engine_api_client.py:15. I did not check whether `server.REQUEST_CONTEXT` resolves the way `_FORMAT_CHILD` expects. If it doesn't, the control at line 218 fails before C2 is reached.

Notes on the passes (not findings):
- Ladder: both tests are at rung 2. They take the runbook's ```bash fences and run them as subprocesses. Their input is a real nginx running the §6 block (C1), or records rendered by the production `ClientLogFormatter` (C2). They check stdout. That is the highest rung a shell runbook supports. The markdown is parsed to get the commands to run, not grepped, so the anti-rung does not apply and no downshift is involved.
- Anti-patterns: none apply.
  - The expected values are independent: real nginx output and real formatter output.
  - Every claim assertion is positive and non-empty, and an absent runbook fails it.
  - C1 has three inputs (GET 200, HEAD 200, forged 404).
  - C2 has four candidates (−60 s, +10 s, the neighbour's +20 s at the prefix address, +1 h) checked in two formats, with the timezone control at line 262.
- Stub question: none of these would pass:
  - a missing runbook
  - a substring grep for `status=200`/`method=GET`
  - `tail -1`, or printing every line
  - an `ip=1.2.3.4` match without a delimiter
  - a time conversion without `-u`

### devsecops-test-claim-auditor

CLAIM AUDIT — VERDICT: BLOCK

CLAUSE MAP  (25 clauses: 10 must_prove, 12 docstring, 3 name)
| id | source | clause | assertion | excludes | status |
|---|---|---|---|---|---|
| C1a | must_prove | "does not list a 404 About request whose user agent carries forged status=200, method=GET and page=about tokens as a successful GET" | :252 | a substring grep for ` status=200 ` or ` method=GET `. The control at :245 shows the forged tokens reached the line space-delimited, so such a grep would list the 404 | CARRIED |
| C1b | must_prove | the "listing filter" lists the real successful GET | :252 | a filter that prints nothing, and a runbook with no such filter (the placeholder key fails the comparison) | CARRIED |
| C1c | must_prove | the filter "selects by field position" | none | nothing. :247 checks the log line's sixth field, not how the runbook's filter selects. :252 passes any filter the one forged ordering (`status=200 method=GET page=about`) fails to fool, including a non-positional contiguous grep ` method=GET status=200 ` | UNCARRIED |
| C2a | must_prove | "the visitor's" record: matched by the visit's address | :291, :292 | an unanchored `ip=1.2.3.4` match picking up the 1.2.3.45 neighbour at +20 s; resolving the visit from the last pages line instead of by request_id | CARRIED |
| C2b | must_prove | "in-window" | :291, :292 | no time filter (the −60 s and +3600 s records are present); a local-time conversion without `-u` (control :262) | CARRIED |
| C2c | must_prove | "request.start record", not the rest of the request | :291, :292 | also printing the rid-match `request.end` record that :273 writes | CARRIED |
| C2d | must_prove | "exactly" that one record | :291, :292 | extra or duplicate Client records (list equality against a one-element list) | CARRIED |
| C2e | must_prove | "from real ClientLogFormatter output" | :283 (input via :217, :282) | hand-written Client lines that differ from what `server.ClientLogFormatter` renders | CARRIED |
| C2f | must_prove | "in … JSON" mode | :291 | a correlation that works only on text lines | CARRIED |
| C2g | must_prove | "and text modes" | :292 | a jq-only correlation that prints nothing for text lines | CARRIED |
| D1 | docstring | "list About visits by field position" (module, l.1) | none | same gap as C1c: a non-positional filter that beats this one token ordering passes | UNCARRIED |
| D2a | docstring | "find a visit's Client request.start record by its address" (l.1) | :291, :292 | the prefix-address neighbour | CARRIED |
| D2b | docstring | "and a time window after it" (l.1) | none | only windows reaching back 60 s or more are excluded. A ±30 s window passes, because no visitor-address record sits a few seconds before the visit | UNCARRIED |
| D3 | docstring | GET /about.html 200, HEAD /about 200, and GET /about/ 404 each write a pages line (l.3) | :243 | a missing or doubled pages line, or the forged request not answered 404 | CARRIED |
| D4 | docstring | "the forged one keeps `status=404` as its sixth field" (l.3) | :247 | forged tokens shifting the status field | CARRIED |
| D5 | docstring | "every runbook line that filters the pages log for GET and 200 prints exactly the real GET line" (l.3, l.234) | :252 | any filter line printing the forged, HEAD or extra lines | CARRIED |
| D6 | docstring | "not the one 60 s before, the one 1 h after, nor the one 20 s after from 1.2.3.45" (l.4, l.256) | :291, :292 | each named decoy being printed | CARRIED |
| D7 | docstring | "Its one `name=<…>` placeholder line gets the visit's request_id" (l.6) | :277 | a non-empty runbook with zero or several placeholders | CARRIED |
| D8 | docstring | "A missing section is an empty runbook, which fails at the claim assertions" (l.6) | :252, :291 | a missing section passing silently | CARRIED |
| D9 | docstring | "not … a HEAD /about 200" (l.234) | :252 | a filter on status alone, which also lists the method=HEAD line | CARRIED |
| D10 | docstring | "Given the visit's request_id" picks the right visit out of three (l.256, l.264) | :291, :292 | taking the last pages line (lands on the neighbour) or every line | CARRIED |
| D11 | docstring | "Skipped when nginx, bash, jq, awk or a `date` that reads `-u -d @<epoch.ms>` is missing" (l.6) | :111, :117, :123, :261 | running against a missing tool or a `date` without epoch.ms support | CARRIED |
| N1 | name | "forged user agent does not move fields" | :247 | the forged tokens shifting the positional fields | CARRIED |
| N2 | name | "runbook finds visit" | :291, :292 | resolving the wrong pages line (only the right visit's address and time yield rid-match) | CARRIED |
| N3 | name | "and client record" | :291, :292 | the wrong Client record or none | CARRIED |

CRITICAL
1. whole-claim (rules/testing.md) — tests/tmp/test_21_static_page_visit_logs_phase3.py:39
   FORGED_UA = "forger/1 status=200 method=GET page=about forger/1"
   C1 says the listing filter "selects by field position". The test uses only one forgery, with its tokens in an order the real format never uses (the format is `method=… status=…`, DEPLOYMENT.md:417). At :252 it checks only that each filter beats that one ordering. A non-positional filter such as `grep ' method=GET status=200 '` is caught by the selection at :249 and prints exactly `get[1]`, so it passes. That same filter would list a 404 whose user agent carries `method=GET status=200`. :247 checks the log line's sixth field, not that the runbook's filter reads that field. Nothing excludes a wrong implementation of "selects by field position", so C1c is UNCARRIED. To carry it, add a forged request whose user agent repeats the real field order, e.g. ` method=GET status=200 rt=0.000 `, and require the filter not to list it.

RECOMMENDATIONS
1. whole-claim (rules/testing.md) — tests/tmp/test_21_static_page_visit_logs_phase3.py:1
   D1 is UNCARRIED, for the same reason as Critical 1.
2. whole-claim (rules/testing.md) — tests/tmp/test_21_static_page_visit_logs_phase3.py:268
   D2b ("a time window after it") is UNCARRIED. The only earlier decoy is at −60 s, so a window open on both sides that reaches back less than 60 s passes. A visitor-address `request.start` a few seconds before the visit would carry "after".
3. bounds (rules/testing.md) — tests/tmp/test_21_static_page_visit_logs_phase3.py:268
   The window is tested at +10 s (inside), −60 s and +3600 s (outside) only. The edges are untested: a record at the visit's own millisecond, just before it, and at the window's closing bound and one past it.
4. normal-and-abnormal-paths (rules/testing.md) — tests/tmp/test_21_static_page_visit_logs_phase3.py:276
   Only a request_id present in the pages log is supplied. The correlation's expected failure mode is never tested: an id with no pages line, where an empty address and window could match every Client record.
5. name-as-sentence (rules/testing.md) — tests/tmp/test_21_static_page_visit_logs_phase3.py:233
   `test_forged_user_agent_does_not_move_fields` names the control at :247, not the claim at :252, which is that the runbook filter does not list the forged 404. If :252 fails, the runner's output reports a field-shift problem and does not say the runbook listed a forged visit. `test_runbook_finds_visit_and_client_record` (:255) states no "when".

OBSERVATIONS
none

NOT ASSESSED
1. `code_under_test` lists tests/active/test_static_page_visit_logs.py, which does not resolve (no file matches tests/**/test_static_page_visit_logs*.py). It was not read.
2. DEPLOYMENT.md has no `### Follow an About visit` heading. The Triage subsections run from `### Triage` (l.195) to `### Follow one request` (l.231), with no section between. So the runbook's listing filter and correlation commands could not be read, and C1c and C2 were judged against the test's assertions alone.
3. `fixtures_path` was not supplied. The test uses only pytest's built-in `tmp_path`, so no conftest was needed.

## 2026-10-02 - Step 7 - Phase 3 (Runbook commands) - self-check (audit round 2, send-back 0)

`tests/tmp/test_21_static_page_visit_logs_phase3.py`, surface `checkpoint`. Collection exit 0.

- C1 - tests/tmp/test_21_static_page_visit_logs_phase3.py:252. Each runbook line that names peertube-browser.pages.access.log and contains GET and 200 is run under bash against the real nginx pages log, and prints exactly [the real GET /about.html 200 line]. That log holds three lines: GET /about.html 200, HEAD /about 200, and a GET /about/ 404 whose UA carries both ` status=200 method=GET page=about ` and the real-order ` method=GET status=200 rt=0.000 ` (controls :243, :245, :247). - expected: {filter_line: [the GET /about.html 200 pages line]} for every such line. Observed with the plan's draft `awk '$1 == "page=about" && $5 == "method=GET" && $6 == "status=200"'`: PASSED. - excludes: A substring filter such as `grep ' method=GET ' | grep ' status=200 '` lists the forged 404 too (earlier probe). A contiguous real-order grep `grep '^page=about ' | grep ' method=GET status=200 '` and `grep -E '^page=about .* method=GET status=200 rt='` also list the forged 404, and both were observed FAILED at :252. A filter on status alone lists the HEAD line. A runbook with no such line reads {} against the placeholder key.
- C2 - tests/tmp/test_21_static_page_visit_logs_phase3.py:292 (JSON) and :293 (text). The pages log holds three visits: 198.51.100.9 at V−120 s, 1.2.3.4 at V with VISIT_ID, and 1.2.3.45 at V+15 s. The Client log is rendered by the real ClientLogFormatter and holds request.start records from 1.2.3.4 at V−5 s, V−60 s, V+10 s and V+3600 s, and from 1.2.3.45 at V+20 s, each followed by its request.end. The whole runbook, given VISIT_ID, prints exactly one Client record. - expected: [the formatter's rid-match (V+10 s) request.start], as a parsed dict in JSON and as the text line in text. Observed with the plan's draft: PASSED. - excludes: A window reaching back (±30 s) also prints the V−5 s record: observed FAILED at the C2 assertion. Conversion without -u: FAILED (earlier probe). `ip=$ip` without the trailing space, or jq without the .context.ip test, also prints the 1.2.3.45 record: FAILED. `tail -n 1` for the visit line lands on the neighbour: FAILED. Printing request.end as well gives two records and fails the list equality.

<exemptions>
none
</exemptions>

<items>
<item id="C1c">
<disposition>fixed</disposition>
<what>`FORGED_UA` (l.39) now also carries the real field order: `forger/1 status=200 method=GET page=about method=GET status=200 rt=0.000 forger/1`. The control at :245 now requires both ` status=200 method=GET page=about ` and ` method=GET status=200 rt=0.000 ` in the 404's pages line. The observed line was `… method=GET status=404 … ua="forger/1 status=200 method=GET page=about method=GET status=200 rt=0.000 forger/1"`. :252 (C1) now carries "selects by field position". It requires every GET/200 filter line to print exactly the real GET line, so any filter that matches a contiguous run of tokens instead of reading fields 5 and 6 lists this 404 and fails. Observed in probe tests/tmp/test_probe_21_p3c.py, using the plan's §8 draft inserted into a copy of DEPLOYMENT.md: `grep '^page=about ' | grep ' method=GET status=200 '` FAILED at :252, `grep -E '^page=about .* method=GET status=200 rt='` FAILED at :252, and the draft's `awk '$1 == "page=about" && $5 == "method=GET" && $6 == "status=200"'` PASSED.</what>
</item>
<item id="D1">
<disposition>fixed</disposition>
<what>This is the same fix as C1c. The forged UA now repeats the real `method=GET status=200 rt=` order, so :252 rejects a non-positional filter that the reversed ordering alone could not catch (probe: the contiguous grep and the anchored `.*` grep both failed, the positional awk passed). The module docstring l.3 and the test docstring now name both forged orderings.</what>
</item>
<item id="D2b">
<disposition>fixed</disposition>
<what>Added a visitor-address `request.start` decoy at V−5 s (`"just_before": (-5, VISIT_IP)`, l.269). :292 and :293 (C2) still require exactly the +10 s record, so any window that reaches back 5 s or more prints the decoy and fails. That includes every symmetric window, because a symmetric window has to reach back 10 s to cover the +10 s match. Probe: the draft with `from` moved to msec−30 (a ±30 s window) FAILED at the C2 assertion, and the draft opening at the visit PASSED. The docstrings at l.4 and l.256 now list "the one 5 s before" among the decoys.</what>
</item>
</items>

<findings_addressed>
Claim CRITICAL 1 (C1c, forged ordering only reversed): FORGED_UA now also carries ` method=GET status=200 rt=0.000 ` in the real field order. The control at :245 checks that both orderings reach the log space-delimited. :252 now fails a contiguous grep and an anchored `.*` grep, and both were observed failing in the probe while the positional awk passed.
Claim RECOMMENDATION 1 (D1): taken. It is closed by the same UA change, and the docstrings at l.3 and l.234 now describe both forged orderings.
Claim RECOMMENDATION 2 (D2b, "after"): taken. Added a visitor-address request.start at V−5 s. A ±30 s window was observed failing at the C2 assertion, and the draft that opens at the visit passed. The docstrings at l.4 and l.256 now name the decoy.
</findings_addressed>

<rows>
<row clause="C1">
<assertion>tests/tmp/test_21_static_page_visit_logs_phase3.py:252. Each runbook line that names peertube-browser.pages.access.log and contains GET and 200 is run under bash against the real nginx pages log, and prints exactly [the real GET /about.html 200 line]. That log holds three lines: GET /about.html 200, HEAD /about 200, and a GET /about/ 404 whose UA carries both ` status=200 method=GET page=about ` and the real-order ` method=GET status=200 rt=0.000 ` (controls :243, :245, :247).</assertion>
<expected>{filter_line: [the GET /about.html 200 pages line]} for every such line. Observed with the plan's draft `awk '$1 == "page=about" && $5 == "method=GET" && $6 == "status=200"'`: PASSED.</expected>
<wrong_implementation>A substring filter such as `grep ' method=GET ' | grep ' status=200 '` lists the forged 404 too (earlier probe). A contiguous real-order grep `grep '^page=about ' | grep ' method=GET status=200 '` and `grep -E '^page=about .* method=GET status=200 rt='` also list the forged 404, and both were observed FAILED at :252. A filter on status alone lists the HEAD line. A runbook with no such line reads {} against the placeholder key.</wrong_implementation>
</row>
<row clause="C2">
<assertion>tests/tmp/test_21_static_page_visit_logs_phase3.py:292 (JSON) and :293 (text). The pages log holds three visits: 198.51.100.9 at V−120 s, 1.2.3.4 at V with VISIT_ID, and 1.2.3.45 at V+15 s. The Client log is rendered by the real ClientLogFormatter and holds request.start records from 1.2.3.4 at V−5 s, V−60 s, V+10 s and V+3600 s, and from 1.2.3.45 at V+20 s, each followed by its request.end. The whole runbook, given VISIT_ID, prints exactly one Client record.</assertion>
<expected>[the formatter's rid-match (V+10 s) request.start], as a parsed dict in JSON and as the text line in text. Observed with the plan's draft: PASSED.</expected>
<wrong_implementation>A window reaching back (±30 s) also prints the V−5 s record: observed FAILED at the C2 assertion. Conversion without -u: FAILED (earlier probe). `ip=$ip` without the trailing space, or jq without the .context.ip test, also prints the 1.2.3.45 record: FAILED. `tail -n 1` for the visit line lands on the neighbour: FAILED. Printing request.end as well gives two records and fails the list equality.</wrong_implementation>
</row>
</rows>

<answers>
1. No. Every exclusion sits inside a positive list equality: :252 requires exactly the real GET line, and :292/:293 require exactly the rid-match record. Controls :243, :245, :247 and :283 prove the input exists. Delete the runbook section and both tests fail at :252 and :292.
2. No. The expected values come from real nginx output and from real ClientLogFormatter output. Deleting the draft's `$6 == "status=200"` test, or its `.ts >= $from`, turns :252 or :292 red.
3. No. C1 has three inputs, and the forged one now carries two token orderings. C2 has five candidate request.start records plus their request.end records, in two formats.
4. No. Only `sudo` (runs its command) and `journalctl` (cats a tmp file) are shimmed. Those are system tools, not modules this project owns. The formatter is the real one.
5. Yes, it collects. No imports or names changed. The edits are a constant, two assert operands, a dict entry and docstrings. The probe module loaded the checkpoint and ran both tests. records now holds 10 rendered lines, and the :283 control compares against len(records).
6. Yes, all observed. The new forged line was observed from nginx: `… method=GET status=404 … ua="forger/1 status=200 method=GET page=about method=GET status=200 rt=0.000 forger/1"`. The V−5 s decoy and the ±30 s mutant were observed through the probe. The probe file tests/tmp/test_probe_21_p3c.py is emptied (it collects nothing) and needs deleting, since I have no delete tool. The earlier tests/tmp/test_probe_21_p3.py also still needs deleting.
7. Yes. DEPLOYMENT.md still has no `### Follow an About visit`, so `_runbook()` returns []. The first test passes its controls (observed with the new UA) and fails at :252 on {} against the placeholder key. The second fails at :292 with [] against the rid-match record.
</answers>

Gate: satisfied

## 2026-10-02 - Step 7 - Phase 3 (Runbook commands) - red (audit round 2)

`tests/tmp/test_21_static_page_visit_logs_phase3.py` exited 1.

```
  tests/tmp/test_21_static_page_visit_logs_phase3.py  2 failed                               0.0s
  --------------------------------------------------
  total                                               2 failed                               0.7s wall, 1 lane

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

## 2026-10-02 - Step 7 - Phase 3 (Runbook commands) - audit (round 2)

- AUDIT: devsecops-test-shape-auditor - PASS
- AUDIT: devsecops-test-claim-auditor - PASS
- OUTSTANDING: nothing

### devsecops-test-shape-auditor

SHAPE AUDIT — VERDICT: PASS

CRITICAL
none

RECOMMENDATIONS
1. doc-lint-grep (rules/shape.md), sitting outside the entry's intent — tests/tmp/test_21_static_page_visit_logs_phase3.py:66
   assert SITE_LINE in text, f"{SITE_LINE} not in DEPLOYMENT.md"
   This line matches three of the entry's <how_to_spot> bullets: it calls `read_text()` on a `.md` file, asserts that a substring is present, and runs no parse before the assertion. It does not match the fourth: it is not checking anyone's choice of words. It checks that the anchor `_site_block()` uses to find the §6 nginx fence is still there. Line 141 (`assert old in server_text`) is the same kind of check: a safety precondition on the extracted fence before the test swaps in local paths and ports. Neither line carries C1 or C2. Both claims are asserted only on the output of the runbook commands when they are actually run. So I am not blocking on this. If someone retitles §6 or rewrites a swapped token, these lines will fail as a test error that has nothing to do with the runbook's behaviour. `shape.md` has no entry for an assertion that only locates something on the way to a behavioural check.

PREDICTED FAILURE
DEPLOYMENT.md has no `### Follow an About visit` heading (its only Triage subsection is `### Follow one request`), so `_runbook()` returns `[]`. `test_forged_user_agent_does_not_move_fields` should then fail at line 252: `{}` is compared with `{"<a runbook line filtering the pages log for GET and 200>": [<the real GET /about.html 200 pages line>]}`. `test_runbook_finds_visit_and_client_record` should fail at line 292: `got["json"] == []` is compared with the single rendered JSON request.start record for `rid-match`. Line 278's control lets the empty runbook through. If nginx, bash, jq, awk or a suitable `date` is missing, the affected test skips instead of failing.

NOT ASSESSED
1. `code_under_test` lists tests/active/test_static_page_visit_logs.py, but that path does not exist and no `tests/**/test_static_page_visit_logs*.py` file matched. Its role, if any, was not assessed. The test under audit does not import it.
2. The stub question was answered from the assertion form and the fixture design. For C1, the 404 line has forged `status=200 method=GET page=about` tokens and also the real-order ` method=GET status=200 rt=0.000 ` sequence, and there is a HEAD 200 control line, so a substring grep, a `$5`-only filter or a status-only filter would fail line 252. For C2, the distractors (−5 s, −60 s, +1 h, and +20 s from the neighbour 1.2.3.45), the EST5 TZ and the JSON/text pair mean that taking the last line, every line, an IP prefix match, a window without `-u`, or a symmetric window would all fail lines 292–293. I did not check this against an actual runbook, because none exists yet.

### devsecops-test-claim-auditor

CLAIM AUDIT — VERDICT: PASS

CLAUSE MAP  (25 clauses: 10 must_prove, 12 docstring, 3 name)
| id | source | clause | assertion | excludes | status |
|---|---|---|---|---|---|
| C1a | must_prove | "does not list a 404 About request whose user agent carries forged status=200, method=GET and page=about tokens as a successful GET" | :252 | A substring grep for ` status=200 ` or ` method=GET `. The control at :245 shows that the forged tokens reached the pages line space-delimited, so such a grep lists the 404 | CARRIED |
| C1b | must_prove | the "listing filter" lists the real successful GET | :252 | A filter that prints nothing. Also a runbook with no such filter: its `{}` fails against the placeholder key | CARRIED |
| C1c | must_prove | the filter "selects by field position" | :252 (control :245, :247) | A non-positional contiguous grep for the real field order ` method=GET status=200 rt=`. FORGED_UA (:39) now repeats that order inside the 404's user agent, so the grep lists the 404. :247 confirms field 6 is still `status=404` | CARRIED |
| C2a | must_prove | "the visitor's" record: matched by the visit's address | :292, :293 | An unanchored `ip=1.2.3.4` match picking up the 1.2.3.45 neighbour at +20 s. Also resolving the visit from the last pages line (:265, the neighbour at +15 s) instead of by request_id | CARRIED |
| C2b | must_prove | "in-window" | :292, :293 | No time filter: the −60 s and +3600 s records are present (:269). A local-time conversion without `-u` (control :262) | CARRIED |
| C2c | must_prove | "request.start record", not the rest of the request | :292, :293 | Also printing the `request.end` record with the same rid (rid-match) that :274 writes | CARRIED |
| C2d | must_prove | "exactly" that one record | :292, :293 | Extra or duplicate Client records: the comparison is list equality against a one-element list (:288) | CARRIED |
| C2e | must_prove | "from real ClientLogFormatter output" | :284 (input via :217, :283) | Hand-written Client lines that differ from what `server.ClientLogFormatter` renders | CARRIED |
| C2f | must_prove | "in … JSON" mode | :292 | A correlation that works only on text lines | CARRIED |
| C2g | must_prove | "and text modes" | :293 | A jq-only correlation that prints nothing for text lines | CARRIED |
| D1 | docstring | "list About visits by field position" (module, l.1) | :252 (control :245) | Same as C1c: the real-order contiguous grep lists the forged 404 | CARRIED |
| D2a | docstring | "find a visit's Client request.start record by its address" (l.1) | :292, :293 | The neighbour whose address has the visitor's as a prefix | CARRIED |
| D2b | docstring | "and a time window after it" (l.1) | :292, :293 | Any window reaching back 5 s or more. The `just_before` record at −5 s (:269) is printed by a symmetric ±30 s window, so that window fails | CARRIED |
| D3 | docstring | GET /about.html 200, HEAD /about 200 and GET /about/ 404 each write a pages line (l.3) | :243 | A missing or doubled pages line, or the forged request not being answered 404 | CARRIED |
| D4 | docstring | "the forged one keeps `status=404` as its sixth field" (l.3) | :247 | Forged tokens shifting the status field | CARRIED |
| D5 | docstring | "every runbook line that filters the pages log for GET and 200 prints exactly the real GET line" (l.3, l.234) | :252 | Any filter line that prints the forged line, the HEAD line or extra lines | CARRIED |
| D6 | docstring | "not the one 60 s before, the one 1 h after, nor the one 20 s after from 1.2.3.45" (l.4, l.256) | :292, :293 | Any of the named decoys being printed | CARRIED |
| D7 | docstring | "Its one `name=<…>` placeholder line gets the visit's request_id" (l.6) | :278 | A non-empty runbook with zero placeholders or several | CARRIED |
| D8 | docstring | "A missing section is an empty runbook, which fails at the claim assertions" (l.6) | :252, :292 | A missing section passing silently | CARRIED |
| D9 | docstring | "not … a HEAD /about 200" (l.234) | :252 | A filter on status alone, which also lists the `method=HEAD` line | CARRIED |
| D10 | docstring | "Given the visit's request_id" picks the right visit out of three (l.256, l.264) | :292, :293 | Taking the last pages line (it lands on the neighbour) or every line | CARRIED |
| D11 | docstring | "Skipped when nginx, bash, jq, awk or a `date` that reads `-u -d @<epoch.ms>` is missing" (l.6) | :111, :117, :123, :261 | Running against a missing tool, or against a `date` without epoch.ms support | CARRIED |
| N1 | name | "forged user agent does not move fields" | :247 | The forged tokens shifting the positional fields | CARRIED |
| N2 | name | "runbook finds visit" | :292, :293 | Resolving the wrong pages line: only the right visit's address and time yield rid-match | CARRIED |
| N3 | name | "and client record" | :292, :293 | The wrong Client record, or none | CARRIED |

CRITICAL
none

RECOMMENDATIONS
none

OBSERVATIONS
1. whole-claim (rules/testing.md): tests/tmp/test_21_static_page_visit_logs_phase3.py:39, :252
   C1c and D1 are now CARRIED, but they exclude only some non-positional filters, not every one.
   - FORGED_UA puts `page=about` in front of the repeated `method=GET status=200 rt=0.000`.
   - So a grep anchored on the preceding key, such as `grep 'ip=[^ ]* method=GET status=200 '`, does not match the 404 and passes :252. That grep still does not select by field position.
   - Forging the whole field prefix in the user agent would leave only line-anchored or field-number filters able to pass. An example is ` ip=1.2.3.4 method=GET status=200 rt=0.000 request_id=… `.
   - The round-one gap (the contiguous real-order grep) is closed by an added assertion input, not by narrowing the prose.
2. whole-claim (rules/testing.md): tests/tmp/test_21_static_page_visit_logs_phase3.py:4, :256, :268–269
   The docstring has grown a clause that no ledger row names: "not the one 5 s before". It is carried. The `just_before` record at −5 s (:269) is excluded by :292 and :293. This is the same input that now carries D2b.

NOT ASSESSED
1. `code_under_test` lists DEPLOYMENT.md's "Follow an About visit" heading and its fenced bash blocks. DEPLOYMENT.md as read has no `### Follow an About visit` heading; the Triage section goes from "Follow one request" (l.231) to "## 3) Build the client". So I judged what each assertion excludes from the test and the §6 `peertube_browser_pages` log format (DEPLOYMENT.md:417). I did not check it against the runbook's actual commands.
2. `code_under_test` lists tests/active/test_static_page_visit_logs.py, which does not resolve. The test under audit does not import it.

## 2026-10-02 - Step 7 - Phase 3 (Runbook commands) - checkpoint outcome (run 1)

`tests/tmp/test_21_static_page_visit_logs_phase3.py` exited 0 after the phase landed.

<changes>
### DEPLOYMENT.md
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
</changes>

<inner_tests>
none
</inner_tests>

<unanticipated>
tests/tmp/probe_about_runbook_date.py — the probe file I used to observe `date` and the runbook's behaviour. It is empty now but still exists, because I had no tool to delete it; please remove it.
</unanticipated>

<awaiting_operator>
none
</awaiting_operator>

```
  tests/tmp/test_21_static_page_visit_logs_phase3.py  2 passed                               0.0s
  --------------------------------------------------
  total                                               2 passed                               0.7s wall, 1 lane

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

## 2026-10-02 - Step 8 - clause accounting

- P1C1 - carried - rests on: the last audit of `tests/tmp/test_21_static_page_visit_logs_phase1.py`
- P1C2 - carried - rests on: the last audit of `tests/tmp/test_21_static_page_visit_logs_phase1.py`
- P2C1 - carried - rests on: the last audit of `tests/tmp/test_21_static_page_visit_logs_phase2.py`
- P2C2 - carried - rests on: the last audit of `tests/tmp/test_21_static_page_visit_logs_phase2.py`
- P3C1 - carried - rests on: the last audit of `tests/tmp/test_21_static_page_visit_logs_phase3.py`
- P3C2 - carried - rests on: the last audit of `tests/tmp/test_21_static_page_visit_logs_phase3.py`

## 2026-10-02 - Step 8 - refactor pass

<refactors>
none — DEPLOYMENT.md was read in full over the changed regions (the §6 site block at lines 433–471 and "Follow an About visit" at lines 231–247), and nothing in them could be changed without breaking a gated check or adding new behaviour.
</refactors>

<left_out>
Merging the three About locations (`= /about`, `= /about/`, `= /about.html`) into one regex location in DEPLOYMENT.md §6: left out because the gated phase-1 checkpoint parses exact locations and needs exactly one `try_files` in each, so merging them would break that check rather than refactor the code. The repetition is already documented by the rat-tail comment and the access_log comment above the locations.
Removing the repeated `set $static_page` and both `access_log` lines from each About location, by using an http-level `map $uri $static_page` plus a server-level `access_log … peertube_browser_pages if=$static_page;`: left out because I could not be sure of it without a run. It adds a brace-holding `map {}` block outside `server {}` that the checkpoint's `_site_block()`/`_statements()` parsing may not handle. It also moves the About URL set into a second place that the rat-tail mapping comparison does not check, and I have not seen how nginx handles the pages log for non-About routes under `if=`.
Not refactors, but for whoever owns the next step: (1) `tests/active/test_static_page_visit_logs.py`, which the rat-tail comment names, does not exist in the worktree yet; promoting the gated checkpoints is up to the workflow. (2) `.un/skills/devsecops/config.json` has no `test_static_page_visit_logs.py` group. It should list DEPLOYMENT.md, client/frontend/vite.config.ts, client/frontend/dev-pages/about.template.html and client/backend/server.py (the source of ClientLogFormatter). (3) Earlier steps left probe files in tests/tmp/ that I have no tool to delete: probe_pages_log.py and probe_about_runbook_date.py (emptied), and probe_21_pages_log.py, probe_21_about_block.py, test_probe_21_p1_nginx.py, test_probe_21_p3.py and test_probe_21_p3c.py. (4) The step's "What the pass is measured against" section came through as the literal placeholder `{rat_tail_rules}`, so the pass was checked against the role's rat-tail rule only.
</left_out>

<needs_fresh_red>
none
</needs_fresh_red>

<observation>
From reading the code only, without a run: the About site block and the runbook are already the smallest form the gated checkpoints allow, so this pass changed no file.
</observation>

## 2026-10-02 - Step 8 - suite comparison (attempt 1)

`--compare` exited 0.

```
selected 1 of 46 test groups (45 unchanged):
  test_search_fusion.py — no map entry
  test_search_fusion.py  10 passed                              1.9s
  ---------------------
  total                  10 passed                              2.0s wall, 1 lane

nothing moved against the previous record

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

## 2026-10-02 - Step 9 - document triage

- [ ] `DEPLOYMENT.md` - The §6 site block and the Triage "Follow an About visit" commands were delivered and are correct. The prose around them is now incomplete or wrong. Edit the prose only. The block and the fenced runbook commands are gated and must not change.
- **§3 "Build the client" (lines 318-322).** "nginx serves `dist/` through `try_files`, and a page missing from the document root is a 404" now holds for every page except `about`. Say that About is built under `dist/dev-pages/`: `about.html` when the local override exists, otherwise `about.template.html`. Say that it is reached at `/about`, `/about/` and `/about.html` only through the §6 About locations. Adding another informational page means adding one more exact location of the same shape.
- **§6 prose after the block (line 504).** "`log_format` stays outside `server {}`" must cover the two formats, `peertube_browser` and `peertube_browser_pages`. Add the following, beside the `proxy_set_header` repetition note:
  - The three exact About locations serve `/dev-pages/about.html`, then `/dev-pages/about.template.html`, then 404, in vite's override-then-template order.
  - Each one sets `$static_page` and lists both `access_log` lines, because a location-level `access_log` replaces the server's.
  - They declare no `add_header`, so they inherit the server CSP, which is About's only CSP (the template has no meta CSP). Adding an `add_header` there would drop it.
  - The new file `/var/log/nginx/peertube-browser.pages.access.log` is covered by the Debian/Ubuntu `/var/log/nginx/*.log` logrotate rule.
  - Direct requests to `/dev-pages/about*.html` go through `location /` and write no pages line.
  - Existing hosts merge in the new `log_format` line and the three locations, then run `nginx -t` and reload. They must not overwrite a certbot-edited file.
- **§6 Verify (lines 516-522).**
  - Add `curl -I http://localhost/about`: expect 200 with a `Content-Security-Policy` header. `/about/` and `/about.html` can be listed too.
  - Add a `sudo tail` of the pages log. The `curl -I` line logs as `method=HEAD`.
  - Add a hint: a 404 on `/about` means §6 was not re-applied or the document root has no `dev-pages/about*.html`.
- **§6 TLS (lines 566-574).** Warn that `certbot --nginx` edits the site file in place, so re-applying §6 by copying the whole block over it drops TLS. Either merge the changes in or re-run certbot afterwards.
- **Triage "Follow an About visit" (lines 231-248).** The requirements' runbook is only partly there. Add the following, in prose and one extra command:
  - The step that finds the visit's line in the main access log by its id: `sudo grep "request_id=$id" /var/log/nginx/peertube-browser.access.log`.
  - Caveat: the id is not shared with any app record, so correlation is probabilistic. NAT and shared IPs make it so.
  - Caveat: the Client's `ip` is resolved through `X-Forwarded-For`/`TRUSTED_PROXIES`, so it equals nginx's `$remote_addr` only when nginx is the sole proxy. Behind a CDN or load balancer, `$remote_addr` is that layer's address.
  - Caveat: the nginx `time=` field is server-local with an offset, while app `ts` is UTC. The `from`/`to` lines normalise from `ts=` (`$msec`) for that reason.
  - Caveat: in text mode, the `ip` field and the unquoted `user_agent` make the match weaker than the JSON match.
  - Caveat: bots and crawlers appear in the log, and the user-agent is the only filter. Name issue 18's beacon endpoint (`docs/project/issues/18-about-outbound-click-tracking.md`) as the upgrade path for counting human visits.
- **Triage "What each log is for" (lines 261-263).** Add a bullet for the pages log: one line per About request, with page marker, ms timestamp, IP, method, status, request time, request id, URI, incoming `X-Request-ID` and user agent, joined to its main-log line by `request_id`.
- **§2 `LOG_FORMAT` paragraph (line 116), optional.** Point to "Follow an About visit" next to the existing "Follow one request" pointer.
- **§7 Verify page list (lines 603-606), optional.** Add `/about.html`, which every page's nav links to and which 404ed in prod before this build.
- **Triage table, optional.** Add a row: `/about` returns 404 → re-apply §6, or run `scripts/sync.sh` so `dev-pages/about*.html` is in the document root.
- [ ] `client/frontend/README.md` - "Local About Overrides" (lines 36-39) names the source files but not how prod serves them. Add that prod nginx serves whichever file was built at `/about`, `/about/` and `/about.html`, the `dev-pages/about.html` override first and the template otherwise (`DEPLOYMENT.md` §6). Add that an override must use root-absolute URLs because the same file is served at `/about/`, and that it gets only the server's CSP header.
- [ ] `docs/project/issues/21-static-page-visit-logs.md` - Still `Status: enhancement, needs-triage` with an empty `## Comments`. At completion:
- set `Status: enhancement, complete`;
- add a delivery comment naming `docs/project/plans/22-21-static-page-visit-logs.md`. It should say what was delivered: About served at `/about`, `/about/` and `/about.html` in prod via §6, the `peertube_browser_pages` log at `/var/log/nginx/peertube-browser.pages.access.log`, and the "Follow an About visit" runbook. It should also say what was scoped out: pages other than About, and the beacon, which is deferred to issue 18;
- move the file to `docs/project/issues/archive/` per `docs/project/issue-tracker.md`, leaving no duplicate in `issues/`.
- [ ] `docs/project/issues/plan.md` - - **Lane 5c (line 98).** It lists 21's files as "nginx docs, the About template, one Client endpoint". For 21 that is only the nginx docs (`DEPLOYMENT.md`); the template and the endpoint belong to 18. Mark 21 delivered with the plan path.
- **P5 row (line 42).** "19 and part of 20 are already delivered" is stale. 19, 20 and 21 are delivered, and 18 remains.
- [ ] `docs/project/issues/18-about-outbound-click-tracking.md` - Add a comment. Issue 21's runbook names 18's beacon endpoint as the upgrade path for pageview counting, so 18's endpoint design should allow a page-view event type as well as outbound clicks. Line 14 plans a click-specific `/api/analytics/outbound-click`. 21 adds no endpoint, so the two do not duplicate each other.

Out of scope:
- [ ] `docs/project/roadmap.md` - No change needed. The Delivered list has no bullet for the sibling logging issues 19 and 20, so the convention does not call for one for 21. The Logging chain line (`19` -> `20` -> `21`) is still accurate.
- [ ] `CONTEXT.md` - No change needed. The "Request id" entry is still true: About lines carry nginx's `$request_id`, but no app record shares it. The scope is About only, so no new glossary term is warranted.
- [ ] `client/README.md` - No change needed. Its `TRUSTED_PROXIES` and `request.start` statements, which the runbook relies on, are unchanged and still true, and it makes no claim about About or the nginx logs.
- [ ] `docs/project/adr/0002-trusted-proxy-client-address.md` - No change needed. The runbook's IP caveat restates this ADR's resolution rule and does not change it. The build touches neither the Client backend nor the proxy headers.
- [ ] `docs/project/adr/0004-cors-opt-in-by-origin.md` - No change needed. Prod nginx still serves everything on one origin. The About locations add no headers and no cross-origin path.
- [ ] `docs/project/adr/0009-engine-blue-green-through-nginx-upstream-snippet.md` - No change needed. Only the public site file changed. The upstream snippet and the 7079 listener are untouched, and §6 line 526 ("leave the public site file above as it is, since nothing here changes it") is still accurate.

ADR conflicts: none

## 2026-10-02 - Step 9 - Update documentation

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

**Updated but not named by the Step 3 inventory.** none

**Other files that had to be touched.** - while updating `docs/project/issues/21-static-page-visit-logs.md`: docs/project/issues/archive/21-static-page-visit-logs.md: new file. `docs/project/issue-tracker.md` says a delivered issue moves to `issues/archive/`, so this is the moved copy of the checklist file. The original `docs/project/issues/21-static-page-visit-logs.md` must be deleted (git rm) so only one copy remains; I have no tool that deletes files.
- while updating `docs/project/issues/plan.md`: none. One thing to check: `docs/project/issues/20-request-lifecycle-logs.md` (`needs-triage`) is still in `issues/` next to its `complete` copy in `issues/archive/`. That looks like a duplicate left over from the issue-20 build. I didn't touch it.

**ADR conflicts.** none

### `DEPLOYMENT.md`

<changes>
I updated the prose in `DEPLOYMENT.md` to match what the build delivered: how About is served, the pages log, the About runbook caveats, and checks and warnings for operators. I didn't change the §6 nginx site block or the fenced runbook commands, since the tests check both.

I checked the claims against the code: `vite.config.ts` (`aboutSourcePath`, `rewriteToAbout`), `dev-pages/` (no `<meta>` CSP), and the Client's `request.start` record and text-mode output in `client/backend/server.py`.

- **§2 `LOG_FORMAT` paragraph:** added a pointer to "Follow an About visit" next to the "Follow one request" pointer.
- **§3 Build the client:** About is built under `dist/dev-pages/`, as `about.html` when the local override exists and `about.template.html` otherwise, never as `dist/about.html`. It is reached at `/about`, `/about/` and `/about.html` only through the §6 About locations. Adding another informational page means one more exact location of the same shape.
- **§6 prose after the block:**
  - The `log_format` note now covers both `peertube_browser` and `peertube_browser_pages`.
  - A new paragraph on the About locations covers:
    - the order they serve files in: `dev-pages/about.html`, then `dev-pages/about.template.html`, then 404, the same choice vite makes;
    - why each one sets `$static_page` and repeats the main `access_log` line;
    - the CSP: they inherit the server's header, which is About's only CSP, and an `add_header` in one of them would drop it;
    - log rotation: the Debian/Ubuntu `/var/log/nginx/*.log` rule covers the new file;
    - direct `/dev-pages/about*.html` requests go through `location /` and write no pages line.
  - A note for hosts that already run the site: merge the new lines in rather than overwriting the file certbot edited, then `nginx -t` and reload.
- **§6 Verify:** added `curl -I http://localhost/about` (expect 200 with the CSP header) and a `sudo tail` of the pages log (expect a `method=HEAD` line). Added a hint for what a 404 on `/about` means.
- **§6 TLS:** `certbot --nginx` edits the site file in place, so copying the whole block over it drops TLS. Merge the changes in, or re-run certbot afterwards.
- **Triage table:** a new row for `/about*` answering 404, pointing to merging the §6 About locations or running `scripts/sync.sh`.
- **Follow an About visit:**
  - The main-log lookup by request id is written inline in the prose (`sudo grep "request_id=$id" …access.log`) rather than as a new fenced block, so the tested blocks stay unchanged.
  - A Caveats list covers:
    - the request id is not shared with app records, so matching by IP and time is probabilistic under NAT or shared addresses;
    - the Client's `ip` comes from `X-Forwarded-For`/`TRUSTED_PROXIES`, so it equals `$remote_addr` only when nginx is the sole proxy;
    - the pages log's `time=` is local time with an offset while app `ts` is UTC, which is why the window is built from `ts=`;
    - the text-mode match goes by field position over unquoted values, so it is looser than the JSON match;
    - bots and crawlers appear in the log, and issue 18's beacon endpoint is the way to count human visits.
- **What each log is for:** a bullet for the pages log listing its fields, joined to the main log by `request_id`.
- **§7 Verify:** added `/about.html` to the list of pages to open.
</changes>

<not_on_checklist>
none
</not_on_checklist>

### `client/frontend/README.md`

<changes>
"Local About Overrides" now says how prod serves the built About page, that overrides need root-absolute URLs, and which CSP applies.

- New bullet: the build puts whichever source it used under `dist/dev-pages/`. Prod nginx serves it at `/about`, `/about/` and `/about.html`, trying the `dev-pages/about.html` override first and the template second. For the locations and the visit log it points to `DEPLOYMENT.md` sections 3 and 6 rather than repeating them.
- New bullet: an override must use root-absolute URLs. The same file is also served at `/about/`, so a relative URL would resolve under `/about/`.
- New bullet: the About page's only CSP is the server's `Content-Security-Policy` header, so an override must work under it.

Checked against the code:
- In `vite.config.ts`, `aboutSourcePath` and `rewriteToAbout` give the override-then-template order and the three URLs.
- The `DEPLOYMENT.md` §6 About locations serve those files and have no `add_header`. §519 says the template has no meta CSP.
- The template's own links are root-absolute, for example `/favicon.png` and `/src/videos.css`.
</changes>

<not_on_checklist>
none
</not_on_checklist>

### `docs/project/issues/21-static-page-visit-logs.md`

<changes>
Issue 21 marked delivered and copied to `docs/project/issues/archive/21-static-page-visit-logs.md` with a delivery comment. **The original at `docs/project/issues/21-static-page-visit-logs.md` still exists and needs deleting.** I have no tool that deletes files, so until it goes there are two copies.

- **Status:** changed `Status: enhancement, needs-triage` to `Status: enhancement, complete`.
- **Delivery comment under `## Comments`:** a single bullet, in the same style as the archived issue 20. It covers:
  - It names `docs/project/plans/22-21-static-page-visit-logs.md` and says the delivery is nginx config and docs only.
  - Prod serves About at `/about`, `/about/` and `/about.html` through three exact locations in `DEPLOYMENT.md` §6. Before this, About returned 404 in prod.
  - Each About request writes one line to `/var/log/nginx/peertube-browser.pages.access.log` in the `peertube_browser_pages` format, carrying the `page=about` marker and the incoming `X-Request-ID` (`-` when absent). It also writes its usual main-log line, and the two are joined by `$request_id`.
  - The "Follow an About visit" Triage runbook matches a visit to the visitor's records by client IP and a time window. No request id is shared with app records, so the match is probabilistic. For fields, commands and caveats the comment points to `DEPLOYMENT.md` instead of repeating them.
  - Left out of this build: other pages (their API calls already show in app logs) and the pageview beacon, which the runbook names as the upgrade path using issue 18's beacon endpoint.
- **Checked against `DEPLOYMENT.md`:** the log format (line 449), the three About locations (lines 467–483) and the "Follow an About visit" heading (line 232).
- **Unchanged:** the rest of the issue body (Problem, Proposed solution, Validation, Related).
</changes>

<not_on_checklist>
docs/project/issues/archive/21-static-page-visit-logs.md: new file. `docs/project/issue-tracker.md` says a delivered issue moves to `issues/archive/`, so this is the moved copy of the checklist file. The original `docs/project/issues/21-static-page-visit-logs.md` must be deleted (git rm) so only one copy remains; I have no tool that deletes files.
</not_on_checklist>

### `docs/project/issues/plan.md`

<changes>
plan.md: P5 row now says 19, 20 and 21 are delivered and 18 remains; lane 5c splits the file list between 21 and 18 and marks 21 delivered with its plan path.

- **P5 row (line 42).** "19 and part of 20 are already delivered (see triage)" now reads "19, 20 and 21 are delivered, and 18 remains." I checked this against the tree: `docs/project/issues/archive/{19,20,21}-*.md` all carry `Status: enhancement, complete`, and 18 is still `needs-triage` in `issues/`.
- **Lane 5c (line 98).** The main-files cell now reads "21: the nginx docs (`DEPLOYMENT.md`). 18: the About template, one Client endpoint". 21 delivered no template or endpoint change. The depends-on cell keeps `20` and adds "21 delivered, see `docs/project/plans/22-21-static-page-visit-logs.md`". That plan file exists at that path.

I left some text alone because it was outside this item's checklist. These parts of the file are still stale for 20: lane 4c's "(19 delivered)", which doesn't mark 20 delivered, and the Triage recommendation "**20 is partly delivered.**"
</changes>

<not_on_checklist>
none. One thing to check: `docs/project/issues/20-request-lifecycle-logs.md` (`needs-triage`) is still in `issues/` next to its `complete` copy in `issues/archive/`. That looks like a duplicate left over from the issue-20 build. I didn't touch it.
</not_on_checklist>

### `docs/project/issues/18-about-outbound-click-tracking.md`

<changes>
Added a comment to issue 18: issue 21 names this issue's beacon endpoint as the way to count pageviews, so the endpoint should also accept a page-view event type.

- I added one comment under `## Comments`, headed "Issue 21 names this endpoint as its pageview upgrade path". It follows the `### heading` plus paragraph format the other issues use.
- The comment says issue 21 (`docs/project/issues/archive/21-static-page-visit-logs.md`) logs About visits in nginx and adds no endpoint, so the two issues don't overlap.
- It cites the "Follow an About visit" runbook in `DEPLOYMENT.md`: bots and crawlers show up in the nginx pages log, and counting human visits would need a pageview beacon sent to this issue's endpoint. I checked `DEPLOYMENT.md` line 258, which points to this issue's beacon endpoint.
- It notes that the endpoint planned above only handles clicks (`/api/analytics/outbound-click`, `outbound_click_events`). The design should also accept a page-view event type so pageviews don't need a second endpoint.
- `Status`, the proposed solution, Validation and Related are unchanged. This issue isn't delivered, and the Related line still correctly separates event analytics from request-log visibility.
</changes>

<not_on_checklist>
none
</not_on_checklist>

## 2026-10-02 - Step 10 - stopped

Harvest tests did not complete. The entries above carry what the step established before it stopped; the gate it failed is the last of them.

