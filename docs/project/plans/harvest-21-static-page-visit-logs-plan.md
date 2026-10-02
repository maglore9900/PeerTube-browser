# Harvest - 21-static-page-visit-logs

Build plan: `docs/project/plans/22-21-static-page-visit-logs.md` (merged to main in 5487831). The build's own Step 10 stopped before it started, so this harvest is being run by hand under `.un/skills/devsecops/workflows/harvest.md`.

## Step 1 - resolved paths and scope

- project_dir: `/home/enduser/code/PeerTube-browser`
- active: `tests/active`
- working: `tests/tmp`
- plans: `docs/project/plans`
- delete_me: `delete_me`
- archive: `tests/archive`
- record: `tests/last_test_validation.json`, snapshotted to `tests/last_test_validation.json.preharvest`

The bootstrap gate is clear: `defaulted` is empty and `conflicts` is empty.

Scope: the build's three gated checkpoints.

- `tests/tmp/test_21_static_page_visit_logs_phase1.py`
- `tests/tmp/test_21_static_page_visit_logs_phase2.py`
- `tests/tmp/test_21_static_page_visit_logs_phase3.py`

Build-21 scratch files that also go to `delete_me/` at Step 7. They are probes with no tests to harvest, and several are empty:
`probe_21_about_block.py`, `probe_21_pages_log.py`, `probe_about_runbook_date.py`, `probe_pages_log.py`, `probe_phase3_runbook.py`, `test_probe_21_p1_nginx.py`, `test_probe_21_p3.py`, `test_probe_21_p3c.py`.

## Step 2 - inventory

### tests/tmp/test_21_static_page_visit_logs_phase1.py
Drives: the §6 nginx site block in `DEPLOYMENT.md`, run in a real nginx, and `client/frontend/vite.config.ts` (rewriteToAbout, aboutSourcePath). Also reads `client/frontend/dev-pages/about.template.html`.

Tests:
- `test_about_urls_serve_override_then_template_then_404_with_csp` (4 params: override-and-template, override-only, template-only, neither)
- `test_about_mapping_matches_vite`

Helpers: `_site_block`, `_statements`, `_csp`, `_free_port`, `_write_config`, `_nginx_args`, `_require_unprivileged_nginx`, `_serving`, `_answer`.
Constants: `SITE_LINE`, `SWAPS` (3 swaps), `ABOUT_URLS`, `NOT_ABOUT_URLS`, `OVERRIDE`, `INDEX`.

### tests/tmp/test_21_static_page_visit_logs_phase2.py
Drives: the same §6 block, through its `peertube_browser_pages` log_format and the About `access_log` lines.

Tests:
- `test_each_about_request_writes_one_pages_line_and_one_main_line_with_same_request_id` (2 params: template-200, no-files-404)
- `test_other_routes_write_no_pages_line`

Helpers: the same harness as phase 1 plus `_configure`, `_lines`, `_request` (status, main lines, pages lines), `_main_request`, `_record`.
Constants: `SWAPS` (4 swaps, adding the upstream port), `OTHER_ROUTES`, `SENT_ID`, `AGENT`, `PAGES_HEAD`.

### tests/tmp/test_21_static_page_visit_logs_phase3.py
Drives: the "Follow an About visit" bash fences in `DEPLOYMENT.md`, against a real nginx pages log and Client records rendered by `ClientLogFormatter` in `client/backend/server.py`.

Tests:
- `test_forged_user_agent_does_not_move_fields`
- `test_runbook_finds_visit_and_client_record`

Helpers: the phase-2 harness (its `_request` returns status and pages lines only) plus `_runbook`, `_require_tools`, `_bash`, `_pages_line`, `_client_lines`, `_client_record`, `_FORMAT_CHILD`.
Constants: `RUNBOOK_HEADING`, `TOOLS`, `FORGED_UA`, `LOCAL_TZ`, `VISIT_*`, `NEIGHBOUR_IP`, `TS_HEAD`.

All three files collected and passed in the build: Step 8 suite comparison, record of 22-21. nginx 1.28.3, bash, jq, awk and date are present on this host, so none of the tests skip here.

## Step 3 - classification

No `tests/active` file asserts anything about the About locations, the pages log or the runbook. A grep for about, pages.access and DEPLOYMENT.md in `tests/active` finds nothing relevant. `test_install_engine_service.py` parses the §6 block only for its upstream/listen statements. Subject file: `tests/active/test_static_page_visit_logs.py`. It does not exist yet, and it is the name the build plan (§12) and the `rat-tail:` comment in `DEPLOYMENT.md` §6 already use.

- `test_about_urls_serve_override_then_template_then_404_with_csp`: **DURABLE**. It is the only test of About serving (override, then template, then 404, with the CSP).
- `test_about_mapping_matches_vite`: **DURABLE**. It is the only check that the nginx block mirrors vite's About mapping, and the rat-tail comment names it.
- `test_each_about_request_writes_one_pages_line_and_one_main_line_with_same_request_id`: **DURABLE**. It is the only test of the pages-log format and of the main-log line being kept.
- `test_other_routes_write_no_pages_line`: **DURABLE**. It is the only test that the pages log is About-only.
- `test_forged_user_agent_does_not_move_fields`: **DURABLE**. It is the only test of the runbook's positional filter against forged tokens.
- `test_runbook_finds_visit_and_client_record`: **DURABLE**. It is the only test of the runbook's correlation window against real ClientLogFormatter output.

Counts: 6 DURABLE, 0 REPLACES, 0 COMBINE, 0 REDUNDANT, 0 SPENT.

The three files share one nginx harness, so they merge into one subject file with one copy of each helper. Phase 2's `SWAPS`, which adds the upstream swap, and phase 2's `_request`, which returns status, main lines and pages lines, are the shared forms. Phase 3's call sites take `[0]` and `[2]` from it.

Group map: add `test_static_page_visit_logs.py` with `DEPLOYMENT.md`, `client/frontend/vite.config.ts`, `client/frontend/dev-pages/about.template.html` and `client/backend/server.py`.

## Step 4 - approval

The operator approved the plan as presented, including moving the 8 build-21 probes to `delete_me/`.

## Step 5 - applied

- Created `tests/active/test_static_page_visit_logs.py` with all 6 tests (10 cases) and one copy of the shared harness. Phase 1's test now builds its run through `_configure`, which adds the upstream swap and runs the same `nginx -t` check. Phase 3's tests read the pages lines as `[2]` of the shared `_request`. Clause labels (`C1`, `C2`) and phase references are gone from comments and docstrings; `_pages_line` now cites the pages-log test instead of "phase 2".
- Added `test_static_page_visit_logs.py` to `test_groups` in `.un/skills/devsecops/config.json`, naming `DEPLOYMENT.md`, `client/frontend/vite.config.ts`, `client/frontend/dev-pages/about.template.html` and `client/backend/server.py`.
- `--audit-map` exited 0 with no MISSING finding for the new group.
- Before any mutation, the new file ran 10 passed with none skipped (nginx 1.28.3 is on this host).

## Step 6 - mutations

Every mutation was made to a `.bak-h21-mN` copy's original, restored with `cp`, checked with `diff` (clean), and the copy moved to `delete_me/`. The test went green again after each restore.

- `test_about_urls_serve_override_then_template_then_404_with_csp`. Rule: the override is served before the template. Mutation: `location = /about.html` try_files lists the template first. Felled: the 200 comparison in `[override-and-template]`, which got Content-Length 1201 where 49 was expected.
- `test_about_mapping_matches_vite`. Rule: the exact locations are vite's About URLs. Mutation: `location = /about/` renamed to `/about-us/`. Felled: `sorted(url for url, _ in exact) == sorted(urls)` ('/about-us/' != '/about.html').
- `test_each_about_request_writes_one_pages_line_and_one_main_line_with_same_request_id`. Rule: About requests keep their main-log line. Mutation: the main `access_log` was removed from `location = /about`. Felled: the per-request count assertion in both params, `(200, 0, 1)` where `(200, 1, 1)` was expected.
- `test_other_routes_write_no_pages_line`. Rule: only About writes the pages log. Mutation: `location /` gained both access_log lines. Felled: the route comparison; /, /index.html and /dev-pages/* each wrote 1 pages line.
- `test_forged_user_agent_does_not_move_fields`. Rule: the runbook lists by field position. Mutation: the listing awk was replaced by `grep ' method=GET status=200 '`. Felled: the filter-output assertion, which listed the forged 404 line.
- `test_runbook_finds_visit_and_client_record`. Rule: the window is built in UTC. Mutation: `-u` was dropped from the `from`/`to` date lines. Felled: `got["json"] == expected["json"]`, which found no record.

## Step 7 - disposed

Moved to `delete_me/`, with no name collisions:
`test_21_static_page_visit_logs_phase1.py`, `test_21_static_page_visit_logs_phase2.py`, `test_21_static_page_visit_logs_phase3.py`, `probe_21_about_block.py`, `probe_21_pages_log.py`, `probe_about_runbook_date.py`, `probe_pages_log.py`, `probe_phase3_runbook.py`, `test_probe_21_p1_nginx.py`, `test_probe_21_p3.py`, `test_probe_21_p3c.py`, and the six `DEPLOYMENT.md.bak-h21-m1..m6` copies.

## Step 8 - suite

The snapshot was restored, then `--compare` ran with no tier and exited 0. It selected `test_static_page_visit_logs.py` (no record) and `test_search_fusion.py` (unmapped, always runs), and both passed. Moved against the pre-harvest record: 10 tests appeared, all from the new file, and nothing departed, turned red or stopped being red. The suite now stands at 670 passed (660 before, plus 10).
